# Юниты, таргеты и зависимости в systemd

## Определения

* **Юниты (Units)**: Основные объекты, которыми управляет `systemd`. Определяют системные ресурсы и действия. Типы юнитов:
  * `.service`: Системная служба (демон).
  * `.socket`: Сетевой сокет, который может активировать службу.
  * `.target`: Группа юнитов, аналог "уровней выполнения" (runlevels).
  * `.timer`: Юнит для запуска других юнитов по расписанию, замена `cron`.
  * `.mount` / `.automount`: Точки монтирования файловых систем.
  * `.path`: Активирует юнит при изменении в файловой системе.
* **Таргет (Target)**: Точка синхронизации, группирующая другие юниты. В `systemd` таргеты являются заменой **уровней выполнения (runlevels)** из старой системы инициализации SysV.
* **Зависимости между юнитами**: Директивы, определяющие порядок запуска и/или требования между юнитами.

| Директива | Тип | Описание |
| :--- | :--- | :--- |
| `After=` | Порядок | Запуск **после** указанного юнита (не создаёт зависимости) |
| `Before=` | Порядок | Запуск **до** указанного юнита |
| `Wants=` | Слабая | Попытка запустить зависимый юнит (неудача не влияет) |
| `Requires=` | Сильная | Если зависимость не запустится, основной юнит не запустится |
| `BindsTo=` | Очень сильная | Как `Requires=`, но связывает жизненные циклы |
| `PartOf=` | Односторонняя | Остановка/перезапуск влияет на этот юнит |
| `Conflicts=` | Конфликт | Остановка указанных юнитов при запуске этого |

**Рекомендация:** Для надёжности используйте комбинацию `Wants=` + `After=` или `Requires=` + `After=`.
* **Типы сервисов (`Type=`)**: Параметр в секции `[Service]` юнит-файла, определяющий, как `systemd` отслеживает состояние службы.
  * `simple` (по умолчанию): `ExecStart` — главный процесс. `systemd` считает сервис запущенным сразу после его старта.
  * `forking`: `ExecStart` запускает процесс, который создает своего потомка и завершается. `systemd` считает главным дочерний процесс. Требует `PIDFile=`.
  * `oneshot`: Для скриптов, которые должны выполниться один раз и завершиться. `systemd` ждет их завершения. Часто используется с `RemainAfterExit=yes`.
  * `notify`: Сервис сам уведомляет `systemd` о готовности через `sd_notify()`.
  * `dbus`: Сервис считается готовым, когда его имя появляется на шине D-Bus.

## Базовые концепции

### Расположение юнит-файлов

* `/usr/lib/systemd/system/`: Юниты, поставляемые с установленными пакетами. **Не изменяйте их напрямую.**
* `/etc/systemd/system/`: Юниты, созданные или измененные системным администратором. Эти файлы имеют приоритет над файлами в `/usr/lib/`.

### Создание собственных юнитов

После создания или изменения юнит-файла необходимо перечитать конфигурацию:

```bash
sudo systemctl daemon-reload
```

### Mount-юниты (`.mount`)

Mount-юниты управляют монтированием файловых систем. Имя файла должно соответствовать пути монтирования (с `/` замененными на `-`).

```ini
# /etc/systemd/system/backup.mount
[Unit]
Description=Mount Backup Disk
# Запускать после сервиса, который подготавливает диск (например, шифрование)
After=wdo.service
# Монтировать ДО запуска локальных файловых систем
Before=local-fs.target
# Требовать запуск сервиса wdo
Requires=wdo.service

[Mount]
Where=/backup
What=/dev/sdb1
Type=ext4
Options=defaults
```

**Ключевые директивы:**
* `Where=` — точка монтирования.
* `What=` — устройство или путь.
* `Type=` — тип файловой системы.
* `Options=` — опции монтирования (как в `/etc/fstab`).

### Automount-юниты (`.automount`)

Automount позволяют монтировать файловую систему **только при обращении** к ней, а не при загрузке. Это полезно для сетевых ФС, зашифрованных дисков или экономии времени загрузки.

```ini
# /etc/systemd/system/backup.automount
[Unit]
Description=Automount Backup Disk
# Зависимости должны совпадать с mount-юнитом
After=wdo.service
Requires=wdo.service

[Automount]
Where=/backup
# Время ожидания перед размонтированием (бездействия)
TimeoutIdleSec=60
```

**Активация:**
```bash
sudo systemctl enable --now backup.automount
```

> **Примечание:** При обращении к `/backup` systemd автоматически смонтирует файловую систему. После `TimeoutIdleSec` секунд бездействия она будет размонтирована.

### Service-юниты для скриптов (Type=oneshot)

Для запуска скриптов (например, бэкапов) используется `Type=oneshot`. Этот тип сообщает systemd, что процесс завершится после выполнения задачи.

```ini
# /etc/systemd/system/backup.service
[Unit]
Description=Backup Script Service
# Зависимость от mount-юнита
Requires=backup.mount
After=backup.mount

[Service]
Type=oneshot
# Запуск от имени пользователя (опционально)
User=backup_user
# Путь к скрипту
ExecStart=/usr/local/bin/backup.sh
# Перенаправление вывода в syslog (для journalctl)
StandardOutput=syslog
StandardError=syslog
# Оставаться в "active" после завершения (для зависимостей)
RemainAfterExit=yes

# Опционально: автозапуск не нужен, если запускается таймером
# [Install]
# WantedBy=multi-user.target
```

**Ключевые директивы:**
* `Type=oneshot` — скрипт выполняется один раз и завершается.
* `RemainAfterExit=yes` — сервис считается активным после завершения скрипта (полезно для зависимостей).
* `User=` — пользователь, от имени которого запускается скрипт (повышает безопасность).
* `StandardOutput=syslog` / `StandardError=syslog` — вывод записывается в syslog (доступно через `journalctl -u backup.service`).

### Директивы безопасности в [Service]

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

### Target-юниты (`.target`)

Таргеты используются для группировки юнитов и управления ими как одним целым.

```ini
# /etc/systemd/system/my-app.target
[Unit]
Description=My Application Target
Documentation=man:systemd.special(7)

[Install]
WantedBy=multi-user.target
```

**Привязка юнитов к таргету:**

В другом юните (например, в `.service`) укажите таргет в секции `[Install]`:

```ini
[Install]
WantedBy=my-app.target
```

**Использование `PartOf=` для зависимостей:**

Директива `PartOf=` позволяет остановить связанные юниты при остановке таргета:

```ini
[Unit]
Description=My Service
PartOf=my-app.target
```

### Таргеты как замена Runlevels

Таргеты в `systemd` — это логические группы юнитов, которые представляют определенное состояние системы. Они обеспечивают гибкую иерархию запуска служб, в отличие от линейных runlevels SysVinit.

**Основные таргеты:**

* `multi-user.target`: Стандартный многопользовательский режим без графического интерфейса (аналог runlevel 3).
* `graphical.target`: Многопользовательский режим с графическим интерфейсом (аналог runlevel 5).

## Практические сценарии

### Управление таргетами

```bash
# Посмотреть текущий таргет по умолчанию
systemctl get-default

# Установить графический режим как таргет по умолчанию
sudo systemctl set-default graphical.target

# Переключиться в другой таргет "на лету"
sudo systemctl isolate multi-user.target
```

### Проверка синтаксиса юнит-файлов (`systemd-analyze verify`)

Перед активацией нового или измененного юнита рекомендуется проверить его на наличие синтаксических ошибок.

```bash
# Проверить синтаксис файла юнита
systemd-analyze verify /etc/systemd/system/my-custom.service
```

Если в файле есть ошибки, команда выведет подробную информацию. В случае отсутствия ошибок команда завершится без вывода. Это позволяет убедиться в корректности файла до выполнения `daemon-reload` и запуска службы.

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

* **Nice и OOMScoreAdjust**: Для приоритетного планирования и защиты от OOM killer’а.

    ```ini
    [Service]
    Nice=-5
    OOMScoreAdjust=-500
    ```
