# ArgoCD — синхронизация и политики

**Актуально для:** Argo CD v3.4+ (покрывает v3.4.x, v3.5.x, v3.6.x; отличаются server-side diff, syncOverrun, Progressive Syncs Beta)

## Предварительные требования

Перед работой с синхронизацией Argo CD убедитесь в выполнении следующих условий:

1. **Кластер Kubernetes:** версия v1.26+ (рекомендуется v1.28+ для полной поддержки Server-Side Apply и field management).
2. **Argo CD установлен:** проверьте статус подов:
   ```bash
   kubectl get pods -n argocd
   # → все поды в статусе Running, READY 1/1 или 2/2
   ```
3. **CLI-клиент `argocd`:** установлен (версия, совместимая с сервером) и настроен вход:
   ```bash
   argocd version
   argocd login <ARGOCD_SERVER> --username admin --password <password>
   ```
4. **Git-репозиторий:** доступен для Argo CD (настроены credentials в `argocd-repo-server` или публичный доступ). Поддерживаются: Git (HTTPS/SSH), Helm-репозитории (HTTP/OCI), Kustomize.
5. **RBAC:** права администратора кластера для первоначальной настройки AppProject, Sync Windows и Resource Tracking. Для операций синхронизации достаточно роли `application:sync` в соответствующем проекте.
6. **AppProject:** приложение привязано к проекту с разрешенными целевыми кластерами (`destServer`), namespaces и источниками репозиториев.
7. **Понимание рисков:** автоматическая синхронизация с `prune: true` и `selfHeal: true` может удалить ресурсы или откатить ручные изменения. Политики должны соответствовать требованиям среды (dev/staging/prod).
8. **Работающая ручная синхронизация:** приложение успешно синхронизировалось хотя бы один раз вручную (UI/CLI) перед включением автоматики.

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

**Skip Reconcile** — полная остановка обработки приложения через аннотацию `argocd.argoproj.io/skip-reconcile: "true"` (Alpha с v2.7.0; на секрете кластера — для всех приложений кластера, с v3.4).

## Основные концепции

### Детальный цикл сверки

ArgoCD Application Controller работает по событийной модели (Webhook от Git-хостинга) или по расписанию (по умолчанию 120s + jitter до 60s, максимальный период 3 минуты — настраивается через `timeout.reconciliation` и `timeout.reconciliation.jitter` в `argocd-cm`):

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
    - `argocd-repo-server` извлекает манифесты из Git (клонирует/обновляет репозиторий).
    - Выполняется рендеринг (Helm `template`, Kustomize `build` или **[кастомные плагины](./argocd_custom_tooling.md)**).
    - Результат кешируется в `repo-server` для повторного использования.
    - Контроллер приложений (`argocd-application-controller`) запрашивает текущее состояние ресурсов из Kubernetes API-сервера (live state) по tracking ID (метка `app.kubernetes.io/instance` или аннотация `argocd.argoproj.io/instance` — см. **[Методы отслеживания ресурсов](./argocd_resource_tracking.md)**).

2.  **Фаза Diff (Сравнение):**
    - Выполняется попарное сравнение желаемого состояния (rendered manifests) и фактического (live state).
    - Стратегия diff по умолчанию — **Legacy** (3-way diff через аннотацию `kubectl.kubernetes.io/last-applied-configuration`).
    - Альтернативы: **Server-Side Diff** (v3.5+, включается аннотацией `argocd.argoproj.io/compare-options: ServerSideDiff=true` или флагом `--server-side-diff`; выполняет SSA в dry-run режиме с учетом admission-вебхуков).
    - Учитываются настройки **[игнорирования различий](./synchronization/ignore_differences.md)** (`ignoreDifferences` с `jsonPointers`, `jqPathExpressions`, `managedFieldsManagers`).
    - Формируется статус синхронизации: `Synced` (всё совпадает) или `OutOfSync` (есть расхождения).
    - Параллельно оценивается здоровье ресурсов (Health Assessment) — статус `Healthy` / `Progressing` / `Degraded` / `Suspended`.

3.  **Фаза Sync (Применение):**
    - Запускается только если статус `OutOfSync` И выполнены условия автоматизации (`automated.enabled != false`) или инициирована ручная синхронизация.
    - Контроллер выстраивает план применения согласно **Sync Waves** (аннотация `argocd.argoproj.io/sync-wave`) и **Hooks** (аннотация `argocd.argoproj.io/hook` — фазы PreSync, Sync, PostSync, SyncFail, PreDelete, PostDelete).
    - Ресурсы применяются в порядке: фаза → волна → Kind → имя.
    - Метод применения: по умолчанию клиентский `kubectl apply`; при `ServerSideApply=true` — `kubectl apply --server-side --force-conflicts`; при `Replace=true` — `kubectl replace`/`create` (имеет приоритет над SSA); при `Force=true` — `kubectl delete` + `create`.
    - После применения проверяется здоровье (Health Check) каждого ресурса.
    - При включенном `prune` удаляются ресурсы, отсутствующие в Git (в обратном порядке волн).

**Интервалы и таймауты:**
- **Интервал сверки (Reconciliation Interval):** `timeout.reconciliation` в `argocd-cm`, **default 120s + jitter до 60s** (макс. 3 минуты).
- **Self-Heal timeout:** флаг `--self-heal-timeout-seconds` deployment `argocd-application-controller`, **default 5s**. Итого типичное время исправления ручной правки — около 2–3,5 минут.
- **Sync Wave Delay:** пауза между волнами, **default 2s**, настраивается `ARGOCD_SYNC_WAVE_DELAY` в окружении контроллера.
- **CLI timeout:** флаг `--timeout` у `argocd app sync` ограничивает ожидание CLI, но не операцию в кластере. Зависшую операцию останавливают: `argocd app terminate-op <name>`.

### Методы отслеживания ресурсов (Resource Tracking)

Для того чтобы ArgoCD знал, какими ресурсами он управляет, используется механизм отслеживания. В v3.x поддерживаются три метода (настраиваются в `argocd-cm` параметром `resourceTrackingMethod`):

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

**Подробное руководство по методам, миграции, multi-cluster отслеживанию, orphaning и диагностике:** см. **[Методы отслеживания ресурсов](./argocd_resource_tracking.md)**.

### Фазы синхронизации

Процесс применения ресурсов разделен на этапы, что позволяет встраивать логику (Hooks) в процесс:

| Фаза | Описание | Типичное применение |
| :--- | :--- | :--- |
| **PreSync** | Выполнение до применения основных ресурсов | Миграции БД, бэкапы, проверки предусловий |
| **Sync** | Выполняется после успешных PreSync-хуков, одновременно с применением манифестов | Сложная оркестрация, не укладывающаяся в rolling-update |
| **PostSync** | Выполнение после того, как все ресурсы стали `Healthy` | Smoke-тесты, уведомления, интеграционные проверки |
| **SyncFail** | Выполнение только при сбое синхронизации | Уведомления об ошибках, откат миграций |
| **PreDelete** | Выполнение перед удалением приложения (v3.3+) | Очистка внешних ресурсов, сохранение данных |
| **PostDelete** | Выполнение после удаления приложения (v2.10+) | Удаление внешних ресурсов, уведомления |

**Важно:** PreDelete-хуки доступны с версии v3.3, PostDelete-хуки — с версии v2.10. Они позволяют выполнять задачи перед и после удаления приложения, что критически важно для корректного завершения работы.

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
# PostDelete хук для уведомлений (v2.10+)
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

**Подробное руководство с включением, RollingSync, health gating, sync windows, matrix generator, диагностикой и edge cases:** см. **[Прогрессивная синхронизация](./synchronization/scenarios/progressive_sync.md)**.

#### Skip Reconcile

Полная остановка обработки приложения через аннотацию `argocd.argoproj.io/skip-reconcile: "true"`. При включении вся обработка приложения останавливается: поле `status` не обновляется, дрейф не детектируется, синхронизации (в т.ч. ручные) не выполняются. Alpha-фича (с v2.7.0), предназначена для интеграции со сторонними проектами; может измениться или исчезнуть в будущих релизах. С v3.4 аннотация поддерживается и на секрете кластера — приостанавливает обработку всех приложений, нацеленных на кластер. Полезно при проведении глобальных технических работ.

```bash
# Приостановка обработки приложения
kubectl annotate application <app-name> -n argocd \
  argocd.argoproj.io/skip-reconcile="true"

# Приостановка для всего кластера (с v3.4)
kubectl annotate secret <cluster-secret> -n argocd \
  argocd.argoproj.io/skip-reconcile="true"

# Возобновление (снятие аннотации или явное "false")
kubectl annotate application <app-name> -n argocd \
  argocd.argoproj.io/skip-reconcile-
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

В манифесте `Application` поведение контроллера настраивается в двух секциях:
- `spec.syncPolicy.automated` — поля политики автоматической синхронизации (`enabled`, `prune`, `selfHeal`, `allowEmpty`);
- `spec.syncPolicy.syncOptions` — опции применения изменений:

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| **CreateNamespace=true** | Автоматическое создание целевого Namespace, если он отсутствует. | false |
| **ServerSideApply=true** | Использование Server-Side Apply вместо Client-Side Apply. | false |
| **RespectIgnoreDifferences=true** | Использование настроек `ignoreDifferences` не только для визуализации, но и при синхронизации. | false |
| **SkipDryRunOnMissingResource=true** | Пропуск проверки `dry-run` для ресурсов, чьи CRD еще не созданы (важно для первой установки). | false |
| **Replace=true** | Использование `kubectl replace`/`create` вместо `apply` (для ресурсов, не помещающихся в аннотацию `last-applied-configuration`). Имеет приоритет над `ServerSideApply=true`. | false |
| **ApplyOutOfSyncOnly=true** | Применение только ресурсов в статусе `OutOfSync` (оптимизация производительности). | false |
| **PruneLast=true** | Удаление старых ресурсов после успешного применения новых. | false |
| **PrunePropagationPolicy=foreground\|background\|orphan** | Политика каскадного удаления dependent-ресурсов. | foreground |
| **FailOnSharedResource=true** | Ошибка синхронизации, если ресурс уже применен другим приложением. | false |
| **Validate=false** | Пропуск валидации манифестов (sync option; нет CLI-флага `--validate` у `argocd app sync`). | true (валидация включена) |
| **Force=true** | Удаление и пересоздание ресурса при каждом синке (`kubectl delete/create`). Обычно на уровне ресурса, часто с `Replace=true`. | false |

**Поля автоматической синхронизации (`spec.syncPolicy.automated`):**

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| **enabled** | Явное вкл/выкл автоматической синхронизации (v3.1+). | null (= true) |
| **prune** | Удаление ресурсов в кластере, которых больше нет в Git, в рамках автосинка. | false |
| **selfHeal** | Автоматический откат ручных правок в кластере к состоянию в Git. | false |
| **allowEmpty** | Разрешение синхронизации при пустом Git-репозитории. | false |

**Пример использования:**
```yaml
spec:
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
      allowEmpty: false
    syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true
    - RespectIgnoreDifferences=true
    - PruneLast=true
    - PrunePropagationPolicy=foreground
```

**Взаимодействие параметров:**
- `selfHeal: true` + `RespectIgnoreDifferences=true` — SelfHeal не перезаписывает поля из `ignoreDifferences`.
- `prune: true` + `PruneLast=true` — Удаление происходит после успешного применения новых ресурсов.
- `Replace=true` + `ServerSideApply=true` — `Replace=true` имеет приоритет и использует `kubectl replace`/`create`.

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

### Сценарий 1: Настройка автоматической синхронизации для Production

**Цель:** Включить полную автоматизацию с защитой от катастрофических удалений и оптимизацией производительности.

**Предварительные условия:** Приложение успешно синхронизировалось вручную хотя бы один раз.

**Шаги:**

1. **Обновите манифест Application:**
```yaml
spec:
  syncPolicy:
    automated:
      enabled: true             # Явное включение (v3.1+); null эквивалентен true
      prune: true               # Удалять ресурсы, отсутствующие в Git
      selfHeal: true            # Исправлять ручные правки в кластере
      allowEmpty: false         # ЗАЩИТА: не синхронизировать, если репозиторий пуст
    syncOptions:
    - CreateNamespace=true         # Создать Namespace автоматически
    - ServerSideApply=true         # Использовать SSA (обходит лимит аннотации 256 KB)
    - FailOnSharedResource=true    # Ошибка, если ресурс занят другим приложением
    - RespectIgnoreDifferences=true # Не трогать поля из ignoreDifferences при apply
    - ApplyOutOfSyncOnly=true      # Оптимизация: не слать в API неизмененные ресурсы
    - PruneLast=true               # Удалять старое только после успеха нового деплоя
    retry:
      limit: 5                     # Максимум 5 попыток при сбое
      backoff:
        duration: 5s               # Пауза между попытками (default 5s)
        factor: 2                  # Экспоненциальный рост паузы (default 2)
        maxDuration: 3m            # Максимальное время ожидания (default 3m)
```

2. **Примените изменения:**
```bash
kubectl apply -f application.yaml
# → result: application.argoproj.io/my-app configured
```

3. **Проверьте статус (подождите до 3 минут до следующей сверки или принудительно):**
```bash
argocd app get my-app --refresh
# → result: Status: Synced, Health: Healthy, Sync Policy: Automated (Prune: true, SelfHeal: true)
```

**Валидация:**
```bash
# 1. Проверьте, что автосинк включен
argocd app get my-app | grep "Sync Policy"
# → result: Sync Policy: Automated (Prune: true, SelfHeal: true)

# 2. Сделайте ручное изменение в кластере (имитация дрейфа)
kubectl patch deployment my-app -n guestbook --type merge -p '{"spec":{"replicas":5}}'
# → result: deployment.apps/my-app patched

# 3. Дождитесь Self-Heal (сверка 120s + jitter 60s + self-heal timeout 5s)
argocd app get my-app --refresh
# → result: Status: Synced, replicas вернулись к значению из Git (3)

# 4. Удалите ресурс из Git и проверьте Prune
git rm guestbook/some-resource.yaml && git push
argocd app get my-app --refresh
# → result: ресурс удален из кластера
```

---

### Сценарий 2: Настройка ручной синхронизации с аудитом для Production

**Цель:** Ручное подтверждение каждого деплоя с полной трассируемостью.

**Шаги:**

1. **Настройте манифест для ручного режима:**
```yaml
spec:
  syncPolicy:
    syncOptions:
    - CreateNamespace=true
    - PruneLast=true
    retry:
      limit: 2
```

2. **Примените и проверьте:**
```bash
kubectl apply -f application.yaml
argocd app get my-app
# → result: Sync Policy: Manual (или <none>)
```

3. **Перед деплоем — анализ diff:**
```bash
argocd app diff my-app
# → показывает отличия live vs desired
# exit code: 0 — нет diff, 1 — есть diff, 2 — ошибка
```

4. **Dry Run для валидации:**
```bash
argocd app sync my-app --dry-run
# → имитирует применение через API-сервер, ресурсы не меняются
```

5. **Синхронизация с аудитом:**
```bash
argocd app sync my-app --info ticket=INC-1234 --info owner=sre-team
# → операция записана в аудит с метками
```

**Валидация:**
```bash
# Ожидание завершения и проверки здоровья
argocd app wait my-app --operation --health
# → result: Operation: Succeeded, Health: Healthy

# Проверка истории
argocd app history my-app
# → показывает ревизии с автором и временем
```

---

### Сценарий 3: Настройка Sync Waves и PreSync Hook для миграции БД

**Цель:** Гарантированный порядок: Namespace → ConfigMap/Secret → PreSync миграция → Deployment → Service → PostSync smoke-test.

**Шаги:**

1. **Добавьте аннотации волн к манифестам в Git:**
```yaml
# Namespace (волна -10)
apiVersion: v1
kind: Namespace
metadata:
  name: production
  annotations:
    argocd.argoproj.io/sync-wave: "-10"
---
# ConfigMap (волна -5)
apiVersion: v1
kind: ConfigMap
metadata:
  name: db-config
  namespace: production
  annotations:
    argocd.argoproj.io/sync-wave: "-5"
---
# PreSync Hook: миграция БД (волна -1)
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
  namespace: production
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation,HookSucceeded
    argocd.argoproj.io/sync-wave: "-1"
spec:
  backoffLimit: 1
  activeDeadlineSeconds: 900
  template:
    spec:
      containers:
      - name: migrate
        image: myorg/migrate:v1.2
        command: ["./migrate.sh"]
      restartPolicy: Never
---
# Deployment (волна 0 — default)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
  namespace: production
---
# Service (волна 5)
apiVersion: v1
kind: Service
metadata:
  name: api-server
  namespace: production
  annotations:
    argocd.argoproj.io/sync-wave: "5"
---
# PostSync Hook: smoke-test (волна 10)
apiVersion: batch/v1
kind: Job
metadata:
  name: smoke-test
  namespace: production
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
    argocd.argoproj.io/sync-wave: "10"
spec:
  backoffLimit: 0
  template:
    spec:
      containers:
      - name: test
        image: curlimages/curl:latest
        command: ["curl", "-f", "http://api-server:8080/health"]
      restartPolicy: Never
```

2. **Выполните синхронизацию:**
```bash
argocd app sync my-app
# → PreSync hook запускается, затем волны по порядку
```

**Валидация:**
```bash
# Отслеживание прогресса в реальном времени
argocd app get my-app --refresh
# → показывает текущую волну и статус хуков

# Логи хука миграции
argocd app logs my-app --kind Job --name db-migrate -f

# Проверка здоровья после завершения
argocd app wait my-app --health
# → result: Health: Healthy
```

---

### Сценарий 4: Настройка Server-Side Apply для работы с HPA

**Цель:** Решить конфликт HPA + Argo CD над полем `replicas` без отключения Self-Heal.

**Шаги:**

1. **Настройте ignoreDifferences для HPA:**
```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    managedFieldsManagers:
    - kube-controller-manager  # HPA пишет через этот менеджер
  syncPolicy:
    syncOptions:
    - ServerSideApply=true
    - RespectIgnoreDifferences=true
```

2. **Проверьте менеджера поля replicas:**
```bash
kubectl get deployment my-app -n production -o jsonpath='{range .metadata.managedFields[*]}{.manager}{"\n"}{end}' | sort -u
# → result: kube-controller-manager (должен быть в списке)
```

3. **Примените и проверьте:**
```bash
kubectl apply -f application.yaml
argocd app get my-app --refresh
# → Status: Synced (replicas от HPA не вызывают OutOfSync)
```

**Валидация:**
```bash
# HPA меняет replicas
kubectl get hpa my-app -n production -w
# Argo CD НЕ должен возвращать replicas к Git-значению
argocd app get my-app --refresh
# → Status: Synced (OutOfSync не появляется)
```

---

### Сценарий 5: Настройка Sync Windows для блокировки деплоя в нерабочее время

**Цель:** Разрешить автосинк только в рабочие часы Пн-Пт 10:00-18:00, ручной — всегда.

**Шаги:**

1. **Настройте AppProject:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production-project
  namespace: argocd
spec:
  syncWindows:
  - kind: allow
    schedule: '0 10 * * 1-5'   # Пн-Пт 10:00
    duration: 8h
    applications: ["prod-*"]
    manualSync: true           # ручной синк разрешен вне окна
    timeZone: "Europe/Moscow"
    syncOverrun: true          # v3.5+: запущенный синк завершится после закрытия окна
```

2. **Примените и проверьте:**
```bash
kubectl apply -f project.yaml
argocd proj windows list production-project
# → ID  STATUS    KIND   SCHEDULE       DURATION  APPLICATIONS  MANUALSYNC  OVERUN
# → 0   Active    allow  0 10 * * 1-5   8h        prod-*        Enabled     Enabled
```

**Валидация:**
```bash
# Вне окна: автосинк заблокирован, приложение OutOfSync
argocd app get prod-app
# → SyncWindow: Sync Denied (Auto), Manual Allowed

# В окне: автосинк работает
# (дождитесь рабочего времени или измените schedule для теста)
```

---

### Подробные руководства

- **[Автоматическая синхронизация](./synchronization/scenarios/auto_sync.md)** — глубокая настройка `automated` и `retry`.
- **[Ручная синхронизация](./synchronization/scenarios/manual_sync.md)** — селективный деплой и аудит изменений.
- **[Sync Waves и Hooks](./synchronization/scenarios/sync_waves_hooks.md)** — управление очередностью и Health Gating.
- **[Окна синхронизации](./synchronization/scenarios/sync_windows.md)** — политики запрета деплоя в праздники и выходные.
- **[Прогрессивная синхронизация](./synchronization/scenarios/progressive_sync.md)** — Rolling деплой для мультикластерных сред.
- **[Игнорирование различий](./synchronization/ignore_differences.md)** — настройка jqPath и managedFieldsManagers.

## Валидация и проверка работоспособности

### Проверка автоматической синхронизации

```bash
# 1. Примените манифест Application
kubectl apply -f application.yaml

# 2. Дождитесь статуса Synced (до 3 минут)
argocd app get my-app
# → result: Status: Synced, Health: Healthy

# Или блокирующее ожидание:
argocd app wait my-app
# → result: Operation: Succeeded, Health: Healthy

# 3. Измените ресурс в кластере (ручное изменение — имитация дрейфа)
kubectl patch deployment my-app --type merge -p '{"spec":{"replicas":5}}'
# → result: deployment.apps/my-app patched

# 4. Дождитесь исправления Self-Heal (сверка 120s + jitter 60s + self-heal timeout 5s)
argocd app get my-app --refresh
# → result: Status: Synced, replicas вернулись к Git-значению (3)

# 5. Проверьте, что реплики вернулись к Git-значению
kubectl get deployment my-app -o jsonpath='{.spec.replicas}'
# → result: 3
```

### Проверка Pruning (удаления лишних ресурсов)

```bash
# 1. Удалите ресурс из Git (или переместите в другую папку)
git rm guestbook/unwanted-resource.yaml && git push
# → result: коммит с удалением зафиксирован

# 2. Дождитесь следующей сверки (или принудительно)
argocd app get my-app --refresh
# → result: ресурс удален из кластера

# 3. Проверьте, что ресурс удален из кластера
kubectl get deployment unwanted-resource -n guestbook
# → result: Error from server (NotFound): deployments.apps "unwanted-resource" not found
```

### Проверка ручной синхронизации с аудитом

```bash
# 1. Проверьте статус приложения
argocd app get my-app
# → result: Sync Policy: Manual

# 2. Просмотрите diff перед синхронизацией
argocd app diff my-app
# → показывает конкретные поля, которые будут изменены

# 3. Выполните Dry Run (валидация включена по умолчанию)
argocd app sync my-app --dry-run
# → имитирует применение, ресурсы не меняются

# 4. Выполните синхронизацию с метаданными для аудита
argocd app sync my-app --info ticket=INC-1234 --info owner=sre-team

# 5. Дождитесь завершения и проверьте здоровье
argocd app wait my-app --operation --health
# → result: Operation: Succeeded, Health: Healthy
```

### Проверка Sync Waves и Hooks

```bash
# 1. Запустите синхронизацию
argocd app sync my-app

# 2. Отслеживайте прогресс волн в реальном времени
argocd app get my-app --refresh
# → показывает текущую волну: "Wave: 0/5" и статус хуков

# 3. Логи PreSync хука (миграция БД)
argocd app logs my-app --kind Job --name db-migrate -f
# → показывает вывод миграции

# 4. Дождитесь завершения всех волн и проверьте здоровье
argocd app wait my-app --health
# → result: Health: Healthy

# 5. Проверьте историю — хук должен быть в списке ресурсов
argocd app history my-app
# → показывает ревизию с хук-ресурсами
```

### Проверка Retry политики

```bash
# 1. Настройте приложение с retry
argocd app set my-app --sync-retry-limit 3 --sync-retry-backoff-duration 5s --sync-retry-backoff-factor 2 --sync-retry-backoff-max-duration 3m

# 2. Временно заблокируйте доступ к API-серверу (имитация сетевого сбоя)
# Например: kubectl scale deploy argocd-application-controller -n argocd --replicas=0

# 3. Запустите синхронизацию
argocd app sync my-app

# 4. Просмотрите логи повторных попыток
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep -i retry
# → показывает попытки: "retry 1/3", "retry 2/3" и т.д.
```

### Проверка Sync Windows

```bash
# 1. Проверьте состояние окон для приложения
argocd app get my-app
# → SyncWindow: Sync Allowed / Sync Denied (Auto), Manual Allowed

# 2. Список окон проекта с текущим статусом
argocd proj windows list production-project
# → ID  STATUS    KIND   SCHEDULE       DURATION  APPLICATIONS  MANUALSYNC  OVERUN
# → 0   Active    allow  0 10 * * 1-5   8h        prod-*        Enabled     Enabled

# 3. Метрики Prometheus (v3.5+)
# argocd_app_sync_blocked == 1 — автосинк заблокирован окнами
# argocd_app_sync_window{window_kind="allow"} == 1 — активно allow-окно
```

## Диагностика и мониторинг

### Базовые команды диагностики

```bash
# Просмотр состояния всех приложений
argocd app list

# Просмотр деталей конкретного приложения (с принудительным обновлением)
argocd app get my-app
argocd app get my-app --refresh
argocd app get my-app --hard-refresh

# Просмотр diff (exit codes: 0 — нет diff, 1 — есть diff, 2 — ошибка)
argocd app diff my-app
argocd app diff my-app --server-side-diff  # v3.5+: с учетом вебхуков

# Просмотр текущей операции (если синк в процессе)
argocd app get my-app --show-operation

# Дерево ресурсов с волнами и статусами
argocd app get my-app -o tree

# Просмотр логов контроллера приложений
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f

# Просмотр логов repo-server (рендеринг)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -f

# Просмотр событий в namespace argocd
kubectl get events -n argocd --sort-by='.lastTimestamp'

# Просмотр подов ArgoCD
kubectl get pods -n argocd -o wide

# История синхронизаций
argocd app history my-app

# Ожидание завершения операции и здоровья
argocd app wait my-app --operation --health

# Принудительная остановка зависшей операции
argocd app terminate-op my-app
```

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`ComparisonError`** | Ошибка в синтаксисе манифестов или недоступность репозитория. | Проверьте манифесты (`argocd app diff`) и доступ к Git (credentials в `argocd-repo-server`). |
| **`InvalidSpecError`** | Ошибка в конфигурации объекта `Application`. | Проверьте манифест Application: `spec.source`, `spec.destination`, `spec.syncPolicy`. |
| **`SyncError`** | Ошибка применения ресурсов в кластере (RBAC, API, validation). | Проверьте RBAC приложения, доступность API-сервера, валидность манифестов. |
| **`UnknownError`** | Неизвестная ошибка контроллера. | Просмотрите логи контроллера: `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller`. |
| **`SelfHeal не работает`** | Ручные правки не откатываются | Не включен `selfHeal` или игнорируется поле | Добавьте `selfHeal: true` и `RespectIgnoreDifferences=true` в `syncOptions`. |
| **`Prune не удаляет`** | Ресурсы не удаляются | Не включен `prune` в `automated` | Добавьте `prune: true` в `spec.syncPolicy.automated` (не в syncOptions!). |
| **`Dry Run завершается ошибкой`** | Ошибка валидации манифестов | Некорректный YAML или отсутствует CRD | Исправьте манифест или добавьте `SkipDryRunOnMissingResource=true`. |
| **`OutOfSync` не исчезает** | Поле не игнорируется корректно | Неверный путь в `ignoreDifferences` или неверный менеджер | `argocd app diff <name>` — покажет конкретные поля; сверьте имя менеджера с `managedFields`. |
| **`Sync operation blocked by sync window`** | Активное deny-окно или вне allow-окна | Sync Windows блокируют синхронизацию | Проверьте `argocd app get <name>` (поле `SyncWindow`); настройте `manualSync: true` или `syncOverrun: true` (v3.5+). |
| **`Shared resource` / `FailOnSharedResource`** | Ресурс управляется другим приложением | Конфликт владения ресурсом | Разделите ресурсы между приложениями или используйте `FailOnSharedResource=false` (default). |
| **`Resource exceeds annotation limit`** | Манифест > 256 KB в `last-applied-configuration` | Лимит client-side apply | Включите `ServerSideApply=true` в `syncOptions`. |
| **`Immutable field changed`** | Попытка изменить неизменяемое поле (selector, clusterIP) | Kubernetes запрещает update | Используйте `Force=true` (удаление + пересоздание) или `Replace=true`. |
| **`Hook завис / Sync не завершается`** | PreSync/PostSync Job не завершается | Нет `activeDeadlineSeconds` или баг в хуке | Добавьте `activeDeadlineSeconds` на Job; остановка: `argocd app terminate-op <name>`. |
| **`Retry не срабатывает`** | Синхронизация падает без повторов | Не настроена политика `retry` | Добавьте `retry.limit > 0` в `syncPolicy`. |
| **`Rollback отклонен`** | `argocd app rollback` не работает | Включен automated sync | Временно отключите `automated.enabled: false` или используйте Git-Revert. |

### Пошаговый алгоритм диагностики

1. **Проверьте статус:** `argocd app get <name>` — убедитесь, что статус `OutOfSync`/`Synced`/`Degraded`, проверьте поле `SyncWindow`.
2. **Просмотрите diff:** `argocd app diff <name>` — проверьте, какие именно поля различаются (Legacy или `--server-side-diff`).
3. **Проверьте настройки syncPolicy:** `automated.enabled`, `prune`, `selfHeal`, `syncOptions`.
4. **Проверьте Sync Windows:** Если есть ограничения по времени, дождитесь окончания блокировки или разрешите ручной синк.
5. **Просмотрите логи контроллера:** `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller` — найдите ошибки по времени.
6. **Проверьте Credentials:** Убедитесь, что Argo CD имеет доступ к Git-репозиторию (`argocd repo list`) и кластеру.
7. **Проверьте CRD:** Если используются кастомные ресурсы, убедитесь, что CRD установлены в кластере.
8. **Проверьте Health Checks:** Убедитесь, что ресурсы проходят проверку здоровья (кастомные Lua-скрипты в `argocd-cm` для CRD).

### Диагностические команды расширенные

```bash
# Принудительное обновление данных (без синхронизации)
argocd app get <app-name> --refresh
argocd app get <app-name> --hard-refresh

# Diff против конкретной ревизии Git
argocd app diff <app-name> --revision <commit-sha>

# Просмотр managedFields ресурса (для ignoreDifferences)
kubectl get <resource> <name> -o jsonpath='{.metadata.managedFields}' | jq

# Просмотр событий для конкретного ресурса
kubectl describe <resource> <name> | grep -A 10 Events

# Логи конкретного hook-Job
kubectl logs -n <namespace> -l job-name=<job-name>

# Метрики контроллера (Prometheus endpoint)
kubectl port-forward -n argocd svc/argocd-metrics 8082:8082
curl localhost:8082/metrics | grep argocd_app
```

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
- **Skip Reconcile:** Используйте `argocd.argoproj.io/skip-reconcile: "true"` (Alpha с v2.7.0) для полной остановки обработки приложения; на секрете кластера (с v3.4) — для всех приложений кластера.

## Ограничения и edge cases

### Ограничения

1. **Лимит ресурсов:** Argo CD имеет внутренние лимиты на количество управляемых ресурсов. Для очень больших приложений (>1000 ресурсов) рекомендуется разбивать на несколько ApplicationSets.
2. **Cross-namespace ресурсы:** Приложение может управлять ресурсами в нескольких namespaces (включая cluster-scoped), если это разрешено AppProject и RBAC. Отдельные ApplicationSets нужны для логической группировки.
3. **ApplicationSet и `automated`:** Политика `syncPolicy.automated` из шаблона применяется для обычных приложений ApplicationSet; при стратегии RollingSync автосинк принудительно отключается контроллером ApplicationSet.
4. **Множественные ApplicationSets:** Если ресурс управляется несколькими ApplicationSets, возникает конфликт. Используйте `FailOnSharedResource=true`.
5. **Skip Reconcile:** Аннотация `argocd.argoproj.io/skip-reconcile: "true"` (на приложении или, с v3.4, на секрете кластера) останавливает всю обработку — статус не обновляется, синхронизации не выполняются.
6. **Rollback при automated sync:** `argocd app rollback` невозможен для приложения с включенным automated sync — используйте Git-Revert.
7. **Multi-source приложения:** Отключенный `selfHeal` не гарантирует сохранения ручных изменений — изменение в другом источнике может вновь запустить autosync.
8. **Secret/ConfigMap при sync с SSA:** При `ServerSideApply=true` Secret/ConfigMap могут требовать явного `Replace=true` если превышают лимит аннотации.

### Edge Cases

1. **UI-откат и `OutOfSync`:** После UI-отката приложение переходит в состояние `OutOfSync` относительно Git. `SelfHeal` временно отключается для этого приложения.
2. **PreSync Hook и Sync Windows:** Если PreSync Hook (миграция БД) выполняется дольше Allow-окна: без `syncOverrun` операция приостанавливается контроллером (`Sync operation blocked by sync window`) и возобновляется, когда окно снова разрешит синхронизацию; с `syncOverrun: true` (v3.5+, на всех подходящих окнах) — завершается.
3. **Progressive Sync и Deny окно:** Если приложение попадает в Deny окно во время Progressive Sync, оно не будет синхронизировано до открытия Allow окна.
4. **Progressive Sync и ручная синхронизация:** Если вы вручную нажмете "Sync" на приложении, которое еще не подошло по очереди, оно будет синхронизировано, но это может нарушить логику `maxUpdate` текущего шага.
5. **PreDelete Hook и удаление ApplicationSet:** Если ApplicationSet удален во время выполняющейся синхронизации, операция завершится, но новые синхронизации будут невозможны.
6. **SelfHeal + IgnoreDifferences:** Если включены и `ignoreDifferences`, и `SelfHeal=true`, Argo CD может пытаться «починить» поля, которые не игнорируются. Убедитесь, что игнорируемые поля действительно исключены из diff.
7. **Prune не работает для ресурсов с OwnerReferences:** Удаление dependent-ресурсов происходит каскадно через Kubernetes API, а не через Argo CD.
8. **Selective Sync и история:** Селективная синхронизация (`--resource`/`--label`) **не** записывается в историю приложения — откат через `argocd app rollback` для такой операции невозможен.
9. **Selective Sync и хуки:** Хуки (PreSync/PostSync и т.д.) **не** выполняются при селективной синхронизации и при `--strategy apply`.
10. **HPA + SelfHeal конфликт:** Если в Git указано `replicas: 3` и включен `selfHeal`, Argo CD вернет количество реплик к значению из Git в течение одного цикла сверки (120s + jitter до 60s, плюс 5s self-heal timeout), конфликтуя с HPA. Решение — исключить `replicas` через `ignoreDifferences` с `managedFieldsManagers: [kube-controller-manager]`.
11. **Server-Side Diff fallback:** Если dry-run runner недоступен, Argo CD автоматически откатывается к клиентскому 3-way/2-way diff. Результат `argocd app diff --server-side-diff` может отличаться от клиентского diff.
12. **ignoreDifferences union:** Локальные (Application) и глобальные (argocd-cm) правила `ignoreDifferences` **объединяются (union)**, а не переопределяют друг друга. Локальное правило не отключает глобальное.
13. **Replace=true приоритет:** `Replace=true` имеет приоритет над `ServerSideApply=true` — используется `kubectl replace`/`create` вместо SSA.
14. **PrunePropagationPolicy default:** По умолчанию `foreground` — каскадное удаление dependent-ресурсов перед основными. `background` — фоновый GC, `orphan` — dependent-ресурсы остаются.
15. **ApplicationSet не добавляет метки:** Контроллер ApplicationSet **не добавляет** меток порождённым приложениям и их ресурсам (только через `preservedLabels`/`globalPreservedLabels`). Метку `argocd.argoproj.io/cluster` нельзя использовать по умолчанию — нужно явно задавать в `template.metadata.labels`.

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
