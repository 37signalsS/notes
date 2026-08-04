# Инструкции Dockerfile: Базовый образ и Метаданные

## Определения

**Базовый образ (Base Image)** — фундамент файловой системы образа. Инструкция `FROM` инициализирует новую стадию сборки и задает основу, на которую будут накладываться последующие слои. Она определяет ОС, системные библиотеки и среду выполнения.

**Метаданные (Metadata)** — структурированные данные об образе (версия, автор, лицензия, описание), которые сохраняются в конфигурации образа (`config.json`). Они не влияют на выполнение кода, но используются системами автоматизации, реестрами и сканерами безопасности для идентификации артефакта и генерации SBOM (Software Bill of Materials).

## Основные концепции

### Инструкция FROM: Инициализация сборки

Инструкция `FROM` должна быть первой значащей командой в Dockerfile (за исключением глобальных `ARG` и директив парсера).

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

**Влияние на Image Digest:** Любое изменение текста `LABEL` (даже добавление пробела) изменяет `config.json` образа. Это приводит к изменению **Image Digest**, что важно учитывать при использовании деплоя по хешам. При этом новые слои в файловой системе не создаются.

### Устаревшие практики

- **MAINTAINER:** Официально признана устаревшей (deprecated).
    *   *Замена:* `LABEL org.opencontainers.image.authors="Name <email@example.com>"`
- **Использование `latest`:** Ведет к невоспроизводимым сборкам и внезапным падениям в CI/CD.
    *   *Замена:* Всегда фиксируйте конкретную минорную версию или дайджест.

## Практические сценарии

### Сценарий 1: Динамическое управление версиями через ARG

Позволяет централизованно менять версию базового образа во всей инфраструктуре через параметры сборки.

```dockerfile
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

# Импорт метаданных базового образа для прослеживаемости
ARG BASE_IMAGE
LABEL org.opencontainers.image.base.name="${BASE_IMAGE}"
```

### Сценарий 2: Многоэтапная сборка (Multi-stage)

Использование `FROM ... AS ...` для минимизации размера и поверхности атаки.

```dockerfile
# Stage 1: Компиляция (тяжелый образ)
FROM golang:1.23-alpine AS builder
WORKDIR /app
COPY . .
RUN go build -o main .

# Stage 2: Выполнение (минимальный образ)
# Использование scratch для статических бинарников
FROM scratch
COPY --from=builder /app/main /main
ENTRYPOINT ["/main"]
```

### Сценарий 3: Группировка для чистоты манифеста

Объединяйте метки в одну инструкцию, чтобы уменьшить количество записей в истории команд, хотя в BuildKit это оптимизировано автоматически.

```dockerfile
LABEL org.opencontainers.image.created=$BUILD_DATE \
      org.opencontainers.image.vendor="MyCompany" \
      org.opencontainers.image.documentation="https://docs.example.com"
```

## Дополнительная информация

### Проверка метаданных

Увидеть все установленные метки и дайджест базового образа можно через `inspect`:

```bash
docker image inspect --format '{{json .Config.Labels}}' <image_id> | jq
```

**См. также:**
- **[Оптимизация сборки: Multi-stage](../Docker_best_practices/build_optimization.md)** — глубокий разбор уменьшения веса.
- **[Безопасность: Фиксация дайджестов](../Docker_best_practices/security.md)** — почему это критично для Supply Chain Security.
- **[Инструкции Dockerfile: Обзор](./overview_definitions.md)** — классификация всех доступных команд.
- **[Версионирование образов](../../Docker_registries/image_versioning_and_tagging.md)** — стратегии управления тегами.
