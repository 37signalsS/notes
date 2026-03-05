# Продвинутые возможности CSI

## Определения

**CSI Advanced Features** — расширенные возможности Container Storage Interface, выходящие за рамки базового управления томами: снапшоты, клонирование, учёт топологии, расширение томов и миграция с in-tree плагинов.

> **Базовая информация:** [Container Storage Interface (CSI)](./csi_overview.md)

---

## Volume Snapshots API

**Volume Snapshot** — механизм создания "снимков" состояния `PersistentVolume` на определённый момент времени. Реализуется через CSI-драйвер и стандартный Kubernetes API.

### Ключевые компоненты

1. **`VolumeSnapshotClass`** — определяет параметры создания снапшотов (аналогично `StorageClass`). Содержит:
   - `driver` — имя CSI-драйвера (например, `ebs.csi.aws.com`, `rbd.csi.ceph.com`)
   - `deletionPolicy` — политика удаления снапшота (`Retain` или `Delete`)
   - `parameters` — специфичные параметры СХД

2. **`VolumeSnapshot`** — ресурс, описывающий запрос на создание снапшота конкретного PVC.

3. **`VolumeSnapshotContent`** — низкоуровневый объект, представляющий снапшот в системе хранения (аналог PV для PVC).

### Сценарии использования

- **Резервное копирование:** Быстрое создание точки восстановления перед обновлением приложения.
- **Клонирование данных:** Создание нового PVC из снапшота для тестирования или аналитики.
- **Миграция данных:** Перенос данных между кластерами через экспорт снапшотов.

### Пример создания снапшота

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
# PVC, созданный из снапшота
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

> **Важно:** Для работы Volume Snapshots в кластере должен быть установлен **snapshot controller** и соответствующий CSI-драйвер с поддержкой `CREATE_DELETE_SNAPSHOT`.

### Пример: Ceph RBD с Volume Snapshots

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
allowVolumeExpansion: true  # Включаем расширение томов
reclaimPolicy: Retain        # Сохраняем данные после удаления PVC

---
# VolumeSnapshotClass для RBD
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: ceph-rbd-snap
driver: rbd.csi.ceph.com
deletionPolicy: Retain
parameters:
  clusterID: rook-ceph

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

---

## Volume Cloning

**Volume Cloning** — создание новой копии существующего `PersistentVolume` через PVC. Реализуется нативно через поле `dataSource` в спецификации PVC.

### Отличие от снапшотов

| Параметр | Снапшот | Клон |
| :--- | :--- | :--- |
| **Цель** | Точка восстановления | Независимый том |
| **Зависимость** | Исходный PVC должен существовать | После создания независим |
| **Использование** | Восстановление, бэкап | Тестирование, аналитика, fork |

### Пример клонирования тома

```yaml
# Клонирование существующего PVC
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

### Требования для клонирования

- CSI-драйвер должен поддерживать `CREATE_DELETE_VOLUME`
- Размер клона должен быть больше или равен размеру исходного тома
- Оба PVC должны быть в одном namespace (ограничение Kubernetes)

---

## CSI Topology

**CSI Topology** — механизм учёта физического расположения томов при планировании подов. Критично для распределённых систем и облачных окружений с зонами доступности.

### Проблема

В облачных окружениях диск привязан к конкретной зоне доступности (AZ). Если под запланирован в другой зоне — он не сможет подключить том.

### Решение

CSI-драйвер сообщает Kubernetes о топологии доступных томов через `TopologyKeys`. Планировщик учитывает это при размещении подов.

### Пример StorageClass с учётом топологии

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: zonal-ssd
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer  # Критично для топологии
allowedTopologies:
  - matchLabelExpressions:
      - key: topology.ebs.csi.aws.com/zone
        values:
          - eu-central-1a
          - eu-central-1b
```

### Режимы volumeBindingMode

| Режим | Описание | Когда использовать |
| :--- | :--- | :--- |
| `Immediate` | PV создаётся сразу при создании PVC | Однозонные кластеры, stateless-приложения |
| `WaitForFirstConsumer` | PV создаётся после появления пода | Многозонные кластеры, stateful-приложения |

> **Рекомендация:** Для stateful-приложений в многозонных кластерах всегда используйте `WaitForFirstConsumer`.

---

## Volume Expansion (Расширение томов)

**Volume Expansion** — увеличение размера `PersistentVolume` без потери данных. Поддерживается двумя способами:

1. **Offline Expansion:** Том должен быть отмонтирован (под остановлен)
2. **Online Expansion:** Расширение "на лету" без остановки приложения (требует поддержки ФС и CSI-драйвера)

### Пример расширения

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

### Требования

- `StorageClass` должен иметь `allowVolumeExpansion: true`
- CSI-драйвер должен поддерживать `EXPAND_VOLUME`
- Для online expansion файловая система должна поддерживать resize (ext4, xfs)

### Проверка поддержки

```bash
kubectl get storageclass standard-ssd -o yaml | grep allowVolumeExpansion
# allowVolumeExpansion: true
```

---

## CSI Migration

**CSI Migration** — процесс перевода встроенных (in-tree) плагинов хранения на внешние (out-of-tree) CSI-драйверы.

### Контекст

До Kubernetes 1.24 многие плагины хранения (AWS EBS, GCE PD, Azure Disk, vSphere) были встроены в код Kubernetes. Начиная с версии 1.24, большинство in-tree плагинов удалены, и их использование автоматически перенаправляется на соответствующие CSI-драйверы.

### Механизм работы

- **`CSIMigration` feature gate:** Включает автоматическую трансляцию in-tree `StorageClass` в CSI-эквиваленты
- **Автоматическая совместимость:** Существующие манифесты с in-tree плагинами продолжают работать без изменений

### Пример миграции AWS EBS

```yaml
# До миграции (in-tree)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: standard
provisioner: kubernetes.io/aws-ebs  # In-tree плагин

# После миграции (автоматически транслируется в)
provisioner: ebs.csi.aws.com  # CSI драйвер
```

### Статус миграции (Kubernetes 1.25+)

| In-tree плагин | CSI замена | Статус |
| :--- | :--- | :--- |
| `kubernetes.io/aws-ebs` | `ebs.csi.aws.com` | ✅ |
| `kubernetes.io/gce-pd` | `pd.csi.storage.gke.io` | ✅ |
| `kubernetes.io/azure-disk` | `disk.csi.azure.com` | ✅ |
| `kubernetes.io/cinder` | `cinder.csi.openstack.org` | ✅ |
| `kubernetes.io/vsphere-volume` | `csi.vsphere.vmware.com` | ✅ |
| `kubernetes.io/portworx-volume` | `pxd.portworx.com` | ✅ |

> **Важно:** Для Kubernetes 1.24+ рекомендуется явно использовать CSI-драйверы в манифестах.

---

## Связанные темы

- **Базовая информация:** [Container Storage Interface (CSI)](./csi_overview.md)
- **PV и PVC:** [Хранение данных: PV, PVC и StorageClass](../pv_and_pvc.md)
