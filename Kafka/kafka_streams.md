# Kafka Streams в Production

**Kafka Streams** — это библиотека для создания распределенных потоковых приложений поверх Kafka. Позволяет выполнять трансформации, агрегации и join'ы данных без внешних фреймворков.

---

## Определения

- **Stream:** Неизменяемый поток данных (KTable, KStream, GlobalKTable).
- **KStream:** Поток записей (append-only), где каждая запись независима.
- **KTable:** Таблица изменений (changelog), где каждая запись обновляет предыдущее значение по ключу.
- **GlobalKTable:** Полная копия таблицы на каждом инстансе (для broadcast join).
- **State Store:** Локальное хранилище состояния (RocksDB) для агрегаций и join'ов.
- **Changelog Topic:** Внутренний Kafka-топик для сохранения состояния State Store.
- **Windowed Operation:** Операция над временным окном (tumbling, hopping, session).
- **Exactly-Once (EOS):** Гарантия обработки ровно один раз через транзакции.
- **Interactive Queries:** REST API для запроса состояния State Store.
- **Processor Topology:** Граф обработки данных (source, processor, sink).

---

## Основные концепции

### Архитектура Kafka Streams

```
┌─────────────────────────────────────────────────────────────┐
│                    Kafka Streams Application                 │
├─────────────────────────────────────────────────────────────┤
│  Source Topic ──▶ [Processor Topology] ──▶ Sink Topic       │
│       │                   │                      │          │
│       │                   ▼                      │          │
│       │            ┌─────────────┐               │          │
│       │            │ State Store  │               │          │
│       │            │ (RocksDB)   │               │          │
│       │            └──────┬──────┘               │          │
│       │                   │                      │          │
│       │                   ▼                      │          │
│       │            Changelog Topic              │          │
│       │            (backup состояния)          │          │
│       │                                        │          │
│       └────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

### Типы операций

| Тип | Описание | Пример |
|-----|----------|--------|
| **Stateless** | Каждая запись обрабатывается независимо | `map`, `filter`, `flatMap` |
| **Stateful** | Требует хранения состояния | `aggregate`, `count`, `join`, `windowedBy` |

### Windowed Operations

| Тип окна | Описание | Пример |
|----------|----------|--------|
| **Tumbling** | Непересекающиеся окна фиксированного размера | 1-минутные агрегаты |
| **Hopping** | Пересекающиеся окна с фиксированным шагом | 5-минутное окно каждую 1 минуту |
| **Session** | Динамические окна по активности пользователя | Сессии пользователя |

### State Store и RocksDB

**State Store** — локальное хранилище состояния на каждом инстансе приложения:
- **In-memory:** Быстрый, но ограничен размером RAM
- **RocksDB:** По умолчанию, хранит данные на диске с кэшем в RAM

**Changelog Topic:**
- Автоматически создаётся для каждого State Store
- Используется для восстановления после сбоя
- Включен по умолчанию (`processing.guarantee=exactly_once_v2`)

### Exactly-Once Semantics (EOS)

Kafka Streams поддерживает EOS через транзакции:
```properties
processing.guarantee=exactly_once_v2
```

**Как работает:**
1. Чтение из source topic
2. Обработка и запись в sink topic
3. Коммит смещений — всё в одной транзакции

### Interactive Queries

Позволяет запрашивать состояние State Store через REST API:
```bash
# Получение значения по ключу
curl http://localhost:8080/state/inventory/products/123

# Получение всех ключей
curl http://localhost:8080/state/inventory/products
```

### Параллелизм и масштабирование

- **Потоки (threads):** `num.stream.threads` — количество потоков обработки
- **Партиции:** Количество партиций source topic определяет максимальный параллелизм
- **Standby реплики:** `num.standby.replicas` — для быстрого failover

---

## Практические сценарии

### Сценарий 1: Базовая настройка

`streams.properties`:
```properties
# Идентификация приложения
application.id=my-streams-app

# Bootstrap серверы
bootstrap.servers=kafka:9092

# Совместимость ключей и значений
default.key.serde=org.apache.kafka.common.serialization.Serdes$String
default.value.serde=org.apache.kafka.common.serialization.Serdes$String

# Exactly-once
processing.guarantee=exactly_once_v2

# Потоки обработки
num.stream.threads=4

# Standby реплики для failover
num.standby.replicas=1

# Кэширование
cache.max.bytes.buffering=10485760

# Commit interval
commit.interval.ms=100
```

### Сценарий 2: Простая трансформация (KStream)

```java
StreamsBuilder builder = new StreamsBuilder();

KStream<String, String> source = builder.stream("input-topic");

source.filter((key, value) -> value != null)
      .mapValues(value -> value.toUpperCase())
      .to("output-topic");

KafkaStreams streams = new KafkaStreams(builder.build(), props);
streams.start();
```

### Сценарий 3: Агрегация с Windowed KTable

```java
StreamsBuilder builder = new StreamsBuilder();

KStream<String, Long> transactions = builder.stream("transactions");

KTable<Windowed<String>, Long> hourlyTotals = transactions
    .groupByKey()
    .windowedBy(TimeWindows.ofSizeWithNoGrace(Duration.ofHours(1)))
    .aggregate(
        () -> 0L,
        (key, value, aggregate) -> aggregate + value,
        Materialized.as("hourly-totals-store")
    );

hourlyTotals.toStream()
    .to("hourly-totals-topic", Produced.with(WindowedSerdes.timeWindowedSerdeFrom(String.class), Serdes.Long()));
```

### Сценарий 4: Stream-Table Join

```java
StreamsBuilder builder = new StreamsBuilder();

KStream<String, Order> orders = builder.stream("orders");
KTable<String, User> users = builder.table("users");

KStream<String, EnrichedOrder> enriched = orders
    .selectKey((key, order) -> order.getUserId())
    .join(users, (order, user) -> new EnrichedOrder(order, user));

enriched.to("enriched-orders");
```

### Сценарий 5: Настройка RocksDB

```properties
# Кастомная конфигурация RocksDB
rocksdb.config.setter=com.myapp.CustomRocksDBConfig

# Размер кэша (по умолчанию 50MB на state store)
cache.max.bytes.buffering=104857600
```

```java
public class CustomRocksDBConfig implements RocksDBConfigSetter {
    @Override
    public void setConfig(String storeName, Options options, Map<String, Object> configs) {
        BlockBasedTableConfig tableConfig = (BlockBasedTableConfig) options.tableFormatConfig();
        tableConfig.setBlockCacheSize(100 * 1024 * 1024L); // 100MB
        tableConfig.setCacheIndexAndFilterBlocks(true);
        options.setTableFormatConfig(tableConfig);
    }
}
```

### Сценарий 6: Interactive Queries

```java
// Получение State Store
ReadOnlyKeyValueStore<String, Long> store =
    streams.store("hourly-totals-store", QueryableStoreTypes.keyValueStore());

// Запрос по ключу
Long total = store.get("product-123");

// Range scan
KeyValueIterator<String, Long> range = store.all();
```

### Сценарий 7: Мониторинг и метрики

```bash
# Метрики Kafka Streams через JMX
kafka-streams-client-metrics:
  - process-rate (записей/сек)
  - commit-rate (коммитов/сек)
  - poll-rate (poll запросов/сек)
  - task-closed-rate
  - failed-stream-threads
```

---

## Дополнительная информация

### Мониторинг Kafka Streams

Ключевые JMX-метрики:
- `kafka.streams:type=stream-metrics,client-id=([^,]+)` — общие метрики
- `kafka.streams:type=stream-task-metrics,client-id=([^,]+),task-id=([^,]+)` — метрики задач
- `kafka.streams:type=stream-processor-node-metrics` — метрики процессоров

**Алерты:**
- `failed-stream-threads > 0` → проблема с потоками обработки
- `commit-rate` падает → проблемы с транзакциями
- `process-rate` падает → проблемы с производительностью

### Чек-лист для production

- [ ] `processing.guarantee=exactly_once_v2`
- [ ] `num.stream.threads` >= количество партиций
- [ ] `num.standby.replicas=1` для быстрого failover
- [ ] Мониторинг State Store размера
- [ ] Настроен commit interval (не слишком частый)
- [ ] Interactive Queries для отладки
- [ ] Обработка ошибок в topology

### Связь с другими компонентами

- **[Гарантии доставки](./delivery_guarantees.md)** — EOS в Streams
- **[Партиционирование](./partitioning_and_balancing.md)** — параллелизм Streams
- **[Schema Registry](./kafka_schema_registry.md)** — схемы для SerDes
- **[Мониторинг](./kafka_for_monitoring.md)** — JMX-метрики

### См. также
- **[Гарантии доставки](./delivery_guarantees.md)** — EOS и транзакции
- **[Партиционирование](./partitioning_and_balancing.md)** — параллелизм
- **[Schema Registry](./kafka_schema_registry.md)** — сериализация
- **[Мониторинг Kafka](./kafka_for_monitoring.md)** — наблюдаемость
- **[Обзор Apache Kafka](./kafka_overview.md)** — введение в Streams
