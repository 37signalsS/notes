# Привязки ролей (RoleBinding) и кластерные привязки (ClusterRoleBinding)

## Определения

<a name="rolebinding"></a>
**RoleBinding (Привязка роли)** — объект Kubernetes, связывающий [Role](./roles.md) или [ClusterRole](./roles.md) с одним или несколькими субъектами в рамках одного пространства имён (namespace). Определяет **кому** и **где** разрешены действия.

<a name="clusterrolebinding"></a>
**ClusterRoleBinding (Кластерная привязка роли)** — объект Kubernetes, связывающий [ClusterRole](./roles.md) с субъектами на уровне всего кластера. Обеспечивает глобальный доступ ко всем ресурсам независимо от пространства имён.

Общие принципы работы **RBAC (Role-Based Access Control — управление доступом на основе ролей)** описаны в файле **[Обзор RBAC](./rbac_overview.md)**.

### Важные ограничения

- **Неизменяемость `roleRef`**: для изменения ссылочной роли необходимо удалить и заново создать объект привязки.
- **Локальность Role**: RoleBinding может ссылаться на Role только в том же пространстве имён, где находится сама привязка.

## Основные концепции

### Субъекты (Subjects)

Поле `subjects` определяет, кому предоставляются права доступа:

| Тип | Описание | Пример |
|-----|----------|--------|
| `User` | Индивидуальный пользователь | `name: "jane@example.com"` |
| `Group` | Группа пользователей | `name: "developers"` |
| `ServiceAccount` | Сервисный аккаунт | `name: "ci-bot"`, `namespace: "dev"` |

> **Важно:** `User` и `Group` не являются объектами внутри Kubernetes. Они управляются внешними системами аутентификации (OIDC, сертификаты, webhook).

### Сервисные аккаунты (ServiceAccount)

<a name="serviceaccount"></a>
**ServiceAccount** — объект Kubernetes, предназначенный для идентификации процессов (приложений), запущенных внутри подов.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app-sa
  namespace: default
automountServiceAccountToken: false  # Рекомендуется: отключить автоматическое монтирование токена
```

> **Лучшая практика:** Используйте `automountServiceAccountToken: false` и подключайте токен только тем подам, которым это явно необходимо для взаимодействия с API Kubernetes.

#### Формат записи ServiceAccount в привязках

Для `ServiceAccount` поле `namespace` в блоке `subjects` является обязательным:

```yaml
subjects:
- kind: ServiceAccount
  name: my-sa
  namespace: default
```

### Специальные системные группы

| Группа | Описание |
|--------|----------|
| `system:authenticated` | Все успешно аутентифицированные субъекты |
| `system:unauthenticated` | Все неаутентифицированные пользователи |
| `system:masters` | Группа суперпользователей, обходящая все проверки RBAC. См. **[Предупреждения безопасности](./rbac_overview.md#preduprezhdeniya-bezopasnosti)** |
| `system:serviceaccounts` | Все сервисные аккаунты кластера |
| `system:serviceaccounts:<ns>` | Все сервисные аккаунты в конкретном пространстве имён |

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

<a name="prakticheskie-scenarii"></a>

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

Kubernetes автоматически создает ряд системных привязок, например:

- `cluster-admin` — связывает группу `system:masters` с ролью `cluster-admin`.

### Множественные привязки

Один субъект может быть упомянут в нескольких привязках одновременно. В этом случае его права суммируются (**аддитивность RBAC**).

### Лучшие практики

1. **Предпочитайте RoleBinding**: даже если используется ClusterRole, привязывайте её через RoleBinding для ограничения прав рамками проекта.
2. **Минимизируйте использование `system:masters`**: не добавляйте пользователей в эту группу, используйте `cluster-admin` через ClusterRoleBinding.
3. **Регулярный аудит**: проверяйте наличие привязок к `system:unauthenticated` и лишних прав у ServiceAccount.
4. **Выделенные ServiceAccount**: создавайте отдельный аккаунт для каждого приложения вместо использования `default`.

### Связанные темы

- **[Общий обзор RBAC](./rbac_overview.md)**
- **[Определение ролей (Role и ClusterRole)](./roles.md)**
- **[Агрегируемые ClusterRole](./aggregation_scenarios.md)**
