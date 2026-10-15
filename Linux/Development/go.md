# Управление и разработка на Go (Golang) в Linux

**Актуально для:** Go 1.27+

## Определения

* **Go (Golang)** — компилируемый язык программирования с параллельностью на основе goroutine. Обладает статической типизацией, сборщиком мусора и встроенной поддержкой многопоточности.
* **Модуль (Module)** — единица управления зависимостями Go, описываемая в `go.mod`. Содержит набор пакетов и их зависимости с точными версиями.
* **go.mod** — файл манифеста модуля. Определяет имя модуля, версию Go и зависимости (direct и indirect).
* **go.sum** — файл с хешами всех зависимостей. Гарантирует воспроизводимость сборки.
* **GOMAXPROCS** — максимальное количество потоков планировщика, выполняющихся одновременно. В Go 1.25+ автоматически читается из cgroups.
* **CGO_ENABLED** — флаг (`0`/`1`), управляющий использованием C-компилятора. `0` создаёт статический бинарник.
* **GOPATH** — директория для рабочих пространств Go (исторически `~/go`). Современные проекты используют модули, `GOPATH` нужен для `go install`-пакетов.

## Базовые концепции

### Архитектура модулей

Современный workflow Go основан на модулях:

```
myproject/
├── go.mod       # имя модуля, версия Go, зависимости
├── go.sum       # хеши зависимостей
├── main.go      # основной код
└── go.dev/      # (опционально) vendored зависимости
```

### Управление зависимостями

```bash
# Создать новый модуль
go mod init github.com/myuser/myproject

# Добавить зависимость (обновит go.mod и go.sum)
go get github.com/gin-gonic/gin@v1.9.1

# Автоматически добавить и удалить ненужные зависимости
go mod tidy

# Скачать все зависимости в локальный кэш (без изменения go.mod)
go mod download

# Установить утилиту (CLI tool) в $GOPATH/bin
go install github.com/tool/tool@latest

# Включить vendoring (локальная копия зависимостей)
go mod vendor
```

### Сборка и запуск

```bash
# Скомпилировать текущий пакет
go build

# Скомпилировать и указать выходной файл
go build -o myapp .

# Выполнить без создания бинарника (для разработки)
go run main.go

# Установить в $GOPATH/bin
go install ./cmd/myapp
```

### Тестирование и проверка

```bash
# Запуск тестов с покрытием
go test -cover ./...

# Запуск с race detector
go test -race ./...

# Статический анализ (обязательно в CI)
go vet ./...

# Автоматическое форматирование кода
go fmt ./...

# Сборка под другую платформу (кросс-компиляция)
GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -o app-arm64 .
```

## Практические сценарии

### Сценарий 1: Минимальное приложение с Gin

```bash
# Инициализация модуля
go mod init myapp

# Добавление веб-фреймворка
go get github.com/gin-gonic/gin

# Автоматическая очистка зависимостей
go mod tidy

# Запуск в режиме разработки
go run main.go
```

### Сценарий 2: Production-сборка в Docker

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.27-bookworm AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /app/server .

FROM cgr.dev/chainguard/static:latest
COPY --from=builder /app/server /server
USER 65532
ENTRYPOINT ["/server"]
```

Подробнее о Docker-оптимизации Go: [Dockerfile: Лучшие практики для Go](../../Docker/Dockerfile/Docker_best_practices/go.md).

## Дополнительная информация

### GOMAXPROCS и контейнеры

В Go 1.25+ рантайм автоматически считывает лимиты CPU из cgroups, и `GOMAXPROCS` не требует ручной настройки.

### GOMEMLIMIT

Для предотвращения OOM Kill в контейнерах установите:
```bash
export GOMEMLIMIT=450MiB  # 90% от лимита RAM контейнера
```

### Переменные окружения

| Переменная | Описание |
| :--- | :--- |
| `GOPATH` | Рабочее пространство (по умолчанию `~/go`) |
| `GOMODCACHE` | Кэш модулей (`/go/pkg/mod`) |
| `GOCACHE` | Кэш компиляции (`/root/.cache/go-build`) |
| `GOPROXY` | Прокси для скачивания модулей (`https://proxy.golang.org,direct`) |
| `GOSUMDB` | База хешей (`sum.golang.org`) |
| `GOFLAGS` | Флаги по умолчанию для `go build`/`go test` |
| `GOOS`/`GOARCH` | Целевая ОС и архитектура для кросс-компиляции |
| `CGO_ENABLED` | Включение/выключение CGO (`0`/`1`) |

## См. также

- [Инструменты сборки в Linux](./build_tools.md) — общая информация о тулчейнах
- [Dockerfile: Лучшие практики для Go](../../Docker/Dockerfile/Docker_best_practices/go.md) — Production-сборка
