# Типичный поток и пример CI/CD пайплайна

## Типичный поток (Workflow)

1.  **Инициация:** Разработчик делает коммит в свою ветку и создает pull/merge request в основную ветку (`main` или `develop`).
2.  **Сборка и статический анализ:** CI-система автоматически запускает пайплайн, который собирает проект, запускает линтеры и инструменты статического анализа кода (SAST).
3.  **Автоматическое тестирование:** Выполняются различные уровни тестов: unit-тесты, интеграционные, контрактные.
4.  **Сканирование безопасности:** Происходит сканирование зависимостей на известные уязвимости (SCA) и проверка лицензий.
5.  **Пакетирование:** При успешном прохождении всех проверок создается релизный артефакт (например, Docker-образ) и публикуется в репозиторий артефактов (registry).
6.  **Развертывание на Staging:** Артефакт развертывается в предпроизводственное окружение (`staging`), где выполняются smoke-тесты и приемочные тесты (acceptance tests).
7.  **Развертывание на Production:**
    *   **Continuous Delivery:** Требуется ручное подтверждение (approval) для развертывания в production.
    *   **Continuous Deployment:** При успешном прохождении всех предыдущих шагов развертывание в production происходит автоматически по заданной политике.

## Пример декларативного пайплайна (GitLab CI)

```yaml
stages:
  - build
  - test
  - package
  - deploy

variables:
  APP_VERSION: "${CI_COMMIT_SHORT_SHA}"

build:
  stage: build
  script:
    - make deps
    - make build
  artifacts:
    paths:
      - dist/
    expire_in: 1 week

test:
  stage: test
  needs: ["build"]
  script:
    - make lint
    - make unit
    - make integration
  cache:
    paths:
      - .cache/pip

package:
  stage: package
  needs: ["test"]
  script:
    - docker build -t registry.example/app:$APP_VERSION .
    - docker push registry.example/app:$APP_VERSION
  artifacts:
    reports:
      dotenv: release.env

deploy_stage:
  stage: deploy
  needs: ["package"]
  script:
    - ./scripts/deploy.sh stage $APP_VERSION
  environment: "stage"

deploy_prod:
  stage: deploy
  needs: ["deploy_stage"]
  when: manual
  only:
    - main
  script:
    - ./scripts/deploy.sh prod $APP_VERSION
  environment: "production"
```
