# S3: мониторинг, алерты и cost optimization

**Актуально для:** Ceph RGW (Squid 19.x / Tentacle 20.x / Umbrella 21.x)

---

## 1. Определения

**Prometheus** — система мониторинга и алертинга с открытым исходным кодом. Собирает метрики по HTTP и хранит их в time-series базе данных.

**Grafana** — платформа для визуализации метрик. Подключается к Prometheus и отображает дашборды в реальном времени.

**RGW metrics** — метрики, экспортируемые Ceph RGW через встроенный Prometheus exporter. Доступны по endpoint `/metrics` на порту 9283 (по умолчанию).

**RGW access logging** — механизм записи всех запросов к bucket в отдельный target bucket. Логи экспортируются в Loki/Elasticsearch для анализа.

**Inventory report** — отчёт о всех объектах в bucket (ключ, размер, Storage Class, статус шифрования, версия). Доступен в Ceph RGW через S3 Inventory API.

**Cost anomaly** — неожиданный рост затрат на хранилище. Обнаруживается через анализ метрик и алерты.

**Unused data** — объекты в S3, к которым нет доступа более N дней. Определяется через Inventory + Access Logs.

---

## 2. Архитектура и базовые концепции

### 2.1 Как работают метрики Ceph RGW в Prometheus

Ceph RGW экспортирует метрики через встроенный exporter:

1. **Сбор:** RGW агрегирует данные о запросах и размере bucket.
2. **Экспорт:** Метрики доступны по `http://<rgw-host>:9283/metrics`.
3. **Скрапинг:** Prometheus собирает метрики с заданным интервалом (по умолчанию 15 секунд).
4. **Retention:** Prometheus хранит данные в локальном TSDB (по умолчанию 15 дней, настраивается).

### 2.2 Основные метрики RGW

| Метрика | Описание | Тип |
|---------|----------|-----|
| `rgw_requests_total` | Общее количество запросов | Counter |
| `rgw_requests_bytes_sent` | Отправлено байт | Counter |
| `rgw_requests_bytes_received` | Получено байт | Counter |
| `rgw_5xx_errors` | Ошибки 5xx | Counter |
| `rgw_4xx_errors` | Ошибки 4xx | Counter |
| `rgw_bucket_size_bytes` | Размер bucket | Gauge |
| `rgw_bucket_objects` | Количество объектов | Gauge |
| `rgw_multipart_uploads` | Незавершённые multipart uploads | Gauge |

### 2.3 Ограничения модели метрик

- **Детализация:** Метрики доступны в реальном времени (задержка scrape interval).
- **Dimensions:** Метрики можно фильтровать по bucket, пользователю, операции.
- **Retention:** Зависит от конфигурации Prometheus (по умолчанию 15 дней).

---

## 3. Метрики и алерты

### 3.1 Prometheus метрики RGW

```promql
# Общее количество запросов за последний час
sum(rate(rgw_requests_total[1h]))

# Количество ошибок 5xx за последние 5 минут
sum(rate(rgw_5xx_errors[5m]))

# Размер bucket'а
rgw_bucket_size_bytes{bucket="my-app-prod-assets"}

# Количество объектов в bucket'е
rgw_bucket_objects{bucket="my-app-prod-assets"}
```

### 3.2 Алерты (Prometheus Alertmanager)

**Критические алерты:**

```yaml
# 1. 5xxErrors — сервисные ошибки
- alert: RGWHigh5xxErrors
  expr: sum(rate(rgw_5xx_errors[5m])) > 5
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "High 5xx errors on RGW"
    description: "{{ $value }} 5xx errors per second"

# 2. 4xxErrors — возможна атака или misconfiguration
- alert: RGWHigh4xxErrors
  expr: sum(rate(rgw_4xx_errors[5m])) > 100
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High 4xx errors on RGW"
    description: "{{ $value }} 4xx errors per second"

# 3. High latency
- alert: RGWHighLatency
  expr: histogram_quantile(0.95, sum(rate(rgw_request_latency_seconds_bucket[5m])) by (le)) > 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High RGW latency"
    description: "P95 latency is {{ $value }}s"
```

### 3.3 Валидация алертов

После создания alert проверьте его состояние:

```bash
# Проверка состояния alert
curl -s http://localhost:9090/api/v1/alerts | jq '.data.alerts[] | select(.labels.alertname == "RGWHigh5xxErrors")'
```

---

## 4. Access Logging и анализ

### 4.1 Включение access logging

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

### 4.2 RGW access log format

```
79a54df98bf4d2d9d6728775159241e1fad325b1 [06/Oct/2024:10:30:00 +0000] 192.0.2.3 arn:aws:iam::rgw:user/app-user REST.GET.OBJECT releases/app.tar.gz "PUT /releases/app.tar.gz" 200 - 1 0 "-" "" - kGkWULf+Vs5aS3RaJkFXKs3/2sM= SigV4 ECDHE-RSA-AES128-SHA TLSv1.2 - - - - - - -
```

### 4.3 Анализ access logs через Loki

```logql
# Поиск DELETE запросов
{job="rgw-access-logs"} |= "DELETE"

# Поиск 4xx/5xx ошибок
{job="rgw-access-logs"} |~ " 4\d\d " or |~ " 5\d\d "

# Агрегация по пользователям
sum by (remote_user) (count_over_time({job="rgw-access-logs"}[1h]))
```

---

## 5. Inventory и аудит

### 5.1 S3 Inventory в Ceph RGW

```bash
# Настройка Inventory configuration
aws s3api put-bucket-inventory-configuration \
  --bucket my-app-archives \
  --id my-inventory \
  --inventory-configuration '{
    "Destination": {
      "S3BucketDestination": {
        "Bucket": "arn:aws:s3:::my-inventory-bucket",
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

### 5.2 Анализ Inventory через Python/pandas

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

### 5.3 Direct SQL на inventory данных

Для анализа inventory данных можно импортировать CSV в PostgreSQL или ClickHouse и выполнять SQL-запросы:

```sql
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
```

---

## 6. Cost tracking

### 6.1 Метрики для cost optimization

| Метрика | Описание | Использование |
|---------|----------|---------------|
| `rgw_bucket_size_bytes` | Размер bucket по пулам | Capacity planning |
| `rgw_bucket_objects` | Количество объектов | Cost attribution |
| `rgw_requests_total` | Общее количество запросов | Cost attribution |
| `rgw_requests_bytes_sent` | Исходящий трафик | Cost attribution |

### 6.2 Кастомные скрипты для cost tracking

```python
import boto3
import pandas as pd
from datetime import datetime

s3 = boto3.client('s3',
    endpoint_url='http://rgw:7480',
    region_name='us-east-1'
)

# Сбор данных о bucket'ах
buckets = s3.list_buckets()['Buckets']
cost_data = []

for bucket in buckets:
    size = s3.get_bucket_size(Bucket=bucket['Name'])  # Если поддерживается RGW
    objects = s3.get_bucket_objects(Bucket=bucket['Name'])
    cost_data.append({
        'bucket': bucket['Name'],
        'size_gb': size / 1e9,
        'objects': objects,
        'date': datetime.now().isoformat()
    })

df = pd.DataFrame(cost_data)
df.to_csv('cost-report.csv', index=False)
```

### 6.3 Lifecycle policies для cost optimization

```json
{
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
}
```

**Оценка экономии:**
- Hot (SSD) → Warm (HDD): экономия 40–50% на хранении.
- Warm (HDD) → Cold (Archive): экономия 80–90% на хранении.

---

## 7. Operational monitoring

### 7.1 Grafana dashboards

Для Ceph RGW используйте готовые Grafana dashboards:
- **Ceph RGW Dashboard** — метрики RGW: запросы, ошибки, latency, размер bucket'ов.
- **Ceph Cluster Dashboard** — общие метрики кластера: OSD, PG, PgPool.

### 7.2 RGW log analysis

```bash
# Просмотр логов RGW
ceph orch logs --service=rgw.myrgw

# Или напрямую через journalctl
journalctl -u ceph-radosgw@rgw.myrgw -f
```

### 7.3 Access Logs анализ

```bash
# Ежедневный скрипт проверки аномалий
#!/bin/bash
# /usr/local/bin/check_rgw_anomalies.sh

LOG_DIR="/var/log/ceph"
TODAY=$(date +%Y-%m-%d)

# Поиск массового удаления (> 100 DELETE за час)
find $LOG_DIR -name "radosgw.*" -exec grep "DELETE" {} \; | \
  awk '{print $4, $7}' | \
  sort | uniq -c | \
  awk '$1 > 100 {print "ALERT: " $1 " deletions by " $2}'

# Поиск необычных IP
find $LOG_DIR -name "radosgw.*" -exec grep "GET" {} \; | \
  awk '{print $4}' | \
  sort | uniq -c | \
  sort -rn | head -10
```

---

## 8. Troubleshooting мониторинга

### 8.1 Метрики не отображаются

**Причины:**
- RGW exporter не запущен или недоступен.
- Prometheus не может подключиться к RGW exporter (firewall, сеть).
- Неправильный port (по умолчанию 9283).

**Решение:**
```bash
# Проверка доступности metrics endpoint
curl -s http://rgw:9283/metrics | head -20

# Проверка firewall
iptables -L -n | grep 9283
```

### 8.2 High latency

**Диагностика:**
```bash
# Проверка метрик RGW
curl -s http://rgw:9283/metrics | grep rgw_request_latency

# Проверка сети
mtr --tcp --port 7480 rgw.example.com

# Проверка OSD performance
ceph osd perf
```

**Solutions:**
- Увеличьте parallel requests для multipart upload/download.
- Используйте CDN для read-heavy workloads.
- Проверьте cluster_network на congestion.

### 8.3 Unexpected costs

**Диагностика:**
```bash
# Анализ размера bucket'ов
aws s3 ls s3://my-app-prod-assets/ --recursive --summarize --human-readable \
  --endpoint-url http://rgw:7480

# Поиск больших объектов
aws s3api list-objects-v2 \
  --bucket my-app-prod-assets \
  --query 'Contents[?Size>`1073741824`].[Key, Size]' \
  --output table \
  --endpoint-url http://rgw:7480
```

**Common cost drivers:**
1. **Большие объекты в SSD пуле** — мигрируйте в HDD/Archive.
2. **Маленькие файлы (< 1 MB)** — inefficient, рассмотрите consolidation.
3. **Незавершённые multipart uploads** — настройте lifecycle `AbortIncompleteMultipartUpload`.
4. **Высокий трафик** — используйте CDN для статических assets.

---

## 9. Best Practices (Production Checklist)

### Monitoring
- [ ] Включены **Prometheus RGW metrics** для всех RGW инстансов.
- [ ] Настроены **Grafana dashboards** для визуализации.
- [ ] Настроены **алерты** на 5xxErrors, 4xxErrors, high latency.
- [ ] Включён **Access Logging** на всех bucket'ах.
- [ ] Настроен **S3 Inventory** для compliance аудита.
- [ ] Используется **Loki/Elasticsearch** для анализа access logs.

### Cost Optimization
- [ ] Настроены **Lifecycle policies** для автоматической миграции между hot/warm/cold pools.
- [ ] Включён **versioning** для критичных bucket'ов.
- [ ] Регулярно анализируется **inventory** для обнаружения устаревших данных.
- [ ] Мониторинг запросов (LIST на миллионы объектов = дорого).

### Reliability
- [ ] Настроены **alerts на 5xxErrors** (инцидент при любом значении > 0).
- [ ] Мониторится **размер bucket** и **количество объектов** (рост без причин = инцидент).
- [ ] Регулярно проверяется **inventory** на orphaned объекты.

### Cleanup и откат
- [ ] Знаете, как отключить metrics: `ceph config set rgw rgw_enable_metrics false`
- [ ] Знаете, как отключить access logging: удалите BucketLoggingStatus через API
- [ ] Знаете, как отключить versioning: `aws s3api put-bucket-versioning --bucket <name> --versioning-configuration Status=Suspended`
- [ ] Знаете, как удалить lifecycle: `aws s3api delete-bucket-lifecycle --bucket <name>`

---

## 10. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: безопасность, шифрование и compliance](./security.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
- [Ansible и S3: интеграция, автоматизация и эксплуатация](./ansible-integration.md)
