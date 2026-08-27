# Argo CD — волны синхронизации (Sync Waves) и хуки (Hooks)

> **Актуальность (2026):** В версии Argo CD v3.x механизмы волн и хуков были дополнены поддержкой фаз удаления (**PreDelete**, **PostDelete**), что позволяет безопасно очищать внешние ресурсы (БД, DNS, облачные балансировщики). Использование волн в сочетании с кастомными Health Checks на Lua стало стандартом для управления жизненным циклом сложных инфраструктурных стеков.

## Предварительные требования

Перед настройкой волн синхронизации и хуков необходимо убедиться в следующем:

1. **Версия Argo CD:** v3.x (для поддержки PreDelete/PostDelete необходима v3.3+).
2. **Argo CD Application Controller:** Активен и работает.
3. **Понимание Sync Waves:** Базовое понимание аннотации `argocd.argoproj.io/sync-wave` и порядка применения ресурсов.
4. **Понимание Hooks:** Базовое понимание аннотации `argocd.argoproj.io/hook` и фаз жизненного цикла.
5. **Health Checks:** Базовое понимание проверок здоровья Argo CD. Для кастомных проверок требуется опыт написания Lua-скриптов.
6. **Kubernetes Jobs:** Понимание работы Kubernetes Jobs для настройки хуков.

## Определения

**Волны синхронизации (Sync Waves)** — механизм Argo CD для управления строгим порядком применения и обновления ресурсов. Позволяет группировать объекты в последовательные этапы, где переход к следующему этапу возможен только после достижения статуса `Healthy` всеми ресурсами текущего.

**Хуки (Hooks)** — специальные аннотации, позволяющие запускать эфемерные задачи (обычно Kubernetes Jobs) на ключевых этапах жизненного цикла синхронизации или удаления приложения.

**Health Gating (Барьер здоровья)** — принцип работы волн синхронизации, при котором контроллер блокирует выполнение следующей волны до тех пор, пока текущая не будет признана полностью работоспособной.

**Hook Delete Policies** — настройки, определяющие условия автоматической очистки ресурсов хука (например, после успешного завершения или перед началом новой синхронизации).

**PreDelete** — (v3.3+) Хук, выполняющийся перед удалением ресурсов. Используется для снапшотов БД, отзыва сертификатов, уведомлений.

**PostDelete** — (v3.3+) Хук, выполняющийся после завершения удаления ресурсов. Используется для удаления DNS-записей, очистки S3, уведомлений.

## Базовые концепции

### Механика волн синхронизации

Управление осуществляется через аннотацию `argocd.argoproj.io/sync-wave`.

- **Порядок выполнения:** Ресурсы с наименьшим числовым значением (например, `-10`) применяются первыми.
- **Диапазон:** Поддерживаются любые целые числа.
- **Значение по умолчанию:** `0`.
- **Sparse Numbering (Разреженная нумерация):** Рекомендуется использовать шаг (например, `-10`, `0`, `10`), чтобы иметь возможность вставить промежуточные ресурсы без изменения всего набора манифестов.
- **Одна волна:** Ресурсы с одинаковым значением `sync-wave` применяются параллельно (или в порядке, определенном Kubernetes).
- **Health Gating между волнами:** Контроллер блокирует выполнение следующей волны до тех пор, пока текущая не будет признана полностью работоспособной (все ресурсы `Healthy`).

### Жизненный цикл хуков

Хуки настраиваются через аннотацию `argocd.argoproj.io/hook`.

| Фаза | Описание | Применение |
| :--- | :--- | :--- |
| **PreSync** | Перед применением основных ресурсов. | Миграции БД, проверка зависимостей. |
| **Sync** | В процессе применения ресурсов. | Редкие случаи специфичной оркестрации. |
| **Skip** | Пропуск ресурса. | Исключение метаданных из GitOps-цикла. |
| **PostSync** | После того как все ресурсы стали `Healthy`. | Smoke-тесты, очистка кеша CDN. |
| **SyncFail** | Только при ошибке синхронизации. | Оповещения в Slack, сбор логов сбоя. |
| **PreDelete** | (v3.3+) Перед удалением ресурсов. | Снапшоты БД, отзыв сертификатов. |
| **PostDelete** | (v3.3+) После завершения удаления. | Удаление записей в DNS, очистка S3. |

### Взаимодействие с другими механизмами

#### Sync Waves и Sync Windows

Окна синхронизации ([Sync Windows](./sync_windows.md)) проверяются только перед запуском синхронизации. Если синхронизация уже выполняется и используется Sync Waves, окно не проверяется повторно для каждой волны. Это означает, что длинный деплой с несколькими волнами может продолжаться после закрытия окна.

**Важно:** Если PreSync Hook (миграция БД) начинается во время Allow окна и выполняется дольше, чем окно остается открытым, Hook не прерывается. Основные ресурсы будут применены после завершения Hook, даже если окно закрылось.

**Рекомендация:** Используйте `syncOverrun: true` в AppProject для приложений с длинными PreSync Hooks (миграции БД), чтобы гарантировать применение основных ресурсов после завершения Hook.

#### Sync Waves и Auto Sync

Автоматическая синхронизация ([Auto Sync](./auto_sync.md)) учитывает Sync Waves — ресурсы применяются в порядке, определенном аннотациями `argocd.argoproj.io/sync-wave`. Если PreSync Hook (миграция) завершается неуспешно, синхронизация прерывается и применяется политика retry.

**Важно:** Если `selfHeal=true` включен, контроллер будет пытаться исправить отклонения, но это не влияет на порядок волн. Waves управляют порядком применения, а `selfHeal` — исправлением отклонений.

#### Sync Waves и Manual Sync

Ручная синхронизация ([Manual Sync](./manual_sync.md)) также учитывает Sync Waves — ресурсы применяются в порядке, определенном аннотациями `argocd.argoproj.io/sync-wave`. Однако ручная синхронизация позволяет пропускать хуки:

```bash
# Синхронизация с выполнением PreSync Hooks
argocd app sync my-app

# Пропуск PreSync Hooks (опасно!)
argocd app sync my-app --hooks

# Синхронизация только PreSync Hooks (без основных ресурсов)
argocd app sync my-app --hooks-only
```

**Важно:** PreSync Hooks выполняются перед применением основных ресурсов. Если Hook завершается неуспешно, синхронизация прерывается.

#### Sync Waves и Progressive Sync

Прогрессивная синхронизация ([Progressive Sync](./progressive_sync.md)) работает на уровне приложений, а Sync Waves — на уровне ресурсов внутри приложения. Эти механизмы дополняют друг друга:

- **Волны:** Управляют порядком ресурсов *внутри* одного приложения (Namespace → Deployment → Service → Ingress).
- **Progressive Sync:** Управляет порядком *между* приложениями (Canary → Staging → Production).

**Пример:** При движении от Canary к Staging контроллер ApplicationSet сначала дождется `Healthy` для всех приложений Canary, затем запустит синхронизацию для Staging. Внутри каждого приложения ресурсы будут применяться в порядке, определенном Sync Waves.

#### Sync Waves и Ignore Differences

Игнорирование различий ([Ignore Differences](../ignore_differences.md)) работает на уровне приложения и не влияет на Sync Waves. Если настроены `ignoreDifferences`, контроллер не будет учитывать эти различия при проверке здоровья ресурсов.

**Важно:** Если ресурс имеет `ignoreDifferences` и находится в Degraded��态е из-за игнорируемых полей, контроллер не будет останавливать.progression.

#### Sync Waves и SelfHeal/Prune

Само-синхронизация (`selfHeal`) и удаление ресурсов (`prune`) работают независимо от Sync Waves. Waves управляют порядком применения, а `selfHeal` — исправлением отклонений, `prune` — удалением лишних ресурсов.

**Важно:** Если `selfHeal=true` включен, контроллер будет пытаться исправить отклонения для всех ресурсов, включая те, которые еще не были применены (в будущих волнах). Это может привести к конфликтам, если ресурс еще не существует.

#### Hooks и Retry

Политика retry ([Retry](./auto_sync.md)) применяется к синхронизации в целом, включая хуки. Если PreSync Hook завершается неуспешно, retry будет повторять попытки до достижения `limit`.

**Важно:** Retry не ограничивает время выполнения. Если синхронизация "зависла" (например, из-за PreSync Hook), retry будет повторять попытки до достижения `limit`. Настройте `--timeout` для ограничения времени.

## Практические сценарии

### Сценарий 1: Инфраструктурная пирамида (Sync Waves)

Обеспечение готовности базы до запуска приложения.

```yaml
# 1. Приоритетный ресурс (Namespace) - Волна -10
apiVersion: v1
kind: Namespace
metadata:
  name: my-stack
  annotations:
    argocd.argoproj.io/sync-wave: "-10"

# 2. Инфраструктура (ConfigMaps, Secrets, Operator CRs) - Волна -5
apiVersion: v1
kind: ConfigMap
metadata:
  name: db-config
  namespace: my-stack
  annotations:
    argocd.argoproj.io/sync-wave: "-5"

# 3. Приложение (Deployment, Service) - Волна 0 (Default)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
  namespace: my-stack
```

### Сценарий 2: Миграция базы данных с безопасной очисткой

Использование политики `BeforeHookCreation` гарантирует отсутствие конфликтов имен Job при перезапусках.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation, HookSucceeded
spec:
  template:
    spec:
      containers:
      - name: migrate
        image: migrations-tool:v2.4
        envFrom: [{configMapRef: {name: db-config}}]
      restartPolicy: Never
```

### Сценарий 3: Кастомный Health Check для операторов (Lua)

По умолчанию Argo CD считает CRD здоровым сразу после создания. Для работы волн с операторами (например, Postgres Operator) добавьте скрипт в `argocd-cm`.

```yaml
data:
  resource.customizations.health.acid.zalan.do_Postgresql: |
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

### Сценарий 4: PreDelete и PostDelete хуки

Безопасное удаление внешних ресурсов (БД, DNS, облачные балансировщики) при удалении приложения.

```yaml
# PreDelete: Снапшот БД перед удалением
apiVersion: batch/v1
kind: Job
metadata:
  name: db-snapshot
  annotations:
    argocd.argoproj.io/hook: PreDelete
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation, HookSucceeded
    argocd.argoproj.io/hook-weight: "1"
spec:
  template:
    spec:
      containers:
      - name: snapshot
        image: postgres:15
        command: ["pg_dump", "-U", "postgres", "-d", "mydb", "-F", "c", "-f", "/backup/snapshot.dump"]
        volumeMounts:
        - name: backup
          mountPath: /backup
      volumes:
      - name: backup
        persistentVolumeClaim:
          claimName: db-backup-pvc
      restartPolicy: Never
  backoffLimit: 1
---
# PostDelete: Удаление DNS-записи после удаления ресурсов
apiVersion: batch/v1
kind: Job
metadata:
  name: dns-cleanup
  annotations:
    argocd.argoproj.io/hook: PostDelete
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation, HookSucceeded
    argocd.argoproj.io/hook-weight: "1"
spec:
  template:
    spec:
      containers:
      - name: cleanup
        image: bitnami/kubectl:latest
        command: ["kubectl", "delete", "dnsrecord", "my-app.example.com", "-n", "kube-system"]
      restartPolicy: Never
  backoffLimit: 1
```

### Сценарий 5: Hooks с Retry и таймаутами

Настройка повторных попыток и таймаутов для хуков с долгим временем выполнения.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: long-migration
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation, HookSucceeded
spec:
  backoffLimit: 3
  activeDeadlineSeconds: 3600
  template:
    spec:
      containers:
      - name: migrate
        image: migrations-tool:v2.4
        command: ["./migrate.sh"]
        env:
        - name: TIMEOUT
          value: "3600"
      restartPolicy: Never
```

**Настройка таймаутов в `argocd-cm`:**

```yaml
data:
  # Таймаут для hook (в секундах)
  controller.process.timeout.seconds: "600"
  # Таймаут для repo server
  controller.repo.server.timeout.seconds: "120"
```

### Сценарий 6: Sync Waves с ApplicationSet

Использование Sync Waves в ApplicationSet для управления порядком ресурсов в каждом кластере.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: my-app-set
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

**Важно:** Sync Waves работают внутри каждого приложения, а Progressive Sync — между приложениями.

### Сценарий 7: Hooks и Sync Windows

Взаимодействие хуков с окнами синхронизации.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production-project
  namespace: argocd
spec:
  syncWindows:
  - kind: allow
    schedule: '0 9-17 * * 1-5'
    duration: 8h
    applications:
    - '*'
    manualSync: true
  - kind: deny
    schedule: '0 0 * * 0,6'
    duration: 24h
    applications:
    - '*'
  syncWindowOptions:
    syncOverrun: true  # Позволяет завершать длинные Hooks после закрытия окна
```

**Поведение:**
- Если PreSync Hook (миграция БД) начинается во время Allow окна и выполняется дольше, Hook не прерывается
- Основные ресурсы будут применены после завершения Hook, даже если окно закрылось
- Если `syncOverrun: false`, синхронизация прервется после закрытия окна

### Сценарий 8: Хуки для мультикластерных миграций

Использование хуков для координации миграций в мультикластерной среде.

```yaml
# PreSync Hook для миграции в каждом кластере
apiVersion: batch/v1
kind: Job
metadata:
  name: cluster-migrate
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation, HookSucceeded
    argocd.argoproj.io/sync-wave: "-1"
spec:
  template:
    spec:
      containers:
      - name: migrate
        image: migrations-tool:v2.4
        command: ["./migrate.sh"]
        env:
        - name: CLUSTER_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.labels['argocd.argoproj.io/cluster']
      restartPolicy: Never
---
# PostSync Hook для проверки после миграции
apiVersion: batch/v1
kind: Job
metadata:
  name: cluster-verify
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation, HookSucceeded
    argocd.argoproj.io/sync-wave: "1"
spec:
  template:
    spec:
      containers:
      - name: verify
        image: curlimages/curl:latest
        command: ["curl", "-f", "http://my-app:8080/health"]
      restartPolicy: Never
```

## Технический справочник

### Политики удаления хуков (`hook-delete-policy`)

| Политика | Описание | Рекомендация |
| :--- | :--- | :--- |
| **HookSucceeded** | Удалить, если Job завершился успешно. | Используйте всегда. |
| **HookFailed** | Удалить, если Job завершился с ошибкой. | Используйте для отладки. |
| **HookErrored** | Удалить, если Job завершился с ошибкой или был отменен. | Используйте для отладки. |
| **BeforeHookCreation** | (Рекомендуется) Удалить старый ресурс перед созданием нового. | Используйте всегда. |

### Полная таблица аннотаций

| Аннотация | Описание | Пример |
| :--- | :--- | :--- |
| `argocd.argoproj.io/sync-wave` | Определяет порядок применения ресурса. | `"10"`, `"-5"`, `"0"` |
| `argocd.argoproj.io/hook` | Определяет фазу жизненного цикла для хука. | `PreSync`, `PostSync`, `SyncFail`, `PreDelete`, `PostDelete` |
| `argocd.argoproj.io/hook-delete-policy` | Определяет условия автоматической очистки хука. | `BeforeHookCreation,HookSucceeded` |
| `argocd.argoproj.io/hook-weight` | Определяет порядок выполнения хуков внутри одной фазы (меньшее значение = первым). | `"1"`, `"10"`, `"100"` |

### Тюнинг таймаутов

Если хук (например, долгая миграция) превышает время ожидания, синхронизация прерывается. Настройте таймауты в `argocd-cm`:

```yaml
data:
  # Таймаут для hook (в секундах)
  controller.process.timeout.seconds: "600"
  # Таймаут для repo server
  controller.repo.server.timeout.seconds: "120"
  # Таймаут для операций kubectl
  controller.kubectl.timeout.seconds: "30"
```

**Важно:** Если хук выполняется дольше таймаута, синхронизация прерывается и применяется политика retry.

### CLI-команды

```bash
# Просмотр состояния Application
argocd app get my-app

# Просмотр Sync Waves для Application
argocd app get my-app -o yaml | grep -A 5 "sync-wave"

# Просмотр логов хука
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep -i "hook"

# Просмотр Job для хука
kubectl get jobs -n <namespace> -l app.kubernetes.io/name=my-app

# Принудительная синхронизация с выполнением PreSync Hooks
argocd app sync my-app

# Пропуск PreSync Hooks (опасно!)
argocd app sync my-app --hooks

# Синхронизация только PreSync Hooks (без основных ресурсов)
argocd app sync my-app --hooks-only

# Откат к предыдущей версии
argocd app rollback my-app <revision>

# Просмотр событий
kubectl get events -n <namespace> --field-selector involvedObject.name=my-app
```

## Диагностика и мониторинг

### Просмотр состояния хуков и волн

```bash
# Просмотр состояния Application
argocd app get my-app

# Просмотр Sync Waves для Application
argocd app get my-app -o yaml | grep -A 5 "sync-wave"

# Просмотр Job для хука
kubectl get jobs -n <namespace> -l app.kubernetes.io/name=my-app

# Просмотр Pod для хука
kubectl get pods -n <namespace> -l app.kubernetes.io/name=my-app
```

### Просмотр логов

```bash
# Логи контроллера (хуки и волны)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep -i "hook\|wave"

# Логи конкретного Job
kubectl logs -n <namespace> -l job-name=my-app-migrate

# Логи с фильтрацией по Application
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep my-app
```

### Prometheus метрики

| Метрика | Описание |
| :--- | :--- |
| `argocd_app_info` | Информация о приложении (включая статус здоровья). |
| `argocd_app_sync_total` | Общее количество синхронизаций. |
| `argocd_app_reconcile_total` | Количество реконсиляций. |
| `argocd_app_health_status` | Статус здоровья приложения. |
| `argocd_app_sync_duration_seconds` | Длительность синхронизации. |

**Пример PromQL-запроса для поиска хуков с ошибками:**
```promql
argocd_app_sync_total{phase="Error"} * on(name) group_left()
argocd_app_info{health_status="Degraded"} > 0
```

### Пошаговый алгоритм диагностики

1. **Проверьте состояние Application:** `argocd app get my-app` — найдите статус `Degraded` или `Progressing`.
2. **Просмотрите логи контроллера:** `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep -i "hook\|wave"` — найдите ошибки.
3. **Просмотрите Job для хука:** `kubectl get jobs -n <namespace> -l app.kubernetes.io/name=my-app` — проверьте статус Job.
4. **Просмотрите Pod для хука:** `kubectl get pods -n <namespace> -l app.kubernetes.io/name=my-app` — проверьте логи Pod.
5. **Исправьте проблему:** Исправьте конфигурацию в Git или откатите к предыдущей версии.

## Лучшие практики

### Настройка для Production

1. **Используйте `BeforeHookCreation` для всех хуков:** Это гарантирует отсутствие конфликтов имен Job при перезапусках.
2. **Используйте `HookSucceeded` для всех хуков:** Это гарантирует очистку Job после успешного завершения.
3. **Настройте таймауты для хуков:** Используйте `activeDeadlineSeconds` для ограничения времени выполнения Job.
4. **Используйте `hook-weight` для управления порядком хуков:** Меньшее значение = первым.
5. **Настройте Health Checks для операторов:** Используйте Lua-скрипты для проверки состояния CRD.

### Безопасность

- **Ограничьте `maxUpdate`:** Не используйте `100%` для Production — это может привести к глобальному прому.
- **Используйте `andOperator: true`:** Для точной фильтрации приложений по нескольким условиям.
- **Настройте RBAC:** Ограничьте доступ к ApplicationSet только авторизованным пользователям.
- **Мониторинг:** Настройте алерты на основе Prometheus-метрик для отслеживания деградации.

## Ограничения и edge cases

### Ограничения

1. **Health Gating между волнами:** Контроллер блокирует выполнение следующей волны до тех пор, пока текущая не будет признана полностью работоспособной. Если ресурс не становится `Healthy`, progression останавливается.
2. **PreSync Hooks выполняются перед применением основных ресурсов:** Если Hook завершается неуспешно, синхронизация прерывается.
3. **PostSync Hooks выполняются после того, как все ресурсы стали `Healthy`:** Если хотя бы один ресурс не становится `Healthy`, PostSync Hook не выполняется.
4. **PreDelete/PostDelete хуки (v3.3+):** Необходима Argo CD v3.3+ для поддержки.
5. **Таймауты хуков:** Если хук выполняется дольше таймаута, синхронизация прерывается.
6. **Retry для хуков:** Retry применяется к синхронизации в целом, включая хуки.
7. **Sync Waves и Progressive Sync:** Waves работают внутри приложения, Progressive Sync — между приложениями.

### Edge Cases

1. **Конфликт имен Job:** Если PreSync Hook создает Job с именем, которое уже существует, ошибка. Используйте `BeforeHookCreation`.
2. **Долгий PreSync Hook:** Если PreSync Hook (миграция БД) выполняется дольше таймаута синхронизации, операция прервется. Настройте `activeDeadlineSeconds`.
3. **PreDelete Hook не завершается:** Если PreDelete Hook "завис", удаление ресурсов не произойдет. Настройте таймаут и retry.
4. **PostDelete Hook не завершается:** Если PostDelete Hook "завис", очистка не произойдет. Настройте таймаут и retry.
5. **Health Check не становится Healthy:** Если кастомный Health Check не возвращает `Healthy`, progression останавливается. Проверьте Lua-скрипт.
6. **Синхронизация во время Deny окна:** Если синхронизация уже выполняется и используется Sync Waves, окно не проверяется повторно для каждой волны.
7. **Удаление ApplicationSet во время прогресса:** Если ApplicationSet удален во время выполняющейся синхронизации, операция завершится, но новые синхронизации будут невозможны.

## Дополнительная информация

### Важные нюансы
- **Health Gating:** Контроллер блокирует выполнение следующей волны до тех пор, пока текущая не будет признана полностью работоспособной.
- **PreDelete/PostDelete:** (v3.3+) Поддержка фаз удаления позволяет безопасно очищать внешние ресурсы.
- **Таймауты:** Настройте `activeDeadlineSeconds` для хуков с долгим временем выполнения.

### См. также
- **[Синхронизация Argo CD: Обзор](../../synchronization.md)** — механизмы и фазы.
- **[Автоматическая синхронизация](./auto_sync.md)** — использование волн в авто-деплое.
- **[Ручная синхронизация](./manual_sync.md)** — селективный деплой и аудит изменений.
- **[Окна синхронизации](./sync_windows.md)** — политики запрета деплоя в праздники и выходные.
- **[Прогрессивная синхронизация](./progressive_sync.md)** — поэтапная раскатка.
- **[Игнорирование различий](../ignore_differences.md)** — настройка jqPath и managedFieldsManagers.
- **[Диагностика Argo CD](../argocd_troubleshooting_and_monitoring.md)** — поиск причин зависания хуков.

### Ссылки
- [Argo CD Documentation: Resource Hooks](https://argo-cd.readthedocs.io/en/stable/user-guide/resource_hooks/)
- [Sync Waves Official Guide](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/)
- [Argo CD Health Assessment](https://argo-cd.readthedocs.io/en/stable/operator-manual/health/)
