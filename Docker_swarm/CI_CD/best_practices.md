# CI/CD с Docker Swarm: Лучшие практики

## Определения

- **Best Practices (Лучшие практики)** — проверенные методы и подходы, обеспечивающие безопасность, надежность и эффективность CI/CD пайплайнов в Docker Swarm.
- **Immutable Infrastructure** — подход, при котором инфраструктура не изменяется после развертывания, а заменяется новой версией. Образы контейнеров неизменяемы (immutable).
- **GitOps** — методология, при которой конфигурация инфраструктуры и приложений хранится в Git, а изменения применяются автоматически через CI/CD пайплайны.
- **Least Privilege** — принцип минимальных привилегий: предоставление только необходимых прав доступа для выполнения задач.

## Базовые концепции

### Принципы безопасного CI/CD

1. **Без Docker-in-Docker:** Сборка образов через Kaniko без доступа к Docker Daemon
2. **Разделение секретов:** Хранение сертификатов и токенов в GitLab CI Variables (File type)
3. **Environment Scope:** Изоляция окружений через привязку переменных к веткам
4. **Manual Trigger для продакшена:** Ручное подтверждение для критических изменений

### Архитектура безопасного пайплайна

```
[Git Commit] → [GitLab CI] → [Kaniko (build)] → [Registry]
                                      ↓
                              [Docker Context]
                                      ↓
                            [Swarm Cluster (deploy)]
```

**Ключевые компоненты:**
- **Kaniko:** Сборка без привилегий, в userspace
- **GitLab Registry:** Приватный реестр с токеном `CI_JOB_TOKEN`
- **Docker Context:** Безопасное подключение через mTLS
- **Swarm:** Развертывание с `--with-registry-auth`

## Практические сценарии

### Сценарий 1: Сборка образов через Kaniko

**Почему Kaniko, а не Docker-in-Docker:**

| Критерий | Kaniko | Docker-in-Docker |
|---|---|---|
| Привилегии | Непривилегированный | Требует `privileged: true` |
| Безопасность | Изоляция userspace | Доступ к Docker Daemon |
| Kubernetes | Нативная поддержка | Сложная настройка |
| Кэширование | Слой образа | Кэш демона |

**Пример задачи в `.gitlab-ci.yml`:**

```yaml
build:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.24.0-debug
    entrypoint: [""]
  script:
    - mkdir -p /kaniko/.docker
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor \
        --context $CI_PROJECT_DIR \
        --dockerfile $CI_PROJECT_DIR/Dockerfile \
        --destination ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}
```

**Подробнее:** **[dockerfile_kaniko.md](../../Docker/Dockerfile/dockerfile_kaniko.md)**

### Сценарий 2: Использование `--with-registry-auth`

**Проблема:** При развертывании сервисов с приватными образами узлы Swarm не могут скачать образ без учетных данных registry.

**Решение:** Флаг `--with-registry-auth` передает учетные данные от менеджера к рабочим узлам.

```yaml
deploy:
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker stack deploy -c docker-compose.yml my-app --with-registry-auth
```

**Важно:**
- `docker login` должен выполняться перед `docker stack deploy`
- Учетные данные передаются только менеджеру, который распространяет их на узлы
- Токены автоматически обновляются при каждом запуске пайплайна

### Сценарий 3: Управление секретами через Environment Scope

**Настройка переменных для разных окружений:**

1. В GitLab: **Settings → CI/CD → Variables**
2. Создайте переменные с одинаковыми именами, но разными значениями
3. Укажите **Environment scope** для каждой

| Переменная | Scope | Значение |
|---|---|---|
| `DOCKER_HOST` | `production` | `tcp://prod-manager:2376` |
| `DOCKER_HOST` | `development` | `tcp://dev-manager:2376` |
| `CA_PEM` | `production` | (сертификат prod) |
| `CA_PEM` | `development` | (сертификат dev) |

**Автоматическое применение:**

```yaml
deploy_prod:
  environment:
    name: production
  variables:
    COMPOSE_FILE: docker-compose.prod.yml
  # GitLab автоматически подставит DOCKER_HOST и сертификаты для production

deploy_dev:
  environment:
    name: development
  variables:
    COMPOSE_FILE: docker-compose.dev.yml
  # GitLab автоматически подставит DOCKER_HOST и сертификаты для development
```

**Подробнее:** **[gitlab_ci_variables_secrets.md](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md)**

### Сценарий 4: Автоматическое развертывание по веткам

**Стратегия ветвления:**

| Ветка | Окружение | Автоматически |
|---|---|---|
| `dev` | Development | ✓ |
| `main` | Production | ✓ |
| `feature/*` | Review (опционально) | ✗ |

**Пример `.gitlab-ci.yml`:**

```yaml
deploy_dev:
  stage: deploy
  environment:
    name: development
    url: http://dev.app.example.com
  rules:
    - if: '$CI_COMMIT_BRANCH == "dev"'

deploy_prod:
  stage: deploy
  environment:
    name: production
    url: https://app.example.com
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
  when: manual  # Ручное подтверждение для production
```

### Сценарий 5: Health Checks и Rolling Updates

**Настройка безопасного обновления:**

```yaml
services:
  app:
    deploy:
      replicas: 3
      update_config:
        parallelism: 1      # Обновлять по одной реплике
        delay: 10s          # Задержка между обновлениями
        failure_action: rollback  # Откат при ошибке
        order: start-first  # Запуск новой перед остановкой старой
      rollback_config:
        parallelism: 1
        delay: 10s
      restart_policy:
        condition: on-failure
        max_attempts: 3
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

**Подробнее:** **[app_lifecycle.md](./app_lifecycle.md)**

### Сценарий 6: Мониторинг и логирование

**Централизованное логирование:**

```yaml
services:
  app:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

**Мониторинг через Docker CLI:**

```bash
# Статус сервисов
docker service ls

# Задачи сервиса
docker service ps my-app_app

# Журналы
docker service logs my-app_app --tail 100 --follow

# Статистика ресурсов
docker stats
```

## Дополнительная информация

### Чек-лист безопасности

- [ ] Kaniko используется вместо Docker-in-Docker
- [ ] Сертификаты хранятся в GitLab CI Variables (File type)
- [ ] Environment scope настроен для изоляции окружений
- [ ] `--with-registry-auth` используется для приватных образов
- [ ] Health checks настроены для всех сервисов
- [ ] Rolling update с `failure_action: rollback`
- [ ] Логирование с ограничением размера
- [ ] Ручное подтверждение для production-деплоя

### Распространенные ошибки

| Ошибка | Причина | Решение |
|---|---|---|
| `denied: requested access to the resource is denied` | Нет `docker login` или `--with-registry-auth` | Добавить аутентификацию |
| `certificate signed by unknown authority` | Неправильный CA в переменной | Проверить `CA_PEM` для окружения |
| Rolling update застрял | Health check не проходит | Увеличить `start_period` |
| Образ не обновляется | Кэш Kaniko | Использовать `--cache=false` или новый тег |

### Связанные документы

- **Настройка кластера** — **[swarm_setup.md](./swarm_setup.md)**
- **Docker Context** — **[docker_context_setup.md](./docker_context_setup.md)**
- **Развертывание приложения** — **[app_deployment.md](./app_deployment.md)**
- **Жизненный цикл приложения** — **[app_lifecycle.md](./app_lifecycle.md)**
- **Kaniko (SSoT)** — **[../../Docker/Dockerfile/dockerfile_kaniko.md](../../Docker/Dockerfile/dockerfile_kaniko.md)**
- **GitLab CI переменные (SSoT)** — **[../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md)**
