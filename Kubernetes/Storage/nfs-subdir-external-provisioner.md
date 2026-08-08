# NFS Subdir External Provisioner (Динамический NFS-провизионер)

> **Статус: Legacy (Не поддерживается).** Проект nfs-subdir-external-provisioner переведен в состояние *unmaintained*. Для новых инсталляций в Kubernetes 1.25+ настоятельно рекомендуется использовать [NFS CSI Driver](https://github.com/kubernetes-csi/csi-driver-nfs).

## Определения

**NFS Subdir External Provisioner** — это динамический провизионер (provisioner) для Kubernetes, который использует существующий NFS-сервер для автоматического создания объектов `PersistentVolume` (PV) через поддиректории.

При поступлении запроса на создание `PersistentVolumeClaim` (PVC), провизионер автоматически создает новую поддиректорию на общем NFS-ресурсе по шаблону `<namespace>-<pvc-name>-<pv-name>` (настраивается) и предоставляет её как сетевой том.

**Назначение:**
- Простое решение для dev/test сред и локальных лабораторий.
- Использование существующих NFS-хранилищ без поддержки CSI.
- Обеспечение доступа `ReadWriteMany` (RWX) для подов.

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

### Конфигурация NFS-сервера

Для корректной работы провизионера на стороне сервера NFS (например, на ОС Linux) экспорт должен быть настроен с определенными параметрами.

**Пример `/etc/exports`:**
```text
/var/nfs/kubedata  192.168.1.0/24(rw,sync,no_subtree_check,no_root_squash)
```

| Параметр | Описание | Почему это важно |
| :--- | :--- | :--- |
| `rw` | Чтение и запись | Поды должны иметь возможность писать данные. |
| `no_root_squash` | Отключает подмену root | Провизионер создает папки от лица root. Без этого параметра возникнет ошибка `Permission Denied`. |

### Переменные окружения (Environment Variables)

Для настройки Provisioner используются следующие переменные в манифесте `Deployment`:

| Переменная | Описание | Значение |
| :--- | :--- | :--- |
| `PROVISIONER_NAME` | Уникальное имя провижинера. Должно совпадать с полем `provisioner` в `StorageClass`. | Например, `cluster.local/nfs-client-provisioner` |
| `NFS_SERVER` | IP-адрес или DNS-имя NFS-сервера. | Например, `192.168.1.10` |
| `NFS_PATH` | Путь к экспортируемой директории на NFS-сервере. | Например, `/var/nfs/kubedata` |

> **Проблема с Endpoints (K8s 1.25+):** Провижинер использует устаревший механизм блокировок через `Endpoints`. В новых версиях Kubernetes (1.30+) это может приводить к ошибкам, если не обновлен образ до `v4.0.2+`. Однако, даже с обновлениями, это архитектурное ограничение является одной из причин перехода на CSI-драйверы.

---

## Современная альтернатива: NFS CSI Driver

Начиная с 2024-2025 гг., стандартом для работы с NFS в Kubernetes является **CSI Driver NFS** (`nfs.csi.k8s.io`).

**Преимущества CSI перед External Provisioner:**
- **Поддержка снимков (Snapshots):** Возможность создания snapshot-ов томов.
- **Volume Expansion:** Динамическое расширение томов без перезагрузки подов.
- **Безопасность:** Работает через стандартные интерфейсы Kubernetes CSI, лучше интегрируется с RBAC и сетевыми политиками.
- **Активная поддержка:** Регулярные обновления безопасности и совместимости с новыми версиями K8s.

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

#### Способ 1: Установка через Helm (Рекомендуется)

Использование Helm позволяет автоматически настроить все необходимые RBAC-роли и параметры.

```bash
# Добавление репозитория
helm repo add nfs-subdir-external-provisioner https://kubernetes-sigs.github.io/nfs-subdir-external-provisioner/

# Установка
helm install nfs-subdir-provisioner nfs-subdir-external-provisioner/nfs-subdir-external-provisioner \
    --set nfs.server=192.168.1.10 \
    --set nfs.path=/var/nfs/kubedata \
    --set storageClass.name=managed-nfs-storage \
    --set storageClass.provisionerName=cluster.local/nfs-client-provisioner
```

#### Способ 2: Ручная установка (Манифесты)

> **Рекомендация:** Для обеспечения изоляции и безопасности рекомендуется разворачивать провижинер в отдельном `namespace` (например, `nfs-provisioner` или `storage`), а не в `default`.

##### Шаг 1: RBAC

Provisioner'у нужны права на управление PV и лидерство (leader election) для работы в нескольких репликах (хотя обычно используется одна):

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
---
# Дополнительно для K8s 1.20+ (Leader Election)
kind: Role
apiVersion: rbac.authorization.k8s.io/v1
metadata:
  name: leader-locking-nfs-client-provisioner
  namespace: nfs-provisioner
rules:
  - apiGroups: [""]
    resources: ["endpoints"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
---
kind: RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
metadata:
  name: leader-locking-nfs-client-provisioner
  namespace: nfs-provisioner
subjects:
  - kind: ServiceAccount
    name: nfs-client-provisioner
    namespace: nfs-provisioner
roleRef:
  kind: Role
  name: leader-locking-nfs-client-provisioner
  apiGroup: rbac.authorization.k8s.io
```

##### Шаг 2: Deployment (Развертывание)

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
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 200m
              memory: 256Mi
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
      nodeSelector:
        kubernetes.io/os: linux
      volumes:
        - name: nfs-client-root
          nfs:
            server: 192.168.1.10
            path: /var/nfs/kubedata
```

> **Важно:** `Deployment` монтирует весь NFS-ресурс для создания поддиректорий. Для корректной работы RBAC и блокировок убедитесь, что версия образа не ниже `v4.0.2`.

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
  pathPattern: "${.PVC.namespace}/${.PVC.name}" # Группировка по неймспейсам
reclaimPolicy: Delete
volumeBindingMode: Immediate
mountOptions:
  - nfsvers=4.1
  - hard
  - rsize=1048576
  - wsize=1048576
  - noatime
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

### Диагностика и отладка

При возникновении проблем с созданием томов рекомендуется проверить:

1. **Логи провизионера:**
   ```bash
   kubectl logs -n nfs-provisioner -l app=nfs-client-provisioner
   ```
   *Ожидаемые сообщения:* `successfully created PV`, `waiting for PVC to be bound`.
   *Ошибки:* `permission denied` (проблемы с правами на NFS), `timeout` (сетевая недоступность сервера).

2. **Статус PVC:**
   ```bash
   kubectl describe pvc <pvc-name>
   ```
   В разделе `Events` будет указана причина, если провизионер не смог создать PV.

3. **Монтирование внутри пода провизионера:**
   Проверьте, что под провизионера сам успешно смонтировал NFS-корень:
   ```bash
   kubectl exec -it -n nfs-provisioner <pod-name> -- df -h /persistentvolumes
   ```

---

## Дополнительная информация

### Безопасность

- **Доступ к корню:** Провизионер монтирует весь корень NFS-шары (`NFS_PATH`). Взлом пода провизионера дает злоумышленнику доступ ко всем данным всех пользователей этого хранилища.
- **Риски no_root_squash:** Использование этого параметра на сервере необходимо для работы провизионера, но оно позволяет любому клиенту с правами root на своей машине манипулировать файлами на сервере. Рекомендуется ограничить доступ к NFS-серверу на уровне Firewall только IP-адресами узлов кластера.
- **Изоляция:** Рекомендуется использовать `pathPattern`, чтобы данные разных приложений были визуально и логически разделены в иерархии папок на сервере.

### Устаревший Helm-чарт `stable/nfs-server-provisioner`

См. отдельный файл: [NFS Server Provisioner (устаревший Helm-чарт)](./nfs-server-provisioner-helm.md).

Краткое описание: чарт разворачивает монолитное приложение (StatefulSet) со встроенным NFS-сервером и provisioner. Использует `hostPath` volume на ноде, что создаёт привязку к конкретной ноде. Не поддерживается, только для тестовых сред.

### См. также

- [NFS: Сетевая файловая система (настройка сервера)](../../Linux/Networking/Services/nfs/index.md)
- [PersistentVolume и PVC в Kubernetes](./pv_and_pvc.md)
- [Local Path Provisioner (для RWO)](./local-path-provisioner.md)
- [Ceph CephFS (распределенное RWX)](./Ceph/cephfs_setup_and_usage/definitions_and_concepts.md)
