# Пользовательские службы systemd: Режим --user

## Определения

* **`systemd --user`** — системный механизм, позволяющий непривилегированным пользователям управлять собственным экземпляром менеджера процессов. Это позволяет запускать службы, таймеры и сокеты, которые не требуют прав root и изолированы в рамках пользовательского контекста.
* **Пользовательская шина D-Bus (Session Bus)** — канал межпроцессного взаимодействия, через который `systemctl --user` общается с пользовательским экземпляром systemd.
* **Linger (Задержка)** — состояние пользователя в `logind`, при котором его экземпляр `systemd --user` запускается при старте ОС и не завершается после закрытия всех сессий.

## Основные концепции

### Жизненный цикл и режим Linger

По умолчанию экземпляр `systemd --user` создается при первом логине пользователя и уничтожается при выходе из последней сессии. Для серверных задач (боты, мониторинг, безрутовые контейнеры) необходимо включить режим **Linger**.

```bash
# Включение постоянной работы менеджера для текущего пользователя
sudo loginctl enable-linger $USER

# Проверка: статус Linger в выводе loginctl
loginctl show-user $USER --property=Linger
# → Linger=yes
```

### Переменные окружения

Пользовательские юниты **не наследуют** переменные из файлов `.bashrc`, `.zshrc` или `.profile`.

1.  **`environment.d` (Рекомендуется):** Создайте файл `~/.config/environment.d/99-custom.conf`. Формат: `KEY=VALUE`. Эти переменные будут доступны всем пользовательским службам.
2.  **`systemctl --user import-environment`:** Передает переменные из текущей оболочки в менеджер (полезно для `$DISPLAY`, `$XDG_RUNTIME_DIR`).
3.  **`DefaultEnvironment=`:** Можно задать в `~/.config/systemd/user.conf` для глобального применения.

### Ограничение ресурсов (Cgroups)

Все пользовательские службы работают внутри системного слайса **`user-$UID.slice`**. 
* Вы можете накладывать лимиты на все службы пользователя сразу через системный `systemctl set-property user-$UID.slice MemoryMax=2G`.
* Индивидуальные лимиты прописываются в секции `[Service]` пользовательского юнита так же, как в системных.

## Практические сценарии

### 1. Иерархия и пути конфигурации

Пользовательский менеджер ищет юниты в следующем порядке (по убыванию приоритета):
1.  **`$XDG_CONFIG_HOME/systemd/user/`** (обычно `~/.config/systemd/user/`) — основные пользовательские конфиги.
2.  **`$XDG_DATA_HOME/systemd/user/`** (обычно `~/.local/share/systemd/user/`) — юниты от установленного пользователем ПО.
3.  **`/etc/systemd/user/`** — общие юниты для всех пользователей системы (управляются root).

### 2. Пример службы: Фоновый Python-скрипт

Создайте файл `~/.config/systemd/user/my-script.service`:
```ini
[Unit]
Description=My Background Python Script
After=network-online.target

[Service]
Type=simple
# %h раскрывается в путь к домашней директории
ExecStart=/usr/bin/python3 %h/scripts/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

**Активация:**
```bash
systemctl --user daemon-reload
systemctl --user enable --now my-script.service
```

### 3. Активация через сокеты (Socket Activation)

Позволяет запускать службу только при поступлении входящего соединения на порт (например, для личного HTTP-прокси).
```ini
# ~/.config/systemd/user/proxy.socket
[Socket]
ListenStream=8080

[Install]
WantedBy=sockets.target
```

## Диагностика и управление

### Базовые команды
```bash
# Просмотр всех юнитов пользователя
systemctl --user list-units

# Чтение журналов (journald фильтрует по UID автоматически)
journalctl --user -u my-script.service -f

# Проверка конфигурации на ошибки
systemd-analyze --user verify ~/.config/systemd/user/my-script.service
```

### Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Failed to connect to bus** | Ошибка инициализации `$XDG_RUNTIME_DIR` или D-Bus при использовании `su` или `sudo`. | Используйте `machinectl shell $USER@.host` или явно задайте `export XDG_RUNTIME_DIR=/run/user/$UID`. |
| **Error: Permission denied (Socket)** | Попытка занять порт < 1024. | Непривилегированные пользователи не могут слушать системные порты. Используйте порты > 1024. |
| **Служба «забывает» переменные** | Ожидание переменных из `.bashrc`. | Перенесите переменные в `~/.config/environment.d/*.conf`. |

## Дополнительная информация

### См. также
* [Обзор юнитов systemd](./systemd_units_overview.md) — базовые типы и логика.
* [Управление сессиями (logind)](./logind_session_management.md) — детали работы `enable-linger`.
* [Таймеры systemd](./timers.md) — планирование задач в контексте пользователя.
* [Журналирование (journald)](../../SystemAdministration/Logging/journald.md) — работа с логами без прав root.
* [Безрутовый Podman](../../Podman/podman_rootless.md) — использование пользовательских служб для контейнеров.
