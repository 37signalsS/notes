# Argo CD: Мультитенантность — паттерны изоляции, project-per-team и tenant namespace isolation

**Актуально для:** Argo CD v3.5.x (v3.5.0 – v3.5.4+; проверено против релиза v3.5.4 от 6 октября 2026 года)

> **Актуальность (2026):** Мультитенантность в Argo CD v3.5.x реализуется через комбинацию AppProject (ограничения на источники/назначения, типы ресурсов, окна синхронизации), RBAC (роли для пользователей/групп, fine-grained control для `update`/`delete` суб-ресурсов), SSO (OIDC/LDAP для аутентификации) и Namespace (сетевая и resource изоляция). Основные паттерны: Project-per-team, Project-per-environment, Shared-controller с tenant namespaces, Multi-controller sharding, Applications-in-any-Namespace, Namespace-scoped Argo CD. Ключевые новшества v3.5: `sourceNamespaces`, `permitOnlyProjectScopedClusters`, `orphanedResources`, `sourceIntegrity` (наследник устаревшего `signatureKeys`), `jwtTokens` в ролях проектов, fine-grained RBAC для `update`/`delete` суб-ресурсов (v3.0+), `destinationServiceAccounts` для имперсонации.

## Предварительные требования

1. **Argo CD установлен** (см. [Установка и настройка](./argocd_installation_and_setup.md)). Рекомендуется версия v3.5.x — последняя на момент обновления (v3.5.4, октябрь 2026).
2. **kubectl** с доступом к namespace `argocd` (или к tenant namespace для namespace-scoped режима).
3. **argocd CLI** настроен (версия, совместимая с сервером).
4. **SSO настроен** (рекомендуется) — см. [SSO с GitLab](./argocd_sso_gitlab.md).
5. **Понимание RBAC и AppProject** — см. [RBAC](./argocd_rbac_deep.md), [AppProject](./argocd_appproject_deep.md).
6. **Доступ к кластеру** для редактирования ConfigMap/Secret в namespace Argo CD (для настройки `argocd-rbac-cm`, `argocd-cm`).
7. **Понимание Sync Windows** — см. [Sync Windows](./synchronization/scenarios/sync_windows.md).
8. **Понимание Kubernetes multi-tenancy** — см. [Kubernetes Multi-tenancy](../../Kubernetes/Concepts/multi-tenancy.md) (Namespace, NetworkPolicy, ResourceQuota, RBAC).

## Определения

| Термин | Определение |
| :--- | :--- |
| **Мультитенантность (Multi-tenancy)** | Архитектурный паттерн, при котором один экземпляр Argo CD обслуживает несколько независимых команд/проектов с изоляцией данных, конфигурации и доступа. |
| **Tenant (Тенант)** | Команда, проект или бизнес-единица, использующая Argo CD с изолированным доступом к своим приложениям и ресурсам. |
| **AppProject** | CRD, определяющий границы (boundary): разрешённые источники, назначения, типы ресурсов, роли, окна синхронизации. |
| **Project-per-team** | Паттерн, при котором каждая команда имеет свой AppProject с уникальными restrictions, roles и sync windows. |
| **Project-per-environment** | Паттерн, при котором каждое окружение (dev/staging/prod) является отдельным AppProject с разными уровнями доступа. |
| **Tenant Namespace** | Kubernetes-namespace, выделенный для конкретного тенанта. Обеспечивает сетевую и resource изоляцию. |
| **Shared Controller** | Единый экземпляр argocd-application-controller, обслуживающий несколько тенантов через AppProject и RBAC. |
| **Applications-in-any-Namespace** | Функция (v3.x), позволяющая создавать Application CR в tenant-namespace вместо namespace Argo CD. Требует `sourceNamespaces` в AppProject для ограничения. |
| **Namespace-scoped Argo CD** | Режим установки Argo CD, при котором все компоненты работают в одном namespace (без cluster-admin). Обеспечивает изоляцию tenant'а на уровне namespace. |
| **destinationServiceAccounts** | Поле AppProject, позволяющее указать service account для имперсонации при синхронизации в каждый destination. Ключевой механизм защиты: тенант не получает прямые кластерные токены. |
| **Project-scoped репозитории/кластеры** | Секреты с меткой `project: <name>`, доступные только приложениям того же проекта. Позволяет self-service добавление репозиториев/кластеров без админа. |
| **Global Project** | AppProject с `labelSelector` в `argocd-cm` (`globalProjects`), от которого наследуются whitelist/blacklist, syncWindows, sourceRepos и destinations другие проекты. |
| **Source Integrity** | Механизм (v3.5+), заменяющий устаревший `signatureKeys`. Позволяет объявлять критерии проверки подлинности источников (GPG commit signatures) в `AppProject.spec.sourceIntegrity`. |
| **Controller Sharding** | Разделение нагрузки argocd-application-controller на несколько реплик по шардам. Критично для масштабирования при 1000+ приложений. |
| **RBAC Fine-grained Permissions** | Правила v3.0+, позволяющие разрешать/запрещать действия на конкретные sub-ресурсы (pods, services) внутри приложения: `delete/*/Pod/*/*`. |

## Базовые концепции

### Принцип Defense-in-Depth

Мультитенантность в Argo CD реализуется трёхуровневой моделью защиты:

```text
Запрос (UI/CLI/API)
    │
    ▼
┌─────────────────────┐
│ 1. Аутентификация    │ ← SSO (OIDC/LDAP), локальный аккаунт, JWT
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ 2. Авторизация       │ ← RBAC (policy.csv + project roles)
│    (Кто?)            │   "кто может sync в production/*"
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ 3. AppProject        │ ← Границы (Что?)
│    Restrictions      │   "разрешено деплоить только Deployment в team-a/*"
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ 4. destinationSA     │ ← Имперсонация для синхронизации
│    (Как?)            │   "контроллер синхронизирует от service account тенанта"
└─────────────────────┘
```

RBAC отвечает **кто** может что сделать, AppProject определяет **что** разрешено сделать, а `destinationServiceAccounts` контролирует **как** (от чьего имени) выполняется синхронизация.

### Архитектурные паттерны мультитенантности

```text
┌──────────────────────────────────────────────────────────┐
│  Argo CD (shared instance)                               │
│                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │ AppProject  │  │ AppProject  │  │ AppProject  │      │
│  │ (team-a)    │  │ (team-b)    │  │ (shared)    │      │
│  │             │  │             │  │             │      │
│  │ sourceRepos: │  │ sourceRepos: │  │ sourceRepos: │      │
│  │  team-a/*   │  │  team-b/*   │  │  *          │      │
│  │ destinations:│  │ destinations:│  │ destinations:│      │
│  │  ns:team-a  │  │  ns:team-b  │  │  ns:shared  │      │
│  │ sourceNS:   │  │ sourceNS:   │  │ sourceNS:   │      │
│  │  team-a-*   │  │  team-b-*   │  │  shared-*   │      │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘      │
│         │                │                │              │
│         ▼                ▼                ▼              │
│  ┌─────────────────────────────────────────────────────┐│
│  │           argocd-application-controller              ││
│  │           (shared, sharded by project)                ││
│  └─────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ namespace   │  │ namespace   │  │ namespace   │
│ team-a      │  │ team-b      │  │ shared      │
│ (isolated)  │  │ (isolated)  │  │ (isolated)  │
└─────────────┘  └─────────────┘  └─────────────┘
```

### Матрица изоляции и защиты

| Уровень | Механизм | Что ограничивает | Где настраивается |
| :--- | :--- | :--- | :--- |
| **Аутентификация** | SSO (OIDC/LDAP) | Кто может войти в Argo CD | `argocd-cm` (OIDC config) |
| **Авторизация** | RBAC (policy.csv) | Какие действия (get/sync/create/delete) с какими ресурсами | `argocd-rbac-cm` |
| **Границы проекта** | AppProject.sourceRepos | Какие Git-репозитории разрешены | `AppProject.spec.sourceRepos` |
| **Границы проекта** | AppProject.destinations | Куда можно деплоить (кластеры + namespace) | `AppProject.spec.destinations` |
| **Границы проекта** | AppProject.namespaceResourceWhitelist/Blacklist | Какие типы ресурсов разрешены/запрещены | `AppProject.spec` |
| **Границы проекта** | AppProject.clusterResourceWhitelist/Blacklist | Какие cluster-scoped ресурсы разрешены | `AppProject.spec` |
| **Область Application** | sourceNamespaces | В каких namespaces могут жить Application CR | `AppProject.spec.sourceNamespaces` |
| **Имперсонация** | destinationServiceAccounts | От чьего service account синхронизировать | `AppProject.spec.destinationServiceAccounts` |
| **Временные окна** | Sync Windows | Когда можно синхронизировать | `AppProject.spec.syncWindows` |
| **Аудит источников** | sourceIntegrity | GPG-подпись коммитов перед sync | `AppProject.spec.sourceIntegrity` |
| **Сетевая изоляция** | NetworkPolicy | Pod-to-Pod трафик между tenant namespaces | Kubernetes NetworkPolicy |
| **Resource изоляция** | ResourceQuota + LimitRange | Лимиты CPU/RAM/объектов на namespace | Kubernetes ResourceQuota |

### Паттерн: Applications-in-any-Namespace

Начиная с v3.x, Application CR может быть создан в tenant namespace (не в `argocd`):

```text
tenant team-a
├── Namespace: team-a  (tenant-owned)
│   ├── AppProject (team-a) — управляется Platform Team через Argo CD
│   └── Application (app-backend) — создан team-a через Argo CD или pull request
argocd namespace
├── argocd-application-controller
├── argocd-server
└── AppProject (team-a) — sourceNamespaces: ["team-a-*"]
```

Это паттерн **declarative-app-per-team**: команда управляет своими Application через GitOps, а Platform Team задаёт границы через `sourceNamespaces` в AppProject.

### Паттерн: Namespace-scoped Argo CD

Для враждебных тенантов (external customers) используется **namespace-scoped установка** (`namespace-install.yaml`):

```bash
# Namespace-scoped установка (без cluster-admin)
kubectl create namespace argocd-team-a
# CRDs устанавливаются отдельно администратором
kubectl apply -n argocd-team-a --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.4/manifests/namespace-install.yaml
```

Ограничения:
- CRD должны быть установлены администратором кластера (разово).
- Argo CD может деплоить только во внешние кластеры (не в `kubernetes.default.svc`).
- Application/ApplicationSet/AppProject создаются только в этом namespace.

## Практические сценарии

### Сценарий 1: Project-per-team

Каждая команда имеет свой AppProject с полной изоляцией.

**1. Команда Backend:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: backend
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: "Backend команда"
  sourceRepos:
    - "https://github.com/myorg/backend/*"
    - "https://charts.myorg.io/backend/*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: backend-*
  clusterResourceWhitelist: []
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
  sourceNamespaces:
    - "team-a-*"
  destinationServiceAccounts:
    - server: https://kubernetes.default.svc
      namespace: backend-prod
      defaultServiceAccount: backend-deployer
  roles:
    - name: developer
      description: "Backend разработчик"
      policies:
        - p, proj:backend:developer, applications, get, backend/*, allow
        - p, proj:backend:developer, applications, sync, backend/*, allow
        - p, proj:backend:developer, applications, create, backend/*, allow
      groups:
        - backend-team
    - name: sre
      description: "Backend SRE"
      policies:
        - p, proj:backend:sre, applications, get, backend/*, allow
        - p, proj:backend:sre, logs, get, backend/*, allow
      jwtTokens:
        - iat: 1535390316
      groups:
        - sre-team
```

**2. Команда Frontend:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: frontend
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: "Frontend команда"
  sourceRepos:
    - "https://github.com/myorg/frontend/*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: frontend-*
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: ""
      kind: Service
    - group: "networking.k8s.io"
      kind: Ingress
  roles:
    - name: developer
      policies:
        - p, proj:frontend:developer, applications, get, frontend/*, allow
        - p, proj:frontend:developer, applications, sync, frontend/*, allow
      groups:
        - frontend-team
```

**3. RBAC для всех команд:**
```yaml
# argocd-rbac-cm
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.default: role:readonly
  policy.csv: |
    # Backend
    p, role:backend-dev, applications, get, backend/*, allow
    p, role:backend-dev, applications, sync, backend/*, allow
    g, backend-team, role:backend-dev

    # Frontend
    p, role:frontend-dev, applications, get, frontend/*, allow
    p, role:frontend-dev, applications, sync, frontend/*, allow
    g, frontend-team, role:frontend-dev

    # SRE (общий доступ)
    p, role:sre, applications, get, */*, allow
    p, role:sre, logs, get, */*, allow
    p, role:sre, exec, create, */*, allow
    g, sre-team, role:sre

  scopes: "[groups]"
```

### Сценарий 2: Project-per-environment

Каждое окружение — отдельный AppProject с разными restrictions.

```yaml
# Development
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: dev
  namespace: argocd
spec:
  sourceRepos: ["*"]
  destinations:
    - server: https://kubernetes.default.svc
      namespace: dev-*
  clusterResourceWhitelist:
    - group: ""
      kind: Namespace
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: ""
      kind: Service
  roles:
    - name: developer
      policies:
        - p, proj:dev:developer, applications, *, dev/*, allow
      groups:
        - dev-team
---
# Staging
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: staging
  namespace: argocd
spec:
  sourceRepos: ["*"]
  destinations:
    - server: https://kubernetes.default.svc
      namespace: staging-*
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: ""
      kind: Service
  roles:
    - name: releaser
      policies:
        - p, proj:staging:releaser, applications, get, staging/*, allow
        - p, proj:staging:releaser, applications, sync, staging/*, allow
      groups:
        - release-team
  syncWindows:
    - kind: allow
      schedule: "0 9 * * 1-5"
      duration: 10h
      timeZone: "Europe/Moscow"
---
# Production
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production
  namespace: argocd
spec:
  sourceRepos:
    - "https://github.com/myorg/prod-*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: production
  clusterResourceWhitelist: []
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: ""
      kind: Service
  namespaceResourceBlacklist:
    - group: ""
      kind: Secret
  roles:
    - name: deployer
      policies:
        - p, proj:production:deployer, applications, get, production/*, allow
        - p, proj:production:deployer, applications, sync, production/*, allow
      groups:
        - sre-team
  syncWindows:
    - kind: allow
      schedule: "0 10 * * 1-5"
      duration: 8h
      timeZone: "Europe/Moscow"
    - kind: deny
      schedule: "0 0 * * 0,6"
      duration: 24h
      applications:
        - "prod-*"
```

### Сценарий 3: Харденинг default project

AppProject `default` по умолчанию разрешает всё. Для безопасности его нужно ограничить.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: default
  namespace: argocd
spec:
  sourceRepos: []
  destinations: []
  clusterResourceBlacklist:
    - group: "*"
      kind: "*"
  namespaceResourceBlacklist:
    - group: "*"
      kind: "*"
```

После применения любое приложение без явного `project` будет отклонено. Переместите приложения в специализированные проекты.

### Сценарий 4: Applications-in-any-Namespace

Создаём AppProject с `sourceNamespaces` для разрешения Application CR в tenant namespace.

```yaml
# AppProject (в namespace argocd, управляется Platform Team)
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-a
  namespace: argocd
spec:
  sourceRepos:
    - "https://github.com/myorg/team-a/*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: team-a-prod
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: ""
      kind: Service
  sourceNamespaces:
    - "team-a-apps"
  roles:
    - name: admin
      policies:
        - p, proj:team-a:admin, applications, *, team-a/*, allow
      groups:
        - team-a
```

```yaml
# Application CR в tenant namespace team-a-apps
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: backend-app
  namespace: team-a-apps
  finalizers:
    - resources-finalizer.argoproj.argoproj.io
spec:
  project: team-a
  source:
    repoURL: "https://github.com/myorg/team-a/backend"
    targetRevision: HEAD
    path: k8s/production
  destination:
    server: https://kubernetes.default.svc
    namespace: team-a-prod
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**Важно:** `sourceNamespaces` ограничивает, в каких namespaces могут находиться Application CR для этого проекта. Без него Argo CD не будет recognizes Application из tenant namespaces.

### Сценарий 5: Namespace-scoped Argo CD (для враждебных тенантов)

```bash
# 1. Создаём namespace для tenant
kubectl create namespace argocd-team-a

# 2. Устанавливаем Argo CD в namespace-scoped режим
#    CRD устанавливаются администратором один раз для всех tenant'ов
kubectl apply -n argocd-team-a --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.4/manifests/namespace-install.yaml

# 3. Настраиваем tenant-scoped AppProject
kubectl apply -f - <<'EOF'
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-a
  namespace: argocd-team-a
spec:
  sourceRepos:
    - "https://github.com/myorg/team-a/*"
  destinations:
    - server: https://prod-cluster.example.com
      namespace: team-a-prod
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: ""
      kind: Service
EOF
```

Ограничения namespace-scoped режима:
- Нельзя деплоить в `kubernetes.default.svc` (in-cluster) — нужен внешний кластер.
- CRD должны быть установлены администратором.
- ApplicationSet Controller и Notifications тоже scoped.

### Сценарий 6: Project-scoped репозитории и кластеры (self-service)

Разработчик может добавлять свои репозитории/кластеры в проект без обращения к администратору.

```yaml
# argocd-rbac-cm
data:
  policy.csv: |
    # Разрешить admin проекта управлять репозиториями
    p, proj:team-a:admin, repositories, create, team-a/*, allow
    p, proj:team-a:admin, repositories, delete, team-a/*, allow
    p, proj:team-a:admin, repositories, update, team-a/*, allow
    p, proj:team-a:admin, clusters, create, team-a/*, allow
    p, proj:team-a:admin, clusters, delete, team-a/*, allow
    p, proj:team-a:admin, clusters, update, team-a/*, allow
```

```bash
# Разработчик добавляет репозиторий в свой проект
argocd repo add --name my-repo \
  https://github.com/myorg/team-a/special-repo.git \
  --type git --project team-a
```

Секрет репозитория будет project-scoped:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: argocd-my-repo
  labels:
    argocd.argoproj.io/secret-type: repository
type: Opaque
stringData:
  project: team-a
  name: argocd-my-repo
  url: https://github.com/myorg/team-a/special-repo.git
  username: ****
  password: ****
```

**Ограничение:** Project-scoped репозитории с templated `project` в ApplicationSet не поддерживаются (нельзя использовать `{{...}}` в поле `project` при project-scoped repo).

### Сценарий 7: Global Projects (наследование конфигурации)

Один проект задаёт базовые политики, от которых наследуют другие проекты через label selector.

```yaml
# Базовый глобальный проект
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: prod-baseline
  labels:
    env: prod
spec:
  namespaceResourceBlacklist:
    - group: ""
      kind: Secret
  syncWindows:
    - kind: deny
      schedule: "0 0 * * 0,6"
      duration: 24h
      namespaces:
        - "prod-*"
---
# Дочерний проект наследует политики
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-a-prod
  labels:
    env: prod
spec:
  sourceRepos:
    - "https://github.com/myorg/team-a/*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: team-a-prod
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
  # Унаследовано из prod-baseline:
  # - namespaceResourceBlacklist (Secret)
  # - syncWindows (deny on weekends)
```

Настройка в `argocd-cm`:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  globalProjects: |-
    - labelSelector:
        matchExpressions:
          - key: env
            operator: In
            values:
              - prod
      projectName: prod-baseline
```

### Сценарий 8: Source Integrity (GPG commit verification)

Замена устаревшего `signatureKeys` новым `sourceIntegrity` (v3.5+).

```yaml
# AppProject с GPG-проверкой коммитов
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production
  namespace: argocd
spec:
  sourceRepos:
    - "https://github.com/myorg/prod-*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: production
  sourceIntegrity:
    git:
      policies:
        - repos:
            - url: "https://github.com/myorg/prod-*"
          gpg:
            mode: strict
            keys:
              - "D56C4FCA57A46444"
```

**Миграция с `signatureKeys` → `sourceIntegrity`:**

Старый способ (deprecated, удаляется в следующей major версии):
```yaml
spec:
  signatureKeys:
    - keyID: "D56C4FCA57A46444"
```

**Важно:** При включённой `sourceIntegrity` синхронизация с локальных источников (`argocd app sync --local`) невозможна до тех пор, пока критерии не будут выполнены.

### Сценарий 9: Namespace-per-tenant изоляция

Выделение namespace для каждого тенанта с NetworkPolicy и ResourceQuota.

```yaml
# Namespace для team-a
apiVersion: v1
kind: Namespace
metadata:
  name: team-a
  labels:
    tenant: team-a
    environment: production
    pod-security.kubernetes.io/enforce: restricted
---
# NetworkPolicy: Default Deny + разрешить Argo CD и DNS
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: tenant-isolation
  namespace: team-a
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              app.kubernetes.io/name: argocd
      ports:
        - port: 8082
          protocol: TCP
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    - to:
        - namespaceSelector: {}
      ports:
        - port: 443
          protocol: TCP
        - port: 6443
          protocol: TCP
```

```yaml
# ResourceQuota для tenant namespace
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-a-quota
  namespace: team-a
spec:
  hard:
    requests.cpu: "10"
    requests.memory: 20Gi
    limits.cpu: "20"
    limits.memory: 40Gi
    pods: "100"
    count/secrets: "50"
    count/configmaps: "100"
    count/services: "30"
```

### Сценарий 10: Controller Sharding для масштабирования

Для 1000+ приложений используется шардирование application-controller.

```yaml
# argocd-cm — настройка алгоритма шардирования
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  # Алгоритмы: "legacy" (default, hash-based), "round-robin", "consistent"
  controller.sharding.algorithm: "legacy"
  # Для dynamic cluster distribution (alpha, v2.9+):
  # использовать Deployment вместо StatefulSet и env ARGOCD_ENABLE_DYNAMIC_CLUSTER_DISTRIBUTION=true
```

```bash
# Проверка распределения приложений по шардам
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller \
  -c application-controller --tail=100 | grep -i shard
# → application set: 0, shard: 0, app: team-a-app-1
# → application set: 0, shard: 1, app: team-b-app-1
```

## Операции и команды

### Управление проектами

```bash
# Список всех проектов
argocd proj list

# Создание проекта
argocd proj create team-a \
  --description "Team A project" \
  --src https://github.com/myorg/team-a/* \
  --dest https://kubernetes.default.svc,team-a-prod

# Добавление роли с policy
argocd proj role create team-a ci-deployer
argocd proj role add-policy team-a ci-deployer \
  --actions sync,get \
  --resource applications \
  --object team-a/* \
  --permission allow

# Генерация JWT-токена для роли
argocd proj role create-token team-a ci-deployer -e 720h

# Удаление роли
argocd proj role delete team-a ci-deployer

# Обновление проекта
argocd proj set team-a --src !https://github.com/myorg/forbidden/*

# Удаление проекта (только если нет привязанных приложений)
argocd proj rm team-a
```

### Управление правами и доступом

```bash
# Просмотр всех приложений в проекте
argocd app list --project team-a

# Проверка RBAC для пользователя
argocd account get-user-info --account <username>

# Просмотр проекта (yaml)
argocd proj get team-a -o yaml

# Проверка конкретного разрешения
argocd admin settings rbac can role:backend-dev sync applications 'backend/*'

# Валидация RBAC конфигурации
argocd admin settings rbac validate
# → RBAC configuration is valid

# Проверка fine-grained прав (v3.0+)
argocd admin settings rbac can role:team-a delete/*/Pod/*/* 'team-a/my-app'
# → yes

# Просмотр JWT токенов роли проекта
kubectl get appproject team-a -n argocd -o jsonpath='{.spec.roles[*].jwtTokens}'

# Проверка истекания токена
argocd account generate-token --account ci-bot | cut -d. -f2 | base64 -d | jq '.exp'
```

### Управление окнами синхронизации

```bash
# Добавить окно
argocd proj windows add production \
  --kind allow \
  --schedule "0 22 * * *" \
  --duration 1h \
  --applications "*"

# Обновить namespaces
argocd proj windows update production 0 --namespaces default,prod-1,prod-2

# Включить overrun (v3.5+)
argocd proj windows enable-sync-overrun production 0

# Разрешить ручной синк в окне
argocd proj windows enable-manual-sync production 0

# Список окон
argocd proj windows list production
```

### Диагностика изоляции

```bash
# Проверка, что тенант НЕ видит чужие namespace
kubectl auth can-i list pods --namespace=other-team-prod --as=alice
# → no

# Проверка, что тенант НЕ имеет cluster-admin
kubectl auth can-i create clusterrolebindings --as=alice
# → no

# Проверка project-scoped репозитория
kubectl get secret -n argocd -o jsonpath='{range .items[?(@.data.project=="team-a")]}{.metadata.name}{"\n"}{end}'

# Проверка NetworkPolicy в tenant namespace
kubectl get networkpolicy -n team-a

# Проверка ResourceQuota
kubectl describe quota team-a-quota -n team-a

# Проверка, что default project ограничен
kubectl get appproject default -n argocd -o jsonpath='{.spec.sourceRepos}'
# → []

# Проверка sourceNamespaces для проекта
kubectl get appproject team-a -n argocd -o jsonpath='{.spec.sourceNamespaces}'
# → [team-a-*]

# Проверка destinationServiceAccounts
kubectl get appproject team-a -n argocd -o jsonpath='{.spec.destinationServiceAccounts}'
```

### Мониторинг (Prometheus метрики)

```promql
# Приложения с активным deny-окном
argocd_app_sync_window{window_kind="deny"} == 1

# Синхронизации, заблокированные окнами (v3.5+)
argocd_app_sync_blocked == 1

# Ошибки в конфигурации окон (fail-closed, v3.5+)
argocd_app_sync_window_error == 1

# Приложения в Degraded статусе по проекту
argocd_app_info{project="team-a", health_status="Degraded"} > 0

# Количество приложений на шард
count by(shard) (argocd_app_info)
```

## Диагностика

### Типичные ошибки мультитенантности

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `application is not permitted` | AppProject `sourceRepos` не разрешает репозиторий | Добавьте URL в `sourceRepos` проекта |
| `application destination is not permitted` | Namespace/cluster не в `destinations` | Добавьте назначение в `destinations` |
| `resource type is not permitted` | Тип ресурса не в whitelist/blacklist | Добавьте тип в `namespaceResourceWhitelist` |
| `namespace is not permitted` | Application CR в namespace не в `sourceNamespaces` | Добавьте namespace в `sourceNamespaces` проекта |
| `permission denied` | RBAC не разрешает действие | Проверьте policy.csv и project roles |
| `permission denied` (sync) | `deny` имеет приоритет над `allow` | Проверьте порядок правил; deny всегда побеждает |
| `project not found` | AppProject не существует | Создайте AppProject |
| `Sync operation blocked by sync window` | Синхронизация попала в deny-окно | Подождите, или используйте `manualSync: true` |
| `ResourceComparison` (source integrity) | Коммит не GPG-подписан | Подпишите коммит или добавьте ключ в `sourceIntegrity` |
| `orphaned resources detected` | Ресурсы в namespace не управляются Argo CD | Включите `orphanedResources` в AppProject или очистите |
| `application project was not found` | Application ссылается на несуществующий проект | Проверьте поле `spec.project` Application CR |

### Пошаговая диагностика при ошибке `permission denied`

```text
1. argocd account get-user-info
   ├── Нет? → Проблема аутентификации (SSO, токен, локальный аккаунт)
   └── Есть? → Перейдите к шагу 2

2. argocd admin settings rbac can <role> <action> <resource> <object>
   ├── yes → Доступ есть на уровне RBAC, проверьте AppProject restrictions
   └── no → Перейдите к шагу 3

3. kubectl get configmap argocd-rbac-cm -n argocd -o yaml
   ├── policy.default задан? → Нет? Добавьте role:readonly
   ├── policy.csv содержит нужные p, правила? → Нет? Добавьте
   ├── g, маппинги корректны? → Нет? Исправьте названия групп
   └── scopes настроен? → Нет? Добавьте scopes: "[groups]"

4. Проверьте AppProject:
   kubectl get appproject <project> -n argocd -o yaml
   ├── namespaceResourceWhitelist/Blacklist блокирует?
   ├── destinations разрешен?
   ├── sourceRepos разрешены?
   ├── sourceNamespaces включает ли namespace Application CR?
   └── syncWindows не блокируют?
```

## Лучшие практики

### Архитектура и паттерны

- **Project-per-team:** Рекомендуется для организаций >5 команд. Каждая команда изолирована в своём AppProject с собственными ролями, репозиториями и назначениями.
- **Project-per-environment:** Используйте для разделения dev/staging/prod. Production требует самых строгих ограничений (blacklist Secret, sync windows, limited roles).
- **Namespace-per-tenant:** Для полной изоляции tenant namespace с Default Deny NetworkPolicy, ResourceQuota и LimitRange.
- **Applications-in-any-Namespace:** Для self-service команд, которым нужно управлять своими Application CR. Используйте `sourceNamespaces` для ограничения.
- **Namespace-scoped Argo CD:** Для враждебных тенантов (external customers), где каждая команда/клиент получает изолированный namespace с Argo CD.
- **Project-scoped репозитории/кластеры:** Для self-service, позволяющее командам добавлять свои репозитории без обращения к администратору.
- **Global projects:** Для наследования базовых политик (prod база) через label selector.

### Безопасность

- **Харденинг default project:** Всегда ограничивайте default project — `sourceRepos: []`, `destinations: []`, blacklist всех ресурсов.
- **SSO groups:** Интегрируйте с OIDC/LDAP для автоматического назначения ролей. Используйте `groups` claim.
- **Namespace isolation:** Используйте NetworkPolicy с Default Deny для tenant namespaces.
- **Fine-grained RBAC:** Используйте `update/*` и `delete/*` паттерны (v3.0+) для ограничения действий на sub-ресурсы.
- **GPG/Source Integrity:** Включайте `sourceIntegrity` для production-проектов (наследник устаревшего `signatureKeys`).
- **destinationServiceAccounts:** Используйте имперсонацию service account'ов тенантов для синхронизации — тенант не получает прямые кластерные токены.
- **Exec/terminal:** Запрещайте `exec create` для большинства ролей через RBAC.
- **Deny по умолчанию:** `policy.default: role:readonly`, явно разрешайте только необходимое.

### Производительность и масштабирование

- **Controller sharding:** Для 1000+ приложений используйте sharding (`controller.sharding.algorithm`).
- **ApplyOutOfSyncOnly:** Оптимизирует применение только изменённых ресурсов.
- **Shallow Git Cloning:** Используйте для монорепозиториев (>1000 файлов).

### Операции и онбординг

- **Единый шаблон namespace:** `<команда>-<окружение>` с метками `team`, `environment`, `cost-centre`, `contact`.
- **ResourceQuota + LimitRange:** Всегда вместе — LimitRange подставляет `requests` по умолчанию, а без них квоты на `requests.*` блокируют создание подов.
- **Object count quotas:** Ограничивайте `count/secrets`, `count/configmaps`, `count/pods` для защиты etcd.
- **PSA (Pod Security Admission):** Применяйте профиль `restricted` для prod namespace через метку.

### Cleanup (офбординг тенанта)

```bash
# 1. Экспорт данных перед удалением
kubectl get all,secrets,configmaps -n tenant-x --no-headers | wc -l

# 2. Удаление Application CR
argocd app list --project tenant-x --hard-refresh

# 3. Удаление namespace (вместе с ресурсами)
kubectl delete namespace tenant-x --wait

# 4. Очистка project-scoped секретов
kubectl get secret -n argocd -o jsonpath='{range .items[?(@.data.project=="tenant-x")]}{.metadata.name}{"\n"}{end}' \
  | xargs -I{} kubectl delete secret {} -n argocd
```

## Ограничения и edge cases

### Ограничения

- **Нет вложенности проектов:** Проекты не могут иметь родительских/дочерних связей. Для наследования используйте Global Projects.
- **Нет cross-project RBAC:** Роли не могут ссылаться на несколько проектов. Используйте глобальные роли в `policy.csv` для кросс-проектного доступа.
- **Shared controller:** Все проекты используют один контроллер (без sharding) — производительность. Шардируйте для масштабирования.
- **Одна policy.csv:** Все правила хранятся в одном ConfigMap. Нет возможности разделить политики по namespace.
- **Namespace-scoped режим:** Не поддерживает in-cluster деплой (`kubernetes.default.svc`). Требуется внешний кластер для destinations.
- **Project-scoped репозитории + templated project:** ApplicationSet с templated `project` (`{{...}}`) не работает с project-scoped репозитериями.
- **Source Integrity + local sync:** При включённой `sourceIntegrity` нельзя синхронизировать с локальных источников (`argocd app sync --local`).
- **SignatureKeys deprecated:** Устаревшее `signatureKeys` удаляется в следующей major версии. Мигрируйте на `sourceIntegrity`.
- **Нет wildcard для действий:** Нельзя написать `p, role:X, applications, *, proj/*, allow` — каждое действие требует отдельного правила.

### Edge Cases

- **Удаление проекта с активными приложениями:** Приложения переходят в `Unknown` статус. Сначала перенесите приложения в другой проект.
- **Cross-project dependencies:** Нет встроенного механизма для зависимостей между проектами. Используйте Sync Waves + App-of-Apps.
- **Shared Secrets:** Secrets между проектами не изолированы на уровне AppProject — только через namespace. Используйте `namespaceResourceBlacklist` для `Secret` в prod.
- **Controller sharding по проектам:** Возможен, но требует ручной настройки `controller.sharding.algorithm` и соответствия репликам Deployment.
- **Deny vs Allow приоритет:** `deny` всегда побеждает `allow`. В order важен: первое совпадение побеждает, но deny имеет приоритет на одинаковом уровне специфичности.
- **Fine-grained RBAC inheritance (v3.0+):** По умолчанию `update`/`delete` без `/*` не применяются к sub-ресурсам. Для обратной совместимости установите `server.rbac.disableApplicationFineGrainedRBACInheritance: "false"` в `argocd-cm`.
- **Application в чужом namespace:** Без `sourceNamespaces` в AppProject Application CR из tenant namespace будет отклонён.
- **Orphaned resources:** При включённом `orphanedResources` контроллер мониторит namespace на наличие ресурсов не из Argo CD. Это создаёт нагрузку — включайте только на well-scoped namespaces.
- **Permit-only project-scoped clusters:** При `permitOnlyProjectScopedClusters: true` приложения могут синхронизироваться только на кластеры, зарегистрированные в проекте.
- **Project-scoped репозитории и ApplicationSet:** Если ApplicationSet использует templated `project`, project-scoped репозитории недоступны.

## Дополнительная информация

### См. также

- [RBAC — модель доступа](./argocd_rbac_deep.md) — политика policy.csv, built-in роли, fine-grained RBAC, JWT-токены
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — поля спецификации, роли, sync windows
- [SSO с GitLab](./argocd_sso_gitlab.md) — OIDC-аутентификация и группы
- [Установка и настройка](./argocd_installation_and_setup.md) — развёртывание, HA, mTLS
- [Sync Windows](./synchronization/scenarios/sync_windows.md) — временные окна синхронизации
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging
- [Disaster Recovery](./argocd_disaster_recovery.md) — бэкап, восстановление, etcd snapshot, HA
- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — Multiple Sources, Helm+Git
- [Отслеживание ресурсов](./argocd_resource_tracking.md) — Label, Annotation, Annotation+Label
- [Удаление и очистка](./argocd_deletion_and_cleanup.md) — Prune, Cascading Deletion, Finalizers
- [Kubernetes Multi-tenancy](../../Kubernetes/Concepts/multi-tenancy.md) — Namespace, NetworkPolicy, ResourceQuota, RBAC, Capsule, vcluster

### Ссылки

- [Project Specification Reference](https://argo-cd.readthedocs.io/en/stable/operator-manual/project-specification)
- [Projects — User Guide](https://argo-cd.readthedocs.io/en/stable/user-guide/projects)
- [RBAC Configuration](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac)
- [Source Integrity](https://argo-cd.readthedocs.io/en/stable/user-guide/source-integrity)
- [Orphaned Resources Monitoring](https://argo-cd.readthedocs.io/en/stable/user-guide/orphaned-resources)
- [Applications in any namespace](https://argo-cd.readthedocs.io/en/stable/operator-manual/app-any-namespace/)
- [Multi-Tenancy in Argo CD (ArgoCon 2023)](https://static.sched.com/hosted_files/colocatedeventsna2023/66/ArgoCD_Multitenancy_ArgoCon2023_Final.pdf)
