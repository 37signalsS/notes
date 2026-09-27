# Инвентаризация оборудования в Linux

## Определения

**`inxi`** — универсальный инструмент для получения краткой, но максимально информативной сводки обо всей системе (ядро, CPU, GPU, RAM, диски, сеть, драйверы). Оптимален для первичной экспресс-диагностики.

**`lshw` (List Hardware)** — комплексная утилита, генерирующая детальное иерархическое дерево аппаратного обеспечения. Извлекает данные из `/proc`, `/sys` и DMI.

**`lspci` (List PCI)** — стандартный инструмент для работы с шиной PCI. Позволяет идентифицировать видеокарты, сетевые адаптеры, NVMe-контроллеры и проверять версии PCIe (до 5.0+).

**`lsusb` (List USB)** — утилита для вывода информации о USB-контроллерах. Для современных стандартов (USB4/Thunderbolt 4) дополняется специализированными инструментами.

**`lsblk` (List Block Devices)** — основной инструмент для визуализации топологии блочных устройств (диски, разделы, LVM, RAID).

**`dmidecode`** — интерфейс для чтения таблиц DMI (SMBIOS). Позволяет получить серийные номера, модель материнской платы, версию BIOS и детальные характеристики слотов памяти.

**`hwinfo`** — мощная альтернатива `lshw`, способная генерировать крайне подробные логи для отчетов в техподдержку.

**`lsscsi`** — утилита для сопоставления логических имен дисков (`/dev/sdX`) с их физическими путями в SCSI/SATA/SAS-контроллерах.

**`nvme-cli`** — специализированный набор инструментов для глубокой диагностики и управления NVMe-накопителями.

**`udevadm info`** — инструмент для получения атрибутов устройства из `sysfs` и свойств `udev`. Используется для стабильного именования, отладки правил и идентификации оборудования по физическим атрибутам (серийный номер, путь на шине, UUID). Детали — в [Udev — динамическое управление устройствами](../Core/udev.md).

**`ethtool`** — стандартный инструмент для диагностики сетевых интерфейсов на физическом уровне (PHY). Позволяет определять модель NIC, поддерживаемые скорости, драйвер и статистику ошибок.

**`ip link`** — утилита из `iproute2` для перечисления сетевых интерфейсов, их состояния (UP/DOWN), MAC-адреса, MTU и скорости. Часто используется для быстрого сопоставления имени интерфейса с драйвером.

**`hwinfo --skeleton`** — режим вывода `hwinfo` в структурированном формате (ключ=значение), удобном для парсинга скриптами, в отличие от стандартного подробного текстового отчета.

**`lspci -s`** — фильтр `lspci` по конкретному адресу PCI-устройства (например, `lspci -s 0000:01:00.0`). Используется для детального анализа отдельного устройства в рамках флота серверов.

**`lsusb -v`** — расширенный вывод `lsusb` с дескрипторами устройств (вендор, продукт, класс, версия USB, потребляемый ток). Полезен для идентификации нестандартных USB-устройств.

---

## Базовые концепции

### Источники данных

| Утилита | Источник данных | Требует root | Основное назначение |
| :--- | :--- | :--- | :--- |
| **`inxi`** | Смешанный (sysfs, proc, dmi) | Нет (частично) | Быстрый человекочитаемый обзор |
| **`lshw`** | DMI, sysfs, /proc | Да | Иерархическая структура железа |
| **`lspci`** | `/sys/bus/pci` | Нет | Шина PCI и драйверы устройств |
| **`lsusb`** | `/sys/bus/usb` | Нет | Периферия и шина USB |
| **`lsblk`** | `/sys/block`, udev | Нет | Блочные устройства и ФС |
| **`dmidecode`** | DMI (BIOS/UEFI) | Да | Низкоуровневые данные (S/N, RAM) |
| **`hwinfo`** | Libhd | Нет (частично) | Глубокий технический отчет |

### Архитектура sysfs и иерархия оборудования

Все современные утилиты инвентаризации опираются на три виртуальные ФС:

1.  **`/sys` (sysfs):** Основной источник данных в рантайме. Дерево организовано по шинам (`/sys/bus/pci`, `/sys/bus/usb`, `/sys/block`) и классам устройств (`/sys/class/net`, `/sys/class/block`). Содержит атрибуты каждого устройства (вендор, модель, драйвер, скорость линка).
2.  **`/proc`:** Виртуальная ФС процессов и ядра. Содержит `/proc/cpuinfo`, `/proc/meminfo`, `/proc/scsi`, `/proc/partitions`. Исторически важна, но многие данные дублируются в `sysfs`.
3.  **DMI/SMBIOS:** Статические таблицы прошивки (BIOS/UEFI). Содержат модель материнской платы, серийные номера, слоты памяти, версию BIOS. Доступны только через `dmidecode` (требует root).

**Важно:** `sysfs` читается без root для большинства атрибутов. `dmidecode` требует root, так как читает физическую память через `/dev/mem`.

### PCI/PCIe: основы архитектуры

Понимание топологии шины критично для диагностики производительности и ошибок.

| Компонент | Назначение |
| :--- | :--- |
| **Root Complex** | Корневой узел, соединяющий CPU/шину с северным мостом. Каждый CPU socket обычно имеет 1–2 Root Complex. |
| **Root Port** | Выход из Root Complex вниз по иерархии. |
| **Switch** | Промежуточный коммутатор, расширяющий количество портов (например, чипсетный PCH). |
| **Endpoint** | Конечное устройство (NIC, GPU, NVMe, звуковая карта). |
| **Link (Lane)** | Физическая линия передачи данных. x1, x4, x8, x16 — количество линков. |
| **Generation** | Скорость на линию: PCIe 3.0 (8 GT/s), 4.0 (16 GT/s), 5.0 (32 GT/s), 6.0 (64 GT/s). |

**Практический совет:** Для определения физического расположения устройства используйте `lspci -tv` (древовидный вывод) или `lspci -nnk -s <addr>`.

### DMI/SMBIOS: типы таблиц

`dmidecode` разбивает данные на типы (тип 0–127). Основные для инвентаризации:

| Тип | Содержимое | Пример использования |
| :--- | :--- | :--- |
| **0** | BIOS | Версия, дата, vendor |
| **1** | Система | Производитель, модель, серийный номер |
| **4** | Процессор | Частота, напряжение, socket |
| **6** | Модуль памяти | Размер, тип (DDR4/DDR5), скорость, производитель |
| **17** | Устройство памяти | Слот, размер, серийный номер, ECC |
| **9** | Слоты PCI | Тип слота (PCIe x16), версия |

### Уровни детализации

- **Экспресс-диагностика**: `inxi -Fz`
- **Краткий обзор**: `lshw -short`, `lspci`, `lsusb`, `lsblk`
- **Глубокий анализ**: `lshw`, `lspci -vvv`, `lsusb -v`, `dmidecode`, `hwinfo`
- **Автоматизация (JSON)**: `lsblk -J`, `lshw -json`, `lscpu -J`

### Виртуализация и оборудование

На виртуальных машинах (VM) вывод утилит специфичен:
- **`lspci`** отображает виртуальные мосты и устройства (например, `Virtio network device`).
- **`lsblk`** отображает виртуальные диски (`vda`, `xvda`).
- **`dmidecode`** часто возвращает информацию о гипервизоре (например, `Manufacturer: QEMU`, `Product Name: Standard PC`).

### NVMe: контроллеры и неймспейсы

NVMe-устройства имеют двухуровневую модель: контроллер (`nvme0`) и неймспейсы (`nvme0n1`, `nvme0n2`). Один контроллер может предоставлять несколько неймспейсов для разделенияstorage или изоляции. Утилита `nvme-cli` работает с обоими уровнями:

```bash
# Список контроллеров и неймспейсов
sudo nvme list

# Детали конкретного контроллера (модель, прошивка, версия NVMe)
sudo nvme id-ctrl /dev/nvme0

# Детали неймспейса
sudo nvme id-ns /dev/nvme0n1
```

### Память: каналы, ранки, ECC

Современные платформы (DDR4/DDR5) используют многоканальную архитектуру. Для оптимальной производительности модули должны быть распределены по каналам равномерно.

```bash
# Определение количества каналов и слотов
sudo dmidecode -t memory | grep -iE "Locator:|Size:|Type:|Speed:|Manufacturer:"

# Проверка поддержки ECC через EDAC
sudo edac-util -v
```

---

## Практические сценарии

### `inxi`: Быстрая сводка системы

```bash
# Полный обзор системы с фильтрацией чувствительных данных (MAC, серийники)
inxi -Fz

# → System:    Host: server1 Kernel: 6.x.x-generic x86_64 bits: 64 Distro: Ubuntu 24.04/26.04
# → CPU:       Info: 16-core model: Intel Core i9-14900K speed: 5700 MHz
# → Graphics:  Device-1: NVIDIA GA102 [GeForce RTX 3090] driver: nvidia v: 550.x
```

### `lshw`: Иерархическая инвентаризация

```bash
# Краткая сводка по классам оборудования
sudo lshw -short

# → H/W path       Device     Class          Description
# → ====================================================
# → /0/100/1.1     /dev/fb0   display        NVIDIA Corporation
# → /0/100/1d/0    eth0       network        Ethernet Connection I219-V

# Получение данных в формате JSON для автоматизации
sudo lshw -json -class network
```

### `lspci`: Шина PCI и PCIe 5.0+

```bash
# Список устройств с указанием используемого драйвера ядра
lspci -nnk

# Проверка физической скорости PCIe и количества линий (LnkSta)
sudo lspci -vvv | grep -iE "LnkSta:|LnkCap:"
# → LnkSta: Speed 32GT/s (PCIe 5.0), Width x16

# Фильтрация по классу устройства (VGA, SATA, NVMe, USB controller и т.д.)
lspci -d ::0300  # Все VGA-устройства (видеокарты)
lspci -d ::0106  # Все NVMe-контроллеры
lspci -d ::0104  # Все SATA-контроллеры
lspci -d ::0200  # Все Ethernet-контроллеры

# Детали конкретного устройства по адресу
sudo lspci -vvv -s 0000:01:00.0

# Обновление локальной базы PCI ID
sudo update-pciids
```

### USB4 и Thunderbolt 4

Для диагностики современных высокоскоростных туннелируемых интерфейсов.

```bash
# Просмотр дерева устройств Thunderbolt (пакет thunderbolt-utils)
lstbt

# Детальный мониторинг USB4 (пакет tbtools)
sudo tbman
```

### `lsusb`: Идентификация USB-устройств

```bash
# Список USB-устройств с вендором и продуктом
lsusb

# Расширенный вывод с дескрипторами (класс, версия USB, ток)
lsusb -v | grep -iE "idVendor|idProduct|bcdUSB|bDeviceClass|bMaxPower"

# Фильтрация по Vendor ID
lsusb -d 046d:  # Все устройства Logitech
```

### `dmidecode`: Низкоуровневые данные BIOS/UEFI

```bash
# Версия BIOS и Embedded Controller
sudo dmidecode -t bios

# Модель системы, производитель, серийный номер
sudo dmidecode -t system

# Детали всех модулей оперативной памяти
sudo dmidecode -t memory | grep -E "Size:|Type:|Speed:|Locator:|Manufacturer:|Part Number:"

# Слоты PCI и их тип
sudo dmidecode -t slot
```

### Инвентаризация оперативной памяти и ECC

```bash
# Общий объем, тип (DDR4/DDR5) и количество слотов
sudo dmidecode -t memory | grep -E "Size:|Type:|Speed:|Locator:"

# Проверка поддержки и состояния ECC (Error Correction Code)
# Требует пакет edac-util или rasdaemon
edac-util -v
```

### Инвентаризация дисков и NVMe 2.0

```bash
# Дерево блочных устройств с UUID и ФС
lsblk -f

# Сопоставление /dev/sdX с контроллерами
lsscsi -g

# Детальные параметры NVMe (модель, прошивка, версия NVMe)
sudo nvme id-ctrl -H /dev/nvme0 | grep -E "Model|Firmware|nvme_ver"
```

### Сетевое оборудование (`ethtool`, `ip link`)

```bash
# Определение драйвера и модели NIC
ethtool -i eth0
# → driver: ixgbe
# → version: 5.1.0-k
# → firmware-version: 0x800003cc

# Проверка физического состояния порта и скорости
sudo ethtool eth0

# Просмотр поддерживаемых функций (Offload, RSS)
sudo ethtool -k eth0

# Быстрый обзор всех интерфейсов с драйверами
ip -d link show
```

### `hwinfo`: Детальный отчет для техподдержки

```bash
# Полный отчет о CPU (включая ревизии и специфические идентификаторы)
hwinfo --cpu

# Сводка по всем классам оборудования (удобно для отчетов)
hwinfo --short

# Структурированный вывод (ключ=значение) для парсинга
hwinfo --skeleton --all

# Отчет в HTML для отправки в техподдержку
sudo hwinfo --html > hwinfo_report.html
```

### `udevadm info`: Идентификация устройств

```bash
# Все свойства устройства (для стабильного именования)
udevadm info --query=property --name=/dev/sdb | grep -E 'ID_SERIAL|ID_PATH|ID_FS_UUID'

# Полный обход атрибутов включая родителей (для отладки правил)
udevadm info -a -n /dev/sdb

# Фильтрация по пути в sysfs (для проверки правил)
udevadm info --query=path --name=/dev/sdb
# → /devices/pci0000:00/0000:00:1f.2/ata1/host0/target0:0:0/0:0:0:0/block/sdb
```

### Автоматизация инвентаризации (JSON и скрипты)

```bash
# Список блочных устройств в JSON
lsblk -J -o NAME,SIZE,TYPE,FSTYPE,UUID,MOUNTPOINTS

# Сеть в JSON (iproute2)
ip -j link show

# PCI-устройства в JSON (ядро 5.10+)
lspci -J

# Полная инвентаризация через lshw (требует root)
sudo lshw -json -quiet

# Пример Bash-скрипта для сбора базовой инвентаризации
#!/bin/bash
# inventory.sh — базовый сбор железа для флота
mkdir -p /tmp/inventory

lshw -json -quiet > /tmp/inventory/lshw.json
lspci -vvv > /tmp/inventory/lspci.txt
lsusb -v > /tmp/inventory/lsusb.txt
sudo dmidecode -t system > /tmp/inventory/system.txt
sudo dmidecode -t memory > /tmp/inventory/memory.txt
lsblk -f > /tmp/inventory/block.txt
ip -s link show > /tmp/inventory/network.txt
```

---

## Диагностика проблем

### Поиск отсутствующего оборудования

1. **Анализ журнала ядра**: `dmesg | grep -iE "pci|usb|error|firmware|failed"`.
2. **Проверка питания**: Убедитесь, что устройство получает питание (особенно для USB/PCIe внешних карт).
3. **Firmware**: Ищите ошибки `Direct firmware load for ... failed`. Установите пакет `linux-firmware`.

### Проблемы с драйверами

Если в `lspci -k` отсутствует строка `Kernel driver in use`:
- Модуль ядра не загружен: проверьте `lsmod`.
- Модуль в черном списке: проверьте `/etc/modprobe.d/`.
- Несоответствие версии ядра: обновите систему.

### Проверка прошивок (firmware)

Устаревшие прошивки BIOS/UEFI, микрокода CPU и встроенное ПО устройств — частая причина нестабильности.

```bash
# Проверка версии BIOS/UEFI
sudo dmidecode -t bios | grep -E "Version:|Release Date:|Vendor:"

# Проверка версии микрокода CPU
grep microcode /proc/cpuinfo | head -1

# Проверка версии прошивки NVMe
sudo nvme id-ctrl /dev/nvme0 | grep -iE "fr|firmware|version"
```

**Пакеты с прошивками:**
- `linux-firmware` — основная коллекция (Wi-Fi, GPU, кодеков).
- `intel-microcode` / `amd-ucode` — патчи микрокода CPU (загружаются при загрузке).
- `firmware-linux-free` / `firmware-linux-nonfree` — в Debian-семействе.

### Отсутствующие PCI-устройства

Если `lspci` не видит ожидаемое устройство:

1. **Проверьте BIOS/UEFI:** Убедитесь, что устройство не отключено в настройках (Secure Boot, IOMMU, SR-IOV).
2. **Проверьте физическое подключение:** Для PCIe карт — переустановите в другой слот, проверьте питание.
3. **Драйвер:** Загрузите модуль вручную (`modprobe <module>`) и проверьте `dmesg`.
4. **IOMMU:** В виртуализации проверьте, что IOMMU включен (`intel_iommu=on` или `amd_iommu=on`).

### Энумерация GPU и дисплеев

```bash
# Все VGA-совместимые устройства
lspci -d ::0300 -nnk

# Детали через DRM/KMS
cat /sys/class/drm/card*/vendor
cat /sys/class/drm/card*/device

# Включенные дисплеи
cat /sys/class/drm/card*/status
# → connected / disconnected
```

### Энумерация аудиоустройств

```bash
# Звуковые контроллеры PCI
lspci -d ::0403 -nnk

# Устройства через ALSA
cat /proc/asound/cards
```

### Thunderbolt: уровни безопасности

```bash
# Текущий уровень безопасности (если установлен bolt)
boltctl

# Или через sysfs (ядро 5.5+)
cat /sys/bus/thunderbolt/devices/domain*/security
# → secure | secure-disconnect | none | user
```

---

## Дополнительная информация

### Сравнение форматов вывода

| Формат | Команда | Применение |
| :--- | :--- | :--- |
| **Текстовый** | `lshw -short` | Чтение человеком |
| **JSON** | `lsblk -J` | Скрипты, автоматизация |
| **XML/HTML** | `sudo lshw -html` | Отчеты для архива |

### Пакеты и зависимости

| Утилита | Пакет (Debian/Ubuntu) | Пакет (RHEL/CentOS) | Зависимости |
| :--- | :--- | :--- | :--- |
| **`inxi`** | `inxi` | `inxi` | `perl`, `pciutils`, `usbutils` |
| **`lshw`** | `lshw` | `lshw` | `libpci3`, `libusb` |
| **`hwinfo`** | `hwinfo` | `hwinfo` | `libhd` |
| **`lsscsi`** | `lsscsi` | `lsscsi` | `sysfsutils` |
| **`edac-util`** | `edac-utils` | `edac-utils` | `edac` модуль ядра |
| **`nvme-cli`** | `nvme-cli` | `nvme-cli` | `libnvme` |
| **`thunderbolt-utils`** | `thunderbolt-tools` | `bolt` | `kernel 5.5+` |

### Firmware и прошивки в Linux

Linux использует несколько механизмов загрузки прошивок:

1.  **`linux-firmware`:** Стандартный пакет с blob-прошивками для Wi-Fi, GPU, медиакодеков.
2.  **Микрокод CPU:** Загружается ядром при старте (`intel-microcode`, `amd-ucode`). Исправляет ошибки процессора без обновления BIOS.
3.  **`request_firmware`:** Механизм ядра, позволяющий драйверам загружать прошивки из `/lib/firmware` по требованию.

**Проверка загруженных прошивок:**
```bash
# Журнал загрузки прошивок
dmesg | grep -i firmware

# Пример вывода:
# → firmwareClass: attempting to load iwlwifi-QuZ-a0-hr-b0-62.ucode
# → firmwareClass: iwlwifi-QuZ-a0-hr-b0-62.ucode loaded successfully
```

### Best Practices для SRE и Sysadmin

1. **Всегда используйте** `lshw -json` или `lsblk -J` для автоматизации. Текстовый вывод ненадежен для парсинга.
2. **Не полагайтесь** на `/dev/sdX` или `/dev/nvme0n1` в скриптах. Используйте стабильные пути (`by-id`, `by-uuid`, `by-path`).
3. **Верифицируйте драйверы** через `lspci -nnk`: отсутствие строки `Kernel driver in use` — сигнал проблемы.
4. **Мониторьте прошивки:** Регулярно проверяйте наличие обновлений, особенно для SSD/RAID-контроллеров и сетевых карт.
5. **Документируйте флот:** Создавайте JSON-отчеты через `hwinfo --skeleton` или `lshw -json` и храните их в CMDB или Git.

### Связанные инструменты

- **Процессор**: детальная топология и флаги — [`cpu_info.md`](./cpu_info.md).
- **Здоровье дисков**: SMART-атрибуты и тесты — [`smartctl/index.md`](./smartctl/index.md).
- **Разделы**: управление таблицами разделов — [`partitions_and_filesystems.md`](../../FileSystems/partitions_and_filesystems.md).
- **Мониторинг ресурсов**: [`top`](../Processes/top.md), [`htop`](../Processes/htop.md).
- **Управление устройствами**: [`udev.md`](../../Core/udev.md) — правила, стабильные имена, системная интеграция.
- **Низкоуровневые сбои**: [`dmesg/troubleshooting.md`](../Kernel/dmesg/troubleshooting.md) — анализ AER, NVMe reset и ошибок шины.
- **Диагностика NVMe**: [`nvme-errors-diagnostics.md`](./nvme-errors-diagnostics.md) — анализ AER и Controller Reset.
- **Удалённое управление серверами**: [`ipmi_bmc.md`](./ipmi_bmc.md) — IPMI/BMC, SEL, удалённое питание, KVM-over-IP.
- **Аппаратный мониторинг**: [`hardware_monitoring.md`](./hardware_monitoring.md) — lm-sensors, hwmon, thermal zones, вентиляторы.
- **Ошибки памяти**: [`memory_ecc_edac.md`](./memory_ecc_edac.md) — ECC, EDAC, MCE, замена DIMM.
- **Прошивки**: [`firmware_update.md`](./firmware_update.md) — fwupd, обновление BIOS/UEFI, microcode.
- **GPU**: [`gpu_diagnostics.md`](./gpu_diagnostics.md) — nvidia-smi, XID errors, AMD GPU.
- **Безопасность загрузки**: [`tpm_secureboot.md`](./tpm_secureboot.md) — TPM2, Secure Boot, Measured Boot.
