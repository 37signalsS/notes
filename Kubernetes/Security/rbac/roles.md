# Роли (Role) и кластерные роли (ClusterRole)

## Определения

<a name="role"></a>

- **Role** — объект, определяющий набор разрешений в рамках одного [пространства имён (namespace)](./rbac_overview.md). Предоставляет доступ только к ресурсам, ограниченным пространством имён (pods, services, configmaps).
<a name="clusterrole"></a>
- **ClusterRole** — объект, определяющий набор разрешений на уровне всего кластера. Предоставляет доступ к кластерным ресурсам (nodes, persistentvolumes), нересурсным URL или ко всем пространствам имён одновременно.

Подробное описание архитектуры **RBAC (Role-Based Access Control — управление доступом на основе ролей)** приведено в файле **[Обзор RBAC](./rbac_overview.md)**.

### Предупреждения

- **Безопасность объектов:** использование префикса `system:` зарезервировано для системных компонентов. См. раздел **[Предупреждения безопасности](./rbac_overview.md#preduprezhdeniya-bezopasnosti)**.
- **CVE (Common Vulnerabilities and Exposures — общеизвестные уязвимости и экспозиции) 2021-25740 (v1.22+):** В новых кластерах доступ на запись к `EndpointSlices` удалён из агрегируемых ролей `admin`/`edit`. Подробности и способы восстановления описаны в разделе **[Агрегируемые ClusterRole](./aggregation_scenarios.md#cve-2021-25740)**.

## Основные концепции

### Структура правил (rules)

Каждая роль содержит список правил, определяющих разрешённые действия:

| Поле | Описание | Пример |
|------|----------|--------|
| `apiGroups` | API-группы ресурсов | `""` (core), `"apps"`, `"rbac.authorization.k8s.io"` |
| `resources` | Типы ресурсов | `pods`, `deployments`, `configmaps` |
| `verbs` | Действия (глаголы) | `get`, `list`, `watch`, `create`, `update`, `delete` |
| `resourceNames` | Ограничение по именам | `["my-config"]` — доступ только к конкретному ресурсу |
| `nonResourceURLs` | Нересурсные пути | `/healthz`, `/metrics` |

### Глаголы (Verbs)

| Глагол (Verb) | Описание | Когда использовать |
|---------------|----------|-------------------|
| `get` | Получение одного ресурса по имени | Чтение конкретного объекта |
| `list` | Получение списка ресурсов | Перечисление объектов |
| `watch` | Отслеживание изменений ресурсов | Для контроллеров и операторов |
| `create` | Создание нового ресурса | Развёртывание приложений |
| `update` | Обновление существующего ресурса | Изменение конфигурации |
| `patch` | Частичное обновление | Точечные изменения |
| `delete` | Удаление ресурса | Очистка, масштабирование вниз |
| `deletecollection` | Удаление нескольких ресурсов | Массовое удаление |
| `bind` | Привязка роли к субъекту | Только для администраторов RBAC |
| `escalate` | Создание роли с большими правами | Только для системных администраторов |
| `impersonate` | Действие от имени другого пользователя | Только для отладки |

### Сравнение Role и ClusterRole

| Критерий | Role | ClusterRole |
|----------|------|-------------|
| **Область действия** | Один namespace | Весь кластер или все namespace |
| **Ресурсы** | Только ресурсы в namespace | Кластерные + ресурсы в namespace |
| **Привязка** | [RoleBinding](./bindings.md) | [ClusterRoleBinding](./bindings.md) или [RoleBinding](./bindings.md) |
| **Агрегация** | Нет | Да ([aggregationRule](./aggregation_scenarios.md)) |
| **resourceNames** | Поддерживается | Поддерживается |
| **nonResourceURLs** | Нет | Да (`/healthz`, `/metrics`) |

> **Ловушка:** путают область действия. Role + RoleBinding работают только в **одном namespace**. ClusterRole + ClusterRoleBinding — на **весь кластер** (nodes, PV, namespaces). ClusterRole, привязанная через RoleBinding, даёт права только в namespace этой привязки. Role, привязанная через ClusterRoleBinding, **невозможна** — ClusterRoleBinding требует ClusterRole.

### Рекомендации по выбору

| Сценарий | Рекомендуемый объект | Обоснование |
|----------|---------------------|-------------|
| Доступ к ресурсам в одном namespace | Role | Изоляция, минимальные привилегии |
| Мониторинг всех namespace (Prometheus) | ClusterRole + RoleBinding | Глобальное чтение с ограниченной привязкой |
| Административные операции | ClusterRole + ClusterRoleBinding | Глобальный доступ для админов |
| Кросс-namespace доступ к Secrets | ClusterRole + RoleBinding в каждом NS | Контролируемый доступ |
| Доступ к нересурсным URL | ClusterRole | Только ClusterRole поддерживает `nonResourceURLs` |

## Практические сценарии

### Примеры манифестов Role

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

### Примеры манифестов ClusterRole

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
# Доступ к нересурсным URL
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: health-checker
rules:
- nonResourceURLs: ["/healthz", "/readyz"]
  verbs: ["get"]
```

### Привязка ClusterRole к конкретному namespace

Для предоставления разрешений, определенных в ClusterRole, только в рамках одного namespace, используется RoleBinding.

```yaml
# 1. ClusterRole для чтения секретов (создается один раз)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: secret-viewer
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
---
# 2. RoleBinding в конкретном namespace
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

<a name="vstroennye-roli"></a>

### Встроенные роли

Kubernetes предоставляет стандартные ClusterRole для типичных задач:

- `cluster-admin` — полный доступ к кластеру.
- `admin` — административные права в рамках namespace (за исключением квот).
- `edit` — чтение и запись объектов в namespace.
- `view` — доступ только на чтение (исключая Secrets).

### Лучшие практики

1. **Избегайте использования подстановочных знаков (`*`):** Не используйте неограниченные права для ресурсов и глаголов.
2. **Используйте `resourceNames`:** Ограничивайте доступ конкретными экземплярами ресурсов.
3. **Принцип наименьших привилегий:** Предоставляйте только тот минимум прав, который необходим для работы.
4. **Агрегация:** Для расширения стандартных ролей используйте [aggregationRule](./aggregation_scenarios.md).

### Связанные темы

- **[Общий обзор RBAC](./rbac_overview.md)**
- **[Привязки ролей (RoleBinding)](./bindings.md)**
- **[Агрегируемые ClusterRole](./aggregation_scenarios.md)**
