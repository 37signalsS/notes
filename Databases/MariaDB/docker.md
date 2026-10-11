# MariaDB в Docker: эксплуатация

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS, mariadb Docker image

## Определения

*   **Официальный образ `mariadb`** — Docker-образ MariaDB Foundation (Docker Hub: `mariadb`, GitHub: `docker-library/mariadb`). Базовые образы: Ubuntu (по умолчанию), RHEL/UBI (варианты `ubi`, `rhel`). Теги: `latest` (rolling), `lts` (последний LTS), версионные (`11.8`, `10.11`).
*   **Базовая ОС образа:** 10.6/10.11 — Ubuntu 22.04; 11.4–12.3 — Ubuntu 24.04; 13.0+ — Ubuntu 26.04. RHEL/UBI-варианты: 10.6–11.8 на UBI 9, 12.3+ на UBI 10.
*   **Environment variables** — переменные для инициализации контейнера: `MARIADB_ROOT_PASSWORD`, `MARIADB_ALLOW_EMPTY_ROOT_PASSWORD`, `MARIADB_RANDOM_ROOT_PASSWORD`, `MARIADB_DATABASE`, `MARIADB_USER`, `MARIADB_PASSWORD`.
*   **`docker-entrypoint.sh`** — скрипт инициализации: создаёт datadir, запускает `mariadb-upgrade`, выполняет `/docker-entrypoint-initdb.d/*.sql|.sh`.
*   **`/docker-entrypoint-initdb.d/`** — каталог с init-скриптами (SQL, shell), выполняемых при первом запуске (пустой datadir).
*   **Healthcheck** — встроенная проверка `mariadb-admin ping` (в новых образах).

## Базовые концепции

### Варианты образов

| Тег | Назначение |
| :--- | :--- |
| `mariadb:latest` | Последний rolling-релиз (не для production) |
| `mariadb:lts` | Последний LTS (рекомендуется для production) |
| `mariadb:11.8` | Конкретная версия (pin для reproducibility) |
| `mariadb:11.8-ubi` | На базе UBI (RHEL-совместимый) |

**Рекомендация:** для production используйте версионный тег (`mariadb:11.8`), а не `latest`.

### Persistent storage

Данные MariaDB должны храниться в volume, иначе теряются при удалении контейнера:

*   **Named volume:** `docker volume create mariadb-data` — управляется Docker.
*   **Bind mount:** `-v /host/path:/var/lib/mysql` — путь на хосте.
*   **Datadir в контейнере:** `/var/lib/mysql`.

**Важно:** datadir должен принадлежать пользователю `mysql` (UID 999 в образе). При bind-mount проверьте права.

### Ограничения контейнеризации

*   **Galera** в Docker требует дополнительной настройки сети (wsrep-адреса) и обычно запускается через StatefulSet (K8s) или docker-compose с фиксированными IP.
*   **Performance:** для production на bare-metal/VM предпочтительнее; Docker — для staging, dev, CI.
*   **cgroups:** лимиты памяти/CPU контейнера влияют на `innodb_buffer_pool_size` (см. **[Мониторинг](monitoring.md)** — cgroups).

## Практические сценарии

### 1. Запуск контейнера

```bash
# Базовый запуск с persistent volume
docker run -d \
  --name mariadb \
  -e MARIADB_ROOT_PASSWORD=StrongRootPassword \
  -e MARIADB_DATABASE=shop \
  -e MARIADB_USER=app \
  -e MARIADB_PASSWORD=AppPassword \
  -p 3306:3306 \
  -v mariadb-data:/var/lib/mysql \
  mariadb:11.8

# Проверка
docker logs mariadb
docker exec mariadb mariadb-admin -u root -pStrongRootPassword ping
# → mysqld is alive
```

### 2. Environment variables

| Переменная | Назначение |
| :--- | :--- |
| `MARIADB_ROOT_PASSWORD` | Пароль root (обязательно, или `RANDOM`/`ALLOW_EMPTY`) |
| `MARIADB_RANDOM_ROOT_PASSWORD` | Генерировать случайный пароль root (`yes`) |
| `MARIADB_ALLOW_EMPTY_ROOT_PASSWORD` | Пустой пароль root (`yes` — только для dev) |
| `MARIADB_DATABASE` | Создать БД при инициализации |
| `MARIADB_USER` | Создать пользователя |
| `MARIADB_PASSWORD` | Пароль пользователя |

**Валидация:**
```bash
docker exec mariadb mariadb -u root -pStrongRootPassword \
  -e "SHOW DATABASES;"
# → information_schema, mysql, performance_schema, shop, sys
```

### 3. Init-скрипты

```bash
# SQL-скрипт выполняется при первом запуске
cat > init.sql <<'EOF'
CREATE TABLE shop.products (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(255)
) ENGINE=InnoDB;
INSERT INTO shop.products (name) VALUES ('Widget');
EOF

docker run -d \
  --name mariadb \
  -e MARIADB_ROOT_PASSWORD=StrongRootPassword \
  -v mariadb-data:/var/lib/mysql \
  -v $(pwd)/init.sql:/docker-entrypoint-initdb.d/init.sql \
  mariadb:11.8
```

**Важно:** init-скрипты выполняются **только при пустом datadir** (первый запуск). При перезапуске с существующими данными — не выполняются.

### 4. Кастомная конфигурация

```bash
# Через bind-mount конфига
cat > my.cnf <<'EOF'
[mariadb]
innodb_buffer_pool_size = 1G
max_connections = 200
slow_query_log = 1
EOF

docker run -d \
  --name mariadb \
  -e MARIADB_ROOT_PASSWORD=StrongRootPassword \
  -v mariadb-data:/var/lib/mysql \
  -v $(pwd)/my.cnf:/etc/mysql/conf.d/custom.cnf \
  mariadb:11.8

# Или через command (аргументы mariadbd)
docker run -d --name mariadb \
  -e MARIADB_ROOT_PASSWORD=StrongRootPassword \
  mariadb:11.8 \
  --innodb-buffer-pool-size=1G --max-connections=200
```

### 5. Healthcheck

```bash
docker run -d \
  --name mariadb \
  -e MARIADB_ROOT_PASSWORD=StrongRootPassword \
  --health-cmd="mariadb-admin ping -uroot -pStrongRootPassword" \
  --health-interval=30s \
  --health-timeout=10s \
  --health-retries=3 \
  mariadb:11.8

# Проверить статус
docker inspect --format='{{.State.Health.Status}}' mariadb
# → healthy
```

### 6. docker-compose (production-паттерн)

```yaml
# docker-compose.yml
services:
  mariadb:
    image: mariadb:11.8
    container_name: mariadb
    restart: unless-stopped
    environment:
      MARIADB_ROOT_PASSWORD: ${MARIADB_ROOT_PASSWORD}
      MARIADB_DATABASE: shop
      MARIADB_USER: app
      MARIADB_PASSWORD: ${MARIADB_PASSWORD}
    ports:
      - "3306:3306"
    volumes:
      - mariadb-data:/var/lib/mysql
      - ./my.cnf:/etc/mysql/conf.d/custom.cnf:ro
      - ./init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD", "mariadb-admin", "ping", "-uroot", "-p${MARIADB_ROOT_PASSWORD}"]
      interval: 30s
      timeout: 10s
      retries: 3
    # Лимиты (учитывайте при настройке innodb_buffer_pool_size)
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: "2.0"

volumes:
  mariadb-data:
```

```bash
docker compose up -d
docker compose ps
docker compose logs -f mariadb
```

### 7. Резервное копирование контейнера

```bash
# Логический бэкап (dump)
docker exec mariadb mariadb-dump -u root -pStrongRootPassword \
  --all-databases --single-transaction > backup.sql

# Физический бэкап (mariadb-backup)
docker exec mariadb mariadb-backup -u root -pStrongRootPassword \
  --backup --target-dir=/backup

# Копирование volume
docker run --rm \
  -v mariadb-data:/from -v $(pwd):/to \
  alpine tar czf /to/mariadb-data.tar.gz -C /from .
```

## Устранение неполадок (Troubleshooting)

### Контейнер не запускается

*   **Причина:** неверные права на datadir (bind-mount), нехватка памяти, неверный конфиг.
*   **Диагностика:** `docker logs mariadb` — ошибки `mariadbd`; `docker inspect mariadb`.
*   **Решение:** проверьте права на bind-mount (`chown -R 999:999 /host/path`); проверьте `my.cnf`; увеличьте лимиты памяти.

### «Access denied» для root

*   **Причина:** неверный пароль, или root использует `unix_socket` (только localhost).
*   **Диагностика:** `docker exec mariadb mariadb -u root -p...`.
*   **Решение:** используйте `MARIADB_ROOT_PASSWORD`; для root извне — создайте пользователя с хостом `%`.

### Данные теряются при перезапуске

*   **Причина:** нет volume — datadir в ephemeral-слое контейнера.
*   **Решение:** используйте named volume или bind-mount для `/var/lib/mysql`.

### Медленная работа

*   **Причина:** лимиты cgroup (memory/CPU), `innodb_buffer_pool_size` больше лимита контейнера.
*   **Диагностика:** `docker stats mariadb`; `docker inspect` — лимиты.
*   **Решение:** увеличьте лимиты; настройте `innodb_buffer_pool_size` < лимита памяти контейнера.

## Лучшие практики (Best Practices)

1.  **Pin версию:** используйте `mariadb:11.8`, а не `latest`.
2.  **Persistent volume** для `/var/lib/mysql` — обязательно.
3.  **Не используйте `MARIADB_ALLOW_EMPTY_ROOT_PASSWORD`** в production.
4.  **Healthcheck** — для оркестраторов (K8s, compose).
5.  **Лимиты памяти:** `innodb_buffer_pool_size` < лимит cgroup.
6.  **Production:** рассмотрите bare-metal/VM вместо Docker для высоких нагрузок.
7.  **Secrets:** используйте Docker secrets / K8s secrets для паролей, а не `-e PASSWORD=...`.

## Дополнительная информация

### См. также

*   **[Установка и настройка](installation_and_setup.md)** — установка на bare-metal.
*   **[Резервное копирование](backup_and_recovery.md)** — mariadb-dump, mariadb-backup.
*   **[Мониторинг](monitoring.md)** — cgroups и метрики.
*   **[MySQL: Docker](../MySQL/docker.md)** — отличия MySQL-образа.

### Внешние ресурсы

*   [MariaDB Docker Image](https://mariadb.com/kb/en/mariadb-docker-image/)
*   [Official mariadb image (Docker Hub)](https://hub.docker.com/_/mariadb)
*   [docker-library/mariadb (GitHub)](https://github.com/docker-library/mariadb)
*   [MariaDB in Docker](https://mariadb.com/docs/server/getting-started/installing/docker/)
