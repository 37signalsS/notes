# systemd Service Types

## Определения

**`Type=`** — директива в секции `[Service]`, определяющая, как `systemd` отслеживает состояние и готовность сервиса. Неправильный выбор типа приводит к ошибкам запуска, зависанию таймаутов или некорректному управлению процессом.

## Базовые концепции

### Полная таблица типов

| Тип | Главный процесс | Когда готов | Когда использовать |
| :--- | :--- | :--- | :--- |
| `simple` | `ExecStart` | Сразу после запуска | Приложения, не требующие инициализации (большинство современных) |
| `exec` | `ExecStart` | После exec() | Как `simple`, но после exec() (проверка бинарника до запуска) |
| `forking` | Дочерний процесс | После выхода родителя | Классические демоны (sshd, nginx, Postfix) |
| `oneshot` | `ExecStart` | После завершения | Скрипты инициализации, миграции, настройка (часто с `RemainAfterExit=yes`) |
| `notify` | `ExecStart` | После `sd_notify()` | Приложения с явной сигнализацией готовности (PostgreSQL, etcd, Podman) |
| `dbus` | `ExecStart` | После регистрации на D-Bus | Сервисы, использующие D-Bus (NetworkManager, bluetoothd) |
| `idle` | `ExecStart` | После запуска, с задержкой | Как `simple`, но отложенный старт (избегание смешивания вывода с другими сервисами) |

### Критичные сопутствующие директивы

| Тип | Обязательные/рекомендуемые директивы |
| :--- | :--- |
| `forking` | `PIDFile=` — путь к PID-файлу (иначе systemd не найдёт главный процесс) |
| `notify` | Приложение должно вызывать `sd_notify("READY=1")` |
| `dbus` | `BusName=` — имя на шине D-Bus |
| `oneshot` | `RemainAfterExit=yes` — если другие сервисы зависят от этого |

> По умолчанию `Type=simple`. Если тип не указан — systemd считает сервис запущенным немедленно после `ExecStart`.

## Практические сценарии

### Type=simple — современное приложение

```ini
[Unit]
Description=Node.js Application

[Service]
Type=simple
WorkingDirectory=/opt/app
ExecStart=/usr/bin/node server.js
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

`systemd` считает сервис запущенным сразу. Подходит, если приложение не форкается и не требует сигнализации готовности.

### Type=forking — классический демон

```ini
[Unit]
Description=Custom Legacy Daemon

[Service]
Type=forking
PIDFile=/run/mydaemon/mydaemon.pid
ExecStart=/usr/sbin/mydaemon --daemon
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Родительский процесс создаёт потомка и завершается. `PIDFile=` критичен — без него systemd потеряет главный процесс.

### Type=notify — сервис с сигнализацией готовности

```ini
[Unit]
Description=Database Service

[Service]
Type=notify
ExecStart=/usr/bin/postgres -D /var/lib/postgres/data
ExecStartPre=/usr/local/bin/warmup.sh
Restart=on-failure
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
```

Приложение вызывает `sd_notify("READY=1")` после полной инициализации. `TimeoutStartSec` увеличен — холодный старт БД может занимать время.

### Type=oneshot — скрипт инициализации

```ini
[Unit]
Description=Load kernel modules
DefaultDependencies=no
Before=sysinit.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/load-modules.sh

[Install]
WantedBy=sysinit.target
```

`RemainAfterExit=yes` — сервис остаётся «active» после завершения, что позволяет другим сервисам зависеть от него.

### Type=exec — ранняя диагностика ошибок

```ini
[Unit]
Description=Application with early validation

[Service]
Type=exec
ExecStart=/usr/local/bin/app --validate-and-run
```

`Type=exec` проверяет, что бинарник существует и является исполняемым **до** попытки запуска. При `Type=simple` ошибка обнаружится позже, и сервис перейдёт в failed.

## Дополнительная информация

### Диагностика типа сервиса

```bash
# Определить текущий тип сервиса
systemctl show <service> --property=Type

# Проверить, считает ли systemd сервис запущенным
systemctl show <service> --property=SubState

# Посмотреть главный PID
systemctl show <service> --property=MainPID

# Если MainPID=0 после старта — тип выбран неверно
```

### Ограничение ресурсов и sandboxing

Директивы `MemoryMax=`, `CPUQuota=`, `PrivateTmp=`, `ProtectSystem=`, `NoNewPrivileges=` и другие применяются ко всем типам сервисов одинаково. Подробное описание — в [cgroups.md](../cgroups.md) (управление ресурсами) и [systemd_run.md](./systemd_run.md) (sandbox-директивы).
