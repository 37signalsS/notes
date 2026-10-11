# S3: распространённые операции CLI и эксплуатация

**Актуально для:** AWS CLI 2.x, S3 API, Ceph RGW (Squid 19.x / Tentacle 20.x / Umbrella 21.x)

## 1. Определения

**aws-cli** — официальный CLI для AWS services, включая S3. Поддерживает все S3 API операции через команды `aws s3` (high-level) и `aws s3api` (low-level).

**Зачем aws-cli:** Это стандарт де-факто для работы с AWS из командной строки. В production используется для скриптов бэкапов, CI/CD пайплайнов, автоматизации. aws-cli abstrahiрует низкоуровневый REST API, предоставляя удобные команды (`cp`, `sync`, `mb`, `rb`).

**s3cmd** —第三方 CLI для S3, легковесный, удобен для простых операций.

**mc (S3 Client)** — клиент для работы с любым S3-compatible endpoint'ом. Поддерживает алиасы, parallel transfers, mirroring.

**Зачем mc:** mc особенно полезен при работе с self-hosted S3-compatible хранилищами (Ceph RGW), где aws-cli может требовать дополнительных настроек endpoint и SSL. mc позволяет настроить алиасы для разных окружений (prod, staging, dr) и быстро переключаться между ними.

**aws s3control** — CLI namespace для операций, которые затрагивают account-level или cross-service ресурсы. В Ceph RGW многие операции s3control не поддерживаются — используйте REST API или radosgw-admin.

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
# → aws-cli/2.25.4 Python/3.12.0 Linux/5.15.0-89-generic botocore/2.25.4

# Конфигурация credentials
aws configure
# AWS Access Key ID [None]: AKIA...
# AWS Secret Access Key [None]: ...
# Default region name [None]: us-east-1
# Default output format [None]: json

# Проверка конфигурации
aws sts get-caller-identity --endpoint-url http://rgw:7480
# → Account, UserId, Arn
```

**Зачем проверять `get-caller-identity`:** Эта команда проверяет, что credentials валидны и вы знаете, от какого principal (user/role) выполняются запросы. Критично для отладки permission issues.

**Варианты credentials (по приоритету):**
1. **Environment variables** (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`) — удобно для CI/CD.
2. **AWS CLI profiles** (`~/.aws/config` + `~/.aws/credentials`) — для работы с несколькими endpoint'ами.
3. **Hardcoded в коде** — **никогда** не делайте так.

**S3-specific конфигурация aws-cli для Ceph RGW:**

```bash
# Настройка endpoint для Ceph RGW
aws configure set default.s3.endpoint_url http://rgw:7480 --profile rgw
aws configure set default.s3.addressing_style path --profile rgw
# addressing_style=path обязательно для Ceph RGW

# Настройка параметров multipart
aws configure set default.s3.multipart_threshold 64MB --profile rgw
aws configure set default.s3.multipart_chunksize 16MB --profile rgw

# Увеличение параллелизма
aws configure set default.s3.max_concurrent_requests 20 --profile rgw
aws configure set default.s3.max_queue_size 10000 --profile rgw
```

**Retry и resilience:**

```bash
# Global retry config
aws configure set default.max_attempts 5 --profile rgw
aws configure set default.retry_mode standard --profile rgw
# retry_mode: standard (рекомендуется) | adaptive

# Или через переменные окружения
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1
export AWS_MAX_ATTEMPTS=5
export AWS_RETRY_MODE=standard
```

### 2.2 Bucket операции

```bash
# Создание bucket (имя должно быть globally unique в рамках кластера)
aws s3 mb s3://my-app-prod-assets \
  --region us-east-1 \
  --endpoint-url http://rgw:7480

# → make_bucket: my-app-prod-assets

# Список bucket'ов
aws s3 ls --endpoint-url http://rgw:7480

# Проверка существования bucket
aws s3api head-bucket --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Проверка региона bucket
aws s3api get-bucket-location --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Удаление bucket (должен быть пустым)
aws s3 rb s3://my-app-prod-assets --endpoint-url http://rgw:7480

# Принудительное удаление bucket со всем содержимым
aws s3 rb s3://my-app-prod-assets --force --endpoint-url http://rgw:7480
```

**Зачем `head-bucket`:** HEAD запрос проверяет существование bucket и ваши permissions на него без возврата содержимого. Используется в скриптах для проверки доступности bucket перед операциями.

**Важно:** `--force` удаляет все объекты в bucket без дополнительных подтверждений. Используйте с осторожностью в production.

### 2.3 Object операции

```bash
# Загрузка одного файла
aws s3 cp ./build/app.tar.gz s3://my-app-prod-assets/releases/v1.2.3/ \
  --storage-class WARM \
  --metadata "build-id=abc123,commit=def456" \
  --server-side-encryption AES256 \
  --endpoint-url http://rgw:7480

# Скачивание файла
aws s3 cp s3://my-app-prod-assets/releases/v1.2.3/app.tar.gz ./downloads/ \
  --endpoint-url http://rgw:7480

# Синхронизация директории (аналог rsync)
aws s3 sync ./dist/ s3://my-app-prod-assets/static/ \
  --delete \
  --exclude "*.tmp" \
  --exclude ".git/*" \
  --endpoint-url http://rgw:7480

# Обратная синхронизация (RGW → локально)
aws s3 sync s3://my-app-prod-assets/backups/ ./restore/ \
  --exact-timestamps \
  --endpoint-url http://rgw:7480

# Удаление объекта
aws s3 rm s3://my-app-prod-assets/old-backup.tar.gz --endpoint-url http://rgw:7480

# Удаление всех объектов с префиксом
aws s3 rm s3://my-app-prod-assets/logs/ --recursive --endpoint-url http://rgw:7480

# Список объектов
aws s3 ls s3://my-app-prod-assets/releases/ --endpoint-url http://rgw:7480
# → 2024-01-15 10:30:00    15MB v1.2.3/app.tar.gz

# Рекурсивный список
aws s3 ls s3://my-app-prod-assets/ --recursive --human-readable --summarize --endpoint-url http://rgw:7480

# Получение метаданных без скачивания
aws s3api head-object \
  --bucket my-app-prod-assets \
  --key releases/v1.2.3/app.tar.gz \
  --endpoint-url http://rgw:7480

# Копирование объекта внутри RGW (server-side)
aws s3 cp s3://my-app-prod-assets/releases/v1.2.3/app.tar.gz \
  s3://my-app-prod-assets/archives/ \
  --storage-class COLD \
  --endpoint-url http://rgw:7480
```

### 2.4 Presigned URLs

```bash
# Генерация presigned URL через aws-cli
aws s3 presign s3://my-app-prod-assets/releases/app.tar.gz \
  --expires-in 3600 \
  --region us-east-1 \
  --endpoint-url http://rgw:7480

# PUT presigned URL (для загрузки от имени сервиса)
aws s3 presign s3://my-app-prod-assets/uploads/${filename} \
  --expires-in 3600 \
  --region us-east-1 \
  --request-method PUT \
  --endpoint-url http://rgw:7480
```

---

## 3. Bucket политики и конфигурация

### 3.1 Versioning

```bash
# Включение versioning
aws s3api put-bucket-versioning \
  --bucket my-app-prod-assets \
  --versioning-configuration Status=Enabled \
  --endpoint-url http://rgw:7480

# Проверка статуса
aws s3api get-bucket-versioning --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Список всех версий объекта
aws s3api list-object-versions \
  --bucket my-app-prod-assets \
  --prefix releases/app.tar.gz \
  --endpoint-url http://rgw:7480

# Восстановление предыдущей версии
aws s3api copy-object \
  --bucket my-app-prod-assets \
  --key releases/app.tar.gz \
  --copy-source "my-app-prod-assets/releases/app.tar.gz?versionId=VERSION_ID" \
  --metadata-directive COPY \
  --endpoint-url http://rgw:7480
```

### 3.2 Lifecycle policies

```bash
# Применение lifecycle configuration
aws s3api put-bucket-lifecycle-configuration \
  --bucket my-app-prod-assets \
  --lifecycle-configuration file://lifecycle.json \
  --endpoint-url http://rgw:7480

# Просмотр текущих правил
aws s3api get-bucket-lifecycle-configuration --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Удаление всех lifecycle правил
aws s3api delete-bucket-lifecycle --bucket my-app-prod-assets --endpoint-url http://rgw:7480
```

### 3.3 Encryption

```bash
# Включение SSE-S3 по умолчанию
aws s3api put-bucket-encryption \
  --bucket my-app-prod-assets \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }' \
  --endpoint-url http://rgw:7480

# Проверка encryption configuration
aws s3api get-bucket-encryption --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Удаление encryption configuration
aws s3api delete-bucket-encryption --bucket my-app-prod-assets --endpoint-url http://rgw:7480
```

### 3.4 Bucket Policy

```bash
# Применение bucket policy
aws s3api put-bucket-policy \
  --bucket my-app-prod-assets \
  --policy file://bucket-policy.json \
  --endpoint-url http://rgw:7480

# Просмотр policy
aws s3api get-bucket-policy --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Удаление policy
aws s3api delete-bucket-policy --bucket my-app-prod-assets --endpoint-url http://rgw:7480
```

### 3.5 Public Access Block

```bash
# Включение Block Public Access через bucket policy
aws s3api put-bucket-policy \
  --bucket my-app-prod-assets \
  --policy '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": ["arn:aws:s3:::my-app-prod-assets", "arn:aws:s3:::my-app-prod-assets/*"],
      "Condition": {"Bool": {"aws:SecureTransport": false}}
    }]
  }' \
  --endpoint-url http://rgw:7480

# Проверка настроек bucket
aws s3api get-public-access-block --bucket my-app-prod-assets --endpoint-url http://rgw:7480
```

### 3.6 Object Lock

```bash
# Включение Object Lock при создании bucket
aws s3api create-bucket \
  --bucket my-app-prod-assets \
  --object-lock-enabled-for-bucket \
  --endpoint-url http://rgw:7480 \
  --region us-east-1

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
  }' \
  --endpoint-url http://rgw:7480

# Проверка retention для объекта
aws s3api get-object-retention \
  --bucket my-app-prod-assets \
  --key releases/v1.2.3/app.tar.gz \
  --endpoint-url http://rgw:7480
```

### 3.7 Replication (Multisite)

В Ceph RGW репликация настраивается через `radosgw-admin`, а не через S3 API. Подробные команды и runbook приведены в:
- [S3: disaster recovery runbook](./dr-runbook.md)

### 3.8 Event Notifications

```bash
# Настройка уведомлений на HTTP webhook
aws s3api put-bucket-notification-configuration \
  --bucket my-app-prod-assets \
  --notification-configuration file://notification.json \
  --endpoint-url http://rgw:7480

# Проверка конфигурации
aws s3api get-bucket-notification-configuration --bucket my-app-prod-assets --endpoint-url http://rgw:7480
```

**Пример notification.json для RGW (MQTT/AMQP/HTTP):**
```json
{
  "TopicConfigurations": [
    {
      "Topic": "http://webhook.example.com/notifications",
      "Events": ["s3:ObjectCreated:*", "s3:ObjectRemoved:*"]
    }
  ]
}
```

### 3.9 CORS

```bash
# Настройка CORS
aws s3api put-bucket-cors \
  --bucket my-app-prod-assets \
  --cors-configuration '{
    "CORSRules": [{
      "AllowedOrigins": ["https://app.example.com"],
      "AllowedMethods": ["GET", "HEAD"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag"],
      "MaxAgeSeconds": 3000
    }]
  }' \
  --endpoint-url http://rgw:7480

# Проверка конфигурации
aws s3api get-bucket-cors --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Удаление CORS
aws s3api delete-bucket-cors --bucket my-app-prod-assets --endpoint-url http://rgw:7480
```

### 3.10 Bucket tagging

```bash
# Назначение тегов bucket
aws s3api put-bucket-tagging \
  --bucket my-app-prod-assets \
  --tagging '{
    "TagSet": [
      {"Key": "Environment", "Value": "prod"},
      {"Key": "Team", "Value": "platform"},
      {"Key": "CostCenter", "Value": "12345"}
    ]
  }' \
  --endpoint-url http://rgw:7480

# Просмотр тегов
aws s3api get-bucket-tagging --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Удаление всех тегов
aws s3api delete-bucket-tagging --bucket my-app-prod-assets --endpoint-url http://rgw:7480
```

### 3.11 Object tagging

```bash
# Назначение тегов объекту
aws s3api put-object-tagging \
  --bucket my-app-prod-assets \
  --key releases/app.tar.gz \
  --tagging '{
    "TagSet": [
      {"Key": "Version", "Value": "1.2.3"},
      {"Key": "BuildId", "Value": "abc123"}
    ]
  }' \
  --endpoint-url http://rgw:7480

# Просмотр тегов объекта
aws s3api get-object-tagging --bucket my-app-prod-assets --key releases/app.tar.gz --endpoint-url http://rgw:7480

# Удаление тегов объекта
aws s3api delete-object-tagging --bucket my-app-prod-assets --key releases/app.tar.gz --endpoint-url http://rgw:7480
```

### 3.12 Ownership controls

```bash
# Настройка object ownership (Bucket owner enforced)
aws s3api put-bucket-ownership-controls \
  --bucket my-app-prod-assets \
  --ownership-controls '{
    "Rules": [{
      "ObjectOwnership": "BucketOwnerEnforced"
    }]
  }' \
  --endpoint-url http://rgw:7480

# Проверка настроек
aws s3api get-bucket-ownership-controls --bucket my-app-prod-assets --endpoint-url http://rgw:7480
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
  }' \
  --endpoint-url http://rgw:7480

# Проверка статуса
aws s3api get-bucket-logging --bucket my-app-prod-assets --endpoint-url http://rgw:7480
```

### 4.2 Metrics и Inventory управление

```bash
# Список настроенных metrics configurations
aws s3api list-bucket-metrics-configurations --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Получение metrics configuration
aws s3api get-bucket-metrics-configuration \
  --bucket my-app-prod-assets \
  --id EntireBucket \
  --endpoint-url http://rgw:7480

# Удаление metrics configuration
aws s3api delete-bucket-metrics-configuration \
  --bucket my-app-prod-assets \
  --id EntireBucket \
  --endpoint-url http://rgw:7480

# Список inventory configurations
aws s3api list-bucket-inventory-configurations --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Получение inventory configuration
aws s3api get-bucket-inventory-configuration \
  --bucket my-app-prod-assets \
  --id my-inventory \
  --endpoint-url http://rgw:7480

# Удаление inventory configuration
aws s3api delete-bucket-inventory-configuration \
  --bucket my-app-prod-assets \
  --id my-inventory \
  --endpoint-url http://rgw:7480
```

---

## 5. Batch Operations

### 5.1 Batch delete objects

```bash
# Массовое удаление объектов через JSON manifest
cat > delete-manifest.json << 'EOF'
{
  "Objects": [
    {"Key": "logs/old-1.log"},
    {"Key": "logs/old-2.log"},
    {"Key": "logs/old-3.log"}
  ],
  "Quiet": false
}
EOF

aws s3api delete-objects \
  --bucket my-app-prod-assets \
  --delete file://delete-manifest.json \
  --endpoint-url http://rgw:7480
```

### 5.2 S3 Batch Operations (через REST API)

В Ceph RGW S3 Batch Operations не поддерживаются нативно. Используйте Python/Go скрипты для массовых операций:

```python
import boto3

s3 = boto3.client('s3',
    endpoint_url='http://rgw:7480',
    region_name='us-east-1'
)

# Список объектов для удаления
response = s3.list_objects_v2(Bucket='my-app-prod-assets', Prefix='logs/')

for obj in response.get('Contents', []):
    s3.delete_object(Bucket='my-app-prod-assets', Key=obj['Key'])
```

---

## 6. Multipart upload

### 6.1 Автоматический multipart (aws-cli)

```bash
# Для файлов > 8 ГБ aws-cli автоматически использует multipart
aws s3 cp large-backup.tar.gz s3://my-app-prod-assets/backups/ \
  --storage-class COLD \
  --endpoint-url http://rgw:7480

# Настройка multipart parameters
aws configure set default.s3.multipart_threshold 64MB --profile rgw
aws configure set default.s3.multipart_chunksize 16MB --profile rgw
```

### 6.2 Ручной multipart (aws s3api)

```bash
# 1. Инициализация
UPLOAD_ID=$(aws s3api create-multipart-upload \
  --bucket my-app-prod-assets \
  --key backups/large-backup.tar.gz \
  --storage-class COLD \
  --query 'UploadId' --output text \
  --endpoint-url http://rgw:7480)

# 2. Загрузка частей (часть 1)
aws s3api upload-part \
  --bucket my-app-prod-assets \
  --key backups/large-backup.tar.gz \
  --part-number 1 \
  --upload-id $UPLOAD_ID \
  --body part-1.tar.gz \
  --query 'ETag' --output text \
  --endpoint-url http://rgw:7480

# 3. Загрузка частей (часть 2)
aws s3api upload-part \
  --bucket my-app-prod-assets \
  --key backups/large-backup.tar.gz \
  --part-number 2 \
  --upload-id $UPLOAD_ID \
  --body part-2.tar.gz \
  --query 'ETag' --output text \
  --endpoint-url http://rgw:7480

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
  }' \
  --endpoint-url http://rgw:7480

# 5. Отмена (при ошибке)
aws s3api abort-multipart-upload \
  --bucket my-app-prod-assets \
  --key backups/large-backup.tar.gz \
  --upload-id $UPLOAD_ID \
  --endpoint-url http://rgw:7480
```

### 6.3 Просмотр незавершённых загрузок

```bash
# Список незавершённых multipart uploads
aws s3api list-multipart-uploads --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Детали по конкретному upload
aws s3api list-parts \
  --bucket my-app-prod-assets \
  --key backups/large-backup.tar.gz \
  --upload-id $UPLOAD_ID \
  --endpoint-url http://rgw:7480

# Массовая отмена старых незавершённых загрузок
aws s3api list-multipart-uploads --bucket my-app-prod-assets \
  --query 'Uploads[*].[Key,UploadId]' --output text \
  --endpoint-url http://rgw:7480 | while read key upload_id; do
    echo "Aborting: $key ($upload_id)"
    aws s3api abort-multipart-upload \
      --bucket my-app-prod-assets \
      --key "$key" \
      --upload-id "$upload_id" \
      --endpoint-url http://rgw:7480
  done
```

---

## 7. Performance tuning

### 7.1 Parallel transfers

```bash
# Увеличение параллелизма для aws-cli
aws configure set default.s3.max_concurrent_requests 20 --profile rgw
aws configure set default.s3.max_queue_size 10000 --profile rgw

# Или через переменные окружения
export AWS_MAX_CONCURRENT_REQUESTS=20
export AWS_MAX_QUEUE_SIZE=10000
```

### 7.2 Retry и timeout

```bash
# CLI-level retry и timeout
aws configure set default.max_attempts 5 --profile rgw
aws configure set default.retry_mode standard --profile rgw
aws configure set default.cli_read_timeout 60 --profile rgw
aws configure set default.cli_connect_timeout 10 --profile rgw

# Или через переменные окружения
export AWS_MAX_ATTEMPTS=5
export AWS_RETRY_MODE=standard
export AWS_CLI_READ_TIMEOUT=60
export AWS_CLI_CONNECT_TIMEOUT=10
```

### 7.3 Pagination и большие листинги

```bash
# list-objects-v2 с пагинацией
aws s3api list-objects-v2 \
  --bucket my-app-prod-assets \
  --max-items 1000 \
  --page-size 100 \
  --starting-token TOKEN \
  --query 'Contents[].Key' \
  --output text \
  --endpoint-url http://rgw:7480

# list-objects-v2 с fetch-owner и start-after
aws s3api list-objects-v2 \
  --bucket my-app-prod-assets \
  --prefix uploads/ \
  --start-after uploads/processed/ \
  --fetch-owner \
  --query 'Contents[*].[Key, Size, Owner.ID]' \
  --output table \
  --endpoint-url http://rgw:7480
```

---

## 8. Дополнительные операции

### 8.1 Object attributes

```bash
# Получение атрибутов объекта без скачивания
aws s3api get-object-attributes \
  --bucket my-app-prod-assets \
  --key releases/app.tar.gz \
  --object-attributes StorageClass ObjectSize ETag Checksum \
  --endpoint-url http://rgw:7480
```

### 8.2 Object legal hold

```bash
# Включение legal hold
aws s3api put-object-legal-hold \
  --bucket my-app-prod-assets \
  --key releases/app.tar.gz \
  --legal-hold Status=ON \
  --endpoint-url http://rgw:7480

# Проверка legal hold
aws s3api get-object-legal-hold \
  --bucket my-app-prod-assets \
  --key releases/app.tar.gz \
  --endpoint-url http://rgw:7480
```

### 8.3 Object retention

```bash
# Установка retention
aws s3api put-object-retention \
  --bucket my-app-prod-assets \
  --key releases/app.tar.gz \
  --retention '{
    "Mode": "GOVERNANCE",
    "RetainUntilDate": "2025-12-31T00:00:00Z"
  }' \
  --endpoint-url http://rgw:7480

# Проверка retention
aws s3api get-object-retention \
  --bucket my-app-prod-assets \
  --key releases/app.tar.gz \
  --endpoint-url http://rgw:7480
```

### 8.4 Cross-tenant access (Ceph RGW tenants)

```bash
# Создание изолированного тенанта
radosgw-admin tenant create --tenant="team-a"

# Создание пользователя в тенанте
radosgw-admin user create \
  --uid="team-a-user" \
  --display-name="Team A User" \
  --tenant="team-a"

# Проверка прав пользователя
radosgw-admin user info --uid="team-a-user"
```

### 8.5 Debug и диагностика

```bash
# Включение debug режима
aws s3 cp file.tar.gz s3://my-app-prod-assets/ --debug 2>&1 | tee upload.log

# Игнорирование SSL (для self-signed certs в dev)
aws s3 ls --endpoint-url http://rgw:7480 --no-verify-ssl

# Использование custom CA bundle
aws s3 ls --ca-bundle /etc/ssl/certs/ca-bundle.crt --endpoint-url http://rgw:7480
```

---

## 9. Troubleshooting

### 9.1 403 Forbidden

```bash
# Проверка bucket policy
aws s3api get-bucket-policy --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Проверка public access block
aws s3api get-public-access-block --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Проверка ACL (если включены)
aws s3api get-object-acl \
  --bucket my-app-prod-assets \
  --key releases/app.tar.gz \
  --endpoint-url http://rgw:7480

# Проверка addressing style
aws configure get default.s3.addressing_style --profile rgw
```

### 9.2 404 NoSuchKey / NoSuchBucket

```bash
# Проверка существования bucket
aws s3api head-bucket --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Проверка существования объекта
aws s3api head-object --bucket my-app-prod-assets --key path/to/object --endpoint-url http://rgw:7480

# Проверка региона bucket
aws s3api get-bucket-location --bucket my-app-prod-assets --endpoint-url http://rgw:7480
```

### 9.3 Slow performance

```bash
# Проверка network connectivity
mtr --tcp --port 7480 rgw.example.com

# Тест скорости загрузки/скачивания
time aws s3 cp test-file.tar.gz s3://my-app-prod-assets/test/ --endpoint-url http://rgw:7480
time aws s3 cp s3://my-app-prod-assets/test/test-file.tar.gz ./ --endpoint-url http://rgw:7480

# Проверка multipart config
aws configure get default.s3.multipart_threshold --profile rgw
aws configure get default.s3.max_concurrent_requests --profile rgw
```

### 9.4 SSL/TLS и endpoint issues

```bash
# Проверка endpoint и сертификата
openssl s_client -connect rgw:7480 -servername rgw

# Для self-hosted с self-signed cert
aws s3 ls --endpoint-url http://rgw:7480 --no-verify-ssl

# Проверка addressing style
aws s3 ls --endpoint-url http://rgw:7480 --no-verify-ssl
# Если 403 — добавьте --no-sign-request или настройте addressing_style=path
```

### 9.5 Multipart stalls

```bash
# Проверка незавершённых multipart uploads
aws s3api list-multipart-uploads --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Проверка lifecycle для автоматической очистки
aws s3api get-bucket-lifecycle-configuration --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# Принудительная отмена зависших uploads
aws s3api list-multipart-uploads --bucket my-app-prod-assets \
  --query 'Uploads[*].[Key,UploadId]' --output text \
  --endpoint-url http://rgw:7480 | while read key upload_id; do
    echo "Aborting: $key ($upload_id)"
    aws s3api abort-multipart-upload \
      --bucket my-app-prod-assets \
      --key "$key" \
      --upload-id "$upload_id" \
      --endpoint-url http://rgw:7480
  done
```

---

## 10. S3-compatible хранилища

### 10.1 Ceph RGW

```bash
# Настройка endpoint для Ceph RGW
aws s3 ls \
  --endpoint-url http://rgw:7480 \
  --no-verify-ssl \
  --no-sign-request

# Создание bucket
aws s3 mb s3://my-bucket \
  --endpoint-url http://rgw:7480 \
  --no-verify-ssl

# Глобальная настройка addressing style (обязательна для Ceph RGW)
aws configure set default.s3.addressing_style path --profile rgw
```

### 10.2 s3cmd

```bash
# Конфигурация s3cmd для Ceph RGW
s3cmd --configure
# Host: rgw.example.com
# Port: 7480
# Path: /
# Access Key: AKIA...
# Secret Key: ...

# Загрузка файла
s3cmd put file.tar.gz s3://my-bucket/ --endpoint-url http://rgw:7480

# Синхронизация директории
s3cmd sync ./dist/ s3://my-bucket/static/ --endpoint-url http://rgw:7480
```

---

## 11. Best Practices (Production Checklist)

### Security
- [ ] Используются **краткоживущие credentials** (STS, Vault, OIDC) вместо статических ключей.
- [ ] Включён **Block Public Access** на уровне account и bucket.
- [ ] Используется **SSE-S3** или **SSE-KMS** (rgw crypto / Vault) для encryption at rest.
- [ ] Настроен **Bucket Policy** с explicit Deny для нешифрованных загрузок.
- [ ] Включён **Access Logging** для audit.
- [ ] Используются **Presigned URLs** с коротким TTL вместо долгоживущих ключей.
- [ ] Настроен **Object Lock** или **Legal Hold** для критичных данных.
- [ ] Используется **Bucket Owner Enforced** для ownership controls.

### Reliability
- [ ] Включён **Versioning** для критичных bucket'ов.
- [ ] Настроены **Lifecycle policies** для управления Storage Class (hot/warm/cold pools).
- [ ] Для объектов > 5 ГБ используется **multipart upload**.
- [ ] Незавершённые multipart uploads очищаются через lifecycle policy.
- [ ] Настроено **multisite replication** для DR.
- [ ] Используются **Retry Mode: standard** с `max_attempts >= 3`.

### Performance
- [ ] Увеличен **multipart_threshold** и **max_concurrent_requests** для больших файлов.
- [ ] Используется **CDN** для статических assets.
- [ ] **Prefix naming** оптимизирован для параллелизма.
- [ ] Настроен **addressing_style=path** для RGW endpoint'ов.

### Cost Optimization
- [ ] Lifecycle policies для миграции между hot/warm/cold pools.
- [ ] **Versioning** включён для критичных bucket'ов.
- [ ] **Inventory** настроен для анализа объектов.
- [ ] Настроены lifecycle policies для автоматического управления.

### Cleanup и откат
- [ ] Знаете, как отключить versioning: `aws s3api put-bucket-versioning --bucket <name> --versioning-configuration Status=Suspended --endpoint-url http://rgw:7480`
- [ ] Знаете, как удалить lifecycle: `aws s3api delete-bucket-lifecycle --bucket <name> --endpoint-url http://rgw:7480`
- [ ] Знаете, как удалить bucket policy: `aws s3api delete-bucket-policy --bucket <name> --endpoint-url http://rgw:7480`
- [ ] Знаете, как удалить encryption: `aws s3api delete-bucket-encryption --bucket <name> --endpoint-url http://rgw:7480`
- [ ] Знаете, как отменить multipart upload: `aws s3api abort-multipart-upload --bucket <name> --key <key> --upload-id <id> --endpoint-url http://rgw:7480`

---

## 12. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: безопасность, шифрование и compliance](./security.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [Ansible и S3: интеграция, автоматизация и эксплуатация](./ansible-integration.md)
- [Ceph RGW: S3-совместимое хранилище на базе Ceph](../../../Kubernetes/Storage/Ceph/ceph_rgw_s3.md)
