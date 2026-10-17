# Vector: Надёжность и обработка ошибок

**Актуально для:** Vector 0.58.0

## Определения

- **Retry (Повтор)** — автоматическая повторная отправка событий в sink при ошибках. Vector использует exponential backoff с jitter для предотвращения retry storm.
- **Exponential Backoff + Jitter** — экспоненциальное увеличение задержки между попытками с случайным смещением для разрезания синхронных волн.
- **Circuit Breaker** — паттерн отказа: после N ошибок ограничивает или блокирует запросы, давая зависимости восстановиться. Vector реализует backpressure через Adaptive Request Concurrency (ARC), но circuit breaker на уровне sink требует внешнего паттерна.
- **Dead Letter Queue (DLQ)** — механизм перенаправления событий, не прошедших обработку или доставку, для последующего анализа и повторной обработки.
- **Rate Limiting** — ограничение скорости отправки запросов на стороне sink (не путать с transform `throttle`, который ограничивает события).
- **Acknowledgement** — подтверждение доставки: событие удаляется из буфера только после получения подтверждения от sink.
- **Bulkhead** — изоляция ресурсов для разных sink'ов/источников для предотвращения каскадных сбоев.

> **Связь с общими паттернами:** общая теория retry, circuit breaker, bulkhead и deadline budgeting изложена в **[Паттерны надёжности](../CI-CD/Core_Concepts/reliability_patterns.md)**. Здесь — Vector-специфичные конфиги.

## Retry Policy для Sinks

Vector автоматически переотправляет события при ошибках sink. Поведение настраивается через секцию `retry`:

```toml
[sinks.loki]
type = "loki"
inputs = ["normalize"]
endpoint = "http://loki:3100"

# Retry policy
[sinks.loki.retry]
max_retries = 10          # максимум попыток (0 = бесконечно, -1 = отключить retry)
initial_backoff_secs = 1  # начальная задержка
max_backoff_secs = 60     # максимальная задержка (обычно 10-60 сек)
timeout_secs = 300        # общий таймаут всех попыток (5 минут)
retryable_status_codes = [429, 503, 502, 504, 500]  # HTTP-коды для retry

[sinks.loki.request]
timeout_secs = 30          # таймаут одного HTTP-запроса
```

**Как работает backoff:**

1.  Первая попытка выполняется сразу.
2.  При неудаче ждём `initial_backoff_secs * 2^(attempt-1) * jitter`, где jitter — случайное значение 0.8–1.0.
3.  Задержка не превышает `max_backoff_secs`.
4.  Если суммарное время превышает `timeout_secs`, retry прекращается.

**Настройка под тип sink:**

| Sink | Когда retry не работает | Особенности |
| :--- | :--- | :--- |
| HTTP (Loki, ES, OpenSearch) | 4xx (кроме 429) | 429 всегда retryable |
| Kafka | При `acks=0` | Используйте `acks=all` для надёжности |
| ClickHouse | 4xx от ClickHouse | 500+ retryable |
| File | Любая ошибка записи | Диск должен быть доступен |

### Debug: как проверить retry-политику

```bash
# Включить trace-логирование для sink retry
VECTOR_LOG=trace vector --config /etc/vector/vector.yaml 2>&1 | grep -i "retry\|backoff"

# Мониторинг метрик retry
curl -s http://localhost:8686/metrics | grep "retries_total"
# → vector_sink_requests_retry_total{component="loki", status="429"} 12
```

## Acknowledgences и гарантии доставки

Vector поддерживает `at-least-once` delivery через acknowledgements. Событие удаляется из буфера **только после** подтверждения sink:

```toml
[sources.app_logs]
type = "file"
include = ["/var/log/app/*.log"]

[sinks.loki]
type = "loki"
inputs = ["app_logs"]
endpoint = "http://loki:3100"

# Включение acknowledgements — at-least-once delivery
[sinks.loki.acknowledgements]
enabled = true

# Disk buffer обязателен для at-least-once при рестарте
[sinks.loki.buffer]
type = "disk"
max_size = 2147483648  # 2 GiB
when_full = "block"
```

**Гарантии доставки:**

| Гарантия | Конфигурация | Потери данных |
| :--- | :--- | :--- |
| **At-most-once** (по умолчанию) | `acknowledgements.enabled = false`, `buffer.type = "memory"` | При падении: потеря событий в памяти |
| **At-least-once** | `acknowledgements.enabled = true` + `buffer.type = "disk"` | Возможны дубли при падении после записи, но до подтверждения |
| **Exactly-once** | Не поддерживается нативно | Требует идемпотентного sink или deduplication на стороне потребителя |

> **Важно:** `acknowledgements` работают только с `disk` buffer. С `memory` buffer при падении Vector данные будут потеряны даже при включённых acknowledgements.

## Rate Limiting на уровне Sink

Rate limiting ограничивает **число запросов** в секунду на стороне sink (не путать с transform `throttle`):

```toml
[sinks.loki]
type = "loki"
inputs = ["normalize"]
endpoint = "http://loki:3100"

[sinks.loki.request]
concurrency = 10                    # фиксированная concurrency (или "adaptive")
rate_limit_num = 100                # максимум 100 запросов...
rate_limit_period_secs = 1          # ...в секунду
timeout_secs = 30
```

**Adaptive Request Concurrency (ARC):** при `concurrency = "adaptive"` Vector автоматически регулирует количество одновременных запросов на основе латентности. Алгоритм:

1.  Vector измеряет `latency = response_time` для каждого sink.
2.  Если latency растёт, уменьшает `concurrency`.
3.  Если latency стабильен, увеличивает `concurrency` до `max_concurrency`.

```toml
[sinks.loki.request]
concurrency = "adaptive"  # авто-подстройка
max_concurrency = 20      # верхний предел
```

## Dead Letter Queue (DLQ)

DLQ перенаправляет события, не прошедшие трансформацию или доставку. Есть два подхода:

### 1. Reroute dropped events на отдельный sink

```toml
[sources.app_logs]
type = "file"
include = ["/var/log/app/*.log"]

# Основной transform с reroute_dropped
[transforms.parse_json]
type = "remap"
inputs = ["app_logs"]
source = '''
. = parse_json(.message)
'''
reroute_dropped = true  # события с ошибками VRL → выход .dropped

# DLQ sink (локальный файл для анализа)
[sinks.dlq_file]
type = "file"
inputs = ["parse_json.dropped"]  # только dropped события
path = "/var/log/vector/dlq.json"
encoding.codec = "json"
```

### 2. Blackhole sink для DLQ с логированием

```toml
# Blackhole sink для отслеживания потерь
[sinks.dlq_blackhole]
type = "blackhole"
inputs = ["parse_json.dropped"]
# В metrics будет: vector_sink_processed_events_total{drop=true}
```

### 3. DLQ в отдельный Loki индекс

```toml
[sinks.loki_dlq]
type = "loki"
inputs = ["parse_json.dropped"]
endpoint = "http://loki:3100"
labels = { level = "error", source = "vector_dlq" }
```

**Мониторинг DLQ:**

```bash
# Количество событий в DLQ
vector top
# → parse_json.dropped: Events Out 5/s

# Метрика в Prometheus
# vector_component_sent_events_total{component="parse_json", output="dropped"}
```

## Circuit Breaker для sink

Встроенного circuit breaker в Vector нет. Паттерн реализуется двумя способами:

### Способ 1: Route-based fallback

```toml
[transforms.route_by_health]
type = "route"
inputs = ["parse_json"]
# Если событие помечено как "проблемное" — в отдельный sink
route.fallback = '.is_error == true'
route.main = '.is_error != true'

# Основной sink (с высокой нагрузкой)
[sinks.loki_main]
type = "loki"
inputs = ["route_by_health.main"]
endpoint = "http://loki:3100"

# Fallback sink (локальный файл при недоступности Loki)
[sinks.fallback_file]
type = "file"
inputs = ["route_by_health.fallback"]
path = "/var/log/vector/fallback.log"
```

### Способ 2: External proxy (Envoy/HAProxy)

Развёртывание Envoy перед sink с circuit breaking:

```yaml
# envoy.yaml (упрощённо)
static_resources:
  listeners:
  - name: loki_listener
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          route_config:
            virtual_hosts:
            - name: loki_backend
              domains: ["*"]
              routes:
              - match: { prefix: "/" }
                route:
                  cluster: loki_cluster
                  max_grpc_attempts: 5  # retry
                typed_retry_policy:
                  retry_host_predicates:
                  - name: envoy.retry_host_predicates.previous_hosts
  clusters:
  - name: loki_cluster
    circuit_breakers:
      thresholds:
      - priority: DEFAULT
        max_connections: 100
        max_pending_requests: 100
        max_requests: 100
```

Vector отправляет на `http://envoy:10080` вместо `http://loki:3100`.

## Bulkhead: изоляция по sink

Для предотвращения каскадных сбоев используйте отдельные sink для разных приоритетов трафика:

```toml
# Высокоприоритетный sink (audit логи)
[sources.audit_logs]
type = "file"
include = ["/var/log/app/audit.log"]

[sinks.loki_audit]
type = "loki"
inputs = ["audit_logs"]
endpoint = "http://loki:3100"
labels = { priority = "high" }
# Отдельный буфер и concurrency
[sinks.loki_audit.buffer]
type = "disk"
max_size = 536870912
[sinks.loki_audit.request]
concurrency = 10

# Низcopриоритетный sink (debug логи)
[sources.debug_logs]
type = "file"
include = ["/var/log/app/debug.log"]

[sinks.loki_debug]
type = "loki"
inputs = ["debug_logs"]
endpoint = "http://loki:3100"
labels = { priority = "low" }
[sinks.loki_debug.buffer]
type = "memory"
[sinks.loki_debug.request]
concurrency = 2
```

## Операции и команды

### Отладка retry и ошибок sink

```bash
# 1. Проверка состояния sink через vector top
vector top --components 'sink_*'
# → loki_sink: Events Out 1500/s, Errors 0, Buffer Size 0

# 2. Просмотр retry-событий в tap
vector tap loki.request_errors
# → {"error":"connection refused","retry_count":3}

# 3. Мониторинг метрик retry
curl -s http://localhost:8686/metrics | grep -E "retry|error|dropped"
# → vector_sink_requests_retry_total{component="loki"} 42
# → vector_sink_request_errors_total{component="loki"} 3
# → vector_component_discarded_events_total{component="parse_json"} 5
```

### Graceful shutdown

```bash
# 1. Отправка SIGTERM (graceful shutdown с таймаутом)
systemctl stop vector
# → Vector завершает обработку буфера и закрывает соединения

# 2. Принудительная остановка (без graceful — может повредить disk buffer)
kill -9 $(pidof vector)
# → Требует восстановления buffer через --repair-data-dir
```

## Устранение неполадок

### События накапливаются в буфере

**Симптом:** `vector_buffer_utilization > 0.9`.

**Причины и решения:**

| Причина | Решение |
| :--- | :--- |
| Sink медленно пишет (низкая пропускная способность хранилища) | Увеличить `batch.max_bytes`/`batch.timeout_secs`, добавить реплики sink |
| `request.concurrency` слишком низок | Увеличить до `adaptive` или руками |
| Network latency к sink | Проверить через `mtr`/`ping`, добавить буферный сервер |
| Sink возвращает 5xx | Включить retry с backoff, добавить circuit breaker |

### Retry storm при массовом сбое

**Симптом:** Рост `vector_sink_requests_retry_total` и нагрузка на downstream в 5-10x.

**Диагностика:**

```bash
# 1. Проверить частоту retry
curl -s http://localhost:8686/metrics | grep "retry_total" | head -5

# 2. Проверить latency sink
vector top --human-metrics
# → latency_seconds должна расти экспоненциально

# 3. Ограничить retry через конфиг
# [sinks.loki.retry]
# max_retries = 3
# timeout_secs = 30  # не более 30 секунд на попытки
```

### DLQ растёт неконтролируемо

**Симптом:** `vector_component_discarded_events_total` растёт, DLQ файл растёт.

**Решение:**

1.  Проверить VRL-программу через `vector tap <transform>.dropped`.
2.  Добавить `parse_json` с обработкой ошибок вместо `parse_json!`:
    ```vrl
    parsed, err = parse_json(.message)
    if err != null {
        .parse_error = string!(err)
    } else {
        . = parsed
    }
    ```
3.  Настроить алерт на рост DLQ (см. [meta-monitoring](../Concepts/Observability_and_Monitoring/meta-monitoring.md)).

## Лучшие практики

### Политика retry

1.  **Ограничьте max_retries:** для HTTP sinks используйте `max_retries = 10` (не бесконечно). Для Kafka — `max_retries = 5`.
2.  **Используйте jitter:** Vector делает это автоматически, но можно дополнительно настроить `initial_backoff_secs` и `max_backoff_secs`.
3.  **Устанавливайте timeout_secs:** не допускайте бесконечного retry — `timeout_secs = 300` (5 минут) для большинства sink.
4.  **Retry для retryable статусов:** включайте только `429, 502, 503, 504` — не retry для `400, 401, 403, 404`.

### Политика DLQ

1.  **Всегда включайте `reroute_dropped = true`** в remap transforms — события с ошибками VRL не исчезают, а попадают в DLQ.
2.  **DLQ в файл + мониторинг:** используйте `blackhole` или `file` sink для DLQ с записью в отдельный файл. Настраивайте алерт на рост.
3.  **Не храните DLQ бесконечно:** добавляйте TTL через logrotate или отдельный transform с таймаутом.

### Политика acknowledgements

1.  **Disk buffer + acknowledgements = at-least-once.** Для критичных пайплайнов (audit logs, security logs) всегда включайте оба.
2.  **Для не критичных данных:** можно использовать `memory` buffer без acknowledgements (at-most-once) для экономии I/O.
3.  **Проверяйте backpressure:** если `acknowledgements` включены и sink медленно отвечает, Vector может накапливать события в буфере. Мониторьте `component_buffer_*`.

### Отказоустойчивость

1.  **Не полагайтесь на Vector как SPOF:** для production используйте несколько aggregator-инстансов с round-robin или load balancer перед sink.
2.  **Circuit breaker на уровне инфраструктуры:** если sink не поддерживает circuit breaking, используйте Envoy/HAProxy перед ним.
3.  **Bulkhead:** отдельные sink для разных приоритетов трафика — сбой одного не влияет на другой.

## Дополнительная информация

- **Общие паттерны надёжности:** [Паттерны надёжности](../CI-CD/Core_Concepts/reliability_patterns.md)
- **Мета-мониторинг с алертами:** [Meta-monitoring — Сценарий 5: Vector + Loki](../Concepts/Observability_and_Monitoring/meta-monitoring.md)
- **Backpressure и буферизация:** [Vector Overview — Обеспечение надёжности](./vector_overview.md#обеспечение-надёжности)
- **Официальная документация:** [Vector Reliability](https://vector.dev/docs/administration/reliability/)