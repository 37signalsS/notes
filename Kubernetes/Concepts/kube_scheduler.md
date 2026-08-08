# Kube-scheduler: планировщик подов в Kubernetes

## Определение

**Kube-scheduler** — это основной компонент плоскости управления (Control Plane) Kubernetes, ответственный за назначение подов (Pods) на доступные рабочие узлы (Nodes). Он непрерывно отслеживает (watch) API-сервер на предмет появления новых подов, у которых поле `spec.nodeName` не заполнено, и выбирает для них наиболее подходящий узел на основе набора политик, ресурсов и ограничений.

**Ключевая роль:** Планировщик является "интеллектуальным диспетчером" кластера. Его задача — обеспечить эффективную утилизацию ресурсов и соблюдение требований доступности приложений. Важно понимать, что планировщик принимает решение только в момент создания пода (однократное действие).

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
*   **Scheduling Gates**: Новая фича (v1.27+), позволяющая удерживать под в состоянии `Pending`, пока внешние условия (например, подготовка квоты или внешних ресурсов) не будут выполнены.

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
```

Использование в поде:
```yaml
spec:
  schedulerName: bin-packing-scheduler
```

---

## Диагностика и отладка

### Мониторинг (Метрики Prometheus)
Для оценки здоровья планировщика отслеживайте следующие метрики:
*   `scheduler_pending_pods`: Количество подов, ожидающих в очереди.
*   `scheduler_scheduling_attempt_duration_seconds`: Длительность попытки планирования (P99).
*   `scheduler_preemption_attempts_total`: Количество попыток вытеснения.
*   `scheduler_pod_scheduling_duration_seconds`: Полное время от создания пода до назначения на узел.

### Статус Pending
Если под не назначается на узел:
1.  **Проверка событий**: `kubectl describe pod <pod-name>` (секция `Events`).
2.  **Проверка ресурсов**: `kubectl top nodes` и `kubectl describe node`.
3.  **Логи планировщика**: `kubectl logs -n kube-system -l component=kube-scheduler`.

### Типичные причины отказа:
*   **Insufficient cpu/memory**: На узлах недостаточно свободных ресурсов согласно `requests`.
*   **MatchNodeSelector / NodeAffinity**: Нет узлов с требуемыми метками.
*   **Taints / Tolerations**: Узлы имеют taints, которые под не переносит.
*   **VolumeBindingWaiting**: Под ожидает создания PV в нужной зоне (WaitForFirstConsumer).

---

## Взаимодействие с Descheduler

Поскольку стандартный планировщик принимает решение только один раз, со временем кластер может стать несбалансированным (например, после добавления новых нод).
*   **Descheduler** анализирует кластер и выселяет (evict) поды, нарушающие политики (например, поды на перегруженных нодах при наличии свободных).
*   Выселенные поды пересоздаются и проходят через цикл `kube-scheduler` заново, попадая на оптимальные узлы.

---

## Дополнительная информация

**Производительность в больших кластерах:**
*   **percentageOfNodesToScore**: Планировщик прекращает поиск, как только находит определенный процент узлов (по умолчанию 10% для 5000+ узлов).
*   **Сложность правил**: Избыточное использование `podAffinity` может значительно замедлить планирование.

**Рекомендации:**
*   **Всегда указывайте `requests`**: Это база для расчета ресурсов планировщиком.
*   **Используйте PriorityClass**: Для разделения критических нагрузок от фоновых.
*   **PDB**: При вытеснении планировщик старается не нарушать [Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md).

**См. также:**
*   [Affinity и Anti-Affinity](../Scheduling/affinity.md)
*   [Taints and Tolerations](../Scheduling/taints_and_tolerations.md)
*   [QoS, Requests и Limits](../Scheduling/qos_limit_and_requests.md)
*   [PriorityClass](./priorityclass.md)
*   [Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md)
