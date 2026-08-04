# Dockerfile: Лучшие практики для Node.js

## Определения

- **package.json / package-lock.json:** Манифест проекта и файл фиксации точных версий зависимостей. Для Yarn это `yarn.lock`, для Pnpm — `pnpm-lock.yaml`.
- **Corepack:** Встроенный в Node.js менеджер менеджеров пакетов. Позволяет использовать `pnpm` и `yarn` без их глобальной установки в образе.
- **npm ci (Clean Install):** Команда для установки зависимостей в CI-средах. Строго следует lock-файлу, удаляет существующие `node_modules` и работает быстрее обычного `install`.
- **node-gyp:** Инструмент для компиляции нативных аддонов (C/C++). Требует наличия Python и компилятора (build-essential) в образе на этапе сборки.
- **Tini:** Легковесный инициализатор (init), решающий проблему PID 1 (обработка сигналов и удаление "зомби-процессов") в контейнерах.
- **Pruning:** Процесс удаления `devDependencies` из папки `node_modules` после этапа сборки для минимизации финального образа.
- **Graceful Shutdown:** Процесс корректного завершения работы приложения (закрытие соединений с БД, HTTP-сервера) при получении сигналов `SIGTERM` или `SIGINT`.
- **Bun / Deno:** Альтернативные среды выполнения JavaScript/TypeScript, предлагающие встроенную поддержку TypeScript и более высокую производительность сборки.

## Базовые концепции

### Выбор базового образа

В 2026 году стандартом остаются образы на базе **Alpine** и **Debian Slim**:
- `node:24-alpine` (LTS) — ~50 МБ. Минимальный размер, но требует осторожности с нативными модулями из-за `musl libc`.
- `node:24-slim` (LTS) — ~70 МБ. База Debian, лучшая совместимость с нативными зависимостями.
- **Google Distroless:** `gcr.io/distroless/nodejs24-debian12` — максимальная безопасность (нет shell, нет пакетных менеджеров).

### Управление ресурсами и V8

Node.js в контейнерах часто требует ручной настройки лимитов V8, особенно в средах с cgroups v2:
*   **Memory Limit:** Используйте `NODE_OPTIONS="--max-old-space-size=X"`, где X составляет 75-80% от лимита памяти контейнера, чтобы оставить место для стека и системных вызовов.
*   **CPU:** Node.js однопоточен для выполнения JS, но использует дополнительные потоки для I/O и `worker_threads`. Для корректного масштабирования в K8s используйте лимиты минимум в 1 CPU.

### Обработка сигналов и PID 1

Использование `node` напрямую как PID 1 не рекомендуется, так как он не обрабатывает системные сигналы корректно.
1.  **Решение:** Используйте `tini` или флаг `--init` в Docker.
2.  **Graceful Shutdown:** Приложение должно явно обрабатывать сигналы:
    ```javascript
    const shutdown = () => server.close(() => process.exit(0));
    process.on('SIGTERM', shutdown);
    process.on('SIGINT', shutdown);
    ```

### Безопасность и аудит

*   **npm audit:** Интегрируйте в процесс сборки: `RUN npm audit --audit-level=high`.
*   **Rootless:** Никогда не запускайте приложение от `root`. Используйте встроенного пользователя `node`.
*   **Секреты:** Используйте `--mount=type=secret,id=npmrc,target=/app/.npmrc` для безопасной установки приватных пакетов.

## Практические сценарии

### Сценарий 1: Многоэтапная сборка (TypeScript + BuildKit + Tini)

Эталонный шаблон для Node.js 24 LTS.

```dockerfile
# syntax=docker/dockerfile:1
# check=error=true

# --- Этап 1: Сборка (builder) ---
FROM node:24-alpine AS builder
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
FROM node:24-alpine
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
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD node --eval "fetch('http://localhost:3000/health').then(r => process.exit(r.ok ? 0 : 1))"

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "dist/main.js"]
```

### Сценарий 2: Использование Pnpm и Corepack (Рекомендуется в 2026)

Pnpm значительно быстрее npm и эффективнее использует дисковое пространство.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:24-alpine AS builder

# Активируем pnpm через corepack
RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app
COPY pnpm-lock.yaml package.json ./

# Монтирование хранилища pnpm
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

COPY . .
RUN pnpm build && pnpm prune --prod

FROM node:24-alpine
# ... (аналогично сценарию 1)
```

### Сценарий 3: Сборка монорепозитория (Turborepo / Nx)

Использование `turbo prune` для копирования только необходимых пакетов.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:24-alpine AS pruner
WORKDIR /app
RUN npm install -g turbo
COPY . .
# Генерируем срез только для конкретного микросервиса
RUN turbo prune my-api --docker

FROM node:24-alpine AS builder
WORKDIR /app
COPY --from=pruner /app/out/json/ ./
COPY --from=pruner /app/out/pnpm-lock.yaml ./
RUN corepack enable && pnpm install
COPY --from=pruner /app/out/full/ ./
RUN pnpm build --filter=my-api
```

### Сценарий 4: Нативные модули (node-gyp)

```dockerfile
# syntax=docker/dockerfile:1
FROM node:24-alpine AS builder
# Установка инструментов сборки (напр. для bcrypt или sharp)
RUN apk add --no-cache python3 make g++
WORKDIR /app
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci
# ...
```

## Дополнительная информация

### Смотрите также

- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — общие принципы кэширования и multi-stage.
- **[Безопасность в Dockerfile](./security.md)** — работа с пользователями и SBOM.
- **[Выполнение приложений в контейнере](./container_execution.md)** — глубокий разбор PID 1 и сигналов.
- **[Отладка distroless-контейнеров](../../Docker_troubleshooting/debugging_distroless.md)**
- **[Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md)**
- **[Инструменты оптимизации Dockerfile](../dockerfile_optimization_tools.md)** — использование `D-roast` для Node.js.
