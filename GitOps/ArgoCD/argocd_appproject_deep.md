# Argo CD: AppProject — изоляция, границы безопасности и управление доступом

**Актуально для:** Argo CD v3.5.x

> **Актуальность (2026):** `AppProject` — ключевой CRD-ресурс (`argoproj.io/v1alpha1`) для изоляции тенантов, контроля границ (security boundaries) и мультитенантности в Argo CD v3.5.x. Объект регламентирует разрешенные источники манифестов (`sourceRepos`), целевые кластеры и пространства имен (`destinations`), списки разрешенных и блокируемых ресурсов Kubernetes (`clusterResourceWhitelist`, `namespaceResourceBlacklist`), окна синхронизации (`syncWindows`), проектные роли с генерацией scoped JWT-токенов для CI/CD, имперсонацию ServiceAccount (`destinationServiceAccounts`), детекцию неконтролируемых сущностей (`orphanedResources`) и изоляцию пространств создания приложений (`sourceNamespaces`).

---

## Предварительные требования

1. **Развернутый Argo CD:** Версия v3.5.x (см. [Установка и настройка](./argocd_installation_and_setup.md)).
2. **Административный доступ:** Права администратора в пространстве имен `argocd` (RBAC `admin` или `kubectl` с правами на редактирование CRD `appprojects.argoproj.io`).
3. **Утилиты управления:** Установленный и аутентифицированный CLI `argocd` и `kubectl`.
4. **Смежные знания:**
   - Модель прав и Casbin-политики (см. [RBAC](./argocd_rbac_deep.md)).
   - Общая стратегия изоляции команд и проектов (см. [Мультитенантность](./argocd_multi_tenancy.md)).
   - Управление регламентными окнами деплоя (см. [Sync Windows](./synchronization/scenarios/sync_windows.md)).

---

## Определения

| Термин | Определение |
| :--- | :--- |
| **AppProject** | Custom Resource (`kind: AppProject`, API-группа `argoproj.io/v1alpha1`), определяющий границы допустимых действий для группы приложений: разрешенные репозитории, целевые кластеры, типы ресурсов и роли. |
| **Default Project (`default`)** | Встроенный проект по умолчанию. В базовой установке разрешает любые репозитории (`*`) и любые назначения (`*/*`), что представляет уязвимость в production-инсталляциях при отсутствии hardening. |
| **Source Repositories (`sourceRepos`)** | Список разрешенных URL Git-репозиториев, Helm-репозиториев или OCI-реестров, из которых приложения проекта могут извлекать манифесты. Поддерживает маски и подстановки. |
| **Destinations (`destinations`)** | Белый список целевых кластеров (по URL `server` или имени `name`) и пространств имен (`namespace`), куда разрешен деплой. |
| **Source Namespaces (`sourceNamespaces`)** | Список пространств имен Kubernetes, в которых пользователям разрешено создавать сами манифесты `Application`, привязанные к данному проекту (механизм *Applications in any namespace*). |
| **Cluster Resource Whitelist / Blacklist** | Перечень типов ресурсов уровня кластера (cluster-scoped, например `ClusterRole`, `Namespace`, `CRD`), разрешенных (`whitelist`) или запрещенных (`blacklist`) для создания приложениями проекта. |
| **Namespace Resource Whitelist / Blacklist** | Перечень типов ресурсов уровня пространства имен (namespace-scoped, например `Deployment`, `Secret`), разрешенных или запрещенных к деплою. Blacklist имеет безусловный приоритет над Whitelist. |
| **Project Role (`roles`)** | Локальная роль доступа внутри AppProject. Позволяет выпускать scoped JWT-токены для CI/CD-пайплайнов и связывать группы поставщика SSO/OIDC с гранулярными правами в рамках только этого проекта. |
| **destinationServiceAccounts** | Механизм имперсонации Kubernetes ServiceAccount в целевом кластере/namespace. Контроллер Argo CD при синхронизации выполняет запросы от имени указанного SA, а не с правами кластерного контроллера. |
| **Orphaned Resources Monitoring** | Функция отслеживания ресурсов в целевом namespace, которые не управляются ни одним приложением Argo CD, привязанным к проекту. |
| **Sync Windows (`syncWindows`)** | Расписания (cron), блокирующие (`deny`) или разрешающие (`allow`) автоматическую и ручную синхронизацию приложений проекта в определенные временные интервалы. |

---

## Архитектура и принципы работы

### Структура спецификации AppProject CRD

Объект `AppProject` представляет собой декларативное описание границ безопасности:

```text
AppProject (argoproj.io/v1alpha1)
├── metadata:
│   ├── name: <имя-проекта>
│   └── finalizers: [resources-finalizer.argocd.argoproj.io]
└── spec:
    ├── description: <описание-проекта>
    ├── sourceRepos:                    ← Белый список репозиториев (Git/Helm/OCI)
    ├── destinations:                   ← Белый список целевых кластеров и namespace
    ├── sourceNamespaces:               ← Где разрешено создавать Application CR
    ├── clusterResourceWhitelist:       ← Разрешенные кластерные типы (Group + Kind)
    ├── clusterResourceBlacklist:       ← Запрещенные кластерные типы (приоритет над whitelist)
    ├── namespaceResourceWhitelist:     ← Разрешенные пространственные типы
    ├── namespaceResourceBlacklist:     ← Запрещенные пространственные типы (например Secret)
    ├── destinationServiceAccounts:     ← Имперсонация SA в целевых namespace
    ├── orphanedResources:              ← Детекция бесхозных объектов в namespace
    │   ├── warn: true
    │   └── ignore: [...]
    ├── syncWindows:                    ← Регламентные окна деплоя (allow/deny)
    ├── permitOnlyProjectScopedClusters:      ← Изоляция: только проектные кластеры
    ├── permitOnlyProjectScopedRepositories:  ← Изоляция: только проектные репозитории
    └── roles:                          ← Локальные роли, JWT токены и маппинг SSO-групп
        ├── name: <имя-роли>
        ├── policies: [...]
        ├── groups: [...]
        └── jwtTokens: [...]
```

### Конвейер валидации и проверок (Security Evaluation Pipeline)

При создании приложения `Application`, редактировании его спеки или запуске синхронизации контроллер `argocd-application-controller` и API-сервер `argocd-server` проверяют операцию по многоуровневому алгоритму:

```text
Операция: Создание Application или запуск Sync
                       │
                       ▼
    [Этап 1: Namespace создания Application]
    Приложение создано вне namespace "argocd"?
    ├── ДА ──> Входит ли namespace в spec.sourceNamespaces проекта?
    │          ├── НЕТ ──> [ОТКАЗ]: Application is outside permitted source namespaces
    │          └── ДА  ──> Переход к Этапу 2
    └── НЕТ ──> Переход к Этапу 2
                       │
                       ▼
    [Этап 2: Проверка источника (Source Repo)]
    URL репозитория манифестов входит в spec.sourceRepos?
    ├── НЕТ ──> [ОТКАЗ]: application repo <url> is not permitted in project
    └── ДА  ──> Переход к Этапу 3
                       │
                       ▼
    [Этап 3: Проверка назначения (Destination)]
    Пара (cluster, namespace) соответствует spec.destinations?
    ├── НЕТ ──> [ОТКАЗ]: application destination is not permitted in project
    └── ДА  ──> Переход к Этапу 4
                       │
                       ▼
    [Этап 4: Проверка типов манифестов (Whitelists / Blacklists)]
    Для каждого ресурса в Git/Helm:
    1. Кластерный ресурс?
       - Если в clusterResourceBlacklist ──> [ОТКАЗ]: resource is explicitly blacklisted
       - Если НЕ в clusterResourceWhitelist ──> [ОТКАЗ]: cluster resource is not permitted
    2. Namespace-ресурс?
       - Если в namespaceResourceBlacklist ──> [ОТКАЗ]: resource is explicitly blacklisted
       - Если задан namespaceResourceWhitelist и ресурс не входит в него ──> [ОТКАЗ]
    └── Успешно ──> Переход к Этапу 5
                       │
                       ▼
    [Этап 5: Авторизация субъекта (RBAC & Project Roles)]
    Имеет ли инициатор (пользователь, SSO-группа или JWT токен роли)
    право на действие (sync, update, get) согласно policy.csv и spec.roles?
    ├── НЕТ ──> [ОТКАЗ]: permission denied: applications, sync, <proj>/<app>
    └── ДА  ──> Переход к Этапу 6
                       │
                       ▼
    [Этап 6: Окна синхронизации (Sync Windows)]
    Попадает ли текущее время под активное окно spec.syncWindows?
    ├── Активно deny-окно (manualSync: false) ──> [БЛОКИРОВКА]: sync is disabled by sync window
    ├── Активно deny-окно (ручной синк при manualSync: true) ──> РАЗРЕШЕНО
    └── Нет блокирующих окон ──> Переход к Этапу 7
                       │
                       ▼
    [Этап 7: Применение манифестов (Impersonation)]
    Сконфигурирован ли destinationServiceAccounts для целевого namespace?
    ├── ДА  ──> Запрос к k8s API отправляется с заголовком impersonation указанного SA
    └── НЕТ ──> Запрос выполняется с правами контроллера Argo CD (cluster-admin)
```

### Разделение ответственности: RBAC против AppProject

В инфраструктуре DevOps/SRE критически важно понимать границу между глобальным RBAC и AppProject:

- **Глобальный RBAC (`argocd-rbac-cm`):** Отвечает на вопрос **«КТО и ЧТО может нажимать в интерфейсе/API Argo CD?»** (например, «группа `developers` может вызывать `sync` для приложений `team-alpha/*`»).
- **AppProject Restrictions:** Отвечает на вопрос **«ЧТО допустимо физически деплоить в кластеры от имени этого проекта?»** (какие репозитории, в какие неймспейсы, какие типы ресурсов).
- **Связка через Project Roles:** Позволяет децентрализовать политики — команда платформы делегирует проект владельцам, которые сами управляют проектными ролями и сервисными токенами для CI/CD внутри своего `AppProject`.

### Жизненный цикл и финализатор `resources-finalizer`

При удалении манифеста `AppProject`:
- Если на проекте установлен финализатор `resources-finalizer.argocd.argoproj.io`, контроллер **запрещает удаление проекта**, пока в системе существуют `Application`, ссылающиеся на этот проект.
- Если удалить проект без финализатора при существующих приложениях, приложения переходят в статус ошибки валидации (`ComparisonError: application project '<name>' not found`), и управление их состоянием блокируется.

---

## Практические сценарии

### Сценарий 1: Проект для команды разработки с сервисными токенами CI/CD

**Контекст:** Команда разработки сервисов `billing` должна иметь возможность деплоить свои приложения в пространства имен `billing-dev` и `billing-qa` кластера. Разработчикам и пайплайну CI/CD (GitLab Runner) запрещено создавать кластерные объекты (`ClusterRole`, `Namespace`), запрещено управлять объектами `ResourceQuota` и `LimitRange`, а для деплоя из CI/CD используется локальный JWT-токен с минимальными правами.

#### Манифест AppProject

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-billing
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: "Проект сервисов биллинга: окружения dev и qa"
  
  # Разрешены только корпоративные репозитории биллинга
  sourceRepos:
    - "https://git.internal.corp/billing/*"
    - "https://helm.internal.corp/charts"

  # Разрешен деплой только в назначенные неймспейсы локального кластера
  destinations:
    - server: https://kubernetes.default.svc
      namespace: billing-dev
    - server: https://kubernetes.default.svc
      namespace: billing-qa

  # Запрет любых кластерных ресурсов
  clusterResourceWhitelist: []

  # Разрешенные типы ресурсов приложений
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: "apps"
      kind: StatefulSet
    - group: ""
      kind: Service
    - group: ""
      kind: ConfigMap
    - group: ""
      kind: Secret
    - group: "networking.k8s.io"
      kind: Ingress
    - group: "batch"
      kind: Job
    - group: "batch"
      kind: CronJob
    - group: "autoscaling"
      kind: HorizontalPodAutoscaler

  # Явный запрет критичных для инфраструктуры квот и сетевых политик платформы
  namespaceResourceBlacklist:
    - group: ""
      kind: ResourceQuota
    - group: ""
      kind: LimitRange

  # Роли проекта для интеграции с CI/CD и SSO разработчиков
  roles:
    # 1. Роль для пайплайна GitLab CI / Jenkins
    - name: cicd-deployer
      description: "Сервисная роль CI/CD для запуска синхронизации и проверки статуса"
      policies:
        - p, proj:team-billing:cicd-deployer, applications, get, team-billing/*, allow
        - p, proj:team-billing:cicd-deployer, applications, sync, team-billing/*, allow
        - p, proj:team-billing:cicd-deployer, applications, action/*, team-billing/*, allow

    # 2. Роль для разработчиков (привязка к корпоративной группе SSO)
    - name: developer
      description: "Разработчики биллинга: чтение, просмотр логов и перезапуск подов"
      policies:
        - p, proj:team-billing:developer, applications, get, team-billing/*, allow
        - p, proj:team-billing:developer, logs, get, team-billing/*, allow
        - p, proj:team-billing:developer, exec, create, team-billing/*, allow
      groups:
        - "billing-devs-group"
```

#### Выпуск и валидация JWT-токена для CI/CD

Создание служебного токена с временем жизни 180 дней для передачи в CI/CD переменную `ARGOCD_AUTH_TOKEN`:

```bash
# 1. Генерация токена для роли cicd-deployer
argocd proj role create-token team-billing cicd-deployer --expires-in 4320h
# → eyJhbGciOiJSUzI1NiIsImtpZCI6... (вывод JWT-токена)

# 2. Проверка прав выданного токена через RBAC can
argocd admin settings rbac can proj:team-billing:cicd-deployer sync applications 'team-billing/billing-service'
# → Yes

argocd admin settings rbac can proj:team-billing:cicd-deployer delete applications 'team-billing/billing-service'
# → No
```

---

### Сценарий 2: Production-проект с жестким контролем, запретом Secret и Sync Windows

**Контекст:** Production-окружение финансовой платформы. Деплой разрешен только из защищенных релизных репозиториев. Для защиты от человеческого фактора и аварий внедрены:
1. Запрет на хранение открытых `Secret` внутри GitOps (используется Vault/SealedSecrets, управляемые отдельным оператором).
2. Запрет изменений в выходные дни и в ночное время (Sync Windows `deny`).
3. Разрешение экстренного ручного синка инженерам SRE (`manualSync: true`).

#### Манифест AppProject

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: platform-production
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: "Production контур высокой надежности"
  
  sourceRepos:
    - "https://git.internal.corp/releases/production.git"
    - "https://helm.internal.corp/charts/stable"

  destinations:
    - name: k8s-prod-dc1
      namespace: prod-apps
    - name: k8s-prod-dc2
      namespace: prod-apps

  # Кластерные ресурсы запрещены полностью
  clusterResourceWhitelist: []

  # Разрешенные типы приложений
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: "apps"
      kind: StatefulSet
    - group: ""
      kind: Service
    - group: ""
      kind: ConfigMap
    - group: "networking.k8s.io"
      kind: Ingress
    - group: "autoscaling"
      kind: HorizontalPodAutoscaler
    - group: "policy"
      kind: PodDisruptionBudget

  # Безопасность: запрет управления Secret через GitOps (защита от утечек)
  namespaceResourceBlacklist:
    - group: ""
      kind: Secret

  # Окна синхронизации (Sync Windows)
  syncWindows:
    # 1. Запрет автоматической и плановой синхронизации в выходные дни (сб, вс)
    - kind: deny
      schedule: "0 0 * * 6,0"
      duration: 24h
      applications:
        - "*"
      timeZone: "Europe/Moscow"
      manualSync: true  # Дежурный SRE может выполнить ручной sync при инциденте

    # 2. Запрет деплоя в нерабочее время (ежедневно с 19:00 до 09:00)
    - kind: deny
      schedule: "0 19 * * 1-5"
      duration: 14h
      applications:
        - "*"
      timeZone: "Europe/Moscow"
      manualSync: true

  # Роль дежурного инженера SRE
  roles:
    - name: sre-oncall
      description: "Дежурные SRE с правом синхронизации и отката"
      policies:
        - p, proj:platform-production:sre-oncall, applications, get, platform-production/*, allow
        - p, proj:platform-production:sre-oncall, applications, sync, platform-production/*, allow
        - p, proj:platform-production:sre-oncall, applications, rollback, platform-production/*, allow
      groups:
        - "sre-core-team"
```

#### Проверка состояния окон синхронизации через CLI

```bash
# Просмотр списка настроенных окон для проекта
argocd proj windows list platform-production
# → ID  STATUS  KIND  SCHEDULE        DURATION  APPLICATIONS  NAMESPA  MANUAL
# → 0   Active  deny  0 0 * * 6,0     24h       *             *        true
# → 1   Active  deny  0 19 * * 1-5    14h       *             *        true

# Проверка влияния окна на статус приложения
argocd app get production-billing-api -n argocd | grep -A 2 -i "Sync Window"
# → Sync Window: Deny window active (ID: 1). Manual sync is allowed.
```

---

### Сценарий 3: Детекция бесхозных ресурсов (Orphaned Resources Monitoring)

**Контекст:** В пространстве имен `prod-services` часто накапливаются ручные артефакты, тестовые ConfigMap или старые Deployment, созданные системными администраторами вручную в обход GitOps. Необходимо включить мониторинг с генерацией предупреждений в UI/метриках, исключив при этом системные ресурсы, генерируемые оператором Ingress или HPA.

#### Манифест AppProject

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: services-monitored
  namespace: argocd
spec:
  description: "Проект с контролем чистоты целевых namespace"
  sourceRepos:
    - "https://git.internal.corp/services/*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: prod-services

  # Включение отслеживания бесхозных ресурсов
  orphanedResources:
    warn: true  # Отображать предупреждение в UI и выставлять метрику argocd_app_info
    ignore:
      # Игнорировать системные ConfigMap, генерируемые контроллерами
      - group: ""
        kind: ConfigMap
        name: "kube-root-ca.crt"
      # Игнорировать EndpointSlice и Endpoints, создаваемые сервисами автоматически
      - group: "discovery.k8s.io"
        kind: EndpointSlice
      - group: ""
        kind: Endpoints
      # Игнорировать автоматически созданные ReplicaSet
      - group: "apps"
        kind: ReplicaSet
```

#### Проверка обнаруженных бесхозных ресурсов через CLI

```bash
# Получение статуса обнаруженных бесхозных объектов в проекте
kubectl get appproject services-monitored -n argocd -o jsonpath='{.status.orphanedResources}'
# → [{"group":"apps","kind":"Deployment","name":"legacy-debug-pod","namespace":"prod-services"}]
```

---

### Сценарий 4: Multi-Cluster изоляция и Project-Scoped кластеры

**Контекст:** В инфраструктуре присутствуют закрытые контуры: кластер баз данных `k8s-db-secure` и кластер общего назначения `k8s-general`. Необходимо гарантировать, что приложения проекта `secure-data` могут использовать только строго выделенный кластер баз данных, а администраторы проекта не смогут ошибочно направить деплой в общий кластер.

#### Манифест Секрета кластера с Project Scope

Секрет подключения кластера помечается лейблом проекта `argocd.argoproj.io/project: secure-data`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cluster-k8s-db-secure
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
    # Привязка кластера строго к проекту secure-data
    argocd.argoproj.io/project: secure-data
type: Opaque
stringData:
  name: k8s-db-secure
  server: https://10.100.20.10:6443
  config: |
    {
      "bearerToken": "kubeconfig-token-for-db-cluster",
      "tlsClientConfig": {
        "insecure": false,
        "caData": "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0t..."
      }
    }
```

#### Манифест AppProject с блокировкой общекластерных подключений

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: secure-data
  namespace: argocd
spec:
  description: "Проект для работы с изолированным кластером баз данных"
  sourceRepos:
    - "https://git.internal.corp/db-deployments/*"

  # Ограничение: разрешено использовать ТОЛЬКО кластеры, помеченные для этого проекта
  permitOnlyProjectScopedClusters: true
  # Ограничение: разрешено использовать ТОЛЬКО репозитории с меткой проекта
  permitOnlyProjectScopedRepositories: true

  destinations:
    - name: k8s-db-secure
      namespace: db-instances
    - name: k8s-db-secure
      namespace: db-backups
```

---

### Сценарий 5: Безопасный деплой через имперсонацию ServiceAccount (`destinationServiceAccounts`)

**Контекст:** По умолчанию `argocd-application-controller` обращается к API-серверу целевого кластера с правами своего сервисного аккаунта (часто обладающего широкими правами `cluster-admin`). В концепции Zero Trust и Principle of Least Privilege тенант `analytics-team` не должен иметь возможности повысить привилегии. Для этого на уровне AppProject настраивается автоматическая имперсонация локального ServiceAccount `analytics-deployer`.

#### Предварительная настройка ServiceAccount и RBAC в целевом namespace

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: analytics-deployer
  namespace: analytics
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: analytics-deployer-role
  namespace: analytics
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets"]
    verbs: ["*"]
  - apiGroups: [""]
    resources: ["services", "configmaps"]
    verbs: ["*"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: analytics-deployer-binding
  namespace: analytics
subjects:
  - kind: ServiceAccount
    name: analytics-deployer
    namespace: analytics
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: analytics-deployer-role
```

#### Манифест AppProject с `destinationServiceAccounts`

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: analytics-team
  namespace: argocd
spec:
  description: "Команда аналитики с ограниченными правами деплоя через SA"
  sourceRepos:
    - "https://git.internal.corp/analytics/*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: analytics

  # Контроллер Argo CD при синхронизации имперсонирует указанный ServiceAccount
  destinationServiceAccounts:
    - server: https://kubernetes.default.svc
      namespace: analytics
      defaultServiceAccount: analytics-deployer

  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: "apps"
      kind: StatefulSet
    - group: ""
      kind: Service
    - group: ""
      kind: ConfigMap
```

При попытке приложения задеплоить `ClusterRoleBinding` или `Ingress` операция будет отклонена не только проверкой AppProject, но и самим Kubernetes API, так как `analytics-deployer` не имеет прав на создание данных объектов.

---

### Сценарий 6: Applications-in-any-Namespace и делегирование создания через `sourceNamespaces`

**Контекст:** В крупных командах разработчикам не предоставляется доступ к namespace `argocd`. Тенанты работают в собственных пространствах имен (например, `tenant-fintech`), где создают манифесты `Application` самостоятельно (например, через Helm или Kustomize). AppProject должен разрешить признание приложений, созданных внутри `tenant-fintech`.

#### Манифест AppProject

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: fintech-tenant
  namespace: argocd
spec:
  description: "Тенант Fintech с децентрализованным созданием Application"
  
  # Разрешаем контроллеру обрабатывать объекты Application из указанного namespace
  sourceNamespaces:
    - tenant-fintech

  sourceRepos:
    - "https://git.internal.corp/fintech/*"

  destinations:
    - server: https://kubernetes.default.svc
      namespace: fintech-dev
    - server: https://kubernetes.default.svc
      namespace: fintech-stage
```

#### Манифест Application, создаваемый разработчиком в своем namespace

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payment-gateway
  namespace: tenant-fintech  # Создано в tenant-неймспейсе, а не в argocd!
spec:
  project: fintech-tenant
  source:
    repoURL: https://git.internal.corp/fintech/payment.git
    targetRevision: main
    path: k8s/stage
  destination:
    server: https://kubernetes.default.svc
    namespace: fintech-stage
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

---

### Сценарий 7: Hardening дефолтного проекта (`default`)

**Внимание (Security Risk):** Стандартный проект `default`, создаваемый при установке Argo CD, содержит конфигурацию `sourceRepos: ['*']` и `destinations: [{server: '*', namespace: '*'}]`. Любой пользователь с базовыми правами на создание приложений может использовать проект `default` и задеплоить привилегированные поды в любой namespace кластера.

#### Процедура изоляции проекта `default`

Патчим объект `default`, очищая все источники и назначения:

```bash
# Блокировка репозиториев и назначений в дефолтном проекте
kubectl patch appproject default -n argocd --type merge -p '
spec:
  description: "Locked default project. Do not use for workloads."
  sourceRepos: []
  destinations: []
  clusterResourceWhitelist: []
  namespaceResourceWhitelist: []
'
# → appproject.argoproj.io/default patched
```

#### Проверка результата

```bash
kubectl get appproject default -n argocd -o yaml | grep -A 5 "spec:"
# → spec:
# →   clusterResourceWhitelist: []
# →   description: Locked default project. Do not use for workloads.
# →   destinations: []
# →   namespaceResourceWhitelist: []
# →   sourceRepos: []
```

---

## Операции и команды

### Сводная таблица команд управления `AppProject`

| Действие | Команда `argocd CLI` | Эквивалент `kubectl` |
| :--- | :--- | :--- |
| **Список проектов** | `argocd proj list` | `kubectl get appprojects -n argocd` |
| **Детали проекта** | `argocd proj get <name>` | `kubectl get appproject <name> -n argocd -o yaml` |
| **Создание проекта** | `argocd proj create <name> --description "..."` | `kubectl apply -f project.yaml` |
| **Удаление проекта** | `argocd proj delete <name>` | `kubectl delete appproject <name> -n argocd` |
| **Добавить репозиторий** | `argocd proj add-source <name> <url>` | Добавление в `.spec.sourceRepos` |
| **Удалить репозиторий** | `argocd proj remove-source <name> <url>` | Удаление из `.spec.sourceRepos` |
| **Добавить назначение** | `argocd proj add-destination <name> <server> <ns>` | Добавление в `.spec.destinations` |
| **Удалить назначение** | `argocd proj remove-destination <name> <server> <ns>` | Удаление из `.spec.destinations` |
| **Разрешить кластерный тип** | `argocd proj allow-cluster-resource <name> <group> <kind>` | Добавление в `.spec.clusterResourceWhitelist` |
| **Запретить кластерный тип** | `argocd proj deny-cluster-resource <name> <group> <kind>` | Добавление в `.spec.clusterResourceBlacklist` |
| **Разрешить тип в namespace** | `argocd proj allow-namespace-resource <name> <group> <kind>` | Добавление в `.spec.namespaceResourceWhitelist` |
| **Запретить тип в namespace** | `argocd proj deny-namespace-resource <name> <group> <kind>` | Добавление в `.spec.namespaceResourceBlacklist` |
| **Создать роль проекта** | `argocd proj role create <name> <role-name>` | Добавление роли в `.spec.roles` |
| **Добавить политику роли** | `argocd proj role add-policy <name> <role-name> -a <action> -o <obj> -p <allow>` | Редактирование `.spec.roles[].policies` |
| **Привязать SSO-группу** | `argocd proj role add-group <name> <role-name> <group>` | Добавление в `.spec.roles[].groups` |
| **Сгенерировать JWT-токен** | `argocd proj role create-token <name> <role-name>` | Генерация подписанного токена через API |
| **Отозвать JWT-токен** | `argocd proj role delete-token <name> <role-name> <id>` | Удаление ID из `.spec.roles[].jwtTokens` |
| **Добавить Sync Window** | `argocd proj windows add <name> --kind <allow/deny> --schedule "..." --duration <dur>` | Редактирование `.spec.syncWindows` |

---

## Диагностика и устранение неисправностей

### Типичные ошибки и способы решения

| Симптом / Текст ошибки | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `application repo <url> is not permitted in project '<proj>'` | Репозиторий приложения отсутствует в `spec.sourceRepos` проекта. | `argocd proj get <proj> -o yaml \| grep -A 10 sourceRepos` | Добавить точный URL или маску репозитория командой `argocd proj add-source <proj> <url>`. |
| `application destination {server: ..., namespace: ...} is not permitted in project '<proj>'` | Кластер или namespace назначения не совпадают ни с одним правилом в `spec.destinations`. | Сравнить поля `spec.destination` в `Application` и `spec.destinations` в `AppProject`. | Добавить назначение: `argocd proj add-destination <proj> <server> <namespace>`. |
| `resource <group>:<kind> is not permitted in project '<proj>'` | Попытка создания ресурса кластерного уровня (например, `Namespace` или `ClusterRole`), когда `clusterResourceWhitelist` пуст. | Проверить состав манифестов чарта/репозитория: `kubectl get app <app> -o jsonpath='{.status.resources}'` | Явно добавить ресурс в белый список: `argocd proj allow-cluster-resource <proj> <group> <kind>`. |
| `resource <group>:<kind> is explicitly blacklisted in project '<proj>'` | Тип ресурса внесен в `namespaceResourceBlacklist` или `clusterResourceBlacklist`. | Проверить blacklist: `kubectl get appproject <proj> -o jsonpath='{.spec.namespaceResourceBlacklist}'` | Если деплой легитимен, удалить ресурс из blacklist. Если нет — исключить манифест из Git. |
| `Application '<app>' is outside of the permitted source namespaces in project '<proj>'` | Приложение создано в namespace тенанта, но этот неймспейс не добавлен в `spec.sourceNamespaces`. | Проверить namespace самого объекта `Application`: `kubectl get app -A \| grep <app>` | Внести неймспейс в `spec.sourceNamespaces` AppProject или переместить манифест Application в `argocd`. |
| `cannot sync: sync is disabled by sync window` | Текущий момент времени совпадает с активным `deny`-окном в `spec.syncWindows`. | `argocd proj windows list <proj>` | Дождаться окончания окна, скорректировать расписание или использовать ручной синк (если включен `manualSync: true`). |
| `cannot delete appproject: project is referenced by applications` | На проекте установлен финализатор `resources-finalizer`, и в системе есть привязанные приложения. | `argocd app list --project <proj>` | Удалить или перепривязать к другому проекту все связанные приложения перед удалением проекта. |
| `token is invalid or expired` | JWT-токен роли проекта истек по времени (`exp`) или был отозван администратором. | `kubectl get appproject <proj> -o jsonpath='{.spec.roles[?(@.name=="<role>")].jwtTokens}'` | Выпустить новый токен: `argocd proj role create-token <proj> <role> --expires-in <hours>`. |

### Инструменты трассировки и логирования

#### 1. Проверка правил RBAC и политик проекта

Команда `argocd admin settings rbac can` позволяет симулировать запросы от имени ролей проекта:

```bash
# Проверка: может ли роль cicd-deployer выполнить sync конкретного приложения
argocd admin settings rbac can proj:team-billing:cicd-deployer sync applications 'team-billing/billing-api'
# → Yes

# Проверка: может ли роль developer удалить приложение
argocd admin settings rbac can proj:team-billing:developer delete applications 'team-billing/billing-api'
# → No
```

#### 2. Проверка журналов контроллера на блокировку AppProject

При отклонении синхронизации контроллер логирует точные причины блокировки:

```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=200 | grep -E "not permitted in project|is blacklisted|sync window"
```

#### 3. Мониторинг метрик Prometheus

Argo CD экспортирует метрики состояния проектов и окон:

- `argocd_app_sync_window_error{project="<proj>"}` — количество ошибок вычисления окон синхронизации (например, синтаксическая ошибка в cron-расписании).
- `argocd_app_sync_total{project="<proj>", phase="Failed"}` — счетчик неудачных синхронизаций в разрезе проекта.

---

## Лучшие практики (Best Practices)

1. **Hardening дефолтного проекта:** Всегда блокируйте проект `default` сразу после установки Argo CD. Очищайте в нем `sourceRepos` и `destinations`, чтобы исключить деплой без явного назначения проекта.
2. **Принцип наименьших привилегий (Least Privilege):**
   - Никогда не используйте маску `*` в `sourceRepos` и `destinations` в production.
   - Запрещайте кластерные ресурсы (`clusterResourceWhitelist: []`) для всех проектов прикладных команд.
   - Исключайте `Secret` через `namespaceResourceBlacklist`, если секреты доставляются через внешние хранилища (HashiCorp Vault, SOPS, External Secrets Operator).
3. **Обязательные финализаторы:** Всегда включайте `finalizers: [resources-finalizer.argocd.argoproj.io]` в манифестах AppProject, чтобы исключить случайное удаление проекта с «зависанием» управляемых приложений.
4. **Управление токенами CI/CD:**
   - Не создавайте токены с бесконечным сроком действия. Устанавливайте `--expires-in` не более 90–180 дней и регламентируйте процедуру ротации.
   - При компрометации токена немедленно удаляйте его ID через `argocd proj role delete-token`.
5. **Имперсонация через `destinationServiceAccounts`:** В критичных кластерах настраивайте имперсонацию конкретных ServiceAccount тенанта. Это гарантирует, что контроллер Argo CD не применит манифесты с привилегиями кластерного администратора, если разработчик случайно добавит недопустимый ресурс.
6. **Грамотная настройка окон (Sync Windows):** При настройке `deny`-окон всегда оставляйте флаг `manualSync: true` для production-проектов, чтобы дежурные инженеры SRE могли доставить emergency hotfix во время инцидента.

---

## Дополнительная информация

### См. также

- [Мультитенантность в Argo CD](./argocd_multi_tenancy.md) — Паттерны project-per-team, tenant namespaces, архитектура разделяемого контроллера.
- [RBAC: модель доступа и политики](./argocd_rbac_deep.md) — Настройка `argocd-rbac-cm`, Casbin-синтаксис, глобальные и проектные права.
- [Sync Windows: сценарии и настройка](./synchronization/scenarios/sync_windows.md) — Детальное руководство по регламентным окнам, расписаниям cron и ручному синку.
- [Безопасность и hardening](./argocd_security_hardening.md) — Сетевые политики, подпись коммитов GPG, аудит и защита контроллеров.
- [Установка и первичная настройка](./argocd_installation_and_setup.md) — Базовое развертывание компонентов Argo CD.
- [Удаление и очистка ресурсов](./argocd_deletion_and_cleanup.md) — Cascading deletion, finalizers и очистка зависших объектов.

### Ссылки

- [Официальная документация Argo CD: Projects Declarative Setup](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#projects)
- [Официальная документация Argo CD: Project Scoped Roles](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/#project-scoped-roles)
- [Официальная документация Argo CD: Sync Windows](https://argo-cd.readthedocs.io/en/stable/operator-manual/sync_windows/)
