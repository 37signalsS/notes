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

# Валидация и тестирование правил

Перед применением правил в production проверяйте их на тестовом устройстве без физического переподключения.

### 1. Получение свойств устройства

```bash
# Все свойства, доступные udev для блочного устройства
udevadm info -q property -n /dev/sdb1 | sort

# Проверка конкретных атрибутов, используемых в правиле
udevadm info -q property -n /dev/sdb1 | grep -E 'ID_FS_UUID|ID_FS_TYPE|ID_SERIAL_SHORT'
# → ID_FS_UUID=a1b2c3d4-e5f6-7890-abcd-ef1234567890
# → ID_FS_TYPE=ext4
```

### 2. Тестирование правила без события

```bash
# Получение sysfs-пути устройства
udevadm info -q path -n /dev/sdb1
# → /devices/pci0000:00/.../block/sdb

# Тестирование правила на конкретном пути
sudo udevadm test --action=add /sys/block/sdb

# Проверка: вывод должен содержать строку с вашим правилом
# Если правило не найдено — проверьте имя файла (должно заканчиваться на .rules)
# и приоритет (двузначное число в начале имени)
```

### 3. Принудительный вызов события

```bash
# Перезагрузка правил
sudo udevadm control --reload-rules

# Принудительный вызов события add для конкретного устройства
sudo udevadm trigger --action=add /dev/sdb1

# Ожидание завершения обработки всеми правилами
sudo udevadm settle --timeout=30
```

# Проверка mount-юнита после события

### 1. Проверка статуса mount-юнита

```bash
# Статус конкретного юнита
systemctl status mnt-backup.mount
# → Active: active (mounted) since ...

# Список всех активных mount-юнитов
systemctl list-units --type=mount

# Поиск юнита, связанного с устройством
systemctl list-units --type=mount | grep sdb
```

### 2. Проверка точки монтирования

```bash
# Точка монтирования и источник
findmnt -T /mnt/backup
# → TARGET SOURCE    FSTYPE OPTIONS
# → /mnt/backup /dev/sdb1 ext4  ro,noatime,nodev,nosuid

# Проверка содержимого
ls -la /mnt/backup
```

### 3. Проверка логов systemd

```bash
# Логи конкретного mount-юнита
journalctl -u mnt-backup.mount -f

# Логи udev
journalctl -u systemd-udevd -f

# Все ошибки systemd за последний час
journalctl -u systemd-udevd --since "1 hour ago" -p err
```

# Обработка краевых случаев и идемпотентность

### 1. Устройство уже смонтировано

Если устройство подключено повторно, `systemd-mount` создаст новый временный юнит с именем `mnt-backup.mount`. Если точка монтирования занята, монтирование завершится ошибкой.

**Решение:** Используйте готовые статические `.mount` юниты с `ENV{SYSTEMD_WANTS}` вместо `systemd-mount` для детерминированного поведения.

### 2. Устройство отключено без размонтирования

Если устройство физически отключено без `umount`, systemd поместит юнит в failed состояние. При повторном подключении udev сработает заново, но mount-юнит может не активироваться из-за stale-состояния.

**Решение:** Добавьте в `.mount` юнит директиву:

```ini
[Mount]
What=/dev/disk/by-uuid/a1b2c3d4
Where=/mnt/data
Type=ext4
Options=defaults,nofail

[Install]
WantedBy=multi-user.target
```

`nofail` позволяет системе продолжить загрузку даже если монтирование не удалось.

### 3. Отсутствие точки монтирования

Если директория `/mnt/backup` не существует, `systemd-mount` завершится ошибкой.

**Решение:** Создавайте точку монтирования заранее или используйте скрипт-обработчик:

```bash
#!/bin/bash
MOUNT_POINT="/mnt/backup"
DEVICE="/dev/$1"

# Создание точки монтирования, если она не существует
mkdir -p "$MOUNT_POINT"

# Монтирование
/usr/bin/systemd-mount --no-block --collect --options=noatime,nodev,nosuid "$DEVICE" "$MOUNT_POINT"
```

### 4. Повторное подключение того же устройства

При быстром переподключении того же устройства udev может сгенерировать несколько событий `add`. Используйте `TAG+="systemd"` для гарантии последовательной обработки:

```ini
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_UUID}=="a1b2c3d4...", TAG+="systemd", ENV{SYSTEMD_WANTS}+="mnt-data.mount"
```

# Безопасность и права

### 1. Файлы ключей LUKS

Файл с ключом дешифрования должен иметь строгие права:

```bash
# Создание ключевого файла с правами 600
sudo install -m 600 /dev/null /etc/keys/backup_key.key
sudo dd if=/dev/urandom of=/etc/keys/backup_key.key bs=4096 count=1

# Проверка прав
ls -la /etc/keys/backup_key.key
# → -rw------- 1 root root 4096 ... /etc/keys/backup_key.key
```

### 2. Запуск скриптов от non-root

Для операций, не требующих полных привилегий root, используйте `sudo` внутри скрипта или systemd-сервис с `User=`:

```ini
# /etc/systemd/system/luks-mount@.service
[Unit]
Description=LUKS mount handler for %i
After=dev-%i.device
Requires=dev-%i.device

[Service]
Type=oneshot
User=backup
Group=disk
ExecStart=/usr/local/bin/luks-handler.sh %i
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 3. Ограничение scope правил

Используйте максимально конкретные матчеры (UUID, тип ФС) вместо широких паттернов:

```ini
# Плохо: сработает для любого блочного устройства
ACTION=="add", SUBSYSTEM=="block", RUN+="/usr/bin/systemd-mount ..."

# Хорошо: только для конкретной ФС и UUID
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_TYPE}=="ext4", ENV{ID_FS_UUID}=="a1b2c3d4...", \
    RUN+="/usr/bin/systemd-mount ..."
```

# Очистка и удаление правил

### 1. Отключение автоматического монтирования

```bash
# Удаление правила
sudo rm /etc/udev/rules.d/99-usb-mount.rules

# Перезагрузка правил
sudo udevadm control --reload-rules

# Отключение mount-юнита
sudo systemctl disable mnt-backup.mount
sudo systemctl stop mnt-backup.mount
```

### 2. Очистка остановленных mount-юнитов

```bash
# Список остановленных mount-юнитов
systemctl list-units --type=mount --state=dead

# Удаление остановленного временного юнита
sudo systemctl reset-failed mnt-backup.mount
```

### 3. Удаление старых symlink-ов

Если точка монтирования была создана как symlink, удалите её:

```bash
sudo rm /mnt/backup
```

# Swap устройства через udev

Для автоматического включения swap-раздела при подключении:

```ini
# /etc/udev/rules.d/99-swap-auto.rules
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_TYPE}=="swap", \
    RUN+="/usr/sbin/swapon /dev/%k"
```

**Важно:** Для swap-устройств, которые должны быть доступны при загрузке, используйте `/etc/fstab` с опцией `_netdev` (если требуется) или создайте статический `.swap` юнит:

```ini
# /etc/systemd/system/dev-disk-by\x2duuid-swap-uuid.swap
[Unit]
Description=Swap partition

[Swap]
What=/dev/disk/by-uuid/swap-uuid

[Install]
WantedBy=multi-user.target
```

Активация через udev:

```ini
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_UUID}=="swap-uuid", \
    ENV{SYSTEMD_WANTS}+="dev-disk-by\\x2duuid-swap-uuid.swap"
```

# Автоматическое создание точек монтирования

Если точка монтирования может отсутствовать, создавайте её в рамках скрипта-обработчика:

```bash
#!/bin/bash
DEVICE="/dev/$1"
UUID="$2"
MOUNT_POINT="/mnt/media/$(basename "$UUID")"

# Создание точки монтирования с безопасными правами
mkdir -p "$MOUNT_POINT"
chmod 755 "$MOUNT_POINT"

# Монтирование с безопасными опциями
/usr/bin/systemd-mount --no-block --collect \
    --options=noatime,nodev,nosuid,noexec \
    "$DEVICE" "$MOUNT_POINT"
```

**Примечание:** Опция `noexec` запрещает выполнение бинарных файлов с файловой системы, что повышает безопасность для съемных носителей.

# Мониторинг и алертинг в production

### 1. Мониторинг статуса mount-юнитов

```bash
# Проверка всех mount-юнитов на failed-состояние
systemctl list-units --type=mount --state=failed

# Мониторинг появления новых устройств
udevadm monitor --udev --subsystem-match=block --property | grep -E 'ACTION=add|ID_FS_UUID'
```

### 2. Логирование и алерты

Настройте логирование для отслеживания событий монтирования:

```bash
# Поиск ошибок монтирования за последние 24 часа
journalctl -u systemd-udevd --since "24 hours ago" | grep -i 'mount.*fail\|systemd-mount.*error'

# Поиск неудачных mount-юнитов
journalctl -u systemd-udevd --since "24 hours ago" | grep -i 'mnt-.*mount.*failed'
```

### 3. Интеграция с мониторингом

Для интеграции с Prometheus node_exporter или аналогичными инструментами:

```bash
# Проверка активности mount-юнитов через systemctl
systemctl is-active mnt-backup.mount
# → active / inactive / failed

# Получение списка смонтированных устройств, управляемых udev
findmnt -t ext4,xfs,vfat -o TARGET,SOURCE,FSTYPE,OPTIONS | grep -v '^#'
```

# Практические рекомендации для SRE

### 1. Документирование правил

Каждое правило udev должно содержать комментарий с описанием назначения, ответственного лица и даты создания:

```ini
# /etc/udev/rules.d/99-usb-backup.rules
# Назначение: Автоматическое монтирование USB-диска для резервного копирования
# Ответственный: backup-team
# Дата: 2024-01-15
# Ссылка: RUNBOOK-1234
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_UUID}=="a1b2c3d4-e5f6-7890-abcd-ef1234567890", \
    TAG+="systemd", ENV{ID_FS_TYPE}=="ext4", ENV{SYSTEMD_WANTS}+="mnt-backup.mount"
```

### 2. Тестирование перед production

1.  Протестируйте правило на тестовом устройстве.
2.  Проверьте поведение при быстром переподключении (replug storm).
3.  Проверьте поведение при отключении устройства без размонтирования.
4.  Проверьте восстановление после перезагрузки.

### 3. Идемпотентность

Убедитесь, что повторное применение правила не приводит к ошибкам:

- Используйте статические `.mount` юниты вместо временных `systemd-mount` для критичных устройств.
- Проверяйте статус юнита перед выполнением действий в скриптах.
- Используйте `nofail` в опциях монтирования для не критичных устройств.

### 4. Управление конфигурацией

Храните правила udev в системе управления конфигурацией (Ansible, Puppet, Chef):

```yaml
# Пример Ansible-задачи
- name: Deploy udev rule for USB backup mount
  copy:
    dest: /etc/udev/rules.d/99-usb-backup.rules
    content: |
      ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_UUID}=="a1b2c3d4-e5f6-7890-abcd-ef1234567890", \
          TAG+="systemd", ENV{ID_FS_TYPE}=="ext4", ENV{SYSTEMD_WANTS}+="mnt-backup.mount"
    mode: '0644'
  notify: Reload udev rules
```

### 5. Аудит

Периодически проверяйте актуальность правил:

```bash
# Список всех кастомных правил
ls -la /etc/udev/rules.d/*.rules

# Проверка времени последнего изменения
stat /etc/udev/rules.d/99-usb-mount.rules
```

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
