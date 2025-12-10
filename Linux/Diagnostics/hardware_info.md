# Команды для проверки аппаратного обеспечения в Linux

## lscpu

Самая простая команда для получения информации о процессорных мощностях (CPU) - `lscpu`. Она не имеет каких-либо дополнительных опций и выполняется в единственном исполнении:

```bash
lscpu
```

**Пример вывода:**

```
Architecture:          i686
CPU op-mode(s):        32-bit, 64-bit
Byte Order:            Little Endian
CPU(s):                1
On-line CPU(s) list:   0
Thread(s) per core:    1
Core(s) per socket:    1
Socket(s):             1
Vendor ID:             GenuineIntel
CPU family:            6
Model:                 94
Stepping:              3
CPU MHz:               3191.969
BogoMIPS:              6383.93
Hypervisor vendor:     Microsoft
Virtualization type:   full
L1d cache:             32K
L1i cache:             32K
L2 cache:              256K
L3 cache:              3072K
```

## lshw – список железных компонентов

Если у вас не исполняется данная команда, то вам необходимо установить `lshw` дополнительно. Например, в CentOS это можно сделать командой `sudo yum install lshw`.

Данная команда позволяет получить информативное описание компонентов вашего сервера, в том числе CPU, памяти, USB/NIC, аудио и прочих:

```bash
lshw -short
```

**Пример вывода:**

```
H/W path          Device       Class      Description
=====================================================
                               system     Virtual Machine
/0                             bus        Virtual Machine
/0/0                           memory     64KiB BIOS
/0/5                           processor  Intel(R) Core(TM) i3-6100T CPU @ 3.20GHz
/0/51                          memory     4GiB System Memory
/0/100                         bridge     440BX/ZX/DX - 82443BX/ZX/DX Host bridge (AGP disabled)
/0/100/7                       bridge     82371AB/EB/MB PIIX4 ISA
/0/100/7.1        scsi1        storage    82371AB/EB/MB PIIX4 IDE
/0/100/7.1/0.0.0  /dev/cdrom1  disk       DVD reader
/0/100/7.3                     bridge     82371AB/EB/MB PIIX4 ACPI
/0/100/8                       display    Hyper-V virtual VGA
/0/1              scsi2        storage
/0/1/0.0.0        /dev/sda     disk       160GB SCSI Disk
/0/1/0.0.0/1      /dev/sda1    volume     500MiB EXT4 volume
/0/1/0.0.0/2      /dev/sda2    volume     149GiB Linux LVM Physical Volume partition
/1                eth0         network    Ethernet interface
```

## lspci – список PCI

Данная команда отображает список всех PCI – шин и устройств, подключенных к ним. Среди них могут быть VGA – адаптеры, видео – карты, NIC, USB, SATA – контроллеры и прочие:

```bash
lspci
```

**Пример вывода:**

```
00:00.0 Host bridge: Intel Corporation 440BX/ZX/DX - 82443BX/ZX/DX Host bridge (AGP disabled) (rev 03)
00:07.0 ISA bridge: Intel Corporation 82371AB/EB/MB PIIX4 ISA (rev 01)
00:07.1 IDE interface: Intel Corporation 82371AB/EB/MB PIIX4 IDE (rev 01)
00:07.3 Bridge: Intel Corporation 82371AB/EB/MB PIIX4 ACPI (rev 02)
00:08.0 VGA compatible controller: Microsoft Corporation Hyper-V virtual VGA
```

### lsscsi (список SCSI/SATA устройств)

`lsscsi` — утилита, которая выводит информацию обо всех подключенных SCSI и SATA устройствах в удобном формате. Это простой и эффективный инструмент для диагностики, инвентаризации и управления устройствами хранения данных.

#### Что можно узнать с помощью `lsscsi`?

*   Устройства хранения данных (HDD, SSD).
*   Оптические приводы (CD/DVD).
*   Информацию о типе устройства (диск, DVD, лента).
*   Путь к устройству в системе (например, `/dev/sdb`, `/dev/sr0`).

#### Установка

Если команда `lsscsi` недоступна, её можно установить из репозиториев пакетов:

*   **Для CentOS/RHEL:**
    ```bash
    sudo yum install lsscsi
    ```
*   **Для Ubuntu/Debian:**
    ```bash
    sudo apt install lsscsi
    ```

#### Примеры использования

*   **Базовый вывод списка SCSI/SATA устройств:**
    ```bash
    lsscsi
    ```
    Пример результата:
    ```
    [3:0:0:0]    disk    ATA      WD1600JS-55NCB1  CC38  /dev/sdb
    [4:0:0:0]    cd/dvd  SONY     DVD RW DRU-190A  1.63  /dev/sr0
    ```
    *   `[3:0:0:0]` — адрес устройства (хост, канал, идентификатор, логический номер).
    *   `disk`/`cd/dvd` — тип устройства.
    *   `ATA` — интерфейс (в данном случае, SATA).
    *   `/dev/sdb` — путь к устройству в файловой системе.

*   **Получение более детальной информации (`-l`):**
    С ключом `-l` команда покажет дополнительные данные:
    ```bash
    lsscsi -l
    ```

*   **Форматированный вывод (`--classic`):**
    Вывод в виде таблицы с заголовками:
    ```bash
    lsscsi --classic
    ```

#### Практическое применение

*   **Диагностика подключенных дисков:** Быстрый способ проверить подключение или обнаружить новое устройство.
*   **Работа с CD/DVD-приводами:** Удобно для проверки состояния оптических приводов перед записью или чтением.
*   **Управление устройствами в серверной среде:** Полезно для администраторов, работающих с большим количеством дисков в SCSI- или SATA-массиве.

### dmidecode

Данная команда отличается от остальных тем, что парсит информацию о железе из SMBIOS/DMI (очень детальный вывод).

```bash
# Посмотреть информацию о CPU
sudo dmidecode -t processor
# RAM информация
sudo dmidecode -t memory
# Информация о BIOS
sudo dmidecode -t bios
```

### mount

Утилита `mount` предназначена для управления и просмотра смонтированных файловых систем и соответствующих точек:

```bash
mount | column -t
```

**Пример вывода:**

```
/dev/mapper/VolGroup-lv_root  on  /                          type  ext4         (rw)
proc                          on  /proc                      type  proc         (rw)
sysfs                         on  /sys                       type  sysfs        (rw)
devpts                        on  /dev/pts                   type  devpts       (rw,gid=5,mode=620)
tmpfs                         on  /dev/shm                   type  tmpfs        (rw)
/dev/sda1                     on  /boot                      type  ext4         (rw)
/dev/mapper/VolGroup-lv_home  on  /home                      type  ext4         (rw)
/var/spool/asterisk/monitor   on  /var/www/html/ast_mon_dir  type  none         (rw,bind)
none                          on  /proc/sys/fs/binfmt_misc   type  binfmt_misc  (rw)
```

### lsusb – список USB-шин и подробная информация об устройствах

Команда расскажет про USB-контроллеры и устройства, подключенные к ним. По умолчанию, команда отобразит краткую информацию. В случае, если необходима глубокая детализация, воспользуйтесь опцией `-v`:

```bash
lsusb
# Для подробной информации
lsusb -v
```

**Пример вывода:**

```
Bus 003 Device 001: ID 9c6a:00c1 Linux Foundation 1.1 root hub
Bus 004 Device 002: ID 092e:00de Microsoft Corp. Basic Optical Mouse v2.0
```
