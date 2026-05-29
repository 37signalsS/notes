# NFS Subdir External Provisioner

## Определения

**NFS Subdir External Provisioner** — динамический provisioner для Kubernetes, использующий существующий NFS-сервер для создания `PersistentVolume`.

При поступлении запроса на PVC provisioner создаёт новую поддиректорию вида `<namespace>-<pvc-name>-<pv-name>` на общем NFS-ресурсе и предоставляет её как `PersistentVolume`.

> **Назначение:** Простое и эффективное решение для dev-сред, лабораторных работ или небольших on-premise инсталляций с существующим NFS-сервером.

---

## Базовые концепции

### Принцип работы

1. **Запрос (PVC):** Пользователь создаёт PVC с указанием `StorageClass`.
2. **Обнаружение:** Контроллер (Provisioner Deployment) видит новый PVC, ассоциированный с его `PROVISIONER_NAME`.
3. **Создание директории:**
    - Provisioner-под имеет смонтированный корень NFS-шары (указанный в `NFS_SERVER` и `NFS_PATH`).
    - Внутри этой шары он создаёт уникальную поддиректорию вида `${namespace}-${pvcName}-${pvName}`.
4. **Создание PV:** Provisioner создаёт объект `PersistentVolume` типа `NFS`, указывающий на **конкретную поддиректорию** на сервере.
5. **Привязка:** Kubernetes связывает созданный PV с исходным PVC (статус `Bound`).

> **Важно:** Provisioner выступает в роли посредника, который автоматизирует рутинную работу по созданию папок и манифестов PV.

### Переменные окружения (Environment Variables)

Для настройки Provisioner используются следующие переменные в манифесте `Deployment`:

| Переменная | Описание | Значение |
| :--- | :--- | :--- |
| `PROVISIONER_NAME` | Уникальное имя провижинера. Должно совпадать с полем `provisioner` в `StorageClass`. | Например, `cluster.local/nfs-client-provisioner` |
| `NFS_SERVER` | IP-адрес или DNS-имя NFS-сервера. | Например, `192.168.1.10` |
| `NFS_PATH` | Путь к экспортируемой директории на NFS-сервере. | Например, `/var/nfs/kubedata` |

> **Предупреждение о совместимости (K8s 1.33+):** В текущих версиях провижинера (на момент 2023-2024 гг.) используется ресурс `Endpoints`, который объявлен устаревшим и может быть удалён в Kubernetes 1.33+ в пользу `EndpointSlice`. При использовании в новых кластерах следует проверить наличие обновлений образа или патчей от сообщества.

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

> **Рекомендация:** Для обеспечения изоляции и безопасности рекомендуется разворачивать провижинер в отдельном `namespace` (например, `nfs-provisioner` или `storage`), а не в `default`.

#### Шаг 1: RBAC

Provisioner'у нужны права на управление PV (создание, удаление, просмотр) и событиями:

```yaml
# nfs-provisioner-rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: nfs-client-provisioner
  namespace: nfs-provisioner
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
  # Дополнительно для работы с эндпоинтами (см. предупреждение в Базовых концепциях)
  - apiGroups: [""]
    resources: ["endpoints"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: run-nfs-client-provisioner
subjects:
  - kind: ServiceAccount
    name: nfs-client-provisioner
    namespace: nfs-provisioner
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
  namespace: nfs-provisioner
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: nfs-client-provisioner
  template:
    metadata:
      labels:
        app: nfs-client-provisioner
    spec:
      serviceAccountName: nfs-client-provisioner
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
  archiveOnDelete: "false"  # "true" = переименовать в archived-..., "false" = физически удалить поддиректорию
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

### Устаревший Helm-чарт `stable/nfs-server-provisioner`

См. отдельный файл: [NFS Server Provisioner (устаревший Helm-чарт)](./nfs-server-provisioner-helm.md).

Краткое описание: чарт разворачивает монолитное приложение (StatefulSet) со встроенным NFS-сервером и provisioner. Использует `hostPath` volume на ноде, что создаёт привязку к конкретной ноде. Не поддерживается, только для тестовых сред.

### См. также

- Базовые концепции хранения: [PersistentVolume и PVC](./pv_and_pvc.md)
- Альтернатива для RWO: [Local Path Provisioner](./local-path-provisioner.md)
- Альтернатива для RWX с репликацией: [Ceph CephFS](./Ceph/cephfs_setup_and_usage/definitions_and_concepts.md)
