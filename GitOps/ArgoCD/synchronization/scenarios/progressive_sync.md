# Argo CD — прогрессивная синхронизация (Progressive Syncs / Rolling Sync)

**Актуально для:** Argo CD v3.3+ (Progressive Syncs — Beta-фича с v3.3.0; фича существовала и в более ранних версиях в статусе alpha под названием «progressive rollouts»)

## Определения

**Progressive Syncs** — механизм контроллера ApplicationSet, управляющий порядком создания и обновления приложений, порождённых ApplicationSet. Приложения обновляются группами (шагами), а не все одновременно.

**RollingSync** — стратегия создания/обновления (`spec.strategy.type: RollingSync`): приложения группируются по меткам через `matchExpressions`, группы обновляются последовательно.

**AllAtOnce** — стратегия создания/обновления по умолчанию: все приложения обновляются одновременно (поведение ApplicationSet без Progressive Syncs).

**Шаг (step)** — группа приложений, отобранных одним набором `matchExpressions`. Переход к следующему шагу возможен только после того, как все приложения текущего шага достигнут состояния `Healthy`.

**maxUpdate** — лимит одновременно обновляемых приложений внутри шага: целое число или процент (например, `10%`). По умолчанию `100%` (все отобранные приложения сразу).

**Health Gating (барьер здоровья)** — правило перехода между шагами: шаг считается завершённым, когда каждое его приложение имеет статус здоровья `Healthy` и статус синхронизации `Synced` для целевой ревизии.

**deletionOrder** — стратегия удаления (`spec.strategy.deletionOrder`): `AllAtOnce` (по умолчанию) или `Reverse` — удаление приложений в обратном порядке шагов.

**Blast Radius (радиус поражения)** — масштаб потенциального сбоя. Progressive Syncs минимизируют его, обновляя сначала малую группу кластеров (Canary).

**Canary Deployment** — стратегия развертывания, при которой обновление сначала применяется к малой группе кластеров, и только после проверки здоровья распространяется на остальные.

## Базовые концепции

### Механика работы RollingSync

Контроллер ApplicationSet отслеживает состояние каждого порождённого приложения в `status.applicationStatus` ApplicationSet. Для каждого приложения ведётся конечный автомат:

1. **Waiting** — целевая ревизия или спецификация приложения изменились (или приложение newly selected шагом).
2. **Pending** — контроллер инициировал синхронизацию приложения.
3. **Progressing** — операция синхронизации завершилась (любым результатом: успехом, ошибкой или сбоем), либо приложение имеет ошибки, мешающие синхронизации. Приложения с ошибками тоже переводятся в `Progressing` — повторные попытки возлагаются на политику `retry` самого приложения, а не на ApplicationSet.
4. **Healthy** — приложение `Healthy` и `Synced` на целевой ревизии.

Шаг завершается только когда **все** его приложения в `Healthy`. Если хотя бы одно приложение «застряло» (например, в `Degraded`), раскатка останавливается на этом шаге — контроллер не переходит к следующему, пока проблема не будет устранена.

Дополнительные свойства RollingSync (из документации и исходников контроллера):

- **Триггер синхронизации** — контроллер запускает синхронизацию точно так же, как это делает UI или CLI: записывает поле `operation` в статус приложения. Поэтому RollingSync **учитывает Sync Windows** так же, как если бы пользователь нажал «Sync» в UI, и **сохраняет политику `retry`** приложения.
- **Автосинк принудительно отключается** у всех порождённых приложений; если в шаблоне задан `syncPolicy.automated`, в логах контроллера появляются предупреждения.
- **Захват внешних изменений** — RollingSync реагирует на статус `OutOfSync` управляемых приложений, поэтому изменения, внесённые вне ApplicationSet (например, правка ресурса в кластере), тоже улавливаются.
- **Приложения вне шагов** — приложение, не отобранное ни одним `matchExpressions`, получает шаг `-1` и **исключается** из раскатки; его нужно синхронизировать вручную (CLI/UI).
- **Поддерживаемые ресурсы** — Deployments, DaemonSets, StatefulSets и Argo Rollouts: приложение переходит в `Progressing`, пока поды развёртываются. Поддерживается любой ресурс с health check, способным сообщать `Progressing`.
- **Hooks** — Argo CD Resource Hooks поддерживаются и рекомендуются для сценариев, где Argo Rollouts не подходит (например, smoke-тест после изменения DaemonSet).

### Включение и настройка

Progressive Syncs — Beta-фича (с v3.3.0), **не включена по умолчанию**. Активируется одним из способов:

1. Флаг `--enable-progressive-syncs` в аргументах контроллера ApplicationSet.
2. Переменная `ARGOCD_APPLICATIONSET_CONTROLLER_ENABLE_PROGRESSIVE_SYNCS=true` в окружении контроллера ApplicationSet.
3. Параметр в ConfigMap `argocd-cmd-params-cm`:

```yaml
data:
  applicationsetcontroller.enable.progressive.syncs: "true"
```

### Стратегии создания и удаления

ApplicationSet различает две независимые стратегии:

- **Создание/обновление** (`spec.strategy.type`): `AllAtOnce` (по умолчанию) или `RollingSync`.
- **Удаление** (`spec.strategy.deletionOrder`): `AllAtOnce` (по умолчанию) или `Reverse`.

`deletionOrder: Reverse` удаляет приложения в обратном порядке шагов — приложения поздних шагов удаляются раньше ранних. Полезно при выводе из эксплуатации зависимых сервисов (сначала фронтенд, потом бэкенд). Требования: `type: RollingSync` и заданные `rollingSync.steps`. Контроллер гарантирует наличие finalizer на ApplicationSet и удерживает его, пока все дочерние приложения не будут удалены, — ApplicationSet не исчезнет раньше своих приложений.

```yaml
spec:
  strategy:
    type: RollingSync
    deletionOrder: Reverse # удаление в обратном порядке шагов
    rollingSync:
      steps:
        - matchExpressions:
            - key: envLabel
              operator: In
              values: [env-dev] # Шаг 1: создаётся первым, удаляется последним
        - matchExpressions:
            - key: envLabel
              operator: In
              values: [env-prod] # Шаг 2: создаётся вторым, удаляется первым
```

### Семантика matchExpressions

- Приложение отбирается шагом, когда **все** `matchExpressions` шага истинны (AND между выражениями).
- Внутри одного выражения `In`/`NotIn` истинны при совпадении **хотя бы с одним** значением (OR внутри `values`).
- Поддерживаются **только операторы `In` и `NotIn`** — другие операторы (например, `Exists`) отвергаются валидацией, и приложение не попадает в шаг.
- При пересечении `In` и `NotIn` **приоритет у `NotIn`**.
- Пустой шаг (не отобрало ни одного приложения) фиксируется как проблема конфигурации в условиях ApplicationSet.

### maxUpdate

- Целое число или процентная строка (`10%`); не указан — `100%` (все отобранные приложения одновременно).
- Проценты **округляются вниз**, но для значений `>0%` результат не меньше 1 приложения.
- `maxUpdate: 0` — ни одно приложение шага не синхронизируется (шаг блокируется).
- Невалидное значение — предупреждение в логах, логика `maxUpdate` для шага игнорируется (обновляются все отобранные приложения).

## Взаимодействие с другими механизмами

### Progressive Sync и Sync Windows

Синхронизация инициируется через поле `operation` — так же, как при нажатии «Sync» в UI. Поэтому окна синхронизации ([Sync Windows](./sync_windows.md)) проверяются для каждого приложения индивидуально, с учётом AppProject приложения.

**Следствие:** приложение, попавшее в Deny-окно, не начнёт синхронизацию, а шаг не завершится, пока оно не станет `Healthy` — раскатка фактически приостанавливается на таком приложении. Планируйте раскатку внутри Allow-окон.

### Progressive Sync и Manual Sync

Ручная синхронизация ([Manual Sync](./manual_sync.md)) приложения возможна в любой момент — контроллер зафиксирует операцию и продолжит отслеживать приложение по своему конечному автомату. Но приложение синхронизируется вне очереди, что нарушает замысел поэтапности. Рекомендуется использовать только для экстренных случаев.

### Progressive Sync и Hooks/Waves

Прогрессивная синхронизация работает на уровне приложений, а [Sync Waves и Hooks](./sync_waves_hooks.md) — на уровне ресурсов внутри приложения. Механизмы дополняют друг друга:

- **Волны:** управляют порядком ресурсов *внутри* одного приложения (Namespace → Deployment → Service → Ingress).
- **Прогрессивная синхронизация:** управляет порядком *между* приложениями (Canary → Staging → Production).

**Пример:** при переходе от Canary к Staging контроллер ApplicationSet дождётся `Healthy` для всех приложений Canary, затем запустит синхронизацию Staging. Внутри каждого приложения ресурсы применяются в порядке Sync Waves.

### Progressive Sync и Auto Sync

`syncPolicy.automated` в шаблоне приложения **игнорируется**: RollingSync принудительно отключает autosync у порождённых приложений (с предупреждениями в логах). Автоматическая синхронизация ([Auto Sync](./auto_sync.md)) управляется контроллером ApplicationSet. Если приложению нужен autosync вне контекста Progressive Syncs — используйте отдельный ApplicationSet без `RollingSync`.

### Progressive Sync и SelfHeal/Prune

`selfHeal` и `prune` являются частью `syncPolicy.automated`, поэтому при RollingSync они тоже отключены у порождённых приложений. Контроллер ApplicationSet управляет процессом синхронизации целиком. Если нужны `selfHeal`/`prune` — отдельный ApplicationSet без стратегии `RollingSync`.

### Progressive Sync и Ignore Differences

`spec.ignoreApplicationDifferences` на ApplicationSet (и `ignoreDifferences` в шаблоне) влияет на вычисление `OutOfSync` и на сравнение спецификаций — то есть на то, какие изменения переводят приложение в `Waiting`. На health-статус и гейтинг `Healthy` игнорирование различий не влияет.

### Progressive Sync и Retry

При запуске синхронизации применяется `syncPolicy.retry` приложения: неудачная операция повторяется по политике приложения, а не по логике ApplicationSet («повторять неудачные синхронизации — задача retry приложения, а не appset»).

## Практические сценарии

### Сценарий 1: Глобальный Canary-пайплайн

Развертывание сначала в один контрольный кластер, затем в Staging, и только потом поэтапно в Production.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: global-app-rollout
spec:
  generators:
  - clusters: {} # Использовать все подключенные кластеры
  strategy:
    type: RollingSync
    deletionOrder: Reverse
    rollingSync:
      steps:
        # Шаг 1: Один кластер для проверки (Canary)
        - matchExpressions:
            - key: environment
              operator: In
              values: [canary]
          maxUpdate: 1
        # Шаг 2: Все тестовые окружения (параллельно, maxUpdate не указан = 100%)
        - matchExpressions:
            - key: environment
              operator: In
              values: [staging]
        # Шаг 3: Весь Production (по 10% за раз, округление вниз, но не менее 1)
        - matchExpressions:
            - key: environment
              operator: In
              values: [production]
          maxUpdate: 10%
  template:
    metadata:
      name: '{{name}}-service'
      labels:
        environment: '{{name}}' # Метка, по которой отбираются шаги
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

**Важно:** приложения, не попавшие ни в один шаг (кластеры без подходящей метки `environment`), исключаются из раскатки и требуют ручной синхронизации.

### Сценарий 2: Мультирегиональная раскатка

Последовательное обновление датацентров в разных регионах для минимизации рисков глобального простоя.

```yaml
rollingSync:
  steps:
    - matchExpressions:
        - key: region
          operator: In
          values: [eu-central-1, eu-west-1]
      maxUpdate: 1
    - matchExpressions:
        - key: region
          operator: In
          values: [us-east-1, us-west-2]
      maxUpdate: 1
```

### Сценарий 3: Progressive Sync с List Generator

Использование статического списка кластеров для точного контроля порядка раскатки.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: list-generator-rollout
  namespace: argocd
spec:
  generators:
  - list:
      elements:
      - cluster: canary-1
        url: https://canary-1.example.com
        environment: canary
      - cluster: staging-1
        url: https://staging-1.example.com
        environment: staging
      - cluster: staging-2
        url: https://staging-2.example.com
        environment: staging
      - cluster: prod-1
        url: https://prod-1.example.com
        environment: production
      - cluster: prod-2
        url: https://prod-2.example.com
        environment: production
  strategy:
    type: RollingSync
    deletionOrder: Reverse
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
            values: [staging]
        maxUpdate: 2
      - matchExpressions:
          - key: environment
            operator: In
            values: [production]
        maxUpdate: 1
  template:
    metadata:
      name: '{{cluster}}-myapp'
      labels:
        environment: '{{environment}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/my-org/manifests.git
        targetRevision: HEAD
        path: app
      destination:
        server: '{{url}}'
        namespace: production
```

**Преимущества List Generator:**
- Полный контроль над порядком кластеров
- Возможность точной настройки `maxUpdate` для каждого шага
- Простота отладки и понимания

### Сценарий 4: Progressive Sync с Git Generator

Динамическое добавление кластеров при появлении новых папок в Git-репозитории.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: git-generator-rollout
  namespace: argocd
spec:
  generators:
  - git:
      repoURL: https://github.com/my-org/clusters.git
      revision: HEAD
      directories:
      - path: clusters/*
  strategy:
    type: RollingSync
    deletionOrder: Reverse
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
            values: [staging]
        maxUpdate: 1
      - matchExpressions:
          - key: environment
            operator: In
            values: [production]
        maxUpdate: 10%
  template:
    metadata:
      name: '{{path.basename}}-app'
      labels:
        environment: '{{path.basename}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/my-org/manifests.git
        targetRevision: HEAD
        path: app/{{path.basename}}
      destination:
        server: '{{url}}'
        namespace: production
```

**Преимущества Git Generator:**
- Динамическое добавление кластеров без изменения ApplicationSet
- Автоматическое удаление приложений при удалении папок из Git
- Единый источник правды (Git)

### Сценарий 5: Progressive Sync с Matrix Generator

Комбинирование двух генераторов для создания произвольных комбинаций «Приложение × Кластер».

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: matrix-generator-rollout
  namespace: argocd
spec:
  generators:
  - matrix:
      generators:
      - git:
          repoURL: https://github.com/my-org/apps.git
          revision: HEAD
          directories:
          - path: apps/*
      - list:
          elements:
          - cluster: prod-1
            url: https://prod-1.example.com
            environment: production
          - cluster: prod-2
            url: https://prod-2.example.com
            environment: production
  strategy:
    type: RollingSync
    deletionOrder: Reverse
    rollingSync:
      steps:
      - matchExpressions:
          - key: environment
            operator: In
            values: [production]
        maxUpdate: 1
  template:
    metadata:
      name: '{{path.basename}}-{{cluster}}'
      labels:
        environment: '{{environment}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/my-org/apps.git
        targetRevision: HEAD
        path: '{{path}}'
      destination:
        server: '{{url}}'
        namespace: production
```

**Преимущества Matrix Generator:**
- Создание комбинаций «N приложений × M кластеров»
- Динамическое добавление как приложений, так и кластеров
- Гибкость в настройке

### Сценарий 6: Health Gating с кастомными проверками

Если стандартных Health Checks Kubernetes недостаточно, используйте кастомные проверки в `argocd-cm`. Реальный пример из документации — health check для `cert-manager.io/Certificate` по условию `Ready`:

```yaml
data:
  resource.customizations.health.cert-manager.io_Certificate: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.conditions ~= nil then
        for i, condition in ipairs(obj.status.conditions) do
          if condition.type == "Ready" and condition.status == "False" then
            hs.status = "Degraded"
            hs.message = condition.message
            return hs
          end
          if condition.type == "Ready" and condition.status == "True" then
            hs.status = "Healthy"
            hs.message = condition.message
            return hs
          end
        end
      end
    end

    hs.status = "Progressing"
    hs.message = "Waiting for certificate"
    return hs
```

**Важно:** кастомные Health Checks напрямую влияют на прогресс — если хотя бы одно приложение переходит в `Degraded` из-за кастомной проверки, шаг никогда не завершится, и раскатка остановится.

Синтаксис ключа: `resource.customizations.health.<group>_<kind>`; для ресурсов без API-группы (например, `PersistentVolumeClaim`) префикс `<group>_` опускается. Подробнее — в [документации по Health Assessment](https://argo-cd.readthedocs.io/en/stable/operator-manual/health/).

### Сценарий 7: Реакция на деградацию во время раскатки

**Симптомы:** приложение в `Degraded`, раскатка остановлена на шаге, следующие шаги не выполняются.

**Диагностика:**

```bash
# Состояние раскатки: статусы приложений по шагам
kubectl get applicationset <name> -n argocd -o json \
  | jq -r '.status.applicationStatus[] | "\(.application) \(.status) step=\(.step) \(.message)"'

# Условия ApplicationSet (RolloutProgressing, проблемы конфигурации)
kubectl get applicationset <name> -n argocd -o jsonpath='{.status.conditions[*].type}{"\n"}'

# Состояние конкретного приложения
argocd app get <app-name>

# Логи контроллера ApplicationSet
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller | grep -i "degraded\|progressive"
```

**Исправление:**

```bash
# Исправить проблему в Git (рекомендуется) — раскатка продолжится автоматически
git commit -m "fix: correct resource configuration"
git push

# Или откатить приложение к предыдущей ревизии по History ID
argocd app history <app-name>            # найти ID
argocd app rollback <app-name> <ID>      # ID опущен — откат к предыдущей версии
```

**Принудительное продолжение (экстренное):**

```bash
# Принудительная синхронизация конкретного приложения (--force = повторное применение всех ресурсов)
argocd app sync <app-name> --force
```

**Важно:** принудительное продолжение выводит приложение из очереди раскатки и может привести к нестабильности. Используйте только в экстренных случаях, после исправления вернитесь к стандартному процессу.

### Сценарий 8: Вывод из эксплуатации в обратном порядке

Удаление приложений в порядке, обратном раскатке — сначала зависимые сервисы, потом те, от кого они зависят.

```yaml
strategy:
  type: RollingSync
  deletionOrder: Reverse
  rollingSync:
    steps:
      - matchExpressions:
          - key: tier
            operator: In
            values: [backend] # Удаляется последним
      - matchExpressions:
          - key: tier
            operator: In
            values: [frontend] # Удаляется первым
```

**Поведение:** контроллер удаляет приложения шаг за шагом в обратном порядке (опрос каждые ~10 секунд), удерживает finalizer ApplicationSet до полного удаления всех приложений. При удалении самого ApplicationSet с `deletionOrder: AllAtOnce` дочерние приложения удаляются одновременно (через garbage collection по ownerReference).

## Технический справочник

### Параметры RollingSync

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `spec.strategy.type` | String | Стратегия создания/обновления: `AllAtOnce` (по умолчанию) или `RollingSync`. |
| `spec.strategy.deletionOrder` | String | Стратегия удаления: `AllAtOnce` (по умолчанию) или `Reverse` (только с `RollingSync` и заданными `steps`). |
| `rollingSync.steps[].matchExpressions` | List | Селекторы меток порождённых приложений. Только операторы `In`/`NotIn`; AND между выражениями, OR внутри `values`, приоритет `NotIn`. |
| `rollingSync.steps[].maxUpdate` | Int/String | Лимит одновременно обновляемых приложений в шаге: число или процент. По умолчанию `100%`; проценты округляются вниз (минимум 1 при `>0%`); `0` блокирует шаг; невалидное значение игнорируется с предупреждением. |

### Параметры контроллера ApplicationSet

| Флаг / env / параметр в `argocd-cmd-params-cm` | Описание | По умолчанию |
| :--- | :--- | :--- |
| `--enable-progressive-syncs` / `ARGOCD_APPLICATIONSET_CONTROLLER_ENABLE_PROGRESSIVE_SYNCS` / `applicationsetcontroller.enable.progressive.syncs` | Включить Progressive Syncs | `false` |
| `--refresh-grace-period-seconds` / `ARGOCD_APPLICATIONSET_CONTROLLER_REFRESH_GRACE_PERIOD_SECONDS` | Минимальный grace-период перед тем, как прогрессивная синхронизация начнёт обновлять устаревшие приложения | `30` |
| `--applicationset-namespaces` / `ARGOCD_APPLICATIONSET_CONTROLLER_NAMESPACES` | Пространства имён для управления ApplicationSet | все |
| `--concurrent-reconciliations` / `ARGOCD_APPLICATIONSET_CONTROLLER_CONCURRENT_RECONCILIATIONS` | Макс. одновременных reconciliations | `10` |
| `--concurrent-application-updates` / `ARGOCD_APPLICATIONSET_CONTROLLER_CONCURRENT_APPLICATION_UPDATES` | Одновременных create/update/delete приложений на один reconcile | `1` |
| `--cache-sync-period` / `ARGOCD_APPLICATIONSET_CONTROLLER_CACHE_SYNC_PERIOD` | Период принудительной синхронизации кеша с API-сервером | `10h` |
| `--metrics-applicationset-labels` | Список меток приложений, добавляемых в метрику `argocd_applicationset_labels` | пусто |

### Статус ApplicationSet

Контроллер ведёт статус раскатки в `status.applicationStatus` — запись на каждое приложение:

| Поле | Описание |
| :--- | :--- |
| `application` | Имя порождённого приложения |
| `status` | Состояние в конечном автомате: `Waiting`, `Pending`, `Progressing`, `Healthy` |
| `step` | Номер шага (1-based); `-1` — приложение не отобрано ни одним шагом |
| `targetRevisions` | Целевые ревизии, для которых ожидается синхронизация |
| `lastTransitionTime` | Время последнего перехода состояния |
| `message` | Человекочитаемое описание последнего перехода |

Условия (`status.conditions`) сообщают о ходе раскатки (`RolloutProgressing`) и о проблемах конфигурации (невалидный `maxUpdate`, пустые шаги).

## Диагностика и мониторинг

### Просмотр состояния ApplicationSet

```bash
# Список ApplicationSet
kubectl get applicationset -n argocd

# Полное состояние (стратегия, шаги, статусы приложений, условия)
kubectl get applicationset <name> -n argocd -o yaml

# Приложения, созданные ApplicationSet — через ownerReference
# (ApplicationSet не добавляет порождённым приложениям собственных меток;
#  метки приложения задаются только в template.metadata.labels)
kubectl get applications -n argocd -o json \
  | jq -r '.items[] | select(.metadata.ownerReferences[]?.kind == "ApplicationSet" and .metadata.ownerReferences[]?.name == "<appset-name>") | .metadata.name'

# То же через метку из шаблона, если она задана (например, environment)
argocd app list -l environment=canary

# Состояние конкретного приложения
argocd app get <app-name>
```

### Просмотр логов контроллера

```bash
# Логи контроллера ApplicationSet
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller -f

# Логи контроллера приложений (ошибки синхронизации)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep -i "error\|degraded"
```

### Мониторинг через Prometheus

| Метрика | Описание |
| :--- | :--- |
| `argocd_app_info` | Информация о приложении; labels `sync_status`, `health_status`. |
| `argocd_app_sync_total` | Общее количество синхронизаций (label `phase`). |
| `argocd_app_reconcile` | Гистограмма длительности сверки, секунды. |
| `argocd_applicationset_labels` | Метки ApplicationSet (раскрываются флагом `--metrics-applicationset-labels`). |

**Пример PromQL-запроса для поиска деградированных приложений:**

```promql
argocd_app_info{health_status="Degraded"}
argocd_app_sync_total{phase="Error"} > 0
```

### Пошаговая диагностика

1. **Проверьте ApplicationSet:** `kubectl get applicationset <name> -n argocd -o yaml` — стратегия `RollingSync`, шаги, условия (`RolloutProgressing`, ошибки конфигурации).
2. **Просмотрите статусы приложений:** `status.applicationStatus` — найдите приложения, не достигшие `Healthy`, и их `message`.
3. **Проверьте здоровье:** `argocd app get <app-name>` — статус `Degraded`, `Progressing` или ошибки ресурсов.
4. **Проверьте окна синхронизации:** если приложение `Pending` и не синхронизируется — возможно, оно попало в Deny-окно своего AppProject.
5. **Просмотрите логи:** контроллер ApplicationSet (прогресс раскатки) и контроллер приложений (ошибки синхронизации).
6. **Исправьте проблему:** исправьте конфигурацию в Git или откатите приложение (`argocd app rollback`); раскатка продолжится автоматически.

## Лучшие практики

### Настройка для Production

1. **Используйте `maxUpdate: 1` для первого шага (Canary):** обновляйте только один кластер для проверки.
2. **Используйте `maxUpdate: 10%` для Production:** не обновляйте более 10% кластеров за раз.
3. **Настройте Health Checks:** кастомные проверки должны корректно отражать состояние приложения — от них зависит гейтинг.
4. **Комбинируйте с Sync Windows:** настройте Allow-окна для рабочих часов, чтобы раскатка проходила в предсказуемое время.
5. **Используйте `deletionOrder: Reverse`:** при выводе из эксплуатации зависимости удалялись в правильном порядке.
6. **Настройте `syncPolicy.retry`:** неудачные операции повторяются по политике приложения, не останавливая раскатку на временных сбоях.

### Безопасность

- **Ограничьте `maxUpdate`:** не используйте `100%` для Production — это может привести к глобальному простою.
- **Настройте RBAC:** ограничьте доступ к ApplicationSet только авторизованным пользователям.
- **Мониторинг:** настройте алерты на основе Prometheus-метрик для отслеживания деградации.

### Масштабирование

- **Для больших инфраструктур:** используйте Git Generator или Matrix Generator для динамического управления кластерами.
- **Для малых инфраструктур:** используйте List Generator для точного контроля.
- **Разделяйте ApplicationSet:** не используйте один ApplicationSet для всех приложений — разделите по функциональным группам.

## Ограничения и edge cases

### Ограничения

1. **Прогрессивная синхронизация работает только с ApplicationSet:** невозможно использовать с отдельными Application.
2. **`syncPolicy.automated` игнорируется:** autosync (включая `selfHeal` и `prune`) отключается у порождённых приложений.
3. **Зависимость от метаданных:** раскатка критически зависит от правильной разметки (labels) приложений, заданной в `template.metadata.labels`.
4. **Только `In`/`NotIn`:** другие операторы в `matchExpressions` шага отвергаются валидацией.
5. **Не интегрируется с Rollout-контроллерами:** механизм работает только со здоровьем управляемых приложений, а не с нативным ReplicaSet controller или Argo Rollouts (хотя ресурсы Argo Rollouts поддерживаются через их health check).

### Edge Cases

1. **Приложение вне шагов (step `-1`):** исключено из раскатки, требует ручной синхронизации. Проверяйте, что все целевые приложения отобраны хотя бы одним шагом.
2. **Приложение в Deny-окне:** синхронизация не начнётся, шаг не завершится — раскатка приостанавливается на таком приложении до открытия Allow-окна.
3. **Нет правил Allow:** если в проекте нет Allow-окон, progressive sync работает всегда (при условии отсутствия Deny).
4. **Ручной sync вне очереди:** приложение синхронизируется раньше срока; контроллер зафиксирует операцию, но порядок раскатки нарушается.
5. **Удаление ApplicationSet во время прогресса:** при `deletionOrder: Reverse` дочерние приложения удаляются в обратном порядке шагов, finalizer удерживается до завершения; при `AllAtOnce` — одновременно через GC.
6. **Смена стратегии с `RollingSync` на `AllAtOnce`:** контроллер очищает `status.applicationStatus` раскатки.
7. **Невалидный `maxUpdate`:** шаг обновляется без ограничения параллелизма, в логах — предупреждение, в условиях ApplicationSet — ошибка конфигурации.
8. **Конфликт общих ресурсов:** если один ресурс управляется несколькими приложениями, используйте Application sync option `FailOnSharedResource=true` (описана в [sync-options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)); отдельного поля ApplicationSet для этого нет.
9. **Grace-период обновления:** изменённые приложения не начинают обновление раньше, чем истечёт `--refresh-grace-period-seconds` (30 с по умолчанию) — защита от слишком частых обновлений при бурных изменениях.

## Дополнительная информация

### См. также
- **[Синхронизация Argo CD: Обзор](../../synchronization.md)** — общие принципы.
- **[Автоматическая синхронизация](./auto_sync.md)** — стандартный режим деплоя.
- **[Ручная синхронизация](./manual_sync.md)** — селективный деплой и аудит изменений.
- **[Волны и хуки](./sync_waves_hooks.md)** — управление порядком ресурсов внутри одного приложения.
- **[Окна синхронизации](./sync_windows.md)** — политики запрета деплоя в праздники и выходные.
- **[Игнорирование различий](../ignore_differences.md)** — настройка jqPath и managedFieldsManagers.
- **[ApplicationSet](../../argocd_applicationsets.md)** — генераторы и шаблоны.
- [Argo CD Progressive Syncs Docs](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Progressive-Syncs/)
- [Argo CD ApplicationSet Generators](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Generators/)
- [Argo CD Health Assessment](https://argo-cd.readthedocs.io/en/stable/operator-manual/health/)
