# Развертывание Spring Boot в GitLab CI с использованием Docker

## Определения

- **Spring Boot** — фреймворк для создания standalone Java-приложений с минимальной конфигурацией. В контексте CI/CD требует сборки JAR-артефакта и последующей контейнеризации.
- **GitLab CI/CD пайплайн** — автоматизированный конвейер для сборки, тестирования и развертывания кода. Базовые концепции (Pipeline, Stage, Job, Runner, Artifact) описаны в **[Основах GitLab CI/CD](../Concepts/gitlab_ci_basics.md)**.
- **Kaniko** — инструмент для сборки Docker-образов внутри контейнера без использования демона Docker. Подробное описание в **[Сборке образов с Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md)**.
- **SSH-агент** — программа для хранения приватных ключей, используемая для аутентификации при SSH-подключениях без интерактивного ввода пароля.

## Основные концепции

### Архитектура пайплайна

```text
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Коммит    │────▶│  Build Stage │────▶│ Deploy Stage│
│   в GitLab  │     │   (Kaniko)   │     │  (SSH + Compose)│
└─────────────┘     └──────────────┘     └─────────────┘
                           │                      │
                           ▼                      ▼
                    GitLab Container Registry  Production Server
```

### Этапы развертывания

1. **Сборка (Build)**: Компиляция приложения и сборка Docker-образа с помощью Kaniko. Образ публикуется во встроенном **[GitLab Container Registry](../../../Docker/docker_registries.md)**.
2. **Развертывание (Deploy)**: Подключение к целевому серверу по SSH, загрузка (pull) новой версии образа и перезапуск контейнера через Docker Compose.

### Требования к инфраструктуре

- **GitLab Runner**: С настроенным Docker executor (см. **[Регистрация GitLab Runner](./runner_registration.md)**).
- **Удаленный сервер**: С установленными Docker и Docker Compose (см. **[Установку Docker на Ubuntu](../../../Docker/docker_install_ubuntu.md)**).
- **Сетевой доступ**: Открытый SSH-порт на сервере и корректно настроенные переменные CI/CD для аутентификации.

## Практические сценарии

### Шаг 1: Подготовка сервера и переменных

Перед настройкой пайплайна необходимо подготовить среду исполнения.

1. **Установка Docker**: Убедитесь, что на целевом сервере установлены Docker Engine и Docker Compose. Инструкции доступны в **[Установке Docker на Ubuntu](../../../Docker/docker_install_ubuntu.md)**.
2. **Настройка SSH-доступа**:
    - Сгенерируйте SSH-ключ для нужд CI/CD.
    - Добавьте публичный ключ в файл `~/.ssh/authorized_keys` на сервере.
3. **Переменные GitLab CI/CD**: В интерфейсе GitLab (`Settings > CI/CD > Variables`) добавьте следующие переменные:

| Переменная | Тип | Описание |
| :--- | :--- | :--- |
| `SSH_PRIVATE_KEY` | **File** | Содержимое приватного SSH-ключа. |
| `SERVER_USER` | Variable | Имя пользователя для подключения (например, `root`). |
| `SERVER_HOST` | Variable | IP-адрес или DNS-имя сервера. |
| `ENV_FILE` | **File** | Содержимое файла `.env` для конфигурации Docker Compose. |

### Шаг 2: Конфигурация проекта

Для работы пайплайна в корне репозитория должны находиться следующие файлы.

#### `Dockerfile`

Использование многостадийной сборки (multi-stage) позволяет уменьшить размер итогового образа.

```dockerfile
FROM maven:3.8-openjdk-17-slim AS build
WORKDIR /home/app
COPY pom.xml .
COPY src ./src
RUN mvn clean package -DskipTests

FROM openjdk:17-jdk-slim
WORKDIR /app
COPY --from=build /home/app/target/*.jar app.jar
EXPOSE 8080
CMD ["java", "-jar", "app.jar"]
```

#### `docker-compose.yml`

```yaml
version: '3.9'
services:
  app:
    image: ${CI_REGISTRY_IMAGE}:latest
    container_name: spring-boot-app
    env_file: .env
    ports:
      - "8080:${APP_PORT:-8080}"
    restart: always
```

#### `.gitlab-ci.yml`

```yaml
stages:
  - build
  - deploy

build:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.24.0-debug
    entrypoint: [""]
  script:
    - /kaniko/executor
      --context "${CI_PROJECT_DIR}"
      --dockerfile "${CI_PROJECT_DIR}/Dockerfile"
      --destination "${CI_REGISTRY_IMAGE}:latest"
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

deploy:
  stage: deploy
  image: docker:27.3
  variables:
    DOCKER_HOST: "ssh://${SERVER_USER}@${SERVER_HOST}"
  before_script:
    - mkdir -p ~/.ssh
    - chmod 700 ~/.ssh
    - eval $(ssh-agent -s)
    - echo "${SSH_PRIVATE_KEY}" | tr -d '\r' | ssh-add -
    - '[[ -f /.dockerenv ]] && echo -e "Host *\n  StrictHostKeyChecking no\n\n" > ~/.ssh/config'
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - cp "$ENV_FILE" .env
    - docker compose pull
    - docker compose up -d --remove-orphans
    - docker image prune -f
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual
```

### Шаг 3: Анализ работы пайплайна

1. **Этап Build**: Kaniko собирает образ и пушит его в Registry. Мы используем тег `latest` для упрощения деплоя, но в production рекомендуется использовать `$CI_COMMIT_SHORT_SHA` (см. **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)**).
2. **Этап Deploy**:
    - Переменная `DOCKER_HOST` указывает Docker CLI подключаться к удаленному серверу через SSH-туннель.
    - `ssh-agent` обеспечивает аутентификацию без пароля.
    - `docker compose pull` гарантирует, что на сервер будет загружена самая свежая версия образа из Registry.
    - `docker image prune -f` удаляет старые (dangling) образы, освобождая место на диске.

## Дополнительная информация

### Безопасность

- **Секреты**: Никогда не храните пароли или ключи в коде. Используйте переменные типа `File` для ключей и сертификатов (подробнее в **[Управлении секретами](../Concepts/gitlab_ci_variables_secrets.md)**).
- **Изоляция**: Kaniko работает без доступа к Docker-сокету хоста, что повышает безопасность Runner'а.

### Альтернативные подходы

- **Kubernetes**: Для крупных проектов рекомендуется переход на **[интеграцию с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** и использование Helm.
- **GitOps**: Рассмотрите использование Push-модели через **[ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md)** для более надежного развертывания.

### Ссылки

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)**
- **[Сборка образов с Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md)**
- **[Docker Registry](../../../Docker/docker_registries.md)**
- **[GitLab CI/CD Variables](../Concepts/gitlab_ci_variables_secrets.md)**
