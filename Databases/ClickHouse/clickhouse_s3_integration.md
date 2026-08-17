# Интеграция ClickHouse и S3

## Определения

**Интеграция с S3 (Simple Storage Service)** — совокупность нативных механизмов ClickHouse для прозрачного взаимодействия с объектными хранилищами (AWS S3, Яндекс Object Storage, MinIO, Google Cloud Storage). Позволяет использовать S3 как бесконечно масштабируемое и экономически эффективное хранилище для аналитических данных.

**Почему это важно:** 
- **Стоимость:** Хранение в S3 в 5–10 раз дешевле, чем на локальных SSD.
- **Масштабируемость:** Возможность хранить петабайты данных без привязки к дисковой емкости конкретных узлов.
- **Разделение ресурсов (Decoupling):** Отделение хранилища (Storage) от вычислительных ресурсов (Compute).

**Текущая версия:** ClickHouse 26.7 (июль 2026, Stable).

## Основные концепции

### Способы взаимодействия

1.  **Табличная функция `s3()`:** ad-hoc запросы к файлам. Поддерживает `glob` (например, `data/*.parquet`) и автоматический вывод схемы.
2.  **Функция `s3Cluster()`:** выполняет запросы распределенно, используя вычислительную мощность всего кластера для параллельного чтения из S3.
3.  **Движок таблицы `S3`:** постоянный интерфейс к данным в бакете. При вставке в такую таблицу данные физически отправляются в S3.
4.  **Движок `S3Queue` (v23.11+):** аналог Kafka для S3. ClickHouse следит за новыми файлами в бакете и автоматически загружает их. Поддерживает `Exactly-once` через Keeper.
5.  **Многоуровневое хранение (Tiered Storage):** прозрачное перемещение "холодных" данных из локальных SSD в S3. Для приложения это остается одной таблицей `MergeTree`.

### Репликация и Zero-copy

**Zero-copy replication:** критическая технология для кластеров.
- **Как это работает:** Реплики в кластере не копируют данные из S3 друг другу. Они создают в S3 ссылки на один и тот же физический объект (data part).
- **Координация:** Все метаданные о владениях частями данных синхронизируются через **ClickHouse Keeper**.
- **Преимущество:** Экономия до N раз дискового пространства в S3 (где N — количество реплик).

### Производительность и кэширование

Для компенсации сетевых задержек (latencies) при работе с S3 используется **File Cache**:
- **Механизм:** ClickHouse сохраняет "горячие" блоки данных из S3 на локальном SSD узла.
- **ZXC Codec (v26.7+):** Специализированный кодек для S3. Он оптимизирован для баланса между степенью сжатия (экономия трафика S3) и скоростью декомпрессии (минимизация нагрузки на CPU).
- **Parallel Reading:** ClickHouse умеет читать один файл из S3 в несколько потоков, что позволяет утилизировать широкие сетевые каналы (10-40 Gbps).

### Безопасность (v26.7+)

**Важное изменение:** ClickHouse больше не использует IAM-роли или переменные окружения сервера автоматически для SQL-запросов пользователей.
- **Именованные коллекции (Named Collections):** Рекомендуемый способ. Учетные данные прописываются в XML-конфиге, а в SQL используется только имя коллекции.
- **Strict Mode:** По умолчанию анонимный доступ запрещен, если не указано иное в настройках.

## Подготовка и требования

### Предварительные условия
- **ClickHouse:** Версия 22.8+ (для базовых функций), рекомендуется 26.7+ для полной поддержки безопасности и кэширования.
- **Бакет:** Создан в S3-совместимом хранилище.
- **Права доступа:** `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket`. Для Zero-copy требуются расширенные права на управление версиями объектов.
- **Сетевая связность:** Низкая задержка между узлами ClickHouse и эндпоинтом S3.

## Практические сценарии

### 1. Настройка Tiered Storage (SSD + S3)

Это наиболее распространенный сценарий для аналитических БД.

**Конфигурация `storage.xml`:**
```xml
<clickhouse>
    <storage_configuration>
        <disks>
            <s3_disk>
                <type>s3</type>
                <endpoint>https://storage.yandexcloud.net/my-bucket/ch_data/</endpoint>
                <access_key_id>KEY</access_key_id>
                <secret_access_key>SECRET</secret_access_key>
                <metadata_path>/var/lib/clickhouse/disks/s3_disk/</metadata_path>
                <!-- Настройка кэша -->
                <cache_enabled>true</cache_enabled>
                <cache_path>/var/lib/clickhouse/disks/s3_disk/cache/</cache_path>
                <cache_max_size>200Gi</cache_max_size>
            </s3_disk>
        </disks>
        <policies>
            <tiered_policy>
                <volumes>
                    <hot><disk>default</disk></hot>
                    <cold><disk>s3_disk</disk></cold>
                </volumes>
                <move_factor>0.15</move_factor>
            </tiered_policy>
        </policies>
    </storage_configuration>
</clickhouse>
```

**Применение к таблице:**
```sql
CREATE TABLE events (...) 
ENGINE = MergeTree() 
ORDER BY id
TTL timestamp + INTERVAL 14 DAY TO DISK 's3_disk' -- Переместить через 2 недели
SETTINGS storage_policy = 'tiered_policy';
```

### 2. Использование S3Queue для автозагрузки

Идеально для ETL-процессов из внешних систем.

```sql
CREATE TABLE s3_import_queue (
    event_id UInt64,
    data String
) ENGINE = S3Queue(
    'https://storage.yandexcloud.net/bucket/incoming/*.json',
    'JSONEachRow'
)
SETTINGS
    s3queue_mode = 'ordered',
    s3queue_last_processed_path = '/clickhouse/s3queue/import';
```

### 3. Работа с Data Lake (Iceberg / Delta Lake)

ClickHouse позволяет читать данные напрямую из форматов Data Lake, сохраняя поддержку эволюции схем.

```sql
-- Запрос к Apache Iceberg
SELECT * FROM iceberg(
    'https://bucket.s3.amazonaws.com/warehouse/db/table',
    'AWS_ACCESS_KEY',
    'AWS_SECRET_KEY'
) WHERE dt = today();
```

## Валидация и проверка

После настройки выполните следующие проверки:

1.  **Проверка размещения данных:**
    ```sql
    SELECT name, disk_name, path FROM system.parts WHERE table = 'events';
    -- Убедитесь, что disk_name показывает 's3_disk' для старых партиций.
    ```
2.  **Эффективность кэша:**
    ```sql
    SELECT cache_name, hits, misses, size FROM system.file_cache;
    ```
3.  **Проверка Zero-copy:**
    ```sql
    SELECT remote_path, count() as refs 
    FROM system.s3_attachments 
    GROUP BY remote_path HAVING refs > 1;
    ```

## Устранение неисправностей

| Ошибка / Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **403 Access Denied** | Неверные ключи или отсутствие прав на бакет | Проверьте IAM-политику. Убедитесь, что `ListBucket` разрешен. |
| **404 Not Found** | Ошибка в эндпоинте или пути к файлу | Проверьте URL эндпоинта. Для Yandex Cloud это `storage.yandexcloud.net`. |
| **Connection Timeout** | Проблемы с DNS или Firewall | Проверьте `allow_remote_hosts` в `config.xml`. Проверьте MTU сети. |
| **Slow S3 queries** | Отсутствие кэша или медленная сеть | Включите `File Cache`. Используйте `s3Cluster` для распараллеливания. |
| **Zero-copy duplicate parts** | Неверная конфигурация Keeper | Убедитесь, что все узлы используют один и тот же `metadata_path` в конфиге S3-диска. |

## Лучшие практики

- **Размер бакета:** ClickHouse работает лучше с меньшим количеством крупных файлов. Избегайте миллионов мелких файлов в одном префиксе S3.
- **Cache Warming:** После рестарта узла кэш "холодный". Используйте `SYSTEM PREFETCH` для прогрева критичных данных.
- **Версионирование S3:** Включайте версионирование на бакете для работы Zero-copy, чтобы избежать случайного удаления данных при конфликтах имен.
- **Очистка (Cleanup):** ClickHouse сам удаляет объекты из S3 при `DROP TABLE`, но при сбоях могут остаться "сироты". Раз в месяц проводите аудит через `system.s3_attachments`.

## Дополнительная информация

### Смежные темы
- Основной обзор системы — **[ClickHouse](./clickhouse.md)**.
- Интеграция с Kafka — **[ClickHouse и Kafka](./clickhouse_kafka_integration.md)**.
- Управление метаданными — **[ClickHouse Keeper](./clickhouse-cluster.md#clickhouse-keeper)**.
- Общая теория объектных хранилищ — **[Yandex Storage](../../Yandex/Storage/storage_concepts.md)**.

### Ресурсы
- [Документация: S3 Storage Engine](https://clickhouse.com/docs/ru/engines/table-engines/integrations/s3/)
- [Документация: S3 Table Function](https://clickhouse.com/docs/ru/sql-reference/table-functions/s3/)
