# Role-Based Access Control (RBAC) в Kubernetes

## Определения

**RBAC (Role-Based Access Control)** — механизм авторизации Kubernetes для гранулярного управления доступом субъектов (пользователей, групп, [ServiceAccount](roles.md#serviceaccount)) к ресурсам кластера через декларативные правила.

Ключевые сущности:

- **Субъект** — кто запрашивает доступ: `User`, `Group`, [ServiceAccount](roles.md#serviceaccount)
- **Роль** — набор разрешений: [Role](roles.md#role), [ClusterRole](roles.md#clusterrole)
- **Привязка** — связь субъекта с ролью: [RoleBinding](bindings.md), [ClusterRoleBinding](bindings.md)

## Основные концепции

### Модель разрешений

RBAC опирается на три вопроса:

- **Что разрешено?** — определяется в [Role](roles.md) и [ClusterRole](roles.md#clusterrole)
- **Кому разрешено?** — определяется в поле `subjects` [привязок](bindings.md)
- **Где разрешено?** — определяется уровнем привязки ([RoleBinding](bindings.md#rolebinding) или [ClusterRoleBinding](bindings.md#clusterrolebinding))

### Основные объекты RBAC

| Объект | Уровень | Назначение |
|--------|---------|------------|
| [Role](roles.md) | Namespace | Права на namespaced-ресурсы в одном namespace |
| [ClusterRole](roles.md#clusterrole) | Кластер | Права на кластерные ресурсы или все namespace |
| [RoleBinding](bindings.md) | Namespace | Привязка роли к субъекту в одном namespace |
| [ClusterRoleBinding](bindings.md#clusterrolebinding) | Кластер | Глобальная привязка ClusterRole к субъекту |

### Принцип аддитивности

Права в RBAC **аддитивны**: итоговые возможности субъекта — это объединение всех разрешений из всех привязок. Отсутствие права означает запрет.

## Практические сценарии

### Проверка прав доступа

```bash
# Проверка прав текущего пользователя
kubectl auth can-i create deployments --namespace default

# Проверка от имени другого пользователя
kubectl auth can-i list secrets --namespace dev --as jane

# Проверка от имени ServiceAccount
kubectl auth can-i list nodes --as=system:serviceaccount:observability:prometheus
```

### Минимальные привилегии

```yaml
# ПЛОХО: избыточные права
rules:
- apiGroups: ["*"]
  resources: ["*"]
  verbs: ["*"]

# ХОРОШО: минимально необходимые права
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
  namespace: default
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
```

### Изоляция по namespace

```yaml
# Доступ только к deployments в namespace 'development'
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: development
  name: deployment-manager
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "watch", "create", "update", "delete"]
---
# Привязка роли к группе разработчиков
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: devs-deployment-access
  namespace: development
subjects:
- kind: Group
  name: developers
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: deployment-manager
  apiGroup: rbac.authorization.k8s.io
```

## Дополнительная информация

### Ограничения RBAC

RBAC имеет принципиальные [ограничения](limitations_opa.md):

- Нет запрещающих правил (deny)
- Нет условий (time, IP)
- Статичность правил
- Нет валидации содержимого ресурсов

Для расширенных сценариев используйте [OPA/Kyverno](limitations_opa.md).

### Агрегация ролей

Для динамического объединения прав используйте [агрегируемые ClusterRole](aggregation_scenarios.md).

### Ссылки

- Подробнее о ролях: [Role и ClusterRole](roles.md)
- Подробнее о привязках: [RoleBinding и ClusterRoleBinding](bindings.md)
- Практические сценарии агрегации: [Агрегируемые ClusterRole](aggregation_scenarios.md)
- Ограничения и альтернативы: [Недостатки RBAC и OPA](limitations_opa.md)
- [Kubernetes RBAC Documentation](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
