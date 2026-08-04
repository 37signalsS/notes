# Комплексный CI/CD пайплайн для Python-проекта

## Надежность и актуальность

- **Оценка надежности:** 10 (SSoT + Современные практики GitLab 17.x)
- **Триггеры обновления:** Выход мажорных версий GitLab (18.0+), обновление Python до 3.13+, изменения в API GitLab Agent (KAS).

## Определения

**Комплексный CI/CD Pipeline** — полностью автоматизированный процесс жизненного цикла ПО, включающий проверку качества кода, многоуровневое тестирование, сборку артефактов и автоматизированное развертывание в различные среды.

**`id_tokens` (OIDC)** — современный механизм аутентификации, позволяющий GitLab Runner безопасно взаимодействовать с облаками и Kubernetes без использования долгоживущих секретов.

**GitLab Agent for Kubernetes (KAS)** — инструмент для безопасного управления кластером через **CI/CD Tunnel**, исключающий необходимость хранения `KUBECONFIG` в переменных репозитория.

**SBOM (Software Bill of Materials)** — формализованный список всех компонентов, библиотек и зависимостей приложения, необходимый для обеспечения безопасности цепочки поставок (Supply Chain Security).

**Quality Gates (Ворота качества)** — набор автоматических проверок (линтеры, тесты, сканеры), которые должны быть пройдены для перехода артефакта на следующую стадию деплоя.

## Основные концепции

### Архитектура и рабочий процесс

1. **Стратегия ветвления (GitLab Flow + TBD):**
    - **`feature/*`**: Короткоживущие ветки для разработки. Запускают проверки качества (Lint, Test, SAST).
    - **`develop`**: Ветка интеграции. Автоматический деплой в окружение **Development**.
    - **`main`**: Стабильная ветка. Автоматический деплой в окружение **Staging**.
    - **Git-теги (`v*.*.*`)**: Официальные релизы. Ручной деплой в **Production**.

2. **Иерархия окружений:**
    - **Development (`dev`)**: Среда для быстрой проверки функционала разработчиками.
    - **Staging**: Копия продакшена для финального тестирования и QA.
    - **Production**: Продуктивная среда, доступная конечным пользователям.

3. **Слои безопасности:**
    - **SAST**: Статический анализ исходного кода.
    - **Dependency Scanning (SCA)**: Анализ уязвимостей в сторонних библиотеках.
    - **Container Scanning**: Проверка Docker-образа на уязвимости в ОС и системных пакетах.
    - **Secret Detection**: Поиск случайно закомиченных ключей и паролей.

## Практические сценарии

### Реализация пайплайна в `.gitlab-ci.yml`

#### Шаг 1: Глобальные настройки и правила

Используем `workflow:rules` для фильтрации запусков и типизации тегов образов.

```yaml
workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      variables:
        DOCKER_IMAGE_TAG: "mr-$CI_MERGE_REQUEST_IID"
    - if: '$CI_COMMIT_BRANCH == "develop"'
      variables:
        DOCKER_IMAGE_TAG: "dev-$CI_COMMIT_SHORT_SHA"
    - if: '$CI_COMMIT_BRANCH == "main"'
      variables:
        DOCKER_IMAGE_TAG: "staging-$CI_COMMIT_SHORT_SHA"
    - if: '$CI_COMMIT_TAG =~ /^v[0-9]+\.[0-9]+\.[0-9]+$/'
      variables:
        DOCKER_IMAGE_TAG: $CI_COMMIT_TAG

stages:
  - validate
  - build
  - test
  - deploy
  - release

include:
  - template: Security/SAST.gitlab-ci.yml
  - template: Security/Secret-Detection.gitlab-ci.yml
  - template: Security/Container-Scanning.yml
  - template: Security/Dependency-Scanning.gitlab-ci.yml

default:
  image: python:3.12-slim
  interruptible: true
```

#### Шаг 2: Валидация и Сборка (SBOM + Kaniko)

```yaml
linting:
  stage: validate
  script:
    - pip install ruff
    - ruff check .
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

build_and_sbom:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.23.1-debug
    entrypoint: [""]
  script:
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor
      --context $CI_PROJECT_DIR
      --dockerfile $CI_PROJECT_DIR/Dockerfile
      --destination $CI_REGISTRY_IMAGE:$DOCKER_IMAGE_TAG
    # Генерация SBOM (Software Bill of Materials)
    - wget https://github.com/anchore/syft/releases/download/v1.0.0/syft_1.0.0_linux_amd64.tar.gz
    - tar -xf syft_1.0.0_linux_amd64.tar.gz
    - ./syft $CI_REGISTRY_IMAGE:$DOCKER_IMAGE_TAG -o cyclonedx-json=sbom.json
  artifacts:
    paths:
      - sbom.json
```

#### Шаг 3: Тестирование в изолированных средах

```yaml
.pytest_base:
  stage: test
  cache:
    key: "python-deps-$CI_COMMIT_REF_SLUG"
    paths:
      - .cache/pip
  before_script:
    - pip install --cache-dir .cache/pip -r requirements-dev.txt

unit_tests:
  extends: .pytest_base
  script:
    - pytest tests/unit --junitxml=report.xml
  artifacts:
    reports:
      junit: report.xml

integration_tests:
  extends: .pytest_base
  script:
    - pytest tests/integration
  rules:
    - if: $CI_COMMIT_BRANCH == "main" || $CI_COMMIT_BRANCH == "develop"
```

#### Шаг 4: Деплой через GitLab Agent (KAS) и Helm

```yaml
.helm_deploy:
  stage: deploy
  image: bitnami/kubectl:1.30.0
  variables:
    KUBE_CONTEXT: "my-group/infra:prod-agent"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - >
      helm upgrade --install $RELEASE_NAME ./charts/app
        --namespace $NAMESPACE
        --set image.tag=$DOCKER_IMAGE_TAG
        --wait --atomic

deploy_dev:
  extends: .helm_deploy
  variables:
    RELEASE_NAME: "python-app-dev"
    NAMESPACE: "dev"
  environment:
    name: development
    url: https://dev.example.com
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'

deploy_prod:
  extends: .helm_deploy
  variables:
    RELEASE_NAME: "python-app-prod"
    NAMESPACE: "production"
  environment:
    name: production
    url: https://app.example.com
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v[0-9]+\.[0-9]+\.[0-9]+$/'
      when: manual
```

## Технические нюансы и Тюнинг

### Оптимизация кэширования
Для Python-проектов критично кэшировать не только `.venv` (который может быть привязан к версии Python), но и саму директорию загрузки `pip` (`.cache/pip`). Это позволяет избежать повторной скачки пакетов при изменении структуры виртуального окружения.

### Безопасность через ID Tokens
В примере с Helm рекомендуется использовать `id_tokens` для аутентификации в Kubernetes, если кластер поддерживает OIDC. Это исключает хранение статических токенов в переменных проекта.

### Тюнинг Docker-образа
Всегда используйте многостадийную сборку (multi-stage). В первом слое (`builder`) устанавливайте зависимости, во втором (`runtime`) — копируйте только `site-packages` и код. Запускайте приложение от имени `non-root` пользователя.

## Дополнительная информация

### Смотрите также

- **[Основы GitLab CI](../Concepts/gitlab_ci_basics.md)** — базовые термины.
- **[Интеграция с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — детальная настройка KAS.
- **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — управление доступом.
- **[Dockerfile для Python](../../../Docker/Dockerfile/Docker_best_practices/python.md)** — глубокая оптимизация сборки.
