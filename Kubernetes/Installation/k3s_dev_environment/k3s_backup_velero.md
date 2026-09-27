# Бэкап и восстановление K3s: Velero

Руководство по настройке бэкапа и восстановления кластера K3s с использованием Velero и Minio. Включает установку, бэкап манифестов и PV, восстановление, расписание бэкапов и тестирование.

Контекст: Часть серии по созданию dev-окружения в K3s. Minio используется как S3-хранилище для бэкапов Velero. См. [Архитектура K3s](./k3s_architecture.md), [Обновление K3s](./k3s_cluster_upgrade.md).

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Velero** | Инструмент для бэкапа и восстановления Kubernetes-кластеров. Бэкапит манифесты (CRD, Deployments, Services) и данные PersistentVolume через CSI snapshots или file-level backup (Restic/Kopia). |
| **Backup** | Снимок состояния кластера: YAML-манифесты всех ресурсов + данные PV. Хранится в Object Storage (Minio/S3). Velero backup НЕ включает etcd/SQLite напрямую. |
| **Restore** | Восстановление кластера из backup. Может быть полным (все ресурсы) или частичным (по label'ам, namespace). Не перезаписывает существующие ресурсы по умолчанию. |
| **Schedule** | CRD Velero для автоматического создания backup по расписанию (cron-формат). |
| **Snapshot** | Снимок PV через CSI (VolumeSnapshot). Требует CSI-драйвера с поддержкой snapshots. Для local-path K3s используется file-level backup через Kopia. |
| **Kopia** | Инструмент file-level backup, встроенный в Velero (ранее Restic). Копирует содержимое PV пофайловому, не требует CSI snapshot. |
| **Minio** | S3-совместимое Object Storage, используется как backend для Velero и артефактов GitLab/Harbor в dev-окружении. |

Навигация: [Velero Overview](../../ToolsUtilities/velero-overview.md) | [Backup Strategies](../../Operations/backup-strategies.md) | [Minio в K3s](./k3s_architecture.md)

---

## Основные концепции

### Архитектура бэкапа K3s через Velero

```text
┌─────────────────────────────────────────────────────────────────┐
│                     K3s Cluster                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    backup     ┌──────────────────────────────┐ │
│  │ Velero       │ ────────────▶ │           Minio              │ │
│  │ (Server)     │               │      (S3-compatible)         │ │
│  │              │               │                              │ │
│  │ Контроллер:  │               │  Buckets:                    │ │
│  │  - backup    │               │  - velero-backups            │ │
│  │  - restore   │               │  - velero-restic             │ │
│  │  - schedule  │               │                              │ │
│  └──────┬───────┘               └──────────────────────────────┘ │
│         │                                                         │
│         │ бэкапит                                                 │
│         ▼                                                         │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ 1. YAML-манифесты: Deployments, Services, ConfigMaps,       │ │
│  │    Secrets, PVC, PV, CRD, RBAC, Ingress                     │ │
│  │ 2. Данные PV через Kopia (file-level backup)                │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ SQLite/etcd: НЕ включается в Velero backup!                 │ │
│  │ Для state.db required отдельный бэкап: cp / tar             │ │
│  └──────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Что бэкапит Velero vs что НЕ бэкапит

| Velero бэкапит | Velero НЕ бэкапит |
| :--- | :--- |
| YAML-манифесты (Deployments, Services, ConfigMaps, Secrets, etc.) | etcd/SQLite (state.db) |
| Данные PersistentVolume (через Kopia/CSI) | K3s binary (`/usr/local/bin/k3s`) |
| Namespace, RBAC, CRD | Container images (нужен Harbor) |
| Ingress, NetworkPolicy | OS-level конфигурацию (sysctl, ufw) |
| Helm releases (как CRD) | `/etc/rancher/k3s/k3s.yaml` (нужен отдельный бэкап) |

### Стратегия бэкапа K3s

| Компонент | Метод | Частота | Хранение |
| :--- | :--- | :--- | :--- |
| **SQLite (state.db)** | `cp` / `tar` | Перед каждым обновлением | 3 последних копии |
| **YAML-манифесты** | Velero backup | Ежедневно | 7 дней |
| **Данные PV (GitLab, Harbor)** | Velero + Kopia | Ежедневно | 7 дней |
| **Конфигурация K3s** | `tar` `/etc/rancher/k3s/` | Перед обновлением | 3 копии |
| **Container images** | Harbor replication | По событию | N/A |

### Ресурсные требования

| Компонент | CPU | Memory | Storage | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| **Velero Server** | 250m | 256Mi | - | Controller + backup driver |
| **Kopia sidecar** | 100m | 128Mi | - | В каждом backupable поде |
| **Minio (shared)** | 250m | 512Mi | 20Gi | Уже установлен в лаборатории |
| **Итого** | ~600m | ~900Mi | ~20Gi | Дополнительно к основному стеку |

---

## Требования и предварительная подготовка

### Программные зависимости

| Компонент | Минимальная версия | Рекомендация |
| :--- | :--- | :--- |
| **K3s** | v1.28+ | v1.36.3+k3s1 |
| **Velero CLI** | v1.14+ | v1.15.x |
| **Velero Server** | v1.14+ | v1.15.x |
| **Minio** | Установлен | См. [Архитектура K3s](./k3s_architecture.md) |
| **Helm** | 3.14+ | v4.2.3 |

### Предварительные шаги

1. **Проверка Minio:**
```bash
kubectl -n minio get pods
# → NAME                   READY   STATUS    AGE
# → minio-xxx              1/1     Running   5m

# Проверка доступности
kubectl -n minio port-forward svc/minio-console 9001:9001 &
curl -s -o /dev/null -w "%{http_code}" http://localhost:9001
# → 200
```

2. **Установка Velero CLI:**
```bash
# macOS
brew install velero

# Linux
curl -fsSL https://github.com/vmware-tanzu/velero/releases/download/v1.15.2/velero-v1.15.2-linux-amd64.tar.gz | tar -xz
sudo mv velero-v1.15.2-linux-amd64/velero /usr/local/bin/

# Проверка
velero version
# → Client: v1.15.2
```

---

## Практические сценарии

### 1. Установка Velero через Helm

```bash
# Создание backup-бакета в Minio
kubectl -n minio exec minio-0 -- mc alias set local http://localhost:9000 minioadmin minioadmin123
kubectl -n minio exec minio-0 -- mc mb local/velero-backups
kubectl -n minio exec minio-0 -- mc mb local/velero-restic

# Установка Velero
helm repo add vmware-tanzu https://vmware-tanzu.github.io/helm-charts
helm repo update

helm install velero vmware-tanzu/velero \
  --namespace velero \
  --create-namespace \
  --set configuration.provider=aws \
  --set configuration.backupStorageLocation[0].name=default \
  --set configuration.backupStorageLocation[0].bucket=velero-backups \
  --set configuration.backupStorageLocation[0].config.region=minio \
  --set configuration.backupStorageLocation[0].config.s3ForcePathStyle=true \
  --set configuration.backupStorageLocation[0].config.s3Url=http://minio.minio.svc:9000 \
  --set configuration.backupStorageLocation[0].config.publicUrl=http://minio.minio.svc:9000 \
  --set configuration.volumeSnapshotLocation[0].name=default \
  --set configuration.volumeSnapshotLocation[0].config.region=minio \
  --set credentials.useSecret=false \
  --set snapshotsEnabled=true \
  --set deployRestic=true \
  --set restic.privileged=true \
  --set initContainers[0].name=velero-plugin-for-aws \
  --set initContainers[0].image=velero/velero-plugin-for-aws:v1.10.0 \
  --set initContainers[0].volumeMounts[0].mountPath=/target \
  --set initContainers[0].volumeMounts[0].name=plugins

# Ожидание готовности
kubectl -n velero get pods -w
# → NAME                      READY   STATUS    AGE
# → restic-xxxxx              2/2     Running   30s
# → velero-xxxxxxxxxx-xxxxx   1/1     Running   30s

# Проверка
velero backup-location get
# → NAME      PROVIDER   BUCKET/PREFIX             ACCESS MODE   PHASE
# → default   aws        velero-backups            ReadWrite     Available
```

### 2. Бэкап SQLite (state.db)

```bash
# Бэкап SQLite (КРИТИЧНО перед обновлением)
sudo cp /var/lib/rancher/k3s/server/db/state.db \
  /var/lib/rancher/k3s/server/db/state.db.backup.$(date +%Y%m%d%H%M%S)

# Бэкап всей директории конфигурации
sudo tar -czf /tmp/k3s-config-$(date +%Y%m%d%H%M%S).tar.gz \
  /etc/rancher/k3s/k3s.yaml \
  /etc/rancher/k3s/registries.yaml \
  /var/lib/rancher/k3s/server/tls/ \
  /var/lib/rancher/k3s/server/manifests/

# Проверка
ls -la /tmp/k3s-config-*.tar.gz
# → -rw-r--r-- 1 root root 12345 Sep 15 10:00 /tmp/k3s-config-20260915100000.tar.gz
```

### 3. Бэкап всех манифестов K3s

```bash
# Бэкап через Velero (только манифесты, без данных PV)
velero backup create k3s-manifests-$(date +%Y%m%d) \
  --include-namespaces gitlab,harbor,argocd,dev-workspaces,monitoring \
  --snapshot-volumes=false \
  --wait

# Проверка
velero backup get
# → NAME                          STATUS      ERRORS   WARNINGS   CREATED
# → k3s-manifests-20260915        Completed   0        0          2026-09-15 10:00:00 +0000 UTC

# Детали бэкапа
velero backup describe k3s-manifests-20260915 --details
# → Phase: Completed
# → Backup Volumes: 0 (snapshot-volumes=false)
```

### 4. Бэкап с данными PV (Kopia)

```bash
# Бэкап с включенным file-level backup (для данных GitLab, Harbor)
velero backup create k3s-full-$(date +%Y%m%d) \
  --include-namespaces gitlab,harbor,argocd,dev-workspaces,monitoring \
  --snapshot-volumes=true \
  --wait

# Проверка
velero backup get
# → NAME                          STATUS      ERRORS   WARNINGS   CREATED
# → k3s-full-20260915             Completed   0        0          2026-09-15 11:00:00 +0000 UTC

# Размер бэкапа в Minio
kubectl -n minio exec minio-0 -- du -sh /data/velero-backups/
# → 2.5G    /data/velero-backups/
```

### 5. Расписание бэкапов (Schedule)

```yaml
# velero-schedule.yaml
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: k3s-daily-backup
  namespace: velero
spec:
  schedule: "0 2 * * *"  # Ежедневно в 02:00
  template:
    includedNamespaces:
      - gitlab
      - harbor
      - argocd
      - dev-workspaces
      - monitoring
    snapshotVolumes: true
    storageLocation: default
    volumeSnapshotLocations:
      - default
    ttl: 168h  # 7 дней
    includedResources:
      - '*'
    excludedResources:
      - events
      - events.events.k8s.io
```

```bash
kubectl apply -f velero-schedule.yaml

# Проверка расписания
velero schedule get
# → NAME                 STATUS    SCHEDULE      LAST BACKUP   AGE
# → k3s-daily-backup     Enabled   0 2 * * *     2h ago        30m

# Ручной запуск по расписанию
velero schedule run k3s-daily-backup
```

### 6. Восстановление из бэкапа

```bash
# Полное восстановление
velero restore create k3s-restore-$(date +%Y%m%d) \
  --from-backup k3s-full-20260915 \
  --wait

# Проверка
velero restore get
# → NAME                          STATUS      ERRORS   WARNINGS   CREATED
# → k3s-restore-20260915          Completed   0        0          2026-09-15 12:00:00 +0000 UTC

# Восстановление только определенного namespace
velero restore create restore-gitlab \
  --from-backup k3s-full-20260915 \
  --include-namespaces gitlab \
  --wait

# Восстановление по label'ам
velero restore create restore-apps \
  --from-backup k3s-full-20260915 \
  --selector app=gitlab \
  --wait
```

### 7. Восстановление SQLite + манифестов (полная процедура)

```bash
# === Сценарий: восстановление после обновления ===

# 1. Остановка K3s
sudo systemctl stop k3s

# 2. Восстановление SQLite
sudo cp /var/lib/rancher/k3s/server/db/state.db.backup.<timestamp> \
  /var/lib/rancher/k3s/server/db/state.db

# 3. Восстановление конфигурации
sudo tar -xzf /tmp/k3s-config-<timestamp>.tar.gz -C /

# 4. Запуск K3s
sudo systemctl start k3s

# 5. Проверка
kubectl get nodes
# → NAME     STATUS   ROLES                  AGE     VERSION
# → server   Ready    control-plane,master   5m      v1.36.3+k3s1

# 6. Восстановление данных PV через Velero
velero restore create restore-full \
  --from-backup k3s-full-<timestamp> \
  --wait
```

---

## Типичные ошибки и устранение неполадок

### Ошибка: `BackupStorageLocation is invalid`

```bash
# Проверка доступности Minio из пода Velero
kubectl -n velero exec $(kubectl -n velero get pods -l name=velero -o name) -- \
  wget -qO- 'http://minio.minio.svc:9000/minio/health/live'
# → (пустой вывод = OK)

# Проверка бакета
kubectl -n velero exec $(kubectl -n velero get pods -l name=velero -o name) -- \
  ls /data/velero-backups/
# → Должны быть backup-директории
```

### Ошибка: Kopia не может забэкапить PV

```bash
# Проверка подов restic
kubectl -n velero get pods -l name=restic
# → restic-xxxxx   2/2   Running

# Проверка логов restic
kubectl -n velero logs $(kubectl -n velero get pods -l name=restic -o name) -c restic --tail=50
# → Ищите "error" или "permission denied"

# Убедитесь, что restic запущен с привилегиями
kubectl -n velero get ds restic -o yaml | grep privileged
# → privileged: true
```

### Ошибка: Velero не видит PVC

```bash
# Проверка аннотации на PVC (для file-level backup)
kubectl get pvc -A -o json | jq -r '.items[] | "\(.metadata.namespace)/\(.metadata.name): \(.metadata.annotations["backup.velero.io/backup-volumes"] // "NOT ANNOTATED")"'

# Добавление аннотации (если забыли)
kubectl annotate pvc -n gitlab data-gitlab-gitaly-0 \
  backup.velero.io/backup-volumes=data
```

---

## Дополнительная информация

### Предупреждения

| Аспект | Риск | Рекомендация |
| :--- | :--- | :--- |
| **SQLite** | Нет HA, потеря при повреждении | Бэкап state.db перед каждым обновлением |
| **Velero не бэкапит SQLite** | Потеря состояния кластера | Отдельный `cp` / `tar` для state.db |
| **Kopia performance** | Медленный backup больших PV | Используйте `--parallelism=4` для ускорения |
| **Minio** | Single point of failure | Для prod используйте S3/GCS с replication |
| **Restore** | Не перезаписывает существующие ресурсы | Используйте `--restore-existing-pods` при необходимости |

### См. также

- [Velero Overview](../../ToolsUtilities/velero-overview.md) -- полный обзор Velero
- [Стратегии бэкапа](../../Operations/backup-strategies.md) -- 3-2-1, RPO/RTO
- [Архитектура K3s](./k3s_architecture.md) -- Minio как backend
- [Обновление K3s](./k3s_cluster_upgrade.md) -- бэкап перед обновлением
