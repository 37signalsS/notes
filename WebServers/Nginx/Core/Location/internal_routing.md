# Nginx: Внутренняя маршрутизация

> **Надежность: 10** (Подтверждено актуальной документацией Nginx на июнь 2026)

## Определения

**Внутренняя маршрутизация (internal routing)** — механизм Nginx, при котором запросы перенаправляются внутри сервера без участия клиента. Клиент не знает о внутренних перенаправлениях — URL (Uniform Resource Locator — унифицированный определитель местонахождения ресурса) в браузере не меняется.

Ключевые инструменты внутренней маршрутизации:

- **Именованные `location`** (`@name`) — блоки для внутренних перенаправлений, которые невозможно вызвать напрямую внешним запросом.
- **Директива `internal`** — ограничивает доступ к `location` только внутренними запросами Nginx.
- **Директива `error_page`** — механизм обработки ошибок через внутренние редиректы.

## Базовые концепции

### Именованные location (`@name`)

Именованные `location` используются для внутренних перенаправлений внутри Nginx, например, с помощью директив `try_files` или `error_page`. Они не участвуют в обычном процессе сопоставления URI (Uniform Resource Identifier — унифицированный идентификатор ресурса).

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

В этом примере, если Nginx не находит статический файл, он выполняет внутреннее перенаправление на именованный `location @backend`, который проксирует запрос к бэкенд-серверам.

### Директива `internal`

Директива `internal` внутри блока `location` делает его доступным только для внутренних запросов. Если клиент попытается обратиться к такому пути напрямую, Nginx вернёт ошибку `404 Not Found`.

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

Это критически важно для защиты конфиденциальных ресурсов, скриптов или внутренних API (Application Programming Interface — программный интерфейс приложения).

## Практические сценарии

### Сценарий 1: Обработка ошибок через error_page

Директива `error_page` позволяет определить кастомные страницы ошибок. Она выполняет внутреннее перенаправление при возникновении указанного HTTP-кода.

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

**Принцип работы:**

- `error_page 404 /404.html;` — при возникновении ошибки 404 Nginx переходит к обработке `/404.html`.
- `location = /404.html { internal; }` — гарантирует, что страница ошибки недоступна для прямого вызова извне.

### Сценарий 2: Fallback на бэкенд для SPA

Типичный паттерн для SPA (Single Page Application — одностраничное приложение) или статических сайтов с динамическим fallback:

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
        internal; # Доступ только для внутренних вызовов
        proxy_pass http://127.0.0.1:8080;
    }
}
```

**Логика обработки:**

1. Запрос `/index.html` → отдаётся статический файл.
2. Запрос `/dashboard` (маршрут на стороне клиента) → файл не найден → внутренний редирект на `@app`.
3. Прямой запрос клиента к `/api/` → ошибка 404 из-за директивы `internal`.

### Сценарий 3: Возврат JSON при ошибках API

Если Nginx работает как API-шлюз, ошибки должны возвращаться в формате JSON (JavaScript Object Notation).

```nginx
server {
    error_page 404 = @handle_404;
    error_page 500 = @handle_500;

    location @handle_404 {
        internal;
        default_type application/json;
        return 404 '{"error": "not_found", "path": "$uri"}';
    }

    location @handle_500 {
        internal;
        default_type application/json;
        return 500 '{"error": "internal_server_error"}';
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
```

## Дополнительная информация

### Взаимодействие с другими директивами

- **`try_files`** — основной инициатор внутренних перенаправлений.
- **`proxy_intercept_errors`** — позволяет перехватывать ошибки от бэкенда для их обработки через локальную директиву `error_page`.

### См. также

- [Директива location: основы и приоритеты](./basics.md)
- [Rewrite правила и try_files](../nginx_rewrite_rules_and_try_files.md)
- [Лучшие практики и отладка location](./best_practices.md)
