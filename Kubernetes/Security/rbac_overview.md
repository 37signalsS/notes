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

## Недостатки RBAC

Несмотря на свою мощь, RBAC имеет ряд ограничений:

### 1. Отсутствие deny-правил

RBAC работает только на основе разрешений (allowlist). Нельзя явно запретить действие — только не предоставить на него права.

```yaml
# Невозможно написать:
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["delete"]
  effect: Deny  # ❌ Такого нет в RBAC!
```

**Решение:** Использование OPA/Kyverno для запрещающих политик.

### 2. Нет условий (conditions)

Нельзя ограничить доступ на основе:
- Времени суток
- IP-адреса источника
- Значений полей ресурса (labels, annotations)
- Состояния ресурса

```yaml
# Невозможно ограничить по label:
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["delete"]
  when: resource.labels.environment == "production"  # ❌ Не поддерживается
```

**Решение:** OPA/Kyverno для политик на основе атрибутов (ABAC).

### 3. Статичность правил

RBAC-политики статичны и не могут динамически адаптироваться к контексту. Нельзя создать правило "разрешить доступ только к подам своей команды".

### 4. Сложность управления в больших кластерах

- Разрастание количества ролей и привязок
- Сложность аудита эффективных прав
- Риск "role explosion" — множество похожих ролей с минимальными отличиями

### 5. Нет контроля над содержимым ресурсов

RBAC контролирует CRUD-операции, но не валидирует содержимое:
- Нельзя запретить Pod с привилегированным контейнером
- Нельзя требовать определенные labels
- Нельзя ограничить ресурсы (CPU/memory)

**Решение:** Admission Controllers (OPA Gatekeeper, Kyverno).

### 6. Проблемы с эскалацией привилегий

- `escalate` verb позволяет создавать роли с правами, которых нет у создателя
- `bind` verb позволяет привязывать существующие роли
- Сложность отслеживания транзитивных прав

## OPA (Open Policy Agent) — расширение возможностей RBAC

**OPA** — это движок политик общего назначения, который позволяет реализовать сложные сценарии авторизации, недоступные в RBAC.

### Возможности OPA в Kubernetes

1. **Политики на основе контекста:**
   - Проверка IP-адреса клиента
   - Время суток
   - Атрибуты ресурса (labels, annotations)

2. **Запрещающие политики:**
   - Явный запрет определенных действий
   - Блокировка по условиям

3. **Валидация содержимого:**
   - Проверка spec ресурсов
   - Валидация безопасности (no privileged containers)
   - Требование наличия определенных полей

4. **Многоуровневая авторизация:**
   - Интеграция с внешними системами
   - Сложная логика принятия решений

### OPA Gatekeeper

OPA Gatekeeper — это специфическая реализация OPA для Kubernetes, работающая как Validating Webhook.

**Архитектура:**
```
API Request → API Server → OPA Gatekeeper → Decision (allow/deny)
                                          ↓
                                    Rego Policies
```

**Пример политики (Rego):**
```rego
package kubernetes.admission

# Запретить privileged контейнеры
deny[msg] {
    input.request.kind.kind == "Pod"
    input.request.object.spec.containers[_].securityContext.privileged
    msg := "Privileged containers are not allowed"
}

# Требовать label 'owner' на всех ресурсах
deny[msg] {
    input.request.object.metadata.labels.owner == ""
    msg := "All resources must have an 'owner' label"
}
```

### Сравнение RBAC и OPA

| Возможность | RBAC | OPA |
|-------------|------|-----|
| **Разрешения CRUD** | ✅ Да | ✅ Да |
| **Запрещающие правила** | ❌ Нет | ✅ Да |
| **Условия (time, IP)** | ❌ Нет | ✅ Да |
| **Проверка содержимого** | ❌ Нет | ✅ Да |
| **Сложность** | Низкая | Высокая |
| **Производительность** | Высокая (встроено) | Ниже (webhook) |
| **Язык политик** | YAML | Rego |

### Рекомендации по использованию

1. **RBAC для базовой авторизации:**
   - Разграничение доступа по namespace
   - Роли разработчиков/операторов
   - Доступ ServiceAccount

2. **OPA для сложных политик:**
   - Безопасность workload (no privileged, no root)
   - Compliance-требования
   - Контекстные ограничения
   - Запрещающие правила

3. **Комбинированный подход:**
   - RBAC дает общий доступ
   - OPA валидирует и ограничивает на уровне Admission Controller

## Дополнительная информация

*   [Using RBAC Authorization (Kubernetes Official Documentation)](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
*   [RBAC Good Practices](https://kubernetes.io/docs/concepts/security/rbac-good-practices/)
*   [OPA Documentation](https://www.openpolicyagent.org/docs/latest/)
*   [OPA Gatekeeper](https://open-policy-agent.github.io/gatekeeper/website/docs/)
