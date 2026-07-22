# Практические сценарии использования PV и PVC

## Определения

В данном файле собраны практические примеры использования `PersistentVolume` (PV) и `PersistentVolumeClaim` (PVC) для различных типов систем хранения данных (СХД) и сценариев развертывания приложений.

Базовые концепции и теория: [Persistent Volumes и PVC](./pv_and_pvc.md).
Настройка классов хранения: [StorageClass](./storageclass.md).

---

## Сценарии использования

### Динамическое выделение: Ceph RBD

Сценарий использования блочного хранилища Ceph через CSI-драйвер. Подходит для баз данных и приложений, требующих высокой производительности (RWO).

```yaml
# 1. StorageClass для Ceph RBD
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-ssd
provisioner: rbd.csi.ceph.com
parameters:
  pool: replicapool
  clusterID: rook-ceph
  csi.storage.k8s.io/provisioner-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/provisioner-secret-namespace: rook-ceph
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true

---
# 2. Запрос на выделение (PVC)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: database-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ceph-ssd
  resources:
    requests:
      storage: 20Gi

---
# 3. Подключение к Поду
apiVersion: v1
kind: Pod
metadata:
  name: postgres-db
spec:
  containers:
    - name: postgres
      image: postgres:15
      volumeMounts:
        - name: db-data
          mountPath: /var/lib/postgresql/data
  volumes:
    - name: db-data
      persistentVolumeClaim:
        claimName: database-pvc
```

**Ключевые моменты:**
- `reclaimPolicy: Retain` гарантирует, что при случайном удалении PVC данные в Ceph останутся целыми.
- `volumeBindingMode: WaitForFirstConsumer` критически важен, чтобы диск был создан в той же зоне доступности, где будет запущен Под.

### Статическое выделение: NFS

Используется для интеграции с существующими файловыми серверами. Администратор вручную описывает параметры подключения.

```yaml
# 1. PV (создается администратором)
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs-shared-pv
spec:
  capacity:
    storage: 100Gi
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  nfs:
    path: /export/k8s-data
    server: 10.0.0.50

---
# 2. PVC (создается разработчиком)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: web-content-pvc
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 50Gi # Может быть меньше или равно объему PV
```

**Пояснения:**
- NFS поддерживает `ReadWriteMany` (RWX), что позволяет многим подам одновременно читать и писать в одну директорию.
- При статическом выделении PVC "связывается" с подходящим по параметрам PV автоматически.

### Deployment с общим хранилищем (RWX)

Стандартный подход для веб-серверов, которым нужен общий доступ к статическим файлам или общая директория для загрузки файлов.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-cluster
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
        image: nginx:latest
        volumeMounts:
        - name: shared-html
          mountPath: /usr/share/nginx/html
      volumes:
      - name: shared-html
        persistentVolumeClaim:
          claimName: web-content-pvc # PVC должен поддерживать RWX
```

**Риски RWX:**
- **Блокировки:** Сама файловая система NFS не управляет конкурентным доступом на уровне файлов. Приложение должно самостоятельно обрабатывать возможные race conditions.
- **Производительность:** Большое количество клиентов к одному NFS-серверу может создать "бутылочное горлышко" по сети.

### StatefulSet: Индивидуальное хранилище для каждой реплики

Для систем, где каждая реплика должна иметь свои уникальные данные (Prometheus, ElasticSearch, Kafka).

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis-cluster
spec:
  serviceName: "redis"
  replicas: 3
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        volumeMounts:
        - name: data
          mountPath: /data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: "ceph-ssd"
      resources:
        requests:
          storage: 5Gi
```

**Особенности работы:**
- `volumeClaimTemplates` автоматически создает PVC для каждой реплики с именами `data-redis-0`, `data-redis-1` и т.д.
- При удалении StatefulSet его PVC **не удаляются** автоматически. Это механизм защиты от потери данных.

---

## Дополнительная информация

- Хранилище на локальных дисках: [Local Path Provisioner](./local-path-provisioner.md).
- Интеграция с Ceph: [Обзор Ceph](./Ceph/ceph_overview.md).
- Работа с Longhorn: [Longhorn — установка и настройка](./longhorn.md).
- Основы StatefulSet: [Концепции StatefulSet](../Base/StatefulSet/statefulset_core_concepts.md).
