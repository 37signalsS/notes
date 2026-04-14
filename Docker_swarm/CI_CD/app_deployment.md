# CI/CD с Docker Swarm: Развертывание приложения

## Определения

- **Application Stack** — стек приложения, состоящий из Docker-сервисов, развертываемых в Swarm через `docker stack deploy`. Управляется из отдельного репозитория с собственным пайплайном CI/CD.
- **Environment Scope** — механизм GitLab CI для привязки переменных к конкретным окружениям (`production`, `development`). Позволяет использовать один пайплайн для развертывания на разные кластеры. Подробно в **[gitlab_ci_variables_secrets.md](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md)**.
- **Kaniko** — инструмент для сборки Docker-образов без демона Docker. Запускается как непривилегированный контейнер, что повышает безопасность CI/CD. SSoT: **[dockerfile_kaniko.md](../../Docker/Dockerfile/dockerfile_kaniko.md)**.
- **Multi-stage Pipeline** — пайплайн с разделением на этапы (build, deploy). Каждый этап выполняется последовательно или параллельно в зависимости от конфигурации.

## Базовые концепции

### Архитектура пайплайна приложения

Пайплайн развертывания приложения состоит из двух основных этапов:

```
[Коммит в Git] → [Build: Kaniko] → [Deploy: Docker Stack]
                      ↓                    ↓
              [Container Registry]  [Swarm Cluster]
```

**Этап 1: Build**

- Сборка Docker-образа из `Dockerfile`
- Использование Kaniko для безопасности (без Docker-in-Docker)
- Пуш образа в Container Registry (GitLab Registry)
- Тегирование по `CI_COMMIT_SHORT_SHA`

**Этап 2: Deploy**

- Подключение к Swarm через mTLS и Docker Context
- Развертывание через `docker stack deploy`
- Использование `--with-registry-auth` для доступа к приватному registry
- Traefik автоматически обнаруживает сервис через labels

### Принцип Environment Scope

Один пайплайн развертывает приложение на разные окружения:

| Переменная | Development | Production |
|---|---|---|
| `DOCKER_HOST` | `tcp://dev-manager:2376` | `tcp://prod-manager:2376` |
| `CA_PEM` | Сертификат dev-кластера | Сертификат prod-кластера |
| `CERT_PEM` | Клиентский dev-сертификат | Клиентский prod-сертификат |
| `KEY_PEM` | Клиентский dev-ключ | Клиентский prod-ключ |
| `COMPOSE_FILE` | `docker-compose.dev.yml` | `docker-compose.prod.yml` |

**Механизм работы:**

1. В GitLab создаются переменные с одинаковыми именами, но разными значениями
2. Каждая переменная привязывается к окружению через Environment scope
3. При запуске задачи с `environment: production` GitLab подставляет prod-значения
4. При запуске с `environment: development` — dev-значения

### Требования к окружению

- **Настроенный CI/CD для инфраструктуры:** Traefik и overlay-сеть `public` уже развернуты (см. **[infra_deployment.md](./infra_deployment.md)**)
- **mTLS для Docker Daemon:** Сертификаты для безопасного подключения (см. **[swarm_setup.md](./swarm_setup.md)**)
- **GitLab Container Registry:** Доступен для пуша образов
- **DNS-записи:** `app.your-domain.com` и `dev.app.your-domain.com` указывают на Swarm-менеджер

## Практические сценарии

### Сценарий 1: Подготовка репозитория приложения

**Шаг 1: Создание Dockerfile**

```dockerfile
FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --production
COPY . .
EXPOSE 3000
CMD ["node", "server.js"]
```

**Шаг 2: Создание `docker-compose.prod.yml`**

```yaml
version: '3.8'

services:
  app:
    image: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}
    networks:
      - public
    deploy:
      replicas: 3
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.my-app-prod.rule=Host(`app.your-domain.com`)"
        - "traefik.http.routers.my-app-prod.entrypoints=websecure"
        - "traefik.http.routers.my-app-prod.tls.certresolver=myresolver"
        - "traefik.http.services.my-app-prod.loadbalancer.server.port=3000"
      update_config:
        parallelism: 1
        delay: 10s
        failure_action: rollback

networks:
  public:
    external: true
```

**Шаг 3: Создание `docker-compose.dev.yml`**

Аналогично prod, но с `replicas: 1` и `Host(\`dev.app.your-domain.com\`)`.

**Шаг 4: Создание `.gitignore`**

```gitignore
node_modules/
.env
*.log
```

### Сценарий 2: Настройка переменных GitLab CI

В **Settings → CI/CD → Variables** создайте переменные для каждого окружения:

| Переменная | Тип | Development | Production |
|---|---|---|---|
| `DOCKER_HOST` | Variable | `tcp://dev-manager:2376` | `tcp://prod-manager:2376` |
| `CA_PEM` | File | `ca.pem` (dev) | `ca.pem` (prod) |
| `CERT_PEM` | File | `cert.pem` (dev) | `cert.pem` (prod) |
| `KEY_PEM` | File | `key.pem` (dev) | `key.pem` (prod) |

Сертификаты берутся из настройки mTLS (см. **[swarm_setup.md](./swarm_setup.md)**).

### Сценарий 3: Настройка `.gitlab-ci.yml`

**Полный пайплайн:**

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
  rules:
    - if: '$CI_COMMIT_BRANCH == "main" || $CI_COMMIT_BRANCH == "dev"'

.deploy_template: &deploy_template
  stage: deploy
  image: docker:24
  before_script:
    - mkdir -p ~/.docker
    - echo "$CA_PEM" > ~/.docker/ca.pem && echo "$CERT_PEM" > ~/.docker/cert.pem && echo "$KEY_PEM" > ~/.docker/key.pem
    - chmod 600 ~/.docker/*.pem
    - docker context create swarm --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use swarm
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - docker stack deploy -c $COMPOSE_FILE my-app --with-registry-auth

deploy_prod:
  <<: *deploy_template
  environment:
    name: production
    url: https://app.your-domain.com
  variables:
    COMPOSE_FILE: docker-compose.prod.yml
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

deploy_dev:
  <<: *deploy_template
  environment:
    name: development
    url: http://dev.app.your-domain.com
  variables:
    COMPOSE_FILE: docker-compose.dev.yml
  rules:
    - if: '$CI_COMMIT_BRANCH == "dev"'
```

**Ключевые моменты:**

- `entrypoint: [""]` — отключение entrypoint для Kaniko
- `--with-registry-auth` — передача учетных данных registry в Swarm
- `update_config` — настройка rolling update с rollback при ошибке

### Сценарий 4: Первый деплой приложения

**Шаг 1: Коммит и пуш**

```bash
git add .
git commit -m "Initial app: Node.js + Traefik labels"
git push
```

**Шаг 2: Мониторинг пайплайна**

В GitLab UI: **CI/CD → Pipelines** — отслеживайте выполнение задач.

**Шаг 3: Проверка развертывания**

```bash
# Переключение на контекст
docker context use prod-swarm

# Проверка сервисов
docker service ls

# Проверка задач
docker service ps my-app_app

# Журналы приложения
docker service logs my-app_app --follow
```

**Шаг 4: Проверка доступности**

```bash
# Проверка HTTPS
curl -I https://app.your-domain.com

# Проверка SSL-сертификата
curl -vI https://app.your-domain.com 2>&1 | grep "SSL certificate"
```

**Подробнее об обновлении и откате приложения** — в **[app_lifecycle.md](./app_lifecycle.md)**.

## Дополнительная информация

### Безопасность

**Рекомендации для продакшена:**

- **Секреты приложения:** Используйте Docker Secrets для паролей и API-ключей
- **Health checks:** Настройте проверки работоспособности в `docker-compose.yml`
- **Resource limits:** Ограничьте потребление CPU и памяти
- **Network policies:** Сегментируйте сети для изоляции сервисов

**Пример health check:**

```yaml
services:
  app:
    deploy:
      update_config:
        order: start-first
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

### Распространенные проблемы

| Проблема | Причина | Решение |
|---|---|---|
| `denied: requested access to the resource is denied` | Нет доступа к registry | Проверить `docker login` и `--with-registry-auth` |
| `service my-app_app could not be found` | Стек не развернут | Проверить имя стека в `docker stack deploy` |
| `502 Bad Gateway` | Traefik не видит сервис | Проверить labels и overlay-сеть `public` |
| `certificate signed by unknown authority` | Неправильный CA | Проверить переменную `CA_PEM` для окружения |
| Rolling update застрял | Health check не проходит | Проверить логи и настройки health check |

### Связанные документы

- **Жизненный цикл приложения (обновление, откат)** — **[app_lifecycle.md](./app_lifecycle.md)**
- **Настройка кластера (mTLS)** — **[swarm_setup.md](./swarm_setup.md)**
- **Docker Context для CI/CD** — **[docker_context_setup.md](./docker_context_setup.md)**
- **Развертывание инфраструктуры** — **[infra_deployment.md](./infra_deployment.md)**
- **Лучшие практики** — **[best_practices.md](./best_practices.md)**
- **Kaniko (SSoT)** — **[../../Docker/Dockerfile/dockerfile_kaniko.md](../../Docker/Dockerfile/dockerfile_kaniko.md)**
- **GitLab CI переменные (SSoT)** — **[../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md)**
- **Traefik в Swarm (SSoT)** — **[../swarm_ingress_traefik.md](../swarm_ingress_traefik.md)**
