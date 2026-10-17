# Grafana Tempo — распределённая трассировка

**Актуально для:** Grafana Tempo 3.1.x

## Определения

**Tempo** — высокомасштабируемое распределённое хранилище трассировок (traces) от Grafana Labs. Написано на Go, лицензия — AGPLv3. Релиз v3.0.0 — май 2026: с этой версии проект перешёл на новую архитектуру с разделением путей чтения и записи (Decoupled Read/Write Path). Версия 3.1 (сентябрь 2026) делает vParquet5 форматом блоков по умолчанию, добавляет арифметику TraceQL Metrics, query-based redaction и rack-aware Kafka fetching. Основная цель — максимально экономичное и производительное хранение огромных объёмов телеметрии в S3-совместимой объектной хранилищах (MinIO, локальный диск).

**Trace (трассировка)** — запись полного жизненного цикла запроса в распределённой системе. Позволяет отследить путь запроса через микросервисы, выявить задержки и ошибки взаимодействия.

**Span (спан)** — минимальный атомарный блок трассировки, представляющий отдельную операцию (HTTP-вызов, запрос к БД, выполнение функции). Содержит метаданные, временные метки и атрибуты.

**TraceQL** — специализированный язык запросов для поиска и анализа трассировок (вдохновлён PromQL и LogQL). Позволяет фильтровать по атрибутам спанов и ресурсов, длительности, статусам, событиям (events) и связям (links). С версии 3.0 генерация метрик на лету (TraceQL Metrics) переведена в статус GA.

**Decoupled Read/Write Path** — архитектурная модель Tempo 3.0, в которой пути записи и чтения полностью независимы, а долговечность данных (durability) обеспечивает внешняя Kafka-совместимая очередь, а не репликация внутри процессов. Запись: Distributor → Kafka → block-builder (Parquet-блоки в объектное хранилище, RF1). Чтение: live-store (свежие данные из того же потока Kafka) + Querier (исторические блоки).

**RF1 / RF3 (Replication Factor)** — количество копий блока в объектном хранилище. В Tempo 2.x трейсы реплицировались на ingester-ах с фактором 3, что порождало 2–2.5× дублирование данных. Tempo 3.0 благодаря Kafka-очереди пишет каждый блок ровно один раз (RF1): трейсы шардируются по ID на уникальные партиции, поэтому каждый блок строится однократно.

**vParquet4 / vParquet5** — форматы хранения блоков в объектном хранилище. vParquet4 добавляет колонки для array-атрибутов, событий и связей (10 string dedicated-колонок на scope). vParquet5 — расширенный формат с 20 string + 5 integer dedicated-колоноками на scope, event-scoped колонками, blob-колонками (zstd для high-cardinality атрибутов) и array-колонками. Начиная с Tempo 3.1, vParquet5 является форматом по умолчанию; vParquet4 доступен как опциональный. vParquet3 удалена (deprecated в 2.10, enforced в 3.1 — Tempo не стартует при конфигурации vParquet3 для записи).

**Span Profiling** — интеграция Tempo с профилировщиками (Grafana Pyroscope). При включённом `span_profiling` в спан добавляются pprof-лейблы, что позволяет переходить от конкретного спана к Flame Graph профиля CPU/Memory соответствующей строки кода.

**Multi-tenancy (многопользовательская изоляция)** — встроенный механизм изоляции данных между tenants (командами, клиентами, окружениями). Каждый tenant имеет независимый набор блоков, политики retention и overrides.

**Retention Policy (политика хранения)** — набор правил, определяющих время жизни трейсов. В Tempo 3.0 retention и компоновку блоков выполняют backend scheduler и backend worker; устаревшие блоки удаляются по завершении заданного окна хранения.

**Trace Redaction** — механизм удаления чувствительных данных (PII) из трейсов. `tempo-cli redact` отправляет задачи в backend scheduler, который переписывает затронутые блока в хранилище; прогресс отслеживается через `/status/backendscheduler`. Поддерживает удаление по trace ID (`--trace-id`) и по TraceQL-запросу (`--query`, 3.1+). Дополнительно доступна `tempo-cli rewrite-blocks drop-traces` — прямое удаление по trace ID из объектного хранилища без backend scheduler.

---

## Основные концепции

### Назначение трассировок

- **Локализация проблем:** быстрое нахождение сервиса, вызывающего задержку или ошибку в цепочке вызовов.
- **Анализ критического пути:** визуализация наиболее длительных этапов выполнения запроса.
- **Оптимизация производительности:** выявление неэффективных запросов к БД или внешним API.
- **Соответствие (Compliance):** использование Trace Redaction для удаления чувствительных данных (PII).
- **Анализ асинхронных взаимодействий:** отслеживание сообщений через очереди (Kafka) с использованием Span Links.
- **Поиск корневых причин (RCA):** корреляция трейсов с логами и метриками для полной картины инцидента.

### Ключевые особенности Tempo 3.1

- **Новая архитектура (Decoupled Path):** использование Kafka (или совместимой очереди, например Redpanda) в качестве буфера записи. Это позволило отказаться от обязательного RF3 в пользу **RF1** (одна копия данных в объектном хранилище вместо трёх), снизив TCO (стоимость владения) в 2–3 раза.
- **Независимость чтения и записи:** тяжёлые или медленные запросы больше не могут остановить приём данных (в 2.x медленный запрос мог «задушить» процессы ingester'а).
- **TraceQL Metrics GA:** создание метрик на основе трейсов в реальном времени без предварительной настройки metrics-generator; включено по умолчанию, поддерживает exemplars, агрегатные функции и арифметику (3.1+).
- **Мульти-тенантность:** встроенная изоляция данных и пер-тенантные лимиты (overrides) для разных команд/клиентов.
- **Совместимость со стандартами:** приём по протоколам OTLP (gRPC/HTTP), Jaeger и Zipkin, а также Kafka-совместимым форматам (OpenCensus в 3.0 не поддерживается).
- **Span Profiling:** интеграция с профилировщиками через otelpyroscope — при включённом `span_profiling` в спан добавляются pprof-лейблы, что позволяет переходить от конкретного спана к Flame Graph профиля CPU/Memory соответствующей строки кода.
- **Экономичность:** хранение в объектном хранилище в формате vParquet5 (по умолчанию с 3.1) делает Tempo значительно дешевле традиционных решений на базе Elasticsearch.
- **Trace Redaction:** `tempo-cli redact` удаляет чувствительные данные (PII) из трейсов по требованию, не дожидаясь окончания retention — для выполнения GDPR-запросов. Query-based redaction (3.1+) удаляет трейсы по TraceQL-запросу.
- **Высокая пропускная способность (High Volume Intake)** и **минимальные зависимости** — простота развёртывания и эксплуатации при больших объёмах телеметрии.
- **vParquet5 по умолчанию (3.1):** расширенные dedicated-колонки (20 string + 5 integer на scope), blob-колонки, event-scoped атрибуты, array-атрибуты.
- **Rack-aware Kafka fetching (3.1):** `client_rack` Kafka config для снижения cross-zone трафика.

### Сравнение с Jaeger

| Характеристика | Tempo 3.1 | Jaeger v2 |
| :--- | :--- | :--- |
| Архитектура | Разделение путей записи/чтения (Kafka-buffer) | Классическая (Collector -> DB) |
| Поиск | TraceQL (мощный поиск по атрибутам и метрикам) | Поиск по тегам, сервисам и операциям |
| Хранение | S3-совместимое объектное хранилище — RF1 (с v3.0) | Elasticsearch, Cassandra, ClickHouse, Badger |
| Стоимость (TCO) | Минимальная (самое дешёвое хранение) | Высокая (из-за накладных расходов БД) |
| Генерация метрик | TraceQL Metrics (динамически) | Adaptive Sampling, интеграция с Prometheus |
| UI | Встроен в Grafana (Explore) | Собственный Jaeger UI |

Подробнее о конкурентном решении: [Jaeger overview](../Jaeger/jaeger_overview.md).

### Архитектура

В версии 3.0 пути записи и чтения полностью разделены (в микросервисном режиме). Трейсы поступают в **Distributor**, который пишет их в **Kafka**-совместимую очередь — слой долговечности (durability layer). Далее **block-builder** асинхронно записывает Parquet-блоки в объектное хранилище (RF1), а **live-store**, читающий тот же поток, отдаёт самые свежие трейсы до готовности блоков. Исторические данные читает **Querier** из object storage. В монолитном режиме все компоненты работают внутри одного бинарника без Kafka. Такое разделение устраняет влияние тяжёлых запросов на стабильность приёма данных.

Подробное описание компонентов, форматов vParquet и режимов миграции: [Архитектура и операции Tempo](./architecture_operations.md).

### Модель многопользовательской изоляции

Tempo 3.1 поддерживает нативную multi-tenancy без внешних абстракций. Каждый tenant имеет изолированное пространство блоков в объектном хранилище. Lимиты и поведение задаются через overrides:
- **Global overrides** — применяются ко всем tenants по умолчанию.
- **Per-tenant overrides** — переопределяют глобальные значения для конкретного tenant.

Важно: per-tenant overrides не наследуют свойства автоматически; все необходимые поля должны быть указаны явно. Legacy (плоские) overrides отключены по умолчанию; для миграции используйте `tempo-cli migrate overrides-config` или временно включите `enable_legacy_overrides: true`.

### Жизненный цикл данных и retention

Данные в Tempo проходят следующие стадии:
1. **Ingest:** трейсы принимаются через OTLP/Jaeger/Zipkin/Kafka, записываются в Kafka-очередь.
2. **Block building:** block-builder асинхронно группирует спаны в Parquet-блоки по временным окнам и tenant-ам, записывает в объектное хранилище (RF1).
3. **Querying:** live-store обслуживает запросы за последние ~30–60 минут; Querier читает исторические блоки из object storage.
4. **Compaction & retention:** backend scheduler планирует задачи компоновки и удаления устаревших блоков; backend worker выполняет эти задачи с авторетраем при сбоях.

Retention задаётся в overrides и может быть как глобальной, так и пер-тенантной. Для удаления данных по GDPR-запросам используется `tempo-cli redact`, который перезаписывает затронутые блоки.

### Span Profiling

Tempo 3.1 поддерживает интеграцию с Grafana Pyroscope для перехода от трейсов к профилям CPU/Memory. При включённом `span_profiling` в каждый спан добавляются pprof-лейблы. Если спан содержит `profile_id`, Grafana UI предлагает открыть Flame Graph для конкретного вызова, позволяя перейти от «медленного спана» к «горячей строке кода» без дополнительной инструментации.

---

## Практические сценарии

### Предварительные требования

**Аппаратные требования:**
- **Монолитный режим:** 2+ CPU, 4–8 ГБ RAM, 50+ ГБ диска (в зависимости от retention и объёма трафика).
- **Микросервисный режим:** отдельные узлы для Distributor, Query Frontend, Querier, live-store, block-builder; Kafka-кластер на 3+ брокерах для продакшена.
- **Объектное хранилище:** S3-совместимое хранилище (MinIO, локальные решения) или локальный диск (только для dev/test).

**Программные зависимости:**
- Kubernetes 1.24+ (для production-деплоя) или Docker/Podman.
- Helm 3.12+.
- Kafka 2.8+ (только для микросервисного режима; совместимые очереди: Redpanda).
- S3-совместимое хранилище с поддержкой versioning (опционально) и lifecycle-правил.

**Сетеые требования:**
- Порты: 3200 (HTTP API), 4317 (OTLP gRPC), 4318 (OTLP HTTP), 9095 (gRPC receiver), 14268 (Jaeger).
- Для Kafka-режима: порт 9092 (broker), достаточная пропускная способность между Tempo и брокерами.

### Установка и деплой

С конца января 2026 OSS-чарты Grafana переехали в репозиторий `grafana-community` (HTTP-репозиторий или OCI: `oci://ghcr.io/grafana-community/helm-charts/...`).

#### Монолитный режим

Подходит для нагрузок до ~100–200 МБ/с, dev/test сред и небольших продакшенов. Kafka не требуется.

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

helm install tempo grafana-community/tempo \
  --namespace tempo --create-namespace \
  --set tempo.memcached.enabled=false \
  --set tempo.queryFrontend.dedicatedColumns="[{name:\"http.method\",type:\"string\",scope:\"span\"},{name:\"deployment.environment\",type:\"string\",scope:\"resource\"}]"
```

**Валидация:**
```bash
kubectl rollout status statefulset/tempo -n tempo --timeout=5m
kubectl get pods -n tempo
curl -s http://<TEMPO_IP>:3200/ready
# → {"status":"ready"}
```

#### Микросервисный режим

Требует работающую Kafka-совместимую очередь. Подходит для продакшена с высокой пропускной способностью.

```bash
helm install tempo grafana-community/tempo-distributed \
  --namespace tempo --create-namespace \
  --set ingest.kafka.enabled=true \
  --set ingest.kafka.addresses[0]="kafka-1:9092" \
  --set ingest.kafka.addresses[1]="kafka-2:9092" \
  --set ingest.kafka.topic="tempo-traces" \
  --set ingest.kafka.autoCreateTopic=true \
  --set ingest.kafka.autoCreateTopicDefaultPartitions=12
```

**Важно:** количество реплик live-store и block-builder должно равняться числу партиций Kafka (block-builder-0 читает партицию 0 и т.д.). Синхронизация реплик выполняется через KEDA-автоскейлер, mirroring-функцию Grafana rollout-operator или статический count реплик.

**Валидация:**
```bash
# Проверка готовности live-store (дозревает до 30 мин без трафика)
kubectl exec -n tempo deploy/tempo-query-frontend -- curl -s http://localhost:3200/ready

# Проверка записи в Kafka
kubectl exec -n tempo deploy/tempo-distributor -- curl -s http://localhost:3200/metrics | grep tempo_distributor_kafka_write_bytes_total

# Проверка работы block-builder
kubectl exec -n tempo deploy/tempo-query-frontend -- curl -s http://localhost:3200/metrics | grep tempo_block_builder_fetch_errors_total
```

### Конфигурация объектного хранилища

Tempo 3.1 поддерживает S3-совместимые хранилища (MinIO, локальные решения) и локальный диск. По умолчанию используется формат vParquet5 (3.1+);

**Пример: MinIO (S3-совместимое)**

```yaml
storage:
  trace:
    backend: s3
    s3:
      bucket: tempo-traces
      endpoint: minio.tempo.svc:9000
      access_key: tempo
      secret_key: <SECRET_bbe25af1>      # insecure для тестов; в продакшене используйте TLS
      insecure: true
    block:
      version: vParquet5   # по умолчанию в 3.1+
```

**Пример: локальный диск (dev/test only)**

```yaml
storage:
  trace:
    backend: local
    local:
      path: /var/tempo/traces
    block:
      version: vParquet5   # по умолчанию в 3.1+
```

**Важные замечания:**
- S3 Versioning можно отключить, если не требуется внешними политиками (Kafka обеспечивает долговечность).
- Для production используйте TLS и HMAC-аутентификацию.
- Настройте lifecycle-правила для автоматического перемещения старых блоков в дешёвые слои хранения (если поддерживаются хранилищем).

### Конфигурация Kafka

Минимальный блок конфигурации Kafka (обязателен в микросервисном режиме):

```yaml
ingest:
  kafka:
    address: kafka-1:9092,kafka-2:9092
    topic: tempo-traces
    auto_create_topic_enabled: true
    auto_create_topic_default_partitions: 12   # ~10 МБ/с пиковой записи на партицию
```

При SASL-аутентификации:

```yaml
ingest:
  kafka:
    address: kafka-1:9092
    topic: tempo-traces
    sasl_username: <USERNAME>
    sasl_password: <PASSWORD>
```

**Рекомендации:**
- Начинайте с ~10 МБ/с пиковой записи на партицию.
- Для продакшена используйте репликацию Kafka (replication.factor >= 3).
- Мониторьте лаг партиций через `tempo_ingest_group_partition_lag_seconds`.

### Миграция с 2.x на 3.x

**Предусловия:**
- Данные в формате vParquet4+ (3.0 не читает vParquet3 и старше; в 3.1 vParquet3 deprecated — Tempo не стартует при записи в vParquet3).
- Доступ к тому же объектному хранилищу.
- Для микросервисного режима — работающая Kafka-совместимая очередь.
- Из SSB (scalable single binary) переходите на монолит или микросервисы.

**Шаги миграции:**

1. **Миграция конфигурации** — `tempo-cli migrate config` читает конфиг 2.x и выдаёт валидный конфиг 3.x: удаляет блоки `ingester`, `ingester_client`, `compactor`, `metrics_generator_client` и конфиг `local_blocks`; в микросервисном режиме добавляет `ingest:`-блок; выставляет `compaction_disabled: true` в дефолтных overrides. Данные в хранилище утилита не изменяет:

   ```bash
   # Монолит
   tempo-cli migrate config --mode=monolithic old-config.yaml > new-config.yaml

   # Микросервисы
   tempo-cli migrate config --kafka-address=<BROKER> --kafka-topic=<TOPIC> old-config.yaml > new-config.yaml
   ```

2. **Legacy overrides** — плоский (unscoped) формат overrides отключён по умолчанию, иначе Tempo не стартует. Мигрируйте через `tempo-cli migrate overrides-config` либо временно включите `enable_legacy_overrides: true` (удалят в будущих релизах).

3. **Параллельный деплой 3.1 с 2.x** (микросервисы) — оба деплоймента указывают на одно объектное хранилище. Пока работают compactor-ы 2.x, одновременно может писать только одна система компоновки: держите `compaction_disabled: true` в дефолтном и каждом пер-тенантном overrides. Проверьте готовность:
   - `tempo_live_store_ready == 1` (на свежем деплойменте без трафика live-store может «дозревать» до `live_store.readiness_max_wait`, по умолчанию 30 мин).
   - `rate(tempo_block_builder_fetch_errors_total[5m])` около нуля.
   - Валидация через Tempo Vulture (`tempo_vulture_trace_error_total == 0`) или запрос по известному trace ID:

   ```bash
   curl http://<TEMPO_3_QUERY_FRONTEND>:3200/api/traces/<TRACE_ID>
   # → JSON трейса, если 3.1 читает исторические блоки из хранилища
   ```

4. **Переключение трафика** — постепенно переводите клиентов (OpenTelemetry Collectors, Grafana Alloy) на 3.1; контролируйте `tempo_distributor_kafka_write_bytes_total` и `tempo_ingest_group_partition_lag_seconds`.

5. **Вывод 2.x** — дождитесь флаша ingester-ов (`tempo_ingester_live_traces` и `tempo_ingester_flush_queue_length` → 0), масштабируйте compactor-ы 2.x в ноль, снимите `compaction_disabled` в 3.1, деинсталлируйте 2.x. Общее хранилище не удаляйте.

**Ограничения:** нет in-place downgrade с 3.0 на 2.x. До деинсталляции 2.x роллбэк возможен переключением трафика (routing change). Блоки, записанные block-builder-ом (RF1), читаемы 2.x при совместимом формате (vParquet4+). **TraceQL Metrics читают только RF1-блоки:** если в 2.x не использовался процессор `local-blocks`, метрики покроют только данные после миграции.

**Верификация после миграции:** `tempo_distributor_kafka_write_bytes_total` растёт, `tempo_block_builder_fetch_records_total` растёт при `tempo_block_builder_fetch_errors_total` = 0, `tempo_live_store_ready` = 1 при `tempo_live_store_records_dropped_total` = 0, исторические запросы возвращают данные, backend-worker-ы выполняют компоновку.

### Работа с TraceQL

Примеры современных запросов (v3.1):

```traceql
// Поиск медленных запросов к конкретному сервису
{ resource.service.name = "billing" && duration > 2s }

// TraceQL Metrics: rate успешных ответов по сервисам (GA, v3.0)
{ span.http.status_code = 200 } | rate() by (resource.service.name)

// TraceQL Metrics: P99 длительности по target с exemplars
{ span:name = "GET /orders" } | quantile_over_time(duration, .99) by (span.http.target) with (exemplars=true)

// TraceQL Metrics: арифметика (3.1+) — ratio error rate
{ span.http.status_code = 500 } | rate() by (resource.service.name) / { } | rate() by (resource.service.name) > 0.05

// TraceQL Metrics: сравнение с порогом (3.1+ comparison operators)
{ span.http.status_code >= 400 } | rate() by (resource.service.name) > 10

// Поиск спанов с конкретными ошибками и событиями
{ status = error && event.name = "exception" }

// Поиск по атрибутам ресурсов
{ resource.node.name = "k8s-node-1" }
```

**TraceQL Metrics (GA, с v3.0; арифметика — с v3.1):** метрики добавляются к любому TraceQL-запросу через пайплайн `| <функция> by (<атрибут>)`. Доступные функции: `rate`, `count_over_time`, `sum_over_time`, `max_over_time`, `min_over_time`, `avg_over_time`, `quantile_over_time`, `histogram_over_time`, `compare`. Результаты фильтруются операторами сравнения (`>`, `>=`, `<`, `<=`, `=`, `!=`) и функциями `topk`/`bottomk`. С 3.1 поддерживается арифметика между метриками (деление, вычитание, умножение, сложение) для построения вычисляемых показателей (например, error rate = `rate(error) / rate(total)`). Метрики включены по умолчанию и читают только RF1-блоки: данные, принятые в Tempo 2.x без local-blocks processor, для metric-запросов недоступны.

### Интеграции

**Grafana Alloy** — рекомендуемый агент для сбора и передачи трейсов. Полностью заменяет старые коллекторы (Promtail, Grafana Agent) и поддерживает нативную корреляцию с профилями Pyroscope. Подробнее: [Grafana Alloy](../Grafana/grafana_alloy_overview.md).

**Grafana Pyroscope** — позволяет выполнять переход «Span-to-Profile». Если спан содержит `profile_id` (когда в Tempo включён `span_profiling`), Grafana предложит открыть Flame Graph для этого конкретного вызова.

**Traces Drilldown** — UI в Grafana для поточечного анализа latency и ошибок без написания TraceQL: запросы генерируются автоматически, а затем доступны для ручной доработки.

**Loki и Mimir** — корреляция через `trace_id` (Derived Fields в [Loki](../Loki/loki_overview.md)) и Exemplars (в [Mimir](../Mimir/mimir_overview.md) или Prometheus). В Tempo 3.1 корреляция стала двусторонней: из Grafana Explore можно перейти от трейса к связанным логам и метрикам по контексту.

### Безопасность

**TLS/mTLS для OTLP:**
```yaml
server:
  http_listen_port: 3200
  grpc_listen_port: 9095

tls:
  cert_file: /etc/tempo/tls/tls.crt
  key_file: /etc/tempo/tls/tls.key
  client_ca_file: /etc/tempo/tls/ca.crt   # для mTLS
```

**Аутентификация в Kafka:**
```yaml
ingest:
  kafka:
    sasl_username: <USERNAME>
    sasl_password: <PASSWORD>
    tls:
      ca_file: /etc/tempo/tls/kafka-ca.crt
      cert_file: /etc/tempo/tls/kafka-tls.crt
      key_file: /etc/tempo/tls/kafka-tls.key
```

**Аутентификация в S3-совместимом хранилище:**
```yaml
storage:
  trace:
    s3:
      access_key: <ACCESS_KEY>
      secret_key: <SECRET_KEY>
      endpoint: minio.tempo.svc:9000
      insecure: false
```

**Рекомендации:**
- Используйте mTLS для связи между компонентами Tempo в микросервисном режиме.
- Храните секреты в Kubernetes Secrets или HashiCorp Vault; не коммитьте ключи в репозиторий.
- Ограничьте доступ к API Tempo (порты 3200, 9095, 4317, 4318) через NetworkPolicy или firewall.
- **Redis cache (3.1+):** Redis Cluster стал режимом по умолчанию; Sentinel удалён. Для single-node Redis добавьте `single_node: true`. Переименованы ключи: `idle_timeout` → `conn_max_idle_time`, `max_connection_age` → `conn_max_lifetime`. TLS-блок заменён dskit-стилем (`tls_cert_path`, `tls_key_path`, `tls_ca_path`, `tls_server_name`). Redis Cluster требует Redis 7+.

### Мониторинг и алертинг

Полный справочник метрик, alert-правил и Grafana-дашбордов — в [Архитектура и операции Tempo](./architecture_operations.md#мониторинг-и-алертинг). Краткая сводка ключевых метрик:

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `tempo_distributor_kafka_write_errors_total` | Ошибки записи в Kafka | > 0 за 5 минут |
| `tempo_distributor_kafka_write_bytes_total` | Объём записанных данных | Резкое снижение > 50% |
| `tempo_distributor_kafka_write_latency_seconds` | Задержка записи в Kafka | > 1 секунда |
| `tempo_live_store_ready` | Готовность live-store | < 1 при наличии трафика |
| `tempo_live_store_lagged_requests_total` | Отставание live-store | Рост тренда |
| `tempo_live_store_records_dropped_total` | Отброшенные записи в live-store | > 0 |
| `tempo_block_builder_fetch_errors_total` | Ошибки чтения Kafka block-builder-ом | > 0 |
| `tempo_block_builder_spans_deduped_total` | Дедуплицированные спаны | Резкий рост = дублирование в источнике |
| `tempo_ingest_group_partition_lag_seconds` | Лаг партиций Kafka | > 60 секунд |
| `tempo_backend_scheduler_jobs_completed_total` | Выполненные backend-worker задачи (компоновка, retention, redaction) | Отсутствие роста > 1 часа |
| `tempo_backend_scheduler_redaction_traces_found_total` | Трейсы найдены при redaction (3.1+) | контроль dry-run vs actual |
| `tempo_vulture_trace_error_total` | Ошибки валидации Tempo Vulture | > 0 |
| `tempo_ingester_live_traces` | Активные трейсы в ingester (2.x) | Должен стремиться к 0 при выводе |
| `tempo_ingester_flush_queue_length` | Очередь флаша ingester (2.x) | Должен стремиться к 0 при выводе |

**Пример алерт-правил Prometheus:**

```yaml
groups:
- name: tempo-alerts
  rules:
  - alert: TempoKafkaWriteErrors
    expr: rate(tempo_distributor_kafka_write_errors_total[5m]) > 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Tempo не может записывать в Kafka"
      
  - alert: TempoLiveStoreLagging
    expr: tempo_live_store_lagged_requests_total > 0
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Live-store отстаёт от Kafka"
      
  - alert: TempoBlockBuilderErrors
    expr: rate(tempo_block_builder_fetch_errors_total[5m]) > 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Block-builder не может читать из Kafka"

  - alert: TempoKafkaWriteLatency
    expr: histogram_quantile(0.99, rate(tempo_distributor_kafka_write_latency_seconds_bucket[5m])) > 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Задержка записи в Kafka превышает 1 секунду"
```

### Производительность и масштабирование

**Партиционирование Kafka:**
- Начинайте с ~10 МБ/с пиковой записи на партицию.
- Количество партиций должно быть равно количеству реплик live-store + block-builder.

**Сценарии масштабирования:**

| Сценарий | Действие |
| :--- | :--- |
| Увеличение приёма | Увеличить replicas Distributor; добавить партиции Kafka; масштабировать live-store и block-builder синхронно |
| Медленные TraceQL-запросы | Увеличить replicas Querier и Query Frontend; настроить кэширование (Redis/Memcached); ограничить временной диапазон запросов |
| Высокая латентность записи | Проверить сеть между Distributor и Kafka; увеличить `target_bytes_per_job` в `query_frontend.metrics`; проверить IOPS объектного хранилища |

  **Кэширование результатов запросов (3.1+):** для Redis Cluster добавьте `single_node: false` (по умолчанию); для single-node Redis — `single_node: true`. Переименованы ключи: `idle_timeout` → `conn_max_idle_time`, `max_connection_age` → `conn_max_lifetime`. Для Memcached: `max_idle_conns` по умолчанию 100, `min_idle_conns_headroom_percentage: 0` для старого поведения.
  ```yaml
  cache:
    background:
      writeback_goroutines: 10
      writeback_buffer: 10000
    caches:
      - roles:
          - frontend-search
        redis:
          endpoint: redis:6379
          single_node: true        # 3.1+: обязательно для single-node Redis
          conn_max_idle_time: 5m   # 3.1+: было idle_timeout
          conn_max_lifetime: 1h    # 3.1+: было max_connection_age
          timeout: 500ms
          expiration: 1h
  ```

### Операции и команды (tempo-cli)

`tempo-cli` — утилита для администрирования, диагностики и upkeep Tempo. Полный справочник команд, примеры миграции конфигурации 2.x → 3.x, redaction по TraceQL-запросу, конвертация блоков vParquet4 → vParquet5 и SRE-процедуры — в [Архитектура и операции Tempo](./architecture_operations.md#операции-и-команды-tempo-cli).

### Диагностика и устранение неполадок

Полная таблица troubleshooting, runbook-ы (TempoKafkaWriteErrors, TempoLiveStoreLagging), процедуры ротации сертификатов, управление логами, backup verification и emergency procedures — в [Архитектура и операции Tempo](./architecture_operations.md#диагностика-и-устранение-неполадок) и разделе [SRE-процедуры](./architecture_operations.md#sre-процедуры).

### Рекомендации по эксплуатации

Глубокие operational recommendations, чек-листы (daily/weekly/monthly), backend scheduler/retention/GDPR redaction, мониторинг и алертинг — в [Архитектура и операции Tempo](./architecture_operations.md). Уникальные рекомендации для index.md:

- **Streaming Queries:** в настройках Grafana включите `Query Streaming` для мгновенного отображения первых результатов поиска.
- **Сэмплирование:** для высоконагруженных систем используйте tail-based sampling в OTel Collector, чтобы сохранять все ошибки и медленные запросы, отбрасывая «здоровые» данные.

---

## Дополнительная информация

Tempo является фундаментом [LGTM Stack](../Kubernetes/Installation/LGTM_Stack/lgtm_otel_minikube_overview.md) и тесно взаимодействует с [OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md).

### См. также

- [Архитектура и операции Tempo](./architecture_operations.md) — компоненты v3.x, vParquet, миграция, операции и команды (tempo-cli), troubleshooting, best practices, SRE-процедуры и мониторинг.
- [Tempo CLI documentation](https://grafana.com/docs/tempo/latest/operations/tempo_cli/)
- [TraceQL Documentation](https://grafana.com/docs/tempo/latest/traceql/)
- [Миграция на Tempo 3.0](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/migrate-to-3/)
- [Upgrade to Tempo 3.1](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/upgrade/) — изменения конфигурации Redis, memcached defaults, vParquet5 по умолчанию
