# Политики Kyverno: Расширенные возможности

## Определения

**Переменные Kyverno** — механизм подстановки значений из контекста запроса в правила политики.

**Foreach** — конструкция для итерации по массивам элементов (контейнеры, volumes, initContainers) в рамках одного правила.

> **Основное руководство:** Операторы условий описаны в [Типы правил](../rules.md). Практические примеры политик — в [Практические сценарии](./practical_scenarios.md).

---

## Basic Concepts

### Переменные в политиках

Kyverno поддерживает подстановку переменных из контекста запроса:

| Переменная | Описание |
|------------|----------|
| `{{request.object.metadata.name}}` | Имя ресурса |
| `{{request.object.metadata.namespace}}` | Namespace ресурса |
| `{{request.userInfo.username}}` | Имя пользователя |
| `{{@}}` | Ссылка на текущий элемент в foreach |
| `{{element}}` | Альтернативный синтаксис для текущего элемента |

### Синтаксис переменных

```yaml
# Прямая подстановка
message: "Container {{ element.name }} must have limits"

# С фильтрацией
key: "{{ request.object.spec.containers[0].image }}"

# С оператором JMESPath
key: "{{ request.object.spec.containers[].image | length(@) }}"
```

---

## Practical Scenarios

### Пример с foreach

Итерация по всем контейнерам в Pod:

```yaml
rules:
  - name: require-readonly-rootfs
    match:
      resources:
        kinds:
          - Pod
    validate:
      message: "Root filesystem must be read-only"
      foreach:
        - list: "request.object.spec.containers"
          deny:
            conditions:
              - key: "{{ element.securityContext.readOnlyRootFilesystem }}"
                operator: NotEqual
                value: true
```

### foreach с несколькими условиями

```yaml
rules:
  - name: require-limits-for-all-containers
    match:
      resources:
        kinds:
          - Pod
    validate:
      message: "All containers must have CPU and memory limits"
      foreach:
        - list: "request.object.spec.containers"
          deny:
            conditions:
              any:
                - key: "{{ element.resources.limits.cpu }}"
                  operator: Equal
                  value: ""
                - key: "{{ element.resources.limits.memory }}"
                  operator: Equal
                  value: ""
```

### Валидация initContainers и containers

```yaml
rules:
  - name: no-privileged-containers
    match:
      resources:
        kinds:
          - Pod
    validate:
      message: "Privileged containers are forbidden"
      foreach:
        - list: "request.object.spec.containers"
          deny:
            conditions:
              - key: "{{ element.securityContext.privileged }}"
                operator: Equal
                value: true
        - list: "request.object.spec.initContainers"
          deny:
            conditions:
              - key: "{{ element.securityContext.privileged }}"
                operator: Equal
                value: true
```

---

## Additional Information

### Важные замечания

1. **Background scan не применяет политики к существующим ресурсам** — политика срабатывает только при CREATE/UPDATE ([подробнее](../background.md))
2. Политики с `validationFailureAction: Enforce` блокируют несоответствующие ресурсы
3. Kyverno проверяет итоговый Pod, сгенерированный из Deployment/StatefulSet/DaemonSet
4. Операторы условий подробно описаны в [Типы правил](../rules.md)

### JMESPath в переменных

Kyverno поддерживает функции JMESPath для обработки данных:

| Функция | Описание | Пример |
|---------|----------|--------|
| `length(@)` | Количество элементов | `{{ request.object.spec.containers[] | length(@) }}` |
| `contains()` | Проверка вхождения | `{{ contains(request.object.metadata.labels, 'app') }}` |
| `join()` | Объединение массива | `{{ join(', ', request.object.spec.containers[].name) }}` |
| `sort()` | Сортировка | `{{ sort(request.object.spec.containers[].name) }}` |

### Связанные темы

- [Типы правил](../rules.md) — операторы условий, типы правил
- [Практические сценарии](./practical_scenarios.md) — примеры политик
- [Определения и концепции](./definitions_and_concepts.md) — базовая структура политик
- [Background Scans](../background.md) — фоновое сканирование
- [Отчеты](../reports.md) — мониторинг применения политик
