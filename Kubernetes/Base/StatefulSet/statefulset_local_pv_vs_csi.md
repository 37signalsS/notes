# StatefulSet: Local PV vs hostPath vs CSI — выбор хранилища для БД

**Актуально для:** Kubernetes 1.30+

## Определения

* **hostPath** — базовый тип тома Kubernetes, монтирующий указанную директорию или файл с файловой системы хоста напрямую в контейнер пода. Не является персистентным томом (`PersistentVolume`), не управляется через PVC и не отслеживается планировщиком при определении доступной емкости диска.
* **Local Persistent Volume (Local PV)** — персистентный том (`PersistentVolume`), физически расположенный на локальном дисковом устройстве конкретного рабочего узла (NVMe/SSD/HDD или LVM логический том). Привязан к узлу через жесткое правило `nodeAffinity` и поддерживается планировщиком Kubernetes через отложенное связывание (`WaitForFirstConsumer`).
* **CSI (Container Storage Interface)** — стандартизированный интерфейс взаимодействия между оркестратором контейнеров (Kubernetes) и внешними/распределенными системами хранения (Ceph RBD, Longhorn, OpenEBS, iSCSI/SAN). Позволяет управлять жизненным циклом блочных и файловых томов через сторонние драйверы без изменения кода Kubernetes.
* **volumeBindingMode: WaitForFirstConsumer** — режим работы `StorageClass`, откладывающий создание и привязку тома (`PV`) до момента, когда планировщик выберет конкретный узел для размещения первого пода-потребителя. Исключает конфликт топологии и несовпадение зон доступности.
* **VolumeAttachment** — системный объект Kubernetes API, фиксирующий статус подключения тома CSI к конкретному узлу кластера. Контролируется контроллером `attach-detach-controller` и внешним компонентом `csi-attacher`.
* **ReadWriteOncePod (RWOP)** — режим доступа тома (`accessMode`), добавленный в Kubernetes для строгого ограничения доступа к тому: разрешено монтирование только одному-единственному поду во всем кластере. Предотвращает состояние гонки и повреждение данных при пересоздании подов StatefulSet.

## Архитектура и основные концепции

Выбор типа хранилища для `StatefulSet` определяет архитектуру отказоустойчивости, предельную производительность (IOPS, p99 latency), сложность сопровождения и сценарии аварийного восстановления (Disaster Recovery) для баз данных и распределенных очередей в on-premise и bare-metal инфраструктуре.

```
+-----------------------------------------------------------------------------------------+
|                                    Kubernetes Scheduler                                 |
+-----------------------------------------------------------------------------------------+
            |                                                      |
            | volumeBindingMode: WaitForFirstConsumer               | CSI VolumeAttachment
            v                                                      v
+-------------------------------+                     +-----------------------------------+
|      Local PV / TopoLVM       |                     |      CSI (Ceph RBD / Longhorn)    |
+-------------------------------+                     +-----------------------------------+
| * Монтирование локального NVMe|                     | * Сетевой блочный доступ          |
| * nodeAffinity: node-01       |                     | * Независимость от узла           |
| * Субмиллисекундная latency   |                     | * Репликация по сети (2x-3x write)|
| * Нет миграции тома           |                     | * Автоматический failover на узел |
+-------------------------------+                     +-----------------------------------+
```

### Сравнительная матрица типов хранилища (Bare-Metal / On-Premise)

| Критерий | hostPath | Local Persistent Volume (Local PV) | Сетевой CSI (Ceph RBD, Longhorn) |
| :--- | :--- | :--- | :--- |
| **Тип ресурса в K8s** | Встроенный том пода (`volumes[].hostPath`) | Полноценный `PersistentVolume` с `nodeAffinity` | `PersistentVolume` через CSI-плагин |
| **Управление через PVC** | Нет | Да (`volumeClaimTemplates` востребован) | Да (`volumeClaimTemplates` востребован) |
| **Динамический провижининг** | Нет (только создание каталога `DirectoryOrCreate`) | Да (TopoLVM, local-path-provisioner) | Да (Ceph-CSI, Longhorn CSI) |
| **Привязка к узлу** | Физическая (без контроля планировщиком) | Жесткая через `spec.nodeAffinity` | Динамическая (монтируется к любому узлу) |
| **Миграция тома при падении узла** | Невозможна | Невозможна (том привязан к физическому диску) | Возможна (том подключается к новому узлу) |
| **Задержка дискового ввода-вывода** | Минимальная (прямой ввод-вывод) | Минимальная (локальный NVMe/SATA, <0.1–0.3 мс) | Сетевая задержка + репликация (1.0–5.0 мс) |
| **Предельный IOPS** | Аппаратный лимит локального диска | Аппаратный лимит диска/контроллера | Ограничен пропускной способностью сети/SDS |
| **Накладные расходы CPU/RAM** | Нулевые | Нулевые (или минимальные у LVM-драйвера) | Высокие (сетевой стек, шифрование, реплики) |
| **Поддержка VolumeSnapshot** | Нет | Зависит от провайдера (LVM thin-pool: да) | Да (стандартный CSI snapshotter) |
| **Онлайн-расширение тома** | Нет | Только при наличии CSI (TopoLVM) | Да (`allowVolumeExpansion: true`) |
| **Контроль квот и емкости** | Отсутствует (риск заполнения root-диска) | Строгий учет емкости в K8s / LVM VG | Строгий учет емкости пула СХД |
| **Безопасность (Pod Security)** | Запрещен политиками PSA `Baseline` и `Restricted` | Разрешен во всех политиках PSA | Разрешен во всех политиках PSA |

### Внутреннее устройство и планирование StatefulSet

1. **Неизменность связки Pod ↔ PVC:**
   При развертывании `StatefulSet` секция `volumeClaimTemplates` генерирует уникальный `PersistentVolumeClaim` для каждой реплики по формуле `<имя-шаблона>-<имя-statefulset>-<порядковый-номер>` (например, `data-postgres-0`).
   При падении или пересоздании пода с тем же порядковым номером контроллер `StatefulSet` всегда повторно монтирует строго тот же самый PVC.
2. **Двухэтапное планирование и WaitForFirstConsumer:**
   Если `StorageClass` настроен с `volumeBindingMode: Immediate`, том создается сразу при появлении PVC на произвольном узле или в произвольной зоне. Когда под запускается, планировщик может не найти свободных ресурсов (CPU/RAM) или столкнуться с `podAntiAffinity` на этом узле, из-за чего под зависает в `Pending` с ошибкой `volume node affinity conflict`.
   При `volumeBindingMode: WaitForFirstConsumer` планировщик сначала выбирает подходящий узел с учетом всех ограничений пода (ресурсы, taints, affinity), и только после этого запускает провижининг тома на выбранном узле.

### Поведение при аварии узла (Node Failure / NodeNotReady)

Поведение StatefulSet при физическом выходе сервера из строя кардинально различается в зависимости от выбранного хранилища:

#### 1. Local PV:
* Под переходит в состояние `Terminating` или остается на узле со статусом `Unknown`/`NodeNotReady`.
* Даже если принудительно удалить под (`kubectl delete pod --force`), новый под с тем же ordinal (например, `postgres-0`) **не сможет запуститься на другом узле**: его PVC привязан к конкретному PV, содержащему `spec.nodeAffinity` с указанием упавшего узла.
* Новый под останется в состоянии `Pending` до тех пор, пока физический сервер не вернется в строй.
* **Вывод для SRE:** Использовать Local PV допустимо только для приложений с встроенной кластерной репликацией (Patroni для PostgreSQL, Kafka, ClickHouse, Cassandra, etcd), где потеря одной ноды компенсируется остальными членами кворума.

#### 2. Сетевой блочный CSI (Ceph RBD / Longhorn):
* Данные физически сохранены в распределенном пуле хранения вне упавшего сервера.
* Однако Kubernetes защищает данные от одновременной записи (split-brain). Пока узел находится в `NodeNotReady`, контроллер `attach-detach-controller` не отключает том от мертвого узла, а объект `VolumeAttachment` остается заблокированным.
* Попытка пересоздать под на исправном узле приводит к ошибке: `Multi-Attach error for volume ... Volume is already exclusively attached to one node and can't be attached to another`.
* Для корректного автоматического или полуавтоматического восстановления в современных версиях Kubernetes (1.28+) применяется механизм **Non-graceful Node Shutdown**: на упавший узел накладывается taint `node.kubernetes.io/out-of-service:NoExecute`, после чего контроллер принудительно удаляет `VolumeAttachment` и под успешно стартует на новом узле.

### Производительность, задержки и накладные расходы

* **Local NVMe (TopoLVM / Direct PV):** Прямой блочный доступ к контроллеру NVMe через ядро Linux. Задержки на операциях `fsync` составляют 20–80 микросекунд (µs). Отсутствует контекстное переключение на сетевые сокеты и программные репликаторы. Обеспечивает максимальную скорость фиксации транзакций в WAL (PostgreSQL/MySQL redo-log).
* **Ceph RBD (CSI krbd):** Блочный доступ через модуль ядра Linux (`krbd`). Каждая операция записи дублируется по сети на OSD-демоны в соответствии с фактором репликации (обычно `size = 3, min_size = 2`). Задержка `fsync` составляет от 1.5 до 4 мс в сети 10/25 GbE.
* **Longhorn CSI:** Работает в пользовательском пространстве (userspace) через виртуальный iSCSI-таргет или модуль SPDK. Создает накладные расходы на чтение/запись до 3–10 мс и потребляет значительные ресурсы CPU узла на поддержание реплик при интенсивном вводе-выводе.

### Безопасность и изоляция хоста

* **hostPath:** Представляет прямую угрозу безопасности контейнерной среды. Позволяет процессу в контейнере обойти изоляцию namespaces и получить доступ к сокетам хоста (`/var/run/docker.sock`, `/var/run/containerd/containerd.sock`), секретам или системным файлам (`/etc/shadow`). Кроме того, контейнер может бесконтрольно заполнить корневой раздел хоста, вызвав системный сбой `DiskPressure` и эвикцию всех подов узла.
* **Local PV (TopoLVM):** Создает отдельный логический том LVM (`Logical Volume`) фиксированного размера для каждого PVC. Заполнение тома базой данных приводит к ошибке `No space left on device` строго внутри контейнера, не затрагивая ОС хоста и соседние поды.
* **CSI:** Тома изолированы на уровне пула блочных устройств СХД, монтируются в выделенные каталоги `/var/lib/kubelet/pods/<pod-uid>/volumes/...` с поддержкой `fsGroup` и прав доступа POSIX.

### Алгоритм выбора типа хранилища для SRE/DevOps

```
Нужно хранилище для StatefulSet в On-Premise?
│
├── Данные временные / тестовые / кэш без требований к сохранности?
│   └── ДА → hostPath или Generic Ephemeral Volume (emptyDir)
│
└── Production-нагрузка (БД, брокеры сообщений, хранилища состояния)
    │
    ├── Архитектура приложения поддерживает репликацию данных (Patroni, Kafka, Cassandra, ClickHouse)?
    │   ├── ДА, и критичны минимальная задержка (latency < 1ms) и максимальный IOPS:
    │   │   └── Выбор → Local PV на NVMe (TopoLVM / local-path-provisioner)
    │   │       * Обязательно: podAntiAffinity, volumeBindingMode: WaitForFirstConsumer
    │   │       * Обязательно: наличие автоматического failover на уровне приложения
    │   │
    │   └── НЕТ, приложение одноузловое (Single-node PG/MySQL) или нет репликации на уровне приложения:
    │       └── Выбор → Сетевой блочный CSI (Ceph RBD / Longhorn)
    │           * Защита от сбоя узла на уровне СХД (репликация блоков 3x)
    │           * Поддержка CSI VolumeSnapshot для резервного копирования
    │           * Возможность перезапуска пода на любом рабочем узле
```

---

## Практические сценарии и конфигурация

### Сценарий 1: Высоконагруженная СУБД (PostgreSQL 16) на Local PV (TopoLVM)

Цель: развертывание высоконагруженного кластера PostgreSQL с репликацией на уровне приложения (Patroni/streaming replication) с субмиллисекундной задержкой WAL.

#### 1. Настройка StorageClass с отложенным связыванием

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-nvme-topolvm
provisioner: topolvm.io
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
allowVolumeExpansion: true
parameters:
  "topolvm.io/device-class": "nvme-thin"
```

#### 2. Манифест StatefulSet с жестким podAntiAffinity

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres-ha
  namespace: database
spec:
  serviceName: postgres-ha
  replicas: 3
  podManagementPolicy: OrderedReady
  selector:
    matchLabels:
      app: postgres-ha
  template:
    metadata:
      labels:
        app: postgres-ha
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app: postgres-ha
            topologyKey: kubernetes.io/hostname
      securityContext:
        fsGroup: 999
        runAsUser: 999
        runAsNonRoot: true
      containers:
      - name: postgresql
        image: postgres:16.4
        resources:
          requests:
            cpu: "4"
            memory: "16Gi"
          limits:
            cpu: "8"
            memory: "32Gi"
        ports:
        - containerPort: 5432
          name: postgres
        env:
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-credentials
              key: password
        volumeMounts:
        - name: pgdata
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: pgdata
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: local-nvme-topolvm
      resources:
        requests:
          storage: 200Gi
```

### Сценарий 2: Распределенный брокер сообщений (Kafka) на локальных дисках

Цель: гарантировать максимальную пропускную способность (sequential write) и исключить влияние сети хранения данных на брокеры Kafka.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: kafka-broker
  namespace: kafka
spec:
  serviceName: kafka-headless
  replicas: 3
  podManagementPolicy: Parallel
  selector:
    matchLabels:
      app: kafka
  template:
    metadata:
      labels:
        app: kafka
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app: kafka
            topologyKey: kubernetes.io/hostname
      containers:
      - name: kafka
        image: apache/kafka:3.7.0
        ports:
        - containerPort: 9092
          name: client
        volumeMounts:
        - name: kafka-storage
          mountPath: /var/lib/kafka/data
  volumeClaimTemplates:
  - metadata:
      name: kafka-storage
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: local-nvme-topolvm
      resources:
        requests:
          storage: 500Gi
```

### Сценарий 3: Отказоустойчивая база данных с сетевым CSI (Ceph RBD)

Цель: база данных с независимым хранилищем, поддержкой моментальных снимков (VolumeSnapshot) и режима эксклюзивной блокировки `ReadWriteOncePod`.

#### 1. StorageClass для Ceph RBD

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-rbd-sc
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: 4a2b6f10-9b45-48b2-b13c-0e77d24a901a
  pool: k8s-rbd-pool
  imageFeatures: layering,exclusive-lock,object-map,fast-diff
  csi.storage.k8s.io/provisioner-secret-name: csi-rbd-secret
  csi.storage.k8s.io/provisioner-secret-namespace: ceph-csi
  csi.storage.k8s.io/controller-expand-secret-name: csi-rbd-secret
  csi.storage.k8s.io/controller-expand-secret-namespace: ceph-csi
  csi.storage.k8s.io/node-stage-secret-name: csi-rbd-secret
  csi.storage.k8s.io/node-stage-secret-namespace: ceph-csi
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
allowVolumeExpansion: true
```

#### 2. StatefulSet с защитой через ReadWriteOncePod

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: db-replicated
  namespace: database
spec:
  serviceName: db-replicated
  replicas: 2
  selector:
    matchLabels:
      app: db-replicated
  template:
    metadata:
      labels:
        app: db-replicated
    spec:
      containers:
      - name: database
        image: postgres:16.4
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOncePod"]
      storageClassName: ceph-rbd-sc
      resources:
        requests:
          storage: 100Gi
```

---

## Операции и команды обслуживания

### Инспекция томов и топологической привязки

Проверка состояния PVC, созданных через `volumeClaimTemplates`:

```bash
kubectl get pvc -n database -l app=postgres-ha -o wide
# → NAME                   STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS          AGE   VOLUMEMODE
# → pgdata-postgres-ha-0   Bound    pvc-8f2b5a1c-34d2-45e6-a78b-90c12e345678   200Gi      RWO            local-nvme-topolvm    2d    Filesystem
# → pgdata-postgres-ha-1   Bound    pvc-1a4e6f8b-789a-4123-bcde-0123456789ab   200Gi      RWO            local-nvme-topolvm    2d    Filesystem
# → pgdata-postgres-ha-2   Bound    pvc-9c8d7e6f-5432-41ba-9876-fedcba987654   200Gi      RWO            local-nvme-topolvm    2d    Filesystem
```

Проверка жесткой привязки `nodeAffinity` у сгенерированного Local PV:

```bash
kubectl get pv pvc-8f2b5a1c-34d2-45e6-a78b-90c12e345678 -o jsonpath='{.spec.nodeAffinity}' | jq .
# → {
# →   "required": {
# →     "nodeSelectorTerms": [
# →       {
# →         "matchExpressions": [
# →           {
# →             "key": "kubernetes.io/hostname",
# →             "operator": "In",
# →             "values": [
# →               "worker-node-01.infra.local"
# →             ]
# →           }
# →         ]
# →       }
# →     ]
# →   }
# → }
```

### Проверка системных объектов подключения CSI томов

Инспекция объектов `VolumeAttachment` для сетевых томов (Ceph RBD / Longhorn):

```bash
kubectl get volumeattachment
# → NAME                                                                 ATTACHER            NODE                         ATTACHED   AGE
# → csi-78a9c1...rbd-pvc-11223344                                       rbd.csi.ceph.com    worker-node-02.infra.local   true       5h12m
# → csi-89b0d2...rbd-pvc-55667788                                       rbd.csi.ceph.com    worker-node-03.infra.local   true       5h10m
```

### Регламент дренажа узла (Node Maintenance)

Дренаж рабочего узла, на котором запущены поды StatefulSet:

1. **Для подов с Local PV:**
   Попытка выселить под командой `kubectl drain` вызовет ошибку, если узел содержит локальное хранилище без явного разрешения флагами:

```bash
kubectl drain worker-node-01.infra.local --ignore-daemonsets --delete-emptydir-data
# → node/worker-node-01.infra.local cordoned
# → evicting pod database/postgres-ha-0
# → pod/postgres-ha-0 evicted
# → node/worker-node-01.infra.local drained
```

*Обратите внимание:* Выселенный под `postgres-ha-0` перейдет в состояние `Pending`, так как его том `Local PV` существует только на выведенном в обслуживание узле `worker-node-01`. Кластерная репликация СУБД должна переключить master-роль на реплику `postgres-ha-1` или `postgres-ha-2`.

2. **Для подов с сетевым CSI:**
   После выполнения `kubectl drain` под удаляется на обслуживаемом узле, контроллер `csi-attacher` отключает том от узла, и под успешно перезапускается на другом доступном узле кластера:

```bash
kubectl get pod postgres-replicated-0 -n database -o wide
# → NAME                    READY   STATUS    RESTARTS   AGE   IP            NODE
# → postgres-replicated-0   1/1     Running   0          45s   10.244.3.42   worker-node-03.infra.local
```

### Разблокировка зависшего тома CSI при аварии узла (Non-graceful Shutdown)

Если физический сервер `worker-node-02` сгорел, сетевой том остается подключенным в статусе `VolumeAttachment`. Для принудительного переноса пода в Kubernetes 1.28+ накладывается системный taint:

```bash
kubectl taint nodes worker-node-02.infra.local node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
# → node/worker-node-02.infra.local tainted
```

Проверка снятия блокировки: контроллер K8s немедленно удалит `VolumeAttachment` и пересоздаст под на исправном сервере. После восстановления или списания сервера taint снимается.

---

## Диагностика и устранение неполадок

### Сводная таблица типовых инцидентов со хранилищем StatefulSet

| Симптом / Ошибка | Первопричина | Команда диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **VolumeBindingError** (`pod has unbound immediate PVCs`) | `volumeBindingMode: Immediate` создал том на узле, где нет ресурсов CPU/RAM или сработал `podAntiAffinity` | `kubectl describe pod <pod-name>` | Пересоздать StorageClass с параметром `volumeBindingMode: WaitForFirstConsumer` |
| **Multi-Attach error for volume** | Старый узел с CSI перешел в `NotReady`, томовый аттачмент не снят, новый узел не может подключить том | `kubectl get volumeattachment`, `kubectl describe pvc` | Наложить `out-of-service` taint на упавший узел или выполнить graceful restart kubelet |
| **Pod stuck in Pending (Local PV)** | Узел, к которому привязан Local PV, недоступен (`NotReady`), а том привязан жестко через `nodeAffinity` | `kubectl get pod -o wide`, `kubectl describe pv <pv-name>` | Восстановить узел или удалить PVC/PV и инициировать ребилд реплики на новом узле |
| **DiskPressure на узле** | Использование `hostPath` или `local-path-provisioner` без квот привело к переполнению ФС хоста | `df -h /`, `kubectl describe node <node>` | Очистить логи/мусор, мигрировать тома на LVM-based провижининг (TopoLVM) с жестким квотированием |
| **VolumeExpansionFailed** | Попытка расширить Local PV без поддержки драйвером или нехватка места в VG | `kubectl describe pvc <pvc-name>` | Для TopoLVM: добавить диск в Volume Group (`vgextend`). Для статического Local PV: расширение не поддерживается |

### Детальные сценарии устранения неисправностей

#### Инцидент 1: Под StatefulSet на Local PV завис в Pending после гибели сервера

**Диагностика:**

```bash
kubectl describe pod postgres-ha-0 -n database
# → Events:
# →   Type     Reason            Age   From               Message
# →   ----     ------            ----  ----               -------
# →   Warning  FailedScheduling  42s   default-scheduler  0/6 nodes are available: 1 node(s) had untolerated taint {node.kubernetes.io/unreachable: }, 5 node(s) had volume node affinity conflict.
```

**Причина:**
Узел `worker-node-01` физически вышел из строя. Том `pgdata-postgres-ha-0` имеет `nodeAffinity` только к `worker-node-01`. Другие 5 узлов отвергнуты планировщиком из-за конфликта `volume node affinity conflict`.

**Решение (SRE Runbook):**
1. Убедиться, что кластерная репликация базы данных активна и мастер-роль перешла на `postgres-ha-1` или `postgres-ha-2`.
2. Если упавший сервер списан безвозвратно, разорвать привязку старого тома:

```bash
# Удалить зависший под и его привязанный PVC
kubectl delete pod postgres-ha-0 -n database --force --grace-period=0
kubectl delete pvc pgdata-postgres-ha-0 -n database
# → pod "postgres-ha-0" force deleted
# → persistentvolumeclaim "pgdata-postgres-ha-0" deleted
```

3. Контроллер `StatefulSet` немедленно создаст новый PVC `pgdata-postgres-ha-0`.
4. Благодаря `volumeBindingMode: WaitForFirstConsumer` планировщик выберет один из оставшихся рабочих узлов, создаст новый чистый `Local PV`, под перейдет в `Running`, а оператор СУБД (например, Patroni) выполнит начальную синхронизацию данных (pg_basebackup) с текущего лидера.

#### Инцидент 2: Блокировка тома Ceph RBD Multi-Attach при рестарте пода

**Диагностика:**

```bash
kubectl describe pod db-replicated-0 -n database
# → Events:
# →   Type     Reason              Age   From                     Message
# →   ----     ------              ----  ----                     -------
# →   Warning  FailedAttachVolume  2m    attachdetach-controller  Multi-Attach error for volume "pvc-11223344" Volume is already exclusively attached to one node (worker-node-02) and cannot be attached to another (worker-node-04)
```

**Решение:**
1. Проверить статус узла `worker-node-02`:

```bash
kubectl get node worker-node-02.infra.local
# → NAME                         STATUS     ROLES    AGE    VERSION
# → worker-node-02.infra.local   NotReady   worker   120d   v1.30.2
```

2. Если подтверждено, что узел отключен от сети и не выполняет запись:

```bash
kubectl taint nodes worker-node-02.infra.local node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
# → node/worker-node-02.infra.local tainted
```

3. Через 10–15 секунд проверить статус пода:

```bash
kubectl get pod db-replicated-0 -n database
# → NAME              READY   STATUS    RESTARTS   AGE
# → db-replicated-0   1/1     Running   0          3m12s
```

---

## Лучшие практики

### 1. Выбор StorageClass под тип рабочей нагрузки

* **Транзакционные OLTP-базы (PostgreSQL, MySQL, MariaDB):**
  * Для высоконагруженных систем (>5 000 write IOPS, низкий p99): использовать **Local PV на NVMe** с драйвером `TopoLVM` или `sig-storage-local-static-provisioner`. Репликация должна обеспечиваться на уровне ПО СУБД (Patroni, Galera).
  * Для средненагруженных систем с критичностью простоты обслуживания: использовать **CSI Ceph RBD** на выделенных SSD/NVMe OSD-пулах.
* **Распределенные очереди и брокеры (Apache Kafka, RabbitMQ Quorum):**
  * Использовать **Local PV**. Сетевая репликация брокеров поверх сетевой репликации Ceph/Longhorn создает тройной оверхед на сеть и диски (write amplification 3x3 = 9x).
* **Аналитические СУБД (ClickHouse):**
  * Использовать **Local PV**. Движок MergeTree рассчитан на локальные блочные диски и самостоятельно управляет шардированием и репликацией данных.

### 2. Защита персистентных томов (Data Safety)

* Всегда устанавливать `reclaimPolicy: Retain` в production `StorageClass`. При случайном удалении `StatefulSet` или PVC физический том и данные на диске останутся целыми и перейдут в статус `Released`, исключая безвозвратную потерю.
* При использовании CSI для StatefulSet применять `accessModes: ["ReadWriteOncePod"]` вместо `ReadWriteOnce`. Это на уровне ядра Kubernetes блокирует одновременный запуск двух реплик одного пода при сбоях сети.

### 3. Гарантии размещения подов (Anti-Affinity)

* Для `StatefulSet` с `Local PV` обязательна директива `podAntiAffinity` с `topologyKey: kubernetes.io/hostname` в режиме `requiredDuringSchedulingIgnoredDuringExecution`.
* Размещение двух подов реплицируемой базы на одном физическом сервере лишает кластер отказоустойчивости: при сбое этого сервера будут потеряны обе реплики.

### 4. Мониторинг и алертинг

* Контролировать метрики заполнения разделов:
  * `kubelet_volume_stats_available_bytes` / `kubelet_volume_stats_capacity_bytes` — предупредительный алерт при заполнении тома > 80%.
  * `kubelet_volume_stats_inodes_free` — алерт на исчерпание inode (критично для очередей сообщений и сессий).
* Для Ceph CSI отслеживать задержки операций:
  * Метрики `csi_operations_seconds_bucket` — время выполнения операций `StageVolume`, `UnstageVolume`, `NodePublishVolume`.

---

## Дополнительная информация

### Ссылки на связанные разделы базы знаний

* **[StorageClass](../../Storage/storageclass.md)** — детальная настройка параметров провижининга и политик утилизации.
* **[PV и PVC](../../Storage/pv_and_pvc.md)** — жизненный цикл персистентных ресурсов и фазы связывания.
* **[Сравнение CSI-драйверов](../../Storage/CSI/csi_drivers_comparison.md)** — архитектура, возможности и ограничения Ceph RBD, Longhorn, TopoLVM.
* **[Паттерны хранения для баз данных](../../Storage/database-storage-patterns.md)** — тюнинг файловых систем, вынос WAL на выделенные диски.
* **[TopoLVM и LVM в Kubernetes](../../../Linux/FileSystems/LVM/advanced_topics/lvm_kubernetes_storage.md)** — настройка локальных LVM-томов с тонким пулом.
* **[Диагностика подсистемы хранения](../../Storage/k8s-storage-troubleshooting.md)** — детальный траблшутинг ошибок монтирования и отсоединения томов.
* **[Ключевые концепции StatefulSet](./statefulset_core_concepts.md)** — сетевая идентичность, ordered ready и жизненный цикл подов.
* **[Лучшие практики StatefulSet](./statefulset_best_practices.md)** — эксплуатация баз данных и брокеров в production.

### Итоговая матрица рекомендаций для типовых баз данных

| СУБД / Сервис | Рекомендуемое хранилище | Механизм репликации | Обоснование выбора |
| :--- | :--- | :--- | :--- |
| **PostgreSQL (OLTP)** | Local PV (NVMe) | Patroni (Streaming Replication) | Минимальная задержка commit/fsync (<0.1 мс). Репликация на уровне СУБД. |
| **PostgreSQL (Failover-only)** | Ceph RBD (CSI) | СХД (Ceph replication 3x) | Для баз без встроенного HA: перенос пода на исправный узел при сбое. |
| **MySQL / MariaDB** | Local PV (NVMe) | Orchestrator / Galera Cluster | Максимальный IOPS транзакций InnoDB. |
| **Apache Kafka** | Local PV (NVMe/SSD) | Встроенный репликатор Kafka (ISR) | Предотвращение тройного сетевого оверхеда SDS. Высокая пропускная способность. |
| **ClickHouse** | Local PV (NVMe) | ClickHouse Keeper + ReplicatedMergeTree | Оптимизация под параллельный блочный I/O локальных NVMe. |
| **Redis (Persistent)** | Local PV (NVMe) | Redis Sentinel / Cluster | Субмиллисекундная запись AOF/RDB. |
| **etcd / ZooKeeper** | Local PV (NVMe) | Raft / Zab консенсус | Крайняя чувствительность к задержкам дискового fsync (heartbeat timeout). |
| **Elasticsearch / OpenSearch** | Local PV или Ceph RBD | Shard Replication (Index level) | Local PV для Data Hot nodes; Ceph RBD для Warm/Cold nodes. |
| **RabbitMQ** | Local PV или Ceph RBD | Quorum Queues (Raft) | Кворумные очереди обеспечивают надежность при локальных дисках. |
