**Data at Rest** — данные, хранящиеся на диске (в S3 bucket). Требуют защиты от несанкционированного доступа.

**Почему это важно:** Data at rest включает все объекты в S3 — бэкапы баз данных, артефакты сборок, логи, конфигурации с секретами. При компрометации AWS account или bucket credentials злоумышленник получает прямой доступ к этим данным. Шифрование at rest защищает даже при физическом доступе к дискам или логическом доступе к bucket.

**Data in Transit** — данные при передаче между клиентом и S3. Требуют шифрования через TLS.

**Почему это важно:** Без TLS credentials, объекты и metadata передаются в открытом виде. В corporate сети или интернете это позволяет перехватить секреты (access key, secret key) или содержимое объектов. TLS 1.2+ обязателен для всех S3 операций в production.

**SSE-S3** — Server-Side Encryption с ключами, управляемыми Amazon S3. AES-256.

**SSE-KMS** — Server-Side Encryption с ключами из AWS KMS. Поддерживает rotation, аудит, granular permissions.

**SSE-C** — Server-Side Encryption с ключами от клиента. Amazon не хранит ключ.

**Client-Side Encryption** — шифрование на стороне клиента до загрузки в S3.

**Object Lock** — WORM-механизм, защищающий объекты от удаления/изменения в течение заданного срока.

**Immutability** — свойство данных, при котором они защищены от любого изменения или удаления (даже администратором).

---

## 2. Базовые концепции безопасности

### 2.1 Модель безопасности S3

S3 использует **multi-layered security model**:

1. **Network layer:** TLS 1.2+ для всех операций, VPC Endpoints (Gateway/Interface) для изоляции трафика.
2. **Identity layer:** IAM principals (users, roles, groups), Bucket Policies, ACL.
3. **Encryption layer:** SSE-S3, SSE-KMS, SSE-C, Client-Side Encryption.
4. **Data layer:** Object Lock, Versioning, Replication, Lifecycle.
5. **Audit layer:** CloudTrail, Access Logging, S3 Inventory, Config Rules.

**Почему multi-layered:** Защита в глубину (defense in depth). Даже если один слой скомпрометирован (например, credentials украдены), другие слои (encryption, network isolation, audit) ограничивают ущерб. В production все слои должны быть включены, а не только один.

### 2.2 Shared Responsibility Model

| Ответственность | AWS (S3 service) | Customer (вы) |
|----------------|------------------|---------------|
| **Инфраструктура** | Data centers, сеть, hardware | — |
| **Шифрование at rest** | SSE-S3 (опционально) | SSE-KMS ключи, Client-side encryption |
| **Шифрование in transit** | TLS endpoint | TLS configuration, certificate validation |
| **Доступ** | IAM service | IAM policies, Bucket Policies, ACL |
| **Данные** | — | Classification, retention, deletion |
| **Аудит** | CloudTrail logs | Log analysis, alerting, incident response |

**Почему это важно:** Shared Responsibility Model определяет границы ответственности. AWS отвечает за security *of* the cloud (инфраструктура), вы отвечаете за security *in* the cloud (данные, доступ, конфигурация). Ошибки в вашей части (неправильный bucket policy, отключенное шифрование) — это ваша ответственность.

---

## 3. Шифрование

### 3.1 Server-Side Encryption (SSE)

**SSE-S3:**
- Ключи управляются Amazon S3 service.
- AES-256 шифрование.
- Бесплатно (включено в стоимость S3).
- Нет rotation, нет granular audit.
- Подходит для non-sensitive данных.

**SSE-KMS (рекомендуется для production):**
- Ключи управляются через AWS KMS.
- Поддерживает automatic key rotation (ежегодно).
- Аудит через CloudTrail (кто, когда, какой ключ использовал).
- Granular permissions (`kms:GenerateDataKey`, `kms:Decrypt`, `kms:Encrypt`).
- Возможность импорта собственных ключей (BYOK - Bring Your Own Key).
- Дополнительная стоимость: $0.03 за 10 000 запросов к KMS + $1 за активный ключ/месяц.

**SSE-C:**
- Клиент предоставляет ключ для каждого запроса.
- Amazon не хранит ключ.
- Используется для compliance требований, когда провайдер не должен иметь доступ к ключам.
- **Важно:** если потеряете ключ — потеряете данные. Нет rotation.

**Зачем выбирать SSE-KMS вместо SSE-S3:**
- **Контроль над ключами:** Вы управляете ключами, можете их отозвать, посмотреть историю использования.
- **Аудит:** CloudTrail логирует каждое использование ключа (кто, когда, для какого объекта).
- **Rotation:** Автоматическая ротация ключей раз в год без повторного шифрования всех объектов.
- **Compliance:** Многие стандарты (PCI DSS, HIPAA) требуют контроля над ключами шифрования.

### 3.2 Настройка SSE-KMS

```bash
# Создание KMS key
aws kms create-key \
  --description "KMS key for S3 state encryption" \
  --key-usage ENCRYPT_DECRYPT \
  --enable-key-rotation

# Создание alias
aws kms create-alias \
  --alias-name alias/terraform-state-key \
  --target-key-id $(aws kms create-key --query 'KeyMetadata.KeyId' --output text)

# Включение SSE-KMS на bucket
aws s3api put-bucket-encryption \
  --bucket my-app-prod-assets \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "aws:kms",
        "KMSMasterKeyID": "arn:aws:kms:eu-central-1:123456789012:alias/terraform-state-key"
      },
      "BucketKeyEnabled": true
    }]
  }'
```

**Bucket Key Enabled:**
- Включает S3 Bucket Key — Amazon управляет ключом данных на уровне bucket,减少 KMS запросы.
- Снижает стоимость на 90–99% для high-volume workloads.
- Поддерживается для SSE-KMS.

**Почему Bucket Key важен для cost optimization:** Без Bucket Key каждый запрос к S3 (PUT, GET) требует отдельного вызова KMS для генерации/дешифрования ключа данных. Для bucket с 1 млн запросов/день это $300/месяц только на KMS. С Bucket Key Amazon кэширует ключ данных на уровне bucket, и KMS вызывается только раз в несколько часов.

### 3.3 Client-Side Encryption

```python
import boto3
from botocore.client import Config
import base64
from cryptography.fernet import Fernet

s3 = boto3.client('s3', config=Config(signature_version='s3v4'))

# Шифрование перед загрузкой
key = Fernet.generate_key()
cipher = Fernet(key)

with open('sensitive-data.tar.gz', 'rb') as f:
    encrypted_data = cipher.encrypt(f.read())

# Загрузка зашифрованных данных
s3.put_object(
    Bucket='my-app-prod-assets',
    Key='encrypted/sensitive-data.tar.gz.enc',
    Body=encrypted_data,
    ServerSideEncryption='aws:kms',
    SSEKMSKeyId='arn:aws:kms:eu-central-1:123456789012:alias/my-key'
)

# Сохранение ключа в KMS или Vault
# Никогда не храните ключ рядом с зашифрованными данными!
```

**Use cases:**
- Compliance требования (PCI DSS, HIPAA), когда провайдер не должен иметь доступ к ключам.
- Defense in depth: дополнительный слой защиты поверх SSE-KMS.

**Почему client-side encryption — это extreme measure:** Client-side encryption даёт максимальный контроль, но требует:
- Управления ключами на стороне клиента (где хранить? как ротировать?).
- Обработки шифрования/дешифрования на каждом клиенте.
- Отладки проблем с шифрованием в production.

Для большинства production-систем SSE-KMS достаточно. Client-side encryption используется только в высокорегулируемых отраслях (финансы, медицина).

---

## 4. IAM Policies

### 4.1 Bucket Policy

Bucket Policy — JSON-документ на уровне bucket, определяющий кто и что может делать.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowListBucket",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::123456789012:role/terraform-ci"
      },
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::my-app-prod-assets",
      "Condition": {
        "StringLike": {"s3:prefix": "releases/*"}
      }
    },
    {
      "Sid": "AllowReadWriteReleases",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::123456789012:role/terraform-ci"
      },
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::my-app-prod-assets/releases/*"
    },
    {
      "Sid": "DenyUnencryptedUploads",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::my-app-prod-assets/*",
      "Condition": {
        "StringNotEquals": {"s3:x-amz-server-side-encryption": "aws:kms"}
      }
    },
    {
      "Sid": "DenyInsecureTransport",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::my-app-prod-assets",
        "arn:aws:s3:::my-app-prod-assets/*"
      ],
      "Condition": {
        "Bool": {"aws:SecureTransport": "false"}
      }
    },
    {
      "Sid": "DenyPublicAccess",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::my-app-prod-assets",
        "arn:aws:s3:::my-app-prod-assets/*"
      ],
      "Condition": {
        "Bool": {"aws:PrincipalIsAWSService": "false"},
        "StringNotEquals": {"aws:PrincipalAccount": "123456789012"}
      }
    }
  ]
}
```

### 4.2 IAM Policy (для principals)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3ReadWriteAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::my-app-prod-assets",
        "arn:aws:s3:::my-app-prod-assets/*"
      ]
    },
    {
      "Sid": "KMSAccess",
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt",
        "kms:GenerateDataKey",
        "kms:DescribeKey"
      ],
      "Resource": "arn:aws:kms:eu-central-1:123456789012:alias/terraform-state-key"
    }
  ]
}
```

### 4.3 VPC Endpoint (Private Link)

```bash
# Создание Gateway VPC Endpoint для S3
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-12345678 \
  --service-name com.amazonaws.eu-central-1.s3 \
  --route-table-id rtb-12345678 \
  --policy file://endpoint-policy.json

# Endpoint policy (ограничивает доступ только к определённым bucket)
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": "*",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": [
        "arn:aws:s3:::my-app-prod-assets/*",
        "arn:aws:s3:::my-app-prod-assets"
      ]
    }
  ]
}
```

**Преимущества:**
- Трафик не покидает AWS network (нет internet gateway, NAT gateway).
- Снижение latency.
- Повышение security (изоляция в VPC).

---

## 5. S3 Object Lock (WORM)

### 5.1 Режимы retention

| Режим | Governance | Compliance |
|-------|-----------|------------|
| **Кто может удалить** | Пользователи с `s3:BypassGovernanceRetention` | Никто, включая root account |
| **Можно сократить retention** | Да (с special permission) | Нет |
| **Использование** | Operational flexibility | Regulatory compliance (SEC 17a-4, FINRA) |

### 5.2 Настройка Object Lock

```bash
# Включение Object Lock при создании bucket (нельзя включить позже!)
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

# Загрузка объекта с retention period
aws s3api put-object \
  --bucket my-app-prod-assets \
  --key backups/etcd-snapshot.db \
  --body ./etcd-snapshot.db \
  --object-lock-mode COMPLIANCE \
  --object-lock-retain-until-date 2026-12-31T23:59:59.000Z \
  --server-side-encryption aws:kms
```

### 5.3 Legal Hold

```bash
# Установка Legal Hold (бессрочная защита от удаления)
aws s3api put-object-legal-hold \
  --bucket my-app-prod-assets \
  --key backups/etcd-snapshot.db \
  --legal-hold Status=ON

# Снятие Legal Hold
aws s3api put-object-legal-hold \
  --bucket my-app-prod-assets \
  --key backups/etcd-snapshot.db \
  --legal-hold Status=OFF
```

**Разница Legal Hold vs Retention:**
- **Legal Hold:** бессрочная, пока явно не снята. Используется для litigation, investigations.
- **Retention:** фиксированный срок. Автоматически истекает.

---

## 6. Audit и мониторинг

### 6.1 CloudTrail data events

```bash
# Включение data events для S3
aws cloudtrail put-event-selectors \
  --trail-name my-trail \
  --event-selectors '[
    {
      "ReadWriteType": "All",
      "IncludeManagementEvents": true,
      "DataResources": [
        {
          "Type": "AWS::S3::Object",
          "Values": ["arn:aws:s3:::my-app-prod-assets/*"]
        }
      ]
    }
  ]'
```

**Data events log:**
- `GetObject` — чтение объектов.
- `PutObject` — загрузка объектов.
- `DeleteObject` — удаление объектов.
- `RestoreObject` — восстановление из Glacier.

### 6.2 Access Logging

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
```

**Log format:**
```
79a54df98bf4d2d9d6728775159241e1fad325b1 [06/Oct/2024:10:30:00 +0000] 192.0.2.3 arn:aws:sts::123456789012:assumed-role/terraform-ci/my-role REST.GET.OBJECT releases/app.tar.gz "PUT /releases/app.tar.gz" 200 - 1 0 "-" "" - kGkWULf+Vs5aS3RaJkFXKs3/2sM= SigV4 ECDHE-RSA-AES128-SHA TLSv1.2 - - - - - -
```

### 6.3 S3 Inventory

```bash
# Настройка S3 Inventory для compliance аудита
aws s3api put-bucket-inventory-configuration \
  --bucket my-app-prod-assets \
  --id security-inventory \
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
    "OptionalFields": [
      "Size",
      "LastModifiedDate",
      "StorageClass",
      "EncryptionStatus",
      "ObjectLockLegalHoldStatus",
      "ObjectLockRetainUntilDate"
    ]
  }'
```

---

## 7. Compliance frameworks

### 7.1 PCI DSS

**Требования для S3:**
- Шифрование данных at rest (SSE-KMS) — Requirement 3.
- Шифрование данных in transit (TLS 1.2+) — Requirement 4.
- Access control (IAM, Bucket Policy) — Requirement 7.
- Audit logging (CloudTrail, S3 Access Logs) — Requirement 10.
- Regular scanning (S3 Inventory, AWS Config) — Requirement 11.

### 7.2 HIPAA

**Требования для S3:**
- Шифрование at rest (SSE-KMS) и in transit (TLS).
- Access logging и audit trails.
- Business Associate Agreement (BAA) с AWS.
- Object Lock для immutability audit logs.

### 7.3 SEC Rule 17a-4 / FINRA

**Требования:**
- Object Lock в режиме **Compliance** для broker-dealer records.
- Retention period ≥ 3 года (first 2 years in easily accessible format).
- Immutability: данные не могут быть изменены или удалены.
- Audit trail всех операций.

```bash
# Настройка для SEC 17a-4 compliance
aws s3api put-object-lock-configuration \
  --bucket my-app-prod-assets \
  --object-lock-configuration '{
    "ObjectLockEnabled": "Enabled",
    "Rule": {
      "DefaultRetention": {
        "Mode": "COMPLIANCE",
        "Days": 1095
      }
    }
  }'
```

---

## 8. Incident Response

### 8.1 План реагирования на security incident

**Сценарий 1: Публичный bucket**

```bash
# 1. Немедленное действие: включить Block Public Access
aws s3api put-public-access-block \
  --bucket compromised-bucket \
  --public-access-block-configuration '{
    "BlockPublicAcls": true,
    "IgnorePublicAcls": true,
    "BlockPublicPolicy": true,
    "RestrictPublicBuckets": true
  }'

# 2. Удалить публичный bucket policy
aws s3api delete-bucket-policy --bucket compromised-bucket

# 3. Проверить access logs на аномалии
aws s3 cp s3://audit-logs/s3-logs/compromised-bucket/ ./logs/ --recursive

# 4. Проверить CloudTrail events
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=ResourceName,AttributeValue=arn:aws:s3:::compromised-bucket \
  --start-time 2024-01-01 --end-time 2024-01-15
```

**Сценарий 2: Утечка данных (data exfiltration)**

```bash
# 1. Отозвать compromised credentials
aws iam delete-access-key --user-name compromised-user --access-key-id AKIA...

# 2. Проверить S3 access logs на аномальные GET запросы
grep "GET.*sensitive-data" s3-access-log* | awk '{print $1}' | sort | uniq -c | sort -rn

# 3. Проверить CloudTrail для идентификации source IP
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=GetObject \
  --start-time 2024-01-01 --end-time 2024-01-15 \
  --query 'Events[*].[CloudTrailEvent.EventSource, CloudTrailEvent.RequestParameters.bucketName, CloudTrailEvent.SourceIPAddress]' \
  --output text | grep compromised-bucket
```

### 8.2 AWS Config Rules

```bash
# Включение AWS Config для S3 compliance monitoring
aws configservice put-config-rule \
  --config-rule file://config-rules.json

# Проверка compliance
aws configservice get-compliance-details-by-config-rule \
  --config-rule-name s3-bucket-public-read-prohibited
```

**Полезные Config Rules:**
- `s3-bucket-public-read-prohibited` — запрещает публичный доступ.
- `s3-bucket-ssl-requests-only` — требует HTTPS.
- `s3-bucket-server-side-encryption-enabled` — требует шифрования.
- `s3-bucket-versioning-enabled` — требует versioning.
- `s3-bucket-logging-enabled` — требует access logging.
- `s3-bucket-object-lock-enabled` — требует Object Lock.

---

## 9. Backup и disaster recovery

### 9.1 S3 Cross-Region Replication (CRR)

```bash
# Создание replication IAM role
aws iam create-role \
  --role-name s3-replication-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "s3.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Настройка replication
aws s3api put-bucket-replication \
  --bucket my-app-prod-assets \
  --replication-configuration '{
    "Role": "arn:aws:iam::123456789012:role/s3-replication-role",
    "Rules": [{
      "ID": "ReplicateToDR",
      "Status": "Enabled",
      "Priority": 1,
      "Destination": {
        "Bucket": "arn:aws:s3:::my-app-dr-bucket",
        "StorageClass": "STANDARD_IA",
        "EncryptionConfiguration": {
          "ReplicaKmsKeyID": "arn:aws:kms:us-east-1:123456789012:alias/dr-key"
        }
      },
      "Filter": {"Prefix": ""}
    }]
  }'
```

### 9.2 S3 Batch Operations

```bash
# Создание job для массового копирования
aws s3control create-job \
  --account-id 123456789012 \
  --operation '{"S3PutObjectCopy": {"TargetResource": "arn:aws:s3:::my-app-dr-bucket", "CannedAccessControlList": "private"}}' \
  --report '{"Bucket": "arn:aws:s3:::my-app-audit-logs", "Format": "Report_CSV_20180820", "Enabled": true, "Prefix": "batch-reports/"}' \
  --manifest '{"Spec": {"Format": "S3BatchOperations_CSV_20180820", "Fields": ["Bucket", "Key"]}, "Location": {"ObjectArn": "arn:aws:s3:::my-app-prod-assets/manifest.csv", "ETag": "ETAG"}}' \
  --description "DR replication job" \
  --priority 10 \
  --role-arn arn:aws:iam::123456789012:role/s3-batch-ops-role
```

---

## 10. Security best practices (Production Checklist)

### Data Protection
- [ ] Включён **SSE-KMS** для всех bucket'ов с sensitive данными.
- [ ] Используется **Bucket Key Enabled** для снижения стоимости KMS.
- [ ] Для compliance: настроен **Object Lock** (Compliance или Governance).
- [ ] Включён **Versioning** для защиты от случайного удаления.
- [ ] Настроены **Lifecycle policies** для автоматического управления Storage Class.

### Access Control
- [ ] Включён **Block Public Access** на уровне account и bucket.
- [ ] Используются **IAM Roles** (OIDC) вместо статических ключей.
- [ ] Настроена **Bucket Policy** с explicit Deny для неавторизованного доступа.
- [ ] Используется **VPC Endpoint** для изоляции трафика.
- [ ] Отключены **ACL** (`BucketOwnerEnforced`).

### Audit & Monitoring
- [ ] Включён **CloudTrail data events** для всех S3 операций.
- [ ] Включён **S3 Access Logging**.
- [ ] Настроены **AWS Config Rules** для compliance monitoring.
- [ ] Используется **S3 Inventory** для регулярного аудита.
- [ ] Настроены alerts на аномалии (публичный доступ, нешифрованные загрузки).

### Incident Response
- [ ] Документирован playbook для security incident (публичный bucket, утечка данных).
- [ ] Настроены automated alerts через CloudWatch/SNS.
- [ ] Регулярно тестируется восстановление state/data из backup.
- [ ] Настроен процесс rotation credentials (OIDC, IAM Roles).

---

## 11. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [Ansible и S3: интеграция, автоматизация и эксплуатация](./ansible-integration.md)
- [Обзор систем хранения данных (СХД)](../data_storage_overview.md)
- [Ceph RGW: S3-совместимое хранилище на базе Ceph](../../../Kubernetes/Storage/Ceph/ceph_rgw_s3.md)
