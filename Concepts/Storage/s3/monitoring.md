# S3: мониторинг, алерты и cost optimization

## 1. Определения

**CloudWatch Metrics for S3** — стандартные метрики, доступные раз в сутки или раз в минуту (с оплатой). Включают размер bucket, количество объектов, количество запросов, ошибки, latency.

**Зачем мониторинг S3:** S3 — это обычно largest consumer storage в инфраструктуре. Не monitoring = неknowledge о:
- Растущих затратах (unexpected cost spikes).
- Инцидентах (5xxErrors, публичный bucket).
- Compliance violations (отсутствие шифрования, public access).
- Capacity planning (bucket растёт без контроля).

**S3 Storage Lens** — сервис организации-wide observability для S3. Предоставляет агрегированные метрики по bucket'ам, account, регионам.

**S3 Inventory** — ежедневные/еженедельные CSV/Parquet отчёты о всех объектах в bucket.

**Cost Explorer** — сервис для анализа затрат на S3 с breakdown по bucket, Storage Class, operation type.

---

## 2. CloudWatch Metrics

### 2.1 Стандартные метрики (Basic Metrics)

Доступны без дополнительной оплаты, отчёт раз в сутки:

| Метрика | Описание | Статистики |
|---------|----------|-----------|
| `BucketSizeBytes` | Размер bucket по Storage Class | Average |
| `NumberOfObjects` | Количество объектов | Average |
| `AllRequests` | Общее количество запросов | Sum |
| `GetRequests` | GET запросы | Sum |
| `PutRequests` | PUT запросы | Sum |
| `DeleteRequests` | DELETE запросы | Sum |
| `HeadRequests` | HEAD запросы | Sum |
| `4xxErrors` | Ошибки клиента (4xx) | Sum |
| `5xxErrors` | Ошибки сервиса (5xx) | Sum |
| `FirstByteLatency` | Задержка до первого байта | Average |
| `TotalRequestLatency` | Общая задержка запроса | Average |
| `ReplicationLatency` | Задержка репликации | Average |

**Ограничения basic metrics:**
- Доступны только для последних 2 недель.
- Отчёт раз в сутки (не real-time).
- Не включают detailed breakdown по prefix, tag, operation type.

### 2.2 Detailed Metrics (Request Metrics)

Предоставляют real-time данные (раз в минуту) с breakdown по:
- Operation type (GetObject, PutObject, DeleteObject).
- Bucket.
- Storage Class.

**Стоимость:** $0.30 за месяц за каждый bucket с включёнными detailed metrics.

```bash
# Включение detailed metrics для bucket
aws cloudwatch put-metric-data \
  --namespace AWS/S3 \
  --metric-name GetRequests \
  --dimensions BucketName=my-app-prod-assets,BucketType=StandardStorage \
  --value 0 \
  --timestamp $(date -u +%Y-%m-%dT%H:%M:%S)

# Или через bucket configuration
aws s3api put-bucket-metrics-configuration \
  --bucket my-app-prod-assets \
  --id EntireBucket \
  --metrics-configuration '{
    "Id": "EntireBucket",
    "Filter": {"Prefix": ""}
  }'
```

### 2.3 Получение метрик через CloudWatch CLI

```bash
# Получение размера bucket
aws cloudwatch get-metric-statistics \
  --namespace AWS/S3 \
  --metric-name BucketSizeBytes \
  --dimensions Name=BucketName,Value=my-app-prod-assets Name=StorageType,Value=StandardStorage \
  --start-time $(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 86400 \
  --statistics Average

# Получение количества запросов
aws cloudwatch get-metric-statistics \
  --namespace AWS/S3 \
  --metric-name AllRequests \
  --dimensions Name=BucketName,Value=my-app-prod-assets \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum
```

---

## 3. Алерты (CloudWatch Alarms)

### 3.1 Критические алерты

```bash
# 1. 5xxErrors — сервисные ошибки
aws cloudwatch put-metric-alarm \
  --alarm-name "s3-5xx-errors-my-app-prod-assets" \
  --alarm-description "Alert on S3 5xx errors" \
  --metric-name 5xxErrors \
  --namespace AWS/S3 \
  --statistic Sum \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=BucketName,Value=my-app-prod-assets \
  --alarm-actions arn:aws:sns:eu-central-1:123456789012:alerts

# 2. 4xxErrors — возможна атака или misconfiguration
aws cloudwatch put-metric-alarm \
  --alarm-name "s3-4xx-errors-my-app-prod-assets" \
  --alarm-description "Alert on high 4xx errors" \
  --metric-name 4xxErrors \
  --namespace AWS/S3 \
  --statistic Sum \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 100 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=BucketName,Value=my-app-prod-assets \
  --alarm-actions arn:aws:sns:eu-central-1:123456789012:alerts

# 3. High latency (TotalRequestLatency > 1s)
aws cloudwatch put-metric-alarm \
  --alarm-name "s3-high-latency-my-app-prod-assets" \
  --alarm-description "Alert on high S3 latency" \
  --metric-name TotalRequestLatency \
  --namespace AWS/S3 \
  --statistic Average \
  --period 300 \
  --evaluation-periods 3 \
  --threshold 1000 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=BucketName,Value=my-app-prod-assets \
  --alarm-actions arn:aws:sns:eu-central-1:123456789012:alerts
```

### 3.2 Cost-оптимизационные алерты

```bash
# 1. Рост размера bucket без соответствующих запросов (возможна утечка)
aws cloudwatch put-metric-alarm \
  --alarm-name "s3-bucket-size-unusual-growth" \
  --alarm-description "Alert on unusual bucket size growth" \
  --metric-name BucketSizeBytes \
  --namespace AWS/S3 \
  --statistic Average \
  --period 86400 \
  --evaluation-periods 2 \
  --threshold 100000000000 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=BucketName,Value=my-app-prod-assets Name=StorageType,Value=StandardStorage \
  --alarm-actions arn:aws:sns:eu-central-1:123456789012:alerts

# 2. Рост количества объектов без роста размера (много маленьких файлов)
aws cloudwatch put-metric-alarm \
  --alarm-name "s3-object-count-high" \
  --alarm-description "Alert on high object count" \
  --metric-name NumberOfObjects \
  --namespace AWS/S3 \
  --statistic Average \
  --period 86400 \
  --evaluation-periods 2 \
  --threshold 1000000 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=BucketName,Value=my-app-prod-assets \
  --alarm-actions arn:aws:sns:eu-central-1:123456789012:alerts
```

---

## 4. S3 Storage Lens

### 4.1 Включение Storage Lens

```bash
# Включение Storage Lens на уровне account
aws s3control put-storage-lens-configuration \
  --account-id 123456789012 \
  --config-id default \
  --storage-lens-configuration '{
    "AccountLevel": {
      "BucketLevel": {
        "ActivityMetrics": {"IsEnabled": true},
        "PrefixLevel": {"IsEnabled": true}
      },
      "StorageLensGroup": {
        "IsEnabled": true,
        "Filter": {
          "And": {
            "MatchAnyPrefix": {"Prefix": ""},
            "MatchAnyTag": {"Tag": {"Key": "env", "Value": "production"}}
          }
        }
      }
    },
    "IsEnabled": true,
    "AwsOrg": {"Arn": "arn:aws:organizations::123456789012:organization/o-exampleorg"},
    "DataExport": {
      "CloudWatchMetrics": {"IsEnabled": true},
      "S3BucketDestination": {
        "OutputSchemaVersion": "V_1",
        "AccountId": "123456789012",
        "Arn": "arn:aws:s3:::my-app-audit-logs",
        "Prefix": "storage-lens/",
        "Format": "CSV",
        "Encryption": {"SSES3": {}}
      }
    }
  }'
```

### 4.2 Storage Lens Groups

Группировка bucket'ов по criteria:

```json
{
  "StorageLensGroup": {
    "IsEnabled": true,
    "Filter": {
      "MatchAnyPrefix": {"Prefix": ["prod/", "staging/"]},
      "MatchAnyTag": {"Tag": {"Key": "team", "Value": "platform"}},
      "MatchObjectSize": {"MatchObjectSizeLessThan": 1048576}
    }
  }
}
```

**Use cases:**
- Мониторинг production bucket'ов отдельно от dev.
- Отслеживание hot/cold data patterns.
- Идентификация orphaned bucket'ов.

---

## 5. Cost monitoring и оптимизация

### 5.1 Cost Explorer

```bash
# Получение затрат на S3 по дням
aws ce get-cost-and-usage \
  --time-period Start=2024-01-01,End=2024-01-31 \
  --granularity DAILY \
  --metrics "BlendedCost" "UsageQuantity" \
  --group-by Type=DIMENSION,Key=SERVICE \
  --filter '{
    "Dimensions": {
      "Key": "SERVICE",
      "Values": ["Amazon Simple Storage Service"]
    }
  }'
```

### 5.2 S3 Storage Lens для cost insights

**Ключевые метрики для cost optimization:**
- **Bytes stored** — общий объём данных.
- **Bytes stored by Storage Class** — breakdown по Standard, IA, Glacier.
- **Operations** — количество операций (GET, PUT, LIST) с breakdown по типу.
- **Average object size** — выявление множества маленьких файлов (inefficient).

### 5.3 Lifecycle policies для cost optimization

```json
{
  "Rules": [
    {
      "ID": "OptimizeCosts",
      "Status": "Enabled",
      "Filter": {"Prefix": "logs/"},
      "Transitions": [
        {"Days": 30, "StorageClass": "STANDARD_IA"},
        {"Days": 90, "StorageClass": "GLACIER_IR"},
        {"Days": 365, "StorageClass": "DEEP_ARCHIVE"}
      ],
      "NoncurrentVersionTransitions": [
        {"Days": 7, "StorageClass": "STANDARD_IA"},
        {"Days": 30, "StorageClass": "GLACIER_IR"}
      ],
      "NoncurrentVersionExpiration": {"NoncurrentDays": 90},
      "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}
    }
  ]
}
```

**Оценка экономии:**
- Standard → Standard-IA: экономия 40–50% на хранении.
- Standard → Intelligent-Tiering: экономия 20–40% для непредсказуемых паттернов.
- Standard → Glacier Deep Archive: экономия 90–95% для архивных данных.

### 5.4 Intelligent-Tiering

Автоматическая оптимизация Storage Class на основе паттернов доступа:

```bash
# Копирование объектов в Intelligent-Tiering
aws s3 cp s3://my-app-prod-assets/data/ s3://my-app-prod-assets/archived/ \
  --recursive \
  --storage-class INTELLIGENT_TIERING
```

**Когда использовать:**
- Данные с непредсказуемым паттерном доступа.
- Не хотите управлять lifecycle policies вручную.
- Готовы платить за monitoring fee ($0.0025 за 1 000 объектов/месяц).

---

## 6. Operational monitoring

### 6.1 CloudWatch Logs Insights запросы

```sql
-- Топ-10 bucket'ов по размеру
| filter @message like /BucketSizeBytes/
| stats avg(@value) as avg_size by bin(1d), @resource.bucketName
| sort avg_size desc
| limit 10

-- Ошибки по типам
| filter @message like /4xxErrors/ or @message like /5xxErrors/
| stats sum(@value) as errors by bin(5m), @resource.bucketName, @metricName
| sort errors desc

-- Запросы по типам операций
| filter @message like /GetRequests/ or @message like /PutRequests/
| stats sum(@value) as requests by bin(1h), @metricName
| render timechart
```

### 6.2 S3 Inventory анализ

```python
import pandas as pd

# Чтение S3 Inventory CSV
df = pd.read_csv('s3-inventory.csv')

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

### 6.3 AWS Config compliance

```bash
# Проверка compliance всех S3 bucket'ов
aws configservice get-compliance-details-by-config-rule \
  --config-rule-name s3-bucket-public-read-prohibited

# Проверка encryption compliance
aws configservice get-compliance-details-by-config-rule \
  --config-rule-name s3-bucket-server-side-encryption-enabled

# Проверка versioning compliance
aws configservice get-compliance-details-by-config-rule \
  --config-rule-name s3-bucket-versioning-enabled
```

---

## 7. Troubleshooting мониторинга

### 7.1 Метрики не отображаются

**Причины:**
- Bucket новый (< 48 часов для basic metrics).
- Bucket пустой (BucketSizeBytes = 0, NumberOfObjects = 0).
- Region mismatch при запросе метрик.

### 7.2 High latency

**Диагностика:**
```bash
# Проверка региона bucket
aws s3api get-bucket-location --bucket my-app-prod-assets

# Проверка network connectivity
mtr --tcp --port 443 s3.eu-central-1.amazonaws.com

# Проверка размера объекта (большие объекты = higher latency)
aws s3api head-object --bucket my-app-prod-assets --key large-file.tar.gz
```

**Solutions:**
- Используйте Transfer Acceleration для cross-region доступа.
- Используйте CloudFront для read-heavy workloads.
- Увеличьте parallel requests для multipart upload/download.

### 7.3 Unexpected costs

**Диагностика:**
```bash
# Анализ затрат по bucket'ам
aws ce get-cost-and-usage \
  --time-period Start=2024-01-01,End=2024-01-31 \
  --granularity MONTHLY \
  --metrics "BlendedCost" \
  --group-by Type=DIMENSION,Key=RESOURCE \
  --filter '{
    "Dimensions": {
      "Key": "SERVICE",
      "Values": ["Amazon Simple Storage Service"]
    }
  }'

# Поиск больших объектов
aws s3api list-objects-v2 \
  --bucket my-app-prod-assets \
  --query 'Contents[?Size>`1073741824`].[Key, Size]' \
  --output table

# Поиск объектов без lifecycle
aws s3api get-bucket-lifecycle-configuration --bucket my-app-prod-assets
```

**Common cost drivers:**
1. **Cross-region replication traffic** — $0.02/ГБ входящего, $0.09/ГБ исходящего.
2. **Glacier retrieval requests** — $0.01 за 1 000 запросов.
3. **LIST requests на bucket с миллионами объектов** — $0.005 за 1 000 запросов.
4. **S3 Select запросы** — $0.001 за 1 000 запросов + $0.0004 за 1 000 отсканированных строк.
5. **Transfer Acceleration** — $0.04–$0.08 за ГБ.

---

## 8. Best Practices (Production Checklist)

### Monitoring
- [ ] Включены **detailed metrics** для критичных bucket'ов.
- [ ] Настроены **CloudWatch Alarms** на 5xxErrors, 4xxErrors, high latency.
- [ ] Включён **S3 Storage Lens** для organisation-wide visibility.
- [ ] Настроен **S3 Inventory** для compliance аудита.
- [ ] Используется **CloudTrail data events** для детального аудита.
- [ ] Включён **S3 Access Logging**.

### Cost Optimization
- [ ] Настроены **Lifecycle policies** для автоматической миграции в IA/Glacier.
- [ ] Используется **Intelligent-Tiering** для непредсказуемых паттернов.
- [ ] Включён **Storage Lens** для cost insights.
- [ ] Регулярно анализируются **Cost Explorer** отчёты.
- [ ] Настроены alerts на неожиданный рост затрат.
- [ ] Используется **Bucket Key Enabled** для SSE-KMS (снижает стоимость на 90–99%).

### Reliability
- [ ] Настроены **alarms на 5xxErrors** (инцидент при любом значении > 0).
- [ ] Настроены **alarms на replication latency** для CRR.
- [ ] Мониторится **размер bucket** и **количество объектов** (рост без причин = инцидент).
- [ ] Регулярно проверяется **S3 Inventory** на orphaned объекты.

---

## 9. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
- [S3: безопасность, шифрование и compliance](./security.md)
- [Ansible и S3: интеграция, автоматизация и эксплуатация](./ansible-integration.md)
- [Обзор систем хранения данных (СХД)](../data_storage_overview.md)