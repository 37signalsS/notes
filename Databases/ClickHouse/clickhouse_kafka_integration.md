# Интеграция ClickHouse и Apache Kafka

## Определения

**Интеграция с Apache Kafka** — совокупность нативных механизмов ClickHouse для потокового потребления и обработки данных из очередей сообщений в режиме реального времени. ClickHouse выступает в роли высокопроизводительного консьюмера (consumer), превращая поток событий в аналитические таблицы.

**Почему это важно:**
- **Real-time аналитика:** Задержка (latency) от события до появления в отчете составляет миллисекунды.
- **Отказоустойчивость:** Kafka выступает буфером, позволяя ClickHouse восстанавливаться после сбоев без потери данных.
- **Event Sourcing:** Возможность восстановить состояние таблиц, перечитав топик с нужного момента (offset).

**Текущая версия:** ClickHouse 26.7 (июль 2026, Stable).

## Основные концепции

### Архитектурный паттерн "Тройка"
Интеграция всегда строится на связке трех сущностей:
1.  **Таблица-очередь (`Kafka` / `Kafka2` engine):** Виртуальная таблица, которая только читает данные из брокера. Данные в ней не хранятся.
2.  **Целевая таблица (`MergeTree`):** Физическое хранилище на диске, оптимизированное для запросов.
3.  **Материализованное представление (Materialized View):** "Клей", который автоматически перекладывает данные из очереди в цель при их поступлении.

### Движок Kafka2 (v26.7+)
Новое поколение движка, решающее проблемы классического `Kafka` engine:
- **Управление смещениями (Offsets):** Хранит оффсеты в **ClickHouse Keeper**, а не только в Kafka. Это предотвращает потерю данных при ребалансировке или сбоях брокера.
- **Exactly-once:** Гарантирует, что сообщение будет записано в целевую таблицу ровно один раз.
- **Производительность:** Улучшенная работа с многопоточностью и уменьшенная нагрузка на CPU при парсинге JSON/Avro.

### Гарантии доставки
- **At-least-once:** Стандартный режим. Оффсеты фиксируются после записи блока в MergeTree. Возможны дубликаты при сетевых сбоях.
- **Exactly-once:** Реализуется через `Kafka2` + `insert_deduplicate = 1`. ClickHouse использует Keeper для дедупликации целых блоков данных по их хэшам.

### Виртуальные столбцы
Позволяют обогащать данные метаинформацией из Kafka без изменения структуры сообщения.

| Столбец | Тип | Описание |
| :--- | :--- | :--- |
| `_topic` | `String` | Имя топика |
| `_partition` | `UInt64` | Номер партиции |
| `_offset` | `UInt64` | Порядковый номер сообщения |
| `_timestamp` | `DateTime` | Время публикации в Kafka |
| `_key` | `String` | Ключ сообщения (обычно используется для шардирования в Kafka) |
| `_headers.name` | `Array(String)` | Заголовки сообщения |

## Подготовка и требования

### Предварительные условия
- **Kafka:** Версия 2.0+ (рекомендуется 3.x или Redpanda для лучшей производительности).
- **Сетевой доступ:** Узлы ClickHouse должны иметь доступ к портам брокеров (по умолчанию 9092 или 9094 для SSL).
- **Ресурсы:** Чтение из Kafka активно потребляет CPU на десериализацию (особенно JSON). Рекомендуется выделять минимум 2 ядра на каждый топик.
- **Настройка Kafka:** Рекомендуется `cleanup.policy = delete` и `retention.ms` не менее 24 часов для возможности переповтора при сбоях.

## Практические сценарии

### 1. Реализация конвейера с Exactly-once (Kafka2)

**Настройка брокеров в `config.d/kafka.xml`:**
```xml
<clickhouse>
    <kafka>
        <named_collections>
            <prod_broker>
                <kafka_broker_list>broker1:9092,broker2:9092</kafka_broker_list>
                <kafka_security_protocol>SASL_PLAINTEXT</kafka_security_protocol>
                <kafka_sasl_mechanism>PLAIN</kafka_sasl_mechanism>
                <kafka_sasl_username>ch_user</kafka_sasl_username>
                <kafka_sasl_password>pwd</kafka_sasl_password>
            </prod_broker>
        </named_collections>
    </kafka>
</clickhouse>
```

**Создание таблиц:**
```sql
-- 1. Виртуальная таблица
CREATE TABLE app_logs_queue (
    timestamp DateTime64(3),
    level String,
    message String
) ENGINE = Kafka2(prod_broker) -- Используем коллекцию
SETTINGS 
    kafka_topic_list = 'app_events',
    kafka_group_name = 'ch_consumers',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 4; -- Должно быть <= кол-ву партиций в Kafka

-- 2. Целевая таблица
CREATE TABLE app_logs (
    event_time DateTime64(3),
    level LowCardinality(String),
    message String,
    _offset UInt64
) ENGINE = MergeTree() 
ORDER BY (level, event_time);

-- 3. Материализованное представление
CREATE MATERIALIZED VIEW app_logs_mv TO app_logs AS
SELECT timestamp as event_time, level, message, _offset
FROM app_logs_queue;
```

### 2. Обработка ошибок (Dead Letter Queue)

Для предотвращения остановки конвейера при битых данных используйте `kafka_handle_error_mode = 'stream'`.

```sql
CREATE TABLE kafka_with_errors (
    data String,
    _error String,
    _raw_message String
) ENGINE = Kafka(...)
SETTINGS 
    kafka_handle_error_mode = 'stream';

CREATE MATERIALIZED VIEW errors_mv TO dlq_table AS
SELECT _raw_message, _error, now() as error_time
FROM kafka_with_errors
WHERE _error != ''; -- Отправляем только ошибки в отдельную таблицу
```

### 3. Интеграция с Avro и Schema Registry

ClickHouse умеет динамически загружать схемы для бинарных форматов.

```sql
CREATE TABLE avro_queue (...) 
ENGINE = Kafka(...)
SETTINGS 
    kafka_format = 'Avro',
    format_avro_schema_registry_url = 'http://schema-registry:8081';
```

## Валидация и проверка

1.  **Проверка активности консьюмеров:**
    ```sql
    SELECT * FROM system.kafka_consumers WHERE topic = 'app_events';
    -- Ищите столбцы last_committed_offset и lag.
    ```
2.  **Анализ логов чтения:**
    ```sql
    SELECT event_time, status, rows_stored, error_message 
    FROM system.kafka_log 
    ORDER BY event_time DESC LIMIT 10;
    ```
3.  **Проверка скорости вставки:**
    ```sql
    SELECT table, count() / 60 as rows_per_sec 
    FROM app_logs 
    WHERE event_time > now() - INTERVAL 1 MINUTE 
    GROUP BY table;
    ```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Consumer Lag растет** | ClickHouse не успевает парсить данные или писать в MergeTree | Увеличьте `kafka_num_consumers`. Проверьте `kafka_max_block_size` (рекомендуется 65536+). |
| **Empty tables** | Неверный формат данных или `kafka_group_name` уже используется | Проверьте `system.errors`. Попробуйте сменить `kafka_group_name` для теста. |
| **"Cannot parse JSON"** | Битые сообщения в топике | Включите `kafka_handle_error_mode = 'stream'` и настройте DLQ (см. сценарий 2). |
| **Connection refused** | Брокеры недоступны по сети | Проверьте `advertised.listeners` на стороне Kafka. Проверьте Firewall. |
| **High CPU usage** | Слишком много мелких вставок или сложный JSON | Используйте `LowCardinality` для строк. Увеличьте `kafka_flush_interval_ms` до 7500-10000. |

## Лучшие практики

1.  **Партиционирование:** Количество партиций в Kafka должно быть кратно (или равно) `kafka_num_consumers` для равномерной нагрузки.
2.  **Батчинг:** Kafka-движок наиболее эффективен при записи большими блоками. Не ставьте `kafka_flush_interval_ms` меньше 5000 мс.
3.  **Оффсеты:** Для критичных данных используйте `Kafka2`, чтобы избежать дублей или потерь при ребалансировке партиций.
4.  **Мониторинг:** Настройте алертинг на столбец `lag` в `system.kafka_consumers`. Лаг > 10 минут — сигнал о проблеме.
5.  **Форматы:** Если возможно, используйте бинарные форматы (Avro, Protobuf, Arrow) — они в 3-5 раз быстрее JSON при десериализации.

## Дополнительная информация

### Смежные темы
- Основной обзор системы — **[ClickHouse](./clickhouse.md)**.
- Интеграция с объектными хранилищами — **[Интеграция ClickHouse и S3](./clickhouse_s3_integration.md)**.
- Управление метаданными — **[ClickHouse Keeper](./clickhouse-cluster.md#clickhouse-keeper)**.
- Гарантии доставки — **[Kafka: Гарантии доставки](../../Kafka/delivery_guarantees.md)**.

### Ресурсы
- [Официальная документация: Kafka Engine](https://clickhouse.com/docs/ru/engines/table-engines/integrations/kafka/)
- [Блог ClickHouse: Exactly-once delivery with Kafka](https://clickhouse.com/blog/exactly-once-delivery-with-clickhouse-and-kafka)
