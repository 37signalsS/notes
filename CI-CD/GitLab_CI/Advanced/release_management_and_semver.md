# Управление релизами и семантическое версионирование

**Актуально для:** GitLab CI 19.x

## Определения

- **Семантическое версионирование (SemVer)** — стандарт версионирования в формате `MAJOR.MINOR.PATCH`. Является обязательным для ресурсов в **[CI/CD Catalog](../Reusable_Pipelines/ci_cd_catalog_components.md)**. Подробные правила — в **[Управлении артефактами](../../artifact_management.md)**.
- **Conventional Commits** — соглашение о форматировании сообщений коммитов (`feat:`, `fix:`, `refactor:`), обеспечивающее машиночитаемую историю для автоматизации SemVer. См. **[Шаблоны и стандарты коммитов](../../../Git/git_commit_template.md)**.
- **Release Evidence** — JSON-отчет (снимок состояния), содержащий метаданные релиза, результаты тестов и отчеты о безопасности. Используется для аудита и комплаенса.
- **GitLab Release** — объект в интерфейсе GitLab, связывающий тег, описание изменений (Changelog) и ссылки на активы. Создается через блок `release:` в `.gitlab-ci.yml`.
- **SBOM (Software Bill of Materials)** — декларативный список всех компонентов и зависимостей. В современных пайплайнах (2026+) генерация SBOM является обязательным шагом для обеспечения безопасности цепочки поставок (SLSA).

## Предварительные требования

- **GitLab 16.0+** — для декларативного блока `release:` в `.gitlab-ci.yml`.
- **GitLab 18.4+** — для встроенного `glab` CLI (автоматическая замена `release-cli`).
- **Роль Maintainer или выше** — права на создание тегов, релизов и protected tags в проекте.
- **Container Registry / Package Registry** — настроенный и доступный реестр для публикации артефактов.
- **GitLab Runner** — доступный раннер с поддержкой необходимых образов (docker, alpine, node).
- **`glab` CLI** (опционально) — для локальной отладки и ручного управления релизами через API.
- **Cosign / Sigstore** (опционально, рекомендуется) — для подписи артефактов и SBOM в production-средах.

## Основные концепции

### Жизненный цикл релиза

Процесс автоматизации релиза в GitLab CI/CD включает следующие этапы:

1.  **Анализ истории** — пайплайн сканирует коммиты с момента последнего тега для определения следующей версии по правилам SemVer.
2.  **Генерация SBOM и аттестаций** — создание спецификации компонентов и доказательств сборки в доверенной среде.
3.  **Создание Git-тега** — создание уникальной метки версии в репозитории.
4.  **Генерация Release Notes** — автоматический сбор описания изменений на основе заголовков коммитов.
5.  **Сбор доказательств (Evidence)** — автоматическое создание снимка состояния проекта (результаты тестов, SBOM).
6.  **Подпись артефактов** — криптографическая подпись образов и аттестаций через **[Cosign/Sigstore](../../../Security/Tools/sigstore.md)** для гарантии целостности и подлинности.
7.  **Ассоциация активов (Assets)** — привязка Docker-образов, бинарных файлов и документации к релизу через постоянные ссылки.
8.  **Публикация** — отправка артефактов в реестры (Container Registry, Package Registry).

### Стратегии релизов

Выбор стратегии определяется политикой команды и типом проекта. Все стратегии используют SemVer как базовый формат версионирования.

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Continuous Release** | Каждый коммит в основную ветку автоматически определяет тип изменения и bump-ит версию | Микросервисы, частые деплои, зрелые команды |
| **Release Candidate (RC)** | Промежуточная версия `v1.2.3-rc.1` перед стабильным релизом | Крупные релизы, много платформ, требующие бета-тестирования |
| **Hotfix** | Экстренный патч для production: ветка `hotfix/*`, bump только PATCH | Критические баги в продакшне |
| **Pre-release** | Версия с суффиксом (`v1.0.0-alpha.1`, `v1.0.0-beta.2`) | Публичное тестирование до стабильного релиза |
| **Snapshot** | Версия с метаданными (`v1.0.0+build.42`) для nightly-сборок | Ночные сборки, dev-окружения |
| **CalVer** | Календарное версионирование `YYYY.MM.PATCH` | Инфраструктурные инструменты, где дата важнее изменений |

**Важно:** Для компонентов **CI/CD Catalog** тег должен быть SemVer (`vX.Y.Z`). Pre-release версии (например, `v1.0.0-rc.1`) поддерживаются каталогом, но никогда не выбираются частичными версиями (`@1.2`) и `~latest` — только точным полным SemVer. CalVer для публикации в каталоге не подходит.

### Release Evidence

**Release Evidence** — автоматически генерируемый JSON-отчет, содержащий метаданные релиза для аудита и комплаенса. Включает:

- **Список коммитов** между предыдущим и текущим релизом
- **Результаты тестов** (пройдено/провалено)
- **SBOM** (состав зависимостей)
- **Аттестации сборки** (SLSA Provenance — где и как был собран артефакт)
- **Подписи** (Cosign/GPG)

Release Evidence автоматически привязывается к GitLab Release и доступен через API. Для ручного создания используйте `glab api`:

```bash
# Создание release evidence через API
curl --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" \
  --data '{
    "evidence": {
      "summary": "Release v1.2.3 passed all checks",
      "sha": "'"$CI_COMMIT_SHA"'"
    }
  }' \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/releases/$NEW_TAG/evidence"
```

### Инструментарий и современное состояние

С версии GitLab **16.0** основным инструментом является декларативное ключевое слово `release:`.
- **`release-cli`**: Устарел в GitLab **18.0**, запланировано удаление в **20.0**. Начиная с 18.4 по умолчанию используется **GitLab CLI (`glab`)** v1.58.0+. Для новых пайплайнов используйте встроенный `release:` или прямой вызов **GitLab Releases API**.
- **CI/CD Catalog**: Требует строгого соблюдения SemVer. Неподдерживаемые форматы тегов блокируют публикацию компонентов в каталоге.
- **Передача версии**: Для передачи вычисленной версии между этапами используется механизм `artifacts:reports:dotenv`.
- **OIDC (id_tokens)**: Используется для безопасной аутентификации во внешних системах и подписи релизных артефактов (например, через Sigstore).

## Практические сценарии

### Сценарий 1: Автоматизация через Shell-скрипт и блок `release:`

Классический подход для проектов, не использующих сторонние инструменты автоматизации.

#### Шаг 1: Анализ коммитов, генерация версии и SBOM

Задача анализирует историю Git и формирует переменные для создания тега, а также генерирует SBOM.

**Файл `templates/analyze_commit.yaml`:**

```yaml
variables:
  MAJOR_CHANGE_PATTERN: 'BREAKING\sCHANGE:'
  MINOR_CHANGE_PATTERN: '^feat(\(.*\))?!?:\s'
  PATCH_CHANGE_PATTERN: '^(fix|perf|refactor)(\(.*\))?!?:\s'
  RELEASE_NOTE_FILE: "RELEASE_NOTE.md"

analyze_commit:
  image: alpine/git
  stage: prepare_release
  script:
    # 1. Получение последнего тега (или v0.0.0 если тегов нет)
    - LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
    
    # 2. Определение уровня изменений
    - COMMITS=$(git log --oneline $LAST_TAG..$CI_COMMIT_SHA)
    - VERSION_CHANGE=""
    - |
      if echo "$COMMITS" | grep -qE "$MAJOR_CHANGE_PATTERN"; then
        VERSION_CHANGE="major"
      elif echo "$COMMITS" | grep -qE "$MINOR_CHANGE_PATTERN"; then
        VERSION_CHANGE="minor"
      elif echo "$COMMITS" | grep -qE "$PATCH_CHANGE_PATTERN"; then
        VERSION_CHANGE="patch"
      else
        echo "No version change detected."
        exit 0
      fi

    # 3. Вычисление нового тега
    - MAJOR=$(echo "$LAST_TAG" | cut -d'v' -f2 | cut -d'.' -f1)
    - MINOR=$(echo "$LAST_TAG" | cut -d'.' -f2)
    - PATCH=$(echo "$LAST_TAG" | cut -d'.' -f3)
    - |
      case "$VERSION_CHANGE" in
        major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
        minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
        patch) PATCH=$((PATCH + 1)) ;;
      esac
    - NEW_TAG="v${MAJOR}.${MINOR}.${PATCH}"
    - echo "NEW_TAG=$NEW_TAG" >> variables.env

    # 4. Генерация Release Notes
    - git log --pretty="* %s (%h)" ${LAST_TAG}..HEAD > $RELEASE_NOTE_FILE

    # 5. Генерация SBOM (используя syft)
    - wget https://raw.githubusercontent.com/anchore/syft/main/install.sh -O install_syft.sh
    - sh install_syft.sh -b /usr/local/bin
    - syft . -o cyclonedx-json=sbom.json

  artifacts:
    paths: [$RELEASE_NOTE_FILE]
    reports:
      dotenv: variables.env
      cyclonedx: sbom.json
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

#### Шаг 2: Создание релиза через декларативный блок

Использование встроенного функционала GitLab для создания официального релиза с привязкой SBOM.

**Файл `.gitlab-ci.yml`:**

```yaml
include:
  - local: 'templates/analyze_commit.yaml'

stages:
  - prepare_release
  - release
  - publish

create_release:
  stage: release
  # release-cli устарел в GitLab 18.0 и будет удален в 20.0.
  # Для GitLab 18.4+ встроенный `release:` работает через glab без дополнительного образа.
  image: registry.gitlab.com/gitlab-org/release-cli:latest
  needs:
    - job: analyze_commit
      artifacts: true
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  release:
    name: 'Release $NEW_TAG'
    description: './RELEASE_NOTE.md'
    tag_name: '$NEW_TAG'
    ref: '$CI_COMMIT_SHA'
    assets:
      links:
        - name: "Container Image"
          url: "$CI_REGISTRY_IMAGE:$NEW_TAG"
        - name: "SBOM Report"
          url: "${CI_PROJECT_URL}/-/jobs/${CI_JOB_ID}/artifacts/file/sbom.json"
```

#### Шаг 3: Публикация артефактов

После создания тега запускается этап публикации.

```yaml
publish_image:
  stage: publish
  image: docker:29.8
  services:
    - docker:29.8-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:$NEW_TAG .
    - docker push $CI_REGISTRY_IMAGE:$NEW_TAG
  rules:
    - if: $NEW_TAG # Используется переменная из dotenv
```

### Сценарий 2: Использование semantic-release (Рекомендуемый)

Для профессиональной автоматизации рекомендуется использовать **semantic-release**. Он полностью исключает ручные шаги и риск человеческой ошибки.

```yaml
release_automated:
  stage: release
  image: node:24-alpine
  before_script:
    - apk add --no-cache git
    - npm install -g semantic-release @semantic-release/gitlab @semantic-release/git
  script:
    - semantic-release
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Пример конфигурации `.releaserc.json`:**
```json
{
  "branches": ["main"],
  "plugins": [
    "@semantic-release/commit-analyzer",
    "@semantic-release/release-notes-generator",
    "@semantic-release/gitlab",
    [
      "@semantic-release/git",
      {
        "assets": ["package.json", "CHANGELOG.md"],
        "message": "chore(release): ${nextRelease.version} [skip ci]\n\n${nextRelease.notes}"
      }
    ]
  ]
}
```

### Сценарий 3: Релиз для CI/CD Catalog (GitLab 17.x+)

Специфические требования к публикации компонентов в каталоге.

```yaml
publish_catalog_component:
  stage: release
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/ # Строгий SemVer
  release:
    name: 'Component Release $CI_COMMIT_TAG'
    tag_name: '$CI_COMMIT_TAG'
    description: 'Automatic release for CI/CD Catalog'
```

### Сценарий 4: Подпись релизов через Cosign (Sigstore)

Подпись артефактов — обязательный шаг для обеспечения безопасности цепочки поставок (EU CRA, SLSA L3). Подробная теория — в **[Sigstore](../../../Security/Tools/sigstore.md)**.

```yaml
sign_release:
  stage: release
  image: registry.gitlab.com/security-products/cosign:latest
  variables:
    COSIGN_YES: "true"
  before_script:
    - apk add --no-cache docker-cli
  script:
    # 1. Подпись Docker-образа (keyless через OIDC GitLab CI)
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker pull $CI_REGISTRY_IMAGE:$NEW_TAG
    - cosign sign $CI_REGISTRY_IMAGE:$NEW_TAG

    # 2. Аттестация SBOM (привязка к образу)
    - cosign attest --predicate sbom.json --type cyclonedx $CI_REGISTRY_IMAGE:$NEW_TAG

    # 3. Подпись Release Evidence
    - cosign sign-blob --yes --bundle release-evidence.bundle release-evidence.json

    # 4. Верификация подписи (проверка работоспособности)
    - cosign verify $CI_REGISTRY_IMAGE:$NEW_TAG
  rules:
    - if: $NEW_TAG
```

**Валидация:** `cosign verify` должен завершиться успешно с выводом `The following checks were performed`. При ошибке `no matching signatures` — проверьте, что реестр поддерживает OCI 1.1 Referrers API.

**Связанные файлы:**
- **[Подпись артефактов](../../../Security/Supply_Chain_Security/artifact_signing.md)** — теория и форматы
- **[Docker Security](../../../Docker/Docker_security/overview.md)** — SBOM, сканирование, подпись

### Сценарий 5: GitLab Releases API через curl (замена release-cli)

Начиная с GitLab 18.4, блок `release:` по умолчанию использует **GitLab CLI (`glab`)** v1.58.0+. Прямой вызов API остаётся универсальным вариантом для сложных сценариев.

```yaml
create_release_api:
  stage: release
  image: alpine:3.24
  before_script:
    - apk add --no-cache curl jq
  script:
    # 1. Создание тега через API
    - |
      curl --fail --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" \
        --header "Content-Type: application/json" \
        --data "{
          \"tag_name\": \"$NEW_TAG\",
          \"ref\": \"$CI_COMMIT_SHA\"
        }" \
        "$CI_API_V4_URL/projects/$CI_PROJECT_ID/repository/tags"

    # 2. Создание GitLab Release с активами
    - |
      RELEASE_DESCRIPTION=$(cat <<EOF
      ## What's Changed
      $(cat RELEASE_NOTE.md)

      ## Installation
      \`\`\`bash
      docker pull $CI_REGISTRY_IMAGE:$NEW_TAG
      \`\`\`
      EOF
      )

      curl --fail --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" \
        --header "Content-Type: application/json" \
        --data "{
          \"tag_name\": \"$NEW_TAG\",
          \"name\": \"Release $NEW_TAG\",
          \"description\": $(echo "$RELEASE_DESCRIPTION" | jq -Rs .),
          \"assets\": {
            \"links\": [
              {
                \"name\": \"Container Image\",
                \"url\": \"$CI_REGISTRY_IMAGE:$NEW_TAG\",
                \"link_type\": \"package\"
              },
              {
                \"name\": \"SBOM Report\",
                \"url\": \"${CI_PROJECT_URL}/-/jobs/${CI_JOB_ID}/artifacts/file/sbom.json\",
                \"link_type\": \"other\"
              }
            ]
          }
        }" \
        "$CI_API_V4_URL/projects/$CI_PROJECT_ID/releases"
  rules:
    - if: $NEW_TAG
```

**Преимущества API перед release-cli:**
- Не требует дополнительного Docker-образа (registry.gitlab.com/gitlab-org/release-cli)
- Полный контроль над HTTP-запросами и обработкой ошибок
- Поддержка расширенных возможностей ( milestone, released_at, assets)
- Возможность создания релизов в нескольких проектах одновременно

### Сценарий 6: Multi-project release (релиз из нескольких проектов)

Когда артефакты собираются в разных проектах, но релиз публикуется централизованно.

```yaml
cross_project_release:
  stage: release
  image: alpine:3.24
  before_script:
    - apk add --no-cache curl jq
  script:
    # Получение токена доступа к целевому проекту
    - |
      TARGET_PROJECT_ID=$(curl --fail --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" \
        "$CI_API_V4_URL/projects?search=$TARGET_PROJECT" | jq '.[0].id')

    # Публикация релиза в целевом проекте
    - |
      curl --fail --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" \
        --header "Content-Type: application/json" \
        --data "{
          \"tag_name\": \"$NEW_TAG\",
          \"name\": \"Release $NEW_TAG\",
          \"description\": \"Cross-project release\",
          \"assets\": {
            \"links\": [
              {
                \"name\": \"Backend Image\",
                \"url\": \"$CI_REGISTRY_IMAGE:$NEW_TAG\"
              },
              {
                \"name\": \"Frontend Build\",
                \"url\": \"${CI_PROJECT_URL}/-/jobs/${CI_JOB_ID}/artifacts/file/dist.zip\"
              }
            ]
          }
        }" \
        "$CI_API_V4_URL/projects/$TARGET_PROJECT_ID/releases"
  rules:
    - if: $NEW_TAG
```

**Важно:** `CI_JOB_TOKEN` имеет ограниченные права. Для записи в другой проект необходимо добавить вызывающий проект в **Inbound Allowlist** целевого проекта (**Settings > CI/CD > Token Access**) или использовать PAT с правами `api`.

## Устранение неполадок (Troubleshooting)

### Типичные ошибки

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **`Tag already exists`** | Пайплайн пытается создать тег, который уже есть в Git | Проверьте логику вычисления версии; удалите конфликтующий тег вручную (осторожно с историей) |
| **`Validation failed: SemVer required`** | Ошибка при публикации в CI/CD Catalog | Убедитесь, что формат тега строго соответствует `vX.Y.Z` (без суффиксов) |
| **`403 Forbidden` при создании релиза** | Недостаточно прав у `CI_JOB_TOKEN` | Проверьте настройки «Token Access» в проекте или используйте персональный токен с правами `api` |
| **`Release Evidence missing`** | JSON-отчет не был сформирован | Проверьте, что все задачи стадии `test` завершились успешно и сгенерировали отчеты |
| **`release-cli: command not found`** | Устаревший release-cli удален в GitLab 20.0 | Используйте встроенный `release:` или прямой вызов Releases API; для CLI — `glab` v1.58.0+ |
| **`dotenv: file too large`** | Файл `variables.env` превышает 5 МБ | Уменьшите количество передаваемых переменных или используйте артефакты для передачи данных |
| **Protected tag error** | Тег не может быть создан из-за настроек защиты | Создайте тег вручную через UI или временно снимите защиту тега |
| **`release:` ignored** | Блок `release:` не выполняется | Проверьте, что `rules` не блокируют задачу и что `tag_name` указан явно |
| **`CI_JOB_TOKEN` expired** | Токен устарел (срок жизни ~1 hour) | Используйте `CI_JOB_TOKEN` внутри pipeline; для долгоживущих операций — PAT |
| **Rate limit exceeded** | Превышен лимит API-запросов (60/min) | Пакетируйте операции, используйте batch-эндпоинты |

### Инструменты диагностики

-   **Merged YAML**: В Pipeline Editor проверьте, как интерполируются переменные версии.
-   **API Dry Run**: Используйте `curl` для проверки создания релиза через GitLab API до внесения изменений в YAML.
-   **Release API**: Просмотрите список релизов проекта через API:
    ```bash
    curl --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" \
      "$CI_API_V4_URL/projects/$CI_PROJECT_ID/releases" | jq '.[].tag_name'
    ```
-   **Tag API**: Проверьте существование тега:
    ```bash
    curl --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" \
      "$CI_API_V4_URL/projects/$CI_PROJECT_ID/repository/tags/$TAG_NAME"
    ```

### Диагностический скрипт

Полная проверка всех компонентов релиза:

```bash
#!/bin/bash
set -euo pipefail

echo "=== Release Diagnostics ==="
echo "--- Last Tag ---"
LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "none")
echo "Last tag: $LAST_TAG"

echo "--- Commits Since Tag ---"
if [ "$LAST_TAG" != "none" ]; then
  git log --oneline "$LAST_TAG..HEAD" | head -20
fi

echo "--- Version Calculation ---"
if [ "$LAST_TAG" != "none" ]; then
  MAJOR=$(echo "$LAST_TAG" | cut -d'v' -f2 | cut -d'.' -f1)
  MINOR=$(echo "$LAST_TAG" | cut -d'.' -f2)
  PATCH=$(echo "$LAST_TAG" | cut -d'.' -f3 | cut -d'-' -f1)
  echo "MAJOR=$MAJOR MINOR=$MINOR PATCH=$PATCH"
fi

echo "--- Tag Protection ---"
curl --fail --silent --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/protected_tags" 2>/dev/null | jq '.[].name' || echo "No protected tags"

echo "--- Existing Releases ---"
curl --fail --silent --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/releases?per_page=5" 2>/dev/null | jq '.[].tag_name' || echo "No releases"

echo "--- CI_JOB_TOKEN Scopes ---"
curl --fail --silent --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" \
  "$CI_API_V4_URL/personal_access_tokens/self" 2>/dev/null | jq '.scopes' || echo "Cannot check token scopes (expected for CI_JOB_TOKEN)"

echo "=== Diagnostics Complete ==="
```

## Дополнительная информация

### Постоянные ссылки на активы (Permanent Links)

Для стабильного доступа к артефактам используйте формат ссылок, привязанных к тегу. В блоке `release:assets:links` можно указывать внешние URL или ссылки на Package Registry.

### Календарное версионирование (CalVer)

В проектах, где дата выпуска важнее типа изменений (например, Ubuntu, Terraform провайдеры), используется **CalVer** (`YYYY.MM.PATCH`).
**Внимание:** Не используйте CalVer для компонентов **CI/CD Catalog**, так как каталог требует строгого соответствия SemVer.

### См. также

- **[Шаблоны и стандарты коммитов](../../../Git/git_commit_template.md)** — подробное описание Conventional Commits.
- **[Подпись артефактов (Cosign/Sigstore)](../../../Security/Tools/sigstore.md)** — теория и практика ключless-подписи.

### Безопасность и политики

- **Protected Tags**: Всегда настраивайте защиту тегов (`Settings -> Repository -> Protected Tags`), чтобы только владельцы (Maintainers) могли создавать релизные метки. Через API:
  ```bash
  # Настройка защиты тега через API
  curl --request POST --header "PRIVATE-TOKEN: $PAT_TOKEN" \
    --data "name=v*" \
    "$CI_API_V4_URL/projects/$CI_PROJECT_ID/protected_tags"
  ```
- **GitLab Releases API**: При необходимости сложной логики (например, создание релиза в нескольких проектах одновременно) используйте прямой вызов API через `curl`. См. **Сценарий 5** выше.
- **CI_JOB_TOKEN**: Токен автоматически предоставляется каждой задаче. Для операций с релизами в рамках одного проекта достаточно прав токена. Для cross-project операций настройте **Inbound Allowlist** (**Settings > CI/CD > Token Access**). С GitLab 18.3+ доступны **Fine-grained Permissions** для тонкой настройки.
- **Подпись артефактов**: Используйте **[Cosign](../../../Security/Tools/sigstore.md)** (keyless-режим через OIDC) для подписи Docker-образов и бинарных файлов. См. **Сценарий 4** выше.
- **Audit Logging**: GitLab фиксирует все операции с релизами в Audit Events. Просмотрите через **Security > Audit Events** или API:
  ```bash
  curl --header "PRIVATE-TOKEN: $PAT_TOKEN" \
    "$CI_API_V4_URL/projects/$CI_PROJECT_ID/audit_events?entity_type=Release" | jq '.[] | {action, created_at, details}'
  ```

### Откат релиза

Процедура отката зависит от стадии, на которой обнаружена проблема.

**Этап 1: Отмена публикации (до завершения релиза)**

Если пайплайн ещё выполняется и релиз не опубликован:

```bash
# Отмена запущенного пайплайна
glab ci cancel $PIPELINE_ID

# Или отмена конкретной задачи
glab api --method POST "projects/$CI_PROJECT_ID/jobs/$JOB_ID/cancel"
```

**Этап 2: Удаление GitLab Release (тег остаётся)**

```bash
# Удаление релиза через API (тег и коммит сохраняются)
curl --request DELETE --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/releases/$TAG_NAME"
```

**Этап 3: Удаление тега (полный откат)**

```bash
# Удаление тега из Git
git tag -d $TAG_NAME
git push origin :refs/tags/$TAG_NAME

# Или через API
curl --request DELETE --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/repository/tags/$TAG_NAME"
```

**Этап 4: Rollback деплоя**

Откат деплоя — отдельная операция от отката релиза. См. **[Проверки здоровья и откат развертывания](../../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)** и **[Сравнение стратегий развертывания](../../../CI-CD/Deployment_Strategies/comparison.md)**.

**Важно:** Удаление тега не удаляет Docker-образ из реестра. Для полного отката необходимо также удалить образ:

```bash
# Удаление образа из Container Registry
curl --request DELETE --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/packages/container/recipes/$TAG_NAME"
```

### Edge cases и ограничения

| Ограничение | Описание | Решение |
| :--- | :--- | :--- |
| **Dotenv file > 5 MB** | Файл `variables.env` не может превышать 5 МБ | Передавайте данные через артефакты или API, а не через dotenv |
| **Dotenv в rules** | Переменные из `artifacts:reports:dotenv` **недоступны** в блоке `rules` | Используйте предопределённые переменные GitLab или `workflow:rules` |
| **release: + when: manual** | `release:` не выполняется при ручном запуске, пока не подтверждён | Убедитесь, что `when: manual` установлен корректно и пользователь нажал "Play" |
| **Nested tags** | Теги с вложенными namespace (`release/v1.0.0`) не поддерживаются `release:` | Используйте плоские теги (`v1.0.0`) |
| **Duplicate tag push** | Если тег уже существует, push нового тега с тем же именем невозможен | Используйте уникальные имена или удалите старый тег |
| **API rate limit** | 60 запросов в минуту для `CI_JOB_TOKEN` | Пакетируйте операции, кэшируйте результаты |
| **release-cli image size** | `release-cli:latest` — ~200 MB Docker image | Для простых релизов используйте API (см. Сценарий 5) |
| **Pre-release SemVer** | CI/CD Catalog отвергает теги с суффиксами (`-rc.1`) | Для каталога используйте строгий SemVer без суффиксов |
| **CalVer + CI/CD Catalog** | CalVer (`YYYY.MM.PATCH`) не соответствует SemVer-требованиям каталога | Используйте SemVer для каталоговых компонентов |
| **Multi-project token scope** | `CI_JOB_TOKEN` не имеет прав на запись в другие проекты по умолчанию | Добавьте проект в Inbound Allowlist или используйте PAT |
