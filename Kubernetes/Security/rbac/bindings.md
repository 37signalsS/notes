# Привязки ролей (RoleBinding) и кластерные привязки (ClusterRoleBinding)

## Определения

- **RoleBinding (Привязка роли)** — объект Kubernetes, связывающий [Role](./roles.md) или [ClusterRole](./roles.md) с субъектами в рамках одного пространства имён (namespace). Определяет **кому** и **где** разрешены действия.
- **ClusterRoleBinding (Кластерная привязка роли)** — объект Kubernetes, связывающий [ClusterRole](./roles.md) с субъектами на уровне всего кластера. Обеспечивает глобальный доступ ко всем ресурсам независимо от пространства имён.

Общие принципы работы **RBAC (Role-Based Access Control — управление доступом на основе ролей)** описаны в файле **[Обзор RBAC](./rbac_overview.md)**.

### Важные ограничения

- **Неизменяемость `roleRef`**: после создания привязки нельзя изменить роль, на которую она ссылается. Для смены роли необходимо удалить и заново создать объект привязки. Это архитектурное ограничение защищает от случайного повышения прав через подмену роли в существующей привязке.
- **Локальность Role**: `RoleBinding` может ссылаться на `Role` только в том же пространстве имён.
- **Ограничение ClusterRole через RoleBinding**: если `RoleBinding` ссылается на `ClusterRole`, права предоставляются только в рамках того namespace, где создана привязка. Это позволяет переиспользовать общие шаблоны (например, роль `view` или `edit`) для конкретных проектов без выдачи глобальных прав.

## Основные концепции

### Субъекты (Subjects)

Поле `subjects` определяет, кому предоставляются права доступа. Подробно типы субъектов разобраны в файле **[Субъекты доступа](./subjects.md)**.

| Тип | Описание | Пример |
|-----|----------|--------|
| `User` | Индивидуальный пользователь | `name: "jane@example.com"` |
| `Group` | Группа пользователей | `name: "developers"` |
| `ServiceAccount` | Идентификатор воркload-а (пода) | `name: "ci-bot"`, `namespace: "dev"` |

**Особенности субъектов:**
1. **Внешние сущности:** `User` и `Group` не являются объектами в базе Kubernetes (etcd). Они приходят из внешних систем (OIDC, сертификаты).
2. **Обязательность Namespace:** Для `ServiceAccount` поле `namespace` в блоке `subjects` является **обязательным**. Если его не указать, Kubernetes не сможет сопоставить запрос от пода с данной привязкой, что является частой причиной ошибок "403 Forbidden".

### Специальные системные группы

Использование групп позволяет гибко управлять доступом для множества субъектов сразу:

| Группа | Описание |
|--------|----------|
| `system:authenticated` | Все успешно аутентифицированные субъекты (включая всех пользователей и SA). |
| `system:unauthenticated` | Анонимные пользователи (если включена анонимная аутентификация). |
| `system:masters` | Суперпользователи кластера. **Критический риск:** имеют полный доступ в обход любых проверок RBAC. |
| `system:serviceaccounts` | Все сервисные аккаунты во всех пространствах имён кластера. |
| `system:serviceaccounts:<ns>` | Все сервисные аккаунты в конкретном `namespace`. Полезно для групповых разрешений внутри проекта. |
| `system:nodes` | Все узлы кластера (используется для Node Authorizer). |

### Сервисные аккаунты (ServiceAccount) и эволюция токенов

**ServiceAccount (SA)** — основной способ идентификации приложений в кластере.

#### Security Hardening токенов
1. **Legacy Tokens (v1.23 и ниже):** Токены генерировались автоматически и хранились в `Secret` бессрочно. Это создавало риск компрометации при краже секрета.
2. **Bound Service Account Tokens (v1.24+):** Токены короткоживущие (обычно 1 час), привязаны к конкретному поду (`object-bound`) и аудитории. Они монтируются как **Projected Volumes** и не хранятся в etcd как секреты.
3. **Node-Bound Tokens (v1.31+):** Токены теперь могут быть привязаны к конкретной **ноде**. Если нода удаляется или компрометируется, все её токены мгновенно аннулируются контроллером.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app-sa
  namespace: default
automountServiceAccountToken: false # Рекомендация: отключайте, если поду не нужен доступ к API
```

### Сравнение RoleBinding и ClusterRoleBinding

| Характеристика | RoleBinding | ClusterRoleBinding |
|----------------|-------------|-------------------|
| **Область действия** | Один namespace | Весь кластер |
| **Допустимые роли (`roleRef`)** | [Role](./roles.md) или [ClusterRole](./roles.md) | Только [ClusterRole](./roles.md) |
| **Субъекты** | User, Group, ServiceAccount | User, Group, ServiceAccount |

## Практические сценарии

### RoleBinding для пользователя (Доступ на чтение)

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: read-pods-binding
  namespace: dev
subjects:
- kind: User
  name: jane.doe@example.com
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: pod-reader # Ссылка на Role в том же namespace
  apiGroup: rbac.authorization.k8s.io
```

### RoleBinding для всех ServiceAccount в namespace

Сценарий: Разрешить всем подам в namespace `apps` получать метрики (через ClusterRole `view`).

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: all-apps-view
  namespace: apps
subjects:
- kind: Group
  name: system:serviceaccounts:apps
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: view # Глобальная роль, ограниченная неймспейсом apps
  apiGroup: rbac.authorization.k8s.io
```

### Кросс-пространственный доступ (Cross-Namespace)

Сценарий: Сервисный аккаунт из неймспейса `monitoring` должен иметь доступ к `production`.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: cross-ns-monitor
  namespace: production # Где предоставляются права
subjects:
- kind: ServiceAccount
  name: prometheus-sa
  namespace: monitoring # Откуда пришел субъект (ОБЯЗАТЕЛЬНО)
roleRef:
  kind: ClusterRole
  name: view
  apiGroup: rbac.authorization.k8s.io
```

### Глобальная привязка ClusterRoleBinding

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: cluster-admin-dev-leads
subjects:
- kind: Group
  name: dev-leads
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: cluster-admin # Полный доступ ко всему кластеру
  apiGroup: rbac.authorization.k8s.io
```

## Проверка и отладка (Verification)

### Проверка привязки через CLI

Для диагностики проблем с доступом используйте следующие команды:

```bash
# Просмотр деталей конкретной привязки
kubectl describe rolebinding read-pods-binding -n dev

# Проверка: может ли субъект выполнить действие
kubectl auth can-i list secrets \
  --as=system:serviceaccount:dev:my-app-sa \
  -n dev

# Проверка всех прав текущего пользователя
kubectl auth can-i --list
```

### Типичные ошибки (Troubleshooting)

1. **Missing Namespace in SA:** Если в блоке `subjects` для SA не указан `namespace`, права не применятся.
2. **RoleRef Mismatch:** Попытка сослаться на `Role` в `ClusterRoleBinding` приведет к ошибке валидации API.
3. **Broken Links:** Если роль (`roleRef`) удалена, привязка остается ("сиротская"), но перестает работать. `kubectl describe` подсветит это предупреждением.
4. **Аддитивность:** Если права не работают, проверьте, не перекрываются ли они другими привязками. RBAC только разрешает.

## Дополнительная информация

### Встроенные привязки

Kubernetes автоматически создает ряд системных привязок при инициализации:
- `cluster-admin`: связывает группу `system:masters` с ролью `cluster-admin`.
- `system:basic-user`: дает базовые права всем аутентифицированным пользователям.
- `system:controller:*`: привязки для внутренних контроллеров Kubernetes.

### Множественные привязки

Один субъект (пользователь, группа или SA) может быть упомянут в неограниченном количестве привязок одновременно.
- **Аддитивность:** Права суммируются. Если одна `RoleBinding` разрешает `get pods`, а другая — `list pods`, субъект сможет выполнять оба действия.
- **Приоритет:** В RBAC нет понятия приоритета или запрещающих правил (deny). Если хотя бы одна привязка разрешает действие — оно разрешено.

### Лучшие практики (Best Practices)

1. **Изоляция через RoleBinding:** Даже если вы используете глобальную `ClusterRole`, привязывайте её через `RoleBinding`, чтобы ограничить область доступа одним неймспейсом.
2. **Принцип минимальных привилегий (PoLP):** Создавайте уникальные `ServiceAccount` для каждого микросервиса. Избегайте использования SA `default`.
3. **Отказ от `system:masters`:** Никогда не добавляйте реальных пользователей в эту группу. Для администрирования используйте привязку к `cluster-admin`.
4. **Именование:** Используйте описательные имена привязок, отражающие суть: `<sa-name>-<role-name>-binding`.
5. **Безопасность системных групп:** Будьте предельно осторожны при назначении прав группам `system:authenticated` и `system:unauthenticated`. Это может открыть "черный ход" в кластер.
6. **Регулярный аудит:** Используйте инструменты сканирования (например, `kubescape` или `rakkess`) для поиска избыточных привилегий и "зависших" привязок.
7. **Автоматизация:** Отключайте `automountServiceAccountToken` в спеке пода, если приложению не нужно общаться с API Kubernetes.

### Связанные темы

- **[Общий обзор RBAC](./rbac_overview.md)**
- **[Определение ролей (Role и ClusterRole)](./roles.md)**
- **[Субъекты доступа (Subjects)](./subjects.md)**
- **[Агрегируемые ClusterRole](./aggregation_scenarios.md)**
