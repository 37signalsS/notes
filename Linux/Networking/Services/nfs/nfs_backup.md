# NFS: Резервное копирование и восстановление

---

## Определения

**Backup NFS** — процесс создания резервных копий данных, хранящихся на NFS-сервере, для защиты от потери данных в результате сбоев оборудования, программных ошибок, ransomware или человеческого фактора.

**RPO (Recovery Point Objective)** — максимальный объём потери данных, допустимый при восстановлении. Определяет частоту бэкапов (например, RPO = 1 час → бэкап каждый час).

**RTO (Recovery Time Objective)** — максимальное время восстановления сервиса после сбоя. Определяет скорость и метод восстановления.

**Инкрементальный бэкап** — сохранение только изменённых файлов с момента последнего бэкапа. Экономит место и время.

**Полный бэкап (Full Backup)** — копирование всех данных независимо от изменений. Самый простой и надёжный, но требует максимум места.

**Снапшот (Snapshot)** — мгновенный снимок состояния ФС в определённый момент времени. Используется как основа для инкрементальных бэкапов.

---

## Теоретический блок

### Стратегии бэкапа NFS

| Стратегия | RPO | RTO | Место | Сложность | Применение |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **rsync (полный инкремент)** | 1 час | Среднее | Среднее | Низкая | Общие хранилища |
| **borgbackup** | 1 час | Низкое | Низкое (дедупликация) | Средняя | Критичные данные |
| **restic** | 1 час | Низкое | Низкое (дедупликация) | Средняя | Облачные/гетерогенные среды |
| **LVM/ZFS снапшот + rsync** | 15 мин | Низкое | Среднее | Высокая | Базы данных на NFS |
| **tar + cron** | 24 часа | Высокое | Высокое | Низкая | Некритичные данные |
| **Velero (Kubernetes)** | 1 час | Среднее | Среднее | Средняя | NFS в K8s |

### Инструменты бэкапа

| Инструмент | Тип | Дедупликация | Шифрование | Отправка на удалённый сервер |
| :--- | :--- | :--- | :--- | :--- |
| **rsync** | Синхронизация | Нет (но инкрементальный) | Через SSH | Да |
| **borgbackup** | Архиватор | Да (content-defined chunking) | Да (AES-256) | Да (borg serve) |
| **restic** | Архиватор | Да | Да (AES-256) | Да (S3, SFTP, rest-server) |
| **duplicity** | Архиватор | Нет | Да (GPG) | Да (scp, rsync, S3) |
| **LVM snapshots** | Снапшот | Нет | Нет | Нет (локально) |
| **ZFS snapshots** | Снапшот | Нет | Нет | Да (zfs send) |

### Топология бэкапа NFS

```
┌─────────────────┐
│  NFS-сервер     │
│  /srv/nfs/data  │
└────────┬────────┘
         │
    ┌────▼────┐
    │  LVM    │
    │ Снапшот │
    └────┬────┘
         │
    ┌────▼────────────────────────────────┐
    │           Backup-клиент             │
    │  rsync/borgbackup/restic            │
    └────┬────────────────────────────────┘
         │
    ┌────▼────┐
    │ Backup  │
    │ сервер  │
    │ (S3/SFTP│
    │ /NAS)   │
    └─────────┘
```

---

## Практический блок

### Сценарий 1: rsync (простой и надёжный)

#### Бэкап с NFS-сервера на backup-сервер

```bash
#!/bin/bash
# /usr/local/bin/nfs_backup_rsync.sh

NFS_SERVER="10.0.0.5"
NFS_PATH="/srv/nfs/data"
BACKUP_SERVER="10.0.0.100"
BACKUP_PATH="/backup/nfs"
LOG_FILE="/var/log/nfs_backup.log"
DATE=$(date +%Y%m%d_%H%M%S)

echo "[$(date)] Starting NFS backup..." >> $LOG_FILE

rsync -avz --delete \
    --timeout=300 \
    --progress \
    -e "ssh -i /root/.ssh/backup_key" \
    ${NFS_SERVER}:${NFS_PATH}/ \
    ${BACKUP_SERVER}:${BACKUP_PATH}/${DATE}/ \
    >> $LOG_FILE 2>&1

if [ $? -eq 0 ]; then
    echo "[$(date)] Backup completed successfully" >> $LOG_FILE
    # Удаление старых бэкапов (старше 30 дней)
    ssh -i /root/.ssh/backup_key ${BACKUP_SERVER} \
        "find ${BACKUP_PATH} -maxdepth 1 -type d -mtime +30 -exec rm -rf {} \;"
else
    echo "[$(date)] Backup FAILED" >> $LOG_FILE
    # Отправка алерта
    echo "NFS backup failed on $(hostname)" | \
        mail -s "NFS Backup Alert" admin@example.com
fi
```

```bash
# Cron (ежедневно в 2:00):
0 2 * * * /usr/local/bin/nfs_backup_rsync.sh
```

#### Восстановление из rsync-бэкапа

```bash
# Восстановление на NFS-сервер:
rsync -avz --progress \
    -e "ssh -i /root/.ssh/backup_key" \
    backup-server:/backup/nfs/20260914_020000/ \
    /srv/nfs/data/

# Или восстановление отдельного файла:
rsync -avz --progress \
    -e "ssh -i /root/.ssh/backup_key" \
    backup-server:/backup/nfs/20260914_020000/critical/file.db \
    /srv/nfs/data/critical/
```

### Сценарий 2: borgbackup (дедупликация + шифрование)

```bash
# Установка на backup-сервер:
sudo apt install -y borgbackup

# Инициализация репозитория:
borg init --encryption=repokey /backup/nfs-repo

# Или на удалённом сервере:
borg init --encryption=repokey ssh://backup-server/backup/nfs-repo
```

#### Бэкап NFS через borgbackup

```bash
#!/bin/bash
# /usr/local/bin/nfs_backup_borg.sh

NFS_MOUNT="/mnt/nfs"
BORG_REPO="ssh://backup-server/backup/nfs-repo"
BORG_PASSPHRASE="your-secure-passphrase"
RETENTION_DAYS=30
LOG_FILE="/var/log/nfs_borg_backup.log"

export BORG_PASSPHRASE

echo "[$(date)] Starting borg backup..." >> $LOG_FILE

borg create --verbose --stats --compression lz4 \
    "${BORG_REPO}::nfs-{now:%Y%m%d_%H%M%S}" \
    ${NFS_MOUNT}/ \
    --exclude '*.tmp' \
    --exclude '*.log' \
    >> $LOG_FILE 2>&1

if [ $? -eq 0 ]; then
    echo "[$(date)] Borg backup completed" >> $LOG_FILE

    # Очистка старых архивов
    borg prune --verbose --stats \
        "${BORG_REPO}" \
        --keep-daily=7 \
        --keep-weekly=4 \
        --keep-monthly=6 \
        >> $LOG_FILE 2>&1

    # Проверка целостности
    borg check "${BORG_REPO}" >> $LOG_FILE 2>&1
else
    echo "[$(date)] Borg backup FAILED" >> $LOG_FILE
fi
```

```bash
# Cron (ежедневно в 2:00):
0 2 * * * /usr/local/bin/nfs_backup_borg.sh
```

#### Восстановление из borgbackup

```bash
# Просмотр содержимого архива:
borg list ssh://backup-server/backup/nfs-repo

# Восстановление всего:
borg extract ssh://backup-server/backup/nfs-repo::nfs-20260914_020000

# Восстановление отдельного файла:
borg extract ssh://backup-server/backup/nfs-repo::nfs-20260914_020000 \
    path/to/critical/file.db
```

### Сценарий 3: LVM снапшот + rsync (для БД на NFS)

```bash
# 1. Создание снапшота (мгновенно, без даунтайма):
sudo lvcreate --size 5G --snapshot --name nfs_snap /dev/vg0/nfs_lv

# 2. Монтирование снапшота:
sudo mkdir -p /mnt/nfs_snap
sudo mount -o ro /dev/vg0/nfs_snap /mnt/nfs_snap

# 3. Бэкап через rsync (с монтированного снапшота):
rsync -avz --progress /mnt/nfs_snap/ backup-server:/backup/nfs/

# 4. Размонтирование и удаление снапшота:
sudo umount /mnt/nfs_snap
sudo lvremove -f /dev/vg0/nfs_snap
```

### Сценарий 4: NFS в Kubernetes (Velero)

```bash
# Установка Velero с NFS-бэкендом:
velero install \
    --provider aws \
    --bucket nfs-backups \
    --secret-file ./credentials-velero \
    --backup-location-config region=us-east-1,s3ForcePathStyle=true,s3Url=http://minio.example.com

# Бэкап всех PVC:
velero backup create nfs-full-backup --include-namespaces production

# Бэкап конкретного PVC:
velero backup create nfs-pvc-backup --include-resources persistentvolumeclaims --selector app=myapp

# Восстановление:
velero restore create --from-backup nfs-full-backup
```

### Сценарий 5: Автоматизация через Ansible

```yaml
---
- name: NFS Backup Setup
  hosts: nfs_servers
  become: true
  vars:
    backup_schedule: "0 2 * * *"
    backup_retention_days: 30
    nfs_export_path: /srv/nfs/data
    backup_server: backup-server.local
    backup_path: /backup/nfs

  tasks:
    - name: Install backup tools
      apt:
        name:
          - rsync
          - borgbackup
        state: present

    - name: Deploy backup script
      template:
        src: nfs_backup.sh.j2
        dest: /usr/local/bin/nfs_backup.sh
        mode: '0750'
        owner: root
        group: root

    - name: Configure cron job
      cron:
        name: "NFS backup"
        minute: "0"
        hour: "2"
        job: "/usr/local/bin/nfs_backup.sh"
        user: root

    - name: Create backup log rotation
      copy:
        content: |
          /var/log/nfs_backup.log {
              daily
              rotate 14
              compress
              missingok
              notifempty
          }
        dest: /etc/logrotate.d/nfs_backup
```

---

## Дополнительная информация

### Тестирование восстановления

```bash
# Регулярное тестирование (ежемесячно):
#!/bin/bash
# /usr/local/bin/nfs_restore_test.sh

# 1. Создание временной директории
TEST_DIR=$(mktemp -d)

# 2. Восстановление из последнего бэкапа
rsync -avz backup-server:/backup/nfs/latest/ $TEST_DIR/

# 3. Проверка целостности (например, checksum)
find $TEST_DIR -type f -exec md5sum {} \; > /tmp/checksums.txt
# Сравнение с оригиналом...

# 4. Очистка
rm -rf $TEST_DIR

echo "Restore test completed at $(date)"
```

### Чеклист бэкапа NFS

- [ ] Определены RPO и RTO для NFS-данных
- [ ] Выбрана стратегия бэкапа (rsync/borgbackup/restic)
- [ ] Настроен автоматический расписание бэкапов
- [ ] Настроено хранение бэкапов (retention policy)
- [ ] Протестировано восстановление из бэкапа
- [ ] Настроено уведомление об ошибках бэкапа
- [ ] Бэкапы шифруются (для критичных данных)
- [ ] Бэкапы хранятся в отдельной локации (3-2-1 правило)
- [ ] Документирована процедура восстановления
- [ ] Регулярно проводится drill по восстановлению

### Правило 3-2-1

- **3** копии данных (1 основная + 2 бэкапа)
- **2** разных типа носителя (локальный диск + NFS/S3)
- **1** копия в удалённом месте (offsite)

### Связанные темы

- **[NFS: Основные концепции](./index.md)** — архитектура NFS.
- **[NFS: Настройка сервера](./nfs_setup.md)** — конфигурация сервера.
- **[NFS: HA](./nfs_ha.md)** — отказоустойчивость.
- **[NFS: Квоты](../../../../Linux/FileSystems/disk_quotas.md)** — управление пространством.
- **[Velero в Kubernetes](../../../../Kubernetes/Installation/kind/kind_velero_backup.md)** — бэкап K8s.
