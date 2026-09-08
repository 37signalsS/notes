# StatefulSet: Local PV vs hostPath vs CSI — выбор хранилища для БД

## Определения

**Local PV vs hostPath vs CSI** — сравнительный анализ трёх типов хранения данных в Kubernetes, используемых с StatefulSet для баз данных и распределённых систем. Выбор типа хранилища определяет производительность, отказоустойчивость и стоимость развертывания.

## Предварительные требования

1.  Понимание PV/PVC: **[PV и PVC](../../Storage/pv_and_pvc.md)**.
2.  StorageClass: **[StorageClass](../../Storage/storageclass.md)**.
3.  CSI-драйверы: **[CSI — сравнение драйверов](../../Storage/CSI/csi_drivers_comparison.md)**.
4.  StatefulSet: **[Ключевые концепции](./statefulset_core_concepts.md)**.

## Основные концепции

### Сравнительная таблица

| Критерий | hostPath | Local Persistent Volume | CSI (сетевой/блочный) |
|:---|:---|:---|:---|
| **Тип** | Эфемерный том пода | Персистентный PV, привязанный к узлу | Персистентный PV через CSI-драйвер |
| **Динамический провижининг** | Нет | Да (local-path-provisioner) | Да (Ceph, Longhorn, NFS, cloud) |
| **Персистентность** | Только пока жив под | Сохраняется при перезапуске пода на том же узле | Сохраняется независимо от узла |
| **Миграция между узлами** | Нет | Нет (данные привязаны к физическому диску) | Да (при volumeBindingMode: WaitForFirstConsumer) |
| **Производительность** | Максимальная (нет overhead) | Максимальная (nativ disk I/O) | Зависит от драйвера (NFS: низкая, Ceph RBD: средняя, NVMe-TCP: высокая) |
| **Multi-Attach** | Невозможен | Невозможен (RWO) | Зависит от драйвера (RWO/RWX) |
| **Снапшоты** | Нет | Нет | Да (CSI VolumeSnapshot) |
| **Расширение диска** | Нет | Нет (только пересоздание) | Да (allowVolumeExpansion) |
| **Cluster Autoscaler** | Не работает (узел зафиксирован) | Не работает (`--skip-nodes-with-local-storage`) | Работает |
| **Защита данных** | Нет (данные теряются при удалении пода) | Частичная (данные живут, пока жив узел) | Полная (при reclaimPolicy: Retain) |
| **Стоимость** | $0 (использует диск узла) | $0–$ (локальный NVMe/SSD узла) | $$–$$$ (сетевое хранилище) |

### hostPath — когда использовать

**Определение:** Простой том, монтирующий директорию хоста в контейнер. Данные хранятся на локальном диске узла и **теряются** при удалении пода (если под не пересоздаётся на том же узле).

**Допустимые сценарии для StatefulSet:**
- Тестовые/dev-окружения, где потеря данных допустима
- Временные кэши и промежуточные данные (Redis, Memcached)
- etcd-поды control plane (но не пользовательские workload'ы)

**Недопустимые сценарии:**
- Production-БД: потеря данных при `kubectl delete pod` или сбое узла
- БД с требованием High Availability: нет механизма переноса данных
- Кластер с Cluster Autoscaler: узлы с hostPath не могут быть удалены

**Пример манифеста (НЕ рекомендуется для production):**

```yaml
spec:
  containers:
  - name: postgres
    volumeMounts:
    - name: data
      mountPath: /var/lib/postgresql/data
  volumes:
  - name: data
    hostPath:
      path: /data/postgres
      type: DirectoryOrCreate
```

### Local Persistent Volume — когда использовать

**Определение:** Персистентный PV, который ссылается на локальный диск узла. В отличие от hostPath, это полноценный PV с динамическим провижинингом и привязкой к узлу через `nodeAffinity`. Данные переживают перезапуск пода (если под планируется на тот же узел), но **не мигрируют** между узлами.

**Допустимые сценарии для StatefulSet:**
- **OLTP-БД с высокой IOPS** (PostgreSQL, MySQL) — локальные NVMe/SSD дают минимальную латентность
- **Kafka** — брокеры привязаны к дискам, репликация на уровне приложения
- **Cassandra** — данные реплицируются между узлами, локальный диск оптимален
- **etcd** — кластер etcd с локальными NVMe

**Ограничения:**
- **Нет миграции**: при падении узла под не переносится автоматически (как и StatefulSet по умолчанию)
- **Cluster Autoscaler**: узлы с local PV не могут быть удалены (`--skip-nodes-with-local-storage`)
- **Нет снапшотов**: CSI VolumeSnapshot недоступен для локальных дисков
- **Ручное восстановление**: при выходе узла из строя данные на этом диске недоступны до его возврата

**Пример с local-path-provisioner:**

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-fast
provisioner: rancher.io/local-path
volumeBindingMode: WaitForFirstConsumer  # Обязательно для local PV
reclaimPolicy: Retain                     # Retain для production-БД
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: postgres
  replicas: 3
  template:
    spec:
      containers:
      - name: postgres
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: local-fast
      resources:
        requests:
          storage: 50Gi
```

**Важно:** `volumeBindingMode: WaitForFirstConsumer` гарантирует, что диск создаётся в той же зоне/узле, куда планируется под. Без этого под может застрять в `Pending` (AZ mismatch).

### CSI (сетевой/блочный) — когда использовать

**Определение:** ПерсистентныйPV, создаваемый через Container Storage Interface (CSI) драйвер. Поддерживает динамический провижининг, снапшоты, расширение, миграцию между узлами.

**Допустимые сценарии для StatefulSet:**
- **Production-БД с требованием HA**: Ceph RBD, Longhorn, Portworx — данные реплицируются между узлами/зонами
- **Мультизональные кластеры**: данные доступны из любой зоны
- **Бэкапы через снапшоты**: CSI VolumeSnapshot для consistent backup
- **NFS/共享存储**: если нужен RWX-доступ (но это rare для БД)

**Популярные CSI-драйверы для StatefulSet:**

| Драйвер | Тип | Производительность | Снапшоты | Расширение | Use-case |
|:---|:---|:---|:---|:---|:---|
| **Ceph RBD** | Блочный | Средняя–Высокая | Да | Да | HA-кластеры, мультизональные |
| **Longhorn** | Блочный | Средняя | Да | Да | Гиперконвергентные кластеры |
| **OpenEBS (cStor)** | Блочный | Средняя | Да | Да | Гиперконвергентные кластеры |
| **NFS (nfs-csi)** | Файловый | Низкая | Нет | Да | Общий доступ (RWX) |
| **AWS EBS** | Блочный | Высокая | Да | Да | Кластеры в AWS |
| **GCE PD** | Блочный | Высокая | Да | Да | Кластеры в GCP |
| **Azure Disk** | Блочный | Высокая | Да | Да | Кластеры в Azure |
| **Local PV (CSI)** | Локальный | Максимальная | Нет | Нет | Высокопроизводительные БД |

**Пример с Ceph RBD:**

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-block
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: <ceph-cluster-id>
  pool: kubernetes
  imageFeatures: layering
  csi.storage.k8s.io/provisioner-secret-name: csi-rbd-secret
  csi.storage.k8s.io/provisioner-secret-namespace: default
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
allowVolumeExpansion: true
```

### Алгоритм выбора для DevOps/SRE

```
Нужна production-БД?
├── Да
│   ├── Данные реплицируются на уровне приложения (Kafka, Cassandra)?
│   │   ├── Да → Local Persistent Volume (максимальная IOPS)
│   │   └── Нет → CSI (Ceph/Longhorn) для автоматической репликации
│   ├── Нужны снапшоты/бэкапы?
│   │   ├── Да → CSI (только CSI поддерживает VolumeSnapshot)
│   │   └── Нет → Local PV (дешевле)
│   └── Кластер мультизональный?
│       ├── Да → CSI с zone-aware provisioning
│       └── Нет → Local PV или CSI
└── Нет (dev/test)
    └── hostPath или local-path-provisioner (дешевле всего)
```

### Практические сценарии

#### Сценарий 1: PostgreSQL на NVMe (OLTP, высокая IOPS)

Цель: максимальная производительность для транзакционной нагрузки.

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nvme-local
provisioner: rancher.io/local-path
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres-oltp
spec:
  serviceName: postgres
  replicas: 3
  podManagementPolicy: OrderedReady
  template:
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app: postgres
            topologyKey: kubernetes.io/hostname  # По одному поду на NVMe-узел
      containers:
      - name: postgres
        image: postgres:16
        env:
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        resources:
          requests:
            cpu: "2"
            memory: "8Gi"
          limits:
            cpu: "4"
            memory: "16Gi"
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: nvme-local
      resources:
        requests:
          storage: 100Gi
```

**Почему Local PV:** PostgreSQL — транзакционная СУБД, где латентность диска критична. Local NVMe даёт <100μs latency vs 1-5ms для сетевого Ceph. Репликация — на уровне PostgreSQL (streaming replication через Patroni), а не CSI.

#### Сценарий 2: Kafka с Strimzi (высокопроизводительные брокеры)

Цель: максимальная пропускная способность для записи/чтения сообщений.

```yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: Kafka
metadata:
  name: production
spec:
  kafka:
    replicas: 3
    storage:
      type: jbod
      volumes:
      - id: 0
        type: persistent-claim
        size: 500Gi
        class: nvme-local  # Local NVMe
        deleteClaim: false
    config:
      default.replication.factor: 3
      min.insync.replicas: 2
  zookeeper:
    replicas: 3
    storage:
      type: persistent-claim
      size: 50Gi
      class: nvme-local
      deleteClaim: false
```

**Почему Local PV:** Kafka реплицирует данные между брокерами (replication factor). Локальный диск даёт максимальную пропускную способность. При падении узла Kafka восстанавливает данные из реплик.

#### Сценарий 3: PostgreSQL с High Availability (Ceph RBD)

Цель: автоматическое восстановление при падении узла.

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-ha
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: <ceph-id>
  pool: ha-pool
  imageFeatures: layering,exclusive-lock,deep-flatten
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
allowVolumeExpansion: true
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres-ha
spec:
  serviceName: postgres
  replicas: 3
  template:
    spec:
      containers:
      - name: postgres
        image: postgres:16
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: ceph-ha
      resources:
        requests:
          storage: 100Gi
```

**Почему CSI (Ceph):** при падении узла Ceph автоматически восстанавливает данные из副本 (replication factor ≥ 3). Под StatefulSet пересоздаётся на другом узле и монтирует тот же PV через Ceph. Данные доступны немедленно.

### Частые ошибки

1. **hostPath в production** — потеря данных при удалении пода или падении узла.
2. **Local PV без `WaitForFirstConsumer`** — под может застрять в `Pending` (AZ mismatch).
3. **CSI без `reclaimPolicy: Retain`** — при удалении PVC данные уничтожаются.
4. **Local PV + Cluster Autoscaler** — autoscaler не может удалить узел с local PV, что приводит к дефициту ресурсов.
5. **NFS для OLTP-БД** — низкая производительность, не подходит для транзакционных нагрузок.
6. **Отсутствие anti-affinity** — все поды БД оказываются на одном узле, при его падении кворум теряется.

## Дополнительная информация

### Ссылки на 관련 разделы

*   **[StorageClass](../../Storage/storageclass.md)** — параметры и настройка.
*   **[PV и PVC](../../Storage/pv_and_pvc.md)** — жизненный цикл томов.
*   **[CSI — сравнение драйверов](../../Storage/CSI/csi_drivers_comparison.md)** — capabilities CSI-драйверов.
*   **[local-path-provisioner](../../Storage/local-path-provisioner.md)** — динамический провижининг для local PV.
*   **[Лучшие практики StatefulSet](./statefulset_best_practices.md)** — выбор StorageClass для БД.
*   **[Volume Types](../../Base/Pod/volume_types/volume_types.md)** — типы томов в Kubernetes.

### Рекомендации по выбору

| Тип БД | Рекомендуемое хранилище | Причина |
|:---|:---|:---|
| PostgreSQL (OLTP) | Local NVMe + Patroni | Минимальная латентность, репликация на уровне приложения |
| PostgreSQL (HA) | Ceph RBD / Longhorn | Автоматическое восстановление при падении узла |
| MySQL (Galera) | Local NVMe | Репликация на уровне Galera |
| MongoDB Replica Set | Local NVMe или Ceph RBD | Репликация на уровне MongoDB |
| Kafka | Local NVMe | Максимальная пропускная способность, репликация на уровне Kafka |
| RabbitMQ (Quorum Queues) | Local NVMe или Ceph RBD | Репликация на уровне RabbitMQ |
| Cassandra | Local NVMe | Репликация на уровне Cassandra |
| Elasticsearch | Ceph RBD / Longhorn | Репликация на уровне ES, снапшоты |
| ZooKeeper / etcd | Local NVMe | Минимальная латентность для consensus |
