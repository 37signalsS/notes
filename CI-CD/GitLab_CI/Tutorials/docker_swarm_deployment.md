# Пример: CI/CD для Docker Swarm с GitLab CI

*   **GitLab CI:** Оркестратор пайплайна.
*   **Docker Swarm:** Целевая платформа для развертывания.
*   **mTLS:** Для безопасного удаленного подключения к Docker Daemon.
*   **Kaniko:** Для сборки Docker-образов без необходимости в Docker-in-Docker.
*   **Docker Context:** Для удобного переключения между dev и prod окружениями.

**Пример `.gitlab-ci.yml`:**

```yaml
stages:
  - build
  - deploy

build:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.9.0-debug
    entrypoint: [""]
  script:
    # Kaniko собирает образ и пушит его в GitLab Registry
    - /kaniko/executor
      --context $CI_PROJECT_DIR
      --dockerfile $CI_PROJECT_DIR/Dockerfile
      --destination $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  only:
    - main
    - dev

deploy_prod:
  stage: deploy
  image: docker:latest
  script:
    # 1. Создаем Docker Context с помощью переменных GitLab CI
    - docker context create swarm-prod --docker "host=${PROD_DOCKER_HOST},ca=${PROD_CA_FILE},cert=${PROD_CERT_FILE},key=${PROD_KEY_FILE}"
    # 2. Переключаемся на созданный контекст
    - docker context use swarm-prod
    # 3. Развертываем стек, используя docker-compose.prod.yml
    - docker stack deploy -c docker-compose.prod.yml --with-registry-auth my-app
  environment:
    name: production
  only:
    - main

deploy_dev:
  stage: deploy
  image: docker:latest
  script:
    - docker context create swarm-dev --docker "host=${DEV_DOCKER_HOST},ca=${DEV_CA_FILE},cert=${DEV_CERT_FILE},key=${DEV_KEY_FILE}"
    - docker context use swarm-dev
    - docker stack deploy -c docker-compose.dev.yml --with-registry-auth my-app
  environment:
    name: development
  only:
    - dev
```

**Объяснение пайплайна:**

1.  **Этап `build`:**
    *   Используется образ `kaniko`, который не требует привилегированного доступа или запущенного Docker-демона.
    *   Он собирает Docker-образ на основе `Dockerfile` в проекте.
    *   Готовый образ с тегом, содержащим хеш коммита, загружается в GitLab Container Registry.

2.  **Этап `deploy`:**
    *   Используется официальный образ `docker`.
    *   С помощью команды `docker context create` настраивается подключение к удаленному Docker Swarm кластеру. Все необходимые данные (хост, сертификаты) безопасно передаются через переменные GitLab CI. Подробнее см. в [Управление секретами](../../DevSecOps/secrets_management.md).
    *   Команда `docker stack deploy` развертывает приложение, описанное в `docker-compose.yml`. Опция `--with-registry-auth` позволяет узлам Swarm аутентифицироваться в GitLab Registry для скачивания образа.
    *   Подробнее о настройке удаленного доступа и развертывании в Swarm см. в [руководстве по Docker Swarm](../../Docker/docker_swarm.md).
