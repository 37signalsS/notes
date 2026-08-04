# Dockerfile: Лучшие практики для Go

## Определения

- **Статически скомпонованный бинарник (Statically Linked Binary):** Исполняемый файл, содержащий все необходимые библиотеки (включая рантайм Go). При `CGO_ENABLED=0` он не зависит от системных библиотек (`libc`), что позволяет запускать его в пустых образах (`scratch`).
- **BuildKit:** Современный движок сборки Docker, поддерживающий параллельное выполнение этапов, монтирование кэша и Heredocs.
- **Wolfi / Chainguard:** Современные "un-distro" образы с фокусом на безопасность (0 CVE). Используют `glibc` вместо `musl`, что делает их идеальными для Go-приложений, требующих максимальной производительности или совместимости с C-библиотеками.
- **PGO (Profile-Guided Optimization):** Технология оптимизации компилятора, использующая данные профилирования реальной нагрузки для повышения производительности (обычно на 2–14%).
- **GOEXPERIMENT:** Переменная окружения для включения экспериментальных функций компилятора и рантайма (например, `rangefunc`, `swisslot`).
- **SBOM (Software Bill of Materials):** Декларативный список всех компонентов и зависимостей, входящих в состав образа.
- **FIPS Mode:** Режим работы (обычно через `boringcrypto`), обеспечивающий соответствие стандартам безопасности США (требует специфичной сборки тулчейна).

## Базовые концепции

### Рантайм и контейнеризация (Go 1.25+)

Начиная с **Go 1.25**, рантайм стал полностью "контейнеро-ориентированным" (native container awareness).

*   **Нативный GOMAXPROCS:** Больше не требуется внешняя библиотека `uber-go/automaxprocs`. Go автоматически считывает лимиты CPU из cgroups (v1/v2) и динамически подстраивает количество потоков планировщика (P) при изменении лимитов Kubernetes.
*   **GOMEMLIMIT (Правило 90%):** Go не видит лимит памяти контейнера автоматически. Для предотвращения OOM Kill необходимо устанавливать `GOMEMLIMIT` в значение **80–90%** от лимита RAM контейнера. Оставшиеся 10–20% необходимы для стеков горутин, метаданных рантайма и аллокаций вне кучи.
*   **Green Tea GC (Go 1.26):** Новый алгоритм сборщика мусора, снижающий CPU-оверхед на 10–20% в высоконагруженных контейнерах за счет более агрессивного переиспользования памяти.

### Выбор базового образа (Сравнение 2026)

| Характеристика | Alpine | Distroless (Static) | Wolfi (Chainguard) |
| :--- | :--- | :--- | :--- |
| **Библиотека C** | `musl` (медленнее для Go) | Нет (или `glibc`) | `glibc` (нативно для Go) |
| **Безопасность** | Средняя (CVE фиксы) | Высокая | **Максимальная (0 CVE)** |
| **Удобство** | Есть `sh`, `apk` | Нет ничего | Есть `apk`, non-root |
| **Размер** | ~5–7 MB | ~2–3 MB | ~10–15 MB |

**Рекомендация:** Используйте **Wolfi/Chainguard** для новых проектов как наиболее безопасную и производительную альтернативу с поддержкой `glibc`.

### Оптимизация сборки (PGO и кэширование)

1.  **PGO:** В 2026 году использование PGO считается стандартом для высоконагруженных систем. 
    *   *Процесс:* Соберите образ → запустите под нагрузкой → снимите профиль (`curl http://app/debug/pprof/profile?seconds=30`) → положите файл как `default.pgo` в корень проекта → пересоберите образ. Компилятор подхватит его автоматически.
2.  **Кэширование BuildKit:** Использование `--mount=type=cache` для `/go/pkg/mod` и `~/.cache/go-build` радикально ускоряет сборку, особенно при частом изменении кода.

### Подводные камни минимальных образов (scratch / distroless)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **HTTPS/TLS ошибки** | Нет доверенных CA | Копировать `/etc/ssl/certs/ca-certificates.crt` |
| **Неверное время** | Нет базы `tzdata` | Копировать `/usr/share/zoneinfo` |
| **Permission Denied** | Запуск от root | Создать UID 10001 в builder и скопировать `/etc/passwd` |
| **Binary not found** | Динамическая линковка | `CGO_ENABLED=0` или использование Wolfi (glibc) |
| **DNS Resolving** | Проблемы с `nsswitch.conf` | Использовать нативный Go-резолвер: `export GODEBUG=netdns=go` |

## Практические сценарии

### Сценарий 1: Эталонный Dockerfile (Wolfi + BuildKit + PGO)

Многоэтапная сборка с кэшированием, non-root пользователем и профилированием.

```dockerfile
# syntax=docker/dockerfile:1
ARG GO_VERSION=1.26
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
FROM --platform=$BUILDPLATFORM golang:1.26-alpine AS builder

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

### Сценарий 3: Сборка с CGO (SQLite / Kafka) на Wolfi

Решает проблемы несовместимости `musl` в Alpine при работе с нативными C-библиотеками.

```dockerfile
# syntax=docker/dockerfile:1
FROM cgr.dev/chainguard/go:1.26 AS builder
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

## Верификация и отладка

### Глубокий анализ бинарника

1.  **Проверка статической линковки:**
    ```bash
    ldd ./app 
    # → "not a dynamic executable" — успех для scratch.
    ```
2.  **Проверка на уязвимости (govulncheck):** Обязательный шаг в CI/CD для обнаружения CVE в зависимостях.
3.  **SBOM генерация:** Используйте `syft` или `docker build --sbom` для генерации состава образа.

### Мониторинг в контейнере

В Go 1.26+ используйте встроенный **Flight Recorder** для сбора данных о производительности с минимальным оверхедом:
```go
import "runtime/flightrecorder"
// Инициализация в main() для непрерывного профилирования
```

## Дополнительная информация

### Управление зависимостями: download vs tidy

| Команда | Использование в Docker | Техническая причина |
| :--- | :--- | :--- |
| **`go mod download`** | **Рекомендуется** | Скачивает версии из `go.sum`, не меняя манифест. Идеально для кэширования слоев. |
| **`go mod tidy`** | **Запрещено** | Может изменить `go.mod`, что нарушает воспроизводимость и инвалидирует кэш. |

### Смотрите также

- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — общие принципы кэширования и Multi-stage.
- **[Безопасность в Dockerfile](./security.md)** — аудит, SBOM и сканирование CVE.
- **[Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md)** — работа с манифестами.
- **[Проблема glibc/musl](../../Docker_troubleshooting/alpine_glibc_compatibility.md)** — детали совместимости в Alpine.
- **[Настройка GOMEMLIMIT (Официально)](https://go.dev/doc/gc-guide#Memory_limit)** — руководство по GC.
- **[Выполнение приложений в контейнере](./container_execution.md)** — PID 1 и сигналы.
