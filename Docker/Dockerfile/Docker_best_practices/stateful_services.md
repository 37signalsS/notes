# Stateful-сервисы в Docker: базы данных, брокеры, кэш

**Актуально для:** PostgreSQL 18.x / 17.x, MySQL 9.x, Redis 8.x, Docker 29.x

## Определения

- **Stateful-сервис:** Сервис, хранящий состояние (данные) между перезапусками. В Docker требует тома (volume) для персистентности — без тома данные теряются при удалении контейнера.
- **Named volume:** Именованный том Docker (`docker volume create pg_data`), управляемый демоном Docker. Рекомендуемый способ хранения данных БД: данные живут вне контейнера, сохраняются при `docker compose down` (без `-v`).
- **Bind mount:** Монтирование директории хоста (`-v /host/path:/container/path`). Для БД не рекомендуется: проблемы с правами (UID mapping) и производительностью; используйте для конфигов и init-скриптов.
- **Entrypoint-скрипт:** Скрипт инициализации официальных образов (`/usr/local/bin/docker-entrypoint.sh`): создаёт пользователя, БД, выполняет init-скрипты при первом запуске.
- **/docker-entrypoint-initdb.d/:** Директория с init-скриптами (`.sql`, `.sql.gz`, `.sh`). Выполняется **только при первом запуске** (когда директория данных пуста) — механизм инициализации схемы и seed-данных.
- **pg_isready / mysqladmin ping / redis-cli ping:** Утилиты health check для PostgreSQL, MySQL, Redis. Используются в `HEALTHCHECK` и compose `healthcheck`.
- **BGSAVE / SAVE:** Команды Redis для создания снапшота RDB. `BGSAVE` — в фоне (не блокирует); `SAVE` — блокирующий.
- **AOF (Append Only File):** Механизм Redis-персистентности: каждая операция записи логируется. `appendonly yes` + `appendfsync everysec` — стандарт production-настройка.
- **PGDATA:** Переменная окружения PostgreSQL, задающая директорию данных (по умолчанию `/var/lib/postgresql/data`). В Alpine-образах часто `/var/lib/postgresql/data` с поддиректорией `pgdata`.
- **Streaming replication:** PostgreSQL-репликация WAL-потоком с primary на standby. В Docker: отдельные контейнеры primary/standby с общими volume или pg_basebackup.
- **Sentinel:** Redis-механизм high availability: мониторинг master, автоматический failover. В Docker Compose — минимум 3 sentinel-контейнера.

## Базовые концепции

### Предпосылки

- **Docker Engine 29.x**; для production — Docker 29.x с cgroups v2.
- Понимание разницы stateless/stateful: stateless-приложения масштабируются горизонтально, stateful-сервисы требуют персистентного хранилища.
- Знание UID/GID: официальные образы БД запускают демона от непривилегированного пользователя (PostgreSQL — UID 999 `postgres`, MySQL — UID 999 `mysql`, Redis — UID 999 `redis`). Том должен быть доступен этому UID.

### Почему stateful-сервисы сложнее в контейнерах

1. **Данные переживают контейнер:** writable layer контейнера уничтожается при `docker rm`. Данные должны жить в named volume.
2. **Права доступа:** демон БД работает от своего UID; bind mount с хоста часто недоступен этому UID → ошибки permissions.
3. **Гraceful shutdown:** БД должны корректно завершаться (flush, checkpoint) — `docker stop` посылает `SIGTERM`, entrypoint-скрипт ловит его и останавливает демон корректно.
4. **Инициализация:** схема и seed-данные применяются один раз, при первом запуске.
5. **Ресурсы:** БД чувствительны к лимитам памяти (shared_buffers, innodb_buffer_pool_size) — лимит контейнера должен учитывать кеш БД.

**Операционный контекст:**
- **SLI/SLO:** Доступность БД — критичный SLI. Для production обычно SLO 99.9% (8.76h downtime/year). Health check — механизм определения доступности для оркестратора; `start_period` должен покрывать cold-start при большом объёме WAL-сегментов или innodb recovery.
- **MTTR и change failure rate:** Инициализация через init-скрипты и миграции (Flyway/Liquibase) — точки отказа. Автоматизация миграций без manual approval повышает change failure rate. Чек-лист деплоя должен включать валидацию дампа на staging.
- **RPO/RTO:** Для БД RPO = интервал бэкапа + WAL-архив. АО (AOF) Redis с `appendfsync everysec` даёт RPO ~1 сек. Логические дампы PostgreSQL через `pg_dump` — RPO = частота дампа.
- **Disaster recovery drill:** Бэкап без теста восстановления = не бэкап. Ежеквартально выполняйте drill: восстановите том/дамп в изолированном окружении и прогоните smoke-test.
- **Supply chain security:** Фиксируйте теги образов (`postgres:18-alpine`, не `postgres:latest`). Проверяйте SBOM и сигнатуры образов перед деплоем. Минимализируйте attack surface: Alpine-образы меньше Debian.
- **CI/CD gates:** Health check должен быть зелёным до того, как трафик пойдёт на контейнер. В pipeline: build → scan (Trivy) → test restore → deploy → smoke test.

### Официальные образы и их entrypoint'ы

| Сервис | Образ | Директория данных | Init-скрипты | Health check |
| :--- | :--- | :--- | :--- | :--- |
| PostgreSQL | `postgres:18-alpine` | `/var/lib/postgresql/data` | `/docker-entrypoint-initdb.d/` | `pg_isready -U $POSTGRES_USER` |
| MySQL | `mysql:9` | `/var/lib/mysql` | `/docker-entrypoint-initdb.d/` | `mysqladmin ping -u root -p$MYSQL_ROOT_PASSWORD` |
| MariaDB | `mariadb:11` | `/var/lib/mysql` | `/docker-entrypoint-initdb.d/` | `mariadb-admin ping` |
| Redis | `redis:8-alpine` | `/data` | нет (используйте `redis-cli` в init-контейнере) | `redis-cli ping` |
| MongoDB | `mongo:8` | `/data/db` | `/docker-entrypoint-initdb.d/` | `mongosh --eval "db.adminCommand('ping')"` |
| RabbitMQ | `rabbitmq:4-management` | `/var/lib/rabbitmq` | definitions JSON через `RABBITMQ_LOAD_DEFINITIONS` | `rabbitmq-diagnostics check_port_connectivity` |

### Тома: named vs bind

**Named volume (рекомендуется для данных):**

```yaml
services:
  db:
    image: postgres:18-alpine
    volumes:
      - pg_data:/var/lib/postgresql/data
volumes:
  pg_data:
```

**Bind mount (для конфигов и init-скриптов, не для данных):**

```yaml
services:
  db:
    image: postgres:18-alpine
    volumes:
      - ./init:/docker-entrypoint-initdb.d:ro
      - ./postgresql.conf:/etc/postgresql/postgresql.conf:ro
```

### Инициализация при первом запуске

Init-скрипты выполняются в алфавитном порядке, один раз, при пустой директории данных:

```
/docker-entrypoint-initdb.d/
├── 01-schema.sql        # DDL: CREATE TABLE
├── 02-seed.sql          # DML: начальные данные
└── 03-functions.sql.gz  # сжатые SQL тоже поддерживаются
```

**Важно:** изменение init-скрипта после первого запуска **не применяется** — том уже содержит данные. Для миграций используйте инструменты приложения (Flyway, Liquibase, Alembic), а не init-скрипты.

### Health checks

```yaml
services:
  db:
    image: postgres:18-alpine
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d appdb"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
```

`start_period` критичен: БД может стартовать дольше 30 секунд при большом объёме данных.

**Оркестрация:** Для Swarm/Kubernetes health check — источник `Ready`/`Not Ready`. Убедитесь, что `start_period` покрывает checkpoint/recovery, а `interval`/`timeout` не вызывают false-positive при пиковой нагрузке. В Swarm mode: `docker service create --health-cmd ... --health-retries 5 --health-interval 10s --health-timeout 5s`.

### Конфигурация

Три способа (в порядке предпочтения):

1. **Флаги командной строки:** `command: ["postgres", "-c", "shared_buffers=256MB", "-c", "max_connections=200"]`
2. **Монтирование конфига:** `postgresql.conf` / `my.cnf` через bind mount `:ro`
3. **Кастомный образ:** `COPY my.cnf /etc/mysql/conf.d/` — для сложных конфигураций

### Пользователи и права

Официальные образы запускают демона от непривилегированного пользователя. При использовании bind mount с хоста:

```bash
# Создать директорию с правильным владельцем (PostgreSQL: UID 999)
sudo mkdir -p /data/pgdata
sudo chown -R 999:999 /data/pgdata
```

Для named volume Docker сам управляет правами — это ещё одна причина предпочитать его.

**Важно для PostgreSQL:** UID зависит от базового образа:
- **Debian-based** (`postgres:18`): UID 999, GID 999
- **Alpine-based** (`postgres:18-alpine`): UID 70, GID 70

Это критично для bind-mount'ов: на Linux владелец папки на хосте должен совпадать с UID в контейнере, иначе — `Permission denied`. На macOS/Windows Docker Desktop выполняет автоматический маппинг прав.

### Ресурсы и graceful shutdown

```yaml
services:
  db:
    image: postgres:18-alpine
    deploy:
      resources:
        limits:
          memory: 4g
          cpus: '2'
    stop_grace_period: 60s
    stop_signal: SIGINT
    shm_size: '1gb'
```

- **Memory:** `deploy.resources.limits.memory` = кеш БД (`shared_buffers` / `innodb_buffer_pool_size`) + 25% на overhead. Без лимита — риск OOM Kill при пике.
- **shm_size:** Для PostgreSQL `/dev/shm` по умолчанию 64MB; `shared_buffers` часто требует больше. `shm_size: '1gb'` покрывает большинство production-сценариев.
- **stop_signal:** PostgreSQL корректнее завершается через `SIGINT` (Fast Shutdown) вместо `SIGTERM` (Smart Shutdown). `SIGINT` не ждёт завершения всех клиентских сессий, сохраняя консистентность данных.
- **stop_grace_period:** Должен превышать время checkpoint. Для PostgreSQL с большим `shared_buffers` — 60s. Для Redis — 20s достаточно.
- **init: true:** Вставляет tini как PID 1 для корректной обработки сигналов.

## Практические сценарии

### Сценарий 1: PostgreSQL с named volume и init-скриптами

```yaml
# docker-compose.yml
services:
  db:
    image: postgres:18-alpine
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
      POSTGRES_DB: appdb
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./init:/docker-entrypoint-initdb.d:ro
    secrets:
      - db_password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d appdb"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

volumes:
  pg_data:

secrets:
  db_password:
    file: ./secrets/db_password.txt
```

**Валидация:**
```bash
docker compose up -d db
docker compose ps db
# → db   Up (healthy)   5432/tcp

docker compose exec db psql -U app -d appdb -c "\dt"
# → List of relations
# → Schema | Name | Type | Owner
```

### Сценарий 2: MySQL / MariaDB

```yaml
services:
  db:
    image: mysql:9
    command: ["mysqld", "--innodb-buffer-pool-size=512M", "--max-connections=200"]
    environment:
      MYSQL_ROOT_PASSWORD_FILE: /run/secrets/db_root_password
      MYSQL_DATABASE: appdb
      MYSQL_USER: app
      MYSQL_PASSWORD_FILE: /run/secrets/db_password
    volumes:
      - mysql_data:/var/lib/mysql
      - ./init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "mysqladmin ping -h localhost"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  mysql_data:
```

**MariaDB** — drop-in замена: `image: mariadb:11`, тот же формат env-переменных и init-скриптов.

### Сценарий 3: Redis с persistence (AOF + RDB)

```yaml
services:
  cache:
    image: redis:8-alpine
    command: ["redis-server", "--appendonly", "yes", "--appendfsync", "everysec", "--maxmemory", "512mb", "--maxmemory-policy", "allkeys-lru"]
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

volumes:
  redis_data:
```

**Валидация persistence:**
```bash
docker compose exec cache redis-cli SET key1 "value1"
docker compose restart cache
docker compose exec cache redis-cli GET key1
# → "value1"
```

### Сценарий 4: Кастомный образ PostgreSQL (расширения)

Когда нужны расширения (PostGIS, TimescaleDB, pgvector):

```dockerfile
# syntax=docker/dockerfile:1
FROM postgres:18-alpine

# PostGIS в Alpine-сборке postgres
RUN apk add --no-cache postgresql18-postgis

# Или для Debian-базы:
# RUN apt-get update && apt-get install -y --no-install-recommends postgresql-18-postgis-3 && rm -rf /var/lib/apt/lists/*

COPY init/ /docker-entrypoint-initdb.d/
```

**Валидация:**
```bash
docker build -t my-postgis:17 .
docker run --rm my-postgis:17 psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS postgis;"
# → CREATE EXTENSION
```

### Сценарий 5: Бэкап тома через helper-контейнер

Данные в named volume недоступны с хоста напрямую — используйте helper-контейнер:

```bash
# Бэкап тома PostgreSQL
docker run --rm \
  -v pg_data:/source:ro \
  -v /backup:/backup \
  alpine:latest \
  tar czf /backup/pg_data-$(date +\%Y\%m\%d).tar.gz -C /source .

# Восстановление
docker run --rm \
  -v pg_data:/target \
  -v /backup:/backup \
  alpine:latest \
  tar xzf /backup/pg_data-20261004.tar.gz -C /target
```

**Логический бэкап (рекомендуется для PostgreSQL):**
```bash
docker exec <db_container> pg_dump -U app -d appdb | gzip > /backup/appdb-$(date +\%Y\%m\%d).sql.gz

# Восстановление
gunzip -c /backup/appdb-20261004.sql.gz | docker exec -i <db_container> psql -U app -d appdb
```

### Сценарий 6: Read-only FS + tmpfs

Redis и PostgreSQL поддерживают read-only rootfs при правильных tmpfs:

```yaml
services:
  cache:
    image: redis:8-alpine
    read_only: true
    tmpfs:
      - /tmp
    volumes:
      - redis_data:/data
```

PostgreSQL требует дополнительных tmpfs (`/tmp`, `/run/postgresql`) и `shm_size` для `/dev/shm`.

## Высокая доступность и disaster recovery

### Replication и failover

**PostgreSQL streaming replication:**
```yaml
services:
  primary:
    image: postgres:18-alpine
    environment:
      POSTGRES_REPLICATION_MODE: master
    volumes:
      - pg_primary:/var/lib/postgresql/data
    command: ["postgres", "-c", "wal_level=replica", "-c", "max_wal_senders=10"]

  replica:
    image: postgres:18-alpine
    environment:
      POSTGRES_REPLICATION_MODE: slave
      POSTGRES_MASTER_HOST: primary
    volumes:
      - pg_replica:/var/lib/postgresql/data
    depends_on:
      primary:
        condition: service_healthy
```

**Redis Sentinel (HA):**
```yaml
services:
  redis:
    image: redis:8-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis_data:/data

  sentinel:
    image: redis:8-alpine
    command: ["redis-sentinel", "/etc/redis/sentinel.conf"]
    volumes:
      - ./sentinel.conf:/etc/redis/sentinel.conf:ro
```

**Чек-лист HA:**
- [ ] Минимум 1 реплика для БД (primary + standby)
- [ ] Redis Sentinel — минимум 3 sentinel-контейнера
- [ ] Трафик идёт через load balancer / proxy (PgBouncer, HAProxy)
- [ ] Автоматический failover протестирован: `docker compose stop primary` → replica поднимается

### Point-in-time recovery (PITR)

PostgreSQL: для PITR нужен continuous archiving WAL:
```yaml
services:
  db:
    image: postgres:18-alpine
    environment:
      POSTGRES_INITDB_ARGS: "--data-checksums"
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./wal_archive:/wal_archive:rw
    command: ["postgres", "-c", "wal_level=replica", "-c", "archive_mode=on", "-c", "archive_command=cp %p /wal_archive/%f"]
```

Восстановление на момент времени: `pg_basebackup` + применение WAL-сегментов из `/wal_archive`.

### Централизованное логирование

Официальные образы пишут логи в stdout/stderr. Для production используйте centralized logging (ELK/Loki/Datadog):

```yaml
services:
  db:
    image: postgres:18-alpine
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "3"
        label: "app=postgres"
```

Сбор логов через sidecar-агент или драйвер Docker. Loki-драйвер: [Локи: драйвер и сбор логов](../../Docker_logs/loki_logging_driver_setup.md).

### Алертинг и SLI

| SLI | Порог | Действие |
| :--- | :--- | :--- |
| Доступность БД | < 99.9% | Проверить health check, сеть, лимиты |
| Latency запроса (P99) | > 500ms | Проверить кеш hit rate, slow queries |
| CPU контейнера | > 80% | Проверить индексы, connection pool |
| Memory usage | > 75% лимита | Увеличить лимит или оптимизировать кеш |
| Disk usage тома | > 80% | Расширение или очистка |
| Replication lag | > 10s | Проверить сеть/нагрузку primary |
| Cache hit rate (Redis) | < 90% | Увеличить maxmemory или проверить TTL |

## Безопасность и верификация

### Аудит и проверка

1. **Секреты:** Пароли через `_FILE` переменные (`POSTGRES_PASSWORD_FILE`) или Docker secrets — не через plain `environment`.
2. **Non-root:** Официальные образы уже запускают демона от непривилегированного пользователя. Не используйте `user: root`.
3. **Сеть:** БД не должны публиковать порты на хост (`ports:`) — только внутренние сети Compose. Для администрирования — `docker compose exec`.
4. **Обновления:** Фиксируйте мажорную версию (`postgres:18-alpine`, не `postgres:latest`).

**Supply chain security:**
- **Image signing:** Проверяйте подписи официальных образов (Docker Content Trust / Notary). Для production — сканируйте уязвимости (Trivy, Grype) перед деплоем.
- **SBOM:** Сохраняйте Software Bill of Materials для каждого образа. Это упрощает audit при уязвимостях (CVE) и соблюдение compliance.
- **Minimal base:** Alpine-образы (~5MB) меньше Debian (~100MB). Меньший attack surface, меньше патчей. Для PostgreSQL: `postgres:18-alpine` вместо `postgres:18`.

**CI/CD gates:**
- Health check должен быть зелёным до того, как трафик пойдёт на контейнер.
- В pipeline: build → scan (Trivy) → test restore → deploy → smoke test.
- Автоматический rollback при падении health check в production.

### Сетевая изоляция

```yaml
services:
  db:
    image: postgres:18-alpine
    networks:
      - backend
    # Нет ports: — БД недоступна извне

  app:
    image: my-app:latest
    networks:
      - frontend
      - backend

networks:
  frontend:
  backend:
    internal: true  # нет выхода в интернет
```

## Типичные ошибки и их решение

### Ошибка 1: Данные теряются после `docker compose down`

**Причина:** Данные в writable layer контейнера; `down` без `-v` удаляет контейнеры, но `down -v` удаляет и тома.

```bash
# Симптом: БД пуста после пересоздания контейнера
# Решение: named volume
volumes:
  - pg_data:/var/lib/postgresql/data
```

### Ошибка 2: "Permission denied" на bind mount

**Причина:** Директория хоста принадлежит root, демон БД работает от UID 999.

```bash
# Решение: chown для UID демона
sudo chown -R 999:999 /data/pgdata
# Или перейти на named volume
```

### Ошибка 3: Init-скрипты не выполняются

**Причина:** Том уже содержит данные (контейнер запускался ранее). Init-скрипты выполняются только при пустой директории данных.

```bash
# Решение: удалить том для повторной инициализации (ОСТОРОЖНО: данные теряются)
docker compose down -v && docker compose up -d
```

### Ошибка 4: OOM Kill при нагрузке

**Причина:** Лимит контейнера меньше, чем кеш БД (shared_buffers / innodb_buffer_pool_size).

```bash
# Диагностика
docker stats <db_container>
# → MEM USAGE / LIMIT: 1.9GiB / 2GiB

# Решение: лимит = кеш БД + 25% на overhead
docker compose up -d --scale db=1  # с deploy.resources.limits.memory: 4g
```

### Ошибка 5: Health check всегда unhealthy

**Причина:** Утилита health check требует аутентификации или `start_period` слишком мал.

```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U app -d appdb"]
  start_period: 30s   # время на первый старт
  retries: 5
```

## Логирование и мониторинг

### Логи

Официальные образы пишут логи в stdout/stderr — доступны через `docker logs`:

```bash
docker compose logs -f db
# → PostgreSQL Database directory appears to contain a database...
# → LOG:  database system is ready to accept connections
```

Ротация — через демон Docker:

```json
// daemon.json
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "3" }
}
```

### Метрики

| Сервис | Экспортер | Метрики |
| :--- | :--- | :--- |
| PostgreSQL | `postgres_exporter` | connections, cache hit rate, replication lag |
| MySQL | `mysqld_exporter` | queries/sec, slow queries, buffer pool |
| Redis | `redis_exporter` | memory usage, hit rate, connected clients |
| RabbitMQ | `rabbitmq_exporter` | queue depth, consumers, unacked |

Экспортеры развёртываются как sidecar или отдельные контейнеры: [Prometheus Exporters](../../../Prometheus/Exporters/other_exporters.md).

| Метрика | Порог | Действие |
| :--- | :--- | :--- |
| Replication lag (PG) | >10 MB | Проверить сеть/нагрузку primary |
| Cache hit rate (Redis) | <90% | Увеличить maxmemory |
| Connections (PG) | >80% max_connections | Пулинг (PgBouncer) или увеличение |
| Disk usage тома | >80% | Очистка/расширение |

## Управление данными и бэкапы

### Стратегия бэкапов

| Тип | Инструмент | Когда |
| :--- | :--- | :--- |
| Логический (SQL) | `pg_dump`, `mysqldump` | Малые БД, point-in-time restore |
| Физический (том) | `tar` через helper-контейнер | Большие БД, быстрое восстановление |
| Redis | `BGSAVE` / копия AOF-файла | Перед деплоем |

**Автоматизация через cron на хосте:**
```bash
# /etc/cron.d/db-backup
0 2 * * * root docker exec db pg_dump -U app appdb | gzip > /backup/appdb-$(date +\%Y\%m\%d).sql.gz
```

Подробно про cron: [Cron-задачи в контейнерах](./cron_jobs.md).

### Восстановление после сбоя

1. Остановите контейнер: `docker compose stop db`
2. Восстановите том из бэкапа (сценарий 5) или примените SQL-дамп
3. Запустите: `docker compose up -d db`
4. Проверьте: `docker compose exec db pg_isready`

**Валидация восстановления (DR drill):**
- Восстанавливайте бэкап в изолированном окружении (не production)
- Прогоняйте smoke-test: `SELECT 1`, основные запросы, репликация
- Измеряйте RTO: время от отказа до полного восстановления
- Фиксируйте результат drill: успех/провал, время, проблемы

## Лучшие практики

### Сводка рекомендаций

| Практика | Рекомендация | Причина |
| :--- | :--- | :--- |
| **Тома** | Named volume для данных | Переживает контейнер, права управляются Docker |
| **Секреты** | `*_FILE` переменные / secrets | Пароли не в plain environment |
| **Init** | `/docker-entrypoint-initdb.d/` для схемы | Детерминированная первичная инициализация |
| **Миграции** | Flyway/Liquibase/Alembic в приложении | Init-скрипты не повторяются |
| **Healthcheck** | `pg_isready` / `mysqladmin ping` / `redis-cli ping` | Корректный порядок запуска |
| **Пины** | `postgres:18-alpine`, не `latest` | Воспроизводимость |
| **Сеть** | `internal: true`, без `ports:` | БД не торчит в интернет |
| **Лимиты** | RAM = кеш БД + 25% | Защита от OOM Kill |
| **shm_size** | `>= shared_buffers` | Shared memory для параллельных запросов |
| **stop_signal** | `SIGINT` для PostgreSQL | Fast Shutdown вместо Smart Shutdown |
| **stop_grace_period** | 60s для PostgreSQL, 20s для Redis | Завершение checkpoint перед SIGKILL |
| **Scan** | Trivy/Grype в CI/CD | Уязвимости образа до деплоя |
| **DR drill** | Квартальный тест восстановления | RTO/RPO известны, не гипотетичны |
| **Бэкапы** | Логические дампы + тома | Point-in-time restore |

### Чек-лист перед деплоем

- [ ] Named volume для директории данных
- [ ] Пароли через secrets / `*_FILE`
- [ ] Healthcheck с `start_period` ≥ 30s
- [ ] БД во внутренней сети (нет `ports:`)
- [ ] Лимит памяти с учётом кеша БД
- [ ] `shm_size` ≥ `shared_buffers` (PostgreSQL)
- [ ] `stop_signal: SIGINT` + `stop_grace_period` (PostgreSQL)
- [ ] Init-скрипты проверены на пустом томе
- [ ] Бэкап автоматизирован, DR drill пройден
- [ ] Scan уязвимостей (Trivy) прошёл в CI/CD
- [ ] `restart: unless-stopped`
- [ ] Репликация и failover протестированы

## Смотрите также

- **[Управление томами Docker](../../Docker_fs/docker_volumes.md)** — named volumes, bind mounts, бэкапы.
- **[Multi-process контейнеры](../../Docker_logs/docker_multi_process_logging.md)** — если БД и приложение в одном контейнере (антипаттерн для production).
- **[Cron-задачи в контейнерах](./cron_jobs.md)** — автоматизация бэкапов.
- **[PostgreSQL в Docker](../../../Databases/PostgreSQL/Operations/docker_deployment.md)** — SSoT для глубокого погружения: PGDATA, UID 999 (Debian) / 70 (Alpine), `shm_size`, `stop_signal: SIGINT`, `stop_grace_period`.
- **[MySQL в Docker](../../../Databases/MySQL/docker.md)** — SSoT для глубокого погружения: архитектура образа (Oracle Linux), LTS vs Innovation, кастомный Dockerfile, UID 999.
- **[Redis overview](../../../Databases/redis_overview.md)** — persistence (RDB/AOF), eviction policies.
- **[Prometheus Exporters](../../../Prometheus/Exporters/other_exporters.md)** — мониторинг БД.
