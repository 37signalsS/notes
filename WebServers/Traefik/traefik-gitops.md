# Traefik в GitOps и CI/CD: валидация, пайплайн, паттерны Argo CD

**Актуально для:** Traefik v3.3+ (v3.x), Helm Chart traefik v34.x+, Argo CD v2.12+

---

## Определения

- **GitOps** — парадигма декларативного управления инфраструктурой и приложениями, при которой Git-репозиторий является единственным источником правды (SSoT), а контроллер в кластере (Argo CD) непрерывно синхронизирует фактическое состояние с целевым (Reconciliation Loop).
- **Argo CD Application Controller** — ключевой сервис Argo CD, непрерывно опрашивающий Kubernetes API и сравнивающий состояние живых ресурсов кластера с манифестами, полученными от `argocd-repo-server`.
- **Static Configuration (Control Plane)** — неизменяемые во время выполнения параметры Traefik (точки входа `entryPoints`, провайдеры конфигурации, системные порты, экспорт метрик, включение Dashboard/API), требующие перезапуска процесса или пересоздания подов Deployment/DaemonSet.
- **Dynamic Configuration (Data Plane)** — динамические правила маршрутизации трафика (роутеры `routers`, сервисы `services`, промежуточные обработчики `middlewares`, параметры TLS `tls`), загружаемые Traefik из Kubernetes CRD (`traefik.io/v1alpha1`) без перезапуска подов и без разрыва соединений.
- **Server-Side Apply (SSA)** — механизм применения манифестов через Kubernetes API с отслеживанием владения отдельными полями (`fieldManager: argocd-application-controller`). Устраняет сбой переполнения 262-килобайтного лимита аннотации `kubectl.kubernetes.io/last-applied-configuration`, возникающий при деплое объемных спецификаций CRD Traefik.
- **Sync Waves & Hooks** — механизм Argo CD (`argocd.argoproj.io/sync-wave`, `argocd.argoproj.io/hook`), позволяющий задавать детерминированный порядок развертывания ресурсов (например, сначала CRD и Namespace, затем контроллер Traefik, затем общие Middleware, и только потом пользовательские IngressRoute).
- **Ignore Differences** — декларативная директива в манифесте `Application`, предписывающая Argo CD игнорировать расхождения между Git и кластером для конкретных мутируемых полей (например, веса сервисов в `TraefikService`, динамически изменяемые оператором прогрессивной доставки Flagger).
- **App-of-Apps** — паттерн архитектуры Argo CD, при котором корневое приложение (`root-application`) развертывает и координирует набор дочерних приложений (ингресс-контроллер, системные плагины, пользовательские правила маршрутизации).
- **Inotify Race Condition** — состояние гонки при обновлении файлов динамической конфигурации на диске в non-Kubernetes средах: если внешний процесс (`git pull`) перезаписывает YAML-файл построчно, файловый провайдер Traefik на базе `fsnotify` может считать недописанный файл, что приводит к синтаксическим ошибкам или кратковременному исчезновению маршрутов.

---

## Архитектура и принципы работы

### 1. Архитектура интеграции Traefik и Argo CD

В модели Argo CD GitOps управление Traefik строго разделяется на Control Plane (развертывание контроллера) и Data Plane (правила маршрутизации сервисов):

```
                        GitOps Repository (Single Source of Truth)
                       ┌──────────────────────────────────────────────┐
                       │  infra-gitops/                               │
                       │  ├── root-application.yaml (App-of-Apps)     │
                       │  ├── platform/traefik/ (Helm / Values)       │
                       │  └── apps/routing/ (IngressRoutes/Middlewares)│
                       └──────────────────────┬───────────────────────┘
                                              │
                                              ▼
                                 ┌────────────────────────┐
                                 │ Argo CD (Repo Server)  │
                                 │ - renders Helm/Kust    │
                                 └────────────┬───────────┘
                                              │
                                              ▼
                             ┌─────────────────────────────────┐
                             │ Argo CD Application Controller   │
                             │ (Server-Side Apply, Sync Waves) │
                             └───────┬─────────────────┬───────┘
                                     │                 │
              [Wave 0-1: Control Plane]               [Wave 2-3: Data Plane]
                                     ▼                                 ▼
                     ┌───────────────────────────┐     ┌───────────────────────────┐
                     │ Traefik Ingress Controller│     │ IngressRoute / Middleware │
                     │ (Deployment, Service, CRD)│     │ (Namespaces: prod, stage) │
                     └─────────────┬─────────────┘     └─────────────┬─────────────┘
                                   │                                 │
                                   │ watches traefik.io/v1alpha1     │
                                   └─────────────────────────────────┘
```

1. **Control Plane (Платформенный контур):** управляется центральной командой эксплуатации. Включает Helm-чарт `traefik/traefik`, Service типа `LoadBalancer` (MetalLB / NodePort), RBAC (`ClusterRole`, `ServiceAccount`), `PodDisruptionBudget` и регистрацию CRD.
2. **Data Plane (Контур маршрутизации):** манифесты `IngressRoute`, `Middleware`, `TLSOption`, `ServersTransport` и `TraefikService`. Децентрализованы по продуктовым каталогам команд разработки, синхронизируются через независимые Argo CD `Application` с ограничением прав через `AppProject`.

### 2. Структура монорепозитория для Argo CD

```
gitops-repository/
├── bootstrap/
│   └── root-application.yaml          # Корневое приложение App-of-Apps
├── platform/
│   └── traefik/
│       ├── base/
│       │   ├── application.yaml       # Argo CD Application для чарта Traefik
│       │   └── values.yaml            # Базовые значения Helm
│       └── environments/
│           ├── staging/
│           │   └── values-staging.yaml
│           └── production/
│               ├── values-production.yaml
│               └── metallb-ip-pool.yaml
├── apps-routing/
│   ├── base/
│   │   ├── middlewares/
│   │   │   ├── security-headers.yaml
│   │   │   ├── rate-limit.yaml
│   │   │   └── forward-auth.yaml
│   │   └── ingressroutes/
│   │       ├── api-gateway.yaml
│   │       └── web-portal.yaml
│   └── overlays/
│       ├── staging/
│       │   └── kustomization.yaml
│       └── production/
│           └── kustomization.yaml
└── .github/
    └── workflows/
        └── ci-validation.yaml         # CI-валидация до вливания в main
```

### 3. Механика валидации конфигурации в CI/CD перед Argo CD

> [!IMPORTANT]
> В бинарном дистрибутиве Traefik v3 **нет** встроенной подкоманды `traefik config validate`. Traefik поддерживает только подкоманды `version` и `healthcheck`. Поэтому валидация в CI/CD перед фиксацией изменений в ветку Argo CD строится на независимых инструментах синтаксического и схемного анализа.

Пайплайн валидации гарантирует, что в Git попадают только проверенные манифесты:
- **`yamllint`:** проверка форматирования и отсутствия синтаксических ошибок YAML.
- **`check-jsonschema`:** проверка динамических конфигураций Traefik по официальной JSON-схеме Traefik v3.
- **`kubeconform`:** валидация кастомных ресурсов `IngressRoute`, `Middleware`, `TLSOption` по OpenAPI v3 схемам из каталога `datreeio/CRDs-catalog`.
- **`helm lint` и `helm template --dry-run=server`:** проверка рендеринга шаблонов чарта с подстановкой боевых файлов `values.yaml`.

### 4. Разрешение проблемы размера CRD и Server-Side Apply в Argo CD

Спецификации Custom Resource Definition Traefik (`traefik.io/v1alpha1`) содержат детальные схемы валидации для десятков параметров маршрутизации. При стандартном Client-Side Apply (`kubectl apply`) Argo CD сохраняет полное состояние в аннотации `kubectl.kubernetes.io/last-applied-configuration`. 

Так как максимальный размер метаданных одного объекта в etcd жестко ограничен **262 144 байтами (256 КБ)**, попытка накатить CRD Traefik без специальных настроек завершается ошибкой:

```
metadata.annotations: Too long: must have at most 262144 bytes
```

**Решение в Argo CD:**
В секции `syncOptions` манифеста `Application` задается опция:

```yaml
syncPolicy:
  syncOptions:
    - ServerSideApply=true
```

При включении SSA Argo CD передает манифест напрямую в API-сервер Kubernetes с указанием менеджера полей `argocd-application-controller`. Kubernetes применяет манифест через механизм `managedFields` без формирования раздутой клиентской аннотации.

### 5. Детерминированный порядок применения через Argo CD Sync Waves

Если IngressRoute или Middleware попытаться применить до того, как API-сервер Kubernetes зарегистрировал CRD Traefik, синхронизация упадет с ошибкой `the server could not find the requested resource`. Для исключения гонок применяются аннотации фаз синхронизации (`Sync Waves`):

| Sync Wave | Назначение ресурсов | Примеры объектов |
| :--- | :--- | :--- |
| **Wave 0** | Пространство имен и регистрация CRD | `Namespace`, `CustomResourceDefinition` |
| **Wave 1** | RBAC, ServiceAccount, Сетевые политики | `ClusterRole`, `ClusterRoleBinding`, `NetworkPolicy` |
| **Wave 2** | Контроллер Traefik и сервисы балансировки | `Deployment`, `DaemonSet`, `Service` (LoadBalancer) |
| **Wave 3** | Базовые переиспользуемые Middleware | `Middleware` (security headers, error pages) |
| **Wave 4** | Правила маршрутизации приложений | `IngressRoute`, `TraefikService`, `TLSOption` |

### 6. GitOps для Bare-Metal / Docker без Kubernetes (Паттерн Atomic Symlink Swap)

В гибридных инфраструктурах, где часть инстансов Traefik работает на физических серверах (Systemd) или в Docker Compose, прямая синхронизация `git pull` в каталог `providers.file.directory` приводит к сбоям: библиотека `fsnotify` перехватывает промежуточную запись файлов, вызывая ошибки парсинга и временное падение маршрутов (HTTP 404/502).

Синхронизатор выкачивает коммит в отдельный каталог релизов (`/etc/traefik/releases/<commit-sha>`), валидирует YAML, после чего атомарно переключает символическую ссылку `/etc/traefik/dynamic` через `ln -sfn ... && mv -T ...`.

---

## Практические сценарии

### Сценарий 1: CI-пайплайн валидации манифестов для Argo CD (GitHub Actions)

Пайплайн проверяет Helm-чарт Traefik, кастомные values и объекты IngressRoute в Pull Request до слияния в ветку, которую отслеживает Argo CD.

```yaml
# .github/workflows/traefik-ci-validation.yml
name: Traefik Manifests Validation for Argo CD

on:
  pull_request:
    paths:
      - 'platform/traefik/**'
      - 'apps-routing/**'
      - '.github/workflows/traefik-ci-validation.yml'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Setup Tools (Python & Kubeconform)
        run: |
          pip install yamllint check-jsonschema
          curl -sL https://github.com/yannh/kubeconform/releases/download/v0.6.7/kubeconform-linux-amd64.tar.gz | tar -xz -C /usr/local/bin kubeconform
          chmod +x /usr/local/bin/kubeconform

      - name: 1. YAML Syntax Check
        run: |
          yamllint -d "{extends: default, rules: {line-length: {max: 160}, document-start: disable}}" platform/ apps-routing/

      - name: 2. Validate Traefik CRDs with OpenAPI Schemas
        run: |
          # Проверка IngressRoute, Middleware, TLSOption через официальный каталог CRD Datree
          kubeconform \
            -strict \
            -ignore-missing-schemas \
            -kubernetes-version 1.32.0 \
            -schema-location default \
            -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
            -summary \
            apps-routing/

      - name: 3. Helm Template Validation
        run: |
          helm repo add traefik https://traefik.github.io/charts
          helm repo update
          
          # Рендеринг Helm-чарта с боевыми values для проверки шаблонизатора
          helm template traefik traefik/traefik \
            --version 34.4.1 \
            -f platform/traefik/base/values.yaml \
            -f platform/traefik/environments/production/values-production.yaml \
            > /tmp/rendered-traefik.yaml
          
          # Валидация сгенерированного манифеста
          kubeconform -strict -summary /tmp/rendered-traefik.yaml
```

### Сценарий 2: Развертывание контроллера Traefik через Argo CD Application

Манифест `Application` развертывает Traefik из официального Helm-чарта с включенным Server-Side Apply, привязкой к пулу адресов MetalLB и экспортом метрик Prometheus.

```yaml
# platform/traefik/base/application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: traefik-controller
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://traefik.github.io/charts
    chart: traefik
    targetRevision: 34.4.1
    helm:
      releaseName: traefik
      valuesObject:
        deployment:
          replicas: 3
          podDisruptionBudget:
            enabled: true
            minAvailable: 2
        service:
          type: LoadBalancer
          annotations:
            metallb.universe.tf/address-pool: edge-pool
        ports:
          web:
            port: 8000
            exposedPort: 80
            redirectTo:
              port: websecure
          websecure:
            port: 8443
            exposedPort: 443
            tls:
              enabled: true
          metrics:
            port: 9100
            expose:
              default: false
        providers:
          kubernetesCRD:
            enabled: true
            allowCrossNamespace: false
            allowExternalNameServices: false
          kubernetesIngress:
            enabled: false
        metrics:
          prometheus:
            entryPoint: metrics
            addEntryPointsLabels: true
            addRoutersLabels: true
            addServicesLabels: true
            serviceMonitor:
              enabled: true
              namespace: traefik
  destination:
    server: https://kubernetes.default.svc
    namespace: traefik
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
      - ApplyOutOfSyncOnly=true
```

### Сценарий 3: Паттерн App-of-Apps для управления Traefik и маршрутизацией

Корневое приложение Argo CD координирует установку контроллера и доставку правил маршрутизации в кластер:

```yaml
# bootstrap/root-application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root-edge-infrastructure
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: git@git.corp.internal:infra/gitops.git
    targetRevision: main
    path: bootstrap/apps
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

Дочернее приложение маршрутизации приложений:

```yaml
# bootstrap/apps/apps-routing.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: edge-routing-production
  namespace: argocd
spec:
  project: default
  source:
    repoURL: git@git.corp.internal:infra/gitops.git
    targetRevision: main
    path: apps-routing/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - ServerSideApply=true
```

### Сценарий 4: Упорядочивание развертывания через Argo CD Sync Waves

Для гарантии того, что Middleware применится строго до IngressRoute, а CRD — до контроллера, манифесты размечаются волнами синхронизации:

```yaml
# apps-routing/base/middlewares/security-headers.yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: security-headers
  namespace: production
  annotations:
    argocd.argoproj.io/sync-wave: "2"
spec:
  headers:
    browserXssFilter: true
    contentTypeNosniff: true
    forceSTSHeader: true
    stsIncludeSubdomains: true
    stsPreload: true
    stsSeconds: 31536000
    frameDeny: true
---
# apps-routing/base/ingressroutes/portal-ingress.yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: internal-portal
  namespace: production
  annotations:
    argocd.argoproj.io/sync-wave: "3"
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`portal.internal.corp`) && PathPrefix(`/`)
      kind: Rule
      services:
        - name: portal-service
          port: 8080
      middlewares:
        - name: security-headers
  tls:
    secretName: portal-tls-secret
```

### Сценарий 5: GitOps-доставка пользовательских IngressRoute через Kustomize в Argo CD

Структура Kustomize-оверлеев позволяет переопределять хосты и секреты под конкретное окружение без дублирования правил:

```yaml
# apps-routing/overlays/production/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: production

resources:
  - ../../base/middlewares/security-headers.yaml
  - ../../base/ingressroutes/portal-ingress.yaml

patches:
  - target:
      group: traefik.io
      version: v1alpha1
      kind: IngressRoute
      name: internal-portal
    patch: |-
      - op: replace
        path: /spec/routes/0/match
        value: "Host(`portal.prod.corp.internal`) && PathPrefix(`/`)"

commonLabels:
  app.kubernetes.io/managed-by: argocd
  environment: production
```

### Сценарий 6: Управление секретами в Argo CD: External Secrets Operator (ESO)

Для исключения открытых паролей `BasicAuth` и ключей TLS из Git манифест связывается с локальным Vault через ESO:

```yaml
# apps-routing/base/secrets/traefik-basic-auth-eso.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: edge-auth-secret
  namespace: production
  annotations:
    argocd.argoproj.io/sync-wave: "1"
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onprem-vault
  target:
    name: edge-basic-auth
    creationPolicy: Owner
  data:
    - secretKey: users
      remoteRef:
        key: kv/data/production/ingress/auth
        property: htpasswd_users
---
# apps-routing/base/middlewares/basic-auth.yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: edge-auth
  namespace: production
  annotations:
    argocd.argoproj.io/sync-wave: "2"
spec:
  basicAuth:
    secret: edge-basic-auth
```

### Сценарий 7: Интеграция Argo CD с Flagger (Исключение дрейфа весов)

Операторы прогрессивной доставки (Flagger) динамически мутируют веса сервисов в объектах `TraefikService` в процессе канареечного анализа. Без настройки исключений Argo CD считает это несанкционированным дрейфом и возвращает исходные веса из Git (`selfHeal`), срывая процесс релиза.

Настройка `ignoreDifferences` в манифесте Argo CD `Application`:

```yaml
# bootstrap/apps/canary-routing.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: production-canary-routing
  namespace: argocd
spec:
  project: default
  source:
    repoURL: git@git.corp.internal:infra/gitops.git
    targetRevision: main
    path: apps-routing/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
  ignoreDifferences:
    # Игнорировать динамические изменения весов контроллером Flagger
    - group: traefik.io
      kind: TraefikService
      jsonPointers:
        - /spec/weighted/services
```

### Сценарий 8: GitOps на Bare-Metal / Docker через `git-sync` и атомарный symlink swap

Для stand-alone серверов Traefik вне Kubernetes развертывается скрипт синхронизации с защитой от гонок `fsnotify`.

Bash-скрипт обновления:

```bash
#!/usr/bin/env bash
# /usr/local/bin/traefik-gitops-sync.sh
set -euo pipefail

REPO_URL="git@git.corp.internal:infra/traefik-configs.git"
CLONE_DIR="/opt/traefik-gitops/repo"
RELEASES_DIR="/etc/traefik/releases"
LIVE_SYMLINK="/etc/traefik/dynamic"
SCHEMA_FILE="/usr/local/share/traefik/traefik-dynamic-schema.json"

mkdir -p "${CLONE_DIR}" "${RELEASES_DIR}"

# 1. Загрузка коммита из Git
if [ ! -d "${CLONE_DIR}/.git" ]; then
  git clone --depth 1 "${REPO_URL}" "${CLONE_DIR}"
else
  cd "${CLONE_DIR}"
  git fetch origin main
  git reset --hard origin/main
fi

COMMIT_SHA=$(git -C "${CLONE_DIR}" rev-parse --short HEAD)
TARGET_DIR="${RELEASES_DIR}/${COMMIT_SHA}"

# 2. Если коммит уже активен — выходим
if [ -d "${TARGET_DIR}" ] && [ "$(readlink -f "${LIVE_SYMLINK}" 2>/dev/null)" = "${TARGET_DIR}" ]; then
  exit 0
fi

# 3. Валидация YAML-файлов перед применением
find "${CLONE_DIR}/dynamic" -name "*.yaml" -o -name "*.yml" | while read -r file; do
  yamllint -d "{extends: default, rules: {line-length: disable}}" "$file"
  check-jsonschema --schemafile "${SCHEMA_FILE}" "$file"
done

# 4. Копирование файлов в каталог релиза
rm -rf "${TARGET_DIR}"
mkdir -p "${TARGET_DIR}"
cp -a "${CLONE_DIR}/dynamic/"* "${TARGET_DIR}/"

# 5. Атомарное переключение символической ссылки
ln -sfn "${TARGET_DIR}" "${LIVE_SYMLINK}.tmp"
mv -T "${LIVE_SYMLINK}.tmp" "${LIVE_SYMLINK}"

echo "Activated release ${COMMIT_SHA} -> ${LIVE_SYMLINK}"

# 6. Очистка старых версий (оставляем 3 последних)
cd "${RELEASES_DIR}"
ls -dt */ | tail -n +4 | xargs -r rm -rf
```

Systemd сервис и таймер:

```ini
# /etc/systemd/system/traefik-gitops.service
[Unit]
Description=Traefik Standalone GitOps Synchronizer
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=traefik
Group=traefik
ExecStart=/usr/local/bin/traefik-gitops-sync.sh
StandardOutput=journal
StandardError=journal
```

```ini
# /etc/systemd/system/traefik-gitops.timer
[Unit]
Description=Run Traefik Standalone GitOps Synchronizer every 2 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=2min
Persistent=true

[Install]
WantedBy=timers.target
```

---

## Операции и команды

### 1. Проверка синтаксиса и схемы манифестов в терминале

```bash
# Валидация структуры YAML
yamllint -d "{extends: default, rules: {line-length: {max: 160}}}" apps-routing/
# → [OK] No issues found

# Проверка кастомных манифестов Traefik CRD через kubeconform
kubeconform -strict -summary \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
  apps-routing/
# → Summary: 12 resources found in 6 files - Valid: 12, Invalid: 0, Errors: 0, Skipped: 0
```

### 2. Тестирование рендеринга Helm-чарта

```bash
# Тестовый рендеринг чарта с боевыми values
helm template traefik traefik/traefik \
  --version 34.4.1 \
  --namespace traefik \
  -f platform/traefik/base/values.yaml \
  -f platform/traefik/environments/production/values-production.yaml \
  --dry-run=server
# → ---
# → # Source: traefik/templates/deployment.yaml
# → apiVersion: apps/v1
# → kind: Deployment
# → metadata:
# →   name: traefik
# → ... (манифесты успешно отрендерены)
```

### 3. Управление приложением Traefik через Argo CD CLI

```bash
# Просмотр расхождений (diff) между Git и кластером
argocd app diff traefik-controller
# → (вывод различий в полях, если обнаружен дрейф)

# Ручная синхронизация приложения с ServerSideApply
argocd app sync traefik-controller --server-side-apply
# → TIMESTAMP                  GROUP        KIND   NAMESPACE                  NAME    STATUS   HEALTH        HOOK  MESSAGE
# → 2026-10-17T15:45:00+03:00  traefik.io   CRD                                       Synced                        customresourcedefinition.apiextensions.k8s.io/ingressroutes.traefik.io configured
# → 2026-10-17T15:45:01+03:00  apps         Deployment   traefik               traefik  Synced   Healthy              deployment.apps/traefik configured

# Получение статуса синхронизации и здоровья
argocd app get traefik-controller
# → Name:               traefik-controller
# → Project:            default
# → Server:             https://kubernetes.default.svc
# → Namespace:          traefik
# → URL:                https://argocd.internal.corp/applications/traefik-controller
# → Repo:               https://traefik.github.io/charts
# → Target:             34.4.1
# → Sync Status:        Synced to 34.4.1 (a1b2c3d)
# → Health Status:      Healthy

# Просмотр истории релизов приложения
argocd app history traefik-controller
# → ID  DATE                           TARGET
# → 1   2026-10-17 14:00:00 +0300 MSK  34.3.0
# → 2   2026-10-17 15:45:00 +0300 MSK  34.4.1

# Откат приложения на предыдущую ревизию (при отключенном automated sync)
argocd app rollback traefik-controller 1
# → Application 'traefik-controller' rolled back to 1
```

### 4. Инспекция активных роутеров через Traefik API

```bash
# Проверка зарегистрированных роутеров через API Traefik
curl -s http://127.0.0.1:8080/api/http/routers | jq '.[] | {name: .name, status: .status, rule: .rule}'
# → {
# →   "name": "production-internal-portal@kubernetescrd",
# →   "status": "enabled",
# →   "rule": "Host(`portal.prod.corp.internal`) && PathPrefix(`/`)"
# → }
```

---

## Устранение неисправностей

| Неисправность / Симптом | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`metadata.annotations: Too long: must have at most 262144 bytes` в Argo CD** | Попытка сохранить CRD Traefik через Client-Side Apply с созданием аннотации `last-applied-configuration`. | Ошибка в Argo CD UI: `kubectl apply failed: Too long`. | Добавить опцию `- ServerSideApply=true` в `spec.syncPolicy.syncOptions` манифеста `Application`. |
| **Бесконечный дрейф `OutOfSync` при канареечном релизе** | Контроллер Flagger меняет веса в объекте `TraefikService`, что расходится с коммитом в Git. | `argocd app diff <app>` показывает постоянное изменение `/spec/weighted/services`. | Настроить секцию `ignoreDifferences` для `kind: TraefikService` по JSON-пути `/spec/weighted/services`. |
| **IngressRoute не находит Middleware из другого namespace** | В Traefik по умолчанию включена строгая изоляция неймспейсов (`allowCrossNamespace: false`). | В логах подов Traefik: `middleware ... not found in namespace ...`. | Задать `providers.kubernetesCRD.allowCrossNamespace: true` в values чарта, либо перенести Middleware в namespace сервиса. |
| **Argo CD падает с ошибкой `ComparisonError: repository not found`** | `argocd-repo-server` не имеет сетевого доступа к приватному Git-репозиторию или истек SSH-ключ. | Статус приложения `ComparisonError`, логи `argocd-repo-server`. | Проверить сетевую доступность Git-сервера и валидность секрета в `Settings -> Repositories` в Argo CD. |
| **Ошибка гонки при развертывании: IngressRoute создается раньше Middleware** | Отсутствует явный порядок синхронизации ресурсов внутри Argo CD Application. | Ошибка синхронизации: `middleware not found`, статус `Degraded`. | Разметить манифесты аннотациями Sync Waves: Middleware (`sync-wave: "2"`), IngressRoute (`sync-wave: "3"`). |
| **404/502 ошибки при git pull на Stand-alone Bare-Metal серверах** | Построчная запись файла в каталоге `providers.file.directory`, библиотека `fsnotify` считывает незавершенный YAML. | В логах Traefik: `level=error msg="Error occurred while parsing configuration..."`. | Использовать паттерн атомарной подмены каталогов через симлинки (`ln -sfn ... && mv -T ...`). |
| **Kubeconform сообщает `could not find schema for IngressRoute`** | В стандартной библиотеке схем Kubernetes отсутствуют кастомные определения CRD Traefik. | Вывод `kubeconform`: `could not find schema for IngressRoute.traefik.io/v1alpha1`. | Добавить ключ `-schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'`. |

---

## Рекомендации

1. **Всегда включайте Server-Side Apply для Traefik:** добавление `ServerSideApply=true` в `syncOptions` каждого `Application` с ресурсами Traefik обязательно для предотвращения сбоев etcd из-за размера схем CRD.
2. **Разделяйте Control Plane и Data Plane по проектам Argo CD (AppProject):** платформенный чарт Traefik должен развертываться в привилегированном проекте `platform` с доступом к кластерным ресурсам, а пользовательские IngressRoute — в проектах команд с ограничением по целевым неймспейсам.
3. **Используйте Sync Waves для детерминированного наката:** всегда явно отделяйте волнами установку секретов/сертификатов (Wave 1), общих Middlewares (Wave 2) и роутеров IngressRoute (Wave 3).
4. **Настраивайте ignoreDifferences для Flagger и динамических мутаций:** это предотвратит постоянный откат канареечных тестов контроллером `argocd-application-controller`.
5. **Включайте `ApplyOutOfSyncOnly=true`:** при наличии сотен объектов IngressRoute эта опция предотвращает повторное отправление неизмененных манифестов в API-сервер, снижая нагрузку на etcd и контроллер Argo CD.
6. **Никаких секретов в открытом виде:** учетные данные basic-auth и приватные ключи TLS должны доставляться в Argo CD исключительно через External Secrets Operator (ESO), Sealed Secrets или SOPS.

---

## Дополнительная информация

- [Argo CD — обзор и ключевые концепции](../../GitOps/ArgoCD/argocd_overview.md) — общая архитектура, контроллеры и принципы работы Argo CD.
- [Ignore Differences в Argo CD](../../GitOps/ArgoCD/synchronization/ignore_differences.md) — детальная настройка исключения дрейфа полей Kubernetes API.
- [Паттерн App-of-Apps в Argo CD](../../GitOps/ArgoCD/argocd_app_of_apps.md) — построение иерархических приложений в GitOps.
- [ApplicationSets в Argo CD](../../GitOps/ArgoCD/argocd_applicationsets.md) — генераторы мультикластерных и мультитенантных инсталляций.
- [Развертывание Traefik: Blue/Green, Canary, Rolling Update](./traefik-deployments.md) — взвешенная балансировка (WRR), Traffic Mirroring и оператор Flagger.
- [Traefik в Kubernetes: CRD, RBAC, Helm, NetworkPolicy](./traefik-kubernetes.md) — спецификации CRD IngressRoute, Middleware, TLSOption и ServersTransport.
- [cert-manager и IngressRoute TLS](./traefik-cert-manager-ingressroute-tls.md) — выпуск TLS-сертификатов Let's Encrypt для Traefik через cert-manager.
- [Шифрование секретов в GitOps](../../GitOps/secrets_encryption.md) — интеграция SOPS, age и безопасность секретов в репозитории.
- [Traefik на Bare-Metal](./traefik-bare-metal.md) — развертывание Traefik под Systemd в физических инфраструктурах.
- [Официальная документация Traefik v3](https://doc.traefik.io/traefik/) — архитектура и параметры конфигурации.
- [Официальная документация Argo CD](https://argo-cd.readthedocs.io/) — руководство администратора и справочник манифестов.
