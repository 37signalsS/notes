# Kaniko: Сборка Docker-образов без демона

## Определения

**Kaniko** — инструмент от Google для сборки образов контейнеров из `Dockerfile` без зависимости от Docker-демона. Выполняет команды `Dockerfile` в пользовательском пространстве (userspace) внутри контейнера. Идеален для CI/CD и Kubernetes.

Официальный репозиторий: **[github.com/GoogleContainerTools/kaniko](https://github.com/GoogleContainerTools/kaniko)**.

## Основные концепции

### Проблема: Зависимость от Docker-демона

В CI/CD-пайплайнах (GitLab CI, Jenkins) и Kubernetes-подах доступ к `/var/run/docker.sock` ограничен или отсутствует. Подход "Docker-in-Docker" (`dind`) требует привилегированного режима и небезопасен.

### Решение: Kaniko

1. Запускается как обычный непривилегированный контейнер.
2. Извлекает файловую систему базового образа.
3. Выполняет команды `Dockerfile`, создавая слои в userspace.
4. Формирует слои на основе разницы снапшотов.
5. Отправляет образ в указанный реестр.

### Преимущества

- **Безопасность:** Не требует привилегированного доступа или Docker-сокета.
- **Простота:** Запускается как обычный контейнер.
- **Совместимость с Kubernetes:** Идеально для сборки в кластере.

### Альтернативы

- **[BuildKit](./dockerfile_buildkit.md)** — современный движок сборки Docker (включен по умолчанию).
- **[Buildah](../alternative_runtimes_and_tools.md)** — сборка образов без демона.

## Практические сценарии

### Сценарий 1: Сборка образа в GitLab CI

```yaml
build-image:
  stage: build
  image:
    # Debug-образ содержит shell для отладки
    name: gcr.io/kaniko-project/executor:v1.24.0-debug
    entrypoint: [""]
  script:
    # Аутентификация в реестре
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    # Запуск сборки
    - /kaniko/executor \
        --context "${CI_PROJECT_DIR}" \
        --dockerfile "${CI_PROJECT_DIR}/Dockerfile" \
        --destination "${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}"
```

**Параметры:**
- `--context` — путь к исходным файлам.
- `--dockerfile` — путь к `Dockerfile`.
- `--destination` — имя и тег итогового образа.

### Сценарий 2: Сборка с приватным реестром и кастомным CA

Для on-premise реестров (Harbor) с внутренними CA-сертификатами:

```yaml
build-custom:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.24.0-debug
    entrypoint: [""]
  script:
    # Аутентификация
    - echo "{\"auths\":{\"$HARBOR_REGISTRY\":{\"username\":\"$HARBOR_USER\",\"password\":\"$HARBOR_PASSWORD\"}}}" > /kaniko/.docker/config.json
    # Сборка с CA и build-arg
    - /kaniko/executor \
      --context $CI_PROJECT_DIR \
      --dockerfile $CI_PROJECT_DIR/Dockerfile \
      --destination "$HARBOR_REGISTRY/my-project/my-image:latest" \
      --build-arg "APP_VERSION=${CI_COMMIT_TAG}" \
      --registry-certificate $CUSTOM_CA_CERT
```

**Параметры:**
- `--registry-certificate` — путь к CA-сертификату.
- `--build-arg` — переменные времени сборки.

### Сценарий 3: Кэширование для ускорения сборок

```yaml
build-image-with-cache:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.24.0-debug
    entrypoint: [""]
  script:
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor \
        --context "${CI_PROJECT_DIR}" \
        --dockerfile "${CI_PROJECT_DIR}/Dockerfile" \
        --destination "${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}" \
        --cache=true \
        --cache-repo "${CI_REGISTRY_IMAGE}/cache"
```

Кэшированные слои хранятся в образе `${CI_REGISTRY_IMAGE}/cache`.

## Дополнительная информация

- **[GitLab CI Tutorials](../../CI-CD/GitLab_CI/Tutorials/)** — руководства по GitLab CI
- **[Docker Swarm CI/CD](../../Docker_swarm/CI_CD/overview.md)** — развертывание в Swarm
- **[Security Overview](../Docker_security/overview.md)** — безопасность сборки
