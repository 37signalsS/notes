# Субъекты доступа (Subjects) в Kubernetes

## Определения

**Субъекты (Subjects)** — это сущности, которым предоставляются разрешения на выполнение действий в кластере Kubernetes. RBAC связывает роли с этими субъектами через объекты Binding (привязки).

В Kubernetes существует три основных типа субъектов:

1.  **Пользователи (Users):** Индивидуальные учетные записи для людей (администраторов, разработчиков) или внешних систем.
2.  **Группы (Groups):** Коллекции субъектов, позволяющие назначать права сразу множеству людей (например, `system:authenticated`). Группы определяются на этапе аутентификации.
3.  **Учетные записи служб (Service Accounts):** Специальные объекты Kubernetes, предназначенные для идентификации процессов (подов), работающих внутри кластера.

**Важное архитектурное различие:**
- **Users и Groups** — внешние сущности. Kubernetes не имеет объектов `kind: User` в своей базе данных (etcd). Информация о них извлекается из сертификатов, токенов или заголовков запроса в момент аутентификации.
- **ServiceAccounts** — внутренние ресурсы API Kubernetes. Они имеют собственные манифесты и жизненный цикл внутри кластера.

---

## Основные концепции

### Маппинг пользователей и групп

Так как Kubernetes не хранит пользователей, их идентификация происходит на уровне модулей аутентификации.

- **X.509 Сертификаты:** Имя пользователя берется из поля `Common Name (CN)`, а группы — из полей `Organization (O)`. Каждое поле `O` в сертификате становится отдельной группой.
- **OIDC (OpenID Connect):** Имя пользователя и группы извлекаются из `claims` токена (например, `email` и `groups`). В Kubernetes v1.30+ поддерживается маппинг через CEL-выражения в конфигурационном файле `--authentication-config`.
- **Аутентифицирующий прокси:** Передает данные через HTTP-заголовки `X-Remote-User` и `X-Remote-Group`. Каждый заголовок `X-Remote-Group` формирует отдельную группу.

**Важно:** Один пользователь может принадлежать нескольким группам одновременно. Права субъекта — это объединение (union) всех прав из всех RoleBinding и ClusterRoleBinding, в которых он упомянут (см. [Привязки ролей](./bindings.md)).

Подробности механизмов проверки личности описаны в файле **[Аутентификация в Kubernetes](../authentication.md)**.

### Системные группы и субъекты

Kubernetes резервирует ряд групп с префиксом `system:` для внутреннего использования и стандартных политик.

| Субъект / Группа | Описание | Риски и использование |
|------------------|----------|-----------------------|
| `system:anonymous` | Назначается анонимным запросам, если включен флаг `--anonymous-auth=true`. | По умолчанию не имеет прав кроме `/healthz` и `/version`. |
| `system:unauthenticated` | Анонимные пользователи и все, кто не прошел аутентификацию. | **Высокий риск.** Не давайте этой группе никаких прав, кроме `/healthz`. |
| `system:authenticated` | Автоматически включает всех успешно аутентифицированных субъектов (включая всех пользователей и ServiceAccount). | Полезно для разрешений "всем своим" (например, `system:basic-user`). |
| `system:masters` | Группа суперпользователей. | **Критический риск.** Члены этой группы обходят RBAC полностью. Не добавляйте сюда пользователей. |
| `system:serviceaccounts` | Включает все ServiceAccounts во всех пространствах имен кластера. | Массовое управление правами приложений. |
| `system:serviceaccounts:<ns>` | Все ServiceAccounts в конкретном неймспейсе. | Изоляция на уровне проекта. |
| `system:nodes` | Группа всех узлов кластера. | Используется Node Authorizer для доступа Kubelet к API. |
| `system:basic-user` | Базовые права на чтение информации о самом пользователе (`SelfSubjectAccessReview`, `SelfSubjectRulesReview`). | Привязана по умолчанию к `system:authenticated`. |
| `system:discovery` | Доступ к эндпоинтам обнаружения API (`/api`, `/apis`, `/openapi`, `/version`). | В версиях до v1.14 также выдавалась `system:unauthenticated`. |
| `system:public-info-viewer` | Доступ к нечувствительной информации (`/healthz`, `/version`). | Введена в v1.14 для ограничения анонимного доступа. |

> **Важно по безопасности:** В кластерах до v1.14 роли `system:discovery` и `system:basic-user` по умолчанию выдавали доступ и неаутентифицированным пользователям, что раскрывало информацию об API. В новых кластерах анонимные пользователи получают только `system:public-info-viewer`.

### Учетные записи служб (Service Accounts)

**Service Account (SA)** — это «удостоверение личности» для вашего приложения. По умолчанию каждый неймспейс содержит SA с именем `default`.

#### Жизненный цикл ServiceAccount

1. **Создание:** SA — обычный объект Kubernetes с манифестом `kind: ServiceAccount`.
2. **Назначение поду:** Указывается в поле `spec.serviceAccountName` манифеста пода. Если не указано, под автоматически получает SA `default` из своего namespace.
3. **Внедрение токена:** Контроллер `ServiceAccount` (Mutating Admission) автоматически монтирует токен в под через projected volume в `/var/run/secrets/kubernetes.io/serviceaccount/`.
4. **Использование:** Приложение читает токен и использует его для аутентификации запросов к API-серверу.
5. **Ротация/Удаление:** Токены автоматически ротируются Kubelet до истечения TTL. При удалении пода токен аннулируется.

#### Ключевые аспекты безопасности

- **Изоляция:** Каждое приложение должно иметь свой уникальный SA. Использование `default` нарушает принцип наименьших привилегий.
- **Токены:** В современных версиях (v1.24+) токены SA являются короткоживущими (по умолчанию 1 час) и привязанными к поду (Bound Service Account Tokens). Подробнее об их эволюции см. в **[Привязках ролей](./bindings.md)**.
- **Automount:** По умолчанию Kubernetes монтирует токен SA в каждый под. Если приложению не нужен API (например, статический сайт), это следует отключать через `automountServiceAccountToken: false`.
- **Ручные токены:** Если приложению нужен долгоживущий токен (например, для внешней системы), его можно создать вручную через projected volume с нужным `expirationSeconds` или как Secret с аннотацией `kubernetes.io/service-account.name`.

#### ServiceAccount и Namespace

ServiceAccount привязан к конкретному namespace. Чтобы под из namespace `app-a` мог использовать SA из namespace `app-b`, необходимо:
1. Создать SA в `app-b`.
2. Создать RoleBinding в `app-b`, предоставляющий права этому SA.
3. Указать `serviceAccountName: app-b/my-sa` в манифесте пода в `app-a`.

Это стандартный паттерн для кросс-неймспейс доступа (например, мониторинг или CI/CD).

### Имперсонация (Impersonation)

Механизм, позволяющий одному пользователю действовать от имени другого (пользователя, группы или ServiceAccount).

- **Глагол:** `impersonate`.
- **Ресурс:** `users`, `groups`, `serviceaccounts` в группе `""` (core API).
- **Заголовки:** `Impersonate-User`, `Impersonate-Group`, `Impersonate-Extra-<key>`.

**Как это работает:** При отправке запроса с заголовком `Impersonate-User: alice@example.com` API-сервер аутентифицирует отправителя (проверяет его личность), а затем проверяет, имеет ли отправитель право `impersonate` на указанный субъект. Если проверка пройдена, дальнейшая авторизация выполняется от имени указанного пользователя.

**Что делает имперсонация:**
- Не отправляет реальные credentials имперсонируемого субъекта.
- Не меняет kubeconfig или контекст kubectl.
- Все действия записываются в аудит-логи с указанием реального отправителя и имперсонируемого субъекта.

**Риски:** Если разрешена имперсонация `system:masters`, имперсонирующий пользователь фактически получает полные права кластера.

Это критически важный инструмент для:
1. **Отладки:** Проверка прав другого пользователя без смены `kubeconfig`.
2. **Безопасности:** Использование привилегированного контроллера, который выполняет действия от имени менее привилегированного субъекта.
3. **CI/CD:** Пайплайн действует от имени ограниченного ServiceAccount, а не от «кластерного» администратора.

---

## Практические сценарии

### Создание и настройка Service Account

```bash
# 1. Создание SA
kubectl create serviceaccount custom-app-sa -n production

# 2. Отключение автоматического монтирования токена (лучшая практика)
kubectl patch serviceaccount custom-app-sa -p '{"automountServiceAccountToken": false}' -n production

# 3. Проверка конфигурации SA
kubectl get sa custom-app-sa -n production -o yaml
# → automountServiceAccountToken: false
```

### Полный пример: Service Account для приложения

```yaml
# 1. ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app-sa
  namespace: production
automountServiceAccountToken: false
---
# 2. Role с минимальными правами
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: my-app-role
  namespace: production
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  resourceNames: ["my-app-config"]
  verbs: ["get"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get"]
  # Ограничение конкретными секретами через resourceNames не работает с create,
  # но работает с get (см. roles.md → resourceNames)
---
# 3. RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: my-app-binding
  namespace: production
subjects:
- kind: ServiceAccount
  name: my-app-sa
  namespace: production  # ОБЯЗАТЕЛЬНО для кросс-неймспейс ссылок
roleRef:
  kind: Role
  name: my-app-role
  apiGroup: rbac.authorization.k8s.io
```

### Проверка прав через имперсонацию

Используйте флаг `--as` для проверки прав другого субъекта. Требуются права администратора.

```bash
# Может ли ServiceAccount 'my-sa' удалять поды в текущем неймспейсе?
kubectl auth can-i delete pods --as=system:serviceaccount:default:my-sa

# Проверка прав от имени группы
kubectl auth can-i list secrets --as-group=developers

# Комплексная проверка: все доступные действия для конкретного SA
kubectl auth can-i --list --as=system:serviceaccount:production:my-app-sa -n production

# Проверка доступа к конкретному ресурсу по имени
kubectl auth can-i get configmaps/app-config --as=system:serviceaccount:production:my-app-sa -n production

# Проверка доступа к нересурсному URL
kubectl auth can-i get /healthz --as=system:serviceaccount:production:my-app-sa
```

### Привязка прав ко всем ServiceAccount проекта

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: all-sa-reader
  namespace: dev-project
subjects:
- kind: Group
  name: system:serviceaccounts:dev-project
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: viewer
  apiGroup: rbac.authorization.k8s.io
```

### ServiceAccount для CI/CD пайплайна

Типичный паттерн: CI/CD система (GitLab Runner, Jenkins) создает временные SA для каждого деплоя.

```yaml
# SA для деплоя в production
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ci-deployer
  namespace: production
automountServiceAccountToken: true  # Нужен доступ к API для деплоя
---
# ClusterRole для деплоя (ограниченный edit)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ci-deployer-role
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: [""]
  resources: ["services", "configmaps"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
---
# RoleBinding в production (ClusterRole ограничивается одним namespace)
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ci-deployer-binding
  namespace: production
subjects:
- kind: ServiceAccount
  name: ci-deployer
  namespace: production
roleRef:
  kind: ClusterRole
  name: ci-deployer-role
  apiGroup: rbac.authorization.k8s.io
```

### ServiceAccount для системы мониторинга

Prometheus и аналогичные системы требуют доступа к метрикам из всех namespace.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: prometheus
  namespace: monitoring
---
# ClusterRole для сбора метрик
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-metrics-reader
rules:
- apiGroups: [""]
  resources: ["nodes", "nodes/metrics", "services", "endpoints", "pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get"]
- nonResourceURLs: ["/metrics", "/metrics/cadvisor"]
  verbs: ["get"]
---
# ClusterRoleBinding (глобальный доступ для мониторинга)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus-binding
subjects:
- kind: ServiceAccount
  name: prometheus
  namespace: monitoring
roleRef:
  kind: ClusterRole
  name: prometheus-metrics-reader
  apiGroup: rbac.authorization.k8s.io
```

### Имперсонация в CI/CD (GitLab CI)

GitLab CI поддерживает имперсонацию через параметр `access_as` в конфигурации kubectl-контекста:

```yaml
# .gitlab-ci.yml
deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  variables:
    KUBE_CONTEXT: "my-cluster/production"
  script:
    - kubectl config set-context --current --user=deployer
    - kubectl apply -f manifests/
```

В Kubernetes такой ServiceAccount получает права через RoleBinding:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: gitlab-deployer
  namespace: production
subjects:
- kind: ServiceAccount
  name: gitlab-ci
  namespace: ci-system
roleRef:
  kind: ClusterRole
  name: edit
  apiGroup: rbac.authorization.k8s.io
```

### Диагностика: почему субъект не имеет доступа

```bash
# 1. Проверка: есть ли привязка для этого субъекта?
kubectl get rolebindings,clusterrolebindings -A -o wide | grep my-app-sa

# 2. Просмотр деталей привязки
kubectl get rolebinding <name> -n <ns> -o yaml

# 3. Проверка прав субъекта (autorentic impersonation)
kubectl auth can-i list secrets \
  --as=system:serviceaccount:production:my-app-sa \
  -n production

# 4. Просмотр всех разрешений субъекта
kubectl auth can-i --list \
  --as=system:serviceaccount:production:my-app-sa \
  -n production

# 5. Проверка: какой SA назначен поду?
kubectl get pod <pod-name> -n <ns> -o jsonpath='{.spec.serviceAccountName}'
# → my-app-sa

# 6. Проверка: существует ли этот SA?
kubectl get sa my-app-sa -n <ns>
```

---

## Дополнительная информация

### Безопасность и Hardening

1. **Не используйте `system:masters`:** Членство в этой группе нельзя ограничить ролями RBAC. Это "черный ход", который должен быть закрыт.
2. **Очистка прав `default` SA:** Не назначайте никаких прав стандартному аккаунту `default`. Отключайте `automountServiceAccountToken` на уровне namespace:
   ```bash
   kubectl patch serviceaccount default -p '{"automountServiceAccountToken": false}' -n <namespace>
   ```
3. **Аудит токенов:** Регулярно проверяйте, какие поды имеют доступ к API кластера:
   ```bash
   kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}: {.spec.serviceAccountName}{"\n"}{end}'
   ```
4. **Ограничение имперсонации:** Права на глагол `impersonate` эквивалентны правам администратора кластера, если разрешена имитация `system:masters`.
5. **Использование готовых ролей:** Вместо создания кастомных ролей используйте встроенные `view`, `edit`, `admin` (см. [Роли и ClusterRole](./roles.md)).
6. **Привязка к группам, а не к пользователям:** Управлять членством в группе (например, в SSO/IdP) легче, чем пересоздавать множество биндингов при кадровых изменениях.
7. **Инструменты аудита:** Используйте `rakkess` или `kubescape` для поиска избыточных привилегий и «зависших» привязок.

### Советы для собеседования

> **Вопрос:** Где Kubernetes хранит пароли пользователей?
> **Ответ:** Нигде. Kubernetes не управляет пользователями напрямую. Он доверяет проверку личности внешним механизмам (OIDC, сертификаты), получая от них только имя и список групп.

> **Вопрос:** Чем опасен `automountServiceAccountToken: true`?
> **Ответ:** При компрометации приложения злоумышленник получает доступ к токену в файловой системе пода и может атаковать API-сервер с правами этого ServiceAccount. Токен можно украсть из `/var/run/secrets/kubernetes.io/serviceaccount/token`.

> **Вопрос:** Как работает имперсонация в Kubernetes?
> **Ответ:** Через HTTP-заголовки `Impersonate-User` и `Impersonate-Group`. API-сервер сначала аутентифицирует отправителя, затем проверяет, имеет ли он право `impersonate` на указанный субъект. Все действия записываются в аудит с указанием обоих субъектов.

> **Вопрос:** Можно ли изменить RoleBinding без даунтайма?
> **Ответ:** Нет. Поле `roleRef` является неизменяемым (immutable). Для смены роли необходимо удалить и создать привязку заново. Между этими шагами доступ субъекта на короткое время пропадает.

### Связанные темы
- **[Обзор RBAC](./rbac_overview.md)**
- **[Роли и ClusterRole](./roles.md)**
- **[Привязки ролей (RoleBinding)](./bindings.md)**
- **[Агрегируемые ClusterRole](./aggregation_scenarios.md)**
- **[Аутентификация через TLS-клиентские сертификаты](./certificate_auth.md)**
- **[Webhook Token Authentication](./webhook_auth.md)**
- **[Эскалация привилегий](./privilege_escalation.md)**
- **[Аутентификация в Kubernetes](../authentication.md)**
- **[Типичные ошибки RBAC](../../Troubleshooting/Common_Errors/ApiAccessForbidden/rbac_objects.md)**
