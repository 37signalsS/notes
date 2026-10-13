# LVM: Практические сценарии восстановления и оптимизации

## Определения

**Восстановление метаданных (Metadata Recovery)** — процесс реанимации структуры групп томов и логических томов из резервных копий конфигурации или дампов метаданных физических томов. Выполняется, когда повреждение области метаданных (MDA) делает VG или LV недоступными, но сами данные на диске остаются целыми.

**Миграция Swap (Swap Migration)** — перенос области подкачки (Swap) с выделенного логического тома LVM в файл или на другой носитель для освобождения места в группе томов или упрощения управления. Актуальна, когда Swap LV занимает пространство VG, необходимое для расширения критичных томов.

**vgsplit / vgmerge** — стандартные утилиты LVM для перемещения существующих логических томов (вместе с их физическими экстентами) между разными группами томов. `vgsplit` отделяет PV из исходной VG в новую временную VG, `vgmerge` объединяет временную VG с целевой.

**thin_repair / thin_dump** — системные утилиты (из пакета `device-mapper-persistent-data`) для восстановления поврежденных метаданных тонких пулов (Thin Pools), когда стандартные средства LVM (`lvconvert --repair`) не могут активировать пул. `thin_dump` выводит содержимое метаданных, `thin_repair` копирует их в новый LV.

**pvck** — утилита проверки целостности физических томов. Проверяет LVM-метку, область метаданных (MDA) и их соответствие эталону из backup. Используется как первый шаг диагностики при подозрении на повреждение PV.

**vgcfgbackup / vgcfgrestore** — команды резервного копирования и восстановления конфигурации группы томов. `vgcfgbackup` сохраняет текущее состояние VG в текстовый файл в `/etc/lvm/backup/`. `vgcfgrestore` записывает сохранённую конфигурацию обратно на PV, перезаписывая текущие (повреждённые) метаданные.

**lvm.conf (секции `activation`, `devices`, `global_filter`)** — главный конфигурационный файл LVM. Секция `devices` определяет фильтры сканирования, `activation` — политики автоматического расширения снимков и thin pool, `global_filter` — глобальную фильтрацию (влияет на все утилиты LVM, включая `pvscan`).

## Базовые концепции

### Механизмы защиты данных

LVM обеспечивает высокую отказоустойчивость благодаря автоматическому резервированию метаданных:
1.  **Backup (`/etc/lvm/backup/`):** содержит последнее актуальное состояние каждой VG. Файл обновляется автоматически после каждой операции, изменяющей структуру VG. Формат — текстовый, human-readable.
2.  **Archive (`/etc/lvm/archive/`):** хранит историю изменений метаданных. Файлы создаются автоматически **до** выполнения любой команды, изменяющей структуру VG (`lvcreate`, `lvremove`, `vgextend` и т.д.). Это позволяет откатиться к состоянию, например, до удаления LV.

**Важно:** Обе директории содержат критически важные файлы. Рекомендуется периодически создавать копии этих директорий на отдельный носитель или в систему контроля версий.

### Стратегии миграции

Миграция ресурсов может происходить как внутри одной VG (`pvmove`), так и между разными VG (`vgsplit`). Перенос данных между независимыми хостами требует использования процедур экспорта/импорта (`vgexport`/`vgimport`).

### Порядок действий при аварии (Decision Tree)

При обнаружении проблем с LVM-структурами следуйте логической последовательности:

1.  **Диагностика** — определите, что именно повреждено (PV, VG metadata, LV, thin pool, RAID).
2.  **Не трогайте данные** — не выполняйте `pvcreate`, `lvcreate`, `lvremove` без анализа. Любая запись может безвозвратно повредить данные.
3.  **Попробуйте стандартные средства** — `vgcfgrestore`, `lvconvert --repair`, `vgchange -ay`.
4.  **Перейдите к ручному восстановлению** — `pvcreate --uuid --restorefile`, `thin_repair`, `pvck --dump`.
5.  **При неуспехе** — используйте Live CD и инструменты внешнего восстановления.

## Практические сценарии

### Сценарий 1: Восстановление PV после повреждения заголовка

Используется, если диск физически исправен, но LVM перестал распознавать его как PV (ошибка `unknown device` или `can't read LVM label`).

**Предварительная проверка:**
```bash
# Убедиться, что диск доступен в системе
lsblk /dev/sdb1
# -> NAME   MAJ:MIN RM SIZE RO TYPE MOUNTPOINT
# -> sdb1     8:17   0  50G  0 disk

# Проверить, не смонтирован ли он где-то
sudo lsof /dev/sdb1
# Если занят - отмонтировать/деактивировать перед восстановлением
```

**Шаг 1: Поиск UUID поврежденного тома**
UUID можно найти в последнем бэкапе метаданных в `/etc/lvm/backup/`.
```bash
sudo grep -A 10 "physical_volumes" /etc/lvm/backup/vg_data
# -> pv0 {
# ->     id = "XYZ-123-abc-..."
```

Альтернативный способ - поиск UUID в архиве:
```bash
# Если backup-файл поврежден, проверьте архив
ls -lt /etc/lvm/archive/vg_data_*.vg | head -5
# Найдите архив, созданный до инцидента
sudo grep "id =" /etc/lvm/archive/vg_data_00005-*.vg | head -5
```

**Шаг 2: Восстановление метки PV**
```bash
sudo pvcreate --uuid "XYZ-123-abc-..." --restorefile /etc/lvm/backup/vg_data /dev/sdb1
# -> Physical volume "/dev/sdb1" successfully created.
```

**Шаг 3: Восстановление структуры группы томов**
```bash
sudo vgcfgrestore vg_data
# -> Volume group "vg_data" successfully restored

sudo vgchange -ay vg_data
# -> 2 logical volume(s) in volume group "vg_data" now active
```

**Шаг 4: Проверка целостности данных**
```bash
# Проверка доступности LV
sudo lvs vg_data
# -> LV      VG      Attr       LSize   Pool Origin Data%  Meta%  Devices
# -> lv_data vg_data -wi-a----  50.00g                                       /dev/sdb1(0)
# -> lv_logs vg_data -wi-a----  10.00g                                       /dev/sdb1(12800)

# Монтирование и проверка ФС
sudo mount /dev/vg_data/lv_data /mnt/data
sudo fsck -n /dev/vg_data/lv_data
```

**Типичные ошибки:**
| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `PV not found with label lvm2` | UUID не совпадает | Проверьте UUID через `pvs -o pv_name,pv_uuid` |
| `Can't get physical volume size` | Повреждение суперблока диска | Используйте `ddrescue` для копирования диска перед восстановлением |
| `vgcfgrestore: not a VG` | Backup-файл поврежден | Попробуйте файл из `/etc/lvm/archive/` |

### Сценарий 2: Восстановление случайно удаленного LV

Если вы выполнили `lvremove`, данные на диске остаются целыми, пока экстенты не будут выделены под новый LV и затерты. **Чем меньше времени прошло с момента удаления - тем выше шанс на успех.**

**Критически важно: НЕ СОЗДАВАЙТЕ НОВЫЕ LV в этой VG до завершения восстановления!**

**Шаг 1: Поиск нужного архива**
Найдите файл архива, созданный непосредственно перед командой удаления.
```bash
sudo vgcfgrestore --list vg_data
# -> File: /etc/lvm/archive/vg_data_00005-98765.vg
# -> Description: Created before executing 'lvremove -f vg_data/lv_critical'
```

**Шаг 2: Тестовое и финальное восстановление**
```bash
# Проверка (рекомендуется)
sudo vgcfgrestore --test -f /etc/lvm/archive/vg_data_00005-98765.vg vg_data
# -> Test mode: metadata will NOT be written.

# Восстановление метаданных
sudo vgcfgrestore -f /etc/lvm/archive/vg_data_00005-98765.vg vg_data
# -> Volume group "vg_data" successfully restored

sudo vgchange -ay vg_data
# -> 2 logical volume(s) in volume group "vg_data" now active
```

**Шаг 3: Проверка целостности ФС после восстановления**
```bash
# Проверка файловой системы
sudo fsck -n /dev/vg_data/lv_critical
# Если fsck сообщает об ошибках:
sudo fsck -y /dev/vg_data/lv_critical

# Монтирование
sudo mount /dev/vg_data/lv_critical /mnt/recovered
ls /mnt/recovered/
```

**Предотвращение (Best Practice):**
- Настройте аудит команд LVM: `auditctl -w /usr/sbin/lvremove -p x -k lvm_lvremove`
- Используйте снимки перед опасными операциями (см. [LVM - Снимки](../snapshots.md))
- Документируйте все ручные операции с LV

### Сценарий 3: Перенос Swap с LV в файл (Освобождение VG)

Сценарий полезен, когда Swap занимает место в VG, необходимое для расширения других томов. Типичная ситуация: серверу нужно расширить LV с данными, но свободного места в VG нет, а Swap LV занимает 4-8 ГиБ.

**Предварительная проверка:**
```bash
# Проверка текущего Swap
sudo swapon --show
# -> NAME                  TYPE      SIZE USED PRIO
# -> /dev/vg_system/lv_swap partition   4G   0B   -2

# Проверка использования Swap
free -h
# ->              total        used        free      shared  buff/cache   available
# -> Swap:         4Gi          0B        4Gi
```

**Шаг 1: Отключение текущего Swap**
```bash
sudo swapoff -v /dev/vg_system/lv_swap
# -> swapoff /dev/vg_system/lv_swap
```

**Шаг 2: Создание файла подкачки**
```bash
sudo fallocate -l 4G /swapfile
# Если fallocate не поддерживается (некоторые ФС):
# sudo dd if=/dev/zero of=/swapfile bs=1M count=4096 status=progress

sudo chmod 600 /swapfile
sudo mkswap /swapfile
# -> Setting up swapspace version 1, size = 4 GiB (4294967296 bytes)
sudo swapon /swapfile
```

**Шаг 3: Обновление `/etc/fstab`**
Замените путь к LV на `/swapfile`:
```
# Было:
/dev/vg_system/lv_swap  none  swap  sw  0  0

# Стало:
/swapfile  none  swap  sw  0  0
```

**Шаг 4: Проверка работы нового Swap**
```bash
sudo swapon --show
# -> NAME      TYPE SIZE USED PRIO
# -> /swapfile file   4G   0B   -2

free -h | grep Swap
# -> Swap:         4Gi          0B        4Gi
```

**Шаг 5: Удаление старого LV**
```bash
sudo lvremove /dev/vg_system/lv_swap
# -> Do you really want to remove and DISCARD active logical volume "lv_swap"? [y/n]: y
# -> Logical volume "lv_swap" successfully removed.

# Проверка освободившегося места
sudo vgs vg_system
# -> VG       #PV #LV #SN Attr   VSize  VFree
# -> vg_system   1   3   0 wz--n- 50.00g 4.00g
```

**Ограничения и особые случаи:**
- Системы с Hibernation (suspend-to-disk) требуют Swap-раздел (файл не подходит без дополнительной настройки `resume=` в ядре).
- Для серверов без Hibernation swap-файл - полностью рабочая альтернатива.
- Если на системе используется zswap или zram, перенос Swap в файл безопасен.

### Сценарий 4: Передача пространства между VG (vgsplit + vgmerge)

Задача: передать диск (или его часть) из `vg_old` в `vg_new`. Используется при реорганизации хранилища, разделении нагрузки или подготовке к выводу сервера из эксплуатации.

**Шаг 1: Подготовка (pvmove)**
Если диск `/dev/sdc1` занят другими LV в `vg_old`, переместите данные с него:
```bash
# Проверка, какие LV используют данный PV
sudo pvs -o pv_name,lv_name,vg_name /dev/sdc1
# -> PV         VG     LV
# -> /dev/sdc1  vg_old lv_data

# Миграция данных с PV
sudo pvmove /dev/sdc1
# -> /dev/sdc1: Moved: 100.00%
```

**Шаг 2: Проверка готовности к разделению**
```bash
# Убедиться, что PV пуст
sudo pvs -o pv_name,vg_name,pv_free /dev/sdc1
# -> PV         VG     PFree
# -> /dev/sdc1  vg_old  50.00g   <- весь объём свободен

# Деактивировать все LV в целом PV (обязательно перед vgsplit)
sudo vgs -o lv_name,devices vg_old | grep sdc1
```

**Шаг 3: Отделение диска в новую временную группу**
```bash
sudo vgsplit vg_old vg_transfer /dev/sdc1
# -> Volume group "vg_transfer" successfully split from "vg_old"
```

**Шаг 4: Слияние групп**
```bash
sudo vgmerge vg_new vg_transfer
# -> Volume group "vg_transfer" successfully merged into "vg_new"

# Проверка результата
sudo vgs vg_new
# -> VG      #PV #LV #SN Attr   VSize  VFree
# -> vg_new    3   5   0 wz--n- 200.00g 50.00g
```

**Важные ограничения:**
- Все LV в переносимой VG должны быть деактивированы перед `vgsplit`.
- Если хотя бы один LV активен - `vgsplit` завершится с ошибкой.
- Между VG на разных хостах передача возможна только через `vgexport`/`vgimport`.

### Сценарий 5: Восстановление поврежденного Тонкого пула

Если тонкий пул не активируется из-за повреждения метаданных (например, после аварийного отключения питания или ошибки ввода-вывода).

**Шаг 1: Проверка состояния**
```bash
sudo lvs -a -o name,attr,metadata_percent,data_percent
# Атрибут 'M' (metadata out of space), 'D' (data problems) или отсутствие активации пула.

# Проверка логов на ошибки
sudo journalctl -k --since "1 hour ago" | grep -i "thin\|error\|lvm"
```

**Шаг 2: Автоматическое восстановление**
```bash
# Деактивация пула (если возможно)
sudo lvchange -an vg_data/thin_pool

# Попытка автоматического восстановления метаданных
sudo lvconvert --repair vg_data/thin_pool
```

**Шаг 3: Ручное восстановление (если автоматическое не помогло)**
```bash
# 1. Создание нового LV для метаданных
sudo lvcreate -n new_tmeta -L 2G vg_data

# 2. Копирование метаданных с помощью thin_repair
sudo thin_repair -i /dev/mapper/vg_data-thin_pool_tmeta -o /dev/mapper/vg_data-new_tmeta

# 3. Подмена метаданных
sudo lvconvert --thinpool vg_data/thin_pool --poolmetadata vg_data/new_tmeta

# 4. Активация пула
sudo lvchange -ay vg_data/thin_pool
```

**Шаг 4: Проверка данных**
```bash
# Проверка доступности LV в пуле
sudo lvs vg_data
# -> LV       VG      Attr       LSize   Pool       Origin Data%  Meta%
# -> thin_lv  vg_data Vwi-a-t-- 100.00g thin_pool          45.23

# Монтирование и проверка ФС
sudo mount /dev/vg_data/thin_lv /mnt/data
```

**Предотвращение:**
- Всегда используйте RAID1 для metadata LV тонкого пула (см. [LVM - Расширенные темы](./advanced_topics.md#raid-и-thin-provisioning)).
- Включите `dmeventd` и настройте `thin_pool_autoextend_threshold = 80`.
- Регулярно проверяйте `data_percent` и `metadata_percent`.

### Сценарий 6: Восстановление деградированного LVM RAID

Если один из дисков в LVM RAID 1/5/6/10 вышел из строя.

**Шаг 1: Идентификация сбойного PV**
```bash
sudo lvs -a -o name,copy_percent,devices
# -> raid_lv  100.00  [raid_lv_rimage_0](0), [raid_lv_rimage_1](unknown)
#                                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#                                    Unknown device - сбойный диск
```

**Шаг 2: Вставка нового диска (если доступен)**
```bash
# Добавление нового диска в RAID
sudo lvconvert --replace /dev/sdb1 /dev/sdd1 vg_data/raid_lv

# Или, если новый диск ещё не в VG:
sudo pvcreate /dev/sdd1
sudo vgextend vg_data /dev/sdd1
sudo lvconvert --replace /dev/sdb1 /dev/sdd1 vg_data/raid_lv
```

**Шаг 3: Если новый диск недоступен - вывод missing PV**
```bash
# Только для RAID1 (одно зеркало потеряно) или RAID5 (один диск потерян)
sudo vgreduce --removemissing --force vg_data
# -> WARNING: Removing partial LV raid_lv_rimage_1.
# -> Volume group "vg_data" successfully reduced

# Если VG не активируется:
sudo vgchange -ay --partial vg_data
# -> Activation of logical volume "vg_data" is not complete.
```

**Шаг 4: Проверка состояния после восстановления**
```bash
sudo lvs -o name,attr,copy_percent vg_data
# -> raid_lv  rwi-a-r--  45.23   <- rebuild в процессе
```

**Важно:** Во время rebuild производительность снижается. Не откладывайте rebuild - чем дольше массив в degraded mode, тем выше риск второго отказа.

### Сценарий 7: Восстановление ФС в режиме Read-Only (аварийный remount)

Типичная ситуация для SRE: файловая система автоматически переключилась в режим `ro` из-за ошибок ввода-вывода, повреждения thin pool или снятия снимка.

**Шаг 1: Диагностика причины**
```bash
# Проверка текущего состояния
mount | grep vg_data
# -> /dev/vg_data/lv_data on /mnt/data type ext4 (ro,relatime,errors=remount-ro)

# Проверка journal на ошибки
sudo journalctl -k --since "1 hour ago" | grep -i "error\|readonly\|remount\|abort"

# Проверка dmesg
dmesg | grep -i "ext4\|xfs\|error\|readonly" | tail -20

# Проверка состояния thin pool (если используется)
sudo lvs -o lv_name,attr,data_percent,metadata_percent vg_data/thin_pool
```

**Шаг 2: Устранение причины**
```bash
# Если thin pool заполнен:
sudo lvextend -L +10G /dev/vg_data/thin_pool
sudo lvchange -ay /dev/vg_data/thin_pool

# Если thin pool metadata заполнены:
sudo lvextend -L +1G /dev/vg_data/thin_pool_tmeta
```

**Шаг 3: Переключение обратно в rw (без перезагрузки)**
```bash
# Remount в режим чтения/записи
sudo mount -o remount,rw /mnt/data

# Проверка
mount | grep vg_data
# -> /dev/vg_data/lv_data on /mnt/data type ext4 (rw,relatime,errors=remount-ro)
```

**Шаг 4: Запуск fsck (если remount не помог)**
```bash
# Для ext4 - отмонтировать и запустить fsck
sudo umount /dev/vg_data/lv_data
sudo fsck -y /dev/vg_data/lv_data
sudo mount /dev/vg_data/lv_data /mnt/data

# Для XFS - используется xfs_repair (требует отмонтирования)
sudo umount /dev/vg_data/lv_xfs
sudo xfs_repair /dev/vg_data/lv_xfs
sudo mount /dev/vg_data/lv_xfs /mnt/data_xfs
```

**Типичные причины переключения в ro:**
| Причина | Признак | Решение |
| :--- | :--- | :--- |
| Thin pool заполнен | `thin_pool` data_percent > 100% | Расширить thin pool |
| I/O ошибки диска | `dmesg` содержит `I/O error` | Заменить диск, проверить SMART |
| Несогласованность ФС | `fsck` находит ошибки | Запустить fsck/reboot |
| Panic ядра из-за ФС | `kernel panic - VFS: Unable to mount root` | Live CD + fsck |

### Сценарий 8: Конвертация Thick LV в Thin LV (онлайн)

Позволяет преобразовать обычный (толстый) логический том в тонкий без остановки сервиса и потери данных.

**Предварительная проверка:**
```bash
# Проверка исходного LV
sudo lvs vg_data/lv_data
# -> LV      VG      Attr       LSize   Pool Origin Data%  Meta%
# -> lv_data vg_data -wi-a---- 100.00g

# Проверка наличия thin pool (или создание нового)
sudo lvs vg_data | grep thin
# Если thin pool нет - создайте (см. thin-provisioning.md)
```

**Шаг 1: Конвертация**
```bash
# Конвертация существующего LV в thin volume с выделением из thin pool
sudo lvconvert --type thin --thinpool vg_data/thin_pool vg_data/lv_data
# -> Logical volume vg_data/lv_data successfully converted.
```

**Шаг 2: Проверка**
```bash
sudo lvs vg_data/lv_data
# -> LV      VG      Attr       LSize   Pool       Origin Data%  Meta%
# -> lv_data vg_data Vwi-a-t-- 100.00g thin_pool          12.34
```

**Важно:** Данные на LV остаются на месте. LV теперь потребляет физическое пространство из thin pool динамически. Оригинальные данные占据 место в thin pool.

### Сценарий 9: Аварийное восстановление через Live CD (полный цикл)

Полноценный сценарий восстановления сервера с LVM при невозможности загрузки ОС.

**Шаг 1: Загрузка с Live CD и обнаружение VG**
```bash
# Загрузка с Live CD (Ubuntu/Debian)
sudo vgchange -ay
# -> 2 logical volume(s) in volume group "vg_data" now active

# Если VG не виден:
sudo pvscan
sudo vgscan
# Если pvscan не находит PV:
sudo pvscan --listunsupported
```

**Шаг 2: Если VG не активируется - восстановление метаданных**
```bash
# Восстановление из backup
sudo vgcfgrestore vg_data

# Или, если backup-файл недоступен - из archive
sudo vgcfgrestore --list vg_data
sudo vgcfgrestore -f /etc/lvm/archive/vg_data_00005-98765.vg vg_data

# Активация
sudo vgchange -ay vg_data
```

**Шаг 3: Если PV повреждён - восстановление UUID**
```bash
# Найти UUID из backup
sudo grep "id =" /etc/lvm/backup/vg_data | head -1

# Восстановление PV
sudo pvcreate --uuid "XYZ-123-abc-..." --restorefile /etc/lvm/backup/vg_data /dev/sdb1

# Восстановление VG
sudo vgcfgrestore vg_data
sudo vgchange -ay vg_data
```

**Шаг 4: Монтирование и копирование данных**
```bash
sudo mount /dev/vg_data/lv_data /mnt/recovery
sudo tar czf /external/backup_$(date +%Y%m%d).tar.gz -C /mnt/recovery .

# Или для прямого доступа:
sudo chroot /mnt/recovery
```

**Шаг 5: Проверка целостности после восстановления**
```bash
# Fsck на каждом LV
sudo fsck -n /dev/vg_data/lv_data
sudo fsck -n /dev/vg_data/lv_logs

# Бэкап метаданных
sudo vgcfgbackup vg_data
```

### Сценарий 10: Мониторинг LVM и оповещения (SRE Alerting Script)

Скрипт для периодической проверки состояния LVM и отправки оповещений при обнаружении проблем.

```bash
#!/bin/bash
# /usr/local/sbin/lvm_health_check.sh
# Проверка здоровья LVM-структур и отправка оповещений
# Рекомендуемый интервал: cron каждые 5 минут

set -euo pipefail

LOG_FILE="/var/log/lvm_health.log"
ALERT_EMAIL="sre-team@example.com"
WARN_THRESHOLD_DATA=80
WARN_THRESHOLD_META=80
WARN_THRESHOLD_SNAP=75

log_msg() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

send_alert() {
    local subject="$1"
    local body="$2"
    echo "$body" | mail -s "LVM ALERT: $subject" "$ALERT_EMAIL" 2>/dev/null || \
        logger -t lvm_health "ALERT: $subject - $body"
}

# 1. Проверка thin pool
while IFS= read -r line; do
    pool_name=$(echo "$line" | awk '{print $1}')
    data_pct=$(echo "$line" | awk '{print $2}')
    meta_pct=$(echo "$line" | awk '{print $3}')

    if (( $(echo "$data_pct > $WARN_THRESHOLD_DATA" | bc -l) )); then
        send_alert "Thin Pool Data High" "Pool $pool_name: data=${data_pct}%"
    fi
    if (( $(echo "$meta_pct > $WARN_THRESHOLD_META" | bc -l) )); then
        send_alert "Thin Pool Metadata High" "Pool $pool_name: meta=${meta_pct}%"
    fi
done < <(sudo lvs --noheadings -o lv_name,data_percent,metadata_percent 2>/dev/null | grep -v "^$")

# 2. Проверка снимков
while IFS= read -r line; do
    snap_name=$(echo "$line" | awk '{print $1}')
    snap_pct=$(echo "$line" | awk '{print $2}')

    if (( $(echo "$snap_pct > $WARN_THRESHOLD_SNAP" | bc -l) )); then
        send_alert "Snapshot Full" "Snapshot $snap_name: ${snap_pct}% used"
    fi
done < <(sudo lvs --noheadings -o lv_name,snap_percent 2>/dev/null | grep -v "^$" | awk '$2 != ""')

# 3. Проверка деградации RAID
while IFS= read -r line; do
    lv_name=$(echo "$line" | awk '{print $1}')
    copy_pct=$(echo "$line" | awk '{print $2}')
    if [[ "$copy_pct" != "100.00" ]]; then
        send_alert "RAID Degraded" "LV $lv_name: copy_percent=${copy_pct}%"
    fi
done < <(sudo lvs --noheadings -o lv_name,copy_percent 2>/dev/null | grep -v "^$" | awk '$2 != ""')

# 4. Проверка free space в VG
while IFS= read -r line; do
    vg_name=$(echo "$line" | awk '{print $1}')
    free_pct=$(echo "$line" | awk '{print $2}')
    if (( $(echo "$free_pct < 10" | bc -l) )); then
        send_alert "VG Low Space" "VG $vg_name: ${free_pct}% free"
    fi
done < <(sudo vgs --noheadings -o vg_name,vg_free --units g 2>/dev/null | awk '{printf "%s %.0f\n", $1, ($2+0)}')

log_msg "Health check completed"
```

Настройка cron:
```bash
# Добавить в /etc/cron.d/lvm_health
*/5 * * * * root /usr/local/sbin/lvm_health_check.sh
```

## Типичные ошибки и их решение

### Восстановление метаданных не удается

**Причина:** Все backup/archive файлы повреждены или отсутствуют.

**Решение:**
```bash
# Поиск UUID PV на самом диске
sudo pvs -o pv_name,pv_uuid

# Или через hexdump (если pvs не видит PV)
sudo hexdump -C /dev/sdb1 | head -5
# LVM-метка начинается с байта 0x01 в смещении 0x0010

# Аварийное удаление VG (потеря всех данных в VG)
sudo vgremove --force vg_data
# Пересоздание VG и восстановление данных из бэкапа
```

### `vgcfgrestore` пишет "not aVG"

**Причина:** Файл backup содержит некорректные метаданные.

**Решение:**
```bash
# Проверка формата backup-файла
head -20 /etc/lvm/backup/vg_data
# Файл должен начинаться с "vg_data {"

# Использование archive-файла вместо backup
sudo vgcfgrestore --list vg_data
# Выберите archive-файл перед проблемной операцией
```

### `thin_repair` не помогает

**Причина:** Повреждены не только метаданные, но и данные thin pool.

**Решение:**
```bash
# Попытка восстановления через dump + repair
sudo thin_dump /dev/mapper/vg_data-thin_pool_tmeta > /tmp/meta_dump.xml
sudo thin_restore -i /tmp/meta_dump.xml -o /dev/mapper/vg_data-new_tmeta

# Если и это не помогает - данные на thin LV могут быть потеряны
# Восстановление из внешнего бэкапа - единственный вариант
```

## Дополнительная информация

### Best Practices для SRE/DevOps

1. **Регулярные бэкапы метаданных:** Настройте cron для `vgcfgbackup` всех VG каждые 6 часов. Храните копии на отдельном сервере.
2. **Документирование схемы:** Ведите актуальную схему PV/VG/LV для каждого сервера (в Wiki или Git).
3. **Тестирование восстановления:** Раз в квартал выполняйте восстановление на тестовом стенде из бэкапов.
4. **Мониторинг:** Настройте алертинг на thin pool > 80%, snapshot > 75%, VG free < 10%, RAID degraded.
5. **Не используйте снимки как permanent storage:** Снимки - временный инструмент для бэкапов и откатов.

### См. также
- **[LVM - Расширенные темы](./advanced_topics.md)** - фильтры `lvm.conf`, загрузка и RAID.
- **[LVM - Тонкое провизионирование](../thin-provisioning.md)** - архитектура и мониторинг пулов.
- **[LVM - Замена диска](../operations/lvm_disk_replacement.md)** - плановая миграция через `pvmove`.
