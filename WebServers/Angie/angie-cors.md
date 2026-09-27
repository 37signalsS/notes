# CORS в Angie

## Определения

**CORS (Cross-Origin Resource Sharing)** — механизм браузера, разрешающий веб-странице одного происхождения (Origin) запрашивать ресурсы другого происхождения. Браузер отправляет заголовок `Origin` и ожидает от сервера разрешающий `Access-Control-Allow-Origin`.

**Preflight** — предварительный OPTIONS-запрос для "непростых" запросов (не-GET/HEAD/POST, нестандартные заголовки, `application/json` и т.п.). Сервер должен ответить на него `200`/`204` с заголовками `Access-Control-Allow-Methods`, `Access-Control-Allow-Headers` и `Access-Control-Max-Age`.

**Credentialed запросы** — запросы с `credentials: include` (cookies, авторизация). Требуют точный `Access-Control-Allow-Origin` (не `*`) и заголовок `Access-Control-Allow-Credentials: true`.

## Теоретический блок

### Заголовки CORS (ответ сервера)

| Заголовок | Назначение |
|:---|:---|
| `Access-Control-Allow-Origin` | Разрешённое происхождение (`*` или конкретный Origin, эхо Origin из запроса) |
| `Access-Control-Allow-Methods` | Список разрешённых HTTP-методов (`GET, POST, PUT, DELETE, OPTIONS`) |
| `Access-Control-Allow-Headers` | Разрешённые заголовки запроса |
| `Access-Control-Allow-Credentials` | `true`, если разрешены credentialed-запросы |
| `Access-Control-Max-Age` | Время кэширования preflight браузером |
| `Access-Control-Expose-Headers` | Заголовки, доступные JS (не только "safelisted") |

### Правила безопасности

*   **Не используйте просто `*` вместе с `credentials`** — браузер отклонит ответ.
*   **Никогда не эхіруйте произвольный `Origin` в `Access-Control-Allow-Origin` без проверки** — иначе любой сайт сможет делать запросы с авторизацией пользователя.
*   Preflight должен обрабатываться **на уровне вашего веб-сервера** (Angie) быстро и без проксирования к бэкенду, если это возможно.
*   Для API с cookie-авторизацией правильный ответ не равен `*`, он равен списку доверенных доменов через `map`.

## Практический блок

### Сценарий 1: Фиксированный список доверенных Origins (без credentials)

```nginx
http {
    # Разрешённые клиенты фронтенда
    map $http_origin $cors_origin {
        default "";
        "https://app.example.com"     "https://app.example.com";
        "https://admin.example.com"   "https://admin.example.com";
    }

    server {
        listen 80;
        server_name api.example.com;

        location /api/ {
            proxy_pass http://backend;

            if ($cors_origin) {
                add_header Access-Control-Allow-Origin $cors_origin always;
                add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
                add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
                add_header Access-Control-Max-Age 3600 always;
            }

            # Preflight — короткий ответ без проксирования
            if ($request_method = OPTIONS) {
                add_header Access-Control-Allow-Origin $cors_origin always;
                add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
                add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
                add_header Access-Control-Max-Age 3600 always;
                return 204;
            }
        }
    }
}
```

### Сценарий 2: Credentialed-запросы (cookies)

```nginx
map $http_origin $cors_origin_cred {
    default "";
    "https://app.example.com"  "https://app.example.com";
}

server {
    location /api/ {
        if ($cors_origin_cred) {
            add_header Access-Control-Allow-Origin $cors_origin_cred always;
            add_header Access-Control-Allow-Credentials true always;
            # $cors_origin_cred здесь — точный Origin; нельзя использовать *
        }
        proxy_pass http://backend;
    }
}
```

### Верификация

```bash
# Простой запрос с Origin
curl -sI -H "Origin: https://app.example.com" http://localhost/api/ping \
  | grep -i access-control
# → access-control-allow-origin: https://app.example.com

# Preflight
curl -si -X OPTIONS -H "Origin: https://app.example.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: authorization" \
  http://localhost/api/login
# → HTTP/1.1 204 No Content, access-control-allow-methods,...

# Неизвестный Origin → заголовков нет
curl -sI -H "Origin: https://evil.example.com" http://localhost/api/ping | grep -i access-control
# → (пусто)
```

## Дополнительная информация

*   `If`-блоки в nginx-конфигурациях — "evil if", но для `add_header` по условию это рабочий pattern; современная альтернатива — `map` (как здесь) без `if`.
*   Для CDN перед Angie заголовки CORS должны отдаваться и на кэшированных ответах — учитывайте, что `Vary: Origin` полезен для корректного кэширования разными `Access-Control-Allow-Origin`.
*   Расширяемый, более сложный вариант с обработкой ошибок backend на preflight — на [Networking/Protocols/HTTP/http_security_hardening.md](../../Networking/Protocols/HTTP/http_security_hardening.md).

## См. также

*   **[Укрепление безопасности HTTP (Test Hardening)](../../Networking/Protocols/HTTP/http_security_hardening.md)** — полный CORS-сценарий, правила preflight и прогон проверок.
*   **[Заголовки безопасности в Angie](./angie-security-headers.md)** — смежные security-заголовки и поведение `add_header`.
*   **[Настройка TLS в Angie](./angie_tls_setup.md)** — HTTPS-база для продуктовых API с CORS.