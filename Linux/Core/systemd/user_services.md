# Пользовательские службы systemd (systemd User Services)

## Определения

**`systemd --user`** — это режим работы менеджера системы и служб `systemd`, позволяющий запускать и управлять юнитами (units) от имени обычного пользователя без привилегий `root`.

Экземпляр пользовательского `systemd` создаётся автоматически при первом входе пользователя в систему и завершается после закрытия последней сессии, если не активирован режим **linger**.

> Обзор типов юнитов: [systemd_units_overview.md](./systemd_units_overview.md). Структура unit-файлов: [systemd_unit_file_structure.md](./systemd_unit_file_structure.md). Управление зависимостями: [systemd_dependencies.md](./systemd_dependencies.md).

## Основные концепции

### Преимущества использования

| Характеристика | Описание |
| :--- | :--- |
| **Безопасность** | Службы работают с правами пользователя, соблюдая принцип наименьших привилегий. |
| **Изоляция** | Пользовательские юниты полностью отделены от системных и от служб других пользователей. |
| **Автономность** | Управление не требует прав администратора или использования `sudo`. |
| **Удобство** | Легкая настройка автозапуска приложений при входе пользователя в ОС (Операционная Система). |

### Расположение конфигурационных файлов

Менеджер ищет юнит-файлы в следующих директориях (в порядке убывания приоритета):

| Путь | Назначение |
| :--- | :--- |
| `~/.config/systemd/user/` | Основное место для пользовательских конфигураций. |
| `~/.local/share/systemd/user/` | Юниты, установленные локальными менеджерами пакетов. |
| `/etc/systemd/user/` | Системные настройки пользовательских служб для всех пользователей. |
| `/usr/lib/systemd/user/` | Стандартные юниты, поставляемые с дистрибутивом. |

### Управление через systemctl

Все команды выполняются с флагом `--user` и не требуют `sudo`.

```bash
# Перечитать конфигурацию после изменения файлов
systemctl --user daemon-reload

# Запустить службу
systemctl --user start my_app.service

# Включить автозапуск при входе пользователя
systemctl --user enable my_app.service
# → Created symlink /home/user/.config/systemd/user/default.target.wants/my_app.service ...

# Проверить текущий статус
systemctl --user status my_app.service
# → ● my_app.service - My App Description
# →    Active: active (running) since Sat 2024-06-08 10:00:00 MSK; 1h ago

# Показать список всех загруженных юнитов пользователя
systemctl --user list-units --type=service
# → UNIT             LOAD   ACTIVE SUB     DESCRIPTION
# → my_app.service   loaded active running My App Description
```

### Спецификаторы путей и переменных

В юнит-файлах можно использовать специальные символы для динамического определения путей:

| Спецификатор | Описание | Пример значения |
| :--- | :--- | :--- |
| `%h` | Домашняя директория пользователя | `/home/username` |
| `%u` | Имя пользователя | `username` |
| `%U` | UID (User ID) пользователя | `1000` |
| `%s` | Командная оболочка (shell) пользователя | `/bin/bash` |

## Практические сценарии

### Запуск персонального веб-сервера

Создайте файл `~/.config/systemd/user/web_server.service`:

```ini
[Unit]
Description=Personal Python Web Server

[Service]
ExecStart=/usr/bin/python3 -m http.server 8000 --directory %h/public_html
Restart=always

[Install]
WantedBy=default.target
```

Активация:

```bash
systemctl --user daemon-reload
systemctl --user enable --now web_server.service
```

### Режим linger: работа служб без активной сессии

По умолчанию службы пользователя завершаются при логауте. Для работы фоновых задач (ботов, серверов) необходимо включить режим `linger`.

```bash
# Включить постоянную работу пользовательского экземпляра systemd
sudo loginctl enable-linger username

# Проверить текущий статус параметра Linger
loginctl show-user username | grep Linger
# → Linger=yes
```

### Просмотр журналов (logs)

```bash
# Просмотр логов конкретной службы пользователя
journalctl --user -u web_server.service -f
# → Jun 08 11:00:00 host python3[1234]: Serving HTTP on 0.0.0.0 port 8000 ...
```

## Дополнительная информация

### Взаимодействие с системными юнитами

Пользовательские службы могут зависеть от системных (например, требовать наличия сети), но системные службы не могут напрямую зависеть от пользовательских.

```ini
[Unit]
Description=Service with network dependency
After=network-online.target
Wants=network-online.target
```

### Типичные проблемы

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Failed to connect to bus** | Экземпляр systemd не запущен. | Убедитесь, что вы вошли в систему или включен linger. |
| **Служба «умирает» при выходе** | Не включен режим linger. | Выполните `sudo loginctl enable-linger`. |
| **Permission denied** | Юнит пытается писать в защищенные `/var/log` или `/etc`. | Используйте пути в `%h` или `/tmp`. |

### См. также

* [Юниты, таргеты и зависимости systemd](./systemd_units_overview.md)
* [Таймеры systemd (Timers)](./timers.md)
* [Journald: централизованное логирование](../../SystemAdministration/Logging/journald.md)
