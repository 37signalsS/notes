# Семантическое Версионирование и Управление Релизами в GitLab CI

### 1.1. Генерация Тега Версии на основе Коммитов

Этот этап направлен на автоматическое определение новой версии (Major, Minor, Patch) на основе анализа сообщений коммитов, следующих соглашению Conventional Commits.

**Файл `templates/release/analyze_commit.yaml`:**
```yaml
variables:
  MAJOR_CHANGE_PATTERN: 'BREAKING\sCHANGE:'
  MINOR_CHANGE_PATTERN: '^feat(\(.*\))?!?:\s'
  PATCH_CHANGE_PATTERN: '^(fix|perf|refactor)(\(.*\))?!?:\s'
  RELEASE_NOTE_FILE: "RELEASE_NOTE.md"
  CHANGES_PATTERN: '^(feat|fix|docs|style|refactor|perf|test|chore|wip)(\(.*\))?(!)?:\s?.+$'

stages:
  - prepare_release

.generate_release_tag: &generate_release_tag
  - >-
    if [ -z "$LAST_TAG" ]; then
      echo "No previous tag found, using the full commit history."
      COMMITS=$(git log --oneline)
    else
      echo "Analyzing commits since $LAST_TAG..."
      COMMITS=$(git log --oneline $LAST_TAG..$CI_COMMIT_SHA)
    fi
  - echo "Commits to analyze ${COMMITS}"
  - VERSION_CHANGE=""
  - >-
    if echo "$COMMITS" | grep -qE "$MAJOR_CHANGE_PATTERN"; then
      VERSION_CHANGE="major"
    elif echo "$COMMITS" | grep -qE "$MINOR_CHANGE_PATTERN"; then
      VERSION_CHANGE="minor"
    elif echo "$COMMITS" | grep -qE "$PATCH_CHANGE_PATTERN"; then
      VERSION_CHANGE="patch"
    fi
  - echo "Change type defined $VERSION_CHANGE"
  - >-
    if echo "$LAST_TAG" | grep -E "^v[0-9]+\.[0-9]+\.[0-9]+" >/dev/null; then
      echo "Valid previous tag found: $LAST_TAG"
      MAJOR=$(echo "$LAST_TAG" | cut -d 'v' -f 2 | cut -d '.' -f 1)
      MINOR=$(echo "$LAST_TAG" | cut -d '.' -f 2)
      PATCH=$(echo "$LAST_TAG" | cut -d '.' -f 3)
    else
      echo "No valid previous tag found or format is incorrect. Starting from 1.0.0"
      MAJOR=1; MINOR=0; PATCH=0
    fi
  - >-
    case "$VERSION_CHANGE" in
    major)
      MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
    minor)
      MINOR=$((MINOR + 1)); PATCH=0 ;;
    patch)
      PATCH=$((PATCH + 1)) ;;
    *)
    echo "No version change detected stopping the release." exit 0 ;;
    esac
  - NEW_TAG="v${MAJOR}.${MINOR}.${PATCH}"
  - echo "New tag $NEW_TAG"
  - echo "NEW_TAG=$NEW_TAG" >> variables.env

.generate_release_note: &generate_release_note
  - >-
    if [ -z "$LAST_TAG" ]; then
      RANGE=""
    else
      RANGE="$LAST_TAG..$CI_COMMIT_SHA"
    fi
  - echo "# Release Notes" > "$RELEASE_NOTE_FILE"
  - echo "" >> "$RELEASE_NOTE_FILE"
  - |-
    add_commit_to_release_note() {
        commit_data="$1"
        commit_hash=$(echo "$commit_data" | sed -n '1p')
        commit_author=$(echo "$commit_data" | sed -n '2p')
        commit_date=$(echo "$commit_data" | sed -n '3p')
        echo "## Commit: $commit_hash" >> "$RELEASE_NOTE_FILE"
        echo "**Author:** $commit_author" >> "$RELEASE_NOTE_FILE"
        echo "" >> "$RELEASE_NOTE_FILE"
        echo "**Date:** $commit_date" >> "$RELEASE_NOTE_FILE"
        echo "" >> "$RELEASE_NOTE_FILE"
        echo "**Updates:**" >> "$RELEASE_NOTE_FILE"
        echo "" >> "$RELEASE_NOTE_FILE"
        messages=$(echo "$commit_data" | sed '1,3d')
        IFS=$'\n'
        for message in $messages; do
            if echo "$message" | grep -Eq "$CHANGES_PATTERN"; then
                echo "- $message" >> "$RELEASE_NOTE_FILE"
            else
                echo "> $message" >> "$RELEASE_NOTE_FILE"
            fi
        done
        echo "" >> "$RELEASE_NOTE_FILE"
    }
  - |-
    process_git_log() {
        range="$1"
        commit_data=""
        git log "$range" --pretty=format:"%H%n%an <%ae>%n%ad%n%B%n<ENDCOMMIT>" | while IFS= read -r line || [ -n "$line" ]; do
            if [ "$line" = "<ENDCOMMIT>" ]; then
                add_commit_to_release_note "$(echo -e "$commit_data")"
                commit_data=""
            else
                commit_data="${commit_data}${line}\n"
            fi
        done
    }
  - process_git_log "$RANGE"

analyze_commit:
  image:
    name: alpine/git
    entrypoint: [ '' ]
  stage: prepare_release
  script:
    - apk add --no-cache curl jq
    - echo "Analyze commit..."
    - LAST_TAG=$(git describe --tags --abbrev=0 $(git rev-list --tags --max-count=1) 2>/dev/null || echo "")
    - *generate_release_tag
    - *generate_release_note
  variables:
    SHELL: '/bin/bash'
  artifacts:
    paths:
      - $RELEASE_NOTE_FILE
    reports:
      dotenv: variables.env
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: on_success
    - when: never
```

**Пояснения:**
*   **Логика версионирования:** Анализирует сообщения коммитов. Если найден `BREAKING CHANGE`, увеличивается Major-версия. Если `feat:`, то Minor. Если `fix:`, `perf:` или `refactor:`, то Patch.
*   **Генерация тега:** Формируется новый тег вида `vX.Y.Z`.
*   **Генерация Release Note:** Создается файл `RELEASE_NOTE.md` с описанием изменений, сгруппированных по коммитам.
*   **Артефакты:** Задача сохраняет сгенерированный тег (через `dotenv`) и файл `RELEASE_NOTE.md` как артефакты для последующих задач.

Рекомендуется ознакомиться с [Conventional Commits](https://www.conventionalcommits.org/ru/v1.0.0-beta.4/) для понимания формата коммитов.

### 1.2. Создание Релиза в GitLab

После генерации тега и Release Note, GitLab CI может автоматически создать релиз в репозитории.

**Файл `templates/release/release.yaml`:**
```yaml
include:
  - local: templates/release/analyze_commit.yaml

stages:
  - prepare_release
  - release

release:
  stage: release
  needs:
    - job: analyze_commit
      artifacts: true
  image: registry.gitlab.com/gitlab-org/release-cli:latest
  script:
    - echo "Release with tag $NEW_TAG"
  release:
    name: 'Release $NEW_TAG'
    tag_name: '$NEW_TAG'
    description: RELEASE_NOTE.md
    ref: '$CI_COMMIT_SHA'
    assets:
      links:
        - name: "GitLab Registry Image"
          url: "$CI_REGISTRY_IMAGE:$NEW_TAG"
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
    - when: never
```

**Пояснения:**
*   **`include`**: Включает предыдущую джобу `analyze_commit` для использования её артефактов.
*   **`needs`**: Указывает, что задача `release` зависит от `analyze_commit` и требует её артефактов.
*   **`image`**: Используется официальный образ `release-cli` от GitLab.
*   **`release` блок**: Специальный блок для создания релизов в GitLab.
    *   `name`, `tag_name`, `description`: Используют переменные и файл `RELEASE_NOTE.md`, сгенерированные на предыдущем шаге.
    *   `assets.links`: Добавляет ссылку на образ в Container Registry, связанный с этим релизом.
*   **`rules`**: Релиз создается вручную при коммитах в основную ветку.

### 1.3. Публикация Docker-образов с Тегами Релизов

После создания семантического тега, необходимо тегировать Docker-образ этим тегом и отправить его в реестр.

**Файл `templates/publish/docker.yaml`:**
```yaml
stages:
  - prepare_publish
  - publish

.publish_latest: &publish_latest
  stage: prepare_publish
  script:
    - echo "Tagging image $CI_COMMIT_SHA as latest..."
    - docker tag $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA $CI_REGISTRY_IMAGE:latest
    - docker push $CI_REGISTRY_IMAGE:latest
  rules:
    - if: $CI_COMMIT_TAG
      when: on_success
    - when: never

.publish_release_tag: &publish_release_tag
  stage: prepare_publish
  script:
    - echo "Tagging image $CI_COMMIT_SHA as $CI_COMMIT_TAG..."
    - docker tag $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA $CI_REGISTRY_IMAGE:$CI_COMMIT_TAG
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_TAG
  rules:
    - if: $CI_COMMIT_TAG
      when: on_success
    - when: never

.publish_stable: &publish_stable
  stage: publish
  script:
    - echo "Tagging image $CI_COMMIT_SHA as stable..."
    - docker tag $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA $CI_REGISTRY_IMAGE:stable
    - docker push $CI_REGISTRY_IMAGE:stable
  rules:
    - if: $CI_COMMIT_TAG
      when: on_success
    - when: never
```

**Пояснения:**
*   Эти задачи выполняются после того, как в репозитории создан новый тег (`$CI_COMMIT_TAG`).
*   **`.publish_latest`**: Тегирует образ с хешем коммита как `latest`.
*   **`.publish_release_tag`**: Тегирует образ с сгенерированным семантическим тегом (`$CI_COMMIT_TAG`).
*   **`.publish_stable`**: (Опционально) Тегирует образ как `stable`, если используется такая стратегия.

### 1.4. Конечный Деплой с Семантическим Тегом

Теперь, когда образ имеет стабильный семантический тег, его можно безопасно деплоить в производственное окружение.

**Пример измененной джобы деплоя в `prod`:**
```yaml
# templates/deploy/kubernetes.yaml (обновлено)
deploy-prod:
  extends: .deploy-k8s-template
  variables:
    DOCKER_TAG: $CI_COMMIT_TAG # Используем семантический тег
  rules:
    - if: $CI_COMMIT_TAG
      when: manual # Деплой в прод только при наличии тега и вручную
    - when: never
  environment:
    name: prod
    action: start
    kubernetes:
      namespace: prod
```

**Пояснения:**
*   Задача `deploy-prod` теперь запускается только при наличии `CI_COMMIT_TAG`, что гарантирует развертывание релизной версии.
*   `DOCKER_TAG: $CI_COMMIT_TAG`: Обеспечивает, что в манифестах Kubernetes будет использован именно релизный тег образа.
*   Деплой в прод остается ручным, что является распространенной практикой для контроля над выпуском.

```