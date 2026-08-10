# Grafana Tempo — распределённая трассировка

## Определения

**Tempo** — высокомасштабируемое распределённое хранилище трассировок (traces) от Grafana Labs. Написано на Go, лицензия — AGPLv3. Релиз v3.0.0 — май 2026: с этой версии проект перешёл на новую архитектуру с разделением путей чтения и записи (Decoupled Read/Write Path). Основная цель — максимально экономичное и производительное хранение огромных объёмов телеметрии в объектных хранилищах (S3, GCS, Azure, MinIO, локальный диск).

**Trace (трассировка)** — запись полного жизненного цикла запроса в распределённой системе. Позволяет отследить путь запроса через микросервисы, выявить задержки и ошибки взаимодействия.

**Span (спан)** — минимальный атомарный блок трассировки, представляющий отдельную операцию (HTTP-вызов, запрос к БД, выполнение функции). Содержит метаданные, временные метки и атрибуты.

**TraceQL** — специализированный язык запросов для поиска и анализа трассировок (вдохновлён PromQL и LogQL). Позволяет фильтровать по атрибутам спанов и ресурсов, длительности, статусам, событиям (events) и связям (links). С версии 3.0 генерация метрик на лету (TraceQL Metrics) переведена в статус GA.

**Decoupled Read/Write Path** — архитектурная модель Tempo 3.0, в которой пути записи и чтения полностью независимы, а долговечность данных (durability) обеспечивает внешняя Kafka-совместимая очередь, а не репликация внутри процессов. Запись: Distributor → Kafka → block-builder (Parquet-блоки в объектное хранилище, RF1). Чтение: live-store (свежие данные из того же потока Kafka) + Querier (исторические блоки).

---

## Основные концепции

### Назначение трассировок

- **Локализация проблем:** быстрое нахождение сервиса, вызывающего задержку или ошибку в цепочке вызовов.
- **Анализ критического пути:** визуализация наиболее длительных этапов выполнения запроса.
- **Оптимизация производительности:** выявление неэффективных запросов к БД или внешним API.
- **Соответствие (Compliance):** использование Trace Redaction для удаления чувствительных данных (PII).

### Ключевые особенности Tempo 3.0

- **Новая архитектура (Decoupled Path):** использование Kafka (или совместимой очереди, например Redpanda) в качестве буфера записи. Это позволило отказаться от обязательного RF3 в пользу **RF1** (одна копия данных в объектном хранилище вместо трёх), снизив TCO (стоимость владения) в 2–3 раза.
- **Независимость чтения и записи:** тяжёлые или медленные запросы больше не могут остановить приём данных (в 2.x медленный запрос мог «задушить» процессы ingester'а).
- **TraceQL Metrics GA:** создание метрик на основе трейсов в реальном времени без предварительной настройки metrics-generator; включено по умолчанию, поддерживает exemplars и агрегатные функции.
- **Мульти-тенантность:** встроенная изоляция данных и пер-тенантные лимиты (overrides) для разных команд/клиентов.
- **Совместимость со стандартами:** приём по протоколам OTLP (gRPC/HTTP), Jaeger и Zipkin, а также Kafka-совместимым форматам (OpenCensus в 3.0 не поддерживается).
- **AI и MCP интеграция (с 2.9):** нативный Tempo MCP Server позволяет AI-агентам (Claude, Grafana Assistant) напрямую анализировать трейсы для поиска корневых причин инцидентов.
- **Span Profiling:** интеграция с Grafana Pyroscope через otelpyroscope — при включённом `span_profiling` в спан добавляются pprof-лейблы, что позволяет переходить от конкретного спана к Flame Graph профиля CPU/Memory соответствующей строки кода.
- **Экономичность:** хранение в object storage в формате vParquet4/vParquet5 делает Tempo значительно дешевле традиционных решений на базе Elasticsearch.
- **Trace Redaction:** `tempo-cli redact` удаляет чувствительные данные (PII) из трейсов по требованию, не дожидаясь окончания retention, — для выполнения GDPR-запросов.
- **Высокая пропускная способность (High Volume Intake)** и **минимальные зависимости** — простота развёртывания и эксплуатации при больших объёмах телеметрии.

### Сравнение с Jaeger

| Характеристика | Tempo 3.0 | Jaeger v2 |
| :--- | :--- | :--- |
| Архитектура | Разделение путей записи/чтения (Kafka-buffer) | Классическая (Collector -> DB) |
| Поиск | TraceQL (мощный поиск по атрибутам и метрикам) | Поиск по тегам, сервисам и операциям |
| Хранение | Object storage (S3/GCS) — RF1 (с v3.0) | Elasticsearch, Cassandra, ClickHouse, Badger |
| Стоимость (TCO) | Минимальная (самое дешёвое хранение) | Высокая (из-за накладных расходов БД) |
| Генерация метрик | TraceQL Metrics (динамически) | Adaptive Sampling, интеграция с Prometheus |
| Интеграция с AI | Нативный MCP Server | Ограниченная (через внешние плагины) |
| UI | Встроен в Grafana (Explore) | Собственный Jaeger UI |

Подробнее о конкурентном решении: [Jaeger overview](../Jaeger/jaeger_overview.md).

### Архитектура

В версии 3.0 пути записи и чтения полностью разделены (в микросервисном режиме). Трейсы поступают в **Distributor**, который пишет их в **Kafka**-совместимую очередь — слой долговечности (durability layer). Далее **block-builder** асинхронно записывает Parquet-блоки в объектное хранилище (RF1), а **live-store**, читающий тот же поток, отдаёт самые свежие трейсы до готовности блоков. Исторические данные читает **Querier** из object storage. В монолитном режиме все компоненты работают внутри одного бинарника без Kafka. Такое разделение устраняет влияние тяжёлых запросов на стабильность приёма данных.

Подробное описание компонентов, форматов vParquet и режимов миграции: [Архитектура и операции Tempo](./architecture_operations.md).

---

## Практические сценарии

### Установка и деплой

С конца января 2026 OSS-чарты Grafana переехали в репозиторий `grafana-community` (HTTP-репозиторий или OCI: `oci://ghcr.io/grafana-community/helm-charts/...`).

**Установка через Helm:**

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

# Монолитный режим (единый бинарник, Kafka не требуется)
helm install tempo grafana-community/tempo --namespace tempo --create-namespace

# Микросервисный режим (требуется Kafka-совместимая очередь)
helm install tempo grafana-community/tempo-distributed --namespace tempo --create-namespace
```

Два основных чарта: `tempo` (монолит) и `tempo-distributed` (микросервисы). Режим выбирается по масштабу: монолит подходит для нагрузки до ~100–200 МБ/с, микросервисы — для продакшена с высокой пропускной способностью.

**Миграция с 2.x:** в 3.0 удалены ingester, compactor и metrics-generator-client, поэтому обычный апгрейд конфигурации не подходит. `tempo-cli migrate config` преобразует конфигурацию 2.x в формат 3.0 (сама утилита обновляет конфиг, а не данные в хранилище — старые блоки остаются читаемыми):

```bash
# Монолит
tempo-cli migrate config --mode=monolithic old-config.yaml > new-config.yaml

# Микросервисы (добавляется блок ingest для Kafka)
tempo-cli migrate config --kafka-address=<broker> --kafka-topic=<topic> old-config.yaml > new-config.yaml
```

Ключевые ограничения v3.0: нет downgrade-пути до 2.x, удалён режим scalable-single-binary (SSB), legacy (плоские) overrides отключены по умолчанию, поддерживаются только блоки vParquet4+.

### Работа с TraceQL

Примеры современных запросов (v3.0):

```traceql
// Поиск медленных запросов к конкретному сервису
{ resource.service.name = "billing" && duration > 2s }

// TraceQL Metrics: rate успешных ответов по сервисам (GA, v3.0)
{ span.http.status_code = 200 } | rate() by (resource.service.name)

// TraceQL Metrics: P99 длительности по target с exemplars
{ span:name = "GET /orders" } | quantile_over_time(duration, .99) by (span.http.target) with (exemplars=true)

// Поиск спанов с конкретными ошибками и событиями
{ status = error && event.name = "exception" }

// Поиск по атрибутам ресурсов
{ resource.node.name = "k8s-node-1" }
```

**TraceQL Metrics (GA, с v3.0):** метрики добавляются к любому TraceQL-запросу через пайплайн `| <функция> by (<атрибут>)`. Доступные функции: `rate`, `count_over_time`, `sum_over_time`, `max_over_time`, `min_over_time`, `avg_over_time`, `quantile_over_time`, `histogram_over_time`, `compare`. Результаты фильтруются операторами сравнения (`>`, `>=`, `<`, `<=`, `=`, `!=`) и функциями `topk`/`bottomk`. Метрики включены по умолчанию и читают только RF1-блоки: данные, принятые в Tempo 2.x без local-blocks processor, для metric-запросов недоступны.

### Интеграции

**Grafana Alloy** — рекомендуемый агент для сбора и передачи трейсов. Полностью заменяет старые коллекторы (Promtail, Grafana Agent) и поддерживает нативную корреляцию с профилями Pyroscope. Подробнее: [Grafana Alloy](../Grafana/grafana_alloy_overview.md).

**Grafana Pyroscope** — позволяет выполнять переход «Span-to-Profile». Если спан содержит `profile_id` (когда в Tempo включён `span_profiling`), Grafana предложит открыть Flame Graph для этого конкретного вызова.

**Traces Drilldown** — UI в Grafana для поточечного анализа latency и ошибок без написания TraceQL: запросы генерируются автоматически, а затем доступны для ручной доработки.

**Loki и Mimir** — корреляция через `trace_id` (Derived Fields в [Loki](../Loki/loki_overview.md)) и Exemplars (в [Mimir](../Mimir/mimir_overview.md) или Prometheus). В Tempo 3.0 корреляция стала двухсторонней благодаря AI-ассистенту, который сам находит связанные логи по контексту трейса.

### Рекомендации по эксплуатации

- **Использование Kafka:** для продуктовых сред в микросервисном режиме Kafka (или совместимая очередь) обязателен, так как обеспечивает долговечность данных; монолитный режим Kafka не требует.
- **Retention Policy:** в 3.0 компоновкой и политиками хранения занимаются backend scheduler и backend worker (заменили Compactor); для GDPR-запросов используйте `tempo-cli redact`.
- **TraceQL Metrics и миграция:** метрики читают только RF1-блоки — планируйте, что metric-запросы по данным из 2.x (без local-blocks processor) вернут результат только для данных, принятых после миграции.
- **S3 Tiering:** используйте Intelligent Tiering в S3 для автоматического перемещения старых трейсов в дешёвые слои хранения.
- **Streaming Queries:** в настройках Grafana включите `Query Streaming` для мгновенного отображения первых результатов поиска.
- **Мониторинг приёма:** следите за `tempo_distributor_kafka_write_errors_total` и `tempo_live_store_lagged_requests_total` — критические индикаторы проблем с записью в очередь и отставанием live-store.

---

## Дополнительная информация

Tempo является фундаментом [LGTM Stack](../Kubernetes/Installation/LGTM_Stack/lgtm_otel_minikube_overview.md) и тесно взаимодействует с [OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md).

### См. также

- [Архитектура и операции Tempo](./architecture_operations.md) — компоненты v3.0, vParquet и миграция.
- [TraceQL Documentation](https://grafana.com/docs/tempo/latest/traceql/)
- [Миграция на Tempo 3.0](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/migrate-to-3/)

