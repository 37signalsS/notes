# MongoDB: Интеграция с Kafka и CDC

**Актуально для:** MongoDB 8.0.x, MongoDB Kafka Connector 2.x, Debezium 2.x, Kafka 3.x, Kafka Connect 3.x

---

## Определения

*   **CDC (Change Data Capture):** Техника захвата изменений данных в реальном времени из журнала операций (oplog) или Change Streams с доставкой в внешнюю систему без опроса (polling) таблиц.
*   **MongoDB Kafka Connector:** Официальный коннектор MongoDB для Kafka Connect. Работает в двух режимах: **Source** (Change Streams MongoDB → Kafka topics) и **Sink** (Kafka topics → MongoDB). Распространяется через Confluent Hub.
*   **Debezium MongoDB Connector:** Open-source коннектор CDC (Red Hat), захватывающий изменения MongoDB через Change Streams и публикующий их в Kafka в стандартизированном формате (с `source`, `op`, `ts_ms` и т.д.).
*   **Change Stream:** Нативный механизм MongoDB для подписки на изменения коллекции/БД/кластера (см. [Change Streams](./mongodb-change-streams.md)). Используется коннекторами как источник изменений.
*   **Oplog:** Специальная capped collection `local.oplog.rs`, хранящая историю операций репликации. Change Streams построены поверх oplog; коннекторы не читают oplog напрямую (кроме legacy-режимов Debezium < 1.0).
*   **Kafka Connect:** Фреймворк для потоковой интеграции Kafka с внешними системами. Коннекторы управляются через REST API (`PUT /connectors/<name>/config`).
*   **SMT (Single Message Transform):** Трансформация отдельного сообщения в Kafka Connect (фильтрация, маппинг, маскирование PII).
*   **DLQ (Dead Letter Queue):** Топик для сообщений, которые не удалось обработать.
*   **Offset Management:** Хранение смещений обработанных данных в Kafka (внутренние топики `__consumer_offsets`, `connect-offsets`).
*   **Resume Token:** Уникальный идентификатор позиции в Change Stream, содержащий Oplog timestamp. Позволяет возобновить чтение после перезапуска.

---

## Базовые концепции

### Два подхода к CDC из MongoDB

| Критерий | MongoDB Kafka Connector | Debezium MongoDB Connector |
| :--- | :--- | :--- |
| **Производитель** | MongoDB Inc. (Confluent-licensed) | Red Hat / Debezium community |
| **Источник изменений** | Change Streams | Change Streams (с Debezium 1.x) |
| **Формат сообщения** | Полный документ (`fullDocument`) | Envelope: `before`/`after`/`op`/`source`/`ts_ms` |
| **Sink-режим** | Есть (Kafka → MongoDB) | Нет (только source) |
| **Типичное применение** | Двунаправленная интеграция, репликация в/из MongoDB | Единый CDC-конвейер для многих СУБД, ETL, audit trail |

### Как работает Source-коннектор

```
mongod (Change Stream)
   │  watch() на коллекции/БД/cluster
   ▼
Kafka Connect Worker (connector task)
   │  преобразование в Kafka record
   ▼
Kafka Topic (prefix + db + collection)
   │
   ▼
Consumers: Elasticsearch, Data Warehouse, микросервисы
```

1.  Коннектор открывает Change Stream (`$changeStream`) с `fullDocument: "updateLookup"` — при `update` в сообщении передаётся полный документ, а не только diff.
2.  Каждая операция (`insert`, `update`, `delete`, `invalidate`) публикуется в topic. Имя topic формируется из `topic.prefix` + имя БД + имя коллекции.
3.  Offset коннектора хранится в Kafka Connect (`__consumer_offsets` / `connect-offsets`), что обеспечивает **at-least-once** доставку и возобновление после рестарта с последнего зафиксированного токена resume.
4.  При потере кворума или недоступности primary коннектор ждёт восстановления Change Stream (автоматический resume по `_data` токену).

### Как работает Sink-коннектор

*   Читает записи из указанных topics и применяет к коллекции MongoDB: `insert` / `update` (upsert) / `delete` по ключу `_id`.
*   Поддерживает **Change Data Capture handlers** — парсеры сообщений в формате Debezium/Confluent, что позволяет принимать потоки, произведённые Debezium из других СУБД, и реплицировать их в MongoDB.
*   Идемпотентность: при повторной доставке записи sink применяет upsert, что делает повторную обработку безопасной.

### Почему CDC, а не polling

*   **Нагрузка:** polling (`find({updatedAt: {$gt: ...}})`) требует индекса и генерирует read load; CDC читает oplog-поток без нагрузки на рабочий набор.
*   **Порядок:** CDC гарантирует порядок операций в пределах shard/partition; polling — нет.
*   **Delete-операции:** polling не видит удаления без tombstone-колонок; CDC передаёт `delete` явно.

---

## Подготовка окружения (Prerequisites)

| Требование | Минимальное значение | Рекомендуемое | Примечание |
| :--- | :--- | :--- | :--- |
| **MongoDB Server** | 4.4+ (Replica Set) | 8.0.x | Change Streams требуют Replica Set или sharded cluster. Standalone не поддерживается. |
| **Kafka** | 2.8+ | 3.6+ (KRaft) | Для production — кластер 3+ брокеров, `min.insync.replicas=2`. |
| **Kafka Connect** | 2.8+ | 3.6+ | Distributed mode с 3+ воркерами. `group.id` уникален для кластера. |
| **MongoDB Kafka Connector** | 1.8+ | 2.x (latest) | Совместимость с версией MongoDB: Connector 2.x для MongoDB 6.0/7.0/8.0. |
| **Debezium (если используется)** | 1.9+ | 2.x+ | Debezium 2.x требует Kafka Connect 3.x. |
| **Права MongoDB** | `read` на целевую БД + `clusterMonitor` (cluster-wide) | Пользователь с `read` + `changeStream` привилегией | Для source-коннектора: `read` на БД/коллекцию. Для watch на кластер: `clusterMonitor` / `clusterAdmin`. |
| **RAM (Kafka Connect worker)** | 4 GB | 8-16 GB | JVM heap 2-4 GB + off-heap для буферов. При больших потоках увеличивайте. |
| **Диск (Kafka Connect)** | 50 GB | 200+ GB SSD NVMe | Внутренние топики (config/offset/status), логи, временные файлы. |
| **Сеть** | 1 Gbps | 10 Gbps | Низкая латентность между Connect, Kafka и MongoDB критична для CDC. |
| **CPU** | 2 vCPU | 8+ vCPU | JVM GC, SMT трансформации, (де)сериализация Avro/Protobuf. |
| **ОС** | Linux (Ubuntu 20.04+, RHEL 8+) | Linux, актуальный LTS | Production не на Windows. |
| **Файловая система** | ext4 / xfs | xfs с `noatime` | Для Kafka log.dirs и Connect work dir. |

**Установка MongoDB Kafka Connector (Linux):**
```bash
# Через Confluent Hub (на каждом Kafka Connect worker)
confluent-hub install --no-prompt mongodb/kafka-connect-mongodb:latest
# # → Installed plugin 'MongoDB Kafka Connector' to /usr/share/confluent-hub-components

# Перезапуск Kafka Connect после установки
systemctl restart confluent-kafka-connect
```

**Установка Debezium MongoDB Connector:**
```bash
# Через Confluent Hub
confluent-hub install --no-prompt debezium/debezium-connector-mongodb:latest

# Или в Docker-образе Kafka Connect (Dockerfile)
FROM confluentinc/cp-kafka-connect:7.6.0
RUN confluent-hub install --no-prompt debezium/debezium-connector-mongodb:latest
```

**Проверка версий и совместимости:**
```bash
# Kafka Connect version
curl -s http://localhost:8083/ | jq .version
# # → "3.6.0"

# Список установленных плагинов
curl -s http://localhost:8083/connector-plugins | jq '.[].class' | grep -i mongo
# # → "com.mongodb.kafka.connect.MongoSourceConnector"
# # → "com.mongodb.kafka.connect.MongoSinkConnector"
# # → "io.debezium.connector.mongodb.MongoDbConnector" (если Debezium установлен)

# Проверка MongoDB Replica Set статуса
mongosh --eval "rs.status()" --quiet
# # → { "ok": 1, "members": [ { "stateStr": "PRIMARY" }, ... ] }
```

---

## Практические сценарии

### 1. Установка MongoDB Kafka Connector

```bash
# Установка через Confluent Hub (на ноде Kafka Connect)
confluent-hub install mongodb/kafka-connect-mongodb:latest
# # → Installed plugin 'MongoDB Kafka Connector'

# Или Docker-образ с коннектором
docker run -d --name mongo-kafka-connect \
  -p 8083:8083 \
  -e CONNECT_BOOTSTRAP_SERVERS=kafka:9092 \
  -e CONNECT_GROUP_ID=mongo-connect-cluster \
  -e CONNECT_CONFIG_TOPIC=connect-configs \
  -e CONNECT_OFFSET_TOPIC=connect-offsets \
  -e CONNECT_STATUS_TOPIC=connect-statuses \
  -e CONNECT_KEY_CONVERTER_SCHEMAS_ENABLE=false \
  -e CONNECT_VALUE_CONVERTER_SCHEMAS_ENABLE=false \
  -e CONNECT_PLUGIN_PATH=/usr/share/java,/usr/share/confluent-hub-components \
  confluentinc/cp-kafka-connect:7.6.0
```

### 2. Source-коннектор: MongoDB → Kafka

```bash
curl -X PUT http://localhost:8083/connectors/mongo-source/config \
  -H "Content-Type: application/json" \
  -d '{
    "connector.class": "com.mongodb.kafka.connect.MongoSourceConnector",
    "connection.uri": "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0",
    "database": "sales_db",
    "collection": "orders",
    "topic.prefix": "mongo",
    "output.format.value": "json",
    "output.schema.infer.value": "true",
    "change.stream.full.document": "updateLookup",
    "publish.full.document.only": "true",
    "tasks.max": "2"
  }'
# # → {"name":"mongo-source","config":{...},"tasks":[...],"type":"source"}
```

**Параметры:**

| Параметр | Назначение |
| :--- | :--- |
| `connection.uri` | URI replica set (обязательно `replicaSet` — Change Streams требуют RS/sharded cluster). |
| `database` / `collection` | Источник изменений. Пустое значение — вся БД / весь кластер. |
| `topic.prefix` | Префикс topic: `mongo.sales_db.orders`. |
| `change.stream.full.document` | `updateLookup` — полный документ в сообщении об update. |
| `publish.full.document.only` | `true` — публиковать только документ (без обёртки `operationType`/`ns`). |

**Проверка потока:**
```bash
kafka-console-consumer --bootstrap-server kafka:9092 \
  --topic mongo.sales_db.orders --from-beginning
# # → {"_id":{"$oid":"..."},"amount":1200,"status":"paid"}
```

### 3. Sink-коннектор: Kafka → MongoDB

```bash
curl -X PUT http://localhost:8083/connectors/mongo-sink/config \
  -H "Content-Type: application/json" \
  -d '{
    "connector.class": "com.mongodb.kafka.connect.MongoSinkConnector",
    "connection.uri": "mongodb://mongo1:27017/?replicaSet=rs0",
    "database": "analytics_db",
    "collection": "orders_mirror",
    "topics": "mongo.sales_db.orders",
    "delete.on.null.values": "true",
    "writemodel.strategy": "com.mongodb.kafka.connect.sink.writemodel.strategy.ReplaceOneDefaultStrategy",
    "tasks.max": "1"
  }'
# # → {"name":"mongo-sink","config":{...},"tasks":[...],"type":"sink"}
```

*   `delete.on.null.values: true` — Kafka-запись с `null` value трактуется как `delete` (tombstone).
*   `writemodel.strategy` — стратегия записи: `ReplaceOneDefaultStrategy` (upsert по `_id`), `InsertOneDefaultStrategy`, `UpdateOneTimestampStrategy` (для Debezium-формата).

### 4. Sink с обработкой Debezium-сообщений

Когда источник — Debezium (например, из PostgreSQL), включается CDC-handler:

```json
{
  "connector.class": "com.mongodb.kafka.connect.MongoSinkConnector",
  "connection.uri": "mongodb://mongo1:27017/?replicaSet=rs0",
  "database": "target_db",
  "collection": "customers",
  "topics": "dbserver1.inventory.customers",
  "change.data.capture.handler": "com.mongodb.kafka.connect.sink.cdc.debezium.DebeziumHandler",
  "delete.on.null.values": "true"
}
```

**DebeziumHandler** маппит envelope Debezium (`op: "c"/"u"/"d"`) в операции MongoDB: `c` → insert, `u` → replace/upsert, `d` → delete.

### 5. Debezium MongoDB Source Connector (альтернатива официальному)

Debezium использует стандартизированный формат envelope для CDC, что удобно для мульти-СУБД пайплайнов:

```bash
curl -X PUT http://localhost:8083/connectors/debezium-mongo-source/config \
  -H "Content-Type: application/json" \
  -d '{
    "connector.class": "io.debezium.connector.mongodb.MongoDbConnector",
    "mongodb.connection.string": "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0",
    "database.include.list": "sales_db",
    "collection.include.list": "sales_db.orders",
    "topic.prefix": "dbz",
    "tasks.max": "2",
    "snapshot.mode": "initial",
    "change.stream.full.document": "updateLookup"
  }'
# # → {"name":"debezium-mongo-source","config":{...},"tasks":[...],"type":"source"}
```

**Формат сообщения Debezium (envelope):**
```json
{
  "before": null,
  "after": { "_id": {"$oid": "..."}, "amount": 1200, "status": "paid" },
  "source": { "version": "2.5.0", "connector": "mongodb", "name": "dbz", "ts_ms": 1700000000000, "snapshot": "false", "db": "sales_db", "collection": "orders", "ord": 1, "rs": "rs0" },
  "op": "c",
  "ts_ms": 1700000000000
}
```

| Параметр Debezium | Назначение |
| :--- | :--- |
| `snapshot.mode` | `initial` (полный снапшот при старте) / `never` / `when_needed` |
| `change.stream.full.document` | `updateLookup` / `whenAvailable` / `required` |
| `mongodb.connection.string` | URI Replica Set (Standalone не поддерживается) |
| `database.include.list` / `collection.include.list` | Фильтрация БД/коллекций (regex допускается) |

### 6. SMT (Single Message Transform) для MongoDB коннекторов

```json
{
  "connector.class": "com.mongodb.kafka.connect.MongoSourceConnector",
  "connection.uri": "mongodb://mongo1:27017/?replicaSet=rs0",
  "database": "sales_db",
  "collection": "orders",
  "topic.prefix": "mongo",
  "transforms": "filterActive,addTimestamp,renameId",
  "transforms.filterActive.type": "org.apache.kafka.connect.transforms.Filter$Value",
  "transforms.filterActive.filter.condition": "$[?(@.status != 'cancelled')]",
  "transforms.addTimestamp.type": "org.apache.kafka.connect.transforms.InsertField$Value",
  "transforms.addTimestamp.timestamp.field": "kafka_ts",
  "transforms.renameId.type": "org.apache.kafka.connect.transforms.RenameField$Value",
  "transforms.renameId.renamed": "_id:orderId"
}
```

| SMT | Применение для CDC |
| :--- | :--- |
| `Filter` | Отбросить ненужные события (например, `status: cancelled`) |
| `InsertField` | Добавить `processed_at`, `source_cluster` метаданные |
| `RenameField` | Нормализовать имена полей (`_id` → `id`) |
| `MaskField` | Скрыть PII (`email` → `***@***.com`) |
| `RegexRouter` | Изменить имя топика: `mongo.db.coll` → `prod.db.coll` |
| `ExtractField` | Извлечь вложенное поле в корень сообщения |

### 7. Production hardening: DLQ, Retries, Exactly-once

**Sink с DLQ и retry:**
```json
{
  "connector.class": "com.mongodb.kafka.connect.MongoSinkConnector",
  "connection.uri": "mongodb://mongo1:27017/?replicaSet=rs0",
  "database": "analytics_db",
  "collection": "orders_mirror",
  "topics": "mongo.sales_db.orders",
  "tasks.max": "4",
  "errors.tolerance": "all",
  "errors.deadletterqueue.topic.name": "dlq.mongo.sink",
  "errors.deadletterqueue.context.headers.enable": "true",
  "errors.retry.delay.max.ms": "60000",
  "errors.retry.timeout": "300000"
}
```

**Настройка Kafka Connect Worker (connect-distributed.properties):**
```properties
group.id=mongo-connect-prod
config.storage.topic=connect-configs
offset.storage.topic=connect-offsets
status.storage.topic=connect-status
config.storage.replication.factor=3
offset.storage.replication.factor=3
status.storage.replication.factor=3

key.converter=io.confluent.connect.avro.AvroConverter
value.converter=io.confluent.connect.avro.AvroConverter
key.converter.schema.registry.url=http://schema-registry:8081
value.converter.schema.registry.url=http://schema-registry:8081

offset.flush.interval.ms=60000
offset.flush.timeout.ms=30000
task.shutdown.graceful.timeout.ms=30000
```

### 8. Управление Resume Token и Recovery

Change Streams использует Resume Token для возобновления. Kafka Connect хранит offsets в топике `connect-offsets`, но для внешней системы (consumer) токен нужно извлекать вручную:

```bash
# Просмотр offsets коннектора в Kafka Connect
curl -s http://localhost:8083/connectors/mongo-source/offsets | jq .
# # → [{"partition":{"connector":"mongo-source","collection":"orders","database":"sales_db"}},{"offset":{"_data":"...resume_token..."}}]

# Ручной resume для custom consumer (mongosh/Node.js):
# 1. Получить последний токен из Kafka (последнее сообщение в топике)
# 2. resumeAfter: token._data
```

```javascript
// Node.js consumer с resume
const { Kafka } = require("kafkajs");
const { MongoClient } = require("mongodb");

const kafka = new Kafka({ brokers: ["kafka:9092"] });
const consumer = kafka.consumer({ groupId: "mongo-cdc-consumer" });
const mongo = new MongoClient("mongodb://mongo1:27017/?replicaSet=rs0");

let lastToken = await loadTokenFromRedis("mongo:cdc:token");

await consumer.connect();
await consumer.subscribe({ topic: "mongo.sales_db.orders", fromBeginning: false });

await consumer.run({
  eachMessage: async ({ message }) => {
    const doc = JSON.parse(message.value.toString());
    await mongo.db("analytics").collection("orders").replaceOne({ _id: doc._id }, doc, { upsert: true });
    lastToken = message.headers.find(h => h.key === "resumeToken")?.value?.toString() || lastToken;
    await saveTokenToRedis("mongo:cdc:token", lastToken);
  }
});
```

### 9. Мониторинг коннекторов (расширенный)

```bash
# Статус коннектора и его task'ов
curl -s http://localhost:8083/connectors/mongo-source/status | jq .
# # → {"name":"mongo-source","connector":{"state":"RUNNING",...},
# #    "tasks":[{"id":0,"state":"RUNNING","worker_id":"..."}], "type":"source"}

# Список коннекторов
curl -s http://localhost:8083/connectors
# # → ["mongo-source","mongo-sink"]

# Лаг репликации: сравнение ts последнего сообщения в topic
# с текущим временем (проверка свежести потока)
kafka-run-class kafka.tools.GetOffsetShell --broker-list kafka:9092 \
  --topic mongo.sales_db.orders --time -1
```

**Алерты (Prometheus + JMX Exporter на Kafka Connect):**
*   `connect_connector_task_state{state="FAILED"}` — коннектор упал.
*   Отсутствие новых сообщений в topic > порога (например, 60s) — CDC-поток застопорился.
*   `mongodb_connector_task_connection_errors` — ошибки подключения к MongoDB.

**Ключевые JMX-метрики (JMX Exporter → Prometheus):**
| Метрика | Назначение | Порог алерта |
| :--- | :--- | :--- |
| `connect_connector_task_state` | Состояние task (RUNNING/FAILED/PAUSED) | `FAILED` > 0 |
| `connect_source_task_records_produced_total` | Кол-во записей, отправленных source task | Рост = 0 за 60s |
| `connect_sink_task_records_put_total` | Кол-во записей, записанных sink task | Рост = 0 за 60s |
| `connect_sink_task_write_errors_total` | Ошибки записи sink | > 0 |
| `mongodb_connector_task_connection_errors` | Ошибки подключения к MongoDB | > 0 |
| `connect_task_offset_commit_failure_total` | Сбои коммита offset | > 0 |
| `kafka_connect_kafka_producer_record_send_rate` | Throughput producer | Падение > 50% |
| `jvm_memory_used_bytes / jvm_memory_max_bytes` | Heap usage Connect worker | > 80% |

**Dashboard (Grafana) — обязательные панели:**
1. Connector/Task state (таблица: connector, task_id, state, worker)
2. Throughput: records/sec (source/sink)
3. Replication lag: `now() - max(message.timestamp)` per topic
4. Error rate: write errors, DLQ size
5. JVM: heap, GC pause, threads

---

## Операции и Команды (Reference)

### Kafka Connect REST API

| Операция | HTTP | Endpoint | Пример |
| :--- | :--- | :--- | :--- |
| Список коннекторов | `GET` | `/connectors` | `curl localhost:8083/connectors` |
| Статус коннектора | `GET` | `/connectors/{name}/status` | `curl localhost:8083/connectors/mongo-source/status` |
| Конфиг коннектора | `GET` | `/connectors/{name}/config` | `curl localhost:8083/connectors/mongo-source/config` |
| Создать/Обновить коннектор | `PUT` | `/connectors/{name}/config` | `curl -X PUT ... -d @config.json` |
| Удалить коннектор | `DELETE` | `/connectors/{name}` | `curl -X DELETE localhost:8083/connectors/mongo-source` |
| Рестарт коннектора | `POST` | `/connectors/{name}/restart` | `curl -X POST localhost:8083/connectors/mongo-source/restart` |
| Рестарт task | `POST` | `/connectors/{name}/tasks/{id}/restart` | `curl -X POST .../tasks/0/restart` |
| Пауза коннектора | `PUT` | `/connectors/{name}/pause` | `curl -X PUT localhost:8083/connectors/mongo-source/pause` |
| Резюме коннектора | `PUT` | `/connectors/{name}/resume` | `curl -X PUT localhost:8083/connectors/mongo-source/resume` |
| Offsets коннектора | `GET` | `/connectors/{name}/offsets` | `curl localhost:8083/connectors/mongo-source/offsets` |
| Список плагинов | `GET` | `/connector-plugins` | `curl localhost:8083/connector-plugins` |

### MongoDB Kafka Connector — ключевые конфиги

| Параметр | Source / Sink | Описание | Пример |
| :--- | :--- | :--- | :--- |
| `connector.class` | Оба | Класс коннектора | `com.mongodb.kafka.connect.MongoSourceConnector` |
| `connection.uri` | Оба | MongoDB URI (RS обязателен) | `mongodb://m1:27017,m2:27017/?replicaSet=rs0` |
| `database` | Source | БД-источник (пусто = все) | `sales_db` |
| `collection` | Source | Коллекция (пусто = все) | `orders` |
| `topic.prefix` | Source | Префикс топика | `mongo` → `mongo.sales_db.orders` |
| `topics` | Sink | Список топиков (через запятую) | `mongo.sales_db.orders,mongo.sales_db.users` |
| `database` / `collection` | Sink | Целевая БД/коллекция | `analytics_db` / `orders_mirror` |
| `change.stream.full.document` | Source | `updateLookup` / `whenAvailable` / `required` | `updateLookup` |
| `publish.full.document.only` | Source | `true` — только документ, без envelope | `true` |
| `writemodel.strategy` | Sink | Стратегия записи | `ReplaceOneDefaultStrategy` |
| `delete.on.null.values` | Sink | `null` value = delete (tombstone) | `true` |
| `change.data.capture.handler` | Sink | Парсер CDC форматов | `DebeziumHandler` |
| `tasks.max` | Оба | Параллелизм (до партиций/шардов) | `4` |
| `batch.size` | Source | Размер батча из Change Stream | `1000` |
| `poll.max.batch.size` | Source | Макс. записей за poll | `1000` |
| `offset.flush.interval.ms` | Worker | Интервал коммита offsets | `60000` |

### Debezium MongoDB Connector — ключевые конфиги

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `connector.class` | Класс коннектора | `io.debezium.connector.mongodb.MongoDbConnector` |
| `mongodb.connection.string` | URI Replica Set | `mongodb://m1:27017/?replicaSet=rs0` |
| `database.include.list` | БД для CDC (regex) | `sales_db` |
| `collection.include.list` | Коллекции для CDC | `sales_db.orders` |
| `topic.prefix` | Префикс топика | `dbz` → `dbz.sales_db.orders` |
| `snapshot.mode` | `initial` / `never` / `when_needed` | `initial` |
| `change.stream.full.document` | `updateLookup` / `whenAvailable` | `updateLookup` |
| `tasks.max` | Параллелизм | `2` |

### Полезные команды диагностики

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `curl -s localhost:8083/connectors` | Список коннекторов | `["mongo-source","mongo-sink"]` |
| `curl -s localhost:8083/connectors/mongo-source/status \| jq` | Статус задач | Все tasks: `"state":"RUNNING"` |
| `curl -s localhost:8083/connectors/mongo-source/offsets \| jq` | Offsets (Resume Tokens) | `_data` токены для каждой партиции |
| `kafka-topics --bootstrap-server kafka:9092 --list \| grep mongo` | Топики MongoDB | `mongo.sales_db.orders` |
| `kafka-consumer-groups --bootstrap-server kafka:9092 --group mongo-connect-prod --describe` | Lag consumer group | `LAG` = 0 или минимальный |
| `kafka-console-consumer --bootstrap-server kafka:9092 --topic mongo.sales_db.orders --from-beginning --max-messages 5` | Проверка формата сообщений | JSON документы |
| `mongosh --eval "rs.status()" --quiet` | Проверка RS | `"ok": 1, members: PRIMARY/SECONDARY` |
| `mongosh --eval "db.getSiblingDB('sales_db').orders.countDocuments()" --quiet` | Подсчёт документов | Число записей |

---

## Устранение неполадок

| Проблема | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`Connector task FAILED` с `MongoCommandException`** | Нет прав на Change Stream (требуется `changeStream` privilege / роль `read` на БД + `clusterMonitor` для cluster-wide watch). | Логи worker'а: `grep "not authorized" connect-distributed.log`. | Выдать пользователю коннектора роль `read` на отслеживаемую БД; для watch на весь кластер — `clusterMonitor`. |
| **Коннектор не создаёт topic** | Неверный `topic.prefix` или Kafka не доступен с worker'а. | `curl /connectors/<name>/status`, логи worker'а. | Проверить `bootstrap.servers`, создать topic заранее (`kafka-topics --create`). |
| **Потеря изменений после рестарта** | Offset не зафиксирован (`offset.flush.interval.ms` слишком велик). | `curl /connectors/<name>/offsets`. | Уменьшить `offset.flush.interval.ms`; проверить `__consumer_offsets`. |
| **`updateLookup` возвращает `null` в fullDocument** | Документ удалён до чтения, или `fullDocument` не настроен. | Сравнить `operationType: "update"` с содержимым `fullDocument`. | Установить `change.stream.full.document: "updateLookup"`; обрабатывать `null` в consumer. |
| **Рост лага при большом потоке** | `tasks.max` меньше партиционности/нагрузки; один task обрабатывает все изменения. | Метрики throughput task'ов. | Увеличить `tasks.max` (source: до числа шардов/партиций). |
| **Debezium-события не применяются sink'ом** | Не указан `change.data.capture.handler`. | В MongoDB приходят сырые JSON-envelope как документы. | Добавить `DebeziumHandler` в конфиг sink-коннектора. |
| **Change Stream `invalidate` после drop collection** | Коллекция удалена — коннектор получает invalidate event и останавливается. | Логи: `invalidate` event. | Пересоздать коннектор; использовать watch на уровне БД вместо коллекции. |
| **Oplog window слишком мал / Resume Token expired** | Oplog перезаписан (capped collection); токен устарел. | Ошибка `Resume token not found` / `Failed to resume` | Увеличить `oplogSizeMB` (см. [Replication](./mongodb-replication.md)); полный ресинк через новый коннектор. |
| **Sink: duplicate key error при рестарте** | At-least-once доставка + нет идемпотентности. | `E11000 duplicate key error` в логах sink task | `writemodel.strategy: ReplaceOneDefaultStrategy` (upsert по `_id`); включить `errors.tolerance=all` + DLQ. |
| **Source: память worker растёт (OOM)** | Большие документы + `publish.full.document.only=false` + много задач. | `jvm_memory_used_bytes` → max; GC pauses | `publish.full.document.only: true`; уменьшить `batch.size`; увеличить heap (`KAFKA_HEAP_OPTS=-Xmx4g`). |
| **Debezium snapshot зависает / долгий** | Большой объём данных для initial snapshot; нет индексов для фильтра. | `snapshot` task в RUNNING часами; `pg_sleep` / table scan в логах | `snapshot.mode: when_needed`; добавить индексы на фильтруемые поля; `snapshot.max.threads` (Debezium 2.x). |
| **Kafka Connect worker не стартует** | Порт 8083 занят / неверный `group.id` / нет доступа к Kafka. | `systemctl status confluent-kafka-connect`; логи | Проверить `bootstrap.servers`; уникальный `group.id`; firewall 9092. |
| **Schema Registry ошибки (Avro)** | Несовместимая схема / нет доступа к Registry. | `SerializationException` / `404 Schema not found` | Проверить `schema.registry.url`; совместимость BACKWARD; зарегистрировать схему вручную. |
| **Sink: документ не обновляется (timestamp strategy)** | `UpdateOneTimestampStrategy` требует `ts_ms` в сообщении Debezium. | Документы не обновляются, только вставляются | Использовать `ReplaceOneDefaultStrategy` или убедиться в наличии `source.ts_ms`. |
| **Source: пропуск событий при failover Primary** | Change Stream resume занимает время; `max.await.time.ms` истекает. | Лаг растёт после failover; логи `Resuming change stream` | Увеличить `max.await.time.ms` (default 1000ms); проверить `retry.timeouts` в конфиге коннектора. |

---

## Ограничения и Edge Cases

*   **Change Streams требуют Replica Set или sharded cluster:** На standalone `mongod` коннектор не работает — минимум одноузловой RS.
*   **Порядок гарантируется только в пределах partition:** Kafka сохраняет порядок записей внутри partition; при `tasks.max > 1` порядок между task'ами не гарантируется.
*   **At-least-once, не exactly-once:** Дубли возможны при рестарте; sink должен быть идемпотентным (upsert по `_id`).
*   **Cluster-wide watch:** `database`/`collection` пустые — watch на весь кластер; требует `clusterMonitor` и генерирует большой поток.
*   **Pre-image/post-image:** Для получения состояния документа *до* изменения включите `changeStreamPreAndPostImages` на коллекции (MongoDB 6.0+) и `full.document.before.change` в коннекторе.
*   **Oplog window ограничивает resume:** Resume Token валиден только пока соответствующая запись в oplog не перезаписана. При большой нагрузке/малом oplog токен может устареть за минуты — полный ресинк обязателен. См. [Replication](./mongodb-replication.md) для расчёта `oplogSizeMB`.
*   **Sharded cluster: порядок между шардами не гарантирован:** Change Stream через `mongos` мерджит события; глобальный порядок отсутствует. Для строгого порядка — коннектор на каждый шард отдельно (direct connection).
*   **Transaction awareness:** Change Streams видит операции внутри транзакции только после commit. Aborted транзакции не генерируют событий. `txnNumber` в Resume Token позволяет отличить транзакционные операции.
*   **`fullDocument: updateLookup` не атомарен:** Документ читается отдельным запросом после oplog записи; между oplog и read документ может измениться/удалиться. `null` в `fullDocument` — нормально для быстрых update/delete.
*   **Sink: нет поддержки bulk write:** MongoDB Sink Connector применяет операции по одной (ReplaceOne/UpdateOne/DeleteOne). Для высокой пропускной способности — кастомный consumer с `bulkWrite`.
*   **Debezium snapshot блокирует collection (legacy):** В старых версиях (`snapshot.mode: initial`) мог блокировать таблицы. В 2.x — неблокирующий, но требует `REPLICA IDENTITY FULL` аналога для MongoDB (не применимо, MongoDB использует Change Streams для snapshot).
*   **Avro/Protobuf Schema Evolution:** При изменении схемы документов MongoDB (новые поля, изменение типов) — обновить схему в Schema Registry с `BACKWARD` совместимостью. Source коннектор с `output.schema.infer.value=true` может генерировать несовместимые схемы.
*   **Single-threaded compression:** Kafka Connect worker сжимает/распаковывает сообщения в одном потоке. При высокой нагрузке — увеличьте `tasks.max` или используйте отдельные worker-пулы.
*   **`publish.full.document.only=true` теряет метаданные:** `operationType`, `ns`, `documentKey` не попадают в Kafka. Для аудита/debug — оставьте `false`.
*   **Connector version vs MongoDB version mismatch:** Connector 1.x для MongoDB 4.4/5.0/6.0; Connector 2.x для 6.0/7.0/8.0. Не используйте Connector 2.x с MongoDB 5.0 — ошибки API.
*   **Offset commit failures при нестабильной сети:** Если Kafka недоступна > `offset.flush.timeout.ms` — коннектор может потерять offsets и ресинка не избежать. Настройте `retries`, `retry.backoff.ms` в worker config.

---

## Лучшие практики (Best Practices)

### Архитектура и дизайн

1.  **Выбор коннектора:** MongoDB Kafka Connector — для двунаправленной интеграции (Source + Sink) и простой репликации. Debezium — для мульти-СУБД CDC пайплайнов, стандартизированного envelope, ETL в DWH/OLAP.
2.  **Source: `publish.full.document.only: true`** — уменьшает размер сообщений в 2–5×, снимает нагрузку с Kafka и network. Метаданные (`operationType`) восстанавливаются по presence/absence полей.
3.  **Sink: `ReplaceOneDefaultStrategy` (upsert по `_id`)** — единственная стратегия, гарантирующая идемпотентность при at-least-once. `InsertOneDefaultStrategy` создаёт дубли при рестарте.
4.  **Topic design:** Один топик на коллекцию (`prefix.db.collection`). Не объединяйте разные коллекции в один топик — разные схемы, разные SMT, разные retention.
5.  **Partitioning:** Для source коннектора `tasks.max` ≤ число партиций топика. Для шардированного кластера — `tasks.max` = число шардов (подключение к каждому шарду напрямую для параллелизма).

### SRE / DevOps / Production

6.  **Kafka Connect: Distributed mode только.** Standalone — для dev. Минимум 3 worker для HA. `group.id` уникален на кластер.
7.  **Internal topics replication factor = 3:** `config.storage.replication.factor=3`, `offset.storage.replication.factor=3`, `status.storage.replication.factor=3`. Иначе потеря одного брокера = потеря координации коннекторов.
8.  **DLQ для всех Sink коннекторов:** `errors.tolerance=all`, `errors.deadletterqueue.topic.name=dlq.<connector>`, `errors.deadletterqueue.context.headers.enable=true`. Регулярно мониторьте размер DLQ.
9.  **Avro/Protobuf + Schema Registry:** Обязательно для production. JSON без схемы — рецепт для data corruption при изменении полей. `key.converter=value.converter=AvroConverter`.
10. **SMT для нормализации:** `InsertField` (source cluster, timestamp), `RenameField` (`_id` → `id`), `MaskField` (PII), `RegexRouter` (topic rename для env 분리).
11. **Мониторинг лага:** Алерт при `lag > 1000` или `no new messages > 60s`. Используйте `kafka-consumer-groups --describe` или Prometheus `connect_source_task_records_produced_total`.
12. **Resume Token backup:** Для custom consumer (не Kafka Connect) — сохраняйте Resume Token в Redis/PostgreSQL каждые N сообщений. При рестарте — `resumeAfter(token)`.
13. **Oplog sizing:** `oplogSizeMB` должен покрывать максимальное допустимое downtime consumer'а + время ресинка. Минимум 24h, рекомендуется 72h+. См. [Replication](./mongodb-replication.md).
14. **Security:** SASL/SSL между Connect ↔ Kafka, Connect ↔ MongoDB. Пароли в Vault/Secrets, не в конфигах. Пользователь коннектора — минимальные привилегии (`read` + `changeStream` на целевые БД).
15. **Runbook для инцидентов:** Документируйте: как рестартнуть коннектор, как очистить зависший offset, как сделать полный ресинк (удалить коннектор + топик + offsets), контакты on-call.
16. **CI/CD валидация:** Тестируйте конфиг коннекторов в staging перед production. Проверяйте совместимость схем (Schema Registry `compatibility=BACKWARD`).
17. **Capacity planning:** Прогнозируйте throughput: `documents/sec * avg_doc_size * 2` (Kafka overhead). Планируйте диск под retention (7-30 дней) и внутренние топики Connect.
18. **Graceful shutdown:** `task.shutdown.graceful.timeout.ms=30000` — даёт task'ам завершить текущий батч и закоммитить offset перед остановкой worker'а.
19. **Version pinning:** Закрепите версии: MongoDB Server, Kafka, Kafka Connect, Connector, Debezium. Не используйте `latest` в production Docker образах.
20. **Chaos testing:** Регулярно тестируйте: kill Primary MongoDB (failover), kill Connect worker (rebalance), kill Kafka broker (ISR shrink), network partition. Проверяйте, что CDC восстанавливается без потерь.

---

## Дополнительная информация

*   **[Change Streams](./mongodb-change-streams.md)** — нативная подписка на изменения, Python/Node.js примеры, Resume Token.
*   **[Replication](./mongodb-replication.md)** — Oplog, `oplogSizeMB`, расчёт размера для CDC window.
*   **[CDC: архитектурные паттерны](../../Concepts/cdc_architectural_patterns.md)** — общая теория CDC, Debezium, Kafka Connect REST API.
*   **[Kafka Connect в production](../../Kafka/kafka_connect_production.md)** — развёртывание и эксплуатация Kafka Connect, DLQ, SMT.
*   **[Kafka: доставка гарантий](../../Kafka/delivery_guarantees.md)** — at-least-once / exactly-once семантика.
*   **[Schema Registry](../../Kafka/kafka_schema_registry.md)** — Avro/Protobuf схемы, совместимость, evolution.
*   **[Администрирование](./mongodb-administration.md)** — пользователи и роли для коннектора, привилегии `changeStream`.
*   [MongoDB Kafka Connector Docs](https://www.mongodb.com/docs/kafka-connector/current/)
*   [Debezium MongoDB Connector](https://debezium.io/documentation/reference/stable/connectors/mongodb.html)
*   [Kafka Connect REST API](https://kafka.apache.org/documentation/#connect_rest)
