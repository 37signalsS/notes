# Podman: Бездемонная (Daemonless) архитектура

> Актуально для: Podman 6.x

## Определения

**Бездемонная архитектура (Daemonless Architecture)** — модель управления контейнерами, исключающая наличие центрального фонового процесса (демона) с правами суперпользователя. В Podman каждая команда является независимым процессом, что устраняет единую точку отказа и повышает безопасность. В отличие от Docker, где вся работа идет через постоянно работающий `dockerd`, в Podman нет ни одного длительно живущего процесса, который бы принимал команды.

**Модель Fork/Exec** — классическая Unix-модель порождения процессов. В Podman контейнеры не являются "клиентами" демона, а становятся прямыми потомками процесса, который их запустил (или передаются под управление менеджера системных служб). После запуска контейнера роль родителя переходит к **conmon**, поэтому CLI-процесс может завершиться, не останавливая контейнер.

**conmon (Container Monitor)** — легковесная утилита на языке C, выступающая в роли монитора жизненного цикла контейнера. Обязанности conmon:

- удержание стандартных потоков (STDIN/STDOUT/STDERR) контейнера и перенаправление их в лог-файлы;
- удержание TTY (если контейнер запущен с `-t`/`--tty`);
- фиксация кода завершения основного процесса контейнера и его проброс наружу (поэтому `podman run` возвращает именно код выхода контейнера);
- резервирование проброшенных портов на время жизни контейнера (опция `enable_port_reservation` в `containers.conf`);
- выполнение роли MAINPID для systemd при `Type=notify` (готовность контейнера сообщается через `sdnotify`).

Conmon порождается **на каждый контейнер** (и на каждый `podman exec`), а не один на весь движок. Тот же conmon используется CRI-O, что подтверждает его статус стандартного компонента OCI-экосистемы.

**conmon-rs** — высокопроизводительная реализация монитора на языке Rust (проект `containers/conmon-rs`). Ее архитектурное отличие: **один экземпляр на весь под** вместо одного на контейнер, что снижает потребление памяти (целевой RSS 3–4 МБ) и позволяет переиспользовать процесс для `exec` без повторного порождения. По состоянию на Podman 6.x conmon-rs находится в стадии оценки и внедрения (Red Hat RUN-1945, пропозиция Podman 6 в Fedora), а по умолчанию продолжает использоваться C-версия conmon.

**OCI Runtime (Среда выполнения)** — низкоуровневая утилита, которая непосредственно взаимодействует с ядром Linux для настройки пространств имен (Namespaces), контрольных групп (Cgroups), монтирований и создания процесса контейнера. Стандартными реализациями являются **crun** (C, используется по умолчанию) и **runc** (Go). Порядок поиска runtime по умолчанию в `containers.conf`: `crun` → `runc` → `runj` → `kata` → `runsc` → `ocijail`. Выбор runtime также возможен флагом `--runtime`, настройкой `[engine] runtime` в `containers.conf` или аннотацией образа `io.containers.runtime`.

**Pause-процесс** — отдельный процесс в rootless-режиме, который удерживает user namespace живым после выхода запускающего процесса. Без него все unprivileged-контейнеры пользователя были бы разрушены, когда завершается процесс, создавший пространство имен.

---

## Основные концепции

### Жизненный цикл процесса (Цепочка запуска)

Когда пользователь выполняет команду `podman run`, запускается следующая цепочка событий:

1. **Podman CLI**: Считывает конфигурацию, проверяет наличие образа (при необходимости выполняет pull), создает слои хранилища и подготавливает спецификацию OCI.
2. **conmon**: Podman порождает процесс `conmon`. Он становится "родителем" для контейнера и остается в памяти, даже если CLI-процесс завершится.
3. **OCI Runtime**: `conmon` вызывает среду выполнения (по умолчанию `crun`).
4. **Контейнер**: Рантайм настраивает изоляцию в ядре (namespaces, cgroups, монтирования) и запускает приложение. После старта рантайм завершается, оставляя `conmon` наблюдать за процессом.

Ключевое следствие: даже при использовании `-d` (detached) или выходе из оболочки контейнер продолжает работать — его родителем остается `conmon`, а не пользовательская сессия. В системах с systemd родителем conmon становится сам systemd, который управляет жизненным циклом контейнера как обычным сервисом.

### Модульные компоненты (Ecosystem)

Podman делегирует задачи специализированным инструментам, следуя философии Unix:

| Компонент | Роль |
| :--- | :--- |
| **Buildah** | Сборка образов из Containerfile. |
| **Skopeo** | Инспекция образов, копирование и работа с реестрами. |
| **Netavark + Aardvark-dns** | Сетевой стек: настройка интерфейсов, бриджей и правил файрвола (Netavark) и разрешение имен внутри пользовательских сетей (Aardvark). В Podman 6.x обязательны версии 2.0. |
| **Pasta** | Сетевой бэкенд rootless-режима (по умолчанию с Podman 5.0) и проброс портов. |
| **gvproxy** | User-mode networking для `podman machine` (macOS, Windows) и rootless-режима. |
| **pinns** | Создание пространств имен для подов (PID, IPC, UTS). |
| **SQLite** | Хранилище метаданных (с Podman 4.9 для новых установок, с 6.0 — единственный бэкенд). |

**Изменения в Podman 6.0** (важно для обновления): удалены поддержка **CNI**-сетей (остался только Netavark), файрвол **iptables** (используется nftables), сетевое окружение **slirp4netns** (заменено на Pasta) и поддержка **cgroups v1**. Изоляция сети теперь включена по умолчанию, что улучшает совместимость с Docker API.

### Интеграция с systemd и Quadlet

Поскольку Podman не имеет собственного демона-планировщика, он использует **systemd** как нативный оркестратор для одиночных узлов. Контейнеры регистрируются в иерархии cgroups systemd (`--cgroup-manager=systemd` — значение по умолчанию), поэтому управляются стандартными средствами: `systemctl`, `journalctl`, лимиты ресурсов, зависимости.

**Quadlet** — генератор systemd-юнитов. Декларативные файлы (расширения `.container`, `.pod`, `.volume`, `.network`, `.image`, `.kube`, `.build`, `.artifact`) размещаются в каталогах поиска, и systemd при загрузке/`daemon-reload` автоматически преобразует их в `.service`-юниты:

- rootful: `/run/containers/systemd/`, `/etc/containers/systemd/`, `/usr/share/containers/systemd/` (приоритет сверху вниз);
- rootless: `$XDG_RUNTIME_DIR/containers/systemd/`, `~/.config/containers/systemd/` (или `$XDG_CONFIG_HOME/containers/systemd/`), а также системные каталоги `.../users/${UID}`.

Преимущества по сравнению с запуском "вручную": автоматический перезапуск, управление зависимостями, лимиты ресурсов и сбор логов в `journald`. Поддерживаются drop-in-каталоги в стиле systemd (`имя_юнита.d/`), позволяющие расширять конфигурацию без правки исходного файла.

**Ready-уведомления (sdnotify):** для сервисов с `Type=notify` Podman сообщает systemd о готовности контейнера. Поведение задается флагом `--sdnotify`:

- `container` (по умолчанию) — сокет `NOTIFY_SOCKET` пробрасывается в контейнер, готовность приходит от приложения; MAINPID указывает на conmon;
- `conmon` — conmon сам шлет `READY` после старта контейнера, сокет в контейнер не передается;
- `ignore` — `NOTIFY_SOCKET` игнорируется (полезно, когда Podman вызывается из другого сервиса, использующего sdnotify).

**Альтернатива (легаси):** команда `podman generate systemd` создает классические юниты из запущенных контейнеров. Quadlet считается рекомендованным подходом для продакшена.

### Хранение состояния (SQLite)

Podman хранит метаданные контейнеров, подов и томов в локальной базе данных (сами данные томов и слои образов — в файловой системе хранилища).

- **Podman 4.9**: SQLite стала базой данных по умолчанию для новых установок.
- **Podman 5.x**: BoltDB объявлена устаревшей, создание новых BoltDB-баз запрещено (существующие продолжали работать); выводилось предупреждение о необходимости миграции.
- **Podman 6.0**: поддержка BoltDB полностью удалена; при первом запуске Podman выполняет **автоматическую миграцию** BoltDB → SQLite. Для контролируемой миграции (например, на больших серверах) существует команда `podman system migrate --migrate-db`.

```bash
# Проверка текущего бэкенда базы данных
podman info --format '{{.Host.DatabaseBackend}}'
# → sqlite
```

Параметр `database_backend` в `containers.conf` (`[engine]`) позволяет явно выбрать `boltdb` или `sqlite` (пустое значение — "использовать существующую, иначе sqlite"). Перед сменой бэкенда рекомендуется выполнить `podman system reset`.

**Драйверы хранилища и особенности daemonless:**

| Драйвер | Где используется | Особенности в daemonless-контексте |
| :--- | :--- | :--- |
| **overlay** | По умолчанию на большинстве дистрибутивов | Поддерживает hard links; не требует дополнительных mount-операций при запуске. В rootless-режиме требует `fuse-overlayfs` если kernel не поддерживает unprivileged overlay mounts. |
| **vfs** | Fallback, отладка | Каждый слой — отдельная копия файлов. Медленнее, но не требует специальных mount-прав. Полезен на файловых системах без overlay support (например, NFS в старых ядрах). |
| **btrfs** | Специализированные хосты | Использует built-in snapshot. Может потребовать `user_subvol_rm_allowed` для rootless. |
| **zfs** | Специализированные хосты | Аналогично btrfs, но через ZFS datasets. В daemonless-контексте работает идентично — mount выполняется рантаймом, не демоном. |

```bash
# Проверка текущего драйвера хранилища
podman info --format '{{.Store.GraphDriverName}}'
# → overlay

# Проверка backing filesystem для хранилища
df -T ~/.local/share/containers/storage
# → overlay on /dev/nvme0n1p2 type ext4 (1.8T)
```

**Важно:** В daemonless-архитектуре mount-операции выполняет рантайм (`crun`) от имени запустившего пользователя, а не центральный демон. Это означает:
- В rootless-режиме mount-point принадлежит пользователю, и его cleanup происходит при завершении conmon.
- При падении хоста или kill -9 контейнера mount-точки могут оставаться "висячими" до перезагрузки или ручного `podman system prune`.

### Docker API-совместимость (Socket)

Для инструментов, которые не могут работать без сокета (Docker Desktop расширения, старые CI-агенты, docker-compose), Podman предоставляет REST API, совместимый с Docker Engine (в Podman 6.x — версия совместимого API **v1.44**).

Ключевое свойство: сокет активируется systemd по требованию. Процесс `podman system service`, обслуживающий запросы, **не живет постоянно** — он поднимается при первом обращении к сокету и завершается после периода простоя. Это сохраняет "бездемонность" архитектуры: фоновый процесс существует только пока в нем есть потребность.

---

## Практические сценарии

### 1. Анализ дерева процессов

Вы можете убедиться в отсутствии демона, проследив иерархию процессов. В отличие от Docker, где родителем всегда является `dockerd`, здесь вы увидите `conmon`:

```bash
# Запуск контейнера в фоне
podman run -d --name web-test nginx:alpine

# Поиск монитора и процесса приложения
ps -ef --forest | rg -A 2 'conmon'
# → 1000  12345     1  0  conmon --api-version ...
# → 1000  12346 12345  0  \_ nginx: master process ...
# → 1000  12347 12346  0      \_ nginx: worker process
```

PPID=1 у conmon означает, что контейнер "пережил" запустивший его CLI-процесс и был переподчинен системному процессу. Никакого центрального демона в дереве нет.

### 2. Декларативное управление через Quadlet

Рекомендуемый способ запуска сервисов в продакшене.

**Файл:** `~/.config/containers/systemd/web.container`
```ini
[Unit]
Description=Nginx Production Service

[Container]
Image=docker.io/library/nginx:latest
PublishPort=80:80
AutoUpdate=registry
CgroupsMode=no-conmon

[Install]
WantedBy=default.target
```

После создания файла выполните:

```bash
systemctl --user daemon-reload
systemctl --user start web.service

# Проверка состояния и логов
systemctl --user status web
journalctl --user -u web -f
```

Пояснения:
- `AutoUpdate=registry` транслируется в метку образа `io.containers.autoupdate=registry` — контейнер будет обновляться через `podman auto-update` (см. **[Автообновление в Podman](./podman_auto_update.md)**).
- `CgroupsMode=no-conmon` соответствует `--cgroups=no-conmon` и запрещает создание отдельной cgroup для conmon (экономия, когда это не требуется).
- Имена сгенерированных юнитов совпадают с именами файлов Quadlet: `web.container` → `web.service`.

### 3. Эмуляция Docker API (Socket)

Для инструментов, работающих только через сокет Docker:

```bash
# Включение сокета (процесс system service поднимается по требованию)
systemctl --user enable --now podman.socket

# Проверка работоспособности
export DOCKER_HOST="unix://$XDG_RUNTIME_DIR/podman/podman.sock"
docker info | grep -i runtime
# → Runtime: crun
```

Rootful-вариант (системный сокет):

```bash
sudo systemctl enable --now podman.socket
export DOCKER_HOST="unix:///run/podman/podman.sock"
docker ps
```

Работа через REST API напрямую:

```bash
curl --unix-socket "$XDG_RUNTIME_DIR/podman/podman.sock" \
  http://localhost/v1.44/containers/json
```

Благодаря совместимости API с Docker здесь работают `docker compose` (через `podman compose` с внешним провайдером) и инструменты, ожидающие docker-сокет. Разница в архитектуре: за сокетом нет постоянно работающего демона, сервис стартует по запросу systemd.

### 4. Жизненный цикл и выходной код

**Проброс кода выхода.** conmon фиксирует код завершения основного процесса и передает его наружу, поэтому `podman run` возвращает код именно контейнера:

```bash
podman run --rm alpine sh -c 'exit 42'
echo $?
# → 42
```

**Живучесть после выхода CLI.** Контейнер в фоне продолжает работу, когда запускающая сессия закрыта (роль родителя выполняет conmon):

```bash
podman run -d --name persistent nginx:alpine

# в новой сессии контейнер по-прежнему виден и работает
podman ps --filter name=persistent --format '{{.Names}} {{.Status}}'
# → persistent Up 10 seconds
```

**Миграция базы данных (Podman 6.0).** Если после обновления требуется контролируемая миграция BoltDB → SQLite:

```bash
# Остановить systemd-активируемые сервисы (podman system service, Quadlet)
# и выполнить миграцию
podman system migrate --migrate-db

# Контроль результата
podman info --format '{{.Host.DatabaseBackend}}'
# → sqlite
```

### 5. Диагностика жизненного цикла (conmon и процессы)

При отсутствии центрального демона диагностика строится вокруг `conmon` и systemd:

```bash
# Поиск conmon для конкретного контейнера
CONMON_PID=$(podman inspect --format '{{.State.ConmonPid}}' web-test)
ps -fp $CONMON_PID -o pid,ppid,cmd

# Проверка PPID: должен быть 1 (systemd) или pid systemd --user
# → PID TTY      STAT   TIME COMMAND
# → 12345 ?        Ss     0:00 /usr/bin/conmon ...

# Просмотр открытых файловых дескрипторов conmon
ls -la /proc/$CONMON_PID/fd

# Проверка, что контейнер "уже не зависит" от CLI-процесса
podman run -d --name orphan-test nginx:alpine
CLI_PID=$!
sleep 2
kill $CLI_PID 2>/dev/null
podman ps --filter name=orphan-test
# → orphan-test Up ... (жив, хотя CLI-процесс убит)
```

**Диагностика через systemd (rootless):**

```bash
# Проверка статуса юнита
systemctl --user status web.service

# Просмотр полного ExecStart (включая --sdnotify, --cgroups)
systemctl --user cat web.service | grep ExecStart
# → ExecStart=/usr/bin/podman run ... --sdnotify=container ...

# Проверка MAINPID (должен указывать на conmon)
systemctl --user show web.service -p MainPID --value
# → 12345
```

### 6. Ограничение ресурсов в Quadlet

В daemonless-архитектуре все лимиты применяются через cgroups systemd. В Quadlet ресурсы задаются в секции `[Container]` или через drop-in к секции `[Service]`:

```ini
# Файл: ~/.config/containers/systemd/web.container
[Unit]
Description=Web with resource limits
After=network-online.target
Wants=network-online.target

[Container]
Image=docker.io/library/nginx:alpine
PublishPort=80:80
Cpus=2
Memory=1g
MemorySwap=1.5g
PidsLimit=256
# Дополнительные лимиты через drop-in или cgroupfs параметры
# annotation io.resourcepolicy=... (зависит от версии Podman)

[Install]
WantedBy=default.target
```

```bash
# Проверка примененных cgroup-лимитов
systemctl --user show web.service -p CPUQuotaPerSecUSec --value
# → 2000000us (2 CPUs)

# Просмотр live cgroup-иерархии
systemd-cgtop -b -n 1
# → Control Group                            CPU  Memory
# → user.slice/user@1000.service/...          0.5%  80M

# Проверка memory.max (cgroup v2)
cat /sys/fs/cgroup/user.slice/user@1000.service/.../memory.max
# → 1073741824
```

**Важно:** `MemorySwap` в Quadlet транслируется в `--memory-swap` CLI, что ограничивает общую память + swap. При `--cgroup-manager=systemd` Podman делегирует контроль cgroup systemd, и ручная правка cgroup-путей может конфликтовать с юнитом.

### 7. Централизованный сбор логов

В daemonless-архитектуре логи контейнеров направляются в `journald` (при использовании systemd/Quadlet) или в stdout/stderr CLI-процесса. Централизованный сбор требует настройки на уровне ОС:

```bash
# Логи конкретного контейнера через journalctl (rootless)
journalctl --user -u web.service --since "1 hour ago" -o json-pretty

# Фильтр по приоритету (ERROR и выше)
journalctl --user -u web.service -p err --since today

# Поиск по содержимому
journalctl --user -u web.service --grep "timeout"

# Persistent storage для rootless юнитов
# По умолчанию journald в user-mode хранит логи в /var/log/journal/
# Если Storage=volatile, логи теряются после перезагрузки
mkdir -p ~/.local/share/journal
journalctl --user --flush
```

**Для rootful-сервисов:**

```bash
journalctl -u web.service --since "1 hour ago" -f
```

### 8. Аудит событий и compliance

Без центрального демона аудит строится на `podman events` и journald:

```bash
# Поток событий в реальном времени (create, start, stop, die, kill)
podman events --filter event=create,start,stop,died,kill --format '{{.Time}} {{.Event}} {{.Actor}}'

# Аудит запуска контейнеров за последний час
podman events --filter event=start --since 1h --format '{{.Time}} {{.Actor}} {{.PID}}'

# Поиск контейнеров без метки io.containers.autoupdate (compliance)
podman ps --filter label=!io.containers.autoupdate --format '{{.Names}}'

# Проверка использования секретов (должны быть только через secret, не env)
podman inspect $(podman ps -q) --format '{{range .HostConfig.Env}}ENV: {{.}}{{"\n"}}{{end}}'
```

---

## Устранение неполадок

### Типичные ошибки daemonless-архитектуры

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| Контейнер завершается сразу после `podman run -d` | Приложение упало, или HEALTHCHECK не настроен при `--sdnotify=healthy` | Проверить `podman logs <name>`; при `sdnotify=healthy` добавить `HealthCmd` в Quadlet или CLI |
| `systemctl --user start` зависает в `activating` | `NOTIFY_SOCKET` не получен, таймаут `TimeoutStartSec` | Проверить, что приложение поддерживает sdnotify, или переключить на `--sdnotify=conmon` |
| `podman events` не показывает события | `events_logger` не настроен, или используется `cgroupfs` вместо `systemd` | Проверить `events_logger=file` или `journald` в `containers.conf` |
| Контейнер "висит" в `stopped` после `podman stop` | conmon не завершился, или остались зависшие процессы | `podman rm -f <name>`; проверить `ps aux | grep conmon` |
| `podman system service` не поднимается | `dbus-user-session` не запущен (rootless) или сокет не активен | `systemctl --user enable --now podman.socket`; убедиться, что `XDG_RUNTIME_DIR` корректен |
| Rootless-контейнер исчез после logout | pause-процесс убит при завершении сессии | Включить `loginctl enable-linger $USER` для серверных узлов |
| `Error: short-name` при pull | Реестр не настроен, не указан FQIN | Использовать `docker.io/library/nginx:alpine` или настроить `registries.conf` |
| `cgroup` ограничения не применяются | `--cgroup-manager=cgroupfs` вместо `systemd` | Переключить на `systemd` или задать `--cgroups=enabled` |

### Диагностические команды

```bash
# Быстрый health-check daemonless-окружения
echo "=== Database backend ==="
podman info --format '{{.Host.DatabaseBackend}}'

echo "=== Storage driver ==="
podman info --format '{{.Store.GraphDriverName}}'

echo "=== Cgroup manager ==="
podman info --format '{{.Host.CgroupManager}}'

echo "=== Conmon processes ==="
pgrep -a conmon

echo "=== Systemd user session ==="
systemctl --user show | grep -E 'MainPID|SubState|ActiveState'

echo "=== Socket activation ==="
systemctl --user status podman.socket

echo "=== Recent events ==="
podman events --filter event=start,stop,died --since 5m --format '{{.Time}} {{.Event}} {{.Actor}} {{.Status}}'
```

### Логирование и audit trail

```bash
# Журнал systemd-юнита (rootless)
journalctl --user -u web.service --since "2 hours ago" -o short-iso

# Поиск ошибок в journald
journalctl --user -u web.service -p err --since today | tail -20

# Экспорт метрик conmon (вручную через /proc)
CONMON_PID=$(podman inspect --format '{{.State.ConmonPid}}' web-test)
cat /proc/$CONMON_PID/status | grep -E 'VmRSS|Threads|voluntary'

# Мониторинг в реальном времени
podman events --filter event=start,stop,died,kill --format '{{.Time}} {{.Event}} {{.Actor}}' --since 1m
```

## Best practices для SRE/Sysadmin

### Проектирование production-окружения

1. **Используйте Quadlet для всех сервисов.** Внешние `podman run` команды несовместимы с автообновлением, audit и централизованным управлением. Размещайте `.container`-файлы в `/etc/containers/systemd/` (rootful) или `~/.config/containers/systemd/` (rootless).

2. **Используйте FQIN (Fully Qualified Image Name) с digest.** Короткие теги (`latest`) ненадежны в продакшене:
   ```ini
   [Container]
   Image=docker.io/library/nginx@sha256:abc123...
   ```

3. **Настройте `sdnotify` корректно.** Для приложений с длительной инициализацией используйте `Notify=healthy` + `HealthCmd` вместо `Notify=conmon`, чтобы systemd не считал сервис готовным до фактической готовности приложения.

4. **Включите `AutoUpdate=registry`** только для staging-сред. В production обновления должны проходить через CI/CD pipeline с предварительным тестированием.

5. **Разделите rootful и rootless зоны.** Rootful — для системных сервисов, требующих привилегий (проброс портов <1024, настройка сети). Rootless — для пользовательских рабочих нагрузок.

### Мониторинг и алертинг

```bash
# Базовый мониторинг: failed/unhealthy контейнеры
FAILED=$(podman ps --filter health=unhealthy --format '{{.Names}}')
if [ -n "$FAILED" ]; then
  echo "ALERT: unhealthy containers: $FAILED"
fi

# Проверка, что Quadlet-юниты в desired state
systemctl --user list-units --type=service --state=failed | grep podman

# Мониторинг дискового пространства хранилища
podman system df
df -h ~/.local/share/containers/storage
```

### Резервное копирование и disaster recovery

```bash
# Экспорт метаданных (SQLite) для disaster recovery
cp ~/.local/share/containers/storage/containers.db ~/backups/

# Экспорт запущенных контейнеров в YAML
podman generate kube running-container > backup.yaml

# Восстановление из backup
podman play kube backup.yaml
```

### Compliance checklist

- [ ] Все production-сервисы управляются через Quadlet (systemd)
- [ ] Используются `io.containers.autoupdate=registry` только где explicitly одобрено
- [ ] `--cap-drop=ALL` с явным добавлением только необходимых capabilities
- [ ] `--security-opt no-new-privileges` для всех production-контейнеров
- [ ] `Memory` и `Cpus` заданы в Quadlet для каждого сервиса
- [ ] Логи направлены в journald (`--log-driver=journald` для rootful)
- [ ] `podman events` агрегируется в SIEM (Filebeat, Fluentd, или journald remote)
- [ ] `pods` используются для tightly-coupled сервисов, share network namespace

### Инцидент-респонс (SRE playbook)

**Сценарий 1: Контейнер в `CrashLoopBackOff`-подобном состоянии**

```bash
# 1. Проверить статус и код выхода
podman ps -a --filter name=my-app
podman inspect my-app --format '{{.State.ExitCode}} {{.State.Error}}'

# 2. Проверить логи через journald (не docker logs!)
journalctl --user -u my-app.service --since "10 minutes ago"

# 3. Проверить события
podman events --filter container=my-app --since 10m

# 4. При необходимости — перезапуск через systemd (не podman start!)
systemctl --user restart my-app.service
```

**Сценарий 2: Нехватка памяти (OOM)**

```bash
# 1. Проверить journald на предмет OOM-kill
journalctl --user -u my-app.service | grep -i "oom\|killed"

# 2. Проверить текущие лимиты cgroup
systemctl --user show my-app.service -p MemoryMax --value

# 3. Проверить usage
cat /sys/fs/cgroup/.../memory.current

# 4. Внедрить Memory= в Quadlet и перезапустить
systemctl --user daemon-reload
systemctl --user restart my-app.service
```

**Сценарий 3: Обновление образа с откатом**

```bash
# 1. Принудительное обновление образа
podman image pull docker.io/library/nginx:alpine

# 2. Перезапуск через systemd (атомарный)
systemctl --user restart web.service

# 3. Проверка статуса
systemctl --user status web.service

# 4. При проблемах — откат к предыдущему образу
# (используйте digest из registry или локальный tag)
podman tag nginx:alpine-previous nginx:alpine
systemctl --user restart web.service
```

### Преимущества архитектуры

1. **Безопасность**: Нет процесса с правами root, постоянно слушающего сеть или сокет. Это минимизирует поверхность атаки. Даже Docker-сокет (`podman.socket`) активируется systemd по требованию, а не работает постоянно.
2. **Изоляция сбоев**: Падение процесса Podman (например, зависшей команды) не приводит к остановке уже запущенных контейнеров — их жизненный цикл ведет conmon и/или systemd.
3. **Обновления без простоя**: Вы можете обновлять сам пакет Podman на хосте, не перезапуская запущенные сервисы (демон отсутствует, перезапускать нечего).
4. **Низкие накладные расходы**: Нет прослойки демона между CLI и runtime — цепочка `CLI → conmon → crun` короче, а служебные процессы легковесны.
5. **Прозрачность**: Процессы контейнеров видны в `ps` как обычные процессы пользователя, что упрощает диагностику и интеграцию с системами мониторинга.
6. **Мультипользовательность**: Отсутствие общего демона позволяет каждому пользователю иметь собственную изолированную среду контейнеров (основа rootless-режима, см. **[Rootless режим](./podman_rootless.md)**).

### Ограничения и подводные камни

- **Нет встроенного автоперезапуска**: контейнер, запущенный "вручную" вне systemd, не будет перезапущен после падения. Для сервисов обязателен systemd/Quadlet.
- **Conmon на контейнер**: каждый контейнер и каждый `podman exec` сопровождаются собственным процессом conmon (небольшой оверхед памяти; при желании отключается `--cgroups=no-conmon` для отдельной cgroup, но сам conmon по-прежнему создается).
- **События и логи неагрегированные**: в отсутствие постоянно работающего процесса события записываются в файл/journald и читаются командой `podman events`; централизованная доставка требует поднять сервис.
- **Rootless и user namespace**: контейнеры живут в user namespace, который удерживается pause-процессом; при изменении `/etc/subuid`/`/etc/subgid` требуется пересоздать namespace (`podman system migrate` или перезапуск контейнеров).
- **Совместимость API не 100%**: Docker-совместимый REST API покрывает основные операции, но не все возможности Docker Engine; отдельные расширенные сценарии могут потребовать нативного Podman CLI.

### Связанные разделы
- **[Rootless режим](./podman_rootless.md)** — как бездемонная архитектура позволяет работать без прав root.
- **[Podman vs Docker](./podman_vs_docker.md)** — фундаментальное сравнение моделей управления.
- **[Сетевой стек Podman](./podman_pods.md)** — архитектура сетевого взаимодействия (Netavark, Aardvark, Pasta).

### Ссылки
- **[podman-systemd.unit](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)** (англ.) — форматы Quadlet-юнитов, каталоги поиска, доступные ключи.
- **[podman generate systemd](https://docs.podman.io/en/latest/markdown/podman-generate-systemd.1.html)** (англ.) — легаси-генерация systemd-юнитов из контейнеров.
- **[podman system service](https://docs.podman.io/en/latest/markdown/podman-system-service.1.html)** (англ.) — REST API, совместимый с Docker.
- **[conmon-rs Repository](https://github.com/containers/conmon-rs)** — монитор на Rust (один экземпляр на под).
- **[Podman 5.0: SQLite и Pasta по умолчанию](https://blog.podman.io/2024/03/podman-5-0-has-been-released/)** (англ.) — изменения бэкендов в 5.0.

### Сравнение с Docker для системных администраторов

| Аспект | Docker (daemon) | Podman (daemonless) |
| :--- | :--- | :--- |
| **Единая точка отказа** | `dockerd` — при падении все контейнеры теряют управление | Нет единого процесса; каждый контейнер автономен |
| **Прослушивание портов** | Демон слушает сокет; socket activation через systemd возможен, но не нативен | Сокет активируется systemd по требованию (socket activation — нативная модель) |
| **Логи** | JSON-файлы в `/var/lib/docker/containers/` или драйверы (`journald`, `fluentd`) | По умолчанию в journald (через systemd) или stdout/stderr CLI |
| **Мониторинг** | `docker stats` через демон; cAdvisor/Node Exporter обращаются к `/proc` | `podman stats` напрямую читает cgroups; `systemd-cgtop` для systemd-управляемых |
| **Обновление** | Требует перезапуск демона (`systemctl restart docker`), краткий downtime | `podman system migrate` без перезапуска контейнеров; пакет обновляется на лету |
| **Пользователи** | Один демон на хост (rootful) или rootlesskit (отдельный пользовательский демон) | Каждый пользователь имеет собственную среду; no shared daemon |
| **Аудит** | Аудит через демон или API-вызовы | Аудит через `podman events` + journald; каждое событие записывается в user-space |

**Для sysadmens, мигрирующих с Docker:**
- Нет `docker.service` для мониторинга — вместо него следите за `podman.socket` и `podman-auto-update.timer`
- Логи не в `/var/lib/docker` — используйте `journalctl -u <unit>` или `~/.local/share/containers/storage/`
- `docker info` ↔ `podman info`; `docker stats` ↔ `podman stats` (одинаковый синтаксис)
- Запуск контейнеров: `docker run` ↔ `podman run` (CLI-совместимость высокая, но архитектурные различия влияют на оркестрацию)

### События и наблюдаемость

В отсутствие центрального демона агрегация событий строится на двух уровнях:

1. **`podman events`** — поток событий из SQLite-хранилища (create, start, stop, die, kill, health_status, exec и др.). Поддерживает фильтры по типу события, контейнеру, образу, label.
2. **`journald`** — логи контейнеров (stdout/stderr) и системные сообщения Podman записываются в journald при использовании systemd/Quadlet.

```bash
# Мониторинг всех событий в реальном времени
podman events --format '{{.Time}} {{.Event}} {{.Actor}} {{.Status}}' --since 1m

# Фильтр: только старты и остановки конкретного контейнера
podman events --filter event=start,stop,died --filter container=my-app --since 1h

# Агрегация journald (rootless)
journalctl --user -u my-app.service --since "1 hour ago" -o json

# Экспорт в SIEM: настроить journald remote (systemd-journal-remote) или
# использовать Filebeat с модулем journald для отправки в Elasticsearch
```

**Конфигурация `events_logger` в `containers.conf`:**

```ini
[engine]
events_logger = "journald"  # или "file", "k8s-file"
```

При `events_logger=journald` события дублируются в journald, что упрощает корреляцию с системными логами. При `file` — пишутся в `~/.local/share/containers/storage/events.log`.

### Conmon-rs: текущее состояние и миграция

**conmon-rs** — альтернативная реализация монитора на Rust (`containers/conmon-rs`), разработка ведется Red Hat и сообществом. Ключевые отличия от C-версии:

- **Один экземпляр на под** вместо одного на контейнер (экономия памяти).
- **Переиспользование для `exec`** — не требуется порождение нового процесса.
- **Целевой RSS 3–4 МБ** на под против ~1 МБ на conmon C-версии.

**Статус на Podman 6.x:** conmon-rs находится в стадии оценки. По умолчанию продолжает использоваться C-версия. Для тестирования можно собрать пакет из репозитория Fedora или скомпилировать из исходников. При явном использовании conmon-rs через `containers.conf` убедитесь, что все хосты в кластере используют совместимую версию.

```ini
# containers.conf
[engine]
monitor = "conmon-rs"
```

**Риски миграции:**
- Несовместимость с существующими скриптами, парсящими вывод `podman inspect` (формат `.State.ConmonPid` может отличаться).
- Отсутствие поддержки в некоторых дистрибутивах (требуется сборка из исходников).
- CRI-O по-прежнему использует C-conmon; смешение версий в одной среде не рекомендуется.
