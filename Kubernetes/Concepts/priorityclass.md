# PriorityClass

## Определения

**PriorityClass** — это ресурс Kubernetes, который позволяет назначать приоритет подам. PriorityClass влияет на порядок планирования подов и определяет, какие поды будут удалены первыми при нехватке ресурсов (при вытеснении подов). Это критически важный механизм для обеспечения доступности критически важных workloads в условиях нехватки ресурсов кластера.

## Основные концепции

`PriorityClass` влияет на два ключевых аспекта жизненного цикла пода:

1. **Порядок планирования (Scheduling Order)**: Когда несколько подов находятся в состоянии `Pending`, планировщик (`kube-scheduler`) будет в первую очередь пытаться разместить поды с более высоким приоритетом.
2. **Вытеснение (Preemption)**: Если для пода с высоким приоритетом нет места в кластере (не хватает CPU/памяти), планировщик может принудительно удалить (`evict`) один или несколько подов с более низким приоритетом с подходящего узла, чтобы освободить ресурсы.

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

### Поля

- **`value`**: Числовое значение приоритета. Чем выше значение, тем выше приоритет.
  - Пользовательские классы: Рекомендуется использовать значения до 1,000,000,000.
  - Системные классы: Занимают диапазон выше 2,000,000,000 для защиты критически важных компонентов кластера.
- **`globalDefault`**: Если `true`, этот `PriorityClass` будет автоматически присвоен всем подам, у которых `priorityClassName` не указан. Если такого класса нет, поды по умолчанию получают приоритет `0`. В кластере может быть только один `PriorityClass` с `globalDefault: true`.
- **`description`**: Человекочитаемое описание.
- **`preemptionPolicy`**: Определяет, могут ли поды с этим классом вытеснять другие поды.
  - `PreemptLowerPriority` (по умолчанию): Поды могут вытеснять поды с более низким приоритетом.
  - `Never`: Поды с этим классом не будут вытеснять другие. Они будут размещены только при наличии свободных ресурсов.

### Встроенные PriorityClasses

Kubernetes по умолчанию создает два `PriorityClass` для защиты своих системных компонентов:

- `system-cluster-critical`: Используется для самых важных компонентов, таких как `etcd`, `kube-apiserver`.
- `system-node-critical`: Используется для компонентов, критичных для работы узла, например, CNI-плагина.

Эти классы имеют очень высокие значения (`value > 2,000,000,000`), что гарантирует, что системные поды никогда не будут вытеснены рабочими нагрузками.

### Использование

Для присвоения пода приоритета используется поле `priorityClassName` в спецификации пода:

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

В большинстве кластеров сосуществуют разные типы рабочих нагрузок: критически важные системные компоненты, production-приложения, staging-среды и тестовые задачи. `PriorityClass` позволяет выстроить иерархию, гарантирующую, что наиболее важные сервисы будут работать даже при дефиците ресурсов.

#### Шаг 1: Определение набора `PriorityClass`

Создадим три уровня приоритета:

- **`high-priority`**: Для критически важных, но не системных компонентов, от которых зависит работа всего кластера. Примеры:
  - Ingress-контроллер
  - Приватный Docker Registry
  - Динамический provisioner для хранилищ (например, `nfs-subdir-external-provisioner`)
- **`medium-priority`**: Для основных production-приложений.
- **`low-priority`**: Для staging, dev-сред или фоновых задач.

Поды без указания `priorityClassName` получат приоритет `0`, что делает их первыми кандидатами на вытеснение.

#### Шаг 2: Манифесты `PriorityClass`

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

Теперь при создании `Deployment` или `StatefulSet` для каждого типа нагрузки указывается соответствующий класс:

**Deployment Ingress-контроллера (высокий приоритет):**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-ingress-controller
spec:
  template:
    spec:
      priorityClassName: high-priority # <---
      ...
```

**Deployment production-приложения (средний приоритет):**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-production-app
spec:
  template:
    spec:
      priorityClassName: medium-priority # <---
      ...
```

### 2. Сценарий: Вытеснение для обеспечения работы Production

Это классический пример использования `PriorityClass` для разделения сред `staging` и `production` в одном кластере.

**Задача**: Гарантировать, что production-приложения всегда будут запущены, даже если для них не хватает ресурсов из-за запущенных staging-приложений.

**Шаги:**

1. **Создаем два `PriorityClass`**: `medium-priority` с высоким значением и `low-priority` с низким.
2. **Разворачиваем staging-приложение** с `priorityClassName: low-priority`, которое занимает большую часть ресурсов узла.
3. **Разворачиваем production-приложение** с `priorityClassName: medium-priority` и большими запросами по ресурсам (`requests`).

**Результат:**

- Так как в кластере не хватает ресурсов для prod-приложения, `kube-scheduler` инициирует вытеснение.
- Он находит узел, где работает staging-приложение, и удаляет его, так как его приоритет ниже.
- Освободившиеся ресурсы используются для запуска production-приложения.
- Под staging-приложения переходит в состояние `Pending` до тех пор, пока в кластере не появятся свободные ресурсы.

Этот механизм позволяет гарантировать доступность критически важных сервисов за счет менее важных.

## Дополнительная информация

- `PriorityClass` является кластерным ресурсом (Cluster-wide), а не namespaced-scoped.
- Если у пода не указан `priorityClassName` и нет `globalDefault` класса, под получает приоритет `0`.
- Если указанный в поде `PriorityClass` не существует, под будет отклонен.
- `PriorityClass` не удаляются автоматически при удалении использующих их подов — их жизненным циклом нужно управлять вручную.
