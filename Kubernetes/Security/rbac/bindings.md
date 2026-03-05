# RoleBinding и ClusterRoleBinding

## Определения

**RoleBinding** — объект Kubernetes, связывающий [Role](./roles.md) или [ClusterRole](./roles.md#clusterrole) с одним или несколькими субъектами в рамках одного namespace. Определяет **кому** и **где** разрешены действия.

**ClusterRoleBinding** — объект Kubernetes, связывающий [ClusterRole](./roles.md#clusterrole) с субъектами на уровне всего кластера. Обеспечивает глобальный доступ независимо от namespace.

### Важные ограничения

- **`roleRef` неизменяем** — для изменения роли необходимо пересоздать binding
- **Нельзя ссылаться на Role из другого namespace** — Role должна существовать в том же namespace, что и RoleBinding

## Основные концепции

### Субъекты (`subjects`)

RoleBinding и ClusterRoleBinding используют поле `subjects` для указания, кому предоставляются права:

| Тип | Описание | Пример |
|-----|----------|--------|
| `User` | Индивидуальный пользователь | `name: "jane@example.com"` |
| `Group` | Группа пользователей | `name: "developers"` |
| `ServiceAccount` | Сервисный аккаунт | `name: "ci-bot"`, `namespace: "dev"` |

> **Важно:** `User` и `Group` не являются объектами Kubernetes. Они создаются и управляются внешними системами аутентификации (OIDC, certificates, webhook).

### ServiceAccount

**ServiceAccount** — объект Kubernetes для идентификации процессов в Pod'ах.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app-sa
  namespace: default
automountServiceAccountToken: false  # Отключить автомонтирование токена
```

> **Best Practice:** Устанавливайте `automountServiceAccountToken: false` по умолчанию и включайте только при необходимости.

### Формат имени ServiceAccount в subjects

```yaml
subjects:
- kind: ServiceAccount
  name: my-sa          # Имя ServiceAccount
  namespace: default   # Namespace обязателен для ServiceAccount
```

### Специальные группы

| Группа | Описание |
|--------|----------|
| `system:authenticated` | Все аутентифицированные пользователи |
| `system:unauthenticated` | Все неаутентифицированные пользователи |
| `system:masters` | Полный доступ (обходит RBAC) — **не добавляйте пользователей!** |
| `system:serviceaccounts` | Все ServiceAccount в кластере |
| `system:serviceaccounts:<ns>` | Все ServiceAccount в namespace |

### Поле `roleRef`

`roleRef` указывает на роль, права которой предоставляются:

- **RoleBinding**: может ссылаться на [Role](./roles.md) в том же namespace или на [ClusterRole](./roles.md#clusterrole) (права будут ограничены namespace привязки)
- **ClusterRoleBinding**: ссылается только на [ClusterRole](./roles.md#clusterrole) с глобальной областью действия

### Сравнение RoleBinding и ClusterRoleBinding

| Характеристика | RoleBinding | ClusterRoleBinding |
|----------------|-------------|-------------------|
| **Область** | Один namespace | Весь кластер |
| **`roleRef`** | [Role](./roles.md) или [ClusterRole](./roles.md#clusterrole) | Только [ClusterRole](./roles.md#clusterrole) |
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

### Лучшие практики

1. **Используйте RoleBinding вместо ClusterRoleBinding** — ограничивайте область действия namespace
2. **Избегайте binding'и к `system:unauthenticated`** — проверяйте и удаляйте лишние
3. **Не добавляйте в `system:masters`** — эта группа обходит RBAC
4. **Аудит binding'ов** — регулярно проверяйте `kubectl get clusterrolebinding,rolebinding --all-namespaces`
5. **ResourceQuota** — применяйте для предотвращения DoS через создание объектов

### Аудит и мониторинг

```bash
# Список всех ClusterRoleBinding
kubectl get clusterrolebinding

# Список всех RoleBinding в namespace
kubectl get rolebinding --namespace default

# Кто имеет доступ к Secrets в namespace
kubectl auth can-i get secrets --namespace default --as=jane

# Проверка binding'и к system:unauthenticated
kubectl get clusterrolebinding -o json | jq '.items[] | select(.subjects[]?.name == "system:unauthenticated")'
```

### Связанные темы

- Общий обзор RBAC: [RBAC Overview](./rbac_overview.md)
- Определение ролей: [Role и ClusterRole](./roles.md)
- Агрегация ролей: [Агрегируемые ClusterRole](./aggregation_scenarios.md)
- Ограничения RBAC: [Недостатки RBAC и OPA](./limitations_opa.md)
