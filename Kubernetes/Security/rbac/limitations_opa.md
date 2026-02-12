# Недостатки RBAC и OPA

## Недостатки RBAC

### 1. Отсутствие deny-правил

RBAC работает только на основе разрешений (allowlist). Нельзя явно запретить действие.

```yaml
# Невозможно написать:
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["delete"]
  effect: Deny  # ❌ Такого нет в RBAC!
```

**Решение:** Использование OPA/Kyverno для запрещающих политик.

### 2. Нет условий (conditions)

Нельзя ограничить доступ на основе:
- Времени суток
- IP-адреса источника
- Значений полей ресурса (labels, annotations)

**Решение:** OPA/Kyverno для политик на основе атрибутов (ABAC).

### 3. Статичность правил

RBAC-политики статичны и не могут динамически адаптироваться к контексту.

### 4. Сложность управления в больших кластерах

- Разрастание количества ролей и привязок
- Сложность аудита эффективных прав
- Риск "role explosion"

### 5. Нет контроля над содержимым ресурсов

RBAC контролирует CRUD-операции, но не валидирует содержимое.

**Решение:** Admission Controllers (OPA Gatekeeper, Kyverno).

## OPA (Open Policy Agent)

**OPA** — это движок политик общего назначения, который позволяет реализовать сложные сценарии авторизации.

### Возможности OPA в Kubernetes

1. **Политики на основе контекста:** IP-адрес, время суток, атрибуты ресурса
2. **Запрещающие политики:** Явный запрет определенных действий
3. **Валидация содержимого:** Проверка spec ресурсов
4. **Многоуровневая авторизация:** Интеграция с внешними системами

### OPA Gatekeeper

OPA Gatekeeper — это специфическая реализация OPA для Kubernetes, работающая как Validating Webhook.

**Пример политики (Rego):**
```rego
package kubernetes.admission

# Запретить privileged контейнеры
deny[msg] {
    input.request.kind.kind == "Pod"
    input.request.object.spec.containers[_].securityContext.privileged
    msg := "Privileged containers are not allowed"
}
```

### Сравнение RBAC и OPA

| Возможность | RBAC | OPA |
|-------------|------|-----|
| **Разрешения CRUD** | ✅ Да | ✅ Да |
| **Запрещающие правила** | ❌ Нет | ✅ Да |
| **Условия (time, IP)** | ❌ Нет | ✅ Да |
| **Проверка содержимого** | ❌ Нет | ✅ Да |
| **Сложность** | Низкая | Высокая |
| **Производительность** | Высокая | Ниже |

## Дополнительная информация

*   [Using RBAC Authorization](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
*   [RBAC Good Practices](https://kubernetes.io/docs/concepts/security/rbac-good-practices/)
*   [OPA Documentation](https://www.openpolicyagent.org/docs/latest/)
*   [OPA Gatekeeper](https://open-policy-agent.github.io/gatekeeper/website/docs/)
