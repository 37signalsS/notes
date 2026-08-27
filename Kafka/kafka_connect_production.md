# Kafka Connect в Production

**Kafka Connect** — это фреймворк для масштабируемой и надёжной интеграции данных между Kafka и внешними системами. В production требует тщательной настройки воркеров, обработки ошибок и мониторинга.

---

## Определения

- **Connector:** Логическая единица интеграции в Kafka Connect. Описывает что и как интегрировать.
- **Source Connector:** Читает данные из внешней системы и записывает в Kafka.
- **Sink Connector:** Читает данные из Kafka и записывает во внешнюю систему.
- **Task:** Минимальная единица работы коннектора. Каждый коннектор может иметь несколько задач для параллелизма.
- **Worker:** Процесс JVM, выполняющий коннекторы и задачи. Можеет быть standalone или distributed.
- **SMT (Single Message Transform):** Трансформация одного сообщения (фильтрация, маппинг, переименование).
- **DLQ (Dead Letter Queue):** Топик для сообщений, которые не удалось обработать.
- **Offset Management:** Хранение смещений обработанных данных в Kafka (внутренние топики).

---

## Основные концепции

### Архитектура Distributed Mode

```
┌─────────────────────────────────────────────────────────────┐
│                    Kafka Connect Cluster                     │
├─────────────────────────────────────────────────────────────┤
│  Worker 1                    Worker 2                        │
│  ┌─────────────────────┐    ┌─────────────────────┐         │
│  │ Connector A (task 0)│    │ Connector A (task 1)│         │
│  │ Connector B (task 0)│    │ Connector B (task 1)│         │
│  └─────────────────────┘    └─────────────────────┘         │
│         │                          │                        │
│         └────────────┬─────────────┘                        │
│                      ▼                                      │
│              ┌───────────────┐                              │
│              │  Kafka Cluster │ (координация)               │
│              └───────────────┘                              │
│         ┌────────────┬────────────┐                         │
│         │            │            │                         │
│         ▼            ▼            ▼                         │
│    __connect-offsets  __connect-configs  __connect-status   │
└─────────────────────────────────────────────────────────────┘
```

**Режимы работы:**
- **Standalone:** Один процесс, все коннекторы на одном воркере. Не рекомендуется для production.
- **Distributed:** Кластер воркеров с автоматическим распределением задач и ребалансировкой.

### Параметры воркеров

| Параметр | Значение по умолчанию | Рекомендуемое | Описание |
|----------|----------------------|---------------|----------|
| `group.id` | - | Уникальное для кластера | Идентификатор группы воркеров |
| `offset.flush.interval.ms` | 60000 | 60000-300000 | Интервал фиксации смещений |
| `offset.flush.timeout.ms` | 5000 | 10000-30000 | Таймаут фиксации |
| `task.shutdown.graceful.timeout.ms` | 5000 | 10000-30000 | Таймаут graceful shutdown |
| `key.converter` | JsonConverter | Для production — Avro/Protobuf | Конвертер ключей |
| `value.converter` | JsonConverter | Для production — Avro/Protobuf | Конвертер значений |

### Параметры коннекторов

| Параметр | Значение по умолчанию | Рекомендуемое | Описание |
|----------|----------------------|---------------|----------|
| `tasks.max` | 1 | 2-10 | Максимальное количество задач |
| `errors.tolerance` | none | all | Толерантность к ошибкам |
| `errors.deadletterqueue.topic.name` | - | `dlq-connector-name` | Топик DLQ |
| `errors.retry.delay.max.ms` | 60000 | 60000-300000 | Максимальная задержка повтора |
| `errors.retry.timeout` | 0 | 60000 | Таймаут повтора |
| `consumer.max.poll.records` | 500 | 1000-5000 | Максимальное количество записей в poll |

### Error Handling и DLQ

**Стратегии обработки ошибок:**

1. **`errors.tolerance=none` (по умолчанию):** Ошибка останавливает коннектор. Подходит для критичных данных.
2. **`errors.tolerance=all`:** Ошибки игнорируются или отправляются в DLQ. Подходит для непрерывной работы.

**DLQ (Dead Letter Queue):**
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Source      │────▶│ Kafka Topic │────▶│ Sink        │
│ (DB, API)   │     │             │     │ (ES, S3)    │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ DLQ Topic   │ (сообщения с ошибками)
                    │ + headers   │
                    └─────────────┘
```

**Заголовки DLQ:**
- `connect.errors.exception.class.name`
- `connect.errors.exception.message`
- `connect.errors.topic`
- `connect.errors.partition`
- `connect.errors.offset`
- `connect.errors.timestamp`

### SMT (Single Message Transform)

SMT применяются к каждому сообщению отдельно:

| Тип | Примеры | Применение |
|-----|---------|-----------|
| Фильтрация | `Filter` | Отбросить сообщения по условию |
| Маппинг | `RenameField`, `ReplaceField` | Переименовать/изменить поля |
| Маршрутизация | `RegexRouter` | Изменить имя топика по regex |
| Masking | `MaskField` | Скрыть PII данные |
| Timestamp | `InsertField`, `TimestampRouter` | Добавить/изменить timestamp |

**Цепочка SMT:**
```json
"transforms": "filter,rename,mask",
"transforms.filter.type": "org.apache.kafka.connect.transforms.Filter$Value",
"transforms.filter.filter.condition": "$[?(@.status == 'active')]",
"transforms.rename.type": "org.apache.kafka.connect.transforms.RenameField$Value",
"transforms.rename.renamed": "user_name:username"
```

---

## Практические сценарии

### Сценарий 1: Базовая настройка Distributed Worker

Файл `connect-distributed.properties`:
```properties
# Уникальный идентификатор группы воркеров
group.id=production-connect-cluster

# Внутренние топики Kafka Connect
config.storage.topic=connect-configs
offset.storage.topic=connect-offsets
status.storage.topic=connect-status

# Репликация внутренних топиков
config.storage.replication.factor=3
offset.storage.replication.factor=3
status.storage.replication.factor=3

# Конвертеры (рекомендуется Avro для production)
key.converter=io.confluent.connect.avro.AvroConverter
value.converter=io.confluent.connect.avro.AvroConverter
key.converter.schema.registry.url=http://schema-registry:8081
value.converter.schema.registry.url=http://schema-registry:8081

# Интервал фиксации смещений
offset.flush.interval.ms=60000
offset.flush.timeout.ms=30000

# Таймаут graceful shutdown
task.shutdown.graceful.timeout.ms=30000
```

### Сценарий 2: Настройка DLQ для Sink Connector

```json
{
  "name": "elasticsearch-sink",
  "config": {
    "connector.class": "io.confluent.connect.elasticsearch.ElasticsearchSinkConnector",
    "topics": "orders,users",
    "connection.url": "http://elasticsearch:9200",
    "type.name": "_doc",
    "key.ignore": "true",
    "schema.ignore": "true",
    
    "tasks.max": "4",
    
    "errors.tolerance": "all",
    "errors.deadletterqueue.topic.name": "dlq-elasticsearch-sink",
    "errors.deadletterqueue.context.headers.enable": "true",
    "errors.retry.delay.max.ms": "60000",
    "errors.retry.timeout": "300000"
  }
}
```

### Сценарий 3: Настройка параллелизма

Для высоконагруженного Source Connector (Debezium):
```json
{
  "name": "mysql-source",
  "config": {
    "connector.class": "io.debezium.connector.mysql.MySqlConnector",
    "database.hostname": "mysql",
    "database.port": "3306",
    "database.user": "debezium",
    "database.password": "dbz",
    "database.server.id": "184054",
    "database.server.name": "production-mysql",
    "database.include.list": "mydb",
    "table.include.list": "mydb.orders,mydb.users",
    
    "tasks.max": "4",
    
    "consumer.max.poll.records": "2000",
    "consumer.fetch.max.bytes": "5242880",
    
    "errors.tolerance": "all",
    "errors.deadletterqueue.topic.name": "dlq-debezium-mysql"
  }
}
```

### Сценарий 4: Использование SMT

Фильтрация и маскирование PII:
```json
{
  "name": "masked-sink",
  "config": {
    "connector.class": "io.confluent.connect.s3.S3SinkConnector",
    "topics": "users",
    
    "transforms": "maskEmail,filterTest,addTimestamp",
    
    "transforms.maskEmail.type": "org.apache.kafka.connect.transforms.MaskField$Value",
    "transforms.maskEmail.fields": "email",
    "transforms.maskEmail.replacement": "*****@*****.com",
    
    "transforms.filterTest.type": "org.apache.kafka.connect.transforms.Filter$Value",
    "transforms.filterTest.filter.condition": "$[?(@.user_type != 'test')]",
    
    "transforms.addTimestamp.type": "org.apache.kafka.connect.transforms.InsertField$Value",
    "transforms.addTimestamp.timestamp.field": "processed_at"
  }
}
```

### Сценарий 5: Мониторинг и алерты

```bash
# Проверка статуса коннектора
curl -s http://connect-worker:8083/connectors/mysql-source/status | jq .

# Проверка статуса задач
curl -s http://connect-worker:8083/connectors/mysql-source/tasks | jq .

# Перезапуск коннектора
curl -X POST http://connect-worker:8083/connectors/mysql-source/restart

# Перезапуск задачи с ошибкой
curl -X POST http://connect-worker:8083/connectors/mysql-source/tasks/0/restart
```

### Сценарий 6: Exactly-once для Sink Connectors

Для коннекторов с поддержкой EOS (JDBC, S3):
```json
{
  "name": "eos-sink",
  "config": {
    "connector.class": "io.confluent.connect.jdbc.JdbcSinkConnector",
    
    "exactly.once.support": "requested",
    "insert.mode": "upsert",
    "pk.mode": "record_key",
    "pk.fields": "id"
  }
}
```

---

## Дополнительная информация

### Мониторинг Kafka Connect

Ключевые JMX-метрики:
- `kafka.connect:type=connect-metrics,connector=([^,]+),task=([0-9]+)` — общие метрики коннектора
- `kafka.connect:type=connector-task-metrics,connector=([^,]+),task=([0-9]+),status=([a-z]+)` — метрики задач
- `kafka.connect:type=source-task-metrics,connector=([^,]+),task=([0-9]+)` — метрики source задач
- `kafka.connect:type=sink-task-metrics,connector=([^,]+),task=([0-9]+)` — метрики sink задач

**Алерты:**
- `status=FAILED` → немедленная реакция
- `batch-size` падает до 0 → проблема с источником/приёмником
- `offset-commit-failures` > 0 → проблемы с координацией

### Чек-лист для production

- [ ] Distributed mode с 3+ воркерами
- [ ] `group.id` уникален для каждого кластера
- [ ] Внутренние топики с `replication.factor=3`
- [ ] DLQ настроен для всех sink-коннекторов
- [ ] `errors.tolerance=all` для непрерывной работы
- [ ] Мониторинг задач коннекторов настроен
- [ ] Avro/Protobuf конвертеры для типобезопасности
- [ ] SMT для валидации и трансформации данных

### Связь с другими настройками

- **[Schema Registry](./kafka_schema_registry.md)** — типобезопасные схемы для коннекторов
- **[Безопасность Kafka](./kafka_overview.md)** — SASL/SSL для Connect workers
- **[Мониторинг Kafka](./kafka_for_monitoring.md)** — JMX-метрики Connect
- **[Capacity Planning](./kafka_capacity_dr.md)** — ресурсы для Connect кластера

### См. также
- **[Kafka Streams](./kafka_streams.md)** — альтернатива Connect для простых трансформаций
- **[Schema Registry](./kafka_schema_registry.md)** — схемы данных
- **[Мониторинг Kafka](./kafka_for_monitoring.md)** — наблюдаемость
- **[Обзор Apache Kafka](./kafka_overview.md)** — введение в Connect
