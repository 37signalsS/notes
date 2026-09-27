# Информация о системе Linux

## Определения

- **Системная информация:** Совокупность данных об операционной системе, версии ядра, архитектуре процессора, уникальных идентификаторах узла и конфигурации времени.
- **`/etc/os-release`:** Стандартный файл в современных дистрибутивах (systemd), содержащий метаданные об операционной системе (имя, версия, ID). Является предпочтительным источником по сравнению с устаревшими `/etc/lsb-release` и `lsb_release`.
- **Machine ID:** 128-битный уникальный идентификатор конкретной инсталляции ОС. Хранится в `/etc/machine-id`. Используется для генерации идентификаторов виртуальных машин, журналирования и аутентификации.
- **DMI (Desktop Management Interface) / SMBIOS:** Таблицы в памяти, содержащие информацию об аппаратном обеспечении от производителя (BIOS, серийные номера, слоты памяти). Доступ только через `dmidecode` с правами root.
- **Виртуализация (Virtualization Detection):** Процесс определения того, запущена ли система на физическом оборудовании (Bare Metal) или внутри гипервизора (KVM, VMware) / контейнера.
- **Hostname (Имя хоста):** Сетевое имя узла. В systemd существует три типа:
  - **Static:** Постоянное имя, записанное в `/etc/hostname`. Сохраняется между перезагрузками.
  - **Transient:** Динамическое имя, полученное от DHCP или DNS. Может изменяться.
  - **Pretty:** Человкочитаемое имя (UTF-8), например `"Мой сервер №1"`. Настраивается через `hostnamectl set-hostname --pretty`.
- **Идентификатор среды (Container Detection):** Способ определения, работает ли процесс в контейнере Docker/Podman или на хосте. Проверяется через файлы `/run/systemd/container`, `/.dockerenv` и содержимое `/proc/1/cgroup`.
- **Init system (Система инициализации):** Первый процесс пользовательского пространства (PID 1). В современных дистрибутивах — **systemd**. Определяется через `ps -p 1 -o comm=` или наличие директории `/run/systemd/system`.

## Основные концепции

### Иерархия источников данных

Linux предоставляет системную информацию через несколько уровней абстракции:

1.  **Слой ядра (Virtual FS):**
    - `/proc`: Динамическая информация о состоянии ядра, памяти, процессов и параметров системы.
    - `/sys`: Статическая и динамическая информация об устройствах, драйверах и параметрах оборудования (sysfs).
2.  **Слой конфигурации и ID:**
    - `/etc/os-release`, `/etc/hostname`, `/etc/machine-id`, `/etc/lsb-release` (устаревший).
3.  **Слой системных служб (systemd):**
    - Высокоуровневые API через `hostnamectl`, `timedatectl`, `localectl`, `loginctl`.
4.  **Слой внешних утилит:**
    - Обертки над виртуальными ФС и DMI (`inxi`, `fastfetch`, `lscpu`, `lshw`).

### Идентификация в гибридных средах

На современных системах важно различать физическую и виртуальную среду:
- **`systemd-detect-virt`**: Позволяет быстро определить тип виртуализации.
- **`virt-what`**: Скрипт, определяющий гипервизор через последовательные проверки (DMI, sysfs, CPU flags).
- **Облачные метаданные**: В публичных облаках информация об инстансе доступна через локальный API (адрес `169.254.169.254`).

### Типы хостовых имен и идентификация

Утилита `hostnamectl` управляет тремя типами имен хоста:
- **Static:** Постоянное имя из `/etc/hostname`. Устанавливается через `sudo hostnamectl set-hostname --static <name>`.
- **Transient:** Имя, полученное от DHCP/DNS. Может быть сброшено через `sudo hostnamectl set-hostname --transient <name>`.
- **Pretty:** Человекочитаемое имя. Используется в интерфейсах и выводе `hostnamectl`.

Также `hostnamectl` показывает тип шасси (chassis): `desktop`, `laptop`, `server`, `vm`, `container`.

### Классификация сред выполнения

| Среда | Характеристики | Методы идентификации |
| :--- | :--- | :--- |
| **Bare Metal** | Физический сервер без гипервизора | `systemd-detect-virt` → `none`, `dmidecode` показывает реальный vendor |
| **Виртуальная машина** | Полная виртуализация с гипервизором | `systemd-detect-virt` → `kvm`, `vmware`, `oracle`; `virt-what` |
| **Контейнер** | Изоляция через namespaces/cgroups | `/.dockerenv`, `cat /run/systemd/container`, `grep docker /proc/1/cgroup` |
| **Псевдовиртуализация (Paravirt)** | KVM/QEMU с драйверами Virtio | `lspci` → `Virtio network device` |

## Практические сценарии

### 1. Быстрая сводка состояния системы

Для получения мгновенного обзора системы (логотип дистрибутива, ядро, аптайм, ресурсы) используются современные "fetch"-утилиты:

```bash
# Современный стандарт для быстрой сводки (быстрее чем neofetch)
fastfetch

# Детальная текстовая сводка (включая GPU и драйверы)
inxi -Fz

# Минималистичный аналог (требует меньше ресурсов)
pfetch

# Устаревший стандарт (медленнее fastfetch)
neofetch
```
*Подробнее об инвентаризации оборудования см. в: **[Инвентаризация оборудования](../Diagnostics/Hardware/hardware_listing.md)**.*

### 2. Идентификация ОС и ядра

```bash
# Информация о ядре (версия и архитектура)
uname -r
# → 6.8.0-44-generic

# Полная информация о системе (ядро, дата сборки, тип ОС)
uname -a
# → Linux server01 6.8.0-44-generic #44-Ubuntu SMP x86_64 GNU/Linux

# Стандартный файл метаданных дистрибутива
cat /etc/os-release
# → NAME="Ubuntu"
# → VERSION_ID="24.04"
# → ID=ubuntu
# → ID_LIKE=debian

# Устаревший метод (для совместимости со старыми скриптами)
lsb_release -a
# → Distributor ID: Ubuntu
# → Description:    Ubuntu 24.04 LTS
# → Release:        24.04
# → Codename:       noble

# Точная версия ядра и компилятор
cat /proc/version
# → Linux version 6.8.0-44-generic (buildd@lcy02-amd64-042) ...

# Параметры загрузки ядра (командная строка)
cat /proc/cmdline
# → BOOT_IMAGE=/boot/vmlinuz-6.8.0-44-generic root=UUID=... ro quiet splash
```

### 3. Управление идентификаторами хоста

Утилита `hostnamectl` является стандартом для управления именем и проверки типа шасси.

```bash
# Просмотр общей информации: имя, machine-id, виртуализация, ядро
hostnamectl
# → Static hostname: server01
# → Icon name: computer-vm
# → Chassis: vm
# → Machine ID: a1b2c3d4e5f6...
# → Boot ID: f6e5d4c3b2a1...
# → Operating System: Ubuntu 24.04 LTS
# → Kernel: Linux 6.8.0-44-generic
# → Architecture: x86-64

# Установка нового статического имени хоста
sudo hostnamectl set-hostname --static my-server-01

# Установка человекочитаемого имени
sudo hostnamectl set-hostname --pretty "Мой сервер №1"

# Определение типа виртуализации
systemd-detect-virt
# → kvm, vmware, oracle (VirtualBox) или none (Bare Metal)
```

### 4. Время работы и нагрузка (Uptime)

```bash
# Текущее время, аптайм, количество пользователей и Load Average (1, 5, 15 мин)
uptime
# → 14:30:00 up 45 days,  3:12,  2 users,  load average: 0.52, 0.38, 0.41

# Время последнего запуска системы
uptime -s
# → 2026-08-01 11:18:00

# Источник данных /proc/uptime (секунды аптайма и idle)
cat /proc/uptime
# → 3883200.42 1245678.20 (первое число — аптайм в секундах, второе — сумма idle)
```
*Интерпретация Load Average описана в: **[Планирование процессов: LA](../Core/processes/scheduling.md#интерпретация-load-average)**.*

### 5. Анализ процесса загрузки (Performance)

Служба systemd предоставляет мощные инструменты для анализа того, на что тратится время при старте.

```bash
# Общее время загрузки (ядро + initrd + пользователи)
systemd-analyze
# → Startup finished in 2.5s (kernel) + 10.2s (userspace) = 12.7s

# Детальная временная шкала early userspace
systemd-analyze time

# Список юнитов, замедляющих загрузку (от самых медленных)
systemd-analyze blame
# → 7.345s network-manager.service
# → 2.120s dev-sda2.device

# Визуализация критической цепочки зависимостей
systemd-analyze critical-chain

# Диаграмма Ганта загрузки в SVG (требует graphviz)
systemd-analyze plot > boot.svg

# Проверка синтаксиса и логических ошибок unit-файлов
systemd-analyze verify myapp.service

# Пути поиска unit-файлов
systemd-analyze unit-paths
```
*Глубокий анализ systemd-analyze см. в: **[systemd-analyze: Анализ производительности](../Core/systemd/performance.md)**.*

### 6. Определение типа среды выполнения (Bare Metal / VM / Container)

Для принятия решений в скриптах и конфигурациях важно точно определить тип среды.

```bash
# Быстрое определение через systemd
systemd-detect-virt
# → kvm, vmware, oracle, none

# Детекция контейнера (Docker/Podman)
cat /run/systemd/container 2>/dev/null && echo "Container detected"
# Или
[ -f /.dockerenv ] && echo "Docker container"

# Проверка cgroup для контейнерных сигнатур
grep -aE "docker|kubepods|containerd" /proc/1/cgroup || echo "Bare Metal or VM"

# Определение через virt-what (требует установки пакета)
sudo virt-what
# → kvm

# Проверка модели процессора (эмулированная или реальная)
grep -E "model name|flags" /proc/cpuinfo | head -n 1
# → model name : Common KVM processor (внутри KVM без nested virt)
```

### 7. Управление временем и локалью

```bash
# Просмотр времени, часового пояса и NTP статуса
timedatectl
# → Local time: Sat 2026-09-13 14:30:00 UTC
# → Universal time: Sat 2026-09-13 14:30:00 UTC
# → RTC time: Sat 2026-09-13 14:30:00
# → Time zone: UTC (UTC, +0000)
# → System clock synchronized: yes
# → NTP service: active

# Установка часового пояса
sudo timedatectl set-timezone Europe/Moscow

# Включение NTP синхронизации
sudo timedatectl set-ntp true

# Просмотр локальных настроек (раскладка, язык)
localectl
# → System Locale: LANG=en_US.UTF-8
# → VC Keymap: us
# → X11 Layout: us,ru
# → X11 Model: pc105
```

### 8. Проверка параметров ядра и sysctl

```bash
# Текущее значение конкретного параметра ядра
sysctl kernel.hostname
# → kernel.hostname = server01

# Просмотр всех параметров (слишком длинный вывод, используйте grep)
sysctl -a | grep -E "net.ipv4|net.core|fs.file-max"

# Изменение параметра (временно, до перезагрузки)
sudo sysctl -w net.core.somaxconn=1024

# Постоянное изменение (запись в /etc/sysctl.conf или /etc/sysctl.d/)
echo "net.core.somaxconn = 1024" | sudo tee /etc/sysctl.d/99-custom.conf
sudo sysctl -p /etc/sysctl.d/99-custom.conf

# Параметры ядра через виртуальную ФС /proc/sys
cat /proc/sys/kernel/ostype
# → Linux
cat /proc/sys/kernel/osrelease
# → 6.8.0-44-generic
cat /proc/sys/kernel/version
# → #44-Ubuntu SMP PREEMPT_DYNAMIC ...
```

### 9. Сбор system info для аудита и CMDB

Стандартизированный сбор данных для документирования инфраструктуры:

```bash
#!/bin/bash
# system_audit.sh — сбор системной информации для аудита и CMDB
# Требует прав root для полного доступа к DMI и некоторым файлам.

OUTPUT_DIR="/tmp/system_audit_$(hostname)_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT_DIR"

# Базовая идентификация
hostnamectl > "$OUTPUT_DIR/hostnamectl.txt"
cat /etc/os-release > "$OUTPUT_DIR/os-release.txt"
uname -a > "$OUTPUT_DIR/uname.txt"
cat /proc/version > "$OUTPUT_DIR/kernel_version.txt"
cat /proc/cmdline > "$OUTPUT_DIR/kernel_cmdline.txt"

# Железо (требует root)
dmidecode -t system > "$OUTPUT_DIR/dmi_system.txt"
dmidecode -t bios > "$OUTPUT_DIR/dmi_bios.txt"
dmidecode -t memory > "$OUTPUT_DIR/dmi_memory.txt"
lshw -json -quiet > "$OUTPUT_DIR/lshw.json"
lspci -vvv > "$OUTPUT_DIR/lspci.txt"
lsusb -v > "$OUTPUT_DIR/lsusb.txt"
lsblk -f > "$OUTPUT_DIR/lsblk.txt"

# Сеть
ip -j link show > "$OUTPUT_DIR/interfaces.json"
ip -j addr show > "$OUTPUT_DIR/addresses.json"

# Время и локаль
timedatectl > "$OUTPUT_DIR/timedatectl.txt"
localectl > "$OUTPUT_DIR/localectl.txt"

# Архивирование
tar czf "${OUTPUT_DIR}.tar.gz" -C "$OUTPUT_DIR" .
echo "Audit collected: ${OUTPUT_DIR}.tar.gz"
```

### 10. Incident Response: минимальный набор данных

При расследовании инцидента или обращению в техподдержку соберите минимальный набор:

```bash
# 1. Идентификация системы
hostnamectl
uname -a
cat /etc/os-release

# 2. Состояние загрузки (uptime, load average)
uptime
cat /proc/loadavg
cat /proc/uptime

# 3. Последние события загрузки
journalctl -b -p err --no-pager | tail -n 50
dmesg | tail -n 50

# 4. Журнал последних перезагрузок
last -x | grep reboot | head -n 5

# 5. Виртуализация и контейнеры
systemd-detect-virt
cat /run/systemd/container 2>/dev/null || echo "Not a container"

# 6. Критичные ошибки ядра
dmesg | grep -iE "error|fail|oom|panic|segfault" | tail -n 20
```

### 11. Проверка статуса поддержки дистрибутива (EOL)

```bash
# Ubuntu: проверка статуса поддержки через ubuntu-support-status
ubuntu-support-status

# Debian: проверка черезDebian Security Tracker (вручную или через API)
# Для RHEL/CentOS/Fedora: проверка через Red Hat Insights илиSubscription Manager
sudo subscription-manager status

# Проверка даты сборки ядра (свежесть ядра = актуальность исправлений)
uname -v
# → #44-Ubuntu SMP PREEMPT_DYNAMIC (сборка от 2026-08-15)
```

## Дополнительная информация

### Ссылки на специализированную диагностику (SSoT)

Для глубокого анализа конкретных подсистем используйте профильные разделы:

- **Процессор:** Топология, флаги, NUMA, C-states — **[Диагностика CPU](../Diagnostics/Hardware/cpu_info.md)**.
- **Оборудование:** Полная инвентаризация (lshw, lspci, dmidecode) — **[Инвентаризация оборудования](../Diagnostics/Hardware/hardware_listing.md)**.
- **Загрузка ядра:** BIOS/UEFI → GRUB → initramfs → systemd — **[Процесс загрузки ядра](../Core/kernel/boot_process.md)**.
- **Память:** Свободно/Занято, буферы — **[Статистика памяти (/proc/meminfo)](../Diagnostics/Memory/proc_meminfo.md)**.
- **Диски:** Разделы, точки монтирования — **[Диагностика ФС и дисков](../Diagnostics/Filesystem/filesystem_and_disk_space_diagnostics.md)**.
- **PCI/USB:** Список шин и контроллеров — **[Инвентаризация оборудования](../Diagnostics/Hardware/hardware_listing.md)**.
- **Сенсоры:** Температура и напряжение — `sensors` (пакет `lm-sensors`).

### Журналы и виртуальные ФС

- **Логи ядра:** Для просмотра событий инициализации оборудования используйте `dmesg`. Подробнее: **[dmesg — сообщения ядра](../Diagnostics/Kernel/dmesg/index.md)**.
- **Журнал загрузки:** Все события текущей загрузки — `journalctl -b`. Подробнее: **[Управление journalctl](../Diagnostics/journalctl/journalctl_management.md)**.
- **ФС /proc:** Динамические параметры ядра. Подробнее: **[Виртуальная ФС /proc](../FileSystems/virtual_fs_proc.md)**.
- **ФС /sys:** Прямой доступ к параметрам устройств. Подробнее: **[Виртуальная ФС /sys](../FileSystems/virtual_fs_sys.md)**.

### Machine-ID и безопасность

`/etc/machine-id` должен быть уникальным для каждой системы. При клонировании виртуальных машин его необходимо сбрасывать:

```bash
sudo rm /etc/machine-id
sudo systemd-machine-id-setup
```
Это критично для работы DHCP, IPv6 и некоторых систем управления конфигурациями (Ansible).

### Загрузка и параметры ядра

- **Ядро и параметры загрузки:** `/proc/cmdline` содержит параметры, переданные ядру загрузчиком (GRUB/systemd-boot). Важные параметры: `root=`, `ro`, `quiet`, `splash`, `initrd=`.
- **Версия ядра:** `/proc/version` содержит точную версию, дату сборки и компилятор.
- **Загрузочные сообщения:** `dmesg` показывает события от самого раннего этапа загрузки (POST, обнаружение оборудования, инициализация драйверов).

### Типичные ошибки и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `hostnamectl` показывает `localhost` | Пустой или отсутствующий `/etc/hostname` | `cat /etc/hostname` | `sudo hostnamectl set-hostname <name>` |
| `machine-id` пустой после клонирования | Скопирован без сброса | `cat /etc/machine-id` | `sudo rm /etc/machine-id && sudo systemd-machine-id-setup` |
| `systemd-detect-virt` не установлен | Пакет `systemd` устарел или отсутствует | `which systemd-detect-virt` | `sudo apt install systemd` или использовать `virt-what` |
| `hostname` не разрешается | Отсутствует запись в `/etc/hosts` | `getent hosts $(hostname)` | Добавить `127.0.1.1 <hostname>` в `/etc/hosts` |
| Неправильное время/NTP не работает | `systemd-timesyncd` отключен или заблокирован | `timedatectl status` | `sudo timedatectl set-ntp true` |

## Дополнительная информация

### Смежные темы

- **[/proc — виртуальная ФС](../FileSystems/virtual_fs_proc.md):** Полный справочник `/proc/PID/*` и `/proc/sys/`.
- **[/sys — sysfs](../FileSystems/virtual_fs_sys.md):** Архитектура sysfs, `/sys/class/`, `/sys/devices/`.
- **[sysctl: Обзор](../Core/kernel/sysctl.md):** Механизм настройки параметров ядра через `/proc/sys/`.
- **[sysctl для production](../Core/kernel/sysctl_production.md):** Рекомендуемые параметры для серверов.
- **[Базовый чеклист производительности](performance_baseline.md):** Практический набор sysctl и limits для нового сервера.
- **[Загрузка ядра](../Core/kernel/boot_process.md):** Полная последовательность загрузки Linux.
- **[GRUB](grub.md):** Управление загрузчиком и параметрами ядра.
