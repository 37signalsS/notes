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

### Deployment с общим хранилищем (NFS)

Стандартный сценарий для stateless-приложений, которым требуется доступ к общим данным (например, конфигурации или общая директория для логов).

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: log-writer
spec:
  replicas: 2
  selector:
    matchLabels:
      app: log-writer
  template:
    metadata:
      labels:
        app: log-writer
    spec:
      containers:
      - name: busybox
        image: busybox
        command: ["/bin/sh", "-c", "while true; do echo \"$(date) - $(hostname)\" >> /data/app.log; sleep 5; done"]
        volumeMounts:
        - name: shared-storage
          mountPath: /data
      volumes:
      - name: shared-storage
        persistentVolumeClaim:
          claimName: nfs-pvc
```

**Особенности и риски:**
- **Общий доступ:** Все реплики пишут в один и тот же файл `app.log`. Это допустимо для простых логов, но может вызвать проблемы с блокировками (race conditions) в сложных приложениях.
- **Отсутствие изоляции:** Приложения не могут иметь эксклюзивный доступ к данным. Например, базы данных с однопользовательским режимом (Berkeley DB) могут повредить файлы при одновременном доступе из двух подов.
- **Непредсказуемость:** Имена подов в Deployment случайны. Если приложению нужно работать с конкретным файлом (например, `pod-0` работает с `file-0`), реализовать это через Deployment крайне сложно.
- **Access Modes:** Требуется хранилище с поддержкой `ReadWriteMany` (RWX), например NFS. Если использовать `ReadWriteOnce` (RWO), второй под не сможет запуститься, так как том уже примонтирован к первому.

### StatefulSet с PersistentVolume

Для stateful-приложений (БД, брокеры сообщений), требующих уникального хранилища для каждого экземпляра, используется **[StatefulSet](../Base/StatefulSet/statefulset_core_concepts.md)**. Он автоматически создаёт уникальный PVC для каждого пода на основе `volumeClaimTemplates`.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: web
spec:
  serviceName: "web-headless" # Обязательно: Headless Service
  replicas: 2
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
      - name: nginx
        image: nginx
        volumeMounts:
        - name: www
          mountPath: /usr/share/nginx/html
  volumeClaimTemplates:
  - metadata:
      name: www
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: standard-ssd
      resources:
        requests:
          storage: 1Gi
```

**Преимущества StatefulSet:**
- **Уникальность PVC:** Каждый pod получает свой персональный PVC: `www-web-0`, `www-web-1`.
- **Стабильная привязка:** При перезапуске под `web-0` всегда получит тот же самый том `www-web-0`.
- **Предсказуемые имена:** Мы заранее знаем имена подов и их PVC, что позволяет приложению понимать, с каким набором данных оно работает.
- **Headless Service:** Критически важен для обеспечения стабильных DNS-имен каждого пода.

> **Важно:** При удалении StatefulSet его PVC **не удаляются автоматически**. Это защита данных. Для полной очистки ресурсов PVC необходимо удалить вручную: `kubectl delete pvc -l app=web`.

---

## Дополнительная информация

Локальное хранилище: [Local Path Provisioner](./local-path-provisioner.md). NFS-хранилище: [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md). Ceph RBD: [Ceph RBD Concepts](./Ceph/ceph_rbd_usage/definitions_and_concepts.md). CephFS: [CephFS Concepts](./Ceph/cephfs_setup_and_usage/definitions_and_concepts.md). StatefulSet: [StatefulSet Core Concepts](../Base/StatefulSet/statefulset_core_concepts.md).
