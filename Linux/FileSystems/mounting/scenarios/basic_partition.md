# Определения

**Сценарий базовой разметки (Basic partition scenario)** — пошаговый алгоритм подготовки и ввода в эксплуатацию нового накопителя (HDD, SSD, NVMe). 

Процесс включает в себя создание таблицы разделов, инициализацию файловой системы и настройку отказоустойчивого автоматического монтирования, обеспечивающей доступность данных после перезагрузки.

# Основные концепции

## Жизненный цикл подготовки диска

Для обеспечения стабильности системы и сохранности данных подготовка диска выполняется в строго определенном порядке:

1.  **Предварительная проверка**: Валидация выбора устройства, проверка наличия данных, анализ здоровья накопителя.
2.  **Очистка**: Удаление остаточных метаданных (сигнатур ФС, RAID или LVM).
3.  **Разметка (Partitioning)**: Создание логических разделов с учетом выравнивания секторов.
4.  **Форматирование (Formatting)**: Создание структур выбранной файловой системы.
5.  **Тюнинг**: Настройка параметров ФС под ожидаемую нагрузку.
6.  **Монтирование**: Регистрация раздела в ОС и проверка работоспособности.

## Выбор стандарта разметки

| Стандарт | Макс. размер | Макс. разделов | Применение |
| :--- | :--- | :--- | :--- |
| **MBR** (Legacy) | 2 ТБ | 4 основных | Старое оборудование, BIOS. |
| **GPT** (Modern) | 9.4 ЗБ | 128 (обычно) | Современные системы, UEFI, диски > 2 ТБ. |

## Секторы и выравнивание

Современные диски используют физические секторы 4 КБ (4Kn) или эмулируют 512 байт (512e), предоставляя логический размер 512 байт. Если раздел начинается не с границы физического сектора, каждая запись вызывает операцию Read-Modify-Write, что снижает производительность и увеличивает износ.

- **4Kn (4K native):** Физический и логический размер 4096 байт. На NVMe и современных SSD.
- **512e (512 byte emulation):** Физический 4096 байт, логический 512 байт. Распространен на SATA/SSD.
- **Выравнивание по 1 МиБ:** Стандартная практика. Для дисков с логическими секторами 512 байт это соответствует сектору 2048; для 4Kn — сектору 256. Утилиты `parted` (с опцией `-a optimal`) и современный `fdisk` выравнивают разделы автоматически.

Некорректное выравнивание может снизить производительность на 20–50%, особенно на NVMe, где параллелизм обработки запросов критичен.

## Флаги разделов (GPT)

GPT поддерживает именованные флаги (атрибуты), влияющие на обработку раздела ОС:

| Флаг | Назначение | Пример использования |
| :--- | :--- | :--- |
| **boot** | Загрузочный раздел (BIOS) | Legacy-загрузка |
| **esp** | EFI System Partition | Загрузка UEFI, обычно 512 МБ, тип `fat32` |
| **raid** | Раздел для массива MD RAID | `/dev/md0` |
| **lvm** | Раздел для Physical Volume LVM | `/dev/vg0/pv00` |
| **hidden** | Скрытый раздел | Оборудование OEM |
| **swap** | Раздел подкачки | `/dev/sda3` swap |

## Выбор файловой системы под нагрузку

| Сценарий | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **Универсальный / данные общего назначения** | `ext4` | Максимальная совместимость, стабильность, возможность shrink. |
| **Высокопроизводительные хранилища, БД, большие файлы** | `xfs` | Масштабируемость до эксабайт, параллельная запись, отличная работа с NVMe. |
| **Сжатие на лету, снимки, контейнеры** | `btrfs` | Поддержка `compress=zstd`, CoW, send/receive для бэкапов. |
| **Корневой раздел с возможностью отката** | `btrfs` с подтомами | Отдельные подтомы для `/`, `/home`, `/var` с возможностью отката через `snapper`. |
| **Твердотельные накопители с постоянной записью** | `ext4` или `xfs` + `noatime` | Минимизация лишних записей; `discard` для онлайн-TRIM. |

## Резервированное пространство для root

В Ext-системах по умолчанию резервируется 5% для суперпользователя. Защищает критичные разделы (`/`, `/var`) от полного заполнения и позволяет демонам писать логи при заполненном диске.

Для разделов с данными на терабайтных дисках 5% — это десятки гигабайт. Рекомендуется снижать до `0` или `1` через `tune2fs -m`. XFS резервирует пространство по умолчанию, но его процент меньше и менее критичен.

## Журналирование

Журналирование обеспечивает целостность данных при сбоях. Перед выполнением операции ФС записывает намерение в журнал.

**Режимы (на примере Ext4):**
- `data=ordered` (по умолчанию): В журнал пишутся только метаданные, но данные сбрасываются на диск *до* фиксации метаданных.
- `data=journal`: Полное журналирование данных и метаданных (медленно, максимально надежно).
- `data=writeback`: Пишутся только метаданные, порядок записи данных не гарантируется (быстро).

Для базового сценария с данными общего назначения используйте `data=ordered` (по умолчанию). Для баз данных или когда допустима потеря последних операций при сбое — `data=writeback`.

# Практические сценарии

## Сценарий: Подготовка нового диска данных

### 1. Идентификация и очистка

Найдите диск и убедитесь, что это пустое устройство:

```bash
lsblk -p
# → NAME        MAJ:MIN RM  SIZE RO TYPE MOUNTPOINTS
# → /dev/sdb      8:16   0  100G  0 disk 
```

**Предварительная проверка здоровья:**
```bash
sudo smartctl -H /dev/sdb
# → SMART overall-health self-assessment test result: PASSED

sudo smartctl -A /dev/sdb | grep -E 'Reallocated_Sector|Current_Pending_Sector|Offline_Uncorrectable'
# → 5 Reallocated_Sector_Ct   0x0033   100   100   010    Pre-fail  Always   -       0
# → 196 Current_Pending_Sector  0x0012   100   100   000    Old_age   Always   -       0
# → 197 Offline_Uncorrectable   0x0010   100   100   000    Old_age   Offline  -       0
```

Если значения `Reallocated_Sector_Ct`, `Current_Pending_Sector` или `Offline_Uncorrectable` отличны от нуля, возможен физический износ. Для критичных данных используйте новый накопитель.

**Проверка на наличие остаточных метаданных:**
```bash
sudo blkid /dev/sdb
# Если вывод пустой или содержит старые UUID — диск новый или очищен.

sudo wipefs -a /dev/sdb
# → /dev/sdb: 8 bytes were erased at offset 0x00000000: 55 aa
```

### 2. Создание таблицы разделов и разделов

#### Метод А: Автоматизированный (parted)
Рекомендуется для SSD и NVMe, так как автоматически выравнивает разделы по границе 1 МБ.

```bash
# Создание таблицы GPT
sudo parted /dev/sdb mklabel gpt

# Создание раздела (100% объема), выравнивание 1 МиБ
sudo parted -a optimal /dev/sdb mkpart primary ext4 1MiB 100%

# Оповещение ядра об изменениях (без перезагрузки)
sudo partprobe /dev/sdb
```

#### Метод Б: Интерактивный (fdisk)
```bash
sudo fdisk /dev/sdb
```
*   `g` — создать GPT.
*   `n` — новый раздел (принимайте значения по умолчанию для выравнивания).
*   `t` — изменить тип раздела (например, `83` для Linux).
*   `w` — записать изменения.

**Подробное описание горячих клавиш и сценарий работы с `fdisk` и `gdisk` — в [Разделы и файловые системы](../../partitions_and_filesystems.md#Практические-сценарии).**

### 3. Создание файловой системы

**Выбор ФС:** `ext4` — универсальный выбор, `xfs` — для больших объемов и высокой производительности, `btrfs` — при необходимости сжатия и снимков.

```bash
# Для ext4 (с меткой тома DATA и сниженным резервом)
sudo mkfs.ext4 -L DATA -m 1 /dev/sdb1
# → Creating filesystem with 26214400 4k blocks and 6553600 inodes

# Для xfs
sudo mkfs.xfs -f -L DATA_XFS /dev/sdb1
```

### 4. Настройка автоматического монтирования

#### Шаг 1: Получение UUID
```bash
lsblk -dno UUID /dev/sdb1
# → a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

#### Шаг 2: Настройка fstab
Создайте точку монтирования и добавьте запись:

```bash
sudo mkdir -p /mnt/data

# Опция noatime снижает износ диска, nofail предотвращает сбой загрузки при отсутствии диска
echo 'UUID=a1b2c3d4-e5f6-7890-abcd-ef1234567890 /mnt/data ext4 defaults,noatime,nofail 0 2' | sudo tee -a /etc/fstab
```

**Вариант fstab для SSD с TRIM:**
```text
UUID=a1b2c3d4-e5f6-7890-abcd-ef1234567890 /mnt/data ext4 defaults,noatime,nofail,discard 0 2
```

`discard` включает онлайн-TRIM. Альтернатива — периодический запуск `fstrim` (рекомендуется для production), который создает меньшую нагрузку на I/O. См. [Обслуживание SSD](../../../SystemAdministration/fstrim_ssd_maintenance.md).

### 5. Применение и верификация

**Критически важно:** Сначала обновите конфигурацию systemd, затем пробуйте монтировать.

```bash
# 1. Перегенерация юнитов монтирования
sudo systemctl daemon-reload

# 2. Монтирование
sudo mount -a

# 3. Проверка результата
df -hT /mnt/data
# → Filesystem     Type  Size  Used Avail Use% Mounted on
# → /dev/sdb1      ext4   98G   24K   93G   1% /mnt/data

# 4. Проверка целостности fstab
findmnt --verify
# → Success: no errors or warnings detected

# 5. Проверка опций монтирования
findmnt -no OPTIONS /mnt/data
# → noatime,relatime,defaults
```

### 6. Тюнинг файловой системы (опционально)

```bash
# Просмотр параметров ext4
sudo tune2fs -l /dev/sdb1

# Отключение резервирования для данных (уже сделано через -m 1 при mkfs)
sudo tune2fs -m 0 /dev/sdb1

# Изменение интервала проверки (в днях, 0 — отключить)
sudo tune2fs -i 0 /dev/sdb1

# Для XFS: ограничение размера журнала
sudo xfs_info /mnt/data
```

### 7. Проверка после перезагрузки

```bash
sudo systemctl reboot

# После загрузки
findmnt -T /mnt/data
# → TARGET SOURCE    FSTYPE OPTIONS
# → /mnt/data /dev/disk/by-uuid/a1b2... ext4 noatime,relatime

df -hT /mnt/data
```

## Сценарий: Production-сервер с LVM + LUKS (полное шифрование данных)

Типичная конфигурация для серверов с повышенными требованиями к безопасности: `Disk → Partition → LUKS → PV → VG → LV → FS → fstab`.

### Архитектура

```
/dev/sda                    ← физический диск
├── /dev/sda1               ← EFI System Partition (512 MiB, vfat)
├── /dev/sda2               ← /boot (1 GiB, ext4)
├── /dev/sda3               ← encrypted container (LUKS)
│   └── /dev/mapper/crypt_root   ← расшифрованный контейнер
│       ├── /dev/mapper/vg_system-lv_root   ← /     (ext4)
│       ├── /dev/mapper/vg_system-lv_var    ← /var  (xfs)
│       ├── /dev/mapper/vg_system-lv_swap   ← swap
│       └── /dev/mapper/vg_system-lv_home   ← /home (ext4)
```

### Шаг 1: Подготовка диска

```bash
# Очистка и создание GPT
sudo wipefs -a /dev/sda
sudo parted /dev/sda mklabel gpt

# EFI System Partition (обязательно для UEFI)
sudo parted -a optimal /dev/sda mkpart ESP fat32 1MiB 513MiB
sudo parted /dev/sda set 1 esp on

# /boot (отдельный раздел — LUKS не может быть корнем без initramfs)
sudo parted -a optimal /dev/sda mkpart boot ext4 513MiB 1537MiB

# Основной контейнер (все оставшееся место)
sudo parted -a optimal /dev/sda mkpart primary 1537MiB 100%

sudo partprobe /dev/sda
```

### Шаг 2: Настройка LUKS

```bash
# Шифрование раздела ( потребуется ввод пароля )
sudo cryptsetup luksFormat --type luks2 --cipher aes-xts-plain64 \
    --key-size 512 --hash sha256 --iter-time 5000 /dev/sda3

# Открытие контейнера (имя mapper'а: crypt_root)
sudo cryptsetup open /dev/sda3 crypt_root

# Проверка
lsblk /dev/sda3
# → NAME        MAJ:MIN RM  SIZE RO TYPE  MOUNTPOINTS
# → sda3        8:3    0  476G  0 part
# └─crypt_root 253:0   0  476G  0 crypt
```

**Важно:** `--iter-time 5000` увеличивает время хеширования пароля, повышая устойчивость к брутфорсу. Для серверов рекомендуется 3000–10000 мс.

### Шаг 3: LVM

```bash
# Physical Volume
sudo pvcreate /dev/mapper/crypt_root

# Volume Group
sudo vgcreate vg_system /dev/mapper/crypt_root

# Logical Volumes
sudo lvcreate -L 50G  -n lv_root vg_system    # /
sudo lvcreate -L 100G -n lv_var  vg_system     # /var
sudo lvcreate -L 20G  -n lv_swap vg_system     # swap
sudo lvcreate -l 100%FREE -n lv_home vg_system # /home (всё оставшееся)

# Проверка
sudo lvdisplay /dev/vg_system
```

### Шаг 4: Форматирование

```bash
# /boot — ОБЯЗАТЕЛЬНО ДО LUKS (чтобы initramfs мог расшифровать корень)
sudo mkfs.ext4 -L BOOT /dev/sda2

# / — корень
sudo mkfs.ext4 -L ROOT -m 1 /dev/mapper/vg_system-lv_root

# /var — логи и данные (XFS для производительности)
sudo mkfs.xfs -L VAR /dev/mapper/vg_system-lv_var

# /home
sudo mkfs.ext4 -L HOME -m 1 /dev/mapper/vg_system-lv_home

# swap
sudo mkswap -L SWAP /dev/mapper/vg_system-lv_swap

# EFI
sudo mkfs.fat -F 32 -n EFI /dev/sda1
```

### Шаг 5: Точки монтирования и fstab

```bash
# Создание точек
sudo mkdir -p /mnt/new_root/{boot,var,home,boot/efi}

# Монтирование в правильном порядке
sudo mount /dev/mapper/vg_system-lv_root /mnt/new_root
sudo mount /dev/sda2 /mnt/new_root/boot
sudo mount /dev/sda1 /mnt/new_root/boot/efi
sudo mount /dev/mapper/vg_system-lv_var /mnt/new_root/var
sudo mount /dev/mapper/vg_system-lv_home /mnt/new_root/home
```

**fstab для production-сервера с LUKS:**

```bash
# Получение UUID'ов
BOOT_UUID=$(lsblk -dno UUID /dev/sda2)
EFI_UUID=$(lsblk -dno UUID /dev/sda1)
ROOT_UUID=$(lsblk -dno UUID /dev/mapper/vg_system-lv_root)
VAR_UUID=$(lsblk -dno UUID /dev/mapper/vg_system-lv_var)
HOME_UUID=$(lsblk -dno UUID /dev/mapper/vg_system-lv_home)
SWAP_UUID=$(lsblk -dno UUID /dev/mapper/vg_system-lv_swap)

cat <<EOF | sudo tee /mnt/new_root/etc/fstab
# === КОРНЕВОЙ РАЗДЕЛ (LVM на LUKS) ===
UUID=${ROOT_UUID}    /    ext4    defaults,noatime,errors=remount-ro    0    1

# === СИСТЕМНЫЕ РАЗДЕЛЫ ===
UUID=${BOOT_UUID}    /boot        ext4    defaults,noatime    0    2
UUID=${EFI_UUID}     /boot/efi    vfat    defaults,noatime    0    2

# === LVM-ТОМЫ ===
UUID=${VAR_UUID}     /var     xfs    defaults,noatime,nosuid,nodev    0    2
UUID=${HOME_UUID}    /home    ext4   defaults,noatime,nosuid,nodev    0    2

# === SWAP ===
UUID=${SWAP_UUID}    none    swap    sw,discard    0    0

# === ВРЕМЕННЫЕ ФС ===
tmpfs    /tmp        tmpfs    defaults,size=2G,noexec,nosuid,nodev    0    0
tmpfs    /dev/shm    tmpfs    defaults,size=1G,noexec,nosuid,nodev    0    0
EOF
```

### Шаг 6: Обновление initramfs и установка загрузчика

```bash
# Монтирование виртуальных ФС
sudo mount --bind /dev  /mnt/new_root/dev
sudo mount --bind /proc /mnt/new_root/proc
sudo mount --bind /sys  /mnt/new_root/sys
sudo mount --bind /run  /mnt/new_root/run

# chroot
sudo chroot /mnt/new_root /bin/bash

# Установка необходимых пакетов (в chroot)
apt install -y cryptsetup lvm2 systemd-cryptsetup  # Debian/Ubuntu
# или
yum install -y cryptsetup lvm2                       # RHEL/CentOS

# Обновление initramfs (включает поддержку LUKS и LVM)
update-initramfs -u   # Debian/Ubuntu
# или
dracut -f --force     # RHEL/CentOS

# Установка загрузчика
grub-install /dev/sda
update-grub           # Debian/Ubuntu
# или
grub2-install /dev/sda
grub2-mkconfig -o /boot/grub2/grub.cfg  # RHEL/CentOS

exit
```

### Шаг 7: Автоматическое расшифрование при загрузке

**Вариант A: Ввод пароля при загрузке** — стандартный. При загрузке initramfs запросит пароль LUKS.

**Вариант B: Keyfile (автоматическая расшифровка)** — для серверов с IPMI/iDRAC, где физический доступ исключён:

```bash
# Создание keyfile (ВНИМАНИЕ: храните резервную копию!)
sudo dd if=/dev/urandom of=/root/.luks-keyfile bs=1 count=256
sudo chmod 400 /root/.luks-keyfile

# Добавление keyfile в LUKS
sudo cryptsetup luksAddKey /dev/sda3 /root/.luks-keyfile

# В fstab (passno=0 для ключевого файла):
# /dev/mapper/crypt_root    /    ext4    defaults,noatime    0    1

# Или через systemd-cryptsetup:
# /dev/sda3  none  luks,keyfile-offset=0,keyfile=/root/.luks-keyfile
```

**Вариант C: TPM2 (без пароля, привязка к оборудованию)** — ядро 5.12+:

```bash
# Проверка TPM2
systemd-cryptenroll --tpm2-device=list

# Запись в LUKS
sudo systemd-cryptenroll /dev/sda3 --tpm2-device=auto --tpm2-pcrs=0+1+2+3+4+5+7

# Автоматическое расшифрование при совпадении PCR-значений
```

### Шаг 8: Верификация

```bash
# Перезагрузка
sudo reboot

# Проверка после загрузки
lsblk
# → NAME                   MAJ:MIN RM   SIZE RO TYPE  MOUNTPOINTS
# → sda                      8:0    0 476.9G  0 disk
# ├─sda1                   8:1    0   512M  0 part  /boot/efi
# ├─sda2                   8:2    0     1G  0 part  /boot
# └─sda3                   8:3    0 475.4G  0 part
#   └─crypt_root         253:0    0 475.4G  0 crypt
#     ├─vg_system-lv_root 253:1    0    50G  0 lvm   /
#     ├─vg_system-lv_var  253:2    0   100G  0 lvm   /var
#     ├─vg_system-lv_swap 253:3    0    20G  0 lvm   [SWAP]
#     └─vg_system-lv_home 253:4    0 305.4G  0 lvm   /home

sudo cryptsetup status crypt_root
# → /dev/mapper/crypt_root is active and is in use.
# → type:    LUKS2
# → cipher:  aes-xts-plain64

sudo vgs
# → VG         #PV #LV #SN Attr   VSize    VFree
# → vg_system   1   4   0 wz--n- <475.39g    0
```

# Дополнительная информация

## Многопартиционный сценарий (данные + логи + бэкап)

Для SRE-сценариев часто требуется разделить диск на логические области:

```bash
# Очистка
sudo wipefs -a /dev/sdb

# Таблица GPT
sudo parted /dev/sdb mklabel gpt

# Раздел 1: данные (70%)
sudo parted -a optimal /dev/sdb mkpart primary ext4 1MiB 70%

# Раздел 2: логи (20%)
sudo parted -a optimal /dev/sdb mkpart primary xfs 70% 90%

# Раздел 3: бэкап (10%)
sudo parted -a optimal /dev/sdb mkpart primary ext4 90% 100%

# Применение
sudo partprobe /dev/sdb

# Форматирование
sudo mkfs.ext4 -L DATA -m 1 /dev/sdb1
sudo mkfs.xfs -L LOGS /dev/sdb2
sudo mkfs.ext4 -L BACKUP -m 1 /dev/sdb3

# Точки монтирования
sudo mkdir -p /mnt/data /mnt/logs /mnt/backup

# fstab
cat <<EOF | sudo tee -a /etc/fstab
UUID=$(lsblk -dno UUID /dev/sdb1) /mnt/data ext4 defaults,noatime,nofail 0 2
UUID=$(lsblk -dno UUID /dev/sdb2) /mnt/logs xfs defaults,noatime,nofail 0 2
UUID=$(lsblk -dno UUID /dev/sdb3) /mnt/backup ext4 defaults,noatime,nofail 0 2
EOF

sudo systemctl daemon-reload
sudo mount -a
```

## Подготовка диска для RAID

При создании RAID 1/10 оставьте небольшой отступ в конце диска (100–500 МБ) для компенсации разницы в объеме дисков разных вендоров:

```bash
sudo parted /dev/sdb mklabel gpt
sudo parted -a optimal /dev/sdb mkpart primary linux-raid 1MiB 99.5%
```

Создание ФС выполняется на готовом массиве `/dev/md0`, а не на разделе.

## Проверка здоровья и мониторинг

```bash
# SMART-атрибуты
sudo smartctl -H /dev/sdb
sudo smartctl -A /dev/sdb | grep -E 'Reallocated|Pending|Uncorrectable'

# Тест записи (осторожно: уничтожает данные на /dev/sdb)
sudo badblocks -wsv /dev/sdb

# Проверка доступного места и inode
df -hT /mnt/data
df -i /mnt/data

# I/O статистика
iostat -dx 1 5 /dev/sdb1
```

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`wrong fs type, bad option`** | Неверный тип ФС или опция | Проверьте `lsblk -f`, установите пакет с ФС (`e2fsprogs`, `xfsprogs`) |
| **`special device /dev/sdX does not exist`** | Устройство не найдено | Используйте UUID/LABEL вместо пути |
| **`No such device` при загрузке** | Диск отсутствует в ранней стадии | Добавьте `nofail` или `x-systemd.device-timeout=10s` |
| **Система в Emergency Mode** | Ошибка в fstab | Войдите в recovery, исправьте `/etc/fstab`, `mount -a` |
| **`target is busy`** | Процесс удерживает ФС | `lsof +D /mnt/data` / `fuser -vm /mnt/data` |

## Автоматизация (Ansible)

```yaml
- name: Prepare new data disk
  hosts: localhost
  tasks:
    - name: Wipe filesystem signatures
      ansible.builtin.command: wipefs -a /dev/sdb

    - name: Create GPT partition table
      ansible.builtin.command: parted /dev/sdb mklabel gpt

    - name: Create primary partition
      ansible.builtin.command: parted -a optimal /dev/sdb mkpart primary ext4 1MiB 100%

    - name: Notify kernel
      ansible.builtin.command: partprobe /dev/sdb

    - name: Create ext4 filesystem
      ansible.builtin.filesystem:
        fstype: ext4
        dev: /dev/sdb1
        opts: "-L DATA -m 1"

    - name: Create mount point
      ansible.builtin.file:
        path: /mnt/data
        state: directory
        mode: '0755'

    - name: Get UUID
      ansible.builtin.command: lsblk -dno UUID /dev/sdb1
      register: disk_uuid
      changed_when: false

    - name: Add fstab entry
      ansible.builtin.lineinfile:
        path: /etc/fstab
        line: "UUID={{ disk_uuid.stdout }} /mnt/data ext4 defaults,noatime,nofail 0 2"

    - name: Reload systemd daemon
      ansible.builtin.systemd:
        daemon_reload: true

    - name: Mount filesystem
      ansible.builtin.command: mount -a
```

## Очистка и удаление

```bash
# 1. Отмонтировать
sudo umount /mnt/data

# 2. Удалить запись из fstab
sudo sed -i '/\/mnt\/data/d' /etc/fstab

# 3. Перегенерация юнитов
sudo systemctl daemon-reload

# 4. Удалить раздел (в fdisk: d, w) или очистить таблицу
sudo wipefs -a /dev/sdb

# 5. Обнулить начало диска (опционально, для полной очистки)
sudo dd if=/dev/zero of=/dev/sdb bs=1M count=10
```

## Безопасность

```bash
# Ограничение прав на точку монтирования
sudo chmod 700 /mnt/data

# Для разделов с критичными данными добавьте опции монтирования:
# nosuid — запрет SUID/SGID
# nodev — игнорирование блочных устройств
# noexec — запрет выполнения бинарников

echo 'UUID=... /mnt/data ext4 defaults,noatime,nosuid,nodev 0 2' | sudo tee -a /etc/fstab

# Проверка SELinux-контекста (если включен enforcing)
sudo restorecon -Rv /mnt/data
```

# См. также

*   **[Конфигурация fstab](../fstab.md)** — описание всех опций монтирования.
*   **[Команды монтирования](../commands.md)** — детальный разбор `mount` и `findmnt`.
*   **[Разделы и ФС в Linux](../../partitions_and_filesystems.md)** — типы файловых систем и их особенности.
*   **[Обслуживание SSD](../../../SystemAdministration/fstrim_ssd_maintenance.md)** — настройка `fstrim` для новых накопителей.
