# GitOps: Образы контейнеров и их жизненный цикл

**Актуально для:** OCI Image/Distribution Spec 1.1, Docker 27.x/28.x, Harbor 2.12+/2.15.x, Kargo v1.11.x, Flux v2.4.x, Argo CD Image Updater v1.0.x, Cosign v2.4+/v3.x

В GitOps образ контейнера является ключевым неизменяемым артефактом, связывающим процессы непрерывной интеграции (CI) и непрерывной доставки (CD). Правильное управление образами — основа предсказуемости, прослеживаемости и отказоустойчивости инфраструктуры: именно криптографический digest образа становится той единственной детерминированной переменной, которой достаточно для описания желаемого состояния приложения в кластере.

## Определения

- **Образ контейнера (Container Image)**: Неизменяемый (immutable) пакет, включающий приложение, системные библиотеки и конфигурацию среды исполнения. В GitOps-конвейере образ является неделимой полезной нагрузкой (payload), доставляемой в кластер на основе коммитов в Git.
- **Тег (Tag)**: Человекочитаемая ссылка (`v1.2.3`, `latest`), указывающая на конкретный манифест образа. В отличие от digest тег является мутабельным (может быть перезаписан), поэтому в GitOps он служит лишь первичным указателем при публикации, но не гарантией неизменности.
- **Дайджест (Digest)**: Уникальный неизменяемый SHA256-хеш содержимого манифеста или индекса образа (`image@sha256:...`). Использование дайджестов гарантирует побайтовую идентичность развернутого кода на всех узлах кластера.
- **OCI (Open Container Initiative) Артефакты**: Стандарт упаковки и распространения, позволяющий хранить в реестрах не только образы ОС, но и Helm-чарты, манифесты Kustomize, спецификации SBOM и криптографические подписи.
- **OCI 1.1 Referrers API**: Механизм спецификации OCI Distribution, связывающий зависимые артефакты (подписи, результаты сканирования, аттестации) с целевым образом через граф зависимостей без изменения дайджеста самого образа.
- **Реестр образов (Image Registry)**: Централизованный сервис хранения и распределения артефактов (например, Harbor, GitLab Container Registry, Forgejo/Gitea). Выполняет роль единого центра дистрибуции OCI-артефактов.
- **Proxy Cache (Pull-through кэш)**: Режим работы локального реестра, кэширующий внешние публичные образы для ускорения загрузки на узлы, экономии WAN-трафика и защиты от сбоев внешних сетей и rate limits.
- **Мульти-архитектурный образ (Multi-arch Image / OCI Image Index)**: Объединение манифестов для различных аппаратных платформ (`linux/amd64`, `linux/arm64`) под единым именем и тегом через индекс манифестов.
- **SBOM (Software Bill of Materials)**: Формализованный машиночитаемый перечень компонентов и библиотек образа (форматы SPDX, CycloneDX).
- **Подпись (Signature) и Аттестация (Attestation)**: Криптографическое подтверждение целостности и происхождения образа (инструменты Cosign, Notation) и метаданные сборки (SLSA Provenance), хранящиеся рядом с артефактом.
- **Image Pull Policy (`IfNotPresent`, `Always`, `Never`)**: Директива kubelet, определяющая необходимость сетевого запроса в реестр при создании контейнера.
- **Image Garbage Collection (Kubelet Image GC)**: Автоматическая очистка неиспользуемых слоев образов демоном kubelet на диске рабочего узла при достижении порогов заполнения файловой системы.
- **Dangling Blobs (Несвязанные блобы)**: Слои данных в хранилище реестра, оставшиеся после удаления тегов манифестов и требующие физической очистки через Garbage Collection (GC).

## Архитектура и базовые концепции

### Разделение ответственности CI и CD

GitOps устанавливает строгую границу между созданием артефакта и его развертыванием:

- **CI (Build & Push)**: Пайплайн компилирует код, собирает мульти-архитектурный образ, генерирует SBOM, сканирует уязвимости, подписывает артефакт и публикует его в OCI-реестр. Результат CI — **новый неизменяемый артефакт с зафиксированным digest**.
- **CD (Pull & Reconcile)**: GitOps-контроллер (Argo CD, Flux) обнаруживает изменение манифеста в Git (или регистрирует новый образ через автоматизацию) и приводит рантайм кластера в соответствие. Результат CD — **актуальное состояние рабочих нагрузок в кластере**.

Главный принцип: **CD никогда не пересобирает артефакт**. Продвижение между средами (Dev → Staging → Production) — это перенос одного и того же хеша digest. Повторная сборка из того же коммита недопустима: она не гарантирует побайтовую идентичность из-за плавающих временных меток слоев и обновления базовых пакетов в репозиториях ОС.

### Жизненный цикл образа в GitOps

```text
Code Commit
    │
    ▼
[CI Pipeline] ──► Multi-arch Build (Docker Buildx / Rootless BuildKit)
    │
    ├──► Уязвимости: Trivy/Grype (FAIL при CRITICAL)
    ├──► SBOM: Syft (CycloneDX / SPDX)
    ├──► Sign & Attest: Cosign (SLSA Provenance via Referrers)
    │
    ▼
[OCI Registry (Harbor)] ──► Фиксация уникального sha256 Digest
    │
    ▼
[Promotion Engine (Kargo)] ──► Создание Freight (Digest + Helm/Git commit)
    │                             │
    │                             ▼
    ├──► Stage: Staging ────► Verification Tests (AnalysisRun / Smoke Tests)
    │                             │
    └──► Stage: Production ◄──────┘ (После успешного гейта / Approval)
          │
          ▼
    [Git Repository] ──► Запись закрепленного digest в манифест values.yaml
          │
          ▼
    [GitOps Agent] ────► Argo CD / Flux выполняет синхронизацию
          │
          ▼
    [Node Kubelet] ────► Containerd проверяет подпись (Kyverno) и пуллит digest
```

Каждый этап жизненного цикла сопровождается жесткими контрольными гейтами:
1. **Гейт сборки**: блокировка отправки в реестр при обнаружении критических CVE без патчей.
2. **Гейт криптографии**: подпись артефакта и прикрепление provenance до публикации в staging.
3. **Гейт продвижения**: переход артефакта на следующий этап только после прохождения тестов на предыдущем без изменения digest.
4. **Гейт допуска (Admission Control)**: проверка подписи с помощью [политик безопасности](./gitops-policy-management.md) (Kyverno) на уровне API-сервера Kubernetes перед созданием пода.

### OCI 1.1 Referrers API и граф связанных артефактов

В спецификации OCI 1.1 артефакты организуются в направленный граф. Дополнительные метаданные связываются с базовым образом через поле `subject` в манифесте:

```text
               ┌───► Manifest: Image (linux/amd64)
               │
Image Index ───┼───► Manifest: Image (linux/arm64)
   ▲           │
   │           └───► Manifest: Image (linux/riscv64)
   │
   ├── [Subject] ─── Manifest: Cosign Signature (application/vnd.dev.cosign.simplesigning.v1+json)
   ├── [Subject] ─── Manifest: CycloneDX SBOM (application/vnd.cyclonedx+json)
   └── [Subject] ─── Manifest: SLSA Provenance Attestation (application/vnd.in-toto+json)
```

**Преимущества для Sysadmin и DevOps:**
- Подписи и SBOM не требуют создания искусственных тегов-пустышек вида `sha256-<hash>.sig`.
- При перемещении или репликации образа инструменты (`skopeo copy --all`, Harbor Replication) автоматически копируют весь граф связанных объектов.
- Admission Controllers и сканеры безопасности обращаются к `v2/<name>/referrers/<digest>` напрямую, не опрашивая списки тегов.

### Структура слоев, базовые образы и скорость раскатки

Слоистая модель хранения OCI непосредственно определяет задержку развертывания (Rollout Latency) в Kubernetes:
- **Базовые слои (Base Layers)**: Использование унифицированных базовых образов (Distroless, Alpine, минимальный Debian) внутри компании позволяет узлам кластера кэшировать общие слои для сотен сервисов.
- **Оптимизация Dockerfile**: Инструкции упорядочиваются от редко меняющихся к часто меняющимся. Зависимости языка (`go.mod`, `pom.xml`, `package.json`) кэшируются до добавления исходного кода.
- **Минимизация накладных расходов**: Применение Multi-stage сборок и Distroless-образов исключает компиляторы, утилиты отладки и пакетные менеджеры, уменьшая размер образа с сотен мегабайт до десятков, что сокращает время `ImagePull` и разгружает дисковую подсистему узла.

### Топология локальных реестров и High Availability (On-prem)

В изолированных дата-центрах и bare-metal инсталляциях реестр образов является критической точкой отказа (SPOF):
1. **Высокая доступность (HA)**: Развертывание [Harbor в режиме HA](../../Docker/Docker_registries/Harbor/installation.md) с внешним PostgreSQL кластером (Patroni), реплицируемым Redis (Sentinel/Cluster) и распределенным объектным хранилищем (S3-совместимый MinIO или Ceph RGW) с многократной репликацией данных.
2. **Proxy Cache (Pull-through кэш)**: Для филиалов и изолированных сегментов сети настраиваются локальные проекты Harbor в режиме Proxy Cache. Запросы к внешним ресурсам кэшируются локально, предотвращая блокировки пайплайнов из-за сетевых сбоев WAN.
3. **P2P-дистрибуция (P2P Preheat)**: При кластерах с сотнями рабочих узлов одномоментный pull нового образа может перегрузить сетевой стек реестра. Интеграция с [Dragonfly P2P](../../Docker/Docker_registries/Harbor/p2p_preheat.md) распределяет слои между самими рабочими нодами по одноранговой сети.

### Взаимодействие Kubelet, Containerd и хранилища образов

При запуске пода рабочий узел выполняет строгую последовательность действий:

```text
Pod Scheduled ──► Kubelet (SyncPod)
                      │
                      ▼
               CRI: PullImage Request ──► Containerd
                                              │
                                              ├── Проверка локального кэша (/var/lib/containerd)
                                              ├── Обращение к mirrors/hosts.toml
                                              ├── Аутентификация (Secret / hosts.toml)
                                              ├── Скачивание недостающих слоев (Content Store)
                                              └── Распаковка в Snapshotter (overlayfs)
```

#### Поведение ImagePullPolicy в GitOps:
- `IfNotPresent`: Kubelet проверяет локальное наличие образа. Если образ указан по **тегу** (`app:v1.2.0`) и уже есть на ноде, kubelet **не обращается в сеть**. Если тег был перезаписан в реестре, нода продолжит крутить старый код. Если указан **digest** (`app@sha256:...`), гарантия соблюдается абсолютно: если digest совпадает, локальный образ идентичен требуемому.
- `Always`: При каждом создании контейнера kubelet опрашивает реестр. Для тегов это запрашивает манифест из сети (нагружая реестр и замедляя старт пода). Для digest сетевой запрос подтверждает неизменность хеша без перекачивания слоев.
- `Never`: Контейнер запускается исключительно из предзагруженного на ноду образа (используется для системных компонентов и air-gapped окружений с жестким pre-pull).

#### Kubelet Image Garbage Collection и DiskPressure:
Kubelet непрерывно отслеживает заполнение файловой системы, где хранятся образы (по умолчанию точка монтирования `/var/lib/containerd`):
- `imageGCHighThresholdPercent` (по умолчанию `80%`): Процент занятого диска, при котором kubelet инициирует немедленный сбор мусора неиспользуемых образов.
- `imageGCLowThresholdPercent` (по умолчанию `70%`): Целевой процент, до которого kubelet удаляет неиспользуемые слои (от самых старых по времени последнего использования к новым).
- `imageMinimumGCAge` (по умолчанию `2m`): Минимальное время жизни образа на узле, до истечения которого он защищен от сборки мусора.

Если очистка образов не успевает освободить место и диск заполняется до порогов эвикшна (`imagefs.available<15%` или `nodefs.available<10%`), узел переходит в состояние `DiskPressure`, перестает принимать новые поды и начинает принудительно выселять существующие. Подробный разбор сценариев приведен в [руководстве по диагностике дискового пространства](../../Kubernetes/Troubleshooting/Common_Errors/PodEvicted/disk_eviction.md).

### Управление аутентификацией: Secret против containerd `hosts.toml`

Для доступа к защищенным реестрам в Kubernetes применяются два подхода:
1. **Namespace-scoped (`imagePullSecrets`)**: Создание секрета типа `kubernetes.io/dockerconfigjson` в каждом пространстве имен и привязка к ServiceAccount или Pod spec. Минус для SRE: необходимость дублирования и синхронизации секретов между десятками namespace.
2. **Cluster-wide (Node-level via containerd `hosts.toml`)**: Настройка аутентификации и корневых сертификатов CA напрямую на рабочих узлах в конфигурации containerd. Все поды кластера получают доступ к внутреннему реестру без необходимости объявления `imagePullSecrets` в прикладных манифестах.

## Практические сценарии

### Сценарий 1: Мульти-архитектурная сборка и инспекция OCI-индексов

**Проблема**: В инфраструктуре используются bare-metal узлы разных архитектур (`amd64` и `arm64`). Необходимо собирать единый артефакт, гарантируя корректное выполнение на любой архитектуре.

**Предварительные требования**: `docker buildx` с драйвером `docker-container`, эмулятор QEMU для компиляции под другую архитектуру (или распределенные нативные раннеры), утилита `crane`.

**Настройка и сборка**:
1. Инициализируйте rootless builder с поддержкой кросс-компиляции:
   ```bash
   docker buildx create --name enterprise-builder --driver docker-container --use
   # → enterprise-builder
   docker buildx inspect --bootstrap
   # → Name: enterprise-builder, Driver: docker-container, Status: running, Platforms: linux/amd64, linux/arm64
   ```

2. Выполните сборку и публикацию мультиплатформенного индекса:
   ```bash
   docker buildx build \
     --platform linux/amd64,linux/arm64 \
     --tag harbor.internal/core/auth-service:2.4.1 \
     --provenance=mode=max \
     --push .
   # → exporting to image
   # → pushing manifest for harbor.internal/core/auth-service:2.4.1
   ```

3. Проверьте манифест OCI Image Index через `crane`:
   ```bash
   crane manifest harbor.internal/core/auth-service:2.4.1 | jq .
   # → result:
   # {
   #   "schemaVersion": 2,
   #   "mediaType": "application/vnd.oci.image.index.v1+json",
   #   "manifests": [
   #     {
   #       "mediaType": "application/vnd.oci.image.manifest.v1+json",
   #       "digest": "sha256:7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069",
   #       "platform": { "architecture": "amd64", "os": "linux" }
   #     },
   #     {
   #       "mediaType": "application/vnd.oci.image.manifest.v1+json",
   #       "digest": "sha256:4d61736f6e20697320677265617420656e67696e656572212121212121212121",
   #       "platform": { "architecture": "arm64", "os": "linux" }
   #     }
   #   ]
   # }
   ```

### Сценарий 2: Многоэтапный промоушен артефактов через Kargo

**Проблема**: Необходимо обеспечить безопасный переход образов между средами Staging и Production с фиксацией digest и прохождением верификационных тестов, исключив ручные правки манифестов.

**Реализация**: Kargo отслеживает новые версии в реестре через ресурс `Warehouse`, формирует неизменяемый `Freight` и передает его по стадиям `Stage`. Детальная архитектура Kargo описана в [Kargo: promotion-пайплайны](./kargo_promotion_pipelines.md).

```yaml
apiVersion: kargo.akuity.io/v1alpha1
kind: Warehouse
metadata:
  name: auth-service-warehouse
  namespace: kargo-apps
spec:
  subscriptions:
    - image:
        repoURL: harbor.internal/core/auth-service
        semverConstraint: ^2.4.0
        discoveryLimit: 5
---
apiVersion: kargo.akuity.io/v1alpha1
kind: Stage
metadata:
  name: staging
  namespace: kargo-apps
spec:
  requestedFreight:
    - origin: { kind: Warehouse, name: auth-service-warehouse }
      sources: { direct: true }
  promotionMechanisms:
    gitRepoUpdates:
      - repoURL: https://git.internal/gitops/infra.git
        readCounterpart: { branch: main }
        writeCounterpart: { branch: main }
        helm:
          images:
            - valueKey: image.digest
              value: ${{ imageFrom(warehouse("auth-service-warehouse")).Digest }}
---
apiVersion: kargo.akuity.io/v1alpha1
kind: Stage
metadata:
  name: prod
  namespace: kargo-apps
spec:
  requestedFreight:
    - origin: { kind: Warehouse, name: auth-service-warehouse }
      sources: { stages: [staging] }
  verification:
    analysisTemplates:
      - name: smoke-test-gate
  promotionMechanisms:
    gitRepoUpdates:
      - repoURL: https://git.internal/gitops/infra.git
        readCounterpart: { branch: main }
        writeCounterpart: { branch: main }
        helm:
          images:
            - valueKey: production.image.digest
              value: ${{ imageFrom(warehouse("auth-service-warehouse")).Digest }}
```

**Проверка состояния в CLI**:
```bash
kargo get freight --project kargo-apps
# → NAME         ALIAS         ORIGIN                   AGE
# → 5a4b3c2d     auth-2.4.1    auth-service-warehouse   12m

kargo get stages --project kargo-apps
# → NAME      CURRENT FREIGHT   HEALTHY   PHASE
# → staging   auth-2.4.1        True      Ready
# → prod      auth-2.4.0        True      Ready
```

### Сценарий 3: Декларативная автоматизация обновления образов в GitOps

Для автоматического обновления тегов и дайджестов в Git-репозиториях применяются контроллеры автоматизации.

#### Вариант А: Flux Image Update Automation (Native Digest Pinning)
Flux считывает реестр, выбирает версию по политике и фиксирует изменение в Git с записью полного `sha256 digest`:

```yaml
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImageRepository
metadata:
  name: auth-service
  namespace: flux-system
spec:
  image: harbor.internal/core/auth-service
  interval: 5m
  secretRef:
    name: harbor-registry-credentials
---
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImagePolicy
metadata:
  name: auth-service-policy
  namespace: flux-system
spec:
  imageRepositoryRef:
    name: auth-service
  policy:
    semver:
      range: 2.x.x
---
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImageUpdateAutomation
metadata:
  name: auth-service-automation
  namespace: flux-system
spec:
  interval: 10m
  sourceRef:
    kind: GitRepository
    name: flux-system
  git:
    checkout:
      ref:
        branch: main
    commit:
      author:
        email: fluxbot@internal
        name: Flux Image Automator
      messageTemplate: "chore(deps): update auth-service to {{ .Selected.Tag }} digest {{ .Selected.Digest }}"
    push:
      branch: main
  update:
    path: ./clusters/production/apps
    strategy: Setters
```

В файле манифеста приложения добавляется маркер-сеттер:
```yaml
# clusters/production/apps/deployment.yaml
spec:
  template:
    spec:
      containers:
        - name: app
          image: harbor.internal/core/auth-service:2.4.1@sha256:7f83b1657ff1... # {"$imagepolicy": "flux-system:auth-service-policy"}
```

#### Вариант Б: Argo CD Image Updater (CRD-режим v1.0+)
Современная версия Image Updater использует манифесты `ImageUpdater` вместо аннотаций:

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: core-services-updater
  namespace: argocd
spec:
  applicationRefs:
    - labelSelector:
        matchLabels:
          environment: staging
      images:
        - alias: auth
          imageName: harbor.internal/core/auth-service
          updateStrategy: semver
          commonUpdateSettings:
            writeBackConfig:
              method: git
              target: environments/staging/values.yaml
              branch: main
```

**Проверка выполнения обновления**:
```bash
flux reconcile image repository auth-service -n flux-system
# → ✔ reconciliation finished in 1.45s, found 18 tags
kubectl get imagepolicy auth-service-policy -n flux-system
# → NAME                  LATEST IMAGE                                     READY
# → auth-service-policy   harbor.internal/core/auth-service:2.4.1@sha256:7f83b1...   True
```

### Сценарий 4: Air-gapped зеркалирование и Proxy Cache в изолированном контуре

**Проблема**: Изолированный промышленный кластер не имеет прямого доступа в Интернет. Требуется доставить базовые образы и Helm-чарты с проверкой целостности.

1. **Копирование артефакта через `skopeo`**:
   Утилита `skopeo` переносит образы напрямую между реестрами без запуска локального Docker-демона:
   ```bash
   # Синхронизация мульти-архитектурного индекса со всеми слоями и подписями
   skopeo copy --all \
     --src-creds "$EXTERNAL_USER:$EXTERNAL_PASS" \
     --dest-creds "$HARBOR_USER:$HARBOR_PASS" \
     docker://registry.opensource.org/library/redis:7.2.5 \
     docker://harbor.internal/cache/redis:7.2.5
   # → Getting image source signatures
   # → Copying blob sha256:a1b2c3...
   # → Copying config sha256:d4e5f6...
   # → Writing manifest to image destination
   # → Storing list signatures
   ```

2. **Настройка Proxy Cache в Harbor**:
   В веб-интерфейсе Harbor создается проект `dockerhub-proxy` с типом **Proxy Cache**, указывающий на upstream-реестр. Образы запрашиваются через локальный адрес:
   `harbor.internal/dockerhub-proxy/library/nginx:1.27`.
   Первый запрос скачивает и сохраняет слои локально; все последующие запросы от сотен узлов обслуживаются из локального NVMe-хранилища Harbor без расхода внешнего канала.

3. **Конфигурация зеркала на рабочих узлах (containerd `hosts.toml`)**:
   Для перенаправления запросов к внешним реестрам на внутренний кэш без изменения манифестов настройте containerd на каждом узле:
   ```toml
   # /etc/containerd/certs.d/docker.io/hosts.toml
   server = "https://registry-1.docker.io"

   [host."https://harbor.internal/v2/dockerhub-proxy"]
     capabilities = ["pull", "resolve"]
     ca = ["/etc/ssl/certs/harbor-internal-ca.crt"]
     [host."https://harbor.internal/v2/dockerhub-proxy".header]
       Authorization = ["Basic dXNlcjpwYXNzd29yZA=="]
   ```

4. Примените конфигурацию без перезагрузки containerd (containerd перечитывает директорию `certs.d` динамически при каждом pull):
   ```bash
   crictl pull docker.io/library/nginx:1.27
   # → Image is up to date for docker.io/library/nginx:1.27
   ```

Подробное руководство по отладке сетевых изоляций представлено в [Air-gapped ошибки Image Pull](../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md).

### Сценарий 5: Полный защищенный CI/CD-конвейер: сборка, сканирование, SBOM и подпись

Production-ready конвейер сборки на базе GitLab CI с использованием локального HashiCorp Vault для хранения ключей подписи (без внешних облачных зависимостей):

```bash
#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="harbor.internal/core/auth-service"
TAG="${CI_COMMIT_SHORT_SHA}"
IMAGE_URI="${IMAGE_NAME}:${TAG}"

echo "=== 1. Multi-arch сборка ==="
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag "$IMAGE_URI" \
  --provenance=mode=max \
  --push .
# → result: образ собран и опубликован в Harbor

echo "=== 2. Сканирование безопасности (Trivy) ==="
trivy image \
  --exit-code 1 \
  --severity CRITICAL \
  --ignore-unfixed \
  "$IMAGE_URI"
# → result: CRITICAL vulnerabilities: 0. Exit code 0.

echo "=== 3. Генерация SBOM (Syft) и аттестация OCI 1.1 ==="
syft "$IMAGE_URI" -o cyclonedx-json=auth-sbom.json
cosign attest \
  --key "hashivault://cosign-signer" \
  --type cyclonedx \
  --predicate auth-sbom.json \
  --yes \
  "$IMAGE_URI"
# → result: Attestation uploaded for harbor.internal/core/auth-service@sha256:...

echo "=== 4. Криптографическая подпись образа ==="
cosign sign \
  --key "hashivault://cosign-signer" \
  --yes \
  "$IMAGE_URI"
# → result: Signature uploaded for harbor.internal/core/auth-service@sha256:...

echo "=== 5. Получение закрепленного Digest для GitOps ==="
IMAGE_DIGEST=$(crane digest "$IMAGE_URI")
echo "PINNED_IMAGE=${IMAGE_NAME}@${IMAGE_DIGEST}" > build.env
# → result: PINNED_IMAGE записан для последующего шага коммита в GitOps-репозиторий
```

### Сценарий 6: Управление жизненным циклом: политики ретенции и безопасный Garbage Collection в Harbor

**Проблема**: Неконтролируемый рост реестра из-за сборок feature-веток переполняет дисковые массивы. Удаление записей в UI освобождает только метаданные, но не физическое дисковое пространство.

**Архитектура очистки в Harbor**:
1. **Удаление манифестов (Soft Delete)**: Удаление тега через UI или API удаляет связь в базе данных PostgreSQL. Сами слои (blobs) остаются на диске, чтобы не сломать другие образы, использующие эти же слои.
2. **Garbage Collection (Физическая очистка)**: Job Service сканирует реестр, находит блобы, на которые не ссылается ни один манифест, и удаляет их из хранилища.

**Скрипт автоматизированной ротации старых PR-образов через Harbor API v2**:
```bash
#!/usr/bin/env bash
set -euo pipefail

HARBOR_URL="https://harbor.internal"
PROJECT="core"
REPO="auth-service"
AUTH="admin:${HARBOR_ADMIN_PASSWORD}"

# Получить список артефактов с тегами вида 'pr-*' старше 14 дней
curl -s -u "$AUTH" \
  "${HARBOR_URL}/api/v2.0/projects/${PROJECT}/repositories/${REPO}/artifacts?page_size=100" \
  | jq -r '.[] | select(.tags != null) |
           select(.tags[].name | test("^pr-")) |
           select((.push_time | fromdateiso8601) < (now - 1209600)) |
           .digest' \
  | while read -r DIGEST; do
      echo "Удаление устаревшего PR-артефакта: $DIGEST"
      curl -s -X DELETE -u "$AUTH" \
        "${HARBOR_URL}/api/v2.0/projects/${PROJECT}/repositories/${REPO}/artifacts/${DIGEST}"
    done
# → result: HTTP 200 на каждый удаленный манифест
```

**Запуск Garbage Collection без остановки работы**:
В современных версиях Harbor сборщик мусора запускается без перевода реестра в глобальный Read-Only режим (Non-blocking GC):
```bash
curl -s -X POST -u "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"schedule":{"type":"Manual"},"parameters":{"delete_untagged":true,"dry_run":false}}' \
  "${HARBOR_URL}/api/v2.0/system/gc/schedule"
# → result: {"status": "success", "job_id": 4821}
```

*Важное правило для SRE*: Политика хранения (Retention Policy) должна иметь исключения (Immunity Rules) для всех дайджестов, развернутых в Production и Staging кластерах, с запасом по времени не менее SLA на откат (обычно 90 дней).

### Сценарий 7: SRE-мониторинг и наблюдаемость доставки образов

**Метрики рабочего узла (Kubelet Prometheus Metrics)**:
- `kubelet_container_image_pull_duration_seconds_bucket`: Гистограмма времени скачивания образов. Резкий рост 95-го перцентиля сигнализирует о деградации сети, перегрузке дисков реестра или скачивании избыточно больших слоев.
- `kubelet_container_image_pull_errors_total`: Счетчик ошибок пуллинга (таймауты, ошибки авторизации, сбои DNS).
- `container_fs_inodes_free` и `node_filesystem_avail_bytes`: Запас свободного места на файловой системе образов (`/var/lib/containerd`).

**Метрики реестра Harbor**:
- `harbor_project_storage_bytes`: Использование хранилища в разрезе проектов.
- `harbor_task_status_count{type="GC"}`: Статус и длительность выполнения задач сборки мусора.
- `harbor_up`: Доступность ключевых компонентов (core, registry, jobservice, postgresql).

**Prometheus Alerting Rules для кластера**:
```yaml
groups:
  - name: image_delivery_alerts
    rules:
      - alert: KubeletHighImagePullErrors
        expr: rate(kubelet_container_image_pull_errors_total[5m]) > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Высокая частота ошибок загрузки образов на узле {{ $labels.instance }}"
          description: "На узле происходят регулярные сбои ImagePullBackOff/ErrImagePull (> 0.05 ошибок/сек)."

      - alert: KubeletImagePullLatencyHigh
        expr: histogram_quantile(0.95, sum(rate(kubelet_container_image_pull_duration_seconds_bucket[5m])) by (le)) > 120
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "95% задержка загрузки образов превышает 2 минуты"
          description: "Замедление скачивания образов блокирует горизонтальное автоскейлирование (HPA)."

      - alert: HarborProjectStorageQuotaNearLimit
        expr: (harbor_project_storage_bytes / harbor_project_quota_bytes) > 0.85
        for: 30m
        labels:
          severity: critical
        annotations:
          summary: "Квота проекта Harbor {{ $labels.project_name }} исчерпана на 85%"
          description: "При достижении 100% CI/CD-пайплайны будут заблокированы ошибкой Push Quota Exceeded."
```

## Операции и команды

Сводная таблица утилит командной строки для системных администраторов и инженеров DevOps:

| Инструмент | Команда | Назначение |
| :--- | :--- | :--- |
| **skopeo** | `skopeo inspect docker://harbor.internal/core/auth:2.4.1` | Просмотр JSON-манифеста без скачивания слоев |
| **skopeo** | `skopeo copy --all docker://src/app:v1 docker://dst/app:v1` | Межреестровое копирование всех платформ и подписей |
| **skopeo** | `skopeo delete docker://harbor.internal/core/auth:2.4.1` | Удаление тега/манифеста из удаленного реестра |
| **crane** | `crane digest harbor.internal/core/auth:2.4.1` | Быстрое получение точного sha256 digest образа |
| **crane** | `crane manifest harbor.internal/core/auth:2.4.1` | Получение полного манифеста или индекса OCI |
| **crane** | `crane export harbor.internal/core/auth:2.4.1 - \| tar -tvf -` | Просмотр содержимого файловой системы образа без Docker |
| **cosign** | `cosign verify --key cosign.pub harbor.internal/core/auth:2.4.1` | Проверка криптографической подписи образа |
| **cosign** | `cosign verify-attestation --key cosign.pub --type cyclonedx ...` | Проверка аттестации и валидности SBOM |
| **cosign** | `cosign tree harbor.internal/core/auth:2.4.1` | Отображение дерева связанных Referrers (подписи, SBOM) |
| **docker buildx** | `docker buildx imagetools inspect harbor.internal/core/auth:2.4.1` | Инспекция поддерживаемых платформ в индексе |

### Примеры практического выполнения команд:

1. **Получение точного дайджеста для фиксации в GitOps-манифесте**:
   ```bash
   crane digest harbor.internal/core/auth-service:2.4.1
   # → sha256:7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069
   ```

2. **Проверка дерева связанных артефактов OCI 1.1**:
   ```bash
   cosign tree harbor.internal/core/auth-service:2.4.1
   # → 📦 Supply Chain Security Tree
   #   └── 🧾 Manifest: harbor.internal/core/auth-service:2.4.1 (sha256:7f83b165...)
   #       ├── 🔏 Signature: sha256:3a1b2c...
   #       ├── 📋 Attestation (cyclonedx): sha256:9f8e7d...
   #       └── 📋 Attestation (slsaprovenance): sha256:1a2b3c...
   ```

3. **Проверка аутентификации реестра через skopeo**:
   ```bash
   skopeo login harbor.internal --username deploy-bot --password "$DEPLOY_TOKEN"
   # → Login Succeeded!
   ```

## Диагностика и устранение неполадок

| Симптом | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `ImagePullBackOff: manifest unknown` после отката | Зафиксированный тег был перезаписан или удален сборщиком мусора (GC) в реестре | `skopeo inspect docker://harbor.internal/...` возвращает 404 | Переключить манифест на резервный digest; настроить в Harbor политику Retention с окном хранения > SLA отката |
| `exec format error` при старте контейнера на узле | В OCI Image Index отсутствует архитектура процессора узла (например, собран только `amd64`, а узел `arm64`) | `uname -m` на узле показывает `aarch64`; `crane manifest <image>` не содержит секции `arm64` | Собрать образ через `docker buildx build --platform linux/amd64,linux/arm64` и переопубликовать индекс |
| `x509: certificate signed by unknown authority` | Kubelet/containerd не доверяет внутреннему CA self-hosted реестра | `crictl pull <image>` завершается ошибкой TLS handshake | Добавить корневой сертификат в `/etc/containerd/certs.d/<registry>/hosts.toml` или в системный trust store ОС узла |
| `429 Too Many Requests` от внешних публичных реестров | Превышены лимиты на неавторизованные скачивания (Docker Hub rate limits) | Логи kubelet содержат `toomanyrequests: You have reached your unauthenticated limit` | Настроить в Harbor проект Proxy Cache; перенаправить запросы через containerd `hosts.toml` |
| Argo CD показывает статус `OutOfSync` сразу после деплоя | Kustomize/Helm оверлей подменяет digest обратно на тег, либо Image Updater конфликтует с Git | Проверить Git diff между master-веткой и желаемым состоянием приложения | Зафиксировать digest непосредственно в Git-репозитории; исключить поле тега из мутаций через `ignoreDifferences` |
| Kubelet переходит в состояние `DiskPressure`, поды выселяются | Дисковый раздел `/var/lib/containerd` переполнен неиспользуемыми слоями образов | `df -h /var/lib/containerd`; `crictl images` показывает гигабайты устаревших слоев | Проверить пороги Kubelet GC (`imageGCHighThresholdPercent: 80`); вынести `/var/lib/containerd` на отдельный диск |
| Ошибка `push failed: project quota exceeded` в CI | Проект в Harbor исчерпал лимит дискового пространства | `curl /api/v2.0/projects/<id>/summary` показывает заполнение квоты на 100% | Запустить Garbage Collection в Harbor; удалить устаревшие PR-артефакты; увеличить квоту проекта |
| `cosign verify` сообщает `no matching signatures found` | Реестр не поддерживает OCI 1.1 Referrers API, либо подписи не были скопированы при репликации | `crane manifest <image>` не показывает Referrers; подписи отсутствуют в зеркале | При переносе использовать `skopeo copy --all`; обновить Harbor до 2.11+; повторно подписать образ в целевом реестре |
| Медленный запуск подов при масштабировании (HPA) | Отсутствие слоев на узле; большой размер образа (>1 Гб); перегрузка сетевого интерфейса | `kubelet_container_image_pull_duration_seconds` > 60 сек | Оптимизировать Dockerfile (Distroless/Alpine); внедрить Pre-pulling через DaemonSet; включить P2P Preheat в Harbor |

## Лучшие практики

### 1. Архитектурная неизменяемость (Immutable Delivery)
- **Используйте Digest Pinning в Production**: Манифесты в production-окружениях обязаны ссылаться на полный дайджест: `harbor.internal/apps/core:2.4.1@sha256:...`. Тег используется для визуального удобства и поиска, а digest гарантирует идентичность выполнения.
- **Включите Tag Immutability в реестре**: Для production-репозиториев Harbor активируйте правило **Tag Immutability** для semver-тегов (`v*`, `*.*.*`). Это защищает от случайной или злонамеренной перезаписи релизных образов.

### 2. Защита дисковой подсистемы и стабильность узлов
- **Выделенный раздел для Container Storage**: Монтируйте директорию данных рантайма контейнеров (`/var/lib/containerd` или `/var/lib/docker`) на отдельный физический диск или LVM-том. Это гарантирует, что при внезапном переполнении слоев образов системный раздел ОС (`/`) не заблокируется, а операционная система сохранит управляемость.
- **Тюнинг порогов Kubelet Image GC**: Для нод с высокими темпами развертываний настройте пороги kubelet:
  ```yaml
  imageMinimumGCAge: 5m
  imageGCHighThresholdPercent: 75
  imageGCLowThresholdPercent: 65
  ```

### 3. Эффективность сети и изоляция
- **Развертывайте Proxy Cache**: Все запросы к публичным ресурсам должны проходить через локальный кэширующий реестр. Это экономит внешний интернет-канал компании на 80–90% и защищает инфраструктуру от внешних инцидентов.
- **Cluster-wide аутентификация**: Настраивайте доверие к локальным реестрам через `hosts.toml` на уровне образов ОС узлов (Golden Images / Ansible), исключая ручное управление сотнями `imagePullSecrets` в пространствах имен.

### 4. Политики безопасности цепочки поставок (Supply Chain Security)
- **Блокировка на уровне Admission Control**: Настройте политики Kyverno, запрещающие запуск подов:
  1. С плавающим тегом `latest`.
  2. Без явного указания digest (или без валидной криптографической подписи доверенной корпоративной CI).
  3. От пользователей с правами root (UID 0).
- **Автоматическая аттестация**: Каждая сборка обязана сопровождаться генерацией SBOM и provenance-аттестацией в формате SLSA.

### 5. Предварительный прогрев критичных образов (Pre-pulling)
- Для приложений, масштабируемых через Horizontal Pod Autoscaler (HPA), скачивание слоев размером в сотни мегабайт во время всплеска нагрузки приводит к недопустимым задержкам. Используйте легковесный DaemonSet, периодически выполняющий `imagePull` базовых слоев на все узлы кластера.

## Дополнительная информация

Смежные разделы базы знаний:
- **[Версионирование и тегирование Docker-образов](../../Docker/Docker_registries/image_versioning_and_tagging.md)** — SemVer, CalVer и стратегии иммутабельности.
- **[Подписание и верификация Docker-образов](../../Docker/Docker_security/image_signature_and_verification.md)** — глубокое погружение в Cosign, Notation и Admission Controller.
- **[Управление артефактами в CI/CD](../../CI-CD/artifact_management.md)** — организация жизненного цикла артефактов.
- **[Kargo: promotion-пайплайны](./kargo_promotion_pipelines.md)** — управление этапами продвижения артефактов.
- **[Renovate: автоматизация зависимостей](./renovate_dependency_updates.md)** — управление версиями образов и чартов через PR.
- **[GitOps: Журналы аудита и трассируемость](./audit_logs.md)** — аудит поставок от коммита до пода.
- **[Обзор Argo CD](../ArgoCD/argocd_overview.md)** · **[Argo CD Image Updater](../ArgoCD/argocd_image_updater.md)** · **[Обзор Flux](../flux.md)**
- **[Harbor: Обзор реестра](../../Docker/Docker_registries/Harbor/overview.md)** · **[Harbor: Репликация](../../Docker/Docker_registries/Harbor/replication.md)** · **[Harbor: Эксплуатация](../../Docker/Docker_registries/Harbor/operations.md)**
- **[Air-gapped ошибки Image Pull](../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md)** · **[Диагностика Image Pull](../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/diagnostics.md)**
- **[Kaniko и альтернативы сборки без демона](../../Docker/Dockerfile/dockerfile_kaniko.md)** · **[Стратегии очистки Docker FS](../../Docker/Docker_fs/cleanup_gc_strategies.md)**

Внешние спецификации и стандарты:
- [OCI Distribution Specification v1.1](https://github.com/opencontainers/distribution-spec/blob/main/spec.md) — официальная спецификация OCI Referrers API.
- [OCI Image Specification v1.1](https://github.com/opencontainers/image-spec/blob/main/spec.md) — структура манифестов и индексов.
- [Kargo Documentation](https://docs.kargo.io/) — оркестрация продвижения артефактов.
- [Flux Image Automation Guide](https://fluxcd.io/flux/guides/image-update/) — автоматизация обновления образов в Git.
- [Sigstore Cosign Documentation](https://docs.sigstore.dev/cosign/overview/) — подписание и аттестация OCI-артефактов.

## Вопросы для собеседования

### Почему в production-манифестах GitOps обязательно указывать digest, а не тег?
**Ответ:** Тег является мутабельным указателем (mutable pointer). Его можно случайно или намеренно перезаписать в реестре (`docker push` с тем же тегом, но другим кодом). Если в Git указан только тег, кластер при перезапуске подов или масштабировании на новые узлы может получить непредсказуемое содержимое. Откат на коммит с тегом `v1.2.3` не гарантирует возврат к прежнему коду. Digest — это криптографический SHA256-хеш манифеста. Он иммутабелен: указание digest гарантирует побайтовую идентичность артефакта, который прошел тестирование, сканирование и подписание.

### Чем опасен плавающий тег `latest` в декларативной инфраструктуре?
**Ответ:** Тег `latest` нарушает главный принцип GitOps — воспроизводимость и детерминированность. При `latest`:
1. В Git отсутствует запись о конкретной версии работающего кода (теряется трассируемость и аудит).
2. Разные узлы одного кластера могут исполнять разные версии одного и того же сервиса (если один узел скачал `latest` вчера, а второй — сегодня после пуша новой версии).
3. Невозможно выполнить автоматический или ручной откат (Rollback) через откат коммита в Git.

### В чем разница между удалением тега через Harbor API и запуском Garbage Collection?
**Ответ:** Удаление тега через веб-интерфейс или REST API Harbor выполняет логическое удаление (Soft Delete): из базы данных PostgreSQL удаляется запись тега и ссылка на манифест. Физические блобы (слои данных) остаются на дисковом хранилище, чтобы не нарушить целостность других образов, которые могут делить эти слои. Реальное освобождение дискового пространства происходит только при запуске Garbage Collection (GC) через Job Service: сборщик мусора обходит все сохраненные блобы, находит те, на которые больше нет ссылок ни от одного манифеста (dangling blobs), и удаляет их из хранилища.

### Как работает механизм Kubelet Image Garbage Collection и чем грозит неправильная настройка порогов?
**Ответ:** Kubelet периодически опрашивает рантайм (containerd) и проверяет свободное место на дисковом разделе хранения образов. При превышении `imageGCHighThresholdPercent` (по умолчанию 80%) kubelet удаляет неиспользуемые контейнерами образы (начиная с самых старых по времени последнего использования) до тех пор, пока занятое пространство не опустится до `imageGCLowThresholdPercent` (по умолчанию 70%). Если пороги настроены слишком высоко, диск может заполниться до порогов Hard Eviction (`imagefs.available<15%`), что вызовет состояние `DiskPressure` и массовое принудительное выселение подов с узла. Если пороги слишком низкие — kubelet будет непрерывно удалять образы, заставляя ноду заново скачивать их при каждом масштабировании или перезапуске подов.

### Как организовать надежную доставку образов в air-gapped контур без доступа к Интернету?
**Ответ:**
1. На границе внешнего контура настраивается буферный реестр (Harbor/skopeo-скрипты), который выполняет синхронизацию необходимых публичных образов с проверкой их подписей и уязвимостей.
2. Перенос в изолированный контур осуществляется через защищенный транспорт (диод данных или физические носители) в виде архивов OCI (`skopeo copy docker-archive:...`) либо через межсетевой шлюз репликации Harbor.
3. Внутри закрытого контура развернут локальный HA-кластер Harbor.
4. На рабочих узлах containerd настраивается через `/etc/containerd/certs.d/` с указанием локального зеркала и доверенного внутреннего CA-сертификата.
5. Политики Admission Control в кластере проверяют, что все образы поступают исключительно из внутреннего домена Harbor и подписаны корпоративным ключом.
