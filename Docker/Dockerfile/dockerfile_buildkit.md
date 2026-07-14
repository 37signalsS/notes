# BuildKit: Современный движок сборки Docker

## Определения

**BuildKit** — современный бэкенд для выполнения `docker build`, заменяющий устаревший (legacy) движок сборки. Обеспечивает значительное улучшение производительности, кэширования и безопасности.

В современных версиях Docker (Docker Desktop, Docker Engine v23.0+) BuildKit **включен по умолчанию**.

### Включение BuildKit

Если вы используете старую версию Docker или BuildKit был принудительно отключен, его можно включить следующими способами:

1. **Временный запуск (для текущей сессии):**
   Установите переменную окружения `DOCKER_BUILDKIT` перед командой сборки:
   ```bash
   DOCKER_BUILDKIT=1 docker build -t my-image .
   ```

2. **Постоянное включение (системно):**
   Добавьте параметр в конфигурационный файл демона Docker `/etc/docker/daemon.json`:
   ```json
   {
     "features": {
       "buildkit": true
     }
   }
   ```
   После изменения конфигурации необходимо перезапустить демон Docker:
   ```bash
   sudo systemctl restart docker
   ```

## Базовые концепции

### Ключевые преимущества BuildKit

- **Параллельное выполнение:** Независимые этапы сборки (например, разные ветки `FROM` в многоэтапной сборке) выполняются параллельно, что сокращает общее время сборки.
- **Улучшенное кэширование:** Интеллектуальное определение переиспользуемых слоев и поддержка внешних кэш-бэкендов (например, в реестре образов).
- **Безопасная работа с секретами:** Возможность монтирования секретов во время сборки без их сохранения в истории или слоях итогового образа.
- **Расширяемый синтаксис:** Поддержка новых возможностей через директиву `# syntax`, таких как расширенные типы монтирования (`--mount`).

### Мультиплатформенная сборка

- **Нативная работа:** Позволяет собирать и запускать образы для различных архитектур (ARM64, x86_64, RISC-V) в рамках одного процесса сборки.
- **Эмуляция (QEMU):** Возможность сборки под другие архитектуры через эмуляцию, если нативная поддержка недоступна.
- **Манифесты:** Автоматическое создание `manifest list`, объединяющего образы для разных платформ под одним тегом.

### Автоматические переменные платформы

BuildKit автоматически предоставляет переменные для управления кросс-платформенной сборкой:

- `TARGETPLATFORM` — целевая платформа (например, `linux/amd64` или `linux/arm64`).
- `TARGETOS` и `TARGETARCH` — ОС и архитектура, извлеченные из `TARGETPLATFORM`.
- `BUILDPLATFORM` — платформа, на которой выполняется сборка (хост-система).
- `TARGETVARIANT` — вариант архитектуры (например, `v7` для ARM).

### Директива синтаксиса

Директива `# syntax` в первой строке `Dockerfile` указывает, какой образ-фронтенд использовать для парсинга файла:

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.21
```

Это позволяет использовать новейшие функции сборщика без обновления самого Docker Engine.

## Практические сценарии

### Сценарий 1: Мультиплатформенная сборка (Cross-compilation)

Оптимальный способ сборки — использование `BUILDPLATFORM` для инструментов компиляции и `TARGETARCH` для целевого бинарного файла.

```dockerfile
# syntax=docker/dockerfile:1
# Этап 1: Сборщик. Используем платформу хоста для скорости (нативные инструменты).
FROM --platform=$BUILDPLATFORM golang:1.23-alpine AS builder

ARG TARGETOS TARGETARCH
WORKDIR /app
COPY . .

# Компиляция под целевую архитектуру
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /app/myapp .

# Этап 2: Финальный образ. Используем целевую платформу.
FROM --platform=$TARGETPLATFORM alpine:3.21
RUN apk --no-cache add ca-certificates
COPY --from=builder /app/myapp /usr/local/bin/myapp
USER nobody
CMD ["myapp"]
```

**Запуск сборки для нескольких платформ:**

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t myapp:latest --push .
```

### Сценарий 2: Использование секретов при сборке

Безопасная передача токенов для доступа к приватным репозиториям.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.21

# Секрет монтируется только на время выполнения команды RUN
RUN --mount=type=secret,id=mysecret \
    apk add --no-cache \
    --repository "https://user:$(cat /run/secrets/mysecret)@my.private.repo/apk" \
    my-private-package

# Вне этой команды секрет недоступен
RUN ls /run/secrets  # Директория будет пуста
```

**Передача секрета команде сборки:**

```bash
docker build --secret id=mysecret,src=my_secret.txt .
```

Подробнее см. **[Управление секретами в Docker](../Docker_security/secrets_management.md)**.

### Сценарий 3: Кэширование зависимостей менеджеров пакетов

Использование `--mount=type=cache` позволяет сохранять кэш (например, `pip`, `npm`, `go mod`) между сборками на одном хосте.

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.13-alpine

WORKDIR /app
COPY requirements.txt .

# Кэш pip сохраняется в специальном томе BuildKit и не попадает в образ
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY . .
```

### Сценарий 4: Отладка Dockerfile

Для пошаговой отладки и инспекции процесса сборки рекомендуется использовать специализированные инструменты, такие как **buildg**. См. **[Альтернативные инструменты сборки](../alternative_runtimes_and_tools.md)**.

## Дополнительная информация

- **[Оптимизация сборки образов](./Docker_best_practices/build_optimization.md)** — техники ускорения и уменьшения размера.
- **[Управление секретами в Docker](../Docker_security/secrets_management.md)** — основной документ по безопасности данных.
- **[Инструкции Dockerfile: Выполнение команд](./Instructions/build_time_commands.md)** — подробнее о `--mount`.
- **[Docker Buildx](https://github.com/docker/buildx)** — документация по расширению CLI для мультиплатформенности.
