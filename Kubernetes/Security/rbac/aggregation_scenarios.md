# Агрегируемые ClusterRole и практические сценарии

## Агрегируемые ClusterRole

Агрегация позволяет объединять правила из нескольких `ClusterRole` в одну. Контроллер автоматически обновляет агрегированную роль.

**Пример агрегирующей роли:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: team-developer
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:
      rbac.myorg.io/aggregate-to-team-developer: "true"
rules: [] # Правила будут добавлены автоматически
```

## Практические сценарии

### 1. Принцип минимальных привилегий

```yaml
# ПЛОХО: избыточные права
rules:
- apiGroups: ["*"]
  resources: ["*"]
  verbs: ["*"]

# ХОРОШО: минимально необходимые права
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: pod-reader
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
```

### 2. Изоляция по Namespace

```yaml
# Доступ только к Deployments в namespace 'development'
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: development
  name: deployment-manager
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "watch", "create", "update", "delete"]
```

### 3. Использование ClusterRole в конкретном Namespace

```yaml
# ClusterRole для просмотра секретов
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

### 4. Ограничение ServiceAccount

```yaml
# ServiceAccount без автоматического монтирования токена
apiVersion: v1
kind: ServiceAccount
metadata:
  name: no-api-access-sa
automountServiceAccountToken: false
```

### 5. Регулярный аудит RBAC

```bash
# Проверка, может ли текущий пользователь создавать Deployments
kubectl auth can-i create deployments --namespace default

# Проверка от имени другого пользователя
kubectl auth can-i list secrets --namespace dev --as jane

# Проверка от имени ServiceAccount
kubectl auth can-i list nodes --as=system:serviceaccount:observability:prometheus
```
