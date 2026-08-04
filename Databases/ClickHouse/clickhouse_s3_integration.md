# Интеграция ClickHouse и S3

## Определения

**Интеграция с S3 (Simple Storage Service)** — совокупность механизмов ClickHouse для взаимодействия с объектными хранилищами (AWS S3, Яндекс Object Storage, MinIO, Google Cloud Storage). Позволяет использовать S3 как внешний источник данных, движок для таблиц или уровень хранения для «холодных» данных в рамках гибридной архитектуры.

**Объектное хранилище** — в контексте ClickHouse выступает как бесконечно масштабируемое и дешевое хранилище, заменяющее или дополняющее локальные диски.

**Текущая версия:** ClickHouse 26.7 (июль 2026, Stable).

## Основные концепции

### Способы взаимодействия

1.  **Табличная функция `s3()`:** позволяет выполнять запросы к файлам в S3 без создания таблиц. Поддерживает шаблоны в путях (wildcards) и автоматический вывод схемы (для форматов Parquet, Native).
2.  **Функция `s3Cluster()`:** расширение функции `s3()`, позволяющее распределять чтение и обработку файлов из S3 между всеми узлами кластера параллельно.
3.  **Движок таблицы `S3`:** постоянная таблица, данные которой физически расположены в S3.
4.  **Движки `Remote` и `RemoteSecure` (v26.7+):** персистентные аналоги табличных функций `remote` и `remote_secure` для работы с удаленными ресурсами, включая объектные хранилища через прокси.
5.  **Движок `S3Queue` (v23.11+):** аналог `Kafka` для объектного хранилища. Автоматически отслеживает появление новых файлов в бакете и загружает их в ClickHouse (поддерживает режимы `ordered` и `unordered`).
6.  **Многоуровневое хранение (Tiered Storage):** использование S3 как «холодного» диска для `MergeTree` таблиц. Данные остаются доступными для SQL-запросов, но физически перемещаются в S3.

### Репликация и отказоустойчивость

**Zero-copy replication:** механизм, позволяющий репликам `ReplicatedMergeTree` использовать одни и те же данные в S3, не дублируя их физически.
- В S3 хранится одна копия данных (data parts).
- Реплики обмениваются только метаданными через **ClickHouse Keeper**.
- Это критически важно для экономии места при хранении петабайт данных в S3.

### Производительность и кэширование

Для компенсации задержек сети используется **File Cache** (дисковый кэш). 
- ClickHouse сохраняет часто используемые блоки данных из S3 на локальном SSD.
- Кэширование настраивается на уровне диска в `config.xml`.
- Поддерживается кэширование метаданных и данных (data parts).
- **ZXC Codec (v26.7+):** асимметричный кодек с быстрой декомпрессией, эффективен для S3-хранилищ при балансе между скоростью и степенью сжатия.

### Безопасность (v26.7+)

Начиная с версии 26.7, ClickHouse по умолчанию **не разрешает** автоматическое использование учетных данных сервера (IAM-роли, переменные окружения) при выполнении S3-запросов из пользовательского SQL. 
- Для использования системных credentials требуется явная настройка в `users.xml` или использование именованных коллекций (Named Collections).

## Практические сценарии

### Прямые запросы и импорт данных

Использование функции `s3` для анализа внешних данных:

```sql
-- Чтение всех Parquet-файлов из папки распределенно по кластеру
SELECT count(), avg(fare_amount)
FROM s3Cluster(
    'my_cluster',
    'https://storage.yandexcloud.net/my-bucket/taxi_data/*.parquet',
    'ACCESS_KEY',
    'SECRET_KEY',
    'Parquet'
);

-- Импорт данных в локальную таблицу с автоматическим выводом схемы
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
                <cache_max_size>100Gi</cache_max_size>
            </s3_cold>
        </disks>
        <policies>
            <tiered_policy>
                <volumes>
                    <hot><disk>default</disk></hot>
                    <cold><disk>s3_cold</disk></cold>
                </volumes>
                <move_factor>0.1</move_factor> <!-- Перемещать, когда на hot < 10% места -->
            </tiered_policy>
        </policies>
    </storage_configuration>
</clickhouse>
```

Применение политики и TTL:
```sql
CREATE TABLE events (...) 
ENGINE = MergeTree() 
ORDER BY event_time
TTL event_time + INTERVAL 1 WEEK TO VOLUME 'cold',
    event_time + INTERVAL 1 MONTH DELETE
SETTINGS storage_policy = 'tiered_policy';
```

### Резервное копирование в S3

Использование нативных команд `BACKUP` и `RESTORE` (рекомендуется для консистентности):

```sql
-- Создание бэкапа базы данных в S3
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
| **S3Queue** | Автоматизация ETL, At-least-once | Требует контроля за состоянием очереди |
| **s3Cluster()** | Высокая скорость за счет параллелизма | Требует наличия настроенного кластера |

### Особенности работы с форматами Data Lake

ClickHouse нативно поддерживает современные форматы хранения данных:
- **Iceberg:** чтение через функцию `iceberg()`. Поддерживает эволюцию схемы.
- **Delta Lake:** чтение через функцию `deltaLake()`. Поддерживает версии (time travel).
- **Hudi:** чтение через функцию `hudi()`. Поддерживает инкрементальные обновления.
- **Parquet / Arrow:** рекомендуемые форматы для S3 из-за поддержки колоночного чтения и метаданных.

### Смежные темы

- Общий обзор системы — **[ClickHouse](./clickhouse.md)**.
- Интеграция с очередями сообщений — **[Интеграция ClickHouse и Kafka](./clickhouse_kafka_integration.md)**.
- Управление метаданными — **[ClickHouse Keeper](./clickhouse.md#репликация-и-шардирование)**.
- Теория хранения — **[Системы хранения данных](../../Concepts/Storage/data_storage_overview.md)**.
