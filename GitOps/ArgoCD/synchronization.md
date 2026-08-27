# ArgoCD — синхронизация и политики

> **Актуальность (2026):** Argo CD v3.x: Server-Side Apply по умолчанию, Progressive Sync для ApplicationSets, PreDelete/PostDelete хуки (v3.3+), OCI-нативность (v3.1+).

## Предварительные требования

1. **Kubernetes кластер:** v1.26+ (рекомендуется v1.28+).
2. **Argo CD установлен:** `kubectl get pods -n argocd` — все поды в статусе `Running`.
3. **Клиент `argocd`:** Установлен и настроен (`argocd login`).
4. **Git-репозиторий:** Доступен с манифестами приложений.
5. **RBAC:** Администратор кластера для первоначальной настройки.

## Определения

**ArgoCD** — декларативный GitOps-инструмент непрерывной доставки для Kubernetes, автоматизирующий развертывание приложений и синхронизацию состояния кластера с Git-репозиторием.

**Желаемое состояние (Desired State)** — эталонная конфигурация ресурсов (YAML, Helm, Kustomize), хранящаяся в Git.

**Фактическое состояние (Live State)** — текущее состояние объектов в кластере Kubernetes.

**Цикл сверки (Reconciliation Loop)** — непрерывный процесс сравнения состояний и устранения расхождений. Состоит из фаз **Refresh** (обнаружение), **Diff** (сравнение) и **Sync** (применение).

**Дрейф конфигурации (Configuration Drift)** — расхождение между тем, что описано в Git, и тем, что реально запущено в кластере (например, после `kubectl edit`).

**Волны синхронизации (Sync Waves)** — механизм управления очередностью деплоя ресурсов на основе их готовности. Каждый ресурс получает аннотацию `argocd.argoproj.io/sync-wave` с целым числом (по умолчанию 0). Ресурсы применяются в порядке возрастания волн.

**Хуки (Hooks)** — запуск эфемерных задач (Jobs) на определенных этапах жизненного цикла синхронизации. Хуки не управляются ArgoCD после завершения и могут быть удалены через `hook-delete-policy`.

**Self-Heal** — механизм автоматического отката ручных правок в кластере к состоянию в Git. Работает при включенном флаге `selfHeal: true` в секции `automated`.

**Prune** — механизм удаления ресурсов в кластере, которых больше нет в Git. Работает при включенном флаге `prune: true`.

**Server-Side Apply (SSA)** — нативный механизм Kubernetes для разрешения конфликтов полей. Логика слияния переносится на сторону API-сервера, что исключает конфликты между несколькими контроллерами.

**Progressive Sync** — поэтапная раскатка `ApplicationSets` по группам кластеров. Позволяет остановить деплой на всю инфраструктуру, если первая группа (Canary) ушла в `Degraded`.

**Reconciliation Pause** — полная остановка сверки для кластера через аннотацию `argocd.argoproj.io/reconciliation-pause: "true"` в секрете кластера.

## Основные концепции

### Детальный цикл сверки

ArgoCD Application Controller работает по событийной модели (Webhook) или по расписанию (по умолчанию 3 минуты):

```
┌─────────────────────────────────────────────────────────────────┐
│                    ArgoCD Reconciliation Loop                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │    Refresh    │───▶│     Diff     │───▶│     Sync     │      │
│  │  (Обнаружение)│    │  (Сравнение) │    │  (Применение)│      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         │                   │                   │               │
│         ▼                   ▼                   ▼               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ repo-server  │    │   controller │    │  K8s API     │      │
│  │ (Git clone,  │    │   (diff,     │    │  (apply,     │      │
│  │  render)     │    │    health)   │    │   delete)    │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

1.  **Фаза Refresh (Обнаружение):**
    - `argocd-repo-server` извлекает манифесты из Git.
    - Выполняется рендеринг (Helm, Kustomize или **[кастомные плагины](./argocd_custom_tooling.md)**).
    - Контроллер получает текущее состояние из API-сервера K8s.
2.  **Фаза Diff (Сравнение):**
    - Выполняется попарное сравнение объектов.
    - Учитываются настройки **[игнорирования различий](./synchronization/ignore_differences.md)**.
    - Формируется статус: `Synced` (всё совпадает) или `OutOfSync` (есть расхождения).
3.  **Фаза Sync (Применение):**
    - Если статус `OutOfSync` и включена автоматизация, контроллер инициирует деплой.
    - Ресурсы применяются согласно **Sync Waves** и **Hooks**.
    - После применения выполняется проверка здоровья (Health Check).

**Интервал сверки:** По умолчанию 3 минуты. Настраивается через `timeout.reconciliation` в `argocd-cm`.

### Методы отслеживания ресурсов (Resource Tracking)

Для того чтобы ArgoCD знал, какими ресурсами он управляет, используется механизм отслеживания. В v3.x поддерживаются следующие методы (настраиваются в `argocd-cm`):

| Метод | Механизм | Рекомендация |
| :--- | :--- | :--- |
| **Labels** | Метка `app.kubernetes.io/instance` | Стандарт, ограничение — длина значения метки (63 символа) |
| **Annotations** | Аннотация `argocd.argoproj.io/tracking-id` | Рекомендуется для избежания проблем с длиной имен |
| **annotation+label** | Оба метода одновременно | Максимальная совместимость |

**Важно:** При использовании Helm рекомендуется метод `annotation`, так как он не конфликтует с управлением аннотациями Helm.

**Пример настройки в `argocd-cm`:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  # Стандартный метод (Labels)
  application.resourceTrackingMethod: label

  # Рекомендуемый метод (Annotations)
  application.resourceTrackingMethod: annotation

  # Максимальная совместимость (Labels + Annotations)
  application.resourceTrackingMethod: annotation+label
```

### Фазы синхронизации

Процесс применения ресурсов разделен на этапы, что позволяет встраивать логику (Hooks) в процесс:

| Фаза | Описание | Типичное применение |
| :--- | :--- | :--- |
| **PreSync** | Выполнение до применения основных ресурсов | Миграции БД, бэкапы, проверки предусловий |
| **Sync** | Применение ресурсов из Git | Основной деплой (Deployments, Services, ConfigMaps) |
| **PostSync** | Выполнение после того, как все ресурсы стали `Healthy` | Smoke-тесты, уведомления, интеграционные проверки |
| **PostSyncCleanup** | Выполнение после PostSync | Удаление временных ресурсов (Jobs, Secrets) |
| **SyncFail** | Выполнение только при сбое | Уведомления об ошибках, откат миграций |
| **PreDelete** | Выполнение перед удалением приложения (v3.3+) | Очистка внешних ресурсов,_DER_ сохранение данных |
| **PostDelete** | Выполнение после удаления приложения (v3.3+) | Удаление внешних ресурсов, уведомления |

**Важно:** PreDelete и PostDelete хуки доступны с версии v3.3+. Они позволяют выполнять задачи перед и после удаления приложения, что критически важно для корректного завершения работы.

**Примеры хук-аннотаций:**
```yaml
# PreSync хук для миграции БД
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
      - name: migrate
        image: my-app/migrate:latest
        command: ["./migrate.sh"]
      restartPolicy: Never
  backoffLimit: 1

---
# PostSync хук для smoke-тестов
apiVersion: batch/v1
kind: Job
metadata:
  name: smoke-test
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      containers:
      - name: test
        image: my-app/test:latest
        command: ["./run-tests.sh"]
      restartPolicy: Never
  backoffLimit: 0

---
# PreDelete хук для очистки (v3.3+)
apiVersion: batch/v1
kind: Job
metadata:
  name: cleanup
  annotations:
    argocd.argoproj.io/hook: PreDelete
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      containers:
      - name: cleanup
        image: my-app/cleanup:latest
        command: ["./cleanup.sh"]
      restartPolicy: Never
  backoffLimit: 0

---
# PostDelete хук для уведомлений (v3.3+)
apiVersion: batch/v1
kind: Job
metadata:
  name: notify-deletion
  annotations:
    argocd.argoproj.io/hook: PostDelete
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      containers:
      - name: notify
        image: my-app/notify:latest
        command: ["./notify.sh"]
      restartPolicy: Never
  backoffLimit: 0
```

**Политики удаления хуков (hook-delete-policy):**

| Политика | Описание |
| :--- | :--- |
| **HookSucceeded** | Удаление хука после успешного завершения |
| **HookFailed** | Удаление хука при ошибке |
| **BeforeHookCreation** | Удаление предыдущего хука перед созданием нового |
| **HookErrored** | Удаление хука при ошибке API (v3.4+) |

### Волны синхронизации (Sync Waves)

Sync Waves позволяют управлять порядком применения ресурсов. Каждый ресурс получает аннотацию `argocd.argoproj.io/sync-wave` с целым числом (по умолчанию 0). Ресурсы применяются в порядке возрастания волн.

```yaml
# Сначала создается Namespace (волна -1)
apiVersion: v1
kind: Namespace
metadata:
  name: production
  annotations:
    argocd.argoproj.io/sync-wave: "-1"

---
# Затем ConfigMap (волна 0)
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  annotations:
    argocd.argoproj.io/sync-wave: "0"

---
# Затем Deployment (волна 1)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  annotations:
    argocd.argoproj.io/sync-wave: "1"

---
# Затем Service (волна 2)
apiVersion: v1
kind: Service
metadata:
  name: my-app
  annotations:
    argocd.argoproj.io/sync-wave: "2"
```

**Важно:** Волны применяются только в пределах одной синхронизации. Если ресурс в волне 1 не стал `Healthy`, следующие волны не применяются.

### Современные методы синхронизации (v3.x)

#### Server-Side Apply (SSA)

Server-Side Apply — нативный механизм Kubernetes для разрешения конфликтов полей. Логика слияния переносится на сторону API-сервера.

**Преимущества SSA:**
- Исключение конфликтов между несколькими контроллерами (HPA, cert-manager, ArgoCD).
- Обход лимита аннотации `last-applied-configuration` (256 KB).
- Корректная обработка полей с определенным владельцем (field manager).

**Включение SSA:**
```yaml
# В манифесте Application
spec:
  syncPolicy:
    syncOptions:
    - ServerSideApply=true

# Или глобально в argocd-cm
data:
  server.side.apply.enabled: "true"
```

**Пример конфликта HPA + ArgoCD без SSA:**
```yaml
# Git: replicas: 3
# HPA: minReplicas: 2, maxReplicas: 10

# Без SSA: ArgoCD перезаписывает replicas=3, HPA меняет обратно
# С SSA: Поля управляются разными field manager, конфликтов нет
```

#### Progressive Sync

Progressive Sync позволяет выполнять поэтапную раскатку `ApplicationSets` по группам кластеров. Позволяет остановить деплой на всю инфраструктуру, если первая группа (Canary) ушла в `Degraded`.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: progressive-apps
  namespace: argocd
spec:
  generators:
  - clusters: {}
  strategy:
    type: RollingSync
    rollingSync:
      steps:
      - matchExpressions:
          - key: environment
            operator: In
            values: [canary]
        maxUpdate: 1
      - matchExpressions:
          - key: environment
            operator: In
            values: [production]
        maxUpdate: 10%
  template:
    metadata:
      name: '{{name}}-app'
    spec:
      project: default
      source:
        repoURL: https://github.com/my-org/manifests.git
        targetRevision: HEAD
        path: app
      destination:
        server: '{{server}}'
        namespace: production
```

**Важно:** При использовании `RollingSync` стандартный флаг `syncPolicy.automated` внутри шаблона приложения игнорируется. Решение о запуске синхронизации принимает контроллер `ApplicationSet`.

#### Reconciliation Pause

Полная остановка сверки для кластера через аннотацию `argocd.argoproj.io/reconciliation-pause: "true"` в секрете кластера. Полезно при проведении глобальных технических работ.

```bash
# Приостановка сверки
kubectl annotate secret <cluster-secret> -n argocd \
  argocd.argoproj.io/reconciliation-pause="true"

# Возобновление сверки
kubectl annotate secret <cluster-secret> -n argocd \
  argocd.argoproj.io/reconciliation-pause-
```

**Сценарии использования:**
- Плановые технические работы на кластере.
- Миграция контрольной панели Kubernetes.
- Обновление версии Kubernetes.
- Временная остановка автоматических откатов.

### Кастомные Health Checks (Lua)

Для CRD (Custom Resource Definitions) Argo CD использует Lua-скрипты для определения статуса здоровья. По умолчанию CRD считаются здоровыми сразу после создания, что может скрывать реальные проблемы.

```yaml
# argocd-cm ConfigMap
data:
  resource.customizations.health.postgresql.openebayesian.org_PostgreSQLCluster: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.PostgresClusterStatus == "Running" then
        hs.status = "Healthy"
        hs.message = "Cluster is running"
        return hs
      end
    end
    hs.status = "Progressing"
    hs.message = "Waiting for cluster"
    return hs
```

**Примеры типичных Health Checks:**
- PostgreSQL Operator: проверка `status.PostgresClusterStatus`
- Cert-Manager: проверка `status.conditions[].type == "Ready"`
- Prometheus Operator: проверка `status.phase == "Running"`

## Параметры синхронизации (Sync Options)

В манифесте `Application` (секция `spec.syncPolicy.syncOptions`) настраивается поведение контроллера:

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| **CreateNamespace=true** | Автоматическое создание целевого Namespace, если он отсутствует. | false |
| **Prune=true** | Удаление ресурсов в кластере, которых больше нет в Git. | false |
| **SelfHeal=true** | Автоматический откат ручных правок в кластере к состоянию в Git. | false |
| **AllowEmpty=false** | Запрет синхронизации, если Git-репозиторий пуст (защита от случайного удаления всего кластера). | false |
| **ServerSideApply=true** | Использование Server-Side Apply вместо Client-Side Apply. | false |
| **RespectIgnoreDifferences=true** | Использование настроек `ignoreDifferences` не только для визуализации, но и при синхронизации. | false |
| **SkipDryRunOnMissingResource=true** | Пропуск проверки `dry-run` для ресурсов, чьи CRD еще не созданы (важно для первой установки). | false |
| **Replace=true** | Использование `kubectl replace` вместо `apply` (для ресурсов с неизменяемыми полями). | false |
| **ApplyOutOfSyncOnly=true** | Применение только ресурсов в статусе `OutOfSync` (оптимизация производительности). | false |
| **PruneLast=true** | Удаление старых ресурсов после успешного применения новых. | false |
| **PrunePropagationPolicy=foreground** | Удаление dependent-ресурсов перед основными (каскадное удаление). | background |
| **Force=true** | Использование `kubectl apply --force` (удаление и пересоздание). | false |

**Пример использования:**
```yaml
spec:
  syncPolicy:
    syncOptions:
    - CreateNamespace=true
    - Prune=true
    - SelfHeal=true
    - ServerSideApply=true
    - RespectIgnoreDifferences=true
    - PruneLast=true
    - PrunePropagationPolicy=foreground
```

**Взаимодействие параметров:**
- `SelfHeal=true` + `RespectIgnoreDifferences=true` — SelfHeal не перезаписывает поля из `ignoreDifferences`.
- `Prune=true` + `PruneLast=true` — Удаление происходит после успешного применения новых ресурсов.
- `Replace=true` + `Force=true` — `Force=true` имеет приоритет, использует `kubectl apply --force`.

## Resource Actions (Действия над ресурсами)

Resource Actions позволяют определять кастомные действия (actions) для конкретных типов Kubernetes-ресурсов. Действия выполняются через CLI (`argocd app action`) или API и используются для операций, не связанных с синхронизацией: рестарт подов, масштабирование, ротация секретов, очистка кэша.

### Архитектура

```text
argocd app action run <action> --kind <kind> --name <name>
    │
    ▼
┌─────────────────────────────┐
│  Resource Action            │
│  Определен в argocd-cm      │
│  или в ConfigMap            │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  Генерация манифеста        │
│  (kubectl patch/replace)    │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  Применение к ресурсу       │
│  (Kubernetes API)           │
└─────────────────────────────┘
```

### Определение Resource Action

Resource Actions определяются в ConfigMap `argocd-notifications-cm` или в `argocd-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
  namespace: argocd
data:
  # Определение действия для Deployment
  action.on-sync-succeeded: |
    message: "Application {{.app.metadata.name}} successfully synced"
  
  # Кастомное действие: restart deployment
  action.restart-deployment: |
    title: Restart Deployment
    description: "Rolling restart of deployment {{.app.spec.destination.name}}"
    enabled: true
    generate: |
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: {{.app.spec.destination.name}}
        namespace: {{.app.spec.destination.namespace}}
      spec:
        template:
          metadata:
            annotations:
              restart-trigger: "{{now}}"
```

### CLI команды для Resource Actions

```bash
# Просмотр доступных действий
argocd app actions list <app-name>

# Запуск действия
argocd app action run <action-name> \
  --kind Deployment \
  --name <deployment-name> \
  --namespace <namespace>

# Пример: restart deployment
argocd app action run restart-deployment \
  --kind Deployment \
  --name my-app \
  --namespace production

# Пример: scaledown
argocd app action run scaledown \
  --kind Deployment \
  --name my-app \
  --namespace production \
  --param replicas=0
```

### Практические примеры

**1. Restart Deployment:**
```yaml
action.restart: |
  title: Restart
  description: "Rolling restart"
  enabled: true
  generate: |
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: {{.app.spec.destination.name}}
    spec:
      template:
        metadata:
          annotations:
            restart: "{{now}}"
```

**2. Scale Down:**
```yaml
action.scaledown: |
  title: Scale Down
  description: "Scale to 0 replicas"
  enabled: true
  generate: |
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: {{.app.spec.destination.name}}
    spec:
      replicas: 0
```

**3. Restart ConfigMap (для перезагрузки подов с Reloader):**
```yaml
action.restart-configmap: |
  title: Restart via ConfigMap
  description: "Update annotation to trigger Reloader"
  enabled: true
  generate: |
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: {{.app.spec.destination.name}}-restart
    data:
      restart: "{{now}}"
```

## Практические сценарии

### Быстрый старт

```bash
# 1. Создание Application через CLI
argocd app create my-app \
  --repo https://github.com/argoproj/argocd-example-apps.git \
  --path guestbook \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace guestbook \
  --sync-policy automated \
  --auto-prune \
  --self-heal

# 2. Синхронизация
argocd app sync my-app

# 3. Просмотр состояния
argocd app get my-app

# 4. Просмотр diff
argocd app diff my-app

# 5. Просмотр логов
argocd app logs my-app
```

### Подробные руководства

- **[Автоматическая синхронизация](./synchronization/scenarios/auto_sync.md)** — глубокая настройка `automated` и `retry`.
- **[Ручная синхронизация](./synchronization/scenarios/manual_sync.md)** — селективный деплой и аудит изменений.
- **[Sync Waves и Hooks](./synchronization/scenarios/sync_waves_hooks.md)** — управление очередностью и Health Gating.
- **[Окна синхронизации](./synchronization/scenarios/sync_windows.md)** — политики запрета деплоя в праздники и выходные.
- **[Прогрессивная синхронизация](./synchronization/scenarios/progressive_sync.md)** — Rolling деплой для мультикластерных сред.
- **[Игнорирование различий](./synchronization/ignore_differences.md)** — настройка jqPath и managedFieldsManagers.

## Диагностика и мониторинг

### Базовые команды диагностики

```bash
# Просмотр состояния всех приложений
argocd app list

# Просмотр деталей конкретного приложения
argocd app get my-app

# Просмотр diff
argocd app diff my-app

# Просмотр логов контроллера
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f

# Просмотр событий в namespace argocd
kubectl get events -n argocd --sort-by='.lastTimestamp'

# Просмотр подов ArgoCD
kubectl get pods -n argocd -o wide
```

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`ComparisonError`** | Ошибка в синтаксисе манифестов или недоступность репозитория. | Проверьте манифесты и доступ к Git. |
| **`InvalidSpecError`** | Ошибка в конфигурации объекта `Application`. | Проверьте манифест Application. |
| **`SyncError`** | Ошибка применения ресурсов в кластере. | Проверьте RBAC и доступность API-сервера. |
| **`UnknownError`** | Неизвестная ошибка. | Просмотрите логи контроллера. |
| **`SelfHeal не работает`** | Ручные правки не откатываются | Не включен `selfHeal` или игнорируется поле | Добавьте `selfHeal: true` и `RespectIgnoreDifferences=true` |
| **`Prune не удаляет`** | Ресурсы не удаляются | Не включен `prune` | Добавьте `prune: true` в syncOptions |
| **`Dry Run завершается ошибкой`** | Ошибка валидации манифестов | Некорректный YAML или отсутствует CRD | Исправьте манифест или добавьте `SkipDryRunOnMissingResource=true` |

Подробнее: **[Диагностика и мониторинг Argo CD](./argocd_troubleshooting_and_monitoring.md)**.

## Лучшие практики

### Производительность

- **Используйте Server-Side Apply:** Включайте `ServerSideApply=true` для больших манифестов и кластеров с мутирующими контроллерами (HPA, cert-manager).
- **Ограничьте частоту сверки:** Настройте `selfHeal: false` для приложений, где ручные правки допустимы.
- **Используйте `ApplyOutOfSyncOnly=true`:** Оптимизирует применение только измененных ресурсов.
- **Shallow Git Cloning:** Используйте `--depth` для монорепозиториев (>1000 файлов).

### Безопасность

- **Используйте AppProject:** Всегда создавайте отдельные проекты для разных команд/окружений.
- **RBAC:** Ограничьте права доступа через AppProject Roles и SSO-группы.
- **Sync Windows:** Настройте окна запрета для Production в нерабочее время.
- **Sealed Secrets / AVP:** Никогда не храните секреты в открытом виде в Git.

### Надежность

- **App-of-Apps:** Используйте для bootstrapping и группировки связанных приложений.
- **ApplicationSet:** Используйте для динамических сред и масштабируемых инфраструктур.
- **Reconciliation Pause:** Используйте `argocd.argoproj.io/reconciliation-pause: "true"` для временной остановки сверки при глобальных технических работах.

## Ограничения и edge cases

### Ограничения

1. **Лимит ресурсов:** Argo CD имеет внутренние лимиты на количество управляемых ресурсов. Для очень больших приложений (>1000 ресурсов) рекомендуется разбивать на несколько ApplicationSets.
2. **Cross-namespace ресурсы:** Автоматическая синхронизация работает только в рамках одного namespace. Для кросс-namespace ресурсов настройте отдельные ApplicationSets.
3. **ApplicationSet и `automated`:** Стандартный флаг `syncPolicy.automated` внутри шаблона ApplicationSet игнорируется. Решение о запуске синхронизации принимает контроллер `ApplicationSet`.
4. **Множественные ApplicationSets:** Если ресурс управляется несколькими ApplicationSets, возникает конфликт. Используйте `FailOnSharedResource=true`.
5. **Reconciliation Pause:** Приостановка сверки через аннотацию `argocd.argoproj.io/reconciliation-pause: "true"` в секрете кластера останавливает все процессы для этого кластера.

### Edge Cases

1. **UI-откат и `OutOfSync`:** После UI-отката приложение переходит в состояние `OutOfSync` относительно Git. `SelfHeal` временно отключается для этого приложения.
2. **PreSync Hook и Sync Windows:** Если PreSync Hook (миграция БД) начинается во время Allow окна и выполняется дольше, Hook не прерывается. Основные ресурсы будут применены после завершения Hook.
3. **Progressive Sync и Deny окно:** Если приложение попадает в Deny окно во время Progressive Sync, оно не будет синхронизировано до открытия Allow окна.
4. **Progressive Sync и ручная синхронизация:** Если вы вручную нажмете "Sync" на приложении, которое еще не подошло по очереди, оно будет синхронизировано, но это может нарушить логику `maxUpdate` текущего шага.
5. **PreDelete Hook и удаление ApplicationSet:** Если ApplicationSet удален во время выполняющейся синхронизации, операция завершится, но новые синхронизации будут невозможны.
6. **SelfHeal + IgnoreDifferences:** Если включены и `ignoreDifferences`, и `SelfHeal=true`, Argo CD может пытаться «починить» поля, которые не игнорируются. Убедитесь, что игнорируемые поля действительно исключены из diff.
7. **Prune не работает для ресурсов с OwnerReferences:** Удаление dependent-ресурсов происходит каскадно через Kubernetes API, а не через Argo CD.

## Дополнительная информация

### Основные изменения в ветке v3.x

- **Progressive Sync:** поэтапное развёртывание ApplicationSets.
- **Server-Side Apply:** стандарт для разрешения конфликтов.
- **PreDelete Hooks (v3.3):** выполнение Jobs перед удалением приложения.
- **OCI-нативность (v3.1):** поддержка Helm-чартов в OCI.

### Стратегии развертывания

ArgoCD интегрируется с **Argo Rollouts** для реализации:
- **Canary Deployment:** постепенное переключение трафика.
- **Blue/Green Deployment:** быстрое переключение между окружениями.

### См. также

- **[Обзор Argo CD](./argocd_overview.md)** — общая архитектура системы.
- **[Диагностика и мониторинг](./argocd_troubleshooting_and_monitoring.md)** — поиск и устранение сбоев.
- **[Игнорирование различий](./synchronization/ignore_differences.md)** — настройка jqPath и managedFieldsManagers.
- **[Методы отслеживания ресурсов](./argocd_resource_tracking.md)** — label, annotation, annotation+label.
- **[Удаление и очистка ресурсов](./argocd_deletion_and_cleanup.md)** — Prune, Cascading Deletion, Propagation Policy.

### Ссылки

- [Официальная документация: Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
- [Argo CD CLI: sync command](https://argo-cd.readthedocs.io/en/stable/user-guide/commands/argocd_app_sync/)
- [Sync Waves Official Guide](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/)
- [Resource Hooks Official Guide](https://argo-cd.readthedocs.io/en/stable/user-guide/resource_hooks/)

## Вопросы для собеседования

### Чем sync waves отличаются от hooks?
Waves упорядочивают применение **манифестов**: ресурсы волны N дождутся здоровья волны N-1. Hooks — это **Jobs, выполняемые на фазах** синхронизации: PreSync (миграции БД), Sync, PostSync (прогрев/уведомления), SyncFail. Типовая связка: PreSync-миграция → wave 0 база → wave 1 приложение → PostSync smoke-test.

### Что произойдет при падении PreSync hook?
Синхронизация останавливается со статусом Failed: основные ресурсы не применяются, PostSync не запускается. Кластер остается на предыдущей ревизии — это безопасный дефолт. Настраиваются повторные попытки и таймауты hook'а; после исправления миграции синк перезапускается.

### Почему включать `prune` и `selfHeal` одновременно с автосинком требует осторожности?
Тройка `automated + prune + selfHeal` делает кластер зеркалом Git без вопросов: случайный коммит (удаленный каталог, пустой файл, неверный overlay) удаляет или ломает ресурсы автоматически. Защиты: `AllowEmpty=false`, запрет force-push в main, CODEOWNERS, поэтапное включение prune только для stateless.

### Когда OutOfSync и Healthy встречаются одновременно?
Легитимные случаи: HPA меняет replicas, мутирующие вебхуки добавляют поля, операторы пишут status. Ресурс работает (Healthy), но отличается от Git (OutOfSync). Решение — ignoreDifferences на конкретные поля, а не отключение self-heal целиком.

### Когда обязателен Server-Side Apply?
Когда манифест превышает лимит аннотаций last-applied-configuration (~262 KB), при конфликтах владения полями с другими контроллерами (HPA, cert-manager) и для ресурсов, управляемых несколькими менеджерами полями. В v3.x SSA — рекомендуемый дефолт.
