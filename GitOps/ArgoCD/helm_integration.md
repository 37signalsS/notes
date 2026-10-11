# Интеграция Argo CD с Helm

**Актуально для:** Argo CD v3.4+ (покрывает v3.4.x, v3.5.x, v3.6.x; отличаются Server-Side Diff по умолчанию, Progressive Syncs Beta, Multiple Sources стабилизация)

## Предварительные требования

Перед работой с интеграцией Argo CD и Helm убедитесь в выполнении следующих условий:

1. **Кластер Kubernetes:** версия v1.26+ (рекомендуется v1.28+ для полной поддержки Server-Side Apply и OCI).
   ```bash
   kubectl version --short
   # → Client Version: v1.28.x, Server Version: v1.28.x
   ```

2. **Argo CD установлен и доступен:** проверьте статус подов:
   ```bash
   kubectl get pods -n argocd
   # → NAME                                        READY   STATUS    RESTARTS   AGE
   # → argocd-application-controller-0             1/1     Running   0          5d
   # → argocd-repo-server-xxxxx                    1/1     Running   0          5d
   # → argocd-server-xxxxx                         1/1     Running   0          5d
   # → argocd-dex-server-xxxxx                     1/1     Running   0          5d
   ```

3. **Helm установлен:** v4.0+ (рекомендуется) или v3.12+ (legacy). Проверка:
   ```bash
   helm version
   # → version.BuildInfo{Version:"v4.0.2", GitCommit:"...", GitTreeState:"clean", GoVersion:"go1.21.x"}
   ```

4. **CLI `argocd`:** Установлен (версия, совместимая с сервером) и настроен вход:
   ```bash
   argocd version
   argocd login <ARGOCD_SERVER> --username admin --password <password>
   # → 'admin:login' logged in successfully
   # Context '<ARGOCD_SERVER>' updated
   ```

5. **Git-репозиторий:** Доступен с манифестами или Helm-чартами. Проверьте доступность:
   ```bash
   git ls-remote <REPO_URL> HEAD
   # → <commit-hash>	HEAD
   ```

6. **RBAC:** Права администратора кластера для первоначальной настройки репозиториев и проектов. Для операций управления приложениями достаточно соответствующих ролей в AppProject.
   ```bash
   kubectl auth can-i create applications --namespace argocd
   # → yes
   ```

7. **OCI-реестр доступен** (если используются OCI-артефакты): проверьте доступность реестра и наличие credentials в `argocd` namespace.
   ```bash
   kubectl get secret -n argocd -l argocd.argoproj.io/secret-type=repository
   # → NAME                 TYPE     DATA   AGE
   # → oci-registry-creds   Opaque   4      1h
   ```

8. **Понимание AppProject** — Helm-интеграция тесно связана с проектами для ограничения источников чартов (см. [AppProject](./argocd_appproject_deep.md)).

## Определения

**Helm** — пакетный менеджер для Kubernetes, использующий формат чартов для декларативного описания приложений. Версии: v3 (legacy, 2020) и v4 (2024+, отказ от legacy API, встроенный SSA).

**Helm-чарт (Chart)** — упакованный набор манифестов и шаблонов (Go templates + Sprig), описывающих связанные ресурсы Kubernetes. Состоит из `Chart.yaml`, `values.yaml`, `templates/`, опционально `Chart.lock`, `values.schema.json`, `README.md`.

**Файлы значений (Values)** — внешние параметры конфигурации (YAML), позволяющие адаптировать один чарт под разные окружения (dev, staging, prod). Приоритет наложения: `values.yaml` (базовый) → `values-<env>.yaml` (переопределения) → CLI `--set` (высший приоритет).

**OCI-артефакты (OCI Artifacts)** — современный стандарт упаковки и хранения Helm-чартов в Docker-реестрах (Harbor, GHCR, Quay, локальные реестры). Используют `application/vnd.cncf.helm.chart.content.v1.tar+gzip` media type. Поддерживаются с Argo CD v2.3+, стабильны в v3.1+.

**Multiple Sources** — механизм Argo CD (v2.6+, стабилен v3.0+), позволяющий объединять в одном приложении чарт из внешнего репозитория (Helm/OCI) и конфигурации (`values.yaml`) из приватного Git-репозитория через `sources[]` + `ref: values`.

**AppProject** — логическая группировка приложений в Argo CD с ограничениями по источникам (`sourceRepositories`), целевым кластерам (`destinations`) и namespace. Критичен для Helm: ограничивает, какие репозитории чартов может использовать приложение.

**Server-Side Apply (SSA)** — режим применения манифестов через Kubernetes API (`fieldManager=argocd`), обходящий лимит аннотации `last-applied-configuration` (256 KB). В Argo CD v3.4+ включён по умолчанию для больших чартов через `syncOptions: ServerSideApply=true`.

**Config Management Plugins (CMP)** — механизм расширения рендеринга Argo CD через sidecar-контейнеры в `repo-server` (CMP v2, v2.6+) или процесс в основном контейнере (CMP v1, legacy). Позволяет использовать Helmwave, Helmfile, helm-secrets, Kustomize поверх Helm.

**sourceHydrator** — компонент Argo CD (v2.6+), отвечающий за подготовку источников перед рендерингом: клонирование Git, скачивание OCI/Helm-чартов, разрешение зависимостей (`helm dependency build`), выполнение CMP-плагинов.

## Базовые концепции

### Архитектура рендеринга Helm в Argo CD

Argo CD рендерит Helm-чарты на стороне `argocd-repo-server` через компонент `sourceHydrator` (v2.6+):

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              Argo CD + Helm: Pipeline рендеринга (v3.x)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐     ┌──────────────────┐     ┌──────────────────────┐   │
│  │   Источники  │────▶│  sourceHydrator  │────▶│  Helm Template / CMP │   │
│  │              │     │  (в repo-server) │     │  (рендеринг)         │   │
│  │ • Git (HTTP/ │     │                  │     │                      │   │
│  │   SSH)       │     │ 1. Clone/fetch   │     │ • helm template      │   │
│  │ • Helm repo  │     │ 2. OCI pull      │     │ • CMP plugin         │   │
│  │ • OCI reg    │     │ 3. dep build     │     │ • Kustomize overlay  │   │
│  │ • Directory  │     │ 4. Plugin exec   │     │                      │   │
│  └──────────────┘     └──────────────────┘     └──────────────────────┘   │
│         │                    │                         │                   │
│         ▼                    ▼                         ▼                   │
│  ┌──────────────┐     ┌──────────────────┐     ┌──────────────────────┐   │
│  │ Кэш          │     │ Подготовленные   │     │  YAML манифесты      │   │
│  │ (in-memory,  │     │ источники        │     │  (Deploy, Svc,       │   │
│  │  TTL 5m)     │     │ (chart + values) │     │   ConfigMap, etc.)   │   │
│  └──────────────┘     └──────────────────┘     └──────────────────────┘   │
│                                                             │               │
│                                                             ▼               │
│                                              ┌──────────────────────────┐   │
│                                              │ Application Controller  │   │
│                                              │ (sync, apply, prune)    │   │
│                                              │ fieldManager=argocd     │   │
│                                              └──────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Процесс рендеринга (пошагово):**

1. **Application Controller** ставит задачу в очередь синхронизации.
2. **sourceHydrator** (в `repo-server` поде) подготавливает источники:
   - Git: shallow clone (`--depth=1` по умолчанию) или полный клон
   - Helm repo: `helm pull` чарта в кэш (`/tmp/helm-cache/`)
   - OCI: `oras pull` или `helm registry` в кэш
   - Directory: чтение локальных файлов
   - Выполнение `helm dependency build` при наличии `Chart.lock`
   - Запуск CMP-плагинов (sidecar в CMP v2)
3. **Helm Template Engine** выполняет рендеринг: `helm template <release> <chart> -f <values...>`
4. **Результат** (YAML манифесты) кэшируется в памяти `repo-server` (TTL ~5 минут, настраивается `repo.server.cache.expiration`)
5. **Application Controller** применяет манифесты через Kubernetes API:
   - **Client-Side Apply** (по умолчанию): `kubectl apply` с аннотацией `last-applied-configuration`
   - **Server-Side Apply** (`ServerSideApply=true`): `kubectl apply --server-side --field-manager=argocd`

**Важно:** Argo CD **не выполняет** `helm install`/`helm upgrade`. Он только рендерит манифесты и применяет их через API Kubernetes. Это означает, что:
- Helm-релизы **не создаются** в кластере (нет записей в Secret `sh.helm.release.v1`).
- Управление состоянием через Helm CLI невозможно (`helm list`, `helm status` не работают).
- Для отката используется Argo CD Rollback (`argocd app rollback`), а не `helm rollback`.
- `helm history` недоступен — история в `argocd app history`.

### Подход 1: Нативная поддержка Helm-репозиториев

Argo CD выполняет рендеринг чарта (`helm template`) на стороне `argocd-repo-server`. В версии v3.4+ обеспечена полная поддержка **Helm 4** (v4.0+), что повышает безопасность за счет отказа от устаревших API.

**Helm 4 vs Helm 3 в контексте Argo CD:**

| Параметр | Helm 3 | Helm 4 |
| :--- | :--- | :--- |
| **Server-Side Apply** | Опционально (флаг) | Встроенная поддержка, в Argo CD — `syncOptions: ServerSideApply=true` |
| **OCI-поддержка** | Экспериментальная (`helm registry`) | Стабильный OCI API (`helm pull/push oci://`) |
| **Безопасность** | Устаревшие API (K8s ≤1.22) | Отказ от legacy API, требует K8s 1.25+ |
| **Производительность** | Стандартная | Оптимизированный рендеринг, меньше аллокаций |
| **values.schema.json** | Опциональная валидация | Встроенная строгая валидация по умолчанию |

#### Традиционный Helm-репозиторий (HTTP/HTTPS)

```yaml
spec:
  source:
    repoURL: 'https://charts.bitnami.com/bitnami'
    chart: 'redis'
    targetRevision: 16.8.9  # Фиксированная версия, не latest
    helm:
      # Опционально: дополнительные values-файлы из того же репозитория
      valueFiles:
        - values-prod.yaml
      # Опционально: параметры рендеринга
      parameters:
        - name: redis.password
          value: "secret"
      # Опционально: пропуск CRD валидации при первом деплое
      skipCrds: false
```

#### OCI-совместимый репозиторий

Для работы с OCI-реестрами необходимо предварительно настроить учетные данные в настройках Argo CD.

**1. Создание секрета для OCI-реестра:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: oci-registry-creds
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  url: ghcr.io/argoproj/charts
  username: <имя-пользователя>
  password: <токен>
  type: oci
```

**2. Применение секрета:**
```bash
kubectl apply -f oci-secret.yaml
# → secret/oci-registry-creds created
```

**3. Манифест Application:**
```yaml
spec:
  source:
    repoURL: 'ghcr.io/argoproj/charts'
    chart: 'argo-cd'
    targetRevision: '5.50.0'  # Точная версия тега в OCI
```

**Нюансы v3.4+:**
- **Производительность:** Repo-server кеширует результаты рендеринга (in-memory, TTL 5m), снижая нагрузку на Git и сеть.
- **Строгая валидация:** Поддержка `values.schema.json` включена по умолчанию — невалидные values блокируют синхронизацию.
- **OCI credentials:** Для приватных реестров настройте credentials через Kubernetes Secret (как выше) или в `argocd-cm` ключ `repositories`.
- **Поведение targetRevision:** В OCI это точный тег (semver) или digest (`sha256:...`); не поддерживает диапазоны вроде `5.x.x`.

### Подход 2: Использование нескольких источников (Multiple Sources)

Это промышленный стандарт для GitOps-процессов. Он позволяет использовать публичный "золотой" чарт и хранить специфичные для компании `values.yaml` в отдельном закрытом репозитории.

```yaml
spec:
  sources:
    - repoURL: 'https://charts.bitnami.com/bitnami'
      chart: 'redis'
      targetRevision: 16.8.9
      helm:
        valueFiles:
          - $values/infra/redis/values-prod.yaml
    - repoURL: 'https://github.com/my-org/gitops-config.git'
      targetRevision: HEAD
      ref: values # Алиас для обращения из первого источника через $values/
```

**Ключевые преимущества:**
- **Разделение ответственности:** Инфраструктурная команда управляет чартом, команды разработки — значениями.
- **Атомарность:** Все изменения конфигурации фиксируются в Git, обеспечивая полный аудит.
- **Безопасность:** Секреты и специфичная конфигурация хранятся в приватном репозитории, а не в публичном чарте.

**Пример: Multiple Sources с несколькими values-файлами (слои конфигурации):**
```yaml
spec:
  sources:
    - repoURL: 'https://charts.bitnami.com/bitnami'
      chart: 'postgresql'
      targetRevision: 12.5.0
      helm:
        valueFiles:
          - $values/apps/my-app/values-base.yaml      # Базовые настройки
          - $values/apps/my-app/values-prod.yaml      # Продакшн-переопределения
          - $values/apps/my-app/values-secrets.yaml   # Секреты (через AVP/Vault)
    - repoURL: 'https://github.com/my-org/gitops-config.git'
      targetRevision: main
      ref: values
```

**Важно:** Ссылка на значения из внешнего репозитория начинается с `$values/` (символ доллара + имя `ref`). Порядок `valueFiles` определяет приоритет наложения: последнее значение побеждает.

**Внутренняя механика Multiple Sources (v3.4+):**
1. `sourceHydrator` клонирует все источники параллельно
2. Источник с `ref: values` монтируется в `/tmp/values/<ref>/`
3. Первый источник (chart) обращается к `$values/...` → разрешается в `/tmp/values/values/...`
4. `helm template` запускается с объединённым набором `-f` файлов

### Подход 3: Рендеринг манифестов в CI

Манифесты генерируются внешней системой (GitLab CI, GitHub Actions) и сохраняются в Git как чистый YAML.

**Когда использовать:**
- Требуется глубокое патчирование через Kustomize, которое невозможно средствами Helm.
- Необходимо сканирование манифестов (Trivy/Checkov) *до* их попадания в кластер.
- Используются сложные генераторы (например, Jsonnet), не поддерживаемые Argo CD нативно.

**Пример CI-пайплайна (GitHub Actions):**
```yaml
jobs:
  render:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Render Helm
      run: |
        helm dependency update charts/my-app
        helm template my-app charts/my-app \
          -f values/prod.yaml \
          --output-dir ./manifests

    - name: Scan manifests
      run: |
        trivy config ./manifests --severity CRITICAL,HIGH
        kubeconform ./manifests

    - name: Commit to GitOps repo
      run: |
        git add ./manifests
        git commit -m "chore: update manifests for prod"
        git push
```

## Продвинутая интеграция через плагины (CMP v2)

Для инструментов, выходящих за рамки стандартного `helm template` (например, Helmwave, Helmfile или расшифровка секретов через `helm-secrets`), используются **[Config Management Plugins](./argocd_custom_tooling.md)**.

**Сценарий использования Helmwave через CMP:**
1. В `repo-server` добавляется sidecar с бинарным файлом `helmwave`.
2. В манифесте `Application` указывается имя плагина.
3. Плагин выполняет сборку графа зависимостей и рендеринг всех ресурсов стека.

**Сравнение CMP v1 и CMP v2:**

| Характеристика | CMP v1 (Legacy) | CMP v2 (Modern) |
| :--- | :--- | :--- |
| **Архитектура** | Процесс в основном контейнере | Sidecar-контейнер |
| **Безопасность** | Общее пространство имен | Изолированный контейнер |
| **Зависимости** | Ограничены основным образом | Полная независимость |
| **Обнаружение** | Ручная настройка | Автоматическое (Discovery) |

Подробнее: **[Custom Tooling и плагины (CMP)](./argocd_custom_tooling.md)**.

## Масштабирование через ApplicationSet

Для управления сотнями однотипных Helm-приложений используется генератор `Git`.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: helm-apps
  namespace: argocd
spec:
  generators:
  - git:
      repoURL: https://github.com/my-org/gitops-repo.git
      directories:
      - path: apps/*
  template:
    metadata:
      name: '{{path.basename}}'
    spec:
      project: default
      source:
        repoURL: 'https://charts.example.com'
        chart: 'common-app-engine'
        targetRevision: 1.2.0
        helm:
          valueFiles:
          - '{{path}}/values.yaml'
      destination:
        server: https://kubernetes.default.svc
        namespace: production
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
        - CreateNamespace=true
```

**Типы генераторов для Helm:**

| Генератор | Описание | Пример использования |
| :--- | :--- | :--- |
| **Git** | Читает директории/ветки из Git | Микросервисы в разных папках |
| **List** | Статический список кластеров/окружений | dev, staging, prod |
| **Cluster** | Все подключенные кластеры | Multi-cluster развертывание |
| **Matrix** | Комбинация двух генераторов | Git + Cluster |
| **SCM Provider** | Динамическое создание из GitLab/GitHub API | Feature-ветки |

Подробнее: **[Синхронизация и политики](./synchronization.md)**.

## Специфичные Sync Options для Helm

В Argo CD существуют параметры, критичные для стабильного деплоя чартов:

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| **SkipDryRunOnMissingResource=true** | Позволяет игнорировать ошибки `dry-run`, если чарт создает CRD и ресурсы на их основе в одной транзакции. Критично для первого деплоя Operators. | false |
| **ServerSideApply=true** | Рекомендуется для чартов с огромными манифестами (например, Prometheus Operator) для обхода лимита аннотаций (256 KB). | false |
| **CreateNamespace=true** | Автоматическое создание целевого Namespace, если он отсутствует. | false |
| **Prune=true** | Удаление ресурсов в кластере, которых больше нет в Git. | false |
| **SelfHeal=true** | Автоматический откат ручных правок в кластере к состоянию в Git. | false |
| **RespectIgnoreDifferences=true** | Использование настроек `ignoreDifferences` не только для визуализации, но и при синхронизации. | false |
| **Replace=true** | Использование `kubectl replace` вместо `apply` (для ресурсов с неизменяемыми полями). | false |

**Пример использования:**
```yaml
spec:
  syncPolicy:
    syncOptions:
    - CreateNamespace=true
    - Prune=true
    - SelfHeal=true
    - ServerSideApply=true
    - SkipDryRunOnMissingResource=true
    - RespectIgnoreDifferences=true
```

**Взаимодействие параметров:**
- `SelfHeal=true` + `RespectIgnoreDifferences=true` — SelfHeal не перезаписывает поля из `ignoreDifferences`.
- `SkipDryRunOnMissingResource=true` + CRD Operators — позволяет.deployать CRD и ресурсы одновременно.
- `ServerSideApply=true` + большой чарт — обходит лимит аннотации `last-applied-configuration`.

## Практические сценарии

### Сценарий 1: Интеграция с Vault через AVP

Использование **Argo CD Vault Plugin** позволяет на лету подставлять секреты в Helm-шаблоны без их хранения в Git.

```yaml
spec:
  sources:
    - repoURL: 'https://charts.bitnami.com/bitnami'
      chart: 'redis'
      targetRevision: 16.8.9
      helm:
        valueFiles:
          - $values/apps/redis/values.yaml
    - repoURL: 'https://github.com/my-org/gitops-config.git'
      targetRevision: HEAD
      ref: values
      plugin:
        name: argocd-vault-plugin
```

Подробнее: **[Интеграция с Vault](./argocd_vault_integration.md)**.

### Сценарий 2: Локальные зависимости чартов

Argo CD умеет автоматически запускать `helm dependency build`, если в репозитории обнаружен `Chart.lock`. Это позволяет использовать `file://` зависимости для локальных сабчартов.

```bash
# Структура репозитория
my-app/
├── Chart.yaml
├── Chart.lock
├── charts/
│   └── common-lib-0.1.0.tgz  # Локальный сабчарт
├── templates/
│   └── deployment.yaml
└── values.yaml
```

**Важно:** Argo CD автоматически обнаружит `Chart.lock` и выполнит `helm dependency build` перед рендерингом.

### Сценарий 3: Multi-environment с Values-Overlay

Использование разных values-файлов для dev, staging и prod окружений.

```yaml
# Application для dev
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app-dev
spec:
  sources:
    - repoURL: 'https://charts.bitnami.com/bitnami'
      chart: 'redis'
      targetRevision: 16.8.9
    - repoURL: 'https://github.com/my-org/gitops-config.git'
      targetRevision: main
      ref: values
      helm:
        valueFiles:
          - $values/environments/dev/values.yaml
  destination:
    server: https://kubernetes-dev.example.com
    namespace: development
```

### Сценарий 4: Откат через Argo CD

Поскольку Argo CD не создает Helm-релизы, откат выполняется через Argo CD Rollback:

```bash
# Просмотр истории синхронизаций
argocd app history my-app

# Откат к предыдущей версии
argocd app rollback my-app

# Откат к конкретному коммиту
argocd app rollback my-app <commit-hash>
```

### Сценарий 5: Тестирование чарта перед деплоем

Валидация чарта перед применением в кластере:

```bash
# Локальный рендеринг
helm template my-app ./charts/my-app -f values/prod.yaml > rendered.yaml

# Валидация схемы
helm lint ./charts/my-app -f values/prod.yaml

# Dry-run в кластере (без реального применения)
helm template my-app ./charts/my-app -f values/prod.yaml | kubectl apply --dry-run=client -f -

# Проверка через Argo CD
argocd app diff my-app --local ./charts/my-app
```

## Валидация

### 1. Проверка доступности Helm-репозитория
```bash
# Список настроенных репозиториев в Argo CD
argocd repo list
# → REPO URL                          TYPE     CONNECTION STATUS
# → https://charts.bitnami.com/bitnami  helm     Successful

# Тест подключения к конкретному репозиторию
argocd repo get https://charts.bitnami.com/bitnami
# → Name:  bitnami
# → Type:  helm
# → URL:   https://charts.bitnami.com/bitnami
# → Connection Status: Successful
```

### 2. Валидация чарта перед деплоем
```bash
# Локальный рендеринг с выводом в файл
helm template my-app ./charts/my-app -f values/prod.yaml > rendered.yaml
# → (создает rendered.yaml с манифестами)

# Валидация синтаксиса и лучших практик
helm lint ./charts/my-app -f values/prod.yaml
# → ==> Linting ./charts/my-app
# → [INFO] Chart.yaml: icon is recommended
# → 1 chart(s) linted, 0 chart(s) failed

# Dry-run в кластере (client-side, без применения)
helm template my-app ./charts/my-app -f values/prod.yaml | kubectl apply --dry-run=client -f -
# → deployment.apps/my-app created (dry-run)
# → service/my-app created (dry-run)

# Валидация через Argo CD (сравнение с текущим состоянием)
argocd app diff my-app --local ./charts/my-app
# → No differences found  (или показывает diff)
```

### 3. Проверка рендеринга через Argo CD (server-side)
```bash
# Просмотр сгенерированных манифестов без применения
argocd app manifest my-app > generated.yaml
# → (YAML манифесты, которые будут применены)

# Проверка через server-side dry-run (v3.5+)
argocd app diff my-app --server-side-dry-run
# → проверяет с учетом мутирующих вебхуков
```

### 4. Проверка Multiple Sources конфигурации
```bash
# Проверка разрешения $values ссылок
argocd app get my-app -o yaml | grep -A 20 "sources:"
# → sources:
# → - repoURL: https://charts.bitnami.com/bitnami
# →   chart: redis
# →   targetRevision: 16.8.9
# →   helm:
# →     valueFiles:
# →     - $values/infra/redis/values-prod.yaml
# → - repoURL: https://github.com/my-org/gitops-config.git
# →   targetRevision: HEAD
# →   ref: values
```

### 5. Проверка OCI-реестра
```bash
# Проверка секрета репозитория
kubectl get secret oci-registry-creds -n argocd -o yaml
# → apiVersion: v1
# → data:
# →   password: <base64>
# →   type: b2Np
# →   url: Z2hjci5pby9hcmdvcHJvai9jaGFydHM=
# →   username: <base64>

# Тест пулла чарта из OCI (локально)
helm pull oci://ghcr.io/argoproj/charts/argo-cd --version 5.50.0
# → Pulled: ghcr.io/argoproj/charts/argo-cd:5.50.0
# → Digest: sha256:...
```

### 6. Проверка ApplicationSet генерации
```bash
# Просмотр сгенерированных Application
argocd appset get helm-apps -o tree
# → helm-apps
# → ├── my-app-1 (Synced)
# → ├── my-app-2 (OutOfSync)
# → └── my-app-3 (Synced)

# Детальная информация о генераторе
argocd appset get helm-apps -o yaml | grep -A 30 "generators:"
```

### 7. Валидация Sync Options
```bash
# Проверка эффективных sync options приложения
argocd app get my-app -o yaml | grep -A 20 "syncOptions:"
# → syncOptions:
# → - CreateNamespace=true
# → - Prune=true
# → - SelfHeal=true
# → - ServerSideApply=true
# → - SkipDryRunOnMissingResource=true
```

## Диагностика и мониторинг

### Пошаговый алгоритм диагностики при ошибке синхронизации Helm

```text
1. argocd app get <app-name>
   ├── Status: OutOfSync/Degraded? → Перейдите к шагу 2
   ├── Status: Synced? → Проблема не в синхронизации (проверьте health)
   └── Status: Unknown? → Проблема с контроллером / repo-server

2. argocd app diff <app-name>
   ├── Diff показывает изменения? → Перейдите к шагу 3
   ├── Ошибка "Helm template failed"? → Проблема рендеринга (шаг 4)
   ├── Ошибка "values not found"? → Проблема путей values (шаг 5)
   └── Ошибка "CRD not found"? → Добавьте SkipDryRunOnMissingResource=true

3. kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -f
   ├── Ошибка в логах repo-server? → Анализ ошибки рендеринга
   ├── Ошибка "chart not found"? → Проверьте repoURL/targetRevision
   ├── Ошибка "dependency build failed"? → Проверьте Chart.lock и доступность
   └── Ошибка OCI pull? → Проверьте секрет repository credentials

4. Локальная проверка чарта:
   helm template <release> <chart> -f <values...>
   ├── Успех? → Проблема в окружении Argo CD (кэш, версия Helm)
   └── Ошибка? → Исправьте чарт/values локально

5. Проверка путей values (Multiple Sources):
   argocd app get <app-name> -o yaml | grep -A 10 "valueFiles:"
   ├── Пути начинаются с $values/? → Проверьте ref источника
   ├── Файлы существуют в Git? → git ls-remote / проверка в UI
   └── Регистр пути совпадает? → Case-sensitive!

6. argocd app history <app-name>
   ├── Есть успешные синхронизации? → Сравните с последней удачной
   └── Нет? → Первая синхронизация — проверьте CRD, namespace, RBAC
```

### Базовые команды диагностики

```bash
# Просмотр состояния приложения
argocd app get my-app

# Просмотр diff
argocd app diff my-app

# Просмотр diff с server-side (v3.5+, учитывает мутирующие вебхуки)
argocd app diff my-app --server-side-diff

# Просмотр сгенерированных манифестов
argocd app manifest my-app

# Просмотр истории синхронизаций
argocd app history my-app

# Просмотр логов контроллера приложений
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f

# Просмотр логов repo-server (рендеринг Helm, sourceHydrator)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -f

# Просмотр логов sourceHydrator (v3.4+)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -f | grep -i sourcehydrator

# Просмотр событий в namespace argocd
kubectl get events -n argocd --sort-by='.lastTimestamp'

# Проверка кэша repo-server (очистка через перезапуск)
kubectl rollout restart deployment argocd-repo-server -n argocd
```

### Расширенная таблица ошибок

| Ошибка / Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Helm template failed` | Ошибка в синтаксисе шаблонов Helm / невалидные values | `helm template .` локально; логи repo-server | Исправьте шаблоны/values; проверьте `values.schema.json` |
| `values.yaml not found` / `stat /tmp/values/...: no such file` | Неверный путь в `valueFiles` или неверный `ref` | `argocd app get -o yaml \| grep valueFiles` | Исправьте путь; проверьте `ref` имя; case-sensitive |
| `CRD not found` / `dry-run failed` | Чарт создает CRD и ресурсы одновременно | `argocd app diff` показывает ошибку на CRD | Добавьте `SkipDryRunOnMissingResource=true` в syncOptions |
| `OCI login failed` / `unauthorized` | Ошибка аутентификации в OCI-реестре | `kubectl get secret -n argocd -l argocd.argoproj.io/secret-type=repository` | Исправьте секрет: `url`, `username`, `password`, `type: oci` |
| `Chart dependency build failed` | Ошибка сборки зависимостей (`Chart.lock` невалиден) | Логи repo-server: `helm dependency build` | Исправьте `Chart.yaml`; выполните `helm dependency build` в CI |
| `values.schema.json invalid` | Несоответствие values-файла схеме чарта | `helm lint` или `helm template` покажет ошибку | Приведите values в соответствие со схемой |
| `ApplicationSet generation failed` | Ошибка в шаблоне ApplicationSet (переменные) | `argocd appset get <name> -o yaml` | Проверьте `{{path.basename}}`, генератор, синтаксис шаблона |
| `Server-Side Apply failed` / `field is immutable` | Попытка изменить immutable поле через SSA | `argocd app diff --server-side-diff` | Добавьте `Replace=true` в syncOptions для ресурса |
| `repo-server: chart not found` | Неправильный `repoURL`, `chart` или `targetRevision` | `argocd repo list`; `helm search repo <chart>` | Исправьте параметры source; проверьте доступность репозитория |
| `repo-server: repository not accessible` | Сеть/аутентификация к Helm/OCI репозиторию | `kubectl exec -it repo-server -- wget -qO- <repoURL>` | Настройте credentials; проверьте сетевые политики |
| `Multiple Sources: ref not found` | Источник с `ref: values` не найден или не клонирован | `argocd app get -o yaml \| grep -A 5 "ref: values"` | Добавьте второй источник с правильным `ref` |
| `Cache stale` / `old values rendered` | Застарел кэш repo-server (TTL 5m) | `kubectl rollout restart deployment argocd-repo-server` | Перезапуск repo-server; или подождите TTL |
| `Chart.lock missing` / `dependencies not built` | `Chart.lock` отсутствует в репозитории | Проверьте Git: `ls -la charts/` | Добавьте `Chart.lock` в Git; выполните `helm dependency build` в CI |
| `Target revision not found` | Тег/ветка/коммит не существует в источнике | `git ls-remote <repoURL> <targetRevision>` | Исправьте `targetRevision` на существующий |
| `Hook failed` / `pre-sync hook failed` | Ошибка выполнения Helm hook (Job не завершился) | `kubectl get jobs -n <namespace> -l argocd.argoproj.io/hook` | Исправьте hook; проверьте RBAC для Job; увеличьте timeout |

### Команды для глубокой диагностики

```bash
# 1. Полный дамп состояния приложения
argocd app get my-app -o yaml > app-state.yaml

# 2. Сравнение локального рендеринга с Argo CD
helm template my-app ./charts/my-app -f values/prod.yaml > local.yaml
argocd app manifest my-app > argocd.yaml
diff -u local.yaml argocd.yaml

# 3. Проверка кэша repo-server (очистка через перезапуск)
kubectl rollout restart deployment argocd-repo-server -n argocd

# 4. Логи sourceHydrator для Multiple Sources
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -f | grep -E "sourceHydrator|MultipleSources"

# 5. Проверка OCI pull credentials
kubectl exec -it -n argocd deployment/argocd-repo-server -- \
  oras pull ghcr.io/argoproj/charts/argo-cd:5.50.0 --username $USER --password $TOKEN

# 6. Проверка kubeconform валидации (если настроено)
kubeconform -summary -strict <(argocd app manifest my-app)
```

## Рекомендации и лучшие практики

### Производительность

- **Используйте Server-Side Apply:** Включайте `ServerSideApply=true` для чартов с манифестами >256 KB (обход лимита аннотаций).
- **Кеширование:** Repo-server кеширует результаты рендеринга. Используйте `targetRevision` с фиксированными версиями, а не `latest`.
- **Shallow Git Cloning:** Используйте `--depth` для монорепозиториев (>1000 файлов).

### Безопасность

- **Фиксация версий:** Запрещено использовать `targetRevision: latest`. Всегда фиксируйте Major или Minor версию для предсказуемости.
- **OCI-безопасность:** Используйте короткоживущие токены или IAM-роли для доступа к реестрам образов вместо статических паролей.
- **Сканер секретов:** Включайте `trivy config` и `kubeconform` в CI-пайплайны перед слиянием изменений в GitOps-репозиторий.
- **AppProject:** Всегда создавайте отдельные проекты для разных команд/окружений.

### Надежность

- **Миграция на Helm v4:** В 2026 году рекомендуется полностью отказаться от Helm v3 в пользу v4 из-за встроенной поддержки SSA и улучшенной работы с OCI.
- **Тестирование:** Включайте `helm lint` и `kubeconform` в CI-пайплайны перед слиянием изменений в GitOps-репозиторий.
- **Валидация схемы:** Используйте `values.schema.json` для автоматической проверки values-файлов.
- **Откат:** Используйте `argocd app rollback` вместо `helm rollback`, так как Argo CD не создает Helm-релизы.

## Ограничения и edge cases

### Ограничения

1. **Нет Helm-релизов:** Argo CD не создает записей в Secret `sh.helm.release`. Управление через Helm CLI невозможно.
2. **Лимит аннотаций:** Клиентский Apply ограничивает размер манифестов (256 KB). Для больших чартов используйте Server-Side Apply.
3. **Cross-namespace ресурсы:** Автоматическая синхронизация работает только в рамках одного namespace.
4. **ApplicationSet и `automated`:** Стандартный флаг `syncPolicy.automated` внутри шаблона ApplicationSet игнорируется. Решение о запуске синхронизации принимает контроллер `ApplicationSet`.
5. **Множественные ApplicationSets:** Если ресурс управляется несколькими ApplicationSets, возникает конфликт. Используйте `FailOnSharedResource=true`.

### Edge Cases

1. **CRD и ресурсы в одной транзакции:** Если чарт создает CRD и ресурсы на их основе (Operators: Prometheus, Cert-Manager, Istio), добавьте `SkipDryRunOnMissingResource=true` в `syncOptions`. Без этого dry-run упадет с ошибкой "CRD not found" на ресурсах, зависящих от CRD.

2. **Мутирующие вебхуки:** Если в кластере есть вебхуки, изменяющие манифесты (Istio sidecar injection, Kyverno, OPA Gatekeeper), используйте Server-Side Diff (v3.5+): `argocd app diff <name> --server-side-diff` или аннотация `argocd.argoproj.io/compare-options: ServerSideDiff=true` — модификации мутирующих вебхуков учитываются и удаляются из diff по умолчанию.

3. **Helm-зависимости из приватных источников:** Если чарт зависит от сабчартов в приватных Helm/OCI репозиториях — используйте `helm repo add` с credentials в CI при сборке `Chart.lock`, или Multiple Sources с отдельным секретом `repository` для каждого приватного источника.

4. **OCI-реестры с самоподписанными сертификатами:** Добавьте CA-сертификат в `argocd-cm` через `tls.clientCAData` (base64 PEM) или смонтируйте CA в `repo-server` под. Иначе `oras pull` / `helm registry` упадет с `x509: certificate signed by unknown authority`.

5. **Ручные правки через kubectl:** Argo CD автоматически откатит изменения при включенном `selfHeal=true`. Используйте `RespectIgnoreDifferences=true` для полей, которые можно менять вручную (например, `replicas` в HPA, annotations для внешних инструментов).

6. **Проблемы с зависимостями:** Если `Chart.lock` отсутствует в репозитории, Argo CD **не выполнит** `helm dependency build` автоматически. Убедитесь, что зависимости собраны в CI (`helm dependency build && git add Chart.lock && git commit`).

7. **Откат при Progressive Sync:** Если приложение находится в процессе Progressive Sync (ApplicationSet `syncPolicy.steps`), откат через `argocd app rollback` может нарушить логику поэтапной раскатки. Используйте `argocd appset abort <appset>` для остановки прогрессивного деплоя перед откатом.

8. **Server-Side Apply + `Replace=true` конфликт:** Не используйте `ServerSideApply=true` и `Replace=true` одновременно для одного приложения — они используют разные стратегии применения. `Replace` нужен только для immutable полей (например, `Service.spec.clusterIP`, `PVC.spec`).

9. **Multiple Sources: порядок valueFiles важен:** В `valueFiles` порядок определяет приоритет: последний файл перезаписывает предыдущие. `$values/...` пути разрешаются относительно корня Git-репозитория с `ref: values`.

10. **Case-sensitivity в Multiple Sources:** Пути в `$values/` и имена `ref:` чувствительны к регистру. `ref: Values` не сработает для `$values/...` — должно быть точное совпадение.

11. **TargetRevision в OCI:** В OCI-реестрах `targetRevision` должен быть точным тегом (semver: `5.50.0`) или digest (`sha256:...`). Диапазоны вроде `5.x.x` или `latest` **не поддерживаются** — OCI не имеет понятия "версии" как Helm-репозитории.

12. **Shallow clone и Git history:** Argo CD использует shallow clone (`--depth=1`) по умолчанию. Для `targetRevision` с конкретным коммитом/тегом, которого нет в shallow клоне, синхронизация упадет. Решение: увеличьте `depth` в `argocd-cm` (`repository.credentials.depth`) или используйте теги.

13. **Helm 3 vs 4 в одном кластере:** Argo CD v3.4+ использует встроенный Helm 4 SDK. Если в CI используется Helm 3 для рендеринга — результаты могут отличаться (SSA, OCI, schema validation). Рекомендуется унифицировать версию Helm в CI и Argo CD.

14. **Kustomize поверх Helm (CMP):** При использовании CMP для Kustomize overlay поверх Helm-чарта — порядок: Helm template → Kustomize. `kustomization.yaml` должен ссылаться на `chart/` директорию или сгенерированные манифесты.

15. **FailOnSharedResource в ApplicationSet:** При управлении одним ресурсом несколькими ApplicationSets — включите `FailOnSharedResource=true` в спецификации ApplicationSet, чтобы предотвратить конфликты синхронизации (race condition между контроллерами).

16. **Sync Windows + Helm hooks:** [Sync Windows](./synchronization/scenarios/sync_windows.md) блокируют синхронизацию, но **не блокируют** выполнение Helm hooks (`pre-sync`, `post-sync`). Hooks могут выполниться вне окна синхронизации — учитывайте при планировании.

17. **Resource tracking annotation limit:** При использовании `ServerSideApply=true` аннотация `field.cattle.io/manager` заменяет `last-applied-configuration`, но Argo CD всё равно добавляет `argocd.argoproj.io/sync-options` для отслеживания. При очень больших манифестах (>1MB) возможны проблемы с лимитом etcd (1MB на объект).

## Дополнительная информация

### См. также

- [Обзор Argo CD](./argocd_overview.md)
- [Синхронизация и политики](./synchronization.md)
- [Custom Tooling и плагины (CMP)](./argocd_custom_tooling.md)
- [Официальная документация: Helm Support](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/)
- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — Multiple Sources, sourceHydrator, Helm+Git, CI-рендеринг vs Multi-Source.
- [Отслеживание ресурсов](./argocd_resource_tracking.md) — Методы отслеживания ресурсов: Label, Annotation, Annotation+Label.
- [Удаление и очистка](./argocd_deletion_and_cleanup.md) — Prune, Cascading Deletion, Propagation Policy, Orphan, Finalizers.

### Ссылки на базу знаний Helm

- [Обзор Helm](../../Kubernetes/ToolsUtilities/Helm/helm_overview.md)
- [Структура Helm-чарта](../../Kubernetes/ToolsUtilities/Helm/helm_chart_structure.md)
- [Основные команды и рабочий процесс](../../Kubernetes/ToolsUtilities/Helm/helm_commands_and_workflow.md)
- [Зависимости и библиотечные чарты](../../Kubernetes/ToolsUtilities/Helm/helm_dependencies_and_library_charts.md)
- [Шаблонизация в Helm](../../Kubernetes/ToolsUtilities/Helm/helm_templating.md)
