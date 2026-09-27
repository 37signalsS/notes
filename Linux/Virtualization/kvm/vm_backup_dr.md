# Резервное копирование и восстановление ВМ (KVM)

В данном файле описываются стратегии бэкапа и disaster recovery для виртуальных машин KVM/QEMU: методы создания резервных копий, инкрементальное копирование, восстановление на уровне образов и файлов, тестирование бэкапов. Концепции HA описаны в [Высокая доступность KVM](./kvm_ha.md), а snapshot'ы — в [Основных концепциях образов](../vm_images/basic_concepts.md).

## Определения

**RPO (Recovery Point Objective)** — максимальный объем данных (в единицах времени), который допустимо потерять при сбое. Определяет частоту бэкапов: RPO = 1 час意味着 бэкап каждый час.

**RTO (Recovery Time Objective)** — целевое время восстановления сервиса после сбоя. Определяет метод восстановления: файловое vs полное.

**Image-Level Backup** — бэкап на уровне дискового образа (qcow2/raw). Включает полное состояние ВМ: ОС, данные, конфигурацию. Восстановление — полная пересборка ВМ из образа.

**File-Level Backup** — бэкап отдельных файлов внутри ВМ (через qemu-guest-agent или挂载 образа). Быстрое восстановление конкретных файлов без пересборки ВМ.

**Incremental Backup** — бэкап, сохраняющий только изменения с момента предыдущего бэкапа. Требует базового (full) бэкапа. Снижает объем хранимых данных на 60-90%.

**Consistent Snapshot** — снапшот, гарантированно содержащий целостные данные на уровне ФС. Требует fsfreeze через qemu-guest-agent перед снятием снапшота.

**DRBD (Distributed Replicated Block Device)** — блочная репликация данных между хостами в реальном времени. Используется для HA-кластеров без общего хранилища.

**Offsite Backup** — резервная копия, хранящаяся физически удаленно от основного сервера. Защита от пожара, затопления, кражи.

## Базовые концепции

### Матрица методов бэкапа

| Метод | Уровень | RPO | RTO | Стоимость хранилища | Сложность |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **virsh snapshot-create** | Внутренний снапшот qcow2 | 0 (мгновенно) | Низкая | Низкая (CoW) | Низкая |
| **qemu-img commit** | Блок-уровень | ~1 час | Средняя | Средняя | Средняя |
| **virt-backup (libvirt)** | Образ ВМ | 1-24 часа | Средняя | Высокая | Средняя |
| **Proxmox Backup Server** | Инкрементальный блок | 15 мин - 24 часа | Низкая | Низкая (dedup) | Средняя |
| **File-level (rsync/tar)** | Файлы внутри ВМ | 1-24 часа | Низкая | Низкая | Низкая |
| **DRBD** | Блок-репликация | 0 (real-time) | Минимальная | 2x (реплика) | Высокая |

### Архитектура бэкап-системы

```
┌─────────────────────────────────────────────────┐
│  KVM Host (гипервизор)                          │
│  ├── ВМ-1 (qcow2 + guest-agent)                │
│  ├── ВМ-2 (qcow2 + guest-agent)                │
│  └── ВМ-3 (raw на LVM)                         │
├─────────────────────────────────────────────────┤
│  Backup Layer                                    │
│  ├── Вариант A: PBS (Proxmox Backup Server)     │
│  ├── Вариант B: restic/borgbackup (file-level)  │
│  ├── Вариант C: virsh + cron (image-level)      │
│  └── Вариант D: DRBD (real-time replication)    │
├─────────────────────────────────────────────────┤
│  Хранилище бэкапов                               │
│  ├── Локальный: /backup/ (RAID)                 │
│  ├── NFS/CIFS: удаленный сервер                 │
│  └── S3/MinIO: объектное хранилище              │
└─────────────────────────────────────────────────┘
```

## Практические сценарии

### Сценарий 1: Бэкап через virsh + snapshots

Простейший метод бэкапа с использованием снапшотов libvirt.

```bash
#!/bin/bash
# vm-backup-virsh.sh — бэкап ВМ через внешние снапшоты
set -euo pipefail

VM_NAME="${1:?Usage: $0 <vm-name>}"
BACKUP_DIR="/backup/vms/$(date +%Y%m%d)"
RETENTION_DAYS=7

# 1. Заморозка ФС через guest-agent (если установлен)
echo "Freezing filesystem..."
virsh qemu-agent-command "$VM_NAME" \
  '{"execute":"guest-fsfreeze-freeze"}' 2>/dev/null || true

# 2. Создание внешнего снапшота
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SNAP_NAME="backup-${TIMESTAMP}"
virsh snapshot-create-as "$VM_NAME" "$SNAP_NAME" \
  --description "Automated backup $(date)" \
  --atomic

# 3. Разморозка ФС
echo "Thawing filesystem..."
virsh qemu-agent-command "$VM_NAME" \
  '{"execute":"guest-fsfreeze-thaw"}' 2>/dev/null || true

# 4. Определение пути к диску
DISK_PATH=$(virsh vol-dumpxml "$(virsh domblklist "$VM_NAME" | awk '/vda|sda/{print $1}')" \
  --pool default 2>/dev/null | grep -oP "file='[^']+'" | cut -d"'" -f2)

# 5. Копирование образа с hardlink (для экономии места)
mkdir -p "$BACKUP_DIR"
SNAP_PATH="/var/lib/libvirt/qemu/snapshot/$VM_NAME/$SNAP_NAME"
# Hardlink вместо копирования (same filesystem)
cp -al "$DISK_PATH" "$BACKUP_DIR/${VM_NAME}-${TIMESTAMP}.qcow2" 2>/dev/null || \
  cp --sparse=always "$DISK_PATH" "$BACKUP_DIR/${VM_NAME}-${TIMESTAMP}.qcow2"

# 6. Сохранение XML-конфигурации
virsh dumpxml "$VM_NAME" > "$BACKUP_DIR/${VM_NAME}.xml"

# 7. Удаление снапшота (данные уже скопированы)
virsh snapshot-delete "$VM_NAME" "$SNAP_NAME"

# 8. Верификация
SHA256=$(sha256sum "$BACKUP_DIR/${VM_NAME}-${TIMESTAMP}.qcow2" | awk '{print $1}')
echo "$SHA256  ${VM_NAME}-${TIMESTAMP}.qcow2" > "$BACKUP_DIR/${VM_NAME}-${TIMESTAMP}.sha256"

echo "Backup completed: $BACKUP_DIR/${VM_NAME}-${TIMESTAMP}.qcow2"
echo "SHA256: $SHA256"

# 9. Очистка старых бэкапов
find /backup/vms/ -maxdepth 1 -type d -mtime +$RETENTION_DAYS -exec rm -rf {} +
```

**Восстановление:**
```bash
#!/bin/bash
# vm-restore-virsh.sh — восстановление ВМ из бэкапа
set -euo pipefail

VM_NAME="${1:?Usage: $0 <vm-name>}"
BACKUP_FILE="${2:?Usage: $0 <vm-name> <backup-file>}"

# 1. Проверка целостности
echo "Verifying backup integrity..."
sha256sum -c "$(dirname "$BACKUP_FILE")/${VM_NAME}-*.sha256" || {
  echo "ERROR: Backup integrity check failed"
  exit 1
}

# 2. Остановка текущей ВМ (если работает)
virsh shutdown "$VM_NAME" 2>/dev/null || true
sleep 10
virsh destroy "$VM_NAME" 2>/dev/null || true

# 3. Копирование образа
RESTORE_PATH="/var/lib/libvirt/images/${VM_NAME}-restored.qcow2"
cp --sparse=always "$BACKUP_FILE" "$RESTORE_PATH"

# 4. Определениеpool
POOL=$(virsh vol-pool "$(basename "$RESTORE_PATH")" 2>/dev/null || echo "default")

# 5. Импорт в пул
virsh vol-upload "$(basename "$RESTORE_PATH")" "$RESTORE_PATH" --pool "$POOL"

# 6. Восстановление из XML
virsh define "$(dirname "$BACKUP_FILE")/${VM_NAME}.xml"

# 7. Запуск
virsh start "$VM_NAME"

echo "VM $VM_NAME restored from $BACKUP_FILE"
```

### Сценарий 2: Инкрементальный бэкап через restic

Restic —現代енный инструмент для инкрементального бэкапа с дедупликацией и шифрованием.

```bash
# Установка restic
sudo apt install -y restic

# Инициализация репозитория
export RESTIC_REPOSITORY="/backup/restic-kvm"
export RESTIC_PASSWORD="your-secure-password"
restic init

# Бэкап всех ВМ (образы + конфиги)
restic backup \
  /var/lib/libvirt/images/*.qcow2 \
  /etc/libvirt/qemu/ \
  --verbose \
  --tag "vm-backup" \
  --exclude "*.tmp"

# Инкрементальный бэкап (только изменения)
restic backup \
  /var/lib/libvirt/images/*.qcow2 \
  --verbose \
  --tag "vm-incremental"

# Просмотр снапшотов
restic snapshots
# → ID        Time                 Host        Tags          Paths
# → ----------------------------------------------------------------
# → a1b2c3d4  2026-09-17 02:00:05  kvm-host-01 vm-backup     /var/lib/libvirt/images
# → e5f6g7h8  2026-09-17 14:00:03  kvm-host-01 vm-incremental

# Восстановление конкретного образа
restic restore a1b2c3d4 --target /tmp/restore --include "web-server-01.qcow2"

# Очистка старых снапшотов (оставить 7 дневных, 4 недельных)
restic forget \
  --keep-daily 7 \
  --keep-weekly 4 \
  --keep-monthly 6 \
  --prune
```

**Автоматизация через systemd:**
```ini
# /etc/systemd/system/vm-backup.service
[Unit]
Description=KVM VM Backup
After=libvirtd.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/vm-backup-all.sh
Environment=RESTIC_REPOSITORY=/backup/restic-kvm
Environment=RESTIC_PASSWORD_FILE=/etc/restic-password
StandardOutput=journal
StandardError=journal

# /etc/systemd/system/vm-backup.timer
[Unit]
Description=Daily VM Backup

[Timer]
OnCalendar=*-*-* 02:00:00
RandomizedDelaySec=900
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now vm-backup.timer
```

### Сценарий 3: Бэкап через Proxmox Backup Server (PBS)

PBS — специализированный бэкап-сервер с инкрементальным хранением на блочном уровне, дедупликацией и шифрованием.

```bash
# Установка PBS (Debian 12)
echo "deb http://enterprise.proxmox.com/debian/pbs bookworm pbs-enterprise" | \
  sudo tee /etc/apt/sources.list.d/pbs-enterprise.list
wget https://enterprise.proxmox.com/debian/proxmox-release-bookworm.gpg -O /etc/apt/trusted.gpg.d/proxmox-release-bookworm.gpg
sudo apt update && sudo apt install -y proxmox-backup-server

# Настройка хранилища
proxmox-backup-manager datastore create kvm-backup /mnt/backup/pbs

# Установка клиента на KVM-хост
apt install -y proxmox-backup-client

# Бэкап ВМ (образ + конфиг)
proxmox-backup-client backup \
  vm/web-server-01.pxar:/var/lib/libvirt/images/web-server-01.qcow2 \
  --repository backup@pbs@192.168.1.50:kvm-backup \
  --keyfile /etc/pbs/client.key

# Бэкап всех ВМ (скрипт)
#!/bin/bash
# pbs-backup-all.sh
for vm in $(virsh list --all --name); do
  DISK=$(virsh domblklist "$vm" | awk '/vda|sda/{print $2}')
  if [ -n "$DISK" ]; then
    proxmox-backup-client backup \
      "vm/${vm}.pxar:${DISK}" \
      --repository backup@pbs@192.168.1.50:kvm-backup \
      --tag "daily" \
      --quiet
  fi
done

# Просмотр бэкапов
proxmox-backup-client list --repository backup@pbs@192.168.1.50:kvm-backup

# Восстановление
proxmox-backup-client restore \
  vm/web-server-01.pxar /var/lib/libvirt/images/web-server-01.qcow2 \
  --repository backup@pbs@192.168.1.50:kvm-backup \
  --snapshot "2026-09-17T02:00:00Z"
```

### Сценарий 4: File-level бэкап через virt-tar

Бэкап отдельных файлов из ВМ без полного копирования образа.

```bash
#!/bin/bash
# vm-file-backup.sh — файловый бэкап из работающей ВМ
set -euo pipefail

VM_NAME="${1:?Usage: $0 <vm-name>}"
BACKUP_DIR="/backup/vm-files/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# 1. Бэкап конфигурационных файлов
echo "Backing up configs..."
virt-tar -a "$(virsh vol-path "$(virsh domblklist "$VM_NAME" | awk '/vda|sda/{print $1}')" --pool default)" \
  -cz "$BACKUP_DIR/${VM_NAME}-configs.tar.gz" \
  /etc/nginx /etc/ssh /etc/postgresql

# 2. Бэкап логов (последние 7 дней)
echo "Backing up logs..."
virt-tar -a "$(virsh vol-path "$(virsh domblklist "$VM_NAME" | awk '/vda|sda/{print $1}')" --pool default)" \
  -cz "$BACKUP_DIR/${VM_NAME}-logs.tar.gz" \
  /var/log/nginx /var/log/syslog

# 3. Бэкап данных БД (PostgreSQL)
echo "Backing up PostgreSQL..."
PG_BACKUP="/backup/vm-files/$(date +%Y%m%d)/${VM_NAME}-pg-dump.sql.gz"
virt-cat -a "$(virsh vol-path "$(virsh domblklist "$VM_NAME" | awk '/vda|sda/{print $1}')" --pool default)" \
  /etc/postgresql/*/main/pg_hba.conf > "$BACKUP_DIR/${VM_NAME}-pg_hba.conf"

# 4. Восстановление конкретного файла
# virt-copy-in -a disk.qcow2 ./restored-file.conf /etc/nginx/
```

### Сценарий 5: Тестирование бэкапов (Backup Verification)

Бэкап бесполезен, если не проверено восстановление.

```bash
#!/bin/bash
# test-backup.sh — автоматизированное тестирование бэкапа
set -euo pipefail

BACKUP_FILE="${1:?Usage: $0 <backup-file>}"
TEST_VM="backup-test-$(date +%s)"

echo "=== Testing backup: $BACKUP_FILE ==="

# 1. Создание тестовой ВМ из бэкапа
echo "Creating test VM..."
cp --sparse=always "$BACKUP_FILE" "/var/lib/libvirt/images/${TEST_VM}.qcow2"

# 2. Запуск ВМ
virt-install \
  --name "$TEST_VM" \
  --memory 1024 --vcpus 1 \
  --disk path="/var/lib/libvirt/images/${TEST_VM}.qcow2",format=qcow2 \
  --import --noautoconsole \
  --os-variant ubuntu24.04

# 3. Ожидание IP
TEST_IP=""
for i in $(seq 1 60); do
  TEST_IP=$(virsh domifaddr "$TEST_VM" 2>/dev/null | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1)
  [ -n "$TEST_IP" ] && break
  sleep 2
done

if [ -z "$TEST_IP" ]; then
  echo "FAIL: VM did not get IP"
  virsh destroy "$TEST_VM" && virsh undefine "$TEST_VM" --remove-all-storage
  exit 1
fi

# 4. Проверки
echo "Testing SSH..."
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 ubuntu@"$TEST_IP" "echo OK" || {
  echo "FAIL: SSH not available"
  virsh destroy "$TEST_VM" && virsh undefine "$TEST_VM" --remove-all-storage
  exit 1
}

echo "Testing services..."
ssh ubuntu@"$TEST_IP" "systemctl is-active nginx || systemctl is-active postgresql" || true

echo "Testing data..."
ssh ubuntu@"$TEST_IP" "ls -la /var/lib/postgresql/ 2>/dev/null || echo 'No PostgreSQL data'"

# 5. Очистка
echo "Cleaning up..."
virsh destroy "$TEST_VM"
virsh undefine "$TEST_VM" --remove-all-storage

echo "=== Backup test passed ==="
```

**Рекомендация:** Запускайте тестирование бэкапов ежедневно на одной случайной ВМ и еженедельно — полное восстановление.

### Сценарий 6: Восстановление поврежденного образа

```bash
#!/bin/bash
# restore-damaged-image.sh — восстановление из бэкапа при повреждении
set -euo pipefail

VM_NAME="${1:?Usage: $0 <vm-name>}"
LATEST_BACKUP=$(ls -t /backup/vms/*/${VM_NAME}-*.qcow2 2>/dev/null | head -1)

if [ -z "$LATEST_BACKUP" ]; then
  echo "ERROR: No backup found for $VM_NAME"
  exit 1
fi

echo "Latest backup: $LATEST_BACKUP"

# 1. Проверка текущего образа
CURRENT_DISK=$(virsh vol-path "$(virsh domblklist "$VM_NAME" | awk '/vda|sda/{print $1}')" --pool default 2>/dev/null)
echo "Checking current disk..."
qemu-img check "$CURRENT_DISK" 2>&1 | tail -5

# 2. Остановка ВМ
virsh shutdown "$VM_NAME"
sleep 15
virsh destroy "$VM_NAME" 2>/dev/null || true

# 3. Резервная копия текущего (поврежденного) образа
mv "$CURRENT_DISK" "${CURRENT_DISK}.damaged.$(date +%s)"

# 4. Восстановление из бэкапа
cp --sparse=always "$LATEST_BACKUP" "$CURRENT_DISK"

# 5. Проверка целостности восстановленного образа
echo "Verifying restored image..."
qemu-img check "$CURRENT_DISK"

# 6. Запуск ВМ
virsh start "$VM_NAME"

echo "VM $VM_NAME restored from $LATEST_BACKUP"
```

## DR Runbook: Recovery Procedures

### Формулы расчёта RPO/RTO

**RPO (Recovery Point Objective):**
```
RPO = интервал между бэкапами × средние потери данных

Пример:
- Бэкап каждый час → RPO = 1 час
- Бэкап каждые 15 минут → RPO = 15 минут
- RPO = 0 → требует real-time репликация (DRBD)
```

**RTO (Recovery Time Objective):**
```
RTO = время_обнаружения + время_диагностики + время_восстановления + время_валидации

Пример:
- Восстановление из snapshot: 5-15 мин
- Восстановление из restic: 15-60 мин
- Восстановление из PBS: 5-15 мин
- Фоллback на DR-хост: 1-5 мин (auto-failover)
```

**Матрица RPO/RTO по tierам:**

| Tier | RPO | RTO | Метод | Стоимость |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1 (критичные)** | 0 | < 5 мин | DRBD + Pacemaker + auto-failover | Высокая |
| **Tier 2 (важные)** | 15 мин | < 30 мин | Инкрементальный бэкап (PBS/restic) | Средняя |
| **Tier 3 (обычные)** | 1-24 часа | < 4 часа | Ежедневный бэкап | Низкая |
| **Tier 4 (разработка)** | 24 часа | < 24 часа | Снапшоты / клонирование | Минимальная |

### DR Runbook (Steps)

**Этап 1: Обнаружение сбоя**
```bash
# Проверка состояния ВМ
virsh list --all | grep -E "shut off|crashed"

# Проверка KVM-хоста
systemctl status libvirtd
journalctl -u libvirtd --since "1 hour ago" -p err

# Проверка хранилища
df -h /var/lib/libvirt/images
zpool status 2>/dev/null  # если ZFS
```

**Этап 2: Диагностика**
```bash
# Проверка логов ВМ
journalctl -u "libvirt-qemu\\x2d${VM_NAME}"

# Проверка дискового образа
qemu-img check /var/lib/libvirt/images/${VM_NAME}.qcow2

# Проверка сети
virsh net-dhcp-leases default
```

**Этап 3: Восстановление (выбор метода)**

| Сценарий | Метод | Шаги |
| :--- | :--- | :--- |
| **ВМ не стартует** | Восстановление из snapshot | `virsh snapshot-revert` |
| **Диск поврежден** | Восстановление из бэкапа | `restic restore` / `cp` из backup |
| **Хост недоступен** | Миграция на DR-хост | `virsh migrate --live` или `--p2p` |
| **Потеря данных** | Восстановление из offsite | `restic restore` с remote repo |
| **Полный сбой ЦОД** | DR-хост в другом site | Автоматический failover (Pacemaker) |

**Этап 4: Валидация после восстановления**
```bash
# Проверка доступности сервисов
curl -s -o /dev/null -w "%{http_code}" http://${VM_IP}/health
ssh -o ConnectTimeout=5 ubuntu@${VM_IP} "systemctl is-active nginx"

# Проверка данных (PostgreSQL)
ssh ubuntu@${VM_IP} "psql -c 'SELECT NOW()' -U app"

# Проверка целостности (файловая)
ssh ubuntu@${VM_IP} "sha256sum -c /etc/checksums.sha256"
```

**Этап 5: Post-Incident**
```bash
# Создание нового бэкапа после восстановления
restic backup /var/lib/libvirt/images/${VM_NAME}.qcow2 --tag "post-incident"

# Уведомление команды
echo "VM $VM_NAME restored from backup at $(date)" | mail -s "DR Incident Resolved" ops@example.com

# Документирование
cat > /tmp/incident-$(date +%Y%m%d).md <<EOF
# Incident Report
- Date: $(date)
- VM: $VM_NAME
- Root cause: [description]
- Resolution: restored from backup $BACKUP_FILE
- Downtime: [duration]
- Action items: [list]
EOF
```

### Тестирование DR (Disaster Recovery Testing)

```bash
#!/bin/bash
# dr-test.sh — ежемесячное тестирование DR
set -euo pipefail

TEST_VM="dr-test-vm"
BACKUP_REPO="/backup/restic-kvm"
REMOTE_REPO="s3:s3.amazonaws.com/dr-backup"

echo "=== DR Test: $(date) ==="

# 1. Симуляция сбоя: удаление тестовой ВМ
virsh destroy "$TEST_VM" 2>/dev/null || true
virsh undefine "$TEST_VM" --remove-all-storage 2>/dev/null || true

# 2. Восстановление из локального бэкапа
echo "Restoring from local backup..."
RESTIC_REPOSITORY="$BACKUP_REPO" restic restore latest \
  --target /tmp/dr-test \
  --include "${TEST_VM}.qcow2"

# 3. Создание ВМ из восстановленного образа
virt-install --name "$TEST_VM" --memory 1024 --vcpus 1 \
  --disk path="/tmp/dr-test/${TEST_VM}.qcow2",format=qcow2 \
  --import --noautoconsole --os-variant ubuntu24.04

# 4. Проверка доступности
for i in $(seq 1 30); do
  IP=$(virsh domifaddr "$TEST_VM" 2>/dev/null | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1)
  [ -n "$IP" ] && break
  sleep 2
done

if [ -n "$IP" ]; then
  ssh -o ConnectTimeout=5 ubuntu@"$IP" "echo 'DR test OK'"
  echo "DR test PASSED: VM restored and accessible at $IP"
else
  echo "DR test FAILED: VM did not get IP"
fi

# 5. Очистка
virsh destroy "$TEST_VM" && virsh undefine "$TEST_VM" --remove-all-storage
```

## Политики хранения

### Рекомендации по retention

| Тип бэкапа | Хранение | Количество |
| :--- | :--- | :--- |
| **Ежедневный инкрементальный** | 7 дней | 7 копий |
| **Еженедельный полный** | 4 недели | 4 копии |
| **Ежемесячный полный** | 6 месяцев | 6 копий |
| **Ежеквартальный полный** | 1 год | 4 копии |
| **Годовой полный** | 3-5 лет | Архив |

### Место хранения (3-2-1 правило)

```
3 копии данных
├── 1: Оригинал (на KVM-хосте)
├── 2: Локальный бэкап (NAS/RAID на том же сайте)
└── 3: Удаленный бэкап (другой сайт / S3 / облако)

2 разных типа носителей
├── SSD/NVMe (оригинал + быстрый локальный)
└── HDD/Tape/S3 (медленный, но дешевый)

1 копия вне сайта
└── Offsite: S3, Glacier, удаленный ЦОД
```

## Мониторинг бэкапов

```yaml
# Prometheus alert rules для бэкапов
groups:
  - name: vm_backup_alerts
    rules:
      - alert: BackupFailed
        expr: backup_last_success_timestamp{job="vm-backup"} < (time() - 86400 * 2)
        for: 1h
        labels:
          severity: critical
        annotations:
          summary: "Бэкап ВМ не выполнялся > 48 часов"

      - alert: BackupSizeAnomaly
        expr: backup_size_bytes{job="vm-backup"} > backup_size_bytes{job="vm-backup"} offset 7d * 2
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Размер бэкапа {{ $labels.vm }} вырос в 2 раза"
```

```bash
# Проверка последнего успешного бэкапа
virsh snapshot-list web-server-01 --name | tail -1
# → backup-20260917_020000

# Проверка PBS
proxmox-backup-manager task list --limit 5
```

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **"No space left on device" при бэкапе** | Недостаточно места в /backup | Расширить хранилище или настроить rotation |
| **Бэкап занимает > 24 часа** | Бэкап через rsync полного образа | Использовать incremental (restic/PBS) |
| **Восстановленная ВМ не стартует** | Поврежден образ или не совпадает XML | Проверить `qemu-img check`, верифицировать XML |
| **Файлы повреждены в бэкапе** | Бэкап без fsfreeze | Использовать guest-agent + fsfreeze |
| **Restic не видит изменения** | Изменился только metadata | Добавить `--changed-since` или увеличить интервал |
| **PBS datastore满** | Нет automatic GC | Настроить `garbage-collection` по расписанию |

## Дополнительная информация

- [Высокая доступность KVM](./kvm_ha.md) — Pacemaker, DRBD, STONITH.
- [Образы ВМ — Основные концепции](../vm_images/basic_concepts.md) — форматы, CoW, снапшоты.
- [Образы ВМ — Практические сценарии](../vm_images/practical_scenarios.md) — qemu-img, libguestfs.
- [Overcommit и планирование ресурсов](./kvm_overcommit_and_capacity.md) — безопасные ratios.
- [Планирование ресурсов (Capacity Planning)](./kvm_capacity_planning.md) — right-sizing, ratio, прогнозирование.
- [Логирование KVM](./kvm_logging.md) — journald, rsyslog, централизованный сбор.
