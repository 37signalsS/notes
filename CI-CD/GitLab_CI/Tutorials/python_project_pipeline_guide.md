# Комплексный CI/CD пайплайн для Python-проекта

## Определения

- **Комплексный CI/CD (Continuous Integration / Continuous Delivery) пайплайн** — автоматизированный процесс, охватывающий полный жизненный цикл ПО: от статического анализа до развертывания в production, управляемый через `.gitlab-ci.yml`.
- **Стратегия Multi-Environment** — подход, при котором приложение последовательно развертывается в несколько окружений (`development`, `staging`, `production`), каждое со своим набором тестов и правил доступа.
- **"Ворота качества" (Quality Gates)** — набор автоматических проверок (линтинг, unit-тесты, сканирование безопасности), обязательных для прохождения перед слиянием кода или развертыванием.
- **Многостадийная сборка (Multi-stage build)** — техника создания Docker-образов, позволяющая разделить процесс сборки зависимостей и формирования финального минималистичного артефакта.

> **Примечание:** Данный туториал описывает комплексный подход. Для базового ознакомления см. **[Начинающее руководство для Python-приложений](./beginner_guide_python_app.md)**.

## Основные концепции

### Архитектура и рабочий процесс

1. **Стратегия ветвления (модифицированный GitLab Flow):**
    - **`feature-*`**: Ветки для разработки функционала. Создаются от `develop`.
    - **`develop`**: Основная ветка разработки. Автоматически развертывается в `dev`.
    - **`main`**: Стабильная ветка. Развертывается в `staging`.
    - **Теги (`v*.*.*`)**: Создаются из `main` для релизов. Развертываются в `production`.

    > **Примечание:** Подробное описание стратегий см. в **[GitLab Flow](./gitlab_flow.md)** и **[Обзоре рабочих процессов Git](../../../Git/git_workflows.md)**.

2. **Стратегия окружений:**
    - **Development (`dev`)**: Для внутреннего тестирования. Развертывается из `develop`.
    - **Staging**: Копия production для финальной проверки. Развертывается из `main`.
    - **Production**: Окружение для пользователей. Развертывается из тегов.

3. **Стратегия тестирования:**
    - **`feature` -> `develop`**: Линтеры, unit-тесты, SAST (Static Application Security Testing).
    - **`develop` -> `main`**: Интеграционные тесты.
    - **После деплоя**: Smoke- или e2e-тесты (End-to-End).

    > **Примечание:** Интеграция тестов описана в **[Testing in CI/CD](../../Testing/testing_cicd_integration.md)**.

### Инструментарий

- **CI/CD**: GitLab CI
- **Контейнеризация**: Docker, Kaniko (безопасная сборка)
- **Оркестрация**: Kubernetes, Helm
- **Тестирование**: Pytest, cURL
- **Релизы**: `semantic-release`

> **Примечание:** Альтернативы релизов см. в **[Управлении релизами](../Advanced/release_management_and_semver.md)**.

### Полный рабочий цикл

1. **Разработка**: MR (Merge Request) из `feature/*` в `develop`. Запуск линтеров, unit-тестов, SAST.
2. **Слияние в `develop`**: Автоматический деплой в `dev` и smoke-тесты.
3. **Подготовка к релизу**: MR из `develop` в `main`. Интеграционные тесты и `helm diff`.
4. **Слияние в `main`**: Автоматический деплой в `staging` и e2e-тесты.
5. **Релиз**: Ручной запуск `create-release` (создание Git-тега). Пайплайн для тега предлагает ручной `deploy-production`.

### Подготовка окружения

- **Доступ к Kubernetes**: Настройте `KUBECONFIG` или `KUBE_TOKEN` в переменных проекта.
- **Доступ к Registry**: Создайте секрет `docker-registry` с **Deploy Token** в кластере.

> **Примечание:** Настройка переменных описана в **[Переменных в GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)**. Интеграция с K8s — в **[GitLab CI Kubernetes Integration](../Advanced/gitlab_kubernetes_integration_guide.md)**.

## Практические сценарии

### Реализация пайплайна в `.gitlab-ci.yml`

#### Шаг 1: Общая структура и правила

```yaml
workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && ($CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "develop" || $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "main")'
    - if: '$CI_COMMIT_BRANCH == "main" || $CI_COMMIT_BRANCH == "develop"'
    - if: '$CI_COMMIT_TAG'
    - if: '$CI_PIPELINE_SOURCE == "web"'
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "develop"'
      variables:
        DOCKER_IMAGE_TAG: "dev-pr-$CI_MERGE_REQUEST_IID"
    - if: '$CI_COMMIT_BRANCH == "main"'
      variables:
        DOCKER_IMAGE_TAG: "main-$CI_PIPELINE_IID"
    - if: '$CI_COMMIT_TAG =~ /^v[0-9]+\.[0-9]+\.[0-9]+$/'
      variables:
        DOCKER_IMAGE_TAG: $CI_COMMIT_TAG

stages:
  - linting
  - building
  - testing
  - deployment
  - validate_deployment
  - release

default:
  image: python:3.11
  cache:
    key: "$CI_COMMIT_REF_SLUG"
    paths:
      - .venv
  before_script:
    - python -m venv .venv
    - source .venv/bin/activate
    - pip install -r requirements-dev.txt

.test_rules_template:
  develop: &develop_rules
    rules:
      - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "develop"'
      - if: '$CI_COMMIT_BRANCH == "develop"'
  main: &main_rules
    rules:
      - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "main"'
      - if: '$CI_COMMIT_BRANCH == "main"'

include:
  - template: Security/SAST.gitlab-ci.yml
  - template: Security/Secret-Detection.gitlab-ci.yml
  - template: Security/Container-Scanning.yml
```

> **Примечание:** Описание `rules` см. в **[Директивах workflow_rules](../Advanced/workflow_rules/directives_definitions.md)**.

#### Шаг 2: Сборка и тестирование

```yaml
pylint:
  stage: linting
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
  script:
    - pylint application/

build-docker:
  stage: building
  image:
    name: gcr.io/kaniko-project/executor:v1.21.0-debug
    entrypoint: [""]
  script:
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor
      --context $CI_PROJECT_DIR
      --dockerfile $CI_PROJECT_DIR/Dockerfile
      --destination $CI_REGISTRY_IMAGE:$DOCKER_IMAGE_TAG

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

# Переопределение стадий для шаблонов безопасности
container_scanning:
  stage: testing
  <<: *main_rules
```

> **Примечание:** Сборка с Kaniko описана в **[Kaniko: Сборка без демона](../../../Docker/Dockerfile/dockerfile_kaniko.md)**.

#### Шаг 3: Развертывание через Helm

```yaml
.deploy_template:
  stage: deployment
  image: bitnami/kubectl:1.29.0
  before_script:
    - helm plugin install https://github.com/databus23/helm-diff
  script:
    - |
      if [[ -n "$HELM_DIFF" ]]; then
        helm diff upgrade --allow-unreleased $RELEASE_NAME ./helm
      elif [[ -n "$HELM_APPLY" ]]; then
        helm upgrade --install $RELEASE_NAME ./helm --set image.tag=$DOCKER_IMAGE_TAG
      fi

deploy-dev:
  extends: .deploy_template
  variables:
    RELEASE_NAME: my-app-dev
  environment:
    name: development
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "develop"'
      variables: { HELM_DIFF: "true" }
    - if: '$CI_COMMIT_BRANCH == "develop"'
      variables: { HELM_APPLY: "true" }

deploy-production:
  extends: .deploy_template
  variables:
    RELEASE_NAME: my-app-prod
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v[0-9]+\.[0-9]+\.[0-9]+$/'
      when: manual
      variables: { HELM_APPLY: "true" }
```

> **Примечание:** Развертывание в K8s описано в **[GitLab CI Kubernetes Integration](../Advanced/gitlab_kubernetes_integration_guide.md)**. Откат — в **[Deployment Health Checks](../../Deployment_Strategies/deployment_health_checks_and_rollback.md)**.

#### Шаг 4: Валидация и релиз

```yaml
validate-dev-smoke:
  stage: validate_deployment
  image: curlimages/curl:8.6.0
  script:
    - curl -s --head http://dev.example.com | grep "200 OK"
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'

create-release:
  stage: release
  image: node:20-alpine
  script:
    - npm install -g semantic-release @semantic-release/gitlab
    - semantic-release
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

## Дополнительная информация

- **Безопасность**: Используйте маскированные переменные для секретов. SAST и сканирование контейнеров встроены в пайплайн.
- **Оптимизация**: Использование Kaniko позволяет собирать образы без привилегированного режима Docker. Кэширование `.venv` ускоряет установку зависимостей.

### Смежные руководства

- **[Основы GitLab CI](../Concepts/gitlab_ci_basics.md)** — базовые компоненты.
- **[Интеграция с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — детальная настройка доступа.
- **[Dockerfile для Python](../../../Docker/Dockerfile/Docker_best_practices/python.md)** — лучшие практики сборки.
