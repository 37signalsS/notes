# S3: compliance-мониторинг и анализ доступа

**Актуально для:** Ceph RGW (Squid 19.x / Tentacle 20.x / Umbrella 21.x)

---

## 1. Определения

**Compliance monitoring** — автоматизированный контроль соответствия конфигурации S3-совместимого хранилища требованиям стандартов (PCI DSS, HIPAA, SEC Rule 17a-4).

**OPA (OpenPolicyAgent)** — политико-ориентированный движок для валидации конфигураций. Используется для проверки bucket policies на соответствие стандартам.

**Public bucket** — bucket, доступный через internet без аутентификации. Частая причина утечек данных.

**Cross-tenant access** — доступ к bucket'у из другого тенанта Ceph RGW. Может быть intentional, но требует аудита.

**Shared access** — доступ к bucket'у из других сервисов или через IAM-подобные роли.

**Unused access** — permissions, присвоенные принципалам (пользователи RGW), которые не использовались за определённый период.

**Policy validation** — проверка bucket policy и ACL на соответствие best practices (публичный доступ, wildcard permissions, нешифрованные загрузки).

**radosgw-admin audit** — встроенный механизм аудита операций RGW. Записывает события в логи Ceph или внешние системы (Loki, Elasticsearch).

**S3 Access Logging** — механизм записи всех запросов к bucket в отдельный target bucket. Доступен во всех S3-совместимых реализациях включая Ceph RGW.

---

## 2. Базовые концепции

### 2.1 Зачем compliance monitoring

S3 bucket'ы — самые частые источники утечек данных. Автоматический анализ обнаруживает:

| Тип доступа | Риск | Пример |
|-------------|------|--------|
| **Public** | Утечка данных | `Principal: "*"` с `s3:GetObject` |
| **Cross-tenant** | Несанкционированный доступ | Внешний тенант с `s3:PutObject` |
| **Cross-origin (CORS)** | Утечка через browser | `AllowedOrigins: "*"` |
| **Unencrypted uploads** | Данные в открытом виде | Отсутствие SSE в bucket policy |

### 2.2 Архитектура compliance monitoring

```
┌─────────────────────────────────────────────────────────┐
│                    Compliance Monitoring                  │
│                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐ │
│  │ OPA Policies│    │ RGW Access  │    │  Custom     │ │
│  │ Validation  │    │ Log Analysis│    │  Scripts    │ │
│  └─────────────┘    └─────────────┘    └─────────────┘ │
│                                                         │
│  Input:                                                  │
│  - Bucket policies (JSON)                                │
│  - ACL configurations                                    │
│  - RGW access logs (/var/log/ceph/radosgw.log)           │
│  - radosgw-admin audit output                            │
│                                                         │
│  Output:                                                 │
│  - Public bucket detection                               │
│  - Cross-tenant access audit                             │
│  - Unused access identification                           │
│  - Compliance reports (PCI DSS, HIPAA, SEC 17a-4)       │
└─────────────────────────────────────────────────────────┘
```

**Компоненты:**

1. **OPA Policies** — декларативные правила в Rego, проверяющие bucket policies на предмет:
   - Публичного доступа (`Principal: "*"`)
   - Отсутствия шифрования
   - Отключённого versioning
   - Небезопасных CORS настроек

2. **RGW Access Log Analysis** — парсинг логов RGW для выявления:
   - Аномальных IP адресов
   - Паттернов доступа
   - Ошибок 4xx/5xx

3. **Custom Scripts** — автоматизированные проверки через:
   - AWS CLI с endpoint RGW
   - Python + boto3
   - Bash скрипты для CI/CD

### 2.3 Severity levels

| Severity | Описание | Действие |
|----------|----------|----------|
| **High** | Public bucket или cross-tenant write | Немедленное действие |
| **Medium** | Cross-tenant read или нешифрованные загрузки | План действий |
| **Low** | Internal cross-tenant, unused access | Audit |

### 2.4 Типы доступа и анализ

| Тип доступа | Метод обнаружения | Частота проверки |
|-------------|-------------------|------------------|
| **Public** | OPA policy + ACL scan | При каждом изменении policy |
| **Cross-tenant** | Access log analysis + IAM audit | Weekly |
| **Shared** | IAM policy review | Monthly |
| **Unused** | Access log analysis (90 дней) | Quarterly |

---

## 3. Предварительные требования

### 3.1 Инфраструктура

- **Ceph RGW кластер** — работоспособный кластер Ceph с RGW gateway (Squid 19.x / Tentacle 20.x / Umbrella 21.x)
- **AWS CLI** — настроен с endpoint RGW (`--endpoint-url http://rgw:7480`)
- **Python 3.8+** — с пакетами `boto3`, `pandas` для анализа логов
- **OPA** — установленный OpenPolicyAgent для валидации policies
- **Prometheus + RGW exporter** — для сбора метрик (порт 9283 по умолчанию)
- **Grafana** — для визуализации алертов
- **Доступ к admin socket** — `radosgw-admin` для аудита операций

### 3.2 Конфигурация AWS CLI

```bash
# ~/.aws/config
[default]
region = us-east-1
output = json

# Для работы с RGW endpoint
aws s3 ls --endpoint-url http://rgw:7480
aws s3api get-bucket-policy --bucket my-bucket --endpoint-url http://rgw:7480
```

### 3.3 Разрешения

Для полноценного аудита требуются следующие permissions:
- `s3:GetBucketPolicy` — чтение bucket policies
- `s3:GetBucketAcl` — чтение ACL
- `s3:GetBucketVersioning` — проверка versioning
- `s3:GetBucketEncryption` — проверка encryption
- `s3:GetBucketLogging` — проверка access logging
- `s3:ListBucket` — перечисление объектов
- `radosgw-admin` execution — для Ceph-специфичного аудита

---

## 4. Практические сценарии

### 4.1 OPA Policies для Ceph RGW

**Запрет public buckets:**
```rego
package s3.policy

deny[msg] {
  bucket := input.bucket
  policy := input.bucketPolicy
  statement := policy.Statement[_]
  statement.Effect == "Allow"
  statement.Principal == "*"
  statement.Action[_] == "s3:GetObject"
  msg := sprintf("Public bucket detected: %s", [bucket])
}
```

**Запрет нешифрованных загрузок:**
```rego
deny[msg] {
  bucket := input.bucket
  policy := input.bucketPolicy
  statement := policy.Statement[_]
  statement.Effect == "Allow"
  statement.Action[_] == "s3:PutObject"
  not statement.Condition.StringNotEquals["s3:x-amz-server-side-encryption"]
  msg := sprintf("Unencrypted uploads allowed: %s", [bucket])
}
```

**Обязательное versioning:**
```rego
deny[msg] {
  bucket := input.bucket
  versioning := input.versioning.Status
  versioning != "Enabled"
  msg := sprintf("Versioning not enabled: %s", [bucket])
}
```

**Запрет небезопасных CORS:**
```rego
deny[msg] {
  bucket := input.bucket
  cors := input.corsConfiguration
  rule := cors.CORSRules[_]
  rule.AllowedOrigins[_] == "*"
  msg := sprintf("Unsafe CORS configuration detected: %s", [bucket])
}
```

**Проверка OPA:**
```bash
# Загрузка policy
opa policy load s3-policy.rego

# Валидация bucket
echo '{"bucket": "my-bucket", "bucketPolicy": {...}, "versioning": {"Status": "Enabled"}}' | \
  opa eval -i /dev/stdin -d s3-policy.rego "data.s3.policy.deny"
```

### 4.2 Анализ access logs через Python

```python
import pandas as pd
import re
from datetime import datetime

# Чтение RGW access logs
log_pattern = r'(?P<remote_user>\S+) \[(?P<time>.*?)\] (?P<remote_addr>\S+) (?P<request>.*?) (?P<status>\d{3})'

logs = []
with open('/var/log/ceph/radosgw.log') as f:
    for line in f:
        match = re.match(log_pattern, line)
        if match:
            logs.append(match.groupdict())

df = pd.DataFrame(logs)

# Поиск публичного доступа (GET запросы без аутентификации)
public_access = df[df['request'].str.contains('GET', case=False)]
print(f"Public GET requests: {len(public_access)}")

# Поиск необычных IP (топ 10)
ip_counts = df['remote_addr'].value_counts()
print("Top 10 IPs by request count:")
print(ip_counts.head(10))

# Поиск 4xx/5xx ошибок
errors = df[df['status'].str.startswith(('4', '5'))]
print(f"Errors: {len(errors)}")
print(f"Error rate: {len(errors)/len(df)*100:.2f}%")

# Анализ по временным интервалам
df['hour'] = pd.to_datetime(df['time'], format='%d/%b/%Y:%H:%M:%S').dt.hour
hourly_requests = df.groupby('hour').size()
print("Hourly request distribution:")
print(hourly_requests)
```

### 4.3 Проверка всех bucket'ов на compliance

```bash
#!/bin/bash
# /usr/local/bin/check_s3_compliance.sh

ENDPOINT="http://rgw:7480"
REPORT_FILE="/var/log/s3-compliance-$(date +%Y%m%d).txt"

echo "S3 Compliance Check - $(date)" > $REPORT_FILE
echo "=================================" >> $REPORT_FILE

# Получение списка bucket'ов
buckets=$(aws s3 ls --endpoint-url $ENDPOINT | awk '{print $3}')

for bucket in $buckets; do
  echo "Checking: $bucket" | tee -a $REPORT_FILE
  alerts=0

  # Проверка versioning
  versioning=$(aws s3api get-bucket-versioning --bucket $bucket --endpoint-url $ENDPOINT 2>/dev/null)
  if [ $? -ne 0 ] || [ "$versioning" != '{"Status":"Enabled"}' ]; then
    echo "  ALERT: Versioning not enabled" | tee -a $REPORT_FILE
    alerts=$((alerts+1))
  fi

  # Проверка encryption
  encryption=$(aws s3api get-bucket-encryption --bucket $bucket --endpoint-url $ENDPOINT 2>/dev/null)
  if [ $? -ne 0 ]; then
    echo "  ALERT: Encryption not enabled" | tee -a $REPORT_FILE
    alerts=$((alerts+1))
  fi

  # Проверка logging
  logging=$(aws s3api get-bucket-logging --bucket $bucket --endpoint-url $ENDPOINT 2>/dev/null)
  if [ $? -ne 0 ]; then
    echo "  ALERT: Logging not enabled" | tee -a $REPORT_FILE
    alerts=$((alerts+1))
  fi

  # Проверка public access
  acl=$(aws s3api get-bucket-acl --bucket $bucket --endpoint-url $ENDPOINT 2>/dev/null)
  if echo "$acl" | grep -q "AllUsers"; then
    echo "  ALERT: Public access detected" | tee -a $REPORT_FILE
    alerts=$((alerts+1))
  fi

  echo "  Alerts: $alerts" | tee -a $REPORT_FILE
  echo "" | tee -a $REPORT_FILE
done

echo "Report saved to: $REPORT_FILE"
```

**Использование:**
```bash
chmod +x /usr/local/bin/check_s3_compliance.sh
# Ручной запуск
/usr/local/bin/check_s3_compliance.sh

# Автоматический запуск через cron (ежедневно в 02:00)
0 2 * * * /usr/local/bin/check_s3_compliance.sh
```

### 4.4 Программный анализ (Python + boto3)

```python
import boto3
from botocore.exceptions import ClientError
from datetime import datetime

s3 = boto3.client('s3',
    endpoint_url='http://rgw:7480',
    region_name='us-east-1'
)

# Получение всех bucket'ов
buckets = s3.list_buckets()['Buckets']
report = []

for bucket in buckets:
    name = bucket['Name']
    bucket_report = {'name': name, 'alerts': []}

    # Проверка versioning
    try:
        versioning = s3.get_bucket_versioning(Bucket=name)
        if versioning.get('Status') != 'Enabled':
            bucket_report['alerts'].append("Versioning not enabled")
    except ClientError:
        bucket_report['alerts'].append("Cannot get versioning")

    # Проверка encryption
    try:
        encryption = s3.get_bucket_encryption(Bucket=name)
    except ClientError:
        bucket_report['alerts'].append("Encryption not enabled")

    # Проверка logging
    try:
        logging = s3.get_bucket_logging(Bucket=name)
        if not logging.get('LoggingEnabled'):
            bucket_report['alerts'].append("Logging not enabled")
    except ClientError:
        bucket_report['alerts'].append("Cannot get logging")

    # Проверка public access
    try:
        acl = s3.get_bucket_acl(Bucket=name)
        for grant in acl['Grants']:
            if grant['Grantee'].get('URI') == 'http://acs.amazonaws.com/groups/global/AllUsers':
                bucket_report['alerts'].append("Public access detected")
                break
    except ClientError:
        pass

    report.append(bucket_report)

# Генерация отчёта
for item in report:
    status = "OK" if not item['alerts'] else f"ALERTS: {', '.join(item['alerts'])}"
    print(f"{item['name']}: {status}")

# Сохранение в JSON
import json
with open(f'/tmp/s3-compliance-{datetime.now().strftime("%Y%m%d")}.json', 'w') as f:
    json.dump(report, f, indent=2)
```

### 4.5 Интеграция с CI/CD

```yaml
# .github/workflows/s3-compliance.yml
name: S3 Compliance Check

on:
  pull_request:
    paths:
      - 'terraform/**'
  schedule:
    - cron: '0 2 * * *'

jobs:
  compliance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup OPA
        run: |
          curl -L -o opa https://openpolicyagent.org/downloads/latest/opa_linux_amd64
          chmod +x opa
          sudo mv opa /usr/local/bin/

      - name: Validate bucket policies
        run: |
          for policy in terraform/policies/*.json; do
            opa eval -i $policy -d policies/ -f pretty "data.s3.policy.deny"
          done

      - name: Run compliance script
        run: |
          chmod +x scripts/check_s3_compliance.sh
          ./scripts/check_s3_compliance.sh
```

---

## 5. Валидация

### 5.1 Проверка OPA policies

**Ожидаемый результат:**
```bash
# Для public bucket — должен вернуть deny message
echo '{"bucket": "public-bucket", "bucketPolicy": {"Statement": [{"Effect": "Allow", "Principal": "*", "Action": ["s3:GetObject"]}]}}' | \
  opa eval -i /dev/stdin -d s3-policy.rego "data.s3.policy.deny"

# Output:
# [
#   {
#     "expressions": [
#       {
#         "value": [
#           "Public bucket detected: public-bucket"
#         ],
#         "text": "data.s3.policy.deny",
#         "location": {
#           "row": 1,
#           "col": 1
#         }
#       }
#     ]
#   }
# ]

# Для compliant bucket — должен вернуть пустой массив
echo '{"bucket": "secure-bucket", "bucketPolicy": {"Statement": [{"Effect": "Allow", "Principal": "arn:aws:iam::123456789012:root", "Action": ["s3:GetObject"]}]}}' | \
  opa eval -i /dev/stdin -d s3-policy.rego "data.s3.policy.deny"

# Output:
# []
```

### 5.2 Проверка compliance скрипта

**Ожидаемый результат:**
```bash
# Запуск скрипта
/usr/local/bin/check_s3_compliance.sh

# Output:
# S3 Compliance Check - Wed Sep 30 12:00:00 UTC 2026
# =================================
# Checking: my-bucket-1
#   ALERT: Encryption not enabled
#   Alerts: 1
#
# Checking: my-bucket-2
#   Alerts: 0
#
# Report saved to: /var/log/s3-compliance-20260930.txt
```

### 5.3 Проверка Prometheus metrics

```bash
# Проверка доступности metrics endpoint
curl -s http://rgw:9283/metrics | grep rgw_public_buckets

# Ожидаемый output:
# rgw_public_buckets{bucket="my-bucket"} 0

# Проверка алертов
curl -s http://localhost:9090/api/v1/alerts | jq '.data.alerts[] | select(.labels.alertname == "RGWPublicBucket")'
```

### 5.4 Проверка Python анализатора

```bash
# Запуск анализатора
python3 s3_access_analyzer.py

# Ожидаемый output:
# Public GET requests: 0
# Top 10 IPs by request count:
# 192.168.1.10    1523
# 192.168.1.11    984
# ...
# Errors: 23
# Error rate: 0.15%
# Hourly request distribution:
# 0     234
# 1     120
# ...
```

---

## 6. Monitoring через Prometheus + Grafana

### 6.1 Настройка Prometheus

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'rgw'
    static_configs:
      - targets: ['rgw1:9283', 'rgw2:9283', 'rgw3:9283']
    scrape_interval: 15s
```

### 6.2 Alert rules

```yaml
# alerts.yml
groups:
  - name: rgw_alerts
    rules:
      - alert: RGWHigh5xxErrors
        expr: sum(rate(rgw_5xx_errors[5m])) > 5
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High 5xx errors on RGW"

      - alert: RGWHigh4xxErrors
        expr: sum(rate(rgw_4xx_errors[5m])) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High 4xx errors on RGW"

      - alert: RGWPublicBucket
        expr: rgw_public_buckets > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Public bucket detected"

      - alert: RGWUnencryptedBucket
        expr: rgw_unencrypted_buckets > 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Unencrypted bucket detected"
```

### 6.3 Grafana dashboard

Используйте готовые dashboard'ы:
- **Ceph RGW Dashboard** — метрики RGW: запросы, ошибки, latency, размер bucket'ов.
- **Ceph Cluster Dashboard** — общие метрики кластера: OSD, PG, PgPool.

---

## 7. Граничные случаи и ограничения

### 7.1 Policy propagation delay

**Проблема:** OPA policy применена, но bucket policy ещё не обновился в RGW.

**Причина:** RGW кэширует bucket policies. Propagation может занимать от нескольких секунд до 1 минуты.

**Решение:**
```bash
# Проверка актуального policy
aws s3api get-bucket-policy --bucket my-bucket --endpoint-url http://rgw:7480

# Принудительное обновление кэша (если поддерживается RGW)
radosgw-admin cache flush --bucket my-bucket
```

### 7.2 Intentional cross-tenant access

**Проблема:** Cross-tenant access является часть архитектуры (например, replication между зонами).

**Решение:** Ведите реестр исключений (exceptions registry) с обоснованием:
```json
{
  "bucket": "my-bucket",
  "allowed_tenants": ["tenant-b", "tenant-c"],
  "justification": "Multisite replication requirement",
  "expires_at": "2026-12-31",
  "approved_by": "security-team"
}
```

### 7.3 ACL vs Bucket Policy precedence

**Проблема:** Bucket остаётся public даже после remediation через bucket policy.

**Причина:** ACL имеет более высокий приоритет чем bucket policy в некоторых сценариях.

**Решение:** Отключите ACL полностью:
```bash
# Включение BucketOwnerEnforced
aws s3api put-bucket-ownership-controls \
  --bucket my-bucket \
  --ownership-controls '{
    "Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]
  }' \
  --endpoint-url http://rgw:7480
```

### 7.4 Log rotation и retention

**Проблема:** Access logs занимают много места, старые логи удаляются.

**Решение:** Настройте lifecycle policy для audit logs:
```bash
# Перемещение logs в Glacier через 90 дней
aws s3api put-bucket-lifecycle-configuration \
  --bucket audit-logs \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "archive-old-logs",
      "Status": "Enabled",
      "Prefix": "s3-logs/",
      "Transitions": [{
        "Days": 90,
        "StorageClass": "GLACIER"
      }],
      "Expiration": {
        "Days": 2555
      }
    }]
  }' \
  --endpoint-url http://rgw:7480
```

### 7.5 Performance impact logging

**Проблема:** Access logging создаёт дополнительную нагрузку на RGW.

**Решение:**
- Используйте отдельный bucket для logs на другом физическом storage pool
- Настройте RGW для асинхронной записи логов
- Мониторьте latency при включённом логировании

### 7.6 Versioning disabled for cost optimization

**Проблема:** Versioning отключён для снижения стоимости storage.

**Решение:** Документируйте исключения в реестре:
```json
{
  "bucket": "temp-uploads",
  "versioning_disabled": true,
  "justification": "Temporary files, lifecycle deletes after 7 days",
  "approved_by": "ops-team",
  "review_date": "2026-12-31"
}
```

---

## 8. Troubleshooting

| Проблема | Причина | Диагностика | Решение |
|----------|---------|-------------|---------|
| OPA не детектирует public bucket | Bucket только что создан | Проверка OPA eval | Подождите propagation policies или rerun |
| False positive: internal cross-tenant | Intentional cross-tenant access | Проверка findings | Архивируйте finding, добавьте исключение в policy |
| Bucket остаётся public после remediation | ACL перезаписывает bucket policy | Проверка ACL и bucket policy | Отключите ACL (`BucketOwnerEnforced`) |
| OPA policy не применяется | Неправильный input format | Проверка OPA eval | Убедитесь, что input соответствует ожидаемому формату |
| Metrics не отображаются | RGW exporter не запущен | Проверка `curl http://rgw:9283/metrics` | Запустите RGW daemon с включённым exporter |
| Access logs не генерируются | Logging не включён на bucket | Проверка `aws s3api get-bucket-logging` | Включите logging через bucket policy или console |
| Compliance script падает с ошибкой | RGW endpoint недоступен | Проверка `curl $ENDPOINT` | Проверьте сеть и доступность RGW |
| OPA eval timeout | Большой volume policies | Проверка размера policy | Увеличьте timeout или оптимизируйте policy |

---

## 9. Best Practices

1. **Включите OPA validation** для всех bucket policies в CI/CD pipeline.
2. **Account-level Block Public Access** — первый barrier. Включайте по умолчанию для всех bucket'ов.
3. **Bucket Owner Enforced** — отключайте ACL на всех новых bucket'ах.
4. **Автоматический compliance check** — запускайте скрипт проверки nightly через cron.
5. **Regular audit** раз в квартал: проверка всех findings, unused access, cross-tenant permissions.
6. **Alerting на severity HIGH** — немедленное уведомление security team.
7. **Combine access logs + OPA** для полной картины доступа.
8. **Document exceptions:** Cross-tenant access иногда нужен. Ведите реестр исключений с обоснованием.
9. **Test incident response** раз в квартал: имитируйте public bucket, проверьте время обнаружения.
10. **Use Terraform/Terragrunt** для управления bucket policies как code.
11. **Enable versioning** на всех production bucket'ах — требуется для audit trail и disaster recovery.
12. **Encrypt at rest** — используйте SSE-KMS для всех sensitive данных.
13. **Monitor metrics** — настройте алерты на public buckets и missing encryption.
14. **Review OPA policies quarterly** — обновляйте правила под новые требования compliance.
15. **Centralize logs** — экспортируйте access logs в Loki/Elasticsearch для долгосрочного хранения.

---

## 10. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: безопасность, шифрование и compliance](./security.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [S3: защита от случайного удаления в Ceph RGW](./mfa-delete.md)
- [S3: Disaster Recovery runbook](./dr-runbook.md)
