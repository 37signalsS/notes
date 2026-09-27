# Изменение размеров LVM

## Определения

**PV (Physical Volume — физический том)** — нижний уровень иерархии LVM; физический диск, раздел или блочное устройство (например, LUKS-контейнер, multipath-устройство), инициализированное для использования в LVM. Содержит метку LVM и область метаданных (по умолчанию 1 МиБ) в формате ASCII, расположенную кольцевым буфером в начале устройства.

**VG (Volume Group — группа томов)** — пул дискового пространства, объединяющий один или несколько PV. Представляет собой единое адресное пространство, разбитое на физические экстенты (PE). VG не имеет фиксированного размера и может быть расширен добавлением новых PV.

**LV (Logical Volume — логический том)** — виртуальный раздел, создаваемый из пространства VG, на котором размещается файловая система. Для операционной системы выглядит как стандартное блочное устройство. LV не привязан к физической позиции на диске — его расположение определяется картой маппинга экстентов.

**PE (Physical Extent — физический экстент)** — минимальный блок данных в VG (по умолчанию **4 МиБ**). Все операции изменения размера кратны размеру PE. Размер PE задаётся при создании VG (`vgcreate -s`) и не может быть изменён позже.

**LE (Logical Extent — логический экстент)** — единица измерения размера LV, соответствующая количеству PE, выделенных под этот том. В стандартных LV LE и PE совпадают по размеру. В RAID LV LE может отличаться от PE из-за избыточности.

**Mapping (маппинг)** — механизм сопоставления LE на PE, определяющий стратегию размещения данных. Типы маппинга: Linear (последовательно), Striped (чередование), RAID 1/5/6/10 (избыточность).

## Базовые концепции

### Принцип изменения размеров

Изменение размеров в LVM выполняется по принципу «снизу вверх» (PV → VG → LV → ФС) при расширении и «сверху вниз» (ФС → LV → VG → PV) при уменьшении. Этот порядок обусловлен тем, что каждый верхний уровень зависит от доступного пространства нижнего.

#### Что происходит при расширении LV

При расширении LVM выполняет следующие действия:
1. Выделяет новые LE из свободного пространства VG
2. Обновляет таблицу маппинга LV, добавляя новые записи LE→PE
3. Увеличивает размер блочного устройства LV в ядре (Device Mapper)
4. Файловая система автоматически видит новое пространство (при использовании флага `-r`)

Эта операция **атомарна** и выполняется без остановки сервисов. Ядро немедленно видит новый размер, а ФС может быть расширена онлайн.

#### Что происходит при уменьшении LV

Уменьшение — более опасная операция:
1. Файловая система должна быть уменьшена **до** LV (иначе данные будут повреждены)
2. LVM удаляет последние LE из таблицы маппинга
3. Физические блоки возвращаются в пул свободного пространства VG

Критическое ограничение: **нельзя уменьшить LV меньше текущего использования ФС**. Это приведёт к обрезке данных.

### Способы указания размера

При использовании команд `lvextend`, `lvreduce` и `lvresize` размер можно указывать двумя флагами:
- **Флаг `-L` (Size):** абсолютное или относительное значение в единицах объема (например, `-L 10G`, `-L +2G`). Поддерживает суффиксы: `k/K` (KiB), `m/M` (MiB), `g/G` (GiB), `t/T` (TiB), `p/P` (PiB), `e/E` (ExiB).
- **Флаг `-l` (Extents):** размер в логических экстентах. Использование `%FREE` или `%VG` позволяет задействовать всё доступное пространство без ошибок округления (например, `-l +100%FREE`). Также поддерживаются `%LV` (текущий размер LV), `%VG` (общий размер VG).

**Рекомендация:** Используйте `-l +100%FREE` для максимальной точности. Флаг `-L` может создавать проблемы из-за разницы между decimal (1000) и binary (1024) системами счисления.

### Поддержка файловыми системами

Изменение размера LVM-тома должно сопровождаться изменением размера файловой системы (ФС).

| Файловая система | Расширение (Grow) | Уменьшение (Shrink) | Инструментарий | Примечания |
| :--- | :--- | :--- | :--- | :--- |
| **ext2/ext3/ext4** | Онлайн | Офлайн (требуется `umount`) | `resize2fs`, `fsadm` | Требует `e2fsck -f` перед уменьшением |
| **XFS** | Онлайн | **Не поддерживается** | `xfs_growfs`, `fsadm` | Только расширение. Для уменьшения — пересоздание |
| **Btrfs** | Онлайн | Онлайн | `btrfs filesystem resize` | Поддерживает multiple devices |
| **F2FS** | Онлайн | Офлайн | `resize.f2fs` | Требует `fsck.f2fs` перед уменьшением |
| **ReiserFS** | Онлайн | Онлайн | `resize_reiserfs` | Устаревшая ФС, не рекомендуется |

**Важно:** Флаг `-r` (`--resizefs`) в командах LVM автоматически определяет тип ФС и вызывает нужную команду. Однако для Btrfs он часто работает некорректно — рекомендуется ручное расширение.

### Точность расчетов и риски

Утилиты LVM и ФС могут использовать разные базы (1000 vs 1024), что создает риск повреждения данных при уменьшении тома.

**Пример проблемы:**
- `lvreduce -L 5G` интерпретирует 5G как 5 × 1000 × 1000 × 1000 = 5 000 000 000 байт
- `resize2fs` может интерпретировать 5G как 5 × 1024 × 1024 × 1024 = 5 368 709 120 байт
- Разница: 368 709 120 байт (~351 МиБ) — потенциальная потеря данных

**Рекомендация:** При уменьшении тома всегда сжимайте ФС до размера на **100–200 МиБ меньше** целевого LV. После успешного уменьшения LV расширьте ФС до границ тома командой `resize2fs` (или аналогом) без указания размера.

### Универсальный инструмент — fsadm

Утилита `fsadm` (входит в состав LVM2) — это обертка, которая автоматически определяет тип ФС и вызывает нужные команды. Она используется внутри команд LVM при указании флага `-r` (`--resizefs`).

**Особенности fsadm:**
- Автоматически определяет тип ФС (ext4, XFS, Btrfs)
- Выполняет необходимые проверки перед изменением размера
- Не поддерживает все типы ФС (например, ZFS, ReiserFS)
- Для XFS требует, чтобы точка монтирования была указана в `/etc/fstab`

**Пример ручного использования:**
```bash
# Расширение ФС на LV (автоопределение типа)
sudo fsadm resize /dev/data_vg/lv_app 10G

# Расширение с указанием размера в блоках
sudo fsadm resize /dev/data_vg/lv_app 20971520
```

## Предварительные требования

### Необходимые пакеты

| Пакет | Дистрибутив | Назначение |
| :--- | :--- | :--- |
| `lvm2` | Все | Основной инструментарий LVM |
| `util-linux` | Все | `resize2fs` (ext2/ext3/ext4) |
| `xfsprogs` | Все | `xfs_growfs` (XFS) |
| `btrfs-progs` | Все | `btrfs filesystem resize` |
| `cloud-guest-utils` | Debian/Ubuntu | `growpart` (для расширения разделов) |
| `gdisk` | RHEL/CentOS | `sgdisk` (для GPT) |
| `device-mapper-persistent-data` | RHEL/CentOS | `thin_repair` (для тонких пулов) |

### Проверка версий

```bash
# Проверка версии LVM
sudo lvm version
# → LVM version:     2.03.11 (2021-01-08)

# Проверка версии ядра (для поддержки Device Mapper)
uname -r
# → 5.15.0-56-generic

# Проверка доступности fsadm
which fsadm
# → /usr/sbin/fsadm
```

### Права доступа

Все операции изменения размеров LVM требуют.root-привилегий. Убедитесь, что:
- Пользователь имеет права `sudo` без пароля для LVM-команд
- В `/etc/sudoers` настроены нужные привилегии
- Сервисы не блокируют устройства (проверка через `lsof` или `fuser`)

## Практические сценарии

### Сценарий 1: Онлайн-расширение логического тома и ФС

Использование флага `-r` позволяет выполнить обе операции атомарно.

**Шаг 1: Проверка свободного места в VG**
```bash
sudo vgs
# → VG      #PV #LV #SN Attr   VSize   VFree
# → data_vg   1   1   0 wz--n- <20.00g <5.00g
```

**Шаг 2: Расширение LV и ФС (ext4/XFS)**
```bash
# Добавить 2 ГБ и сразу расширить ФС
sudo lvextend -L +2G -r /dev/data_vg/lv_app
# → Logical volume data_vg/lv_app successfully resized.

# Использовать всё свободное место в группе
sudo lvextend -l +100%FREE -r /dev/data_vg/lv_app
```

**Шаг 3: Верификация**
```bash
# Проверка нового размера LV
sudo lvs data_vg/lv_app
# → LV      VG      Attr       LSize   Pool Origin Data%  Meta%
# → lv_app  data_vg -wi-ao---- 22.00g

# Проверка размера ФС
df -hT /mnt/data
# → Filesystem              Type  Size  Used Avail Use% Mounted on
# → /dev/mapper/data_vg-lv_app ext4  22G   15G  5.9G  72% /mnt/data
```

**Шаг 4: Расширение Btrfs (вручную)**
Флаг `-r` часто не поддерживает Btrfs. Расширение выполняется по точке монтирования.
```bash
sudo lvextend -l +100%FREE /dev/data_vg/lv_btrfs
sudo btrfs filesystem resize max /mnt/btrfs_data
# → Resize '/mnt/btrfs_data' of 'max'
```

### Сценарий 2: Безопасное уменьшение (ext4)

**Внимание:** Невозможно для XFS. Уменьшение — деструктивная операция, бэкап обязателен.

**Способ А: Автоматический (через fsadm)**
```bash
sudo lvresize -L 5G -r /dev/data_vg/lv_app
# → WARNING: Reducing active logical volume to 5.00 GiB.
# → Do you really want to reduce data_vg/lv_app? [y/n]: y
```

**Способ Б: Ручной (максимальный контроль)**
1. **Размонтирование и проверка:**
   ```bash
   sudo umount /mnt/data
   sudo e2fsck -f /dev/data_vg/lv_app
   ```
2. **Сжатие ФС:** Уменьшаем ФС до 4.8G (если целевой LV — 5G) для защиты от ошибок округления.
   ```bash
   sudo resize2fs /dev/data_vg/lv_app 4800M
   ```
3. **Уменьшение LV:**
   ```bash
   sudo lvreduce -L 5G /dev/data_vg/lv_app
   ```
4. **Растягивание ФС:** Растягиваем ФС до границ LV.
   ```bash
   sudo resize2fs /dev/data_vg/lv_app
   sudo mount /dev/data_vg/lv_app /mnt/data
   ```

**Верификация после уменьшения:**
```bash
sudo lvs data_vg/lv_app
# → LV      VG      Attr       LSize   Pool Origin Data%  Meta%
# → lv_app  data_vg -wi-ao----  5.00g

df -hT /mnt/data
# → /dev/mapper/data_vg-lv_app ext4  4.8G  3.2G  1.4G  70% /mnt/data
```

### Сценарий 3: Расширение после увеличения физического диска (Виртуальные машины)

Применяется, когда объём виртуального диска был увеличен в гипервизоре (VMware, Proxmox, KVM/Xen, oVirt).

**Шаг 1: Обнаружение изменений**
```bash
# Пересканирование диска sdb
echo 1 | sudo tee /sys/class/block/sdb/device/rescan
# → 1

# Проверка нового размера
lsblk /dev/sdb
# → NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINT
# → sdb      8:16   0   50G  0 disk
# → └─sdb1   8:17   0   20G  0 part
```

**Шаг 2: Расширение раздела (если используется раздел, а не целый диск)**
```bash
# Метод 1: growpart (рекомендуется)
sudo growpart /dev/sdb 1
# → CHANGED: partition=1 start=2048 old: size=41940992 end=41943040 new: size=62912479 end=62914527

# Метод 2: parted (для GPT дисков >4 ТБ)
sudo parted /dev/sdb
# (parted) resizepart 1 100%
# (parted) quit
```

**Шаг 3: Обновление размера PV**
```bash
sudo pvresize /dev/sdb1
# → Physical volume "/dev/sdb1" changed
# → 1 physical volume(s) resized or updated
```

**Шаг 4: Расширение LV** согласно Сценарию 1.

**Шаг 5: Верификация полного пайплайна**
```bash
# Проверка всех уровней
sudo pvs /dev/sdb1
# → PV         VG      Fmt  Attr PSize  PFree
# → /dev/sdb1  data_vg lvm2 a--  <50.00g <30.00g

sudo vgs data_vg
# → VG      #PV #LV #SN Attr   VSize   VFree
# → data_vg   1   1   0 wz--n- <50.00g <30.00g

df -hT /mnt/data
# → /dev/mapper/data_vg-lv_app ext4  22G   15G  5.9G  72% /mnt/data
```

### Сценарий 4: Добавление нового PV для расширения VG

Если на существующих дисках нет места, добавляем новый носитель.

```bash
# 1. Проверка нового диска
lsblk
# → NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINT
# → sdc      8:32   0  100G  0 disk

# 2. Инициализация PV
sudo pvcreate /dev/sdc
# → Physical volume "/dev/sdc" successfully created.

# 3. Расширение VG
sudo vgextend data_vg /dev/sdc
# → Volume group "data_vg" successfully extended

# 4. Проверка нового размера VG
sudo vgs data_vg
# → VG      #PV #LV #SN Attr   VSize    VFree
# → data_vg   2   1   0 wz--n- <120.00g <100.00g

# 5. Расширение LV
sudo lvextend -l +100%FREE -r /dev/data_vg/lv_app
```

**Верификация:**
```bash
sudo pvs
# → PV         VG      Fmt  Attr PSize   PFree
# → /dev/sdb   data_vg lvm2 a--  <20.00g     0
# → /dev/sdc   data_vg lvm2 a--  <100.00g <80.00g
```

### Сценарий 5: Изменение размера зашифрованного тома (LUKS + LVM)

Схема: `Disk → LUKS → LVM PV → VG → LV`.

**Алгоритм расширения:**
1. **Расширение физического носителя** (Сценарий 3)
2. **Расширение LUKS-контейнера:**
   ```bash
   # Проверка текущего размера LUKS
   sudo cryptsetup status crypt_disk
   # → /dev/mapper/crypt_disk is active and is in use.
   # → type:    LUKS2
   # → cipher:  aes-xts-plain64
   # → keysize: 512 bits
   # → device:  /dev/sdb1
   # → sector size:  512
   # → offset:  32768 sectors
   # → size:    41910272 sectors
   # → mode:    read/write

   # Расширение LUKS-контейнера
   sudo cryptsetup resize crypt_disk
   # → Device crypt_disk resized to 62912479 sectors.
   ```
3. **Обновление PV и LV:**
   ```bash
   sudo pvresize /dev/mapper/crypt_disk
   # → Physical volume "/dev/mapper/crypt_disk" changed

   sudo lvextend -l +100%FREE -r /dev/data_vg/lv_app
   ```

**Важно:** Порядок критичен. Нельзя расширить PV до расширения LUKS-контейнера.

### Сценарий 6: Изменение размера в Тонких пулах (Thin Provisioning)

Для тонких томов расширение виртуального размера не требует свободного места в VG немедленно.

```bash
# Расширение виртуального размера тонкого тома
sudo lvextend -V 2T /dev/my_vg/thin_lv

# Расширение физического пространства тонкого пула (требует VFree в VG)
sudo lvextend -L +100G -r /dev/my_vg/thin_pool
```

**Мониторинг после расширения:**
```bash
sudo lvs -o lv_name,lv_size,data_percent,metadata_percent
# → LV          LSize   Data%  Meta%
# → thin_lv     2.00t   45.23  12.45

# Проверка размера пула
sudo lvs -o lv_name,lv_size,thin_count
# → LV          LSize   Thin#
# → thin_pool   500.00g     1
```

**Важно:** Расширение пула и расширение тома — независимые операции. Пул определяет физическое пространство, а том — виртуальный размер.

*Подробнее см. в [LVM — Тонкое провизионирование](../thin-provisioning.md).*

### Сценарий 7: Расширение VDO-тома (RHEL 9+)

VDO интегрирован в LVM как тип логического тома. Расширение состоит из двух этапов: расширение VDO Pool (физический слой) и расширение VDO LV (виртуальный размер).

```bash
# 1. Расширение VDO Pool (физическое пространство)
sudo lvextend -L +50G /dev/my_vg/vdo_pool_my_vdo_lv

# 2. Расширение VDO LV (виртуальный размер)
sudo lvextend -L +200G /dev/my_vg/my_vdo_lv

# 3. Расширение ФС
sudo xfs_growfs /mnt/vdo_data
```

**Верификация:**
```bash
# Проверка эффективности сжатия и дедупликации
sudo lvs -o+vdo_compression,vdo_deduplication,vdo_usage_percent
# → LV          VG    Attr       LSize   Data%  VDOCompr  VDEDUP
# → my_vdo_lv   my_vg vwi-aotz-- 200.00g 34.21  2.3       1.8

# Детальная статистика
sudo vdostats --human-readable
# → /dev/mapper/my_vg-vdo_pool_my_vdo_lv
# →    50 GiB physical size
# →    17 GiB physical used
# →    34 GiB virtual size
# →    12 GiB virtual used
```

**Особенности VDO resize:**
- Расширение Pool всегда безопасно — это просто добавление физических слабов
- Расширение LV увеличивает виртуальный размер — данные не перемещаются
- Дедупликация и сжатие работают по-прежнему после расширения

*Подробнее см. в [VDO — Virtual Data Optimizer](../../vdo.md).*

### Сценарий 8: Расширение multipath-устройства (iSCSI/SAN)

В средах с multipath (SAN/iSCSI) расширение требует дополнительных шагов для обновления всех путей.

```bash
# 1. Увеличить LUN на стороне СХД (вне Linux)

# 2. Обновить multipath-конфигурацию
sudo multipath -r
# → remake map [OK]

# 3. Пересканировать все базовые устройства
for sd in /sys/class/block/sd*/device/rescan; do
    echo 1 | sudo tee "$sd"
done

# 4. Обновить размер multipath-устройства
sudo multipathd show paths format "%d %t %T %s"
# → sdb  FFP    360060160 abcdef01 mpatha
# → sdc  FFP    360060160 abcdef01 mpatha

# 5. Расширить PV через multipath-устройство
sudo pvresize /dev/mapper/mpatha
# → Physical volume "/dev/mapper/mpatha" changed

# 6. Расширить LV и ФС
sudo lvextend -l +100%FREE -r /dev/vg_data/lv_data
```

**Критично:** Фильтр LVM должен быть настроен для игнорирования базовых `sdX` устройств и использования только `mpath*`:

```ini
# /etc/lvm/lvm.conf
devices {
    filter = [ "a|/dev/mapper/mpath.*|", "r|/dev/sd.*|", "r|/dev/dm-.*|" ]
}
```

**Верификация multipath:**
```bash
# Проверка всех путей
sudo multipathd show paths
# → hcil    dev dev_t pri dm_st   ch chk  rr
# → 0:0:0:0 sdb 8:16  1   active  A  Y    1
# → 0:0:1:0 sdc 8:32  1   active  A  Y    1

# Проверка размера multipath-устройства
sudo multipath -ll
# → mpatha (360060160...) dm-0  NETAPP,LUN
# ├─360060160... dm-0  100.00G
# ├─360060160... dm-0  100.00G
# └─360060160... dm-0  100.00G
```

### Сценарий 9: Расширение LVM RAID тома

При использовании встроенного RAID LVM (raid1, raid5, raid6, raid10) расширение требует учёта избыточности.

#### RAID 1 (зеркало)

```bash
# Расширение RAID1 LV
sudo lvextend -L +10G -r /dev/vg_data/lv_raid1

# Проверка состояния зеркала
sudo lvs -o lv_name,lv_attr,devices
# → LV      Attr       Devices
# → lv_raid1 rwi-aotm-- 2
# │  └─lv_raid1_rimage_0 lwi-aotm-- 10.00g
# │  └─lv_raid1_rimage_1 lwi-aotm-- 10.00g
```

#### RAID 5/6/10

```bash
# Расширение RAID5 LV (требует добавления PV)
sudo vgextend vg_data /dev/sdd
sudo lvextend -l +100%FREE -r /dev/vg_data/lv_raid5

# Проверка состояния RAID
sudo lvs -o lv_name,lv_attr,stripe_count,devices
# → LV      Attr       #Str Devices
# → lv_raid5 rwi-aotm--    3 3
```

**Важно:** Расширение RAID5/6 требует добавления минимум одного нового PV. Расширение RAID1 возможно без добавления PV (просто увеличение размера зеркал).

### Сценарий 10: Сжатие VG (уменьшение PV)

В ситуациях, когда необходимо освободить физический диск для использования за пределами LVM.

```bash
# 1. Проверка свободного места в LV
sudo lvs data_vg
# → LV      VG      Attr       LSize   Pool Origin Data%  Meta%
# → lv_app  data_vg -wi-ao---- 10.00g

# 2. Свободное место в VG должно быть >= размеру переносимого PV
sudo vgs data_vg
# → VG      #PV #LV #SN Attr   VSize   VFree
# → data_vg   2   1   0 wz--n- <120.00g <80.00g

# 3. Перенос данных с целевого PV на другие PV
sudo pvmove /dev/sdc
# → Physical volume "/dev/sdc" still in use

# 4. Удаление PV из VG
sudo vgreduce data_vg /dev/sdc
# → Removed "/dev/sdc" from volume group "data_vg"

# 5. Удаление метаданных LVM с диска
sudo pvremove /dev/sdc
# → Labels on physical volume "/dev/sdc" successfully wiped.

# 6. Проверка результата
sudo pvs
# → PV         VG      Fmt  Attr PSize  PFree
# → /dev/sdb   data_vg lvm2 a--  20.00g     0
# → /dev/sdc   lvm2    lvm2 ---  100.00g 100.00g
```

**Критическое условие:** На PV не должно быть активных LV. Если LV расположены частично на целевом PV, используйте `pvmove` для их миграции.

## Дополнительная информация

### Лучшие практики

1. **Резервное копирование:** Всегда создавайте резервную копию данных перед уменьшением томов. Для расширения резервное копирование рекомендуется, но не обязательно.

2. **Мониторинг свободного места:** Настройте алерты на достижение 80% и 90% заполнения VG:
   ```bash
   # Проверка свободного места
   sudo vgs --noheadings --nosuffix --units g -o vg_name,v_free
   # → data_vg 5.00
   ```

3. **Именование:** Используйте осмысленные имена PV/VG/LV. Избегайте имён, содержащих пробелы или специальные символы.

4. **Документация:** Ведите журнал изменений размеров. Фиксируйте дату, оператора, исходный и целевой размеры.

5. **Тестирование:** На non-production окружении проверяйте сценарии уменьшения перед выполнением на боевых серверах.

6. **Избегайте смешивания типов дисков:** Не объединяйте SSD и HDD в один VG, если это не является осознанным решением. Разная производительность может создать проблемы.

### Граничные случаи и ограничения

1. **Размер PE:** При создании VG размер PE фиксируется. Все последующие операции кратны этому размеру. Для массивов >100 ТБ рекомендуется увеличивать PE до 32–128 МиБ.

2. **Максимальный размер LV:** Зависит от архитектуры:
   - 32-битные ядра: ~2 ТБ (с 4 МиБ PE)
   - 64-битные ядра: ~8 ЭиБ (теоретический предел)

3. **Онлайн-операции:** Расширение LV и ФС всегда онлайн. Уменьшение ФС (ext4) требует `umount`. XFS не поддерживает уменьшение.

4. **Дублирование UUID:** При клонировании дисков (rsync, dd) возникают дубли UUID. Используйте `vgimportclone` для переименования VG.

5. **Загрузка:** Если корневой раздел (`/`) находится на LVM, расширение может потребовать пересборки initramfs (особенно при изменении фильтров в `lvm.conf`).

6. **Thin Pool overflow:** Если тонкий пул заполняется на 100%, том переходит в режим read-only. Решение: расширение пула или удаление данных.

7. **VDO Pool exhaustion:** Аналогично thin pool — при заполнении VDO Pool устройство становится read-only. Требует `fstrim` для освобождения неиспользуемых блоков.

8. **Multipath и фильтры:** Неправильный фильтр в `lvm.conf` приведёт к тому, что LVM будет видеть базовые `sdX` устройства вместо `mpath*`. Это приведёт к конфликтам UUID.

9. **Снимки при расширении:** Активные снимки могут влиять на производительность расширения. Рекомендуется удалять временные снимки перед масштабными операциями.

### Устранение неполадностей

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `device not found` | Устройство не существует или не активно | Проверить `lsblk`, выполнить `vgscan`, проверить `lvm.conf` фильтры |
| `Insufficient suitable allocatable extents` | Недостаточно свободного пространства в VG | Выполнить `vgs` для проверки `VFree`, добавить новый PV через `vgextend` |
| `Couldn't find device with uuid` | Устаревшие метаданные или удалённый диск | Выполнить `vgreduce --removemissing VG_NAME` для очистки |
| `Logical volume contains a filesystem in use` | ФС смонтирована или используется процессом | Выполнить `umount`, затем повторить операцию. Для root — загрузка с LiveCD |
| `fsadm: Failed to check mountpoint` | Точка монтирования не в `/etc/fstab` | Добавить запись в fstab или использовать ручной `resize2fs`/`xfs_growfs` |
| `Can't merge over active LV` | Попытка слияния снапшота при активном LV | Деактивировать целевой LV: `lvchange -an VG/LV`, затем повторить `lvconvert --merge` |
| `Thin pool is full` | Тонкий пул заполнен на 100% | Расширить пул: `lvextend -L +SIZE VG/pool`. ФС перейдёт в read-only |
| `VDO pool is full` | VDO Pool исчерпан | Расширить пул или выполнить `fstrim -v /mountpoint` для освобождения блоков |
| `Part of LV is missing` | Физический диск повреждён или отключён | Проверить `pvs`, восстановить диск или выполнить `vgreduce --removemissing` |
| `metadata not found` | Повреждение области метаданных PV | Использовать `pvck --repair` или восстановить из `/etc/lvm/backup/` |

### Диагностические команды

```bash
# Быстрая проверка состояния всех уровней
sudo pvs && sudo vgs && sudo lvs

# Проверка активных процессов, использующих LV
sudo lsof /dev/mapper/data_vg-lv_app
sudo fuser -vm /dev/mapper/data_vg-lv_app

# Проверка journal для ошибок LVM
sudo journalctl -k | grep -i "device-mapper\|lvm\|dm-"

# Просмотр метаданных VG
sudo vgcfgrestore --list data_vg

# Проверка целостности PV
sudo pvck /dev/sdb1

# Проверка целостности VG
sudo vgck data_vg
```

### См. также
- **[LVM — Управление томами](../management_operations.md)** — общие операции и мониторинг.
- **[LVM — Создание PV, VG и LV](./pv_vg_creation.md)** — инициализация структуры.
- **[LVM — Просмотр информации](./lvm_view_info.md)** — команды диагностики.
- **[LVM — Тонкое провизионирование](../thin-provisioning.md)** — динамическое выделение места.
- **[VDO — Virtual Data Optimizer](../../vdo.md)** — дедупликация и сжатие.
- **[Расширение дискового пространства](../../disk_expansion.md)** — общий обзор расширения разделов.
