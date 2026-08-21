# Инструкции Dockerfile: Базовый образ и Метаданные

## Определения

**Базовый образ (Base Image)** — фундамент файловой системы образа. Инструкция `FROM` инициализирует новую стадию сборки и задает основу, на которую будут накладываться последующие слои. Она определяет ОС, системные библиотеки и среду выполнения.

**Метаданные (Metadata)** — структурированные данные об образе (версия, автор, лицензия, описание), которые сохраняются в конфигурации образа (`config.json`). Они не влияют на выполнение кода, но используются системами автоматизации, реестрами и сканерами безопасности для идентификации артефакта и генерации SBOM (Software Bill of Materials). Метаданные не создают новых слоёв файловой системы, но изменяют `Image Digest`, что критически важно учитывать при CI/CD деплое.

**OCI Image Specification (OCI Image Spec)** — открытый стандарт, определяющий формат метаданных образов контейнеров. Пространство имен `org.opencontainers.image.*` является рекомендованным способом аннотирования образов согласно этой спецификации. Использование стандартных ключей обеспечивает совместимость с реестрами (Docker Hub, Harbor, ECR), сканерами безопасности и инструментами SBOM-генерации.

**Software Bill of Materials (SBOM)** — машиночитаемый перечень всех компонентов и зависимостей образа. Метаданные образа, указанные через `LABEL`, становятся частью SBOM и используются для аудита безопасности, отслеживания уязвимостей и соответствия регуляторным требованиям (стандарты CycloneDX или SPDX).

## Предварительные требования

- **Docker** версии 20.10 или новее (для полной поддержки BuildKit и мультиплатформенных сборок).
- **BuildKit** включён (по умолчанию в Docker 23.0+; для более ранних версий — `DOCKER_BUILDKIT=1`).
- Текстовый редактор с подсветкой синтаксиса Dockerfile (VS Code с расширением `dockerfile`, JetBrains с Docker plugin).
- Понимание базовых концепций Linux: файловая система, процессы, пользователи и группы, переменные окружения.
- Доступ к реестру образов (Docker Hub, приватный реестр) для загрузки базовых образов.
- Для мультиплатформенных сборок: установленный `buildx` (`docker buildx install`).

## Основные концепции

### Инструкция FROM: Инициализация сборки

Инструкция `FROM` должна быть первой значащей командой в Dockerfile (за исключением глобальных `ARG` и директив парсера). Каждая новая инструкция `FROM` начинает новую стадию (stage) сборки, сбрасывая контекст предыдущей стадии.

**Синтаксис и безопасность:**

```dockerfile
# 1. По тегу (мутабельный способ, не рекомендуется для prod)
FROM alpine:3.21

# 2. По дайджесту (наивысшая степень безопасности и воспроизводимости)
# Гарантирует неизменность образа даже при перезаписи тега в реестре
FROM alpine:3.21@sha256:a8560b36e8b8210634f77d9f7f9efd7ffa463e380b75e2e74aff4511df3ef88c

# 3. Именование стадии для Multi-stage сборки
FROM golang:1.23-alpine AS builder

# 4. Указание целевой платформы (для мультиплатформенных образов)
FROM --platform=linux/arm64 ubuntu:24.04
```

**Влияние на кэш сборки:** Изменение базового образа (тега или дайджеста) инвалидирует кэш для всех последующих инструкций в данной стадии. Это означает, что любое обновление `FROM` приведёт к полной пересборке всех слоёв ниже, поэтому инструкции, зависящие от базы (например, установка пакетов), должны располагаться как можно ниже в `Dockerfile`.

**Типы базовых образов:**

| Тип | Примеры | Размер | Назначение |
| :--- | :--- | :--- | :--- |
| **Полноразмерные** | `ubuntu:24.04`, `debian:bookworm` | 70-120 MB | Разработка, отладка, когда нужен полный набор утилит |
| **Минималистичные** | `alpine:3.21`, `busybox` | 5-15 MB | Продакшн-сборки с минимальной поверхностью атаки |
| **Distroless** | `gcr.io/distroless/static`, `chainguard/static` | 2-5 MB | Максимальная безопасность (нет shell, пакетного менеджера) |
| **Пустые** | `scratch` | 0 MB | Статические бинарники (Go, Rust), когда ОС не нужна |

**Использование `scratch`:** Образ `scratch` полностью пуст — в нём нет файловой системы, нет shell, нет стандартных утилит Linux. Подходит для статически скомпилированных бинарников (Go, Rust), которые не зависят от системных библиотек. При использовании `scratch` необходимо явно копировать необходимые файлы (например, CA-сертификаты для HTTPS) через `COPY --from=builder`.

**Использование `distroless`:** Образы Google distroless содержат только минимальный набор библиотек и рантайм (например, JRE для Java), но не содержат shell, пакетного менеджера или стандартных утилит. Это сводит поверхность атаки к минимуму, но затрудняет отладку (нельзя выполнить `docker exec -it <container> sh`).

**Мультиплатформенные сборки:** Инструкция `FROM --platform` позволяет указать целевую архитектуру образа. Это критически важно при кросс-компиляции (например, сборка `linux/arm64` на `linux/amd64` хосте). Для работы требуется `buildx` и поддержка QEMU или реальных builder'ов для целевой архитектуры.

**Нюансы области видимости ARG (Scope):**

Инструкция `ARG` — единственная, которая может стоять *перед* `FROM`. Это позволяет параметризовать выбор базы.

```dockerfile
# Глобальная область (Global Scope)
ARG VERSION=3.21
FROM alpine:${VERSION}

# Чтобы использовать эту переменную в RUN, её нужно переобъявить внутри стадии
ARG VERSION
RUN echo "Building on Alpine ${VERSION}"
```

**Важные особенности:**
- Глобальный `ARG` (до первого `FROM`) доступен только в самой инструкции `FROM` и её аргументах (например, `--platform`).
- Чтобы передать значение `ARG` в рантайм, его нужно скопировать в `ENV` (подробнее — в разделе [Переменные (ENV и ARG)](./environment_variables.md)).
- `ARG`, объявленный в предыдущей стадии multi-stage сборки, **не доступен** в следующей стадии — каждая стадия имеет изолированное пространство имён.

### Инструкция LABEL: Аннотирование образа

Директива `LABEL` добавляет метаданные в формате «ключ-значение». Современный стандарт требует использования пространства имен **`org.opencontainers.image`** (OCI Image Spec v1.1).

**Рекомендованные ключи**

| Ключ | Описание | Пример |
| :--- | :--- | :--- |
| `org.opencontainers.image.title` | Название приложения | `"Order Service API"` |
| `org.opencontainers.image.version` | Версия ПО (SemVer) | `"1.4.2"` |
| `org.opencontainers.image.source` | Ссылка на репозиторий | `"https://github.com/org/repo"` |
| `org.opencontainers.image.revision` | Git Commit SHA | `"a1b2c3d4..."` |
| `org.opencontainers.image.base.digest`| SHA256 базового образа | `"sha256:abcd..."` |
| `org.opencontainers.image.licenses` | Лицензия (SPDX) | `"Apache-2.0"` |
| `org.opencontainers.image.created` | Дата и время сборки (ISO 8601) | `"2026-08-21T10:00:00Z"` |
| `org.opencontainers.image.vendor` | Организация-производитель | `"MyCompany Inc."` |
| `org.opencontainers.image.description` | Краткое описание образа | `"API gateway for microservices"` |
| `org.opencontainers.image.url` | Домашняя страница проекта | `"https://example.com"` |
| `org.opencontainers.image.documentation` | Ссылка на документацию | `"https://docs.example.com"` |
| `org.opencontainers.image.authors` | Авторы (формат: `Name <email>`) | `"DevOps Team <devops@example.com>"` |

**Влияние на Image Digest:** Любое изменение текста `LABEL` (даже добавление пробела) изменяет `config.json` образа. Это приводит к изменению **Image Digest**, что важно учитывать при использовании деплоя по хешам. При этом новые слои в файловой системе не создаются. Это значит, что изменение лейблов не влияет на размер образа, но влияет на воспроизводимость — два образа с одинаковым содержимым, но разными лейблами, будут иметь разные дайджесты.

**Влияние на кэш сборки:** Инструкции `LABEL` не инвалидируют кэш предыдущих слоёв, но изменение лейблов заставляет BuildKit пересоздать метаданные образа (config.json). Это не замедляет сборку, но может влиять на CI/CD пайплайны, которые сравнивают дайджесты образов.

**SBOM и прослеживаемость:** Метаданные, указанные через `LABEL`, автоматически включаются в генерируемый SBOM (Software Bill of Materials). Сканеры безопасности (Trivy, Grype, Snyk) используют эти данные для определения версии ПО и поиска известных уязвимостей. Отсутствие стандартных лейблов OCI затрудняет автоматизированный аудит.

### Устаревшие практики

- **MAINTAINER:** Официально признана устаревшей (deprecated) с Docker 1.13.
    *   *Причина:* Инструкция `MAINTAINER` не поддерживает формат OCI и не может быть использована для генерации SBOM. Она создаёт отдельный слой, что увеличивает размер образа.
    *   *Замена:* `LABEL org.opencontainers.image.authors="Name <email@example.com>"`
- **Использование `latest`:** Ведет к невоспроизводимым сборкам и внезапным падениям в CI/CD.
    *   *Причина:* Тег `latest` является мутабельным — владелец репозитория может обновить образ под этим тегом в любой момент, изменив версию ОС, библиотек или рантайма.
    *   *Замена:* Всегда фиксируйте конкретную минорную версию или дайджест (`node:20.11-slim` вместо `node:latest`).
- **Смешивание тегов и дайджестов без указания версии:** Использование `FROM image@sha256:abc...` без указания тега затрудняет чтение Dockerfile и отладку.
    *   *Замена:* Указывайте тег для читаемости и дайджест для безопасности: `FROM alpine:3.21@sha256:abc...`.

## Практические сценарии

### Сценарий 1: Динамическое управление версиями через ARG

Позволяет централизованно менять версию базового образа во всей инфраструктуре через параметры сборки. Это особенно полезно, когда один и тот же Dockerfile используется для нескольких окружений или при автоматическом обновлении зависимостей в CI/CD.

```dockerfile
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

# Импорт метаданных базового образа для прослеживаемости
ARG BASE_IMAGE
LABEL org.opencontainers.image.base.name="${BASE_IMAGE}"
```

**Сборка с параметрами:**

```bash
# Сборка с образом по умолчанию
docker build -t myapp:1.0 .

# Сборка с указанием другого базового образа
docker build --build-arg BASE_IMAGE=python:3.11-slim -t myapp:1.0-py311 .

# Сборка с указанием образа из приватного реестра
docker build --build-arg BASE_IMAGE=registry.example.com/python:3.12-slim -t myapp:1.0 .
```

### Сценарий 2: Многоэтапная сборка (Multi-stage)

Использование `FROM ... AS ...` для минимизации размера и поверхности атаки. Каждая стадия сборки имеет изолированное пространство имён для переменных и файловой системы. Финальный образ содержит только последнюю стадию (или явно указанную через `COPY --from`).

```dockerfile
# Stage 1: Компиляция (тяжелый образ с компилятором и зависимостями)
FROM golang:1.23-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o main .

# Stage 2: Выполнение (минимальный образ)
# Использование scratch для статических бинарников
FROM scratch
# Копируем CA-сертификаты для HTTPS-запросов
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /app/main /main
ENTRYPOINT ["/main"]
```

**Важные особенности:**
- `CGO_ENABLED=0` — отключает динамическую линковку с libc, что позволяет использовать `scratch`.
- `COPY --from=builder` — копирует файлы из предыдущей стадии. Можно указать стадию по имени (`--from=builder`) или по номеру (`--from=0`).
- CA-сертификаты необходимы для HTTPS-запросов, так как `scratch` не содержит стандартных корневых сертификатов.

### Сценарий 3: Группировка для чистоты манифеста

Объединяйте метки в одну инструкцию, чтобы уменьшить количество записей в истории команд, хотя в BuildKit это оптимизировано автоматически.

```dockerfile
LABEL org.opencontainers.image.created=$BUILD_DATE \
      org.opencontainers.image.vendor="MyCompany" \
      org.opencontainers.image.documentation="https://docs.example.com"
```

### Сценарий 4: Интеграция с CI/CD для автоматической простановки метаданных

В CI/CD пайплайнах метаданные образа генерируются автоматически на основе переменных окружения CI-системы. Это обеспечивает прослеживаемость (traceability) каждого образа до конкретного коммита и билда.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json .

# Метаданные, генерируемые CI/CD
ARG BUILD_DATE
ARG GIT_SHA
ARG GIT_TAG
LABEL org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.version="${GIT_TAG}" \
      org.opencontainers.image.source="https://github.com/org/repo" \
      org.opencontainers.image.title="Order Service API" \
      org.opencontainers.image.vendor="MyCompany" \
      org.opencontainers.image.licenses="Apache-2.0"

EXPOSE 3000
CMD ["node", "dist/server.js"]
```

**Сборка в CI/CD (GitHub Actions пример):**

```yaml
- name: Build and push
  uses: docker/build-push-action@v5
  with:
    context: .
    push: true
    tags: myregistry.io/order-service:${{ github.sha }}
    build-args: |
      BUILD_DATE=${{ github.event.head_commit.timestamp }}
      GIT_SHA=${{ github.sha }}
      GIT_TAG=${{ github.ref_name }}
```

### Сценарий 5: Многоэтапная сборка с дифференциацией зависимостей

Разделение этапов установки зависимостей и сборки кода позволяет максимально эффективно использовать кэш Docker. Изменение исходного кода не приводит к пересборке зависимостей.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:20-alpine AS deps
WORKDIR /app
# Копируем только файлы зависимостей (изменяются редко)
COPY package.json package-lock.json ./
RUN npm ci

# Stage 2: Сборка (изменяется чаще)
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
# Копируем исходный код (изменяется чаще)
COPY . .
RUN npm run build

# Stage 3: Продакшн
FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/package.json .
COPY --from=deps /app/node_modules ./node_modules
EXPOSE 3000
CMD ["node", "dist/server.js"]
```

### Сценарий 6: Мультиплатформенная сборка для архитектур amd64 и arm64

Сборка образов для нескольких архитектур позволяет использовать один и тот же образ на серверах (amd64) и на устройствах ARM (Apple Silicon, Raspberry Pi, ARM-серверы).

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.23-alpine AS builder
ARG TARGETARCH
WORKDIR /app
COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} go build -o main .

FROM scratch
COPY --from=builder /app/main /main
ENTRYPOINT ["/main"]
```

**Сборка:**

```bash
# Создание multi-platform builder'а (однократно)
docker buildx create --name multiarch --driver docker-container --use

# Сборка для нескольких платформ
docker buildx build --platform linux/amd64,linux/arm64 -t myregistry.io/myapp:1.0 --push .
```

**Примечание:** Переменная `$BUILDPLATFORM` автоматически определяет архитектуру хоста, на котором запущена сборка. Это позволяет избежать эмуляции через QEMU и значительно ускоряет кросс-компиляцию.

## Дополнительная информация

### Валидация и проверка

**Просмотр метаданных образа:**

После сборки образа необходимо проверить, что метаданные и базовый образ настроены корректно.

```bash
# Просмотр всех лейблов
docker image inspect --format '{{json .Config.Labels}}' <image_id> | jq

# Просмотр конкретного лейбла
docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' <image_id>
# → 1.4.2

# Просмотр базового образа и дайджеста
docker image inspect --format '{{.Config.Image}}' <image_id>
# → node:20-alpine

docker image inspect --format '{{index .RepoDigests 0}}' <image_id>
# → node@sha256:723c347...

# Просмотр истории инструкций (слоёв)
docker history <image_id>
```

**Проверка целостности дайджеста:**

```bash
# Скачиваем образ по дайджесту
docker pull myregistry.io/myapp@sha256:a1b2c3d4...

# Сравниваем дайджест с ожидаемым
docker inspect --format '{{index .RepoDigests 0}}' myregistry.io/myapp@sha256:a1b2c3d4...
# → myregistry.io/myapp@sha256:a1b2c3d4...
```

**Проверка размера и слоёв образа:**

```bash
# Просмотр размера образа
docker images <image_id>

# Просмотр размера каждого слоя
docker history <image_id> --human-readable --format "{{.Size}}\t{{.CreatedBy}}"
```

### Типичные ошибки и решение проблем

**Ошибка: `FROM` не является первой инструкцией**

Сообщение:
```text
FROM must be the first instruction
```

Причина: Инструкция `FROM` должна быть первой значащей командой в Dockerfile. До неё могут находиться только комментарии, `ARG` и директивы парсера (`# syntax`, `# check`).

Решение:
```dockerfile
# Правильно
ARG BASE_IMAGE=alpine:3.21
FROM ${BASE_IMAGE}

# Неправильно
LABEL version="1.0"
FROM alpine:3.21
```

**Ошибка: Переменная ARG не определена в стадии**

Сообщение:
```text
ARG used without matching FROM
```

Причина: Глобальный `ARG` (до первого `FROM`) доступен только в инструкции `FROM`. Для использования внутри стадии его необходимо переобъявить.

Решение:
```dockerfile
ARG VERSION=3.21
FROM alpine:${VERSION}

# Переобъявляем для использования в RUN
ARG VERSION
RUN echo "Building on Alpine ${VERSION}"
```

**Ошибка: Образ `scratch` не содержит необходимых файлов**

Сообщение:
```text
/bin/sh: not found
```

Причина: Образ `scratch` полностью пуст — нет shell, нет стандартных библиотек, нет утилит.

Решение: Убедитесь, что бинарник скомпилирован статически (`CGO_ENABLED=0` для Go). Копируйте все необходимые файлы (CA-сертификаты, конфиги) через `COPY --from=builder`.

**Ошибка: Мультиплатформенная сборка не поддерживается**

Сообщение:
```text
multiple platforms feature is currently not supported for docker driver
```

Причина: Драйвер Docker по умолчанию не поддерживает мультиплатформенные сборки.

Решение:
```bash
docker buildx create --name multiarch --driver docker-container --use
docker buildx inspect --bootstrap
```

### Граничные случаи

**Пустой `FROM` (scratch) и CA-сертификаты:**

Образ `scratch` не содержит корневых сертификатов, что делает невозможными HTTPS-запросы. При использовании `scratch` необходимо явно копировать CA-сертификаты из предыдущей стадии:

```dockerfile
FROM scratch
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /app/main /main
ENTRYPOINT ["/main"]
```

**Унаследование переменных окружения из базового образа:**

Переменные `ENV`, установленные в базовом образе, наследуются всеми последующими слоями. Это может приводить к конфликтам, если базовый образ содержит нежелательные настройки. Для сброса используйте:

```dockerfile
ENV PATH="/usr/local/bin:/usr/bin:/bin"
ENV HOME="/app"
```

**Конфликт имён стадий в multi-stage:**

Имена стадий должны быть уникальными в пределах одного Dockerfile. Повторное использование имени приведёт к ошибке:

```dockerfile
FROM golang:1.23-alpine AS builder
# ... сборка ...

FROM golang:1.23-alpine AS builder  # Ошибка: имя уже занято
# ... сборка ...
```

Решение: используйте уникальные имена (`builder-api`, `builder-worker`).

### См. также

- **[Оптимизация сборки: Multi-stage](../Docker_best_practices/build_optimization.md)** — глубокий разбор уменьшения веса и стратегий кэширования.
- **[Безопасность: Фиксация дайджестов](../Docker_best_practices/security.md)** — почему это критично для Supply Chain Security.
- **[Версионирование образов](../../Docker_registries/image_versioning_and_tagging.md)** — стратегии управления тегами и дайджестами.
