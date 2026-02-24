# Недостатки RBAC и OPA

## Определения

**RBAC (Role-Based Access Control)** — механизм авторизации Kubernetes на основе ролей, предоставляющий только разрешающие (allow) правила без условий.

**ABAC (Attribute-Based Access Control)** — модель авторизации, позволяющая принимать решения на основе атрибутов субъекта, ресурса, действия и окружения.

**OPA (Open Policy Agent)** — движок политик общего назначения для реализации сложных сценариев авторизации, включая ABAC.

**OPA Gatekeeper** — реализация OPA для Kubernetes в виде Validating Admission Webhook.

## Основные концепции

### Ограничения RBAC

RBAC имеет принципиальные ограничения:

| Ограничение | Описание | Риск |
|-------------|----------|------|
| Нет deny-правил | Только разрешения, нельзя явно запретить | Сложно исключить определённые действия |
| Нет условий | Нет проверок времени, IP, labels | Невозможен контекстный доступ |
| Статичность | Правила не адаптируются динамически | Требуется ручное обновление |
| Нет валидации содержимого | Только CRUD-операции | Нельзя проверить spec ресурса |
| Role explosion | Разрастание количества ролей | Сложность управления |

### ABAC через OPA

OPA позволяет реализовать ABAC с проверками:

- Атрибуты субъекта (роль, группа, время суток)
- Атрибуты ресурса (labels, annotations, namespace)
- Атрибуты окружения (IP-адрес, время запроса)
- Атрибуты действия (HTTP метод, API endpoint)

### Решение: Admission Controllers

Для компенсации ограничений RBAC используются:

- **OPA Gatekeeper** — политики на Rego
- **Kyverno** — политики в YAML
- **Pod Security Standards** — встроенные политики безопасности

## Практические сценарии

### Сценарий 1: Запрещающие политики

RBAC не поддерживает `effect: Deny`:

```yaml
# Невозможно написать в RBAC:
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["delete"]
  effect: Deny  # ❌ Такого нет в RBAC!
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

RBAC контролирует CRUD, но не валидирует spec. OPA проверяет содержимое:

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

## Дополнительная информация

### Сравнение RBAC и OPA

| Возможность | RBAC | OPA |
|-------------|------|-----|
| Разрешения CRUD | ✅ | ✅ |
| Запрещающие правила | ❌ | ✅ |
| Условия (time, IP) | ❌ | ✅ |
| Проверка содержимого | ❌ | ✅ |
| Сложность | Низкая | Высокая |
| Производительность | Высокая | Средняя |
| Встроенность | Нативно | Требует установки |

### Когда использовать RBAC

- Базовое разграничение доступа
- Разделение namespace между командами
- Стандартные CRUD-операции
- Простота и производительность важны

### Когда использовать OPA

- Запрещающие политики
- Контекстные условия доступа
- Валидация spec ресурсов
- Соответствие комплаенсу
- Сложные бизнес-правила

### Связанные темы

- Основы RBAC: [RBAC Overview](../rbac/rbac_overview.md)
- Определение ролей: [Role и ClusterRole](../rbac/roles.md)
- Привязки: [RoleBinding и ClusterRoleBinding](../rbac/bindings.md)
- Практические сценарии: [Агрегируемые ClusterRole](../rbac/aggregation_scenarios.md)
- [OPA Documentation](https://www.openpolicyagent.org/docs/latest/)
- [OPA Gatekeeper](https://open-policy-agent.github.io/gatekeeper/website/docs/)
- [Kubernetes RBAC Good Practices](https://kubernetes.io/docs/concepts/security/rbac-good-practices/)
