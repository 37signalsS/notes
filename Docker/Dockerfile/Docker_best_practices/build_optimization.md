# Оптимизация сборки Docker-образов

## Определения

- **Кэширование слоев (Layer Caching):** Механизм Docker, сохраняющий результат каждой инструкции `Dockerfile` в виде неизменяемого слоя. При повторных сборках Docker переиспользует существующие слои, если инструкция и контекст не изменились.
- **Многоэтапная сборка (Multi-stage Builds):** Техника использования нескольких инструкций `FROM` в одном файле. Позволяет разделить среду сборки (с компиляторами и зависимостями) и среду выполнения (минимально необходимый набор файлов). Итогом multistage-сборки является **Docker-образ** — по сути, tar-архив с слоями файловой системы, который можно физически распаковать и исследовать.
- **Контекст сборки (Build Context):** Набор локальных файлов, отправляемых Docker-клиентом сборщику (BuildKit) перед началом сборки. Оптимизация контекста напрямую влияет на скорость передачи данных.
- **BuildKit:** Современный движок сборки, использующий граф зависимостей (LLB) для параллельного выполнения команд и поддерживающий расширенные возможности (маунты, секреты, кэширование).
- **Монтирование кэша (Cache Mounts):** Механизм BuildKit (`--mount=type=cache`), позволяющий сохранять данные пакетных менеджеров во внешнем хранилище между сборками, не включая их в слои образа.
- **Аттестации (Attestations):** Метаданные (SBOM, Provenance), прикрепляемые к образу для подтверждения его состава и происхождения.
- **Heredoc:** Синтаксис Dockerfile, позволяющий записывать многострочные скрипты `RUN` без использования символов переноса строки `\`.
- **Distroless образы:** Минимальные базовые образы от Google, содержащие только приложение и его зависимости без оболочки, пакетного менеджера и других системных утилит. Используются как финальная стадия multi-stage для максимального уменьшения размера и поверхности атаки.
- **Squash (слоёв):** Механизм объединения всех слоёв образа в один, уменьшающий размер, но уничтожающий кэш и замедляющий повторную сборку. В BuildKit доступен через `--squash`, но не рекомендуется для production — предпочтительнее multi-stage + `COPY --link`.

## Базовые концепции

### Порядок инструкций и инвалидация кэша

Для максимальной эффективности кэширования инструкции в `Dockerfile` должны располагаться в порядке **от редко изменяемых к часто изменяемым**.

1.  **Каскадная инвалидация:** Если кэш слоя N сброшен (например, изменился текст команды или файл в `COPY`), то слои N+1, N+2 и все последующие будут пересобраны принудительно.
2.  **Инструкции RUN:** Любое изменение текста команды инвалидирует слой. Рекомендуется объединять связанные команды (например, `apt-get update && apt-get install`) для уменьшения количества слоев.
3.  **Инструкции COPY/ADD:** Docker проверяет контрольные суммы файлов. Если изменился хотя бы один файл, кэш слоя сбрасывается. **Антипаттерн:** `COPY . .` в начале файла, так как любое изменение кода сбросит кэш установки зависимостей.
4.  **`COPY --link` (BuildKit 1.5+):** Позволяет копировать файлы в независимые слои. Если предыдущие слои (например, базовый образ) изменятся, Docker просто пересоберет манифест, не перекопируя файлы заново. Это критично для ускорения сборки при обновлении базового образа.

### Стратегии оптимизации по типу приложения

| Критерий | Компилируемые (Go, Rust, C++) | Интерпретируемые (Node.js, Python) | JVM (Java, Kotlin) |
| :--- | :--- | :--- | :--- |
| **Главная цель** | Уменьшение размера образа (бинарник). | Ускорение установки зависимостей. | Уменьшение размера SDK + кэш .m2. |
| **Multi-stage** | **Критически важен** (отсечение SDK). | **Желателен** (удаление `dev-deps` и кэшей). | **Критически важен** (JDK ~300MB vs JRE ~80MB). |
| **Тип кэша** | Кэш компилятора (`target`, `build`). | Кэш пакетного менеджера (`~/.npm`, `pip`). | Кэш `.m2/repository`. |
| **Кросс-компиляция** | Нативная поддержка (`GOOS`, `TARGETARCH`). | Не применимо. | Не применимо (GraalVM — исключение). |
| **Рекомендуемый базовый образ** | `scratch`, `distroless/static`. | `alpine`, `slim`. | `eclipse-temurin-*-jre-alpine`. |

### Продвинутые возможности BuildKit

- **`COPY --link`:** Позволяет копировать файлы в абсолютно независимые слои. Если предыдущие слои (например, базовый образ) изменятся, Docker просто пересоберет манифест, не перекопируя файлы заново.
- **Временные монтирования (`--mount`):**
    - `type=cache`: Для папок зависимостей (`node_modules`, `pip cache`).
    - `type=secret`: Безопасная передача токенов без их сохранения в истории образа.
    - `type=ssh`: Использование SSH-ключей хоста для доступа к приватным репозиториям.
    - `type=bind`: Использование файлов из других стадий без их физического копирования.
    - `type=tmpfs`: Временное хранилище в RAM для промежуточных данных.
- **Reproducible Builds:** Использование переменной `SOURCE_DATE_EPOCH` для фиксации временных меток слоев, что позволяет получать идентичные дайджесты образов при сборке из того же исходного кода.
- **Build Checks:** Встроенный линтер Dockerfile (`docker buildx build --check`), проверяющий инструкции на соответствие лучшим практикам перед началом сборки.

### Удаленное кэширование (BuildKit Cache Backends)

Для CI/CD критически важно сохранять кэш между запусками. BuildKit поддерживает несколько бэкендов:

| Бэкенд | Назначение | Пример использования |
| :--- | :--- | :--- |
| **`registry`** | Универсальный, работает везде | `--cache-to type=registry,ref=reg/cache:app,mode=max` |
| **`gha`** | Оптимизирован для GitHub Actions | `--cache-to type=gha,mode=max` |
| **`s3`** | Для AWS / MinIO | `--cache-to type=s3,region=eu-west-1,bucket=cache,key=app` |
| **`local`** | Локальная папка на хосте | `--cache-to type=local,dest=/tmp/buildx-cache,mode=max` |
| **`inline`** | Кэш встраивается в образ (Docker Hub) | По умолчанию при `--push` |

**Режимы кэширования:**

| Режим | Описание | Когда использовать |
| :--- | :--- | :--- |
| `mode=min` | Кэш только финальной стадии | По умолчанию; экономит место |
| `mode=max` | Кэш всех промежуточных слоев (включая неиспользуемые в финальном образе) | Рекомендуется для CI/CD — ускоряет повторные сборки |

**Важно:** Режим `mode=max` сохраняет кэш всех промежуточных слоев, включая неиспользуемые в финальном образе стадии multi-stage. Это критично, так как при изменении только финальной стадии промежуточные стадии (builder) не пересобираются, и их кэш должен быть доступен.
## Практические сценарии

### Сценарий 1: Оптимальное кэширование Node.js

Использование `COPY --link` и монтирования кэша для `npm`.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine AS builder
WORKDIR /app

# Копируем только файлы манифеста в независимый слой
COPY --link package.json package-lock.json ./

# Кэш npm не попадает в образ, но доступен при следующей сборке
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# Копируем исходный код
COPY --link . .
RUN npm run build

FROM nginx:alpine
# Копируем только артефакты сборки
COPY --from=builder --link /app/dist /usr/share/nginx/html
```

### Сценарий 2: Кэширование для Python (pip)

Использование Heredoc и монтирования кэша.

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .

# Heredoc для чистоты кода и монтирование кэша pip
RUN --mount=type=cache,target=/root/.cache/pip <<EOF
apt-get update
apt-get install -y --no-install-recommends gcc
pip install --no-cache-dir --requirement requirements.txt
apt-get purge -y --auto-remove gcc
rm -rf /var/lib/apt/lists/*
EOF

COPY . .
CMD ["python", "app.py"]
```

### Сценарий 3: Java/Maven с сохранением .m2

Maven скачивает зависимости при каждой сборке. Монтирование кэша решает эту проблему.

```dockerfile
# syntax=docker/dockerfile:1
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY pom.xml .
# Предварительная загрузка зависимостей
RUN --mount=type=cache,target=/root/.m2 \
    mvn dependency:go-offline

COPY src ./src
RUN --mount=type=cache,target=/root/.m2 \
    mvn package -DskipTests

FROM eclipse-temurin:21-jre-alpine
COPY --from=build /app/target/*.jar /app/app.jar
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
```

### Сценарий 4: Безопасная сборка с секретами

Передача токена доступа к приватному реестру пакетов.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine
WORKDIR /app
COPY package.json ./
# Токен монтируется только на время выполнения команды и не сохраняется в образе
RUN --mount=type=secret,id=npm_token \
    NPM_TOKEN=$(cat /run/secrets/npm_token) npm install
```

### Сценарий 5: Go-приложение с кросс-компиляцией и distroless

Максимально минимальный образ: кросс-компиляция + distroless.

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.24-alpine AS builder

# Автоматически заполняются BuildKit
ARG TARGETOS TARGETARCH
WORKDIR /src
COPY go.mod go.sum ./

# Кэшируем модули Go
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY . .

# Кэшируем результат компиляции
RUN --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -o /app/server .

# Финальный образ: ~5-10MB вместо ~800MB
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /app/server /server
ENTRYPOINT ["/server"]
```

**Валидация:**
```bash
# Сборка под две архитектуры
docker buildx build --platform linux/amd64,linux/arm64 -t myapp:latest .

# Проверка размера образа
docker images myapp:latest
# → REPOSITORY   TAG       SIZE
# → myapp        latest    5.8MB  (вместо ~800MB без multi-stage)

# Проверка что кэш работает
# Вторая сборка будет значительно быстрее
time docker buildx build --platform linux/amd64,linux/arm64 -t myapp:latest .
```

### Сценарий 6: Rust с кэшированием Cargo

```dockerfile
# syntax=docker/dockerfile:1
FROM rust:1.82-slim AS builder
WORKDIR /app
COPY Cargo.toml Cargo.lock ./

# Создаём заглушку main.rs для кэширования зависимостей
RUN mkdir src && echo "fn main() {}" > src/main.rs

# Кэшируем реестр Cargo и результат компиляции зависимостей
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo build --release && \
    rm -rf src

# Копируем исходный код и пересобираем только бинарник
COPY src ./src
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo build --release && \
    cp target/release/myapp /usr/local/bin/

FROM debian:bookworm-slim
COPY --from=builder /usr/local/bin/myapp /usr/local/bin/myapp
ENTRYPOINT ["myapp"]
```

**Почему заглушка `main.rs`:** Без неё `cargo build` начнёт компиляцию зависимостей и кода одновременно. С заглушкой зависимости компилируются отдельно (кэшируются), а код — отдельно. При изменении только `src/` зависимости не пересобираются.

### Сценарий 7: C++ с ccache

```dockerfile
# syntax=docker/dockerfile:1
FROM ubuntu:24.04 AS builder
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ccache
WORKDIR /src
COPY . .

# Кэш компиляции ccache
RUN --mount=type=cache,target=/root/.cache/ccache \
    CC="ccache gcc" CXX="ccache g++" make -j$(nproc)

FROM debian:bookworm-slim
COPY --from=builder /src/myapp /usr/local/bin/myapp
ENTRYPOINT ["myapp"]
```

### Сценарий 8: Сборка с аттестациями (SBOM) для production

```bash
# Сборка с генерацией SBOM и provenance
docker buildx build \
  --sbom=true \
  --provenance=mode=max \
  --cache-to type=registry,ref=myregistry/cache:myapp,mode=max \
  --cache-from type=registry,ref=myregistry/cache:myapp \
  --push -t myregistry.com/app:v1 .

# Проверка SBOM
docker buildx imagetools inspect myregistry.com/app:v1 \
  --format '{{ json .SBOM }}' | jq .
```
## Анализ слоев и инструменты

### Интерактивный анализ с dive

Инструмент [dive](https://github.com/wagoodman/dive) позволяет визуализировать каждый слой образа и находить «мусор» — файлы, которые были созданы и затем удалены в разных слоях.

```bash
# Запуск анализа
dive myapp:latest

# В интерфейсе обратите внимание на колонку Efficiency
# Если она ниже 90%, образ содержит файлы-призраки
```

**Типичная проблема:** `apt-get clean` в отдельном `RUN` не уменьшает размер слоя, потому что файлы уже зафиксированы в предыдущем слое. Правильный подход — объединять установку и очистку в один `RUN`:

```dockerfile
# ПЛОХО: мусор остался в слое установки
RUN apt-get update && apt-get install -y curl
RUN apt-get clean

# ХОРОШО: мусор удалён до фиксации слоя
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*
```

### Docker Scout — рекомендации по базовому образу

```bash
# Быстрый обзор и рекомендации
docker scout quickview myapp:latest

# Сравнение с другим базовым образом
docker scout compare myapp:latest --to python:3.12-slim
```

### Просмотр размера слоев

```bash
# Просмотр размера каждого слоя
docker history myapp:latest --format "{{.Size}} {{.CreatedBy}}"
# → 7.2MB  RUN apk add --no-cache tini
# → 1.1MB  COPY package.json ./
# → 42.3MB COPY . .

# Просмотр общего размера
docker image inspect myapp:latest --format='{{.Size}}'
# → 52341234 (байты)
```
## Валидация и диагностика

### Проверка Dockerfile перед сборкой

```bash
# Встроенный линтер BuildKit
docker buildx build --check .
# → [WARNING] ...: UndefinedVar: TargetStageName is not defined as an ARG

# Просмотр outline параметров сборки
docker buildx build --call=outline .
# → TARGETPLATFORM: linux/amd64
# → TARGETOS: linux
# → TARGETARCH: amd64

# Просмотр доступных таргетов (стадий)
docker buildx build --call=targets .
```

### Проверка размера контекста

```bash
# Просмотр размера директории
du -sh .
# → 45M    .

# Просмотр размера контекста (с учётом .dockerignore)
docker build --progress=plain . 2>&1 | grep "transferring"
# → transferring context: 8.3MB done

# Сравнение ДО и ПОСЛЕ оптимизации .dockerignore
# До: 42.1MB → После: 8.3MB
```

### Проверка эффективности multi-stage

```bash
# Сравнение размеров стадий
docker buildx build --target builder -t myapp:builder .
docker buildx build -t myapp:final .

docker images myapp
# → REPOSITORY   TAG      SIZE
# → myapp        builder  1.2GB   (стадия сборки)
# → myapp        final    15MB    (финальный образ)
# → Экономия: ~99%
```

### Проверка кэша

```bash
# Просмотр использования диска кэшем
docker buildx du
# → RECLAIMABLE   SIZE
# → 2.1GB         3.4GB

# Просмотр кэша за последние 24 часа
docker buildx du --filter until=24h

# Очистка старого кэша
docker buildx prune --filter "until=72h"
```

### Проверка кэша зависимостей

```bash
# Сборка两次 — вторая должна быть быстрее
time docker build -t myapp:latest .
# → real    0m45.2s

# Изменить код, пересобрать
time docker build -t myapp:latest .
# → real    0m12.8s  (зависимости из кэша)
```

### Проверка SBOM и provenance

```bash
# Просмотр SBOM в образе
docker buildx imagetools inspect myapp:latest \
  --format '{{ json .SBOM }}' | jq '.artifacts | length'
# → 42 (количество компонентов)

# Просмотр provenance
docker buildx imagetools inspect myapp:latest \
  --format '{{ json .Provenance }}' | jq '.buildType'
# → "https://github.com/moby/buildkit/client/llb"
```
## Типичные ошибки и их решение

### Ошибка 1: Кэш не переиспользуется между сборками

**Причина:** Не настроены источники кэша или используется локальный кэш в ephemeral-окружениях (CI/CD).

```bash
# Диагностика
docker buildx ls
# → Если сборщик "default" с драйвером "docker" — кэш только локальный
```

**Решение:** Настройте удаленный кэш:

```bash
docker buildx build \
  --cache-to type=registry,ref=myregistry/cache:myapp,mode=max \
  --cache-from type=registry,ref=myregistry/cache:myapp \
  -t myapp:latest .
```

### Ошибка 2: Образ слишком большой после multi-stage

**Причина:** В финальную стадию попали лишние файлы или не использовался дистрибутивный образ.

```bash
# Диагностика
dive myapp:latest
# → Проверьте каждую директорию на наличие мусора
```

**Решение:**

```dockerfile
# ПЛОХО: копируем всё из builder
FROM alpine:3.21
COPY --from=builder /app /app

# ХОРОШО: копируем только нужный артефакт
FROM alpine:3.21
COPY --from=builder /app/dist /usr/share/nginx/html
```

### Ошибка 3: `COPY --link` не ускоряет сборку

**Причина:** `COPY --link` работает только если предыдущие слои изменились. Если изменяется сам файл — слой всё равно пересобирается.

**Решение:** Используйте `COPY --link` вместе с `# syntax=docker/dockerfile:1` и правильно выстроенной последовательностью инструкций:

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine AS builder
WORKDIR /app

# 1. Манифест (редко меняется)
COPY --link package.json package-lock.json ./
RUN npm ci

# 2. Код (часто меняется)
COPY --link . .
RUN npm run build
```

### Ошибка 4: Heredoc не работает

**Причина:** Отсутствует директива `# syntax` или используется устаревший синтаксис.

```dockerfile
# ПЛОХО: нет директивы syntax
RUN <<EOF
apt-get update
apt-get install -y curl
EOF

# ХОРОШО: синтаксис указан
# syntax=docker/dockerfile:1.4
RUN <<EOF
apt-get update
apt-get install -y curl
EOF
```

### Ошибка 5: Кэш apt не переиспользуется

**Причина:** Кэш apt хранится в `/var/cache/apt` и `/var/lib/apt`, которые попадают в слой.

**Решение:** Используйте монтирование кэша:

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends curl
```

### Ошибка 6: Медленная мультиплатформенная сборка

**Причина:** Эмуляция через QEMU значительно медленнее нативной сборки.

**Решение:** Используйте кросс-компиляцию для Go/Rust:

```dockerfile
FROM --platform=$BUILDPLATFORM golang:1.24-alpine AS builder
ARG TARGETOS TARGETARCH
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /app .
```

### Ошибка 7: Секрет попадает в слой образа

**Причина:** Секрет передан через `ENV`, `ARG` или `RUN echo`.

```dockerfile
# ПЛОХО: пароль навсегда в истории
ENV DB_PASS=secret123
RUN PGPASSWORD=$DB_PASS pg_dump ...

# ХОРОШО: секрет через BuildKit
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=db_pass \
    PGPASSWORD=$(cat /run/secrets/db_pass) pg_dump ...
```

```bash
# Запуск сборки с секретом
docker buildx build --secret id=db_pass,src=./db_pass.txt -t myapp .
```

### Ошибка 8: `docker build --check` не находит проблем

**Причина:** Используется устаревший синтаксис или отключены проверки.

```dockerfile
# Включение проверок и перевод предупреждений в ошибки
# syntax=docker/dockerfile:1
# check=error=true
FROM node:22-alpine
```
## Лучшие практики

### Сводка рекомендаций

| Практика | Рекомендация | Причина |
| :--- | :--- | :--- |
| **Multi-stage** | Всегда для компилируемых языков, желательно для интерпретируемых | Уменьшение размера образа на 90-99% |
| **Cache Mounts** | `--mount=type=cache` для пакетных менеджеров | Ускорение повторных сборок в 5-10 раз |
| **COPY --link** | Использовать для копирования файлов | Независимые слои, ускорение при обновлении базового образа |
| **Heredoc** | Использовать вместо `\` для многострочных команд | Улучшает читаемость и уменьшает ошибки |
| **.dockerignore** | Всегда создавать, исключать .git, node_modules, секреты | Уменьшение контекста сборки |
| **Удаленный кэш** | Настроить `--cache-to`/`--cache-from` для CI/CD | Ускорение сборок в CI/CD |
| **Аттестации** | Включать `--sbom` и `--provenance` для production | Безопасность и аудит |
| **Build Checks** | Использовать `docker buildx build --check` | Статический анализ перед сборкой |
| **Размер контекста** | Проверять через `du -sh .` и `--progress=plain` | Скорость передачи контекста |
| **Кросс-компиляция** | Использовать для Go/Rust вместо QEMU | Ускорение multi-platform сборки |

### Порядок инструкций в Dockerfile

```dockerfile
# 1. Версия синтаксиса (всегда первой строкой)
# syntax=docker/dockerfile:1

# 2. Базовый образ (стабильная версия, не latest)
FROM node:22-alpine AS builder

# 3. SHELL (если нужен pipefail)
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# 4. WORKDIR
WORKDIR /app

# 5. Системные зависимости (кэшируются долго, меняются редко)
RUN apk add --no-cache tini

# 6. Зависимости (манифест + lock-файл)
COPY --link package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

# 7. Исходный код (меняется часто)
COPY --link . .

# 8. Сборка
RUN npm run build

# 9. Финальная стадия (минимальный образ)
FROM nginx:alpine
COPY --from=builder --link /app/dist /usr/share/nginx/html

# 10. Метаданные
LABEL version="1.0" maintainer="team@example.com"

# 11. Entrypoint
ENTRYPOINT ["nginx", "-g", "daemon off;"]
```

### Чек-лист перед деплоем

- [ ] Dockerfile использует exec-form для CMD/ENTRYPOINT
- [ ] Multi-stage: финальная стадия содержит только необходимые файлы
- [ ] Cache mounts настроены для пакетных менеджеров (npm, pip, maven, cargo)
- [ ] `.dockerignore` исключает .git, node_modules, секреты, артефакты сборки
- [ ] Базовый образ использует конкретную версию (не `latest`)
- [ ] `--no-install-recommends` при установке пакетов через apt
- [ ] Кэш пакетного менеджера удалён в том же RUN (или через cache mount)
- [ ] Секреты переданы через `--mount=type=secret`, не через ENV/ARG
- [ ] `--sbom` и `--provenance` включены для production-сборок
- [ ] `docker buildx build --check` не выявил проблем
- [ ] Размер образа проверен через `dive` (efficiency > 90%)
- [ ] Удалённый кэш настроен для CI/CD (`--cache-to`/`--cache-from`)
- [ ] Кросс-компиляция используется для Go/Rust multi-platform сборок
## Дополнительная информация

### Взаимодействие с CI/CD

Для сохранения кэша между запусками в CI (GitHub Actions, GitLab CI) необходимо использовать экспортеры кэша:
- `--cache-from type=registry,ref=...`
- `--cache-to type=registry,ref=...,mode=max`
Режим `mode=max` сохраняет кэш всех промежуточных слоев, включая неиспользуемые в финальном образе стадии multi-stage.

**Пример GitHub Actions:**

```yaml
- name: Build and push
  uses: docker/build-push-action@v6
  with:
    context: .
    push: true
    tags: myorg/app:${{ github.sha }}
    cache-from: type=gha
    cache-to: type=gha,mode=max
    sbom: true
    provenance: mode=max
```

**Пример GitLab CI:**

```yaml
build:
  stage: build
  image: docker:27
  services:
    - docker:29.8-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker buildx create --use --driver docker-container
    - docker buildx build \
        --cache-from type=registry,ref=$CI_REGISTRY_IMAGE/cache \
        --cache-to type=registry,ref=$CI_REGISTRY_IMAGE/cache,mode=max \
        --push -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
```

### Смотрите также

- **[BuildKit в Dockerfile](../dockerfile_buildkit.md)** — глубокий разбор механизмов маунтов и LLB.
- **[Docker Buildx: Мультиплатформенность](../docker_buildx.md)** — управление инстансами сборщиков и кросс-сборка.
- **[Контекст сборки и .dockerignore](../dockerfile_build_context.md)** — правила исключения файлов.
- **[Инструменты оптимизации: dive, Scout, hadolint](../dockerfile_optimization_tools.md)** — статический и динамический анализ образов.
- **[Инструкция RUN: кэширование и монтирования](../Instructions/build_time_commands.md)** — детальный разбор `--mount` и Heredoc.
