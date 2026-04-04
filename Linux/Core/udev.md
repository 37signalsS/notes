# Udev

## Определения

**Udev (userside /dev)** — подсистема ядра Linux и демон для динамического управления файлами устройств в `/dev`. Автоматически создаёт и удаляет ноды устройств при подключении/отключении.

**Основные функции:**

| Функция | Описание |
| :--- | :--- |
| **Создание/удаление** | Динамическое управление нодами устройств в `/dev` |
| **Постоянные имена** | Присвоение имён на основе атрибутов (серийный номер, UUID) |
| **Права доступа** | Изменение владельца и прав для файлов устройств |
| **События** | Запуск скриптов/программ при событиях (add, remove, change) |

## Основные концепции

### Правила udev

**Расположение правил:**

- **Системные:** `/lib/udev/rules.d/` (из пакетов)
- **Пользовательские:** `/etc/udev/rules.d/` (приоритет)

**Именование файлов:** `<номер>-<имя>.rules` (например, `10-backup-disk.rules`)

**Синтаксис правила:**

```
<условие1>, <условие2>, <действие1>, <действие2>
```

**Ключи совпадения (match keys):**

| Ключ | Описание | Пример |
| :--- | :--- | :--- |
| `SUBSYSTEM` | Подсистема устройства | `SUBSYSTEM=="block"` |
| `KERNEL` | Имя устройства в ядре | `KERNEL=="sdb"` |
| `ATTR{файл}` | Атрибут из sysfs | `ATTR{serial}=="12345"` |
| `ENV{переменная}` | Переменная окружения | `ENV{ID_FS_TYPE}=="ext4"` |
| `ACTION` | Действие (add, remove, change) | `ACTION=="add"` |

**Ключи действий (assignment keys):**

| Ключ | Описание | Пример |
| :--- | :--- | :--- |
| `NAME` | Имя устройства | `NAME="backup"` |
| `SYMLINK` | Символическая ссылка | `SYMLINK+="backup"` |
| `OWNER` | Владелец | `OWNER="root"` |
| `GROUP` | Группа | `GROUP="disk"` |
| `MODE` | Права доступа | `MODE="0660"` |
| `RUN` | Команда для выполнения | `RUN+="/usr/local/bin/mount.sh"` |
| `TAG` | Тег для systemd | `TAG+="uaccess"` |

### Управление правилами

```bash
# Перезагрузить правила
sudo udevadm control --reload-rules

# Применить к существующим устройствам
sudo udevadm trigger

# Проверить событие устройства
udevadm monitor --udev --property

# Получить информацию об устройстве
udevadm info -a -p /sys/class/block/sdb

# Тестирование правила
udevadm test /sys/class/block/sdb
```

## Практические сценарии

### 1. Постоянная ссылка на диск

Создание символической ссылки `/dev/backup` для диска `/dev/sdb`:

```
# /etc/udev/rules.d/10-backup-disk.rules

SUBSYSTEM=="block", KERNEL=="sdb", SYMLINK+="backup", GROUP="plugdev", TAG+="uaccess"
```

| Ключ | Описание |
| :--- | :--- |
| `SUBSYSTEM=="block"` | Только блочные устройства |
| `KERNEL=="sdb"` | Устройство называется sdb |
| `SYMLINK+="backup"` | Создать ссылку `/dev/backup` |
| `GROUP="plugdev"` | Группа-владелец |
| `TAG+="uaccess"` | Доступ через systemd-logind |

**Применение:**

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
ls -l /dev/backup  # Проверка
```

### 2. Постоянное имя для USB-диска по серийному номеру

```bash
# Узнать серийный номер
udevadm info -a -n /dev/sdb1 | grep serial

# Создать правило (заменить 1234567890 на реальный серийник)
# /etc/udev/rules.d/10-usb-backup.rules
SUBSYSTEM=="block", ENV{ID_SERIAL_SHORT}=="1234567890", SYMLINK+="usb-backup"
```

### 3. Автоматическое монтирование при подключении

```bash
# /etc/udev/rules.d/99-usb-mount.rules
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_TYPE}=="ext4", RUN+="/usr/local/bin/auto-mount.sh %k"
```

```bash
#!/bin/bash
# /usr/local/bin/auto-mount.sh
DEVICE="/dev/$1"
mkdir -p /mnt/auto-$1
mount $DEVICE /mnt/auto-$1
```

> **Предупреждение:** Для простого автоматического монтирования предпочтительнее использовать [`/etc/fstab`](../FileSystems/mounting/fstab.md) или [systemd mount units](../FileSystems/mounting/scenarios/systemd_mount.md).

### 4. Изменение планировщика I/O для диска

```bash
# /etc/udev/rules.d/60-scheduler.rules
ACTION=="add|change", KERNEL=="sda", ATTR{queue/scheduler}="mq-deadline"
ACTION=="add|change", KERNEL=="nvme*", ATTR{queue/scheduler}="none"
```

Подробно: [I/O Schedulers](./kernel/io_schedulers.md#постоянное-изменение-планировщика-с-помощью-udev).

### 5. Права доступа для устройства

```bash
# /etc/udev/rules.d/50-permissions.rules
# Дать пользователю доступ к Arduino
SUBSYSTEM=="tty", ATTRS{idVendor}=="2341", MODE="0666"

# Доступ к веб-камере
SUBSYSTEM=="video4linux", GROUP="video", MODE="0660"
```

### 6. Отладка и диагностика

```bash
# Мониторинг событий в реальном времени
udevadm monitor --udev --property

# Информация об устройстве со всеми атрибутами
udevadm info -a -p /sys/class/block/sda

# Тестирование правил без применения
udevadm test /sys/class/block/sda

# Проверка версии udev
udevadm --version
```

## Дополнительная информация

### Связанные темы

- **[/dev FS](../FileSystems/virtual_fs_dev.md)** — виртуальная файловая система устройств
- **[Mounting](../FileSystems/mounting/index.md)** — монтирование файловых систем
- **[Systemd](./systemd/overview.md)** — интеграция с systemd
- **[I/O Schedulers](./kernel/io_schedulers.md)** — планировщики ввода-вывода

### Troubleshooting

| Проблема | Решение |
| :--- | :--- |
| Правило не применяется | Проверить синтаксис, `udevadm test`, порядок имён файлов |
| События не генерируются | Проверить `udevadm monitor`, права доступа к устройству |
| Конфликт правил | Правила выполняются по алфавиту, проверить приоритет |
| RUN не выполняется | Проверить путь к скрипту, права выполнения, лог `journalctl -u systemd-udevd` |
