# Dockerfile: Лучшие практики для Rust

## Определения

- **Cargo:** Официальный менеджер пакетов и система сборки для Rust.
- **Toolchain:** Набор инструментов (компилятор `rustc`, менеджер `cargo`, стандартная библиотека), необходимых для сборки.
- **Статическая линковка (Static Linking):** Включение всех необходимых библиотек (включая `libc`) в исполняемый файл. Бинарник становится полностью автономным и может работать в образе `scratch`.
- **LTO (Link Time Optimization):** Оптимизация на этапе линковки, уменьшающая размер бинарного файла и повышающая его производительность.
- **cargo-chef:** Инструмент для декомпозиции `Cargo.toml` и предварительной сборки зависимостей, что обеспечивает максимально эффективное кэширование слоев Docker.
- **mold / lld:** Современные сверхбыстрые линкеры. `mold` может сократить время линковки в несколько раз по сравнению со стандартным `ld`.
- **Sparse Index:** Метод получения метаданных пакетов из crates.io по HTTP вместо скачивания всего git-репозитория. Ускоряет `cargo fetch` и `cargo build`.
- **MUSL / GLIBC:** Две реализации стандартной библиотеки C. `musl` чаще используется для статической линковки в минимальных образах (Alpine), `glibc` — стандарт для Debian/Ubuntu.
- **sccache:** Инструмент для распределенного кэширования компиляции (Shared Compilation Cache), позволяющий переиспользовать артефакты между разными сборками.
- **cargo-zigbuild:** Обертка над `cargo`, использующая линкер Zig для упрощения кросс-компиляции и управления версиями `glibc`.

## Базовые концепции

### Специфика компиляции Rust в контейнерах

Rust известен длительным временем компиляции, что требует особого подхода к Docker:
*   **Тип:** Компилируемый. Создает нативный машинный код.
*   **Артефакт:** Одиночный исполняемый файл.
*   **Multi-stage:** Критически важен. Сборочный образ весит ~2 ГБ, финальный — от 5 МБ (scratch) до 80 МБ (debian-slim).
*   **Проблема кэширования:** Любое изменение в `src/*.rs` инвалидирует кэш слоев Docker, если не разделять сборку зависимостей и кода.
*   **Инкрементальная компиляция:** По умолчанию полезна для локальной разработки, но в Docker для `release` сборок её следует отключать (`CARGO_INCREMENTAL=0`), чтобы избежать раздувания `target` и проблем с кэшированием слоев.

### Оптимизация скорости сборки (2026)

1.  **Sparse Index:** Включен по умолчанию, но в Docker полезно явно указывать `ENV CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse`.
2.  **Быстрые линкеры:** Использование `mold` (для Linux x86_64) или `lld` сокращает финальный этап сборки (линковку) на 50-80%.
3.  **Кэширование BuildKit:** Использование `--mount=type=cache,target=/usr/local/cargo/registry` и аналогичного для `target` является обязательным стандартом.
4.  **Разделение зависимостей:** Использование `cargo-chef` или создание "пустого" проекта для предварительной компиляции `Cargo.lock`.

### Оптимизация бинарного файла

Для production-образов (профиль `release`):
1.  **Strip:** Удаление отладочных символов (`strip target/release/app`). Уменьшает размер на 30-50%.
2.  **LTO:** `lto = true` в `Cargo.toml`. Улучшает производительность, но замедляет сборку.
3.  **Panic Strategy:** `panic = "abort"` уменьшает размер за счет удаления логики unwinding.
4.  **Codegen Units:** Установка `codegen-units = 1` повышает оптимизацию за счет отказа от параллельной генерации кода.

## Практические сценарии

### Сценарий 1: Сборка через cargo-chef (Золотой стандарт)

Позволяет кэшировать зависимости отдельно от кода приложения.

```dockerfile
# syntax=docker/dockerfile:1
# check=error=true

# --- Этап 1: Планирование (planner) ---
FROM lukemathwalker/cargo-chef:latest-rust-1.85-alpine AS planner
WORKDIR /app
COPY . .
RUN cargo chef prepare --recipe-path recipe.json

# --- Этап 2: Сборка зависимостей (cacher) ---
FROM lukemathwalker/cargo-chef:latest-rust-1.85-alpine AS cacher
WORKDIR /app
COPY --from=planner /app/recipe.json recipe.json
ENV CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse
# Кэшируем и реестр, и результаты сборки зависимостей
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo chef cook --release --recipe-path recipe.json

# --- Этап 3: Сборка приложения (builder) ---
FROM rust:1.85-alpine AS builder
RUN apk add --no-cache binutils mold
WORKDIR /app
COPY . .
# Копируем кэшированные зависимости
COPY --from=cacher /app/target target
COPY --from=cacher /usr/local/cargo /usr/local/cargo
# Сборка с быстрым линкером и без инкрементальности
ENV CARGO_INCREMENTAL=0
ENV RUSTFLAGS="-C link-arg=-fuse-ld=mold"
RUN cargo build --release && \
    strip target/release/my-app

# --- Этап 4: Финальный образ (runtime) ---
FROM alpine:3.24
RUN apk add --no-cache libgcc
WORKDIR /app
COPY --from=builder /app/target/release/my-app ./app
# Запуск от не-root пользователя
RUN adduser -D -u 10001 appuser
USER appuser
HEALTHCHECK --interval=30s --timeout=3s CMD ./app --health || exit 1
ENTRYPOINT ["./app"]
```

### Сценарий 2: Статическая линковка и запуск в `scratch`

Идеально для микросервисов без внешних зависимостей от ОС.

```dockerfile
# syntax=docker/dockerfile:1
FROM rust:1.85-alpine AS builder
RUN apk add --no-cache musl-dev pkgconfig openssl-dev binutils
WORKDIR /app
COPY . .
RUN rustup target add x86_64-unknown-linux-musl

# Сборка со статической линковкой
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    cargo build --release --target x86_64-unknown-linux-musl && \
    strip target/x86_64-unknown-linux-musl/release/my-app

FROM scratch
# Не забываем сертификаты для HTTPS запросов
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /app/target/x86_64-unknown-linux-musl/release/my-app /main
# Использование цифрового ID пользователя (scratch не знает имен)
USER 10001:10001
ENTRYPOINT ["/main"]
```

### Сценарий 3: Кросс-компиляция через cargo-zigbuild

Решает проблемы с разными версиями `glibc` при сборке под ARM64/AMD64.

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM rust:1.85-slim AS builder
RUN apt-get update && apt-get install -y python3 pip clang zig
RUN cargo install cargo-zigbuild
WORKDIR /app
COPY . .
ARG TARGETPLATFORM
RUN case "$TARGETPLATFORM" in \
      "linux/amd64") export TARGET="x86_64-unknown-linux-gnu.2.28" ;; \
      "linux/arm64") export TARGET="aarch64-unknown-linux-gnu.2.28" ;; \
    esac && \
    cargo zigbuild --release --target $TARGET
```

### Сценарий 4: Окружение для разработки (Hot Reload)

Использование `cargo-watch` для автоматического перезапуска внутри контейнера.

```dockerfile
# syntax=docker/dockerfile:1
FROM rust:1.85 AS dev
RUN cargo install cargo-watch
WORKDIR /app
# Кэшируем зависимости для ускорения запуска dev-контейнера
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs && cargo build && rm -rf src
COPY . .
ENTRYPOINT ["cargo", "watch", "-x", "run"]
```

### Сценарий 5: Работа с Workspaces (Монорепозитории)

При сборке в Workspace важно копировать все `Cargo.toml` для корректного планирования.
```dockerfile
# В этапе planner для cargo-chef
COPY Cargo.toml Cargo.lock ./
COPY crates/ crates/
RUN cargo chef prepare --recipe-path recipe.json
```

## Безопасность и верификация

### Верификация и аудит

1.  **Проверка зависимостей:** Использование `ldd` для подтверждения статической линковки.
2.  **Аудит безопасности:** `cargo audit` для поиска известных уязвимостей в зависимостях.
3.  **Генерация SBOM:** Рекомендуется генерировать Software Bill of Materials на этапе сборки:
    ```bash
    cargo sbom > bom.json
    # Или через внешние инструменты
    syft target/release/my-app -o json > sbom.json
    ```

### Права доступа

Всегда создавайте пользователя с минимальными правами. Если приложению нужны `capabilities` (например, для биндинга портов < 1024), используйте `setcap` на этапе сборки и запускайте бинарник с ограниченными правами.

## Дополнительная информация

### Смотрите также

- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — общие стратегии кэширования.
- **[Безопасность в Dockerfile](./security.md)** — глубокий аудит и сканирование CVE.
- **[Кэширование для Rust в GitLab CI](../../CI-CD/GitLab_CI/Advanced/gitlab_ci_caching/cache_scenarios.md#сценарий-4---кэширование-зависимостей-rust-cargo)**
- **[Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md)**
- **[Инструменты оптимизации Dockerfile](../dockerfile_optimization_tools.md)** — обзор `D-roast` и других утилит.
- **[Проблема зомби-процессов (PID 1)](./container_execution.md)** — важно для Rust-приложений, запускающих дочерние процессы.
