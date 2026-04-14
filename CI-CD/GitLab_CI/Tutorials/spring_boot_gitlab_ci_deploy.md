# Развертывание Spring Boot в GitLab CI с Docker

## Определения

**Spring Boot** — фреймворк для создания standalone Java-приложений с минимальной конфигурацией. В контексте CI/CD требует сборки JAR-артефакта и контейнеризации для переносимого развертывания.

**GitLab CI/CD Pipeline** — автоматизированный конвейер для сборки, тестирования и развертывания кода. Базовые концепции (Pipeline, Stage, Job, Runner, Artifact) описаны в [Основах GitLab CI/CD](../Concepts/gitlab_ci_basics.md).

**Kaniko** — инструмент для сборки Docker-образов без демона Docker. Подробное описание в [Сборка образов с Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md).

---

## Основные концепции

### Архитектура пайплайна

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Коммит    │────▶│  Build Stage │────▶│ Deploy Stage│
│   в GitLab  │     │   (Kaniko)   │     │  (SSH + Compose)│
└─────────────┘     └──────────────┘     └─────────────┘
                           │                      │
                           ▼                      ▼
                    GitLab Container Registry  Production Server
```

### Этапы развертывания

1. **Build**: Сборка Docker-образа через Kaniko, отправка в [GitLab Container Registry](../../../Docker/docker_registries.md).
2. **Deploy**: SSH-подключение к серверу, загрузка образа, перезапуск контейнера через `docker compose`.

### Требования к инфраструктуре

- **GitLab Runner** с тегом `docker` (для сборки)
- **Удаленный сервер** с Docker и Docker Compose
- **SSH-доступ** с ключом для аутентификации
- **Переменные CI/CD** для хранения секретов

---

## Практические сценарии

### Сценарий 1: Настройка сервера

#### Установка Docker

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh ./get-docker.sh
```

#### Запуск GitLab Runner

```bash
docker run -d --name gitlab-runner --restart always \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:alpine
```

#### Регистрация Runner в проекте

Токен регистрации: `Settings > CI/CD > Runners`.

```bash
docker run --rm -it -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  gitlab/gitlab-runner:alpine register \
  --non-interactive \
  --url "https://gitlab.com/" \
  --registration-token "<ВАШ_REGISTRATION_TOKEN>" \
  --executor docker \
  --description "Docker Runner для Spring Boot" \
  --tag-list "docker" \
  --docker-image alpine:latest \
  --docker-privileged \
  --docker-volumes "/certs/client"
```

#### Аутентификация в GitLab Registry

1. Создать Personal Access Token: `User Profile > Access Tokens` (права `read_registry`, `write_registry`).
2. Выполнить вход на сервере:

```bash
docker login registry.gitlab.com -u "<USERNAME>" -p "<ACCESS_TOKEN>"
```

#### Настройка SSH для деплоя

```bash
# Генерация ключа
ssh-keygen -t rsa -b 4096 -C "gitlab-ci-deploy"

# Добавление публичного ключа
cat ~/.ssh/id_rsa.pub >> ~/.ssh/authorized_keys

# Получение приватного ключа для копирования в GitLab
cat ~/.ssh/id_rsa
```

#### Переменные GitLab CI/CD

Настроить в `Settings > CI/CD > Variables`:

| Переменная | Тип | Значение |
|------------|-----|----------|
| `SSH_PRIVATE_KEY` | File | Содержимое `id_rsa` |
| `SERVER_USER` | Variable | SSH-пользователь (например, `root`) |
| `SERVER_HOST` | Variable | IP-адрес сервера |
| `ENV_FILE` | File | Переменные для docker-compose |

Пример содержимого `ENV_FILE`:

```
TEST_SERVICE_PORT=8080
OPEN_API_TITLE=My Spring App
```

---

### Сценарий 2: Конфигурация проекта

#### `docker-compose.yml`

```yaml
version: '3.9'
services:
  core:
    container_name: spring-application
    image: ${CI_REGISTRY_IMAGE}:latest
    environment:
      TEST_SERVICE_PORT: ${TEST_SERVICE_PORT}
      OPEN_API_TITLE: ${OPEN_API_TITLE}
    ports:
      - "8081:${TEST_SERVICE_PORT}"
    logging:
      driver: 'json-file'
      options:
        max-size: '100m'
        max-file: '3'
```

#### `Dockerfile`

```dockerfile
FROM maven:3.8-openjdk-17-slim

RUN mkdir -p /home/app
WORKDIR /home/app

ADD pom.xml /home/app
ADD src /home/app/src

RUN mvn clean package

CMD ["java", "-jar", "/home/app/target/test-0.0.1-SNAPSHOT.jar"]
```

#### `.gitlab-ci.yml`

```yaml
stages:
  - build
  - deploy

build-only-MR:
  stage: build
  tags:
    - docker
  image:
    name: gcr.io/kaniko-project/executor:v1.24.0-debug
    entrypoint: [""]
  script:
    - /kaniko/executor \
      --context "${CI_PROJECT_DIR}" \
      --dockerfile "${CI_PROJECT_DIR}/Dockerfile" \
      --no-push
  only:
    - merge_requests

build:
  stage: build
  tags:
    - docker
  image:
    name: gcr.io/kaniko-project/executor:v1.24.0-debug
    entrypoint: [""]
  script:
    - /kaniko/executor \
      --context "${CI_PROJECT_DIR}" \
      --dockerfile "${CI_PROJECT_DIR}/Dockerfile" \
      --destination "${CI_REGISTRY_IMAGE}:latest"
  only:
    - main

deploy:
  stage: deploy
  image: docker:27.3-git
  tags:
    - gitlab-org-docker
  variables:
    DOCKER_HOST: "ssh://${SERVER_USER}@${SERVER_HOST}"
  before_script:
    - mkdir -p ~/.ssh
    - chmod 700 ~/.ssh
    - eval $(ssh-agent -s)
    - echo "${SSH_PRIVATE_KEY}" | tr -d '\r' | ssh-add -
    - '[[ -f /.dockerenv || -d /run/secrets/kubernetes.io/serviceaccount ]] && echo -e "Host *\n  StrictHostKeyChecking no\n\n" > ~/.ssh/config'
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - docker compose --env-file $ENV_FILE pull
    - docker compose --env-file $ENV_FILE down --timeout=60 --remove-orphans
    - docker compose --env-file $ENV_FILE up --build --detach
    - docker image prune -f || true
  only:
    - main
  when: manual
```

---

### Сценарий 3: Анализ конфигурации

#### Этап `build`

- **`build-only-MR`**: Сборка образа для Merge Request без отправки в Registry (`--no-push`). Проверка собираемости без загрязнения реестра.
- **`build`**: Сборка и публикация образа с тегом `latest` при коммите в `main`.

#### Этап `deploy`

- **`when: manual`**: Ручной запуск для контроля релиза.
- **`DOCKER_HOST`**: Перенаправление Docker CLI на удаленный сервер через SSH.
- **`before_script`**:
  - Настройка SSH-агента и добавление приватного ключа.
  - Отключение проверки хоста (`StrictHostKeyChecking no`) для эфемерных окружений.
  - Аутентификация в GitLab Registry.
- **`script`**:
  - Загрузка нового образа (`pull`).
  - Остановка старых контейнеров (`down`).
  - Запуск новой версии (`up --detach`).
  - Очистка неиспользуемых образов (`prune`).

---

## Дополнительная информация

### Безопасность

- **SSH-ключи**: Хранить в переменных типа `File`, не в plain text.
- **Registry Credentials**: Использовать встроенные переменные `$CI_REGISTRY_USER` и `$CI_REGISTRY_PASSWORD`.
- **Привилегии Runner**: `--docker-privileged` требуется для Docker-in-Docker, но Kaniko работает без привилегий (см. [dockerfile_kaniko.md](../../../Docker/Dockerfile/dockerfile_kaniko.md)).

### Альтернативные подходы

- **Docker Buildx**: Для кроссплатформенной сборки (ARM/AMD).
- **Cloud Runners**: Использование managed runners GitLab.com вместо self-hosted.
- **Kubernetes Deployment**: Развертывание через `kubectl` вместо SSH + Compose.

### Ссылки

- [Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md) — базовые концепции.
- [Сборка образов с Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md) — безопасная сборка без демона.
- [Docker Registry](../../../Docker/docker_registries.md) — работа с реестрами образов.
- [GitLab CI/CD Variables](../Concepts/gitlab_ci_variables_secrets.md) — управление секретами.
