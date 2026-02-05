# Развертывание PostgreSQL в Docker

## Основные концепции

### Сохранение данных (Volumes)

**Критически важно:** Данные внутри контейнера эфемерны и теряются при его удалении (`docker rm`). Для надежного хранения данных PostgreSQL **всегда используйте тома (volumes)**, монтируя их в директорию `/var/lib/postgresql/data`.

```bash
# Пример монтирования именованного тома
-v pg-data:/var/lib/postgresql/data 
```

### Сеть и доступ к базе данных

Для изоляции и удобства обращения по именам рекомендуется создавать пользовательские сети Docker. Контейнеры в одной сети могут обращаться друг к другу по именам сервисов. Для внешнего доступа порт `5432` контейнера необходимо "пробросить" на хост-машину.

### Инициализация базы данных

Официальный образ PostgreSQL автоматически выполняет SQL- и shell-скрипты из директории `/docker-entrypoint-initdb.d` при первом запуске контейнера. Это стандартный способ для первоначального создания пользователей, баз данных и схем.

### Безопасность

* **Доверенные образы:** Используйте **только официальные образы** (`postgres`) или образы из доверенного внутреннего registry. **Всегда закрепляйте версию** (например, `postgres:16.3`), избегая тега `latest`.
* **Сетевой доступ:** **Никогда не публикуйте порт базы данных напрямую в интернет**. Доступ должен быть ограничен внутренней сетью Docker, либо осуществляться через VPN, SSH-туннели или прокси (PgBouncer).
* **Аутентификация:** По умолчанию официальный образ использует метод аутентификации `trust`, позволяя подключаться без пароля. **Для production это необходимо исправить**, смонтировав собственный `pg_hba.conf` с более строгими правилами (`md5` или `scram-sha-256`).
* **Принцип наименьших привилегий:** Официальный образ `postgres` уже следует лучшей практике, запуская процесс от имени непривилегированного пользователя `postgres`.
* **Управление конфигурацией:** Конфигурационные файлы следует монтировать в контейнер как тома или использовать Docker Secrets/Configs, а **не встраивать их в образ**.

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
* **`healthcheck` и `depends_on`:** `depends_on` с условием `service_healthy` гарантирует, что сервис `app` запустится только после того, как PostgreSQL будет готов принимать соединения.

## Дополнительная информация

### Расширение стека дополнительными инструментами

Для полноценного мониторинга и управления можно добавить в `docker-compose.yml` сервисы Prometheus, Grafana, PgAdmin и PgBouncer, объединив их в общую сеть.

**Пример сервиса для `postgres-exporter`:**

```yaml
  pg_exporter:
    image: prometheuscommunity/postgres-exporter:v0.15.0
    restart: always
    environment:
      DATA_SOURCE_NAME: "postgresql://myuser:mysecretpassword@db:5432/myapp?sslmode=disable"
    networks:
      - app-net # или отдельная сеть мониторинга
    depends_on:
      - db
```

**Пример сервиса для `pgbouncer`:**

```yaml
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
