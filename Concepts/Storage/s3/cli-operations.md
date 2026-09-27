# S3: распространённые операции CLI и эксплуатация

## 1. Определения

**aws-cli** — официальный CLI для AWS services, включая S3. Поддерживает все S3 API операции через команды `aws s3` (high-level) и `aws s3api` (low-level).

**Зачем aws-cli:** Это стандарт де-факто для работы с AWS из командной строки. В production используется для скриптов бэкапов, CI/CD пайплайнов, автоматизации. aws-cli abstrahiрует низкоуровневый REST API, предоставляя удобные команды (`cp`, `sync`, `mb`, `rb`).

**s3cmd** —第三方 CLI для S3, легковесный, удобен для простых операций.

**mc (S3 Client)** — клиент для работы с любым S3-compatible endpoint'ом. Поддерживает алиасы, parallel transfers, mirroring.

**Зачем mc:** mc особенно полезен при работе с self-hosted S3-compatible хранилищами (Ceph RGW, Garage, Yandex Storage), где aws-cli может требовать дополнительных настроек endpoint и SSL. mc позволяет настроить алиасы для разных окружений (prod, staging, dr) и быстро переключаться между ними.

---

## 2. Базовые операции

### 2.1 Установка и конфигурация aws-cli

```bash
# macOS
brew install awscli

# Linux (pip)
pip install awscli

# Проверка версии
aws --version
# → aws-cli/2.17.0 Python/3.12.0 Linux/5.15.0-89-generic botocore/2.17.0

# Конфигурация credentials
aws configure
# AWS Access Key ID [None]: AKIA...
# AWS Secret Access Key [None]: ...
# Default region name [None]: eu-central-1
# Default output format [None]: json

# Проверка конфигурации
aws sts get-caller-identity
# → Account, UserId, Arn
```

**Зачем проверять `get-caller-identity`:** Эта команда проверяет, что credentials валидны и вы знаете, от какого principal (user/role) выполняются запросы. Критично для отладки permission issues.

**Варианты credentials (по приоритету):**
1. **IAM Role** (на EC2/ECS/Lambda) — временные credentials через IMDS, безопаснее всего.
2. **Environment variables** (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`) — удобно для CI/CD.
3. **AWS CLI profiles** (`~/.aws/config` + `~/.aws/credentials`) — для работы с несколькими аккаунтами.
4. **Hardcoded в коде** — **никогда** не делайте так.

### 2.2 Bucket операции

```bash
# Создание bucket (имя должно быть globally unique)
aws s3 mb s3://my-app-prod-assets \
  --region eu-central-1

# Список bucket'ов
aws s3 ls

# Проверка существования bucket
aws s3api head-bucket --bucket my-app-prod-assets

# Удаление bucket (должен быть пустым)
aws s3 rb s3://my-app-prod-assets

# Принудительное удаление bucket со всем содержимым
aws s3 rb s3://my-app-prod-assets --force
```

**Зачем `head-bucket`:** HEAD запрос проверяет существование bucket и ваши permissions на него без возврата содержимого. Используется в скриптах для проверки доступности bucket перед операциями.

**Важно:** `--force` удаляет все объекты в bucket без дополнительных подтверждений. Используйте с осторожностью в production.

### 2.3 Object операции

```bash
# Загрузка одного файла
aws s3 cp ./build/app.tar.gz s3://my-app-prod-assets/releases/v1.2.3/ \
  --storage-class STANDARD_IA \
  --metadata "build-id=abc123,commit=def456" \
  --server-side-encryption aws:kms

# Скачивание файла
aws s3 cp s3://my-app-prod-assets/releases/v1.2.3/app.tar.gz ./downloads/ \
  --storage-class STANDARD

# Синхронизация директории (аналог rsync)
aws s3 sync ./dist/ s3://my-app-prod-assets/static/ \
  --delete \
  --exclude "*.tmp" \
  --exclude ".git/*"

# Обратная синхронизация (S3 → локально)
aws s3 sync s3://my-app-prod-assets/backups/ ./restore/ \
  --exact-timestamps

# Удаление объекта
aws s3 rm s3://my-app-prod-assets/old-backup.tar.gz

# Удаление всех объектов с префиксом
aws s3 rm s3://my-app-prod-assets/logs/ --recursive

# Список объектов
aws s3 ls s3://my-app-prod-assets/releases/
# → 2024-01-15 10:30:00    15MB v1.2.3/app.tar.gz

# Рекурсивный список
aws s3 ls s3://my-app-prod-assets/ --recursive --human-readable --summarize

# Получение метаданных без скачивания
aws s3api head-object \
  --bucket my-app-prod-assets \
  --key releases/v1.2.3/app.tar.gz

# Копирование объекта внутри S3 (server-side)
aws s3 cp s3://my-app-prod-assets/releases/v1.2.3/app.tar.gz \
  s3://my-app-prod-assets/archives/ \
  --storage-class GLACIER_IR
```

**Зачем `sync` вместо `cp`:** `sync` сравнивает локальные и удалённые файлы по размеру и времени модификации, загружает только изменившиеся. Это значительно ускоряет повторные деплои. `--delete` удаляет объекты в S3, которых нет локально (аналог `rsync --delete`).

**Зачем `--exact-timestamps` при обратной синхронизации:** По умолчанию `sync` использует только время модификации для сравнения. `--exact-timestamps` также учитывает миллисекунды, что важно для точного восстановления.

### 2.4 Presigned URLs

```bash
# Генерация presigned URL через aws-cli
aws s3 presign s3://my-app-prod-assets/releases/app.tar.gz \
  --expires-in 3600 \
  --region eu-central-1

# → https://my-app-prod-assets.s3.eu-central-1.amazonaws.com/releases/app.tar.gz?...

# PUT presigned URL (для загрузки от имени сервиса)
aws s3 presign s3://my-app-prod-assets/uploads/${filename} \
  --expires-in 3600 \
  --region eu-central-1 \
  --request-method PUT
```

---

## 3. Bucket политики и конфигурация

### 3.1 Versioning

```bash
# Включение versioning
aws s3api put-bucket-versioning \
  --bucket my-app-prod-assets \
  --versioning-configuration Status=Enabled

# Проверка статуса
aws s3api get-bucket-versioning --bucket my-app-prod-assets

# Список всех версий объекта
aws s3api list-object-versions \
  --bucket my-app-prod-assets \
  --prefix releases/app.tar.gz

# Восстановление предыдущей версии
aws s3api copy-object \
  --bucket my-app-prod-assets \
  --key releases/app.tar.gz \
  --copy-source my-app-prod-assets/releases/app.tar.gz?versionId=VERSION_ID \
  --metadata-directive COPY
```

### 3.2 Lifecycle policies

```bash
# Применение lifecycle configuration
aws s3api put-bucket-lifecycle-configuration \
  --bucket my-app-prod-assets \
  --lifecycle-configuration file://lifecycle.json

# Просмотр текущих правил
aws s3api get-bucket-lifecycle-configuration --bucket my-app-prod-assets

# Удаление всех lifecycle правил
aws s3api delete-bucket-lifecycle --bucket my-app-prod-assets
```

### 3.3 Encryption

```bash
# Включение SSE-KMS по умолчанию
aws s3api put-bucket-encryption \
  --bucket my-app-prod-assets \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "aws:kms",
        "KMSMasterKeyID": "arn:aws:kms:eu-central-1:123456789012:alias/my-key"
      },
      "BucketKeyEnabled": true
    }]
  }'

# Проверка encryption configuration
aws s3api get-bucket-encryption --bucket my-app-prod-assets

# Удаление encryption configuration
aws s3api delete-bucket-encryption --bucket my-app-prod-assets
```

### 3.4 Bucket Policy

```bash
# Применение bucket policy
aws s3api put-bucket-policy \
  --bucket my-app-prod-assets \
  --policy file://bucket-policy.json

# Просмотр policy
aws s3api get-bucket-policy --bucket my-app-prod-assets

# Удаление policy
aws s3api delete-bucket-policy --bucket my-app-prod-assets
```

### 3.5 Public Access Block

```bash
# Включение Block Public Access
aws s3api put-public-access-block \
  --bucket my-app-prod-assets \
  --public-access-block-configuration '{
    "BlockPublicAcls": true,
    "IgnorePublicAcls": true,
    "BlockPublicPolicy": true,
    "RestrictPublicBuckets": true
  }'

# Проверка настроек
aws s3api get-public-access-block --bucket my-app-prod-assets
```

### 3.6 Object Lock

```bash
# Включение Object Lock при создании bucket
aws s3api create-bucket \
  --bucket my-app-prod-assets \
  --object-lock-enabled-for-bucket \
  --region eu-central-1

# Настройка retention по умолчанию
aws s3api put-object-lock-configuration \
  --bucket my-app-prod-assets \
  --object-lock-configuration '{
    "ObjectLockEnabled": "Enabled",
    "Rule": {
      "DefaultRetention": {
        "Mode": "COMPLIANCE",
        "Days": 30
      }
    }
  }'

# Проверка retention для объекта
aws s3api get-object-retention \
  --bucket my-app-prod-assets \
  --key releases/v1.2.3/app.tar.gz
```

### 3.7 Replication

```bash
# Настройка replication configuration
aws s3api put-bucket-replication \
  --bucket my-app-prod-assets \
  --replication-configuration file://replication.json

# Проверка replication status
aws s3api get-bucket-replication --bucket my-app-prod-assets
```

### 3.8 Event Notifications

```bash
# Настройка уведомлений на SQS
aws s3api put-bucket-notification-configuration \
  --bucket my-app-prod-assets \
  --notification-configuration file://notification.json

# Проверка конфигурации
aws s3api get-bucket-notification-configuration --bucket my-app-prod-assets
```

---

## 4. Мониторинг и аудит

### 4.1 Access Logging

```bash
# Включение access logging
aws s3api put-bucket-logging \
  --bucket my-app-prod-assets \
  --bucket-logging-status '{
    "LoggingEnabled": {
      "TargetBucket": "my-app-audit-logs",
      "TargetPrefix": "s3-logs/my-app-prod-assets/"
    }
  }'

# Проверка статуса
aws s3api get-bucket-logging --bucket my-app-prod-assets
```

### 4.2 CloudWatch Metrics

```bash
# Получение метрик через CloudWatch
aws cloudwatch get-metric-statistics \
  --namespace AWS/S3 \
  --metric-name BucketSizeBytes \
  --dimensions Name=BucketName,Value=my-app-prod-assets Name=StorageType,Value=StandardStorage \
  --start-time $(date -u -d '1 day ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 86400 \
  --statistics Average
```

### 4.3 S3 Inventory

```bash
# Настройка S3 Inventory
aws s3api put-bucket-inventory-configuration \
  --bucket my-app-prod-assets \
  --id my-inventory \
  --inventory-configuration '{
    "Destination": {
      "S3BucketDestination": {
        "Bucket": "arn:aws:s3:::my-app-audit-logs",
        "Prefix": "inventory/",
        "Format": "CSV"
      }
    },
    "IsEnabled": true,
    "Schedule": {"Frequency": "Daily"},
    "IncludedObjectVersions": "All",
    "OptionalFields": ["Size", "LastModifiedDate", "StorageClass", "EncryptionStatus"]
  }'
```

---

## 5. Multipart upload

### 5.1 Автоматический multipart (aws-cli)

```bash
# Для файлов > 8 ГБ aws-cli автоматически использует multipart
aws s3 cp large-backup.tar.gz s3://my-app-prod-assets/backups/ \
  --storage-class DEEP_ARCHIVE

# Настройка multipart parameters
aws configure set default.s3.multipart_threshold 64MB
aws configure set default.s3.multipart_chunksize 16MB
```

### 5.2 Ручной multipart (aws s3api)

```bash
# 1. Инициализация
UPLOAD_ID=$(aws s3api create-multipart-upload \
  --bucket my-app-prod-assets \
  --key backups/large-backup.tar.gz \
  --storage-class DEEP_ARCHIVE \
  --query 'UploadId' --output text)

# 2. Загрузка частей (часть 1)
aws s3api upload-part \
  --bucket my-app-prod-assets \
  --key backups/large-backup.tar.gz \
  --part-number 1 \
  --upload-id $UPLOAD_ID \
  --body part-1.tar.gz \
  --query 'ETag' --output text

# 3. Загрузка частей (часть 2)
aws s3api upload-part \
  --bucket my-app-prod-assets \
  --key backups/large-backup.tar.gz \
  --part-number 2 \
  --upload-id $UPLOAD_ID \
  --body part-2.tar.gz \
  --query 'ETag' --output text

# 4. Завершение
aws s3api complete-multipart-upload \
  --bucket my-app-prod-assets \
  --key backups/large-backup.tar.gz \
  --upload-id $UPLOAD_ID \
  --multipart-upload '{
    "Parts": [
      {"ETag": "ETAG1", "PartNumber": 1},
      {"ETag": "ETAG2", "PartNumber": 2}
    ]
  }'

# 5. Отмена (при ошибке)
aws s3api abort-multipart-upload \
  --bucket my-app-prod-assets \
  --key backups/large-backup.tar.gz \
  --upload-id $UPLOAD_ID
```

### 5.3 Просмотр незавершённых загрузок

```bash
# Список незавершённых multipart uploads
aws s3api list-multipart-uploads --bucket my-app-prod-assets

# Детали по конкретному upload
aws s3api list-parts \
  --bucket my-app-prod-assets \
  --key backups/large-backup.tar.gz \
  --upload-id $UPLOAD_ID

# Массовая отмена старых незавершённых загрузок
aws s3api list-multipart-uploads --bucket my-app-prod-assets \
  --query 'Uploads[*].[Key,UploadId]' --output text | while read key upload_id; do
    echo "Aborting: $key ($upload_id)"
    aws s3api abort-multipart-upload \
      --bucket my-app-prod-assets \
      --key "$key" \
      --upload-id "$upload_id"
  done
```

---

## 6. Performance tuning

### 6.1 Parallel transfers

```bash
# Увеличение параллелизма для aws-cli
aws configure set default.s3.max_concurrent_requests 20
aws configure set default.s3.max_queue_size 10000

# Или через переменные окружения
export AWS_MAX_CONCURRENT_REQUESTS=20
export AWS_MAX_QUEUE_SIZE=10000
```

### 6.2 Transfer Acceleration

```bash
# Проверка, включено ли Transfer Acceleration
aws s3api get-bucket-accelerate-configuration --bucket my-app-prod-assets

# Включение
aws s3api put-bucket-accelerate-configuration \
  --bucket my-app-prod-assets \
  --accelerate-configuration Status=Enabled

# Использование accelerated endpoint
aws s3 cp large-file.tar.gz s3://my-app-prod-assets/ \
  --endpoint-url https://my-app-prod-assets.s3-accelerate.amazonaws.com
```

### 6.3 Select (аналитические запросы)

```bash
# SQL-подобный запрос к CSV в S3
aws s3api select-object-content \
  --bucket my-app-prod-assets \
  --key data/large.csv \
  --expression "SELECT * FROM S3Object s WHERE s.status = 'active'" \
  --expression-type SQL \
  --input-serialization '{"CSV": {"FileHeaderInfo": "USE"}}' \
  --output-serialization '{"CSV": {}}' \
  output.csv
```

---

## 7. Troubleshooting

### 7.1 403 Forbidden

```bash
# Проверка bucket policy
aws s3api get-bucket-policy --bucket my-app-prod-assets

# Проверка public access block
aws s3api get-public-access-block --bucket my-app-prod-assets

# Проверка IAM permissions
aws iam get-user-policy --user-name my-user --policy-name my-policy

# Проверка KMS key policy (для SSE-KMS)
aws kms get-key-policy --key-id alias/my-key --policy-name default
```

### 7.2 404 NoSuchKey / NoSuchBucket

```bash
# Проверка существования bucket
aws s3api head-bucket --bucket my-app-prod-assets

# Проверка существования объекта
aws s3api head-object --bucket my-app-prod-assets --key path/to/object

# Проверка региона bucket
aws s3api get-bucket-location --bucket my-app-prod-assets
```

### 7.3 Slow performance

```bash
# Проверка network connectivity
aws s3api list-buckets --endpoint-url https://s3.eu-central-1.amazonaws.com

# Тест скорости загрузки/скачивания
time aws s3 cp test-file.tar.gz s3://my-app-prod-assets/test/
time aws s3 cp s3://my-app-prod-assets/test/test-file.tar.gz ./

# Проверка multipart config
aws configure get default.s3.multipart_threshold
aws configure get default.s3.max_concurrent_requests
```

### 7.4 Unexpected costs

```bash
# Анализ размера bucket
aws s3 ls s3://my-app-prod-assets/ --recursive --summarize --human-readable

# Проверка Storage Class распределения
aws s3api list-objects-v2 \
  --bucket my-app-prod-assets \
  --query 'Contents[*].[StorageClass, Size]' \
  --output text | awk '{sum[$1]+=$2} END {for (c in sum) print c, sum[c]}'

# Поиск больших объектов (> 1 ГБ)
aws s3api list-objects-v2 \
  --bucket my-app-prod-assets \
  --query 'Contents[?Size>`1073741824`].[Key, Size]' \
  --output table
```

---

## 8. S3-compatible хранилища

### 8.1 Ceph RGW

```bash
# Настройка endpoint для Ceph RGW
aws s3 ls \
  --endpoint-url http://ceph-rgw.local:7480 \
  --no-verify-ssl

# Создание bucket
aws s3 mb s3://my-bucket \
  --endpoint-url http://ceph-rgw.local:7480 \
  --no-verify-ssl
```

### 8.2 Garage

```bash
# Настройка endpoint для Garage
aws s3 ls \
  --endpoint-url http://garage.local:3900 \
  --no-verify-ssl
```

### 8.3 Yandex Object Storage

```bash
# Yandex Cloud S3-compatible endpoint
aws s3 ls \
  --endpoint-url https://storage.yandexcloud.net \
  --profile yandex

# Создание bucket
aws s3 mb s3://my-yandex-bucket \
  --endpoint-url https://storage.yandexcloud.net \
  --profile yandex
```

---

## 9. Best Practices (Production Checklist)

### Security
- [ ] Используются **IAM roles** вместо статических ключей (OIDC для CI/CD).
- [ ] Включён **Block Public Access** на уровне account и bucket.
- [ ] Используется **SSE-KMS** для encryption at rest.
- [ ] Настроен **Bucket Policy** с explicit Deny для нешифрованных загрузок.
- [ ] Включён **Access Logging** и **CloudTrail data events**.
- [ ] Используются **Presigned URLs** с коротким TTL вместо долгоживущих ключей.

### Reliability
- [ ] Включён **S3 Versioning** для критичных bucket'ов.
- [ ] Настроены **Lifecycle policies** для управления Storage Class.
- [ ] Для объектов > 5 ГБ используется **multipart upload**.
- [ ] Незавершённые multipart uploads очищаются через lifecycle policy.
- [ ] Для critical data включён **Object Lock**.
- [ ] Настроено **Cross-Region Replication** для DR.

### Performance
- [ ] Увеличен **multipart_threshold** и **max_concurrent_requests** для больших файлов.
- [ ] Используется **Transfer Acceleration** для cross-region клиентов.
- [ ] Для аналитических запросов используется **S3 Select**.
- [ ] **Prefix naming** оптимизирован для параллелизма.

### Cost Optimization
- [ ] Lifecycle policies для миграции в IA/Glacier.
- [ ] **Intelligent-Tiering** для непредсказуемых паттернов.
- [ ] **Storage Lens** включён для visibility.
- [ ] Мониторинг неиспользуемых bucket'ов через AWS Config.

---

## 10. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: безопасность, шифрование и compliance](./security.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [Ansible и S3: интеграция, автоматизация и эксплуатация](./ansible-integration.md)
- [Обзор систем хранения данных (СХД)](../data_storage_overview.md)