# GitHub Packages и GHCR: Реестры, публикация, управление

**Актуально для:** GitHub Packages, GHCR, октябрь 2026 (OIDC trusted publishing, fine-grained PAT, registry API v2, cleanup policies, organization-level packages)

GitHub Packages — это встроенная в платформу GitHub система хостинга пакетов (Container Registry, npm, Maven, NuGet, PyPI, RubyGems, Terraform, Debian). GHCR (GitHub Container Registry) — специализированный OCI-совместимый реестр для Docker-образов и Helm-чартов с нативной интеграцией в GitHub Actions, правами доступа на уровне репозитория/организации и поддержкой trusted publishing через OIDC.

## Определения

- **GitHub Packages**: Универсальный реестр пакетов, встроенный в GitHub. Поддерживает экосистемы: npm, Maven, Gradle, NuGet, PyPI, RubyGems, Terraform, Debian, Docker (GHCR), Helm.
- **GHCR (GitHub Container Registry)**: OCI-совместимый реестр для Docker-образов (`ghcr.io`) и Helm-чартов. Наследует модель прав доступа GitHub (репозиторий/организация), поддерживает fine-grained permissions и OIDC.
- **Package Registry API**: REST/GraphQL API для программного управления пакетами (создание, чтение, удаление, управление версиями, cleanup policies).
- **OIDC Trusted Publishing**: Публикация пакетов без долгоживущих токенов: GitHub Actions выдаёт короткоживущий ID-токен (`id-token: write`), реестр обменивает его на право публикации. Работает для npm, PyPI, RubyGems, GHCR.
- **Fine-grained PAT**: Токен с ограниченным набором прав (только `packages: read` / `packages: write` / `packages: delete` для конкретных репозиториев/организаций), заменяет классические PAT для CI/CD.
- **Package Visibility**: Уровень видимости пакета — `public` (виден всем), `internal` (виден в организации/Enterprise), `private` (виден только с явным доступом). Настраивается в настройках пакета или при публикации.
- **Cleanup Policies**: Правила автоматического удаления старых/неиспользуемых версий пакетов (по количеству версий, возрасту, тегам). Настраиваются на уровне репозитория/организации/Enterprise.
- **Package Inheritance**: Пакет наследует права доступа и видимость от репозитория, к которому привязан (если не настроено иначе). При передаче репозитория пакет переходит вместе с ним.
- **Registry URL Pattern**: `ghcr.io/<OWNER>/<REPOSITORY>/<IMAGE>:<TAG>` для образов; `npm.pkg.github.com/<OWNER>/<PACKAGE>` для npm; `maven.pkg.github.com/<OWNER>/<REPO>/<ARTIFACT>` для Maven.

## Архитектура и модель доступа

### Иерархия прав доступа к пакетам

```
Enterprise/Organization
    ↓ (настройки пакетов по умолчанию, cleanup policies)
Repository (owner пакета)
    ↓ (Package Settings → Manage Actions access / Package visibility)
Package (конкретный образ/пакет)
    ├── Read: pull, download, view metadata
    ├── Write: push, publish new versions, manage versions
    ├── Delete: delete versions, delete package
    └── Admin: manage settings, transfer ownership, configure cleanup
```

### Режимы аутентификации для публикации/pull

| Сценарий | Метод | Права | Примечание |
|---|---|---|---|
| GitHub Actions (репозиторий пакета) | `GITHUB_TOKEN` | `packages: write` / `read` | Автоматически, без секретов |
| GitHub Actions (другой репозиторий) | Fine-grained PAT / App Installation Token | `packages: write` | Нужен токен с доступом к целевому пакету |
| Локальная разработка / Docker CLI | `gh auth token` / PAT | `packages: read/write` | `echo $GH_TOKEN \| docker login ghcr.io -u USER --password-stdin` |
| Trusted Publishing (npm/PyPI/RubyGems) | OIDC (`id-token: write`) | Без токена | Настраивается в настройках пакета на стороне реестра |
| Self-hosted runners | Fine-grained PAT / App Token | `packages: read/write` | Классический PAT не рекомендуется |

## Практические сценарии

### Сценарий 1: Публикация Docker-образа в GHCR через GitHub Actions

**Предварительные требования**: Репозиторий с Dockerfile; включён GitHub Packages в настройках организации/репозитория; права `packages: write` для воркфлоу.

```yaml
name: Publish to GHCR
on:
  push:
    tags: ['v*']
  workflow_dispatch:

permissions:
  contents: read
  packages: write      # обязательно для push в GHCR
  id-token: write      # для trusted publishing (опционально, но рекомендуется)

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Login to GHCR
        uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ github.token }}   # GITHUB_TOKEN с packages:write
      
      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v6
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=raw,value=latest,enable={{is_default_branch}}
            type=sha,prefix=
      
      - name: Build and push
        uses: docker/build-push-action@v7
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

**Валидация**: `docker pull ghcr.io/<owner>/<repo>:<tag>` — образ скачивается; в UI репозитория вкладка **Packages** показывает опубликованный образ с тегами.

### Сценарий 2: Публикация npm-пакета через Trusted Publishing (OIDC)

**Предварительные требования**: Пакет на npmjs.com; в настройках пакета добавлен Trusted Publisher типа "GitHub Actions" с указанием репозитория и имени воркфлоу (опционально — environment).

```yaml
name: Publish npm
on:
  release:
    types: [published]

permissions:
  contents: read
  id-token: write      # критично для OIDC

jobs:
  publish-npm:
    runs-on: ubuntu-latest
    environment: production   # гейт перед внешней публикацией
    steps:
      - uses: actions/checkout@v7
      
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          registry-url: https://registry.npmjs.org
      
      - run: npm ci
      
      - name: Publish
        run: npm publish --provenance --access public
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}  # не используется при OIDC, но setup-node требует registry-url
```

**Важно**: При trusted publishing `NPM_TOKEN` не создаётся и не нужен. Право `id-token: write` заставляет `npm publish` запросить OIDC-токен у GitHub. Для публичных пакетов npm автоматически прикладывает provenance-атестацию (Sigstore).

### Сценарий 3: Публикация Maven-артефакта в GitHub Packages

```yaml
name: Publish Maven
on:
  release:
    types: [published]

permissions:
  contents: read
  packages: write

jobs:
  publish-maven:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      
      - uses: actions/setup-java@v4
        with:
          distribution: 'temurin'
          java-version: '21'
          server-id: github
          settings-path: ${{ github.workspace }}
          cache: maven
      
      - name: Configure Maven settings
        run: |
          cat > settings.xml <<EOF
          <settings>
            <servers>
              <server>
                <id>github</id>
                <username>${{ github.actor }}</username>
                <password>${{ secrets.GITHUB_TOKEN }}</password>
              </server>
            </servers>
          </settings>
          EOF
      
      - run: mvn -B deploy --settings settings.xml -DskipTests
```

### Сценарий 4: Настройка Cleanup Policies (автоочистка старых версий)

Cleanup policies настраиваются в UI (Settings → Packages → Cleanup policies) или через API. Пример политики через API:

```bash
# Создать политику: хранить только последние 10 версий для untagged образов
gh api -X PUT /orgs/<ORG>/packages/cleanup-policies \
  -f package_type='container' \
  -f max_versions=10 \
  -f keep_untagged=false \
  -f delete_untagged_after_days=30
```

Параметры политики:
- `package_type`: `container` (Docker/Helm), `npm`, `maven`, `nuget`, `rubygems`, `pypi`, `terraform`, `deb`
- `max_versions`: максимальное количество версий для хранения (1–10000)
- `keep_untagged`: `true` — не удалять untagged версии; `false` — удалять по возрасту
- `delete_untagged_after_days`: дни до удаления untagged (1–365, если `keep_untagged=false`)

**Валидация**: В UI пакета версия исчезает после следующего запуска cleanup job (обычно раз в сутки). Проверка: `gh api /orgs/<ORG>/packages/<PACKAGE_ID>/versions` — старые версии отсутствуют.

### Сценарий 5: Удаление версий пакета через API / CLI

```bash
# Удалить конкретную версию контейнера
gh api -X DELETE /orgs/<ORG>/packages/container/<IMAGE>/versions/<VERSION_ID>

# Удалить все untagged версии старше 30 дней (ручная очистка)
gh api /orgs/<ORG>/packages/container/<IMAGE>/versions --jq '.[] | select(.metadata.container.tags == [] and .created_at < "'$(date -d '30 days ago' -Iseconds)'") | .id' | xargs -I {} gh api -X DELETE /orgs/<ORG>/packages/container/<IMAGE>/versions/{}

# Удалить весь пакет (требует admin права)
gh api -X DELETE /orgs/<ORG>/packages/<PACKAGE_TYPE>/<PACKAGE_NAME>
```

### Сценарий 6: Pull приватного образа из GHCR в Kubernetes (imagePullSecrets)

```yaml
# Создать секрет в кластере (один раз)
kubectl create secret docker-registry ghcr-secret \
  --docker-server=ghcr.io \
  --docker-username=<GITHUB_USERNAME> \
  --docker-password=<FINE_GRAINED_PAT_WITH_PACKAGES_READ> \
  --namespace=<NAMESPACE>

# Использовать в Deployment/Pod
spec:
  template:
    spec:
      imagePullSecrets:
        - name: ghcr-secret
      containers:
        - name: app
          image: ghcr.io/<ORG>/<REPO>/<IMAGE>:<TAG>
```

Для GitHub Actions runners в кластере (ARC) — см. **[Actions Runner Controller](./actions_runner_controller.md)**.

### Сценарий 7: Копирование/перемещение пакета между репозиториями/организациями

```bash
# Экспорт манифеста пакета (для миграции)
gh api /orgs/<SRC_ORG>/packages/<TYPE>/<NAME>/versions --jq '.[] | {version: .name, manifest: .metadata.container.manifest}'

# Переопубликация в другую организацию (требует pull + push)
docker pull ghcr.io/<SRC_ORG>/<REPO>/<IMAGE>:<TAG>
docker tag ghcr.io/<SRC_ORG>/<REPO>/<IMAGE>:<TAG> ghcr.io/<DST_ORG>/<REPO>/<IMAGE>:<TAG>
docker push ghcr.io/<DST_ORG>/<REPO>/<IMAGE>:<TAG>
```

## Команды и API-операции

### GitHub CLI (`gh`) для пакетов

```bash
# Список пакетов организации
gh api /orgs/<ORG>/packages --jq '.[] | {name: .name, type: .package_type, visibility: .visibility}'

# Список версий пакета
gh api /orgs/<ORG>/packages/<TYPE>/<NAME>/versions --jq '.[] | {id: .id, name: .name, tags: .metadata.container.tags, created: .created_at}'

# Информация о пакете
gh api /orgs/<ORG>/packages/<TYPE>/<NAME>

# Удалить версию
gh api -X DELETE /orgs/<ORG>/packages/<TYPE>/<NAME>/versions/<VERSION_ID>

# Настройки видимости пакета
gh api -X PATCH /orgs/<ORG>/packages/<TYPE>/<NAME> -f visibility=private

# Cleanup policies (организация)
gh api /orgs/<ORG>/packages/cleanup-policies
gh api -X PUT /orgs/<ORG>/packages/cleanup-policies -f package_type=container -f max_versions=50
```

### Docker CLI с GHCR

```bash
# Аутентификация через gh
echo $GH_TOKEN | docker login ghcr.io -u <USERNAME> --password-stdin

# Или через PAT
echo <PAT> | docker login ghcr.io -u <USERNAME> --password-stdin

# Pull образа
docker pull ghcr.io/<ORG>/<REPO>/<IMAGE>:<TAG>

# Push образа (после login)
docker push ghcr.io/<ORG>/<REPO>/<IMAGE>:<TAG>
```

### REST API ключевые эндпоинты

| Операция | Endpoint |
|---|---|
| Список пакетов org | `GET /orgs/{org}/packages` |
| Получить пакет | `GET /orgs/{org}/packages/{package_type}/{package_name}` |
| Версии пакета | `GET /orgs/{org}/packages/{package_type}/{package_name}/versions` |
| Удалить версию | `DELETE /orgs/{org}/packages/{package_type}/{package_name}/versions/{version_id}` |
| Удалить пакет | `DELETE /orgs/{org}/packages/{package_type}/{package_name}` |
| Cleanup policies | `GET/PUT /orgs/{org}/packages/cleanup-policies` |
| Package visibility | `PATCH /orgs/{org}/packages/{package_type}/{package_name}` |

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| `403 Forbidden` при `docker push` | Нет права `packages: write` у токена / репозиторий не имеет доступа к пакетам | Добавить `permissions: packages: write` в воркфлоу; проверить настройки пакета (Package Settings → Actions access) |
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