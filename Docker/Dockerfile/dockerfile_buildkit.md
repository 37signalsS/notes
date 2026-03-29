# BuildKit: Движок сборки Docker

## Определения

**BuildKit** — современный бэкенд для выполнения `docker build`, заменяющий legacy-движок сборки. Обеспечивает улучшения в производительности, кэшировании и безопасности.

В современных версиях Docker (Docker Desktop, Docker Engine v23.0+) BuildKit **включен по умолчанию**.

## Основные концепции

### Ключевые преимущества BuildKit

- **Параллельное выполнение:** Независимые этапы сборки (например, разные ветки `FROM` в многоэтапной сборке) выполняются параллельно.
- **Улучшенное кэширование:** Интеллектуальное определение переиспользуемых слоев ускоряет повторные сборки.
- **Безопасная работа с секретами:** Монтирование секретов во время сборки без сохранения в истории или слоях образа.
- **Расширяемый синтаксис:** Новые возможности в `Dockerfile`, например `RUN --mount=type=cache`.

### Мультиплатформенная сборка

- **Нативная работа:** Запуск образов на различных архитектурах (Apple M1/M2, x86_64, AWS Graviton) без эмуляции.
- **Оптимальная производительность:** Использование нативных сборок для каждой архитектуры.
- **Широкая поддержка:** Создание образов для IoT и Edge-устройств.
- **Унификация:** Единый тег образа для всей инфраструктуры.

### Переменные BuildKit для кросс-платформенной сборки

- `TARGETPLATFORM` — целевая платформа, указанная в `--platform` (например, `linux/amd64`).
- `TARGETOS` и `TARGETARCH` — ОС и архитектура, извлеченные из `TARGETPLATFORM`.
- `BUILDPLATFORM` — платформа, на которой выполняется сборка.
- `TARGETVARIANT` — вариант архитектуры (например, `v7` для ARM).

### Директива синтаксиса

Директива `# syntax` в первой строке `Dockerfile` указывает образ-интерпретатор:

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine
```

Это позволяет использовать альтернативные фронтенды для сборки.

## Практические сценарии

### Сценарий 1: Мультиплатформенная сборка

BuildKit позволяет создавать образы для нескольких архитектур из одного `Dockerfile`.

**Сборка для конкретной платформы:**

```bash
# AMD64 (классические серверы)
docker build --platform linux/amd64 -t myapp:latest .

# ARM64 (Apple M1/M2, AWS Graviton)
docker build --platform linux/arm64 -t myapp:latest .
```

**Адаптивный Dockerfile:**

```dockerfile
# syntax=docker/dockerfile:1
# Этап 1: Сборщик. Используем платформу хоста ($BUILDPLATFORM) для скорости.
FROM --platform=$BUILDPLATFORM golang:1.23-alpine AS builder

ARG TARGETOS TARGETARCH
WORKDIR /app
COPY . .

# Компиляция под целевую архитектуру ($TARGETARCH)
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /app/myapp .

# Этап 2: Финальный образ. Обязательно используем целевую платформу.
FROM --platform=$TARGETPLATFORM alpine:3.21
RUN apk --no-cache add ca-certificates
COPY --from=builder /app/myapp /usr/local/bin/myapp
USER nobody
CMD ["myapp"]
```

**Проверка архитектуры:**

```bash
docker inspect myapp:latest | grep Architecture
# "Architecture": "amd64"
```

### Сценарий 2: Build-time секреты

BuildKit позволяет безопасно использовать секреты (токены, пароли) во время сборки без сохранения в слоях образа.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.21

# Секрет монтируется только на время выполнения команды
RUN --mount=type=secret,id=mysecret \
    apk add --no-cache \
    --repository "https://user:$(cat /run/secrets/mysecret)@my.private.repo/apk" \
    my-private-package

# Вне этой команды секрет недоступен
RUN ls /run/secrets  # Директория будет пуста
```

**Запуск сборки с секретом:**

```bash
# my_secret.txt содержит токен
docker build --secret id=mysecret,src=my_secret.txt .
```

Подробное описание: **[Управление секретами в Docker](../Docker_security/secrets_management.md)**.

### Сценарий 3: Кэширование зависимостей

`--mount=type=cache` ускоряет повторные сборки за счет сохранения кэша между запусками.

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.13-alpine

# Кэш pip сохраняется между сборками, но не попадает в финальный образ
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```

Подробнее: **[Оптимизация сборки](./Docker_best_practices/build_optimization.md)**.

### Сценарий 4: Интерактивная отладка

Для пошаговой отладки `Dockerfile` используйте инструмент **[buildg](../alternative_runtimes_and_tools.md)**.

### Альтернативные фронтенды

Директива `# syntax` позволяет использовать альтернативные парсеры для интерпретации `Dockerfile`.

**Примеры фронтендов:**

- **Mocker** (`# syntax=github.com/moby/mocker/dockerfile-frontend:v0.1.0`) — описание сборки в формате YAML.
- **Buildpacks** (`# syntax=paketobuildpacks/builder:base`) — автоматическая сборка на основе структуры приложения.

## Дополнительная информация

- **[Docker Buildx](https://github.com/docker/buildx)** — CLI-плагин для расширенной мультиплатформенной сборки
- **[Управление секретами](../Docker_security/secrets_management.md)** — безопасное использование секретов
- **[Оптимизация сборки](./Docker_best_practices/build_optimization.md)** — техники оптимизации
- **[Buildg](../alternative_runtimes_and_tools.md)** — интерактивная отладка Dockerfile
