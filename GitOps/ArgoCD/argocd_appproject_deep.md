# Argo CD: AppProject — изоляция, квоты и управление доступом

> **Актуальность (2026):** AppProject — ключевой механизм мультитенантности и изоляции в Argo CD v3.x. Определяет допустимые источники (sourceRepos), назначения (destinations), ограничения на типы ресурсов (clusterResourceWhitelist/namespaceResourceWhitelist), роли и группы пользователей (roles), окна синхронизации (syncWindows), а также квоты на количество приложений и кластеров.

## Предварительные требования

1. **Argo CD установлен** (см. [Установка и настройка](./argocd_installation_and_setup.md)).
2. **kubectl** с доступом к namespace `argocd`.
3. **argocd CLI** настроен.
4. **Понимание RBAC** — AppProject тесно связан с моделью доступа (см. [RBAC](./argocd_rbac_deep.md)).

## Определения

**AppProject** — логическая группировка приложений в Argo CD, определяющая boundaries (границы) доступа: какие Git-репозитории разрешены, в какие кластеры и namespace'ы можно деплоить, какие типы Kubernetes-ресурсов допустимы, а также роли и группы пользователей.

**Source Repo (Источник)** — Git-репозиторий или Helm-чарт, разрешенный для использования в проекте. Указывается через `sourceRepos`. Поддерживаются маски `*` (все) и конкретные URL.

**Destination (Назначение)** — Kubernetes-кластер и namespace, в который разрешен деплой ресурсов проекта. Указывается через `destinations`. Кластер определяется как `server` (URL) или `name`.

**Cluster Resource Whitelist (Whitelist кластерных ресурсов)** — список типов Kubernetes-ресурсов, которые разрешено управлять на уровне кластера (например, `ClusterRole`, `Namespace`). Если не задан — управление кластерными ресурсами запрещено.

**Namespace Resource Whitelist (Whitelist пространственных ресурсов)** — список типов Kubernetes-ресурсов, разрешенных для управления в namespace'ах. Если не задан — разрешены все типы.

**Namespace Resource Blacklist (Blacklist пространственных ресурсов)** — список типов ресурсов, которые запрещены для управления в namespace'ах. Blacklist имеет приоритет над whitelist.

**Role (Роль проекта)** — кастомная роль, определенная внутри AppProject, ограничивающая действия пользователей в рамках конкретного проекта. Отличается от глобальных ролей RBAC.

## Базовые концепции

### Архитектура AppProject

```text
AppProject
├── sourceRepos:       ← Какие Git-репозитории разрешены
│   ├── https://github.com/org/app1
│   └── https://charts.example.com
├── destinations:      ← Куда можно деплоить
│   ├── server: https://kubernetes.default.svc
│   │   namespace: production
│   └── name: staging-cluster
│       namespace: staging
├── clusterResourceWhitelist:  ← Какие кластерные ресурсы разрешены
│   - group: ""
│     kind: Namespace
├── namespaceResourceWhitelist:  ← Какие namespace-ресурсы разрешены
│   - group: "apps"
│     kind: Deployment
│   - group: ""
│     kind: Service
├── namespaceResourceBlacklist:  ← Что запрещено (приоритет над whitelist)
│   - group: ""
│     kind: Secret
├── roles:             ← Кастомные роли проекта
│   - name: developer
│    description: "Разработчик"
│     policies:
│       - p, proj:production:developer, applications, get, production/*, allow
│     groups:
│       - dev-team
├── syncWindows:       ← Окна синхронизации
│   - kind: allow
│     schedule: "0 10 * * 1-5"
│     duration: 8h
└── quotas:            ← Квоты
    - apps: 50
    - clusters: 3
```

### Иерархия проверок

```text
Запрос на деплой
    │
    ▼
1. AppProject.sourceRepos  ← Разрешен ли этот Git-репозиторий?
    │
    ▼
2. AppProject.destinations  ← Разрешен ли этот кластер/namespace?
    │
    ▼
3. AppProject.namespaceResourceWhitelist/Blacklist  ← Разрешен ли этот тип ресурса?
    │
    ▼
4. AppProject.clusterResourceWhitelist  ← Разрешен ли кластерный ресурс?
    │
    ▼
5. RBAC (policy.csv)  ← Есть ли у пользователя право на это действие?
    │
    ▼
6. Sync Windows  ← Разрешено ли синхронизировать в это время?
```

### Связь с RBAC

AppProject определяет **что** разрешено (boundary), а RBAC определяет **кто** может это сделать (identity). Комбинация:

- **AppProject:** `разрешено деплоить Deployment в production`
- **RBAC:** `role:dev-team может sync applications в development/*`
- **Результат:** Разработчик может синхронизовать Deployment, но только в `development`, не в `production`.

## Практические сценарии

### Сценарий 1: Проект для команды разработки

Минимальный проект с ограничениями: только определенные репозитории и namespace.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: development
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: "Проект для команды разработки"
  sourceRepos:
    - "https://github.com/myorg/*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: dev-*
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
    - group: ""
      kind: Pod
  roles:
    - name: developer
      description: "Разработчик"
      policies:
        - p, proj:development:developer, applications, get, development/*, allow
        - p, proj:development:developer, applications, sync, development/*, allow
        - p, proj:development:developer, applications, create, development/*, allow
      groups:
        - dev-team
```

### Сценарий 2: Production с жесткими ограничениями

Production-проект с whitelist ресурсов, запретом Secret и кастомными ролями.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: "Production проект"
  sourceRepos:
    - "https://github.com/myorg/prod-*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: production
    - server: https://prod-cluster.example.com
      namespace: production
  clusterResourceWhitelist:
    - group: ""
      kind: Namespace
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: "apps"
      kind: StatefulSet
    - group: "networking.k8s.io"
      kind: Ingress
    - group: ""
      kind: Service
    - group: ""
      kind: ConfigMap
  namespaceResourceBlacklist:
    - group: ""
      kind: Secret
  roles:
    - name: deployer
      description: "Деплой в production (только sync, без delete)"
      policies:
        - p, proj:production:deployer, applications, get, production/*, allow
        - p, proj:production:deployer, applications, sync, production/*, allow
      groups:
        - sre-team
    - name: viewer
      description: "Только просмотр"
      policies:
        - p, proj:production:viewer, applications, get, production/*, allow
      groups:
        - stakeholder-team
  syncWindows:
    - kind: allow
      schedule: "0 10 * * 1-5"
      duration: 8h
      namespaces:
        - production
    - kind: deny
      schedule: "0 0 * * 0"
      duration: 24h
      namespaces:
        - production
```

### Сценарий 3: Квоты на ресурсы проекта

Ограничение количества приложений и кластеров.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: sandbox
  namespace: argocd
spec:
  description: "Песочница для экспериментов"
  sourceRepos:
    - "*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: sandbox-*
  clusterResourceWhitelist:
    - group: "*"
      kind: "*"
  namespaceResourceWhitelist:
    - group: "*"
      kind: "*"
  # Квоты
  roles:
    - name: sandbox-user
      description: "Пользователь песочницы"
      policies:
        - p, proj:sandbox:sandbox-user, applications, *, sandbox/*, allow
      groups:
        - sandbox-users
```

**Просмотр квот:**
```bash
kubectl get appproject sandbox -n argocd -o jsonpath='{.spec.roles}'
```

### Сценарий 4: Multi-cluster проект

Проект, деплоящий ресурсы в несколько кластеров.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: multi-cluster-apps
  namespace: argocd
spec:
  description: "Мультикластерное приложение"
  sourceRepos:
    - "https://github.com/myorg/multi-cluster/*"
  destinations:
    - name: cluster-east
      namespace: app-east
    - name: cluster-west
      namespace: app-west
    - name: cluster-us
      namespace: app-us
  clusterResourceWhitelist:
    - group: ""
      kind: Namespace
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: ""
      kind: Service
    - group: ""
      kind: ConfigMap
```

### Сценарий 5: Делегирование управления через.roles

Настройка кастомных ролей с granular-доступом.

```yaml
roles:
  # Роль для создания приложений (без sync)
  - name: app-creator
    description: "Создание приложений, без деплоя"
    policies:
      - p, proj:myproject:app-creator, applications, get, myproject/*, allow
      - p, proj:myproject:app-creator, applications, create, myproject/*, allow
    groups:
      - platform-team

  # Роль для sync (без delete)
  - name: releaser
    description: "Синхронизация приложений"
    policies:
      - p, proj:myproject:releaser, applications, get, myproject/*, allow
      - p, proj:myproject:releaser, applications, sync, myproject/*, allow
    groups:
      - ci-bot
      - sre-team

  # Роль для просмотра логов
  - name: log-viewer
    description: "Просмотр логов и метрик"
    policies:
      - p, proj:myproject:log-viewer, applications, get, myproject/*, allow
      - p, proj:myproject:log-viewer, logs, get, myproject/*, allow
    groups:
      - support-team
```

**Проверка доступа роли проекта:**
```bash
argocd admin settings rbac can role:app-creator create applications 'myproject/new-app'
# → yes

argocd admin settings rbac can role:app-creator sync applications 'myproject/new-app'
# → no
```

### Сценарий 6: Sync Windows в AppProject

Защита production от деплоев в нерабочее время.

```yaml
spec:
  syncWindows:
    # Разрешено: пн-пт 10:00-18:00
    - kind: allow
      schedule: "0 10 * * 1-5"
      duration: 8h
      applications:
        - "*"
      namespaces:
        - production
      manualSync: true  # Ручная синхронизация разрешена

    # Запрещено: выходные
    - kind: deny
      schedule: "0 0 * * 0,6"
      duration: 24h
      applications:
        - "*"
      namespaces:
        - production

    # Запрещено: пятница в последних днях месяца (emergency freeze)
    - kind: deny
      schedule: "0 0 28-31 * 5"
      duration: 24h
      applications:
        - "*"
```

**Подробнее о Sync Windows:** см. [Sync Windows](./synchronization/scenarios/sync_windows.md).

## Диагностика

### Базовые команды

```bash
# Просмотр всех проектов
argocd proj list
kubectl get appproject -n argocd

# Просмотр деталей проекта
argocd proj get <project-name>
kubectl get appproject <project-name> -n argocd -o yaml

# Просмотр приложений в проекте
argocd app list --project <project-name>

# Проверка квот
kubectl get appproject <project-name> -n argocd -o jsonpath='{.spec.roles}'
```

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `application repo is not permitted` | Репозиторий не в `sourceRepos` | Добавьте URL в `sourceRepos` проекта |
| `application destination is not permitted` | Кластер/namespace не в `destinations` | Добавьте назначение в `destinations` |
| `resource type is not permitted` | Тип ресурса не в whitelist | Добавьте тип в `namespaceResourceWhitelist` |
| `resource type is explicitly blacklisted` | Тип ресурса в blacklist | Удалите тип из `namespaceResourceBlacklist` |
| `permission denied` | Нет роли в проекте | Добавьте роль или назначьте группу |

## Лучшие практики

- **Один проект на команду/окружение:** Не создавайте "супер-проекты" с `*/*` — это подрывает изоляцию.
- **Явный whitelist:** Не полагайтесь на поведение по умолчанию (все ресурсы) — явно указывайте разрешенные типы.
- **Blacklist для Secret:** В production обязательно исключайте `Secret` из namespaceResourceWhitelist.
- **Финализаторы:** Всегда добавляйте `finalizers: [resources-finalizer.argocd.argoproj.io]` для корректного удаления.
- **Роли проекта vs глобальные роли:** Используйте роли проекта для granular-контроля, глобальные — для общего доступа.
- **Sync Windows в AppProject:** Всегда настраивайте окна для production.

## Ограничения и edge cases

### Ограничения

- **Нет вложенности проектов:** Проекты не могут иметь родительских/дочерних связей.
- **Кластерные ресурсы:** `clusterResourceWhitelist` не поддерживает маски для конкретных экземпляров — только по типу.
- **Синхронное обновление:** При изменении AppProject ограничения применяются немедленно к существующим приложениям.

### Edge Cases

- **Удаление проекта с приложениями:** При удалении AppProject все связанные приложения переходят в `Unknown` статус.
- **Пустой whitelist:** Если `namespaceResourceWhitelist` не задан и `namespaceResourceBlacklist` тоже — разрешены все типы (кроме кластерных).
- **Конфликт whitelist/blacklist:** Blacklist всегда имеет приоритет. Если тип в обоих — он запрещен.
- **Multiple destinations с одним namespace:** допустимо, но может привести к конфликтам при деплое.

## Дополнительная информация

### См. также

- [RBAC — модель доступа](./argocd_rbac_deep.md)
- [SSO с GitLab (OIDC groups)](./argocd_sso_gitlab.md)
- [Sync Windows](./synchronization/scenarios/sync_windows.md)
- [Установка и настройка](./argocd_installation_and_setup.md)
- [Мультитенантность](./argocd_multi_tenancy.md) — Паттерны мультитенантности, tenant isolation, project-per-team.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — Multiple Sources, sourceHydrator, Helm+Git, CI-рендеринг vs Multi-Source.
- [Удаление и очистка](./argocd_deletion_and_cleanup.md) — Prune, Cascading Deletion, Propagation Policy, Orphan, Finalizers.

### Ссылки

- [AppProject Reference](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#projects)
- [RBAC with Projects](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/#project-scoped-roles)
- [Sync Windows](https://argo-cd.readthedocs.io/en/stable/operator-manual/sync_windows/)
