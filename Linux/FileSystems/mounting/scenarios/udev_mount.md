# Определения

**Udev** — подсистема Linux для динамического управления устройствами в директории `/dev`. Она обрабатывает события ядра (uevents) и позволяет выполнять административные действия (скрипты, команды) при подключении или удалении оборудования.

Теоретические основы и методы инспекции атрибутов описаны в основном материале: [Udev — динамическое управление устройствами](../../../Core/udev.md).

# Основные концепции

Использование udev для монтирования основано на обработке событий `add` (подключение) и `remove` (отключение).

> **Важное архитектурное предупреждение:** В современных системах с `systemd` прямое выполнение `/bin/mount` через параметр `RUN` в правилах udev считается антипаттерном. `udev` завершает процессы в `RUN` по жесткому таймауту, что может привести к повреждению файловой системы.

**Рекомендуемые современные подходы:**
1.  **`systemd-mount`**: Специализированная утилита, которая передает задачу монтирования демону systemd, обеспечивая корректное управление жизненным циклом.
2.  **Systemd-юниты**: Активация готового `.mount` или `.service` юнита через переменную окружения `ENV{SYSTEMD_WANTS}`.

# Практические сценарии

## Сценарий 1: Монтирование USB-диска по UUID

Этот метод надежнее, чем использование серийного номера родительского устройства, так как привязан непосредственно к файловой системе.

### 1. Сбор атрибутов файловой системы
Подключите диск и найдите его UUID:
```bash
udevadm info -q property -n /dev/sdb1 | grep -E 'ID_FS_UUID|ID_FS_TYPE'
# → ID_FS_UUID=a1b2c3d4-e5f6-7890-abcd-ef1234567890
# → ID_FS_TYPE=ext4
```

### 2. Создание правила udev
Создайте файл `/etc/udev/rules.d/99-usb-mount.rules`:
```ini
# /etc/udev/rules.d/99-usb-mount.rules
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_UUID}=="a1b2c3d4-e5f6-7890-abcd-ef1234567890", \
    RUN+="/usr/bin/systemd-mount --no-block --collect --options=noatime,nodev,nosuid /dev/%k /mnt/backup"
```
*   `--no-block`: Не ждать завершения операции монтирования.
*   `--collect`: Автоматически очищать временный юнит после размонтирования.
*   `/dev/%k`: Имя устройства в системе (например, `sdb1`).

## Сценарий 2: Автоматическая дешифрация и монтирование LUKS

Если на внешнем диске используется шифрование, udev может инициировать процесс открытия тома.

### 1. Подготовка скрипта-обработчика
Создайте `/usr/local/bin/luks-handler.sh`:
```bash
#!/bin/bash
DEVICE="/dev/$1"
MAPPER_NAME="secure_data"
KEY_FILE="/etc/keys/backup_key.key"

if [ -f "$KEY_FILE" ]; then
    /usr/sbin/cryptsetup luksOpen "$DEVICE" "$MAPPER_NAME" --key-file "$KEY_FILE"
    /usr/bin/systemd-mount "/dev/mapper/$MAPPER_NAME" /mnt/secure
fi
```

### 2. Правило udev для LUKS
Используйте `systemd-run`, чтобы скрипт выполнялся вне контекста таймаутов udev:
```ini
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_TYPE}=="crypto_LUKS", ENV{ID_FS_UUID}=="xxxx-yyyy", \
    RUN+="/usr/bin/systemd-run --unit=luks-mount@%k /usr/local/bin/luks-handler.sh %k"
```

## Сценарий 3: Активация нативного Mount Unit

Наиболее «чистый» способ в архитектуре systemd.

### 1. Создание Mount Unit
Создайте файл `/etc/systemd/system/mnt-data.mount`:
```ini
[Unit]
Description=External Data Disk

[Mount]
What=/dev/disk/by-uuid/a1b2c3d4...
Where=/mnt/data
Type=ext4
Options=defaults,nofail

[Install]
WantedBy=multi-user.target
```

### 2. Правило udev для активации
```ini
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_UUID}=="a1b2c3d4...", ENV{SYSTEMD_WANTS}+="mnt-data.mount"
```
*При подключении диска udev добавит юнит в очередь запуска systemd.*

# Управление и диагностика

### Применение конфигурации
После редактирования правил:
```bash
sudo udevadm control --reload-rules
# Проверка правил на уже подключенном устройстве
sudo udevadm trigger --action=add /dev/sdb1
```

### Мониторинг событий
```bash
# Просмотр атрибутов, доступных udev в реальном времени
udevadm monitor --udev --property
# → ID_FS_UUID=...
# → ID_MODEL=...
```

### Отладка выполнения
Если монтирование не произошло:
1.  Проверьте статус временного юнита: `systemctl status mnt-backup.mount`.
2.  Просмотрите логи: `journalctl -u systemd-udevd -f`.

# Дополнительная информация

*   **[Udev — глубокая теория](../../../Core/udev.md)** — атрибуты, ключи и приоритеты.
*   **[Systemd mount units](./systemd_mount.md)** — правила именования и структура юнитов.
*   **[Команды монтирования](../commands.md)** — использование `findmnt` для анализа.
*   **[Шифрование LUKS](../../storage_overview.md#шифрование-диска-с-помощью-luks)** — работа с `cryptsetup`.
