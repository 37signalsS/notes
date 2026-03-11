# Kube-scheduler: Планировщик подов в Kubernetes

## Определения

**Kube-scheduler** — компонент Control Plane Kubernetes, отвечающий за назначение подов (Pods) на доступные рабочие узлы (Nodes). Принимает решение о размещении на основе требований пода и доступных ресурсов кластера.

**Основная задача:** Найти для каждого пода ноду, которая:

- Соответствует всем жёстким требованиям (ресурсы, метки, taints, affinity)
- Является наилучшей по ряду критериев (свободные ресурсы, сбалансированность, предпочтения)

После выбора scheduler сообщает API-серверу о назначении, и kubelet на выбранной ноде запускает под.

> **Связанные компоненты:** [Control Plane Architecture](./control_plane_architecture.md), [Affinity и Anti-Affinity](../Scheduling/affinity.md), [Taints and Tolerations](../Scheduling/taints_and_tolerations.md), [PriorityClass](./priorityclass.md), [QoS, Requests и Limits](../Scheduling/qos_limit_and_requests.md)

---

## Основные концепции

### Процесс планирования

Процесс планирования делится на два этапа:

#### 1. Фильтрация (Predicates / Filtering)

Отсеиваются все ноды, которые не могут запустить под. Проверяются:

- **Достаточно ли свободных ресурсов** (CPU, память, диски, порты)
- **Соответствуют ли метки ноды** требованиям `nodeSelector` или `nodeAffinity`
- **Не запрещают ли taints** запуск пода без соответствующих `tolerations`
- **Соблюдены ли правила Pod Affinity/Anti-Affinity**
- **Нет ли конфликтов** с уже запущенными подами (например, занятые `hostPort`)

**Результат:** Список подходящих нод.

#### 2. Оценка (Scoring / Prioritization)

Каждая оставшаяся нода получает баллы по различным критериям. Чем больше баллов, тем предпочтительнее нода.

**Критерии оценки:**

- Количество свободных ресурсов после запуска пода
- Сбалансированность использования ресурсов
- Близость к другим заданным подам (для уменьшения сетевых задержек)
- Выполнение правил предпочтений (`preferred` affinity)

**Результат:** Нода с наибольшей суммой баллов выбирается для запуска пода.

> **Если подходящих нод нет:** Под остаётся в статусе `Pending`, и scheduler периодически повторяет попытки планирования.

### Ключевые механизмы управления планированием

#### NodeSelector

Простейший способ указать, что под должен быть размещён на ноде с определённой меткой.

```yaml
spec:
  nodeSelector:
    disktype: ssd
```

> **Более гибкая альтернатива:** [Node Affinity](../Scheduling/affinity.md) поддерживает сложные выражения (`In`, `NotIn`, `Exists`, `Gt`, `Lt`).

#### Affinity и Anti-Affinity

Более выразительные правила, поддерживающие условия и уровни строгости:

- **`requiredDuringSchedulingIgnoredDuringExecution`** — жёсткое требование
- **`preferredDuringSchedulingIgnoredDuringExecution`** — предпочтение

**Типы:**

| Тип | Описание | Сценарий |
|-----|----------|----------|
| **Node Affinity** | Привязка к характеристикам ноды | GPU, SSD, зона доступности |
| **Pod Affinity** | Привязка к расположению других подов | Коликейшн связанных компонентов |
| **Pod Anti-Affinity** | Избегание расположения с другими подами | Высокая доступность, распределение реплик |

Подробно: [Affinity и Anti-Affinity](../Scheduling/affinity.md).

#### Taints и Tolerations

Механизм «отталкивания» на уровне узлов:

- **Taints** наносятся на ноды и отталкивают поды без соответствующих `tolerations`
- **Tolerations** задаются в спецификации пода и позволяют «терпеть» taints

**Эффекты Taints:**

- `NoSchedule` — новые поды без toleration не размещаются
- `PreferNoSchedule` — мягкая версия `NoSchedule`
- `NoExecute` — новые поды не размещаются, существующие вытесняются

Подробно: [Taints and Tolerations](../Scheduling/taints_and_tolerations.md).

#### Resource Requests и Limits

Scheduler учитывает запрошенные подом ресурсы (`requests`) и доступные на ноде.

- **`requests`** — гарантированное количество ресурсов, используется для планирования
- **`limits`** — максимальное количество ресурсов, используется для ограничения

> **Важно:** Без указания `requests` под может быть запланирован на перегруженную ноду, что приведёт к нехватке ресурсов для других подов.

Подробно: [QoS, Requests и Limits](../Scheduling/qos_limit_and_requests.md).

#### Приоритеты подов (Pod Priority and Preemption)

Поды можно разделять по приоритетам через `PriorityClass`.

- **Порядок планирования:** Поды с более высоким приоритетом планируются первыми
- **Вытеснение (Preemption):** Если высокоприоритетный под не может быть запланирован, scheduler может вытеснить один или несколько низкоприоритетных подов

Подробно: [PriorityClass](./priorityclass.md).

### Жизненный цикл планирования

1. **Пользователь создаёт под** через `kubectl apply -f pod.yaml`
2. **API-сервер валидирует** и сохраняет под в `etcd` (поле `spec.nodeName` пустое)
3. **Scheduler обнаруживает под** через механизм `watch` за API-сервером
4. **Фильтрация:** Scheduler отбирает ноды, удовлетворяющие требованиям
5. **Оценка:** Scheduler ранжирует подходящие ноды
6. **Привязка (Binding):** Scheduler отправляет решение API-серверу
7. **API-сервер обновляет под** в `etcd`, записывая `spec.nodeName`
8. **Kubelet на выбранной ноде** обнаруживает назначенный под и запускает его

---

## Практические сценарии

### Сценарий 1: Размещение на узлах с GPU

**Задача:** Запустить ML-воркфлоу только на узлах с GPU.

**Решение:** Комбинация `nodeAffinity` и `tolerations`.

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

### Сценарий 2: Высокая доступность с Pod Anti-Affinity

**Задача:** Распределить реплики приложения по разным узлам для отказоустойчивости.

**Решение:** Использовать `podAntiAffinity` с `topologyKey: kubernetes.io/hostname`.

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

> **Альтернатива:** [TopologySpreadConstraints](../Scheduling/affinity.md) обеспечивают более равномерное распределение.

### Сценарий 3: Приоритизация критичных workload'ов

**Задача:** Гарантировать запуск production-приложений даже при нехватке ресурсов.

**Решение:** Использовать `PriorityClass` с высоким приоритетом.

```yaml
# 1. Создать PriorityClass
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: production-critical
value: 1000000
globalDefault: false
description: "Высокий приоритет для production"

---
# 2. Применить к Deployment
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

### Сценарий 4: Диагностика Pending-подов

**Симптом:** Под остаётся в статусе `Pending` длительное время.

**Диагностика:**

```bash
# 1. Проверить события пода
kubectl describe pod <pod-name>

# 2. Искать сообщения о планировании:
# - "0/10 nodes are available: 10 Insufficient cpu"
# - "0/5 nodes are available: 5 node(s) didn't match Pod Anti-Affinity rules"
# - "0/3 nodes are available: 3 node(s) had taint {node-role.kubernetes.io/master: NoSchedule}"

# 3. Проверить доступные ресурсы нод
kubectl top nodes

# 4. Проверить taints нод
kubectl describe node <node-name> | grep -A 5 "Taints"
```

**Типичные причины:**

- Недостаточно ресурсов (CPU/память)
- Не выполнены требования `nodeAffinity`/`nodeSelector`
- Taints нод без соответствующих `tolerations`
- Не выполнены правила `podAntiAffinity` (слишком много реплик)

---

## Дополнительная информация

### Производительность планировщика

- **Масштаб:** В больших кластерах (>500 узлов) избегайте широких селекторов в `podAffinity`/`podAntiAffinity` (`matchLabels: {}`) — это замедляет работу scheduler
- **Сложные правила:** Комбинация множества правил (`nodeAffinity` + `podAntiAffinity` + `topologySpreadConstraints`) может привести к увеличению времени планирования
- **Гибкость:** Отдавайте предпочтение мягким правилам (`preferred...`) — жёсткие правила (`required...`) могут сделать систему хрупкой

### Взаимосвязь с другими механизмами

| Механизм | Назначение | SSoT |
|----------|------------|------|
| **Node Affinity** | Притяжение к узлам с метками | [Affinity](../Scheduling/affinity.md) |
| **Pod Affinity/Anti-Affinity** | Притяжение/отталкивание от других подов | [Affinity](../Scheduling/affinity.md) |
| **Taints/Tolerations** | Отталкивание на уровне узлов | [Taints](../Scheduling/taints_and_tolerations.md) |
| **PriorityClass** | Приоритет планирования и вытеснения | [PriorityClass](./priorityclass.md) |
| **Resource Requests/Limits** | Управление ресурсами и QoS | [QoS](../Scheduling/qos_limit_and_requests.md) |
| **TopologySpreadConstraints** | Равномерное распределение | [Affinity](../Scheduling/affinity.md) |

### Лучшие практики

1. **Всегда указывайте `requests`** — без них scheduler не может эффективно распределять поды
2. **Используйте `PriorityClass`** для разделения сред (production/staging/dev)
3. **Комбинируйте механизмы:** `taint` для резервирования узлов + `nodeAffinity` для размещения
4. **Мониторьте Pending-поды** — это индикатор нехватки ресурсов или неправильной конфигурации
5. **Тестируйте сценарии отказа** — проверяйте, как scheduler реагирует на потерю узлов

### Ссылки

- [Официальная документация: kube-scheduler](https://kubernetes.io/docs/reference/command-line-tools-reference/kube-scheduler/)
- [Официальная документация: Планирование подов](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/)
- [Официальная документация: PriorityClass](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/)
