# Nginx: развертывание SPA и шлюз API (Single Page Application & API Gateway)

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x (Mainline), Node.js 20+ / 22+ LTS, Vite 5+ / 6+, Docker 27+

---

## 0. Декларация перекрытия (Overlap Declaration)

Настоящий документ является единым источником правды (SSoT) по сквозному развертыванию Single Page Applications (React, Vue, Angular, Svelte) совместно с обратным проксированием Backend API в директории `Scenarios`:
- [Core/Location/serving_files.md](../Core/Location/serving_files.md) — рассматривает низкоуровневые директивы модуля статики (`root`, `alias`, `open_file_cache`, `sendfile`), но не содержит законченного сценария связки с API-бэкендом и HTML5 History API.
- [Performance/Caching/client_caching.md](../Performance/Caching/client_caching.md) — детально описывает спецификацию HTTP-заголовков RFC 9111 (`Cache-Control`, `ETag`, `Vary`), используемых в данном сценарии для раздельного кэширования `index.html` и неизменяемых ассетов.
- [Proxy/nginx_reverse_proxy_core.md](../Proxy/nginx_reverse_proxy_core.md) — описывает базовые принципы директивы `proxy_pass`, заголовков и сокетов.

---

## 1. Определения

- **Single Page Application (SPA)** — архитектура веб-приложения, при которой браузер загружает единый HTML-документ (`index.html`) и набор статических ресурсов (JavaScript-чанки, CSS, шрифты, медиа). Все последующие переходы между страницами и отображение представлений выполняются клиентским JavaScript-роутером без перезагрузки всей страницы с сервера.
- **HTML5 History API (Client-side Routing)** — механизм браузера (`window.history.pushState` и `replaceState`), позволяющий веб-приложению эмулировать переходы по URL (например, `/dashboard/settings` или `/users/42`) без отправки реального HTTP-запроса на сервер. При прямом обращении или нажатии клавиши F5 браузер запрашивает этот путь у Nginx, что требует обязательной серверной поддержки (fallback).
- **History API Fallback (`try_files`)** — директива Nginx `try_files $uri $uri/ /index.html;`, проверяющая физическое существование запрошенного файла или каталога на диске. Если ресурс не найден, Nginx отдает базовый `index.html` со статусом `200 OK`, делегируя разбор маршрута клиентскому роутеру.
- **Cache Busting (Хэширование ассетов)** — методология сборки фронтенда современными бандлерами (Vite, Webpack, Rollup), при которой в имена генерируемых файлов встраивается хэш содержимого (например, `assets/index-B7x9L2a.js`). Изменение исходного кода меняет хэш и имя файла, гарантируя мгновенную загрузку нового кода клиентами.
- **Матрица клиентского кэширования SPA** — разделение статики на две взаимоисключающие категории:
  1. `index.html` — **никогда не кэшируется** (`Cache-Control: no-cache, no-store, must-revalidate`), чтобы клиент при каждом открытии получал актуальные ссылки на новые сборки.
  2. Хэшированные ассеты (`/assets/*`) — **кэшируются на максимальный срок** (`Cache-Control: public, max-age=31536000, immutable`), так как их содержимое гарантированно неизменно.
- **Off-by-slash в `proxy_pass`** — критическая особенность нормализации URI в Nginx. Наличие завершающего слэша в адресе прокси (`proxy_pass http://backend/;`) приводит к замене совпавшего префикса `location`, тогда как отсутствие слэша (`proxy_pass http://backend;`) передает оригинальный URI запроса без модификаций.
- **Static Precompression (`gzip_static` / `brotli_static`)** — отдача предварительно сжатых файлов (`.gz` и `.br`), подготовленных на этапе CI/CD сборки. Позволяет отдавать сжатый контент через системный вызов `sendfile(2)` без затрат CPU сервера на сжатие в реальном времени.

---

## 2. Архитектура и принципы работы

### 2.1 Схема разделения потоков трафика в SPA Gateway

Nginx выступает в роли единой точки входа (Single Entry Point), терминирует TLS, раздает статическую сборку и проксирует API-запросы:

```text
                               Клиентский браузер
                                       │
                      HTTPS :443       │
                                       ▼
                     ┌──────────────────────────────────┐
                     │    Nginx Edge / SPA Gateway      │
                     │  - TLS Termination & HTTP/2      │
                     │  - Security Headers (CSP, HSTS)  │
                     └─────────────────┬────────────────┘
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            │                                                     │
   GET /assets/main-d3b1.js                             POST /api/v1/auth/login
   GET /users/profile (F5)                                        │
            │                                                     │
            ▼                                                     ▼
┌──────────────────────────────┐              ┌───────────────────────────────────────┐
│ Локальная файловая система   │              │ Backend Upstream Cluster              │
│ /var/www/spa/dist            │              │ (Go / Node.js / Python / Java)        │
│                              │              │                                       │
│ - /assets/* ──► immutable    │              │ HTTP/1.1 Keepalive                    │
│ - index.html ──► no-store    │              │ proxy_set_header X-Real-IP            │
│ - fallback: try_files        │              │ proxy_set_header X-Request-ID         │
└──────────────────────────────┘              └───────────────────────────────────────┘
```

### 2.2 Логика обработки запросов: статика против динамики

1. **Запрос хэшированного ресурса (`/assets/chunk-A1b2.js`):**
   * Срабатывает блок `location /assets/`.
   * Nginx находит файл на диске и отдает его напрямую из page cache ядра Linux через `sendfile(2)`.
   * Заголовок ответа: `Cache-Control: public, max-age=31536000, immutable`. Браузер сохраняет файл на 1 год и больше не обращается к серверу за ним.
2. **Запрос клиентского маршрута (`/orders/123/edit`):**
   * Срабатывает базовый блок `location /`.
   * Директива `try_files $uri $uri/ /index.html;` проверяет наличие файла `/orders/123/edit` и каталога `/orders/123/edit/`.
   * Так как физического файла нет, управление передается на `/index.html`.
   * Nginx отдает `index.html` со статусом `200 OK` и заголовками `Cache-Control: no-cache, no-store, must-revalidate`.
   * Браузер загружает свежий `index.html`, парсит теги `<script>`, скачивает актуальные чанки и инициализирует клиентский роутер, который рендерит страницу редактирования заказа.
3. **Запрос к программному интерфейсу (`/api/v1/data`):**
   * Срабатывает приоритетный блок `location /api/`.
   * Статический обработчик отключается; активируется модуль `ngx_http_upstream_module`.
   * Запрос проксируется на внутренний порт приложения или Unix Domain Socket с сохранением сквозного `X-Request-ID`.

---

## 3. Практические сценарии

### Сценарий 1: Production SPA (React/Vue/Vite) + Backend API на хосте (Bare-Metal / VM)

**Контекст:** На сервере развернуто клиентское приложение на базе Vite в каталоге `/var/www/frontend/dist` и локальный сервис API (Node.js/Go) на порту `127.0.0.1:8080`.

#### 1. Эталонный конфигурационный файл (`/etc/nginx/conf.d/spa_application.conf`)

```nginx
# Пул бэкенд-серверов API с постоянными соединениями
upstream backend_api_cluster {
    server 127.0.0.1:8080 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

# Карта MIME-типов для сжатия (устанавливается в http или подключается)
server {
    listen 80;
    listen [::]:80;
    server_name app.example.com;

    # Принудительный редирект на HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name app.example.com;

    # SSL сертификаты (Let's Encrypt / Корпоративный CA)
    ssl_certificate /etc/letsencrypt/live/app.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL_SPA:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # Корневой каталог сборки фронтенда
    root /var/www/frontend/dist;
    index index.html;

    # Оптимизация дискового ввода-вывода
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;

    # Статическое и динамическое сжатие
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types
        text/plain
        text/css
        text/javascript
        application/javascript
        application/json
        application/x-javascript
        text/xml
        application/xml
        application/xml+rss
        image/svg+xml;

    # Проверка наличия предварительно сжатых файлов (.gz)
    gzip_static on;

    # Базовые заголовки безопасности (Security Headers)
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https://app.example.com;" always;

    # 1. API Reverse Proxy
    location /api/ {
        proxy_pass http://backend_api_cluster;

        # Протокол HTTP/1.1 и очистка Connection для активации upstream keepalive
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # Проброс заголовков хоста и реального адреса клиента
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Сквозной correlation ID для трассировки запросов
        proxy_set_header X-Request-ID $request_id;
        add_header X-Request-ID $request_id always;

        # Лимиты и таймауты
        proxy_connect_timeout 5s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
        client_max_body_size 10m;

        # Отключение буферизации для снижения задержек API (по необходимости)
        proxy_buffering on;
        proxy_buffer_size 8k;
        proxy_buffers 8 8k;
    }

    # 2. Неизменяемые хэшированные статические ресурсы (JS, CSS, Media)
    location /assets/ {
        # Vite помещает все чанки в подкаталог /assets/
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";
        access_log off;
        try_files $uri =404;
    }

    # 3. Служебные статические файлы корня (favicon, robots.txt, manifest)
    location ~* \.(?:ico|png|svg|webp|txt|xml|webmanifest)$ {
        expires 7d;
        add_header Cache-Control "public, max-age=604800";
        access_log off;
        try_files $uri =404;
    }

    # 4. Основной роутинг приложения и точка входа (History API Fallback)
    location / {
        # Запрет кэширования index.html для исключения "залипания" старых релизов
        add_header Cache-Control "no-cache, no-store, must-revalidate" always;
        add_header Pragma "no-cache" always;
        add_header Expires "0" always;

        # Каскадная проверка: файл -> каталог -> fallback на index.html
        try_files $uri $uri/ /index.html;
    }

    # Запрет доступа к скрытым системным файлам (.git, .env)
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }
}
```

---

### Сценарий 2: Контейнеризированный SPA + Gateway в Docker Compose

**Контекст:** В CI/CD собирается неизменяемый Docker-образ фронтенда, в который копируется скомпилированная статика. Nginx работает в изолированном контейнере, направляя трафик на соседний контейнер `backend-service` по внутренней сети Docker.

#### 1. Многоэтапная сборка образа фронтенда (`Dockerfile.frontend`)

```dockerfile
# Этап 1: Сборка статических файлов
FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build && \
    # Предварительное сжатие gzip для модуля gzip_static
    find dist -type f -regex '.*\.\(js\|css\|html\|svg\|json\)$' -exec gzip -9 -k {} +

# Этап 2: Минимальный production-образ Nginx
FROM nginx:1.27-alpine
# Удаление дефолтного виртуального хоста
RUN rm -f /etc/nginx/conf.d/default.conf
# Копирование сборки
COPY --from=builder /app/dist /usr/share/nginx/html
# Копирование кастомного конфига
COPY nginx.conf /etc/nginx/conf.d/app.conf

EXPOSE 80
STOPSIGNAL SIGQUIT
CMD ["nginx", "-g", "daemon off;"]
```

#### 2. Конфигурация Nginx в контейнере (`nginx.conf`)

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # Встроенный DNS Docker Engine для разрешения имени сервиса
    resolver 127.0.0.11 valid=10s ipv6=off;

    gzip on;
    gzip_static on;
    gzip_types text/plain text/css application/javascript application/json image/svg+xml;

    location /api/ {
        # Использование переменной активирует runtime DNS resolution в Docker
        set $upstream_backend http://backend-service:5000;
        proxy_pass $upstream_backend;

        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";
        access_log off;
        try_files $uri =404;
    }

    location / {
        add_header Cache-Control "no-cache, no-store, must-revalidate" always;
        try_files $uri $uri/ /index.html;
    }
}
```

#### 3. Оркестрация в `docker-compose.yml`

```yaml
services:
  frontend-gateway:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    container_name: spa_frontend_gateway
    restart: unless-stopped
    ports:
      - "80:80"
    networks:
      - app_internal_network
    depends_on:
      - backend-service

  backend-service:
    image: mycompany/api-service:1.4.2
    container_name: api_backend_app
    restart: unless-stopped
    environment:
      - PORT=5000
      - NODE_ENV=production
    networks:
      - app_internal_network

networks:
  app_internal_network:
    driver: bridge
```

---

### Сценарий 3: Поддержка WebSockets и Server-Sent Events (SSE) в SPA

**Контекст:** В SPA требуется обновлять данные в реальном времени (уведомления, чаты, живые графики) через WebSocket (`/ws/`) или Server-Sent Events (`/api/stream`).

```nginx
# Маппинг для безопасного переключения протокола Connection
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl http2;
    server_name app.example.com;

    # ... (SSL и базовые параметры) ...

    # WebSocket эндпоинт
    location /ws/ {
        proxy_pass http://backend_api_cluster;
        proxy_http_version 1.1;

        # Заголовки рукопожатия Upgrade
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # Увеличение таймаута ожидания передачи данных (1 час)
        # Предотвращает разрыв неактивного сокета каждые 60 секунд
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # Server-Sent Events (SSE) эндпоинт
    location /api/v1/stream {
        proxy_pass http://backend_api_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;

        # КРИТИЧНО для SSE: немедленная отдача эвентов клиенту без накопления в буфере
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;

        proxy_read_timeout 1800s;
    }
}
```

---

## 4. Операции и команды

### 4.1 Проверка конфигурации и атомарное развертывание

```bash
# Валидация синтаксиса перед перезагрузкой
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Безопасное применение изменений (Graceful Reload)
sudo systemctl reload nginx
```

### 4.2 Проверка клиентских заголовков кэширования через `curl`

```bash
# 1. Проверка index.html: должен возвращаться статус 200 и запрет кэширования
curl -I -s https://app.example.com/
# → HTTP/2 200
# → cache-control: no-cache, no-store, must-revalidate
# → pragma: no-cache
# → x-frame-options: SAMEORIGIN
# → x-content-type-options: nosniff

# 2. Проверка виртуального SPA-маршрута: должен отдаваться index.html (200 OK)
curl -I -s https://app.example.com/dashboard/analytics/reports
# → HTTP/2 200
# → cache-control: no-cache, no-store, must-revalidate

# 3. Проверка хэшированного ассета: кэширование на 1 год и статус immutable
curl -I -s https://app.example.com/assets/index-B7x9L2a.js
# → HTTP/2 200
# → cache-control: public, max-age=31536000, immutable
# → content-type: application/javascript

# 4. Проверка API-проксирования: проброс заголовка X-Request-ID
curl -I -s https://app.example.com/api/v1/health
# → HTTP/2 200
# → x-request-id: 9a7b3c2d4e5f6a7b8c9d0e1f2a3b4c5d
# → content-type: application/json
```

---

## 5. Диагностика и устранение неисправностей

| Симптом / Ошибка | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`404 Not Found` при обновлении страницы по F5** (на маршрутах `/users`, `/profile`) | В конфигурации Nginx отсутствует fallback через `try_files` на `index.html`. Nginx пытается найти физическую папку `/users` на диске. | В `error.log`: `"open() "/var/www/dist/users" failed (2: No such file or directory)"` | Убедиться, что в `location /` присутствует: `try_files $uri $uri/ /index.html;`. |
| **Клиенты видят белый экран после релиза (MIME type mismatch)** | Браузер запросил старый хэш чанка (из закешированного `index.html`), которого уже нет на сервере. Браузер получает `index.html` вместо `.js` и ругается на некорректный MIME-тип (`text/html`). | В консоли браузера: `"Refused to execute script from '...' because its MIME type ('text/html') is not executable"`. | 1. Запретить кэширование `index.html` (`no-store`).<br>2. Не удалять файлы старых сборок из `/var/www/dist/assets/` сразу, сохранять 2-3 предыдущих релиза на 24 часа. |
| **Задвоение или срез префикса URI в API (`404` от бэкенда)** | Ошибка со слэшем в директиве `proxy_pass`. Настройка `proxy_pass http://backend/;` срезает `/api/`, отправляя на бэкенд `/v1/users`, тогда как приложение ожидает `/api/v1/users`. | В `access.log` бэкенда: `GET /v1/users` вместо `GET /api/v1/users`. | Если бэкенд сам ждет префикс `/api/`, убрать слэш: `proxy_pass http://backend_api_cluster;`. |
| **Циклический редирект (Internal Redirection Cycle)** | В `try_files` указан несуществующий файл fallback (например, опечатка в пути к `index.html`), либо у Nginx нет прав на чтение корня. | В `error.log`: `"rewrite or internal redirection cycle while internally redirecting to "/index.html""` | 1. Проверить права: `chmod 755 /var/www/dist && chown -R www-data:www-data /var/www/dist`.<br>2. Убедиться, что `index.html` физически присутствует в каталоге `root`. |
| **`413 Request Entity Too Large` при загрузке файлов** | По умолчанию директива `client_max_body_size` равна 1 МБ, что блокирует загрузку изображений или документов через форму SPA. | В `error.log`: `"client intended to send too large body: 5242880 bytes"` | Добавить в блок `location /api/` директиву: `client_max_body_size 25m;`. |

---

## 6. Рекомендации и лучшие практики

1. **Никогда не кэшируйте `index.html`:**  
   Единственная точка входа SPA должна всегда запрашиваться заново. Это гарантирует мгновенную доставку новых версий без необходимости просить пользователей очищать кэш браузера (`Ctrl+F5`).
2. **Активируйте предварительное сжатие `gzip_static` / `brotli_static`:**  
   Сжатие ассетов на этапе сборки с максимальным уровнем компрессии (`gzip -9` или `brotli -11`) полностью разгружает процессор сервера и ускоряет загрузку скриптов на 15–30%.
3. **Храните N-1 релиз на сервере (Asset Retention):**  
   При развертывании новой версии статики не очищайте каталог `/assets/` полностью. Если пользователь открыл вкладку до релиза и продолжает кликать по приложению, его браузер будет запрашивать старые чанки. Удаляйте старые файлы через 24–48 часов после деплоя.
4. **Управляйте пулами соединений к бэкенду (Upstream Keepalive):**  
   Для высоконагруженных API-шлюзов обязательно включайте `keepalive 32;` в блоке `upstream` и задавайте `proxy_http_version 1.1; proxy_set_header Connection "";`. Это устраняет накладные расходы на TCP-хэндшейки между Nginx и API.
5. **Используйте сквозной идентификатор запроса (`$request_id`):**  
   Всегда пробрасывайте заголовок `X-Request-ID` в бэкенд и возвращайте его клиенту. При возникновении ошибки фронтенд может отобразить этот ID пользователю, что сокращает время поиска инцидента в логах до нескольких секунд.

---

## 7. Дополнительная информация

- [Nginx: отдача статических файлов](../Core/Location/serving_files.md) — низкоуровневая оптимизация дискового ввода-вывода (`sendfile`, `open_file_cache`).
- [Клиентское кэширование в Nginx и Angie](../Performance/Caching/client_caching.md) — эталонные настройки HTTP-заголовков кэширования RFC 9111.
- [Шейпинг трафика и Rate Limiting](../Performance/nginx_traffic_shaping_and_overload_protection.md) — защита API от перегрузок и злоупотреблений.
- [Стратегии Cache Busting в CI/CD](../../../CI-CD/Frontend_CI_CD/frontend_pipeline_specifics.md) — генерация уникальных хэшей ассетов в автоматизированных пайплайнах.
