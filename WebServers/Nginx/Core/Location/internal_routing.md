# Nginx: Internal Routing

## Definitions

**Internal routing (внутренняя маршрутизация)** — механизм Nginx, при котором запросы перенаправляются внутри сервера без участия клиента. Клиент не знает о внутренних перенаправлениях — URL в браузере не меняется.

Ключевые инструменты internal routing:
- **Именованные `location`** (`@name`) — блоки для внутренних перенаправлений
- **Директива `internal`** — ограничивает доступ к `location` только внутренними запросами
- **Директива `error_page`** — обработка ошибок через внутренние редиректы

## Basic Concepts

### Именованные location (`@name`)

Именованные `location` не могут быть вызваны напрямую клиентом. Они используются для внутренних перенаправлений внутри Nginx, например, с помощью `try_files` или `error_page`.

**Синтаксис:** `@name`

**Пример:**

```nginx
location / {
    try_files $uri @backend;
}

location @backend {
    proxy_pass http://my_backend_servers;
}
```

В этом примере, если Nginx не находит статический файл, он внутренне перенаправляет запрос на именованный `location @backend`, который затем проксирует запрос к бэкенд-серверам.

### Директива `internal`

Директива `internal` внутри `location` делает этот `location` доступным только для внутренних запросов Nginx. Клиентские запросы к такому `location` будут отклонены с ошибкой 404 Not Found.

**Пример:**

```nginx
location /private_data/ {
    internal;
    root /var/www/internal_files;
}

location /error_pages/ {
    internal;
    root /var/www/errors;
}
```

Это полезно для защиты конфиденциальных ресурсов или для организации внутренних API, которые не должны быть доступны извне.

## Practical Scenarios

### Сценарий 1: Обработка ошибок через error_page

Директива `error_page` позволяет определить кастомные страницы ошибок. Она выполняет **внутреннее перенаправление** при возникновении указанной ошибки.

**Синтаксис:** `error_page code ... [=[response]] uri;`

```nginx
server {
    root /var/www/html;

    error_page 404 /404.html;
    error_page 500 502 503 504 /50x.html;

    location / {
        try_files $uri $uri/ =404;
    }

    location = /404.html {
        internal;
    }

    location = /50x.html {
        internal;
    }
}
```

**Как это работает:**
- `error_page 404 /404.html;` — при ошибке 404 Nginx выполняет внутреннее перенаправление на `/404.html`
- `location = /404.html { internal; }` — страница ошибки доступна только для внутренних запросов; прямой запрос клиента вернёт 404

### Сценарий 2: Fallback на бэкенд

Типичный паттерн для SPA-приложений или статических сайтов с динамическим fallback:

```nginx
server {
    root /var/www/app;

    location / {
        try_files $uri $uri/ @app;
    }

    location @app {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api/ {
        internal;
        proxy_pass http://127.0.0.1:8080;
    }
}
```

**Порядок обработки:**
1. Запрос `/index.html` → ищется статический файл
2. Запрос `/dashboard` → файл не найден → внутренний редирект на `@app`
3. Запрос `/api/data` напрямую клиентом → 404 (директива `internal`)

### Сценарий 3: Внутренний API для обработки ошибок

```nginx
server {
    error_page 404 = @handle_404;
    error_page 500 = @handle_500;

    location @handle_404 {
        internal;
        return 404 '{"error": "not_found", "path": "$uri"}';
        default_type application/json;
    }

    location @handle_500 {
        internal;
        return 500 '{"error": "internal_server_error"}';
        default_type application/json;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
```

Этот паттерн возвращает JSON-ответы для API вместо HTML-страниц ошибок.

## Additional Information

### Связь с другими директивами

- `try_files` — основной триггер внутренних перенаправлений
- `proxy_intercept_errors` — перехват ошибок от бэкенда для обработки через `error_page`

### См. также

- [Директива location: основы и приоритеты](./basics.md)
- [Rewrite правила и try_files](../nginx_rewrite_rules_and_try_files.md)
- [Лучшие практики и отладка location](./best_practices.md)
