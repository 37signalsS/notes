# Совместимость с Glibc в Alpine Linux

## Определения

**Проблема несовместимости libc** — ситуация, когда бинарный файл, скомпилированный для одной реализации стандартной библиотеки C, не работает в системе с другой реализацией. Типичный случай — ошибка `file not found` или `error while loading shared libraries` при запуске в Alpine Linux приложения, собранного в Ubuntu/Debian.

Подробное сравнение библиотек: **[Сравнение Glibc и Musl](../../Linux/Core/glibc_vs_musl.md)**.

## Основные концепции

### Причина ошибки

Alpine Linux использует **`musl libc`** вместо стандартной **`glibc`**. Бинарные файлы, скомпилированные с `glibc`, содержат зависимости от её символов и не могут выполняться в среде `musl` без специальных мер.

### Диагностика

```bash
# Проверка зависимостей бинарного файла
ldd ./myapp
# Ошибка: "not a dynamic executable" или ссылки на libc.so.6

# Проверка интерпретера
readelf -l ./myapp | grep interpreter
# glibc: /lib64/ld-linux-x86-64.so.2
# musl: /lib/ld-musl-x86_64.so.1
```

## Практические сценарии

### Сценарий 1: Пересборка для musl (рекомендуемый)

Нативная компиляция в Alpine сохраняет преимущества дистрибутива (размер, безопасность). Используйте [многоэтапную сборку](../Dockerfile/Docker_best_practices/build_optimization.md#многоэтапная-сборка-multi-stage-builds).

**Пример для Go:**

```dockerfile
# Этап сборки
FROM golang:1.26-alpine AS builder
WORKDIR /src
COPY . .
# Статическая компиляция без CGO
RUN CGO_ENABLED=0 go build -o /app .

# Финальный этап
FROM scratch
COPY --from=builder /app /app
CMD ["/app"]
```

**Пример для C/C++:**

```dockerfile
FROM alpine:3.23 AS builder
RUN apk add --no-cache gcc musl-dev
WORKDIR /src
COPY . .
RUN gcc -static myapp.c -o myapp

FROM scratch
COPY --from=builder /src/myapp /app
CMD ["/app"]
```

### Сценарий 2: Установка glibc в Alpine (компромисс)

Использовать только при отсутствии исходного кода.

```dockerfile
FROM alpine:3.23

ENV GLIBC_VERSION="2.40-r0"

RUN apk add --no-cache wget ca-certificates && \
    wget -q -O /etc/apk/keys/sgerrand.rsa.pub \
        https://alpine-pkgs.sgerrand.com/sgerrand.rsa.pub && \
    wget "https://github.com/sgerrand/alpine-pkg-glibc/releases/download/${GLIBC_VERSION}/glibc-${GLIBC_VERSION}.apk" && \
    apk add --no-cache glibc-${GLIBC_VERSION}.apk && \
    rm -f glibc-*.apk

COPY ./my-glibc-app /usr/local/bin/
CMD ["my-glibc-app"]
```

### Сценарий 3: Альтернативные базовые образы

Если glibc критична, рассмотрите:

- **`debian:slim`** — минималистичные образы Debian с glibc
- **`distroless`** — образы без shell, только приложение и glibc
- **`gcr.io/distroless/static-debian12`** — для статических бинарников

## Дополнительная информация

### Недостатки установки glibc в Alpine

- Увеличение размера образа (~15 МБ дополнительно)
- Нарушение философии минимализма Alpine
- Потенциальные конфликты между glibc и musl
- Сторонний репозиторий (вопросы безопасности)

### Предупреждение о версиях

Версии пакетов glibc для Alpine могут обновляться. Проверяйте актуальные релизы:

- [sgerrand/alpine-pkg-glibc releases](https://github.com/sgerrand/alpine-pkg-glibc/releases)
- [Alpine Linux packages](https://pkgs.alpinelinux.org/packages)
