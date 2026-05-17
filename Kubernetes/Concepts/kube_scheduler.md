# Kube-scheduler: Планировщик подов в Kubernetes

## Определения

**Kube-scheduler** — компонент Control Plane Kubernetes, отвечающий за назначение подов (Pods) на доступные рабочие узлы (Nodes). Принимает решение о размещении на основе требований пода и доступных ресурсов кластера.

**Основная задача:** Найти для каждого пода ноду, которая соответствует всем жёстким требованиям (ресурсы, метки, taints, affinity) и является наилучшей по ряду критериев (свободные ресурсы, сбалансированность, предпочтения).

После выбора scheduler сообщает API-серверу о назначении, и kubelet на выбранной ноде запускает под.

## Основные концепции

### Процесс планирования

Процесс планирования делится на два этапа:

**1. Фильтрация (Predicates / Filtering):** Отсеиваются все ноды, которые не могут запустить под. Проверяются:

* Достаточность свободных ресурсов (CPU, память, диски, порты)
* Соответствие меток ноды требованиям `nodeSelector` или `nodeAffinity`
* Отсутствие запрещающих taints без соответствующих `tolerations`
* Соблюдение правил Pod Affinity/Anti-Affinity
* Отсутствие конфликтов с уже запущенными подами (например, занятые `hostPort`)

**Результат:** Список подходящих нод.

**2. Оценка (Scoring / Prioritization):** Каждая оставшаяся нода получает баллы по различным критериям. Чем больше баллов, тем предпочтительнее нода.

**Критерии оценки:**

* Количество свободных ресурсов после запуска пода
* Сбалансированность использования ресурсов
* Близость к другим заданным подам (для уменьшения сетевых задержек)
* Выполнение правил предпочтений (`preferred` affinity)

**Результат:** Нода с наибольшей суммой баллов выбирается для запуска пода.

Если подходящих нод нет, под остаётся в статусе `Pending`, и scheduler периодически повторяет попытки планирования.

### Механизмы управления планированием

**NodeSelector:** Простейший способ указать, что под должен быть размещён на ноде с определённой меткой. Более гибкая альтернатива — [Node Affinity](../Scheduling/affinity.md) с поддержкой сложных выражений (`In`, `NotIn`, `Exists`, `Gt`, `Lt`).

**Affinity и Anti-Affinity:** Выразительные правила с условиями и уровнями строгости (`requiredDuringSchedulingIgnoredDuringExecution`, `preferredDuringSchedulingIgnoredDuringExecution`). Типы: Node Affinity, Pod Affinity, Pod Anti-Affinity. Подробнее: [Affinity и Anti-Affinity](../Scheduling/affinity.md).

**Taints и Tolerations:** Механизм «отталкивания» на уровне узлов. Taints наносятся на ноды, Tolerations задаются в спецификации пода. Эффекты: `NoSchedule`, `PreferNoSchedule`, `NoExecute`. Подробнее: [Taints and Tolerations](../Scheduling/taints_and_tolerations.md).

**Resource Requests и Limits:** Scheduler учитывает `requests` для планирования и `limits` для ограничения. Без указания `requests` под может быть запланирован на перегруженную ноду. Подробнее: [QoS, Requests и Limits](../Scheduling/qos_limit_and_requests.md).

**Приоритеты подов (Pod Priority and Preemption):** Поды разделяются по приоритетам через `PriorityClass`. Поды с высоким приоритетом планируются первыми, при нехватке ресурсов возможно вытеснение низкоприоритетных подов. Подробнее: [PriorityClass](./priorityclass.md).

### Жизненный цикл планирования

1. Пользователь создаёт под через `kubectl apply -f pod.yaml`
2. API-сервер валидирует и сохраняет под в `etcd` (поле `spec.nodeName` пустое)
3. Scheduler обнаруживает под через механизм `watch` за API-сервером
4. Фильтрация: Scheduler отбирает ноды, удовлетворяющие требованиям
5. Оценка: Scheduler ранжирует подходящие ноды
6. Привязка (Binding): Scheduler принимает решение о назначении пода.
7. Патчинг: Scheduler выполняет операцию `patch` для ресурса пода, заполняя поле `spec.nodeName` выбранным узлом. API-сервер проводит запрос по пайплайну обработки и записывает изменения в `etcd`.
8. Уведомление Kubelet: Каждый `kubelet` использует подписку `watch` с точечной фильтрацией `fieldSelector` (а именно: `spec.nodeName=имя_данной_ноды`), поэтому он видит только те поды, которые назначены именно ему.
9. Kubelet извлекает спецификацию назначенного пода и приступает к его запуску на ноде.

## Практические сценарии

### Размещение на узлах с GPU

**Задача:** Запустить ML-воркфлоу только на узлах с GPU.

**Решение:** Комбинация `nodeAffinity` и `tolerations`:

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

**Задача:** Распределить реплики приложения по разным узлам для отказоустойчивости.

**Решение:** Использовать `podAntiAffinity` с `topologyKey: kubernetes.io/hostname`:

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

Альтернатива: [TopologySpreadConstraints](../Scheduling/affinity.md) обеспечивают более равномерное распределение.

### Приоритизация критичных workload'ов

**Задача:** Гарантировать запуск production-приложений даже при нехватке ресурсов.

**Решение:** Использовать `PriorityClass` с высоким приоритетом:

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: production-critical
value: 1000000
globalDefault: false
description: "Высокий приоритет для production"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: critical-app
spec:
  template:
    spec:
      priorityClassName: production-critical
      containers:
      - name: app
        image: my-app:latest
        resources:
          requests:
            cpu: "1"
            memory: "2Gi"
```

При нехватке ресурсов scheduler вытеснит поды с низким приоритетом.

### Диагностика Pending-подов

**Симптом:** Под остаётся в статусе `Pending` длительное время.

**Диагностика:**

```bash
# Проверить события пода
kubectl describe pod <pod-name>

# Проверить доступные ресурсы нод
kubectl top nodes

# Проверить taints нод
kubectl describe node <node-name> | grep -A 5 "Taints"
```

**Типичные причины:**

* Недостаточно ресурсов (CPU/память)
* Не выполнены требования `nodeAffinity`/`nodeSelector`
* Taints нод без соответствующих `tolerations`
* Не выполнены правила `podAntiAffinity` (слишком много реплик)

Сообщения в событиях пода: `0/10 nodes are available: 10 Insufficient cpu`, `0/5 nodes are available: 5 node(s) didn't match Pod Anti-Affinity rules`.

## Дополнительная информация

**Производительность планировщика:**

* В больших кластерах (>500 узлов) избегайте широких селекторов в `podAffinity`/`podAntiAffinity` (`matchLabels: {}`) — это замедляет работу scheduler
* Комбинация множества правил (`nodeAffinity` + `podAntiAffinity` + `topologySpreadConstraints`) может увеличить время планирования
* Отдавайте предпочтение мягким правилам (`preferred...`) — жёсткие правила (`required...`) могут сделать систему хрупкой

**Рекомендации:**

* Всегда указывайте `requests` — без них scheduler не может эффективно распределять поды
* Используйте `PriorityClass` для разделения сред (production/staging/dev)
* Комбинируйте механизмы: `taint` для резервирования узлов + `nodeAffinity` для размещения
* Мониторьте Pending-поды — это индикатор нехватки ресурсов или неправильной конфигурации
* Тестируйте сценарии отказа — проверяйте реакцию scheduler на потерю узлов
