# Архитектура и операции Tempo

## Определения

**Tempo** — высокомасштабируемое распределённое хранилище трассировок. В данном файле рассматриваются глубокие технические аспекты архитектуры 3.0: компоненты, форматы блоков, конфигурация, миграция с 2.x и эксплуатация.

**Decoupled Read/Write Path** — архитектурная модель Tempo 3.0, при которой пути записи и чтения полностью независимы, а долговечность данных (durability) обеспечивает внешняя Kafka-совместимая очередь, а не репликация внутренних процессов (RF3). Запись: Distributor → Kafka → block-builder (Parquet в объектное хранилище, RF1). Чтение: live-store (свежие данные) + Querier (исторические блоки).

**RF1 / RF3 (Replication Factor)** — количество копий блока в объектном хранилище. В Tempo 2.x трейсы реплицировались на ingester-ах с фактором 3, что порождало 2–2.5× дублирование данных. Tempo 3.0 благодаря Kafka-очереди пишет каждый блок ровно один раз (RF1): трейсы шардируются по ID на уникальные партиции, поэтому каждый блок строится однократно.

**vParquet4** — блоковый формат по умолчанию в Tempo 3.0 (введён в 2.0). Добавляет колонки, позволяющие искать по array-атрибутам, событиям (events) и связям (links).

**vParquet5** — опциональный production-ready формат (доступен с 2.10/2.11 и в 3.0). Помимо vParquet4 даёт расширенные dedicated-колонки (20 string + 5 integer на scope), event-scoped колонки, blob-колонки (zstd вместо словарного кодирования) и array-колонки.

Навигация: [Главная Tempo](./index.md).

---

## Основные концепции

### Архитектура 3.0 и компоненты

С версии 3.0 write path и read path полностью независимы. Distributor пишет трейсы в Kafka, откуда их потребляют **block-builder**, **live-store** и **metrics-generator**. Компоновкой и retention занимаются **backend scheduler** и **backend worker**. Ingester, compactor и SSB-режим удалены.

| Компонент | Роль в 3.0 | Изменения против 2.x |
| :--- | :--- | :--- |
| **Distributor** | Приём, валидация, лимиты | Вместо передачи по gRPC в ingester-ы пишет трейсы в Kafka. Запись подтверждается (ack) только после подтверждения Kafka. |
| **Kafka / Queue** | Durability layer | Единственный topic (`ingest.kafka.topic`); буфер между приёмом и хранением; позволяет RF1. Ориентир: ~10 МБ/с пиковой записи на партицию. |
| **Block-builder** | Запись блоков в object storage | Новый компонент. Потребляет Kafka, строит Parquet-блоки (RF1) и дедуплицирует спаны внутри трейсов. Один экземпляр — на одну партицию. |
| **Live-store** | Свежие данные в запросах | Новый компонент. Потребляет тот же поток Kafka и обслуживает запросы за последние ~30–60 минут; в монолитном режиме также флашит блоки в storage. Один экземпляр — на партицию. |
| **Querier** | Выполнение запросов | Свежий диапазон читает из live-store, историю — из object storage; на лету выполняет TraceQL Metrics. |
| **Query Frontend** | Оркестрация и шардинг | Разбивает запросы на шарды, управляет кэшем и очередью; параметры metric-запросов — в блоке `query_frontend.metrics`. |
| **Backend scheduler** | Планирование задач | Заменил compactor: job-основанная компоновка с централизованным отслеживанием прогресса, авторетраем упавших задач; retention и redaction. Статус: `/status/backendscheduler`. |
| **Backend worker** | Исполнение задач | Выполняет задачи компоновки/retention, назначенные scheduler-ом. |
| **Metrics-generator** | Генерация метрик (Service Graphs и др.) | В 3.0 читает спаны из Kafka через общий `ingest:`-блок; процессор `local-blocks` удалён (блоки строит block-builder). |

Удалены в 3.0: ingester (и секции конфигурации `ingester`, `ingester_client`), compactor (и `compactor`), `metrics_generator_client`, режим scalable single binary (SSB), encoding v2.

**Ключевой нюанс масштабирования:** количество реплик block-builder и live-store должно быть равно числу партиций Kafka (block-builder-0 читает партицию 0, block-builder-1 — партицию 1 и т.д.). Синхронизация реплик: KEDA-автоскейлер, mirroring-функция Grafana rollout-operator или статический count реплик.

### Режимы деплоя

1. **Монолит (Monolithic mode)** — все компоненты в одном бинарнике, Kafka не требуется: distributor отдаёт данные сразу metrics-generator-у в процессе, live-store обслуживает свежие запросы и сам флашит блоки. Подходит для нагрузки ~100–200 МБ/с.
2. **Микросервисы (Microservices mode)** — каждый компонент запускается отдельным `target`-ом и масштабируется независимо. Требует Kafka-совместимой очереди (Apache Kafka, Redpanda).
3. **SSB (scalable single binary)** — режим удалён в 3.0; при миграции выбирайте монолит или микросервисы.

### Форматы хранения (vParquet)

Parquet — единственный поддерживаемый формат блоков в 3.0 (по умолчанию с 2.0). Блок — директория `<tenant-id>/<block-id>/` в объектном хранилище:

| Файл | Назначение |
| :--- | :--- |
| `meta.json` | Метаданные блока: временной диапазон, тенант, block ID, поле `replaces` (атомарная замена). |
| `data.parquet` | Данные трейсов в колоночном формате. |
| Bloom filter | Вероятностная структура для быстрого поиска trace ID. |
| Index | Сопоставление trace ID → row groups. |
| `nocompact.flg` | Временный флаг, запрещающий компоновку во время флаша. |

| Версия | Статус в 3.0 | Особенности |
| :--- | :--- | :--- |
| vParquet3 | **Удалена** (deprecated в 2.10) | Больше не поддерживается. |
| **vParquet4** | **По умолчанию (default)** | Колонки для array-атрибутов, событий и связей; 10 string dedicated-колонок на scope. |
| **vParquet5** | **Опциональный, production-ready** | 20 string + 5 integer dedicated-колонок на scope, event-scoped колонки, blob-колонки (zstd для high-cardinality/high-length атрибутов), array-колонки. |

Смена версии формата (применяется ко всем компонентам, пишущим блоки — live-store и block-builder):

```yaml
storage:
  trace:
    block:
      version: vParquet4   # или vParquet5
```

Старые блоки в других форматах остаются читаемыми; новые всегда пишутся в сконфигурированной версии.

**Dedicated columns** — продвижение часто запрашиваемых атрибутов из общей колонки `Attrs` в отдельные колонки Parquet для ускорения TraceQL-запросов:

```yaml
storage:
  trace:
    block:
      parquet_dedicated_columns:
        - name: http.method
          type: string
          scope: span
        - name: deployment.environment
          type: string
          scope: resource
```

---

## Практические сценарии

### Миграция на Tempo 3.0

**Предусловия:** данные в формате vParquet4+ (3.0 не читает vParquet3 и старше); доступ к тому же объектному хранилищу; для микросервисного режима — работающая Kafka-совместимая очередь (монолиту Kafka не нужна); из SSB перейти на монолит или микросервисы.

1. **Миграция конфигурации** — `tempo-cli migrate config` читает конфиг 2.x и выдаёт валидный конфиг 3.0: удаляет блоки `ingester`, `ingester_client`, `compactor`, `metrics_generator_client` и конфиг `local_blocks`; в микросервисном режиме добавляет `ingest:`-блок; выставляет `compaction_disabled: true` в дефолтных overrides. Данные в хранилище утилита не изменяет:

   Монолит:
   ```bash
   tempo-cli migrate config --mode=monolithic old-config.yaml > new-config.yaml
   ```

   Микросервисы:
   ```bash
   tempo-cli migrate config --kafka-address=<BROKER> --kafka-topic=<TOPIC> old-config.yaml > new-config.yaml
   ```

2. **Legacy overrides** — плоский (unscoped) формат overrides в 3.0 отключён по умолчанию, иначе Tempo не стартует. Мигрируйте через `tempo-cli migrate overrides-config` либо временно включите `enable_legacy_overrides: true` (удалят в будущих релизах).

3. **Деплой 3.0 параллельно с 2.x** (микросервисы) — оба деплоймента указывают на одно объектное хранилище. Пока работают compactor-ы 2.x, одновременно может писать только одна система компоновки: держите `compaction_disabled: true` в дефолтном и каждом пер-тенантном overrides (они не наследуют свойства). Проверьте готовность: `tempo_live_store_ready == 1` (на свежем деплойменте без трафика live-store может «дозревать» до `live_store.readiness_max_wait`, по умолчанию 30 мин), `rate(tempo_block_builder_fetch_errors_total[5m])` около нуля; валидация через Tempo Vulture (`tempo_vulture_trace_error_total == 0`) или запрос по известному trace ID:

   ```bash
   curl http://<TEMPO_3_QUERY_FRONTEND>:3200/api/traces/<TRACE_ID>
   # → JSON трейса, если 3.0 читает исторические блоки из хранилища
   ```

4. **Переключение трафика** — постепенно переводите клиентов (OpenTelemetry Collectors, Grafana Alloy) на 3.0; контролируйте `tempo_distributor_kafka_write_bytes_total` и `tempo_ingest_group_partition_lag_seconds`.

5. **Вывод 2.x** — дождитесь флаша ingester-ов (`tempo_ingester_live_traces` и `tempo_ingester_flush_queue_length` → 0), масштабируйте compactor-ы 2.x в ноль, снимите `compaction_disabled` в 3.0, деинсталлируйте 2.x. Общее хранилище не удаляйте.

**Ограничения:** нет in-place downgrade с 3.0 на 2.x. До деинсталляции 2.x роллбэк возможен переключением трафика (routing change). Блоки, записанные block-builder-ом (RF1), читаемы 2.x при совместимом формате (vParquet4+). **TraceQL Metrics читают только RF1-блоки:** если в 2.x не использовался процессор `local-blocks`, метрики покроют только данные после миграции.

**Верификация после миграции:** `tempo_distributor_kafka_write_bytes_total` растёт, `tempo_block_builder_fetch_records_total` растёт при `tempo_block_builder_fetch_errors_total` = 0, `tempo_live_store_ready` = 1 при `tempo_live_store_records_dropped_total` = 0, исторические запросы возвращают данные, backend-worker-ы выполняют компоновку.

### Примеры конфигурации (v3.0)

#### Микросервисы с Kafka

Минимальный блок подключения Kafka (`ingest:` обязателен в микросервисном режиме):

```yaml
server:
  http_listen_port: 3200

storage:
  trace:
    backend: s3
    s3:
      bucket: tempo-traces
    block:
      version: vParquet4

ingest:
  kafka:
    address: kafka-1:9092,kafka-2:9092
    topic: tempo-traces
    auto_create_topic_enabled: true
    auto_create_topic_default_partitions: 12   # ~10 МБ/с на партицию
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

Блоки `live_store:` и `block_builder:` используют разумные значения по умолчанию и для большинства деплойментов не требуют override. Число реплик live-store и block-builder должно равняться числу партиций Kafka.

#### Монолит

Kafka не нужен: все компоненты работают в одном процессе, live-store флашит блоки сам. Достаточно мигрировать конфиг и обновить бинарник.

#### TraceQL Metrics (GA)

Параметры metric-запросов живут в блоке `query_frontend.metrics` (граница live-store/backend по умолчанию `query_backend_after: 15m`, лимит диапазона запроса — `max_duration: 24h`, exemplars — `max_exemplars`):

```yaml
query_frontend:
  metrics:
    concurrent_jobs: 1000
    target_bytes_per_job: 2.25e+08   # ~225 МБ
    interval: 30m0s

cache:
  background:
    writeback_goroutines: 10
    writeback_buffer: 10000
  caches:
    - roles:
        - frontend-search
      redis:
        endpoint: redis:6379
        timeout: 500ms
        expiration: 1h
```

Кэширование результатов выполняется топ-левел-блоком `cache:` с ролями (`frontend-search`, `bloom`, `parquet-footer`, `parquet-page`, `parquet-column-idx`, `parquet-offset-idx`, `trace-id-index`); бэкенды — Redis или Memcached. Таймауты metric-запросов настраиваются через `querier.search.query_timeout`, `server.http_server_read_timeout` и `server.http_server_write_timeout`.

### Рекомендации по эксплуатации

- **S3 Durability:** благодаря Kafka запись использует RF1; versioning в S3 можно отключить, если не требуется внешними политиками.
- **Компоновка (job-based):** в 3.0 компоновку и retention выполняют backend scheduler + backend worker с централизованным отслеживанием прогресса и авторетраем упавших задач. CLI-флаги компоновки утратили дублирующий префикс: `compaction.compaction.block-retention` → `compaction.block-retention`, аналогично `compaction.max-block-bytes` и `compaction.max-objects-per-block`.
- **Параллельная операция с 2.x:** одновременно активна только одна система компоновки — держите `compaction_disabled: true` в 3.0, пока живы compactor-ы 2.x; после вывода 2.x override снимается.
- **Redaction (GDPR):** `tempo-cli redact` отправляет задачи в backend scheduler, который переписывает затронутые блоки в хранилище; прогресс — через `/status/backendscheduler`. Интерфейс `TraceRedactor` позволяет скрывать целые трейсы из результатов запросов (`ErrTraceHidden`), когда точечного удаления спанов недостаточно.
- **Мониторинг приёма и чтения:** `tempo_distributor_kafka_write_errors_total` и `tempo_distributor_kafka_write_bytes_total` (запись в очередь), `tempo_block_builder_fetch_errors_total` и `tempo_block_builder_spans_deduped_total` (block-builder), `tempo_live_store_ready`, `tempo_live_store_records_dropped_total`, `tempo_live_store_lagged_requests_total` (live-store), `tempo_ingest_group_partition_lag_seconds` (задержка в Kafka).
- **Партиционирование:** начинайте с ~10 МБ/с пиковой записи на партицию; реплики live-store/block-builder синхронизируйте с числом партиций (KEDA или rollout-operator mirror).

---

## Дополнительная информация

### См. также

- [Главная Tempo](./index.md) — обзор, определения, TraceQL, сравнение с Jaeger.
- [Tempo architecture reference](https://grafana.com/docs/tempo/latest/reference-tempo-architecture/)
- [Миграция на Tempo 3.0](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/migrate-to-3/)