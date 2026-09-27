# Паттерны инструментации: что измерять

## Определения

**Паттерны инструментации** — это типовые наборы метрик, рекомендуемые для конкретных классов сервисов и компонентов инфраструктуры. Паттерны определяют **что** измерять, **каким типом метрики** и **зачем**, на основе методологий [RED](../../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md), [USE](../../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md) и [Four Golden Signals](../../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md).

Паттерны инструментации позволяют: быстро настроить мониторинг нового сервиса, обеспечить покрытие критических компонентов, избежать типовых ошибок (пропуск важных метрик, избыточная кардинальность).

## Основные концепции

### Методологический фреймворк

Перед выбором конкретных метрик определите тип компонента и примените соответствующую методологию:

| Компонент | Методология | Что измерять | Метрики |
|:---|:---|:---|:---|
| **HTTP/API сервис** | RED | Rate, Errors, Duration | `*_total` (Counter), `*_duration_seconds` (Histogram) |
| **База данных** | USE | Utilization, Saturation, Errors | `*_connections` (Gauge), `*_queries_total` (Counter), `*_pool_*` (Gauge) |
| **Очередь сообщений** | RED | Rate, Errors, Duration | `*_messages_total` (Counter), `*_queue_length` (Gauge) |
| **Файловая система / Диск** | USE | Utilization, Saturation, Errors | `*_free_bytes` (Gauge), `*_io_seconds_total` (Counter) |
| **Сеть** | USE | Utilization, Saturation, Errors | `*_bytes_total` (Counter), `*_drops_total` (Counter) |
| **Фоновые задачи (Cron)** | — | Last success, Duration, Failures | `*_last_success_timestamp_seconds` (Gauge), `*_runs_total` (Counter) |
| **Контейнер / Pod** | USE + RED | CPU/Memory/Network/Restart | cadvisor-метрики (см. ниже) |

### Три обязательные метрики для любого HTTP-сервиса

Любой HTTP-сервис должен экспортировать минимум три метрики:

| Метрика | Тип | Что измеряет | Зачем |
|:---|:---|:---|:---|
| `<service>_requests_total` | Counter | Количество запросов по методам и статусам | `rate()` → RPS, доля ошибок |
| `<service>_request_duration_seconds` | Histogram | Распределение длительности запросов | `histogram_quantile()` → p50/p95/p99 |
| `<service>_requests_in_flight` | Gauge | Количество текущих обрабатываемых запросов | Мониторинг перегрузки |

**Дополнительно (рекомендуется):**

| Метрика | Тип | Что измеряет | Зачем |
|:---|:---|:---|:---|
| `<service>_request_size_bytes` | Histogram | Размер входящего запроса | Анализ трафика |
| `<service>_response_size_bytes` | Histogram | Размер ответа | Планирование пропускной способности |

### Три обязательные метрики для фоновых задач

| Метрика | Тип | Что измеряет | Зачем |
|:---|:---|:---|:---|
| `<task>_last_success_timestamp_seconds` | Gauge | Unix-timestamp последнего успешного запуска | Алерт: `time() - last_success > threshold` |
| `<task>_runs_total{status="success|failed"}` | Counter | Количество запусков по статусу | `rate()` → частота успехов/ошибок |
| `<task>_duration_seconds` | Histogram | Длительность выполнения | p95 длительности, детекция регрессий |

## Практические сценарии

### Сценарий 1: HTTP REST API (Go / Python / Java)

Стандартный набор метрик для веб-API с использованием [client_libraries](../../Exporters/extensibility/client_libraries.md):

**Go (net/http middleware):**
```go
var (
    httpRequestsTotal = promauto.NewCounterVec(
        prometheus.CounterOpts{
            Name: "http_requests_total",
            Help: "Total number of HTTP requests.",
        },
        []string{"method", "handler", "status_code"},
    )

    httpRequestDuration = promauto.NewHistogramVec(
        prometheus.HistogramOpts{
            Name:    "http_request_duration_seconds",
            Help:    "Duration of HTTP requests in seconds.",
            Buckets: prometheus.DefBuckets,
        },
        []string{"method", "handler"},
    )

    httpRequestsInFlight = promauto.NewGauge(
        prometheus.GaugeOpts{
            Name: "http_requests_in_flight",
            Help: "Current number of HTTP requests being processed.",
        },
    )
)
```

**Python (Flask/FastAPI middleware):**
```python
from prometheus_client import Counter, Histogram, Gauge

REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
)

REQUEST_LATENCY = Histogram(
    'http_request_duration_seconds',
    'HTTP request latency in seconds',
    ['method', 'endpoint'],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

REQUESTS_IN_FLIGHT = Gauge(
    'http_requests_in_flight',
    'Current HTTP requests in progress'
)
```

**Примеры PromQL-запросов:**
```promql
# RPS по методам
sum by (method) (rate(http_requests_total[5m]))

# Доля 5xx ошибок
sum(rate(http_requests_total{status_code=~"5.."}[5m]))
/
sum(rate(http_requests_total[5m]))

# p99 латентности
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))

# Текущее количество запросов в обработке
http_requests_in_flight
```

### Сценарий 2: PostgreSQL / MySQL

Метрики для реляционных БД через стандартные экспортёры ([other_exporters](../../Exporters/other_exporters.md)):

**Ключевые метрики:**
```text
# Подключения (Gauge — USE: Utilization/Saturation)
pg_stat_activity_count{state="active"}          # Активные соединения
pg_stat_activity_count{state="idle"}            # Idle-соединения
pg_settings_max_connections                     # Лимит соединений

# Запросы (Counter — RED: Rate)
pg_stat_database_xact_commit{datname="mydb"}   # Успешные транзакции
pg_stat_database_xact_rollback{datname="mydb"} # Откаты транзакций
pg_stat_database_blks_hit{datname="mydb"}      # Cache hits
pg_stat_database_blks_read{datname="mydb"}     # Disk reads

# Размер (Gauge — USE: Utilization)
pg_database_size_bytes{datname="mydb"}         # Размер БД
pg_stat_database_tup_fetched{datname="mydb"}   # Выбранные строки

# Locks (Gauge — USE: Saturation)
pg_locks_count{mode="ExclusiveLock"}           # Блокировки
```

**Алерты:**
```promql
# Высокая доля disk reads (нет в кэше)
rate(pg_stat_database_blks_read[5m])
/
(rate(pg_stat_database_blks_hit[5m]) + rate(pg_stat_database_blks_read[5m])) > 0.1

# Истощение соединений
pg_stat_activity_count / pg_settings_max_connections > 0.8

# Рост числа lock-ов
pg_locks_count{mode="ExclusiveLock"} > 10
```

### Сценарий 3: Redis

**Ключевые метрики:**
```text
# Память (Gauge — USE: Utilization)
redis_memory_used_bytes
redis_memory_max_bytes
redis_mem_fragmentation_ratio

# Соединения (Gauge — USE: Saturation)
redis_connected_clients
redis_blocked_clients

# Трафик (Counter — RED: Rate)
redis_commands_processed_total
redis_commands_total{cmd="get"}
redis_commands_total{cmd="set"}

# Производительность (Gauge)
redis_instantaneous_ops_per_sec
redis_keyspace_hits_total
redis_keyspace_misses_total

# Replication (Gauge)
redis_connected_slaves
redis_master_repl_offset
```

**Алерты:**
```promql
# Высокий fragmentation ratio (утечка памяти)
redis_mem_fragmentation_ratio > 1.5

# Истощение памяти
redis_memory_used_bytes / redis_memory_max_bytes > 0.9

# Низкий hit rate
rate(redis_keyspace_hits_total[5m])
/
(rate(redis_keyspace_hits_total[5m]) + rate(redis_keyspace_misses_total[5m])) < 0.9
```

### Сценарий 4: RabbitMQ / Kafka

**RabbitMQ (RED):**
```text
# Сообщения (Counter — Rate)
rabbitmq_queue_messages_published_total{queue="orders"}
rabbitmq_queue_messages_delivered_total{queue="orders"}
rabbitmq_queue_messages_acknowledged_total{queue="orders"}

# Очередь (Gauge — Saturation)
rabbitmq_queue_messages{queue="orders"}              # Текущая длина
rabbitmq_queue_messages_ready{queue="orders"}        # Готовые к обработке
rabbitmq_queue_messages_unacked{queue="orders"}      # Не подтверждённые

# Соединения (Gauge)
rabbitmq_connections
rabbitmq_channels
```

**Kafka (RED):**
```text
# Продюсеры (Counter — Rate)
kafka_topic_messages_produced_total{topic="events"}
kafka_topic_bytes_produced_total{topic="events"}

# Консьюмеры (Counter — Rate + Gauge — Lag)
kafka_consumergroup_lag{consumergroup="my-group", topic="events"}
kafka_consumergroup_messages_consumed_total{consumergroup="my-group"}

# Брокеры (Gauge — USE)
kafka_broker_topics_partitions{topic="events"}
kafka_broker_under_replicated_partitions{topic="events"}
```

### Сценарий 5: Kubernetes Pod / Container

Метрики через [cadvisor](../../Exporters/cadvisor.md) и [node_exporter](../../Exporters/node_exporter.md):

**Container-level (USE):**
```text
# CPU (Counter — USE: Utilization через rate)
container_cpu_usage_seconds_total{container="nginx", pod="web-01", namespace="prod"}
container_cpu_cfs_throttled_seconds_total{container="nginx", pod="web-01"}

# Память (Gauge — USE: Utilization)
container_memory_working_set_bytes{container="nginx", pod="web-01"}
container_memory_rss{container="nginx", pod="web-01"}

# Лимиты (Gauge — статические)
container_spec_cpu_quota{container="nginx"}
container_spec_memory_limit_bytes{container="nginx"}

# Сеть (Counter — USE: Saturation/Errors)
container_network_receive_bytes_total{interface="eth0", pod="web-01"}
container_network_transmit_bytes_total{interface="eth0", pod="web-01"}
container_network_receive_errors_total{interface="eth0", pod="web-01"}
container_network_transmit_errors_total{interface="eth0", pod="web-01"}
```

**Полезные PromQL-вычисления:**
```promql
# CPU throttling ratio (доля throttled времени)
rate(container_cpu_cfs_throttled_seconds_total[5m])
/
rate(container_cpu_usage_seconds_total[5m])

# Memory usage vs limit (в процентах)
container_memory_working_set_bytes
/
container_spec_memory_limit_bytes * 100

# OOM-kill детекция
kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1
```

### Сценарий 6: Node / VM (bare-metal)

Метрики через [node_exporter](../../Exporters/node_exporter.md) (USE-метод):

**Утилизация (Utilization):**
```promql
# CPU (Gauge — доля от 0 до 1)
1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))

# Память (Gauge — в процентах)
(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100

# Диск (Gauge — в процентах)
(1 - node_filesystem_free_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100

# Сеть (Counter — байты/сек)
rate(node_network_receive_bytes_total{device!="lo"}[5m])
+ rate(node_network_transmit_bytes_total{device!="lo"}[5m])
```

**Насыщение (Saturation):**
```promql
# Load Average vs CPU cores
node_load1 / count by (instance) (node_cpu_seconds_total{mode="idle"})

# Disk I/O queue
node_disk_io_time_seconds_total  # Время обслуживания диска

# Ошибки сети
rate(node_network_receive_errs_total[5m])
+ rate(node_network_transmit_errs_total[5m])
```

### Сценарий 7: DNS-сервер (BIND / CoreDNS / Unbound)

```text
# Запросы (Counter — Rate)
dns_queries_total{server="dns-01", type="A"}
dns_queries_total{server="dns-01", type="AAAA"}

# Ответы (Counter — Rate)
dns_responses_total{server="dns-01", rcode="NOERROR"}
dns_responses_total{server="dns-01", rcode="NXDOMAIN"}

# Производительность (Histogram)
dns_query_duration_seconds{server="dns-01"}

# Кэш (Gauge)
dns_cache_size{server="dns-01", cache="response"}
dns_cache_hits_total{server="dns-01"}
dns_cache_misses_total{server="dns-01"}
```

### Сценарий 8: TLS-сертификаты

```text
# Gauge: дней до истечения
tls_certificate_expiry_seconds{domain="example.com"}
# Вычисление:
# (tls_certificate_expiry_seconds - time()) / 86400

# Counter: количество проверок
tls_certificate_check_total{domain="example.com", status="valid"}
tls_certificate_check_total{domain="example.com", status="expired"}
```

**Алерт:**
```promql
# Сертификат истечёт через 14 дней
(tls_certificate_expiry_seconds - time()) / 86400 < 14
```

### Сценарий 9: Бэкапы

```text
# Gauge: временная́я метка последнего успешного бэкапа
backup_last_success_timestamp_seconds{job="nightly-backup"}

# Counter: количество запусков
backup_runs_total{job="nightly-backup", status="success"}
backup_runs_total{job="nightly-backup", status="failed"}

# Gauge: размер последнего бэкапа
backup_size_bytes{job="nightly-backup"}

# Gauge: длительность последнего бэкапа
backup_duration_seconds{job="nightly-backup"}
```

**Алерты:**
```promql
# Бэкап не выполнялся более 25 часов
time() - backup_last_success_timestamp_seconds{job="nightly-backup"} > 25 * 3600

# Доля ошибок бэкапов выше 10%
rate(backup_runs_total{status="failed"}[24h])
/
rate(backup_runs_total[24h]) > 0.1
```

### Сценарий 10: GRPC-сервис

```text
# Запросы (Counter — Rate)
grpc_server_handled_total{grpc_method="GetUser", grpc_code="OK"}
grpc_server_handled_total{grpc_method="GetUser", grpc_code="NotFound"}

# Длительность (Histogram)
grpc_server_handling_seconds{grpc_method="GetUser"}

# Текущие запросы (Gauge)
grpc_server_started_total{grpc_method="GetUser"}
```

**Примечание:** GRPC-метрики обычно автоматически экспортируются библиотеками (Go `grpc_prometheus`, Java `micrometer`). Убедитесь, что interceptor добавлен в серверный pipeline.

## Дополнительная информация

### Чеклист инструментации нового сервиса

Перед деплоем нового сервиса в production проверьте:

- [ ] Экспортируется ли метрика `up` (встроенная в Prometheus) или кастомный health-check?
- [ ] Есть ли Counter для подсчёта событий (запросы, ошибки, задачи)?
- [ ] Есть ли Histogram/Summary для измерения длительности?
- [ ] Есть ли Gauge для текущих состояний (очереди, соединения, память)?
- [ ] Указаны ли базовые единицы в именах (`_seconds`, `_bytes`)?
- [ ] Есть ли суффикс `_total` для Counter?
- [ ] Лейблы имеют низкую кардинальность?
- [ ] Экспортёр корректно обрабатывает graceful shutdown (stale markers)?
- [ ] Метрики доступны на эндпоинте `/metrics`?
- [ ] Метрики не содержат секретов (токены, пароли, IP-адреса)?

### Антипаттерны инструментации

| Антипаттерн | Проблема | Решение |
|:---|:---|:---|
| **Gauge для событий** | Gauge не показывает накопленный итог; `rate()` на Gauge даёт отрицательные значения | Использовать Counter |
| **Counter для текущих значений** | Counter только растёт; нельзя показать "сколько сейчас" | Использовать Gauge |
| **Histogram без `+Inf` корзины** | `histogram_quantile()` не может вычислить квантиль выше максимальной границы | Всегда включать `+Inf` (по умолчанию в библиотеках) |
| **Слишком много лейблов** | Взрыв кардинальности → OOM Prometheus | Ограничить лейблы: `method`, `status_code`, `handler` |
| **Метрики без HELP/TYPE** | Prometheus не может определить тип и единицы | Всегда указывать `# HELP` и `# TYPE` |
| **Измерение размера ответа как Gauge** | Пиковые значения теряются между скрейпами | Использовать Histogram для распределения |
| **`irate()` в алертах** | Чувствителен к шуму и пропущенным скрейпам | Использовать `rate()` с окном `[5m]` |
| **Метрики с точками в имени (v2.x)** | Точки заменяются подчёркиваниями → несовместимость с OTel | Использовать подчёркивания или Prometheus v3.0+ |

### Связь с методологиями

| Методология | Компонент | Метрики | Тип |
|:---|:---|:---|:---|
| **RED** (Rate, Errors, Duration) | HTTP-сервисы, очереди, микросервисы | `requests_total`, `errors_total`, `duration_seconds` | Counter + Histogram |
| **USE** (Utilization, Saturation, Errors) | БД, диски, сеть, CPU, память | `usage_bytes`, `queue_depth`, `errors_total` | Gauge + Counter |
| **Golden Signals** (Latency, Traffic, Errors, Saturation) | Любой сервис | Комбинация RED + USE | Все типы |

### Приоритет метрик по критичности

| Приоритет | Метрика | Тип | Когда обязательна |
|:---|:---|:---|:---|
| **P0 — Критично** | Availability (up / health) | Gauge | Всегда |
| **P0 — Критично** | Error Rate (errors / total) | Counter | Всегда |
| **P1 — Важно** | Latency (p50, p95, p99) | Histogram | Для сервисов с SLA |
| **P1 — Важно** | Traffic (RPS / QPS) | Counter | Для сервисов с трафиком |
| **P2 — Полезно** | Saturation (queue, connections) | Gauge | Для stateful-компонентов |
| **P2 — Полезно** | Resource Usage (CPU, RAM, Disk) | Gauge | Для инфраструктуры |
| **P3 — Опционально** | Business Metrics (orders, revenue) | Counter/Gauge | По требованию бизнеса |

### См. также

- [Соглашения по именованию](./naming_conventions.md) — правила присвоения имён метрикам.
- [Типы метрик: обзор](./overview.md) — классификация типов и критерии выбора.
- [Counter](./counter.md) — детали счётчиков и `rate()`.
- [Histogram](./histogram.md) — распределения и перцентили.
- [Примеры алертов](./alerts.md) — типовые правила оповещений.
- [Методологии мониторинга](../../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md) — USE, RED, Golden Signals.
