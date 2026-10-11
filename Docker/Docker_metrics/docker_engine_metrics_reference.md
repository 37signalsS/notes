# Справочник метрик Docker Engine (порт 9323)

**Актуально для:** Docker Engine 20.10–29.8.x (текущий релиз — 29.8.2, 2026-09-30; версионность отдельных метрик — в столбце «С версии»)

## Определения

**Docker Engine Metrics** — встроенный экспортёр метрик демона Docker в формате Prometheus, доступный на порту `9323` при настройке `metrics-addr` в `daemon.json`. Экспортирует стандартный Prometheus-реестр демона: метрики самого демона (`engine_daemon_*`), сборки (`builder_*`), логирования (`logger_*`), Swarm (`swarm_*`) и Go-runtime (`go_*`, `process_*`).

**Пространство имён `engine_daemon_`** — все метрики демона имеют префикс `engine_daemon_`. Формируется в исходниках moby как `gometrics.NewNamespace("engine", "daemon", nil)` (библиотека `github.com/docker/go-metrics`).

**Правило формирования имён** — полное имя метрики собирается как `<namespace>_<subsystem>_<name>[_<unit>]`: к имени добавляется суффикс единицы измерения (`seconds`, `bytes`, `total` или нестандартные `info`, `cpus`, `containers`). Счётчики получают суффикс `_total` на этапе определения. Поэтому реальные имена отличаются от «коротких» имён в исходниках: `container_states` + unit `containers` → `engine_daemon_container_states_containers`; `engine_cpus` + unit `cpus` → `engine_daemon_engine_cpus_cpus`; счётчик `health_checks` → `engine_daemon_health_checks_total`.

**Timer-метрика** — прометеус-гистограмма длительности операции. Экспортируется как три серии: `_seconds_bucket{le}` (кумулятивные бакеты), `_seconds_sum` и `_seconds_count`. Бакеты — дефолтные Prometheus (DefBuckets: 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, +Inf). Средняя длительность = `_sum / _count`; квантили доступны через `histogram_quantile`.

## Основные концепции

### Как формируются имена метрик

Библиотека `github.com/docker/go-metrics` — обёртка над `prometheus/client_golang`, принудительно применяющая соглашения об именовании. Ключевые правила, влияющие на то, что видно на эндпоинте:

| Тип в исходниках | Суффикс при экспорте | Пример |
|---|---|---|
| `NewCounter("health_checks")` | `_total` | `engine_daemon_health_checks_total` |
| `NewGauge("engine_memory", ..., Bytes)` | `_bytes` | `engine_daemon_engine_memory_bytes` |
| `NewGauge("engine_cpus", ..., Unit("cpus"))` | `_cpus` | `engine_daemon_engine_cpus_cpus` |
| `NewDesc("container_states", ..., Unit("containers"), "state")` | `_containers` | `engine_daemon_container_states_containers{state}` |
| `NewLabeledTimer("container_actions", ..., "action")` | `_seconds` + гистограмма | `engine_daemon_container_actions_seconds_{bucket,sum,count}{action}` |
| `NewGauge("events_subscribers", ..., Total)` | `_total` (но тип — gauge!) | `engine_daemon_events_subscribers_total` |

*Примечание:* метрики с суффиксом `_total`, определённые как gauge (`events_subscribers_total`, `swarm_manager_*_total`), — это **текущие значения, а не счётчики**. Применять к ним `rate()`/`increase()` нельзя — считайте дельту между сэмплами или используйте значение напрямую.

### Что экспортируется на эндпоинте

Эндпоинт `9323` обслуживает стандартный Prometheus-реестр процесса `dockerd`. Помимо `engine_daemon_*` на нём присутствуют:

- `builder_*` — метрики сборки образов демона (не путать с метриками отдельного процесса `buildkitd`);
- `logger_*` — метрики драйверов логирования;
- `swarm_*` — метрики Swarm (регистрируются при старте демона всегда; на хостах вне Swarm — нулевые значения, `swarm_node_manager` = 0);
- `go_*`, `process_*` — стандартные метрики Go-runtime и процесса (полезны для диагностики утечек памяти и горутин в самом `dockerd`).

Согласно документации Docker: «The available metrics and the names of those metrics are in active development and may change at any time» и «Currently, you can only monitor Docker itself. You can't currently monitor your application using the Docker target».

## Предварительные требования

- **Docker Engine:** 20.10+ (параметр `metrics-addr` работает без `experimental`; в 18.09–20.10 требовался экспериментальный режим)
- **Настройка:** `"metrics-addr": "127.0.0.1:9323"` в `daemon.json` (Linux: `/etc/docker/daemon.json`; Windows Server: `C:\ProgramData\docker\config\daemon.json`; Docker Desktop: Settings → Docker Engine; rootless: `~/.config/docker/daemon.json`)
- **Перезапуск:** `sudo systemctl restart docker`
- **Проверка:**

```bash
curl -s http://localhost:9323/metrics | grep -E "engine_daemon_engine_info|engine_daemon_container_states_containers"
# → # HELP engine_daemon_engine_info The information related to the engine and the OS it is running on
# → # TYPE engine_daemon_engine_info gauge
# → engine_daemon_engine_info{architecture="x86_64",...,graphdriver="overlay2",version="29.8.2"} 1
# → engine_daemon_container_states_containers{state="running"} 12
```

## Полный перечень метрик

### Информация о движке

| Метрика | Тип | Метки | Описание | С версии |
|---|---|---|---|---|
| `engine_daemon_engine_info` | gauge | `version`, `commit`, `architecture`, `graphdriver`, `kernel`, `os`, `os_type`, `os_version`, `daemon_id` | Информация о движке и ОС. Значение всегда `1` — используется для выгрузки меток | 18.09+ |
| `engine_daemon_engine_cpus_cpus` | gauge | — | Число CPU, доступных движку | 18.09+ |
| `engine_daemon_engine_memory_bytes` | gauge | — | Объём памяти хоста в байтах | 18.09+ |

### Состояния контейнеров

| Метрика | Тип | Метки | Описание | С версии |
|---|---|---|---|---|
| `engine_daemon_container_states_containers` | gauge | `state` (`running`, `paused`, `stopped`) | Количество контейнеров в каждом состоянии | 18.09+ |

*Примечание:* метрики `container_count` в Docker Engine нет. Для подсчёта контейнеров используйте `engine_daemon_container_states_containers` или `docker ps -q | wc -l`.

### Таймеры операций (гистограммы)

| Метрика | Метки | Описание | С версии |
|---|---|---|---|
| `engine_daemon_container_actions_seconds_{bucket,sum,count}` | `action` (`start`, `changes`, `commit`, `create`, `delete`) | Длительность операций с контейнерами | 18.09+ |
| `engine_daemon_network_actions_seconds_{bucket,sum,count}` | `action` | Длительность сетевых операций | 18.09+ |
| `engine_daemon_host_info_functions_seconds_{bucket,sum,count}` | `function` | Длительность функций сбора информации о хосте | 20.10+ |
| `engine_daemon_image_actions_seconds_{bucket,sum,count}` | `action` | Длительность операций с образами | 28.0+ |
| `engine_daemon_health_check_start_duration_seconds_{bucket,sum,count}` | — | Время подготовки к запуску health-check'а | 23.0+ |

### Health-check'и

| Метрика | Тип | Описание | С версии |
|---|---|---|---|
| `engine_daemon_health_checks_total` | counter | Общее число выполненных health-check'ов | 18.09+ |
| `engine_daemon_health_checks_failed_total` | counter | Число неудачных health-check'ов | 18.09+ |

*Примечание:* per-container статуса health (healthy/unhealthy) в метриках нет — только агрегированные счётчики (запрос на такую метрику moby#46958 открыт с 2023). Статус конкретного контейнера: `docker inspect --format '{{.State.Health.Status}}' <container>`.

### События

| Метрика | Тип | Описание | С версии |
|---|---|---|---|
| `engine_daemon_events_total` | counter | Число записанных событий | 18.09+ |
| `engine_daemon_events_subscribers_total` | gauge | Число текущих подписчиков на события | 18.09+ |

*Примечание:* `engine_daemon_events_subscribers_total > 0` означает, что кто-то (коллектор, `docker events`) слушает поток событий демона. Метрика — gauge, несмотря на суффикс `_total`.

### Сборка образов (builder)

| Метрика | Тип | Метки | Описание | С версии |
|---|---|---|---|---|
| `builder_builds_triggered_total` | counter | — | Число запущенных сборок | 18.09+ |
| `builder_builds_failed_total` | counter | `reason` | Число неудачных сборок по причинам | 18.09+ |

Значения метки `reason`: `build_canceled`, `build_target_not_reachable_error`, `command_not_supported_error`, `dockerfile_empty_error`, `dockerfile_syntax_error`, `error_processing_commands_error`, `missing_onbuild_arguments_error`, `unknown_instruction_error`.

*Примечание:* это метрики встроенного в демон builder. Метрики самого BuildKit-даемона (`buildkitd`) экспортируются его собственным эндпоинтом, не через порт 9323.

### Логирование (logger)

| Метрика | Тип | Описание | С версии |
|---|---|---|---|
| `logger_log_write_operations_failed_total` | counter | Число неудачных записей в логи контейнеров | 18.09+ |
| `logger_log_read_operations_failed_total` | counter | Число неудачных чтений из stdio контейнеров | 18.09+ |
| `logger_log_entries_size_greater_than_buffer_total` | counter | Число записей лога, превышающих размер буфера | 18.09+ |

### Docker Swarm

Метрики регистрируются при старте демона всегда (пакеты swarmkit импортируются безусловно); на хостах вне Swarm значения нулевые. Заполняются при участии в Swarm: `swarm_node_manager` = 1 на менеджерах, `swarm_manager_*` — только на менеджер-нодах.

| Метрика | Тип | Метки | Описание | С версии |
|---|---|---|---|---|
| `swarm_node_manager` | gauge | — | 1, если нода — менеджер Swarm | 18.09+ |
| `swarm_node_info` | gauge | `node_id`, `swarm_id` | Информация о Swarm-кластере | 18.09+ |
| `swarm_manager_leader` | gauge | — | 1, если этот менеджер — лидер | 18.09+ |
| `swarm_manager_services_total` | gauge | — | Число сервисов в object store | 18.09+ |
| `swarm_manager_networks_total` | gauge | — | Число сетей в object store | 18.09+ |
| `swarm_manager_secrets_total` | gauge | — | Число секретов в object store | 18.09+ |
| `swarm_manager_configs_total` | gauge | — | Число конфигов в object store | 18.09+ |
| `swarm_manager_nodes` | gauge | `state` (`ready`, `down`, `unknown`, `disconnected`) | Число нод по состояниям | 18.09+ |
| `swarm_manager_tasks_total` | gauge | `state` (`new`, `pending`, `assigned`, `accepted`, `preparing`, `ready`, `starting`, `running`, `complete`, `shutdown`, `failed`, `rejected`, `remove`, `orphaned`) | Число задач по состояниям | 18.09+ |
| `swarm_dispatcher_scheduling_delay_seconds_{bucket,sum,count}` | histogram | — | Задержка перехода задачи NEW → RUNNING | 18.09+ |
| `swarm_raft_snapshot_latency_seconds_{bucket,sum,count}` | histogram | — | Латентность создания Raft-снапшота | 18.09+ |
| `swarm_raft_transaction_latency_seconds_{bucket,sum,count}` | histogram | — | Латентность Raft-транзакции | 18.09+ |
| `swarm_store_write_tx_latency_seconds_{bucket,sum,count}` | histogram | — | Латентность записи в memory store | 18.09+ |
| `swarm_store_read_tx_latency_seconds_{bucket,sum,count}` | histogram | — | Латентность чтения из memory store | 18.09+ |
| `swarm_store_lookup_latency_seconds_{bucket,sum,count}` | histogram | — | Латентность поиска в memory store | 18.09+ |
| `swarm_store_batch_latency_seconds_{bucket,sum,count}` | histogram | — | Латентность батч-записи в memory store | 18.09+ |
| `swarm_store_memory_store_lock_duration_seconds_{bucket,sum,count}` | histogram | — | Время удержания блокировки memory store | 18.09+ |

*Примечание:* `swarm_manager_*_total` — gauge (текущие количества), а не counter, несмотря на суффикс `_total`.

### Go runtime

Стандартные метрики `prometheus/client_golang` процесса `dockerd`: `go_goroutines`, `go_memstats_*` (в т.ч. `go_memstats_heap_inuse_bytes`, `go_memstats_sys_bytes`), `go_gc_duration_seconds` (summary), `process_cpu_seconds_total`, `process_open_fds`, `process_max_fds`, `process_resident_memory_bytes`, `process_start_time_seconds`, `process_virtual_memory_bytes`. Полезны для диагностики утечек памяти и роста горутин в самом демоне.

### Что НЕ экспортируется

- **Per-container метрики** (CPU, RAM, Network, I/O, PIDs) — через cAdvisor.
- **Метрики BuildKit-даемона** (`buildkitd` как отдельный процесс) — через собственный эндпоинт `buildkitd`. Метрики сборки демона (`builder_builds_*`) на 9323 есть.
- **Метрики containerd** — через собственный эндпоинт containerd.
- **OOM-события в реальном времени** — через `docker events --filter 'event=oom'` или cAdvisor (`container_oom_events_total`).
- **Размеры образов и контейнеров** (`docker_images_size_bytes` и подобных) — только `docker system df` / `docker image ls`.
- **Per-container статус health** — только агрегированные `engine_daemon_health_checks{,_failed}_total`.

## Практические сценарии

### PromQL: состояние контейнеров

```promql
# Число запущенных контейнеров
sum(engine_daemon_container_states_containers{state="running"})

# Число остановленных контейнеров
sum(engine_daemon_container_states_containers{state="stopped"})

# Изменение числа запущенных контейнеров за 5 минут
delta(engine_daemon_container_states_containers{state="running"}[5m])
```

### PromQL: длительность операций

```promql
# Средняя длительность запуска контейнера (секунды)
rate(engine_daemon_container_actions_seconds_sum{action="start"}[5m])
  /
rate(engine_daemon_container_actions_seconds_count{action="start"}[5m])

# p95 длительности запуска контейнера (таймеры — полные гистограммы, histogram_quantile доступен)
histogram_quantile(0.95,
  sum(rate(engine_daemon_container_actions_seconds_bucket{action="start"}[5m])) by (le))

# p99 длительности операций с образами (Docker 28.0+)
histogram_quantile(0.99,
  sum(rate(engine_daemon_image_actions_seconds_bucket[5m])) by (le))
```

### PromQL: health-check'и, сборка, логирование

```promql
# Доля неудачных health-check'ов
rate(engine_daemon_health_checks_failed_total[5m])
  /
rate(engine_daemon_health_checks_total[5m])

# Доля неудачных сборок (CI-хосты)
rate(builder_builds_failed_total[5m])
  /
rate(builder_builds_triggered_total[5m])

# Неудачные сборки по причинам за 1 час
sum by (reason) (increase(builder_builds_failed_total[1h]))

# Сбои записи логов контейнеров
rate(logger_log_write_operations_failed_total[5m])
```

### PromQL: Swarm

```promql
# Нода — менеджер Swarm?
swarm_node_manager

# Этот менеджер — лидер?
swarm_manager_leader

# Число задач по состояниям
sum by (state) (swarm_manager_tasks_total)

# p95 задержки планирования задач (NEW → RUNNING)
histogram_quantile(0.95,
  sum(rate(swarm_dispatcher_scheduling_delay_seconds_bucket[5m])) by (le))

# Число нод по состояниям
sum by (state) (swarm_manager_nodes)
```

### PromQL: информация о движке и Go runtime

```promql
# Версия движка на каждом хосте
engine_daemon_engine_info

# Число CPU и объём памяти хоста
engine_daemon_engine_cpus_cpus
engine_daemon_engine_memory_bytes

# Число горутин и resident-память демона
go_goroutines
process_resident_memory_bytes
```

### Алерты

```yaml
groups:
  - name: docker-engine
    rules:
      - alert: DockerEngineDown
        expr: up{job="docker-engine"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Docker daemon не отвечает на {{ $labels.instance }}"

      - alert: DockerFailedHealthChecks
        expr: rate(engine_daemon_health_checks_failed_total[5m]) / rate(engine_daemon_health_checks_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Доля неудачных health-check'ов контейнеров >10% на {{ $labels.instance }}"

      - alert: DockerNoRunningContainers
        expr: sum(engine_daemon_container_states_containers{state="running"}) == 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Нет запущенных контейнеров на {{ $labels.instance }}"

      - alert: DockerBuildFailures
        expr: rate(builder_builds_failed_total[5m]) / rate(builder_builds_triggered_total[5m]) > 0.2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Доля неудачных сборок образов >20% на {{ $labels.instance }}"

      - alert: DockerLogWriteFailures
        expr: rate(logger_log_write_operations_failed_total[5m]) > 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Сбои записи логов контейнеров на {{ $labels.instance }}"
```

## Диагностика и устранение неполадок

1. **Порт 9323 не отвечает**
   - **Причина:** `metrics-addr` не задан или демон не перезапущен.
   - **Решение:** Проверьте `daemon.json`, выполните `systemctl restart docker`, проверьте слушающий порт: `ss -tlnp | grep 9323`.

2. **Имена метрик отличаются от ожидаемых (суффиксы `_total`, `_bytes`, `_containers`, `_cpus_cpus`)**
   - **Причина:** Это не ошибка — правило формирования имён `docker/go-metrics` добавляет к имени единицу измерения, а счётчики получают `_total`. Например, в исходниках метрика называется `container_states`, а экспортируется как `engine_daemon_container_states_containers`.
   - **Решение:** Сверяйтесь с таблицами выше. Вывести актуальный список: `curl -s http://localhost:9323/metrics | grep -E "engine_daemon|builder_|logger_|swarm_"`.

3. **Часть метрик отсутствует**
   - **Причина:** Версионность: `image_actions` — с 28.0, `health_check_start_duration` — с 23.0, `host_info_functions` — с 20.10. Имена и набор метрик «in active development and may change at any time» (предупреждение Docker).
   - **Решение:** Проверьте версию движка: `docker version --format '{{.Server.Version}}'` и сверьтесь со столбцом «С версии».

4. **Swarm-метрики нулевые или `swarm_node_manager` = 0**
   - **Причина:** Хост не участвует в Swarm или является worker-нодой. `swarm_manager_*` заполняются только на менеджер-нодах.
   - **Решение:** Проверьте статус: `docker info --format '{{.Swarm.LocalNodeState}}'`. На менеджере `swarm_node_manager` = 1.

5. **Нет метрик конкретных контейнеров (CPU, RAM, сеть)**
   - **Причина:** Эндпоинт 9323 экспортирует только метрики демона и платформы. Per-container метрики в Docker Engine не реализованы.
   - **Решение:** Разверните cAdvisor (порт 8080) для per-container метрик.

## Лучшие практики

- **Скрейпите с интервалом 30s** — демон-метрики не меняются чаще, и интервал 1s создаёт лишнюю нагрузку на TSDB.
- **Используйте `histogram_quantile` для таймеров** — таймеры экспортируются как полные гистограммы с DefBuckets, p95/p99 доступны без дополнительной инструментации.
- **Не полагайтесь на метрики демона для per-container мониторинга** — используйте cAdvisor.
- **Учитывайте версионность** — набор метрик расширялся в 20.10 (`host_info_functions`), 23.0 (`health_check_start_duration`) и 28.0 (`image_actions`). Проверяйте версию движка перед написанием алертов.
- **Следите за `builder_builds_failed_total` на CI-хостах** — рост доли неудачных сборок часто указывает на проблемы с registry или дисковым пространством.
- **Имена метрик могут измениться** — Docker предупреждает, что метрики в активной разработке. Фиксируйте версию движка в scope-линии файла и в алертах используйте полные имена с суффиксами.
- **Swarm-метрики собирайте с менеджер-нод** — на worker-нодах `swarm_manager_*` нулевые; алерты на них с менеджеров дадут ложные срабатывания.

## Дополнительная информация

- **[Интеграция Docker с Prometheus](./docker_prometheus_integration.md)** — настройка `scrape_configs`, `docker_sd_config`, `dockerswarm_sd_config`, маршрутизация алертов через Alertmanager.
- **[Нативные метрики Docker](./docker_native_metrics.md)** — `docker stats`, PSI, чтение cgroups напрямую.
- **[cAdvisor: развертывание и сбор метрик](./docker_cadvisor_deployment.md)** — per-container метрики.
- **[Grafana для Docker-метрик](./docker_grafana_dashboards.md)** — дашборды, провиженинг, алерты.
- **[Docker метрики: вопросы на собеседованиях](./docker_metrics_interview_qa.md)** — краткие ответы на вопросы SRE-собеседований.
- **[Конфигурация Docker daemon](../docker_daemon_config.md)** — полный справочник `daemon.json`, включая `metrics-addr`.
- **[Collect Docker metrics with Prometheus](https://docs.docker.com/engine/daemon/prometheus/)** — официальная документация Docker.
- **[docker/go-metrics](https://github.com/docker/go-metrics)** — библиотека, формирующая имена метрик (правило `<name>_<unit>`, суффикс `_total` для счётчиков).
- **Исходники moby** (по версиям):
  - v20.10–v27: `daemon/metrics.go` (метрики демона), `daemon/events/metrics.go` (события), `builder/dockerfile/metrics.go` (сборка), `daemon/logger/metrics.go` (логирование);
  - v28.x: `internal/metrics/metrics.go` (все метрики демона, включая события);
  - v29+: `daemon/internal/metrics/metrics.go`, `daemon/builder/dockerfile/metrics.go`;
  - Swarm-метрики — в vendored swarmkit: `manager/metrics/collector.go` (`swarm_manager_{nodes,tasks,services,networks,secrets,configs}`), `manager/manager.go` (`swarm_manager_leader`), `node/node.go` (`swarm_node_{manager,info}`), `manager/state/store/memory.go` (`swarm_store_*`), `manager/state/raft/{storage,raft}.go` (`swarm_raft_*`), `manager/dispatcher/dispatcher.go` (`swarm_dispatcher_scheduling_delay`).
