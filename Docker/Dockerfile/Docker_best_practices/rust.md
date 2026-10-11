# Dockerfile: Лучшие практики для Rust

**Актуально для:** Rust 1.98.x

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
- **RUSTFLAGS:** Переменная окружения, передающая флаги компилятору `rustc` (например, `-C link-arg=-fuse-ld=mold`).
- **CARGO_REGISTRIES_CRATES_IO_PROTOCOL:** Переменная окружения, управляющая протоколом загрузки зависимостей. Значение `sparse` включает эффективный протокол sparse-индекса.
- **CARGO_INCREMENTAL:** Переменная окружения, управляющая инкрементальной компиляцией. В release-сборках внутри Docker рекомендуется отключать (`0`) для предотвращения раздувания `target`.
- **panic = "abort":** Стратегия обработки паник в Rust. Вместо раскрутки стека (unwind) происходит немедленное завершение процесса, что уменьшает размер бинарника.
- **codegen-units:** Количество параллельных единиц генерации кода. Значение `1` включает максимальную оптимизацию за счет отключения параллельной генерации.
- **rust-toolchain.toml:** Файл в корне проекта, фиксирующий версию тулчейна Rust. Обеспечивает воспроизводимость сборок между разными окружениями.
- **Workspace (Рабочая область):** Механизм Cargo для управления несколькими связанными пакетами в одном репозитории (монорепозиторий).
- **Cargo.lock:** Файл с точными версиями всех зависимостей (включая транзитивные). Должен коммититься для библиотек, но часто генерируется заново для бинарных проектов.
- **Cross-compilation (Кросс-компиляция):** Процесс создания бинарного файла под целевую архитектуру/ОС без выполнения кода этой архитектуры во время сборки. Rust поддерживает нативную кросс-компиляцию через `rustup target add`.
- **Target triple:** Строка вида `x86_64-unknown-linux-musl`, идентифицирующая целевую архитектуру, вендора, ОС и libc.
- **BuildKit:** Современный движок сборки Docker, поддерживающий параллельное выполнение этапов, монтирование кэша, секреты и Heredocs.
- **Cache Mount (Монтирование кэша):** Механизм BuildKit (`--mount=type=cache`), сохраняющий данные пакетных менеджеров между сборками без их попадания в итоговый образ.
- **Bind Mount (Монтирование контекста):** Механизм BuildKit (`--mount=type=bind`), предоставляющий доступ к файлам из контекста сборки или других стадий без их физического копирования.
- **Reproducible Build (Воспроизводимая сборка):** Свойство сборки давать идентичный бинарник/образ при одинаковых исходных данных.
- **SOURCE_DATE_EPOCH:** Переменная окружения (Unix timestamp), фиксирующая метку времени для всех файлов в образе. Используется для получения идентичных дайджестов при повторных сборках.
- **SBOM (Software Bill of Materials):** Декларативный список всех компонентов и зависимостей, входящих в состав образа.
- **distroless / chiseled:** Минималистичные образы от Google, содержащие только приложение и его рантайм-зависимости без shell, пакетных менеджеров и стандартных утилит.
- **Wolfi / Chainguard:** Современные "un-distro" образы с фокусом на безопасность (0 CVE). Используют `glibc` вместо `musl`.
- **PID 1 (в контексте Docker):** Первый процесс в пространстве имен контейнера. Отвечает за обработку сигналов и очистку зомби-процессов.

## Базовые концепции

### Специфика компиляции Rust в контейнерах

Rust обладает уникальными характеристиками, напрямую влияющими на проектирование Dockerfile:

*   **Тип:** Компилируемый. Создает нативный машинный код (ELF на Linux).
*   **Артефакт:** Одиночный исполняемый файл без внешних зависимостей (при статической линковке).
*   **Multi-stage:** Критически важен. Сборочный образ весит ~2 ГБ (с toolchain), финальный — от 5 МБ (scratch) до 80 МБ (debian-slim).
*   **Проблема кэширования:** Любое изменение в `src/*.rs` инвалидирует кэш слоев Docker, если не разделить сборку зависимостей и кода. Это делает cargo-chef и разделение COPY инструкций обязательными.
*   **Инкрементальная компиляция:** По умолчанию полезна для локальной разработки, но в Docker для `release` сборок её следует отключать (`CARGO_INCREMENTAL=0`), чтобы избежать раздувания `target` и проблем с кэшированием слоев.
*   **Отладочная информация:** По умолчанию Rust включает DWARF-отладку, увеличивающую размер бинарника на 30-50%. Для production используется `strip` или флаги `-s -w`.
*   **Сборка под foreign architecture:** Rust требует установки target triple через `rustup target add`. Для кросс-компиляции под ARM64/AMD64 также нужны linker и libc под целевую архитектуру.

### Выбор базового образа (Сравнение 2026)

| Характеристика | Alpine (musl) | Debian Bookworm (glibc) | Distroless (Static) | Wolfi (Chainguard) |
| :--- | :--- | :--- | :--- | :--- |
| **Библиотека C** | `musl` | `glibc` | Нет (или `musl`) | `glibc` (нативно для Rust) |
| **Безопасность** | Средняя | Средняя/Высокая | Высокая | **Максимальная (0 CVE)** |
| **Удобство** | Есть `sh`, `apk` | Есть `sh`, `apt` | Нет ничего | Есть `apk`, non-root |
| **Размер** | ~5–7 MB | ~50–70 MB | ~2–3 MB | ~10–15 MB |
| **C-библиотеки** | Требуют `musl-dev` | Стандартные Debian-пакеты | Только статические | Стандартные `apk`-пакеты |
| **Использование** | Статическая линковка, минимализм | CGO, OpenSSL, динамическая линковка | Максимальная минимизация | **Рекомендуется для новых проектов** |

**Рекомендация:** Используйте **Wolfi/Chainguard** для новых проектов как наиболее безопасную и производительную альтернативу с поддержкой `glibc`. Для проектов, требующих привычного Debian-окружения, выбирайте `rust:1.98-bookworm` на этапе сборки и `gcr.io/distroless/static-debian12` на рантайме. Alpine подходит только при использовании `musl` target и статической линковки.

### .dockerignore для Rust

Исключение лишних файлов из контекста сборки радикально ускоряет передачу данных в BuildKit:

```dockerignore
# Системные и служебные директории
.git
.vscode
.idea
tmp
dist
target

# Кэши Cargo
.cache

# Зависимости
vendor

# Не нужные в контейнере
*.md
LICENSE
.dockerignore
Dockerfile*
docker-compose*
Makefile
Taskfile*
rust-toolchain.toml
```

### Оптимизация скорости сборки (2026)

1.  **Sparse Index:** Включен по умолчанию, но в Docker полезно явно указывать `ENV CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse`.
2.  **Быстрые линкеры:** Использование `mold` (для Linux x86_64) или `lld` сокращает финальный этап сборки (линковку) на 50-80%.
3.  **Кэширование BuildKit:** Использование `--mount=type=cache,target=/usr/local/cargo/registry` и аналогичного для `target` является обязательным стандартом.
4.  **Разделение зависимостей:** Использование `cargo-chef` или создание "пустого" проекта для предварительной компиляции `Cargo.lock`.
5.  **sccache:** Для CI/CD пайплайнов с частыми пересборками используйте `sccache` с удаленным бэкендом (S3, Redis).

### Оптимизация бинарного файла

Для production-образов (профиль `release`):

1.  **Strip:** Удаление отладочных символов (`strip target/release/app`). Уменьшает размер на 30-50%.
2.  **LTO:** `lto = true` в `Cargo.toml`. Улучшает производительность, но замедляет сборку.
3.  **Panic Strategy:** `panic = "abort"` уменьшает размер за счет удаления логики unwinding.
4.  **Codegen Units:** Установка `codegen-units = 1` повышает оптимизацию за счет отказа от параллельной генерации кода.
5.  **UPX (опционально):** Дополнительное сжатие бинарника на 50-70% с минимальным оверхедом при старте.

### Рантайм и контейнеризация (Rust в 2026)

Rust-приложения в контейнерах подвержены тем же ограничениям cgroups, что и любые другие:

*   **Память (cgroups v2):** Rust рантайм не видит лимит памяти контейнера автоматически. При превышении лимита RSS процесс получает `SIGKILL` (Exit Code 137). Для предотвращения OOM Kill используйте предсказуемый аллокатор (`jemalloc`, `mimalloc`) и корректно настраивайте лимиты. В cgroups v2 также доступен `memory.high` (мягкий лимит с throttling) и `memory.max` (жесткий лимит с kill).
*   **CPU Throttling:** Если лимит процессора превышен, ядро ограничивает кванты времени. Rust-приложения должны адаптировать количество потоков под лимиты cgroups (например, через `num_cpus::get()` или чтение `/sys/fs/cgroup/cpu.max`). Для сервисов с жесткими latency-требованиями используйте `cpu.shares` и `cpu.rt_runtime_us`.
*   **PID Limits:** Ограничьте количество процессов через `--pids-limit`. По умолчанию в Docker нет лимита, что позволяет злоумышленнику запустить fork bomb или случайно исчерпать таблицу процессов ядра.
*   **User Namespace Remapping (Userns):** Маппинг UID 0 (root) внутри контейнера на непривилегированного пользователя хоста предотвращает эскалацию привилегий при побеге из контейнера. В Docker включите через `userns-remap` в daemon.json.
*   **Обработка сигналов:** Rust приложения должны явно перехватывать `SIGTERM` и `SIGINT` для корректного graceful shutdown. Без обработки Docker будет ждать таймаут и отправит `SIGKILL`.
*   **Graceful Shutdown:** Паттерн: перехват `SIGTERM` → остановка приема новых запросов → завершение текущих операций → сохранение состояния → выход. Используйте `STOPSIGNAL SIGTERM` в Dockerfile для явного указания сигнала.
*   **Проблема PID 1:** Rust-приложения без дочерних процессов могут безопасно работать как PID 1. Если приложение порождает дочерние процессы (например, через `std::process::Command`), используйте `tini` или `dumb-init`.
*   **Read-only Rootfs:** Запуск с `--read-only` блокирует запись в корневую ФС, предотвращая эксплойты persistence. Используйте `tmpfs` для `/tmp` и других writable директорий.
*   **Логирование:** Для production используйте structured logging (JSON) и Docker logging drivers (`json-file` с rotation, `fluentd`, `awslogs`, `gcplogs`). Избегайте записи логов в файлы внутри контейнера при read-only rootfs — используйте stdout/stderr.
*   **Environment-driven Configuration:** Следуйте 12-factor app methodology: конфигурация через переменные окружения, секреты через Docker Secrets или BuildKit Secrets, а не через файлы или ARG в Dockerfile.

### Воспроизводимость сборок (Reproducible Builds)

Для получения идентичных дайджестов бинарников и образов:

1.  **rust-toolchain.toml:** Фиксируйте версию тулчейна в репозитории.
2.  **Cargo.lock:** Фиксируйте версии всех зависимостей.
3.  **Флаги stripping путей:** Используйте `RUSTFLAGS="-C link-arg=-fdebug-prefix-map=$(pwd)=."` для удаления абсолютных путей из бинарника.
4.  **SOURCE_DATE_EPOCH:** Переменная окружения, фиксирующая временную метку. BuildKit поддерживает её нативно.
5.  **Pinning по дайджесту:** Базовые образы фиксируются по SHA256, а не по тегу.
6.  **Отключение incremental:** `CARGO_INCREMENTAL=0` гарантирует детерминированную сборку.

### Подводные камни минимальных образов (scratch / distroless / Alpine / Wolfi)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **HTTPS/TLS ошибки** | Нет доверенных CA | Копировать `/etc/ssl/certs/ca-certificates.crt` из builder |
| **Неверное время** | Нет базы `tzdata` | Копировать `/usr/share/zoneinfo` или устанавливать `TZ=UTC` |
| **Permission Denied** | Запуск от root | Создать UID 10001 в builder и скопировать `/etc/passwd` |
| **Binary not found** | Динамическая линковка | Статическая линковка (`x86_64-unknown-linux-musl`) или Wolfi (glibc) |
| **OOM Kill (Exit 137)** | Отсутствие лимита или утечка памяти | Установить лимит памяти, использовать предсказуемый аллокатор |
| **CPU Throttling** | `std::thread::available_parallelism()` выше лимита cgroups | Читать `/sys/fs/cgroup/cpu.max` для адаптации пула потоков |
| **Отсутствие шрифтов/локали** | Нет `glibc` locale | Копировать `/usr/share/locale` или использовать Wolfi с `glibc` |
| **Крупный размер бинарника** | Отсутствие strip, LTO | Применять `strip`, `lto=true`, `codegen-units = 1`, `panic = "abort"` |
| **Read-only rootfs** | Приложение пытается писать в корень | Использовать `tmpfs` для `/tmp`, `--read-only` и `--tmpfs /tmp:rw,noexec,nosuid` |
| **Logs lost** | Запись в файл, а не stdout | Логировать в stdout/stderr для работы с Docker logging drivers |
| **Fork bomb / зомби** | Отсутствие `--pids-limit` и PID 1 обработчика | Добавить `--pids-limit=64` и использовать `tini` если есть дочерние процессы |
| **Permission Denied (userns)** | UID 0 внутри контейнера, но remap на хосте | Использовать числовой UID 10001 и копировать `/etc/passwd` при необходимости |

## Практические сценарии

### Сценарий 1: Сборка через cargo-chef (Золотой стандарт)

Позволяет кэшировать зависимости отдельно от кода приложения.

```dockerfile
# syntax=docker/dockerfile:1
# check=error=true

# --- Этап 1: Планирование (planner) ---
FROM lukemathwalker/cargo-chef:latest-rust-1.98.1-alpine3.24 AS planner
WORKDIR /app
COPY . .
RUN cargo chef prepare --recipe-path recipe.json

# --- Этап 2: Сборка зависимостей (cacher) ---
FROM lukemathwalker/cargo-chef:latest-rust-1.98.1-alpine3.24 AS cacher
WORKDIR /app
COPY --from=planner /app/recipe.json recipe.json
ENV CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse
# Кэшируем и реестр, и результаты сборки зависимостей
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo chef cook --release --recipe-path recipe.json

# --- Этап 3: Сборка приложения (builder) ---
FROM rust:1.98-alpine3.24 AS builder
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

**Валидация:**
```bash
# Проверка размера образа
docker images myapp:latest
# → alpine:3.24 (~10MB) + my-app (~5-15MB)

# Проверка статической линковки
docker run --rm myapp:latest ldd ./app
# → "not a dynamic executable" (если собрано с musl)

# Проверка пользователя
docker run --rm myapp:latest id
# → uid=10001(appuser) gid=10001(appuser)
```

### Сценарий 2: Статическая линковка и запуск в `scratch`

Идеально для микросервисов без внешних зависимостей от ОС.

```dockerfile
# syntax=docker/dockerfile:1
FROM rust:1.98-alpine3.24 AS builder
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
FROM --platform=$BUILDPLATFORM rust:1.98-slim AS builder
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

### Сценарий 4: Мультиплатформенная сборка (Buildx + cargo-chef)

Сборка под AMD64 и ARM64 с использованием нативной кросс-компиляции Rust.

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM rust:1.98-slim AS planner
WORKDIR /app
COPY . .
RUN cargo chef prepare --recipe-path recipe.json

FROM --platform=$BUILDPLATFORM rust:1.98-slim AS cacher
WORKDIR /app
COPY --from=planner /app/recipe.json recipe.json
ENV CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo chef cook --release --recipe-path recipe.json

FROM --platform=$BUILDPLATFORM rust:1.98-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    binutils mold gcc-aarch64-linux-gnu libc6-dev-arm64-cross && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
COPY --from=cacher /app/target target
COPY --from=cacher /usr/local/cargo /usr/local/cargo
ARG TARGETPLATFORM
ENV CARGO_INCREMENTAL=0
RUN case "$TARGETPLATFORM" in \
      "linux/amd64") export TARGET="x86_64-unknown-linux-gnu" ;; \
      "linux/arm64") export TARGET="aarch64-unknown-linux-gnu" ;; \
    esac && \
    cargo build --release --target $TARGET && \
    strip target/$TARGET/release/my-app

# Финальный multi-stage (пример для Alpine)
FROM alpine:3.24
RUN apk add --no-cache libgcc
WORKDIR /app
COPY --from=builder /app/target/release/my-app ./app
RUN adduser -D -u 10001 appuser
USER appuser
ENTRYPOINT ["./app"]
```

Запуск:
```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --cache-from type=registry,ref=myreg.com/app:cache \
  --cache-to type=registry,ref=myreg.com/app:cache,mode=max \
  -t myreg.com/app:1.0.0 \
  --push .
```

### Сценарий 5: Окружение для разработки (Hot Reload)

Использование `cargo-watch` для автоматического перезапуска внутри контейнера.

```dockerfile
# syntax=docker/dockerfile:1
FROM rust:1.98 AS dev
RUN cargo install cargo-watch
WORKDIR /app
# Кэшируем зависимости для ускорения запуска dev-контейнера
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs && cargo build && rm -rf src
COPY . .
ENTRYPOINT ["cargo", "watch", "-x", "run"]
```

Запуск:
```bash
docker run --rm -it -v $(pwd):/app -p 8080:8080 myapp:dev
```

### Сценарий 6: Работа с Workspaces (Монорепозитории)

При сборке в Workspace важно копировать все `Cargo.toml` для корректного планирования.

```dockerfile
# В этапе planner для cargo-chef
COPY Cargo.toml Cargo.lock ./
COPY crates/ crates/
RUN cargo chef prepare --recipe-path recipe.json
```

### Сценарий 7: Воспроизводимая сборка с SOURCE_DATE_EPOCH

Фиксация временных меток для получения идентичных дайджестов при повторных сборках.

```dockerfile
# syntax=docker/dockerfile:1
ARG RUST_VERSION=1.98
FROM rust:${RUST_VERSION}-bookworm AS builder

# Фиксируем метку времени (например, timestamp коммита)
ARG SOURCE_DATE_EPOCH=1724200000

WORKDIR /app
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH} \
    CARGO_INCREMENTAL=0

COPY Cargo.toml Cargo.lock ./
COPY src ./src

RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo build --release && \
    strip target/release/my-app

FROM debian:bookworm-slim
COPY --from=builder /app/target/release/my-app /usr/bin/app
RUN useradd -m -u 10001 appuser
USER 10001
ENTRYPOINT ["/usr/bin/app"]
```

Запуск:
```bash
SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) docker buildx build --platform linux/amd64 -t myapp:1.0.0 .
```

### Сценарий 8: CI/CD пайплайн с cargo-audit, syft, Docker Scout и Trivy

Полный цикл проверки безопасности в GitHub Actions. `docker scout` — нативный инструмент Docker для анализа уязвимостей, использующий SBOM-аттестации, прикрепленные на этапе сборки.

```yaml
# .github/workflows/docker-rust.yml
name: Build and Scan Rust Docker Image

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Cache Cargo registry
        uses: actions/cache@v4
        with:
          path: |
            ~/.cargo/registry
            ~/.cargo/git
            target
          key: cargo-${{ hashFiles('**/Cargo.lock') }}

      - name: Install cargo-audit
        run: cargo install cargo-audit

      - name: Check vulnerabilities
        run: cargo audit

      - name: Build image
        run: |
          docker buildx build \
            --platform linux/amd64,linux/arm64 \
            --cache-from type=registry,ref=ghcr.io/${{ github.repository }}:cache \
            --cache-to type=registry,ref=ghcr.io/${{ github.repository }}:cache,mode=max \
            --sbom true \
            --provenance mode=max \
            --tag ghcr.io/${{ github.repository }}:${{ github.sha }} \
            --push .

      - name: Install Syft
        uses: anchore/syft-action@v0.94.0
        with:
          image: ghcr.io/${{ github.repository }}:${{ github.sha }}
          format: spdx-json
          output: syft.spdx.json

      - name: Install Trivy
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ghcr.io/${{ github.repository }}:${{ github.sha }}
          format: table
          exit-code: 1
          severity: HIGH,CRITICAL

      - name: Analyze vulnerabilities with Docker Scout
        run: |
          docker scout cves ghcr.io/${{ github.repository }}:${{ github.sha }} \
            --only-critical \
            --exit-code 1
```

### Сценарий 9: CGO с OpenSSL на Debian + Distroless

Для Rust-приложений, требующих нативные C-библиотеки (например, `openssl-sys`).

```dockerfile
# syntax=docker/dockerfile:1
FROM rust:1.98-bookworm AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN cargo build --release && \
    strip target/release/my-app

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /app/target/release/my-app /usr/bin/app
# Если нужны динамические библиотеки, копируем их
COPY --from=builder /usr/lib/x86_64-linux-gnu/libssl.so* /usr/lib/x86_64-linux-gnu/
USER 65532
ENTRYPOINT ["/usr/bin/app"]
```

## Безопасность и верификация

### Верификация и аудит

1.  **Проверка зависимостей:** `cargo audit` для поиска известных уязвимостей в зависимостях.
2.  **Аудит лицензий:** `cargo deny` для проверки лицензий зависимостей и запрета нежелательных.
3.  **Генерация SBOM:** Рекомендуется генерировать Software Bill of Materials на этапе сборки:
    ```bash
    cargo sbom > bom.json
    # Или через внешние инструменты
    syft target/release/my-app -o json > sbom.json
    ```
4.  **Проверка бинарника:** `file`, `readelf`, `ldd` для анализа типа линковки и архитектуры.

### Права доступа

Всегда создавайте пользователя с минимальными правами. Если приложению нужны `capabilities` (например, для биндинга портов < 1024), используйте `setcap` на этапе сборки и запускайте бинарник с ограниченными правами.

## Верификация и отладка

### Глубокий анализ бинарника

1.  **Проверка статической линковки:**
    ```bash
    ldd ./my-app
    # → "not a dynamic executable" — успех для scratch/distroless static.
    ```
    Для детального анализа используйте `readelf` или `objdump`:
    ```bash
    readelf -h ./my-app | grep "Type:"
    # → "Type: EXEC (Executable file)" — бинарник готов к запуску
    ```

2.  **Проверка архитектуры и ОС:**
    ```bash
    file ./my-app
    # → ./my-app: ELF 64-bit LSB executable, ARM aarch64, version 1 (SYSV), statically linked
    ```

3.  **Проверка уязвимостей (cargo-audit):** Обязательный шаг в CI/CD для обнаружения CVE в зависимостях.
    ```bash
    cargo audit
    # → No vulnerabilities found.
    ```

4.  **Проверка размера и секций:**
    ```bash
    size ./my-app
    # → показывает размер .text, .data, .bss секций
    ```

5.  **SBOM генерация:** Используйте `syft` или `docker build --sbom` для генерации состава образа.
    ```bash
    syft myapp:latest -o spdx-json > sbom.spdx.json
    ```

6.  **Сканирование уязвимостей образа (Trivy):**
    ```bash
    trivy image myapp:latest --severity HIGH,CRITICAL
    ```

7.  **Анализ слоев (dive):** Визуальный инструмент для поиска неожиданных файлов в слоях.
    ```bash
    dive myapp:latest
    ```

### Диагностика рантайма

```bash
# Проверка сигналов (Rust приложение должно обрабатывать SIGTERM)
docker run --rm myapp:latest sh -c "kill -SIGTERM 1 && sleep 5 && ps aux"

# Проверка лимитов cgroups
docker inspect myapp --format='{{.HostConfig.Memory}}'
docker inspect myapp --format='{{.HostConfig.CpuShares}}'

# Мониторинг OOM
docker inspect myapp --format='{{.State.OOMKilled}}'

# Проверка exit code
docker inspect myapp --format='{{.State.ExitCode}}'
```

## Типичные ошибки и их решение

### Ошибка 1: Сборка не кэшируется при изменении кода

**Причина:** `COPY . .` выполняется до сборки зависимостей или зависимости не отделены от кода.

```dockerfile
# ПЛОХО: любое изменение кода инвалидирует весь кэш
COPY . .
RUN cargo build --release
```

**Решение:** Используйте cargo-chef или разделите COPY инструкций:
```dockerfile
COPY Cargo.toml Cargo.lock ./
RUN cargo fetch
COPY src ./src
RUN cargo build --release
```

### Ошибка 2: Слишком большой размер образа

**Причина:** В финальный образ попадают исходный код, Cargo кэш или не-stripped бинарник.

```bash
# Диагностика
docker images myapp
# → 2.1 GB (вместо ожидаемых 10-50 MB)

# dive покажет лишние слои
dive myapp:latest
```

**Решение:**
1. Используйте multi-stage сборку
2. Добавьте `strip target/release/my-app`
3. Включите `lto = true` и `panic = "abort"` в `Cargo.toml`

### Ошибка 3: `ld: error: unable to find library -lssl`

**Причина:** Отсутствуют нативные зависимости при статической линковке или CGO.

```bash
# Диагностика
docker build .
# → error: linking with `cc` failed: exit status 1
# → ld: library not found for -lssl
```

**Решение:** Установите `openssl-dev` (Alpine) или `libssl-dev` (Debian) в builder-этапе.

### Ошибка 4: Контейнер не запускается на ARM64

**Причина:** Бинарник собран под `x86_64`, но контейнер запускается на `arm64`.

```bash
# Диагностика
docker run --rm myapp:latest
# → exec format error

# Проверка архитектуры
file target/release/my-app
# → ELF 64-bit LSB executable, x86-64
```

**Решение:** Используйте `docker buildx build --platform linux/arm64` или нативную кросс-компиляцию.

### Ошибка 5: TLS ошибки в scratch/ minimal образах

**Причина:** Отсутствуют CA-сертификаты.

```bash
# Диагностика
curl https://crates.io
# → curl: (60) SSL certificate problem
```

**Решение:** Скопируйте `/etc/ssl/certs/ca-certificates.crt` из builder в финальный образ.

## Лучшие практики

### Сводка рекомендаций

| Практика | Рекомендация | Причина |
| :--- | :--- | :--- |
| **Multi-stage** | Всегда используйте | Исключает toolchain и исходный код из финального образа |
| **cargo-chef** | Для production-сборок | Максимальное кэширование зависимостей |
| **Cache Mounts** | `cargo registry` + `target` | Ускоряет повторные сборки в 2-5 раз |
| **Быстрый линкер** | `mold` или `lld` | Сокращает линковку на 50-80% |
| **Strip** | Удаляйте отладочные символы | Уменьшает размер на 30-50% |
| **LTO** | `lto = true` | Улучшает производительность |
| **Panic abort** | `panic = "abort"` | Уменьшает размер |
| **Non-root** | `USER 10001` | Безопасность (Pod Security Standards) |
| **SBOM** | Генерируйте на этапе CI | Аудит зависимостей и CVE |
| **Pin версии** | `rust:1.98-bookworm` | Воспроизводимость сборок |
| **Sparse Index** | `CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse` | Ускоряет `cargo fetch` |
| **HEALTHCHECK** | Добавляйте в runtime-образ | Мониторинг состояния контейнера |

### Порядок инструкций в Dockerfile

```dockerfile
# 1. FROM (multi-stage)
FROM rust:1.98-bookworm AS builder

# 2. SHELL (если нужен pipefail)
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# 3. WORKDIR
WORKDIR /app

# 4. Системные зависимости (mold, pkg-config, libssl-dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
    mold binutils pkg-config libssl-dev && \
    rm -rf /var/lib/apt/lists/*

# 5. Кэширование зависимостей (cargo-chef или ручное)
COPY Cargo.toml Cargo.lock ./
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    cargo fetch

# 6. Исходный код и сборка
COPY src ./src
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    CARGO_INCREMENTAL=0 \
    cargo build --release && \
    strip target/release/my-app

# 7. Финальный образ
FROM alpine:3.24
COPY --from=builder /app/target/release/my-app ./app
RUN adduser -D -u 10001 appuser
USER 10001
HEALTHCHECK --interval=30s --timeout=3s CMD ./app --health || exit 1
ENTRYPOINT ["./app"]
```

### Чек-лист перед деплоем

- [ ] Multi-stage сборка исключает toolchain из финального образа
- [ ] Бинарник stripped (отладочные символы удалены)
- [ ] Запуск от non-root пользователя (UID 10001 или аналоги)
- [ ] HEALTHCHECK добавлен в финальный образ
- [ ] SBOM генерируется на этапе CI/CD
- [ ] cargo audit запущен и не имеет HIGH/CRITICAL уязвимостей
- [ ] Версии базовых образов зафиксированы (не `latest`)
- [ ] SOURCE_DATE_EPOCH установлен для воспроизводимости (опционально)
- [ ] Кэш BuildKit настроен (registry или local)

## Дополнительная информация

### Смотрите также

- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — общие стратегии кэширования.
- **[Безопасность в Dockerfile](./security.md)** — глубокий аудит и сканирование CVE.
- **[Выполнение приложений в контейнере](./container_execution.md)** — PID 1 и сигналы.
