# Развертывание PostgreSQL в Docker

## Определения

**postgres** — официальный Docker-образ PostgreSQL, поддерживаемый сообществом. Включает сервер СУБД, клиентские утилиты (`psql`, `pg_dump`, `pg_restore`, `pg_isready`) и скрипты `entrypoint` для автоматизации развертывания.

**PGDATA** — переменная окружения, определяющая абсолютный путь к директории с данными (Database Cluster) внутри контейнера. Для персистентности этот путь всегда должен быть примонтирован к тому (Volume).

**POSTGRES_PASSWORD_FILE** — безопасный способ передачи пароля через Docker Secrets или примонтированные файлы вместо открытых переменных окружения (предотвращает утечку через `docker inspect`).

**docker-entrypoint-initdb.d** — директория в образе, содержимое которой (`.sql`, `.sql.gz`, `.sh`) выполняется автоматически при **первом** запуске контейнера на пустом томе.

**Fast Shutdown (SIGINT)** — рекомендуемый метод остановки PostgreSQL в контейнере. В отличие от `Smart Shutdown` (SIGTERM), он не ждет завершения всех клиентских сессий, а немедленно прерывает их, сохраняя консистентность данных (предпочтительно для Docker).

## Предпосылки

1.  **Docker Engine & Compose:** Установленные и настроенные компоненты (рекомендуется Docker 24+).
2.  **Ресурсы:** Минимум 512MB RAM для пустого инстанса; для Production — согласно планируемой нагрузке.
3.  **Сетевой доступ:** Разрешение подключений в `pg_hba.conf` и firewall хоста.

## Основные концепции

### Управление данными и правами

PostgreSQL в Docker работает под системным пользователем `postgres` (стандартный **UID 999, GID 999**).

- **Персистентность:** Всегда монтируйте том в поддиректорию внутри точки монтирования, чтобы избежать конфликтов с системной папкой `lost+found` (актуально для Ext4). Рекомендуется: `-e PGDATA=/var/lib/postgresql/data/pgdata`.
- **Права доступа (Permissions):** 
  - На Linux bind-mounts требуют, чтобы владелец папки на хосте имел UID 999.
  - На macOS/Windows Docker Desktop выполняет автоматический маппинг прав.
- **Подробнее о томах:** **[Docker: Тома и персистентное хранение](../../../Docker/Docker_fs/docker_volumes.md)**.

### Тюнинг ресурсов и производительность

- **Shared Memory (shm_size):** PostgreSQL активно использует разделяемую память. В Docker по умолчанию лимит равен 64MB. **Обязательно** устанавливайте `shm_size` равным лимиту RAM контейнера или минимум 25% от доступной памяти.
- **Huge Pages:** Снижают нагрузку на TLB.
  - На хосте: `sysctl -w vm.nr_hugepages=1024`.
  - В контейнере: `huge_pages = try` (по умолчанию).
- **Stop Signal:** Docker отправляет `SIGTERM` (`Smart Shutdown`), что может привести к долгому ожиданию завершения сессий. Рекомендуется использовать `STOPSIGNAL SIGINT` (`Fast Shutdown`) для ускорения остановки без риска повреждения данных.

### Инициализация и логирование

- **Init-скрипты:** Выполняются строго один раз. Если нужно создать несколько БД или пользователей при старте, используйте `.sh` скрипт в `docker-entrypoint-initdb.d`.
- **Логи:** По умолчанию выводятся в `stdout`. Рекомендуется настроить `log_destination = 'stderr'` и собирать их через `fluentd`, `promtail` или напрямую через Docker Logging Driver.
- **Тюнинг через CLI:** Параметры конфигурации можно передавать напрямую в команду запуска: `docker run ... postgres -c 'max_connections=200'`.

### Сетевое взаимодействие и Безопасность

- **Сетевая изоляция:** Используйте `internal` сети в Docker Compose для БД, чтобы она была доступна только бэкенд-сервисам.
- **Защита I/O:** При использовании больших БД на Linux монтируйте тома на файловые системы **XFS** или **Ext4** с опцией `noatime`.
- **Upgrade-стратегии:**
  - **Minor:** Обновление тега образа (16.1 -> 16.2).
  - **Major:** Требует `pg_upgrade` (через спец. образы вроде `tianon/postgres-upgrade`) или `dump/restore`.

## Практические сценарии

### Сценарий 1: Запуск через Docker CLI

Базовый запуск с безопасной передачей пароля через файл:

```bash
# Создание сети для взаимодействия приложений
docker network create pg-backend

# Запуск контейнера
docker run --name pg-master \
  -d --network pg-backend \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/pg_pass \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v pg_data_volume:/var/lib/postgresql/data \
  -v $(pwd)/secrets/db_pass.txt:/run/secrets/pg_pass:ro \
  -p 127.0.0.1:5432:5432 \
  postgres:16-alpine
```

### Сценарий 2: Оптимальный Docker Compose (Best Practice)

Конфигурация с проверкой здоровья, лимитами ресурсов и правильной инициализацией:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: pg_prod
    shm_size: '1gb'
    restart: unless-stopped
    stop_signal: SIGINT
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

secrets:
  db_password:
    file: ./secrets/password.txt

volumes:
  pg_data:

networks:
  internal:
    driver: bridge
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

### Сценарий 4: Кастомный образ с расширениями

**Файл `Dockerfile`:**
```dockerfile
FROM postgres:16-alpine

# Установка зависимостей для сборки расширений
RUN apk add --no-cache --virtual .build-deps \
    gcc make musl-dev clang15 llvm15 util-linux-dev \
    postgresql16-contrib

# Настройка STOPSIGNAL для корректного завершения (Fast Shutdown)
STOPSIGNAL SIGINT

# Очистка временных зависимостей
RUN apk del .build-deps
```

### Сценарий 5: Администрирование и бэкапы (Cheat Sheet)

**Подключение внутри контейнера:**
```bash
docker exec -it pg_prod psql -U admin -d main_db
```

**Создание дампа (Logical Backup):**
```bash
docker exec pg_prod pg_dump -U admin main_db | gzip > backup_$(date +%F).sql.gz
```

**Восстановление:**
```bash
gunzip < backup.sql.gz | docker exec -i pg_prod psql -U admin -d main_db
```

**Горячее обновление конфига (Reload):**
```bash
docker exec -it pg_prod psql -U admin -c "SELECT pg_reload_conf();"
```

## Валидация и проверка

1.  **Статус готовности:** `docker exec pg_prod pg_isready`.
2.  **Проверка логов инициализации:** `docker logs pg_prod | grep "database system is ready to accept connections"`.
3.  **Проверка разделяемой памяти:** `docker inspect pg_prod --format '{{.HostConfig.ShmSize}}'`.

## Типовые проблемы и Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Zombie processes** | PostgreSQL — не PID 1. | Используйте `STOPSIGNAL SIGINT` или флаг `--init`. |
| **Permission denied (Data)** | Несовпадение UID/GID. | `chown -R 999:999` на папку хоста или используйте Named Volumes. |
| **Container OOM Kill** | Нехватка RAM или лимитов. | Установите `memory limit` > `shared_buffers` + 200MB (overhead). |
| **Init scripts not running** | Папка `PGDATA` не пуста. | Очистите том перед первым запуском. |
| **Shared memory error** | Лимит `shm_size` слишком мал. | Увеличьте `shm_size` в `compose.yaml` или параметром `--shm-size`. |

## Дополнительная информация

### Безопасность

1. **Минимизация:** Предпочитайте `alpine` версии образа.
2. **Изоляция:** Публикуйте порты только на `127.0.0.1`, если доступ нужен только для отладки.
3. **Секреты:** Используйте Docker Secrets (`POSTGRES_PASSWORD_FILE`) вместо переменных окружения.

### Связанные документы

- **[Наблюдаемость PostgreSQL](./observability.md)** — мониторинг контейнеров и метрики.
- **[Оптимизация производительности](./performance_tuning.md)** — детальный тюнинг параметров.
- **[PostgreSQL в Kubernetes](./kubernetes_deployment.md)** — использование CloudNativePG оператора.
- **[Тома в Docker](../../../Docker/Docker_fs/docker_volumes.md)** — детальный разбор типов монтирования.
- **[Автоматизация бэкапов](./backup_automation.md)** — стратегии резервного копирования.
