# Dockerfile: Лучшие практики для C/C++

**Актуально для:** C++ toolchain 2026 (GCC 15+/16, Clang 22+, CMake 4.4+, Alpine 3.24)

## Определения

- **Toolchain:** Набор инструментов для компиляции и сборки ПО (компиляторы `gcc`/`clang`, линковщики `ld`/`lld`/`mold`, системы сборки `make`/`cmake`/`ninja`).
- **mold:** Сверхбыстрый современный линковщик, работающий в несколько раз быстрее `lld` и на порядки быстрее классического `ld`. Критичен для сокращения времени сборки крупных проектов в Docker.
- **Статическая линковка (Static Linking):** Включение всех необходимых библиотек непосредственно в исполняемый файл. Позволяет создавать автономные бинарники, работающие в образах `scratch`.
- **Динамическая линковка (Dynamic Linking):** Связывание программы с разделяемыми библиотеками (`.so`) в момент её запуска. Требует совпадения версий `glibc`/`musl` между этапом сборки и финальным образом.
- **musl / glibc:** Два основных варианта реализации стандартной библиотеки C. `musl` используется в Alpine, легковесен, но имеет несовместимости с бинарниками, собранными под `glibc`. `glibc` используется в Debian/Ubuntu/Wolfi, обеспечивает полную совместимость и выше производительность для I/O-bound нагрузок.
- **scratch:** Специальный пустой Docker-образ (`FROM scratch`), не содержащий никаких файлов. Подходит только для полностью статических бинарников. Не имеет shell, пакетного менеджера и CA-сертификатов.
- **Distroless / Distroless-static:** Семейство минималистичных образов от Google, содержащих только приложение и его рантайм-зависимости без shell, пакетных менеджеров и стандартных утилит. Вариант `distroless/static` — для статических бинарников, `distroless/static-debian12` — на базе `glibc`.
- **Wolfi / Chainguard:** Современные "un-distro" образы, ориентированные на безопасность (0 CVE) и использующие `glibc`. Идеальная база для производительных C++ приложений.
- **Hardening:** Применение флагов компиляции (например, `-fhardened`, `Stack Protector`, `Full RELRO`) для повышения устойчивости бинарника к эксплойтам.
- **PGO (Profile-Guided Optimization):** Метод оптимизации, при котором компилятор использует данные реального выполнения программы для ускорения кода. В GCC 15+/16 и Clang 22+ применяется автоматически при наличии файла `default.profdata`.
- **BOLT (Binary Optimization and Layout Tool):** Инструмент от Meta для пост-линковочной оптимизации бинарников, улучшающий размещение кода в памяти.
- **SBOM (Software Bill of Materials):** Декларативный перечень всех компонентов и зависимостей, необходимый для аудита безопасности.
- **LTO (Link Time Optimization):** Оптимизация на этапе линковки, анализирующая весь проект целиком. Позволяет удалять неиспользуемый код и выполнять инлайнинг функций между разными объектными файлами.
- **Strip:** Удаление отладочных символов из бинарника для минимизации его размера.
- **ccache:** Обертка над компилятором для кэширования результатов компиляции объектных файлов. В контейнере монтируется через `--mount=type=cache`.
- **Ninja:** Низкоуровневая система сборки, ориентированная на скорость выполнения. Генерирует минимально необходимый граф зависимостей и оптимизирована для инкрементальных сборок.
- **Conan / Vcpkg:** Современные менеджеры зависимостей для C/C++. Conan 2.x поддерживает CycloneDX 1.6, Vcpkg генерирует SPDX SBOM.
- **BuildKit:** Современный движок сборки Docker, поддерживающий параллельное выполнение этапов, монтирование кэша и Heredocs.
- **Multi-stage Build (Многоэтапная сборка):** Техника использования нескольких инструкций `FROM` в одном файле. Позволяет разделить среду сборки и среду выполнения, исключая инструменты из итогового образа.
- **Cross-compilation (Кросс-компиляция):** Процесс создания бинарного файла под целевую архитектуру/ОС без выполнения кода этой архитектуры во время сборки.
- **QEMU / binfmt_misc:** Механизм эмуляции архитектур в userspace. Используется как fallback, когда нативная кросс-компиляция невозможна.
- **cgroups (Control Groups):** Механизм Linux для ограничения и учёта ресурсов (CPU, память, I/O) для групп процессов. В контексте Docker определяет лимиты контейнера.
- **CPU Throttling:** Ограничение квантов времени процессора ядром при превышении лимитов cgroups, проявляющееся как резкое замедление приложения.
- **OOM Kill (Exit Code 137):** Убийство процесса ядром при превышении лимита памяти (RSS). Приложение не может перехватить `SIGKILL`.
- **FORTIFY_SOURCE:** Мacro, включающий встроенные проверки переполнений буфера в стандартной библиотеке C (`glibc`).
- **Full RELRO:** Режим линковки, при котором таблица relocated-символов (GOT) делается доступной только для чтения во время выполнения, предотвращая перезапись адресов функций.
- **PIE (Position Independent Executable):** Режим компиляции, при котором бинарник загружается по случайному адресу в памяти (ASLR), усложняющий эксплуатацию уязвимостей.
- **Canary (Stack Protector):** Случайное значение, размещаемое на стеке перед адресом возврата. При переполнении буфера канарейка изменяется, и функция завершается вместо передачи управления эксплойту.
- **tcmalloc / jemalloc:** Альтернативные аллокаторы памяти, заменяющие стандартный `malloc` из `glibc`. В контейнерах с жёсткими лимитами RAM часто показывают более предсказуемое поведение и меньше фрагментации.
- **ca-certificates:** Пакет с корневыми сертификатами доверенных центров сертификации (CA). Без него HTTPS-клиенты не смогут проверить цепочку TLS-сертификатов.
- **tzdata:** База данных часовых поясов. Без нее приложения возвращают `unknown location` или используют фиксированный UTC.
- **ldflags:** Параметр компоновщика, передаваемая через `CMAKE_EXE_LINKER_FLAGS` или `LDFLAGS`. Используется для указания `-fuse-ld=mold`, `-Wl,-z,relro`, `-static`.
- **-fdebug-prefix-map:** Флаг GCC/Clang, заменяющий абсолютные пути к исходникам в отладочной информации на относительные или стандартные (`/build/src` → `.`). Критичен для воспроизводимых сборок.
- **-s -w:** Флаги `strip` (`-s` удаляет таблицу символов, `-w` удаляет отладочную информацию DWARF). Сокращают размер бинарника на 20–30%.
- **GOCACHE (ccache equivalent):** В C++ эквивалентом является кэш `ccache` (`/root/.cache/ccache`). В контейнере монтируется через `--mount=type=cache`.
- **.dockerignore:** Файл в корне контекста сборки, задающий исключения. Ускоряет сборку, исключая `.git`, `build/`, `cmake-build-*`, `*.o`, `*.a`.
- **Cache Mount (Монтирование кэша):** Механизм BuildKit (`--mount=type=cache`), сохраняющий данные пакетных менеджеров между сборками без их попадания в итоговый образ.
- **Bind Mount (Монтирование контекста):** Механизм BuildKit (`--mount=type=bind`), предоставляющий доступ к файлам из контекста сборки без их физического копирования в слой образа.
- **Reproducible Build (Воспроизводимая сборка):** Свойство сборки давать идентичный бинарник/образ при одинаковых исходных данных. Достигается через `-fdebug-prefix-map`, `SOURCE_DATE_EPOCH` и pinning базовых образов по дайджесту.
- **SOURCE_DATE_EPOCH:** Переменная окружения (Unix timestamp), фиксирующая метку времени для всех файлов в образе. Используется для получения идентичных дайджестов при повторных сборках.
- **checksec:** Утилита для проверки наличия hardening-флагов (NX, PIE, RELRO, Canary) в ELF-бинарниках.
- **trivy:** Мультиформатный сканер уязвимостей от Aqua Security. Анализирует файловую систему контейнера и SBOM.
- **dive:** Интерактивный инструмент для анализа слоев Docker-образов. Позволяет обнаруживать «мусор», попавший в итоговый образ.
- **syft:** Утилита от Anchore для генерации SBOM в форматах SPDX и CycloneDX.
- **cppcheck / clang-tidy:** Статические анализаторы кода для C/C++. В 2026 году являются обязательным этапом CI/CD для catching неопределённого поведения и уязвимостей до сборки.

## Базовые концепции

### Особенности сборки C/C++ в контейнерах

*   **Multi-stage:** Обязателен. Сборочное окружение (SDK) в десятки раз тяжелее рантайма. Инструменты сборки никогда не должны попадать в финальный образ.
*   **Длительность сборки:** C++ компилируется медленно. Использование `ccache`, `mold` и параллельной сборки (`ninja`) — стандарт де-факто в 2026 году.
*   **Выбор линковки:** Для минимального образа (`scratch`/`distroless`) требуется статическая линковка. Для совместимости с C++17/20 библиотеками (например, `libstdc++`, `libgcc_s`) динамическая линковка на `glibc` (Wolfi/Debian) предпочтительнее.
*   **Воспроизводимость:** Используйте флаги удаления путей (`-fdebug-prefix-map` или аналоги в CMake) для получения идентичных бинарников независимо от пути сборки в контейнере.

### Ускорение компиляции (The Gold Standard 2026)

Для достижения минимального времени сборки рекомендуется связка: **BuildKit Cache Mounts + ccache + mold + Ninja**.

1.  **ccache:** Сохраняет результаты компиляции объектных файлов. Требует монтирования `--mount=type=cache`. В CMake включается через `-DCMAKE_CXX_COMPILER_LAUNCHER=ccache`.
2.  **mold:** Устраняет "бутылочное горлышко" этапа линковки. В CMake 4.4+ включается через `CMAKE_LINKER_TYPE=MOLD`. В ручную через `-DCMAKE_EXE_LINKER_FLAGS="-fuse-ld=mold"`.
3.  **Ninja:** Намного эффективнее классического `make` при работе с графами зависимостей в контейнерах.
4.  **sccache (опционально):** Аналог `ccache` от Mozilla, поддерживающий распределённые кэши (S3, Redis) в CI/CD пайплайнах.

### Рантайм и контейнеризация (C++ в 2026)

C++ приложения в контейнерах подвержены тем же ограничениям, что и любые другие:

*   **cgroups и лимиты памяти:** Go и Java считывают лимиты cgroups автоматически. C++ рантайм (`glibc` malloc, `libc++ allocator`) этого не делает. При превышении лимита RSS процесс получает `SIGKILL` (Exit Code 137). Для предсказуемого поведения используйте `tcmalloc` или `jemalloc`, которые лучше работают с ограниченной памятью.
*   **CPU Throttling:** Если лимит процессора превышен, ядро ограничивает кванты времени. Высоконагруженные C++ сервисы должны проверять `std::thread::hardware_concurrency()` или читать `/sys/fs/cgroup/cpu.max` для адаптации пула потоков.
*   **Аллокаторы памяти:** `glibc` malloc фрагментируется под долгую нагрузку. В Docker рекомендуется связка `tcmalloc` (Google) или `jemalloc` (Facebook) с переменной окружения `LD_PRELOAD` или линковкой на этапе сборки.
*   **Флаги hardening:** Современные компиляторы (GCC 15+/16, Clang 22+) поддерживают комплексную защиту. Все флаги должны применяться на этапе сборки, а не на рантайме.

### Воспроизводимость сборок (Reproducible Builds)

Для получения идентичных дайджестов бинарников и образов:

1.  **Флаг `-fdebug-prefix-map`:** Заменяет абсолютные пути к исходникам в отладочной информации. В CMake: `-DCMAKE_CXX_FLAGS="-fdebug-prefix-map=$(pwd)=."`.
2.  **SOURCE_DATE_EPOCH:** Переменная окружения, фиксирующая временную метку. BuildKit поддерживает её нативно. CMake 3.26+ автоматически использует её для встраивания дат в бинарники.
3.  **Pinning по дайджесту:** Базовые образы фиксируются по SHA256.
4.  **Vendoring / Lock-файлы:** Используйте `conan lock create` или `vcpkg export` для фиксации версий зависимостей.

### .dockerignore для C++

Исключение лишних файлов из контекста сборки радикально ускоряет передачу данных в BuildKit:

```dockerignore
# Системные и служебные директории
.git
.vscode
.idea
build/
cmake-build-*/
out/
tmp
dist

# Кэши и артефакты сборки
*.o
*.a
*.so
*.so.*
*.d
*.profraw
*.profdata
*.pgo

# Зависимости (если не используется vendoring)
vcpkg_installed/
conan/
external/

# Не нужные в контейнере
*.md
LICENSE
.dockerignore
Dockerfile*
docker-compose*
Makefile
Taskfile*
CMakeLists.txt
*.cmake
```

### Управление зависимостями

| Метод | Использование в Docker | Преимущества |
| :--- | :--- | :--- |
| **Vcpkg** | Рекомендуется | Фиксация версий через `vcpkg.json`, автоматическая генерация SBOM (SPDX). |
| **Conan 2.x** | Рекомендуется | Нативная поддержка CycloneDX 1.6, гибкие профили сборки. |
| **Apt / Apk** | Для простых нужд | Скорость установки, но жесткая привязка к версии дистрибутива. |

### Безопасность и Hardening (Стандарты 2026)

Современные компиляторы (GCC 15+/16, Clang 22+) поддерживают комплексные флаги защиты:
- **`-fhardened`**: Мета-флаг, включающий набор проверенных практик защиты.
- **`-D_FORTIFY_SOURCE=3`**: Улучшенное обнаружение переполнений буфера (заменяет уровень 2).
- **`-Wl,-z,relro,-z,now`**: Полный RELRO (защита таблиц импорта).
- **`-D_GLIBCXX_ASSERTIONS`**: Проверка границ в стандартной библиотеке (STL).
- **`-fstack-protector-strong`**: Усиленная защита стека с канарейкой.
- **`-fPIE` / `-pie`**: Position Independent Executable для поддержки ASLR.

### Выбор базового образа (Сравнение 2026)

| Характеристика | Alpine (musl) | Debian Bookworm (glibc) | Distroless (Static) | Wolfi (Chainguard) |
| :--- | :--- | :--- | :--- | :--- |
| **Библиотека C** | `musl` | `glibc` | Нет (или `musl`) | `glibc` (нативно для C++) |
| **Безопасность** | Средняя | Средняя/Высокая | Высокая | **Максимальная (0 CVE)** |
| **Удобство** | Есть `sh`, `apk` | Есть `sh`, `apt` | Нет ничего | Есть `apk`, non-root |
| **Размер** | ~5–7 MB | ~50–70 MB | ~2–3 MB | ~10–15 MB |
| **C++ ABI совместимость** | musl (отличная от glibc) | glibc (стандарт) | Зависит от варианта | glibc (рекомендуется) |
| **Использование** | Легковесные сервисы | Стандартные enterprise-приложения | Максимальная минимизация | **Рекомендуется для новых проектов** |

**Рекомендация:** Используйте **Wolfi/Chainguard** для новых проектов. Для корпоративных сред с требованием привычного Debian-стека выбирайте Debian Bookworm на этапе сборки и `distroless/static-debian12` на рантайме.

### Мультиплатформенная сборка и кросс-компиляция

C++ поддерживает кросс-компиляцию, но требует установки тулчейна под целевую архитектуру:

*   **Архитектуры:** `x86_64`, `aarch64`, `armv7`, `riscv64`, `ppc64le`, `s390x`.
*   **BuildKit аргументы:** При использовании `docker buildx build` с флагом `--platform`, BuildKit автоматически подставляет `TARGETOS` и `TARGETARCH`.
*   **Нативная кросс-компиляция:** CMake +Ninja поддерживают кросс-компиляцию через `toolchain-файлы`. Например, для ARM64: `-DCMAKE_TOOLCHAIN_FILE=../aarch64-linux-gnu.toolchain.cmake`.
*   **Эмуляция (QEMU):** Используется только при отсутствии нативного тулчейна. Требует предустановки `binfmt_misc` и QEMU-утилит на хосте сборщика. Медленнее нативной компиляции в 5–20 раз.
*   **CMake presets (CMake 3.19+):** Рекомендуется использовать `CMakePresets.json` для описания конфигураций кросс-компиляции.

### Оптимизация сборки (PGO, LTO, BOLT и кэширование)

1.  **PGO (GCC):** В 2026 году считается стандартом для высоконагруженных систем.
    *   *Процесс (GCC):* Соберите образ с `-fprofile-generate` → запустите под нагрузкой → снимите профиль (файлы `*.gcda` генерируются автоматически) → пересоберите с `-fprofile-use`.
    *   *Процесс (Clang/LLVM):* Соберите образ с `-fprofile-generate` → запустите под нагрузкой → снимите профиль (`*.profraw`) → объедините через `llvm-profdata merge -o default.profdata *.profraw` → пересоберите с `-fprofile-use=default.profdata`.
    *   *Важно:* При кросс-компиляции профиль должен быть снят под той же архитектурой и ОС.
2.  **BOLT:** Пост-линковочная оптимизация от Meta. Применяется после финальной сборки: `llvm-bolt my_app -o my_app.bolt -reorder-blocks=cache -reorder-functions=hfsort`. Улучшает размещение кода в памяти на 5–15%.
3.  **LTO:** Включается через `-flto=auto` (GCC) или `-flto=thin` (Clang). Сокращает размер бинарника на 10–20% и ускорявает выполнение зачёт инлайнинга.
4.  **Кэширование BuildKit:** Использование `--mount=type=cache` для `/root/.cache/ccache` и `~/.ccache` (если используется sccache). В Conan кэш монтируется в `~/.cache/conan2`.
5.  **Multi-stage оптимальный порядок:**
    1.  `COPY` только манифестов зависимостей (`conanfile.py`, `vcpkg.json`, `CMakeLists.txt`) + кэш mount → установка зависимостей.
    2.  `COPY . .` + сборка.
    3.  Копирование только бинарника и runtime-зависимостей в финальный этап.

### Подводные камни минимальных образов (scratch / distroless / Alpine / Wolfi)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **HTTPS/TLS ошибки** | Нет доверенных CA | Копировать `/etc/ssl/certs/ca-certificates.crt` из builder |
| **Неверное время** | Нет базы `tzdata` | Копировать `/usr/share/zoneinfo` или устанавливать `TZ=UTC` |
| **Permission Denied** | Запуск от root | Создать UID 10001 в builder и скопировать `/etc/passwd` |
| **Binary not found / ODR** | Динамическая линковка `glibc` под `musl` | Статическая линковка (`-static`) или использование Wolfi (glibc) |
| **DNS Resolving** | Проблемы с `nsswitch.conf` / отсутствие `libnss` | Использовать статическую линковку с `musl` или настроить статический DNS |
| **OOM Kill (Exit 137)** | Отсутствие лимита или переполнение кучи | Использовать `tcmalloc`/`jemalloc`, ограничить RSS, мониторить через `valgrind`/`heaptrack` |
| **CPU Throttling** | `std::thread::hardware_concurrency()` выше лимита cgroups | Читать `/sys/fs/cgroup/cpu.max` или адаптировать пул потоков под `nproc` |
| **Отсутствие шрифтов/локали** | Нет `glibc` locale | Копировать `/usr/share/locale` или использовать Wolfi с `glibc` |
| **Крупный размер бинарника** | Отсутствие `strip`, `-s -w`, LTO | Применять `strip`, `-s -w`, LTO, UPX (опционально) |
| **Неопределённое поведение** | Отсутствие статического анализа | Запускать `cppcheck`, `clang-tidy`, AddressSanitizer в CI |

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
RUN apk add --no-cache build-base cmake clang llvm mold ninja

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
COPY --from=sdk /src/build-final/my_app /usr/bin/my_app
USER 65532
ENTRYPOINT ["my_app"]
```

### Сценарий 4: Статическая сборка на `scratch` с CGO (SQLite / librdkafka)

Для приложений, требующих нативные C-библиотеки, но стремящихся к максимальному минимализму.

```dockerfile
# syntax=docker/dockerfile:1
FROM debian:bookworm-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build \
    libsqlite3-dev sqlite3 \
    librdkafka-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

# Статическая линковка со всеми зависимостями
RUN cmake -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_EXE_LINKER_FLAGS="-static" \
    -DCMAKE_CXX_FLAGS="-O3 -D_FORTIFY_SOURCE=3" \
    . && \
    ninja -C build && \
    strip build/my_app

# Финальный этап — пустой образ
FROM scratch

# Обязательные системные файлы
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /usr/share/zoneinfo/ /usr/share/zoneinfo/

COPY --from=builder /app/build/my_app /my_app
USER 10001
ENTRYPOINT ["/my_app"]
```

### Сценарий 5: Контейнер с C++ и CGO на Alpine + SQLite

Альтернативный сценарий для проектов, требующих SQLite через CGO на Alpine/musl.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.24 AS builder
RUN apk add --no-cache \
    build-base cmake ninja \
    sqlite-dev sqlite-libs

WORKDIR /app
COPY . .

RUN cmake -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_EXE_LINKER_FLAGS="-static" \
    . && \
    ninja -C build && \
    strip build/my_app

FROM scratch
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /app/build/my_app /my_app
USER 10001
ENTRYPOINT ["/my_app"]
```

### Сценарий 6: Docker Bake HCL для C++ Multi-stage

Использование `docker-bake.hcl` для управления сложной multi-arch сборкой C++ проектов.

```hcl
# docker-bake.hcl
group "default" {
  targets = ["release"]
}

target "release" {
  platforms = ["linux/amd64", "linux/arm64"]
  tags      = ["registry.example.com/my-app:1.0", "registry.example.com/my-app:latest"]
  
  output = ["type=registry"]
  
  cache-from = ["type=registry,ref=registry.example.com/my-app:cache"]
  cache-to   = ["type=registry,ref=registry.example.com/my-app:cache,mode=max"]
}

target "dev" {
  platforms = ["linux/amd64"]
  tags      = ["my-app:dev"]
  output    = ["type=docker"]
  
  cache-from = ["type=local,src=build-cache"]
  cache-to   = ["type=local,dest=build-cache"]
}
```

```bash
# Запуск сборки
docker buildx bake release

# Локальная разработка
docker buildx bake dev
```

### Сценарий 7: Воспроизводимая сборка с SOURCE_DATE_EPOCH

Фиксация временных меток для получения идентичных дайджестов.

```dockerfile
# syntax=docker/dockerfile:1
FROM debian:bookworm-slim@sha256:d2d7... AS builder

# Фиксируем время сборки для воспроизводимости
ARG SOURCE_DATE_EPOCH=1735689600

RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build ccache && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY . .

RUN --mount=type=cache,target=/root/.cache/ccache \
    cmake -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_FLAGS="-fdebug-prefix-map=/build=." \
    . && \
    ninja -C build && \
    strip build/my_app

FROM debian:bookworm-slim
COPY --from=builder /build/my_app /usr/bin/my_app
RUN useradd -m -u 10001 appuser
USER 10001
ENTRYPOINT ["my_app"]
```

### Сценарий 8: CI/CD пайплайн (govulncheck, syft, trivy)

Полный цикл безопасности и качества для C++ образа.

```yaml
# .github/workflows/cpp-docker.yml
name: C++ Docker CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build-and-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Install tools
        run: |
          sudo apt-get update
          sudo apt-get install -y cppcheck clang-tidy
          
      - name: Static analysis
        run: |
          cppcheck --enable=all --error-exitcode=1 src/
          clang-tidy src/*.cpp --
          
      - name: Build image
        run: |
          docker buildx create --use
          docker buildx build \
            --platform linux/amd64,linux/arm64 \
            --cache-from type=registry,ref=${{ secrets.REGISTRY }}/my-app:cache \
            --cache-to type=registry,ref=${{ secrets.REGISTRY }}/my-app:cache,mode=max \
            --tag ${{ secrets.REGISTRY }}/my-app:${{ github.sha }} \
            --push .
          
      - name: Vulnerability scan
        run: |
          trivy image --severity HIGH,CRITICAL ${{ secrets.REGISTRY }}/my-app:${{ github.sha }}
          
      - name: Generate SBOM
        run: |
          syft ${{ secrets.REGISTRY }}/my-app:${{ github.sha }} \
            -o spdx-json > sbom.spdx.json
```

## Верификация и отладка

### Глубокий аудит бинарника

```bash
# 1. Проверка линковки (статическая vs динамическая)
ldd ./my_app
# → not a dynamic executable (успех для static)

# 2. Проверка архитектуры и ELF-заголовка
file ./my_app
# → ELF 64-bit LSB executable, x86-64, version 1 (SYSV), statically linked

# 3. Проверка защиты (NX, PIE, Canary, RELRO)
checksec --file=./my_app
# → NX: enabled | PIE: enabled | Canary: enabled | RELRO: Full

# 4. Анализ секций и символов
readelf -h ./my_app
readelf -S ./my_app | grep -E "\.text|\.data|\.bss|\.rodata"

# 5. Проверка hardening-флагов
objdump -d -M intel ./my_app | grep -i "stack canary\|fortify"

# 6. Сканирование уязвимостей
trivy image --severity HIGH,CRITICAL my_app:latest

# 7. Анализ слоев образа
dive my_app:latest

# 8. Генерация SBOM
syft my_app:latest -o spdx-json > sbom.json
```

### Диагностика рантайма

```bash
# Проверка аллокаций памяти (требует сборки с debug-символами)
valgrind --tool=massif ./my_app

# Отслеживание вызовов malloc/free
ltrace -c ./my_app

# Проверка динамических библиотек
LD_DEBUG=libs ./my_app

# Мониторинг cgroups (CPU/Memory limits)
cat /sys/fs/cgroup/cpu.max
cat /sys/fs/cgroup/memory.max
cat /sys/fs/cgroup/cpu.stat
```

### Диагностика линковки

```bash
# Разрешение символов (bindings)
LD_DEBUG=bindings ./my_app

# Проверка динамического линковщика
ldd ./my_app
readelf -l ./my_app | grep interpreter

# Проверка зависимостей от системных библиотек
objdump -p ./my_app | grep NEEDED
```

### pprof для C++

Хотя C++ не имеет встроенного `net/http/pprof`, можно использовать:

```bash
# CPU profiling
perf record -g ./my_app
perf report

# Memory profiling
valgrind --tool=massif ./my_app
ms_print massif.out.*

# Tracing
bpftrace -e 'tracepoint:syscalls:sys_enter_* { @[probe] = count(); }'
```

## Дополнительная информация

### Воспроизводимость сборок (Reproducible Builds)

Полный чек-лист для получения идентичных дайджестов:

| Элемент | Действие |
| :--- | :--- |
| **Исходный код** | Git submodules с фиксированными SHA1 |
| **Зависимости** | `conan lock create` или `vcpkg export` с фиксацией версий |
| **Компиляция** | `-fdebug-prefix-map=/build/src=.` |
| **Линковка** | `-Wl,-build-id=none` (отключение Build-ID) |
| **Время** | `SOURCE_DATE_EPOCH=1735689600` |
| **Базовый образ** | Pinning по SHA256 дайджесту |
| **BuildKit** | `--output=type=registry,push=true` с `--metadata` |

### Запуск тестов в multi-stage

C++ тесты должны запускаться в builder-stage, но не попадать в финальный образ:

```dockerfile
# syntax=docker/dockerfile:1
FROM debian:bookworm-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build ccache catch2 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY . .

RUN --mount=type=cache,target=/root/.cache/ccache \
    cmake -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_TESTING=ON \
    . && \
    ninja -C build && \
    ctest --test-dir build --output-on-failure && \
    strip build/my_app

# Финальный этап без тестов и catch2
FROM debian:bookworm-slim
COPY --from=builder /build/my_app /usr/bin/my_app
RUN useradd -m -u 10001 appuser
USER 10001
ENTRYPOINT ["my_app"]
```

### Выбор финального образа (Quick Guide)

| Сценарий | Финальный образ | Обоснование |
| :--- | :--- | :--- |
| **Максимальная безопасность** | `scratch` или `distroless/static` | 0 поверхность атаки |
| **Enterprise / Compliance** | `debian:bookworm-slim` или `wolfi-base` | Знакомый стек, доступ к apt/apk |
| **CGO / динамическая линковка** | `cgr.dev/chainguard/glibc-dynamic` | glibc совместимость |
| **Минимальный размер + glibc** | `wolfi-base` или `distroless/static-debian12` | Баланс размера и совместимости |
| **Отладка / Debug** | `debian:bookworm-slim` с debug-символами | Возможность подключения gdb |

### Оптимизация размера бинарника

Комплексный подход к уменьшению размера:

| Метод | Эффект | Команда |
| :--- | :--- | :--- |
| **Strip** | -20–30% | `strip my_app` или `-s -w` |
| **LTO** | -10–20% | `-flto=auto` |
| **UPX** | -50–70% (с оверхедом старта) | `upx --best my_app` |
| **Статическая линковка** | Убирает .so | `-static` |
| **Без RTTI/Exceptions** | -5–15% | `-fno-rtti -fno-exceptions` |

## Best Practices

### 1. Используйте Exec Form для ENTRYPOINT и CMD

Всегда используйте JSON-форму (`ENTRYPOINT ["/usr/bin/app"]`), чтобы приложение получало PID 1 напрямую и обрабатывало `SIGTERM`/`SIGINT` от Docker/Kubernetes.

### 2. Реализуйте graceful shutdown в коде

C++ приложения в контейнерах должны корректно завершаться по `SIGTERM`:

```cpp
#include <csignal>
#include <atomic>
#include <csignal>

std::atomic<bool> shutdown_requested{false};

void signal_handler(int sig) {
    if (sig == SIGTERM || sig == SIGINT) {
        shutdown_requested = true;
    }
}

int main() {
    std::signal(SIGTERM, signal_handler);
    std::signal(SIGINT, signal_handler);
    
    while (!shutdown_requested) {
        // Основной цикл работы
    }
    
    return 0;
}
```

### 3. Создавайте non-root пользователя с фиксированным UID

Всегда создавайте отдельного пользователя в builder и копируйте `/etc/passwd` в финальный образ:

```dockerfile
RUN useradd -m -u 10001 appuser
COPY --from=builder /etc/passwd /etc/passwd
USER 10001
```

### 4. Пиннингуйте базовые образы по SHA256 дайджесту

Для production используйте дайджесты вместо тегов:

```dockerfile
FROM debian:bookworm-slim@sha256:d2d7... AS builder
FROM cgr.dev/chainguard/static:latest@sha256:abc123... AS runtime
```

### 5. Используйте связку ccache + mold + Ninja

Это стандарт де-факто в 2026 году для ускорения сборки C++ проектов в Docker. В CMake 4.4+ включается через `CMAKE_LINKER_TYPE=MOLD` и `-DCMAKE_CXX_COMPILER_LAUNCHER=ccache`.

### 6. Отключайте CGO, если нет зависимости от C-библиотек

`CGO_ENABLED=0` (Go) или полная статическая линковка (`-static`) для C++ гарантирует автономный бинарник. Если нужна CGO, используйте Wolfi (`glibc`) вместо Alpine (`musl`).

### 7. Верифицируйте hardening-флаги в CI/CD

Запускайте `checksec --file=./my_app` и убедитесь, что включены: NX, PIE, RELRO (Full), Canary. Это requirement для regulated environments.

### 8. Используйте SOURCE_DATE_EPOCH для воспроизводимости

```dockerfile
ARG SOURCE_DATE_EPOCH
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}
```

CMake 3.26+ автоматически использует `SOURCE_DATE_EPOCH` для встраивания дат в бинарники.

### 9. Запускайте тесты в builder-stage

Тесты (catch2, gtest) должны выполняться в builder, но не попадать в финальный образ. Используйте `ctest --output-on-failure` после сборки.

### 10. Мониторинг cgroups throttling

C++ рантайм не считывает лимиты cgroups автоматически. Читайте `/sys/fs/cgroup/cpu.max` и адаптируйте пул потоков под `nproc` или лимит CPU:

```bash
cat /sys/fs/cgroup/cpu.max
cat /sys/fs/cgroup/memory.max
```

### Смотрите также

- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — общие стратегии кэширования.
- **[Безопасность в Dockerfile](./security.md)** — глубокий аудит и сканирование CVE.
- **[Инструменты сборки в Linux](../../../Linux/Development/build_tools.md)** — подробнее о CMake, ccache и mold.
- **[Dockerfile: Лучшие практики для Rust](./rust.md)** — сравнение с альтернативным системным языком.
- **[Dockerfile: Лучшие практики для Go](./go.md)** — детали работы со статической линковкой.
