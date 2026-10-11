# Dockerfile: Лучшие практики для Go

**Актуально для:** Go 1.27

## Определения

- **Статически скомпонованный бинарник (Statically Linked Binary):** Исполняемый файл, содержащий все необходимые библиотеки (включая рантайм Go). При `CGO_ENABLED=0` он не зависит от системных библиотек (`libc`), что позволяет запускать его в пустых образах (`scratch`).
- **Динамически скомпонованный бинарник (Dynamically Linked Binary):** Исполняемый файл, зависящий от разделяемых библиотек (`libc.so.6`, `libm.so.6` и т.д.), присутствующих в базовом образе. Требует совпадения версий `glibc`/`musl` между этапом сборки и финальным образом.
- **CGO_ENABLED:** Переменная окружения, управляющая использованием C-компилятора (`gcc`) в процессе сборки Go. Значение `0` отключает cgo и создает полностью статический бинарник; `1` включает линковку с C-библиотеками (например, `libsqlite3`, `librdkafka`).
- **musl / glibc:** Два основных варианта реализации стандартной библиотеки C. `musl` используется в Alpine, легковесен, но имеет несовместимости с бинарниками, собранными под `glibc`. `glibc` используется в Debian/Ubuntu/Wolfi, обеспечивает полную совместимость и выше производительность для I/O-bound нагрузок.
- **scratch:** Специальный пустой Docker-образ (`FROM scratch`), не содержащий никаких файлов. Подходит только для полностью статических бинарников. Не имеет shell, пакетного менеджера и CA-сертификатов.
- **Distroless:** Семейство минималистичных образов от Google, содержащих только приложение и его рантайм-зависимости без shell, пакетных менеджеров и стандартных утилит. Вариант `distroless/static` — для статических бинарников, `distroless/static-debian12` — на базе `glibc`.
- **Wolfi / Chainguard:** Современные "un-distro" образы с фокусом на безопасность (0 CVE). Используют `glibc` вместо `musl`, что делает их идеальными для Go-приложений, требующих максимальной производительности или совместимости с C-библиотеками.
- **BuildKit:** Современный движок сборки Docker, поддерживающий параллельное выполнение этапов, монтирование кэша и Heredocs.
- **Multi-stage Build (Многоэтапная сборка):** Техника использования нескольких инструкций `FROM` в одном файле. Позволяет разделить среду сборки (с компилятором и зависимостями) и среду выполнения (только бинарник), исключая исходный код и инструменты из итогового образа.
- **Cross-compilation (Кросс-компиляция):** Процесс создания бинарного файла под целевую архитектуру/ОС без выполнения кода этой архитектуры во время сборки. Go поддерживает нативную кросс-компиляцию через переменные `GOOS` и `GOARCH`.
- **Native Cross-compilation:** В контексте Buildx — использование возможностей компилятора Go для создания бинарника под целевую платформу без эмуляции QEMU. Самый быстрый метод мультиплатформенной сборки.
- **QEMU / binfmt_misc:** Механизм эмуляции архитектур в userspace. `binfmt_misc` регистрирует форматы бинарников в ядре, позволяя запускать бинарники одной архитектуры на другой через QEMU. Используется как fallback, когда нативная кросс-компиляция невозможна.
- **GOMAXPROCS:** Переменная окружения, задающая максимальное количество потоков планировщика (P), которые могут выполняться одновременно. В Go 1.25+ рантайм автоматически считывает лимиты CPU из cgroups (v1/v2), делая ручную настройку и библиотеку `uber-go/automaxprocs` избыточной.
- **automaxprocs:** Внешняя библиотека (`uber-go/automaxprocs`), которая ранее переопределяла `GOMAXPROCS` на основе лимитов cgroups. Начиная с Go 1.25, функциональность встроена в рантайм, и библиотека больше не требуется.
- **GOMEMLIMIT:** Переменная окружения, задающая мягкий лимит на использование памяти кучей (heap). Go 1.25+ не видит лимит памяти контейнера автоматически. Для предотвращения OOM Kill необходимо устанавливать `GOMEMLIMIT` в значение **80–90%** от лимита RAM контейнера.
- **GODEBUG=netdns=go:** Переменная окружения, принудительно включающая нативный DNS-резолвер Go вместо системного (`glibc`/`musl`). Критически важна для минимальных образов (`scratch`, `distroless`), где отсутствует `/etc/nsswitch.conf` и `libnss`.
- **nsswitch.conf:** Конфигурационный файл `/etc/nsswitch.conf`, определяющий порядок источников для разрешения имен (DNS, `/etc/hosts`, WINS). В минимальных образах его отсутствие может приводить к ошибкам разрешения имен через системный резолвер.
- **ca-certificates:** Пакет с корневыми сертификатами доверенных центров сертификации (CA). Без него Go (и любые HTTPS-клиенты) не сможет проверить цепочку TLS-сертификатов, что приведет к ошибкам `x509: certificate signed by unknown authority`.
- **tzdata:** База данных часовых поясов. Без нее Go возвращает `time: unknown location` или использует фиксированный UTC, что нарушает логику приложений, зависящих от локального времени.
- **PGO (Profile-Guided Optimization):** Технология оптимизации компилятора, использующая данные профилирования реальной нагрузки для повышения производительности (обычно на 2–14%). В Go 1.21+ применяется автоматически при наличии файла `default.pgo` в корне модуля.
- **GOEXPERIMENT:** Переменная окружения для включения экспериментальных функций компилятора и рантайма (например, `rangefunc`, `swisslot`). Используется только для тестирования нестабильных возможностей, запрещена в production.
- **Flight Recorder:** Встроенный в Go 1.25+ механизм непрерывного низко-оверходного профилирования (`runtime/trace`). Позволяет собирать данные о производительности в production без внешних инструментов вроде `pprof`.
- **govulncheck:** Официальный инструмент Go для статического анализа зависимостей и исходного кода на предмет известных CVE. Рекомендован к обязательному запуску в CI/CD.
- **syft:** Утилита от Anchore для генерации SBOM (Software Bill of Materials) в форматах SPDX и CycloneDX. Поддерживает анализ Go-модулей, Docker-образов и файловых систем.
- **trivy:** Мультиформатный сканер уязвимостей от Aqua Security. Анализирует файловую систему контейнера, зависимости Go (`go.sum`), SBOM и конфигурации IaC.
- **dive:** Интерактивный инструмент для анализа слоев Docker-образов. Позволяет обнаруживать "мусор" (кэши, временные файлы), который попал в итоговый образ.
- **SBOM (Software Bill of Materials):** Декларативный список всех компонентов и зависимостей, входящих в состав образа.
- **Provenance:** Метаданные о процессе сборки образа (кто, когда, на каком узле, с какими параметрами собирал). Входит в состав аттестаций SLSA.
- **SLSA (Supply-chain Levels for Software Artifacts):** Фреймворк для обеспечения безопасности цепочки поставок ПО. Определяет уровни (L1–L4) гарантий целостности артефактов сборки.
- **FIPS Mode:** Режим работы (обычно через `boringcrypto`), обеспечивающий соответствие стандартам безопасности США (требует специфичной сборки тулчейна).
- **ldflags:** Параметр `go build -ldflags`, передающая флаги компоновщику. В Go используется для удаления отладочной информации (`-s -w`) и внедрения версии (`-X main.Version=1.0`).
- **-trimpath:** Флаг `go build`, удаляющий абсолютные пути к файлам системы из бинарника. Улучшает воспроизводимость сборок (reproducible builds).
- **-s -w:** Флаги компоновщика (`-s` удаляет таблицу символов, `-w` удаляет отладочную информацию DWARF). Сокращают размер бинарника на 20–30%.
- **GOCACHE:** Путь к директории кэша компилятора Go (объектные файлы `.o`). В контейнере монтируется через `--mount=type=cache,target=$GOCACHE`.
- **GOMODCACHE:** Путь к директории кэша модулей Go (`/go/pkg/mod`). В контейнере монтируется через `--mount=type=cache,target=$GOMODCACHE`.
- **.dockerignore:** Файл в корне контекста сборки, задающий исключения (аналогично `.gitignore`). Ускоряет сборку, исключая из передачи сборщику `.git`, `vendor`, `dist`, `tmp`, `*.test`.
- **Cache Mount (Монтирование кэша):** Механизм BuildKit (`--mount=type=cache`), сохраняющий данные пакетных менеджеров между сборками без их попадания в итоговый образ.
- **Bind Mount (Монтирование контекста):** Механизм BuildKit (`--mount=type=bind`), предоставляющий доступ к файлам из контекста сборки или других стадий без их физического копирования в слой образа.
- **Reproducible Build (Воспроизводимая сборка):** Свойство сборки давать идентичный бинарник/образ при одинаковых исходных данных. Достигается через фиксацию зависимостей (`go.sum`), `-trimpath`, `SOURCE_DATE_EPOCH` и пinning базовых образов по дайджесту.
- **SOURCE_DATE_EPOCH:** Переменная окружения (Unix timestamp), фиксирующая метку времени для всех файлов в образе. Используется для получения идентичных дайджестов при повторных сборках.

## Базовые концепции

### Рантайм и контейнеризация (Go 1.25+)

Начиная с **Go 1.25**, рантайм стал полностью "контейнеро-ориентированным" (native container awareness).

*   **Нативный GOMAXPROCS:** Больше не требуется внешняя библиотека `uber-go/automaxprocs`. Go автоматически считывает лимиты CPU из cgroups (v1/v2) и динамически подстраивает количество потоков планировщика (P) при изменении лимитов Kubernetes.
*   **GOMEMLIMIT (Правило 90%):** Go не видит лимит памяти контейнера автоматически. Для предотвращения OOM Kill необходимо устанавливать `GOMEMLIMIT` в значение **80–90%** от лимита RAM контейнера. Оставшиеся 10–20% необходимы для стеков горутин, метаданных рантайма и аллокаций вне кучи.
*   **Green Tea GC (Go 1.26):** Новый алгоритм сборщика мусора, снижающий CPU-оверхед на 10–20% в высоконагруженных контейнерах за счет более агрессивного переиспользования памяти.

#### Воспроизводимость сборок (Reproducible Builds)

Для получения идентичных дайджестов бинарников и образов при повторных сборках:

1.  **Фиксация зависимостей:** Используйте `go.sum` и `-mod=vendor` (если vendoring включен).
2.  **Флаг `-trimpath`:** Удаляет абсолютные пути к исходникам из бинарника, предотвращая утечку структуры директорий хоста.
3.  **SOURCE_DATE_EPOCH:** Переменная окружения, фиксирующая временную метку для всех файлов в образе. BuildKit поддерживает ее нативно.
4.  **Pinning по дайджесту:** Базовые образы фиксируются по SHA256 (`cgr.dev/chainguard/go:1.27@sha256:...`), а не по тегу.

#### .dockerignore для Go

Исключение лишних файлов из контекста сборки радикально ускоряет передачу данных в BuildKit:

```dockerignore
# Системные и служебные директории
.git
.vscode
.idea
tmp
dist
bin

# Кэши Go и зависимостей
vendor
go.sum

# Не нужные в контейнере
*.md
LICENSE
.dockerignore
Dockerfile*
docker-compose*
Makefile
Taskfile*
```

### Выбор базового образа (Сравнение 2026)

| Характеристика | Alpine (musl) | Debian Bookworm (glibc) | Distroless (Static) | Wolfi (Chainguard) |
| :--- | :--- | :--- | :--- | :--- |
| **Библиотека C** | `musl` | `glibc` | Нет (или `glibc`) | `glibc` (нативно для Go) |
| **Безопасность** | Средняя | Средняя/Высокая | Высокая | **Максимальная (0 CVE)** |
| **Удобство** | Есть `sh`, `apk` | Есть `sh`, `apt` | Нет ничего | Есть `apk`, non-root |
| **Размер** | ~5–7 MB | ~50–70 MB | ~2–3 MB | ~10–15 MB |
| **Использование** | Легковесные сервисы, CGO с musl | Стандартные enterprise-приложения | Максимальная минимизация | **Рекомендуется для новых проектов** |

**Рекомендация:** Используйте **Wolfi/Chainguard** для новых проектов как наиболее безопасную и производительную альтернативу с поддержкой `glibc`. Для проектов, требующих привычного Debian-окружения, выбирайте `golang:1.27-bookworm` на этапе сборки и `distroless/static-debian12` на рантайме.

### Мультиплатформенная сборка и кросс-компиляция

Go поддерживает нативную кросс-компиляцию без QEMU-эмуляции, что делает его идеальным для multi-arch пайплайнов.

*   **Архитектуры:** `GOARCH` принимает `amd64`, `arm64`, `arm`, `riscv64`, `ppc64le`, `s390x`.
*   **ОС:** `GOOS` принимает `linux`, `darwin`, `windows`, `freebsd`.
*   **BuildKit аргументы:** При использовании `docker buildx build` с флагом `--platform`, BuildKit автоматически подставляет `TARGETOS` и `TARGETARCH`, что избавляет от ручного перечисления.
*   **Эмуляция (QEMU):** Используется только при отсутствии нативной кросс-компиляции или при сборке под `windows`/`darwin`. Требует предустановки `binfmt_misc` и QEMU-утилит на хосте сборщика.

### Оптимизация сборки (PGO и кэширование)

1.  **PGO:** В 2026 году использование PGO считается стандартом для высоконагруженных систем.
    *   *Процесс:* Соберите образ → запустите под нагрузкой → снимите профиль (`curl http://app/debug/pprof/profile?seconds=30`) → положите файл как `default.pgo` в корень проекта → пересоберите образ. Компилятор подхватит его автоматически.
    *   *Важно:* Для корректной работы PGO при кросс-компиляции профиль должен быть снят под той же архитектурой и ОС, под которую собирается бинарник.
2.  **Кэширование BuildKit:** Использование `--mount=type=cache` для `/go/pkg/mod` (`GOMODCACHE`) и `~/.cache/go-build` (`GOCACHE`) радикально ускоряет сборку, особенно при частом изменении кода.
3.  **Multi-stage оптимальный порядок:**
    1.  `COPY go.mod go.sum .` + кэш mount → `go mod download` (инвалидируется только при изменении зависимостей).
    2.  `COPY . .` + сборка.
    3.  Копирование только бинарника в финальный этап.

### Подводные камни минимальных образов (scratch / distroless / Wolfi)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **HTTPS/TLS ошибки** | Нет доверенных CA | Копировать `/etc/ssl/certs/ca-certificates.crt` из builder |
| **Неверное время** | Нет базы `tzdata` | Копировать `/usr/share/zoneinfo` или устанавливать `TZ=UTC` |
| **Permission Denied** | Запуск от root | Создать UID 10001 в builder и скопировать `/etc/passwd` |
| **Binary not found** | Динамическая линковка | `CGO_ENABLED=0` или использование Wolfi (glibc) |
| **DNS Resolving** | Проблемы с `nsswitch.conf` | Использовать нативный Go-резолвер: `export GODEBUG=netdns=go` |
| **OOM Kill (Exit 137)** | Отсутствие `GOMEMLIMIT` | Установить `GOMEMLIMIT=80-90%` от лимита RAM |
| **CPU Throttling** | GOMAXPROCS выше лимита | Go 1.25+ читает cgroups автоматически; проверить через `runtime.NumCPU()` |
| **Отсутствие шрифтов/локали** | Нет `glibc` locale | Копировать `/usr/share/locale` или использовать Wolfi с `glibc` |

## Практические сценарии

### Сценарий 0: Multi-stage на Debian Bookworm + Distroless (Enterprise)

Альтернатива Wolfi для корпоративных сред, где требуется привычный Debian-стек на этапе сборки и максимальная минимизация на рантайме.

```dockerfile
# syntax=docker/dockerfile:1
ARG GO_VERSION=1.27
FROM golang:${GO_VERSION}-bookworm AS builder

WORKDIR /app

# Bind mount для манифестов + кэш модулей
RUN --mount=type=bind,source=go.mod,target=go.mod \
    --mount=type=bind,source=go.sum,target=go.sum \
    --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY . .

# Включаем CGO для совместимости, но собираем статически
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux go build \
    -trimpath \
    -ldflags="-s -w" \
    -o /usr/bin/app .

# Финальный этап: Distroless на glibc (debian12)
FROM gcr.io/distroless/static-debian12:nonroot

# Копируем CA-сертификаты (если нужен HTTPS)
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

COPY --from=builder /usr/bin/app /usr/bin/app

# nonroot уже предустановлен в образе (UID 65532)
USER 65532

ENV GOMEMLIMIT=450MiB
HEALTHCHECK --interval=30s --timeout=3s CMD ["/usr/bin/app", "-health"]
ENTRYPOINT ["/usr/bin/app"]
```

### Сценарий 1: Эталонный Dockerfile (Wolfi + BuildKit + PGO)

Многоэтапная сборка с кэшированием, non-root пользователем и профилированием.

```dockerfile
# syntax=docker/dockerfile:1
ARG GO_VERSION=1.27
FROM cgr.dev/chainguard/go:${GO_VERSION} AS builder

WORKDIR /app

# 1. Кэширование зависимостей (Bind mount для go.mod/sum)
RUN --mount=type=bind,source=go.mod,target=go.mod \
    --mount=type=bind,source=go.sum,target=go.sum \
    --mount=type=cache,target=/go/pkg/mod \
    go mod download

# 2. Копирование кода и PGO профиля
COPY . .

# 3. Сборка с использованием всех оптимизаций
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux go build \
    -trimpath \
    -ldflags="-s -w" \
    -o /usr/bin/app .

# --- Финальный этап ---
FROM cgr.dev/chainguard/static:latest

# Копируем артефакт
COPY --from=builder /usr/bin/app /usr/bin/app

# Пользователь nonroot (UID 65532) уже в образе static
USER 65532

# GOMEMLIMIT (рекомендуется 90% от лимита контейнера)
ENV GOMEMLIMIT=450MiB

# Проверка здоровья
HEALTHCHECK --interval=30s --timeout=3s CMD ["/usr/bin/app", "-health"]

ENTRYPOINT ["/usr/bin/app"]
```

### Сценарий 2: Мультиплатформенная сборка (Buildx)

Сборка под AMD64 и ARM64 с использованием перекрестной компиляции Go.

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.27-alpine AS builder

ARG TARGETOS TARGETARCH
WORKDIR /app
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download
COPY . .

# Использование аргументов TARGETOS и TARGETARCH для кросс-компиляции
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -trimpath -ldflags="-s -w" -o /main .

FROM scratch
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /main /main
USER 10001
ENTRYPOINT ["/main"]
```

### Сценарий 3: Multi-stage на `scratch` с системными зависимостями

Чистый минимализм для ультравысоконагруженных сервисов, где критичен каждый килобайт. Требует ручного копирования CA-сертификатов, базы часовых поясов и файла пользователей.

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.27-bookworm AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux go build \
    -trimpath \
    -ldflags="-s -w" \
    -o /app/server .

# Финальный этап — абсолютно пустой образ
FROM scratch

# Обязательные системные файлы
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /usr/share/zoneinfo/ /usr/share/zoneinfo/

COPY --from=builder /app/server /server
USER 10001
ENV GOMEMLIMIT=400MiB
HEALTHCHECK --interval=30s --timeout=3s CMD ["/server", "-health"]
ENTRYPOINT ["/server"]
```

### Сценарий 4: Сборка с CGO (SQLite / Kafka) на Wolfi

Решает проблемы несовместимости `musl` в Alpine при работе с нативными C-библиотеками.

```dockerfile
# syntax=docker/dockerfile:1
FROM cgr.dev/chainguard/go:1.27 AS builder
RUN apk add --no-cache build-base librdkafka-dev

WORKDIR /app
COPY . .
# Включаем CGO и линкуем необходимые библиотеки
RUN --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=1 go build -trimpath -ldflags="-w -s" -o /app/service .

FROM cgr.dev/chainguard/glibc-dynamic:latest
# Установка рантайм-зависимостей
RUN apk add --no-cache librdkafka
COPY --from=builder /app/service /usr/bin/service
USER 65532
ENTRYPOINT ["/usr/bin/service"]
```

### Сценарий 5: Сборка с CGO на Alpine (SQLite)

Практичный паттерн для Go-приложений, использующих `modernc.org/sqlite` или `go-sqlite3`. Alpine с `musl` совместим с CGO при использовании `build-base`.

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.27-alpine AS builder

# Установка C-компилятора и заголовков
RUN apk add --no-cache build-base sqlite-dev

WORKDIR /app
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY . .
# CGO_ENABLED=1 обязательно для SQLite
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=1 go build \
    -trimpath -ldflags="-s -w" \
    -o /app/server .

# Финальный этап: минимальный Alpine
FROM alpine:3.24
RUN apk add --no-cache sqlite-libs
COPY --from=builder /app/server /server
RUN addgroup -S appgroup -g 1001 && adduser -S appuser -G appgroup -u 1001
USER 1001
ENTRYPOINT ["/server"]
```

### Сценарий 6: Декларативная сборка через Docker Bake

Инструмент `docker bake` позволяет вынести параметры сборки в HCL/JSON-файл, что удобно для поддержки нескольких конфигураций (dev/prod, multi-arch).

**`docker-bake.hcl`:**
```hcl
target "app" {
  contexts = {
    builder = "docker-image://docker.io/docker/dockerfile:1"
  }
  tags = ["myreg.com/app:1.2.3", "myreg.com/app:latest"]
  platforms = ["linux/amd64", "linux/arm64"]
  outputs = ["type=image,name=myreg.com/app:1.2.3,push=true"]
  cache-from = ["type=registry,ref=myreg.com/app:cache"]
  cache-to = ["type=registry,ref=myreg.com/app:cache,mode=max"]
  sbom = true
  provenance = true
}

target "app-dev" {
  inherits = ["app"]
  tags = ["myreg.com/app:dev"]
  platforms = ["linux/amd64"]
  cache-to = ["type=local,dest=tmp-buildcache"]
}
```

**Запуск:**
```bash
docker buildx bake app            # prod
docker buildx bake app-dev        # dev с локальным кэшем
```

### Сценарий 7: Reproducible Build с SOURCE_DATE_EPOCH

Фиксация временных меток для получения идентичных дайджестов при повторных сборках из одного коммита.

```dockerfile
# syntax=docker/dockerfile:1
ARG GO_VERSION=1.27
FROM golang:${GO_VERSION}-bookworm AS builder

# Фиксируем метку времени (например, timestamp коммита)
ARG SOURCE_DATE_EPOCH=1724200000

WORKDIR /app
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}

COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux go build \
    -trimpath \
    -ldflags="-s -w -buildid=" \
    -o /app/server .

# Финальный этап
FROM cgr.dev/chainguard/static:latest
COPY --from=builder /app/server /server
USER 65532
ENTRYPOINT ["/server"]
```

**Запуск:**
```bash
SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) docker buildx build --platform linux/amd64 -t myapp:1.0.0 .
```

### Сценарий 8: CI/CD пайплайн с govulncheck, syft, trivy

Полный цикл проверки безопасности в GitHub Actions.

```yaml
# .github/workflows/docker-go.yml
name: Build and Scan Go Docker Image

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

      - name: Cache Go modules
        uses: actions/cache@v4
        with:
          path: |
            ~/.cache/go-build
            ~/go/pkg/mod
          key: go-mod-${{ hashFiles('go.sum') }}

      - name: Install govulncheck
        run: go install golang.org/x/vuln/cmd/govulncheck@latest

      - name: Check vulnerabilities
        run: govulncheck ./...

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
```

## Верификация и отладка

### Глубокий анализ бинарника

1.  **Проверка статической линковки:**
    ```bash
    ldd ./app 
    # → "not a dynamic executable" — успех для scratch/distroless static.
    ```
    Для детального анализа используйте `readelf` или `objdump`:
    ```bash
    readelf -h ./app | grep "Type:"
    # → "Type: EXEC (Executable file)" — бинарник готов к запуску
    ```
2.  **Проверка архитектуры и ОС:**
    ```bash
    file ./app
    # → ./app: ELF 64-bit LSB executable, ARM aarch64, version 1 (SYSV), statically linked
    ```
    В Go также можно проверить целевую архитектуру:
    ```bash
    go env GOARCH
    # → arm64
    ```
3.  **Проверка уязвимостей (govulncheck):** Обязательный шаг в CI/CD для обнаружения CVE в зависимостях и исходном коде.
    ```bash
    govulncheck ./...
    # → No vulnerabilities found.
    ```
4.  **Проверка рантайм-параметров:** Вставьте в `main()` диагностику для подтверждения корректной работы в контейнере:
    ```go
    fmt.Printf("GOMAXPROCS=%d, NumCPU=%d, HeapAlloc=%d\n",
        runtime.GOMAXPROCS(0),
        runtime.NumCPU(),
        memStats.HeapAlloc)
    ```
5.  **SBOM генерация:** Используйте `syft` или `docker build --sbom` для генерации состава образа.
    ```bash
    # Анализ готового образа
    syft myapp:latest -o spdx-json > sbom.spdx.json
    
    # Анализ файловой системы
    syft dir:/path/to/app -o cyclonedx-json > sbom.cdx.json
    ```
6.  **Сканирование уязвимостей образа (Trivy):**
    ```bash
    trivy image myapp:latest --severity HIGH,CRITICAL
    # → Проверяет ОС-пакеты (если есть) и Go-зависимости
    ```
7.  **Анализ слоев (dive):** Визуальный инструмент для поиска неожиданных файлов в слоях.
    ```bash
    dive myapp:latest
    # → Позволяет просматривать каждый слой и сравнивать размеры
    ```

### Мониторинг в контейнере

В Go 1.25+ используйте встроенный **Flight Recorder** для сбора данных о производительности с минимальным оверхедом:

```go
import "runtime/trace"

func init() {
    fr := trace.NewFlightRecorder(trace.FlightRecorderConfig{
        MinAge:   100 * time.Millisecond,
        MaxBytes: 1 << 20,
    })
    if err := fr.Start(); err != nil {
        log.Fatalf("failed to start flight recorder: %v", err)
    }
}
```

Также доступен классический `net/http/pprof` для интерактивного профилирования:

```go
import _ "net/http/pprof"

func main() {
    go func() {
        log.Println(http.ListenAndServe("localhost:6060", nil))
    }()
    // ... запуск сервера
}
```
Снимайте профиль:
```bash
curl http://localhost:6060/debug/pprof/profile?seconds=30 > cpu.pb.gz
go tool pprof -http=:8080 cpu.pb.gz
```

## Best Practices

### 1. Используйте Exec Form и неявный сигнал завершения

Всегда используйте JSON-форму для `ENTRYPOINT` и `CMD`, чтобы Go-приложение получало PID 1 напрямую и обрабатывало `SIGTERM`/`SIGINT` от Docker/Kubernetes:

```dockerfile
ENTRYPOINT ["/usr/bin/app"]
CMD ["serve"]
```

Для multi-process сценариев или если приложение spawning дочерние процессы, используйте `docker run --init` или добавьте `tini`:

```dockerfile
# Копирование tini из builder
COPY --from=docker.io/docker/dockerfile:1.9.7 /docker-init /usr/local/bin/docker-init
ENTRYPOINT ["/usr/local/bin/docker-init", "--", "/usr/bin/app"]
```

### 2. Реализуйте graceful shutdown в коде

Go-приложения в контейнерах должны корректно завершаться по `SIGTERM` (дефолт для `docker stop` и `kubectl delete`):

```go
func main() {
    ctx, stop := signal.NotifyContext(context.Background(),
        syscall.SIGINT, syscall.SIGTERM)
    defer stop()

    srv := &http.Server{Addr: ":8080", Handler: router}

    go func() {
        <-ctx.Done()
        shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
        defer cancel()
        srv.Shutdown(shutdownCtx)
    }()

    if err := srv.ListenAndServe(); err != http.ErrServerClosed {
        log.Fatal(err)
    }
}
```

### 3. Приватный пользователь без оболочки

Всегда создавайте отдельного non-root пользователя в builder и копируйте `/etc/passwd` в финальный образ. Для `scratch` и `distroless` используйте фиксированный UID (например, `65532` для distroless, `10001` для scratch):

```dockerfile
RUN groupadd -g 65532 appgroup && useradd -u 65532 -g appgroup appuser
COPY --from=builder /etc/passwd /etc/passwd
USER 65532
```

### 4. Пиннинг базовых образов по дайджесту

Для production используйте SHA256-дайджесты вместо тегов. Это исключает недетерминированные сборки при обновлении upstream-образа:

```dockerfile
FROM golang:1.27@sha256:abc123... AS builder
FROM cgr.dev/chainguard/static:latest@sha256:def456... AS runtime
```

### 5. Ограничения ресурсов и GOMEMLIMIT

Всегда задавайте лимиты памяти в оркестраторе и синхронизируйте `GOMEMLIMIT`:

| Сценарий | memory limit | GOMEMLIMIT | GOMAXPROCS |
| :--- | :--- | :--- | :--- |
| CPU-bound сервис | 256 MiB | 200 MiB | auto (Go 1.25+) |
| I/O-bound сервис | 512 MiB | 450 MiB | auto (Go 1.25+) |
| Памятоемкий (кэши) | 1 GiB | 900 MiB | auto (Go 1.25+) |

**Важно:** Go 1.25+ автоматически считывает `cpu.cfs_quota_us` и `cpu.cfs_period_us` из cgroups v1/v2. `GOMAXPROCS` настраивать вручную не требуется. Для cgroups v2 с `cpu.max` (BFQ/EAS) поведение аналогично.

### 6. Отключите CGO, если нет зависимости от C-библиотек

`CGO_ENABLED=0` — единственный способ гарантировать статический бинарник для `scratch` и `distroless/static`. Если нужна CGO, используйте Wolfi (`glibc`) вместо Alpine (`musl`) для совместимости.

### 7. Верификация каждой сборки

- **Статическая линковка:** `ldd ./app` → `not a dynamic executable`
- **Архитектура:** `file ./app` → ожидаемая arch
- **Уязвимости:** `govulncheck ./...` + `trivy image`
- **Состав:** `syft` или `docker build --sbom`
- **Слои:** `dive myapp:latest`

### 8. Используйте SOURCE_DATE_EPOCH для воспроизводимости

```dockerfile
ARG SOURCE_DATE_EPOCH
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}
```

Запуск: `SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) docker buildx build ...`

### 9. SBOM и Provenance в CI/CD

Включите `--sbom` и `--provenance` в `docker buildx build` или через Docker Bake. Это requirement для SLSA L2+ и regulated environments (PCI DSS, SOC 2).

```bash
docker buildx build \
  --sbom true \
  --provenance mode=max \
  --push \
  -t myreg.com/app:1.0.0 .
```

### 10. Мониторинг cgroups throtelling

В Go 1.25+ проверяйте runtime через встроенные средства:

```go
var ms runtime.MemStats
runtime.ReadMemStats(&ms)
log.Printf("GOMAXPROCS=%d NumCPU=%d HeapAlloc=%d",
    runtime.GOMAXPROCS(0), runtime.NumCPU(), ms.HeapAlloc)
```

Для диагностики throttling на уровне узла:

```bash
cat /sys/fs/cgroup/cpu.stat
# → nr_throttled: 42
# → throttled_time: 123456789
```

## Edge Cases

### Кросс-компиляция с вариантами архитектуры

Для multi-arch пайплайнов используйте `TARGETVARIANT` вместе с `TARGETOS`/`TARGETARCH`:

```dockerfile
ARG TARGETOS TARGETARCH TARGETVARIANT
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH GOARM=$TARGETVARIANT \
    go build -trimpath -ldflags="-s -w" -o /app/main .
```

| Архитектура | Вариант | Пример `TARGETVARIANT` | Комментарий |
| :--- | :--- | :--- | :--- |
| `arm` | `GOARM` | `7` | ARMv7 ( Raspbian ) |
| `amd64` | `GOAMD64` | `v3` | AVX2, BMI2 (Intel Haswell+, AMD Zen+) |
| `ppc64` | `GOPPC64` | `power9` | PowerPC 64-bit LE |
| `riscv64` | `GORISCV64` | `rva20u64` | RISC-V Vector |

**Важно:** PGO-профиль должен быть снят под той же `GOARCH`/`GOAMD64`, под которую собирается бинарник. Нельзя использовать профиль с `amd64/v1` для сборки под `amd64/v4`.

### CGO с динамической линковкой в multi-stage

Если CGO включен и используется динамическая линковка (например, `libsqlite3.so`), финальный образ должен содержать все зависимости:

```dockerfile
FROM cgr.dev/chainguard/glibc-dynamic:latest
RUN apk add --no-cache sqlite-libs
COPY --from=builder /app/service /usr/bin/service
# Проверка зависимостей:
# ldd /usr/bin/service
```

### Обратная совместимость CGO с Alpine

Для Alpine (`musl`) с CGO требуются `build-base` и соответствующие `-dev` пакеты. Статически слинкованный бинарник (`CGO_ENABLED=0`) несовместим с библиотеками, собранными под `glibc`:

```dockerfile
FROM golang:1.27-alpine AS builder
RUN apk add --no-cache build-base sqlite-dev
RUN CGO_ENABLED=1 go build -o /app/server .
FROM alpine:3.24
RUN apk add --no-cache sqlite-libs
COPY --from=builder /app/server /server
```

### Отладка production-образов

Для `scratch` и `distroless` нет shell. Используйте `docker debug` (Docker Desktop 4.33+) или эфемерные контейнеры:

```bash
docker debug myapp:latest
# → предоставляет shell с Nix Toolbox в namespace контейнера
```

Для Kubernetes используйте `kubectl debug`:

```bash
kubectl debug -it --image=busybox:1.36 --target=myapp-pod
```

### Слишком большие бинарники

Go-бинарники со включенным CGO и отладочной информацией могут превышать 100 MB. Оптимизации:

1. **Уберите отладку:** `-ldflags="-s -w"` (-20-30%)
2. **Установите GOMEMLIMIT:** предотвращает неконтролируемый рост heap
3. **Включите UPX** (опционально, для production):
   ```dockerfile
   RUN apk add --no-cache upx
   RUN upx --best --lzma /app/server
   ```
   **Предупреждение:** UPX unpacking добавляет overhead при старте (~10-50 ms) и может быть заблокирован security policy.

### Обработка нескольких сигналов

Go 1.27+ поддерживает `signal.NotifyContext`. Для приложений с фоновыми воркерами (goroutines) используйте `errgroup` для скоординированной остановки:

```go
g, ctx := errgroup.WithContext(context.Background())
g.Go(func() error { return worker1(ctx) })
g.Go(func() error { return worker2(ctx) })
<-ctx.Done()
g.Wait()
```

### Дублирование content в модуле

Если модуль содержит main-пакет и библиотеку, используйте `go build -o` явно, чтобы избежать неожиданного поведения:

```dockerfile
RUN go build -trimpath -ldflags="-s -w" -o /usr/bin/app ./cmd/server
```

## Дополнительная информация

### Управление зависимостями: download vs tidy

| Команда | Использование в Docker | Техническая причина |
| :--- | :--- | :--- |
| **`go mod download`** | **Рекомендуется** | Скачивает версии из `go.sum`, не меняя манифест. Идеально для кэширования слоев. |
| **`go mod tidy`** | **Запрещено** | Может изменить `go.mod`, что нарушает воспроизводимость и инвалидирует кэш. |

### Кэширование BuildKit для Go

Переменные окружения `GOCACHE` и `GOMODCACHE` задают пути к кэшам компилятора и модулей. Их монтирование через `type=cache` ускоряет повторные сборки:

```dockerfile
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go build ./...
```

*   **`/go/pkg/mod`** (`GOMODCACHE`): Кэш скачанных модулей. Уменьшает время `go mod download` при изменении зависимостей.
*   **`/root/.cache/go-build`** (`GOCACHE`): Кэш скомпилированных пакетов (`.a` файлы). Ускоряет перекомпиляцию при изменении только одного пакета.

**Важно:** Никогда не монтируйте `type=cache` для директории с исходным кодом (`/app`). Это сломает инвалидацию кэша при изменении кода.

### Флаги сборки go build

| Флаг | Назначение | Эффект |
| :--- | :--- | :--- |
| **`-trimpath`** | Удаляет абсолютные пути из бинарника | Улучшает воспроизводимость, не leaking структуры хоста |
| **`-ldflags="-s -w"`** | Передает флаги компоновщику | Удаляет таблицу символов и DWARF-отладку, уменьшая размер на 20–30% |
| **`-ldflags="-buildid="`** | Очищает build ID | Повышает воспроизводимость при использовании `SOURCE_DATE_EPOCH` |
| **`-o /path/binary`** | Явно задает путь выходного файла | Позволяет контролировать расположение артефакта в multi-stage |
| **`CGO_ENABLED=0`** | Отключает CGO | Гарантирует статическую линковку, подходит для `scratch` |
| **`CGO_ENABLED=1`** | Включает CGO | Требуется для `libsqlite3`, `librdkafka`, системных вызовов |

### Cross-compilation параметры

Go поддерживает нативную кросс-компиляцию через переменные окружения:

```bash
# Пример: сборка под ARM64 из Linux/amd64
GOOS=linux GOARCH=arm64 GOARM=8 CGO_ENABLED=0 go build -o app-arm64 .
```

В BuildKit/Docker Buildx аргументы `TARGETOS`/`TARGETARCH` заполняются автоматически:

```dockerfile
FROM --platform=$BUILDPLATFORM golang:1.27-bookworm AS builder
ARG TARGETOS TARGETARCH TARGETVARIANT
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH GOARM=$TARGETVARIANT \
    go build -o /app/main .
```

### Vendor-директория

Для полной независимости от внешних сетей во время сборки используйте vendoring:

```bash
go mod vendor
```

В Dockerfile:
```dockerfile
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY vendor ./vendor
RUN CGO_ENABLED=0 go build -mod=vendor -o /app .
```

Ввод `-mod=vendor` заставляет компилятор использовать локальную директорию `vendor`, исключая обращение к сети или `GOMODCACHE`.

### Запуск тестов в Multi-stage

Для ускорения CI тесты можно запускать в отдельном промежуточном этапе, не включая их в финальный образ:

```dockerfile
FROM golang:1.27-bookworm AS tester
WORKDIR /app
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN go test -race -coverprofile=coverage.out ./...

FROM golang:1.27-bookworm AS builder
# ... сборка
```

Или используйте `docker buildx build --target=tester` для изолированного запуска тестов.

### Выбор финального образа: краткий гид

| Сценарий | Финальный образ | Преимущество |
| :--- | :--- | :--- |
| Максимальная безопасность, нет CGO | `scratch` | 0 байт поверх бинарника |
| Максимальная безопасность, есть CGO | `cgr.dev/chainguard/static` | glibc, non-root, 0 CVE |
| Enterprise, привычный стек | `gcr.io/distroless/static-debian12` | Debian-совместимость, 0 shell |
| Отладка, нужно `sh`/`apk` | `golang:1.27-bookworm` | Полный debug-инструментарий |
| Легковесный Alpine | `alpine:3.24` | `apk`, `sh`, но musl-риски |

### Смотрите также

- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — общие принципы кэширования и Multi-stage.
- **[Безопасность в Dockerfile](./security.md)** — аудит, SBOM и сканирование CVE.
- **[Выполнение приложений в контейнере](./container_execution.md)** — PID 1 и сигналы.
