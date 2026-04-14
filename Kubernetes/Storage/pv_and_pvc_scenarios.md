# PV/PVC Practical Scenarios

## Определения

Практические примеры использования PersistentVolume и PersistentVolumeClaim с различными типами хранилищ.

Базовые концепции: [PersistentVolume и PVC](./pv_and_pvc.md). StorageClass: [StorageClass](./storageclass.md).

---

## Практические сценарии

### Динамическое выделение: Ceph RBD

```yaml
# 1. StorageClass
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
# 2. PersistentVolumeClaim
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-app-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ceph-ssd
  resources:
    requests:
      storage: 10Gi

---
# 3. Pod с PVC
apiVersion: v1
kind: Pod
metadata:
  name: my-app-pod
spec:
  containers:
    - name: my-app
      image: nginx
      volumeMounts:
        - name: my-storage
          mountPath: /usr/share/nginx/html
  volumes:
    - name: my-storage
      persistentVolumeClaim:
        claimName: my-app-pvc
```

**Пояснения:**

- `reclaimPolicy: Retain` — данные сохраняются после удаления PVC (production).
- `volumeBindingMode: WaitForFirstConsumer` — PV создаётся после планирования пода (важно для RBD, который привязан к узлу).
- Секреты provisioner нужны для аутентификации CSI-драйвера в Ceph-кластере.

### Статическое выделение: NFS

```yaml
# 1. PV (администратор)
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs-logs-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  nfs:
    path: /var/k8s-logs
    server: 192.168.1.100

---
# 2. PVC (разработчик)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: fluentd-logs-pvc
  namespace: logging
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 10Gi

---
# 3. Pod с PVC
apiVersion: v1
kind: Pod
metadata:
  name: fluentd
  namespace: logging
spec:
  containers:
    - name: fluentd
      image: fluent/fluentd
      volumeMounts:
        - name: log-storage
          mountPath: /fluentd/log
  volumes:
    - name: log-storage
      persistentVolumeClaim:
        claimName: fluentd-logs-pvc
```

**Пояснения:**

- NFS поддерживает `ReadWriteMany` — несколько подов могут писать в один том.
- Статическое выделение: PV создан вручную администратором, PVC автоматически связывается с ним.

### StatefulSet с PersistentVolume

Для stateful-приложений (БД) используется **[StatefulSet](../Base/StatefulSet/statefulset_core_concepts.md)**. Он автоматически создаёт уникальный PVC для каждого пода на основе `volumeClaimTemplates`:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: postgres
  replicas: 3
  selector:
    matchLabels:
      app: postgres
  template:
    spec:
      containers:
        - name: postgres
          image: postgres:15
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: standard-ssd
        resources:
          requests:
            storage: 10Gi
```

**Пояснения:**

- Каждый pod получает свой PVC: `data-postgres-0`, `data-postgres-1`, `data-postgres-2`.
- При удалении pod PVC сохраняется (данные не теряются).
- При масштабировании новые PVC создаются автоматически.

> **Важно:** По умолчанию при удалении StatefulSet его PVC **не удаляются** автоматически. Это защищает данные от случайной потери.

---

## Дополнительная информация

Локальное хранилище: [Local Path Provisioner](./local-path-provisioner.md). NFS-хранилище: [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md). Ceph RBD: [Ceph RBD Concepts](./Ceph/ceph_rbd_usage/definitions_and_concepts.md). CephFS: [CephFS Concepts](./Ceph/cephfs_setup_and_usage/definitions_and_concepts.md). StatefulSet: [StatefulSet Core Concepts](../Base/StatefulSet/statefulset_core_concepts.md).
