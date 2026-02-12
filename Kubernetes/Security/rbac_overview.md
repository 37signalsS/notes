# Role-Based Access Control (RBAC) в Kubernetes

## Определения

**RBAC (Role-Based Access Control)** — это механизм авторизации в Kubernetes, который позволяет гранулярно управлять доступом пользователей, групп и сервисных аккаунтов к ресурсам кластера.

В Kubernetes модель RBAC опирается на описание разрешённых действий в виде объектов `Role` и `ClusterRole`. Эти объекты определяют, какие операции (`verbs`) над какими ресурсами (`resources`) допустимы. Применяются эти права к субъектам (`User`, `Group`, `ServiceAccount`) через объекты-связки `RoleBinding` и `ClusterRoleBinding`.

- **Роли (`Role`, `ClusterRole`)** отвечают на вопрос «что разрешено?».
- **Привязки (`RoleBinding`, `ClusterRoleBinding`)** отвечают на вопросы «кому разрешено?» и «где разрешено?».

### Назначение RBAC

*   **Реализация принципа наименьших привилегий (Principle of Least Privilege)**: субъекты получают только те права, которые им необходимы для выполнения задач.
*   **Разделение обязанностей**: команды и приложения изолированы друг от друга.
*   **Соответствие требованиям безопасности** и комплаенса.
*   **Предотвращение несанкционированного доступа** к ресурсам кластера и эскалации привилегий.

## Основные концепции

### Основные объекты RBAC

*   `Role`
*   `ClusterRole`
*   `RoleBinding`
*   `ClusterRoleBinding`
*   `User`, `Group`, `ServiceAccount` (субъекты)

Права в RBAC являются **аддитивными**: итоговые возможности субъекта — это объединение всех разрешений из всех привязок, которые на него действуют. Явного механизма запрета (`deny`) в стандартном RBAC нет.

### Role и ClusterRole

`Role` и `ClusterRole` содержат правила (`rules`), которые представляют собой набор разрешений.

*   **Role**: представляет собой набор прав в пределах конкретного **пространства имен (`namespace`)**. Не может предоставлять доступ к кластерным ресурсам (например, `nodes`).
*   **ClusterRole**: является **кластерным объектом** (не принадлежит `namespace`) и может использоваться для предоставления прав на:
    *   Кластерные ресурсы (`nodes`, `persistentvolumes`).
    *   Ресурсы во всех `namespace` (например, `pods` в масштабе всего кластера).
    *   Нересурсные URL (например, `/healthz`).

#### Структура правил (`rules`)
Каждая роль содержит список правил, где указываются:
*   `apiGroups`: список API-групп (`""` для core API).
*   `resources`: типы ресурсов (`pods`, `configmaps`, `nodes` и т.д.). Можно использовать `*`.
*   `verbs`: действия (`get`, `list`, `watch`, `create`, `update`, `patch`, `delete`). Также существуют специфичные, например `deletecollection`, `escalate`, `bind`, `approve`. Можно использовать `*`.
*   `resourceNames`: ограничение правил на конкретные имена ресурсов.
*   `nonResourceURLs`: доступ к не-ресурсным HTTP путям API-сервера.

> **Примечание:** Ограничение `resourceNames` не применимо к операциям `list` и `watch`, так как они возвращают списки объектов.

#### Сравнение Role и ClusterRole

| Критерий | Role | ClusterRole |
| :--- | :--- | :--- |
| **Область действия** | Один `namespace` | Весь кластер |
| **Ресурсы** | Только `namespaced` ресурсы | Кластерные и `namespaced` ресурсы |
| **Привязка** | `RoleBinding` в том же `namespace` | `ClusterRoleBinding` (на весь кластер) или `RoleBinding` (на конкретный `namespace`) |
| **Агрегация** | Нет | Есть (`aggregationRule`) |

### RoleBinding и ClusterRoleBinding

`RoleBinding` и `ClusterRoleBinding` используются для привязки ролей к субъектам.

*   **RoleBinding**: назначает права в пределах **одного `namespace`**. Может ссылаться как на `Role` (в том же `namespace`), так и на `ClusterRole` (в этом случае права из `ClusterRole` будут действовать только в `namespace`, где создан `RoleBinding`).
*   **ClusterRoleBinding**: назначает права на **весь кластер**. Ссылается только на `ClusterRole`.

#### Субъекты (`subjects`)
В качестве субъектов могут выступать:
- `User`: `kind: User, name: "jane"`
- `Group`: `kind: Group, name: "developers"`
- `ServiceAccount`: `kind: ServiceAccount, name: "ci-bot", namespace: "dev"`

> **Важно:** `User` и `Group` не являются объектами Kubernetes. Они приходят из внешних систем аутентификации (сертификаты, токены). `ServiceAccount` — это объект Kubernetes.

#### Сравнение RoleBinding и ClusterRoleBinding

| Характеристика | RoleBinding | ClusterRoleBinding |
| :--- | :--- | :--- |
| **Область действия** | Один `namespace` | Весь кластер |
| **`roleRef`** | `Role` (локальная) или `ClusterRole` | Только `ClusterRole` |
| **`namespace` у ресурса** | Обязателен | Отсутствует (кластерный ресурс) |
| **`ServiceAccount` subject** | Если `namespace` не указан, используется `namespace` самого `RoleBinding`. | `namespace` в `subject` обязателен. |
| **Типовые сценарии**| Делегирование ролей в пределах команды/проекта | Глобальные роли для администраторов, контроллеров, системных компонентов. |

### Агрегируемые ClusterRole

Агрегация позволяет объединять правила из нескольких `ClusterRole` в одну. Контроллер автоматически обновляет агрегированную роль, добавляя в нее правила из ролей, отмеченных специальной меткой (`label`). Это удобно для расширения стандартных ролей (`admin`, `edit`, `view`).

**Пример агрегирующей роли:**
Она находит все `ClusterRole` с меткой `rbac.myorg.io/aggregate-to-team-developer: "true"` и объединяет их правила.

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

## Практические сценарии и лучшие практики

### 1. Принцип минимальных привилегий
Всегда предоставляйте только те права, которые абсолютно необходимы.

```yaml
# ПЛОХО: избыточные права
rules:
- apiGroups: ["*"]
  resources: ["*"]
  verbs: ["*"]

# ХОРОШО: минимально необходимые права для чтения подов
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
Используйте `Role` и `RoleBinding` для ограничения доступа к ресурсам в рамках `namespace`.

```yaml
# Доступ только к Deployments в конкретном namespace 'development'
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
  name: dev-lead-binding
  namespace: development
subjects:
- kind: User
  name: dev-lead
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: deployment-manager
  apiGroup: rbac.authorization.k8s.io
```

### 3. Использование ClusterRole в конкретном Namespace
Чтобы переиспользовать роль в нескольких `namespace`, создайте `ClusterRole` и привязывайте ее через `RoleBinding`.

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
Если приложению не нужен доступ к Kubernetes API, отключите автоматическое монтирование токена `ServiceAccount`.

```yaml
# ServiceAccount без автоматического монтирования токена
apiVersion: v1
kind: ServiceAccount
metadata:
  name: no-api-access-sa
automountServiceAccountToken: false

# Под, использующий этот ServiceAccount
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  serviceAccountName: no-api-access-sa
  ...
```

### 5. Регулярный аудит RBAC
Периодически проверяйте текущие права доступа с помощью `kubectl auth can-i`.

```bash
# Проверка, может ли текущий пользователь создавать Deployments в namespace 'default'
kubectl auth can-i create deployments --namespace default

# Проверка от имени другого пользователя
kubectl auth can-i list secrets --namespace dev --as jane

# Проверка от имени ServiceAccount
kubectl auth can-i list nodes --as=system:serviceaccount:observability:prometheus
```

### Дополнительные рекомендации

*   **Предпочитайте `Role`**: Используйте `ClusterRole` только при необходимости кластерного доступа или для повторного использования в нескольких `namespace`.
*   **Связывайте группы, а не пользователей**: Для кластеров с внешней аутентификацией предпочтительнее назначать права группам. Это упрощает управление при смене состава команды.
*   **Ограничивайте доступ к RBAC-ресурсам**: Чтобы предотвратить эскалацию привилегий, отдельно ограничивайте права на `create`, `update`, `patch` для ресурсов `roles`, `rolebindings`, `clusterroles` и `clusterrolebindings`.
*   **Не давайте права `escalate` и `bind` без необходимости**: `escalate` позволяет получить права другой роли, а `bind` — создавать `RoleBinding`/`ClusterRoleBinding`.

## Дополнительная информация

*   [Using RBAC Authorization (Kubernetes Official Documentation)](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
*   [RBAC Good Practices](https://kubernetes.io/docs/concepts/security/rbac-good-practices/)
