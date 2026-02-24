# Role и ClusterRole

## Определения

**Role** — объект Kubernetes, определяющий набор разрешений в рамках одного [namespace](../rbac/rbac_overview.md). Может предоставлять доступ только к namespaced-ресурсам (pods, services, configmaps и т.д.).

**ClusterRole** — объект Kubernetes, определяющий набор разрешений на уровне всего кластера. Может предоставлять доступ к кластерным ресурсам ([nodes](roles.md#nodes), persistentvolumes), нересурсным URL (/healthz) или ко всем namespace.

## Основные концепции

### Структура правил (`rules`)

Каждая роль содержит список правил, определяющих разрешённые действия:

| Поле | Описание | Пример |
|------|----------|--------|
| `apiGroups` | API-группы ресурсов | `""` (core), `"apps"`, `"rbac.authorization.k8s.io"` |
| `resources` | Типы ресурсов | `pods`, `deployments`, `configmaps` |
| `verbs` | Действия | `get`, `list`, `watch`, `create`, `update`, `delete` |
| `resourceNames` | Ограничение по именам | `["my-config"]` — доступ только к конкретному ресурсу |
| `nonResourceURLs` | Нересурсные пути | `/healthz`, `/metrics` |

### Сравнение Role и ClusterRole

| Критерий | Role | ClusterRole |
|----------|------|-------------|
| **Область** | Один namespace | Весь кластер или все namespace |
| **Ресурсы** | Только namespaced | Кластерные + namespaced |
| **Привязка** | [RoleBinding](../rbac/bindings.md#rolebinding) | [ClusterRoleBinding](../rbac/bindings.md#clusterrolebinding) или [RoleBinding](../rbac/bindings.md#rolebinding) |
| **Агрегация** | Нет | Да ([aggregationRule](../rbac/aggregation_scenarios.md)) |

### Где использовать Role

- Доступ к ресурсам в конкретном namespace
- Изоляция команд/проектов
- Делегирование прав без глобального доступа

### Где использовать ClusterRole

- Доступ к кластерным ресурсам (nodes, persistentvolumes)
- Мониторинг всех namespace (Prometheus)
- Административные операции
- [Агрегируемые роли](../rbac/aggregation_scenarios.md)

## Практические сценарии

### Примеры Role

```yaml
# Чтение pods и services в namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-service-reader
  namespace: production
rules:
- apiGroups: [""]
  resources: ["pods", "services"]
  verbs: ["get", "list", "watch"]
```

```yaml
# Управление deployments в namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: deployment-manager
  namespace: development
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "watch", "create", "update", "delete"]
```

### Примеры ClusterRole

```yaml
# Глобальное чтение нод
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-reader
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "watch"]
```

```yaml
# Чтение секретов во всех namespace (опасно!)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cross-namespace-secret-reader
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list"]
```

```yaml
# Доступ к нересурсным URL
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: health-checker
rules:
- nonResourceURLs: ["/healthz", "/readyz"]
  verbs: ["get"]
```

### Привязка ClusterRole к namespace

```yaml
# ClusterRole для чтения секретов
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: secret-viewer
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
---
# Даем группе 'devs' права на просмотр секретов только в namespace 'staging'
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: view-secrets-in-staging
  namespace: staging
subjects:
- kind: Group
  name: devs
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: secret-viewer
  apiGroup: rbac.authorization.k8s.io
```

## Дополнительная информация

### Агрегируемые ClusterRole

ClusterRole поддерживают [динамическую агрегацию](../rbac/aggregation_scenarios.md) через `aggregationRule`.

### Встроенные роли

Kubernetes предоставляет встроенные ClusterRole:

- `cluster-admin` — полный доступ
- `admin` — админ в рамках namespace
- `edit` — чтение и запись
- `view` — только чтение

### Связанные темы

- Общий обзор RBAC: [RBAC Overview](../rbac/rbac_overview.md)
- Привязки ролей: [RoleBinding и ClusterRoleBinding](../rbac/bindings.md)
- Практические сценарии: [Агрегируемые ClusterRole](../rbac/aggregation_scenarios.md)
- Ограничения RBAC: [Недостатки RBAC и OPA](../rbac/limitations_opa.md)
