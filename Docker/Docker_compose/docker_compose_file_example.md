# Примеры конфигурации compose.yml

**Актуально для:** Docker Compose v5+ (Compose Specification)

## Определения

**`compose.yml`** — центральный файл декларативного описания ресурсов в Docker Compose. В нем определяются сервисы, сети, тома, секреты и конфигурации, составляющие единый стек приложения. Техническое описание каждой директивы представлено в [Справочнике по директивам](./docker_compose_directives.md).

**Compose Specification** — открытый стандарт, определяющий синтаксис и поведение `compose.yml`. В современных версиях (Compose v5+) поле `version` является необязательным и устаревшим.

**Эталонный пример** — Production-ready конфигурация, демонстрирующая industry-стандарты безопасности, надежности и наблюдаемости.

## Архитектура и принципы работы

### Жизненный цикл конфигурации

1. **Загрузка и валидация:** Compose загружает указанные файлы (`-f` или `include`), проверяет синтаксис YAML и типы значений.
2. **Слияние (merge):** Несколько файлов объединяются по правилам: скаляры заменяются, массивы конкатенируются, карты сливаются глубоко. Подробнее о правилах слияния см. [**Compose extends, include и правила слияния**](./docker_compose_extends_include.md).
3. **Разрешение переменных:** Интерполяция `${VAR}` из окружения, `.env` файлов и `env_file`. Приоритет: OS Environment > `--env-file` > `env_file` > `.env` > значения в `compose.yml`.
4. **Создание ресурсов:** Compose создает сети, тома и секреты через Docker API. Все именованные ресурсы получают префикс проекта.
5. **Запуск сервисов:** Контейнеры запускаются с учетом `depends_on` и `healthcheck`. При `condition: service_healthy` Compose дожидается готовности зависимого сервиса.

### Структура файла

```
compose.yml
├── name: проект
├── include: импорты
├── services: сервисы
│   ├── image/build
│   ├── ports
│   ├── environment/env_file
│   ├── volumes
│   ├── networks
│   ├── deploy (resources, restart)
│   ├── healthcheck
│   ├── logging
│   └── develop (watch)
├── networks
├── volumes
├── secrets
└── configs
```

## Базовые концепции

### Версионирование и модульность

- **Отсутствие `version`:** В Compose Specification поле `version` удалено. Если оно присутствует — игнорируется.
- **`name`:** Задает имя проекта (префикс для контейнеров, сетей, томов).
- **`include`:** (Compose v2.20+) Импортирует целые compose-файлы, обеспечивая истинную модульность. Поддерживает локальные файлы и OCI-артефакты.

### Безопасность по умолчанию

- **`secrets`:** Для чувствительных данных (пароли, ключи). Секреты монтируются как файлы в `/run/secrets/`.
- **`user`:** Запуск от непривилегированного пользователя (`user: "1001:1001"`).
- **`read_only`:** Только для чтения корневая ФС. Для временных данных добавьте `tmpfs`.
- **`cap_drop`:** Отзыв всех Linux capabilities, добавление только необходимых через `cap_add`.

### Надежность

- **`healthcheck`:** Обязателен для stateful-сервисов (базы данных, кэши). Используйте `start_period` для приложений с долгой инициализацией.
- **`depends_on` с `condition: service_healthy`:** Декларативное управление зависимостями без внешних скриптов.
- **`restart: unless-stopped`:** Рекомендуется для production. Для CI/CD задач — `on-failure[:max]`.
- **`deploy.resources`:** Лимиты памяти и CPU. `limits` — жесткий потолок, `reservations` — мягкий лимит (в non-Swarm compose работает только `reservations.memory` как `--memory-reservation`; `reservations.cpus`/`pids` — опции Swarm).

### Наблюдаемость

- **`logging`:** Ротация логов через `json-file` с `max-size` и `max-file`. Без ротации логи заполняют диск.
- **`labels`:** Метаданные для внешних инструментов (Traefik, Prometheus).

## Практические сценарии

### Сценарий 1: Production-ready стек с базой данных и кэшем

Стек с настроенной безопасностью, проверками готовности и ротацией логов.

```yaml
name: production-ready-stack

services:
  database:
    image: postgres:17-alpine
    restart: unless-stopped
    environment:
      - POSTGRES_USER=app_user
      - POSTGRES_DB=app_db
    secrets:
      - db_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - backend_net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app_user -d app_db"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 512M
        reservations:
          cpus: "0.25"
          memory: 256M

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    user: "1001:1001"
    read_only: true
    tmpfs:
      - /tmp
      - /run
    depends_on:
      database:
        condition: service_healthy
    environment:
      - DB_HOST=database
      - REDIS_URL=redis://cache:6379
    networks:
      - backend_net
      - frontend_net
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 512M
        reservations:
          cpus: "0.25"
          memory: 256M
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  cache:
    image: redis:7.4-alpine
    networks:
      - backend_net
    healthcheck:
      test: ["CMD-SHELL", "redis-cli ping"]
      interval: 10s
      timeout: 5s
      retries: 3
    deploy:
      resources:
        limits:
          cpus: "0.25"
          memory: 256M

volumes:
  postgres_data:

networks:
  frontend_net:
  backend_net:
    internal: true

secrets:
  db_password:
    file: ./secrets/db_pass.txt
```

**Запуск:**
```bash
docker compose up -d --build --wait --remove-orphans
```

### Сценарий 2: Масштабируемый стек с Nginx (Load Balancing)

Балансировка нагрузки между несколькими экземплярами приложения.

```yaml
name: scalable-web-app

services:
  web:
    build: ./app
    restart: always
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: "0.5"
          memory: 256M
    networks:
      - web_net

  proxy:
    image: nginx:1.30-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - web
    networks:
      - web_net

networks:
  web_net:
```

**Запуск:**
```bash
docker compose up -d --scale web=3
```

### Сценарий 3: Корпоративный стек с профилями и модулями

Использование профилей для выборочного запуска инструментов мониторинга и отладки.

```yaml
name: enterprise-app

services:
  app:
    image: my-corp-app:1.0.0
    networks:
      - app_net
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 1G

  debug-tools:
    image: nicolaka/netshoot:latest
    profiles:
      - debug
    network_mode: "service:app"
    cap_add:
      - NET_ADMIN
      - NET_RAW

  prometheus-exporter:
    image: prom/node-exporter:latest
    profiles:
      - monitoring
    pid: host
    network_mode: "host"

networks:
  app_net:
```

**Запуск с профилем отладки:**
```bash
docker compose --profile debug up -d
```

### Сценарий 4: Мульти-файловая конфигурация Dev/Staging/Prod

Разделение ответственности через наложение compose-файлов. Подробнее о правилах слияния см. [**Compose extends, include и правила слияния**](./docker_compose_extends_include.md).

**compose.yml (базовая логика):**
```yaml
name: multi-env-app

services:
  web:
    image: myapp:1.0.0
    ports:
      - "8000:8000"
    environment:
      - LOG_LEVEL=info
    networks:
      - app_net
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 512M

  db:
    image: postgres:17-alpine
    environment:
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - db_data:/var/lib/postgresql/data
    networks:
      - app_net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      retries: 5

volumes:
  db_data:

networks:
  app_net:

secrets:
  db_password:
    file: ./secrets/db_pass.txt
```

**compose.override.yml (разработка):**
```yaml
services:
  web:
    build: ./web
    volumes:
      - ./web/src:/app/src
    environment:
      - DEBUG=true
```

**compose.prod.yml (продакшн):**
```yaml
services:
  web:
    restart: unless-stopped
    deploy:
      replicas: 2
      resources:
        limits:
          cpus: "1.0"
          memory: 1G
        reservations:
          cpus: "0.5"
          memory: 512M
  db:
    restart: unless-stopped
    command: >
      postgres -c
      shared_buffers=256MB
      -c max_connections=200
```

**Запуск:**
```bash
# Development: базовый файл + автоматический override
docker compose up -d

# Production: базовый файл + явный override
docker compose -f compose.yml -f compose.prod.yml up -d
```

### Сценарий 5: Stateful стек с автоматическим backup

Стек с PostgreSQL и автоматическим резервным копированием через Cron.

```yaml
name: postgres-with-backup

services:
  postgres:
    image: postgres:17-alpine
    restart: unless-stopped
    environment:
      - POSTGRES_USER=app_user
      - POSTGRES_DB=app_db
    secrets:
      - db_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./backups:/backups
    networks:
      - backend_net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app_user -d app_db"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 1G

  backup:
    image: postgres:17-alpine
    restart: unless-stopped
    environment:
      - PGPASSWORD_FILE=/run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - ./backups:/backups
    networks:
      - backend_net
    entrypoint: >
      /bin/sh -c "
        while true; do
          pg_dump -h postgres -U app_user app_db > /backups/backup_$$(date +%Y%m%d_%H%M%S).sql;
          find /backups -name 'backup_*.sql' -mtime +7 -delete;
          sleep 86400;
        done
      "

volumes:
  postgres_data:

networks:
  backend_net:
    internal: true

secrets:
  db_password:
    file: ./secrets/db_pass.txt
```

**Запуск:**
```bash
docker compose up -d --wait
```

### Сценарий 6: Security-hardened стек

Стек с максимальной изоляцией и минимальными привилегиями.

```yaml
name: hardened-stack

services:
  web:
    image: nginx:1.30-alpine
    read_only: true
    tmpfs:
      - /var/cache/nginx:size=100M
      - /var/run:size=10M
      - /tmp:size=100M
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
    security_opt:
      - no-new-privileges:true
    user: "101:101"
    volumes:
      - ./nginx/conf:/etc/nginx/conf.d:ro
      - ./static:/usr/share/nginx/html:ro
    networks:
      - frontend_net
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

networks:
  frontend_net:
```

## Валидация и проверка

Перед применением конфигурации в production выполните:

```bash
# Валидация синтаксиса и вывод итоговой конфигурации
docker compose config

# Проверка конкретного сервиса
docker compose config database

# Валидация без реального запуска
docker compose up --dry-run
```

**Ожидаемый результат:** команда `config` выводит итоговый YAML без ошибок. `--dry-run` показывает все шаги, которые Compose выполнит при реальном запуске.

## Устранение неполадок

### Типичные ошибки конфигурации

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **`no configuration file`** | Compose не находит `compose.yml` | Укажите путь через `-f` или убедитесь, что файл существует. |
| **`service [...] has neither an image nor a build context`** | Отсутствует `image` или `build` | Добавьте одну из директив в сервис. |
| **`port is already allocated`** | Порт занят другим процессом | Освободите порт (`lsof -i :PORT`) или измените маппинг. |
| **`service_healthy` не работает** | Отсутствует `healthcheck` в зависимом сервисе | Добавьте `healthcheck` в зависимый сервис. |
| **`deadline exceeded`** при `--wait` | Сервис не переходит в `healthy` за таймаут | Увеличьте `--wait-timeout` или проверьте `healthcheck`. |
| **`permission denied`** при монтировании | Неверные права на хосте | Настройте `user` в сервисе или исправьте права на хосте (`chown`). |
| **`OOMKilled`** | Недостаточно памяти в `deploy.resources.limits` | Увеличьте лимит памяти или оптимизируйте потребление. |
| **`network [...] declared as external`** | Внешняя сеть не существует | Создайте сеть вручную (`docker network create`) или уберите `external: true`. |

### Диагностический процесс

При возникновении проблем с конфигурацией:

1. **Валидировать конфигурацию:** `docker compose config` — убедитесь, что YAML корректен.
2. **Проверить статус:** `docker compose ps` — найти сервис в состоянии `exited` или `restarting`.
3. **Изучить логи:** `docker compose logs <service>` — искать `ERROR`, `failed`, `cannot`.
4. **Проверить ресурсы:** `docker compose stats` — убедиться, что сервису выделено достаточно CPU и RAM.
5. **Инспектировать контейнер:** `docker inspect <container>` — проверить `Mounts`, `Config`, `HostConfig`.

## Рекомендации

### Безопасность

- **Никогда не хардкодите секреты:** Используйте `secrets:` с файлами, исключенными из Git.
- **Запускайте от непривилегированного пользователя:** `user: "1001:1001"` минимизирует последствия компрометации.
- **Ограничивайте capabilities:** `cap_drop: [ALL]` + `cap_add` только для необходимого.
- **Read-only корневая ФС:** Для статичных сервисов добавьте `read_only: true` и `tmpfs` для временных данных.
- **Network isolation:** Используйте `internal: true` для баз данных и внутренних сервисов.

### Надежность

- **Всегда определяйте `healthcheck`:** Для stateful-сервисов (базы данных, кэши). Используйте `start_period`.
- **Используйте `depends_on` с `condition: service_healthy`:** Исключает race conditions.
- **Фиксируйте версии образов:** Избегайте `latest` в production; используйте дайджесты или SHA-хэши.
- **Настраивайте ротацию логов:** `logging.driver` с `max-size` и `max-file`.
- **Именуйте проекты:** Используйте `name:` на верхнем уровне для предсказуемости имен контейнеров.

### Производительность

- **Используйте именованные тома для данных:** Bind mounts уязвимы к правам доступа; именованные тома управляются Docker.
- **tmpfs для временных данных:** Снижает I/O на диск.
- **Сетевая изоляция:** Разделяйте frontend, backend и данные на разные сети.
- **Используйте `build` вместо `image` для разработки:** Автоматическая пересборка при изменениях.

### Поддержка и эксплуатация

- **Версионируйте `compose.yml`:** Храните в Git с четкими коммитами.
- **Используйте `.env.example`:** Документируйте требуемые переменные без реальных значений.
- **Регулярно обновляйте образы:** Настраивайте политику пересборки (`--pull`) и проверяйте уязвимости.
- **Тестируйте откат:** Убедитесь, что `docker compose down` и повторный `up` восстанавливают работоспособность.

## Дополнительная информация

### Связанные документы

- **[Обзор Docker Compose](./docker_compose_overview.md)** — архитектура и ключевые возможности.
- **[Справочник по директивам](./docker_compose_directives.md)** — детальное описание всех ключей YAML.
- **[Compose extends, include и правила слияния](./docker_compose_extends_include.md)** — модульность и приоритеты.
- **[Продвинутые возможности](./docker_compose_advanced_topics.md)** — интерполяция переменных, профили, `include`.
- **[Режим watch](./docker_compose_watch_mode.md)** — автоматическая синхронизация кода для разработки.
- **[Тестирование в CI/CD](./docker_compose_ci_cd_testing.md)** — детерминированные окружения для пайплайнов.
- **[Миграция VPS без простоя](./vps_migration_zero_downtime.md)** — практическое руководство по переносу стека.

### Источники

- Официальная документация: [Compose Specification](https://github.com/compose-spec/compose-spec/blob/main/spec.md)
- Официальная документация: [Docker Compose File Reference](https://docs.docker.com/reference/compose-file/)
- Исходный код: [docker/compose](https://github.com/docker/compose)
