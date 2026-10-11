# S3: disaster recovery runbook

**Актуально для:** Ceph RGW (Squid 19.x / Tentacle 20.x / Umbrella 21.x)

---

## 1. Определения

**Runbook** — пошаговая инструкция для SRE/SysAdmin на случай инцидента с RGW. Содержит: симптомы проблемы, диагностические команды, возможные причины, пошаговые решения, escalation path.

**Disaster Recovery (DR)** — комплекс мер по восстановлению работы RGW после катастрофического сбоя: accidental deletion, mass overwrite, compromised credentials, infrastructure failure.

**RPO (Recovery Point Objective)** — максимально допустимый период потери данных. Для RGW: зависит от replication frequency и versioning.

**RTO (Recovery Time Objective)** — максимально допустимый простой. Для RGW: зависит от способа восстановления (version restore vs multisite failover).

**Accidental deletion** — массовое удаление объектов/версий по ошибке. Основная причина потери данных в RGW.

**Compromised credentials** — злоумышленник получил доступ к access key/secret key. Требует немедленного отзыва и ротации.

**Public bucket incident** — bucket стал публичным из-за ошибки в policy. Требует немедленного отзыва публичного доступа.

**Mass overwrite** — злоумышленник или баг перезаписал множество объектов. Восстановление через versioning или multisite replication.

**Multisite** — конфигурация Ceph RGW с несколькими зонами (zones) в одной zonegroup, обеспечивающая синхронную или асинхронную репликацию между сайтами.

**Zone** — логический эквивалент сайта в multisite-конфигурации RGW. Каждая zone имеет свой endpoint и pool.

**Object Lock** — механизм WORM (Write Once Read Many), защищающий объекты от удаления/перезаписи в течение заданного периода.

---

## 2. Базовые концепции

### 2.1 Уровни защиты RGW

| Уровень | Защита | Включение |
|---------|--------|-----------|
| **Prevention** | Block Public Access, Bucket Policy, Object Lock, Versioning | Всегда |
| **Detection** | Access Logging, RGW audit logs, Inventory | Всегда |
| **Recovery** | Multisite Replication, Backup, Versioning | Для критичных данных |

### 2.2 Сценарии инцидентов

| Инцидент | RPO | RTO | Метод восстановления |
|----------|-----|-----|---------------------|
| Accidental deletion | 0 (versioning) | 1–24 часа | Version restore, multisite failover |
| Compromised credentials | 0 (versioning) | 1–4 часа | Rotate keys, restore from multisite |
| Public bucket | 0 | 5–30 минут | Block Public Access, audit logs |
| Mass overwrite | 0 (versioning) | 1–24 часа | Version restore, multisite failover |
| Infrastructure failure | Часы | Часы | DR cluster, backup restore |
| Ransomware (encryption in-place) | Часы | Часы–дни | Object Lock, air-gap backup |

### 2.3 Архитектура DR

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DR Architecture                              │
│                                                                     │
│  ┌─────────────────┐         ┌─────────────────┐                   │
│  │   Primary Site  │         │   DR Site       │                   │
│  │   (us-east-1)   │◄───────►│   (us-west-1)   │                   │
│  │                 │  sync   │                 │                   │
│  │  RGW Master Zone│  status │  RGW Replica    │                   │
│  │  OSDs: 12       │         │  OSDs: 12       │                   │
│  └────────┬────────┘         └────────┬────────┘                   │
│           │                          │                              │
│           ▼                          ▼                              │
│  ┌─────────────────┐         ┌─────────────────┐                   │
│  │   Backup        │         │   Object Lock   │                   │
│  │   (Borg/Restic) │         │   (30d retention)│                   │
│  │   Air-gap       │         │                 │                   │
│  └─────────────────┘         └─────────────────┘                   │
│                                                                     │
│  Components:                                                        │
│  - radosgw-admin: управление зонами, пользователями, buckets        │
│  - Ceph MDS/MON: метаданные, мониторинг кластера                    │
│  - RGW daemons: обработка S3 запросов                               │
│  - Prometheus + RGW exporter: метрики, алерты                       │
│  - Loki/Elasticsearch: хранение access logs                         │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.4 Типы репликации

| Тип | Настройка | RPO | Использование |
|-----|-----------|-----|---------------|
| **Multisite sync** | `radosgw-admin zone create` | Минуты | Активный-Active DR |
| **Versioning** | `put-bucket-versioning` | 0 | Защита от deletion/overwrite |
| **Object Lock** | `put-object-lock-configuration` | 0 | Ransomware, compliance |
| **aws s3 sync** | AWS CLI | Зависит от schedule | Ручное/скриптовое DR |

---

## 3. Предварительные требования

### 3.1 Инфраструктура

- **Два Ceph кластера** — primary и DR site, каждый с RGW gateway
- **Сеть между сайтами** — VPN, MPLS или dedicated link с latency < 50ms для multisite
- **radosgw-admin** — доступен на Management node с правами на оба кластера
- **AWS CLI** — настроен с endpoint'ами обоих RGW
- **Python 3.8+** — с `boto3`, `pandas` для скриптов восстановления
- **Prometheus + RGW exporter** — для мониторинга обоих сайтов
- **Loki/Elasticsearch** — для хранения access logs и audit
- **Backup storage** — Borg/Restic репозиторий или внешний S3-совместимый target

### 3.2 Разрешения

Для выполнения runbook'ов требуются:
- `s3:GetBucketVersioning`, `s3:ListBucketVersions` — проверка и восстановление версий
- `s3:GetBucketPolicy`, `s3:PutBucketPolicy` — аудит и блокировка bucket
- `s3:GetBucketAcl`, `s3:PutBucketAcl` — проверка и изменение ACL
- `radosgw-admin` execution — управление зонами, пользователями, buckets
- Ceph CLI: `ceph`, `radosgw-admin` — диагностика кластера

### 3.3 Конфигурация AWS CLI

```bash
# ~/.aws/config
[default]
region = us-east-1
output = json

# Profile для primary site
[profile primary]
region = us-east-1
output = json

# Profile для DR site
[profile dr]
region = us-west-1
output = json

# Проверка подключения
aws s3 ls --endpoint-url http://rgw-master:7480 --profile primary
aws s3 ls --endpoint-url http://rgw-replica:7480 --profile dr
```

---

## 4. Runbook'и по сценариям

### 4.1 Сценарий 1: Accidental deletion

**Симптомы:**
- Объекты исчезли из bucket'а.
- `ListObjectsV2` возвращает меньше объектов, чем ожидается.
- Access Logs показывают `DELETE` запросы от unexpected principal.

**Диагностика:**
```bash
# 1. Проверка версий объекта
aws s3api list-object-versions \
  --bucket my-app-prod-assets \
  --prefix releases/ \
  --query 'Versions[*].[Key, VersionId, LastModified, IsLatest]' \
  --output table \
  --endpoint-url http://rgw:7480

# 2. Проверка delete markers
aws s3api list-object-versions \
  --bucket my-app-prod-assets \
  --prefix releases/ \
  --query 'DeleteMarkers[*].[Key, VersionId, LastModified]' \
  --output table \
  --endpoint-url http://rgw:7480

# 3. Проверка Access Logs
grep "DELETE.*my-app-prod-assets" /var/log/ceph/radosgw.*.log | tail -50

# 4. Проверка RGW audit log
radosgw-admin log list --bucket my-app-prod-assets | grep DELETE
```

**Восстановление:**
```bash
# 1. Восстановление предыдущей версии (если versioning включён)
aws s3api copy-object \
  --bucket my-app-prod-assets \
  --key releases/app.tar.gz \
  --copy-source "my-app-prod-assets/releases/app.tar.gz?versionId=3lLf9..." \
  --metadata-directive COPY \
  --endpoint-url http://rgw:7480

# 2. Массовое восстановление через Python/pandas скрипт
python restore_versions.py --bucket my-app-prod-assets --prefix releases/

# 3. Если versioning не включён — проверка multisite
radosgw-admin sync status
# Восстановление из DR bucket
```

**Cleanup:**
- Удалите delete markers после восстановления: `aws s3api delete-object --bucket ... --key ... --version-id <delete-marker-id>`
- Проверьте, что bucket policy не разрешает массовое удаление

**Prevention:**
- Включите Versioning на всех production bucket'ах.
- Настройте Object Lock (Compliance mode) для критичных данных.
- Настройте lifecycle policy для удаления delete markers только после N дней.

### 4.2 Сценарий 2: Compromised credentials

**Симптомы:**
- Access Logs показывают необычные `GET`/`PUT` запросы из unexpected IP.
- Обнаружена утечка credentials.
- Резкий рост размера bucket'а или запросов.

**Немедленные действия:**
```bash
# 1. Отозвать compromised credentials
radosgw-admin user rm --uid="compromised-user" --purge-data

# 2. Проверка последних операций
grep "compromised-user\|suspicious-ip" /var/log/ceph/radosgw.*.log | awk '{print $1, $4}' | sort | uniq -c | sort -rn | head -20

# 3. Создание новых credentials
radosgw-admin user create --uid="app-user" --display-name="Application User"
```

**Восстановление:**
```bash
# 1. Создание новых credentials
radosgw-admin user create --uid="app-user" --display-name="Application User"

# 2. Проверка bucket'ов на изменения
for bucket in $(aws s3 ls --endpoint-url http://rgw:7480 | awk '{print $3}'); do
  echo "Auditing: $bucket"
  aws s3api get-bucket-policy --bucket $bucket --endpoint-url http://rgw:7480
  aws s3api get-bucket-versioning --bucket $bucket --endpoint-url http://rgw:7480
done

# 3. Восстановление из multisite replication
radosgw-admin sync status
```

**Cleanup:**
- Отзовите все sessions/tokens для compromised user
- Обновите IAM policies, если credentials были использованы для доступа к внешним сервисам
- Проверьте bucket policies на наличие изменений

**Prevention:**
- Используйте краткоживущие credentials (STS, Vault, OIDC) вместо статических ключей.
- Включите access logging на всех bucket'ах.
- Настройте OPA policies для continuous compliance monitoring.
- Block Public Access на уровне account и bucket.

### 4.3 Сценарий 3: Public bucket incident

**Симптомы:**
- Access logs показывают GET запросы из internet.
- Обнаружена утечка данных через внешние источники.

**Немедленные действия:**
```bash
# 1. Блокировка публичного доступа
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

# 2. Удаление публичного bucket policy
aws s3api delete-bucket-policy --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# 3. Проверка ACL
aws s3api get-bucket-acl --bucket my-app-prod-assets --endpoint-url http://rgw:7480

# 4. Проверка Access Logs
ls my-audit-logs/s3-logs/my-app-prod-assets/ --recursive | head -20
```

**Расследование:**
```bash
# 1. Кто скачал данные?
grep "GET.*my-app-prod-assets" /var/log/ceph/radosgw.*.log | \
  awk '{print $1, $4}' | sort | uniq -c | sort -rn | head -20

# 2. Какие объекты были доступны?
grep "GET.*my-app-prod-assets" /var/log/ceph/radosgw.*.log | \
  awk '{print $7}' | sort | uniq -c | sort -rn | head -50

# 3. В какой период bucket был публичным?
grep "my-app-prod-assets" /var/log/ceph/radosgw.*.log | head -5
grep "my-app-prod-assets" /var/log/ceph/radosgw.*.log | tail -5
```

**Cleanup:**
- Удалите публичный ACL: `aws s3api put-bucket-acl --bucket ... --acl private`
- Включите Bucket Owner Enforced: `put-bucket-ownership-controls --object-ownership BucketOwnerEnforced`
- Проверьте CloudTrail/RGW audit на предмет других публичных bucket'ов

**Prevention:**
- Account-level Block Public Access — всегда включён.
- OPA policies для continuous compliance monitoring.
- CI/CD проверка bucket policy на public access.

### 4.4 Сценарий 4: Mass overwrite

**Симптомы:**
- Объекты имеют неожиданный размер или содержимое.
- Access Logs показывают массовые PUT запросы.
- Приложение возвращает ошибки из-за неожиданного содержимого объектов.

**Диагностика:**
```bash
# 1. Проверка версий
aws s3api list-object-versions \
  --bucket my-app-prod-assets \
  --prefix data/ \
  --query 'Versions[*].[Key, VersionId, Size, LastModified]' \
  --output table \
  --endpoint-url http://rgw:7480

# 2. Определение момента overwrite
aws s3api list-object-versions \
  --bucket my-app-prod-assets \
  --prefix data/ \
  --query 'Versions[?IsLatest==`false`].[Key, VersionId, LastModified]' \
  --output table \
  --endpoint-url http://rgw:7480 | head -20

# 3. Access Logs: кто перезаписал?
grep "PUT.*my-app-prod-assets" /var/log/ceph/radosgw.*.log | \
  awk '{print $4, $7}' | sort | uniq -c | sort -rn | head -20
```

**Восстановление:**
```bash
# 1. Rollback через versioning (если включён)
aws s3api copy-object \
  --bucket my-app-prod-assets \
  --key data/file.json \
  --copy-source "my-app-prod-assets/data/file.json?versionId=<good-version-id>" \
  --metadata-directive COPY \
  --endpoint-url http://rgw:7480

# 2. Массовый rollback через Python/pandas скрипт
python restore_versions.py --bucket my-app-prod-assets --prefix data/

# 3. Если versioning не включён — проверка multisite
radosgw-admin sync status
# Восстановление из DR bucket
```

**Cleanup:**
- Удалите overwritten версии: `aws s3api delete-object --bucket ... --key ... --version-id <bad-version-id>`
- Проверьте bucket policy на предмет изменений

**Prevention:**
- Включите Versioning и Object Lock на всех production bucket'ах.
- Используйте MFA Delete для критичных bucket'ов.
- Настройте OPA policies, запрещающие массовые overwrite.

### 4.5 Сценарий 5: Infrastructure failure (self-hosted)

**Симптомы:**
- Ceph RGW: OSD down, PG degraded.
- RGW: Node unreachable, 503 errors.

**Диагностика:**
```bash
# Ceph status
ceph status
ceph osd tree
radosgw-admin bucket stats --bucket my-bucket

# Проверка RGW daemons
ceph orch ps --daemon-type rgw

# Проверка multisite sync
radosgw-admin sync status

# Проверка network connectivity
nc -zv rgw-master 7480
nc -zv rgw-replica 7480
```

**Восстановление:**
```bash
# Ceph RGW: восстановление OSD
ceph osd out <osd-id>
ceph osd crush remove <osd-id>
# Замена диска, добавление нового OSD

# Перезапуск RGW daemon
ceph orch restart rgw.myrgw

# Проверка sync status (multisite)
radosgw-admin sync status

# Если primary site недоступен долго — включите DR site
# Обновите DNS/load balancer для указания на DR RGW endpoint
```

**Cleanup:**
- После восстановления primary site выполните resync: `radosgw-admin sync run --yes-i-really-really-mean-it`
- Проверьте consistency данных между primary и DR

**Prevention:**
- Настройте multisite replication для всех критичных bucket'ов.
- Используйте load balancer с health checks для RGW endpoints.
- Мониторьте OSD health, PG states, RGW daemon status.

### 4.6 Сценарий 6: Ransomware (encryption in-place)

**Симптомы:**
- Объекты имеют неожиданное расширение или зашифрованы.
- На bucket'ах появились новые объекты с extension `.locked` или `README.txt`.
- Access Logs показывают массовые PUT запросы из unexpected IP.

**Немедленные действия:**
```bash
# 1. Изолируйте infected bucket
aws s3api put-bucket-policy \
  --bucket infected-bucket \
  --policy '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": ["arn:aws:s3:::infected-bucket", "arn:aws:s3:::infected-bucket/*"]
    }]
  }' \
  --endpoint-url http://rgw:7480

# 2. Отзовите все credentials, имевшие доступ
radosgw-admin user rm --uid="compromised-user" --purge-data

# 3. Проверка Object Lock
aws s3api get-object-lock-configuration \
  --bucket infected-bucket \
  --endpoint-url http://rgw:7480
```

**Восстановление:**
```bash
# 1. Если Object Lock включён — объекты защищены, восстановите предыдущие версии
aws s3api list-object-versions \
  --bucket infected-bucket \
  --query 'Versions[*].[Key, VersionId, LastModified, Size]' \
  --output table \
  --endpoint-url http://rgw:7480 | \
  awk '$3 > "2026-09-28"' | \
  sort -k3

# 2. Если multisite настроен — восстановите из DR bucket (до заражения)
radosgw-admin sync status

# 3. Если нет защиты — восстановите из Borg/Restic backup
borg list /path/to/repo
borg extract /path/to/repo::archive-name
```

**Cleanup:**
- Удалите заражённые объекты
- Проверьте все bucket'ы на предмет ransomware artifacts
- Обновите все credentials и policies
- Проведите forensic анализ логов

**Prevention:**
- Object Lock в Compliance mode для критичных данных.
- Air-gap backup (Borg/Restic на отдельный носитель).
- Network segmentation: RGW не доступен из internet напрямую.

---

## 5. Preventive controls

### 5.1 Versioning + Object Lock

```bash
# Включение versioning
aws s3api put-bucket-versioning \
  --bucket my-app-prod-assets \
  --versioning-configuration Status=Enabled \
  --endpoint-url http://rgw:7480

# Включение Object Lock (Compliance mode, 30 дней)
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

### 5.2 Multisite Replication (Ceph RGW)

```bash
# Настройка master-зоны
radosgw-admin zone create --rgw-zone=us-east-1 --rgw-zonegroup=us \
  --endpoints=http://rgw-master:7480 --master
radosgw-admin zonegroup modify --rgw-zonegroup=us --master
radosgw-admin period update --commit

# Настройка replica-зоны (на втором кластере)
radosgw-admin zone create --rgw-zone=us-west-1 --rgw-zonegroup=us \
  --endpoints=http://rgw-replica:7480

# Синхронизация
radosgw-admin sync status
```

### 5.3 Backup strategy (3-2-1-1-0)

| Копия | Расположение | Тип |
|-------|-------------|-----|
| 1 | Production bucket (versioning + Object Lock) | Live |
| 2 | Cross-site bucket (multisite replication) | Replicated |
| 3 | External backup (Borg/Restic to RGW) | Archived |

### 5.4 Network hardening

- RGW endpoint доступен только через internal network/VPN.
- Firewall rules: разрешите только 7480 (RGW) и 9283 (metrics) из trusted subnet.
- Используйте TLS для всех RGW endpoint'ов.
- Отдельный VPC/subnet для RGW daemons.

### 5.5 Access controls

- Block Public Access на account и bucket уровне.
- Bucket Owner Enforced для всех новых bucket'ов.
- Минимальные permissions для RGW пользователей (least privilege).
- Краткоживущие credentials (STS, Vault) вместо статических ключей.

---

## 6. Monitoring и alerting

### 6.1 Prometheus Alerts

```yaml
# 1. Mass deletion detection
- alert: RGWMassDeletion
  expr: sum(rate(rgw_delete_requests_total[5m])) > 100
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Mass deletion detected on RGW"

# 2. 5xxErrors (service degradation)
- alert: RGWHigh5xxErrors
  expr: sum(rate(rgw_5xx_errors[5m])) > 5
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "High 5xx errors on RGW"

# 3. Public bucket detection
- alert: RGWPublicBucket
  expr: rgw_public_buckets > 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Public bucket detected"

# 4. Multisite sync failure
- alert: RGWMultisiteSyncFailed
  expr: rgw_sync_status{status="failed"} > 0
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "Multisite sync failed"

# 5. RGW daemon down
- alert: RGWDemonDown
  expr: up{job="rgw"} == 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "RGW daemon is down"
```

### 6.2 Access Logs анализ

```bash
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

# Поиск публичного доступа (GET без authentication)
find $LOG_DIR -name "radosgw.*" -exec grep "GET.*200" {} \; | \
  awk '$5 == "-" {print $4}' | \
  sort | uniq -c | \
  sort -rn | head -20
```

### 6.3 Grafana dashboard

- **Ceph RGW Dashboard** — метрики RGW: запросы, ошибки, latency, размер bucket'ов.
- **Ceph Cluster Dashboard** — общие метрики кластера: OSD, PG, PgPool.
- **Multisite Status** — кастомный dashboard для отслеживания sync status между зонами.

---

## 7. Валидация

### 7.1 Drill-test checklist

```markdown
- [ ] Version restore: восстановите произвольный объект из versioned bucket'а.
- [ ] Multisite failover: убедитесь, что DR bucket содержит все объекты.
- [ ] Object Lock: убедитесь, что locked объекты не могут быть удалены.
- [ ] Backup restore: восстановите данные из Borg/Restic backup в изолированную среду.
- [ ] Access Logs: убедитесь, что логи доступны и содержат все операции.
- [ ] Alarm testing: проверьте, что Prometheus alerts срабатывают при имитации инцидента.
- [ ] Credential rotation: проверьте, что отозванный user не имеет доступа.
- [ ] Network failover: проверьте переключение на DR endpoint при недоступности primary.
```

### 7.2 Проверка multisite sync

```bash
# Проверка sync status
radosgw-admin sync status

# Ожидаемый output:
# realm 9b14...69a7 (rados)
# period 3e5c...8b21 (rados)
# master_zone 1 (mutable)
# zonegroup us (mutable)
# zone us-east-1 (mutable)
# zone us-west-1 (mutable)
# sync status: syncing
# data sync: 100% complete

# Проверка конкретного bucket
aws s3api list-objects-v2 \
  --bucket my-app-prod-assets \
  --endpoint-url http://rgw-replica:7480 \
  --profile dr
```

### 7.3 Проверка versioning и Object Lock

```bash
# Проверка versioning
aws s3api get-bucket-versioning \
  --bucket my-app-prod-assets \
  --endpoint-url http://rgw:7480

# Ожидаемый output: Status: Enabled

# Проверка Object Lock
aws s3api get-object-lock-configuration \
  --bucket my-app-prod-assets \
  --endpoint-url http://rgw:7480

# Ожидаемый output: ObjectLockEnabled: Enabled, DefaultRetention: COMPLIANCE 30 days
```

### 7.4 Проверка Prometheus alerts

```bash
# Проверка доступности metrics endpoint
curl -s http://rgw:9283/metrics | grep rgw_requests_total

# Проверка алертов
curl -s http://localhost:9090/api/v1/alerts | jq '.data.alerts[] | select(.labels.alertname == "RGWMassDeletion")'
```

### 7.5 Проверка backup integrity

```bash
# Borg backup
borg list /path/to/repo
borg extract --dry-run /path/to/repo::latest

# Restic backup
restic check /path/to/repo
restic snapshots /path/to/repo
```

---

## 8. Граничные случаи и ограничения

### 8.1 Policy propagation delay

**Проблема:** OPA policy применена, но bucket policy ещё не обновился в RGW.

**Причина:** RGW кэширует bucket policies. Propagation может занимать от нескольких секунд до 1 минуты.

**Решение:**
```bash
# Проверка актуального policy
aws s3api get-bucket-policy --bucket my-bucket --endpoint-url http://rgw:7480

# Принудительное обновление кэша (если поддерживается RGW)
radosgw-admin cache flush --bucket my-bucket
```

### 8.2 Multisite split-brain

**Проблема:** Оба сайта одновременно стали primary, данные расходятся.

**Причина:** Сетевое разделение (network partition) между сайтами.

**Решение:**
- Определите canonical source (последний обновлённый).
- Остановите один из сайтов: `radosgw-admin period update --commit --force`
- Принудительно sync: `radosgw-admin sync run --yes-i-really-really-mean-it`
- Проверьте consistency: сравните количество объектов на primary и DR

### 8.3 Versioning disabled for cost optimization

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

### 8.4 ACL vs Bucket Policy precedence

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

### 8.5 Log rotation и retention

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

### 8.6 Performance impact logging

**Проблема:** Access logging создаёт дополнительную нагрузку на RGW.

**Решение:**
- Используйте отдельный bucket для logs на другом физическом storage pool
- Настройте RGW для асинхронной записи логов
- Мониторьте latency при включённом логировании

---

## 9. Troubleshooting

| Проблема | Причина | Диагностика | Решение |
|----------|---------|-------------|---------|
| Accidental deletion | Отсутствие versioning | `list-object-versions` | Включите versioning, восстановите из backup |
| Compromised credentials | Утечка ключа | Access Logs, audit log | Отзовите ключ, создайте новый, проверьте изменения |
| Public bucket incident | Ошибка в policy | `get-bucket-acl`, `get-bucket-policy` | Удалите public ACL, примените Deny policy |
| Mass overwrite | Злоумышленник/баг | `list-object-versions`, Access Logs | Rollback через versioning или multisite |
| Infrastructure failure | OSD down, PG degraded | `ceph status`, `ceph osd tree` | Замена OSD, перезапуск RGW daemon |
| Ransomware | Compromised credentials | Object Lock, versioning | Object Lock, air-gap backup restore |
| Multisite sync failed | Network partition | `radosgw-admin sync status` | Проверка connectivity, принудительный sync |
| OPA не детектирует public bucket | Bucket только что создан | Проверка OPA eval | Подождите propagation policies или rerun |
| Metrics не отображаются | RGW exporter не запущен | `curl http://rgw:9283/metrics` | Запустите RGW daemon с включённым exporter |
| Access logs не генерируются | Logging не включён | `get-bucket-logging` | Включите logging через bucket policy |

---

## 10. Best Practices

1. **Versioning + Object Lock** — базовый уровень защиты для всех production bucket'ов.
2. **Multisite Replication** — для критичных данных. RPO = время синхронизации между зонами.
3. **Block Public Access** — на уровне account и bucket. Никогда не отключайте.
4. **Access Logging + RGW audit** — включите на всех bucket'ах для audit.
5. **Regular drill tests** — раз в квартал тестируйте восстановление.
6. **Automated alerts** — на public bucket, массовое удаление, 5xxErrors, multisite sync failure.
7. **3-2-1-1-0 backup strategy** — 3 копии, 2 носителя, 1 off-site, 1 immutable, 0 ошибок.
8. **Use краткоживущие credentials** — минимизируйте поверхность атаки.
9. **Document runbook'и** — каждый сценарий должен быть документирован с контактами escalation.
10. **Post-incident review** — после каждого инцидента обновляйте runbook и preventive controls.
11. **Network hardening** — RGW endpoint только через internal network, TLS everywhere.
12. **Centralize logs** — экспортируйте access logs в Loki/Elasticsearch для долгосрочного хранения.
13. **Enable versioning** на всех production bucket'ах — требуется для audit trail и disaster recovery.
14. **Encrypt at rest** — используйте SSE-KMS для всех sensitive данных.
15. **Monitor metrics** — настройте алерты на public buckets, missing encryption, sync failures.

---

## 11. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: безопасность, шифрование и compliance](./security.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [S3: защита от случайного удаления в Ceph RGW](./mfa-delete.md)
- [S3: compliance-мониторинг и анализ доступа](./access-analyzer.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
