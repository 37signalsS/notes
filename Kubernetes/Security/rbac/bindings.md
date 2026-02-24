# RoleBinding и ClusterRoleBinding

## Определения

**RoleBinding** — объект Kubernetes, связывающий [Role](../rbac/roles.md) или [ClusterRole](../rbac/roles.md#clusterrole) с одним или несколькими субъектами в рамках одного namespace. Определяет **кому** и **где** разрешены действия.

**ClusterRoleBinding** — объект Kubernetes, связывающий [ClusterRole](../rbac/roles.md#clusterrole) с субъектами на уровне всего кластера. Обеспечивает глобальный доступ независимо от namespace.

## Основные концепции

### Субъекты (`subjects`)

RoleBinding и ClusterRoleBinding используют поле `subjects` для указания, кому предоставляются права:

| Тип | Описание | Пример |
|-----|----------|--------|
| `User` | Индивидуальный пользователь | `name: "jane@example.com"` |
| `Group` | Группа пользователей | `name: "developers"` |
| `ServiceAccount` | Сервисный аккаунт | `name: "ci-bot"`, `namespace: "dev"` |

> **Важно:** `User` и `Group` не являются объектами Kubernetes. Они создаются и управляются внешними системами аутентификации (OIDC, certificates, webhook).

### Поле `roleRef`

`roleRef` указывает на роль, права которой предоставляются:

- **RoleBinding**: может ссылаться на [Role](../rbac/roles.md) в том же namespace или на [ClusterRole](../rbac/roles.md#clusterrole) (права будут ограничены namespace привязки)
- **ClusterRoleBinding**: ссылается только на [ClusterRole](../rbac/roles.md#clusterrole) с глобальной областью действия

### Сравнение RoleBinding и ClusterRoleBinding

| Характеристика | RoleBinding | ClusterRoleBinding |
|----------------|-------------|-------------------|
| **Область** | Один namespace | Весь кластер |
| **`roleRef`** | [Role](../rbac/roles.md) или [ClusterRole](../rbac/roles.md#clusterrole) | Только [ClusterRole](../rbac/roles.md#clusterrole) |
| **Субъекты** | User, Group, ServiceAccount | User, Group, ServiceAccount |
| **Сценарии** | Команда/проект | Администраторы, системные сервисы |

## Практические сценарии

### RoleBinding с Role

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
  namespace: default
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: read-pods
  namespace: default
subjects:
- kind: User
  name: jane
  apiGroup: rbac.authorization.k8s.io
- kind: ServiceAccount
  name: monitoring
  namespace: default
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

### RoleBinding с ClusterRole

```yaml
# ClusterRole для чтения секретов (определена глобально)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: secret-reader
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list"]
---
# Привязка ClusterRole к группе только в namespace 'staging'
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: read-secrets-in-staging
  namespace: staging
subjects:
- kind: Group
  name: developers
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: secret-reader
  apiGroup: rbac.authorization.k8s.io
```

### ClusterRoleBinding

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-admin
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["*"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: admin-nodes
subjects:
- kind: Group
  name: cluster-admins
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: node-admin
  apiGroup: rbac.authorization.k8s.io
```

### ServiceAccount без автомонтирования токена

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: no-api-access-sa
automountServiceAccountToken: false
```

## Дополнительная информация

### Встроенные привязки

Kubernetes создаёт встроенные ClusterRoleBinding:

- `cluster-admin` → группа `system:masters`

### Множественные привязки

Один субъект может иметь несколько привязок к разным ролям. Права аддитивны.

### Связанные темы

- Общий обзор RBAC: [RBAC Overview](../rbac/rbac_overview.md)
- Определение ролей: [Role и ClusterRole](../rbac/roles.md)
- Агрегация ролей: [Агрегируемые ClusterRole](../rbac/aggregation_scenarios.md)
- Ограничения RBAC: [Недостатки RBAC и OPA](../rbac/limitations_opa.md)
