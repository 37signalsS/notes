# Агрегируемые кластерные роли (ClusterRole)

## Определения

**Агрегация ролей (Role Aggregation)** — механизм в **RBAC (Role-Based Access Control — управление доступом на основе ролей)** Kubernetes для динамического объединения правил из нескольких [ClusterRole](./roles.md#clusterrole) в одну агрегирующую роль. Контроллер автоматически обновляет агрегирующую роль при изменении входящих в неё ролей.

**Агрегируемая ClusterRole** — роль, содержащая поле `aggregationRule` с селекторами для автоматического сбора правил из других ролей.

## Основные концепции

### Механизм работы

1. Создаётся агрегирующая ClusterRole с заполненным полем `aggregationRule`.
2. Контроллер RBAC находит все ClusterRole, соответствующие указанным селекторам.
3. Правила из найденных ролей автоматически добавляются в список `rules` агрегирующей роли.
4. При любом изменении (создании, удалении, модификации) соответствующих ролей агрегирующая роль обновляется автоматически.

> **Важно:** Агрегация поддерживается только для ClusterRole. Обычные [роли (Role)](./roles.md#role) не поддерживают `aggregationRule`.

### Синтаксис aggregationRule

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aggregated-role
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:          # Селектор по меткам (labels)
      rbac.example.io/aggregate-to-role: "true"
  - matchExpressions:     # Селектор по выражениям
    - key: rbac.example.io/scope
      operator: In
      values: ["global", "team"]
rules: []  # Правила будут добавлены контроллером автоматически
```

### Метки (labels) для агрегации во встроенные роли

Kubernetes предоставляет стандартные встроенные ClusterRole (`admin`, `edit`, `view`), которые можно расширять, добавляя свои роли с соответствующими метками:

| Метка (Label) | Агрегирует в |
|---------------|--------------|
| `rbac.authorization.k8s.io/aggregate-to-admin` | ClusterRole `admin` |
| `rbac.authorization.k8s.io/aggregate-to-edit` | ClusterRole `edit` |
| `rbac.authorization.k8s.io/aggregate-to-view` | ClusterRole `view` |

### Преимущества агрегации

- **Модульность**: разные компоненты или команды могут определять свои специфические права независимо.
- **Автоматическое обновление**: любые изменения в исходных ролях мгновенно отражаются в агрегированной роли.
- **Расширяемость**: возможность дополнять стандартные роли Kubernetes без их прямого редактирования.
- **Децентрализация**: команды могут самостоятельно управлять правами, необходимыми для их сервисов.

### Ограничения

- Механизм работает только для объектов [ClusterRole](./roles.md#clusterrole).
- [Role](./roles.md#role) не поддерживают поле `aggregationRule`.
- Запрещены циклические ссылки между ролями.
- Агрегированные правила всегда добавляются в конец общего списка `rules`.

## Практические сценарии

### Сценарий 1: Агрегация прав для команды разработчиков

В данном примере создается общая роль для разработчиков, которая автоматически собирает права на просмотр подов и управление развертываниями (deployments).

```yaml
# 1. Агрегирующая роль
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: team-developer
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:
      rbac.myorg.io/aggregate-to-team-developer: "true"
rules: []
---
# 2. Права на просмотр подов (добавляет команда инфраструктуры)
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
# 3. Права на управление развертываниями (добавляет команда CI/CD)
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

**Результат:** ClusterRole `team-developer` автоматически объединит права из обеих ролей.

### Сценарий 2: Расширение стандартной роли edit

Добавление специфических прав (например, на выполнение команд в подах) всем пользователям, обладающим встроенной ролью `edit`.

```yaml
# Добавление права на выполнение exec в подах
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

### Сценарий 3: Модульная роль для мониторинга

Создание роли `monitoring`, которая собирает необходимые разрешения от разных компонентов системы (Prometheus, Grafana).

```yaml
# Базовая агрегирующая роль
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: monitoring
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:
      rbac.myorg.io/aggregate-to-monitoring: "true"
rules: []
```

### Сценарий 4: Агрегация по условиям (matchExpressions)

Более гибкая настройка селекторов для выбора ролей на основе сложных условий.

```yaml
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
```

<a name="cve-2021-25740"></a>

### Сценарий 5: Восстановление записи в Endpoints (CVE-2021-25740)

Начиная с Kubernetes v1.22, доступ на запись к `EndpointSlices` удалён из ролей `admin`/`edit` по умолчанию. Если вашим приложениям требуется это право:

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

> **Предупреждение:** Восстанавливайте эти права только в случае явной необходимости, так как это снижает общий уровень безопасности кластера.

## Дополнительная информация

### Проверка агрегированных правил

```bash
# Просмотр итогового списка правил ClusterRole
kubectl get clusterrole team-developer -o yaml

# Список ролей, участвующих в агрегации для конкретного селектора
kubectl get clusterrole -l rbac.myorg.io/aggregate-to-team-developer=true

# Список всех ролей, расширяющих встроенную роль edit
kubectl get clusterrole -l rbac.authorization.k8s.io/aggregate-to-edit
```

### Автоматическое согласование (Auto-reconciliation)

По умолчанию API-сервер восстанавливает значения стандартных ролей при каждом перезапуске. Чтобы внести изменения в системные роли вручную и предотвратить их перезапись, используется аннотация:

```yaml
metadata:
  annotations:
    rbac.authorization.kubernetes.io/autoupdate: "false"
```

> **Внимание:** Отключение автоматического обновления может привести к критическим ошибкам в работе кластера при обновлении версии Kubernetes, если новые обязательные права не будут добавлены вручную.

### Связанные темы

- **[Обзор RBAC](./rbac_overview.md)** — общая архитектура управления доступом.
- **[Определение ролей (Role и ClusterRole)](./roles.md)** — детальное описание базовых объектов.
- **[Привязки ролей (RoleBinding)](./bindings.md)** — механизмы назначения прав субъектам.
