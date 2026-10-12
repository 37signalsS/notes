# Kafka Connect в Production

**Актуально для:** Apache Kafka 3.8.x / 3.9.x / 4.0.x

**Kafka Connect** — это распределенный фреймворк для масштабируемой и отказоустойчивой интеграции Apache Kafka с внешними источниками и приемниками данных (реляционные и NoSQL СУБД, поисковые движки, файловые хранилища). В production-окружении эксплуатация Connect требует изоляции воркеров, оптимизации протоколов ребалансировки, корректного управления внутренними топиками, настройки Dead Letter Queue (DLQ) и автоматизированного мониторинга.

---

## Определения

- **Worker:** Отдельный JVM-процесс Kafka Connect, выполняющий коннекторы и задачи. В production объединяется в распределенный кластер (`distributed mode`).
- **Connector:** Декларативная абстракция, определяющая интеграцию: конфигурацию, схему данных, источник/приемник и правила разбиения на задачи.
- **Source Connector:** Коннектор, считывающий данные из внешней системы и публикующий их в топики Kafka.
- **Sink Connector:** Коннектор, вычитывающий сообщения из топиков Kafka и записывающий их во внешнюю систему.
- **Task:** Минимальная неделимая единица параллельного исполнения. Коннектор делит объем работы на несколько задач (`tasks.max`), которые воркеры распределяют между собой.
- **Converter:** Механизм сериализации и десериализации данных между внутренним представлением Kafka Connect (`ConnectRecord`) и бинарным форматом топика (Avro, Protobuf, JSON, String).
- **SMT (Single Message Transform):** Легковесная трансформация, применяемая на лету к отдельному сообщению до записи в Kafka (Source) или до отправки в приемник (Sink).
- **DLQ (Dead Letter Queue):** Выделенный топик Kafka для изоляции «сообщений-отравителей» (poison pills) и некорректных записей без остановки работы Sink-коннектора.
- **Internal Topics:** Служебные компактифицированные топики Kafka (`connect-configs`, `connect-offsets`, `connect-status`), обеспечивающие хранение состояния и консенсус кластера Connect.
- **Incremental Cooperative Rebalancing:** Протокол координации задач (KIP-415), позволяющий перераспределять задачи между воркерами без остановки всего кластера.

---

## Основные концепции и архитектура

### Архитектура Distributed Mode

В production-среде Kafka Connect развертывается исключительно в режиме `distributed`. Кластер состоит из независимых воркеров с одинаковым `group.id`. Координация между воркерами осуществляется брокерами Kafka через стандартный Consumer Group Coordinator протокол.

```
┌────────────────────────────────────────────────────────────────────────┐
│                      Kafka Connect Cluster (group.id)                  │
├────────────────────────────────┬───────────────────────────────────────┤
│ Worker Node 1                  │ Worker Node 2                         │
│  ┌──────────────────────────┐  │  ┌──────────────────────────┐         │
│  │ Connector A (Leader)     │  │  │ Connector B (Follower)   │         │
│  │ ├─ Task A-0              │  │  │ ├─ Task A-1              │         │
│  │ └─ Task B-0              │  │  │ └─ Task B-1              │         │
│  └──────────────────────────┘  │  └──────────────────────────┘         │
│         │ REST API (8083)      │         │ REST API (8083)             │
└─────────┼──────────────────────┴─────────┼─────────────────────────────┘
          │                                │
          └───────────────┬────────────────┘
                          ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Kafka Cluster (Brokers)                         │
├────────────────────────────────────────────────────────────────────────┤
│  Group Coordinator (выбор лидера воркеров и назначение задач)           │
│                                                                        │
│  Внутренние топики (хранение состояния и конфигураций):                │
│  ├── __connect-configs   (cleanup.policy=compact, partitions=1)        │
│  ├── __connect-offsets   (cleanup.policy=compact, partitions=25)       │
│  └── __connect-status    (cleanup.policy=compact, partitions=5)        │
└────────────────────────────────────────────────────────────────────────┘
```

**Принцип работы лидера:**
Один из воркеров группы назначается лидером (Leader Worker). Лидер считывает топик `config.storage.topic`, вычисляет оптимальное распределение задач (`Connector` и `Task`) между всеми зарегистрированными воркерами и отправляет план координатору группы. При выходе лидера из строя оставшиеся воркеры мгновенно выбирают нового лидера.

### Внутренние служебные топики

Кластер Connect не требует внешних хранилищ типа ZooKeeper или etcd. Все состояние сохраняется во внутренних топиках Kafka:

| Топик | Конфигурационный параметр | Партиции | Cleanup Policy | Репликация в Prod | Назначение |
|---|---|---|---|---|---|
| **Configs** | `config.storage.topic` | **Строго 1** | `compact` | 3 (`min.insync=2`) | Хранение версий конфигураций коннекторов. Одиночная партиция гарантирует строгий порядок обновлений. |
| **Offsets** | `offset.storage.topic` | 25–50 | `compact` | 3 (`min.insync=2`) | Смещения Source-коннекторов (например, LSN в PostgreSQL, binlog позиция в MySQL) и internal commit offsets. |
| **Status** | `status.storage.topic` | 5–10 | `compact` | 3 (`min.insync=2`) | Текущие статусы коннекторов и задач (`RUNNING`, `FAILED`, `PAUSED`, `STOPPED`) и трассировки исключений. |

> [!IMPORTANT]
> Параметр `config.storage.topic` обязан иметь ровно 1 партицию. Увеличение числа партиций для топика конфигураций приведет к нарушению консистентности и падению воркеров Connect.

### Протоколы ребалансировки: Eager vs Incremental Cooperative

1. **Eager Rebalancing (`connect.protocol=eager` / `EagerAssignor`):**
   - Устаревший протокол. При добавлении нового воркера, перезапуске ноды или смене конфигурации **все** работающие коннекторы и задачи на всех воркерах полностью останавливаются (эффект «stop-the-world»).
   - Вызывает скачки задержки (lag spikes) и всплески сетевого трафика.
2. **Incremental Cooperative Rebalancing (`connect.protocol=sessioned` / `IncrementalCooperativeAssignor`):**
   - Протокол по умолчанию начиная с Kafka 2.4+.
   - При ребалансировке останавливаются и перемещаются только те задачи, которые необходимо перенести на другой воркер. Задачи, остающиеся на текущих нодах, продолжают непрерывно обрабатывать данные.
   - Минимизирует время недоступности при rolling restart кластера воркеров за счет параметра `scheduled.rebalance.max.delay.ms` (по умолчанию `300000` мс — 5 минут). Воркер ожидает возвращения перезагружаемого узла, не начиная масштабную миграцию задач.

### Жизненный цикл коннекторов и задач

Состояния объекта (Connector и Task) в Kafka Connect:
- `UNASSIGNED`: Воркер зарегистрировал объект, но задача еще не распределена планировщиком.
- `RUNNING`: Задача активно считывает или записывает данные.
- `PAUSED`: Обработка приостановлена через REST API. Назначение задач за воркерами сохраняется, но потоки ввода-вывода заблокированы.
- `STOPPED`: Введено в Kafka 3.5 (KIP-875). Все задачи полностью остановлены и выгружены из памяти воркеров, освобождены сокеты и внешние соединения, но конфигурация и смещения сохраняются. Требуется для безопасной модификации и сброса смещений.
- `FAILED`: Задача завершилась аварийно из-за необработанного исключения. Требует ручного или автоматизированного вмешательства через REST API.

### Модель данных и конвертеры (Converters)

Kafka Connect преобразует сообщения в два этапа:
1. **Source:** Внешняя система → `ConnectRecord` (внутренняя типизированная структура данных со схемой) → `Converter` → сериализованные байты в топик Kafka.
2. **Sink:** Байты из топика Kafka → `Converter` → `ConnectRecord` со схемой → Внешняя система.

Используются раздельные конвертеры для ключа и значения:
- `key.converter`: Формат ключа записи.
- `value.converter`: Формат тела (payload) записи.
- `header.converter`: Формат метаданных (заголовков). По умолчанию `org.apache.kafka.connect.storage.SimpleHeaderConverter`.

В production для поддержания эволюции схем и компактности сообщений рекомендуется связка `io.confluent.connect.avro.AvroConverter` или `ProtobufConverter` со Schema Registry. При использовании `JsonConverter` без реестра схем обязательно отключение внедрения схем (`schemas.enable=false`), иначе объем накладных расходов вырастает в 10–20 раз за счет передачи JSON Schema в каждом сообщении.

### Изоляция плагинов и загрузчик классов (Plugin Classloading)

Kafka Connect изолирует классы каждого плагина коннектора в отдельном дочернем загрузчике классов (Isolated ClassLoader):
- Каталоги плагинов перечисляются в параметре `plugin.path`.
- Каждый плагин (JAR-файл или директория с зависимостями) должен лежать в отдельной поддиректории:
  `/opt/kafka/plugins/debezium-postgres/`
  `/opt/kafka/plugins/confluent-kafka-connect-jdbc/`
- Загрузчик классов сначала ищет зависимости внутри поддиректории плагина, исключая конфликты версий (например, разные версии библиотек Jackson, Guava или драйверов JDBC между коннекторами и ядром Kafka).

---

## Практические сценарии и конфигурация

### Сценарий 1: Конфигурация распределенного воркера (Production)

Файл `/etc/kafka/connect-distributed.properties` для развертывания на выделенных серверах или ВМ с шифрованием и аутентификацией:

```properties
# ------------------------------------------------------------------------------
# 1. Параметры кластера и координации
# ------------------------------------------------------------------------------
group.id=connect-cluster-prod
bootstrap.servers=kafka-broker-01:9092,kafka-broker-02:9092,kafka-broker-03:9092

# ------------------------------------------------------------------------------
# 2. Внутренние служебные топики (RF=3, min.insync.replicas=2)
# ------------------------------------------------------------------------------
config.storage.topic=prod-connect-configs
config.storage.replication.factor=3

offset.storage.topic=prod-connect-offsets
offset.storage.replication.factor=3
offset.storage.partitions=25

status.storage.topic=prod-connect-status
status.storage.replication.factor=3
status.storage.partitions=5

# ------------------------------------------------------------------------------
# 3. Конвертеры по умолчанию (Avro со Schema Registry)
# ------------------------------------------------------------------------------
key.converter=io.confluent.connect.avro.AvroConverter
key.converter.schema.registry.url=http://schema-registry.internal:8081
value.converter=io.confluent.connect.avro.AvroConverter
value.converter.schema.registry.url=http://schema-registry.internal:8081

# ------------------------------------------------------------------------------
# 4. REST API воркера и сетевые интерфейсы
# ------------------------------------------------------------------------------
listeners=http://0.0.0.0:8083
rest.advertised.listener=http
rest.advertised.host.name=connect-node-01.internal
rest.advertised.port=8083

# ------------------------------------------------------------------------------
# 5. Изоляция плагинов и пути загрузки
# ------------------------------------------------------------------------------
plugin.path=/opt/kafka/plugins

# ------------------------------------------------------------------------------
# 6. Надежность и протокол ребалансировки
# ------------------------------------------------------------------------------
# Включение протокола Incremental Cooperative Rebalancing
connect.protocol=sessioned

# Задержка ребалансировки при плановом rolling restart (5 минут)
scheduled.rebalance.max.delay.ms=300000

# Интервалы фиксации смещений
offset.flush.interval.ms=60000
offset.flush.timeout.ms=30000

# Таймаут ожидания корректного завершения задач при перезапуске
task.shutdown.graceful.timeout.ms=30000

# Разрешение переопределения конфигураций Kafka-клиентов на уровне коннекторов
connector.client.config.override.policy=All

# ------------------------------------------------------------------------------
# 7. Безопасность взаимодействия с брокерами Kafka (SASL_PLAINTEXT / SASL_SSL)
# ------------------------------------------------------------------------------
# security.protocol=SASL_PLAINTEXT
# sasl.mechanism=SCRAM-SHA-512
# sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required \
#   username="connect_worker" \
#   password="worker_secret_password";
```

### Сценарий 2: Systemd Unit и тюнинг JVM воркера

Файл `/etc/systemd/system/kafka-connect.service`:

```ini
[Unit]
Description=Apache Kafka Connect Distributed Worker
Documentation=https://kafka.apache.org/documentation/#connect
After=network.target network-online.target

[Service]
Type=simple
User=kafka
Group=kafka
Environment="KAFKA_LOG4J_OPTS=-Dlog4j.configuration=file:/etc/kafka/connect-log4j.properties"
Environment="KAFKA_HEAP_OPTS=-Xms4g -Xmx4g -XX:+UseG1GC -XX:MaxGCPauseMillis=20 -XX:InitiatingHeapOccupancyPercent=45 -XX:G1ReservePercent=15 -XX:MinMetaspaceFreeRatio=50 -XX:MaxMetaspaceFreeRatio=80"
Environment="KAFKA_JMX_OPTS=-Dcom.sun.management.jmxremote=true -Dcom.sun.management.jmxremote.authenticate=false -Dcom.sun.management.jmxremote.ssl=false -Djava.rmi.server.hostname=connect-node-01.internal -Dcom.sun.management.jmxremote.port=9999 -Dcom.sun.management.jmxremote.rmi.port=9999"
ExecStart=/opt/kafka/bin/connect-distributed.sh /etc/kafka/connect-distributed.properties
Restart=on-failure
RestartSec=10s
LimitNOFILE=65536
LimitNPROC=32768
TimeoutStopSec=60s

[Install]
WantedBy=multi-user.target
```

Применение и запуск:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kafka-connect.service
sudo systemctl status kafka-connect.service
# → Active: active (running) since Mon 2026-10-12 14:10:00 MSK; 10s ago
```

### Сценарий 3: Установка и проверка плагинов коннекторов

Установка плагинов выполняется в изолированные каталоги:
```bash
# 1. Создание каталога плагинов
sudo mkdir -p /opt/kafka/plugins/debezium-postgres
sudo mkdir -p /opt/kafka/plugins/kafka-connect-jdbc

# 2. Распаковка плагина (пример: Debezium PostgreSQL)
sudo tar -xzf /tmp/debezium-connector-postgres-2.7.3.Final-plugin.tar.gz -C /opt/kafka/plugins/debezium-postgres/

# 3. Назначение прав доступа
sudo chown -R kafka:kafka /opt/kafka/plugins

# 4. Проверка доступности плагинов через REST API воркера
curl -s http://127.0.0.1:8083/connector-plugins | jq -r '.[].class' | grep -E "Postgres|Jdbc"
# → io.debezium.connector.postgresql.PostgresConnector
# → io.confluent.connect.jdbc.JdbcSourceConnector
# → io.confluent.connect.jdbc.JdbcSinkConnector
```

### Сценарий 4: Production Source Connector (Debezium PostgreSQL CDC)

Конфигурация захвата изменений из PostgreSQL с использованием публикации `pgoutput` и изоляцией нагрузки:

```json
{
  "name": "pg-orders-cdc-source",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "tasks.max": "1",
    
    "plugin.name": "pgoutput",
    "database.hostname": "postgres-master.internal",
    "database.port": "5432",
    "database.user": "debezium_cdc",
    "database.password": "secure_cdc_pass",
    "database.dbname": "shop_db",
    "database.server.name": "prod_shop",
    "topic.prefix": "prod_shop",
    
    "table.include.list": "public.orders,public.order_items",
    "publication.name": "dbz_orders_publication",
    "publication.autocreate.mode": "filtered",
    "slot.name": "debezium_orders_slot",
    "slot.drop.on.stop": "false",
    
    "snapshot.mode": "initial",
    "snapshot.locking.mode": "none",
    "max.batch.size": "4096",
    "max.queue.size": "16384",
    "poll.interval.ms": "500",
    
    "key.converter": "io.confluent.connect.avro.AvroConverter",
    "key.converter.schema.registry.url": "http://schema-registry.internal:8081",
    "value.converter": "io.confluent.connect.avro.AvroConverter",
    "value.converter.schema.registry.url": "http://schema-registry.internal:8081",
    
    "tombstones.on.delete": "true",
    "decimal.handling.mode": "double",
    "heartbeat.interval.ms": "10000",
    "heartbeat.topics.prefix": "__debezium-heartbeat"
  }
}
```

> [!NOTE]
> Большинство Source CDC коннекторов (Debezium) поддерживают строго `tasks.max=1`, так как журнал транзакций СУБД (WAL/binlog) должен читаться строго последовательно в один поток для гарантии порядка событий.

### Сценарий 5: Production Sink Connector с DLQ и ретраями

Конфигурация JDBC Sink Connector для записи данных в PostgreSQL с включенной очередью сбойных сообщений (Dead Letter Queue):

```json
{
  "name": "pg-orders-jdbc-sink",
  "config": {
    "connector.class": "io.confluent.connect.jdbc.JdbcSinkConnector",
    "tasks.max": "4",
    "topics": "prod_shop.public.orders",
    
    "connection.url": "jdbc:postgresql://postgres-replica.internal:5432/analytics_db",
    "connection.user": "connect_sink_user",
    "connection.password": "sink_secure_password",
    "insert.mode": "upsert",
    "pk.mode": "record_key",
    "pk.fields": "order_id",
    "auto.create": "true",
    "auto.evolve": "true",
    "batch.size": "3000",
    
    "key.converter": "io.confluent.connect.avro.AvroConverter",
    "key.converter.schema.registry.url": "http://schema-registry.internal:8081",
    "value.converter": "io.confluent.connect.avro.AvroConverter",
    "value.converter.schema.registry.url": "http://schema-registry.internal:8081",
    
    "errors.tolerance": "all",
    "errors.log.enable": "true",
    "errors.log.include.messages": "true",
    
    "errors.retry.timeout": "60000",
    "errors.retry.delay.max.ms": "5000",
    
    "errors.deadletterqueue.topic.name": "dlq-pg-orders-sink",
    "errors.deadletterqueue.topic.replication.factor": "3",
    "errors.deadletterqueue.context.headers.enable": "true"
  }
}
```

**Анализ заголовков в топике DLQ:**
При попадании записи в DLQ коннектор записывает системные метаданные в заголовки Kafka сообщения:
- `connect.errors.exception.class.name`: Имя Java-класса исключения (например, `org.postgresql.util.PSQLException`).
- `connect.errors.exception.message`: Текст ошибки СУБД или конвертера.
- `connect.errors.topic`: Исходный топик.
- `connect.errors.partition`: Исходная партиция.
- `connect.errors.offset`: Смещение сбойной записи.

### Сценарий 6: Конвейер SMT с предикатами

Single Message Transforms выполняются последовательно. Предикаты (Predicates) позволяют применять трансформацию только к тем сообщениям, которые соответствуют условию:

```json
{
  "name": "filtered-masked-sink",
  "config": {
    "connector.class": "io.confluent.connect.jdbc.JdbcSinkConnector",
    "tasks.max": "2",
    "topics": "customer-events",
    
    "predicates": "isCustomerActive",
    "predicates.isCustomerActive.type": "org.apache.kafka.connect.transforms.predicates.RecordIsTombstone",
    
    "transforms": "routeByCountry,maskCard,dropTombstones",
    
    "transforms.routeByCountry.type": "org.apache.kafka.connect.transforms.RegexRouter",
    "transforms.routeByCountry.regex": "customer-events",
    "transforms.routeByCountry.replacement": "sink_customer_events_v1",
    
    "transforms.maskCard.type": "org.apache.kafka.connect.transforms.MaskField$Value",
    "transforms.maskCard.fields": "card_number",
    "transforms.maskCard.replacement": "XXXX-XXXX-XXXX-0000",
    
    "transforms.dropTombstones.type": "org.apache.kafka.connect.transforms.Filter",
    "transforms.dropTombstones.predicate": "isCustomerActive",
    "transforms.dropTombstones.negate": "false"
  }
}
```

### Сценарий 7: Динамическое управление смещениями (KIP-875)

В Kafka 3.5+ добавлена возможность чтения, модификации и сброса офсетов коннекторов через REST API без прямого редактирования топика `connect-offsets`.

**Алгоритм сброса офсетов для перечитывания данных (Replay):**
```bash
# 1. Остановка коннектора (перевод в состояние STOPPED)
curl -s -X PUT http://127.0.0.1:8083/connectors/pg-orders-jdbc-sink/stop
# → HTTP/1.1 204 No Content

# 2. Проверка текущих смещений
curl -s http://127.0.0.1:8083/connectors/pg-orders-jdbc-sink/offsets | jq .
# → {
# →   "offsets": [
# →     {
# →       "partition": {
# →         "kafka_topic": "prod_shop.public.orders",
# →         "kafka_partition": 0
# →       },
# →       "offset": {
# →         "kafka_offset": 1420550
# →       }
# →     }
# →   ]
# → }

# 3. Полный сброс смещений (коннектор начнет чтение согласно auto.offset.reset)
curl -s -X DELETE http://127.0.0.1:8083/connectors/pg-orders-jdbc-sink/offsets | jq .
# → {
# →   "message": "The offsets for connector pg-orders-jdbc-sink have been reset."
# → }

# 4. Возобновление работы коннектора
curl -s -X PUT http://127.0.0.1:8083/connectors/pg-orders-jdbc-sink/resume
# → HTTP/1.1 204 No Content
```

---

## Операции и администрирование через REST API

Kafka Connect предоставляет HTTP REST API (по умолчанию порт `8083`) для мониторинга, управления жизненным циклом и динамической настройки.

### Справочник REST API эндпоинтов

| HTTP Метод | URL Путь | Назначение |
|---|---|---|
| `GET` | `/` | Информация о кластере воркеров, версия Kafka, commit id и `kafka_cluster_id`. |
| `GET` | `/connector-plugins` | Список зарегистрированных плагинов в `plugin.path`. |
| `PUT` | `/connector-plugins/{plugin}/config/validate` | Валидация конфигурации без создания коннектора. |
| `GET` | `/connectors` | Список имен всех зарегистрированных коннекторов. |
| `POST` | `/connectors` | Создание нового коннектора (тело: JSON с `name` и `config`). |
| `GET` | `/connectors/{name}` | Получение информации о коннекторе и текущей конфигурации. |
| `GET` | `/connectors/{name}/config` | Получение только словаря конфигурации коннектора. |
| `PUT` | `/connectors/{name}/config` | Обновление конфигурации коннектора. |
| `GET` | `/connectors/{name}/status` | Текущий статус коннектора и всех его задач (`tasks`). |
| `POST` | `/connectors/{name}/restart` | Перезапуск коннектора. Параметры: `includeTasks=true`, `onlyFailed=true`. |
| `POST` | `/connectors/{name}/tasks/{id}/restart` | Принудительный перезапуск конкретной сбойной задачи. |
| `PUT` | `/connectors/{name}/pause` | Приостановка обработки (задачи остаются назначенными). |
| `PUT` | `/connectors/{name}/resume` | Возобновление обработки после pause или stop. |
| `PUT` | `/connectors/{name}/stop` | Полная остановка и выгрузка задач из памяти (Kafka 3.5+). |
| `GET` | `/connectors/{name}/offsets` | Получение текущих зафиксированных смещений коннектора. |
| `PATCH`| `/connectors/{name}/offsets` | Ручная модификация смещений коннектора в состоянии STOPPED. |
| `DELETE`| `/connectors/{name}/offsets`| Полный сброс смещений коннектора в состоянии STOPPED. |
| `DELETE`| `/connectors/{name}` | Полное удаление коннектора. |
| `GET` | `/admin/loggers` | Список текущих логгеров и уровней логирования. |
| `PUT` | `/admin/loggers/{logger}` | Динамическое изменение уровня логирования (`DEBUG`, `INFO`). |

### Примеры команд администрирования

#### 1. Проверка состояния кластера и установленных плагинов

```bash
# Проверка версии и подключения к брокерам
curl -s http://127.0.0.1:8083/ | jq .
# → {
# →   "version": "3.9.0",
# →   "commit": "c47945d8b7654b42",
# →   "kafka_cluster_id": "9hBvXZqTR4S3JtW5y_12xA"
# → }

# Валидация конфигурации коннектора перед развертыванием
curl -s -X PUT http://127.0.0.1:8083/connector-plugins/PostgresConnector/config/validate \
  -H "Content-Type: application/json" \
  -d '{"connector.class":"io.debezium.connector.postgresql.PostgresConnector"}' | jq .error_count
# → 5
```

#### 2. Создание или обновление коннектора

```bash
# Идемпотентное создание/обновление коннектора через PUT /config
curl -s -X PUT http://127.0.0.1:8083/connectors/pg-orders-jdbc-sink/config \
  -H "Content-Type: application/json" \
  -d @sink-config.json | jq .name
# → "pg-orders-jdbc-sink"
```

#### 3. Мониторинг статуса коннектора и задач

```bash
curl -s http://127.0.0.1:8083/connectors/pg-orders-jdbc-sink/status | jq .
# → {
# →   "name": "pg-orders-jdbc-sink",
# →   "connector": {
# →     "state": "RUNNING",
# →     "worker_id": "connect-node-01.internal:8083"
# →   },
# →   "tasks": [
# →     {
# →       "id": 0,
# →       "state": "RUNNING",
# →       "worker_id": "connect-node-01.internal:8083"
# →     },
# →     {
# →       "id": 1,
# →       "state": "FAILED",
# →       "worker_id": "connect-node-02.internal:8083",
# →       "trace": "org.apache.kafka.connect.errors.ConnectException: Connection refused..."
# →     }
# →   ],
# →   "type": "sink"
# → }
```

#### 4. Интеллектуальный перезапуск упавших задач (KIP-745)

```bash
# Перезапуск ТОЛЬКО тех задач, которые находятся в состоянии FAILED
curl -s -X POST "http://127.0.0.1:8083/connectors/pg-orders-jdbc-sink/restart?includeTasks=true&onlyFailed=true"
# → HTTP/1.1 202 Accepted
```

#### 5. Динамическое изменение уровня логирования в рантайме

```bash
# Включение DEBUG логирования для конкретного пакета коннектора без перезапуска воркера
curl -s -X PUT http://127.0.0.1:8083/admin/loggers/io.debezium.connector.postgresql \
  -H "Content-Type: application/json" \
  -d '{"level": "DEBUG"}' | jq .
# → [
# →   "io.debezium.connector.postgresql",
# →   "io.debezium.connector.postgresql.PostgresConnector"
# → ]
```

---

## Troubleshooting: диагностика и устранение неисправностей

### Матрица инцидентов

| Симптом / Ошибка | Вероятная причина | Диагностика | Решение |
|---|---|---|---|
| Постоянные ребалансировки (**Rebalance Storm**), воркеры циклически отключаются | Превышение `max.poll.interval.ms` из-за тяжелых батчей в Sink; сетевой джиттер между воркерами | Проверить логи: `JoinGroup failed`, `CommitFailedException` | Увеличить `scheduled.rebalance.max.delay.ms`; уменьшить `max.poll.records` у consumer; настроить G1GC |
| Задача переходит в статус `FAILED` с `ConnectException` | Сетевой сбой внешней СУБД; недоступность хоста; исчерпание пула соединений | `GET /connectors/{name}/status` поле `trace` | Проверить connectivity (`nc -zv host port`); настроить `errors.retry.timeout`; выполнить `restart?onlyFailed=true` |
| `OffsetCommitTimeoutException` во время работы воркера | Слишком долгий flush смещений; перегрузка внутренних топиков Kafka | Логи воркера: `WorkerSinkTask: Commit of offsets timed out` | Увеличить `offset.flush.timeout.ms=60000`; проверить `UnderReplicatedPartitions` для `connect-offsets` |
| `PluginNotFoundException` или `ClassNotFoundException` при запуске коннектора | Плагин не распакован в `plugin.path`; отсутствует структура каталогов; неверные права доступа | `curl localhost:8083/connector-plugins`; проверить права на директорию | Разместить каждый плагин в отдельной поддиректории; `chmod -R 755 /opt/kafka/plugins`; перезапустить воркер |
| Падение воркера с `java.lang.OutOfMemoryError: Java heap space` | Чрезмерно большой `max.batch.size`; накопление сообщений в буферах SMT; утечка памяти драйвера JDBC | `jstat -gcutil <pid>`; анализ heap dump (`-XX:+HeapDumpOnOutOfMemoryError`) | Выделить heap (`-Xmx4g`..`-Xmx8g`); уменьшить `batch.size` и `max.queue.size`; изолировать коннекторы по группам |
| `DataException: Converting byte[] to Kafka Connect data failed due to serialization error` | Несоответствие конвертера: попытка прочитать Avro через JsonConverter или неверный URL Schema Registry | Логи задачи; проверить заголовок magic byte (`0x00`) в бинарном сообщении | Настроить правильный `key.converter`/`value.converter` и `schema.registry.url` |

### Сценарии локализации и решения проблем

#### 1. Устранение шторма ребалансировок (Rebalance Storm)

**Диагностика:**
В логах воркеров (`/var/log/kafka/connect.log`) регистрируются частые сообщения:
```text
[2026-10-12 14:12:00,102] INFO [Worker clientId=connect-1, groupId=connect-cluster-prod] (Rebalance) JoinGroup failed with org.apache.kafka.common.errors.MemberIdRequiredException
[2026-10-12 14:12:15,340] WARN [Worker clientId=connect-1, groupId=connect-cluster-prod] (Rebalance) Displaced task pg-orders-jdbc-sink-0 due to rebalance
```

**Решение:**
1. Проверьте, что в конфигурации воркеров включен протокол `sessioned`:
   ```properties
   connect.protocol=sessioned
   scheduled.rebalance.max.delay.ms=300000
   ```
2. Если Sink-коннектор выполняет длительную пакетную запись в СУБД, консьюмер не успевает вызвать `poll()` в пределах таймаута:
   ```json
   "consumer.override.max.poll.interval.ms": "300000",
   "consumer.override.max.poll.records": "500"
   ```

#### 2. Диагностика сообщений-отравителей (Poison Pills) без DLQ

**Симптом:**
Sink-коннектор внезапно падает с ошибкой десериализации, блокируя всю партицию топика:
```text
org.apache.kafka.connect.errors.DataException: Failed to deserialize data for topic orders to Avro
Caused by: org.apache.kafka.common.errors.SerializationException: Error deserializing Avro message for id -1
```

**Решение:**
1. Не удаляя коннектор, обновите его конфигурацию, включив DLQ и пропуск ошибок:
   ```bash
   curl -s -X PUT http://127.0.0.1:8083/connectors/pg-orders-jdbc-sink/config \
     -H "Content-Type: application/json" \
     -d '{
       ...
       "errors.tolerance": "all",
       "errors.deadletterqueue.topic.name": "dlq-pg-orders-sink",
       "errors.deadletterqueue.context.headers.enable": "true"
     }'
   ```
2. Выполните рестарт упавших задач:
   ```bash
   curl -s -X POST "http://127.0.0.1:8083/connectors/pg-orders-jdbc-sink/restart?includeTasks=true&onlyFailed=true"
   ```
3. Вычитайте поврежденное сообщение из DLQ топика с выводом заголовков:
   ```bash
   kafka-console-consumer.sh --bootstrap-server kafka-broker-01:9092 \
     --topic dlq-pg-orders-sink \
     --from-beginning \
     --property print.headers=true \
     --max-messages 1
   # → connect.errors.topic:orders,connect.errors.partition:2,connect.errors.offset:410294	{"raw_corrupted_payload"}
   ```

---

## Best Practices: надежность, производительность и безопасность

### 1. Доменная изоляция воркеров (Noisy Neighbor Isolation)

В крупных production-системах категорически не рекомендуется запускать все коннекторы в одном общем кластере Kafka Connect:
- **Выделенный CDC Cluster (`group.id=connect-cdc-prod`):** Только Source-коннекторы (Debezium). Высокая утилизация памяти под структуры журналов транзакций, критичность к сохранению последовательности.
- **Выделенный Sink Cluster (`group.id=connect-sink-prod`):** Коннекторы записи в СУБД, Elasticsearch и хранилища данных. Нагрузка связана с сетевыми батчами и параллелизмом консьюмеров.
- **Преимущество:** Сбой или длительная ребалансировка одного тяжелого аналитического Sink-коннектора не останавливает репликацию критичных транзакционных CDC-потоков.

### 2. Эксплуатация внутренних топиков

- **Компактификация:** Убедитесь, что топики `connect-configs`, `connect-offsets` и `connect-status` имеют параметр `cleanup.policy=compact`. Удаление старых записей по времени (`delete`) приведет к потере смещений и конфигураций.
- **Фактор репликации:** Всегда `replication.factor=3` и `min.insync.replicas=2`. Потеря внутреннего топика эквивалентна потере метаданных всего кластера.

### 3. Тюнинг ресурсов и JVM

- **Размер кучи (Heap):** Стандартное рекомендуемое значение: `4GB`–`8GB`. Использование кучи свыше 16GB не рекомендуется — эффективнее горизонтально масштабировать количество воркеров.
- **Сборщик мусора:** Использовать OpenJDK 17/21 с `G1GC`:
  `-XX:+UseG1GC -XX:MaxGCPauseMillis=20 -XX:InitiatingHeapOccupancyPercent=45`
- **Процессорные ресурсы:** Рассчитывать количество задач на воркер: суммарное число активных задач (`tasks.max`) на ноде не должно превышать `(CPU Cores * 2)`.

### 4. Безопасность и разграничение доступа

- **Сетевая изоляция REST API:** По умолчанию REST API Connect не имеет встроенной аутентификации. В production-контуре:
  1. Биндить listener на внутренний IP интерфейс (`rest.advertised.host.name`).
  2. Устанавливать перед портом `8083` reverse-proxy (Nginx / HAProxy) с включенным mTLS или Basic/Token-аутентификацией.
- **Секреты в конфигурациях:** Использовать механизм `config.providers` (например, `FileConfigProvider` или `DirectoryConfigProvider`) для исключения открытых паролей из JSON конфигураций коннекторов:
  ```properties
  config.providers=file
  config.providers.file.class=org.apache.kafka.common.config.provider.FileConfigProvider
  ```
  В конфигурации коннектора:
  `"database.password": "${file:/etc/kafka/secrets.properties:db_password}"`

### 5. Метрики мониторинга и алертинг SRE

Сбор метрик настраивается через **Prometheus JMX Exporter** (порт 9999 или отдельный HTTP endpoint).

**Ключевые метрики для алертинга:**

| Метрика JMX / Prometheus | Тип | Порог алерта | Значение и действие |
|---|---|---|---|
| `kafka_connect_connector_task_metrics_status{status="failed"}` | Gauge | `> 0` | **Критический алерт:** Задача упала и прекратила обработку. Требуется автоматический рестарт или разбор стектрейса. |
| `kafka_connect_worker_metrics_connector_count` | Gauge | Резкое падение | Отключение коннектора от воркера при сбое узла. |
| `kafka_connect_sink_task_metrics_sink_record_read_rate` | Rate | Падение до 0 при наличии данных в топике | Зависание консьюмера или сетевой таймаут к целевой системе. |
| `kafka_connect_source_task_metrics_source_record_poll_rate` | Rate | Падение до 0 при наличии активности в источнике | Обрыв сессии к БД, зависание replication slot. |
| `kafka_connect_worker_metrics_rebalance_latency_ms` | Gauge | `> 30000` | Длительная ребалансировка. Проверить `scheduled.rebalance.max.delay.ms` и GC-паузы. |
| `kafka_connect_worker_metrics_task_startup_failure_percentage` | Gauge | `> 0` | Ошибки инициализации задач при старте воркера. |

---

## Дополнительная информация

### Связанные руководства в базе знаний

- **[Обзор Apache Kafka](./kafka_overview.md)** — архитектура кластера брокеров, контроллеры KRaft, группы консьюмеров.
- **[Kafka Schema Registry](./kafka_schema_registry.md)** — управление схемами Avro/Protobuf и совместимость структур для конвертеров.
- **[JVM и Garbage Collection Тюнинг для Kafka](./kafka_jvm_gc_tuning.md)** — оптимизация параметров G1GC, паузы сборщика и флаги памяти.
- **[Тюнинг ОС Linux для Apache Kafka](./kafka_os_tuning.md)** — системные параметры ядра, `sysctl`, дескрипторы файлов и дисковый ввод-вывод.
- **[Мониторинг Apache Kafka](./kafka_for_monitoring.md)** — архитектура наблюдаемости, сбор метрик JMX и дашборды.
- **[Гарантии доставки сообщений](./delivery_guarantees.md)** — семантика At-least-once, At-most-once и Exactly-once при интеграции систем.
- **[Troubleshooting Playbook для Apache Kafka](./kafka_troubleshooting_playbook.md)** — общий алгоритм локализации сетевых и брокерных сбоев.
- **[Strimzi Kafka Operator](./strimzi_kafka_operator.md)** — декларативное управление ресурсами `KafkaConnect` и `KafkaConnector` в среде Kubernetes.
