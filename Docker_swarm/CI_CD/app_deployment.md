# Деплой приложения в Docker Swarm через GitLab CI

## Определения

- **Application Stack** — стек приложения, состоящий из Docker-сервисов, развертываемых в Swarm через `docker stack deploy`. Управляется из отдельного репозитория с собственным пайплайном CI/CD.
- **Environment Scope** — механизм GitLab CI для привязки переменных к конкретным окружениям (`production`, `development`). Позволяет использовать один пайплайн для развертывания на разные кластеры. Подробно в **[gitlab_ci_variables_secrets.md](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md)**.
- **Kaniko** — инструмент для сборки Docker-образов без демона Docker. Запускается как непривилегированный контейнер, что повышает безопасность CI/CD. Подробнее: **[dockerfile_kaniko.md](../../Docker/Dockerfile/dockerfile_kaniko.md)**.
- **Multi-stage Pipeline** — пайплайн с разделением на этапы (build, deploy). Каждый этап выполняется последовательно или параллельно в зависимости от конфигурации.

## Базовые концепции

### Архитектура пайплайна приложения

```
[Code Push] → [Build (Kaniko)] → [Registry] → [Deploy (mTLS)] → [Swarm Cluster]
```

1. **Build Stage:** Сборка образа с помощью Kaniko. Образ пушится в GitLab Container Registry.
2. **Deploy Stage:** Использование `docker stack deploy` через защищенный канал (mTLS) для обновления сервисов в кластере.

### Принцип разделения ответственности

Репозиторий приложения содержит только код и Dockerfile. Пайплайны деплоя могут наследоваться из централизованных шаблонов или использовать `docker-compose.yml` файлы, специфичные для приложения.

## Практические сценарии

### Сценарий 1: Конфигурация GitLab CI для деплоя

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
    - mkdir -p /kaniko/.docker
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor --context $CI_PROJECT_DIR --dockerfile $CI_PROJECT_DIR/Dockerfile --destination ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}

deploy_prod:
  stage: deploy
  image: docker:24.0.5
  variables:
    DOCKER_HOST: "tcp://prod-manager.example.com:2376"
    DOCKER_TLS_VERIFY: 1
  before_script:
    - mkdir -p ~/.docker
    - echo "$CA_PEM" > ~/.docker/ca.pem
    - echo "$CERT_PEM" > ~/.docker/cert.pem
    - echo "$KEY_PEM" > ~/.docker/key.pem
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker stack deploy -c docker-compose.yml my-app --with-registry-auth
  environment:
    name: production
  only:
    - main
```

**Ключевые моменты:**

- `entrypoint: [""]` — отключение entrypoint для Kaniko.
- `DOCKER_HOST` — адрес менеджера Swarm.
- `--with-registry-auth` — передача учетных данных реестра узлам кластера.

### Сценарий 2: Использование Docker Context

Для более удобного управления несколькими кластерами:

```yaml
deploy:
  script:
    - docker context create remote --docker "host=$DOCKER_HOST,ca=~/.docker/ca.pem,cert=~/.docker/cert.pem,key=~/.docker/key.pem"
    - docker context use remote
    - docker stack deploy -c docker-compose.yml my-app --with-registry-auth
```

## Дополнительная информация

### Связанные документы

- **Жизненный цикл приложения (обновление, откат)** — **[app_lifecycle.md](./app_lifecycle.md)**
- **Настройка кластера (mTLS)** — **[swarm_setup.md](./swarm_setup.md)**
- **Docker Context для CI/CD** — **[docker_context_setup.md](./docker_context_setup.md)**
- **Развертывание инфраструктуры** — **[infra_deployment.md](./infra_deployment.md)**
- **Лучшие практики** — **[best_practices.md](./best_practices.md)**
- **Kaniko** — **[../../Docker/Dockerfile/dockerfile_kaniko.md](../../Docker/Dockerfile/dockerfile_kaniko.md)**
- **GitLab CI переменные** — **[../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md)**
- **Traefik в Swarm** — **[../swarm_ingress_traefik.md](../swarm_ingress_traefik.md)**
