# Типы сервисов в systemd

## Определения

* **`Type=`** — ключевая директива секции `[Service]`, определяющая алгоритм запуска процесса и механизм, по которому `systemd` определяет момент готовности (Readiness) юнита.
* **Готовность (Readiness)** — состояние, при котором менеджер системных служб считает юнит успешно запущенным и переходит к активации зависимых от него служб (через `After/Requires`).
* **sd_notify** — протокол уведомлений (через Unix-сокет), позволяющий приложению явно сообщать менеджеру об этапах своей инициализации.
* **Жизненный цикл сервиса** — последовательность состояний: `inactive` → `activating` (start) → `active` (running) → `deactivating` (stop) → `inactive`. Для `oneshot` с `RemainAfterExit=yes` конечное состояние — `active (exited)`.
* **Main PID** — идентификатор главного процесса сервиса, отслеживаемый `systemd`. Для типов `simple`, `exec`, `notify` это PID процесса, запущенного через `ExecStart`. Для `forking` — PID дочернего процесса после fork (сверенный с `PIDFile=`).
* **Socket activation** — альтернативный механизм запуска, при котором сервис запускается по первому подключению к сокету. Независим от `Type=`, но часто используется с `Type=simple`.

## Основные концепции

### Сравнение механизмов запуска

| Тип | Критерий готовности | Обнаружение ошибок старта | Применение |
| :--- | :--- | :--- | :--- |
| **`simple`** | Сразу после выполнения системного вызова `fork()`. | Минимальное. | Скрипты, не требующие подтверждения запуска. |
| **`exec`** | (v240+) После успешного завершения `execve()` (когда процесс реально начал исполняться). | Среднее (упадет, если бинарник не найден). | **Рекомендуемая замена `simple`** для всех современных систем. |
| **`forking`** | Когда родительский процесс, запущенный через `ExecStart`, завершается. | Среднее. | Классические демоны, уходящие в фон самостоятельно (`nginx`, `sshd`). |
| **`oneshot`** | После того как главный процесс полностью завершил свою работу. | Высокое. | Скрипты настройки, миграции данных, разовые задачи. |
| **`notify`** | После получения сообщения `READY=1` от приложения по протоколу `sd_notify`. | Максимальное. | Сложные службы с длительным прогревом (`postgresql`, `docker`). |
| **`notify-reload`** | (v253+) Аналог `notify`, но с поддержкой нативной перезагрузки через SIGHUP. | Максимальное. | Современные сервисы, умеющие перечитывать конфиг без `ExecReload`. |
| **`dbus`** | После того как юнит захватит указанное имя на системной шине D-Bus. | Высокое. | Системные компоненты (например, NetworkManager). |
| **`idle`** | Аналог `simple`, но запуск откладывается до выполнения всех других заданий. | Минимальное. | Задачи с низким приоритетом, чтобы не забивать вывод консоли. |

### Детализация механизмов готовности

#### Type=simple
`systemd` считает сервис готовым сразу после `fork()`. Если бинарный файл отсутствует или имеет неверные права, ошибка обнаружится только когда процесс попытается запуститься и упадет с `ENOENT`. Это означает, что зависимые юниты могут стартовать до того, как `systemd` поймет, что запуск Failed.

#### Type=exec
Добавляет проверку после `execve()`. Если запускаемый файл не найден, имеет неправильный формат ELF или отсутствуют права на выполнение, `systemd` немедленно переводит юнит в `failed`. Рекомендуется для всех новых unit-файлов, так как исключает "молчаливый" отказ.

#### Type=forking
`systemd` отслеживает завершение родительского процесса. Если дочерний процесс не создается или PID в `PIDFile=` не соответствует реальному Main PID, сервис считается упавшим. Критически важно указывать `PIDFile=` для корректного отслеживания.

#### Type=oneshot
Сервис остается в состоянии `activating` до полного завершения процесса. Без `RemainAfterExit=yes` юнит переходит в `inactive`, что нарушает цепочки `After=` зависимостей. С флагом `RemainAfterExit=yes` состояние становится `active (exited)`.

#### Type=notify
Приложение должно отправить `READY=1` через сокет уведомлений. Если уведомление не приходит в течение `TimeoutStartSec=`, `systemd` убивает процесс. Протокол поддерживает расширенные статусы: `STATUS=`, `ERRNO=`, `BUSERROR=`, `MAINPID=`.

#### Type=notify-reload
(v253+) При `systemctl reload` `systemd` ожидает последовательности: `RELOADING=1` → (релоад) → `READY=1`. Это исключает гонку, когда `ExecReload` завершился, но приложение еще не готово.

#### Type=dbus
`systemd` подключается к системной шине D-Bus и ожидает появления указанного в `BusName=` имени. Если сервис уже запущен (активируемый по D-Bus), `systemd` не запускает второй экземпляр.

#### Type=idle
Использует тот же критерий готовности, что и `simple`, но запускается в отдельной очереди с пониженным приоритетом. Полезно для фоновых задач, чтобы не создавать помехи в выводе консоли во время загрузки.

### Связанные директивы и их влияние на типы сервисов

| Директива | Взаимодействие с Type= | Описание |
| :--- | :--- | :--- |
| **`TimeoutStartSec=`** | Все типы | Время ожидания готовности. Для `notify`/`dbus` — время ожидания сигнала. Для `forking` — время завершения родителя. По умолчанию `DefaultTimeoutStartSec=90s`. |
| **`TimeoutStopSec=`** | Все типы | Время ожидания graceful shutdown (SIGTERM). По умолчанию `DefaultTimeoutStopSec=90s`. |
| **`Restart=`** | Все, кроме `oneshot` (по умолчанию `no`) | Политика перезапуска: `no`, `on-success`, `on-failure`, `on-abnormal`, `on-watchdog`, `always`. Для `oneshot` перезапуск обычно бессмысленен. |
| **`RestartSec=`** | Взаимодействует с `Restart=` | Задержка перед перезапуском. Для `on-failure` с экспоненциальным backoff используйте `RestartSec=5s` и `StartLimitIntervalSec=`, `StartLimitBurst=`. |
| **`RemainAfterExit=`** | `oneshot`, `notify` (редко) | Оставить юнит `active` после завершения. Критично для `oneshot`, если зависимые юниты используют `After=`. |
| **`PIDFile=`** | `forking` (обязательно), `notify` (опционально) | Путь к файлу с PID главного процесса. Для `forking` требуется для корректного отслеживания Main PID. |
| **`BusName=`** | `dbus` (обязательно) | Имя, которое сервис зарегистрирует на системной шине. |
| **`NotifyAccess=`** | `notify`, `notify-reload` | `none` (только main process), `main` (main + fork), `all` (все процессы). По умолчанию `main`. |
| **`ExecStartPre=`** | Все типы | Команды, выполняемые перед `ExecStart=`. Сбой прерывает запуск. |
| **`ExecStartPost=`** | Все типы | Команды после готовности сервиса. Не влияют на критерий готовности. |
| **`ExecReload=`** | Все, кроме `notify-reload` | Команда перезагрузки конфигурации. Для `notify-reload` используется встроенный механизм. |
| **`ExecStop=`** | Все типы | Команда graceful shutdown. Если не указана — отправка SIGTERM. |
| **`WatchdogSec=`** | Все типы | Включение watchdog. Приложение должно отправлять `WATCHDOG=1` через `sd_notify`. |
| **`KillMode=`** | Все типы | `control-group` (по умолчанию), `main`, `mixed`, `none`. Определяет, какие процессы убивать при остановке. |
| **`User=` / `Group=`** | Все типы | Пользователь и группа для запуска процесса. |

### Глубокий разбор поведения

#### Нативная перезагрузка (Type=notify-reload)
Начиная с версии v253, этот тип позволяет отказаться от директивы `ExecReload`. `systemd` сам отправляет сигнал (обычно SIGHUP) и ждет от приложения уведомления `RELOADING=1` → `READY=1`. Это исключает «состояние неопределенности» во время перезапуска.

#### Работа с D-Bus (Type=dbus)
Для этого типа обязательна директива **`BusName=`**. `systemd` будет блокировать запуск зависимых юнитов до тех пор, пока сервис не зарегистрирует свое имя на шине. Это гарантирует, что клиенты не получат ошибку «Name not found» при обращении к сервису сразу после старта.

#### Сохранение состояния Oneshot
Директива **`RemainAfterExit=yes`** критична для `oneshot`. Без нее сервис перейдет в статус `inactive` сразу после завершения процесса, и зависимые юниты (`After`) могут не запуститься или посчитать это сбоем. С этим флагом юнит останется в статусе `active (exited)`.

#### Обработка двойного fork (double-fork)
Классические демоны, которые делают `fork()` дважды (чтобы отсоединиться от управляющего терминала), создают проблему для `Type=simple` и `Type=exec`: `systemd` считает завершенным процесс-предок, который немедленно завершается, в то время как реальный демон остается в фоне. Для таких случаев используйте `Type=forking` с корректным `PIDFile=`, либо отключите двойной fork в самом приложении (рекомендуется для современных сервисов).

## Практические сценарии

### 1. Переход с Simple на Exec (Production стандарт)

```ini
[Service]
Type=exec
ExecStart=/usr/bin/my-app
# Если my-app не существует, systemctl start выдаст ошибку немедленно
```

### 2. Настройка классического демона (Forking)

Требует явного указания PID-файла, чтобы `systemd` знал, какой именно процесс в дереве является «главным».

```ini
[Service]
Type=forking
ExecStart=/usr/sbin/nginx -c /etc/nginx/nginx.conf
PIDFile=/run/nginx.pid
```

### 3. Использование уведомлений в обертках

Если основное приложение не поддерживает `sd_notify`, можно использовать утилиту `systemd-notify` в shell-скрипте.

```ini
[Service]
Type=notify
# Разрешаем отправку уведомлений дочерним процессам
NotifyAccess=all
ExecStart=/usr/local/bin/start_app.sh
```

**Скрипт `start_app.sh`**:
```bash
#!/bin/bash
# Выполняем предварительные действия
/usr/bin/prepare_db.sh
# Сообщаем о готовности
systemd-notify --ready --status="DB Prepared, launching app..."
# Передаем управление приложению
exec /usr/bin/my-app
```

### 4. Oneshot-сервис с RemainAfterExit

Используйте для разовых задач настройки, которые должны оставаться активными после завершения.

```ini
[Service]
Type=oneshot
ExecStart=/usr/local/bin/initial-setup.sh
RemainAfterExit=yes
```

### 5. Управление политикой перезапуска (Restart)

Различные политики для разных сценариев:

```ini
[Service]
Type=simple
ExecStart=/usr/bin/critical-app
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=300
StartLimitBurst=5
```

### 6. Ограничение времени запуска (TimeoutStartSec)

Для сервисов с долгим прогревом:

```ini
[Service]
Type=notify
ExecStart=/usr/bin/postgresql
TimeoutStartSec=300
NotifyAccess=all
```

### 7. Использование ExecStartPre и ExecStartPost

Предварительная и последующая подготовка:

```ini
[Service]
Type=simple
ExecStartPre=/usr/bin/check-disk.sh
ExecStart=/usr/bin/app
ExecStartPost=/usr/bin/register-in-etcd.sh
```

### 8. Переменные окружения и рабочий каталог

```ini
[Service]
Type=simple
WorkingDirectory=/opt/app
Environment="NODE_ENV=production"
EnvironmentFile=/opt/app/.env
ExecStart=/usr/bin/node server.js
```

### 9. Watchdog для автоматического перезапуска зависшего сервиса

```ini
[Service]
Type=notify
ExecStart=/usr/bin/my-app
WatchdogSec=30
NotifyAccess=all
# Приложение должно отправлять WATCHDOG=1 каждые 10 секунд
```

### 10. Type=dbus для системного компонента

```ini
[Service]
Type=dbus
BusName=org.freedesktop.NetworkManager
ExecStart=/usr/sbin/NetworkManager
```

### 11. Graceful shutdown и корректная обработка сигналов

```ini
[Service]
Type=simple
ExecStart=/usr/bin/web-app
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=30
ExecStop=/usr/bin/drain-connections.sh
```

### 12. Socket activation с Type=simple

```ini
# /etc/systemd/system/ssh.socket
[Socket]
ListenStream=2222
Accept=no

# /etc/systemd/system/ssh@.service
[Service]
Type=simple
ExecStart=/usr/sbin/sshd -i -e
```

### 13. Перенаправление STDIN/STDOUT/STDERR

```ini
[Service]
Type=simple
ExecStart=/usr/bin/app
StandardInput=tty
StandardOutput=journal
StandardError=journal
```

### 14. Ограничение ресурсов и изоляция

```ini
[Service]
Type=simple
ExecStart=/usr/bin/app
MemoryMax=512M
CPUQuota=50%
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
NoNewPrivileges=yes
```

## Диагностика и отладка

### Проверка типа и статуса

```bash
# Узнать текущий тип запущенного сервиса
systemctl show my-app.service -p Type

# Просмотр ошибок протокола уведомлений
# Если Type=notify, а READY=1 не пришел вовремя
journalctl -u my-app.service
# → my-app.service: Start operation timed out. Terminating.
```

### Мониторинг D-Bus

```bash
# Проверка зарегистрированных имен (для Type=dbus)
busctl list | grep org.my.Service
```

### Проверка Main PID

```bash
# Узнать Main PID сервиса
systemctl show my-app.service -p MainPID

# Сравнить с реальным PID в системе
ps -p $(systemctl show my-app.service -p MainPID --value) -o pid,ppid,cmd
```

### Проверка статуса oneshot

```bash
# Для oneshot с RemainAfterExit=yes
systemctl status my-app.service
# → Active: active (exited) since ...

# Без RemainAfterExit
systemctl status my-app.service
# → Active: inactive (dead) since ...
```

### Диагностические команды по типам сервисов

| Команда | Контекст | Описание |
| :--- | :--- | :--- |
| `systemctl show <unit> -p Type,Result,ExecMainStatus,SubState` | Все типы | Полная диагностика состояния запуска. `Result=success` или `Result=timeout`. |
| `systemctl show <unit> -p MainPID,ControlGroup` | `simple`, `exec`, `notify` | Проверка процесса и cgroup. |
| `systemctl show <unit> -p FragmentPath,AssertPathExists` | Все типы | Проверка путей к unit-файлу и существования файлов. |
| `systemd-analyze critical-chain <unit>` | Все типы | Время запуска и зависимые юниты. |
| `journalctl -u <unit> -b` | Все типы | Логи с текущей загрузки. |
| `systemctl status <unit>` | Все типы | Краткий статус, Main PID, последние логи. |

## Устранение неисправностей

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| `NTP service: inactive` | Юнит не запущен или `Type=` не соответствует поведению процесса | Проверьте `systemctl status`, сравните с таблицей типов. |
| `System clock synchronized: no` | `systemd-timesyncd` не подключился к серверу или сработал таймаут | Проверьте сеть, конфигурацию `/etc/systemd/timesyncd.conf`, `timedatectl timesync-status`. |
| `Start operation timed out` | `TimeoutStartSec=` истек, приложение не отправило `READY=1` | Увеличьте `TimeoutStartSec`, проверьте логи приложения. |
| `Stratum: 16` | Нет подключения к upstream NTP-серверам | Проверьте DNS, файрвол (UDP/123), настройки `FallbackNTP`. |
| Конфликт с Chrony или ntpd | Два клиента NTP одновременно | Отключите один из сервисов: `systemctl disable --now chronyd`. |
| `Type=notify`, но нет уведомлений | Приложение не поддерживает `sd_notify`, `NotifyAccess=` ограничен | Используйте обертку с `systemd-notify` или переключитесь на `Type=simple`/`exec`. |
| `Type=forking`, сервис падает | Отсутствует `PIDFile=`, демон делает double-fork, PID не совпадает | Укажите корректный `PIDFile=`, проверьте логи. |
| `Type=dbus`, имя уже занято | Другой сервис зарегистрировал то же `BusName=` | Проверьте `busctl list`, измените имя или уберите конфликтующий сервис. |
| Сервис падает сразу после старта | Некорректный `Type=`, отсутствуют права, не найден бинарник | Для `exec` ошибка будет явной; для `simple` проверьте логи. |
| `oneshot` завершается, юнит `inactive` | Отсутствует `RemainAfterExit=yes` | Добавьте директиву для поддержки зависимостей `After=`. |
| `Restart=` не срабатывает | `Restart=on-failure` не реагирует на SIGKILL, для `oneshot` restart отключен | Используйте `Restart=always` или проверьте `SuccessExitStatus=`. |
| Watchdog не работает | `WatchdogSec=` указан, но приложение не отправляет `WATCHDOG=1` | Добавьте отправку уведомления в код приложения. |
| PID-файл не обновляется | Демон пишет PID в другой путь или права на каталог `/run/` ограничены | Проверьте путь `PIDFile=`, права на каталог. |
| `sd_notify` недоступен | Переменная `$NOTIFY_SOCKET` не установлена, сокет не смонтирован | Для контейнеров пробросите сокет: `-v /run/systemd/notify:/run/systemd/notify`. |

## Рекомендации по эксплуатации (Best Practices)

1. **Используйте `Type=exec` вместо `simple`** для всех новых unit-файлов. Это исключает "молчаливый" отказ при отсутствии бинарника.
2. **Применяйте `Type=notify` для сложных сервисов** с длительным прогревом. Это позволяет зависимым юнитам стартовать точно в момент готовности, а не по факту fork().
3. **Ограничивайте `TimeoutStartSec=`** для быстрых сервисов. Значение по умолчанию 90 секунд слишком велико для простых скриптов.
4. **Всегда указывайте `PIDFile=` для `Type=forking`**. Без этого `systemd` не может корректно отслеживать Main PID и управлять процессом.
5. **Используйте `RemainAfterExit=yes` для `oneshot`**, если зависимые юниты используют `After=`. Без флага юнит перейдет в `inactive`.
6. **Настраивайте `Restart=on-failure` с `RestartSec=5`** для критичных сервисов. Это обеспечивает автоматическое восстановление после падения.
7. **Ограничьте частоту перезапусков** через `StartLimitIntervalSec=` и `StartLimitBurst=`, чтобы избежать штормов при поломке инфраструктуры.
8. **Используйте `KillMode=mixed`** для сервисов, которые порождают дочерние процессы. Это гарантирует, что SIGTERM получит только главный процесс, а SIGKILL — все остальные.
9. **Для legacy-приложений без `sd_notify`** используйте `Type=exec` или `Type=simple` с оберткой, если перехватывать сигналы и отправлять `systemd-notify` нецелесообразно.
10. **Избегайте `Restart=always` для `oneshot`** сервисов. Это приведет к бесконечному циклу перезапуска разовой задачи.

## Ограничения и крайние случаи

* **Server mode (встроенный NTP-сервер):** `systemd-timesyncd` работает только как клиент. Для серверного режима используйте `chronyd` или `ntpd`.
* **Точность:** `systemd-timesyncd` подходит для большинства задач, но не для систем, требующих высокой точности (PTP, GPS). Для этого используйте `chrony` с опцией `makestep`.
* **NTS (Network Time Security):** `systemd-timesyncd` не поддерживает NTS. Для защиты от атак MitM используйте `chronyd`.
* **Таймауты:** При больших сдвигах времени (boot после простоя) `systemd-timesyncd` может не успеть синхронизироваться до старта критичных сервисов. Используйте `makestep` или настройте `time-sync.target`.
* **Контейнеры:** В контейнерах настройте синхронизацию на уровне хоста. Контейнеры автоматически используют системные часы хоста.
* **Двойной fork:** Если демон делает double-fork без опции, `Type=simple` и `Type=exec` не смогут корректно отслеживать Main PID. Используйте `Type=forking` с `PIDFile=`.
* **D-Bus активация:** `Type=dbus` работает только если клиент обращается к сервису через D-Bus. Прямой запуск через `systemctl start` может не сработать, если сервис не может зарегистрировать имя сам.
* **Idle приоритет:** `Type=idle` может вызвать задержку запуска на системах с высокой нагрузкой. Не используйте для критичных сервисов.
* **Watchdog ограничения:** `WatchdogSec=` работает только с `Type=notify` и `Type=notify-reload`. Для других типов watchdog неактивен.
* **SIGSTOP и cgroup:** `systemd` не переводит процессы в `T` (stopped) при `systemctl stop`, а использует ` freezer` cgroup или SIGTERM/SIGKILL.
* **PID-файл и перезапуск:** Если `PIDFile=` указывает на несуществующий файл при перезапуске, `systemd` считает старый процесс завершенным и запускает новый экземпляр.
* **Конфликт типов:** Если указан `Type=simple`, а приложение делает fork(), `systemd` будет отслеживать только исходный процесс. Ребенок останется "сиротой" в той же cgroup.

## Очистка и обслуживание

### Отключение ненужного типа сервиса

```bash
# Остановить и отключить сервис
sudo systemctl disable --now my-app.service

# Если сервис был активирован через socket или таймер
sudo systemctl disable --now my-app.socket my-app.timer
```

### Восстановление стандартного типа

```bash
# Если изменили Type= и нужно вернуть default
sudo systemctl daemon-reload
sudo systemctl restart my-app.service
```

### Сброс состояния failed

```bash
# После превышения лимита перезапусков
sudo systemctl reset-failed my-app.service
sudo systemctl start my-app.service
```

### Проверка после изменений

```bash
# Проверить тип и статус
systemctl show my-app.service -p Type,SubState,Result,MainPID

# Проверить, что процесс работает
systemctl status my-app.service

# Проверить логи на ошибки
journalctl -u my-app.service -n 50 --no-pager
```

## См. также
* [Структура юнит-файла](./systemd_unit_file_structure.md) — обзор секций `[Service]` и `[Unit]`.
* [Управление зависимостями](./systemd_dependencies.md) — как тип запуска влияет на момент активации `After=`.
* [Обзор юнитов systemd](./systemd_units_overview.md) — классификация всех типов объектов.
* [Обзор systemd](./overview.md) — общие принципы работы менеджера служб.