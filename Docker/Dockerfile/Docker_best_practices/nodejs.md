# Dockerfile: Лучшие практики для Node.js

**Актуально для:** Node.js 26.x

## Определения

- **package.json / package-lock.json:** Манифест проекта и файл фиксации точных версий зависимостей. Для Yarn это `yarn.lock`, для Pnpm — `pnpm-lock.yaml`.
- **Corepack:** Встроенный в Node.js инструмент для управления менеджерами пакетов. Позволяет использовать `pnpm` и `yarn` без их глобальной установки в образе.
- **npm ci (Clean Install):** Команда для установки зависимостей в CI-средах. Строго следует lock-файлу, удаляет существующие `node_modules` и работает быстрее обычного `install`.
- **node-gyp:** Инструмент для компиляции нативных аддонов (C/C++). Требует наличия Python и компилятора (build-essential) в образе на этапе сборки.
- **Tini:** Легковесный инициализатор (init), решающий проблему PID 1 (обработка сигналов и удаление "зомби-процессов") в контейнерах.
- **Pruning:** Процесс удаления `devDependencies` из папки `node_modules` после этапа сборки для минимизации финального образа.
- **Graceful Shutdown:** Процесс корректного завершения работы приложения (закрытие соединений с БД, HTTP-сервера) при получении сигналов `SIGTERM` или `SIGINT`.
- **Bun / Deno:** Альтернативные среды выполнения JavaScript/TypeScript, предлагающие встроенную поддержку TypeScript и более высокую производительность сборки.
- **docker init:** Команда Docker Desktop для автоматической генерации Dockerfile, docker-compose.yml и .dockerignore на основе анализа проекта. Поддерживает Node.js, Go, Python, .NET, Rust, Java.
- **dotenv:** Паттерн загрузки переменных окружения из файла `.env` в приложение. В контейнерах `.env` файлы не должны попадать в образ — их передают через `--env-file` или `--env` при запуске.
- **cross-env:** Утилита для кроссплатформенной установки переменных окружения в npm-скриптах. Решает проблему различий между `export VAR=val` (Unix) и `set VAR=val` (Windows) в package.json.

## Предварительные требования

- **Docker Engine 24+** с включённым BuildKit (`DOCKER_BUILDKIT=1` или `"features": { "buildkit": true }` в `daemon.json`).
- **Node.js 26.x LTS** как целевая версия runtime. Для сборки может использоваться та же или более новая версия.
- Понимание принципов **multi-stage сборки** и механики слоёв Docker.
- Знание особенностей **cgroups v2** в целевой ОС хоста (Ubuntu 22.04+, RHEL 9+, Debian 12+), так как они влияют на лимиты памяти и CPU в контейнере.
- Наличие `.dockerignore` в корне проекта для исключения `node_modules`, `.git`, секретов и артефактов сборки из контекста.

## Базовые концепции

### Выбор базового образа

В 2026 году стандартом остаются образы на базе **Alpine** и **Debian Slim**:
- `node:26-alpine` (LTS) — ~168 МБ (сжатый образ). Минимальный размер, но требует осторожности с нативными модулями из-за `musl libc`.
- `node:26-slim` (LTS) — ~232 МБ (сжатый образ). База Debian, лучшая совместимость с нативными зависимостями.
- **Google Distroless:** `gcr.io/distroless/nodejs24-debian12` — максимальная безопасность (нет shell, нет пакетных менеджеров).

**Важно о версионировании:**
- Используйте конкретные теги версий (`node:26-alpine`, а не `node:alpine`) для воспроизводимости.
- В production рекомендуется pinning по SHA256 дайджесту: `node:26-alpine@sha256:abc123...` — гарантирует, что образ не будет изменён.
- Для multi-stage сборки пинните обе стадии (builder и runtime) одним дайджестом.

### Управление ресурсами и V8

Node.js в контейнерах требует ручной настройки лимитов V8, так как по умолчанию движок не знает о cgroups и может превысить лимиты памяти контейнера.

*   **Memory Limit:** Используйте `NODE_OPTIONS="--max-old-space-size=X"`, где X составляет 75-80% от лимита памяти контейнера. Это правило учитывает:
    - `--max-old-space-size` ограничивает только V8 heap (старое поколение), но не стек, внешнюю память (native addons) и внутренние структуры V8.
    - Оставшиеся 20-25% необходимы для стека вызовов, зон V8 (code space, map space) и нативных модулей (`node-gyp`).
    - При достижении лимита V8 пытается выполнить garbage collection; если не помогает — процесс завершается с `FATAL ERROR: Reached heap limit`.
    - **Расчёт:** `--max-old-space-size=1024` для контейнера с `--memory=1536m` (75% от 1536).

*   **CPU:** Node.js однопоточен для выполнения JS (event loop), но использует дополнительные потоки для I/O и `worker_threads`. Для корректного масштабирования:
    - Минимум 1 CPU (`--cpus=1`) для небольших сервисов.
    - При использовании `worker_threads` учитывайте их в общем лимите.
    - В Kubernetes лимиты CPU throttling (`cpu.cfs_quota_us` / `cpu.cfs_period_us`) могут снижать пропускную способность при пиковых нагрузках.

*   **cgroups v2:** В современных дистрибутивах (Ubuntu 22.04+, RHEL 9+, Debian 12+) используются cgroups v2, где:
    - `memory.max` — жёсткий лимит, при превышении которого OOM killer завершает процесс.
    - `memory.high` — мягкий лимит, при превышении которого kernel принудительно сжимает кэш и замедляет процесс (memory pressure).
    - Node.js не отслеживает `memory.high` автоматически — только `memory.max`. Настройте `--max-old-space-size` с запасом под `memory.high`.

### Обработка сигналов и PID 1

В Linux процесс с PID 1 имеет особые semantics: он не Inherit signal dispositions по умолчанию и не автоматически убирает зомби-процессы. Node.js как PID 1 игнорирует большинство сигналов, что приводит к:

- **Незавершаемым контейнерам:** `docker stop` отправляет `SIGTERM`, но `node` его не обрабатывает → через 10 секунд Docker отправляет `SIGKILL` (принудительное завершение).
- **Накоплению зомби:** Дочерние процессы (воркеры, `child_process`) завершаются, но `waitpid()` не вызывается → зомби накапливаются в таблице процессов.
- **Утечкам ресурсов:** При `SIGKILL` не вызываются `process.on('exit')` и `server.close()`, соединения с БД и HTTP-клиентами остаются в `ESTABLISHED` состоянии.

**Решение:** Используйте `tini` или флаг `--init` в Docker. Tini становится PID 1, пробрасывает сигналы дочернему процессу и вызывает `waitpid()` для зомби. Подробнее: [Init Process в Docker: tini](../../Docker/Dockerfile/init_process_tini.md).

**Graceful Shutdown:** Приложение должно явно обрабатывать сигналы и корректно завершать работу:

```javascript
const shutdown = (signal) => {
  console.log(`Received ${signal}, shutting down gracefully...`);
  
  // Перестаём принимать новые соединения
  server.close(() => {
    console.log('HTTP server closed');
    process.exit(0);
  });
  
  // Принудительное завершение через таймаут
  setTimeout(() => {
    console.error('Forced shutdown after timeout');
    process.exit(1);
  }, 10000);
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
```

**Важно для Kubernetes:** K8s отправляет `SIGTERM` перед `SIGKILL` (по умолчанию 30 секунд). Настройте `terminationGracePeriodSeconds` в манифесте и `StartupProbe` с `failureThreshold` для корректного завершения.

### PM2 в контейнерах (антипаттерн)

PM2 — process manager для bare-metal Node.js. В контейнерах он **не нужен и вреден**:

*   **Дублирование функций:** Docker/Kubernetes перезапускают контейнер при падении — PM2 дублирует эту логику внутри контейнера.
*   **Сигналы:** PM2 как PID 1 перехватывает `SIGTERM` и может мешать graceful shutdown приложения.
*   **Cluster mode:** PM2 cluster mode форкает несколько процессов Node — в Kubernetes это мешает горизонтальному масштабированию (реплики) и корректному учёту CPU-лимитов.

**Когда PM2 оправдан:** legacy-приложения, требующие cluster mode без возможности рефакторинга, или несколько тесно связанных Node-процессов (но тогда предпочтительнее `s6-overlay`/`supervisord` — см. [Multi-process контейнеры](../../Docker_logs/docker_multi_process_logging.md)).

```dockerfile
# Если PM2 всё же необходим (legacy)
FROM node:26-alpine
RUN npm install -g pm2
# pm2-runtime — foreground-режим, обязательный для Docker (daemon-режим PM2 не подходит)
CMD ["pm2-runtime", "ecosystem.config.js"]
```

**Валидация:**
```bash
docker run --rm my-app pm2-runtime --version
# → 5.x.x
```

### Безопасность и аудит

*   **npm audit:** Интегрируйте в процесс сборки: `RUN npm audit --audit-level=high`. Если аудит провалился — сборка прервётся. В критичных продакшн-сценариях используйте `--audit-level=critical` только для критических уязвимостей.
*   **Rootless:** Никогда не запускайте приложение от `root`. Используйте встроенного пользователя `node` (UID 1000 в большинстве образов). Для дополнительной изоляции создайте собственного пользователя с `addgroup -S nodejs && adduser -S nodejs -G nodejs`.
*   **Секреты:** Используйте `--mount=type=secret,id=npmrc,target=/app/.npmrc` для безопасной установки приватных пакетов. Никогда не копируйте `.npmrc` или `.env` файлы через `COPY` — они попадут в слой образа.
*   **Сканирование образов:** После сборки сканируйте образ через Trivy или Snyk: `trivy image my-app:latest`.

## Практические сценарии

### Сценарий 0: `.dockerignore` для Node.js

Правильный `.dockerignore` исключает файлы, которые не должны попадать в контекст сборки. Это ускоряет передачу данных в BuildKit и предотвращает утечку секретов в слои образа.

```dockerignore
# Зависимости
node_modules
.pnpm-store
.yarn/cache
.npm

# Исходный код и конфигурация
.git
.env
.env.*
!.env.example
.npmrc

# Артефакты сборки
dist
build
out
coverage
*.log

# Инфраструктура
Dockerfile
docker-compose*.yml
.dockerignore

# Файлы IDE и ОС
.idea
.vscode
*.swp
.DS_Store
Thumbs.db
```

**Почему это важно:**
- `node_modules` в контексте может занимать 500+ МБ и ломать кэш слоёв.
- `.env` и `.npmrc` с секретами никогда не должны попадать в образ.
- `.git` содержит историю коммитов с потенциальными секретами.

**Валидация:**
```bash
# Проверка размера контекста сборки
docker build --no-cache --progress=plain . 2>&1 | grep "Sending build context"
# → Sending build context to Docker daemon  1.2MB

# Без .dockerignore контекст может быть 50-500MB
```

### Сценарий 1: Многоэтапная сборка (TypeScript + BuildKit + Tini)

Эталонный шаблон для Node.js 24 LTS.

```dockerfile
# syntax=docker/dockerfile:1
# check=error=true

# --- Этап 1: Сборка (builder) ---
FROM node:26-alpine@sha256:... AS builder
WORKDIR /app

# Копируем манифесты для кэширования слоев
COPY package.json package-lock.json ./

# Используем монтирование кэша npm для ускорения последующих сборок
RUN --mount=type=cache,target=/root/.npm \
    npm ci && \
    npm audit --audit-level=high

# Копируем код и собираем проект
COPY . .
RUN npm run build && \
    # Оставляем только production зависимости
    npm prune --omit=dev

# --- Этап 2: Финальный образ (runtime) ---
FROM node:26-alpine@sha256:...
RUN apk add --no-cache tini
WORKDIR /app

# Настройки окружения
ENV NODE_ENV=production \
    NODE_OPTIONS="--max-old-space-size=1024"

# Копируем только артефакты
COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist

# Безопасность
USER node

# Проверка здоровья через встроенный fetch (Node.js 20+)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD node --eval "fetch('http://localhost:3000/health').then(r => process.exit(r.ok ? 0 : 1))"

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "dist/main.js"]
```

**Валидация:**
```bash
# Проверка что контейнер запущен от node (не root)
docker exec <container> id
# → uid=1000(node) gid=1000(node) groups=1000(node)

# Проверка HEALTHCHECK статуса
docker inspect --format='{{json .State.Health}}' <container>

# Проверка что devDependencies не попали в образ
docker run --rm my-app:latest ls node_modules | grep -E "jest|eslint|mocha" || echo "devDependencies не найдены"
# → devDependencies не найдены
```

**Запуск с переменными окружения:**
```bash
# Использование .env файла (не попадает в образ)
docker run -d \
  --env-file .env.production \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  -p 3000:3000 \
  my-app:latest

# Или с отдельными переменными
docker run -d \
  -e DATABASE_URL=postgres://... \
  -e JWT_SECRET=secret \
  -p 3000:3000 \
  my-app:latest
```

### Сценарий 2: Использование Pnpm и Corepack (Рекомендуется в 2026)

Pnpm значительно быстрее npm и эффективнее использует дисковое пространство.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:26-alpine@sha256:... AS builder

# Активируем pnpm через corepack
RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app
COPY pnpm-lock.yaml package.json ./

# Монтирование хранилища pnpm
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

COPY . .
RUN pnpm build && pnpm prune --prod

# Финальный образ
FROM node:26-alpine@sha256:...
RUN apk add --no-cache tini
WORKDIR /app

ENV NODE_ENV=production \
    NODE_OPTIONS="--max-old-space-size=1024"

COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist

USER node
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD node --eval "fetch('http://localhost:3000/health').then(r => process.exit(r.ok ? 0 : 1))"

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "dist/main.js"]
```

**Валидация:**
```bash
# Проверка что pnpm store не попал в финальный образ
docker run --rm my-app:latest sh -c "ls /pnpm 2>/dev/null || echo 'pnpm store не найден'"
# → pnpm store не найден

# Проверка размера node_modules (pnpm использует hard links)
docker exec <container> du -sh node_modules
# → node_modules     45M    (vs ~120M для npm)
```

**Различия между менеджерами пакетов:**
| Менеджер | Хранилище | Скорость | Хардлинки | Lock-файл |
|:---|:---|:---|:---|:---|
| npm | `node_modules` (плоская структура) | Базовая | Нет | `package-lock.json` |
| pnpm | `.pnpm-store` (контентно-адресуемое) | Высокая | Да | `pnpm-lock.yaml` |
| yarn | `.cache/yarn` | Высокая | Да | `yarn.lock` |

### Сценарий 3: Сборка монорепозитория (Turborepo / Nx)

Использование `turbo prune` для копирования только необходимых пакетов.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:26-alpine AS pruner
WORKDIR /app
RUN npm install -g turbo
COPY . .
# Генерируем срез только для конкретного микросервиса
RUN turbo prune my-api --docker

FROM node:26-alpine AS builder
WORKDIR /app
COPY --from=pruner /app/out/json/ ./
COPY --from=pruner /app/out/pnpm-lock.yaml ./
RUN corepack enable && pnpm install
COPY --from=pruner /app/out/full/ ./
RUN pnpm build --filter=my-api
```

### Сценарий 4: Нативные модули (node-gyp)

Для проектов с нативными зависимостями (bcrypt, sharp, sqlite3, canvas).

```dockerfile
# syntax=docker/dockerfile:1
FROM node:26-slim AS builder
# Установка инструментов сборки (напр. для bcrypt или sharp)
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 make g++ && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci
COPY . .
RUN npm run build && npm prune --omit=dev

FROM node:26-slim
# Для нативных модулей в runtime тоже нужны shared-библиотеки
RUN apt-get update && \
    apt-get install -y --no-install-recommends tini && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
USER node
ENTRYPOINT ["tini", "--"]
CMD ["node", "dist/main.js"]
```

**Валидация:**
```bash
# Проверка что нативные модули скомпилированы под правильную архитектуру
docker exec <container> node -e "console.log(process.arch)"
# → x64

# Проверка что build tools не попали в финальный образ
docker exec <container> which g++ 2>/dev/null || echo "g++ не найден"
# → g++ не найден

# Проверка что python3 не попал в финальный образ
docker exec <container> which python3 2>/dev/null || echo "python3 не найден"
# → python3 не найден
```

**Типичные нативные модули и их зависимости:**
| Модуль | Зависимости сборки | Альтернатива (без компиляции) |
|:---|:---|:---|
| `bcrypt` | python3, make, g++ | `bcryptjs` (чистый JS) |
| `sharp` | python3, make, g++, libvips | `jimp` (чистый JS, медленнее) |
| `sqlite3` | python3, make, g++ | `better-sqlite3` (тоже нативный) |
| `canvas` | python3, make, g++, libcairo2-dev | `@napi-rs/canvas` ( предкомпилированный) |

### Сценарий 5: Google Distroless (Максимальная безопасность)

Distroless-образы не содержат shell, пакетный менеджер или другие инструменты — только ваше приложение и его зависимости. Идеально для production.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:26-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
RUN npm run build && npm prune --omit=dev

# Финальный образ — Distroless (нет shell, нет apt, нет apk)
FROM gcr.io/distroless/nodejs24-debian12
WORKDIR /app

COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist

# Distroless не содержит пользователя node — используйте nonroot (UID 65534)
USER nonroot:nonroot

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["node", "--eval", "fetch('http://localhost:3000/health').then(r => process.exit(r.ok ? 0 : 1))"]

CMD ["dist/main.js"]
```

**Валидация:**
```bash
# Проверка что shell отсутствует
docker exec <container> /bin/sh -c "echo hacked" 2>&1
# → exec: "/bin/sh": no such file or directory

# Проверка что отсутствуют пакетные менеджеры
docker exec <container> apt-get --version 2>&1 || echo "apt-get не найден"
# → apt-get не найден

# Проверка размера образа
docker images my-app:latest
# → REPOSITORY   TAG       SIZE
# → my-app       latest    ~100 MB (vs ~150 MB для node:26-alpine)
```

**Отладка Distroless:**
Для отладки используйте debug-тег: `gcr.io/distroless/nodejs24-debian12:debug` — он содержит busybox shell.
Подробнее: [Отладка distroless-контейнеров](../../Docker_troubleshooting/debugging_distroless.md)

### Сценарий 6: Multi-platform сборка (ARM64 + AMD64)

Сборка образов для нескольких архитектур через Docker Buildx.

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM node:26-alpine AS builder
ARG TARGETARCH
WORKDIR /app

COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY . .
RUN npm run build && npm prune --omit=dev

FROM node:26-alpine
RUN apk add --no-cache tini
WORKDIR /app

COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist

USER node
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "dist/main.js"]
```

**Сборка:**
```bash
# Создание builder (однократно)
docker buildx create --name multiarch --driver docker-container --use

# Сборка для обеих платформ
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t my-app:latest \
  --push .

# Проверка что образ содержит обе архитектуры
docker manifest inspect my-app:latest
# → manifests: [{platform: {architecture: amd64}}, {platform: {architecture: arm64}}]
```

**Важные ограничения:**
- Нативные модули (node-gyp) требуют кросс-компиляции или QEMU эмуляции.
- `--platform=$BUILDPLATFORM` ускоряет сборку — она выполняется на хосте, а не через QEMU.
- Дайджесты разные для разных архитектур — pinning по SHA256 работает на уровне манифеста.

### Сценарий 7: Контейнер разработки с Hot Reload

Для локальной разработки с volume mount и горячей перезагрузкой.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:26-alpine
RUN apk add --no-cache tini
WORKDIR /app

# Устанавливаем ВСЕ зависимости (включая dev)
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

# Копируем исходный код
COPY . .

# Настройки для dev
ENV NODE_ENV=development \
    CHOKIDAR_USEPOLLING=1

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD node --eval "fetch('http://localhost:3000/health').then(r => process.exit(r.ok ? 0 : 1))"

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["npx", "nodemon", "--legacy-watch", "src/main.ts"]
```

**Запуск:**
```bash
# С volume mount для горячей перезагрузки
docker run -d \
  -v $(pwd)/src:/app/src \
  -p 3000:3000 \
  --env-file .env \
  my-app-dev:latest
```

**Отличия от production:**
- `npm ci` устанавливает devDependencies (jest, eslint, nodemon) — в production они исключаются.
- `CHOKIDAR_USEPOLLING=1` — работает на macOS/Windows через Docker Desktop (inotify не работает в shared folders).
- `npx nodemon` вместо `node` — автоматическая перезагрузка при изменении файлов.
- Volume mount подменяет `src/` в контейнере — изменения отслеживаются в реальном времени.
- `--read-only` и `--cap-drop=ALL` обычно не используются в dev для удобства отладки.
- Лимиты ресурсов (`--memory`, `--cpus`) обычно жёстко не задаются в dev.

### Сценарий 8: SBOM и аттестации (BuildKit + Docker Scout)

Генерация SBOM (Software Bill of Materials) и аттестаций при сборке для compliance и безопасности.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:26-alpine@sha256:... AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
RUN npm run build && npm prune --omit=dev

FROM node:26-alpine@sha256:...
RUN apk add --no-cache tini
WORKDIR /app
COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
USER node
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "dist/main.js"]
```

**Сборка с SBOM и Provenance:**
```bash
# Сборка с генерацией SBOM и аттестаций
DOCKER_BUILDKIT=1 docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t my-app:latest \
  --sbom=true \
  --provenance=mode=max \
  --push \
  .

# Просмотр SBOM в образе
docker buildx imagetools inspect my-app:latest --format '{{ json .SBOM }}' | jq

# Просмотр Provenance
docker buildx imagetools inspect my-app:latest --format '{{ json .Provenance }}' | jq
```

**Сканирование уязвимостей через Docker Scout:**
```bash
# Быстрый обзор
docker scout quickview my-app:latest

# Только критичные и высокие уязвимости
docker scout cves my-app:latest --only-severity critical,high

# Сравнение с базовым образом
docker scout compare my-app:latest node:26-alpine
```

**Подпись образа (Cosign):**
```bash
# Подпись образа
cosign sign my-app:latest

# Верификация подписи
cosign verify my-app:latest
```

**Валидация:**
```bash
# Проверка что SBOM присутствует
docker buildx imagetools inspect my-app:latest --format '{{ json .SBOM }}' | jq '.artifacts | length'
# → число артефактов в SBOM

# Проверка подписи
cosign verify my-app:latest --certificate-identity=... --certificate-oidc-issuer=...
# → Verification succeeded
```

## Типичные ошибки и их решение

### Ошибка 1: npm ci падает с "Cannot read property 'find' of undefined"

**Причина:** Отсутствует `package-lock.json` или версия Node.js не совместима с lock-файлом.

```bash
# Решение 1: сгенерировать lock-файл
npm install --package-lock-only

# Решение 2: проверить версию Node.js в lock-файле
node -e "const p = require('./package-lock.json'); console.log(p.lockfileVersion)"
# → 3 (для npm 7+)

# Решение 3: если lock-файл от npm 6 (lockfileVersion: 1), обновить
npm install --package-lock-only --lockfile-version=3
```

### Ошибка 2: "Module not found" после npm prune --omit=dev

**Причина:** Пакет ошибочно добавлен в `dependencies` вместо `devDependencies`.

```bash
# Диагностика: найти пакет в package.json
node -e "const p = require('./package.json'); console.log(p.dependencies['eslint'])"
# → если undefined — пакет в devDependencies

# Решение: переместить в devDependencies
npm install --save-dev eslint

# Или проверить что пакет действительно нужен в production
grep -r "require('eslint')" src/ || echo "esModuleType не найден в src/"
```

### Ошибка 3: Контейнер завершается с OOMKilled (exit code 137)

**Причина:** Node.js использует больше памяти, чем лимит cgroups.

```bash
# Диагностика: проверить потребление памяти
docker stats --no-stream <container>
# → MEM USAGE / LIMIT
# → 245MiB / 256MiB  (почти满了)

# Решение 1: увеличить лимит памяти
docker run -d --memory=512m my-app:latest

# Решение 2: установить max-old-space-size (70% от лимита)
ENV NODE_OPTIONS="--max-old-space-size=364"  # 70% от 512MB

# Решение 3: найти утечку памяти
node --max-old-space-size=256 --expose-gc src/main.js
# Затем: docker exec <container> node --eval "global.gc(); console.log(process.memoryUsage())"
```

### Ошибка 4: HEALTHCHECK всегда unhealthy

**Причина:** Приложение слушает `127.0.0.1` вместо `0.0.0.0`, или health endpoint не существует.

```bash
# Диагностика: проверить что приложение слушает
docker exec <container> netstat -tlnp 2>/dev/null || docker exec <container> ss -tlnp
# →/tcp  0  128  127.0.0.1:3000  0.0.0.0:*  (ОШИБКА: только localhost)
# →/tcp  0  128  0.0.0.0:3000    0.0.0.0:*  (НОРМА: все интерфейсы)

# Решение: в Express/Fastify слушать 0.0.0.0
app.listen(3000, '0.0.0.0', () => console.log('Listening on 0.0.0.0:3000'));
# Или через переменную окружения
ENV HOST=0.0.0.0
```

### Ошибка 5: BUILDPLATFORM не работает в Dockerfile

**Причина:** Не указана директива `# syntax=docker/dockerfile:1` или не используется BuildKit.

```bash
# Решение: добавить syntax directive в первую строку
# syntax=docker/dockerfile:1

# И включить BuildKit
export DOCKER_BUILDKIT=1

# Или в daemon.json:
# { "features": { "buildkit": true } }
```

### Ошибка 6: "npm WARN deprecated" при сборке

**Причина:** Зависимости используют устаревшие пакеты. Не блокирует сборку, но создаёт шум в логах.

```bash
# Решение: подавить предупреждения deprecated
RUN npm ci --loglevel=error

# Или исправить зависимости
npm audit fix

# Или для критичных deprecated — обновить пакеты вручную
npm outdated
npm update
```

### Ошибка 7: pnpm install падает с "ERR_PNPM_NO_LOCKFILE"

**Причина:** Отсутствует `pnpm-lock.yaml` или файл неправильно скопирован.

```bash
# Решение 1: сгенерировать lock-файл
pnpm install

# Решение 2: в Dockerfile проверить что файл копируется
COPY pnpm-lock.yaml package.json ./
# Не забудьте указать pnpm-lock.yaml, а не package-lock.json!

# Решение 3: если монорепозиторий
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
```

### Ошибка 8: Node.js не находит модуль в Alpine

**Причина:** Alpine использует `musl libc` вместо `glibc` — нативные модули, скомпилированные для glibc, не работают.

```bash
# Симптом: Error: /lib/x86_64-linux-gnu/libc.so.6: version 'GLIBC_2.28' not found

# Решение 1: использовать slim (Debian) вместо Alpine
FROM node:26-slim

# Решение 2: установить совместимость glibc
RUN apk add --no-cache gcompat

# Решение 3: собрать нативный модуль в Alpine
RUN apk add --no-cache python3 make g++ && npm rebuild
```

## Лучшие практики

### Сводка рекомендаций

| Практика | Рекомендация | Причина |
|:---|:---|:---|
| **Multi-stage** | SDK для сборки, alpine/slim для запуска | Уменьшает размер на 50-70% |
| **Layer caching** | Копировать `package.json` до исходного кода | Ускоряет повторную сборку |
| **Cache mount** | `--mount=type=cache,target=/root/.npm` | npm не скачивает заново |
| **Non-root** | `USER node` в конце Dockerfile | Предотвращение Container Escape |
| **Pinning** | `FROM image@sha256:...` | Гарантия воспроизводимости |
| **npm audit** | `RUN npm audit --audit-level=high` | Раннее обнаружение уязвимостей |
| **Pruning** | `npm prune --omit=dev` | Уменьшает размер node_modules |
| **Tini** | `apk add tini` или `--init` | Корректная обработка сигналов |
| **NODE_ENV** | `ENV NODE_ENV=production` | Включает оптимизации Express/Fastify |
| **Health endpoint** | `/health` в приложении | Проверка состояния контейнера |
| **.read-only** | `--read-only` + tmpfs | Блокировка записи в ФС |
| **Ограничение памяти** | `--memory` + `NODE_OPTIONS=--max-old-space-size` | Защита от OOM |

### Порядок инструкций в безопасном Dockerfile

```dockerfile
# 1. Версия синтаксиса
# syntax=docker/dockerfile:1

# 2. Базовый образ с pinning
FROM node:26-alpine@sha256:... AS builder

# 3. Переменные сборки
ARG TARGETARCH
ENV NODE_ENV=development

# 4. Копирование package.json (layer caching)
COPY package.json package-lock.json ./

# 5. Восстановление пакетов с cache mount
RUN --mount=type=cache,target=/root/.npm npm ci

# 6. Копирование исходного кода
COPY . .

# 7. Сборка и очистка
RUN npm run build && npm prune --omit=dev

# 8. Финальный образ
FROM node:26-alpine@sha256:...
RUN apk add --no-cache tini
WORKDIR /app

# 9. Переменные рантайма
ENV NODE_ENV=production \
    NODE_OPTIONS="--max-old-space-size=1024"

# 10. Копирование артефактов
COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist

# 11. Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD node --eval "fetch('http://localhost:3000/health').then(r => process.exit(r.ok ? 0 : 1))"

# 12. Non-root пользователь
USER node

# 13. Entrypoint
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "dist/main.js"]
```

### Чек-лист перед деплоем

**Dockerfile:**
- [ ] Инструкция `USER node` в конце (не root)
- [ ] Multi-stage: финальная стадия не содержит SDK и build tools
- [ ] Базовый образ зафиксирован по SHA256 дайджесту
- [ ] `package.json` копируется до исходного кода (layer caching)
- [ ] `--mount=type=cache` для npm/pnpm
- [ ] `NODE_ENV=production` установлен
- [ ] `npm audit` интегрирован в сборку
- [ ] `npm prune --omit=dev` выполнен
- [ ] HEALTHCHECK настроен и работает
- [ ] Нет секретов в ENV, ARG или .npmrc

**Запуск контейнера:**
- [ ] `--read-only` с tmpfs для временных данных
- [ ] `--cap-drop=ALL` + только необходимые capabilities
- [ ] `--security-opt=no-new-privileges`
- [ ] Привязка портов к localhost (если не нужен внешний доступ)
- [ ] Лимиты памяти установлены (`--memory`)
- [ ] `NODE_OPTIONS="--max-old-space-size"` настроен (70% от лимита)

**Kubernetes:**
- [ ] StartupProbe с `failureThreshold: 12` (60 сек на старт)
- [ ] LivenessProbe не зависит от внешних сервисов
- [ ] ReadinessProbe проверяет зависимость от БД
- [ ] Лимиты памяти и CPU установлены
- [ ] SecurityContext с `runAsNonRoot: true`

## Дополнительная информация

### Смотрите также

- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — общие принципы кэширования и multi-stage.
- **[Безопасность в Dockerfile](./security.md)** — работа с пользователями и SBOM.
- **[Выполнение приложений в контейнере](./container_execution.md)** — глубокий разбор PID 1 и сигналов.
