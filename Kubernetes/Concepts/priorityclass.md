# PriorityClass

## Определения

**PriorityClass** — это ресурс Kubernetes, который позволяет назначать приоритет подам. PriorityClass влияет на порядок планирования подов и определяет, какие поды будут удалены первыми при нехватке ресурсов (при вытеснении подов). Это критически важный механизм для обеспечения доступности критически важных workloads в условиях нехватки ресурсов кластера.

## Основные концепции

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

- **value**: Числовое значение приоритета (от -100000000 до 1000000000). Чем выше значение, тем выше приоритет. Системные priority classes (например, `system-cluster-critical`) имеют значения выше 10 000 000.
- **globalDefault**: Если установлено в `true`, этот PriorityClass будет использоваться по умолчанию для всех подов без явного указания `priorityClassName`. Только один PriorityClass может иметь `globalDefault: true`.
- **description**: Описание назначения данного priority class.

### Встроенные PriorityClasses

Kubernetes предоставляет несколько встроенных PriorityClasses:

- `system-cluster-critical` (значение 2000000000): Для критически важных системных компонентов кластера.
- `system-node-critical` (значение 2000001000): Для компонентов, критичных для работы узлов.

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

### Создание кастомных PriorityClasses

Рекомендуется создавать набор кастомных PriorityClasses для различных типов приложений:

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: low-priority
value: 100
globalDefault: false
description: "Low priority for batch jobs"
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: medium-priority
value: 500
globalDefault: false
description: "Medium priority for standard workloads"
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-priority
value: 1000
globalDefault: false
description: "High priority for critical services"
```

### Сценарии использования

1. **Критические сервисы**: Приложения, которые должны быть всегда доступны (например, frontend веб-приложения).
2. **Фоновые задачи**: менее важные workloads, которые могут быть вытеснены при нехватке ресурсов.
3. **Dev/Staging среды**: Низкий приоритет для тестовых окружений, чтобы production нагрузки вытесняли их при необходимости.

## Дополнительная информация

- PriorityClasses являются кластерными ресурсами (Cluster-wide), а не namespace-scoped.
- При отсутствии у пода указанного `priorityClassName`, под получает значение приоритета 0.
- Если указанный PriorityClass не существует, под не будет запланирован.
- PriorityClasses не удаляются автоматически — необходимо вручную управлять их жизненным циклом.
