# Deployment с GitOps

**Актуально для:** Kubernetes 1.30+ / Argo CD 2.12+

Интеграция Kubernetes Deployment с GitOps: Git как единственный источник правды (SSoT), автоматическая синхронизация через Argo CD, разрешение конфликтов с HPA, безопасный выкат конфигураций и SRE-протоколы отката.

## Предварительные требования (Prerequisites)

- Локальный или on-premise кластер Kubernetes (v1.30+).
- Установленный GitOps-контроллер (Argo CD v2.12+).
- Git-репозиторий с декларативными манифестами приложений (Kustomize или чистые манифесты).
- Утилиты командной строки `kubectl` и `argocd` CLI.
- Базовое понимание жизненного цикла и манифестов [Deployment](./index.md).

## 1. Определения

- **GitOps** — парадигма управления инфраструктурой и приложениями, при которой Git является единственным источником истины (Single Source of Truth, SSoT), а изменения применяются в кластер декларативно через непрерывный цикл согласования (Reconciliation Loop).
- **Reconciliation Loop** — бесконечный фоновый процесс контроллера GitOps, сравнивающий целевое состояние из Git (Target State) с фактическим состоянием ресурсов в etcd кластера (Live State).
- **Дрейф конфигурации (Drift)** — расхождение между декларированным состоянием манифеста в Git и реальным состоянием объекта в Kubernetes кластере (например, вследствие ручного выполнения `kubectl edit` или вмешательства мутирующих вебхуков).
- **Self-Healing** — механизм автоматического приведения состояния ресурса в кластере к состоянию в Git при обнаружении несанкционированного дрейфа.
- **Server-Side Apply (SSA)** — механизм Kubernetes API (активен по умолчанию начиная с 1.22), управляющий правами владения отдельными полями объектов через метаданные `metadata.managedFields`.
- **Sync Waves & Hooks** — механизмы управления фазами и строгой очередностью развертывания ресурсов в GitOps (например, запуск миграции БД строго до обновления Deployment).

> Общие концепции методологии GitOps, сравнение pull- и push-моделей см. в [GitOps Overview](../../../GitOps/GitOps_overview.md). Детальная архитектура контроллера представлена в [Argo CD Overview](../../../GitOps/ArgoCD/argocd_overview.md).

## 2. Базовые концепции

### Deployment в классическом CI/CD vs GitOps

| Аспект | Push-модель (Классический CI/CD) | Pull-модель (GitOps) |
|:-------|:--------------------------------|:---------------------|
| **Доступ к кластеру** | CI-раннер хранит `kubeconfig` с правами `cluster-admin` | Контроллер работает внутри кластера с изолированным ServiceAccount |
| **Источник изменений** | Императивная команда `kubectl apply` из пайплайна | Коммит/Merge Request в защищенную ветку Git-репозитория |
| **Реакция на ручные правки** | Нет реакции; ручной дрейф сохраняется до следующего билда | `selfHeal` автоматически восстанавливает декларированное состояние |
| **Управление откатом** | `kubectl rollout undo` (создает скрытый дрейф с Git) | `git revert` сохраняет прозрачную историю аудита изменений |
| **Статус выката** | Отслеживается скриптом CI (`kubectl rollout status`) | Отслеживается health-чеками контроллера в режиме реального времени |

### Архитектурный цикл согласования Deployment

```
1. Инженер коммитит манифест (новый образ / env) в ветку main
    ↓
2. GitOps-контроллер обнаруживает коммит (Git Polling или Webhook)
    ↓
3. Генерация манифестов: kustomize build / helm template
    ↓
4. Вычисление diff: сравнение Git-манифеста с живым Deployment в etcd
    ↓
5. Server-Side Apply: применение патча к Deployment
    ↓
6. Kubernetes kube-controller-manager выполняет RollingUpdate подов
    ↓
7. Контроллер GitOps оценивает условия (Progressing, Available, ReplicaFailure)
    ↓
8. Статус синхронизации: Synced & Healthy (или Degraded при ошибке)
```

---

## 3. Практические сценарии и конфигурация

### Сценарий 1: Argo CD Application для управления Deployment

Production-манифест `Application` с включенным Server-Side Apply, защитой от дрейфа и игнорированием динамических полей автоскейлинга.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-service
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://git.internal.company.lan/devops/k8s-apps.git
    targetRevision: main
    path: environments/production/billing-service
  destination:
    server: https://kubernetes.default.svc
    namespace: billing
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
      - RespectIgnoreDifferences=true
      - PruneLast=true
    retry:
      limit: 5
      backoff:
        duration: 10s
        factor: 2
        maxDuration: 3m
  ignoreDifferences:
    # Исключение поля replicas для бесконфликтной работы с HPA
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
```

### Сценарий 2: Разрешение конфликта между GitOps и HPA за `spec.replicas`

Наиболее частая проблема SRE при переводе Deployment на GitOps: если в манифесте Git зафиксировано `replicas: 3`, а `HorizontalPodAutoscaler` смасштабировал нагрузку до 8 реплик при всплеске трафика, GitOps-контроллер с `selfHeal: true` воспримет это как дрейф и принудительно уменьшит количество реплик обратно до 3, вызывая деградацию сервиса.

#### Решение через Server-Side Apply (Рекомендуемое)

В Kubernetes Server-Side Apply каждое поле отслеживается в `metadata.managedFields`. Если манифест Deployment в Git **вообще не содержит строки `replicas`**, контроллер GitOps не претендует на владение полем `.spec.replicas`. Владение переходит к контроллеру HPA (`kube-controller-manager`), управляющему суб-ресурсом `/scale`.

```yaml
# environments/production/billing-service/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-service
  namespace: billing
spec:
  # Поле replicas намеренно удалено! Начальное значение задается при первом запуске,
  # а последующее управление отдается HPA.
  selector:
    matchLabels:
      app: billing-service
  template:
    metadata:
      labels:
        app: billing-service
    spec:
      containers:
        - name: app
          image: registry.internal.company.lan/apps/billing:v2.4.1
          resources:
            requests:
              cpu: "250m"
              memory: "512Mi"
            limits:
              cpu: "1000m"
              memory: "1Gi"
```

> [!IMPORTANT]
> При использовании Argo CD необходимо активировать флаг `syncOptions: [RespectIgnoreDifferences=true]`, иначе фоновый цикл `selfHeal` проигнорирует директиву `ignoreDifferences` во время автоматического применения исправлений.

### Сценарий 3: Автоматический перезапуск Deployment при обновлении ConfigMap и Secret

В Kubernetes изменение содержимого `ConfigMap` или `Secret` **не инициирует** пересоздание подов в `Deployment`, если значения передаются через переменные окружения (`env`, `envFrom`) или монтируются через `subPath`. Для GitOps существует три надежных решения:

#### Вариант А: Kustomize configMapGenerator (Идиоматичный GitOps)
Kustomize добавляет суффикс с хешем содержимого к имени объекта (например, `billing-config-8f92m7c4ht`). Изменение любого параметра генерирует новое имя, что меняет ссылку в `Deployment.spec.template` и штатно запускает RollingUpdate без сторонних операторов.

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - deployment.yaml

configMapGenerator:
  - name: billing-config
    files:
      - config.properties
```

#### Вариант Б: Хеш-аннотация в шаблоне пода
Встраивание контрольной суммы конфигурационного файла в метаданные PodTemplateSpec:

```yaml
spec:
  template:
    metadata:
      annotations:
        checksum/config: "a8f5c2d3e9b17462fa189c450123ef89"
```

#### Вариант В: Использование Stakater Reloader
Если ConfigMap генерируется внешними инструментами (например, [External Secrets Operator](../../../GitOps/secrets_encryption.md)), на Deployment вешается аннотация контроллера Reloader:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-service
  annotations:
    configmap.reloader.stakater.com/reload: "billing-config"
    secret.reloader.stakater.com/reload: "billing-secrets"
```

> Подробнее о работе контроллера перезапуска см. в [Обзор Reloader](../../../Kubernetes/ToolsUtilities/reloader/reloader_overview.md).

### Сценарий 4: Порядок выката (Sync Waves & Hooks) для Deployment и миграций БД

В распределенных системах выкат новой версии Deployment требует предварительного применения миграций схемы базы данных. В Argo CD порядок задается волнами синхронизации:

```yaml
# Wave 0: Конфигурация и секреты
apiVersion: v1
kind: ConfigMap
metadata:
  name: billing-config
  annotations:
    argocd.argoproj.io/sync-wave: "0"
data:
  DB_HOST: "postgres-cluster.db.svc.cluster.local"
---
# Wave 1: Миграция базы данных (PreSync Hook)
apiVersion: batch/v1
kind: Job
metadata:
  name: billing-db-migrate-v2-4-1
  annotations:
    argocd.argoproj.io/sync-wave: "1"
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: registry.internal.company.lan/apps/billing-migrate:v2.4.1
---
# Wave 2: Deployment приложения
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-service
  annotations:
    argocd.argoproj.io/sync-wave: "2"
spec:
  replicas: 3
  progressDeadlineSeconds: 600
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: billing-service
    spec:
      containers:
        - name: app
          image: registry.internal.company.lan/apps/billing:v2.4.1
```

Если Job в Wave 1 завершится с ошибкой (non-zero exit code), Argo CD прерывает синхронизацию и **не запускает** Wave 2. Существующий Deployment продолжает обслуживать трафик на старой версии без простоя.

### Сценарий 5: Процедуры отката (Rollback Runbooks)

#### Вариант 1: Штатный откат через Git Revert (Рекомендуется)
Полностью сохраняет идеологию GitOps и аудит изменений в репозитории.

```bash
# 1. Просмотр последних коммитов в репозитории манифестов
git log --oneline -n 3
# → 9f2b8a1 (HEAD -> main) feat(billing): update image to v2.4.1
# → 4c7d0e3 fix(billing): adjust memory limits
# → 1a8b9c0 feat(billing): release stable v2.4.0

# 2. Создание коммита отката проблемного изменения
git revert 9f2b8a1 --no-edit

# 3. Отправка изменений в ветку main
git push origin main

# 4. Проверка автоматического запуска reconciliation
argocd app get billing-service
# → Sync Status: Synced to: 1a8b9c0
# → Health Status: Healthy
```

#### Вариант 2: Аварийный откат SRE при P1-инциденте (Emergency Rollback)
Если в кластере произошел критический сбой выката (Production Down), ожидание прохождения CI-пайплайна Git недопустимо. Использование `kubectl rollout undo` при активном `selfHeal: true` приведет к немедленной перезаписи отката контроллером GitOps.

Аварийный протокол SRE:

```bash
# Шаг 1: Немедленная приостановка автоматической синхронизации
argocd app set billing-service --sync-policy none

# Шаг 2: Выполнение мгновенного отката средствами Kubernetes
kubectl rollout undo deployment/billing-service -n billing

# Шаг 3: Мониторинг стабилизации подов
kubectl rollout status deployment/billing-service -n billing --timeout=60s
# → deployment "billing-service" successfully rolled out

# Шаг 4: Пост-инцидентная синхронизация репозитория (в Git)
# Инженер вносит git revert в репозиторий, пушит в main
git revert HEAD && git push origin main

# Шаг 5: Включение автоматической синхронизации обратно
argocd app set billing-service --sync-policy automated --auto-prune --self-heal
```

---

## 4. Операции и команды

Сводка команд системного администратора и SRE для диагностики и управления жизненным циклом Deployment в GitOps:

| Операция | Команда CLI | Назначение / Ожидаемый результат |
|:---------|:------------|:---------------------------------|
| **Проверка дрейфа** | `argocd app diff <app-name>` | Отображает разницу между Git и живым Deployment в кластере |
| **Принудительная синхронизация** | `argocd app sync <app-name> --force` | Принудительно применяет манифесты в обход зависших операций |
| **Прерывание операции выката** | `argocd app terminate-op <app-name>` | Останавливает зависший sync при блокировке волны хуков |
| **Проверка статуса подов** | `kubectl rollout status deployment/<app> -n <ns>` | Возвращает прогресс развертывания реплик |
| **Инспекция владельцев полей** | `kubectl get deployment <app> -n <ns> -o yaml` | Просмотр секции `metadata.managedFields` для выявления конфликтов SSA |

### Примеры выполнения команд с ожидаемым выводом

```bash
# 1. Проверка расхождений манифестов в Argo CD
argocd app diff billing-service
# → ===== apps/Deployment billing/billing-service ======
# → 131c131
# → <         image: registry.internal.company.lan/apps/billing:v2.4.1
# → ---
# → >         image: registry.internal.company.lan/apps/billing:v2.4.0

# 2. Проверка статуса приложения в Argo CD
argocd app get billing-service
# → Name:               billing-service
# → Project:            default
# → Server:             https://kubernetes.default.svc
# → Namespace:          billing
# → URL:                https://argocd.internal.company.lan/applications/billing-service
# → Repo:               https://git.internal.company.lan/devops/k8s-apps.git
# → Target:             main
# → Path:               environments/production/billing-service
# → Sync Status:        Synced to main (9f2b8a1)
# → Health Status:      Healthy
```

---

## 5. Устранение неполадок (Troubleshooting)

### Сценарий 1: OutOfSync Flapping из-за конфликта `spec.replicas` с HPA

- **Симптомы:** Приложение циклически переходит из `Synced` в `OutOfSync`. В истории событий Deployment каждую минуту фиксируются события масштабирования подов вверх и вниз (`ScalingReplicaSet`).
- **Причина:** В манифесте Git зафиксировано жесткое значение `spec.replicas`. Контроллер HPA меняет реплики в кластере, а GitOps-контроллер с флагом `selfHeal: true` перезаписывает их значением из Git.
- **Диагностика:**
  ```bash
  argocd app diff billing-service
  # → ===== apps/Deployment billing/billing-service ======
  # → <   replicas: 2
  # → ---
  # → >   replicas: 6
  ```
- **Решение:**
  1. Добавить в манифест `Application` секцию `ignoreDifferences` для `/spec/replicas` и флаг `RespectIgnoreDifferences=true`.
  2. Либо удалить строку `replicas:` из манифеста `Deployment` в Git при активном Server-Side Apply.

---

### Сценарий 2: Зависший Rollout и статус Degraded (`ProgressDeadlineExceeded`)

- **Симптомы:** Argo CD отображает статус приложения `Degraded`, синхронизация останавливается, последующие волны не запускаются.
- **Причина:** Новый Pod упал в `CrashLoopBackOff` или `ImagePullBackOff`. Контроллер Deployment исчерпал лимит времени `spec.progressDeadlineSeconds` (по умолчанию 600 секунд) и выставил условие `Progressing=False` с причиной `ProgressDeadlineExceeded`.
- **Диагностика:**
  ```bash
  kubectl get deployment billing-service -n billing -o jsonpath='{.status.conditions[?(@.type=="Progressing")]}'
  # → {"lastTransitionTime":"...","message":"ReplicaSet \"billing-service-674b8f\" has timed out progressing.","reason":"ProgressDeadlineExceeded","status":"False","type":"Progressing"}

  kubectl get pods -n billing -l app=billing-service
  # → billing-service-674b8f-kx9pt   0/1     CrashLoopBackOff   4          3m
  ```
- **Решение:**
  1. Исследовать логи контейнера: `kubectl logs -n billing billing-service-674b8f-kx9pt --previous`.
  2. Если ошибка в коде или конфигурации — выполнить `git revert` проблемного коммита.
  3. Для оперативного восстановления запустить аварийный протокол отката (см. Сценарий 6).

---

### Сценарий 3: Случайное удаление Deployment при активном `prune: true`

- **Симптомы:** В кластере внезапно удалился весь Deployment и все его поды, трафик сервиса полностью деградировал.
- **Причина:** Разработчик случайно удалил файл манифеста или переименовал директорию в Git. GitOps-контроллер обнаружил отсутствие ресурса в целевой ветке и выполнил автоматический `prune` (каскадное удаление).
- **Диагностика:**
  ```bash
  kubectl get events -n billing --sort-by='.metadata.creationTimestamp' | grep -i delete
  # → 2m   Normal   Killing   pod/billing-service-589f8   Stopping container app
  # → 2m   Normal   SuccessfulDelete   replicaset/billing-service-589f8
  ```
- **Решение:**
  1. Восстановить файл манифеста в Git: `git checkout HEAD~1 -- environments/production/billing-service/deployment.yaml && git commit -m "fix: restore deployment" && git push`.
  2. **Превентивная защита:** Установить на манифест критичного ресурса аннотацию защиты от prune:
     ```yaml
     metadata:
       annotations:
         argocd.argoproj.io/sync-options: Prune=false
     ```

---

### Сценарий 4: Конфликт владения полями Server-Side Apply (`ApplyPatchesConflict`)

- **Симптомы:** Ошибка синхронизации `Apply failed with status 409: ApplyPatchesConflict`.
- **Причина:** Другой контроллер или пользователь применил изменения через классический `kubectl apply` с менеджером полей `kubectl-client-side-apply`, перекрыв поля, которыми управляет GitOps (`argocd-application-controller`).
- **Диагностика:**
  ```bash
  kubectl get deployment billing-service -n billing -o yaml | grep -A 10 managedFields
  # → manager: kubectl-client-side-apply
  # → operation: Update
  ```
- **Решение:**
  Выполнить принудительное переопределение владения полем флагом force:
  ```bash
  argocd app sync billing-service --force
  ```
  В манифесте Argo CD зафиксировать опцию:
  ```yaml
  syncOptions:
    - ServerSideApply=true
    - Force=false # Использовать Force только точечно при явных конфликтах
  ```

---

### Сценарий 5: Рассинхронизация версии ConfigMap и Deployment (Race Condition)

- **Симптомы:** Новые поды стартуют со старыми конфигурационными файлами или падают с `CreateContainerConfigError` из-за отсутствия новых ключей.
- **Причина:** Deployment и ConfigMap находятся в одной фазе синхронизации без фиксации порядка, либо используется монтирование существующего ConfigMap без смены имени.
- **Решение:**
  1. Использовать Kustomize `configMapGenerator` (генерация уникального имени по хешу).
  2. Разделить ресурсы по волнам синхронизации: ConfigMap — Wave `0`, Deployment — Wave `1` (см. Сценарий 5).

---

## 6. Рекомендации и лучшие практики (Best Practices)

1. **Исключение runtime-полей из Git-репозитория:**
   - Никогда не фиксируйте в Git поля, управляемые ядром Kubernetes или операторами: `status`, `metadata.resourceVersion`, `metadata.uid`, `metadata.generation`, `metadata.creationTimestamp`.
   - Если количество реплик контролируется `HPA`, исключите поле `spec.replicas` из манифеста Git.
2. **Идемпотентность и иммутабельность конфигураций:**
   - Предпочитайте генерацию иммутабельных ConfigMaps (`configMapGenerator`) вместо ручного редактирования `ConfigMap` на месте. Это гарантирует детерминированный откат: возврат хеша в Git возвращает точную копию конфигурации.
3. **Безопасное удаление (Prune Protection):**
   - Для критически важных рабочих нагрузок в продакшене активируйте опцию `PruneLast=true` (удаление старых ресурсов только после успешного выката новых).
   - Включайте аннотацию `argocd.argoproj.io/sync-options: Prune=false` на базах данных и stateful-компонентах.
4. **Валидация манифестов в CI перед коммитом:**
   - Интегрируйте в pre-commit или pull-request проверки линтеры `kubeconform` со строгой валидацией Kubernetes OpenAPI схем, исключая синтаксические ошибки манифестов до их попадания в Git.
5. **Согласование таймаутов:**
    - Значение `spec.progressDeadlineSeconds` в манифесте Deployment (рекомендуется от 300 до 600 секунд) должно быть меньше общего таймаута синхронизации GitOps-оператора (`retry.backoff.maxDuration` в Argo CD), чтобы контроллер успел получить достоверный статус ошибки выката до разрыва сессии.
6. **Zero-Downtime параметры Deployment:**
   - Для гарантированной непрерывности обслуживания в производственной среде задавайте `strategy.rollingUpdate.maxUnavailable: 0` и `strategy.rollingUpdate.maxSurge: 25%` (или `1`), а также корректные `readinessProbe` и обработку сигнала `SIGTERM` в контейнерах (`terminationGracePeriodSeconds`).

---

## 7. Дополнительная информация

### См. также
- [Deployment манифест](./deployment_manifest.md) — детальное описание полей и спецификации `apps/v1/Deployment`.
- [Устранение неполадок Deployment](./troubleshooting.md) — диагностика циклов RollingUpdate, причин `CrashLoopBackOff` и зондов готовности.
- [Продвинутые стратегии отката](./advanced_rollback_strategies.md) — техники automated rollback по метрикам.
- [Progressive Delivery](./progressive_delivery.md) — интеграция Canary и Blue-Green выкатов через Argo Rollouts и Flagger.
- [Управление секретами в GitOps](../../../GitOps/secrets_encryption.md) — Mozilla SOPS, Sealed Secrets и External Secrets Operator.
- [Синхронизация в Argo CD](../../../GitOps/ArgoCD/synchronization.md) — детальный разбор фаз, волн и хуков синхронизации.
- [Игнорирование различий (Ignore Differences)](../../../GitOps/ArgoCD/synchronization/ignore_differences.md) — тонкая настройка дрейфа ресурсов.
- [Обзор Reloader](../../../Kubernetes/ToolsUtilities/reloader/reloader_overview.md) — контроллер перезапуска подов при обновлении секретов и конфигураций.
- [Kustomize Overview](../../../Kubernetes/ToolsUtilities/kustomize/kustomize_overview.md) — шаблонизация и оверлеи манифестов для сред staging и production.

