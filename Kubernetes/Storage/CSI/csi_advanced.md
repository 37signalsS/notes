# Продвинутые возможности CSI

## Определения

**CSI Advanced Features** — это расширенный набор функций Container Storage Interface, выходящий за рамки базового жизненного цикла томов. Эти возможности позволяют реализовывать сложные стратегии резервного копирования, интеллектуальное планирование и динамическое управление ресурсами ([базовая информация](./csi_overview.md)).

Ключевые продвинутые функции:
- **Volume Snapshots** — создание мгновенных снимков состояния томов.
- **Volume Cloning** — создание независимых копий томов.
- **CSI Topology** — учёт физического расположения СХД при планировании.
- **Volume Expansion** — динамическое изменение размера томов.
- **Volume Health Monitoring** — мониторинг состояния данных и оборудования.
- **Storage Capacity Tracking** — учёт доступного пространства при планировании.
- **CSI Migration** — перевод инфраструктуры со старых встроенных плагинов на CSI.

---

## Базовые концепции

### API снапшотов томов (Volume Snapshots)

Механизм создания "снимков" состояния `PersistentVolume`. Реализуется через CSI-драйвер и стандартный Kubernetes API.

#### Ключевые компоненты
1. **`VolumeSnapshotClass`**: определяет параметры создания снапшотов (аналогично `StorageClass`).
   - `driver`: имя драйвера (например, `ebs.csi.aws.com`).
   - `deletionPolicy`: `Retain` (сохранить в СХД после удаления объекта в K8s) или `Delete`.
   - `parameters`: специфичные настройки вендора (например, тип инкрементального бэкапа).
2. **`VolumeSnapshot`**: запрос пользователя на создание снапшота конкретного PVC.
3. **`VolumeSnapshotContent`**: физический указатель на снапшот в СХД (аналог PV).

> **Требование:** В кластере должен быть развернут **snapshot-controller** и соответствующие CRD.

### Клонирование томов (Volume Cloning)

Создание новой копии существующего тома через PVC с использованием поля `dataSource`.

#### Сравнение снапшотов и клонов

| Параметр | Снапшот (Snapshot) | Клон (Clone) |
| :--- | :--- | :--- |
| **Цель** | Точка восстановления / бэкап | Независимая рабочая копия |
| **Зависимость** | Часто зависит от родительского тома в СХД | Полностью независимый том |
| **Объект в K8s** | `VolumeSnapshot` | `PersistentVolumeClaim` |
| **Использование** | Восстановление после сбоев | Тестирование на реальных данных, Fork БД |

#### Требования для клонирования
- Драйвер должен поддерживать `CREATE_DELETE_VOLUME`.
- Размер клона должен быть ≥ размера исходного тома.
- Оба PVC должны находиться в одном Namespace.

### Топология CSI (CSI Topology)

Механизм, решающий проблему "несвязанности" планировщика подов и расположения дисков в облаке или мульти-зональных кластерах.

#### Режимы volumeBindingMode

| Режим | Описание | Когда использовать |
| :--- | :--- | :--- |
| **`Immediate`** | PV создаётся сразу при появлении PVC. | Однозонные кластеры, сетевые ФС (NFS). |
| **`WaitForFirstConsumer`** | PV создаётся только после того, как под назначен на узел. | Облачные диски (EBS, GCE PD), локальные диски, Ceph RBD. |

> **Рекомендация:** Для stateful-приложений в многозонных кластерах всегда используйте `WaitForFirstConsumer`.

### Расширение томов (Volume Expansion)

Увеличение размера тома без пересоздания PVC.

#### Способы расширения
1. **Offline Expansion**: требует остановки пода (отмонтирования тома).
2. **Online Expansion**: расширение выполняется "на лету". Требует поддержки со стороны файловой системы (ext4, xfs) и CSI-драйвера.

#### Требования
- `allowVolumeExpansion: true` в `StorageClass`.
- Драйвер должен поддерживать `EXPAND_VOLUME`.

### Мониторинг здоровья томов (Volume Health Monitoring)

Позволяет Kubernetes обнаруживать аномалии на уровне данных (например, ошибки ФС или выход из строя диска в СХД).
- **External Health Monitor**: Sidecar-комтейнер, который опрашивает драйвер и генерирует Events для PVC/Pod.
- Это позволяет автоматизированным системам (например, Descheduler) реагировать на проблемы с хранилищем до того, как приложение упадет.

### Отслеживание ёмкости (Storage Capacity Tracking)

Позволяет планировщику учитывать доступное место в конкретной топологической зоне перед назначением пода.
- Актуально для локальных дисков и СХД с ограниченным объемом на узел/зону.
- Использует объекты `CSIStorageCapacity`.

### Миграция CSI (CSI Migration)

Процесс прозрачного перевода старых встроенных (in-tree) плагинов на CSI-драйверы.

> **Статус миграции (Kubernetes 1.31+):** Большинство встроенных плагинов (AWS EBS, GCP PD, Azure Disk, vSphere) полностью удалены. Kubernetes автоматически перенаправляет запросы к старым provisioner (например, `kubernetes.io/aws-ebs`) на соответствующие CSI-драйверы.
> **Важно:** Плагины Ceph RBD и CephFS полностью удалены в v1.31. Миграция для них не поддерживается — необходимо явно использовать CSI-драйверы.

---

## Практические сценарии

### Создание снапшота PVC (Ceph RBD)

```yaml
# 1. Класс для снапшотов
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: csi-rbd-snap-class
driver: rbd.csi.ceph.com
deletionPolicy: Retain
parameters:
  clusterID: rook-ceph
  csi.storage.k8s.io/snapshotter-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/snapshotter-secret-namespace: rook-ceph

---
# 2. Создание снапшота
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: pg-db-snapshot
spec:
  volumeSnapshotClassName: csi-rbd-snap-class
  source:
    persistentVolumeClaimName: postgres-data-pvc
```

### Восстановление из снапшота

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: restored-db-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ceph-rbd-ssd
  resources:
    requests:
      storage: 20Gi
  dataSource:
    name: pg-db-snapshot
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
```

### Клонирование тома

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: cloned-app-data
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: standard-ssd
  resources:
    requests:
      storage: 10Gi
  dataSource:
    name: original-app-data-pvc
    kind: PersistentVolumeClaim
```

### Расширение тома (Online Resize)

1. Обновите PVC, увеличив размер:
```bash
kubectl patch pvc my-app-pvc -p '{"spec":{"resources":{"requests":{"storage":"50Gi"}}}}'
```

2. Проверьте статус расширения:
```bash
kubectl get pvc my-app-pvc -o yaml
# Ищите в status:
# conditions:
# - type: Resizing
#   status: "True"
```

### Использование топологии (AWS EBS)

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: zonal-ebs
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer
parameters:
  type: gp3
allowedTopologies:
- matchLabelExpressions:
  - key: topology.ebs.csi.aws.com/zone
    values:
    - us-east-1a
```

---

## Дополнительная информация

### Диагностика и мониторинг

- [Сравнение и эксплуатация CSI](./csi_drivers_comparison.md) — диагностика и выбор драйверов.
- [Обзор CSI](./csi_overview.md) — архитектура и базовые понятия.
- [PV, PVC и StorageClass](../pv_and_pvc.md) — основы хранения данных в Kubernetes.
- [Концепции Ceph RBD](../Ceph/ceph_rbd_usage/definitions_and_concepts.md).
- [Концепции CephFS](../Ceph/cephfs_setup_and_usage/definitions_and_concepts.md).

### Официальные источники

- [Kubernetes Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/)
- [Storage Capacity Tracking](https://kubernetes.io/docs/concepts/storage/storage-capacity/)
- [Volume Health Monitoring](https://kubernetes.io/docs/concepts/storage/persistent-volumes/#volume-health-monitoring)
