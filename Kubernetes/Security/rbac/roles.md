# Role и ClusterRole

## Определения

**Role** — объект Kubernetes, определяющий набор разрешений в рамках одного [namespace](./rbac_overview.md). Может предоставлять доступ только к namespaced-ресурсам (pods, services, configmaps и т.д.).

**ClusterRole** — объект Kubernetes, определяющий набор разрешений на уровне всего кластера. Может предоставлять доступ к кластерным ресурсам ([nodes](#nodes), persistentvolumes), нересурсным URL (/healthz) или ко всем namespace.

### Предупреждения

- **CVE-2021-25740 (v1.22+):** В новых кластерах доступ на запись к EndpointSlices удалён из агрегируемых ролей `admin`/`edit`
- **Префикс `system:`** — зарезервирован для системных компонентов. Не создавайте роли с этим префиксом

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

### Verbs (глаголы)

| Verb | Описание | Когда использовать |
|------|----------|-------------------|
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
| **Область** | Один namespace | Весь кластер или все namespace |
| **Ресурсы** | Только namespaced | Кластерные + namespaced |
| **Привязка** | [RoleBinding](./bindings.md#rolebinding) | [ClusterRoleBinding](./bindings.md#clusterrolebinding) или [RoleBinding](./bindings.md#rolebinding) |
| **Агрегация** | Нет | Да ([aggregationRule](./aggregation_scenarios.md)) |
| **resourceNames** | Поддерживается | Поддерживается |
| **nonResourceURLs** | Нет | Да (`/healthz`, `/metrics`) |

### Лучшие практики выбора

| Сценарий | Рекомендуемый объект | Обоснование |
|----------|---------------------|-------------|
| Доступ к ресурсам в одном namespace | Role | Изоляция, минимальные привилегии |
| Мониторинг всех namespace (Prometheus) | ClusterRole + RoleBinding | Глобальное чтение с ограниченной привязкой |
| Административные операции | ClusterRole + ClusterRoleBinding | Глобальный доступ для админов |
| Кросс-namespace доступ к Secrets | ClusterRole + RoleBinding per namespace | Контролируемый доступ |
| Доступ к нересурсным URL | ClusterRole | Только ClusterRole поддерживает `nonResourceURLs` |

### Где использовать Role

- Доступ к ресурсам в конкретном namespace
- Изоляция команд/проектов
- Делегирование прав без глобального доступа

### Где использовать ClusterRole

- Доступ к кластерным ресурсам (nodes, persistentvolumes)
- Мониторинг всех namespace (Prometheus)
- Административные операции
- [Агрегируемые роли](./aggregation_scenarios.md)

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
# Чтение секретов во всех namespace (ОПАСНО!)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cross-namespace-secret-reader
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list"]
```

> **Предупреждение:** Предоставление прав на `list`/`watch` Secrets раскрывает содержимое всех секретов. Используйте с осторожностью.

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

ClusterRole поддерживают [динамическую агрегацию](./aggregation_scenarios.md) через `aggregationRule`.

### Встроенные роли

Kubernetes предоставляет встроенные ClusterRole:

- `cluster-admin` — полный доступ
- `admin` — админ в рамках namespace
- `edit` — чтение и запись
- `view` — только чтение

### Лучшие практики

1. **Избегайте wildcard:** Не используйте `resources: ["*"]` и `verbs: ["*"]`
2. **Используйте resourceNames:** Ограничивайте доступ конкретными ресурсами
3. **Принцип наименьших привилегий:** Начинайте с минимальных прав и добавляйте по необходимости
4. **Аудит:** Регулярно проверяйте роли с помощью `kubectl auth can-i --list`

### Связанные темы

- Общий обзор RBAC: [RBAC Overview](./rbac_overview.md)
- Привязки ролей: [RoleBinding и ClusterRoleBinding](./bindings.md)
- Практические сценарии: [Агрегируемые ClusterRole](./aggregation_scenarios.md)
- Ограничения RBAC: [Недостатки RBAC и OPA](./limitations_opa.md)
