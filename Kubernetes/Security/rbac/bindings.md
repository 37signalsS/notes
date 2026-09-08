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
3. **Поле `apiGroup` у субъектов:** для `User` и `Group` значение всегда `rbac.authorization.k8s.io` — это признак встроенного типа субъекта RBAC. Для `ServiceAccount` узел `apiGroup` указывать не нужно (поле отсутствует или пустое), тип распознаётся как ресурс core API.
4. **Один субъект — множество привязок:** права одного субъекта — это объединение (union) всех ролей из всех привязок, где он фигурирует (субъект может быть и частью группы, и иметь собственные точечные привязки одновременно).

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

**Важно:** указание группы `system:serviceaccounts` в `RoleBinding` даёт права всем SA **в рамках конкретного namespace** (где создана привязка). Для глобального охвата всех SA требуется `ClusterRoleBinding`. То же относится и к `system:authenticated`/`system:unauthenticated` в `RoleBinding` — привязка сужает область до одного namespace.

### Сервисные аккаунты (ServiceAccount) и эволюция токенов

**ServiceAccount (SA)** — основной способ идентификации приложений в кластере.

#### Security Hardening токенов
1. **Legacy Tokens (v1.23 и ниже):** Токены генерировались автоматически и хранились в `Secret` бессрочно. Это создавало риск компрометации при краже секрета.
2. **Bound Service Account Tokens (v1.24+):** Токены короткоживущие (обычно 1 час), привязаны к конкретному поду (`object-bound`) и аудитории. Они монтируются как **Projected Volumes** и не хранятся в etcd как секреты.
3. **Node-Bound Tokens (альфа в v1.29, бета в v1.31, GA в v1.33):** Токены могут быть привязаны к конкретной **Node** (объект-привязка, как и в случае с Pod). Если нода удаляется или меняется её UID, аутентификатор перестаёт принимать такие токены — они автоматически теряют силу без действий со стороны контроллера. Создаются явно:
   ```bash
   # kubectl 1.31+
   kubectl create token my-sa --bound-object-kind Node --bound-object-name worker-01
   ```

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

### Структура `roleRef` и версия API

API-группа привязок — `rbac.authorization.k8s.io`, стабильная версия `v1`. Современные манифесты используют `apiVersion: rbac.authorization.k8s.io/v1` (более старые `v1beta1` устарели и удалены в v1.22).

Блок `roleRef` описывает, **на какую роль** ссылается привязка, и состоит ровно из трёх полей:

```yaml
roleRef:
  kind: Role            # или ClusterRole (в ClusterRoleBinding — только ClusterRole)
  name: pod-reader      # имя роли в том же namespace (для Role) или глобальной роли
  apiGroup: rbac.authorization.k8s.io
```

Требования валидации:
- `kind` может быть только `Role` либо `ClusterRole` — другие значения (например `User`) отклоняются API-сервером.
- `apiGroup` всегда `rbac.authorization.k8s.io`; указание другого значения также приведёт к ошибке.
- Все три поля **неизменяемы** — попытка изменить `roleRef` у существующей привязки (включая `kubectl apply` с обновлённым манифестом) возвращает ошибку. Привязку нужно удалить и создать заново.
- `RoleBinding` может ссылаться на `Role` **только в том же namespace** (поле `name` резолвится относительно namespace привязки). `ClusterRole` доступна из любого namespace.

### Поведение при ссылке на агрегируемую ClusterRole

Если `roleRef.name` указывает на **агрегируемую** ClusterRole (см. [Агрегируемые ClusterRole](./aggregation_scenarios.md)), то в момент обращения привязки к правам учитываются и правила, собранные через `aggregationRule`. Это означает, что добавление новой агрегируемой роли с меткой `aggregate-to-admin/edit/view` автоматически расширяет доступ **всех** субъектов, привязанных к агрегату ролей. Учитывайте это при операциях в GitOps — изменение меток агрегации мгновенно меняет фактические права существующих привязок.

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

### Создание привязок через kubectl (императивный способ)

Для быстрых/разовых операций удобнее создавать привязки одной командой, без файла манифеста (в манифестах, применяемых из Git, предпочтителен декларативный вариант):

```bash
# RoleBinding для пользователя
kubectl create rolebinding pod-reader-binding \
  --role=pod-reader \
  --user=jane.doe@example.com \
  -n dev

# RoleBinding для группы
kubectl create rolebinding devs-view-binding \
  --clusterrole=view \
  --group=developers \
  -n dev

# RoleBinding для ServiceAccount (указывается как имяSA:namespace)
kubectl create rolebinding my-sa-view \
  --clusterrole=view \
  --serviceaccount=dev:my-app-sa \
  -n dev

# ClusterRoleBinding для группы
kubectl create clusterrolebinding cluster-admin-dev-leads \
  --clusterrole=cluster-admin \
  --group=dev-leads
# → rolebinding.rbac.authorization.k8s.io/pod-reader-binding created
```

Проверить созданную привязку:

```bash
# Краткая сводка всех привязок в namespace (колонки USERS/GROUPS/SERVICEACCOUNTS)
kubectl get rolebindings -n dev

# Расширенный вывод
kubectl get rolebindings -n dev -o wide
# → NAME              ROLE         USERS               GROUPS          SERVICEACCOUNTS
# → pod-reader-binding Role/pod-reader jane.doe@example.com
```

### Множественные субъекты в одной привязке

Привязка может содержать **несколько записей в `subjects`**, что сокращает число объектов RBAC и упрощает управление:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ops-access
  namespace: production
subjects:
- kind: User
  name: alice@example.com
  apiGroup: rbac.authorization.k8s.io
- kind: Group
  name: on-call-eng
  apiGroup: rbac.authorization.k8s.io
- kind: ServiceAccount
  name: pipeline-bot
  namespace: ci
roleRef:
  kind: ClusterRole
  name: edit
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

# Поиск всех привязок, в которых участвует субъект
kubectl get rolebindings,clusterrolebindings -A | grep my-app-sa

# Проверка прав субъекта с учетом группы (OIDC/LDAP группа)
kubectl auth can-i get pods --as=jane.doe@example.com --as-group=developers -n dev
```

> **Совет для диагностики:** таблица `-o wide` в `kubectl get rolebindings` показывает колонки `USERS`, `GROUPS`, `SERVICEACCOUNTS` — это самый быстрый способ увидеть, какая привязка (или её отсутствие) отвечает за доступ конкретного субъекта.

### Типичные ошибки (Troubleshooting)

1. **Missing Namespace in SA:** Если в блоке `subjects` для SA не указан `namespace`, права не применятся. При создании через `kubectl create rolebinding --serviceaccount=sa:namespace` подстановка правильного namespace обязательна.
2. **RoleRef Mismatch:** Попытка сослаться на `Role` в `ClusterRoleBinding` приведет к ошибке валидации API (`RoleBinding` может ссылаться только на `Role`/`ClusterRole`, а `ClusterRoleBinding` — только на `ClusterRole`).
3. **Broken Links:** Если роль (`roleRef`) удалена, привязка остается ("сиротская"), но перестает работать. `kubectl describe` подсветит это предупреждением (`Warning  ReferenceErrors`).
4. **Аддитивность:** Если права не работают, проверьте, не перекрываются ли они другими привязками. RBAC только разрешает.
5. **Изменение `roleRef` через `kubectl apply`:** из‑за неизменяемости ссылки на роль применение обновлённого манифеста вернёт ошибку вида `roleRef: invalid value ...` / запрет операции. Это типичная ловушка GitOps-пайплайнов. Исправление — удалить привязку и создать заново:
   ```bash
   kubectl delete rolebinding read-pods-binding -n dev
   kubectl apply -f read-pods-binding.yaml
   ```
   Помните: удаление и повторное создание привязки значит, что между шагами доступ субъекта на короткое время пропадает.
6. **Задержка распространения RBAC:** API-сервер кэширует RBAC-данные, поэтому после создания/изменения привязки новые права применяются не мгновенно (обычно от единиц секунд до минуты). Кэш управляется параметром `authorization.configuration.authorization.k8s.io/...` (стандартные значения — пересчёт каждые 5–30 секунд). Если сразу после `kubectl apply` права «не заработали», подождите несколько секунд и повторите проверку.
7. **Права не подхватываются приложением при старте:** приложение, получившее токен SA, обращается к API с тем же токеном и теми же правами, что и SA. Проблема обычно не в «устаревшем токене», а в том, что SA, выданный поду, не совпадает с SA из манифеста привязки (`spec.serviceAccountName`). Проверьте связку SA пода ↔ `subjects.name` в привязке.

### Текущее состояние и права субъекта (чек-лист)

Для быстрого выяснения, почему субъект не имеет доступа:

```bash
# 1. Все привязки субъекта по всем namespace
kubectl get rolebindings,clusterrolebindings -A | grep <subject>

# 2. Конкретная привязка (код 8 вместо YAML)
kubectl get rolebinding <name> -n <ns> -o yaml

# 3. Самостоятельная проверка от имени субъекта
kubectl auth can-i get pods --as=system:serviceaccount:dev:my-app-sa -n dev

# 4. Просмотр правил, которыми фактически владеет субъект
# (нужно право на SelfSubjectRulesReview — есть у system:basic-user)
kubectl auth can-i --list --as=system:serviceaccount:dev:my-app-sa -n dev
```

Первое и главное правило отладки: **найти, есть ли вообще привязка для этого субъекта**. Если её нет, то никакая роль не «сработает» — привязка является обязательным мостом между ролью и субъектом.

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
- **[Multi-cluster RBAC](./multi_cluster_rbac.md)**
- **[RBAC для ResourceQuota и LimitRange](./resource_quota_rbac.md)**
