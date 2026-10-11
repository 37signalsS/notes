# Развертывание PostgreSQL в Docker

**Актуально для:** PostgreSQL 14–18 (теги образов `postgres:14`–`postgres:18`); Docker Engine 29.x, Compose v5.x

## Определения

**postgres** — официальный Docker-образ PostgreSQL, поддерживаемый сообществом (docker-library/postgres). Включает сервер СУБД, клиентские утилиты (`psql`, `pg_dump`, `pg_restore`, `pg_isready`) и скрипт `entrypoint` для автоматизации развертывания. Два варианта базовой ОС: Debian (UID/GID `999`) и Alpine (UID/GID `70`).

**PGDATA** — переменная окружения, определяющая абсолютный путь к директории с данными (Database Cluster) внутри контейнера. Для персистентности этот путь должен быть примонтирован к тому (Volume).

**POSTGRES_PASSWORD_FILE** — безопасный способ передачи пароля через Docker Secrets или примонтированные файлы вместо открытых переменных окружения (предотвращает утечку через `docker inspect`).

**POSTGRES_INITDB_ARGS** — дополнительные аргументы `initdb` (например, `--data-checksums`, `--auth-local=scram-sha-256 --auth-host=scram-sha-256`). Применяются только при первичной инициализации кластера.

**docker-entrypoint-initdb.d** — директория в образе, содержимое которой (`.sql`, `.sql.gz`, `.sql.xz`, `.sql.zst`, `.sh`) выполняется автоматически в **алфавитном порядке** при **первом** запуске контейнера на пустом томе. Исполняемые `.sh` запускаются, неисполняемые — подключаются через `source`.

**Fast Shutdown (SIGINT)** — рекомендуемый метод остановки PostgreSQL в контейнере. В отличие от `Smart Shutdown` (SIGTERM), он не ждёт завершения всех клиентских сессий, а немедленно прерывает их, сохраняя консистентность данных.

**stop_grace_period** — время ожидания остановки контейнера после сигнала остановки перед принудительным `SIGKILL`. По умолчанию **10 секунд**; для PostgreSQL с большим объёмом данных рекомендуется увеличить (30–60s).

**shm_size** — лимит разделяемой памяти `/dev/shm` контейнера. В Docker по умолчанию всего **64MB**, что часто недостаточно для настроенного `shared_buffers`.

**internal network** — сеть Docker без маршрута наружу: контейнеры общаются только внутри сети, доступ извне невозможен.

## Предпосылки

1.  **Docker Engine & Compose:** Docker Engine 29.x и Compose v5.x (проверка: `docker version`, `docker compose version`). Compose v2+ — плагин `docker compose`; старый автономный `docker-compose` (v1) больше не развивается.
2.  **Ресурсы:** Минимум 512MB RAM для пустого инстанса; для Production — согласно планируемой нагрузке.
3.  **Хранилище:** Отдельный том для данных; на Linux — файловая система **XFS** или **Ext4** с опцией `noatime` для лучшей I/O.
4.  **Сетевой доступ:** Разрешение подключений в `pg_hba.conf` и firewall хоста.

## Основные концепции

### Управление данными и правами

PostgreSQL в Docker работает под системным пользователем `postgres`, но его идентификатор **зависит от варианта образа**:

- **Debian-based** (`postgres:17`, `postgres:17-bookworm`): **UID 999, GID 999**.
- **Alpine-based** (`postgres:17-alpine`): **UID 70, GID 70**.

Это критично для bind-mount'ов: на Linux владелец папки на хосте должен совпадать с UID пользователя в контейнере, иначе — `Permission denied`. На macOS/Windows Docker Desktop выполняет автоматический маппинг прав.

- **Персистентность:** Всегда монтируйте том в поддиректорию внутри точки монтирования, чтобы избежать конфликтов с системной папкой `lost+found` (актуально для Ext4). Рекомендуется: `-e PGDATA=/var/lib/postgresql/data/pgdata`.
- **Named Volumes vs bind-mount:** для данных БД предпочтительны именованные тома (Docker управляет правами); bind-mount — для init-скриптов и конфигов в режиме `:ro`.
- **Произвольный пользователь:** образ поддерживает запуск от произвольного UID через `--user` (в Debian-вариантах — через `nss_wrapper`); достаточно, чтобы владелец `$PGDATA` совпадал.
- **Подробнее о томах:** **[Docker: Тома и персистентное хранение](../../../Docker/Docker_fs/docker_volumes.md)**.

### Тюнинг ресурсов и производительности

- **Shared Memory (shm_size):** PostgreSQL использует разделяемую память для `shared_buffers` и параллельных запросов. Лимит `/dev/shm` в Docker по умолчанию — 64MB; при превышении — ошибка `could not resize shared memory segment ... No space left on device` (SQLSTATE 53100). **Правило: `shm_size` должен быть не меньше `shared_buffers`** (с запасом). В Swarm-режиме — tmpfs-том с `size`.
- **Huge Pages:** Снижают нагрузку на TLB.
  - На хосте: `sysctl -w vm.nr_hugepages=1024` (количество рассчитывается от `shared_buffers`).
  - В контейнере: `huge_pages = try` (по умолчанию).
- **Остановка контейнера:** Docker отправляет `SIGTERM` и ждёт `stop_grace_period` (по умолчанию 10s), затем `SIGKILL`. Для PostgreSQL: `stop_signal: SIGINT` (`Fast Shutdown`) + увеличенный `stop_grace_period`. Замечание: `docker compose restart` игнорирует `stop_grace_period` (всегда 10s) — используйте `docker compose restart -t 60 <service>` или `docker stop -t 60`.
- **Ограничение файловых дескрипторов:** при большом числе соединений проверьте `ulimits.nofile` (soft/hard) — PostgreSQL открывает файл на соединение.
- **Тюнинг через CLI:** Параметры конфигурации можно передавать напрямую в команду запуска: `docker run ... postgres -c 'max_connections=200'`.

### Инициализация и логирование

- **Init-скрипты:** Выполняются строго один раз — только если `$PGDATA` пуст. Скрипты исполняются в алфавитном порядке (префиксы `01-`, `02-` задают последовательность). Если нужно создать несколько БД или пользователей при старте, используйте `.sh` скрипт в `docker-entrypoint-initdb.d`.
- **Логи:** По умолчанию выводятся в `stdout`/`stderr`. Рекомендуется `log_destination = 'stderr'` и `logging_collector = off` — сбор через Docker Logging Driver (fluentd, promtail и т.п.).
- **Healthcheck:** `pg_isready` проверяет готовность соединений, но не возможность записи; для критичных приложений строже: `psql -U admin -d main_db -c 'SELECT 1'`.

### Сетевое взаимодействие и безопасность

- **Сетевая изоляция:** Используйте `internal: true` сети в Docker Compose для БД, чтобы она была доступна только бэкенд-сервисам.
- **Публикация портов:** Публикуйте только на `127.0.0.1` (`-p 127.0.0.1:5432:5432`), если доступ нужен только для отладки с хоста.
- **Upgrade-стратегии:**
  - **Minor:** Обновление тега образа (17.10 -> 17.11) — `pg_upgrade` не требуется, достаточно пересоздать контейнер на том же томе.
  - **Major:** Требует `pg_upgrade` или `dump/restore`. Образ `tianon/postgres-upgrade:OLD-to-NEW` (например, `17-to-18`) — PoC от мейнтейнера официального образа: «adapt it for your needs, don't expect it to work as-is». Особенности: требует чистого shutdown старого кластера (`pg_ctl stop` внутри контейнера перед остановкой), совпадения `--data-checksums` на обоих кластерах и deprecated флага `--link`. Надёжная альтернатива для Production — логический `pg_dump`/`pg_restore`.

## Практические сценарии

### Сценарий 1: Запуск через Docker CLI

Базовый запуск с безопасной передачей пароля через файл:

```bash
# Создание сети для взаимодействия приложений
docker network create pg-backend

# Запуск контейнера
docker run --name pg-master \
  -d --network pg-backend \
  --init \
  --shm-size=1gb \
  --stop-signal=SIGINT \
  --stop-timeout=60 \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/pg_pass \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v pg_data_volume:/var/lib/postgresql/data \
  -v $(pwd)/secrets/db_pass.txt:/run/secrets/pg_pass:ro \
  -p 127.0.0.1:5432:5432 \
  postgres:17-alpine
```

### Сценарий 2: Оптимальный Docker Compose (Best Practice)

Конфигурация с проверкой здоровья, лимитами ресурсов и правильной инициализацией:

```yaml
services:
  postgres:
    image: postgres:17-alpine   # в production пиньте patch: postgres:17.11-alpine
    container_name: pg_prod
    shm_size: '1gb'               # >= shared_buffers
    restart: unless-stopped
    stop_signal: SIGINT           # Fast Shutdown
    stop_grace_period: 60s        # по умолчанию 10s, затем SIGKILL
    init: true                    # сбор зомби (docker-init)
    # Тюнинг параметров через аргументы командной строки
    command: >
      postgres -c 'shared_buffers=256MB'
               -c 'max_connections=200'
               -c 'logging_collector=off'
               -c 'log_destination=stderr'
    environment:
      - POSTGRES_USER=admin
      - POSTGRES_DB=main_db
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
      - PGDATA=/var/lib/postgresql/data/pgdata
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./init-sql:/docker-entrypoint-initdb.d:ro
    secrets:
      - db_password
    ulimits:
      nofile:
        soft: 65535
        hard: 65535
    tmpfs:
      - /var/run/postgresql
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1024M
        reservations:
          memory: 512M
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U admin -d main_db"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - internal

# Зависимые сервисы ждут готовности БД:
#   api:
#     depends_on:
#       postgres:
#         condition: service_healthy

secrets:
  db_password:
    file: ./secrets/password.txt

volumes:
  pg_data:

networks:
  internal:
    driver: bridge
    internal: true   # нет маршрута наружу
```

### Сценарий 3: Инициализация нескольких БД и пользователей

Официальный образ создает только одну БД. Для сложной структуры используйте `.sh` скрипт.

**Файл `./init-sql/01-init.sh`:**
```bash
#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER dev_user WITH PASSWORD 'dev_pass';
    CREATE DATABASE dev_db;
    GRANT ALL PRIVILEGES ON DATABASE dev_db TO dev_user;

    CREATE SCHEMA IF NOT EXISTS extensions;
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp" SCHEMA extensions;
EOSQL
# → результат: созданы БД dev_db и расширения при первом старте.
```

**Замечания:**
- `ON_ERROR_STOP=1` прерывает инициализацию при любой ошибке — иначе скрипт «проглотит» сбой и контейнер стартует с неполной схемой.
- SQL-файлы в `docker-entrypoint-initdb.d` должны быть читаемы (`chmod 644`), иначе — `Permission denied`.
- Модули contrib (`pg_stat_statements`, `uuid-ossp`, `pgcrypto`) доступны в официальном образе; в Alpine-вариантах расширения, не входящие в `postgres-contrib`, требуют сборки в собственном образе.

### Сценарий 4: Кастомный образ с расширениями

Если требуется расширение, отсутствующее в официальном образе (например, `pgvector`), используйте готовый образ-расширение или соберите своё:

**Вариант A — готовый образ `pgvector/pgvector` (официальный образ проекта pgvector):**
```bash
docker run -d --name pgvec \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/pg_pass \
  -v pgvec_data:/var/lib/postgresql/data \
  -v $(pwd)/secrets/db_pass.txt:/run/secrets/pg_pass:ro \
  pgvector/pgvector:pg16
docker exec pgvec psql -U postgres -c "CREATE EXTENSION vector;"
# → результат: расширение vector установлено
```

**Вариант B — собственная сборка (по паттерну Dockerfile проекта pgvector):**
```dockerfile
FROM postgres:16-bookworm

# Сборка расширения из исходников с последующим удалением тулчейна
RUN apt-get update \
 && apt-mark hold locales \
 && apt-get install -y --no-install-recommends build-essential postgresql-server-dev-16 \
 && cd /tmp \
  && git clone --branch v0.8.7 --depth 1 https://github.com/pgvector/pgvector.git \
 && cd pgvector && make && make install \
 && apt-get remove -y build-essential postgresql-server-dev-16 \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /tmp/pgvector

STOPSIGNAL SIGINT
```

### Сценарий 5: Администрирование и бэкапы (Cheat Sheet)

**Подключение внутри контейнера:**
```bash
# В compose-проекте предпочтительнее:
docker compose exec postgres psql -U admin -d main_db
# Или напрямую:
docker exec -it pg_prod psql -U admin -d main_db
```

**Создание дампа (Logical Backup):**
```bash
# Custom-формат: сжатие и выборочное восстановление через pg_restore
docker exec pg_prod pg_dump -U admin -Fc -d main_db > backup_$(date +%F).dump
```

**Восстановление:**
```bash
docker exec -i pg_prod pg_restore -U admin -d main_db --clean --if-exists < backup.dump
```

**Горячее обновление конфига (Reload):**
```bash
docker exec pg_prod psql -U admin -c "SELECT pg_reload_conf();"
```

**Замечания для автоматизации:**
- В cron/systemd-таймерах используйте `docker exec` **без** `-it` — иначе ошибка `the input device is not a TTY`.
- Подробнее о стратегиях и ротации бэкапов: **[Автоматизация бэкапов](./backup_automation.md)**.

## Операции и команды

| Команда | Назначение |
| :--- | :--- |
| `docker compose up -d` | Запуск стека (сборка/пересоздание при изменении compose-файла) |
| `docker compose ps` | Статус контейнеров проекта |
| `docker compose logs -f postgres` | Трансляция логов БД |
| `docker compose config` | Валидация и рендер compose-файла (проверка перед apply) |
| `docker compose exec postgres psql` | Подключение к БД внутри проекта |
| `docker compose restart -t 60 postgres` | Перезапуск с учётом времени graceful-stop (`restart` сам не читает `stop_grace_period`) |
| `docker compose down` | Остановка и удаление контейнеров/сетей (**тома сохраняются**) |
| `docker compose pull` | Обновление образа до актуального тега |
| `docker volume ls` / `inspect` / `rm` | Управление именованными томами |
| `docker image ls postgres` / `pull` / `tag` | Управление образами |
| `docker stats --no-stream pg_prod` | Потребление CPU/RAM контейнером |
| `docker inspect --format '{{.HostConfig.ShmSize}}' pg_prod` | Проверка лимита `/dev/shm` |
| `docker stop -t 60 pg_prod` | Остановка с кастомным grace period |

## Валидация и проверка

1.  **Статус готовности:** `docker compose ps` (колонка Health: `healthy`) или `docker exec pg_prod pg_isready`.
2.  **Проверка логов инициализации:** `docker logs pg_prod | grep "database system is ready to accept connections"`.
3.  **Проверка разделяемой памяти:** `docker inspect pg_prod --format '{{.HostConfig.ShmSize}}'` (должен быть >= `shared_buffers`).
4.  **Проверка внутреннего лимита:** `docker exec pg_prod df -h /dev/shm`.
5.  **Проверка сети:** `docker network inspect pg-backend --format '{{.Internal}}'` → `true` для internal-сетей.
6.  **Приёмочное тестовое подключение** от имени приложения: `docker exec pg_prod psql -U app_user -d main_db -c 'SELECT 1'`.

## Типовые проблемы и Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Zombie processes** | PostgreSQL — PID 1, но не реапитит зомби сторонних процессов. | `init: true` в compose или флаг `--init` при `docker run`. |
| **Permission denied (Data)** | Несовпадение UID/GID (999 для Debian, 70 для Alpine). | `chown -R 999:999` (или `70:70`) на папку хоста, либо используйте Named Volumes. |
| **Container OOM Kill** | Нехватка RAM или лимитов. | Установите `memory limit` > `shared_buffers` + overhead. |
| **Init scripts not running** | Папка `PGDATA` не пуста. | Инициализация выполняется только на пустом томе; очистите том перед первым запуском. |
| **Shared memory error (SQLSTATE 53100)** | `shm_size` меньше `shared_buffers`. | Увеличьте `shm_size` в `compose.yaml` или параметром `--shm-size`. |
| **«the input device is not a TTY»** | `-it` в cron/таймере. | Уберите `-it` из `docker exec` в скриптах автоматизации. |
| **Задержка 10s при stop/restart** | `stop_grace_period` по умолчанию; `compose restart` его игнорирует. | `stop_grace_period: 60s` + `docker compose restart -t 60`. |
| **pg_upgrade: checksums mismatch** | Кластеры с разным `--data-checksums`. | Инициализируйте оба кластера с `--data-checksums` (`POSTGRES_INITDB_ARGS`). |
| **«password authentication failed» после смены `POSTGRES_PASSWORD`** | Переменные применяются только при первичной инициализации. | Смена пароля — через `ALTER ROLE ... PASSWORD` внутри БД, не через переменную. |

## Лучшие практики

- **Пиньте версии образа:** в production — patch-тег (`postgres:17.11-alpine`), а не `latest` и не плавающий мажорный тег — иначе `docker compose pull` незаметно обновит мажорную версию PostgreSQL.
- **Секреты:** Docker Secrets (`POSTGRES_PASSWORD_FILE`) вместо переменных окружения.
- **Изоляция:** `internal: true` сети для БД; публикация порта только на `127.0.0.1`, если доступ нужен для отладки.
- **Корректный жизненный цикл:** `stop_signal: SIGINT`, `stop_grace_period`, `init: true`.
- **Минимальные права приложений:** приложение подключается не суперпользователем — см. **[Управление ролями и правами доступа (RBAC)](./role_management.md)**.
- **Мониторинг:** `docker stats` + метрики PostgreSQL — **[Наблюдаемость PostgreSQL](./observability.md)**.
- **Логи:** `stderr` и Docker Logging Driver вместо файлов внутри контейнера.
- **Конфигурация:** не монтируйте `postgresql.conf` внутрь `PGDATA`; передавайте параметры через `command: postgres -c ...` или `-c config_file=/path/to/postgresql.conf` с отдельным монтированием.

## Очистка и откат

**Остановка и удаление стека:**
```bash
docker compose down          # контейнеры и сети удаляются, тома сохраняются
docker compose down -v       # ВНИМАНИЕ: удаляет и именованные тома (данные БД!)
```

**Очистка ресурсов:**
```bash
docker volume rm pg_data                 # удаление конкретного тома (данные теряются)
docker volume prune                      # неиспользуемые тома
docker image prune                       # «висящие» образы
docker system prune                      # остановленные контейнеры, сети, висящие образы (тома НЕ трогает)
docker system prune -a                   # + неиспользуемые образы (проверьте перед запуском!)
```

**Откат образа:**
```bash
# Откат на предыдущий patch в пределах мажорной версии:
docker compose pull && docker compose up -d   # после правки тега в compose.yaml
```

**Важно:** downgrade PostgreSQL на более старую мажорную версию не поддерживается (`PGDATA` нового кластера не читается старым сервером). Восстановление на старую версию — только из логического бэкапа (`pg_dump`/`pg_restore`).

## Дополнительная информация

### Связанные документы

- **[Наблюдаемость PostgreSQL](./observability.md)** — мониторинг контейнеров и метрики.
- **[Оптимизация производительности](./performance_tuning.md)** — детальный тюнинг параметров.
- **[PostgreSQL в Kubernetes](./kubernetes_deployment.md)** — оркестрация в Kubernetes.
- **[Тома в Docker](../../../Docker/Docker_fs/docker_volumes.md)** — детальный разбор типов монтирования.
- **[Автоматизация бэкапов](./backup_automation.md)** — стратегии резервного копирования.
- **[Управление ролями и правами доступа (RBAC)](./role_management.md)** — минимальные права для приложений.
