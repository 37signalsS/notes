# Развертывание PostgreSQL в Docker

## Определения

**postgres** — официальный Docker-образ PostgreSQL, содержащий сервер БД и клиентские утилиты.

**Именованный том (Named Volume)** — управляемый Docker ресурс хранения данных, сохраняющийся после удаления контейнера.

**docker-entrypoint-initdb.d** — специальная директория в образе, где размещаются скрипты инициализации (`.sh`, `.sql`, `.sql.gz`), выполняемые при первом запуске на пустом томе.

## Основные концепции

### Сохранение данных

Данные в контейнере эфемерны. Для персистентного хранения необходимо монтировать том в директорию, указанную в переменной `PGDATA` (по умолчанию `/var/lib/postgresql/data`).

- **Рекомендация:** Использовать поддиректорию внутри тома для избежания конфликтов с системными файлами (например, `PGDATA=/var/lib/postgresql/data/pgdata`).
- **Тома:** Сравнение типов томов приведено в **[Docker: Тома и персистентное хранение данных](../../../Docker/Docker_fs/docker_volumes.md)**.

### Сеть и доступ

Для изоляции рекомендуется создавать пользовательские сети Docker (User-defined bridge networks).

- Контейнеры в одной сети обращаются друг к другу по именам сервисов.
- Порт `5432` следует пробрасывать на хост (`-p`) только при необходимости внешнего доступа (например, для GUI-клиентов).
- В production рекомендуется ограничить доступ через `127.0.0.1:5432:5432`.

### Инициализация (Init Scripts)

Официальный образ автоматически выполняет скрипты из `/docker-entrypoint-initdb.d` при **первом** запуске.

- Скрипты выполняются в алфавитном порядке.
- Поддерживаются форматы: `.sh`, `.sql`, `.sql.gz`.
- Если директория данных (`PGDATA`) уже содержит базу, скрипты проигнорируются.

### Безопасность

- **Закрепление версии:** Всегда указывайте конкретный тег (например, `postgres:16.3-alpine`), избегая `latest`.
- **Секреты:** Используйте `POSTGRES_PASSWORD_FILE` вместо `POSTGRES_PASSWORD` для передачи пароля через Docker Secrets или примонтированные файлы.
- **Аутентификация:** По умолчанию используется метод `trust` (для локальных подключений). Для сетевых подключений настройте `scram-sha-256` в `pg_hba.conf`.
- **Hardening:** Общие принципы защиты СУБД описаны в **[Безопасная установка СУБД](../../installation_security.md)**.
- **Docker Security:** Практики защиты контейнеров — **[Безопасность в Dockerfile](../../../Docker/Dockerfile/Docker_best_practices/security.md)**.

## Практические сценарии

### Сценарий 1: Запуск standalone-сервера (CLI)

```bash
# 1. Создаем выделенную сеть
docker network create pg-net

# 2. Запускаем контейнер с примонтированным конфигом и инициализацией
docker run --name pg-server \
  --network pg-net \
  -e POSTGRES_PASSWORD=mysecretpassword \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -p 127.0.0.1:5432:5432 \
  -v pg-data:/var/lib/postgresql/data \
  -v ./my_pg_hba.conf:/var/lib/postgresql/data/pgdata/pg_hba.conf \
  -v ./init-scripts:/docker-entrypoint-initdb.d \
  -d postgres:16.3-alpine
```

### Сценарий 2: Развертывание через Docker Compose (Best Practice)

Пример конфигурации с проверкой здоровья (`healthcheck`) и ограничением ресурсов:

```yaml
services:
  db:
    image: postgres:16.3-alpine
    container_name: postgres_prod
    restart: always
    environment:
      - POSTGRES_USER=app_user
      - POSTGRES_DB=app_db
      # Использование файла для секрета
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
      - PGDATA=/var/lib/postgresql/data/pgdata
    volumes:
      - db_data:/var/lib/postgresql/data
      - ./init-scripts:/docker-entrypoint-initdb.d:ro
    secrets:
      - db_password
    deploy:
      resources:
        limits:
          memory: 1gb
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app_user -d app_db"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - backend

secrets:
  db_password:
    file: ./db_password.txt

volumes:
  db_data:

networks:
  backend:
    driver: bridge
```

### Сценарий 3: Администрирование в Docker

- **Выполнение команд в контейнере:**

  ```bash
  docker exec -it pg-server psql -U postgres
  ```

- **Создание бэкапа (Logical Dump):**

  ```bash
  docker exec pg-server pg_dumpall -U postgres > full_backup.sql
  ```

- **Восстановление из дампа:**

  ```bash
  cat backup.sql | docker exec -i pg-server psql -U postgres
  ```

## Дополнительная информация

### Расширение стека (Sidecars)

Для полноценной эксплуатации часто добавляются дополнительные компоненты:

- **[Full-Stack Observability](./observability.md)** — использование `postgres-exporter` для сбора метрик.
- **PgBouncer** — пул соединений для высоконагруженных систем.
- **Adminer / pgAdmin** — веб-интерфейсы для управления.

### Связанные документы

- **Резервное копирование:** **[Backup and Recovery](../Concepts/backup_and_recovery.md)**
- **Производительность:** **[Performance Tuning](./performance_tuning.md)**
- **Kubernetes:** **[PostgreSQL в Kubernetes](./kubernetes_deployment.md)**
- **Тома Docker:** **[Docker: Тома и персистентное хранение](../../../Docker/Docker_fs/docker_volumes.md)**
