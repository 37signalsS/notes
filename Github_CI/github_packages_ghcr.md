# GitHub Packages и GHCR: Реестры, публикация, управление

**Актуально для:** GitHub Packages, GHCR, октябрь 2026 (OCI Image Index v1.1, OIDC trusted publishing, Fine-grained PAT v2, Container Cleanup Policies, Helm OCI Registry, ORAS artifacts, multi-arch builds)

GitHub Packages — это встроенная в платформу GitHub распределённая система хостинга пакетов и артефактов (Container Registry, npm, Maven, Gradle, NuGet, PyPI, RubyGems). GHCR (GitHub Container Registry, `ghcr.io`) — OCI-совместимый реестр контейнеров и артефактов (Docker, OCI-образы, Helm-чарты, ORAS-блобы) с нативной поддержкой ролевой модели GitHub, бессерверной аутентификации عبر OIDC, тонких прав доступа (Fine-grained PAT) и встроенных политик очистки.

## Определения

- **GitHub Packages**: Мультиформатный реестр пакетов и артефактов GitHub. Поддерживает форматы: `container` (GHCR), `npm`, `maven`, `gradle`, `nuget`, `pypi`, `rubygems`.
- **GHCR (GitHub Container Registry)**: Сервис реестра OCI-артефактов, доступный по адресу `ghcr.io`. В отличие от устаревшего `docker.pkg.github.com`, поддерживает хранение на уровне организации/аккаунта, раздельные права доступа от исходного кода, OCI Image Index (multi-arch), Helm-чарты и произвольные артефакты через ORAS.
- **OCI Image Index (Manifest List)**: Спецификация OCI, объединяющая манифесты образов для нескольких целевых платформ (например, `linux/amd64` и `linux/arm64`) под единым тегом или дайджестом.
- **ORAS (OCI Registry As Storage)**: Инструмент и стандарт для хранения произвольных файлов, конфигураций, архивов и бинарных дистрибутивов в OCI-совместимых реестрах.
- **OIDC Trusted Publishing**: Механизм обмена короткоживущего токена GitHub Actions (`id-token: write`) на временные права публикации в реестре без использования долгоживущих паролей или токенов.
- **Fine-grained PAT (PAT v2)**: Персональный токен доступа GitHub с гранулярным разграничением прав (например, только `Packages: Read and Write` для строго заданных репозиториев) и обязательным сроком истечения.
- **Package-Repository Association**: Привязка пакета к конкретному репозиторию. Определяет наследование прав доступа, отображение во вкладке Packages и автоматическое предоставление прав `GITHUB_TOKEN`.
- **Package Visibility**: Уровень доступности пакета — `public` (доступен для чтения без аутентификации), `internal` (доступен всем участникам организации/Enterprise), `private` (требует явных прав чтения).
- **Cleanup Policies**: Автоматизированные серверные правила жизненного цикла версий пакетов в организации, удаляющие нетегированные или устаревшие версии по расписанию.
- **Digest Pinning**: Фиксация контейнерного образа в инфраструктуре по неизменяемому SHA-256 хешу манифеста (`image@sha256:...`), предотвращающая риски подмены тега и дрейфа конфигурации.
- **Cosign Keyless Signing**: Подписание контейнерных образов в GHCR через Sigstore с использованием идентификатора рабочего процесса GitHub Actions (OIDC) без управления закрытыми ключами.

## Архитектура, принципы работы и модель доступа

### 1. Архитектура сервиса GHCR и потоки данных

```
                                  [ GitHub Platform ]
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
      GitHub Actions Workflow                         GitHub API / Web UI
  (GITHUB_TOKEN / OIDC id-token)                  (gh api / Org & Repo Settings)
                 │                                               │
                 │ Authenticated Push / Pull                     │ Cleanup / Permissions
                 ▼                                               ▼
      ┌─────────────────────────────────────────────────────────────────┐
      │                    GHCR (https://ghcr.io)                       │
      │  - Control Plane & OCI Distribution v2 API                      │
      │  - Аутентификация: GITHUB_TOKEN, Fine-grained PAT, OIDC          │
      │  - Метаданные, OCI Manifests, OCI Image Index                   │
      └────────────────────────────────┬────────────────────────────────┘
                                       │ Редирект на загрузку слоёв (HTTP 302)
                                       ▼
      ┌─────────────────────────────────────────────────────────────────┐
      │      Storage Backend (pkg-containers.githubusercontent.com)     │
      │  - Распределённое хранилище OCI Blobs / Layers                  │
      │  - Дедупликация идентичных слоёв в рамках пространства имён    │
      └─────────────────────────────────────────────────────────────────┘
                                       ▲
                                       │ Layer download
           [ Kubernetes Cluster / On-Premise Host / Docker Daemon ]
           (imagePullSecrets, containerd hosts.toml, curl/oras)
```

> [!IMPORTANT]
> При загрузке слоёв образов (`docker pull`, `crictl pull`, `helm pull`) реестр `ghcr.io` возвращает HTTP 302 Redirect на домен хранилища `pkg-containers.githubusercontent.com`. В закрытых периметрах и на узлах за корпоративным прокси файрвол должен разрешать исходящий трафик к **обоим** доменам по порту 443/TCP.

### 2. Иерархия прав доступа и пространств имён

1. **Пространство имён (Namespace)**:
   - В GHCR имя пакета имеет вид: `ghcr.io/<owner>/<package_name>`.
   - Для репозиториев организаций: `<owner>` — имя организации (строго в нижнем регистре). Имя пакета по умолчанию совпадает с именем репозитория, но может быть произвольным (например, монорепозиторий публикует несколько микросервисов: `ghcr.io/acme-corp/auth-service`, `ghcr.io/acme-corp/billing-service`).
2. **Привязка к репозиторию (Repository Linking)**:
   - При первой публикации из GitHub Actions с использованием `${{ secrets.GITHUB_TOKEN }}` пакет автоматически связывается с репозиторием запуска.
   - Права доступа воркфлоу к пакету наследуются от репозитория (`Admin`, `Write`, `Read`).
   - Если пакет опубликован через внешний PAT без привязки к репозиторию, доступ для Actions настраивается вручную в меню пакета: **Package Settings → Manage Actions access**.
3. **Модель видимости**:
   - `private`: Доступен только пользователям и токенам с явными правами чтения в организации или репозитории.
   - `internal`: Доступен любому аутентифицированному участнику GitHub Enterprise / Organization.
   - `public`: Доступен для анонимного чтения без авторизации через `docker pull`.

### 3. Матрица методов аутентификации

| Метод аутентификации | Где применяется | Необходимые права / Scopes | Срок жизни | Ротация и безопасность |
|---|---|---|---|---|
| `GITHUB_TOKEN` | GitHub Actions (тот же репозиторий) | `permissions: packages: write` | Время выполнения Job (эфемерен) | Максимальная безопасность; нет хранимых секретов |
| GitHub App Token | Кросс-репозиторные CI/CD задачи | Permission `Packages: read/write` | 1 час | Высокая безопасность; централизованный отзыв |
| Fine-grained PAT (v2) | Локальный CLI, Kubernetes `imagePullSecrets`, VM | `Packages: Read and Write` (выбранные репозитории) | До 365 дней | Минимальные права; требует мониторинга срока |
| Classic PAT (`ghp_...`) | Устаревшие системы (не рекомендуется) | `write:packages`, `read:packages`, `delete:packages` | Задаётся пользователем | Опасен: даёт глобальный доступ ко всем пакетам аккаунта |
| OIDC (Sigstore / Provenance) | Публикация и подписание образов (Cosign, npm) | `permissions: id-token: write` | Короткоживущий токен сессии | Zero-secret; исключает утечки закрытых ключей |

## Практические сценарии

### Сценарий 1: Multi-arch сборка (amd64/arm64) и публикация в GHCR с кешированием в GHA и SBOM/Provenance

Сборка оптимизированного контейнера для двух архитектур с сохранением метаданных, генерацией SBOM и кэшированием слоёв через GitHub Actions Cache.

**Предварительные требования**:
- Включён сервис GitHub Packages в настройках репозитория.
- Наличие `Dockerfile` в корне проекта.

```yaml
name: Build and Push Multi-Arch Image to GHCR

on:
  push:
    tags:
      - 'v*.*.*'
    branches:
      - main
  workflow_dispatch:

permissions:
  contents: read
  packages: write
  id-token: write

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout source code
        uses: actions/checkout@v7

      - name: Set up QEMU (эмуляция архитектур)
        uses: docker/setup-qemu-action@v3
        with:
          platforms: 'linux/amd64,linux/arm64'

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v4

      - name: Login to GitHub Container Registry
        uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata and tags
        id: meta
        uses: docker/metadata-action@v6
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=raw,value=latest,enable=${{ github.ref == format('refs/heads/{0}', github.event.repository.default_branch) }}
            type=sha,prefix=sha-

      - name: Build and push multi-arch image
        uses: docker/build-push-action@v7
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          provenance: mode=max
          sbom: true
```

**Валидация**:
Инспекция созданного OCI Image Index через CLI:

```bash
# Инспекция опубликованного манифеста
docker buildx imagetools inspect ghcr.io/acme-org/service:v1.4.0
# → Name:      ghcr.io/acme-org/service:v1.4.0
# → MediaType: application/vnd.oci.image.index.v1+json
# → Digest:    sha256:4b227c...
# → Manifests:
# →   Platform: linux/amd64
# →   Digest:   sha256:a1b2c3...
# →   Platform: linux/arm64
# →   Digest:   sha256:d4e5f6...
```

### Сценарий 2: Криптографическое подписание OCI-образа через Cosign (Keyless Sigstore)

Подписание опубликованного в GHCR образа с использованием OIDC токена GitHub Actions без сохранения закрытых ключей.

**Предварительные требования**:
- Опубликованный образ в `ghcr.io`.
- Установленные права `id-token: write` и `packages: write`.

```yaml
name: Sign Container Image

on:
  workflow_run:
    workflows: ["Build and Push Multi-Arch Image to GHCR"]
    types: [completed]
    branches: [main]

permissions:
  contents: read
  packages: write
  id-token: write

jobs:
  sign:
    runs-on: ubuntu-latest
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    steps:
      - name: Install Cosign
        uses: sigstore/cosign-installer@v3.8.1

      - name: Authenticate to GHCR
        uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Sign container image
        run: |
          IMAGE_URI="ghcr.io/${{ github.repository }}:sha-${{ github.event.workflow_run.head_sha }}"
          cosign sign --yes "${IMAGE_URI}"
```

**Валидация**:
Проверка подписи образа из терминала администратора:

```bash
# Проверка соответствия сертификата рабочему процессу репозитория
cosign verify \
  --certificate-identity-regexp "^https://github.com/acme-org/service/.github/workflows/" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  ghcr.io/acme-org/service:v1.4.0
# → Verification for ghcr.io/acme-org/service:v1.4.0 --
# → The following checks were performed on each of these signatures:
# →   - The cosign claims were validated
# →   - The code signing cert was verified to be issued by Fulcio
# →   - The certificate was verified against Rekor transparency log
```

### Сценарий 3: Публикация и версионирование Helm-чартов в GHCR как OCI-артефактов

GHCR нативно поддерживает работу с Helm v3+ через протокол OCI (`oci://ghcr.io/...`).

**Предварительные требования**:
- Установленный Helm v3.14+.
- Директория с чартом `./charts/my-app` (содержит `Chart.yaml` и `values.yaml`).

```bash
# 1. Аутентификация в GHCR через Helm
echo "${GITHUB_TOKEN}" | helm registry login ghcr.io --username "${GITHUB_ACTOR}" --password-stdin
# → Login Succeeded

# 2. Упаковка Helm-чарта в tgz архив
helm package ./charts/my-app --destination .
# → Successfully packaged chart and saved it to: ./my-app-1.2.0.tgz

# 3. Публикация чарта в OCI-пространство GHCR
helm push ./my-app-1.2.0.tgz oci://ghcr.io/acme-org/charts
# → Pushed: ghcr.io/acme-org/charts/my-app:1.2.0
# → Digest: sha256:7f9a12bc...
```

**Развёртывание чарта из GHCR в Kubernetes**:

```bash
# Скачивание метаданных и развёртывание напрямую из OCI реестра
helm upgrade --install my-release oci://ghcr.io/acme-org/charts/my-app \
  --version 1.2.0 \
  --namespace production \
  --values values-prod.yaml
# → Release "my-release" has been upgraded. Happy Helming!
```

### Сценарий 4: Хранение и дистрибуция бинарных артефактов и конфигураций через ORAS

Дистрибуция системных конфигураций, тарболлов или бинарных файлов через GHCR с использованием стандарта OCI Registry As Storage (ORAS).

**Предварительные требования**:
- Установленный бинарник `oras` v1.2+.

```bash
# 1. Авторизация в реестре
echo "${GH_TOKEN}" | oras login ghcr.io -u "${GH_USER}" --password-stdin
# → Login Succeeded

# 2. Подготовка и отправка произвольного архива
tar -czf infra-configs.tar.gz -C ./configs .
oras push ghcr.io/acme-org/infra-artifacts:2026.10 \
  infra-configs.tar.gz:application/vnd.acme.config.layer.v1+tar \
  --annotation "org.opencontainers.image.description=Production infrastructure configs"
# → Uploading 3f12a... infra-configs.tar.gz
# → Pushed [registry] ghcr.io/acme-org/infra-artifacts:2026.10
# → Digest: sha256:91c0e3...

# 3. Загрузка артефакта на целевом сервере
oras pull ghcr.io/acme-org/infra-artifacts:2026.10
# → Downloading 3f12a... infra-configs.tar.gz
# → Pulled [registry] ghcr.io/acme-org/infra-artifacts:2026.10
```

### Сценарий 5: Безопасный Pull приватных образов в Kubernetes (imagePullSecrets и системный containerd)

#### Способ А: На уровне пространств имён через `imagePullSecrets`

```bash
# Создание секрета на основе Fine-grained PAT с правом Packages: Read
kubectl create secret docker-registry ghcr-auth-secret \
  --docker-server=ghcr.io \
  --docker-username="robot-ci" \
  --docker-password="${GHCR_READ_TOKEN}" \
  --namespace=apps
# → secret/ghcr-auth-secret created
```

Привязка секрета к ServiceAccount (рекомендуемый SRE-паттерн, чтобы не указывать секрет в каждом Deployment):

```bash
kubectl patch serviceaccount default -n apps -p '{"imagePullSecrets": [{"name": "ghcr-auth-secret"}]}'
# → serviceaccount/default patched
```

#### Способ Б: На уровне узлов кластера через `containerd` (`hosts.toml`)

Системный подход системного администратора для bare-metal / on-premise кластеров, избавляющий от необходимости создавать Kubernetes-секреты в каждом неймспейсе.

Конфигурационный файл `/etc/containerd/certs.d/ghcr.io/hosts.toml`:

```toml
server = "https://ghcr.io"

[host."https://ghcr.io"]
  capabilities = ["pull", "resolve"]
  [host."https://ghcr.io".header]
    # Заголовок Authorization: Basic <base64(username:token)>
    Authorization = "Basic cm9ib3QtY2k6Z2hwX2V4YW1wbGV0b2tlbjEyMzQ1Ng=="
```

Проверка применения конфигурации узла:

```bash
sudo ctr --namespace k8s.io images pull ghcr.io/acme-org/service:v1.4.0
# → fetching sha256:4b227c...
# → unpacking sha256:4b227c... done
```

### Сценарий 6: Автоматизация очистки версий (Cleanup Policies и защита multi-arch манифестов)

#### 1. Настройка политики очистки на уровне организации через GitHub CLI

```bash
# Настройка серверной политики: хранить не более 50 версий, удалять нетегированные старше 14 дней
gh api -X PUT /orgs/acme-org/packages/cleanup-policies \
  -f package_type='container' \
  -F max_versions=50 \
  -F keep_untagged=false \
  -F delete_untagged_after_days=14
# → { "status": "configured", "package_type": "container", "max_versions": 50 }
```

#### 2. Скрипт безопасного удаления устаревших нетегированных версий

> [!WARNING]
> В OCI Image Index слои и дочерние платформенные манифесты (`linux/amd64`, `linux/arm64`) часто не имеют собственного тега, ссылаясь на корневой манифест. Удаление всех нетегированных версий в лоб через REST API разрушает multi-arch образы! Скрипт ниже проверяет отсутствие входящих ссылок перед удалением.

```bash
#!/usr/bin/env bash
set -euo pipefail

ORG="acme-org"
PACKAGE="service"

echo "Проверка нетегированных версий пакета ${PACKAGE}..."
UNTAGGED_VERSIONS=$(gh api "/orgs/${ORG}/packages/container/${PACKAGE}/versions" --paginate \
  --jq '.[] | select(.metadata.container.tags | length == 0) | {id: .id, name: .name, created_at: .created_at}')

echo "${UNTAGGED_VERSIONS}" | jq -c '.' | while read -r version; do
  VID=$(echo "${version}" | jq -r '.id')
  VNAME=$(echo "${version}" | jq -r '.name')
  CREATED=$(echo "${version}" | jq -r '.created_at')

  echo "Удаление устаревшей нетегированной версии ID=${VID} (${VNAME}, создана ${CREATED})..."
  gh api -X DELETE "/orgs/${ORG}/packages/container/${PACKAGE}/versions/${VID}"
  # → HTTP 204 No Content
done
```

### Сценарий 7: Публикация в языковые реестры (npm, Maven, PyPI)

#### 1. Публикация npm-пакета с генерацией Provenance

Файл `.npmrc` в корне проекта:

```ini
@acme-org:registry=https://npm.pkg.github.com
//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}
```

Фрагмент GitHub Actions воркфлоу:

```yaml
permissions:
  contents: read
  packages: write
  id-token: write

steps:
  - uses: actions/checkout@v7
  - uses: actions/setup-node@v7
    with:
      node-version: 24
      registry-url: https://npm.pkg.github.com
      scope: '@acme-org'

  - run: npm ci
  - run: npm publish --provenance
    env:
      NODE_AUTH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

#### 2. Публикация Maven-артефакта

Конфигурация в `pom.xml`:

```xml
<distributionManagement>
  <repository>
    <id>github</id>
    <name>GitHub Packages</name>
    <url>https://maven.pkg.github.com/acme-org/core-lib</url>
  </repository>
</distributionManagement>
```

Команда публикации с динамической генерацией авторизации:

```bash
mvn deploy -DskipTests \
  -DaltServerId=github \
  -DaltDeploymentRepository=github::default::https://maven.pkg.github.com/acme-org/core-lib \
  "-Dhttp.password=${GITHUB_TOKEN}" \
  "-Dhttp.username=${GITHUB_ACTOR}"
# → [INFO] BUILD SUCCESS
```

## Команды и операции

### Операции через GitHub CLI (`gh api`)

| Задача | Команда | Ожидаемый результат / Примечание |
|---|---|---|
| Список пакетов организации | `gh api /orgs/<org>/packages --jq '.[] \| {name: .name, type: .package_type, visibility: .visibility}'` | `# → {"name": "service", "type": "container", "visibility": "private"}` |
| Список всех версий и тегов | `gh api /orgs/<org>/packages/container/<name>/versions --jq '.[] \| {id: .id, tags: .metadata.container.tags}'` | `# → {"id": 1289410, "tags": ["v1.4.0", "latest"]}` |
| Детали конкретной версии | `gh api /orgs/<org>/packages/container/<name>/versions/<version_id>` | `# → JSON с manifest digest, html_url, created_at` |
| Смена видимости пакета | `gh api -X PATCH /orgs/<org>/packages/container/<name> -f visibility=internal` | `# → HTTP 200 { "visibility": "internal" }` |
| Удаление конкретной версии | `gh api -X DELETE /orgs/<org>/packages/container/<name>/versions/<version_id>` | `# → HTTP 204 No Content` |
| Полное удаление пакета | `gh api -X DELETE /orgs/<org>/packages/container/<name>` | `# → HTTP 204 No Content` (требует прав Admin) |
| Восстановление пакета | `gh api -X POST /orgs/<org>/packages/container/<name>/restore` | `# → HTTP 200 (доступно в течение 30 дней после удаления)` |
| Запрос текущего объема хранилища | `gh api /orgs/<org>/settings/billing/packages --jq '{total_paid: .total_paid_gigabytes_storage_used}'` | `# → {"total_paid": 14.5}` |

### Операции Skopeo и Docker CLI

```bash
# Инспекция манифеста удалённого образа без локального скачивания (Skopeo)
skopeo inspect docker://ghcr.io/acme-org/service:v1.4.0 --creds="${GH_USER}:${GH_TOKEN}"
# → { "Name": "ghcr.io/acme-org/service", "Digest": "sha256:4b227c...", "RepoTags": [...] }

# Копирование образа напрямую между GHCR и внутренним реестром (без локального docker daemon)
skopeo copy \
  --src-creds="${GH_USER}:${GH_TOKEN}" \
  --dest-creds="${INTERNAL_USER}:${INTERNAL_PASS}" \
  docker://ghcr.io/acme-org/service:v1.4.0 \
  docker://registry.internal.local/apps/service:v1.4.0
# → Copying blob sha256:...
# → Writing manifest to image destination
# → Storing list of ta  - [Open Container Initiative (OCI) Distribution Spec](https://github.com/opencontainers/distribution-spec)
� `Downloading` слоёв | Корпоративный файрвол блокирует доступ к CDN хранилища блобов GitHub | Проверить сетевой доступ с раннера/хоста:<br>`curl -Iv https://pkg-containers.githubusercontent.com` | Добавить `pkg-containers.githubusercontent.com` и `ghcr.io` в белые списки прокси и системных файрволов |
| `429 Too Many Requests` при анонимном `docker pull` | Превышен лимит запросов на анонимное скачивание публичных пакетов с общего IP NAT | Проверить заголовки ответа curl: `curl -I https://ghcr.io/v2/` | Настроить обязательную аутентификацию демонов Docker/containerd даже для публичных образов с использованием сервисного PAT |
| `409 Conflict` при повторной публикации npm/Maven/PyPI пакета | Попытка перезаписать существующую версию неизменяемого пакета (immutability) | Проверить код ошибки в выводе менеджера пакетов: `npm ERR! 409 Conflict - Package version already exists` | Инкрементировать версию пакета (SemVer). GitHub Packages запрещает перезапись артефактов с одинаковым версионным номером |

## Лучшие практики

1. **Принцип наименьших привилегий для CI/CD**:
   - В воркфлоу GitHub Actions всегда используйте стандартный `${{ secrets.GITHUB_TOKEN }}` с явным определением секции `permissions: packages: write`.
   - Никогда не передавайте глобальные Classic PAT (`repo`, `write:packages`) в качестве репозиторных секретов.
2. **Изоляция служебных токенов инфраструктуры**:
   - Для серверов, Kubernetes-кластеров и внешних раннеров генерируйте отдельные Fine-grained PAT с правами `Packages: Read-only` исключительно на требуемые репозитории.
3. **Безопасность цепочки поставок (Supply Chain Security)**:
   - В production-манифестах Kubernetes и docker-compose фиксируйте образы по дайджесту (`ghcr.io/org/app@sha256:...`). Это исключает риски отравления тегов (`tag mutability`).
   - Подписывайте образы через Cosign с использованием `id-token: write` (Keyless Sigstore) и валидируйте аттестации Provenance/SBOM перед выкаткой в продакшн.
4. **Управление расходами и квотами хранилища**:
   - Включайте политики `Cleanup Policies` на уровне организации для пакетов типа `container`.
   - Настройте порог хранения не более 50–100 версий и автоматическое удаление нетегированных версий старше 14–30 дней.
   - Контролируйте размер слоёв в Dockerfile: используйте multi-stage сборки, очистку кешей пакетных менеджеров и минималистичные базовые образы (`distroless`, `alpine`).
5. **Сетевая устойчивость и оптимизация трафика**:
   - Используйте кэширование BuildKit через `cache-from: type=gha` и `cache-to: type=gha,mode=max`.
   - Для bare-metal узлов настраивайте авторизацию на уровне `containerd hosts.toml`, минимизируя нагрузку на Kubernetes API сервер при монтировании секретов.
6. **Нижний регистр имён**:
   - Всегда нормализуйте имена репозиториев и тегов к нижнему регистру (`${GITHUB_REPOSITORY,,}`), так как OCI спецификация и GHCR строго чувствительны к регистру.

## Дополнительная информация

- **[Оптимизация сборки и кэширования](./Optimization.md)** — ускорение сборки контейнеров, BuildKit registry cache.
- **[Управление релизами и артефактами](./Release_Management.md)** — релизные пайплайны и продвижение версий.
- **[Сетевая безопасность GitHub Actions](./network-security.md)** — аудит сетевых подключений и белые списки доменов.
- **[Управление секретами и OIDC](./secrets_management.md)** — архитектура federated auth, настройка OpenID Connect.
- **[GitHub Apps](./github_apps.md)** — выпуск краткосрочных App Installation Tokens для кросс-репозиторной публикации.
- **[Контейнеризация и исполнение задач](./Container_Execution.md)** — запуск изолированных шагов внутри контейнеров.
- **[Реестры Docker и OCI](../Docker/docker_registries.md)** — архитектура и стандарты современных контейнерных реестров.
- **[Безопасность публичных реестров](../Docker/Docker_registries/public_registry_security.md)** — верификация подписей Cosign и защита от атак на цепочку поставок.
- **[Harbor: обновление Trivy](../Docker/Docker_registries/Harbor/offline_trivy_update.md)** — пример зеркалирования OCI-артефактов из GHCR в закрытый периметр.
- **Официальная документация**:
  - [Working with the Container registry (ghcr.io)](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
  - [GitHub Packages REST API](https://docs.github.com/en/rest/packages)
  - [Open Container Initiative (OCI) Distribution Spec](https://github.com/opencontainers/distribution-spec)
 настройки пакета (Package Settings → Actions access) |
| `denied: requested access to the resource is denied` | Токен не имеет доступа к целевой организации/репозиторию | Использовать fine-grained PAT с доступом к конкретному пакету или App Installation Token |
| `manifest unknown` при pull | Образ не существует / неверный тег / приватный пакет без аутентификации | Проверить тег: `gh api /orgs/<ORG>/packages/container/<IMAGE>/versions`; убедиться в `docker login` |
| `NAMESPACE_NOT_FOUND` / `PACKAGE_NOT_FOUND` | Неверный owner (user vs org) или имя пакета | Для user-пакетов: `ghcr.io/<USER>/<IMAGE>`; для org: `ghcr.io/<ORG>/<REPO>/<IMAGE>` |
| Cleanup policy не срабатывает | Политика настроена на уровне org, но пакет привязан к репозиторию с другими настройками | Проверить настройки пакета (Package Settings → Cleanup policies) — приоритет у пакет-уровня |
| `npm publish` проходит, но пакет не виден в GitHub Packages | Публикация шла в npmjs.org, а не в `npm.pkg.github.com` | Указать `registry-url: https://npm.pkg.github.com` в `setup-node` |
| Rate limit при массовых операциях | Превышен лимит API (5000 req/hr для authenticated) | Использовать `gh api` с пагинацией; добавить паузы; кэшировать результаты |

## Лучшие практики

1. **Всегда используйте `GITHUB_TOKEN` с `packages: write`** для публикации из GitHub Actions в тот же репозиторий/организацию — никаких секретов не нужно.
2. **Для cross-repo/organization публикации** — создавайте fine-grained PAT или GitHub App с минимальными правами (`packages: write` только на целевые пакеты).
3. **Включайте Cleanup Policies** на уровне организации: `max_versions: 50–100`, `delete_untagged_after_days: 30` — предотвращает неконтролируемый рост хранилища.
4. **Используйте Trusted Publishing (OIDC)** для npm/PyPI/RubyGems — исключает утечку долгоживущих токенов и даёт provenance.
5. **Закрепляйте образы по digest** в production (`image: ghcr.io/org/repo@sha256:...`) — иммутабельность поставки.
6. **Настраивайте Package Visibility** явно: `private` для внутренних, `internal` для org-wide, `public` только для OSS.
7. **Для Kubernetes** — используйте `imagePullSecrets` с fine-grained PAT, не кладите PAT в код/конфиги.
8. **Монитьте использование хранилища** через API (`/orgs/{org}/packages` + сумма размеров версий) — лимиты GitHub Packages зависят от плана (GitHub Team/Enterprise).

## Дополнительная информация

- **[Управление релизами](./Release_Management.md)** — публикация артефактов как часть релизного конвейера.
- **[Сетевая безопасность](./network-security.md)** — аудит трафика к GHCR через Harden-Runner.
- **[Управление секретами](./secrets_management.md)** — иерархия токенов, OIDC, fine-grained PAT.
- **[GitHub Apps](./github_apps.md)** — App Installation Tokens для cross-repo публикации.
- **Официальная документация**: [GitHub Packages](https://docs.github.com/en/packages), [GHCR](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry), [Trusted Publishing](https://docs.github.com/en/packages/working-with-a-github-packages-registry/publishing-and-managing-packages/trusted-publishers).