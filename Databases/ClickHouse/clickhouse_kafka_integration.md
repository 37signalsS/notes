# Интеграция ClickHouse и Apache Kafka

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**Apache Kafka** — распределённая платформа потоковой передачи событий (event streaming), используемая как буфер между источниками данных и аналитическими системами. В контексте ClickHouse Kafka выступает внешним брокером сообщений, обеспечивая хранение и доставку событий с гарантиями.

**Интеграция ClickHouse и Kafka** — совокупность нативных механизмов ClickHouse для потребления, обработки и сохранения потоковых данных из очередей сообщений в режиме реального времени. ClickHouse выступает в роли высокопроизводительного консьюмера (consumer), превращая поток событий в аналитические таблицы.

**Kafka engine** — встроенный движок таблиц ClickHouse, который подключается к брокерам Kafka и позволяет читать сообщения как из виртуальной таблицы. Данные в движке не хранятся постоянно.

**Хранение offsets в Keeper** — экспериментальный режим движка `Kafka` (включается настройкой `allow_kafka_offsets_storage_in_keeper`), при котором смещения консьюмера хранятся в ClickHouse Keeper через настройки `kafka_keeper_path` и `kafka_replica_name`, а не только в Kafka. Предотвращает потерю/сброс offsets при ребалансировке или сбоях брокера.

**ClickHouse Keeper** — встроенный компонент координации ClickHouse, совместимый с ZooKeeper. Хранит метаданные слияний, репликации и, при включенном режиме хранения offsets в Keeper, смещения консьюмеров.

**Dead Letter Queue (DLQ)** — механизм обработки ошибок, при котором сообщения, не прошедшие парсинг, направляются в отдельную таблицу вместо блокировки всего конвейера.

**Materialized View (в контексте Kafka)** — автоматический конвейер, который перекладывает данные из виртуальной Kafka-таблицы в целевую таблицу MergeTree при поступлении новых сообщений.

**Consumer Lag** — отставание консьюмера от головы топика Kafka, измеряемое в количестве сообщений или времени. Ключевая SRE-метрика для оценки задержки ingestion.

**Schema Registry** — внешний сервис (например, Confluent Schema Registry или Redpanda Console), хранящий схемы для бинарных форматов Avro/Protobuf. ClickHouse может динамически загружать схемы через `format_avro_schema_registry_url`.

**Named Collections** — абстракция параметров подключения к внешним системам (Kafka, S3), хранимая в XML-конфигурации ClickHouse и используемая через `CREATE NAMED COLLECTION`. Позволяет переиспользовать конфигурацию без хардкода в DDL.

**Kafka Connect Sink** — альтернативный вариант интеграции через фреймворк Kafka Connect с официальным коннектором ClickHouse. Поддерживает exactly-once, сторонние state stores и работает с ClickHouse 23.3+.

**Protobuf** — бинарный формат сериализации, поддерживаемый ClickHouse для Kafka ingestion. С версии 26.9 поддерживаются вложенные типы и `oneof` без экспериментальных флагов.

**Redpanda** — Kafka API-совместимый брокер сообщений, рекомендуемый для on-prem развёртываний из-за упрощённой операционности и отсутствия зависимости от JVM.

## Основные концепции

### Архитектурный паттерн "Тройка"

Интеграция всегда строится на связке трех сущностей:

1.  **Таблица-очередь (`Kafka` engine):** Виртуальная таблица, которая только читает данные из брокера. Данные в ней не хранятся.
2. **Целевая таблица (`MergeTree`):** Физическое хранилище на диске, оптимизированное для аналитических запросов.
3. **Материализованное представление (Materialized View):** Автоматический конвейер, который перекладывает данные из очереди в цель при их поступлении.

### Хранение offsets в ClickHouse Keeper (экспериментально)

Режим движка `Kafka`, при котором смещения консьюмера хранятся в **ClickHouse Keeper** вместо Kafka. Включается установкой `allow_kafka_offsets_storage_in_keeper = 1` и указанием двух настроек — `kafka_keeper_path` (путь в Keeper) и `kafka_replica_name` (имя реплики в Keeper). Обе настройки должны быть указаны одновременно или не указаны вовсе.

- **Управление смещениями (Offsets):** При перезапуске таблицы или восстановлении после ошибки offsets берутся из Keeper, а не из Kafka. Это предотвращает потерю/сброс offsets при ребалансировке или сбоях брокера.
- **Exactly-once:** Достигается комбинацией хранения offsets в Keeper с дедупликацией блоков на целевой таблице (`insert_deduplicate` на `ReplicatedMergeTree`) — Keeper хранит прогресс консьюмера, а ClickHouse отсеивает повторно доставленные блоки.
- **Ограничения:** Для repeatable reads сообщения нельзя потреблять из нескольких партиций в одном потоке. Рекомендуется использовать `{uuid}` в `kafka_keeper_path`, чтобы избежать коллизий путей при пересоздании таблиц.

### Гарантии доставки

- **At-least-once:** Стандартный режим. Оффсеты фиксируются после записи блока в MergeTree. Возможны дубликаты при сетевых сбоях.
- **Exactly-once:** Реализуется через хранение offsets в Keeper (`kafka_keeper_path` + `kafka_replica_name`) + дедупликация блоков на целевой `ReplicatedMergeTree`-таблице (`insert_deduplicate = 1`).

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

## Железо и ОС

### Железо

- **CPU:** Чтение из Kafka активно потребляет CPU на десериализацию (особенно JSON). Рекомендуется минимум 4 ядра на узел ClickHouse, обрабатывающий Kafka-ingestion; выделяйте отдельные ядра для консьюмеров при высокой нагрузке.
- **RAM:** 16 GB минимум; 32+ GB рекомендуется при использовании режима хранения offsets в Keeper или больших блоков (`kafka_max_block_size` > 65536).
- **Сеть:** 10 GbE между ClickHouse и Kafka-брокерами. MTU 9000 (jumbo frames) увеличивает пропускную способность для больших батчей.
- **Диски:** NVMe/SSD для целевых MergeTree-таблиц. Consumer lag растёт на HDD при высокой частоте слияний.

### ОС

- **Ядро Linux:** 5.4+ с включённым `CONFIG_IKCONFIG` для тонкой настройки сетевых буферов.
- **Лимиты файлов:** `fs.file-max >= 1000000`, `nofile` для пользователя `clickhouse` >= 65536.
- **Виртуальная память:** `vm.max_map_count >= 262144` (требуется для KeeperMap и offsets в Keeper).
- **Transparent Huge Pages (THP):** отключён (`echo never > /sys/kernel/mm/transparent_hugepage/enabled`) для стабильной задержки.

## Архитектура взаимодействия

```
Kafka Broker → ClickHouse Kafka Engine → Materialized View → MergeTree
       ↓                    ↓                       ↓
   retention.ms      _topic/_partition        ORDER BY ключ
                  _offset (Kafka/Keeper)     compression codec
                  _timestamp                  TTL
```

1. Брокер Kafka хранит сообщения в топиках с настроенным `retention.ms` и `cleanup.policy`.
2. Движок Kafka подключается к брокерам, формирует consumer group и получает батчи сообщений.
3. Виртуальные столбцы добавляют метаинформацию (_topic, _partition, _offset, _timestamp).
4. Materialized View автоматически вставляет данные в целевую таблицу MergeTree.
5. Смещения фиксируются в Kafka (обычный режим) или в ClickHouse Keeper (режим `kafka_keeper_path`) после успешной записи.

## Подготовка и требования

### Предварительные условия

- **Kafka:** Версия 2.0+ (рекомендуется 3.x или Redpanda для лучшей производительности и упрощённой эксплуатации on-prem).
- **ClickHouse Keeper:** Обязателен для режима хранения offsets в Keeper. Может быть как встроенным (один узел), так и кластером из 3 узлов для отказоустойчивости.
- **Сетевой доступ:** Узлы ClickHouse должны иметь доступ к портам брокеров (по умолчанию 9092 для PLAINTEXT, 9094 для SSL).
- **Ресурсы:** Чтение из Kafka активно потребляет CPU на десериализацию (особенно JSON). Рекомендуется выделять минимум 2 ядра на каждый топик.
- **Настройка Kafka:** Рекомендуется `cleanup.policy = delete` и `retention.ms` не менее 24 часов для возможности переповтора при сбоях.

## Практические сценарии

### 1. Реализация конвейера с Exactly-once (offsets в Keeper)

**Настройка Named Collection в `config.d/kafka.xml`:**
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

**Включение режима хранения offsets в Keeper (на каждом узле в `users.d/` или профиле пользователя):**
```xml
<!-- /etc/clickhouse-server/users.d/kafka_keeper.xml -->
<clickhouse>
    <profiles>
        <default>
            <allow_kafka_offsets_storage_in_keeper>1</allow_kafka_offsets_storage_in_keeper>
        </default>
    </profiles>
</clickhouse>
```

**Создание таблиц:**
```sql
-- 1. Виртуальная таблица
CREATE TABLE app_logs_queue (
    timestamp DateTime64(3),
    level String,
    message String
) ENGINE = Kafka(prod_broker)
SETTINGS
    kafka_topic_list = 'app_events',
    kafka_group_name = 'ch_consumers',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 4,
    kafka_max_block_size = 65536,
    kafka_keeper_path = '/clickhouse/kafka/app_logs/{uuid}',
    kafka_replica_name = 'replica-1';

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
WHERE _error != '';
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

### 4. Интеграция с Protobuf

С версии 26.9 ClickHouse поддерживает вложенные типы и `oneof` в Protobuf без экспериментальных флагов.

```sql
CREATE TABLE proto_queue (...)
ENGINE = Kafka(...)
SETTINGS
    kafka_format = 'Protobuf',
    format_protobuf_schema_registry_url = 'http://schema-registry:8081';
```

### 5. Резервное копирование и восстановление

Перед изменением конфигурации Kafka-конвейера или ротицией топиков выполните:

```sql
-- Бэкап целевой таблицы
BACKUP TABLE app_logs TO Disk('backups', 'app_logs_2026Q3.zip');

-- Проверка бэкапа
RESTORE TABLE app_logs_restore FROM Disk('backups', 'app_logs_2026Q3.zip')
SETTINGS allow_nonrestorable_backup = 1;
```

При использовании режима хранения offsets в Keeper (`kafka_keeper_path`) при откате на другой кластер ClickHouse смещения восстановятся автоматически из Keeper.

## Мониторинг и операции

### Валидация и проверка

1. **Проверка активности консьюмеров:**
    ```sql
    SELECT * FROM system.kafka_consumers WHERE topic = 'app_events';
    -- Ищите столбцы last_committed_offset и lag.
    ```

2. **Анализ логов чтения:**
    ```sql
    SELECT event_time, status, rows_stored, error_message 
    FROM system.kafka_log 
    ORDER BY event_time DESC LIMIT 10;
    ```

3. **Проверка скорости вставки:**
    ```sql
    SELECT table, count() / 60 as rows_per_sec 
    FROM app_logs 
    WHERE event_time > now() - INTERVAL 1 MINUTE 
    GROUP BY table;
    ```

4. **Проверка здоровья слияний:**
    ```sql
    SELECT database, table, count() as active_parts
    FROM system.merges
    WHERE database = currentDatabase()
    GROUP BY database, table;
    ```

### SRE-метрики и пороги

| Метрика | Источник | SRE-порог |
| :--- | :--- | :--- |
| Consumer Lag (сообщения) | `system.kafka_consumers.lag` | > 10 000 — алерт |
| Consumer Lag (время) | `system.kafka_consumers.lag` / throughput | > 5 минут — алерт |
| Ошибки парсинга | `system.errors` | > 0.1% от обработанных сообщений — алерт |
| Время записи блока | `system.kafka_log` | P99 > 2 секунд — алерт |
| CPU на узел ClickHouse | `system.metrics` | > 80% sustained — алерт |
| Активные слияния | `system.merges` | > 5 на таблицу одновременно — алерт |

### Prometheus/Grafana

Добавьте в дашборд Kafka-интеграции:
- `lag` из `system.kafka_consumers` — основной индикатор здоровья ingestion
- `rows_stored` / `error_message` из `system.kafka_log` — частота и типы ошибок
- CPU/memory с узлов ClickHouse — десериализация JSON/Avro ресурсоёмка
- Метрики слияний MergeTree — фрагментация при высокой частоте вставок

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Consumer Lag растет** | ClickHouse не успевает парсить данные или писать в MergeTree | Увеличьте `kafka_num_consumers`. Проверьте `kafka_max_block_size` (рекомендуется 65536+). |
| **Empty tables** | Неверный формат данных или `kafka_group_name` уже используется | Проверьте `system.errors`. Попробуйте сменить `kafka_group_name` для теста. |
| **"Cannot parse JSON"** | Битые сообщения в топике | Включите `kafka_handle_error_mode = 'stream'` и настройте DLQ (см. сценарий 2). |
| **Connection refused** | Брокеры недоступны по сети | Проверьте `advertised.listeners` на стороне Kafka. Проверьте Firewall. |
| **High CPU usage** | Слишком много мелких вставок или сложный JSON | Используйте `LowCardinality` для строк. Увеличьте `kafka_flush_interval_ms` до 7500-10000. |
| **Offsets сброшены после рестарта** | Используется классический Kafka engine без хранения offsets в Keeper | Включите `kafka_keeper_path`/`kafka_replica_name` (режим Keeper). Проверьте `system.kafka_consumers` после перезапуска. |
| **Duplicate сообщения** | At-least-once режим при сетевых сбоях | Включите offsets в Keeper + `insert_deduplicate = 1` или добавьте уникальный ключ в ORDER BY. |

## Лучшие практики

1. **Партиционирование:** Количество партиций в Kafka должно быть кратно (или равно) `kafka_num_consumers` для равномерной нагрузки.
2. **Батчинг:** Kafka-движок наиболее эффективен при записи большими блоками. Не ставьте `kafka_flush_interval_ms` меньше 5000 мс.
3.  **Оффсеты:** Для критичных данных включите хранение offsets в Keeper (`kafka_keeper_path` + `kafka_replica_name`), чтобы избежать дублей или потерь при ребалансировке партиций.
4. **Мониторинг:** Настройте алертинг на столбец `lag` в `system.kafka_consumers`. Лаг > 10 минут — сигнал о проблеме.
5. **Форматы:** Если возможно, используйте бинарные форматы (Avro, Protobuf, Arrow) — они в 3-5 раз быстрее JSON при десериализации.
6. **Сеть:** Разместите ClickHouse и Kafka в одной VLAN или доступном сегменте сети с задержкой < 1 мс.
7. **Бэкапы:** Планируйте регулярный бэкап MergeTree-таблиц через `clickhouse-backup` или `BACKUP TABLE`.
8. **Тестирование:** Создайте staging-топик с production-трафиком для проверки новых схем перед деплоем.

## Дополнительная информация

### Смежные темы

- Основной обзор системы — **[ClickHouse](./clickhouse.md)**.
- Интеграция с объектными хранилищами — **[Интеграция ClickHouse и S3](./clickhouse_s3_integration.md)**.
- Управление метаданными — **[ClickHouse Keeper](./clickhouse-cluster.md#clickhouse-keeper)**.
- Гарантии доставки — **[Kafka: Гарантии доставки](../../Kafka/delivery_guarantees.md)**.
- Мониторинг операций — **[ClickHouse Operations](./clickhouse-operations.md)**.

### Ресурсы

- [Официальная документация: Kafka Engine](https://clickhouse.com/docs/ru/engines/table-engines/integrations/kafka/)
- [Блог ClickHouse: Exactly-once delivery with Kafka](https://clickhouse.com/blog/exactly-once-delivery-with-clickhouse-and-kafka)
- [Документация: Kafka Connect Sink](https://clickhouse.com/docs/integrations/connectors/data-ingestion/kafka/)
