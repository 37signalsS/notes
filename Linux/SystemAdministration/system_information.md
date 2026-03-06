# Информация о системе Linux

## Определения

**Системная информация** — данные о конфигурации, состоянии и характеристиках системы Linux, включая аппаратное обеспечение, ядро, операционную систему и запущенные процессы.

### Источники системной информации

- **Виртуальные файловые системы:** `/proc` (процессы и системные параметры), `/sys` (аппаратное обеспечение и ядро).
- **Логи ядра:** [`dmesg`](../Diagnostics/Kernel/dmesg.md) (сообщения ядра при загрузке и работе).
- **Утилиты:** Специализированные команды, которые парсят данные из этих источников и представляют их в удобном виде (например, `lscpu`, `dmidecode`, `ip`). Подробное сравнение `lscpu` и `dmidecode`, а также источников их данных, см. в [Аппаратная информация о CPU](../Diagnostics/Hardware/cpu_info.md).

### Различия для виртуальных и физических серверов

На **виртуальных машинах (VMs)** информация об оборудовании эмулируется и предоставляется гипервизором. Соответственно, некоторые данные могут отражать виртуализированное окружение, а не реальное физическое железо. Например, `dmidecode` может показать информацию о виртуальном BIOS, а не о BIOS хост-системы.

## Практические сценарии

### Версия ядра и операционной системы

- **Версия ядра:**

    ```bash
    uname -a # Подробная информация о ядре
    cat /proc/version # Информация о ядре и компиляторе
    ```

- **Определение дистрибутива Linux:**

    ```bash
    cat /etc/os-release # Основной способ (NAME, VERSION_ID и т.д.)
    cat /etc/redhat-release # Для RHEL-подобных
    cat /etc/debian_version # Для Debian-подобных
    ```

### Имя хоста (Hostname)

Имя хоста — это уникальное имя, присваиваемое компьютеру в сети. Оно используется для идентификации устройства в локальной сети и в интернете.

- **Просмотр текущего имени хоста:**

    ```bash
    hostname
    ```

    Для получения более подробной информации (FQDN, короткое имя, IP-адреса) используйте `hostname -f` (FQDN), `hostname -s` (короткое имя).

- **Временная установка имени хоста (до перезагрузки):**

    ```bash
    sudo hostname new_hostname
    ```

    Это изменение действует только до следующей перезагрузки системы.

- **Постоянная настройка имени хоста:**
    1. **Редактирование файла `/etc/hostname`:**

        ```bash
        sudo nano /etc/hostname
        # Введите 'new_hostname' в файл
        ```

        Этот файл содержит только короткое имя хоста.
    2. **Редактирование файла `/etc/hosts`:**
        Убедитесь, что IP-адрес `127.0.1.1` (для Debian/Ubuntu) или `127.0.0.1` (для RHEL/CentOS) связан с вашим FQDN и коротким именем хоста.

        ```
        127.0.0.1   localhost
        127.0.1.1   new_hostname.example.com new_hostname
        ```

        Подробнее об этом файле см. в [Настройка и диагностика DNS-клиента в Linux](../Networking/Concepts/dns_client.md).
    3. **Применение изменений без перезагрузки:**

        ```bash
        sudo systemctl restart hostname.service
        # Или вручную
        sudo hostname -F /etc/hostname
        ```

        Изменения в `/etc/hosts` вступают в силу немедленно.

### Процессор (CPU)

- **Модель процессора, количество ядер, поддерживаемые инструкции:**

    ```bash
    lscpu # Сводная информация о CPU
    cat /proc/cpuinfo | grep 'model name' # Только модель
    cat /proc/cpuinfo | grep 'flags' # Поддерживаемые инструкции
    ```

- **Количество физических и логических ядер:**

    ```bash
    grep "cpu cores" /proc/cpuinfo | sort -u # Физические ядра на каждом CPU
    grep -c "processor" /proc/cpuinfo # Общее количество логических ядер
    sudo dmidecode -t processor | grep "Core Enabled:" # Физические ядра (через DMI)
    sudo dmidecode -t processor | grep "Thread Count:" # Логические ядра (через DMI)
    ```

- **Режимы работы процессора (governor):**

    ```bash
    cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
    # powersave, ondemand, performance
    ```

### Память, материнская плата, BIOS

- **Информация о модулях оперативной памяти (RAM):**

    ```bash
    sudo dmidecode --type memory # Подробно о RAM
    sudo dmidecode --type 17 # Аналогично --type memory
    ```

- **Модель материнской платы:**

    ```bash
    sudo dmidecode --type baseboard
    ```

- **Версия BIOS/UEFI:**

    ```bash
    sudo dmidecode --type bios
    ```

### Датчики (температура, напряжение, вентиляторы)

- **Текущие значения датчиков (требует `lm-sensors`):**

    ```bash
    sensors
    ```

- **Через IPMI (для серверов Supermicro):**

    ```bash
    sudo ipmicfg -pminfo
    ```

### Сетевые адаптеры

- **Идентификация адаптеров:**

    ```bash
    lspci | grep -i net # PCI-устройства, связанные с сетью
    lshw -class network -short # Сетевые интерфейсы и их драйверы
    ```

- **Состояние сетевых интерфейсов:**

    ```bash
    ip a # IP-адреса и состояние интерфейсов (UP, DOWN, NO-CARRIER)
    ip link show # Только состояние канального уровня
    ```

### Шины и устройства

- **PCI устройства:**

    ```bash
    lspci -vvv # Подробная информация обо всех PCI-устройствах
    ```

- **USB устройства:**

    ```bash
    lsusb -vvv # Подробная информация обо всех USB-устройствах
    ```

## Дополнительная информация

### Связанные темы

**Диагностика Hardware:**

- **[Диагностика CPU](../Diagnostics/Hardware/cpu_info.md)** — подробная информация о процессоре
- **[Hardware listing](../Diagnostics/Hardware/hardware_listing.md)** — полная инвентаризация оборудования
- **[smartctl](../Diagnostics/Hardware/smartctl.md)** — мониторинг состояния дисков

**Диагностика процессов и памяти:**

- **[ps](../Diagnostics/Processes/ps.md)** — информация о процессах
- **[top/htop](../Diagnostics/Processes/htop.md)** — мониторинг процессов в реальном времени
- **[vmstat](../Diagnostics/Memory/vmstat.md)** — статистика памяти и CPU
- **[proc_meminfo](../Diagnostics/Memory/proc_meminfo.md)** — информация о памяти

**Файловые системы:**

- **[/proc](../FileSystems/virtual_fs_proc.md)** — виртуальная ФС процессов
- **[/sys](../FileSystems/virtual_fs_sys.md)** — виртуальная ФС ядра

**Диагностика сети:**

- **[ip](../Networking/Tools/iproute2/ip_address.md)** — информация о сетевых интерфейсах
- **[ss](../Diagnostics/Networking/ss.md)** — сетевые сокеты
- **[netstat](../Diagnostics/Networking/netstat.md)** — устаревшая, но полезная
