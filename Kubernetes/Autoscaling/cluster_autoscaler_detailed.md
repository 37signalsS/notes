# Cluster Autoscaler (CA)

**Актуально для:** Kubernetes 1.30–1.33 / Cluster Autoscaler 1.30.x–1.33.x

## Определения

**Cluster Autoscaler (CA)** — это базовый контроллер Kubernetes, предназначенный для автоматического изменения размера вычислительного кластера (количества рабочих узлов). Решение о масштабировании принимается исключительно на основе анализа дефицита ресурсов подов (`requests`) в очереди планировщика, а не на основе фактической загрузки CPU/RAM узлов.

**Node Group (MachineDeployment / MachineSet)** — логическое объединение идентичных виртуальных или физических машин (одинаковый профиль оборудования, дисковая подсистема, метки и taints), управляемое инфраструктурным провайдером (например, Cluster API в on-premise средах). CA управляет кластером через абстракцию групп узлов.

**Expander** — алгоритмическая стратегия выбора целевой группы узлов при масштабировании вверх (Scale-Up), когда несколько доступных групп способны разместить поды в состоянии `Pending`.

**ProvisioningRequest** — механизм и CRD (`autoscaling.x-k8s.io`, статус Beta в Kubernetes 1.30+), позволяющий декларативно запрашивать выделение пула узлов заданной конфигурации до фактического создания подов, что необходимо для пакетных вычислительных задач (batch/ETL).

**Dynamic Resource Allocation (DRA)** — фреймворк Kubernetes для запроса специализированных аппаратных ресурсов (сетевые адаптеры SR-IOV, DPU, FPGA, локальные NVMe-диски). Начиная с Kubernetes 1.32 (Structured Parameters, KEP-4381), CA поддерживает симуляцию доступности DRA-ресурсов при принятии решений о масштабировании.

**Scale-Down Cooldown** — интервал защитной паузы после завершения операций масштабирования, предотвращающий «флаппинг» (циклическое добавление и немедленное удаление серверов).

**Pod Disruption Budget (PDB)** — ресурс политики доступности (`policy/v1`), определяющий минимально допустимое количество готовых реплик приложения при добровольном выселении подов во время сжатия кластера (Scale-Down) или обновления узлов.

**Over-provisioning (Pause Pods)** — архитектурный паттерн создания «горячего резерва» вычислительных мощностей с помощью низкоприоритетных спящих подов, вытесняемых реальной рабочей нагрузкой при всплесках трафика.

---

## Архитектура и принцип работы

### Двухуровневая архитектура масштабирования в On-Premise инфраструктуре

В отказоустойчивой инфраструктуре Kubernetes разделяются два контура управления:
1. **Control Plane (API-сервер, etcd, Scheduler, Controller Manager):** Разворачивается на выделенных статических серверах или отказоустойчивых виртуальных машинах (через kubeadm, RKE2 или Talos Linux) и не масштабируется автоматически через CA во избежание деградации кворума etcd.
2. **Data Plane (Worker Nodes):** Масштабируется автоматически контроллером **Cluster Autoscaler** в связке с провайдером инфраструктуры — в частных ЦОД и на bare-metal стандартным интерфейсом выступает **Cluster API (CAPI)** с провайдерами для vSphere (CAPV), Bare-Metal (Metal3 / Ironic) или OpenStack (CAPO).

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Kubernetes Control Plane                        │
│                                                                        │
│   ┌─────────────────────┐                 ┌────────────────────────┐   │
│   │   kube-apiserver    │◄────────────────┤   Cluster Autoscaler   │   │
│   │  (Pending Pods /    │                 │ (Simulation & Decision)│   │
│   │   Nodes / Metrics)  │                 └───────────┬────────────┘   │
│   └──────────┬──────────┘                             │                │
└──────────────┼────────────────────────────────────────┼────────────────┘
               │                                        │
               ▼                                        ▼
    ┌──────────────────────┐               ┌─────────────────────────┐
    │   kube-scheduler     │               │   Cluster API (CAPI)    │
    │  (Filters / Scoring) │               │ MachineDeployment Scale │
    └──────────────────────┘               └────────────┬────────────┘
                                                        │
                      ┌─────────────────────────────────┴─────────────┐
                      ▼                                               ▼
          ┌───────────────────────────┐                   ┌───────────────────────────┐
          │  Bare-Metal (Metal3/IPMI) │                   │  Virtualization (vSphere) │
          │  Physical Server PXE-boot │                   │  VM Clone / Provisioning  │
          └───────────────────────────┘                   └───────────────────────────┘
```

### Внутренний цикл управления (Autoscaling Loop)

CA работает как непрерывный управляющий цикл (по умолчанию период сканирования `--scan-interval=10s`):
1. **Сбор состояния (Listing):** Запрос к API-серверу списка узлов, подов, PDB, PVC, PV и шаблонов групп узлов (`MachineDeployment`).
2. **Анализ Unschedulable подов:** Отбор подов в статусе `Pending`, получивших от `kube-scheduler` событие `FailedScheduling` (нехватка CPU, памяти, несовпадение `nodeSelector`, `affinity` или `taints`).
3. **Симуляция планирования (Scheduler Simulation):** CA запускает встроенный алгоритм планировщика. Для каждой доступной группы узлов проверяется: если создать узел из этого шаблона, поместятся ли на нем `Pending` поды с учетом всех ограничений?
4. **Выбор группы (Expander):** Если поды могут быть размещены в нескольких группах узлов, применяется алгоритм Expander.
5. **Масштабирование вверх (Scale-Up):** CA отправляет запрос к инфраструктурному контроллеру (например, увеличивает `.spec.replicas` в `MachineDeployment`).
6. **Анализ недогруженных узлов (Scale-Down Evaluation):** Поиск узлов, суммарные `requests` которых ниже `--scale-down-utilization-threshold`. Если поды узла можно безопасно перенести на другие работающие серверы, запускается таймер невостребованности.
7. **Масштабирование вниз (Scale-Down Drain & Delete):** По истечении таймера узел помечается taint `ToBeDeletedByClusterAutoscaler`, выполняется выселение подов через Eviction API, после чего узел безопасно удаляется из инфраструктуры.

### Алгоритм симуляции планировщика

CA не опрашивает внешний `kube-scheduler`, а использует скомпилированные библиотеки логики планировщика Kubernetes. При симуляции проверяются:
- **Емкость узла (Capacity & Allocatable):** Из общей емкости вычитаются системные резервы `kube-reserved` и `system-reserved`, а также ресурсы DaemonSet, которые автоматически запустятся на новом узле.
- **Tolerations и Taints:** Проверяется совпадение taints шаблона группы узлов с tolerations подов.
- **Node Affinity и Node Selector:** Проверяются обязательные (`requiredDuringSchedulingIgnoredDuringExecution`) селекторы меток.
- **Pod Affinity и Pod Anti-Affinity:** Симулируется взаимное размещение подов на новом и существующих узлах кластера с учетом топологических ключей (`topologyKey`).
- **Topology Spread Constraints:** Проверяется максимальный допустимый перекос (`maxSkew`) между доменами отказа (стойками, зонами).
- **Связывание томов (Volume Binding):** Для `StorageClass` с `volumeBindingMode: WaitForFirstConsumer` симулируется возможность создания PV в топологическом сегменте нового узла.
- **DRA (Dynamic Resource Allocation):** Начиная с версии 1.32, CA поддерживает структурированные параметры `ResourceClaim` и проверяет возможность их аллокации драйвером оборудования.

### Механизм масштабирования вверх (Scale-Up)

Триггером для Scale-Up служит наличие хотя бы одного пода в состоянии `Pending`, для которого планировщик зафиксировал невозможность запуска.
- Если узел можно добавить, CA увеличивает целевой размер группы (`DesiredCapacity` / `.spec.replicas`).
- Если узел находится в статусе создания дольше `--max-node-provision-time` (по умолчанию 15 минут) и не переходит в `Ready`, CA регистрирует ошибку и временно блокирует дальнейшие попытки добавления узлов в эту группу.
- Время инициализации в локальных дата-центрах варьируется от 2–5 минут для виртуальных машин до 15–30 минут для bare-metal серверов (PXE-boot, инициализация RAID и IPMI).

### Механизм масштабирования вниз (Scale-Down)

Узел признается кандидатом на удаление, если выполняются **все** следующие условия:
1. Утилизация по сумме `requests` (CPU и RAM отдельно) строго ниже `--scale-down-utilization-threshold` (по умолчанию 0.5, то есть 50%).
2. Все поды узла могут быть перемещены на оставшиеся узлы кластера без перегрузки последних и без нарушения ограничений планирования.
3. Узел находится в состоянии недостаточной загрузки непрерывно в течение `--scale-down-unneeded-time` (по умолчанию 10 минут).

### Факторы, блокирующие Scale-Down

CA **не будет** удалять узел, если на нем обнаружен хотя бы один из следующих блокирующих факторов:
- **Pod Disruption Budget:** Нарушение лимита PDB (поле `.status.disruptionsAllowed == 0` у целевого приложения).
- **Аннотация safe-to-evict:** Наличие пода с аннотацией `"cluster-autoscaler.kubernetes.io/safe-to-evict": "false"`.
- **Локальное хранилище (Local Storage):** Поды, использующие `emptyDir` или `hostPath`, если не выставлен флаг `--skip-nodes-with-local-storage=false`.
- **Поды без контроллера:** Автономные поды (bare pods), созданные напрямую без Deployment, ReplicaSet, StatefulSet или Job (их удаление приведет к безвозвратной потере рабочей нагрузки).
- **Системные поды:** Поды в namespace `kube-system`, у которых не настроен персональный PDB (если не выставлен флаг `--skip-nodes-with-system-pods=false`).
- **Аннотация узла:** Узел помечен аннотацией `"cluster-autoscaler.kubernetes.io/scale-down-disabled": "true"`.
- **Невозможность размещения:** Поды узла не могут разместиться на оставшихся серверах из-за нехватки свободных ресурсов или жестких правил `podAntiAffinity`.

### Алгоритмы выбора группы узлов (Expanders)

Если `Pending` под может быть размещен на узлах нескольких разных групп, CA применяет выбранный `Expander` (`--expander`):

| Стратегия | Принцип работы | Сценарий применения в On-Premise / Sysadmin |
| :--- | :--- | :--- |
| **`random`** | Выбирает случайную подходящую группу (по умолчанию). | Кластеры с однородными серверами одинаковой конфигурации. |
| **`most-pods`** | Выбирает группу, способную вместить максимальное количество текущих `Pending` подов. | Массовые параллельные деплои микросервисов. |
| **`least-waste`** | Выбирает группу, в которой после размещения подов останется минимальный объем неиспользованных CPU и RAM. | Максимизация плотности упаковки (bin-packing) и экономия емкости гипервизора/железа. |
| **`priority`** | Выбирает группу с наивысшим приоритетом на основе регулярных выражений из ConfigMap. | Разделение пулов серверов по поколениям (High-Performance → Standard → Cold Reserve). |

> **Примечание:** Стратегия `price` (ценовая оптимизация) поддерживается исключительно для публичных облаков с интеграцией в их Billing API и не применима в on-premise инфраструктуре.

---

## Установка и конфигурация

### Матрица совместимости версий

Версия Cluster Autoscaler строго привязана к минорной версии Kubernetes, так как CA использует внутренние структуры данных и типы планировщика соответствующего релиза.

| Версия Kubernetes | Рекомендуемая версия CA | Поддержка API и возможностей |
| :--- | :--- | :--- |
| **1.33.x** | `registry.k8s.io/autoscaling/cluster-autoscaler:v1.33.0` | DRA Structured Parameters, In-Place Pod Resize (Beta) |
| **1.32.x** | `registry.k8s.io/autoscaling/cluster-autoscaler:v1.32.0` | Удаление старого DRA API, обязательный Structured Parameters |
| **1.31.x** | `registry.k8s.io/autoscaling/cluster-autoscaler:v1.31.0` | Стабильный статус CAPI v1.7+, поддержка SchedulingGates |
| **1.30.x** | `registry.k8s.io/autoscaling/cluster-autoscaler:v1.30.0` | ProvisioningRequest (Beta), базовая поддержка NodeSwap |

### Feature Gates

| Feature Gate | Статус в 1.30–1.33 | Влияние на Cluster Autoscaler |
| :--- | :--- | :--- |
| `InPlacePodVerticalScaling` | Beta (1.33+) | Учитывает динамическое изменение `requests` контейнеров без перезапуска подов при симуляции емкости узлов. |
| `DynamicResourceAllocation` | Beta (1.32+) | Симуляция структурированных параметров оборудования (DRA) при расчете Scale-Up. |
| `NodeSwap` | Beta (1.30+) | Учитывает доступную подкачку памяти узла при проверке лимитов `requests.memory`. |
| `SchedulingGates` | GA (1.30+) | Поды с активными scheduling gates блокируются и игнорируются CA до снятия гейта. |

### Минимальные RBAC-права (On-Premise / Cluster API)

Манифест создает сервисный аккаунт и кластерную роль, достаточную для взаимодействия с ядром Kubernetes, Storage API, Coordination API (Leases для HA) и объектами Cluster API (`MachineDeployment`, `MachineSet`, `Machine`).

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  labels:
    app.kubernetes.io/name: cluster-autoscaler
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cluster-autoscaler
rules:
  # Системные события и координация
  - apiGroups: [""]
    resources: ["events", "endpoints"]
    verbs: ["create", "patch"]
  - apiGroups: ["coordination.k8s.io"]
    resources: ["leases"]
    verbs: ["create", "get", "update"]
  # Выселение подов и мониторинг
  - apiGroups: [""]
    resources: ["pods/eviction"]
    verbs: ["create"]
  - apiGroups: [""]
    resources: ["pods/status"]
    verbs: ["update"]
  - apiGroups: [""]
    resources: ["endpointslices"]
    verbs: ["get", "list", "watch"]
  # Управление состоянием узлов и подов
  - apiGroups: [""]
    resources: ["nodes"]
    verbs: ["list", "watch", "get", "patch", "update"]
  - apiGroups: [""]
    resources: ["pods", "services", "replicationcontrollers", "persistentvolumeclaims", "persistentvolumes"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["daemonsets", "replicasets", "statefulsets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["policy"]
    resources: ["poddisruptionbudgets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["storage.k8s.io"]
    resources: ["storageclasses", "csinodes", "csidrivers", "csistoragecapacities"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["batch"]
    resources: ["jobs", "cronjobs"]
    verbs: ["get", "list", "watch"]
  # Декларативное выделение емкости (ProvisioningRequest)
  - apiGroups: ["autoscaling.x-k8s.io"]
    resources: ["provisioningrequests", "provisioningrequests/status"]
    verbs: ["get", "list", "watch", "update", "patch"]
  # Взаимодействие с инфраструктурным Cluster API (CAPI)
  - apiGroups: ["cluster.x-k8s.io"]
    resources: ["machinedeployments", "machinesets", "machines", "machinepools"]
    verbs: ["get", "list", "watch", "create", "update", "delete", "patch"]
  - apiGroups: ["cluster.x-k8s.io"]
    resources: ["machinedeployments/scale", "machinesets/scale"]
    verbs: ["get", "update", "patch"]
  - apiGroups: ["cluster.x-k8s.io"]
    resources: ["machines/status", "machinesets/status", "machinedeployments/status"]
    verbs: ["get", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: cluster-autoscaler
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-autoscaler
subjects:
  - kind: ServiceAccount
    name: cluster-autoscaler
    namespace: kube-system
```

### Параметры запуска (Флаги командной строки)

| Флаг | Значение по умолчанию | Описание и влияние на эксплуатацию |
| :--- | :--- | :--- |
| `--cloud-provider` | `clusterapi` | Инфраструктурный драйвер. Для On-Premise используется `clusterapi` (или `kubemark` для стендовых нагрузочных тестов). |
| `--node-group-auto-discovery` | (пусто) | Формат автоматического обнаружения групп: `clusterapi:machinedeployments.cluster.x-k8s.io/asg-pool-` или по меткам. |
| `--scan-interval` | `10s` | Частота опроса API-сервера и цикла симуляции планировщика. |
| `--scale-down-enabled` | `true` | Глобальный переключатель механизма сжатия кластера. При авариях переводится в `false`. |
| `--scale-down-utilization-threshold` | `0.5` | Порог относительной утилизации ресурсов узла (сумма `requests` / Allocatable). Ниже порога — кандидат на удаление. |
| `--scale-down-unneeded-time` | `10m` | Время непрерывной недогрузки узла перед началом процедуры drain. |
| `--scale-down-delay-after-add` | `10m` | Защитный период после добавления любого узла, в течение которого scale-down заморожен. |
| `--scale-down-delay-after-delete` | `0s` | Пауза после удаления узла перед следующим удалением в той же группе. |
| `--scale-down-delay-after-failure` | `3m` | Защитная пауза после сбоя попытки удаления узла. |
| `--scale-down-non-empty-candidates-count` | `30` | Лимит непустых узлов, анализируемых на удаление за один цикл (снижает CPU overhead CA). |
| `--max-node-provision-time` | `15m` | Максимальное время ожидания регистрации нового узла в кластере до фиксации ошибки. Для bare-metal рекомендуется увеличивать до `25m–30m`. |
| `--max-graceful-termination-sec` | `600` | Максимальное время ожидания корректного завершения подов при drain перед принудительным выселением. |
| `--max-nodes-total` | `0` (безлимитно) | Жесткий лимит на максимальное суммарное число рабочих узлов во всем кластере. |
| `--min-node-count` | `0` | Минимальное число узлов, поддерживаемое CA. |
| `--expander` | `random` | Стратегия выбора группы узлов при Scale-Up (`random`, `most-pods`, `least-waste`, `priority`). |
| `--balance-similar-node-groups` | `false` | Автоматическая балансировка числа узлов между похожими группами (критично для распределения по стойкам/ЦОД). |
| `--skip-nodes-with-system-pods` | `true` | Запрет удаления узлов, на которых запущены поды из `kube-system` без настроенного PDB. |
| `--skip-nodes-with-local-storage` | `true` | Запрет удаления узлов с подами, монтирующими `emptyDir` или `hostPath`. В современных CSI рекомендуется выставлять в `false`. |
| `--expendable-pods-priority-cutoff` | `-10` | Поды с приоритетом ниже или равным cutoff выселяются принудительно без соблюдения PDB. |
| `--leader-elect` | `true` | Включение механизма Leader Election для обеспечения High Availability нескольких реплик CA. |
| `--leader-elect-lease-duration` | `15s` | Длительность удержания лидерского Lease-объекта в `coordination.k8s.io`. |
| `--leader-elect-renew-deadline` | `10s` | Максимальный интервал продления аренды лидером перед передачей роли. |
| `--leader-elect-retry-period` | `2s` | Интервал повторных попыток перехвата лидерства резервными репликами. |
| `--cluster-autoscaler-status-config-map` | `cluster-autoscaler-status` | Имя ConfigMap в namespace `kube-system` для записи сводного диагностического отчета. |

### Развёртывание в On-Premise через Kustomize

Промышленный манифест развертывания CA в HA-режиме (две реплики с Leader Election, строгий non-root SecurityContext, мониторинг через порт 8085).

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  labels:
    app.kubernetes.io/name: cluster-autoscaler
spec:
  replicas: 2
  revisionHistoryLimit: 3
  selector:
    matchLabels:
      app.kubernetes.io/name: cluster-autoscaler
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app.kubernetes.io/name: cluster-autoscaler
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8085"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: cluster-autoscaler
      priorityClassName: system-cluster-critical
      securityContext:
        runAsNonRoot: true
        runAsUser: 65534
        runAsGroup: 65534
        fsGroup: 65534
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: cluster-autoscaler
          image: registry.k8s.io/autoscaling/cluster-autoscaler:v1.33.0
          imagePullPolicy: IfNotPresent
          command:
            - ./cluster-autoscaler
            - --v=4
            - --stderrthreshold=info
            - --cloud-provider=clusterapi
            - --node-group-auto-discovery=clusterapi:machinedeployments.cluster.x-k8s.io/pool-
            - --expander=least-waste
            - --balance-similar-node-groups=true
            - --skip-nodes-with-local-storage=false
            - --scale-down-utilization-threshold=0.5
            - --scale-down-unneeded-time=10m
            - --scale-down-delay-after-add=10m
            - --max-node-provision-time=20m
            - --leader-elect=true
            - --leader-elect-lease-duration=15s
            - --leader-elect-renew-deadline=10s
            - --leader-elect-retry-period=2s
            - --cluster-autoscaler-status-config-map=cluster-autoscaler-status
            - --address=0.0.0.0
            - --port=8085
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 1Gi
          livenessProbe:
            httpGet:
              path: /health-check
              port: 8085
            initialDelaySeconds: 30
            periodSeconds: 15
            timeoutSeconds: 5
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /health-check
              port: 8085
            initialDelaySeconds: 10
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 2
          ports:
            - name: metrics
              containerPort: 8085
              protocol: TCP
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
```

---

## Практические сценарии

### Сценарий 1: Избыточное резервирование (Over-provisioning) через Pause Pods

В локальных дата-центрах запуск физических или виртуальных узлов занимает от нескольких минут до получаса. Для обеспечения мгновенного выделения ресурсов критическим сервисам применяется паттерн с поглощающими подами (`Pause Pods`) и отрицательным приоритетом.

1. **Создание низкоприоритетного класса планирования:**
```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: overprovisioning-reserve
value: -10
globalDefault: false
description: "Приоритет резервных pause-подов для горячего запаса узлов"
```

2. **Развертывание резервирующего Deployment:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-overprovisioning
  namespace: kube-system
spec:
  replicas: 4
  selector:
    matchLabels:
      app: cluster-overprovisioning
  template:
    metadata:
      labels:
        app: cluster-overprovisioning
    spec:
      priorityClassName: overprovisioning-reserve
      terminationGracePeriodSeconds: 0
      containers:
        - name: reserve
          image: registry.k8s.io/pause:3.10
          resources:
            requests:
              cpu: "2"
              memory: "8Gi"
            limits:
              cpu: "2"
              memory: "8Gi"
```

*Механика работы:* Резервные поды суммарно занимают 8 CPU и 32Gi RAM на рабочих узлах. Когда в кластер поступает рабочий под с нормальным приоритетом (по умолчанию 0 или выше), `kube-scheduler` выполняет вытеснение (Preemption) pause-пода. Рабочий под запускается **мгновенно** на освободившемся месте, а вытесненный pause-под переходит в статус `Pending`, запуская фоновый Scale-Up нового узла через CA.

### Сценарий 2: Приоритетный выбор пулов серверов (Priority Expander)

При наличии разных пулов инфраструктуры (например, высокопроизводительные физические серверы с быстрыми CPU, стандартные виртуальные машины и холодный резервный кластер гипервизоров) CA запускается с флагом `--expander=priority`.

1. **Конфигурация ConfigMap с весами пулов:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-autoscaler-priority-expander
  namespace: kube-system
data:
  priorities: |-
    100:
      - .*pool-highperf-baremetal.*   # Высший приоритет: первичное заполнение
    50:
      - .*pool-standard-vms.*         # Средний приоритет: стандартная виртуализация
    10:
      - .*pool-cold-standby.*         # Резервный пул при исчерпании основных
```

2. **Проверка компиляции регулярных выражений:**
```bash
kubectl get configmap cluster-autoscaler-priority-expander -n kube-system -o jsonpath='{.data.priorities}'
# → 100:
# →   - .*pool-highperf-baremetal.*
# → 50:
# →   - .*pool-standard-vms.*
# → 10:
# →   - .*pool-cold-standby.*
```

### Сценарий 3: Защита критических узлов и подов от Scale-Down

Для узлов с базами данных, брокерами сообщений или узлов с долгими сессиями необходимо гарантировать защиту от выселения при сжатии кластера.

1. **Защита конкретного узла через аннотацию:**
```bash
kubectl annotate node worker-db-01.infra.local \
  cluster-autoscaler.kubernetes.io/scale-down-disabled="true" --overwrite
# → node/worker-db-01.infra.local annotated
```

2. **Защита пода от выселения в манифесте приложения:**
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: clickhouse-keeper
  namespace: infra-storage
spec:
  replicas: 3
  selector:
    matchLabels:
      app: clickhouse-keeper
  template:
    metadata:
      labels:
        app: clickhouse-keeper
      annotations:
        # CA откажется перемещать данный под при поиске кандидатов на scale-down
        cluster-autoscaler.kubernetes.io/safe-to-evict: "false"
    spec:
      containers:
        - name: keeper
          image: clickhouse/clickhouse-keeper:24.3
          resources:
            requests:
              cpu: "1"
              memory: "2Gi"
```

### Сценарий 4: Корректное завершение работы (Graceful Shutdown) и PDB при дренаже

При Scale-Down CA инициирует выселение подов. Приложения должны корректно завершать активные транзакции, а PDB обязан гарантировать непрерывность кворума.

1. **Настройка PodDisruptionBudget:**
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: order-service-pdb
  namespace: production
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: order-service
```

2. **Настройка жизненного цикла пода в Deployment:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-service
  namespace: production
spec:
  replicas: 3
  template:
    metadata:
      labels:
        app: order-service
    spec:
      terminationGracePeriodSeconds: 45
      containers:
        - name: app
          image: internal-registry.local/apps/order-service:v2.1
          lifecycle:
            preStop:
              exec:
                # Пауза для исключения endpoint из балансировщика Ingress до снятия приложения
                command: ["/bin/sh", "-c", "sleep 10"]
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
```

3. **Проверка эмуляции безопасного выселения перед регламентными работами:**
```bash
kubectl drain worker-04.infra.local --ignore-daemonsets --delete-emptydir-data --dry-run=client
# → Evacuating node worker-04.infra.local (dry-run)
# → evicting pod production/order-service-789bf-qwert
# → node/worker-04.infra.local drained (dry-run)
```

### Сценарий 5: StatefulSet с `volumeBindingMode: WaitForFirstConsumer` и Ceph RBD / CSI

При использовании локального распределенного блочного хранилища (Ceph RBD / Rook) связывание тома PV должно откладываться до выбора узла планировщиком, иначе под окажется привязан к топологической зоне, где нет свободных вычислительных узлов.

1. **StorageClass с отложенным связыванием:**
```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-rbd-wffc
provisioner: rbd.csi.ceph.com
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
allowVolumeExpansion: true
parameters:
  clusterID: 4a259c0e-cfa1-4be6-976d-123456789abc
  pool: kubernetes-pool
  imageFeatures: layering
  csi.storage.k8s.io/provisioner-secret-name: csi-rbd-secret
  csi.storage.k8s.io/provisioner-secret-namespace: ceph-system
  csi.storage.k8s.io/node-publish-secret-name: csi-rbd-secret
  csi.storage.k8s.io/node-publish-secret-namespace: ceph-system
```

2. **Взаимодействие CA и StatefulSet:**
- При масштабировании StatefulSet под #3 переходит в `Pending`.
- Благодаря `volumeBindingMode: WaitForFirstConsumer` PVC не привязывается к случайному узлу.
- CA в цикле симуляции видит требование тома, симулирует создание узла в подходящей стойке/пуле оборудования, добавляет узел через `MachineDeployment`.
- После регистрации узла `kube-scheduler` назначает под на новый сервер, и CSI-драйвер монтирует том непосредственно к нему.

### Сценарий 6: ProvisioningRequest для пакетных вычислений и ETL-задач

Для тяжелых распределенных задач обработки данных (ETL, пакетная обработка очередей) недопустим старт вычислений по частям. `ProvisioningRequest` позволяет подготовить группу узлов атомарно до фактического запуска контейнеров.

```yaml
apiVersion: autoscaling.x-k8s.io/v1
kind: ProvisioningRequest
metadata:
  name: nightly-etl-processing
  namespace: data-platform
spec:
  provisioningClassName: "best-effort-atomic-scale-up.autoscaling.x-k8s.io"
  validUntilSeconds: 1800
  podSets:
    - name: workers
      count: 8
      podTemplateRef:
        apiVersion: v1
        kind: PodTemplate
        name: etl-worker-template
      resources:
        requests:
          cpu: "8"
          memory: "32Gi"
---
apiVersion: v1
kind: PodTemplate
metadata:
  name: etl-worker-template
  namespace: data-platform
template:
  spec:
    nodeSelector:
      hardware-tier: high-memory
    containers:
      - name: etl-runner
        image: internal-registry.local/data/etl-runner:v3.0
        resources:
          requests:
            cpu: "8"
            memory: "32Gi"
        command: ["/bin/sh", "-c", "sleep infinity"]
    restartPolicy: Never
```

**Проверка статуса готовности пула узлов:**
```bash
kubectl get provisioningrequest nightly-etl-processing -n data-platform -o yaml
# → status:
# →   conditions:
# →   - type: Provisioned
# →     status: "True"
# →     reason: "ScaleUpSucceeded"
# →   - type: CapacityAvailable
# →     status: "True"
```

### Сценарий 7: Шардинг Cluster Autoscaler в крупных On-Premise кластерах

В кластерах масштаба >500–1000 рабочих узлов единый инстанс CA испытывает задержки из-за сериализации симуляций планировщика. Решением является разделение (шардинг) инстансов CA по доменам отказа (стойкам, серверам дата-центра) или по namespace.

```yaml
# Шард 1: Контролирует пул узлов в стойках первой серверной группы
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler-rack-a
  namespace: kube-system
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: cluster-autoscaler
          image: registry.k8s.io/autoscaling/cluster-autoscaler:v1.33.0
          command:
            - ./cluster-autoscaler
            - --cloud-provider=clusterapi
            - --node-group-auto-discovery=clusterapi:machinedeployments.cluster.x-k8s.io/rack-a-
            - --leader-elect=false
            - --port=8085
```

```yaml
# Шард 2: Контролирует пул узлов во второй группе стоек
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler-rack-b
  namespace: kube-system
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: cluster-autoscaler
          image: registry.k8s.io/autoscaling/cluster-autoscaler:v1.33.0
          command:
            - ./cluster-autoscaler
            - --cloud-provider=clusterapi
            - --node-group-auto-discovery=clusterapi:machinedeployments.cluster.x-k8s.io/rack-b-
            - --leader-elect=false
            - --port=8086
```

> **Правило:** При шардинге по группам узлов флаг `--leader-elect` устанавливается в `false`, так как каждый инстанс управляет непересекающимся набором `MachineDeployment`.

### Сценарий 8: Координация с ResourceQuota и LimitRange

Если в Namespace настроены жесткие квоты, при росте нагрузки поды могут оставаться в статусе `Pending` не из-за нехватки физических узлов, а из-за отказа API-сервера создавать поды (`exceeded quota`). CA в этом случае не может помочь, а кластер рискует зависнуть в дедлоке.

1. **Расчет безопасной квоты с учетом масштабирования:**
   `ResourceQuota.requests.cpu >= (maxReplicas HPA × requests.cpu) × 1.25`

2. **Пример согласованного манифеста ResourceQuota:**
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: backend-quota
  namespace: production
spec:
  hard:
    requests.cpu: "32"
    requests.memory: 64Gi
    limits.cpu: "64"
    limits.memory: 128Gi
    pods: "50"
```

3. **Диагностика конфликтов квоты:**
```bash
kubectl get events -n production --field-selector reason=FailedCreate --sort-by='.lastTimestamp'
# → Warning  FailedCreate  replicaset/api-backend-6789  Error creating: pods "api-backend-6789-abc" is forbidden: exceeded quota: backend-quota, requested: requests.cpu=2, used: requests.cpu=31, limited: requests.cpu=32
```

---

## Операции и команды

Сводный перечень команд для повседневного администрирования, мониторинга и регламентных процедур SRE/DevOps.

### Проверка состояния и диагностических событий CA

```bash
# 1. Просмотр системных событий, сгенерированных Cluster Autoscaler
kubectl get events -A --field-selector source=cluster-autoscaler --sort-by='.lastTimestamp'
# → kube-system  10m  Normal  ScaledUpGroup  pod/api-worker-1  Scale-up: group pool-vms-01 size set to 8

# 2. Проверка статуса лидера (Leader Election Lease)
kubectl get lease cluster-autoscaler -n kube-system
# → NAME                 HOLDER                                                AGE
# → cluster-autoscaler   cluster-autoscaler-58f79fbc94-w2r6d_8ab12e34-5678     45d

# 3. Чтение агрегированного отчета статуса CA из ConfigMap
kubectl get cm cluster-autoscaler-status -n kube-system -o yaml
# → data:
# →   status: |
# →     Cluster-autoscaler status at 2026-10-12 18:00:00:
# →     Cluster-wide:
# →       Health:      Healthy (ready=24 unready=0 kernelMounterReady=24)
# →       ScaleUp:     NoActivity
# →       ScaleDown:   NoCandidates
```

### Анализ подов и причин блокировки масштабирования

```bash
# 4. Поиск Unschedulable подов в кластере
kubectl get pods -A --field-selector status.phase=Pending -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,NODE:.spec.nodeName,REASON:.status.conditions[?(@.reason=="Unschedulable")].message
# → production  batch-worker-5  <none>  0/24 nodes are available: 24 Insufficient cpu.

# 5. Выявление невыселяемых узлов в логах активного пода CA
kubectl logs -n kube-system -l app.kubernetes.io/name=cluster-autoscaler --tail=200 | grep -E "unremovable|ScaleDown|NotTriggeredScaleUp"
# → I1012 18:02:15.123456 1 static_autoscaler.go:420] Fast evaluation: node worker-03 unremovable: pod production/db-0 has safe-to-evict=false

# 6. Проверка PDB, блокирующих выселение (allowedDisruptions == 0)
kubectl get pdb -A -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,ALLOWED:.status.disruptionsAllowed,EXPECTED:.status.expectedPods
# → default     redis-cluster   0       3
```

### Регламентные процедуры управления узлами

```bash
# 7. Аварийная заморозка Scale-Down на конкретном узле
kubectl annotate node worker-compute-05.infra.local cluster-autoscaler.kubernetes.io/scale-down-disabled="true" --overwrite
# → node/worker-compute-05.infra.local annotated

# 8. Снятие блокировки Scale-Down
kubectl annotate node worker-compute-05.infra.local cluster-autoscaler.kubernetes.io/scale-down-disabled-
# → node/worker-compute-05.infra.local annotation removed

# 9. Проверка доступности метрик на порту 8085
kubectl exec -n kube-system deploy/cluster-autoscaler -- wget -qO- http://127.0.0.1:8085/metrics | grep cluster_autoscaler_unschedulable_pods_count
# → # HELP cluster_autoscaler_unschedulable_pods_count Number of unschedulable pods.
# → # TYPE cluster_autoscaler_unschedulable_pods_count gauge
# → cluster_autoscaler_unschedulable_pods_count 0
```

---

## Диагностика и устранение неполадок

### Матрица типовых проблем

| Симптом | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **Поды зависают в `Pending`, узлы не добавляются** | Достигнут лимит `--max-nodes-total` или квота `maxSize` группы. | `kubectl logs deploy/cluster-autoscaler -n kube-system \| grep maxNodes` | Увеличить лимит `--max-nodes-total` или `.spec.replicas` в `MachineDeployment`. |
| **Поды `Pending`, CA пишет `no matching node group`** | Поды требуют taints/labels/селекторы, которых нет в шаблоне `MachineDeployment`. | `kubectl describe pod <name>` и сопоставление с метками групп. | Добавить tolerations в поды или создать группу узлов с требуемыми метками. |
| **Узлы не удаляются при утилизации < 50%** | PDB блокирует выселение (`allowedDisruptions: 0`) или есть поды с local storage. | `kubectl get pdb -A` и поиск в логах по фразе `pod blocks scale-down`. | Настроить PDB; выставить флаг `--skip-nodes-with-local-storage=false`. |
| **Постоянный флаппинг (узлы добавляются и удаляются)** | Слишком короткий `--scale-down-unneeded-time` или рассинхронизация с HPA. | Сравнение метрик `scaled_up_nodes_total` и `evicted_pods_total`. | Увеличить `--scale-down-delay-after-add=15m` и настроить stabilization window в HPA. |
| **CA перестает реагировать на Pending-поды** | Потерян кворум лидера (Lease deadlock) или сетевая изоляция API-сервера. | `kubectl get lease cluster-autoscaler -n kube-system` | Проверить сетевую связность между узлами; перезапустить под CA. |
| **Bare-metal хосты не переходят в `Ready`** | Сбой PXE-загрузки, DHCP или IPMI контроллера Metal3. | `kubectl get baremetalhost -n metal3-system` | Проверить состояние BMC/IPMI хоста и логи Ironic. |

### Prometheus-метрики

| Метрика | Тип | Назначение для SRE-мониторинга |
| :--- | :--- | :--- |
| `cluster_autoscaler_nodes_count` | Gauge | Текущее количество узлов в кластере с разбивкой по статусам (`ready`, `unready`, `notStarted`). |
| `cluster_autoscaler_unschedulable_pods_count` | Gauge | Число подов в очереди, которые CA не может разместить. Значение > 0 дольше 5 минут сигнализирует об аварии. |
| `cluster_autoscaler_scale_down_in_cooldown` | Gauge | Флаг блокировки сжатия кластера (период cooldown после добавления узла). |
| `cluster_autoscaler_evicted_pods_total` | Counter | Суммарное количество подов, выселенных CA в рамках Scale-Down. |
| `cluster_autoscaler_scaled_up_nodes_total` | Counter | Счетчик успешно добавленных узлов. |
| `cluster_autoscaler_failed_scale_ups_total` | Counter | Количество сбоев при попытке масштабирования вверх (ошибки CAPI, таймауты boot). |
| `cluster_autoscaler_unremovable_nodes_count` | Gauge | Количество узлов, признанных недогруженными, но заблокированных от удаления (PDB, local storage). |
| `cluster_autoscaler_last_activity` | Gauge | Unix-время последнего успешного действия CA. Детектор зависания процесса. |
| `cluster_autoscaler_cluster_simulation_scheduling_step_duration_seconds` | Histogram | Длительность выполнения одного шага симуляции планировщика. |

### Prometheus-алерты (PrometheusRule)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: cluster-autoscaler-alerts
  namespace: kube-system
  labels:
    role: alert-rules
spec:
  groups:
    - name: cluster-autoscaler.rules
      rules:
        # Критический алерт: Сбои добавления узлов в инфраструктуре
        - alert: ClusterAutoscalerScaleUpFailed
          expr: increase(cluster_autoscaler_failed_scale_ups_total[10m]) > 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Сбой добавления узлов Cluster Autoscaler"
            description: "CA не смог добавить узел за последние 10 минут. Проверьте емкость гипервизора/пула bare-metal и логи MachineDeployment."

        # Предупреждение: Зависание подов в очереди планирования
        - alert: ClusterAutoscalerUnschedulablePodsStuck
          expr: cluster_autoscaler_unschedulable_pods_count > 0
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "Поды ожидают масштабирования более 15 минут"
            description: "{{ $value }} подов находятся в статусе Unschedulable. Возможно исчерпание лимита max-nodes-total или несовпадение меток."

        # Информационный алерт: Высокое количество заблокированных узлов
        - alert: ClusterAutoscalerHighUnremovableNodes
          expr: cluster_autoscaler_unremovable_nodes_count > 5
          for: 30m
          labels:
            severity: info
          annotations:
            summary: "Более 5 недогруженных узлов заблокированы от удаления"
            description: "Узлы не могут быть удалены из-за жестких PDB (allowedDisruptions=0) или подов с local-storage/safe-to-evict."
```

---

## Лучшие практики

1. **Честное задание `requests`:** CA оперирует исключительно значениями `requests`. Если разработчики завышают `requests`, кластер будет необоснованно раздуваться. Если `requests` занижены — возникнет переподписка (overcommit) и деградация производительности по CPU/OOMKills. Рекомендуется калибровать значения через VPA в режиме Recommendation.
2. **Обязательная настройка PDB для всех продакшн-сервисов:** Без PDB выселение при Scale-Down может снять все реплики сервиса одновременно. Всегда указывайте `minAvailable: 1` или `maxUnavailable: 1`.
3. **Отключение блокировки по Local Storage:** Современные сервисы часто используют временные каталоги `emptyDir` для кэшей. Устанавливайте флаг `--skip-nodes-with-local-storage=false`, иначе поды с `emptyDir` заблокируют удаление узлов.
4. **Синхронизация окон стабилизации:** При одновременном использовании HPA и CA настраивайте задержку `stabilizationWindowSeconds` в HPA на 5–10 минут, а `--scale-down-unneeded-time` в CA — минимум на 10–15 минут во избежание взаимных резонансных колебаний.
5. **Разделение отказоустойчивых доменов:** Включайте флаг `--balance-similar-node-groups=true`, чтобы узлы добавлялись равномерно по серверным стойкам и сегментам ЦОД.
6. **Высокая доступность CA:** Всегда развертывайте `replicas: 2` с включенным Leader Election (`--leader-elect=true`) и классом приоритета `system-cluster-critical`.
7. **Graceful Termination:** Убедитесь, что приложения корректно ловят сигнал `SIGTERM` и имеют достаточный `terminationGracePeriodSeconds` (30–60 секунд).

---

## Дополнительная информация

### Архитектурные взаимосвязи

- **Cluster API (CAPI):** Стандартный механизм декларативного управления инфраструктурой серверов для CA в On-Premise средах через ресурсы `MachineDeployment` и `MachineSet`.
- **Metal3 / Ironic:** Обеспечивает интеграцию с «голым железом» (Bare-Metal) через протоколы IPMI/Redfish и PXE-загрузку.
- **Descheduler:** Дополняет Cluster Autoscaler, принудительно выселяя поды со слабо загруженных узлов для ускорения консолидации и срабатывания Scale-Down.
- **VPA (Vertical Pod Autoscaler):** Оптимизирует `requests` контейнеров, обеспечивая корректные входные данные для алгоритма симуляции CA.

### Первоисточники и документация

- [Kubernetes Autoscaler Upstream Repository](https://github.com/kubernetes/autoscaler/tree/master/cluster-autoscaler) — официальный исходный код и документация параметров запуска.
- [Cluster Autoscaler FAQ](https://github.com/kubernetes/autoscaler/blob/master/cluster-autoscaler/FAQ.md) — авторитетный сборник edge cases и ответов разработчиков.
- [KEP-4381: Dynamic Resource Allocation Structured Parameters](https://github.com/kubernetes/enhancements/tree/master/keps/sig-node/4381-dra-structured-parameters) — спецификация параметров аппаратных ресурсов в планировщике и CA.
- [ProvisioningRequest Design Specification](https://github.com/kubernetes/autoscaler/blob/master/cluster-autoscaler/proposals/provisioning-request.md) — архитектура декларативного заказа вычислительной емкости.

### См. также

- [Pod Disruption Budget (PDB)](./pod_disruption_budget.md) — детальная настройка политик доступности при добровольном выселении подов.
- [Autoscaling в On-Premise / Bare-Metal средах](./on_premise_autoscaling.md) — обзор архитектур автомасштабирования на собственном оборудовании.
- [Vertical Pod Autoscaler (VPA)](./vpa_detailed.md) — вертикальное профилирование requests для корректного расчета емкости CA.
- [Descheduler](./descheduler.md) — дефрагментация кластера и балансировка нагрузки после масштабирования.
- [Мониторинг и алертинг автомасштабирования](./alerting_monitoring.md) — метрики и дашборды для мониторинга autoscaling-компонентов.
- [Горизонтальное масштабирование и шардинг](./sharding.md) — стратегии деления больших кластеров и шардинга контроллеров.
- [Изменение ресурсов подов без перезапуска (In-Place Pod Resize)](./in_place_pod_resize.md) — механизм вертикального масштабирования в K8s 1.33+.
