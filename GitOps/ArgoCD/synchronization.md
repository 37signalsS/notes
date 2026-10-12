# ArgoCD — синхронизация и политики

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; Server-Side Diff, syncOverrun, Progressive Syncs; Kubernetes 1.28–1.32+; bare-metal / on-premise)

## Определения

- **ArgoCD** — декларативный GitOps-инструмент непрерывной доставки для Kubernetes, автоматизирующий развертывание приложений и синхронизацию состояния кластера с Git-репозиторием.
- **Желаемое состояние (Desired State)** — эталонная конфигурация ресурсов (YAML, Helm, Kustomize), зафиксированная в Git-репозитории или OCI-реестре.
- **Фактическое состояние (Live State)** — текущее состояние манифестов и объектов в кластере Kubernetes, считываемое через Kubernetes API.
- **Цикл сверки (Reconciliation Loop)** — непрерывный процесс сопоставления Desired State и Live State, выполняемый контроллером Argo CD. Состоит из фаз **Refresh** (получение и рендеринг), **Diff** (сравнение) и **Sync** (применение изменений).
- **Дрейф конфигурации (Configuration Drift)** — расхождение между эталонным описанием в Git и фактическим состоянием объектов в кластере (например, после прямого выполнения `kubectl edit` или вмешательства внешнего оператора).
- **Волны синхронизации (Sync Waves)** — механизм упорядочивания деплоя манифестов на основе целочисленной аннотации `argocd.argoproj.io/sync-wave`. Ресурсы применяются строго по возрастанию волн; переход к следующей волне происходит только после достижения статуса `Healthy` всеми ресурсами текущей волны.
- **Хуки жизненного цикла (Hooks)** — запуск вспомогательных задач (Jobs, Pods) на определенных фазах синхронизации через аннотацию `argocd.argoproj.io/hook` (PreSync, Sync, PostSync, SyncFail, PreDelete, PostDelete). Хуки не управляются Argo CD как постоянные ресурсы приложения и могут удаляться по политике `argocd.argoproj.io/hook-delete-policy`.
- **Self-Heal** — механизм автоматического устранения дрейфа: откат ручных правок в кластере к эталонному состоянию в Git при включенном флаге `selfHeal: true` в секции `spec.syncPolicy.automated`.
- **Pruning (Очистка ресурсов)** — механизм удаления из кластера тех ресурсов, манифесты которых были удалены из Git-репозитория (`prune: true`).
- **Server-Side Apply (SSA)** — нативный механизм Kubernetes API для декларативного слияния изменений (`fieldManager=argocd`), устраняющий ограничение аннотации `kubectl.kubernetes.io/last-applied-configuration` (256 KB) и предотвращающий конфликты владения полями между несколькими контроллерами.
- **Server-Side Diff** — стратегия вычисления различий (v3.5+), при которой рендеренные манифесты отправляются на API-сервер в dry-run режиме (`ServerSideDiff=true`), позволяя учесть дефолтные значения схемы и мутирующие вебхуки (Mutating Admission Webhooks) до физического применения.
- **Параметры синхронизации (Sync Options)** — набор директив в `spec.syncPolicy.syncOptions`, тонко настраивающих процесс применения манифестов к API-серверу (создание namespace, порядок удаления, приоритет replace/apply).
- **Окна синхронизации (Sync Windows)** — правила в объекте `AppProject`, разрешающие (`allow`) или запрещающие (`deny`) запуск автоматической или ручной синхронизации для групп приложений по cron-расписанию.
- **Отслеживание ресурсов (Resource Tracking)** — метод связывания реальных объектов в кластере с управляющим объектом `Application` через аннотацию `argocd.argoproj.io/tracking-id` или метку `app.kubernetes.io/instance`.
- **Действия над ресурсами (Resource Actions)** — кастомные сценарии модификации ресурсов (рестарт Deployment, масштабирование, очистка кэша), запускаемые через UI, CLI или REST API без изменения манифестов в Git.
- **Оценка здоровья (Health Assessment)** — алгоритм определения функционального статуса ресурса (`Healthy`, `Progressing`, `Degraded`, `Suspended`, `Missing`, `Unknown`), встроенный в контроллер или переопределяемый через Lua-скрипты в `argocd-cm`.
- **Progressive Sync** — стратегия поэтапного развертывания генераторов `ApplicationSets` по кластерам и окружениям (`RollingSync`) с автоматической остановкой раскатки при сбое первой группы.
- **Skip Reconcile** — механизм полной заморозки обработки приложения или всех приложений кластера через аннотацию `argocd.argoproj.io/skip-reconcile: "true"` (Alpha с v2.7.0 для Application; с v3.4 для секрета кластера).

---

## Архитектура и основные концепции

### Детальный цикл сверки (Reconciliation Loop)

Контроллер приложений `argocd-application-controller` непрерывно синхронизирует состояние системы. Сверка инициируется входящим Webhook от корпоративного Git-хостинга (GitLab, Gitea) либо периодическим опросом (по умолчанию 120s + случайный jitter до 60s, максимальный период 3 минуты — настраивается через ключи `timeout.reconciliation` и `timeout.reconciliation.jitter` в `argocd-cm`):

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            Argo CD Reconciliation Loop                           │
├──────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│   ┌─────────────────────┐    ┌─────────────────────┐    ┌────────────────────┐   │
│   │       Refresh       │───▶│        Diff         │───▶│        Sync        │   │
│   │    (Обнаружение)    │    │     (Сравнение)     │    │    (Применение)    │   │
│   └─────────────────────┘    └─────────────────────┘    └────────────────────┘   │
│              │                          │                          │             │
│              ▼                          ▼                          ▼             │
│   ┌─────────────────────┐    ┌─────────────────────┐    ┌────────────────────┐   │
│   │  argocd-repo-server │    │  argocd-application │    │  Kubernetes API    │   │
│   │  (Git clone/fetch,  │    │     controller      │    │  (SSA / Client,    │   │
│   │   manifest render,  │    │   (K8s Live Cache,  │    │   Admission Hooks, │   │
│   │   Redis Cache)      │    │    diffing, health) │    │   delete, prune)   │   │
│   └─────────────────────┘    └─────────────────────┘    └────────────────────┘   │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

#### 1. Фаза Refresh (Обнаружение и рендеринг)
- `argocd-repo-server` обновляет локальный репозиторий (`git fetch` / shallow clone).
- Выполняется компиляция манифестов: Helm (`helm template`), Kustomize (`kustomize build`) или **[кастомные плагины CMP v2](./argocd_custom_tooling.md)**.
- Результат рендеринга кэшируется в Redis.
- Контроллер приложений запрашивает актуальный Live State из локального кэша информаторов (K8s API Informers) по ключу отслеживания (Tracking ID).

#### 2. Фаза Diff (Сравнение)
- Сравниваются эталонные манифесты (Desired State) и объекты кластера (Live State).
- **Legacy Diff (по умолчанию):** 3-way слияние на основе аннотации `kubectl.kubernetes.io/last-applied-configuration`.
- **Server-Side Diff (v3.5+):** выполняет SSA в режиме `dry-run=All` прямо на API-сервере Kubernetes. Это исключает ложный `OutOfSync`, вызванный мутирующими вебхуками (например, инъекцией sidecar, модификацией аннотаций, дефолтными значениями полей). Включается аннотацией `argocd.argoproj.io/compare-options: ServerSideDiff=true` или флагом контроллера `--server-side-diff`.
- Применяются правила **[игнорирования различий](./synchronization/ignore_differences.md)** (`spec.ignoreDifferences` и `resource.customizations.ignoreDifferences` в `argocd-cm`).
- Формируется статус синхронизации: `Synced` (состояния идентичны) или `OutOfSync` (зафиксирован дрейф).
- Рассчитывается статус здоровья: `Healthy`, `Progressing`, `Degraded`, `Suspended`, `Missing`, `Unknown`.

#### 3. Фаза Sync (Применение изменений)
- Запускается вручную оператором либо автоматически (если настроена секция `spec.syncPolicy.automated` и отсутствуют блокирующие окна Sync Windows).
- Контроллер строит граф исполнения на основе фаз (Hooks) и волн (`argocd.argoproj.io/sync-wave`).
- Порядок применения ресурсов:
  $$\text{Фаза} \longrightarrow \text{Волна} \longrightarrow \text{Kind (Namespace } \to \text{ CRD } \to \text{ Workloads)} \longrightarrow \text{Имя}$$
- Метод применения:
  - Client-Side Apply (по умолчанию): `kubectl apply`.
  - Server-Side Apply: `kubectl apply --server-side --force-conflicts` при `ServerSideApply=true`.
  - Replace: `kubectl replace --force` или `create` при `Replace=true` (имеет безусловный приоритет над SSA).
  - Force: `kubectl delete` с последующим `kubectl create` при `Force=true`.
- После применения контроллер ожидает перехода ресурсов волны в статус `Healthy`.
- При наличии `prune: true` удаляются ресурсы, отсутствующие в Git (в порядке, обратном волнам деплоя).

### Временные интервалы и внутренние таймауты

| Параметр | Расположение | Значение по умолчанию | Назначение в SRE/Sysadmin |
| :--- | :--- | :--- | :--- |
| `timeout.reconciliation` | `argocd-cm` | `120s` | Базовый интервал опроса Git при отсутствии входящих вебхуков. |
| `timeout.reconciliation.jitter` | `argocd-cm` | `60s` | Случайная задержка (0–60с) для предотвращения «громоподобного стада» (Thundering Herd) запросов к Git. |
| `--self-heal-timeout-seconds` | Флаг `argocd-application-controller` | `5s` | Задержка перед запуском автоисправления дрейфа после его обнаружения. |
| `ARGOCD_SYNC_WAVE_DELAY` | Переменная окружения контроллера | `2s` | Пауза между успешным завершением волны и стартом следующей (дает время контроллерам K8s среагировать). |
| `--status-processors` | Флаг `argocd-application-controller` | `20` | Количество параллельных воркеров обработки статуса и диффа приложений. |
| `--operation-processors` | Флаг `argocd-application-controller` | `10` | Количество параллельных воркеров выполнения операций синхронизации. |

### Webhook-driven сверка против периодического опроса (Polling)

В корпоративных bare-metal средах с сотнями микросервисов опрос Git раз в 3 минуты (`timeout.reconciliation: 180s`) вызывает:
1. Пиковые нагрузки и исчерпание лимитов (HTTP 429) на внутреннем сервере GitLab/Gitea.
2. Неоправданный расход CPU и дискового I/O в `argocd-repo-server`.
3. Задержку доставки изменений от 1 секунды до 3 минут.

**Инженерное решение:**
- Увеличение `timeout.reconciliation` до `1h`–`2h` в `argocd-cm`.
- Настройка мгновенных push-уведомлений через вебхук `https://<argocd-server>/api/webhook` (GitLab/Gitea). При получении вебхука `argocd-server` отправляет событие в очередь контроллера, запуская немедленный Refresh конкретного репозитория за доли секунды.

### Методы отслеживания ресурсов (Resource Tracking)

Для однозначного сопоставления объектов в кластере с манифестом `Application` используется один из методов (параметр `application.resourceTrackingMethod` в `argocd-cm`):

| Метод | Идентификатор в K8s | Достоинства | Ограничения и риски |
| :--- | :--- | :--- | :--- |
| **label** (legacy) | `app.kubernetes.io/instance: <app-name>` | Стандартная метка K8s ecosystem | Ограничение длины значения метки (63 символа). Конфликтует со стандартными чартами Helm. |
| **annotation** | `argocd.argoproj.io/tracking-id: <app-name>:<group>/<kind>:<ns>/<name>` | Нет лимита длины имени, полная совместимость с Helm | Требует поддержки мутации аннотаций, не фильтруется селекторами меток `kubectl -l`. |
| **annotation+label** | И аннотация, и метка одновременно | Максимальная совместимость при миграциях | Избыточность метаданных. |

**Конфигурация в `argocd-cm`:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  # Рекомендуемый метод для enterprise-кластеров
  application.resourceTrackingMethod: annotation
```

Подробное руководство по отслеживанию, миграции и диагностике orphan-ресурсов: **[Методы отслеживания ресурсов](./argocd_resource_tracking.md)**.

### Фазы синхронизации и жизненный цикл хуков

Процесс синхронизации разделен на строгие фазы. Хуки представляют собой Job или Pod с аннотацией `argocd.argoproj.io/hook`:

```text
                ┌──────────────────────────────────────────────────┐
                │          Синхронизация приложения                │
                └────────────────────────┬─────────────────────────┘
                                         │
                                         ▼
                                  ┌─────────────┐
                                  │   PreSync   │  (Бэкап, миграция БД)
                                  └──────┬──────┘
                                         │  Успех
                                         ▼
                                  ┌─────────────┐
                                  │    Sync     │  (Применение манифестов по волнам)
                                  └──────┬──────┘
                                         │  Успех
                                         ▼
                                  ┌─────────────┐
                                  │  PostSync   │  (Smoke-тесты, уведомления, прогрев кэша)
                                  └──────┬──────┘
                                         │
                    ┌────────────────────┴────────────────────┐
                    │ При сбое                                │ При удалении Application
                    ▼                                         ▼
             ┌─────────────┐                           ┌─────────────┐
             │  SyncFail   │ (Алерт, откат миграции)   │  PreDelete  │ (Очистка внешних ресурсов)
             └─────────────┘                           └──────┬──────┘
                                                              │
                                                              ▼
                                                       ┌─────────────┐
                                                       │ PostDelete  │ (Уведомление об удалении)
                                                       └─────────────┘
```

| Фаза | Описание | Поведение при сбое |
| :--- | :--- | :--- |
| **PreSync** | Выполняется до начала развертывания основных манифестов. | Прерывает всю синхронизацию. Основные манифесты **не** применяются. Кластер остается в предыдущей версии. |
| **Sync** | Выполняется параллельно с манифестами, входящими в фазу Sync. | Синхронизация помечается как `Failed`. |
| **PostSync** | Выполняется после того, как все основные ресурсы перешли в статус `Healthy`. | Приложение переходит в статус `Degraded`/`Failed`, но основные ресурсы уже применены. |
| **SyncFail** | Запускается **только** в случае сбоя фаз PreSync, Sync или применения манифестов. | Выполняет компенсирующие действия (оповещение SRE, очистка временных таблиц). |
| **PreDelete** (v3.3+) | Выполняется перед удалением приложения из кластера. | Блокирует удаление приложения до завершения хука. |
| **PostDelete** (v2.10+) | Выполняется после полного удаления ресурсов приложения. | Финализирует удаление, отправляет аудит. |

#### Политики удаления хуков (`argocd.argoproj.io/hook-delete-policy`)
- `HookSucceeded` — удалить объект Job после успешного завершения (exit code 0).
- `HookFailed` — удалить объект Job при аварийном завершении. **Внимание (SRE Best Practice):** не используйте `HookFailed` для критичных задач (миграции БД), так как удаление пода уничтожит логи с ошибкой, сделав невозможной диагностику!
- `BeforeHookCreation` — удалить старый Job с тем же именем перед запуском нового. **Рекомендуемый стандарт** для обеспечения идемпотентности повторных сисадминских деплоев.
- Поддерживается указание политик через запятую: `BeforeHookCreation,HookSucceeded`.

### Волны синхронизации (Sync Waves)

Аннотация `argocd.argoproj.io/sync-wave: "<целое число>"` (положительное, ноль или отрицательное) определяет строгий порядок деплоя:

```yaml
# 1. Сначала пространство имен (волна -10)
apiVersion: v1
kind: Namespace
metadata:
  name: billing
  annotations:
    argocd.argoproj.io/sync-wave: "-10"
---
# 2. Конфигурация и секреты (волна -5)
apiVersion: v1
kind: ConfigMap
metadata:
  name: billing-config
  namespace: billing
  annotations:
    argocd.argoproj.io/sync-wave: "-5"
---
# 3. Основной микросервис (волна 0 — по умолчанию)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-api
  namespace: billing
  annotations:
    argocd.argoproj.io/sync-wave: "0"
---
# 4. Сервис и сетевой доступ (волна 5)
apiVersion: v1
kind: Service
metadata:
  name: billing-api
  namespace: billing
  annotations:
    argocd.argoproj.io/sync-wave: "5"
```

**Ключевые правила работы волн:**
1. Ресурсы в волне $N$ не начнут применяться, пока абсолютно все ресурсы в волне $N-1$ не получат статус `Healthy`.
2. Если Deployment в волне 0 находится в статусе `Progressing` (например, выкачивает тяжелый образ из локального реестра), контроллер ждет завершения до истечения таймаута операции.
3. При включенном `prune: true` удаление устаревших ресурсов выполняется в **обратном порядке волн** (от больших индексов к меньшим), гарантируя, что потребители будут удалены раньше зависимостей (например, Deployment удалится раньше Secret/ConfigMap).

### Server-Side Apply (SSA) против Client-Side Apply

Client-Side Apply сохраняет весь отправляемый манифест в аннотации `kubectl.kubernetes.io/last-applied-configuration`. Это создает критические эксплуатационные проблемы:
- **Лимит 256 KB:** манифесты больших CRD, списков ролей или ConfigMap вызывают ошибку `metadata.annotations: Too long: must have at most 262144 bytes`.
- **Конфликт контроллеров:** если HPA меняет `.spec.replicas`, а cert-manager инжектирует сертификаты в Secret, классический `apply` перезаписывает чужие поля, вызывая бесконечный `OutOfSync` и петлю reconciliation.

**Преимущества Server-Side Apply (`ServerSideApply=true`):**
- Управление властью над полями переносится в `metadata.managedFields` Kubernetes API с менеджером `fieldManager=argocd`.
- Argo CD владеет только теми полями, которые явно объявлены в Git. Поля, созданные runtime-контроллерами (статусы, реплики от HPA, динамические порты), не конфликтуют с деплоем.
- Полное отсутствие ограничения на размер манифеста в 256 KB.

### Server-Side Diff (v3.5+)

При традиционном diff Argo CD сравнивает отрендеренный YAML с Live-объектом в памяти. Однако многие контроллеры кластера используют мутирующие вебхуки (Mutating Admission Webhooks): добавляют переменные окружения, security-контексты, прокси-контейнеры. Это приводило к постоянному ложному статусу `OutOfSync`.

**Server-Side Diff** отправляет манифест в K8s API с флагом `dry-run=All`. API-сервер прогоняет манифест через все admission-контроллеры и схему валидации, возвращая точный предсказанный результат.
- Включение для отдельного приложения:
  ```yaml
  metadata:
    annotations:
      argocd.argoproj.io/compare-options: ServerSideDiff=true
  ```
- Включение глобально в CLI: `argocd app diff <app> --server-side-diff`.
- Fallback: если dry-run эндпоинт недоступен, контроллер автоматически возвращается к классическому 3-way diff.

### Progressive Syncs (ApplicationSet RollingSync)

При управлении сотнями кластеров и пространств имен через `ApplicationSet` одновременный деплой чреват глобальной деградацией сервиса при ошибке в коде. Progressive Syncs (Beta с v3.3+) реализует ступенчатую раскатку:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: core-services
  namespace: argocd
spec:
  generators:
  - clusters:
      selector:
        matchLabels:
          tier: internal
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
        maxUpdate: 25%
  template:
    metadata:
      name: '{{name}}-service'
    spec:
      project: default
      source:
        repoURL: https://git.internal.company/infra/manifests.git
        targetRevision: HEAD
        path: apps/service
      destination:
        server: '{{server}}'
        namespace: production
```
**Важное замечание для SRE:** при активации стратегии `RollingSync` стандартный автосинк `spec.syncPolicy.automated` внутри сгенерированных приложений принудительно отключается контроллером ApplicationSet. Контроллер сам руководит фазами переходов между шагами на основе здоровья предыдущей группы.

Подробное руководство: **[Прогрессивная синхронизация](./synchronization/scenarios/progressive_sync.md)**.

### Механизм Skip Reconcile

Аннотация `argocd.argoproj.io/skip-reconcile: "true"` полностью останавливает обработку контроллером.
- На уровне приложения: контроллер не проверяет Git, не строит diff, не выполняет ручные и автоматические синхронизации. Поле `status` замораживается.
- На уровне секрета кластера (v3.4+): приостанавливает обработку **всех** приложений, нацеленных на данный кластер.

**Сценарии применения в Sysadmin/SRE:**
1. Экстренное обслуживание кластера (обновление версии Kubernetes с v1.28 до v1.30).
2. Аварийный отказ сетевого хранилища (Ceph, NFS), когда массовый перезапуск подов вызовет лавину алертов.
3. Проведение ручных аварийных работ (Break-Glass) без риска перезаписи со стороны `selfHeal`.

---

## Параметры и политики синхронизации (Sync Options & Policies)

Поведение контроллера при согласовании состояний задается в двух секциях манифеста `Application`:
1. `spec.syncPolicy.automated` — политика автоматического запуска.
2. `spec.syncPolicy.syncOptions` — директивы низкоуровневого применения изменений в API-сервер.

### Параметры автоматической синхронизации (`spec.syncPolicy.automated`)

| Параметр | Тип | По умолчанию | Описание и инженерные последствия |
| :--- | :--- | :--- | :--- |
| **`enabled`** | boolean | `null` (= true) | Явное включение/отключение автосинка (v3.1+). При `enabled: false` автосинк заблокирован даже при наличии `prune` и `selfHeal`. |
| **`prune`** | boolean | `false` | Автоматическое удаление ресурсов из кластера, если их манифесты удалены из Git. Защита от мусорных объектов. |
| **`selfHeal`** | boolean | `false` | Автоматический возврат к Git-состоянию при ручных изменениях в кластере. Срабатывает с задержкой 5с (`--self-heal-timeout-seconds`). |
| **`allowEmpty`** | boolean | `false` | Разрешение синхронизации при полностью пустом Git-репозитории. **Критично:** всегда держите `false`, чтобы случайное удаление ветки не уничтожило весь namespace! |

### Директивы применения (`spec.syncPolicy.syncOptions`)

| Опция | По умолчанию | Назначение и рекомендации |
| :--- | :--- | :--- |
| **`CreateNamespace=true`** | `false` | Автоматически создает целевой namespace, если он отсутствует в кластере. |
| **`ServerSideApply=true`** | `false` | Включает Server-Side Apply. Рекомендуется для всех современных сред (K8s 1.28+) для исключения конфликтов полей и обхода лимита 256 KB. |
| **`RespectIgnoreDifferences=true`** | `false` | Заставляет механизм синхронизации учитывать правила `ignoreDifferences` при отправке патча. Без этого флаг игнорирует различия только для отрисовки статуса, но при синке перезаписывает поля! |
| **`ApplyOutOfSyncOnly=true`** | `false` | Применяет к API-серверу только те объекты, которые находятся в статусе `OutOfSync`. Критично снижает нагрузку на K8s API в приложениях с сотнями ресурсов. |
| **`PruneLast=true`** | `false` | Удаляет устаревшие ресурсы только **после** того, как новые ресурсы успешно применились и перешли в статус `Healthy`. Предотвращает Downtime. |
| **`PrunePropagationPolicy=foreground\|background\|orphan`** | `foreground` | Стратегия каскадного удаления зависимых ресурсов через Garbage Collector Kubernetes. |
| **`SkipDryRunOnMissingResource=true`** | `false` | Пропускает валидацию dry-run для ресурсов, чьи CRD еще не установлены в кластере (решает проблему первого деплоя операторов). |
| **`Replace=true`** | `false` | Использовать `kubectl replace`/`create` вместо `apply`. Имеет безусловный приоритет над `ServerSideApply=true`. |
| **`FailOnSharedResource=true`** | `false` | Завершать синк ошибкой, если ресурс уже помечен как принадлежащий другому приложению Argo CD. Защищает от перезаписи объектов между командами. |
| **`Validate=false`** | `true` | Отключает валидацию манифестов по схеме OpenAPI K8s API. Применяется только при несовместимости версий схем. |
| **`Force=true`** | `false` | Жесткое удаление и пересоздание ресурса (`delete` + `create`) при каждом синке. Используется для объектов с неизменяемыми полями. |

### Политика повторных попыток (`spec.syncPolicy.retry`)

При сетевых задержках, сбоях etcd или временной недоступности репозитория контроллер может автоматически повторять попытки синхронизации:

```yaml
spec:
  syncPolicy:
    retry:
      limit: 5              # Максимальное количество попыток
      backoff:
        duration: 5s        # Начальная задержка между попытками
        factor: 2           # Множитель экспоненциальной задержки
        maxDuration: 3m     # Верхняя граница задержки
```

Формула расчета интервала между попытками:
$$\text{Интервал} = \min\left(\text{duration} \times \text{factor}^{(\text{попытка} - 1)},\; \text{maxDuration}\right)$$
Для вышеуказанной конфигурации: 5с $\to$ 10с $\to$ 20с $\to$ 40с $\to$ 80с (но не более 3 минут).

---

## Действия над ресурсами (Resource Actions)

Resource Actions предоставляют сисадминам и разработчикам механизм выполнения регламентных процедур над объектами Kubernetes без прямого доступа `kubectl` к production-кластеру и без внесения коммитов в Git.

### Архитектура и поток управления

```text
  argocd app action run <action> --kind <kind> --name <name>
                           │
                           ▼
               ┌───────────────────────┐
               │     argocd-server     │  (Авторизация через RBAC AppProject)
               └───────────┬───────────┘
                           │
                           ▼
               ┌───────────────────────┐
               │    Lua-генератор      │  (Читает lua-скрипт из argocd-cm)
               └───────────┬───────────┘
                           │
                           ▼
               ┌───────────────────────┐
               │ Kubernetes API-сервер │  (kubectl patch / replace)
               └───────────────────────┘
```

### Конфигурация в `argocd-cm`

Действия описываются на языке Lua в ConfigMap `argocd-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  # Кастомное действие рестарта Deployment
  resource.customizations.actions.apps_Deployment: |
    discovery.lua: |
      actions = {}
      actions["restart"] = {["displayName"] = "Rolling Restart"}
      return actions
    definitions.lua: |
      actions = {}
      actions["restart"] = function(obj)
        if obj.spec.template.metadata == nil then
          obj.spec.template.metadata = {}
        end
        if obj.spec.template.metadata.annotations == nil then
          obj.spec.template.metadata.annotations = {}
        end
        obj.spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"] = os.date("!%Y-%m-%dT%TZ")
        return obj
      end
      return actions
```

---

## Практические сценарии

### Предварительные требования

Перед выполнением сценариев убедитесь в соблюдении условий:
1. **Кластер Kubernetes:** версия v1.28–v1.32+ (bare-metal или on-premise установка).
2. **Argo CD:** версия v3.5.x развернута в namespace `argocd`. Проверка статуса подов:
   ```bash
   kubectl get pods -n argocd -l app.kubernetes.io/part-of=argocd
   # → Все поды (server, repo-server, application-controller, redis) в статусе Running, READY 1/1
   ```
3. **CLI `argocd`:** утилита установлена и настроена авторизация администратора:
   ```bash
   argocd version --short
   # → argocd: v3.5.x, argocd-server: v3.5.x
   argocd login argocd.internal.company:443 --username admin --password <secure-password> --insecure
   # → 'admin:login' logged in successfully
   ```
4. **Git-репозиторий:** настроен доступ (SSH-ключ или Personal Access Token) в `argocd-repo-server`.
5. **AppProject:** создан проект `production-project` с правами деплоя в требуемые namespaces.

---

### Сценарий 1: Эталонная автоматическая синхронизация для Production

**Цель:** настроить отказоустойчивую автоматическую синхронизацию с защитой от непреднамеренных удалений, оптимизацией вызовов API и гарантией очередности применения.

#### 1. Подготовка манифеста `Application`

Создайте файл `app-production.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-production
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: production-project
  source:
    repoURL: https://git.internal.company/finance/billing.git
    targetRevision: main
    path: k8s/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: billing
  syncPolicy:
    automated:
      enabled: true                 # Явное включение
      prune: true                   # Удалять удаленные из Git ресурсы
      selfHeal: true                # Откатывать ручные правки в кластере
      allowEmpty: false             # Защита от удаления всего при пустом репо
    syncOptions:
    - CreateNamespace=true          # Создать namespace billing при отсутствии
    - ServerSideApply=true          # SSA для разрешения конфликтов полей
    - RespectIgnoreDifferences=true  # Учитывать ignoreDifferences при apply
    - ApplyOutOfSyncOnly=true       # Не трогать немодифицированные объекты
    - PruneLast=true                # Удалять старое только после здоровья нового
    - PrunePropagationPolicy=foreground # Каскадное удаление dependents
    - FailOnSharedResource=true     # Защита от конфликта владения с другими приложениями
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

#### 2. Применение и валидация

```bash
kubectl apply -f app-production.yaml
# → application.argoproj.io/billing-production created

# Принудительный опрос и ожидание статуса
argocd app get billing-production --refresh
# → App Name: billing-production
# → Sync Status: Synced to main
# → Health Status: Healthy
# → Sync Policy: Automated (Prune: true, SelfHeal: true)

# Имитация дрейфа конфигурации (ручная правка через kubectl)
kubectl patch deployment billing-service -n billing --type merge -p '{"spec":{"replicas":10}}'
# → deployment.apps/billing-service patched

# Проверка реакции Self-Heal (ожидание до 180с сверки + 5с таймаута self-heal)
argocd app get billing-production --refresh
# → Реплики автоматически возвращены к значению из Git (3)
kubectl get deployment billing-service -n billing -o jsonpath='{.spec.replicas}'
# → 3
```

---

### Сценарий 2: Ручная контролируемая синхронизация с аудитом и pre-flight diff

**Цель:** выполнить регламентный релиз в production с предварительной инспекцией диффа, симуляцией через dry-run и фиксацией номера тикета в аудит-логе.

#### 1. Настройка манифеста для ручного управления

```yaml
spec:
  syncPolicy:
    # automated отсутствует — ручной режим
    syncOptions:
    - ServerSideApply=true
    - PruneLast=true
    retry:
      limit: 2
```

#### 2. Процедура деплоя и инспекции

```bash
# Шаг 1: Инспекция расхождений с учетом серверных вебхуков
argocd app diff billing-production --server-side-diff
# → ===== apps/Deployment billing/billing-service ======
# → 132c132
# → <         image: registry.internal.company/billing:v2.4.0
# → ---
# → >         image: registry.internal.company/billing:v2.5.0
# exit code: 1 (есть расхождения)

# Шаг 2: Симуляция применения (Dry Run)
argocd app sync billing-production --dry-run
# → Name             Type        Sync Status  Health Status  Message
# → billing-service  Deployment  OutOfSync    Healthy        dry-run apply succeeded

# Шаг 3: Выполнение синхронизации с метаданными аудита
argocd app sync billing-production \
  --prune \
  --info ticket=OPS-48291 \
  --info engineer=sysadmin-team
# → TIMESTAMP                  GROUP        KIND   NAMESPACE                  NAME    STATUS   HEALTH        HOOK  MESSAGE
# → 2026-10-12T20:30:00+03:00   apps  Deployment     billing       billing-service    Synced  Progressing          deployment.apps/billing-service configured

# Шаг 4: Блокирующее ожидание перехода в Healthy
argocd app wait billing-production --operation --health --timeout 300
# → Operation: Succeeded
# → Health: Healthy

# Шаг 5: Проверка журнала операций
argocd app history billing-production
# → ID  DATE                           REVISION  INFO
# → 1   2026-10-12 20:30:00 +0300 MSK  a8f3b1c   ticket=OPS-48291, engineer=sysadmin-team
```

---

### Сценарий 3: Настройка Sync Waves и PreSync/PostSync хуков для миграции БД

**Цель:** гарантировать порядок применения: `Namespace` $\to$ `Secret/ConfigMap` $\to$ миграция БД (`PreSync Job`) $\to$ `Deployment` $\to$ `Service` $\to$ интеграционные тесты (`PostSync Job`).

#### 1. Описание манифестов с волнами и хуками

```yaml
# 1. Namespace (Волна -10)
apiVersion: v1
kind: Namespace
metadata:
  name: accounting
  annotations:
    argocd.argoproj.io/sync-wave: "-10"
---
# 2. Секреты подключения к СУБД (Волна -5)
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
  namespace: accounting
  annotations:
    argocd.argoproj.io/sync-wave: "-5"
type: Opaque
stringData:
  DB_PASSWORD: "HardenedPassword"
---
# 3. PreSync Hook: Миграция схемы БД (Волна -1)
apiVersion: batch/v1
kind: Job
metadata:
  name: schema-migration-v3
  namespace: accounting
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation,HookSucceeded
    argocd.argoproj.io/sync-wave: "-1"
spec:
  activeDeadlineSeconds: 600       # Защита от зависания миграции (10 минут)
  backoffLimit: 1
  template:
    spec:
      containers:
      - name: migrator
        image: registry.internal.company/accounting/migrator:v3.1.0
        command: ["/app/migrate", "--env=production"]
      restartPolicy: Never
---
# 4. Основное приложение (Волна 0)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: accounting-app
  namespace: accounting
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  replicas: 3
  selector:
    matchLabels:
      app: accounting
  template:
    metadata:
      labels:
        app: accounting
    spec:
      containers:
      - name: app
        image: registry.internal.company/accounting/app:v3.1.0
        ports:
        - containerPort: 8080
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080
---
# 5. Сетевой сервис (Волна 5)
apiVersion: v1
kind: Service
metadata:
  name: accounting-svc
  namespace: accounting
  annotations:
    argocd.argoproj.io/sync-wave: "5"
spec:
  ports:
  - port: 80
    targetPort: 8080
  selector:
    app: accounting
---
# 6. PostSync Hook: Проверка доступности (Волна 10)
apiVersion: batch/v1
kind: Job
metadata:
  name: smoke-test
  namespace: accounting
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
    argocd.argoproj.io/sync-wave: "10"
spec:
  activeDeadlineSeconds: 120
  backoffLimit: 0
  template:
    spec:
      containers:
      - name: curl-check
        image: registry.internal.company/base/curl:8.5.0
        command: ["curl", "-f", "http://accounting-svc.accounting.svc.cluster.local/healthz"]
      restartPolicy: Never
```

#### 2. Запуск и отслеживание выполнения

```bash
argocd app sync accounting-app
# Отслеживание логов хука миграции в реальном времени:
argocd app logs accounting-app --kind Job --name schema-migration-v3 -f
# → [INFO] Applying migration 003_add_audit_table...
# → [INFO] Migration applied successfully in 1.4s

# Проверка перехода волн:
argocd app get accounting-app
# → Phase: Succeeded, Health: Healthy
```

---

### Сценарий 4: Разрешение конфликтов Server-Side Apply и HPA

**Цель:** обеспечить совместную работу Argo CD и HorizontalPodAutoscaler над полем `spec.replicas` без возникновения статуса `OutOfSync` и без отключения `selfHeal`.

#### 1. Определение менеджера полей

Выясните, какой менеджер управляет полем `replicas` в работающем Deployment:
```bash
kubectl get deployment billing-service -n billing -o jsonpath='{range .metadata.managedFields[*]}{.manager}{"\t"}{.fieldsV1}{"\n"}{end}' | grep replicas
# → kube-controller-manager    {"f:spec":{"f:replicas":{}}}
```

#### 2. Настройка `ignoreDifferences` с `managedFieldsManagers`

В манифесте `Application`:

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    name: billing-service
    namespace: billing
    managedFieldsManagers:
    - kube-controller-manager      # Игнорировать любые поля, записанные HPA-контроллером
  syncPolicy:
    automated:
      enabled: true
      selfHeal: true
    syncOptions:
    - ServerSideApply=true
    - RespectIgnoreDifferences=true # КРИТИЧНО: не затирать реплики при apply
```

#### 3. Валидация

```bash
# 1. Примените манифест
kubectl apply -f application.yaml

# 2. Принудительно сымитируйте автомасштабирование HPA
kubectl scale deployment billing-service -n billing --replicas=8
# → deployment.apps/billing-service scaled

# 3. Выполните refresh в Argo CD
argocd app get billing-production --refresh
# → Sync Status: Synced
# → Реплики остаются равными 8, Self-Heal НЕ откатывает их к Git-значению!
```

---

### Сценарий 5: Настройка Sync Windows для блокировки деплоев в нерабочее время

**Цель:** запретить автоматический деплой в production в праздники, выходные и ночные часы. Разрешить автодеплой только в рабочие дни (Пн-Пт) с 10:00 до 18:00 по московскому времени. Разрешить экстренный ручной деплой в любое время.

#### 1. Описание Sync Windows в `AppProject`

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production-project
  namespace: argocd
spec:
  syncWindows:
  - kind: allow
    schedule: "0 10 * * 1-5"       # Пн-Пт в 10:00 MSK
    duration: 8h                   # Длительность окна: 8 часов (до 18:00)
    applications:
    - "*-production"
    manualSync: true               # Разрешить инженеру ручной синк вне окна
    timeZone: "Europe/Moscow"      # IANA таймзона
    syncOverrun: true              # v3.5+: не убивать синк, начавшийся до 18:00
```

#### 2. Проверка состояния окон через CLI

```bash
argocd proj windows list production-project
# → ID  STATUS    KIND   SCHEDULE       DURATION  APPLICATIONS    MANUALSYNC  OVERRUN
# → 0   Inactive  allow  0 10 * * 1-5   8h        *-production    Enabled     Enabled

# Проверка статуса приложения вне рабочего окна:
argocd app get billing-production
# → Sync Status: OutOfSync (sync window active: auto sync denied)
```

---

### Сценарий 6: Процедура аварийного отката (Rollback / Break-Glass) при включенном автосинке

**Проблема:** если приложение настроено с `automated.selfHeal: true`, команда `argocd app rollback` возвращает ошибку, так как контроллер немедленно обнаружит расхождение с коммитом в Git и выполнит откат обратно к коду.

**Стандартная процедура SRE / Sysadmin (GitOps-Way):**

1. **Штатный откат через Git (рекомендуется):**
   ```bash
   git revert HEAD --no-edit
   git push origin main
   argocd app sync billing-production
   ```

2. **Экстренный аварийный откат (Break-Glass Protocol при падении сервиса):**
   Если Git-хостинг недоступен или требуется восстановить работу сервиса за секунды:

   ```bash
   # Шаг 1: Заморозка сверки Argo CD
   kubectl annotate application billing-production -n argocd \
     argocd.argoproj.io/skip-reconcile="true" --overwrite
   # → application.argoproj.io/billing-production annotated

   # Шаг 2: Откат рабочей нагрузки в кластере напрямую через K8s
   kubectl rollout undo deployment/billing-service -n billing
   # → deployment.apps/billing-service rolled back

   # Шаг 3: Проверка восстановления сервиса
   kubectl rollout status deployment/billing-service -n billing
   # → deployment "billing-service" successfully rolled out

   # Шаг 4: Устранение проблемы в Git-репозитории (фиксация стабильного образа)
   # ... инженер пушит исправление в main ...

   # Шаг 5: Снятие заморозки сверки
   kubectl annotate application billing-production -n argocd \
     argocd.argoproj.io/skip-reconcile-
   # → application.argoproj.io/billing-production annotated (removed)
   ```

---

### Сценарий 7: Настройка Webhook от корпоративного GitLab/Gitea

**Цель:** исключить задержку деплоя в 3 минуты и устранить постоянную нагрузку опроса репозиториев на bare-metal GitLab сервере.

#### 1. Генерация и сохранение секретного токена

```bash
# Генерация надежного токена
WEBHOOK_SECRET=$(openssl rand -hex 32)

# Сохранение в secret Argo CD
kubectl patch secret argocd-secret -n argocd --type merge -p \
  "{\"stringData\":{\"webhook.gitlab.secret\":\"$WEBHOOK_SECRET\"}}"
# → secret/argocd-secret patched
```

#### 2. Увеличение интервала фонового опроса в `argocd-cm`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  # Увеличиваем интервал фонового опроса до 1 часа, полагаясь на вебхуки
  timeout.reconciliation: "3600s"
  timeout.reconciliation.jitter: "300s"
```

#### 3. Настройка вебхука в интерфейсе GitLab/Gitea
- **URL:** `https://argocd.internal.company/api/webhook`
- **Secret Token:** вставьте значение `$WEBHOOK_SECRET`
- **Trigger Events:** `Push events`, `Tag push events`
- **SSL verification:** включено (при использовании корпоративного внутреннего CA).

#### 4. Валидация
Сделайте коммит в репозиторий. Проверьте логи `argocd-server`:
```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server --tail=50 | grep -i webhook
# → time="2026-10-12T20:35:12Z" level=info msg="Received push event repo: https://git.internal.company/finance/billing.git"
# → time="2026-10-12T20:35:12Z" level=info msg="Requested refresh for app billing-production"
```

---

## Операции и команды управления синхронизацией

### Сводная таблица CLI-команд `argocd`

| Команда | Основные флаги | Назначение |
| :--- | :--- | :--- |
| `argocd app sync <app>` | `--prune`, `--dry-run`, `--force` | Запуск синхронизации манифестов с кластером. |
| | `--server-side-apply` | Использование Server-Side Apply для операции. |
| | `--strategy apply\|hook` | Стратегия применения (при `apply` хуки игнорируются). |
| | `--resource <g:k:n>` | Селективная синхронизация конкретного объекта. |
| | `--label <key=value>` | Селективная синхронизация по метке ресурса. |
| | `--timeout <sec>` | Ограничение времени ожидания завершения операции CLI. |
| | `--info <key=val>` | Добавление метаданных аудита (тикет, автор). |
| | `--async` | Асинхронный запуск без ожидания завершения. |
| `argocd app terminate-op <app>` | — | Принудительная остановка зависшей синхронизации или хука. |
| `argocd app diff <app>` | `--server-side-diff` | Вывод различий с учетом серверных admission-вебхуков. |
| | `--revision <sha>` | Сравнение Live-состояния с конкретным коммитом Git. |
| `argocd app wait <app>` | `--operation`, `--health` | Блокирующее ожидание успешного синка и перехода в Healthy. |
| | `--timeout <sec>` | Таймаут ожидания готовности ресурсов. |
| `argocd app get <app>` | `--refresh`, `--hard-refresh` | Запрос статуса (hard-refresh очищает кэш Git в repo-server). |
| | `--show-operation` | Детальный вывод выполняющейся в данный момент операции. |
| | `-o tree` | Отображение иерархического дерева ресурсов с волнами. |
| `argocd app rollback <app> [id]` | — | Откат к предыдущей успешной ревизии (только при manual sync!). |
| `argocd app actions list <app>` | `--kind <k>`, `--name <n>` | Просмотр доступных Resource Actions для ресурса. |
| `argocd app action run <app> <act>` | `--kind <k>`, `--name <n>`, `--namespace <ns>` | Выполнение кастомного действия над ресурсом. |
| `argocd proj windows list <proj>` | — | Просмотр статуса окон синхронизации проекта. |

### Примеры команд с ожидаемым выводом

```bash
# 1. Принудительный сброс кэша Git и проверка актуального состояния
argocd app get billing-production --hard-refresh
# → Name:               billing-production
# → Project:            production-project
# → Server:             https://kubernetes.default.svc
# → Namespace:          billing
# → URL:                https://argocd.internal.company/applications/billing-production
# → Repo:               https://git.internal.company/finance/billing.git
# → Target:             main
# → Sync Window:        Sync Allowed
# → Sync Status:        OutOfSync from main (a8f3b1c)
# → Health Status:      Healthy

# 2. Селективная синхронизация только ConfigMap без перезапуска приложения
argocd app sync billing-production --resource :ConfigMap:billing-config
# → GROUP  KIND       NAMESPACE  NAME            STATUS  HEALTH   HOOK  MESSAGE
# →        ConfigMap  billing    billing-config  Synced                 configmap/billing-config configured

# 3. Аварийная остановка зависшей синхронизации (зависший PreSync hook)
argocd app terminate-op billing-production
# → Operation terminated successfully

# 4. Просмотр дерева ресурсов с фазами и статусами
argocd app get billing-production -o tree
# → GROUP  KIND        NAMESPACE  NAME             STATUS  HEALTH
# →        Namespace              billing          Synced  Healthy (Wave -10)
# →        ConfigMap   billing    billing-config   Synced  Healthy (Wave -5)
# → apps   Deployment  billing    billing-service  Synced  Healthy (Wave 0)
# →        Service     billing    billing-service  Synced  Healthy (Wave 5)
```

---

## Валидация и проверка работоспособности

### 1. Комплексная проверка автоматической синхронизации и Self-Heal

```bash
# Проверка текущего статуса политики
argocd app get billing-production | grep "Sync Policy"
# → result: Sync Policy: Automated (Prune: true, SelfHeal: true)

# Симуляция изменения в кластере
kubectl annotate deployment billing-service -n billing manual-edit="true"
# → result: deployment.apps/billing-service annotated

# Ожидание реакции контроллера
argocd app get billing-production --refresh
# → result: Status: Synced, ручная аннотация удалена контроллером
```

### 2. Проверка механизма Pruning (удаление устаревших ресурсов)

```bash
# Проверка удаления ресурса при удалении из Git
# 1. Удалите файл из Git и запушьте коммит
git rm k8s/overlays/production/old-cronjob.yaml && git commit -m "remove cronjob" && git push
# → result: [main d4e5f6a] remove cronjob

# 2. Обновите состояние в Argo CD
argocd app get billing-production --refresh
# → result: Sync Status: Synced

# 3. Проверьте удаление объекта из кластера
kubectl get cronjob old-cronjob -n billing
# → result: Error from server (NotFound): cronjobs.batch "old-cronjob" not found
```

### 3. Проверка поведения политики повторов (Retry Backoff)

```bash
# Имитация ошибки применения (например, указание недопустимого селектора в манифесте)
# Просмотр логов контроллера на предмет повторных попыток
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=100 | grep -i retry
# → result: level=warning msg="Operation failed; retrying in 5s (retry 1/5)"
# → result: level=warning msg="Operation failed; retrying in 10s (retry 2/5)"
# → result: level=warning msg="Operation failed; retrying in 20s (retry 3/5)"
```

---

## Диагностика и устранение неполадок (Troubleshooting)

### Пошаговый алгоритм диагностики (SRE Runbook)

```text
 ┌───────────────────────────────────────────────────────────┐
 │ 1. Проверить общий статус: argocd app get <app>           │
 └─────────────────────────────┬─────────────────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
 ┌──────────────────────┐              ┌──────────────────────┐
 │ Статус: OutOfSync    │              │ Статус: Degraded     │
 └──────────┬───────────┘              └──────────┬───────────┘
            │                                     │
            ▼                                     ▼
 ┌─────────────────────────────┐        ┌─────────────────────────────┐
 │ 2. Проверить diff:          │        │ 2. Проверить k8s workloads: │
 │ argocd app diff <app>       │        │ kubectl describe pod /      │
 │ --server-side-diff          │        │ kubectl logs -n <ns>        │
 └──────────┬──────────────────┘        └─────────────────────────────┘
            │
            ▼
 ┌───────────────────────────────────────────────────────────┐
 │ 3. Проверить блокировку: SyncWindow / Skip-Reconcile?     │
 └─────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
 ┌───────────────────────────────────────────────────────────┐
 │ 4. Проверить логи контроллера:                            │
 │ kubectl logs -n argocd -l app.kubernetes.io/name=         │
 │ argocd-application-controller                             │
 └───────────────────────────────────────────────────────────┘
```

### Матрица типовых ошибок и решений

| Ошибка / Симптом | Первопричина | Инженерное решение (Sysadmin / SRE) |
| :--- | :--- | :--- |
| **`ComparisonError: Failed to load target state`** | Синтаксическая ошибка в YAML, падение `helm template` или недоступность репозитория Git. | 1. Проверить доступ: `argocd repo list`<br>2. Просмотреть логи repo-server: `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server`<br>3. Локально протестировать рендеринг: `helm template k8s/`. |
| **`SyncError: Too long: must have at most 262144 bytes`** | Манифест превысил лимит аннотации `last-applied-configuration` (256 KB) в Client-Side Apply. | Включить Server-Side Apply: добавить `ServerSideApply=true` в `spec.syncPolicy.syncOptions`. |
| **`OutOfSync` не исчезает после синка** | Мутирующий admission-вебхук кластера или оператор изменяет поля после применения манифеста. | 1. Выполнить `argocd app diff <app> --server-side-diff`<br>2. Определить менеджера поля через `metadata.managedFields`<br>3. Добавить исключение в `spec.ignoreDifferences` с `managedFieldsManagers`. |
| **Зависшая синхронизация (`Sync Progressing` часами)** | PreSync/PostSync Job ожидает завершения или упал без `activeDeadlineSeconds`. | 1. Остановить зависшую операцию: `argocd app terminate-op <app>`<br>2. Проверить логи Job: `kubectl logs -n <ns> job/<name>`<br>3. Обязательно добавить `activeDeadlineSeconds: 300` в спецификацию Job. |
| **`Sync operation blocked by sync window`** | Попадание во временной интервал блокирующего deny-окна проекта `AppProject`. | 1. Проверить окна: `argocd proj windows list <proj>`<br>2. Для аварийного деплоя использовать ручной синк (если `manualSync: true`) либо временно разрешить окно. |
| **`Shared resource conflict`** | Один и тот же ресурс управляется двумя разными объектами `Application`. | 1. Разделить владение ресурсами в манифестах Git<br>2. Включить `FailOnSharedResource=true` в `syncOptions` для защиты от перезаписи. |
| **`Rollback rejected: cannot rollback automated application`** | Попытка отката через `argocd app rollback` при включенном `automated: true`. | 1. Временно отключить автосинк (`argocd.argoproj.io/skip-reconcile="true"`)<br>2. Выполнить откат манифеста в Git (`git revert`) и запушить в ветку. |
| **Очередь контроллера перегружена (`reconcile timeout`)** | Нехватка воркеров обработки статуса при масштабировании на 500+ приложений. | Увеличить флаги в deployment `argocd-application-controller`:<br>`--status-processors=50`<br>`--operation-processors=25`. |
| **`Prune` не удаляет зависимые ресурсы** | У ресурсов заданы `ownerReferences`, управляемые другим контроллером. | Проверить `PrunePropagationPolicy=foreground` и каскадное удаление зависимостей в K8s GC. |

### Метрики Prometheus и алертинг для SRE

Контроллер экспортирует метрики на порту `8082` (`svc/argocd-metrics`).

#### Ключевые метрики

```promql
# 1. Количество приложений в рассинхронизации (OutOfSync)
argocd_app_sync_status{sync_status="OutOfSync"}

# 2. Количество приложений в аварийном статусе (Degraded)
argocd_app_health_status{health_status="Degraded"}

# 3. Количество сбоев операций синхронизации за последние 15 минут
increase(argocd_app_sync_total{phase="Failed"}[15m])

# 4. Приложения, заблокированные окнами синхронизации
argocd_app_sync_blocked == 1

# 5. Время выполнения цикла сверки (99-й перцентиль)
histogram_quantile(0.99, rate(argocd_app_reconcile_duration_seconds_bucket[5m]))
```

#### Пример PrometheusRule для Alertmanager

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: argocd-sync-alerts
  namespace: argocd
  labels:
    role: alert-rules
spec:
  groups:
  - name: argocd.sync.rules
    rules:
    - alert: ArgoCDApplicationDegraded
      expr: argocd_app_health_status{health_status="Degraded"} == 1
      for: 10m
      labels:
        severity: critical
      annotations:
        summary: "Приложение {{ $labels.name }} в статусе Degraded"
        description: "Приложение {{ $labels.name }} деградировало более 10 минут. Проверьте поды и события в namespace."

    - alert: ArgoCDSyncFailedRepeatedly
      expr: increase(argocd_app_sync_total{phase="Failed"}[15m]) > 3
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Повторные сбои синхронизации {{ $labels.name }}"
        description: "Зафиксировано более 3 неудачных попыток синхронизации за последние 15 минут."
```

---

## Лучшие практики

### Производительность и масштабируемость (bare-metal / on-premise)

1. **Используйте Server-Side Apply повсеместно:** задайте глобальный дефолт в `argocd-cm` (`server.side.apply.enabled: "true"`) либо явно в каждом `Application`. Это исключает разрастание аннотаций и конфликты `managedFields`.
2. **Откажитесь от частого Polling в пользу Webhooks:** выставьте интервал опроса `timeout.reconciliation: "3600s"` и настройте входящие вебхуки от внутреннего GitLab/Gitea.
3. **Оптимизируйте применение через `ApplyOutOfSyncOnly=true`:** не нагружайте API-сервер Kubernetes повторным применением сотен неизмененных ресурсов.
4. **Настройте шардирование контроллера (Controller Sharding):** при количестве приложений > 1000 переведите `argocd-application-controller` в `StatefulSet` с переменной окружения `ARGOCD_CONTROLLER_SHARDS` и запуском нескольких реплик.

### Безопасность и разграничение прав

1. **Никогда не используйте `allowEmpty: true` в Production:** пустой коммит или удаление каталога приведут к удалению всех ресурсов окружения.
2. **Изолируйте команды через `AppProject`:** настраивайте `sourceRepositories`, `destinations` и жесткие ограничения ролей Casbin RBAC для исключения кросс-проектных изменений.
3. **Защищайте критические периоды через `Sync Windows`:** блокируйте автоматическую раскатку в ночные часы и праздники, чтобы команда SRE не занималась аварийным восстановлением без дежурной смены.
4. **Используйте `FailOnSharedResource=true`:** предотвращает случайный захват чужих Deployment/Service объектами `Application` из соседних репозиториев.

### Надежность и непрерывность доставки

1. **Всегда задавайте `activeDeadlineSeconds` для хуков:** зависшая миграция базы данных или smoke-test заблокирует весь конвейер доставки до ручного вмешательства.
2. **Используйте `PruneLast=true`:** предотвращает ситуацию, когда старый Deployment уже удален, а новый не может запуститься из-за ошибки в образе.
3. **Настройте `BeforeHookCreation` для хуков-миграций:** гарантирует чистое пересоздание Job при повторном запуске упавшего синка.

### Очистка и безопасный вывод из эксплуатации (Cleanup & Revert)

1. **Каскадное удаление ресурсов через финализатор:**
   При необходимости удаления приложения вместе со всеми физическими ресурсами добавьте финализатор:
   ```yaml
   metadata:
     finalizers:
     - resources-finalizer.argocd.argoproj.io
   ```
2. **Безопасное удаление без удаления подов:**
   Если требуется удалить манифест `Application` из Argo CD, но **сохранить** работающие поды и базы данных в кластере:
   - Снимите финализатор перед удалением:
     ```bash
     kubectl patch application billing-production -n argocd --type json \
       -p='[{"op": "remove", "path": "/metadata/finalizers"}]'
     kubectl delete application billing-production -n argocd
     ```
   Все объекты в namespace `billing` останутся нетронутыми.

---

## Ограничения и граничные случаи (Edge Cases)

### Ограничения
1. **Внутренние лимиты контроллера:** при деплое приложений, содержащих более 1000 ресурсов в одном объекте `Application`, возможны задержки diff и падение repo-server по OOM. Рекомендуется декомпозиция на несколько приложений или `ApplicationSet`.
2. **Cross-namespace ограничения:** один объект `Application` может управлять объектами в разных пространствах имен, только если они явно разрешены в `spec.destinations` объекта `AppProject`.
3. **Ограничения `argocd app rollback`:** откат через CLI/UI невозможен при активном `automated: true` (вызывает моментальный повторный autosync).
4. **Selective Sync и история:** селективная синхронизация конкретного ресурса (`--resource` или `--label`) **не** фиксируется в истории приложения (`argocd app history`), и к ней невозможно применить откат.

### Граничные случаи (Edge Cases)
1. **Приоритет `Replace=true` над `ServerSideApply=true`:** если в `syncOptions` одновременно указаны `Replace=true` и `ServerSideApply=true`, опция `Replace` имеет безусловный приоритет: контроллер выполнит `kubectl replace`/`create`, проигнорировав SSA.
2. **Объединение правил (Union) `ignoreDifferences`:** правила, определенные локально в `spec.ignoreDifferences` объекта `Application`, **объединяются** с глобальными правилами из `argocd-cm`, а не переопределяют их.
3. **PreSync Hook и закрытие окна синхронизации:** если Job миграции БД запустился внутри разрешающего окна `Sync Window`, но продолжается дольше его завершения:
   - без `syncOverrun`: синк приостанавливается с ошибкой `Sync operation blocked by sync window`;
   - с `syncOverrun: true` (v3.5+): запущенный синк штатно завершается, последующие волны применяются.
4. **Конфликт HPA и `selfHeal` при отсутствии ignoreDifferences:** если в Git зафиксировано `replicas: 3`, а HPA масштабировал Deployment до 10, включенный `selfHeal` вернет количество реплик к 3 ровно через один интервал сверки (120–180с + 5с), вызвав деградацию сервиса под нагрузкой.
5. **Хуки и селективная синхронизация:** при запуске селективного синка (`argocd app sync --resource ...`) или при флаге `--strategy apply` хуки (`PreSync`, `PostSync`) **не выполняются**.
6. **ApplicationSet и метки ресурсов:** контроллер `ApplicationSet` по умолчанию **не** наследует свои метки на создаваемые ресурсы. Если вам требуется метка `argocd.argoproj.io/cluster`, задавайте ее явно в `template.metadata.labels`.

---

## Дополнительная информация

### Ключевые изменения в ветке v3.x

- **Server-Side Diff (v3.5+):** поддержка предсказания диффа с учетом K8s admission-вебхуков.
- **Свойство `syncOverrun` в Sync Windows (v3.5+):** предотвращение аварийного обрыва начавшихся синхронизаций при закрытии временного окна.
- **Skip Reconcile на секрете кластера (v3.4+):** одновременная заморозка сверки всех приложений кластера при регламентных работах.
- **Стабилизация PreDelete хуков (v3.3+):** корректный запуск регламентных задач очистки перед деинсталляцией приложения.
- **Явный флаг `spec.syncPolicy.automated.enabled` (v3.1+):** декларативное выключение автосинка без удаления секций `prune` и `selfHeal`.

### Стратегии прогрессивного развертывания (Argo Rollouts)

Для задач плавного переключения трафика без простоя Argo CD интегрируется с контроллером **Argo Rollouts**:
- **Canary:** постепенное направление части реального трафика (5% $\to$ 20% $\to$ 50% $\to$ 100%) на новую версию подов с анализом метрик Prometheus через `AnalysisTemplate`.
- **Blue-Green:** создание параллельного набора подов новой версии, проверка готовности и мгновенное переключение сервиса `activeService`.

### См. также

- **[Обзор Argo CD](./argocd_overview.md)** — архитектура контрольной плоскости и базовые концепции GitOps.
- **[Диагностика и мониторинг Argo CD](./argocd_troubleshooting_and_monitoring.md)** — глубокий анализ журналов, дашборды Grafana и профилирование pprof.
- **[Игнорирование различий](./synchronization/ignore_differences.md)** — синтаксис JQ, JSON Pointers и настройка `managedFieldsManagers`.
- **[Методы отслеживания ресурсов](./argocd_resource_tracking.md)** — детальный разбор режимов tracking-id, label и миграция между ними.
- **[Удаление и очистка ресурсов](./argocd_deletion_and_cleanup.md)** — Prune, Cascading Deletion, финализаторы и Garbage Collector.
- **[Интеграция Argo CD с Helm](./helm_integration.md)** — рендеринг чартов, sourceHydrator и работа с Multiple Sources.
- **[Сценарии: автоматическая синхронизация](./synchronization/scenarios/auto_sync.md)** — глубокая настройка автосинка.
- **[Сценарии: ручная синхронизация](./synchronization/scenarios/manual_sync.md)** — регламентные процедуры и выборочный деплой.
- **[Сценарии: Sync Waves и Hooks](./synchronization/scenarios/sync_waves_hooks.md)** — продвинутая оркестрация сложных зависимостей.
- **[Сценарии: окна синхронизации](./synchronization/scenarios/sync_windows.md)** — расписания и временные зоны деплоя.
- **[Сценарии: прогрессивная синхронизация](./synchronization/scenarios/progressive_sync.md)** — RollingSync в распределенных кластерах.

### Ссылки

- [Официальная документация: Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
- [Argo CD CLI: sync command](https://argo-cd.readthedocs.io/en/stable/user-guide/commands/argocd_app_sync/)
- [Sync Waves Official Guide](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/)
- [Resource Hooks Official Guide](https://argo-cd.readthedocs.io/en/stable/user-guide/resource_hooks/)
- [Diff Strategies and Server-Side Diff](https://argo-cd.readthedocs.io/en/stable/user-guide/diffing/)

---

## Вопросы для собеседования

### 1. В чем фундаментальная разница между Sync Waves и Resource Hooks?
**Ответ:** Sync Waves управляют очередностью применения **стандартных декларативных манифестов** приложения (Namespace, ConfigMap, Deployment, Service). Волна $N$ не запустится, пока все ресурсы волны $N-1$ не станут `Healthy`. Hooks — это **эфемерные разовые задачи (Jobs/Pods)**, запускаемые на определенных фазах жизненного цикла (PreSync для миграций БД, PostSync для smoke-тестов, SyncFail для нотификаций). Хуки не отслеживаются как постоянные ресурсы приложения после завершения и удаляются в соответствии с `hook-delete-policy`.

### 2. Что произойдет, если в фазе PreSync упадет Job миграции БД?
**Ответ:** Синхронизация немедленно прерывается со статусом `Failed`. Манифесты фазы Sync (Deployment, Service) к API-серверу **не применяются**, фаза PostSync не вызывается. Кластер остается в исходном рабочем состоянии на предыдущей версии. Если для Job не настроен `activeDeadlineSeconds`, он может зависнуть в состоянии выполнения до ручной остановки (`argocd app terminate-op`).

### 3. Почему одновременное включение `automated: true`, `prune: true` и `selfHeal: true` требует особых мер предосторожности?
**Ответ:** Данная связка превращает кластер в абсолютно зеркальное отражение Git-репозитория в режиме реального времени. Любая ошибка в Git (случайное удаление директории, некорректная очистка ветки, пустой файл манифеста) приведет к немедленному автоматическому удалению боевых ресурсов из кластера. Обязательные меры защиты: задание `allowEmpty: false`, настройка защиты веток в Git (Branch Protection, обязательный Code Review), использование финализаторов и `PruneLast=true`.

### 4. Почему `argocd app rollback` не работает для приложений с автосинком и как выполнить экстренный откат?
**Ответ:** При включенном `automated: true` команда `rollback` блокируется, так как контроллер сразу же зафиксирует расхождение с коммитом в отслеживаемой ветке Git и перетрет откат обратно. Для экстренного отката (Break-Glass) необходимо сначала заморозить сверку приложения через аннотацию `argocd.argoproj.io/skip-reconcile="true"`, выполнить откат рабочей нагрузки через `kubectl rollout undo`, после чего исправить манифест в Git и снять аннотацию.

### 5. Как Server-Side Apply разрешает конфликт владения между Argo CD и HPA?
**Ответ:** При использовании SSA Kubernetes API отслеживает владельца каждого конкретного поля объекта в `metadata.managedFields`. Argo CD с менеджером `fieldManager=argocd` владеет только теми полями, которые объявлены в Git. HPA через `kube-controller-manager` управляет полем `spec.replicas`. В сочетании с `RespectIgnoreDifferences=true` и исключением менеджера `kube-controller-manager` в секции `ignoreDifferences`, Argo CD не перезаписывает динамическое количество реплик, установленное HPA.
