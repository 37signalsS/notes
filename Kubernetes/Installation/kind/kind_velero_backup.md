# kind — backup и restore через Velero

## Определения

**Velero** — инструмент для backup и восстановления объектов Kubernetes (Deployments, Services, ConfigMaps, Secrets, PersistentVolumeClaim) и связанных данных (PersistentVolumes). Работает через Kubernetes API и поддерживает различные бэкенд-хранилища (S3, MinIO, NFS, local).

**Backup** — снапшот всех (или отфильтрованных) объектов Kubernetes и их данных в определённый момент времени.

**Restore** — восстановление объектов из ранее созданного backup.

**Snapshot** — снапшот дискового тома (PersistentVolume), создаваемый через CSI-драйвер или.storage-класс.

---

## Основные концепции

### Зачем тестировать Velero в kind

kind позволяет безопасно проверить процедуры backup/restore перед применением в production:

- Проверить, что Velero корректно подключается к бэкенду
- Протестировать backup и restore конкретных неймспейсов
- Отработать восстановление после «катастрофы» (удаление кластера)
- Проверить фильтрацию backup по label/namespace

### Ограничения Velero в kind

| Ограничение | Описание | Решение |
|:---|:---|:---|
| **Нет CSI-снапшотов** | kind использует local-path-provisioner, не поддерживающий снапшоты | Использовать файловый backup (Restic/Kopia) |
| **Только объекты** | Backup объектов Kubernetes работает полноценно | Для данных PV использовать Restic |
| **MinIO вместо S3** | Для локального тестирования нужен MinIO | Запустить MinIO как под в кластере |

### Архитектура Velero в kind

```
┌─────────────────────────────────────────────┐
│                    kind                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Velero  │  │   MinIO  │  │  Restic  │  │
│  │  Server  │  │  (S3)    │  │ (files)  │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       │              │              │        │
│       └──────────────┴──────────────┘        │
│                    │                         │
│              Backup/Restore                  │
│                    │                         │
│       ┌────────────┴────────────┐            │
│       │  Kubernetes Objects     │            │
│       │  (Deployments, Pods,    │            │
│       │   Services, Secrets)    │            │
│       └─────────────────────────┘            │
└─────────────────────────────────────────────┘
```

---

## Практические сценарии

### Сценарий 1: Установка Velero и MinIO в kind

```bash
# 1. Создание кластера
kind create cluster --name velero-test

# 2. Установка MinIO (S3-совместимое хранилище)
kubectl apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: minio
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: minio
  namespace: minio
spec:
  replicas: 1
  selector:
    matchLabels:
      app: minio
  template:
    metadata:
      labels:
        app: minio
    spec:
      containers:
      - name: minio
        image: minio/minio:latest
        args: ["server", "/data", "--console-address", ":9001"]
        env:
        - name: MINIO_ROOT_USER
          value: "minioadmin"
        - name: MINIO_ROOT_PASSWORD
          value: "minioadmin"
        ports:
        - containerPort: 9000
        - containerPort: 9001
        volumeMounts:
        - name: data
          mountPath: /data
      volumes:
      - name: data
        emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: minio
  namespace: minio
spec:
  selector:
    app: minio
  ports:
  - name: api
    port: 9000
  - name: console
    port: 9001
EOF

# Ожидание готовности MinIO
kubectl -n minio rollout status deployment/minio

# 3. Установка Velero CLI
brew install velero  # macOS
# или
curl -fsSL https://github.com/vmware-tanzu/velero/releases/download/v1.14.0/velero-v1.14.0-darwin-amd64.tar.gz | tar xz
sudo mv velero-v1.14.0-darwin-amd64/velero /usr/local/bin/

# 4. Создание конфигурации Velero
cat > velero-config.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: minio-credentials
  namespace: velero
stringData:
  cloud: |
    [default]
    aws_access_key_id=minioadmin
    aws_secret_access_key=minioadmin
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: minio-config
  namespace: velero
data:
  bucket: "velero-backups"
  config: |
    [default]
    aws_access_key_id=minioadmin
    aws_secret_access_key=minioadmin
    region=minio
    s3ForcePathStyle=true
    s3Url=http://minio.minio.svc:9000
    publicUrl=
EOF

# 5. Установка Velero
velero install \
  --provider aws \
  --bucket velero-backups \
  --secret-file <(kubectl get secret minio-credentials -n velero -o jsonpath='{.data.cloud}' | base64 -d) \
  --backup-location-config "region=minio,s3ForcePathStyle=true,s3Url=http://minio.minio.svc:9000" \
  --use-node-agent \
  --plugins velero/velero-plugin-for-aws:v1.9.0

# 6. Ожидание готовности
kubectl -n velero rollout status deployment/velero
kubectl get pods -n velero
```

### Сценарий 2: Тестовое приложение и backup

```bash
# 1. Создание тестового приложения
kubectl apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: test-app
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx
  namespace: test-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:1.27
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: nginx
  namespace: test-app
spec:
  selector:
    app: nginx
  ports:
  - port: 80
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-config
  namespace: test-app
data:
  nginx.conf: |
    server {
      listen 80;
      location / {
        return 200 "Hello from kind!";
      }
    }
EOF

# Ожидание готовности
kubectl -n test-app rollout status deployment/nginx

# 2. Создание backup
velero backup create test-app-backup \
  --include-namespaces test-app \
  --wait

# 3. Проверка backup
velero backup get
# → NAME               STATUS      ERRORS   WARNINGS   CREATED                      EXPIRES   STORAGE LOCATION   SELECTOR
# → test-app-backup    Completed   0        0          2026-09-09 12:00:00 +0000 UTC   30d       default            <none>

# 4. Детали backup
velero backup describe test-app-backup --details
```

### Сценарий 3: Восстановление после удаления

```bash
# 1. Удаление тестового приложения (эмуляция катастрофы)
kubectl delete namespace test-app

# 2. Проверка: приложение удалено
kubectl get namespace test-app
# → Error from server (NotFound): namespaces "test-app" not found

# 3. Восстановление из backup
velero restore create test-app-restore \
  --from-backup test-app-backup \
  --wait

# 4. Проверка восстановления
kubectl get namespace test-app
# → NAME       STATUS   AGE
# → test-app   Active   30s

kubectl -n test-app get pods
# → NAME                    READY   STATUS    RESTARTS   AGE
# → nginx-xxxxx-yyyyy       1/1     Running   0          30s
# → nginx-xxxxx-zzzzz       1/1     Running   0          30s
# → nginx-xxxxx-aaaa        1/1     Running   0          30s

kubectl -n test-app get configmap nginx-config
# → NAME           DATA   AGE
# → nginx-config   1      30s
```

### Сценарий 4: Backup с фильтрацией

```bash
# Backup только определённых namespace
velero backup create prod-backup \
  --include-namespaces production,staging \
  --wait

# Backup с фильтрацией по label
velero backup create critical-backup \
  --selector "backup=critical" \
  --wait

# Backup с исключением определённых ресурсов
velero backup create exclude-jobs-backup \
  --exclude-resources jobs,cronjobs \
  --wait

# Backup всех namespace кроме system
velero backup create all-except-system \
  --exclude-namespaces kube-system,kube-public,kube-node-lease \
  --wait

# Просмотр всех backup
velero backup get --all-namespaces
```

### Сценарий 5: Автоматический backup через CronSchedule

```bash
# Ежедневный backup production namespace
velero schedule create daily-prod \
  --schedule="0 2 * * *" \
  --include-namespaces production \
  --ttl 720h \
  --wait

# Еженедельный backup всех namespace
velero schedule create weekly-all \
  --schedule="0 0 * * 0" \
  --exclude-namespaces kube-system,kube-public \
  --ttl 720h \
  --wait

# Просмотр расписаний
velero schedule get

# Ручной запуск по расписанию
velero backup create --from-schedule daily-prod manual-prod-backup
```

### Сценарий 6: Диагностика проблем Velero

**Типичные ошибки:**

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Backup phase: PartiallyFailed` | Часть объектов не удалось backup | Проверить `velero backup describe --details` |
| `Restore phase: PartiallyFailed` | Конфликт с существующими объектами | Использовать `--restore-volumes` или `--force` |
| `BackupRepository not found` | MinIO недоступен | Проверить под MinIO: `kubectl -n minio get pods` |
| `Plugin not found` | Не установлен плагин для S3 | Установить `velero-plugin-for-aws` |

**Команды диагностики:**

```bash
# Просмотр логов Velero
kubectl -n velero logs -l app.kubernetes.io/name=velero --tail=50

# Просмотр деталей backup
velero backup describe test-app-backup --details

# Просмотр логов конкретного backup
velero backup logs test-app-backup

# Просмотрrestore
velero restore describe test-app-restore --details

# Проверка BackupStorageLocation
velero backup-location get

# Проверка PodVolumeBackups (для Restic)
kubectl get podvolumebackups -n velero
```

---

## Дополнительная информация

### Ссылки

- [kind — определения и концепции](./kind_concepts.md) — архитектура и внутреннее устройство узлов
- [Velero Overview](../../ToolsUtilities/velero-overview.md) — полная теория Velero
- [Backup стратегии](../../Operations/backup-strategies.md) — общие стратегии backup в Kubernetes
- [Storage](../../Storage/) — information about storage classes and CSI drivers
- [Официальная документация Velero](https://velero.io/docs/)
