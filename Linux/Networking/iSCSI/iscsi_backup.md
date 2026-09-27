# iSCSI: Резервное копирование и восстановление

Руководство по стратегиям резервного копирования, созданию снапшотов, восстановлению данных и обеспечению целостности в iSCSI-инфраструктуре.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Crash-Consistent Snapshot** | Снапшот, гарантирующий целостность данных на уровне «как при аварийном выключении». ФС может потребовать восстановления (fsck). |
| **Application-Consistent Snapshot** | Снапшот с гарантированной целостностью на уровне приложения (все записи сброшены на диск). Требует «заморозки» I/O (quiesce). |
| **LVM Snapshot** | COW (Copy-on-Write) снапшот на уровне логического тома. Мгновенное создание, минимальные затраты. |
| **SCSI-3 PR (Persistent Reservations)** | Механизм управления доступом к LUN для нескольких инициаторов (требуется для кластеров). |
| **RPO (Recovery Point Objective)** | Максимально допустимый период потери данных. |
| **RTO (Recovery Time Objective)** | Максимально допустимый простой системы при восстановлении. |
| **GFS (Grandfather-Father-Son)** | Стратегия резервного копирования с полными, инкрементальными и разностными копиями. |

## Модель данных iSCSI

```
┌─────────────┐     ┌──────────────┐     ┌────────────────────┐
│  Приложение  │────▶│  ФС (ext4/xfs)│────▶│  LVM / Block Dev   │
└─────────────┘     └──────────────┘     └────────────────────┘
                                                  │
                                          ┌───────┴───────┐
                                          │  iSCSI LUN    │
                                          │  (multipath)  │
                                          └───────────────┘
```

**Ключевая проблема:** Снапшот должен гарантировать целостность данных на всех уровнях стека.

### Уровни консистентности при бэкапе

| Уровень | Описание | Метод | Применение |
| :--- | :--- | :--- | :--- |
| **Crash-Consistent** | Данные как при аварийном выключении | LVM snapshot без quiesce | Файловые серверы, не критичные данные |
| **File-System Consistent** | ФС-metadata консистентны | `freeze` + snapshot + `thaw` | Файловые системы с.metadata |
| **Application-Consistent** | Данные приложения консистентны | Quiesce приложения + snapshot | СУБД, критичные приложения |

## Матрица RPO/RTO для iSCSI-сценариев

| Сценарий | RPO | RTO | Метод | Инструменты |
| :--- | :--- | :--- | :--- | :--- |
| Файловый сервер на iSCSI | 24 ч | 1-4 ч | Ежедневный GFS | LVM snap + tar/rsync |
| PostgreSQL на iSCSI | 5-15 мин | 30 мин-1 ч | Quiesce + snap + WAL | pg_start_backup + LVM snap |
| MySQL/InnoDB на iSCSI | 15-60 мин | 1-2 ч | FLUSH + snap + binlog | FLUSH TABLES + LVM snap |
| Виртуальные машины на iSCSI | 1 ч | 15-30 мин | Snap VM + дамп БД | qemu-img snapshot + LVM snap |
| Высоконагруженная СУБД (RAC) | 0 (sync rep) | 5 мин | Кластер + репликация | Oracle RAC + Data Guard |
| Тестовая среда | 24 ч | 4-8 ч | Полный snap + rsync | LVM snap + rsync |

**Факторы выбора RPO:**
- Допустимый объем потери данных (бизнес-требования)
- Частота изменения данных (Write IOPS)
- Доступная пропускная способность для передачи бэкапа
- Время жизни снапшота (COW-переполнение)

### Правило 3-2-1-1-0 для iSCSI

Современная стратегия резервного копирования для критичных iSCSI-инфраструктур:

- **3** копии данных (production + 2 бэкапа)
- **2** разных типа носителей (диски + лента/облако)
- **1** копия вне площадки (Off-site)
- **1** копия неизменяемая (Immutable) или в изолированном контуре (Air-gap)
- **0** ошибок после тестирования восстановления

## Стратегии резервного копирования

### Уровень 1: Снапшоты на стороне таргета

Снапшоты создаются на сервере хранения и невидимы для инициатора. Это наиболее эффективный подход для iSCSI, так как не нагружает клиентские хосты.

#### LVM Snapshots (рекомендуется для Linux-таргетов)

LVM snapshots — основной механизм создания снапшотов для iSCSI-данных на Linux-таргетах. Использует механизм Copy-on-Write (COW) для мгновенного создания снимков.

**Принцип работы COW:**
1. При создании снимка выделяется COW-буфер (обычно 10-20% от размера оригинала)
2. При записи в исходный том блок сначала копируется в COW-буфер
3. Затем записываются новые данные
4. Снимок содержит «старое» состояние блока

**Рекомендации по размеру COW-буфера:**
- **Минимум:** 10% от размера исходного тома
- **Рекомендуется:** 20% для активно записываемых данных
- **Максимум:** 100% (тогда снимок никогда не переполнится)

```bash
# На таргете: создание COW-снапшота
sudo lvcreate -L 5G -s -n snap_data_$(date +%F) /dev/vg_data/lv_iscsi_data
# → 5G — максимальный размер COW. При переполнении снапшот становится невалидным.

# Монтирование снапшота для бэкапа
sudo mkdir -p /mnt/snap
sudo mount -o ro /dev/vg_data/snap_data_$(date +%F) /mnt/snap

# Бэкап с монтированного снапшота
sudo tar czf /backup/iscsi_data_$(date +%F).tar.gz -C /mnt/snap .

# Отмонтирование и удаление снапшота после бэкапа
sudo umount /mnt/snap
sudo lvremove -f /dev/vg_data/snap_data_$(date +%F)
```

**Настройка автоматического расширения снапшота:**
```ini
# /etc/lvm/lvm.conf
snapshot_autoextend_threshold = 70
snapshot_autoextend_percent = 20
```

#### Тонкие снапшоты (Thin Snapshots)

Если исходный LV создан в Thin Pool, снапшот не требует фиксированного COW-буфера:

```bash
# Создание thin-pool (если ещё не создан)
sudo lvcreate -L 500G --thinpool thin_data vg_iscsi

# Создание thin-LV
sudo lvcreate -V 100G --thin -n lv_data vg_iscsi/thin_data

# Thin-снапшот (не требует -L, размер динамический)
sudo lvcreate -s -n snap_data_thin vg_iscsi/lv_data

# Проверка потребления thin-pool
sudo lvs -o+data_percent,metadata_percent vg_iscsi/thin_data
```

**Преимущества thin-снапшотов:**
- Не нужно заранее вычислять размер COW-буфера
- Данные потребляются динамически (только записанные блоки)
- Экономия места: несколько снапшотов могут разделять пустые блоки

**Риски thin-снапшотов:**
- Thin Pool может исчерпать свободное место → все thin-LV станут read-only
- Мониторинг обязателен: `lvs -o+data_percent vg_iscsi/thin_data`
- При thin-overcommitment вероятность потери данных выше, чем при толстых снапшотах

#### Автоматизация создания снапшотов (cron)

Полный скрипт автоматического бэкапа iSCSI-данных через LVM-снапшоты:

```bash
#!/bin/bash
# /usr/local/bin/iscsi_snap_backup.sh
# Автоматический snapshot + rsync на удаленный сервер
# Запуск через cron: 0 2 * * * /usr/local/bin/iscsi_snap_backup.sh >> /var/log/iscsi_backup.log 2>&1

set -euo pipefail

# --- Конфигурация ---
LV_PATH="/dev/vg_data/lv_iscsi_data"
SNAP_NAME="backup_$(date +%Y%m%d_%H%M%S)"
SNAP_SIZE="10G"
MOUNT_POINT="/mnt/iscsi_backup_snap"
REMOTE_HOST="backup-server"
REMOTE_PATH="/backup/iscsi"
LOG_FILE="/var/log/iscsi_backup.log"
RETENTION_DAYS=7

# --- Функции ---
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

cleanup() {
    log "Очистка..."
    umount "$MOUNT_POINT" 2>/dev/null || true
    lvremove -f "$LV_PATH"_"$SNAP_NAME" 2>/dev/null || true
    log "Снапшот удалён"
}
trap cleanup EXIT

# --- Основной процесс ---
log "=== Начало бэкапа iSCSI ==="

# 1. Проверка свободного места в VG
VG_NAME=$(vgs --noheadings -o vg_name "$LV_PATH" | awk '{print $1}')
FREE_PE=$(vgs --noheadings -o vg_free --units g "$VG_NAME" | tr -d ' G')
log "Свободное место в $VG_NAME: ${FREE_PE}G"

if (( $(echo "$FREE_PE < 10" | bc -l) )); then
    log "ОШИБКА: Недостаточно свободного места (< 10G). Бэкап отменён."
    exit 1
fi

# 2. Создание снапшота
log "Создание снапшота $SNAP_NAME..."
lvcreate -L "$SNAP_SIZE" -s -n "$SNAP_NAME" "$LV_PATH"

# 3. Монтирование
mkdir -p "$MOUNT_POINT"
mount -o ro "$LV_PATH"_"$SNAP_NAME" "$MOUNT_POINT"

# 4. Валидация (проверка целостности ФС)
log "Проверка целостности ФС..."
if ! fsck -n "$LV_PATH"_"$SNAP_NAME" > /dev/null 2>&1; then
    log "ОШИБКА: ФС повреждена. Бэкап отменён."
    exit 1
fi

# 5. Копирование на удаленный сервер
log "Копирование на $REMOTE_HOST..."
rsync -avz --delete \
    --exclude='lost+found' \
    --exclude='*.tmp' \
    "$MOUNT_POINT/" \
    "$REMOTE_HOST:$REMOTE_PATH/$(date +%Y%m%d)/"

# 6. Проверка целостности (checksum)
LOCAL_SUM=$(find "$MOUNT_POINT" -type f -exec md5sum {} + | sort | md5sum | awk '{print $1}')
REMOTE_SUM=$(ssh "$REMOTE_HOST" "find $REMOTE_PATH/$(date +%Y%m%d)/ -type f -exec md5sum {} + | sort | md5sum | awk '{print $1}'")

if [ "$LOCAL_SUM" = "$REMOTE_SUM" ]; then
    log "Checksum совпадает: $LOCAL_SUM"
else
    log "ОШИБКА: Checksum НЕ совпадает! Локальный: $LOCAL_SUM, Удалённый: $REMOTE_SUM"
    exit 1
fi

# 7. Очистка старых бэкапов на удалённом сервере
log "Очистка бэкапов старше $RETENTION_DAYS дней..."
ssh "$REMOTE_HOST" "find $REMOTE_PATH -maxdepth 1 -type d -mtime +$RETENTION_DAYS -exec rm -rf {} +"

log "=== Бэкап завершён успешно ==="
```

#### Бэкап с application-consistent (PostgreSQL + cron)

```bash
#!/bin/bash
# /usr/local/bin/iscsi_pg_backup.sh
# PostgreSQL + LVM snap + pgBackRest для WAL-архивации

set -euo pipefail

DATA_LV="/dev/vg_data/pg_data"
SNAP_NAME="pg_snap_$(date +%Y%m%d_%H%M%S)"
SNAP_SIZE="5G"
BACKUP_REPO="/backup/pg_backups"
PG_HOST="localhost"
PG_PORT="5432"
PG_USER="postgres"
PG_DB="mydb"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" ; }

cleanup() {
    umount /mnt/pg_snap 2>/dev/null || true
    lvremove -f "$DATA_LV"_"$SNAP_NAME" 2>/dev/null || true
}
trap cleanup EXIT

log "=== iSCSI + PostgreSQL backup ==="

# 1. Quiesce: начало резервного копирования (WAL segment switch)
sudo -u postgres psql -h "$PG_HOST" -p "$PG_PORT" -d "$PG_DB" \
    -c "SELECT pg_start_backup('iscsi_snap', true, false)"

# 2. Создание LVM-снапшота
lvcreate -L "$SNAP_SIZE" -s -n "$SNAP_NAME" "$DATA_LV"

# 3. Quiesce: завершение резервного копирования
sudo -u postgres psql -h "$PG_HOST" -p "$PG_PORT" -d "$PG_DB" \
    -c "SELECT pg_stop_backup()"

# 4. Монтирование и копирование
mkdir -p /mnt/pg_snap
mount -o ro "$DATA_LV"_"$SNAP_NAME" /mnt/pg_snap

# 5. Бэкап через pgBackRest (из снапшота)
sudo -u postgres pgbackrest --stanza=main \
    --repo1-path="$BACKUP_REPO" \
    --pg1-path=/mnt/pg_snap \
    backup --type=incr

# 6. Проверка
sudo -u postgres pgbackrest --stanza=main \
    --repo1-path="$BACKUP_REPO" \
    info

log "=== Бэкап PostgreSQL завершён ==="
```

#### Target-level snapshots (hardware snapshots)

Если используется аппаратная СХД (NetApp, Dell EMC, и т.д.), снапшоты создаются через API массива:

```bash
# Пример:snapshot через CLI (зависит от вендора)
# NetApp ONTAP:
volume snapshot create -vserver iscsi_svm -volume data_vol -snapshot snap_$(date +%F)

# Dell EMC (Unisphere CLI):
snap -create -res /dev/vg_iscsi/lv_data -name snap_$(date +%F)
```

### Уровень 2: Снапшоты на стороне инициатора

Снапшоты создаются на хосте-клиенте (требует application-consistent подхода).

#### Для Linux-инициатора (LVM)

```bash
# На инициаторе, если данные на LVM
# 1. Заморозка приложения (для application-consistent)
sudo lvcreate -L 1G -s -n snap_app_data /dev/vg_app/lv_data

# 2. Бэкап снапшота
sudo mount -o ro /dev/vg_app/snap_app_data /mnt/snap
sudo rsync -av /mnt/snap/ /backup/app_data/

# 3. Очистка
sudo umount /mnt/snap
sudo lvremove -f /dev/vg_app/snap_app_data
```

#### Для Windows-инициатора (VSS)

Windows использует Volume Shadow Copy Service (VSS) для application-consistent снапшотов:

```powershell
# Создание VSS-снапшота (PowerShell, от администратора)
vssadmin create shadow /for=D: /oldest

# Или через wmic
wmic shadowcopy call create Volume="D:\"
```

### Уровень 3: Интеграция с бэкап-серверами

#### Бэкап через rsync/dd (файловый уровень)

```bash
# rsync: инкрементальный бэкап с снапшота
sudo rsync -av --delete /mnt/snap/ backup-server:/backup/iscsi/$(date +%F)/

# dd: блочный бэкап (для полных образов)
sudo dd if=/dev/mapper/mpatha of=/backup/iscsi_full_$(date +%F).img bs=4M status=progress
```

#### Бэкап черезbacula/bareos

```bash
# Пример JobDef для iSCSI-данных
Job {
  Name = "iSCSI-Backup"
  Client = "storage-server-fd"
  FileSet = "iSCSI-Data"
  Storage = "File"
  Pool = "Full"
  Schedule = "WeeklyCycle"
  Messages = "Standard"
  Run Before Job = "/usr/local/bin/snap_iscsi.sh"
  Run After Job = "/usr/local/bin/snap_cleanup.sh"
}
```

## Восстановление данных

### Процедура восстановления из LVM-снапшота

Восстановление данных из снапшота зависит от типа тома и файловой системы.

#### Восстановление обычного (Thick) снапшота

```bash
# 1. Размонтирование тома (если возможно)
sudo umount /dev/vg_data/lv_iscsi_data

# 2. Запуск слияния снапшота с оригиналом
sudo lvconvert --merge /dev/vg_data/snap_data_2026-09-12
# → Merging of volume vg_data/snap_data_2026-09-12 started.

# 3. Активация тома (если слияние выполняется в фоне)
sudo lvchange -ay /dev/vg_data/lv_iscsi_data

# 4. Проверка целостности файловой системы
sudo fsck -f /dev/vg_data/lv_iscsi_data

# 5. Монтирование.tomа
sudo mount /dev/vg_data/lv_iscsi_data /mnt/data
```

**Важно:** Для корневой файловой системы потребуется перезагрузка, так как слияние выполняется при следующей активации тома.

#### Восстановление тонкого (Thin) снапшота

```bash
# 1. Проверка состояния thin-pool
sudo lvs -o+data_percent,metadata_percent vg_iscsi/thin_data

# 2. Если thin-pool переполнен — освободите место
sudo lvremove /dev/vg_data/old_thin_snap

# 3. Восстановление из снапшота
sudo lvconvert --merge /dev/vg_data/thin_snap_data

# 4. Проверка и монтирование
sudo fsck -f /dev/vg_data/thin_data
sudo mount /dev/vg_data/thin_data /mnt/data
```

### Восстановление файлов из снапшота (без слияния)

Если нужно восстановить отдельные файлы, можно примонтировать снапшот как обычный том:

```bash
# 1. Монтирование снапшота в режиме только чтение
sudo mkdir -p /mnt/snap_restore
sudo mount -o ro /dev/vg_data/snap_data_2026-09-12 /mnt/snap_restore

# 2. Копирование нужных файлов
sudo cp /mnt/snap_restore/etc/important.conf /restore/etc/
sudo rsync -av /mnt/snap_restore/var/www/ /restore/var/www/

# 3. Размонтирование
sudo umount /mnt/snap_restore
```

### Восстановление PostgreSQL из снапшота

```bash
# 1. Остановка PostgreSQL
sudo systemctl stop postgresql

# 2. Удаление повреждённых данных
sudo rm -rf /var/lib/postgresql/14/main/*

# 3. Монтирование снапшота
sudo mount -o ro /dev/vg_data/pg_snap_2026-09-12 /mnt/pg_snap

# 4. Копирование данных
sudo rsync -av /mnt/pg_snap/ /var/lib/postgresql/14/main/

# 5. Настройка прав
sudo chown -R postgres:postgres /var/lib/postgresql/14/main/

# 6. Запуск PostgreSQL
sudo systemctl start postgresql

# 7. Проверка целостности (WAL-архивация должна быть настроена)
sudo -u postgres psql -c "SELECT pg_is_in_recovery();"
```

### Восстановление MySQL/InnoDB из снапшота

```bash
# 1. Остановка MySQL
sudo systemctl stop mysql

# 2. Монтирование снапшота
sudo mount -o ro /dev/vg_data/mysql_snap_2026-09-12 /mnt/mysql_snap

# 3. Копирование данных
sudo rsync -av /mnt/mysql_snap/ /var/lib/mysql/

# 4. Настройка прав
sudo chown -R mysql:mysql /var/lib/mysql/

# 5. Запуск MySQL с проверкой целостности
sudo systemctl start mysql
sudo mysqlcheck --all-databases --check-upgrade
```

### Восстановление виртуальных машин

Для ВМ, хранящихся на iSCSI-дисках:

```bash
# 1. Остановка ВМ
sudo virsh shutdown vm_name

# 2. Монтирование снапшота
sudo mount -o ro /dev/vg_data/vm_snap_2026-09-12 /mnt/vm_snap

# 3. Копирование образа диска
sudo cp /mnt/vm_snap/vm_disk.qcow2 /var/lib/libvirt/images/vm_disk_restored.qcow2

# 4. Запуск ВМ
sudo virsh start vm_name
```

### Тестирование восстановления

**Бэкап не считается существующим, пока не проведено успешное тестовое восстановление.**

```bash
# Скрипт тестирования восстановления
#!/bin/bash
# /usr/local/bin/test_iscsi_restore.sh

set -euo pipefail

SNAP_NAME="$1"
TEST_DIR="/tmp/iscsi_restore_test_$(date +%s)"
LOG_FILE="/var/log/iscsi_restore_test.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "=== Начало теста восстановления из $SNAP_NAME ==="

# 1. Создание временной директории
mkdir -p "$TEST_DIR"

# 2. Монтирование снапшота
sudo mount -o ro /dev/vg_data/"$SNAP_NAME" "$TEST_DIR"

# 3. Проверка целостности файловой системы
if sudo fsck -n "$TEST_DIR" > /dev/null 2>&1; then
    log "ФС целостна"
else
    log "ОШИБКА: ФС повреждена"
    exit 1
fi

# 4. Проверка наличия ключевых файлов
if [ -f "$TEST_DIR/etc/fstab" ]; then
    log "Ключевые файлы найдены"
else
    log "ОШИБКА: Ключевые файлы отсутствуют"
    exit 1
fi

# 5. Размонтирование и очистка
sudo umount "$TEST_DIR"
rm -rf "$TEST_DIR"

log "=== Тест восстановления пройден ==="
```

## Консистентность данных

### Уровни консистентности

| Уровень | Описание | Метод | RPO |
| :--- | :--- | :--- | :--- |
| **Crash-Consistent** | Данные «как при аварийном выключении» | LVM snapshot без quiesce | 0 (мгновенно) |
| **File-System Consistent** | ФС-metadata консистентны | `freeze` + snapshot + `thaw` | 0 |
| **Application-Consistent** | Данные приложения консистентны | Quiesce приложения + snapshot | 0 |

### Процедура application-consistent снапшота

```bash
#!/bin/bash
# /usr/local/bin/app_consistent_snap.sh
# Создание application-consistent снапшота для PostgreSQL

LVM_SNAP="/dev/vg_data/pg_data_snap"
DATA_LV="/dev/vg_data/pg_data"
MOUNT_POINT="/var/lib/postgresql"
BACKUP_DIR="/backup/postgres"

# 1. Заморозка I/O (PostgreSQL: pg_start_backup)
sudo -u postgres psql -c "SELECT pg_start_backup('snapshot', true)"

# 2. Создание COW-снапшота
sudo lvcreate -L 2G -s -n pg_data_snap_$(date +%F) "$DATA_LV"

# 3. Разморозка I/O
sudo -u postgres psql -c "SELECT pg_stop_backup()"

# 4. Монтирование и бэкап
sudo mkdir -p /mnt/snap
sudo mount -o ro "$LVM_SNAP" /mnt/snap
sudo rsync -av /mnt/snap/ "$BACKUP_DIR/$(date +%F)/"

# 5. Очистка
sudo umount /mnt/snap
sudo lvremove -f "$LVM_SNAP"
```

### Quiesce для различных СУБД

| СУБД | Команда freeze | Команда thaw |
| :--- | :--- | :--- |
| **PostgreSQL** | `SELECT pg_start_backup('label', true)` | `SELECT pg_stop_backup()` |
| **MySQL** | `FLUSH TABLES WITH READ LOCK` | `UNLOCK TABLES` |
| **MariaDB** | `FLUSH TABLES WITH READ LOCK` | `UNLOCK TABLES` |
| **Oracle** | `ALTER TABLESPACE BEGIN BACKUP` | `ALTER TABLESPACE END BACKUP` |
| **MS SQL Server** | VSS (hardware provider) | VSS |

## Интеграция с LVM

### Важные настройки для iSCSI + LVM

```ini
# /etc/lvm/lvm.conf

devices {
    # Фильтр: разрешить только multipath-устройства
    filter = [ "a|/dev/mapper/mpath.*|", "r|/dev/sd.*|" ]

    # Ограничение сканирования (ускорение)
    scan = [ "/dev/mapper" ]

    # Настройка для сетевых устройств
    obtain_device_list_with_udev = 0
}

backup {
    # Резервное копирование метаданных LVM
    retain = 30
    directory = "/etc/lvm/backup"
}
```

### Работа с VG на iSCSI-устройствах

```bash
# Создание VG поверх multipath-устройства
sudo vgcreate vg_iscsi /dev/mapper/mpatha

# Создание LV
sudo lvcreate -L 100G -n lv_data vg_iscsi
sudo lvcreate -L 20G -n lv_logs vg_iscsi

# Создание снапшота
sudo lvcreate -L 10G -s -n snap_data vg_iscsi/lv_data

# Просмотр снапшота
sudo lvs
# → lv_data  vg_iscsi  -wi-a-- 100.00g
#   snap_data vg_iscsi  Swi-a--  10.00g   lv_data
```

## Стратегии бэкапа

### Полный бэкап (Full Backup)

```bash
# Полный бэкап всех данных с таргета
#!/bin/bash
SNAP_NAME="full_$(date +%F)"
sudo lvcreate -L 10G -s -n "$SNAP_NAME" /dev/vg_data/lv_iscsi
sudo mount -o ro /dev/vg_data/"$SNAP_NAME" /mnt/snap
sudo tar czf /backup/iscsi_full_$(date +%F).tar.gz -C /mnt/snap .
sudo umount /mnt/snap
sudo lvremove -f /dev/vg_data/"$SNAP_NAME"
```

### Инкрементальный бэкап

```bash
# Инкремент: только изменения с момента последнего бэкапа
LAST_FULL="/backup/iscsi_full_2026-09-01.tar.gz"
sudo rsync -av --compare-dest="$LAST_FULL" /mnt/snap/ /backup/iscsi_incremental_$(date +%F)/
```

### Стратегия祖父-отец-сын (GFS)

| День | Тип бэкапа | Хранение |
| :--- | :--- | :--- |
| Вс | Полный (Grandfather) | 12 месяцев |
| Пн-Сб | Инкрементальный (Father) | 4 недели |
| Ежедневно | Разностный (Son) | 7 дней |

## Безопасное хранение бэкапов

### Шифрование резервных копий

Данные должны шифроваться **до** передачи в хранилище (source-side encryption).

#### Шифрование с помощью GPG

```bash
# Шифрование архива перед отправкой
tar -czf - /mnt/snap_data/ | gpg --symmetric --cipher-algo AES256 -o backup_$(date +%F).tar.gz.gpg

# Расшифровка
gpg --decrypt backup_$(date +%F).tar.gz.gpg | tar -xzf - -C /restore/
```

#### Шифрование с помощью age (современная альтернатива)

```bash
# Генерация ключа
age-keygen -o /etc/age/backup_key.txt

# Шифрование
tar -czf - /mnt/snap_data/ | age -r age1... > backup_$(date +%F).tar.gz.age

# Расшифровка
age -d -i /etc/age/backup_key.txt backup_$(date +%F).tar.gz.age | tar -xzf - -C /restore/
```

### Неизменяемость (Immutability)

Для защиты бэкапов от удаления или модификации (включая администратора):

#### Объектное хранилище (S3-совместимое)

```bash
# Включение Object Lock при создании бакета
aws s3api create-bucket \
    --bucket iscsi-backups-immutable \
    --object-lock-enabled-for-bucket

# Загрузка с Immutability Governance Mode
aws s3api put-object \
    --bucket iscsi-backups-immutable \
    --key backup_$(date +%F).tar.gz.gpg \
    --body backup_$(date +%F).tar.gz.gpg \
    --object-lock-mode GOVERNANCE \
    --object-lock-retain-until-date "$(date -d '+30 days' +%Y-%m-%dT%H:%M:%SZ)"
```

#### Локальное хранилище с Append-Only

```bash
# Создание директории с Append-Only (только через特殊ый пользователь)
sudo mkdir -p /backup/immutable
sudo chown backup-immutable:backup-immutable /backup/immutable
sudo chmod 700 /backup/immutable

# Настройка ACL для запрета удаления
sudo setfacl -m u:backup-immutable:rwx /backup/immutable
sudo setfacl -m d:backup-immutable:rwx /backup/immutable
```

### Air-gap резервное копирование

Физическое изолирование бэкапов от сети:

```bash
# Скрипт для Air-gap бэкапа на ленту
#!/bin/bash
# /usr/local/bin/airgap_backup.sh

set -euo pipefail

TAPE_DEVICE="/dev/nst0"
BACKUP_DIR="/backup/immutable"
LOG_FILE="/var/log/airgap_backup.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "=== Начало Air-gap бэкапа ==="

# 1. Проверка наличия ленты
if ! mt -f "$TAPE_DEVICE" status > /dev/null 2>&1; then
    log "ОШИБКА: Лента не найдена или устройство не готово"
    exit 1
fi

# 2. Запись на ленту
log "Запись данных на ленту..."
find "$BACKUP_DIR" -type f -name "*.tar.gz.gpg" -mtime -1 -print0 | \
    tar -cf "$TAPE_DEVICE" --null -T -

# 3. Верификация
log "Верификация данных..."
mt -f "$TAPE_DEVICE" rewind
tar -df "$TAPE_DEVICE" -T /dev/null

# 4. Отключение ленты
log "Отключение ленты от системы"
mt -f "$TAPE_DEVICE" offline

log "=== Air-gap бэкап завершён ==="
```

### Мониторинг целостности бэкапов

```bash
# Скрипт проверки целостности бэкапов
#!/bin/bash
# /usr/local/bin/verify_backups.sh

set -euo pipefail

BACKUP_DIR="/backup/remote"
LOG_FILE="/var/log/backup_verification.log"
ALERT_EMAIL="ops@example.com"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# Проверка наличия свежего бэкапа
LATEST_BACKUP=$(find "$BACKUP_DIR" -name "*.tar.gz*" -type f -printf '%T@ %p\n' 2>/dev/null | \
    sort -rn | head -1 | awk '{print $2}')

if [ -z "$LATEST_BACKUP" ]; then
    log "КРИТИЧЕСКАЯ ОШИБКА: Свежие бэкапы не найдены"
    echo "CRITICAL: No recent backups found on $(hostname)" | mail -s "Backup Alert" "$ALERT_EMAIL"
    exit 1
fi

BACKUP_AGE=$(( ($(date +%s) - $(stat -c %Y "$LATEST_BACKUP")) / 86400 ))

if [ "$BACKUP_AGE" -gt 7 ]; then
    log "ПРЕДУПРЕЖДЕНИЕ: Последний бэкап $BACKUP_AGE дней назад"
    echo "WARNING: Last backup is $BACKUP_AGE days old" | mail -s "Backup Alert" "$ALERT_EMAIL"
fi

# Проверка checksum
log "Проверка целостности файлов..."
for f in "$BACKUP_DIR"/*.sha256; do
    if [ -f "$f" ]; then
        BASENAME=$(basename "$f" .sha256)
        if ! sha256sum -c "$f" > /dev/null 2>&1; then
            log "ОШИБКА: Checksum не совпадает для $BASENAME"
            echo "CRITICAL: Checksum mismatch for $BASENAME" | mail -s "Backup Alert" "$ALERT_EMAIL"
        fi
    fi
done

log "Проверка завершена успешно"
```

## Ограничения и особенности

### Ограничения LVM Snapshots

- **COW-переполнение:** При записи данных в исходный LV превышающих размер COW, снапшот становится невалидным (`I` в `lvs`). Рекомендуется выделять 10-20% от размера оригинала.
- **Производительность:** Каждая операция записи вызывает копирование старых данных (COW). При активном снапшоте производительность записи падает на 5-15%.
- **Не для production без мониторинга:** Обязательно отслеживать `data_percent` в `lvs`.
- **Одновременные снимки:** При наличии нескольких снимков одного тома производительность падает пропорционально количеству снимков.

### Одновременный доступ к LUN

Если к одному LUN подключены несколько инициаторов:
- **Без SCSI-3 PR:** Каждый видит устройство, но запись приводит к повреждению данных
- **С SCSI-3 PR:** Кластерные СУБД (PostgreSQL, Oracle RAC) могут безопасно использовать общий LUN
- **Настройка PR:** `targetcli` → `/scsi/.../reservations` (операции Register/Preempt/Clear)

### Типичные проблемы при бэкапе и их решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Снапшот переполнен** | COW-буфер исчерпан | Увеличить размер снапшота или чаще удалять старые |
| **Бэкап занимает слишком много времени** | Большие объемы данных | Использовать инкрементальный бэкап (rsync --link-dest) |
| **ФС повреждена после восстановления** | Неконсистентный снапшот | Использовать application-consistent подход |
| **Сетевые ошибки при копированныи** | Нестабильная сеть | Настроить повторные попытки (rsync --partial) |
| **Нехватка места на целевом сервере** | Нет ротации бэкапов | Настроить автоматическую очистку старых копий |

### Rescan после изменения размера LUN

Если размер LUN на таргете был изменён:

```bash
# 1. На инициаторе: уведомить ядро об изменении размера
echo 1 | sudo tee /sys/class/block/sdb/device/rescan

# 2. Обновить Multipath (если используется)
sudo multipath -r

# 3. Расширить ФС
sudo resize2fs /dev/mapper/mpatha1       # для ext4
sudo xfs_growfs /data                     # для xfs
```

### Восстановление после потери снапшота

Если снапшот стал невалидным (атрибут `I` в `lvs`):

```bash
# 1. Проверка состояния
sudo lvs -o lv_name,vg_name,lv_size,snap_percent,attr vg_data
# → LV            VG      LSize   Snap%  Attr
# → snap_data     vg_data  5.00g  100.00 Swi--p---

# 2. Удаление невалидного снапшота
sudo lvremove -f /dev/vg_data/snap_data

# 3. Создание нового снапшота (с увеличенным размером)
sudo lvcreate -L 10G -s -n snap_data_new /dev/vg_data/lv_iscsi_data

# 4. Проверка нового снапшота
sudo lvs -o lv_name,vg_name,lv_size,snap_percent,attr vg_data
# → LV            VG      LSize   Snap%  Attr
# → snap_data_new vg_data 10.00g   0.00  Swi-a-s---
```

## Чек-лист перед продакшеном

### Безопасность iSCSI
- [ ] Настроен firewall (порт 3260/tcp ограничен)
- [ ] Включён CHAP (односторонний или взаимный)
- [ ] ACL настроен (только доверенные IQN)
- [ ] Сетевая изоляция (выделенный VLAN для iSCSI-трафика)
- [ ] Шифрование трафика (IPsec при необходимости)

### Multipath и LVM
- [ ] Multipath настроен и протестирован (failover)
- [ ] LVM фильтр настроен (`filter = [ "a|/dev/mapper/mpath.*|", "r|/dev/sd.*|" ]`)
- [ ] `replacement_timeout` установлен (рекомендуется 120 сек)
- [ ] `_netdev` опция в `/etc/fstab`

### Резервное копирование
- [ ] Стратегия бэкапа определена (full + incremental)
- [ ] RPO/RTO параметры установлены для каждого типа данных
- [ ] Тестовый бэкап-восстановление выполнено
- [ ] Шифрование бэкапов настроено
- [ ] Неизменяемость (Immutability) настроена для критичных данных
- [ ] Air-gap копирование организовано (при необходимости)

### Мониторинг и алертинг
- [ ] Мониторинг снапшотов настроен (`lvs -o snap_percent`)
- [ ] Алертинг на переполнение COW-буфера настроен
- [ ] Проверка целостности бэкапов автоматизирована
- [ ] Мониторинг состояния Multipath настроен

### Документация и процедуры
- [ ] Процедура восстановления документирована
- [ ] Контакты ответственных лиц обновлены
- [ ] Тестовое восстановление проведено и задокументировано
- [ ] Регулярный аудит бэкапов запланирован

## См. также

- **[Настройка iSCSI Target](./iscsi_target_setup.md)** — создание LUN и backstores
- **[Настройка Multipath I/O](./iscsi_multipath.md)** — отказоустойчивость при бэкапе
- **[LVM — снимки](../../FileSystems/LVM/snapshots.md)** — подробнее о работе COW и типах снимков
- **[Резервное копирование и восстановление в Linux](../../SystemAdministration/backup_and_recovery.md)** — общие стратегии и инструменты
- **[Диагностика iSCSI](./iscsi_diagnostics.md)** — проверка состояния сессий
- **[Мониторинг iSCSI](./iscsi_monitoring.md)** — настройка алертинга на проблемы с бэкапами
