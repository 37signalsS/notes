# Практические сценарии

## Сценарий 1: Модульная конфигурация проекта

**Структура:**

```
project/
├── .gitlab-ci.yml
└── .gitlab-ci/
    ├── build.yml
    ├── test.yml
    └── deploy.yml
```

```yaml
# .gitlab-ci.yml
include:
  - local: '.gitlab-ci/build.yml'
  - local: '.gitlab-ci/test.yml'
  - local: '.gitlab-ci/deploy.yml'

stages:
  - build
  - test
  - deploy
```

## Сценарий 2: Централизованные шаблоны для группы проектов

**Репозиторий шаблонов (`group/ci-templates`):**

```
ci-templates/
├── docker-build.yml
├── nodejs-test.yml
└── kubernetes-deploy.yml
```

```yaml
# docker-build.yml
.docker_build:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
```

**Проект (`.gitlab-ci.yml`):**

```yaml
include:
  - project: 'group/ci-templates'
    ref: v1.2.0
    file: '/docker-build.yml'

stages:
  - build

build:
  extends: .docker_build
  variables:
    DOCKER_BUILDKIT: "1"
```

## Сценарий 3: Условное включение для разных окружений

```yaml
include:
  - local: '.gitlab-ci/build.yml'
  
  - local: '.gitlab-ci/deploy-dev.yml'
    rules:
      - if: '$CI_COMMIT_BRANCH == "develop"'
  
  - local: '.gitlab-ci/deploy-prod.yml'
    rules:
      - if: '$CI_COMMIT_BRANCH == "main"'
```

## Сценарий 4: Использование компонента с inputs

```yaml
include:
  - component: '$CI_SERVER_FQDN/group/security/secret-detection@1.0.0'
    inputs:
      stage: security
      scan_path: './config/secrets'
```
