# Dockerfile: Лучшие практики для Go

Примеры демонстрируют многоэтапную сборку, где для компиляции используется полноценный образ, а для выполнения — минималистичный.

## Сборка со `scratch`
Можно запускать собранный бинарный файл в минималистичном образе `FROM scratch` для уменьшения размера и поверхности атаки.

```dockerfile
# --- Этап 1: Сборка бинарного файла (builder) ---
FROM golang:1.25.1-alpine AS builder
RUN apk update && apk add --no-cache git
RUN adduser -D -u 10001 appuser
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
RUN go mod verify
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags "-w -s" -o /app/main .

# --- Этап 2: Финальный образ ---
FROM scratch
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/group /etc/group
COPY --from=builder /app/main /main
USER appuser
EXPOSE 9292
ENTRYPOINT ["/main"]
```

## Сборка с `distroless`
Этот подход является прагматичным выбором для большинства приложений, которым нужны базовые функции ОС (например, работа с DNS, TLS-сертификаты).

```dockerfile
# Этап 1: Сборка
FROM golang:1.25.1-bookworm as builder
WORKDIR /app
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o my-app .

# Этап 2: Создание финального образа
FROM gcr.io/distroless/static-debian12
COPY --from=builder /app/my-app /
CMD ["/my-app"]
```

## Решение проблемы "no such file or directory" в Alpine
При многоэтапной сборке Go, когда на этапе сборки используется `glibc`-образ, а на финальном — `alpine` (`musl libc`), может возникнуть ошибка `no such file or directory` из-за несовместимости библиотек.
**Решение:** Скомпилировать **полностью статически связанный (statically linked)** бинарный файл.
```dockerfile
FROM golang:1.25.1 AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -a -ldflags '-extldflags "-static"' -o /app/main .
FROM alpine:3.22.2
COPY --from=builder /app/main /main
RUN chmod +x /main
ENTRYPOINT ["/main"]
```
