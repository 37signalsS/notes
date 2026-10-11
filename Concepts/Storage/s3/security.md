# S3: безопасность, шифрование и compliance

**Актуально для:** Ceph RGW (Squid 19.x / Tentacle 20.x / Umbrella 21.x)

---

## 1. Определения

**Data at Rest** — данные, хранящиеся на диске (в S3 bucket). Требуют защиты от несанкционированного доступа.

**Почему это важно:** Data at rest включает все объекты в S3 — бэкапы баз данных, артефакты сборок, логи, конфигурации с секретами. При компрометации credentials злоумышленник получает прямой доступ к этим данным. Шифрование at rest защищает даже при физическом доступе к дискам или логическому доступу к bucket.

**Data in Transit** — данные при передаче между клиентом и S3. Требуют шифрования через TLS.

**Почему это важно:** Без TLS credentials, объекты и metadata передаются в открытом виде. В corporate сети или интернете это позволяет перехватить секреты (access key, secret key) или содержимое объектов. TLS 1.2+ обязателен для всех S3 операций в production.

**SSE-S3** — Server-Side Encryption с ключами, управляемыми самой S3-совместимой реализацией. AES-256.

**SSE-KMS** — Server-Side Encryption с ключами из внешнего или встроенного Key Management Service. В Ceph RGW — через `rgw crypto` или HashiCorp Vault. Поддерживает rotation ключей, аудит, granular permissions.

**SSE-C** — Server-Side Encryption с ключами от клиента. Сервис не хранит ключ.

**Client-Side Encryption** — шифрование на стороне клиента до загрузки в S3.

**Object Lock** — WORM-механизм, защищающий объекты от удаления/изменения в течение заданного срока.

**Immutability** — свойство данных, при котором они защищены от любого изменения или удаления (даже администратором).

**CORS (Cross-Origin Resource Sharing)** — механизм, позволяющий браузерам выполнять запросы к S3 bucket с других origins.

**Presigned URL** — подписанный URL, дающий ограниченный по времени доступ к объекту без раскрытия credentials.

**Path-style addressing** — стиль адресации, при котором bucket указан в пути URL: `https://s3.example.com/bucket-name/key`. Стандарт для Ceph RGW.

**rgw crypto** — встроенный механизм шифрования Ceph RGW. Поддерживает SSE-KMS с внешним Vault или внутренним ключом.

**HashiCorp Vault** — внешний KMS для управления ключами шифрования. Интегрируется с Ceph RGW через `rgw crypto` plugin.

---

## 2. Базовые концепции безопасности

### 2.1 Модель безопасности S3

S3 использует **multi-layered security model**:

1. **Network layer:** TLS 1.2+ для всех операций, изоляция трафика через firewall / network policies.
2. **Identity layer:** Access keys, роли, bucket policies, ACL.
3. **Encryption layer:** SSE-S3, SSE-KMS (rgw crypto / Vault), SSE-C, Client-Side Encryption.
4. **Data layer:** Object Lock, Versioning, Replication, Lifecycle.
5. **Audit layer:** Access Logging, application-level audit, metrics, OPA policies.

**Почему multi-layered:** Защита в глубину (defense in depth). Даже если один слой скомпрометирован (например, credentials украдены), другие слои (encryption, network isolation, audit) ограничивают ущерб. В production все слои должны быть включены, а не только один.

### 2.2 Аутентификация и авторизация

**Аутентификация:**
- **Access Key + Secret Key** — статические credentials для сервисных аккаунтов.
- **STS / временные credentials** — краткоживущие ключи, выдаваемые внешним сервисом (HashiCorp Vault, LDAP, OIDC). Рекомендуются для production.
- **Signature v4** — алгоритм подписи запросов. Все S3-совместимые реализации его поддерживают.
- **IAM-подобные роли** — встроенные роли в Ceph RGW для разделения обязанностей.

**Авторизация:**
- **Bucket Policy** — JSON-документ на уровне bucket, определяющий кто и что может делать.
- **IAM Policy / пользовательские политики** — политики, привязанные к identity (пользователь, роль, сервисный аккаунт).
- **ACL** — устаревший механизм контроля доступа на уровне объекта. В новых deployment'ах отключается (`BucketOwnerEnforced`).

**Path-style addressing:**
- **Path-style:** `https://s3.example.com/bucket-name/key` — bucket в пути. Используется для self-hosted реализаций. Ceph RGW по умолчанию использует path-style или поддерживает оба режима.

**Почему это важно:** Неправильный стиль адресации — частая причина 403 Forbidden при работе с self-hosted S3. При настройке SDK/CLI явно указывайте `path_style: true` для внутренних хранилищ.

### 2.3 CORS

CORS позволяет браузерам выполнять запросы к S3 bucket с других origins. Критично для web-приложений, загружающих файлы напрямую в S3.

```json
{
  "CORSRules": [
    {
      "AllowedOrigins": ["https://app.example.com", "https://admin.example.com"],
      "AllowedMethods": ["GET", "PUT", "POST", "DELETE"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag", "x-amz-version-id"],
      "MaxAgeSeconds": 3000
    }
  ]
}
```

**Важно:**
- `AllowedOrigins: ["*"]` с `AllowedMethods: ["PUT"]` опасен — любой сайт может загружать данные в ваш bucket.
- Для production ограничьте origins конкретными доменами.
- `MaxAgeSeconds` кэширует preflight-ответ, уменьшая latency для браузера.

---

## 3. Шифрование

### 3.1 Server-Side Encryption (SSE)

**SSE-S3:**
- Ключи управляются самой S3-совместимой реализацией (Ceph RGW).
- AES-256 шифрование.
- Бесплатно (включено в стоимость хранилища).
- Нет rotation, нет granular audit.
- Подходит для non-sensitive данных.

**SSE-KMS (рекомендуется для production) — Ceph RGW:**
- Встроенный KMS через `rgw crypto` или интеграция с HashiCorp Vault.
- Настройка через `radosgw-admin` или Ceph Dashboard.
- Поддерживает automatic key rotation (через Vault).
- Аудит использования ключей.
- Granular permissions.
- Возможность импорта собственных ключей (BYOK - Bring Your Own Key).

**SSE-C:**
- Клиент предоставляет ключ для каждого запроса.
- Сервис не хранит ключ.
- Используется для compliance требований, когда провайдер не должен иметь доступ к ключам.
- **Важно:** если потеряете ключ — потеряете данные. Нет rotation.

**Зачем выбирать SSE-KMS вместо SSE-S3:**
- **Контроль над ключами:** Вы управляете ключами, можете их отозвать, посмотреть историю использования.
- **Аудит:** Логируется каждое использование ключа (кто, когда, для какого объекта).
- **Rotation:** Автоматическая ротация ключей без повторного шифрования всех объектов.
- **Compliance:** Многие стандарты (PCI DSS, HIPAA) требуют контроля над ключами шифрования.

### 3.2 Настройка SSE-KMS (Ceph RGW)

```bash
# Включение rgw crypto в Ceph config
ceph config set mgr mgr/radosgw/enable_cors true
ceph config set rgw rgw_crypt_require_ssl false

# Или интеграция с HashiCorp Vault
# Настройка в ceph.conf:
# [client.rgw]
# rgw crypt vault addr = https://vault.example.com:8200
# rgw crypt vault token = s.XXXXXX
# rgw crypt vault secret engine = transit
```

**KMS key rotation в Ceph RGW:**
```bash
# Если используется Vault — rotation выполняется через Vault API:
vault write -force transit/keys/my-rgw-key/rotate

# RGW автоматически подхватывает новый ключ при следующей операции
```

### 3.3 Client-Side Encryption

```python
import boto3
from cryptography.fernet import Fernet

s3 = boto3.client('s3',
    endpoint_url='http://rgw:7480',
    region_name='us-east-1'
)

# Шифрование перед загрузкой
key = Fernet.generate_key()
cipher = Fernet(key)

with open('sensitive-data.tar.gz', 'rb') as f:
    encrypted_data = cipher.encrypt(f.read())

# Загрузка зашифрованных данных
s3.put_object(
    Bucket='my-app-prod-assets',
    Key='encrypted/sensitive-data.tar.gz.enc',
    Body=encrypted_data
)

# Сохранение ключа в Vault или внешнем KMS
# Никогда не храните ключ рядом с зашифрованными данными!
```

**Use cases:**
- Compliance требования, когда провайдер не должен иметь доступ к ключам.
- Defense in depth: дополнительный слой защиты поверх SSE-KMS.

---

## 4. IAM Policies и контроль доступа

### 4.1 Bucket Policy

Bucket Policy — JSON-документ на уровне bucket, определяющий кто и что может делать. Синтаксис совместим с AWS IAM Policy grammar, поэтому примеры ниже работают в Ceph RGW.

**Для Ceph RGW:**
```bash
# Создание пользователя с policy
radosgw-admin user create \
  --uid="my-user" \
  --display-name="My Service User" \
  --system

# Применение bucket policy через S3 API
aws s3api put-bucket-policy \
  --bucket my-app-prod-assets \
  --policy file://bucket-policy.json \
  --endpoint-url http://rgw:7480
```

**Пример bucket policy:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowListBucket",
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::rgw:user/my-user"},
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::my-app-prod-assets",
      "Condition": {"StringLike": {"s3:prefix": "releases/*"}}
    },
    {
      "Sid": "AllowReadWriteReleases",
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::rgw:user/my-user"},
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::my-app-prod-assets/releases/*"
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
    }
  ]
}
```

### 4.3 Presigned URLs

Presigned URLs дают ограниченный по времени доступ к объекту без раскрытия credentials. Все S3-совместимые SDK поддерживают генерацию presigned URL.

**Для Ceph RGW через Python (boto3):**
```python
import boto3
from botocore.client import Config

s3 = boto3.client('s3',
    endpoint_url='http://rgw:7480',
    region_name='us-east-1',
    config=Config(signature_version='s3v4')
)

# Генерация presigned URL для GET
url = s3.generate_presigned_url(
    'get_object',
    Params={'Bucket': 'my-bucket', 'Key': 'releases/app.tar.gz'},
    ExpiresIn=3600
)

# Генерация presigned URL для PUT
url = s3.generate_presigned_url(
    'put_object',
    Params={'Bucket': 'my-bucket', 'Key': 'uploads/file.tar.gz'},
    ExpiresIn=3600
)
```

**Зачем presigned URLs:**
- Безопасная передача временного доступа клиентам без выдачи постоянных credentials.
- Загрузка файлов из браузера/мобильного приложения напрямую в S3, минуя backend.
- Ограничение по времени и IP.

---

## 5. S3 Object Lock (WORM)

### 5.1 Режимы retention

| Режим | Governance | Compliance |
|-------|-----------|------------|
| **Кто может удалить** | Пользователи с `s3:BypassGovernanceRetention` | Никто, включая root account |
| **Можно сократить retention** | Да (с special permission) | Нет |
| **Использование** | Operational flexibility | Regulatory compliance (SEC 17a-4, FINRA) |

### 5.2 Настройка Object Lock в Ceph RGW

```bash
# Включение Object Lock через radosgw-admin
radosgw-admin bucket create \
  --bucket=my-app-prod-assets \
  --object-lock-enabled

# Настройка retention через S3 API
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
```

### 5.3 Legal Hold

```bash
# Установка Legal Hold через API
aws s3api put-object-legal-hold \
  --bucket my-app-prod-assets \
  --key backups/etcd-snapshot.db \
  --legal-hold Status=ON \
  --endpoint-url http://rgw:7480
```

**Разница Legal Hold vs Retention:**
- **Legal Hold:** бессрочная, пока явно не снята. Используется для litigation, investigations.
- **Retention:** фиксированный срок. Автоматически истекает.

---

## 6. Audit и мониторинг

### 6.1 Access Logging

S3 Access Logging — механизм записи всех запросов к bucket в отдельный target bucket. Доступен во всех S3-совместимых реализациях включая Ceph RGW.

```bash
# Включение через S3 API
aws s3api put-bucket-logging \
  --bucket my-app-prod-assets \
  --bucket-logging-status '{
    "LoggingEnabled": {
      "TargetBucket": "my-app-audit-logs",
      "TargetPrefix": "s3-logs/my-app-prod-assets/"
    }
  }' \
  --endpoint-url http://rgw:7480
```

### 6.2 radosgw-admin audit

```bash
# Просмотр операций через radosgw-admin
radosgw-admin user stats --uid="app-user"
radosgw-admin bucket stats --bucket="my-app-prod-assets"
radosgw-admin client list
radosgw-admin log list
```

### 6.3 OPA Policies + Access Log Analysis

Подробное описание OPA policies, скриптов compliance monitoring и анализа access logs приведено в:
- [S3: compliance-мониторинг и анализ доступа](./access-analyzer.md)

Там содержатся готовые Rego-политики для Ceph RGW, Python-скрипты для анализа логов, bash-скрипты для compliance проверок и интеграция с CI/CD.

### 6.4 Инвентаризация и сканирование

Для compliance аудита и инвентаризации объектов используйте:
- **radosgw-admin bucket stats** — статистика bucket в Ceph RGW.
- **aws s3api list-objects-v2** — перечисление объектов.
- **Python/pandas** — анализ CSV inventory отчётов.

**Пример rclone scan:**
```bash
# Сканирование bucket и вывод CSV отчёта
rclone ls s3://my-app-prod-assets --max-depth 1 > inventory.csv
```

---

## 7. Compliance frameworks

### 7.1 PCI DSS

**Требования для S3:**
- Шифрование данных at rest (SSE-KMS) — Requirement 3.
- Шифрование данных in transit (TLS 1.2+) — Requirement 4.
- Access control (Bucket Policy, IAM) — Requirement 7.
- Audit logging (Access Logs, application audit) — Requirement 10.
- Regular scanning (inventory, compliance checks) — Requirement 11.

### 7.2 HIPAA

**Требования для S3:**
- Шифрование at rest (SSE-KMS) и in transit (TLS).
- Access logging и audit trails.
- Object Lock для immutability audit logs.

### 7.3 SEC Rule 17a-4 / FINRA

**Требования:**
- Object Lock в режиме **Compliance** для broker-dealer records.
- Retention period ≥ 3 года (first 2 years in easily accessible format).
- Immutability: данные не могут быть изменены или удалены.
- Audit trail всех операций.

**Для Ceph RGW:**
```bash
# Настройка retention policy
aws s3api put-object-lock-configuration \
  --bucket my-locked-bucket \
  --object-lock-configuration '{
    "ObjectLockEnabled": "Enabled",
    "Rule": {
      "DefaultRetention": {
        "Mode": "COMPLIANCE",
        "Days": 1095
      }
    }
  }' \
  --endpoint-url http://rgw:7480
```

---

## 8. Incident Response

### 8.1 План реагирования на security incident

**Сценарий 1: Публичный bucket**

```bash
# 1. Немедленное действие: отозвать публичный доступ
aws s3api put-bucket-policy \
  --bucket my-app-prod-assets \
  --policy '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::my-app-prod-assets/*"
    }]
  }' \
  --endpoint-url http://rgw:7480

# 2. Проверить access logs на аномалии
grep "GET.*my-app-prod-assets" /var/log/ceph/radosgw.*.log | tail -50
```

**Сценарий 2: Утечка данных (data exfiltration)**

```bash
# 1. Отозвать compromised credentials
radosgw-admin user rm --uid="compromised-user" --purge-data

# 2. Проверить access logs на аномальные GET запросы
grep "GET.*sensitive-data" /var/log/ceph/radosgw.*.log | awk '{print $1}' | sort | uniq -c | sort -rn

# 3. Проверить source IP в access logs
grep "sensitive-data" /var/log/ceph/radosgw.*.log | awk '{print $4}' | sort | uniq -c | sort -rn
```

### 8.2 Compliance monitoring

Подробное руководство по continuous compliance monitoring приведено в:
- [S3: compliance-мониторинг и анализ доступа](./access-analyzer.md)

Там описаны OPA policies, скрипты проверок, интеграция с Prometheus/Grafana и алерты для Ceph RGW.

---

## 9. Backup и disaster recovery

Подробное руководство по настройке multisite репликации, runbook'ам инцидентов, preventive controls и drill-testing приведено в:
- [S3: disaster recovery runbook](./dr-runbook.md)

### 9.1 Массовые операции

```bash
# Массовое копирование bucket'а через aws-cli
aws s3 sync s3://my-app-prod-assets s3://my-app-dr-bucket \
  --endpoint-url http://rgw:7480 \
  --progress
```

---

## 10. Performance tuning для Ceph RGW

### 10.1 Именование объектов (prefix naming)

S3-совместимые хранилища используют hash-таблицы для распределения объектов. При частом доступе к объектам с одинаковым prefix'ом возникает hotspot.

**Рекомендации:**
- Используйте случайный префикс (2-8 hex символов) в начале ключа: `a3f2/releases/app.tar.gz`.
- Для временно-именоваемых объектов добавляйте timestamp: `20240928/releases/app.tar.gz`.
- Избегайте последовательных имён: `log-0001`, `log-0002` — создают hotspot.

### 10.2 Multipart upload tuning

**Минимальный размер части:** 5MB (S3 API). Для Ceph RGW с высокой задержкой увеличивайте до 16-64MB.

```bash
# Настройка через Ceph config
ceph config set rgw rgw_multipart_part_size 65536
```

### 10.3 Сетевая оптимизация

- **HTTP/2** — поддержка в RGW. Включает multiplexing и header compression.
- **Keep-Alive** — переиспользование соединений. Включается по умолчанию в большинстве SDK.
- **DNS round-robin** — для распределения нагрузки между node'ами кластера.
- **CDN** — для статических assets (артефакты, образы). CDN кэширует объекты на edge, снижая latency.

### 10.4 Monitoring и алерты

Для Ceph RGW используйте:
- **Prometheus + RGW exporter** — метрики из встроенных exporter'ов.
- **Grafana dashboards** — визуализация метрик RGW.
- **Алерты:** 5xx ошибки, высокая latency, отсутствие шифрования, публичный доступ.

---

## 11. Security best practices (Production Checklist)

### Data Protection
- [ ] Включён **SSE-KMS** для всех bucket'ов с sensitive данными (через rgw crypto или Vault).
- [ ] Для compliance: настроен **Object Lock** (Compliance или Governance).
- [ ] Включён **Versioning** для защиты от случайного удаления.
- [ ] Настроены **Lifecycle policies** для автоматического управления Storage Class (hot/warm/cold pools).
- [ ] Для high-volume workloads настроено multipart upload tuning.

### Access Control
- [ ] Включён **Block Public Access** на уровне account и bucket.
- [ ] Используются **краткоживущие credentials** (STS, Vault, OIDC) вместо статических ключей.
- [ ] Настроена **Bucket Policy** с explicit Deny для неавторизованного доступа.
- [ ] Используется **path-style addressing** для внутренних хранилищ.
- [ ] Отключены **ACL** (`BucketOwnerEnforced`).

### Audit & Monitoring
- [ ] Включён **Access Logging**.
- [ ] Настроены **Prometheus/Grafana** для метрик и алертов.
- [ ] Используется **inventory scanning** (radosgw-admin bucket stats, aws s3api list-objects-v2) для регулярного аудита.
- [ ] Настроены alerts на аномалии (публичный доступ, нешифрованные загрузки, высокий объём ошибок).

### Incident Response
- [ ] Документирован playbook для security incident (публичный bucket, утечка данных).
- [ ] Регулярно тестируется восстановление state/data из backup.
- [ ] Настроен процесс rotation credentials.
- [ ] Настроены алерты на аномалии через Prometheus Alertmanager или аналоги.

### Performance & Cost
- [ ] Настроено prefix naming для избежания hotspot'ов.
- [ ] Настроен multipart upload tuning для загрузки больших файлов.
- [ ] Используется CDN для статических assets.
- [ ] Настроены lifecycle policies для автоматического перехода между hot/warm/cold pools.

---

## 12. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [Ansible и S3: интеграция, автоматизация и эксплуатация](./ansible-integration.md)
- [Ceph RGW: S3-совместимое хранилище на базе Ceph](../../../Kubernetes/Storage/Ceph/ceph_rgw_s3.md)
