# Агрегируемые ClusterRole и практические сценарии

## Определения

**Агрегация ролей (Role Aggregation)** — механизм Kubernetes для динамического объединения правил из нескольких [ClusterRole](../rbac/roles.md#clusterrole) в одну агрегирующую роль. Контроллер автоматически обновляет агрегированную роль при изменении совпадающих ролей.

**Агрегируемая ClusterRole** — роль с полем `aggregationRule`, содержащим селекторы для автоматического сбора правил.

## Основные концепции

### Механизм работы

1. Создаётся агрегирующая ClusterRole с `aggregationRule`
2. Контроллер находит все ClusterRole, соответствующие селекторам
3. Правила из найденных ролей автоматически добавляются в агрегирующую роль
4. При изменении совпадающих ролей агрегирующая роль обновляется

### Синтаксис aggregationRule

```yaml
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:          # Селектор по меткам
      rbac.myorg.io/aggregate-to-team-developer: "true"
  - matchExpressions:     # Селектор по выражениям
    - key: rbac.example.io/scope
      operator: In
      values: ["global", "team"]
```

### Преимущества агрегации

- **Модульность**: разные команды/компоненты определяют свои права
- **Автоматическое обновление**: изменения в исходных ролях отражаются в агрегированной
- **Расширяемость**: легко добавлять новые права без изменения основной роли

## Практические сценарии

### Сценарий 1: Агрегация для команд

```yaml
# Агрегирующая роль для команды разработчиков
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: team-developer
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:
      rbac.myorg.io/aggregate-to-team-developer: "true"
rules: [] # Правила будут добавлены автоматически
---
# Права на просмотр pods (добавляет команда A)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: pod-viewer
  labels:
    rbac.myorg.io/aggregate-to-team-developer: "true"
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log"]
  verbs: ["get", "list", "watch"]
---
# Права на управление deployments (добавляет команда B)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: deployment-manager
  labels:
    rbac.myorg.io/aggregate-to-team-developer: "true"
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "watch", "create", "update", "delete"]
```

### Сценарий 2: Принцип минимальных привилегий

```yaml
# ПЛОХО: избыточные права
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: overly-permissive
rules:
- apiGroups: ["*"]
  resources: ["*"]
  verbs: ["*"]

# ХОРОШО: минимально необходимые права
---
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

### Сценарий 3: Изоляция по namespace

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

### Сценарий 4: Использование ClusterRole в конкретном namespace

```yaml
# ClusterRole для просмотра секретов (определена глобально)
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

### Сценарий 5: Регулярный аудит RBAC

```bash
# Проверка, может ли текущий пользователь создавать Deployments
kubectl auth can-i create deployments --namespace default

# Проверка от имени другого пользователя
kubectl auth can-i list secrets --namespace dev --as jane

# Проверка от имени ServiceAccount
kubectl auth can-i list nodes --as=system:serviceaccount:observability:prometheus

# Список всех разрешений текущего пользователя
kubectl auth can-i --list
```

## Дополнительная информация

### Ограничения агрегации

- Агрегация работает только с [ClusterRole](../rbac/roles.md#clusterrole)
- [Role](../rbac/roles.md) не поддерживают `aggregationRule`
- Циклические ссылки не допускаются

### Связанные темы

- Основы RBAC: [RBAC Overview](../rbac/rbac_overview.md)
- Определение ролей: [Role и ClusterRole](../rbac/roles.md)
- Привязки ролей: [RoleBinding и ClusterRoleBinding](../rbac/bindings.md)
- Ограничения RBAC: [Недостатки RBAC и OPA](../rbac/limitations_opa.md)
- [Kubernetes RBAC Documentation](https://kubernetes.io/docs/reference/access-authn-authz/rbac/#aggregated-clusterroles)
