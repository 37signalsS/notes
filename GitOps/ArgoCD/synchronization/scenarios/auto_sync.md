# Argo CD — автоматическая синхронизация

> **Актуальность (2026):** В версии Argo CD v3.x автоматическая синхронизация стала более эффективной благодаря оптимизации `ApplyOutOfSyncOnly` и поддержке **Server-Side Apply (SSA)** по умолчанию. Эти механизмы позволяют управлять кластерами с десятками тысяч ресурсов без деградации производительности API-сервера Kubernetes.

## Предварительные требования

Перед включением автоматической синхронизации необходимо убедиться в следующем:

1. **Версия Argo CD:** v2.6+ (рекомендуется v3.x для полной поддержки SSA и оптимизаций).
2. **Проект (AppProject):** Приложение должно быть привязано к проекту с разрешенными целевыми кластерами и namespaces.
3. **Источник кода:** Репозиторий доступен для Argo CD (настроены credentials или публичный доступ).
4. **Понимание рисков:** Автоматическая синхронизация с `prune: true` и `selfHeal: true` может удалить ресурсы или откатить ручные изменения. Убедитесь, что политики соответствуют требованиям среды.
5. **Настроенная синхронизация:** Приложение уже успешно синхронизируется вручную (или хотя бы один раз через UI/CLI).

## Определения

**Автоматическая синхронизация (Automated Sync)** — режим работы Argo CD, при котором контроллер автоматически применяет изменения из Git к кластеру сразу после обнаружения расхождений (`OutOfSync`). Это исключает ручное вмешательство из цикла доставки.

**Self-Heal (Автоматическое исправление)** — механизм, который обнаруживает ручные изменения в кластере (Manual Drift) и автоматически возвращает ресурсы к эталонному состоянию, описанному в Git. Работает только для изменений, обнаруженных контроллером Argo CD; не отслеживает изменения, внесенные во время окон `Sync Windows`.

**Pruning (Удаление лишнего)** — процесс автоматического удаления ресурсов из Kubernetes, если их описание было удалено из Git-репозитория. Гарантирует, что кластер не содержит "мусорных" объектов. Удаление происходит в порядке, обратном зависимостям (сначала dependent-ресурсы).

**Sync Options (Опции синхронизации)** — специфические флаги в манифесте `Application`, управляющие тонким поведением процесса применения изменений (например, пропуск валидации или создание пространств имен).

**Retry Policy (Политика повторных попыток)** — конфигурация, определяющая количество и интервалы повторных попыток синхронизации при временных сбоях (сетевые ошибки, недоступность API, таймауты).

## Базовые концепции

### Почему автоматизация необходима

1.  **Борьба с дрейфом (Drift):** В динамических средах ручные правки (`kubectl edit`) неизбежны, но опасны. `Self-Heal` гарантирует, что инфраструктура всегда соответствует коду.
2.  **Масштабируемость:** Один оператор может управлять сотнями приложений, так как Argo CD берет на себя рутину по нажатию кнопок "Sync".
3.  **Скорость (MTTD/MTTR):** Время от коммита до деплоя в Staging сокращается до секунд.
4.  **Консистентность:** Гарантирует, что все кластеры (dev/staging/prod) находятся в одинаковом состоянии, описанном в Git.
5.  **Аудит:** Каждая синхронизация логируется, что позволяет отслеживать, кто и когда применил изменения.

### Механика выполнения Sync

1.  **Детекция:** Контроллер сравнивает `Live State` (текущее состояние в кластере) и `Desired State` (описание в Git).
2.  **Оценка:** Если статус `OutOfSync`, проверяется наличие флага `syncPolicy.automated`.
3.  **Порядок:** Argo CD выстраивает дерево ресурсов согласно [Sync Waves и Hooks](./sync_waves_hooks.md).
4.  **Применение:** Выполняется `kubectl apply` (или SSA) для каждого ресурса.
5.  **Валидация:** После применения проверяется健康ность ресурсов (Health Checks).
6.  **Повторные попытки:** При неудаче применяется политика retry (если настроена).

### Компоненты автоматической синхронизации

- **`automated`** — основной флаг, включающий автоматическую синхронизацию. Содержит подпараметры `prune` и `selfHeal`.
- **`prune`** — разрешает удаление ресурсов, отсутствующих в Git. Без этого флага Argo CD только добавляет/обновляет, но не удаляет.
- **`selfHeal`** — разрешает автоматическое исправление ручных правок в кластере. Работает с интервалом проверки (по умолчанию 5 минут).
- **`allowEmpty`** — защитный флаг, запрещающий синхронизацию, если Git-репозиторий пуст (все манифесты удалены).
- **`retry`** — конфигурация повторных попыток при временных сбоях.

### Взаимодействие с другими механизмами

- **Sync Windows:** Если настроены [Sync Windows](./sync_windows.md), автоматическая синхронизация будет заблокирована в запрещенные интервалы, даже если в Git появились изменения.
- **Sync Waves:** Автоматическая синхронизация учитывает [волны и хуки](./sync_waves_hooks.md) — ресурсы применяются в порядке, определенном аннотациями `argocd.argoproj.io/sync-wave`.
- **Progressive Sync:** В ApplicationSet стандартный флаг `syncPolicy.automated` внутри шаблона приложения игнорируется. Решение о запуске синхронизации принимает контроллер `ApplicationSet`.
- **Ignore Differences:** Если настроено [игнорирование различий](../ignore_differences.md), `selfHeal` не будет пытаться исправить игнорируемые поля.

## Практические сценарии

### Сценарий 1: Эталонная конфигурация для Production

Для продуктивных сред рекомендуется комбинация защитных механизмов и оптимизаций.

```yaml
spec:
  syncPolicy:
    automated:
      prune: true             # Удалять ресурсы, отсутствующие в Git
      selfHeal: true          # Исправлять ручные правки в кластере
      allowEmpty: false       # ЗАЩИТА: не удалять всё, если репозиторий пуст
    syncOptions:
    - CreateNamespace=true       # Создать Namespace автоматически
    - ServerSideApply=true       # Использовать SSA (стандарт 2026 года)
    - FailOnSharedResource=true  # Ошибка, если ресурс занят другим приложением
    - RespectIgnoreDifferences=true # Не трогать поля из ignoreDifferences
    - ApplyOutOfSyncOnly=true    # Оптимизация: не слать в API неизмененные ресурсы
    - PruneLast=true             # Удалять старое только после успеха нового деплоя
    retry:
      limit: 5                   # Максимум 5 попыток при сбое
      backoff:
        duration: 5s             # Пауза между попытками
        factor: 2                # Экспоненциальный рост паузы
        maxDuration: 5m          # Максимальное время ожидания
```

**Пояснения:**
- `PruneLast=true` гарантирует, что старые ресурсы (например, старые Job-ы миграций) удаляются только после успешного применения новых.
- `FailOnSharedResource=true` предотвращает случайное удаление ресурса, который используется несколькими приложениями.
- `ApplyOutOfSyncOnly=true` снижает нагрузку на API-сервер, пропуская ресурсы, которые уже находятся в желаемом состоянии.

### Сценарий 2: Защита от "Катастрофического удаления"

При массовом рефакторинге или ошибке в скриптах генерации манифесты могут исчезнуть из Git.
- **Проблема:** С включенным `prune: true` Argo CD удалит все ресурсы приложения, что приведет к Downtime.
- **Решение:** 
    1. Использование `allowEmpty: false` (входит в стандарт v3.x) — запрещает удаление всех ресурсов сразу.
    2. Опция `PrunePropagationPolicy=foreground` — гарантирует корректное удаление ресурсов с учетом зависимостей (OwnerReferences).

```yaml
spec:
  syncPolicy:
    syncOptions:
    - PrunePropagationPolicy=foreground  # Удалять dependent-ресурсы перед основными
    - PruneLast=true                     # Удалять старое только после успеха нового
```

**Дополнительная защита:**
- Используйте `Sync Windows` для блокировки автоматической синхронизации в критические периоды.
- Настройте нотификации для алертов при обнаружении массового удаления.

### Сценарий 3: Оптимизация для высоконагруженных API (SSA)

Если приложение содержит тысячи объектов (например, `NetworkPolicy` или `ConfigMap`).
- **Проблема:** Обычный `kubectl apply` перегружает API-сервер и может вызывать ошибки `Too large resource`.
- **Решение:** 
    - Включите `ServerSideApply=true`. Это переносит логику слияния (merging) на сторону Kubernetes.
    - Включите `ApplyOutOfSyncOnly=true`, чтобы Argo CD не тратил ресурсы на проверку идентичных объектов.

```yaml
spec:
  syncPolicy:
    syncOptions:
    - ServerSideApply=true
    - ApplyOutOfSyncOnly=true
```

**Мониторинг производительности:**
- Следите за метрикой `argocd_app_reconcile_bucket` — она показывает время последней сверки.
- Используйте `argocd app get <name> --refresh` для принудительного обновления (без синхронизации).

### Сценарий 4: Совместная работа с HPA и Service Mesh

- **Проблема:** Внешние системы (HPA, Istio) меняют ресурсы. Argo CD видит дрейф и пытается его исправить.
- **Решение:** 
    1. Настройте [игнорирование различий](../ignore_differences.md).
    2. Обязательно включите `RespectIgnoreDifferences=true` в `syncOptions`, иначе `Self-Heal` перезапишет эти поля при следующей проверке.

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
Если в Git указано `replicas: 3` и включен `selfHeal`, ArgoCD будет мгновенно возвращать количество реплик назад, конфликтуя с HPA. Решение — исключить `replicas` из Git или использовать `managedFieldsManagers`.

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

**Важно:** Автоматическая синхронизация применяет ресурсы в порядке Sync Waves. Если PreSync Hook (миграция) завершается неуспешно, синхронизация прерывается и применяется политика retry.

### Сценарий 6: ApplicationSet и автоматическая синхронизация

В ApplicationSet стандартный флаг `syncPolicy.automated` внутри шаблона приложения игнорируется. Автоматическая синхронизация на уровне ApplicationSet управляется контроллером ApplicationSet.

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

### Сценарий 7: Интеграция с Progressive Sync (Canary)

Для поэтапной раскатки по группам кластеров с возможностью остановки на Canary.

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
      - matchExpressions:
        - key: env
          operator: In
          values:
          - production
```

**Поведение:** Если приложение в `canary` перейдет в `Degraded`, автоматическая синхронизация для `staging` и `production` не запустится.

## Технический справочник

### Полный перечень опций синхронизации (v3.x)

| Опция | Описание | Рекомендация |
| :--- | :--- | :--- |
| `CreateNamespace=true` | Автоматическое создание Namespace, если он отсутствует. | Всегда для dev/staging. |
| `Prune=true` | Удаление ресурсов, которых нет в Git. | Для Production с `PruneLast=true`. |
| `SelfHeal=true` | Автоматический откат ручных правок. | Для Production и Staging. |
| `AllowEmpty=false` | Запрет синхронизации, если Git пуст. | **Всегда включать** (защита). |
| `ServerSideApply=true` | Использование SSA вместо Client-Side Apply. | Стандарт для v3.x. |
| `RespectIgnoreDifferences=true` | Уважение настроек `ignoreDifferences` при синхронизации. | Обязательно с `ignoreDifferences`. |
| `SkipDryRunOnMissingResource=true` | Пропуск `dry-run` для ресурсов с отсутствующими CRD. | Для первой установки CRD. |
| `Replace=true` | Использование `kubectl replace` вместо `apply`. | Для ресурсов с immutable-полями. |
| `ApplyOutOfSyncOnly=true` | Пропуск неизмененных ресурсов. | Для приложений с >100 ресурсами. |
| `PruneLast=true` | Удаление старых ресурсов после успеха нового деплоя. | **Всегда в Prod**. |
| `PrunePropagationPolicy=foreground` | Удаление dependent-ресурсов перед основными. | Для каскадного удаления. |
| `PrunePropagationPolicy=background` | Удаление dependent-ресурсов после основных. | По умолчанию. |
| `FailOnSharedResource=true` | Ошибка, если ресурс используется другим приложением. | Для мульти-приложений. |
| `Validate=false` | Пропуск валидации манифестов. | Только для кастомных CRD. |
| `SkipSchemaValidation=true` | Пропуск валидации схемы. | Только для некорректных CRD. |
| `ManagedNamespaceMetadata=true` | Управление аннотациями/метками Namespace. | Для автоматизации метаданных. |
| `Force=true` | Использование `kubectl apply --force`. | Для конфликтов при обновлении. |

### Настройка логики Retry

Если синхронизация падает из-за временных сетевых ошибок или недоступности вебхуков, `Retry` позволяет приложению восстановиться автоматически.

- **`limit`**: максимальное количество попыток (по умолчанию 0 — без повторов).
- **`duration`**: начальный интервал между попытками (по умолчанию 2s).
- **`factor`**: множитель (например, 2 превратит 5s в 10s, 20s и т.д.).
- **`maxDuration`**: "потолок" ожидания, чтобы цикл не растягивался на часы.

**Примеры:**

```yaml
# Базовый retry (3 попытки)
retry:
  limit: 3

# Экспоненциальный backoff (5 попыток)
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

- **Интервал сверки (Reconciliation Interval):** По умолчанию 3 минуты. Контроллер проверяет Git и кластер каждые 3 минуты.
- **Интервал Self-Heal:** Совпадает с интервалом сверки. Ручные правки исправляются в течение 3-5 минут.
- **Таймаут синхронизации:** По умолчанию не ограничен (зависит от количества ресурсов).

## Диагностика и устранение неисправностей

### Типичные проблемы

| Проблема | Симптомы | Вероятная причина | Решение |
| :--- | :--- | :--- | :--- |
| **Синхронизация не запускается** | Приложение в статусе `OutOfSync`, но не синхронизируется | Не включен `automated` или настроены Sync Windows | Проверьте `spec.syncPolicy.automated` и Sync Windows |
| **Self-Heal не работает** | Ручные правки не откатываются | Не включен `selfHeal` или игнорируется поле | Добавьте `selfHeal: true` и `RespectIgnoreDifferences=true` |
| **Ресурсы не удаляются** | Старые ресурсы остаются в кластере | Не включен `prune` | Добавьте `prune: true` в `automated` |
| **Ошибка "repository not found"** | Синхронизация падает с ошибкой доступа | Нет доступа к Git-репозиторию | Проверьте Credentials в `argocd-repo-server` |
| **Конфликт с HPA** | Argo CD возвращает количество реплик | `selfHeal` конфликтует с HPA | Настройте `ignoreDifferences` для `replicas` |
| **Медленная синхронизация** | Синхронизация занимает >5 минут | Много ресурсов, нет `ApplyOutOfSyncOnly` | Включите `ApplyOutOfSyncOnly=true` |
| **Ошибка "shared resource"** | Синхронизация падает | Ресурс используется другим приложением | Включите `FailOnSharedResource=false` или разделите ресурсы |
| **Retry не срабатывает** | Синхронизация падает без повторов | Не настроена политика retry | Добавьте `retry.limit > 0` |

### Диагностические команды

```bash
# Просмотр статуса приложения
argocd app get <app-name>

# Принудительное обновление (без синхронизации)
argocd app get <app-name> --refresh

# Просмотр логов контроллера
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f

# Просмотр событий синхронизации
kubectl get events -n argocd --field-selector reason=Synced

# Просмотр деталей последней синхронизации
argocd app history <app-name>

# Просмотр diff перед синхронизацией
argocd app diff <app-name>

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

# 2. Дождитесь статуса Synced (до 5 минут)
argocd app get <name> --watch

# 3. Измените ресурс в кластере (ручное изменение)
kubectl patch deployment <name> --type merge -p '{"spec":{"replicas":5}}'

# 4. Дождитесь исправления Self-Heal (до 5 минут)
argocd app get <name> --watch

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

- **`AllowEmpty=false`:** Всегда включайте этот флаг — он защищает от массового удаления ресурсов при ошибке в скриптах генерации.
- **`FailOnSharedResource=true`:** Используйте в мульти-приложениях, чтобы не удалить ресурс, используемый другим приложением.
- **Sync Windows:** Настраивайте окна блокировки для критических периодов (отпуски, выходные,aintenance).
- **Ревью через PR:** Любые изменения в `syncPolicy` должны проходить code review.

### Масштабирование

- **`ApplyOutOfSyncOnly=true`:** Включайте для приложений с >50 ресурсами — снижает нагрузку на API-сервер.
- **`ServerSideApply=true`:** Используйте для всех приложений в v3.x — переносит логику слияния на сторону Kubernetes.
- **ApplicationSet:** Используйте для управления множеством приложений с едиными политиками.
- **Progressive Sync:** Используйте для поэтапной раскатки по кластерам.

### Мониторинг

- **Алерты на `OutOfSync`:** Настраивайте алерты на длительный статус `OutOfSync` (>10 минут).
- **Алерты на `Degraded`:** Немедленно реагируйте на приложения в статусе `Degraded`.
- **Метрики Argo CD:** Используйте Prometheus-метрики для мониторинга времени синхронизации.
- **Нотификации:** Настройте Slack/Email/PagerDuty для уведомлений о синхронизациях.

### Интеграция с CI/CD

- **Git-Triggered Sync:** Автоматическая синхронизация запускается сразу после коммита в Git.
- **PR-Triggered Sync:** Для dev/staging можно настроить синхронизацию при мерже PR.
- **Manual Sync для Prod:** Рассмотрите возможность использования ручной синхронизации для Production с аудитом.

## Ограничения и edge cases

### Ограничения

1. **Self-Heal не отслеживает изменения во время Sync Windows:** Если ресурс изменен во время блокировки, Argo CD не обнаружит это до следующей проверки после окончания окна.
2. **Prune не работает для ресурсов с OwnerReferences:** Удаление dependent-ресурсов происходит каскадно через Kubernetes API, а не через Argo CD.
3. **Retry не ограничивает время выполнения:** Если синхронизация "зависла" (например, из-за PreSync Hook), retry будет повторять попытки до достижения `limit`.
4. **ApplicationSet игнорирует `automated` в шаблоне:** Автоматическая синхронизация управляется контроллером ApplicationSet, а не параметрами шаблона.

### Edge Cases

1. **Конфликт Self-Heal и HPA:** Если в Git указано `replicas: 3` и включен `selfHeal`, Argo CD будет конфликтовать с HPA. Решение — использовать `ignoreDifferences` для `replicas`.
2. **Множественные ApplicationSets на один ресурс:** Если ресурс управляется несколькими ApplicationSets, возникает конфликт. Используйте `FailOnSharedResource=true`.
3. **Удаление Application во время синхронизации:** Если Application удален во время выполняющейся синхронизации, операция завершается, но ресурсы в кластере могут остаться в промежуточном состоянии.
4. **Helm Chart с mutable-полями:** Некоторые Helm-чарты используют поля, которые невозможно обновить через `apply`. Используйте `Replace=true`.
5. **Cross-namespace ресурсы:** Автоматическая синхронизация работает только в рамках одного namespace. Для кросс-namespace ресурсов настройте отдельные ApplicationSets.

## Мониторинг и нотификации

### Метрики Prometheus

- `argocd_app_reconcile_bucket` — время последней сверки.
- `argocd_app_reconcile_errors_total` — количество ошибок синхронизации.
- `argocd_app_sync_total` — количество успешных/неуспешных синхронизаций.
- `argocd_app_health_status` — здоровье приложения (Healthy/Degraded/Progressing).

### Нотификации

Argo CD интегрируется с多种 системами нотификаций:
- **Slack:** Уведомления о синхронизациях, ошибках, изменениях здоровья.
- **Email:** Отчеты о деплоях для аудита.
- **PagerDuty/Opsgenie:** Алерты на критические ошибки.
- **Webhook:** Интеграция с кастомными системами.

**Пример конфигурации нотификаций (argocd-notifications-cm):**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
data:
  trigger.on-sync-succeeded: |
    - when: app.status.operationState.phase in ['Succeeded']
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
    signingSecret: $slack-signing-secret
```

## Дополнительная информация

### Ограничения

- **Окна синхронизации:** Если настроены [Sync Windows](./sync_windows.md), автоматическая синхронизация будет заблокирована в запрещенные интервалы, даже если в Git появились изменения.
- **Зависшие операции:** Если процесс синхронизации "завис" (например, из-за PreSync Hook), новые изменения в Git не будут применяться до завершения или принудительной остановки текущей операции.
- **Лимит ресурсов:** Argo CD имеет внутренние лимиты на количество управляемых ресурсов. Для очень больших приложений (>1000 ресурсов) рекомендуется разбивать на несколько ApplicationSets.

### См. также

- **[Синхронизация Argo CD: Обзор](../../synchronization.md)** — общая архитектура процесса.
- **[Игнорирование различий](../ignore_differences.md)** — решение конфликтов с внешними контроллерами.
- **[Волны и хуки](./sync_waves_hooks.md)** — управление очередностью.
- **[Окна синхронизации](./sync_windows.md)** — временные ограничения.
- **[Прогрессивная синхронизация](./progressive_sync.md)** — поэтапная раскатка.
- **[Ручная синхронизация](./manual_sync.md)** — селективный деплой.
- [Официальная документация: Automated Sync](https://argo-cd.readthedocs.io/en/stable/user-guide/auto-sync/)
- [Официальная документация: Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
