# NFS Subdir External Provisioner

## 1. Определения

**NFS Subdir External Provisioner** — это динамический provisioner для Kubernetes, который использует существующий и доступный NFS-сервер для создания `PersistentVolume` (PV).

В отличие от более сложных хранилищ (например, Ceph или GlusterFS), этот provisioner не управляет самим хранилищем. Вместо этого, при поступлении запроса на `PersistentVolumeClaim` (PVC), он просто создает новую поддиректорию вида `<namespace>-<pvc-name>-<pv-name>` на общем NFS-ресурсе и предоставляет ее в качестве `PersistentVolume`.

Это делает его простым и эффективным решением для `dev`-сред, лабораторных работ или небольших on-premise инсталляций, где уже есть NFS-сервер.

## 2. Основные концепции

### Принцип работы

1.  **Запрос (PVC):** Пользователь создает `PersistentVolumeClaim`, указывая `StorageClass`, который обслуживается этим provisioner'ом.
2.  **Действие Provisioner'а:** Контроллер provisioner'а, который запущен в кластере как `Deployment`, замечает новый PVC.
3.  **Создание директории:** Он подключается к NFS-серверу и создает в корневом каталоге новую, уникально именованную поддиректорию.
4.  **Создание PV:** Provisioner создает объект `PersistentVolume` с типом `NFS`, указывая в качестве пути только что созданную поддиректорию.
5.  **Привязка:** Kubernetes связывает (`binds`) этот новый PV с пользовательским PVC.

### Политика очистки (`ReclaimPolicy`)

Когда PVC удаляется, `ReclaimPolicy`, указанная в `StorageClass` или `PV`, определяет, что произойдет с данными на NFS-сервере:
*   `Delete` (по умолчанию): Provisioner удалит поддиректорию со всем ее содержимым.
*   `Retain`: Provisioner переименует директорию в `archived-<namespace>-<pvc-name>-<pv-name>`, сохранив данные.

## 3. Практические сценарии

### 3.1. Предварительные требования

*   **NFS-сервер:** Должен быть доступен со всех рабочих узлов Kubernetes.
*   **NFS-клиент:** На всех рабочих узлах должны быть установлены утилиты для монтирования NFS (например, пакет `nfs-common` для Debian/Ubuntu или `nfs-utils` для CentOS).

### 3.2. Установка и настройка

#### Шаг 1: RBAC (Role-Based Access Control)

Provisioner'у нужны права на создание, удаление и управление `PersistentVolume`.

```yaml
# nfs-provisioner-rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: nfs-client-provisioner
  namespace: default # Можно разместить в любом namespace
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
  # ... и другие необходимые права
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

#### Шаг 2: Deployment Provisioner'а

Создаем `Deployment`, который запустит контроллер provisioner'а.

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
      priorityClassName: high-priority # Важный компонент, задаем высокий приоритет
      containers:
        - name: nfs-client-provisioner
          image: k8s.gcr.io/sig-storage/nfs-subdir-external-provisioner:v4.0.2
          volumeMounts:
            - name: nfs-client-root
              mountPath: /persistentvolumes
          env:
            - name: PROVISIONER_NAME
              value: my-nfs-storage # Имя, которое будет использоваться в StorageClass
            - name: NFS_SERVER
              value: 192.168.1.10 # IP-адрес вашего NFS-сервера
            - name: NFS_PATH
              value: /var/nfs/kubedata # Путь к экспортируемой директории на NFS-сервере
      volumes:
        - name: nfs-client-root
          nfs:
            server: 192.168.1.10
            path: /var/nfs/kubedata
```
> **Важно:** `Deployment` монтирует к себе весь NFS-ресурс (`/persistentvolumes`), чтобы иметь возможность создавать и удалять в нем поддиректории.

#### Шаг 3: Создание `StorageClass`

Создаем `StorageClass`, который будет использовать наш provisioner.

```yaml
# nfs-storageclass.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: managed-nfs-storage
provisioner: my-nfs-storage # То же имя, что и в PROVISIONER_NAME
parameters:
  archiveOnDelete: "false" # При удалении PVC данные будут удаляться
```

### 3.3. Использование

Теперь любой пользователь в кластере может запросить хранилище, создав `PersistentVolumeClaim`.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-test-pvc
spec:
  storageClassName: managed-nfs-storage # Ссылаемся на наш StorageClass
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
```

После создания этого PVC:
1.  NFS Provisioner создаст директорию на NFS-сервере (например, `/var/nfs/kubedata/default-my-test-pvc-pvc-xxxx`).
2.  Provisioner создаст `PersistentVolume`, указывающий на эту директорию.
3.  `my-test-pvc` будет успешно привязан к этому `PV` и перейдет в статус `Bound`.

## 4. Дополнительная информация

*   **`accessModes`**: Несмотря на то, что NFS поддерживает `ReadWriteMany` (одновременный доступ на чтение и запись из нескольких подов), при использовании этого provisioner'а рекомендуется быть осторожным, так как он не обеспечивает никаких механизмов блокировок на уровне файлов.
*   [Официальный репозиторий](https://github.com/kubernetes-sigs/nfs-subdir-external-provisioner)
