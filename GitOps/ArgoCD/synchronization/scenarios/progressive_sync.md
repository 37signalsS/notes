# Argo CD — прогрессивная синхронизация (Rolling Sync)

> **Актуальность (2026):** В версии Argo CD v3.x прогрессивная синхронизация стала неотъемлемой частью контроллера **ApplicationSet**. Она позволяет управлять развертыванием приложений в масштабах сотен кластеров, обеспечивая безопасность через поэтапную раскатку и автоматическую блокировку при обнаружении деградации здоровья ресурсов.

## Предварительные требования

Перед настройкой прогрессивной синхронизации необходимо убедиться в следующем:

1. **Версия Argo CD:** v3.x (рекомендуется v3.5+ для полной поддержки `andOperator` и расширенного Health Gating).
2. **ApplicationSet Controller:** Активен и работает (в v3.x встроен по умолчанию).
3. **Генераторы:** Понимание работы генераторов ApplicationSet (List, Cluster, Git, Matrix) — от них зависит, какие приложения будут синхронизироваться.
4. **Метки кластеров (Labels):** Кластеры должны иметь правильные labels для фильтрации в `matchExpressions` (например, `environment: production`, `region: eu-central-1`).
5. **Health Checks:** Базовое понимание проверок здоровья Argo CD. Для кастомных проверок требуется опыт написания Lua-скриптов.
6. **AppProject:** Убедитесь, что проект создан и в него входят целевые приложения.

## Определения

**Прогрессивная синхронизация (Progressive Sync)** — стратегия развертывания в рамках `ApplicationSet`, при которой обновления применяются к группам приложений последовательно, а не одновременно.

**Rolling Sync** — конкретный алгоритм прогрессивной синхронизации, имитирующий поведение `RollingUpdate` в Kubernetes, но на уровне пар "Приложение-Кластер".

**Health Gating (Барьер здоровья)** — механизм контроля, который разрешает переход к следующему этапу (шагу) синхронизации только в том случае, если все приложения текущего этапа достигли статуса `Healthy`. Если хотя бы одно приложение переходит в `Degraded`, прогресс останавливается.

**Blast Radius (Радиус поражения)** — концепция ограничения масштаба потенциального сбоя. Прогрессивная синхронизация минимизирует этот радиус, обновляя сначала малую группу кластеров (Canary).

**Canary Deployment** — стратегия развертывания, при которой обновление сначала применяется к малой группе кластеров (Canary), и только после проверки здоровья распространяется на остальные.

**Progressive Rollout** — поэтапное распространение изменений по группам кластеров с контролем здоровья на каждом шаге.

## Базовые концепции

### Механика работы Rolling Sync

При активации стратегии `RollingSync` в `ApplicationSet`, процесс синхронизации меняется фундаментально:

1.  **Оркестрация вместо автоматики:** Стандартный флаг `syncPolicy.automated` внутри шаблона приложения игнорируется. Решение о запуске синхронизации принимает контроллер `ApplicationSet`.
2.  **Группировка по шагам (Steps):** Весь набор генерируемых приложений разбивается на логические группы с помощью селекторов `matchExpressions`.
3.  **Контроль параллелизма (maxUpdate):** Параметр определяет, сколько приложений *внутри одного шага* могут находиться в процессе обновления одновременно. Может быть числом (например, `1`) или процентом (`10%`).
4.  **Остановка при сбое:** Если приложение переходит в статус `Degraded`, контроллер останавливает прогресс. Дальнейшие шаги не выполняются, пока проблема не будет устранена (или пока приложение не будет исключено из набора).

### Включение и настройка

В Argo CD v3.x функционал включен по умолчанию. Однако для тонкой настройки контроллера используются параметры в `argocd-cmd-params-cm`:

```yaml
data:
  # Интервал проверки здоровья приложений для прогрессивной синхронизации
  applicationsetcontroller.progressive.sync.requeue.interval.seconds: "30"
```

### Взаимодействие с другими механизмами

#### Progressive Sync и Sync Windows

Окна синхронизации ([Sync Windows](./sync_windows.md)) проверяются для каждого приложения отдельно. Контроллер ApplicationSet не управляет окнами синхронизации. Если приложение попадает в Deny окно, оно не будет синхронизировано до открытия Allow окна.

**Важно:** Если во время выполнения шага одно из приложений попадает в Deny окно, контроллер ожидает его, не блокируя остальные приложения шага (если `maxUpdate > 1`).

#### Progressive Sync и Manual Sync

Ручная синхронизация ([Manual Sync](./manual_sync.md)) применяется к конкретному приложению, а не ко всем группам. Контроллер ApplicationSet не управляет ручными синхронизациями. Если вы вручную нажмете "Sync" на приложении, которое еще не подошло по очереди, оно будет синхронизировано, но это может нарушить логику `maxUpdate` текущего шага.

**Рекомендация:** Используйте ручную синхронизацию только для экстренных случаев. Для плановых обновлений полагайтесь на автоматический прогресс.

#### Progressive Sync и Hooks/Waves

Прогрессивная синхронизация работает на уровне приложений, а [Sync Waves и Hooks](./sync_waves_hooks.md) — на уровне ресурсов внутри приложения. Эти механизмы дополняют друг друга:

- **Волны:** Управляют порядком ресурсов *внутри* одного приложения (Namespace → Deployment → Service → Ingress).
- **Прогрессивная синхронизация:** Управляет порядком *между* приложениями (Canary → Staging → Production).

**Пример:** При движении от Canary к Staging контроллер ApplicationSet сначала дождется `Healthy` для всех приложений Canary, затем запустит синхронизацию для Staging. Внутри каждого приложения ресурсы будут применяться в порядке, определенном Sync Waves.

#### Progressive Sync и Auto Sync

Стандартный флаг `syncPolicy.automated` внутри шаблона приложения игнорируется. Автоматическая синхронизация ([Auto Sync](./auto_sync.md)) управляется контроллером ApplicationSet. Если вам нужна автоматическая синхронизация для конкретного приложения вне контекста progressive sync, используйте отдельный ApplicationSet без стратегии `RollingSync`.

#### Progressive Sync и Ignore Differences

Игнорирование различий ([Ignore Differences](../ignore_differences.md)) работает на уровне приложения и не влияет на прогрессивную синхронизацию. Если настроены `ignoreDifferences`, контроллер ApplicationSet не будет учитывать эти различия при проверке здоровья.

#### Progressive Sync и SelfHeal/Prune

Само-синхронизация (`selfHeal`) и удаление ресурсов (`prune`) не工作的 в контексте progressive sync, так как `syncPolicy.automated` игнорируется. Контроллер ApplicationSet управляет всем процессом. Если вам нужен `selfHeal` или `prune`, рассмотрите использование отдельного ApplicationSet без стратегии `RollingSync`.

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
    rollingSync:
      steps:
        # Шаг 1: Один кластер для проверки (Canary)
        - matchExpressions:
            - key: environment
              operator: In
              values: [canary]
          maxUpdate: 1
        
        # Шаг 2: Все тестовые окружения (параллельно)
        - matchExpressions:
            - key: environment
              operator: In
              values: [staging]
          # maxUpdate не указан = 100%
          
        # Шаг 3: Весь Production (по 10% за раз)
        - matchExpressions:
            - key: environment
              operator: In
              values: [production]
          maxUpdate: 10%
  template:
    metadata:
      name: '{{name}}-service'
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

### Сценарий 3: Использование Lua для кастомного здоровья

Если стандартных Health Checks Kubernetes недостаточно (например, для проверки прогрева кэша или состояния БД), используйте кастомные проверки в `argocd-cm`.

```yaml
data:
  resource.customizations.health.argoproj.io_Application: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.health ~= nil then
        hs.status = obj.status.health.status
        hs.message = obj.status.health.message
      end
    end
    return hs
```

### Сценарий 4: Progressive Sync с List Generator

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

### Сценарий 5: Progressive Sync с Git Generator

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

### Сценарий 6: Progressive Sync с Matrix Generator

Комбинирование двух генераторов для создания произвольных комбинаций "Приложение × Кластер".

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
- Создание комбинаций "N приложений × M кластеров"
- Динамическое добавление как приложений, так и кластеров
- Гибкость в настройке

### Сценарий 7: Health Gating с кастомными проверками

Использование Lua-скриптов для проверки состояния внешних ресурсов (БД, кэш, очереди).

```yaml
data:
  resource.customizations.health.postgresql_operator_PostgreSQL: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.PostgreSQLClusterStatus == "ClusterInHealthyState" then
        hs.status = "Healthy"
        hs.message = "PostgreSQL cluster is healthy"
      else
        hs.status = "Degraded"
        hs.message = "PostgreSQL cluster is not healthy"
      end
    end
    return hs
```

**Пример использования в ApplicationSet:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: db-dependent-app
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
      name: '{{name}}-db-app'
    spec:
      project: default
      source:
        repoURL: https://github.com/my-org/manifests.git
        targetRevision: HEAD
        path: db-app
      destination:
        server: '{{server}}'
        namespace: production
```

**Важно:** Кастомные Health Checks влияют на progression. Если хотя бы одно приложение переходит в `Degraded` из-за кастомной проверки, прогресс останавливается.

### Сценарий 8: Rollback при деградации

Действия при обнаружении деградации во время progressive sync.

**Симптомы:**
- Приложение переходит в статус `Degraded`
- Прогресс останавливается
- Следующие шаги не выполняются

**Действия:**

1. **Диагностика:**
```bash
# Просмотр состояния ApplicationSet
kubectl get applicationset <name> -n argocd -o yaml

# Просмотр состояния приложения
argocd app get <app-name>

# Просмотр логов контроллера
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep -i "degraded"
```

2. **Исправление:**
```bash
# Исправить проблему в Git (рекомендуется)
git commit -m "fix: correct resource configuration"
git push

# Или откатить к предыдущей версии
argocd app rollback <app-name> <revision>
```

3. **Принудительное продолжение (экстренное):**
```bash
# Принудительная синхронизация конкретного приложения
argocd app sync <app-name> --force

# Или удалить ApplicationSet и создать заново
kubectl delete applicationset <name> -n argocd
kubectl apply -f applicationset.yaml
```

**Важно:** Принудительное продолжение может привести к нестабильности. Используйте только в экстренных случаях.

### Сценарий 9: Принудительная синхронизация приложения

Обход progressive sync для конкретного приложения (экстренные случаи).

```bash
# 1. Найти приложение в ApplicationSet
argocd app list | grep <app-name>

# 2. Принудительная синхронизация
argocd app sync <app-name> --force

# 3. Проверить статус
argocd app get <app-name>
```

**Важно:** Это нарушает логику progressive sync. Используйте только для экстренных фиксов. После исправления вернитесь к стандартному процессу.

### Сценарий 10: Progressive Sync и Sync Windows

Взаимодействие progressive sync с окнами синхронизации.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: windows-aware-rollout
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
      project: production-project
      source:
        repoURL: https://github.com/my-org/manifests.git
        targetRevision: HEAD
        path: app
      destination:
        server: '{{server}}'
        namespace: production
```

**Поведение:**
- Если на AppProject настроены Deny окна, каждое приложение проверяется индивидуально
- Приложение в Deny окне не синхронизируется, но не блокирует остальные
- Если все приложения шага в Deny окне, прогресс останавливается

**Рекомендация:** Настройте Allow окна для рабочих часов, чтобы progressive sync работал в предсказуемое время.

## Технический справочник

### Параметры RollingSync

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `matchExpressions` | List | Стандартные селекторы Kubernetes для фильтрации приложений. |
| `maxUpdate` | Int/String | Лимит одновременно обновляемых приложений (число или %). |
| `andOperator` | Boolean | (v3.2+) Если `true`, требует совпадения всех условий в шаге. |

### Параметры контроллера ApplicationSet

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| `applicationsetcontroller.progressive.sync.requeue.interval.seconds` | Интервал проверки здоровья приложений | `30` |
| `applicationsetcontroller.namespaces` | Пространства имен для управления | `""` (все) |
| `applicationsetcontroller.requeue.duration` | Интервал повторной проверки | `3m` |

### CLI-команды

```bash
# Просмотр состояния ApplicationSet
kubectl get applicationset -n argocd
kubectl get applicationset <name> -n argocd -o yaml

# Просмотр приложений, созданных ApplicationSet
argocd app list -l app.kubernetes.io/part-of=<appset-name>

# Просмотр состояния конкретного приложения
argocd app get <app-name>

# Принудительная синхронизация (экстренное)
argocd app sync <app-name> --force

# Откат к предыдущей версии
argocd app rollback <app-name> <revision>

# Просмотр логов контроллера
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f

# Просмотр событий
kubectl get events -n argocd --field-selector involvedObject.name=<app-name>
```

## Диагностика и мониторинг

### Просмотр состояния ApplicationSet

```bash
# Список ApplicationSet
kubectl get applicationset -n argocd

# Состояние конкретного ApplicationSet
kubectl get applicationset <name> -n argocd -o yaml

# Список приложений, созданных ApplicationSet
argocd app list -l app.kubernetes.io/part-of=<appset-name>

# Состояние конкретного приложения
argocd app get <app-name>
```

### Просмотр логов контроллера

```bash
# Логи контроллера ApplicationSet
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller -f

# Логи контроллера приложений (ошибки синхронизации)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep -i "error\|degraded"

# Логи с фильтрацией по ApplicationSet
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller | grep <appset-name>
```

### Мониторинг через Prometheus

| Метрика | Описание |
| :--- | :--- |
| `argocd_app_info` | Информация о приложении (включая статус здоровья). |
| `argocd_app_sync_total` | Общее количество синхронизаций. |
| `argocd_app_reconcile_total` | Количество реконсиляций. |
| `argocd_app_health_status` | Статус здоровья приложения. |

**Пример PromQL-запроса для поиска деградированных приложений:**
```promql
argocd_app_info{health_status="Degraded"} * on(name) group_left()
argocd_app_sync_total{phase="Error"} > 0
```

### Пошаговая диагностика

1. **Проверьте ApplicationSet:** `kubectl get applicationset <name> -o yaml` — убедитесь, что стратегия `RollingSync` настроена правильно.
2. **Просмотрите приложения:** `argocd app list -l app.kubernetes.io/part-of=<appset-name>` — проверьте статус каждого приложения.
3. **Проверьте здоровье:** `argocd app get <app-name>` — найдите приложения в статусе `Degraded`.
4. **Просмотрите логи:** `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller` — найдите ошибки.
5. **Исправьте проблему:** Исправьте конфигурацию в Git или откатите к предыдущей версии.

## Лучшие практики

### Настройка для Production

1. **Используйте `maxUpdate: 1` для первого шага (Canary):** Обновляйте только один кластер для проверки.
2. **Используйте `maxUpdate: 10%` для Production:** Не обновляйте более 10% кластеров за раз.
3. **Настройте Health Checks:** Убедитесь, что кастомные проверки здоровья корректно отражают состояние приложения.
4. **Комбинируйте с Sync Windows:** Настройте Allow окна для рабочих часов, чтобы progressive sync работал в предсказуемое время.

### Безопасность

- **Ограничьте `maxUpdate`:** Не используйте `100%` для Production — это может привести к глобальному прому.
- **Используйте `andOperator: true`:** Для точной фильтрации приложений по нескольким условиям.
- **Настройте RBAC:** Ограничьте доступ к ApplicationSet только авторизованным пользователям.
- **Мониторинг:** Настройте алерты на основе Prometheus-метрик для отслеживания деградации.

### Масштабирование

- **Для больших инфраструктур:** Используйте Git Generator или Matrix Generator для динамического управления кластерами.
- **Для малых инфраструктур:** Используйте List Generator для точного контроля.
- **Разделяйте ApplicationSet:** Не используйте один ApplicationSet для всех приложений — разделите по функциональным группам.

## Ограничения и edge cases

### Ограничения

1. **Прогрессивная синхронизация работает только с ApplicationSet:** Невозможно использовать с отдельными Application.
2. **`syncPolicy.automated` игнорируется:** Автоматическая синхронизация управляется контроллером ApplicationSet.
3. **Зависимость от метаданных:** Прогрессивная синхронизация критически зависит от правильной разметки (labels) кластеров в Argo CD.
4. **Прерывание:** Если вы вручную нажмете "Sync" на приложении, которое еще не подошло по очереди, оно будет синхронизировано, но это может нарушить логику `maxUpdate` текущего шага.

### Edge Cases

1. **Конфликт с Manual Sync:** Ручная синхронизация приложения, которое еще не подошло по очереди, может нарушить логику `maxUpdate`.
2. **Приложение в Deny окне:** Если приложение попадает в Deny окно, оно не синхронизируется, но не блокирует остальные приложения шага.
3. **Нет правил Allow:** Если в проекте нет Allow окон, progressive sync работает всегда (при условии отсутствия Deny).
4. **Удаление ApplicationSet во время прогресса:** Если ApplicationSet удален во время выполняющейся синхронизации, операция завершится, но новые синхронизации будут невозможны.
5. **Конфликт с другими ApplicationSets:** Если ресурс управляется несколькими ApplicationSets, возникает конфликт. Используйте `FailOnSharedResource=true`.
6. **Лимит ресурсов:** Argo CD имеет внутренние лимиты на количество управляемых ресурсов. Для очень больших приложений (>1000 ресурсов) рекомендуется разбивать на несколько ApplicationSets.

## Дополнительная информация

### Важные нюансы
- **Зависимость от метаданных:** Прогрессивная синхронизация критически зависит от правильной разметки (labels) кластеров в Argo CD.
- **Прерывание:** Если вы вручную нажмете "Sync" на приложении, которое еще не подошло по очереди, оно будет синхронизировано, но это может нарушить логику `maxUpdate` текущего шага.

### См. также
- **[Синхронизация Argo CD: Обзор](../../synchronization.md)** — общие принципы.
- **[Автоматическая синхронизация](./auto_sync.md)** — стандартный режим деплоя.
- **[Ручная синхронизация](./manual_sync.md)** — селективный деплой и аудит изменений.
- **[Волны и хуки](./sync_waves_hooks.md)** — управление порядком ресурсов внутри одного кластера.
- **[Окна синхронизации](./sync_windows.md)** — политики запрета деплоя в праздники и выходные.
- **[Игнорирование различий](../ignore_differences.md)** — настройка jqPath и managedFieldsManagers.
- [Argo CD ApplicationSet: Rolling Sync Docs](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Progressive-Syncs/)

### Ссылки
- [Официальная документация: Progressive Syncs](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Progressive-Syncs/)
- [Argo CD ApplicationSet Generators](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Generators/)
- [Argo CD Health Assessment](https://argo-cd.readthedocs.io/en/stable/operator-manual/health/)
