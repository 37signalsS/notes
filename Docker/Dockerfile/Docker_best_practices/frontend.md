# Dockerfile: Лучшие практики для Frontend (SPA и SSR)

## Определения

- **SPA (Single Page Application):** Веб-приложение, которое загружает одну HTML-страницу и динамически обновляет её при взаимодействии с пользователем (React, Vue, Angular, Svelte).
- **SSR (Server-Side Rendering):** Метод рендеринга страниц на стороне сервера при каждом запросе. Требует наличия Node.js в рантайме (Next.js, Nuxt.js, Remix).
- **Static Serving:** Раздача предварительно собранных статических файлов (HTML, JS, CSS) веб-сервером (Nginx, Caddy).
- **Multi-stage Build:** Техника сборки образа, разделенная на этапы (сборка артефакта и финальный рантайм), позволяющая исключить исходный код и `node_modules` из итогового образа.
- **History API Fallback:** Конфигурация веб-сервера, перенаправляющая все запросы на `index.html` для корректной работы клиентского роутинга SPA.
- **Content Security Policy (CSP):** Заголовок безопасности, ограничивающий источники загрузки ресурсов для предотвращения XSS и других атак.

## Базовые концепции

### Разделение сред: Build-time vs Runtime

Главная сложность фронтенда в Docker — это момент подстановки конфигурации.

1.  **SPA (Static):** Приложение компилируется в статику. Переменные окружения (`VITE_`, `REACT_APP_`) подставляются **в момент сборки** (Build-time). Если нужно менять API URL без пересборки, требуются специальные методы (см. Практические сценарии).
2.  **SSR (Next.js/Nuxt):** Приложение работает как сервер. Оно может читать `process.env` **в рантайме**, как обычный бэкенд на Node.js.

### Кэширование и оптимизация BuildKit

Фронтенд-проекты часто имеют огромные `node_modules`.
- **pnpm:** Рекомендуемый менеджер пакетов (стандарт 2026 года). Использует контентно-адресуемое хранилище.
- **Mount Cache:** Использование `--mount=type=cache` в Dockerfile позволяет сохранять кэш пакетов между сборками на хосте, радикально ускоряя процесс.

### Стратегия раздачи статики

Для SPA после сборки Node.js **не нужен**.
- **Nginx:** Оптимальный выбор для production. Обеспечивает сжатие, кэширование и безопасность.
- **Immutable Assets:** Файлы с хешами в именах (`app.a1b2c3.js`) должны кэшироваться браузером "навсегда".
- **Mutable Assets:** `index.html` и `service-worker.js` никогда не должны кэшироваться.

## Практические сценарии

### Сценарий 1: Оптимизированный SPA (Vite + pnpm + Nginx)

Самый быстрый и легкий способ сборки современного SPA.

```dockerfile
# syntax=docker/dockerfile:1
# --- Этап 1: Сборка (builder) ---
FROM node:24-alpine AS builder
WORKDIR /app

# Активируем pnpm и настраиваем кэш
RUN corepack enable && corepack prepare pnpm@latest --activate
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"

# Кэшируем зависимости отдельно от кода
COPY pnpm-lock.yaml package.json ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# Копируем код и собираем
COPY . .
RUN pnpm build

# --- Этап 2: Финальный образ (Nginx) ---
FROM nginx:1.27-alpine

# Копируем кастомный конфиг (см. сценарий 2)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Копируем только статику
COPY --from=builder /app/dist /usr/share/nginx/html

# Запуск от непривилегированного пользователя (Security Best Practice)
RUN touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /var/log/nginx /usr/share/nginx/html
USER nginx

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
```

### Сценарий 2: Правильный nginx.conf для SPA

```nginx
server {
    listen 8080;
    root /usr/share/nginx/html;
    index index.html;

    # Поддержка клиентского роутинга (React Router, Vue Router)
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Кэширование хешированных ассетов (1 год)
    location ~* \.(?:js|css|woff2?|png|jpg|jpeg|gif|svg|ico)$ {
        expires 1y;
        add_header Cache-Control "public, no-transform";
        access_log off;
    }

    # Запрет кэширования для index.html
    location = /index.html {
        expires -1;
        add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0";
    }

    # Сжатие
    gzip on;
    gzip_types text/plain text/css application/javascript application/json;
    gzip_min_length 1000;
}
```

### Сценарий 3: Docker-образ для Next.js (SSR Mode)

Next.js требует Node.js в рантайме. Используем `standalone` режим для минимизации размера.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:24-alpine AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@latest --activate
COPY pnpm-lock.yaml package.json ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

# Создаем пользователя
RUN addgroup -S nodejs -g 1001 && adduser -S nextjs -u 1001

# Копируем только необходимые файлы из standalone билда
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
```

### Сценарий 4: Runtime переменные для SPA (метод config.json)

Вместо сложного `envsubst` в HTML, используйте внешний JSON.

1.  В приложении делайте запрос: `fetch('/config.json')`.
2.  В `nginx.conf` добавьте мапинг.
3.  При запуске контейнера генерируйте файл:

```dockerfile
# entrypoint.sh
echo "{\"API_URL\": \"${API_URL}\"}" > /usr/share/nginx/html/config.json
exec "$@"
```

## Дополнительная информация

### Смотрите также

- **[Dockerfile: Лучшие практики для Node.js](./nodejs.md)** — глубокая оптимизация сборки зависимостей.
- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — механизмы кэширования BuildKit.
- **[Безопасность в Dockerfile](./security.md)** — работа с пользователями и заголовками.
- **[Nginx: Раздача статики](../../WebServers/Nginx/Core/Location/serving_files.md)** — продвинутая настройка веб-сервера.
