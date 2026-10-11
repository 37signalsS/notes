# Деплой Spring Boot в GitLab CI/CD с использованием Docker

**Актуально для:** GitLab 19.x / GitLab Runner 19.x / Java 21

Практическое руководство по организации CI/CD пайплайна для Spring Boot приложения: сборка, сканирование, миграции БД и деплой через SSH на целевой сервер с использованием Docker Compose.

---

## Определения

**Spring Boot** — современный Java-фреймворк для создания автономных микросервисов. В контексте CI/CD требует разделения этапов компиляции (JDK + Maven/Gradle) и исполнения (JRE).

**id_tokens (OIDC)** — механизм генерации временных JWT-токенов для федерации идентиности. Используется для безопасной аутентификации между компонентами CI/CD без хранения статических паролей в GitLab Variables.

**Kaniko** — инструмент для сборки Docker-образов «внутри» контейнера (userspace). Является стандартом безопасности, так как не требует привилегированного доступа к `/var/run/docker.sock`.

**SBOM (Software Bill of Materials)** — список всех компонентов и библиотек в образе. Необходим для аудита безопасности и проверки цепочки поставок (Supply Chain Security).

**Quality Gates (Ворота качества)** — набор автоматизированных проверок (Unit-тесты, линтеры, сканеры CVE), которые блокируют продвижение артефакта при несоблюдении критериев качества.

**Docker-in-Docker (DinD)** — технология, позволяющая собирать и запускать Docker-образы внутри контейнера. В данном руководстве используется через проброс сокета `/var/run/docker.sock` или сервис `docker:dind`.

## Основные концепции

### Архитектура пайплайна (Lifecycle)

Современный процесс доставки Spring Boot приложения ориентирован на безопасность и скорость обратной связи:

```text
┌────────┐     ┌──────────┐     ┌───────┐     ┌─────────┐     ┌────────┐
│ Commit │────▶│ Validate │────▶│ Build │────▶│ Scan/QA │────▶│ Deploy │
└────────┘     └──────────┘     └───────┘     └─────────┘     └────────┘
                  │ (Checkstyle)   │ (Kaniko)    │ (Trivy)       │ (SSH)
                  ▼                ▼             ▼               ▼
               Linter           Artifact      SBOM/CVE        Production
```

### Принципы сборки Java в Docker

1.  **Multi-stage сборка:** Обязательна. Первый этап (`builder`) содержит тяжелый JDK и кэш Maven, второй этап (`runtime`) содержит только легковесную JRE и `.jar` файл. Это сокращает размер образа на 600МБ+ и минимизирует поверхность атаки.
2.  **Управление зависимостями:** Использование `go-offline` режима в Maven или кэширования Gradle-демона позволяет сократить время сборки с минут до секунд.
3.  **Безопасность рантайма:** Запуск Java-приложения от имени непривилегированного пользователя (`non-root`) — критическое требование безопасности.
4.  **Миграции БД:** Изменения схемы (Flyway/Liquibase) должны выполняться **до** запуска приложения, но **после** успешной сборки артефакта.

### Безопасность и риски Docker Socket

Проброс `/var/run/docker.sock` внутрь контейнера Runner'а дает ему права суперпользователя на хост-системе.
*   **Dev-окружение:** Допустимо для локальных тестов и сборки образов.
*   **Production:** Категорически запрещено. Используйте изолированные виртуальные машины или Kaniko для сборки без привилегий.

### Хранение данных и артефактов

GitLab Registry и артефакты пайплайна требуют управления жизненным циклом:
*   **Registry:** Хранит Docker-образы. По умолчанию не ограничивает количество тегов — требуется политика очистки.
*   **Artifacts:** Временные файлы (JUnit-отчеты, SBOM). Имеют встроенное TTL (`artifacts:expire_in`).
*   **Cache:** Зависимости Maven/Gradle. По умолчанию не имеют TTL — требует периодической очистки.

## Практические сценарии

### Предварительные требования

**Окружение:**
*   **Runner:** GitLab Runner с тегом `docker-runner` (Docker Executor).
*   **Target:** Сервер с Docker 27.0+ и поддержкой SSH-ключей.
*   **Java:** Версия 21 (LTS).

**Аппаратные ресурсы:**
*   **RAM:** 8 ГБ (минимум 4 ГБ для Runner'а).
*   **Диск:** SSD, минимум 20 ГБ свободного места для образов и кэша.

**Переменные CI/CD (Settings > CI/CD > Variables):**
| Переменная | Тип | Назначение |
| :--- | :--- | :--- |
| `SSH_PRIVATE_KEY` | **File** | Приватный ключ для деплоя. |
| `SSH_KNOWN_HOSTS` | Variable | Отпечаток (fingerprint) целевого сервера. |
| `DB_URL` / `DB_USER` / `DB_PASS` | Variable | Учетные данные для миграций. |
| `SERVER_USER` / `SERVER_HOST` | Variable | Целевой сервер для деплоя. |

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

# Healthcheck для Docker
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8080/actuator/health || exit 1

USER 10001
ENV JAVA_OPTS="-Xmx512m -Xms256m -XX:MaxRAMPercentage=75.0 -XX:+UseG1GC"
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
    expire_in: 1 week
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
  tags: [docker-runner]

# 3. Сканирование на уязвимости и SBOM
vulnerability_scan:
  stage: scan
  image: aquasec/trivy:0.74.0
  script:
    - trivy image --format json --output report.json $IMAGE_NAME
    - trivy image --format cyclonedx --output sbom.json $IMAGE_NAME
  artifacts:
    reports:
      cyclonedx: sbom.json
    paths: [report.json]
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  tags: [docker-runner]
  allow_failure: false

# 4. Миграция базы данных
database_migrate:
  stage: migrate
  image: maven:3.9-eclipse-temurin-21-jammy
  script:
    - mvn $MAVEN_CLI_OPTS flyway:migrate -Dflyway.url=$DB_URL -Dflyway.user=$DB_USER -Dflyway.password=$DB_PASSWORD
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  tags: [docker-runner]

# 5. Деплой через SSH
deploy_ssh:
  stage: deploy
  image: docker:29.8
  services:
    - docker:29.8-dind
  variables:
    DOCKER_HOST: "tcp://docker:2376"
    DOCKER_TLS_CERTDIR: "/certs"
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
  tags: [docker-runner]
```

### Шаг 3: Docker Compose для целевого сервера

На целевом сервере создайте `docker-compose.yml`:

```yaml
services:
  app:
    image: ${IMAGE_NAME}
    restart: always
    ports:
      - "8080:8080"
    environment:
      - SPRING_DATASOURCE_URL=${DB_URL}
      - SPRING_DATASOURCE_USERNAME=${DB_USER}
      - SPRING_DATASOURCE_PASSWORD=${DB_PASSWORD}
      - JAVA_OPTS=-Xmx512m -Xms256m -XX:MaxRAMPercentage=75.0
    volumes:
      - ./logs:/app/logs
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/actuator/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    deploy:
      resources:
        limits:
          memory: 1G
        reservations:
          memory: 512M
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
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
4.  **Smoke Test:** Проверьте ключевые эндпоинты приложения: `curl -f http://server-host:8080/api/health`.

## Технические нюансы и Тюнинг

### Работа с Testcontainers

Если ваши интеграционные тесты используют **Testcontainers**, раннеру необходим доступ к Docker. В Docker Executor это достигается через:
- Использование сервиса `docker:dind` в пайплайне.
- Или проброс сокета (менее безопасно).
Подробнее см. **[Testcontainers: Роль в CI/CD](../../../Testing/testcontainers_overview.md)**.

### Оптимизация памяти JVM

В контейнере Java должна "видеть" лимиты Docker. В Java 17+ это работает автоматически, но рекомендуется явно задавать `-XX:MaxRAMPercentage=75.0`, чтобы JVM не пыталась захватить всю память хост-системы.

### Ротация логов Docker

На хосте Runner'а настройте ротацию логов через `daemon.json`:
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

### Очистка кэша Maven

Периодически очищайте кэш на Runner'е для предотвращения переполнения диска:
```bash
docker system prune -af
docker volume prune -af
```

### Устранение неполадок (Troubleshooting)

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **502 Bad Gateway** | Приложение еще не поднялось после деплоя | Увеличьте `initialDelay` в healthcheck или время ожидания в Smoke-тестах. Добавьте `readinessProbe` с `periodSeconds: 10`. |
| **Permission Denied (SSH)** | Неверный ключ или права на файл | Убедитесь, что `SSH_PRIVATE_KEY` имеет тип **File** и права 600. Проверьте `ssh-rsa` формат ключа. |
| **OOM Kill** | JVM вышла за пределы лимитов Docker | Согласуйте `-Xmx` и `resources.limits.memory` в Compose. Используйте `-XX:MaxRAMPercentage=75.0` вместо фиксированных значений. |
| **Flyway Checksum Mismatch** | Изменен существующий скрипт миграции | Никогда не меняйте старые файлы миграций — создавайте новые. Откат: `flyway repair`. |
| **Maven: No compiler is provided** | JDK не найден в контейнере Builder | Убедитесь, что базовый образ содержит JDK (не JRE). Используйте `maven:3.9-eclipse-temurin-21-jammy`. |
| **Kaniko: Failed to get credential** | Container Registry авторизация не настроена | Проверьте переменные `CI_REGISTRY_USER` и `CI_JOB_TOKEN`. GitLab автоматически предоставляет токен для встроенного Registry. |
| **Container repeatedly перезапускается (CrashLoopBackOff)** | Приложение падает при старте | Проверьте логи: `docker logs <container>`. Частые причины: невалидный `SPRING_DATASOURCE_URL`, отсутствие миграций, нехватка памяти. |
| **Image not found в Registry** | Имя образа не совпадает или Registry недоступен | Проверьте `IMAGE_NAME` переменную. Убедитесь, что `docker login` проходит успешно в before_script. |
| **Testcontainers: Cannot connect to Docker** | Docker-in-Docker не настроен или Socket не проброшен | Добавьте сервис `docker:dind` или пробросьте `/var/run/docker.sock`. Укажите `DOCKER_HOST: tcp://docker:2375`. |
| **Flyway: Connection refused** | База данных недоступна из контейнера Runner'а | Проверьте `DB_URL` — используйте внутренний адрес Docker-сети, а не `localhost`. Убедитесь, что PostgreSQL запущен и доступен. |
| **Actuator: 404 Not Found** | Endpoint не включен в конфигурации | Добавьте в `application.properties`: `management.endpoints.web.exposure.include=health,info,prometheus`. |
| **Disk space exhausted** | Локальные образы и кэш заполнили диск | Выполните `docker system prune -af` на хосте Runner'а. Настройте cron для автоматической очистки. |

## Лучшие практики (Best Practices)

**Безопасность:**
*   Используйте Kaniko вместо DinD для сборки образов — это исключает необходимость `privileged = true`.
*   Все секретные переменные (БД, SSH-ключи) храните в CI/CD Variables с флагами `masked` и `protected`.
*   Регулярно обновляйте базовые образы (Eclipse Temurin, Maven) — это закрывает CVE в зависимостях.
*   Добавьте сканирование Trivy как **обязательный** этап — блокируйте деплой при критических уязвимостях.
*   Используйте SBOM для аудита цепочки поставок (Supply Chain Security).

**Производительность:**
*   Кэшируйте `.m2/repository` между запусками пайплайна — это сокращает время сборки на 50-80%.
*   Используйте `dependency:go-offline` в Maven для предзагрузки зависимостей в отдельном слое Docker.
*   В Dockerfile копируйте `pom.xml` перед `src` — это максимизирует кэширование слоёв.
*   Настройте `JAVA_OPTS` с учётом лимитов Docker: `-XX:MaxRAMPercentage=75.0 -XX:+UseG1GC`.

**Надёжность:**
*   Используйте `when: manual` для деплоя — это предотвращает автоматический деплой из ветки feature.
*   Пинайте версии образов (Kaniko, Maven, Trivy) вместо `latest` — это гарантирует воспроизводимость.
*   Добавьте Smoke-тест после деплоя — проверяйте Actuator Health и ключевые эндпоинты.
*   Настройте `retry: 2` для сканирования и деплоя — нестабильные сети могут прервать задачу.
*   Используйте `depends_on` с `condition: service_healthy` для зависимостей от баз данных.

## Очистка и откат (Cleanup)

**Откат деплоя:**
```bash
# SSH на сервер деплоя
ssh deployer@server

# Остановка текущей версии
cd /opt/app && docker compose down

# Откат к предыдущему тегу
export IMAGE_TAG=<previous-commit-sha>
docker compose up -d

# Или через git
git checkout <previous-commit> && docker compose up -d --build
```

**Откат миграции Flyway:**
```bash
# Через Maven (среда с доступом к БД)
mvn flyway:undo -Dflyway.url=$DB_URL -Dflyway.user=$DB_USER -Dflyway.password=$DB_PASS

# Или вручную (последняя миграция)
flyway undo -url=jdbc:postgresql://host:5432/db -user=user -password=pass
```

**Очистка Container Registry:**
```bash
# Удаление старых тегов через API
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/registry/repositories/$REPO_ID/tags/<tag>"

# Очистка локального кэша образов
docker image prune -af
```

**Очистка артефактов:**
```bash
# Удаление старых артефактов пайплайна (Settings > CI/CD > Artifacts expiration)
# Или через API
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/artifacts"
```

**Очистка кэша Runner'а:**
```bash
# На хосте Runner'а
docker system prune -af --filter "until=168h"
docker volume prune -af --filter "label!=keep"
```

## Граничные случаи (Edge Cases)

**Мульти-Maven модуль:**
*   Если проект состоит из нескольких Maven-модулей, настройте кэширование на уровне корня: `key: "$CI_COMMIT_REF_SLUG"` и `paths: ["./**/.m2/repository"]`.
*   Сборка: `mvn clean package -pl module-name -am` (с зависимостями).

**Монорепозиторий:**
*   Используйте `rules:changes` для запуска пайплайна только при изменении relevant files:
  ```yaml
  rules:
    - changes: ["src/**", "pom.xml", "Dockerfile"]
  ```

**Несколько целевых серверов:**
*   Деплой на несколько серверов через SSH-ключ и `parallel`:
  ```yaml
  deploy:
    stage: deploy
    parallel:
      matrix:
        - SERVER_HOST: ["server-1", "server-2", "server-3"]
  ```

**Горячий restart без даунтайма:**
*   Используйте `docker compose up -d --remove-orphans` вместо `down && up` для минимизации даунтайма.
*   Настройте `HEALTHCHECK` в Dockerfile для автоматического удаления из LB при падении.

**Отладка Jenkins vs GitLab CI:**
*   В GitLab CI нет `sh -x` для отладки — используйте `set -x` в начале script для отладки.
*   Артефакты (`artifacts:paths`) доступны только в UI пайплайна, а не на сервере.

## Мониторинг и логирование

**Просмотр логов:**
```bash
# Логи Runner'а
docker logs gitlab-runner --tail 100 -f

# Логи контейнера приложения
docker logs app_container_name --tail 100 -f

# Логи Docker Compose
docker compose logs -f --tail=100
```

**Проверка состояния компонентов:**
```bash
# Статус контейнеров
docker compose ps

# Проверка диска и inodes на хосте
df -h
df -i

# Проверка размера Docker volumes
docker system df -v
```

**Активные задачи и метрики:**
```bash
# Количество запущенных задач Runner'а
docker exec -it gitlab-runner gitlab-runner list

# Размер кэша Maven
du -sh .m2/repository
```

## Дополнительная информация

### Мониторинг приложения

Интегрируйте Spring Boot Actuator с Micrometer для сбора метрик в формате Prometheus. См. руководство по **[Prometheus: Сбор метрик Java](../../../Prometheus/overview.md)**.

Настройте в `application.properties`:
```properties
management.endpoints.web.exposure.include=health,info,metrics,prometheus
management.endpoint.health.show-details=always
```

### Смотрите также

*   **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — базовый синтаксис и ключевые концепции.
*   **[Сборка с Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md)** — безопасная сборка Docker-образов без привилегий.
*   **[Переменные и секреты GitLab](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md)** — маскирование и управление секретами.
*   **[Регистрация GitLab Runner](../Tutorials/runner_registration.md)** — настройка Docker Executor и 10 сценариев.
*   **[GitLab Runner через Docker Compose](../Tutorials/gitlab_runner_docker_compose.md)** — готовый стек для быстрого старта.
*   **[Тестирование с Testcontainers](../../../Testing/testcontainers_overview.md)** — интеграционные тесты в CI/CD.
