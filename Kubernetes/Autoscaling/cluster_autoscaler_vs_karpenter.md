# Cluster Autoscaler vs Karpenter: сравнительный анализ

**Актуально для:** Kubernetes 1.30–1.32 / Cluster Autoscaler 1.31+ / Karpenter v1.0+

## Определения

**Cluster Autoscaler (CA)** — базовый контроллер Kubernetes, масштабирующий кластер через абстракцию пулов узлов (Node Groups / ASG / MachineDeployment в Cluster API). Работает реактивно: отслеживает появление подов в статусе `Pending` с причиной `Unschedulable`, запускает внутреннюю симуляцию `kube-scheduler` на основе статических шаблонов групп и запрашивает добавление или удаление виртуальных или физических машин через API инфраструктурного провайдера.

**Karpenter** — контроллер гибкого провижининга узлов Kubernetes с открытым исходным кодом (проект под эгидой Kubernetes SIGs / CNCF), реализующий концепцию Just-in-Time (JIT) Group-less Provisioning. Минует абстракцию фиксированных групп узлов, агрегирует требования неразмещенных подов (CPU, RAM, архитектура, топология, селекторы) и напрямую запрашивает у провайдера инстансы с оптимальным размещением подов (Binpacking), а также динамически уплотняет и депровижинит недогруженные узлы (Consolidation).

**Node Group (MachineDeployment / MachineSet)** — логическое объединение однородных серверов или виртуальных машин с одинаковыми параметрами (размер диска, профиль CPU/RAM, метки, taints). Управляется внешней инфраструктурной системой (например, Cluster API в частных средах или контроллерами облачных платформ).

**Just-in-Time (JIT) Provisioning (Group-less)** — архитектурный подход, при котором узлы не объединяются в жесткие пулы заранее. Узел заказывается и конфигурируется динамически под конкретный набор ожидающих подов в момент возникновения потребности.

**Binpacking (Упаковка в контейнеры)** — алгоритмическая задача оптимального размещения подов с различными запросами ресурсов (`requests`) на минимально возможном количестве узлов для минимизации простоев и перерасхода памяти и процессорных ядер.

**NodePool (Karpenter CRD `apiVersion: karpenter.sh/v1`)** — декларативный ресурс, определяющий правила и ограничения, в рамках которых Karpenter формирует и удаляет узлы (допустимые типы инстансов, зоны доступности, архитектура CPU, taints, лимиты емкости и политики консолидации).

**NodeClaim (Karpenter CRD `apiVersion: karpenter.sh/v1`)** — объект жизненного цикла единичного запрашиваемого узла в Karpenter. Представляет собой атомарный запрос на создание инфраструктурной единицы и ее связывание с объектом `Node` в Kubernetes.

**Expander** — алгоритмическая стратегия Cluster Autoscaler, определяющая приоритет выбора группы узлов для расширения, если несколько доступных групп способны удовлетворить требования `Pending`-подов (`priority`, `random`, `most-pods`, `least-waste`, `price`).

**Consolidation (Консолидация)** — фоновый механизм Karpenter, анализирующий работающие узлы с целью их сжатия: выселение подов с недогруженных узлов и их перенос на другие существующие узлы либо замена дорогого/крупного узла на более компактный.

**Pod Disruption Budget (PDB)** — ресурс политики доступности (`policy/v1`), определяющий минимально допустимое число готовых реплик или максимальное количество недоступных подов при добровольных выселениях (Eviction), вызванных операциями Scale-Down или обновлением инфраструктуры.

**Overprovisioning / Headroom (Резервирование мощностей)** — архитектурный паттерн поддержания «теплого» резерва свободных вычислительных мощностей в кластере с помощью низкоприоритетных спящих подов (`PriorityClass` с отрицательным или околонулевым приоритетом и образом `pause`), которые мгновенно вытесняются критичными приложениями при всплеске нагрузки.

---

## Архитектура и сравнительный анализ

### Фундаментальные архитектурные различия

Основное различие между Cluster Autoscaler и Karpenter заключается в модели абстракции инфраструктуры и точке принятия решений о параметрах узла.

```
Cluster Autoscaler (Модель управления группами узлов):
  1. HPA / Workload → Pod в Pending (Unschedulable)
  2. CA отслеживает события API-сервера каждые --scan-interval (по умолчанию 10с)
  3. Симуляция: CA перебирает известные шаблоны Node Groups (MachineDeployment / ASG)
  4. Expander выбирает подходящую группу (например, по приоритету или емкости)
  5. CA увеличивает счетчик .spec.replicas / DesiredCapacity в API провайдера
  6. Провайдер запускает машину → Инициализация ОС / kubelet → Регистрация узла
  7. kube-scheduler размещает Pod на зарегистрированном узле

Karpenter (Модель Just-in-Time Group-less):
  1. HPA / Workload → Pod в Pending (Unschedulable)
  2. Karpenter подписан на события планировщика через informers (реакция < 1–2с)
  3. Оценка: агрегирует все ожидающие поды и вычисляет матрицу совместимости:
     ├── CPU, RAM, OS/Arch, Topology Spread, Pod Affinity/Anti-Affinity, Taints
     └── Выполняет прямой расчет binpacking и формирует NodeClaim под точные размеры
  4. Karpenter напрямую вызывает API провайдера для создания конкретного инстанса
  5. Инициализация ОС / kubelet → Регистрация узла со встроенными метками/taints
  6. kube-scheduler размещает поды без задержки ожидания внешних групп
```

### Сравнительная таблица характеристик

| Характеристика | Cluster Autoscaler (CA) | Karpenter |
|----------------|-------------------------|-----------|
| **Архитектурная модель** | Управление размером статических групп узлов (Node Groups / MachineDeployments) | Декларативный JIT-провижининг без привязки к группам (Group-less NodePools) |
| **API-ресурсы и CRD** | Стандартные ресурсы Kubernetes (`ConfigMap` для приоритетов expander, флаги запуска) | CRD `karpenter.sh/v1` (`NodePool`, `NodeClaim`) и `NodeClass` провайдера |
| **Скорость реакции (Scale-Up)** | 3–10 минут (цикл опроса, симуляция групп, ожидание инфраструктурного оркестратора) | 45–90 секунд (событийно-ориентированная реакция, прямой вызов API создания ВМ/сервера) |
| **Эффективность Binpacking** | Средняя. Ограничена фиксированным профилем машин в преднастроенных группах | Высокая. Динамически подбирает тип и размер вычислителя под точный суммарный запрос подов |
| **Масштабирование вниз (Scale-Down)** | Реактивное по таймеру `--scale-down-unneeded-time` (обычно 10 минут) при утилизации `< 50%` | Непрерывная консолидация (`WhenEmpty`, `WhenUnderutilized`, `Balanced`) с бюджетами депровижининга |
| **Инфраструктурная поддержка** | Универсальная: On-Premise (через Cluster API / Metal3 / vSphere / OpenStack), любые IaaS | Провайдерная модель (AWS, Azure, проектные провайдеры). Не поддерживает традиционный Bare-Metal без развитого API |
| **Сложность конфигурации** | Высокая инфраструктурная сложность: необходимость заранее проектировать матрицы групп узлов | Низкая инфраструктурная сложность: несколько гибких `NodePool` покрывают потребности всего кластера |
| **Отказоустойчивость (HA)** | Встроенная модель `Leader Election` через Kubernetes Lease (активен 1 экземпляр) | Многорепличное развертывание с вебхуками валидации и распределенным контроллером |
| **DRA (Dynamic Resource Allocation)** | Поддерживается (начиная с Kubernetes 1.32 в рамках KEP-4381 и параметров `ResourceClaim`) | Поддерживается через расширенные требования и драйверы ресурсов |
| **Batch/HPC нагрузки** | Поддерживает `ProvisioningRequest` (Beta в K8s 1.30+) для резервирования пачек узлов | Поддерживает атомарный запуск групп узлов через спецификацию NodePool |

### Сравнение жизненного цикла масштабирования

#### 1. Цикл Scale-Up (Холодный старт и инициализация)

```
Cluster Autoscaler:
Time (сек) 0с            10-20с           30-40с             180-300с          360с+
           │               │                │                   │                │
           Pending Pod ──► Scan Loop ──► Expander Choice ──► Provider API ──► Node Ready
                           (Опрос API)   (Выбор группы)      (ASG/CAPI Scale) (kubelet up)

Karpenter:
Time (сек) 0с      2-5с             10с                45-60с            75с
           │        │                │                   │                │
           Pending ─► Watch Event ──► Binpacking ─────► Provider API ──► Node Ready
           Pod        (Informer)     (Прямой расчет)     (Создание ВМ)    (kubelet up)
```

#### 2. Цикл Scale-Down и консолидации

- **Cluster Autoscaler:**
  1. Вычисляет утилизацию узла по сумме `requests` (CPU и память раздельно).
  2. Если утилизация падает ниже `--scale-down-utilization-threshold=0.5` непрерывно в течение `--scale-down-unneeded-time=10m`, узел помечается кандидатом.
  3. Проверяются блокирующие факторы: PDB, локальное хранилище без репликации (`emptyDir`, `hostPath`), системные поды без контроллеров, аннотация `cluster-autoscaler.kubernetes.io/safe-to-evict: "false"`.
  4. При отсутствии блокировок узел маркируется taint `ToBeDeletedByClusterAutoscaler`, поды выселяются через Eviction API, узел удаляется из инфраструктуры.
- **Karpenter:**
  1. Контроллер Disruption в реальном времени отслеживает изменения в кластере.
  2. При обнаружении узла, который стал пустым (`WhenEmpty`) или недогруженным (`WhenUnderutilized`), Karpenter симулирует: можно ли перенести поды на другие узлы, либо заменить текущий узел на узел меньшего размера?
  3. Проверяются `spec.disruption.budgets` (лимит допустимой деградации в процентах или штуках) и PDB подов.
  4. Если замена выгодна, Karpenter сначала заказывает новый меньший узел, дожидается его готовности, переносит нагрузку (graceful drain) и удаляет старый узел без простоя сервиса.

### Матрица выбора: когда использовать каждое решение

| Критерий инфраструктуры и задач | Рекомендация | Техническое обоснование |
|---------------------------------|--------------|-------------------------|
| **On-Premise (Bare-Metal, vSphere, OpenStack)** | **Cluster Autoscaler** | CA глубоко интегрирован с Cluster API (CAPV, CAPM3, CAPO), умеет управлять жизненным циклом физических машин через PXE/Ironic и статическими пулами ВМ. Karpenter не имеет зрелого bare-metal драйвера. |
| **Инфраструктура с динамическими требованиями к ресурсам** | **Karpenter** | Автоматически подбирает серверы с нужным соотношением CPU:RAM, освобождая SRE от ручного проектирования десятков различных групп узлов под микросервисы. |
| **Высокие требования к скорости реакции (SLA по Scale-Up)** | **Karpenter** | Реакция за десятки секунд вместо минут предотвращает накопление очередей запросов в ingress-шлюзах при резких всплесках трафика. |
| **Строго регламентированная инфраструктура (Compliance, аудит)** | **Cluster Autoscaler** | Фиксированные группы узлов обеспечивают полную предсказуемость сетевой изоляции, профилей безопасности ОС и неизменности состава пулов. |
| **Смешанный парк архитектур (x86_64 и ARM64)** | **Karpenter** | Единый NodePool с селектором архитектуры позволяет приложениям с мультиплатформенными образами динамически выбирать наиболее дешевую архитектуру. |
| **Пакетная обработка и очереди задач (Batch / ETL)** | **Cluster Autoscaler** или **Karpenter** | CA поддерживает интеграцию с `ProvisioningRequest` (K8s 1.30+) для очередей задач; Karpenter обеспечивает моментальный запуск и последующее агрессивное удаление узлов после завершения Job. |

---

## Взаимодействие с механизмами ядра Kubernetes

### Взаимодействие с kube-scheduler

Оба автоскейлера тесно взаимодействуют со стандартным планировщиком `kube-scheduler`, но реализуют принципиально разные механизмы симуляции:

1. **Симуляция в Cluster Autoscaler:** CA компилирует внутри себя код предикатов `kube-scheduler` соответствующей версии Kubernetes. Когда под попадает в `Pending`, CA берет абстрактные описания существующих Node Groups, создает виртуальные представления узлов (Fake Nodes) и прогоняет через них алгоритм планирования. Если виртуальный узел проходит фильтры (`NodeAffinity`, `Tolerations`, `TopologySpreadConstraints`), CA отдает команду на расширение соответствующей группы.
2. **Симуляция в Karpenter:** Karpenter перехватывает поды до того, как они пройдут стандартный цикл перепланирования. Он оценивает суммарные требования всех ожидающих подов одновременно, формирует математическую модель упаковки (Binpacking optimization) и подбирает минимально достаточную конфигурацию вычислителя. Созданный узел изначально регистрируется с необходимыми метками, поэтому при его переходе в статус `Ready` `kube-scheduler` сразу назначает запланированные поды на целевой сервер.

### Взаимодействие с Pod Disruption Budget (PDB)

PDB регламентирует допустимый уровень деградации реплик приложения. При сжатии кластера PDB может приводить к аварийным ситуациям:

- **Поведение CA:** Если на узле находится хотя бы один под, для которого PDB имеет `.status.disruptionsAllowed == 0` (например, при `minAvailable: 100%` или при упавших соседних репликах), CA признает узел «неудаляемым» (`unremovable`). Таймер scale-down сбрасывается. Если таких узлов много, кластер застревает в раздутом состоянии.
- **Поведение Karpenter:** Karpenter уважает PDB, руководствуясь `spec.template.spec.terminationGracePeriod` и правилами `disruption.budgets`. Если PDB блокирует выселение пода, Karpenter не будет разрушать узел в рамках регулярной консолидации. Однако при истечении времени жизни узла (`expireAfter`) или принудительном удалении узла, если время дренажа превышает `terminationGracePeriod`, Karpenter может принудительно удалить узел, о чем SRE информируется через события Kubernetes.

### Взаимодействие с Descheduler

Использование Descheduler совместно с автомасштабированием требует жесткой координации:

- **Риск конфликта (Controller Thrashing):** Если Descheduler выселяет поды с целью выравнивания нагрузки между узлами (стратегия `LowNodeUtilization`), а Cluster Autoscaler или Karpenter одновременно пытаются оптимизировать кластер вниз (удалив пустующие узлы), возникает циклическая война контроллеров:
  1. Descheduler выселяет под с относительно нагруженного узла.
  2. Под временно попадает в `Pending`.
  3. CA/Karpenter видит `Pending` и заказывает новый узел.
  4. Старый узел опустошается, и автоскейлер удаляет его.
  5. Кластер тратит ресурсы на постоянный перезапуск и ввод/вывод серверов.
- **Правило согласования:** В кластерах с Karpenter включение дефрагментации Descheduler обычно избыточно, так как встроенный механизм `Consolidation` решает ту же задачу безопаснее на уровне самого провижинера. При использовании Cluster Autoscaler интервал запуска Descheduler должен быть значительно больше интервалов scale-down (например, запуск раз в час), а пороги утилизации в политиках Descheduler должны быть выше порога `--scale-down-utilization-threshold`.

### Паттерн Headroom (Overprovisioning)

Для устранения задержки холодного старта (от 1 до 5 минут) в высоконагруженных системах применяется шаблон буферной емкости (Headroom):

```
Приоритеты планировщика:
  Production Pods (Priority: 1000)   ───► Вытесняют буфер и стартуют МГНОВЕННО (0 сек)
  Buffer Pause Pods (Priority: -10)  ───► Вытесняются в Pending ──► Триггерят CA/Karpenter
```

1. Создается `PriorityClass` со значением `-10`.
2. Развертывается Deployment с минимальным образом `registry.k8s.io/pause:3.10` и запросами ресурсов, равными размеру одного типового узла (например, 4 vCPU, 16 GiB RAM).
3. Буферные поды занимают место на узлах.
4. При наплыве боевой нагрузки продуктовые поды с более высоким приоритетом немедленно вытесняют pause-поды (`Preemption`). Боевые сервисы стартуют за 2–5 секунд.
5. Вытесненные pause-поды переходят в статус `Pending`, запуская процедуру масштабирования CA или Karpenter в фоновом режиме.

---

## Практические сценарии и конфигурация

### Сценарий 1: Отказоустойчивое развертывание Cluster Autoscaler

Конфигурация Cluster Autoscaler для работы в инфраструктуре на базе Cluster API или частного IaaS с механизмом выбора лидера:

```yaml
# cluster-autoscaler-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  labels:
    app.kubernetes.io/name: cluster-autoscaler
spec:
  replicas: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: cluster-autoscaler
  template:
    metadata:
      labels:
        app.kubernetes.io/name: cluster-autoscaler
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8085"
    spec:
      serviceAccountName: cluster-autoscaler
      tolerations:
        - key: node-role.kubernetes.io/control-plane
          operator: Exists
          effect: NoSchedule
      nodeSelector:
        node-role.kubernetes.io/control-plane: ""
      containers:
        - name: cluster-autoscaler
          image: registry.k8s.io/autoscaling/cluster-autoscaler:v1.31.0
          command:
            - ./cluster-autoscaler
            - --v=4
            - --cloud-provider=clusterapi
            - --leader-elect=true
            - --leader-elect-resource-name=cluster-autoscaler
            - --leader-elect-resource-namespace=kube-system
            - --expander=priority,least-waste
            - --balance-similar-node-groups=true
            - --scale-down-enabled=true
            - --scale-down-utilization-threshold=0.5
            - --scale-down-unneeded-time=10m
            - --scale-down-delay-after-add=5m
            - --max-node-provision-time=15m
            - --skip-nodes-with-local-storage=false
            - --skip-nodes-with-system-pods=true
            - --address=0.0.0.0
            - --port=8085
          resources:
            requests:
              cpu: 100m
              memory: 300Mi
            limits:
              cpu: 1000m
              memory: 1Gi
```

Конфигурация приоритетов для экспандера (привязка групп узлов к приоритетам):

```yaml
# ca-priority-expander-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-autoscaler-priority-expander
  namespace: kube-system
data:
  priorities: |-
    100:
      - .*worker-standard.*
    50:
      - .*worker-large.*
    10:
      - .*worker-fallback.*
```

### Сценарий 2: Декларативная конфигурация Karpenter v1 (NodePool и NodeClass)

Конфигурация NodePool спецификации API `karpenter.sh/v1` с контролем консолидации и лимитами:

```yaml
# karpenter-nodepool-production.yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: default-workload
spec:
  template:
    metadata:
      labels:
        environment: production
        team: platform
    spec:
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default-nodeclass
      requirements:
        - key: kubernetes.io/arch
          operator: In
          values: ["amd64", "arm64"]
        - key: kubernetes.io/os
          operator: In
          values: ["linux"]
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["on-demand"]
        - key: karpenter.k8s.aws/instance-category
          operator: In
          values: ["c", "m", "r"]
        - key: karpenter.k8s.aws/instance-generation
          operator: Gt
          values: ["4"]
      # Предельное время жизни узла до плановой ротации
      expireAfter: 720h
      # Предельное время ожидания завершения подов перед принудительным удалением узла
      terminationGracePeriod: 48h
  # Политики депровижининга и консолидации
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 1m
    budgets:
      # Запрет вывода более 10% узлов одновременно
      - nodes: 10%
      # Полный запрет консолидации в пиковые бизнес-часы
      - schedule: "0 9 * * mon-fri"
        duration: 9h
        nodes: "0"
  limits:
    cpu: "256"
    memory: 1024Gi
  weight: 50
---
# karpenter-nodeclass.yaml
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: default-nodeclass
spec:
  amiFamily: AL2023
  role: "KarpenterNodeRole-Cluster"
  subnetSelectorTerms:
    - tags:
        karpenter.sh/discovery: production-cluster
  securityGroupSelectorTerms:
    - tags:
        karpenter.sh/discovery: production-cluster
  metadataOptions:
    httpEndpoint: enabled
    httpProtocolIPv6: disabled
    httpPutResponseHopLimit: 1
    httpTokens: required
```

### Сценарий 3: Настройка Overprovisioning (Headroom) через PriorityClass

Создание резервного вычислительного пула для мгновенного горизонтального скейлинга критичных приложений:

```yaml
# headroom-overprovisioning.yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: overprovisioning-buffer
value: -10
globalDefault: false
description: "Низкий приоритет для буферных подов горячего резерва инфраструктуры"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-headroom-buffer
  namespace: kube-system
  labels:
    app.kubernetes.io/name: headroom-buffer
spec:
  # Количество реплик определяет размер резервного пула узлов
  replicas: 4
  selector:
    matchLabels:
      app.kubernetes.io/name: headroom-buffer
  template:
    metadata:
      labels:
        app.kubernetes.io/name: headroom-buffer
    spec:
      priorityClassName: overprovisioning-buffer
      terminationGracePeriodSeconds: 0
      containers:
        - name: reserve-capacity
          image: registry.k8s.io/pause:3.10
          resources:
            requests:
              cpu: "1900m"
              memory: "7Gi"
            limits:
              cpu: "1900m"
              memory: "7Gi"
```

### Сценарий 4: Пошаговая миграция с Cluster Autoscaler на Karpenter

Безопасный перенос рабочих нагрузок кластера из-под управления CA в управление Karpenter без остановки продуктивных сервисов:

#### Шаг 1. Параллельная установка контроллера Karpenter

```bash
# Установка Karpenter через Helm в изолированное пространство имен
helm install karpenter oci://public.ecr.aws/karpenter/karpenter \
  --version 1.0.8 \
  --namespace kube-system \
  --set settings.clusterName=production-cluster \
  --set controller.resources.requests.cpu=500m \
  --set controller.resources.requests.memory=1Gi
# → NAME: karpenter
# → STATUS: deployed
# → REVISION: 1
```

#### Шаг 2. Применение конфигурации NodePool и NodeClass

```bash
kubectl apply -f karpenter-nodepool-production.yaml
# → nodepool.karpenter.sh/default-workload created
# → ec2nodeclass.karpenter.k8s.aws/default-nodeclass created
```

#### Шаг 3. Изоляция старых узлов Cluster Autoscaler от новых подов

Добавление cordon или taint на узлы старых групп, чтобы новые поды размещались только через Karpenter:

```bash
# Выборка узлов старого пула и установка ограничивающего taint
kubectl get nodes -l node.kubernetes.io/instance-type -o name | head -n 3 | xargs -I {} kubectl taint {} migration=karpenter:NoSchedule
# → node/ip-10-0-1-10.ec2.internal tainted
# → node/ip-10-0-1-11.ec2.internal tainted
# → node/ip-10-0-1-12.ec2.internal tainted
```

#### Шаг 4. Поочередный перенос рабочей нагрузки (Graceful Drain)

```bash
# Выселение подов с узла CA с соблюдением PDB
kubectl drain ip-10-0-1-10.ec2.internal --ignore-daemonsets --delete-emptydir-data --force
# → evicting pod default/payment-service-6d8bf8cb7f-j8xk2
# → evicting pod default/order-service-7598c775cf-w2b5t
# → node/ip-10-0-1-10.ec2.internal drained
```

Проверка появления новых `NodeClaims` и узлов в Karpenter:

```bash
kubectl get nodeclaims
# → NAME            TYPE          CAPACITY   ZONE         NODE                          READY   AGE
# → default-9x2kz   m5.2xlarge    on-demand  us-east-1a   ip-10-0-2-45.ec2.internal     True    45s
```

#### Шаг 5. Отключение Cluster Autoscaler

```bash
# Остановка Deployment старого автоскейлера
kubectl scale deployment cluster-autoscaler -n kube-system --replicas=0
# → deployment.apps/cluster-autoscaler scaled

# Проверка отсутствия активности старого контроллера
kubectl get leases -n kube-system cluster-autoscaler
# → NAME                 HOLDER   AGE
# → cluster-autoscaler   <none>   120d
```

---

## Диагностика и устранение неполадок

### 1. Поды зависли в Pending, узлы не добавляются

**Симптомы:** HPA масштабирует поды, статус подов `Pending`, сообщения `0/12 nodes are available: 12 Insufficient cpu`, новые узлы не появляются.

**Диагностика:**
```bash
# Проверка причин непрохождения планировщика для пода
kubectl describe pod <pending-pod-name> | grep -A 5 Events
# → Events:
# → Type     Reason            Age   From               Message
# → ----     ------            ----  ----               -------
# → Warning  FailedScheduling  45s   default-scheduler  0/8 nodes are available: 8 Insufficient memory.

# Проверка логов Cluster Autoscaler на предмет симуляции
kubectl logs -n kube-system -l app.kubernetes.io/name=cluster-autoscaler --tail=50 | grep -i "scale up"
# → I1012 18:20:10.123 main.go:345] Scale-up: 3 pods need reservation, evaluating 2 node groups
# → W1012 18:20:15.543 scale_up.go:120] Node group worker-standard max size reached (max: 20, current: 20)

# Проверка логов Karpenter
kubectl logs -n kube-system -l app.kubernetes.io/name=karpenter -c controller --tail=50 | grep -i "nomination"
# → {"level":"ERROR","time":"2026-10-12T18:20:22Z","logger":"controller","message":"could not schedule pod","pod":"default/order-service-xxx","error":"no instance type matched pod requirements"}
```

**Решение:**
- В CA: Проверить параметр `--nodes=min:max:name`. Если достигнут верхний предел (max), расширить лимит группы узлов или добавить дополнительную группу в ConfigMap экспандера.
- В Karpenter: Проверить секцию `spec.limits` в объекте `NodePool`. Если сумма ресурсов достигла `spec.limits.cpu` или `spec.limits.memory`, увеличить квоту пула. Проверить `spec.template.spec.requirements` на взаимную противоречивость фильтров.

### 2. Блокировка удаления недогруженного узла (Scale-down blocked)

**Симптомы:** Утилизация узла составляет менее 20%, но автоскейлер не выводит узел из эксплуатации.

**Диагностика:**
```bash
# Анализ блокировок в Cluster Autoscaler
kubectl describe configmap cluster-autoscaler-status -n kube-system
# → ScaleDown:
# →   Nodes unneeded: 2
# →   Nodes unremovable: 1
# →   Unremovable reasons:
# →     ip-10-0-1-15.ec2.internal: Pod default/redis-slave-0 blocks scale-down: PodDisruptionBudget is violated or pod has local storage

# Проверка PDB в кластере
kubectl get pdb -A
# → NAMESPACE   NAME       MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → default     redis-pdb  1               N/A               0                     15d

# Проверка подов с аннотацией запрета выселения
kubectl get pods -A -o jsonpath='{range .items[?(@.metadata.annotations.cluster-autoscaler\.kubernetes\.io/safe-to-evict=="false")]}{.metadata.namespace}{"/"}{.metadata.name}{"\n"}{end}'
# → default/critical-collector-daemon
```

**Решение:**
- Если PDB имеет `ALLOWED DISRUPTIONS: 0`, восстановить упавшие реплики приложения или временно скорректировать PDB.
- Для подов с локальным хранилищем (`emptyDir`), если данные временные, добавить аннотацию:
  ```yaml
  metadata:
    annotations:
      cluster-autoscaler.kubernetes.io/safe-to-evict: "true"
  ```
- В Karpenter проверить статус `NodeClaim` и события консолидации:
  ```bash
  kubectl describe nodeclaim <nodeclaim-name> | grep -A 5 Disruption
  # → Disruption:
  # →   Eligible: False
  # →   Reason: PodBlockingEviction (default/redis-slave-0)
  ```

### 3. Циклический флаппинг узлов (Thrashing Loop)

**Симптомы:** Узел вводится в строй, поды запускаются, через 5 минут узел признается недогруженным и удаляется, затем поды снова переходят в `Pending` и процесс повторяется.

**Диагностика:**
- Проверить совпадение порогов: HPA масштабирует поды вниз при падении CPU, автоскейлер удаляет узел, затем HPA фиксирует рост средней утилизации CPU на оставшихся узлах и запускает Scale-up.

**Решение:**
- В Cluster Autoscaler: Увеличить `--scale-down-unneeded-time=15m` и установить защитный интервал `--scale-down-delay-after-add=10m`.
- В Karpenter: Настроить `disruption.consolidationPolicy: WhenEmpty` вместо `WhenUnderutilized` для нестабильных нагрузок, либо задать задержку:
  ```yaml
  disruption:
    consolidationPolicy: WhenUnderutilized
    consolidateAfter: 5m
  ```

### Метрики Prometheus и алертинг для SRE

#### Ключевые метрики

| Метрика | Система | Тип | Назначение |
|---------|---------|-----|------------|
| `cluster_autoscaler_unschedulable_pods_count` | CA | Gauge | Количество подов в очереди, под которые CA не может выделить узлы. |
| `cluster_autoscaler_failed_scale_ups_total` | CA | Counter | Суммарное количество неудачных попыток расширения пулов узлов. |
| `cluster_autoscaler_unremovable_nodes_count` | CA | Gauge | Количество пустых/недогруженных узлов, заблокированных от удаления (PDB/Taints). |
| `karpenter_nodeclaims_created` | Karpenter | Counter | Количество созданных инфраструктурных требований на узлы. |
| `karpenter_disruption_actions_performed_total` | Karpenter | Counter | Количество выполненных операций консолидации, депровижининга и ротации. |
| `karpenter_nodepool_usage` | Karpenter | Gauge | Текущий уровень потребления лимита CPU/памяти конкретным `NodePool`. |
| `karpenter_nodepool_limit` | Karpenter | Gauge | Максимальный лимит ресурсов, заданный в `.spec.limits`. |

#### Готовые правила PromQL алертинга

```yaml
# autoscaler-alerts.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: autoscaling-alerts
  namespace: monitoring
spec:
  groups:
    - name: autoscaling.rules
      rules:
        # Алерт на зависание подов из-за сбоя масштабирования CA
        - alert: ClusterAutoscalerScaleUpFailed
          expr: increase(cluster_autoscaler_failed_scale_ups_total[10m]) > 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Сбой расширения кластера Cluster Autoscaler"
            description: "CA зафиксировал ошибки создания узлов за последние 10 минут. Возможны исчерпание квот инфраструктуры или сетевые сбои."

        # Алерт на неразмещенные поды в очереди
        - alert: UnschedulablePodsQueueStuck
          expr: cluster_autoscaler_unschedulable_pods_count > 0
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Поды застряли в состоянии Unschedulable"
            description: "В кластере обнаружены поды, ожидающие масштабирования дольше 10 минут."

        # Алерт на исчерпание лимитов NodePool в Karpenter
        - alert: KarpenterNodePoolLimitExhausted
          expr: (karpenter_nodepool_usage / karpenter_nodepool_limit) > 0.90
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Лимит ресурсов Karpenter NodePool исчерпан на 90%"
            description: "NodePool {{ $labels.nodepool }} приблизился к установленному лимиту ресурсов. Масштабирование может быть заблокировано."

        # Алерт на циклический сбой депровижининга Karpenter
        - alert: KarpenterConsolidationLoop
          expr: rate(karpenter_disruption_actions_performed_total[15m]) > 0.2
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "Высокая частота консолидации Karpenter"
            description: "Karpenter выполняет частые операции депровижининга узлов, возможен флуктуационный цикл (thrashing)."
```

---

## Лучшие практики

1. **Базис планирования исключительно на `requests`:**
   - Ни Cluster Autoscaler, ни Karpenter не ориентируются на фактическую утилизацию CPU/RAM узлов из Metrics Server при принятии решения о масштабировании вверх. Решение принимается исключительно на основе объявленных `resources.requests`.
   - Если у приложений не заданы `requests`, автоскейлеры считают под «нулевым» по потреблению, что приводит к переуплотнению узлов и последующему аварийному выселению по OOM (Out Of Memory).

2. **Защита системных узлов Control Plane и Kube-System:**
   - Системные компоненты (CoreDNS, CNI плагины, ingress-контроллеры, сервисные операторы) должны быть защищены от случайной ротации автоскейлерами.
   - Рекомендуется размещать критическую инфраструктуру на статическом пуле узлов с меткой `node-role.kubernetes.io/infra: ""` и соответствующими `nodeSelector` / `tolerations`.

3. **Синхронизация таймаутов завершения:**
   - `terminationGracePeriodSeconds` в подах приложений должен быть строго меньше, чем `terminationGracePeriod` в Karpenter NodePool или таймаут drain в Cluster Autoscaler.
   - Если приложению требуется 60 секунд на сохранение состояния перед выходом, выставляйте `terminationGracePeriodSeconds: 90` в Deployment и не менее `terminationGracePeriod: 10m` в настройках автоскейлера.

4. **Предотвращение взаимных блокировок PDB:**
   - Никогда не создавайте PDB со значением `minAvailable: 100%` или `maxUnavailable: 0` для приложений с количеством реплик менее 3. Любая попытка выселения пода заблокирует масштабирование кластера вниз.
   - Для одиночных подов (реплика 1) использование PDB с `minAvailable: 1` полностью блокирует drain узла.

5. **Изоляция сред через taints вместо создания избыточных групп:**
   - В Karpenter используйте механизм `startupTaints` для подготовки узлов (например, до завершения инициализации DaemonSet маршрутизации CNI), чтобы поды не попадали на еще не готовые узлы.

---

## Дополнительная информация

### См. также

- [Cluster Autoscaler: Глубокое погружение](cluster_autoscaler_detailed.md) — детальный разбор внутреннего цикла CA, флагов, CAPI и Bare-Metal масштабирования
- [Автоматическое масштабирование в Kubernetes: Архитектурный обзор](overview_concepts.md) — общие уровни и принципы автомасштабирования (HPA, VPA, CA, Karpenter)
- [Pod Disruption Budget (PDB)](pod_disruption_budget.md) — настройка бюджетов доступности и исключение тупиковых блокировок при выселении
- [Descheduler: автоматическая дефрагментация](descheduler.md) — оптимизация размещения подов и координация с автоскейлерами
- [On-premise масштабирование кластера](on_premise_autoscaling.md) — масштабирование в частных ЦОД и на bare-metal платформах
- [HPA и приоритизация подов](hpa_priority_preemption.md) — взаимодействие очередей подов, PriorityClass и горизонтального масштабирования
