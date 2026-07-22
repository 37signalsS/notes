# Развертывание PostgreSQL в Docker

## Определения

**postgres** — официальный Docker-образ PostgreSQL, включающий сервер СУБД, клиентские утилиты и набор скриптов для автоматизации инициализации.

**Именованный том (Named Volume)** — механизм Docker для персистентного хранения данных, обеспечивающий изоляцию файловой системы БД от жизненного цикла контейнера.

**docker-entrypoint-initdb.d** — точка расширения в образе, предназначенная для автоматического выполнения SQL или Bash скриптов при первом создании базы данных.

## Основные концепции

### Управление данными и правами

PostgreSQL в Docker работает под пользователем `postgres` (стандартный UID 999, GID 999). 

- **Персистентность:** Всегда монтируйте том в директорию, указанную в `PGDATA` (рекомендуется `/var/lib/postgresql/data/pgdata`).
- **Права доступа:** При использовании bind mounts (монтирование папки с хоста) убедитесь, что директория на хосте принадлежит пользователю с UID 999. В некоторых дистрибутивах или облачных конфигурациях (например, Selectel) может потребоваться явное указание `USERMAP_UID` и `USERMAP_GID` в переменных окружения для корректного маппинга прав, если это поддерживается используемым образом.
- **Подробнее о томах:** [Docker: Тома и персистентное хранение](../../../Docker/Docker_fs/docker_volumes.md).

### Тюнинг ресурсов и памяти

Для работы PostgreSQL требуется установленный Docker Engine. См. [Установка Docker на Ubuntu](../../../Docker/docker_install_ubuntu.md).

В контейнеризированной среде PostgreSQL не видит реальных ограничений cgroups без дополнительной настройки.

- **shared_buffers:** Рекомендуется устанавливать на уровне 25% от лимита памяти контейнера (через команду запуска или конфиг).
- **huge_pages:** По умолчанию в контейнерах `try`. Для полноценной работы может потребоваться увеличение `shm_size` в Docker и настройка параметров ядра на хосте.
- **Лимиты:** Всегда устанавливайте `deploy.resources.limits` в Docker Compose для предотвращения OOM Killer.

### Инициализация и логирование

- **Init-скрипты:** Выполняются строго один раз при пустом `PGDATA`. Поддерживают `.sql`, `.sql.gz` и `.sh`.
- **Логи:** Официальный образ направляет логи в `stdout`/`stderr`. Это позволяет собирать их стандартными средствами Docker (например, `docker logs`) или внешними драйверами (Loki, Fluentd).
- **Формат логов:** Для удобства парсинга рекомендуется изменить формат логов на CSV или JSON (требует правок в `postgresql.conf`).

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

### Сценарий 3: Администрирование и бэкапы

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

## Дополнительная информация

### Безопасность

1. **Образы:** Используйте `alpine` версии для минимизации поверхности атаки.
2. **Сеть:** Никогда не публикуйте порт `5432` на `0.0.0.0` без SSL и строгих правил в `pg_hba.conf`.
3. **Обновления:** Для минорных версий (например, 16.2 -> 16.3) достаточно сменить тег образа и перезапустить контейнер. Мажорные версии требуют миграции данных (`pg_upgrade`).

### Связанные документы

- [Наблюдаемость PostgreSQL](./observability.md) — сбор метрик и трейсов в Docker.
- [Оптимизация производительности](./performance_tuning.md) — детальный тюнинг параметров СУБД.
- [PostgreSQL в Kubernetes](./kubernetes_deployment.md) — масштабирование и High Availability.
- [Безопасность в Dockerfile](../../../Docker/Dockerfile/Docker_best_practices/security.md) — общие практики защиты контейнеров.
