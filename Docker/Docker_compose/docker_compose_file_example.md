# Пример файла compose.yml: Веб-приложение + База данных

## Определения

Файл `compose.yml` является центральным файлом конфигурации для приложений Docker Compose. Этот документ демонстрирует практическое применение директив на классическом примере стека "веб-приложение + база данных".

Все объяснения синтаксиса вынесены в документы, на которые даются ссылки.

## Базовые концепции

### Файл `compose.yml`

```yaml
version: '3.8'
name: my-app

services:
  web:
    build:
      context: .
    image: my-app-web:latest
    ports:
      - "127.0.0.1:8000:8000"
    networks:
      - app-net
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:16-alpine
    networks:
      - app-net
    volumes:
      - db-data:/var/lib/postgresql/data
    secrets:
      - db_password
    env_file:
      - .env
    environment:
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

volumes:
  db-data:

networks:
  app-net:
    driver: bridge

secrets:
  db_password:
    file: ./db_password.txt
```

## Практические сценарии

### Разбор примера

Этот `compose.yml` демонстрирует ключевые практики:

- **Управление зависимостями:** Сервис `web` стартует только после того, как `db` пройдет проверку `healthcheck`. Это реализовано через `depends_on` с условием `service_healthy`. Подробнее: [Справочник по директивам](./docker_compose_directives.md)

- **Управление секретами:** Пароль от базы данных не хранится в открытом виде, а передается через Docker Secrets. Подробнее: [Безопасное управление секретами в Docker](../Docker_security/secrets_management.md)

- **Персистентность данных:** Данные PostgreSQL хранятся в именованном томе `db-data`, что защищает их от потери при пересоздании контейнера. Подробнее: [Docker Volumes](../../Docker/Docker_fs/docker_volumes.md)

- **Сетевая изоляция:** Сервисы `web` и `db` общаются друг с другом по именам в изолированной сети `app-net`.

## Дополнительная информация

### Вспомогательные файлы

##### Файл `.env` (неконфиденциальные данные)

```ini
# .env
# Используется для переменных, которые можно безопасно коммитить в Git
POSTGRES_USER=app_user
POSTGRES_DB=app_db
```

##### Файл `db_password.txt` (секрет)

```
# db_password.txt
super_secret_password_12345
```

> **ВАЖНО:** Обязательно добавьте файл с секретом (в данном случае `db_password.txt`) в ваш `.gitignore`, чтобы он никогда не попал в систему контроля версий.
