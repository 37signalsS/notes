# Развертывание PostgreSQL в Docker

## Определения

**postgres** — официальный Docker-образ PostgreSQL, содержащий сервер БД и клиентские утилиты.

**Именованный том (Named Volume)** — управляемый Docker ресурс хранения данных, сохраняющийся после удаления контейнера.

**docker-entrypoint-initdb.d** — специальная директория в образе, где размещаются скрипты инициализации (`.sh`, `.sql`, `.sql.gz`), выполняемые при первом запуске.

## Основные концепции

### Сохранение данных

Данные в контейнере эфемерны и теряются при удалении контейнера (`docker rm`). Для персистентного хранения данных PostgreSQL необходимо монтировать том в директорию `/var/lib/postgresql/data`.

Подробнее о типах томов и их сравнении — **[Docker: Тома и персистентное хранение данных](../../../Docker/Docker_fs/docker_volumes.md)**.

### Сеть и доступ

Для изоляции рекомендуется создавать пользовательские сети Docker. Контейнеры в одной сети обращаются друг к другу по именам сервисов. Порт `5432` пробрасывается на хост только при необходимости внешнего доступа.

### Инициализация

Официальный образ автоматически выполняет скрипты из `/docker-entrypoint-initdb.d` при первом запуске на пустом томе. Скрипты выполняются в алфавитном порядке.

### Безопасность

- **Закрепление версии:** Всегда указывайте конкретную версию образа (например, `postgres:16.3`), избегая тега `latest`.
- **Ограничение доступа:** Не публикуйте порт БД напрямую в интернет. Используйте внутренние сети Docker, VPN или SSH-туннели.
- **Аутентификация:** По умолчанию образ использует метод `trust`. Для production монтируйте `pg_hba.conf` с `scram-sha-256` или `md5`.
- **Непривилегированный запуск:** Образ запускается от пользователя `postgres` (не root).
- **Секреты:** Используйте Docker Secrets или переменные окружения через `.env`-файлы, а не хардкод в `docker-compose.yml`.

Подробнее о безопасности образов — **[Безопасность в Dockerfile](../../../Docker/Dockerfile/Docker_best_practices/security.md)**.

## Практические сценарии

### Сценарий 1: Запуск standalone-сервера

```bash
# 1. (Опционально) Создаем выделенную сеть
docker network create pg-net

# 2. Запускаем контейнер
docker run --name pg-server \
  --network pg-net \
  -e POSTGRES_PASSWORD=mysecretpassword \
  -p 127.0.0.1:5432:5432 \
  -v pg-data:/var/lib/postgresql/data \
  -v ./my_pg_hba.conf:/var/lib/postgresql/data/pg_hba.conf \
  -v ./init-scripts:/docker-entrypoint-initdb.d \
  -d postgres:16.3
```

* `--name pg-server`: Задает имя контейнера для удобства обращения.
* `--network pg-net`: Подключает контейнер к созданной сети.
* `-e POSTGRES_PASSWORD=...`: Устанавливает пароль суперпользователя.
* `-p 127.0.0.1:5432:5432`: Пробрасывает порт контейнера только на `localhost` хоста для безопасности.
* `-v pg-data:/...`: Монтирует именованный том для хранения данных.
* `-v ./my_pg_hba.conf:/...`: Монтирует кастомный файл конфигурации безопасности.
* `-v ./init-scripts:/...`: Монтирует директорию со скриптами инициализации.
* `-d`: Запускает контейнер в фоновом режиме.

### Сценарий 2: Подключение и администрирование

* **Через `docker exec`:**

    ```bash
    docker exec -it pg-server psql -U postgres
    ```

* **С помощью временного клиент-контейнера (рекомендуемый паттерн):**

    ```bash
    docker run --rm -it --network=pg-net postgres:16.3 psql -h pg-server -U postgres
    ```

* **Инспекция контейнера:**

    ```bash
    docker inspect pg-server
    ```

### Сценарий 3: Развертывание стека с Docker Compose

**Пример `docker-compose.yml` для приложения (`app`) и базы данных (`db`):**

```yaml
version: '3.8'

services:
  db:
    image: postgres:16.3
    restart: always
    networks:
      - app-net
    environment:
      - POSTGRES_USER=myuser
      - POSTGRES_PASSWORD=mysecretpassword
      - POSTGRES_DB=myapp
    volumes:
      - db-data:/var/lib/postgresql/data
      - ./init-scripts:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U myuser -d myapp"]
      interval: 10s
      timeout: 5s
      retries: 5

  app:
    build: .
    networks:
      - app-net
    ports:
      - "8080:80"
    depends_on:
      db:
        condition: service_healthy
    environment:
      - DATABASE_URL=postgresql://myuser:mysecretpassword@db:5432/myapp

volumes:
  db-data:

networks:
  app-net:
    driver: bridge
```

* **Взаимодействие:** Сервис `app` обращается к базе данных по имени сервиса `db` и внутреннему порту `5432`.
* **`healthcheck` и `depends_on`:** `depends_on` с условием `service_healthy` гарантирует, что сервис `app` запустится только после готовности PostgreSQL.

## Дополнительная информация

### Расширение стека инструментами мониторинга

Для полноценного мониторинга можно добавить сервисы `postgres-exporter` и `pgbouncer`:

```yaml
  pg_exporter:
    image: prometheuscommunity/postgres-exporter:v0.15.0
    restart: always
    environment:
      DATA_SOURCE_NAME: "postgresql://myuser:mysecretpassword@db:5432/myapp?sslmode=disable"
    networks:
      - app-net
    depends_on:
      - db

  pgbouncer:
    image: edoburu/pgbouncer:1.22.1
    restart: always
    environment:
      DB_HOST: db
      # ... другие переменные для настройки pgbouncer
    ports: ["6432:6432"]
    depends_on:
      - db
```

### Связанные документы

- **Мониторинг:** **[Full-Stack Observability для PostgreSQL](./observability.md)**
- **Резервное копирование:** **[Backup and Recovery](../Concepts/backup_and_recovery.md)**
- **Производительность:** **[Performance Tuning](./performance_tuning.md)**
- **Kubernetes:** **[PostgreSQL в Kubernetes](./kubernetes_deployment.md)**
- **Безопасность Docker:** **[Безопасность в Dockerfile](../../../Docker/Dockerfile/Docker_best_practices/security.md)**
- **Тома Docker:** **[Docker: Тома и персистентное хранение](../../../Docker/Docker_fs/docker_volumes.md)**
