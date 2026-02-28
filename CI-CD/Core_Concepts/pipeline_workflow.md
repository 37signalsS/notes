# Типичный поток и пример CI/CD пайплайна

### Определения

- **Поток пайплайна (Pipeline Workflow)** — это последовательность **[этапов (Stages)](./pipeline_elements.md)** и **[задач (Jobs)](./pipeline_elements.md)**, которые выполняются для доставки кода от коммита до развертывания. Этот документ описывает типичный, обобщенный поток.

### Основные концепции: Типичный поток (Workflow)

Процесс инициируется **[триггером](./pipeline_elements.md)** (например, `git push`) и выполняется **[исполнителями (Runners)](./pipeline_elements.md)**.

1. **Инициация:** Разработчик создает `pull/merge request` в основную ветку (`main`).
2. **Сборка и статический анализ:** Запускается **[пайплайн](./pipeline_elements.md)**, который собирает проект, запускает линтеры и SAST-сканеры.
3. **Автоматическое тестирование:** Выполняются unit-тесты, интеграционные и др.
4. **Сканирование безопасности:** Происходит сканирование зависимостей на уязвимости (SCA).
5. **Пакетирование:** Создается релизный **[артефакт](./pipeline_elements.md)** (например, Docker-образ) и публикуется в **[репозиторий артефактов](../artifact_management.md)**.
6. **Развертывание на Staging:** Артефакт развертывается в предпроизводственную **[среду (Environment)](./pipeline_elements.md)**, где выполняются smoke-тесты.
7. **Развертывание на Production:**
    - **Continuous Delivery:** Требуется ручное подтверждение для развертывания.
    - **Continuous Deployment:** Развертывание происходит автоматически при успехе всех предыдущих шагов.

### Практические сценарии: Пример на GitLab CI

Этот декларативный пайплайн иллюстрирует описанный выше поток.

```yaml
# Определение последовательности этапов (Stages)
stages:
  - build
  - test
  - package
  - deploy

variables:
  APP_VERSION: "${CI_COMMIT_SHORT_SHA}"

# Задача (Job) на этапе 'build'
build:
  stage: build
  script:
    - make deps
    - make build
  # Создание артефактов для передачи на следующие этапы
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
  # Использование кэширования для ускорения
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

# Задача развертывания в среду 'staging'
deploy_stage:
  stage: deploy
  needs: ["package"]
  script:
    - ./scripts/deploy.sh stage $APP_VERSION
  environment: "stage"

# Задача развертывания в среду 'production'
deploy_prod:
  stage: deploy
  needs: ["deploy_stage"]
  when: manual # Триггер: ручной запуск
  only:
    - main
  script:
    - ./scripts/deploy.sh prod $APP_VERSION
  environment: "production"
```
