# systemd Service Types

## Определения

**Типы сервисов (`Type=`)**: Параметр в секции `[Service]` юнит-файла, определяющий, как `systemd` отслеживает состояние службы.

* `simple` (по умолчанию): `ExecStart` — главный процесс. `systemd` считает сервис запущенным сразу после его старта.
* `forking`: `ExecStart` запускает процесс, который создает своего потомка и завершается. `systemd` считает главным дочерний процесс. Требует `PIDFile=`.
* `oneshot`: Для скриптов, которые должны выполниться один раз и завершиться. `systemd` ждет их завершения. Часто используется с `RemainAfterExit=yes`.
* `notify`: Сервис сам уведомляет `systemd` о готовности через `sd_notify()`.
* `dbus`: Сервис считается готовым, когда его имя появляется на шине D-Bus.

## Базовые концепции

### Директивы безопасности (sandboxing)

Современные best practices рекомендуют использовать sandbox-директивы для изоляции служб:

```ini
[Service]
# Ограничение ресурсов
MemoryMax=512M
CPUQuota=50%

# Безопасность
NoNewPrivileges=yes          # Запрет получения новых привилегий
PrivateTmp=yes               # Отдельный /tmp для сервиса
ProtectSystem=strict         # Защита системных директорий
ProtectHome=yes              # Защита домашних директорий
ReadWritePaths=/var/lib/app  # Разрешённые пути для записи
ReadOnlyPaths=/etc           # Только чтение для /etc

# Сеть
PrivateNetwork=no            # Отдельный network namespace (если нужно)
RestrictAddressFamilies=AF_INET AF_INET6  # Разрешённые семейства адресов

# Capabilities
CapabilityBoundingSet=CAP_NET_BIND_SERVICE  # Ограничить capabilities
AmbientCapabilities=         # Сброс ambient capabilities
```

## Дополнительная информация

### Оптимизация производительности и приоритеты при холодном старте

* **IOSchedulingClass и IOSchedulingPriority**: Позволяют задать класс и приоритет доступа к диску.

    ```ini
    [Service]
    IOSchedulingClass=best-effort
    IOSchedulingPriority=2
    ```

    Для сервисов, работающих с базами данных или логами, можно установить `IOSchedulingClass=realtime` или поднять приоритет (ближе к `0`).
* **CPUSchedulingPolicy и CPUSchedulingPriority**: Контроль приоритетов на уровне CPU-шедулера. Для критичных задач — `SCHED_FIFO` или `SCHED_RR`.

    ```ini
    [Service]
    CPUSchedulingPolicy=fifo
    CPUSchedulingPriority=50
    ```

* **StartLimitBurst и StartLimitIntervalSec**: Контролируют поведение при частых перезапусках.

    ```ini
    [Unit]
    StartLimitBurst=10
    StartLimitIntervalSec=30
    ```

    Это полезно, если сервис зависит от сети или сторонних демонов и может не сразу запуститься.
* **TimeoutStartSec**: Увеличивает таймаут запуска, если холодный старт занимает много времени.

    ```ini
    [Service]
    TimeoutStartSec=60s
    ```

* **ExecStartPre и ReadyNotify**: Позволяют запускать предварительную инициализацию отдельно.

    ```ini
    [Service]
    ExecStartPre=/usr/local/bin/warmup.sh
    Type=notify
    ```

* **Nice и OOMScoreAdjust**: Для приоритетного планирования и защиты от OOM killer'а.

    ```ini
    [Service]
    Nice=-5
    OOMScoreAdjust=-500
    ```
