# Kube-scheduler: планировщик подов в Kubernetes

## Определения

**Kube-scheduler** — это основной компонент плоскости управления (Control Plane) Kubernetes, отвечающий за назначение подов (Pods) на доступные рабочие узлы (Nodes). Он непрерывно отслеживает (watch) API-сервер на предмет появления новых подов, у которых поле `spec.nodeName` не заполнено, и выбирает для них наиболее подходящий узел на основе набора политик и ограничений.

**Основная задача:** найти для каждого пода узел, который удовлетворяет всем жестким требованиям (Predicates) и является наилучшим согласно критериям предпочтения (Priorities).

После того как планировщик выбирает узел, он выполняет операцию привязки (Binding), сообщая API-серверу о своем решении. Затем `kubelet` на выбранном узле видит назначение и приступает к запуску контейнеров.

## Основные концепции

### Процесс планирования (Классическая модель)

Процесс выбора узла для пода начинается с определения ответственного планировщика и проходит через цикл проверок:

#### 0. Выбор планировщика (Scheduler Selection)
В кластере Kubernetes может одновременно работать несколько планировщиков. 
*   **`spec.schedulerName`**: Поле в спецификации Pod, которое определяет, какой планировщик должен обработать данный объект.
*   Если поле не указано, Pod подхватывается планировщиком по умолчанию (`default-scheduler`). 
*   Если указано имя несуществующего планировщика, Pod навсегда останется в состоянии `Pending`.

#### 1. Фильтрация (Predicates / Filtering)
На этом этапе планировщик отсеивает все узлы, которые физически или логически не могут запустить данный под. Проверяются следующие условия:
*   **Достаточность ресурсов**: Наличие свободных CPU, RAM, эфемерного хранилища и свободных портов (`hostPort`).
*   **Ошибки узла и допуски (Taints & Tolerations)**: Проверка наличия `taints` на узле. Pod будет запланирован только если у него есть соответствующие `tolerations`.
*   **Правила сходства (Affinity & Anti-Affinity)**: Проверка `nodeAffinity`, `podAffinity` и `podAntiAffinity`.
*   **Дисковые ограничения**: Проверка возможности подключения требуемых томов (PVC/PV). При использовании `volumeBindingMode: WaitForFirstConsumer` планировщик также учитывает топологию доступности дисков.

**Результат:** список "подходящих" узлов (feasible nodes). Если список пуст, под остается в статусе `Pending`, а причина отказа регистрируется в разделе событий (`Events`).

#### 2. Оценка (Scoring / Prioritization)
Каждый узел из списка прошедших фильтрацию получает баллы (от 0 до 100) по ряду критериев. Планировщик суммирует баллы от разных функций оценки:
*   **LeastRequestedPriority**: Предпочтение отдается узлам с меньшей загрузкой (равномерное распределение нагрузки по кластеру).
*   **MostRequestedPriority**: Предпочтение отдается более нагруженным узлам (стратегия упаковки — "bin packing", полезна для экономии ресурсов в облаке).
*   **ImageLocalityPriority**: Приоритет узлам, на которых уже скачаны необходимые Docker-образы.
*   **BalancedResourceAllocation**: Предпочтение узлам, где после запуска пода соотношение CPU и RAM будет наиболее сбалансированным.
*   **NodeAffinityPriority**: Учет мягких предпочтений (`preferredDuringSchedulingIgnoredDuringExecution`).

**Результат:** Выбирается узел с наивысшим баллом. Если таких несколько, выбор происходит случайным образом.

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

## Жизненный цикл планирования (Workflow)

1.  **Пользователь/Контроллер** создает под через API.
2.  **API-сервер** сохраняет объект в `etcd` с пустым полем `spec.nodeName`.
3.  **Kube-scheduler** обнаруживает новый под через `watch`.
4.  **Scheduling Cycle (Синхронный)**:
    *   Планировщик извлекает под из очереди.
    *   Проходит этапы **Filter** и **Score**.
    *   Выбирает узел.
    *   Выполняет этап **Reserve** в локальном кеше.
5.  **Binding Cycle (Асинхронный)**:
    *   Выполняет этап **Permit** (проверка разрешений).
    *   Выполняет этап **PreBind** (подготовка).
    *   Отправляет запрос `patch` к API-серверу для заполнения `nodeName` (этап **Bind**).
6.  **Kubelet** на узле видит обновление, скачивает образы и запускает контейнеры.

## Практические сценарии

### Сценарий 1: Размещение на узлах с GPU
**Задача:** Направить ML-нагрузку только на узлы с видеокартами, зарезервированными для этих целей.

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
```

## Диагностика и отладка

### Статус Pending
Если под не назначается на узел, выполните следующие шаги:

1.  **Проверка событий**:
    ```bash
    kubectl describe pod <pod-name>
    # Ищите секцию 'Events', там будет указано количество узлов и причины отказа
    ```
2.  **Проверка ресурсов узлов**:
    ```bash
    kubectl top nodes
    kubectl describe node <node-name> | grep -A 5 Allocated
    ```
3.  **Логи планировщика**:
    В HA-кластерах логи активного планировщика помогут понять логику принятия решений:
    ```bash
    kubectl logs -n kube-system -l component=kube-scheduler
    ```

### Типичные причины отказа в планировании:
*   **Insufficient cpu/memory**: На узлах недостаточно свободных ресурсов согласно `requests`.
*   **MatchNodeSelector / NodeAffinity**: Нет узлов с требуемыми метками.
*   **Taints / Tolerations**: Узлы имеют taints, которые не "переносит" под.
*   **PodAffinityRulesNotMet**: Нарушены правила близости к другим подам.
*   **Too many pods**: Достигнут лимит `maxPods` на узле (по умолчанию 110).

## Дополнительная информация

**Производительность в больших кластерах:**
*   **percentageOfNodesToScore**: Планировщик прекращает поиск подходящих узлов, как только находит определенный процент от общего числа. Для кластера в 5000 узлов это значение по умолчанию равно 10%.
*   **Сложность правил**: Избыточное использование `podAffinity` в больших кластерах может значительно замедлить планирование из-за необходимости пересчета связей.

**Рекомендации:**
*   **Всегда указывайте `requests`**: Без них планировщик не может корректно рассчитать нагрузку.
*   **Используйте `PriorityClass`**: Для разделения критических нагрузок от фоновых.
*   **PDB**: При использовании вытеснения планировщик старается не нарушать [Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md).

**См. также:**
*   [Affinity и Anti-Affinity](../Scheduling/affinity.md)
*   [Taints and Tolerations](../Scheduling/taints_and_tolerations.md)
*   [QoS, Requests и Limits](../Scheduling/qos_limit_and_requests.md)
*   [PriorityClass](./priorityclass.md)
*   [Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md)
