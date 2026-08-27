# Reverse proxy и оптимизация доставки для фронтенда

## Определения

- **Reverse Proxy** — сервер перед приложением (nginx/Angie), терминирующий TLS, раздающий статику и проксирующий динамику (SSR) к бэкенду/процессу.
- **Upstream** — группа бэкенд-серверов, между которыми прокси балансирует трафик.
- **Keepalive** — переиспользование соединений к upstream (снижает latency на handshake).
- **Precompression (прекомпрессия)** — заранее сгенерированные `.gz`/`.br` файлы, отдаваемые без сжатия на лету.
- **HTTP/2, HTTP/3 (QUIC)** — протоколы доставки; HTTP/2 мультиплексирует запросы, HTTP/3 поверх UDP ускоряет при потерях пакетов.
- **CORS (Cross-Origin Resource Sharing)** — механизм разрешения кросс-доменных запросов (шрифты, ассеты, API).

---

## Основные концепции

### Зачем прокси перед фронтендом
Даже чистая статика выигрывает от nginx: терминация TLS, отдача `immutable` заголовков, precompression, CORS, security-заголовки. Для SSR прокси обязателен (скрывает процесс, даёт keepalive и балансировку).

### HTTP/2 и доменное шардинг
Мультиплексирование HTTP/2 делает **domain sharding (раскидывание ассетов по N доменам) анти-паттерном** — это добавляет лишние TCP/TLS-соединения. Все ассеты должны отдаваться с одного хоста (или через CDN) по HTTP/2. Исключение — изоляция по origin для cookie/sandbox.

### Precompression vs сжатие на лету
Сжимать Brotli/Gzip на каждый запрос дорого. На этапе сборки генерируем `.br`/`.gz` рядом с ассетами, а nginx отдаёт готовый файл по `Accept-Encoding`. Обязателен `Vary: Accept-Encoding`, иначе клиент без Brotli получит brotli-данные из кэша другого клиента.

### CORS для ассетов
Шрифты и некоторые API требуют явного `Access-Control-Allow-Origin`. Частая ошибка — закрытые CORS ломают загрузку web-шрифтов с CDN.

### Early Hints (103, ранние подсказки)
Сервер может заранее (до ответа) попросить браузер подгрузить критические CSS/JS (`Link: </app.abc.css>; rel=preload`). Ускоряет LCP.

---

## Практические сценарии

### Сценарий 1: nginx upstream + keepalive к SSR
```nginx
upstream ssr {
    least_conn;
    server 127.0.0.1:3000 max_fails=3 fail_timeout=10s;
    server 127.0.0.1:3001 max_fails=3 fail_timeout=10s;
    keepalive 32;
}
server {
    location / {
        proxy_pass http://ssr;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### Сценарий 2: Precompression (Brotli/Gzip)
```nginx
# На этапе сборки: brotli -q 11 dist/assets/*.js
location /assets/ {
    gzip_static on;
    brotli_static on;
    add_header Content-Encoding gzip;     # только если отдали .gz
    add_header Vary Accept-Encoding;
    add_header Cache-Control "public, max-age=31536000, immutable";
    try_files $uri.$http_accept_encoding $uri =404;
}
```

### Сценарий 3: HTTP/2, HTTP/3 и Early Hints
```nginx
listen 443 ssl;
http2 on;
# HTTP/3 (QUIC) — при поддержке
listen 443 quic reuseport;
add_header Alt-Svc 'h3=":443"';
# Early Hints
location = / {
    add_header Link "</assets/app.abc.css>; rel=preload; as=style";
    # 103 Early Hints выдаётся автоматически при proxy_pass с поддержкой
}
```

### Сценарий 4: CORS для шрифтов/ассетов и API
```nginx
location /fonts/ {
    add_header Access-Control-Allow-Origin "https://app.example.com" always;
    add_header Vary Origin always;
}
location /api/ {
    add_header Access-Control-Allow-Origin "https://app.example.com" always;
    add_header Access-Control-Allow-Methods "GET,POST,OPTIONS" always;
    add_header Access-Control-Allow-Headers "Content-Type,Authorization" always;
    if ($request_method = OPTIONS) { return 204; }
}
```

### Сценарий 5: WebSocket upgrade (для SSR с live-режимом)
```nginx
location /ws/ {
    proxy_pass http://ssr;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

---

## Дополнительная информация

### Лучшие практики
1. Отдавайте статику напрямую из nginx, не проксируя в Node/SSR-процесс.
2. Включайте `keepalive` к upstream и `proxy_http_version 1.1` с пустым `Connection`.
3. Генерируйте `.br`/`.gz` на сборке и отдавайте `static` — не сжимайте на лету.
4. Не используйте domain sharding при HTTP/2+.
5. Всегда `Vary: Accept-Encoding` на сжатых ответах.

### Типичные проблемы
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Браузер получает gzip вместо brotli | Нет `Vary` / precompression | `brotli_static on` + `Vary: Accept-Encoding` |
| Шрифты не грузятся | CORS блокирует | `Access-Control-Allow-Origin` на `/fonts/` |
| Высокий latency на SSR | Нет keepalive | `keepalive 32` + `proxy_http_version 1.1` |
| Медленный LCP | Нет preload | Early Hints `Link: rel=preload` критических ассетов |

### См. также
- **[Выдача статических файлов](../../WebServers/Nginx/Core/Location/serving_files.md)** — базовая конфигурация location.
- **[Клиентское кэширование в Nginx](../../WebServers/Nginx/Performance/Caching/client_caching.md)** — `Cache-Control` под фронтенд.
- **[Деплой SSR/SSG/ISR](./ssr_ssg_deployment.md)** — проксирование к процессу.
- **[Security-заголовки и CSP](./frontend_security_headers.md)** — где размещать заголовки.
