# PriorityClass — приоритеты подов

## Определения

**PriorityClass** — это ресурс Kubernetes, который позволяет назначать приоритет подам. PriorityClass влияет на два ключевых аспекта: порядок планирования (Scheduling Order) и механизм вытеснения (Preemption). Это критически важный механизм для обеспечения доступности высокоприоритетных нагрузок (workloads) в условиях дефицита ресурсов кластера.

## Основные концепции

`PriorityClass` влияет на два этапа жизненного цикла пода:

1.  **Порядок планирования (Scheduling Order)**: Когда несколько подов находятся в состоянии `Pending`, планировщик (`kube-scheduler`) сортирует их по значению приоритета. Поды с более высоким приоритетом рассматриваются первыми для размещения на узлах.
2.  **Вытеснение (Preemption)**: Если для пода с высоким приоритетом нет места в кластере (не хватает CPU или памяти), планировщик может принудительно удалить (`evict`) один или несколько подов с более низким приоритетом с подходящего узла, чтобы освободить ресурсы для более важной задачи.

### Структура манифеста

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-priority
value: 1000000
globalDefault: false
preemptionPolicy: PreemptLowerPriority
description: "High priority for production workloads"
```

### Поля конфигурации

*   **`value`**: Числовое значение приоритета. Чем выше значение, тем выше приоритет.
    *   Пользовательские классы: Рекомендуется использовать значения до 1,000,000,000.
    *   Системные классы: Занимают диапазон выше 2,000,000,000 для защиты критически важных компонентов кластера.
*   **`globalDefault`**: Если `true`, этот `PriorityClass` будет автоматически присвоен всем подам, у которых `priorityClassName` не указан. Если такого класса нет, поды по умолчанию получают приоритет `0`. В кластере может быть только один `PriorityClass` с `globalDefault: true`.
*   **`preemptionPolicy`**: Определяет поведение при нехватке ресурсов.
    *   `PreemptLowerPriority` (по умолчанию): Поды могут вытеснять поды с более низким приоритетом.
    *   `Never`: Поды с этим классом будут помещены в начало очереди планирования, но не будут вытеснять другие поды. Они будут ждать появления свободных ресурсов.
*   **`description`**: Человекочитаемое описание назначения данного класса.

### Встроенные PriorityClass

Kubernetes автоматически создает два `PriorityClass` для защиты своих системных компонентов:

*   **`system-cluster-critical`**: Используется для самых важных компонентов, критичных для работы всего кластера (например, `etcd`, `kube-apiserver`, `kube-scheduler`).
*   **`system-node-critical`**: Используется для компонентов, критичных для работы конкретного узла (например, `kubelet`, CNI-плагины, драйверы хранилищ).

Эти классы имеют значения `value > 2,000,000,000`, что гарантирует, что системные поды никогда не будут вытеснены рабочими нагрузками пользователей.

### Использование в поде

Для присвоения приоритета поду используется поле `priorityClassName` в спецификации (`spec`) пода:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app
spec:
  priorityClassName: high-priority
  containers:
  - name: my-app
    image: my-image
```

## Алгоритм выбора жертв (Victim Selection)

При инициировании вытеснения планировщик старается минимизировать ущерб для кластера, выбирая подов-жертв по следующим правилам:
1.  Сначала выбираются поды с самым низким приоритетом.
2.  Среди подов с одинаковым приоритетом первыми вытесняются те, у которых ниже QoS-класс (`BestEffort` -> `Burstable` -> `Guaranteed`).
3.  Планировщик учитывает **Pod Disruption Budget (PDB)**. Он постарается не выбирать поды, удаление которых нарушит PDB, если есть другие подходящие кандидаты.
4.  Выбираются поды, работающие наименьшее количество времени.

## Ограничение использования через ResourceQuota

Поскольку высокий приоритет позволяет удалять другие поды, в мультитенантных средах необходимо ограничивать доступ к мощным `PriorityClass`. Это делается через `scopeSelector`:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: limit-high-priority
  namespace: development
spec:
  hard:
    pods: "0" # Запрет на использование high-priority в этом namespace
  scopeSelector:
    matchExpressions:
    - scopeName: PriorityClass
      operator: In
      values: ["high-priority"]
```

## Отличие от Kubelet Eviction

Важно различать **Preemption** (планировщик) и **Eviction** (kubelet), так как они работают по разным правилам:

| Характеристика | Preemption (Планировщик) | Eviction (Kubelet) |
| :--- | :--- | :--- |
| **Причина** | Нет места для нового пода с высоким приоритетом. | Узел исчерпал ресурсы (Memory, Disk, PID). |
| **Что учитывается** | `PriorityClass` (поле `value`). | QoS Class (`Guaranteed`, `Burstable`, `BestEffort`). |
| **Цель** | Разместить новый под. | Сохранить стабильность работы узла. |
| **Учет PDB** | Планировщик старается не нарушать PDB. | Kubelet игнорирует PDB (стабильность узла выше). |

## Практические сценарии

### 1. Создание иерархии приоритетов для различных сред

#### Шаг 1: Определение набора PriorityClass
Создадим три уровня приоритета для типичного кластера:
*   **`high-priority`**: Для аддонов кластера (Ingress, Metrics Server).
*   **`medium-priority`**: Для продуктивных приложений.
*   **`low-priority`**: Для тестовых сред и фоновых задач.

#### Шаг 2: Манифесты PriorityClass
```yaml
# Высокий приоритет для аддонов
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-priority
value: 1000000
description: "Приоритет для критически важных аддонов (ingress, registry)."

---
# Средний приоритет для Prod
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: medium-priority
value: 500000
description: "Приоритет для продуктивных нагрузок."

---
# Низкий приоритет для Dev
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: low-priority
value: 100000
description: "Приоритет для некритичных сред."
```

#### Шаг 3: Применение к Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: production-api
spec:
  template:
    spec:
      priorityClassName: medium-priority
      ...
```

### 2. Сценарий: Пакетная обработка (Batch Jobs) без вытеснения
**Задача**: Запустить расчетную задачу, которая должна быть первой в очереди, когда освободится место (например, ночью), но она не должна "убивать" работающий Staging днем.

**Решение**:
```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: batch-priority
value: 800000
preemptionPolicy: Never
description: "Высокий приоритет в очереди, но без вытеснения других подов."
```

## Дополнительная информация

**Важные особенности:**
*   `PriorityClass` является кластерным ресурсом (`cluster-scoped`).
*   Если у пода не указан класс и нет `globalDefault`, приоритет равен `0`.
*   При указании несуществующего класса под будет отклонён **API-сервером**.
*   Удаление `PriorityClass` не влияет на уже запущенные поды, но новые поды с этим именем создать не удастся.

**Рекомендации (Best practices):**
*   Достаточно 3–5 уровней приоритетов для большинства организаций.
*   Избегайте `globalDefault: true` без явной необходимости.
*   Используйте `preemptionPolicy: Never` для ресурсоемких Batch-задач.
*   Всегда комбинируйте PriorityClass с **ResourceQuotas**, чтобы избежать злоупотреблений.

**См. также:**
*   [Планировщик kube-scheduler](./kube_scheduler.md)
*   [Квоты ресурсов ResourceQuota](../Scheduling/qos_limit_and_requests.md)
*   [Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md)
*   [QoS классы в Kubernetes](../Scheduling/qos_limit_and_requests.md)
