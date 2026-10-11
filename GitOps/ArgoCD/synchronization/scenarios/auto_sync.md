# Argo CD — автоматическая синхронизация

> **Актуально для:** Argo CD v3.4.x

Автоматическая синхронизация (Automated Sync Policy) позволяет контроллеру Argo CD применять изменения из Git к кластеру без ручного вмешательства и без прямого доступа CI/CD-пайплайнов к API-серверу Argo CD — достаточно коммита в отслеживаемый репозиторий. Производительность сверки для больших приложений повышают опция `ApplyOutOfSyncOnly=true` и **Server-Side Apply (SSA)**. Отдельно от SSA доступна стратегия диффа **Server-Side Diff** (стабильна с v3.1.0) — она выполняет SSA в dryrun-режиме для предсказания результата с участием admission-вебхуков; включается явно (см. «Diff-стратегии»).

## Предварительные требования

Перед включением автоматической синхронизации необходимо убедить в следующем:

1. **Версия Argo CD:** базовый механизм auto-sync работает с ранних версий; флаг `spec.syncPolicy.automated.enabled` — с v3.1.0; PreDelete-хуки — с v3.3.0; Progressive Syncs — Beta с v3.3.0. Рекомендуется v3.4.x.
2. **Проект (AppProject):** Приложение должно быть привязано к проекту с разрешенными целевыми кластерами и namespaces.
3. **Источник кода:** Репозиторий доступен для Argo CD (настроены credentials или публичный доступ).
4. **Понимание рисков:** Автоматическая синхронизация с `prune: true` и `selfHeal: true` может удалить ресурсы или откатить ручные изменения. Убедитесь, что политики соответствуют требованиям среды.
5. **Настроенная синхронизация:** Приложение уже успешно синхронизируется вручную (или хотя бы один раз через UI/CLI).

## Определения

**Автоматическая синхронизация (Automated Sync)** — режим работы Argo CD, при котором контроллер автоматически применяет изменения из Git к кластеру при обнаружении расхождений (`OutOfSync`). Это исключает ручное вмешательство из цикла доставки.

**Self-Heal (Автоматическое исправление)** — механизм, который обнаруживает ручные изменения в кластере (Manual Drift) и автоматически возвращает ресурсы к эталонному состоянию, описанному в Git. Дрейф фиксируется на этапе сверки; при включенном `selfHeal` синхронизация запускается через self-heal timeout (по умолчанию 5 секунд).

**Pruning (Удаление лишнего)** — процесс автоматического удаления ресурсов из Kubernetes, если их описание удалено из Git-репозитория. Гарантирует, что кластер не содержит "мусорных" объектов. Удаление происходит в порядке, обратном зависимостям (сначала dependent-ресурсы).

**Sync Options (Опции синхронизации)** — флаги в `spec.syncPolicy.syncOptions` манифеста `Application`, управляющие тонким поведением применения изменений (пропуск валидации, создание Namespace и т.д.). Не путать с полями `spec.syncPolicy.automated` (`prune`, `selfHeal`, `allowEmpty`, `enabled`) — это разные секции API.

**Retry Policy (Политика повторных попыток)** — конфигурация `spec.syncPolicy.retry`, определяющая количество и интервалы повторных попыток синхронизации при временных сбоях (сетевые ошибки, недоступность API, таймауты).

## Базовые концепции

### Почему автоматизация необходима

1.  **Борьба с дрейфом (Drift):** В динамических средах ручные правки (`kubectl edit`) неизбежны, но опасны. `Self-Heal` гарантирует, что инфраструктура всегда соответствует коду.
2.  **Масштабируемость:** Один оператор может управлять сотнями приложений, так как Argo CD берет на себя рутину по нажатию кнопок "Sync".
3.  **Скорость доставки:** Время от коммита до деплоя в Staging сокращается до одного интервала сверки (по умолчанию 120s + jitter до 60s).
4.  **Консистентность:** Гарантирует, что все кластеры (dev/staging/prod) находятся в одинаковом состоянии, описанном в Git.
5.  **Аудит:** Каждая синхронизация логируется, что позволяет отслеживать, кто и когда применил изменения.

### Механика выполнения Sync

1.  **Детекция:** Контроллер сравнивает `Live State` (текущее состояние в кластере) и `Desired State` (описание в Git). Стратегия diff по умолчанию — **Legacy** (3-way diff с аннотацией `last-applied-configuration`).
2.  **Оценка:** Если статус `OutOfSync`, проверяется наличие флага `syncPolicy.automated` (с `enabled` не равным `false`).
3.  **Порядок:** Argo CD выстраивает дерево ресурсов согласно [Sync Waves и Hooks](./sync_waves_hooks.md).
4.  **Применение:** По умолчанию выполняется клиентский `kubectl apply`; при `ServerSideApply=true` — `kubectl apply --server-side --force-conflicts`.
5.  **Валидация:** После применения проверяется работоспособность (health) ресурсов (Health Checks).
6.  **Повторные попытки:** При неудаче применяется политика retry (если настроена).

### Семантика автоматической синхронизации

- Автоматическая синхронизация запускается **только** для приложений в статусе `OutOfSync`. Приложения в статусе `Synced` или с ошибкой не синхронизируются автоматически.
- Выполняется не более одной синхронизации на уникальную комбинацию commit SHA1 и параметров. Если последняя успешная синхронизация уже была против того же SHA, повторная не запускается — кроме случая `selfHeal: true`.
- Если предыдущая попытка синхронизации против того же commit-SHA завершилась неудачей, автоматический повтор **не** выполняется — нужен retry или ручной запуск.
- **Rollback невозможен** для приложения с включенным automated sync (`argocd app rollback` отвергается).
- Для multi-source приложений отключение `selfHeal` не гарантирует сохранения ручных изменений: изменение в одном из источников может вновь запустить autosync.

### Компоненты автоматической синхронизации

- **`automated`** — основной флаг, включающий автоматическую синхронизацию. Содержит подпараметры `prune`, `selfHeal`, `allowEmpty` и `enabled`.
- **`enabled`** — явное включение/выключение (v3.1.0+). По умолчанию (при `automated: {}` или `enabled: null`) автосинк включен; при `enabled: false` контроллер пропускает автосинк, даже если заданы `prune`, `selfHeal` и `allowEmpty`.
- **`prune`** — разрешает удаление ресурсов, отсутствующих в Git. По умолчанию `false` (защита): без этого флага Argo CD только добавляет/обновляет, но не удаляет.
- **`selfHeal`** — разрешает автоматическое исправление ручных правок в кластере. По умолчанию `false`.
- **`allowEmpty`** — разрешает синхронизацию, если Git-репозиторий пуст (все манифесты удалены). По умолчанию `false` — синхронизация с пустым источником запрещена.
- **`retry`** — конфигурация повторных попыток при временных сбоях (см. «Настройка логики Retry»).

### Взаимодействие с другими механизмами

- **Sync Windows:** Если настроены [Sync Windows](./sync_windows.md), автоматическая синхронизация блокируется в запрещенные интервалы, даже если в Git появились изменения. Дрейф при этом обнаруживается (приложение остается `OutOfSync`), а коррекция откладывается до открытия окна. Для мониторинга блокировки есть метрика `argocd_app_sync_blocked`.
- **Sync Waves:** Автоматическая синхронизация учитывает [волны и хуки](./sync_waves_hooks.md) — ресурсы применяются в порядке, определенном аннотациями `argocd.argoproj.io/sync-wave`.
- **Progressive Sync:** При стратегии `RollingSync` ([Progressive Syncs](./progressive_sync.md)) автосинк для сгенерированных приложений принудительно отключается контроллером ApplicationSet (в логах applicationset-controller появляются предупреждения для спецификаций с `automated`). Для обычного ApplicationSet без RollingSync политика из шаблона работает штатно.
- **Ignore Differences:** Если настроено [игнорирование различий](../ignore_differences.md), эти поля не влияют на вычисление diff. Чтобы синхронизация не перезаписывала их на этапе применения, включите `RespectIgnoreDifferences=true`.

## Практические сценарии

### Сценарий 1: Эталонная конфигурация для Production

Для продуктивных сред рекомендуется комбинация защитных механизмов и оптимизаций.

```yaml
spec:
  syncPolicy:
    automated:
      enabled: true             # Явное включение (v3.1+); null эквивалентен true
      prune: true               # Удалять ресурсы, отсутствующие в Git
      selfHeal: true            # Исправлять ручные правки в кластере
      allowEmpty: false         # ЗАЩИТА: не синхронизировать, если репозиторий пуст (default)
    syncOptions:
    - CreateNamespace=true         # Создать Namespace автоматически
    - ServerSideApply=true         # Использовать SSA (опционально; default — client-side apply)
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

Те же настройки через CLI:

```bash
argocd app set <app-name> --sync-policy automated --auto-prune --self-heal
argocd app set <app-name> --sync-option ApplyOutOfSyncOnly=true --sync-option PruneLast=true
```

**Пояснения:**
- `PruneLast=true` гарантирует, что старые ресурсы (например, старые Job-ы миграций) удаляются только после успешного применения новых.
- `FailOnSharedResource=true` предотвращает случайное удаление ресурса, который используется несколькими приложениями.
- `ApplyOutOfSyncOnly=true` снижает нагрузку на API-сервер, пропуская ресурсы, которые уже находятся в желаемом состоянии. Sync-хуки при этом всё равно выполняются, операция записывается в историю. После апгрейда на Argo CD 3.0 с переходом на annotation-based tracking приложения с `ApplyOutOfSyncOnly=true` требуют одного явного синка (см. upgrade guide 2.14→3.0).

### Сценарий 2: Защита от "Катастрофического удаления"

При массовом рефакторинге или ошибке в скриптах генерации манифесты могут исчезнуть из Git.
- **Проблема:** С включенным `prune: true` Argo CD удалит все ресурсы приложения, что приведет к Downtime.
- **Решение:**
    1. `allowEmpty: false` — значение по умолчанию и одновременно защита: синхронизация с полностью пустым источником запрещена. Это поле секции `automated`, не syncOption.
    2. Опция `PrunePropagationPolicy=foreground` — удаление dependent-ресурсов с учетом зависимостей (OwnerReferences). Это **значение по умолчанию**; явно указывать его нужно только для документирования намерения. Альтернативы: `background` (фоновый GC) и `orphan` (dependent-ресурсы остаются).

```yaml
spec:
  syncPolicy:
    syncOptions:
    - PrunePropagationPolicy=foreground  # default: каскадное удаление dependent-ресурсов перед основными
    - PruneLast=true                     # Удалять старое только после успеха нового
```

**Дополнительная защита:**
- Для критичных ресурсов (Namespace, PVC) используйте `Prune=confirm` / `Delete=confirm` — удаление требует ручного подтверждения в UI/CLI (`argocd app confirm-deletion`) или аннотации `argocd.argoproj.io/deletion-approved: <ISO-timestamp>`.
- Используйте `Sync Windows` для блокировки автоматической синхронизации в критические периоды.
- Настройте нотификации для алертов при обнаружении массового удаления.

### Сценарий 3: Оптимизация для высоконагруженных API (SSA)

Если приложение содержит тысячи объектов (например, `NetworkPolicy` или `ConfigMap`).
- **Проблема:** При клиентском `kubectl apply` предыдущее состояние хранится в аннотации `kubectl.kubernetes.io/last-applied-configuration` с лимитом 262144 байт (~256 КБ) — крупные манифесты не применяются. Кроме того, apply каждого объекта нагружает API-сервер.
- **Решение:**
    - Включите `ServerSideApply=true`. Это переносит логику слияния (merging) на сторону Kubernetes (`kubectl apply --server-side --force-conflicts`), аннотация `last-applied-configuration` не используется.
    - Включите `ApplyOutOfSyncOnly=true`, чтобы Argo CD не тратил ресурсы на применение идентичных объектов.

```yaml
spec:
  syncPolicy:
    syncOptions:
    - ServerSideApply=true
    - ApplyOutOfSyncOnly=true
```

**Мониторинг производительности:**
- Следите за метрикой `argocd_app_reconcile` — гистограмма длительности сверки в секундах (`_bucket`/`_sum`/`_count`).
- Используйте `argocd app get <name> --refresh` для принудительного обновления (без синхронизации).

### Сценарий 4: Совместная работа с HPA и Service Mesh

- **Проблема:** Внешние системы (HPA, Istio) меняют ресурсы. Argo CD видит дрейф и пытается его исправить.
- **Решение:**
    1. Настройте [игнорирование различий](../ignore_differences.md).
    2. Обязательно включите `RespectIgnoreDifferences=true` в `syncOptions`, иначе синхронизация применит desired state как есть и перезапишет эти поля при следующем синке. Опция эффективна только для уже созданных в кластере ресурсов.

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    managedFieldsManagers:
    - kube-controller-manager  # HPA
  - group: apps
    kind: Deployment
    jqPathExpressions:
    - .spec.template.spec.containers[] | select(.name == "istio-proxy")
  syncPolicy:
    syncOptions:
    - RespectIgnoreDifferences=true
```

**Конфликт HPA + SelfHeal:**
Если в Git указано `replicas: 3` и включен `selfHeal`, Argo CD вернет количество реплик к значению из Git в течение одного цикла сверки (120s + jitter до 60s, плюс 5s self-heal timeout), конфликтуя с HPA. Решение — исключить `replicas` из Git (полностью или через `ignoreDifferences`) или использовать `managedFieldsManagers`.

### Сценарий 5: Автоматическая синхронизация с Hooks (Pre/Post)

Для приложений, требующих миграций баз данных или инициализации перед деплоем.

```yaml
spec:
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - ServerSideApply=true
    retry:
      limit: 3
      backoff:
        duration: 10s
        factor: 2
        maxDuration: 2m
```

**Важно:** Автоматическая синхронизация применяет ресурсы в порядке Sync Waves. Если PreSync Hook (миграция) завершается неуспешно, синхронизация прерывается и применяется политика retry. Зависшая операция (например, зависший Hook) блокирует применение новых изменений до завершения или принудительной остановки (`argocd app terminate-op <name>`).

### Сценарий 6: ApplicationSet и автоматическая синхронизация

Для обычного ApplicationSet (стратегия `AllAtOnce` или без стратегии) секция `syncPolicy` из шаблона применяется к каждому сгенерированному приложению и работает штатно — включая `automated`, `prune` и `selfHeal`. Ручные правки `syncPolicy` в сгенерированном Application не сохраняются: контроллер ApplicationSet возвращает спецификацию к шаблону при следующей сверке.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: my-appset
  namespace: argocd
spec:
  generators:
  - list:
      elements:
      - cluster: dev
        url: https://dev-cluster.example.com
      - cluster: staging
        url: https://staging-cluster.example.com
  template:
    metadata:
      name: 'my-app-{{cluster}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/infra.git
        path: apps/{{cluster}}
        targetRevision: HEAD
      destination:
        server: '{{url}}'
        namespace: default
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
        - ServerSideApply=true
```

**Примечание:** В мультикластерных средах автоматическая синхронизация работает независимо для каждого кластера. Проблемы в одном кластере не влияют на другие.

**Исключение — RollingSync:** при стратегии `RollingSync` (Progressive Syncs) автосинк в сгенерированных приложениях принудительно отключается контроллером ApplicationSet — см. Сценарий 7.

### Сценарий 7: Интеграция с Progressive Sync (Canary)

Для поэтапной раскатки по группам приложений с возможностью остановки на Canary. Progressive Syncs — **Beta-фича с v3.3.0**, должна быть явно включена одним из способов:

```yaml
# argocd-cmd-params-cm
data:
  applicationsetcontroller.enable.progressive.syncs: "true"
```

или флаг `--enable-progressive-syncs` / переменная `ARGOCD_APPLICATIONSET_CONTROLLER_ENABLE_PROGRESSIVE_SYNCS=true` для контроллера ApplicationSet.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: progressive-app
  namespace: argocd
spec:
  strategy:
    type: RollingSync
    rollingSync:
      steps:
      - matchExpressions:
        - key: env
          operator: In
          values:
          - canary
      - matchExpressions:
        - key: env
          operator: In
          values:
          - staging
        maxUpdate: 10%   # параллельность внутри шага: число или процент (default 100%)
      - matchExpressions:
        - key: env
          operator: In
          values:
          - production
```

**Поведение:**
- Контроллер дожидается статуса `Healthy` для всех приложений шага, прежде чем перейти к следующему. Если приложение в `canary` переходит в `Degraded`, прогресс останавливается — синхронизация для `staging` и `production` не запускается.
- RollingSync **уважает Sync Windows** (синк запускается так, как если бы оператор нажал кнопку Sync в UI) и сохраняет `retry`-настройки приложения.
- Автосинк (`syncPolicy.automated`) в шаблоне при RollingSync игнорируется/отключается принудительно — решение о запуске принимает контроллер ApplicationSet.
- Приложения, не попавшие ни в один шаг, исключаются из rolling sync и требуют ручного синка.

## Технический справочник

### Поля syncPolicy.automated

| Поле | Default | Описание |
| :--- | :--- | :--- |
| `enabled` | `null` (= true) | Явное вкл/выкл автоматической синхронизации (v3.1.0+). `false` отключает автосинк, даже если заданы остальные поля. |
| `prune` | `false` | Удалять ресурсы, которых нет в Git, в рамках автоматической синхронизации. |
| `selfHeal` | `false` | Автоматически возвращать ручные правки кластера к состоянию Git. |
| `allowEmpty` | `false` | Разрешить синхронизацию при пустом источнике (ноль live-ресурсов). |

### Полный перечень опций syncOptions (v3.4.x)

| Опция | Описание | Рекомендация |
| :--- | :--- | :--- |
| `CreateNamespace=true` | Автоматическое создание Namespace, если он отсутствует. | Всегда для dev/staging. |
| `Prune=false` | Запрет удаления конкретного ресурса (resource-аннотация или app level); переопределяет политику приложения. | Для критичных ресурсов. |
| `Prune=confirm` | Удаление ресурса только после ручного подтверждения (UI/CLI, `argocd app confirm-deletion`, или аннотация `argocd.argoproj.io/deletion-approved`). | Для Namespace и критичных ресурсов. |
| `Delete=false` | Не удалять ресурс при удалении Application. | Для PVC и внешних ресурсов. |
| `Delete=confirm` | Удаление при delete Application только после подтверждения. | Для критичных ресурсов. |
| `PruneLast=true` | Удаление старых ресурсов финальной волной, после здоровья новых. | **Всегда в Prod**. |
| `PrunePropagationPolicy=foreground\|background\|orphan` | Политика каскадного удаления dependent-ресурсов. **По умолчанию `foreground`**. | `background` — фоновый GC; `orphan` — оставить dependent-ресурсы. |
| `ApplyOutOfSyncOnly=true` | Применять только ресурсы в статусе `OutOfSync`; хуки всё равно выполняются, синк пишется в историю. | Для приложений с тысячами объектов. |
| `ServerSideApply=true` | `kubectl apply --server-side --force-conflicts`; обходит лимит аннотации `last-applied-configuration` (256 КБ). | Крупные манифесты, частично управляемые ресурсы. |
| `ClientSideApplyMigration=true` | Миграция field ownership с client-side apply на SSA (включен по умолчанию). | При переходе на SSA. |
| `RespectIgnoreDifferences=true` | Учитывать `ignoreDifferences` на этапе apply (pre-patch desired state). Эффективно только для уже созданных ресурсов. | Обязательно с `ignoreDifferences`. |
| `SkipDryRunOnMissingResource=true` | Пропуск `dry-run` для ресурсов с отсутствующими CRD. | Для первой установки CRD. |
| `FailOnSharedResource=true` | Ошибка, если ресурс уже применен другим приложением. | Для мульти-приложений. |
| `Replace=true` | `kubectl replace`/`create` вместо `apply`. **Имеет приоритет над `ServerSideApply=true`**. Destructive — ресурс может быть пересоздан. | Для ресурсов, не помещающихся в аннотацию last-applied. |
| `Validate=false` | Пропуск валидации манифестов (sync option; у `argocd app sync` нет CLI-флага `--validate`). | Для RawExtension-типов и partial-манифестов с SSA. |
| `Force=true` | `kubectl delete/create` — ресурс удаляется и пересоздается при каждом синке. Обычно resource-аннотация, часто с `Replace=true`. | Для Job, которые должны запускаться при каждом синке. |

**Отдельно от syncOptions:** `spec.syncPolicy.managedNamespaceMetadata` — поле политики (не опция) с `labels`/`annotations` для автосоздаваемого Namespace; требует `CreateNamespace=true`. Если в Git есть манифест того же Namespace, он переопределяет `managedNamespaceMetadata`.

### Diff-стратегии

- **Legacy** (default): 3-way diff по live state, desired state и аннотации `last-applied-configuration`.
- **Structured-Merge Diff**: автоматически применялась при включенном `ServerSideApply=true`; сейчас **discontinued** в пользу Server-Side Diff (проблемы с CRD, задающими default-значения).
- **Server-Side Diff** (v3.5+): выполняет SSA в dry-run режиме для каждого ресурса и сравнивает результат с live state. Преимущество: admission-контроллеры (валидирующие и мутирующие вебхуки) участвуют в диффе — невалидные ресурсы выявляются на этапе diff, а не sync. Модификации мутирующих вебхуков удаляются из diff по умолчанию. Для новых (еще не созданных) и удаляемых ресурсов server-side diff не выполняется — возвращается упрощённый diff без вызова к kube-api.

Включение (v3.5+):

```yaml
# На уровне приложения (аннотация):
metadata:
  annotations:
    argocd.argoproj.io/compare-options: ServerSideDiff=true
```

```bash
# Или через CLI:
argocd app diff <app-name> --server-side-diff
```

В новых версиях Server-Side Diff также включается автоматически для ресурсов с sync option `ServerSideApply=true`. Глобального переключателя в `argocd-cm`/`argocd-cmd-params-cm` нет; когда dry-run runner недоступен (например, `argocd app diff` без server-side generation), Argo CD автоматически откатывается к клиентскому 3-way/2-way diff.

### Настройка логики Retry

Если синхронизация падает из-за временных сетевых ошибок или недоступности вебхуков, `Retry` позволяет приложению восстановиться автоматически. Формула паузы: `timeToWait = duration × factor^retryCount`, ограниченная сверху `maxDuration`.

- **`limit`**: максимальное количество попыток. **Default 0** — без повторов; `-1` — бесконечные повторы.
- **`backoff.duration`**: базовая пауза перед первым повтором. **Default 5s**.
- **`backoff.factor`**: множитель (default 2 превратит 5s в 10s, 20s и т.д.). **Default 2**.
- **`backoff.maxDuration`**: "потолок" ожидания, чтобы цикл не растягивался на часы. **Default 3m**.
- **`refresh`** (default `false`): при повторе использовать последнюю ревизию из источника, а не ту, что была в момент неудачи (`argocd app set <app> --sync-retry-refresh`).

**Примеры:**

```yaml
# Базовый retry (3 попытки)
retry:
  limit: 3

# Экспоненциальный backoff (5 попыток, дефолтные 5s/2/3m)
retry:
  limit: 5
  backoff:
    duration: 5s
    factor: 2
    maxDuration: 3m

# Агрессивный retry (для критичных сервисов)
retry:
  limit: 10
  backoff:
    duration: 2s
    factor: 1.5
    maxDuration: 10m
```

### Временные интервалы

- **Интервал сверки (Reconciliation Interval):** определяется значением `timeout.reconciliation` в `argocd-cm`, **default 120s + jitter до 60s** (максимальный период 3 минуты). Контроллер проверяет Git и кластер с этим интервалом.
- **Self-Heal:** дрейф обнаруживается на сверке; синк запускается через self-heal timeout — **5s default** (флаг `--self-heal-timeout-seconds` deployment `argocd-application-controller`). Итого типичное время исправления ручной правки — около 2–3,5 минут.
- **Таймаут ожидания в CLI:** `--timeout` на `argocd app sync` ограничивает время ожидания CLI-команды, но не саму операцию в кластере. Зависшую операцию можно остановить принудительно: `argocd app terminate-op <name>`.

## Диагностика и устранение неисправностей

### Типичные проблемы

| Проблема | Симптомы | Вероятная причина | Решение |
| :--- | :--- | :--- | :--- |
| **Синхронизация не запускается** | Приложение в статусе `OutOfSync`, но не синхронизируется | Не включен `automated` (или `enabled: false`) или настроены Sync Windows | Проверьте `spec.syncPolicy.automated` и Sync Windows; метрика `argocd_app_sync_blocked` |
| **Self-Heal не работает** | Ручные правки не откатываются | Не включен `selfHeal` или игнорируется поле | Добавьте `selfHeal: true` и `RespectIgnoreDifferences=true` |
| **Ресурсы не удаляются** | Старые ресурсы остаются в кластере | Не включен `prune` | Добавьте `prune: true` в `automated` |
| **Ошибка "repository not found"** | Синхронизация падает с ошибкой доступа | Нет доступа к Git-репозиторию | Проверьте Credentials в `argocd-repo-server` |
| **Конфликт с HPA** | Argo CD возвращает количество реплик | `selfHeal` конфликтует с HPA | Настройте `ignoreDifferences` для `replicas` |
| **Медленная синхронизация** | Синхронизация занимает >5 минут | Много ресурсов, нет `ApplyOutOfSyncOnly` | Включите `ApplyOutOfSyncOnly=true`, `ServerSideApply=true` |
| **Ошибка "shared resource"** | Синхронизация падает | Ресурс используется другим приложением | Включите `FailOnSharedResource=false` (default) или разделите ресурсы |
| **Retry не срабатывает** | Синхронизация падает без повторов | Не настроена политика retry | Добавьте `retry.limit > 0` |
| **Невозможен rollback** | `argocd app rollback` отклоняется | Включен automated sync | Временно отключите `automated` или `enabled: false` |

### Диагностические команды

```bash
# Просмотр статуса приложения
argocd app get <app-name>

# Принудительное обновление данных (без синхронизации)
argocd app get <app-name> --refresh
argocd app get <app-name> --hard-refresh

# Diff перед синхронизацией (exit codes: 0 — нет diff, 1 — есть diff, 2 — ошибка)
argocd app diff <app-name>

# Ожидание синхронизированного и здорового состояния
argocd app wait <app-name>

# Остановка зависшей операции
argocd app terminate-op <app-name>

# Просмотр логов контроллера
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f

# События Application (в namespace, где живет ресурс Application)
kubectl get events -n <namespace-приложения> --field-selector involvedObject.kind=Application

# Просмотр деталей последней синхронизации
argocd app history <app-name>

# Принудительная синхронизация (CLI)
argocd app sync <app-name>

# Принудительная синхронизация с prune
argocd app sync <app-name> --prune
```

### Пошаговая диагностика

1. **Проверьте статус:** `argocd app get <name>` — убедитесь, что статус `OutOfSync` или `Synced`.
2. **Просмотрите diff:** `argocd app diff <name>` — проверьте, какие именно поля различаются.
3. **Проверьте настройки:** Убедитесь, что `syncPolicy.automated` включен и содержит нужные флаги.
4. **Проверьте Sync Windows:** Если есть ограничения по времени, дождитесь окончания блокировки.
5. **Просмотрите логи:** `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller` — найдите ошибки.
6. **Проверьте Credentials:** Убедитесь, что Argo CD имеет доступ к Git-репозиторию и кластеру.

## Валидация и проверка работоспособности

### Проверка автоматической синхронизации

```bash
# 1. Примените манифест Application
kubectl apply -f application.yaml

# 2. Дождитесь статуса Synced (до 3 минут)
argocd app get <name>
# или блокирующее ожидание:
argocd app wait <name>

# 3. Измените ресурс в кластере (ручное изменение)
kubectl patch deployment <name> --type merge -p '{"spec":{"replicas":5}}'

# 4. Дождитесь исправления Self-Heal (сверка 120s + jitter 60s + self-heal timeout 5s)
argocd app get <name>
# или отслеживайте статус ресурса:
kubectl get deployment <name> -w

# 5. Проверьте, что реплики вернулись к Git-значению
kubectl get deployment <name> -o jsonpath='{.spec.replicas}'
```

### Проверка Pruning

```bash
# 1. Удалите ресурс из Git (или переместите в другую папку)
git rm resource.yaml && git push

# 2. Дождитесь следующей сверки (или принудительно)
argocd app get <name> --refresh

# 3. Проверьте, что ресурс удален из кластера
kubectl get <resource> <name>
# → result: Error from server (NotFound)
```

### Проверка Retry

```bash
# 1. Временно заблокируйте доступ к API-серверу (имитация сбоя)
# Или отключите сеть для контроллера

# 2. Запустите синхронизацию
argocd app sync <name>

# 3. Просмотрите логи повторных попыток
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep retry
```

## Лучшие практики

### Приоритет настроек

1. **Для Production:** Всегда используйте `prune: true`, `selfHeal: true`, `PruneLast=true`, `RespectIgnoreDifferences=true`, `ApplyOutOfSyncOnly=true`.
2. **Для Staging:** Аналогично Production, но можно отключить `PruneLast=true` для ускорения итераций.
3. **Для Development:** Можно использовать `prune: false`, `selfHeal: false` для ручного управления.

### Безопасность

- **`allowEmpty: false`:** Не устанавливайте `allowEmpty: true` без необходимости — default-значение `false` защищает от массового удаления ресурсов при ошибке в скриптах генерации.
- **`FailOnSharedResource=true`:** Используйте в мульти-приложениях, чтобы не удалить ресурс, используемый другим приложением.
- **`Prune=confirm` / `Delete=confirm`:** Для Namespace и PVC — удаление только после явного подтверждения.
- **Sync Windows:** Настраивайте окна блокировки для критических периодов (отпуски, выходные, техническое обслуживание).
- **Ревью через PR:** Любые изменения в `syncPolicy` должны проходить code review.
- **Запрет force-push в main** и CODEOWNERS на манифесты — дополнительные защиты от катастрофического удаления.

### Масштабирование

- **`ApplyOutOfSyncOnly=true`:** Включайте для приложений с тысячами объектов — снижает нагрузку на API-сервер и размер `status.operationState.syncResult.resources`.
- **`ServerSideApply=true`:** Используйте для крупных манифестов (лимит аннотации `last-applied-configuration` — 256 КБ) и ресурсов, частично управляемых другими контроллерами.
- **ApplicationSet:** Используйте для управления множеством приложений с едиными политиками.
- **Progressive Sync:** Используйте для поэтапной раскатки по кластерам (Beta с v3.3.0, требует явного включения).
- **Шардирование:** Для очень больших инсталляций — шардирование application-controller (`controller.sharding.algorithm`).

### Мониторинг

- **Алерты на `OutOfSync`:** Настраивайте алерты на длительный статус `OutOfSync` (>10 минут) — `argocd_app_info{sync_status="OutOfSync"}`.
- **Алерты на `Degraded`:** Немедленно реагируйте на приложения в статусе `Degraded` — `argocd_app_info{health_status="Degraded"}`.
- **Алерты на ошибки синхронизации:** `increase(argocd_app_sync_total{phase="Error"}[5m]) > 0`.
- **Блокировки Sync Windows:** `argocd_app_sync_blocked == 1` — автосинк заблокирован окнами.
- **Нотификации:** Настройте Slack/Email/PagerDuty для уведомлений о синхронизациях.

### Интеграция с CI/CD

- **Git-Triggered Sync:** Автоматическая синхронизация запускается в течение одного интервала сверки (120s + jitter до 60s) после коммита в Git. CI-пайплайну не нужен доступ к API-серверу Argo CD.
- **PR-Triggered Sync:** Для dev/staging можно настроить синхронизацию при мерже PR.
- **Manual Sync для Prod:** Рассмотрите возможность использования ручной синхронизации для Production с аудитом.

## Ограничения и edge cases

### Ограничения

1. **Self-Heal и Sync Windows:** Если ресурс изменен во время блокировки, Argo CD обнаруживает дрейф (приложение остается `OutOfSync`), но коррекция откладывается до открытия окна.
2. **Prune и OwnerReferences:** В pruning участвуют только top-level ресурсы приложения. Ресурсы, которым внешние контроллеры добавили ownerReferences, исключаются из pruning по дизайну (Argo CD не считает их управляемыми объектами) — удаление таких dependent-ресурсов происходит каскадно через Kubernetes Garbage Collector по OwnerReferences.
3. **Retry не отменяет зависшую операцию:** Если синхронизация "зависла" (например, из-за PreSync Hook), retry не запускается до завершения или принудительной остановки текущей операции (`argocd app terminate-op`).
4. **ApplicationSet:** Для обычного ApplicationSet `syncPolicy` из шаблона работает штатно; для RollingSync автосинк принудительно отключен контроллером ApplicationSet.
5. **Rollback:** `argocd app rollback` невозможен для приложения с включенным automated sync.
6. **Multi-source приложения:** Отключенный `selfHeal` не гарантирует сохранения ручных изменений — изменение в другом источнике может вновь запустить autosync.

### Edge Cases

1. **Конфликт Self-Heal и HPA:** Если в Git указано `replicas: 3` и включен `selfHeal`, Argo CD будет возвращать реплики к значению из Git в течение цикла сверки, конфликтуя с HPA. Решение — использовать `ignoreDifferences` для `replicas`.
2. **Множественные ApplicationSets на один ресурс:** Если ресурс управляется несколькими ApplicationSets, возникает конфликт. Используйте `FailOnSharedResource=true`.
3. **Удаление Application во время синхронизации:** Если Application удален во время выполняющейся синхронизации, операция завершается, но ресурсы в кластере могут остаться в промежуточном состоянии.
4. **Helm Chart с mutable-полями:** Некоторые Helm-чарты используют поля, которые невозможно обновить через `apply`. Используйте `Replace=true`.
5. **Cross-namespace ресурсы:** Автоматическая синхронизация не ограничена одним namespace — Argo CD может управлять cluster-scoped ресурсами и ресурсами в других namespaces, если это разрешено RBAC и AppProject, а манифесты явно указывают `metadata.namespace`.

## Мониторинг и нотификации

### Метрики Prometheus

Применимо к application-controller (эндпоинт `argocd-metrics:8082/metrics`):

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `argocd_app_reconcile` | histogram | Длительность сверки приложения, секунды (серии `_bucket`, `_sum`, `_count`). |
| `argocd_app_sync_total` | counter | История синхронизаций; label `phase`: `Error`, `Failed`, `Running`, `Succeeded`, `Terminating`. |
| `argocd_app_sync_duration_seconds_total` | counter | Суммарная длительность синхронизаций, секунды. |
| `argocd_app_info` | gauge | Информация о приложении; labels `sync_status` и `health_status` (`Healthy`/`Degraded`/`Progressing` и др.). |
| `argocd_app_condition` | gauge | Условия (conditions) приложения. |
| `argocd_app_k8s_request_total` | counter | Число запросов к Kubernetes API при сверке. |
| `argocd_app_sync_window` | gauge | Оценка sync windows приложения (количество allow/deny). |
| `argocd_app_sync_blocked` | gauge | `1` — автоматическая синхронизация сейчас заблокирована sync windows проекта. |

### Нотификации

Argo CD Notifications интегрируется с системами доставки (Slack, Email, PagerDuty, Telegram, MS Teams, Webhook). Полная конфигурация — в [ArgoCD Notifications](../../argocd_notifications.md) (SSoT по уведомлениям). Пример конфигурации (`argocd-notifications-cm`):

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
data:
  # oncePer предотвращает флаттер: уведомление только при смене ревизии
  trigger.on-sync-succeeded: |
    - when: app.status.operationState.phase in ['Succeeded']
      oncePer: app.status.sync.revision
      send: [app-sync-succeeded]
  trigger.on-sync-failed: |
    - when: app.status.operationState.phase in ['Error', 'Failed']
      send: [app-sync-failed]
  template.app-sync-succeeded: |
    message: |
      Application {{.app.metadata.name}} sync succeeded.
      Revision: {{.app.status.sync.revision}}
  template.app-sync-failed: |
    message: |
      Application {{.app.metadata.name}} sync failed.
      Error: {{.app.status.operationState.message}}
  service.slack: |
    token: $slack-token
```

**Важно:** триггеры сами по себе ничего не отправляют — нужна подписка: либо глобальная секция `subscriptions` в ConfigMap, либо аннотация на Application:

```yaml
metadata:
  annotations:
    notifications.argoproj.io/subscribe.on-sync-succeeded.slack: my-channel
    notifications.argoproj.io/subscribe.on-sync-failed.slack: my-channel
```

Секреты (токены) хранятся в `argocd-notifications-secret` и передаются в сервисы по ссылкам вида `$slack-token`.

## Дополнительная информация

### PreDelete и PostDelete хуки

- **PreDelete** (v3.3.0+) — хук, выполняющийся при **удалении приложения** (не при синхронизации): снапшоты БД, отзыв сертификатов, уведомления. Работает только при удалении всего Application (не при prune). Если PreDelete хук завершается неуспешно, удаление приложения блокируется.
- **PostDelete** (v2.10+) — выполняется после удаления всех ресурсов: очистка внешних ресурсов (DNS, S3), уведомления. При сбое хука Application CR сохраняется с ошибкой удаления (`DeletionError`).

### Ограничения

- **Окна синхронизации:** Если настроены [Sync Windows](./sync_windows.md), автоматическая синхронизация будет заблокирована в запрещенные интервалы, даже если в Git появились изменения.
- **Зависящие операции:** Если процесс синхронизации "завис" (например, из-за PreSync Hook), новые изменения в Git не будут применяться до завершения или принудительной остановки текущей операции.
- **Масштаб:** Для очень больших приложений (тысячи ресурсов) используйте `ApplyOutOfSyncOnly=true`, SSA, шардирование контроллера и разбиение на несколько ApplicationSet.

### См. также

- **[Синхронизация Argo CD: Обзор](../../synchronization.md)** — общая архитектура процесса.
- **[Игнорирование различий](../ignore_differences.md)** — решение конфликтов с внешними контроллерами.
- **[Волны и хуки](./sync_waves_hooks.md)** — управление очередностью.
- **[Окна синхронизации](./sync_windows.md)** — временные ограничения.
- **[Прогрессивная синхронизация](./progressive_sync.md)** — поэтапная раскатка.
- **[Ручная синхронизация](./manual_sync.md)** — селективный деплой.
- **[ArgoCD Notifications](../../argocd_notifications.md)** — уведомления (SSoT).
- [Официальная документация: Automated Sync Policy](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)
- [Официальная документация: Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
- [Официальная документация: Diff Strategies](https://argo-cd.readthedocs.io/en/stable/user-guide/diff-strategies/)
- [Официальная документация: Progressive Syncs](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Progressive-Syncs/)
