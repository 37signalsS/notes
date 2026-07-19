# Dockerfile: Лучшие практики для Node.js

> **Надежность: 10** (Актуализировано согласно стандартам 2026 года, Node.js v20/v22/v24)

## Определения

- **package.json / package-lock.json:** Манифест проекта и файл фиксации точных версий зависимостей. Для Yarn это `yarn.lock`, для Pnpm — `pnpm-lock.yaml`.
- **npm ci (Clean Install):** Команда для установки зависимостей в CI-средах, которая строго следует lock-файлу и удаляет существующие `node_modules`.
- **node-gyp:** Инструмент для компиляции нативных аддонов (написанных на C/C++) для Node.js. Требует наличия Python и компилятора в образе.
- **Tini:** Легковесный инициализатор (init), решающий проблему PID 1 (обработка сигналов и удаление "зомби-процессов") в контейнерах.
- **Pruning:** Процесс удаления `devDependencies` из папки `node_modules` после этапа сборки для минимизации финального образа.

## Базовые концепции

### Выбор базового образа

Рекомендуется использовать официальные образы на базе **Alpine** для минимального размера или **Debian Slim** для максимальной совместимости.
- `node:22-alpine` — ~50 МБ, идеален для большинства приложений.
- `node:22-slim` — ~70 МБ, если требуются сложные системные зависимости или нативные модули.

### Проблема PID 1 и Tini

Node.js не предназначен для работы в качестве PID 1. Он не пересылает сигналы (например, `SIGTERM`) дочерним процессам и не очищает "зомби". Это приводит к тому, что контейнеры долго останавливаются и могут потреблять лишние ресурсы.
**Решение:** Использование `tini` в качестве `ENTRYPOINT`.

### Кэширование зависимостей (BuildKit)

Современный подход требует использования `--mount=type=cache` для сохранения кэша менеджера пакетов (`~/.npm` или `/pnpm/store`) между сборками. Это значительно ускоряет сборку в CI/CD, не раздувая при этом слои образа.

### Исключение devDependencies (--omit=dev)

Флаг `--omit=dev` (ранее `--production`) критически важен. Он гарантирует, что в финальный образ не попадут инструменты тестирования, линтеры и компиляторы (TypeScript), что уменьшает размер образа на 60–80% и сокращает поверхность атаки.

## Практические сценарии

### Сценарий 1: Многоэтапная сборка (TypeScript + BuildKit + Tini)

Оптимальный шаблон для современного веб-приложения.

```dockerfile
# syntax=docker/dockerfile:1
# --- Этап 1: Сборка (builder) ---
FROM node:22-alpine AS builder
WORKDIR /app

# Копируем манифесты
COPY package.json package-lock.json ./

# Используем монтирование кэша для npm
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# Копируем исходный код и собираем (например, из TS в JS)
COPY . .
RUN npm run build && \
    # Удаляем devDependencies прямо здесь
    npm prune --omit=dev

# --- Этап 2: Финальный образ ---
FROM node:22-alpine
# Установка tini для корректной обработки сигналов
RUN apk add --no-cache tini
WORKDIR /app

ENV NODE_ENV=production

# Копируем только необходимые артефакты
COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist

# Безопасность: запуск от пользователя node (встроен в образ)
USER node

# Tini гарантирует корректную остановку приложения
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "dist/main.js"]
```

### Сценарий 2: Использование Pnpm и Corepack

Pnpm является наиболее эффективным менеджером пакетов по скорости и использованию диска.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine AS builder

# Активируем pnpm через встроенный corepack
RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app
COPY pnpm-lock.yaml package.json ./

# Кэшируем store pnpm
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

COPY . .
RUN pnpm build && pnpm prune --prod

# --- Финальный этап ---
FROM node:22-alpine
# ... (остальное аналогично сценарию 1)
```

### Сценарий 3: Нативные модули (node-gyp)

Если вам нужны пакеты вроде `bcrypt` или `sharp`, их нужно собирать на этапе `builder`.

```dockerfile
FROM node:22-alpine AS builder
# Устанавливаем инструменты компиляции
RUN apk add --no-cache python3 make g++
WORKDIR /app
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci
# ...
```

## Дополнительная информация

### Смотрите также

- [Оптимизация сборки Docker-образов](./build_optimization.md) — общие принципы кэширования.
- [Безопасность в Dockerfile](./security.md) — детали работы с пользователями.
- [Отладка distroless-контейнеров](../../Docker_troubleshooting/debugging_distroless.md)
- [Выполнение приложений в контейнере](./container_execution.md) — подробнее про PID 1 и Tini.
