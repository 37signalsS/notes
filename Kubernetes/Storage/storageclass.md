# StorageClass

## Определения

**`StorageClass`** — объект Kubernetes, описывающий "классы" или "профили" хранилища с различными характеристиками (тип диска, зона, шифрование). Позволяет администраторам определять шаблоны для динамического выделения PV.

Подробнее о базовых концепциях PV/PVC: [PersistentVolume и PVC](./pv_and_pvc.md).

---

## Базовые концепции

### Назначение StorageClass

StorageClass абстрагирует детали инфраструктуры и позволяет разработчикам запрашивать хранилище по характеристикам, а не по конкретному типу:

- **Тип хранилища** (SSD, HDD, сетевое)
- **Provisioner** (CSI-драйвер для работы с конкретной СХД)
- **Параметры выделения** (тип диска, зона доступности, шифрование)
- **Политика возврата** (`Retain` или `Delete`)
- **Режим привязки** (`Immediate` или `WaitForFirstConsumer`)

### Ключевые параметры

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: standard-ssd
provisioner: ebs.csi.aws.com        # CSI-драйвер
parameters:
  type: gp2                         # Параметры для драйвера
reclaimPolicy: Delete               # Политика возврата
volumeBindingMode: WaitForFirstConsumer  # Режим привязки
allowVolumeExpansion: true          # Разрешить расширение
```

#### `provisioner`

Имя плагина, который создаёт физические тома. Определяет тип СХД:

| Provisioner | Тип хранилища |
|-------------|---------------|
| `kubernetes.io/aws-ebs` | AWS EBS (in-tree, legacy) |
| `ebs.csi.aws.com` | AWS EBS (CSI) |
| `rbd.csi.ceph.com` | Ceph RBD |
| `nfs.csi.k8s.io` | NFS через CSI |
| `rancher.io/local-path` | [Local Path Provisioner](./local-path-provisioner.md) |
| `cluster.local/nfs-client-provisioner` | [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md) |

#### `volumeBindingMode`

| Режим | Описание | Когда использовать |
|-------|----------|-------------------|
| `Immediate` | PV создаётся сразу при создании PVC | Простые однозонные кластеры |
| `WaitForFirstConsumer` | PV создаётся после появления пода (планирования на узел) | Многозонные кластеры, локальные хранилища |

> **Важно:** Для stateful-приложений в многозонных кластерах и для локальных хранилищ всегда используйте `WaitForFirstConsumer`. Это гарантирует, что том будет создан в той же зоне/на том же узле, где работает приложение.

#### `allowVolumeExpansion`

Разрешает увеличение размера PVC "на лету" (без удаления пода). Поддерживается не всеми CSI-драйверами.

#### `parameters`

Специфичные для provisioner параметры. Зависят от типа СХД:

- Для AWS EBS: `type`, `encrypted`, `kmsKeyId`
- Для Ceph RBD: `pool`, `clusterID`, секреты
- Для NFS: обычно не используются

---

## Практические сценарии

### Несколько классов хранилища

Типичная конфигурация для production-кластера:

```yaml
# Быстрый SSD для БД
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: ebs.csi.aws.com
parameters:
  type: io2
  iopsPerGB: "50"
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
---
# Стандартный для приложений
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: standard
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
reclaimPolicy: Delete
volumeBindingMode: Immediate
allowVolumeExpansion: true
---
# Класс по умолчанию (annotation)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: default-storage
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
reclaimPolicy: Delete
volumeBindingMode: Immediate
```

> **Важно:** Только один StorageClass может быть default в кластере. PVC без указания `storageClassName` будет использовать класс по умолчанию.

### Практические примеры использования StorageClass с конкретными СХД см. в [сценариях PV/PVC](./pv_and_pvc_scenarios.md)

---

## Дополнительная информация

Архитектура CSI: [CSI Overview](./CSI/csi_overview.md). Расширенные возможности CSI: [CSI Advanced](./CSI/csi_advanced.md). Сравнение драйверов: [CSI Drivers Comparison](./CSI/csi_drivers_comparison.md). Официальная документация: [Storage Classes](https://kubernetes.io/docs/concepts/storage/storage-classes/).
