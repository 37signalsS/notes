# Создание PV, VG и LV

## Определения

**PV (Physical Volume — физический том)** — диск, раздел или блочное устройство (например, LUKS-контейнер, RAID-массив mdadm), инициализированное для работы в LVM. Содержит LVM-метку (magic number), идентификатор UUID и область метаданных (MDA). Допустимо создавать PV на целых дисках (`/dev/sdX`) или разделах (`/dev/sdX1`).

**VG (Volume Group — группа томов)** — виртуальный пул хранения, объединяющий один или несколько PV. Представляет собой единое адресное пространство с фиксированным размером физического экстента (PE). VG является основной единицей управления ресурсами: все LV создаются из пространства VG.

**LV (Logical Volume — логический том)** — виртуальный блочный раздел, создаваемый внутри VG. Для операционной системы LV выглядит как обычный диск (`/dev/VG_NAME/LV_NAME` или `/dev/mapper/VG_NAME-LV_NAME`). Поддерживает 다양한 типы: linear, striped, mirror, raid, thin, cache, snapshot.

**PE (Physical Extent — физический экстент)** — минимальный блок данных в VG (по умолчанию **4 МиБ**). Размер PE задаётся при создании VG (`vgcreate -s`) и не может быть изменён позже. Все операции изменения размера LV кратны размеру PE. Для очень больших массивов (10+ ТБ) рекомендуется увеличивать до 32–128 МиБ.

**MDA (Metadata Area — область метаданных)** — участок диска (по умолчанию 1 МиБ), содержащий информацию о структуре VG в текстовом формате ASCII. Расположена в кольцевом буфере: при каждом изменении VG LVM записывает новую копию в следующий слот, сохраняя предыдущие версии. Резервные копии хранятся в `/etc/lvm/archive/`.

## Базовые концепции

### Иерархия уровней LVM

Процесс абстракции дискового пространства:

```
Физический носитель → Physical Volume (PV) → Volume Group (VG) → Logical Volume (LV) → Файловая система
```

| Уровень | Масштаб | Управление |
| :--- | :--- | :--- |
| **Block Device** | Физический диск / раздел | Ядро Linux, udev |
| **PV** | Один диск / раздел | `pvcreate`, `pvremove`, `pvdisplay` |
| **VG** | Пул из одного или нескольких PV | `vgcreate`, `vgextend`, `vgreduce`, `vgremove` |
| **LV** | Виртуальный раздел из VG | `lvcreate`, `lvextend`, `lvreduce`, `lvremove` |

### Ключевые принципы инициализации

- **Очистка сигнатур (`wipefs`):** Перед созданий PV рекомендуется выполнить `wipefs --all`, чтобы удалить сигнатуры RAID (superblock), файловых систем (ext4, XFS), LUKS, старого LVM или других меток. Остаточные сигнатуры могут конфликтовать с LVM-меткой и приводить к ошибкам при поиске устройств (`pvscan`, `vgscan`).

- **Размер метаданных (`--metadatasize`):** По умолчанию 1 МиБ. Для групп с сотнями LV, множественных VG или сложной структуры рекомендуется увеличивать до 2–4 МиБ при создании PV. Увеличение метаданных не влияет на производительность, но снижает риск исчерпания пространства MDA.

- **Выравнивание (`--dataalignment`):** LVM автоматически выравнивает данные по границам экстентов. На SSD и RAID-массивах рекомендуется проверять соответствие размера PE физическому блоку устройства (512 байт, 4 КиБ) или страйпу RAID. Неправильное выравнивание снижает производительность.

- **Размер PE:** Задаётся при создании VG (`vgcreate -s`). Для массивов <1 ТБ стандартный 4 МиБ оптимален. Для массивов 10+ ТБ увеличение до 32–128 МиБ ускоряет работу `vgs`, `lvs`, `pvmove` и других инструментов, поскольку уменьшается количество экстентов для обработки.

- **UUID:** Каждый PV, VG и LV получает уникальный UUID при создании. UUID сохраняется в метаданных и используется для идентификации при восстановлении, перемещении или реорганизации.

### Основные типы логических томов

| Тип | Флаг / Параметр | Описание | Минимальное кол-во PV |
| :--- | :--- | :--- | :--- |
| **Linear** | По умолчанию | Последовательное заполнение PV. Если LV больше одного PV, данные записываются последовательно. | 1 |
| **Striped** | `-i <кол-во>` | RAID 0 (чередование) для повышения скорости. Данные разбиваются на полосы по PV. | 2+ |
| **Mirror** | `--type mirror` | Зеркалирование через device-mapper. Полная копия данных на каждом PV. | 2+ |
| **RAID 1** | `--type raid1` | Зеркалирование через dm-raid. Рекомендуется вместо `mirror` (более стабильный, поддерживает rebuild). | 2+ |
| **RAID 5** | `--type raid5` | Баланс между ёмкостью и отказоустойчивостью. Потеря 1 диска без потери данных. | 3+ |
| **RAID 6** | `--type raid6` | Двойная чётность. Потеря 2 дисков без потери данных. | 4+ |
| **RAID 10** | `--type raid10` | Комбинация RAID 1 + RAID 0. Высокая производительность и отказоустойчивость. | 4+ |
| **Thin** | `--thin` | Тонкое провизионирование (выделение по требованию). Требует создания thin pool. | 1 |
| **Cache** | `--type cache` | Кэширование через dm-cache. Требует fast device (NVMe/SSD) как cache pool. | 2 |

### Параметры pvcreate

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `--metadatasize <размер>` | Размер области метаданных (по умолчанию 1M) | Использовать 2M для VG с >50 LV |
| `--dataalignment <смещение>` | Выравнивание данных | Проверять на SSD/RAID: `--dataalignment 1M` |
| `--uuid <UUID>` | Задать конкретный UUID | Использовать только при восстановлении |
| `--restorefile <файл>` | Восстановление PV из backup | Использовать с `--uuid` при восстановлении |
| `--force` | Принудительное создание | Использовать только при восстановлении (ignores existing signatures) |
| `--yes` | Пропустить подтверждение | Для автоматизации скриптов |
| `--labelsector <сектор>` | Позиция LVM-метки (по умолчанию 1) | Изменять только при конфликте с other metadata |
| `--config 'devices{...}'` | Временные параметры конфигурации | Для переопределения фильтров на лету |

### Параметры vgcreate

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `-s <размер>` | Размер Physical Extent | Для массивов >10 ТБ: `-s 32M` или `-s 128M` |
| `--maxlogicalvolumes <число>` | Максимальное число LV (0 = без ограничений) | Использовать для ограничения в shared-средах |
| `--maxphysicalvolumes <число>` | Максимальное число PV (0 = без ограничений) | Ограничение для кластеров |
| `--addtag <тег>` | Добавить тег к VG | Полезно для группировки (prod, dev, test) |
| `--alloc <политика>` | Политика распределения: `normal`, `contiguous`, `cling`, `anywhere` | `normal` для большинства случаев |
| `--foreign` | Разрешить создание VG с "чужими" PV | Для миграции между VG |

### Параметры lvcreate

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `-L <размер>` | Размер LV в единицах (k, m, g, t) | Использовать для точного размера |
| `-l <число экстентов>` | Размер LV в экстентах | `-l +100%FREE` для использования всего свободного места |
| `-n <имя>` | Имя LV | Следовать соглашению об именовании |
| `-i <число>` | Количество полос (striped) | Для striped: равномерно по PV |
| `-I <размер>` | Размер полосы striped | Проверять с физическим блоком устройства |
| `--type <тип>` | Тип LV | `raid1`, `raid5`, `raid6`, `raid10`, `thin`, `cache`, `mirror` |
| `-m <число зеркал>` | Количество зеркал (mirror) | Для `--type mirror`: 1 зеркало = 2 копии |
| `--contiguous` | Непрерывное распределение | Улучшает производительность на HDD |
| `--permission <доступ>` | Права доступа: `rw` (по умолчанию), `r` (read-only) | `r` для снимков и резервных копий |
| `--readahead <значение>` | Предчтение: `none`, `auto`, или число секторов | `auto` для большинства случаев |
| `--discards <режим>` | Обработка discards: `passdown`, `nop`, `ignore` | `passdown` для SSD, `nop` для HDD |
| `-Z <y/n>` | Зануление первого блока (по умолчанию `y`) | `n` только для восстановления данных |
| `-W <y/n>` | Зануление всего LV (по умолчанию `y`) | `n` ускоряет создание, но небезопасно |
| `-V <размер>` | Виртуальный размер для thin volume | Использовать с `--thin` |

## Практические сценарии

### Сценарий 1: Подготовка нового диска (полный цикл)

Пошаговый процесс от подключения диска до монтирования файловой системы с проверкой на каждом этапе.

**Шаг 1: Идентификация диска**
```bash
lsblk
# → NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINTS
# → sdb    8:16    0   20G  0 disk

ls -la /dev/disk/by-id/ | grep sdb
# → lrwxrwxrwx 1 root root  9 ... ../../sdb
```

**Шаг 2: Очистка сигнатур и инициализация PV**
```bash
sudo wipefs --all /dev/sdb
# → /dev/sdb: 2 bytes were erased at offset 0x00000438 (ext4)

sudo pvcreate --metadatasize 2M /dev/sdb
# → Physical volume "/dev/sdb" successfully created.

# Проверка
sudo pvs /dev/sdb
# → PV         VG   Fmt  Attr PSize   PFree
# → /dev/sdb        lvm2 ---  <20.00g <20.00g
```

**Шаг 3: Создание VG**
```bash
sudo vgcreate vg_data /dev/sdb
# → Volume group "vg_data" successfully created

# Проверка
sudo vgs vg_data
# → VG      #PV #LV #SN Attr   VSize   VFree
# → vg_data   1   0   0 wz--n- <20.00g <20.00g
```

**Шаг 4: Создание LV**
```bash
sudo lvcreate -n lv_db -L 10G vg_data
# → Logical volume "lv_db" created.

# Проверка
sudo lvs vg_data
# → LV    VG      Attr       LSize   Pool Origin Data%  Meta%
# → lv_db vg_data -wi-a----- 10.00g
```

**Шаг 5: Создание файловой системы и монтирование**
```bash
sudo mkfs.ext4 /dev/vg_data/lv_db
sudo mkdir -p /mnt/db
sudo mount /dev/vg_data/lv_db /mnt/db

# Добавление в /etc/fstab
echo '/dev/vg_data/lv_db /mnt/db ext4 defaults 0 2' | sudo tee -a /etc/fstab
```

**Шаг 6: Финальная проверка**
```bash
df -h /mnt/db
# → Filesystem                  Size  Used Avail Use% Mounted on
# → /dev/mapper/vg_data-lv_db   10G   24K  9.8G   1% /mnt/db

mount | grep lv_db
# → /dev/mapper/vg_data-lv_db on /mnt/db type ext4 (rw,relatime)
```

### Сценарий 2: Создание VG из нескольких PV

В production-среде VG часто создается из нескольких дисков для увеличения общего пула.

```bash
# Подготовка двух дисков
sudo wipefs --all /dev/sdb /dev/sdc
sudo pvcreate /dev/sdb /dev/sdc
# → Physical volume "/dev/sdb" successfully created.
# → Physical volume "/dev/sdc" successfully created.

# Создание VG из двух PV
sudo vgcreate vg_data /dev/sdb /dev/sdc
# → Volume group "vg_data" successfully created

# Проверка распределения
sudo pvs -o pv_name,vg_name,pv_size,pv_free
# → PV         VG      PSize   PFree
# → /dev/sdb   vg_data <20.00g <20.00g
# → /dev/sdc   vg_data <20.00g <20.00g

sudo vgs vg_data
# → VG      #PV #LV #SN Attr   VSize  VFree
# → vg_data   2   0   0 wz--n- 39.99g 39.99g
```

### Сценарий 3: Создание LV с указанием конкретного PV

По умолчанию LVM распределяет LV по всем PV в VG. Для ограничения использования определённого PV:

```bash
# LV будет создан только на /dev/sdb
sudo lvcreate -n lv_db -L 10G vg_data /dev/sdb

# Проверка
sudo lvs -o lv_name,devices vg_data
# → LV    Devices
# → lv_db /dev/sdb(0-2559)

# LV будет создан на обоих PV (по умолчанию)
sudo lvcreate -n lv_app -L 15G vg_data
sudo lvs -o lv_name,devices vg_data
# → LV    Devices
# → lv_db /dev/sdb(0-2559)
# → lv_app /dev/sdc(0-3839),/dev/sdb(2560-6399)
```

### Сценарий 4: Создание LV с использованием всех свободных экстентов

Вместо указания точного размера можно выделить всё свободное место:

```bash
# Использовать все свободные PE в VG
sudo lvcreate -n lv_data -l +100%FREE vg_data

# Проверка
sudo vgs vg_data
# → VG      #PV #LV #SN Attr   VSize  VFree
# → vg_data   2   1   0 wz--n- 39.99g    0

sudo lvs vg_data
# → LV      VG      Attr       LSize  Pool Origin Data%  Meta%
# → lv_data vg_data -wi-a----- 39.99g
```

### Сценарий 5: Создание LV с чередованием (Performance)

Требуется как минимум два физических носителя. Чередование (striping) распределяет данные по PV для увеличения пропускной способности.

```bash
# Создание VG из двух дисков
sudo vgcreate vg_perf /dev/sdc /dev/sdd

# Создание Striped LV: 2 полосы (-i 2), размер полосы 64K (-I 64k)
sudo lvcreate -i 2 -I 64k -L 40G -n lv_high_perf vg_perf
# → Logical volume "lv_high_perf" created.

# Проверка конфигурации striped
sudo lvs -o lv_name,stripe_count,stripe_size,devices vg_perf
# → LV            #Str Stripe Size Devices
# → lv_high_perf     2      64.00k /dev/sdd(0-5119),/dev/sdc(0-5119)
```

> **Примечание:** Размер полосы striped (`-I`) должен быть кратен физическому блоку устройства. Для SSD оптимально 64K–256K.

### Сценарий 6: Создание RAID 1 (зеркало)

```bash
# Создание VG на двух дисках
sudo vgcreate vg_mirror /dev/sdb /dev/sdc

# Создание RAID 1 LV с одним зеркалом (-m 1)
sudo lvcreate --type raid1 -m 1 -n lv_critical -L 5G vg_mirror

# Проверка состояния
sudo lvs -o lv_name,lv_attr,copy_percent,devices vg_mirror
# → LV         Attr       Copy% Devices
# → lv_critical rwi-aor--- 100.00 /dev/sdb(0-1279),/dev/sdc(0-1279)
```

> **Примечание:** `Copy%` показывает прогресс синхронизации. При 100% массив fully synced.

### Сценарий 7: Создание LV на разделе (partitioned disk)

Когда использования целого диска невозможно (двойная загрузка, зарезервированное пространство):

```bash
# Создание раздела (GPT)
sudo parted /dev/sdb mklabel gpt
sudo parted /dev/sdb mkpart primary 1MiB 10GiB
sudo parted /dev/sdb mkpart primary 10GiB 100%

# Инициализация PV на разделах
sudo pvcreate /dev/sdb1 /dev/sdb2

# Создание VG
sudo vgcreate vg_data /dev/sdb1 /dev/sdb2
```

### Сценарий 8: Создание PV на LUKS-контейнере

LVM может работать поверх LUKS-шифрования. Сначала создаётся зашифрованный контейнер, затем — PV.

```bash
# Шифрование диска
sudo cryptsetup luksFormat /dev/sdb
sudo cryptsetup luksOpen /dev/sdb encrypted_sdb

# Создание PV на расшифрованном устройстве
sudo pvcreate /dev/mapper/encrypted_sdb

# Создание VG
sudo vgcreate vg_secure /dev/mapper/encrypted_sdb

# Создание LV
sudo lvcreate -n lv_data -L 50G vg_secure
```

> **Примечание:** При использовании LVM-over-LUKS потребуется дополнительная настройка initramfs для автоматического расшифрования при загрузке.

### Сценарий 9: Создание LV с дополнительными параметрами

```bash
# LV с непрерывным распределением (contiguous) — улучшает производительность на HDD
sudo lvcreate -n lv_sequential -L 20G --contiguous vg_data

# LV только для чтения (для снимков или резервных копий)
sudo lvcreate -n lv_backup -L 10G --permission r vg_data

# LV с увеличенным readahead (для последовательных чтений)
sudo lvcreate -n lv_stream -L 50G --readahead 256 vg_data

# LV без зануления (для восстановления данных)
sudo lvcreate -n lv_raw -L 1G -Z n vg_data

# Thin volume (тонкий том) — выделение по требованию
sudo lvcreate -L 100G --poolmetadatasize 1G --chunksize 256K --thinpool tp_data vg_data
sudo lvcreate -V 1T --thin -n lv_app vg_data/tp_data
```

### Сценарий 10: Тонкое провизионирование — создание thin pool и thin volume

Для динамического выделения места ( Thin Provisioning )池 создаётся отдельно, а тома — внутри пула.

```bash
# Шаг 1: Создание thin pool (100 ГБ данных + 1 ГБ метаданных)
sudo lvcreate -L 100G --poolmetadatasize 1G --thinpool tp_data vg_data
# → Logical volume "tp_data" created.

# Шаг 2: Создание thin volume (виртуальный размер 1 ТБ)
sudo lvcreate -V 1T --thin -n lv_app vg_data/tp_data
# → Logical volume "lv_app" created.

# Шаг 3: Проверка
sudo lvs -o lv_name,lv_size,data_percent,metadata_percent,lv_attr vg_data
# → LV      LSize    Data%  Meta%  Attr
# → tp_data 100.00g   0.01   1.00  twi-aotz--
# → lv_app    1.00t   0.01         Vwi-aotz--
```

> **Подробнее:** [LVM — Тонкое провизионирование](../thin-provisioning.md) — автоматическое расширение, мониторинг, восстановление.

### Сценарий 11: Undo-операции (pvremove, vgremove, lvremove)

При ошибке или изменении плана необходимо корректное удаление объектов.

```bash
# Удаление LV (том должен быть неактивным и не смонтирован)
sudo umount /mnt/db
sudo lvremove /dev/vg_data/lv_db
# → Do you really want to remove and DISCARD active logical volume "lv_db"? [y/n]: y
# → Logical volume "lv_db" successfully removed.

# Удаление VG (все LV должны быть удалены)
sudo vgremove vg_data
# → Volume group "vg_data" successfully removed

# Удаление PV (данные не удаляются, но LVM-метка стирается)
sudo pvremove /dev/sdb
# → Labels on physical volume "/dev/sdb" successfully wiped.
```

> **Важно:** `pvremove` не удаляет данные с диска — он только стирает LVM-метку. Для безопасного удаления данных используйте `shred` или `wipefs`.

### Сценарий 12: Соглашение об именовании

Рекомендуемые соглашения для production-сред:

| Объект | Формат | Пример | Назначение |
| :--- | :--- | :--- | :--- |
| **VG** | `vg_<назначение>` | `vg_data`, `vg_backup` | Общее хранилище данных |
| **VG** | `vg_<среда>_<назначение>` | `vg_prod_db`, `vg_dev_web` | Раздельные среды |
| **LV** | `lv_<назначение>` | `lv_db`, `lv_logs` | Логические тома |
| **LV** | `lv_<сервис>_<тип>` | `lv_mysql_data`, `lv_nginx_conf` | Детализация по сервисам |
| **Thin Pool** | `tp_<назначение>` | `tp_data`, `tp_vm` | Пулы тонкого провизионирования |
| **Snapshot** | `snap_<lv>_<дата>` | `snap_lv_db_20260913` | Снимки с датой |

## Дополнительная информация

### Лучшие практики

1. **Проверка после каждого шага:** Используйте `pvs`, `vgs`, `lvs` после каждой операции создания для подтверждения результата.

2. **Оптимальный размер PE:**
   - < 1 ТБ: 4 МиБ (по умолчанию)
   - 1–10 ТБ: 8–16 МиБ
   - > 10 ТБ: 32–128 МиБ

3. **Использование `--metadatasize 2M`:** Для VG с потенциалом >50 LV или дляVG, который будет расширяться множественными `vgextend`.

4. **Выравнивание на SSD/RAID:** Проверяйте `--dataalignment` перед созданием PV. Неправильное выравнивание снижает IOPS на 10–30%.

5. **Именование:** Следуйте соглашению (Сценарий 12). Изменение имён в production затруднено.

6. **Резервное копирование метаданных:** После создания VG выполните `sudo vgcfgbackup vg_data`. Метаданные хранятся в `/etc/lvm/backup/` и `/etc/lvm/archive/`.

7. **Избегайте `-Z n` в production:** Зануление первого блока защищает от утечки данных. Отключайте только при восстановлении.

8. **Документирование:** Фиксируйте конфигурацию: `sudo vgdisplay -v vg_data > /root/vg_data_config.txt`.

### Граничные случаи и ограничения

1. **PV на целом диске vs. разделе:** Использование целого диска (`/dev/sdb`) упрощает расширение, но не совместимо с dual-boot. Разделы (`/dev/sdb1`) безопаснее, но требуют `partprobe` после изменений.

2. **Удаление PV из VG:** `pvremove` невозможен, если PV содержит данные LV. Используйте `pvmove` для миграции данных перед удалением.

3. **VG с одним PV:** VG с единственным PV не является отказоустойчивым. Рекомендуется минимум 2 PV для критичных данных.

4. **Thin pool满:** При заполнении thin pool на 100% все LV в пуле переходят в read-only. Рекомендуется настроить `thin_pool_autoextend_threshold`.

5. **Конфликт UUID:** При клонировании дисков могут возникнуть дубликаты UUID. Используйте `pvcreate --uuid <новый> --restorefile` для переопределения.

6. **RAID на SSD:** Использование RAID 5/6 на SSD снижает производительность записи из-за чётности. Рассмотрите RAID 10.

7. **Nested LVM:** LVM-on-LVM (PV на LV) поддерживается, но не рекомендуется без крайней необходимости (сложность восстановления).

### Устранение неполадций

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `pvcreate` не удаётся: "contains a filesystem" | Остаточная сигнатура | `wipefs --all /dev/sdX`, затем повторить |
| `pvcreate` не удаётся: "device is mounted" | Устройство смонтировано | `umount /dev/sdX`, затем повторить |
| `vgcreate` не удаётся: "PV has duplicate UUID" | Клонированный диск | `pvcreate --uuid <новый> --restorefile` |
| `lvcreate` не удаётся: "not enough free extends" | Недостаточно места в VG | `vgs vg_data` для проверки VFree |
| `lvcreate` не удаётся: "insufficient suitable allocatable extents" | Политика распределения | Попробовать `--alloc anywhere` (не для production) |
| `lvcreate --type raid1` не удаётся: "not enough PVs" | Мало PV для RAID | Требуется минимум 2 PV |
| `vgcreate -s` не удаётся: "invalid physical extent size" | Размер не кратен 128KiB | Использовать кратное 128KiB значение |
| `pvremove` не удаётся: "PV is still in use" | PV принадлежит VG | Сначала `vgreduce --removemissing VG`, затем `pvremove` |

### Диагностические команды

```bash
# Проверка всех PV
sudo pvs

# Проверка всех VG
sudo vgs

# Проверка всех LV
sudo lvs

# Детальная информация о PV
sudo pvdisplay /dev/sdb

# Детальная информация о VG
sudo vgdisplay vg_data

# Детальная информация о LV
sudo lvdisplay /dev/vg_data/lv_db

# Просмотр всех доступных полей для pvs/vgs/lvs
sudo pvs -o help
sudo vgs -o help
sudo lvs -o help

# Просмотр метаданных VG
sudo vgcfgrestore --list vg_data

# Проверка целостности PV
sudo pvck /dev/sdb

# Проверка целостности VG
sudo vgck vg_data

# Просмотр journal для ошибок LVM
sudo journalctl -k | grep -i "lvm\|device-mapper\|dm-"
```

### См. также
- **[LVM — Обзор и концепции](../overview_concepts.md)** — архитектура Device Mapper, принципы работы.
- **[LVM — Жизненный цикл](./lvm_lifecycle.md)** — полный цикл от создания до удаления.
- **[LVM — Просмотр информации](./lvm_view_info.md)** — расшифровка атрибутов и команд вывода.
- **[LVM — Изменение размеров томов](./lvm_resize.md)** — расширение и уменьшение томов.
- **[LVM — Тонкое провизионирование](../thin-provisioning.md)** — создание thin pool и thin volumes.
- **[LVM — Снимки](../snapshots.md)** — создание и управление снимками.
- **[LVM — Продвинутые темы](../advanced_topics/advanced_topics.md)** — RAID, кэширование, вложенное LVM.
- **[LVM — Практические сценарии](../advanced_topics/practical_scenarios.md)** — восстановление метаданных, vgsplit/vgmerge.
