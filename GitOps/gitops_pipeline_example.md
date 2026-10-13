# GitOps: пример пайплайна

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x), Helm v3.14–v3.16+ / Helm v4.x, Kubernetes 1.28–1.32+ (on-premise / bare-metal), Cosign v2.4+, Trivy 0.5x+

## Определения

**GitOps-пайплайн** — сквозной автоматизированный конвейер поставки программного обеспечения, реализующий декларативный подход к управлению состоянием инфраструктуры и рабочих нагрузок. В этой модели подсистемы строго разделены:
- **CI (Continuous Integration)** отвечает за верификацию исходного кода, запуск тестов, проверку безопасности, сборку и криптографическое подписание неизменяемых артефактов в OCI-реестре.
- **CD (Continuous Delivery)** непрерывно синхронизирует фактическое состояние кластера с декларативным описанием, зафиксированным в Git-репозитории конфигураций, используя Pull-модель реконсиляции без прямого сетевого доступа CI-раннеров к API-серверу Kubernetes.

Ключевые термины:

| Термин | Определение |
| :--- | :--- |
| **Неизменяемый артефакт (Immutable Artifact)** | Контейнерный образ или Helm-чарт, опубликованный в OCI-реестре под уникальным криптографическим дайджестом (`sha256:...`) или семантическим тегом, изменение содержимого которого запрещено политиками реестра. |
| **Репозиторий приложения (Source / App Repo)** | Репозиторий разработчиков, содержащий исходный код сервиса, Dockerfile, локальные Helm-шаблоны и конфигурацию CI-конвейера сборки. |
| **Конфигурационный репозиторий (GitOps / Config Repo)** | Единый источник правды (SSoT) для инфраструктуры и кластерных развертываний, содержащий декларативные манифесты, оверлеи сред (staging, prod), values-файлы и объекты Argo CD `Application`. |
| **Продвижение (Promotion)** | Процесс контролируемого переноса проверенного артефакта между средами (Dev → Staging → Production) путем фиксации новой версии в GitOps-репозитории через Pull Request или автоматизированный контроллер. |
| **Pull-модель доставки** | Архитектурный подход, при котором агент внутри кластера (Argo CD) самостоятельно считывает конфигурацию из Git и реестров, исключая необходимость хранения административных `kubeconfig` в CI-системах. |
| **Server-Side Apply (SSA)** | Нативный механизм Kubernetes API (`fieldManager`), управляющий отдельными полями манифестов на стороне API-сервера, что предотвращает конфликты с мутирующими контроллерами и обходит лимит аннотации `last-applied-configuration` (256 KB). |
| **Multiple Sources** | Механизм Argo CD (`spec.sources`), позволяющий объединять в рамках одного `Application` параметризованный OCI Helm-чарт и внешний Git-репозиторий с файлами значений (`values-prod.yaml`) с адресацией через `$ref`. |
| **Keyless-подписание (Identity-based Signing)** | Метод криптографического подписания артефактов через утилиту Cosign и протокол Sigstore/OIDC, при котором короткоживущие сертификаты выпускаются на основе удостоверения CI-раннера без постоянного хранения закрытых ключей. |

## Основные концепции и архитектура

### Разделение зон ответственности и сетевая безопасность

В корпоративной on-premise архитектуре пайплайн базируется на строгой изоляции контуров:

1. **Контур CI (Зона разработки и сборки):**
   - Выполняет компиляцию, линтинг, статический анализ безопасности (SAST, сканирование секретов), запуск тестов.
   - Собирает контейнерный образ и упаковывает Helm-чарт.
   - Сканирует артефакты на уязвимости и подписывает их через Cosign.
   - Публикует артефакты в корпоративный OCI-реестр (Harbor / GHCR).
   - **Сетевое ограничение:** CI-раннеры не имеют сетевой связности с Kubernetes Control Plane и не содержат учетных записей `kubeconfig`. При компрометации раннера злоумышленник не получает доступ к production-кластеру.

2. **Контур CD (Кластерный контур доставки):**
   - Контроллер Argo CD развернут внутри доверенного периметра кластера Kubernetes.
   - Агент опрашивает Git-репозиторий конфигураций и OCI-реестр либо получает входящие Webhook-события.
   - Контроллер выполняет непрерывный цикл реконсиляции (Reconciliation Loop), вычисляя разницу (`diff`) между желаемым состоянием из Git и живым состоянием кластера (`etcd`).
   - При обнаружении дрейфа (Drift) или ручных вмешательств через `kubectl` контроллер принудительно возвращает состояние кластера к эталону (`selfHeal: true`).

```text
┌────────────────────────────────────────────────────────────────────────┐
│                          CI Контур (Сборка)                            │
│                                                                        │
│  ┌──────────────┐     Push/PR      ┌─────────────────────────────┐     │
│  │  App Repo    │ ───────────────► │ CI Runner (GitHub Actions / │     │
│  │ (код, Docker,│                  │ GitLab Runner On-Premise)   │     │
│  │  Helm-чарт)  │                  │ • Static Checks & Gitleaks  │     │
│  └──────────────┘                  │ • Container Build & Trivy   │     │
│                                    │ • Helm Package & Cosign     │     │
│                                    └──────────────┬──────────────┘     │
└───────────────────────────────────────────────────┼────────────────────┘
                                                    │
                                     Publish Images │ Publish Charts
                                     & Signatures   │ (OCI)
                                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Реестр артефактов (DMZ / OCI)                   │
│                                                                        │
│                      ┌──────────────────────────────┐                  │
│                      │ Harbor / GHCR (OCI Registry) │                  │
│                      │ • app:sha256:... (Signed)    │                  │
│                      │ • charts/app:0.1.0 (OCI)     │                  │
│                      └──────────────┬───────────────┘                  │
└─────────────────────────────────────┼──────────────────────────────────┘
                                      │
              Promotion PR /          │ OCI Pull
              Image Updater           │
                                      ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       CD Контур (Kubernetes Cluster)                   │
│                                                                        │
│  ┌──────────────┐   Webhook/Poll   ┌─────────────────────────────┐     │
│  │ GitOps Repo  │ ───────────────► │ Argo CD (Pull Controller)   │     │
│  │ (оверлеи,    │                  │ • Reconcile & SSA           │     │
│  │  values-prod)│                  │ • Self-Healing & Pruning    │     │
│  └──────────────┘                  └──────────────┬──────────────┘     │
│                                                   │ In-Cluster API     │
│                                                   ▼ Apply              │
│                                    ┌─────────────────────────────┐     │
│                                    │ Production Workloads        │     │
│                                    │ (Pods, Services, Ingress)   │     │
│                                    └─────────────────────────────┘     │
└────────────────────────────────────────────────────────────────────────┘
```

### Стек компонентов и технологий

- **VCS & CI:** GitHub Actions (или on-premise GitLab CI / Gitea Actions) с self-hosted раннерами в изолированной DMZ.
- **Хранилище артефактов:** OCI-совместимый реестр (Harbor v2.10+ или GitHub Packages `ghcr.io`) с поддержкой OCI 1.1 Referrers API.
- **Безопасность Supply Chain:**
  - `gitleaks` — статический анализ утечек секретов в кодовой базе и манифестах.
  - `trivy` — сканирование уязвимостей в зависимостях ОС и библиотек контейнера.
  - `cosign` — цифровая подпись образов и аттестаций (SBOM/SLSA) с последующей проверкой политиками в кластере через [Kyverno](../Security/Supply_Chain_Security/artifact_signing.md).
- **Валидация манифестов:**
  - `kubeconform` — высокоскоростная валидация манифестов по схемам Kubernetes API и CRD-каталогам (см. [Kubeconform](../Kubernetes/ToolsUtilities/kubeconform_overview.md)).
  - `conftest` — верификация манифестов на соответствие корпоративным политикам безопасности (Rego/OPA).
  - `kube-score` — статический анализ надежности и устойчивости спецификаций Pod.
  - `kubectl --dry-run=server` — серверная валидация схем и мутирующих admission-вебхуков.
- **CD-оркестрация:** Argo CD v3.5+ с поддержкой Server-Side Apply и Multiple Sources (см. [Обзор Argo CD](./ArgoCD/argocd_overview.md)).
- **Пакетный менеджмент:** Helm v3.14+ / v4.x с публикацией чартов по протоколу `oci://`.

### Преимущества, ограничения и компромиссы

**Преимущества:**
1. **Аудит и прослеживаемость:** Каждое изменение production-среды зафиксировано в истории коммитов GitOps-репозитория с указанием автора, ревьюера и точного хэша коммита артефакта.
2. **Нулевой доступ CI к кластеру:** Отсутствие необходимости генерировать и обновлять сертификаты или токены доступа к Kubernetes API для CI-агентов.
3. **Воспроизводимость инфраструктуры:** Полное восстановление кластера после катастрофы (Disaster Recovery) сводится к подключению Argo CD к GitOps-репозиторию (см. [Восстановление после аварий](./ArgoCD/argocd_disaster_recovery.md)).
4. **Защита от конфигурационного дрейфа:** Механизм `selfHeal` ликвидирует несанкционированные ручные правки в реальном времени.

**Ограничения и компромиссы:**
1. **Задержка доставки (Delivery Latency):** Стандартный цикл опроса источников в Argo CD составляет 3 минуты (`timeout.reconciliation: 180s`). Для мгновенного применения требуется настройка Webhook от Git-сервера и OCI-реестра в `argocd-server`.
2. **Управление секретами:** Открытые секреты запрещено хранить в Git. Требуется внедрение [шифрования секретов](./secrets_encryption.md) (SOPS / Sealed Secrets) либо интеграция с HashiCorp Vault / OpenBao через [Argo CD Vault Plugin](./ArgoCD/argocd_vault_integration.md).
3. **Дисциплина развертывания:** Откат через `kubectl rollout undo` блокируется контроллером Argo CD. Инженеры обязаны производить любые манипуляции исключительно через `git revert`.

## Практические сценарии

### Предварительные требования и подготовка среды

| Компонент | Минимальная версия | Назначение | Проверка готовности |
| :--- | :--- | :--- | :--- |
| **Kubernetes** | 1.28–1.32+ | On-premise / bare-metal кластер | `kubectl version --short` |
| **Argo CD** | v3.5+ (ветка v3.x) | GitOps CD-контроллер | `argocd version --short` |
| **Helm** | 3.14+ / 4.x | Шаблонизатор и OCI-клиент | `helm version --short` |
| **Cosign** | 2.4+ / 3.x | Подпись образов и верификация | `cosign version` |
| **Trivy** | 0.50+ | Сканер уязвимостей артефактов | `trivy --version` |
| **Gitleaks** | 8.18+ | Детектор секретов в коде | `gitleaks version` |
| **Kubeconform** | 0.6.7+ | Схематическая валидация YAML | `kubeconform -v` |
| **Conftest** | 0.50+ | Проверка Rego-политик | `conftest --version` |

Подготовка структуры репозиториев:
- **Репозиторий приложения (`app-source-repo`):**
  - `src/` — исходный код микросервиса.
  - `Dockerfile` — многоэтапная сборка (Multi-stage build) без привилегий root.
  - `charts/app/` — базовый Helm-чарт (`Chart.yaml`, `values.yaml`, `templates/`).
  - `.github/workflows/` — конвейеры проверок и публикации.
- **Конфигурационный репозиторий (`gitops-config-repo`):**
  - `apps/production-app/values-prod.yaml` — параметры развертывания для продакшена.
  - `apps/production-app/values-staging.yaml` — параметры для тестового контура.
  - `bootstrap/applications/production-app.yaml` — манифест Argo CD `Application`.
  - `policies/` — корпоративные правила Conftest (Rego).

---

### Сквозной поток выполнения (Workflow)

#### Шаг 1: Проверка в Feature-ветке (CI PR-Checks)

При каждом открытии Pull Request или коммите в ветку разработки запускаются быстрые статические проверки, предотвращающие попадание дефектных манифестов и утекших учетных данных в общую ветку:

```yaml
# .github/workflows/pr-checks.yml
name: PR Static Checks

on:
  pull_request:
    branches:
      - main
    paths-ignore:
      - '**.md'
      - 'docs/**'

jobs:
  static-analysis:
    name: Lint, Secrets and Tests
    runs-on: ubuntu-latest
    steps:
      - name: Checkout source code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0 # полная история необходима gitleaks для сканирования всех коммитов PR

      - name: Detect leaked secrets
        run: |
          gitleaks detect --source . --redact --verbose --exit-code 1
          # → при обнаружении утечки: exit 1 с маскированием значения в логах

      - name: Lint Helm Chart
        run: |
          helm lint charts/app --strict
          # → проверка синтаксиса Chart.yaml, шаблонов и значений по умолчанию

      - name: Run unit tests
        run: |
          make test
          # → запуск юнит-тестов приложения с генерацией отчета о покрытии
```

---

#### Шаг 2: Сборка, сканирование и публикация артефактов (CI Main)

После слияния Pull Request в ветку `main` конвейер собирает контейнерный образ, сканирует его на уязвимости, подписывает через Cosign и публикует Helm-чарт в OCI-реестр.

```yaml
# .github/workflows/ci-publish.yml
name: Build, Scan, Sign and Publish

on:
  push:
    branches:
      - main
    tags:
      - 'v*.*.*'

permissions:
  contents: read
  packages: write     # запись образов и чартов в OCI-реестр
  id-token: write     # критично: генерация OIDC-токена для keyless-подписи Cosign

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build-and-publish:
    name: Build, Scan & OCI Publish
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Prepare build environment
        run: |
          # Приведение имени репозитория к нижнему регистру для соответствия стандарту OCI
          LOWER_IMAGE=$(echo "${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}" | tr '[:upper:]' '[:lower:]')
          echo "IMAGE_LOWER=${LOWER_IMAGE}" >> $GITHUB_ENV
          echo "SHORT_SHA=$(echo '${{ github.sha }}' | cut -c1-7)" >> $GITHUB_ENV

      - name: Login to OCI Registry (Docker)
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build container image
        run: |
          docker build \
            --file Dockerfile \
            --tag ${{ env.IMAGE_LOWER }}:${{ github.sha }} \
            --tag ${{ env.IMAGE_LOWER }}:${{ env.SHORT_SHA }} .

      - name: Scan vulnerability with Trivy
        run: |
          # Блокировка сборки только при наличии критических уязвимостей, имеющих исправление
          trivy image \
            --severity CRITICAL,HIGH \
            --ignore-unfixed \
            --exit-code 1 \
            ${{ env.IMAGE_LOWER }}:${{ github.sha }}
          # → при наличии исправляемых CVE CRITICAL/HIGH пайплайн завершается аварийно

      - name: Push image to OCI Registry
        run: |
          docker push ${{ env.IMAGE_LOWER }}:${{ github.sha }}
          docker push ${{ env.IMAGE_LOWER }}:${{ env.SHORT_SHA }}

      - name: Install Cosign CLI
        uses: sigstore/cosign-installer@v3.8.1

      - name: Sign image (Keyless via GitHub OIDC)
        run: |
          # Keyless-подпись привязывается к метаданным запуска workflow
          cosign sign --yes ${{ env.IMAGE_LOWER }}:${{ github.sha }}
          # → подпись загружается в OCI-реестр через Referrers API

      - name: Package and Push Helm Chart to OCI
        run: |
          # Генерация уникальной версии чарта для предотвращения 409 Conflict в реестре
          CHART_VERSION="0.1.0-${{ github.run_number }}"
          sed -i "s/^version:.*/version: ${CHART_VERSION}/" charts/app/Chart.yaml
          sed -i "s/^appVersion:.*/appVersion: \"${{ github.sha }}\"/" charts/app/Chart.yaml
          
          helm package charts/app --destination dist/
          
          # Аутентификация Helm в OCI-реестре
          echo "${{ secrets.GITHUB_TOKEN }}" | helm registry login ${{ env.REGISTRY }} -u ${{ github.actor }} --password-stdin
          
          helm push dist/app-${CHART_VERSION}.tgz oci://${{ env.REGISTRY }}/${{ github.repository_owner }}/charts
          # → result: Pushed: ghcr.io/org/charts/app:0.1.0-XX
```

> **Важные архитектурные нюансы порядка выполнения:**
> 1. **Сканирование предшествует публикации:** Уязвимый образ не должен попадать в реестр, чтобы исключить риск его выкатки в тестовые или продуктовые контуры.
> 2. **Подпись выполняется строго после `docker push`:** Утилита Cosign связывает подпись с удаленным манифестом образа в реестре. Локальный образ подписать невозможно.
> 3. **Требование `id-token: write`:** Для выпуска эфемерного сертификата Fulcio пайплайн обязан обладать правами на генерацию OIDC JWT-токена.
> 4. **Иммутабельность версий чарта:** В производственных OCI-реестрах (Harbor) включена политика `Tag Immutability`. Публикация с фиксированной версией `0.1.0` при повторном запуске приведет к ошибке `409 Conflict`. Версия обязана содержать номер сборки или семантический тег.

---

#### Шаг 3: Валидация и гейты качества GitOps-репозитория

Pull Request в конфигурационный GitOps-репозиторий — критический барьер безопасности перед применением изменений в кластере. Конвейер выполняет эшелонированную проверку манифестов:

```yaml
# .github/workflows/config-validate.yml
name: GitOps Quality Gates

on:
  pull_request:
    branches:
      - main
    paths:
      - 'apps/**'
      - 'policies/**'

jobs:
  manifest-validation:
    name: Lint, Schemas, Policies & Dry-Run
    runs-on: ubuntu-latest
    steps:
      - name: Checkout GitOps repository
        uses: actions/checkout@v4

      - name: Check for unencrypted secrets
        run: |
          gitleaks detect --source . --no-git --redact --verbose
          # → проверяет, что в PR не добавлены приватные ключи, токены или plain-text секреты

      - name: Render environment manifests
        run: |
          mkdir -p build/
          # Рендеринг манифестов через kustomize или helm template
          kustomize build apps/production-app/overlays/prod > build/rendered-prod.yaml
          kustomize build apps/production-app/overlays/staging > build/rendered-staging.yaml

      - name: Validate Kubernetes API schemas (Kubeconform)
        run: |
          kubeconform -strict -summary \
            -kubernetes-version 1.31.0 \
            -schema-location default \
            -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{ .ResourceKind }}_{{ .Group }}_{{ .Version }}.json' \
            build/rendered-prod.yaml build/rendered-staging.yaml
          # → проверка соответствия спецификациям K8s API v1.31 и CRD-каталогу

      - name: Platform policy verification (Conftest / Rego)
        run: |
          conftest test --policy policies/ build/rendered-prod.yaml
          # Проверяемые правила:
          # 1. Запрет использования плавающих тегов (:latest)
          # 2. Обязательное указание resources.limits и resources.requests
          # 3. Запрет запуска от root (runAsNonRoot: true)
          # 4. Обязательное наличие livenessProbe и readinessProbe

      - name: Static reliability score (kube-score)
        run: |
          kube-score score build/rendered-prod.yaml --ignore-container-cpu-limit

      - name: Server-Side Dry-Run on Live API
        run: |
          kubectl apply --dry-run=server --server-side -f build/rendered-prod.yaml
        env:
          KUBECONFIG: /tmp/readonly-kubeconfig # учетная запись CI с правами dry-run в namespace prod
```

> **Обоснование Server-Side Dry-Run:**
> Статические анализаторы (`kubeconform`, `kube-score`) оперируют только схемами. Они не могут обнаружить конфликты с динамическими контроллерами в кластере: валидирующими и мутирующими вебхуками (ValidatingAdmissionWebhook / MutatingAdmissionWebhook), лимитами ResourceQuota, политиками Pod Security Standards и коллизиями Server-Side Apply. `kubectl apply --dry-run=server` отправляет манифест через полный конвейер admission кластера без фиксации объекта в `etcd`.

---

#### Шаг 4: Развертывание и сверка состояния (CD, Argo CD)

В корпоративной практике Helm-чарт хранится в OCI-реестре, а специфичные для окружения параметры (`values-prod.yaml`) — в GitOps-репозитории. Объект Argo CD `Application` реализует паттерн **Multiple Sources**:

```yaml
# bootstrap/applications/production-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: production-app
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io # каскадная очистка ресурсов кластера при удалении App
spec:
  project: default
  # Паттерн Multiple Sources (доступен с Argo CD v2.6+, полностью стабилизирован в v3.x)
  sources:
    # 1. Первичный источник: параметризованный чарт из OCI-реестра
    - repoURL: ghcr.io/org/charts
      chart: app
      targetRevision: 0.1.0-42 # закрепленная версия чарта (точка продвижения)
      helm:
        valueFiles:
          - $values/apps/production-app/values-prod.yaml
    # 2. Вторичный источник: конфигурационный GitOps-репозиторий
    - repoURL: https://github.com/org/gitops-config.git
      targetRevision: main
      ref: values # псевдоним источника, используемый в ссылке $values
  destination:
    server: https://kubernetes.default.svc
    namespace: prod
  syncPolicy:
    automated:
      prune: true          # удалять объекты, удаленные из манифестов
      selfHeal: true       # подавлять ручные правки в кластере
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true # включает SSA (полевой менеджер argocd)
      - PruneLast=true       # удаление ресурсов после создания новых для предотвращения downtime
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

Параметры и риски конфигурации синхронизации:

| Параметр | Назначение | Риск при некорректной настройке |
| :--- | :--- | :--- |
| `targetRevision` | Фиксированная версия чарта / SHA коммита GitOps-репозитория | Ошибочный тег замораживает доставку обновлений |
| `automated.prune` | Удаление объектов из кластера при их исчезновении из манифестов | Ошибочный коммит с удалением директории приведет к каскадному удалению рабочих нагрузок |
| `automated.selfHeal` | Автоматический откат несанкционированных ручных правок (`kubectl edit`) | Конфликтует с HPA, мутирующим `spec.replicas`. Требуется настройка `ignoreDifferences` |
| `ServerSideApply` | Управление полями через `fieldManager` Kubernetes API | При выключенном SSA манифесты размером >256 KB завершаются ошибкой аннотации `last-applied` |
| `PruneLast` | Удаление устаревших объектов только после успешного развертывания новых | Без этого параметра Service или Secret могут быть удалены до старта нового Pod |

---

#### Шаг 5: Проверка работоспособности и верификация в кластере

Инженерные команды валидируют состояние пайплайна и доставленных артефактов следующими командами:

```bash
# 1. Принудительный запрос актуального статуса приложения в Argo CD
argocd app get production-app --refresh
# → Name:               production-app
# → Project:            default
# → Server:             https://kubernetes.default.svc
# → Namespace:          prod
# → URL:                https://argocd.corp.internal/applications/production-app
# → Sync Status:        Synced to 0.1.0-42 (b3f8a1c)
# → Health Status:      Healthy

# 2. Проверка запущенного образа и его точного digest в кластере
kubectl get deployment production-app -n prod \
  -o jsonpath='{.spec.template.spec.containers[0].image}' && echo
# → ghcr.io/org/app:b3f8a1c0d4e5f6...

# 3. Верификация цифровой подписи развернутого образа через Cosign
cosign verify ghcr.io/org/app:b3f8a1c0d4e5f6... \
  --certificate-identity-regexp '^https://github\.com/org/app-source-repo/\.github/workflows/ci-publish\.yml@refs/heads/main$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
# → Verification for ghcr.io/org/app:b3f8a1c0d4e5f6... --
# → The following checks were performed on each of these signatures:
# →   - The cosign claims were validated
# →   - The code signing cert was verified in accordance with Fulcio/Rekor
# → Certificate subject: https://github.com/org/app-source-repo/...
# → Verified OK

# 4. Просмотр истории синхронизаций и ревизий
argocd app history production-app
# → ID  DATE                           REVISION
# → 1   2026-10-12 10:15:30 +0300 MSK  0.1.0-41 (a1b2c3d)
# → 2   2026-10-13 14:22:10 +0300 MSK  0.1.0-42 (b3f8a1c)
```

---

#### Шаг 6: Откат изменений (Rollback)

В GitOps-парадигме единственным корректным методом отката является операция над Git-репозиторием:

```bash
# 1. Создание revert-коммита в конфигурационном GitOps-репозитории
git revert HEAD --no-edit
git push origin main
# → result: [main 9f8e7d6] Revert "Promote app to 0.1.0-42"

# 2. Проверка расчета diff в Argo CD перед применением
argocd app diff production-app
# → ===== Deployment/prod/production-app ======
# → 13c13
# → <   image: ghcr.io/org/app:0.1.0-42
# → ---
# → >   image: ghcr.io/org/app:0.1.0-41
```

> **Предостережение об антипаттерне `argocd app rollback`:**
> Выполнение команды `argocd app rollback` в CLI или через веб-интерфейс при включенной автосинхронизации (`automated.selfHeal: true`) бесполезно. Контроллер зафиксирует несоответствие состояния кластера текущему коммиту ветки Git и в следующем цикле реконсиляции немедленно применит сбойную версию обратно. Откат через API допустим исключительно при предварительном отключении автосинхронизации (`argocd app set production-app --sync-policy none`) как экстренная мера с обязательным последующим `git revert`.

---

### Продвижение между окружениями (Promotion)

Продвижение артефакта из тестового контура в продуктовый осуществляется обновлением ссылки на версию чарта или дайджеста образа в файлах конфигурационного репозитория.

#### Вариант А: Эталонный ручной PR-поток (Audit & Compliance)

Разработчик или релиз-инженер создает Pull Request в GitOps-репозиторий:

```diff
# GitOps-репозиторий: bootstrap/applications/production-app.yaml
 spec:
   sources:
     - repoURL: ghcr.io/org/charts
       chart: app
-      targetRevision: 0.1.0-41
+      targetRevision: 0.1.0-42
```

Преимущества:
- Прохождение автоматизированных гейтов качества (Quality Gates).
- Обязательное ревью изменений вторым инженером (Four-Eyes Principle).
- Полная аудируемость и интеграция с Change Management.

#### Вариант Б: Автоматизированное продвижение

| Инструмент | Архитектурный механизм | Область применения |
| :--- | :--- | :--- |
| **[Argo CD Image Updater](./ArgoCD/argocd_image_updater.md)** | Контроллер опрашивает OCI-реестр по заданным семантическим правилам и обновляет параметры `Application` через API Argo CD (запись коммита в Git опциональна). | Dev / QA среды с непрерывным развертыванием свежих сборок. |
| **[Kargo](./Concepts/kargo_promotion_pipelines.md)** | Декларативные CRD `Warehouse`, `Freight` и `Stage`. Фиксирует проверенный кортеж артефактов (образ + чарт + коммит) и проводит его через цепочки сред с валидационными тестами и гейтами одобрения. | Enterprise-конвейеры со строгими требованиями регуляторов и многоступенчатыми средами. |
| **[Renovate](./Concepts/renovate_dependency_updates.md)** | Сканирует реестры и автоматически формирует Pull Request'ы с bump'ом версий чартов и дайджестов образов в GitOps-репозитории. | Автоматизация обновления внешних и внутренних базовых зависимостей с прохождением PR-гейтов. |

---

## Операции и команды

Операционный Runbook для системных администраторов и инженеров SRE по обслуживанию и диагностике конвейера доставки:

```bash
# 1. Принудительная инвалидация локального кэша repo-server и реконсиляция
argocd app get production-app --hard-refresh
# → result: app cache invalidated, manifest regenerated from OCI/Git

# 2. Ручной запуск процесса синхронизации с принудительной очисткой (Prune)
argocd app sync production-app --prune --force
# → TIMESTAMP                  GROUP        KIND   NAMESPACE                  NAME    STATUS   HEALTH        HOOK  MESSAGE
# → 2026-10-13T14:30:00+03:00  apps   Deployment        prod        production-app    Synced  Healthy              deployment.apps/production-app configured

# 3. Диагностика входящих Webhook-запросов в логах контроллера
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server --tail=100 | grep -i webhook
# → time="2026-10-13T14:30:01Z" level=info msg="Received push event repo: https://github.com/org/gitops-config"
# → time="2026-10-13T14:30:02Z" level=info msg="Triggered refresh for 1 apps affected by repo: https://github.com/org/gitops-config"

# 4. Проверка состояния локального OCI-артефакта в реестре (Skopeo)
skopeo inspect docker://ghcr.io/org/app:0.1.0-42
# → {
# →     "Name": "ghcr.io/org/app",
# →     "Digest": "sha256:7c9e1b2f...",
# →     "RepoTags": ["0.1.0-42", "b3f8a1c"]
# → }

# 5. Проверка манифестов чарта напрямую из OCI-реестра
helm show chart oci://ghcr.io/org/charts/app --version 0.1.0-42
# → apiVersion: v2
# → name: app
# → version: 0.1.0-42
# → appVersion: "b3f8a1c0d4e5f6"

# 6. Временная блокировка автоматической синхронизации при аварийных работах
argocd app set production-app --sync-policy none
# → result: auto-sync disabled for 'production-app'

# 7. Возврат штатного режима автосинхронизации с self-heal
argocd app set production-app --sync-policy automated --auto-prune --self-heal
# → result: auto-sync enabled for 'production-app'
```

---

## Типовые проблемы и их решение

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `denied: permission_denied` / `403 Forbidden` при `docker push` в GHCR | В GitHub Actions отсутствует блок `permissions: packages: write` либо истек токен доступа. | Проверить права workflow и результат шага `docker/login-action`. | Добавить `permissions: { packages: write }` в файл workflow. Для on-premise Harbor проверить права Robot Account. |
| `cosign sign` завершается с ошибкой `no OIDC token available` | В workflow отсутствует разрешение `permissions: id-token: write`, необходимое для получения JWT от OIDC-провайдера. | Лог шага подписи: `error generating token: no id-token permission`. | Добавить `permissions: id-token: write` на уровне job или всего workflow. |
| `cosign sign` возвращает `GET ... MANIFEST_UNKNOWN` | Шаг подписи запущен до выполнения `docker push` — образ отсутствует в реестре. | Проверить порядок шагов в CI-пайплайне. | Обеспечить строгое следование конвейеру: `build → scan → push → sign`. |
| `helm push` завершается с ошибкой `409 Conflict: tag already exists` | В OCI-реестре включена политика иммутабельности тегов (`Tag Immutability`), а чарт пушится с повторяющейся версией. | Лог шага публикации Helm: `status 409 Conflict`. | Внедрить динамическое формирование версии чарта: `0.1.0-${{ github.run_number }}`. |
| Argo CD возвращает ошибкой `values-prod.yaml: no such file or directory` при OCI-чарте | В одиночном источнике (`spec.source`) указан OCI-чарт, но файл values ищется локально в архиве чарта, а не в Git. | `argocd app get production-app` возвращает ошибку рендеринга манифеста. | Перевести приложение на паттерн `spec.sources` (Multiple Sources) с монтированием GitOps-репозитория через `$values`. |
| Изменения закоммичены в GitOps-репозиторий, но Argo CD не видит их 3 минуты | Не настроен входящий Webhook от Git-сервиса к `argocd-server`, контроллер работает по fallback-таймауту опроса. | Проверить настройки сетевого экрана между Git-сервером и Argo CD. | Настроить отправку Webhook на endpoint `https://<argocd-server>/api/webhook` с секретом `webhook.github.secret` в `argocd-secret`. |
| Приложение циклически переходит в статус `OutOfSync` по полю `spec.replicas` | Горизонтальный автоскейлер (HPA) изменяет количество реплик, а `selfHeal` принудительно возвращает значение из Git. | `argocd app diff production-app` показывает расхождение только по полю `replicas`. | Добавить секцию `ignoreDifferences` для поля `.spec.replicas` в манифесте `Application`. |
| Серверный dry-run или Argo CD sync падает с ошибкой Admission Webhook | Kyverno или Gatekeeper блокирует развертывание из-за отсутствия подписи или нарушения Pod Security Standards. | `kubectl describe pod` или логи вебхука: `admission webhook denied: image signature verification failed`. | Проверить соответствие identity подписи правилам кластерной политики; устранить запуск от root или отсутствие securityContext. |
| `kubeconform` падает с ошибкой `could not find schema for CRD` | Схематический валидатор не имеет доступа к определениям пользовательских ресурсов (Argo CD, Kyverno, Prometheus). | Лог Kubeconform: `could not find schema for Application`. | Добавить параметр `-schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{ .ResourceKind }}_{{ .Group }}_{{ .Version }}.json'`. |
| `prune` удалил рабочие ресурсы из кластера | В Git случайно закоммичено удаление директории манифестов или переименован файл namespace. | `kubectl get events -n prod` показывает события удаления от имени контроллера `argocd-application-controller`. | Немедленно выполнить `git revert` в GitOps-репозитории; настроить sync window и требование ревью для продуктовых оверлеев. |

---

## Рекомендации и лучшие практики

1. **Принцип наименьших привилегий (Least Privilege RBAC):**
   - CI-раннерам полностью закрывается доступ к Kubernetes API.
   - Для публикации артефактов используются автоматически генерируемые короткоживущие токены (`GITHUB_TOKEN` или робот-аккаунты Harbor с правами на запись только в конкретный проект).
   - Внутри кластера сервисной учетной записи `argocd-application-controller` предоставляются ограниченные права в целевых namespace через [AppProject RBAC](./ArgoCD/argocd_appproject_deep.md).

2. **Digest-Pinning в продуктовых манифестах:**
   - Для критических сред фиксируйте образ по его криптографическому дайджесту (`image: ghcr.io/org/app@sha256:...`). Это гарантирует побайтовую неизменность проверенного в CI образа и защищает от атак подмены тегов в реестре.

3. **Изоляция репозиториев (App Repo vs Config Repo):**
   - Разделяйте репозиторий приложения и GitOps-репозиторий конфигураций. Это разграничивает зоны ответственности: разработчики имеют права на слияние в репозиторий кода, но изменения в GitOps-репозиторий требуют обязательного аппрува от инженеров платформы и SRE.

4. **In-Cluster валидация подписей и политик безопасности:**
   - Наличие цифровой подписи бесполезно без ее проверки перед запуском. Разверните в кластере Kyverno или Gatekeeper с политиками `verifyImages`, блокирующими запуск контейнеров без валидной подписи доверенного CI-конвейера (см. [Управление политиками](./Concepts/gitops-policy-management.md)).

5. **SRE-наблюдаемость и DORA-метрики:**
   - Настройте сбор метрик Argo CD в Prometheus:
     - `argocd_app_sync_total{phase="Succeeded"}` — отслеживание частоты развертываний (Deployment Frequency).
     - `argocd_app_sync_total{phase=~"Failed|Error"}` — частота сбоев изменений (Change Failure Rate).
     - `argocd_app_health_status{status="Degraded"}` — алерт на деградацию здоровья продуктовых приложений.
   - Подробнее о расчете метрик: [DORA метрики в GitOps](./Concepts/dora_metrics_gitops.md).

### Очистка окружения

Команды демонтажа тестового стенда для очистки ресурсов кластера и реестра:

```bash
# 1. Каскадное удаление приложения из-под управления Argo CD
# (флаг --cascade гарантирует удаление всех управляемых Deployment, Service, ConfigMap)
argocd app delete production-app --cascade --yes
# → application 'production-app' deleted

# 2. Проверка освобождения пространства имен в кластере
kubectl get all -n prod
# → No resources found in prod namespace.

# 3. Удаление опубликованных образов и чартов из реестра
# Для Harbor: вызов API удаления артефакта через curl/клиент
# Для GHCR: удаление версии пакета через Web UI (Packages -> app -> Delete version)

# 4. Отзыв временных сервисных учетных записей и Kubeconfig
rm -f /tmp/readonly-kubeconfig
```

---

## Дополнительная информация

**Связанные документы:**
- [Обзор методологии GitOps](./GitOps_overview.md) — фундаментальные принципы, модели Push/Pull и архитектурные паттерны.
- [Обзор Argo CD](./ArgoCD/argocd_overview.md) — архитектура компонентов CD-контроллера.
- [Multiple Sources в Argo CD](./ArgoCD/argocd_multi_source_apps.md) — детальная архитектура разделения OCI Helm-чартов и Git-репозиториев.
- [Синхронизация в Argo CD](./ArgoCD/synchronization.md) — стратегии Server-Side Apply, Sync Waves и управление хуками.
- [Жизненный цикл образов и OCI-хранилищ](./Concepts/containerization_and_image_storage.md) — стандарты OCI 1.1, тегирование и ретенция в Harbor.
- [Подпись артефактов и Cosign](../Security/Supply_Chain_Security/artifact_signing.md) — криптографическая безопасность цепочки поставок (Supply Chain Security).
- [Валидация манифестов через Kubeconform](../Kubernetes/ToolsUtilities/kubeconform_overview.md) — интеграция схематического анализа в CI/CD.
- [Управление политиками GitOps](./Concepts/gitops-policy-management.md) — runtime-контроль манифестов через Kyverno и Gatekeeper.
- [Уведомления в GitOps](./gitops_notifications.md) — настройка оповещений об инцидентах доставки в Telegram/Slack/Email.
- [DORA метрики в GitOps](./Concepts/dora_metrics_gitops.md) — мониторинг надежности и скорости поставки.

---

## Вопросы для собеседования

### Почему деплой из CI-пайплайна (`kubectl apply` после сборки) не считается полноценным GitOps?
Прямой деплой из CI реализует классическую Push-модель доставки. В ней отсутствует агент реконсиляции внутри кластера, нет непрерывного отслеживания и устранения дрейфа (Drift Detection / Self-Healing), а административный `kubeconfig` с правами на запись скомпрометирован хранением в переменных окружения CI. GitOps требует, чтобы кластер сам вытягивал конфигурацию (Pull Model), Git являлся единственным источником правды, а CI не имел доступа к K8s API.

### Что хранится в репозитории приложения (App Repo), а что в конфигурационном (GitOps Repo)?
В App Repo хранятся: исходный код, Dockerfile, локальные шаблоны Helm, юнит-тесты и CI-пайплайны сборки. В GitOps Repo хранятся: целевые оверлеи окружений (dev, staging, prod), зафиксированные версии артефактов (дайджесты образов, версии чартов), конфигурации инфраструктурных манифестов (Ingress, NetworkPolicy, SealedSecrets) и манифесты Argo CD `Application`. Такое разделение разграничивает циклы релизов и разграничивает права доступа (RBAC).

### Зачем в PR-гейтах необходим именно server-side dry-run, а не только проверка через Kubeconform?
Kubeconform проверяет соответствие статической JSON-схеме Kubernetes API. Он не может обнаружить динамические кластерные ограничения: срабатывание мутирующих и валидирующих вебхуков (ValidatingAdmissionWebhook), исчерпание квот ресурсов (ResourceQuota), несоответствие правилам безопасности Pod Security Standards (PSA) и конфликты владения полями Server-Side Apply (SSA). `kubectl apply --dry-run=server` прогоняет манифест через реальный API-сервер без сохранения в `etcd`.

### Почему команда `argocd app rollback` считается антипаттерном при включенной автосинхронизации?
При включенной автосинхронизации (`automated.selfHeal: true`) контроллер непрерывно сверяет кластер с коммитом ветки Git. Команда `argocd app rollback` временно откатывает ресурсы в кластере, создавая расхождение с Git. В следующем цикле реконсиляции Argo CD обнаружит дрейф и принудительно восстановит версию из Git, нивелировав откат. Корректный откат в GitOps — это создание `git revert` в конфигурационном репозитории.

### Как решается разделение Helm-чарта и значений окружений при использовании OCI-реестра в Argo CD?
Используется механизм Multiple Sources (`spec.sources`). Первый источник ссылается на OCI-реестр с версией Helm-чарта (`repoURL: ghcr.io/org/charts`, `chart: app`), а второй источник ссылается на GitOps-репозиторий с назначением псевдонима (`ref: values`). В секции первичного источника файл значений монтируется через переменную `$values/path/to/values-prod.yaml`. Это исключает антипаттерн запекания продуктовых values внутрь публичного чарта.
