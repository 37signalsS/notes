# Kargo: promotion-пайплайны продвижения артефактов

**Актуально для:** Kargo v1.11.x – v1.12.x, Argo CD v2.13.x – v3.x, Kubernetes 1.29–1.32+

Kargo — специализированный оркестратор продвижения артефактов (promotion engine) в экосистеме GitOps, переданный в CNCF. Он устраняет критический архитектурный разрыв между CI и CD («CD для CD»), формализуя жизненный цикл релизов при перемещении через последовательность сред (например, `dev` → `staging` → `prod`).

В классическом GitOps-стеке продвижение версий часто реализуется разрозненными скриптами в CI-конвейерах (`yq`/`sed`), ручными Pull Request или внешними ботами. Это приводит к потере сквозного аудита, рассинхронизации зависимых микросервисов и риску модификации артефакта после его валидации на тестовых контурах. Kargo обеспечивает неизменяемость наборов артефактов (digest pinning), автоматический контроль качества (quality gates) и декларативное управление переходом версий.

## Определения

- **Warehouse** — Kubernetes-ресурс источника артефактов. Отслеживает обновления в OCI-реестрах (образы), Git-репозиториях (манифесты, чарты) и Helm-репозиториях, формируя новые выпуски артефактов.
- **Freight** — неизменяемый снимок (snapshot) набора совместимых артефактов: digest контейнерного образа + git-коммит + версия Helm-чарта. Идентифицируется криптографическим ID и человекочитаемым алиасом (например, `auth-v2.4.1`). Именно Freight, а не мутабельный образный тег, перемещается между стадиями.
- **Stage** — изолированное окружение или логический контур (`dev`, `staging`, `prod`), управляемый как ресурс Kargo. Содержит правила отбора Freight (`requestedFreight`), шаблон шагов промоушена (`promotionTemplate`) и механизмы валидации (`verification`).
- **Promotion** — запись о факте и процессе применения конкретного Freight на определенном Stage. Выполняет цепочку декларативных шагов (обновление Git, применение манифестов, запуск синхронизации в Argo CD) и отслеживает статус выполнения.
- **PromotionStep** — атомарный шаг промоушена в `promotionTemplate`, выполняемый встроенным раннером Kargo (`git-clone`, `kustomize-set-image`, `helm-update-image`, `yaml-update`, `argocd-update`, `git-commit`, `git-push`).
- **PromotionTask** / **ClusterPromotionTask** — переиспользуемые шаблоны последовательностей шагов промоушена на уровне проекта или всего кластера.
- **Verification** — процесс автоматической валидации окружения после выкатки Freight (запуск Kubernetes Jobs или интеграция с Argo Rollouts `AnalysisTemplate`/`AnalysisRun`).
- **Auto-promotion vs Approval** — политика продвижения: стадия забирает доступный Freight автоматически либо блокирует его до явного одобрения инженером/авторизованной системой (`approvalPolicy`).

## Архитектура и базовые концепции

### Проблема «CD для CD» в GitOps

При разделении обязанностей CI-система собирает артефакты, а GitOps-контроллер (Argo CD / Flux) синхронизирует состояние кластера с Git. Промежуточный этап — выбор артефакта, прошедшего тестирование, и обновление конфигурации следующего окружения — оказывается слабым звеном:

| Проблема самодельных скриптов | Решение в Kargo |
| :--- | :--- |
| **Мутабельность тегов**: скрипт обновляет тег `v1.2.0`, но базовый слой или digest могли измениться | **Неизменяемость Freight**: фиксируется побайтовый sha256-digest, гарантируя идентичность кода во всех средах |
| **Разобщенность компонентов**: образ обновился, а зависимый Helm-чарт или схема БД — нет | **Составной Freight**: связывает образ, чарт и конфигурационный коммит в единую неделимую сущность |
| **Отсутствие гейтов в Git**: коммит в `prod` не учитывает реальное состояние метрик в `staging` | **Декларативные гейты**: `Stage prod` физически не принимает Freight, пока он не прошел `Verification` в `staging` |
| **Фрагментарный аудит**: история промоушенов теряется в логах десятков CI-пайплайнов | **Единый CRD-аудит**: каждый переход зафиксирован в объектах `Promotion` с точным временем, автором и хешами |

### Архитектурная модель Kargo

Kargo спроектирован как cloud-agnostic Kubernetes-native контроллер:

```text
 ┌────────────────────────────────────────────────────────────────────────┐
 │                           Kubernetes Cluster                           │
 │                                                                        │
 │  ┌───────────────────────┐              ┌───────────────────────────┐  │
 │  │    Kargo Web UI       │              │     Kargo API Server      │  │
 │  │ (визуализация графа)  │◄────────────►│ (OIDC / K8s RBAC / gRPC)  │  │
 │  └───────────────────────┘              └─────────────┬─────────────┘  │
 │                                                       │                │
 │                                         ┌─────────────▼─────────────┐  │
 │  ┌───────────────────────┐              │      Kargo Controller     │  │
 │  │ External Secrets /    │─────────────►│    (reconciliation loop)  │  │
 │  │ K8s Secrets (creds)   │              └─────────────┬─────────────┘  │
 │  └───────────────────────┘                            │                │
 └───────────────────────────────────────────────────────┼────────────────┘
                                                         │
       ┌───────────────────────────┬─────────────────────┴─────────────┐
       ▼                           ▼                                   ▼
┌──────────────┐          ┌─────────────────┐                ┌──────────────────┐
│ Harbor OCI   │          │ Git (GitLab/    │                │ Argo CD API      │
│ (образы/     │          │ Gitea/GitHub)   │                │ (контроль        │
│ Helm-чарты)  │          │ (инфра-репо)    │                │ приложений/синк) │
└──────────────┘          └─────────────────┘                └──────────────────┘
```

1. **Kargo Controller**:
   - Опрашивает источники через `Warehouse` (или принимает webhook-события), формирует `Freight`.
   - Проверяет условия готовности стадий, обрабатывает `autoPromotion` и `approvalPolicy`.
   - При старте промоушена создает временное рабочее пространство, исполняет шаги `PromotionStep` (клонирование Git, правка Kustomize/Helm, коммит, пуш, вызов Argo CD API).
   - Запускает `Verification` (AnalysisRun / Job) и переводит `Freight` в статус проверенного.
2. **Kargo API Server**: предоставляет gRPC/REST API для Kargo CLI и веб-интерфейса, валидирует права через нативный Kubernetes RBAC или внешние OIDC-провайдеры (Dex, Keycloak).
3. **Хранение состояния**: Kargo полностью безлик (stateless) по отношению к локальным дискам; все состояние хранится в Custom Resources в Kubernetes etcd (`Warehouse`, `Stage`, `Freight`, `Promotion`). Для систем с высокой нагрузкой контроллер поддерживает шардирование через метку `kargo.akuity.io/shard`.

### Модель жизненного цикла Freight

Граф движения артефактов описывается зависимостями между объектами `Stage`:

```text
   Warehouse: billing-api (Harbor OCI + Git Config)
                         │
                         ▼
        Freight: billing-v1.4.2 (digest: sha256:7a8b... + commit: f2c4...)
                         │
                         ├────────────────────────────────────────┐
                         ▼ (auto-promotion)                       │
                  Stage: dev                                      │
               (argocd-update dev)                                │
                         │                                        │
                         ▼ (auto-promotion после успеха dev)      │
                  Stage: staging                                  │
            (kustomize edit + argocd-update)                      │
                         │                                        │
                         ▼ (Verification: AnalysisTemplate)       ▼
                  [Prometheus Gate]                      [Заблокировано до
                   (успех >= 99.5%)                       прохождения staging]
                         │                                        │
                         ▼ (ручной approval инженера)             │
                  Stage: prod ◄───────────────────────────────────┘
            (git write-back + argocd sync)
```

Каждая стадия определяет входящие источники (`requestedFreight.sources`):
- `direct: true` — артефакты поступают напрямую из `Warehouse` (характерно для `dev`).
- `stages: [staging]` — артефакты могут поступить на стадию только после того, как они были успешно применены и верифицированы на предыдущей стадии.

## Практические сценарии и конфигурация

### Предварительные требования и настройка учетных данных

Для работы в закрытом (on-premises) контуре Kargo требуются права на чтение OCI-реестра, чтение/запись в Git и доступ к API Argo CD.

Все секреты размещаются в целевом пространстве имен Kargo Project (помеченном лейблом `kargo.akuity.io/project: "true"`) и маркируются лейблом типа учетных данных `kargo.akuity.io/cred-type`:

```yaml
# 1. Секрет доступа к частному реестру Harbor (чтение образов)
apiVersion: v1
kind: Secret
metadata:
  name: harbor-registry-creds
  namespace: kargo-demo
  labels:
    kargo.akuity.io/cred-type: image
type: kubernetes.io/basic-auth
stringData:
  repoURL: harbor.internal/billing/api
  username: robot-kargo
  password: HarborRobotTokenSecret123
---
# 2. Секрет доступа к GitLab для записи изменений в инфра-репозиторий (SSH-ключ)
apiVersion: v1
kind: Secret
metadata:
  name: gitlab-repo-creds
  namespace: kargo-demo
  labels:
    kargo.akuity.io/cred-type: git
type: Opaque
stringData:
  repoURL: git@gitlab.internal:platform/fleet-infra.git
  sshPrivateKey: |
    -----BEGIN OPENSSH PRIVATE KEY-----
    b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAABlwAAAAdzc2gtcn
    ... (приватный ключ с правами push в ветки промоушена) ...
    -----END OPENSSH PRIVATE KEY-----
---
# 3. Секрет доступа к Argo CD API (токен сервисного аккаунта Argo CD)
apiVersion: v1
kind: Secret
metadata:
  name: argocd-creds
  namespace: kargo-demo
  labels:
    kargo.akuity.io/cred-type: argocd
type: Opaque
stringData:
  serverURL: https://argocd.internal
  token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
  insecureSkipTLSVerify: "false"
```

---

### Сценарий 1: Декларативная цепочка dev → staging → prod

Определим пайплайн продвижения микросервиса `billing-api`:
- `Warehouse` отслеживает стабильные семантические версии `^1.0.0` в Harbor.
- `dev` получает новые Freight автоматически через прямой API-вызов `argocd-update`.
- `prod` требует обязательного прохождения `staging` и ручного одобрения дежурным инженером.

```yaml
apiVersion: kargo.akuity.io/v1alpha1
kind: Warehouse
metadata:
  name: billing-api
  namespace: kargo-demo
spec:
  interval: 5m0s
  subscriptions:
    - image:
        repoURL: harbor.internal/billing/api
        imageSelectionStrategy: SemVer
        constraint: ^1.0.0
        discoveryLimit: 10
---
apiVersion: kargo.akuity.io/v1alpha1
kind: Stage
metadata:
  name: dev
  namespace: kargo-demo
spec:
  requestedFreight:
    - origin:
        kind: Warehouse
        name: billing-api
      sources:
        direct: true
  promotionTemplate:
    spec:
      steps:
        - uses: argocd-update
          as: update-dev-app
          config:
            appName: billing-dev
            appNamespace: argocd
            imageUpdates:
              - image: harbor.internal/billing/api
                useDigest: true
---
apiVersion: kargo.akuity.io/v1alpha1
kind: Stage
metadata:
  name: staging
  namespace: kargo-demo
spec:
  requestedFreight:
    - origin:
        kind: Warehouse
        name: billing-api
      sources:
        stages:
          - dev
  promotionTemplate:
    spec:
      steps:
        - uses: argocd-update
          as: update-staging-app
          config:
            appName: billing-staging
            appNamespace: argocd
            imageUpdates:
              - image: harbor.internal/billing/api
                useDigest: true
---
apiVersion: kargo.akuity.io/v1alpha1
kind: Stage
metadata:
  name: prod
  namespace: kargo-demo
spec:
  requestedFreight:
    - origin:
        kind: Warehouse
        name: billing-api
      sources:
        stages:
          - staging
  promotionTemplate:
    spec:
      steps:
        - uses: argocd-update
          as: update-prod-app
          config:
            appName: billing-prod
            appNamespace: argocd
            imageUpdates:
              - image: harbor.internal/billing/api
                useDigest: true
```

Команды управления жизненным циклом через CLI:

```bash
# Просмотр обнаруженных артефактов на складе
kargo get warehouses --project kargo-demo
# → NAME          DISCOVERED ARTIFACTS   AGE
# → billing-api   10 images              42m

# Список доступных наборов Freight
kargo get freight --project kargo-demo
# → NAME       ALIAS         ORIGIN        DISCOVERED   STAGE(S)
# → a8f2c1b4   app-1.4.2     billing-api   15m ago      dev, staging
# → c9d0e1f3   app-1.4.1     billing-api   2d ago       dev, staging, prod

# Состояние стадий конвейера
kargo get stages --project kargo-demo
# → NAME      CURRENT FREIGHT   HEALTHY   PHASE
# → dev       app-1.4.2         True      Ready
# → staging   app-1.4.2         True      Ready
# → prod      app-1.4.1         True      Ready

# Одобрение (approval) проверенного на staging артефакта app-1.4.2 для выкатки в прод
kargo approve freight app-1.4.2 --stage prod --project kargo-demo
# → Freight "app-1.4.2" approved for Stage "prod" in Project "kargo-demo"

# Запуск промоушена одобренного Freight в prod
kargo promote --stage prod --freight app-1.4.2 --project kargo-demo
# → Promotion "prod.01jb8..." created for Stage "prod"
```

---

### Сценарий 2: Автоматическая верификация качества (Verification Gate)

Чтобы исключить попадание нестабильного релиза в `prod`, стадия `staging` выполняет автоматическую верификацию через `AnalysisTemplate` (переиспользование шаблонов метрик Argo Rollouts) либо запуск верификационного Job:

```yaml
apiVersion: kargo.akuity.io/v1alpha1
kind: Stage
metadata:
  name: staging
  namespace: kargo-demo
spec:
  requestedFreight:
    - origin:
        kind: Warehouse
        name: billing-api
      sources:
        stages:
          - dev
  promotionTemplate:
    spec:
      steps:
        - uses: argocd-update
          as: sync-staging
          config:
            appName: billing-staging
            appNamespace: argocd
  verification:
    analysisTemplates:
      - name: prometheus-error-rate-gate
    args:
      - name: service-name
        value: billing-api
      - name: prometheus-url
        value: http://prometheus-k8s.monitoring.svc.cluster.local:9090
```

Манифест `AnalysisTemplate` в пространстве имен проекта (проверяет метрики приложения в течение 5 минут после деплоя):

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: prometheus-error-rate-gate
  namespace: kargo-demo
spec:
  metrics:
    - name: http-error-rate
      interval: 1m
      count: 5
      failureLimit: 1
      successCondition: result[0] <= 0.005
      provider:
        prometheus:
          address: http://prometheus-k8s.monitoring.svc.cluster.local:9090
          query: |
            sum(rate(http_requests_total{job="billing-api",status=~"5.*"}[2m]))
            /
            sum(rate(http_requests_total{job="billing-api"}[2m]))
```

Поведение при верификации:
1. Контроллер Kargo запускает ресурс `AnalysisRun` при успешном завершении промоушена.
2. Стадия переходит в фазу `Verifying`.
3. Если PromQL-запрос возвращает ошибку > 0.5%, `AnalysisRun` переходит в `Failed`, статус стадии становится `VerificationFailed`.
4. Freight `app-1.4.2` помечается как непригодный к передаче downstream; стадия `prod` физически не увидит его в списке разрешенных к аппруву.

---

### Сценарий 3: Git Write-back в Kustomize-оверлей (Rendered Manifests)

Если в архитектуре запрещены прямые API-манипуляции с Argo CD и требуется строгий аудит через Git-коммиты, промоушен настраивается как последовательность шагов в `promotionTemplate`:
1. Клонирование инфраструктурного репозитория (`git-clone`).
2. Фиксация digest в `kustomization.yaml` целевого окружения (`kustomize-set-image`).
3. Создание коммита с метаданными релиза (`git-commit`).
4. Отправка ветки в GitLab (`git-push`).
5. Ожидание завершения синхронизации в Argo CD (`argocd-update`).

```yaml
apiVersion: kargo.akuity.io/v1alpha1
kind: Stage
metadata:
  name: prod
  namespace: kargo-demo
spec:
  requestedFreight:
    - origin:
        kind: Warehouse
        name: billing-api
      sources:
        stages:
          - staging
  promotionTemplate:
    spec:
      steps:
        # Шаг 1: Клонирование GitOps-репозитория
        - uses: git-clone
          as: clone-infra
          config:
            repoURL: git@gitlab.internal:platform/fleet-infra.git
            checkout:
              - branch: main
                path: ./repo

        # Шаг 2: Обновление image digest в Kustomize-оверлее прода
        - uses: kustomize-set-image
          as: update-overlay
          config:
            path: ./repo/environments/prod
            images:
              - image: harbor.internal/billing/api
                digest: ${{ imageFrom(warehouse("billing-api")).Digest }}

        # Шаг 3: Формирование детерминированного коммита
        - uses: git-commit
          as: commit-changes
          config:
            path: ./repo
            message: "kargo(prod): promote freight ${{ freight.alias }} to production"
            author:
              name: "Kargo Automation"
              email: "kargo-bot@internal.corp"

        # Шаг 4: Пуш изменений в защищенную ветку
        - uses: git-push
          as: push-changes
          config:
            path: ./repo
            targetBranch: main

        # Шаг 5: Инициализация синка в Argo CD и ожидание состояния Synced + Healthy
        - uses: argocd-update
          as: wait-argo-sync
          config:
            appName: billing-prod
            appNamespace: argocd
```

Результат: в истории GitLab появляется точная цепочка коммитов вида `kargo(prod): promote freight app-1.4.2 to production` с привязкой к конкретному sha256-хешу образа из Harbor.

---

### Сценарий 4: Экстренная остановка (Freeze) и Rollback

При обнаружении деградации продакшена SRE-команда выполняет экстренное управление через Kargo CLI:

```bash
# 1. Заморозка стадии prod (блокировка любых auto-promotion и ручных запусков)
kargo pause stage prod --project kargo-demo
# → Stage "prod" paused in Project "kargo-demo"

# 2. Поиск последнего стабильного заверенного Freight
kargo get freight --project kargo-demo
# → NAME       ALIAS         ORIGIN        DISCOVERED   STAGE(S)
# → a8f2c1b4   app-1.4.2     billing-api   45m ago      dev, staging, prod (деградирует)
# → c9d0e1f3   app-1.4.1     billing-api   2d ago       dev, staging, prod (стабилен)

# 3. Откат продакшена на артефакт app-1.4.1
kargo promote --stage prod --freight app-1.4.1 --project kargo-demo
# → Promotion "prod.01jb89xyz" created for Stage "prod"

# 4. Проверка статуса выполнения отката
kargo get promotions --stage prod --project kargo-demo
# → NAME             STAGE   FREIGHT     PHASE       AGE
# → prod.01jb89xyz   prod    app-1.4.1   Succeeded   1m

# 5. Снятие блокировки со стадии после исправления инцидента
kargo resume stage prod --project kargo-demo
# → Stage "prod" resumed in Project "kargo-demo"
```

## Операции и команды CLI

Сводная таблица регламентных команд инженера сопровождения:

| Операция | Команда CLI | Ожидаемый результат / Примечание |
| :--- | :--- | :--- |
| **Список проектов** | `kargo get projects` | Выводит доступные тенанты (`Project` CRD) |
| **Статус складов** | `kargo get warehouses -p <proj>` | Сводка обнаруженных артефактов и частоты опроса |
| **Ручной опрос склада** | `kargo refresh warehouse <name> -p <proj>` | Принудительный скачок интервала поиска новых версий |
| **Инспекция Freight** | `kargo get freight -p <proj> -o wide` | Детализация: ID, алиас, точный digest, коммит |
| **Статус стадий** | `kargo get stages -p <proj>` | Текущий активный Freight, здоровье, фаза верификации |
| **Ручной аппрув** | `kargo approve freight <alias> --stage <stg> -p <proj>` | Разрешает выкатку артефакта на защищенную стадию |
| **Запуск промоушена** | `kargo promote --stage <stg> --freight <alias> -p <proj>` | Инициализирует объект `Promotion` |
| **История промоушенов**| `kargo get promotions --stage <stg> -p <proj>` | Список запусков: `Succeeded`, `Failed`, `Running` |
| **Логи промоушена** | `kargo logs promotion <promo-id> -p <proj>` | Пошаговый вывод раннеров (git, kustomize, argo) |
| **Принудительный синк**| `kargo refresh stage <stg> -p <proj>` | Перепроверка состояния stage и запуск auto-promotion |
| **Блокировка стадии** | `kargo pause stage <stg> -p <proj>` | Аварийный стоп конвейера (запрет выкаток) |
| **Разблокировка** | `kargo resume stage <stg> -p <proj>` | Возобновление штатной работы конвейера |

## Диагностика и устранение неполадок

| Симптом | Вероятная причина | Диагностика и устранение |
| :--- | :--- | :--- |
| **Warehouse не создает Freight** | 1. Ошибка учетных данных реестра.<br>2. `constraint` отсекает новые теги.<br>3. Реестр не поддерживает OCI Distribution Spec. | 1. Проверить статус склада: `kubectl describe warehouse <name> -n <proj>`.<br>2. Проверить секрет с лейблом `kargo.akuity.io/cred-type: image`.<br>3. Убедиться, что в Harbor опубликован именно валидный image index / manifest list. |
| **Stage зависает в фазе `Verifying`** | 1. Падает `AnalysisRun` / `Job`.<br>2. PromQL возвращает ошибку синтаксиса или тайм-аут.<br>3. Не задан лимит времени анализа. | 1. Найти активный ран: `kubectl get analysisrun -n <proj>`.<br>2. Проверить логи `Job` или доступность Prometheus.<br>3. Добавить в `AnalysisTemplate` жесткий `timeout` и `failureLimit`. |
| **Ошибка на шаге `argocd-update`** | 1. Токен Argo CD истек или не имеет прав `applications, sync, update`.<br>2. Application находится в другом namespace, запрещенном проектом. | 1. Проверить секрет `kargo.akuity.io/cred-type: argocd`.<br>2. Проверить права роли в `argocd-rbac-cm` на сервере Argo CD.<br>3. Выполнить проверку токена через `argocd app get <name> --auth-token <tok>`. |
| **Ошибка на шаге `git-push` (Rejected / Non-fast-forward)** | Конкурентный коммит в инфра-репозиторий сторонним CI-процессом или другим параллельным промоушеном. | 1. Включить шаг `git-clone` непосредственно перед `git-commit`.<br>2. В конфигурации шага `git-push` активировать повторные попытки (retry backoff).<br>3. Использовать выделенные ветки окружений вместо прямого коммита в `main`. |
| **Аппрув выдан, но промоушен не стартует** | 1. Стадия находится в состоянии `paused`.<br>2. Не включен `autoPromotion` для одобренных версий.<br>3. Ошибочный алиас Freight при выдаче approval. | 1. Проверить флаг паузы: `kargo get stage <stg> -p <proj>`.<br>2. Проверить `spec.requestedFreight` — одобрен ли именно тот ID Freight, который выбран для промоушена. |
| **Переполнение etcd объектами Freight и Promotion** | Отсутствует политика очистки старых ресурсов (retention). | 1. Настроить в `spec.freightRetention` или глобальном конфиге контроллера Kargo лимит хранения неактивных артефактов.<br>2. Запустить регламентную очистку завершенных `Promotion` CR. |

## Лучшие практики и эксплуатация в SRE/DevOps

### 1. Высокая доступность и отказоустойчивость контроллера

- **Active/Standby контроллер**: Kargo Controller поддерживает нативный Kubernetes Leader Election (`leases`). В production-кластере рекомендуется запускать 2 реплики контроллера:
  ```yaml
  controller:
    replicas: 2
    leaderElection:
      enabled: true
  ```
- **Горизонтальное шардирование (Sharding)**: при управлении сотнями сервисов нагрузка разделяется назначением шардов. Укажите в Stage/Warehouse поле `spec.shard: shard-billing`, а контроллеры запустите с фильтрацией по аргументу `--shard=shard-billing`.

### 2. Управление секретами без облачных провайдеров

- Исключите хранение постоянных токенов в статических манифестах Git.
- В корпоративной инфраструктуре используйте связку **External Secrets Operator (ESO) + HashiCorp Vault**:
  - Vault выпускает короткоживущие токены для GitLab и Harbor.
  - ESO реплицирует их в Kubernetes Secrets с автоматическим добавлением меток `kargo.akuity.io/cred-type: git` и `kargo.akuity.io/cred-type: image`.

### 3. Моментальная реакция через Webhooks (избавление от задержек полинга)

По умолчанию `Warehouse` опрашивает реестры с интервалом (обычно `5m`). Для обеспечения низкого Lead Time в CI настраивается отправка webhook в Kargo API Server сразу после публикации образа в Harbor:

```bash
# Вызов вебхука из пайплайна сборщика/Harbor Webhook
curl -X POST https://kargo-api.internal/webhooks/warehouse \
  -H "Authorization: Bearer ${KARGO_WEBHOOK_SECRET}" \
  -H "Content-Type: application/json" \
  -d '{"project": "kargo-demo", "warehouse": "billing-api"}'
```
Это переводит время обнаружения нового артефакта из диапазона нескольких минут в миллисекунды.

### 4. Очистка устаревших артефактов (Retention Policy)

Накопление десятков тысяч CRD `Freight` и `Promotion` замедляет API-сервер Kubernetes и увеличивает размер резервных копий etcd. На уровне проекта настраивается retention-политика:

```yaml
apiVersion: kargo.akuity.io/v1alpha1
kind: ProjectConfig
metadata:
  name: default
  namespace: kargo-demo
spec:
  freightRetention:
    maxCount: 30       # сохранять не более 30 последних наборов Freight
    maxAge: 720h       # удалять неиспользуемые Freight старше 30 дней
```

### 5. Мониторинг и метрики (Prometheus & DORA)

Контроллер Kargo экспортирует стандартные Prometheus-метрики на порту `:8080/metrics`. Ключевые метрики для настройки алертинга:

```promql
# 1. Частота падений промоушенов по стадиям (алерт SRE)
rate(kargo_promotions_total{phase="Failed"}[15m]) > 0

# 2. Длительность выполнения промоушена (SLA конвейера доставки)
histogram_quantile(0.95, sum(rate(kargo_promotion_duration_seconds_bucket[1h])) by (le, stage))

# 3. Расчет Lead Time for Changes (метрика DORA)
# Разница времени между созданием Freight на складе и успешным промоушеном в прод:
kargo_stage_freight_applied_timestamp{stage="prod"} - kargo_freight_creation_timestamp
```

## Дополнительная информация

### Взаимодействие со смежными компонентами платформы

1. **Криптографическая верификация**: Kargo фиксирует digest, а политики кластерной безопасности (Kyverno / Gatekeeper) проверяют Cosign-подписи и аттестации SLSA/provenance при развертывании в кластере. Подробности см. в руководстве [Жизненный цикл образов и хранение](./containerization_and_image_storage.md).
2. **Мульти-кластерная доставка**: Kargo координирует продвижение по средам (`dev` → `prod`), тогда как распределение одного и того же Freight по флоту региональных кластеров выполняет `ApplicationSet` с генератором `RollingSync`. См. [Мульти-кластерные паттерны](./multi_cluster_patterns.md).
3. **Безопасное переключение трафика**: Kargo передает управление на уровень пода, где контроллер канареечных релизов плавно переключает трафик (Service Mesh / Ingress). См. [Прогрессивная доставка](./progressive_delivery_gitops.md).

### См. также

- [Жизненный цикл образов и хранение](./containerization_and_image_storage.md) — OCI-реестры, фиксация digest, зеркалирование и подпись артефактов.
- [Обзор методологии: стратегии продвижения](../GitOps_overview.md) — сравнение моделей branch-based, repo-based, overlay и kargo promotion.
- [Метрики DORA в GitOps](./dora_metrics_gitops.md) — измерение Lead Time for Changes, Deployment Frequency и MTTR через события промоушена.
- [Аудит и прослеживаемость в GitOps](./audit_logs.md) — сквозной аудит коммитов, дайджестов и событий контроллеров.
- [Мульти-кластерные паттерны](./multi_cluster_patterns.md) — координация раскатки на флот кластеров через ApplicationSet.
- [Прогрессивная доставка](./progressive_delivery_gitops.md) — канареечные развертывания и AnalysisTemplate через Argo Rollouts.
