# Dockerfile: Лучшие практики для Frontend (SPA)

## Определения

- **SPA (Single Page Application):** Веб-приложение, загружающееся как одна страница и динамически обновляющее содержимое без полной перезагрузки (React, Vue, Angular, Svelte).
- **Static Serving:** Раздача предварительно собранных статических файлов (HTML, JS, CSS) веб-сервером.
- **Multi-stage Build:** Метод разделения процесса на этап сборки (Node.js) и этап раздачи (Nginx), что позволяет исключить исходный код и `node_modules` из финального образа.
- **History API Fallback:** Настройка сервера, перенаправляющая все запросы на `index.html`, чтобы роутинг SPA (на стороне клиента) работал корректно при обновлении страницы.
- **Content Security Policy (CSP):** Механизм защиты, предотвращающий выполнение недоверенного кода в браузере.

## Базовые концепции

### Особенности сборки Frontend

Фронтенд-приложения требуют компиляции (транспиляции) из современных стандартов (TypeScript, JSX) в бандлы, понятные браузеру.
*   **Инструменты:** Vite (стандарт 2026 года), Webpack (legacy), pnpm (рекомендуемый менеджер пакетов).
*   **Артефакт:** Папка `dist` или `build` с минифицированными файлами.
*   **Рантайм:** После сборки Node.js **не нужен**. Достаточно веб-сервера (Nginx, Caddy).

### Кэширование и хеширование

Современные сборщики добавляют уникальный хеш к именам файлов (например, `main.8f2a1c.js`).
- **Ассеты (JS, CSS, изображения):** Могут кэшироваться браузером «навсегда» (Cache-Control: `max-age=31536000`), так как при изменении кода хеш изменится.
- **index.html:** Никогда не должен кэшироваться, так как он ссылается на актуальные версии ассетов.

### Проблема переменных окружения (Runtime Env)

SPA собирается в статику. Переменные `process.env` подставляются **в момент сборки**.
- **Плохо:** Хардкодить URL API в образ. Это заставляет пересобирать образ для каждого окружения (dev/staging/prod).
- **Хорошо:** Использовать `envsubst` в Nginx для подстановки переменных в `index.html` или JS-конфиг при старте контейнера.

## Практические сценарии

### Сценарий 1: Современная сборка Vite + Nginx (BuildKit + Multi-stage)

```dockerfile
# syntax=docker/dockerfile:1
# --- Этап 1: Сборка (builder) ---
FROM node:24-alpine AS builder
WORKDIR /app

# Активируем pnpm для скорости
RUN corepack enable && corepack prepare pnpm@latest --activate

# Кэшируем зависимости
COPY pnpm-lock.yaml package.json ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# Копируем исходники и собираем
COPY . .
RUN pnpm build

# --- Этап 2: Финальный образ (Nginx) ---
FROM nginx:1.27-alpine

# Копируем конфиг
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Копируем статику из builder
COPY --from=builder /app/dist /usr/share/nginx/html

# Настройка безопасности: запуск от непривилегированного пользователя
# В Alpine образах Nginx обычно требует создания пользователя вручную для портов > 1024
RUN touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /var/log/nginx /usr/share/nginx/html
USER nginx

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
```

### Сценарий 2: Оптимальный nginx.conf для SPA (Gzip, CSP, Caching)

```nginx
server {
    listen 8080;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # Сжатие (Gzip)
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml;
    gzip_proxied any;
    gzip_min_length 1000;

    # Безопасность (Заголовки)
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-XSS-Protection "1; mode=block";
    add_header X-Content-Type-Options "nosniff";
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';";

    location / {
        try_files $uri $uri/ /index.html;
    }

    # Кэширование ассетов (хешированные файлы)
    location ~* \.(?:ico|css|js|gif|jpe?g|png|woff2?|svg)$ {
        expires 1y;
        add_header Cache-Control "public, no-transform";
        access_log off;
    }

    # index.html кэшировать нельзя
    location = /index.html {
        expires -1;
        add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0";
    }
}
```

### Сценарий 3: Подстановка Runtime переменных через envsubst

Если вам нужно менять API_URL без пересборки образа:

1.  В `index.html` добавьте плейсхолдер: `<script>window.ENV_API_URL = "${API_URL}";</script>`
2.  В Dockerfile измените `CMD`:
```dockerfile
# Требуется пакет gettext для envsubst
RUN apk add --no-cache gettext
CMD ["/bin/sh", "-c", "envsubst < /usr/share/nginx/html/index.html > /usr/share/nginx/html/index.html.tmp && mv /usr/share/nginx/html/index.html.tmp /usr/share/nginx/html/index.html && nginx -g 'daemon off;'"]
```

## Дополнительная информация

### Смотрите также

- [Dockerfile: Лучшие практики для Node.js](./nodejs.md) — оптимизация этапа сборки.
- [Оптимизация сборки Docker-образов](./build_optimization.md) — детали multi-stage и кэширования.
- [Безопасность в Dockerfile](./security.md) — заголовки и права доступа.
- [Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md)
