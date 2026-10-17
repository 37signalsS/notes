# Руководство: Высоконагруженный конвейер логов (Fluent Bit, Kafka, Vector, OpenSearch)

**Актуально для:** Fluent Bit 5.1.x / Kafka 4.x / Vector 0.58.x / OpenSearch 3.8.x

> Авторитетный источник по построению масштабируемых систем сбора логов в архитектуре "Edge → Transport → Aggregator → Storage". Описывает интеграцию современных компонентов (Fluent Bit 5.1.x, Kafka 4.x, Vector 0.58.x, OpenSearch 3.8) с упором на протокол OpenTelemetry (OTel).

## Определения

* **Конвейер логов (Logging Pipeline)** — последовательность этапов обработки данных. Типовой стек 2026 года: `Edge Agent (Fluent Bit) → Buffer (Kafka) → Heavy Transformer (Vector) → Search Platform (OpenSearch)`.
* **OTLP (OpenTelemetry Protocol)** — открытый стандарт передачи телеметрии (логов, метрик, трассировок), ставший основным протоколом взаимодействия в современных конвейерах.
* **VRL (Vector Remap Language)** — выражение-ориентированный, типобезопасный язык трансформации данных в Vector; VRL-программы компилируются в нативный код Rust при старте Vector, обеспечивая производительность уровня Rust и безопасность типов. Подробнее: **[Язык VRL](../../Vector/vrl_language.md)**.
* **Противодавление (Backpressure)** — состояние, при котором приемник не успевает обрабатывать данные. В данном конвейере Kafka выступает основным буфером, изолирующим Edge-агентов от проблем хранилища.
* **Dead Letter Queue (DLQ)** — механизм перенаправления событий, которые не удалось распарсить или доставить, во вторичное хранилище (например, S3) для последующего анализа.
* **KRaft** — встроенный протокол консенсуса Kafka на базе Raft, заменивший ZooKeeper. Начиная с Kafka 4.0 (март 2025) KRaft — единственный режим работы: поддержка ZooKeeper полностью удалена.
* **Data Stream (OpenSearch)** — управляемая коллекция индексов только на запись (`write index` + backing indices) с единой точкой именования (в этом конвейере — `logs-k8s-default`); автоматически выполняет rollover, избавляя от ручного управления алиасами.
* **ISM (Index State Management)** — плагин OpenSearch для автоматизации жизненного цикла индексов: rollover по размеру/возрасту, миграция между узлами hot/warm, удаление по истечении retention.

## Основные концепции

### Архитектура и поток данных

В высоконагруженных системах (High Load) прямая отправка логов в OpenSearch недопустима из-за риска потери данных при всплесках трафика (bursts).

1.  **Edge Layer (Сбор)**: Fluent Bit 5.1.x работает как легкий edge-агент с поддержкой OTLP, минимизируя нагрузку на CPU/RAM узла.
2.  **Transport Layer (Буфер)**: Kafka обеспечивает персистентность. Даже при полной остановке OpenSearch на 24 часа, логи сохраняются в топиках.
3.  **Aggregation Layer (Трансформация)**: Vector вычитывает данные, нормализует их к единому стандарту (ECS/OTel) и выполняет тяжелые вычисления (GeoIP, декодирование стектрейсов).
4.  **Storage Layer (Аналитика)**: OpenSearch 3.8 (ядро Lucene 10.5) индексирует данные; поддерживает gRPC-транспорт (Bulk и k-NN GA с 3.2, остальные gRPC API экспериментальны), HTTP/3 на клиенте (3.8) и потоковую передачу между кластерами через Arrow Flight (3.8).

### Роли и характеристики компонентов

| Компонент | Язык / Технология | Роль в 2026 году | Ключевая фича |
| :--- | :--- | :--- | :--- |
| **Fluent Bit** | C | Легкий Edge-агент | SQL Processor на стороне Edge |
| **Kafka** | Java / Scala | Durability Buffer | Zstd сжатие, KRaft-only (4.0+), KIP-848 (GA в 4.0); KIP-1274: фаза 1 в 4.3 (предупреждения при classic), удаление classic в 6.0 |
| **Vector** | Rust | ETL Агрегатор | VRL (безопасные трансформации) |
| **OpenSearch** | Java (Lucene 10.5) | Search Platform | gRPC-транспорт (Bulk/k-NN GA с 3.2), Data Prepper (OTel), PPL; PromQL — через Prometheus data source (3.7+) |

### Принципы отказоустойчивости конвейера

Надежность сквозной доставки определяется настройками каждого звена:

*   **Producer (Fluent Bit)**: параметр `rdkafka.acks=all` гарантирует запись во все синхронизированные реплики. Значение `acks=1` быстрее, но допускает потерю события при падении лидера партиции сразу после записи.
*   **Брокеры (Kafka)**: для продакшн-топиков обязательны `replication.factor >= 3` и `min.insync.replicas = 2` — кластер переживает отказ одного брокера без остановки записи (при `acks=all`).
*   **Consumer (Vector)**: коммит offset-ов после успешной отправки в OpenSearch дает семантику **at-least-once** (дубли возможны при сбое между записью и коммитом; дедупликация — задача хранилища или `trace_id`+`span_id`). Семантика exactly-once для логов обычно избыточна.
*   **Дисковая буферизация в Vector**: связка Kafka → Vector → OpenSearch дополняется локальным disk-буфером Vector'а (`buffer.type = "disk"`, `when_full = "block"`) — переживает рестарт пода без потери вычитанных, но неотправленных событий.

## Практические сценарии

### Требования к окружению

Сценарии предполагают: развернутые брокеры Kafka 4.x (KRaft, доступность `kafka-prod:9092` из сети агентов), инстанс OpenSearch 3.x с Security Plugin, Linux-хосты для Edge-агентов с правами чтения `/var/log/containers/`, Docker или пакетные репозитории для установки Fluent Bit 5.1+ и Vector 0.58+. Переменные `OS_USER`/`OS_PASS` — учетные данные пользователя OpenSearch с правами записи в data streams.

### 1. Настройка Fluent Bit 5.x (Edge)

В современных версиях рекомендуется использовать формат YAML для конфигурации.

```yaml
service:
  flush: 1
  http_server: on          # Экспорт внутренних метрик (порт 2020)
  http_port: 2020
  storage.path: /var/log/flb-storage/
  storage.type: filesystem # Защита от OOM при переполнении буфера
  storage.metrics: on      # Метрики storage layer на эндпоинте /api/v1/storage

pipeline:
  inputs:
    - name: tail
      tag: kube.*                    # Явный тег: по нему работают kubernetes filter и rewrite_tag
      path: /var/log/containers/*.log
      multiline.parser: docker, cri  # Склейка многострочных стектрейсов (docker, cri)
      parser: json                   # JSON-логи приложений: поля (level, message) доступны сразу
      storage.type: filesystem

  filters:
    - name: kubernetes
      match: kube.*
    - name: rewrite_tag
      match: kube.*                  # Не "*": порождаемый тег должен НЕ совпадать с match,
                                     # иначе Fluent Bit детектирует цикл эмиттера и отклоняет эмиссию
      rule: $level ^(error|critical)$ logs.priority false
                                     # keep=false: запись пере-эмитируется с новым тегом без дублирата
      emitter_name: priority_reemitter # Именованный эмиттер повторно тегированных событий
      emitter_storage.type: filesystem # Буфер эмиттера на диске при противодавлении

  outputs:
    - name: kafka
      match: "*"
      brokers: kafka-prod:9092
      topics: logs-k8s-raw         # Опция называется topics (plural)
      rdkafka.compression.codec: zstd
      rdkafka.acks: all            # Гарантия записи во все ISR-реплики
      rdkafka.linger.ms: 5         # Микро-батчинг перед отправкой
      workers: 4                     # Параллельные потоки отправки (по умолчанию 1)
    - name: kafka                    # Алертинг: только события уровня error/critical
      match: "logs.priority"
      brokers: kafka-prod:9092
      topics: logs-k8s-errors
      rdkafka.compression.codec: zstd
      rdkafka.acks: all
```

Пояснения к ключевым параметрам:

*   `storage.type: filesystem` на уровне input — чанки событий пишутся на диск до подтверждения доставки; при недоступности Kafka агент не теряет данные и не растет в памяти.
*   `parser: json` — встроенный парсер (проверить список: `fluent-bit -L`): JSON-строки приложений раскладываются в поля (`level`, `message`) ещё на Edge, что даёт маршрутизацию по `$level` в `rewrite_tag` и снимает парсинг с агрегатора. Невалидный JSON (plain-text логи, стектрейсы) остаётся в поле `log` — Vector нормализует его в `message`.
*   `multiline.parser: docker, cri` — склейка многострочных стектрейсов для обоих рантаймов контейнеров; склейка выполняется до парсинга, поэтому стектрейс попадает в JSON-парсер целиком.
*   `rewrite_tag` — события уровня error/critical пере-эмитируются с тегом `logs.priority` (`keep=false` — оригинальная запись не дублируется). Второй output (`match: "logs.priority"`) отправляет их в отдельный топик для алертинга; основной output (`match: "*"`) получает все события, включая пере-эмитированные. Важно: `match` фильтра не должен совпадать с порождаемым тегом — иначе срабатывает защита от цикла эмиттера (ошибка `emitter cycle detected`, эмиссия отклоняется).
*   Проверка конфигурации без запуска pipeline:

```bash
fluent-bit --config /etc/fluent-bit/fluent-bit.yaml --dry-run
# → Fluent Bit v5.1.x
# → * configuration test is successful (код возврата 0)
```

Начиная с Fluent Bit 4.2 `--dry-run` выполняет полную валидацию свойств плагинов: неизвестные или опечатанные ключи (например, `topic` вместо `topics`) отлавливаются на этапе проверки, а не в рантайме.

### 2. Конфигурация Kafka (Буфер)

Для Production-сред топики логов должны иметь:
*   **Partitions**: Равно или кратно количеству инстансов Vector (например, 12 партиций на 3 инстанса Vector).
*   **Retention**: Минимум 24 часа (`retention.ms=86400000`).
*   **Compression**: `compression.type=zstd` для максимальной экономии места.

Начиная с Kafka 4.x создание топика не требует подключения к ZooKeeper — все операции идут через broker API (KRaft). Текущая версия Kafka — 4.3 (июнь 2026). Эволюция протокола групп (KIP-1274): в 4.3 — фаза 1, при использовании classic-протокола логируется предупреждение (дефолт пока `classic`); в 5.0 дефолт сменится на `consumer` и classic будет deprecated; удаление classic — в 6.0. Для новых consumer-групп рекомендуется сразу протокол KIP-848 (`group.protocol=consumer`). Создание топика со всеми продакшн-настройками:

```bash
kafka-topics.sh --bootstrap-server kafka-prod:9092 --create \
  --topic logs-k8s-raw \
  --partitions 12 \
  --replication-factor 3 \
  --config min.insync.replicas=2 \
  --config retention.ms=86400000 \
  --config compression.type=zstd \
  --config cleanup.policy=delete
# → Created topic logs-k8s-raw.
```

Проверка конфигурации топика:

```bash
kafka-topics.sh --bootstrap-server kafka-prod:9092 --describe --topic logs-k8s-raw
# → Topic: logs-k8s-raw  PartitionCount: 12  ReplicationFactor: 3  Configs: compression.type=zstd,min.insync.replicas=2,cleanup.policy=delete
# →   Topic: logs-k8s-raw  Partition: 0  Leader: 1  Replicas: 1,2,3  Isr: 1,2,3
```

Каждая партиция должна показывать полный список ISR (`Isr: 1,2,3`); неполный ISR сигнализирует об отстающем брокере и риске для `acks=all`.

### 3. Настройка Vector (Агрегатор и Трансформатор)

Vector преобразует сырой JSON из Kafka в структурированный OTel-формат.

```toml
[sources.kafka_in]
type = "kafka"
bootstrap_servers = "kafka-prod:9092"
group_id = "vector-aggregator"
topics = ["logs-k8s-raw"]
session_timeout_ms = 30000       # Обнаружение падения консьюмера (default 10000); drain_timeout_ms по умолчанию = половина

[transforms.vrl_processing]
type = "remap"
inputs = ["kafka_in"]
drop_on_error = true             # Не блокировать пайплайн при ошибке трансформации
reroute_dropped = true           # Упавшие события уходят в выход ".dropped" (см. DLQ ниже)
source = """
# Парсинг события: Fluent Bit отправляет запись как JSON-строку,
# которая попадает в .message (decoding по умолчанию — bytes)
.parsed, err = parse_json(.message)
if err != null {
    log("Failed to parse JSON: " + err, level: "error")
    .status = "error_parsing"
} else {
    . = .parsed                  # Замена корня: метаданные kafka source
                                 # (offset, partition, topic) отбрасываются автоматически
    # Plain-text логи: Edge не распарсил строку, она осталась в поле log —
    # приводим к единому полю message
    if exists(.log) && !exists(.message) {
        .message = .log
        del(.log)
    }
    # Нормализация метаданных (OTel-style)
    if exists(.kubernetes) {
        .service.name = .kubernetes.container_name
    }
    .host = { "hostname": .host } # tail input добавляет host строкой
}
"""

[sinks.opensearch_out]
type = "elasticsearch"           # Отдельного opensearch sink в Vector нет:
                                 # elasticsearch sink полностью совместим с OpenSearch
opensearch_service_type = "managed"  # self-managed OpenSearch (значение по умолчанию)
inputs = ["vrl_processing"]
endpoints = ["https://opensearch:9200"]  # endpoint (singular) deprecated
mode = "data_stream"             # Запись в Data Streams через bulk create action;
                                 # при наличии поля timestamp Vector переименовывает его в @timestamp
data_stream.type = "logs"        # Имя стрима формируется как <type>-<dataset>-<namespace>:
data_stream.dataset = "k8s"      # logs-k8s-default (шаблон индекса logs-k8s* совпадает)
data_stream.namespace = "default"
auth.strategy = "basic"
auth.user = "${OS_USER}"
auth.password = "${OS_PASS}"
tls.verify_certificate = true
tls.ca_file = "/etc/vector/certs/root-ca.pem"
batch.max_bytes = 10485760       # Батчи до 10 MB
batch.timeout_secs = 1           # Не держать события дольше 1с ради латентности
request.concurrency = "adaptive" # Адаптивное число параллельных запросов (учитывает 429)

[sinks.opensearch_out.buffer]
type = "disk"                    # Локальный disk-буфер: переживает рестарт агента
when_full = "block"              # при переполнении блокирует источник (backpressure)
max_size = 268435488             # ~256 MB (минимум для disk-буфера); нужен writable data_dir
```

Проверка конфигурации и наблюдение за потоком:

```bash
vector validate --config /etc/vector/vector.toml
# → код возврата 0, предупреждений о неизвестных опциях нет

vector tap vrl_processing       # Просмотр событий после трансформации "на лету"
# → {"service.name":"payments-api","message":"order created","host":{"hostname":"node-1"},...}
```

> Важно (Vector 0.57+): интерполяция переменных окружения `${VAR}` отключена по умолчанию. Для конфигурации выше запускайте агент с флагом `--dangerously-allow-env-var-interpolation` (или переменной `VECTOR_DANGEROUSLY_ALLOW_ENV_VAR_INTERPOLATION=true`), либо — рекомендуемый способ для секретов — используйте secret-провайдеры. Подробнее: [Vector Overview](../../Vector/vector_overview.md), раздел «Интерполяция переменных окружения (v0.57+)».

Локальная проверка трансформаций перед деплоем выполняется unit-тестами в секции `[[tests]]` (примеры: [Vector: Практические сценарии](../../Vector/practical_scenarios.md)).

#### Dead Letter Queue: маршрутизация необработанных событий

Связка `drop_on_error` + `reroute_dropped` направляет события, не прошедшие VRL-трансформацию, в именованный выход `<transform>.dropped`. Отправляем их в S3 для последующего разбора:

```toml
[sinks.dlq_s3]
type = "aws_s3"
inputs = ["vrl_processing.dropped"]  # Только отклоненные события
bucket = "company-logs-dlq"
key_prefix = "parse-errors/%Y/%m/%d/"
compression = "gzip"

[sinks.dlq_s3.batch]
max_bytes = 10000000

[sinks.dlq_s3.retry]
max_duration_secs = 3600
```

Это реализует определенный выше паттерн DLQ: ни одно событие не исчезает молча — ошибки парсинга накапливаются в бакете с префиксом даты, а метрика `component_errors_total` трансформации служит триггером для алерта. Для on-prem стендов вместо AWS S3 подойдёт любое S3-совместимое хранилище (например, MinIO) — укажите его через `aws.endpoint`.

> **См. также:** подробнее о TLS/mTLS, аутентификации, управлении секретами и systemd hardening — **[Vector Security](../../Vector/vector_security.md)**; о retry policy, circuit breaker, DLQ-паттернах и acknowledgements — **[Vector Reliability](../../Vector/vector_reliability.md)**.

### 4. Настройка OpenSearch (Storage)

Подготовка принимающей стороны: шаблон данных, политика жизненного цикла, проверка записи.

Шаблон индекса для Data Stream (создается один раз через Dashboards Dev Tools или API):

```json
PUT _index_template/logs-k8s
{
  "index_patterns": ["logs-k8s*"],
  "data_stream": {},
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1,
      "refresh_interval": "5s"
    },
    "mappings": {
      "properties": {
        "@timestamp":     { "type": "date" },
        "message":        { "type": "text" },
        "service.name":   { "type": "keyword" },
        "host.hostname":  { "type": "keyword" },
        "status":         { "type": "keyword" },
        "trace_id":       { "type": "keyword" },
        "kubernetes.pod_name": { "type": "keyword" },
        "kubernetes.namespace": { "type": "keyword" }
      }
    }
  }
}
# → {"acknowledged": true}
```

Политика ISM: rollover при достижении 50 ГБ или 30 дней, удаление индексов через 90 дней:

```json
PUT _plugins/_ism/policies/logs-retention
{
  "policy": {
    "description": "Rollover и очистка лог-индексов",
    "default_state": "hot",
    "states": [
      {
        "name": "hot",
        "actions": [
          { "rollover": { "min_size": "50gb", "min_index_age": "30d" } }
        ],
        "transitions": [
          { "state_name": "delete", "conditions": { "min_index_age": "90d" } }
        ]
      },
      { "name": "delete", "actions": [ { "delete": {} } ] }
    ],
    "ism_template": {
      "index_patterns": [".ds-logs-k8s-default*", "logs-k8s-default*"],
      "priority": 100
    }
  }
}
# → {"_id": "logs-retention", ...}
```

Ключевой момент: без блока `ism_template` (или ручной привязки через `POST /_plugins/_ism/add/<index>`) политика **не применяется** к backing-индексам потока — ротация и удаление не сработают. Шаблон действует только на индексы, созданные после привязки политики. Детали и альтернативные сценарии (warm/cold-фазы, force_merge, уведомления): [OpenSearch: Управление жизненным циклом индексов (ISM)](../OpenSearch/opensearch_ism_lifecycle.md).

Проверка привязки политики к индексу потока:

```bash
GET _plugins/_ism/explain/.ds-logs-k8s-default-000001?pretty
# → "policy_id":"logs-retention", "enabled":true, "state":{"name":"hot"}
```

Замечания по безопасности:

*   Начиная с OpenSearch 2.12 контейнер требует переменную `OPENSEARCH_INITIAL_ADMIN_PASSWORD` (минимум 8 символов: заглавная и строчная буквы, цифра и спецсимвол) — стандартный пароль `admin` больше не допустим.
*   Демо-сертификаты (`demo certs`) подходят только для теста; в production замените их собственным PKI и включите TLS на транспортном и HTTP-слоях.

### 5. Сквозная проверка конвейера

После запуска всех компонентов выполните проверку каждого стыка:

1.  **Сырые данные доходят до Kafka** (вычитать пару сообщений без коммита):
    ```bash
    kafka-console-consumer.sh --bootstrap-server kafka-prod:9092 \
      --topic logs-k8s-raw --max-messages 1 --timeout-ms 5000
    # → {"date":1755937200,"level":"info","message":"GET /healthz 200","kubernetes":{"pod_name":"api-7d9f"},"host":"node-1"}
    ```
2.  **Vector обрабатывает и отправляет батчи** (топология в реальном времени и ошибки):
    ```bash
    vector top
    # → Компонент vrl_processing: колонка Events Out растёт;
    # → opensearch_out: Events In ≈ Events Out

    journalctl -u vector -n 50 --no-pager -p err
    # → пустой вывод при штатной работе (ошибки отправки и трансформации — здесь)
    ```
3.  **Данные проиндексированы в OpenSearch**:
    ```bash
    curl -ku admin:$OS_PASS "https://localhost:9200/_data_stream/logs-k8s-default?pretty"
    # → {
    # →   "data_streams": [{
    # →     "name": "logs-k8s-default",
    # →     "indices": [{ "index_name": ".ds-logs-k8s-default-000001" }],
    # →     "generation": 1, "status": "GREEN", "template": "logs-k8s"
    # →   }]
    # → }

    curl -ku admin:$OS_PASS "https://localhost:9200/logs-k8s-default/_count?pretty"
    # → { "count" : 1204, "_shards" : { "total" : 3, "successful" : 3, "skipped" : 0, "failed" : 0 } }
    ```
4.  **Поиск работает** — найти ошибки конкретного сервиса за последний час:
    ```bash
    curl -ku admin:$OS_PASS "https://localhost:9200/logs-k8s-default/_search?pretty" \
      -H "Content-Type: application/json" -d '{
        "query": {
          "bool": {
            "filter": [
              { "term": { "service.name": "payments-api" } },
              { "term": { "status": "error_parsing" } },
              { "range": { "@timestamp": { "gte": "now-1h" } } }
            ]
          }
        }
      }'
    # → {"took":12,...,"hits":{"total":{"value":42},...}}
    ```

## Дополнительная информация

### Мониторинг конвейера (Observability)

1.  **Consumer Lag**: Самая важная метрика. Если лаг в Kafka растет — Vector не справляется. Решение: добавьте партиции в топик и увеличьте количество реплик Vector.
    ```bash
    kafka-consumer-groups.sh --bootstrap-server kafka-prod:9092 --describe --group vector-aggregator
    # → GROUP              TOPIC         PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG  CONSUMER-ID
    # → vector-aggregator  logs-k8s-raw  0         12503          12510          7    vector-aggregator-1-...
    ```
2.  **Backpressure в Fluent Bit**: Следите за метриками storage layer: `fluentbit_storage_layer_chunks_up` (активные чанки в RAM, норма — ниже `storage.max_chunks_up`) и `fluentbit_storage_layer_chunks_down` (чанки, вытесненные на диск). Рост `_down` означает, что Kafka работает медленно или недоступна.
     ```bash
     curl -s http://localhost:2020/api/v1/metrics/prometheus | grep fluentbit_storage_layer_chunks
     # → fluentbit_storage_layer_chunks_up 3
     # → fluentbit_storage_layer_chunks_down 0
     ```

3.  **Ошибки обработки в Vector**: метрика `component_errors_total` компонента `vrl_processing` и счетчик `component_received_events_total` sink'а `dlq_s3` должны оставаться на нуле; рост последнего означает изменение формата логов приложением (события уходят в DLQ).
4.  **End-to-End Tracing**: Используйте `trace_id` из OpenTelemetry для корреляции лога с конкретным запросом пользователя во всем конвейере — поле сохраняется при всех преобразованиях и индексируется как keyword.

### Безопасность и отказоустойчивость

*   **Шифрование**: Используйте TLS 1.3 для всех сегментов сети. Для сегмента Edge → Kafka добавьте поверх TLS аутентификацию SASL SCRAM (в Fluent Bit: `rdkafka.security.protocol: ssl_sasl_scram` + параметры `rdkafka.sasl.*`; в Vector source kafka — секция `sasl`), чтобы компрометация одного узла не давала анонимную запись в топики.
*   **Изоляция**: Выделяйте Vector-агрегаторы в отдельный пул узлов (Node Pool), чтобы тяжелые трансформации не влияли на работу приложений.
*   **Схема данных**: Стандартизируйте логи на базе **ECS (Elastic Common Schema)**. Это позволит использовать готовые правила безопасности в OpenSearch Security Analytics.
*   **Управление секретами**: Пароли не хранятся в конфигах — только переменные окружения или secret-провайдеры; учтите ограничение Vector 0.57+ по интерполяции `${VAR}` (см. Сценарий 3).
*   **Резервное копирование OpenSearch**: Настройте snapshot-репозиторий (S3/HDFS) и регулярные снимки индексов — retention ISM удаляет данные безвозвратно.

### Типичные проблемы

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| Consumer Lag монотонно растет | Vector не успевает за потоком | Масштабируйте: партиции топика ≥ числа реплик Vector; профилируйте VRL (тяжелые `geoip`/регексы); увеличьте `request.concurrency` |
| `fluentbit_storage_layer_chunks_*` растет | Kafka недоступна или медленная | Проверьте сетевую доступность `kafka-prod:9092` и ошибки в логе агента; убедитесь, что диск под `storage.path` не переполнен |
| События в DLQ (рост `component_received_events_total` у `dlq_s3`) | Приложение изменило формат лога | Изучите образец через `vector tap`, поправьте VRL; временно усильте парсинг fallback-веткой |
| Политика ISM не применяется к индексам потока | В политике нет `ism_template` или индексы созданы до привязки политики | Проверьте привязку: `GET _plugins/_ism/explain/.ds-logs-k8s-default-000001`; добавьте `ism_template` в политику или привяжите вручную: `POST /_plugins/_ism/add/<index>` |
| В логах Fluent Bit: `emitter cycle detected` | `match` фильтра `rewrite_tag` совпадает с порождаемым тегом | Сузьте `match` до тега входа (например, `kube.*`), чтобы новый тег не совпадал с шаблоном фильтра |
| Bulk-ответы 429 / `es_rejected_execution_exception` | OpenSearch перегружен записью | Backpressure корректно замедлит Vector (Kafka буферизует); увеличьте шарды/реплики кластера, проверьте refresh_interval |
| Ошибки маппинга `illegal_argument_exception` | Точки в ключах вложенных полей (labels/annotations K8s) | Замените точки на подчеркивания рекурсивно в VRL (рецепт: [Vector: Практические сценарии](../../Vector/practical_scenarios.md), сценарий 1) |
| События со сдвинутым временем | Часовой пояс при разборе timestamp | Задайте `timezone` в transform `remap` или нормализуйте время в UTC на Edge |

### Рекомендации по развитию

*   **OTel-native альтернатива**: По мере зрелости экосистемы часть слоя агрегации можно перенести на **OpenTelemetry Collector** (единый протокол OTLP end-to-end) либо на **Data Prepper** — OTel-ориентированный инжест-компонент экосистемы OpenSearch. Протокол: [OTLP Protocol](../../OpenTelemetry/otlp_protocol.md).
*   **Capacity planning**: пропускная способность партиции Kafka ~10 МБ/с; ориентир: `партиций >= max(пиковый поток / 10МБ/с, реплик Vector × 2)`.
*   **Порядок обновлений**: Storage (OpenSearch) → Aggregator (Vector) → Transport (Kafka) → Edge (Fluent Bit). Каждый следующий слой должен поддерживать протокол предыдущего обновленного; откат безопасен в обратном порядке благодаря буферизации в Kafka.
*   **Фиксация версий**: Пинуйте конкретные версии образов и пакетов (например, `fluent/fluent-bit:5.1.2`, `timberio/vector:0.58.0-alpine`, `opensearchproject/opensearch:3.8.0`) и обновляйте их контролируемо, сверяясь с release notes.

### Очистка окружения (откат изменений)

При демонтаже конвейера порядок обратный порядку обновления — сначала Edge, затем хранилище и буфер:

```bash
# 1. Остановка агентов (systemd или удаление подов/DaemonSet)
sudo systemctl stop vector fluent-bit

# 2. Удаление data stream (вместе со всеми backing-индексами)
curl -ku admin:$OS_PASS -X DELETE "https://localhost:9200/_data_stream/logs-k8s-default"
# → {"acknowledged": true}

# 3. Удаление шаблона индекса и политики ISM
curl -ku admin:$OS_PASS -X DELETE "https://localhost:9200/_index_template/logs-k8s"
# → {"acknowledged": true}
curl -ku admin:$OS_PASS -X DELETE "https://localhost:9200/_plugins/_ism/policies/logs-retention"
# → {"acknowledged": true}

# 4. Удаление топика-буфера (все недоставленные события в нем исчезнут)
kafka-topics.sh --bootstrap-server kafka-prod:9092 --delete --topic logs-k8s-raw
# → Topic logs-k8s-raw is marked for deletion.
```

Замечания:

*   Удаление data stream и топика необратимо — при необходимости сохранения сделайте снимок (`PUT _snapshot/<repo>/<snapshot>`) до удаления (см. раздел «Безопасность и отказоустойчивость»).
*   Локальные дисковые буферы (`storage.path` Fluent Bit, `data_dir` Vector) очищаются вручную после остановки агентов; при повторном развёртывании на том же хосте старые чанки будут дочитаны — это штатное поведение at-least-once.
*   Откат конфигурации агента: восстановите предыдущий файл конфигурации и перезапустите службу; Kafka-буфер гарантирует, что события, накопленные за время простоя, будут доставлены после возврата к рабочей конфигурации.

---
## См. также

*   **[OpenSearch: Обзор системы](../OpenSearch/opensearch_overview.md)** — архитектура и Data Streams.
*   **[OpenSearch: Управление жизненным циклом индексов (ISM)](../OpenSearch/opensearch_ism_lifecycle.md)** — детали политик ISM: warm/cold-фазы, force_merge, уведомления.
*   **[Kafka для мониторинга и наблюдаемости](../../Kafka/kafka_for_monitoring.md)** — риски прямой отправки телеметрии и роли брокера.
*   **[Kafka: CLI-утилиты](../../Kafka/kafka_cli_tools.md)** — справочник по kafka-topics.sh, kafka-consumer-groups.sh и другим инструментам.
*   **[Vector: Язык VRL](../../Vector/vrl_language.md)** — детальный справочник по функциям.
