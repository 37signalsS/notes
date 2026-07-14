# Dockerfile: Лучшие практики для Go

## Определения

- **Статически скомпонованный бинарник (Statically Linked Binary):** Исполняемый файл, который содержит в себе все необходимые библиотеки и не зависит от разделяемых библиотек в операционной системе. Это делает его полностью переносимым.

## Базовые концепции

### Система модулей: go.mod и go.sum

Файлы `go.mod` и `go.sum` используются для управления зависимостями и обеспечения воспроизводимости сборок.

*   **`go.mod`**: Основной манифест. Описывает имя модуля, версию Go и список зависимостей.
*   **`go.sum`**: Содержит контрольные суммы (хеши) зависимостей для проверки их целостности.

| Язык | Манифест зависимостей | Фиксация версий / Хеши |
| :--- | :--- | :--- |
| **Go** | `go.mod` | `go.sum` |
| **Node.js** | `package.json` | `package-lock.json` |
| **Python** | `pyproject.toml` / `requirements.txt` | `poetry.lock` / `Pipfile.lock` |
| **Java** | `pom.xml` | — |

### Управление зависимостями: download vs tidy

В Docker-контейнерах и CI/CD крайне важно использовать правильные команды для работы с модулями.

| Команда | Назначение | Использование в Docker |
| :--- | :--- | :--- |
| **`go mod download`** | Только скачивание зависимостей из `go.mod`. Не меняет файлы проекта. | **Рекомендуется.** Гарантирует воспроизводимость. |
| **`go mod tidy`** | Анализ кода, удаление лишнего и добавление нового. Меняет `go.mod` и `go.sum`. | **Не рекомендуется.** Docker должен собирать, а не менять проект. |

**Важное правило:** Если `go.sum` отсутствует в репозитории (плохая практика), используйте `COPY go.mod ./` и `go mod download`. Но для безопасности и предсказуемости `go.sum` **обязательно** должен быть закоммичен.

### Определение версии Go

Версия языка всегда фиксируется в основном манифесте зависимостей:

*   **`go.mod`**: Версия указана в первой части файла после объявления модуля.
    ```go
    module github.com/user/repo
    go 1.22.0
    ```

### Подход к созданию образов для Go

Экосистема Go идеально подходит для [многоэтапных сборок](./build_optimization.md). Благодаря способности компилятора Go создавать полностью автономные статические бинарники, стандартным паттерном является:

1. **Этап "builder":** Использование полного `golang` образа, содержащего **SDK (Software Development Kit — набор инструментов разработки)** и все инструменты для компиляции и сборки зависимостей.
2. **Этап "final":** Копирование единственного скомпилированного бинарника в минималистичный финальный образ, такой как [`scratch`](./security.md) или [`distroless`](./security.md).

### Подводные камни scratch-образов

Использование `FROM scratch` дает минимальный размер, но лишает приложение системных ресурсов.

| Проблема | Причина | Последствие | Решение |
| :--- | :--- | :--- | :--- |
| **HTTPS запросы** | Нет CA-сертификатов | Ошибка проверки SSL/TLS | Копировать сертификаты из builder |
| **Часовые пояса** | Нет `/usr/share/zoneinfo` | `time.LoadLocation()` упадет | Копировать `tzdata` из builder |
| **CGO / SQLite** | Требуется динамическая линковка | Бинарник не запустится | `CGO_ENABLED=0` или статическая линковка |
| **Пользователи** | Нет `/etc/passwd` | `USER appuser` упадет | Скопировать `/etc/passwd` из builder |

### Проблема совместимости `glibc` и `musl`

При многоэтапной сборке, когда на этапе сборки используется стандартный дистрибутив (например, `golang:1.26-bookworm` на базе Debian с `glibc`), а на финальном — `alpine` (который использует `musl libc`), может возникнуть ошибка `no such file or directory`. Это происходит из-за несовместимости системных библиотек. Решение — компиляция полностью статического бинарника с флагами `-ldflags '-extldflags "-static"'`. Подробности: [Проблема несовместимости libc (Alpine)](../../Docker_troubleshooting/alpine_glibc_compatibility.md).

## Практические сценарии

### Сценарий 1: Сборка с `scratch` (Полная конфигурация)

Этот пример учитывает все типичные проблемы минималистичных образов:

```dockerfile
# --- Этап 1: Builder ---
FROM golang:1.26-alpine AS builder
# Устанавливаем сертификаты и часовые пояса
RUN apk add --no-cache ca-certificates tzdata
# Создаем непривилегированного пользователя
RUN adduser -D -S -u 10001 appuser
WORKDIR /app

# Оптимизация кэширования: сначала только модули
COPY go.mod go.sum ./
# Используем download для стабильности сборки
RUN go mod download

# Копируем исходный код только ПОСЛЕ скачивания зависимостей
COPY . .
# Собираем статически скомпонованный бинарник
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags "-w -s" -o main .

# --- Этап 2: Финальный образ ---
FROM scratch
# Копируем системные файлы из builder
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo
COPY --from=builder /app/main /main

USER appuser
EXPOSE 9292
ENTRYPOINT ["/main"]
```

### Сценарий 2: Сборка с `distroless` (Прагматичный выбор)

`distroless`-образы — отличный компромисс. Они немного больше, чем `scratch`, но включают базовые вещи, которые могут понадобиться приложению, например, **CA-сертификаты (Certificate Authority — центр сертификации)** для работы с TLS/HTTPS и информацию о часовых поясах, сохраняя при этом высокий уровень безопасности (в них нет shell). Отсутствие shell усложняет отладку — руководство по решению этой проблемы см. [Отладка distroless-контейнеров](../../Docker_troubleshooting/debugging_distroless.md).

```dockerfile
# --- Этап 1: Сборка ---
FROM golang:1.26-bookworm as builder
WORKDIR /app
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o my-app .

# --- Этап 2: Создание финального образа ---
# Используем distroless-образ для статически скомпонованных приложений
FROM gcr.io/distroless/static-debian12
COPY --from=builder /app/my-app /
CMD ["/my-app"]
```

### Сценарий 3: Сборка с поддержкой CGO (Alpine)

Используется, если приложению требуются C-библиотеки (например, `go-sqlite3`). Требует установки инструментов компиляции в builder и использования Alpine (или Debian) в финальном образе для совместимости с `libc`.

```dockerfile
# --- Этап 1: Builder ---
FROM golang:1.24-alpine AS builder

# Установка зависимостей для компиляции C-кода
RUN apk add --no-cache gcc musl-dev

# Создаем пользователя заранее
RUN adduser -D -S -u 10001 appuser

WORKDIR /app

# Кэширование зависимостей
COPY go.mod go.sum ./
RUN go mod download

COPY . .

# Собираем с включенным CGO
# -a: принудительная пересборка всех пакетов
RUN CGO_ENABLED=1 go build -a -ldflags "-w -s" -o /app/main .

# --- Этап 2: Final ---
FROM alpine:3.24

# Сертификаты для HTTPS и данные о часовых поясах
RUN apk add --no-cache ca-certificates tzdata

# Создаем того же пользователя и подготавливаем директории
RUN adduser -D -S -u 10001 appuser && \
    mkdir -p /data && \
    chown 10001 /data

COPY --from=builder /app/main /main

USER appuser

# Пример порта и точки входа
EXPOSE 8080
ENTRYPOINT ["/main"]
```

### Сценарий 4: Решение проблемы совместимости с Alpine (`musl`)

Если вы хотите использовать `alpine` в качестве финального образа, но собираете приложение на `glibc`-окружении, необходимо скомпилировать **полностью статически связанный** бинарный файл. Проблема несовместимости `glibc` (Debian) и `musl` (Alpine) решается флагами статической линковки. Общие принципы оптимизации сборки см. [Оптимизация сборки Docker-образов](./build_optimization.md).

```dockerfile
# --- Этап 1: Сборка ---
FROM golang:1.24 AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
# Флаг -a принудительно пересобирает пакеты
# -ldflags '-extldflags "-static"' обеспечивает статическую линковку
RUN CGO_ENABLED=0 GOOS=linux go build -a -ldflags '-extldflags "-static"' -o /app/main .

# --- Этап 2: Финальный образ ---
FROM alpine:3.24
COPY --from=builder /app/main /main
RUN chmod +x /main
ENTRYPOINT ["/main"]
```

### Верификация статической сборки

```bash
# 1. ldd — если бинарь статический, ответит "not a dynamic executable"
ldd ./main
# → not a dynamic executable

# 2. file — покажет "statically linked"
file ./main
# → ELF 64-bit LSB executable, x86-64, statically linked
```

Если `ldd` выводит список `.so`-зависимостей (libc.so.6, ld-linux-x86-64) — бинарь динамический и не запустится в Alpine/scratch.

## Дополнительная информация

### Смотрите также

- [Оптимизация сборки Docker-образов](./build_optimization.md)
- [Безопасность в Dockerfile](./security.md)
- [Проблема несовместимости libc (Alpine)](../../Docker_troubleshooting/alpine_glibc_compatibility.md)
