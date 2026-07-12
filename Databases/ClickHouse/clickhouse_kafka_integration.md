# Интеграция ClickHouse и Apache Kafka

## Обзор

Интеграция с **Apache Kafka** позволяет ClickHouse работать в режиме реального времени, потребляя потоки событий непосредственно из шины данных. Это стандартный способ реализации аналитики реального времени и обработки логов.

## Стандартный паттерн интеграции

Для надежного и производительного чтения данных из Kafka используется связка из трех сущностей:

1.  **Таблица с движком `Kafka`:** виртуальный "проводник", который подключается к Kafka и считывает сообщения.
2.  **Целевая таблица (`MergeTree`):** физическое хранилище, где данные лежат в оптимальном для запросов виде.
3.  **Материализованное представление (MV):** фоновый процесс (триггер), который перекладывает данные из Kafka-таблицы в целевую таблицу.

### Пример реализации

**1. Создание таблицы-очереди:**
```sql
CREATE TABLE kafka_queue (
    timestamp DateTime64(3),
    level String,
    message String
) ENGINE = Kafka()
SETTINGS 
    kafka_broker_list = 'localhost:9092',
    kafka_topic_list = 'logs_topic',
    kafka_group_name = 'clickhouse_group',
    kafka_format = 'JSONEachRow';
```

**2. Создание целевой таблицы:**
```sql
CREATE TABLE logs (
    timestamp DateTime64(3),
    level String,
    message String
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (level, timestamp);
```

**3. Создание материализованного представления:**
```sql
CREATE MATERIALIZED VIEW logs_mv TO logs AS
SELECT timestamp, level, message
FROM kafka_queue;
```

## Особенности работы

- **Чтение как поток:** после того как данные прочитаны материализованным представлением, они считаются "потребленными" (committed). Прямой `SELECT` из таблицы `Kafka` вернет только те данные, которые еще не были прочитаны.
- **Offsets:** ClickHouse автоматически управляет смещениями (offsets) в Kafka. При перезагрузке он продолжит чтение с последнего успешно записанного в целевую таблицу сообщения.
- **Прямой выбор (Direct Select):** по умолчанию `SELECT` из таблицы `Kafka` не рекомендуется. Если необходимо для отладки, включите настройку: `SET stream_like_engine_allow_direct_select = 1`.

## Рекомендации по производительности

### Батчинг (Batching)
Kafka работает эффективно только при вставке данных пачками. ClickHouse накапливает сообщения из Kafka и записывает их в целевую таблицу блоками.
- Настройки батчинга: `kafka_max_block_size` (количество строк) и `kafka_poll_max_batch_size`.

### Параллелизм
Количество потребителей (consumers) должно соответствовать количеству партиций в топике Kafka.
- Если в топике 4 партиции, установите `kafka_num_consumers = 4` для максимальной скорости чтения.
- Лишние потребители будут простаивать, потребляя ресурсы.

### Форматы данных
ClickHouse поддерживает большинство популярных форматов Kafka: `JSONEachRow`, `CSV`, `Avro`, `Protobuf`, `Parquet`.

## Мониторинг и отладка

Для анализа работы интеграции используйте системные таблицы:
- `system.kafka_consumers`: статус текущих потребителей.
- `system.errors`: отслеживание ошибок парсинга данных.

## Дополнительная информация

- [Обзор ClickHouse](../clickhouse.md)
- [Интеграция с PostgreSQL](../PostgreSQL/Integrations/clickhouse.md)
- [Интеграция с S3](./clickhouse_s3_integration.md)
