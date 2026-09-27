# Расширение дискового пространства в Linux

## Определения

- **Расширение (Expansion/Resize):** Комплексный многоуровневый процесс увеличения логической емкости хранилища. В Linux этот процесс всегда выполняется «снизу вверх», от физического носителя до структур файловой системы.
- **Блочное устройство (Block Device):** Абстракция накопителя в ядре (например, `/dev/sda`, `/dev/nvme0n1`).
- **growpart:** Инструмент из пакета `cloud-guest-utils`, позволяющий изменить таблицу разделов (MBR или GPT) для расширения раздела до конца диска без потери данных и без размонтирования (Online).
- **rescan:** Системная операция принудительного уведомления ядра о том, что характеристики блочного устройства (размер) изменились. Критично для виртуализации (VirtIO, VMware) и SAN/iSCSI.
- **Online-расширение:** Возможность увеличить объем ФС без остановки сервисов и размонтирования раздела.

## Основные концепции

### Зачем нужен LVM: Проблемы классической схемы разметки

Классическая схема разделов (MBR/GPT) имеет фундаментальное ограничение: **свободное пространство можно добавить только к последнему разделу**. Это создаёт серьёзные проблемы в реальных сценариях.

#### Ограничения классической разметки

| Операция | Классическая схема | LVM |
|:---------|:-------------------|:----|
| Расширить последний раздел | Возможно (с оговорками) | Возможно |
| Расширить средний раздел | **Невозможно без остановки сервиса** | Возможно онлайн |
| Расширить любой раздел | Только последний | Любой |
| Перенести данные на другой диск | Требует остановки и ручного переноса | `pvmove` онлайн |

#### Почему нельзя расширить средний раздел?

При изменении размера среднего раздела (не последнего) изменяется его **начальный сектор**, что влечёт за собой смещение всех последующих разделов. Это критично, поскольку:

1. **Суперблок файловой системы привязан к фиксированной позиции** — например, XFS хранит свой суперблок со смещением 1024 байта от начала раздела.
2. **Изменение начала раздела нарушает позицию суперблока** — файловая система становится неработоспособной.
3. **Утилиты восстановления (fsck) не помогут** — они работают с концом раздела, но не с его началом.

#### Последствия ошибок при классической разметке

```bash
# Увеличили средний раздел (/dev/sdb2) — затронули начало /dev/sdb3
# Результат: файловая система на /dev/sdb3 нечитаема
# Восстановление: возврат к прежним границам, потеря данных на расширенной части
```

#### Решение: LVM

LVM вводит дополнительный уровень абстракции между блочным устройством и файловой системой:

```
┌─────────────────────────────────────────────────────────┐
│  Файловая система (ext4, XFS, Btrfs)                   │
├─────────────────────────────────────────────────────────┤
│  Logical Volume (LV) — логический том                  │
│  • Не привязан к физической позиции на диске            │
│  • Можно расширять/уменьшать без влияния на другие LV  │
├─────────────────────────────────────────────────────────┤
│  Volume Group (VG) — группа томов                      │
│  • Пул дискового пространства из одного или нескольких PV│
│  • Physical Extent (PE) — минимальная единица (4 MiB)  │
├─────────────────────────────────────────────────────────┤
│  Physical Volume (PV) — физический том                 │
│  • Диск или раздел с метаданными LVM                   │
└─────────────────────────────────────────────────────────┘
```

**Ключевое преимущество:** LVM оперирует логическими томами, которые не имеют фиксированной привязки к физическим секторам. Расширение LV затрагивает только карту экстентов внутри VG, не меняя физическую структуру диска.

Подробнее о структуре LVM см. **[LVM — Обзор и основные концепции](./LVM/overview_concepts.md)**.

### Иерархия уровней расширения (Золотой путь)

Процесс расширения — это цепочка зависимых действий. Пропуск любого звена приведет к «фантомному» расширению (место добавлено, но недоступно).

1.  **Инфраструктурный уровень:** Увеличение LUN в СХД, расширение виртуального диска в гипервизоре (VMware, Proxmox) или в облаке (Yandex Cloud, AWS).
2.  **Уровень ядра (Kernel Discovery):** Ядро должно увидеть новый размер блочного устройства.
3.  **Уровень разметки (Partitioning):** Раздел (Partition) должен быть расширен в таблице разделов.
4.  **Уровень абстракции (LVM/RAID/LUKS):** Опциональный этап, если ФС живет не на голом разделе.
5.  **Уровень ФС (FileSystem):** Метаданные ФС (суперблоки, карты блоков) должны быть обновлены для использования нового пространства.

### Сравнение инструментов разметки

| Инструмент | Метод | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **growpart** | Автоматический | Безопасно, поддерживает Online-расширение. | Требует установки пакета. |
| **parted** | Интерактивный/CLI | Удобная команда `resizepart`. Поддерживает GPT. | Не всегда корректно работает с MBR в старых версиях. |
| **fdisk** | Интерактивный | Есть везде. | Требует удаления и пересоздания раздела (риск ошибки). |

### Online/offline ограничения по типам файловых систем

Не все файловые системы поддерживают расширение «на горячую». Понимание ограничений критично для планиования окон обслуживания:

| ФС | Online-расширение | Offline-расширение | Ограничения |
| :--- | :--- | :--- | :--- |
| **Ext4** | Да (mounted) | Да (unmounted) | Требует включенного journaling; resize2fs работает и на смонтированной ФС. |
| **XFS** | Да (mounted, **только рост**) | Да (unmounted, только рост) | Уменьшение (shrink) не поддерживается ни online, ни offline. |
| **Btrfs** | Да (mounted) | Да | Поддерживает добавление устройств в multi-device ФС онлайн. Shrink возможен offline. |
| **F2FS** | Да (mounted) | Да | Поддерживается начиная с ядра 4.10. |
| **ReiserFS** | Да (mounted) | Да | Устаревшая ФС; поддержка ядром ограничена. |
| **NTFS** | Да (mount.ntfs-3g) | Да | Требует `ntfs-3g` в userspace; производительность ниже, чем у нативных ФС. |

**Важно:** Online-расширение XFS работает только при монтировании через `xfs` драйвер ядра (не `xfs` FUSE). Проверка: `mount -t xfs`.

## Практические сценарии

### Предварительные действия

Перед изменением размеров разделов рекомендуется отмонтировать диск. Если диск системный, требуется загрузка в recovery. Расширение на горячую возможно, но выполняется на свой страх и риск. **Создайте резервную копию критичных данных перед началом работ.**

### 1. Уведомление ядра об изменениях (Rescan)

Если размер диска изменен в облаке или гипервизоре, ядро может продолжать видеть старый размер.

```bash
# Для конкретного диска (например, sdb)
echo 1 | sudo tee /sys/class/block/sdb/device/rescan

# Обновление всех SCSI-устройств (полезно при добавлении новых LUN)
sudo rescan-scsi-bus.sh -r
```
*Проверка результата:* `lsblk` или `dmesg | tail`.

### 1.1. Проверка видимого размера диска

После увеличения объема диска в гипервизоре система может продолжать видеть старый размер. Проверьте актуальные размеры:

```bash
lsblk
# NAME   MAJ:MIN RM   SIZE RO TYPE MOUNTPOINT
# sdb      8:16   0     5T  0 disk
# └─sdb1   8:17   0     4T  0 part /data
```

Если размер диска изменился, а размер раздела нет — переходите к расширению раздела.

### 2. Расширение раздела (Partition Level)

#### Метод А: growpart (Рекомендуемый)
```bash
# Расширить раздел 1 на диске /dev/vda
sudo growpart /dev/vda 1
```

#### Метод Б: parted
```bash
# Перевести в режим работы с устройством
sudo parted /dev/sda
# Внутри: resizepart [номер] [конец, например 100%]
(parted) resizepart 1 100%
(parted) quit
```

#### Метод В: fdisk (удаление и пересоздание раздела)
Подходит для разделов объемом менее 4 ТБ. Требует аккуратности, но работает даже когда `growpart` недоступен.

```bash
sudo fdisk /dev/sdb
```

**Шаг 1:** Просмотр текущей таблицы разделов:
```bash
Command (m for help): p
# Device     Start        End    Sectors Size Type
# /dev/sdb1   2048 8589843750 8589841703   4T Linux filesystem
```

**Шаг 2:** Удалить раздел:
```bash
Command (m for help): d
Selected partition 1
# Partition 1 has been deleted.
```

**Шаг 3:** Создать новый раздел с тем же номером и тем же начальным сектором, но с новым конечным сектором:
```bash
Command (m for help): n
Partition number (1-128, default 1): 1
First sector (34-8589934558, default 2048): 2048
Last sector, +sectors or +size{K,M,G,T,P} (2048-8589934558, default 8589934558): 8589934558
```

**Важно:** Если программа сообщает о существующей сигнатуре ФС, не удаляйте ее:
```bash
Partition #1 contains a ext4 signature.
Do you want to remove the signature? [Y]es/[N]o: N
```

**Шаг 4:** Проверить новую таблицу:
```bash
Command (m for help): p
# Device     Start         End     Sectors Size Type
# /dev/sdb1   2048 10751953125 10751951078   5T Linux filesystem
```

**Шаг 5:** Записать изменения:
```bash
Command (m for help): w
```

#### Метод Г: parted для дисков GPT более 4 ТБ

Если при использовании `fdisk` появляется ошибка `Value out of range`, используйте `parted`:

```bash
sudo parted /dev/sdb
```

Внутри `parted`:
```bash
(parted) print
# Number  Start   End     Size    File system  Name     Flags
#  1      1049kB  3299GB  3299GB  ext4         primary

(parted) resizepart 1
Warning: Partition /dev/sdb1 is being used. Are you sure you want to continue?
Yes/No? Yes
End?  [3299GB]? 4398GB

(parted) quit
```

Если `parted -l` выдает предупреждение о неиспользуемом пространстве, ответьте `Fix`:
```bash
Warning: Not all of the space available to /dev/sdb appears to be used...
Fix/Ignore? Fix
```

### 3. Расширение файловой системы (FileSystem Level)

Операция выполняется только **после** расширения раздела или логического тома.

| ФС | Команда | Указание цели |
| :--- | :--- | :--- |
| **Ext4** | `sudo resize2fs /dev/vda1` | Путь к устройству. |
| **XFS** | `sudo xfs_growfs /mnt/data` | **Точка монтирования.** |
| **Btrfs** | `sudo btrfs filesystem resize max /mnt/btrfs` | Путь к ФС. |

### 4. Автоматизация через Cloud-init

В облачных средах (Yandex Cloud, AWS) расширение системного раздела часто происходит автоматически при первой загрузке или при изменении параметров инстанса, если установлены пакеты `cloud-init` и `growpart`.

**Конфигурация в user-data:**
```yaml
#cloud-config
growpart:
  mode: auto
  devices: ['/']
  ignore_growroot_disabled: false
```

### 5. Расширение Swap-раздела

Swap нельзя расширить «на горячую».
1. Отключить: `sudo swapoff /dev/sda2`.
2. Расширить раздел: `sudo growpart /dev/sda 2`.
3. Пересоздать структуру: `sudo mkswap /dev/sda2`.
4. Включить: `sudo swapon /dev/sda2`.

### 6. Расширение в LVM-окружении

LVM упрощает процесс, позволяя объединять несколько физических дисков в одну ФС. При изменении размера PV операция должна выполняться в строгой последовательности: PV → VG → LV → ФС.

#### Быстрый пайплайн

```bash
# 1. Обновление размера PV после расширения раздела
sudo pvresize /dev/sdb1

# 2. Расширение LV и ФС одной командой (ext4/XFS)
sudo lvextend -l +100%FREE -r /dev/vg0/lv_root
```

#### Полный workflow (если требуется ручное управление)

**Шаг 1:** Проверка состояния PV/VG/LV:
```bash
sudo pvs
# PV         VG            Fmt  Attr PSize  PFree
# /dev/sdb1  vg_data       lvm2 a--   5.00t    0

sudo vgs
# VG      #PV #LV #SN Attr   VSize   VFree
# vg_data   1   2   0 wz--n-  5.00t    0
```

**Шаг 2:** Обновление PV:
```bash
sudo pvresize /dev/sdb1
# Physical volume "/dev/sdb1" changed
```

**Шаг 3:** Расширение LV до максимального размера:
```bash
sudo lvextend -l +100%FREE /dev/vg0/lv_data
```

**Шаг 4:** Расширение файловой системы:
```bash
# Для ext4
sudo resize2fs /dev/vg0/lv_data

# Для XFS
sudo xfs_growfs /mnt/data
```

*Для детального изучения сложных сценариев LVM см. [Изменение размеров LVM](./LVM/operations/lvm_resize.md).*

### 7. Расширение LUKS+LVM

LUKS добавляет уровень шифрования между разделом и PV. Порядок расширения критичен: **LUKS → PV → VG → LV → ФС**.

```bash
# 1. Расширить раздел (если нужно)
sudo growpart /dev/sda 1

# 2. Увеличить LUKS-контейнер
sudo cryptsetup resize crypt_data

# 3. Обновить размер PV
sudo pvresize /dev/mapper/crypt_data

# 4. Расширить LV и ФС одной командой
sudo lvextend -l +100%FREE -r /dev/vg_data/lv_root
```

**Важно:** Не забывайте про `cryptsetup resize` — без этого `pvresize` увидит старый размер LUKS-контейнера.

*Подробные сценарии LUKS+LVM см. в [Изменение размеров LVM](./LVM/operations/lvm_resize.md), сценарий 5.*

### 8. Настройка auto-extend для Thin Pool

Thin Pool может автоматически расширяться при заполнении, что критично для production-сред с динамическим выделением:

```bash
# Проверка текущих параметров
sudo lvs -o+seg_monitor

# Настройка в /etc/lvm/lvm.conf или через lvchange
sudo lvchange --monitor y --poolmetadataspare 0 vg_thin/tp_root

# Установка порогов auto-extend (в lvm.conf)
thin_pool_autoextend_threshold = 80
thin_pool_autoextend_percent = 20
```

**Требование:** Должен работать `lvm2-monitor` (`dmeventd`). Проверка:
```bash
systemctl status lvm2-monitor
# → active (running)
```

*Подробнее о thin provisioning см. [Thin provisioning](./LVM/thin-provisioning.md) и [Изменение размеров LVM](./LVM/operations/lvm_resize.md), сценарий 6.*

### 9. Расширение VDO (Virtual Data Optimizer)

VDO добавляет слой дедупликации и компрессии поверх LV. Расширение происходит в два этапа: Pool → VDO LV.

```bash
# 1. Расширить VDO Pool LV
sudo lvextend -L +50G vg_vdo/vdo_pool_myvdo

# 2. Расширить сам VDO LV
sudo lvextend -L +200G vg_vdo/myvdo

# 3. Расширить ФС (XFS)
sudo xfs_growfs /mnt/vdo_data
```

**Валидация:**
```bash
lvs -o+vdo_compression,vdo_savings,vdo_used
vdostats --verbose
```

*Детали см. в [VDO](./vdo.md) и [Изменение размеров LVM](./LVM/operations/lvm_resize.md), сценарий 7.*

### 10. Расширение Multipath-устройств

При расширении LUN в СХД нужно обновить все пути multipath перед работой с LVM:

```bash
# 1. Rescan SCSI-устройств (все пути к LUN)
for disk in /sys/class/scsi_device/*/device/rescan; do
    echo 1 | sudo tee "$disk"
done

# 2. Перечитать карту multipath
sudo multipath -r

# 3. Проверить новый размер
lsblk | grep mpath

# 4. PV → VG → LV → ФС
sudo pvresize /dev/mapper/mpatha
sudo lvextend -l +100%FREE -r /dev/vg_data/lv_data
```

**Примечание:** Multipath-устройства (`/dev/mapper/mpath*`) не требуют отдельного `growpart` — они автоматически отражают новый размер LUN после `multipath -r`.

*Детали multipath см. [iSCSI Multipath](../Networking/iSCSI/iscsi_multipath.md) и [Изменение размеров LVM](./LVM/operations/lvm_resize.md), сценарий 8.*

### 11. Расширение RAID-массивов (mdadm)

Software RAID (mdadm) поддерживает добавление устройств и увеличение массива «на лету» через `--grow`:

```bash
# 1. Добавить новый диск в массив (RAID1 → RAID1 с 3 устройствами)
sudo mdadm --grow /dev/md0 --raid-devices=3

# 2. После замены всех дисков на большие — расширить массив
sudo mdadm --grow /dev/md0 --size=max

# 3. Обновить размер ФС
sudo resize2fs /dev/md0
```

**Ограничения:**
- RAID5/6: перестройка массива (reshape) может занимать часы; скорость зависит от `sync_speed` в `/proc/sys/dev/raid/speed_limit_min`.
- Изменение уровня RAID (например, RAID1 → RAID5) возможно, но рискованно; всегда тестируйте на не критичных данных.

*Детали см. [RAID1 management](../FileSystems/RAID/raid1-management.md) и [RAID overview](../FileSystems/RAID/overview.md).*

### 12. Расширение Btrfs (multi-device)

Btrfs — ФС с поддержкой multi-device из коробки. Добавление нового диска не требует LVM:

```bash
# 1. Добавить новое устройство в ФС (online)
sudo btrfs device add /dev/sdc /mnt/btrfs_data

# 2. Проверить баланс
sudo btrfs filesystem df /mnt/btrfs_data

# 3. Перераспределить данные (можно в фоне)
sudo btrfs balance start -dconvert=single -mconvert=single /mnt/btrfs_data

# 4. Проверить новый размер
df -h /mnt/btrfs_data
```

**Важно:** Btrfs balance — долгая операция. Для мониторинга: `watch btrfs filesystem df /mnt/btrfs_data`.

### 13. Расширение Loop-устройств

Loop-устройства часто используются для образов дисков (`.img`, `.qcow2`) и контейнеров. Hot-resize возможен:

```bash
# 1. Увеличить файл образа
truncate -s +10G /var/lib/libvirt/images/vm_disk.img

# 2. Уведомить ядро об изменении размера loop-устройства
sudo losetup -c /dev/loop0

# 3. Расширить ФС
sudo resize2fs /dev/loop0
```

**Автоматический метод (cryptsetup + LVM):** Если loop-устройство содержит LUKS+LVM, следуйте сценарию 7.

*Детали см. [Loop devices](./loop_devices.md).*

### 14. Расширение дисков ВМ (virt-resize)

Для виртуальных машин (KVM/QEMU) можно расширить диск и автоматически корректировать разделы и ФС:

```bash
# 1. Создать целевой образ большего размера
qemu-img create -f qcow2 /tmp/new_disk.qcow2 50G

# 2. virt-resize автоматически расширит разделы и ФС
sudo virt-resize --expand /dev/sda1 /var/lib/libvirt/images/old_disk.qcow2 /tmp/new_disk.qcow2

# 3. Заменить старый образ на новый (ВМ должна быть выключена)
mv /tmp/new_disk.qcow2 /var/lib/libvirt/images/vm_disk.qcow2
```

**Ограничение:** `virt-resize` работает только с выключенной ВМ (offline). Для online-расширения используйте `growpart` внутри гостевой ОС.

*Детали см. [Практические сценарии с образами ВМ](../Virtualization/vm_images/practical_scenarios.md).*

### 15. Добавление нового диска (не расширение существующего)

Частая задача: добавить совершенно новый диск в систему (не расширять существующий раздел). Полный workflow:

```bash
# 1. Идентифицировать новое устройство по stable name (WWID/PARTUUID)
ls -l /dev/disk/by-id/
# → scsi-36000... → /dev/sdb

# 2. Проверить, что диск не содержит разделов
sudo wipefs -a /dev/sdb  # ОСТОРОЖНО: удаляет все сигнатуры

# 3. Создать таблицу разделов и раздел (GPT)
sudo parted /dev/sdb -- mklabel gpt mkpart primary 0% 100%

# 4. Создать ФС
sudo mkfs.ext4 -L data_new /dev/sdb1

# 5. Создать точку монтирования и добавить в fstab
sudo mkdir -p /mnt/data_new
echo 'LABEL=data_new /mnt/data_new ext4 defaults,noatime 0 2' | sudo tee -a /etc/fstab

# 6. Смонтировать
sudo mount -a
```

**Для LVM:** вместо mkfs создайте PV → VG → LV и смонтируйте LV.

### 16. Расширение NVMe namespace

NVMe поддерживает несколько namespace на одном контроллере. Расширение может потребоваться при замене диска на больший:

```bash
# 1. Проверить текущие namespace
sudo nvme list
# → Device   Namespace Usage Format
# → /dev/nvme0n1  1         500 GB  512 B + 0 B

# 2. Если namespace не использует весь доступный пространство — удалить и пересоздать
sudo nvme delete-ns /dev/nvme0n1 -n 1
sudo nvme create-ns /dev/nvme0n1 --size=<total_sectors> --ctrlr-id=1
sudo nvme attach-ns /dev/nvme0n1 -n 1 -c 1

# 3. Rescan ядра
echo 1 | sudo tee /sys/class/block/nvme0n1/device/rescan

# 4. Расширить раздел и ФС (обычный workflow)
```

**Примечание:** Процесс зависит от драйвера и firmware NVMe-устройства. Некоторые контроллеры поддерживают online-resize namespace без удаления.

## Верификация и диагностика

1.  **`lsblk`** — проверка иерархии и размера разделов.
2.  **`df -hT`** — проверка доступного места в ФС.
3.  **`lsblk -f`** — проверка типов ФС и UUID.
4.  **`pvs` / `vgs` / `lvs`** — если используется LVM.

### Итоговая проверка

После всех операций убедитесь, что файловая система увидела новое пространство:
```bash
df -hT
# Filesystem                                Size  Used Avail Use% Mounted on
# /dev/sdb1                                 5.0T  3.3T  1.5T  71% /data
```

### Расширенная диагностика

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **"Device or resource busy"** | `partprobe` не обновляет таблицу разделов. | Раздел используется процессом (mount, swap, LVM PV). | `lsof /dev/sdb1` или `fuser -v /dev/sdb1`; остановить процесс или перезагрузиться. |
| **XFS не растет** | `xfs_growfs` возвращает ошибку. | Указано устройство вместо точки монтирования; ФС не XFS. | Использовать точку монтирования: `xfs_growfs /mnt/data`. |
| **GPT corruption** | `growpart` падает с `GPT: not all of the space available...` | Структуры GPT не обновлены до конца диска. | `sgdisk -e /dev/sdX` → `parted -l` → Fix. |
| **LUKS: pvresize не видит новое место** | `pvresize` возвращает старый PFree. | Забыли `cryptsetup resize` перед `pvresize`. | Выполнить `cryptsetup resize` → `pvresize`. |
| **LVM: LV не расширяется** | `lvextend` возвращает `Insufficient free space`. | VG не имеет свободных PE; нужен новый PV или `vgextend`. | `pvresize` на существующий PV или `vgextend vg_data /dev/sdc1`. |
| **Thin pool заполнен** | `dmeventd` не запускает auto-extend. | `lvm2-monitor` отключен; пороги не настроены. | `systemctl enable --now lvm2-monitor`; настроить `lvm.conf`. |
| **Multipath: новый размер не виден** | `lsblk` показывает старый размер mpath. | Не выполнено `multipath -r` после rescan. | `multipath -r` → `pvresize /dev/mapper/mpatha`. |
| **RAID: reshape зависает** | `mdadm --grow` долго висит. | Низкий `sync_speed`; носитель медленный. | Увеличить `echo 50000 > /proc/sys/dev/raid/speed_limit_min`. |
| **Btrfs: balance зависает** | `btrfs balance start` не завершается. | Высокая нагрузка на ФС; недостаточно места для перемещения блоков. | Остановить `btrfs balance cancel`; проверить `df` и `btrfs filesystem df`. |
| **Loop: resize не работает** | `resize2fs` на loop-устройстве возвращает ошибку. | Ядро не обновлено о новом размере; нет `losetup -c`. | `losetup -c /dev/loopX` перед `resize2fs`. |
| **Swap: swapon падает** | `swapon /dev/sda2` возвращает "device is busy". | swaparea активна (проверьте `swapon --show`). | `swapoff /dev/sda2` → `mkswap` → `swapon`. |
| **GPT: fdisk не сохраняет** | После `w` в `fdisk` таблица не обновлена. | Ядро заняло раздел; `partprobe` не отработан. | `partprobe` или перезагрузка; убедиться, что нет `Device or resource busy`. |

### Проверочные скрипты

```bash
#!/bin/bash
# verify_disk_expansion.sh — базовая проверка после расширения
set -euo pipefail

echo "=== Проверка разделов ==="
lsblk

echo "=== Проверка ФС ==="
df -hT

echo "=== Проверка LVM ==="
pvs
vgs
lvs

echo "=== Проверка монтирований ==="
findmnt

echo "=== Проверка блокировок ==="
sudo lsof /dev/sd* 2>/dev/null || true
```

## Автоматизация и мониторинг

### Мониторинг свободного места (простой скрипт)

```bash
#!/bin/bash
# disk_monitor.sh — мониторинг и автоматическое расширение через LVM
# Предназначен для запуска через cron или systemd-timer

THRESHOLD=90
VG_DATA="vg_data"
LV_DATA="lv_data"
MOUNT_POINT="/data"
EXTEND_SIZE="+10G"

check_and_extend() {
    usage=$(df -h "$MOUNT_POINT" | awk 'NR==2 {print $5}' | tr -d '%')
    if [ "$usage" -ge "$THRESHOLD" ]; then
        echo "$(date): $MOUNT_POINT usage at ${usage}% — extending..."
        sudo lvextend -L $EXTEND_SIZE -r "$VG_DATA/$LV_DATA"
        echo "$(date): Extended $VG_DATA/$LV_DATA by $EXTEND_SIZE"
    fi
}

check_and_extend
```

**Внимание:** Автоматическое расширение без наблюдения опасно. Используйте только в контролируемых средах с уведомлениями (Slack, email).

### Мониторинг Thin Pool

```bash
# Проверка использования thin pool
sudo lvs -o+seg_monitor

# Ожидаемый вывод: VG Data TP 100.00g 85.00g 15.00g
# Если Used接近 100% — auto-extend должен сработать, либо расширяйте вручную
```

## Процедура отката

Расширение обычно необратимо (вы добавляли пространство, но не удаляли данные). Однако при ошибках:

### Откат расширения раздела (fdisk)

Если вы расширили раздел, но еще не записали таблицу (`w` в fdisk):
- Просто не выполняйте `w` — reboot или `partprobe` восстановит старую таблицу.

Если таблица уже записана, но ФС не расширена:
- Раздел больше, чем ФС — это не критично. ФС просто не использует новое пространство.
- Откат: удалите раздел через `fdisk` (с тем же начальным сектором!) и создайте заново с прежним размером.

### Откат LVM

```bash
# Если LV еще не расширен — ничего откатывать не нужно
# Если LV расширен, а данные не записаны:
sudo lvreduce -L -10G /dev/vg_data/lv_data  # ОСТОРОЖНО: уменьшение опасно!
# Лучше: перенести данные на другой LV и удалить текущий
```

**Важно:** Уменьшение (`lvreduce`, `resize2fs` в меньшую сторону) требует **предварительного уменьшения ФС** (`resize2fs /dev/vg_data/lv_data 10G` перед `lvreduce`). Всегда делайте backup перед уменьшением.

### Откат XFS

XFS **не поддерживает уменьшение (shrink)**. Единственный способ отката — backup → пересоздание ФС → restore.

## Лучшие практики

### 1. Резервное копирование

- **Всегда** создавайте backup перед изменением таблицы разделов или LVM-метаданных.
- Для LVM: `vgcfgbackup` перед `vgextend`/`vgreduce`.
- Для разделов: `sfdisk -d /dev/sda > /backup/sda_partitions.sfdisk`.

### 2. Использование stable names

Никогда не полагайтесь на `/dev/sda`, `/dev/sdb` — они могут меняться при перезагрузке. Используйте:
- `/dev/disk/by-id/` (WWID, серийный номер)
- `/dev/disk/by-path/` (PCI path)
- `/dev/mapper/vg_name-lv_name` для LVM
- `/dev/mapper/mpatha` для multipath

### 3. Проверка выравнивания

После расширения раздела проверяйте выравнивание 4K/8K:
```bash
sudo parted /dev/sda align-check optimal 1
# → 1 aligned
```

### 4. Мониторинг после расширения

После расширения настройте мониторинг (Prometheus, Zabbix) на новый порог использования диска. Рекомендуемый порог: 80% (warning), 90% (critical).

### 5. Документирование изменений

Ведите журнал изменений инфраструктуры (ITIL-style):
- Дата, время, окно обслуживания
- Кто выполнил
- Что изменено (диск, раздел, LV)
- Результат проверки (`df -hT`, `lsblk`)

### 6. Тестирование на не критичных хостах

Перед применением на production протестируйте workflow на staging/ВМ с тем же дистрибутивом и версией ядра.

### 7. Использование LVM там, где возможно

LVM eliminates большинство ограничений классической разметки. Используйте LVM для:
- Системных разделов (если поддерживается дистрибутивом)
- Данных, которые могут расти
- ВМ и контейнеров

### 8. Избегание `fdisk` для разделов > 4 ТБ

`fdisk` не работает с дисками > 2 TiB в MBR и имеет проблемы с GPT > 4 ТБ. Используйте `gdisk` или `parted`.

### 9. Проверка UEFI/BIOS ограничений

- BIOS + MBR: максимальный размер диска 2 TiB.
- UEFI + GPT: нет ограничений по размеру.
- Для загрузочных разделов > 2 TiB требуется UEFI.

### 10. Использование `partprobe` вместо reboot

После изменения таблицы разделов попробуйте `sudo partprobe` или `sudo partx -a /dev/sda` перед перезагрузкой. Если ядро не может обновить таблицу (раздел занят) — используйте `kpartx` для работы с образом диска.

## Границы применимости и ограничения

### 1. Барьер 2 TiB (MBR)

MBR (DOS) использует 32-битный счетчик секторов. При секторе 512 байт максимальный размер:
```
2^32 секторов × 512 байт = 2 TiB
```
Для дисков > 2 TiB используйте GPT. Современные диски поставляются с GPT по умолчанию.

### 2. Выравнивание секторов (4K/8K native)

Современные диски (Advanced Format) используют физические секторы 4096 байт (4K). Неправильное выравнивание разделов снижает производительность в 2–3 раза.

**Проверка:**
```bash
sudo fdisk -l /dev/sda | grep "sector size"
# → Sector size (logical/physical): 512 bytes / 4096 bytes
```

**Решение:** Используйте `parted` с опцией `optimal` alignment или начните раздел с сектора 2048 (выравнивание по 1 MiB).

### 3. Ограничения ext4

- Максимальный размер ФС: 1 EiB (экзобайт).
- Максимальный размер файла: 16 TiB (4K block).
- Online-расширение: полностью поддерживается.
- Online-уменьшение: **не поддерживается** (требуется unmount).

### 4. Ограничения XFS

- Максимальный размер ФС: 8 EiB (на практике ограничен оборудованием).
- Максимальный размер файла: 8 EiB.
- **Shrink (уменьшение) не поддерживается** ни online, ни offline (официально не рекомендуется).
- Online-расширение: только в mounted состоянии.

### 5. Ограничения Btrfs

- Максимальный размер ФС: 16 EiB (на практике ограничен).
- Максимальный размер файла: 16 EiB.
- Поддерживает online добавление устройств.
- Shrink возможен offline, но может быть нестабильным на больших объемах.

### 6. Ограничения LVM

- Максимальный размер LV: зависит от версии LVM2 и ядра (обычно 8 EiB).
- Минимальный PE: 1 MiB; рекомендуется 4 MiB (по умолчанию).
- LVM metadata: хранится в начале PV; при повреждении metadata данные недоступны.

### 7. Ограничения RAID (mdadm)

- Максимальный размер массива: зависит от уровня RAID и ядра (обычно 8 ZiB).
- RAID5/6: rebuild при добавлении диска может занять часы/дни; риск второго сбоя.
- Изменение уровня RAID (reshape) поддерживается не всеми уровнями.

### 8. Ограничения VDO

- VDO работает только с блочными устройствами ≥ 10 GB.
- Поддерживает только один VDO LV на один physical LV.
- Нельзя изменить размер VDO LV меньше размера underlying LV.

### 9. Ограничения Cloud-init

Cloud-init auto-grow работает только при наличии пакета `cloud-guest-utils` и правильной конфигурации. На裸 metal-серверах или ВМ без cloud-init auto-grow не работает.

## Краткий справочник (TL;DR)

```bash
# Проверка размеров
lsblk
parted -l
fdisk -l

# Если ядро не видит новый размер
echo 1 | sudo tee /sys/class/block/sda/device/rescan

# Расширение раздела через fdisk (если нет growpart)
sudo fdisk /dev/sda
# p — просмотр
# d — удалить раздел
# n — создать новый (с тем же началом, новым концом)
# p — проверить
# w — записать

# Расширение ФС (ext4)
sudo resize2fs /dev/sda1

# Если LVM
sudo pvresize /dev/sda1
sudo lvextend -l +100%FREE /dev/mapper/vg1-lv-root
sudo resize2fs /dev/mapper/vg1-lv-root

# Если LUKS+LVM
sudo cryptsetup resize crypt_data
sudo pvresize /dev/mapper/crypt_data
sudo lvextend -l +100%FREE -r /dev/vg_data/lv_root

# Если XFS (указать точку монтирования!)
sudo xfs_growfs /mnt/data

# Если Btrfs
sudo btrfs filesystem resize max /mnt/btrfs

# Если VDO
sudo lvextend -L +50G vg_vdo/vdo_pool_myvdo
sudo lvextend -L +200G vg_vdo/myvdo
sudo xfs_growfs /mnt/vdo_data

# Если Multipath
for disk in /sys/class/scsi_device/*/device/rescan; do echo 1 | sudo tee "$disk"; done
sudo multipath -r
sudo pvresize /dev/mapper/mpatha

# Если RAID (mdadm)
sudo mdadm --grow /dev/md0 --raid-devices=3
sudo mdadm --grow /dev/md0 --size=max
sudo resize2fs /dev/md0

# Если ошибка GPT
sudo sgdisk -e /dev/sda
sudo parted -l
# Fix
```

## Дополнительная информация

- **Связанные темы:**
  - [Изменение размеров LVM](./LVM/operations/lvm_resize.md) — SSoT по LVM-ресайзу, 10 практических сценариев.
  - [Восстановление таблиц разделов](./partition_tables_recovery.md) — исправление GPT заголовков после ошибок.
  - [Диагностика дискового пространства](../Diagnostics/Filesystem/filesystem_and_disk_space_diagnostics.md) — действия при нехватке места.
  - [Разделы и файловые системы](./partitions_and_filesystems.md) — основы теории, GPT/MBR, UUID.
  - [Loop devices](./loop_devices.md) — расширение loop-устройств и образов дисков.
  - [VDO](./vdo.md) — оптимизация хранилища с дедупликацией.
  - [LVM — Обзор и основные концепции](./LVM/overview_concepts.md) — архитектура LVM, PV/VG/LV.
  - [Thin provisioning](./LVM/thin-provisioning.md) — тонкое выделение, auto-extend.
  - [RAID overview](../FileSystems/RAID/overview.md) — изменение конфигурации массива (reshape).
  - [iSCSI Multipath](../Networking/iSCSI/iscsi_multipath.md) — расширение multipath-устройств.
  - [Практические сценарии с образами ВМ](../Virtualization/vm_images/practical_scenarios.md) — virt-resize для расширения дисков ВМ.
