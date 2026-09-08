# Интеграция Docker и systemd: Управление юнитами

## Определения

* **Интеграция Docker с systemd** — архитектурный подход, при котором внешняя система инициализации (`systemd`) управляет жизненным циклом Docker-контейнеров на хосте. В этой модели контейнер рассматривается как стандартная системная служба.
* **`sdnotify`** — протокол уведомления о готовности (READY=1), позволяющий приложению внутри контейнера сообщить `systemd` об успешном запуске для разблокировки зависимых служб.
* **Делегирование (Delegation)** — механизм cgroup v2, позволяющий менеджеру процессов (PID 1) передать управление определенной веткой иерархии ресурсов (CGroup) дочернему процессу (Docker daemon), что необходимо для корректной работы лимитов внутри контейнера.
* **Активация через сокет (Socket Activation)** — механизм systemd, при котором юнит-файл сокета (`docker.socket`) активирует демон Docker по первому входящему подключению, экономя ресурсы на простаивающих хостах.
* **Жёсткий лимит (`MemoryMax=`)** — абсолютный порог потребления памяти, при превышении которого ядро инициирует OOM Killer внутри cgroup. В контексте Docker соответствует `--memory` флагу `docker run`.
* **Мягкий лимит (`MemoryHigh=`)** — порог троттлинга памяти: при превышении система начинает активно вытеснять страницы процесса, но не убивает его.
* **`KillMode=mixed`** — режим завершения, при котором `systemd` отправляет SIGTERM только основному процессу (`docker run`), позволяя Docker daemon корректно остановить контейнер. В режиме `control-group` systemd может убить прокси-процессы раньше времени.

## Архитектура и принципы работы

### Взаимодействие компонентов

При внешнем управлении контейнер через `systemd` взаимодействие строится по следующей схеме:

1. **Systemd (PID 1)** читает unit-файл и активирует зависимости (`Requires=docker.service`).
2. **Docker daemon** (`dockerd`) запускается как стандартный системный сервис и управляет образом и сетью.
3. **Unit-файл приложения** вызывает `docker run` через `ExecStart=`. Контейнер становится дочерним процессом transient-scope, связанного с unit-файлом.
4. **Cgroup delegation** (`Delegate=yes`) передает Docker daemon'у управление под-cgroups для процессов внутри контейнера. Без этого лимиты, заданные через `docker run` (например, `--cpus`, `--memory`), не будут применены корректно в cgroup v2.
5. **Жизненный цикл:** `systemd` отслеживает выходной код `docker run`. При падении контейнера срабатывает политика `Restart=`. При остановке юнита (`systemctl stop`) systemd вызывает `ExecStop=` (обычно `docker stop`), ожидая вежливого завершения.

### Жизненный цикл unit-файла

| Состояние | Событие | Действие systemd |
| :--- | :--- | :--- |
| **inactive** | `systemctl start app-container` | Загрузка unit-файла, активация зависимостей, запуск `ExecStartPre=` |
| **activating** | Выполнение `docker run` | Ожидание READY=1 (если `Type=notify`) или завершения fork (если `Type=simple`) |
| **active** | Контейнер работает | Мониторинг главного процесса, сбор логов в journald |
| **deactivating** | `systemctl stop app-container` | Выполнение `ExecStop=`, ожидание `TimeoutStopSec=` |
| **failed** | Выходной код ≠ 0 после `RestartSec=` exhaustion | Уведомление в journald, счетчик сбоев |

### Типы сервисов и Docker

Для контейнеров, управляемых systemd, предпочтителен `Type=simple` (по умолчанию), так как `docker run` не уходит в фон самостоятельно. Если приложение внутри контейнера поддерживает `sdnotify`, можно использовать `Type=notify`. `Type=oneshot` применим только для разовых задач (миграции, инициализация данных) с флагом `RemainAfterExit=yes`.

## Основные концепции

### Преимущества внешнего управления

1.  **Нативная оркестрация зависимостей:** Использование `After=`, `Requires=` и `Wants=` для связки контейнеров с базами данных на хосте, точками монтирования или сетевыми интерфейсами.
2.  **Централизованная диагностика:** Команды `systemctl status` и `journalctl -u` предоставляют полную картину состояния приложения без необходимости переключения контекста на Docker CLI.
3.  **Гибкая политика перезапуска:** Настройка `StartLimitIntervalSec` и `StartLimitBurst` предотвращает бесконечные циклы перезапуска при фатальных ошибках.
4.  **Безопасная очистка:** Автоматическое удаление контейнеров при остановке (`--rm`) гарантирует отсутствие конфликтов имен при следующем запуске.

### Параметры юнита и безопасность

| Директива | Назначение | Техническое обоснование |
| :--- | :--- | :--- |
| **`Delegate=yes`** | Управление cgroups | Обязательно для Docker в режиме cgroup v2. Позволяет Docker создавать под-cgroups для процессов контейнера без конфликтов с `systemd`. |
| **`KillMode=mixed`** | Режим завершения | Отправляет SIGTERM только основному процессу (`docker run`), позволяя Docker daemon корректно остановить контейнер. В режиме `control-group` systemd может убить прокси-процессы раньше времени. |
| **`Type=notify`** | Уведомление о готовности | Если приложение поддерживает `sdnotify`, systemd будет ждать сигнала READY перед запуском зависимых юнитов. Требует проброса сокета. |
| **`EnvironmentFile=`** | Конфигурация | Позволяет выносить настройки (порты, теги образов) в отдельный файл (например, `/etc/default/myapp`), не меняя сам юнит. |
| **`ProtectSystem=strict`** | Защита ФС | Монтирует корневую ФС как read-only, исключая `/etc`, `/usr` и другие каталоги из изменений. Для записи используйте tmpfs или отдельные volume. |
| **`PrivateTmp=yes`** | Изоляция временных файлов | Создает изолированный `/tmp` и `/var/tmp` для сервиса, предотвращая доступ к временным файлам других служб. |
| **`ProtectHome=yes`** | Защита домашних каталогов | Делает `/home`, `/root`, `/run/user` невидимыми или read-only для сервиса. |
| **`NoNewPrivileges=yes`** | Ограничение привилегий | Запрещает процессу и его дочерним процессам получать новые привилегии через `setuid`/`capabilities`. |
| **`ReadOnlyPaths=`** | Выборочная защита | Позволяет сделать конкретные пути read-only (например, `ReadOnlyPaths=/etc/myapp.conf`). |
| **`CPUQuota=`** | Лимит CPU | Ограничивает процент CPU (например, `CPUQuota=50%` = половина одного ядра). Работает в связке с `CPUAccounting=yes`. |
| **`MemoryMax=`** | Лимит памяти | Жёсткий лимит RAM (например, `MemoryMax=1G`). При превышении срабатывает OOM Killer внутри cgroup. |
| **`IOWeight=`** | Приоритет диска | Относительный вес I/O (1-10000). Для снижения приоритета фоновых задач используйте `IOSchedulingClass=idle`. |

### Управление ресурсами и окружением

#### Resource limits в unit-файле

В отличие от флагов `docker run` (`--cpus`, `--memory`), systemd-директивы применяются на уровне cgroup хоста до запуска контейнера. Это обеспечивает гарантированное выделение ресурсов даже до момента загрузки образа:

```ini
[Service]
Delegate=yes
CPUAccounting=yes
CPUQuota=50%
MemoryAccounting=yes
MemoryMax=1G
MemoryHigh=800M
IOAccounting=yes
IOWeight=100
TasksMax=256
```

**Почему это важно:** Если Docker daemon запущен с задержкой (например, при холодном старте), `docker run --memory=1G` не защитит хост до фактического запуска контейнера. `MemoryMax=` в юните работает немедленно.

#### Environment management

Для безопасной передачи секретов используйте `EnvironmentFile=` с правами `600`:

```bash
# /etc/default/app-container
IMAGE_TAG=myapp:1.2.3
HOST_PORT=8080
DB_PASSWORD=supersecret
```

```ini
# В unit-файле
EnvironmentFile=-/etc/default/app-container
```

Флаг `-` перед путем означает, что отсутствие файла не считается ошибкой. Это позволяет использовать один юнит на всех окружениях, подключая нужный файл через drop-in или условие.

#### Обработка сигналов

`KillSignal=` и `SendSIGKILL=` контролируют цепочку завершения:

```ini
[Service]
KillSignal=SIGTERM
TimeoutStopSec=30
SendSIGKILL=no
```

Если Docker контейнер корректно обрабатывает SIGTERM (например, через `exec` в PID 1), достаточно `TimeoutStopSec=`. Для legacy-образов, игнорирующих SIGTERM, добавьте `SendSIGKILL=yes` с запасом времени.

### Интеграция с journald

Все stdout/stderr контейнера автоматически попадают в journald через драйвер `json-file` (по умолчанию). Для единого хранилища логов:

```bash
# Фильтрация по конкретному контейнеру
journalctl -u app-container.service --since "1 hour ago"

# Следование за логами в реальном времени
journalctl -u app-container.service -f

# Экспорт в JSON для парсинга
journalctl -u app-container.service -o json | jq '._PID'
```

## Практические сценарии

### 1. Эталонный юнит для контейнера (Production)

Путь: `/etc/systemd/system/app-container.service`

```ini
[Unit]
Description=My App Production Container
Requires=docker.service
After=docker.service network-online.target
Wants=docker.socket

[Service]
Restart=on-failure
RestartSec=10
TimeoutStartSec=0
StartLimitIntervalSec=300
StartLimitBurst=5
Delegate=yes
CPUAccounting=yes
CPUQuota=50%
MemoryAccounting=yes
MemoryMax=1G
MemoryHigh=800M
IOAccounting=yes
IOWeight=100
TasksMax=256
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
NoNewPrivileges=yes
EnvironmentFile=-/etc/default/app-container

ExecStartPre=-/usr/bin/docker stop %n
ExecStartPre=-/usr/bin/docker rm %n
ExecStartPre=/usr/bin/docker pull ${IMAGE_TAG}
ExecStartPre=/usr/local/bin/check-image.sh ${IMAGE_TAG}

ExecStart=/usr/bin/docker run --rm --name %n \
    --env-file /etc/default/app-container \
    -p ${HOST_PORT}:80 \
    ${IMAGE_TAG}

ExecStop=/usr/bin/docker stop -t 30 %n

[Install]
WantedBy=multi-user.target
```

### 2. Использование Docker Compose как системной службы

Идеально для многокомпонентных приложений на одном узле.

```ini
[Unit]
Description=Docker Compose Stack
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/myapp-stack
Delegate=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
NoNewPrivileges=yes
CPUQuota=100%
MemoryMax=4G

ExecStartPre=/usr/bin/docker compose pull
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down --timeout 30

[Install]
WantedBy=multi-user.target
```

### 3. Настройка уведомлений (sdnotify)

Для использования `Type=notify` в контейнере необходимо пробросить путь к сокету уведомлений:
1.  Установите `NotifyAccess=all` в юните.
2.  Пробросьте `$NOTIFY_SOCKET` в контейнер как переменную окружения.
3.  Монтируйте сокет: `-v /run/systemd/notify:/run/systemd/notify`.

### 4. Активация через сокет (Socket Activation)

Для демонов, которые простаивают большую часть времени, socket activation снижает потребление памяти:

```ini
# /etc/systemd/system/docker-registry.socket
[Unit]
Description=Docker Registry Socket

[Socket]
ListenStream=127.0.0.1:5000
BindIPv6Only=both

[Install]
WantedBy=sockets.target
```

```ini
# /etc/systemd/system/docker-registry.service
[Unit]
Description=Docker Registry Container
Requires=docker.service
After=docker.service

[Service]
Type=notify
NotifyAccess=all
ExecStart=/usr/bin/docker run --rm --name docker-registry \
    -v /opt/registry/data:/var/lib/registry \
    registry:2
ExecStop=/usr/bin/docker stop docker-registry

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now docker-registry.socket
# Демон запустится при первом подключении к порту 5000
```

### 5. Защищённый юнит с sandboxing

Максимальная изоляция для контейнеров, обрабатывающих внешний ввод:

```ini
[Unit]
Description=Sandboxed Container
After=docker.service

[Service]
Type=simple
Restart=on-failure
RestartSec=5
Delegate=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
PrivateDevices=yes
NoNewPrivileges=yes
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
CPUQuota=25%
MemoryMax=512M
IOWeight=50

ExecStartPre=/usr/bin/docker inspect ${IMAGE_TAG}
ExecStart=/usr/bin/docker run --rm --name sandbox-app \
    --read-only \
    --tmpfs /tmp \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    ${IMAGE_TAG}

ExecStop=/usr/bin/docker stop -t 10 sandbox-app
```

### 6. Предварительная валидация и healthcheck

Проверка образа и зависимостей перед запуском:

```ini
[Unit]
Description=Validated Container
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=simple
Restart=on-failure
RestartSec=15
StartLimitIntervalSec=600
StartLimitBurst=3
Delegate=yes
CPUQuota=50%
MemoryMax=2G

# Валидация образа
ExecStartPre=-/usr/bin/docker rm -f %n
ExecStartPre=/usr/local/bin/verify-image.sh ${IMAGE_TAG}
ExecStartPre=/usr/local/bin/check-disk-space.sh /var/lib/docker 10G

# Запуск с healthcheck
ExecStart=/usr/bin/docker run --rm --name %n \
    --health-cmd="curl -f http://localhost:8080/health || exit 1" \
    --health-interval=30s \
    --health-timeout=5s \
    --health-retries=3 \
    ${IMAGE_TAG}

# Graceful shutdown с ожиданием ready probe
ExecStop=/usr/bin/docker stop -t 40 %n
```

Скрипт `verify-image.sh`:
```bash
#!/bin/bash
IMAGE=$1
if ! docker inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Image $IMAGE not found"
    exit 1
fi
echo "Image $IMAGE verified"
```

### 7. Цепочки зависимостей многоконтейнерных приложений

Для приложений, где контейнеры зависят друг от друга, используйте `After=` и `Requires=`:

```ini
# /etc/systemd/system/db-migration.service
[Unit]
Description=Database Migration Container
Requires=docker.service postgresql.service
After=docker.service postgresql.service

[Service]
Type=oneshot
RemainAfterExit=yes
Delegate=yes
CPUQuota=25%
MemoryMax=512M

ExecStartPre=/usr/bin/docker pull db-migrator:latest
ExecStart=/usr/bin/docker run --rm --network app-network \
    -e DATABASE_URL=postgres://app:secret@db:5432/myapp \
    db-migrator:latest
```

```ini
# /etc/systemd/system/web-app.service
[Unit]
Description=Web Application Container
Requires=docker.service db-migration.service
After=docker.service db-migration.service

[Service]
Type=simple
Restart=on-failure
Delegate=yes
CPUQuota=50%
MemoryMax=1G

ExecStart=/usr/bin/docker run --rm --name web-app \
    --network app-network \
    -p 8080:80 \
    web-app:latest
```

### 8. Динамические задачи через systemd-run

Для разовых операций (бэкап, миграция, диагностика) без создания постоянных unit-файлов:

```bash
# Ограниченный по ресурсам бэкап
sudo systemd-run --unit=backup-job \
  --scope \
  -p MemoryMax=1G \
  -p CPUQuota=25% \
  -p IOWeight=50 \
  -p PrivateTmp=yes \
  /usr/local/bin/backup.sh

# Валидация
systemctl status backup-job.scope
systemd-cgls | grep backup-job
```

## Диагностика и управление

```bash
# Проверка влияния Delegate на иерархию cgroups
systemd-cgls --unit app-container.service

# Чтение журналов с метаданными Docker
journalctl -u app-container.service -o json | jq '._KERNEL_DEVICE'

# Проверка статуса сокета Docker, от которого зависит юнит
systemctl status docker.socket

# Мониторинг потребления ресурсов unit'ом
systemd-cgtop --batch --iterations=1 --raw | grep app-container

# Проверка параметров cgroup
systemctl show app-container.service \
  -p Delegate \
  -p CPUQuota \
  -p MemoryMax \
  -p ControlGroup

# Проверка доступных контроллеров cgroup v2
cat /sys/fs/cgroup/cgroup.controllers
# → cpu io memory pids

# Проверка delegation в родительской группе
cat /sys/fs/cgroup/system.slice/cgroup.subtree_control
# → cpu io memory pids

# Диагностика конфликтов cgroup
systemd-analyze verify app-container.service
journalctl -u app-container.service -n 50 --no-pager
```

## Устранение неисправностей

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Failed at step Memory cgroup` | Ошибка delegation или ядро не поддерживает запрашиваемый контроллер. | Проверьте: `/sys/fs/cgroup/cgroup.controllers`. Убедитесь, что родительская cgroup делегирует контроллеры (`Delegate=yes` в родительском slice). |
| `Permission denied` при записи в cgroup | Отсутствуют права root или родительский slice не делегировал контроллер. | Запускайте через `sudo`. Проверьте `Delegate=yes` для родительского slice. |
| `CPUQuota` не применяется | Включен `CPUQuotaPeriodSec` с некорректным значением или отсутствует `CPUAccounting=`. | Установите `CPUAccounting=yes` явно. Проверьте: `systemctl show <unit> -p CPUQuota`. |
| Контейнер завершается при старте | Отсутствует `network-online.target` или образ еще не pulled. | Добавьте `After=network-online.target`. Используйте `ExecStartPre=` для `docker pull`. |
| `Type=notify` таймаут | Приложение не отправляет READY=1 или `NotifyAccess=` ограничен. | Установите `NotifyAccess=all`. Проверьте монтирование сокета и переменную `$NOTIFY_SOCKET`. |
| Логи дублируются | Конфликт между journald и драйвером `json-file`. | Настройте `log-driver=journald` в `/etc/docker/daemon.json` для исключения дублирования. |
| `docker stop` не завершает контейнер | Процесс внутри контейнера игнорирует SIGTERM. | Увеличьте `TimeoutStopSec=` или добавьте `STOPSIGNAL SIGRTMIN+3` в Dockerfile. |
| Ошибка `cgroup: cannot set cgroup` | Используется cgroup v1 или неправильный драйвер. | Проверьте: `stat -fc %T /sys/fs/cgroup/`. Убедитесь, что Docker использует `cgroupfs` или `systemd` driver. |
| Контейнер не стартует после перезагрузки | Отсутствует `WantedBy=multi-user.target` или юнит не включен. | Выполните: `systemctl daemon-reload && systemctl enable --now app-container.service`. |
| Конфликт портов | Порт уже занят другим сервисом на хосте. | Проверьте: `ss -tlnp | grep :80`. Используйте `docker port` для проверки. |

## Рекомендации по эксплуатации (Best Practices)

1.  **Delegate всегда:** Для всех unit-файлов, запускающих Docker контейнеры, указывайте `Delegate=yes`. Без этого cgroup-лимиты Docker игнорируются в cgroup v2.
2.  **Resource limits по умолчанию:** Всегда задавайте `CPUQuota=`, `MemoryMax=`, `TasksMax=` в unit-файле. Отсутствие лимитов чревато влиянием на соседние сервисы при аварии в контейнере.
3.  **EnvironmentFile вместо аргументов:** Никогда не передавайте секреты через командную строку (`Environment="PASS=secret"`). Они попадут в `ps` и journalctl. Используйте файлы с правами `600`.
4.  **Sandboxing по умолчанию:** Включайте `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes` и `NoNewPrivileges=yes` для всех production-юнитов. Развивайте культуру минимальных привилегий.
5.  **ExecStartPre для валидации:** Добавляйте проверки образа, дискового пространства и зависимостей в `ExecStartPre=`. Это предотвращает падение юнита с непонятной ошибкой midway.
6.  **Graceful shutdown:** Используйте `docker stop -t <seconds>` с запасом времени на graceful shutdown приложения. Настройте `TimeoutStopSec=` с учетом времени shutdown приложения.
7.  **Логирование через journald:** Настройте Docker daemon на использование драйвера `journald`. Это обеспечивает единое хранилище логов и корреляцию с другими сервисами через `journalctl -u`.
8.  **Slice для группировки:** Для многоконтейнерных приложений создавайте отдельный slice (например, `app.slice`) с общими лимитами, а не задавайте одинаковые лимиты на каждый юнит.
9.  **Валидация unit-файлов:** Перед применением запускайте `systemd-analyze verify app-container.service` для проверки синтаксиса и `systemd-analyze plot > graph.svg` для визуализации зависимостей.
10. **Избегайте `Restart=always` в Docker Compose:** При использовании systemd для управления жизненным циклом отключайте `restart: always` в Compose-файле. Это предотвращает конфликты при попытке Docker перезапустить контейнер, пока systemd считает его упавшим.

## Ограничения и крайние случаи (Edge Cases)

### Поведение при перезагрузке

Unit-файлы systemd выживают перезагрузку, но состояние контейнеров (запущенные/остановленные) — нет. Для автоматического запуска после boot:

```bash
systemctl enable --now app-container.service
```

Если контейнер требует определенного порядка загрузки (например, NFS или RAID), добавьте `After=network-online.target` и `Wants=network-online.target`.

### Поведение при завершении родительского процесса

При ручной остановке unit'а (`systemctl stop`) systemd вызывает `ExecStop=` и дожидается завершения `docker stop`. Если shell, из которого был запущен `systemctl`, завершается раньше, это не влияет на сервис — он управляется PID 1.

### Cgroup driver conflict

Docker поддерживает два драйвера cgroup: `cgroupfs` и `systemd`. При использовании `Delegate=yes` и `Type=notify` предпочтителен драйвер `systemd`:

```bash
# Проверка текущего драйвера
docker info | grep -i "cgroup driver"
# → Cgroup Driver: systemd

# Настройка в /etc/docker/daemon.json
{
  "exec-opts": ["native.cgroupdriver=systemd"]
}
```

После изменения требуется `systemctl restart docker`.

### Драйверы storage и overlay

При использовании `overlay2` (по умолчанию) на системах с `ProtectSystem=strict` убедитесь, что каталоги Docker (`/var/lib/docker`, `/var/run/docker`) монтируются как tmpfs или доступны через volume. Иначе `docker run` завершится с ошибкой записи.

### Взаимодействие с SELinux/AppArmor

* **SELinux:** В enforcing-режиме может блокировать запись Docker в cgroup-файлы. Проверяйте логи: `ausearch -m avc -ts recent | grep docker`.
* **AppArmor:** Профиль `docker-default` может конфликтовать с `SystemCallFilter=` в unit-файле. При ошибках проверяйте: `journalctl -u app-container.service | grep DENIED`.

### Поведение при нехватке памяти

Если `MemoryMax=` превышен, OOM Killer убивает процессы внутри cgroup контейнера. Docker помечает контейнер как `OOMKilled`. При использовании `Restart=on-failure` systemd перезапустит контейнер. Для тонкой настройки используйте `MemoryHigh=` (мягкий лимит с троттлингом) вместо только `MemoryMax=`.

### Docker-in-Docker vs внешнее управление

Запуск полного Docker daemon внутри контейнера (DinD) требует `--privileged` или явного предоставления `SYS_ADMIN` и доступа к cgroups. Это отдельный сценарий, не overlapping с внешним управлением через systemd. Подробнее: **[Systemd в Docker](../../Docker/docker_systemd.md)**.

## Очистка и обслуживание

### Удаление юнитов и контейнеров

```bash
# Остановка и отключение юнита
sudo systemctl stop app-container.service
sudo systemctl disable app-container.service

# Удаление unit-файла
sudo rm /etc/systemd/system/app-container.service
sudo systemctl daemon-reload

# Принудительная остановка и удаление контейнера
sudo docker stop -t 10 app-container
sudo docker rm -f app-container
```

### Удаление завершенных transient-юнитов

```bash
# Сброс failed-юнитов (очищает список)
sudo systemctl reset-failed

# Принудительная остановка и удаление lingering-юнитов
sudo systemctl stop backup-now.service
sudo systemctl reset-failed backup-now.service
```

### Ротация логов journald

```bash
# Просмотр размера журналов
journalctl --disk-usage

# Очистка логов старше 7 дней
sudo journalctl --vacuum-time=7d

# Ограничение размера журналов 500MB
sudo journalctl --vacuum-size=500M
```

### Очистка Docker ресурсов

```bash
# Удаление остановленных контейнеров, неиспользуемых сетей и образов
sudo docker system prune -f

# Удаление неиспользуемых volumes (осторожно!)
sudo docker volume prune -f

# Полная очистка (образы, контейнеры, volumes, кэш)
sudo docker system prune -a --volumes -f
```

### Поиск orphaned ресурсов

```bash
# Юниты в состоянии failed или exited, которые остались из-за отсутствия --collect
systemctl --failed --type=service --no-legend | awk '{print $1}' | grep '^run-'

# Неиспользуемые образы Docker
sudo docker images -f "dangling=true" -q

# Контейнеры, не принадлежащие активным unit'ам
docker ps -a --filter "status=exited" --format "{{.Names}}"
```

## Дополнительная информация

### Сравнение с нативной интеграцией Podman

В отличие от Docker, **Podman** предлагает более совершенную интеграцию через генератор **Quadlet**. Он исключает необходимость ручного написания сложных `ExecStartPre`, автоматически обрабатывая зависимости и жизненный цикл.
Подробнее: **[Podman: Автообновление и Quadlet](../../../Podman/podman_auto_update.md)**.

### Анти-паттерны

*   **Использование `Restart=always` в Docker и в Systemd одновременно:** Может привести к конфликтам при попытке Docker перезапустить контейнер, пока systemd считает его упавшим. Рекомендуется отключать `restart: always` в Docker при использовании systemd.
*   **Systemd внутри Docker:** Запуск systemd как PID 1 внутри контейнера — это отдельная задача со своими рисками. Подробнее см. **[Systemd в Docker](../../../Docker/docker_systemd.md)**.
*   **Отсутствие `Delegate=yes` при использовании cgroup v2:** Без делегирования Docker не может управлять под-cgroups, и лимиты, заданные через `docker run`, игнорируются.
*   **Передача секретов через командную строку:** `docker run -e PASSWORD=secret` делает секрет видимым в `ps aux` и journalctl. Используйте `--env-file` или `docker secret` (Swarm) / внешние vault'ы.
*   **Использование `--privileged` вместо точечных capabilities:** Дает контейнеру все права, сводя на нет изоляцию. Вместо этого добавляйте только необходимые capabilities через `--cap-add`.

### См. также

* [Обзор юнитов systemd](./systemd_units_overview.md) — базовые типы и логика.
* [Журналирование (journald)](../../SystemAdministration/Logging/journald.md) — работа с логами.
