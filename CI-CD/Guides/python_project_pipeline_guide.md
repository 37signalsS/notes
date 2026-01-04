# Проектирование комплексного CI/CD пайплайна для Python-приложений

## Определения

**Комплексный CI/CD пайплайн** — это автоматизированный процесс, который берет исходный код приложения, проводит его через этапы сборки, тестирования и развертывания в различные окружения (например, `development`, `staging`, `production`), следуя набору предопределенных правил и практик. Цель такого пайплайна — повысить скорость, надежность и безопасность доставки изменений до конечного пользователя.

Ключевые технологии, используемые в данном руководстве:

*   **[GitLab CI](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md):** Встроенный в GitLab инструмент для автоматизации, который запускает пайплайны на основе YAML-конфигурации (`.gitlab-ci.yml`) в репозитории.
*   **[Docker](../../Docker/docker_overview.md):** Платформа для контейнеризации приложений. Позволяет упаковать приложение со всеми его зависимостями в изолированный контейнер, который можно запускать где угодно.
*   **[Kaniko](../../Docker/Dockerfile/dockerfile_kaniko.md):** Инструмент для сборки Docker-образов внутри контейнера или Kubernetes-пода без использования Docker-демона, что повышает безопасность в CI/CD-окружениях.
*   **[Kubernetes](../../Kubernetes/kubernetes_overview.md):** Платформа для оркестрации контейнеризированных приложений. Управляет развертыванием, масштабированием и работой приложений.
*   **[Helm](../../Kubernetes/ToolsUtilities/helm.md):** Менеджер пакетов для Kubernetes. Упрощает развертывание и управление приложениями путем упаковки их в "чарты" — наборы предварительно сконфигурированных ресурсов.
*   **SAST (Static Application Security Testing):** Метод тестирования безопасности, который анализирует исходный код на предмет известных уязвимостей без его фактического запуска.

## Основные концепции

### 1. Архитектура и стратегии

#### Стратегия ветвления (Git Flow)
*   **`feature-*` ветки:** Вся разработка (новые функции, исправления) ведется в отдельных ветках.
*   **`develop` ветка:** Основная ветка для разработки. Feature-ветки сливаются в `develop` через Merge Request'ы (с обязательным код-ревью).
*   **`master` ветка:** Стабильная ветка, из которой формируются релизы. Ветка `develop` периодически сливается в `master`.

#### Стратегия окружений
*   **Production:** Окружение для конечных пользователей. Развертываются только релизы, созданные из тегов в ветке `master`.
*   **Staging:** Предрелизное окружение, точная копия Production. На него разворачивается содержимое ветки `master` для финального, расширенного тестирования.
*   **Development (Dev):** Окружение для разработчиков. На него разворачивается содержимое ветки `develop`.

> **Примечание:** Динамические окружения (Review Apps) для каждой feature-ветки являются возможным улучшением в будущем, но на данном этапе не реализуются для упрощения.

#### Стратегия тестирования и "Ворота качества" (Quality Gates)

**Критерии для слияния `feature` -> `develop`:**
*   Код-ревью пройдено.
*   Отсутствуют синтаксические ошибки (линтинг).
*   Docker-образ успешно собирается.
*   Проходят все **Unit-тесты**.
*   Проходят базовые тесты безопасности (**SAST**).

**Критерии для слияния `develop` -> `master`:**
*   Все предыдущие критерии выполнены.
*   Успешно проходят все **интеграционные тесты**.
*   Приложение успешно развернуто в `dev` окружение.
*   План развертывания (dry-run) в `staging` окружение выполняется без ошибок.

**Критерии для создания релиза (Production):**
*   Приложение успешно развернуто в `staging` окружение.
*   Все тесты на `staging` окружении проходят.
*   План развертывания (dry-run) в `production` окружение выполняется без ошибок.
*   Получено **ручное подтверждение** на развертывание (практика **Continuous Delivery**).

### 2. Инструментарий и структура проекта

#### Выбор инструментов
*   **CI/CD:** **GitLab CI**
*   **Тестирование:** **Pytest**
*   **Сборка образов:** **Kaniko**
*   **Безопасность (SAST):** Встроенные шаблоны GitLab CI
*   **E2E / Smoke тесты:** **cURL**
*   **Развертывание:** **Helm**
*   **Уведомления:** **Slack**

#### Обзор кодовой базы
Приложение представляет собой простой веб-сервис на базе **Flask**.
-   **`application/`**: Директория с исходным кодом (`__init__.py`, `helpers.py`).
-   **`tests/`**: Директория с тестами на базе `pytest` (`unit/`, `integration/`).
-   **`requirements.txt`**: Основные зависимости.
-   **`requirements-dev.txt`**: Зависимости для разработки и тестирования.

#### Принципы контейнеризации
-   **`Dockerfile`**: Используется **многостадийная сборка (multi-stage build)**.
    1.  На первой стадии в полном образе Python устанавливаются все зависимости.
    2.  На второй стадии берется минималистичный "distroless" образ от Google, в который копируются только код приложения и готовые зависимости. Это позволяет получить маленький и безопасный итоговый образ.
-   **`.dockerignore`**: Исключает из контекста сборки ненужные файлы (`.venv`, `.idea` и т.д.), что ускоряет процесс.

## Практические сценарии

### Сценарий 1: Реализация полного CI/CD пайплайна

В этом сценарии мы пошагово реализуем `.gitlab-ci.yml`.

#### Шаг 1: Скелет `.gitlab-ci.yml` (общая структура и правила)

Создаем первоначальную версию с определенными стадиями, правилами и настройками по умолчанию.

```yaml
# 1. Глобальные правила запуска и переменные
workflow:
  rules:
    # Запускать для Merge Request'ов, прямых пушей, тегов и ручного старта
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && ($CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "develop" || $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "main")'
    - if: '$CI_COMMIT_BRANCH == "main" || $CI_COMMIT_BRANCH == "develop"'
    - if: '$CI_COMMIT_TAG'
    - if: '$CI_PIPELINE_SOURCE == "web"'
    # Динамическое определение тега для Docker-образа
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "develop"'
      variables:
        DOCKER_IMAGE_TAG: "dev-pr-$CI_MERGE_REQUEST_IID"
    - if: '$CI_COMMIT_BRANCH == "main"'
      variables:
        DOCKER_IMAGE_TAG: "main-$CI_PIPELINE_IID"
    - if: '$CI_COMMIT_TAG =~ /^v[0-9]+\.[0-9]+\.[0-9]+$/'
      variables:
        DOCKER_IMAGE_TAG: $CI_COMMIT_TAG

# 2. Последовательность стадий
stages:
  - linting
  - building
  - testing
  - deployment
  - validate_deployment
  - release

# 3. Настройки по умолчанию
default:
  image: python:3.9
  cache:
    key: "$CI_COMMIT_REF_SLUG"
    paths:
      - .venv
  before_script:
    - python -m venv .venv
    - source .venv/bin/activate
    - pip install -r requirements-dev.txt

# 4. Шаблоны правил для задач
.test_rules_template:
  develop: &develop_rules
    rules:
      - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "develop"'
      - if: '$CI_COMMIT_BRANCH == "develop"'
  main: &main_rules
    rules:
      - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "main"'
      - if: '$CI_COMMIT_BRANCH == "main"'

# 5. Подключение шаблонов безопасности
include:
  - template: Security/SAST.gitlab-ci.yml
  - template: Security/Secret-Detection.gitlab-ci.yml
  - template: Security/Container-Scanning.yml
```

#### Шаг 2: Реализация стадий `linting`, `building`, `testing`

Добавляем конкретные задачи для проверки качества кода, сборки образа и тестирования.

```yaml
# ... (продолжение .gitlab-ci.yml)

# Задачи линтинга
pylint:
  stage: linting
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
  script:
    - pylint application/

black:
  stage: linting
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
  script:
    - black --check .

# Задача сборки Docker-образа
build-docker:
  stage: building
  image:
    name: gcr.io/kaniko-project/executor:v1.9.0-debug
    entrypoint: [""]
  script:
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor
      --context $CI_PROJECT_DIR
      --dockerfile $CI_PROJECT_DIR/Dockerfile
      --destination $CI_REGISTRY_IMAGE:$DOCKER_IMAGE_TAG

# Задачи функционального тестирования
unit-tests:
  stage: testing
  <<: *develop_rules
  script:
    - pytest tests/unit

integration-tests:
  stage: testing
  <<: *main_rules
  script:
    - pytest tests/integration

# Кастомизация задач безопасности из шаблонов
sast:
  <<: *develop_rules

secret_detection:
  <<: *develop_rules

container_scanning:
  stage: testing
  <<: *main_rules
```

#### Шаг 3: Реализация стадии `deployment`

Создается общий шаблон `.deploy_template` для унификации развертывания в разные окружения.

```yaml
# ... (продолжение .gitlab-ci.yml)

# Шаблон для развертывания
.deploy_template:
  stage: deployment
  image: darthvad1r/kube-helm-aws:1.0.0
  before_script:
    - helm plugin install https://github.com/databus23/helm-diff
    - aws eks --region us-east-1 update-kubeconfig --name slurm-eks-cluster
    - kubectl version
  script:
    - |
      if [[ -n "$HELM_DIFF" ]]; then
        helm diff upgrade --allow-unreleased $RELEASE_NAME ./helm
      elif [[ -n "$HELM_APPLY" ]]; then
        helm upgrade --install $RELEASE_NAME ./helm --set image.tag=$DOCKER_IMAGE_TAG
      else
        echo "Skipping deployment step..."
      fi

# Задачи развертывания
deploy-dev:
  extends: .deploy_template
  variables:
    RELEASE_NAME: my-app-dev
  environment:
    name: development
    url: http://dev.example.com
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "develop"'
      variables:
        HELM_DIFF: "true"
    - if: '$CI_COMMIT_BRANCH == "develop"'
      variables:
        HELM_APPLY: "true"

deploy-staging:
  extends: .deploy_template
  variables:
    RELEASE_NAME: my-app-staging
    ENDPOINT: http://staging.example.com
  environment:
    name: staging
    url: $ENDPOINT
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "main"'
      variables:
        HELM_DIFF: "true"
    - if: '$CI_COMMIT_BRANCH == "main"'
      variables:
        HELM_APPLY: "true"

deploy-production:
  extends: .deploy_template
  variables:
    RELEASE_NAME: my-app-prod
  environment:
    name: production
    url: http://prod.example.com
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v[0-9]+\.[0-9]+\.[0-9]+$/'
      when: manual
      variables:
        HELM_APPLY: "true"
  before_script:
    - |
      if ! echo "$AUTHORIZED_USERS" | grep -q "$GITLAB_USER_LOGIN"; then
        echo "User $GITLAB_USER_LOGIN is not authorized to deploy to production."
        exit 1
      fi
    - !reference [.deploy_template, before_script]
```

#### Шаг 4: Реализация стадий `validate_deployment` и `release`

```yaml
# ... (окончание .gitlab-ci.yml)

# Задачи валидации после развертывания
validate-dev-smoke:
  stage: validate_deployment
  image: curlimages/curl:7.75.0
  script:
    - curl -s --head http://dev.example.com | grep "200 OK"
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'

validate-staging-e2e:
  stage: validate_deployment
  image: curlimages/curl:7.75.0
  script:
    - |
      CONTENT=$(curl http://staging.example.com/version)
      if ! echo "$CONTENT" | grep -q "$DOCKER_IMAGE_TAG"; then
        echo "Version check failed!"
        exit 1
      else
        echo "Version check passed. Found version $DOCKER_IMAGE_TAG."
      fi
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

# Задача создания релиза
create-release:
  stage: release
  image: node:16-alpine
  script:
    - npm install -g semantic-release @semantic-release/gitlab
    - semantic-release
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

### Сценарий 2: Демонстрация полного рабочего цикла

1.  **Feature-ветка -> `develop`**:
    -   Разработчик создает `feature/my-new-feature` и пушит код.
    -   Создается **Merge Request** в ветку `develop`.
    -   Запускается пайплайн для MR: `linting` -> `build-docker` -> `unit-tests` -> `sast` -> `secret-detection` -> `helm diff` (dry-run для dev).
    -   После успешного прохождения всех проверок и код-ревью MR сливается в `develop`.

2.  **Коммит в `develop`**:
    -   Слияние запускает новый пайплайн уже на самой ветке `develop`.
    -   Выполняются те же шаги, но вместо `helm diff` происходит реальное развертывание (`helm upgrade`) в **dev-окружение**.
    -   После деплоя запускается `validate-dev-smoke`, чтобы убедиться, что окружение работает.

3.  **`develop` -> `main` (подготовка к релизу)**:
    -   Создается **Merge Request** из `develop` в `main`.
    -   Запускается пайплайн для MR: `linting` -> `build-docker` -> `integration-tests` -> `container-scanning` -> `helm diff` (dry-run для staging).
    -   После слияния в `main` запускается пайплайн, который разворачивает приложение в **staging-окружение** и прогоняет на нем `validate-staging-e2e` тесты.

4.  **Релиз в Production**:
    -   Когда команда готова к релизу, менеджер вручную запускает задачу `create-release` из ветки `main`.
    -   Инструмент релиза создает новый тег (например, `v1.2.3`) и GitLab Release с описанием изменений.
    -   Создание тега автоматически запускает пайплайн для этого тега, в котором становится доступна ручная задача `deploy-production`.
    -   Авторизованный пользователь нажимает кнопку "Play", и приложение разворачивается в **production-окружение**.

## Дополнительная иинформация

### Подготовка окружения

-   **Доступ к Kubernetes**: Для взаимодействия с кластером в CI/CD переменных проекта (`Settings > CI/CD > Variables`) необходимо настроить учетные данные (например, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` и `AUTHORIZED_USERS`).
-   **Доступ к Registry**: В кластере Kubernetes необходимо вручную создать секрет типа `docker-registry`, содержащий `Deploy Token` с правом `read_registry`. Этот секрет затем указывается в Helm-чарте в `imagePullSecrets`.
