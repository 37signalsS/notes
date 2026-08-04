# Dockerfile: Лучшие практики для C/C++

## Определения

- **Toolchain:** Набор инструментов для компиляции и сборки ПО (компиляторы `gcc`/`clang`, линковщики `ld`/`lld`/`mold`, системы сборки `make`/`cmake`/`ninja`).
- **mold:** Сверхбыстрый современный линковщик, работающий в несколько раз быстрее `lld` и на порядки быстрее классического `ld`. Критичен для сокращения времени сборки крупных проектов в Docker.
- **Статическая линковка (Static Linking):** Включение всех необходимых библиотек непосредственно в исполняемый файл. Позволяет создавать автономные бинарники, работающие в образах `scratch`.
- **Wolfi / Chainguard:** Современные "un-distro" образы, ориентированные на безопасность (0 CVE) и использующие `glibc`. Идеальная база для производительных C++ приложений.
- **Hardening:** Применение флагов компиляции (например, `-fhardened`, `Stack Protector`, `Full RELRO`) для повышения устойчивости бинарника к эксплойтам.
- **PGO (Profile-Guided Optimization):** Метод оптимизации, при котором компилятор использует данные реального выполнения программы для ускорения кода.
- **BOLT (Binary Optimization and Layout Tool):** Инструмент от Meta для пост-линковочной оптимизации бинарников, улучшающий размещение кода в памяти.
- **SBOM (Software Bill of Materials):** Декларативный перечень всех компонентов и зависимостей, необходимый для аудита безопасности.
- **LTO (Link Time Optimization):** Оптимизация на этапе линковки, анализирующая весь проект целиком.
- **Strip:** Удаление отладочных символов из бинарника для минимизации его размера.

## Базовые концепции

### Особенности сборки C/C++ в контейнерах

*   **Multi-stage:** Обязателен. Сборочное окружение (SDK) в десятки раз тяжелее рантайма. Инструменты сборки никогда не должны попадать в финальный образ.
*   **Длительность сборки:** C++ компилируется медленно. Использование `ccache`, `mold` и параллельной сборки (`ninja`) — стандарт де-факто в 2026 году.
*   **Воспроизводимость:** Используйте флаги удаления путей (`-fdebug-prefix-map` или аналоги в CMake) для получения идентичных бинарников независимо от пути сборки в контейнере.

### Ускорение компиляции (The Gold Standard 2026)

Для достижения минимального времени сборки рекомендуется связка: **BuildKit Cache Mounts + ccache + mold + Ninja**.

1.  **ccache:** Сохраняет результаты компиляции объектных файлов. Требует монтирования `--mount=type=cache`.
2.  **mold:** Устраняет "бутылочное горлышко" этапа линковки. В CMake 3.29+ включается через `CMAKE_LINKER_TYPE=MOLD`.
3.  **Ninja:** Намного эффективнее классического `make` при работе с графами зависимостей в контейнерах.

### Управление зависимостями

| Метод | Использование в Docker | Преимущества |
| :--- | :--- | :--- |
| **Vcpkg** | Рекомендуется | Фиксация версий через `vcpkg.json`, автоматическая генерация SBOM (SPDX). |
| **Conan 2.x** | Рекомендуется | Нативная поддержка CycloneDX 1.6, гибкие профили сборки. |
| **Apt / Apk** | Для простых нужд | Скорость установки, но жесткая привязка к версии дистрибутива. |

### Безопасность и Hardening (Стандарты 2026)

Современные компиляторы (GCC 15+, Clang 18+) поддерживают комплексные флаги защиты:
- **`-fhardened`**: Мета-флаг, включающий набор проверенных практик защиты.
- **`-D_FORTIFY_SOURCE=3`**: Улучшенное обнаружение переполнений буфера (заменяет уровень 2).
- **`-Wl,-z,relro,-z,now`**: Полный RELRO (защита таблиц импорта).
- **`-D_GLIBCXX_ASSERTIONS`**: Проверка границ в стандартной библиотеке (STL).

## Практические сценарии

### Сценарий 1: Эталонная сборка (CMake + ccache + mold + BuildKit)

Максимальная скорость и чистота финального образа на базе Debian.

```dockerfile
# syntax=docker/dockerfile:1.10
# --- Stage 1: Build Environment ---
FROM debian:bookworm-slim AS builder

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build mold ccache libssl-dev git

WORKDIR /build
ENV CCACHE_DIR=/root/.cache/ccache \
    CCACHE_BASEDIR=/build

COPY . .

# Монтируем кэш ccache и собираем с использованием mold
RUN --mount=type=cache,target=/root/.cache/ccache \
    cmake -S . -B out -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
    -DCMAKE_LINKER_TYPE=MOLD && \
    cmake --build out && \
    strip out/my_app

# --- Stage 2: Hardened Runtime ---
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends libssl3 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /build/out/my_app .

RUN useradd -m -u 10001 appuser
USER appuser
ENTRYPOINT ["./my_app"]
```

### Сценарий 2: Статическая сборка на Alpine/Scratch с Hardening

Для создания максимально компактных и безопасных (static) бинарников.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.24 AS builder
RUN apk add --no-cache build-base cmake ninja ccache openssl-dev openssl-libs-static

WORKDIR /app
COPY . .

# Сборка со всеми флагами защиты 2026 года
RUN --mount=type=cache,target=/root/.cache/ccache \
    cmake -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_EXE_LINKER_FLAGS="-static -Wl,-z,relro,-z,now" \
    -DCMAKE_CXX_FLAGS="-fhardened -D_FORTIFY_SOURCE=3 -D_GLIBCXX_ASSERTIONS" \
    . && \
    ninja -C build

# --- Финальный этап ---
FROM scratch
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /app/build/my_app /my_app
ENTRYPOINT ["/my_app"]
```

### Сценарий 3: Экстремальная производительность (PGO + Wolfi)

Использование профилирования и самых безопасных базовых образов.

```dockerfile
# syntax=docker/dockerfile:1
FROM cgr.dev/chainguard/wolfi-base AS sdk
RUN apk add --no-cache build-base cmake clang-18 llvm-18 mold ninja

WORKDIR /src
COPY . .

# 1. Сборка с инструментарием PGO
RUN cmake -B build-pgo -G Ninja -DCMAKE_CXX_FLAGS="-fprofile-generate=/tmp/pgo" && \
    cmake --build build-pgo

# 2. Обучение (запуск тестов или бенчмарков для сбора профиля)
# Это создает файл default.profdata
RUN ./build-pgo/tests --run-full-suite && \
    llvm-profdata merge -output=default.profdata /tmp/pgo/*.profraw

# 3. Финальная оптимизированная сборка
RUN cmake -B build-final -G Ninja \
    -DCMAKE_CXX_FLAGS="-fprofile-use=/src/default.profdata -O3" \
    -DCMAKE_LINKER_TYPE=MOLD && \
    cmake --build build-final

FROM cgr.dev/chainguard/glibc-dynamic:latest
COPY --from=builder /src/build-final/my_app /usr/bin/my_app
USER 65532
ENTRYPOINT ["my_app"]
```

## Верификация и отладка

### Глубокий аудит бинарника

```bash
# 1. Проверка линковки (статическая vs динамическая)
ldd ./my_app
# → not a dynamic executable (успех для static)

# 2. Проверка защиты (NX, PIE, Canary, RELRO)
# Требуется утилита checksec
checksec --file=./my_app

# 3. Сканирование SBOM и уязвимостей
# В 2026 году стандарт CI/CD
trivy image --severity HIGH,CRITICAL my_app:latest
```

## Дополнительная информация

### Подводные камни scratch-образов (Legacy Info preserved)

При использовании `scratch` или `distroless-static` помните:
- **HTTPS:** Необходим файл `/etc/ssl/certs/ca-certificates.crt`.
- **Timezones:** Необходима директория `/usr/share/zoneinfo`.
- **Users:** Если приложение требует юзера, создайте его в builder и скопируйте `/etc/passwd`.
- **DNS:** Если возникают ошибки резолвинга, используйте статическую линковку с `musl` или настройте `nsswitch.conf`.

### Смотрите также

- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — общие стратегии кэширования.
- **[Безопасность в Dockerfile](./security.md)** — глубокий аудит и сканирование CVE.
- **[Инструменты сборки в Linux](../../Linux/Development/build_tools.md)** — подробнее о CMake и ccache.
- **[Dockerfile: Лучшие практики для Rust](./rust.md)** — сравнение с альтернативным системным языком.
- **[Dockerfile: Лучшие практики для Go](./go.md)** — детали работы с `scratch` и статикой.
