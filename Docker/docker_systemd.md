# Systemd в Docker — запуск и управление службами

**Актуально для:** Docker Engine 29.x (актуальный релиз — 29.8.x, сентябрь 2026), systemd 252–257, cgroup v2 (Unified Hierarchy)

> **Позиционирование.** Запуск `systemd` как PID 1 в контейнере — **не рекомендуемый для production паттерн**.
> Он расширяет поверхность атаки, требует дополнительных привилегий, ломает изоляцию cgroups и переводит
> вывод приложений из `docker logs` в собственный журнал контейнера. Область применения — узкая:
> образы, которые должны вести себя как полноценная ОС (Ansible/Molecule, CI-образы, legacy-приложения
> с поставляемыми дистрибутивом systemd-юнитами). Во всех остальных случаях используйте
> [`tini`/`dumb-init`](./Dockerfile/init_process_tini.md) или
> [`s6-overlay`/`supervisord`](./Docker_logs/docker_multi_process_logging.md).

---

## Определения

- **Systemd в Docker:** Запуск полнофункциональной системы инициализации `systemd` (`/sbin/init` или
  `/lib/systemd/systemd`) в качестве первого процесса (PID 1) внутри контейнера.
- **PID 1 (namespace init):** Первый процесс в PID namespace. Ядро Linux трактует его особо: он
  не получает стандартных обработчиков сигналов по умолчанию, обязан пожинать (`reap`) завершившиеся
  дочерние процессы и становиться приёмным родителем для сирот.
- **Init-протокол:** Неформальный контракт, который init-система ожидает от окружения: «сигнал
  завершения = остановка системы». Docker этот контракт не соблюдает — по умолчанию он всегда
  отправляет `SIGTERM`.
- **Zombie Process:** Дочерний процесс, завершивший выполнение, но не удалённый из таблицы процессов,
  потому что родитель не вызвал `wait()`/`waitpid()`.
- **Cgroup v2 (Unified Hierarchy):** Единая иерархия контрольных групп; `/sys/fs/cgroup` — единственная
  точка монтирования, все контроллеры доступны через неё.
- **Cgroup namespace:** Пространство имён, изолирующее представление иерархии cgroups внутри контейнера
  от хоста. Именно из-за него пути в `/sys/fs/cgroup` внутри контейнера перестают совпадать с путями,
  которые сообщает `/proc/<PID>/cgroup`.
- **Делегирование cgroup-поддерева (delegation):** Передача контейнеру (или конкретному юниту хоста)
  прав на запись в собственную подгруппу дерева cgroups. `systemd` **безусловно требует** прав записи
  в дерево cgroups, поэтому делегирование — обязательное условие его запуска.
- **Slice:** Юнит systemd (`foo.slice`), группирующий поддерево cgroups. Используется как безопасная
  альтернатива пробросу всей хостовой иерархии cgroups в контейнер.
- **Journald:** Служба systemd, собирающая вывод юнитов в бинарный журнал. По умолчанию пишет на диск
  или в ОЗУ (`/run/log/journal`), **а не** в stdout контейнера.
- **Console (`/dev/console`):** В контейнере — псевдотерминал, предоставляемый runtime. Docker
  создаёт `/dev/console` **только** при выделении TTY (`-t`/`--tty`). Это узкое место всех схем
  проброса журнала в `docker logs`.

---

## Основные концепции

### Почему systemd в контейнере — не паттерн по умолчанию

| Проблема | Механизм | Практическое следствие |
| :--- | :--- | :--- |
| **Нарушение принципа одного процесса** | Контейнер превращается в «микро-ВМ» | Невозможно отличить состояние конкретного приложения от состояния ОС в одном health check |
| **Сигнальный протокол** | PID 1 в контейнере не является sysvinit | `SIGTERM` не останавливает систему, нужен `SIGRTMIN+3` (см. ниже) |
| **Изоляция cgroups** | Требование прав записи в дерево cgroups | Приходится отдавать контейнеру часть хостовой иерархии cgroups |
| **Привилегии** | `CAP_SYS_ADMIN` для `mount`/`setns`, `CAP_MKNOD` для `PrivateDevices=` | Расширенная поверхность атаки; необходимость отключать seccomp-профиль |
| **Логирование** | Вывод уходит в собственный journald контейнера | `docker logs` пуст, нужна отдельная схема проброса |
| **Управление ресурсами** | systemd перехватывает создание cgroups | Ограничения Docker (`--memory`, `--cpus`) конфликтуют с `memory.high`/`CPUQuota` юнитов |
| **Package hooks при сборке** | Постредустановочные скрипты вызывают `systemctl start` | Сборка образа падает с `System has not been booted with systemd as init system (PID 1)` |

Практический совет для SRE: если прикладной код не поставляет `.service`-юниты, необходимость в
`systemd` почти никогда не оправдана. Требования к таким образам возникают обычно там, где нужно
воспроизвести поведение существующей ВМ, — и тогда правильнее выбрать виртуальную машину.

### Механизм 1: PID 1 и семантика сигналов

Это главная причина, по которой нужен `STOPSIGNAL SIGRTMIN+3`.

Docker по умолчанию отправляет `SIGTERM`, ждёт 10 секунд, затем `SIGKILL`. Для обычного приложения
это корректный протокол. Для `systemd` — нет.

Сигнал `SIGTERM`, полученный **системным менеджером, работающим как PID 1**, имеет специальную
семантику, унаследованную от sysvinit и upstart: он означает не «остановиться», а «перечитать своё
состояние». Согласно `man systemd(1)`:

> **SIGTERM** — Upon receiving this signal the systemd system manager serializes its state, reexecutes
> itself and deserializes the saved state again. This is mostly equivalent to `systemctl daemon-reexec`.

То есть `systemd` не игнорирует `SIGTERM` — он выполняет `daemon-reexec` и продолжает работать, а Docker
по истечении таймаута убивает контейнер через `SIGKILL`.

Корректный сигнал завершения для `systemd` — **`SIGRTMIN+3`**, эквивалентный `systemctl halt`.
Семейство сигналов реального времени `SIGRTMIN+N` зарезервировано менеджером:

| Сигнал | Действие |
| :--- | :--- |
| `SIGRTMIN+1` | Принудительная ротация журнала |
| `SIGRTMIN+2` | Перезапуск демона |
| **`SIGRTMIN+3`** | **Корректная остановка менеджера (halt)** |
| `SIGRTMIN+4` | Эквивалент `poweroff` |
| `SIGRTMIN+13` | Немедленный halt (без штатной последовательности) |
| `SIGTERM` | `daemon-reexec` — перезагрузка состояния, **не** остановка |

`STOPSIGNAL SIGRTMIN+3` в Dockerfile переопределяет сигнал остановки на уровне образа; эквивалентный
флаг рантайма — `docker run --stop-signal SIGRTMIN+3`. Значение понимается и Dockerfile-парсером, и
`docker run`; числовой эквивалент на Linux — `37`.

Полная механика `STOPSIGNAL` как инструкции Dockerfile разобрана в
[health_signals.md](./Dockerfile/Instructions/health_signals.md), порядок завершения контейнера —
в [container_execution.md](./Dockerfile/Docker_best_practices/container_execution.md).

### Механизм 2: почему systemd требует записи в cgroups

`systemd` создаёт cgroup для каждого запущенного юнита и каждого scope. Это не оптимизация, а часть
процесса запуска: без подгруппы в дереве cgroups юнит не стартует.

Отсюда ключевое ограничение, сформулированное в документации systemd (`docs/CGROUP_DELEGATION.md` и
[systemd.io/CONTAINER_INTERFACE](https://systemd.io/CONTAINER_INTERFACE/)): контейнеру нужно
**делегировать поддерево** дерева cgroups, и `systemd` запускается в корне этого поддерева. Он
определит, в какой группе находится, и возьмёт её под управление, не трогая ничего выше.

Дополнительное ограничение: **нельзя подменить `/sys/fs/cgroup` монтированием только поддерева**
хоста. Часть API cgroups — это `/proc/<PID>/cgroup`, который сообщает полные пути; если смонтированное
дерево не совпадает с этими путями, `systemd` падает с ошибкой вида
`Failed to create /init.scope control group`. Разрешено монтировать верхние части дерева в режиме
read-only и открывать на запись только поддерево контейнера.

**Как Docker это ломает.** На хосте с cgroup v2 Docker по умолчанию монтирует `/sys/fs/cgroup`
внутрь контейнера **в режиме read-only**. Результат:

```
Failed to create /init.scope control group: Read-only file system
[!!!!!!] Failed to allocate manager object: Read-only file system
Exiting PID 1...
```

Это ровно та ошибка, которую даёт «безопасная» конфигурация `--cgroupns=private` без дополнительных
мер. Поэтому `--cgroupns=private` сам по себе для `systemd` **недостаточен** — рабочие варианты в
разделе «Практические сценарии».

### Механизм 3: journald против `docker logs`

Здесь необходимо различать два независимых механизма, которые часто путают:

1. **Внутриконтейнерный journald.** Менеджер запускает каждый сервис со stdout/stderr, подключёнными
   к journald. Вывод уходит в бинарный журнал `/var/log/journal` или `/run/log/journal`, а **не** в
   stdout PID 1. `docker logs` показывает только то, что PID 1 пишет в свой stdout — то есть практически
   ничего.
2. **Logging driver `journald` в Docker.** Обратное направление: Docker передаёт stdout/stderr
   контейнера в **хостовый** журнал. Эта опция не имеет отношения к systemd внутри контейнера и не
   решает проблему из пункта 1 — см.
   [docker_logging_drivers_overview.md](./Docker_logs/docker_logging_drivers_overview.md).

Способы вернуть вывод сервисов в `docker logs` разобраны в разделе «Перенаправление вывода сервисов».

### Сравнение систем инициализации

| Характеристика | systemd (внутри) | tini / dumb-init | s6-overlay / supervisord |
| :--- | :--- | :--- | :--- |
| **Цель** | Эмуляция полной ОС | Решение проблемы PID 1 | Групповой запуск и перезапуск служб |
| **Сложность** | Максимальная | Минимальная | Средняя |
| **Изоляция cgroups** | Нарушена (нужен доступ к дереву) | Не затрагивается | Не затрагивается |
| **Привилегии** | `CAP_SYS_ADMIN`, отключение seccomp | Стандартные | Стандартные |
| **Сбор зомби** | Да | Да | Да |
| **Управление** | `systemctl` (полное) | Отсутствует | Собственные CLI / Web |
| **Вывод в `docker logs`** | Требует настройки (`-t`) | Прямой, без настройки | Прямой, без настройки |
| **Требования к образу** | Полноценный дистрибутив с systemd | +1 бинарник (~20 KB) | +1 слой s6 либо Python |

---

## Предварительные требования

**Хост**

- Docker Engine **20.10+**; в актуальной ветке — **29.x**. Проверить версию: `docker version --format '{{.Server.Version}}'`.
- **cgroup v2 (Unified Hierarchy)** на хосте. Проверка: `docker info | grep 'Cgroup Version'` →
  `Cgroup Version: 2`. Признак наличия v2 на хосте — файл
  `/sys/fs/cgroup/cgroup.controllers`.
- **Важно:** поддержка cgroup v1 **объявлена устаревшей в Docker Engine 29.0** и сохраняется как минимум
  до мая 2029 года. Миграцию на cgroup v2 следует планировать заранее.
- Хост под управлением `systemd` (Fedora, RHEL/Alma/Rocky 8+, Ubuntu 22.04+, Debian 12+) — иначе
  иерархия cgroups, которую создаст Docker, не будет соответствовать раскладке systemd и проброс
  поддерева потребует ручной подготовки на хосте.

**Образ**

- Базовый дистрибутив, **поставляющий systemd пакетом**. Практичные варианты: `ubuntu:24.04`
  (systemd 255), `debian:13` (systemd 257), `rockylinux:9`, `almalinux:9` (systemd 252).
- **Alpine не подходит:** его штатная система инициализации — OpenRC, а не systemd. Образы на базе
  Alpine для этого сценария не используются.
- `dbus` устанавливается автоматически как зависимость `systemd` в дистрибутивах Debian/Ubuntu/RHEL;
  отдельно ставить не нужно, но проверить стоит.

**Права**

- `--cap-add SYS_ADMIN` — для операций `mount` и `setns`, которые systemd выполняет при старте и
  при работе с `PrivateDevices=`.
- `CAP_MKNOD` — если сервисы используют `PrivateDevices=` (systemd создаёт узлы устройств сам);
  ограничивать его не следует.
- `--security-opt seccomp=unconfined` — стандартный seccomp-профиль Docker блокирует `mount`,
  `setns`, `unshare` и ряд других вызовов, без которых `systemd` не стартует.

**Проверка до начала работы**

```bash
# Версия Engine
docker version --format '{{.Server.Version}}'
# → 29.8.1

# Версия cgroups
docker info --format '{{.CgroupVersion}}'
# → 2

# Наличие unified-иерархии на хосте
test -f /sys/fs/cgroup/cgroup.controllers && echo "cgroup v2" || echo "cgroup v1"
# → cgroup v2

# Cgroup driver, которым управляется Docker
docker info --format '{{.CgroupDriver}}'
# → systemd
```

---

## Сборка образа

### Базовый Dockerfile

```dockerfile
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends systemd dbus && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Службы, которые не имеют смысла в контейнере.
# Маскировка выполняется на уровне файловой системы и работает во время сборки.
RUN for unit in \
        systemd-remount-fs.service \
        dev-hugepages.mount \
        sys-kernel-config.mount \
        systemd-udevd.service \
        systemd-logind.service \
        systemd-vconsole-setup.service \
        getty.target \
        console-getty.service \
        systemd-backlight.service \
        systemd-homed.service ; do \
        systemctl mask "$unit" 2>/dev/null || true ; \
    done

# systemd как PID 1: SIGTERM означал бы daemon-reexec, а не остановку
STOPSIGNAL SIGRTMIN+3

# Journald: без персистентности и с пробросом на консоль контейнера
RUN printf '[Journal]\nStorage=volatile\nForwardToConsole=yes\n' \
        > /etc/systemd/journald.conf

# Отключаем сообщения [ OK ] и раскраску в выводе статуса
RUN printf '[Manager]\nStatusMaxEntries=0\n' \
        > /etc/systemd/system.conf

EXPOSE 80

CMD ["/sbin/init"]
```

Ожидаемый результат сборки и проверки:

```bash
docker build -t systemd-node:24.04 .

docker inspect --format '{{.Config.StopSignal}}' systemd-node:24.04
# → SIGRTMIN+3

docker run -d --name smoke-test --tmpfs /run --tmpfs /run/lock --tmpfs /tmp \
    --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
    --cap-add SYS_ADMIN --security-opt seccomp=unconfined \
    systemd-node:24.04

docker exec smoke-test systemctl is-system-running
# → running
# (или degraded, если часть юнитов завершилась с ошибкой — см. журнал)
```

### Что работает через `systemctl` во время сборки, а что нет

Это ключевой момент, который регулярно ломает сборку. `systemctl` — клиент, работающий поверх
системной шины D-Bus, а во время `docker build` PID 1 — это `RUN`-команда, а не `systemd`. Поэтому
результат зависит от подкоманды:

| Подкоманда | Работает в `RUN` | Почему |
| :--- | :--- | :--- |
| `systemctl enable <unit>` | **Да** | Чистая файловая операция: создаёт симлинк в `*.target.wants/` |
| `systemctl disable <unit>` | **Да** | Удаляет симлинк |
| `systemctl mask <unit>` | **Да** | Создаёт симлинк на `/dev/null` |
| `systemctl unmask <unit>` | **Да** | Удаляет маску |
| `systemctl link <unit>` | **Да** | Создаёт симлинк в `/etc/systemd/system/` |
| `systemctl daemon-reload` | Только как no-op | Нет работающего менеджера — команда не даёт эффекта |
| `systemctl start/stop/restart` | **Нет** | Требуется живой systemd |
| `systemctl status/is-active` | **Нет** | Нет systemd для опроса состояния |
| `systemctl is-enabled` | Частично | Читает файловую систему; результат осмыслен только после enable в том же `RUN` |

Ошибка, которую дают нерабочие подкоманды:

```
System has not been booted with systemd as init system (PID 1). Can't operate.
Failed to connect to bus: Host is down
```

Отсюда практическое правило для образов с systemd: **пост-установочные скрипты пакетов,
вызывающие `systemctl start` или `systemctl enable --now`, необходимо подавлять.** На дистрибутивах
Debian/Ubuntu это делается через `/usr/sbin/policy-rc.d`:

```dockerfile
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && \
    chmod +x /usr/sbin/policy-rc.d
```

Код возврата `101` — сигнал пакетному менеджеру «сервис не запущен, но ошибки нет». Если достаточно
мягкого поведения, используйте `exit 0`. Этот же приём устраняет ошибки вида
`invoke-rc.d: could not determine current runlevel` в deb-пакетах, устанавливаемых внутри образа.

**Проверка корректности образа без запуска systemd.** Образ с systemd нельзя проверить `docker run`
на этапе сборки — init-система не работает. Вместо этого проверяйте состояние файловой системы
отдельным `RUN`-шагом:

```dockerfile
RUN set -eu; \
    # сервис включён — симлинк в wants-каталоге multi-user.target
    test -L /etc/systemd/system/multi-user.target.wants/nginx.service; \
    # пакет действительно установлен
    dpkg-query -W -f='${Status}' nginx | grep -q 'install ok installed'; \
    # маска на месте
    test -L /etc/systemd/system/systemd-udevd.service
```

### Настройка journald

Файл `/etc/systemd/journald.conf`:

```ini
[Journal]
# volatile — журнал живёт только в /run/log/journal и не переживает перезапуск контейнера.
# В контейнере это правильное значение: постоянный журнал на read-only слое невозможен,
# а на tmpfs-слое он бессмысленно расходует память.
Storage=volatile

# Проброс в /dev/console, который Docker отображает в свой stdout.
# Работает ТОЛЬКО при выделенном TTY (docker run -t).
ForwardToConsole=yes

# Явно отключаем остальные каналы: syslog и kmsg в контейнере уходят в никуда
ForwardToSyslog=no
ForwardToKmsg=no
ForwardToWall=no

# Компактный вывод в консоль
MaxLevelStore=info
MaxLevelConsole=info
```

Альтернатива — drop-in, чтобы не перезаписывать дистрибутивный файл:

```bash
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=volatile\nForwardToConsole=yes\n' \
    > /etc/systemd/journald.conf.d/10-container.conf
```

Ожидаемый результат:

```bash
docker run -d --name journal-test -t --tmpfs /run --tmpfs /tmp \
    --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
    --cap-add SYS_ADMIN --security-opt seccomp=unconfined \
    --hostname node01 systemd-node:24.04

docker logs -f journal-test
# → Загрузка сообщений журнала в /run/log/journal...
# → systemd[1]: Detected architecture x86-64
# → systemd[1]: systemd 255 running in system mode (+PAM +AUDIT ...)
```

### Перенаправление вывода сервисов

Проброс через `journald.conf` удобен глобально, но требует TTY и не даёт per-service контроля.
Более точная схема — директивы `StandardOutput=` в самом юните.

**Вариант A — глобальный, через `ForwardToConsole=yes`.** Применим сразу ко всем сервисам, требует
`docker run -t`.

**Вариант B — per-service, через `journal+console`.** Не зависит от `journald.conf`, но также
требует `/dev/console`, то есть `-t`:

```ini
# /etc/systemd/system/myapp.service.d/10-logging.conf
[Service]
StandardOutput=journal+console
StandardError=journal+console
SyslogIdentifier=myapp
```

**Вариант C — дублирование в файл, который затем отдаётся наружу.** Не зависит от TTY:

```ini
# /etc/systemd/system/myapp.service
[Service]
StandardOutput=append:/var/log/myapp.log
StandardError=append:/var/log/myapp.log
```

```dockerfile
VOLUME /var/log
```

**Вариант D — `journalctl` как мастер-процесс.** Требует, чтобы `systemd` не занимал PID 1:

```dockerfile
CMD ["/bin/sh", "-c", "/sbin/init & while wait -n; do :; done; exec journalctl --follow --no-pager --output=cat"]
```

Плата — нарушение init-протокола: `STOPSIGNAL SIGRTMIN+3` больше не доходит до менеджера напрямую,
а `docker stop` завершает процесс без штатной остановки сервисов.

**Вариант E — forwarding во внешний syslog.** Применим, когда рядом уже есть сборщик:

```ini
# /etc/systemd/journald.conf.d/20-forward.conf
[Journal]
ForwardToSyslog=yes
ForwardToSyslogProtocol=syslog
```

> **Выбор:** для CI и Ansible-образов, где важна предсказуемость и простота, — вариант B плюс `-t`.
> Для production без TTY — вариант C.

---

## Практические сценарии

### Сценарий 1: Обойтись без systemd (рекомендуется)

Подавляющий majority сценариев. Полный разбор — в
[init_process_tini.md](./Dockerfile/init_process_tini.md) и
[docker_multi_process_logging.md](./Docker_logs/docker_multi_process_logging.md).

```dockerfile
FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini dbus && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["nginx", "-g", "daemon off;"]
```

```bash
docker run -d --init myapp           # встроенный init Docker, без образа tini
```

```yaml
# compose.yaml
services:
  app:
    image: myapp
    init: true
    stop_grace_period: 30s
```

Критерии выбора: приложение порождает дочерние процессы, является shell-скриптом или не обрабатывает
сигналы. Если ни одного условия нет — init не нужен вовсе.

### Сценарий 2: Запуск на хосте с cgroup v2

Простейший рабочий вариант: передать контейнеру хостовую иерархию cgroups целиком.

```bash
docker run -d \
    --name systemd-node \
    --hostname node01 \
    --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
    --cgroupns=host \
    -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
    --cap-add SYS_ADMIN \
    --security-opt seccomp=unconfined \
    -t \
    systemd-node:24.04
```

Почему именно так:

- **`--cgroupns=host`** — обязателен. При `private` Docker монтирует `/sys/fs/cgroup` в read-only, и
  `systemd` падает на создании `init.scope`. Передача хостовой точки монтирования при активном
  cgroup namespace несовместима: пути в `/proc/<PID>/cgroup` перестают соответствовать дереву.
- **`-v /sys/fs/cgroup:/sys/fs/cgroup:rw`** — даёт менеджеру права записи в unified-иерархию.
  Режим `:ro` в cgroup v2 неработоспособен: `systemd` создаёт подгруппы при каждом старте юнита.
- **`--tmpfs /run --tmpfs /run/lock --tmpfs /tmp`** — `/run` в образе является обычным каталогом в
  слое; `systemd` ожидает tmpfs для сокетов и PID-файлов и монтирует его при старте. Тот же приём
  освобождает эти пути при пересоздании контейнера.
- **`--cap-add SYS_ADMIN`** — для `mount`/`setns`; **`--security-opt seccomp=unconfined`** — чтобы
  seccomp-фильтр не блокировал эти вызовы.
- **`-t`** — чтобы появился `/dev/console`, без него не работает проброс журнала.

**Компромисс:** контейнер получает права записи в корневую cgroup-группу хоста и, при
`--cgroupns=host`, видит процессы хоста через `/proc`. Это фактически отменяет cgroup-изоляцию.
Допустимо для доверенных образов в изолированных средах (CI-раннеры, лаборатории), недопустимо для
мультиарендного продакшена.

### Сценарий 3: Минимальные права через выделенный systemd slice

Вариант без передачи всей иерархии хоста. Docker размещает контейнер в собственном scope внутри
указанного slice, и контейнеру монтируется только этот поддерево — с сохранением изоляции.

**На хосте** создайте slice и включите контроллеры в его поддереве:

```bash
# slice определяет границу; Docker разместит контейнер в docker-<id>.scope внутри него
systemctl start systemd-cgroups.slice

# Активировать контроллеры в поддереве slice
echo '+cpu +memory +pids' > /sys/fs/cgroup/systemd-cgroups.slice/cgroup.subtree_control

# Проверить, что Docker действительно создал scope
systemd-cgls --no-pager | grep -A5 'systemd-cgroups.slice'
# → systemd-cgroups.slice
#   └─docker-8ed22f651971.scope
#     └─init.scope
#       └─1 /sbin/init
```

**Запуск контейнера** — монтируется только поддерево slice:

```bash
docker run -d \
    --name systemd-node \
    --hostname node01 \
    --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
    --cgroup-parent=systemd-cgroups.slice \
    --cgroupns=host \
    -v /sys/fs/cgroup/systemd-cgroups.slice:/sys/fs/cgroup:rw \
    --cap-add SYS_ADMIN \
    --security-opt seccomp=unconfined \
    -t \
    systemd-node:24.04
```

**Почему так работает:** Docker с драйвером cgroups `systemd` создаёт для контейнера
`<cgroup_parent>/docker-<id>.scope`. Монтируя в контейнер `/sys/fs/cgroup/systemd-cgroups.slice`
как `/sys/fs/cgroup`, мы даём менеджеру ровно тот корень, в котором он находится, и оставляем
`/proc/<PID>/cgroup` согласованным с деревом.

**Ограничения и подводные камни:**

- **Опция `nsdelegate` в монтировании хоста.** Если хост смонтировал cgroup2 с флагом `nsdelegate`,
  bind-mount поддерева может завершиться ошибкой
  `error mounting "/sys/fs/...": read-only file system`. Проверка:
  ```bash
  grep cgroup /proc/mounts
  # → cgroup2 /sys/fs/cgroup cgroup2 rw,seclabel,nosuid,nodev,noexec,relatime,nsdelegate ...
  ```
  Снять флаг можно только перемонтированием на хосте; Docker отдельного флага для этого не имеет.
  Как обходной путь — один запуск контейнера с `--cgroupns=host` **без** bind-mount сбрасывает
  `nsdelegate` на хосте, после чего монтирование поддерева работает:
  ```bash
  docker run --rm --cgroupns=host ubuntu:latest true
  grep cgroup /proc/mounts   # nsdelegate исчез
  ```
- **`userns-remap` меняет поведение.** При включённом user namespace remapping приватный
  `/sys/fs/cgroup` монтируется в режиме rw, и часть описанных проблем не воспроизводится. Проверяйте
  фактическое поведение, а не предполагайте его.
- **Docker Engine 29 и `containerd` image store:** при userns-remap образ store containerd временно
  недоступен (moby#47377, moby#51042).

### Сценарий 4: Docker Compose

Все необходимые директивы присутствуют в Compose Specification: `cgroup` (Compose v2.15.0+),
`cgroup_parent`, `security_opt`, `cap_add`, `tmpfs`, `hostname`, `stop_grace_period`, `stop_signal`.

```yaml
# compose.yaml
services:
  node:
    build:
      context: .
      dockerfile: Dockerfile.systemd
    image: systemd-node:24.04
    container_name: systemd-node
    hostname: node01
    cgroup: host
    cgroup_parent: systemd-cgroups.slice
    cap_add:
      - SYS_ADMIN
    security_opt:
      - seccomp=unconfined
    tmpfs:
      - /run
      - /run/lock
      - /tmp
    volumes:
      - type: bind
        source: /sys/fs/cgroup/systemd-cgroups.slice
        target: /sys/fs/cgroup
    tty: true
    stop_signal: SIGRTMIN+3
    stop_grace_period: 30s
```

```bash
docker compose up -d
docker compose logs -f node
docker compose down
```

Обратите внимание: в Compose директива называется **`cgroup`** (значения `host` / `private`), а не
`cgroupns` — это разные ключи спецификаций, и подмена приводит к тихой ошибке валидации.

### Сценарий 5: cgroup v1 (legacy)

**Статус:** поддержка cgroup v1 объявлена устаревшей в Docker Engine 29.0; окончание не раньше мая
2029 года. Приведённое ниже нужно только для существующих хостов; новые разворачивать на cgroup v2.

На cgroup v1 `systemd` требует прав записи **только в свою иерархию** `/sys/fs/cgroup/systemd/`
(остальные контроллеры необязательны). Это позволяет не открывать контейнеру остальные иерархии:

```bash
docker run -d \
    --name systemd-node \
    --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
    --cgroupns=host \
    -v /sys/fs/cgroup/systemd:/sys/fs/cgroup/systemd:rw \
    --cap-add SYS_ADMIN \
    --security-opt seccomp=unconfined \
    -t \
    systemd-node:24.04
```

Специфика v1, которой нет в v2:

- Корневая точка `/sys/fs/cgroup` на хосте — `tmpfs`, а не отдельная иерархия. Монтировать нужно
  именно подкаталоги.
- Режим `:ro` на хосте с `systemd` исторически работал (системный `systemd` держит
  `/sys/fs/cgroup/systemd` rw), но **перестал работать начиная с systemd 248**: хост с legacy-иерархией
  помечается как tainted, и монтирование read-only не удаётся. Не рассчитывайте на этот приём.
- Контроллер `blkio` удалён из ядра Linux начиная с 5.0, поэтому `--blkio-weight` при cgroup v1
  объявлен устаревшим и в Docker; при cgroup v2 лимиты I/O задаются через `io.weight`.

### Сценарий 6: Ansible, Molecule и CI-образы

Основной сценарий, где `systemd` действительно оправдан: платформа управления конфигурациями
ожидает работающий `systemctl` и `service_facts`.

Правила, проверенные практикой:

- **Образ должен запускать `systemd` как PID 1** (`CMD ["/sbin/init"]` либо
  `command: /sbin/init`). Только тогда `service_facts` собирает факты о сервисах.
- **`--cgroupns=host`** обязателен на хостах с cgroup v2 — иначе контейнер не стартует.
- **`command: /sbin/init` в конфигурации драйвера Molecule**, а не `command: sleep infinity`.
- Службы, которые Molecule/Ansible ждёт, должны быть **включены в образе**
  (`systemctl enable <service>` в `RUN`), иначе они не стартуют при загрузке.
- `systemd` в контейнере работает заметно медленнее: запуск набора юнитов занимает секунды. Поднимайте
  `ansible_timeout` (типовое значение 600 с) и `retries` для `wait_for_connection`.
- Базовые образы с преднастроенным systemd: `geerlingguy/docker-<distro>-ansible`. Их `Vagrantfile`
  и `Makefile` уже содержат требуемые флаги запуска.

```bash
# Типичный запуск для Molecule вручную (для отладки)
docker run -d --name molecule \
    --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
    --cap-add SYS_ADMIN --security-opt seccomp=unconfined \
    --tmpfs /run --tmpfs /tmp \
    -v "$PWD":/project \
    geerlingguy/docker-debian12-ansible:latest \
    /sbin/init
```

### Сценарий 7: Podman и rootless-альтернативы

Если задача — «получить systemd внутри контейнера», иногда правильный ответ — сменить runtime, а не
дополнительно расширять права Docker.

**Podman** реализует этот сценарий штатно:

- Автоматически определяет, что PID 1 — `systemd`, и выставляет сигнал остановки `SIGRTMIN+3`.
  Флаг `--systemd=always` форсирует такое поведение, `--systemd=force` — считать контейнер системным
  независимо от содержимого.
- `--unmask` для точечного снятия AppArmor/SELinux-масок с отдельных путей, например
  `--unmask=/sys/fs/cgroup`; поддерживается как `--unmask` (все пути), так и `--unmask=path:rw`.
- Не требует демона: контейнер запускает `crun`/`runc` напрямую, что меняет модель отказа и
  упрощает rootless-режим.
- Работает под `systemd` хоста через Quadlet; cgroup-менеджер по умолчанию — `systemd`.

**Rootless Docker** официально **не поддерживает** запуск `systemd` внутри контейнера: демон
работает в user-сервисе systemd, и делегированное поддерево cgroups недостаточно для
`init.scope`. Не планируйте такой сценарий — используйте Podman или VM.

**Sysbox** — специализированный рантайм (runc replacement), виртуализирующий namespaces через
User Namespaces, включая cgroups. Позволяет запускать `systemd` без `CAP_SYS_ADMIN` и без проброса
`/sys/fs/cgroup`. Подробнее — в [alternative_runtimes_and_tools.md](./alternative_runtimes_and_tools.md)
и [docker-in-docker.md](./docker-in-docker.md).

**Vagrant / libvirt** — если поведение ВМ действительно нужно, это правильный инструмент, а не
контейнер с `systemd`.

### Сценарий 8: Замена systemd без systemd

Когда `systemd` нужен только для совместимости скриптов, использующих `systemctl`, а реального
управления службами не требуется, существуют shim-реализации:

| Инструмент | Модель | Ограничения |
| :--- | :--- | :--- |
| **`systemd` в пользовательском режиме** (`systemd --user`) | Реальный systemd, но без PID 1 и без управления хоста | Не подходит, если нужны системные привилегии и unit-файлы |
| **`docker-systemctl-replacement`** | Python-скрипт, подменяющий `/usr/bin/systemctl`; парсит `*.service` и выполняет `ExecStart`/`ExecStop` | Нет настоящего supervisor: нет авторестарта, нет зависимостей, нет интеграции с journald |
| **`s6-overlay`** | Полноценный сервис-менеджер | Несовместим с `systemctl`-скриптами |
| **Distrobox / `chroot` с init** | Почти полная ОС без изоляции | Слабая изоляция |

```bash
# Проверка shim-подхода: скрипты получают рабочий systemctl без systemd
docker run --rm myapp-image systemctl is-active nginx
# → active
```

Этот подход популярен в homelab-средах (Synology Container Manager и аналоги), но для продакшена
не подходит: отсутствие авторестарта и наблюдаемости делает его непригодным для сервисов, за
которыми кто-то дежурит.

---

## Валидация

### Проверка после сборки

```bash
# 1. Сигнал остановки зафиксирован в образе
docker inspect --format '{{.Config.StopSignal}}' systemd-node:24.04
# → SIGRTMIN+3

# 2. PID 1 — именно systemd
docker exec systemd-node ps -p 1 -o pid,comm,args
# → PID COMMAND COMMAND
# →   1 systemd   /sbin/init

# 3. Менеджер достиг рабочего состояния
docker exec systemd-node systemctl is-system-running
# → running
# → degraded — часть юнитов упала; смотрите journalctl

# 4. Включённые сервисы действительно стартуют
docker exec systemd-node systemctl is-enabled nginx
# → enabled
docker exec systemd-node systemctl is-active nginx
# → active

# 5. Есть ли зомби (их быть не должно)
docker exec systemd-node ps -eo pid,ppid,stat,comm | awk '$3 ~ /Z/'
# → (пусто)

# 6. cgroups смонтированы в режиме rw
docker exec systemd-node findmnt -no TARGET,FSTYPE,OPTIONS /sys/fs/cgroup
# → /sys/fs/cgroup cgroup2 rw,nosuid,nodev,noexec,...

# 7. Журнал виден через docker logs (нужен -t и ForwardToConsole=yes)
docker logs --tail 50 systemd-node
# → systemd[1]: Startup finished in 1.2s (kernel) + 420ms (userspace) = 1.6s
```

### Проверка корректного завершения

```bash
# Засечь время: должно быть существенно меньше таймаута
time docker stop systemd-node
# → real 0m1.4s
# → контейнер остановился штатно, а не по SIGKILL

docker inspect --format '{{.State.ExitCode}}' systemd-node
# → 0
```

Негативный контроль: если время остановки совпадает с `stop_grace_period` (по умолчанию 10 с), а
код возврата `137` (`128 + 9`, SIGKILL) — `STOPSIGNAL SIGRTMIN+3` не действует. Проверьте
`docker inspect --format '{{.Config.StopSignal}}'` и версию образа.

### Проверка изоляции cgroups

```bash
# На хосте: убедиться, что контейнер внутри своего scope, а не в корне дерева
systemd-cgls --no-pager | grep systemd-cgroups.slice

# Убедиться, что ограничения Docker применяются
docker exec systemd-node systemd-cgtop --no-pager -n1

# Внутри контейнера: видит ли systemd себя в корне делегированного поддерева
docker exec systemd-node cat /proc/1/cgroup
# → 0::/
# → путь обрезан корнем cgroup namespace — это ожидаемо при --cgroupns=host
#   для systemd; при --cgroupns=private путь сохранялся бы полностью
```

---

## Типичные ошибки и их решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Failed to create /init.scope control group: Read-only file system` | Docker смонтировал `/sys/fs/cgroup` в read-only (дефолт при `--cgroupns=private` на cgroup v2) | Использовать `--cgroupns=host` вместе с bind-mount в `:rw`. См. сценарии 2 и 3 |
| `Failed to create ... control group: Permission denied` | Поддерево смонтировано, но его владельцем считается «ложный root» из cgroup namespace | Сочетание `--cgroupns=host` и bind-mount **поддерева**, а не всей иерархии |
| `error mounting "/sys/fs...": read-only file system` при старте | На хосте cgroup2 смонтирован с опцией `nsdelegate`, мешающей bind-mount поддерева | Снять `nsdelegate` (перемонтированием на хосте либо разовым `docker run --rm --cgroupns=host ubuntu true`) |
| `System has not been booted with systemd as init system (PID 1). Can't operate.` | `systemctl start/stop/restart/status` во время `docker build` или в контейнере без systemd | Использовать только `enable`/`disable`/`mask` в `RUN`; подавить хуки пакетов через `/usr/sbin/policy-rc.d` |
| `System has not been booted...` при старте приложения внутри контейнера | PID 1 — не systemd | Проверить `docker exec <c> ps -p 1 -o comm`. Либо перейти на сценарий 1, либо запускать systemd по сценарию 2/3 |
| `docker stop` ждёт 10 секунд, код возврата `137` | Не задан `STOPSIGNAL SIGRTMIN+3`; systemd трактует `SIGTERM` как `daemon-reexec` | Добавить `STOPSIGNAL SIGRTMIN+3` в Dockerfile или `stop_signal: SIGRTMIN+3` в Compose |
| `docker stop` не останавливает сервисы, но завершается быстро | Принят `SIGRTMIN+3`, но `systemd-halt.service` замаскирован | Проверить `docker exec <c> systemctl is-enabled systemd-halt.service` |
| `docker logs` пуст | Вывод уходит во внутриконтейнерный journald; нет `ForwardToConsole=yes` и нет TTY | Настроить `journald.conf` (см. выше) **и** запускать с `-t`/`tty: true`; либо `journal+console` в юните; либо `append:` в файл |
| `docker logs` пуст при `journal+console` и `-t` | `StandardOutput=journal+console` переопределён drop-in-ом ниже по приоритету | `docker exec <c> systemctl show myapp.service -p StandardOutput` и проверить drop-in-каталоги |
| Журнал контейнера не переживает `docker restart` | `Storage=volatile` (сознательный выбор) либо `/var/log/journal` на read-only слое | Это ожидаемое поведение; для персистентности нужен volume на `/var/log/journal` |
| `CAP_SYS_ADMIN` не помогает, `mount` возвращает `EPERM` | Активен seccomp-профиль Docker, блокирующий `mount`/`setns` | Добавить `--security-opt seccomp=unconfined` |
| Контейнер стартует и сразу падает, в логах `Exiting PID 1` | `systemd` не смог создать ни одного cgroup | Проверить `findmnt /sys/fs/cgroup` внутри контейнера и версии Docker/systemd на хосте |
| Маскировка не сработала, служба стартует | `systemctl mask` в `RUN` подавлен через `2>/dev/null \|\| true` | Проверить фактическое состояние: `test -L /etc/systemd/system/systemd-udevd.service` |
| Нужен systemd, но хост cgroup v1 и `systemd` 248+ | Legacy-иерархия помечается tainted, монтирование `:ro` не работает | Перевести хост на cgroup v2 (актуально); временно — `:rw` с `--cgroupns=host` |
| Работает на одной машине, не работает на другой | Разные версии ядра, systemd или режим cgroups | Собрать и сохранить диагностику (§ «Дополнительная информация») и сравнить |

---

## Лучшие практики

**Архитектурные**

1. **Не используйте `systemd` там, где достаточно init-процесса.** Проверьте: приложение
   порождает дочерние процессы? Требуется ли `systemctl` в скриптах? Если нет — берите
   `tini` или `s6-overlay`.
2. **Предпочитайте выделенный slice полной иерархии хоста** (сценарий 3). Это сохраняет
   cgroup-изоляцию и упрощает аудит.
3. **Если образ будет использоваться в Kubernetes, помните:** Kubernetes не поддерживает
   `--init`, а `kubelet` отправляет `SIGTERM` контейнеру независимо от `STOPSIGNAL` в образе в
   ряде конфигураций. Единственный надёжный путь — `tini`/`s6-overlay` в `ENTRYPOINT`.
4. **Изолируйте такие контейнеры на отдельных хостах или в отдельном пуле.** Образ с `systemd` и
   доступом к корневой cgroup-группе хоста — это фактически полноценный доступ к хосту.

**При сборке образа**

5. **Подавляйте старт сервисов при установке пакетов** через `/usr/sbin/policy-rc.d`.
6. **Маскируйте всё, что не имеет смысла:** `udev`, `logind`, `getty`, `vconsole-setup`,
   `remount-fs`, `backlight`, `homed`.
7. **Оставляйте `STOPSIGNAL SIGRTMIN+3` в образе**, а не только в команде запуска — иначе
   `docker run` без флагов, `docker compose up` из чужого репозитория и CI-скрипты получат
   неверное поведение.
8. **Пиньте базовый образ по тегу или digest**, а не `latest`: состав юнитов между релизами меняется.
9. **Проверяйте образ статически** (`RUN`-шаг с проверкой симлинков и пакетов), а не «запуском и
   посмотрим».

**При эксплуатации**

10. **Ограничивайте `stop_grace_period` осмысленно.** Полная остановка `systemd` занимает секунды;
    10 секунд по умолчанию обычно достаточно, но для контейнера с тяжёлыми `ExecStop` нужно 30–60 с.
11. **Не полагайтесь на `docker logs` как на единственный источник логов.** Внутриконтейнерный journald
    недоступен снаружи без `docker exec`. Для production настройте внешний сборщик (Vector, Fluentd,
    Grafana Alloy) — см. [docker_agent_based_logging.md](./Docker_logs/docker_agent_based_logging.md).
12. **Держите `--cap-add SYS_ADMIN` и отключение seccomp минимально необходимыми.** Если задача решается
    через Podman или Sysbox, откажитесь от Docker полностью.
13. **Документируйте требуемые флаги запуска в README образа.** Флаг `--cgroupns=host` — обязательное
    условие работоспособности; без него образ «работает у одного человека».

---

## Дополнительная информация

### Требования systemd к контейнерной среде

[systemd.io/CONTAINER_INTERFACE](https://systemd.io/CONTAINER_INTERFACE/) — канонический документ
с требованиями. Ключевые пункты, применимые к Docker:

- `/proc`, `/sys` и `/sys/fs/selinux` должны быть смонтированы **до** запуска `systemd`.
- `/sys` должен быть смонтирован **read-only**. По этому признаку `systemd` определяет, что
  устройства виртуализированы, и не запускает `systemd-udevd`, `systemd-logind`,
  `systemd-networkd` в полном режиме. Исключение — сетевые пространства имён: `/sys/class/net`
  виртуализирован, и его подкаталоги можно оставить rw.
- `/dev` должен быть собственным `tmpfs` контейнера с узлами `/dev/null`, `/dev/zero`, `/dev/full`,
  `/dev/random`, `/dev/urandom`, `/dev/tty`, `/dev/ptmx`.
- **`CAP_MKNOD` нельзя отбирать.** Многие юниты используют `PrivateDevices=`, и systemd создаёт узлы
  устройств сам. Ограничивайте создание устройств через BPF-программы
  `BPF_PROG_TYPE_CGROUP_DEVICE` (на cgroup v2) или контроллер `devices` (на cgroup v1), а не отбором
  capability.
- Иерархии cgroups либо монтируются целиком, либо не монтируются вовсе — тогда их смонтирует сам
  `systemd`. Поддеревья вместо полной иерархии монтировать нельзя.
- Точка контрольных групп контейнера должна создаваться как юнит с `Delegate=yes`, чтобы контейнер
  стал частью всех контроллеров. Docker делает это сам, создавая `<slice>/docker-<id>.scope`.
- Иерархия монтирований должна быть смонтирована `MS_SHARED` до вызова `systemd` — Docker выполняет
  это условие.

### Диагностика: что собрать при разборе инцидента

```bash
# Версии
docker version --format '{{.Server.Version}}'
docker exec systemd-node systemctl --version | head -1
docker exec systemd-node cat /etc/os-release | head -2
uname -r

# Состояние cgroups на хосте и в контейнере
docker info --format 'CgroupVersion={{.CgroupVersion}} CgroupDriver={{.CgroupDriver}}'
docker exec systemd-node findmnt -o TARGET,FSTYPE,OPTIONS /sys/fs/cgroup
docker exec systemd-node cat /proc/1/cgroup
grep cgroup /proc/mounts

# Права и ограничения
docker inspect --format 'Privileged={{.HostConfig.Privileged}} CapAdd={{.HostConfig.CapAdd}} SecOpt={{.HostConfig.SecurityOpt}} CgroupnsMode={{.HostConfig.CgroupnsMode}}' systemd-node
docker inspect --format 'StopSignal={{.Config.StopSignal}}' systemd-node

# Состояние менеджера и журнал
docker exec systemd-node systemctl is-system-running
docker exec systemd-node systemctl --failed --no-pager
docker exec systemd-node journalctl -p err -b --no-pager | tail -50
docker logs --tail 200 systemd-node
```

### Откат изменений

Все изменения, связанные с этим сценарием, откатываются на уровне контейнера и тома — образ не
требует специальной очистки:

```bash
# Остановить и удалить контейнер (tmpfs-каталоги исчезают вместе с ним)
docker compose down

# Удалить образ
docker rmi systemd-node:24.04

# Откатить настройки хоста
systemctl stop systemd-cgroups.slice
# или снять контроллеры, записанные в subtree_control:
echo '-cpu -memory -pids' > /sys/fs/cgroup/systemd-cgroups.slice/cgroup.subtree_control

# Проверить, что дерево cgroups хоста не осталось в изменённом состоянии
systemd-cgls --no-pager | grep systemd-cgroups.slice
# → (пусто)
```

Если использовался `--privileged` или проброс всей иерархии cgroups хоста, контейнер следует удалить
немедленно после теста: у него были права записи в корневую cgroup-группу хоста.

### См. также

- **[Init Process в Docker: tini, PID 1, zombie reaping](./Dockerfile/init_process_tini.md)** —
  авторитетный разбор PID 1, зомби-процессов, проброса сигналов; основная альтернатива `systemd`.
- **[Паттерн Multi-Process в Docker](./Docker_logs/docker_multi_process_logging.md)** — `s6-overlay`,
  `supervisord`, ограничение ресурсов на уровне cgroup v2.
- **[Инструкции Dockerfile: HEALTHCHECK и STOPSIGNAL](./Dockerfile/Instructions/health_signals.md)** —
  полная механика `STOPSIGNAL` и health check.
- **[Выполнение приложений в контейнере](./Dockerfile/Docker_best_practices/container_execution.md)** —
  Graceful Shutdown, exec-form, exit codes 137/143.
- **[Linux-изоляция: namespaces и cgroups](./Concepts/linux_isolation.md)** — device, PID, network
  namespaces и режимы `cgroupns` в общем виде.
- **[Контрольные группы (cgroups)](../Linux/Core/cgroups.md)** — делегирование и непривилегированный
  доступ к контроллерам.
- **[Интеграция Docker и systemd на хосте](../Linux/Core/systemd/docker_integration.md)** —
  управление контейнерами как юнитами на стороне хоста.
- **[Альтернативные среды выполнения](./alternative_runtimes_and_tools.md)** — Sysbox, Kata, gVisor.
- **[Docker-in-Docker](./docker-in-docker.md)** — Sysbox и `--privileged` как стратегии для DinD.
- **[Безопасность: Capabilities и hardening хоста](./Docker_security/host_daemon_hardening.md)** —
  риски `SYS_ADMIN` и защита dockerd.
- **[Logging drivers в Docker](./Docker_logs/docker_logging_drivers_overview.md)** — включая
  различие с внутриконтейнерным journald.
- **[systemd Container Interface](https://systemd.io/CONTAINER_INTERFACE/)** — официальный контракт
  systemd с контейнерными менеджерами.
- **[Systemd CGROUP_DELEGATION](https://github.com/systemd/systemd/blob/main/docs/CGROUP_DELEGATION.md)** —
  правила делегирования поддерева cgroups.
