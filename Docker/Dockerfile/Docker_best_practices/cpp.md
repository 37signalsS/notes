# Dockerfile: Лучшие практики для C/C++

## Определения

- **Toolchain:** Набор инструментов для компиляции и сборки ПО (компиляторы `gcc`/`clang`, линковщики `ld`/`lld`, системы сборки `make`/`cmake`/`ninja`).
- **Статическая линковка (Static Linking):** Включение всех необходимых библиотек непосредственно в исполняемый файл. Позволяет создавать автономные бинарники, работающие в образе `scratch`.
- **Динамическая линковка (Dynamic Linking):** Использование разделяемых библиотек (`.so`), которые должны присутствовать в операционной системе контейнера в рантайме.
- **LTO (Link Time Optimization):** Метод оптимизации на этапе линковки, позволяющий уменьшить размер бинарника и повысить производительность за счет анализа всего кода целиком.
- **Hardening:** Применение флагов компиляции (например, `Stack Protector`, `PIE`, `ASLR`) для повышения устойчивости приложения к эксплойтам.
- **Strip:** Удаление отладочной информации и таблицы символов из бинарного файла для уменьшения его размера.

## Базовые концепции

### Особенности сборки C/C++ (Компилируемый язык)

*   **Тип:** Компилируемый. Прямая компиляция в машинный код под конкретную архитектуру.
*   **Артефакт:** Исполняемый файл и (опционально) разделяемые библиотеки.
*   **Multi-stage:** Обязателен. Сборочное окружение C++ (компиляторы, заголовочные файлы `-dev`) обычно в 10–50 раз тяжелее финального рантайма.
*   **Длительность сборки:** C++ компилируется медленно. Использование `ccache` и параллельной сборки (`make -j`) критично для CI/CD.

### Использование BuildKit для ускорения компиляции

Современный движок BuildKit позволяет монтировать кэш, который сохраняется между сборками.
- **Кэш компилятора (`ccache`):** Сохраняет результаты компиляции отдельных файлов. Позволяет сократить время повторной сборки на 90%.
- **Кэш зависимостей (`vcpkg`/`conan`):** Предотвращает повторную загрузку и сборку библиотек.

### Управление зависимостями

1.  **Системные пакеты (`apt`, `apk`):** Самый простой путь, но версии библиотек привязаны к дистрибутиву ОС.
2.  **Vcpkg / Conan:** Современные пакетные менеджеры для C++. Позволяют фиксировать версии библиотек независимо от ОС. Требуют кэширования папок установки в Docker.
3.  **Git Submodules:** Исходный код зависимостей копируется в проект. Увеличивает время сборки, но обеспечивает полный контроль.

### Безопасность и Hardening

Для production-образов рекомендуется использовать флаги безопасности (обычно задаются через `CMAKE_CXX_FLAGS`):
- `-fstack-protector-strong`: Защита от переполнения стека.
- `-D_FORTIFY_SOURCE=2`: Обнаружение опасных вызовов функций.
- `-Wl,-z,relro,-z,now`: Защита таблиц линковки (Read-only Relocation).

## Практические сценарии

### Сценарий 1: Оптимальная сборка CMake + ccache + BuildKit

Этот пример демонстрирует максимально быструю сборку за счет кэширования.

```dockerfile
# syntax=docker/dockerfile:1
# --- Этап 1: Сборка (builder) ---
FROM debian:bookworm-slim AS builder

# Установка инструментов и ccache
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    ninja-build \
    ccache \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Настройка путей для ccache
ENV CCACHE_DIR=/root/.ccache
ENV PATH="/usr/lib/ccache:$PATH"

COPY . .

# Монтируем кэш ccache и сборочную директорию build
RUN --mount=type=cache,target=/root/.ccache \
    mkdir build && cd build && \
    cmake -G Ninja -DCMAKE_BUILD_TYPE=Release .. && \
    ninja && \
    strip my_app

# --- Этап 2: Финальный образ ---
FROM debian:bookworm-slim

# Установка только необходимых рантайм-библиотек
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/build/my_app .

# Запуск от пользователя с ограниченными правами
RUN useradd -m -u 10001 appuser
USER appuser

ENTRYPOINT ["./my_app"]
```

### Сценарий 2: Статическая сборка на Alpine с защитой (Hardening)

Создание максимально компактного и защищенного бинарника.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.24 AS builder
RUN apk add --no-cache build-base cmake ninja ccache openssl-dev openssl-libs-static

WORKDIR /app
COPY . .

# Сборка со статической линковкой и флагами безопасности
RUN --mount=type=cache,target=/root/.ccache \
    mkdir build && cd build && \
    cmake -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_EXE_LINKER_FLAGS="-static" \
    -DCMAKE_CXX_FLAGS="-fstack-protector-strong -D_FORTIFY_SOURCE=2" \
    .. && \
    ninja

# --- Финальный этап ---
FROM scratch
# Копируем бинарник, он полностью автономен
COPY --from=builder /app/build/my_app /my_app

# Если приложению нужны CA-сертификаты (HTTPS)
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

ENTRYPOINT ["/my_app"]
```

### Сценарий 3: Интеграция с Vcpkg

Для проектов с большим количеством внешних библиотек.

```dockerfile
# syntax=docker/dockerfile:1
FROM debian:bookworm-slim AS builder
RUN apt-get update && apt-get install -y git curl zip unzip tar pkg-config build-essential cmake
# Установка vcpkg
RUN git clone https://github.com/microsoft/vcpkg.git /opt/vcpkg && \
    /opt/vcpkg/bootstrap-vcpkg.sh

WORKDIR /app
COPY vcpkg.json .

# Кэшируем загрузку и сборку зависимостей vcpkg
RUN --mount=type=cache,target=/root/.cache/vcpkg \
    /opt/vcpkg/vcpkg install

COPY . .
RUN cmake -B build -S . -DCMAKE_TOOLCHAIN_FILE=/opt/vcpkg/scripts/buildsystems/vcpkg.cmake
RUN cmake --build build --config Release
```

### Верификация бинарника

```bash
# 1. Проверка линковки (динамическая или статическая)
ldd ./my_app
# → not a dynamic executable (для статической)

# 2. Проверка флагов безопасности (checksec)
checksec --file=./my_app
# → NX: Enabled, PIE: Enabled, Canary: Enabled
```

## Дополнительная информация

### Смотрите также

- [Оптимизация сборки Docker-образов](./build_optimization.md)
- [Безопасность в Dockerfile](./security.md)
- [Dockerfile: Лучшие практики для Rust](./rust.md) — альтернативный подход к компилируемым языкам
- [Dockerfile: Лучшие практики для Go](./go.md) — детали работы с `scratch` и статикой
