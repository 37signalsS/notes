# Crossplane: Интеграция с GitOps

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); Argo CD v2.12+ / v3.5+; Flux v2.x; on-premise / bare-metal

## Определения

- **GitOps для инфраструктуры** — операционная модель управления ИТ-инфраструктурой, при которой Git-репозиторий выступает единственным источником правды (Single Source of Truth, SSoT) для декларативного описания целевого состояния систем. Доставка изменений выполняется автоматизированными pull-контроллерами внутри кластера.
- **Crossplane Control Plane** — управляющий кластер Kubernetes с установленным ядром Crossplane и набором провайдеров, функционирующий как центральная плоскость управления корпоративной инфраструктурой (on-premise серверами, гипервизорами, базами данных, хранилищами и сетевыми сервисами).
- **Двухконтурная сверка (Two-Loop Reconciliation)** — архитектурный паттерн совместной работы GitOps-контроллера и Crossplane:
  1. *GitOps-контур* (Argo CD / Flux) опрашивает Git-репозиторий и приводит манифесты в кластере в соответствие с коммитами (`selfHeal` / `prune`).
  2. *Crossplane-контур* непрерывно сверяет состояние физических и логических ресурсов инфраструктуры (СУБД, бакеты, виртуальные машины, сетевые сегменты) с манифестами в Kubernetes API и ликвидирует дрейф параметров (drift detection).
- **Managed Resource (MR)** — низкоуровневый Kubernetes-ресурс (CRD), представляющий конкретную сущность целевой системы (например, база данных `Database` или роль `Role` в `provider-sql`, объект в `provider-kubernetes`, виртуальная машина в `provider-proxmox`).
- **CompositeResourceDefinition (XRD)** — кластерная схема пользовательского API платформы, определяющая абстрактный интерфейс сервиса (например, `XPostgreSQLInstance`), его входные параметры и схему валидации.
- **Composition** — реализация XRD, связывающая абстрактный ресурс с набором конкретных Managed Resources через конвейер Composition Functions (`mode: Pipeline`).
- **CompositeResourceClaim (Claim)** — namespace-scoped запрос разработчика на предоставление инфраструктурного сервиса, связанный с жизненным циклом пространства имен приложения.
- **ProviderConfig** — декларативная конфигурация подключения провайдера к целевой инфраструктуре (адрес эндпоинта, таймауты, пулы соединений, ссылки на секреты с аутентификационными данными).
- **OCI Configuration Package** — стандартизированный OCI-образ (распространяемый через локальный реестр, например Harbor), содержащий упакованные XRD и Compositions платформы с поддержкой версионирования и контроля целостности.

---

## Базовые концепции

### Разделение ответственности: два слоя GitOps

Устойчивая архитектура GitOps на базе Crossplane исключает смешивание платформенного кода и запросов прикладных команд в едином монолитном репозитории. Архитектура разделяется на два независимых слоя:

```text
┌────────────────────────────────────────────────────────────────────────┐
│ Слой 1: Платформенный репозиторий (Platform / Bootstrap Git Repo)      │
│ Владелец: SRE / Platform Engineers                                     │
│ Содержимое:                                                            │
│  - Установка Crossplane Core, Helm-чарты провайдеров и функций         │
│  - Пакеты провайдеров (provider-sql, provider-kubernetes, etc.)        │
│  - ProviderConfig, ClusterSecretStore (Vault), SOPS-ключи              │
│  - Платформенные OCI Configuration, XRD и Compositions (Golden Paths)  │
│ Доставка: Argo CD / Flux (синхронизация в namespace crossplane-system) │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ Предоставляет платформенный API
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Слой 2: Прикладной репозиторий (Application / Claims Git Repo)         │
│ Владелец: Команды разработки / DevOps продуктов                        │
│ Содержимое:                                                            │
│  - Запросы на ресурсы: CompositeResourceClaim (БД, S3-бакеты, очереди) │
│  - Нативные манифесты приложений (Deployment, Service, Ingress)        │
│  - Ссылки на генерируемые Connection Secrets                           │
│ Доставка: Argo CD / Flux (синхронизация в продуктовые namespaces)      │
│ Ограничение: Прямые учетные данные инфраструктуры сюда НЕ попадают     │
└────────────────────────────────────────────────────────────────────────┘
```

Такое разделение гарантирует:
- Разработчики не имеют доступа к учетным записям администраторов СУБД, гипервизоров или сетевых коммутаторов.
- Изменение реализации платформенного сервиса (например, переход с отдельного экземпляра PostgreSQL на HA-кластер Patroni) происходит в Слое 1 без изменения прикладных манифестов в Слое 2.

### Архитектура и схема взаимодействия

```text
┌────────────────────────┐         ┌──────────────────────┐        ┌─────────────────────────┐
│ Git (Platform Repo)    │         │  GitOps-контроллер   │        │  Management Cluster     │
│ XRD / Composition /    │────────▶│   (Argo CD / Flux)   │───────▶│  Crossplane Core +      │
│ Provider / Functions   │         │    Sync & Prune      │        │  Провайдеры (Reconcile) │
└────────────────────────┘         └──────────────────────┘        └───────────┬─────────────┘
                                                                               │ 3. Создание MR
┌────────────────────────┐         ┌──────────────────────┐                    │
│ Git (App Claims Repo)  │         │  GitOps-контроллер   │                    ▼
│ CompositeResourceClaim │────────▶│   (Argo CD / Flux)   │─────────▶  ┌─────────────────────────┐
│ (запрос на БД / S3)    │         │    Sync & Self-Heal  │            │ Локальная инфраструктура│
└────────────────────────┘         └──────────────────────┘            │ Bare-Metal / K8s Fleet /│
                                                                       │ Patroni / Ceph / Vault  │
Поток данных и жизненный цикл:                                         └─────────────────────────┘
1. Коммит Claim в Git прикладного репозитория.
2. GitOps-контроллер обнаруживает коммит и применяет Claim в продуктовый namespace кластера.
3. Crossplane связывает Claim с кластерным Composite Resource (XR).
4. Composition Pipeline разворачивает набор Managed Resources (MR).
5. Провайдер подключается по внутренней сети к целевой системе и выполняет настройку.
6. Провайдер генерирует Connection Secret в namespace приложения; статус поднимается до Claim (`Ready: True`).
```

### Роли: Crossplane против GitOps-инструмента

Инструменты дополняют друг друга, решая непересекающиеся задачи:

| Критерий | GitOps-контроллер (Argo CD / Flux) | Crossplane |
| :--- | :--- | :--- |
| **Зона ответственности** | Доставка манифестов из Git/OCI в Kubernetes API | Приведение внешней инфраструктуры к состоянию манифестов K8s |
| **Управление дрейфом** | Сверяет состояние объектов в etcd кластера с Git | Сверяет реальные объекты в инфраструктуре с состоянием в etcd |
| **Реакция на вмешательство** | Перезаписывает измененный манифест в кластере (`selfHeal`) | Перенастраивает параметры целевого сервиса по сети |
| **Осведомленность о сервисах**| Не знает семантики СУБД, бакетов или гипервизоров | Реализует протоколы конкретных провайдеров (SQL, S3 API, SSH/API) |

Crossplane **GitOps-агностичен**: в качестве доставщика манифестов подходит любой pull-контроллер. Доставка через CI (`kubectl apply` в push-модели) не рекомендуется, так как лишает платформу автоматического восстановления при дрейфе (`selfHeal`) и очистки удаленных ресурсов (`prune`).

### Сравнение GitOps-контроллеров: Argo CD и Flux в On-Premise

| Параметр | Argo CD | Flux |
| :--- | :--- | :--- |
| **Визуализация и UI** | Наглядное дерево зависимостей `Application` (Claim → XR → MR). Визуализация статусов условий готовности (`Ready`, `Synced`). | UI отсутствует из коробки (сторонний Weave GitOps). Управление преимущественно через CLI `flux`. |
| **Мультикластерность** | `ApplicationSet` с генераторами `cluster`, `git`, `list`, `pullRequest` для централизованного управления парком кластеров. | Архитектура pull-агентов на каждом кластере (`flux-system`), высокая автономность edge-узлов. |
| **Работа с OCI** | Поддержка Helm-чартов и Kustomize из OCI-реестров. | Нативная поддержка OCI-артефактов первого класса (`OCIRepository`), идеальная связка с пакетами Crossplane. |
| **Расшифровка секретов** | Требует настройки Config Management Plugins (CMP) или интеграции с внешними операторами (ESO). | Встроенное нативное расшифровывание **SOPS** без внешних плагинов (`decryption.provider: sops`). |
| **Кастомные Health Checks** | Поддержка Lua-скриптов в `argocd-cm` для вычисления статуса здоровья CRD Crossplane. | Встроенная поддержка `healthChecks` по стандартным условиям `Ready` в объектах Kustomization. |
| **Рекомендация для On-Premise** | Корпоративные Control Plane кластеры с выделенной командой SRE и многопользовательским доступом. | Изолированные, распределенные или air-gapped кластеры без центрального UI. |

### Управление секретами: ESO и SOPS в изолированном контуре

В GitOps-процессе пароли и токены подключения к инфраструктуре запрещено хранить в Git в открытом виде. В контексте Crossplane решаются две задачи:
1. **Безопасная доставка реквизитов подключения к инфраструктуре в `ProviderConfig`** (входные секреты).
2. **Маршрутизация сгенерированных Crossplane реквизитов доступа к созданным базам и сервисам** (выходные Connection Secrets).

Общую теорию и методы ротации см. в [GitOps: Управление секретами и шифрование](../secrets_encryption.md).

#### Паттерн 1: External Secrets Operator (ESO) + HashiCorp Vault

Рекомендуемый подход для корпоративной on-premise инфраструктуры:
- **Входные креды:** Административные пароли СУБД, токены гипервизоров и сервисных аккаунтов хранятся в корпоративном Vault. ESO через `ClusterSecretStore` доставляет их в Secret неймспейса `crossplane-system`, откуда их читает `ProviderConfig`.
- **Выходные креды:** Crossplane сохраняет созданные пароли в локальный Secret через `writeConnectionSecretToRef`. Объект `PushSecret` оператора ESO переносит эти данные обратно в Vault (путь `secret/data/apps/<app-name>/db`), откуда их могут забирать внешние системы или другие кластеры.

```yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: vault-backend
spec:
  provider:
    vault:
      server: "https://vault.internal.corp:8200"
      path: "secret"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "crossplane-provider"
          serviceAccountRef:
            name: crossplane-provider-sa
            namespace: crossplane-system
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: postgres-admin-credentials
  namespace: crossplane-system
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: postgres-admin-creds
    creationPolicy: Owner
  data:
    - secretKey: password
      remoteRef:
        key: infrastructure/database/patroni
        property: superuser_password
```

#### Паттерн 2: Mozilla SOPS с асимметричными ключами age

Для контуров без выделенного Vault применяется шифрование файлов манифестов перед коммитом в Git с помощью утилиты `sops` и открытых ключей `age`.
- Приватный ключ `age` монтируется в контроллер GitOps (Flux Kustomize Controller или плагин Argo CD repo-server).
- Контроллер расшифровывает манифест в оперативной памяти перед отправкой в Kubernetes API; в etcd и Git секреты хранятся в защищенном виде.

### Жизненный цикл и политики удаления: Delete против Orphan

Критический аспект SRE-эксплуатации Crossplane через GitOps — управление удалением ресурсов при удалении манифестов из репозитория:

- **`deletionPolicy: Delete` (по умолчанию)** — при удалении манифеста Claim или MR из Git, GitOps-инструмент удаляет объект из кластера, после чего контроллер провайдера выполняет физическое удаление ресурса на внешнем сервере (`DROP DATABASE`, удаление виртуальной машины или бакета).
- **`deletionPolicy: Orphan`** — при удалении объекта из кластера Crossplane снимает финализаторы и удаляет объект из Kubernetes API, но оставляет физический ресурс на внешнем сервере нетронутым.

> [!WARNING]
> В продуктивных средах для stateful-ресурсов (базы данных, дисковые тома, постоянные хранилища) в Compositions **обязательно** задается `deletionPolicy: Orphan` либо в Argo CD включается аннотация `argocd.argoproj.io/sync-options: Prune=false`. Случайный коммит с удалением файла Claim или удаление ветки в Git не должны приводить к физическому уничтожению корпоративных данных.

Для поэтапного подключения существующей инфраструктуры в Crossplane v2.x используется `managementPolicies`:
- `["ObserveOnly"]` — Crossplane только считывает текущие параметры ресурса, не изменяя их и не удаляя при очистке.
- `["Create", "Update", "Observe"]` — создание и поддержка без возможности удаления внешнего объекта.
- `["*"]` — полный контроль жизненного цикла.

---

## Практические сценарии

### Предварительные требования

Перед началом работы убедитесь в готовности компонентов:

| Компонент | Минимальная версия | Назначение в On-Premise инфраструктуре |
| :--- | :--- | :--- |
| **Kubernetes** | v1.28–v1.32+ | Управляющий кластер (Management Cluster, bare-metal / VM) |
| **Crossplane** | v2.4+ (ветка v2.x) | Ядро Control Plane ([Crossplane: Обзор](./overview.md)) |
| **Провайдеры** | `provider-sql` v0.9+, `provider-kubernetes` v1.3+ | Управление СУБД ([provider-kubernetes](./provider_kubernetes_setup.md)) |
| **GitOps-инструмент** | Argo CD v2.12+ / v3.5+ или Flux v2.x | Контроллер непрерывной доставки из Git |
| **Хранилище секретов** | HashiCorp Vault v1.15+ или SOPS (age) | Безопасная передача учетных данных |
| **OCI-реестр** | Harbor v2.8+ / GitLab Registry | Локальный реестр для пакетов провайдеров и Configuration |
| **CLI-утилиты** | `crossplane`, `kubectl`, `argocd`, `flux` | Управление и локальное тестирование манифестов |

### Сценарий 1: Argo CD + Crossplane Claim для корпоративной СУБД (provider-sql)

Разработчики описывают абстрактный запрос на базу данных PostgreSQL, размещенную на существующем корпоративном HA-кластере Patroni / PostgreSQL.

#### 1. Платформенный слой: ProviderConfig для подключения к СУБД

```yaml
# platform/providers/postgres-providerconfig.yaml
apiVersion: postgresql.sql.crossplane.io/v1alpha1
kind: ProviderConfig
metadata:
  name: patroni-ha-cluster
spec:
  credentials:
    source: Secret
    secretRef:
      namespace: crossplane-system
      name: postgres-admin-creds
      key: password
  sslMode: require
  endpoint: patroni-pooler.internal.corp
  port: 5432
  database: postgres
  username: postgres_admin
```

#### 2. Платформенный слой: XRD и Composition (PostgreSQL Database)

```yaml
# platform/definitions/xrd-postgres.yaml
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: xpostgresqlinstances.database.internal.corp
spec:
  group: database.internal.corp
  names:
    kind: XPostgreSQLInstance
    plural: xpostgresqlinstances
  claimNames:
    kind: PostgreSQLInstance
    plural: postgresqlinstances
  versions:
    - name: v1alpha1
      served: true
      referenceable: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
                parameters:
                  type: object
                  properties:
                    databaseName:
                      type: string
                    encoding:
                      type: string
                      default: "UTF8"
                  required:
                    - databaseName
              required:
                - parameters
---
# platform/compositions/composition-postgres.yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: postgres-database-patroni
  labels:
    provider: sql
    engine: postgres
spec:
  compositeTypeRef:
    apiVersion: database.internal.corp/v1alpha1
    kind: XPostgreSQLInstance
  mode: Pipeline
  pipeline:
    - step: patch-and-transform
      functionRef:
        name: function-auto-ready
    - step: create-database
      functionRef:
        name: function-kcl
      input:
        apiVersion: kcl.fn.crossplane.io/v1beta1
        kind: KCLInput
        spec:
          source: |
            oxr = option("params").oxr
            dxr = option("params").dxr
            db_name = oxr.spec.parameters.databaseName
            
            items = [
              {
                apiVersion = "postgresql.sql.crossplane.io/v1alpha1"
                kind = "Database"
                metadata = {
                  name = db_name
                  annotations = {
                    "crossplane.io/external-name" = db_name
                  }
                }
                spec = {
                  deletionPolicy = "Orphan"
                  forProvider = {
                    encoding = oxr.spec.parameters.encoding
                  }
                  providerConfigRef = {
                    name = "patroni-ha-cluster"
                  }
                }
              }
            ]
```

#### 3. Прикладной слой: Claim в Git-репозитории команды разработки

```yaml
# app-repo/infrastructure/production/database-claim.yaml
apiVersion: database.internal.corp/v1alpha1
kind: PostgreSQLInstance
metadata:
  name: billing-db
  namespace: billing-production
spec:
  parameters:
    databaseName: billing_prod
    encoding: "UTF8"
  compositionSelector:
    matchLabels:
      provider: sql
      engine: postgres
  writeConnectionSecretToRef:
    name: billing-db-conn
```

#### 4. Настройка Argo CD Application

```yaml
# platform/argocd/apps/billing-infrastructure.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-infrastructure
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://gitlab.internal.corp/apps/billing-service.git
    targetRevision: main
    path: infrastructure/production
  destination:
    server: https://kubernetes.default.svc
    namespace: billing-production
  syncPolicy:
    automated:
      prune: false              # Защита от случайного удаления stateful-ресурсов
      selfHeal: true           # Автоисправление локального дрейфа в K8s
    syncOptions:
      - CreateNamespace=true
      - RespectIgnoreDifferences=true
```

#### 5. Проверка состояния

```bash
kubectl get claim,xpostgresqlinstances,database.postgresql.sql.crossplane.io -n billing-production
# → NAME                                                   READY   CONNECTION-SECRET   AGE
#   postgresqlinstance.database.internal.corp/billing-db   True    billing-db-conn     42s
#   
#   NAME                                                    READY   COMPOSITION                  AGE
#   xpostgresqlinstance.database.internal.corp/billing-db   True    postgres-database-patroni    45s
#   
#   NAME                                                    READY   SYNCED   AGE
#   database.postgresql.sql.crossplane.io/billing_prod      True    True     38s

argocd app get billing-infrastructure
# → Name:               argocd/billing-infrastructure
#   Project:            default
#   Server:             https://kubernetes.default.svc
#   Namespace:          billing-production
#   Status:             Healthy
#   Health:             Healthy
```

---

### Сценарий 2: Мультикластерное масштабирование через ApplicationSet (On-Premise Fleet)

Для развертывания типовых наборов инфраструктурных компонентов и провайдеров Crossplane по всему парку внутренних кластеров используется `ApplicationSet` с кластерным генератором:

```yaml
# platform/argocd/applicationsets/fleet-crossplane-providers.yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: fleet-crossplane-providers
  namespace: argocd
spec:
  generators:
    - clusters:
        selector:
          matchLabels:
            environment: production
            managed-by: platform-team
  template:
    metadata:
      name: 'crossplane-providers-{{name}}'
    spec:
      project: default
      source:
        repoURL: https://gitlab.internal.corp/platform/fleet-configuration.git
        targetRevision: main
        path: bundles/core-providers
      destination:
        server: '{{server}}'
        namespace: crossplane-system
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - ServerSideApply=true
```

Каждый целевой кластер получает идентичный набор проверенных пакетов провайдеров (`provider-kubernetes`, `provider-sql`), а параметры подключения передаются через аннотации секрета кластера в Argo CD.

---

### Сценарий 3: Динамические окружения (Review Apps) с локальными ресурсами

Паттерн автоматического выделения временных баз данных, схем и пространств имен для каждого Merge Request в GitLab CI:
- Генератор ApplicationSet `pullRequest` опрашивает локальный GitLab.
- Создается namespace `preview-mr-<id>`, куда доставляется Claim на выделенную базу данных.
- Crossplane через `provider-sql` создает изолированную БД за 2–3 секунды на существующем Patroni-кластере без развертывания тяжелых виртуальных машин.
- При закрытии MR ветка удаляется, ApplicationSet удаляет приложение, а финализатор Crossplane корректно освобождает базу данных.

Подробное пошаговое руководство с GitLab CI, скриптами очистки и сетевыми политиками см. в [Argo CD: Динамические окружения с Crossplane](../ArgoCD/dynamic_environments_crossplane.md).

---

### Сценарий 4: Bootstrap платформы — установка Crossplane, провайдеров и функций через GitOps

Для развертывания Control Plane с нуля используется фазирование через GitOps:

#### Вариант A: Развертывание через Argo CD с использованием Sync Waves

Манифесты платформенного репозитория организуются с аннотациями `argocd.argoproj.io/sync-wave`:

```yaml
# 1. Волна -1: HelmRelease Crossplane Core
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: crossplane-core
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
spec:
  project: default
  source:
    repoURL: https://charts.crossplane.io/stable
    chart: crossplane
    targetRevision: 2.4.0
    helm:
      values: |
        args:
          - --enable-composition-functions
  destination:
    server: https://kubernetes.default.svc
    namespace: crossplane-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
---
# 2. Волна 0: Провайдеры и функции из локального OCI Harbor
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-sql
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  package: harbor.internal.corp/crossplane/provider-sql:v0.9.0
  packagePullSecrets:
    - name: harbor-pull-secret
---
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-kcl
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  package: harbor.internal.corp/crossplane/function-kcl:v0.9.0
  packagePullSecrets:
    - name: harbor-pull-secret
---
# 3. Волна 1: ProviderConfig и ClusterSecretStore (применяются после регистрации CRD провайдером)
apiVersion: postgresql.sql.crossplane.io/v1alpha1
kind: ProviderConfig
metadata:
  name: patroni-ha-cluster
  annotations:
    argocd.argoproj.io/sync-wave: "1"
spec:
  credentials:
    source: Secret
    secretRef:
      namespace: crossplane-system
      name: postgres-admin-creds
      key: password
```

#### Вариант B: Развертывание через Flux с графом зависимостей `dependsOn`

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: crossplane-stable
  namespace: flux-system
spec:
  interval: 2h
  url: https://charts.crossplane.io/stable
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: crossplane
  namespace: flux-system
spec:
  interval: 1h
  chart:
    spec:
      chart: crossplane
      version: "2.4.x"
      sourceRef:
        kind: HelmRepository
        name: crossplane-stable
        namespace: flux-system
  install:
    createNamespace: true
  values:
    args:
      - --enable-composition-functions
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: crossplane-providers
  namespace: flux-system
spec:
  interval: 10m
  path: "./platform/providers"
  prune: true
  sourceRef:
    kind: GitRepository
    name: cluster-config
  dependsOn:
    - name: crossplane
  healthChecks:
    - apiVersion: pkg.crossplane.io/v1
      kind: Provider
      name: provider-sql
```

```bash
flux get kustomization crossplane-providers
# → NAME                 READY   STATUS
#   crossplane-providers True    Applied revision: main@sha1:e3f19c4d...

kubectl get providers.pkg.crossplane.io
# → NAME                 INSTALLED   HEALTHY   PACKAGE                                           AGE
#   provider-sql         True        True      harbor.internal.corp/crossplane/provider-sql:v0.9.0 3m
```

---

### Сценарий 5: Flux + Crossplane — OCI-артефакты, SOPS и Kustomization

В закрытых корпоративных сетях (air-gapped) манифесты Claim шифруются утилитой SOPS, а платформенные Compositions упаковываются в OCI Configuration:

```yaml
# 1. Платформа ссылается на локальный OCI Configuration
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: platform-onprem-database
spec:
  package: harbor.internal.corp/crossplane-configurations/postgres:v1.4.0
  packagePullSecrets:
    - name: harbor-pull-secret
---
# 2. Kustomization доставляет зашифрованные Claim
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: billing-claims
  namespace: flux-system
spec:
  interval: 5m
  path: "./claims/production"
  prune: true
  decryption:
    provider: sops
    secretRef:
      name: sops-age-key
  sourceRef:
    kind: GitRepository
    name: billing-infra-repo
  healthChecks:
    - apiVersion: database.internal.corp/v1alpha1
      kind: PostgreSQLInstance
      name: billing-db
      namespace: billing-production
```

```bash
flux reconcile kustomization billing-claims --with-source
# → ► fetching secret: flux-system/sops-age-key
#   ► decrypting 1 file(s) using sops
#   ✔ Kustomization reconciled successfully

kubectl get postgresqlinstances.database.internal.corp -n billing-production
# → NAME         READY   CONNECTION-SECRET   AGE
#   billing-db   True    billing-db-conn     1m
```

---

### Сценарий 6: Сборка и публикация Configuration-пакета в локальный OCI-реестр (Harbor)

Платформенные инженеры версионируют Compositions и XRD как OCI-образы. Структура директории `platform-pkg/`:
- `crossplane.yaml` — метаданные пакета и зависимости от провайдеров.
- `definition.yaml` — XRD.
- `composition.yaml` — Composition Pipeline.

```bash
# 1. Сборка пакета с помощью Crossplane CLI
crossplane xpkg build \
  --package-root ./platform-pkg \
  --package-file postgres-package.xpkg
# → built package postgres-package.xpkg

# 2. Аутентификация и публикация в корпоративный Harbor
docker login harbor.internal.corp -u platform-bot -p $HARBOR_ROBOT_SECRET
# → Login Succeeded

crossplane xpkg push \
  postgres-package.xpkg \
  harbor.internal.corp/crossplane-configurations/postgres:v1.4.0
# → pushed harbor.internal.corp/crossplane-configurations/postgres:v1.4.0

# 3. Проверка активации ревизии в кластере
kubectl get configurationrevisions.pkg.crossplane.io
# → NAME                                HEALTHY   REVISION   IMAGE
#   platform-onprem-database-a7b4c81    True      1          harbor.internal.corp/crossplane-configurations/postgres:v1.4.0
```

---

## Операции и команды

Сводка команд для повседневной эксплуатации и диагностики связки Crossplane и GitOps-контроллеров:

| Область | Команда | Назначение |
| :--- | :--- | :--- |
| **Crossplane CLI** | `crossplane render <claim.yaml> <comp.yaml> <funcs.yaml>` | Локальный пре-рендер Composition без обращения к кластеру K8s |
| **Crossplane CLI** | `crossplane beta validate <xrd.yaml> <comp.yaml>` | Проверка валидности схем XRD и связей Compositions |
| **Crossplane CLI** | `crossplane beta trace <claim-kind> <name> -n <ns>` | Построение полного дерева от Claim до XR и всех дочерних MR |
| **Argo CD CLI** | `argocd app diff <app-name>` | Проверка расхождения манифестов в кластере с Git |
| **Argo CD CLI** | `argocd app sync <app-name> --force --prune` | Принудительная ручная синхронизация приложения |
| **Flux CLI** | `flux reconcile kustomization <name> --with-source` | Немедленный опрос Git и повторное применение Kustomization |
| **Flux CLI** | `flux trace <resource-kind> <name> -n <ns>` | Трассировка источника доставки объекта в кластер |
| **Kubectl** | `kubectl get claim,composite,managed -A` | Общий просмотр всех ресурсов Crossplane во всех namespaces |
| **Kubectl** | `kubectl describe providerconfig <name>` | Диагностика статуса соединения провайдера с целевой инфраструктурой |

### Практические примеры выполнения команд

```bash
# Трассировка графа ресурсов для проблемного Claim
crossplane beta trace postgresqlinstance billing-db -n billing-production
# → NAME                                                  SYNCED   READY   STATUS
#   PostgreSQLInstance/billing-db (billing-production)   True     True    Available
#   └─ XPostgreSQLInstance/billing-db-7d84f               True     True    Available
#      └─ Database/billing_prod                           True     True    Available

# Проверка расхождения (дрейфа) манифестов в Argo CD
argocd app diff billing-infrastructure
# → ===== postgresql.sql.crossplane.io/Database billing-production/billing_prod ======
#   < unchanged >

# Проверка состояния провайдеров и их готовности
kubectl get providers.pkg.crossplane.io
# → NAME                  INSTALLED   HEALTHY   PACKAGE                                             AGE
#   provider-kubernetes   True        True      harbor.internal.corp/crossplane/provider-k8s:v1.3.0  2d
#   provider-sql          True        True      harbor.internal.corp/crossplane/provider-sql:v0.9.0  2d

# Диагностика ProviderConfig
kubectl describe providerconfig.postgresql.sql.crossplane.io patroni-ha-cluster
# → Name:         patroni-ha-cluster
#   API Version:  postgresql.sql.crossplane.io/v1alpha1
#   Kind:         ProviderConfig
#   Spec:
#     Endpoint:  patroni-pooler.internal.corp
#     Port:      5432
#     Ssl Mode:  require
#   Events:      <none>
```

---

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Claim вечно в `Progressing` / `Unknown`** | Отсутствует подходящая `Composition` или не совпали метки `compositionSelector`. | `kubectl describe claim <name> -n <ns>` (искать `cannot find composite resource: no matching composition`). | Проверить соответствие `matchLabels` в Claim и меток в объектах `Composition`; применить манифесты Слоя 1. |
| **Argo CD показывает постоянный `OutOfSync`** | Дрейф по системным полям `status.*`, аннотациям или late-initialized полям провайдера. | `argocd app diff <app-name>` покажет расхождения в поле `status` или `metadata`. | Настроить секцию `ignoreDifferences` в спецификации `Application` (см. «Лучшие практики»). |
| **Ошибка синхронизации `SyncFailed` при первичном деплое** | Гонка зависимостей: Claim применился раньше, чем провайдер зарегистрировал CRD в API-сервере. | Логи Argo CD: `the server could not find the requested resource`. | Использовать Sync Waves (`sync-wave: "0"` для провайдеров, `sync-wave: "2"` для Claim) или Flux `dependsOn`. |
| **Провайдер сообщает `connection refused` / `timeout`** | Сетевая изоляция: нет доступа из подов `crossplane-system` до эндпоинта СУБД/хоста. | `kubectl logs -n crossplane-system -l pkg.crossplane.io/provider=provider-sql --tail=50`. | Проверить NetworkPolicy, внутренние firewall-правила и DNS-резолвинг из кластера K8s до целевого сервиса. |
| **Удаление Claim или Namespace зависает** | Финализатор Crossplane не может завершить очистку из-за недоступности внешней СУБД. | `kubectl get claim <name> -n <ns> -o yaml` (проверить блок `metadata.finalizers`). | Если сервис выведен из эксплуатации: переключить `spec.deletionPolicy: Orphan`, либо вручную очистить `finalizers` через `kubectl edit`. |
| **Flux не расшифровывает SOPS-манифест** | Отсутствует Secret с age-ключом в неймспейсе `flux-system` или неверный публичный ключ. | `flux get kustomization <name>` (ошибка `age: no identity matched any of the recipients`). | Проверить наличие `sops-age-key` в `flux-system` и соответствие открытого ключа в файле `.sops.yaml`. |
| **Пакет провайдера в статусе `Healthy: False`** | Ошибка авторизации в корпоративном реестре (Harbor) при скачивании OCI-образа. | `kubectl describe provider <name>` (искать `ImagePullBackOff` или `401 Unauthorized`). | Создать `Secret` с `dockerconfigjson` в `crossplane-system` и прописать его в `spec.packagePullSecrets` объекта `Provider`. |

### Диагностика зависших финализаторов

Когда внешний инфраструктурный сервер недоступен, а пространство имен приложения удаляется через GitOps, удаление блокируется финализатором Crossplane (`finalizer.managedresource.crossplane.io`):

```bash
# 1. Поиск зависшего Managed Resource
kubectl get managed -n billing-production 2>/dev/null
# → NAME                                               READY   SYNCED   AGE
#   database.postgresql.sql.crossplane.io/billing_prod False   False    15m

# 2. Просмотр причин сбоя очистки
kubectl describe database.postgresql.sql.crossplane.io/billing_prod | grep -A 5 Events
# → Events:
#   Type     Reason               Message
#   Warning  CannotDeleteExternal dial tcp 10.10.20.15:5432: i/o timeout

# 3. Безопасный перевод в Orphan (отказ от физического удаления при сбое сети)
kubectl patch database.postgresql.sql.crossplane.io/billing_prod \
  --type='json' -p='[{"op": "replace", "path": "/spec/deletionPolicy", "value": "Orphan"}]'
# → patched

# 4. Если объект необходимо удалить принудительно:
kubectl patch database.postgresql.sql.crossplane.io/billing_prod \
  --type='merge' -p='{"metadata":{"finalizers":[]}}'
# → patched
```

---

## Лучшие практики

### Фазирование развертывания через Sync Waves в Argo CD

Для предотвращения ошибок первичного развертывания платформа должна инициализироваться строго упорядоченно. Рекомендуемая схема Sync Waves:

| Волна (`sync-wave`) | Развертываемые компоненты |
| :---: | :--- |
| **-2** | Namespace `crossplane-system`, ServiceAccounts, RBAC, секреты доступа к Harbor (`packagePullSecrets`) |
| **-1** | Crossplane Core HelmRelease, Custom Controller Settings |
| **0** | Пакеты провайдеров (`Provider`) и функции композиции (`Function`) |
| **1** | Секреты учетных данных (ESO ExternalSecret / SOPS), `ProviderConfig`, `ClusterSecretStore` |
| **2** | Платформенные абстракции: CompositeResourceDefinitions (XRD) и Compositions |
| **3** | Прикладные манифесты: CompositeResourceClaims (Claim) и клиентские рабочие нагрузки |

### Настройка ignoreDifferences для CRD Crossplane

Поскольку контроллеры Crossplane непрерывно обновляют блок `status`, а некоторые провайдеры модифицируют метаданные, Argo CD без должной настройки входит в бесконечный цикл синхронизации. Добавьте в спецификацию `Application` или глобально в ConfigMap `argocd-cm`:

```yaml
# В спецификации Application:
spec:
  ignoreDifferences:
    # Игнорирование статусов и аннотаций конфигурации у всех Claims
    - group: "*.crossplane.io"
      kind: "*"
      jsonPointers:
        - /status
        - /metadata/annotations/kubectl.kubernetes.io~1last-applied-configuration
    # Игнорирование полей статуса и late-initialized свойств Managed Resources
    - group: "*.sql.crossplane.io"
      kind: "*"
      jsonPointers:
        - /status
    - group: "*.kubernetes.crossplane.io"
      kind: "*"
      jsonPointers:
        - /status
```

Глобальная настройка в `argocd-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  resource.customizations.ignoreDifferences.all: |
    jsonPointers:
      - /status
```

Подробнее о механизмах diffing см. в [ignoreDifferences в Argo CD](../ArgoCD/synchronization/ignore_differences.md).

### Кастомные Lua Health Checks в Argo CD

По умолчанию Argo CD не распознает состояние готовности пользовательских CRD Crossplane (Claim и XR), считая их постоянно находящимися в статусе `Progressing`. Для отображения реального состояния здоровья добавьте Lua-скрипт в ConfigMap `argocd-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  resource.customizations.health.database.internal.corp_PostgreSQLInstance: |
    hs = {}
    if obj.status ~= nil and obj.status.conditions ~= nil then
      for i, condition in ipairs(obj.status.conditions) do
        if condition.type == "Ready" and condition.status == "True" then
          hs.status = "Healthy"
          hs.message = condition.message or "Resource is Ready"
          return hs
        end
        if condition.type == "Synced" and condition.status == "False" then
          hs.status = "Degraded"
          hs.message = condition.message or "Resource synchronization failed"
          return hs
        end
      end
    end
    hs.status = "Progressing"
    hs.message = "Waiting for Crossplane resource to become Ready"
    return hs
```

### Валидация манифестов и Pre-flight проверки в CI/CD

Ошибки в синтаксисе Composition или несоответствие полей OpenAPI-схеме XRD должны выявляться на этапе Merge Request до попадания в GitOps-пайплайн:

```bash
# 1. Локальный рендер ресурсов из Claim через Composition
crossplane render \
  ./claims/database-claim.yaml \
  ./compositions/composition-postgres.yaml \
  ./functions/function-kcl.yaml > rendered-resources.yaml
# → Managed Resources успешно сгенерированы

# 2. Строгая валидация сгенерированных манифестов по JSON-схемам CRD
kubeconform -strict -summary rendered-resources.yaml
# → Summary: 1 resource valid, 0 invalid, 0 errors

# 3. Server-side dry-run в тестовом кластере (проверка прав RBAC и конфликтов полей)
kubectl apply --dry-run=server -k ./platform/definitions
# → compositeresourcedefinition.apiextensions.crossplane.io/xpostgresqlinstances.database.internal.corp configured (server dry run)
```

### Сетевая безопасность и изоляция учетных данных провайдеров

1. **Принцип минимальных привилегий для провайдеров:**
   - Не используйте учетную запись суперпользователя СУБД (`postgres`) для всех операций. Создайте сервисного пользователя `crossplane_provisioner` с правами `CREATEDB` и `CREATEROLE`, ограниченного доступом только к базам данных приложений.
2. **Изоляция сетевого периметра:**
   - Ограничьте egress-трафик из пространства имен `crossplane-system` через `NetworkPolicy`. Поды провайдеров должны иметь сетевой доступ только к корпоративному Vault, целевым пулерам баз данных (PgBouncer/Patroni) и K8s API.
3. **Шифрование транзитного трафика:**
   - Обязательно используйте `sslMode: require` или `verify-full` в `ProviderConfig` с указанием доверенного корпоративного корневого сертификата (`CABundle`).

---

## Дополнительная информация

### Внутренние ссылки

- [Crossplane: Обзор](./overview.md) — фундаментальные концепции, архитектура и жизненный цикл Managed Resources.
- [Crossplane: Управление ресурсами Kubernetes](./provider_kubernetes_setup.md) — детальная настройка `provider-kubernetes` для мультикластерной оркестрации.
- [Argo CD: Динамические окружения с Crossplane](../ArgoCD/dynamic_environments_crossplane.md) — практическое руководство по Review Apps и интеграции с GitLab CI.
- [ignoreDifferences в Argo CD](../ArgoCD/synchronization/ignore_differences.md) — подавление ложного дрейфа и нормализация манифестов.
- [GitOps: Управление секретами и шифрование](../secrets_encryption.md) — настройка HashiCorp Vault, External Secrets Operator и Mozilla SOPS.
- [Composition Functions](./composition_functions.md) — разработка конвейеров композиции на KCL, Python и Go.
- [Резервное копирование и DR](./backup_dr.md) — стратегии резервного копирования и восстановления Control Plane через Velero.
- [Сравнение с Terraform и OpenTofu](./terraform_comparison.md) — детальный анализ pull-модели Crossplane против классического IaC.
- [Мультитенантность](./multi_tenancy.md) — изоляция команд разработчиков в Control Plane.
- [Usage Protection](./usage_protection.md) — защита зависимых ресурсов от случайного удаления через CRD `Usage`.

### Внешние ресурсы

- [Crossplane Official Documentation](https://docs.crossplane.io/latest/) — официальное руководство по архитектуре и пакетам Crossplane.
- [Argo CD Custom Resource Health Checks](https://argo-cd.readthedocs.io/en/stable/operator-manual/health/) — документация по написанию Lua-скриптов для кастомных CRD.
- [Flux OCI Artifacts Documentation](https://fluxcd.io/flux/cheatsheets/oci-artifacts/) — работа с OCI-репозиториями в GitOps-пайплайнах Flux.
- [External Secrets Operator Documentation](https://external-secrets.io/latest/) — интеграция Kubernetes с HashiCorp Vault.
