# Cross-Origin Resource Sharing (CORS) в Nginx

**Актуально для:** Nginx 1.24+ / 1.26+ (Stable), 1.27+ / 1.28+ (Mainline)

---

## Определения

**Cross-Origin Resource Sharing (CORS)** — механизм безопасности браузеров (спецификация W3C / WHATWG Fetch Standard), позволяющий веб-странице с одним источником (Origin: схема + домен + порт) безопасно выполнять запросы к ресурсам другого источника.

**Origin (Источник)** — тройка протокола, доменного имени и TCP-порта (`https://app.example.com:443`). Передается браузером в заголовке `Origin` при любом межсайтовом запросе, а также при `POST`-запросах.

**Preflight-запрос (Предварительный запрос)** — предварительный HTTP-запрос методом `OPTIONS`, автоматически отправляемый браузером перед выполнением сложного запроса (запросы с методами `PUT`, `DELETE`, `PATCH`, кастомными заголовками вроде `Authorization` или типами контента, отличными от стандартных `application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`).

**Простой запрос (Simple Request)** — запрос методами `GET`, `HEAD` или `POST` со стандартными заголовками и типами контента. Браузер отправляет его сразу, без отправки preflight `OPTIONS`.

**Заголовки семейства `Access-Control-*`:**
- `Access-Control-Allow-Origin` — указывает разрешенный источник (`*` или точный URL источника).
- `Access-Control-Allow-Methods` — список разрешенных HTTP-методов для кросс-доменных запросов (`GET, POST, PUT, DELETE, OPTIONS, PATCH`).
- `Access-Control-Allow-Headers` — список разрешенных заголовков клиента (`Authorization, Content-Type, X-Requested-With, X-Request-ID`).
- `Access-Control-Allow-Credentials` — флаг (`true`), разрешающий браузеру передавать пользовательские учетные данные (cookies, HTTP-аутентификацию, клиентские TLS-сертификаты).
- `Access-Control-Max-Age` — время в секундах, на которое браузер может кэшировать результат preflight-запроса, избегая повторных `OPTIONS`.
- `Access-Control-Expose-Headers` — список заголовков ответа бэкенда, к которым браузерный JavaScript имеет явный доступ (`Content-Disposition, X-Request-ID`).

---

## Архитектура и базовые концепции

### Жизненный цикл CORS-запроса в Nginx

```
[Браузер]                                            [Nginx Reverse Proxy]                 [Бэкенд-сервис]
   │                                                           │                                  │
   │ ── 1. OPTIONS /api/v1/resource (Preflight) ─────────────> │                                  │
   │    Origin: https://app.example.com                        │                                  │
   │    Access-Control-Request-Method: DELETE                  │                                  │
   │    Access-Control-Request-Headers: Authorization          │                                  │
   │                                                           │                                  │
   │                                                           │ [Проверка Origin через map]      │
   │                                                           │ [Генерация ответа: 204 No Cont]  │
   │                                                           │ (Запрос НЕ передается бэкенду)   │
   │                                                           │                                  │
   │ <── 2. HTTP/1.1 204 No Content ────────────────────────── │                                  │
   │    Access-Control-Allow-Origin: https://app.example.com   │                                  │
   │    Access-Control-Allow-Methods: GET, POST, PUT, DELETE   │                                  │
   │    Access-Control-Allow-Headers: Authorization,...        │                                  │
   │    Access-Control-Allow-Credentials: true                 │                                  │
   │    Access-Control-Max-Age: 86400                          │                                  │
   │                                                           │                                  │
   │ ── 3. DELETE /api/v1/resource (Фактический запрос) ─────> │ ── 4. DELETE /api/v1/resource ─> │
   │    Origin: https://app.example.com                        │    (Проксирование на апстрим)    │
   │    Authorization: Bearer <token>                          │                                  │
   │                                                           │ <── 5. HTTP/1.1 200 OK ───────── │
   │                                                           │                                  │
   │ <── 6. HTTP/1.1 200 OK ────────────────────────────────── │                                  │
   │    Access-Control-Allow-Origin: https://app.example.com   │                                  │
   │    Access-Control-Allow-Credentials: true                 │                                  │
```

### Ловушки и архитектурные правила Nginx

#### 1. Недопустимость подстановочного знака `*` с `credentials`
Согласно стандарту CORS (W3C), если сервер возвращает заголовок `Access-Control-Allow-Credentials: true`, заголовок `Access-Control-Allow-Origin` **ни при каких условиях не может содержать `*`**. Браузер заблокирует такой ответ с фатальной ошибкой консоли:
`The value of the 'Access-Control-Allow-Origin' header in the response must not be the wildcard '*' when the request's credentials mode is 'include'`.

В ответе должен возвращаться **точный origin запрашивающего клиента**, прошедший валидацию по белому списку.

#### 2. Декларативная валидация Origin через `map` (защита от отражения)
Ошибочный подход — слепо возвращать значение клиентского заголовка `$http_origin`:
```nginx
# УЯЗВИМАЯ КОНФИГУРАЦИЯ (Arbitrary Origin Reflection):
add_header Access-Control-Allow-Origin $http_origin always;
```
Это полностью нивелирует защиту Same-Origin Policy: любой вредоносный сайт (`evil.com`) сможет инициировать запросы от имени аутентифицированного пользователя.

Корректное решение — декларативная таблица разрешенных доменов через директиву `map` в контексте `http`:
```nginx
map $http_origin $cors_origin {
    default                         "";
    "~^https?://(.*\.)?example\.com(:[0-9]+)?$" "$http_origin";
    "https://partner-portal.ru"      "$http_origin";
    "http://localhost:3000"          "$http_origin";
}
```

#### 3. Ловушка наследования `add_header` в блоках `location` и `if`
Директива `add_header` относится к директивам списочного типа. Если внутри блока `location` (или вложенного `if`) объявлена хотя бы одна собственная директива `add_header`, **все родительские директивы `add_header` (заголовки безопасности HSTS, CSP, X-Frame-Options) полностью аннулируются**.

Поэтому:
1. Заголовки CORS всегда дополняются параметром `always`: `add_header ... always;` (гарантирует отдачу заголовка даже при ошибках 4xx/5xx).
2. Заголовки preflight-ответа объявляются в изолированном блоке или подключаются через `include snippets/cors.conf`.

#### 4. Конфликт дублирования заголовков бэкенда
Если приложение за Nginx (например, Spring Boot, FastAPI, Node.js) также выставляет заголовки CORS, клиент получит дублирующиеся строки:
`Access-Control-Allow-Origin: https://site.ru, https://site.ru`
Браузер сочтет ответ невалидным и заблокирует ресурс. Для предотвращения дублей в Nginx используется директива:
`proxy_hide_header Access-Control-Allow-Origin;`

---

## Практические сценарии

### Сценарий 1: Промышленный API-шлюз с мультидоменным CORS и поддержкой учетных данных (Credentials)

**Задача:** Обеспечить безопасный доступ к REST API `/api/` для нескольких доверенных фронтендов с поддержкой JWT в cookies и предзапросов `OPTIONS`.

```nginx
# /etc/nginx/conf.d/cors_api.conf

# 1. Белый список разрешенных источников (контекст http)
map $http_origin $cors_origin {
    default                                 "";
    "https://frontend.company.com"          "$http_origin";
    "https://admin.company.com"             "$http_origin";
    "~^https://.*\.partner-service\.ru$"    "$http_origin";
    "http://localhost:5173"                 "$http_origin"; # Локальная разработка (Vite)
}

# 2. Определение preflight-запроса OPTIONS
map $request_method $is_options {
    default 0;
    OPTIONS 1;
}

server {
    listen 443 ssl;
    server_name api.company.com;

    ssl_certificate     /etc/ssl/certs/api.company.com.crt;
    ssl_certificate_key /etc/ssl/private/api.company.com.key;

    location /api/ {
        # Скрываем заголовки бэкенда, чтобы исключить дублирование
        proxy_hide_header Access-Control-Allow-Origin;
        proxy_hide_header Access-Control-Allow-Credentials;
        proxy_hide_header Access-Control-Allow-Methods;
        proxy_hide_header Access-Control-Allow-Headers;

        # Обработка Preflight OPTIONS запроса
        if ($is_options) {
            add_header Access-Control-Allow-Origin $cors_origin always;
            add_header Access-Control-Allow-Credentials "true" always;
            add_header Access-Control-Allow-Methods "GET, POST, PUT, PATCH, DELETE, OPTIONS" always;
            add_header Access-Control-Allow-Headers "Authorization, Content-Type, Accept, Origin, X-Requested-With, X-Request-ID" always;
            add_header Access-Control-Max-Age 86400 always; # Кэш preflight на 24 часа
            add_header Content-Length 0 always;
            add_header Content-Type "text/plain; charset=utf-8" always;
            return 204;
        }

        # Заголовки для фактических запросов (GET, POST, PUT, DELETE)
        add_header Access-Control-Allow-Origin $cors_origin always;
        add_header Access-Control-Allow-Credentials "true" always;
        add_header Access-Control-Expose-Headers "Content-Length, Content-Range, X-Request-ID" always;

        # Базовые заголовки безопасности (восстановление после add_header)
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Frame-Options "DENY" always;

        proxy_pass http://backend_cluster;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

### Сценарий 2: Раздача кросс-доменных статических ресурсов (Веб-шрифты, CDN ассеты)

**Задача:** Разрешить загрузку шрифтов (`.woff2`, `.ttf`) и SVG-иконок со статического хоста `cdn.example.com` для любых внешних доменов.

```nginx
# /etc/nginx/conf.d/cdn_static.conf

server {
    listen 80;
    server_name cdn.example.com;
    root /var/www/cdn/public;

    # Изолированный блок для шрифтов с модификатором ^~
    location ^~ /assets/fonts/ {
        # Простые запросы шрифтов не требуют credentials, разрешен wildcard *
        add_header Access-Control-Allow-Origin "*" always;
        add_header Access-Control-Allow-Methods "GET, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Origin, Accept" always;
        add_header Access-Control-Max-Age 604800 always; # 7 дней

        # Preflight для кастомных загрузчиков
        if ($request_method = 'OPTIONS') {
            return 204;
        }

        # Долгосрочное кэширование статики
        expires 365d;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        access_log off;
        try_files $uri =404;
    }
}
```

---

### Сценарий 3: Модульный сниппет CORS для микросервисной архитектуры

**Задача:** Исключить дублирование логики CORS в десятках микросервисных конфигураций Nginx.

Создается переиспользуемый конфигурационный файл `/etc/nginx/snippets/cors.conf`:

```nginx
# /etc/nginx/snippets/cors.conf

if ($request_method = 'OPTIONS') {
    add_header Access-Control-Allow-Origin $cors_origin always;
    add_header Access-Control-Allow-Credentials "true" always;
    add_header Access-Control-Allow-Methods "GET, POST, PUT, PATCH, DELETE, OPTIONS" always;
    add_header Access-Control-Allow-Headers "DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization,X-Request-ID" always;
    add_header Access-Control-Max-Age 86400 always;
    add_header Content-Type "text/plain; charset=utf-8";
    add_header Content-Length 0;
    return 204;
}

add_header Access-Control-Allow-Origin $cors_origin always;
add_header Access-Control-Allow-Credentials "true" always;
add_header Access-Control-Expose-Headers "Content-Length,Content-Range,X-Request-ID" always;
```

Подключение внутри любого `location`:

```nginx
location /services/user/ {
    include /etc/nginx/snippets/cors.conf;
    proxy_pass http://user_service;
}
```

---

## Операции и команды

### 1. Тестирование Preflight-запроса через curl

Проверка ответа на предварительный запрос методом `OPTIONS`:

```bash
curl -k -i -X OPTIONS https://api.company.com/api/v1/users \
  -H "Origin: https://frontend.company.com" \
  -H "Access-Control-Request-Method: DELETE" \
  -H "Access-Control-Request-Headers: Authorization, X-Request-ID"
```

**Ожидаемый ответ:**
```http
HTTP/1.1 204 No Content
Server: nginx
Access-Control-Allow-Origin: https://frontend.company.com
Access-Control-Allow-Credentials: true
Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS
Access-Control-Allow-Headers: Authorization, Content-Type, Accept, Origin, X-Requested-With, X-Request-ID
Access-Control-Max-Age: 86400
Content-Length: 0
```

### 2. Тестирование запрещенного Origin

Проверка отсутствия заголовков CORS для недоверенного источника:

```bash
curl -k -i -X OPTIONS https://api.company.com/api/v1/users \
  -H "Origin: https://malicious-site.evil.com" \
  -H "Access-Control-Request-Method: GET"
```

**Ожидаемый ответ:**
Заголовок `Access-Control-Allow-Origin` должен отсутствовать либо быть пустым.

### 3. Тестирование фактического запроса с учетными данными

```bash
curl -k -i -X GET https://api.company.com/api/v1/users \
  -H "Origin: https://frontend.company.com" \
  -H "Authorization: Bearer test_token"
```

**Ожидаемый ответ:**
```http
HTTP/1.1 200 OK
Access-Control-Allow-Origin: https://frontend.company.com
Access-Control-Allow-Credentials: true
Content-Type: application/json
```

---

## Диагностика и устранение неполадок

### Матрица типичных дефектов

| Симптом / Ошибка в браузере | Причина | Способ диагностики | Решение |
| :--- | :--- | :--- | :--- |
| `Response to preflight request doesn't pass access control check: It does not have HTTP ok status.` | Nginx или бэкенд возвращает 403, 405 или 500 на метод `OPTIONS`. | `curl -i -X OPTIONS ...` показывает код 405 Method Not Allowed. | Добавить обработку метода `OPTIONS` с немедленным возвратом кода `204 No Content`. |
| `The value of the 'Access-Control-Allow-Origin' header must not be the wildcard '*' when credentials mode is 'include'` | Задан `add_header ... "*"` совместно с `credentials: true`. | Инспекция заголовков в ответе: наличие `*` и `true`. | Использовать `map $http_origin $cors_origin` для подстановки точного Origin клиента. |
| `The 'Access-Control-Allow-Origin' header contains multiple values '..., ...', but only one is allowed` | И Nginx, и апстрим-сервер выставляют заголовки CORS одновременно. | В заголовках ответа видны дублирующие строки `Access-Control-Allow-Origin`. | Добавить в `location` директивы `proxy_hide_header Access-Control-Allow-Origin;` и `proxy_hide_header Access-Control-Allow-Credentials;`. |
| Пропадают заголовки безопасности (`HSTS`, `X-Frame-Options`) при включении CORS | Локальный `add_header` в `location` затер родительские заголовки. | `curl -sI https://host/api/` — отсутствие `Strict-Transport-Security`. | Продублировать базовые security headers в блоке `location` либо вынести их в общий snippet. |
| Запрос падает с ошибкой CORS только при статусах 401, 404, 500, 502 | `add_header` объявлен без флага `always`. | При ошибке бэкенда Nginx не отдает заголовки CORS, и браузер скрывает реальную ошибку за CORS error. | Добавить суффикс `always` ко всем директивам `add_header`. |

---

## Лучшие практики (Production & SRE)

1. **Всегда используйте флаг `always`:** Директива `add_header Access-Control-Allow-Origin $cors_origin always;` гарантирует, что браузер получит CORS-заголовки даже при сбоях бэкенда (500/502/504) или ошибках авторизации (401/403). Без флага `always` клиент не увидит тело ошибки, а получит непрозрачную ошибку CORS в консоли.
2. **Кэшируйте Preflight (`Access-Control-Max-Age`):** Задавайте значение от `86400` (24 часа) до `604800` (7 дней). Это снижает число HTTP-запросов к серверу почти в два раза для активных пользователей веб-приложения.
3. **Не используйте проверку Origin регулярными выражениями без привязки границ:** В блоке `map` регулярные выражения обязательно должны содержать маркеры начала `^` и конца `$` строки (например, `"~^https://.*\.example\.com$"`). Шаблон без якорей `"~example.com"` уязвим к обходу через домен атакующего `example.com.attacker.com`.
4. **Контролируйте дублирование заголовков:** При миграциях приложений постепенно переносите ответственность за CORS на периметр Nginx, отключая middleware CORS в коде бэкенда (Node.js/Django/Go) во избежание конфликтов.

---

## Дополнительная информация

### Связанные темы в базе знаний
- **[Основы сопоставления и семантика location](../Core/Location/basics.md)** — алгоритмы сопоставления URI, приоритеты модификаторов и нормализация.
- **[Лучшие практики организации location](../Core/Location/best_practices.md)** — плоская иерархия блоков, наследование директив списочного типа.
- **[Руководство по безопасности Nginx](./nginx_security_guide.md)** — базовая защита периметра, заголовки HSTS, CSP, защита WebSocket от CSWSH (Origin validation) и маскирование данных.
- **[Редиректы и proxy_redirect](../../Proxy/nginx_proxy_redirects.md)** — управление редиректами и исключение утечек внутренних адресов.

### Официальная документация и RFC
- [MDN Web Docs: Cross-Origin Resource Sharing (CORS)](https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS)
- [W3C Recommendation: Cross-Origin Resource Sharing](https://www.w3.org/TR/cors/)
- [RFC 9110: HTTP Semantics (Field Definitions)](https://www.rfc-editor.org/rfc/rfc9110.html)
