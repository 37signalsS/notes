# Деплой Spring Boot в GitLab CI/CD с использованием Docker

## Определения

**Spring Boot** — фреймворк для создания автономных Java-приложений. В CI/CD процессе требует компиляции исходного кода (Maven/Gradle), сборки JAR/WAR артефакта и последующей контейнеризации.

**GitLab CI/CD пайплайн** — автоматизированный конвейер, управляемый через `.gitlab-ci.yml`. Основные компоненты описаны в **[Основах GitLab CI/CD](../Concepts/gitlab_ci_basics.md)**.

**Kaniko** — инструмент для сборки Docker-образов внутри контейнера без доступа к сокету хоста (`/var/run/docker.sock`), что является стандартом безопасности для Kubernetes-раннеров. Подробнее см. **[Сборка образов с Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md)**.

**Quality Gates (Ворота качества)** — набор автоматических проверок (тесты, линтеры), которые должны пройти успешно для перехода на следующий этап деплоя.

## Основные концепции

### Архитектура пайплайна (Modern Workflow)

```text
┌────────┐     ┌──────┐     ┌───────┐     ┌─────────┐     ┌────────┐
│ Commit │────▶│ Test │────▶│ Build │────▶│ Migrate │────▶│ Deploy │
└────────┘     └──────┘     └───────┘     └─────────┘     └────────┘
                  │            │               │               │
                  ▼            ▼               ▼               ▼
               Reports     Registry       Database      Production
```

### Ключевые этапы

1. **Тестирование (Test):** Запуск Unit и интеграционных тестов с использованием Testcontainers.
2. **Сборка (Build):** Компиляция через Maven с использованием кэширования зависимостей и сборка образа через Kaniko.
3. **Миграция (Migrate):** Применение изменений схемы БД через Flyway или Liquibase до развертывания новой версии приложения.
4. **Развертывание (Deploy):** Обновление контейнеров на удаленном хосте через SSH и Docker Compose.
5. **Верификация (Verify):** Выполнение Smoke-тестов для проверки доступности эндпоинтов после деплоя.

## Практические сценарии

### Шаг 1: Подготовка инфраструктуры и секретов

1. **Сервер:** Убедитесь, что на целевом сервере установлены Docker 24+ и Docker Compose v2. См. **[Установку Docker на Ubuntu](../../../Docker/docker_install_ubuntu.md)**.
2. **Переменные CI/CD:** В `Settings > CI/CD > Variables` добавьте:

| Переменная | Тип | Описание |
| :--- | :--- | :--- |
| `SSH_PRIVATE_KEY` | **File** | Приватный ключ для доступа к серверу. Добавьте соответствующий `public key` в `~/.ssh/authorized_keys` на сервере. |
| `SSH_KNOWN_HOSTS` | Variable | Результат команды `ssh-keyscan <ip_сервера>`. Защищает от MitM. |
| `SERVER_USER` | Variable | Имя пользователя (например, `deploy-user`). |
| `SERVER_HOST` | Variable | IP или FQDN сервера. |
| `SPRING_PROFILES_ACTIVE` | Variable | Активный профиль (например, `prod`). |

### Шаг 2: Конфигурация проекта

#### `Dockerfile` (Оптимизированный multi-stage)

```dockerfile
# Stage 1: Build
FROM maven:3.9-eclipse-temurin-21-jammy AS build
WORKDIR /app
# Кэширование зависимостей Maven
COPY pom.xml .
RUN mvn dependency:go-offline -B
COPY src ./src
RUN mvn clean package -DskipTests

# Stage 2: Runtime
FROM eclipse-temurin:21-jre-jammy
RUN useradd -m springuser
USER springuser
WORKDIR /app
COPY --from=build /app/target/*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
```

#### `.gitlab-ci.yml`

```yaml
stages:
  - test
  - build
  - migrate
  - deploy
  - verify

variables:
  DOCKER_IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  MAVEN_OPTS: "-Dmaven.repo.local=$CI_PROJECT_DIR/.m2/repository"

# Кэширование Maven зависимостей
cache:
  paths:
    - .m2/repository

test_job:
  stage: test
  image: maven:3.9-eclipse-temurin-21-jammy
  script:
    - mvn test
  artifacts:
    when: always
    reports:
      junit: target/surefire-reports/*.xml

build_image:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.24.0-debug
    entrypoint: [""]
  script:
    - /kaniko/executor
      --context "${CI_PROJECT_DIR}"
      --dockerfile "${CI_PROJECT_DIR}/Dockerfile"
      --destination "${DOCKER_IMAGE}"
      --destination "${CI_REGISTRY_IMAGE}:latest"

db_migration:
  stage: migrate
  image: maven:3.9-eclipse-temurin-21-jammy
  script:
    - mvn flyway:migrate -Dflyway.url=$DB_URL -Dflyway.user=$DB_USER -Dflyway.password=$DB_PASSWORD
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy_prod:
  stage: deploy
  image: docker:27.3
  variables:
    DOCKER_HOST: "ssh://${SERVER_USER}@${SERVER_HOST}"
  before_script:
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
    - eval $(ssh-agent -s)
    - echo "${SSH_PRIVATE_KEY}" | tr -d '\r' | ssh-add -
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
  script:
    - docker compose pull
    - docker compose up -d --remove-orphans
    - docker image prune -f
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual

smoke_test:
  stage: verify
  image: curlimages/curl:latest
  script:
    - sleep 30 # Ожидание запуска приложения
    - curl -f http://${SERVER_HOST}:8080/actuator/health | grep "UP"
    # → {"status":"UP"}
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

## Технические нюансы и Тюнинг

### Оптимизация производительности
1. **Maven Offline:** Использование `dependency:go-offline` в первом слое Docker-образа позволяет эффективно использовать Docker-кэш для библиотек.
2. **Local Repository:** Переопределение `MAVEN_OPTS` для хранения репозитория в папке проекта позволяет GitLab CI кэшировать его между запусками пайплайнов.

### Безопасность SSH
Всегда используйте `SSH_KNOWN_HOSTS`. Без этого шага задача деплоя уязвима для атак типа "человек посередине" (Man-in-the-Middle), так как Runner будет слепо доверять любому ключу сервера при первом подключении.

### База данных
Миграции (`db_migration`) должны выполняться **до** деплоя приложения. Если миграция ломает обратную совместимость, используйте стратегии Blue/Green деплоя.

## Дополнительная информация

### Мониторинг
Для Spring Boot приложений рекомендуется настроить **Spring Boot Actuator** и интегрировать его с **[Prometheus](../../../Prometheus/overview.md)** для отслеживания состояния JVM и бизнес-метрик.

### Смотрите также

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — база.
- **[Сборка образов с Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md)** — безопасность сборки.
- **[Переменные и секреты в GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)** — работа с типами `File` и `Masked`.
- **[Docker Registry](../../../Docker/docker_registries.md)** — управление образами.
