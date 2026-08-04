# Развертывание PostgreSQL в Docker

## Определения

**postgres** — официальный Docker-образ PostgreSQL. Включает сервер СУБД, утилиты (`psql`, `pg_dump`) и `entrypoint`-скрипты для автоматизации развертывания.

**PGDATA** — переменная окружения, определяющая путь к файлам данных внутри контейнера. Для персистентности этот путь всегда должен быть примонтирован к тому (Volume).

**POSTGRES_PASSWORD_FILE** — безопасный способ передачи пароля через Docker Secrets или примонтированные файлы вместо открытых переменных окружения.

**docker-entrypoint-initdb.d** — директория в образе, скрипты из которой (`.sql`, `.sh`, `.sql.gz`) выполняются автоматически при **первом** запуске контейнера на пустом томе.

## Основные концепции

### Управление данными и правами

PostgreSQL в Docker работает под пользователем `postgres` (стандартный UID 999, GID 999). 

- **Персистентность:** Всегда монтируйте том в поддиректорию внутри точки монтирования, чтобы избежать конфликтов с `lost+found`. Рекомендуется: `-e PGDATA=/var/lib/postgresql/data/pgdata`.
- **Права доступа (Permissions):** 
  - На Linux bind-mounts требуют, чтобы владелец папки на хосте имел UID 999.
  - На macOS/Windows Docker Desktop выполняет автоматический маппинг прав, ручная настройка обычно не требуется.
- **Подробнее о томах:** [Docker: Тома и персистентное хранение](../../../Docker/Docker_fs/docker_volumes.md).

### Тюнинг ресурсов и производительность

В контейнеризированной среде PostgreSQL требует специфических настроек ядра и Docker-демона.

- **Shared Memory (shm_size):** PostgreSQL активно использует разделяемую память. В Docker Compose по умолчанию лимит `shm_size` равен 64MB, чего недостаточно для нагруженных БД. Рекомендуется устанавливать `shm_size` равным лимиту оперативной памяти контейнера.
- **Huge Pages:** Для повышения производительности (снижение нагрузки на TLB) рекомендуется включать Huge Pages.
  - На хосте: `sysctl -w vm.nr_hugepages=1024`
  - В контейнере: `huge_pages = try` (по умолчанию).
- **Stop Signal:** По умолчанию Docker отправляет `SIGTERM` для остановки, что в PostgreSQL приводит к `Smart Shutdown` (ожидание завершения всех сессий). Для быстрого, но безопасного закрытия в Docker рекомендуется использовать `STOPSIGNAL SIGINT` (Fast Shutdown).

### Инициализация и логирование

- **Init-скрипты:** Выполняются строго один раз. Если нужно создать несколько баз данных или пользователей при старте, используйте `.sh` скрипт в `docker-entrypoint-initdb.d`.
- **Логи:** По умолчанию выводятся в `stdout`. Для SRE-задач рекомендуется настроить `log_destination = 'stderr'` и собирать их через `fluentd` или `promtail`.
- **Тюнинг через CLI:** Параметры конфигурации можно передавать напрямую в команду запуска контейнера: `docker run ... postgres -c 'max_connections=200'`.

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
    restart: unless-stopped
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

Официальный образ создает только одну БД через переменные. Для создания сложной структуры используйте `.sh` скрипт.

**Файл `./init-sql/01-init-multiple-databases.sh`:**
```bash
#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER dev_user WITH PASSWORD 'dev_pass';
    CREATE DATABASE dev_db;
    GRANT ALL PRIVILEGES ON DATABASE dev_db TO dev_user;
    
    CREATE DATABASE test_db;
    GRANT ALL PRIVILEGES ON DATABASE test_db TO dev_user;
EOSQL
# → результат: созданы БД dev_db и test_db при первом старте.
```

### Сценарий 4: Кастомный образ с расширениями

Если требуются расширения, не входящие в стандартную поставку (например, `pg_repack` или `pg_stat_statements`), соберите свой образ.

**Файл `Dockerfile`:**
```dockerfile
FROM postgres:16-alpine

# Установка зависимостей для сборки расширений
RUN apk add --no-cache --virtual .build-deps \
    gcc make musl-dev clang15 llvm15 util-linux-dev

# Пример установки расширения через пакетный менеджер (если есть) или сборки
RUN apk add --no-cache postgresql16-contrib

# Настройка STOPSIGNAL для корректного завершения
STOPSIGNAL SIGINT

# Удаление временных зависимостей
RUN apk del .build-deps
```

### Сценарий 5: Администрирование и бэкапы

**Подключение через psql с хоста:**
Требуется установленный клиент (`sudo apt install postgresql-client`).
```bash
psql -h 127.0.0.1 -U admin -d main_db
```

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

### Типовые проблемы и Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Zombie processes** | PostgreSQL — не PID 1. | Используйте `STOPSIGNAL SIGINT` или `--init` флаг в Docker. |
| **Permission denied (Data)** | Несовпадение UID/GID. | `chown -R 999:999` на папку хоста или используйте Named Volumes. |
| **Container OOM Kill** | Нехватка RAM или лимитов. | Установите `deploy.resources.limits.memory` > `shared_buffers` + 200MB. |
| **Init scripts not running** | Папка `PGDATA` не пуста. | Очистите том/папку перед первым запуском. |

## Дополнительная информация

### Безопасность

1. **Минимизация:** Всегда предпочитайте образы на базе `alpine` или `distroless` (если есть поддержка).
2. **Изоляция:** Используйте `internal` сети в Docker Compose для БД, публикуя порт только на `127.0.0.1` для отладки.
3. **Секреты:** Используйте Docker Secrets (`/run/secrets/`) вместо переменных окружения для паролей в production.
4. **Защита I/O:** При использовании больших БД на Linux монтируйте тома на файловые системы XFS или Ext4 с опцией `noatime`.

### Связанные документы

- [Наблюдаемость PostgreSQL](./observability.md) — мониторинг контейнеров и метрики.
- [Оптимизация производительности](./performance_tuning.md) — детальный тюнинг параметров `postgresql.conf`.
- [PostgreSQL в Kubernetes](./kubernetes_deployment.md) — использование CloudNativePG оператора.
- [Тома в Docker](../../../Docker/Docker_fs/docker_volumes.md) — детальный разбор типов монтирования.
- [Безопасность Docker](../../../Docker/Docker_security/vulnerability_scanning.md) — сканирование образов на CVE.
