# Argo CD: Мультитенантность — паттерны изоляции, project-per-team и tenant namespace isolation

**Актуально для:** Argo CD v3.5.x (v3.5.0–v3.5.4+; проверено против релиза v3.5.4 от октября 2026 года; Kubernetes 1.28–1.32+; bare-metal / on-premise)

> **Актуальность (2026):** Мультитенантность в Argo CD v3.5.x реализуется через эшелонированную модель защиты (Defense-in-Depth): разграничение прав и областей видимости в `AppProject` (ограничения репозиториев, кластеров, типов ресурсов, окон синхронизации), ролевую модель RBAC (глобальные роли и роли проектов с гранулярным контролем `update`/`delete` суб-ресурсов), корпоративный SSO (OIDC/LDAP через Keycloak или Dex) и инфраструктурную изоляцию в Kubernetes (Namespace, NetworkPolicy, ResourceQuota, LimitRange, Pod Security Admission). Ключевые возможности v3.5: децентрализованное управление манифестами через `sourceNamespaces` (Applications-in-any-Namespace), имперсонация сервисных аккаунтов через `destinationServiceAccounts`, проверка криптографической подлинности коммитов `sourceIntegrity` (полноценная замена устаревшего `signatureKeys`), изоляция проектных кластеров `permitOnlyProjectScopedClusters` и репозиториев `permitOnlyProjectScopedRepositories`, шардирование контроллеров по кластерам и тенантам (`controller.sharding.algorithm`), а также запуск полностью изолированных экземпляров Argo CD в режиме `namespace-install`.

---

## Определения

| Термин | Определение |
| :--- | :--- |
| **Мультитенантность (Multi-tenancy)** | Архитектурная модель, при которой единая инсталляция Argo CD обслуживает множество независимых команд, сервисов или инфраструктурных контуров с гарантированной изоляцией конфигураций, доступов и ресурсов. |
| **Тенант (Tenant)** | Команда разработки, продуктовое подразделение или проект, обладающий изолированным пространством имен в Kubernetes и собственным скоупом управления в Argo CD. |
| **AppProject** | Custom Resource (`argoproj.io/v1alpha1`), задающий логические границы безопасности: разрешенные Git/Helm/OCI-репозитории, целевые кластеры и пространства имен, белые и черные списки видов ресурсов K8s, проектные роли и регламентные окна синхронизации. |
| **Project-per-team** | Архитектурный паттерн, при котором каждому тенанту выделяется собственный `AppProject` с уникальным набором ограничений, ролей и синхронизационных окон. |
| **Project-per-environment** | Паттерн разделения сред выполнения (development, staging, production) по независимым проектам `AppProject` с ужесточением политик безопасности по мере продвижения к production. |
| **Tenant Namespace** | Пространство имен Kubernetes, закрепленное за тенантом. Обеспечивает изоляцию рабочих нагрузок на уровне ядра K8s посредством NetworkPolicy, ResourceQuota и RBAC. |
| **Shared Controller** | Единый разделяемый экземпляр `argocd-application-controller`, обрабатывающий задачи сверки для всех тенантов с логическим разделением через `AppProject`. |
| **Applications-in-any-Namespace** | Архитектурный режим (Argo CD v3.x), позволяющий тенантам объявлять ресурсы `Application` в собственных пространствах имен без доступа к системному namespace `argocd`. Требует активации через `application.namespaces` в `argocd-cmd-params-cm` и разрешения в `AppProject.spec.sourceNamespaces`. |
| **Namespace-scoped Argo CD** | Режим развертывания Argo CD (`namespace-install.yaml`), при котором компоненты контроллера и сервера функционируют с правами локального namespace (без `ClusterRole` и доступа cluster-admin) и управляют внешними целевыми кластерами. |
| **destinationServiceAccounts** | Механизм имперсонации Kubernetes ServiceAccount в целевом кластере/namespace. Контроллер Argo CD при синхронизации манифестов действует от имени указанного SA тенанта с его локальными правами RBAC, исключая использование избыточных прав контроллера. |
| **Project-scoped ресурсы** | Секреты репозиториев (`repository`) и кластеров (`cluster`), помеченные меткой `project: <имя>`, доступные только приложениям указанного проекта. Позволяет организовать безопасный self-service без вмешательства системных администраторов. |
| **Global Projects** | Механизм наследования политик, при котором дочерние проекты автоматически получают базовые правила (whitelist/blacklist ресурсов, syncWindows) от базового `AppProject` на основе `labelSelector` в ConfigMap `argocd-cm`. |
| **Source Integrity** | Механизм проверки подлинности источников манифестов (Argo CD v3.5+), пришедший на смену устаревшему полю `signatureKeys`. Валидирует GPG-подписи коммитов перед запуском генерации и синхронизации. |
| **Controller Sharding** | Горизонтальное масштабирование `argocd-application-controller` путем разделения пула обслуживаемых кластеров и приложений между несколькими репликами (шардами) StatefulSet. |
| **RBAC Fine-grained Permissions** | Гранулярные правила авторизации (введены в v3.0+, стабилизированы в v3.5+), позволяющие разграничивать доступ к отдельным суб-ресурсам и действиям внутри приложения (например, разрешение на перезапуск подов `delete/*/Pod/*/*` при запрете на изменение спецификации приложения). |

---

## Архитектура и базовые концепции

### Четырёхуровневая модель Defense-in-Depth

Изоляция тенантов в Argo CD строится по принципу эшелонированной обороны (Defense-in-Depth). Запрос на управление или синхронизацию последовательно проходит четыре независимых барьера проверки:

```text
Запрос (UI / CLI / REST API / GitOps-триггер)
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Аутентификация (Identity & SSO)                          │
│    Проверка подлинности субъекта: Keycloak, Dex, OIDC,     │
│    локальный аккаунт, подписанный JWT-токен API             │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Авторизация (RBAC Evaluation)                            │
│    Проверка прав субъекта на действие в Casbin:              │
│    Глобальные правила policy.csv + проектные роли (roles)   │
│    «Может ли инженер team-a выполнить sync приложения X?»   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Границы проекта (AppProject Boundaries)                  │
│    Проверка допустимости манифеста и окружения:             │
│    - Источник Git/Helm разрешен в sourceRepos?              │
│    - Кластер и Namespace входят в destinations?             │
│    - Виды ресурсов разрешены в Whitelist / не в Blacklist?  │
│    - Не блокируют ли операцию Sync Windows?                 │
│    - Валидна ли GPG-подпись коммита в sourceIntegrity?      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Исполнение в Kubernetes API (K8s API & Impersonation)     │
│    Применение манифестов в целевом кластере:                │
│    - Без имперсонации: от имени ServiceAccount контроллера  │
│    - С destinationServiceAccounts: от имени локального SA   │
│      тенанта (Kubernetes API возвращает 403 при выходе за   │
│      пределы назначенных тенанту прав RBAC)                 │
└─────────────────────────────────────────────────────────────┘
```

Каждый уровень решает свою строгую задачу:
- **Аутентификация** удостоверяет личность пользователя или пайплайна.
- **RBAC** определяет, **кто** имеет право запросить действие (`get`, `sync`, `create`, `delete`).
- **AppProject** определяет, **что именно** и **куда** разрешено доставлять декларативно.
- **destinationServiceAccounts** определяет, **с какими привилегиями в ядре Kubernetes** происходит материализация объектов.

---

### Архитектурные паттерны мультитенантности

В зависимости от требований к безопасности и масштабу инфраструктуры применяются следующие архитектурные схемы:

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ Схема 1: Shared Control Plane (Project-per-team + Applications-in-NS)    │
│                                                                         │
│  Argo CD Control Plane (namespace: argocd)                              │
│  ├── argocd-server                                                      │
│  ├── argocd-repo-server                                                 │
│  └── argocd-application-controller (sharded)                           │
│                                                                         │
│       │                              │                             │    │
│       │ watch CRs                    │ watch CRs                   │    │
│       ▼                              ▼                             ▼    │
│  ┌───────────────────────┐  ┌───────────────────────┐  ┌──────────────┐ │
│  │ Namespace: team-a-apps│  │ Namespace: team-b-apps│  │ ...          │ │
│  │ Application: backend  │  │ Application: frontend │  │              │ │
│  │ AppProject: team-a    │  │ AppProject: team-b    │  │              │ │
│  └───────────┬───────────┘  └───────────┬───────────┘  └──────────────┘ │
└──────────────┼──────────────────────────┼───────────────────────────────┘
               │ sync (via Impersonation) │ sync (via Impersonation)
               ▼                          ▼
 ┌───────────────────────────┐ ┌───────────────────────────┐
 │ Целевой Namespace:        │ │ Целевой Namespace:        │
 │ team-a-prod               │ │ team-b-prod               │
 │ NetworkPolicy / Quotas    │ │ NetworkPolicy / Quotas    │
 └───────────────────────────┘ └───────────────────────────┘
```

#### Сравнение моделей изоляции

| Паттерн | Степень изоляции | Нагрузка на Control Plane | Операционная сложность | Целевой сценарий использования |
| :--- | :--- | :--- | :--- | :--- |
| **Project-per-team (Shared)** | Логическая (Soft) | Низкая (единый контроллер) | Минимальная | Внутренние команды одной организации, доверенные разработчики. |
| **Applications-in-any-Namespace** | Логическая + Self-Service | Средняя (контроллер слушает несколько NS) | Средняя | Децентрализованный GitOps: команды сами создают Application CR в своих NS. |
| **Multi-controller Sharding** | Логическая (масштабируемая) | Оптимизированная (пул шардов) | Средняя | Крупные on-prem инсталляции (>1000 приложений, десятки кластеров). |
| **Namespace-scoped Argo CD** | Высокая (изоляция процессов) | Высокая (отдельные поды на тенанта) | Высокая | Враждебные тенанты, жесткие требования безопасности (PCI-DSS / гостайна). |
| **Dedicated Instance per Tenant** | Максимальная (Hard) | Наивысшая (N полных инсталляций) | Высокая (требует автоматизации) | Полная изоляция команд в разных физических или виртуальных кластерах. |

---

### Матрица механизмов изоляции и защиты

| Уровень стека | Механизм | Что защищает / ограничивает | Точка конфигурации |
| :--- | :--- | :--- | :--- |
| **Аутентификация** | SSO / OIDC (Keycloak / Dex) | Доступ в интерфейс и API Argo CD | ConfigMap `argocd-cm` (`oidc.config` / `dex.config`) |
| **Авторизация** | RBAC (`policy.csv`, роли) | Допустимые операции над сущностями Argo CD | ConfigMap `argocd-rbac-cm`, поле `.spec.roles` в `AppProject` |
| **Границы репозиториев** | `sourceRepos` | Запрет на использование чужих или недоверенных Git/Helm репозиториев | `AppProject.spec.sourceRepos` |
| **Границы кластеров и NS** | `destinations` | Запрет деплоя в чужие неймспейсы или инфраструктурные контуры | `AppProject.spec.destinations` |
| **Фильтрация ресурсов** | `namespaceResourceWhitelist` / `Blacklist` | Запрет создания привилегированных объектов (например, `Secret`, `RoleBinding`) | `AppProject.spec` |
| **Кластерные ресурсы** | `clusterResourceWhitelist` / `Blacklist` | Запрет создания `ClusterRole`, `CRD`, `Namespace`, `MutatingWebhookConfiguration` | `AppProject.spec` |
| **Область создания Application** | `sourceNamespaces` | Список неймспейсов, откуда разрешено принимать Application CR | `AppProject.spec.sourceNamespaces` + `argocd-cmd-params-cm` |
| **Имперсонация K8s API** | `destinationServiceAccounts` | Ограничение прав синхронизации правами сервисного аккаунта тенанта | `AppProject.spec.destinationServiceAccounts` + K8s RBAC |
| **Временные интервалы** | Sync Windows | Запрет автоматического или ручного деплоя в часы пиковой нагрузки / выходные | `AppProject.spec.syncWindows` |
| **Контроль подлинности** | `sourceIntegrity` | Проверка криптографической GPG-подписи коммитов в Git | `AppProject.spec.sourceIntegrity` |
| **Сетевая изоляция K8s** | `NetworkPolicy` | Блокировка межподового трафика между неймспейсами тенантов | Kubernetes `NetworkPolicy` в tenant namespace |
| **Лимиты ресурсов K8s** | `ResourceQuota` + `LimitRange` | Предотвращение исчерпания CPU, RAM, диска и дескрипторов etcd (Noisy Neighbor) | Kubernetes `ResourceQuota`, `LimitRange` |
| **Безопасность подов K8s** | Pod Security Standards (PSA) | Запрет привилегированных контейнеров, hostPath, hostNetwork | Метки namespace: `pod-security.kubernetes.io/enforce: restricted` |

---

## Практические сценарии

### Предварительные требования

Перед реализацией сценариев убедитесь в готовности окружения:
1. **Кластер Kubernetes:** версия v1.28–v1.32+ (on-premise / bare-metal).
2. **Установленный Argo CD:** версия v3.5.x (v3.5.4+) в namespace `argocd` (см. [Установка и настройка](./argocd_installation_and_setup.md)).
3. **Утилиты управления:** настроенные CLI `kubectl` и `argocd` с правами администратора.
4. **Смежные знания:**
   - Модель прав доступа и правила Casbin: [RBAC](./argocd_rbac_deep.md).
   - Детальная спецификация полей проекта: [AppProject](./argocd_appproject_deep.md).
   - Расписания окон блокировок: [Sync Windows](./synchronization/scenarios/sync_windows.md).
   - Базовые концепции мультитенантности K8s: [Kubernetes Multi-tenancy](../../Kubernetes/Concepts/multi-tenancy.md).

---

### Сценарий 1: Паттерн Project-per-team (Изоляция команд разработки)

**Контекст:** В организации две команды разработки — `backend` и `frontend`. Команды должны иметь доступ только к своим приложениям, репозиториям и пространствам имен. Администраторы платформы (SRE) имеют глобальный доступ.

#### 1. AppProject для команды Backend

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: backend
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: "Проект для сервисов команды Backend"
  # Разрешены только репозитории бэкенда
  sourceRepos:
    - "https://git.corp.internal/backend/*"
    - "https://helm.corp.internal/charts/backend/*"
  # Разрешен деплой только в неймспейсы бэкенда
  destinations:
    - server: https://kubernetes.default.svc
      namespace: "backend-*"
  # Полный запрет на любые кластерные ресурсы
  clusterResourceWhitelist: []
  # Белый список разрешенных пространственных ресурсов
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
  # Делегирование создания Application из пространства имен разработчиков
  sourceNamespaces:
    - "backend-apps"
  # Имперсонация выделенного ServiceAccount при деплое в production
  destinationServiceAccounts:
    - server: https://kubernetes.default.svc
      namespace: backend-prod
      defaultServiceAccount: backend-deployer
  # Проектные роли
  roles:
    - name: developer
      description: "Разработчик команды Backend"
      policies:
        - p, proj:backend:developer, applications, get, backend/*, allow
        - p, proj:backend:developer, applications, sync, backend/*, allow
        - p, proj:backend:developer, applications, create, backend/*, allow
      groups:
        - "sso-backend-devs"
    - name: ci-deployer
      description: "Автоматизация CI/CD для выкатки релизов"
      policies:
        - p, proj:backend:ci-deployer, applications, get, backend/*, allow
        - p, proj:backend:ci-deployer, applications, sync, backend/*, allow
      jwtTokens:
        - iat: 1770000000
```

#### 2. AppProject для команды Frontend

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: frontend
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: "Проект для SPA и статических сервисов Frontend"
  sourceRepos:
    - "https://git.corp.internal/frontend/*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: "frontend-*"
  clusterResourceWhitelist: []
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: ""
      kind: Service
    - group: "networking.k8s.io"
      kind: Ingress
    - group: ""
      kind: ConfigMap
  # Черный список: фронтенд не должен управлять Secret напрямую через Git
  namespaceResourceBlacklist:
    - group: ""
      kind: Secret
  roles:
    - name: developer
      policies:
        - p, proj:frontend:developer, applications, get, frontend/*, allow
        - p, proj:frontend:developer, applications, sync, frontend/*, allow
      groups:
        - "sso-frontend-devs"
```

#### 3. Настройка глобального RBAC в ConfigMap `argocd-rbac-cm`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  # Принцип наименьших привилегий: все неавторизованные пользователи получают readonly
  policy.default: role:readonly
  policy.csv: |
    # Маппинг проектных ролей на группы корпоративного OIDC
    g, sso-backend-devs, proj:backend:developer
    g, sso-frontend-devs, proj:frontend:developer

    # Глобальная роль SRE с полным доступом ко всем проектам и приложениям
    p, role:sre, applications, *, */*, allow
    p, role:sre, clusters, *, *, allow
    p, role:sre, repositories, *, *, allow
    p, role:sre, logs, get, */*, allow
    p, role:sre, exec, create, */*, allow
    g, sso-sre-engineers, role:sre
  scopes: "[groups]"
```

**Валидация применения:**
```bash
# Проверка валидности синтаксиса политик
argocd admin settings rbac validate
# → result: RBAC configuration is valid

# Тестирование прав пользователя frontend на чужой проект backend
argocd admin settings rbac can role:frontend-dev sync applications 'backend/api'
# → result: no
```

---

### Сценарий 2: Паттерн Project-per-environment с дифференцированными окнами синхронизации

**Контекст:** Разделение контуров `dev`, `staging` и `production` с запретом неконтролируемых изменений в рабочее время и выходные дни.

```yaml
# 1. Среда разработки: максимальная свобода, автоматический синк в любое время
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: dev-env
  namespace: argocd
spec:
  description: "Контур разработки"
  sourceRepos: ["*"]
  destinations:
    - server: https://kubernetes.default.svc
      namespace: "*-dev"
  namespaceResourceWhitelist:
    - group: "*"
      kind: "*"
  roles:
    - name: developer
      policies:
        - p, proj:dev-env:developer, applications, *, dev-env/*, allow
      groups:
        - "developers-all"
---
# 2. Production: жесткие ограничения и запреты синхронизации
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: prod-env
  namespace: argocd
spec:
  description: "Боевой контур Production"
  sourceRepos:
    - "https://git.corp.internal/production-releases/*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: "*-prod"
  # Полный запрет на создание/изменение кластерных сущностей и манипуляцию секретами
  clusterResourceWhitelist: []
  namespaceResourceBlacklist:
    - group: ""
      kind: Secret
  roles:
    - name: release-manager
      policies:
        - p, proj:prod-env:release-manager, applications, get, prod-env/*, allow
        - p, proj:prod-env:release-manager, applications, sync, prod-env/*, allow
      groups:
        - "release-engineers"
  # Окна синхронизации: релизы разрешены только в будни с 10:00 до 17:00
  syncWindows:
    - kind: allow
      schedule: "0 10 * * 1-5"
      duration: 7h
      timeZone: "Europe/Moscow"
      applications:
        - "*"
    # Безусловный запрет деплоя в выходные дни (даже при ручной попытке)
    - kind: deny
      schedule: "0 0 * * 6,0"
      duration: 24h
      timeZone: "Europe/Moscow"
      manualSync: false
      applications:
        - "*"
```

---

### Сценарий 3: Харденинг дефолтного проекта (`default`)

**Контекст безопасности:** При стандартной установке проект `default` имеет настройки `sourceRepos: ['*']` и `destinations: [{server: '*', namespace: '*'}]`. Любой пользователь с базовыми правами на создание приложений может использовать `default` и развернуть привилегированный под в любой namespace.

#### Полная блокировка проекта `default`

```bash
# Применение манифеста с полным обнулением прав проекта default
kubectl apply -f - <<'EOF'
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: default
  namespace: argocd
spec:
  description: "LOCKED DEFAULT PROJECT. DO NOT USE. ALL WORKLOADS MUST USE DEDICATED APPPROJECT."
  sourceRepos: []
  destinations: []
  clusterResourceBlacklist:
    - group: "*"
      kind: "*"
  namespaceResourceBlacklist:
    - group: "*"
      kind: "*"
EOF
# → result: appproject.argoproj.io/default configured
```

**Проверка блокировки:**
```bash
# Попытка создания приложения в проекте default завершится ошибкой
argocd app create test-exploit \
  --project default \
  --repo https://git.corp.internal/test.git \
  --path . \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace kube-system
# → result: FAILED: application destination is not permitted in project 'default'
```

---

### Сценарий 4: Applications-in-any-Namespace (Децентрализованный GitOps)

**Контекст:** Разработчики тенанта работают исключительно в своем пространстве имен `team-a-apps`. Они должны самостоятельно объявлять манифесты `Application` через свои CI/CD-пайплайны или Git-репозитории, не имея доступа к namespace `argocd`.

#### Шаг 1: Активация мониторинга пространств имен в `argocd-cmd-params-cm`

По умолчанию Argo CD отслеживает CRD `Application` только в собственном namespace (`argocd`). Для включения мониторинга внешних неймспейсов системный администратор настраивает параметр `application.namespaces`:

```yaml
# Патч ConfigMap argocd-cmd-params-cm
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  # Список пространств имен (через запятую) или шаблон
  application.namespaces: "team-a-apps, team-b-apps"
```

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  application.namespaces: "team-a-apps, team-b-apps"
EOF
# → result: configmap/argocd-cmd-params-cm configured

# Перезапуск контроллера и сервера для применения изменений параметров
kubectl rollout restart deployment argocd-server -n argocd
kubectl rollout restart statefulset argocd-application-controller -n argocd
# → result: deployment.apps/argocd-server restarted
# → result: statefulset.apps/argocd-application-controller restarted
```

#### Шаг 2: Настройка RBAC в Kubernetes для доступа контроллера к неймспейсу тенанта

Контроллер `argocd-application-controller` и API-сервер `argocd-server` должны иметь права на чтение и обновление `Application` внутри `team-a-apps`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: argocd-application-manager
  namespace: team-a-apps
rules:
  - apiGroups: ["argoproj.io"]
    resources: ["applications", "appprojects"]
    verbs: ["get", "list", "watch", "update", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: argocd-application-manager-binding
  namespace: team-a-apps
subjects:
  - kind: ServiceAccount
    name: argocd-application-controller
    namespace: argocd
  - kind: ServiceAccount
    name: argocd-server
    namespace: argocd
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: argocd-application-manager
```

#### Шаг 3: Объявление разрешения в AppProject

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-a
  namespace: argocd
spec:
  description: "Проект team-a с поддержкой Applications-in-any-Namespace"
  sourceRepos:
    - "https://git.corp.internal/team-a/*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: team-a-prod
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: ""
      kind: Service
  # Ключевой параметр: разрешаем создание Application в namespace team-a-apps
  sourceNamespaces:
    - "team-a-apps"
```

#### Шаг 4: Создание Application тенантом внутри своего namespace

```yaml
# Манифест создается разработчиком в namespace team-a-apps!
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payment-service
  namespace: team-a-apps
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: team-a
  source:
    repoURL: "https://git.corp.internal/team-a/payment-service.git"
    targetRevision: main
    path: deploy/production
  destination:
    server: https://kubernetes.default.svc
    namespace: team-a-prod
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**Валидация:**
```bash
# Проверка регистрации приложения в namespace тенанта
kubectl get application -n team-a-apps
# → result: NAME              SYNC STATUS   HEALTH STATUS
# → result: payment-service   Synced        Healthy

# Проверка, что приложение отображается в Argo CD CLI
argocd app get team-a-apps/payment-service
# → result: Name:               team-a-apps/payment-service
# → result: Project:            team-a
# → result: Server:             https://kubernetes.default.svc
# → result: Namespace:          team-a-prod
# → result: Status:             Synced
```

---

### Сценарий 5: Имперсонация ServiceAccount (`destinationServiceAccounts`)

**Архитектурный контекст:** По умолчанию `argocd-application-controller` подключается к целевому кластеру под собственным ServiceAccount, обладающим широкими (часто кластерными) привилегиями. При ошибке в белом списке `AppProject` тенант может случайно применить объект, выходящий за рамки его зоны ответственности. 

Использование `destinationServiceAccounts` заставляет контроллер выполнять все вызовы к K8s API через механизм **Kubernetes API Impersonation** от имени сервисного аккаунта тенанта.

```text
argocd-application-controller
  │
  │ Запрос к K8s API с заголовком:
  │ Impersonate-User: system:serviceaccount:team-a-prod:team-a-deployer
  ▼
kube-apiserver
  │
  ├── Проверка: имеет ли контроллер право impersonate на этот SA?
  │   └── ДА
  │
  └── Проверка: имеет ли сам team-a-deployer право создать запрашиваемый ресурс?
      ├── ДА  ──> Ресурс создан
      └── НЕТ ──> 403 Forbidden (блокировка на уровне ядра K8s!)
```

#### 1. Создание ServiceAccount и RBAC тенанта в целевом namespace

```yaml
# В пространстве имен назначения team-a-prod
apiVersion: v1
kind: ServiceAccount
metadata:
  name: team-a-deployer
  namespace: team-a-prod
---
# Роль ограничивает действия тенанта ТОЛЬКО разрешенными ресурсами
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: team-a-deployer-role
  namespace: team-a-prod
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["services", "configmaps"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: team-a-deployer-binding
  namespace: team-a-prod
subjects:
  - kind: ServiceAccount
    name: team-a-deployer
    namespace: team-a-prod
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: team-a-deployer-role
```

#### 2. Предоставление прав на имперсонацию контроллеру Argo CD

```yaml
# Разрешаем контроллеру Argo CD имперсонировать ServiceAccount в team-a-prod
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: argocd-impersonator
  namespace: team-a-prod
rules:
  - apiGroups: [""]
    resources: ["serviceaccounts"]
    verbs: ["impersonate"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: argocd-impersonator-binding
  namespace: team-a-prod
subjects:
  - kind: ServiceAccount
    name: argocd-application-controller
    namespace: argocd
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: argocd-impersonator
```

#### 3. Настройка AppProject с `destinationServiceAccounts`

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-a
  namespace: argocd
spec:
  sourceRepos:
    - "https://git.corp.internal/team-a/*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: team-a-prod
  # Привязка имперсонации
  destinationServiceAccounts:
    - server: https://kubernetes.default.svc
      namespace: team-a-prod
      defaultServiceAccount: team-a-deployer
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: ""
      kind: Service
    - group: ""
      kind: ConfigMap
```

**Тест безопасности:** Если разработчик добавит в Git манифест `RoleBinding`, дающий права `cluster-admin`, контроллер попытается применить его от имени `team-a-deployer`. Kube-apiserver моментально вернет ошибку:
```text
# → result: Operation cannot be fulfilled: rolebindings.rbac.authorization.k8s.io is forbidden:
# → result: User "system:serviceaccount:team-a-prod:team-a-deployer" cannot create resource "rolebindings" in API group "rbac.authorization.k8s.io"
```

---

### Сценарий 6: Project-scoped репозитории и кластеры (Безопасный Self-Service)

**Контекст:** Команда `team-a` должна самостоятельно регистрировать приватные Git-репозитории и подключать изолированные dev-кластеры без обращения к администраторам платформы.

#### 1. Делегирование прав на управление репозиториями в `argocd-rbac-cm`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.csv: |
    # Разрешаем администратору проекта управлять репозиториями строго в рамках своего проекта
    p, proj:team-a:admin, repositories, create, team-a/*, allow
    p, proj:team-a:admin, repositories, get, team-a/*, allow
    p, proj:team-a:admin, repositories, update, team-a/*, allow
    p, proj:team-a:admin, repositories, delete, team-a/*, allow
    g, team-a-leads, proj:team-a:admin
```

#### 2. Добавление репозитория тенантом через CLI

```bash
# Добавление приватного Git-репозитория с привязкой к проекту team-a
argocd repo add https://git.corp.internal/team-a/internal-libs.git \
  --project team-a \
  --username git-reader \
  --password-path /tmp/git-token.txt
# → result: Repository 'https://git.corp.internal/team-a/internal-libs.git' added
```

#### 3. Структура созданного Kubernetes Secret

Argo CD автоматически изолирует такой секрет меткой `project: <имя>`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: repo-internal-libs-10928374
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
type: Opaque
stringData:
  project: team-a
  type: git
  url: https://git.corp.internal/team-a/internal-libs.git
  username: git-reader
  password: "..."
```

**Ограничение изоляции:** Приложения из проекта `team-b` не смогут использовать данный репозиторий, даже если в манифесте `Application` указан точный URL. Попытка синхронизации завершится ошибкой `repository not permitted in project 'team-b'`.

---

### Сценарий 7: Наследование политик безопасности через Global Projects

**Контекст:** В организации десятки продуктовых проектов. Для всех production-проектов необходимо централизованно гарантировать единые базовые правила безопасности: запрет секретов из Git, единые окна бэкапов и блокировку кластерных ресурсов.

#### 1. Определение базового проекта в GitOps

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: prod-security-baseline
  namespace: argocd
  labels:
    tier: production-baseline
spec:
  description: "Глобальные политики безопасности для всех production проектов"
  # Полный запрет кластерных ресурсов для всех дочерних проектов
  clusterResourceBlacklist:
    - group: "*"
      kind: "*"
  # Запрет секретов в открытом Git
  namespaceResourceBlacklist:
    - group: ""
      kind: Secret
  # Единое окно технологического обслуживания: блокировка синхронизации в ночь на воскресенье
  syncWindows:
    - kind: deny
      schedule: "0 0 * * 0"
      duration: 6h
      timeZone: "Europe/Moscow"
      applications: ["*"]
```

#### 2. Регистрация селектора в `argocd-cm`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  globalProjects: |
    - projectName: prod-security-baseline
      labelSelector:
        matchLabels:
          environment: production
```

#### 3. Дочерний проект с наследованием

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: billing-service
  namespace: argocd
  labels:
    # Метка активирует наследование prod-security-baseline
    environment: production
spec:
  description: "Проект сервиса биллинга"
  sourceRepos:
    - "https://git.corp.internal/billing/*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: billing-prod
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: ""
      kind: Service
```

Дочерний проект `billing-service` автоматически объединяет свои белые списки с запретами базового проекта `prod-security-baseline`.

---

### Сценарий 8: Проверка подлинности коммитов через Source Integrity (GPG)

**Контекст:** В production запрещен деплой неподписанных коммитов или коммитов, подписанных неуполномоченными инженерами. На смену устаревшему `signatureKeys` в v3.5+ пришел механизм `sourceIntegrity`.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: payment-core
  namespace: argocd
spec:
  description: "Критичный проект платежного шлюза со строгой верификацией подписей"
  sourceRepos:
    - "https://git.corp.internal/fintech/payment-core.git"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: payment-prod
  # Новая спецификация v3.5+: Source Integrity
  sourceIntegrity:
    git:
      policies:
        - repos:
            - url: "https://git.corp.internal/fintech/payment-core.git"
          gpg:
            # Режим strict: каждый коммит в ветке ОБЯЗАН быть подписан доверенным ключом
            mode: strict
            keys:
              # Идентификаторы доверенных публичных GPG-ключей релиз-инженеров
              - "D56C4FCA57A46444"
              - "8A4B6291C8240F12"
```

**Добавление публичного ключа в Argo CD:**
```bash
# Импорт публичного GPG ключа доверенного инженера в контроллер
argocd gpg add --from-file /etc/pki/gpg/release-engineer-d56c.pub
# → result: GPG public key 'D56C4FCA57A46444' added

# Список зарегистрированных ключей
argocd gpg list
# → result: ID                OWNER                         TRUSTED
# → result: D56C4FCA57A46444  release-eng@corp.internal     true
```

Если коммит не подписан или подписан сторонним ключом, Argo CD блокирует операцию генерации манифестов со статусом `ComparisonError`:
```text
# → result: ComparisonError: Commit e4a8f9c is not signed with a trusted GPG key for project payment-core
```

---

### Сценарий 9: Сетевая и ресурсная изоляция тенантов в On-Prem кластере

**Контекст:** Изоляция пространств имен тенанта на уровне ядра Linux и Kubernetes в среде Bare-Metal. Предотвращение сетевых перехватов и защиты кластера от проблемы Noisy Neighbor (исчерпание CPU, RAM и объектов etcd).

#### 1. Пространство имен с Pod Security Admission (Restricted)

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: team-a-prod
  labels:
    tenant: team-a
    environment: production
    # Полный запрет root-контейнеров, hostNetwork, hostPID и privilegeEscalation
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
```

#### 2. NetworkPolicy: Default Deny + разрешенный трафик

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: tenant-default-isolation
  namespace: team-a-prod
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # 1. Разрешаем трафик внутри собственного неймспейса
    - from:
        - podSelector: {}
    # 2. Разрешаем входящий HTTP/HTTPS трафик строго от Ingress Controller (например, ingress-nginx)
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
      ports:
        - protocol: TCP
          port: 8080
    # 3. Разрешаем сбор метрик системой Prometheus из пространства monitoring
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
      ports:
        - protocol: TCP
          port: 9090
  egress:
    # 1. Обязательный резолвинг DNS через CoreDNS в kube-system
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # 2. Доступ к корпоративным сервисам и базам данных в приватной сети
    - to:
        - ipBlock:
            cidr: 10.100.0.0/16
      ports:
        - protocol: TCP
          port: 5432
        - protocol: TCP
          port: 6379
```

> **Важно для DevOps/SRE:** Argo CD `application-controller` взаимодействует с Kubernetes через API-сервер (`kube-apiserver:6443`), поэтому ему не требуется прямой сетевой доступ внутрь подов тенанта.

#### 3. ResourceQuota и LimitRange

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-a-quota
  namespace: team-a-prod
spec:
  hard:
    requests.cpu: "16"
    requests.memory: 32Gi
    limits.cpu: "32"
    limits.memory: 64Gi
    # Защита etcd от разрастания сущностей тенанта
    pods: "100"
    count/services: "20"
    count/configmaps: "50"
    count/secrets: "50"
    count/persistentvolumeclaims: "10"
---
# Обязательный спутник ResourceQuota: задает значения по умолчанию, если разработчик забыл указать их в Pod
apiVersion: v1
kind: LimitRange
metadata:
  name: team-a-limits
  namespace: team-a-prod
spec:
  limits:
    - type: Container
      default:
        cpu: "500m"
        memory: "512Mi"
      defaultRequest:
        cpu: "100m"
        memory: "128Mi"
      max:
        cpu: "4"
        memory: "8Gi"
      min:
        cpu: "50m"
        memory: "64Mi"
```

---

### Сценарий 10: Масштабирование контроллера (Controller Sharding) для On-Prem

**Контекст:** В масштабных bare-metal инсталляциях с количеством приложений > 1000 один процесс `argocd-application-controller` исчерпывает ресурсы CPU/RAM и вызывает задержки очереди сверки (reconciliation queue).

#### 1. Механизм шардирования в On-Prem среде

Argo CD поддерживает шардирование контроллера через `StatefulSet`. По умолчанию шардирование распределяет **кластеры**, а не приложения:
- `legacy`: вычисление хеша от URL кластера (`hash(cluster_url) % replicas`).
- `round-robin`: циклическое распределение кластеров по шардам.
- `consistent-hashing`: консистентное хеширование для минимизации миграции при изменении количества шардов.

**Нюанс для монокластера (Single-Cluster Pitfall):** Если все 1000 приложений тенантов развернуты в локальном кластере (`https://kubernetes.default.svc`), при обычном шардинге ВСЕ приложения попадут на шард 0, а остальные реплики будут простаивать!

**Решения для SRE в On-Prem:**
1. Включение динамического распределения кластеров через переменную окружения `ARGOCD_ENABLE_DYNAMIC_CLUSTER_DISTRIBUTION=true`.
2. Регистрация локального кластера как отдельных виртуальных кластерных записей для каждого проекта с явным назначением метки шарда `shard: "0"`, `shard: "1"` в Secret кластера.

#### 2. Настройка ConfigMap `argocd-cmd-params-cm`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  # Алгоритм распределения нагрузки
  controller.sharding.algorithm: "round-robin"
```

#### 3. Масштабирование StatefulSet контроллера

```bash
# Увеличение количества реплик контроллера до 3
kubectl scale statefulset argocd-application-controller -n argocd --replicas=3
# → result: statefulset.apps/argocd-application-controller scaled

# Проверка распределения шардов между подами
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-application-controller
# → result: NAME                              READY   STATUS    RESTARTS   AGE
# → result: argocd-application-controller-0   1/1     Running   0          5m
# → result: argocd-application-controller-1   1/1     Running   0          1m
# → result: argocd-application-controller-2   1/1     Running   0          1m
```

Каждая реплика StatefulSet автоматически получает свой номер шарда через переменную `ARGOCD_CONTROLLER_SHARD` (0, 1, 2) и флаг `--replicas 3`.

#### 4. Проверка статистики распределения нагрузки

```bash
# Статистика распределения кластеров и приложений по шардам
argocd admin cluster stats
# → result: SHARD  CLUSTERS  APPLICATIONS
# → result: 0      4         342
# → result: 1      4         351
# → result: 2      3         318
```

---

### Сценарий 11: Установка в режиме Namespace-scoped (Для изолированных тенантов)

**Контекст:** Для клиентов или подразделений с повышенными требованиями к изоляции (например, внешние подрядчики) выделяется персональный инстанс Argo CD, запускаемый строго внутри одного пространства имен без глобальных прав `cluster-admin`.

```bash
# 1. Администратор кластера создает пространство имен тенанта
kubectl create namespace tenant-secure-zone
# → result: namespace/tenant-secure-zone created

# 2. Установка Argo CD без кластерных привилегий (manifest namespace-install.yaml)
#    (CRDs должны быть предварительно установлены в кластере администратором)
kubectl apply -n tenant-secure-zone --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.4/manifests/namespace-install.yaml
# → result: serviceaccount/argocd-application-controller created
# → result: role.rbac.authorization.k8s.io/argocd-application-controller created
# → result: rolebinding.rbac.authorization.k8s.io/argocd-application-controller created
# → result: service/argocd-server created
# → result: deployment.apps/argocd-server created
```

**Особенности эксплуатации Namespace-scoped:**
- Инстанс управляет ресурсами строго через внешние кластерные эндпоинты или локально в рамках своего неймспейса (не может деплоить в другие системные пространства имен хост-кластера).
- Доступ пользователей изолирован: скомпрометированный сервер Argo CD тенанта не имеет доступа к управляющему контуру хост-кластера.

---

### Сценарий 12: Декларативная фабрика тенантов (Tenant Factory через ApplicationSet)

**Контекст:** Автоматизация онбординга новых команд. Инженер платформы добавляет описание нового тенанта в Git, а центральный контроллер автоматически генерирует пространство имен, `AppProject`, квоты, сетевые политики и базовые роли.

#### Манифест ApplicationSet (Tenant Onboarding Generator)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: tenant-factory
  namespace: argocd
spec:
  generators:
    - git:
        repoURL: "https://git.corp.internal/platform/tenants-inventory.git"
        revision: main
        files:
          - path: "tenants/*/tenant.json"
  template:
    metadata:
      name: "tenant-{{name}}"
    spec:
      project: default
      source:
        repoURL: "https://git.corp.internal/platform/tenant-blueprints.git"
        targetRevision: main
        path: blueprints/standard-tenant
        helm:
          parameters:
            - name: "tenantName"
              value: "{{name}}"
            - name: "cpuQuota"
              value: "{{quota.cpu}}"
            - name: "memoryQuota"
              value: "{{quota.memory}}"
            - name: "gitRepo"
              value: "{{gitRepo}}"
      destination:
        server: https://kubernetes.default.svc
        namespace: "argocd"
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

#### Файл конфигурации тенанта в Git (`tenants/billing/tenant.json`)

```json
{
  "name": "billing",
  "gitRepo": "https://git.corp.internal/billing/*",
  "quota": {
    "cpu": "32",
    "memory": "64Gi"
  }
}
```

Создание PR с добавлением `tenant.json` автоматически разворачивает всю мультитенантную обвязку за считанные секунды.

---

## Операции и команды

### Управление проектами и ролями через CLI

```bash
# 1. Просмотр списка всех проектов
argocd proj list
# → result: NAME      DESCRIPTION                     DESTINATIONS  SOURCES
# → result: default   Locked default project          0             0
# → result: backend   Проект для сервисов Backend     1             2
# → result: frontend  Проект для сервисов Frontend    1             1

# 2. Создание нового проекта команды
argocd proj create analytics \
  --description "Команда аналитики данных" \
  --src "https://git.corp.internal/analytics/*" \
  --dest "https://kubernetes.default.svc,analytics-prod"
# → result: Project 'analytics' created

# 3. Добавление роли разработчика в проект
argocd proj role create analytics developer \
  --description "Разработчик аналитических сервисов"
# → result: Role 'developer' created in project 'analytics'

# 4. Назначение прав на синхронизацию для роли (флаг --action)
argocd proj role add-policy analytics developer \
  --action sync \
  --object "analytics/*" \
  --permission allow
# → result: Policy added to role 'developer' in project 'analytics'

# 5. Выпуск сервисного JWT-токена для CI/CD с временем жизни 30 дней (720 часов)
argocd proj role create-token analytics developer --expires-in 720h
# → result: eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE3NzAwMDAwMDAsImlzcyI6ImFyZ29jZCIsInN1YiI6InByb2o6YW5hbHl0aWNzOmRldmVsb3BlciJ9...

# 6. Удаление проекта (возможно только при отсутствии привязанных Application)
argocd proj rm analytics
# → result: Project 'analytics' deleted
```

---

### Аудит доступа и валидация политик RBAC

```bash
# 1. Проверка прав конкретной роли на выполнение операции
argocd admin settings rbac can proj:backend:developer sync applications 'backend/billing-api'
# → result: Yes

# 2. Проверка запрещенного действия роли (попытка деплоя в чужой проект)
argocd admin settings rbac can proj:frontend:developer sync applications 'backend/billing-api'
# → result: No

# 3. Проверка гранулярных прав на суб-ресурсы (удаление пода для перезапуска)
argocd admin settings rbac can role:backend-dev delete/*/Pod/*/* 'backend/billing-api'
# → result: Yes

# 4. Получение информации об аутентифицированном пользователе и его группах
argocd account get-user-info
# → result: Logged In: true
# → result: User: ivan.ivanov
# → result: Groups: sso-backend-devs, sso-developers-all
```

---

### Управление окнами синхронизации (Sync Windows)

```bash
# 1. Добавление разрешающего окна синхронизации на рабочие часы
argocd proj windows add backend \
  --kind allow \
  --schedule "0 9 * * 1-5" \
  --duration 9h \
  --time-zone "Europe/Moscow" \
  --applications "*"
# → result: Sync window added to project 'backend' with ID 0

# 2. Добавление блокирующего окна (deny) на выходные дни
argocd proj windows add backend \
  --kind deny \
  --schedule "0 0 * * 6,0" \
  --duration 24h \
  --time-zone "Europe/Moscow" \
  --applications "*"
# → result: Sync window added to project 'backend' with ID 1

# 3. Разрешение ручного синка инженером в период действия окна (manualSync override)
argocd proj windows enable-manual-sync backend 1
# → result: Manual sync enabled for sync window 1 in project 'backend'

# 4. Просмотр активных окон проекта
argocd proj windows list backend
# → result: ID  KIND   SCHEDULE       DURATION  TIMEZONE       APPLICATIONS  MANUALSYNC
# → result: 0   allow  0 9 * * 1-5    9h        Europe/Moscow  *             false
# → result: 1   deny   0 0 * * 6,0    24h       Europe/Moscow  *             true
```

---

### Мониторинг мультитенантности через Prometheus

```promql
# 1. Количество приложений, принадлежащих каждому проекту (инвентаризация тенантов)
count by (project) (argocd_app_info)

# 2. Количество приложений в статусе Degraded по проектам
sum by (project) (argocd_app_info{health_status="Degraded"})

# 3. Количество заблокированных синхронизаций из-за окон Sync Windows
sum by (project) (argocd_app_sync_window{window_kind="deny"}) == 1

# 4. Распределение приложений по шардам контроллера (контроль балансировки)
count by (shard) (argocd_app_info)

# 5. Ошибки синхронизации, вызванные отказом в правах K8s API (Impersonation)
sum by (project) (rate(argocd_app_sync_total{phase="Failed"}[5m])) > 0
```

---

## Диагностика и устранение неисправностей

### Типичные ошибки и способы их устранения

| Сообщение об ошибке | Причина сбоя | Метод диагностики | Способ решения |
| :--- | :--- | :--- | :--- |
| `application repo <URL> is not permitted in project '<NAME>'` | Репозиторий манифестов отсутствует в `spec.sourceRepos` проекта. | `kubectl get appproject <NAME> -n argocd -o yaml` | Добавить URL репозитория или маску в поле `sourceRepos`. |
| `application destination <CLUSTER, NS> is not permitted in project '<NAME>'` | Целевой кластер или namespace назначения отсутствует в `spec.destinations`. | Сверить поля `destination` в Application и `destinations` в AppProject. | Добавить пару `server` (или `name`) и `namespace` в `destinations`. |
| `resource <GROUP:KIND> is not permitted in project '<NAME>'` | Вид ресурса заблокирован `namespaceResourceBlacklist` или отсутствует в Whitelist. | Проверить логи контроллера: `kubectl logs -n argocd statefulset/argocd-application-controller`. | Добавить вид ресурса в `namespaceResourceWhitelist` или удалить из Blacklist. |
| `application is outside permitted source namespaces` | Манифест `Application` создан в namespace, не включенном в `sourceNamespaces`. | `kubectl get appproject <NAME> -o jsonpath='{.spec.sourceNamespaces}'` | Добавить namespace в `sourceNamespaces` проекта и в `application.namespaces` в `argocd-cmd-params-cm`. |
| `Permission denied` (UI/CLI) | Правила Casbin RBAC в `argocd-rbac-cm` не разрешают действие субъекту. | `argocd admin settings rbac can <ROLE> <ACTION> <RESOURCE> <OBJECT>` | Проверить маппинг групп OIDC в `policy.csv` и права проектной роли. |
| `Sync operation blocked by sync window` | Синхронизация заблокирована активным окном `deny` или отсутствием окна `allow`. | `argocd proj windows list <PROJECT>` | Дождаться окончания окна, скорректировать cron-расписание или включить `manualSync: true`. |
| `User "..." cannot create resource in API group` (403) | Сервисный аккаунт имперсонации `destinationServiceAccounts` не имеет прав K8s. | `kubectl auth can-i create <KIND> -n <NS> --as=system:serviceaccount:<NS>:<SA>` | Расширить Role/RoleBinding сервисного аккаунта тенанта в целевом namespace. |
| `Commit ... is not signed with a trusted GPG key` | Коммит не имеет валидной подписи GPG при активной политике `sourceIntegrity`. | `git log --show-signature -1 <COMMIT>` в Git-репозитории. | Подписать коммит доверенным ключом или импортировать ключ через `argocd gpg add`. |
| `All controller shards assigned to single instance` | Все приложения используют локальный кластер, и алгоритм хеширует один URL на шард 0. | `argocd admin cluster stats` | Включить динамическое шардирование или зарегистрировать кластер с явными метками шардов. |

---

### Пошаговое дерево диагностики при ошибках доступа

```text
[Проблема: Ошибка авторизации или сбой синхронизации]
                           │
                           ▼
                 [Шаг 1: Аутентификация]
       Пользователь успешно входит в UI/CLI?
       ├── НЕТ ──> Проверить OIDC/Dex: логи argocd-server,
       │           валидность токена, истечение сертификатов IdP.
       └── ДА  ──> Переход к Шагу 2.
                           │
                           ▼
                 [Шаг 2: Проверка RBAC]
       Команда 'argocd admin settings rbac can' возвращает Yes?
       ├── НЕТ ──> Проверить argocd-rbac-cm:
       │           1. Задан ли policy.default?
       │           2. Привязана ли SSO-группа через 'g,' к роли?
       │           3. Соответствует ли scopes: "[groups]" claims провайдера?
       └── ДА  ──> Переход к Шагу 3.
                           │
                           ▼
              [Шаг 3: Границы AppProject]
       Соответствует ли Application спецификации AppProject?
       ├── Repo не разрешен?     ──> Добавить URL в spec.sourceRepos.
       ├── Destination не в белом?──> Добавить namespace в spec.destinations.
       ├── Ресурс заблокирован?  ──> Проверить namespaceResourceBlacklist.
       ├── SourceNamespace чужой?──> Проверить spec.sourceNamespaces и
       │                             argocd-cmd-params-cm.
       └── Все разрешено         ──> Переход к Шагу 4.
                           │
                           ▼
              [Шаг 4: Окна Sync Windows]
       Синхронизация блокируется расписанием?
       ├── ДА ──> Проверить активные окна: argocd proj windows list.
       └── НЕТ ──> Переход к Шагу 5.
                           │
                           ▼
          [Шаг 5: K8s API & Impersonation SA]
       Возвращает ли Kube-API ошибку 403 Forbidden?
       ├── ДА ──> Проверить права ServiceAccount в целевом namespace:
       │           kubectl auth can-i create ... --as=system:serviceaccount:...
       └── НЕТ ──> Проверить статус самого пода приложения (CrashLoopBackOff, ImagePullBackOff).
```

---

## Лучшие практики

### Архитектура и разграничение зон ответственности

1. **Принцип жестких границ проектов:** Каждая продуктовая команда обязана иметь изолированный `AppProject`. Использование общего проекта для нескольких команд нарушает изоляцию аудита и увеличивает радиус поражения (blast radius).
2. **Hardening проекта `default`:** Всегда обнуляйте `sourceRepos` и `destinations` в проекте `default` сразу после установки Argo CD. Это предотвратит случайный или злонамеренный деплой мимо проектных политик.
3. **Строгая иерархия сред:** Проекты production обязаны быть изолированы от dev/staging. В production-проектах недопустимо использование масок `*` в `sourceRepos` и `destinations`.
4. **Централизация базовых политик через Global Projects:** Используйте Global Projects для автоматического применения базовых запретов (например, блокировка `ClusterRole` и `Secret` из Git) во всех production-проектах.

---

### Безопасность и Least Privilege

1. **Отказ от прямого доступа разработчиков в namespace `argocd`:** Команды должны оперировать только в своих tenant-неймспейсах через паттерн `Applications-in-any-Namespace`.
2. **Обязательная имперсонация через `destinationServiceAccounts`:** Не позволяйте контроллеру Argo CD синхронизировать production-манифесты с правами кластерного администратора. Сервисный аккаунт тенанта должен иметь права только на явно разрешенные сущности.
3. **NetworkPolicy Default Deny:** Каждый tenant namespace обязан содержать сетевую политику `Default Deny` для входящего и исходящего трафика, разрешая взаимодействие только с Ingress-контроллером, DNS и выделенными базами данных.
4. **Контроль подлинности коммитов:** Включайте `sourceIntegrity` со строгим режимом (`strict`) для критичных проектов. Запрещайте локальную синхронизацию (`--local`) для production-контуров.
5. **Запрет интерактивного терминала:** Не предоставляйте разработчикам право `exec create` в production-проектах через RBAC Argo CD. Доступ в контейнеры должен осуществляться только через регламентированные процедуры отладки.

---

### Производительность и сайзинг в On-Prem

1. **Согласованная настройка Quota и Limits:** Всегда создавайте `LimitRange` вместе с `ResourceQuota`. Без `LimitRange` поды без явных `requests`/`limits` будут отклонены Kubernetes, блокируя работу тенанта.
2. **Защита etcd через квоты на количество объектов:** Ограничивайте `count/secrets`, `count/configmaps` и `count/pods` на уровне 50–100 объектов на namespace для защиты базы данных кластера.
3. **Шардирование при росте нагрузки:** Переходите на шардирование `argocd-application-controller` при превышении порога в 500 приложений. Для монокластеров настраивайте виртуальные кластерные секреты или флаг динамического шардинга.

---

### Регламент офбординга (Удаление тенанта)

Для безопасного удаления тенанта без оставления «висячих» ресурсов (orphaned objects) соблюдайте регламент:

```bash
# 1. Проверка наличия активных приложений тенанта
argocd app list --project tenant-legacy
# → result: (список приложений)

# 2. Каскадное удаление всех приложений проекта с очисткой K8s ресурсов
for app in $(argocd app list --project tenant-legacy -o name); do
  argocd app delete "$app" --cascade --yes
done
# → result: Application deleted successfully

# 3. Удаление проектных секретов репозиториев
kubectl get secret -n argocd -l argocd.argoproj.io/secret-type=repository -o json \
  | jq -r '.items[] | select(.stringData.project=="tenant-legacy") | .metadata.name' \
  | xargs -r -I{} kubectl delete secret {} -n argocd
# → result: secret "repo-legacy" deleted

# 4. Удаление AppProject тенанта
argocd proj rm tenant-legacy
# → result: Project 'tenant-legacy' deleted

# 5. Удаление tenant namespace в Kubernetes
kubectl delete namespace tenant-legacy-prod --wait
# → result: namespace "tenant-legacy-prod" deleted
```

---

## Ограничения и граничные случаи

### Системные ограничения

1. **Отсутствие произвольной вложенности проектов:** `AppProject` не поддерживает иерархическое дерево (проект не может быть подпроектом другого проекта). Для частичной эмуляции иерархии используется только механизм `globalProjects`.
2. **Единый конфигурационный файл RBAC:** Все глобальные политики Casbin хранятся в едином объекте `argocd-rbac-cm`. Невозможно разделить глобальные политики по отдельным неймспейсам (разграничение внутри неймспейсов доступно только через локальные `.spec.roles` в `AppProject`).
3. **Шардирование по кластерам по умолчанию:** Стандартные алгоритмы шардинга (`legacy`, `round-robin`) разделяют нагрузку по кластерам. При сосредоточении сотен приложений в одном bare-metal кластере требуется дополнительная настройка распределения.
4. **Project-scoped репозитории в ApplicationSet:** Генераторы `ApplicationSet`, использующие шаблонизацию имени проекта (например, `project: "{{name}}"`), не могут использовать репозитории, помеченные как project-scoped, так как контроллер валидирует репозиторий до разрешения шаблона.
5. **Ограничения Namespace-scoped режима:** Экземпляр Argo CD, установленный через `namespace-install.yaml`, не может управлять локальным кластером через `https://kubernetes.default.svc` без кластерных прав и требует подключения внешних кластеров через токены.

---

### Граничные случаи эксплуатации

1. **Приоритет запрещающих правил (Deny Trumps Allow):** В окнах синхронизации (`syncWindows`) и списках ресурсов (`clusterResourceBlacklist`, `namespaceResourceBlacklist`) запрещающие правила имеют безусловный приоритет. Если ресурс разрешен в Whitelist, но попадает под маску Blacklist — он будет заблокирован.
2. **Удаление AppProject при существующих Application:** Если администратор принудительно удаляет `AppProject`, в котором остались приложения (например, сняв finalizer), приложения переходят в статус `Unknown` и не могут быть синхронизированы или удалены через стандартный цикл без восстановления проекта.
3. **Утечка секретов через общие репозитории:** Если два тенанта используют один монорепозиторий, разграничение через `sourceRepos` должно использовать строгие подкаталоги, а для Helm-чартов — строгие значения `path` и `targetRevision`.
4. **Конфликты CRD при децентрализованном деплое:** Если два тенанта пытаются применить манифесты одной и той же CRD с разными версиями, побеждает последний применивший, что может сломать контроллер первого тенанта. Поэтому `CustomResourceDefinition` ОБЯЗАН находиться в `clusterResourceBlacklist` для всех тенантов и управляться централизованно Platform SRE.
5. **Наследование Fine-grained RBAC:** В версиях v3.0+ действия `update` и `delete` без явного указания суб-ресурса не распространяются на суб-ресурсы автоматически. При необходимости сохранения старого поведения требуется выставить `server.rbac.disableApplicationFineGrainedRBACInheritance: "false"` в `argocd-cm`.

---

## Дополнительная информация

### См. также

- [RBAC — модель доступа, policy.csv и практические сценарии](./argocd_rbac_deep.md) — детальное описание синтаксиса Casbin, built-in ролей и JWT токенов.
- [AppProject — изоляция проектов и границы безопасности](./argocd_appproject_deep.md) — полное руководство по спецификации полей `AppProject`.
- [SSO с GitLab и Dex](./argocd_sso_gitlab.md) — настройка корпоративной аутентификации OIDC и сопоставления групп.
- [Установка и настройка Argo CD](./argocd_installation_and_setup.md) — развертывание в режиме High Availability, базовые ConfigMap и тюнинг.
- [Временные окна синхронизации (Sync Windows)](./synchronization/scenarios/sync_windows.md) — регламентные ограничения синхронизации.
- [Hardening безопасности Argo CD](./argocd_security_hardening.md) — сетевые политики контроллера, mTLS, proxy и audit logging.
- [ApplicationSets — генераторы и шаблонизация](./argocd_applicationsets.md) — генерация приложений для множества тенантов.
- [Мониторинг и траблшутинг Argo CD](./argocd_troubleshooting_and_monitoring.md) — метрики Prometheus, алерты и диагностика производительности.
- [Disaster Recovery и резервное копирование](./argocd_disaster_recovery.md) — восстановление конфигурации тенантов и экспорт манифестов.
- [Отслеживание ресурсов и Tracking Methods](./argocd_resource_tracking.md) — аннотации и метки отслеживания объектов K8s.
- [Удаление и очистка ресурсов](./argocd_deletion_and_cleanup.md) — каскадное удаление, финализаторы и сборка мусора.
- [Мульти-тенантность в Kubernetes](../../Kubernetes/Concepts/multi-tenancy.md) — фундаментальные концепции изоляции неймспейсов, Capsule и vcluster.

---

### Ссылки и источники

- [Официальная документация: AppProject Specification Reference](https://argo-cd.readthedocs.io/en/stable/operator-manual/project-specification/)
- [Официальная документация: Projects User Guide](https://argo-cd.readthedocs.io/en/stable/user-guide/projects/)
- [Официальная документация: RBAC Configuration](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/)
- [Официальная документация: Applications in Any Namespace](https://argo-cd.readthedocs.io/en/stable/operator-manual/app-any-namespace/)
- [Официальная документация: Source Integrity](https://argo-cd.readthedocs.io/en/stable/user-guide/source-integrity/)
- [Официальная документация: High Availability and Controller Sharding](https://argo-cd.readthedocs.io/en/stable/operator-manual/high_availability/)
- [Документация Kubernetes: Multi-tenancy Guide](https://kubernetes.io/docs/concepts/security/multi-tenancy/)
