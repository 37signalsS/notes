# systemd Unit File Structure

## Определения

**Unit-файлы** — текстовые файлы в формате INI. Состоят из секций в квадратных скобках с директивами `Ключ=Значение`. Комментарии начинаются с `#`.

## Базовые концепции

**Основные секции:**

| Секция | Описание |
| :--- | :--- |
| `[Unit]` | Присутствует во всех юнитах. Описание, зависимости, порядок загрузки, условия запуска |
| `[Service]` | Только для `.service`. Параметры запуска, контроля и остановки процесса |
| `[Install]` | Используется `systemctl enable`. Указывает, в какие таргеты включать юнит |
| `[Socket]`, `[Timer]`, `[Mount]`, `[Path]` | Специфические секции для соответствующих типов юнитов |

### Секция [Unit]

Базовая секция, присутствующая во всех юнитах. Управляет метаданными, зависимостями и условиями запуска.

**Основные директивы:**

| Директива | Описание |
| :--- | :--- |
| `Description=` | Понятное имя юнита (отображается в `systemctl status`) |
| `Documentation=` | Список URI с документацией (через пробел) |
| `After=` / `Before=` | Порядок запуска (подробнее: [systemd_dependencies.md](./systemd_dependencies.md)) |
| `Requires=` / `Wants=` | Зависимости (подробнее: [systemd_dependencies.md](./systemd_dependencies.md)) |
| `Conflicts=` | Если указанный юнит запущен, текущий будет остановлен (и наоборот) |
| `ConditionPathExists=` | Проверка наличия файла перед запуском (пример условий `Condition...`) |
| `Assert...` | Проверки, при неудаче которых юнит считается неисправным |

### Секция [Service]

Определяет параметры запуска службы. Используется только в `.service` юнитах.

**Ключевые директивы:**

| Директива | Описание |
| :--- | :--- |
| `Type=` | Тип сервиса: `simple` (по умолчанию), `forking`, `oneshot`, `notify`, `dbus` |
| `User=` | Пользователь, от имени которого запускается процесс |
| `EnvironmentFile=` | Путь к файлу с переменными окружения (для секретов) |
| `ExecStart=` | Команда для запуска службы |
| `ExecStartPre=` | Команда перед запуском (подготовка) |
| `ExecStop=` | Команда для остановки службы |
| `Restart=` | Политика перезапуска: `no`, `on-success`, `on-failure`, `on-abnormal`, `always` |
| `RestartSec=` | Задержка перед перезапуском |
| `StandardOutput=` | Куда направлять stdout: `journal`, `syslog`, `file` |
| `StandardError=` | Куда направлять stderr |

#### Использование `EnvironmentFile` для управления секретами

Передача секретов через `EnvironmentFile` — безопасный способ для приложений, работающих как systemd-сервисы. Файл с секретами хранится на сервере с ограниченными правами и не коммитится в Git.

1. **Создать файл с секретами:**

    ```bash
    sudo mkdir -p /etc/myapp
    sudo nano /etc/myapp/secrets.env
    ```

    Содержимое файла (`DB_PASSWORD=...`):

    ```
    DB_PASSWORD=my_super_password
    API_TOKEN=abc123xyz
    ```

2. **Ограничить права доступа:**

    ```bash
    sudo chmod 600 /etc/myapp/secrets.env
    sudo chown root:root /etc/myapp/secrets.env
    ```

3. **Подключить в юнит-файле:**

    ```ini
    [Service]
    User=appuser
    EnvironmentFile=/etc/myapp/secrets.env
    ExecStart=/usr/bin/myapp
    ```

Приложение получит переменные окружения, как если бы они были переданы напрямую.

> Подробнее о типах сервисов: [systemd_service_types.md](./systemd_service_types.md)

### Секция [Install]

Управляет автозапуском юнита через `systemctl enable`.

| Директива | Описание |
| :--- | :--- |
| `WantedBy=` | Включить юнит в указанный таргет (создает symlink в `.wants/`) |
| `RequiredBy=` | Включить юнит как обязательную зависимость таргета |
| `Alias=` | Альтернативное имя для юнита |

### Специфические секции

#### [Socket] — активация по сокету

| Директива | Описание |
| :--- | :--- |
| `ListenStream=` | TCP-порт или Unix-сокет |
| `ListenDatagram=` | UDP-порт |
| `Accept=` | `yes` — отдельный инстанс сервиса на подключение, `no` — один сервис обрабатывает все |

> Socket-активация позволяет запускать сервис только при поступлении подключения. Пример: `sshd.socket`.

#### [Timer] — планирование задач

| Директива | Описание |
| :--- | :--- |
| `OnCalendar=` | Расписание (формат `*-*-* HH:MM:SS`) |
| `OnActiveSec=` | Запуск через время после активации таймера |
| `OnBootSec=` | Запуск через время после загрузки |
| `OnUnitActiveSec=` | Периодический запуск относительно последнего запуска юнита |
| `Persistent=` | `true` — выполнить пропущенный запуск после загрузки |
| `AccuracySec=` | Точность запуска (по умолчанию `1m`) |

> Подробнее о таймерах: [timers.md](./timers.md).

#### [Mount] / [Automount] — монтирование

| Директива | Описание |
| :--- | :--- |
| `Where=` | Точка монтирования |
| `What=` | Устройство или удалённый ресурс |
| `Type=` | Тип файловой системы |
| `Options=` | Опции монтирования |
| `TimeoutIdleSec=` | (Automount) Размонтирование после бездействия |

> Имя `.mount`-файла должно совпадать с путём монтирования (`/mnt/data` → `mnt-data.mount`). Подробнее: [systemd_practical_scenarios.md](./systemd_practical_scenarios.md).

## Практические сценарии

### Drop-in override-файлы (без изменения оригинала)

Для переопределения директив пакетного юнита без риска потери при обновлении:

```bash
# Создать drop-in override
sudo systemctl edit nginx.service
```

Создаст `/etc/systemd/system/nginx.service.d/override.conf`. Содержимое:

```ini
[Service]
# Переопределить CPUQuota, не трогая остальные настройки
CPUQuota=80%
MemoryMax=1G
```

**Ручное создание drop-in каталога:**

```bash
sudo mkdir -p /etc/systemd/system/my-service.service.d
sudo nano /etc/systemd/system/my-service.service.d/custom.conf
```

> Drop-in файлы **дополняют** основной unit-файл, а не заменяют его. Директивы с `=` переопределяют, директивы с `+=` добавляют.

### Полный override (замена всего юнита)

```bash
sudo systemctl edit --full nginx.service
```

Создаёт полную копию в `/etc/systemd/system/nginx.service`. Эта копия полностью заменяет пакетный юнит.

### Перечитка конфигурации

После создания или изменения юнит-файла:

```bash
sudo systemctl daemon-reload
```

### Проверка синтаксиса юнит-файлов (`systemd-analyze verify`)

Перед активацией нового или измененного юнита рекомендуется проверить его на наличие синтаксических ошибок.

```bash
# Проверить синтаксис файла юнита
systemd-analyze verify /etc/systemd/system/my-custom.service
```

Если в файле есть ошибки, команда выведет подробную информацию. В случае отсутствия ошибок команда завершится без вывода.

### Просмотр итогового (merged) юнита

```bash
# Показать объединённый unit-файл (оригинал + все drop-in)
systemctl cat nginx.service

# Показать все директивы юнита (включая значения по умолчанию)
systemctl show nginx.service
```

## Дополнительная информация

### Приоритет файлов и переопределение

| Расположение | Приоритет | Назначение |
| :--- | :--- | :--- |
| `/etc/systemd/system/` | Высший | Пользовательские override-файлы |
| `/run/systemd/system/` | Средний | Динамические юниты (runtime) |
| `/usr/lib/systemd/system/` | Низший | Пакетные юниты (не изменять) |

> **Важно:** Никогда не изменяйте файлы в `/usr/lib/systemd/system/`. Для переопределения используйте `systemctl edit` или создавайте drop-in файлы в `/etc/systemd/system/`.

Drop-in файлы в `*.d/*.conf` обрабатываются в лексикографическом порядке.

### Связанные файлы

Зависимости юнитов: [systemd_dependencies.md](./systemd_dependencies.md). Типы сервисов: [systemd_service_types.md](./systemd_service_types.md). Таймеры: [timers.md](./timers.md). Обзор юнитов: [systemd_units_overview.md](./systemd_units_overview.md). Практические сценарии: [systemd_practical_scenarios.md](./systemd_practical_scenarios.md).
