# Виртуальная файловая система /sys (sysfs)

## Определения

- **sysfs:** Виртуальная файловая система (псевдо-ФС), монтируемая в каталог `/sys`. Она служит структурированным интерфейсом для экспорта объектной модели ядра (**Kernel Object Model**) в пространство пользователя. В отличие от `/proc`, которая ориентирована на процессы и общую статистику, `sysfs` фокусируется на иерархии оборудования, драйверов и подсистем ядра.
- **Kobject (Kernel Object):** Фундаментальная структура данных в ядре Linux, представляющая абстрактный объект (устройство, шина, модуль). Каждый каталог в `/sys` — это визуализация конкретного **kobject**.
- **Kset:** Набор однотипных **kobjects**, объединенных в логическую группу (например, все устройства на шине PCI).
- **Attribute (Атрибут):** Обычный файл внутри каталога `sysfs`, представляющий конкретный параметр объекта (например, серийный номер, состояние питания).
- **configfs:** «Родственная» ФС (обычно в `/sys/kernel/config`), которая, в отличие от `sysfs`, предназначена для создания объектов ядром по инициативе пользователя (например, динамическое создание iSCSI-целей).
- **Refcount (Reference Count):** Счётчик ссылок на `kobject`, управляемый макросами `kobject_get()` / `kobject_put()`. Когда счётчик достигает нуля, ядро вызывает метод `release()` и освобождает память.
- **Kref:** Обёртка вокруг refcount, предоставляющая типбезопасный цикл жизненного цикла объекта.
- **Uevent (Userspace Event):** Текстовое сообщение, генерируемое ядром через netlink-сокет `NETLINK_KOBJECT_UEVENT` при изменении состояния `kobject`. Содержит переменные окружения (`ACTION`, `DEVPATH`, `SUBSYSTEM`) для обработки `udev`.

## Основные концепции

### Философия и структура

Главный принцип `sysfs` — **«один файл — одно значение»**. Это упрощает парсинг в скриптах и автоматизацию через `udev`.

#### Топология каталогов

1.  **`/sys/devices/`:** Фундаментальное дерево всех устройств. Отражает реальную физическую топологию (как устройства подключены друг к другу и к шинам). Почти все остальные каталоги `/sys` содержат символические ссылки на объекты в этом дереве.
2.  **`/sys/bus/`:** Группировка по типу передачи данных (pci, usb, scsi, virtio). Внутри каждой шины есть каталоги `devices` (все устройства на шине) и `drivers` (все драйверы, обслуживающие эту шину).
3.  **`/sys/class/`:** Логическая группировка по функциональному назначению (подсистемам).
    - `net/`: Сетевые интерфейсы.
    - `block/`: Диски и разделы.
    - `power_supply/`: Аккумуляторы, адаптеры питания.
    - `tty/`: Терминалы.
4.  **`/sys/module/`:** Параметры загруженных модулей (LKM). Здесь можно менять настройки модулей «на лету», если драйвер это поддерживает.
5.  **`/sys/fs/`:** Параметры и статистика активных файловых систем.
6.  **`/sys/firmware/`:** Интерфейс к прошивке (BIOS/UEFI). Например, переменные EFI доступны в `/sys/firmware/efi/efivars/`.

### Жизненный цикл kobject

Каждый `kobject` существует в ядре до тех пор, пока его refcount не обнулится:

1.  **Allocation:** Драйвер создаёт `kobject` через `kobject_create_and_add()` или `kobject_init()` + `kobject_add()`. Ядро создаёт каталог в `sysfs` и связывает его с родительским объектом.
2.  **Registration:** Атрибуты объекта создаются через `__ATTR()` / `__ATTR_RO()` / `__ATTR_RW()`. Ядро создаёт файлы в каталоге объекта и связывает их с методами `show()` (чтение) и `store()` (запись).
3.  **Reference Counting:** Каждое обращение к объекту увеличивает refcount. Потоки ядра, `sysfs` и `udev` держат ссылки, предотвращая преждевременное освобождение.
4.  **Release:** Когда refcount достигает нуля, ядро вызывает метод `release()`, удаляет атрибуты из `sysfs` и освобождает память.

**Практическое значение для SRE:** Если объект «исчезает» из `/sys` при активном использовании (например, при горячем отключении диска), это означает, что драйвер корректно освободил `kobject`. Если объект остаётся в `/sys` без драйвера — возможна утечка ссылок (kobject leak).

### Атрибуты и права доступа

Атрибуты в `sysfs` — это обычные файлы, но их содержимое генерируется ядром динамически:

- **Текстовые атрибуты:** Обычные файлы, методы `show()` / `store()` работают с текстовым представлением (например, `cat /sys/block/sda/queue/scheduler`).
- **Бинарные атрибуты:** Используются для произвольных бинарных данных (например, EDID монитора, VPD диска). Доступны через `bin_attribute` и требуют Alignment по размеру страницы.
- **Права по умолчанию:** Обычно `0444` (чтение для всех) или `0644` (чтение + запись для root). Права задаются в макросе `__ATTR()` при компиляции драйвера.
- **Безопасность:** Запись в атрибуты требует `CAP_SYS_ADMIN` или соответствующих прав на файл. Изменение атрибутов без понимания последствий может привести к недоступности устройства или потере данных.

### Механизм Uevents

При изменении состояния любого **kobject** (подключение устройства, изменение режима питания) ядро генерирует **uevent** — текстовое сообщение, передаваемое через netlink-сокет. Эти сообщения являются триггером для работы `udev`, который на их основе создает ноды в `/dev` и применяет правила.

**Поток uevent:**
1. Драйвер вызывает `kobject_uevent()` для `kobject`.
2. Ядро формирует переменные окружения (`ACTION=add|remove|change`, `DEVPATH=/devices/...`, `SUBSYSTEM=block`).
3. Сообщение отправляется через `NETLINK_KOBJECT_UEVENT` всем подписчикам.
4. `systemd-udevd` получает uevent, импортирует атрибуты из `sysfs`, применяет правила.
5. По правилам создаются симлинки, назначаются права, запускаются сервисы.

### sysfs против procfs

| Критерий | sysfs (`/sys`) | procfs (`/proc`) |
| :--- | :--- | :--- |
| **Назначение** | Объектная модель ядра (устройства, драйверы, модули) | Процессы, системная статистика, параметры ядра |
| **Структура** | Иерархическая, отражает связи объектов | Древовидная PID-ориентированная + файлы параметров |
| **Создание файлов** | Динамическое ядром через `kobject` и `attribute` | Статические или генерируемые на лету обработчиками |
| **Запись** | Ограничена атрибутами `store()` | Широкий набор (`/proc/sys/` — sysctl) |
| **Главный потребитель** | `udev`, `systemd`, утилиты инвентаризации | Приложения (`ps`, `top`), `sysctl`, `cgclassify` |
| **Производительность** | Высокая (кешируется в slab) | Высокая, но при большом количестве процессов — выше накладные |

### Безопасность sysfs

- **Глобальность:** `sysfs` монтируется единообразно для всех namespaces и не имеет per-namespace копий (в отличие от `/proc`, где есть `/proc/<PID>/`).
- **Права на запись:** Изменение атрибутов (`driver/unbind`, `power/control`, `scheduler`) требует `root`. Ошибка в скрипте может привести к недоступности оборудования.
- **Информационная безопасность:** Атрибуты могут раскрывать конфиденциальную информацию (серийные номера, MAC-адреса, версии прошивок). В контейнерах `sysfs` виден полностью, что расширяет поверхность атаки.
- **Защита:** Используйте `chmod`/`mount --bind` для ограничения доступа к критичным каталогам в production. Для отладочных `sysfs` (debugfs, tracefs) применяйте `chmod 750`.

## sysfs в контейнерах и namespaces

В отличие от `/proc`, `sysfs` не поддерживает per-namespace изоляцию на уровне содержимого. Контейнеры видят ту же иерархию, что и хост, что создаёт риски:

- **Утечка информации:** Контейнер может читать атрибуты всех устройств хоста (серийные номера, модели, пути PCI).
- **Блокирующие операции:** Попытка записи в атрибуты устройств, не принадлежащих контейнеру, завершится ошибкой `Permission denied` или `EBUSY`, но сам `sysfs` доступен.
- **Рекомендация:** Для контейнеров используйте `--read-only` для `/sys` или настройте AppArmor/SELinux профили, ограничивающие доступ к `/sys`.

```bash
# Проверка монтирования sysfs в контейнере
docker exec container1 mount | grep sysfs
# → sysfs on /sys type sysfs (rw,nosuid,nodev,noexec,relatime)

# Ограничение доступа: read-only bind mount
sudo mount --bind /sys /sys
sudo mount -o remount,ro /sys
```

## Администрирование и диагностика

### Обзор критических путей sysfs

| Путь | Назначение | Типичные задачи |
| :--- | :--- | :--- |
| `/sys/block/<dev>/queue/scheduler` | Активный планировщик I/O | Тюнинг производительности дисков |
| `/sys/block/<dev>/queue/nr_requests` | Глубина очереди запросов | Настройка под высокие нагрузки |
| `/sys/block/<dev>/device/` | Атрибуты контроллера (SATA/SCSI/NVMe) | Идентификация модели, прошивки |
| `/sys/class/net/<iface>/speed` | Скорость сетевого интерфейса | Мониторинг линка |
| `/sys/class/power_supply/` | Состояние батарей и адаптеров | Мониторинг заряда ноутбуков/ИБП |
| `/sys/firmware/efi/efivars/` | Переменные UEFI (NVRAM) | Управление загрузкой (осторожно!) |
| `/sys/bus/pci/devices/` | Устройства на шине PCI | Инвентаризация, переподключение |
| `/sys/module/<name>/parameters/` | Параметры загруженных модулей | Динамический тюнинг без перезагрузки |
| `/sys/class/block/<dev>/stat` | Счётчики I/O устройства | Производительность, отладка |
| `/sys/class/dmi/id/` | Аппаратная информация (DMI/SMBIOS) | Инвентаризация серверного железа |

### Инвентаризация оборудования через sysfs

```bash
#!/bin/bash
# sysfs_inventory.sh — инвентаризация оборудования без внешних утилит
# Требует root для чтения некоторых атрибутов

echo "=== CPU ==="
cat /sys/devices/system/cpu/online
# → 0-15

echo "=== Память ==="
cat /sys/devices/system/memory/block_size_bytes
# → 100000000

echo "=== PCI устройства ==="
ls /sys/bus/pci/devices/ | while read -r dev; do
    echo "$dev: $(cat /sys/bus/pci/devices/$dev/vendor 2>/dev/null):$(cat /sys/bus/pci/devices/$dev/device 2>/dev/null)"
done

echo "=== Блочные устройства ===
lsblk -f -o NAME,SIZE,TYPE,FSTYPE,MODEL,SERIAL,ROTA

echo "=== Сетевые интерфейсы ==="
ls /sys/class/net/ | while read -r iface; do
    echo "$iface: $(cat /sys/class/net/$iface/type) $(cat /sys/class/net/$iface/speed 2>/dev/null) Mbps"
done
```

### Мониторинг и observability

`sysfs` предоставляет доступ к метрикам, которые могут использоваться в Prometheus exporters (node_exporter) и скриптах:

```bash
# Статистика I/O устройства (в байтах)
cat /sys/block/sda/stat
# →  12345  0  67890  0  12345  0  67890  0  0  0  0

# Парсинг: reads, reads_merged, sectors_read, time_reading, writes, writes_merged, ...

# Детальная статистика NVMe
cat /sys/block/nvme0n1/stat
sudo nvme smart-log /dev/nvme0n1  # через утилиту nvme-cli

# Мониторинг питания
cat /sys/class/power_supply/BAT0/capacity
cat /sys/class/power_supply/BAT0/status
# → Discharging

# Тепловые зоны CPU
for tz in /sys/class/thermal/thermal_zone*; do
    echo "$tz: $(cat $tz/temp 2>/dev/null) мК"
done
```

### systemd и sysfs

`systemd` активно читает `sysfs` для создания `.device` юнитов и управления зависимостями:

- Каждое устройство, обнаруженное в `sysfs`, получает соответствующий `.device` юnit (например, `dev-disk-by\x2did-ata-Samsung_SSD_860.device`).
- `systemd` отслеживает события `uevent` через `udev` и переключает состояния юнитов.
- В `udev` правилах можно использовать `ENV{SYSTEMD_WANTS}` для запуска сервисов при подключении устройства.

```bash
# Просмотр device-юнитов
systemctl list-units --type=device

# Зависимости устройства
systemctl show dev-disk-by\x2did-ata-Samsung_SSD_860.device

# Принудительный повторный вызов udev events
sudo udevadm trigger --subsystem-match=block
```

### Постоянная настройка атрибутов sysfs

Изменения через `tee` сбрасываются при перезагрузке. Для постоянства используйте `udev` правила или `systemd` tmpfiles:

```bash
# /etc/udev/rules.d/99-sysfs-tuning.rules
# HDD: BFQ планировщик
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="1", ATTR{queue/scheduler}="bfq"
# NVMe: отключение планировщика
ACTION=="add|change", KERNEL=="nvme*", ATTR{queue/scheduler}="none"
# USB авто-сон
ACTION=="add|change", SUBSYSTEM=="usb", ATTR{power/control}="auto"

# Применение
sudo udevadm control --reload-rules
sudo udevadm trigger --type=devices --action=add
```

### Диагностика загрузки и оборудования через sysfs

```bash
# Проверка, загружено ли ядро с поддержкой sysfs
grep -q sysfs /proc/filesystems && echo "sysfs supported" || echo "sysfs not supported"

# Проверка монтирования
mount | grep sysfs
# → sysfs on /sys type sysfs (rw,nosuid,nodev,noexec,relatime)

# Проверка версии ядра и доступности атрибутов
uname -r
ls /sys/devices/system/cpu/cpu0/cpufreq/  # если cpufreq включён

# Диагностика проблем с обнаружением устройств
# Если устройства нет в /sys/devices — драйвер не загружен или оборудование не опознано
dmesg | grep -iE "pci|usb|nvme|scsi" | tail -20

# Проверка состояния шины
ls /sys/bus/pci/devices/ | wc -l
```

## Практические сценарии

### 1. Управление жизненным циклом оборудования

`sysfs` позволяет «переподключать» устройства без перезагрузки, что критично при отладке драйверов или пробросе устройств в ВМ (VFIO).

```bash
# Идентификация устройства (PCI ID)
lspci -D | grep Ethernet
# → 0000:00:1f.6 Ethernet controller...

# Отключение устройства от текущего драйвера
echo "0000:00:1f.6" | sudo tee /sys/bus/pci/devices/0000:00:1f.6/driver/unbind

# Инициирование пересканирования шины (поиск новых устройств)
echo 1 | sudo tee /sys/bus/pci/rescan
```

### 2. Сбор метрик без внешних утилит

Прямое обращение к атрибутам быстрее и надежнее в критических скриптах автоматизации.

```bash
# Проверка типа загрузки (UEFI vs BIOS)
[ -d /sys/firmware/efi ] && echo "UEFI" || echo "Legacy BIOS"

# Состояние заряда батареи в процентах
cat /sys/class/power_supply/BAT0/capacity

# Скорость сетевого интерфейса (в Мбит/с)
cat /sys/class/net/eth0/speed
```

### 3. Тюнинг производительности дисков

Настройка планировщика и параметров очереди (Queue) для SSD/NVMe.

```bash
# Просмотр активного планировщика (в скобках)
cat /sys/block/nvme0n1/queue/scheduler
# → [none] mq-deadline kyber

# Включение глубокой очереди запросов для высоконагруженных систем
echo 256 | sudo tee /sys/block/sda/queue/nr_requests
```

### 4. Динамическая отладка ядра (Dynamic Debug)

Если ядро собрано с `CONFIG_DYNAMIC_DEBUG`, можно включать отладочные сообщения для конкретных модулей или функций через `debugfs`.

```bash
# Включение всех сообщений для модуля nfsd
echo 'module nfsd +p' | sudo tee /sys/kernel/debug/dynamic_debug/control
```

### 5. Runtime Power Management

Управление энергопотреблением конкретных устройств.

```bash
# Перевод USB-устройства в режим авто-сна при простое
echo auto | sudo tee /sys/bus/usb/devices/1-1/power/control

# Отключение авто-сна для критичного устройства (например, RAID контроллера)
echo on | sudo tee /sys/bus/pci/devices/0000:00:1f.2/power/control
```

### 6. Инвентаризация оборудования для CMDB

Сбор данных о сервере для базы данных оборудования (CMDB):

```bash
#!/bin/bash
# cmdb_collector.sh — минимальный сборщик инвентаризации

echo "hostname=$(hostname)"
echo "kernel=$(uname -r)"
echo "cpu=$(cat /sys/devices/system/cpu/online)"
echo "memory_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')"

echo "=== PCI ==="
for dev in /sys/bus/pci/devices/*; do
    id=$(basename "$dev")
    vendor=$(cat "$dev/vendor" 2>/dev/null)
    device=$(cat "$dev/device" 2>/dev/null)
    echo "pci.$id=$vendor:$device"
done

echo "=== Диски ==="
lsblk -d -o NAME,SIZE,MODEL,SERIAL,ROTA

echo "=== Сеть ==="
for iface in /sys/class/net/*; do
    name=$(basename "$iface")
    [ "$name" = "lo" ] && continue
    mac=$(cat "$iface/address" 2>/dev/null)
    speed=$(cat "$iface/speed" 2>/dev/null)
    echo "net.$name=$mac $speed Mbps"
done
```

### 7. Мониторинг температуры и питания

```bash
# Температурные зоны (многопоточные серверы)
for tz in /sys/class/thermal/thermal_zone*; do
    temp_mk=$(cat "$tz/temp" 2>/dev/null)
    type=$(cat "$tz/type" 2>/dev/null)
    echo "$type: $((temp_mk / 1000))°C"
done

# Статус питания
cat /sys/class/power_supply/AC/online
# → 1 (подключен к сети)

# Напряжение и ёмкость батареи (ноутбуки/ИБП)
cat /sys/class/power_supply/BAT0/voltage_now
cat /sys/class/power_supply/BAT0/charge_full
```

### 8. Отладка проблем с устройствами

```bash
# Проверка, видит ли ядро устройство
ls /sys/bus/pci/devices/ | grep -i "0000:01:00.0"

# Просмотр статуса устройства (enabled/disabled)
cat /sys/bus/pci/devices/0000:01:00.0/enable
# → 1

# Проверка ошибок AER (Advanced Error Reporting) для PCIe
cat /sys/bus/pci/devices/0000:01:00.0/aer_dev_correctable
cat /sys/bus/pci/devices/0000:01:00.0/aer_dev_uncorrectable

# Сброс счётчика ошибок (если драйвер поддерживает)
echo 1 | sudo tee /sys/bus/pci/devices/0000:01:00.0/reset_method
```

### 9. Управление CPU frequency scaling

```bash
# Доступные governors
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors
# → performance powersave ondemand conservative

# Текущий governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
# → performance

# Установка performance для всех ядер
for cpu in /sys/devices/system/cpu/cpu[0-9]*; do
    echo performance | sudo tee "$cpu/cpufreq/scaling_governor"
done

# Текущая частота (в кГц)
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq
# → 4500000
```

### 10. Безопасное отключение устройств

```bash
# PCIe устройство: перевод в режим D3cold (глубокий сон)
echo 0 | sudo tee /sys/bus/pci/devices/0000:01:00.0/enable

# USB устройство: отключение питания
echo 0 | sudo tee /sys/bus/usb/devices/1-1/power/autosuspend
echo 0 | sudo tee /sys/bus/usb/devices/1-1/authorized

# Повторное подключение
echo 1 | sudo tee /sys/bus/pci/devices/0000:01:00.0/enable
```

## Диагностика неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Устройство отсутствует в `/sys/devices/`** | Драйвер не загружен или оборудование не обнаружено | Проверьте `dmesg | tail`, загрузите модуль (`modprobe`) |
| **`sysfs` недоступен (No such file or directory)** | ФС не смонтирована или повреждена | `mount -t sysfs sysfs /sys` (обычно монтируется ядром автоматически) |
| **Атрибут отсутствует (No such file or directory)** | Драйвер не экспортирует этот атрибут или ядро собрано без поддержки | Проверьте документацию драйвера, версию ядра |
| **`Permission denied` при записи в атрибут** | Недостаточно прав (не root) или атрибут только для чтения | `sudo tee /sys/...`, проверьте права файла (`ls -l`) |
| **`Device or resource busy` при отключении** | Устройство используется (смонтировано, открыто процессом) | `lsof +D /mnt/data`, `umount`, остановите зависимые сервисы |
| **Устройство «исчезло» из `/sys` после отключения** | Нормальное поведение: драйвер корректно удалил `kobject` | Проверьте `dmesg` на предмет ошибок отключения |
| **Не удаётся переподключить PCIe устройство** | Устройство не поддерживает hotplug или занято VFIO/GPU | Проверьте `reset_method`, используйте `probe` вместо `rescan` |

## Чек-лист перед изменением sysfs

Изменения атрибутов `sysfs` влияют на работающее ядро. Выполняйте предварительные проверки:

1. **Резервное копирование:** Если изменяете параметры диска или RAID, убедитесь, что данные сохранены.
2. **Документирование:** Запишите исходные значения атрибутов перед изменением (`cp /sys/block/sda/queue/scheduler /tmp/scheduler.bak`).
3. **Понимание рисков:** Изучите документацию драйвера. Неправильный scheduler или `nr_requests` может снизить производительность.
4. **Тестирование:** Применяйте изменения на тестовом стенде перед production.
5. **Постоянство:** Используйте `udev` правила, а не скрипты в `/etc/rc.local` для применения настроек после перезагрузки.
6. **Мониторинг:** После изменения метрик (`iostat`, `await`, `%util`) наблюдайте за поведением системы 5–10 минут.

## Справочник инструментов для работы с sysfs

| Инструмент | Назначение | Пример |
| :--- | :--- | :--- |
| **`udevadm info`** | Детальная информация об устройстве и его атрибутах | `udevadm info -a -n /dev/sda` |
| **`udevadm monitor`** | Мониторинг событий uevent в реальном времени | `udevadm monitor --kernel --udev --subsystem-match=block` |
| **`udevadm test`** | Имитация обработки события без реального применения | `udevadm test /sys/block/sda` |
| **`lsblk`** | Древовидный обзор блочных устройств (читает `sysfs`) | `lsblk -f -o NAME,SIZE,TYPE,FSTYPE,MODEL` |
| **`findmnt`** | Анализ монтирования (читает `/proc/self/mountinfo`) | `findmnt -D` |
| **`lspci`/`lsusb`/`lscpu`** | Инвентаризация через `sysfs` | `lspci -vvv` |
| **`iostat`** | Статистика I/O (агрегирует данные из `/sys/block/*/stat`) | `iostat -xz 1` |
| **`nvme`** | Управление NVMe устройствами (читает `sysfs` атрибуты) | `nvme list`, `nvme smart-log` |
| **`systemctl`** | Просмотр `.device` юнитов (интеграция systemd + sysfs) | `systemctl list-units --type=device` |
| **`tuned`** | Автоматическое применение профилей производительности | `tuned-adm profile latency-performance` |
| **`bpftrace`** | Трассировка событий sysfs (доступ к функциям ядра) | `bpftrace -e 'kprobe:kobject_uevent { printf("%s\n", comm); }'` |

## См. также

- [Udev: динамическое управление устройствами](../Core/udev.md) — основной потребитель данных из `sysfs`.
- [Виртуальная ФС /proc](./virtual_fs_proc.md) — интерфейс процессов и параметров ядра.
- [Виртуальные и псевдофайловые системы: Обзор](./virtual_filesystems.md) — архитектурное сравнение.
