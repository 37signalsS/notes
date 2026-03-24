# Pipeline Workflow

## Определения

**Поток пайплайна (Pipeline Workflow)** — это последовательность [этапов (Stages)](./pipeline_glossary.md#этап-stage) и [задач (Jobs)](./pipeline_glossary.md#задача-job-step), которые выполняются для доставки кода от коммита до развертывания.

Процесс инициируется [триггером](./pipeline_glossary.md#триггер-trigger) (например, `git push`) и выполняется [исполнителями (Runners)](./pipeline_glossary.md#исполнитель-runner-agent).

## Основные концепции

### Типичный поток (Workflow)

1. **Инициация:** Разработчик создает `pull/merge request` в основную ветку (`main`).
2. **Сборка и статический анализ:** Запускается [пайплайн](./pipeline_glossary.md#пайплайн-pipeline), который собирает проект, запускает линтеры и SAST-сканеры.
3. **Автоматическое тестирование:** Выполняются unit-тесты, интеграционные и др.
4. **Сканирование безопасности:** Происходит сканирование зависимостей на уязвимости (SCA).
5. **Пакетирование:** Создается релизный [артефакт](./pipeline_glossary.md#артефакт-artifact) (например, Docker-образ) и публикуется в [репозиторий артефактов](../artifact_management.md).
6. **Развертывание на Staging:** Артефакт развертывается в предпроизводственную [среду (Environment)](./pipeline_glossary.md#среда-environment), где выполняются smoke-тесты.
7. **Развертывание на Production:**
   - **Continuous Delivery:** Требуется ручное подтверждение для развертывания.
   - **Continuous Deployment:** Развертывание происходит автоматически при успехе всех предыдущих шагов.

### Принципы построения

- **Fail-Fast:** Самые быстрые проверки (линтинг, unit-тесты) выполняются первыми.
- **Параллелизм:** Независимые задачи выполняются одновременно для сокращения времени пайплайна.
- **Последовательность:** Зависимые этапы выполняются строго по порядку.

## Практические сценарии

### Пример на GitLab CI

Этот декларативный пайплайн иллюстрирует описанный выше поток.

```yaml
# Определение последовательности [Этапов (Stages)](./pipeline_glossary.md#этап-stage)
stages:
  - build
  - test
  - package
  - deploy

variables:
  APP_VERSION: "${CI_COMMIT_SHORT_SHA}"

# [Задача (Job)](./pipeline_glossary.md#задача-job-step) на этапе 'build'
build:
  stage: build
  script:
    - make deps
    - make build
  # Создание [артефактов](./pipeline_glossary.md#артефакт-artifact) для передачи на следующие этапы
  artifacts:
    paths:
      - dist/
    expire_in: 1 week

# Задача на этапе 'test'
test:
  stage: test
  needs: ["build"] # Зависимость от задачи 'build'
  script:
    - make lint
    - make unit
    - make integration
  # Использование [кэширования](./pipeline_glossary.md#кэш-cache) для ускорения
  cache:
    paths:
      - .cache/pip

# Задача на этапе 'package'
package:
  stage: package
  needs: ["test"]
  script:
    - docker build -t registry.example/app:$APP_VERSION .
    - docker push registry.example/app:$APP_VERSION
  artifacts:
    reports:
      dotenv: release.env

# Задача развертывания в [среду](./pipeline_glossary.md#среда-environment) 'staging'
deploy_stage:
  stage: deploy
  needs: ["package"]
  script:
    - ./scripts/deploy.sh stage $APP_VERSION
  environment: "stage"

# Задача развертывания в [среду](./pipeline_glossary.md#среда-environment) 'production'
deploy_prod:
  stage: deploy
  needs: ["deploy_stage"]
  when: manual # [Триггер](./pipeline_glossary.md#триггер-trigger): ручной запуск
  only:
    - main
  script:
    - ./scripts/deploy.sh prod $APP_VERSION
  environment: "production"
```

### Пояснения к примеру

| Компонент | Описание |
| :--- | :--- |
| `stages` | Последовательность этапов: `build` → `test` → `package` → `deploy` |
| `needs` | Явное указание зависимостей между задачами |
| `artifacts` | Передача результатов сборки между этапами |
| `cache` | Сохранение зависимостей между запусками пайплайна |
| `environment` | Декларативное описание среды развертывания |
| `when: manual` | Требование ручного подтверждения для production |

## Дополнительная информация

### Связанные документы

- **[CI/CD: Обзор](../ci_cd_overview.md)** — общее введение в CI/CD.
- **[Глоссарий](./pipeline_glossary.md)** — определения ключевых терминов.
- **[GitLab CI Basics](../GitLab_CI/Concepts/gitlab_ci_basics.md)** — основы GitLab CI.
- **[GitOps Pipeline Example](./gitops_pipeline_example.md)** — пример пайплайна с GitOps.
- **[Deployment Strategies](./deployment_strategies.md)** — стратегии развертывания.
