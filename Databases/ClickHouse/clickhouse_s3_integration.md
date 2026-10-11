# Интеграция ClickHouse и S3

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**S3-совместимое объектное хранилище** — внешняя система хранения данных, реализующая S3 API. В on-prem средах используйте MinIO, Ceph Rados Gateway (RGW), или другие S3-совместимые решения.

**Интеграция с S3** — совокупность нативных механизмов ClickHouse для прозрачного взаимодействия с объектными хранилищами через S3 API. Позволяет использовать объектное хранилище как экономически эффективное расширение локальных дисков для аналитических данных.

**Почему это важно:**
- **Стоимость:** Хранение в S3 в 5–10 раз дешевле, чем на локальных SSD.
- **Масштабируемость:** Возможность хранить петабайты данных без привязки к дисковой емкости конкретных узлов.
- **Разделение ресурсов (Decoupling):** Отделение хранилища (Storage) от вычислительных ресурсов (Compute).

**Тир 1 (hot)** — локальный SSD/NVMe узел, где хранятся активные данные для быстрого доступа.

**Тир 2 (cold)** — объектное хранилище (S3-совместимое), где хранятся архивные и редко используемые данные.

**File Cache** — локальный кэш ClickHouse на SSD узла, который хранит "горячие" блоки данных из S3 для компенсации сетевых задержек.

**Zero-copy replication** — механизм кластерной репликации, при котором реплики не копируют данные из S3 друг другу, а создают ссылки на один и тот же физический объект в хранилище.

**ZXC Codec** — специализированный кодек сжатия для данных на S3 (v26.7+), оптимизированный для баланса между степенью сжатия (экономия трафика) и скоростью декомпрессии (минимальная нагрузка на CPU).

**Named Collections** — наборы параметров подключения к S3-совместимым хранилищам, хранимые в XML-конфигурации ClickHouse и используемые через `CREATE NAMED COLLECTION`.

**SSE-C (Server-Side Encryption with Customer-provided keys)** — шифрование на стороне S3 с ключом, управляемым клиентом. Ключ передаётся через `server_side_encryption_customer_key_base64`.

**SSE-KMS (Server-Side Encryption with AWS KMS)** — шифрование на стороне S3 с ключом из AWS KMS. Поддерживает `server_side_encryption_kms_key_id`, `server_side_encryption_kms_encryption_context`, `server_side_encryption_kms_bucket_key_enabled`.

**proxy_resolver** — механизм проксирования S3-трафика через HTTP/S proxy. Конфигурируется через `<proxy>` в XML или переменные окружения `http_proxy`/`https_proxy`.

**S3Queue** — движок таблицы (v23.11+), который отслеживает новые файлы в S3-бакете и автоматически загружает их, поддерживает Exactly-once через ClickHouse Keeper.

**Tiered Storage Policy** — политика хранения, объединяющая несколько дисков/volume в единое пространство с автоматическим перемещением данных между тирами.

**metadata_path** — локальный путь на узле ClickHouse для хранения метаданных S3-диска.

**filesystem_caches** — XML-секция конфигурации для File Cache, содержащая `<path>`, `<max_size>`, `<cache_on_write_operations>` и другие параметры.

**filesystem_cache_settings** — таблица `system.filesystem_cache_settings` для мониторинга конфигурации File Cache.

## Основные концепции

### Способы взаимодействия

1. **Табличная функция `s3()`:** ad-hoc запросы к файлам. Поддерживает `glob` (например, `data/*.parquet`) и автоматический вывод схемы.

2. **Функция `s3Cluster()`:** выполняет запросы распределенно, используя вычислительную мощность всего кластера для параллельного чтения из S3.

3. **Движок таблицы `S3`:** постоянный интерфейс к данным в бакете. При вставке в такую таблицу данные физически отправляются в S3.

4. **Движок `S3Queue` (v23.11+):** аналог Kafka для S3. ClickHouse следит за новыми файлами в бакете и автоматически загружает их. Поддерживает Exactly-once через Keeper.

5. **Многоуровневое хранение (Tiered Storage):** прозрачное перемещение "холодных" данных из локальных SSD в S3-совместимое хранилище. Для приложения это остается одной таблицей `MergeTree`. Детальное описание Tiered Storage см. в [ClickHouse Performance](./clickhouse-performance.md#уровни-хранения-ttl-и-tiered-storage).

### Архитектура взаимодействия

ClickHouse взаимодействует с S3 через собственную реализацию S3 API клиента. При чтении данных:

1. Запрос поступает в локальный MergeTree
2. Для частей данных на S3 ClickHouse проверяет File Cache
3. При cache miss данные читаются из S3 через параллельные потоки
4. Прочитанные гранулы кэшируются на локальном SSD
5. При записи "холодные" части перемещаются в S3 согласно TTL/политике

### Репликация и Zero-copy

**Zero-copy replication:** критическая технология для кластеров.
- **Как это работает:** Реплики в кластере не копируют данные из S3 друг другу. Они создают в S3 ссылки на один и тот же физический объект (data part).
- **Координация:** Все метаданные о владениях частями данных синхронизируются через **ClickHouse Keeper**.
- **Преимущество:** Экономия до N раз дискового пространства в S3 (где N — количество реплик).

### Производительность и кэширование

Для компенсации сетевых задержек (latencies) при работе с S3 используется **File Cache**:
- **Механизм:** ClickHouse сохраняет "горячие" блоки данных из S3 на локальном SSD узла.
- **ZXC Codec (v26.7+):** Специализированный кодек для S3. Он оптимизирован для баланса между степенью сжатия (экономия трафика S3) и скоростью декомпрессии (минимизация нагрузки на CPU).
- **Parallel Reading:** ClickHouse умеет читать один файл из S3 в несколько потоков, что позволяет утилизировать широкие сетевые каналы (10–40 Gbps).

### Безопасность в on-prem средах

**Важное изменение:** ClickHouse больше не использует IAM-роли или переменные окружения сервера автоматически для SQL-запросов пользователей.
- **Named Collections:** Рекомендуемый способ. Учетные данные прописываются в XML-конфиге, а в SQL используется только имя коллекции. Детальное описание см. в [ClickHouse Operations](./clickhouse-operations.md#шифрование-и-named-collections).
- **Strict Mode:** По умолчанию анонимный доступ запрещен, если не указано иное в настройках.

### Шифрование S3 (SSE-C и SSE-KMS)

ClickHouse поддерживает два режима серверного шифрования для объектов в S3:

- **SSE-C (Customer-provided keys):** ключ шифрования управляется клиентом и передаётся через `server_side_encryption_customer_key_base64` (base64-кодированный 256-битный ключ AES). ClickHouse добавляет заголовок `x-amz-server-side-encryption-customer-algorithm: AES256` к каждому `PutObject`/`GetObject`.
- **SSE-KMS (AWS KMS):** шифрование с ключом из AWS KMS. Поддерживаются:
  - `server_side_encryption_kms_key_id` — ARN или alias KMS-ключа (пустая строка = AWS managed key).
  - `server_side_encryption_kms_encryption_context` — контекст шифрования (дополнительный authenticated data).
  - `server_side_encryption_kms_bucket_key_enabled` — использует S3 Bucket Keys для снижения нагрузки на KMS (экономит до 99% запросов к KMS).

> **Важно:** SSE-KMS заголовки нужно подписать. ClickHouse делает это автоматически — не используйте `header` для KMS-заголовков, так как они добавляются после подписи запроса (issue #48723, PR #48724).

```xml
<s3_disk>
    <type>s3</type>
    <endpoint>http://minio.internal:9000/clickhouse-data/</endpoint>
    <access_key_id>MINIO_ACCESS_KEY</access_key_id>
    <secret_access_key>MINIO_SECRET_KEY</secret_access_key>
    <server_side_encryption_kms_key_id>arn:aws:kms:eu-west-1:123456789:key/abcd-1234</server_side_encryption_kms_key_id>
    <server_side_encryption_kms_bucket_key_enabled>true</server_side_encryption_kms_bucket_key_enabled>
</s3_disk>
```

## Подготовка и требования

### Железо и ОС

- **ClickHouse сервер:** CPU с поддержкой SSE 4.2 или AVX-512, RAM минимум 16 GB (рекомендуется 32+ GB для File Cache), локальный SSD/NVME для hot tier и кэша.
- **S3-совместимое хранилище:** MinIO, Ceph RGW, или аналогичное решение с redundant storage.
- **Сеть:** низкая задержка между узлами ClickHouse и S3 endpoint (рекомендуется 10 GbE или выше), MTU 9000 (jumbo frames) для высокопроизводительных сред.
- **Лимиты ОС:**
  - `fs.file-max` минимум 100000
  - `vm.max_map_count` минимум 262144
  - Отключение Transparent Huge Pages (THP) рекомендуется

### Предварительные условия

- **ClickHouse:** Версия 22.8+ (для базовых функций), рекомендуется 26.9+ для полной поддержки безопасности, кэширования и ZXC Codec.
- **Бакет:** Создан в S3-совместимом хранилище (MinIO, Ceph RGW).
- **Права доступа:** `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket`. Для Zero-copy требуются расширенные права на управление версиями объектов.
- **Сетевая связность:** Низкая задержка между узлами ClickHouse и эндпоинтом S3.

## Практические сценарии

### 1. Настройка Tiered Storage (SSD + S3)

Это наиболее распространенный сценарий для on-prem аналитических БД.

**Конфигурация `storage_configuration` для MinIO:**
```xml
<clickhouse>
    <filesystem_caches>
        <s3_cache>
            <path>/var/lib/clickhouse/filesystem_cache/s3/</path>
            <max_size>200Gi</max_size>
            <cache_on_write_operations>true</cache_on_write_operations>
        </s3_cache>
    </filesystem_caches>
    <storage_configuration>
        <disks>
            <s3_disk>
                <type>s3</type>
                <endpoint>http://minio.internal:9000/clickhouse-data/</endpoint>
                <access_key_id>MINIO_ACCESS_KEY</access_key_id>
                <secret_access_key>MINIO_SECRET_KEY</secret_access_key>
                <metadata_path>/var/lib/clickhouse/disks/s3_disk/</metadata_path>
                <cache_name>s3_cache</cache_name>
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
CREATE TABLE events (
    event_id UInt64,
    event_type String,
    payload String,
    created_at DateTime
) ENGINE = MergeTree()
ORDER BY (event_type, created_at)
PARTITION BY toYYYYMM(created_at)
TTL created_at + INTERVAL 14 DAY TO DISK 's3_disk' -- Переместить через 2 недели
SETTINGS storage_policy = 'tiered_policy';
```

### 2. Использование Named Collections для S3

Рекомендуемый способ абстрагировать параметры подключения к S3 — Named Collections. Учётные данные хранятся в XML-конфиге, а в SQL используется только имя коллекции.

**XML-конфигурация** (`/etc/clickhouse-server/config.d/s3_collections.xml`):
```xml
<clickhouse>
    <named_collections>
        <s3_prod>
            <endpoint>http://minio.internal:9000/clickhouse-prod/</endpoint>
            <access_key_id>prod_access_key</access_key_id>
            <secret_access_key>prod_secret_key</secret_access_key>
            <!-- SSE-KMS -->
            <server_side_encryption_kms_key_id>arn:aws:kms:eu-west-1:123:key/abcd</server_side_encryption_kms_key_id>
        </s3_prod>
    </named_collections>
</clickhouse>
```

**DDL-альтернатива** (с версии 23.3):
```sql
CREATE NAMED COLLECTION s3_prod AS
    endpoint = 'http://minio.internal:9000/clickhouse-prod/',
    access_key_id = 'prod_access_key',
    secret_access_key = 'prod_secret_key';
```

**Использование в SQL:**
```sql
-- Табличная функция s3()
SELECT count() FROM s3(s3_prod, url='data/*.parquet', format='Parquet');

-- S3Queue
CREATE TABLE import_queue (...)
ENGINE = S3Queue(s3_prod, url='incoming/*.json', format='JSONEachRow');

-- Резервное копирование через clickhouse-backup
BACKUP TABLE events TO S3(s3_prod);
```

> **Важно:** XML-конфиги работают с `BACKUP/RESTORE`, SQL-коллекции — только в 26.9+ (issue #94604, PR #94605).

### 3. Настройка File Cache для S3

File Cache компенсирует сетевые задержки при чтении из S3, сохраняя "горячие" блоки на локальном SSD.

**XML-конфигурация** (`/etc/clickhouse-server/config.d/filesystem_cache.xml`):
```xml
<clickhouse>
    <filesystem_caches>
        <s3_cache>
            <path>/var/lib/clickhouse/filesystem_cache/s3/</path>
            <max_size>200Gi</max_size>
            <max_elements>10000000</max_elements>
            <max_file_segment_size>1Gi</max_file_segment_size>
            <!-- Запись в кэш при INSERT и слияниях -->
            <cache_on_write_operations>true</cache_on_write_operations>
            <!-- Размер кэша = 70-80% от SSD -->
            <max_size_ratio_to_total_space>0.75</max_size_ratio_to_total_space>
        </s3_cache>
    </filesystem_caches>
</clickhouse>
```

**Подключение к S3-диску:**
```xml
<s3_disk>
    <type>s3</type>
    <endpoint>http://minio.internal:9000/clickhouse-data/</endpoint>
    <access_key_id>MINIO_ACCESS_KEY</access_key_id>
    <secret_access_key>MINIO_SECRET_KEY</secret_access_key>
    <!-- Ссылка на File Cache -->
    <cache_name>s3_cache</cache_name>
</s3_disk>
```

**Настройки на уровне запросов (session settings):**
| Setting | Default | Описание |
| --- | --- | --- |
| `enable_filesystem_cache` | `true` | Включить/выключить использование кэша для запроса |
| `filesystem_cache_max_download_size` | — | Максимальный размер, который может быть загружен в кэш одним запросом |
| `filesystem_cache_skip_download_if_exceeds_per_query_cache_write_limit` | `true` | Пропускать загрузку, если превышен лимит кэша на запрос |

### 4. Настройка прокси для S3

Для on-prem сред с прокси-сервером:

```xml
<storage_configuration>
    <disks>
        <s3>
            <type>s3</type>
            <endpoint>http://minio.internal:9000/clickhouse-data/</endpoint>
            <access_key_id>MINIO_ACCESS_KEY</access_key_id>
            <secret_access_key>MINIO_SECRET_KEY</secret_access_key>
        </s3>
    </disks>
    <!-- Явный proxy URI -->
    <proxy>
        <uri>http://proxy.corp.local:3128</uri>
    </proxy>
    <policies>
        <s3_policy>
            <volumes>
                <main><disk>s3</disk></main>
            </volumes>
        </s3_policy>
    </policies>
</storage_configuration>
```

Можно также использовать `<proxy><resolver>` для динамического решения адреса прокси.

Если `<proxy>` не указан, ClickHouse использует переменные окружения `http_proxy`/`https_proxy` (precedence: remote resolver → list resolver → environment).

### 5. Использование S3Queue для автозагрузки

Идеально для ETL-процессов из внешних систем через S3.

```sql
CREATE TABLE s3_import_queue (
    event_id UInt64,
    data String,
    loaded_at DateTime DEFAULT now()
) ENGINE = S3Queue(
    'http://minio.internal:9000/bucket/incoming/*.json',
    'JSONEachRow'
)
SETTINGS
    s3queue_mode = 'ordered',
    s3queue_last_processed_path = '/clickhouse/s3queue/import';
```

### 6. Работа с Data Lake (Iceberg / Delta Lake)

ClickHouse позволяет читать данные напрямую из форматов Data Lake на S3-совместимых хранилищах.

```sql
-- Запрос к Apache Iceberg на MinIO
SELECT * FROM iceberg(
    'http://minio.internal:9000/warehouse/db/table',
    'ICEBERG_ACCESS_KEY',
    'ICEBERG_SECRET_KEY'
) WHERE dt = today();
```

## Валидация и проверка

После настройки выполните следующие проверки:

1. **Проверка размещения данных:**
    ```sql
    SELECT name, disk_name, path FROM system.parts WHERE table = 'events';
    -- Убедитесь, что disk_name показывает 's3_disk' для старых партиций.
    ```
2. **Эффективность кэша:**
    ```sql
    -- Настройки File Cache
    SELECT cache_name, max_size, current_size, current_elements_num
    FROM system.filesystem_cache_settings
    WHERE cache_name = 's3_cache';

    -- Статистика попаданий в кэш (entries)
    SELECT cache_name, count() AS entries, sum(size) AS total_size
    FROM system.filesystem_cache
    WHERE cache_name = 's3_cache'
    GROUP BY cache_name;
    ```
3. **Проверка Zero-copy:**
    ```sql
    SELECT remote_path, count() as refs
    FROM system.s3_attachments
    GROUP BY remote_path HAVING refs > 1;
    ```
4. **Здоровье слияний:**
    ```sql
    SELECT database, table, count() as active_merges
    FROM system.merges
    WHERE table = 'events'
    GROUP BY database, table;
    ```

## Мониторинг и операции

### Мониторинг S3-специфичных метрик

Для on-prem сред рекомендуемые SRE-алерты:

| Метрика | Источник | Порог |
| --- | --- | --- |
| Hit rate File Cache | `system.filesystem_cache` | < 80% — алерт |
| Размер кэша / capacity | `system.filesystem_cache_settings` | `current_size / max_size` > 95% — алерт |
| Количество элементов кэша | `system.filesystem_cache_settings` | Рост без снижения |
| Latency S3 запросов P99 | `system.query_log` / `system.s3_query_log` | > 500ms — алерт |
| Ошибки S3 запросов | `system.query_log` | > 1% — алерт |

**Запросы для диагностики:**

```sql
-- Текущие S3 запросы и их статус
SELECT query_id, query_start_time, reading_time, result_rows, result_bytes
FROM system.query_log
WHERE query_kind = 'Select' AND is_initial_query = 1
  AND query LIKE '%s3%'
  AND event_time > now() - INTERVAL 5 MINUTE
ORDER BY query_start_time DESC;

-- S3 ошибки в логах
SELECT exception, count() AS cnt
FROM system.query_log
WHERE exception LIKE '%S3%'
  AND event_time > now() - INTERVAL 1 HOUR
GROUP BY exception ORDER BY cnt DESC;

-- Мониторинг File Cache
SELECT
    cache_name,
    formatReadableSize(max_size) AS max_size,
    formatReadableSize(current_size) AS current_size,
    round(100 * current_size / max_size, 1) AS fill_percent,
    current_elements_num AS entries
FROM system.filesystem_cache_settings
WHERE cache_name = 's3_cache';
```

### Резервное копирование на S3

Используйте `clickhouse-backup` с S3-совместимым хранилищем:

```yaml
# /etc/clickhouse-backup/config.d/s3.yaml
objectStorage:
  type: s3
  s3:
    endpoint: http://minio.internal:9000
    access_key: MINIO_ACCESS_KEY
    secret_key: MINIO_SECRET_KEY
    bucket: clickhouse-backups
    region: us-east-1
    disable_ssl: true
```

```bash
# Создание бэкапа
clickhouse-backup create daily_backup
# → Backup daily_backup created successfully

# Загрузка в S3
clickhouse-backup upload daily_backup
# → Uploaded daily_backup to s3://clickhouse-backups/
```

## DevOps / SRE: операционные процедуры

### Управление File Cache

```bash
# Просмотр кэшей
SYSTEM DESCRIBE FILESYSTEM CACHE;

# Очистка кэша по имени
SYSTEM DROP FILESYSTEM CACHE s3_cache;

# Очистка всего кэша
SYSTEM DROP FILESYSTEM CACHE ALL;
```

```sql
-- Принудительная очистка кэша программно
SYSTEM DROP FILESYSTEM CACHE s3_cache;

-- Проверка состояния кэша после очистки
SELECT current_size, current_elements_num FROM system.filesystem_cache_settings
WHERE cache_name = 's3_cache';
```

### Очистка orphaned S3-объектов

ClickHouse удаляет объекты из S3 при `DROP TABLE`, но при аварийных остановках могут остаться "сироты". Проверка и очистка:

```sql
-- Проверка ссылок на S3-объекты
SELECT remote_path, count() AS refs
FROM system.s3_attachments
GROUP BY remote_path;

-- Поиск detached parts (потерянные части)
SELECT database, table, partition, name, disk_name
FROM system.detached_parts WHERE disk_name = 's3_disk';
```

```bash
# Ручная очистка orphaned объектов через s3cmd
s3cmd del s3://clickhouse-data/orphaned_objects/list.txt --endpoint=http://minio.internal:9000
```

### Диагностика S3-соединения

```sql
-- Проверка доступности S3
SELECT count() FROM s3(
    'http://minio.internal:9000/clickhouse-data/test_connection',
    'MINIO_ACCESS_KEY', 'MINIO_SECRET_KEY'
);

-- Проверка multipart загрузок
SYSTEM FLUSH DISTRIBUTED;

-- Сброс S3 клиентского пула (после смены proxy/ключей)
SYSTEM RESTART REPLICAS;
```

### SRE-настройки сервера

Ключевые серверные настройки для S3 (изменяются без перезапуска через `SYSTEM RELOAD CONFIG`):

| Настройка | Default | Описание |
| --- | --- | --- |
| `s3_max_redirects` | `10` | Максимальное количество HTTP-редиректов |
| `s3_retry_attempts` | `500` | Количество попыток при S3-ошибках (0 = без retries) |
| `s3_max_single_part_upload_size` | `32Mb` | Максимальный размер для single-part upload |
| `s3_min_upload_part_size` | `16Mb` | Минимальный размер части для multipart upload |
| `s3_max_inflight_parts_for_one_file` | `20` | Макс. параллельных частей для одного файла |
| `s3_allow_parallel_part_upload` | `false` | Параллельная multipart загрузка |
| `s3_allow_multipart_copy` | `false` | Разрешить multipart copy |
| `s3_load_table_anonymously_if_credentials_restricted` | `1` | Не падать при старте, если S3-объекты не могут аутентифицироваться |

### Очистка и обслуживание

- `SYSTEM DROP FILESYSTEM CACHE s3_cache` — очистка кэша при проблемах с повреждением
- `OPTIMIZE TABLE ... FINAL` — ускоренное слияние для освобождения S3-объектов после TTL
- `ALTER TABLE ... MATERIALIZE TTL` — принудительное применение TTL для перемещения холодных данных
- Аудит orphaned S3-объектов раз в месяц через `system.s3_attachments`

### Аварийное восстановление

1. Восстановите на новый кластер с тем же S3 endpoint
2. Убедитесь, что `metadata_path` доступен и идентичен
3. Используйте `clickhouse-backup restore` для восстановления метаданных
4. Проверьте целостность данных через `system.parts` и `system.s3_attachments`

## Устранение неисправностей

| Ошибка / Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **403 Access Denied** | Неверные ключи или отсутствие прав на бакет | Проверьте ключи доступа. Убедитесь, что `ListBucket` разрешен. |
| **404 Not Found** | Ошибка в эндпоинте или пути к файлу | Проверьте URL эндпоинта. Для MinIO: `http://minio.internal:9000`. |
| **Connection Timeout** | Проблемы с DNS или Firewall | Проверьте `allow_remote_hosts` в `config.xml`. Проверьте MTU сети. |
| **Slow S3 queries** | Отсутствие кэша или медленная сеть | Включите File Cache. Увеличьте `max_size` в `<filesystem_caches>`. Используйте `s3Cluster` для распараллеливания. |
| **Zero-copy duplicate parts** | Неверная конфигурация metadata_path | Убедитесь, что все узлы используют одинаковый `metadata_path` в конфиге S3-диска. |
| **File Cache не эффективен** | Слишком маленький max_size | Увеличьте `max_size` до 10–20% от размера hot данных. |
| **Высокая латентность S3** | Медленная сеть или перегруженный S3 endpoint | Проверьте сетевые линки. Увеличьте `s3_max_inflight_parts_for_one_file`, используйте `s3Cluster`. |
| **Потеря данных при сбое** | Отсутствие версионирования в S3 | Включите версионирование на бакете для защиты от случайного удаления. |
| **Ошибка SSE-KMS при HEAD/UploadPart** | KMS-заголовки не подписываются | Используйте `server_side_encryption_kms_key_id` в конфиге диска, а не `header` в SQL (issue #64570). |
| **Zero-copy конфликты в кластере** | `allow_remote_fs_zero_copy_replication = true` в 22.7 | В 22.8+ disabled by default. Если используете < 22.8, установите в `false` для DR-сценариев. |
| **Сироты после DROP TABLE** | Сбои при удалении частей с S3 | Проверьте `system.s3_attachments` и удалите orphaned объекты вручную через `s3cmd` или AWS CLI. |
| **File Cache заполняет SSD** | `cache_on_write_operations=true` + большой INSERT | Сократите `max_size`, настройте `max_size_ratio_to_total_space`, или отключите `cache_on_write_operations`. |

## Лучшие практики

- **Размер объектов:** ClickHouse работает лучше с меньшим количеством крупных файлов. Избегайте миллионов мелких файлов в одном префиксе S3.
- **Cache Warming:** После рестарта узла кэш "холодный". Выполните запросы к "горячим" данным для прогрева File Cache (ClickHouse автоматически кэширует прочитанные блоки).
- **Версионирование S3:** Включайте версионирование на бакете для защиты данных и работы Zero-copy, чтобы избежать случайного удаления данных при конфликтах имен.
- **Очистка (Cleanup):** ClickHouse сам удаляет объекты из S3 при `DROP TABLE`, но при сбоях могут остаться "сироты". Раз в месяц проводите аудит через `system.s3_attachments`.
- **Сетевая изоляция:** Разместите S3 endpoint в той же сети, что и ClickHouse узлы. Используйте VLAN или отдельный сегмент для трафика к объектному хранилищу.
- **Мониторинг:** Настройте алерты на падение hit rate File Cache ниже 80% и рост latency S3 запросов.
- **Бэкапы:** Регулярно тестируйте восстановление из S3-бэкапов. Храните бэкапы в отдельном бакете от рабочих данных.
- **Емкость:** Планируйте емкость S3 с запасом 30–50% для роста данных и операций слияния.
- **Шифрование:** Используйте SSE-KMS с `server_side_encryption_kms_bucket_key_enabled=true` для снижения нагрузки на KMS. Не храните ключи в SQL — используйте Named Collections.
- **Прокси:** Для on-prem сред с прокси используйте `<proxy><uri>` в конфиге диска или переменные окружения `http_proxy`/`https_proxy`.

## Дополнительная информация

### Смежные темы
- Основной обзор системы — **[ClickHouse](./clickhouse.md)**.
- Производительность и Tiered Storage — **[ClickHouse Performance](./clickhouse-performance.md)**.
- Эксплуатация, безопасность и бэкапы — **[ClickHouse Operations](./clickhouse-operations.md)**.
- Кластерное управление и Keeper — **[ClickHouse Cluster](./clickhouse-cluster.md)**.
- Интеграция с Kafka — **[ClickHouse и Kafka](./clickhouse_kafka_integration.md)**.
- Общая теория объектных хранилищ — **[Yandex Storage](../../Yandex/Storage/storage_concepts.md)**.

### Ресурсы
- [Документация: S3 Storage Engine](https://clickhouse.com/docs/ru/engines/table-engines/integrations/s3/)
- [Документация: S3 Table Function](https://clickhouse.com/docs/ru/sql-reference/table-functions/s3/)
- [Документация: s3Cluster Table Function](https://clickhouse.com/docs/ru/sql-reference/table-functions/s3Cluster/)
- [Документация: Tiered Storage](https://clickhouse.com/docs/ru/engines/table-engines/mergetree-family/mergetree#table_engine-mergetree-tiered-storage)
- [Документация: File Cache (Filesystem Cache)](https://clickhouse.com/docs/ru/operations/tables/filesystem_cache/)
- [Документация: Named Collections](https://clickhouse.com/docs/ru/operations/named_collections/)
- [Документация: Хранилище данных на сервере](https://clickhouse.com/docs/ru/operations/storing-data/)
- [Документация: Настройки S3](https://clickhouse.com/docs/ru/reference/settings/server-settings/settings/s3)
