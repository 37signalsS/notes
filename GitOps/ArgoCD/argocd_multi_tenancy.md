# Argo CD: Мультитенантность — паттерны изоляции и project-per-team

> **Актуальность (2026):** Мультитенантность в Argo CD v3.x реализуется через комбинацию AppProject (ограничения на источники/назначения), RBAC (роли для пользователей/групп), SSO (OIDC/LDAP для аутентификации) и Namespace (сетевая и resource изоляция). Основные паттерны: Project-per-team, Project-per-environment, Shared-controller с tenant namespaces.

## Предварительные требования

1. **Argo CD установлен** (см. [Установка и настройка](./argocd_installation_and_setup.md)).
2. **kubectl** с доступом к namespace `argocd`.
3. **argocd CLI** настроен.
4. **SSO настроен** (рекомендуется) — см. [SSO с GitLab](./argocd_sso_gitlab.md).
5. **Понимание RBAC и AppProject** — см. [RBAC](./argocd_rbac_deep.md), [AppProject](./argocd_appproject_deep.md).

## Определения

**Мультитенантность (Multi-tenancy)** — архитектурный паттерн, при котором один экземпляр Argo CD обслуживает несколько независимых команд/проектов с изоляцией данных, конфигурации и доступа.

**Tenant (Тенант)** — команда, проект или бизнес-единица, использующая Argo CD с изолированным доступом к своим приложениям и ресурсам.

**Project-per-team** — паттерн, при котором каждая команда имеет свой AppProject с уникальными restrictions, roles и sync windows.

**Project-per-environment** — паттерн, при котором каждое окружение (dev/staging/prod) является отдельным AppProject с разными уровнями доступа.

**Tenant Namespace** — Kubernetes-namespace, выделенный для конкретного тенанта. Обеспечивает сетевую и resource изоляцию.

**Shared Controller** — единый экземпляр argocd-application-controller, обслуживающий несколько тенантов через AppProject и RBAC.

## Базовые концепции

### Архитектура мультитенантности

```text
┌──────────────────────────────────────────────────────────┐
│  Argo CD (shared instance)                               │
│                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │ AppProject  │  │ AppProject  │  │ AppProject  │      │
│  │ (team-a)    │  │ (team-b)    │  │ (shared)    │      │
│  │             │  │             │  │             │      │
│  │ repos:      │  │ repos:      │  │ repos:      │      │
│  │  team-a/*   │  │  team-b/*   │  │  *          │      │
│  │ dests:      │  │ dests:      │  │ dests:      │      │
│  │  ns:team-a  │  │  ns:team-b  │  │  ns:shared  │      │
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

### Матрица изоляции

| Уровень изоляции | Механизм | Что ограничивает |
| :--- | :--- | :--- |
| **AppProject.sourceRepos** | Какие Git-репозитории разрешены | Доступ к коду |
| **AppProject.destinations** | Куда можно деплоить | Кластеры и namespace'ы |
| **AppProject.namespaceResourceWhitelist** | Какие типы ресурсов разрешены | CRD, Secrets и др. |
| **RBAC (policy.csv)** | Кто может做什么 | Действия с приложениями |
| **SSO groups** | Кто аутентифицирован | Доступ к Argo CD |
| **Namespace** | Сетевая и resource изоляция | Pod-to-Pod трафик, ресурсы |

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
    g, sre-team, role:sre

  scopes: "[groups]"
```

### Сценарий 2: Project-per-environment

Каждое окружение — отдельный AppProject с разными restriction.

```yaml
# Development
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: dev
spec:
  sourceRepos: ["*"]  # Все репозитории
  destinations:
    - server: https://kubernetes.default.svc
      namespace: dev-*
  namespaceResourceWhitelist:
    - group: "*"
      kind: "*"  # Все типы ресурсов
  roles:
    - name: developer
      policies:
        - p, proj:dev:developer, applications, *, dev/*, allow  # Все действия
      groups:
        - dev-team

---
# Staging
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: staging
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

---
# Production
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production
spec:
  sourceRepos:
    - "https://github.com/myorg/prod-*"  # Только prod репозитории
  destinations:
    - server: https://kubernetes.default.svc
      namespace: production
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: ""
      kind: Service
  namespaceResourceBlacklist:
    - group: ""
      kind: Secret  # Запрет на Secret
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
    - kind: deny
      schedule: "0 0 * * 0,6"
      duration: 24h
```

### Сценарий 3: Namespace-per-tenant изоляция

Выделение namespace для каждого тенанта с NetworkPolicy.

```yaml
# Namespace для team-a
apiVersion: v1
kind: Namespace
metadata:
  name: team-a
  labels:
    tenant: team-a
    env: production

---
# NetworkPolicy для изоляции
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
    # Только от Argo CD controller
    - from:
        - namespaceSelector:
            matchLabels:
              name: argocd
  egress:
    # Только DNS и Kubernetes API
    - to:
        - namespaceSelector: {}
      ports:
        - port: 53
        - port: 6443
```

## Диагностика

### Базовые команды

```bash
# Просмотр всех проектов
argocd proj list

# Просмотр приложений в проекте
argocd app list --project team-a

# Проверка RBAC для пользователя
argocd account get-user-info --account <username>

# Просмотр проекта
argocd proj get team-a -o yaml

# Проверка доступа
argocd admin settings rbac can role:backend-dev sync applications 'backend/*'
```

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `application is not permitted` | AppProject не разрешает этот репозиторий | Обновите `sourceRepos` |
| `permission denied` | RBAC не разрешает действие | Добавьте роль в policy.csv |
| `project not found` | AppProject не существует | Создайте AppProject |
| `namespace is not permitted` | Namespace не в `destinations` | Добавьте namespace в destinations |

## Лучшие практики

- **Project-per-team:** Рекомендуется для организаций >5 команд.
- **Project-per-environment:** Используйте для разделения dev/staging/prod.
- **SSO groups:** Интегрируйте с OIDC/LDAP для автоматического назначения ролей.
- **Namespace isolation:** Используйте NetworkPolicy для сетевой изоляции.
- **Quotas:** Ограничьте количество приложений и кластеров на проект.
- **Sync Windows:** Настройте разные окна для разных тенантов.

## Ограничения и edge cases

### Ограничения

- **Нет вложенности проектов:** Проекты не могут иметь родительских связей.
- **Нет cross-project RBAC:** Роли не могут ссылаться на несколько проектов.
- **Shared controller:** Все проекты используют один контроллер (производительность).
- **Нет namespace quotas:** Argo CD не ограничивает количество namespace на проект.

### Edge Cases

- **Удаление проекта с активными приложениями:** Приложения переходят в `Unknown`.
- **Cross-project dependencies:** Нет встроенного механизма для зависимостей между проектами.
- **Shared Secrets:** Secrets между проектами не изолированы (только через namespace).
- **Controller sharding по проектам:** Возможен, но требует ручной настройки.

## Дополнительная информация

### См. также

- [RBAC](./argocd_rbac_deep.md)
- [AppProject](./argocd_appproject_deep.md)
- [SSO с GitLab](./argocd_sso_gitlab.md)
- [Установка и настройка](./argocd_installation_and_setup.md)
- [Kubernetes Multi-tenancy](../../Kubernetes/Concepts/multi-tenancy.md)
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Disaster Recovery](./argocd_disaster_recovery.md) — Бэкап, восстановление, etcd snapshot, HA, geo-recovery.
- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — Multiple Sources, sourceHydrator, Helm+Git, CI-рендеринг vs Multi-Source.
- [Отслеживание ресурсов](./argocd_resource_tracking.md) — Методы отслеживания ресурсов: Label, Annotation, Annotation+Label.
- [Удаление и очистка](./argocd_deletion_and_cleanup.md) — Prune, Cascading Deletion, Propagation Policy, Orphan, Finalizers.

### Ссылки

- [Multi-Tenancy in Argo CD](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#projects)
- [RBAC with Projects](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/#project-scoped-roles)
- [Kubernetes Multi-Tenancy](https://kubernetes.io/docs/concepts/security/multi-tenancy/)
