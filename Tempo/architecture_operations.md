# Архитектура и операции Tempo

**Актуально для:** Grafana Tempo 3.1.x

## Определения

**Tempo** — высокомасштабируемое распределённое хранилище трассировок. В данном файле рассматриваются глубокие технические аспекты архитектуры 3.x: компоненты, форматы блоков, конфигурация, миграция с 2.x и эксплуатация.

**Decoupled Read/Write Path** — архитектурная модель Tempo 3.0, при которой пути записи и чтения полностью независимы, а долговечность данных (durability) обеспечивает внешняя Kafka-совместимая очередь, а не репликация внутренних процессов (RF3). Запись: Distributor → Kafka → block-builder (Parquet в объектное хранилище, RF1). Чтение: live-store (свежие данные) + Querier (исторические блоки).

**RF1 / RF3 (Replication Factor)** — количество копий блока в объектном хранилище. В Tempo 2.x трейсы реплицировались на ingester-ах с фактором 3, что порождало 2–2.5× дублирование данных. Tempo 3.0 благодаря Kafka-очереди пишет каждый блок ровно один раз (RF1): трейсы шардируются по ID на уникальные партиции, поэтому каждый блок строится однократно.

**vParquet4** — блоковый формат, введённый в 2.0. Добавляет колонки для array-атрибутов, событий и связей. По умолчанию в 3.0; в 3.1+ уступил vParquet5.

**vParquet5** — расширенный формат (доступен с 2.10/2.11). 20 string + 5 integer dedicated-колонок на scope (span, resource, event), event-scoped колонки, blob-колонки (zstd для high-cardinality/high-length атрибутов) через `options: ["blob"]`, array-колонки через `options: ["array"]`. **По умолчанию в Tempo 3.1+**; vParquet4 доступен как опциональный. vParquet3 удалена (deprecated в 2.10, enforced в 3.1 — Tempo не стартует при записи в vParquet3).

**Block (блок)** — атомарная единица хранения трейсов в объектном хранилище. Директория `<tenant-id>/<block-id>/` с файлами `meta.json`, `data.parquet`, Bloom filter, index и временными флагами.

**Bloom filter** — вероятностная структура данных, хранящаяся в каждом блоке для быстрого ответа на вопрос «возможно ли, что trace ID присутствует в этом блоке?». Позволяет Querier-у пропускать чтение `data.parquet` для отсутствующих трейсов. Размер фильтра и false-positive rate обычно настраиваются автоматически; при изменении объёма блока перестройка не требуется.

**Index (Parquet offset index)** — сопоставление trace ID → row groups внутри `data.parquet`. Querier использует index после успешного прохождения Bloom filter для прямого перехода к нужным row groups без полного сканирования файла.

**Atomic Replacement (атомарная замена)** — механизм обновления блоков через поле `replaces` в `meta.json`. При изменении блока (например, после redaction или compaction) новый блок ссылается на заменяемый; Querier атомарно переключается на новую версию, гарантируя целостность reads.

**`nocompact.flg`** — временный файл-флаг в директории блока, запрещающий backend scheduler запускать компоновку для этого блока, пока block-builder или live-store активно его модифицирует. Флаг удаляется автоматически после завершения флаша.

**Deduplication (дедупликация)** — процесс удаления дублирующихся спанов внутри одного трейса на уровне block-builder. Kafka гарантирует exactly-once доставку спанов в рамках партиции по ключу `trace_id`, но deduplication на стороне block-builder защищает от повторов при перезапуске консьюмера или retry.

**Backpressure (обратное давление)** — механизм предотвращения переполнения Kafka при превышении скорости записи над скоростью потребления block-builder-ом или live-store. Проявляется через рост `tempo_ingest_group_partition_lag_seconds`; устранением служит масштабирование consumer-ов или увеличение партиций.

**Job-based Compaction (job-based компоновка)** — в 3.0 компоновка и retention реализованы через backend scheduler + backend worker. Scheduler создаёт job-задачи с централизованным отслеживанием прогресса и авторетраем при сбоях; worker выполняют задачи. CLI-флаги утратили дублирующий префикс: `compaction.compaction.block-retention` → `compaction.block-retention`.

**Redaction (GDPR — удаление трейсов)** — механизм удаления трейсов из объектного хранилища. `tempo-cli redact` отправляет задачи в backend scheduler, который переписывает затронутые блоки. В 3.1+ поддерживает удаление по TraceQL-запросу (`--query`), dry-run (`--dry-run`), scoping по времени (`--start`/`--end`). Для удаления по конкретным trace ID используется `tempo-cli rewrite-blocks drop-traces` (работает напрямую с хранилищем).

**Span Profiling** — интеграция Tempo с профилировщиками (Grafana Pyroscope). При включённом `span_profiling` в спан добавляются pprof-лейблы, что позволяет переходить от конкретного спана к Flame Graph профиля CPU/Memory соответствующей строки кода.

**Multi-tenancy (многопользовательская изоляция)** — встроенный механизм изоляции данных между tenants (командами, клиентами, окружениями). Каждый tenant имеет независимый набор блоков, политики retention и overrides.

**Retention Policy (политика хранения)** — набор правил, определяющих время жизни трейсов. В Tempo 3.x retention и компоновку блоков выполняют backend scheduler и backend worker; устаревшие блоки удаляются по завершении заданного окна хранения.

---

## Основные концепции

### Архитектура 3.1 и компоненты

С версии 3.0 write path и read path полностью независимы. Distributor пишет трейсы в Kafka, откуда их потребляют **block-builder**, **live-store** и **metrics-generator**. Компоновкой и retention занимаются **backend scheduler** и **backend worker**. Ingester, compactor и SSB-режим удалены.

| Компонент | Роль в 3.x | Изменения против 2.x |
| :--- | :--- | :--- |
| **Distributor** | Приём, валидация, лимиты | Вместо передачи по gRPC в ingester-ы пишет трейсы в Kafka. Запись подтверждается (ack) только после подтверждения Kafka. |
| **Kafka / Queue** | Durability layer | Единственный topic (`ingest.kafka.topic`); буфер между приёмом и хранением; позволяет RF1. Ориентир: ~10 МБ/с пиковой записи на партицию. |
| **Block-builder** | Запись блоков в object storage | Новый компонент. Потребляет Kafka, строит Parquet-блоки (RF1) и дедуплицирует спаны внутри трейсов. Один экземпляр — на одну партицию. |
| **Live-store** | Свежие данные в запросах | Новый компонент. Потребляет тот же поток Kafka и обслуживает запросы за последние ~30–60 минут; в монолитном режиме также флашит блоки в storage. Один экземпляр — на партицию. |
| **Querier** | Выполнение запросов | Свежий диапазон читает из live-store, историю — из object storage; на лету выполняет TraceQL Metrics. |
| **Query Frontend** | Оркестрация и шардинг | Разбивает запросы на шарды, управляет кэшем и очередью; параметры metric-запросов — в блоке `query_frontend.metrics`. |
| **Backend scheduler** | Планирование задач | Заменил compactor: job-основанная компоновка с централизованным отслеживанием прогресса, авторетраем упавших задач; retention и redaction. Статус: `/status/backendscheduler`. |
| **Backend worker** | Исполнение задач | Выполняет задачи компоновки/retention, назначенные scheduler-ом. |
| **Metrics-generator** | Генерация метрик (Service Graphs и др.) | В 3.x читает спаны из Kafka через общий `ingest:`-блок; процессор `local-blocks` удалён (блоки строит block-builder). |

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

Backend scheduler — singleton-компонент, который создаёт job-задачи и назначает их на backend worker-ы через gRPC. Worker выполняет задачу и отчитывается результатом. Состояние job-ов хранится в work cache (в памяти), периодически сбрасываемой в объектное хранилище для восстановления после сбоя. При сбое worker-а:

- Job возвращается в очередь с экспоненциальным backoff.
- Повторные попытки не создают дублирующие блоки благодаря проверке `replaces` и идемпотентности операций compaction/retention.
- Статус и прогресс доступны через `/status/backendscheduler` (API) и метрики backend scheduler/worker.

**Конфигурация:**

```yaml
backend_scheduler:
  maintenance_interval: 1m
  backend_flush_interval: 1m

backend_worker:
  backend_scheduler_addr: backend-scheduler:9095
  finish_on_shutdown_timeout: 30s
```

**Job types (три типа задач):**
- **Compaction** — объединение малых блоков в большие.
- **Retention** — удаление блоков старше retention window.
- **Redaction** — перезапись блоков для удаления трейсов по GDPR-запросу.

**Статус API (`/status/backendscheduler`):** возвращает plain-text таблицу с двумя секциями — `Active Jobs` (все job-ы в work cache, отсортированные по времени создания, с колонками: status, tenant, worker, timestamps) и `Pending Jobs` (redaction job-ы в очереди).

**Ключевые метрики backend scheduler/worker:**

| Метрика | Описание |
| :--- | :--- |
| `tempo_backend_scheduler_jobs_created_total` | Созданные job-ы (с метками `tenant`, `job_type`) |
| `tempo_backend_scheduler_jobs_completed_total` | Успешно завершённые job-ы |
| `tempo_backend_scheduler_jobs_failed_total` | Неудачные job-ы |
| `tempo_backend_scheduler_jobs_active` | Job-ы, назначенные worker-у в данный момент |
| `tempo_backend_scheduler_jobs_pending` | Очередь job-ов, не назначенных на worker |
| `tempodb_compaction_outstanding_blocks` | Непроскомпащенные блоки на tenant — **основной сигнал для автоскейлинга** |
| `tempodb_blocklist_length` | Количество живых блоков на tenant; высокие значения — компоновка отстаёт |
| `tempo_backend_scheduler_redaction_traces_found_total` | Трейсы найдены при redaction; `mode=apply` — удалено, `mode=dry_run` — оценка blast radius |
| `tempo_backend_worker_redaction_block_missing_total` | Redaction job-ы с блоком, отсутствующим в blocklist — возмож пробел покрытия |

Все метрики job duration используют метку `job_type` со значениями `JOB_TYPE_COMPACTION`, `JOB_TYPE_RETENTION`, `JOB_TYPE_REDACTION`.

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

Parquet — единственный поддерживаемый формат блоков в 3.x (по умолчанию с 2.0; vParquet5 — по умолчанию с 3.1). Блок — директория `<tenant-id>/<block-id>/` в объектном хранилище:

| Файл | Назначение |
| :--- | :--- |
| `meta.json` | Метаданные блока: временной диапазон, тенант, block ID, поле `replaces` (атомарная замена). |
| `data.parquet` | Данные трейсов в колоночном формате. |
| Bloom filter | Вероятностная структура для быстрого поиска trace ID. |
| Index | Сопоставление trace ID → row groups. |
| `nocompact.flg` | Временный флаг, запрещающий компоновку во время флаша. |

| Версия | Статус в 3.1 | Особенности |
| :--- | :--- | :--- |
| vParquet3 | **Удалена** (deprecated в 2.10, enforced в 3.1) | Tempo не стартует при записи в vParquet3. Чтение существующих блоков — без изменений. |
| vParquet4 | **Опциональный (fallback)** | Колонки для array-атрибутов, событий и связей; 10 string dedicated-колонок на scope. |
| **vParquet5** | **По умолчанию (default) в 3.1+** | 20 string + 5 integer dedicated-колонок на scope, event-scoped колонки, blob-колонки (zstd для high-cardinality/high-length атрибутов), array-колонки. |

Смена версии формата (применяется ко всем компонентам, пишущим блоки — live-store и block-builder):

```yaml
storage:
  trace:
    block:
      version: vParquet5   # по умолчанию в 3.1+ (было vParquet4)
```

Старые блоки в других форматах остаются читаемыми; новые всегда пишутся в сконфигурированной версии.

**Dedicated columns** — продвижение часто запрашиваемых атрибутов из общей колонки `Attrs` в отдельные колонки Parquet для ускорения TraceQL-запросов. В vParquet5 поддерживаются:
- **`options: ["array"]`** — array-valued атрибуты (например, HTTP headers).
- **`options: ["blob"]`** — blob-колонки для high-cardinality/high-length атрибутов (UUID, stack traces, db.statement) с zstd-compression вместо dictionary encoding.
- **`int/<attribute>`** — integer dedicated columns (vParquet5 only), эффективны при prevalence ≥ 5% строк в scope.
- **Event-scoped columns** — атрибуты событий (exception.message, exception.stacktrace).

```yaml
storage:
  trace:
    block:
      version: vParquet5
      parquet_dedicated_columns:
        - name: http.method
          type: string
          scope: span
        - name: http.request.header.accept
          type: string
          scope: span
          options: ["array"]
        - name: span.http.status_code
          type: string
          scope: span       # для integer используйте int/span.http.status_code
        - name: db.statement
          type: string
          scope: span
          options: ["blob"]
        - name: exception.stacktrace
          type: string
          scope: event
          options: ["blob"]
        - name: deployment.environment
          type: string
          scope: resource
```

Для подбора колонок используйте `tempo-cli analyse block` (см. [Операции и команды](#операции-и-команды-tempo-cli)) или `tempo-cli suggest columns`.

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

**Предусловия:** данные в формате vParquet4+ (3.0 не читает vParquet3 и старше; в 3.1 vParquet3 deprecated — Tempo не стартует при записи в vParquet3); доступ к тому же объектному хранилищу; для микросервисного режима — работающая Kafka-совместимая очередь (монолиту Kafka не нужна); из SSB перейти на монолит или микросервисы.

1. **Миграция конфигурации** — `tempo-cli migrate config` читает конфиг 2.x и выдаёт валидный конфиг 3.x: удаляет блоки `ingester`, `ingester_client`, `compactor`, `metrics_generator_client` и конфиг `local_blocks`; в микросервисном режиме добавляет `ingest:`-блок; выставляет `compaction_disabled: true` в дефолтных overrides. Данные в хранилище утилита не изменяет:

   Монолит:
   ```bash
   tempo-cli migrate config --mode=monolithic old-config.yaml > new-config.yaml
   ```

   Микросервисы:
   ```bash
   tempo-cli migrate config --kafka-address=<BROKER> --kafka-topic=<TOPIC> old-config.yaml > new-config.yaml
   ```

2. **Legacy overrides** — плоский (unscoped) формат overrides отключён по умолчанию, иначе Tempo не стартует. Мигрируйте через `tempo-cli migrate overrides-config` либо временно включите `enable_legacy_overrides: true` (удалят в будущих релизах).

3. **Деплой 3.1 параллельно с 2.x** (микросервисы) — оба деплоймента указывают на одно объектное хранилище. Пока работают compactor-ы 2.x, одновременно может писать только одна система компоновки: держите `compaction_disabled: true` в дефолтном и каждом пер-тенантном overrides (они не наследуют свойства). Проверьте готовность: `tempo_live_store_ready == 1` (на свежем деплойменте без трафика live-store может «дозревать» до `live_store.readiness_max_wait`, по умолчанию 30 мин), `rate(tempo_block_builder_fetch_errors_total[5m])` около нуля; валидация через Tempo Vulture (`tempo_vulture_trace_error_total == 0`) или запрос по известному trace ID:

   ```bash
   curl http://<TEMPO_3_QUERY_FRONTEND>:3200/api/traces/<TRACE_ID>
   # → JSON трейса, если 3.1 читает исторические блоки из хранилища
   ```

4. **Переключение трафика** — постепенно переводите клиентов (OpenTelemetry Collectors, Grafana Alloy) на 3.1; контролируйте `tempo_distributor_kafka_write_bytes_total` и `tempo_ingest_group_partition_lag_seconds`.

5. **Вывод 2.x** — дождитесь флаша ingester-ов (`tempo_ingester_live_traces` и `tempo_ingester_flush_queue_length` → 0), масштабируйте compactor-ы 2.x в ноль, снимите `compaction_disabled` в 3.1, деинсталлируйте 2.x. Общее хранилище не удаляйте.

**Ограничения:** нет in-place downgrade с 3.0 на 2.x. До деинсталляции 2.x роллбэк возможен переключением трафика (routing change). Блоки, записанные block-builder-ом (RF1), читаемы 2.x при совместимом формате (vParquet4+). **TraceQL Metrics читают только RF1-блоки:** если в 2.x не использовался процессор `local-blocks`, метрики покроют только данные после миграции.

**Верификация после миграции:** `tempo_distributor_kafka_write_bytes_total` растёт, `tempo_block_builder_fetch_records_total` растёт при `tempo_block_builder_fetch_errors_total` = 0, `tempo_live_store_ready` = 1 при `tempo_live_store_records_dropped_total` = 0, исторические запросы возвращают данные, backend-worker-ы выполняют компоновку.

### Примеры конфигурации (v3.1)

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
       version: vParquet5   # по умолчанию в 3.1+

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
          image: grafana/tempo:3.1
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
6. Постепенно переключите трафик на 3.1.
7. После стабилизации снимите `compaction_disabled` и уберите 2.x.

### Безопасность (hardening checklist)

- [ ] **TLS everywhere:** включите TLS для всех внешних портов (3200, 4317, 4318, 9095) и внутреннего взаимодействия (mTLS между компонентами в микросервисном режиме).
- [ ] **Kafka SASL:** используйте SASL/SCRAM или mTLS для аутентификации в Kafka; ограничьте ACL на topic `tempo-traces`. В 3.1+ поддерживается `client_rack` для rack-aware fetching.
- [ ] **Redis cache (3.1+):** Redis Cluster — режим по умолчанию; Sentinel удалён. Для single-node Redis установите `single_node: true`. Переименованы ключи: `idle_timeout` → `conn_max_idle_time`, `max_connection_age` → `conn_max_lifetime`.
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

## Операции и команды (tempo-cli)

`tempo-cli` — утилита для администрирования, диагностики и upkeep Tempo. Работает с объектным хранилищем напрямую или через backend scheduler. Доступен как Docker-образ (`grafana/tempo-cli`) и как локальный бинарник (`make tempo-cli`).

```bash
# Docker (рекомендуется)
docker run --rm grafana/tempo-cli <command>

# Локально
go run ./cmd/tempo-cli <command>
# или после сборки:
./bin/$(go env GOOS)/tempo-cli-$(go env GOARCH) <command>
```

**Backend options** (применяются только к конкретной команде): `--config-file`/`-c` (рекомендуется), `--backend` (`s3`/`gcs`/`azure`/`local`), `--bucket`, `--s3-endpoint`, `--s3-user`/`--s3-pass`, `--insecure-skip-verify`.

#### Основные команды

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `tempo-cli migrate config` | Миграция конфигурации 2.x → 3.x | `tempo-cli migrate config --mode=monolithic old.yaml > new.yaml` |
| `tempo-cli migrate overrides-config` | Миграция legacy overrides на scoped format | `tempo-cli migrate overrides-config config.yaml -d out.yaml` |
| `tempo-cli migrate overrides-per-tenant` | Миграция per-tenant overrides | `tempo-cli migrate overrides-per-tenant overrides.yaml -d out.yaml` |
| `tempo-cli migrate tenant` | Копирование блоков между tenant/backend | `tempo-cli migrate tenant --source-config-file src.yaml --config-file dst.yaml t1 t2` |
| `tempo-cli redact` | GDPR-удаление по trace ID или TraceQL-запросу (3.1+) | `tempo-cli redact --tenant=t1 --query='{span.http.status_code=500}' --dry-run localhost:9095` |
| `tempo-cli rewrite-blocks drop-traces` | Прямое удаление по trace ID из хранилища | `tempo-cli rewrite-blocks drop-traces --drop-trace --backend=s3 --bucket=bkt t1 <TRACE_ID>` |
| `tempo-cli parquet convert-4to5` | Конвертация vParquet4 → vParquet5 | `tempo-cli parquet convert-4to5 ./block-in ./block-out "span.http.method" "int/span.http.status_code" "blob/span.db.statement"` |
| `tempo-cli parquet convert-3to4` | Конвертация vParquet3 → vParquet4 | `tempo-cli parquet convert-3to4 ./block-in ./out span.db.statement` |
| `tempo-cli list blocks` | Список блоков tenant | `tempo-cli list blocks -c tempo.yaml single-tenant` |
| `tempo-cli list compaction-summary` | Сводка по компоновке | `tempo-cli list compaction-summary -c tempo.yaml single-tenant` |
| `tempo-cli list cache-summary` | Сводка по кэшу (bloom filter) | `tempo-cli list cache-summary -c tempo.yaml single-tenant` |
| `tempo-cli list column` | Значения в колонке блока | `tempo-cli list column -c tempo.yaml single-tenant <BLOCK_ID> TraceID` |
| `tempo-cli view schema` | Схема блока Parquet + метаданные | `tempo-cli view schema -c tempo.yaml single-tenant <BLOCK_ID>` |
| `tempo-cli analyse block` | Анализ атрибутов для dedicated columns | `tempo-cli analyse block -c tempo.yaml single-tenant <BLOCK_ID>` |
| `tempo-cli analyse blocks` | Анализ всех блоков tenant | `tempo-cli analyse blocks -c tempo.yaml single-tenant` |
| `tempo-cli suggest columns` | Рекомендации по dedicated columns | `tempo-cli suggest columns -c tempo.yaml --format yaml --out suggestions.yaml single-tenant` |
| `tempo-cli query api trace-id` | Поиск трейса по ID через API | `tempo-cli query api trace-id http://tempo:3200 f1cfe82a8eef933b` |
| `tempo-cli query api search` | Поиск по TraceQL через API | `tempo-cli query api search localhost:3200 '{status = error}' now-1h now` |
| `tempo-cli query api search-tags` | Поиск имен атрибутов | `tempo-cli query api search-tags localhost:3200 now-1h now` |
| `tempo-cli query api search-tag-values` | Поиск значений атрибутов | `tempo-cli query api search-tag-values localhost:3200 resource.service.name now-1h now` |
| `tempo-cli query api metrics` | TraceQL Metrics через CLI | `tempo-cli query api metrics localhost:3200 '{} \| rate() by (resource.service.name)' now-1h now` |
| `tempo-cli query trace-id` | Просмотр трейса по ID из хранилища | `tempo-cli query trace-id f1cfe82a8eef933b single-tenant` |
| `tempo-cli query trace-summary` | Сводка трейса из хранилища | `tempo-cli query trace-summary f1cfe82a8eef933b single-tenant` |
| `tempo-cli query search` | Поиск по key/value в блоках | `tempo-cli query search http.method GET now-1h now single-tenant --backend=s3 --bucket=tempo-traces` |

#### Пример: миграция конфигурации 2.x → 3.x

```bash
# Монолитный режим (Kafka не нужен)
tempo-cli migrate config --mode=monolithic old-config.yaml > new-config.yaml

# Микросервисный режим
tempo-cli migrate config --kafka-address=<BROKER> --kafka-topic=<TOPIC> old-config.yaml > new-config.yaml

# Миграция overrides (если используются legacy flat overrides)
tempo-cli migrate overrides-config config.yaml -d migrated-overrides.yaml
```

**Важно:** перед миграцией убедитесь, что данные в формате vParquet4+ (3.0 не читает vParquet3 и старше; в 3.1 vParquet3 deprecated). После вывода 2.x снимите `compaction_disabled: true` из overrides.

#### Пример: redaction по TraceQL-запросу (3.1+)

```bash
# 1. Сначала dry-run для оценки blast radius
tempo-cli redact --tenant=my-tenant --query='{span.http.status_code=500}' --dry-run localhost:9095

# 2. Проверьте match count через метрику:
#    tempo_backend_scheduler_redaction_traces_found_total{mode="dry_run"}

# 3. Затем реальное удаление
tempo-cli redact --tenant=my-tenant --query='{span.http.status_code=500}' localhost:9095
```

Ограничения `--query`: один spanset filter с `=` на `resource.*` или `span.*`, соединённый `&&` или `||`. `--start`/`--end` scoping по времени для больших tenant-ов. `--trace-id` для конкретных трейсов (до 1000 за запрос).

#### Пример: конвертация блоков vParquet4 → vParquet5

```bash
tempo-cli parquet convert-4to5 ./block-in ./block-out "span.http.method" "int/span.http.status_code" "blob/span.db.statement"
```

Префиксы колонок: `int/` — integer dedicated column, `blob/` — blob-encoded колонка для high-cardinality атрибутов.

#### Пример: анализ блока для подбора dedicated columns

```bash
# Полный анализ с blob detection
tempo-cli analyse block --blob-threshold=4MiB --generate-jsonnet --backend=local --bucket=./data/ single-tenant <BLOCK_ID>

# Рекомендации по dedicated columns для tenant
tempo-cli suggest columns -c ./tempo.yaml --format yaml --out suggestions.yaml single-tenant
```

**Примечание:** `tempo-cli redact` делегирует работу backend scheduler через gRPC; `tempo-cli rewrite-blocks drop-traces` оперирует объектным хранилищем напрямую. Обе операции необратимы. Redaction snapshots блоклист при submission; трейсы, ещё не сброшенные в хранилище block-builder-ом, не покрываются — подождите ~10 мин после остановки приёма перед redaction.

## Восстановление после сбоев (Disaster Recovery)

Tempo не имеет встроенного бэкапа метаданных; объектное хранилище само по себе не является бэкапом при случайном удалении. Рекомендации:

1. **Versioning в S3:** включите versioning на бакете; это защищает от случайного `DELETE` или overwrite блоков. Kafka обеспечивает durability, но не защищает от human error.
2. **Replication бакета:** для production используйте кросс-региональную репликацию (если поддерживается хранилищем) или периодический экспорт списка объектов.
3. **Метаданные:** backend scheduler хранит состояние job-ов в метаданных. При полной потере мета-store бэкап можно восстановить из `meta.json` блоков (они содержат временные диапазоны, tenant, replaces).
4. **Роллбэк 3.0 → 2.x:** in-place downgrade невозможен. До деинсталляции 2.x роллбэк возможен переключением трафика на 2.x (routing change). Блоки RF1 читаемы 2.x при совместимом формате (vParquet4+).

## Runbook: TempoKafkaWriteErrors

**Симптомы:** `rate(tempo_distributor_kafka_write_errors_total[5m]) > 0` более 5 минут.

**Диагностика (0–5 минут):**
1. Проверьте доступность Kafka брокеров: `kubectl exec -n kafka <broker-pod> -- kafka-topics.sh --bootstrap-server localhost:9092 --describe`
2. Проверьте лаг партиций: `tempo_ingest_group_partition_lag_seconds`
3. Проверьте логи Distributor: `kubectl logs -n tempo -l app=tempo-distributor --tail=100 | grep -i kafka`

**Решение:**
- Если брокер недоступен: проверьте NetworkPolicy, DNS, состояние брокера.
- Если переполнение: увеличьте partitions Kafka, проверьте disk usage брокера.
- Если ACL/SASL ошибка: проверьте конфигурацию SASL в Tempo и Kafka.

## Runbook: TempoLiveStoreLagging

**Симптомы:** `tempo_live_store_lagged_requests_total > 0` более 2 минут.

**Диагностика:**
1. Проверьте задержку Kafka: `tempo_ingest_group_partition_lag_seconds`
2. Проверьте ресурсы live-store: `kubectl top pods -n tempo -l app=tempo-live-store`
3. Проверьте IOPS объектного хранилища (если live-store флашит блоки).

**Решение:**
- Масштабируйте live-store: количество реплик = числу партиций Kafka.
- Увеличьте `target_bytes_per_job` в `query_frontend.metrics`.
- Проверьте сеть между Kafka и live-store.

## Бенчмаркинг производительности

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

## Диагностика и устранение неполадок

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

## Операционный чек-лист (daily/weekly/monthly)

#### Ежедневно
- [ ] Проверьте алерты Tempo (KafkaWriteErrors, LiveStoreLagging, BlockBuilderErrors).
- [ ] Проверьте лаг партиций Kafka (`tempo_ingest_group_partition_lag_seconds`) — должен быть < 60s.
- [ ] Проверьте готовность live-store (`tempo_live_store_ready == 1`).
  - [ ] Проверьте, что backend worker-ы выполняют компоновку (`tempo_backend_scheduler_jobs_completed_total` растёт).

#### Еженедельно
- [ ] Проверьте использование объектного хранилища (ёммость, количество блоков).
- [ ] Проверьте retention policy: убедитесь, что старые блоки удаляются по расписанию.
- [ ] Проверьте логи на наличие `tempo_block_builder_fetch_errors_total` > 0.
- [ ] Проверьте ресурсы pods (CPU/Memory) — нет ли pods в OOMKilled.

#### Ежемесячно
- [ ] Обновите Tempo до последней стабильной версии (проверьте release notes на breaking changes).
- [ ] Проверьте версию формата блоков (vParquet5 по умолчанию в 3.1+; при необходимости оставайтесь на vParquet4 через `storage.trace.block.version`).
- [ ] Проверьте конфигурацию dedicated columns — актуальны ли они для текущих TraceQL-запросов.
- [ ] Проверьте backup метаданных и S3 versioning (если включено).

## Рекомендации по эксплуатации

- **S3 Durability:** благодаря Kafka запись использует RF1; versioning в объектном хранилище можно отключить, если не требуется внешними политиками.
- **Компоновка (job-based):** в 3.0 компоновку и retention выполняют backend scheduler + backend worker с централизованным отслеживанием прогресса и авторетраем упавших задач. CLI-флаги компоновки утратили дублирующий префикс: `compaction.compaction.block-retention` → `compaction.block-retention`, аналогично `compaction.max-block-bytes` и `compaction.max-objects-per-block`.
- **Параллельная операция с 2.x:** одновременно активна только одна система компоновки — держите `compaction_disabled: true` в 3.1, пока живы compactor-ы 2.x; после вывода 2.x override снимается.
- **Семантические конвенции:** строго следуйте OpenTelemetry Semantic Conventions для атрибутов (`http.method`, `db.system`, `exception.type`); это обеспечивает корректную работу TraceQL и корреляцию с другими сигналами.
- **Versioning схем:** используйте versioning для атрибутов (например, `http.request.version: 2`) при внесении breaking changes, чтобы не ломать существующие TraceQL-запросы.

## SRE-процедуры

#### Сервисные рестарты и rolling update

**Graceful shutdown:**

```bash
# Distributor — safe to restart один за другим (Kafka consumer group rebalance)
kubectl rollout restart deployment/tempo-distributor -n tempo

# Query Frontend — обновляйте с maxSurge=0 для избежания потери queued requests
kubectl patch deployment tempo-query-frontend -n tempo -p '{"spec":{"strategy":{"type":"RollingUpdate","rollingUpdate":{"maxSurge":0}}}}}'

# Live-store / Block-builder — требуется синхронизация с числом партиций Kafka
# Один экземпляр читает одну партицию; при rolling update соблюдайте maxUnavailable=0
kubectl patch deployment tempo-live-store -n tempo -p '{"spec":{"strategy":{"rollingUpdate":{"maxUnavailable":0}}}}}'
```

**Health check verification:**

```bash
# Проверить готовность всех компонентов
for comp in distributor query-frontend querier live-store block-builder backend-scheduler backend-worker; do
  kubectl exec -n tempo deploy/tempo-$comp -- curl -sf http://localhost:3200/ready || echo "$comp NOT ready"
done

# Проверить метрики live-store (дозревание без трафика — до 30 мин)
kubectl exec -n tempo deploy/tempo-query-frontend -- curl -s http://localhost:3200/metrics | grep tempo_live_store_ready

# Проверить отсутствие ошибок block-builder
kubectl exec -n tempo deploy/tempo-query-frontend -- curl -s http://localhost:3200/metrics | grep tempo_block_builder_fetch_errors_total
```

#### Ротация TLS-сертификатов

1. **Обновление сертификатов** (cert-manager, Vault или manual):

```bash
# Пример с cert-manager для Tempo API (порт 3200) и OTLP (порты 4317, 4318)
kubectl patch certificate tempo-tls -n tempo --type=json -p='[{"op":"replace","path":"/spec/dnsNames","value":["tempo.tempo.svc.cluster.local","tempo.tempo.svc","tempo:3200","tempo:4317","tempo:4318"]}]'
```

2. **Проверка цепочки сертификатов:**

```bash
# Проверить сертификат
kubectl exec -n tempo deploy/tempo-distributor -- openssl s_client -connect localhost:3200 -servername tempo.tempo.svc

# Проверить срок действия
kubectl exec -n tempo deploy/tempo-distributor -- openssl x509 -in /etc/tempo/tls/tls.crt -noout -dates
```

3. **Ротация Kafka TLS/SASL credentials:**

```bash
# Обновить Secret с SASL-креденшелами
kubectl create secret generic tempo-kafka-secret -n tempo \
  --from-literal=username=<NEW_USER> \
  --from-literal=password=<NEW_PASS> \
  --dry-run=client -o yaml | kubectl apply -f -

# Перезапустить компоненты, использующие Kafka (distributor, live-store, block-builder)
kubectl rollout restart deployment/tempo-distributor deployment/tempo-live-store deployment/tempo-block-builder -n tempo
```

#### Управление логами и ротация

Tempo пишет логи в stdout/stderr (best practice для K8s). Для production:

```yaml
# Loki Promtail/Fluent-bit config для сбора логов Tempo
- job_name: tempo-logs
  static_configs:
  - targets:
      - localhost:3200  # health check endpoint
  loki:
    labels:
      job: tempo
      component: distributor
  pipeline_stages:
  - json:
      expressions:
        level: level
        msg: msg
  - labels:
      level:
  - output:
      source: msg
```

**Log retention:** настраивается на стороне Loki (например, `retention_period: 90d` в конфиге Loki).

**Важные паттерны в логах для алёртинга:**
- `level=error msg=".*kafka.*"` — проблемы с Kafka
- `level=error msg=".*backend scheduler.*"` — проблемы с компоновкой
- `level=warn msg=".*backpressure.*"` — backpressure сигналы

#### Процедура backup verification

**Ежемесячная проверка восстановления:**

1. Создать тестовый tenant с небольшим объёмом данных
2. Записать тестовый трейс с известным trace ID
3. Подождать.flush блока (10 мин)
4. Проверить читаемость через `tempo-cli query trace-id`
5. Удалить тестовый tenant

```bash
# 1. Записать тестовый трейс (через otel-cli или приложение)
# 2. Дождаться flush
sleep 600

# 3. Проверить читаемость
tempo-cli query api trace-id http://tempo-query-frontend:3200 <TEST_TRACE_ID>
# → JSON трейса, если запись удалась

# 4. Проверить backup объектного хранилища
#    (object versioning или репликация — зависит от используемого бэкенда)
tempo-cli list blocks -c ./tempo.yaml single-tenant | wc -l
#    → количество доступных блоков должно совпадать с list до теста
```

#### Управление данными и lifecycle

**Data lifecycle workflow:**

```bash
# Просмотр текущих блоков и их возраста
tempo-cli list blocks -c ./tempo.yaml single-tenant | sort -k9 -rn | head -20
# Колонки: ID, Lvl, Objects, Size, Vers, Window, Start, End, Duration, Age

# Проверка compaction summary
tempo-cli list compaction-summary -c ./tempo.yaml single-tenant

# Проверка bloom filter cache
tempo-cli list cache-summary -c ./tempo.yaml single-tenant
```

**Контроль размера блоков:**
- block_duration по умолчанию ~2h → ~10МБ/блок. При высокой кардинальности атрибутов блоки могут стать слишком большими.
- Настраивайте `block_builder.block_duration` для контроля размера блоков (цель: 10–100MB на блок).

#### Emergency procedures

**Tenant-level compaction pause (для инцидента):**

```yaml
# В per-tenant overrides
overrides:
  "<tenant-id>":
    compaction:
      compaction_disabled: true
```

**Force retention cleanup (manual, при срочном удалении старых блоков):**

```bash
# Найти блоки старше retention window
tempo-cli list blocks -c ./tempo.yaml single-tenant | grep -v compacted
# Затем использовать backend scheduler: tempo-cli redact --query для удаления по TraceQL
```

## Мониторинг и алертинг

### Ключевые метрики Tempo

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `tempo_distributor_kafka_write_errors_total` | Ошибки записи в Kafka | > 0 за 5 минут |
| `tempo_distributor_kafka_write_bytes_total` | Объём записанных данных | резкое падение > 50% |
| `tempo_distributor_kafka_write_latency_seconds` | Задержка записи в Kafka | p99 > 1 секунда |
| `tempo_distributor_kafka_records_per_message` | Количество спанов на сообщение | аномально высокое — проверка batching |
| `tempo_ingest_group_partition_lag_seconds` | Лаг партиций Kafka | > 60 секунд |
| `tempo_block_builder_fetch_errors_total` | Ошибки чтения Kafka в block-builder | > 0 |
| `tempo_block_builder_spans_deduped_total` | Дедупликованные спаны | резкий рост = дубли в источнике |
| `tempo_block_builder_spans_written_total` | Спаны, записанные в блоки | падение = проблема с block-builder |
| `tempo_live_store_ready` | Готовность live-store | < 1 при наличии трафика |
| `tempo_live_store_records_dropped_total` | Отброшенные записи в live-store | > 0 |
| `tempo_live_store_lagged_requests_total` | Отставание live-store | рост тренда |
| `tempo_backend_scheduler_jobs_created_total` | Созданные job-ы (compaction/retention/redaction) | с метками `tenant`, `job_type` |
| `tempo_backend_scheduler_jobs_completed_total` | Завершённые job-ы | отсутствие роста > 1 час |
| `tempo_backend_scheduler_jobs_failed_total` | Неудачные job-ы | > 0 |
| `tempo_backend_scheduler_jobs_pending` | Очередь job-ов | рост = недостаёт worker capacity |
| `tempodb_compaction_outstanding_blocks` | Блоки, ожидающие компоновки | рост = компоновка отстаёт |
| `tempodb_blocklist_length` | Живые блоки на tenant | рост = compaction falling behind |
| `tempo_backend_scheduler_redaction_traces_found_total` | Трейсы найдены при redaction | контроль `mode=dry_run` vs `mode=apply` |
| `tempo_backend_worker_redaction_block_missing_total` | Redaction job с блоком не из blocklist | возмож пробел покрытия |
| `tempo_vulture_trace_error_total` | Ошибки валидации Tempo Vulture | > 0 |

### Alertmanager правила

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

  - alert: TempoBackendJobsStalled
    expr: tempo_backend_scheduler_jobs_pending > 10
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Backend scheduler имеет незавершённые job-ы"
```

### Grafana дашборды (3.1+)

Tempo mixin (`operations/tempo-mixin/`) включает предбилтденные дашборды:
- **Tempo - Overview** — общие метрики приёма и запросов
- **Tempo - Backend Work** — статус job-ов, compaction/retention/redaction, CPU/memory backend scheduler/worker, autoscaling panel
- **Tempo - LiveStore** (новый в 3.1) — latency чтения, ingest lag, backpressure, KEDA autoscaling

Для индексации метрик используйте Grafana Agent или OTel Collector с Prometheus scraper.

## Дополнительная информация

Навигация: [Главная Tempo](./index.md) — обзор, определения, TraceQL, сравнение с Jaeger.

### См. также

- [Grafana Tempo — распределённая трассировка](./index.md) — обзор, ключевые особенности, TraceQL, сравнение с Jaeger.
- [Tempo architecture reference](https://grafana.com/docs/tempo/latest/reference-tempo-architecture/)
- [Tempo components](https://grafana.com/docs/tempo/latest/reference-tempo-architecture/components/) — distributor, block-builder, live-store, querier, backend scheduler/worker.
- [Compactation operations](https://grafana.com/docs/tempo/latest/operations/compaction/) — timing requirements and block selection.
- [Tempo CLI documentation](https://grafana.com/docs/tempo/latest/operations/tempo_cli/)
- [TraceQL Documentation](https://grafana.com/docs/tempo/latest/traceql/)
- [Миграция на Tempo 3.0](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/migrate-to-3/)
- [Upgrade to Tempo 3.1](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/upgrade/) — изменения конфигурации Redis, memcached defaults, vParquet5 по умолчанию
- [Dedicated attribute columns](https://grafana.com/docs/tempo/latest/operations/dedicated_columns/)