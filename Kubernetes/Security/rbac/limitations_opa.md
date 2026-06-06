# Недостатки RBAC и OPA

## Определения

**RBAC (Role-Based Access Control — управление доступом на основе ролей)** — механизм авторизации Kubernetes на основе ролей, предоставляющий только разрешающие (allow) правила без условий.

**ABAC (Attribute-Based Access Control — управление доступом на основе атрибутов)** — модель авторизации, позволяющая принимать решения на основе атрибутов субъекта, ресурса, действия и окружения.

**OPA (Open Policy Agent)** — движок политик общего назначения для реализации сложных сценариев авторизации, включая ABAC.

**OPA Gatekeeper** — реализация OPA для Kubernetes в виде Validating Admission Webhook.

**Kyverno** — альтернатива OPA с политиками в формате YAML (не требует изучения Rego).

## Основные концепции

### Ограничения RBAC

RBAC имеет принципиальные ограничения:

| Ограничение | Описание | Риск | Митигация |
|-------------|----------|------|-----------|
| Нет deny-правил | Только разрешения, нельзя явно запретить | Сложно исключить определённые действия | OPA/Kyverno |
| Нет условий | Нет проверок времени, IP, labels | Невозможен контекстный доступ | OPA/Kyverno |
| Статичность | Правила не адаптируются динамически | Требуется ручное обновление | Агрегация ролей |
| Нет валидации содержимого | Только **CRUD (Create, Read, Update, Delete)** операции | Нельзя проверить spec ресурса | Входные контроллеры |
| Role explosion | Разрастание количества ролей | Сложность управления | Агрегация, именование |
| Нет аудита действий | RBAC не логирует запросы | Сложно отслеживать нарушения | Kubernetes Audit Log |

### Входные контроллеры (Admission Controllers)

Для компенсации ограничений RBAC используются:

| Контроллер | Тип | Назначение |
|------------|-----|------------|
| **OPA Gatekeeper** | Validating Webhook | Политики на Rego |
| **Kyverno** | Validating/Mutating Webhook | Политики в YAML |
| **Pod Security Admission** | Built-in | Встроенные политики безопасности |
| **Resource Quota** | Built-in | Ограничение ресурсов namespace |
| **Limit Ranges** | Built-in | Ограничение ресурсов pod/container |

## Практические сценарии

### Сценарий 1: Запрещающие политики

RBAC не поддерживает `effect: Deny`:

```yaml
# Невозможно написать в RBAC:
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["delete"]
  effect: Deny  # Такого нет в RBAC!
```

Решение через OPA Gatekeeper:

```rego
package kubernetes.admission

# Запретить удаление pods в namespace kube-system
deny[msg] {
    input.request.kind.kind == "Pod"
    input.request.operation == "DELETE"
    input.request.namespace == "kube-system"
    msg := "Deleting pods in kube-system is not allowed"
}
```

Решение через Kyverno:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: deny-delete-kube-system-pods
spec:
  validationFailureAction: Enforce
  rules:
  - name: deny-delete
    match:
      any:
      - resources:
          kinds:
          - Pod
    preconditions:
      all:
      - key: "{{request.operation}}"
        operator: Equals
        value: DELETE
    validate:
      message: "Deleting pods in kube-system is not allowed"
      deny:
        conditions:
          all:
          - key: "{{request.object.metadata.namespace}}"
            operator: Equals
            value: kube-system
```

### Сценарий 2: Условия на основе времени

RBAC не проверяет время суток. OPA позволяет ограничить доступ по времени:

```rego
package kubernetes.admission

# Разрешить создание deployments только в рабочие часы
deny[msg] {
    input.request.kind.kind == "Deployment"
    input.request.operation == "CREATE"
    not is_business_hours
    msg := "Deployments can only be created during business hours (9-18)"
}

is_business_hours {
    [hour, _] := time.clock(time.now_ns())
    hour >= 9
    hour < 18
}
```

### Сценарий 3: Валидация содержимого ресурсов

RBAC контролирует **CRUD (Create, Read, Update, Delete)** операции, но не валидирует spec. OPA проверяет содержимое:

```rego
package kubernetes.admission

# Запретить privileged контейнеры
deny[msg] {
    input.request.kind.kind == "Pod"
    input.request.object.spec.containers[_].securityContext.privileged
    msg := "Privileged containers are not allowed"
}

# Требовать resource limits
deny[msg] {
    input.request.kind.kind == "Pod"
    container := input.request.object.spec.containers[_]
    not container.resources.limits.memory
    msg := sprintf("Container %s must have memory limits", [container.name])
}
```

### Сценарий 4: Проверка по IP-адресу

```rego
package kubernetes.admission

# Разрешить доступ к secrets только из внутренней сети
deny[msg] {
    input.request.kind.kind == "Secret"
    input.request.remoteAddress != "10.0.0.0/8"
    msg := "Access to secrets is only allowed from internal network"
}
```

### Сценарий 5: Многоуровневая авторизация

```rego
package kubernetes.admission

# Разрешить редактирование ConfigMap только владельцу (по label)
allow {
    input.request.kind.kind == "ConfigMap"
    input.request.operation == "UPDATE"
    input.request.object.metadata.labels.owner == input.request.userInfo.username
}

deny[msg] {
    input.request.kind.kind == "ConfigMap"
    input.request.operation == "UPDATE"
    not allow
    msg := "You can only edit ConfigMaps that you own"
}
```

### Сценарий 6: Требование labels для всех ресурсов

```rego
package kubernetes.admission

# Требовать label 'app' для всех Deployments
deny[msg] {
    input.request.kind.kind == "Deployment"
    input.request.operation == "CREATE"
    not input.request.object.metadata.labels.app
    msg := "All Deployments must have 'app' label"
}
```

## Дополнительная информация

### Сравнение RBAC и OPA

| Возможность | RBAC | OPA | Kyverno |
|-------------|------|-----|---------|
| Разрешения CRUD | Да | Да | Да |
| Запрещающие правила | Нет | Да | Да |
| Условия (time, IP) | Нет | Да | Да |
| Проверка содержимого | Нет | Да | Да |
| Мутация ресурсов | Нет | Нет | Да |
| Сложность | Низкая | Высокая (Rego) | Средняя (YAML) |
| Производительность | Высокая | Средняя | Средняя |
| Встроенность | Нативно | Требует установки | Требует установки |

### Когда использовать RBAC

- Базовое разграничение доступа
- Разделение namespace между командами
- Стандартные CRUD-операции
- Простота и производительность важны

### Когда использовать OPA/Kyverno

- Запрещающие политики
- Контекстные условия доступа
- Валидация spec ресурсов
- Соответствие комплаенсу
- Сложные бизнес-правила
- Мутация ресурсов (только Kyverno)

### Выбор между OPA и Kyverno

| Критерий | OPA Gatekeeper | Kyverno |
|----------|----------------|---------|
| Язык политик | Rego (требует обучения) | YAML (знакомый формат) |
| Мутация ресурсов | Нет | Да |
| Сообщество | Большое (**CNCF — Cloud Native Computing Foundation**) | Растущее (CNCF) |
| Интеграции | Широкие | Широкие |
| Сложность | Высокая | Средняя |

> **Рекомендация:** Для простых сценариев выбирайте Kyverno (YAML проще Rego). Для сложных — OPA (более зрелая экосистема).

### Связанные темы

- **[Общий обзор RBAC](./rbac_overview.md)**
- **[Определение ролей (Role и ClusterRole)](./roles.md)**
- **[Привязки ролей (RoleBinding)](./bindings.md)**
