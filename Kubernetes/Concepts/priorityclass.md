# PriorityClass — приоритеты подов

## Определения

**PriorityClass** — это ресурс Kubernetes, который позволяет назначать приоритет подам. PriorityClass влияет на порядок планирования подов и определяет, какие поды будут удалены первыми при нехватке ресурсов (при вытеснении подов). Это важный механизм для обеспечения доступности нагрузок (workloads) в условиях дефицита ресурсов кластера.

## Основные концепции

`PriorityClass` влияет на два ключевых аспекта жизненного цикла пода:

1. **Порядок планирования (Scheduling Order)**: Когда несколько подов находятся в состоянии `Pending`, планировщик (`kube-scheduler`) будет в первую очередь пытаться разместить поды с более высоким приоритетом.
2. **Вытеснение (Preemption)**: Если для пода с высоким приоритетом нет места в кластере (не хватает CPU (Central Processing Unit) или памяти), планировщик может принудительно удалить (`evict`) один или несколько подов с более низким приоритетом с подходящего узла, чтобы освободить ресурсы.

### Структура PriorityClass

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-priority
value: 1000
globalDefault: false
description: "High priority for production workloads"
```

### Поля конфигурации

- **`value`**: Числовое значение приоритета. Чем выше значение, тем выше приоритет.
  - Пользовательские классы: Рекомендуется использовать значения до 1,000,000,000.
  - Системные классы: Занимают диапазон выше 2,000,000,000 для защиты критически важных компонентов кластера.
- **`globalDefault`**: Если `true`, этот `PriorityClass` будет автоматически присвоен всем подам, у которых `priorityClassName` не указан. Если такого класса нет, поды по умолчанию получают приоритет `0`. В кластере может быть только один `PriorityClass` с `globalDefault: true`.
- **`description`**: Человекочитаемое описание.
- **`preemptionPolicy`**: Определяет, могут ли поды с этим классом вытеснять другие поды.
  - `PreemptLowerPriority` (по умолчанию): Поды могут вытеснять поды с более низким приоритетом.
  - `Never`: Поды с этим классом не будут вытеснять другие. Они будут размещены только при наличии свободных ресурсов.

### Встроенные PriorityClass

Kubernetes по умолчанию создает два `PriorityClass` для защиты своих системных компонентов:

- `system-cluster-critical`: Используется для самых важных компонентов, таких как `etcd`, `kube-apiserver`.
- `system-node-critical`: Используется для компонентов, критичных для работы узла, например, CNI (Container Network Interface) плагина.

Эти классы имеют очень высокие значения (`value > 2,000,000,000`), что гарантирует, что системные поды никогда не будут вытеснены рабочими нагрузками.

### Использование

Для присвоения поду приоритета используется поле `priorityClassName` в спецификации (`spec`) пода:

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

## Практические сценарии

### 1. Создание иерархии приоритетов для различных сред

В большинстве кластеров сосуществуют разные типы рабочих нагрузок: системные компоненты, продуктивные приложения, тестовые среды. `PriorityClass` позволяет выстроить иерархию, гарантирующую работу наиболее важных сервисов при дефиците ресурсов.

#### Шаг 1: Определение набора PriorityClass

Создадим три уровня приоритета:

- **`high-priority`**: Для важных компонентов кластера. Примеры: Ingress-контроллер, реестр Docker Registry, динамический provisioner для хранилищ (например, NFS (Network File System)).
- **`medium-priority`**: Для основных продуктивных приложений.
- **`low-priority`**: Для тестовых сред или фоновых задач.

Поды без указания `priorityClassName` получат приоритет `0`, что делает их первыми кандидатами на вытеснение.

#### Шаг 2: Манифесты PriorityClass

```yaml
# priority-classes.yaml

# Высокий приоритет для аддонов кластера
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-priority
value: 1000000
globalDefault: false
description: "Приоритет для критически важных компонентов кластера (ingress, registry, etc)."

---
# Средний приоритет для production-приложений
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: medium-priority
value: 500000
globalDefault: false
description: "Приоритет для production-приложений."

---
# Низкий приоритет для тестовых сред
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: low-priority
value: 100000
globalDefault: false
description: "Приоритет для staging, dev и других некритичных приложений."
```

#### Шаг 3: Применение к подам

При создании `Deployment` или `StatefulSet` указывается соответствующий класс:

**Deployment Ingress-контроллера (высокий приоритет):**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-ingress-controller
spec:
  template:
    spec:
      priorityClassName: high-priority
      ...
```

### 2. Сценарий: Вытеснение для обеспечения работы Production

Пример разделения сред `staging` и `production` в одном кластере.

**Задача**: Гарантировать запуск продуктивных приложений при нехватке ресурсов.

**Результат:**
- Если в кластере не хватает ресурсов для высокоприоритетного пода, `kube-scheduler` инициирует вытеснение.
- Он находит узел с подами более низкого приоритета и удаляет их (`evict`), освобождая ресурсы.
- Продуктивное приложение запускается, а вытесненные поды переходят в состояние `Pending` до появления ресурсов.

## Дополнительная информация

**Важные особенности:**

- `PriorityClass` является кластерным ресурсом (cluster-scoped).
- Если у пода не указан класс и нет `globalDefault`, приоритет равен `0`.
- При указании несуществующего класса под будет отклонён **API (Application Programming Interface)** сервером.
- Жизненным циклом `PriorityClass` нужно управлять вручную (удаление подов не удаляет класс).

**Рекомендации (Best practices):**

- Используйте значения до `1,000,000,000` для пользовательских классов.
- Достаточно 3–5 уровней приоритетов.
- Избегайте `globalDefault: true` без явной необходимости.
- Используйте `preemptionPolicy: Never`, если под должен ждать ресурсы, а не вытеснять другие.

**См. также:**
- [Планировщик kube-scheduler](./kube_scheduler.md)
- [Квоты ресурсов ResourceQuota](../Scheduling/qos_limit_and_requests.md)
- [Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md)
