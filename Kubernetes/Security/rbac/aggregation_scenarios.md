# Агрегируемые ClusterRole

## Определения

**Агрегация ролей (Role Aggregation)** — механизм Kubernetes для динамического объединения правил из нескольких [ClusterRole](./roles.md#clusterrole) в одну агрегирующую роль. Контроллер автоматически обновляет агрегирующую роль при изменении совпадающих ролей.

**Агрегируемая ClusterRole** — роль с полем `aggregationRule`, содержащим селекторы для автоматического сбора правил.

## Основные концепции

### Механизм работы

1. Создаётся агрегирующая ClusterRole с `aggregationRule`
2. Контроллер находит все ClusterRole, соответствующие селекторам
3. Правила из найденных ролей автоматически добавляются в агрегирующую роль
4. При изменении совпадающих ролей агрегирующая роль обновляется

> **Важно:** Агрегация работает только с ClusterRole. [Role](./roles.md#role) не поддерживают `aggregationRule`.

### Синтаксис aggregationRule

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aggregated-role
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:          # Селектор по меткам
      rbac.example.io/aggregate-to-role: "true"
  - matchExpressions:     # Селектор по выражениям
    - key: rbac.example.io/scope
      operator: In
      values: ["global", "team"]
rules: []  # Правила будут добавлены автоматически
```

### Лейблы для агрегации во встроенные роли

Kubernetes предоставляет встроенные ClusterRole (`admin`, `edit`, `view`), в которые можно добавлять права через лейблы:

| Лейбл | Агрегирует в |
|-------|--------------|
| `rbac.authorization.k8s.io/aggregate-to-admin` | ClusterRole `admin` |
| `rbac.authorization.k8s.io/aggregate-to-edit` | ClusterRole `edit` |
| `rbac.authorization.k8s.io/aggregate-to-view` | ClusterRole `view` |

### Преимущества агрегации

- **Модульность**: разные команды/компоненты определяют свои права
- **Автоматическое обновление**: изменения в исходных ролях отражаются в агрегированной
- **Расширяемость**: легко добавлять новые права без изменения основной роли
- **Decentralization**: команды управляют своими правами независимо

### Ограничения

- Агрегация работает только с [ClusterRole](./roles.md#clusterrole)
- [Role](./roles.md#role) не поддерживают `aggregationRule`
- Циклические ссылки не допускаются
- Агрегированные правила добавляются в конец списка `rules`

## Практические сценарии

### Сценарий 1: Агрегация для команды разработчиков

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

**Результат:** ClusterRole `team-developer` автоматически получит правила из `pod-viewer` и `deployment-manager`.

### Сценарий 2: Расширение встроенной роли edit

```yaml
# Добавляем право на перезапуск deployments во встроенную роль edit
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: custom:aggregate-to-edit:restart-deployments
  labels:
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["patch"]  # Для kubectl rollout restart
---
# Добавляем право на выполнение exec в pods
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: custom:aggregate-to-edit:exec
  labels:
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
rules:
- apiGroups: [""]
  resources: ["pods/exec"]
  verbs: ["create"]
```

**Результат:** Все пользователи с ролью `edit` получат дополнительные права.

### Сценарий 3: Модульная роль для мониторинга

```yaml
# Базовая агрегирующая роль для мониторинга
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: monitoring
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:
      rbac.myorg.io/aggregate-to-monitoring: "true"
rules: []
---
# Права для Prometheus (добавляет платформа)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: monitoring:prometheus
  labels:
    rbac.myorg.io/aggregate-to-monitoring: "true"
rules:
- apiGroups: [""]
  resources: ["nodes", "nodes/metrics", "services", "endpoints", "pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get"]
- nonResourceURLs: ["/metrics"]
  verbs: ["get"]
---
# Права для Grafana (добавляет платформа)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: monitoring:grafana
  labels:
    rbac.myorg.io/aggregate-to-monitoring: "true"
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get", "list"]
- apiGroups: [""]
  resources: ["services", "endpoints"]
  verbs: ["get", "list"]
```

### Сценарий 4: Агрегация по условиям (matchExpressions)

```yaml
# Агрегирующая роль с селектором по выражениям
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: team-global
aggregationRule:
  clusterRoleSelectors:
  - matchExpressions:
    - key: rbac.example.io/scope
      operator: In
      values: ["global", "team"]
    - key: rbac.example.io/team
      operator: Exists
rules: []
---
# Роль будет включена (оба условия выполнены)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: team-a-global
  labels:
    rbac.example.io/scope: "global"
    rbac.example.io/team: "team-a"
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list"]
---
# Роль НЕ будет включена (scope=local)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: team-a-local
  labels:
    rbac.example.io/scope: "local"
    rbac.example.io/team: "team-a"
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get"]
```

### Сценарий 5: Восстановление записи к Endpoints (CVE-2021-25740)

Начиная с Kubernetes v1.22, доступ на запись к EndpointSlices удалён из ролей `admin`/`edit` для новых кластеров. Если требуется восстановить:

```yaml
# Восстановление доступа на запись к Endpoints для роли edit
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: custom:aggregate-to-edit:endpoints
  labels:
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
rules:
- apiGroups: [""]
  resources: ["endpoints"]
  verbs: ["create", "delete", "patch", "update"]
```

> **Предупреждение:** Восстанавливайте только если приложения зависят от записи в Endpoints.

## Дополнительная информация

### Проверка агрегированных правил

```bash
# Просмотр агрегированных правил ClusterRole
kubectl get clusterrole team-developer -o yaml

# Проверка, какие ClusterRole участвуют в агрегации
kubectl get clusterrole -l rbac.myorg.io/aggregate-to-team-developer=true

# Список всех ClusterRole с лейблами агрегации
kubectl get clusterrole -l rbac.authorization.k8s.io/aggregate-to-edit
```

### Auto-reconciliation

По умолчанию API server восстанавливает дефолтные роли при каждом запуске. Для отключения:

```yaml
metadata:
  annotations:
    rbac.authorization.kubernetes.io/autoupdate: "false"
```

> **Внимание:** Отключение может привести к неработоспособности кластера при отсутствии дефолтных разрешений.

### Связанные темы

- Основы RBAC: [RBAC Overview](./rbac_overview.md)
- Определение ролей: [Role и ClusterRole](./roles.md)
- Привязки ролей: [RoleBinding и ClusterRoleBinding](./bindings.md)
- Ограничения RBAC: [Недостатки RBAC и OPA](./limitations_opa.md)
- [Kubernetes RBAC: Aggregated ClusterRoles](https://kubernetes.io/docs/reference/access-authn-authz/rbac/#aggregated-clusterroles)
