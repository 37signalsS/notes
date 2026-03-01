# ArgoCD: Синхронизация и её политики

> **SSoT:** Этот файл — основной источник истины для политик синхронизации ArgoCD.

## Определения

| Термин | Определение |
| :--- | :--- |
| **Синхронизация (Synchronization)** | Процесс приведения состояния Kubernetes-кластера в соответствие с конфигурацией из Git-репозитория |
| **Desired State** | Желаемое состояние, описанное в манифестах (YAML, Helm, Kustomize) в Git |
| **Live State** | Фактическое состояние объектов в Kubernetes-кластере |
| **OutOfSync** | Статус приложения при расхождении `Live State` и `Desired State` |
| **Sync Status** | Соответствие состояния кластера Git: `Synced` или `OutOfSync` |
| **Health Status** | Состояние здоровья ресурсов: `Healthy`, `Progressing`, `Degraded`, `Suspended`, `Missing` |

## Базовые концепции

### Цикл сверки (Reconciliation Loop)

ArgoCD Application Controller с заданной периодичностью (по умолчанию 3 минуты) или по триггеру (webhook, manual refresh):

1. Клонирует Git-репозиторий
2. Рендерит манифесты (Helm-шаблон, Kustomize, plain YAML)
3. Сравнивает результат с `Live State` в кластере
4. При расхождении присваивает статус `OutOfSync`

### Политики синхронизации

Определяются в секции `syncPolicy` манифеста `Application`:

```yaml
spec:
  syncPolicy:
    automated:
      prune: true      # Удалять ресурсы, отсутствующие в Git
      selfHeal: true   # Исправлять дрейф конфигурации
    syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true
    - PrunePropagationPolicy=foreground
    - PruneLast=true
```

## Практические сценарии

### Сценарий 1: Ручная синхронизация (Manual Sync)

**Поведение по умолчанию.** ArgoCD обнаруживает расхождение и показывает статус `OutOfSync`, но не применяет изменения автоматически.

**Когда использовать:**
- Production-окружения с требованием ручного подтверждения
- Критичные изменения, требующие проверки
- Окружения с compliance-требованиями

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://git.example.com/repo.git
    path: my-app
    targetRevision: HEAD
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
  # syncPolicy не указан — Manual по умолчанию
```

**Команды CLI:**
```bash
# Просмотр различий
argocd app diff my-app

# Запуск синхронизации
argocd app sync my-app

# Синхронизация с конкретной ревизией
argocd app sync my-app --revision abc123

# Ожидание завершения
argocd app wait my-app --sync --health
```

### Сценарий 2: Автоматическая синхронизация (Auto-Sync)

ArgoCD автоматически применяет изменения из Git при их обнаружении.

**Когда использовать:**
- Dev/Staging-окружения
- Приложения с высокой частотой развёртываний
- Команды с зрелыми CI/CD-процессами

**Ключевые параметры:**

| Параметр | Описание |
| :--- | :--- |
| `prune: true` | Автоматически удалять ресурсы, удалённые из Git |
| `selfHeal: true` | Автоматически исправлять ручные изменения в кластере |

```yaml
spec:
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true
    - PrunePropagationPolicy=foreground
    - PruneLast=true
    - RespectIgnoreDifferences=true
```

**Опции `syncOptions`:**

| Опция | Описание |
| :--- | :--- |
| `CreateNamespace=true` | Автоматически создавать целевой namespace |
| `ServerSideApply=true` | Использовать Server-Side Apply для обработки конфликтов |
| `PrunePropagationPolicy=foreground` | Ждать удаления ресурсов перед продолжением |
| `PruneLast=true` | Удалять ресурсы после применения остальных изменений |
| `RespectIgnoreDifferences=true` | Игнорировать указанные различия при синхронизации |

### Сценарий 3: Управление порядком — Sync Waves и Hooks

**Sync Waves** — аннотация для группировки ресурсов и применения в определённом порядке.

```yaml
# 1. CRD (wave -2)
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: mycrds.example.com
  annotations:
    argocd.argoproj.io/sync-wave: "-2"

# 2. Namespace (wave -1)
apiVersion: v1
kind: Namespace
metadata:
  name: my-app
  annotations:
    argocd.argoproj.io/sync-wave: "-1"

# 3. Deployment и Service (wave 0)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  annotations:
    argocd.argoproj.io/sync-wave: "0"

# 4. Ingress (wave 1)
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-ingress
  annotations:
    argocd.argoproj.io/sync-wave: "1"
```

**Hooks** — ресурсы для выполнения действий до/во время/после синхронизации.

| Hook | Описание |
| :--- | :--- |
| `PreSync` | Выполняется перед синхронизацией (миграции БД, тесты) |
| `Sync` | Выполняется во время синхронизации |
| `PostSync` | Выполняется после синхронизации (уведомления, smoke-тесты) |
| `Skip` | Пропускается при синхронизации |

**Пример PreSync Hook для миграции БД:**
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migration
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      containers:
      - name: migration
        image: my-app:migration
        command: ["rails", "db:migrate"]
      restartPolicy: Never
  backoffLimit: 1
```

**Политики удаления Hooks (`hook-delete-policy`):**

| Политика | Описание |
| :--- | :--- |
| `HookSucceeded` | Удалить после успешного выполнения |
| `HookFailed` | Удалить после неудачи |
| `BeforeHookCreation` | Удалить старый hook перед созданием нового |

### Сценарий 4: Окна синхронизации (Sync Windows)

**Sync Windows** ограничивают автоматическую синхронизацию по расписанию. Настраиваются на уровне `AppProject`.

**Когда использовать:**
- Запрет деплоев в нерабочее время
- Code freeze в праздничные периоды
- Ограничение деплоев в часы пик

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production-apps
  namespace: argocd
spec:
  description: "Production приложения"
  sourceRepos:
  - 'https://github.com/my-org/production-repo.git'
  destinations:
  - namespace: 'prod'
    server: 'https://kubernetes.default.svc'
  
  syncWindows:
  # Разрешение: будни 9:00-18:00 MSK
  - kind: allow
    schedule: '0 9-18 * * 1-5'
    duration: 1h
    timeZone: "Europe/Moscow"
    applications:
    - '*-prod'
    manualSync: true  # Ручная синхронизация разрешена всегда
  
  # Запрет: с 25 декабря на неделю
  - kind: deny
    schedule: '0 0 25 12 *'
    duration: 168h  # 7 дней
    timeZone: "Europe/Moscow"
    applications:
    - '*-prod'
```

**Параметры Sync Window:**

| Параметр | Описание |
| :--- | :--- |
| `kind` | `allow` (разрешение) или `deny` (запрет) |
| `schedule` | Cron-выражение |
| `duration` | Длительность окна (например, `1h`, `168h`) |
| `timeZone` | Часовой пояс (например, `Europe/Moscow`) |
| `applications` | Список приложений или wildcard |
| `manualSync` | Разрешить ручную синхронизацию вне окна |

**Проверка активных окон:**
```bash
argocd proj get production-apps
```

### Сценарий 5: Прогрессивная синхронизация (Progressive Sync, v3.x)

**Progressive Sync** — постепенное развёртывание на несколько кластеров с валидацией на каждом этапе.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: progressive-app
  namespace: argocd
spec:
  generators:
  - clusters:
      selector:
        matchLabels:
          environment: production
  template:
    metadata:
      name: 'app-{{name}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/my-org/app.git
        targetRevision: HEAD
        path: manifests
      destination:
        server: '{{server}}'
        namespace: production
      syncPolicy:
        progressiveSync:
          maxUpdate: 1  # Максимум 1 кластер за раз
          steps:
          - maxUpdate: 1
            matchExpressions:
            - key: environment
              operator: In
              values: [staging]
          - maxUpdate: 2
            matchExpressions:
            - key: environment
              operator: In
              values: [production]
```

## Дополнительная информация

### Игнорирование различий (Ignore Differences)

Для ресурсов, где допустим дрейф (например, `replicas` для HPA):

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    jsonPointers:
    - /spec/replicas
  - group: autoscaling
    kind: HorizontalPodAutoscaler
    jqPathExpressions:
    - .spec.minReplicas
    - .spec.maxReplicas
```

### Принудительная синхронизация

```bash
# Принудительное применение (игнорируя различия)
argocd app sync my-app --force

# Пропуск проверки здоровья
argocd app sync my-app --skip-schema-validation
```

### Ссылки

- **[Обзор ArgoCD](./argocd_overview.md)**
- **[Установка и настройка](./argocd_installation_and_setup.md)**
- **[Официальная документация](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)**
