# LVM — Операции управления

## Определения

**Операции управления LVM** — совокупность административных задач по поддержке, мониторингу и изменению конфигурации системы логических томов на протяжении всего их жизненного цикла.

**LVM CLI Toolkit** — набор утилит пользовательского пространства (`pvs`, `vgs`, `lvs` и др.), взаимодействующих с Device Mapper в ядре для управления блочными устройствами.

**Фильтры LVM** — параметры конфигурации в `/etc/lvm/lvm.conf`, ограничивающие список блочных устройств, которые система должна сканировать при поиске метаданных LVM.

**Теги LVM (Tags)** — строковые метки (до 1024 символов), назначаемые объектам LVM (PV, VG, LV) для их группировки, массового управления или фильтрации.

**dmeventd (Device Mapper Event Daemon)** — системный демон, отвечающий за автоматический мониторинг состояния LVM-объектов. Уведомляет о изменениях (заполнение thin pool, развитие снимков, деградация RAID). Управляется через `lvm2-monitor.service`.

**lvm.conf** — главный конфигурационный файл LVM, определяющий фильтры устройств, политики распределения, пороги автоматического расширения и параметры логирования. Расположен в `/etc/lvm/lvm.conf`.

## Базовые концепции

### Иерархия инструментов управления

Инструментарий LVM разделен по функциональному назначению:
1.  **Reporting (Отчеты):** `pvs`, `vgs`, `lvs`. Компактный табличный вывод.
2.  **Display (Детализация):** `pvdisplay`, `vgdisplay`, `lvdisplay`. Подробная многострочная информация.
3.  **Action (Действие):** `pvcreate`, `vgextend`, `lvchange`, `lvremove`. Команды, изменяющие структуру или атрибуты.
4.  **Maintenance (Обслуживание):** `vgscan`, `vgck`, `vgexport`, `vgimport`. Проверка и подготовка к миграции.

### Классификация задач по SSoT-файлам

| Категория | Основной документ | Описание задачи |
| :--- | :--- | :--- |
| **Инициализация** | [Создание PV, VG, LV](./operations/pv_vg_creation.md) | Первичная подготовка носителей и пулов. |
| **Масштабирование** | [Изменение размеров](./operations/lvm_resize.md) | Онлайн-расширение и уменьшение томов. |
| **Снимки** | [Снимки (Snapshots)](./snapshots.md) | Резервное копирование и точки отката (COW). |
| **Тонкие пулы** | [Thin Provisioning](./thin-provisioning.md) | Динамическое выделение места и переподписка. |
| **Миграция** | [Замена диска](./operations/lvm_disk_replacement.md) | Замена физических носителей через `pvmove`. |
| **Мониторинг** | [Просмотр информации](./operations/lvm_view_info.md) | Анализ состояния и атрибутов томов. |

### Конфигурация LVM (lvm.conf) — ключевые параметры для DevOps/SRE

Конфигурационный файл `/etc/lvm/lvm.conf` определяет поведение всей подсистемы LVM. Ниже — параметры, наиболее критичные для DevOps/SRE.

#### Фильтры устройств

Фильтры определяют, какие устройства LVM должен сканировать. Неправильные фильтры — частая причина «пропадания» VG.

```bash
# /etc/lvm/lvm.conf
devices {
    # Пример: только multipath-устройства (для SAN)
    global_filter = [ "a|/dev/mapper/mpath.*|", "r|.*|" ]

    # Пример: локальные диски + NVMe (без iSCSI)
    filter = [ "a|/dev/sd[a-z].*|", "a|/dev/nvme.*|", "r|.*|" ]
}
```

**Рекомендация:** После изменения фильтров необходимо:
```bash
sudo udevadm trigger && sudo udevadm settle
sudo vgscan
sudo vgs
```

#### Автоматическое расширение thin pool и снимков

```bash
# /etc/lvm/lvm.conf
activation {
    # Thin Pool — авто-расширение при достижении порога
    thin_pool_autoextend_threshold = 80   # Порог заполнения (%)
    thin_pool_autoextend_percent = 20     # Процент расширения

    # Снимки — авто-расширение
    snapshot_autoextend_threshold = 80
    snapshot_autoextend_percent = 20
}

# Включить мониторинг (обязательно для авто-расширения)
global {
    monitoring = 1
}
```

**Важно:** Автоматическое расширение работает только при запущенном `dmeventd`:
```bash
sudo systemctl enable --now dmeventd
sudo systemctl status lvm2-monitor.service
```

#### Логирование

```bash
# /etc/lvm/lvm.conf
log {
    file = "/var/log/lvm2.log"
    level = 7    # 0=quiet, 5=normal, 7=verbose (для отладки)
    overwrite = 1
}
```

**Для production:** уровень `5` (normal). Для отладки — `7` (verbose). Не оставляйте `7` на боевых серверах — высокий I/O.

#### Настройка распределения (allocation)

```bash
# /etc/lvm/lvm.conf
allocation {
    # Политика распределения по PV
    # cling = заполнять один PV перед переходом на следующий
    # striped = чередование (для striped LV)
    # contiguous = непрерывное размещение
    cling = 1

    # Максимальное количество LV для созданий по умолчанию
    max_lv = 0    # 0 = без ограничений
    max_pv = 0
}
```

#### Время ожидания (timeout)

```bash
# /etc/lvm/lvm.conf
dmeventd {
    # Таймаут ожидания поллинга дляoperations
    polling_interval = 10   # секунд
}
```

## Практические сценарии

### Сценарий 1: Оперативная проверка здоровья (SRE Cheat Sheet)

```bash
# 1. Проверка физических дисков
sudo pvs
# → PV         VG      Fmt  Attr PSize   PFree
# → /dev/sdb   data_vg lvm2 a--  <20.00g <5.00g

# 2. Проверка свободного места в группах
sudo vgs
# → VG      #PV #LV #SN Attr   VSize   VFree
# → data_vg   1   2   0 wz--n- <20.00g <5.00g

# 3. Поиск переполненных томов или снимков
sudo lvs -o lv_name,data_percent,snap_percent

# 4. Проверка атрибутов (активность, тип)
sudo lvs -a -o lv_name,lv_attr,devices

# 5. Проверка целостности метаданных
sudo vgck data_vg

# 6. Проверка journal для ошибок LVM
sudo journalctl -k | grep -i "device-mapper\|lvm\|dm-"

# 7. Проверка статуса dmeventd
sudo systemctl status lvm2-monitor.service
```

### Сценарий 2: Перенос группы томов на другой сервер

Используется при физическом перемещении дисков между хостами.

**На исходном сервере:**
```bash
# 1. Отмонтирование и деактивация
sudo umount /mnt/data
sudo vgchange -an vg_data
# → 0 logical volume(s) in volume group "vg_data" now active

# 2. Экспорт (пометка метаданных)
sudo vgexport vg_data
# → Volume group "vg_data" successfully exported
```

**На целевом сервере:**
```bash
# 1. Сканирование и импорт
sudo pvscan
# → PV /dev/sdc    is in exported VG vg_data [20.00 GiB / 5.00 GiB free]
sudo vgimport vg_data
# → Volume group "vg_data" successfully imported

# 2. Активация и монтирование
sudo vgchange -ay vg_data
sudo mount /dev/vg_data/lv_data /mnt/data
```

### Сценарий 3: Массовое управление через теги

Позволяет выполнять действия над группой объектов одновременно.

```bash
# 1. Назначение тегов
sudo vgchange --addtag production vg_data
sudo lvchange --addtag database vg_data/lv_db_01
sudo lvchange --addtag database vg_data/lv_db_02

# 2. Просмотр объектов с определенным тегом
sudo lvs @database

# 3. Массовая активация/деактивация по тегу
sudo lvchange -an @database
# → 2 logical volume(s) in volume group "vg_data" now inactive
```

### Сценарий 4: Управление метаданными и бэкапами

LVM автоматически сохраняет конфигурацию при каждом изменении.

-   **/etc/lvm/backup/** — содержит актуальную копию каждой VG.
-   **/etc/lvm/archive/** — история изменений метаданных (позволяет откатиться назад).

**Ручной бэкап всех VG:**
```bash
for vg in $(sudo vgs --noheadings -o vg_name); do
    sudo vgcfgbackup $vg
    echo "Backup of $vg completed"
done
```

**Просмотр истории изменений:**
```bash
sudo vgcfgrestore --list vg_data
# → File: /etc/lvm/archive/vg_data_00040-12345.vg
# → Description: Created before executing 'lvextend -L +5G vg_data/lv_app'
```

Подробные сценарии восстановления описаны в:
- **[LVM — Расширенные темы (Диагностика)](./advanced_topics/advanced_topics.md#сценарий-5-диагностика-целостности-метаданных)**
- **[LVM — Практические сценарии восстановления](./advanced_topics/practical_scenarios.md)**

## Безопасность LVM

### Защита от случайного удаления

```bash
# Запрет на уменьшение VG (защита от vgreduce/remove)
sudo vgchange -x n vg_data    # Resizeable = no

# Разрешение на уменьшение (перед плановой операцией)
sudo vgchange -x y vg_data    # Resizeable = yes
```

### Шифрование LVM (LUKS)

Для зашифрованных томов схема: `Disk → LUKS → LVM PV → VG → LV`.

```bash
# Проверка статуса LUKS-контейнера
sudo cryptsetup status crypt_disk
# → /dev/mapper/crypt_disk is active and is in use.
# → type:    LUKS2
# → cipher:  aes-xts-plain64

# Блокировка LUKS-контейнера (перед извлечением диска)
sudo cryptsetup luksClose crypt_disk
```

### Очистка диска перед утилизацией

```bash
# Очистка LVM-метаданных
sudo pvremove /dev/sdX

# Полная очистка диска (включая LVM-метки и данные)
sudo wipefs --all /dev/sdX
sudo blkdiscard /dev/sdX    # Для SSD (TRIM)
# Или для HDD:
sudo dd if=/dev/zero of=/dev/sdX bs=1M status=progress
```

## Интеграция с systemd и автоматизация

### Ключевые службы LVM

| Служба | Назначение | Автозапуск |
| :--- | :--- | :--- |
| `lvm2-pvscan@.service` | Автоматическое сканирование PV при обнаружении устройства | Да (udev trigger) |
| `lvm2-monitor.service` | Мониторинг состояния томов через `dmeventd` | Да |
| `lvm2-lvmpolld.service` | Поллинг для длительных операций (pvmove) | Да |
| `lvm2-activation@.service` | Активация VG при загрузке | Да (initramfs) |

**Проверка и управление:**
```bash
# Проверка статуса
sudo systemctl status lvm2-monitor.service

# Включение мониторинга (обязательно для авто-расширения thin pool)
sudo systemctl enable --now lvm2-monitor.service

# Просмотр логов
sudo journalctl -u lvm2-monitor.service --since "1 hour ago"
```

### Создание systemd timer для регулярных проверок

```bash
# /etc/systemd/system/lvm-healthcheck.service
[Unit]
Description=LVM Health Check
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/lvm_health_check.sh
```

```bash
# /etc/systemd/system/lvm-healthcheck.timer
[Unit]
Description=Run LVM health check daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
# Активация таймера
sudo systemctl enable --now lvm-healthcheck.timer

# Ручной запуск проверки
sudo systemctl start lvm-healthcheck.service
```

## Интеграция с мониторингом

### Экспорт метрик для Prometheus

Для мониторинга LVM через Prometheus используется `node_exporter` с текстовым коллектором:

```bash
# /etc/node_exporter/textfile/lvm.prom
#!/bin/bash
# Скрипт генерации метрик LVM

OUTPUT="/var/lib/node_exporter/textfile/lvm.prom"

# Метрика: свободное место в VG
for vg in $(sudo vgs --noheadings --nosuffix --units g -o vg_name,vg_free 2>/dev/null); do
    name=$(echo $vg | awk '{print $1}')
    free=$(echo $vg | awk '{print $2}')
    echo "lvm_vg_free_bytes{name=\"$name\"} $(echo "$free * 1073741824" | bc)" >> ${OUTPUT}.tmp
done

# Метрика: использование thin pool
sudo lvs --noheadings -o lv_name,vg_name,data_percent,metadata_percent 2>/dev/null | \
while read lv vg data meta; do
    if [[ -n "$data" ]]; then
        echo "lvm_thin_pool_data_percent{pool=\"$lv\",vg=\"$vg\"} $data" >> ${OUTPUT}.tmp
        echo "lvm_thin_pool_meta_percent{pool=\"$lv\",vg=\"$vg\"} $meta" >> ${OUTPUT}.tmp
    fi
done

# Метрика: использование снимков
sudo lvs --noheadings -o lv_name,vg_name,snap_percent,origin 2>/dev/null | \
while read lv vg snap origin; do
    if [[ -n "$snap" ]]; then
        echo "lvm_snapshot_usage_percent{name=\"$lv\",vg=\"$vg\",origin=\"$origin\"} $snap" >> ${OUTPUT}.tmp
    fi
done

mv ${OUTPUT}.tmp ${OUTPUT}
```

**Запуск по cron:**
```bash
# /etc/cron.d/lvm_metrics
*/5 * * * * root /etc/node_exporter/textfile/lvm_metrics.sh
```

### Пороги алертования (SRE/DevOps)

Рекомендуемые пороги для настройки мониторинга (Prometheus, Zabbix, Nagios):

| Метрика | Порог WARNING | Порог CRITICAL | Действие |
| :--- | :--- | :--- | :--- |
| **Thin Pool Data%** | > 80% | > 90% | Расширить пул: `lvextend -L +SIZE` |
| **Thin Pool Meta%** | > 70% | > 85% | Расширить метаданные: `lvextend --poolmetadatasize` |
| **Snapshot Usage%** | > 60% | > 80% | Рассмотреть удаление или увеличение |
| **VG Free Space** | < 10% | < 5% | Добавить PV или переместить данные |
| **LV Usage%** | > 85% | > 95% | Расширить LV: `lvextend -r` |
| **Missing PVs** | > 0 | > 0 | Немедленная диагностика, `vgreduce --removemissing` |
| **RAID Degraded** | `d` flag | `D` flag | Замена диска, rebuild |
| **Cache Hit Rate** | < 80% | < 60% | Увеличить размер кэш-пула |

## Скрипты автоматизации

### Скрипт полной проверки здоровья LVM

```bash
#!/bin/bash
# lvm_full_check.sh — комплексная проверка LVM для DevOps/SRE
set -euo pipefail

LOG_FILE="/var/log/lvm_check_$(date +%Y%m%d_%H%M%S).log"
ALERT_LEVEL=0  # 0=OK, 1=WARNING, 2=CRITICAL

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

check_pv() {
    log "=== Physical Volumes ==="
    sudo pvs --noheadings -o pv_name,vg_name,pv_attr,pv_free 2>/dev/null | while read pv vg attr free; do
        if [[ "$attr" == *"x"* ]]; then
            log "  CRITICAL: $pv ($vg) is EXPORTED"
            ALERT_LEVEL=2
        fi
    done
}

check_vg_free() {
    log "=== VG Free Space ==="
    sudo vgs --noheadings --nosuffix --units g -o vg_name,vg_free,vg_free_count 2>/dev/null | while read vg free count; do
        if (( count < 100 )); then
            log "  CRITICAL: $vg has only ${free}g ($count PE) free"
            ALERT_LEVEL=2
        elif (( count < 256 )); then
            log "  WARNING: $vg has ${free}g ($count PE) free"
            [ $ALERT_LEVEL -lt 1 ] && ALERT_LEVEL=1
        else
            log "  OK: $vg has ${free}g ($count PE) free"
        fi
    done
}

check_thin_pools() {
    log "=== Thin Pool Usage ==="
    sudo lvs --noheadings -o lv_name,vg_name,data_percent,metadata_percent,lv_attr 2>/dev/null | \
    while read lv vg data meta attr; do
        if [[ "$attr" == *"t"* ]] && [[ -n "$data" ]]; then
            data_int=${data%.*}
            if (( data_int > 90 )); then
                log "  CRITICAL: $vg/$lv at ${data}% (thin pool near full)"
                ALERT_LEVEL=2
            elif (( data_int > 80 )); then
                log "  WARNING: $vg/$lv at ${data}%"
                [ $ALERT_LEVEL -lt 1 ] && ALERT_LEVEL=1
            fi
        fi
    done
}

check_snapshots() {
    log "=== Snapshot Usage ==="
    sudo lvs --noheadings -o lv_name,vg_name,snap_percent,lv_attr 2>/dev/null | \
    while read lv vg snap attr; do
        if [[ "$attr" == *"s"* ]] && [[ -n "$snap" ]]; then
            snap_int=${snap%.*}
            if (( snap_int > 80 )); then
                log "  CRITICAL: $vg/$lv snapshot at ${snap}% (near auto-delete)"
                ALERT_LEVEL=2
            elif (( snap_int > 60 )); then
                log "  WARNING: $vg/$lv snapshot at ${snap}%"
                [ $ALERT_LEVEL -lt 1 ] && ALERT_LEVEL=1
            fi
        fi
    done
}

check_metadata() {
    log "=== Metadata Integrity ==="
    for vg in $(sudo vgs --noheadings -o vg_name 2>/dev/null); do
        if ! sudo vgck "$vg" >/dev/null 2>&1; then
            log "  CRITICAL: $vg metadata check FAILED"
            ALERT_LEVEL=2
        else
            log "  OK: $vg metadata OK"
        fi
    done
}

check_missing_pvs() {
    log "=== Missing PVs ==="
    missing=$(sudo vgs --noheadings -o vg_missing_pv_count 2>/dev/null | tr -d ' ')
    if [[ "$missing" -gt 0 ]] 2>/dev/null; then
        log "  CRITICAL: VG has $missing missing PVs"
        ALERT_LEVEL=2
    else
        log "  OK: All PVs present"
    fi
}

# Main
log "=== LVM Health Check Started ==="
check_pv
check_vg_free
check_thin_pools
check_snapshots
check_metadata
check_missing_pvs
log "=== LVM Health Check Complete (Alert Level: $ALERT_LEVEL) ==="

exit $ALERT_LEVEL
```

### Скрипт автоматического резервного копирования метаданных

```bash
#!/bin/bash
# lvm_backup_metadata.sh — бэкап метаданных всех VG
set -euo pipefail

BACKUP_DIR="/backup/lvm_metadata/$(date +%Y%m%d)"
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"

# Бэкап всех VG
for vg in $(sudo vgs --noheadings -o vg_name); do
    sudo vgcfgbackup -f "$BACKUP_DIR/${vg}.conf" "$vg"
    echo "Backup of $vg saved to $BACKUP_DIR/${vg}.conf"
done

# Копирование архива
sudo tar czf "$BACKUP_DIR/lvm_archive.tar.gz" -C /etc/lvm/ backup/ archive/

# Очистка старых бэкапов
find /backup/lvm_metadata -maxdepth 1 -type d -mtime +$RETENTION_DAYS -exec rm -rf {} +

echo "LVM metadata backup completed: $BACKUP_DIR"
```

## DR-стратегия: план восстановления LVM

### Что хранить в backup

| Объект | Команда backup | Частота | Хранение |
|:---|:---|:---|:---|
| VG метаданные | `vgcfgbackup -f /backup/vg_data.conf vg_data` | Ежедневно | Вне сервера (S3, NFS) |
| Archive метаданных | `tar czf /backup/lvm_archive.tar.gz -C /etc/lvm/ backup/ archive/` | Ежедневно | Вне сервера |
| LVM конфигурация | Копия `lvm.conf` в Git | При изменении | Git-репозиторий |
| Список LV/PV/VG | `lvs/vgs/pvs --reportformat json > /backup/lvm_inventory.json` | Ежедневно | Вне сервера |
| LUKS-заголовки | `cryptsetup luksHeaderBackup /dev/vg/lv --header-backup-file /backup/luks_header` | При изменении | Защищённый носитель |

### Runbook: восстановление VG из backup

```bash
# 1. Определение проблемы
sudo vgs
# → VG "vg_data" not found

# 2. Поиск backup-файла
ls -la /etc/lvm/backup/vg_data.conf
# → Если есть — восстановление:
sudo vgcfgrestore -f /etc/lvm/backup/vg_data.conf vg_data

# 3. Если backup-файл повреждён — поиск archive
ls -la /etc/lvm/archive/vg_data_*.conf
# → Выбрать наиболее свежий:
sudo vgcfgrestore -f /etc/lvm/archive/vg_data_00001.conf vg_data

# 4. Активация VG
sudo vgchange -ay vg_data

# 5. Проверка LV
sudo lvs
# → (список LV должен восстановиться)

# 6. Проверка ФС
sudo fsck -n /dev/vg_data/lv_data
```

### Runbook: восстановление после потери PV

```bash
# 1. Определение отсутствующего PV
sudo vgs
# → VG "vg_data" has 1 missing PV

# 2. Удаление missing PV из VG
sudo vgreduce --removemissing vg_data

# 3. Если PV был важен (данные потеряны) — попытка восстановления
sudo ddrescue /dev/sdb /backup/sdb_image.log /backup/sdb_image.raw

# 4. Если PV был дублем (mirrored) — данные на другом PV в порядке
sudo lvdisplay vg_data/lv_data
# → Проверить, что LV активен
```

### Runbook: восстановление thin pool после переполнения

```bash
# 1. Проверка статуса
sudo lvs -o lv_name,lv_attr,data_percent vg_data/thin_pool
# → thin_pool  twi-a-t--  100.00g  100.00 (100% заполнен)

# 2. Все LV в read-only — проверить
sudo lvs -o lv_name,lv_attr
# → lv_data  Vwi-a-t--  200.00g (read-only из-за thin pool)

# 3. Расширение thin pool
sudo vgdisplay vg_data | grep "VFree"
# → VFree  50.00g
sudo lvextend -L +50G /dev/vg_data/thin_pool

# 4. Активация LV обратно
sudo lvchange -ay /dev/vg_data/lv_data

# 5. Проверка ФС
sudo fsck -n /dev/mapper/vg_data-lv_data
```

### Runbook: загрузка с LVM после повреждения initramfs

```bash
# 1. Загрузиться с Live CD

# 2. Проверить PV/VG
sudo pvscan
sudo vgscan
sudo vgchange -ay vg_data

# 3. Смонтировать корень
sudo mount /dev/vg_data/lv_root /mnt

# 4. Chroot
sudo chroot /mnt

# 5. Переустановка LVM в initramfs (Debian/Ubuntu)
echo "lvm2" | tee -a /etc/initramfs-tools/modules
update-initramfs -u

# 6. Переустановка LVM в initramfs (RHEL/CentOS)
dracut --force --add lvm --regenerate-all

# 7. Проверка GRUB
cat /boot/grub/grub.cfg | grep -i lvm
# → Убедиться, что root= UUID/LVM путь корректен

# 8. Перезагрузка
exit
sudo reboot
```

### Тестирование DR (ежеквартально)

1. Восстановление VG из backup на тестовом стенде.
2. Загрузка с LVM после переустановки initramfs.
3. Расширение thin pool после симуляции переполнения.
4. Проверка доступности всех LV и ФС.

## Дополнительная информация

### Диагностика и устранение неисправностей

| Проблема | Признак | Решение |
| :--- | :--- | :--- |
| **VG Not Found** | Группа не видна после подключения диска | Выполнить `vgscan` и проверить `global_filter` в **[lvm.conf](./advanced_topics/advanced_topics.md#фильтрация-устройств-lvmconf)**. |
| **Duplicate PV UUID** | Ошибка при клонировании дисков | Использовать `vgimportclone` для переименования VG и смены UUID. |
| **I/O Error (Thin)** | ФС перешла в Read-Only | Пул переполнен. Расширить пул или удалить снимки. Подробнее — в [Устранение неполадок: ФС в режиме read-only](../read_only_filesystem_troubleshooting.md). |
| **Thin Pool is Full** | Все LV become read-only | Расширить пул: `lvextend -L +SIZE VG/pool`. Проверить `monitoring = 1` и `dmeventd`. |
| **Metadata Checksum Error** | Ошибка целостности MDA | Использовать `pvck --repair` или восстановить из `/etc/lvm/backup/`. |
| **Device Not Found** | Устройство не существует или не активно | Проверить `lsblk`, выполнить `vgscan`, проверить фильтры в `lvm.conf`. |
| **Insufficient Space** | Недостаточно места для операции | Проверить `vgs` для `VFree`, добавить PV через `vgextend`. |
| **LV In Use** | Нельзя деактивировать LV | Проверить `lsof` / `fuser`, завершить процессы или перезагрузить. |

### Лучшие практики для DevOps/SRE

1. **Версионирование конфигурации:** Храните `lvm.conf` в Git. При изменениях — pull request и плановая deploying.
2. **Именование:** Используйте осмысленные имена с префиксами: `lv_db_prod_01`, `lv_app_staging`. Избегайте имён `lv1`, `lv2`.
3. **Документация:** Ведите CMDB с описанием PV/VG/LV для каждого сервера.
4. **Тестирование:** Все критические операции (vgexport, vgsplit, vgcfgrestore) сначала на staging.
5. **Мониторинг:** Настройте алерты по порогам из таблицы выше. Используйте `dmeventd` для авто-расширения.
6. **Резервное копирование:** Регулярно делайте `vgcfgbackup` и храните копии вне сервера.
7. **Rollback plan:** Перед каждой операцией продумывайте откат. Снимки — ваш друг.
8. **Минимизация downtime:** Для критичных сервисов используйте онлайн-операции (pvmove, lvextend) и планируйте работы в окно минимальной нагрузки.

### См. также
- **[LVM — Обзор и концепции](./overview_concepts.md)** — архитектура и экстенты.
- **[LVM — Расширенные темы](./advanced_topics/advanced_topics.md)** — глубокая диагностика, фильтры, RAID, кэши.
- **[LVM — Просмотр информации](./operations/lvm_view_info.md)** — детальный разбор команд `lvs`, `vgs`.
- **[LVM — Жизненный цикл](./operations/lvm_lifecycle.md)** — интеграция с systemd и активация.
