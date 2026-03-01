# Управление релизами и семантическое версионирование

## Определения

- **Семантическое Версионирование (SemVer)**: Cтандарт версионирования ПО в формате `MAJOR.MINOR.PATCH`, где изменения отражают характер правок: `MAJOR` для обратно несовместимых изменений, `MINOR` для новой функциональности и `PATCH` для исправлений ошибок.
- **Conventional Commits**: Соглашение о форматировании сообщений коммитов, которое придает им машиночитаемый смысл. Формат `type(scope): description` позволяет автоматически определять тип изменений (например, `feat:` для новой функции, `fix:` для исправления, `BREAKING CHANGE:` для ломающих изменений).
- **Управление релизами в CI/CD**: Процесс автоматизации создания, тегирования и развертывания новых версий ПО на основе событий в системе контроля версий. В GitLab это реализуется с помощью `release-cli` и специальных ключевых слов в `.gitlab-ci.yml`.

## Основные концепции

#### Философия автоматизированного релиза

В основе подхода лежит строгая дисциплина в именовании коммитов (Conventional Commits). Это позволяет CI/CD-пайплайну автоматически анализировать историю изменений и принимать решения о следующем номере версии по правилам SemVer.

Весь процесс делится на четыре логических этапа:

1. **Анализ**: Пайплайн анализирует коммиты с момента последнего релиза (тега).
2. **Версионирование**: На основе анализа определяется, какую часть версии (`MAJOR`, `MINOR` или `PATCH`) нужно увеличить, и генерируется новый тег.
3. **Создание релиза**: В GitLab создается формальный релиз, к которому прикрепляются описание изменений (release notes) и другие артефакты.
4. **Публикация и развертывание**: Собранные артефакты (например, Docker-образы) тегируются новой версией и развертываются в нужные окружения.

Ключевым инструментом в этом процессе является **`release-cli`** от GitLab (актуальная версия **0.24.0** на 2026 год), а для передачи данных между этапами используется механизм артефактов **`artifacts:reports:dotenv`**.

**Важно:** Начиная с GitLab 17, release-cli находится в режиме maintenance. Для новых проектов рассмотрите использование [GitLab Releases API](https://docs.gitlab.com/ee/api/releases/) напрямую или декларативный блок `release:` в `.gitlab-ci.yml`.

## Практические сценарии

#### Сценарий: Полный цикл автоматизации релиза

Этот сценарий показывает, как настроить пайплайн, который автоматически определяет версию, создает релиз и публикует Docker-образ.

##### Шаг 1: Анализ коммитов и генерация версии

Первая задача анализирует историю Git, определяет тип изменений и генерирует новый тег версии, а также описание релиза.

**Пример (`templates/analyze_commit.yaml`):**

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
    # 1. Получаем последний тег
    - LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
    
    # 2. Определяем диапазон коммитов для анализа
    - |
      if [ -z "$LAST_TAG" ]; then
        echo "No previous tag found, analyzing full history."
        COMMITS=$(git log --oneline)
      else
        echo "Analyzing commits since $LAST_TAG..."
        COMMITS=$(git log --oneline $LAST_TAG..$CI_COMMIT_SHA)
      fi
    
    # 3. Определяем уровень изменений (major, minor, patch)
    - VERSION_CHANGE=""
    - |
      if echo "$COMMITS" | grep -qE "$MAJOR_CHANGE_PATTERN"; then
        VERSION_CHANGE="major"
      elif echo "$COMMITS" | grep -qE "$MINOR_CHANGE_PATTERN"; then
        VERSION_CHANGE="minor"
      elif echo "$COMMITS" | grep -qE "$PATCH_CHANGE_PATTERN"; then
        VERSION_CHANGE="patch"
      else
        echo "No version change detected. Stopping release."
        exit 0
      fi

    # 4. Вычисляем новый тег версии
    - |
      if echo "$LAST_TAG" | grep -E "^v[0-9]+\.[0-9]+\.[0-9]+$" >/dev/null; then
        MAJOR=$(echo "$LAST_TAG" | cut -d'v' -f2 | cut -d'.' -f1)
        MINOR=$(echo "$LAST_TAG" | cut -d'.' -f2)
        PATCH=$(echo "$LAST_TAG" | cut -d'.' -f3)
      else
        MAJOR=1; MINOR=0; PATCH=0
      fi
    - |
      case "$VERSION_CHANGE" in
        major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
        minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
        patch) PATCH=$((PATCH + 1)) ;;
      esac
    - NEW_TAG="v${MAJOR}.${MINOR}.${PATCH}"
    - echo "New tag determined: $NEW_TAG"
    - echo "NEW_TAG=$NEW_TAG" >> variables.env

    # 5. Генерируем Release Notes из коммитов
    - git log --pretty="* %s (%h) by %an" ${LAST_TAG}..HEAD > $RELEASE_NOTE_FILE

  artifacts:
    paths:
      - $RELEASE_NOTE_FILE
    reports:
      dotenv: variables.env # Передаем NEW_TAG в следующие задачи
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Пояснения:**

- Скрипт определяет последний тег, анализирует коммиты с тех пор и вычисляет новую SemVer-версию.
- Переменная `NEW_TAG` и файл `RELEASE_NOTE.md` сохраняются как артефакты.

##### Шаг 2: Создание релиза в GitLab

Следующая задача использует артефакты из предыдущей, чтобы создать формальный релиз в GitLab.

**Пример (`.gitlab-ci.yml`):**

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
      when: manual # Создание релиза запускается вручную для контроля
  release:
    name: 'Release $NEW_TAG'
    description: './RELEASE_NOTE.md' # Ссылка на артефакт
    tag_name: '$NEW_TAG'
    ref: '$CI_COMMIT_SHA'
    assets:
      links:
        - name: "GitLab Registry Image"
          url: "$CI_REGISTRY_IMAGE:$NEW_TAG"
```

**Пояснения:**

- **`needs`**: Гарантирует, что эта задача запустится после `analyze_commit` и получит доступ к ее артефактам.
- **`image: release-cli`**: Используется официальный образ для создания релизов.
- **`release:`**: Специальный блок, который декларативно описывает релиз, используя переменные и файлы из предыдущего шага.

##### Шаг 3: Публикация Docker-образа с тегом релиза

После создания релиза и соответствующего тега в Git, запускается пайплайн по этому тегу, который публикует Docker-образ.

**Пример (часть `.gitlab-ci.yml`):**

```yaml
publish_image:
  stage: publish
  image: docker:20.10
  services:
    - docker:20.10-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_TAG .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_TAG
    # Опционально: также тегируем как 'latest'
    - docker tag $CI_REGISTRY_IMAGE:$CI_COMMIT_TAG $CI_REGISTRY_IMAGE:latest
    - docker push $CI_REGISTRY_IMAGE:latest
  rules:
    - if: $CI_COMMIT_TAG # Задача запускается только для тегов
```

**Пояснения:**

- Эта задача выполняется только при создании нового тега (`if: $CI_COMMIT_TAG`).
- Она собирает Docker-образ и тегирует его семантической версией из переменной `$CI_COMMIT_TAG`.

##### Шаг 4: Развертывание релиза в Production

Финальный шаг — безопасное развертывание образа с семантическим тегом.

**Пример (часть `.gitlab-ci.yml`):**

```yaml
deploy_prod:
  stage: deploy
  # ... конфигурация для деплоя (kubectl, helm, etc.)
  script:
    - echo "Deploying version $CI_COMMIT_TAG to production"
    - helm upgrade --install my-app ./charts --set image.tag=$CI_COMMIT_TAG
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_TAG
      when: manual # Деплой в прод только по тегу и вручную
```

**Пояснения:**

- Задача запускается только для тегов и требует ручного подтверждения.
- Для развертывания используется переменная `$CI_COMMIT_TAG`, что гарантирует доставку именно релизной версии.

## Дополнительная информация

- **Спецификация Conventional Commits**: [www.conventionalcommits.org](https://www.conventionalcommits.org/ru/v1.0.0/)
- **Документация `release-cli`**: [docs.gitlab.com/ee/api/releases/#create-a-release](https://docs.gitlab.com/ee/api/releases/#create-a-release)
- **GitLab Releases API**: [docs.gitlab.com/ee/api/releases/](https://docs.gitlab.com/ee/api/releases/)

## Best Practices (2025-2026)

1. **Используйте декларативный блок `release:`**
   - Начиная с GitLab 16+, предпочтительнее использовать встроенный блок `release:` вместо release-cli
   - Упрощает конфигурацию и уменьшает зависимости

2. **Автоматическая генерация changelog**
   - Используйте `git log` с фильтрацией по тегам
   - Включайте только коммиты с `feat:`, `fix:`, `BREAKING CHANGE:`

3. **Ручное подтверждение для production**
   - Всегда используйте `when: manual` для создания релизов в production
   - Дайте возможность проверить changelog перед публикацией

4. **Связывание артефактов**
   - Добавляйте ссылки на Docker-образы в `assets.links`
   - Прикрепляйте бинарные файлы через `assets:links` или `artifacts`

5. **Защита тегов**
   - Используйте защищённые теги для production-релизов
   - Требуйте approval от maintainer перед созданием тега

6. **Интеграция с Package Registry**
   - Публикуйте пакеты в GitLab Package Registry
   - Связывайте релизы с соответствующими пакетами

## Альтернатива release-cli (GitLab 17+)

```yaml
# Современный подход с использованием декларативного release
create_release:
  stage: release
  image: alpine:3.19
  needs:
    - job: analyze_commit
      artifacts: true
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  before_script:
    - apk add --no-cache curl jq
  script:
    - |
      curl --request POST \
        --header "PRIVATE-TOKEN: ${GITLAB_ACCESS_TOKEN}" \
        --header "Content-Type: application/json" \
        --data "{
          \"name\": \"Release $NEW_TAG\",
          \"tag_name\": \"$NEW_TAG\",
          \"description\": \"$(cat RELEASE_NOTE.md | jq -Rs .)\",
          \"ref\": \"$CI_COMMIT_SHA\",
          \"assets\": {
            \"links\": [{
              \"name\": \"Docker Image\",
              \"url\": \"${CI_REGISTRY_IMAGE}:${NEW_TAG}\"
            }]
          }
        }" \
        "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/releases"
```
