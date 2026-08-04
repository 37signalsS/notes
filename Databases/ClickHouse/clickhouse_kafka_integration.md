# Интеграция ClickHouse и Apache Kafka

## Определения

**Интеграция с Apache Kafka** — механизм ClickHouse для потокового потребления данных из очередей сообщений в режиме реального времени. ClickHouse выступает в роли консьюмера (consumer), преобразуя поток событий в строки таблиц.

**Движок `Kafka`** — специализированный движок таблиц, который служит интерфейсом для чтения и (реже) записи данных в топики Kafka.

**Движок `Kafka2` (v26.7+, экспериментальный)** — обновленная версия движка, использующая ClickHouse Keeper для управления смещениями (offsets). Обеспечивает более высокую надежность и поддержку нативной семантики Exactly-once.

**ETL-конвейер (Extract, Transform, Load)** — в контексте ClickHouse это связка из движка `Kafka`, материализованного представления для трансформации и целевой таблицы `MergeTree` для хранения.

**Текущая версия:** ClickHouse 26.7 (июль 2026, Stable).

## Основные концепции

### Стандартный паттерн интеграции

Для надежной и производительной обработки данных используется связка из трех сущностей:

1.  **Таблица-очередь (`Kafka` engine):** виртуальная таблица, не хранящая данные на диске. Она отвечает за соединение с брокером и чтение сообщений.
2.  **Целевая таблица (`MergeTree`):** физическое хранилище, где данные лежат в оптимальном для аналитики виде.
3.  **Материализованное представление (MV):** фоновый процесс (триггер), который срабатывает при поступлении пачки сообщений в таблицу-очередь и перекладывает их в целевую таблицу.

### Гарантии доставки и Exactly-once (v26.7+)

ClickHouse поддерживает различные уровни гарантий доставки:

- **At-least-once (минимум один раз):** Стандартный режим. Оффсеты фиксируются в Kafka только после успешной записи в `MergeTree`. При сбоях возможны дубликаты.
- **Exactly-once (ровно один раз):** Реализуется в версии 26.7 через движок `Kafka2` и механизм **KeeperMap**.
  - **Атомные коммиты:** Оффсеты сохраняются в ClickHouse Keeper синхронно с записью данных.
  - **Дедупликация вставок:** Использование `insert_deduplicate = 1` позволяет ClickHouse игнорировать повторно отправленные блоки данных от Kafka при ретраях.

### Виртуальные столбцы

Движки Kafka предоставляют метаданные сообщений через виртуальные столбцы, которые можно использовать в `SELECT` запросах материализованных представлений.

| Столбец | Тип | Описание |
| :--- | :--- | :--- |
| `_topic` | `String` | Имя топика Kafka |
| `_key` | `String` | Ключ сообщения |
| `_offset` | `UInt64` | Смещение сообщения в партиции |
| `_partition` | `UInt64` | ID партиции |
| `_timestamp` | `Nullable(DateTime)` | Таймстамп сообщения (секунды) |
| `_timestamp_ms` | `Nullable(DateTime64(3))` | Таймстамп в миллисекундах |
| `_headers.name` | `Array(String)` | Ключи заголовков (headers) |
| `_headers.value` | `Array(String)` | Значения заголовков |
| `_error` | `String` | Текст ошибки парсинга (при `kafka_handle_error_mode = 'stream'`) |
| `_raw_message` | `String` | Исходное сообщение при ошибке парсинга |

## Практические сценарии

### Реализация конвейера с обработкой ошибок

Рекомендуется использовать **Named Collections** для безопасного хранения реквизитов доступа в `config.d/named_collections.xml`.

**1. Создание таблицы-очереди:**

```sql
CREATE TABLE kafka_queue (
    timestamp DateTime64(3),
    level String,
    message String
) ENGINE = Kafka()
SETTINGS 
    kafka_broker_list = 'host1:9092,host2:9092',
    kafka_topic_list = 'app_logs',
    kafka_group_name = 'clickhouse_consumers',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 2,
    kafka_handle_error_mode = 'stream';
```

**2. Создание целевой таблицы с дедупликацией:**

```sql
CREATE TABLE logs (
    timestamp DateTime64(3),
    level String,
    message String,
    _topic String,
    _partition UInt64,
    _offset UInt64,
    _error String
) ENGINE = ReplacingMergeTree() -- Позволяет чистить дубликаты по (topic, partition, offset)
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (_topic, _partition, _offset);
```

**3. Материализованное представление:**

```sql
CREATE MATERIALIZED VIEW logs_mv TO logs AS
SELECT 
    timestamp, level, message,
    _topic, _partition, _offset, _error
FROM kafka_queue;
```

### Интеграция с Schema Registry (Avro/Protobuf)

Для работы с бинарными форматами ClickHouse может автоматически загружать схемы из Confluent Schema Registry.

```sql
-- Пример для Avro
SETTINGS 
    kafka_format = 'Avro',
    format_avro_schema_registry_url = 'http://schema-registry:8081';
```

## Рекомендации по производительности

### Батчинг (Batching)
Kafka работает эффективно только при вставке данных большими пачками.
- **`kafka_max_block_size`**: размер блока сообщений перед записью в MergeTree (рекомендуется 65,536+).
- **`kafka_flush_interval_ms`**: максимальное время ожидания перед записью блока (рекомендуется 7,500–10,000 мс).

### Параллелизм
- Количество потребителей (`kafka_num_consumers`) должно соответствовать числу партиций в топике для максимальной утилизации.
- **`kafka_thread_per_consumer = 1`**: выделяет отдельный поток на каждого консьюмера.

## Мониторинг и диагностика

Системные таблицы для контроля состояния (требуют прав `readonly=0` или административных привилегий):

- **`system.kafka_consumers`**: Реальное состояние консьюмеров, текущие оффсеты и отставание (lag).
- **`system.kafka_log`**: История событий консьюмера (назначение партиций, ошибки, коммиты оффсетов).
- **`system.errors`**: Мониторинг частоты ошибок `CANNOT_PARSE_TEXT` или `KAFKA_ERROR`.

**Проверка отставания (Lag):**
```sql
SELECT topic, partition, last_bottomless_offset - last_committed_offset AS lag
FROM system.kafka_consumers;
```

**Прямой запрос (Direct Select):**
Для отладки без сдвига оффсетов:
`SET stream_like_engine_allow_direct_select = 1;`
`SELECT * FROM kafka_queue LIMIT 10;`

## Дополнительная информация

### Смежные темы

- Общий обзор системы — **[ClickHouse](./clickhouse.md)**.
- Интеграция с объектными хранилищами — **[Интеграция ClickHouse и S3](./clickhouse_s3_integration.md)**.
- Работа с внешними данными в PostgreSQL — **[Интеграция PostgreSQL и ClickHouse](../PostgreSQL/Integrations/clickhouse.md)**.
- Настройка репликации и Keeper — **[ClickHouse Keeper](./clickhouse.md#репликация-и-шардирование)**.
- Гарантии доставки в Kafka — **[Kafka: Гарантии доставки](../../Kafka/delivery_guarantees.md)**.
