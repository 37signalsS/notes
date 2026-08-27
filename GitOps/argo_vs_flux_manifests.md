# Сравнение ArgoCD и Flux: архитектура и манифесты

**ArgoCD** и **Flux** — два ведущих GitOps-инструмента в экосистеме CNCF, реализующие свои задачи с разной философией. Данное сравнение фокусируется на ключевых архитектурных различиях, особенностях безопасности и их отражении в структуре манифестов.

## Определения

- **ArgoCD**: Централизованный GitOps-инструмент с упором на принцип «все-в-одном». Обладает мощным графическим интерфейсом и встроенными функциями мультикластерного управления. Основной ресурс — `Application`, объединяющий источник и назначение.
- **Flux**: Набор (toolkit) декомпозированных, независимых контроллеров. Философия Flux следует принципу Unix-way — каждый инструмент выполняет одну задачу. Ответственность разделена между несколькими кастомными ресурсами (CRD), такими как `GitRepository`, `OCIRepository` и `Kustomization`.
- **GitOps Toolkit**: Набор специализированных контроллеров Flux (source-, kustomize-, helm-, notification-controller), взаимодействующих исключительно через Kubernetes API — один контроллер читает статус артефакта другого, без прямых сетевых вызовов между ними.
- **AppProject**: CRD в ArgoCD, задающий логическую границу для команды: разрешенные репозитории источников, целевые кластеры и неймспейсы, типы ресурсов. Аналог во Flux строится из стандартных примитивов Kubernetes (ServiceAccount + RoleBinding + impersonation).
- **HelmRelease**: CRD во Flux (`helm-controller`), описывающий управляемый Helm-релиз декларативно: источник чарта, диапазон версий, values, стратегия поведения при сбое upgrade.

## Предварительные требования

Для воспроизведения сценариев сравнения необходимы:

| Компонент | ArgoCD | Flux |
| :--- | :--- | :--- |
| Версия инструмента | Линейка v3.x (SSA по умолчанию, OCI-нативность с v3.1+) | Линейка v2.9.x (GA v2.9.0 — июнь 2026; поддерживаются Kubernetes 1.34–1.36, ветка v2.6 EOL) |
| CLI | `argocd` CLI той же минорной версии, что и сервер | `flux` CLI версии устанавливаемого релиза (например, v2.9.4): `brew install fluxcd/tap/flux` |
| Кластер | Kubernetes с правами на установку в namespace `argocd` | Kubernetes 1.34–1.36; проверка готовности `flux check --pre` |
| Доступ к Git | PAT или deploy key на чтение GitOps-репозитория | PAT со scope `repo` (GitHub) либо эквивалент; bootstrap сам создает deploy key |

Исходное состояние: рабочий кластер Kubernetes, доступ к тестовому Git-репозиторию с манифестами приложения (структура `apps/billing/base` + `apps/billing/overlays/prod`).

## Основные концепции

### 1. Архитектура и потребление ресурсов

| Аспект | ArgoCD | Flux |
| :--- | :--- | :--- |
| **Архитектура** | Монолитная (API server, repository server, controller, Redis) | Модульная (GitOps Toolkit на независимых контроллерах) |
| **Управление** | Централизованное (Hub-and-Spoke) | Децентрализованное (агент в каждом кластере) |
| **Потребление ресурсов** | Выше (из-за UI и кэширования графа ресурсов в памяти) | Ниже (минималистичные контроллеры на Go) |
| **Масштабируемость** | Шардирование контроллера приложений для крупных сред | Естественное масштабирование через распределение |
| **Хранение состояния** | Хранит состояние всех ресурсов кластера для визуализации | Контроллеры отслеживают только свои CRD |
| **Связанность компонентов** | Внутренние вызовы между компонентами монолита (gRPC/Redis-кэш) | Контроллеры общаются только через Kubernetes API (статусы артефактов) — компоненты заменяемы независимо |
| **Установка самого инструмента** | Helm-чарт / манифесты / оператор | `flux bootstrap` коммитит манифесты установки в Git — кластер «управляет сам собой» |
| **Управление инстансами Flux** | Неприменимо (единый монолит) | Flux Operator: декларативная версия и состав контроллеров (`FluxInstance`), шардирование реконсиляции, несколько инстансов в одном кластере |

Следствие модульности Flux: можно установить подмножество контроллеров (например, только `source-controller` + `kustomize-controller` без image-automation) и независимо обновлять каждый. Следствие монолитности ArgoCD: единая точка конфигурации (`argocd-cm`) и единая модель обновления всего стека сразу, зато согласованные версии компонентов гарантированы.

### 2. Модель конфигурации и синхронизации

- **ArgoCD**: Использует единый ресурс `Application`. В нем объединены источник (Git/Helm), целевой кластер и политики синхронизации (`syncPolicy`). Начиная с линейки v3.x стандартом является **Server-Side Apply (SSA)**, что минимизирует конфликты при работе с мутирующими вебхуками и большими манифестами.
- **Flux**: Разделяет обязанности. `Source`-контроллер отвечает за получение артефактов (`GitRepository`, `OCIRepository`), а `Kustomize`- и `Helm`-контроллеры — за их применение. Это позволяет использовать один источник для множества независимых развертываний в разных неймспейсах с разными интервалами сверки.

Дополнительные различия модели:

- **Применение изменений**: Flux применяет манипресты через Server-Side Apply с field manager вида `kustomize-controller`; опция `ServerSideApply=true` в ArgoCD фиксирует тот же механизм явно (в v3.x он уже включен по умолчанию).
- **Зависимости**: Flux выстраивает порядок через `dependsOn` между `Kustomization` (родитель считается выполненным при `Ready=True` после healthChecks); ArgoCD использует sync waves и хуки внутри одного `Application`.
- **Триггеры реконсиляции**: оба инструмента работают по интервалу плюс вебхуки от Git-хостинга; во Flux дополнительный ручной триггер — команда `flux reconcile kustomization <name>`, в ArgoCD — `argocd app sync` (императивное применение) или `--refresh`.

### 3. Интерфейс и отладка

- **ArgoCD**: Поставляется с развитым Web UI, который визуализирует иерархию ресурсов, позволяет сравнивать различия (diff), просматривать логи и выполнять откат. Отладка расхождения выполняется командой `argocd app diff <app> --server-side-generate` — она показывает, какие поля и каким менеджером изменены, что критично при диагностике конфликтов владения полями SSA.
- **Flux**: Не имеет официального встроенного графического интерфейса. Основное взаимодействие происходит через CLI `flux`: `flux get kustomizations` (статус), `flux describe kustomization <name>` (детали последней реконсиляции, примененная ревизия), `flux events` (события контроллеров). Отладка выполняется через инспекцию статусов CRD (`kubectl describe kustomization`) и логов контроллеров. Для визуализации используются сторонние решения: FreeLens (вкладка со всеми ресурсами Flux), Weave GitOps (ограниченно развивается после закрытия Weaveworks в 2024) и веб-дашборд в составе Flux Operator.

Практическое следствие: в ArgoCD первичный интерфейс — визуальный (быстрый онбординг команды, разбор инцидентов глазами не-engineers), во Flux — терминальный и декларативный (легче автоматизировать, меньше кликов, но выше порог входа). Столбец *Applied Revision* в GUI-инструментах для Flux показывает хэш примененного коммита — быстрая проверка того, что кластер получил последнюю версию.

### 4. Безопасность и мультитенантность

| Функция | ArgoCD | Flux |
| :--- | :--- | :--- |
| **Изоляция (Multi-tenancy)** | Нативная через `AppProject` (ограничение репозиториев, кластеров, ресурсов) | Изоляция через ServiceAccount Impersonation для каждой `Kustomization` |
| **Доступ (RBAC)** | Детализированный встроенный RBAC с поддержкой SSO (OIDC, SAML); с v3.0+ права на sync/update/delete разделены | Нативный Kubernetes RBAC (контроллер работает от имени ServiceAccount) |
| **Секреты** | Внешние операторы (ESO) или плагины расшифровки (AVP) | Глубокая нативная интеграция с Mozilla SOPS (KMS, age) |
| **Управление флотом** | Централизованные политики безопасности для всех кластеров | Индивидуальные настройки безопасности в каждом кластере |
| **Верификация источников** | Source Integrity (v3.5): блокировка синхронизации коммитов без доверенной GPG-подписи | `spec.verify` в `GitRepository`/`OCIRepository`: Cosign/GPG-подписи; SSH-подписи коммитов с v2.9 |
| **Операции от имени пользователя** | Impersonation (beta с v3.5): операции сервера выполняются от имени запросившего пользователя | Базовый принцип архитектуры: каждая `Kustomization` может работать от своего ServiceAccount |

Важное уточнение про подписи: верификация источников в обоих инструментах — **опциональная, настраиваемая функция**, а не включенное по умолчанию требование. Контроллер блокирует применение неподписанного артефакта только если в манифесте источника сконфигурировано поле проверки (`spec.verify` во Flux, политика подписей в ArgoCD). Рекомендация для production-цепочки поставок: настроить верификацию для всех внешних источников и сочетать её с политиками admission (Kyverno/Gatekeeper) на уровне образов — см. [Жизненный цикл образов](./Concepts/containerization_and_image_storage.md).

### Семантика дрейфа и самовосстановления

Ключевое практическое различие, часто вызывающее неожиданности при переходе между инструментами:

- **ArgoCD** разделяет понятия *OutOfSync* (обнаружено расхождение) и *коррекция*: без `automated.selfHeal: true` контроллер покажет статус OutOfSync, но не будет перезаписывать ручные изменения (`kubectl edit`). С selfHeal любое отклонение исправляется в течение интервала реконсиляции.
- **Flux** корректирует дрейф всегда: каждая итерация реконсиляции заново применяет желаемое состояние (это часть цикла, а не отдельная опция). Ручные правки переживают максимум один интервал. Управление «мягкостью» достигается не отключением коррекции, а правилами игнорирования полей: `Kustomization.spec.ignore` и структурированные DriftIgnoreRules (v2.9+) позволяют оставить поле под владением другого контроллера (классика — `spec.replicas` у HPA).
- **Приостановка**: `spec.suspend: true` (или `flux suspend ks <name>`) останавливает и применение, и коррекцию дрейфа — ручные правки сохраняются до возобновления. Эквивалент в ArgoCD — отключение auto-sync у приложения.

Это означает: миграция с ArgoCD без selfHeal на Flux меняет поведение кластера — все «безопасные» ручные хотфиксы начнут откатываться. Перед миграцией инвентаризируйте такие правки и перенесите их в Git.

## Практические сценарии

### Сценарий 1: Развертывание приложения через Kustomize

#### Подход ArgoCD (единый манифест)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-api
  namespace: argocd
spec:
  project: finance-team
  source:
    repoURL: https://github.com/org/infra-gitops.git
    path: apps/billing/overlays/prod
    targetRevision: HEAD
  destination:
    server: https://kubernetes.default.svc
    namespace: billing
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - ServerSideApply=true
```

Проверка применения:

```bash
argocd app get billing-api --refresh
# → Name:               billing-api
# → Status:             Synced
# → Health:             Healthy
# → Sync Policy:        Automated (Prune, SelfHeal)

kubectl get deploy -n billing
# → NAME          READY   UP-TO-DATE   AVAILABLE
# → billing-api   2/2     2            2
```

#### Подход Flux (разделение ресурсов)

```yaml
# 1. Определение источника (Source)
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: billing-manifests
  namespace: flux-system
spec:
  interval: 10m
  url: oci://ghcr.io/org/manifests/billing
  ref:
    tag: v1.2.0
---
# 2. Определение применения (Reconciliation)
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: billing-api
  namespace: flux-system
spec:
  serviceAccountName: billing-reconciler
  interval: 1h
  path: ./overlays/prod
  prune: true
  sourceRef:
    kind: OCIRepository
    name: billing-manifests
  targetNamespace: billing
```

Проверка применения:

```bash
flux get sources oci billing-manifests
# → NAME              REVISION        SUSPENDED   READY   MESSAGE
# → billing-manifests sha256:a1b2c3d     False     True    stored artifact for digest

flux get kustomizations billing-api
# → NAME          REVISION       SUSPENDED   READY   MESSAGE
# → billing-api   v1.2.0/<sha>   False       True    Apply succeeded
```

Обратите внимание на распределение интервалов: источник опрашивается каждые 10 минут, применение выполняется ежечасно. Во Flux эти тайминги независимы — частая сверка дешевого артефакта (локальный tar) отделена от дорогой реконсиляции (вызовы API-сервера). В ArgoCD эквивалент настраивается парой параметров `timeout.reconciliation` и webhook'ами глобально, без разбивки на источник/применение.

### Сценарий 2: Первичная установка (bootstrap) инструментов

Сама установка демонстрирует философскую разницу:

```bash
# Flux: установка = коммит манифестов контроллеров в GitOps-репозиторий
flux bootstrap github \
  --owner=my-org \
  --repository=fleet-infra \
  --branch=main \
  --path=clusters/production
# ► connecting to github.com
# ✔ repository created
# ✔ component source-controller deployed
# ✔ kustomization flux-system reconciled
# → далее изменения состава Flux вносятся правкой манифестов в Git, а не командами

# ArgoCD: установка через Helm (или нативные манифесты)
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd --namespace argocd --create-namespace
# → NAME: argocd ... STATUS: deployed
# → установка императивна: чтобы она стала GitOps-управляемой,
#   состояние ArgoCD впоследствии описывают Application/AppProject в Git
```

Bootstrap во Flux идемпотентен и повторно безопасен: запуск на существующем кластере приведет манифесты к нужной версии. Для управления версиями и составом компонентов Flux в десятках кластеров рекомендуется [Flux Operator](./flux.md) — конфигурация `FluxInstance` сама живет в Git.

### Сценарий 3: Развертывание Helm-приложения

#### Подход ArgoCD (источник-чарт в Application)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ingress-nginx
  namespace: argocd
spec:
  project: platform
  source:
    repoURL: registry-1.docker.io/bitnamicharts # OCI-реестр как источник (нативно с v3.1+)
    chart: nginx
    targetRevision: 20.3.1                     # пиннинг конкретной версии чарта
    helm:
      valuesObject:
        controller:
          replicaCount: 3
  destination:
    server: https://kubernetes.default.svc
    namespace: ingress-nginx
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

#### Подход Flux (HelmRelease)

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: bitnami
  namespace: flux-system
spec:
  type: oci
  url: oci://registry-1.docker.io/bitnamicharts
  interval: 30m
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: ingress-nginx
  namespace: flux-system
spec:
  interval: 1h
  chartRef:
    kind: HelmRepository
    name: bitnami
    chart: nginx
    version: ">=20.0.0 <21.0.0"   # диапазон semver вместо жесткого пина
  install:
    crds: CreateReplace
  values:
    controller:
      replicaCount: 3
```

Разница в семантике версионирования: `targetRevision` у ArgoCD требует явного bump'а при каждом обновлении (что идеально ложится на PR-процесс promotion), а диапазон `version` у HelmRelease позволяет контроллеру самому подтягивать новые патчи в границах диапазона (удобно для автообновлений, но снижает контроль — компенсируется политиками и уведомлениями). При неудачном upgrade helm-controller автоматически откатывает релиз к предыдущей рабочей ревизии (`strategy: rollback`); в ArgoCD аналогичную защиту дают health-check'и + откат вручную или через Argo Rollouts.

### Сценарий 4: Шифрование секретов

#### Подход Flux (нативная расшифровка SOPS)

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: billing-secrets
  namespace: flux-system
spec:
  interval: 1h
  path: ./apps/billing/secrets
  prune: true
  sourceRef:
    kind: GitRepository
    name: infra-gitops
  decryption:
    provider: sops
    secretRef:
      name: sops-age   # Secret с приватным ключом age в flux-system
```

Рабочий процесс: `.sops.yaml` в репозитории определяет правила шифрования; файлы шифруются локально (`sops --encrypt --in-place secret.yaml`) и коммитятся — в Git лежит только шифротекст, приватный ключ age существует исключительно в кластере. Расшифровка происходит на лету при сборке kustomize-controller'ом.

#### Подход ArgoCD (плагин или внешний оператор)

ArgoCD не умеет расшифровывать SOPS нативно — типовые пути:

```yaml
# Вариант А: KSOPS/Kustomize плагин (расшифровка на стороне ArgoCD)
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-secrets
  namespace: argocd
spec:
  project: finance-team
  source:
    repoURL: https://github.com/org/infra-gitops.git
    path: apps/billing/secrets   # содержит *.enc.yaml, расшифровываются KSOPS-плагином
    targetRevision: HEAD
  destination:
    server: https://kubernetes.default.svc
    namespace: billing
```

```yaml
# Вариант B: External Secrets Operator — секреты вообще не проходят через Git
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: billing-db
  namespace: billing
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: db-credentials
  data:
    - secretKey: password
      remoteRef:
        key: billing/db
```

Подробности и сравнение подходов — в [Шифрование секретов](./secrets_encryption.md). Практический вывод: во Flux путь SOPS встроен в контроллер (меньше движущихся частей), в ArgoCD выбор между плагином (нужно обслуживать кастомный образ repo-server) и ESO (больше инфраструктуры, но секреты не попадают даже в зашифрованном виде в Git).

### Сценарий 5: Изоляция команд (мультитенантность)

#### Подход ArgoCD (AppProject)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: finance-team
  namespace: argocd
spec:
  description: Приложения финансовой команды
  sourceRepos:
    - https://github.com/org/infra-gitops.git
    - oci://ghcr.io/org/charts
  destinations:
    - server: https://kubernetes.default.svc
      namespace: billing
    - server: https://kubernetes.default.svc
      namespace: finance-staging
  clusterResourceWhitelist: []           # командам запрещены cluster-scoped ресурсы
  namespaceResourceBlacklist:
    - group: ""
      kind: ResourceQuota               # нельзя менять собственные квоты
  roles:
    - name: deployer
      policies:
        - p, proj:finance-team:deployer, applications, sync, finance-team/*, allow
      groups:
        - idp:finance-devs              # маппинг группы из SSO/OIDC
```

Все `Application` команды обязаны ссылаться на проект (`project: finance-team`), и RBAC ArgoCD ограничивает действия рамками проекта.

#### Подход Flux (impersonation)

```bash
# 1. ServiceAccount команды в целевом неймспейсе
kubectl create sa billing-reconciler -n billing
# → serviceaccount/billing-reconciler created

# 2. RoleBinding — права ТОЛЬКО в своем неймспейсе
kubectl create rolebinding billing-reconciler-admin \
  --serviceaccount=billing:billing-reconciler \
  --clusterrole=admin -n billing
# → rolebinding.rbac.authorization.k8s.io/billing-reconciler-admin created

# 3. Отсутствие прав в flux-system гарантирует, что контроллер,
#    действуя от имени billing-reconciler, не сможет тронуть чужие неймспейсы
```

Далее `serviceAccountName: billing-reconciler` в `Kustomization` (как в Сценарии 1) заставляет kustomize-controller применять манифесты от имени ограниченного аккаунта: попытка создать cluster-scoped объект или ресурс в чужом неймспейсе упадет с `forbidden` и будет видна в статусе объекта. Различие моделей: AppProject — централизованная надстройка над всеми приложениями проекта (одна точка аудита), impersonation — композиция стандартных механизмов Kubernetes (нет собственного слоя абстракции, зато вся логика видна обычным kubectl и работает одинаково для людей и контроллера).

### Сценарий 6: Откат развертывания

```bash
# === Общий принцип для обоих инструментов: откат = git revert ===
cd infra-gitops && git revert <commit-sha> && git push
# → ArgoCD/Flux обнаружат возврат версии и сами вернут прежнее состояние кластера

# === Специфика ArgoCD ===
argocd app history billing-api
# → ID  REVISION
# → 3   HEAD (abc123def)   ← текущая
# → 2   HEAD (987654fed)   ← предыдущая
argocd app rollback billing-api 2
# ВНИМАНИЕ: при включенном auto-sync следующая реконсиляция отменит ручной откат —
# сначала отключите: argocd app set billing-api --sync-policy none
# штатный путь — всегда git revert

# === Специфика Flux ===
flux suspend kustomization billing-api   # заморозить, если нужно время на разбор
# → ► suspending kustomization billing-api in flux-system namespace
#     ✔ kustomization suspended
flux resume kustomization billing-api    # после git revert — возобновить
# Помните: suspended-объект НЕ корректирует дрейф; список подвисших стоит аудировать:
flux get kustomizations | grep True   # столбец SUSPENDED
```

Во Flux дополнительно работает защита уровня Helm-релиза: при неудачном upgrade `HelmRelease` со `strategy: rollback` helm-controller сам возвращается к последней успешной ревизии — до вмешательства человека. В ArgoCD эквивалентная автоматизация достигается связкой с Argo Rollouts (см. ниже).

## Дополнительная информация

### Функциональное сравнение

| Функция | ArgoCD | Flux |
| :--- | :--- | :--- |
| **Работа с Helm** | Нативная поддержка (рендеринг на стороне сервера) | Через специализированный Helm Controller |
| **OCI-артефакты** | Поддержка OCI как источников манифестов и чартов (нативно с v3.1+) | OCI является приоритетным транспортом (`flux push artifact`, высокая скорость, версионирование) |
| **Автоматизация образов** | Аддон ArgoCD Image Updater (v1.x: декларативный CRD, запись в Git опциональна; аннотации — legacy) | Контроллеры Image Reflector и Automation (правка Git через маркеры) |
| **Прогрессивный деплой** | Argo Rollouts (анализ метрик, Canary) | Flagger (интеграция с Service Mesh); рабочие конфигурации обоих — [Прогрессивная доставка в GitOps](./Concepts/progressive_delivery_gitops.md) |
| **Уведомления** | Интегрированы в контроллер (ConfigMap `argocd-notifications-cm`, аннотации подписки на приложениях) | Отдельный notification-controller с CRD (`Provider`/`Alert`/`Receiver`) |
| **Монорепозитории** | Shallow Git Cloning (v3.3+) ускоряет клонирование больших репозиториев | source-watcher/ArtifactGenerator (v2.9): составные артефакты из нескольких источников, меньше пересборок |
| **Отслеживание ресурсов** | Настраиваемые методы tracking (label/annotation, configmap) в `argocd-cm` | Владение полями через SSA field managers, правила игнорирования полей |
| **Расширяемость** | Плагины рендеринга (config management plugins), кастомные health checks | Контроллер можно заменить своим (архитектура toolkit), postBuild-подстановки |

### Актуальное состояние (август 2026)

*   **Управляемые сервисы:** Amazon EKS Capability for Argo CD (запуск в конце 2025) предоставляет полностью управляемый Argo CD, работающий вне кластеров в сервисных аккаунтах AWS: масштабирование, обновления, кросс-аккаунтные подключения через EKS Access Entries, SSO через IAM Identity Center, нативные интеграции с ECR/Secrets Manager/CodeConnections; с августа 2026 поддерживается тонкая настройка через стандартный `argocd-cm`. Со стороны Azure исторически доступно управляемое расширение Flux для AKS, а с марта 2026 в public preview вышло и расширение Argo CD для AKS/Azure Arc (Workload Identity к ACR/Azure DevOps, SSO через Entra ID, сборки на Azure Linux). Итог: обе облачные платформы теперь предлагают управляемыми ОБА инструмента, что снимает последний аргумент «операционной сложности» при выборе.
*   **OCI-ориентированность:** Оба инструмента окончательно перешли на OCI-репозитории как основной способ доставки манифестов, что снизило нагрузку на Git-серверы в крупных организациях. Во Flux это выражается приоритетом `OCIRepository` и командой `flux push artifact`; в ArgoCD — нативными OCI-источниками чартов и манифестов (v3.1+).
*   **Безопасность цепочки поставок:** Верификация подписей стала штатной частью конвейера, но остается настраиваемой: во Flux — поле `spec.verify` (Cosign-подписи OCI-артефактов, GPG/SSH-подписи Git-коммитов; image-automation-controller умеет подписывать собственные коммиты); в ArgoCD — Source Integrity (v3.5) блокирует синхронизацию коммитов без доверенной GPG-подписи, добавлен взаимный mTLS между внутренними компонентами. Политики admission (Kyverno/Gatekeeper) дополняют картину на уровне образов.
*   **Эксплуатация крупных флотов:** ArgoCD развивает шардирование application-controller и Progressive Sync в ApplicationSet; Flux отвечает Flux Operator'ом — декларативное управление инстансами (`FluxInstance`), шардирование реконсиляции, шаблонизация наборов ресурсов (`ResourceSet`).

### Типовые проблемы и их решение

| Симптом | Инструмент | Причина | Решение |
| :--- | :--- | :--- | :--- |
| Ручные правки исчезают каждые N минут | Flux | Коррекция дрейфа — часть каждого цикла реконсиляции | Перенести изменение в Git либо добавить поле в `spec.ignore`; проверить владельца поля: `kubectl get deploy -n billing -o yaml \| grep -A5 managedFields` |
| Статус OutOfSync, но ничего не происходит | ArgoCD | Auto-sync/selfHeal не включены | Включить `automated.selfHeal` в `syncPolicy` либо синхронизировать вручную `argocd app sync` |
| `forbidden` в статусе `Kustomization` | Flux | Impersonated ServiceAccount не имеет прав на целевые ресурсы | Расширить RoleBinding в рамках политики; убедиться, что манифесты не создают cluster-scoped объекты без прав |
| `Application` не видит репозиторий | ArgoCD | Репозиторий не входит в `sourceRepos` проекта | Добавить URL в `AppProject.spec.sourceRepos` или сменить проект |
| Реконсиляция не идет, статус Ready=False без ошибок | Flux | `spec.suspend: true` | `flux get kustomizations` (столбец SUSPENDED), затем `flux resume` |
| Откат через CLI отменяется сам собой | Оба | Автосинхронизация возвращает состояние из Git | Единственный устойчивый откат — `git revert`; CLI-откат допустим только с временной приостановкой автосинхронизации |
| Конфликт полей с HPA (replicas мигает) | Оба | Два менеджера борются за одно поле | ArgoCD: `ignoreDifferences` в Application; Flux: `spec.ignore`/DriftIgnoreRules с привязкой к field manager |
| Медленная обработка большого монорепозитория | ArgoCD / Flux | Полное клонирование Git / пересборка артефактов | ArgoCD: Shallow Cloning (v3.3+); Flux: source-watcher с составными артефактами (v2.9) |

### Критерии выбора

| Ситуация | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| Команда с сильной визуальной культурой, платформа для разработчиков | ArgoCD | Web UI снижает порог входа, diff и история видны без терминала |
| Минимальный след в кластере, edge/multi-tenant кластеры | Flux | Контроллеры потребляют мало ресурсов, ставится подмножество компонентов |
| Жесткие требования к мультитенантности с централизованным аудитом | ArgoCD | AppProject дает единую точку контроля проектов и встроенный RBAC с SSO |
| Нативная работа с SOPS и «чистым» Kubernetes-RBAC | Flux | Расшифровка встроена в kustomize-controller; изоляция через impersonation без собственных абстракций |
| Fleet из десятков кластеров на одной облаке | Управляемый сервис | EKS Capability for Argo CD / расширения AKS снимают эксплуатацию control plane |
| Автоматические автообновления патчей чартов в заданном диапазоне | Flux | Диапазон semver в HelmRelease + автоматический rollback helm-controller |
| Строгий PR-процесс продвижения версий между средами | Любой / ArgoCD чуть удобнее | Явный `targetRevision` в Application естественно проходит code review |

Инструменты не взаимоисключающие: распространена гибридная схема — ArgoCD в центральном hub-кластере для прикладных команд, Flux в периферийных/edge-кластерах для системных компонентов. Общая методология описана в [Обзоре методологии GitOps](./GitOps_overview.md).

**Связанные документы:**
- [Обзор методологии GitOps](./GitOps_overview.md) — фундаментальные принципы.
- [Обзор ArgoCD](./ArgoCD/argocd_overview.md) — детальная архитектура.
- [Обзор Flux](./flux.md) — модульный подход и контроллеры.

**Официальные ресурсы:** [Argo Project](https://argoproj.github.io/), [Flux Community](https://fluxcd.io/).
