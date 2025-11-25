# Практическое руководство: CI/CD пайплайн для Docker-приложений в GitLab

Это руководство демонстрирует создание базового CI/CD пайплайна в GitLab для Docker-приложения, включающего этапы сборки образа, тестирования с использованием `docker-compose` и последующей очистки ресурсов.

См. также:
*   [Основы GitLab CI/CD](./gitlab_ci_basics.md)
*   [Управление Docker-образами в GitLab CI: Загрузка в Registry](./gitlab_ci_docker_push.md)
*   [GitLab CI как конструктор Workflow](./gitlab_ci_workflow_constructor.md)
*   [Docker Compose](../Docker/docker_compose.md)

## 1. Подготовка: `Dockerfile` и `docker-compose.yml`

Для реализации пайплайна нам понадобится `Dockerfile` для сборки образа приложения и `docker-compose.yml` для организации тестовой среды.

### 1.1. Пример `docker-compose.yml` для тестирования

Этот файл `docker-compose.yml` предназначен для запуска приложения и отдельного сервиса `test`, который будет проверять его доступность.

```yaml
version: '3.8'
services:
  app:
    image: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_REF_SLUG}:${CI_PIPELINE_ID}
    ports:
      - "80:80"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost"]
      interval: 10s
      timeout: 5s
      retries: 5
  test:
    image: alpine/curl:latest # Используем образ с curl для проверки
    command: ["/bin/sh", "-c", "apk add --no-cache curl && while ! curl -s app:80; do echo waiting for app; sleep 1; done"]
    depends_on:
      app:
        condition: service_healthy
```

**Пояснения:**

*   **`app` сервис:** Использует Docker-образ, собранный на этапе `build`, с динамически генерируемым тегом, включающим `CI_REGISTRY_IMAGE`, `CI_COMMIT_REF_SLUG` (название ветки) и `CI_PIPELINE_ID`.
*   **`test` сервис:** Зависит от `app`, используя `service_healthy` для проверки готовности приложения. Выполняет `curl` запрос к приложению. Если `curl` возвращает успешный код (0), задача считается выполненной успешно.

## 2. Настройка `.gitlab-ci.yml`

Теперь добавим стадии и задачи в файл `.gitlab-ci.yml` для сборки, тестирования и очистки.

```yaml
stages:
  - build
  - test
  - cleanup

variables:
  # Полное имя образа с тегом, включающим название ветки и ID пайплайна
  FULL_DOCKER_IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_REF_SLUG:$CI_PIPELINE_ID

build_job:
  stage: build
  image: docker:latest # Используем образ Docker для сборки
  services:
    - docker:dind # Запускаем Docker-in-Docker
  script:
    - docker build -t $FULL_DOCKER_IMAGE . # Собираем Docker образ

test_job:
  stage: test
  image: docker/compose:latest # Используем образ docker-compose для запуска тестов
  services:
    - docker:dind # Запускаем Docker-in-Docker
  script:
    - echo "Running tests with docker-compose..."
    # Создаем временный docker-compose.yml с подставленными переменными
    - envsubst < docker-compose.yml > docker-compose-ci.yml
    - docker-compose -f docker-compose-ci.yml up -d
    - docker-compose -f docker-compose-ci.yml logs app # Выводим логи приложения для отладки
    - docker-compose -f docker-compose-ci.yml run --rm test # Запускаем сервис test
    - docker-compose -f docker-compose-ci.yml down # Останавливаем контейнеры после тестов

cleanup_job:
  stage: cleanup
  image: docker/compose:latest # Используем образ docker-compose для очистки
  services:
    - docker:dind # Запускаем Docker-in-Docker
  script:
    - echo "Cleaning up docker-compose resources..."
    - envsubst < docker-compose.yml > docker-compose-ci.yml
    - docker-compose -f docker-compose-ci.yml down # Удаляем контейнеры и сети
  when: always # Задача очистки будет выполняться всегда, независимо от успеха предыдущих стадий
```

### 2.1. Пояснения к задачам

*   **`stages`:** Определены три последовательные стадии: `build` (сборка образа), `test` (тестирование приложения) и `cleanup` (очистка окружения).
*   **`variables`:** Определена переменная `FULL_DOCKER_IMAGE`, которая формирует уникальное имя образа, включая полный путь к Registry, название ветки (`$CI_COMMIT_REF_SLUG`) и ID пайплайна (`$CI_PIPELINE_ID`). Это обеспечивает версионирование и уникальность образов.
*   **`build_job`:**
    *   `image: docker:latest` и `services: - docker:dind`: Используется паттерн Docker-in-Docker для сборки образов внутри CI окружения.
    *   `script: docker build -t $FULL_DOCKER_IMAGE .`: Собирает Docker-образ и присваивает ему уникальный тег.
*   **`test_job`:**
    *   `image: docker/compose:latest` и `services: - docker:dind`: Для выполнения команд `docker-compose` используется соответствующий образ.
    *   `script:`
        *   `envsubst < docker-compose.yml > docker-compose-ci.yml`: В данном примере используется `envsubst` для подстановки переменных окружения GitLab CI (таких как `CI_REGISTRY_IMAGE`, `CI_COMMIT_REF_SLUG`, `CI_PIPELINE_ID`) в `docker-compose.yml`. Это позволяет `docker-compose` использовать корректное имя образа, собранного на предыдущем этапе.
        *   `docker-compose -f docker-compose-ci.yml up -d`: Запускает сервисы, описанные в `docker-compose-ci.yml`, в фоновом режиме.
        *   `docker-compose -f docker-compose-ci.yml run --rm test`: Запускает сервис `test` из `docker-compose.yml` для проверки доступности приложения. Код выхода `0` из этого сервиса означает успешное прохождение теста.
        *   `docker-compose -f docker-compose-ci.yml down`: Останавливает запущенные контейнеры.
*   **`cleanup_job`:**
    *   `image: docker/compose:latest` и `services: - docker:dind`: Аналогично `test_job`.
    *   `script: docker-compose -f docker-compose-ci.yml down`: Производит очистку всех запущенных `docker-compose` ресурсов (контейнеров, сетей).
    *   `when: always`: Эта директива гарантирует, что задача `cleanup_job` будет выполняться **всегда**, независимо от того, успешно или неуспешно завершились предыдущие стадии пайплайна. Это критически важно для предотвращения засорения Runner'а неиспользуемыми ресурсами.

## 3. Наблюдение за пайплайном в GitLab

После сохранения и коммита `.gitlab-ci.yml` GitLab автоматически запустит пайплайн. Вы можете отслеживать его выполнение в разделе **CI/CD > Pipelines** вашего проекта. Каждый этап и каждая задача будут иметь статус (ожидание, выполнение, успех, неудача), а также подробные логи выполнения.
После успешного прохождения всех этапов, включая `cleanup`, ресурсы на Runner'е будут освобождены.
