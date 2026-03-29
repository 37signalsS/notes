# CI/CD с Docker Swarm: Развертывание инфраструктуры

## Определения

- **Инфраструктурный стек (infra-stack)** — набор общих сервисов (Traefik, базы данных, кэши), развертываемых в Docker Swarm как единое целое. Управляется из отдельного репозитория GitLab.
- **Shared Services** — сервисы, используемые несколькими приложениями одновременно (например, Traefik для маршрутизации, PostgreSQL для хранения данных).
- **Overlay-сеть** — виртуальная сеть Docker Swarm, соединяющая контейнеры на разных узлах кластера. Используется для связи между Traefik и приложениями.
- **Manual Trigger** — ручной запуск пайплайна в GitLab CI. Рекомендуется для инфраструктурных изменений, требующих дополнительного контроля.

## Базовые концепции

### Архитектура инфраструктурного стека

Инфраструктурные сервисы выносятся в отдельный репозиторий (`infra-stack`) по следующим причинам:

- **Изоляция изменений:** Обновление инфраструктуры не требует деплоя приложений
- **Контроль версий:** Отдельная история изменений для общих сервисов
- **Безопасность:** Ограниченный доступ к репозиторию инфраструктуры
- **Повторное использование:** Несколько приложений используют общую инфраструктуру

**Компоненты стека:**
```
[infra-stack репозиторий]
    ├── docker-compose.yml      # Конфигурация сервисов
    ├── .gitlab-ci.yml          # Пайплайн развертывания
    └── .env                    # Переменные окружения (не коммитить)
```

### Принцип работы CI/CD для инфраструктуры

1. **Изменения в репозитории:** Коммит в `infra-stack` запускает пайплайн
2. **Ручное подтверждение:** Деплой требует явного одобрения (manual trigger)
3. **Подключение к Swarm:** GitLab Runner использует mTLS и Docker Context
4. **Развертывание стека:** `docker stack deploy` обновляет сервисы в Swarm
5. **Автоматическое обнаружение:** Traefik обнаруживает новые сервисы через Docker API

### Требования к окружению

- **Настроенный кластер Swarm:** Минимум 3 менеджера для кворума
- **mTLS для Docker Daemon:** Сертификаты для безопасного подключения (см. **[swarm_setup.md](./swarm_setup.md)**)
- **GitLab CI/CD:** Настроенные переменные окружения (сертификаты, токены)
- **Сетевая связность:** Доступ с GitLab Runner к порту 2376 менеджера Swarm

## Практические сценарии

### Сценарий 1: Подготовка репозитория инфраструктуры

**Шаг 1: Создание структуры репозитория**

```bash
mkdir infra-stack && cd infra-stack
git init
```

**Шаг 2: Создание `docker-compose.yml`**

```yaml
version: '3.8'

services:
  traefik:
    image: traefik:v3.6
    command:
      - "--log.level=INFO"
      - "--api.dashboard=true"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--providers.swarm=true"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
      - "--certificatesresolvers.myresolver.acme.tlschallenge=true"
      - "--certificatesresolvers.myresolver.acme.email=${ACME_EMAIL}"
      - "--certificatesresolvers.myresolver.acme.storage=/certificates/acme.json"
    ports:
      - "80:80"
      - "443:443"
      - "8080:8080"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "traefik-certs:/certificates"
    networks:
      - public
    deploy:
      placement:
        constraints:
          - "node.role==manager"

volumes:
  traefik-certs:

networks:
  public:
    driver: overlay
    name: public
```

> **Примечание:** Эта конфигурация содержит только Traefik. Для добавления баз данных (PostgreSQL, MariaDB) расширьте файл дополнительными сервисами.

**Шаг 3: Создание `.gitignore`**

```gitignore
.env
*.pem
*.key
```

### Сценарий 2: Настройка переменных GitLab CI

В настройках GitLab (**Settings → CI/CD → Variables**) создайте следующие переменные:

| Переменная | Тип | Значение | Описание |
|---|---|---|---|
| `DOCKER_HOST` | Variable | `tcp://manager.example.com:2376` | Адрес Docker Daemon |
| `CA_PEM` | File | (содержимое `ca.pem`) | Корневой сертификат |
| `CERT_PEM` | File | (содержимое `cert.pem`) | Клиентский сертификат |
| `KEY_PEM` | File | (содержимое `key.pem`) | Клиентский ключ |
| `ACME_EMAIL` | Variable | `admin@example.com` | Email для Let's Encrypt |

**Получение сертификатов:**

Сертификаты берутся из настройки mTLS (см. **[swarm_setup.md](./swarm_setup.md)**):
- `ca.pem` — корневой сертификат CA
- `cert.pem` — клиентский сертификат для GitLab Runner
- `key.pem` — клиентский ключ

### Сценарий 3: Настройка `.gitlab-ci.yml`

**Базовый пайплайн для развертывания:**

```yaml
stages:
  - deploy

deploy_infra:
  stage: deploy
  image: docker:24
  before_script:
    - mkdir -p ~/.docker
    - echo "$CA_PEM" > ~/.docker/ca.pem
    - echo "$CERT_PEM" > ~/.docker/cert.pem
    - echo "$KEY_PEM" > ~/.docker/key.pem
    - chmod 600 ~/.docker/*.pem
    - docker context create swarm \
      --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use swarm
  script:
    - docker stack deploy -c docker-compose.yml shared-infra --with-registry-auth
  when: manual
```

**Параметры пайплайна:**
- `image: docker:24` — образ Docker CLI для выполнения команд
- `when: manual` — ручной запуск (требует подтверждения в UI GitLab)
- `--with-registry-auth` — передача учетных данных registry в Swarm

### Сценарий 4: Развертывание инфраструктуры

**Шаг 1: Первый деплой**

```bash
# Коммит изменений
git add .
git commit -m "Initial infra-stack: Traefik v3.6"
git push

# В GitLab UI: CI/CD → Pipelines → Запуск пайплайна
```

**Шаг 2: Проверка развертывания**

```bash
# Переключение на контекст Swarm
docker context use prod-swarm

# Проверка сервисов
docker service ls

# Проверка журналов Traefik
docker service logs shared-infra_traefik --follow
```

**Шаг 3: Проверка доступности**

```bash
# Проверка портов
curl -I http://manager.example.com
curl -I https://manager.example.com

# Dashboard Traefik (не защищен по умолчанию!)
curl http://manager.example.com:8080/api/http/routers
```

### Сценарий 5: Обновление инфраструктуры

**Обновление версии Traefik:**

1. Измените версию образа в `docker-compose.yml`:
   ```yaml
   image: traefik:v3.7  # было traefik:v3.6
   ```

2. Закоммитьте и отправьте изменения:
   ```bash
   git commit -am "Upgrade Traefik to v3.7"
   git push
   ```

3. Запустите пайплайн в GitLab UI

**Мониторинг обновления:**

```bash
# Отслеживание задач
docker service ps shared-infra_traefik

# Журналы обновления
docker service logs shared-infra_traefik --tail 100
```

### Сценарий 6: Добавление дополнительных сервисов

**Пример: Добавление PostgreSQL:**

```yaml
services:
  traefik:
    # ... конфигурация Traefik ...

  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=${POSTGRES_DB}
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - public
    deploy:
      placement:
        constraints:
          - "node.labels.db == true"

volumes:
  traefik-certs:
  postgres-data:
```

**Добавление переменных в GitLab:**
- `POSTGRES_DB` — имя базы данных
- `POSTGRES_USER` — пользователь
- `POSTGRES_PASSWORD` (Masked) — пароль

## Дополнительная информация

### Безопасность

**Рекомендации для продакшена:**

- **Dashboard Traefik:** Защитите BasicAuth или отключите (`--api.insecure=false`)
- **Сетевой доступ:** Ограничьте firewall доступ к портам 80, 443, 8080
- **Секреты:** Используйте Docker Secrets для чувствительных данных
- **Ротация сертификатов:** Обновляйте клиентские сертификаты ежегодно

**Пример защиты Dashboard:**

```yaml
command:
  - "--api.dashboard=true"
  - "--api.insecure=false"
  - "--entrypoints.traefik.address=:8080"
  - "--entrypoints.traefik.http.middlewares=admin-auth.basicauth.users=admin:$$apr1$$xyz"
  - "--entrypoints.traefik.http.routers.dashboard.middlewares=admin-auth"
```

### Распространенные проблемы

| Проблема | Причина | Решение |
|---|---|---|
| `service shared-infra_traefik could not be found` | Стек не развернут | Запустить пайплайн вручную |
| `certificate signed by unknown authority` | Неправильный CA | Проверить переменную `CA_PEM` |
| `Cannot connect to the Docker daemon` | Порт недоступен | Проверить firewall и `DOCKER_HOST` |
| Traefik не обнаруживает сервисы | Разные overlay-сети | Подключить сервисы к `public` |

### Связанные документы

- **Настройка кластера (mTLS)** — **[swarm_setup.md](./swarm_setup.md)**
- **Docker Context для CI/CD** — **[docker_context_setup.md](./docker_context_setup.md)**
- **Traefik в Swarm (SSoT)** — **[../swarm_ingress_traefik.md](../swarm_ingress_traefik.md)**
- **Развертывание приложения** — **[app_deployment.md](./app_deployment.md)**
- **Лучшие практики** — **[best_practices.md](./best_practices.md)**
- **Обзор Traefik** — **[../../WebServers/Traefik/traefik_overview.md](../../WebServers/Traefik/traefik_overview.md)**
