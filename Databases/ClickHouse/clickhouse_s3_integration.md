# Интеграция ClickHouse и S3

## Определения

**Интеграция с S3 (Simple Storage Service)** — совокупность механизмов ClickHouse для взаимодействия с объектными хранилищами (AWS S3, Яндекс Object Storage, MinIO, Google Cloud Storage). Позволяет использовать S3 как внешний источник данных, движок для таблиц или уровень хранения для "холодных" данных в рамках гибридной архитектуры.

**Объектное хранилище** — в контексте ClickHouse выступает как бесконечно масштабируемое и дешевое хранилище, заменяющее или дополняющее локальные диски.

## Основные концепции

### Способы взаимодействия

1.  **Табличная функция `s3()`:** позволяет выполнять запросы к файлам в S3 без создания таблиц. Поддерживает шаблоны в путях (wildcards) и автоматический вывод схемы (для форматов Parquet, Native).
2.  **Движок таблицы `S3`:** постоянная таблица, данные которой физически расположены в S3. Подходит для обмена данными и хранения небольших архивов.
3.  **Движок `S3Queue` (v23.11+):** аналог `Kafka` для объектного хранилища. Автоматически отслеживает появление новых файлов в бакете и загружает их в ClickHouse.
4.  **Многоуровневое хранение (Tiered Storage):** использование S3 как "холодного" диска для `MergeTree` таблиц. Данные остаются доступными для SQL-запросов, но физически перемещаются в S3.

### Репликация и отказоустойчивость

**Zero-copy replication:** механизм, позволяющий репликам `ReplicatedMergeTree` использовать одни и те же данные в S3, не дублируя их физически. В объектном хранилище хранится одна копия данных, а реплики обмениваются только метаданными.
- Координация осуществляется через **ClickHouse Keeper**.

### Производительность и кэширование

Для компенсации задержек сети используется **File Cache** (дисковый кэш). ClickHouse сохраняет часто используемые блоки данных из S3 на локальном SSD, обеспечивая скорость чтения, сопоставимую с локальными таблицами.

## Практические сценарии

### Прямые запросы и импорт данных

Использование функции `s3` для анализа внешних данных:

```sql
-- Чтение всех Parquet-файлов из папки
SELECT count(), avg(fare_amount)
FROM s3(
    'https://storage.yandexcloud.net/my-bucket/taxi_data/*.parquet',
    'ACCESS_KEY',
    'SECRET_KEY',
    'Parquet'
);

-- Импорт данных в локальную таблицу
INSERT INTO local_table
SELECT * FROM s3('https://storage.yandexcloud.net/my-bucket/data.csv.gz', 'CSVWithNames');
```

### Настройка многоуровневого хранения

Конфигурация в `config.d/storage.xml`:

```xml
<clickhouse>
    <storage_configuration>
        <disks>
            <s3_cold>
                <type>s3</type>
                <endpoint>https://storage.yandexcloud.net/my-bucket/data/</endpoint>
                <access_key_id>your_key</access_key_id>
                <secret_access_key>your_secret</secret_access_key>
                <!-- Настройка кэширования -->
                <metadata_path>/var/lib/clickhouse/disks/s3_cold/</metadata_path>
                <cache_enabled>true</cache_enabled>
                <cache_path>/var/lib/clickhouse/disks/s3_cold/cache/</cache_path>
            </s3_cold>
        </disks>
        <policies>
            <tiered_policy>
                <volumes>
                    <hot><disk>default</disk></hot>
                    <cold><disk>s3_cold</disk></cold>
                </volumes>
            </tiered_policy>
        </policies>
    </storage_configuration>
</clickhouse>
```

Применение политики:
```sql
CREATE TABLE events (...) 
ENGINE = MergeTree() 
ORDER BY event_time
SETTINGS storage_policy = 'tiered_policy';
```

### Резервное копирование в S3

Использование нативных команд `BACKUP` и `RESTORE`:

```sql
-- Создание бэкапа базы данных
BACKUP DATABASE my_db TO S3(
    'https://storage.yandexcloud.net/backups/my_db_full.zip',
    'ACCESS_KEY',
    'SECRET_KEY'
);
```

## Дополнительная информация

### Сравнение подходов

| Метод | Плюсы | Минусы |
| :--- | :--- | :--- |
| **Функция s3()** | Не требует настройки, гибкость | Нет индексов, медленно для частых запросов |
| **Tiered Storage** | Прозрачно для приложений, индексы работают | Сложность настройки конфигурации |
| **S3Queue** | Автоматизация ETL | Требует контроля за состоянием очереди |

### Особенности работы с форматами

ClickHouse нативно поддерживает сложные форматы данных в S3:
- **Parquet / Avro / ORC:** высокая степень сжатия и колоночное чтение.
- **Iceberg / Delta Lake / Hudi:** поддержка современных форматов Data Lake (чтение через функции `iceberg()`, `deltaLake()`).

### Смежные темы

- Общий обзор системы — **[ClickHouse](./clickhouse.md)**.
- Интеграция с очередями сообщений — **[Интеграция ClickHouse и Kafka](./clickhouse_kafka_integration.md)**.
- Управление метаданными — **[ClickHouse Keeper](./clickhouse.md#репликация-и-шардирование)**.
