# Nginx: внутренняя маршрутизация

> **Надежность: 10** (Подтверждено актуальной документацией Nginx на июль 2026)

## Определения

**Внутренняя маршрутизация (Internal routing)** — механизм Nginx, при котором запросы перенаправляются внутри сервера без участия клиента. Клиент не получает HTTP-редирект (301/302), и URL (Uniform Resource Locator — унифицированный определитель местонахождения ресурса) в браузере остается неизменным.

Ключевые инструменты внутренней маршрутизации:

- **Именованные `location`** (`@name`) — блоки для внутренних перенаправлений, которые невозможно вызвать напрямую внешним запросом.
- **Директива `internal`** — ограничивает доступ к `location` только внутренними запросами Nginx.
- **Директива `error_page`** — механизм обработки ошибок через внутренние редиректы.
- **Заголовок `X-Accel-Redirect`** — позволяет бэкенду инициировать отдачу файла самим Nginx.

---

## Базовые концепции

### Именованные location (`@name`)

Именованные `location` не участвуют в обычном сопоставлении URI (Uniform Resource Identifier — унифицированный идентификатор ресурса). Они вызываются только явно через другие директивы, такие как `try_files` или `error_page`.

```nginx
location / {
    # Сначала пытаемся отдать статику, если нет — уходим на @backend
    try_files $uri @backend;
}

location @backend {
    proxy_pass http://upstream_app;
}
```

### Директива `internal`

Директива `internal` внутри блока `location` делает его доступным только для внутренних перенаправлений. Прямой запрос от клиента вернет `404 Not Found`.

**Случаи использования:**
- Защита страниц ошибок (`error_page`).
- Защита статики, отдаваемой через `X-Accel-Redirect`.
- Внутренние API-эндпоинты (например, для модуля `auth_request`).

### Лимиты и предотвращение циклов

Nginx ограничивает количество внутренних перенаправлений до **10** на один запрос. Если лимит превышен, Nginx возвращает ошибку `500 Internal Server Error`.

```bash
tail -f /var/log/nginx/error.log
# → rewrite or internal redirection cycle while internal redirection to "/index.html"
```

---

## Практические сценарии

### Сценарий 1: Управление отдачей файлов бэкендом (`X-Accel-Redirect`)

Бэкенд-приложение проверяет права доступа и решает, какой файл отдать, отправляя заголовок `X-Accel-Redirect`. Nginx перехватывает его и отдает файл сам (Zero-Copy).

```nginx
# Конфигурация Nginx
location /internal_files/ {
    internal;
    root /var/www/protected;
}

location /download {
    proxy_pass http://app_server;
}
```

**Логика:**
1. Клиент запрашивает `/download`.
2. Бэкенд возвращает заголовок `X-Accel-Redirect: /internal_files/report.pdf`.
3. Nginx отдает `/var/www/protected/internal_files/report.pdf`.

### Сценарий 2: Рекурсивные страницы ошибок

Если сама страница ошибки вызывает ошибку (например, из-за отсутствия прав), Nginx вернет стандартную заглушку. Директива `recursive_error_pages` позволяет продолжать внутренние перенаправления.

```nginx
server {
    recursive_error_pages on;
    error_page 404 /404.php;

    location = /404.php {
        internal;
        fastcgi_pass unix:/run/php/php-fpm.sock;
    }
}
```

### Сценарий 3: Внутренняя проверка авторизации (`auth_request`)

Модуль `auth_request` выполняет внутренний подзапрос для проверки прав доступа.

```nginx
location /private/ {
    auth_request /auth-verify;
    root /var/www/private;
}

location = /auth-verify {
    internal;
    proxy_pass http://auth_service/validate;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
}
```

### Сценарий 4: Возврат JSON при ошибках API

Для API (Application Programming Interface — программный интерфейс приложения) ошибки должны быть в формате JSON (JavaScript Object Notation).

```nginx
server {
    error_page 404 = @json_404;

    location @json_404 {
        internal;
        default_type application/json;
        return 404 '{"status": 404, "message": "Not Found"}';
    }
}
```

---

## Дополнительная информация

### Нюансы использования

- **`proxy_intercept_errors on;`** — необходима, если вы хотите, чтобы `error_page` обрабатывала ошибки, пришедшие от бэкенда (`proxy_pass`).
- **URI при редиректе** — при переходе в именованный `location` переменная `$uri` сохраняет исходное значение запроса.

### См. также

- [Директива location: основы и приоритеты](./basics.md)
- [Rewrite правила и try_files](../nginx_rewrite_rules_and_try_files.md)
- [Лучшие практики и отладка location](./best_practices.md)
