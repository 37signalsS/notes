# Dockerfile: Лучшие практики для Rust

> **Надежность: 10** (Актуализировано согласно стандартам 2026 года, Rust 1.85+)

## Определения

- **Cargo:** Официальный менеджер пакетов и система сборки для Rust.
- **Toolchain:** Набор инструментов (компилятор `rustc`, менеджер `cargo`, стандартная библиотека), необходимых для сборки.
- **Статическая линковка (Static Linking):** Включение всех необходимых библиотек (включая `libc`) в исполняемый файл. Бинарник становится полностью автономным и может работать в образе `scratch`.
- **LTO (Link Time Optimization):** Оптимизация на этапе линковки, уменьшающая размер бинарного файла и повышающая его производительность.
- **cargo-chef:** Инструмент для декомпозиции `Cargo.toml` и предварительной сборки зависимостей, что обеспечивает максимально эффективное кэширование слоев Docker.
- **MUSL / GLIBC:** Две реализации стандартной библиотеки C. `musl` чаще используется для статической линковки в минимальных образах (Alpine), `glibc` — стандарт для Debian/Ubuntu.

## Базовые концепции

### Специфика компиляции Rust

Rust известен длительным временем компиляции, особенно при первой сборке зависимостей.
*   **Тип:** Компилируемый. Создает нативный машинный код.
*   **Артефакт:** Одиночный исполняемый файл.
*   **Multi-stage:** Обязателен. Образ со сборочным тулчейном весит ~1.5–2 ГБ, тогда как финальный бинарник обычно занимает от 10 до 50 МБ.
*   **Проблема кэширования:** Стандартная инструкция `COPY . .` инвалидирует кэш при любом изменении кода, заставляя `cargo build` пересобирать все зависимости.

### Кэширование через BuildKit

Использование монтирования кэша (`--mount=type=cache`) позволяет сохранять директорию `target` и кэш `cargo` между сборками на одном хосте, что сокращает время инкрементальной сборки в разы.

### Оптимизация бинарного файла

Для production-образов критически важно:
1.  **Release-профиль:** Сборка с флагом `--release`.
2.  **Strip:** Удаление отладочных символов (`strip target/release/app`).
3.  **LTO:** Включение `lto = true` в `Cargo.toml` для лучшей оптимизации.

## Практические сценарии

### Сценарий 1: Сборка через cargo-chef (Максимальное кэширование)

Это «золотой стандарт» для Rust в Docker. Позволяет кэшировать зависимости даже при изменении исходного кода.

```dockerfile
# syntax=docker/dockerfile:1
# --- Этап 1: Планирование (planner) ---
FROM lukemathwalker/cargo-chef:latest-rust-1.85-alpine AS planner
WORKDIR /app
COPY . .
RUN cargo chef prepare --recipe-path recipe.json

# --- Этап 2: Сборка зависимостей (cacher) ---
FROM lukemathwalker/cargo-chef:latest-rust-1.85-alpine AS cacher
WORKDIR /app
COPY --from=planner /app/recipe.json recipe.json
# Кэшируем сборку зависимостей
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo chef cook --release --recipe-path recipe.json

# --- Этап 3: Сборка приложения (builder) ---
FROM rust:1.85-alpine AS builder
WORKDIR /app
COPY . .
# Копируем скомпилированные зависимости
COPY --from=cacher /app/target target
COPY --from=cacher /usr/local/cargo /usr/local/cargo
# Сборка кода приложения и очистка бинарника
RUN cargo build --release && \
    strip target/release/my-app

# --- Этап 4: Финальный образ (runtime) ---
FROM alpine:3.24
# Установка необходимых рантайм-библиотек (если не используется scratch)
RUN apk add --no-cache libgcc
WORKDIR /app
COPY --from=builder /app/target/release/my-app ./app
# Запуск от непривилегированного пользователя
RUN adduser -D -u 10001 appuser
USER appuser
ENTRYPOINT ["./app"]
```

### Сценарий 2: Статическая линковка и запуск в `scratch`

Для максимальной безопасности и минимального размера. Требует целевой платформы `x86_64-unknown-linux-musl`.

```dockerfile
# syntax=docker/dockerfile:1
FROM rust:1.85-alpine AS builder
RUN apk add --no-cache musl-dev pkgconfig openssl-dev
WORKDIR /app
COPY . .
# Добавляем target для статической сборки
RUN rustup target add x86_64-unknown-linux-musl
# Сборка со статической линковкой
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    cargo build --release --target x86_64-unknown-linux-musl && \
    strip target/x86_64-unknown-linux-musl/release/my-app

# --- Финальный этап ---
FROM scratch
# Копируем бинарник и (если нужно) системные сертификаты для HTTPS
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /app/target/x86_64-unknown-linux-musl/release/my-app /main
ENTRYPOINT ["/main"]
```

### Сценарий 3: Мультиплатформенная сборка (AMD64/ARM64)

Использование встроенных переменных BuildKit для кросс-компиляции.

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM rust:1.85 AS builder
ARG TARGETPLATFORM
WORKDIR /app
COPY . .
# Логика выбора архитектуры и кросс-компиляции
RUN case "$TARGETPLATFORM" in \
      "linux/amd64") export TARGET="x86_64-unknown-linux-gnu" ;; \
      "linux/arm64") export TARGET="aarch64-unknown-linux-gnu" ;; \
    esac && \
    rustup target add $TARGET && \
    cargo build --release --target $TARGET
```

### Верификация бинарника

```bash
# Проверка зависимостей (ldd)
ldd ./app 
# → not a dynamic executable (для статической сборки)

# Проверка на уязвимости зависимостей (cargo-audit)
# Рекомендуется запускать на этапе CI до сборки образа
cargo audit
```

## Дополнительная информация

### Смотрите также

- [Оптимизация сборки Docker-образов](./build_optimization.md) — кэширование и multi-stage.
- [Безопасность в Dockerfile](./security.md) — использование `scratch` и `distroless`.
- [Кэширование для Rust в GitLab CI](../../CI-CD/GitLab_CI/Advanced/gitlab_ci_caching/cache_scenarios.md#сценарий-4---кэширование-зависимостей-rust-cargo) — настройка CI-пайплайна.
- [Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md)
