# Dockerfile: Лучшие практики для Go

## Определения

- **Статически скомпонованный бинарник (Statically Linked Binary):** Исполняемый файл, который содержит в себе все необходимые библиотеки и не зависит от внешних разделяемых библиотек (shared libraries) ОС.
- **BuildKit:** Современный движок сборки Docker, поддерживающий расширенные функции, такие как параллельное выполнение этапов и монтирование кэша.
- **Distroless:** Минималистичные образы (от Google), содержащие только приложение и его рантайм-зависимости, без оболочки (shell) и пакетного менеджера.
- **SBOM (Software Bill of Materials):** Перечень всех компонентов и зависимостей, входящих в состав программного обеспечения.

## Базовые концепции

### Особенности сборки Go (Компилируемый язык)

*   **Тип:** Компилируемый. Превращает исходный код в исполняемый файл под конкретную архитектуру.
*   **Артефакт:** Один статически скомпилированный бинарник (при `CGO_ENABLED=0`).
*   **Multi-stage:** Критически важен. Позволяет использовать образ `scratch` (0 байт) или `distroless` как финальный.
*   **Кэширование BuildKit:** Использование `--mount=type=cache` позволяет сохранять кэш модулей (`GOMODCACHE`) и кэш компилятора между сборками, даже если `go.mod` изменился.

### Воспроизводимые сборки: trimpath

Флаг `-trimpath` удаляет пути к файловой системе сборщика из скомпилированного бинарника. Это важно для безопасности (не раскрывает структуру папок) и обеспечения идентичности хеша бинарника при сборке в разных средах.

### Система модулей: go.mod и go.sum

Файлы `go.mod` и `go.sum` обеспечивают воспроизводимость зависимостей.

*   **`go.mod`**: Основной манифест с версией Go и списком зависимостей.
*   **`go.sum`**: Хеши зависимостей для проверки целостности.

### Управление зависимостями: download vs tidy

| Команда | Использование в Docker | Причина |
| :--- | :--- | :--- |
| **`go mod download`** | **Рекомендуется** | Скачивает зависимости без изменения файлов проекта. |
| **`go mod tidy`** | **Не рекомендуется** | Может изменить `go.mod`/`go.sum`, что недопустимо на этапе сборки. |

### Подход к созданию образов для Go

1. **Этап "builder":** Образ `golang:1.26-alpine` или `bookworm` (содержит SDK).
2. **Этап "final":** Минимальный образ (`scratch`, `distroless`, `alpine`).

### Подводные камни scratch-образов

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **HTTPS запросы** | Нет CA-сертификатов | Копировать `/etc/ssl/certs/ca-certificates.crt` |
| **Часовые пояса** | Нет `tzdata` | Копировать `/usr/share/zoneinfo` |
| **Пользователи** | Нет `/etc/passwd` | Создать пользователя в builder и скопировать файл |
| **CGO / SQLite** | Динамическая линковка | `CGO_ENABLED=0` или полная статическая линковка |

## Практические сценарии

### Сценарий 1: Оптимальная сборка с кэшированием (BuildKit)

Использование монтирования кэша значительно ускоряет повторные сборки в CI/CD.

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.26-alpine AS builder

# Устанавливаем необходимые системные зависимости
RUN apk add --no-cache ca-certificates tzdata

# Создаем пользователя для безопасности
RUN adduser -D -S -u 10001 appuser

WORKDIR /app

# Копируем файлы зависимостей
COPY go.mod go.sum ./

# Кэшируем загруженные модули
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

# Копируем исходный код
COPY . .

# Собираем бинарник с использованием кэша компилятора и флага -trimpath
RUN --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux go build \
    -trimpath \
    -ldflags "-w -s" \
    -o /app/main .

# --- Финальный этап ---
FROM scratch

COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo
COPY --from=builder /app/main /main

USER appuser
EXPOSE 8080
ENTRYPOINT ["/main"]
```

### Сценарий 2: Мультиплатформенная сборка (Cross-compilation)

Использование встроенных переменных BuildKit для сборки под разные архитектуры (AMD64, ARM64).

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.26-alpine AS builder

# TARGETOS и TARGETARCH заполняются Docker автоматически
ARG TARGETOS TARGETARCH

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .

# Кросс-компиляция под целевую платформу
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -trimpath -ldflags "-w -s" -o /app/main .

FROM gcr.io/distroless/static-debian12
COPY --from=builder /app/main /
ENTRYPOINT ["/main"]
```
**Команда запуска:** `docker buildx build --platform linux/amd64,linux/arm64 -t app:latest .`

### Сценарий 3: Сборка с поддержкой CGO (Alpine)

Используется для библиотек, требующих C (например, `go-sqlite3`).

```dockerfile
FROM golang:1.26-alpine AS builder
RUN apk add --no-cache gcc musl-dev
WORKDIR /app
COPY . .
# Включаем CGO и принудительно пересобираем для чистоты
RUN CGO_ENABLED=1 go build -a -ldflags "-w -s" -o main .

FROM alpine:3.24
RUN apk add --no-cache ca-certificates tzdata
COPY --from=builder /app/main /main
ENTRYPOINT ["/main"]
```

### Сценарий 4: Безопасное завершение (Signal Handling)

Go-приложения должны корректно обрабатывать сигналы завершения. Docker отправляет `SIGTERM`.

1. **В коде:** Обрабатывайте `os.Interrupt` и `syscall.SIGTERM`.
2. **В Dockerfile:** Используйте `ENTRYPOINT` в формате JSON (`["/main"]`), чтобы приложение было PID 1 и получало сигналы напрямую.
3. **STOPSIGNAL:** По умолчанию `SIGTERM`, но можно изменить.

```dockerfile
# ... этапы сборки ...
FROM scratch
COPY --from=builder /app/main /main
# Явное указание сигнала завершения (опционально)
STOPSIGNAL SIGTERM
ENTRYPOINT ["/main"]
```

### Верификация бинарника

```bash
# Проверка статической линковки
ldd ./main 
# → not a dynamic executable

# Проверка на уязвимости (govulncheck)
# Требуется установленный Go
govulncheck ./...
```

## Дополнительная информация

### Управление уязвимостями

Рекомендуется использовать `govulncheck` (официальный инструмент Go) для анализа зависимостей на наличие известных уязвимостей непосредственно перед сборкой образа.

### Смотрите также

- [Оптимизация сборки Docker-образов](./build_optimization.md)
- [Безопасность в Dockerfile](./security.md)
- [Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md)
- [Проблема несовместимости libc (Alpine)](../../Docker_troubleshooting/alpine_glibc_compatibility.md)
