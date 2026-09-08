# NFS Subdir External Provisioner (Динамический NFS-провизионер)

> **Статус: Legacy (Не поддерживается).** Проект nfs-subdir-external-provisioner переведен в состояние *unmaintained*. Для новых инсталляций в Kubernetes 1.25+ настоятельно рекомендуется использовать [NFS CSI Driver](https://github.com/kubernetes-csi/csi-driver-nfs).

## Определения

**`NFS Subdir External Provisioner`** — динамический провизионер для Kubernetes, который автоматически создаёт `PersistentVolume` (PV) через поддиректории на существующем NFS-сервере.

**`Provisioner Name`** — уникальное имя провизионера (например, `cluster.local/nfs-client-provisioner`), которое должно совпадать с полем `provisioner` в `StorageClass`. Используется контроллером для обнаружения PVC, требующих динамического выделения.

**`pathPattern`** — параметр StorageClass, определяющий шаблон именования поддиректорий на NFS-сервере. Поддерживает переменные `${.PVC.namespace}`, `${.PVC.name}`, `${.PV.name}` и другие аннотации PVC.

**`archiveOnDelete`** — параметр StorageClass, определяющий поведение при удалении PVC: `false` — физическое удаление поддиректории, `true` — переименование в `archived-<name>` (безопасное удаление с сохранением данных).

**`mountOptions`** — параметр StorageClass, определяющий опции монтирования NFS на узлах (nfsvers, rsize, wsize, hard, noatime и др.).

**`ReadWriteMany` (RWX)** — режим доступа, позволяющий нескольким подам на разных узлах одновременно читать и писать данные в один и тот же том.

**Назначение:**
- Простое решение для dev/test сред и локальных лабораторий.
- Использование существующих NFS-хранилищ без поддержки CSI.
- Обеспечение доступа `ReadWriteMany` (RWX) для подов.

**Смежные темы:**
- [PersistentVolume и PVC](./pv_and_pvc.md) — базовые концепции, lifecycle, AccessModes.
- [StorageClass](./storageclass.md) — параметры динамического провижининга.
- [NFS CSI Driver](./CSI/csi_drivers_comparison.md) — современная CSI-альтернатива.
- [NFS Server Provisioner (устаревший Helm-чарт)](./nfs-server-provisioner-helm.md) — встроенный NFS-сервер.

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
| `sync` | Синхронная запись | Гарантирует целостность данных при сбоях. |
| `no_subtree_check` | Отключает проверку поддеревьев | Улучшает производительность и стабильность. |
| `no_root_squash` | Отключает подмену root | Провизионер создает папки от лица root. Без этого параметра возникнет ошибка `Permission Denied`. |

**Применение изменений:**
```bash
# После изменения /etc/exports
exportfs -ra
# Проверить текущие экспорты
exportfs -v
```

### Шаблоны именования (pathPattern)

Параметр `pathPattern` в StorageClass определяет структуру каталогов на NFS-сервере. Поддерживаются переменные:

| Переменная | Описание | Пример |
| :--- | :--- | :--- |
| `${.PVC.namespace}` | Namespace PVC | `production` |
| `${.PVC.name}` | Имя PVC | `database-pvc` |
| `${.PV.name}` | Имя PV (генерируется) | `pvc-a1b2c3d4-...` |
| `${.PVC.annotations.<key>` | Аннотация из PVC | `${.PVC.annotations.example.com/team}` |

**Примеры pathPattern:**
```yaml
# По умолчанию (обратная совместимость)
pathPattern: "${.PVC.namespace}-${.PVC.name}-${.PV.name}"
# → /var/nfs/kubedata/default-my-pvc-pvc-a1b2c3d4

# Группировка по namespace
pathPattern: "${.PVC.namespace}/${.PVC.name}"
# → /var/nfs/kubedata/production/database-pvc

# С аннотациями (для multi-tenant)
pathPattern: "${.PVC.annotations.com.team/name}/${.PVC.name}"
# → /var/nfs/kubedata/team-alpha/app-data
```

**Создание аннотации в PVC:**
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: app-data
  annotations:
    com.team/name: "team-alpha"
spec:
  storageClassName: managed-nfs-storage
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 10Gi
```

### Поведение при удалении (archiveOnDelete)

| Значение | Поведение | Когда использовать |
| :--- | :--- | :--- |
| `"false"` | Физическое удаление поддиректории со всем содержимым | Dev/Test, временные данные |
| `"true"` | Переименование в `archived-<namespace>-<pvc-name>-<pv-name>` | Production, важные данные (требует ручной очистки) |

```yaml
# Пример StorageClass с archiveOnDelete
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: managed-nfs-storage
provisioner: cluster.local/nfs-client-provisioner
parameters:
  archiveOnDelete: "true"
  pathPattern: "${.PVC.namespace}/${.PVC.name}"
reclaimPolicy: Retain
volumeBindingMode: Immediate
mountOptions:
  - nfsvers=4.1
  - hard
  - rsize=1048576
  - wsize=1048576
  - noatime
```

**Важно:** При `archiveOnDelete: "true"` и `reclaimPolicy: Retain` данные сохраняются, но PV требует ручной очистки перед повторным использованием.

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
| **Нет снимков** | Не поддерживает Volume Snapshots | Использовать CSI-драйвер или внешние инструменты |
| **Нет расширения** | Нет поддержки Volume Expansion | Использовать CSI-драйвер |

### Безопасность NFS-сервера

**Ограничение доступа на уровне Firewall:**
```bash
# iptables: разрешить NFS только с узлов кластера
iptables -A INPUT -p tcp --dport 2049 -s 192.168.1.0/24 -j ACCEPT
iptables -A INPUT -p tcp --dport 2049 -j DROP

# Ограничить по UID/GID (если нужно)
# В /etc/exports добавить root_squash для production
/var/nfs/kubedata  192.168.1.0/24(rw,sync,no_subtree_check,root_squash)
```

**Изоляция через квоты:**
```bash
# Установить лимит дискового пространства на NFS-сервере ( quotas)
# 1. Включить квоты в /etc/fstab
/dev/sda1  /var/nfs  ext4  defaults,usrquota,grpquota  0  2

# 2. Создать квоту для пользователя/группы
edquota -u nfsnobody  # или группу
# Ограничение: 10G soft, 15G hard
```

**Мониторинг NFS-сервера:**
```bash
# Проверить активные подключения
exportfs -v
nfsstat -s
nfsiostat

# Проверить использование диска
df -h /var/nfs/kubedata
du -sh /var/nfs/kubedata/*
```

### Производительность NFS

**Оптимальные mountOptions:**
```yaml
mountOptions:
  - nfsvers=4.1    # NFS 4.1 для параллельных операций
  - hard           # Отказоустойчивость (безопаснее чем soft)
  - rsize=1048576  # Максимальный размер блока чтения (1MB)
  - wsize=1048576  # Максимальный размер блока записи (1MB)
  - noatime        # Отключить обновление времени доступа
  - noresvport     # Не использовать зарезервированный порт
  - connect=8      # Количество TCP-соединений (для NFS 4.1+)
```

**Тестирование производительности:**
```bash
# Бенчмарк NFS с пода
kubectl run nfs-bench --rm -it --image=alpine -- sh

# Внутри пода:
apk add --no-cache fio
fio --name=nfs-test --rw=randwrite --bs=4k --size=100M --numjobs=1 \
    --runtime=30 --group_reporting --directory=/mnt/nfs
```

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

**Полная диагностика проблем с NFS-провизионером:**

```bash
# 1. Логи провизионера
kubectl logs -n nfs-provisioner -l app=nfs-client-provisioner --tail=100

# 2. Статус PVC
kubectl describe pvc <pvc-name>
# → Секция Events: причина ошибки

# 3. Статус пода провизионера
kubectl get pods -n nfs-provisioner -o wide
kubectl describe pod -n nfs-provisioner <pod-name>

# 4. Монтирование NFS внутри пода провизионера
kubectl exec -it -n nfs-provisioner <pod-name> -- df -h /persistentvolumes

# 5. Проверка NFS-доступности с узла
showmount -e <nfs-server-ip>
mount -t nfs4 <nfs-server-ip>:/var/nfs/kubedata /mnt/test

# 6. Проверка StorageClass
kubectl get storageclass managed-nfs-storage -o yaml

# 7. Проверка PV
kubectl get pv | grep nfs
kubectl describe pv <pv-name>

# 8. Проверка событий ProvisioningFailed
kubectl get events --field-selector reason=ProvisioningFailed

# 9. Проверка финализаторов (если PVC в Terminating)
kubectl get pvc <name> -o jsonpath='{.metadata.finalizers}'

# 10. Проверка NFS-клиента на узле
kubectl debug node/<node-name> -it --image=alpine
# Внутри контейнера:
apk add --no-cache nfs-utils
showmount -e <nfs-server-ip>
```

**Типичные ошибки и решения:**

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `permission denied` | `no_root_squash` не включен | Добавьте `no_root_squash` в `/etc/exports`, выполните `exportfs -ra` |
| `timeout` | NFS-сервер недоступен | Проверьте сетевую доступность, firewall, статус NFS-сервера |
| `Unable to mount volume` | NFS-клиент не установлен на узле | Установите `nfs-common` (Debian) или `nfs-utils` (RHEL) |
| `PV not created` | Провизионер не может подключиться к NFS | Проверьте `NFS_SERVER` и `NFS_PATH`, логи провизионера |
| `Multi-Attach error` | RWO-том на нескольких узлах | Используйте `ReadWriteMany` или `WaitForFirstConsumer` |
| `End of directory` | Путь NFS не существует или не экспортирован | Проверьте `exportfs -v`, создайте директорию вручную |
| `Stale file handle` | NFS-сервер перезагружен или экспорт изменён | Примонтируйте заново или перезапустите поды |

---

## Миграция на NFS CSI Driver

Для миграции с nfs-subdir-external-provisioner на современный NFS CSI Driver:

**Преимущества CSI:**
- Активная поддержка и безопасность
- Поддержка Volume Snapshots
- Поддержка Volume Expansion
- Лучшая интеграция с RBAC и сетевыми политиками

**Процесс миграции:**
1. Установите NFS CSI Driver: `helm install csi-driver-nfs csi-driver-nfs/csi-driver-nfs --namespace kube-system`
2. Создайте StorageClass с CSI-драйвером: `nfs.csi.k8s.io`
3. Постепенно переносите PVC с旧 StorageClass на новую
4. Скопируйте данные с旧 томов на новые (rsync, cp)
5. Удалите旧 StorageClass и Provisioner

> **Подробности:** См. [NFS CSI Driver в сравнении драйверов](./CSI/csi_drivers_comparison.md).

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

- [PersistentVolume и PVC в Kubernetes](./pv_and_pvc.md) — базовые концепции, lifecycle, AccessModes
- [Практические сценарии PV и PVC](./pv_and_pvc_scenarios.md) — YAML-манифесты для разных сценариев
- [StorageClass](./storageclass.md) — параметры динамического провижининга
- [NFS CSI Driver (современная альтернатива)](./CSI/csi_drivers_comparison.md) — сравнение CSI-драйверов
- [Local Path Provisioner (для RWO)](./local-path-provisioner.md) — локальный провижинер
- [Ceph CephFS (распределенное RWX)](./Ceph/cephfs_setup_and_usage/definitions_and_concepts.md) — CephFS
- [NFS: Сетевая файловая система (настройка сервера)](../../Linux/Networking/Services/nfs/index.md)
- [Официальная документация: NFS Subdir External Provisioner](https://github.com/kubernetes-sigs/nfs-subdir-external-provisioner)
