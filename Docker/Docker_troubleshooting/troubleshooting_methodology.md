# Методология диагностики Docker (Troubleshooting Methodology)

**Актуально для:** Docker Engine 20.10+ / 28.x–29.x; Docker Desktop 4.33+ (`docker debug`)

**Prerequisites:** доступ к Docker-хосту (SSH/console), `docker` CLI в PATH, права на демон (пользователь в группе `docker` или `sudo`; rootless — свой контекст, см. **[Диагностика демона](./docker_daemon_failures.md)**).

## Определения

**Decision tree диагностики** — упорядоченный по симптомам маршрут от наблюдения к файлу с разбором конкретной проблемы. Позволяет не перебирать всю базу знаний, а за 2–3 команды локализовать класс проблемы.

**Management plane vs Data plane** — `docker events`, `docker ps`, `docker inspect` показывают состояние объектов (management plane); прохождение пакетов и системные вызовы — data plane, диагностируется eBPF-инструментами (см. **[Docker events](./debugging_with_docker_events.md)**).

## Основные концепции

### Базовая последовательность диагностики

Для любого симптома «контейнер не работает» — фиксированный порядок, от дешёвых команд к дорогим:

```bash
# 1. Состояние объекта
docker ps -a --filter name=<app>
# → Status, Ports, ExitCode

# 2. Вывод приложения
docker logs --tail 50 <app>

# 3. Конфигурация и состояние
docker inspect <app> --format 'Status: {{.State.Status}}, Health: {{.State.Health.Status}}, Exit: {{.State.ExitCode}}, OOM: {{.State.OOMKilled}}, Pid: {{.State.Pid}}'
# Health: healthy / unhealthy / no-healthcheck / empty (нет HEALTHCHECK)

# 4. События жизненного цикла
docker events --filter container=<app> --since 10m

# 5. Хост: ресурсы и ядро
df -h /var/lib/docker; dmesg | tail -20; journalctl -u docker --since 10m

# 6. Compose-стек: то же на уровне проекта
docker compose ps -a; docker compose logs --tail 50 <service>
```

**Принцип:** сначала CLI/демон (отвечает ли Docker), затем контейнер (запущен ли), затем приложение (работает ли), затем хост (ресурсы, ядро, сеть). `unhealthy` — часто первый признак «живого, но неработающего» контейнера (см. **[Зависшие контейнеры](./hung_containers.md)**).

### Три вопроса локализации

1. **CLI-ошибка или ошибка контейнера?** Ошибка вида `Cannot connect...`/`permission denied` — уровень демона. Ошибка вида `Exited (N)`/`unhealthy` — уровень контейнера.
2. **Контейнер stopped или running?** Stopped → коды завершения. Running, но не отвечает → hung-контейнеры или сеть.
3. **Проблема в образе или в среде?** Воспроизводится на `docker run` с чистым образом → образ/сборка. Только в production-конфигурации → тома/сеть/права.

## Практические сценарии

### Сценарий 1: CLI сообщает об ошибке подключения

**Симптом:** `Cannot connect to the Docker daemon`, `permission denied ... docker.sock`.

**Маршрут:** **[Диагностика демона](./docker_daemon_failures.md)** — демон, сокет, контекст, `DOCKER_HOST`, rootless.

```bash
systemctl status docker; docker context ls; ls -l /var/run/docker.sock
```

### Сценарий 2: Контейнер не запускается / сразу exited

**Симптом:** `Exited (N)`, `Restarting`, `CrashLoopBackOff`-аналог.

**Маршрут:** **[Коды завершения](./docker_exit_codes.md)** — интерпретация кода (125/126/127, 137 OOM, 143/137 stop), crash-loop, Compose-пропагация кодов.

```bash
docker inspect <app> --format '{{.State.ExitCode}} {{.State.OOMKilled}} {{.State.Error}}'
```

### Сценарий 3: Контейнер `Up`, но сервис не отвечает

**Симптом:** `docker ps` показывает `Up`, `curl` не отвечает.

**Маршрут (параллельный):**

1. **[Зависшие контейнеры](./hung_containers.md)** — `docker top`, `docker stats`, D-state, зомби, 100% CPU.
2. **[Диагностика сетевой связности](./network_connectivity_issues.md)** — слушает ли приложение порт (`ss -tlnp`), firewall, MTU.
3. **[Конфликты портов](./port_conflicts.md)** — бинд к `127.0.0.1` вместо `0.0.0.0`, «port is already allocated».

```bash
docker exec <app> ss -tlnp 2>/dev/null || docker debug <app> --command "ss -tlnp"
docker port <app>
```

### Сценарий 4: Циклические перезапуски

**Симптом:** `Restarting (N) ...`, `docker ps --filter status=restarting`.

**Маршрут:** **[Docker events](./debugging_with_docker_events.md)** (события `die`/`restart`/`health_status`) + **[Коды завершения](./docker_exit_codes.md)** (причина по коду) + **[Autoheal](./docker_autoheal.md)** (если перезапускает монитор — проверить `start_period`).

```bash
docker inspect <app> --format '{{.State.ExitCode}} {{.State.OOMKilled}}'
docker compose ps -a --status=exited   # для стеков
docker compose logs --tail 20 <service>
```

### Сценарий 5: Нет сетевой связности

**Симптом:** DNS не резолвится, таймауты соединений, обрывы.

**Маршрут:** **[Диагностика сетевой связности](./network_connectivity_issues.md)** — conntrack, MTU, iptables, Docker 28 isolation, eBPF; послойное дерево решений — **[Decision tree сетевых проблем](../Docker_network/troubleshooting/decision_tree.md)**; **[Конфликты портов](./port_conflicts.md)** — ephemeral-порты; DNS-детали — **[DNS resolution issues](../Docker_network/troubleshooting/dns_resolution_issues.md)**.

### Сценарий 6: «No space left on device»

**Симптом:** ошибки записи, падение сборки/контейнера.

**Маршрут:** **[Анализ использования диска](../Docker_fs/disk_usage_analysis.md)** — `docker system df`, inodes, логи `json-file`, SRE-пороги; **[Очистка и GC](../Docker_fs/cleanup_gc_strategies.md)**; ротация логов — **[docker_log_rotation.md](../Docker_logs/docker_log_rotation.md)**.

```bash
docker system df; df -h /var/lib/docker; df -i /var/lib/docker
```

### Сценарий 7: Сборка образа падает

**Симптом:** ошибки `RUN`/`COPY`, `failed to solve`, кэш не переиспользуется.

**Маршрут:** **[BuildKit: разрешение проблем](../Dockerfile/dockerfile_buildkit.md)**, **[Buildx: типичные ошибки](../Dockerfile/docker_buildx.md)**, **[RUN: типичные ошибки](../Dockerfile/Instructions/build_time_commands.md)**, **[контекст сборки](../Dockerfile/dockerfile_build_context.md)**; отладка точками останова — **[Docker Debug, сценарий 9](./docker_debug.md)**.

### Сценарий 8: «exec format error» / образ не запускается на этом хосте

**Симптом:** `exec format error`, `no matching manifest for linux/amd64`.

**Маршрут:** **[Alpine: разрешение проблем](../Dockerfile/dockerfile_alpine_linux.md)** (архитектура, `docker inspect --format '{{.Architecture}}'`, `buildx --platform`), **[Rust best practices, Ошибка 4](../Dockerfile/Docker_best_practices/rust.md)**, **[Buildx: multi-arch](../Dockerfile/docker_buildx.md)**.

### Сценарий 9: Данные потерялись / том не монтируется

**Симптом:** пустой datadir после рестарта, `permission denied` при записи в `/data`, `volume is in use`.

**Маршрут:** **[Тома: устранение неполадок](../Docker_fs/docker_volumes.md)** — UID/GID, SELinux `:z`/`:Z`, propagation, `volume in use`; stateful-паттерны — **[Stateful-сервисы](../Dockerfile/Docker_best_practices/stateful_services.md)**.

### Сценарий 10: Бинарник не запускается в Alpine

**Симптом:** `No such file or directory` при существующем файле, `libc.so.6: cannot open shared object file`.

**Маршрут:** **[glibc/musl совместимость](./alpine_glibc_compatibility.md)** — `file`/`readelf`, `gcompat`, Wolfi, пересборка.

### Сценарий 11: Нет shell в образе (distroless/scratch)

**Симптом:** `exec: "sh": executable file not found in $PATH`.

**Маршрут:** **[Отладка distroless](./debugging_distroless.md)** — `docker debug`, `:debug`-теги, sidecar, `nsenter`, eBPF; ошибки exec — **[docker_exec_failures.md](./docker_exec_failures.md)**.

### Сценарий 12: Неверное время в контейнере

**Симптом:** UTC вместо локального времени, смещённые метки логов.

**Маршрут:** **[Время и часовые пояса](./container_time_sync.md)** — `tzdata`, `TZ`, `/etc/localtime`, NTP на хосте.

### Сценарий 13: Образ не скачивается / `docker run` падает на pull

**Симптом:** `Unable to find image ... locally`, `pull access denied`, `unauthorized: authentication required`, `TLS handshake timeout`.

**Маршрут:** **[Реестры: типичные ошибки](../docker_registries.md)** — `docker login`, `--password-stdin`, токены; **[Образы: устранение неполадок](../Docker_fs/images/docker_images_basics.md)** — имя/тег, `docker manifest inspect`; таймауты и зеркала — **[Диагностика демона](./docker_daemon_failures.md)** (registry-mirrors).

```bash
docker pull <image>:<tag>
# → Error response from daemon: pull access denied for <image>,
#   repository does not exist or may require 'docker login'
```

## Индекс симптомов

| Симптом | Файл |
| :--- | :--- |
| `Cannot connect to the Docker daemon` | [docker_daemon_failures.md](./docker_daemon_failures.md) |
| `permission denied ... docker.sock` | [docker_daemon_failures.md](./docker_daemon_failures.md) |
| `Exited (N)`, `Restarting`, коды 125–143, 137 | [docker_exit_codes.md](./docker_exit_codes.md) |
| `Up`, но не отвечает; `docker stop` висит; D-state | [hung_containers.md](./hung_containers.md) |
| `Container is not running` при exec; `not a TTY` | [docker_exec_failures.md](./docker_exec_failures.md) |
| `port is already allocated`; недоступен из LAN | [port_conflicts.md](./port_conflicts.md) |
| DNS, MTU, conntrack, iptables, Docker 28 isolation | [network_connectivity_issues.md](./network_connectivity_issues.md) |
| `no space left on device`, inodes, рост логов | [disk_usage_analysis.md](../Docker_fs/disk_usage_analysis.md) |
| `volume is in use`, `permission denied` в `/data`, потеря данных | [docker_volumes.md](../Docker_fs/docker_volumes.md) |
| Падение сборки, `failed to solve`, кэш | [dockerfile_buildkit.md](../Dockerfile/dockerfile_buildkit.md), [docker_buildx.md](../Dockerfile/docker_buildx.md) |
| `exec format error`, multi-arch | [dockerfile_alpine_linux.md](../Dockerfile/dockerfile_alpine_linux.md) |
| `No such file or directory` (бинарник есть), `libc.so.6` | [alpine_glibc_compatibility.md](./alpine_glibc_compatibility.md) |
| `exec: "sh": executable file not found` (distroless) | [debugging_distroless.md](./debugging_distroless.md) |
| `unhealthy`-циклы, autoheal | [docker_autoheal.md](./docker_autoheal.md) |
| Время/часовой пояс в контейнере | [container_time_sync.md](./container_time_sync.md) |
| `pull access denied`, `unauthorized`, `TLS handshake timeout` | [docker_registries.md](../docker_registries.md), [docker_images_basics.md](../Docker_fs/images/docker_images_basics.md) |
| Логи: драйверы, ротация, `--since` | [Docker_logs/](../Docker_logs/) |
| `docker events`, аудит exec | [debugging_with_docker_events.md](./debugging_with_docker_events.md) |

## Валидация

```bash
# 1. Демон отвечает
docker info --format '{{.ServerVersion}}'
# → 28.5.2

# 2. Базовая последовательность работает
docker ps -a --filter name=my-app && docker logs --tail 5 my-app
# → статус + последние строки лога

# 3. События доступны
docker events --filter event=die --since 1h --until 0s
# → (события die за час или пусто)

# 4. Диск и inodes в норме
df -h /var/lib/docker && df -i /var/lib/docker
# → Use% < 80%, IUse% < 80%
```

## Лучшие практики

1. **Фиксированный порядок команд** (ps → logs → inspect → events → хост) — не начинайте с `dmesg` и не перепрыгивайте к перезапуску демона.
2. **Не перезапускайте `dockerd` как первый шаг** — это останавливает все контейнеры и стирает доказательства (буфер событий, состояние).
3. **Воспроизводите в минимальном окружении**: `docker run --rm <image>` без томов и сетей — отделяет проблему образа от проблемы среды.
4. **Runbook по симптомам**: держите индекс (таблица выше) под рукой в CI/Slack — большинство инцидентов попадают в 13 сценариев.
5. **Мониторинг первой линии**: алерты на `die`/`oom`-события, `unhealthy`, `df` > 80%, `NTPSynchronized=no` — ловят большинство проблем до пользователей.
6. **Собирайте доказательства до очистки**: `docker inspect`, `docker events --since`, `journalctl -u docker` — до `docker rm`/`prune`.
7. **Стек ≠ контейнер**: в Compose-средах дублируйте базовую последовательность на уровне проекта (`docker compose ps`, `docker compose logs`) — состояние проекта не всегда отражает состояние отдельных контейнеров.

## Дополнительная информация

### См. также

- **[Команды Docker](../docker_commands.md)** — справочник CLI и таблица типовых ошибок.
- **[Docker events](./debugging_with_docker_events.md)** — management plane.
- **[Inspektor Gadget / eBPF](./debugging_distroless.md)** — data plane.
- **[Docker: Оптимизация производительности](../Docker_performance_tuning.md)** — CPU/IO/сеть.
- **[Podman troubleshooting](../../Podman/podman_troubleshooting.md)** — аналогичный runbook для Podman.

**Глубокое изучение:**
- **[Docker troubleshooting (документация)](https://docs.docker.com/engine/troubleshooting/)** — официальные runbooks.
- **[moby/moby issues](https://github.com/moby/moby/issues)** — первоисточники багов `docker stop`/`kill` (D-state, exit events).
