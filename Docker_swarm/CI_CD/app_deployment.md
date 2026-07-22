# Деплой приложения в Docker Swarm через GitLab CI

## Определения

- **Application Stack:** Стек приложения, состоящий из Docker-сервисов, развертываемых в Swarm через `docker stack deploy`. Управляется из отдельного репозитория с собственным пайплайном CI/CD.
- **Environment Scope:** Механизм GitLab CI для привязки переменных к конкретным окружениям (`production`, `development`). Подробно в **[Переменные и секреты GitLab CI](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md)**.
- **[Kaniko](../../Docker/Dockerfile/dockerfile_kaniko.md):** Инструмент для сборки Docker-образов без демона Docker. Позволяет избежать использования привилегированного режима в CI.
- **[Docker Context](../CI_CD/docker_context_setup.md):** Механизм переключения между различными Docker-хостами (локальный, удаленный Swarm) без изменения переменных окружения для каждой команды.

## Базовые концепции

### Архитектура пайплайна доставки

Современный процесс доставки (CD) в Swarm строится на изоляции сборки от среды развертывания:

1. **Build Stage (Сборка):** Выполняется в эфемерном раннере с помощью Kaniko. Образ помечается уникальным тегом (обычно `${CI_COMMIT_SHA}`).
2. **Registry (Реестр):** Хранение образов. Swarm-менеджер должен иметь доступ к реестру для распространения образов по узлам.
3. **Deploy Stage (Развертывание):** Раннер подключается к менеджеру кластера через mTLS и выполняет декларативное обновление стека.

### Безопасность развертывания

- **mTLS:** Обязательная аутентификация клиента (раннера) на сервере ( Swarm API).
- **Secrets:** Передача чувствительных данных через переменные GitLab CI типа `File` (для сертификатов).
- **Least Privilege:** Ограничение прав доступа раннера только к конкретным портам менеджеров кластера.

## Практические сценарии

### Сценарий 1: Конфигурация .gitlab-ci.yml

Пример современного пайплайна для деплоя в Swarm:

```yaml
stages:
  - build
  - deploy

build_image:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.24.0-debug
    entrypoint: [""]
  script:
    - mkdir -p /kaniko/.docker
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor --context "dir://$CI_PROJECT_DIR" --dockerfile $CI_PROJECT_DIR/Dockerfile --destination ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}

deploy_to_swarm:
  stage: deploy
  image: docker:27.x
  variables:
    DOCKER_HOST: "tcp://swarm-manager.example.com:2376"
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

### Сценарий 2: Использование Docker Context в пайплайне

Абстракция параметров подключения для удобства управления:

```yaml
script:
  - docker context create swarm-prod --docker "host=tcp://$MANAGER_IP:2376,ca=~/.docker/ca.pem,cert=~/.docker/cert.pem,key=~/.docker/key.pem"
  - docker context use swarm-prod
  - docker stack deploy -c docker-compose.yml my-app --with-registry-auth
```

## Дополнительная информация

### Проверка результата деплоя

После выполнения команды `docker stack deploy` рекомендуется добавить шаг верификации, так как деплой в Swarm асинхронный:

```bash
# Ожидание стабилизации сервиса (пример скрипта)
docker service rollback --dry-run my-app_web
docker service inspect my-app_web --pretty
```

Подробнее о мониторинге процесса — в **[Жизненный цикл приложения](./app_lifecycle.md)**.

### Связанные документы

- **[app_lifecycle.md](./app_lifecycle.md)** — Rolling Update, Health Checks и откаты.
- **[swarm_setup.md](./swarm_setup.md)** — настройка mTLS и порта 2376.
- **[best_practices.md](./best_practices.md)** — рекомендации по безопасности и сборке (Kaniko).
- **[docker_context_setup.md](./docker_context_setup.md)** — детальная настройка контекстов.
- **[infra_deployment.md](./infra_deployment.md)** — развертывание Traefik и общих сетей.
