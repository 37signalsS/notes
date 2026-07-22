# Привязки ролей (RoleBinding) и кластерные привязки (ClusterRoleBinding)

## Определения

- **RoleBinding (Привязка роли)** — объект Kubernetes, связывающий [Role](./roles.md) или [ClusterRole](./roles.md) с субъектами в рамках одного пространства имён (namespace). Определяет **кому** и **где** разрешены действия.
- **ClusterRoleBinding (Кластерная привязка роли)** — объект Kubernetes, связывающий [ClusterRole](./roles.md) с субъектами на уровне всего кластера. Обеспечивает глобальный доступ ко всем ресурсам независимо от пространства имён.

Общие принципы работы **RBAC (Role-Based Access Control — управление доступом на основе ролей)** описаны в файле **[Обзор RBAC](./rbac_overview.md)**.

### Важные ограничения

- **Неизменяемость `roleRef`**: после создания привязки нельзя изменить роль, на которую она ссылается. Для смены роли необходимо удалить и заново создать объект привязки.
- **Локальность Role**: `RoleBinding` может ссылаться на `Role` только в том же пространстве имён.
- **Ограничение ClusterRole через RoleBinding**: если `RoleBinding` ссылается на `ClusterRole`, права предоставляются только в рамках того namespace, где создана привязка.

## Основные концепции

### Субъекты (Subjects)

Поле `subjects` определяет, кому предоставляются права доступа:

| Тип | Описание | Пример |
|-----|----------|--------|
| `User` | Индивидуальный пользователь | `name: "jane@example.com"` |
| `Group` | Группа пользователей | `name: "developers"` |
| `ServiceAccount` | Идентификатор воркload-а (пода) | `name: "ci-bot"`, `namespace: "dev"` |

**Особенности субъектов:**
1. **Внешние пользователи:** `User` и `Group` не хранятся в БД Kubernetes. Они приходят из внешних систем (сертификаты, OIDC, LDAP).
2. **Обязательность Namespace:** Для `ServiceAccount` поле `namespace` в блоке `subjects` является **обязательным**. Пропуск этого поля — частая причина ошибок, при которых привязка создается, но доступ не предоставляется.

### Сервисные аккаунты (ServiceAccount)

**ServiceAccount (SA)** — основной механизм идентификации приложений (воркload-ов) в Kubernetes. Каждому поду назначается один SA, токен которого используется для аутентификации в API-сервере.

#### Эволюция токенов (Security Hardening)
1. **Legacy Tokens (v1.23 и ниже):** Токены генерировались автоматически и хранились в `Secret` бессрочно. Этот метод признан небезопасным.
2. **Bound Service Account Tokens (v1.24+):** Токены теперь являются короткоживущими (обычно 1 час), привязаны к конкретному поду (`object-bound`) и аудитории (`audience-bound`). Они не хранятся в `Secret`, а монтируются через **Projected Volumes**.
3. **Node-Bound Tokens (v1.31+):** Новая возможность привязки токена к конкретной **ноде**. Если нода компрометирована или удалена, все связанные с ней токены мгновенно аннулируются.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app-sa
  namespace: default
automountServiceAccountToken: false # Рекомендация: отключать по умолчанию
```

> **Лучшая практика:** Если приложению не нужно взаимодействовать с API Kubernetes, всегда устанавливайте `automountServiceAccountToken: false`. Это исключает риск захвата токена при компрометации приложения.

### Специальные системные группы

| Группа | Описание |
|--------|----------|
| `system:authenticated` | Все успешно аутентифицированные субъекты (включая SA). |
| `system:unauthenticated` | Анонимные пользователи (если разрешены в API-сервере). |
| `system:masters` | Суперпользователи кластера. **Критический риск:** обходят все проверки RBAC. |
| `system:serviceaccounts` | Все сервисные аккаунты во всех пространствах имён. |
| `system:serviceaccounts:<ns>` | Все сервисные аккаунты в конкретном `namespace`. |
| `system:nodes` | Все ноды кластера (используется для Node Authorizer). |


### Поле roleRef

Поле `roleRef` указывает на роль, права которой делегируются:

- **В RoleBinding**: может ссылаться на [Role](./roles.md) в том же namespace или на [ClusterRole](./roles.md) (в этом случае права ClusterRole ограничиваются пространством имён привязки).
- **В ClusterRoleBinding**: может ссылаться только на [ClusterRole](./roles.md) для получения глобальных прав.

### Сравнение RoleBinding и ClusterRoleBinding

| Характеристика | RoleBinding | ClusterRoleBinding |
|----------------|-------------|-------------------|
| **Область действия** | Конкретное пространство имён | Весь кластер |
| **Допустимые роли (`roleRef`)** | [Role](./roles.md) или [ClusterRole](./roles.md) | Только [ClusterRole](./roles.md) |
| **Субъекты** | User, Group, ServiceAccount | User, Group, ServiceAccount |
| **Типовые сценарии** | Права команды внутри проекта | Системные администраторы, мониторинг |

## Практические сценарии

### RoleBinding с локальной Role

Предоставление прав на чтение подов пользователю и сервисному аккаунту в одном пространстве имён:

```yaml
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
  name: pod-reader # Ссылка на Role в namespace 'default'
  apiGroup: rbac.authorization.k8s.io
```

### RoleBinding с глобальной ClusterRole

Привязка глобально определенной роли (например, для чтения секретов) только в одном пространстве имён:

```yaml
# Привязка ClusterRole 'secret-reader' к группе только в namespace 'staging'
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

### Глобальная привязка ClusterRoleBinding

Предоставление административных прав на узлы кластера для группы администраторов:

```yaml
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

## Дополнительная информация

### Встроенные привязки

Kubernetes автоматически создает ряд системных привязок. Самая важная:
- `cluster-admin` — связывает группу `system:masters` с ролью `cluster-admin`. Это дает полный контроль над кластером.

### Множественные привязки

Один субъект может быть упомянут в нескольких привязках одновременно. В этом случае его права суммируются (**аддитивность RBAC**). Если одна роль разрешает `get`, а другая `list`, субъект сможет делать и то, и другое.

### Лучшие практики

1. **Изоляция через RoleBinding:** Всегда предпочитайте `RoleBinding`, даже если используете `ClusterRole`. Это ограничивает "радиус поражения" при компрометации субъекта одним пространством имён.
2. **Отказ от `system:masters`:** Никогда не добавляйте пользователей в группу `system:masters`. Для административных задач используйте привязку к ClusterRole `cluster-admin`.
3. **Один ServiceAccount — одно приложение:** Не используйте `default` ServiceAccount. Создавайте уникальные SA для каждого микросервиса с минимально необходимым набором прав.
4. **Безопасные токены:** Используйте короткоживущие токены (Bound Tokens) и отключайте `automountServiceAccountToken` для подов, которым не нужен доступ к API.
5. **Регулярный аудит:** Используйте инструменты типа `rbac-lookup`, `rakkess` или `kubectl auth can-i` для поиска избыточных прав и привязок к анонимным пользователям.
6. **Очистка сиротских привязок:** При удалении Namespace или ServiceAccount проверяйте наличие "зависших" `ClusterRoleBinding`, которые могут указывать на несуществующие субъекты.

### Связанные темы

- **[Общий обзор RBAC](./rbac_overview.md)**
- **[Определение ролей (Role и ClusterRole)](./roles.md)**
- **[Агрегируемые ClusterRole](./aggregation_scenarios.md)**

