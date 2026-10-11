# ClickHouse — Наблюдаемость (логи, метрики, трейсы)

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Предварительные требования

| Требование | Минимальная версия / значение | Примечание |
| :--- | :--- | :--- |
| ClickHouse Server | 26.8.x (LTS) / 26.9.x (Stable) | TimeSeries движок требует 26.8+ |
| ClickHouse Client | Соответствует серверу | Для `clickhouse-client --dialect promql` |
| Prometheus | 2.45+ | Поддержка `remote_write` v1 |
| OTel Collector Contrib | 0.110+ | `clickhouseexporter` только в Contrib |
| Vector | 0.40+ | ClickHouse sink (HTTP/Arrow) |
| Jaeger | 2.18.0+ | Нативный бэкенд ClickHouse (экспериментальный) |
| Сеть | HTTP 8123/8443, Native 9000/9440 | Порты открыты между компонентами |
| Диск | SSD/NVMe, 500 GB+ на узел | Для горячей телеметрии (TTL 30 дней) |
| RAM | 64 GB+ на узел | Для батчинга и MergeTree пула |
| CPU | 16+ ядер | Для сжатия и агрегации |

**Настройка пользователя для телеметрии:**
```sql
CREATE USER telemetry_writer IDENTIFIED WITH sha256_password BY '<hash>'
    SETTINGS
        enable_time_series_table = 1,
        async_insert = 1,
        wait_for_async_insert = 1,
        async_insert_max_data_size = 10485760,
        max_insert_threads = 8;
GRANT INSERT, SELECT ON prometheus.* TO telemetry_writer;
GRANT INSERT, SELECT ON otel.* TO telemetry_writer;
GRANT INSERT, SELECT ON logs.* TO telemetry_writer;
```

## Определения

**Observability pipeline** — конвейер сбора телеметрии (logs, metrics, traces) в ClickHouse для аналитики и алертинга.

**remote_write** — протокол Prometheus для отправки метрик в удалённое хранилище. ClickHouse принимает его через HTTP-handler `prometheus_api_v1`, пишущий в таблицу движка `TimeSeries`.

**TimeSeries** — табличный движок ClickHouse для временных рядов (метрика + теги + сэмплы). Данные физически хранит во внутренних таблицах: `samples` (MergeTree), `recent samples` (TTL, по умолчанию 4 дня), `tags` (AggregatingMergeTree, текстовый индекс `keyValuePairs` на карте тегов), `metric families` (ReplacingMergeTree). Работа gated настройкой `enable_time_series_table`.

**OTel Collector** — агент/gateway из проекта OpenTelemetry: принимает телеметрию (OTLP, filelog, syslog и др.), обрабатывает и экспортирует в бэкенды. ClickHouse exporter входит только в **Collector Contrib** (не в core-дистрибутив).

**OTLP** — OpenTelemetry Protocol (gRPC :4317 / HTTP :4318). **ClickHouse server не имеет встроенного OTLP-приёмника** — приём реализуется через OTel Collector с clickhouse exporter (нативный TCP :9000 или HTTP :8123).

**clickhouse exporter** — экспортер OTel Collector Contrib, пишущий traces/logs/metrics/profiles в ClickHouse. Создаёт таблицы `otel_traces`, `otel_logs`, `otel_metrics_*` (при `create_schema: true`).

**opentelemetry_span_log** — системная таблица `system.opentelemetry_span_log` со спанами, которые **генерирует сам ClickHouse** при выполнении запросов (включена по умолчанию). Направление обратное приёму: экспорт в Jaeger/Zipkin.

**Jaeger** — система распределённого трейсинга. Jaeger v2 (с v2.18.0) имеет нативный экспериментальный бэкенд ClickHouse (feature gate `storage.clickhouse`, StageAlpha; поддерживает ClickHouse 26.x).

**Vector** — агент сбора телеметрии; поддерживает ClickHouse как sink (HTTP :8123, форматы `json_each_row` / `arrow_stream`).

**Downsampling** — снижение гранулярности старых метрик (агрегация 1m → 1h) для экономии хранения.

## Основные концепции

### Три pillar-а в ClickHouse

| Pillar | Приём в ClickHouse | Типичная схема |
| :--- | :--- | :--- |
| **Metrics** | Prometheus `remote_write` → handler `prometheus_api_v1` → движок `TimeSeries` | `prometheus.metrics` (metric_name, tags, samples) |
| **Logs** | OTel Collector (filelog/OTLP) или Vector/Fluentd → HTTP `:8123` | `logs` (timestamp, level, service, message) |
| **Traces** | OTel Collector (OTLP-приёмник) → clickhouse exporter → нативный `:9000` | `otel_traces` (Timestamp, TraceId, ServiceName, Duration) |

### Почему ClickHouse для observability

- Колоночное хранение + сжатие: логи и метрики сжимаются в 10–100 раз.
- SQL для аналитики: один язык для запросов к логам, метрикам и трейсам.
- Высокая скорость вставки: десятки миллионов событий в секунду на узел.
- TTL: автоматическое удаление или перемещение старых данных.

### Архитектура приёма

```
[Prometheus] --remote_write--> [ClickHouse HTTP :8123 /prometheus/api/v1/write] --> [TimeSeries таблица]
[OTLP SDK]   --OTLP :4317/4318--> [OTel Collector] --clickhouse exporter :9000--> [otel_traces / otel_logs]
[Vector]     --Arrow/JSON sink--> [ClickHouse HTTP :8123] ----------------------> [logs таблица]
[Jaeger v2]  --storage (feature gate)--> [ClickHouse native :9000] -------------> [jaeger_v2.spans]
[ClickHouse] --собственные спаны--> system.opentelemetry_span_log --> (MV/URL) --> [Zipkin / Jaeger]
```

### Разграничение: приём vs экспорт

Три разных механизма, которые путают из-за слова «Prometheus»:

| Задача | Механизм | Порт |
| :--- | :--- | :--- |
| **При**ём метрик из Prometheus (remote_write) | `<http_handlers>` + handler `prometheus_api_v1` + движок `TimeSeries` | HTTP `8123`/`8443` |
| **Эк**спорт собственных метрик ClickHouse для скрейпа | секция `<prometheus>` (exporter, `/metrics`) | `9363` |
| **Эк**спорт собственных трейсов ClickHouse | `system.opentelemetry_span_log` + MV/URL или OTel Collector | — |

Экспортёр метрик на `9363` и системные таблицы мониторинга описаны в **[Мониторинг и системные таблицы](./clickhouse-monitoring.md)**.

## Практические сценарии

### Приём метрик Prometheus (remote_write)

**Шаг 1. Настроить handler на основном HTTP-порту сервера:**

```xml
<!-- config.d/prometheus_api.xml -->
<clickhouse>
    <http_handlers>
        <defaults/>
        <rule>
            <url_prefix>/prometheus/api/v1</url_prefix>
            <handler>
                <type>prometheus_api_v1</type>
                <!-- фиксированная таблица; без этих строк таблица задаётся
                     параметрами database/table в каждом запросе -->
                <database>prometheus</database>
                <table>metrics</table>
            </handler>
        </rule>
    </http_handlers>
</clickhouse>
```

`<defaults/>` сохраняет встроенные обработчики (`/ping`, SQL-запросы). Один handler обслуживает все эндпоинты: `/prometheus/api/v1/write` (remote write), `/read` (remote read), `/query` и `/query_range` (PromQL), `/series`, `/metadata`, `/format_query`.

**Шаг 2. Создать таблицу движка TimeSeries:**

```sql
-- Включить движок для пользователя (однократно или в профиле пользователя)
SET enable_time_series_table = 1;

CREATE DATABASE prometheus;
CREATE TABLE prometheus.metrics ENGINE = TimeSeries;
```

Движок создаёт внутренние таблицы автоматически. Полезные настройки при создании: `SAMPLES INNER COLUMNS (...)` — типы сэмплов, `TAGS INNER COLUMNS (...)` — дополнительные колонки тегов, `SETTINGS tags_to_columns = {'instance': 'instance'}` — выносить горячие теги в отдельные колонки, `recent_samples_ttl_seconds` — окно быстрой недавней выборки (по умолчанию 345600 = 4 дня).

**Шаг 3. Настроить Prometheus на отправку:**

```yaml
# prometheus.yml
remote_write:
  - url: http://clickhouse:8123/prometheus/api/v1/write?database=prometheus&table=metrics
    basic_auth:
      username: telemetry_writer
      password: <password>
```

Для продакшена — HTTPS-порт `8443` и TLS. Асинхронные вставки батчат remote_write-запросы: `async_insert=1` в URL или в профиле пользователя (в версиях 26.8+ `async_insert` включён по умолчанию; `async_insert=0` возвращает синхронное поведение). Запрос подтверждается только после flush во внутренние таблицы `TimeSeries` — гарантия durable-write.

**Проверка приёма:**

```bash
# PromQL через HTTP-эндпоинт
curl --user telemetry_writer:<password> --get "http://clickhouse:8123/prometheus/api/v1/query" \
  --data-urlencode "query=up" \
  --data-urlencode "database=prometheus" \
  --data-urlencode "table=metrics"
# → {"status":"success","data":{"resultType":"vector","result":[{"metric":{"__name__":"up","instance":"..."},"value":[1234567890.123,"1"]}]}}

# PromQL из clickhouse-client
clickhouse-client --dialect promql --promql_database prometheus --promql_table metrics \
  --query 'up'
# → 1

# SQL напрямую по внешним колонкам таблицы
SELECT metric_name, tags, samples FROM prometheus.metrics LIMIT 5;
# → metric_name: up, tags: {'instance': '...'}, samples: [1]
```

**Ожидаемый результат:** Запрос `up` возвращает вектор с метрикой `up=1` для каждого целевого инстанса. В `system.inserts` видна активная вставка в `prometheus.metrics`.

**Grafana:** Prometheus datasource с базовым URL `http://clickhouse:8123/prometheus` (`httpMethod: POST`, `customQueryParameters: database=prometheus&table=metrics`). Embed PromQL в SQL — table functions `prometheusQuery()` / `prometheusQueryRange()`.

### Приём трейсов и логов через OTel Collector

**Предварительные требования:** OTel Collector Contrib 0.110+, ClickHouse 26.8+, сеть между Collector и ClickHouse (порт 9000 или 8123).

ClickHouse server не принимает OTLP напрямую. Развертывается OTel Collector (Contrib-дистрибутив) с clickhouse exporter:

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318
  filelog:
    include: [/var/log/app/*.log]
    start_at: beginning

processors:
  batch:
    timeout: 5s
    send_batch_size: 10000   # рекомендуется >= 10000; до 100000 при достаточной RAM
  memory_limiter:
    check_interval: 1s
    limit_mib: 2048

exporters:
  clickhouse:
    endpoint: tcp://clickhouse:9000?dial_timeout=10s&compress=lz4&async_insert=1
    database: otel
    create_schema: true        # в продакшене — false и собственная схема
    ttl: 72h
    traces_table_name: otel_traces
    logs_table_name: otel_logs
    timeout: 5s
    sending_queue:
      queue_size: 10000
    retry_on_failure:
      enabled: true
      initial_interval: 5s
      max_interval: 30s
      max_elapsed_time: 300s

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [clickhouse]
    logs:
      receivers: [filelog]
      processors: [memory_limiter, batch]
      exporters: [clickhouse]
```

Параметры экспортера: `endpoint` — `tcp://` (нативный протокол, порт `9000`; TLS — `secure=true` на `9440`) или `http://` (порт `8123`); `metrics_tables` — имена таблиц для `gauge`/`sum`/`summary`/`histogram`/`exponential_histogram`; `profiles_table_name` (по умолчанию `otel_profiles`). Экспортёр также создаёт вспомогательную таблицу `otel_traces_trace_id_ts` для быстрого поиска по `trace_id`.

**Рекомендуемая схема трейсов** (сокращённая; полная — в документации по schema design):

```sql
CREATE TABLE otel.otel_traces
(
    `Timestamp` DateTime64(9) CODEC(Delta(8), ZSTD(1)),
    `TraceId` String CODEC(ZSTD(1)),
    `SpanId` String CODEC(ZSTD(1)),
    `ParentSpanId` String CODEC(ZSTD(1)),
    `SpanName` LowCardinality(String) CODEC(ZSTD(1)),
    `SpanKind` LowCardinality(String) CODEC(ZSTD(1)),
    `ServiceName` LowCardinality(String) CODEC(ZSTD(1)),
    `ResourceAttributes` Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    `SpanAttributes` Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    `Duration` Int64 CODEC(ZSTD(1)),
    `StatusCode` LowCardinality(String) CODEC(ZSTD(1)),
    `StatusMessage` String CODEC(ZSTD(1)),
    `Events.Timestamp` Array(DateTime64(9)) CODEC(ZSTD(1)),
    `Events.Name` Array(LowCardinality(String)) CODEC(ZSTD(1)),
    `Events.Attributes` Array(Map(LowCardinality(String), String)) CODEC(ZSTD(1)),
    `Links.TraceId` Array(String) CODEC(ZSTD(1)),
    `Links.SpanId` Array(String) CODEC(ZSTD(1)),
    `Links.Attributes` Array(Map(LowCardinality(String), String)) CODEC(ZSTD(1)),
    INDEX idx_trace_id TraceId TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_res_attr_key mapKeys(ResourceAttributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_span_attr_key mapKeys(SpanAttributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_duration Duration TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree
PARTITION BY toDate(Timestamp)
ORDER BY (ServiceName, SpanName, toDateTime(Timestamp))
TTL toDate(Timestamp) + INTERVAL 30 DAY;
```

**Проверка приёма:**

```sql
-- Спаны за последний час
SELECT ServiceName, count() AS spans, avg(Duration) AS avg_duration_ns
FROM otel.otel_traces
WHERE Timestamp > now() - INTERVAL 1 HOUR
GROUP BY ServiceName;
-- → ServiceName: frontend, spans: 12450, avg_duration_ns: 45000000

-- Поиск спанов по trace_id (через вспомогательную таблицу экспортёра)
WITH '391dae938234560b16bb63f51501cb6f' AS trace_id,
     (SELECT min(Start) FROM otel.otel_traces_trace_id_ts WHERE TraceId = trace_id) AS start,
     (SELECT max(End) + 1 FROM otel.otel_traces_trace_id_ts WHERE TraceId = trace_id) AS end
SELECT Timestamp, SpanName, ServiceName, Duration
FROM otel.otel_traces
WHERE TraceId = trace_id AND Timestamp >= start AND Timestamp <= end;
-- → Timestamp: 2026-10-08 10:30:00.123456789, SpanName: GET /api/users, ServiceName: frontend, Duration: 125000000
```

**Ожидаемый результат:** Агрегация по сервисам показывает ненулевое количество спанов. Поиск по `trace_id` возвращает цепочку спанов с корректными таймингами. В логах Collector — отсутствие ошибок `exporter/clickhouse`.

### Приём логов через Vector

**Предварительные требования:** Vector 0.40+, ClickHouse 26.8+, HTTP 8123 доступен.

Vector поддерживает ClickHouse как sink (HTTP `:8123`). Детали конфигурации — в **[Vector: практические сценарии](../../Vector/practical_scenarios.md)**.

```toml
[sources.app_logs]
type = "file"
include = ["/var/log/app/*.log"]

[sinks.clickhouse]
type = "clickhouse"
inputs = ["app_logs"]
endpoint = "http://clickhouse:8123"
database = "logs"
table = "raw_events"
format = "json_each_row"
compression = "gzip"
skip_unknown_fields = true
batch.max_bytes = 10485760   # 10 MB батчи
```

Формат `arrow_stream` (Apache Arrow IPC, v0.55+) даёт лучшую производительность: схема таблицы запрашивается при старте, типы маппятся в Arrow. Ограничения: `table`/`database` должны быть статическими, колонки `IPv4`/`IPv6` не поддерживаются — для них используйте JSON-формат.

```sql
-- Таблица логов
CREATE TABLE logs
(
    timestamp DateTime64(3),
    level LowCardinality(String),
    service LowCardinality(String),
    host LowCardinality(String),
    message String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (service, timestamp)
TTL timestamp + INTERVAL 30 DAY;
```

**Проверка приёма:**

```sql
SELECT service, count() AS events
FROM logs
WHERE timestamp > now() - INTERVAL 10 MINUTE
GROUP BY service;
-- → service: api-gateway, events: 5420
-- → service: payment-service, events: 1230
```

**Ожидаемый результат:** Количество событий растёт в соответствии с логами приложений. В `system.inserts` видна активная вставка в `logs.raw_events`. В логах Vector — отсутствие ошибок `clickhouse` sink.

### Собственные трейсы ClickHouse (opentelemetry_span_log)

**Предварительные требования:** ClickHouse 26.8+ (таблица включена по умолчанию).

ClickHouse генерирует спаны для своих запросов и хранит их в `system.opentelemetry_span_log` (включена по умолчанию в `config.xml`; таблица без `event_time` — сортировка `(finish_date, finish_time_us, trace_id)`, TTL задаётся внутри `<engine>`).

```sql
-- Включить генерацию спанов для запросов
SET opentelemetry_trace_processors = 1;
SET opentelemetry_start_trace_probability = 1;   -- 1 = все запросы

-- Трейсы конкретного запроса
SELECT toString(trace_id) AS traceID, toString(span_id) AS spanID,
       operation_name, start_time_us, finish_time_us - start_time_us AS duration_ns
FROM system.opentelemetry_span_log
WHERE attribute['clickhouse.query_id'] = '<query_id>'
ORDER BY start_time_us;
```

**Проверка приёма:**

```sql
-- Проверить, что трассировка активна
SELECT count() FROM system.opentelemetry_span_log
WHERE finish_date = today();
-- → 15420 (ненулевое значение)
```

**Ожидаемый результат:** Запрос возвращает спаны с корректными `trace_id`, `span_id`, `operation_name` (например, `DB::executeQuery`, `MergeTree::read`). Длительность в наносекундах соответствует реальному времени выполнения.

Экспорт в Jaeger/Zipkin: для тестов — materialized view с `ENGINE = URL(...)`, пушащая спаны в HTTP-коллектор; в продакшене — регулярный экспорт через OTel Collector. Детали — в **[Мониторинг и системные таблицы](./clickhouse-monitoring.md)** (секция профилирования) и в [документации ClickHouse](https://clickhouse.com/docs/en/operations/opentelemetry).

### Хранение трейсов Jaeger

**Предварительные требования:** Jaeger v2.18.0+, ClickHouse 26.x, feature gate `storage.clickhouse` (StageAlpha — экспериментальный).

Jaeger v2 (с v2.18.0) имеет нативный бэкенд ClickHouse — **экспериментальный** (feature gate `storage.clickhouse`, StageAlpha; схема может меняться в breaking-изменениями; поддерживает ClickHouse 26.x).

```bash
# Запуск Jaeger с бэкендом ClickHouse
go run ./cmd/jaeger --config cmd/jaeger/config-clickhouse.yaml --feature-gates=storage.clickhouse
```

При `create_schema: true` таблицы создаются автоматически (БД `jaeger_v2`): `spans` (одна строка на спан, атрибуты в `Nested`-колонках; `PARTITION BY toDate(start_time)`, `ORDER BY (service_name, name, toDateTime(start_time))`, `bloom_filter` на `trace_id`, `minmax` на `duration`), `services`, `operations`, `trace_id_timestamps`, `attribute_metadata`, `dependencies`. Вспомогательные таблицы заполняются materialized views.

**Проверка приёма:**

```sql
-- Проверить, что спаны пишутся
SELECT service_name, count() AS spans
FROM jaeger_v2.spans
WHERE start_time > now() - INTERVAL 10 MINUTE
GROUP BY service_name;
-- → service_name: frontend, spans: 8920
```

**Ожидаемый результат:** Спаны появляются в таблице `jaeger_v2.spans` с корректными `service_name`, `trace_id`, `span_id`. В UI Jaeger трейсы отображаются корректно.

Схема, конфигурация и оптимизация — в **[Jaeger: глубокое погружение в хранение](../../Jaeger/jaeger_storage_deep_dive.md)**.

### Downsampling метрик

**Предварительные требования:** Таблица метрик с сырыми данными (TimeSeries или MergeTree), настроенные TTL.

Снижение гранулярности старых данных для экономии хранения:

```sql
-- Целевая таблица (однократно)
CREATE TABLE metrics_hourly
(
    hour DateTime,
    name LowCardinality(String),
    labels Map(LowCardinality(String), String),
    avg_value Float64,
    max_value Float64,
    min_value Float64,
    cnt UInt64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(hour)
ORDER BY (name, hour, labels);

-- Агрегация 1-минутных метрик в почасовые (запускать по расписанию,
-- например systemd-timer/cron, раз в час)
INSERT INTO metrics_hourly
SELECT
    toStartOfHour(timestamp) AS hour,
    name,
    labels,
    avg(value) AS avg_value,
    max(value) AS max_value,
    min(value) AS min_value,
    count() AS cnt
FROM metrics
WHERE timestamp < now() - INTERVAL 7 DAY
  AND timestamp >= now() - INTERVAL 8 DAY
GROUP BY hour, name, labels;
```

**Проверка результата:**

```sql
-- Проверить агрегацию за прошлый день
SELECT hour, name, avg_value, cnt
FROM metrics_hourly
WHERE hour >= today() - INTERVAL 2 DAY
ORDER BY hour DESC LIMIT 10;
-- → hour: 2026-10-07 14:00:00, name: http_requests_total, avg_value: 1245.5, cnt: 60
```

**Ожидаемый результат:** Каждая часовая запись имеет `cnt = 60` (60 минут × 1 сэмпл/мин). Значения `avg_value`, `max_value`, `min_value` соответствуют ожидаемым для метрики.

Альтернатива для горячей агрегации — materialized view с `toStartOfHour()`; для долгосрочного хранения сырых метрик — перемещение партиций на холодный диск/S3 (см. **[Интеграция ClickHouse и S3](./clickhouse_s3_integration.md)**).

## Операции и команды

```sql
-- Активные вставки телеметрии
SELECT * FROM system.inserts;

-- Рост частей в таблицах приёма (всплеск = проблемы с батчингом)
SELECT database, table, count() AS parts
FROM system.parts
WHERE active AND database IN ('otel', 'prometheus', 'logs')
GROUP BY database, table;

-- Ошибки вставок за период
SELECT exception, count() AS cnt
FROM system.query_log
WHERE type IN ('ExceptionWhileProcessing', 'ExceptionBeforeStart')
  AND event_time > now() - INTERVAL 1 HOUR
GROUP BY exception
ORDER BY cnt DESC;

-- Статистика батчинга async_insert
SELECT
    formatReadableSize(sum(rows)) AS total_rows,
    formatReadableSize(sum(bytes)) AS total_bytes,
    count() AS batches
FROM system.query_log
WHERE query_kind = 'Insert'
  AND type = 'QueryFinish'
  AND event_time > now() - INTERVAL 1 HOUR
  AND query LIKE '%async_insert%';

-- Размер таблиц телеметрии
SELECT
    database,
    table,
    formatReadableSize(sum(bytes_on_disk)) AS size,
    sum(rows) AS rows,
    max(modification_time) AS last_modified
FROM system.parts
WHERE active AND database IN ('otel', 'prometheus', 'logs', 'jaeger_v2')
GROUP BY database, table
ORDER BY sum(bytes_on_disk) DESC;

-- Проверка TTL на таблицах
SELECT database, table, partition,
       toDateTime(ttl_infos[1].where_expression) AS ttl_expr
FROM system.parts
WHERE active AND database IN ('otel', 'prometheus', 'logs')
  AND ttl_infos IS NOT NULL
GROUP BY database, table, partition, ttl_infos
ORDER BY database, table;

-- Асинхронная очередь вставок
SELECT * FROM system.asynchronous_insert_queue
WHERE table IN ('metrics', 'otel_traces', 'otel_logs', 'raw_events');
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| remote_write возвращает 404 | Нет правила `<http_handlers>` с `url_prefix=/prometheus/api/v1` | Добавить правило в `config.xml`, перезапустить сервер |
| remote_write возвращает 401 | Нет `basic_auth` в `prometheus.yml` | Задать пользователя/пароль в URL или в профиле |
| Ошибка `Unknown table engine TimeSeries` | Не включён `enable_time_series_table` для пользователя | `SET enable_time_series_table = 1` или в профиле пользователя |
| Метрики не читаются по PromQL | Таблица не указана в запросе | Параметры `database`/`table` в URL или фиксированная таблица в handler |
| Трейсы не приходят | Коллектор без clickhouse exporter (он есть только в Contrib) | Использовать otelcol-contrib; проверить `endpoint` (`tcp://...:9000`) |
| Таблиц `otel_traces`/`otel_logs` нет | `create_schema: false` без предварительного создания | Создать схему вручную или включить `create_schema` |
| Логи дублируются | Retry Vector/коллектора после таймаута | Дедупликация по `event_id` или `ReplacingMergeTree` |
| Много частей (too many parts) | Мелкие батчи без async_insert | `async_insert=1`, увеличить `send_batch_size`/`batch.max_bytes` |
| Ошибки Arrow в Vector | Колонки `IPv4`/`IPv6` не поддерживаются `arrow_stream` | Формат `json_each_row` для этих колонок |
| Таблица растёт быстро | Нет TTL | Добавить `TTL timestamp + INTERVAL N DAY` |
| Медленные запросы к логам | `message` в ORDER BY или нет индексов | `ORDER BY (service, timestamp)`; полнотекстовый индекс на `message` |
| High cardinality в labels/тегах | Слишком много уникальных значений на источнике | Ограничить cardinality на источнике (processor/transform); `tags_to_columns` для горячих тегов |
| `system.opentelemetry_span_log` пуст | Трассировка запросов не включена | `SET opentelemetry_trace_processors = 1` |
| Downsampling не работает / данные не агрегируются | Неправильное окно WHERE в INSERT | Проверить границы интервала: `WHERE timestamp < now() - 7d AND timestamp >= now() - 8d` |
| Jaeger UI не показывает трейсы | Не совпадает схема БД / feature gate не включён | Проверить `--feature-gates=storage.clickhouse`; пересоздать схему |
| Vector sink: `connection refused` | ClickHouse HTTP порт недоступен | Проверить `clickhouse:8123` доступен; `telnet clickhouse 8123` |
| OTel Collector OOM | `batch.send_batch_size` слишком велик при малой RAM | Уменьшить `send_batch_size`; добавить `memory_limiter` processor |
| TimeSeries: PromQL timeout | Слишком широкий диапазон / нет индексов по тегам | Использовать `tags_to_columns` для горячих тегов; сузить time range |

## Лучшие практики

1. **Отдельные базы данных** для телеметрии (`otel`, `prometheus`, `logs`) — изоляция от бизнес-данных.
2. **PARTITION BY toDate/toYYYYMM(timestamp)** — партиционирование для быстрой очистки; TTL на всех телеметрийных таблицах.
3. **ORDER BY (service, timestamp)** — сервис первым для фильтрации; `message` — последней колонкой, не в ключе сортировки.
4. **LowCardinality** для `level`, `service`, `host`, `ServiceName` — экономия на сжатии.
5. **Ограничивать cardinality на источнике** (OTel processor / Vector transform `tag_cardinality_limit`), а не в ClickHouse.
6. **Собственные схемы вместо `create_schema: true`** в продакшене — оптимальные кодеки, индексы, TTL (см. [schema design](https://clickhouse.com/docs/guides/use-cases/observability/build-your-own/schema-design)).
7. **Downsampling** — агрегировать старые метрики в почасовые/суточные.
8. **Не хранить raw message в горячей таблице** — выносить в отдельную таблицу с длинным TTL.
9. **Мониторить сам конвейер**: self-метрики OTel Collector/Vector (отправлено/сбой/retry), `system.inserts`, рост частей в `system.parts`.
10. **Jaeger + ClickHouse — экспериментальный бэкенд**: не использовать для критичных данных без оценки риска изменения схемы.

### Очистка и откат изменений

**Удаление конвейера приёма метрик Prometheus:**
```sql
-- Остановить remote_write в Prometheus
-- Удалить handler из config.xml и перезапустить ClickHouse
DROP TABLE IF EXISTS prometheus.metrics;
DROP DATABASE IF EXISTS prometheus;
```

**Удаление конвейера OTel Collector:**
```bash
# Остановить Collector
kubectl delete -f otel-collector.yaml  # или systemctl stop otelcol
```
```sql
DROP TABLE IF EXISTS otel.otel_traces;
DROP TABLE IF EXISTS otel.otel_logs;
DROP TABLE IF EXISTS otel.otel_traces_trace_id_ts;
DROP DATABASE IF EXISTS otel;
```

**Удаление конвейера Vector:**
```bash
# Остановить Vector
systemctl stop vector
```
```sql
DROP TABLE IF EXISTS logs.raw_events;
DROP DATABASE IF EXISTS logs;
```

**Откат схемы к `create_schema: true`:**
```sql
-- Если ручная схема вызвала проблемы
DROP TABLE IF EXISTS otel.otel_traces;
DROP TABLE IF EXISTS otel.otel_logs;
-- В конфиге Collector: create_schema: true
-- Перезапустить Collector — таблицы создадутся автоматически
```

**Проверка после очистки:**
```sql
-- Нет остаточных таблиц
SELECT database, table FROM system.tables
WHERE database IN ('prometheus', 'otel', 'logs', 'jaeger_v2');
-- → 0 rows

-- Нет активных вставок
SELECT * FROM system.inserts WHERE table IN ('metrics', 'otel_traces', 'otel_logs', 'raw_events');
-- → 0 rows
```

## Граничные случаи и ограничения

| Сценарий | Ограничение / поведение | Рекомендация |
| :--- | :--- | :--- |
| **Большие трейсы (> 1 MB/спан)** | ClickHouse нативный протокол имеет лимит на размер пакета (100 MB по умолчанию) | Увеличить `max_insert_block_size`; использовать HTTP сжатие |
| **Out-of-order метрики** | TimeSeries пишет в партицию по `timestamp`; старые данные создают новые части | Настроить `recent_samples_ttl_seconds`; использовать `SYSTEM STOP MERGES` на время загрузки |
| **Бурст логов (лог-шторм)** | Очередь Vector/Collector переполняется, OOM | `memory_limiter` + `batch` с `send_batch_max_size`; алерт на `vector_component_received_bytes_total` |
| **High cardinality trace_id** | Bloom filter на `TraceId` эффективен до ~1M уникальных/партицию | Партиционировать по часу для очень высокой нагрузки |
| **Jaeger schema drift** | StageAlpha — схема может меняться breaking-образно между версиями Jaeger | Закрепить версию Jaeger; тестировать миграцию на стенде |
| **TLS между компонентами** | Нативный порт 9000 не поддерживает TLS без `secure=true` на 9440 | Использовать `secure=true` в endpoint или HTTP 8443 |
| **Мультитенантность** | Нет встроенной изоляции тенантов в TimeSeries | Отдельные БД/таблицы на тенанта; row policies для SELECT |
| **Загрузка исторических данных** | `INSERT` в MergeTree сортирует данные — медленно для TB | `clickhouse-local` + `clickhouse-client --max_insert_block_size`; загружать по партициям |
| **Remote read для Prometheus** | Поддерживается, но медленнее чем нативный PromQL | Для долгих retention — использовать SQL напрямую |
| **Профили (continuous profiling)** | `otel_profiles` таблица требует отдельной схемы | Включить `profiles_table_name` в экспортёре; схема в docs |

## Дополнительная информация

### Смежные темы

- Интеграция Vector → ClickHouse — **[Vector: практические сценарии](../../Vector/practical_scenarios.md)**.
- Хранение трейсов Jaeger — **[Jaeger: глубокое погружение](../../Jaeger/jaeger_storage_deep_dive.md)**.
- Мониторинг самого ClickHouse (system-таблицы, экспортёр `9363`, алерты) — **[Мониторинг и системные таблицы](./clickhouse-monitoring.md)**.
- Tiered Storage (S3) — **[Интеграция ClickHouse и S3](./clickhouse_s3_integration.md)**.
- Мониторинг производительности — **[Производительность](./clickhouse-performance.md)**.

### Ресурсы

- [Документация: Prometheus HTTP API (remote write, remote read, PromQL)](https://clickhouse.com/docs/concepts/features/interfaces/prometheus)
- [Документация: Prometheus metrics endpoint (скрейп, порт 9363)](https://clickhouse.com/docs/concepts/features/interfaces/prometheus-metrics)
- [Документация: TimeSeries engine](https://clickhouse.com/docs/reference/engines/table-engines/integrations/time-series)
- [Гайд: Integrating OpenTelemetry (OTel Collector + clickhouse exporter)](https://clickhouse.com/docs/guides/use-cases/observability/build-your-own/integrating-opentelemetry)
- [Гайд: Designing a schema for observability](https://clickhouse.com/docs/guides/use-cases/observability/build-your-own/schema-design)
- [Документация: OpenTelemetry в ClickHouse (opentelemetry_span_log)](https://clickhouse.com/docs/en/operations/opentelemetry)
- [OTel Collector Contrib: clickhouse exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/clickhouseexporter)
- [Документация: Jaeger v2 — ClickHouse storage](https://www.jaegertracing.io/docs/latest/storage/clickhouse/)
- [Документация: Vector clickhouse sink](https://vector.dev/docs/reference/configuration/sinks/clickhouse/)
