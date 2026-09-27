# Процесс загрузки ядра Linux

## Определения

**vmlinux** — статический исполняемый файл ядра в формате ELF. Содержит отладочные символы и не сжат. Используется для анализа дампов памяти (`crash`) и отладки.

**vmlinuz** — сжатый, самораспаковывающийся образ ядра. Это именно тот файл, который находится в `/boot`. Он включает в себя загрузочный код, который распаковывает ядро в оперативную память и передает ему управление.

**initrd (Initial RAM Disk)** — *устаревший* метод (образ файловой системы, например ext2), который монтировался как блочное устройство. Требовал наличия драйвера ФС внутри ядра.

**initramfs (Initial RAM File System)** — *современный* стандарт. Архив `cpio`, который распаковывается ядром в `tmpfs`. Не требует драйверов ФС для монтирования, так как работает напрямую с кэшем страниц. Содержит минимальный набор драйверов (LVM, RAID, LUKS) для поиска реального корня.

**Unified Kernel Image (UKI)** — формат (PE-файл), объединяющий ядро, `initramfs`, командную строку (`cmdline`) и микрокод CPU в один подписанный файл для UEFI. Обеспечивает целостность всей загрузочной цепочки.

**Systemd-stub** — компонент `systemd`, интегрированный в загрузчик UEFI, который извлекает ядро, `initramfs` и параметры из секций UKI и измеряет их в **TPM2 PCR 11**.

**Measured Boot** — процесс записи хешей каждого этапа загрузки (прошивка, загрузчик, ядро) в регистры **TPM2 PCR (Platform Configuration Registers)**. Позволяет реализовать аттестацию и `unseal` ключей шифрования только при неизменности загрузочной цепочки.

**Система инициализации (Init system)** — первый процесс пользовательского пространства (PID 1). В современных системах — **systemd**.

## Основные концепции

### Цепочка передачи управления (Boot Chain)

1. **Прошивка (Firmware: BIOS/UEFI):** Выполняет POST, инициализирует контроллеры памяти и ищет загрузочное устройство. UEFI запускает `.efi` приложение (загрузчик или UKI).
2. **Загрузчик (Bootloader: GRUB, systemd-boot):** Загружает `vmlinuz` и `initramfs` в память. Подготавливает дерево устройств (Device Tree) или таблицу ACPI.
3. **Низкоуровневый старт (Decompression & Mode Switch):**
   - Процессор стартует в 16-битном Real Mode (legacy) или сразу в 32/64-битном (UEFI).
   - Код распаковки в `vmlinuz` переводит CPU в **Long Mode** (64-бит), включает страничную адресацию и распаковывает `vmlinux`.
   - Выполняется переход к точке входа ядра (например, `startup_64`).
4. **Инициализация ядра (`start_kernel`):**
   - `setup_arch()`: Анализ параметров загрузки, инициализация консоли и памяти (E820 map).
   - `trap_init()`: Настройка таблицы прерываний (IDT).
   - `mm_init()`: Настройка аллокаторов памяти (Buddy system, Slab).
   - `sched_init()`: Запуск планировщика задач.
   - `rest_init()`: Создает поток `kernel_init` (будущий PID 1) и `kthreadd` (PID 2).
5. **Раннее пространство пользователя (Early Userspace):** Ядро распаковывает `initramfs` в `tmpfs` и запускает `/init`. Здесь происходит подготовка сложных хранилищ.
6. **Смена корня (switch_root):** `initramfs` очищается, монтируется реальный корень, и управление передается `/sbin/init`.

### Парадокс курицы и яйца: решение через initramfs

Классическая проблема загрузки Linux заключается в следующем: чтобы ядро могло запустить систему, ему нужно примонтировать жёсткий диск и прочитать оттуда драйвер контроллера диска. Но чтобы прочитать этот драйвер с диска, ядру уже нужно иметь этот драйвер в памяти. Получается замкнутый круг.

Для разрыва этого круга инженеры придумали `initramfs` (Initial RAM File System). Вместе с ядром загрузчик GRUB копирует в оперативную память специальный архив — файл с именем `initrd` или `initramfs`. По сути, это крошечный временный прообраз Linux, запечатанный в виртуальный диск в оперативной памяти.

Ядро просыпается в памяти, видит этот готовый RAM-диск и монтирует его как свой самый первый временный корень. Внутри `initramfs` лежат все необходимые драйверы для SATA, NVMe дисков и RAID-контроллеров. Ядро спокойно подгружает эти драйверы прямо из быстрой оперативной памяти, запускает контроллер, находит настоящий жёсткий диск, монтирует его в реальный корень системы, а временный `initramfs` просто стирается из памяти.

Файлы `initramfs` хранятся в каталоге `/boot` рядом с ядром (`vmlinuz-*`). Их размер обычно составляет около 100 МБ. Это и есть наш временный Init RAM FS архив, внутри которого упакованы модули ядра и скрипты.

### Детали инициализации ядра (start_kernel)

Функция `start_kernel()` (в `init/main.c`) является главной точкой входа ядра после распаковки. Она последовательно выполняет критические этапы:

- **`setup_arch()`:** Идентифицирует архитектуру (x86_64, ARM64), инициализирует `boot_command_line`, разбирает таблицу E820 (карту физической памяти), настраивает консоль (VGA/EFI framebuffer).
- **`mm_init()`:** Инициализирует ZONE_DMA, ZONE_NORMAL, ZONE_HIGHMEM (на x86_64), запускает `kmem_cache` (Slab/SLUB), инициализирует `page_alloc` и `vmalloc`.
- **`sched_init()`:** Инициализирует планировщик (EEVDF на 6.12+), создает `runqueues` для каждого CPU, настраивает таймеры (tick/nohz_full).
- **`rcu_init()`:** Запускает подсистему RCU, создает `rcu_sched` и `rcu_bh` kthreads.
- **`trap_init()`:** Настраивает IDT (x86) или VBAR (ARM64), регистрирует обработчики исключений.
- **`local_irq_enable()`:** Разрешает локальные прерывания (первые прерывания обрабатываются после инициализации планировщика).
- **`rest_init()`:** Создает `kernel_init` (PID 1) через `kernel_thread()`, который затем запускает `kernel_init_freeable()` и `/init`.
- **`kernel_init()`:** Монтирует корневой раздел, запускает `systemd` или другой init.

### Раннее пространство пользователя (Early Userspace)

`initramfs` монтируется как `tmpfs` и содержит `/init`. Этот минимальный userspace отвечает за:

- **`devtmpfs`:** Ядро автоматически создает узлы устройств в `/dev` через `kdevtmpfs` (начиная с 2.6.32), но `udevd` (systemd-udevd) управляет правами и симлинками.
- **Загрузка модулей:** `udev` сканирует шины (PCI, USB, ACPI) и подгружает драйверы через `modprobe` на основе `modules.alias`.
- **Подготовка сети:** В сценариях PXE/Diskless — настройка DHCP и монтирование по NFS/iSCSI.
- **Криптография:** Ввод пароля LUKS или автоматическая расшифровка через TPM2/FIDO2.
- **Сборка хранилищ:** Активация LVM групп (`vgchange`) и сборка программных RAID (`mdadm`).

### Современная модель: Unified Kernel Image (UKI)

UKI решает проблему «недоверенного» `initramfs`:
- **Структура PE-файла:** UKI состоит из секций `.linux` (ядро), `.initrd` (initramfs), `.cmdline` (параметры), `.ucode` (микрокод).
- **Целостность:** Весь артефакт подписывается ключом Secure Boot.
- **systemd-stub:** Извлекает компоненты из PE-секций и измеряет их (Measurement) в **TPM2 PCR 11**.
- **Measured Boot:** Позволяет реализовать `unseal` ключей LUKS только в случае неизменности ядра и его параметров через `systemd-pcrlock`.

### Безопасность загрузки

| Компонент | Механизм | PCR | Описание |
| :--- | :--- | :--- | :--- |
| **Прошивка** | Firmware measurements | PCR 0 | Хеш кода прошивки |
| **Загрузчик** | GRUB/shim | PCR 4 | Хеш загрузчика |
| **Secure Boot** | db ключи | PCR 7 | Статус Secure Boot |
| **Ядро UKI** | systemd-stub | PCR 11 | Хеш ядра + cmdline + initrd |

**Lockdown:** При включенном Secure Boot активируется режим **Lockdown** (`integrity` или `confidentiality`), который запрещает:
- Загрузку неподписанных модулей (`module_blacklist` ineffective if `CONFIG_MODULE_SIG_FORCE=y`).
- Доступ к `/dev/mem` и `/dev/kmem`.
- Использование `kexec` без проверки подписи.
- Изменение MSR регистров.

### Архитектурные особенности

#### x86_64 (Legacy BIOS)
- Старт в 16-битном Real Mode (CS=0x0000, IP=0x7c00).
- Переход в 32-бит Protected Mode, затем в 64-бит Long Mode (`cr0`, `cr4`, `efer`).
- Использование ACPI таблиц вместо BIOS interrupt calls.

#### x86_64 (UEFI)
- Старт в 64-битном UEFI environment (DXE phase).
- Загрузчик вызывает `ExitBootServices()` перед передачей управления ядру.
- Использование GOP (Graphics Output Protocol) вместо VBIOS.

#### ARM64 (AArch64)
- Старт в Exception Level 1 (EL1/EL2) в режиме AArch64.
- Использование Device Tree (DTB) вместо ACPI (хотя ACPI поддерживается в Server-режимах).
- Требуется `CONFIG_ARM64` и соответствующая платформенная поддержка.

## Параметры загрузки ядра

Параметры передаются через загрузчик или вшиваются в UKI. Просмотр текущих: `cat /proc/cmdline`.

| Группа | Параметр | Описание |
| :--- | :--- | :--- |
| **Хранилище** | `root=UUID=...` | Указывает на корневое устройство (лучше использовать UUID). |
| | `rootflags=data=writeback` | Параметры монтирования корня (например, для Btrfs). |
| | `rd.luks.name=...` | Имя LUKS-разделов для dracut. |
| **Инициализация** | `init=/bin/bash` | Запуск bash вместо systemd (сброс пароля). |
| | `rd.break` | Остановка загрузки внутри initramfs перед `switch_root`. |
| | `systemd.unit=emergency.target` | Принудительная загрузка в аварийный режим. |
| | `systemd.unit=rescue.target` | Режим спасения (монтирует все ФС, требует пароль). |
| | `systemd.debug_shell` | Запускает root-оболочку на TTY9. |
| | `systemd.confirm_spawn=yes` | Интерактивный запуск сервисов (y/n). |
| **Видео** | `nomodeset` | Отключение загрузки видеодрайверов на раннем этапе (диагностика GPU). |
| | `video=DP-1:e` | Принудительное включение выхода DisplayPort. |
| **Производительность** | `nohz_full=` | Отключает tick scheduler на указанных ядрах. |
| | `rcu_nocbs=` | Отключает RCU callback processing на указанных ядрах. |
| | `isolcpus=` | Изолирует ядра от планировщика. |
| | `intel_pstate=no_hwp` | Отключает Hardware P-states (Intel). |
| **Безопасность** | `lockdown=integrity` | Включает режим Lockdown (Secure Boot). |
| | `slab_nomerge` | Отключает слияние slab-кэшей. |
| | `init_on_alloc=1` | Обнуляет память при выделении. |
| | `pti=on` | Включает Page Table Isolation (Spectre). |
| **Отладка** | `initcall_debug` | Вывод времени выполнения initcall. |
| | `debug` | Включает расширенную отладочную информацию. |
| | `loglevel=7` | Максимальный уровень логирования ядра. |
| | `earlyprintk=...` | Вывод сообщений ядра на раннем этапе. |

## Практические сценарии

### Анализ времени загрузки

Для детального анализа времени загрузки используйте `systemd-analyze`. Подробное описание всех команд, практических сценариев и методик оптимизации см. в **[Анализ производительности (systemd-analyze)](../systemd/performance.md)**.

### Создание и управление UKI

Сборка через `ukify` (входит в состав `systemd`):

```bash
# Сборка образа с подписью
/lib/systemd/ukify build \
    --linux=/boot/vmlinuz-linux \
    --initrd=/boot/initramfs-linux.img \
    --cmdline="root=UUID=... rw quiet" \
    --output=/boot/efi/EFI/Linux/system.efi
```

Для автоматизации в Arch Linux используется `mkinitcpio` с пресетом `uki`, в Fedora — `dracut --uefi`.

### Диагностика проблем загрузки

#### 1. Анализ логов ядра и systemd

```bash
# Логи текущей загрузки (только ошибки)
journalctl -b -p err

# Полный лог загрузки
journalctl -b

# Сообщения ядра (ring buffer)
sudo dmesg -H | grep -iE "error|fail|panic|oops"

# Отслеживание в реальном времени
sudo dmesg -w
```

#### 2. Определение точки отказа

```bash
# Просмотр времени загрузки каждого этапа
systemd-analyze time

# Если ядро загружается медленно — проверка dmesg
dmesg | grep -E "ACPI|error|fail|CPU"

# Если зависает на initramfs — проверка blkid и fsck
blkid
sudo fsck /dev/sdX
```

#### 3. Проверка целостности UKI

```bash
# Проверка подписи UKI (PE-файла)
sbverify --cert /path/to/db.key --key /path/to/db.crt /boot/efi/EFI/Linux/system.efi

# Просмотр секций UKI
objdump -h /boot/efi/EFI/Linux/system.efi

# Просмотр PCR измерений (если есть PCR11)
tpm2_pcrread sha256:11
```

### Пересборка initramfs

После изменения `/etc/fstab` (если изменились UUID) или параметров LVM необходимо обновить образ:

- **Debian/Ubuntu:** `sudo update-initramfs -u -k all`
- **RHEL/Fedora:** `sudo dracut --force`
- **Arch Linux:** `sudo mkinitcpio -P`

### Настройка загрузчика GRUB

```bash
# Проверка конфигурации GRUB
sudo update-grub

# Просмотр текущих параметров
grep GRUB_CMDLINE_LINUX /etc/default/grub

# Ручное добавление параметров (пример для isolcpus)
sudo sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="/&isolcpus=2,3 nohz_full=2,3 rcu_nocbs=2,3 /' /etc/default/grub
sudo update-grub
```

### Загрузка по сети (PXE)

PXE (Preboot Execution Environment) позволяет загружать ОС по сети без локальных дисков:

1. **Этапы PXE:**
   - DHCP: Клиент получает IP, адрес TFTP-сервера и имя загрузчика (`pxelinux.0` или `grubx64.efi`).
   - TFTP: Загружается загрузчик и его конфигурация (`pxelinux.cfg/`).
   - Загрузчик: Загружает ядро и initramfs по TFTP или HTTP (iPXE).

2. **Настройка DHCP (ISC dhcpd):**
   ```bash
   # /etc/dhcp/dhcpd.conf
   subnet 192.168.1.0 netmask 255.255.255.0 {
     range 192.168.1.100 192.168.1.200;
     option routers 192.168.1.1;
     next-server 192.168.1.10;  # TFTP-сервер
     filename "pxelinux.0";      # BIOS
     # filename "grubx64.efi";   # UEFI
   }
   ```

3. **Настройка dnsmasq (простой вариант):**
   ```bash
   dnsmasq \
     --dhcp-range=192.168.1.100,192.168.1.200,12h \
     --dhcp-boot=pxelinux.0 \
     --enable-tftp --tftp-root=/srv/tftp \
     --pxe-service=0,"RHEL 9 Install"
   ```

### Headless загрузка (Serial Console)

Для серверов без монитора настройка последовательной консоли позволяет видеть загрузку через IPMI/DRAC:

```bash
# Добавление в параметры ядра
GRUB_CMDLINE_LINUX_DEFAULT="... console=ttyS0,115200n8 console=tty0"

# В /etc/default/grub
GRUB_TERMINAL="serial"
GRUB_SERIAL_COMMAND="serial --speed=115200 --unit=0 --word=8 --parity=no --stop=1"

# Обновление
sudo update-grub
```

### Проверка поддерживаемых функций ядра

```bash
# Параметры сборки ядра
grep CONFIG_PREEMPT /boot/config-$(uname -r)
# → CONFIG_PREEMPT=y

# Проверка Secure Boot
bootctl status | grep "Secure Boot"
# → Secure Boot: enabled

# Проверка EFI переменных
[ -d /sys/firmware/efi ] && echo "UEFI Mode" || echo "Legacy Mode"

# Проверка модулей ядра
lsmod | head -n 10

# Проверка статуса TPM
cat /sys/class/tpm/tpm0/tpm_version_major
# → 2 (TPM 2.0)
```

## Специфические сценарии

### Boot на ARM64

ARM64 использует Device Tree (DTB) вместо ACPI на большинстве платформ:

```bash
# Проверка DTB
dtc -I fs /proc/device-tree | head -n 20

# Просмотр совместимости
cat /proc/device-tree/compatible
# → "linux,dummy-soc"; "linux,simple-bus"

# Проверка U-Boot (если используется)
env print bootcmd
env print bootargs
```

### Оптимизация загрузки для серверов

```bash
# Отключение ненужных сервисов
sudo systemctl mask plymouth-quit-wait.service
sudo systemctl mask systemd-rfkill.service
sudo systemctl mask NetworkManager-wait-online.service

# Параллельный запуск сервисов (по умолчанию в systemd)
sudo systemctl set-default multi-user.target

# Параметры ядра для быстрой загрузки
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash rd.systemd.show_status=0"
```

### Диагностика зависаний при загрузке

```bash
# Если зависание на раннем этапе — добавьте earlyprintk
GRUB_CMDLINE_LINUX_DEFAULT="... earlyprintk=ttyS0,115200"

# Если зависание в initramfs — rd.breakw
GRUB_CMDLINE_LINUX_DEFAULT="... rd.break"

# Если зависание в systemd — systemd.debug_shell
GRUB_CMDLINE_LINUX_DEFAULT="... systemd.debug_shell"
# Затем Ctrl+Alt+F9 для доступа к shell
```

## Дополнительная информация

### Связанные темы

- **Низкоуровневая прошивка:** [BIOS и UEFI](../firmware_bios_uefi.md) — этапы до передачи управления ядру.
- **Управление загрузчиком:** [GRUB](../../SystemAdministration/grub.md) — настройка традиционной загрузки.
- **Инициализация служб:** [systemd](../systemd/overview.md) — работа после `switch_root`.
- **Диагностика загрузки:** [Восстановление при сбоях загрузки](../../Diagnostics/Troubleshooting/boot_failure_recovery.md) — стратегии LiveCD и chroot.
- **Живые обновления:** [Live Patching и kexec](./live_patching.md) — быстрая перезагрузка через kexec.
- **Журналирование:** [dmesg](../../Diagnostics/Kernel/dmesg/index.md) — просмотр сообщений ядра.
- **Модули ядра:** [Kernel Modules](./kernel_modules.md) — загрузка модулей на этапе initramfs.
- **Интерфейсы ядра:** [Интерфейсы ядра Linux](./kernel_interfaces.md) — syscalls, VFS, Netlink.
