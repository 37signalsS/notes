# Kube-scheduler: планировщик подов в Kubernetes

## Определения

**Kube-scheduler** — компонент плоскости управления (Control Plane) Kubernetes, отвечающий за назначение подов (Pods) на доступные рабочие узлы (Nodes). Он принимает решение о размещении на основе требований пода и доступных ресурсов кластера.

**Основная задача:** найти для каждого пода узел, который соответствует всем жёстким требованиям (ресурсы, метки, taints, affinity) и является наилучшим по ряду критериев (свободные ресурсы, сбалансированность, предпочтения).

После выбора планировщик сообщает API-серверу о назначении, и kubelet на выбранном узле запускает под.

## Основные концепции

### Процесс планирования

Процесс планирования выполняется в два основных этапа:

**1. Фильтрация (Predicates / Filtering)**
Отсеиваются все узлы, которые не могут запустить под. Проверяются:

* Достаточность свободных ресурсов (CPU (Central Processing Unit), память, диски, порты).
* Соответствие меток узла требованиям `nodeSelector` или `nodeAffinity`.
* Отсутствие запрещающих taints без соответствующих `tolerations`.
* Соблюдение правил Pod Affinity/Anti-Affinity.
* Отсутствие конфликтов с уже запущенными подами (например, занятые `hostPort`).

**Результат:** список подходящих узлов.

**2. Оценка (Scoring / Prioritization)**
Каждый оставшийся узел получает баллы по различным критериям. Чем больше баллов, тем предпочтительнее узел. Критерии оценки:

* Количество свободных ресурсов после запуска пода.
* Сбалансированность использования ресурсов.
* Близость к другим заданным подам для уменьшения сетевых задержек.
* Выполнение правил предпочтений (`preferred` affinity).

**Результат:** выбирается узел с наибольшей суммой баллов. Если подходящих узлов нет, под остаётся в статусе `Pending`.

### Механизмы управления планированием

* **NodeSelector:** простейший способ указать, что под должен быть размещён на узле с определённой меткой. Более гибкая альтернатива — [Node Affinity](../Scheduling/affinity.md).
* **Affinity и Anti-Affinity:** правила с уровнями строгости (`required` — жёсткие, `preferred` — мягкие). Подробнее: [Affinity и Anti-Affinity](../Scheduling/affinity.md).
* **Taints и Tolerations:** механизм «отталкивания» на уровне узлов. Подробнее: [Taints and Tolerations](../Scheduling/taints_and_tolerations.md).
* **Resource Requests и Limits:** планировщик учитывает `requests` для расчёта доступного места. Подробнее: [QoS (Quality of Service), Requests и Limits](../Scheduling/qos_limit_and_requests.md).
* **Приоритеты подов (Pod Priority and Preemption):** поды с высоким приоритетом планируются первыми и могут вытеснять низкоприоритетные поды. Подробнее: [PriorityClass](./priorityclass.md).

### Жизненный цикл планирования

1. Пользователь создаёт под, API-сервер сохраняет его в `etcd` с пустым полем `spec.nodeName`.
2. Планировщик обнаруживает новый под через механизм `watch`.
3. Этап фильтрации: отбор подходящих узлов.
4. Этап оценки: ранжирование узлов.
5. Привязка (Binding): планировщик выбирает узел и выполняет операцию `patch` для ресурса пода, заполняя `spec.nodeName`.
6. Уведомление Kubelet: `kubelet` на целевом узле видит назначение через `watch` и приступает к запуску контейнеров.

## Практические сценарии

### Размещение на узлах с GPU

**Задача:** запустить нагрузку Machine Learning (ML) только на узлах с **GPU (Graphics Processing Unit)**.

**Решение:** комбинация `nodeAffinity` и `tolerations`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: ml-training
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: nvidia.com/gpu
            operator: Exists
  tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
  containers:
  - name: trainer
    image: tensorflow/tensorflow:latest-gpu
    resources:
      limits:
        nvidia.com/gpu: "1"
```

### Высокая доступность с Pod Anti-Affinity

**Задача:** распределить реплики приложения по разным узлам для отказоустойчивости.

**Решение:** использовать `podAntiAffinity` с `topologyKey: kubernetes.io/hostname`.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web-app
  template:
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app: web-app
            topologyKey: kubernetes.io/hostname
      containers:
      - name: web
        image: nginx:1.28.0
```

### Диагностика Pending-подов

**Симптом:** под остаётся в статусе `Pending`.

**Диагностика:**

```bash
# Проверить события пода
kubectl describe pod <pod-name>

# Проверить доступные ресурсы узлов
kubectl top nodes
```

**Типичные причины:**

* Недостаточно ресурсов (CPU/память).
* Не выполнены требования `nodeAffinity` или `nodeSelector`.
* Taints узлов без соответствующих `tolerations`.
* Конфликты `podAntiAffinity`.

## Дополнительная информация

**Особенности производительности:**

* В больших кластерах (>500 узлов) широкие селекторы в `podAffinity` могут замедлять планирование.
* Избыток жёстких правил (`required`) снижает гибкость системы при отказах узлов.

**Рекомендации:**

* Всегда указывайте `requests` для эффективного распределения ресурсов.
* Используйте `PriorityClass` для разделения сред (production/staging).
* Комбинируйте `taints` для резервирования узлов с `nodeAffinity` для точного размещения.

**См. также:**

* [Affinity и Anti-Affinity](../Scheduling/affinity.md)
* [Taints and Tolerations](../Scheduling/taints_and_tolerations.md)
* [QoS, Requests и Limits](../Scheduling/qos_limit_and_requests.md)
* [PriorityClass](./priorityclass.md)
