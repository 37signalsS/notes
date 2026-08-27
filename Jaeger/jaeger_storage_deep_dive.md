# Storage Deep Dive: Jaeger

> **Важно:** Документация описывает **Jaeger v2** (текущая версия).

**Storage Deep Dive для Jaeger** — это детальный разбор бэкендов хранения (ClickHouse, Elasticsearch, Kafka), их внутреннего устройства, конфигурации и оптимизации под нагрузку. В Jaeger v2 механизм хранения инкапсулирован в **Storage Extension**, что обеспечивает единый пул соединений и retry-логику, но специфика настройки остается уникальной для каждой базы. Понимание внутреннего устройства хранилища необходимо для эксплуатации production-систем и ответов на собеседованиях про observability.

Общий обзор бэкендов: **[Обзор Jaeger](./jaeger_overview.md)**.
Архитектура Storage Extension: **[Архитектура Jaeger](./jaeger_architecture.md)**.
Capacity Planning: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Storage Extension** | Модуль Jaeger v2, предоставляющий единый интерфейс для всех бэкендов хранения (ClickHouse, Elasticsearch, Kafka) |
| **MergeTree** | Движок таблиц ClickHouse, используемый по умолчанию для хранения спанов. Обеспечивает высокую скорость чтения за счет сортировки и первичного ключа |
| **Inverted Index** | Индекс Elasticsearch, позволяющий выполнять поиск по тегам спанов. Потребляет много RAM при высокой cardinality |
| **ILM (Index Lifecycle Management)** | Политика автоматического управления жизненным циклом индексов в Elasticsearch (Hot/Warm/Cold/Delete) |
| **Consumer Group** | Группа Kafka-консьюмеров, обеспечивающая балансировку нагрузки и координацию offsets |
| **WAL (Write-Ahead Log)** | Журнал предзаписи Kafka, обеспечивающий durability сообщений перед коммитом offset |
| **TTL (Time To Live)** | Политика автоматического удаления старых трейсов на уровне таблицы/индекса |

---

## Базовые концепции

### Сравнение бэкендов

| Критерий | ClickHouse | Elasticsearch / OpenSearch | Kafka (буфер) |
| :--- | :--- | :--- | :--- |
| **Основное применение** | Production (рекомендуется с v2.20+) | Enterprise с требованиями к поиску | Буферизация пиков, streaming |
| **Скорость записи** | Очень высокая (columnar) | Средняя (inverted index overhead) | Очень высокая (append-only) |
| **Скорость поиска** | Высокая по tags (если настроен ORDER BY) | Высокая по произвольным атрибутам | Нет (только чтение топика) |
| **Стоимость хранения** | Низкая (компрессия MergeTree) | Средняя (инвертированные индексы) | Средняя (репликация Kafka) |
| **Сложность эксплуатации** | Средняя | Высокая (требует тюнинга JVM, шардирования) | Средняя |
| **TTL** | На уровне таблицы (partition) | ILM / ISM | Retention по топику |

### Архитектура Storage Extension

Storage Extension в Jaeger v2 выступает как фасад над бэкендами:
- **Connection Pool:** Единый пул соединений для Collector, Query и Ingester.
- **Retry Logic:** Экспоненциальные повторы при недоступности хранилища.
- **Circuit Breaker:** Отключение записей при длительном недоступлении БД.
- **Batching:** Группировка спанов перед записью для снижения overhead.

---

## ClickHouse Deep Dive

ClickHouse стал first-class citizen в Jaeger v2 благодаряcolumnar-архитектуре и эффективной компрессии.

### Схема базы данных

При использовании Jaeger v2 с ClickHouse создаются таблицы в базе `jaeger_v2`:

```sql
-- Основная таблица спанов
CREATE TABLE jaeger_v2.spans
(
    trace_id String,
    span_id String,
    operation_name String,
    start_time_ns UInt64,
    duration_ns UInt64,
    service_name String,
    tags Map(String, String),
    logs Array<JSON>,
    references Array<String>,
    process Array<String>,
    flags UInt32,
    PRIMARY KEY (trace_id, span_id)
)
ENGINE = MergeTree()
PARTITION BY toDate(fromUnixTimestamp64Nano(start_time_ns))
ORDER BY (service_name, operation_name, start_time_ns)
TTL start_time_ns + INTERVAL 7 DAY
SETTINGS index_granularity = 8192;
```

### Ключевые параметры конфигурации

| Параметр | Рекомендация | Описание |
| :--- | :--- | :--- |
| `ORDER BY` | `(service_name, operation_name, start_time_ns)` | Определяет физический порядок данных. Самый важный параметр для производительности поиска |
| `PARTITION BY` | `toDate(fromUnixTimestamp64Nano(start_time_ns))` | Разбивка по дням для эффективного TTL и prune partitions |
| `TTL` | `start_time_ns + INTERVAL 7 DAY` | Автоматическое удаление старых трейсов |
| `index_granularity` | `8192` | Количество строк между индексными маркерами. Меньше = быстрее поиск, больше = меньше размер индекса |
| `compression` | `LZ4` | Алгоритм сжатия. LZ4 — оптимальный баланс скорости и ratio |

### Оптимизация производительности

1.  **Индексы по часто используемым тегам:**
    ```sql
    CREATE INDEX idx_http_status ON jaeger_v2.spans (tags['http.status_code']) TYPE bloom_filter GRANULARITY 4;
    ```
2.  **TTL и партиционирование:** Удаление старых партиций происходит почти мгновенно без `OPTIMIZE TABLE FINAL`.
3.  **Настройка MergeTree:**
    ```yaml
    # clickhouse-server-config.xml
    <merge_tree>
      <max_bytes_to_merge_at_max_space_pool>5368709120</max_bytes_to_merge_at_max_space_pool>
      <number_of_free_entries_in_pool_to_lower_max_size_of_merge>16</number_of_free_entries_in_pool_to_lower_max_size_of_merge>
    </merge_tree>
    ```

### Ограничения

- **Нет Row-Level Security:** Изоляция данных по teams реализуется на уровне отдельных таблиц/баз.
- **Высокая cardinality тегов:** Bloom filter индексы эффективны только для низкой/средней cardinality. Для `trace_id` индексы не нужны (уже в PRIMARY KEY).
- ** updates/deletes:** MergeTree не предназначен для частых обновлений. Трейсы должны быть иммутабельными.

---

## Elasticsearch / OpenSearch Deep Dive

Elasticsearch используется в enterprise-средах с требованиями к гибкому поиску и RBAC.

### Mapping и Index Templates

```json
PUT _index_template/jaeger_v2
{
  "index_patterns": ["jaeger_v2*"],
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 2,
      "index.lifecycle.name": "jaeger_policy",
      "index.lifecycle.rollover_alias": "jaeger_v2"
    },
    "mappings": {
      "properties": {
        "traceID": { "type": "keyword" },
        "spanID": { "type": "keyword" },
        "operationName": { "type": "text", "fields": { "keyword": { "type": "keyword" } } },
        "serviceName": { "type": "keyword" },
        "duration": { "type": "long" },
        "startTime": { "type": "date_nanos" },
        "tags": { "type": "object", "enabled": true },
        "logs": { "type": "nested" }
      }
    }
  }
}
```

### ILM Policy

```json
PUT _ilm/policy/jaeger_policy
{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": { "rollover": { "max_size": "50GB", "max_age": "1d" } }
      },
      "warm": {
        "min_age": "7d",
        "actions": { "shrink": { "number_of_shards": 1 }, "force_merge": { "max_num_segments": 1 } }
      },
      "delete": {
        "min_age": "30d",
        "actions": { "delete": {} }
      }
    }
  }
}
```

### Оптимизация производительности

1.  **Shard Sizing:** Целевой размер шарда 20–50 GB. При росте выше 50 GB поиск замедляется.
2.  **Force Merge:** Периодический `force_merge` на warm-фазе снижает количество сегментов и ускоряет поиск.
3.  **Отключение `_source`:** Если нужны только агрегации, отключите `_source` для экономии места.
4.  **Keyword vs Text:** Используйте `keyword` для точного совпадения тегов, `text` — для полнотекстового поиска по `operationName`.

### Ограничения

- **JVM Heap:** Максимум 31 GB. При большем heap GC становится длительным и неэффективным.
- **Shard Splitting:** Нельзя уменьшить количество шардов после создания индекса. Планируйте шардирование заранее.
- **Index Corruption:** При нештатном завершении могут появиться corrupted segments. Решение: `POST /index/_refresh` и проверка `_cat/indices`.

---

## Kafka Deep Dive (Streaming)

Kafka выступает как буфер между Collector (producer) и Ingester (consumer), обеспечивая decoupling SLA приема от скорости записи в ClickHouse.

### Конфигурация топика

```bash
# Создание топика с оптимальными параметрами
kafka-topics.sh --create \
  --topic jaeger-spans \
  --partitions 12 \
  --replication-factor 3 \
  --config retention.hours=48 \
  --config segment.bytes=1073741824 \
  --config compression.type=lz4 \
  --bootstrap-server kafka:9092
```

### Producer (Collector) конфигурация

```yaml
exporters:
  kafka:
    brokers: ["kafka:9092"]
    topic: jaeger-spans
    protocol_version: "2.0.0"
    compression: lz4
    metadata:
      full: false
    retry:
      backoff: 1s
      max: 3
```

### Consumer (Ingester) конфигурация

```yaml
receivers:
  kafka:
    brokers: ["kafka:9092"]
    topic: jaeger-spans
    protocol_version: "2.0.0"
    group_id: jaeger-ingester

processors:
  batch:

exporters:
  jaeger_storage_exporter:
    trace_storage:
      type: clickhouse
      options:
        clickhouse:
          endpoint: "tcp://clickhouse:9000"
          database: jaeger_v2
```

### Consumer Group и Offset Management

- **Группа `jaeger-ingester`:** Все инстансы Ingester принадлежат одной группе. Kafka автоматически распределяет партиции между ними.
- **Offset Commit:** Ingester коммитит offset после успешной записи в ClickHouse. При сбое Ingester перечитывает неподтвержденные сообщения.
- **Lag Monitoring:** Критически важно отслеживать `consumer_lag`:
  ```bash
  kafka-consumer-groups.sh --bootstrap-server kafka:9092 --describe --group jaeger-ingester
  ```

### Ограничения

- **Retention:** При переполнении retention старые сегменты удаляются. Если Ingester отстал, данные теряются.
- **Replication Factor 1:** Риск потери данных при падении брокера. Используйте RF ≥ 3 в production.
- **Message Size:** По умолчанию максимальный размер сообщения в Kafka 1 MB. При очень больших спанах увеличьте `message.max.bytes`.

---

## Практические сценарии

### Сценарий 1: Первичная настройка ClickHouse для Jaeger

```bash
# 1. Создание базы данных
clickhouse-client --query "CREATE DATABASE IF NOT EXISTS jaeger_v2"

# 2. Создание таблицы (если не используется Storage Extension auto-init)
clickhouse-client --query "
CREATE TABLE IF NOT EXISTS jaeger_v2.spans
(
    trace_id String,
    span_id String,
    operation_name String,
    start_time_ns UInt64,
    duration_ns UInt64,
    service_name String,
    tags Map(String, String),
    logs Array<JSON>,
    references Array<String>,
    process Array<String>,
    flags UInt32,
    PRIMARY KEY (trace_id, span_id)
)
ENGINE = MergeTree()
PARTITION BY toDate(fromUnixTimestamp64Nano(start_time_ns))
ORDER BY (service_name, operation_name, start_time_ns)
TTL start_time_ns + INTERVAL 7 DAY
SETTINGS index_granularity = 8192;
"

# 3. Создание индекса по тегу http.status_code
clickhouse-client --query "
CREATE INDEX idx_http_status ON jaeger_v2.spans (tags['http.status_code']) TYPE bloom_filter GRANULARITY 4;
"

# 4. Проверка
clickhouse-client --query "SHOW TABLES FROM jaeger_v2"
clickhouse-client --query "SELECT count() FROM jaeger_v2.spans"
```

### Сценарий 2: Перенос данных из Elasticsearch v1 в ClickHouse v2

```python
import requests
import json

ES_URL = "http://elasticsearch:9200/jaeger-*/_search?scroll=2m"
CH_URL = "http://clickhouse:8123"

# 1. Получение всех спанов из Elasticsearch
response = requests.get(ES_URL, json={"query": {"match_all": {}}, "size": 1000})
hits = response.json()["hits"]["hits"]
scroll_id = response.json()["_scroll_id"]

while hits:
    # 2. Трансформация в формат ClickHouse
    for hit in hits:
        span = hit["_source"]
        # ... адаптация полей под схему ClickHouse
        pass

    # 3. Пачкающая запись в ClickHouse
    # (реализация bulk insert)

    # 4. Получение следующей порции
    response = requests.get(f"http://elasticsearch:9200/_search/scroll", json={"scroll_id": scroll_id})
    hits = response.json()["hits"]["hits"]
```

### Сценарий 3: Мониторинг здоровья Kafka Consumer Group

```bash
# Проверка lag
kafka-consumer-groups.sh --bootstrap-server kafka:9092 --describe --group jaeger-ingester

# Ожидаемый вывод:
# GROUP   TOPIC       PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG
# jaeger-ingester jaeger-spans 0  12345678        12345680         2

# Если LAG растет — увеличивайте реплики Ingester или проверьте скорость записи в ClickHouse
```

---

## Лучшие практики

1.  **ClickHouse как default:** Используйте ClickHouse для новых проектов. Он обеспечивает лучшую производительность и меньшую TCO.
2.  **TTL повсеместно:** Настраивайте TTL на уровне таблицы/индекса. Без TCO данные будут расти бесконечно.
3.  **Ограничьте cardinality:** Удаляйте high-cardinality теги на уровне Collector (`attributes` processor), если они не нужны для поиска.
4.  **Kafka только для пиков:** Не используйте Kafka как постоянное хранилище. Retention 24–48 часов достаточно для большинства сценариев.
5.  **Мониторинг disk и lag:** Настройте алерты на `disk_usage` (ClickHouse) и `consumer_lag` (Kafka) до наступления проблем.

---

## Очистка окружения

```bash
# Остановка Docker Compose
docker compose down -v

# Удаление данных ClickHouse
docker volume rm jaeger_clickhouse_data

# Удаление тестовых ресурсов Kubernetes
kubectl delete namespace jaeger-test
```

---

## Дополнительная информация

**Смежные темы:**

* Выбор хранилища: **[Обзор Jaeger](./jaeger_overview.md)**
* Архитектура Storage Extension: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Production развертывание: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**
* ClickHouse: **[ClickHouse: Обзор](../Databases/ClickHouse/clickhouse.md)**
* Kafka: **[Apache Kafka: Обзор](../Kafka/kafka_overview.md)**
* Elasticsearch Capacity Planning: **[Elasticsearch: Capacity Planning](../ELK_Stack/Elasticsearch/elasticsearch_capacity_planning.md)**

### См. также

* [Jaeger Storage Documentation](https://www.jaegertracing.io/docs/latest/storage/)
* [ClickHouse MergeTree Documentation](https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/mergetree)
* [Elasticsearch ILM Documentation](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-lifecycle-management.html)
