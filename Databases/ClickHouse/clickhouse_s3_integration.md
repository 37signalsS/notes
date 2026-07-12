# Интеграция ClickHouse и S3

## Обзор

Интеграция с **S3 (Simple Storage Service)** является одной из ключевых возможностей ClickHouse для построения современных архитектур данных (Data Lakehouse). Она позволяет использовать объектные хранилища (AWS S3, Яндекс Object Storage, MinIO, Ceph) как источник данных, так и как масштабируемое хранилище для "холодных" данных.

## Способы интеграции

### Табличная функция `s3()`

Позволяет выполнять запросы к данным в S3 напрямую, без создания постоянной таблицы в ClickHouse. Удобно для разовых выгрузок или проверки данных.

**Синтаксис:**
```sql
SELECT * FROM s3(
    'https://bucket-name.s3.amazonaws.com/data.csv',
    'access_key',
    'secret_key',
    'CSV'
);
```

**Пример импорта данных:**
```sql
INSERT INTO local_table
SELECT * FROM s3('https://storage.yandexcloud.net/my-bucket/taxi_data/*.parquet', 'Parquet');
```

### Движок таблицы `S3`

Используется для создания постоянной таблицы, которая физически хранит данные в S3.

```sql
CREATE TABLE s3_table (
    id UInt64,
    name String
) ENGINE = S3(
    'https://storage.yandexcloud.net/my-bucket/data.csv',
    'access_key',
    'secret_key',
    'CSV'
);
```

## Многоуровневое хранение (Tiered Storage)

ClickHouse позволяет автоматически перемещать старые или редко используемые данные на S3, освобождая дорогое место на SSD/NVMe.

### Настройка политики хранения (Storage Policy)

Конфигурация задается в XML-файлах ClickHouse (`config.xml` или в `conf.d/`).

**1. Определение дисков:**
```xml
<storage_configuration>
    <disks>
        <default></default> <!-- Локальный диск -->
        <s3_disk>
            <type>s3</type>
            <endpoint>https://storage.yandexcloud.net/my-bucket/clickhouse/</endpoint>
            <access_key_id>your_key</access_key_id>
            <secret_access_key>your_secret</secret_access_key>
        </s3_disk>
    </disks>
</storage_configuration>
```

**2. Определение политик:**
```xml
<policies>
    <tiered_policy>
        <volumes>
            <hot>
                <disk>default</disk>
            </hot>
            <cold>
                <disk>s3_disk</disk>
            </cold>
        </volumes>
        <move_factor>0.1</move_factor> <!-- Перемещать на cold, когда на hot осталось <10% места -->
    </tiered_policy>
</policies>
```

**3. Применение политики к таблице:**
```sql
CREATE TABLE events (...)
ENGINE = MergeTree()
ORDER BY id
SETTINGS storage_policy = 'tiered_policy';
```

## Резервное копирование в S3

ClickHouse поддерживает нативную команду `BACKUP` для выгрузки данных в S3.

**Пример создания бэкапа:**
```sql
BACKUP TABLE my_table TO S3(
    'https://storage.yandexcloud.net/backups/my_table_backup.zip',
    'access_key',
    'secret_key'
);
```

**Пример восстановления:**
```sql
RESTORE TABLE my_table FROM S3(
    'https://storage.yandexcloud.net/backups/my_table_backup.zip',
    'access_key',
    'secret_key'
);
```

## Преимущества и ограничения

| Характеристика | Описание |
| :--- | :--- |
| **Масштабируемость** | Объектные хранилища практически безграничны. |
| **Стоимость** | S3 значительно дешевле локальных SSD. |
| **Производительность** | Чтение из S3 медленнее, чем с локальных дисков. Рекомендуется использовать кэширование. |
| **Кэширование** | ClickHouse может кэшировать данные из S3 на локальном диске (`S3Cache`). |

## Дополнительная информация

- [Обзор ClickHouse](../clickhouse.md)
- [Интеграция с Kafka](./clickhouse_kafka_integration.md)
