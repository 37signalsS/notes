# Роли (Role) и кластерные роли (ClusterRole)

## Определения

- **Role** — объект, определяющий набор разрешений в рамках одного [пространства имён (namespace)](./rbac_overview.md). Предоставляет доступ только к ресурсам, ограниченным пространством имён (pods, services, configmaps).

- **ClusterRole** — объект, определяющий набор разрешений на уровне всего кластера. Предоставляет доступ к кластерным ресурсам (nodes, persistentvolumes), нересурсным URL или ко всем пространствам имён одновременно.

Подробное описание архитектуры **RBAC (Role-Based Access Control — управление доступом на основе ролей)** приведено в файле **[Обзор RBAC](./rbac_overview.md)**.

### Предупреждения

- **Безопасность объектов:** использование префикса `system:` зарезервировано для системных компонентов. См. раздел **[Предупреждения безопасности](./rbac_overview.md)**.
- **Группа `system:masters`:** Членство в этой группе дает неограниченный доступ в обход RBAC. Избегайте добавления пользователей в эту группу.
- **Pod Security Admission (PSA):** Начиная с v1.25 (после удаления PodSecurityPolicy), для контроля безопасности подов используются метки на уровне Namespace, а не RBAC-глагол `use`. См. раздел **[Pod Security Context](../pod_security_context.md)**.
- **CVE-2021-25740 (историческая справка):** В кластерах до v1.22 доступ на запись к `EndpointSlices` был в агрегируемых ролях `admin`/`edit`. В новых версиях это исправлено. Подробности: **[Агрегируемые ClusterRole](./aggregation_scenarios.md#cve-2021-25740)**.

## Основные концепции

### Структура правил (rules)

Каждая роль содержит список правил, определяющих разрешённые действия:

| Поле | Описание | Пример |
|------|----------|--------|
| `apiGroups` | API-группы ресурсов | `""` (core), `"apps"`, `"rbac.authorization.k8s.io"` |
| `resources` | Типы ресурсов | `pods`, `deployments`, `configmaps` |
| `verbs` | Действия (глаголы) | `get`, `list`, `watch`, `create`, `update`, `delete` |
| `resourceNames` | Ограничение по именам | `["my-config"]` — доступ только к конкретному ресурсу. **Внимание:** не работает с глаголом `create`. |
| `nonResourceURLs` | Нересурсные пути | `/healthz`, `/metrics` (только для ClusterRole) |

### Глаголы (Verbs)

| Глагол (Verb) | Описание | Риски и особенности |
|---------------|----------|-------------------|
| `get` | Чтение одного ресурса по имени | Базовый доступ. |
| `list` | Список ресурсов | **Риск:** `list` секретов позволяет увидеть содержимое всех секретов в namespace. |
| `watch` | Отслеживание изменений | Используется контроллерами. |
| `create` | Создание нового ресурса | Несовместим с `resourceNames`. |
| `update` | Полное обновление ресурса | Заменяет существующий объект. |
| `patch` | Частичное обновление | Рекомендуется для точечных изменений. |
| `delete` | Удаление ресурса | Возможность прерывания работы сервиса. |
| `deletecollection` | Массовое удаление | **Высокий риск:** удаление всех объектов типа в namespace. |
| `bind` | Привязка роли к субъекту | **Критический риск:** позволяет пользователю выдать права самому себе. |
| `escalate` | Повышение прав роли | **Критический риск:** редактирование ролей для добавления прав, которых нет у пользователя. |
| `impersonate` | Действие от имени другого | **Критический риск:** обход ограничений через привилегированную учётку. |
| `use` | Использование ресурса | **Устарело:** ранее использовалось для PodSecurityPolicy (удалено в 1.25+). |

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

## Проверка прав (Verification)

Для отладки RBAC и проверки разрешений без смены контекста используются встроенные средства `kubectl`.

### Проверка своих прав
```bash
# Список всех разрешений в текущем namespace
kubectl auth can-i --list

# Проверка возможности конкретного действия
kubectl auth can-i create deployments
```

### Проверка прав другого субъекта
Требуются права администратора кластера.
```bash
# Проверка прав ServiceAccount в namespace
kubectl auth can-i list secrets \
  --as=system:serviceaccount:production:my-app-sa \
  -n production

# Проверка прав конкретного пользователя
kubectl auth can-i get nodes --as=johndoe
```

## Дополнительная информация

### Встроенные роли

Kubernetes предоставляет стандартные ClusterRole для типичных задач:

- `cluster-admin` — полный доступ к кластеру.
- `admin` — административные права в рамках namespace (за исключением квот).
- `edit` — чтение и запись объектов в namespace.
- `view` — доступ только на чтение (исключая Secrets).

### Лучшие практики

1. **Принцип наименьших привилегий (PoLP):** Предоставляйте только тот минимум прав, который необходим для работы.
2. **Избегайте подстановочных знаков (`*`):** Явно указывайте ресурсы и глаголы. `*` в `apiGroups` или `resources` затрудняет аудит.
3. **Ограничивайте `list` для Secrets:** Глагол `list` на ресурсе `secrets` позволяет получить данные всех секретов сразу. Используйте `get` + `resourceNames`.
4. **Не используйте группу `system:masters`:** Пользователи в этой группе обходят все проверки RBAC. Это "черный ход", который невозможно заблокировать политиками.
5. **Используйте `resourceNames`:** Где возможно, ограничивайте доступ конкретными экземплярами (например, доступ только к одному `ConfigMap`).
6. **Аудит и сканирование:** Регулярно проверяйте права инструментами вроде `rakkess` или `kubescape` для обнаружения избыточных привилегий.
7. **Агрегация:** Для расширения стандартных ролей используйте [aggregationRule](./aggregation_scenarios.md).

### Связанные темы

- **[Общий обзор RBAC](./rbac_overview.md)**
- **[Привязки ролей (RoleBinding)](./bindings.md)**
- **[Агрегируемые ClusterRole](./aggregation_scenarios.md)**
