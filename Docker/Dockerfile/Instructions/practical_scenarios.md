# Инструкции Dockerfile: Практические Сценарии

## Определения

**Приоритет команд при запуске контейнера** — порядок, в котором `docker run` и `docker-compose.yml` переопределяют инструкции из `Dockerfile`.

## Основные концепции

### Золотое правило переопределения

`docker-compose.yml` (или `docker run`) всегда имеет приоритет над `Dockerfile`:

1. `command:` в `compose.yml` (или аргументы в `docker run`) **заменяет** `CMD` из `Dockerfile`
2. `entrypoint:` в `compose.yml` (или `--entrypoint` в `docker run`) **заменяет** `ENTRYPOINT` из `Dockerfile`

### Таблица переопределения

| Источник | ENTRYPOINT | CMD |
| :--- | :--- | :--- |
| Dockerfile | `ENTRYPOINT ["/app/run"]` | `CMD ["--default"]` |
| docker-compose.yml / docker run | `entrypoint: /app/debug` | `command: --prod` |
| **Результат** | Переопределяется | Переопределяется |

### Базовое взаимодействие ENTRYPOINT и CMD

| В Dockerfile | В docker-compose / docker run | Итоговая команда |
| :--- | :--- | :--- |
| `ENTRYPOINT ["/app/run"]`<br>`CMD ["--default"]` | (ничего) | `/app/run --default` |
| `ENTRYPOINT ["/app/run"]`<br>`CMD ["--default"]` | `command: --prod` | `/app/run --prod` |
| `ENTRYPOINT ["/app/run"]` | `entrypoint: /app/debug` | `/app/debug` |
| `ENTRYPOINT ["/app/run"]`<br>`CMD ["--default"]` | `entrypoint: /app/debug`<br>`command: --verbose` | `/app/debug --verbose` |

## Практические сценарии

### Сценарий 1: Переопределение CMD для ping

**Dockerfile:**

```dockerfile
FROM alpine:3.20.0
ENTRYPOINT ["ping", "-c", "3"]
CMD ["localhost"]
```

По умолчанию: `ping -c 3 localhost`

**docker-compose.yml:**

```yaml
services:
  pinger:
    build: .
    command: google.com
```

**Результат:** `ping -c 3 google.com`

### Сценарий 2: Отладка с переопределением ENTRYPOINT

**docker-compose.yml:**

```yaml
services:
  app:
    build: .
    entrypoint: /bin/sh
    command: -c "echo debug && tail -f /dev/null"
```

**docker run эквивалент:**

```bash
docker run --entrypoint /bin/sh my-image -c "echo debug && tail -f /dev/null"
```

### Сценарий 3: Запуск тестов с переопределением CMD

**Dockerfile:**

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY . .
RUN npm install
CMD ["node", "server.js"]
```

**Запуск тестов:**

```bash
docker run my-image npm test
```

**Результат:** Вместо `node server.js` выполнится `npm test`

### Сценарий 4: Переопределение ENV переменных

**Dockerfile:**

```dockerfile
FROM python:3.11-slim
ENV APP_ENV=production
ENV LOG_LEVEL=info
CMD ["python", "app.py"]
```

**docker-compose.yml:**

```yaml
services:
  app:
    build: .
    environment:
      - APP_ENV=development
      - LOG_LEVEL=debug
```

**Результат:** Приложение запустится с `APP_ENV=development` и `LOG_LEVEL=debug`

### Сценарий 5: Переопределение WORKDIR

**Dockerfile:**

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY . .
CMD ["node", "index.js"]
```

**docker run с переопределением:**

```bash
docker run -w /app/scripts my-image node script.js
```

**Результат:** Контейнер запустится из `/app/scripts` с командой `node script.js`

### Сценарий 6: Переопределение USER

**Dockerfile:**

```dockerfile
FROM ubuntu
RUN useradd -m appuser
USER appuser
CMD ["/bin/bash"]
```

**docker run от root:**

```bash
docker run -u root my-image
```

**Результат:** Контейнер запустится от `root`, а не от `appuser`

### Сценарий 7: Комбинированное переопределение в CI/CD

**Dockerfile:**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```

**compose.test.yml:**

```yaml
services:
  test:
    build: .
    entrypoint: pytest
    command: tests/
    environment:
      - DJANGO_SETTINGS_MODULE=config.test
    volumes:
      - ./tests:/app/tests
```

**Результат:** Запуск тестов вместо development-сервера

### Сценарий 8: Override-файл для локальной разработки

**compose.yml:**

```yaml
services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DEBUG=false
```

**compose.override.yml:**

```yaml
services:
  web:
    environment:
      - DEBUG=true
    volumes:
      - .:/app
    command: python manage.py runserver 0.0.0.0:8000
```

**Результат:** При запуске `docker compose up` автоматически применится override-файл с настройками для разработки.

## Дополнительная информация

Подробнее о формах записи (shell vs exec) см. **[Выполнение при запуске](./runtime_execution.md)**. О конфигурации Docker Compose читайте в **[Docker Compose file example](../../Docker_compose/docker_compose_file_example.md)** и **[Docker Compose directives](../../Docker_compose/docker_compose_directives.md)**.
