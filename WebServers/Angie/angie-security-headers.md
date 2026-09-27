# Заголовки безопасности в Angie

## Определения

**Заголовки безопасности (Security Headers)** — HTTP-заголовки ответа, которые инструктируют браузер, как обрабатывать и защищать ресурс: запрет встраивания во фреймы, отключение MIME-sniffing, политики `Content-Security-Policy`, защита от clickjacking и др.

**`add_header`** — директива Angie/Nginx, добавляющая заголовок к HTTP-ответу. Поддерживает параметр `always`, чтобы отправлять заголовок и для ответов с ошибками (4xx/5xx).

**Основной набор (2026):**
*   `Strict-Transport-Security` (HSTS) — принудительный HTTPS.
*   `Content-Security-Policy` (CSP) — источник загрузки контента (скриптов, стилей, картинок).
*   `X-Content-Type-Options: nosniff` — запрет MIME-sniffing.
*   `X-Frame-Options: DENY|SAMEORIGIN` — запрет встраивания в фреймы (устаревает в пользу CSP `frame-ancestors`).
*   `Referrer-Policy`, `Permissions-Policy` — ограничение передачи Referrer и браузерных API.

## Теоретический блок

### Поведение add_header при наследовании

Классическая "ловушка": если в дочернем контексте (`location`) объявлена хотя бы одна директива `add_header`, то **все** `add_header` родительского уровня (http/server) перестают наследоваться и применяются только заголовки, объявленные в самом `location`.

```nginx
http {
    add_header X-Content-Type-Options nosniff always;
    server {
        location / {
            # НАСЛЕДУЕТ X-Content-Type-Options
        }
        location /api/ {
            add_header X-Debug 1;          # X-Content-Type-Options потеряется!
        }
    }
}
```

### `always` — отправка на ошибках

По умолчанию `add_header` не отправляет заголовок на ответах с кодом 204, 304 или 4xx/5xx (кроме "успешных" 200–203, 206). Параметр `always` заставляет отправлять заголовок всегда — критично для CSP/HSTS, которые должны действовать и на ошибках. Это касается и заголовков, заданных через `add_header` от проксируемого бэкенда — их следует дублировать директивой бэкенда, а не полагаться на `proxy_hide_header`.

## Практический блок

### Сценарий 1: Базовый набор заголовков на уровне http

```nginx
http {
    # HSTS применяется только через HTTPS (браузеры игнорируют его на HTTP)
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
}
```

### Сценарий 2: CSP в отдельном location без потери остальных

Поскольку `add_header` в `location` отменяет наследование http-уровня, дублируйте нужные заголовки в критичных location:

```nginx
server {
    location /app/ {
        # Локальный CSP + обязательный повтор x-frame
        add_header Content-Security-Policy "default-src 'self'" always;
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options nosniff always;
    }
}
```

### Сценарий 3: Проверка отправленных заголовков

```bash
# Просмотр заголовков живого сайта
curl -sI https://example.com/ | grep -Ei "strict-transport|x-content|x-frame|content-security|referrer-policy"

# Также проверить ответ с ошибкой (проверка always)
curl -sI https://example.com/nonexistent -o /dev/null -w "%{http_code}\n"   # 404
curl -sI https://example.com/nonexistent | grep -i x-content-type-options  # должен быть даже на 404

# Что реально получит браузер — целиком
curl -sI https://example.com/
```

Нюанс: для ответа с `Content-Type: text/html` с ошибками убедитесь, что статусы 4xx/5xx не "съедают" заголовок — это типичная причина, когда HSTS пропадает на 404.

## Дополнительная информация

*   HSTS лучше задавать и через `add_header`, и/или через конфигурацию TLS-сервера, чтобы исключить момент, когда сайт доступен по HTTP. Подробнее — в [Настройке TLS в Angie](./angie_tls_setup.md).
*   Внимание к `always` на 3xx: заголовки будут отправлены и на редиректах, что для HSTS правильно; для CSP — не всегда желательно. Тестируйте маршруты редиректов.
*   Не полностью перекрывайте потребности бэкенда: заголовки, которые должен генерировать backend (например, `Cache-Control`), обычно не заменяют `add_header`, а настраиваются в приложении.

## См. также

*   **[Укрепление безопасности HTTP (Test Hardening)](../../Networking/Protocols/HTTP/http_security_hardening.md)** — полный набор заголовков и сценарии для всего HTTP-стека.
*   **[Заголовки безопасности фронтенда (CI/CD)](../../CI-CD/Frontend_CI_CD/frontend_security_headers.md)** — практика выставления заголовков на этапе сборки.
*   **[Настройка TLS в Angie](./angie_tls_setup.md)** — HSTS вместе с TLS, HTTP/2/3, ALPN.