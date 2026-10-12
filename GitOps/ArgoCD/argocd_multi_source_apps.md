# Argo CD: Multiple Sources и архитектура гидрации манифестов

**Актуально для:** Argo CD v3.5+ (Multiple Sources стабилизированы с v2.6+, внутренняя гидрация в repo-server v3.x; Kubernetes 1.28–1.32+; on-premise / bare-metal)

В стандартной модели Argo CD объект `Application` связывает один целевой репозиторий с одним пространством имен в Kubernetes. Однако в корпоративной практике DevOps и SRE разделение ответственности требует изолировать версионирование базового кода (Helm-чарты, Kustomize-компоненты) от окружения и параметров развертывания (values-файлы, оверлеи сред, секреты). 

Механизм **Multiple Sources** (`spec.sources`) позволяет объединять манифесты из нескольких репозиториев (Git, OCI, Helm-репозитории) в рамках единого приложения с поддержкой взаимных ссылок через `$ref`. Внутренний механизм гидрации источников (`source hydration`) в `argocd-repo-server` разрешает зависимости, подставляет файлы конфигурации и компилирует итоговый поток ресурсов Kubernetes без необходимости генерации избыточных промежуточных коммитов в исходных ветках.

## Предварительные требования

| Компонент / Инструмент | Минимальная версия | Назначение в архитектуре |
| :--- | :--- | :--- |
| **Argo CD** | v2.6+ (рекомендуется v3.5+) | Поддержка массива `spec.sources` и ссылки `$ref` в `helm.valueFiles` |
| **Kubernetes** | v1.28–1.32+ | On-premise / bare-metal кластер (управляющий hub или целевой spoke) |
| **argocd CLI** | v3.5.x | Управление приложениями, локальный рендеринг и проверка diff |
| **kubectl** | v1.28+ | Административный доступ к namespace `argocd` для диагностики подов |
| **Git-хранилище** | GitLab CE/EE / Gitea | Хранение values-файлов, оверлеев и параметров сред с deploy keys / токенами |
| **Helm / OCI Registry** | Harbor v2.8+ / ChartMuseum | Корпоративный реестр Helm-чартов и OCI-артефактов |

## Определения

- **Multiple Sources** — функционал Argo CD, позволяющий специфицировать массив `spec.sources` вместо одиночного `spec.source`. Применяется для сборки приложения из нескольких независимых Git-репозиториев или комбинации Helm/OCI-реестра и Git-репозитория конфигураций.
- **Вторичный источник (Secondary Source)** — элемент массива `spec.sources`, помеченный атрибутом `ref: <alias>`. Этот источник используется не как самостоятельный генератор манифестов верхнего уровня, а как поставщик внешних файлов значений или оверлеев для других источников.
- **Ссылка `ref` (`$ref`)** — механизм интерполяции пути, позволяющий первичному источнику (например, Helm-чарту) обращаться к файлам внутри вторичного источника по синтаксису `$alias/<относительный-путь-к-файлу>`.
- **Внутренняя гидрация манифестов (repo-server Hydration Engine)** — процесс в компоненте `argocd-repo-server`, в рамках которого параллельно скачиваются все объявленные источники, монтируются во временную файловую структуру `/tmp/_app/` или `/tmp/values/<ref>/`, объединяются аргументами генератора (`helm template -f ...`) и преобразуются в чистый YAML-поток.
- **Паттерн Git Hydration (Dry vs. Hydrated Branches)** — архитектурный подход GitOps, при котором параметризованные («сухие» / dry) манифесты (Helm, Kustomize) рендерятся внешним пайплайном (CI/CD) в плоский статический YAML («гидрированные» / hydrated манифесты) и фиксируются в отдельной ветке или репозитории для упрощения аудита, ускорения синхронизации и снятия вычислительной нагрузки с `repo-server`.
- **LWW (Last-Write-Wins) при слиянии ресурсов** — правило разрешения коллизий в Multiple Sources: если два разных источника генерируют ресурс с идентичными `apiVersion`, `kind`, `metadata.name` и `metadata.namespace`, Argo CD применяет манифест из последнего по порядку источника в массиве `spec.sources` и фиксирует событие `RepeatedResourceWarning`.

## Архитектура и базовые концепции

### Внутренняя архитектура Multiple Sources в `argocd-repo-server`

Компонент `argocd-repo-server` выступает вычислительным ядром генерации манифестов. При получении запроса от `argocd-application-controller` на рендеринг приложения с `spec.sources` происходит многоэтапная обработка:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                      Application Manifest (CRD)                        │
│                                                                        │
│  spec:                                                                 │
│    sources:                                                            │
│    - repoURL: 'https://harbor.corp.internal/chartrepo/infra'           │
│      chart: redis                                                      │
│      targetRevision: 17.5.0                                            │
│      helm:                                                             │
│        valueFiles:                                                     │
│        - $values/envs/production/redis-values.yaml                     │
│    - repoURL: 'git@gitlab.corp.internal:infra/app-configs.git'         │
│      targetRevision: main                                              │
│      ref: values                                                       │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        argocd-repo-server                              │
│                                                                        │
│  1. Параллельный Fetch / Clone:                                        │
│     ├── Helm/OCI: скачивание чарта redis-17.5.0.tgz в кеш              │
│     └── Git: git fetch git@gitlab... (bare/cached repo)                │
│                                                                        │
│  2. Изоляция в /tmp (Ephemeral Workspace):                             │
│     ├── /tmp/_app/<hash>/chart/redis/                                  │
│     └── /tmp/_app/<hash>/values/envs/production/redis-values.yaml      │
│                                                                        │
│  3. Разрешение ссылок $ref:                                            │
│     $values/...  ──▶  подставляется путь к каталогу клона с ref: values│
│                                                                        │
│  4. Выполнение рендеринга:                                             │
│     helm template redis /tmp/_app/.../redis                            │
│       -f /tmp/_app/.../values/envs/production/redis-values.yaml        │
│                                                                        │
│  5. Потоковая агрегация манифестов и проверка коллизий:                │
│     Объединение выходных YAML всех источников -> возврат контроллеру    │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ gRPC Response (Manifest stream)
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   argocd-application-controller                        │
│                                                                        │
│  1. Сравнение с фактическим состоянием etcd (Reconciliation Loop)      │
│  2. Вычисление трехстороннего Diff (Server-side diff)                  │
│  3. Применение изменений в целевой Kubernetes Cluster через kube-apiserver │
└────────────────────────────────────────────────────────────────────────┘
```

### Жизненный цикл обработки источников

1. **Параллельная вычитка репозиториев:** Для каждого элемента массива `spec.sources` `repo-server` проверяет локальный кэш репозиториев (по умолчанию в `/tmp/`). Если репозиторий отсутствует или ревизия не закэширована, выполняется `git fetch` или обращение к OCI/Helm registry с использованием учетных данных из Secret в namespace `argocd`.
2. **Создание изолированного рабочего пространства:** В каталоге `/tmp/` создается изолированная директория для конкретной сборки манифестов приложения.
3. **Монтирование репозиториев с `ref`:** Репозиторий, у которого определено поле `ref: <name>`, подготавливается в рабочей директории. Переменная окружения или ссылка вида `$name` транслируется в абсолютный путь к корню данного источника.
4. **Рендеринг каждого источника:**
   - Если источник является Helm-чартом: вызывается `helm template` с переданными значениями (`valueFiles`, `valuesObject`, `parameters`).
   - Если источник является Kustomize: вызывается `kustomize build`.
   - Если источник представляет собой набор статических YAML: выполняется парсинг файлов в директории.
5. **Объединение и дедупликация ресурсов:** Все сгенерированные манифесты соединяются в единый список. Если обнаружены одинаковые ресурсы (`Group`, `Version`, `Kind`, `Namespace`, `Name`), побеждает последний источник в списке `spec.sources`, а контроллер логирует предупреждение.

### Сравнение архитектурных подходов

| Параметр | Single Source | Multiple Sources (`spec.sources`) | Паттерн Pre-rendered Git Hydration (CI) |
| :--- | :--- | :--- | :--- |
| **Разделение чарта и конфигураций** | Требует упаковки values в репозиторий чарта или git submodule | Полная изоляция: чарт в Harbor, values в GitLab | Полная изоляция через пайплайн сборки |
| **Место выполнения рендеринга** | `argocd-repo-server` внутри кластера | `argocd-repo-server` внутри кластера | CI runner (GitLab Runner / Jenkins) |
| **Нагрузка на `repo-server`** | Низкая/Средняя | Повышенная (параллельный I/O и clone нескольких репозиториев) | Минимальная (только чтение готового YAML) |
| **Audit Trail (Аудит отрендеренных манифестов)** | Отсутствует в Git (рендеринг на лету) | Отсутствует в Git (рендеринг на лету) | Полный (каждый отрендеренный манифест зафиксирован коммитом) |
| **Сложность CI/CD** | Минимальная | Минимальная (не требуются CI-джобы для выката) | Высокая (необходимы скрипты генерации и права на push в Git) |
| **Поддержка нативного отката (`argocd app rollback`)** | Поддерживается | **Не поддерживается** (из-за нескольких нескоррелированных ревизий) | Поддерживается (единый коммит в гидрированной ветке) |

## Практические сценарии и конфигурация

### Сценарий 1: Helm-чарт из приватного Harbor (OCI) + многослойные values из GitLab

Классический SRE-паттерн: инфраструктурная команда публикует проверенный Helm-чарт приложения в корпоративный реестр Harbor (через OCI или Helm repository API). Команда эксплуатации хранит настройки для каждого контура (`dev`, `stage`, `prod`) в защищенном репозитории конфигураций `infra/app-configs`.

```yaml
# application-production.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-service-prod
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: production
  sources:
    # 1. Первичный источник: Helm-чарт из OCI-реестра Harbor
    - repoURL: 'harbor.corp.internal/charts'
      chart: 'billing-service'
      targetRevision: '2.4.1'
      helm:
        releaseName: 'billing-prod'
        # Порядок valueFiles задает приоритет: каждый последующий файл переопределяет ключи предыдущих
        valueFiles:
          - '$configs/base/common-defaults.yaml'
          - '$configs/environments/production/values.yaml'
          - '$configs/environments/production/networking.yaml'
        # Прямые переопределения параметров имеют наивысший приоритет над файлами
        parameters:
          - name: 'replicaCount'
            value: '5'
          - name: 'ingress.hosts[0].host'
            value: 'billing.prod.corp.internal'

    # 2. Вторичный источник: Репозиторий конфигураций окружений
    - repoURL: 'git@gitlab.corp.internal:infra/app-configs.git'
      targetRevision: 'release-2026.10'
      ref: configs
      path: 'services/billing-service'

  destination:
    server: 'https://kubernetes.default.svc'
    namespace: 'billing-prod'
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - PruneLast=true
      - ServerSideApply=true
```

**Структура репозитория конфигураций `infra/app-configs.git`:**

```text
services/billing-service/
├── base/
│   └── common-defaults.yaml       # Общие параметры логирования, таймаутов, метрик
└── environments/
    ├── production/
    │   ├── values.yaml            # Ресурсы подов, профили БД, репликация
    │   └── networking.yaml        # Настройки Service, Ingress и NetworkPolicy
    └── staging/
        ├── values.yaml
        └── networking.yaml
```

---

### Сценарий 2: Масштабирование флота через ApplicationSet (Matrix Generator + Multiple Sources)

При управлении десятками кластеров и окружений ручное создание манифестов `Application` недопустимо. `ApplicationSet` позволяет объединить матричный генератор (`matrix`) с `sources`, подставляя нужные ветки и кластеры.

```yaml
# appset-billing-fleet.yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: fleet-billing-service
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  generators:
    - matrix:
        generators:
          # Генератор 1: Список целевых окружений
          - list:
              elements:
                - env: staging
                  chartVersion: 2.5.0-rc.1
                  configBranch: staging
                - env: production
                  chartVersion: 2.4.1
                  configBranch: main
          # Генератор 2: Кластеры для соответствующего окружения (из Secret Argo CD)
          - clusters:
              selector:
                matchLabels:
                  environment: '{{ .env }}'
  template:
    metadata:
      name: 'billing-service-{{ .env }}-{{ .name }}'
      labels:
        environment: '{{ .env }}'
        app.kubernetes.io/part-of: billing
    spec:
      project: '{{ .env }}'
      sources:
        - repoURL: 'harbor.corp.internal/charts'
          chart: 'billing-service'
          targetRevision: '{{ .chartVersion }}'
          helm:
            releaseName: 'billing-service'
            valueFiles:
              - '$configs/environments/{{ .env }}/values.yaml'
              - '$configs/environments/{{ .env }}/clusters/{{ .name }}.yaml'
        - repoURL: 'git@gitlab.corp.internal:infra/app-configs.git'
          targetRevision: '{{ .configBranch }}'
          ref: configs
          path: 'services/billing-service'
      destination:
        server: '{{ .server }}'
        namespace: 'billing'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

---

### Сценарий 3: Kustomize Base из общего каталога + оверлеи из репозитория среды

Multiple Sources можно применять не только для Helm, но и для Kustomize, когда базовые ресурсы хранятся в репозитории платформенной библиотеки (`platform/k8s-base-library`), а специфичные для приложения патчи и оверлеи находятся в репозитории сервиса.

```yaml
# app-kustomize-multisource.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: analytics-worker
  namespace: argocd
spec:
  project: default
  sources:
    # 1. Основной источник приложения с оверлеем Kustomize
    - repoURL: 'git@gitlab.corp.internal:apps/analytics-worker.git'
      targetRevision: 'main'
      path: 'deploy/overlays/production'
    # 2. Дополнительный источник: Платформенные шаблоны и общие ресурсы
    - repoURL: 'git@gitlab.corp.internal:platform/k8s-base-library.git'
      targetRevision: 'v1.12.0'
      ref: platform
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: 'analytics'
```

**Файл `deploy/overlays/production/kustomization.yaml` в репозитории приложения:**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# Ссылка на локальные ресурсы и внешний источник через символическую ссылку или путь $platform
resources:
  - deployment.yaml
  - service.yaml

# Патчи параметров для продакшн-контура
patches:
  - target:
      kind: Deployment
      name: analytics-worker
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 8
```

---

### Сценарий 4: Комбинирование разнородных манифестов (Helm-чарт + платформенные CRD и мониторинг)

Часто сторонний или внутренний Helm-чарт не содержит нужных для SRE объектов мониторинга (ServiceMonitor, PrometheusRule) или корпоративных NetworkPolicy. В Multiple Sources можно объединить Helm-чарт и каталог со статическими YAML-манифестами.

```yaml
# app-combined-service.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: redis-ha-monitoring
  namespace: argocd
spec:
  project: infrastructure
  sources:
    # Источник 1: Официальный Helm-чарт Redis
    - repoURL: 'https://charts.bitnami.com/bitnami'
      chart: 'redis'
      targetRevision: '18.2.1'
      helm:
        valueFiles:
          - '$env/redis/values.yaml'

    # Источник 2: Конфигурационный Git-репозиторий (values)
    - repoURL: 'git@gitlab.corp.internal:infra/k8s-environments.git'
      targetRevision: 'main'
      ref: env
      path: 'production'

    # Источник 3: Платформенные манифесты (PrometheusRule, ServiceMonitor, NetworkPolicy)
    - repoURL: 'git@gitlab.corp.internal:infra/monitoring-rules.git'
      targetRevision: 'main'
      path: 'alerts/redis'

  destination:
    server: 'https://kubernetes.default.svc'
    namespace: 'redis-system'
```

---

### Сценарий 5: Архитектурный паттерн Dry/Hydrated Branches (CI Pre-rendering)

В средах с повышенными требованиями к ИБ (PCI-DSS, финтех) динамический запуск `helm template` внутри кластера на `repo-server` может быть запрещен, либо требуется строгий криптографический аудит коммитов перед применением.

Паттерн предполагает разделение репозитория на:
1. **Dry-источник (ветка `main`):** содержит `Chart.yaml`, исходные шаблоны, `values.yaml`.
2. **Hydrated-источник (ветка `hydrated` или отдельный репозиторий `gitops-manifests`):** содержит только плоские манифесты `.yaml`, отрендеренные в CI пайплайне.

```text
┌───────────────────────┐
│ Разработчик / SRE     │
│ git push origin main  │
└───────────┬───────────┘
            │
            ▼
┌────────────────────────────────────────────────────────────────────────┐
│ GitLab CI Runner (Изолированный контур сборки)                         │
│                                                                        │
│ 1. Скачивание зависимостей: helm dependency build                      │
│ 2. Рендеринг манифестов:                                               │
│    helm template my-app . -f values.yaml -f envs/prod.yaml > /tmp/out  │
│ 3. Валидация и аудит безопасности:                                     │
│    kubeconform --strict /tmp/out.yaml                                  │
│    trivy config /tmp/out.yaml                                          │
│ 4. Фиксация артефакта:                                                 │
│    git checkout hydrated && cp /tmp/out.yaml ./manifests.yaml          │
│    git commit -m "Hydrate commit ${CI_COMMIT_SHA}" && git push         │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Argo CD Application                                                    │
│ Синхронизирует исключительно ветку hydrated (Zero-overhead на рендеринг)│
└────────────────────────────────────────────────────────────────────────┘
```

**Пример конфигурации `.gitlab-ci.yml` для автоматической гидрации:**

```yaml
stages:
  - hydrate

hydrate_manifests:
  stage: hydrate
  image: harbor.corp.internal/platform/gitops-builder:v1.4.0
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
  before_script:
    - git config --global user.name "GitOps Hydrator Bot"
    - git config --global user.email "gitops-bot@corp.internal"
    - git remote set-url origin "https://oauth2:${GL_CI_TOKEN}@gitlab.corp.internal/${CI_PROJECT_PATH}.git"
  script:
    - mkdir -p /tmp/hydrated-output
    - helm dependency build ./helm/app
    - helm template app ./helm/app -f ./helm/app/values.yaml -f ./envs/production.yaml > /tmp/hydrated-output/all-manifests.yaml
    - kubeconform -kubernetes-version 1.30.0 -strict /tmp/hydrated-output/all-manifests.yaml
    - git fetch origin hydrated:hydrated || git checkout -b hydrated
    - git checkout hydrated
    - cp /tmp/hydrated-output/all-manifests.yaml ./manifests.yaml
    - git add manifests.yaml
    - |
      if git diff --staged --quiet; then
        echo "Изменений в отрендеренных манифестах нет. Пропуск коммита."
      else
        git commit -m "Auto-hydrate manifests from commit ${CI_COMMIT_SHA} [skip ci]"
        git push origin hydrated
      fi
```

**Манифест Argo CD Application для гидрированной ветки:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: core-app-hydrated
  namespace: argocd
spec:
  project: production
  source:
    repoURL: 'https://gitlab.corp.internal/apps/core-app.git'
    targetRevision: 'hydrated'
    path: '.'
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: 'core-app'
```

## Операции и команды

Все операции валидации, синхронизации и инспекции выполняются через `argocd CLI` и `kubectl`.

### 1. Проверка конфигурации источников приложения

```bash
# Выгрузка текущей конфигурации источников
argocd app get billing-service-prod -o yaml | yq '.spec.sources'
# → [
# →   {
# →     "chart": "billing-service",
# →     "helm": {
# →       "releaseName": "billing-prod",
# →       "valueFiles": [
# →         "$configs/base/common-defaults.yaml",
# →         "$configs/environments/production/values.yaml"
# →       ]
# →     },
# →     "repoURL": "harbor.corp.internal/charts",
# →     "targetRevision": "2.4.1"
# →   },
# →   {
# →     "path": "services/billing-service",
# →     "ref": "configs",
# →     "repoURL": "git@gitlab.corp.internal:infra/app-configs.git",
# →     "targetRevision": "release-2026.10"
# →   }
# → ]
```

### 2. Тестирование сборки и рендеринга манифестов через CLI

Команда запрашивает у `repo-server` рендеринг всех источников без внесения изменений в кластер:

```bash
# Проверка рендеринга манифестов на стороне repo-server
argocd app manifests billing-service-prod | grep -E "^apiVersion:|^kind:|^metadata:" -A 1
# → apiVersion: apps/v1
# → kind: Deployment
# → metadata:
# →   name: billing-service
# → --
# → apiVersion: v1
# → kind: Service
# → metadata:
# →   name: billing-service
# → --
# → apiVersion: networking.k8s.io/v1
# → kind: Ingress
# → metadata:
# →   name: billing-service
```

### 3. Просмотр расхождений (Diff) с кластером

```bash
# Вычисление Server-Side diff для всех объединенных ресурсов
argocd app diff billing-service-prod --server-side
# → ===== apps/Deployment billing-prod/billing-service ======
# → 128c128
# → <         image: harbor.corp.internal/apps/billing:2.4.0
# → ---
# → >         image: harbor.corp.internal/apps/billing:2.4.1
# → 142c142
# → <       replicas: 3
# → ---
# → >       replicas: 5
```

### 4. Принудительный сброс кэша и регенерация (Hard Refresh)

При пуше изменений во вторичный репозиторий без настроенного вебхука необходимо запросить перечитку:

```bash
# Жесткая очистка кэша repo-server и повторное клонирование источников
argocd app get billing-service-prod --hard-refresh
# → Name:               argocd/billing-service-prod
# → Project:            production
# → Server:             https://kubernetes.default.svc
# → Namespace:          billing-prod
# → URL:                https://argocd.corp.internal/applications/billing-service-prod
# → Repo (1/2):         harbor.corp.internal/charts
# → Target (1/2):       2.4.1
# → Path (1/2):         billing-service
# → Repo (2/2):         git@gitlab.corp.internal:infra/app-configs.git
# → Target (2/2):       release-2026.10
# → Path (2/2):         services/billing-service
# → Sync Status:        OutOfSync from 2.4.1, release-2026.10
# → Health Status:      Healthy
```

### 5. Ручная синхронизация приложения с контролем Prune

```bash
# Запуск синхронизации с удалением устаревших объектов
argocd app sync billing-service-prod --prune
# → TIMESTAMP                  GROUP        KIND   NAMESPACE                  NAME    STATUS    HEALTH        HOOK  MESSAGE
# → 2026-10-12T14:15:02+03:00   apps  Deployment  billing-prod       billing-service  Synced   Progressing          deployment.apps/billing-service configured
# → 2026-10-12T14:15:03+03:00         Service      billing-prod       billing-service  Synced   Healthy              service/billing-service configured
# → 2026-10-12T14:15:04+03:00   apps  Deployment  billing-prod       billing-service  Synced   Healthy              deployment.apps/billing-service updated
```

## Диагностика и устранение неполадок

### Сводная таблица типовых сбоев

| Ошибка / Симптом | Первопричина | Метод верификации | Способ устранения |
| :--- | :--- | :--- | :--- |
| `could not retrieve ref <alias>` | Опечатка в имени `$alias` в `helm.valueFiles` или отсутствие `ref: <alias>` во втором источнике | `argocd app get <app> -o yaml \| grep -E 'ref:|valueFiles:'` | Убедиться, что имя после символа `$` в пути в точности совпадает с полем `ref:` вторичного источника (регистрозависимо). |
| `stat /tmp/_app/.../values.yaml: no such file or directory` | Неверный относительный путь внутри вторичного репозитория или опечатка в `path` | `git ls-tree -r --name-only <targetRevision>` в Git | Скорректировать путь: `$ref/<path-inside-repo>/values.yaml`. Убедиться, что файл присутствует в указанной ветке `targetRevision`. |
| `RepeatedResourceWarning` | Два разных источника в `spec.sources` сгенерировали одинаковый Kubernetes-ресурс | `argocd app manifests <app> \| grep -E '^kind:\|^  name:'` | Изменить имя одного из ресурсов либо удалить дубликат из платформенного каталога. Принять во внимание, что победит последний источник. |
| `failed to clone within 90s: context deadline exceeded` | Тяжелый Git-репозиторий с большой историей или медленный канал; repo-server не успевает склонировать несколько источников | `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server \| grep "timeout"` | Настроить `ARGOCD_EXEC_TIMEOUT: "180s"` в ConfigMap `argocd-cm`, оптимизировать репозитории (git shallow clone). |
| `Authentication failed for repository` | Для одного из репозиториев в `spec.sources` не настроен Secret с credentials в namespace `argocd` | `argocd repo list` | Создать отдельный Secret с типом `repo-creds` или зарегистрировать каждый репозиторий через `argocd repo add`. |
| Изменение в Git не вызывает Auto-Sync | GitLab Webhook отправляет push-событие, но URL вебхука не сопоставляется с вторичным источником | `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server \| grep -i webhook` | Настроить Webhook в **обоих** Git-репозиториях (и чарта, и конфигураций) на адрес `https://argocd.corp.internal/api/webhook`. |
| Ошибка вызова `argocd app rollback` | Попытка выполнить нативный откат для приложения с `spec.sources` | CLI возвращает: `Rollback is not supported for multi-source applications` | Откатывать изменения коммитом в Git (GitOps revert), а не через состояние в etcd Argo CD. |

---

### Детальные сценарии отладки

#### Сценарий отладки 1: Диагностика ошибки разрешения `$ref`

При несовпадении имен или путей `repo-server` не может смонтировать файл значений:

```bash
# 1. Проверка сообщения об ошибке в статусе Application
kubectl get application billing-service-prod -n argocd -o jsonpath='{.status.conditions}' | jq .
# → [
# →   {
# →     "lastTransitionTime": "2026-10-12T14:18:22Z",
# →     "message": "ComparisonError: helm template failed: could not retrieve ref 'configs': reference not found in sources",
# →     "type": "ComparisonError"
# →   }
# → ]

# 2. Проверка описания источников в манифесте
kubectl get application billing-service-prod -n argocd -o jsonpath='{.spec.sources[*].ref}'
# → config   <-- Внимание! В манифесте указано 'config', а в helm.valueFiles используется '$configs'
```

**Решение:** Привести имя алиаса в соответствие: заменить `$configs/...` на `$config/...` или обновить поле `ref: configs`.

---

#### Сценарий отладки 2: Инспекция дискового пространства и временных директорий `repo-server`

Когда десятки приложений используют Multiple Sources, `argocd-repo-server` может исчерпать дисковый лимит по причине клонирования нескольких репозиториев на одно приложение:

```bash
# 1. Проверка использования диска внутри пода repo-server
kubectl exec -it -n argocd deployment/argocd-repo-server -- df -h /tmp
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/nvme0n1p1   50G   47G  3.0G  94% /tmp

# 2. Проверка зависших временных рабочих директорий приложений
kubectl exec -it -n argocd deployment/argocd-repo-server -- du -sh /tmp/_app/* | sort -hr | head -n 5
# → 8.4G    /tmp/_app/4a1b8c2d9e...
# → 6.1G    /tmp/_app/7f3e1a0b5c...
# → 4.5G    /tmp/_app/1c9d8a7e3f...

# 3. Принудительная очистка старых временных файлов (при необходимости)
kubectl exec -it -n argocd deployment/argocd-repo-server -- find /tmp/_app -mindepth 1 -maxdepth 1 -mmin +120 -exec rm -rf {} +
# → Cleaned up temporary directories older than 2 hours.
```

---

#### Сценарий отладки 3: Мониторинг производительности через Prometheus и метрики

Для контроля нагрузки на `repo-server` при сборке multi-source приложений используются метрики Prometheus:

```promql
# 1. 95-й перцентиль времени выполнения генерации манифестов repo-server (в секундах)
histogram_quantile(0.95, sum(rate(argocd_repo_server_exec_duration_seconds_bucket[5m])) by (le))

# 2. Количество запросов к Git-репозиториям с разбивкой по кодам возврата
sum(rate(argocd_git_request_total[5m])) by (repo, status)

# 3. Количество приложений, находящихся в состоянии ошибки синхронизации
sum(argocd_app_info{sync_status="OutOfSync", health_status="Degraded"}) by (project)
```

## Рекомендации и лучшие практики

### 1. Правило разделения ответственности (SoC) в репозиториях

- **Helm Chart Repo (Artifact Repository):** Хранит только переиспользуемый шаблон сервиса (`templates/`, `Chart.yaml`, дефолтные `values.yaml`). Управляется продуктовой командой, тестируется в изолированном контуре и версионируется строгим SemVer (например, `harbor.corp.internal/charts/my-app:1.8.2`).
- **Config Repo (Environment Git Repository):** Хранит только параметры окружений (`production/values.yaml`, `staging/values.yaml`). Управляется SRE и релизными инженерами.
- **Platform Repo:** Хранит общие библиотеки, политики безопасности, шаблоны сетевых доступов.

### 2. Ограничение количества источников (Принцип анти-монолита)

Официальная документация и SRE-практика настоятельно рекомендуют **не превышать лимит в 2–3 источника** в массиве `spec.sources`. 
- Не используйте `spec.sources` для группировки десятка несвязанных между собой микросервисов в одно «мега-приложение».
- Для оркестрации независимых микросервисов применяйте паттерн **App of Apps** либо **ApplicationSet**.
- Если в `spec.sources` накапливается 4 и более источников, цикл сборки приложения в `repo-server` кратно удлиняется, создавая узкое горлышко по I/O и сетевым запросам.

### 3. Тюнинг параметров `argocd-cm` для ускорения сборки

В корпоративном кластере с активным использованием Multiple Sources рекомендуется скорректировать параметры в ConfigMap `argocd-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  # Увеличение таймаута ожидания ответа от repo-server (актуально при параллельном клонировании)
  controller.repo.server.timeout.seconds: "120"
  
  # Таймаут на выполнение Git-операций
  timeout.git: "90s"
  
  # Время жизни кэша отрендеренных манифестов (по умолчанию 24ч)
  # Позволяет не пересобирать манифесты, если ревизии обоих источников не изменились
  repo.cache.expiration: "24h"
```

Параметры для контейнера `argocd-repo-server` в Deployment `argocd-repo-server`:

```yaml
spec:
  template:
    spec:
      containers:
        - name: argocd-repo-server
          env:
            # Предотвращение зависания утилит Helm/Git
            - name: ARGOCD_EXEC_TIMEOUT
              value: "120s"
            # Максимальное количество одновременных процессов рендеринга на один под
            - name: ARGOCD_CONCURRENCY_LIMIT
              value: "30"
          resources:
            requests:
              cpu: "1000m"
              memory: "2Gi"
            limits:
              cpu: "4000m"
              memory: "8Gi"
```

### 4. Управление секретами в среде Multiple Sources

Никогда не коммитьте незашифрованные секреты в репозиторий `app-configs`:
- **Sealed Secrets:** Зашифрованные Secret-манифесты хранятся непосредственно во вторичном Git-репозитории и расшифровываются контроллером Sealed Secrets в кластере.
- **HashiCorp Vault + External Secrets Operator (ESO):** В Git хранятся манифесты `ExternalSecret`, ссылающиеся на ключи в корпоративном Vault.
- **Argo CD Vault Plugin (AVP):** Если используется CMP v2 sidecar, AVP подставляет секреты в оперативной памяти `repo-server`. При использовании с Multiple Sources убедитесь, что AVP-плагин настроен на обработку объединенного потока манифестов.

## Ограничения и граничные случаи

### 1. Взаимоисключение `spec.source` и `spec.sources`

Поля `spec.source` и `spec.sources` являются **строго взаимоисключающими**.
- Если в манифесте объявлено поле `spec.sources`, контроллер Argo CD полностью игнорирует поле `spec.source` (либо выдает ошибку валидации схемы в зависимости от настроек admission webhook).
- Недопустимо совместное использование этих полей в одном манифесте.

### 2. Блокировка нативного отката (`argocd app rollback`)

В одиночном приложении (`spec.source`) откат работает путем переключения на конкретный ID ревизии в истории развертываний. В приложении с Multiple Sources история приложения состоит из матрицы ревизий (`[rev1, rev2, ...]`). 
- Нативный откат через `argocd app rollback <app-name> <revision-id>` **не поддерживается** для приложений с Multiple Sources.
- Единственным легитимным способом отката является GitOps-откат: выполнение `git revert` в Git-репозитории конфигураций или переключение тега Helm-чарта с последующим коммитом.

### 3. Интеграция с Argo CD Image Updater

При автоматическом обновлении тегов контейнеров через `argocd-image-updater`:
- Image Updater должен точно знать, в какой именно репозиторий из списка `spec.sources` производить запись (`write-back`).
- При использовании Multiple Sources обязательно явно указывать параметры `writeBackConfig.method: git` и `gitConfig.repository` с целевым файлом `writeBackTarget: "helmvalues:./environments/prod/values.yaml"`, иначе Image Updater попытается выполнить запись в репозиторий Helm-чарта и завершится ошибкой доступа.

### 4. Порядок Sync Waves и Hooks

Если ресурсы аннотированы `argocd.argoproj.io/sync-wave` в разных источниках:
- Argo CD формирует общий граф выполнения Sync Waves независимо от того, из какого источника пришел ресурс.
- Ресурс из вторичного источника с волной `wave: 0` будет применен раньше, чем ресурс из первичного источника с волной `wave: 1`.
- Ресурсы PreSync / PostSync хуков корректно оркестрируются контроллером, если они не конфликтуют по имени и пространству имен.

## Дополнительная информация

### См. также

- [Helm интеграция](./helm_integration.md) — Базовый рендеринг Helm, CMP-плагины, жизненный цикл и разрешение зависимостей.
- [ApplicationSet — генераторы приложений](./argocd_applicationsets.md) — Матричные, Git- и List-генераторы для автоматизации флота приложений.
- [Диагностика и мониторинг](./argocd_troubleshooting_and_monitoring.md) — Системный траблшутинг контроллера, метрики Prometheus и логирование.
- [Синхронизация приложений](./synchronization.md) — Reconciliation loop, Server-Side diff, Sync Waves и управление фазами синхронизации.
- [Кастомные инструменты и CMP v2](./argocd_custom_tooling.md) — Настройка sidecar-контейнеров плагинов генерации манифестов.
- [Безопасность](./argocd_security_hardening.md) — Сетевые политики repo-server, mTLS, TLS-сертификаты и изоляция.
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — Ограничение `sourceRepos` и белые списки целевых пространств имен.
- [Image Updater](./argocd_image_updater.md) — Автоматический write-back образов контейнеров в Git при работе с Multiple Sources.
- [Установка и настройка](./argocd_installation_and_setup.md) — Базовое развертывание компонентов Argo CD на bare-metal Kubernetes.

### Ссылки на официальную документацию

- [Argo CD Multiple Sources Application Guide](https://argo-cd.readthedocs.io/en/stable/user-guide/multiple_sources/)
- [Argo CD Application CRD Specification](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#applications)
- [Argo CD High Availability & Repo Server Scaling](https://argo-cd.readthedocs.io/en/stable/operator-manual/high_availability/)
