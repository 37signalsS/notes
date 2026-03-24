# Комплексный CI/CD пайплайн для Python-проекта

## Определения

- **Комплексный CI/CD пайплайн**: Автоматизированный процесс, охватывающий все этапы жизненного цикла ПО — от статического анализа кода до развертывания в production, управляемый через `.gitlab-ci.yml`.
- **Стратегия Multi-Environment**: Подход, при котором приложение последовательно развертывается в несколько окружений (`development`, `staging`, `production`), каждое со своим набором тестов и правил развертывания.
- **"Ворота качества" (Quality Gates)**: Набор автоматических проверок (линтинг, unit-тесты, сканирование безопасности), которые должны быть успешно пройдены, прежде чем код будет допущен к слиянию в основную ветку или развертыванию.
- **Многостадийная сборка (Multi-stage build)**: Техника создания Docker-образов, при которой для сборки зависимостей используется один образ, а для финального артефакта — другой, минималистичный. Это позволяет значительно уменьшить размер и уязвимость итогового образа.

> **Примечание:** Данный туториал описывает комплексный подход. Для базового ознакомления см. **[Начинающее руководство для Python-приложений](./beginner_guide_python_app.md)**.

## Основные концепции

### Архитектура и рабочий процесс

1. **Стратегия ветвления (модифицированный Git Flow):**
    - **`feature-*`**: Ветки для разработки нового функционала. Создаются от `develop`.
    - **`develop`**: Основная ветка разработки, куда сливаются feature-ветки. Автоматически развертывается в `development` окружение.
    - **`main`**: Стабильная ветка. Периодически синхронизируется с `develop`. Развертывается в `staging` окружение.
    - **Теги (`v*.*.*`)**: Создаются из ветки `main` для релиза. Только теги развертываются в `production`.

    > **Примечание:** Подробное описание стратегий ветвления см. в **[GitLab Flow](./gitlab_flow.md)** и **[Обзоре рабочих процессов Git](../../../Git/git_workflows.md)**.

2. **Стратегия окружений:**
    - **Development (`dev`)**: Для разработчиков. Развертывается из `develop`.
    - **Staging**: Предрелизное окружение, копия production. Развертывается из `main`.
    - **Production**: Окружение для конечных пользователей. Развертывается из тегов.

3. **Стратегия тестирования и "Ворота качества":**
    - **`feature` -> `develop`**: Прогоняются линтеры, unit-тесты и SAST-сканеры.
    - **`develop` -> `main`**: Прогоняются интеграционные тесты.
    - После развертывания в каждое окружение выполняются smoke- или e2e-тесты для верификации.

    > **Примечание:** Интеграция тестов в CI/CD описана в **[Testing in CI/CD](../../Testing/testing_cicd_integration.md)**.

### Инструментарий и структура проекта

- **CI/CD:** GitLab CI
- **Контейнеризация:** Docker, Kaniko (для безопасной сборки)
- **Оркестрация и развертывание:** Kubernetes, Helm
- **Тестирование:** Pytest (unit/integration), cURL (smoke/e2e)
- **Релизы:** `semantic-release`

> **Примечание:** Альтернативный подход к управлению релизами см. в **[Управлении релизами и семантическим версионированием](../Advanced/release_management_and_semver.md)**.

Приложение представляет собой простой веб-сервис на **Flask**. `Dockerfile` использует многостадийную сборку для создания минималистичного и безопасного образа на базе "distroless".

### Полный рабочий цикл

1. **Разработка фичи:** Разработчик создает Merge Request из `feature/*` в `develop`. Пайплайн запускает линтеры, unit-тесты, SAST и `helm diff` для dev-окружения.
2. **Слияние в `develop`:** После код-ревью и успешного пайплайна MR сливается. Запускается новый пайплайн, который развертывает приложение в `dev` окружение и запускает smoke-тесты.
3. **Подготовка к релизу:** Создается MR из `develop` в `main`. Пайплайн запускает интеграционные тесты и `helm diff` для staging-окружения.
4. **Слияние в `main`:** После слияния запускается пайплайн, который разворачивает приложение в `staging` и выполняет e2e-тесты.
5. **Релиз в Production:** Менеджер вручную запускает задачу `create-release`, которая с помощью `semantic-release` создает Git-тег. Это инициирует пайплайн для тега, в котором доступна ручная задача `deploy-production`. После подтверждения приложение развертывается в production.

### Подготовка окружения

- **Доступ к Kubernetes**: В переменных CI/CD проекта (`Settings > CI/CD > Variables`) должны быть настроены учетные данные для доступа к кластеру (`KUBE_URL`, `KUBE_TOKEN` или `KUBECONFIG`).
- **Доступ к Registry**: В Kubernetes должен быть создан секрет типа `docker-registry` с `Deploy Token` для доступа к GitLab Container Registry.

> **Примечание:** Настройка переменных и секретов описана в **[Переменных и секретах в GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)**. Интеграция с Kubernetes — в **[GitLab CI Kubernetes Integration](../Advanced/gitlab_kubernetes_integration_guide.md)**.

## Практические сценарии

### Реализация полного CI/CD пайплайна в `.gitlab-ci.yml`

#### Шаг 1: Общая структура и правила (`workflow`, `stages`, `default`)

```yaml
# 1. Глобальные правила запуска и переменные
workflow:
  rules:
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
  image: python:3.11
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

> **Примечание:** Подробное описание директив `workflow:rules` и `rules` см. в **[Директивах workflow_rules](../Advanced/workflow_rules/directives_definitions.md)**.

#### Шаг 2: Стадии `linting`, `building`, `testing`

```yaml
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
    name: gcr.io/kaniko-project/executor:v1.21.0-debug
    entrypoint: [""]
  script:
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor
      --context $CI_PROJECT_DIR
      --dockerfile $CI_PROJECT_DIR/Dockerfile
      --destination $CI_REGISTRY_IMAGE:$DOCKER_IMAGE_TAG

> **Примечание:** Безопасная сборка образов с Kaniko описана в **[Best Practices Dockerfile для Python](../../../Docker/Dockerfile/Docker_best_practices/python.md)**.

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

#### Шаг 3: Стадия `deployment`

```yaml
# Шаблон для развертывания
.deploy_template:
  stage: deployment
  image: bitnami/kubectl:1.29.0
  before_script:
    - helm plugin install https://github.com/databus23/helm-diff
    # Для Yandex Cloud Managed Kubernetes
    - yc managed-kubernetes cluster get-credentials --name example-k8s-cluster --context k8s-context
    # Или для локального кластера (kubeconfig уже настроен)
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
  environment:
    name: staging
    url: http://staging.example.com
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
```

> **Примечание:** Развертывание в Kubernetes с Helm описано в **[GitLab CI Kubernetes Integration](../Advanced/gitlab_kubernetes_integration_guide.md)**. Проверки здоровья и откат — в **[Deployment Health Checks](../../Deployment_Strategies/deployment_health_checks_and_rollback.md)**.

#### Шаг 4: Стадии `validate_deployment` и `release`

```yaml
# Задачи валидации после развертывания
validate-dev-smoke:
  stage: validate_deployment
  image: curlimages/curl:8.6.0
  script:
    - curl -s --head http://dev.example.com | grep "200 OK"
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'

validate-staging-e2e:
  stage: validate_deployment
  image: curlimages/curl:8.6.0
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
  image: node:20-alpine
  script:
    - npm install -g semantic-release @semantic-release/gitlab
    - semantic-release
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```
