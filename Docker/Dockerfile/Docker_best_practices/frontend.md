# Dockerfile: Лучшие практики для Frontend (SPA и SSR)

## Определения

- **SPA (Single Page Application):** Веб-приложение, которое загружает одну HTML-страницу и динамически обновляет её при взаимодействии с пользователем (React, Vue, Angular, Svelte).
- **SSR (Server-Side Rendering):** Метод рендеринга страниц на стороне сервера при каждом запросе. Требует наличия Node.js в рантайме (Next.js, Nuxt.js, Remix).
- **Static Serving:** Раздача предварительно собранных статических файлов (HTML, JS, CSS) веб-сервером (Nginx, Caddy).
- **Multi-stage Build:** Техника сборки образа, разделенная на этапы (сборка артефакта и финальный рантайм), позволяющая исключить исходный код и `node_modules` из итогового образа.
- **History API Fallback:** Конфигурация веб-сервера, перенаправляющая все запросы на `index.html` для корректной работы клиентского роутинга SPA.
- **Content Security Policy (CSP):** Заголовок безопасности, ограничивающий источники загрузки ресурсов для предотвращения XSS и других атак.
- **Corepack:** Встроенный в Node.js инструмент для управления менеджерами пакетов (pnpm, yarn). Позволяет использовать их без глобальной установки в образе.
- **node-gyp:** Инструмент для компиляции нативных аддонов (C/C++). Требует наличия Python и компилятора в образе на этапе сборки.
- **Tini:** Легковесный init-процесс (PID 1) для контейнеров. Решает проблему обработки сигналов и удаления зомби-процессов.
- **Graceful Shutdown:** Корректное завершение работы приложения (закрытие соединений с БД, HTTP-сервера) при получении сигналов `SIGTERM` или `SIGINT`.

## Базовые концепции

### Разделение сред: Build-time vs Runtime

Главная сложность фронтенда в Docker — это момент подстановки конфигурации.

1.  **SPA (Static):** Приложение компилируется в статику. Переменные окружения (`VITE_`, `REACT_APP_`) подставляются **в момент сборки** (Build-time). Если нужно менять API URL без пересборки, требуются специальные методы (см. Практические сценарии).
2.  **SSR (Next.js/Nuxt):** Приложение работает как сервер. Оно может читать `process.env` **в рантайме**, как обычный бэкенд на Node.js.

**Почему это важно:** В SPA подстановка переменных при запуске контейнера невозможна без дополнительных инструментов (`envsubst`, `config.json`). Переменные зашиты в `index.html` и JS-бандлы на этапе `npm run build`.

### Выбор менеджера пакетов для Docker (2026)

| Менеджер | Рекомендация | Кэширование | Особенности |
| :--- | :--- | :--- | :--- |
| **pnpm** | **Стандарт 2026** | Контентно-адресуемое хранилище (`/pnpm/store`) | Экономит диск, быстрый, workspace-поддержка |
| **npm** | Legacy | `--mount=type=cache,target=/root/.npm` | Стандарт, но медленнее pnpm |
| **yarn (berry)** | Специфичные случаи | `--mount=type=cache,target=/root/.yarn` | PnP-режим, Plug'n'Play |
| **bun** | Экспериментальный | Встроенный кэш | Экстремальная скорость, но нестабилен для production |

**Рекомендация:** Используйте `pnpm` через `corepack`:

```bash
# В Dockerfile
RUN corepack enable && corepack prepare pnpm@latest --activate
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
```

### Кэширование и оптимизация BuildKit

Фронтенд-проекты часто имеют огромные `node_modules` (200+ МБ).

- **pnpm:** Рекомендуемый менеджер пакетов (стандарт 2026 года). Использует контентно-адресуемое хранилище.
- **Mount Cache:** Использование `--mount=type=cache` в Dockerfile позволяет сохранять кэш пакетов между сборками на хосте, радикально ускоряя процесс.
- **Layer Caching:** Копируйте `package.json` и lock-файл **до** исходного кода. Это позволяет использовать кэш Docker для зависимостей при изменении только кода.

```dockerfile
# Правильный порядок слоев
COPY pnpm-lock.yaml package.json ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# Исходный код копируется ПОСЛЕ зависимостей
COPY . .
```

### Стратегия раздачи статики

Для SPA после сборки Node.js **не нужен**.

- **Nginx:** Оптимальный выбор для production. Обеспечивает сжатие, кэширование и безопасность.
- **Caddy:** Автоматический HTTPS, простая конфигурация. Хорошая альтернатива для проектов с автоматическим SSL.
- **Immutable Assets:** Файлы с хешами в именах (`app.a1b2c3.js`) должны кэшироваться браузером "навсегда".
- **Mutable Assets:** `index.html` и `service-worker.js` никогда не должны кэшироваться.

### Обработка сигналов и PID 1

Для SSR-приложений (Next.js, Nuxt.js) Node.js запускается как PID 1. Это вызывает проблемы:
*   `SIGTERM` не достигает приложения (контейнер завершается через `SIGKILL` после таймаута).
*   Зомби-процессы накапливаются.

**Решения:**
1.  **tini (рекомендуется):** `RUN apk add --no-cache tini` + `ENTRYPOINT ["/sbin/tini", "--"]`
2.  **`--init` флаг:** Docker автоматически добавляет tini.
3.  **Docker Compose `init: true`:** Аналог `--init` для Compose.

Для SPA (Nginx) проблема PID 1 менее критична, так как Nginx корректно обрабатывает сигналы. Однако для graceful shutdown рекомендуется `--stop-signal SIGQUIT`.

### Безопасность

- **npm audit:** Интегрируйте в процесс сборки: `RUN npm audit --audit-level=high`. Если аудит провалился — сборка прервётся.
- **Rootless:** Никогда не запускайте приложение от `root`. Используйте встроенного пользователя `node` (UID 1000) или `nginx` (UID 101).
- **Секреты:** Используйте `--mount=type=secret` для безопасной установки приватных пакетов. Никогда не копируйте `.npmrc` или `.env` через `COPY`.
- **CSP заголовки:** Настройте Content Security Policy для защиты от XSS-атак.
- **Read-only filesystem:** Для Nginx контейнеров используйте `--read-only` с `tmpfs` для временных файлов.

### .dockerignore для фронтенд-проектов

Правильный `.dockerignore` критически важен для фронтенда — `node_modules` может занимать 500+ МБ и ломать кэш слоев.

```
# node_modules (воссоздаются в builder)
node_modules

# Dev-зависимости и конфигурация
.git
.github
.vscode
.env
.env.*
!.env.example

# Сборочные артефакты (пересоздаются)
dist
build
.next
.nuxt

# Тесты и документация
coverage
*.test.*
*.spec.*
__tests__
README.md
LICENSE

# Docker и CI
Dockerfile
docker-compose*.yml
.dockerignore
```

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

### Сценарий 5: Сборка с переменными окружения (ARG для Multi-env)

Для сборки одного образа под разные окружения (dev, staging, prod) используйте `ARG`:

```dockerfile
# syntax=docker/dockerfile:1
FROM node:24-alpine AS builder
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@latest --activate
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"

# Аргумент сборки (только на этапе build)
ARG VITE_API_URL=https://api.example.com
ARG VITE_APP_VERSION=1.0.0

# Передаем в сборку Vite
ENV VITE_API_URL=${VITE_API_URL} \
    VITE_APP_VERSION=${VITE_APP_VERSION}

COPY pnpm-lock.yaml package.json ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

# --- Финальный этап ---
FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
```

**Сборка:**
```bash
# Production
docker build \
  --build-arg VITE_API_URL=https://api.prod.com \
  --build-arg VITE_APP_VERSION=2.1.0 \
  -t my-app:prod .

# Staging
docker build \
  --build-arg VITE_API_URL=https://api.staging.com \
  -t my-app:staging .
```

**Валидация:**
```bash
# Проверка что переменная попала в бандл
docker run --rm my-app:prod cat /usr/share/nginx/html/assets/index.js | grep "api.prod.com"
# → https://api.prod.com
```

### Сценарий 6: Caddy как альтернатива Nginx

Caddy предоставляет автоматический HTTPS и более простую конфигурацию. Идеален для проектов, где нужен SSL без внешнего балансировщика.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:24-alpine AS builder
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@latest --activate
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"

COPY pnpm-lock.yaml package.json ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

# --- Финальный этап (Caddy) ---
FROM caddy:2-alpine

COPY --from=builder /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile

EXPOSE 80
EXPOSE 443
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile"]
```

**Caddyfile:**
```
:80 {
    root * /srv
    file_server
    try_files {path} /index.html

    header {
        # Кэширование хешированных ассетов
        @static path *.js *.css *.woff2 *.png *.jpg *.jpeg *.gif *.svg *.ico
        header @static Cache-Control "public, max-age=31536000, immutable"

        # Запрет кэширования index.html
        @index path /index.html
        header @index Cache-Control "no-store, no-cache, must-revalidate"

        # Безопасность
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy strict-origin-when-cross-origin
    }

    encode gzip zstd
}
```

**Валидация:**
```bash
# Проверка что Caddy запустился
docker exec <container> caddy version
# → v2.x.x

# Проверка ответа
curl -I http://localhost:80
# → HTTP/1.1 200 OK
# → Server: Caddy
```

### Сценарий 7: Nginx с заголовками безопасности (CSP, HSTS)

Конфигурация Nginx с полным набором заголовков безопасности для SPA:

```nginx
server {
    listen 8080;
    root /usr/share/nginx/html;
    index index.html;

    # === Безопасность ===
    # Content Security Policy (CSP)
    # Разрешаем только нужные источники; в продакшене усильте
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' https://api.example.com; frame-ancestors 'none';" always;

    # HSTS (только для HTTPS за прокси/balancer)
    # add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    # Защита от кликджекинга
    add_header X-Frame-Options "DENY" always;

    # Отключение MIME-sniffing
    add_header X-Content-Type-Options "nosniff" always;

    # Referrer Policy
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Permissions Policy (отключаем камеры, микрофоны и т.д.)
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;

    # === Роутинг ===
    location / {
        try_files $uri $uri/ /index.html;
    }

    # === Кэширование ===
    location ~* \.(?:js|css|woff2?|png|jpg|jpeg|gif|svg|ico)$ {
        expires 1y;
        add_header Cache-Control "public, no-transform";
        access_log off;
    }

    location = /index.html {
        expires -1;
        add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0";
    }

    # === Сжатие ===
    gzip on;
    gzip_types text/plain text/css application/javascript application/json image/svg+xml;
    gzip_min_length 1000;
    gzip_vary on;
}
```

**Валидация:**
```bash
# Проверка заголовков
curl -I http://localhost:8080
# → Content-Security-Policy: default-src 'self'; ...
# → X-Content-Type-Options: nosniff
# → X-Frame-Options: DENY
# → Referrer-Policy: strict-origin-when-cross-origin
# → Permissions-Policy: camera=(), microphone=(), geolocation=()
```

### Сценарий 8: Docker Compose: Frontend + Backend + Nginx Reverse Proxy

Полноценный стек с фронтендом, бэкендом и обратным прокси:

```yaml
services:
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    volumes:
      - frontend-dist:/usr/share/nginx/html:ro
    networks:
      - internal

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    environment:
      - NODE_ENV=production
      - DATABASE_URL=postgresql://user:pass@db:5432/mydb
    networks:
      - internal
      - external
    depends_on:
      db:
        condition: service_healthy

  nginx:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - frontend-dist:/usr/share/nginx/html:ro
      - ./nginx/certs:/etc/nginx/certs:ro
    networks:
      - external
    depends_on:
      - frontend
      - backend
    restart: unless-stopped
    read_only: true
    tmpfs:
      - /var/cache/nginx
      - /var/run
      - /tmp

  db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
      - POSTGRES_DB=mydb
    volumes:
      - db-data:/var/lib/postgresql/data
    networks:
      - internal
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user -d mydb"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  frontend-dist:
  db-data:

networks:
  internal:
    internal: true
  external:
```

**Nginx конфигурация для прокси:**
```nginx
server {
    listen 80;
    server_name myapp.example.com;

    # SPA + статика
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }

    # API прокси на backend
    location /api/ {
        proxy_pass http://backend:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Кэширование ассетов
    location ~* \.(?:js|css|woff2?|png|jpg|jpeg|gif|svg|ico)$ {
        expires 1y;
        add_header Cache-Control "public, no-transform";
        access_log off;
    }
}
```

**Валидация:**
```bash
docker compose up -d
docker compose ps
# → NAME        SERVICE     STATUS      PORTS
# → frontend-1  frontend    running
# → backend-1   backend     running
# → nginx-1     nginx       running     0.0.0.0:80->80/tcp
# → db-1        db          running (healthy)

# Проверка прокси
curl http://localhost/api/health
# → {"status":"ok"}
```

### Сценарий 9: Health Check для Nginx SPA

Nginx не имеет встроенного health endpoint. Создайте минимальный healthcheck:

```dockerfile
# В builder этапе создайте healthcheck.html
RUN echo '{"status":"ok"}' > /app/dist/healthcheck.json

# --- Финальный этап ---
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

# HEALTHCHECK с curl ( Alpine имеет curl черезBusyBox)
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost:8080/healthcheck.json || exit 1

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
```

**Или через код (для SSR):**
```dockerfile
# Для Next.js SSR
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD node --eval "fetch('http://localhost:3000/api/health').then(r => process.exit(r.ok ? 0 : 1))"
```

**Валидация:**
```bash
docker inspect --format='{{.State.Health.Status}}' <container>
# → healthy

docker inspect --format='{{json .State.Health.Log}}' <container> | python3 -m json.tool
# → [{"Output":"HTTP/1.1 200 OK\n","ExitCode":0,...}]
```

### Сценарий 10: Read-only Nginx контейнер

Максимальная безопасность: файловая система только для чтения, временные файлы в tmpfs:

```dockerfile
FROM nginx:1.27-alpine

RUN touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /var/log/nginx /usr/share/nginx/html

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

USER nginx
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
```

**Запуск:**
```bash
docker run -d \
  --read-only \
  --tmpfs /var/cache/nginx:rw,size=10m \
  --tmpfs /var/run:rw,size=1m \
  --tmpfs /tmp:rw,size=10m \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  --security-opt=no-new-privileges \
  -p 8080:8080 \
  my-spa:latest
```

**Валидация:**
```bash
# Проверка что запись запрещена
docker exec <container> touch /usr/share/nginx/html/test.txt 2>&1
# → touch: /usr/share/nginx/html/test.txt: Read-only file system

# Проверка что tmpfs работает
docker exec <container> touch /tmp/test.txt
# → (успешно)
docker exec <container> rm /tmp/test.txt
```

### Сценарий 11: Graceful Shutdown для SSR (Next.js с tini)

```dockerfile
# syntax=docker/dockerfile:1
FROM node:24-alpine AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@latest --activate
COPY pnpm-lock.yaml package.json ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM node:24-alpine
RUN apk add --no-cache tini
WORKDIR /app
ENV NODE_ENV=production

RUN addgroup -S nodejs -g 1001 && adduser -S nextjs -u 1001

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

# tini как PID 1, node как дочерний процесс
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "server.js"]
```

**Валидация:**
```bash
docker stop --timeout 30 <container>
docker inspect <container> --format='{{.State.ExitCode}}'
# → 0

# Проверка что tini является PID 1
docker exec <container> ps -p 1 -o pid,comm,args
# → PID   COMMAND  COMMAND
#   1   tini     /sbin/tini -- node server.js
```

## Типичные ошибки и их решение

### Ошибка 1: "node_modules" попадает в финальный образ

**Причина:** Отсутствует `.dockerignore` или multi-stage не используется.

```bash
# Симптом: образ весит 1.5+ ГБ вместо 50 МБ
docker images my-spa
# → my-spa   latest   1.42GB

# Решение 1: добавить .dockerignore
echo "node_modules" >> .dockerignore

# Решение 2: использовать multi-stage (см. Сценарий 1)
```

### Ошибка 2: SPA роутинг возвращает 404

**Причина:** Отсутствует `try_files` в nginx.conf.

```bash
# Симптом: прямой переход по URL /dashboard возвращает 404

# Решение: добавить try_files
location / {
    try_files $uri $uri/ /index.html;
}
```

### Ошибка 3: Переменные окружения не подставляются в SPA

**Причина:** `VITE_` переменные зашиты в бандл при сборке и не меняются в рантайме.

```bash
# Симптом: API URL всегда дефолтный, несмотря на ENV

# Решение 1: пересобрать образ с нужными ARG
docker build --build-arg VITE_API_URL=https://api.prod.com -t my-app:prod .

# Решение 2: использовать метод config.json (см. Сценарий 4)
```

### Ошибка 4: Nginx не запускается (permission denied)

**Причина:** Nginx запущен от root, но директории не доступны, или наоборот — от пользователя без прав.

```bash
# Симптом: nginx: [alert] could not open error log file

# Решение: создать PID файл и назначить права
RUN touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /var/log/nginx
USER nginx
```

### Ошибка 5: Pnpm install падает с "ERR_PNPM_NO_LOCKFILE"

**Причина:** Отсутствует `pnpm-lock.yaml` или файл неправильно скопирован.

```bash
# Решение: убедиться что lock-файл копируется ДО исходного кода
COPY pnpm-lock.yaml package.json ./
RUN pnpm install --frozen-lockfile
# Не использовать pnpm install без --frozen-lockfile в CI!
```

### Ошибка 6: Контейнер не завершается по `docker stop`

**Причина:** Node.js (SSR) не обрабатывает `SIGTERM` корректно.

```bash
# Решение 1: добавить tini (см. Сценарий 11)
# Решение 2: увеличить таймаут
docker stop --timeout 60 <container>

# Решение 3: в Docker Compose
services:
  app:
    stop_grace_period: 60s
```

## Лучшие практики

### Сводка рекомендаций

| Практика | Рекомендация | Причина |
| :--- | :--- | :--- |
| **Multi-stage** | SDK для сборки, alpine/slim для запуска | Уменьшает размер на 70-90% |
| **Менеджер пакетов** | pnpm через corepack | Скорость, workspace, контентно-адресуемый кэш |
| **Cache mount** | `--mount=type=cache,target=/pnpm/store` | Ускоряет повторные сборки |
| **Layer caching** | Копировать lock-файл до исходного кода | Кэш зависимостей не ломается |
| **Non-root** | `USER nginx` или `USER node` | Защита от Container Escape |
| **.dockerignore** | Исключить node_modules, dist, .git | Уменьшает context и размер слоев |
| **ARG для env** | `ARG VITE_API_URL` + `--build-arg` | Multi-env без пересборки |
| **CSP заголовки** | `Content-Security-Policy` в nginx.conf | Защита от XSS |
| **Read-only FS** | `--read-only` + tmpfs | Блокировка записи в ФС |
| **tini** | `ENTRYPOINT ["/sbin/tini", "--"]` | Корректная обработка сигналов (SSR) |
| **HEALTHCHECK** | `wget` или `node --eval` | Мониторинг состояния контейнера |
| **npm audit** | `RUN npm audit --audit-level=high` | Раннее обнаружение CVE |

### Чек-лист перед деплоем

**Dockerfile:**
- [ ] Multi-stage: финальная стадия не содержит SDK и build tools
- [ ] Базовый образ зафиксирован по версии или SHA256 дайджесту
- [ ] `USER nginx` или `USER node` в конце (не root)
- [ ] `--mount=type=cache` для pnpm/npm
- [ ] `COPY lock-файл` до исходного кода (layer caching)
- [ ] `.dockerignore` исключает `node_modules`, `dist`, `.git`
- [ ] `npm audit` интегрирован в сборку
- [ ] HEALTHCHECK настроен и работает
- [ ] Нет секретов в ENV, ARG или .npmrc
- [ ] CSP заголовки настроены в nginx.conf

**Запуск контейнера:**
- [ ] `--read-only` с tmpfs для временных данных
- [ ] `--cap-drop=ALL` + только необходимые capabilities
- [ ] `--security-opt=no-new-privileges`
- [ ] `--stop-signal SIGQUIT` для Nginx graceful shutdown
- [ ] `--init` или `init: true` для SSR-приложений
- [ ] Лимиты памяти установлены (`--memory`)

**Kubernetes:**
- [ ] StartupProbe с足够的 `failureThreshold` (60+ сек на старт)
- [ ] LivenessProbe не зависит от внешних сервисов
- [ ] ReadinessProbe проверяет health endpoint
- [ ] Лимиты памяти и CPU установлены
- [ ] SecurityContext с `runAsNonRoot: true`

## Дополнительная информация

### Смотрите также

- **[Dockerfile: Лучшие практики для Node.js](./nodejs.md)** — глубокая оптимизация сборки зависимостей.
- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — механизмы кэширования BuildKit.
- **[Безопасность в Dockerfile](./security.md)** — работа с пользователями и заголовками.
