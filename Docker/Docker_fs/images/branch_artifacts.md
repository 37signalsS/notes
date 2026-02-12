# Docker-образы в разных бранчах

## Вопрос: Один артефакт или разные?

**Сценарий:** Dockerfile добавлен в бранч `dev`, образ собран и в `dev`, и в `stage`.

**Ответ:** Это будут **разные артефакты**, даже если Dockerfile одинаковый.

## Почему разные артефакты?

```
Бранч dev:
┌─────────────────────────────────────────────────────────────┐
│  dev: Dockerfile ──► docker build ──► myapp:dev-{hash}     │
│                                                              │
│  Контекст сборки:                                           │
│  - Git commit: abc123 (dev)                                 │
│  - Base image: ubuntu:20.04 (latest на момент сборки)      │
│  - Build args: ENV=development                              │
│  - Слои: [base]─[deps]─[code@abc123]─[config-dev]          │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ Разные!
                              ▼
Бранч stage:
┌─────────────────────────────────────────────────────────────┐
│  stage: Dockerfile ──► docker build ──► myapp:stage-{hash} │
│                                                              │
│  Контекст сборки:                                           │
│  - Git commit: def456 (stage)                               │
│  - Base image: ubuntu:20.04 (возможно другой digest!)      │
│  - Build args: ENV=staging                                  │
│  - Слои: [base]─[deps]─[code@def456]─[config-stage]        │
└─────────────────────────────────────────────────────────────┘
```

## Факторы, создающие различия

| Фактор | Влияние | Результат |
|--------|---------|-----------|
| **Git-история** | Разные коммиты = разный код | Разные слои COPY |
| **Base image** | `ubuntu:latest` меняется | Может быть разный base layer |
| **Build args** | `ENV=dev` vs `ENV=prod` | Разные инструкции RUN |
| **Build context** | Разные файлы в бранче | Разные слои COPY |

## Immutable артефакты: Лучшая практика

```dockerfile
# Dockerfile с явным версионированием
FROM ubuntu:20.04@sha256:abc123...  # Пиним digest!

ARG APP_VERSION
ARG BUILD_ENV

# Установка зависимостей (кэшируется)
RUN apt-get update && apt-get install -y \
    python3=3.8.10-0ubuntu1 \
    && rm -rf /var/lib/apt/lists/*

# Копирование кода
COPY . /app

# Сборка с версией
RUN echo "Building ${APP_VERSION} for ${BUILD_ENV}"

LABEL git.commit=$GIT_COMMIT \
      build.env=$BUILD_ENV \
      build.date=$BUILD_DATE
```

```bash
# Сборка с полным контролем
DOCKER_BUILDKIT=1 docker build \
  --build-arg APP_VERSION=1.2.3 \
  --build-arg BUILD_ENV=dev \
  --build-arg GIT_COMMIT=$(git rev-parse HEAD) \
  --build-arg BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ') \
  -t myapp:1.2.3-dev-$(git rev-parse --short HEAD) \
  -t myapp:1.2.3-dev-latest \
  .
```
