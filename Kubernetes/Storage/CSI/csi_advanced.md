# Продвинутые возможности CSI

## Определения

**CSI Advanced Features** — расширенные возможности Container Storage Interface, выходящие за рамки базового управления томами ([базовая информация](./csi_overview.md)):

- **Volume Snapshots** — создание снимков состояния `PersistentVolume` на определённый момент времени
- **Volume Cloning** — создание независимой копии существующего тома
- **CSI Topology** — учёт физического расположения томов при планировании подов
- **Volume Expansion** — увеличение размера `PersistentVolume` без потери данных
- **CSI Migration** — перевод встроенных (in-tree) плагинов хранения на внешние (out-of-tree) CSI-драйверы

---

## Базовые концепции

### API снапшотов томов (Volume Snapshots)

**Volume Snapshot** — механизм создания "снимков" состояния `PersistentVolume`. Реализуется через CSI-драйвер и стандартный Kubernetes API.

#### Ключевые компоненты

1. **`VolumeSnapshotClass`** — определяет параметры создания снапшотов (аналогично `StorageClass`):
   - `driver` — имя CSI-драйвера (например, `ebs.csi.aws.com`, `rbd.csi.ceph.com`)
   - `deletionPolicy` — политика удаления (`Retain` или `Delete`)
   - `parameters` — специфичные параметры СХД

2. **`VolumeSnapshot`** — ресурс, описывающий запрос на создание снапшота конкретного PVC.

3. **`VolumeSnapshotContent`** — низкоуровневый объект, представляющий снапшот в системе хранения (аналог PV для PVC).

> **Требование:** Для работы Volume Snapshots в кластере должен быть установлен **snapshot controller** и CSI-драйвер с поддержкой `CREATE_DELETE_SNAPSHOT`.

#### Сценарии использования

- **Резервное копирование:** Быстрое создание точки восстановления перед обновлением приложения.
- **Клонирование данных:** Создание нового PVC из снапшота для тестирования или аналитики.
- **Миграция данных:** Перенос данных между кластерами через экспорт снапшотов.

### Клонирование томов (Volume Cloning)

**Volume Cloning** — создание новой копии существующего `PersistentVolume` через PVC с использованием поля `dataSource`.

#### Отличие от снапшотов

| Параметр | Снапшот | Клон |
| :--- | :--- | :--- |
| **Цель** | Точка восстановления | Независимый том |
| **Зависимость** | Исходный PVC должен существовать | После создания независим |
| **Использование** | Восстановление, бэкап | Тестирование, аналитика, fork |

#### Требования для клонирования

- CSI-драйвер должен поддерживать `CREATE_DELETE_VOLUME`
- Размер клона ≥ размера исходного тома
- Оба PVC в одном namespace (ограничение Kubernetes)

### Топология CSI (CSI Topology)

**CSI Topology** — механизм учёта физического расположения томов при планировании подов. Критично для распределённых систем и облачных окружений с зонами доступности.

#### Проблема и решение

В облачных окружениях диск привязан к конкретной зоне доступности (AZ). CSI-драйвер сообщает Kubernetes о топологии через `TopologyKeys`, планировщик учитывает это при размещении подов.

#### Режимы volumeBindingMode

| Режим | Описание | Когда использовать |
| :--- | :--- | :--- |
| `Immediate` | PV создаётся сразу при создании PVC | Однозонные кластеры, stateless-приложения |
| `WaitForFirstConsumer` | PV создаётся после появления пода | Многозонные кластеры, stateful-приложения |

> **Рекомендация:** Для stateful-приложений в многозонных кластерах всегда использовать `WaitForFirstConsumer`.

### Расширение томов (Volume Expansion)

**Volume Expansion** — увеличение размера `PersistentVolume` без потери данных.

#### Способы расширения

1. **Offline Expansion:** Том должен быть отмонтирован (под остановлен)
2. **Online Expansion:** Расширение "на лету" без остановки приложения (требует поддержки ФС и CSI-драйвера)

#### Требования

- `StorageClass` должен иметь `allowVolumeExpansion: true`
- CSI-драйвер должен поддерживать `EXPAND_VOLUME`
- Для online expansion файловая система должна поддерживать resize (ext4, xfs)

### Миграция CSI (CSI Migration)

**CSI Migration** — процесс перевода встроенных (in-tree) плагинов хранения на внешние (out-of-tree) CSI-драйверы.

#### Контекст

До Kubernetes 1.24 многие плагины (AWS EBS, GCE PD, Azure Disk, vSphere, Cinder, Ceph RBD, CephFS) были встроены в код Kubernetes. Начиная с 1.24, большинство in-tree плагинов удалены, использование автоматически перенаправляется на CSI-драйверы.

> **Важно (Kubernetes 1.31+):** В v1.31 полностью удалены плагины CephFS и Ceph RBD. Все оставшиеся in-tree интеграции с облачными провайдерами удалены. Kubernetes перешёл к строго vendor-neutral архитектуре — использование CSI-драйверов обязательно ([Kubernetes 1.31 changelog](https://kubernetes.io/blog/2024/07/19/kubernetes-1-31-upcoming-changes/)).

#### Механизм работы

- **`CSIMigration` feature gate:** Включает автоматическую трансляцию in-tree `StorageClass` в CSI-эквиваленты
- **Автоматическая совместимость:** Существующие манифесты продолжают работать без изменений

#### Статус миграции (завершена в Kubernetes 1.31)

| In-tree плагин | CSI замена | Сценарий |
| :--- | :--- | :--- |
| `kubernetes.io/aws-ebs` | `ebs.csi.aws.com` | AWS EBS |
| `kubernetes.io/gce-pd` | `pd.csi.storage.gke.io` | GCP Persistent Disk |
| `kubernetes.io/azure-disk` | `disk.csi.azure.com` | Azure Disk |
| `kubernetes.io/cinder` | `cinder.csi.openstack.org` | OpenStack |
| `kubernetes.io/vsphere-volume` | `csi.vsphere.vmware.com` | VMware vSphere |
| `kubernetes.io/portworx-volume` | `pxd.portworx.com` | Portworx |
| `kubernetes.io/cephfs` | `cephfs.csi.ceph.com` | Ceph FS (**удалён в 1.31**) |
| `kubernetes.io/rbd` | `rbd.csi.ceph.com` | Ceph RBD (**удалён в 1.31**) |

> **Рекомендация:** Для Kubernetes 1.24+ явно использовать CSI-драйверы в манифестах.

---

## Практические сценарии

### Создание снапшота PVC

```yaml
# VolumeSnapshotClass
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: csi-rbd-snap-class
driver: rbd.csi.ceph.com
deletionPolicy: Retain  # Снапшот сохранится после удаления VolumeSnapshot

---
# VolumeSnapshot
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: my-db-snapshot
spec:
  volumeSnapshotClassName: csi-rbd-snap-class
  source:
    persistentVolumeClaimName: my-db-pvc
```

### Восстановление из снапшота

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: restored-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: standard
  resources:
    requests:
      storage: 10Gi
  dataSource:
    name: my-db-snapshot
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
```

### Клонирование тома

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: cloned-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: standard
  resources:
    requests:
      storage: 10Gi  # Должен быть >= размера исходного PVC
  dataSource:
    name: source-pvc  # Имя исходного PVC
    kind: PersistentVolumeClaim
```

### Ceph RBD с снапшотами (Volume Snapshots) для PostgreSQL

```yaml
# StorageClass для RBD
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-rbd-ssd
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: rook-ceph
  pool: replicapool
  imageFormat: "2"
  imageFeatures: layering,fast-diff,object-map
  csi.storage.k8s.io/provisioner-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/node-stage-secret-name: rook-csi-rbd-node
allowVolumeExpansion: true
reclaimPolicy: Retain

---
# PVC для PostgreSQL
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-data
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ceph-rbd-ssd
  resources:
    requests:
      storage: 50Gi

---
# VolumeSnapshot для бэкапа
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: postgres-backup-daily
spec:
  volumeSnapshotClassName: ceph-rbd-snap
  source:
    persistentVolumeClaimName: postgres-data
```

### StorageClass с учётом топологии

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: zonal-ssd
provisioner: rbd.csi.ceph.com
volumeBindingMode: WaitForFirstConsumer  # Критично для топологии
parameters:
  pool: replicapool
  clusterID: rook-ceph
```

### Расширение тома

```yaml
# Обновление PVC с 10Gi до 20Gi
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-app-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: standard-ssd
  resources:
    requests:
      storage: 20Gi  # Увеличиваем размер
```

Проверка поддержки расширения:

```bash
kubectl get storageclass standard-ssd -o yaml | grep allowVolumeExpansion
# allowVolumeExpansion: true
```

### Миграция с in-tree на CSI (Ceph RBD)

```yaml
# До миграции (in-tree, устарело)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-storage
provisioner: kubernetes.io/cinder  # In-tree плагин (OpenStack)

# После миграции (CSI драйвер)
provisioner: rbd.csi.ceph.com
parameters:
  pool: replicapool
  clusterID: rook-ceph
```

---

## Дополнительная информация

### Диагностика и мониторинг

Проверка статуса CSI-драйверов и таблица поддержки Snapshots/Cloning/Expansion/Topology доступна в [сравнении CSI-драйверов](./csi_drivers_comparison.md#диагностика-и-мониторинг-csi). Для базовых концепций CSI см. [обзор CSI](./csi_overview.md), для настройки PV/PVC — [руководство по хранению данных](../pv_and_pvc.md). Настройка Ceph CSI драйверов: [RBD](../Ceph/ceph_csi_rbd_driver_setup.md), [CephFS](../Ceph/ceph_csi_cephfs_driver_setup.md).

### Официальные источники

Спецификации Kubernetes: [Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/), [Storage Classes](https://kubernetes.io/docs/concepts/storage/storage-classes/). Полная спецификация: [CSI Specification](https://github.com/container-storage-interface/spec).
