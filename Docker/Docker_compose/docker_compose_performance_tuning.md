# Производительность Docker Compose: лимиты, OOM, I/O

**Актуально для:** Docker Engine 29.x, Docker Compose v5.x / v2.13+, cgroup v2. Хостовый tuning (overlay2, conntrack, NUMA, I/O scheduler) — в SSoT-файле [Оптимизация производительности Docker](../Docker_performance_tuning.md); здесь — compose-специфичные рычаги. Глубокий разбор лимитов cgroup v2 (`memory.high`, `cpu.weight`, blkio, `--ulimit`, `--oom-score-adj`) — в [Ограничение ресурсов контейнеров](../Docker_security/resource_limits.md).

## Определения

**`deploy.resources.limits`** — жёсткие лимиты сервиса в compose: `cpus` (доли ядра), `memory` (потолок RAM), `pids` (лимит процессов). При превышении `memory` ядро убивает процесс в cgroup — контейнер получает статус `OOMKilled`.

**`deploy.resources.reservations`** — мягкий лимит (soft limit), а не потолок и не гарантированный минимум: в non-Swarm compose `reservations.memory` применяется как `--memory-reservation` (с Compose v2.13+) — при превышении ядро вытесняет память контейнера (reclaim), но не убивает процесс. `reservations.cpus` и `reservations.pids` compose не применяет — это опции только для Swarm.

**CoW overhead** — накладные расходы overlay2 на первую запись файла (Copy-on-Write): файл копируется из read-only слоя в верхний слой контейнера. Критично для write-heavy нагрузок (БД, логи).

**Conntrack exhaustion** — исчерпание таблицы трекинга соединений (`nf_conntrack_max`): каждый published port создаёт DNAT-правило, а каждое соединение занимает в таблице две записи (прямое и обратное направление). Размер таблицы по умолчанию зависит от RAM хоста (buckets = totalram/16384, кап 262144) — актуальное значение проверяйте: `sysctl net.netfilter.nf_conntrack_max`. При переполнении пакеты дропаются с `nf_conntrack: table full, dropping packet`.

**OOMKilled** — статус контейнера, убитого ядром при превышении memory-лимита (exit code 137, SIGKILL).

**`ulimits`** — лимиты файловых дескрипторов (`nofile`) и процессов (`nproc`) внутри контейнера, задаются в compose-файле; исчерпание `nofile` проявляется как `too many open files` в high-connection сервисах (балансировщики, БД).

## Базовые концепции

### Что контролируется из compose, а что — на хосте

| Рычаг | Где настраивается | Эффект |
| :--- | :--- | :--- |
| `cpus`, `memory`, `pids` | compose-файл (`deploy.resources.limits`) | Лимиты cgroup контейнера |
| `logging.options` (ротация) | compose-файл (`logging`) | Предотвращение переполнения диска логами |
| Volumes vs bind mounts | compose-файл (`volumes:`) | Обход overlay2 CoW для write-heavy данных |
| `stop_grace_period` | compose-файл | Время graceful shutdown перед SIGKILL |
| `ulimits` (`nofile`, `nproc`) | compose-файл (`ulimits`) | Лимиты файловых дескрипторов и процессов в контейнере |
| `cpuset` | compose-файл (`cpuset`) | Привязка контейнера к ядрам CPU (пиннинг) |
| `init: true` | compose-файл | tini как PID 1: сбор zombie-процессов |
| `read_only` + `tmpfs` | compose-файл | Read-only корень и tmpfs: меньше CoW-записей в слой контейнера |
| `mem_swappiness`, `oom_score_adj`, `memswap_limit` | compose-файл | Склонность к свопу, приоритет жертвы OOM и лимит swap |
| `shm_size` | compose-файл | Размер `/dev/shm` (shared memory для БД и браузеров) |
| overlay2, conntrack, NUMA, swappiness | хост (`sysctl`, `daemon.json`) | Глобальная производительность — см. SSoT |

### Почему volumes быстрее bind mounts для записи

Named volume управляется dockerd напрямую и обходит CoW overlay2 для данных; bind mount тоже обходит overlay2, но требует согласования прав. Для БД и логов — named volume; для hot-reload в dev — bind mount.

### Механика OOM в compose

1. Контейнер превышает `deploy.resources.limits.memory`.
2. Ядро убивает процесс в cgroup (SIGKILL).
3. Docker помечает контейнер `OOMKilled`, exit code 137.
4. Политика `restart:` определяет, перезапустится ли сервис.

**Мягкий лимит:** compose не имеет аналога cgroup v2 `memory.high` (троттлинг без убийства). Ближайший встроенный механизм — `deploy.resources.reservations.memory` (soft limit на reclaim, см. Определения). Настоящий `memory.high`-троттлинг возможен только снаружи Docker: на уровне systemd-юнита (`MemoryHigh=`), если стек управляется через systemd.

## Практические сценарии

### Сценарий 1: Лимиты ресурсов для production-стека

```yaml
services:
  web:
    image: myapp:1.0.0
    init: true                      # tini как PID 1: сбор zombie-процессов
    cpuset: "0,1"                   # пиннинг к ядрам (latency-sensitive)
    ulimits:
      nofile:
        soft: 65536
        hard: 65536
    deploy:
      resources:
        limits:
          cpus: "0.50"
          memory: 512M
          pids: 256
        reservations:
          memory: 256M              # soft limit (reclaim), не гарантия
    stop_grace_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
        compress: "true"
```

**Ожидаемый результат:** Сервис ограничен половиной ядра и 512 МБ, привязан к ядрам 0–1, лимит `nofile` 65536; логи ротируются (макс. 50 МБ на контейнер); graceful shutdown до 30 с.

**Важно:** значения `log-opts` — строки; изменения лог-драйвера применяются только к новым контейнерам (`--force-recreate`). `reservations.cpus`/`reservations.pids` compose не применяет (опции Swarm) — в примере указан только `reservations.memory`, который работает как soft limit.

### Сценарий 2: Диагностика OOM

```bash
# 1. Найти убитый контейнер
docker compose ps -a
# → web-1   Exit 137

# 2. Подтвердить OOM
docker inspect --format '{{.State.OOMKilled}} {{.State.ExitCode}}' $(docker compose ps -q web)
# → true 137

# 3. Мониторинг потребления в реальном времени
docker compose stats
# разовый снимок (без потокового вывода):
docker compose stats --no-stream

# 4. Процессы внутри контейнера (поиск runaway-процесса)
docker compose top web

# 5. История событий OOM (compose events не поддерживает --filter)
docker events --filter event=oom
# или поток compose в JSON:
docker compose events --json | jq 'select(.action == "oom")'
```

**Ожидаемый результат:** Подтверждено, что контейнер убит по памяти. Действия: поднять `memory`, найти утечку в приложении, проверить `reservations`.

### Сценарий 3: Write-heavy сервис (БД)

```yaml
services:
  db:
    image: postgres:17-alpine
    volumes:
      - db_data:/var/lib/postgresql/data   # named volume: обход CoW
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 4G
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      start_period: 30s
volumes:
  db_data:
```

**Ожидаемый результат:** Данные БД в named volume — нативная производительность записи; лимит защищает хост от деградации.

### Сценарий 4: Высоконагруженный хост с множеством портов

```bash
# Симптом: дропаются пакеты, новые соединения не устанавливаются
dmesg | grep conntrack
# → nf_conntrack: table full, dropping packet

# Диагностика
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max

# Лечение (хост): увеличить таблицу
sudo sysctl -w net.netfilter.nf_conntrack_max=524288
# Постоянно: /etc/sysctl.d/99-conntrack.conf
```

**Ожидаемый результат:** Таблица conntrack увеличена; compose-стеки с десятками published ports работают стабильно.

**Профилактика в compose:** публикуйте только необходимые порты; внутренние сервисы — через `expose` и `internal: true` сети.

### Сценарий 5: High-connection сервис (балансировщик, БД)

```yaml
services:
  proxy:
    image: traefik:v3.4
    init: true
    cpuset: "2,3"                   # пиннинг: меньше context switch
    ulimits:
      nofile:
        soft: 65536
        hard: 65536                 # лимит на соединения
    mem_swappiness: 0               # не свопать при давлении
    oom_score_adj: -500             # убивать последним
    read_only: true                 # read-only корень
    tmpfs:
      - /tmp                        # запись без CoW в слой контейнера
```

**Ожидаемый результат:** Сервис держит десятки тысяч соединений без `too many open files`, не свопается, имеет низкий приоритет OOM и не пишет в свой слой overlay2.

**Примечание:** `read_only: true` ломает приложения, пишущие в рабочие директории — такие пути выносите на named volume или `tmpfs`. `oom_score_adj` — относительный приоритет ядра при выборе жертвы OOM (-1000…1000); он не защищает от `memory`-лимита.

## Операции и команды

| Команда | Назначение |
| :--- | :--- |
| `docker compose stats [--no-stream] [-a]` | Потребление CPU/RAM сервисами (`--no-stream` — разовый снимок, `-a` — все контейнеры) |
| `docker compose top [SVC]` | Процессы внутри контейнеров (поиск runaway-процессов) |
| `docker events --filter event=oom` | События OOM (`compose events` не поддерживает `--filter`; его поток — `compose events --json`) |
| `docker inspect --format '{{.State.OOMKilled}}' <c>` | Флаг OOM контейнера |
| `docker compose config [--format json]` | Проверка итоговых лимитов после merge файлов |
| `docker compose up -d --force-recreate` | Применить изменения лог-драйвера |
| `du -hs /var/lib/docker/containers/*/*-json.log \| sort -rh` | Поиск виновников переполнения диска логами |

## Устранение неполадок

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Контейнер в `OOMKilled` (exit 137) | Превышен `memory` limit | Поднимите лимит; найдите утечку; проверьте `reservations` |
| Диск заполнен логами | Ротация не настроена | `logging.options` с `max-size`/`max-file`; `truncate -s 0` экстренно |
| Медленная первая запись в файл | CoW overlay2 | Named volume для write-heavy данных |
| `table full, dropping packet` | Conntrack exhaustion | `sysctl net.netfilter.nf_conntrack_max`; меньше published ports |
| Лимиты не применяются | Юнит systemd без `Delegate=yes` | Добавьте `Delegate=yes` (см. [Автозапуск через systemd](./docker_compose_systemd_autostart.md)) |
| `too many open files` в контейнере | Исчерпан `ulimits.nofile` | Поднимите `ulimits.nofile` в compose-файле |
| Zombie-процессы в контейнере | Нет init-системы | `init: true` (tini собирает zombie) |
| `unknown flag: --filter` при `compose events` | `compose events` не поддерживает `--filter` | `docker events --filter event=oom` или `compose events --json` + `jq` |
| Латентность на NUMA-системе | Удалённый memory access | Хостовый tuning: `numactl`, привязка к NUMA-ноде — см. SSoT |

## Рекомендации

1. **Всегда задавайте `limits`** — отсутствие лимита в одном сервисе может деградировать весь хост (эффект домино).
2. **Ротируйте логи в compose-файле** — `json-file` без `max-size` растёт неограниченно.
3. **Named volumes для БД и логов** — обход CoW overlay2.
4. **`start_period` для долгой инициализации** — иначе healthcheck убьёт контейнер во время старта БД.
5. **`ulimits.nofile` для high-connection сервисов** — балансировщики и БД упираются в дескрипторы раньше, чем в CPU/RAM.
6. **`init: true` для сервисов с дочерними процессами** — иначе zombie-процессы копятся (в контейнере нет init-системы).
7. **`read_only: true` + `tmpfs`** — read-only корень устраняет CoW-записи в слой контейнера; пишущие пути выносите на volume или tmpfs.
8. **Хостовый tuning не заменяется compose** — overlay2, conntrack, NUMA, swappiness настраиваются на хосте (SSoT: Docker_performance_tuning.md).

## Дополнительная информация

- **[Оптимизация производительности Docker](../Docker_performance_tuning.md)** — SSoT: overlay2 CoW, conntrack, I/O scheduler, NUMA, page cache, THP.
- **[Ограничение ресурсов контейнеров](../Docker_security/resource_limits.md)** — глубокий разбор лимитов cgroup v2 (`memory.high`, `cpu.weight`, blkio, `--ulimit`, `--oom-score-adj`).
- **[Docker логирование: вопросы на собеседованиях](../Docker_logs/docker_logging_interview_qa.md)** — диагностика OOM, ротация, dual logging.
- **[Автозапуск через systemd](./docker_compose_systemd_autostart.md)** — `MemoryHigh=`/`MemoryMax=` на уровне юнита.
- **[Примеры конфигураций](./docker_compose_file_example.md)** — эталонные `deploy.resources`.
- **[Миграция VPS без простоя](./vps_migration_zero_downtime.md)** — latency при миграции.
