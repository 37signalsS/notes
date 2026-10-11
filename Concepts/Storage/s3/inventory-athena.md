# S3: Inventory, анализ данных и cost-оптимизация

**Актуально для:** Ceph RGW (Squid 19.x / Tentacle 20.x / Umbrella 21.x)

---

## 1. Определения

**S3 Inventory** — сервис, генерирующий ежедневные/еженедельные отчёты о всех объектах в bucket (ключ, размер, Storage Class, статус шифрования, версия). Доступен в Ceph RGW.

**Inventory report format** — формат отчёта: CSV, ORC, Parquet. CSV — универсальный, Parquet — для аналитики (меньший размер, быстрее запросы).

**S3 Inventory** — единственный способ получить полный список объектов в bucket (особенно для миллионов объектов).

**Cost anomaly** — неожиданный рост затрат на хранилище. Обнаруживается через анализ метрик и алерты.

**Unused data** — объекты в S3, к которым нет доступа более N дней. Определяется через Inventory + Access Logs.

---

## 2. Базовые концепции

### 2.1 S3 Inventory: зачем нужен

Inventory — единственный способ получить полный список объектов в bucket:

| Сценарий | Использование Inventory |
|----------|------------------------|
| **Audit compliance** | Проверка encryption status, Object Lock, retention |
| **Cost optimization** | Поиск неиспользуемых объектов, анализ Storage Class |
| **Lifecycle validation** | Проверка, что lifecycle policies применяются корректно |
| **Data migration** | Планирование миграции между buckets/регионами |
| **Security** | Обнаружение orphaned объектов, публичный доступ |

**Важно:** Inventory — eventual consistency. Отчёт за сегодня появляется в течение 24–48 часов.

### 2.2 Форматы отчётов

| Формат | Размер | Скорость запросов | Использование |
|--------|--------|------------------|---------------|
| **CSV** | Большой (text) | Медленный | Универсальный, Excel, grep |
| **ORC** | Средний | Быстрый | Аналитика, компрессия |
| **Parquet** | Малый | Самый быстрый | Аналитика, Big Data |

**Рекомендация:** Используйте **Parquet + Snappy** для production-аналитики. В 3–5 раз меньше места и быстрее запросы. CSV — только для быстрых проверок.

---

## 3. Практические сценарии

### 3.1 Настройка S3 Inventory (CSV)

**Важно:** В Ceph RGW destination bucket указывается по имени, без AWS ARN. Формат `arn:aws:s3:::bucket` не используется в RGW-совместимых конфигурациях.

```bash
# Создание Inventory configuration
aws s3api put-bucket-inventory-configuration \
  --bucket my-app-archives \
  --id my-inventory \
  --inventory-configuration '{
    "Destination": {
      "S3BucketDestination": {
        "Bucket": "my-inventory-bucket",
        "Prefix": "inventory/",
        "Format": "CSV"
      }
    },
    "IsEnabled": true,
    "Schedule": {"Frequency": "Daily"},
    "IncludedObjectVersions": "All",
    "OptionalFields": [
      "Size", "LastModifiedDate", "StorageClass",
      "EncryptionStatus", "BucketKeyStatus", "ReplicationStatus"
    ]
  }' \
  --endpoint-url http://rgw:7480
```

### 3.2 Настройка S3 Inventory (Parquet)

```bash
# Parquet + сжатие Snappy
aws s3api put-bucket-inventory-configuration \
  --bucket my-app-archives \
  --id my-inventory-parquet \
  --inventory-configuration '{
    "Destination": {
      "S3BucketDestination": {
        "Bucket": "my-inventory-bucket",
        "Prefix": "inventory-parquet/",
        "Format": "Parquet",
        "Compression": "Snappy"
      }
    },
    "IsEnabled": true,
    "Schedule": {"Frequency": "Daily"},
    "IncludedObjectVersions": "All",
    "OptionalFields": [
      "Size", "LastModifiedDate", "StorageClass",
      "EncryptionStatus", "IsMultipartUploaded"
    ]
  }' \
  --endpoint-url http://rgw:7480
```

### 3.3 Анализ Inventory через Python/pandas

```python
import pandas as pd

# Чтение S3 Inventory CSV
# Для больших файлов (>1 ГБ) используйте polars или dask вместо pandas
df = pd.read_csv("s3-inventory.csv")

# Анализ Storage Class распределения
print(df['StorageClass'].value_counts())

# Анализ размера объектов
print(f"Общий размер: {df['Size'].sum() / 1e9:.2f} GB")
print(f"Средний размер объекта: {df['Size'].mean() / 1e6:.2f} MB")
print(f"Медианный размер: {df['Size'].median() / 1e6:.2f} MB")

# Выявление маленьких файлов (< 1 МБ)
small_files = df[df['Size'] < 1e6]
print(f"Маленьких файлов: {len(small_files)} ({len(small_files)/len(df)*100:.1f}%)")

# Анализ по prefix
df['Prefix'] = df['Key'].str.split('/').str[0]
print(df.groupby('Prefix')['Size'].sum().sort_values(ascending=False))
```

### 3.4 Анализ через SQL (PostgreSQL, ClickHouse, DuckDB)

Для анализа inventory данных можно импортировать CSV/Parquet в локальную или серверную БД и выполнять SQL-запросы. Для аналитики на лету без импорта подходит DuckDB.

```sql
-- Создание таблицы
CREATE TABLE s3_inventory (
  bucket STRING,
  key STRING,
  size BIGINT,
  storage_class STRING,
  last_modified_date DATE,
  is_delete_marker BOOLEAN
);

-- Импорт CSV
COPY s3_inventory FROM '/path/to/s3-inventory.csv' WITH CSV HEADER;

-- Топ-10 prefix'ов по размеру
SELECT
  regexp_extract(key, '^([^/]+)/') as prefix,
  SUM(size) as total_size,
  COUNT(*) as object_count
FROM s3_inventory
WHERE bucket = 'my-app-archives'
GROUP BY prefix
ORDER BY total_size DESC
LIMIT 10;

-- Объекты в Standard > 90 дней (candidate для lifecycle)
SELECT
  key,
  size,
  storage_class,
  last_modified_date
FROM s3_inventory
WHERE bucket = 'my-app-archives'
  AND storage_class = 'STANDARD'
  AND last_modified_date < CURRENT_DATE - INTERVAL '90 days'
ORDER BY size DESC
LIMIT 100;

-- Объекты без Object Lock (compliance audit)
SELECT
  COUNT(*) as unprotected_objects,
  SUM(size) as unprotected_size
FROM s3_inventory
WHERE bucket = 'my-app-archives'
  AND object_lock_mode IS NULL;

-- Распределение по Storage Class
SELECT
  storage_class,
  COUNT(*) as count,
  SUM(size) as total_size,
  SUM(size) / 1024 / 1024 / 1024 as size_gb
FROM s3_inventory
WHERE bucket = 'my-app-archives'
GROUP BY storage_class
ORDER BY size_gb DESC;

-- Поиск маленьких файлов (< 1 MB)
SELECT
  COUNT(*) as small_files,
  SUM(size) as total_size
FROM s3_inventory
WHERE bucket = 'my-app-archives'
  AND size < 1048576;
```

---

## 4. Cost optimization

### 4.1 Обнаружение неиспользуемых данных

```python
import pandas as pd

df = pd.read_csv('s3-inventory.csv')

# Объекты, к которым не было доступа > 180 дней (по LastModified)
df['last_modified_date'] = pd.to_datetime(df['last_modified_date'])
old_objects = df[df['last_modified_date'] < pd.Timestamp.now() - pd.Timedelta(days=180)]
print(f"Неиспользуемых объектов: {len(old_objects)}")
print(f"Объём неиспользуемых данных: {old_objects['Size'].sum() / 1e9:.2f} GB")
```

### 4.2 Относительная стоимость tiering

Для self-hosted Ceph RGW стоимость определяется аппаратной базой (SSD vs HDD vs EC pools) и операционными расходами, а не облачными тарифами.

| Слой | Тип диска | Относительная стоимость | Сценарий |
|------|-----------|------------------------|----------|
| **Hot** | NVMe/SSD | Максимальная | Активные артефакты, текущие бэкапы |
| **Warm** | HDD | Средняя | Артефакты старше 30 дней, редко читаемые |
| **Cold** | HDD/EC | Минимальная | Архивы, compliance логи, долгосрочное хранение |

**Оценка:** Для 100 ТБ данных переход с replicated HDD (3x replica) на EC (4+2) даёт экономию места ~40% при той же durability. Дополнительный переход на холодные EC pools с ленивыми дисками снижает операционные расходы.

### 4.3 Lifecycle automation через Inventory insights

```bash
# На основе Inventory данных: создание lifecycle policy
# Полный JSON schema lifecycle rules см. в glacier-restore.md раздел 2.2
aws s3api put-bucket-lifecycle-configuration \
  --bucket my-app-archives \
  --lifecycle-configuration '{
    "Rules": [
      {
        "ID": "OptimizeCosts",
        "Status": "Enabled",
        "Filter": {"Prefix": "logs/"},
        "Transitions": [
          {"Days": 7, "StorageClass": "WARM"},
          {"Days": 90, "StorageClass": "COLD"}
        ],
        "NoncurrentVersionTransitions": [
          {"Days": 7, "StorageClass": "WARM"},
          {"Days": 30, "StorageClass": "COLD"}
        ],
        "NoncurrentVersionExpiration": {"NoncurrentDays": 90},
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}
      }
    ]
  }' \
  --endpoint-url http://rgw:7480
```

**Важно:** Полный lifecycle JSON дублирует схему из `glacier-restore.md`. Используйте Inventory insights для обоснования параметров (Days, StorageClass), а не для дублирования конфигурации.

---

## 5. Предварительные требования

Для работы с Inventory и аналитикой необходимы:

- **aws-cli 2.x** — основной инструмент для управления S3 Inventory configuration.
- **ceph-common / radosgw-admin** — утилиты для диагностики RGW (bucket stats, placement, config).
- **jq** — для парсинга JSON-вывода `radosgw-admin`.
- **pandas / polars / dask** — для анализа CSV/Parquet отчётов. Для файлов >1 ГБ используйте polars или dask.
- **DuckDB / PostgreSQL / ClickHouse** — для SQL-аналитики. DuckDB подходит для локальной аналитики без отдельного сервера.
- **Доступ к RGW endpoint** — порт 7480 (HTTP) или 443 (HTTPS).
- **Valid credentials** — Access Key ID и Secret Key с правами `s3:GetBucketInventoryConfiguration`, `s3:PutBucketInventoryConfiguration`.
- **Синхронизированные часы** — разница между клиентом и RGW не должна превышать 15 минут (NTP обязателен).
- **Права на `radosgw-admin`** — для проверки bucket placement и RGW config.

```
# Проверка доступности RGW endpoint
curl -s -o /dev/null -w "%{http_code}" http://rgw:7480
# → 403 или 200

# Проверка aws-cli
aws --version
# → aws-cli/2.x Python/3.x Linux/...

# Проверка inventory configuration
aws s3api list-bucket-inventory-configurations \
  --bucket my-app-archives \
  --endpoint-url http://rgw:7480
# → {"InventoryConfigurationList": [...]}

# Проверка bucket placement (Ceph-specific)
radosgw-admin bucket stats --bucket my-app-archives | jq .placement_rule
# → "default-placement"

# Проверка RGC config
ceph config get client.rgw.* rgw_lc_max_worker
# → 3
```

---

## 6. Troubleshooting

| Проблема | Причина | Диагностика | Решение |
|----------|---------|-------------|---------|
| Inventory отчёт пустой | Bucket новый (< 48 часов) или пустой | `aws s3api list-objects-v2 --bucket ...` | Подождите 48 часов |
| Inventory не обновляется | Schedule неактивен | `aws s3api get-bucket-inventory-configuration` → `IsEnabled` | Включите `IsEnabled: true` |
| Партиции Parquet не появляются | Partition projection не настроен | Проверка manifest в S3 destination | Настройте projection для Parquet |
| Запросы к Inventory медленные | Нет partition pruning | `EXPLAIN` SQL запроса | Добавьте partition filter в WHERE |
| Сканирование всей таблицы | Отсутствует partition filter | Проверка `DataScannedInBytes` | Добавьте partition filter |
| Access Denied при создании Inventory | Нет прав на destination bucket | `aws s3api get-bucket-acl --bucket my-inventory-bucket` | Добавьте write permissions для RGW service account |
| Clock skew в отчёте | Разница времени > 15 минут | `date`, `ceph tell <daemon> time` | Синхронизируйте часы через NTP |
| Lifecycle не применяется на основе Inventory | Lifecycle thread отключён | `ceph config get client.rgw.* rgw_enable_lc_threads` | Убедитесь, что `rgw_enable_lc_threads = true` |
| Маленькие файлы доминируют | Много объектов < 1 МБ | `df[df['Size'] < 1e6]` в pandas | Создайте multipart upload policy или lifecycle для объединения |

---

## 7. Consistency and edge cases

### 7.1 Consistency model

| Операция | Консистентность |
|----------|----------------|
| Создание Inventory configuration | Strong (запись метаданных конфигурации) |
| Генерация отчёта | Eventual (отчёт появляется через 24–48 часов) |
| Чтение отчёта из destination bucket | Strong (после появления manifest) |
| Обновление configuration | Eventual |

**Production advice:**
- Inventory — eventual consistency для генерации отчётов. Не планируйте критичные процессы на точное время появления manifest.
- Для больших bucket'ов (>1M объектов) ожидайте верхнюю границу 48 часов.
- Combine Inventory с `radosgw-admin bucket stats` для оперативной оценки размера bucket без ожидания отчёта.

### 7.2 Edge cases

- **Very large buckets (>10M объектов):** Parquet с partition projection обязателен. CSV может превысить лимиты памяти при анализе в pandas.
- **Versioned buckets:** Inventory включает все версии при `IncludedObjectVersions: All`. Это может увеличить размер отчёта в 2–3 раза.
- **Multipart uploads:** Зависшие multipart uploads отображаются в Inventory как отдельные объекты. Используйте `AbortIncompleteMultipartUpload` в lifecycle для очистки.
- **Delete markers:** При `IncludedObjectVersions: All` delete markers присутствуют в отчёте. Фильтруйте по `IsDeleteMarker`.
- **Encryption:** Inventory отображает `EncryptionStatus`, но не показывает детали KMS ключа. Для аудита шифрования используйте `radosgw-admin bucket stats` + `EncryptionStatus` в Inventory.
- **Clock skew:** Разница времени > 15 минут вызывает `403 RequestTimeTooSkewed` при подписи запросов. Для Inventory это не критично, но влияет на `LastModifiedDate` в отчёте.
- **Multisite:** Inventory configuration хранится в zonegroup. При multisite replication configuration не распространяется на удалённые zones автоматически.

---

## 8. Best Practices

1. **Используйте Parquet + Snappy** для Inventory. В 3–5 раз меньше места, быстрее запросы. Для bucket'ов >100k объектов Parquet обязателен.
2. **Настройте Inventory на все production bucket'ы.** Это основа для audit и cost optimization.
3. **Анализируйте Inventory раз в квартал** для поиска неиспользуемых данных. Для больших инфраструктур автоматизируйте через cron + pandas.
4. **Combine Inventory + Access Logs** для точного анализа паттернов доступа. Inventory даёт полный список, Access Logs — паттерны доступа.
5. **В Ceph RGW нет платы за перечисление объектов**, но учитывайте storage costs для destination bucket с Inventory отчётами.
6. **Автоматизируйте cost optimization** через Python/pandas или dask скрипты. На основе Inventory данных создавайте lifecycle policies для перехода в WARM/COLD.
7. **Документируйте Inventory schedule и retention.** Храните Inventory отчёты для compliance audit минимум 1 год.
8. **Тестируйте Parquet import** перед production. Убедитесь, что все поля корректно импортируются в DuckDB/PostgreSQL.
9. **Используйте `radosgw-admin bucket stats`** для оперативной проверки bucket размера без ожидания Inventory отчёта.
10. **Настраивайте partition projection** для Parquet. Это ускоряет запросы в 10+ раз за счёт partition pruning.
11. **Версионирование + Inventory:** При включённом versioning используйте `IncludedObjectVersions: All` только если нужен полный audit. Для обычного analysis используйте `Current` для уменьшения размера отчёта.
12. **Lifecycle worker threads:** Убедитесь, что `rgw_lc_max_worker` достаточен для обработки lifecycle policies, созданных на основе Inventory insights.
13. **Monitor RGW logs** для ошибок генерации Inventory: `ceph log last rgw` или `journalctl -u ceph-rgw`.

---

## 9. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [S3: безопасность, шифрование и compliance](./security.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
- [S3: RGW storage tiering и lifecycle transitions](./glacier-restore.md)
