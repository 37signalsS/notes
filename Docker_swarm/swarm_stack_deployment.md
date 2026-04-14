# Docker Swarm: Stack Deployment

## Определения

**Stack (Стек)** — многоконтейнерное приложение в Docker Swarm, описанное декларативно через файл `docker-compose.yml`. Управляется командой `docker stack deploy`.

**Docker Stack** — механизм развертывания стеков в Swarm, преобразующий `docker-compose.yml` в Swarm-сервисы с поддержкой репликации, балансировки нагрузки и отказоустойчивости.

## Базовые концепции

### Отличия от `docker compose`

| Параметр | `docker compose` | `docker stack` |
|---|---|---|
| **Команда** | `docker compose up` | `docker stack deploy` |
| **Режим** | Одиночный хост | Swarm-кластер |
| **Секция `deploy`** | Частично поддерживается | Полная поддержка |
| **`container_name`** | Поддерживается | Игнорируется |
| **`restart`** | Поддерживается | Игнорируется (используется `restart_policy`) |
| **`depends_on`** | Поддерживается | Игнорируется (Swarm управляет зависимостями) |

**Важно:** Современные версии `docker compose` (v2.20+) частично поддерживают `deploy.replicas` и `deploy.resources` без Swarm, но полная функциональность доступна только в режиме Swarm.

### Игнорируемые параметры

При развертывании через `docker stack deploy` игнорируются:

- `container_name` — Swarm автоматически именует контейнеры
- `restart` — используется `restart_policy` внутри `deploy`
- `depends_on` — Swarm управляет порядком запуска
- `build` — образы должны быть собраны заранее
- `profiles` — не поддерживаются в Swarm

### Структура файла для Swarm

```yaml
version: '3.8'

services:
  <service-name>:
    image: <image>:<tag>
    deploy:
      replicas: <count>
      resources:
        limits: ...
      placement:
        constraints: ...
      update_config: ...
      restart_policy: ...
    networks: ...
    volumes: ...
    secrets: ...
    configs: ...
```

## Практические сценарии

### Базовое развертывание стека

#### Пример `docker-compose.yml`

```yaml
version: '3.8'

services:
  web:
    image: nginx:1.26.3
    ports:
      - "80:80"
    deploy:
      replicas: 3
      placement:
        constraints:
          - node.role == worker
      update_config:
        parallelism: 1
        delay: 10s
      restart_policy:
        condition: on-failure

  backend:
    image: my-backend-app:1.0
    deploy:
      replicas: 2
      placement:
        constraints:
          - node.labels.app == backend
```

#### Управление стеком (CLI)

```sh
# Развертывание или обновление стека
docker stack deploy -c docker-compose.yml my-app-stack

# Просмотр запущенных стеков
docker stack ls

# Просмотр сервисов в стеке
docker stack services my-app-stack

# Просмотр задач сервиса
docker stack ps my-app-stack

# Удаление стека
docker stack rm my-app-stack
```

**Важно:** `docker stack deploy` идемпотентна — создает стек или обновляет его согласно новому `docker-compose.yml`.

### Работа с сетями

#### Создание external-сети

```yaml
version: '3.8'

services:
  web:
    image: nginx
    networks:
      - frontend
      - backend

  db:
    image: postgres:15
    networks:
      - backend

networks:
  frontend:
    external: true
  backend:
    driver: overlay
```

**Предварительная настройка:**

```sh
docker network create --driver overlay frontend
docker stack deploy -c docker-compose.yml myapp
```

#### Изоляция трафика

```yaml
services:
  frontend:
    networks:
      - public
      - internal
  
  backend:
    networks:
      - internal
      - database
  
  db:
    networks:
      - database

networks:
  public:
    driver: overlay
  internal:
    driver: overlay
    internal: true
  database:
    driver: overlay
    internal: true
```

### Работа с томами

#### Named volumes

```yaml
version: '3.8'

services:
  db:
    image: postgres:15
    volumes:
      - db-data:/var/lib/postgresql/data
    deploy:
      placement:
        constraints:
          - node.labels.db == true

volumes:
  db-data:
    driver: local
```

**Важно:** Named volumes привязаны к конкретному узлу. Для репликации используйте external-хранилища (NFS, Ceph).

### Работа с секретами и конфигурациями

```yaml
version: '3.8'

services:
  app:
    image: my-app:latest
    secrets:
      - db_password
      - api_token
    configs:
      - app_config
    deploy:
      replicas: 3

  db:
    image: postgres:15
    secrets:
      - db_password
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password

secrets:
  db_password:
    external: true
  api_token:
    external: true

configs:
  app_config:
    external: true
```

**Предварительная настройка:**

```sh
docker secret create db_password ./password.txt
docker secret create api_token ./token.txt
docker config create app_config ./app.yaml
```

### Ограничение ресурсов

```yaml
services:
  app:
    image: my-app:latest
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 256M
```

### Placement Constraints

```yaml
services:
  db:
    image: postgres:15
    deploy:
      placement:
        constraints:
          - node.labels.db == true
          - node.role == worker
        preferences:
          - spread: node.labels.zone

  cache:
    image: redis:7
    deploy:
      placement:
        constraints:
          - node.labels.cache == true
```

**Установка меток на узлы:**

```sh
docker node update --label-add db=true node-1
docker node update --label-add cache=true node-2
```

## Дополнительная информация

### Лучшие практики

- **Идемпотентность:** Файлы `docker-compose.yml` должны быть идемпотентными
- **Version pinning:** Фиксируйте версии образов (`nginx:1.26.3`, не `nginx:latest`)
- **Resource limits:** Всегда указывайте ограничения ресурсов
- **Health checks:** Используйте `healthcheck` для мониторинга состояния
- **External networks:** Создавайте сети заранее для контроля конфигурации

### Продвинутые стратегии

Для Canary, Blue-Green развертывания и troubleshooting см. **[swarm_stack_advanced.md](./swarm_stack_advanced.md)**.

### Связанные документы

- **Docker Compose Advanced** — **[../Docker/Docker_compose/docker_compose_advanced_topics.md](../Docker/Docker_compose/docker_compose_advanced_topics.md)**
- **Secrets and Configs** — **[swarm_secrets_configs.md](./swarm_secrets_configs.md)**
- **CLI Reference** — **[swarm_management_cli.md](./swarm_management_cli.md)**
- **Продвинутые стратегии** — **[swarm_stack_advanced.md](./swarm_stack_advanced.md)**
