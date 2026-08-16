# Деплой Spring Boot в GitLab CI/CD с использованием Docker

## Определения

**Spring Boot** — современный Java-фреймворк для создания автономных микросервисов. В контексте CI/CD требует разделения этапов компиляции (JDK + Maven/Gradle) и исполнения (JRE).

**GitLab Agent for Kubernetes (KAS)** — рекомендуемый в 2026 году механизм интеграции, обеспечивающий безопасный **CI/CD Tunnel** без передачи статических `KUBECONFIG`.

**id_tokens (OIDC)** — механизм генерации временных JWT-токенов для федерации идентичности. Используется для безопасной аутентификации в HashiCorp Vault или облачных провайдерах без хранения паролей в GitLab.

**Kaniko** — инструмент для сборки Docker-образов «внутри» контейнера (userspace). Является стандартом безопасности, так как не требует привилегированного доступа к `/var/run/docker.sock`.

**SBOM (Software Bill of Materials)** — список всех компонентов и библиотек в образе. Необходим для аудита безопасности и проверки цепочки поставок (Supply Chain Security).

**Quality Gates (Ворота качества)** — набор автоматизированных проверок (Unit-тесты, линтеры, сканеры CVE), которые блокируют продвижение артефакта при несоблюдении критериев качества.

## Основные концепции

### Архитектура пайплайна (Lifecycle 2026)

Современный процесс доставки Spring Boot приложения ориентирован на безопасность и скорость обратной связи:

```text
┌────────┐     ┌──────────┐     ┌───────┐     ┌─────────┐     ┌────────┐
│ Commit │────▶│ Validate │────▶│ Build │────▶│ Scan/QA │────▶│ Deploy │
└────────┘     └──────────┘     └───────┘     └─────────┘     └────────┘
                  │ (Checkstyle)   │ (Kaniko)    │ (Trivy)       │ (SSH/K8s)
                  ▼                ▼             ▼               ▼
               Linter           Artifact      SBOM/CVE        Production
```

### Принципы сборки Java в Docker

1.  **Multi-stage сборка:** Обязательна. Первый этап (`builder`) содержит тяжелый JDK и кэш Maven, второй этап (`runtime`) содержит только легковесную JRE и `.jar` файл. Это сокращает размер образа на 600МБ+ и минимизирует поверхность атаки.
2.  **Управление зависимостями:** Использование `go-offline` режима в Maven или кэширования Gradle-демона позволяет сократить время сборки с минут до секунд.
3.  **Безопасность рантайма:** Запуск Java-приложения от имени непривилегированного пользователя (`non-root`) — критическое требование безопасности.
4.  **Миграции БД:** Изменения схемы (Flyway/Liquibase) должны выполняться **до** запуска приложения, но **после** успешной сборки артефакта.

## Практические сценарии

### Предварительные требования

**Окружение:**
- **Runner:** GitLab Runner с тегом `docker-runner`.
- **Target:** Сервер с Docker 27.0+ и поддержкой SSH-ключей.
- **Java:** Версия 21 (LTS).

**Переменные CI/CD (Settings > CI/CD > Variables):**
| Переменная | Тип | Назначение |
| :--- | :--- | :--- |
| `SSH_PRIVATE_KEY` | **File** | Приватный ключ для деплоя. |
| `SSH_KNOWN_HOSTS` | Variable | Отпечаток (fingerprint) целевого сервера. |
| `DB_URL` / `DB_PASS` | Variable | Учетные данные для миграций. |

### Шаг 1: Оптимизированный Dockerfile (Multi-stage + Security)

Используем Eclipse Temurin как наиболее стабильный и совместимый дистрибутив OpenJDK.

```dockerfile
# syntax=docker/dockerfile:1

# --- Stage 1: Build (Maven Cache Optimization) ---
FROM maven:3.9-eclipse-temurin-21-jammy AS builder
WORKDIR /app

# Копируем только описание зависимостей для создания кеш-слоя
COPY pom.xml .
RUN mvn dependency:go-offline -B

# Копируем исходный код и собираем проект
COPY src ./src
RUN mvn clean package -DskipTests

# --- Stage 2: Runtime (Hardened JRE) ---
FROM eclipse-temurin:21-jre-jammy
WORKDIR /app

# Создаем пользователя для безопасности
RUN useradd -m -u 10001 springuser && \
    chown -R springuser:springuser /app

# Копируем только артефакт
COPY --from=builder /app/target/*.jar app.jar

USER 10001
ENV JAVA_OPTS="-Xmx512m -Xms256m"
EXPOSE 8080

# Использование exec-формы для корректной передачи сигналов (SIGTERM)
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]
```

### Шаг 2: Конфигурация пайплайна `.gitlab-ci.yml`

Используем современные механизмы кэширования и интеграцию с Kaniko.

```yaml
stages:
  - test
  - build
  - scan
  - migrate
  - deploy

variables:
  IMAGE_NAME: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  MAVEN_CLI_OPTS: "-Dmaven.repo.local=$CI_PROJECT_DIR/.m2/repository"

# Глобальный кэш зависимостей
cache:
  key: "$CI_COMMIT_REF_SLUG"
  paths:
    - .m2/repository

# 1. Тестирование и линтинг
unit_tests:
  stage: test
  image: maven:3.9-eclipse-temurin-21-jammy
  script:
    - mvn $MAVEN_CLI_OPTS test
  artifacts:
    when: always
    reports:
      junit: target/surefire-reports/*.xml
  tags: [docker-runner]

# 2. Безопасная сборка образа
build_image:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.24.0-debug
    entrypoint: [""]
  script:
    - /kaniko/executor
      --context "${CI_PROJECT_DIR}"
      --dockerfile "${CI_PROJECT_DIR}/Dockerfile"
      --destination "${IMAGE_NAME}"
      --destination "${CI_REGISTRY_IMAGE}:latest"
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# 3. Сканирование на уязвимости и SBOM
vulnerability_scan:
  stage: scan
  image: aquasec/trivy:latest
  script:
    - trivy image --format json --output report.json $IMAGE_NAME
    - trivy image --format cyclonedx --output sbom.json $IMAGE_NAME
  artifacts:
    reports:
      cyclonedx: sbom.json
    paths: [report.json]
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# 4. Миграция базы данных
database_migrate:
  stage: migrate
  image: maven:3.9-eclipse-temurin-21-jammy
  script:
    - mvn $MAVEN_CLI_OPTS flyway:migrate -Dflyway.url=$DB_URL -Dflyway.user=$DB_USER -Dflyway.password=$DB_PASSWORD
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual

# 5. Деплой через SSH
deploy_ssh:
  stage: deploy
  image: docker:27.0
  variables:
    DOCKER_HOST: "ssh://${SERVER_USER}@${SERVER_HOST}"
  before_script:
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
    - eval $(ssh-agent -s)
    - chmod 600 "$SSH_PRIVATE_KEY"
    - ssh-add "$SSH_PRIVATE_KEY"
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
  script:
    - docker compose pull
    - docker compose up -d --remove-orphans
    - docker image prune -f
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

## Валидация и проверка

Для подтверждения корректности деплоя выполните:
1.  **JUnit Reports:** Проверьте вкладку **Tests** в пайплайне — там должны отображаться результаты всех тестов.
2.  **Actuator Health:** Выполните запрос к эндпоинту здоровья:
    ```bash
    curl -f http://server-host:8080/actuator/health
    # Ожидаемый результат: {"status":"UP"}
    ```
3.  **Logs Validation:** Проверьте логи контейнера на наличие ошибок запуска: `docker logs -f app_container_name`.

## Технические нюансы и Тюнинг

### Работа с Testcontainers
Если ваши интеграционные тесты используют **Testcontainers**, раннеру необходим доступ к Docker. В Docker Executor это достигается через:
- Использование сервиса `docker:dind`.
- Или проброс сокета (менее безопасно).
Подробнее см. **[Testcontainers: Роль в CI/CD](../../../Testing/testcontainers_overview.md)**.

### Оптимизация памяти JVM
В контейнере Java должна "видеть" лимиты Docker. В Java 17+ это работает автоматически, но рекомендуется явно задавать `-XX:MaxRAMPercentage=75.0`, чтобы JVM не пыталась захватить всю память хост-системы.

### Устранение неполадок (Troubleshooting)

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **502 Bad Gateway** | Приложение еще не поднялось | Увеличьте `initialDelay` или время ожидания в Smoke-тестах. |
| **Permission Denied (SSH)** | Неверный ключ или права на файл | Убедитесь, что `SSH_PRIVATE_KEY` имеет тип **File** и права 600. |
| **OOM Kill** | JVM вышла за пределы лимитов Docker | Согласуйте `-Xmx` и `resources.limits.memory` в Compose. |
| **Flyway Checksum Mismatch** | Изменен существующий скрипт миграции | Никогда не меняйте старые файлы миграций, создавайте новые. |

## Дополнительная информация

### Мониторинг
Интегрируйте Spring Boot Actuator с Micrometer для сбора метрик в формате Prometheus. См. руководство по **[Prometheus: Сбор метрик Java](../../../Prometheus/overview.md)**.

### Смотрите также
- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — базовый синтаксис.
- **[Сборка с Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md)** — детализация безопасности.
- **[Переменные и секреты GitLab](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md)** — OIDC и маскирование.
