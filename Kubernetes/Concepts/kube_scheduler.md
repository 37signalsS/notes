# Kube-scheduler: планировщик подов в Kubernetes

## Определение

**Kube-scheduler** — это основной компонент плоскости управления (Control Plane) Kubernetes, ответственный за назначение подов (Pods) на доступные рабочие узлы (Nodes). Он непрерывно отслеживает (watch) API-сервер на предмет появления новых подов, у которых поле `spec.nodeName` не заполнено, и выбирает для них наиболее подходящий узел на основе набора политик, ресурсов и ограничений.

**Ключевая роль:** Планировщик является "интеллектуальным диспетчером" кластера. Его задача — обеспечить эффективную утилизацию ресурсов и соблюдение требований доступности приложений. Важно понимать, что планировщик принимает решение только в момент создания пода (однократное действие).

**Расположение в кластере:** Kube-scheduler работает как Pod в namespace `kube-system`, управляемый static pod манифестом (kubeadm) илиDeployment (другие методы установки). Порт по умолчанию: `10259` (HTTPS,(metrics и healthz)). Файл конфигурации: `/etc/kubernetes/scheduler-config.yaml` (kubeadm) или аргументы командной строки в манифесте `/etc/kubernetes/manifests/kube-scheduler.yaml`.

---

## Основные концепции

### Процесс планирования (Жизненный цикл)

Процесс планирования одного пода состоит из двух циклов: **Scheduling Cycle** (выбор узла, выполняется последовательно) и **Binding Cycle** (привязка к узлу, может выполняться параллельно).

#### 1. Фильтрация (Predicates / Filtering)
На этом этапе планировщик отсеивает все узлы, которые физически или логически не могут запустить данный под. Проверяются следующие плагины/условия:
*   **NodeResourcesFit**: Наличие свободных CPU, RAM и эфемерного хранилища на основе `requests`.
*   **Taints & Tolerations**: Проверка наличия `taints` на узле. Pod будет запланирован только если у него есть соответствующие `tolerations`.
*   **NodeSelector / NodeAffinity**: Проверка соответствия меток узла требованиям пода.
*   **PodTopologySpread**: Проверка ограничений на распределение подов по различным топологическим доменам (зоны, стойки).
*   **Volume Restriction**: Проверка возможности подключения требуемых томов (PV/PVC). При использовании `volumeBindingMode: WaitForFirstConsumer` планировщик также учитывает топологию доступности дисков.

**Результат:** список "подходящих" узлов (feasible nodes). Если список пуст, под остается в статусе `Pending`.

#### 2. Оценка (Scoring / Prioritization)
Каждый узел из списка прошедших фильтрацию получает баллы (от 0 до 100). Планировщик суммирует баллы от разных функций оценки:
*   **LeastRequestedPriority**: Предпочтение отдается узлам с меньшей загрузкой (равномерное распределение).
*   **MostRequestedPriority**: Предпочтение отдается более нагруженным узлам (стратегия упаковки — "bin packing").
*   **ImageLocalityPriority**: Приоритет узлам, на которых уже скачаны необходимые образы.
*   **BalancedResourceAllocation**: Предпочтение узлам, где соотношение CPU и RAM после запуска будет наиболее сбалансированным.

**Результат:** Выбирается узел с наивысшим баллом. Если таких несколько, выбор происходит случайно (round-robin).

### Современная архитектура: Scheduling Framework

Начиная с Kubernetes 1.15, планировщик перешел на расширяемую архитектуру **Scheduling Framework**. Это позволяет разработчикам добавлять свои плагины на различных этапах жизненного цикла планирования.

**Точки расширения (Extension Points):**
*   **QueueSort**: Определение порядка подов в очереди ожидания.
*   **PreFilter**: Предварительная обработка данных о поде перед фильтрацией.
*   **Filter**: Реализация логики Predicates.
*   **PostFilter**: Запускается, если ни один узел не подошел. Здесь обычно реализуется логика **Preemption** (вытеснения).
*   **PreScore / Score**: Реализация логики Prioritization.
*   **NormalizeScore**: Приведение баллов от разных плагинов к единому диапазону.
*   **Reserve**: Резервирование ресурсов на узле (защита от race conditions до фактической записи в etcd).
*   **Permit**: Возможность задержать или отклонить привязку (используется для Gang Scheduling).
*   **PreBind / Bind / PostBind**: Этапы финальной привязки пода к узлу.

### Механизмы управления размещением

*   **NodeSelector**: Простейший механизм фильтрации по меткам узлов.
*   **Affinity и Anti-Affinity**: Гибкие правила с уровнями строгости (`required` — жесткие, `preferred` — мягкие). Подробнее: [Affinity и Anti-Affinity](../Scheduling/affinity.md).
*   **Taints и Tolerations**: Механизм "отталкивания" подов от определенных узлов. Подробнее: [Taints and Tolerations](../Scheduling/taints_and_tolerations.md).
*   **Pod Topology Spread Constraints**: Позволяет контролировать распределение подов по различным топологическим доменам (зоны, стойки, хосты) для обеспечения отказоустойчивости и баланса.
*   **Resource Requests и Limits**: Планировщик использует значение `requests` для расчета доступного места. Подробнее: [QoS, Requests и Limits](../Scheduling/qos_limit_and_requests.md).
*   **PriorityClass**: Определяет очередь планирования и возможность вытеснения других подов. Подробнее: [PriorityClass](./priorityclass.md).
*   **Scheduling Gates**: Механизм (GA v1.30), позволяющий удерживать под в состоянии `Pending`, пока внешние условия (например, подготовка квоты или внешних ресурсов) не будут выполнены. Планировщик полностью игнорирует поды с непустыми `schedulingGates`, что снижает нагрузку на Control Plane.

### Preemption (Вытеснение)

Preemption — механизм, позволяющий планировщику удалить (evict) поды с более низким приоритетом для размещения пода с более высоким приоритетом. Процесс вытеснения запускается на этапе **PostFilter**, если на кластере не нашлось узла с достаточными ресурсами для пода.

**Порядок действий при вытеснении:**
1. Планировщик ищет поды-«жертвы» с более низким `PriorityClass`, чье удаление освободит достаточно ресурсов.
2. Проверяется, не будет ли нарушено [Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md) для подов-жертв (если PDB определен).
3. Выбирается набор жертв, MinimalDisruption (минимальное влияние на доступность).
4. Поды-жертвы удаляются через Eviction API (учитывает PDB).
5. После удаления жертв под-кандидат планируется повторно.

**Важные нюансы:**
*   Под с `PreemptionPolicy: Never` **не будет** вытеснять другие поды, но **может быть вытеснен** более приоритетным подом.
*   Если жертвы найдены, но планировщик не может успешно назначить под даже после их удаления, под остается в очереди с увеличенным back-off.
*   С версии 1.32+ доступна **Asynchronous Preemption** — удаление жертв выполняется асинхронно, ускоряя назначение высокоприоритетных подов.
*   Вытеснение не учитывает PodDisruptionBudget по умолчанию. С K8s 1.21+ доступна опция `checkNodeFitness`, влияющая на порядок проверки узлов после вытеснения.

**Отслеживание вытеснений:**
```bash
# Количество попыток вытеснения
kubectl get --raw /metrics | grep scheduler_preemption_attempts

# Количество подов-жертв
kubectl get --raw /metrics | grep scheduler_preemption_victims
```

---

## Жизненный цикл планирования (Workflow)

1.  **Пользователь/Контроллер** создает под через API.
2.  **API-сервер** сохраняет объект в `etcd` с пустым полем `spec.nodeName`.
3.  **Kube-scheduler** обнаруживает новый под через `watch`.
4.  **Синхронная фаза (Scheduling Cycle)**:
    *   Извлечение из очереди.
    *   Прохождение этапов **Filter** и **Score**.
    *   Выбор узла.
    *   Выполнение этапа **Reserve** (обновление локального кэша планировщика).
5.  **Асинхронная фаза (Binding Cycle)**:
    *   Выполнение этапа **Permit**.
    *   Выполнение этапа **PreBind**.
    *   Отправка запроса `Binding` к API-серверу (этап **Bind**).
6.  **Kubelet** на узле видит назначение и запускает контейнеры.

---

## Практические сценарии

### Сценарий 1: Размещение на узлах с GPU
**Задача:** Направить ML-нагрузку только на узлы с видеокартами.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-training
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: accelerator
            operator: In
            values:
            - nvidia-tesla-v100
  tolerations:
  - key: "gpu-node"
    operator: "Exists"
    effect: "NoSchedule"
  containers:
  - name: worker
    image: nvidia/cuda:12.0-base
    resources:
      limits:
        nvidia.com/gpu: 1
```

### Сценарий 2: Равномерное распределение по зонам (Topology Spread)
**Задача:** Гарантировать, что реплики приложения будут распределены по зонам доступности максимально равномерно (разница не более 1 пода).

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: distributed-app
spec:
  replicas: 4
  template:
    spec:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: distributed-app
      containers:
      - name: nginx
        image: nginx:1.27
```

### Сценарий 3: Изоляция сред через Scheduler Profiles
Вы можете настроить `kube-scheduler` так, чтобы он по-разному обрабатывал поды в зависимости от их `schedulerName`.

```yaml
apiVersion: kubescheduler.config.k8s.io/v1
kind: KubeSchedulerConfiguration
profiles:
  - schedulerName: default-scheduler
  - schedulerName: bin-packing-scheduler
    pluginConfig:
    - name: NodeResourcesFit
      args:
        scoringStrategy:
          type: MostAllocated # Стратегия упаковки для экономии ресурсов
  - schedulerName: spread-scheduler
    pluginConfig:
    - name: PodTopologySpread
      args:
        defaultingType: List
        defaultConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: ScheduleAnyway
```

Использование в поде:
```yaml
spec:
  schedulerName: bin-packing-scheduler
```

**Типичные профили:**

| Имя профиля | Стратегия | Кейс применения |
| :--- | :--- | :--- |
| `default-scheduler` | LeastAllocated | Балансировка нагрузки по умолчанию |
| `bin-packing-scheduler` | MostAllocated | Упаковка подов на минимальное число узлов (экономия на лицензиях, облегчение масштабирования) |
| `spread-scheduler` | LeastAllocated + PodTopologySpread | Максимальное распределение для отказоустойчивости |

**Профили по типам нагрузки:** разные типы нагрузки требуют разных стратегий — инференс равномернее распределять (`LeastAllocated` + `ImageLocality` для быстрого старта), обучение упаковывать плотнее (`MostAllocated` в скопе `nvidia.com/gpu`). Готовый пример конфигурации с двумя профилями и рекомендации по выбору — в [Обзоре решений для планирования](../Scheduling/scheduling_solutions_overview.md#практические-сценарии).

### Сценарий 4: Multi-Scheduler — изоляция рабочих нагрузок
В кластере могут одновременно работать несколько экземпляров планировщика. Каждый под привязывается к определенному планировщику через поле `schedulerName`. Это позволяет изолировать критические и фоновые нагрузки.

**Пример манифеста второго планировщика:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: custom-scheduler
  namespace: kube-system
spec:
  replicas: 1
  selector:
    matchLabels:
      component: custom-scheduler
  template:
    metadata:
      labels:
        component: custom-scheduler
    spec:
      serviceAccountName: kube-scheduler
      containers:
      - name: kube-scheduler
        image: registry.k8s.io/kube-scheduler:v1.31.0
        command:
        - kube-scheduler
        - --config=/etc/kubernetes/scheduler-config.yaml
        - --v=2
        volumeMounts:
        - name: config
          mountPath: /etc/kubernetes/scheduler-config.yaml
          subPath: scheduler-config.yaml
      volumes:
      - name: config
        configMap:
          name: custom-scheduler-config
```

**Привязка пода к конкретному планировщику:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: critical-app
spec:
  schedulerName: custom-scheduler  # ← указываем имя планировщика
  containers:
  - name: app
    image: nginx:1.27
```

**Важно:** Кастомный планировщик должен иметь правильные RBAC-разрешения (ServiceAccount с кластерными рольами `system:kube-scheduler` или эквивалент).

---

## Диагностика и отладка

### Инспекция состояния планировщика

**Проверка конфигурации:**
```bash
# Просмотр текущей конфигурации (kubeadm)
kubectl get cm -n kube-system kube-scheduler -o yaml

# Просмотр аргументов запуска
kubectl get pod -n kube-system -l component=kube-scheduler -o jsonpath='{.items[0].spec.containers[0].command}'

# Проверка конфигурационного файла на мастер-ноде
cat /etc/kubernetes/scheduler-config.yaml
```

**Проверка здоровья:**
```bash
# Healthz-эндпоинт (по умолчанию на порту 10259)
kubectl get --raw https://localhost:10259/healthz
# → ok

# Livez check (k8s 1.26+)
kubectl get --raw https://localhost:10259/livez
kubectl get --raw https://localhost:10259/readyz
```

**Проверка конкуренции за лидерство (HA-кластеры):**
```bash
# Список Lease-объектов планировщика
kubectl get lease -n kube-system kube-scheduler

# Текущий лидер
kubectl get lease kube-scheduler -n kube-system -o jsonpath='{.spec.holderIdentity}'
```

### Мониторинг (Метрики Prometheus)

Для оценки здоровья планировщика отслеживайте следующие метрики:

| Метрика | Описание | Тип |
| :--- | :--- | :--- |
| `scheduler_pending_pods` | Количество подов в очереди (по типам: active, backoff, gated, unschedulable) | gauge |
| `scheduler_scheduling_attempt_duration_seconds` | Гистограмма длительности попытки планирования | histogram |
| `scheduler_pod_scheduling_duration_seconds` | Полное время от создания пода до назначения на узел | histogram |
| `scheduler_preemption_attempts_total` | Количество попыток вытеснения | counter |
| `scheduler_preemption_victims_total` | Количество подов-жертв при вытеснении | counter |
| `scheduler_e2e_scheduling_duration_seconds` | End-to-end время планирования | histogram |
| `scheduler_plugin_execution_duration_seconds` | Время выполнения отдельных плагинов | histogram |

**Примеры PromQL-запросов:**
```promql
# Поды в очереди без назначения
scheduler_pending_pods{queue="unschedulable"} > 0

# 99-й перцентиль времени планирования
histogram_quantile(0.99, rate(scheduler_scheduling_attempt_duration_seconds_bucket[5m]))

# Среднее время планирования за последние 5 минут
rate(scheduler_scheduling_attempt_duration_seconds_sum[5m])
/
rate(scheduler_scheduling_attempt_duration_seconds_count[5m])

# Частота вытеснений за час
increase(scheduler_preemption_attempts_total[1h])

# Поды, заблокированные Scheduling Gates
scheduler_pending_pods{queue="gated"} > 0

# Среднее время выполнения плагина NodeResourcesFit
histogram_quantile(0.95, rate(scheduler_plugin_execution_duration_seconds_bucket{plugin="NodeResourcesFit"}[5m]))
```

### Логирование

**Уровень детализации логов:**
```bash
# Просмотр логов планировщика (kubeadm)
kubectl logs -n kube-system -l component=kube-scheduler --tail=100

# С фильтрацией по событиям планирования
kubectl logs -n kube-system -l component=kube-scheduler | grep -E "Scheduled|FailedScheduling"

# Увеличение детализации (v=3 для подробных логов каждого пода)
# В манифесте или конфигурации: --v=3
```

**Структура логов (пример):**
```
I0830 12:00:00.123456  12345 scheduler.go:200] "Attempting to schedule pod" pod="default/my-pod"
I0830 12:00:00.124567  12345 scheduler.go:300] "Successfully bound pod to node" pod="default/my-pod" node="worker-3"
```

### Диагностические команды

**Полный диагностический набор:**
```bash
# 1. Список Pending-подов в кластере
kubectl get pods --all-namespaces --field-selector=status.phase=Pending

# 2. Детали конкретного Pending-пода
kubectl describe pod <pod-name> -n <namespace>

# 3. Ресурсы узлов (доступные CPU/.Memory)
kubectl top nodes
kubectl describe nodes | grep -A 5 "Allocated resources"

# 4. Проверка Taints на узлах
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints

# 5. Проверка квот в namespace
kubectl get resourcequota -n <namespace>

# 6. Проверка конфликта Affinity
kubectl get nodes -l <label-selector>  # соответствует ли меткам в nodeSelector

# 7. Проверка состояния PV/PVC
kubectl get pvc -n <namespace>
kubectl get pv

# 8. Проверка событий планировщика за последние 10 минут
kubectl get events --field-selector reason=FailedScheduling --sort-by=.metadata.creationTimestamp -A
```

### Типичные причины отказа и решения

| Причина | Сообщение в Events | Решение |
| :--- | :--- | :--- |
| **Недостаток ресурсов** | `Insufficient cpu/memory` | Добавить узлы, уменьшить requests, или использовать Cluster Autoscaler |
| **NodeSelector** | `MatchNodeSelector` | Добавить требуемые метки на узлы или изменить selector в поде |
| **NodeAffinity** | `NodeAffinity` | Проверить `requiredDuringScheduling` правила |
| **Taints** | `Taints/Tolerations` | Добавить tolerations к поду или убрать taints с узлов |
| **Volume Binding** | `VolumeBindingWaiting` | Проверить StorageClass, зону доступности PV, WaitForFirstConsumer |
| **Pod Affinity** | `PodAffinity` | Убедиться, что целевые поды существуют и доступны |
| **Topology Spread** | `TopologySpread` | Увеличить `maxSkew` или изменить `whenUnsatisfiable: ScheduleAnyway` |
| **PDB вытеснения** | `Preemption` | Проверить PDB подов-жертв, рассмотреть отключение PDB для preemption |
| **Scheduling Gates** | `SchedulingGated` | Проверить внешний контроллер, ответственный за удаление gates |
| **Кворум etcd** | `Failed to create scheduler` | Проверить доступность etcd кворума |
| **RBAC** | `Unauthorized` | Проверить ServiceAccount и ClusterRoleBinding планировщика |

**Пошаговая диагностика Pending-пода:**
```bash
# Шаг 1: Определить причину из Events
kubectl describe pod <pod> -n <ns> | grep -A 10 "Events"

# Шаг 2: Если "Insufficient cpu", проверить доступные ресурсы
kubectl describe nodes | grep -B 5 -A 10 "Allocated resources"

# Шаг 3: Если "Taints", проверить taints на всех узлах
kubectl get nodes -o json | jq '.items[].spec.taints'

# Шаг 4: Если под назначается, но застревает в ContainerCreating —
# проверить PDB,.setImagePullPolicy, readiness
kubectl get events -n <ns> --field-selector involvedObject.name=<pod>

# Шаг 5: Если под заблокирован Scheduling Gates
kubectl get pod <pod> -o jsonpath='{.spec.schedulingGates}'
```

---

## Взаимодействие с Descheduler

Поскольку стандартный планировщик принимает решение только один раз, со временем кластер может стать несбалансированным (например, после добавления новых нод).
*   **Descheduler** анализирует кластер и выселяет (evict) поды, нарушающие политики (например, поды на перегруженных нодах при наличии свободных).
*   Выселенные поды пересоздаются и проходят через цикл `kube-scheduler` заново, попадая на оптимальные узлы.

---

## Дополнительная информация

### Производительность в больших кластерах

*   **percentageOfNodesToScore**: Планировщик прекращает поиск, как только находит определенный процент узлов (по умолчанию 10% для 5000+ узлов). Значение уменьшается с ростом кластера: для 100 узлов — 50%, для 5000+ — 10%.
*   **Сложность правил**: Избыточное использование `podAffinity` может значительно замедлить планирование. При hundreds подов с_mutual podAffinity_ планировщик проверяет попарные комбинации — это O(n^2).
*   **Размер очереди**: Держите количество Pending-подов в очереди minimal. Большое количество Pending-подов замедляет цикл планирования.
*   **Избегайте `nodeAffinity` на hundreds узлов**: Это увеличивает время фильтрации. Используйте `preferredDuringSchedulingIgnoredDuringExecution` вместо `required` когда возможно.

**Пороговые значения для больших кластерах (>1000 узлов):**
| Параметр | Значение по умолчанию | Рекомендация |
| :--- | :--- | :--- |
| `percentageOfNodesToScore` | 50 (<=100 узлов), 10 (>=5000) | Проверять, что хватает для размещения всех Pending-подов |
| `parallelism` (очередь) | числа ядер | Масштабировать с CPU планировщика |
| `maxPods` (на узел) | 110 | Увеличивать только при необходимости |

### HA и Production-конфигурация

**Высокая доступность планировщика:**
Kube-scheduler поддерживает HA через механизм **Leader Election**. В кластере работает несколько экземпляров планировщика, но активен только один (лидер). Остальные находятся в standby и перехватывают управление при сбое лидера.

**Типичная конфигурация для HA:**
```yaml
apiVersion: kubescheduler.config.k8s.io/v1
kind: KubeSchedulerConfiguration
leaderElection:
  leaderElect: true
  leaseDuration: 15s
  renewDeadline: 10s
  retryPeriod: 2s
  resourceLock: lease
  resourceName: kube-scheduler
  resourceNamespace: kube-system
profiles:
  - schedulerName: default-scheduler
    plugins:
      score:
        disabled:
        - name: NodeResourcesFit  # отключаем для балансировки
        enabled:
        - name: NodeResourcesBalancedAllocation
        - name: ImageLocality
```

**Проверка Leader Election:**
```bash
# Текущий лидер
kubectl get lease kube-scheduler -n kube-system -o jsonpath='{.spec.holderIdentity}'
# → ip-10-0-1-50_10-0-1-50@2024-01-01T00:00:00Z

# Все экземпляры планировщика
kubectl get pods -n kube-system -l component=kube-scheduler -o wide
```

**Оптимизация для production:**
*   Запускайте планировщик на выделенных узлах control plane (с taints `node-role.kubernetes.io/control-plane:NoSchedule`).
*   Рекомендуется минимум 2 узла control plane для HA.
*   Ресурсы планировщика: CPU 0.5-1 core, Memory 512MB-1GB (для кластеров до数千 узлов).
*   Логи: установите `--v=2` для production ($info-level), `--v=4` для отладки.

### Практические рекомендации

*   **Всегда указывайте `requests`**: Это база для расчета ресурсов планировщиком. Без `requests` планировщик считает под "пустым" и может разместить на перегруженном узле.
*   **Используйте PriorityClass**: Для разделения критических нагрузок от фоновых. Критичные сервисы с `system-cluster-critical` или пользовательские с `high` получат приоритет.
*   **PDB**: При вытеснении планировщик старается не нарушать [Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md). Определите PDB для каждого критичного сервиса.
*   **Планируйте Capacity**: Мониторьте `scheduler_pending_pods{queue="unschedulable"}` — растущее значение указывает на нехватку ресурсов.
*   **Избегайте `nodeSelector` + `nodeAffinity` одновременно**: Это избыточно — `nodeAffinity` более гибкий и покрывает все кейсы `nodeSelector`.

### Тестирование конфигурации: kube-scheduler-simulator

Перед применением `KubeSchedulerConfiguration` или кастомных плагинов в production конфигурацию можно проверить в **kube-scheduler-simulator** (проект kubernetes-sigs) — веб-симулятор планировщика:

* Создаются и редактируются Nodes, Pods, PV/PVC, StorageClasses, PriorityClasses через YAML;
* Подключается произвольный `KubeSchedulerConfiguration` (переменная окружения `KUBE_SCHEDULER_CONFIG_PATH`; на результаты планирования влияют поля `.profiles`);
* Для каждого пода видны результаты **каждого Filter-плагина**, **каждого Score-плагина** и итоговый нормализованный балл с учётом весов плагинов по каждому узлу;
* Симулятор работает на фейковом кластере **KWOK** (Kubernetes WithOut Kubelet) — Kubernetes без kubelet, что позволяет моделировать кластер без реальных нод;
* Запуск: `make docker_build_and_up` в репозитории, доступ на `http://localhost:3000`;
* Поддерживаются out-of-tree плагины — можно тестировать кастомные плагины планировщика.

Репозиторий: [kubernetes-sigs/kube-scheduler-simulator](https://github.com/kubernetes-sigs/kube-scheduler-simulator).

### Расширяемость (Scheduling Framework)

Помимо встроенных плагинов, планировщик поддерживает кастомные плагины через **Scheduling Framework**. Кастомные плагины реализуют интерфейсы на различных Extension Points:

*   **QueueSort**: Определение порядка подов в очереди (например, по времени создания или приоритету).
*   **Filter**: Дополнительная фильтрация узлов (например, проверка лимитов квот).
*   **Score**: Веса для оценки узлов (например, предпочтение определенных зон).
*   **Bind**: Кастомная логика привязки (например, интеграция с внешними системами).

**Пример конфигурации кастомного плагина:**
```yaml
apiVersion: kubescheduler.config.k8s.io/v1
kind: KubeSchedulerConfiguration
profiles:
  - schedulerName: default-scheduler
    pluginConfig:
    - name: NodeResourcesFit
      args:
        scoringStrategy:
          type: MostAllocated  # стратегия bin packing
          resources:
          - name: cpu
            weight: 1
          - name: memory
            weight: 1
```

### Coscheduling / Gang Scheduling

**Coscheduling** — паттерн планирования, при котором группа подов планируется **одновременно**. Все поды группы должны быть запланированы или ни один. Используется для HPC, ML-обучения, Spark/ Ray-задач, где поды группы зависимы друг от друга.

**Зачем нужен:** Без Coscheduling возможна ситуация, когда 4 из 5 подов Spark-задачи запланированы, а 5-й ждёт ресурсов. Остальные 4 пода потребляют ресурсы без результативной работы.

**Реализация через Scheduling Framework:**
1. **QueueSort:** Поды одной группы получают одинаковый приоритет в очереди.
2. **PreFilter:** Подсчитывает количество подов группы в очереди.
3. **Filter:** Проверяет, что на узле достаточно ресурсов для **всей** группы.
4. **Permit:** Задерживает (wait) каждый под группы, пока не будут приняты все. При接纳 всех — разрешает запуск. При отказе хотя бы одного — отклоняет группу.

**Пример: Spark-задача с 4 исполнителями**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: spark-executor-0
  labels:
    app: spark
    group: spark-job-1
spec:
  schedulerName: default-scheduler
  containers:
  - name: executor
    image: spark:3.5
    resources:
      requests:
        cpu: "4"
        memory: "8Gi"
      limits:
        cpu: "4"
        memory: "8Gi"
---
apiVersion: v1
kind: Pod
metadata:
  name: spark-executor-1
  labels:
    app: spark
    group: spark-job-1
spec:
  schedulerName: default-scheduler
  containers:
  - name: executor
    image: spark:3.5
    resources:
      requests:
        cpu: "4"
        memory: "8Gi"
      limits:
        cpu: "4"
        memory: "8Gi"
---
# ... spark-executor-2, spark-executor-3
```

**Внешний плагин coscheduling (SIG Scheduling):**
Для полноценного Coscheduling используется out-of-tree плагин `coscheduling` из репозитория `scheduler-plugins`. Он добавляет:
* **QueueSort:** Сортировка подов группы по приоритету и времени создания.
* **Permit:** Механизм ожидания (wait) и接纳 (authorize) для всей группы.
* **Filter:** Проверка, что ресурсы доступны для всей группы.

**Диагностика:**
```bash
# Проверка подов в очереди ожидания
kubectl get pods --field-selector status.phase=Pending -o json | jq '.items[] | select(.spec.schedulerName == "default-scheduler") | {name: .metadata.name, group: .metadata.labels.group}'

# Проверка событий планирования
kubectl get events --field-selector reason=FailedScheduling | grep -i "gang\|coscheduling"

# Метрики планировщика
kubectl get --raw /metrics | grep scheduler_pending_pods{queue="gated"}
```

**Ограничения:**
* Coscheduling **не встроен** в стандартный kube-scheduler — требует установки плагина `coscheduling`.
* Поды группы должны иметь общую метку (например, `group: spark-job-1`) для идентификации.
* При использовании с HPA.coscheduling может конфликтовать с автоматическим масштабированием.
* PDB подов группы должны позволять одновременное выселение всех подов при необходимости.

### Ограничения и известные особенности

*   Планировщик не учитывает будущие изменения ресурсов (например, HPA-скейлинг). Планирование происходит на основе текущих `requests`.
*   `PodAffinity` и `PodAntiAffinity` с `requiredDuringSchedulingIgnoredDuringExecution` могут вызвать deadlock, если правила противоречивы.
*   При большом количестве подов (>10000 в очереди) время планирования может превысить SLA. Мониторьте `scheduler_scheduling_attempt_duration_seconds`.
*   `nodeName` (прямое назначение) **полностью обходит** планировщик — используйте только для static pods или специфических кейсов.
*   Планировщик не переназначает поды после их запуска. Для балансировки используйте Descheduler.

**См. также:**
*   [Affinity и Anti-Affinity](../Scheduling/affinity.md)
*   [Taints and Tolerations](../Scheduling/taints_and_tolerations.md)
*   [QoS, Requests и Limits](../Scheduling/qos_limit_and_requests.md)
*   [Topology Manager](../Scheduling/topology_manager.md) — NUMA-осознанное планирование ресурсов
*   [Memory Manager](../Scheduling/memory_manager.md) — NUMA-осознанное выделение памяти
*   [Device Manager](../Scheduling/device_manager.md) — управление GPU и специализированным оборудованием
*   [PriorityClass](./priorityclass.md)
*   [Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md)
*   [Продвинутые темы Pod](../Base/Pod/pod_advanced_topics.md)
*   [Обзор решений для планирования](../Scheduling/scheduling_solutions_overview.md) — матрица выбора планировщика
*   [Kueue](../Scheduling/kueue.md) — очереди и квоты для batch/AI-нагрузок
*   [Apache YuniKorn](../Scheduling/yunikorn.md) — иерархические очереди
*   [KAI Scheduler](../Scheduling/kai_scheduler.md) — topology-aware GPU-планирование
