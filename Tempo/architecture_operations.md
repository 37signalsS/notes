# Архитектура и операции Tempo

## Определения

**Tempo** — высокомасштабируемое распределённое хранилище трассировок. В данном файле рассматриваются глубокие технические аспекты архитектуры 3.0: компоненты, форматы блоков, конфигурация, миграция с 2.x и эксплуатация.

**Decoupled Read/Write Path** — архитектурная модель Tempo 3.0, при которой пути записи и чтения полностью независимы, а долговечность данных (durability) обеспечивает внешняя Kafka-совместимая очередь, а не репликация внутренних процессов (RF3). Запись: Distributor → Kafka → block-builder (Parquet в объектное хранилище, RF1). Чтение: live-store (свежие данные) + Querier (исторические блоки).

**RF1 / RF3 (Replication Factor)** — количество копий блока в объектном хранилище. В Tempo 2.x трейсы реплицировались на ingester-ах с фактором 3, что порождало 2–2.5× дублирование данных. Tempo 3.0 благодаря Kafka-очереди пишет каждый блок ровно один раз (RF1): трейсы шардируются по ID на уникальные партиции, поэтому каждый блок строится однократно.

**vParquet4** — блоковый формат по умолчанию в Tempo 3.0 (введён в 2.0). Добавляет колонки, позволяющие искать по array-атрибутам, событиям (events) и связям (links).

**vParquet5** — опциональный production-ready формат (доступен с 2.10/2.11 и в 3.0). Помимо vParquet4 даёт расширенные dedicated-колонки (20 string + 5 integer на scope), event-scoped колонки, blob-колонки (zstd вместо словарного кодирования) и array-колонки.

**Block (блок)** — атомарная единица хранения трейсов в объектном хранилище. Директория `<tenant-id>/<block-id>/` с файлами `meta.json`, `data.parquet`, Bloom filter, index и временными флагами.

**Bloom filter** — вероятностная структура данных, хранящаяся в каждом блоке для быстрого ответа на вопрос «возможно ли, что trace ID присутствует в этом блоке?». Позволяет Querier-у пропускать чтение `data.parquet` для отсутствующих трейсов. Размер фильтра и false-positive rate обычно настраиваются автоматически; при изменении объёма блока перестройка не требуется.

**Index (Parquet offset index)** — сопоставление trace ID → row groups внутри `data.parquet`. Querier использует index после успешного прохождения Bloom filter для прямого перехода к нужным row groups без полного сканирования файла.

**Atomic Replacement (атомарная замена)** — механизм обновления блоков через поле `replaces` в `meta.json`. При изменении блока (например, после redaction или compaction) новый блок ссылается на заменяемый; Querier атомарно переключается на новую версию, гарантируя целостность reads.

**`nocompact.flg`** — временный файл-флаг в директории блока, запрещающий backend scheduler запускать компоновку для этого блока, пока block-bisher или live-store активно его модифицирует. Флаг удаляется автоматически после завершения флаша.

**Deduplication (дедупликация)** — процесс удаления дублирующихся спанов внутри одного трейса на уровне block-builder. Kafka гарантирует exactly-once доставку спанов в рамках партиции по ключу `trace_id`, но deduplication на стороне block-builder защищает от повторов при перезапуске консьюмера или retry.

**Backpressure (обратное давление)** — механизм предотвращения переполнения Kafka при превышении скорости записи над скоростью потребления block-builder-ом или live-store. Проявляется через рост `tempo_ingest_group_partition_lag_seconds`; устранением служит масштабирование consumer-ов или увеличение партиций.

**Job-based Compaction (job-based компоновка)** — в 3.0 компоновка и retention реализованы через backend scheduler + backend worker. Scheduler создаёт job-задачи с централизованным отслеживанием прогресса и авторетраем при сбоях; worker выполняют задачи. CLI-флаги утратили дублирующий префикс: `compaction.compaction.block-retention` → `compaction.block-retention`.

**Trace Redactor** — интерфейс для скрытия целых трейсов из результатов запросов. Когда точечное удаление спанов через `tempo-cli redact` недостаточно, Trace Redactor возвращает `ErrTraceHidden`, полностью скрывая трейс от Querier.

**Span Profiling** — интеграция Tempo с профилировщиками (Grafana Pyroscope). При включённом `span_profiling` в спан добавляются pprof-лейблы, что позволяет переходить от конкретного спана к Flame Graph профиля CPU/Memory соответствующей строки кода.

**Multi-tenancy (многопользовательская изоляция)** — встроенный механизм изоляции данных между tenants (командами, клиентами, окружениями). Каждый tenant имеет независимый набор блоков, политики retention и overrides.

**Retention Policy (политика хранения)** — набор правил, определяющих время жизни трейсов. В Tempo 3.0 retention и компоновку блоков выполняют backend scheduler и backend worker; устаревшие блоки удаляются по завершении заданного окна хранения.

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

### Жизненный цикл блока

1. **Ingest:** Distributor получает трейс по OTLP/Jaeger/Zipkin/Kafka, выполняет validation и rate-limiting, записывает спаны в Kafka-очередь с ключом `trace_id`. Запись считается завершённой только после подтверждения Kafka (ack).
2. **Consume:** block-builder потребляет партицию Kafka, группирует спаны по временным окнам и tenant-ам. В рамках одного окна формируется один блок. Длительность окна настраивается через `block_builder.block_duration`.
3. **Deduplication:** перед записью block-builder удаляет дублирующиеся спаны внутри трейса (защита от retry на уровне Distributor или Kafka consumer group rebalance).
4. **Write:** блок записывается в объектное хранилище в формате vParquet4/vParquet5 с RF1. Одновременно создаётся `meta.json` с полем `replaces = ""` (первая версия) или ID предыдущего блока (атомарная замена).
5. **Indexing:** Bloom filter и Parquet offset index строятся на лету при записи или асинхронно после; Querier использует их для фильтрации.
6. **Compaction & Retention:** backend scheduler планирует job на объединение мелких блоков в крупные и удаление блоков старше retention. Backend worker выполняет job с авторетраем при сбоях. Прогресс отслеживается через `/status/backendscheduler`.
7. **Query:** Querier проверяет Bloom filter → index → читает row groups из `data.parquet`. Свежие данные (~30–60 минут) обслуживаются live-store из того же потока Kafka.

### Стратегия партиционирования Kafka

Для RF1 ключевым является распределение трейсов по партициям. Tempo использует ключ `trace_id` при записи в Kafka, что гарантирует:
- Все спаны одного трейса попадают в одну партицию.
- block-builder читает партицию упорядоченно, что упрощает deduplication.
- Отсутствие cross-partition зависимостей при построении блоков.

При миграции или изменении партиций: добавляйте партиции только; удаление партиций не поддерживается. Убедитесь, что количество реплик block-builder/live-store синхронизировано с новым числом партиций до перезапуска.

### Backpressure и устойчивость

Kafka выступает буфером между Distributor и block-builder/live-store. При превышении скорости потребления над скоростью записи:
- Рост лага партиций (`tempo_ingest_group_partition_lag_seconds`).
- Увеличение использования диска брокерами Kafka.
- Потенциальное повышение latency до появления трейсов в запросах (live-store «дозревает»).

Меры: масштабирование live-store и block-builder, увеличение партиций, увеличение `fetch.message.max.bytes` у consumer-ов, проверка IOPS объектного хранилища.

### Backend Scheduler и Retry Policy

Backend scheduler хранит состояние job-ов в метаданных (обычно в том же объектном хранилище или встроенном мета-store). При сбое worker-а:
- Job возвращается в очередь с экспоненциальным backoff.
- Повторные попытки не создают дублирующие блоки благодаря проверке `replaces` и идемпотентности операций compaction/retention.
- Статус и прогресс доступны через `/status/backendscheduler` (API) и метрики `tempo_backend_*`.

### Кэширование в Querier

Для снижения нагрузки на объектное хранилище Tempo кэширует:
- **Bloom filter** и **Parquet footer** — в памяти Querier или внешнем кэше (Redis/Memcached).
- **Parquet page / column index / offset index** — частые запросы к одним и тем же блокам.
- **Результаты TraceQL-запросов** — топ-левел кэш с ролями `frontend-search`, `bloom`, `parquet-footer`, `parquet-page`, `parquet-column-idx`, `parquet-offset-idx`, `trace-id-index`.

Размер кэша и TTL настраиваются в блоке `cache:`. Для production-сред с высокой повторяемостью запросов рекомендуется Redis с expiration ≥ 1h.

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

### Предварительные требования

**Аппаратные требования:**
- **Монолитный режим:** 2+ CPU, 4–8 ГБ RAM, 50+ ГБ диска (в зависимости от retention и объёма трафика).
- **Микросервисный режим:** отдельные узлы для Distributor, Query Frontend, Querier, live-store, block-builder; Kafka-кластер на 3+ брокерах для продакшена.
- **Объектное хранилище:** S3-совместимое хранилище (MinIO, локальный диск) или S3-совместимые решения.

**Программные зависимости:**
- Kubernetes 1.24+ (для production-деплоя) или Docker/Podman.
- Helm 3.12+.
- Kafka 2.8+ (только для микросервисного режима; совместимые очереди: Redpanda).
- S3-совместимое хранилище с поддержкой versioning (опционально) и lifecycle-правил.

**Сетевые требования:**
- Порты: 3200 (HTTP API), 4317 (OTLP gRPC), 4318 (OTLP HTTP), 9095 (gRPC receiver), 14268 (Jaeger).
- Для Kafka-режима: порт 9092 (broker), достаточная пропускная способность между Tempo и брокерами.

### Требования к ресурсам и планирование ёмкости

#### CPU / RAM / Disk per component

| Компонент | CPU (рекомендация) | RAM (рекомендация) | Disk (локальный) | Замечания |
| :--- | :--- | :--- | :--- | :--- |
| **Distributor** | 1–2 ядра | 2–4 ГБ | нет | Bound по CPU при высокой нагрузке OTLP; memory-bound при кэшировании. |
| **Query Frontend** | 1–2 ядра | 2–4 ГБ | нет | Требует CPU для TraceQL-парсинга; кэши увеличивает RAM. |
| **Querier** | 2–4 ядра | 4–8 ГБ | нет | Memory-bound при больших временных диапазонах; настраивайте `max_duration` и `concurrent_jobs`. |
| **Live-store** | 2–4 ядра | 4–8 ГБ | 20–50 ГБ | Читает Kafka, хранит свежие блоки; disk нужен для WAL/блоков до флаша. |
| **Block-builder** | 2–4 ядра | 4–8 ГБ | 20–100 ГБ | Высокое потребление RAM при большом числе спанов в блоке; disk для staging перед флашем. |
| **Metrics-generator** | 1–2 ядра | 2–4 ГБ | нет | Зависит от `interval` и количества service graphs. |
| **Backend scheduler** | 1 ядро | 2 ГБ | нет | Легковесный; хранит метаданные job-ов. |
| **Backend worker** | 2–4 ядра | 4–8 ГБ | 20–50 ГБ | IO-bound при чтении старых блоков для compaction/retention. |

#### Формулы планирования

- **Пропускная способность Kafka:** начинайте с ~10 МБ/с на партицию. При пиковой нагрузке 100 МБ/с требуется ≥10 партиций. Рост числа партиций в production — операция с downtime; планируйте запас.
- **Ёмкость объектного хранилища:** примерно 1–3 ГБ на 1 млн спанов (зависит от cardinality атрибутов и формата vParquet4/vParquet5). Учитывайте retention × средний дневной объём + 20% запас на compaction overhead.
- **Живой стек (live-store):** время хранения свежих данных ~30–60 минут; объём ≈ (пиковая скорость записи) × (3600 секунд) × 2–3× (дедупликация).

#### Kubernetes Resource Requests/Limits (пример)

```yaml
# Пример для Query Frontend
resources:
  requests:
    cpu: "1000m"
    memory: "2Gi"
  limits:
    cpu: "2000m"
    memory: "4Gi"

# Пример для Querier (высоконагруженный)
resources:
  requests:
    cpu: "2000m"
    memory: "4Gi"
  limits:
    cpu: "4000m"
    memory: "8Gi"
```

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

### Деплой в Kubernetes

#### Пример манифеста (микросервисы)

```yaml
# tempo-distributor.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tempo-distributor
  namespace: tempo
spec:
  replicas: 3
  selector:
    matchLabels:
      app: tempo-distributor
  template:
    metadata:
      labels:
        app: tempo-distributor
    spec:
      containers:
        - name: distributor
          image: grafana/tempo:3.0
          args: ["-target=distributor"]
          ports:
            - containerPort: 3200
            - containerPort: 4317
            - containerPort: 4318
            - containerPort: 9095
          livenessProbe:
            httpGet:
              path: /ready
              port: 3200
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /ready
              port: 3200
            initialDelaySeconds: 5
            periodSeconds: 5
          resources:
            requests:
              cpu: "1000m"
              memory: "2Gi"
            limits:
              cpu: "2000m"
              memory: "4Gi"
```

#### Health Check Endpoints

| Endpoint | Назначение | Ожидаемый ответ |
| :--- | :--- | :--- |
| `GET /ready` | Готовность принимать трафик | `{"status":"ready"}` |
| `GET /metrics` | Метрики Prometheus | Текст Prometheus format |
| `GET /api/traces/{traceID}` | Поиск трейса по ID | JSON с трейсом или 404 |
| `POST /api/search` | Поиск трейсов (TraceQL) | JSON с результатами |
| `GET /status/backendscheduler` | Статус backend scheduler | JSON с job-статистикой |

#### Network Policy (микросервисный режим)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: tempo-allow-ingress
  namespace: tempo
spec:
  podSelector:
    matchLabels:
      app: tempo-distributor
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: otel-collector
      ports:
        - protocol: TCP
          port: 4317
        - protocol: TCP
          port: 4318
```

#### Rolling Update Procedure

1. Убедитесь, что оба деплоймента (старый и новый) указывают на одно объектное хранилище.
2. Установите `compaction_disabled: true` в дефолтных и пер-тенантных overrides для нового деплоймента.
3. Выполните rolling update Distributor ( Recreate или RollingUpdate с maxSurge=0, т.к. Kafka consumer group rebalance).
4. Обновите Query Frontend, Querier, live-store, block-builder по очереди.
5. Проверьте метрики: `tempo_live_store_ready == 1`, `tempo_block_builder_fetch_errors_total` ≈ 0.
6. Постепенно переключите трафик на 3.0.
7. После стабилизации снимите `compaction_disabled` и уберите 2.x.

### Безопасность (hardening checklist)

- [ ] **TLS everywhere:** включите TLS для всех внешних портов (3200, 4317, 4318, 9095) и внутреннего взаимодействия (mTLS между компонентами в микросервисном режиме).
- [ ] **Kafka SASL:** используйте SASL/SCRAM или mTLS для аутентификации в Kafka; ограничьте ACL на topic `tempo-traces`.
- [ ] **S3 credentials:** храните ключи в Kubernetes Secrets или HashiCorp Vault; не коммитьте в репозиторий. Используйте IAM-роли (если поддерживаются хранилищем) вместо статических ключей.
- [ ] **NetworkPolicy:** ограничьте доступ к портам Tempo только authorised sources (OTel Collector, Grafana, Querier).
- [ ] **RBAC:** Tempo не требует встроенных RBAC; управление доступом осуществляется на уровне инфраструктуры (K8s NetworkPolicy, Kafka ACL, S3 IAM).
- [ ] **Secrets rotation:** регулярно ротируйте ключи S3 и Kafka; проверяйте срок действия TLS-сертификатов.
- [ ] **Audit logging:** включите аудит запросов к API Tempo (порт 3200) через Kubernetes audit или reverse proxy.

### Конфигурация объектного хранилища

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
      version: vParquet4
```

**Пример: локальный диск (dev/test only)**

```yaml
storage:
  trace:
    backend: local
    local:
      path: /var/tempo/traces
    block:
      version: vParquet4
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

### Рекомендации по эксплуатации

- **S3 Durability:** благодаря Kafka запись использует RF1; versioning в S3 можно отключить, если не требуется внешними политиками.
- **Компоновка (job-based):** в 3.0 компоновку и retention выполняют backend scheduler + backend worker с централизованным отслеживанием прогресса и авторетраем упавших задач. CLI-флаги компоновки утратили дублирующий префикс: `compaction.compaction.block-retention` → `compaction.block-retention`, аналогично `compaction.max-block-bytes` и `compaction.max-objects-per-block`.
- **Параллельная операция с 2.x:** одновременно активна только одна система компоновки — держите `compaction_disabled: true` в 3.0, пока живы compactor-ы 2.x; после вывода 2.x override снимается.
- **Redaction (GDPR):** `tempo-cli redact` отправляет задачи в backend scheduler, который переписывает затронутые блоки в хранилище; прогресс — через `/status/backendscheduler`. Интерфейс `TraceRedactor` позволяет скрывать целые трейсы из результатов запросов (`ErrTraceHidden`), когда точечного удаления спанов недостаточно.
- **Мониторинг приёма и чтения:** `tempo_distributor_kafka_write_errors_total` и `tempo_distributor_kafka_write_bytes_total` (запись в очередь), `tempo_block_builder_fetch_errors_total` и `tempo_block_builder_spans_deduped_total` (block-builder), `tempo_live_store_ready`, `tempo_live_store_records_dropped_total`, `tempo_live_store_lagged_requests_total` (live-store), `tempo_ingest_group_partition_lag_seconds` (задержка в Kafka).
- **Партиционирование:** начинайте с ~10 МБ/с пиковой записи на партицию; реплики live-store/block-builder синхронизируйте с числом партиций (KEDA или rollout-operator mirror).
- **Семантические конвенции:** строго следуйте OpenTelemetry Semantic Conventions для атрибутов (`http.method`, `db.system`, `exception.type`); это обеспечивает корректную работу TraceQL и корреляцию с другими сигналами.
- **Versioning схем:** используйте versioning для атрибутов (например, `http.request.version: 2`) при внесении breaking changes, чтобы не ломать существующие TraceQL-запросы.

### Восстановление после сбоев (Disaster Recovery)

Tempo не имеет встроенного бэкапа метаданных; объектное хранилище само по себе не является бэкапом при случайном удалении. Рекомендации:

1. **Versioning в S3:** включите versioning на бакете; это защищает от случайного `DELETE` или overwrite блоков. Kafka обеспечивает durability, но не защищает от human error.
2. **Replication бакета:** для production используйте кросс-региональную репликацию (если поддерживается хранилищем) или периодический экспорт списка объектов.
3. **Метаданные:** backend scheduler хранит состояние job-ов в метаданных. При полной потере мета-store бэкап можно восстановить из `meta.json` блоков (они содержат временные диапазоны, tenant, replaces).
4. **Роллбэк 3.0 → 2.x:** in-place downgrade невозможен. До деинсталляции 2.x роллбэк возможен переключением трафика на 2.x (routing change). Блоки RF1 читаемы 2.x при совместимом формате (vParquet4+).

### Runbook: TempoKafkaWriteErrors

**Симптомы:** `rate(tempo_distributor_kafka_write_errors_total[5m]) > 0` более 5 минут.

**Диагностика (0–5 минут):**
1. Проверьте доступность Kafka брокеров: `kubectl exec -n kafka <broker-pod> -- kafka-topics.sh --bootstrap-server localhost:9092 --describe`
2. Проверьте лаг партиций: `tempo_ingest_group_partition_lag_seconds`
3. Проверьте логи Distributor: `kubectl logs -n tempo -l app=tempo-distributor --tail=100 | grep -i kafka`

**Решение:**
- Если брокер недоступен: проверьте NetworkPolicy, DNS, состояние брокера.
- Если переполнение: увеличьте partitions Kafka, проверьте disk usage брокера.
- Если ACL/SASL ошибка: проверьте конфигурацию SASL в Tempo и Kafka.

### Runbook: TempoLiveStoreLagging

**Симптомы:** `tempo_live_store_lagged_requests_total > 0` более 2 минут.

**Диагностика:**
1. Проверьте задержку Kafka: `tempo_ingest_group_partition_lag_seconds`
2. Проверьте ресурсы live-store: `kubectl top pods -n tempo -l app=tempo-live-store`
3. Проверьте IOPS объектного хранилища (если live-store флашит блоки).

**Решение:**
- Масштабируйте live-store: количество реплик = числу партиций Kafka.
- Увеличьте `target_bytes_per_job` в `query_frontend.metrics`.
- Проверьте сеть между Kafka и live-store.

### Бенчмаркинг производительности

#### Тест приёма (ingest benchmark)

```bash
# Используйте otel-bench (OpenTelemetry benchmark tool)
otel-bench run \
  --endpoint tempo-distributor:4317 \
  --protocol grpc \
  --rate 10000 \
  --duration 60s \
  --attributes 10 \
  --events 2
```

Мониторьте во время теста:
- `tempo_distributor_kafka_write_bytes_total` (скорость записи)
- `tempo_ingest_group_partition_lag_seconds` (лаг)
- CPU/Memory Distributor и live-store

#### Тест запросов (query benchmark)

```bash
# Используйте Tempo Vulture для валидации
tempo-vulture \
  --tempo-url=http://tempo-query-frontend:3200 \
  --query-rate=10 \
  --duration=60s \
  --min-duration=100ms \
  --max-duration=5s
```

Мониторьте:
- `tempo_querier_search_duration_seconds` (гистограмма latency)
- `tempo_querier_search_bytes_returned` (объём возвращаемых данных)

### Диагностика и устранение неполадок

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Tempo не стартует** | Отсутствует Kafka в микросервисном режиме или неправильный `ingest:` блок | Проверить конфигурацию `ingest.kafka`; убедиться, что брокеры доступны; `kubectl logs` на distributor | Исправить `ingest:` блок; убедиться, что Kafka запущена и доступна |
| **Трейсы не найдены** | Данные ещё не записаны (live-store не дозрел) или retention истёк | Проверить `tempo_live_store_ready`; убедиться, что trace ID корректен; проверить retention policy | Дождаться `live_store_ready == 1`; проверить `live_store.readiness_max_wait`; убедиться, что retention не удалил блоки |
| **Медленные запросы TraceQL** | Слишком большой временной диапазон или отсутствие кэша | Ограничить `max_duration`; проверить `querier_search_duration_seconds`; включить кэширование Redis | Уменьшить `max_duration`; включить кэш; увеличить `concurrent_jobs`; добавить dedicated columns |
| **Ошибки записи в Kafka** | Брокер недоступен или переполнен | Проверить доступность Kafka; проверить лаг партиций; убедиться в достаточной пропускной способности | Проверить NetworkPolicy; масштабировать Kafka; увеличить partitions |
| **Высокое потребление RAM в block-builder** | Слишком много партиций на один экземпляр | `kubectl top pods`; проверить количество партиций | Масштабировать block-builder: один экземпляр на партицию |
| **Отставание live-store** | Kafka-консьюмер не успевает за продьюсером | Проверить `tempo_ingest_group_partition_lag_seconds`; ресурсы live-store | Масштабировать live-store; проверить IOPS хранилища; уменьшить размер batch-ов |
| **Потеря спанов при приёме** | Backpressure в Kafka или Distributor | Проверить `tempo_distributor_kafka_write_bytes_total`; увеличить partitions Kafka; настроить batch processor в OTel Collector | Увеличить partitions; настроить batch processor; проверить сеть между Distributor и Kafka |
| **Ошибки TLS-рукопожатия** | Неверные сертификаты или несовпадение CN/SAN | Проверить срок действия сертификатов; убедиться, что CN/SAN соответствуют endpoint-ам; `openssl s_client` | Обновить сертификаты; исправить CN/SAN; проверить chain of trust |
| **Duplication спанов** | Несколько источников отправляют одинаковые данные без идемпотентности | Проверить `tempo_block_builder_spans_deduped_total`; логи OTel Collector | Включить дедупликацию на уровне Kafka (ключ `trace_id`); настроить идемпотентность Consumer |
| **Квоты S3 exceeded / 503 SlowDown** | Превышение лимитов запросов к хранилищу | Проверить логи Tempo на 503; метрики S3 (если доступны); `tempo_block_builder_fetch_errors_total` | Увеличить `target_bytes_per_job` для уменьшения числа запросов; запросить лимиты у провайдера хранилища; включить client-side retry с backoff |
| **Высокое потребление диска live-store/block-builder** | Слишком большой `block_duration` или малый flush interval | Проверить `block_builder.block_duration`; использование диска в pods | Уменьшить `block_duration`; настроить lifecycle для staging директории |
| **TraceQL Metrics возвращают только данные после миграции** | В 2.x не использовался `local-blocks` processor | Проверить метрики `tempo_distributor_kafka_write_bytes_total` до и после миграции | Ожидаемое поведение; данные 2.x без local-blocks недоступны для metric-запросов |

### Операционный чек-лист (daily/weekly/monthly)

#### Ежедневно
- [ ] Проверьте алерты Tempo (KafkaWriteErrors, LiveStoreLagging, BlockBuilderErrors).
- [ ] Проверьте лаг партиций Kafka (`tempo_ingest_group_partition_lag_seconds`) — должен быть < 60s.
- [ ] Проверьте готовность live-store (`tempo_live_store_ready == 1`).
- [ ] Проверьте, что backend worker-ы выполняют компоновку (`tempo_backend_jobs_completed_total` растёт).

#### Еженедельно
- [ ] Проверьте использование объектного хранилища (ёммость, количество блоков).
- [ ] Проверьте retention policy: убедитесь, что старые блоки удаляются по расписанию.
- [ ] Проверьте логи на наличие `tempo_block_builder_fetch_errors_total` > 0.
- [ ] Проверьте ресурсы pods (CPU/Memory) — нет ли pods в OOMKilled.

#### Ежемесячно
- [ ] Обновите Tempo до последней стабильной версии (проверьте release notes на breaking changes).
- [ ] Проверьте версию формата блоков (vParquet4 vs vParquet5) — при наличии возможности протестируйте vParquet5.
- [ ] Проверьте конфигурацию dedicated columns — актуальны ли они для текущих TraceQL-запросов.
- [ ] Проверьте backup метаданных и S3 versioning (если включено).

## Дополнительная информация

### См. также

- [Главная Tempo](./index.md) — обзор, определения, TraceQL, сравнение с Jaeger.
- [Tempo architecture reference](https://grafana.com/docs/tempo/latest/reference-tempo-architecture/)
- [Миграция на Tempo 3.0](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/migrate-to-3/)