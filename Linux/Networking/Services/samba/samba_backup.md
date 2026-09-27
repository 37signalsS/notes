# Samba: Резервное копирование

## Определения

**rsync** — утилита для инкрементальной синхронизации файлов. Передает только изменения (delta), что делает её эффективной для бэкапов большихOLUME dữli шар.

**borgbackup (borg)** — архиватор с дедупликацией, шифрованием и сжатием. Оптимален для долгосрочного хранения бэкапов с минимальным потреблением места.

**restic** — современный бэкап-инструмент с шифрованием, дедупликацией и поддержкой множества бэкендов (локальный, S3, SFTP).

**LVM Snapshot** — механизм создания мгновенных снимков логического тома. Позволяет получить консистентный снимок данных без остановки сервисов.

**VSS (Volume Shadow Copy)** — механизм Windows для создания снимков томов. При работе с Samba на стороне клиента (Windows) VSS позволяет бэкапить открытые файлы.

**Consistent Backup** — бэкап, при котором данные на диске находятся в согласованном состоянии (нет полузаписанных транзакций). Достигается через fsfreeze, LVM-snapshot или остановку сервисов.

**Incremental Backup** — бэкап, содержащий только изменения с момента предыдущего бэкапа. Экономит место и время, но требует полного бэкапа для восстановления.

**Deduplication** — механизм исключения дублирующихся блоков данных. В borgbackup реализован через content-defined chunking (Rabin fingerprinting).

## Базовые концепции

### Что нужно бэкапить в Samba

| Компонент | Путь | Важность | Частота |
| :--- | :--- | :--- | :--- |
| **Конфигурация** | `/etc/samba/smb.conf` | Критичная | При изменениях |
| **Базы данных TDB** | `/var/lib/samba/private/` | Критичная | Ежедневно |
| **Данные шар** | `/srv/samba/shares/` | Зависит от данных | По политике |
| **Ключи Kerberos** | `/etc/krb5.keytab` | Высокая | При ротации |
| **idmap база** | `/var/lib/samba/private/idmap.ldb` | Высокая | Ежедневно |
| **Логи аудита** | `/var/log/samba/audit.log` | Средняя | Ежедневно |

### Стратегии бэкапов

| Стратегия | Время | Место | Сложность | Восстановление |
| :--- | :--- | :--- | :--- | :--- |
| **rsync (full copy)** | Среднее | 100% данных | Низкая | Быстрое |
| **borgbackup** | Низкое | 20-40% данных | Средняя | Быстрое |
| **restic** | Низкое | 20-40% данных | Средняя | Быстрое |
| **LVM Snapshot + rsync** | Минимальное | 100% данных | Высокая | Быстрое |

### Типы бэкапов

```
Полный бэкап (Full):      [████████████████████] 100%
Инкрементальный (Incr):   [██] [█] [██] [█] [██]   Только изменения
Дифференциальный (Diff):  [████] [██████] [████████] Все с момента Full
```

## Практические сценарии

### 1. Бэкап через rsync (простой)

```bash
#!/bin/bash
# /usr/local/bin/samba_backup_rsync.sh

# Настройки
BACKUP_SRC="/srv/samba/shares/"
BACKUP_DST="backup-server:/backup/samba"
LOG_FILE="/var/log/samba_backup.log"
DATE=$(date +%Y%m%d_%H%M%S)

# Логирование
exec > >(tee -a "$LOG_FILE") 2>&1
echo "=== Начало бэкапа: $(date) ==="

# Создание инкрементального бэкапа с hardlinks
rsync -avz --delete \
    --link-dest="$BACKUP_DST/latest" \
    "$BACKUP_SRC" \
    "$BACKUP_DST/$DATE/"

# Обновление ссылки latest
ln -snf "$BACKUP_DST/$DATE" "$BACKUP_DST/latest"

# Бэкап конфигурации
rsync -avz /etc/samba/smb.conf "$BACKUP_DST/config/"

# Бэкап TDB-баз
tar -czf "$BACKUP_DST/tdb/tdb_$DATE.tar.gz" \
    /var/lib/samba/private/secrets.tdb \
    /var/lib/samba/private/idmap.ldb \
    /var/lib/samba/private/passdb.tdb

echo "=== Бэкап завершен: $(date) ==="
```

```bash
# Cron: ежедневно в 2:00
0 2 * * * /usr/local/bin/samba_backup_rsync.sh
```

### 2. Восстановление из rsync

```bash
# Полное восстановление данных
sudo rsync -avz backup-server:/backup/samba/latest/ /srv/samba/shares/

# Восстановление конкретного файла
sudo rsync -avz backup-server:/backup/samba/latest/important_file.txt \
    /srv/samba/shares/important_file.txt

# Восстановление конфигурации
sudo rsync -avz backup-server:/backup/samba/config/smb.conf /etc/samba/smb.conf
sudo systemctl restart smbd
```

### 3. Бэкап через borgbackup (дедупликация)

```bash
# Установка
sudo apt install -y borgbackup

# Инициализация репозитория
borg init --encryption=repokey /backup/samba-repo
# Или удаленный репозиторий
borg init --encryption=repokey ssh://backup-server/backup/samba-repo
```

```bash
#!/bin/bash
# /usr/local/bin/samba_backup_borg.sh

# Настройки
BORG_REPO="ssh://backup-server/backup/samba-repo"
BORG_PASSCOMMAND="cat /root/.borg_samba_pass"
BACKUP_SRC="/srv/samba/shares/"
CONFIG_SRC="/etc/samba/"
TDB_SRC="/var/lib/samba/private/"
LOG_FILE="/var/log/samba_borg.log"
DATE=$(date +%Y%m%d_%H%M%S)

# Логирование
exec > >(tee -a "$LOG_FILE") 2>&1
echo "=== Начало borg-бэкапа: $(date) ==="

# Экспорт пароля
export BORG_PASSCOMMAND

# Создание архива
borg create \
    --verbose \
    --stats \
    --compression auto,zstd,6 \
    --exclude '*.tmp' \
    --exclude '*~' \
    "$BORG_REPO::samba-{now}" \
    "$BACKUP_SRC" \
    "$CONFIG_SRC" \
    "$TDB_SRC"

# Очистка старых архивов (оставить 7 дневных, 4 недельных, 6 месячных)
borg prune \
    --verbose \
    --stats \
    --keep-daily=7 \
    --keep-weekly=4 \
    --keep-monthly=6 \
    "$BORG_REPO"

# Проверка целостности
borg check "$BORG_REPO"

echo "=== Borg-бэкап завершен: $(date) ==="
```

```bash
# Cron: ежедневно в 2:30
30 2 * * * /usr/local/bin/samba_backup_borg.sh
```

### 4. Восстановление из borgbackup

```bash
# Список архивов
borg list ssh://backup-server/backup/samba-repo

# Восстановление всего
borg extract ssh://backup-server/backup/samba-repo::samba-2026-09-15T02:30:00

# Восстановление конкретного файла
borg extract ssh://backup-server/backup/samba-repo::samba-2026-09-15T02:30:00 \
    srv/samba/shares/data/important_file.txt

# Монтирование архива (для просмотра)
mkdir /mnt/borg
borg mount ssh://backup-server/backup/samba-repo::samba-2026-09-15T02:30:00 /mnt/borg
ls /mnt/borg/srv/samba/shares/
borg umount /mnt/borg
```

### 5. Бэкап с LVM Snapshot (консистентный)

```bash
#!/bin/bash
# /usr/local/bin/samba_backup_lvm.sh

# Настройки
VG_NAME="vg_samba"
LV_NAME="lv_samba_data"
SNAP_NAME="snap_samba_data"
SNAP_SIZE="10G"
BACKUP_DST="backup-server:/backup/samba/lvm"
LOG_FILE="/var/log/samba_lvm_backup.log"
DATE=$(date +%Y%m%d_%H%M%S)

# Логирование
exec > >(tee -a "$LOG_FILE") 2>&1
echo "=== Начало LVM-бэкапа: $(date) ==="

# Создание снапшота
lvcreate -L "$SNAP_SIZE" -s -n "$SNAP_NAME" "/dev/$VG_NAME/$LV_NAME"
echo "Снапшот создан"

# Монтирование снапшота
mkdir -p /mnt/samba_snap
mount -o ro "/dev/$VG_NAME/$SNAP_NAME" /mnt/samba_snap

# Бэкап через rsync
rsync -avz --delete /mnt/samba_snap/ "$BACKUP_DST/$DATE/"

# Размонтирование и удаление снапшота
umount /mnt/samba_snap
lvremove -f "/dev/$VG_NAME/$SNAP_NAME"

echo "=== LVM-бэкап завершен: $(date) ==="
```

### 6. Бэкап конфигурации Samba

```bash
#!/bin/bash
# /usr/local/bin/samba_backup_config.sh

BACKUP_DIR="/backup/samba/config/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# smb.conf
cp /etc/samba/smb.conf "$BACKUP_DIR/"

# TDB-базы (критичные для AD)
tar -czf "$BACKUP_DIR/tdb_private.tar.gz" \
    /var/lib/samba/private/secrets.tdb \
    /var/lib/samba/private/idmap.ldb \
    /var/lib/samba/private/passdb.tdb \
    /var/lib/samba/private/sam.ldb.d/ 2>/dev/null || true

# Keytab
cp /etc/krb5.keytab "$BACKUP_DIR/" 2>/dev/null || true

# NSS/PAM конфигурация
cp /etc/nsswitch.conf "$BACKUP_DIR/"
cp /etc/pam.d/common-session "$BACKUP_DIR/" 2>/dev/null || true

echo "Конфигурация Samba сохранена в $BACKUP_DIR"
```

### 7. Восстановление TDB-баз

```bash
# Остановка сервисов
sudo systemctl stop smbd winbind

# Восстановление из бэкапа
sudo tar -xzf /backup/samba/config/latest/tdb_private.tar.gz -C /

# Исправление прав
sudo chown -R root:root /var/lib/samba/private
sudo chmod 600 /var/lib/samba/private/secrets.tdb
sudo chmod 600 /var/lib/samba/private/idmap.ldb

# Запуск сервисов
sudo systemctl start smbd winbind
```

### 8. Автоматизация через Ansible

```yaml
# См. samba_automation.md → backup_samba_config.yml
# Roles для бэкапа:
# - ansible-role-samba-backup-rsync
# - ansible-role-samba-backup-borg
```

### 9. Проверка целостности бэкапов

```bash
# Проверка rsync-бэкапа
rsync -avn backup-server:/backup/samba/latest/ /srv/samba/shares/
# Флаг -n (dry-run) покажет различия без копирования

# Проверка borg-бэкапа
borg check ssh://backup-server/backup/samba-repo
borg info ssh://backup-server/backup/samba-repo::latest

# Проверка LVM-снапшота
sudo lvs vg_samba
# Снапшот должен быть в��态 "active"
```

## Мониторинг и диагностика

### Мониторинг процесса бэкапа

```bash
# Проверка последнего бэкапа
ls -lt /backup/samba/ | head -5

# Проверка cron
crontab -l | grep samba_backup

# Проверка логов
tail -f /var/log/samba_backup.log
tail -f /var/log/samba_borg.log
```

### Интеграция с Prometheus

```bash
# Метрика успешности бэкапа
cat <<'EOF' > /usr/local/bin/samba_backup_metrics.sh
#!/bin/bash
METRICS_DIR="/var/lib/node_exporter/textfile_collector"
LAST_BACKUP=$(stat -c %Y /backup/samba/latest 2>/dev/null || echo "0")
CURRENT_TIME=$(date +%s)
AGE_HOURS=$(( (CURRENT_TIME - LAST_BACKUP) / 3600 ))

echo "samba_backup_age_hours $AGE_HOURS" > "$METRICS_DIR/samba_backup.prom.$$"
echo "samba_backup_last_timestamp $LAST_BACKUP" >> "$METRICS_DIR/samba_backup.prom.$$"

mv "$METRICS_DIR/samba_backup.prom.$$" "$METRICS_DIR/samba_backup.prom"
EOF
chmod +x /usr/local/bin/samba_backup_metrics.sh
```

### Алерт на просроченный бэкап

```yaml
# Prometheus rule
- alert: SambaBackupTooOld
  expr: samba_backup_age_hours > 25
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Samba backup is {{ $value }} hours old"
```

## Типовые ошибки бэкапа

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| rsync: Permission denied | Нет прав на чтение шары | Запускайте от root или через sudo |
| borg: Repository integrity error | Повреждение репозитория | `borg check --repair` |
| LVM snapshot: not enough space | Мало места для снапшота | Увеличьте `SNAP_SIZE` |
| Бэкап занимает много места | Нет prune-политики | Настройте `borg prune` |

## Дополнительная информация

- [Настройка сервера](./samba_setup.md) — создание шар.
- [Устранение неполадок](./samba_troubleshooting.md) — восстановление после сбоев.

## См. также

- [NFS: Резервное копирование](../nfs/nfs_backup.md) — аналогичные стратегии для NFS.
- [rsync: Основы](../../../../Linux/SystemAdministration/rsync.md) — детальный разбор rsync.
- [borgbackup: Обзор](../../../../Linux/SystemAdministration/backup_and_recovery.md) — бэкапы в Linux.
- [LVM: Снапшоты](../../../../Linux/FileSystems/LVM/snapshots.md) — создание снапшотов.
