# Crossplane: Интеграция с GitOps

## Определения

**GitOps для инфраструктуры** — операционная модель, при которой Git-репозиторий является единственным источником правды для всей декларативной конфигурации инфраструктуры. Crossplane выступает в роли исполнительного механизма — **control plane** (плоскости управления), предоставляя Kubernetes-native API для облачных ресурсов, а GitOps-инструменты (Argo CD, Flux) обеспечивают автоматическую доставку и синхронизацию этого состояния в кластер.

Ключевой принцип связки: желаемое состояние описывается один раз в Git и доставляется в кластер **pull-моделью** (контроллеры сами опрашивают источник), а не push-моделью (CI запускает `kubectl apply`). При этом действуют **два независимых контура непрерывного согласования (reconciliation)**:

1. **GitOps-контур** сверяет манифесты в кластере с тем, что лежит в Git (при расхождении — возвращает к эталону, `selfHeal`/`prune`).
2. **Crossplane-контур** сверяет ресурсы в облаке с тем, что описано в манифестах (при расхождении — возвращает параметры облака к YAML).

В 2026 году эта связка является стандартом для построения **Internal Developer Platforms (IDP)**: разработчики запрашивают инфраструктуру через абстрактные `Claim`, не имея прямого доступа к облачным консолям и не работая с низкоуровневыми Terraform/CLI облака.

## Базовые концепции

### Разделение ответственности: два слоя GitOps

Эффективная интеграция строится на разделении репозиториев по ролям (Separation of Concerns). Важно понимать, что Crossplane сам по себе — тоже часть инфраструктуры, которую нужно доставить в кластер. Поэтому выделяют два слоя:

**Слой 1 — Платформенный (Bootstrap / Platform repo):**
*   **Содержимое:** сам Crossplane (Core), пакеты провайдеров (`Provider`/`Configuration` из OCI), `CompositeResourceDefinitions` (XRD), `Compositions` (или Composition Functions), настройки провайдеров (`ProviderConfig`), `ClusterSecretStore`/SOPS-ключи.
*   **Владелец:** Команда платформы (SRE/Platform Engineers).
*   **Задача:** Определение корпоративных стандартов и «золотых путей» (Golden Paths) инфраструктуры, управление жизненным циклом самого Crossplane.
*   **Доставляется:** GitOps-инструментом как любой другой манифест (Helm/Kustomize).

**Слой 2 — Потребительский (Application / Claims repo):**
*   **Содержимое:** `CompositeResourceClaims` (Claims) — запросы на конкретные ресурсы (БД, S3, очереди), а также манифесты самих приложений.
*   **Владелец:** Команды разработки.
*   **Задача:** Использование инфраструктуры как зависимости приложения через высокоуровневый API, определённый платформой.
*   **Доставляется:** GitOps-инструментом; низкоуровневые учётные данные облака здесь **никогда не хранятся**.

### Архитектура и схема взаимодействия

```text
┌───────────────────────┐         ┌──────────────────┐        ┌──────────────────────┐
│  Git (Platform repo)  │         │  GitOps Tool     │        │  Management Cluster  │
│  XRD/Composition/     │         │  Argo CD / Flux  │        │  (Crossplane Core +  │
│  Provider/Config      │────────▶│  Sync & Prune    │──────▶ │   Provider, reconcile)│
└───────────────────────┘         └──────────────────┘        └──────────┬───────────┘
                                                                          │ 3. Создание MR
┌───────────────────────┐         ┌──────────────────┐                   │
│  Git (Claims repo)    │         │  GitOps Tool     │                   ▼
│  CompositeResourceClaim│────────▶│  Sync & Prune    │────────▶   ┌──────────────────┐
└───────────────────────┘         └──────────────────┘        │  Облако (API)    │
                                                              │  Managed Resource│
                                                              └──────────────────┘
        Поток данных (упрощлённо):
        Claims repo ──▶ Claim в кластере ──▶ Crossplane создаёт XR ──▶
        Composition разворачивает MR ──▶ Provider вызывает облачный API ──▶ ресурс готов
```

Шаги на схеме:
1. Коммит Claim (или XRD/Composition) в соответствующий Git-репозиторий.
2. GitOps-инструмент обнаруживает изменение и применяет манифест в кластер (`kubectl apply` под капотом).
3. Контроллер Crossplane замечает новый объект и начинает цикл сверки: для Claim создаётся XR, по Composition — набор MR, провайдер вызывает API облака.
4. Облачный ресурс provisioning'ится; статус поднимается по цепочке MR → XR → Claim (`status.conditions[].type: Ready`).

### Роли: Crossplane против GitOps-инструмента

Инструменты не конкурируют, а дополняют друг друга, разделяя ответственность:

*   **GitOps-инструмент** отвечает только за *доставку* объектов в Kubernetes (из Git/OCI в кластер) и защиту от ручных правок манифестов в кластере. Он не знает семантики Crossplane и не взаимодействует с облаком.
*   **Crossplane** отвечает за *приведение облака* в соответствие с манифестами и поддержание этого состояния (reconcile, drift detection на стороне облака). Он не доставляет манифесты из Git.

Crossplane при этом **GitOps-агностичен**: в качестве доставщика манифестов подходит любой pull-based контроллер (Argo CD, Flux,甚至 простой `kubectl apply` в CI — но тогда теряется self-heal/prune).

### Поддерживаемые инструменты

| Инструмент | Преимущества в связке с Crossplane | Рекомендация |
| :--- | :--- | :--- |
| **Argo CD** | Отличная визуализация иерархии ресурсов (Claim → XR → MR) в UI и дереве приложения. Нативная поддержка `ApplicationSet` для мульти-окружений и мульти-кластеров. Кастомные Lua health checks для CRD Crossplane. | Для централизованных Control Plane с UI, multi-tenant и сложными политиками. |
| **Flux** | Нативная поддержка OCI-репозиториев (Crossplane Packages доставляются как OCI-артефакты). Встроенное прозрачное расшифровывание **SOPS**. Лучшее масштабирование на распределённые системы и Edge-кластеры (контроллеры шардируются). | Для распределённых систем, edge, «gitless» GitOps через OCI, когда UI не критичен. |

Оба инструмента используют идентичную pull-модель и корректно работают с CRD Crossplane (включая owner references, по которым удаляются зависимые MR при удалении Claim).

## Управление секретами

В GitOps-процессе секреты (пароли БД, ключи доступа облака) не должны храниться в Git в открытом виде. Для Crossplane типичны две задачи: (а) как **безопасно передать облачные креды в `ProviderConfig`** и (б) как **распространить сгенерированные Crossplane connection-секреты** дальше по платформе.

Общую настройку SOPS/ESO см. в [Шифрование секретов в GitOps](../secrets_encryption.md).

### External Secrets Operator (ESO) + HashiCorp Vault

ESO предоставляет два направления синхронизации, и их важно не путать:

**Паттерн A — `ExternalSecret` (pull, «внутрь»):** облачные креды хранятся в Vault, ESO вытягивает их в Kubernetes Secret, на который ссылается `ProviderConfig`. Это исключает коммит ключей облака в Git.

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: yc-provider-creds
  namespace: crossplane-system
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: yc-creds
    creationPolicy: Owner
  data:
    - secretKey: credentials
      remoteRef:
        key: secret/data/crossplane/yandex
        property: credentials   # поле в Vault, содержащее JSON сервисного аккаунта
---
apiVersion: yandex.cloud/v1alpha1
kind: ProviderConfig
metadata:
  name: default
spec:
  credentials:
    source: Secret
    secretRef:
      namespace: crossplane-system
      name: yc-creds
      key: credentials
```

**Паттерн B — `PushSecret` (push, «наружу»):** когда Crossplane создаёт БД, он пишет учётные данные в Kubernetes Secret через `writeConnectionSecretToRef`. `PushSecret` переносит этот секрет в Vault, чтобы другие приложения/команды могли забрать его оттуда централизованно.

```yaml
apiVersion: external-secrets.io/v1alpha1
kind: PushSecret
metadata:
  name: db-conn-to-vault
  namespace: production
spec:
  refreshInterval: 10s
  secretStoreRefs:
    - name: vault-backend
      kind: ClusterSecretStore
  selector:
    secret:
      name: db-conn-secret   # создан Crossplane через writeConnectionSecretToRef у Claim
  data:
    - match:
        remoteRef:
          remoteKey: secret/data/apps/inventory-db
          property: password
```

*Плюс подхода:* централизованное хранение, ротация и аудит секретов в Vault; Git остаётся свободным от кредов.

### Mozilla SOPS

Конфиденциальные манифесты (например, `ProviderConfig` с API-ключами, либо сам `ExternalSecret`/`Secret` с ключом) шифруются в Git, а контроллер расшифровывает их «на лету» перед применением.

*   **Flux:** поддерживает SOPS нативно. Нужен age-ключ в Secret `sops-age` в неймспейсе Flux, и блок `decryption: { provider: sops }` в `Kustomization` (пример — в Сценарии 5).
*   **Argo CD:** нативного расшифровывания нет; используется Config Management Plugin (CMP) с `helm-secrets`/`kustomize-sops` либо [kustomize](https://github.com/bitnami-labs/sealed-secrets) в связке с `argocd-cm`. Ключ SOPS монтируется в `argocd-repo-server`.

```yaml
# providerconfig-yc-encrypted.yaml — этот файл лежит в Git уже зашифрованным (sops)
apiVersion: yandex.cloud/v1alpha1
kind: ProviderConfig
metadata:
  name: default
spec:
  credentials:
    source: Secret
    secretRef:
      namespace: crossplane-system
      name: yc-creds
      key: credentials
```

*Плюс:* простота, секреты хранятся рядом с кодом в зашифрованном виде, проверяются в CI тем же ключом.

## Практические сценарии

### Предварительные требования

*   Kubernetes-кластер (Management Cluster), к которому есть доступ через `kubectl`.
*   **Crossplane v2.x** (актуально на 2026 год — v2.4), установленный в неймспейсе `crossplane-system`. Установку и концепции см. в [Crossplane: Обзор](./overview.md).
*   Установленный провайдер (например, [Yandex Cloud](./provider_yandex_cloud_setup.md)) с готовым `ProviderConfig`.
*   GitOps-инструмент: **Argo CD v2.12+ (или v3.x)** либо **Flux v2.x** (OCI/SOPS — GA).
*   CLI: `crossplane` (для `render`/`validate`), `kubectl`, `kubeconform` (опционально для CI).
*   Git-репозитории: платформенный (XRD/Composition/ProviderConfig) и потребительский (Claims).

> Замечание: XRD `PostgreSQLInstance` и соответствующая `Composition` с метками `provider: yandex-cloud, tier: production` из Сценария 1 должны уже быть применены из платформенного репозитория, иначе Claim останется `unknown`.

### Сценарий 1: Argo CD + Crossplane Claim (рекомендуемый подход)

Вместо управления низкоуровневыми ресурсами разработчики коммитят абстрактный `Claim`.

1.  **Создание Claim в Git (App repo):**

    ```yaml
    apiVersion: database.example.org/v1alpha1
    kind: PostgreSQLInstance
    metadata:
      name: inventory-db
      namespace: production
    spec:
      parameters:
        storageGB: 20
        version: "15"
      compositionSelector:
        matchLabels:
          provider: yandex-cloud
          tier: production
      writeConnectionSecretToRef:
        name: db-conn-secret
    ```

2.  **Настройка Argo CD Application:**

    ```yaml
    apiVersion: argoproj.io/v1alpha1
    kind: Application
    metadata:
      name: app-infrastructure
      namespace: argocd
    spec:
      project: default
      source:
        repoURL: https://github.com/org/app-infra-gitops.git
        targetRevision: main
        path: infrastructure/production
      destination:
        server: https://kubernetes.default.svc
        namespace: production
      syncPolicy:
        automated:
          prune: true
          selfHeal: true   # автоматическое исправление дрейфа в кластере
    ```

3.  **Проверка результата:**

    ```bash
    kubectl get claim,inventorydb.postgresql.example.org -n production
    # → NAME                                  READY  CONNECTION-SECRET
    #   postgresqlinstance.database.inventory-db  True   db-conn-secret

    kubectl get compositeresourcedefinition,xr,managed -n production 2>/dev/null | head
    # → иерархия Claim -> XR -> (набор) MR

    argocd app get app-infrastructure
    # → STATUS: Healthy | SYNC STATUS: Synced
    ```

### Сценарий 2: Масштабирование через ApplicationSet

Для управления множеством окружений (dev, staging, prod) или кластеров используются генераторы `ApplicationSet`. `list` — самый простой; в проде чаще применяют `cluster` (по секретам кластеров в Argo CD) или `git`/`scmProvider` (по структуре репозитория).

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: platform-stacks
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - env: dev
            cluster: https://kubernetes.default.svc
          - env: prod
            cluster: https://prod-cluster.example.com
  template:
    metadata:
      name: '{{env}}-stack'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/platform-manifests.git
        targetRevision: main
        path: 'stacks/{{env}}'
      destination:
        server: '{{cluster}}'
        namespace: crossplane-system
```

### Сценарий 3: Динамические окружения (Review Apps)

Связка ApplicationSet + Crossplane позволяет автоматически создавать полные стеки (приложение + БД + S3) для каждой ветки разработчика. Подробное пошаговое руководство с GitLab CI и `scmProvider`-генератором: **[Argo CD: Динамические окружения с Crossplane](../ArgoCD/dynamic_environments_crossplane.md)**.

### Сценарий 4: Bootstrap — установка Crossplane и провайдеров через GitOps

Прежде чем применять Claims, сам Crossplane и провайдеры должны попасть в кластер. Их тоже доставляет GitOps, причём провайдеры/конфигурации — как OCI-пакеты.

**Вариант A — Argo CD (Helm + Kustomize):**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: crossplane-platform
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/platform-repo.git
    targetRevision: main
    path: crossplane
  destination:
    server: https://kubernetes.default.svc
    namespace: crossplane-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

В `platform-repo/crossplane/` лежат: `Provider` (тянут пакет из OCI) и `Configuration` (композиции упакованы в OCI) + `ProviderConfig`.

```yaml
# crossplane/provider-yandex.yaml — установка провайдера как OCI-пакета
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-yandex-cloud
spec:
  package: xpkg.upbound.io/yandexcloud/crossplane-provider-yc:v0.14.1
  # packagePullSecrets:                # если реестр приватный
  #   - name: registry-pull-secret
```

**Вариант B — Flux (HelmRepository + HelmRelease + Kustomization):**

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: crossplane-stable
  namespace: flux-system
spec:
  interval: 1h
  url: https://charts.crossplane.io/stable
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: crossplane
  namespace: flux-system
spec:
  interval: 30m
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
    args: ["--enable-composition-functions"]
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: crossplane-platform
  namespace: flux-system
spec:
  interval: 10m
  path: "./platform/crossplane"
  prune: true
  sourceRef:
    kind: GitRepository
    name: cluster-config
  dependsOn:
    - name: crossplane          # сначала поднимается Crossplane, затем платформенные манифесты
```

Применение и проверка:

```bash
flux get kustomization crossplane-platform
# → NAME                  READY  STATUS
#   crossplane-platform   True   Applied revision main@sha1...

kubectl get providers
# → NAME                    INSTALLED  HEALTHY  PACKAGE
#   provider-yandex-cloud   True       True     xpkg.crossplane.io/.../v0.11.0
```

### Сценарий 5: Flux + Crossplane — OCI-пакеты, SOPS и Kustomization

Полный пример потребительского слоя на Flux: Claims доставляются из Git с прозрачной расшифровкой SOPS, а платформенные композиции — как OCI Configuration-пакет.

```yaml
# 1) Платформа ссылается на Configuration-пакет в OCI (XRD/Composition внутри образа)
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: platform-postgres
spec:
  package: oci://ghcr.io/org/crossplane-platform:v1.2.3
  # packagePullSecrets:
  #   - name: registry-pull
---
# 2) Kustomization доставляет Claims и расшифровывает SOPS
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: app-claims
  namespace: flux-system
spec:
  interval: 5m
  path: "./claims/production"
  prune: true
  decryption:
    provider: sops
    secretRef:
      name: sops-age          # age-ключ SOPS в неймспейсе flux-system
  sourceRef:
    kind: GitRepository
    name: app-config
  healthChecks:              # Flux дождётся готовности CRD Crossplane
    - apiVersion: database.example.org/v1alpha1
      kind: PostgreSQLInstance
      name: inventory-db
      namespace: production
```

```bash
flux get kustomization app-claims
# → NAME         READY  STATUS
#   app-claims    True   Applied revision main@sha1...

kubectl get postgresqlinstance -n production
# → NAME           READY  CONNECTION-SECRET
#   inventory-db   True   db-conn-secret
```

> Альтернатива «gitless» GitOps: упакуйте сами манифесты Claims/Kustomization в OCI (`flux push artifact oci://...`) и применяйте через `OCIRepository` + `Kustomization` с `sourceRef.kind: OCIRepository`. Подробнее: Flux OCI cheatsheet (ссылка в «Внешних ресурсах»).

### Сценарий 6: Публикация Configuration-пакета в OCI-реестр

Вместо хранения сырых YAML-файлов композиций в Git, их упаковывают в **Crossplane Configuration Package** и публикуют в OCI-реестр. Это даёт версионирование инфраструктурных модулей, как у Helm-чартов, и позволяет Flux/Argo CD отслеживать новые версии.

```bash
# 1) Сборка пакета (требуется crossplane CLI; корень — crossplane.yaml + Composition/XRD)
crossplane xpkg build --package-root ./platform --package-file platform.xpkg
# → built package platform.xpkg

# 2) Публикация в реестр (пакет — это OCI-образ)
crossplane xpkg push platform.xpkg oci://ghcr.io/org/crossplane-platform:v1.2.3
# → pushed ghcr.io/org/crossplane-platform:v1.2.3

# 3) В кластере Configuration ссылается на тег; при появлении новой версии Crossplane
#    создаёт новую ревизию и (по revisionActivationPolicy) активирует её
kubectl get configurationrevisions
# → NAME                            HEALTHY  REVISION  IMAGE
#   platform-postgres-v1.2.3        True     1         ghcr.io/org/crossplane-platform:v1.2.3
```

Для приватного реестра создайте `packagePullSecrets` (Secret типа `dockerconfigjson`) в неймспейсе Crossplane и укажите его в `spec.packagePullSecrets` объекта `Configuration`/`Provider`.

## Передовые практики (2026)

### Валидация в CI (Pre-flight checks)

Перед синхронизацией манифестов в кластер их проверяют локально, чтобы не ломать прод через невалидную композицию:

```bash
# Локальный рендер композиции — что именно создаст Crossplane из Claim
crossplane render --xrd ../xrd.yaml --composition ../composition.yaml --resources ./claim.yaml
# → вывод итоговых Managed Resources (MR), включая projected connection secret

# Валидация по схемам CRD и политикам (если подключён провайдер политик)
crossplane beta validate --xrd ../xrd.yaml --composition ../composition.yaml --resources ./claim.yaml
# → VALID: Composition is valid

# Валидация всего Kustomize/YAML перед синком (без кластера)
kubectl kustomize ./infra | kubeconform -strict -summary
# → Summary: 12 resources validated

# Server-side dry-run (требует доступа к кластеру; ловит конфликты API)
kubectl apply --dry-run=server -k ./infra
# → configured / unchanged
```

Дополнительно в CI применяют интеграционные тесты (kuttl) на ephemeral-кластере и `conftest`/Kyverno для политик (см. [Управление политиками через GitOps](../Concepts/gitops-policy-management.md)).

### Настройка Health Checks в Argo CD

Argo CD не имеет встроенных health-проверок для CRD Crossplane, поэтому Claim/XR будут вечно `Progressing`, пока не добавлена кастомная Lua-проверка. Её кладут в `resource.customizations.health.<group>_<kind>` ConfigMap `argocd-cm`:

```yaml
resource.customizations.health.database.example.org_PostgreSQLInstance: |
  hs = {}
  if obj.status ~= nil and obj.status.conditions ~= nil then
    for i, condition in ipairs(obj.status.conditions) do
      if condition.type == "Ready" and condition.status == "True" then
        hs.status = "Healthy"
        hs.message = condition.message
        return hs
      end
    end
  end
  hs.status = "Progressing"
  hs.message = "Waiting for resource to be ready"
  return hs
```

*   Для группы провайдеров удобен wildcard: `resource.customizations.health."*.aws.crossplane.io/*"` (через ключ `resource.customizations`, а не `...health.<g>_<k>`).
*   Аналогично настраиваются проверки для XR (`composite...`) и MR (`*.yandex.cloud/*`), чтобы дерево приложения корректно отображало готовность.

### ignoreDifferences для Crossplane

Crossplane постоянно пишет в `status.*` (conditions, observed, connection details), а некоторые провайдеры возвращают поздно-инициализированные (late-initialized) поля в `spec.forProvider`. Argo CD будет показывать вечный `OutOfSync`. Исключите эти поля:

```yaml
spec:
  ignoreDifferences:
    - group: "*.crossplane.io"
      kind: CompositeResourceClaim
      jsonPointers:
        - /status
        - /metadata/annotations/last-applied-configuration
    - group: "*.yandex.cloud"
      kind: "*"
      jsonPointers:
        - /status
```

### Политики удаления (Deletion Policy) и managementPolicies

Явно определяйте поведение при удалении манифеста из Git:
*   `DeletionPolicy: Delete` (по умолчанию) — физическое удаление ресурса в облаке вместе с объектом Kubernetes.
*   `DeletionPolicy: Orphan` — удаляется только объект в Kubernetes, облачный ресурс остаётся. Рекомендуется для критических БД в Prod, чтобы ошибка в GitOps-пайплайне не уничтожила данные.

```yaml
# на уровне MR (в Composition) или Claim
spec:
  deletionPolicy: Orphan
```

Для безопасного подключения существующей инфраструктуры используйте `managementPolicies` (v2): `ObserveOnly` позволяет Crossplane только читать облако без изменений, `*` (все действия) — поведение по умолчанию. Finalizers Crossplane гарантируют корректный очистной цикл в облаке перед удалением объекта.

### Доставка через OCI-артефакты

Хранение композиций в Configuration Package (Сценарий 6) обеспечивает версионирование инфраструктурных модулей аналогично Helm-чартам; Flux/Argo CD отслеживают новые теги и обновляют ресурс `Configuration`. Это особенно удобно для air-gapped сред и централизованного распространения модулей между кластерами.

## Исправление дрейфа (Drift Detection)

Связка Crossplane + GitOps обеспечивает двухуровневую защиту от ручных изменений:

1.  **Уровень GitOps (Argo CD/Flux):** если кто-то изменил манифест Crossplane в кластере через `kubectl edit`, GitOps-инструмент обнаружит расхождение с Git (`OutOfSync`) и вернёт манифест к эталону (`selfHeal` / Flux reconcile). Flux проверяется командой `flux get kustomization <name>`; Argo CD — `argocd app diff <name>`.
2.  **Уровень Crossplane:** если параметры ресурса изменены напрямую в консоли облака, контроллер Crossplane в ходе очередного цикла сверки обнаружит расхождение с `spec.forProvider` и вернёт параметры облака к описанным в YAML (зависит от `managementPolicies`).

```bash
# Диагностика расхождения на стороне Crossplane
crossplane alpha trace claim postgresqlinstance inventory-db -n production
# → дерево Claim → XR → MR с текущим и желаемым состоянием

kubectl describe mr <имя-mr> -n production | grep -A5 "Events\|Last Transition"
# → события reconcile: Observed, Created, Ready
```

**Ограничения:** Crossplane отслеживает дрейф только по полям, которыми он управляет (`spec.forProvider` и связанные), и с периодичностью poll-интервала провайдера — мгновенного webhook-детекта нет. Поля, не входящие в схему провайдера, Crossplane не увидит. Для pure-drift-наблюдения без правок используйте `managementPolicies: ["ObserveOnly"]`.

## Устранение неполадок

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Claim вечно `Unknown`/`Progressing` | Нет подходящей Composition (метки `compositionSelector` не совпали) или XRD ещё не применён | `kubectl get xrd,composition`; сверить метки; применить платформенный манифест из Сценария 4 |
| Argo CD вечный `OutOfSync` на Claim | Дрейф по `status.*` / late-initialized полям | Добавить `ignoreDifferences` (раздел выше) |
| `ProviderConfig` не `Healthy` | Неверный Secret/creds или нет сети до облака | `kubectl describe providerconfig`, проверить `ExternalSecret`/SOPS и логи провайдера |
| MR не создаётся | Ошибка в Composition (ссылка на несуществующее поле XRD) | `crossplane render` + `crossplane beta validate` в CI; `kubectl describe xr` |
| Удаление Claim «висит» | Finalizer ждёт очистки в облаке / `DeletionPolicy` | `kubectl get events` провайдера; при необходимости `Orphan` для критичных БД |
| Flux не расшифровывает SOPS | Нет Secret `sops-age` или блок `decryption` | Создать age-ключ в `flux-system`, добавить `decryption.provider: sops` в Kustomization |

## Дополнительная информация

*   Обзор Crossplane и жизненный цикл MR: [Crossplane Overview](./overview.md)
*   Настройка провайдеров: [Yandex Cloud Setup](./provider_yandex_cloud_setup.md), [Kubernetes Setup](./provider_kubernetes_setup.md)
*   Динамические окружения: [Argo CD: Динамические окружения с Crossplane](../ArgoCD/dynamic_environments_crossplane.md)
*   Шифрование секретов (SOPS/ESO): [Шифрование секретов в GitOps](../secrets_encryption.md)
*   Тематические разделы: [Composition Functions](./composition_functions.md), [Мультитенантность](./multi_tenancy.md), [Usage](./usage_protection.md), [Тестирование](./testing_crossplane.md), [Обновление/миграция](./upgrade_migration.md), [Observability](./observability.md), [Политики](./policy_governance.md), [Self-Service/IDP](./self_service.md), [Безопасность цепочки поставок](./package_security.md), [Backup/DR](./backup_dr.md)

Внешние ресурсы:
* [Crossplane: Configurations (OCI-пакеты)](https://docs.crossplane.io/latest/packages/configurations/)
* [Argo CD: Custom Resource Health](https://argo-cd.readthedocs.io/en/stable/operator-manual/health/)
* [Flux: OCI Artifacts cheatsheet](https://fluxcd.io/flux/cheatsheets/oci-artifacts/)
