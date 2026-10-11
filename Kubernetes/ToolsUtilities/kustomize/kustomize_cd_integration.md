# Интеграция Kustomize в конвейеры CD

Интеграция Kustomize в конвейеры непрерывного развертывания (CD) обеспечивает автоматизированное, декларативное и воспроизводимое управление конфигурациями Kubernetes для различных окружений. Документ описывает практические модели доставки, типовые шаблоны CI/CD-пайплайнов и шаблоны GitOps-контроллеров, фокусируясь на on-prem/devops/sre/sysadmin-сценариях (без интеграции с managed-сервисами облачных провайдеров).

## 1. Определения

**Kustomize CD Integration** — процесс автоматического рендеринга и применения манифестов Kubernetes, настроенных через Kustomize, в целевые кластеры в рамках конвейера доставки.

**Push-модель (CI-driven)** — стратегия, при которой внешний конвейер (Jenkins, GitLab CI, GitHub Actions) активно подключается к кластеру и выполняет `kubectl apply -k`.

**Pull-модель (GitOps-driven)** — стратегия, при которой специальный агент внутри кластера (ArgoCD, Flux) отслеживает изменения в Git и самостоятельно синхронизирует состояние кластера с описанным в репозитории.

**Dry-run (Валидация)** — этап проверки сгенерированных манифестов на соответствие схемам Kubernetes API и политикам безопасности без их фактического применения.

**Overlay (оверлей)** — директория Kustomize, наследующая `resources` от base-каталога и применяющая патчи/генераторы, специфичные для конкретной среды (dev/stage/prod), региона или тенанта.

**Kustomize Edit (Image Tag Injection)** — программное изменение поля `images` в `kustomization.yaml` через подкоманды `kustomize edit set image`/`kustomize edit set tag` для внедрения актуальной версии образа в CD-пайплайне.

**ConfigMap/Secret Hash Suffix** — автоматически генерируемый Kustomize хеш-суффикс в имени ресурса при использовании `configMapGenerator`/`secretGenerator`, обеспечивающий триггер `RollingUpdate` Deployment'а при изменении содержимого ConfigMap/Secret.

**Server-Side Apply (SSA)** — режим `kubectl apply --server-side`, при котором атрибуция манифеста и merge-логика происходят на стороне kube-apiserver; рекомендуется для GitOps-контроллеров и больших манифестов.

**Drift (дрейф конфигурации)** — расхождение между состоянием, описанным в Git, и фактическим состоянием кластера, вызванное ручными изменениями (`kubectl edit`, прямой `kubectl patch` или откатом контроллера).

## 2. Основные концепции

### Модели доставки

| Характеристика | Push-модель (CI-driven) | Pull-модель (GitOps) |
| :--- | :--- | :--- |
| **Инструменты** | Jenkins, GitLab CI, GitHub Actions, Tekton, Drone, Woodpecker | ArgoCD, Flux |
| **Доступ** | Требуются учетные данные кластера в CI | Агент уже внутри кластера |
| **State Drift** | Сложно отследить ручные изменения | Автоматическое исправление (Self-healing) |
| **Безопасность** | Широкий доступ для CI-раннеров | Минимальный доступ (только к Git) |
| **Скорость доставки** | Низкая латентность (прямой apply) | Задержка 1–3 мин (polling/webhook) |
| **Стоимость трафика** | Прямое подключение к API-server | Агент в кластере → нет внешнего доступа |
| **Audit trail** | Журнал CI-системы | Журнал Git + журнал контроллера |
| **Сложность инфраструктуры** | Низкая | Требует установки контроллера |
| **Обратимость** | `git revert` + `kubectl rollout undo` | `git revert` + `argocd app rollback` / `flux suspend` |

Гибридная модель (CI для рендера → GitOps для применения) становится стандартом: CI собирает манифесты и пушит их в GitOps-репозиторий, а контроллер применяет в кластер.

### Разделение ответственности

В зрелых процессах рекомендуется разделять репозиторий с исходным кодом приложения и репозиторий с конфигурациями Kubernetes. CI-пайплайн обновляет тег образа в `kustomization.yaml` (через `kustomize edit set image`), а CD-инструмент применяет изменения.

Типичный layout для корпоративной среды:

```text
app-repo/                          # исходный код
├── Dockerfile
├── src/
└── ...

infra-repo/                        # GitOps-репозиторий
├── base/
│   └── my-app/
│       ├── kustomization.yaml
│       ├── deployment.yaml
│       └── service.yaml
└── overlays/
    ├── dev/
    ├── staging/
    └── production/
```

Также распространена обратная модель — **mono-repo**, где конфигурации и код лежат рядом (`app/k8s/overlays/...`). Подходит для небольших команд; упрощает локальную разработку и PR-review.

### Стратегии продвижения релизов через Kustomize

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Branch promotion** | Каждая среда — отдельная ветка (`dev`, `stage`, `main`) | Простые пайплайны, малая команда |
| **Directory promotion** | Все среды в одной ветке, разные `overlays/`, тег в `kustomization.yaml` меняется в коммите | Стандартный GitOps (ArgoCD/Flux читают `HEAD`) |
| **Tag promotion** | Git-tag определяет версию overlay (`overlays/production` читает `tag: v1.4.2`) | Команды с релизным циклом (semver) |
| **Helm-style release** | CI собирает архив, ArgoCD sync на архив (OCI/HTTP) | Требуется аудит и reproducibility |

В любой стратегии ключевая инвариантность — `base/` никогда не меняется изолированно: все окружения получают изменения атомарно через merge в ветку/каталог.

### Хеширование имен в CD

Использование `configMapGenerator` и `secretGenerator` является критическим для CD. Kustomize автоматически добавляет хеш к имени ресурса, что гарантирует запуск **Rolling Update** при изменении конфигурации, исключая ситуации, когда поды используют устаревшие данные.

**Пример** (`base/kustomization.yaml`):

```yaml
configMapGenerator:
  - name: app-config
    files:
      - application.properties
      - logback.xml
secretGenerator:
  - name: app-secrets
    files:
      - db-password.txt
    options:
      disableNameSuffixHash: false   # значение по умолчанию, явно для документации
```

После `kustomize build` создаются ресурсы с именами `app-config-7d2f8c9b4h` и `app-secrets-k2j8s3m9xk`. При изменении любого файла хеш пересчитывается → Deployment получает новую аннотацию `configMapHash` → kubelet создает новые поды с актуальной конфигурацией.

### Image Tag Injection

В CD-пайплайнах изменение версии образа — самая частая операция. Правильный путь через Kustomize:

```bash
# Обновить тег в overlays/production/kustomization.yaml
kustomize edit set image myapp=registry.internal/finance/billing-api:v1.7.3

# Проверить результат
kustomize build overlays/production | grep "image:"
# → image: registry.internal/finance/billing-api:v1.7.3
```

Альтернатива — `kustomize edit set tag` (для тегов) и `kustomize edit set digest` (для immutable digest'ов в supply-chain). При работе с digest'ами рекомендуется всегда комбинировать digest + tag для совместимости с `kubectl rollout history`.

### Server-Side Apply vs Client-Side Apply

| Режим | Команда | Поведение | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Client-side** (по умолчанию) | `kubectl apply -k` или `kubectl apply -f -` | Client сохраняет `last-applied-configuration` в аннотации; merge-логика на стороне kubectl | Простые CI-pipelines, малый объем |
| **Server-side apply** | `kubectl apply -k --server-side` | Merge-логика на стороне kube-apiserver; `fieldManager` идентифицирует владельца | GitOps-контроллеры, совместное редактирование несколькими акторами, большие манифесты (>3 МБ) |

В GitOps (ArgoCD, Flux) SSA включен по умолчанию. В push-моделях (CI) выбор остается за оператором, но для манифестов, которые также редактируются вручную или HPA-контроллером, SSA предпочтительнее.

## 3. Практические сценарии

### 3.1. Сценарий 1: Push-модель через GitHub Actions

Пример рабочего процесса, который валидирует и применяет манифесты.

```yaml
name: Deploy to Staging
on:
  push:
    branches: [ main ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Kustomize
        run: |
          curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
          sudo mv kustomize /usr/local/bin/

      - name: Validate Manifests (Dry-run)
        run: kustomize build overlays/staging | kubectl apply --dry-run=client -f -

      - name: Deploy
        run: kustomize build overlays/staging | kubectl apply -f -
```

**Расширение для production с подтверждением и image-injection:**

```yaml
name: Deploy to Production
on:
  workflow_dispatch:
    inputs:
      image_tag:
        description: 'Image tag (например, v1.7.3)'
        required: true

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production     # требует approve в GitHub UI
    steps:
      - uses: actions/checkout@v4

      - name: Set up Kustomize
        run: |
          curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
          sudo mv kustomize /usr/local/bin/

      - name: Update image tag
        working-directory: overlays/production
        run: |
          kustomize edit set image myapp=registry.internal/finance/billing-api:${{ github.event.inputs.image_tag }}
          kustomize edit set tag myapp:${{ github.event.inputs.image_tag }}
          cat kustomization.yaml

      - name: Dry-run
        run: kustomize build overlays/production | kubeconform -strict -summary

      - name: Diff against cluster
        run: |
          kustomize build overlays/production > /tmp/manifest.yaml
          kubectl diff -f /tmp/manifest.yaml || true

      - name: Apply
        run: kustomize build overlays/production | kubectl apply -f -
```

### 3.2. Сценарий 2: Push-модель через Jenkins Pipeline

Расширенный пример с ручным подтверждением для Production.

```groovy
pipeline {
    agent any
    stages {
        stage('Checkout') {
            steps {
                git 'https://your-repo-url.git'
            }
        }
        stage('Build & Validate') {
            steps {
                sh 'kustomize build overlays/staging > staging-manifest.yaml'
                sh 'kustomize build overlays/production > production-manifest.yaml'
                // Валидация через kubeconform
                sh 'kustomize build overlays/staging | kubeconform -strict'
            }
        }
        stage('Deploy to Staging') {
            steps {
                sh 'kubectl apply -k overlays/staging/'
            }
        }
        stage('Promote to Production') {
            steps {
                input message: 'Promote to Production?'
                sh 'kubectl apply -k overlays/production/'
            }
        }
    }
}
```

**Улучшенная версия с шагами dry-run, diff, snapshot:**

```groovy
pipeline {
    agent { label 'k8s-deploy' }
    options {
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '30'))
    }
    environment {
        KUBECONFIG = credentials('kubeconfig-production')
    }
    parameters {
        string(name: 'IMAGE_TAG', defaultValue: 'latest', description: 'Тег образа')
    }
    stages {
        stage('Checkout') {
            steps { checkout scm }
        }
        stage('Update image tag') {
            steps {
                dir('overlays/production') {
                    sh "kustomize edit set image myapp=registry.internal/finance/billing-api:${params.IMAGE_TAG}"
                }
            }
        }
        stage('Validate (kubeconform)') {
            steps {
                sh 'kustomize build overlays/production | kubeconform -strict -summary -verbose'
            }
        }
        stage('Dry-run (server)') {
            steps {
                sh 'kustomize build overlays/production | kubectl apply --dry-run=server -f -'
            }
        }
        stage('Diff') {
            steps {
                sh '''
                    kustomize build overlays/production > /tmp/manifest.yaml
                    kubectl diff -f /tmp/manifest.yaml > /tmp/diff.patch || true
                '''
                archiveArtifacts artifacts: '/tmp/diff.patch', allowEmptyArchive: true
            }
        }
        stage('Snapshot') {
            steps {
                sh '''
                    mkdir -p snapshots/$BUILD_NUMBER
                    kustomize build overlays/production > snapshots/$BUILD_NUMBER/manifest.yaml
                '''
                archiveArtifacts artifacts: 'snapshots/**', fingerprint: true
            }
        }
        stage('Deploy to Production') {
            steps {
                input message: "Promote ${params.IMAGE_TAG} to production?"
                sh 'kubectl apply -k overlays/production/'
            }
        }
    }
    post {
        failure {
            // Уведомление через mail/Slack
        }
    }
}
```

### 3.3. Сценарий 3: Pull-модель через ArgoCD

ArgoCD нативно поддерживает Kustomize. Достаточно указать путь к директории.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app-staging
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://github.com/my-org/my-infra.git'
    targetRevision: HEAD
    path: overlays/staging
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: staging
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**Расширенная версия с Kustomize-параметрами, ignoreDifferences, sync windows:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-api-production
  namespace: argocd
  annotations:
    notifications.argoproj.io/subscribe.on-deployed.slack: argocd-deploys
spec:
  project: finance-team
  source:
    repoURL: 'https://github.com/my-org/infra-gitops.git'
    targetRevision: main
    path: apps/billing/overlays/production
    # Kustomize-specific (argo-cd ≥ 2.6)
    kustomize:
      namePrefix: prod-
      commonAnnotations:
        owner: sre-team
      commonLabels:
        env: production
      forceCommonLabels: false    # отключает вырезание commonLabels из selectors (kubelet < 1.27)
      images:
        - myapp=registry.internal/finance/billing-api:v1.7.3
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: billing
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
      allowEmpty: false
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
      - PrunePropagationPolicy=foreground
      - PruneLast=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
  revisionHistory:
    limit: 10
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas           # HPA управляет
        - /spec/template/spec/containers/0/resources    # VPA/limits-контроллер
    - group: autoscaling
      kind: HorizontalPodAutoscaler
      jsonPointers:
        - /status
```

**Multi-source (Helm + Kustomize одновременно)** — поддерживается через `sources` (argo-cd ≥ 2.4). Это полезно, если base-слой описывается Helm-чартом, а overlay — Kustomize:

```yaml
spec:
  sources:
    - repoURL: 'https://charts.example.com/'
      chart: my-app
      targetRevision: 1.7.3
      helm:
        valueFiles:
          - $values/overlays/production/values.yaml
    - repoURL: 'https://github.com/my-org/infra-gitops.git'
      targetRevision: main
      path: overlays/production
      # kustomize без параметров — накладывается поверх результата helm template
```

### 3.4. Сценарий 4: Pull-модель через Flux v2

Flux v2 имеет выделенный контроллер **kustomize-controller**, который работает с ресурсами `Kustomization`:

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: infra-gitops
  namespace: flux-system
spec:
  interval: 5m
  url: https://github.com/my-org/infra-gitops.git
  ref:
    branch: main
  secretRef:
    name: flux-git-creds     # basic-auth или SSH-key
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: billing-api-production
  namespace: flux-system
spec:
  interval: 10m
  sourceRef:
    kind: GitRepository
    name: infra-gitops
  path: ./apps/billing/overlays/production
  prune: true
  wait: true
  timeout: 5m
  force: false
  healthChecks:
    - apiVersion: apps/v1
      kind: Deployment
      name: billing-api
      namespace: billing
  postBuild:
    substituteFrom:
      - kind: ConfigMap
        name: cluster-vars
    substitute:
      cluster_name: production-eu-west
  decryption:
    provider: sops
    secretRef:
      name: sops-keys
```

**Health checks и задержки** — критичны для production-роллаутов. Без `healthChecks` Flux пометит ресурсы `Ready` сразу после `kubectl apply`, и следующее обновление начнется до того, как поды станут `Ready`. Рекомендуется всегда указывать `healthChecks` для критичных Deployment'ов и Job'ов.

### 3.5. Сценарий 5: CI-системы (GitLab CI, Tekton, Drone, Woodpecker)

**GitLab CI** (`.gitlab-ci.yml`):

```yaml
stages:
  - validate
  - deploy

variables:
  KUSTOMIZE_VERSION: "5.4.3"

.kustomize_setup: &kustomize_setup
  image:
    name: registry.internal/ci/kustomize:${KUSTOMIZE_VERSION}
    entrypoint: [""]
  before_script:
    - kustomize version

deploy:staging:
  stage: deploy
  <<: *kustomize_setup
  script:
    - cd overlays/staging
    - kustomize edit set image myapp=registry.internal/finance/billing-api:${CI_COMMIT_TAG}
    - kustomize build . | kubeconform -strict
    - kustomize build . | kubectl apply -f -
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

deploy:production:
  stage: deploy
  <<: *kustomize_setup
  script:
    - cd overlays/production
    - kustomize edit set image myapp=registry.internal/finance/billing-api:${CI_COMMIT_TAG}
    - kustomize build . > /tmp/manifest.yaml
    - kubectl apply --dry-run=server -f /tmp/manifest.yaml
    - kubectl diff -f /tmp/manifest.yaml
    - kubectl apply -f /tmp/manifest.yaml
  environment:
    name: production
  when: manual
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
```

**Tekton** (PipelineRun):

```yaml
apiVersion: tekton.dev/v1beta1
kind: Task
metadata:
  name: kustomize-apply
spec:
  workspaces:
    - name: source
  params:
    - name: overlay-path
      type: string
    - name: image-tag
      type: string
    - name: kubeconfig-secret
      type: string
  steps:
    - name: update-image
      image: registry.internal/ci/kustomize:5.4.3
      workingDir: $(workspaces.source.path)
      script: |
        cd $(params.overlay-path)
        kustomize edit set image myapp=registry.internal/finance/billing-api:$(params.image-tag)
    - name: validate
      image: registry.internal/ci/kustomize:5.4.3
      workingDir: $(workspaces.source.path)
      script: |
        kustomize build $(params.overlay-path) | kubeconform -strict
    - name: apply
      image: bitnami/kubectl:1.31
      workingDir: $(workspaces.source.path)
      script: |
        kustomize build $(params.overlay-path) | kubectl apply -f -
```

**Drone / Woodpecker** (`.drone.yml` / `.woodpecker.yml`):

```yaml
kind: pipeline
name: deploy-prod
steps:
  - name: update-tag
    image: registry.internal/ci/kustomize:5.4.3
    commands:
      - cd overlays/production
      - kustomize edit set image myapp=registry.internal/finance/billing-api:${DRONE_TAG}
  - name: validate
    image: registry.internal/ci/kustomize:5.4.3
    commands:
      - kustomize build overlays/production | kubeconform -strict
  - name: deploy
    image: bitnami/kubectl:1.31
    environment:
      KUBECONFIG:
        from_secret: kubeconfig
    commands:
      - kustomize build overlays/production | kubectl apply -f -
when:
  event: tag
```

### 3.6. Управление секретами

Для CD критически важно не хранить секреты в открытом виде.

**SOPS + Kustomize (через ksops plugin):**

`.sops.yaml`:

```yaml
creation_rules:
  - path_regex: overlays/.*/secrets\.yaml$
    key_groups:
      - age:
          - age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8
```

`overlays/production/secrets.yaml` (зашифрованный):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: app-secrets
stringData:
  db-password: ENC[AES256_GCM,data:trhS...,tag:...,type:str]
sops:
  age: |
    enc: ...
  lastmodified: "2026-08-12T10:00:00Z"
  mac: ENC[AES256_GCM,data:...]
  enc: |
    enc: ...
```

В CI устанавливается `ksops` как Kustomize plugin, и build автоматически расшифровывает:

```bash
# Установка ksops в CI-образ
KSOPS_VERSION=4.3.0
curl -sL "https://github.com/viaduct-ai/kustomize-sops/releases/download/v${KSOPS_VERSION}/ksops_${KSOPS_VERSION}_linux_amd64" -o ksops
chmod +x ksops && mv ksops /usr/local/bin/

# Плагин должен лежать в ${XDG_CONFIG_HOME:-$HOME/.config}/kustomize/plugin/viaduct.ai/v1/ksops/ksops
# Затем build работает прозрачно
kustomize build overlays/production
```

**Sealed Secrets** (контроллер в кластере):

```bash
# 1. Установка контроллера (helm/kustomize)
kubectl apply -k github.com/bitnami-labs/sealed-secrets/kustomize

# 2. Шифрование секрета
kubeseal --controller-name=sealed-secrets --controller-namespace=kube-system \
  -f secret.yaml -w sealed-secret.yaml

# 3. Sealed-манифест хранится в Git
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: app-secrets
  namespace: production
spec:
  encryptedData:
    db-password: AgBy3i4OJSWK+PiTySYZZA9rO43cGDEQAx...
  template:
    metadata:
      name: app-secrets
      namespace: production
```

Kustomize в CD-пайплайне ничего не расшифровывает — просто применяет `SealedSecret`, контроллер в кластере создает обычный `Secret`.

**External Secrets Operator (ESO)** — рекомендуется для on-prem инфраструктур с уже развернутым Vault/HashiCorp:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: app-secrets
  namespace: production
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: vault-backend
  target:
    name: app-secrets
  data:
    - secretKey: db-password
      remoteRef:
        key: secret/data/billing/prod
        property: db_password
```

В `kustomization.yaml` ESO-манифест кладется как resource, и Kustomize его только применяет. Реальные значения подтягиваются контроллером ESO уже после apply.

### 3.7. Стратегия откатов и версионирование

Для обеспечения надежности рекомендуется:

1.  **Git-тегирование:** пометка коммитов в репозитории конфигураций тегами версий (например, `v1.0.1`).
2.  **Откат в Git:** выполнение `git revert` в репозитории конфигураций. GitOps-инструмент мгновенно применит предыдущее стабильное состояние.
3.  **Снапшоты релизов:** хранение сгенерированных манифестов в архиве артефактов CI для возможности быстрого `kubectl apply` в случае недоступности Git.

**Конкретные команды отката:**

```bash
# === Push-модель: kubectl rollout undo ===
kubectl rollout undo deployment/billing-api -n production
kubectl rollout undo deployment/billing-api -n production --to-revision=3

# === ArgoCD: явный откат ===
argocd app history billing-api-production
# ID  REVISION
# 12  abc1234    ← bad
# 11  def5678    ← good
argocd app rollback billing-api-production 11

# === Flux: suspend + ручной откат через git ===
flux suspend kustomization billing-api-production
# ... ручной git revert ...
flux resume kustomization billing-api-production

# === Универсальный аварийный откат из snapshot (если Git недоступен) ===
kubectl apply -f snapshots/12345/manifest.yaml
```

**Политика retention снапшотов:** хранить последние 30 релизов для production, 10 для staging. Хранилище артефактов (MinIO, Nexus, GitLab Artifacts) должно иметь политику TTL.

### 3.8. Validation Pipeline (kubeconform + OPA/Kyverno)

Многоуровневая валидация перед apply:

```bash
# 1. Схема Kubernetes API
kustomize build overlays/production | kubeconform -strict -summary -verbose

# 2. Политики безопасности (Conftest + OPA Rego)
kustomize build overlays/production | conftest test --policy policies/ -

# 3. Лучшие практики (polaris)
polaris audit --kustomize-dir overlays/production --set-exit-code-on-error

# 4. Dry-run на стороне сервера
kustomize build overlays/production | kubectl apply --dry-run=server -f -

# 5. Проверка подписи образов (cosign)
kustomize build overlays/production | python3 -c "
import sys, yaml
for doc in yaml.safe_load_all(sys.stdin):
    if doc and doc.get('kind') == 'Deployment':
        for c in doc['spec']['template']['spec']['containers']:
            print(c['image'])
" | xargs -I{} cosign verify {} --certificate-identity-regexp '.*@my-org.*'
```

### 3.9. Canary / Blue-Green через Kustomize

Канареечное развертывание без service-mesh реализуется через два overlay'а и `Selector` в Service:

`base/kustomization.yaml`:

```yaml
resources:
  - deployment.yaml
  - service.yaml
```

`overlays/canary/kustomization.yaml`:

```yaml
resources:
  - ../../base
patchesStrategicMerge:
  - deployment-canary.yaml
```

`overlays/canary/deployment-canary.yaml` — отдельный Deployment с `name: app-canary` и `replicas: 1` (5% от production). Service направляет 95% трафика на основной, 5% — на канарейку (через аннотации ingress-контроллера или Istio/VirtualService).

В CD-пайплайне canary деплоится первым, валидируется метриками (latency, error rate), затем промоутится через изменение replicas и удаление canary-Deployment'а.

### 3.10. Image Promotion Pipeline (CI → GitOps)

Связка registry → CI → GitOps-репозиторий:

```bash
#!/bin/bash
# scripts/promote.sh
# Использование: ./promote.sh v1.7.3
set -euo pipefail

IMAGE_TAG="$1"
GITOPS_REPO="git@github.com:my-org/infra-gitops.git"
WORKDIR=$(mktemp -d)

git clone "$GITOPS_REPO" "$WORKDIR"
cd "$WORKDIR"

for env in staging production; do
  cd "overlays/$env"
  kustomize edit set image myapp=registry.internal/finance/billing-api:"$IMAGE_TAG"
  kustomize edit set tag myapp:"$IMAGE_TAG"
  cd -
done

git add overlays/
git commit -m "Promote billing-api to $IMAGE_TAG"
git push origin main
```

В GitOps-репозитории (например, на Gitea) настраивается webhook в ArgoCD/Flux — apply произойдет автоматически.

## 4. Диагностика и решение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `kustomize build` падает с `accumulating resources` | Циклическая зависимость между base и overlay | Проверить `bases:` и `resources:` на петли; использовать `kustomize cfg lint` |
| `kubectl apply -k` ругается на `no matches for kind` | CRD не установлены в кластере | Применить CRD до apply (отдельный шаг CI или `dependencies` в ArgoCD Application) |
| ArgoCD показывает `OutOfSync` после ручного `kubectl edit` | Self-heal отключен или sync-окно не активно | Включить `selfHeal: true` или выполнить `argocd app sync --force` |
| `ImagePullBackOff` после `kustomize edit set image` | Registry недоступен или неверный секрет | Проверить `imagePullSecrets`, сетевую связность до registry, `kubectl describe pod` |
| Хеш ConfigMap не изменился при изменении файла | `disableNameSuffixHash: true` или `behavior: merge` | Проверить `kustomization.yaml`; для rolling-restart должен быть включен хеш-суффикс |
| `diff` показывает изменения, которых нет в Git | Server-side apply оставил `managedFields` от предыдущего apply | Использовать `kubectl apply --server-side --force-conflicts` или почистить аннотации |
| ArgoCD sync падает с `ComparisonError` | Изменения в Git невалидны (синтаксис YAML) | Проверить `argocd app manifests` локально; `kustomize build` на dev-машине |
| Flux Kustomization в состоянии `Ready=False` после изменения | Health checks не прошли (поды не Ready) | `flux get kustomization`, `flux logs`; увеличить `timeout` или исправить readiness probe |
| Kustomize edit не сохраняет изменение | Файл `kustomization.yaml` read-only или нет прав | Проверить `ls -la overlays/production/`; CI должен иметь RW |
| `kubeconform` сообщает о неизвестных полях | Используется CRD без схемы | Создать `schemas/` и передать `-schema-location` |
| `argocd app sync` долго (timeout) | Большой namespace с тысячами объектов | Увеличить `syncOptions.timeout`, использовать `ServerSideApply=true`, разбить на несколько Application |
| `kubectl diff` ничего не показывает, но ArgoCD считает `OutOfSync` | ArgoCD использует SSA + ignoreDifferences | Согласовать ignoreDifferences между CI (`--server-side`) и ArgoCD |

### Диагностические команды

```bash
# Какой манифест ArgoCD видит
argocd app manifests billing-api-production

# История ревизий
argocd app history billing-api-production
flux get kustomization billing-api-production

# Дрифт между Git и кластером
argocd app diff billing-api-production
flux diff kustomization billing-api-production

# События Kustomization в кластере
kubectl describe kustomization billing-api-production -n flux-system

# Логи kustomize-controller
kubectl logs -n flux-system -l app=kustomize-controller --tail=200
```

### 3.11. Multi-cluster деплой через Kustomize

При управлении несколькими кластерами (регионы, окружения) Kustomize используется для создания кластер-специфичных конфигураций из общей base.

**Структура репозитория:**
```text
infra-repo/
├── base/                          # Общая base
│   └── web-server/
│       ├── deployment.yaml
│       ├── service.yaml
│       └── kustomization.yaml
├── clusters/
│   ├── prod-eu/
│   │   └── web-server/
│   │       └── kustomization.yaml # EU-specific overlay
│   ├── prod-us/
│   │   └── web-server/
│   │       └── kustomization.yaml # US-specific overlay
│   └── staging/
│       └── web-server/
│           └── kustomization.yaml
└── platform/                      # Аддоны (monitoring, ingress)
```

**Overlay для конкретного кластера:**
```yaml
# clusters/prod-eu/web-server/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../../base/web-server
  - ../cluster-vars.yaml

namespace: web-server
namePrefix: eu-

patches:
  - target:
      kind: Deployment
      name: web-server
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 5
      - op: add
        path: /spec/template/spec/containers/0/env/-
        value:
          name: REGION
          value: eu-west-1
```

**ArgoCD ApplicationSet для автоматического деплоя во все кластеры:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: web-server
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - cluster: prod-eu
            url: https://kubernetes-eu.internal
          - cluster: prod-us
            url: https://kubernetes-us.internal
  template:
    metadata:
      name: 'web-server-{{cluster}}'
    spec:
      source:
        repoURL: https://github.com/org/infra.git
        path: 'clusters/{{cluster}}/web-server'
      destination:
        server: '{{url}}'
        namespace: web-server
```

Подробнее: [Multi-cluster паттерны](./kustomize_multi_cluster.md).

## 5. Безопасность

- **Минимум привилегий в CI:** ServiceAccount для apply должен иметь только `get/list/watch/create/update/patch/delete` на конкретные ресурсы в конкретном namespace, **не** `cluster-admin`. Используйте RBAC-role + RoleBinding на namespace.
- **Отдельные kubeconfig'ы для CI:** `kubeconfig-prod`, `kubeconfig-staging` — хранятся в CI secret store (GitHub Encrypted Secrets, GitLab Protected Variables, Jenkins Credentials) с audit-trail доступа.
- **OIDC вместо static-токенов:** используйте `kubelogin` или другой exec-плагин; CI-раннер получает токен на короткое время через workload identity (Gitea Actions OIDC, GitLab OIDC, Jenkins + Vault Agent).
- **Подпись манифестов (cosign):** для production-кластеров — подписывайте собранные Kustomize-манифесты перед коммитом в GitOps-репозиторий; `cosign verify-blob` в admission controller (Kyverno/Conftest) предотвращает apply неподписанных изменений.
- **Запрет на force-apply:** `kubectl replace --force` и `kubectl delete --all` в production — только через ручное подтверждение и аудит-лог.
- **Изоляция канареечных rollout'ов:** канареечные overlay'ы деплоятся в **отдельный namespace** с отдельным ServiceAccount, чтобы при ошибке не задеть основной namespace.
- **Audit-лог CD-операций:** все `kubectl apply -k`, `argocd app sync`, `flux reconcile` пишут в audit-лог кластера; настройте Fluentbit/Vector для отправки в SIEM (Loki, Splunk on-prem).

## 6. Производительность и масштабирование

| Число ресурсов в namespace | Рекомендация |
| :--- | :--- |
| < 100 | Один Application/Kustomization, без оптимизаций |
| 100–500 | Разделить по доменам (frontend, backend, data), включить `ServerSideApply=true` |
| 500–2000 | Несколько ArgoCD ApplicationSet или HelmRelease'ов + Kustomize; избегать `kubectl diff` на весь namespace |
| 2000+ | Переходить на Helm + Kustomize overlay для base, либо на ApplicationSet с auto-discovery |

**Тюнинг ArgoCD:**

- `--status-processors` — увеличить до 50 при большом числе Application'ов.
- `repoServer.replicas: 3` — для крупных манифестов.
- SSA и server-side diff настраиваются на уровне приложения (sync option `ServerSideApply=true`, аннотация `argocd.argoproj.io/compare-options: ServerSideDiff=true`); глобальных ключей exclusions для diff в `argocd-cm` нет — для исключения полей из diff используйте `ignoreDifferences` (см. [Ignore Differences](../../../GitOps/ArgoCD/synchronization/ignore_differences.md)).

**Тюнинг Flux:**

- `--concurrent=10` — параллельные reconcile.
- `--events-per-second=10` — если много Kustomization'ов.
- `spec.interval` — увеличить с 10m до 1h для non-critical, чтобы снизить нагрузку на kube-apiserver.

## 7. Чеклист внедрения CD с Kustomize

1. **Определить модель:** push или pull. Для зрелых команд — pull (ArgoCD/Flux).
2. **Разделить репозитории:** `app-repo` (код) + `infra-repo` (Kustomize), или mono-repo.
3. **Создать base/overlay структуру:** минимум `base/` + `overlays/{dev,staging,production}/`.
4. **Включить configMapGenerator/secretGenerator:** для автоматического rolling-restart.
5. **Настроить CI-валидацию:** kubeconform + dry-run + diff на каждый PR.
6. **Настроить image-promotion:** `kustomize edit set image` в CI, push в GitOps-репо.
7. **Развернуть GitOps-контроллер:** ArgoCD или Flux, настроить webhook'и.
8. **Настроить self-heal:** `selfHeal: true` в ArgoCD / `prune: true` в Flux.
9. **Внедрить health-checks:** для всех Deployment'ов, ожидание `Ready`.
10. **Настроить secrets:** SOPS/Sealed Secrets/ESO в зависимости от on-prem-инфраструктуры.
11. **Описать стратегию откатов:** документировать команды для CI и GitOps-контроллера.
12. **Внедрить audit-logging:** admission controller + audit-policy + SIEM.
13. **Обучить команду:** `argocd app`, `flux get`, ручной откат, `kustomize build`.

## 8. Дополнительная информация

### См. также

- **[Обзор Kustomize: основные концепции](./kustomize_overview.md)** — базовые определения, установка, интеграция с `kubectl`.
- **[Структура и синтаксис kustomization.yaml](./kustomize_structure_and_syntax.md)** — детальный разбор полей, transformers, generators.
- **[Продвинутые возможности](./kustomize_advanced_features.md)** — components, replacements, hash-суффиксы, exec-плагины.
- **[Debugging Kustomize](./kustomize_debugging.md)** — troubleshooting ошибок в CI/CD.
- **[Multi-cluster паттерны](./kustomize_multi_cluster.md)** — multi-cluster деплой через overlays.
- **[Git-автоматизация](./kustomize_git_automation.md)** — Renovate, image promotion, pre-commit.
- **[Тестирование и валидация](./kustomize_testing_validation.md)** — conftest, snapshot, lint.
- **[Валидация манифестов (kubeconform)](../kubeconform_overview.md)** — автоматическая проверка схем Kubernetes API.
- **[ArgoCD: синхронизация и self-heal](../../../GitOps/ArgoCD/synchronization.md)** — детали GitOps-модели ArgoCD.
- **[Flux v2: Kustomize Controller](../../../GitOps/flux.md)** — описание `Kustomization` API.

### Внешние ресурсы

- [Official Kustomize Documentation](https://kustomize.io/)
- [ArgoCD: Kustomize Integration](https://argo-cd.readthedocs.io/en/stable/user-guide/kustomize/)
- [Flux v2: Kustomization API](https://fluxcd.io/flux/components/kustomize/kustomization/)
- [SOPS + Kustomize (ksops)](https://github.com/viaduct-ai/kustomize-sops)
- [External Secrets Operator](https://external-secrets.io/)
