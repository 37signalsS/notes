# Пользовательские службы systemd

## Определения

* **`systemd --user`** — это режим работы менеджера `systemd`, позволяющий пользователям запускать и контролировать собственные юниты (службы, таймеры, сокеты) без прав администратора. Каждый активный пользователь получает отдельный экземпляр менеджера процессов.
* **Пользовательский менеджер** — процесс `systemd`, запущенный от имени пользователя. Он управляет жизненным циклом служб в рамках сессии или постоянно (при включенном linger).

## Основные концепции

### Жизненный цикл и режим linger

По умолчанию экземпляр `systemd --user` запускается при первом входе пользователя (логине) и завершается после закрытия последней сессии.
* **Режим Linger** — позволяет пользовательскому менеджеру запускаться при старте системы и продолжать работу после логаута. Это необходимо для работы фоновых ботов, серверов и планировщиков.

```bash
# Включить постоянную работу менеджера для пользователя
sudo loginctl enable-linger username

# Проверка статуса
loginctl show-user username | grep Linger
# → Linger=yes
```

### Управление переменными окружения

Пользовательские службы не наследуют переменные из `.bashrc` или `.profile`, так как запускаются напрямую менеджером `systemd`.

1. **`environment.d` (Рекомендуемый способ)**: Создайте файл `~/.config/environment.d/60-var.conf` для статических переменных.
2. **`import-environment`**: Используется для передачи динамических переменных (например, `$DISPLAY` или `$XDG_RUNTIME_DIR`) из текущей сессии в менеджер.
   ```bash
   systemctl --user import-environment DISPLAY XAUTHORITY
   ```
3. **`set-environment`**: Установка конкретных значений «на лету».
   ```bash
   systemctl --user set-environment MY_VAR=value
   ```

### XDG Autostart

Современные графические оболочки (KDE Plasma 6, GNOME) используют `systemd-xdg-autostart-generator` для преобразования `.desktop` файлов в нативные юниты systemd. Это позволяет управлять приложениями автозапуска через стандартный `systemctl --user`.

## Практические сценарии

### Настройка иерархии конфигурации

Менеджер ищет юниты в порядке приоритета:
1. `~/.config/systemd/user/` — локальные юниты пользователя (**рекомендуется**).
2. `~/.local/share/systemd/user/` — юниты от локально установленных пакетов.
3. `/etc/systemd/user/` — системные юниты для всех пользователей.
4. `/usr/lib/systemd/user/` — юниты, поставляемые дистрибутивом.

### Пример создания службы (Telegram-бот)

Создайте файл `~/.config/systemd/user/tg-bot.service`:

```ini
[Unit]
Description=Telegram Notification Bot
After=network-online.target

[Service]
ExecStart=%h/bin/bot-executable
Restart=on-failure
Environment=TOKEN_FILE=%h/.config/bot/token

[Install]
WantedBy=default.target
```

**Активация и запуск:**
```bash
systemctl --user daemon-reload
systemctl --user enable --now tg-bot.service

# Проверка статуса
systemctl --user status tg-bot.service
# → ● tg-bot.service - Telegram Notification Bot
# →    Active: active (running) since Mon 2024-06-10 12:00:00 UTC
```

### Использование спецификаторов

В пользовательских юнитах часто применяются переменные для переносимости:
* **`%h`** — Путь к домашней директории (`/home/user`).
* **`%u`** — Имя пользователя.
* **`%E`** — Путь к конфигурации (`~/.config`).
* **`%t`** — Путь к runtime-директории (`/run/user/1000`).

## Диагностика и управление

```bash
# Просмотр всех пользовательских служб
systemctl --user list-units --type=service

# Чтение логов конкретной службы
journalctl --user -u tg-bot.service -f

# Проверка ошибок в конфигурации
systemd-analyze --user verify ~/.config/systemd/user/tg-bot.service
```

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Failed to connect to bus** | Сессия не инициализирована корректно (часто при `su -`). | Используйте `machinectl shell user@host` или проверьте `$XDG_RUNTIME_DIR`. |
| **Служба не видит `$PATH`** | Переменные из shell не проброшены в systemd. | Используйте `environment.d` или полные пути в `ExecStart`. |
| **Permission denied (Socket)** | Попытка занять порт < 1024. | Используйте порты > 1024 или настройте `AmbientCapabilities=CAP_NET_BIND_SERVICE`. |

## Дополнительная информация

### См. также
* [Обзор юнитов systemd](./systemd_units_overview.md)
* [Структура unit-файлов](./systemd_unit_file_structure.md)
* [Управление сессиями (logind)](./logind_session_management.md)
* [Таймеры systemd](./timers.md)
* [Логирование (journald)](../../SystemAdministration/Logging/journald.md)
* [Зависимости юнитов](./systemd_dependencies.md)
