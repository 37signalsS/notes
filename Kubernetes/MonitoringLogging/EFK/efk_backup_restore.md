# Бэкап и восстановление Elasticsearch в Kubernetes

## Определения

**Snapshot** — снимок состояния Elasticsearch (кластера, индексов или конкретных shard'ов), сохраняемый в хранилище (repository). Снапшоты используются для бэкапа и восстановления данных.

**Snapshot Repository** — хранилище, куда сохраняются снапшоты. Поддерживает несколько типов: filesystem (NFS, local), S3-compatible (MinIO, AWS S3), Google Cloud Storage, Azure Blob Storage.

**ILM (Index Lifecycle Management)** — механизм управления жизненным циклом индексов, включая автоматическое создание снапшотов через политики.

**Restore** — процесс восстановления данных из снапшота. Может восстанавливать кластер, отдельные индексы или конкретные shard'ы.

**Incremental Snapshot** — снапшот, содержащий только данные, изменившиеся с момента предыдущего снапшота. Экономит место в хранилище.

**Snapshot Lifecycle Management (SLM)** — политика автоматического создания снапшотов по расписанию (аналог cron для бэкапов).

**Retention Policy** — политика удаления старых снапшотов для оптимизации использования хранилища.

## Теоретический блок

### Архитектура бэкапа Elasticsearch

```
┌─────────────────────────────────────────────────────────────┐
│                   Бэкап Elasticsearch                        │
├─────────────────────────────────────────────────────────────┤
│  Elasticsearch Cluster                                      │
│  └─ Index Data (segments, translog)                         │
│       │                                                     │
│       ▼                                                     │
│  Snapshot Process (снимает данные)                           │
│       │                                                     │
│       ▼                                                     │
│  Snapshot Repository (хранилище снапшотов)                  │
│  └─ Location: /mnt/nfs/backups/elasticsearch                │
│  └─ Type: fs (filesystem) или s3 (облако)                   │
│  └─ Retention: хранить 7 дней, макс. 50 снапшотов           │
└─────────────────────────────────────────────────────────────┘
```

### Типы снапшотов

| Тип | Описание | Использование |
| :--- | :--- | :--- |
| **Full Snapshot** | Полный снимок всех данных | Начальный бэкап, перед миграцией |
| **Incremental Snapshot** | Только измененные данные | Регулярные бэкапы (ежедневные) |
| **Partial Snapshot** | Не все shard'ы (при ошибках) | Экстренные бэкапи |
| **Clone Snapshot** | Копия существующего снапшота | Тестирование восстановления |

### Типы хранилищ

| Тип | Преимущества | Недостатки |
| :--- | :--- | :--- |
| **Filesystem (NFS)** | Простота, скорость | Зависимость от NFS-сервера |
| **S3-compatible** | Масштабируемость, надежность | Стоимость, задержка сети |
| **Google Cloud Storage** | Интеграция с GCP | Зависимость от GCP |
| **Azure Blob Storage** | Интеграция с Azure | Зависимость от Azure |

## Практический блок

### 1. Создание Snapshot Repository

#### Вариант 1: Filesystem (NFS)

```yaml
# 01-snapshot-repository.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: elasticsearch-backups
  namespace: logging
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: nfs-client
  resources:
    requests:
      storage: 100Gi
```

```bash
# Регистрация repository в Elasticsearch
curl -X PUT "http://elasticsearch-master:9200/_snapshot/my_backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "fs",
    "settings": {
      "location": "/mount/backups/elasticsearch",
      "compress": true,
      "max_snapshot_bytes_per_sec": "50mb",
      "max_restore_bytes_per_sec": "50mb"
    }
  }'
```

#### Вариант 2: S3-compatible (MinIO)

```bash
# Установка MinIO через Helm
helm repo add minio https://charts.min.io/
helm install minio minio/minio \
  -n logging \
  --set rootUser=minioadmin \
  --set rootPassword=minioadmin123 \
  --set persistence.size=100Gi

# Регистрация S3 repository
curl -X PUT "http://elasticsearch-master:9200/_snapshot/my_s3_backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "s3",
    "settings": {
      "bucket": "elasticsearch-backups",
      "region": "us-east-1",
      "endpoint": "http://minio.logging.svc:9000",
      "access_key": "minioadmin",
      "secret_key": "minioadmin123",
      "compress": true,
      "server_side_encryption": false,
      "path_style_access": true
    }
  }'
```

### 2. Настройка Snapshot Lifecycle Management (SLM)

```bash
# Создание SLM политики для ежедневных бэкапов
curl -X PUT "http://elasticsearch-master:9200/_slm/policy/daily_backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "schedule": "0 30 1 * * ?",
    "name": "<daily-snap-{now/d}>",
    "repository": "my_backup",
    "config": {
      "indices": ["*"],
      "ignore_unavailable": true,
      "include_global_state": false
    },
    "retention": {
      "expire_after": "7d",
      "min_count": 5,
      "max_count": 50
    }
  }'

# Создание SLM политики для еженедельных бэкапов
curl -X PUT "http://elasticsearch-master:9200/_slm/policy/weekly_backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "schedule": "0 0 2 ? * SUN",
    "name": "<weekly-snap-{now/d}>",
    "repository": "my_backup",
    "config": {
      "indices": ["*"],
      "ignore_unavailable": true,
      "include_global_state": true
    },
    "retention": {
      "expire_after": "30d",
      "min_count": 4,
      "max_count": 12
    }
  }'

# Просмотр SLM политик
curl -X GET "http://elasticsearch-master:9200/_slm/policy" | jq .

# Ручной запуск SLM политики
curl -X POST "http://elasticsearch-master:9200/_slm/policy/daily_backup/_execute"

# Просмотр статуса снапшотов
curl -X GET "http://elasticsearch-master:9200/_snapshot/my_backup/_all" | jq .
```

### 3. Ручное создание снапшота

```bash
# Создание полного снапшота
curl -X PUT "http://elasticsearch-master:9200/_snapshot/my_backup/manual_snapshot_$(date +%Y%m%d_%H%M%S)" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "*",
    "ignore_unavailable": true,
    "include_global_state": false,
    "metadata": {
      "taken_by": "manual",
      "reason": "pre-upgrade backup"
    }
  }'

# Создание снапшота конкретных индексов
curl -X PUT "http://elasticsearch-master:9200/_snapshot/my_backup/index_snapshot" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "fluent-bit-*",
    "ignore_unavailable": true,
    "include_global_state": false
  }'

# Просмотр статуса снапшота
curl -X GET "http://elasticsearch-master:9200/_snapshot/my_backup/manual_snapshot_20260809_120000" | jq .

# Просмотр всех снапшотов
curl -X GET "http://elasticsearch-master:9200/_snapshot/my_backup/_all" | jq '.snapshots[] | {name, start_time, end_time, state}'
```

### 4. Восстановление из снапшота

```bash
# Восстановление всех данных из снапшота
curl -X POST "http://elasticsearch-master:9200/_snapshot/my_backup/manual_snapshot_20260809_120000/_restore" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "*",
    "ignore_unavailable": true,
    "include_global_state": true,
    "rename_pattern": "(.+)",
    "rename_replacement": "restored_$1"
  }'

# Восстановление конкретных индексов
curl -X POST "http://elasticsearch-master:9200/_snapshot/my_backup/manual_snapshot_20260809_120000/_restore" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "fluent-bit-2026.08.*",
    "ignore_unavailable": true,
    "include_global_state": false,
    "rename_pattern": "(.+)",
    "rename_replacement": "restored_$1"
  }'

# Восстановление с перезаписью существующих индексов
curl -X POST "http://elasticsearch-master:9200/_snapshot/my_backup/manual_snapshot_20260809_120000/_restore" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "*",
    "ignore_unavailable": true,
    "include_global_state": true,
    "rename_pattern": "(.+)",
    "rename_replacement": "restored_$1",
    "ignore_aliases": true
  }'

# Просмотр статуса восстановления
curl -X GET "http://elasticsearch-master:9200/_cluster/recovery?active_only=true" | jq .
```

### 5. Удаление старых снапшотов

```bash
# Удаление конкретного снапшота
curl -X DELETE "http://elasticsearch-master:9200/_snapshot/my_backup/manual_snapshot_20260809_120000"

# Удаление снапшотов старше 7 дней
curl -X DELETE "http://elasticsearch-master:9200/_snapshot/my_backup/snapshots" \
  -H 'Content-Type: application/json' \
  -d '{
    "snapshots": [
      "daily-snap-2026.08.01",
      "daily-snap-2026.08.02",
      "daily-snap-2026.08.03",
      "daily-snap-2026.08.04",
      "daily-snap-2026.08.05",
      "daily-snap-2026.08.06"
    ]
  }'

# Просмотр размера снапшотов
curl -X GET "http://elasticsearch-master:9200/_snapshot/my_backup/_all" | jq '.snapshots[] | {name, total_shards, shard_stats}'
```

### 6. Автоматизация бэкапа через CronJob

```yaml
# 02-backup-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: elasticsearch-backup
  namespace: logging
spec:
  schedule: "0 30 1 * * ?"  # Каждый день в 01:30
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: elasticsearch-backup
          containers:
          - name: backup
            image: curlimages/curl:latest
            command:
            - /bin/sh
            - -c
            - |
              # Создание снапшота
              curl -X PUT "http://elasticsearch-master:9200/_snapshot/my_backup/auto_backup_$(date +%Y%m%d_%H%M%S)" \
                -H 'Content-Type: application/json' \
                -d '{
                  "indices": "*",
                  "ignore_unavailable": true,
                  "include_global_state": false,
                  "metadata": {
                    "taken_by": "cronjob",
                    "reason": "daily backup"
                  }
                }'
              
              # Проверка статуса
              sleep 10
              curl -X GET "http://elasticsearch-master:9200/_snapshot/my_backup/_all" | jq .
            env:
            - name: ELASTICSEARCH_URL
              value: "http://elasticsearch-master:9200"
          restartPolicy: OnFailure
      backoffLimit: 3
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: elasticsearch-backup
  namespace: logging
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: elasticsearch-backup
  namespace: logging
rules:
- apiGroups: [""]
  resources: ["pods", "services"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: elasticsearch-backup
  namespace: logging
subjects:
- kind: ServiceAccount
  name: elasticsearch-backup
  namespace: logging
roleRef:
  kind: Role
  name: elasticsearch-backup
  apiGroup: rbac.authorization.k8s.io
```

### 7. Мониторинг бэкапов

```yaml
# 03-backup-monitoring.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: elasticsearch-backup-alerts
  namespace: monitoring
  labels:
    release: prometheus
spec:
  groups:
  - name: elasticsearch-backup
    rules:
    # Алерт на неудачный снапшот
    - alert: ElasticsearchSnapshotFailed
      expr: elasticsearch_snapshots_failed_total > 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Elasticsearch: неудачный снапшот"
        description: "Количество неудачных снапшотов: {{ $value }}"
    
    # Алерт на старый снапшот
    - alert: ElasticsearchSnapshotOld
      expr: time() - elasticsearch_snapshots_start_time_seconds > 7 * 24 * 3600
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Elasticsearch: снапшот старше 7 дней"
        description: "Последний снапшот создан более 7 дней назад"
    
    # Алерт на превышение лимита снапшотов
    - alert: ElasticsearchSnapshotCountHigh
      expr: elasticsearch_snapshots_count > 50
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Elasticsearch: слишком много снапшотов"
        description: "Количество снапшотов: {{ $value }} (лимит: 50)"
```

## Дополнительная информация

### Проверка бэкапов

```bash
# Просмотр repository
curl -X GET "http://elasticsearch-master:9200/_snapshot/my_backup" | jq .

# Просмотр всех снапшотов
curl -X GET "http://elasticsearch-master:9200/_snapshot/my_backup/_all" | jq .

# Просмотр статуса SLM
curl -X GET "http://elasticsearch-master:9200/_slm/stats" | jq .

# Просмотр SLM политик
curl -X GET "http://elasticsearch-master:9200/_slm/policy" | jq .

# Просмотр последнего успешного снапшота
curl -X GET "http://elasticsearch-master:9200/_snapshot/my_backup/_all" | jq '.snapshots[] | select(.state == "SUCCESS") | {name, start_time, end_time}'
```

### Частые проблемы

1. **Repository isn't shared across all nodes**: Убедитесь, что хранилище доступно со всех нод кластера.
2. **Snapshot failed due to shard allocation**: Проверьте, что все shard'ы назначены.
3. **Restore failed due to index already exists**: Используйте `rename_pattern` для переименования индексов.
4. **Insufficient disk space**: Проверьте свободное место в хранилище.
5. **Network timeout**: Увеличьте таймауты для больших снапшотов.

### Рекомендации

1. Регулярно тестируйте восстановление из снапшотов.
2. Используйте SLM для автоматизации бэкапов.
3. Храните снапшоты в разных location (3-2-1 правило).
4. Мониторьте статус бэкапов и настраивайте алерты.
5. Документируйте процедуру восстановления.
6. Используйте增量 снапшоты для экономии места.

### Полезные ссылки

- [Elasticsearch Snapshot and Restore](https://www.elastic.co/guide/en/elasticsearch/reference/current/snapshot-restore.html)
- [Snapshot Lifecycle Management](https://www.elastic.co/guide/en/elasticsearch/reference/current/snapshot-lifecycle-management.html)
- [ECK Backup and Restore](https://www.elastic.co/guide/en/cloud-on-k8s/current/k8s-snapshot-restore.html)
- [MinIO for Elasticsearch](https://www.min.io/docs/minio/linux/integrations/elasticsearch.html)
- [Backup Strategies](https://www.elastic.co/blog/elasticsearch-backup-strategies)