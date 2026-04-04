# systemd User Services

## Определения

**`systemd --user`** — пользовательский режим `systemd`, позволяющий запускать и управлять службами от имени обычного пользователя без прав `root`. Экземпляр `systemd` создаётся при первом входе пользователя и завершается после окончания последней сессии (если не включён linger).

> Обзор типов юнитов: [systemd_units_overview.md](./systemd_units_overview.md). Структура unit-файлов: [systemd_unit_file_structure.md](./systemd_unit_file_structure.md). Зависимости: [systemd_dependencies.md](./systemd_dependencies.md).

## Базовые концепции

### Преимущества

| Характеристика | Описание |
| :--- | :--- |
| Безопасность | Службы работают с правами пользователя, а не root (принцип наименьших привилегий) |
| Изоляция | Пользовательские юниты изолированы от системных и от служб других пользователей |
| Без sudo | Управление без прав администратора |
| Автозапуск | Простая настройка запуска при входе в систему |

### Расположение юнит-файлов

| Путь | Назначение | Приоритет |
| :--- | :--- | :--- |
| `~/.config/systemd/user/` | Пользовательские юниты | Высший |
| `~/.local/share/systemd/user/` | Локально установленные (например, `pip install --user`) | Высокий |
| `/etc/systemd/user/` | Системные юниты для всех пользователей | Средний |
| `/usr/lib/systemd/user/` | Пакетные юниты | Низший |

### Управление пользовательскими службами

| Команда | Описание |
| :--- | :--- |
| `systemctl --user start <service>` | Запустить службу |
| `systemctl --user stop <service>` | Остановить службу |
| `systemctl --user restart <service>` | Перезапустить службу |
| `systemctl --user status <service>` | Проверить статус |
| `systemctl --user enable <service>` | Включить автозапуск при входе |
| `systemctl --user disable <service>` | Отключить автозапуск |
| `systemctl --user daemon-reload` | Перечитать конфигурацию |
| `systemctl --user list-units` | Показать все пользовательские юниты |
| `systemctl --user failed` | Показать упавшие службы |
| `journalctl --user -u <service>` | Логи пользовательской службы |

> **Важно:** Все команды выполняются от имени пользователя, без `sudo`.

### Переменные и спецификаторы

| Спецификатор | Значение | Пример |
| :--- | :--- | :--- |
| `%h` | Домашняя директория | `ExecStart=/usr/bin/python3 -m http.server 8000 --directory %h/public_html` |
| `%u` | Имя пользователя | `Description=Service for user %u` |
| `%U` | UID пользователя | `ExecStart=/usr/local/bin/app --uid %U` |
| `%s` | Shell пользователя | `ExecStart=%s -c 'echo hello'` |

## Практические сценарии

### Веб-сервер пользователя

1. Создайте файл `~/.config/systemd/user/my_web_server.service`:

    ```ini
    [Unit]
    Description=My Personal Python Web Server

    [Service]
    ExecStart=/usr/bin/python3 -m http.server 8000 --directory %h/public_html
    Restart=always

    [Install]
    WantedBy=default.target
    ```

2. Примените конфигурацию:

    ```bash
    systemctl --user daemon-reload
    systemctl --user enable --now my_web_server.service
    ```

### Синхронизация файлов (Syncthing)

```ini
# ~/.config/systemd/user/syncthing.service
[Unit]
Description=Syncthing - Open Source Continuous File Synchronization
Documentation=https://docs.syncthing.net/
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/syncthing serve --no-browser --logfile=default
Restart=on-failure
RestartSec=10
# Папка для конфигурации Syncthing
Environment=STNORESTART=yes

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now syncthing.service
```

### Пользовательский таймер для резервного копирования

**Сервис** (`~/.config/systemd/user/backup.service`):

```ini
[Unit]
Description=Personal Backup Script

[Service]
Type=oneshot
ExecStart=%h/scripts/backup.sh
RemainAfterExit=yes
```

**Таймер** (`~/.config/systemd/user/backup.timer`):

```ini
[Unit]
Description=Run backup daily

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now backup.timer
```

### Режим linger (работа без сессии)

По умолчанию пользовательский `systemd` завершается после выхода пользователя из системы. Для сервисов, которые должны работать постоянно (боты, веб-серверы):

```bash
# Включить linger для пользователя
sudo loginctl enable-linger <username>

# Отключить linger
sudo loginctl disable-linger <username>

# Проверить статус
loginctl show-user <username> | grep Linger
```

### Диагностика

```bash
# Проверить статус пользовательского systemd
systemctl --user status

# Показать все юниты пользователя
systemctl --user list-units --type=service

# Проверить, запущен ли user-экземпляр
pidof systemd

# Логи пользовательских юнитов (без --user flag логи будут пустыми)
journalctl --user -xe

# Перезапустить пользовательский systemd (перечитать все юниты)
systemctl --user daemon-reload
```

## Дополнительная информация

### Зависимости в пользовательских службах

Пользовательские юниты могут зависеть от системных, но не наоборот (по умолчанию). Для зависимости системного юнита от пользовательского используйте dbus-активацию или сокеты.

```ini
# Пользовательский юнит зависит от сети
[Unit]
After=network-online.target
Wants=network-online.target
```

Подробности о зависимостях: [systemd_dependencies.md](./systemd_dependencies.md).

### Проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| «Failed to connect to bus» | Пользовательский systemd не запущен | Войти в систему, или включить linger |
| Сервис останавливается после выхода | Linger не включён | `sudo loginctl enable-linger <username>` |
| Таймер не срабатывает | Пользователь не в системе | Включить linger, или использовать системный таймер |
| Permission denied на файл | Неправильный владелец | Проверить `User=` и права файла |
| `journalctl --user` пустой | Нет сессии | Войти в систему, или включить linger |

### Связанные файлы

Зависимости юнитов: [systemd_dependencies.md](./systemd_dependencies.md). Структура unit-файлов: [systemd_unit_file_structure.md](./systemd_unit_file_structure.md). Таймеры: [timers.md](./timers.md). Типы сервисов: [systemd_service_types.md](./systemd_service_types.md). Обзор юнитов: [systemd_units_overview.md](./systemd_units_overview.md).
