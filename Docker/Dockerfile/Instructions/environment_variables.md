# Инструкции Dockerfile: Переменные Окружения и Аргументы

## Определения

**`ARG` (Argument)** — переменная времени сборки, доступная только в процессе `docker build`. Не сохраняется в конечном образе.

**`ENV` (Environment)** — переменная окружения, доступная как при сборке, так и во время выполнения контейнера. Сохраняется в образе.

## Основные концепции

### `ARG`

- Доступна **только** в процессе сборки образа (`docker build`)
- Не сохраняется в конечном образе
- Используется для параметризации сборки: версии пакетов, токены для доступа к приватным репозиториям

**Синтаксис:**

```dockerfile
ARG APP_VERSION=1.0
RUN echo "Собирается версия: $APP_VERSION"
```

**Переопределение при сборке:**

```bash
docker build --build-arg APP_VERSION=2.1 .
```

> **Безопасность:** Не используйте `ARG` для секретов в production. Значения `ARG` видны в истории образа через `docker history`.

### `ENV`

- Устанавливает переменные окружения, доступные как при сборке, так и в запущенном контейторе
- Сохраняется в образе и доступно через `docker inspect`
- Используется для конфигурации приложения: URL БД, порты, пути

**Синтаксис:**

```dockerfile
ENV DB_HOST=localhost
ENV DB_PORT=5432
CMD ["echo", "Подключение к $DB_HOST:$DB_PORT"]
```

**Переопределение при запуске:**

```bash
docker run -e DB_HOST=db.example.com my-image
```

### Совместное использование `ARG` и `ENV`

Часто `ARG` используют для установки значения `ENV` по умолчанию:

```dockerfile
ARG APP_PORT=8080
ENV PORT=${APP_PORT}
EXPOSE ${PORT}
```

### `ENV PYTHONUNBUFFERED=1`

Для Python-приложений. По умолчанию Python буферизирует потоки `stdout` и `stderr`. Установка `ENV PYTHONUNBUFFERED=1` отключает буферизацию, и вывод сразу направляется в логи контейнера.

## Практические сценарии

### Сценарий 1: Параметризация версии приложения

```dockerfile
ARG NODE_VERSION=20-alpine
FROM node:${NODE_VERSION}
ARG APP_VERSION=1.0.0
ENV APP_VERSION=${APP_VERSION}
LABEL version="${APP_VERSION}"
```

### Сценарий 2: Безопасная передача секретов на этапе сборки

> Для секретов используйте `--mount=type=secret` (BuildKit), а не `ARG`

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine
RUN --mount=type=secret,id=npm_token \
    NPM_TOKEN=$(cat /run/secrets/npm_token) && \
    echo "//registry.npmjs.org/:_authToken=${NPM_TOKEN}" > .npmrc
```

### Сценарий 3: Конфигурация приложения через ENV

```dockerfile
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
CMD ["python", "app.py"]
```

## Дополнительная информация

- Не используйте `ENV` для секретов в production — применяйте **[Docker Secrets](../../Docker_security/secrets_management.md)** или внешние хранилища (Vault)
- Подробнее о безопасном управлении secrets см. **[Управление секретами](../../Docker_security/secrets_management.md)**
- Переменные окружения можно переопределить при запуске: `docker run -e VAR=value`
- Полезные переменные для Python: `PYTHONUNBUFFERED`, `PYTHONDONTWRITEBYTECODE`, `PYTHONPATH`
