# NFS Server Provisioner (Встроенный NFS-сервер через Helm)

> **Статус: Archived / Deprecated.** Helm-чарт `stable/nfs-server-provisioner` официально заархивирован. Для современных инсталляций (K8s 1.25+) рекомендуется использовать официальный преемник: [nfs-ganesha-server-and-external-provisioner](https://github.com/kubernetes-sigs/nfs-ganesha-server-and-external-provisioner).

## Определения

**`In-cluster NFS Server`** — NFS-сервер, развернутый внутри кластера Kubernetes как под (обычно StatefulSet). Отличается от внешних NFS-тем, что серверный процесс и данные находятся в кластере, а не на выделенной машине.

**`NFS-Ganesha`** — пользовательская (user-space) реализация NFS-сервера, используемая в данном Helm-чарте. В отличие от Kernel NFS, не требует модулей ядра и работает как обычный процесс внутри контейнера.

**`Kernel NFS`** — NFS-сервер, реализованный на уровне ядра Linux (пакет `nfs-kernel-server`). Требует доступа к модулям ядра хоста, поэтому не может быть запущен внутри стандартного контейнера без привилегий.

**`HostPath Provisioner`** — механизм, при котором NFS-сервер хранит данные на локальном диске узла через `hostPath` volume. Данные привязаны к конкретной ноде и не мигрируют при перемещении пода.

**`ReadWriteMany` (RWX)** — режим доступа, позволяющий нескольким подам на разных узлах одновременно читать и писать данные в один и тот же том.

**`StatefulSet`** — объект Kubernetes для управления подами с уникальными сетевыми идентификаторами и стабильным хранилищем. Используется для NFS-сервера для сохранения данных при перезапусках.

**Назначение Helm-чарта `stable/nfs-server-provisioner`:**
- Быстрое создание RWX-хранилища в однонодовых кластерах (Minikube, MicroK8s, K3s).
- Тестирование механизмов динамического выделения томов без внешней инфраструктуры.
- Обучающие сценарии и лабораторные работы.

**Смежные темы:**
- [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md) — работа с внешними NFS-серверами.
- [PersistentVolume и PVC](./pv_and_pvc.md) — базовые концепции хранения.
- [StorageClass](./storageclass.md) — параметры динамического провижининга.
- [CSI Drivers Comparison](./CSI/csi_drivers_comparison.md) — сравнение CSI-драйверов.

---

## Современная альтернатива: NFS-Ganesha Provisioner

Поскольку проект `stable` больше не поддерживается, сообщество `kubernetes-sigs` развивает официальную замену.

**Преимущества нового чарта:**
- **Поддержка современных API:** Полная совместимость с Kubernetes 1.25–1.30+.
- **NFS-Ganesha:** Использование современного пользовательского NFS-сервера, который не требует модулей ядра на хосте.
- **Безопасность:** Улучшенные настройки RBAC и поддержка `securityContext`.

**Установка преемника:**
```bash
helm repo add nfs-ganesha-server-and-external-provisioner https://kubernetes-sigs.github.io/nfs-ganesha-server-and-external-provisioner/
helm install nfs-server nfs-ganesha-server-and-external-provisioner/nfs-server-provisioner
```

### NFS-Ganesha vs Kernel NFS: Сравнение

| Характеристика | NFS-Ganesha | Kernel NFS |
| :--- | :--- | :--- |
| **Реализация** | User-space (пользовательское пространство) | Ядро Linux |
| **Модули ядра** | Не требует | Требует `nfsd`, `nfs` модули |
| **Запуск в контейнере** | Да, без привилегий | Только с привилегиями и модулями на хосте |
| **Производительность** | Ниже (контекстные переключения user/kernel) | Выше (прямой доступ к ядру) |
| **Безопасность** | Лучше (изоляция от ядра) | Хуже (доступ к ядру) |
| **Надежность** | Зависит от стабильности процесса | Зависит от стабильности ядра |
| **Рекомендация** | Kubernetes, контейнеры, dev/test | Production без контейнеров |

> **Вывод:** Для in-cluster NFS-сервера NFS-Ganesha — предпочтительный выбор. Kernel NFS рекомендуется только для внешних NFS-серверов на выделенных машинах.

---

## Базовые концепции

### Архитектура

Система разворачивается как `StatefulSet` с одной репликой. Это необходимо для сохранения стабильного сетевого идентификатора и корректной работы блокировок файловой системы.

**Компоненты внутри пода:**
1. **Ganesha NFS / Kernel NFS:** Программный сервер, обеспечивающий экспорт директорий.
2. **NFS Provisioner:** Контроллер, который слушает Kubernetes API и создает поддиректории в основной "шаре".

**Зависимость от узла:** Хранилище привязано к конкретной ноде через `hostPath`. Если под переедет на другую ноду, он не найдет свои старые данные.

> **Подробнее:** [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md) — современный и рекомендуемый аналог для работы с внешними серверами.

### Принцип работы

1. **Запуск:** Под монтирует локальную директорию узла (например, `/var/lib/nfs-storage`).
2. **Регистрация:** Создается `StorageClass` (по умолчанию `nfs`).
3. **Выделение:** При создании PVC на 100Mi, провизионер создает папку внутри монтирования и генерирует объект `PersistentVolume`, указывающий на IP пода и эту папку.
4. **Монтирование:** Клиентские поды подключаются к IP-адресу пода-сервера через стандартный протокол NFS.

---

## Практические сценарии

### Полный цикл установки и настройки

#### Шаг 1: Подготовка окружения

Создайте отдельное пространство имен для изоляции ресурсов хранения:

```bash
kubectl create namespace nfs-storage
# → namespace/nfs-storage created
```

#### Шаг 2: Подключение архивного репозитория

Репозиторий `stable` больше не обновляется, но чарты доступны в архиве:

```bash
helm repo add stable https://charts.helm.sh/stable
helm repo update
# → Hang tight while we grab the latest from your chart repositories...
```

#### Шаг 3: Скачивание и исправление чарта

Поскольку чарт старый, рекомендуется скачать его локально для возможной правки API-версий (если ваш кластер v1.25+):

```bash
helm pull stable/nfs-server-provisioner --untar
# → Создаётся директория nfs-server-provisioner/

# Проверка структуры
ls nfs-server-provisioner/
# → Chart.yaml  values.yaml  templates/
```

#### Шаг 4: Конфигурация (values.yaml)

Отредактируйте `nfs-server-provisioner/values.yaml`. Важно настроить персистентность и привязку к ноде:

```yaml
# nfs-server-provisioner/values.yaml

persistence:
  enabled: true
  size: 10Gi  # Общий объем дискового пространства на ноде

storageClass:
  name: nfs-internal
  defaultClass: false

# Обязательно для hostPath: привязка к конкретной железной ноде
nodeSelector:
  kubernetes.io/hostname: "worker-01" 
```

**Полная таблица параметров values.yaml:**

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `persistence.enabled` | `true` | Включить персистентное хранилище (PersistentVolume) |
| `persistence.size` | `8Gi` | Объем дискового пространства для NFS-экспорта |
| `persistence.storageClass` | `""` | StorageClass для создания PVC. Пусто = использовать существующий PV |
| `persistence.accessModes` | `["ReadWriteOnce"]` | AccessMode для создаваемого PVC |
| `persistence.hostPath` | `"/srv/nfs-provisioner"` | Путь на файловой системе узла (только hostPath) |
| `storageClass.name` | `nfs` | Имя создаваемого StorageClass |
| `storageClass.defaultClass` | `false` | Сделать StorageClass по умолчанию |
| `storageClass.provisionerName` | `cluster.local/nfs-server-provisioner` | Имя provisioner для StorageClass |
| `storageClass.reclaimPolicy` | `Delete` | ReclaimPolicy: Delete или Retain |
| `storageClass.volumeBindingMode` | `Immediate` | VolumeBindingMode: Immediate или WaitForFirstConsumer |
| `storageClass.archiveOnDelete` | `true` | Переименовывать вместо удаления при Delete |
| `nodeSelector` | `{}` | Привязка к узлу (обязательно для hostPath) |
| `resources.requests.cpu` | `200m` | Минимальные CPU для NFS-сервера |
| `resources.requests.memory` | `256Mi` | Минимальная память |
| `service.type` | `ClusterIP` | Тип сервиса (ClusterIP/NodePort/LoadBalancer) |
| `service.nfsTcpPort` | `2049` | Порт NFS TCP |
| `service.nfsUdpPort` | `2049` | Порт NFS UDP |
| `service.mountdPort` | `20048` | Порт mountd |
| `service.rpcbindPort` | `111` | Порт rpcbind |
| `securityContext.privileged` | `false` | Привилегированный контейнер (для Kernel NFS) |
| `securityContext.capabilities.add` | `[]` | Дополнительные capabilities (например, `["SYS_ADMIN"]`) |

#### Шаг 5: Создание базового PV (Подложка)

Перед установкой чарта создайте PV, который под провизионера будет использовать как свое хранилище:

```yaml
# nfs-root-pv.yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs-root-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  hostPath:
    path: /data/nfs-export  # Путь на диске ноды worker-01
---
# nfs-root-pvc.yaml (если чарт требует существующий PVC)
# Обычно чарт сам создает PVC, если persistence.enabled=true
```

#### Шаг 6: Установка

```bash
helm install nfs-server ./nfs-server-provisioner \
  --namespace nfs-storage \
  -f nfs-server-provisioner/values.yaml
```

### Проверка и тестирование

#### 1. Валидация развертывания

```bash
# Проверка пода
kubectl get pods -n nfs-storage
# → NAME                    READY   STATUS    RESTARTS   AGE
# → nfs-server-provisioner-0   1/1     Running   0          1m

# Проверка StorageClass
kubectl get storageclass
# → NAME           PROVISIONER                            RECLAIMPOLICY   VOLUMEBINDINGMODE
# → nfs-internal   cluster.local/nfs-server-provisioner   Delete          Immediate
```

#### 2. Тестирование динамического PVC

Создайте запрос на том:

```yaml
# test-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: dynamic-nfs-pvc
  namespace: nfs-storage
spec:
  storageClassName: nfs-internal
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 500Mi
```

```bash
kubectl apply -f test-pvc.yaml
kubectl get pvc -n nfs-storage
# → NAME              STATUS   VOLUME                                     CAPACITY   ACCESS MODES
# → dynamic-nfs-pvc   Bound    pvc-12345678-abcd-1234-abcd-1234567890ab   500Mi      RWX
```

#### 3. Проверка сохранения данных (Nginx)

Разверните под для проверки записи:

```yaml
# test-pod.yaml
apiVersion: v1
kind: Pod
metadata:
  name: storage-test-pod
  namespace: nfs-storage
spec:
  containers:
    - name: nginx
      image: nginx:latest
      volumeMounts:
        - name: nfs-vol
          mountPath: /data
  volumes:
    - name: nfs-vol
      persistentVolumeClaim:
        claimName: dynamic-nfs-pvc
```

**Процедура верификации:**

1. **Запись данных:**
   ```bash
   kubectl exec -it -n nfs-storage storage-test-pod -- bash -c "echo 'Persistence Works' > /data/test.txt"
   ```

2. **Пересоздание пода:**
   ```bash
   kubectl delete pod storage-test-pod -n nfs-storage
   kubectl apply -f test-pod.yaml
   ```

3. **Проверка:**
   ```bash
   kubectl exec -it -n nfs-storage storage-test-pod -- cat /data/test.txt
   # → Persistence Works
   ```

---

## Безопасность и конфигурация

### Привилегии контейнера

Запуск NFS-сервера внутри контейнера требует расширенных привилегий для работы с системными вызовами монтирования и экспорта.

**Рекомендуемый `securityContext`:**
```yaml
securityContext:
  privileged: true
  capabilities:
    add: ["SYS_ADMIN", "DAC_READ_SEARCH"]
```

**Минимальный `securityContext` (для NFS-Ganesha):**
```yaml
securityContext:
  privileged: false
  capabilities:
    add: ["SYS_ADMIN"]
```

### RBAC и ServiceAccount

Для безопасного управления NFS-сервером:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: nfs-server-provisioner
  namespace: nfs-storage
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: nfs-server-provisioner
rules:
  - apiGroups: [""]
    resources: ["persistentvolumes"]
    verbs: ["get", "list", "watch", "create", "delete"]
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["storage.k8s.io"]
    resources: ["storageclasses"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["create", "patch"]
```

### Сетевые политики (NetworkPolicies)

Поскольку NFS-сервер открывает порты (2049) внутри кластера, рекомендуется ограничить доступ к нему только для тех пространств имен, которым действительно нужно хранилище.

**Пример политики:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-nfs-access
  namespace: nfs-storage
spec:
  podSelector:
    matchLabels:
      app: nfs-server-provisioner
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              storage-client: "true"
      ports:
        - protocol: TCP
          port: 2049
```

---

## Необходимые системные пакеты

Для успешного монтирования NFS на клиентских нодах должны быть установлены утилиты:

- **Ubuntu/Debian:** `sudo apt update && sudo apt install nfs-common -y`
- **CentOS/RHEL/Rocky:** `sudo yum install nfs-utils -y`

## Диагностика и отладка

**Полная диагностика проблем с in-cluster NFS:**

```bash
# 1. Логи NFS-сервера
kubectl logs -n nfs-storage nfs-server-provisioner-0 --tail=100

# 2. Статус пода
kubectl get pods -n nfs-storage -o wide
kubectl describe pod -n nfs-storage nfs-server-provisioner-0

# 3. Проверка NFS-экспорта внутри пода
kubectl exec -it -n nfs-storage nfs-server-provisioner-0 -- showmount -e localhost

# 4. Проверка файловой системы
kubectl exec -it -n nfs-storage nfs-server-provisioner-0 -- df -h /export

# 5. Проверка StorageClass
kubectl get storageclass nfs-internal -o yaml

# 6. Проверка PV и PVC
kubectl get pv,pvc -n nfs-storage
kubectl describe pv <pv-name>

# 7. Проверка сетевой доступности с клиентского узла
kubectl run nfs-client-test --rm -it --image=alpine -- sh
# Внутри пода:
apk add --no-cache nfs-utils
showmount -e nfs-server-provisioner.nfs-storage.svc.cluster.local

# 8. Проверка событий ProvisioningFailed
kubectl get events --field-selector reason=ProvisioningFailed

# 9. Проверка NFS-клиента на узле
kubectl debug node/<node-name> -it --image=alpine
# Внутри контейнера:
apk add --no-cache nfs-utils
showmount -e <nfs-server-ip>

# 10. Проверка disk usage на NFS-сервере
kubectl exec -it -n nfs-storage nfs-server-provisioner-0 -- du -sh /export/*
```

**Типичные ошибки и решения:**

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Unable to mount volume` | NFS-клиент не установлен на узле | Установите `nfs-common` (Debian) или `nfs-utils` (RHEL) |
| `Mounting arguments: ... mount.nfs` | NFS-сервер не отвечает | Проверьте статус пода, логи, сетевую доступность |
| `Permission denied` | `no_root_squash` не включен | Добавьте `securityContext.privileged: true` или настройте экспорт |
| `No such file or directory` | Путь `/export` не существует | Убедитесь, что `persistence.enabled: true` и путь корректен |
| `NFS server not responding` | Под NFS-сервера завершился | Проверьте ресурсы узла, OOM Kill, restart policy |
| `Stale file handle` | NFS-сервер перезапущен | Примонтируйте заново на клиентах |
| `StorageClass not found` | Имя StorageClass не совпадает | Проверьте `storageClass.name` в values.yaml |
| `Multi-Attach error` | RWO-том на нескольких узлах | Используйте `ReadWriteMany` вместо `ReadWriteOnce` |

---

## Дополнительная информация

### Backup и восстановление

**Бэкап NFS-данных (на стороне сервера):**
```bash
# 1. Остановить NFS-экспорт на время бэкапа
kubectl exec -it -n nfs-storage nfs-server-provisioner-0 -- exportfs -ua

# 2. Скопировать данные с локального диска узла
# (на узле, где запущен под)
tar -czf /backup/nfs-data-$(date +%Y%m%d).tar.gz -C /var/lib/nfs-export .

# 3. Восстановить экспорт
kubectl exec -it -n nfs-storage nfs-server-provisioner-0 -- exportfs -ra
```

**Бэкап через под с NFS-монтированием:**
```yaml
# backup-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: nfs-backup
  namespace: nfs-storage
spec:
  template:
    spec:
      containers:
        - name: backup
          image: alpine
          command: ["/bin/sh", "-c"]
          args:
            - |
              apk add --no-cache nfs-utils tar
              mkdir -p /mnt/nfs /backup
              mount -t nfs4 nfs-server-provisioner.nfs-storage.svc.cluster.local:/export /mnt/nfs
              tar -czf /backup/nfs-$(date +%Y%m%d).tar.gz -C /mnt/nfs .
              umount /mnt/nfs
          volumeMounts:
            - name: backup-storage
              mountPath: /backup
      volumes:
        - name: backup-storage
          hostPath:
            path: /backup
      restartPolicy: Never
```

## Производительность NFS

**Оптимальные mountOptions для клиента:**
```yaml
mountOptions:
  - nfsvers=4.1    # NFS 4.1 для параллельных операций
  - hard           # Отказоустойчивость (безопаснее чем soft)
  - rsize=1048576  # Максимальный размер блока чтения (1MB)
  - wsize=1048576  # Максимальный размер блока записи (1MB)
  - noatime        # Отключить обновление времени доступа
  - noresvport     # Не использовать зарезервированный порт
```

**Тестирование производительности:**
```bash
# Бенчмарк NFS с пода
kubectl run nfs-bench --rm -it --image=alpine -- sh

# Внутри пода:
apk add --no-cache fio nfs-utils
mount -t nfs4 nfs-server-provisioner.nfs-storage.svc.cluster.local:/export /mnt/nfs
fio --name=nfs-test --rw=randwrite --bs=4k --size=100M --numjobs=1 \
    --runtime=30 --group_reporting --directory=/mnt/nfs
```

## Миграция на внешний NFS или CSI

**Почему мигрировать:**
- In-cluster NFS-сервер не отказоустойчив (SPOF).
- Данные привязаны к одной ноде (hostPath).
- Нет поддержки Volume Snapshots и Expansion.

**Процесс миграции:**
1. Установите внешний NFS-сервер (выделенная машина или NAS).
2. Настройте экспорт на внешнем сервере.
3. Установите `nfs-subdir-external-provisioner` или NFS CSI Driver.
4. Скопируйте данные с旧 пода на внешний NFS (rsync).
5. Переключите PVC на новую StorageClass.
6. Удалите旧 NFS-сервер и Helm-чарт.

**Пример rsync-миграции:**
```bash
# С旧 in-cluster NFS
kubectl exec -it -n nfs-storage nfs-server-provisioner-0 -- tar -czf /tmp/backup.tar.gz -C /export .
kubectl cp nfs-storage/nfs-server-provisioner-0:/tmp/backup.tar.gz ./backup.tar.gz

# На внешний NFS-сервер
tar -xzf backup.tar.gz -C /mnt/nfs-export/
```

> **Подробности:** См. [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md).

## Критические ограничения

| Ограничение | Описание | Риски |
| :--- | :--- | :--- |
| **Локальная привязка** | Данные часто хранятся на локальном диске ОДНОЙ ноды. | При выходе ноды из строя данные становятся недоступны (SPOF). |
| **Отсутствие HA** | Сервер — это одиночный под (StatefulSet с 1 репликой). | Перезагрузка пода вызывает прерывание связи (I/O hang) у клиентов. |
| **Устаревший код (stable)** | Оригинальный чарт `stable` не обновляется. | Проблемы безопасности и несовместимость с новыми K8s API (v1.25+). |
| **Производительность** | Весь трафик идет через один под. | Ограничение пропускной способности сети одного узла. |
| **Нет снимков** | Не поддерживает Volume Snapshots | Использовать CSI-драйвер или внешние инструменты |
| **Нет расширения** | Не поддерживает Volume Expansion | Использовать CSI-драйвер |

### Рекомендации по выбору

- **Использовать для:** локальных экспериментов, CI/CD пайплайнов в однонодовых окружениях, демонстраций RWX.
- **НЕ использовать для:** Production-баз данных, высоконагруженных систем, многонодовых кластеров с потребностью в отказоустойчивости.

### См. также

- Базовые концепции хранения: [PersistentVolume и PVC](./pv_and_pvc.md)
- Рекомендуемый современный аналог: [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md)
- Альтернатива для локальных дисков: [Local Path Provisioner](./local-path-provisioner.md)
- Сравнение CSI-драйверов: [CSI Drivers Comparison](./CSI/csi_drivers_comparison.md)
- Распределенное хранилище: [Ceph CephFS](./Ceph/cephfs_setup_and_usage/definitions_and_concepts.md)
