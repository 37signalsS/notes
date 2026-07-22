# Управление релизами и семантическое версионирование

## Определения

- **Семантическое версионирование (SemVer)** — стандарт версионирования программного обеспечения в формате `MAJOR.MINOR.PATCH`, где изменения отражают характер правок: `MAJOR` для обратно несовместимых изменений, `MINOR` для новой функциональности и `PATCH` для исправления ошибок.
- **Conventional Commits** — соглашение о форматировании сообщений коммитов, которое придает им машиночитаемый смысл. Формат `type(scope): description` позволяет автоматически определять тип изменений (например, `feat:` для новой функции, `fix:` для исправления, `BREAKING CHANGE:` для критических изменений).
- **Управление релизами в CI/CD** — процесс автоматизации создания, тегирования и развертывания новых версий ПО. В GitLab реализуется через декларативный блок `release:` в файле `.gitlab-ci.yml`.

## Основные концепции

### Философия автоматизированного релиза

В основе подхода лежит дисциплина именования коммитов. Это позволяет пайплайну автоматически анализировать историю изменений и вычислять следующий номер версии по правилам **SemVer**.

Процесс состоит из четырех этапов:

1. **Анализ** — пайплайн сканирует коммиты с момента последнего тега.
2. **Версионирование** — определяется уровень изменений (`MAJOR`, `MINOR` или `PATCH`) и генерируется новый тег.
3. **Создание релиза** — в GitLab создается объект **Release**, к которому прикрепляются описание изменений (**Release Notes**) и артефакты.
4. **Публикация** — собранные артефакты (например, Docker-образы) тегируются новой версией и отправляются в реестры.

### Инструментарий и современное состояние

С версии GitLab **16.0** основным инструментом является декларативное ключевое слово `release:`. Инструмент командной строки `release-cli` с версии **17.0** находится в режиме поддержки (**maintenance**). Для новых проектов рекомендуется использовать встроенные возможности GitLab или прямые вызовы **GitLab Releases API**.

Для передачи версии между задачами используется механизм `artifacts:reports:dotenv`.

## Практические сценарии

### Сценарий: Полный цикл автоматизации релиза

Этот пример демонстрирует пайплайн, который автоматически вычисляет версию на основе коммитов, создает релиз и публикует Docker-образ.

#### Шаг 1: Анализ коммитов и генерация версии

Задача анализирует историю Git и формирует переменные для следующего шага.

**Файл `templates/analyze_commit.yaml`:**

```yaml
variables:
  MAJOR_CHANGE_PATTERN: 'BREAKING\sCHANGE:'
  MINOR_CHANGE_PATTERN: '^feat(\(.*\))?!?:\s'
  PATCH_CHANGE_PATTERN: '^(fix|perf|refactor)(\(.*\))?!?:\s'
  RELEASE_NOTE_FILE: "RELEASE_NOTE.md"

stages:
  - prepare_release

analyze_commit:
  image: alpine/git
  stage: prepare_release
  script:
    # 1. Получение последнего тега
    - LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
    
    # 2. Определение диапазона коммитов
    - echo "Analyzing commits since $LAST_TAG..."
    - COMMITS=$(git log --oneline $LAST_TAG..$CI_COMMIT_SHA)
    
    # 3. Определение уровня изменений
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

    # 4. Вычисление нового тега
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

    # 5. Генерация Release Notes
    - git log --pretty="* %s (%h)" ${LAST_TAG}..HEAD > $RELEASE_NOTE_FILE

  artifacts:
    paths:
      - $RELEASE_NOTE_FILE
    reports:
      dotenv: variables.env
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

#### Шаг 2: Создание релиза через декларативный блок

Использование встроенного функционала GitLab для создания релиза.

**Файл `.gitlab-ci.yml`:**

```yaml
include:
  - local: 'templates/analyze_commit.yaml'

stages:
  - prepare_release
  - release

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
        - name: "Docker Image"
          url: "$CI_REGISTRY_IMAGE:$NEW_TAG"
```

#### Шаг 3: Публикация и развертывание

После создания тега запускается отдельный пайплайн для публикации артефактов.

```yaml
publish_image:
  stage: publish
  image: docker:24.0
  services:
    - docker:24.0-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_TAG .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_TAG
  rules:
    - if: $CI_COMMIT_TAG
```

## Дополнительная информация

### Рекомендации по автоматизации (2025-2026)

Для сложных проектов рекомендуется использовать специализированные инструменты, такие как **semantic-release**. Они полностью автоматизируют весь цикл: от анализа коммитов до публикации в реестры пакетов (npm, PyPI) и генерации **Changelog**.

В GitLab 16+ доступна встроенная генерация описания изменений:
```yaml
release:
  tag_name: $NEW_TAG
  description: 'Release created by CI/CD'
  changelog:
    generate: true # Автоматическая генерация на основе истории коммитов
```

Для обеспечения безопасности всегда используйте **Protected Tags**, чтобы только доверенные участники команды могли инициировать процесс создания релиза в продуктивных ветках.

### Альтернатива через API (GitLab 17+)

Если использование `release-cli` невозможно (например, из-за ограничений безопасности образов), можно использовать прямой вызов API через `curl`:

```yaml
create_release_api:
  stage: release
  image: alpine:3.21
  script:
    - |
      curl --request POST \
        --header "PRIVATE-TOKEN: ${GITLAB_API_TOKEN}" \
        --header "Content-Type: application/json" \
        --data "{\"name\": \"Release $NEW_TAG\", \"tag_name\": \"$NEW_TAG\", \"ref\": \"$CI_COMMIT_SHA\"}" \
        "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/releases"
```

### См. также

- **[Шаблоны и стандарты коммитов](../../../Git/git_commit_template.md)** — подробное описание Conventional Commits.
- **[Управление артефактами](../../artifact_management.md)** — схемы версионирования (SemVer, CalVer).
- **[CI/CD Catalog Reference](../Reusable_Pipelines/ci_cd_catalog_reference.md)** — требования SemVer для компонентов каталога.
- **[Docker тегирование](../../../Docker/Docker_registries/image_versioning_and_tagging.md)** — стратегии именования образов.
