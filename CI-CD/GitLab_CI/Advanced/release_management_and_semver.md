# Управление релизами и семантическое версионирование

## Определения

- **Семантическое версионирование (SemVer)** — стандарт версионирования в формате `MAJOR.MINOR.PATCH`. Является обязательным для ресурсов в **[CI/CD Catalog](../Reusable_Pipelines/ci_cd_catalog_components.md)**. Подробные правила — в **[Управлении артефактами](../../artifact_management.md)**.
- **Conventional Commits** — соглашение о форматировании сообщений коммитов (`feat:`, `fix:`, `refactor:`), обеспечивающее машиночитаемую историю для автоматизации SemVer. См. **[Шаблоны и стандарты коммитов](../../../Git/git_commit_template.md)**.
- **Release Evidence** — JSON-отчет (снимок состояния), содержащий метаданные релиза, результаты тестов и отчеты о безопасности. Используется для аудита и комплаенса.
- **GitLab Release** — объект в интерфейсе GitLab, связывающий тег, описание изменений (Changelog) и ссылки на активы. Создается через блок `release:` в `.gitlab-ci.yml`.
- **SBOM (Software Bill of Materials)** — декларативный список всех компонентов и зависимостей. В современных пайплайнах (2026+) генерация SBOM является обязательным шагом для обеспечения безопасности цепочки поставок (SLSA).

## Основные концепции

### Жизненный цикл релиза

Процесс автоматизации релиза в GitLab CI/CD включает следующие этапы:

1.  **Анализ истории** — пайплайн сканирует коммиты с момента последнего тега для определения следующей версии по правилам SemVer.
2.  **Генерация SBOM и аттестаций** — создание спецификации компонентов и доказательств сборки в доверенной среде.
3.  **Создание Git-тега** — создание уникальной метки версии в репозитории.
4.  **Генерация Release Notes** — автоматический сбор описания изменений на основе заголовков коммитов.
5.  **Сбор доказательств (Evidence)** — автоматическое создание снимка состояния проекта (результаты тестов, SBOM).
6.  **Ассоциация активов (Assets)** — привязка Docker-образов, бинарных файлов и документации к релизу через постоянные ссылки.
7.  **Публикация** — отправка артефактов в реестры (Container Registry, Package Registry).

### Инструментарий и современное состояние

С версии GitLab **16.0** основным инструментом является декларативное ключевое слово `release:`.
- **`release-cli`**: Начиная с версии **17.0**, инструмент находится в режиме поддержки. Рекомендуется использовать встроенные возможности YAML или прямой вызов **GitLab Releases API**.
- **CI/CD Catalog**: Требует строгого соблюдения SemVer. Неподдерживаемые форматы тегов блокируют публикацию компонентов в каталоге.
- **Передача версии**: Для передачи вычисленной версии между этапами используется механизм `artifacts:reports:dotenv`.
- **OIDC (id_tokens)**: Используется для безопасной аутентификации в облаках и подписи релизных артефактов (например, через Sigstore).

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
  image: docker:27.0
  services:
    - docker:27.0-dind
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
  image: node:22-alpine
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

## Устранение неполадок (Troubleshooting)

### Типичные ошибки
-   **`Tag already exists`**: Пайплайн пытается создать тег, который уже есть в Git. Решение: Проверьте логику вычисления версии или удалите конфликтующий тег вручную (осторожно с историей).
-   **`Validation failed: SemVer required`**: Ошибка при публикации в CI/CD Catalog. Решение: Убедитесь, что формат тега строго соответствует `vX.Y.Z`.
-   **`403 Forbidden` при создании релиза**: Недостаточно прав у `CI_JOB_TOKEN`. Решение: Проверьте настройки «Token Access» в проекте или используйте персональный токен с правами `api`.
-   **`Release Evidence missing`**: JSON-отчет не был сформирован. Решение: Проверьте, что все задачи стадии `test` завершились успешно и сгенерировали отчеты.

### Инструменты диагностики
-   **Merged YAML**: В Pipeline Editor проверьте, как интерполируются переменные версии.
-   **API Dry Run**: Используйте `curl` для проверки создания релиза через GitLab API до внесения изменений в YAML.

## Дополнительная информация

### Постоянные ссылки на активы (Permanent Links)

Для стабильного доступа к артефактам используйте формат ссылок, привязанных к тегу. В блоке `release:assets:links` можно указывать внешние URL или ссылки на Package Registry.

### Календарное версионирование (CalVer)

В проектах, где дата выпуска важнее типа изменений (например, Ubuntu, Terraform провайдеры), используется **CalVer** (`YYYY.MM.PATCH`).
**Внимание:** Не используйте CalVer для компонентов **CI/CD Catalog**, так как каталог требует строгого соответствия SemVer.

### Безопасность и политики

- **Protected Tags**: Всегда настраивайте защиту тегов (`Settings -> Repository -> Protected Tags`), чтобы только владельцы (Maintainers) могли создавать релизные метки.
- **GitLab Releases API**: При необходимости сложной логики (например, создание релиза в нескольких проектах одновременно) используйте прямой вызов API через `curl`.

### См. также

- **[Шаблоны и стандарты коммитов](../../../Git/git_commit_template.md)** — подробное описание Conventional Commits.
- **[Управление артефактами](../../artifact_management.md)** — общие схемы версионирования и SBOM.
- **[CI/CD Catalog Reference](../Reusable_Pipelines/ci_cd_catalog_reference.md)** — требования для компонентов каталога.
- **[Docker тегирование](../../../Docker/Docker_registries/image_versioning_and_tagging.md)** — стратегии именования образов.
