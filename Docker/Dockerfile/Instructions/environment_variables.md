# Инструкции Dockerfile: Переменные Окружения и Аргументы

## Определения

**`ARG` (Argument)** — переменная времени сборки, доступная только в процессе `docker build`. Не сохраняется в конечном образе.

**`ENV` (Environment)** — переменная окружения, доступная как при сборке, так и во время выполнения контейнера. Сохраняется в образе.

## Основные концепции

### Синтаксис

**ENV:**

```dockerfile
# Форма 1: несколько переменных в одной инструкции (рекомендуется)
ENV <key>=<value> [<key>=<value>...]

# Форма 2: альтернативный синтаксис (не рекомендуется)
ENV <key> <value>
```

**Примеры:**

```dockerfile
ENV MY_NAME="John Doe"
ENV MY_DOG=Rex\ The\ Dog
ENV DB_HOST=localhost DB_PORT=5432
```

**ARG:**

```dockerfile
ARG <name>[=<default value>] [<name>[=<default value>]...]
```

**Примеры:**

```dockerfile
ARG APP_VERSION=1.0
ARG user1
ARG buildno=1
```

### Сравнение ENV и ARG

| Характеристика | ENV | ARG |
| :--- | :--- | :--- |
| **Сохранение в образе** | Да | Нет |
| **Доступность в контейнере** | Да | Нет |
| **Видимость в `docker history`** | Да | Нет (кроме predefined) |
| **Передача через CLI** | `docker run --env` | `docker build --build-arg` |
| **Область действия** | От объявления до конца Dockerfile | От объявления до конца стадии |

### Переопределение значений

**ARG при сборке:**

```bash
docker build --build-arg APP_VERSION=2.1 .
```

**ENV при запуске:**

```bash
docker run -e DB_HOST=db.example.com my-image
```

### Совместное использование ARG и ENV

Часто `ARG` используют для установки значения `ENV` по умолчанию:

```dockerfile
ARG APP_PORT=8080
ENV PORT=${APP_PORT}
EXPOSE ${PORT}
```

> **Важно:** ENV всегда переопределяет ARG с тем же именем после точки объявления ENV.

### Область видимости ARG по стадиям

```dockerfile
FROM busybox
USER ${username:-some_user}  # some_user (ARG ещё не объявлен)
ARG username
USER $username               # значение из --build-arg

FROM ubuntu
# ARG username здесь недоступен — нужно объявить заново
ARG username
USER $username
```

**Правило:** ARG действует только с строки объявления. Для использования в нескольких стадиях объявляйте в каждой стадии.

### Предопределённые ARG

Docker предоставляет встроенные переменные (не требуют объявления `ARG`):

| Переменная | Описание |
| :--- | :--- |
| `HTTP_PROXY` / `http_proxy` | Прокси для HTTP-запросов |
| `HTTPS_PROXY` / `https_proxy` | Прокси для HTTPS-запросов |
| `FTP_PROXY` / `ftp_proxy` | Прокси для FTP-запросов |
| `NO_PROXY` / `no_proxy` | Исключения для прокси |
| `ALL_PROXY` / `all_proxy` | Универсальный прокси |

**Примечание:** По умолчанию исключены из `docker history` для безопасности.

### Автоматические платформенные ARG (BuildKit)

| Переменная | Описание |
| :--- | :--- |
| `TARGETPLATFORM` | Платформа результата сборки (например, `linux/amd64`) |
| `BUILDPLATFORM` | Платформа узла сборки |
| `TARGETOS` | ОС целевой платформы |
| `TARGETARCH` | Архитектура целевой платформы |
| `TARGETVARIANT` | Вариант архитектуры (например, `v7`) |

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine
ARG TARGETPLATFORM
RUN echo "Building for ${TARGETPLATFORM}"
```

### Полезные ENV для Python

| Переменная | Описание |
| :--- | :--- |
| `PYTHONUNBUFFERED=1` | Отключает буферизацию вывода (логи сразу в STDOUT) |
| `PYTHONDONTWRITEBYTECODE=1` | Не создаёт `.pyc` файлы |
| `PIP_NO_CACHE_DIR=1` | Не кэширует пакеты pip (уменьшает размер образа) |

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

> ⚠️ **Не используйте `ARG` для секретов** — значения видны в `docker history` и provenance-аттестациях.

Используйте `--mount=type=secret` (BuildKit):

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine
RUN --mount=type=secret,id=npm_token \
    NPM_TOKEN=$(cat /run/secrets/npm_token) && \
    echo "//registry.npmjs.org/:_authToken=${NPM_TOKEN}" > .npmrc
```

**Сборка:**

```bash
docker buildx build --secret id=npm_token,src=$HOME/.npmrc .
```

### Сценарий 3: Монтаж секрета как переменной окружения

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine
RUN --mount=type=secret,id=API_KEY,env=API_KEY \
    some-command --token-from-env $API_KEY
```

**Сборка:**

```bash
docker buildx build --secret id=API_KEY .
```

### Сценарий 4: Конфигурация приложения через ENV

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

### Сценарий 5: Временные переменные для apt-get

```dockerfile
# Вариант 1: inline в RUN
RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y curl

# Вариант 2: ARG (не сохраняется в образе)
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y curl
```

## Дополнительная информация

Для секретов в runtime используйте **[Docker Secrets](../../Docker_security/secrets_management.md)** или внешние хранилища (Vault). Переменные окружения можно переопределить при запуске через `docker run -e VAR=value`. Подробнее о многоэтапной сборке см. **[Оптимизация сборки](../Docker_best_practices/build_optimization.md)**.
