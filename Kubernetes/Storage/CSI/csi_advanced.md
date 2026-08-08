# Продвинутые возможности CSI

## Определения

**Продвинутые возможности CSI (CSI Advanced Features)** — это расширенный набор функций Container Storage Interface, выходящий за рамки базового жизненного цикла томов (создание, удаление, монтирование). Эти возможности позволяют реализовывать сложные стратегии управления данными, такие как консистентное резервное копирование, интеллектуальное планирование с учётом топологии и проактивный мониторинг состояния хранилищ.

Ключевые продвинутые функции:
- **Volume Snapshots** — создание мгновенных снимков состояния томов через Kubernetes API.
- **Volume Cloning** — создание независимых копий существующих томов (клонов).
- **CSI Topology** — учёт физического расположения СХД (зоны, регионы) при планировании подов.
- **Volume Expansion & Performance Control** — динамическое изменение размера томов и параметров производительности (IOPS, пропускная способность).
- **Volume Health Monitoring** — обнаружение сбоев на уровне файловой системы или оборудования СХД.
- **Storage Capacity Tracking** — информирование планировщика о доступном свободном месте в конкретных зонах.
- **CSI Migration** — механизм прозрачного перевода старых встроенных плагинов на современный CSI-стек.

---

## Базовые концепции

### API снапшотов томов (Volume Snapshots)

Механизм создания "снимков" данных `PersistentVolume`. Реализуется через CSI-драйвер и стандартный Kubernetes API.

#### Ключевые компоненты
1. **snapshot-controller**: Служба Kubernetes, которая управляет объектами снапшотов.
2. **external-snapshotter (Sidecar)**: Контейнер в поде CSI-драйвера, который взаимодействует с API СХД для создания снимка.
3. **`VolumeSnapshotClass`**: Определяет параметры создания снапшотов (аналогично `StorageClass`).
   - `driver`: Имя CSI-драйвера (например, `ebs.csi.aws.com`).
   - `deletionPolicy`: `Retain` (сохранить в СХД после удаления объекта в K8s) или `Delete`.
   - `parameters`: Специфичные настройки вендора (например, тип инкрементального бэкапа).
4. **`VolumeSnapshot`**: Запрос пользователя на создание снапшота конкретного PVC.
5. **`VolumeSnapshotContent`**: Физический указатель на снапшот в СХД. Это ресурс уровня кластера (аналог PV).

### Клонирование томов (Volume Cloning)

Создание нового тома на основе существующего PVC через поле `dataSource`. В отличие от снапшота, клон создаётся как готовый к использованию `PersistentVolumeClaim`.

#### Сравнение снапшотов и клонов

| Параметр | Снапшот (Snapshot) | Клон (Clone) |
| :--- | :--- | :--- |
| **Цель** | Точка восстановления / бэкап | Независимая рабочая копия |
| **Зависимость** | Часто зависит от родительского тома в СХД | Обычно независимый (зависит от СХД) |
| **Объект в K8s** | `VolumeSnapshot` | `PersistentVolumeClaim` |
| **Использование** | Восстановление после сбоев | Тестирование, Fork БД, аналитика |

#### Требования для клонирования
- Драйвер должен поддерживать операцию `CREATE_DELETE_VOLUME` с источником.
- Размер клона должен быть **больше или равен** размеру исходного тома.
- Оба PVC (источник и клон) должны находиться в **одном Namespace**.

### Топология CSI (CSI Topology)

Решает проблему доступности данных в распределённых кластерах (например, диск AWS EBS доступен только в той зоне `Availability Zone`, где он был создан).

#### Компоненты топологии
1. **`CSINode`**: Объект, хранящий информацию о топологических метках узла (зоны, регионы).
2. **`volumeBindingMode: WaitForFirstConsumer`**: Режим в `StorageClass`, при котором PV создаётся только после того, как планировщик выбрал узел для пода. Это гарантирует, что том будет создан именно в той зоне, где запустится под.
3. **`allowedTopologies`**: Список зон/узлов в `StorageClass`, где разрешено создавать тома.

### Расширение и управление атрибутами (Volume Expansion & Attributes)

#### Динамическое расширение (Volume Expansion)
Увеличение размера тома без потери данных.
- **Online Expansion**: Выполняется на лету без остановки пода. Требует поддержки файловой системы (XFS, Ext4) и драйвера.
- **Offline Expansion**: Требует отмонтирования тома (остановки пода).

#### Volume Attributes Class (v1.31+)
Новый механизм (Beta в 1.31) для динамического изменения параметров производительности без изменения размера.
- Позволяет управлять **IOPS** и **Throughput** (пропускной способностью) через объект `VolumeAttributesClass`.
- Параметры изменяются "на лету", если CSI-драйвер поддерживает эту функцию.

### Мониторинг здоровья томов (Volume Health Monitoring)

Позволяет обнаруживать проблемы с данными (например, Read-only FS после сбоя диска), которые не видны стандартным проверкам подов.

#### Как это работает
- **external-health-monitor**: Sidecar-контейнеры (Controller и Node), которые опрашивают СХД и Kubelet.
- **События (Events)**: Если обнаружена проблема, генерируется Event **`VolumeConditionAbnormal`** для PVC (контроллером) или для Pod (через Kubelet на узле).

### Отслеживание ёмкости (Storage Capacity Tracking)

Планировщик учитывает доступный объем хранилища в конкретной зоне перед назначением пода.
- Актуально для локальных дисков (Local PV) и СХД с ограниченным ресурсом на группу узлов.
- Используются объекты **`CSIStorageCapacity`**, которые создаёт CSI-драйвер.

### Миграция CSI (CSI Migration)

Процесс перевода старых встроенных (in-tree) плагинов на внешние CSI-драйверы.

> **Статус в Kubernetes 1.31+:**
> - Большинство встроенных плагинов (**AWS EBS, GCP PD, Azure Disk, vSphere**) полностью удалены.
> - **Ceph RBD и CephFS**: Полностью удалены. Автоматическая миграция для них **не поддерживается** — переход на `ceph-csi` должен быть явным.
> - **Portworx**: Единственный драйвер, чья миграция находится в Alpha.

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
      storage: 20Gi # Должно быть >= размера снапшота
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

### Управление производительностью (VolumeAttributesClass)

```yaml
apiVersion: storage.k8s.io/v1alpha1
kind: VolumeAttributesClass
metadata:
  name: high-iops-profile
driverName: ebs.csi.aws.com
parameters:
  type: gp3
  iops: "5000"
  throughput: "250"
```

Применение к PVC:
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: db-pvc
spec:
  volumeAttributesClassName: high-iops-profile
  # ...
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

## Диагностика и мониторинг

### Мониторинг событий здоровья
Проверка наличия проблем с томами через события:
```bash
kubectl get events --field-selector involvedObject.kind=PersistentVolumeClaim
# Ищите событие: VolumeConditionAbnormal
```

### Проблемы планирования (Topology)
Если под висит в `Pending` с ошибкой `node(s) had volume node affinity conflict`:
1. Проверьте зоны в `StorageClass.allowedTopologies`.
2. Проверьте метки на узлах: `kubectl get nodes --show-labels`.
3. Убедитесь, что PV имеет корректный `nodeAffinity`.

---

## Дополнительная информация

### Ссылки на связанные темы
- [Обзор CSI](./csi_overview.md) — архитектура и базовые компоненты.
- [Сравнение CSI-драйверов](./csi_drivers_comparison.md) — возможности драйверов (Longhorn, Ceph, Cloud).
- [PV, PVC и StorageClass](../pv_and_pvc.md) — базовые операции с томами.
- [Обзор Ceph](../Ceph/ceph_overview.md) — общая информация о системе Ceph.

### Официальные источники
- [Kubernetes: Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/)
- [Kubernetes: Storage Capacity Tracking](https://kubernetes.io/docs/concepts/storage/storage-capacity/)
- [Kubernetes: Volume Health Monitoring](https://kubernetes.io/docs/concepts/storage/persistent-volumes/#volume-health-monitoring)
- [CSI Migration Guide](https://kubernetes.io/docs/concepts/storage/volumes/#csi-migration)
