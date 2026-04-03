# NFS Subdir External Provisioner

## Определения

**NFS Subdir External Provisioner** — динамический provisioner для Kubernetes, использующий существующий NFS-сервер для создания `PersistentVolume`.

При поступлении запроса на PVC provisioner создаёт новую поддиректорию вида `<namespace>-<pvc-name>-<pv-name>` на общем NFS-ресурсе и предоставляет её как `PersistentVolume`.

> **Назначение:** Простое и эффективное решение для dev-сред, лабораторных работ или небольших on-premise инсталляций с существующим NFS-сервером.

---

## Базовые концепции

### Принцип работы

1. **Запрос (PVC):** Пользователь создаёт PVC с указанием `StorageClass`.
2. **Действие Provisioner'а:** Контроллер (Deployment) обнаруживает новый PVC.
3. **Создание директории:** Provisioner подключается к NFS-серверу и создаёт уникальную поддиректорию.
4. **Создание PV:** Provisioner создаёт `PersistentVolume` с типом `NFS`, указывающий на новую директорию.
5. **Привязка:** Kubernetes связывает PV с PVC (статус `Bound`).

### Политика очистки (ReclaimPolicy)

| Политика | Описание | Когда использовать |
|----------|----------|-------------------|
| **`Delete`** (по умолчанию) | Provisioner удаляет поддиректорию со всем содержимым | Dev/Test, временные данные |
| **`Retain`** | Provisioner переименовывает директорию в `archived-<namespace>-<pvc-name>-<pv-name>` | Production, важные данные |

> **Важно:** При `Retain` данные сохраняются, но PV требует ручной очистки перед повторным использованием.

### Ограничения

| Ограничение | Описание | Рекомендация |
|-------------|----------|--------------|
| **Производительность** | Ограничена скоростью сети и возможностями NFS-сервера | Не использовать для high-IOPS workload |
| **Блокировки** | Нет механизмов блокировок на уровне файлов | Осторожно с параллельной записью |
| **Зависимость от NFS** | Требуется доступный NFS-сервер | Настроить мониторинг NFS |

---

## Практические сценарии

### Предварительные требования

1. **NFS-сервер:** Доступен со всех рабочих узлов Kubernetes.
2. **NFS-клиент:** На всех узлах установлены утилиты для монтирования NFS:
   - Debian/Ubuntu: `nfs-common`
   - CentOS/RHEL: `nfs-utils`

### Установка и настройка

#### Шаг 1: RBAC

Provisioner'у нужны права на управление PV:

```yaml
# nfs-provisioner-rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: nfs-client-provisioner
  namespace: default
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: nfs-client-provisioner-runner
rules:
  - apiGroups: [""]
    resources: ["persistentvolumes"]
    verbs: ["get", "list", "watch", "create", "delete"]
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["get", "list", "watch", "update"]
  - apiGroups: ["storage.k8s.io"]
    resources: ["storageclasses"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["create", "update", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: run-nfs-client-provisioner
subjects:
  - kind: ServiceAccount
    name: nfs-client-provisioner
    namespace: default
roleRef:
  kind: ClusterRole
  name: nfs-client-provisioner-runner
  apiGroup: rbac.authorization.k8s.io
```

#### Шаг 2: Deployment

```yaml
# nfs-provisioner-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nfs-client-provisioner
spec:
  replicas: 1
  template:
    spec:
      serviceAccountName: nfs-client-provisioner
      priorityClassName: high-priority
      containers:
        - name: nfs-client-provisioner
          image: registry.k8s.io/sig-storage/nfs-subdir-external-provisioner:v4.0.2
          volumeMounts:
            - name: nfs-client-root
              mountPath: /persistentvolumes
          env:
            - name: PROVISIONER_NAME
              value: cluster.local/nfs-client-provisioner
            - name: NFS_SERVER
              value: 192.168.1.10
            - name: NFS_PATH
              value: /var/nfs/kubedata
      volumes:
        - name: nfs-client-root
          nfs:
            server: 192.168.1.10
            path: /var/nfs/kubedata
```

> **Важно:** `Deployment` монтирует весь NFS-ресурс для создания поддиректорий.

#### Шаг 3: StorageClass

```yaml
# nfs-storageclass.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: managed-nfs-storage
provisioner: cluster.local/nfs-client-provisioner
parameters:
  archiveOnDelete: "false"  # false = удалять, true = архивировать
reclaimPolicy: Delete
volumeBindingMode: Immediate
```

### Использование

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-test-pvc
spec:
  storageClassName: managed-nfs-storage
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 1Gi
```

**Результат:**

1. NFS Provisioner создаёт директорию на NFS-сервере (например, `/var/nfs/kubedata/default-my-test-pvc-pvc-xxxx`).
2. Создаётся `PersistentVolume`, указывающий на эту директорию.
3. PVC переходит в статус `Bound`.

### Пример: Pod с RWX-доступом

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: web-server
spec:
  containers:
    - name: nginx
      image: nginx:latest
      volumeMounts:
        - name: shared-data
          mountPath: /usr/share/nginx/html
  volumes:
    - name: shared-data
      persistentVolumeClaim:
        claimName: my-test-pvc
```

---

## Дополнительная информация

Базовые концепции: [PersistentVolume и PVC](./pv_and_pvc.md). Альтернатива для RWO: [Local Path Provisioner](./local-path-provisioner.md). Альтернатива для RWX с репликацией: [Ceph CephFS](./Ceph/ceph_csi_cephfs_driver_setup.md).

Официальный репозиторий: [kubernetes-sigs/nfs-subdir-external-provisioner](https://github.com/kubernetes-sigs/nfs-subdir-external-provisioner). Документация Kubernetes по NFS: [Volumes — NFS](https://kubernetes.io/docs/concepts/storage/volumes/#nfs).
