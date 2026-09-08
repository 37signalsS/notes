# Миграция данных между кластерами через CSI

## Определения

**Cross-Cluster Data Migration** — процесс переноса PersistentVolume (данных приложений) между двумя независимыми Kubernetes-кластерами, thường используется при миграции между дата-центрами, обновлении инфраструктуры или при аварийном восстановлении.

Основные подходы:
- **Velero + CSI Snapshots** — создание снапшотов через CSI и восстановление в целевом кластере
- **Репликация на уровне СХД** — Ceph RBD mirroring, Longhorn DR Volume
- **rsync / rclone** — файловая репликация данных поверх NFS/S3
- **Экспорт/импорт** — выгрузка данных из приложения и загрузка в новом кластере

---

## Теоретический блок

### Матрица подходов к миграции

| Подход | Уровень | RPO | RTO | Ограничения |
| :--- | :--- | :--- | :--- | :--- |
| **Velero + CSI Snapshots** | K8s API + CSI | Зависит от частоты снапшотов (часы) | 30-60 мин | Требует CSI-драйвер с поддержкой снапшотов на обоих кластерах |
| **Ceph RBD Mirroring** | СХД (block) | Мгновенно (sync) / секунды (async) | 5-15 мин | Только для Ceph RBD, требует настройки на уровне Ceph |
| **Longhorn DR Volume** | СХД (block) | Зависит от schedules | 15-30 мин | Только Longhorn |
| **Velero Data Mover** | K8s API + FS | Зависит от частоты | 30-120 мин | Медленно для больших томов |
| **rsync поверх VPN** | Файловая система | Зависит от rsync cron | 10-30 мин | Только для файловых томов (NFS/CephFS) |
| **Экспорт из приложения** | Приложение | Зависит от метода | 1-24 часа | Зависит от приложения |

### Velero + CSI Snapshots: Архитектура

```
Источниковый кластер:
  1. Velero создаёт VolumeSnapshot через CSI
  2. CSI-драйвер создаёт снапшот в СХД
  3. Velero экспортирует снапшот в Object Storage (BSL)
  4. Velero сохраняет K8s-ресурсы (PV, PVC, Deployment, etc.) в BSL

Целевой кластер:
  1. Velero импортирует K8s-ресурсы из BSL
  2. Velero создаёт VolumeSnapshotContent из снапшота в BSL
  3. CSI-драйвер создаёт новый PV из снапшота
  4. PVC привязывается к новому PV
```

**Требования:**
- CSI-драйвер с поддержкой снапшотов на **обоих** кластерах
- Object Storage (S3/MinIO) доступный из обоих кластеров
- Velero с CSI-плагином (`velero-plugin-for-csi`)
- `VolumeSnapshotClass` на обоих кластерах

### Ceph RBD Mirroring: Архитектура

```
Ceph Cluster A (источник):
  rbd mirror pool enable <pool> image
  rbd mirror image enable <image>

Ceph Cluster B (приёмник):
  rbd mirror pool peer add <pool> <cluster-A-fsid>
  → Автоматическая репликация образов между кластерами

Kubernetes (приёмник):
  Создаём PV с dataImporterAnnotation → Ceph CSI подключает реплицированный образ
```

**Режимы mirroring:**
- **Pool-level mirroring** — реплицируются все образы в пуле
- **Image-level mirroring** — реплицируются отдельные образы
- **Синхронный (sync)** — RPO=0, но задержка на запись
- **Асинхронный (async)** — RPO > 0, нет задержки

### Критерии выбора подхода

```
Данные < 100 ГБ?
  ├─ Да → Velero + CSI Snapshots (простой,足够的 для большинства случаев)
  └─ Нет →
     ├─ Ceph RBD на обоих кластерах?
     │   ├─ Да → Ceph RBD Mirroring (быстро, RPO=0)
     │   └─ Нет →
     │       ├─ Longhorn на обоих кластерах?
     │       │   ├─ Да → Longhorn DR Volume
     │       │   └─ Нет → rsync + VPN / Velero Data Mover
     └─ Файловое хранилище (NFS/CephFS)?
         └─ rsync поверх VPN (самый быстрый способ)
```

---

## Практический блок

### Сценарий 1: Миграция через Velero + CSI Snapshots

#### Шаг 1: Подготовка на обоих кластерах

```bash
# На обоих кластерах: установка Velero с CSI-плагином
helm repo add vmware-tanzu https://vmware-tanzu.github.io/helm-charts
helm install velero vmware-tanzu/velero \
  --namespace velero --create-namespace \
  --set configuration.provider=aws \
  --set configuration.backupStorageLocation[0].bucket=velero-migration \
  --set configuration.backupStorageLocation[0].config.region=minio \
  --set configuration.backupStorageLocation[0].config.s3ForcePathStyle=true \
  --set configuration.backupStorageLocation[0].config.s3Url=http://minio.minio.svc:9000 \
  --set snapshotsEnabled=true \
  --set deployRestic=false \
  --set configuration.features=EnableCSI

# На целевом кластере: создание VolumeSnapshotClass
cat <<EOF | kubectl apply -f -
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: csi-snapshot-class
  labels:
    velero.io/csi-volumesnapshot-class: "true"
driver: rbd.csi.ceph.com
deletionPolicy: Retain
parameters:
  clusterID: <ceph-cluster-id>
EOF
```

#### Шаг 2: Backup на исходном кластере

```bash
# Создание backup с CSI-снапшотами
velero backup create migration-backup \
  --include-namespaces production \
  --storage-location default \
  --wait

# Проверка статуса
velero backup describe migration-backup
velero backup logs migration-backup | grep -i "csi\|snapshot"
```

#### Шаг 3: Восстановление на целевом кластере

```bash
# Копирование BSL-данных между кластерами (если MinIO/S3 не общий)
# На исходном кластере:
mc mirror velero-migration/ /backup/velero-migration/

# На целевом кластере:
mc mirror /backup/velero-migration/ velero-migration/

# Восстановление
velero restore create migration-restore \
  --from-backup migration-backup \
  --namespace-mappings production:production-restored \
  --wait

# Проверка
kubectl get pvc -n production-restored
kubectl get pods -n production-restored
```

#### Шаг 4: Resource Modifiers для кросс-кластерного восстановления

```yaml
# Если StorageClass на целевом кластере отличается
apiVersion: velero.io/v1alpha1
kind: ResourceModifier
metadata:
  name: storage-migration-modifier
  namespace: velero
spec:
  resourceSelector:
    includedResources:
      - persistentvolumeclaims
  patches:
    - op: replace
      path: /spec/storageClassName
      value: "ceph-rbd-new"
    - op: replace
      path: /spec/resources/requests/storage
      value: "100Gi"
```

### Сценарий 2: Ceph RBD Mirroring

#### Настройка на исходном Ceph-кластере

```bash
# Включение mirroring для пула
ceph bullseye rbd mirror pool enable kube rbd mirror

# Создание peer-связи с целевым кластером
ceph bullseye rbd mirror pool peer add kube client.bootstrap-mirror@remote

# Для конкретного образа (image-level mirroring)
rbd mirror image enable kube/my-pvc-image

# Проверка статуса
rbd mirror pool status kube
rbd mirror image status kube/my-pvc-image
```

#### Импорт в целевой кластер

```yaml
# PV, ссылающийся на реплицированный Ceph RBD образ
apiVersion: v1
kind: PersistentVolume
metadata:
  name: migrated-pv
  annotations:
    pv.kubernetes.io/provisioned-by: rbd.csi.ceph.com
spec:
  capacity:
    storage: 100Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ceph-rbd
  csi:
    driver: rbd.csi.ceph.com
    volumeHandle: <image-id-from-mirror>
    volumeAttributes:
      clusterID: <target-ceph-cluster-id>
      imageFeatures: layering
      imageFormat: "2"
      pool: kube
    nodeStageSecretRef:
      name: csi-rbd-secret
      namespace: kube-system
    controllerPublishSecretRef:
      name: csi-rbd-secret
      namespace: kube-system
```

### Сценарий 3: rsync для NFS-данных

```bash
# Миграция данных с NFS одного кластера на NFS другого кластера

# На исходном NFS-сервере:
rsync -avz --progress /exports/kubernetes/ \
  <target-nfs-server>:/exports/kubernetes/

# Или через VPN (если NFS-серверы не в одной сети):
rsync -avz -e "ssh -p 22 -i ~/.ssh/migration_key" \
  /exports/kubernetes/ user@<target-server>:/exports/kubernetes/

# Инициализация (после rsync) — повторная синхронизация для данных, изменившихся во время первой передачи:
rsync -avz --delete /exports/kubernetes/ \
  <target-nfs-server>:/exports/kubernetes/
```

### Чеклист миграции

- [ ] **Backup на исходном кластере**: Velero backup завершён, BSL доступен
- [ ] **CSI-драйвер на целевом кластере**: установлен и зарегистрирован
- [ ] **VolumeSnapshotClass**: создан на целевом кластере с `velero.io/csi-volumesnapshot-class`
- [ ] **StorageClass**: совпадает с исходным кластером (или настроен ResourceModifier)
- [ ] **Секреты**: CSI-секреты (access/secret keys) доступны на целевом кластере
- [ ] **Тестовое восстановление**: проверено на тестовом PVC перед основной миграцией
- [ ] **Downtime**: согласовано окно простоя (при необходимости)
- [ ] **Rollback план**: исходный кластер сохранён до подтверждения успеха

---

## Дополнительная информация

### Связанные темы
- [Velero — Обзор](../../../ToolsUtilities/velero-overview.md) — полная документация Velero
- [Стратегии бэкапа](../../Operations/backup-strategies.md) — стратегии бэкапа Kubernetes
- [Disaster Recovery](../../../Concepts/disaster_recovery.md) — паттерны DR
- [Сравнение CSI-драйверов](./csi_drivers_comparison.md) — выбор драйвера
- [Продвинутые возможности CSI](./csi_advanced.md) — снапшоты, клонирование
- [Ceph RBD — Advanced](../Ceph/ceph_rbd_usage/advanced_topics.md) — live migration между пулами

### Официальные источники
- [Velero CSI Plugin](https://github.com/vmware-tanzu/velero-plugin-for-csi) — CSI-плагин Velero
- [Ceph RBD Mirroring](https://docs.ceph.com/en/latest/rbd/rbd-mirroring/) — документация Ceph
- [Longhorn DR Volume](https://longhorn.io/docs/latest/volumes/volumes-with-dr-volume/) — DR-тома Longhorn
