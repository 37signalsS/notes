# Инструкции Dockerfile: Обзор

**Актуально для:** Docker 20.10+, BuildKit v1.4+

## Определения

**Инструкции Dockerfile** — зарезервированные ключевые слова, используемые в файле `Dockerfile` для описания процесса сборки образа. Каждая инструкция представляет собой отдельный логический шаг, который либо формирует новый слой файловой системы (изменяя содержимое), либо модифицирует метаданные образа (управляя рантаймом). Инструкции выполняются последовательно сверху вниз, и каждая создаёт неизменяемый слой (layer) в стеке образа.

**Директивы парсера (Parser Directives)** — специальные инструкции, которые обязаны находиться в самых первых строках файла (до первого инструкции или комментария). Они управляют поведением сборщика (BuildKit), определяют версию синтаксиса и активируют встроенные механизмы проверки качества (линтинга). Директивы парсера не являются инструкциями Dockerfile в строгом смысле — они не создают слои и не влияют на образ.

**Слой (Layer)** — неизменяемый контейнер с файлами и метаданными, создаваемый каждой инструккой Dockerfile, изменяющей файловую систему. Слои кэшируются сборщиком и переиспользуются при повторной сборке, что значительно ускоряет процесс. Каждый слой имеет уникальный cryptographic hash, используемый для инвалидации кэша.

**Кэш сборки (Build Cache)** — механизм повторного использования результатов предыдущих сборок. BuildKit проверяет, изменились ли входные данные инструкции (аргументы, содержимое файлов, зависимости), и если нет — пропускает выполнение, используя закэшированный результат. Понимание того, какие инструкции инвалидируют кэш, критически важно для оптимизации времени сборки.

**Digest образа (Image Digest)** — уникальный криптографический хеш (SHA256), идентифицирующий точное содержимое образа. Изменение любого слоя или метаданных приводит к новому digest. Digest используется для отслеживания версий, проверки целостности и управления зависимостями в CI/CD пайплайнах.

## Предварительные требования

- **Docker** версии 20.10 или новее (для поддержки BuildKit по умолчанию).
- **BuildKit** включён (по умолчанию в Docker 23.0+; для более ранних версий — `DOCKER_BUILDKIT=1`).
- Текстовый редактор с подсветкой синтаксиса Dockerfile (VS Code с расширением `dockerfile`, JetBrains с Docker plugin).
- Понимание базовых концепций Linux: файловая система, процессы, пользователи и группы, переменные окружения.

## Основные концепции

### Директивы парсера (2025-2026)

Современные сборки (BuildKit v1.8+) требуют явного управления правилами сборки через директивы.

| Директива | Назначение | Пример |
| :--- | :--- | :--- |
| **`# syntax`** | Выбор версии синтаксиса Dockerfile | `# syntax=docker/dockerfile:1` |
| **`# check`** | Встроенный линтинг и проверка best practices | `# check=error=true` |
| **`# escape`** | Символ экранирования (актуально для Windows) | `# escape=` ` (backtick) |

**`# syntax`** — позволяет использовать конкретную версию сборщика. Это критически важно для воспроизводимости: разные версии BuildKit могут иметь различное поведение. Полная документация по директиве `# syntax` приведена в разделе [BuildKit в Dockerfile](../dockerfile_buildkit.md).

**`# check=error=true`** — переводит сборку в строгий режим. Если BuildKit обнаружит использование `latest`, отсутствие `USER` или относительные пути в `WORKDIR`, сборка будет прервана. Это позволяет автоматически выявлять проблемы безопасности и соответствия best practices на этапе сборки. Подробнее о линтере и проверках — [BuildKit: линтер и проверки](../dockerfile_buildkit.md).

**`# escape`** — изменяет символ экранирования по умолчанию (`\`). Актуально только для Windows-контейнеров, где обратная косая используется в путях. Для Linux-контейнителей используется стандартный `\`.

### Классификация инструкций

**1. Инструкции, создающие слои (Layer-creating):**
Изменяют содержимое файловой системы. Каждый такой шаг увеличивает физический размер образа. Инвалидируют кэш сборки при изменении входных данных.

| Инструкция | Назначение | Ключевые возможности (2026) |
| :--- | :--- | :--- |
| `FROM` | Базовый образ | Поддержка `--platform`, именование стадий (`AS`). |
| `RUN` | Выполнение команд | Поддержка Heredocs (`<<EOF`), маунтов (`--mount`). |
| `COPY` | Копирование файлов | Флаги `--parents`, `--exclude`, `--link`, `--chmod`. |
| `ADD` | Продвинутое копирование | Флаг `--checksum` для валидации внешних ресурсов. |

**2. Инструкции метаданных (Metadata-only):**
Не создают слоев в файловой системе, но изменяют JSON-конфигурацию образа. Влияют на **Image Digest**, но не на размер слоев.

| Инструкция | Назначение | Влияние на рантайм |
| :--- | :--- | :--- |
| `WORKDIR` | Рабочий каталог | Устанавливает контекст для всех последующих команд. |
| `ENV` | Переменные окружения | Доступны приложению во время выполнения. |
| `ARG` | Переменные сборки | Доступны только во время сборки (не в рантайме). |
| `EXPOSE` | Сетевые порты | Документирует ожидаемые порты приложения. |
| `VOLUME` | Точки монтирования | Автоматически создает анонимные тома. |
| `LABEL` | Аннотации | Метаданные для Service Discovery и SBOM. |
| `USER` | Пользователь | Устанавливает UID/GID (рекомендуется >10000). |
| `SHELL` | Оболочка | Позволяет использовать Python/Node.js как shell. |
| `STOPSIGNAL` | Сигнал остановки | Настройка Graceful Shutdown (SIGTERM, SIGQUIT). |

**3. Инструкции выполнения и триггеры:**

| Инструкция | Назначение | Особенности |
| :--- | :--- | :--- |
| `CMD` | Аргументы по умолчанию | Легко переопределяются при `docker run`. |
| `ENTRYPOINT` | Точка входа | Основной процесс контейнера (PID 1). |
| `HEALTHCHECK` | Проверка здоровья | Мониторинг внутри Docker Engine/Swarm. |
| `ONBUILD` | Отложенный триггер | Выполняется, когда образ становится базовым. |

### Взаимодействие инструкций

Инструкции Dockerfile связаны друг с другом и влияют на поведение образа:

- **`FROM`** определяет базовый образ, от которого наследуются все последующие инструкции.
- **`ARG`** доступен только до `FROM` (если объявлен до него) или только в пределах стадии.
- **`ENV`** доступен и во время сборки, и во время выполнения. Может быть переопределён через `-e` при `docker run`.
- **`WORKDIR`** устанавливает рабочую директорию для всех последующих `RUN`, `CMD`, `ENTRYPOINT`, `COPY`, `ADD`.
- **`USER`** определяет, от имени какого пользователя выполняются команды `RUN`, `CMD`, `ENTRYPOINT`.
- **`VOLUME`** создаёт точку монтирования, но не привязывает её к хосту до `docker run -v`.
- **`EXPOSE`** — исключительно документирующая инструкция; она не открывает порты.

### Порядок инструкций

Рекомендуемый порядок инструкций в Dockerfile (согласно best practices):

```dockerfile
# 1. Директивы парсера (самые первые строки)
# syntax=docker/dockerfile:1

# 2. FROM (базовый образ)
FROM node:26-slim

# 3. Метаданные для сборки
ARG NODE_ENV=production
LABEL maintainer="team@example.com"
LABEL version="1.0"

# 4. Установка зависимостей (System deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 5. Рабочий каталог
WORKDIR /app

# 6. Копирование зависимостей (для кэширования)
COPY package*.json ./
RUN npm ci --only=production

# 7. Копирование кода приложения
COPY . .

# 8. Создание пользователя (безопасность)
RUN addgroup -g 1001 appgroup && adduser -u 1001 -G appgroup -s /bin/sh -D appuser
USER 1001

# 9. Переменные окружения
ENV NODE_ENV=production
ENV PORT=3000

# 10. Документирование портов
EXPOSE 3000

# 11. Healthcheck
HEALTHCHECK --interval=30s --timeout=3s CMD curl -f http://localhost:3000/health || exit 1

# 12. Точка входа
CMD ["node", "index.js"]
```

**Почему именно такой порядок:**
- Метаданные (`LABEL`, `ARG`) размещаются рано, чтобы быть доступными для инструкций ниже.
- Системные зависимости устанавливаются до копирования кода — это позволяет кэшировать слой с зависимостями.
- `USER` устанавливается до `CMD`/`ENTRYPOINT`, чтобы процесс запускался от непривилегированного пользователя.
- `HEALTHCHECK` размещается перед `CMD` для ясности.
## Новые возможности (v1.7 – v1.11+)

### Heredocs (Многострочные блоки)

Инструкция `RUN` поддерживает Heredoc-синтаксис (BuildKit 1.4+), что избавляет от необходимости использования цепочек `&& \` и делает скрипты читаемыми.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine
RUN <<EOF
    apk update
    apk add --no-cache curl git
    rm -rf /var/cache/apk/*
EOF
```

Heredocs позволяют использовать переменные окружения, интегрироваться с `--mount` и поддерживать несколько блоков в одном `RUN`. Полная документация по Heredocs, включая переменные, маунты и интеграцию с BuildKit, приведена в разделе [Инструкция RUN: Heredoc-синтаксис](./build_time_commands.md).

### Нативная аттестация (SBOM и Provenance)

В 2026 году BuildKit по умолчанию может генерировать отчеты о безопасности. Инструкции `LABEL` и `COPY` участвуют в формировании **SBOM (Software Bill of Materials)** — перечня всех компонентов, зависимостей и лицензий, входящих в образ.

SBOM позволяет:
- Отслеживать уязвимости в зависимостях (CVE).
- Соответствовать требованиям регуляторов (FSTEC, SOC2).
- Автоматизировать аудит безопасности в CI/CD.

Форматы SBOM: CycloneDX, SPDX. Инструменты генерации: Syft, Trivy. Полная документация — [SBOM и аттестация образов](../../Docker_security/docker_sbom.md).

### Переход на Containerd Store

Современные версии Docker Engine используют общее хранилище с Kubernetes через **Containerd Store**. Инструкции Dockerfile теперь генерируют слои, которые полностью совместимы с нативным форматом `containerd` без конвертации.

**Преимущества:**
- Устранение дублирования образов между Docker и Kubernetes.
- Единый формат хранения OCI-образов.
- Уменьшение использования дискового пространства.

**Влияние на Dockerfile:**
- Слои, созданные через `RUN`, `COPY`, `ADD`, автоматически совместимы с containerd.
- Образы, собранные через `docker buildx`, могут быть напрямую использованы в Kubernetes.
- Нет необходимости в дополнительных инструкциях для совместимости.

## Сводная таблица характеристик

| Инструкция | Создает слой | Инвалидирует кэш | Влияет на Digest |
| :--- | :---: | :---: | :---: |
| `RUN`, `COPY`, `ADD` | Да | Да | Да |
| `WORKDIR`, `USER`, `ENV` | Нет | Да | Да |
| `EXPOSE`, `LABEL`, `STOPSIGNAL` | Нет | Нет* | Да |
| `CMD`, `ENTRYPOINT` | Нет | Нет | Да |

*\* Изменение `LABEL` не инвалидирует кэш для предыдущих слоев, но может повлиять на последующие, если они используют эти метки через скрипты.*

**Как работает инвалидация кэша:**
- **`RUN`** — кэш сброшен, если изменились аргументы команды или содержимое файлов, используемых в команде.
- **`COPY` / `ADD`** — кэш сброшен, если изменилось содержимое копируемых файлов (по checksum).
- **`ENV`** — кэш сброшен при изменении значения переменной.
- **`ARG`** — кэш сброшен при передаче нового значения через `--build-arg`.
- **`WORKDIR`** — кэш сброшен при изменении пути.

**Совет по оптимизации:** Группируйте команды `RUN` и кэшируйте зависимости отдельно от кода приложения. Копируйте `package.json` / `go.mod` / `requirements.txt` до остальных файлов — это позволит кэшировать установку зависимостей.

## Практические сценарии

### Сценарий 1: Минимальный безопасный Dockerfile

Базовый шаблон Dockerfile с основными best practices: непривилегированный пользователь,.healthcheck, минимизация размера.

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Системные зависимости (только необходимые)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Рабочий каталог
WORKDIR /app

# Зависимости (кэшируются отдельно от кода)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY . .

# Пользователь (безопасность)
RUN addgroup --gid 1001 appgroup && \
    adduser --uid 1001 --gid 1001 --disabled-password --gecos "" appuser
USER 1001

# Переменные окружения
ENV PYTHONUNBUFFERED=1
ENV APP_ENV=production

# Порты
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=3s \
    CMD curl -f http://localhost:8000/health || exit 1

# Запуск
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Сценарий 2: Строгая проверка (Best Practice 2026)

Использование `# check` для предотвращения типичных ошибок безопасности на этапе сборки.

```dockerfile
# syntax=docker/dockerfile:1
# check=error=true

FROM node:26-slim
WORKDIR /app
# Ошибка сборки: использование root (прервано линтером BuildKit)
COPY . .
CMD ["node", "index.js"]
```

**Что проверяет `# check=error=true`:**
- Использование тегов `:latest` вместо конкретных версий.
- Отсутствие инструкции `USER` (запуск от root).
- Относительные пути в `WORKDIR`.
- Использование `apt-get` без `--no-install-recommends`.
- Копирование всего контекста (`COPY . .`) без `.dockerignore`.

Подробнее о линтере и проверках — [BuildKit: линтер и проверки](../dockerfile_buildkit.md).

### Сценарий 3: Продвинутое копирование (Monorepo)

Использование `--parents` для сохранения структуры папок без сложных `mkdir`.

```dockerfile
# syntax=docker/dockerfile:1.7-labs
FROM alpine
COPY --parents services/api/config.json /dist/
# Результат в образе: /dist/services/api/config.json
```

**Альтернатива без `--parents`:**
```dockerfile
FROM alpine
RUN mkdir -p /dist/services/api
COPY services/api/config.json /dist/services/api/
```

Флаг `--parents` значительно упрощает копирование файлов из монорепозиториев. Полная документация — [Инструкция COPY: флаг --parents](./copying_files.md).

### Сценарий 4: Multi-stage сборка

Разделение этапов сборки и запуска для минимизации размера образа.

```dockerfile
# syntax=docker/dockerfile:1

# Стадия 1: Сборка
FROM golang:1.27-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /app .

# Стадия 2: Runtime (минимальный образ)
FROM alpine:3.24
RUN addgroup -g 1001 appgroup && adduser -u 1001 -G appgroup -s /bin/sh -D appuser
COPY --from=builder /app /app
USER 1001
EXPOSE 8080
CMD ["/app"]
```

**Преимущества multi-stage:**
- Стадия сборки содержит инструменты компиляции (Go, Maven, npm) — они не попадают в финальный образ.
- Финальный образ содержит только бинарник/приложение и минимальные зависимости.
- Размер образа уменьшается в 10-50 раз.

### Сценарий 5: Кэширование зависимостей

Стратегия копирования файлов для максимального переиспользования кэша.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:26-slim
WORKDIR /app

# Шаг 1: Копируем файлы зависимостей (редко меняются)
COPY package.json package-lock.json ./

# Шаг 2: Устанавливаем зависимости (кэшируется, пока package.json не изменится)
RUN npm ci --only=production

# Шаг 3: Копируем код приложения (часто меняется)
COPY . .
```

**Почему это работает:**
- Docker кэширует результат каждого шага.
- Если изменился только код приложения (не `package.json`), шаги 1-2 берутся из кэша.
- Установка зависимостей (`npm ci`) — самая времязатратная операция; её кэширование экономит секунды/минуты.

### Сценарий 6: Использование ARG для параметризации

Передача параметров сборки через `--build-arg` для разных окружений.

```dockerfile
# syntax=docker/dockerfile:1
ARG NODE_VERSION=24
FROM node:${NODE_VERSION}-slim

ARG APP_ENV=production
ARG BUILD_DATE
ARG VERSION

LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.environment="${APP_ENV}"

WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .

ENV NODE_ENV=${APP_ENV}
EXPOSE 3000
CMD ["node", "index.js"]
```

**Сборка для разных окружений:**
```bash
# Продакшен
docker build \
    --build-arg NODE_VERSION=24 \
    --build-arg APP_ENV=production \
    --build-arg BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ") \
    --build-arg VERSION=1.2.3 \
    -t myapp:prod .

# Разработка
docker build \
    --build-arg NODE_VERSION=24 \
    --build-arg APP_ENV=development \
    -t myapp:dev .
```

Подробнее об `ARG` и `ENV` — [Инструкции ENV и ARG](./environment_variables.md).
### Сценарий 7: Копирование SSH-ключей для приватных зависимостей

Безопасное копирование SSH-ключей для доступа к приватным репозиториям (GitHub, GitLab) без сохранения ключей в образе.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.24
RUN apk add --no-cache git openssh

# Монтирование SSH-ключа (ключ НЕ попадает в слой образа)
RUN --mount=type=ssh git clone git@github.com:private/repo.git /app

WORKDIR /app
CMD ["ls", "-la"]
```

**Сборка и запуск:**
```bash
# Сборка с пробросом SSH-агента
eval $(ssh-agent)
ssh-add ~/.ssh/id_rsa
docker build --ssh default -t myapp .

# Запуск (SSH-агент доступен контейнеру)
docker run --rm -it --ssh default myapp
```

Подробнее о маунтах — [Инструкция RUN: маунты BuildKit](./build_time_commands.md).

### Сценарий 8: Использование .dockerignore

Управление контекстом сборки через `.dockerignore` для исключения ненужных файлов.

**Пример `.dockerignore`:**
```
# Системные файлы
.git
.github
.vscode
.idea

# Зависимости (переустанавливаются в RUN)
node_modules
vendor
__pycache__

# Тесты и документация
tests
docs
*.md
README*

# Сборочные артефакты
dist
build
*.log
```

**Влияние на кэш:**
- Без `.dockerignore`: изменение `.git/config` инвалидирует кэш для `COPY . .`.
- С `.dockerignore`: `.git` исключён, кэш сохраняется.

Подробнее — [Контекст сборки и .dockerignore](../dockerfile_build_context.md).

### Сценарий 9: ONBUILD для базовых образов

Использование `ONBUILD` для создания базовых образов, которые автоматизируют настройку для дочерних проектов.

**Базовый образ (Dockerfile.base):**
```dockerfile
FROM node:26-slim
WORKDIR /app
ONBUILD COPY package*.json ./
ONBUILD RUN npm ci --only=production
ONBUILD COPY . .
```

**Дочерний образ (Dockerfile):**
```dockerfile
FROM my-base:latest
# ONBUILD инструкции выполняются автоматически при сборке
CMD ["node", "index.js"]
```

**Ограничения:**
- `ONBUILD` не может вызвать другую инструкцию `ONBUILD`.
- `ONBUILD` не может ссылаться на `FROM` или `MAINTAINER`.
- Используйте с осторожностью — это скрытая логика, которую сложно отлаживать.

### Сценарий 10: Динамические метаданные через LABEL

Автоматическое добавление метаданных для отслеживания версий и.owner.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.24

ARG BUILD_DATE
ARG VERSION
ARG GIT_SHA

LABEL org.opencontainers.image.title="My Application"
LABEL org.opencontainers.image.description="Production-ready application"
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.revision="${GIT_SHA}"
LABEL org.opencontainers.image.vendor="Engineering Team"
LABEL org.opencontainers.image.licenses="MIT"
```

**Сборка с метаданными:**
```bash
docker build \
    --build-arg BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ") \
    --build-arg VERSION=1.2.3 \
    --build-arg GIT_SHA=$(git rev-parse HEAD) \
    -t myapp:1.2.3 .
```

**Просмотр метаданных:**
```bash
docker inspect myapp:1.2.3 | jq '.[0].Config.Labels'
```

## Типичные ошибки и их решение

### Ошибка 1: Использование :latest вместо конкретных версий

**Проблема:** `FROM ubuntu` без тега = `FROM ubuntu:latest`. Поведение сборки не воспроизводимо — сегодня это 24.04, завтра может быть 24.10.

```dockerfile
# ПЛОХО: не воспроизводимо
FROM ubuntu
FROM node
FROM python

# ХОРОШО: конкретная версия
FROM ubuntu:24.04
FROM node:26-slim
FROM python:3.12-alpine
```

**Решение:** Включите `# check=error=true` для автоматического выявления этой ошибки.

### Ошибка 2: Запуск от root

**Проблема:** По умолчанию процессы в контейнере запускаются от root. Если приложение будет скомпрометировано, злоумышленник получит root-доступ.

```dockerfile
# ПЛОХО: процесс запускается от root
FROM node:26-slim
WORKDIR /app
COPY . .
CMD ["node", "index.js"]

# ХОРОШО: непривилегированный пользователь
FROM node:26-slim
WORKDIR /app
RUN addgroup --gid 1001 appgroup && \
    adduser --uid 1001 --gid 1001 --disabled-password --gecos "" appuser
USER 1001
COPY --chown=1001:1001 . .
CMD ["node", "index.js"]
```

### Ошибка 3: Копирование всего контекста без .dockerignore

**Проблема:** `COPY . .` копирует ВСЁ из контекста сборки, включая `.git`, `node_modules`, `tests`, что увеличивает размер образа и инвалидирует кэш.

**Решение:** Создайте `.dockerignore` с исключениями (см. Сценарий 8).

### Ошибка 4: Слишком много слоёв

**Проблема:** Каждая инструкция `RUN` создаёт отдельный слой. 10 команд `RUN` = 10 слоёв = увеличение размера и сложность отладки.

```dockerfile
# ПЛОХО: 4 слоя
RUN apt-get update
RUN apt-get install -y curl
RUN apt-get install -y git
RUN rm -rf /var/lib/apt/lists/*

# ХОРОШО: 1 слой
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl git && \
    rm -rf /var/lib/apt/lists/*
```

### Ошибка 5: Неправильный порядок инструкций

**Проблема:** Копирование кода до зависимостей приводит к инвалидации кэша при каждом изменении кода.

```dockerfile
# ПЛОХО: зависимость от кода инвалидирует кэш
COPY . .
RUN npm ci

# ХОРОШО: зависимости кэшируются отдельно
COPY package*.json ./
RUN npm ci
COPY . .
```

### Ошибка 6: Использование ADD без необходимости

**Проблема:** `ADD` имеет неявное поведение (автоматическое распаковка tar-архивов, загрузка URL). Для простого копирования файлов используйте `COPY`.

```dockerfile
# ПЛОХО: ADD для простого копирования
ADD config.json /app/config.json

# ХОРОШО: COPY для простого копирования
COPY config.json /app/config.json

# ХОРОШО: ADD для распаковки архива
ADD archive.tar.gz /app/
```

## Лучшие практики

### Безопасность

1. **Всегда используйте `USER`** — никогда не запускайте приложение от root в продакшене.
2. **Используйте `# check=error=true`** — автоматически выявляйте проблемы на этапе сборки.
3. **Не храните секреты в `ENV`/`ARG`** — они видны в `docker inspect`. Используйте `--secret` или внешние менеджеры секретов.
4. **Сканируйте образы** — используйте Trivy, Snyk или Docker Scout для проверки уязвимостей.
5. **Используйте многостадийные сборки** — минимизируйте количество пакетов в финальном образе.

### Производительность

1. **Кэшируйте зависимости отдельно** — копируйте файлы зависимостей до кода приложения.
2. **Группируйте команды `RUN`** — уменьшайте количество слоёв.
3. **Используйте `--no-install-recommends`** — уменьшайте размер системных пакетов.
4. **Используйте official images** — они оптимизированы и регулярно обновляются.
5. **Используйте `COPY --link`** (BuildKit 1.5+) — копирование без инвалидации кэша предыдущих слоёв.

### Читаемость

1. **Следуйте рекомендуемому порядку** — FROM, LABEL, RUN, WORKDIR, COPY, USER, ENV, EXPOSE, CMD.
2. **Используйте Heredocs** для многострочных команд — избегайте цепочек `&& \`.
3. **Комментируйте неочевидные решения** — объясняйте _почему_, а не _что_.
4. **Используйте `.dockerignore`** — исключайте ненужные файлы из контекста сборки.

### Воспроизводимость

1. **Закрепляйте версии** — используйте конкретные теги вместо `:latest`.
2. **Используйте `# syntax`** — указывайте версию синтаксиса Dockerfile.
3. **Фиксируйте dependency lock-файлы** — `package-lock.json`, `go.sum`, `requirements.txt`.
4. **Используйте `ARG` для дат и версий** — метаданные сборки должны быть параметризованы.

## Граничные случаи и ограничения

### Ограничение: Один ENTRYPOINT на контейнер

Контейнер может иметь только один `ENTRYPOINT`. Если базовый образ определяет `ENTRYPOINT`, дочерний образ может переопределить его, но не дополнить.

```dockerfile
# Базовый образ
FROM alpine:3.24
ENTRYPOINT ["/bin/sh"]

# Дочерний образ: ENTRYPOINT перезаписывается
FROM my-base:latest
ENTRYPOINT ["/bin/bash"]  # Вместо /bin/sh
```

### Ограничение: ONBUILD не поддерживает вложенность

Инструкция `ONBUILD` не может вызвать другую инструкцию `ONBUILD`:

```dockerfile
# ОШИБКА: вложенный ONBUILD
FROM alpine
ONBUILD ONBUILD RUN echo "nested"  # BuildKit проигнорирует или выдаст ошибку
```

### Ограничение: Кэш и переменные окружения

Изменение `ENV` инвалидирует кэш для всех последующих инструкций, даже если они не используют эту переменную:

```dockerfile
FROM node:26-slim
ENV APP_ENV=production
RUN apt-get update  # Кэш сброшен, даже если APP_ENV не используется здесь
```

### Ограничение: Многостадийные сборки и кэш

Кэш каждой стадии multi-stage сборки изолирован. Изменение в стадии builder не влияет на кэш стадии runtime (если не изменился `COPY --from`).

### Ограничение: Digest и теги

Digest образа (`sha256:...`) не обновляется автоматически при изменении тега. Один и тот же тег может указывать на разные digest:

```bash
# Проверка digest
docker inspect --format='{{index .RepoDigests 0}}' node:26-slim
# → node@sha256:abc123...

# Через неделю digest может измениться
docker pull node:26-slim
docker inspect --format='{{index .RepoDigests 0}}' node:26-slim
# → node@sha256:def456...
```

### Ограничение: Windows-контейнеры и #escape

На Windows-контейнерах символ `\` используется в путях (например, `C:\Windows\System32`). Директива `# escape` позволяет изменить символ экранирования на `` ` ``:

```dockerfile
# escape=`
FROM windowsservercore
RUN dir C:\Windows\System32
```

### Ограничение: BuildKit отключён (legacy builder)

В окружениях с устаревшим Docker (до 23.0) или принудительно отключённом BuildKit (`DOCKER_BUILDKIT=0`) некоторые инструкции и директивы недоступны:

```bash
# Проверка режима
echo $DOCKER_BUILDKIT  # 0 = legacy, 1 = BuildKit

# Legacy builder: нет поддержки Heredocs, --mount, --parents
docker build --no-cache .
```

**Ограничения legacy builder:**
- Нет Heredoc-синтаксиса (`<<EOF`)
- Нет mount-монтирований (`--mount=type=ssh`)
- Нет флага `--parents` в `COPY`
- Нет встроенного линтинга (`# check`)
- Нет SBOM и Provenance по умолчанию

**Решение:** Обновите Docker до 23.0+ или включите BuildKit через демона (`/etc/docker/daemon.json`).

### Ограничение: Rootless Docker и сборка

Rootless Docker имеет ограничения на сборку образов:
- Нет доступа к `docker` группе
- Нет возможности использовать `--platform` без дополнительных разрешений
- BuildKit может требовать явного указания драйвера

```bash
# Проверка режима
docker info | grep -i rootless

# Сборка в Rootless
docker build --build-arg BUILDKIT_PROGRESS=plain .
```

### Ограничение: Air-gapped окружения

В изолированных сетях (без доступа к интернету) сборка требует предварительной подготовки:
- Базовые образы должны быть загружены в локальный registry
- `docker buildx build --output=type=local` для экспорта артефактов
- Kaniko или BuildKit в режиме `--oci` для сборки без демона Docker

```bash
# Загрузка базового образа в локальный registry
docker pull alpine:3.24
docker tag alpine:3.24 localhost:5000/alpine:3.24
docker push localhost:5000/alpine:3.24

# Сборка из локального registry
docker build --registry-mirror http://localhost:5000 -t myapp .
```

### Ограничение: Воспроизводимость и `SOURCE_DATE_EPOCH`

Для детерминированных сборок (reproducible builds) используйте `SOURCE_DATE_EPOCH`:
- Фиксирует временные метки в слоях
- Гарантирует одинаковые digest для одного исходного кода
- Важно для compliance и аудита

```dockerfile
# syntax=docker/dockerfile:1
ARG SOURCE_DATE_EPOCH=1735689600
FROM alpine:3.24
RUN touch /build-$(date -u -d "@$SOURCE_DATE_EPOCH" +"%Y-%m-%d")
```

```bash
# Сборка с фиксированной датой
docker build --build-arg SOURCE_DATE_EPOCH=1735689600 -t myapp:reproducible .
```

### Ограничение: Дисковое пространство и кэш сборки

BuildKit кэширует промежуточные слои на диске. При нехватке места:
- Используйте `docker builder prune` для очистки неиспользуемого кэша
- Настройте `buildkitd.toml` для ограничения размера кэша
- Используйте `--no-cache` для полной пересборки (не влияет на хранилище)

```bash
# Очистка кэша
docker builder prune -a --filter until=24h

# Проверка размера кэша
docker system df -v | grep Build
```

### Ограничение: Режим BuildKit daemon vs client

BuildKit может работать в двух режимах:
- **Daemon mode** (по умолчанию в Docker 23.0+): кэш сохраняется между сборками
- **Client mode** (`buildctl`): изолированные сборки, нет персистентного кэша

```bash
# Daemon mode (Docker CLI)
docker build -t myapp .

# Client mode (buildctl)
buildctl build --frontend=dockerfile.v0 --local context=. --local dockerfile=.
```

### Ограничение: Параллелизм и лимиты ресурсов

BuildKit использует параллельные воркеры для ускорения сборки:
- По умолчанию: число воркеров = количество CPU cores
- Ограничьте через `--cpu-shares` или `buildkitd.toml`
- В CI/CD окружениях используйте `--build-arg BUILDKIT_MAX_CPU=2`

```bash
# Ограничение ресурсов
docker build --build-arg BUILDKIT_MAX_CPU=2 --build-arg BUILDKIT_MAX_MEM=4g -t myapp .
```

## Валидация

### Проверка версии Docker Engine

```bash
# Минимальная версия для BuildKit по умолчанию
docker version --format '{{.Server.Version}}'
# → 24.0.5 (требуется 20.10+)

# Проверка версии клиента
docker version --format '{{.Client.Version}}'
```

### Проверка статуса BuildKit

```bash
# BuildKit по умолчанию в Docker 23.0+
docker info | grep -i buildkit
# → BuildKit: Enabled (true)

# Проверка через переменную окружения
echo $DOCKER_BUILDKIT
# → 1 (включён) или пусто (используется значение по умолчанию)
```

### Проверка синтаксиса директив парсера

```bash
# Линтинг Dockerfile
docker build --check -t myapp .
# → error: FROM requires a tag

# Строгий режим
# syntax=docker/dockerfile:1
# check=error=true
```

### Проверка отсутствия секретов в слоях

```bash
# Анализ истории слоёв
docker history myapp:latest
# → Проверьте, нет ли команд с секретами (API keys, пароли, токены)

# Сканирование секретов
trivy image --scanners secret myapp:latest
# → Проверка на наличие ключей, паролей, токенов
```

### Проверка эффективности .dockerignore

```bash
# Размер контекста до/после .dockerignore
tar -czf context-before.tar.gz .
tar -czf context-after.tar.gz .  # с .dockerignore

# Разница в размере = эффективность исключений
```

### Проверка размера образа и количества слоёв

```bash
# Размер образа
docker images myapp:latest
# → myapp latest 123MB 2 hours ago

# Количество слоёв
docker inspect myapp:latest --format '{{len .RootFS.Layers}}'
# → 5 (оптимально: 5-10 для большинства приложений)

# Анализ слоёв
dive myapp:latest
# → Визуализация каждого слоя и его размера
```

### Проверка генерации SBOM

```bash
# Генерация SBOM через Syft
syft myapp:latest -o cyclonedax-json > sbom.json

# Проверка через Trivy
trivy image --format cyclonedx myapp:latest > sbom-trivy.json

# Валидация SBOM
jq '.components | length' sbom.json
# → Количество компонентов в образе
```

## Дополнительная информация

### Правила именования
- **Стандарт:** `Dockerfile` (без расширения).
- **Альтернативы:** `Dockerfile.dev`, `Dockerfile.prod`.
- **Bake:** Для сложных проектов используйте **[docker-bake.hcl](../docker-bake.md)** для параллельной сборки.

**См. также:**
- **[BuildKit в Dockerfile](../dockerfile_buildkit.md)** — архитектура, LLB-граф, линтер и проверки.
- **[Контекст сборки и .dockerignore](../dockerfile_build_context.md)** — управление файлами и оптимизация контекста.
