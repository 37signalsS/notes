# Паттерны хранения для баз данных в Kubernetes

## Определения

**Database Storage Patterns** — проверенные архитектурные решения по организации персистентного хранилища для реляционных и нереляционных баз данных в контейнеризированной среде. Включают выбор типа хранилища, тюнинг файловой системы, размещение компонентов и стратегии резервного копирования.

**OLTP (Online Transaction Processing)** — транзакционные нагрузки с высокими требованиями к IOPS и низкой задержкой (PostgreSQL, MySQL, MariaDB). Критична random 4K read/write производительность.

**OLAP (Online Analytical Processing)** — аналитические нагрузки с преобладанием sequential read/write (ClickHouse, BigQuery). Критична throughput, а не IOPS.

**WAL (Write-Ahead Log)** — журнал транзакций реляционных БД. Является наиболее узким местом производительности: каждая транзакция требует fsync в WAL перед коммитом.

**Связанные темы:**
- [StatefulSet — ядро концепций](../Base/StatefulSet/statefulset_core_concepts.md) — volumeClaimTemplates.
- [StatefulSet — практическое руководство](../Base/StatefulSet/statefulset_practical_guide.md) — изменение размера томов.
- [StatefulSet — Local PV vs CSI](../Base/StatefulSet/statefulset_local_pv_vs_csi.md) — выбор хранилища.
- [Storage Decision Matrix](./storage-decision-matrix.md) — выбор хранилища.
- [Storage Performance Testing](./storage-performance-testing.md) — тестирование IOPS.

---

## Теоретический блок

### Требования разных БД к storage

| БД | Тип нагрузки | Мин. IOPS (4K) | Требования к латентности | Access Mode | Особенности |
|:---|:---|:---|:---|:---|:---|
| **PostgreSQL** | OLTP | 10,000+ | p99 < 5ms | RWO | WAL fsync критичен, нужен fsGroup |
| **MySQL (InnoDB)** | OLTP | 10,000+ | p99 < 5ms | RWO | doublewrite buffer, redo log |
| **MariaDB** | OLTP | 10,000+ | p99 < 5ms | RWO | Аналогично MySQL |
| **MongoDB** | Mixed | 5,000+ | p99 < 10ms | RWO | journal, WiredTiger cache |
| **Redis** | Extreme OLTP | 50,000+ | p99 < 1ms | RWO | AOF fsync, RDB snapshots |
| **ClickHouse** | OLAP | 5,000+ | p99 < 50ms | RWO | MergeTree, bulk writes |
| **Elasticsearch** | Mixed | 5,000+ | p99 < 10ms | RWO | Множество индексов, segment merges |
| **Kafka** | Sequential write | 5,000+ | p99 < 10ms | RWO | Log segments, high throughput |

### Паттерны размещения компонентов

| Паттерн | Описание | Когда использовать |
|:---|:---|:---|
| **Single Volume** | Все данные в одном PVC | Dev/Test, маленькие БД |
| **Data + WAL на разных томах** | WAL на быстром SSD, данные на основном хранилище | Production PostgreSQL/MySQL |
| **Data + Logs на разных томах** | Логи приложения отдельно от данных | Production, высокая нагрузка |
| **Replicated (operator)** | Оператор управляет репликацией | Production кластеры БД |
| **Local NVMe** | Данные на локальном NVMe узла | Максимальная производительность |

---

## Практический блок

### 1. PostgreSQL: Production-ready конфигурация

#### StorageClass для PostgreSQL

```yaml
# Быстрый SSD для WAL ( high IOPS, low latency)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: postgres-wal
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: <ceph-cluster-id>
  pool: fast-ssd
  csi.storage.k8s.io/provisioner-secret-name: ceph-secret
  csi.storage.k8s.io/provisioner-secret-namespace: default
reclaimPolicy: Retain
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
---
# Основной том для данных
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: postgres-data
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: <ceph-cluster-id>
  pool: ssd-data
  csi.storage.k8s.io/provisioner-secret-name: ceph-secret
  csi.storage.k8s.io/provisioner-secret-namespace: default
reclaimPolicy: Retain
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
```

#### StatefulSet с разделёнными томами

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgresql
spec:
  serviceName: postgresql
  replicas: 3
  selector:
    matchLabels:
      app: postgresql
  template:
    metadata:
      labels:
        app: postgresql
    spec:
      securityContext:
        fsGroup: 999         # postgres user group
        fsGroupChangePolicy: OnRootMismatch
      containers:
      - name: postgres
        image: postgres:16
        env:
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secret
              key: password
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
        - name: wal
          mountPath: /var/lib/postgresql/wal
        resources:
          requests:
            cpu: "1"
            memory: 2Gi
          limits:
            cpu: "4"
            memory: 8Gi
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ReadWriteOnce]
      storageClassName: postgres-data
      resources:
        requests:
          storage: 100Gi
  - metadata:
      name: wal
    spec:
      accessModes: [ReadWriteOnce]
      storageClassName: postgres-wal
      resources:
        requests:
          storage: 20Gi
```

#### Конфигурация PostgreSQL для K8s

```sql
-- postgresql.conf (через ConfigMap или параметры environment)

-- WAL на отдельном томе
wal_level = replica
wal_dir = '/var/lib/postgresql/wal'
max_wal_size = '10GB'
min_wal_size = '1GB'

-- Оптимизации для SSD
random_page_cost = 1.1          -- SSD: минимум random access penalty
effective_io_concurrency = 200  -- SSD: параллельные I/O
effective_cache_size = '6GB'    -- 75% от RAM

-- fsync и durability
fsync = on                      -- ОБЯЗАТЕЛЬНО для данных
synchronous_commit = on
wal_sync_method = fdatasync

-- Чекпоинт
checkpoint_timeout = '15min'
checkpoint_completion_target = 0.9
```

### 2. MySQL: Production-ready конфигурация

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mysql
spec:
  serviceName: mysql
  replicas: 3
  selector:
    matchLabels:
      app: mysql
  template:
    spec:
      securityContext:
        fsGroup: 999
        fsGroupChangePolicy: OnRootMismatch
      containers:
      - name: mysql
        image: mysql:8.0
        env:
        - name: MYSQL_ROOT_PASSWORD
          valueFrom:
            secretKeyRef:
              name: mysql-secret
              key: root-password
        volumeMounts:
        - name: data
          mountPath: /var/lib/mysql
        resources:
          requests:
            cpu: "1"
            memory: 2Gi
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ReadWriteOnce]
      storageClassName: postgres-data  # Тот же fast-ssd
      resources:
        requests:
          storage: 100Gi
```

```ini
# my.cnf (через ConfigMap)

[mysqld]
# InnoDB optimizations
innodb_buffer_pool_size = 6G        # 75% от RAM
innodb_buffer_pool_instances = 4
innodb_log_file_size = 1G
innodb_flush_log_at_trx_commit = 1  # fsync каждый коммит (durability)
innodb_flush_method = O_DIRECT       # Минимизация кэширования ОС

# I/O
innodb_io_capacity = 10000          # SSD IOPS
innodb_io_capacity_max = 20000

# Replication
server-id = 1
log_bin = mysql-bin
binlog_format = ROW
gtid_mode = ON
```

### 3. MongoDB: Production-ready конфигурация

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mongodb
spec:
  serviceName: mongodb
  replicas: 3
  selector:
    matchLabels:
      app: mongodb
  template:
    spec:
      containers:
      - name: mongodb
        image: mongo:7.0
        command:
        - mongod
        - --replSet
        - rs0
        - --bind_ip_all
        - --wiredTigerCacheSizeGB
        - "4"                    # 50% от RAM
        volumeMounts:
        - name: data
          mountPath: /data/db
        - name: journal
          mountPath: /data/journal
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ReadWriteOnce]
      storageClassName: postgres-data
      resources:
        requests:
          storage: 200Gi
  - metadata:
      name: journal
    spec:
      accessModes: [ReadWriteOnce]
      storageClassName: postgres-wal  # Быстрый SSD для journal
      resources:
        requests:
          storage: 10Gi
```

### 4. Паттерн: WAL на tmpfs (максимальная скорость)

Для PostgreSQL/MySQL — WAL-файл на tmpfs (RAM-disk):

```yaml
containers:
- name: postgres
  volumeMounts:
  - name: data
    mountPath: /var/lib/postgresql/data
  - name: wal-tmpfs
    mountPath: /var/lib/postgresql/wal
volumes:
- name: data
  persistentVolumeClaim:
    claimName: postgres-data
- name: wal-tmpfs
  emptyDir:
    medium: Memory
    sizeLimit: 2Gi
```

**Важно:** WAL на tmpfs безопасен только при наличии репликации (streaming replication или Ceph RBD replica ≥ 2). При потере узла WAL-данные на tmpfs теряются.

### 5. Миграция данных между PVC (rsync)

```bash
# 1. Запустить под с двумя PVC
kubectl run migration --rm -it --image=alpine --overrides='{
  "spec": {
    "containers": [{
      "name": "migration",
      "image": "alpine",
      "command": ["sh", "-c", "apk add rsync && rsync -avP /source/ /dest/"],
      "volumeMounts": [
        {"name": "source", "mountPath": "/source"},
        {"name": "dest", "mountPath": "/dest"}
      ]
    }],
    "volumes": [
      {"name": "source", "persistentVolumeClaim": {"claimName": "old-data"}},
      {"name": "dest", "persistentVolumeClaim": {"claimName": "new-data"}}
    ]
  }
}'

# 2. После завершения: переключить поды на новый PVC
```

---

## Дополнительная информация

### Чеклист: Production БД в K8s

- [ ] StorageClass с `allowVolumeExpansion: true`
- [ ] `volumeBindingMode: WaitForFirstConsumer` для локальных/拓扑-aware хранилищ
- [ ] `reclaimPolicy: Retain` для production данных
- [ ] Разделение WAL/journal и данных на разных типах дисков
- [ ] `fsGroup` установлен для пользователя БД
- [ ] `fsGroupChangePolicy: OnRootMismatch` для минимизации chmod
- [ ] Ресурсы (CPU/RAM) заданы явно
- [ ] Логические дампы (pg_dump, mysqldump) настроены
- [ ] CSI Snapshots или Velero бэкапы настроены
- [ ] Тестовое восстановление выполнено

### См. также

- [StatefulSet — ядро концепций](../Base/StatefulSet/statefulset_core_concepts.md) — volumeClaimTemplates.
- [StatefulSet — Local PV vs CSI](../Base/StatefulSet/statefulset_local_pv_vs_csi.md) — выбор хранилища.
- [Storage Decision Matrix](./storage-decision-matrix.md) — выбор хранилища.
- [Velero](../ToolsUtilities/velero-overview.md) — бэкап и восстановление.
- [PostgreSQL Operator (Zalando)](../../Databases/PostgreSQL/Operations/zalando_spilo_manifests.md) — оператор PostgreSQL.
