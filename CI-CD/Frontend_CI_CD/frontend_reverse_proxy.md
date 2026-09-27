# Reverse proxy и оптимизация доставки для фронтенда

## Определения

- **Reverse Proxy** — сервер перед приложением (nginx/Angie), терминирующий TLS, раздающий статику и проксирующий динамику (SSR) к бэкенду/процессу.
- **Upstream** — группа бэкенд-серверов, между которыми прокси балансирует трафик.
- **Keepalive** — переиспользование соединений к upstream (снижает latency на handshake).
- **Precompression (прекомпрессия)** — заранее сгенерированные `.gz`/`.br` файлы, отдаваемые без сжатия на лету.
- **HTTP/2, HTTP/3 (QUIC)** — протоколы доставки; HTTP/2 мультиплексирует запросы, HTTP/3 поверх UDP ускоряет при потерях пакетов.
- **CORS (Cross-Origin Resource Sharing)** — механизм разрешения кросс-доменных запросов (шрифты, ассеты, API).
- **Early Hints (103)** — ранний ответ сервера с заголовком `Link`, позволяющий браузеру заранее подгрузить критические ассеты до ответа 200.
- **Sticky Sessions** — привязка сессии к конкретному бэкенду по cookie или параметру; для фронтенда требуется только для stateful SSR с экспериментальными функциями.

---

## Основные концепции

### Зачем прокси перед фронтендом

Даже чистая статика выигрывает от nginx: терминация TLS, отдача `immutable` заголовков, precompression, CORS, security-заголовки. Для SSR прокси обязателен (скрывает процесс, даёт keepalive и балансировку).

### Архитектура размещения

Для фронтенда reverse proxy размещается между клиентом и источником контента:

```
[Клиент] -> [CDN/Edge (опционально)] -> [Nginx/Angie reverse proxy] -> [SSR-процесс / Статика]
```

**Принципы:**
- **Изоляция:** SSR-процесс привязывается к `127.0.0.1` или внутреннему VLAN, чтобы он был доступен только через reverse proxy.
- **Разделение ответственности:** Nginx обрабатывает TLS, сжатие, кэширование и CORS; приложение отвечает за рендеринг.
- **Zero-downtime:** Конфигурация Nginx меняется грациозно (`nginx -s reload`), не обрывая соединения.

### HTTP/2 и доменное шардинг

Мультиплексирование HTTP/2 делает **domain sharding (раскидывание ассетов по N доменам) анти-паттерном** — это добавляет лишние TCP/TLS-соединения. Все ассеты должны отдаваться с одного хоста (или через CDN) по HTTP/2. Исключение — изоляция по origin для cookie/sandbox.

### Precompression vs сжатие на лету

Сжимать Brotli/Gzip на каждый запрос дорого. На этапе сборки генерируем `.br`/`.gz` рядом с ассетами, а nginx отдаёт готовый файл по `Accept-Encoding`. Обязателен `Vary: Accept-Encoding`, иначе клиент без Brotli получит brotli-данные из кэша другого клиента.

### CORS для ассетов

Шрифты и некоторые API требуют явного `Access-Control-Allow-Origin`. Частая ошибка — закрытые CORS ломают загрузку web-шрифтов с CDN.

### Early Hints (103, ранние подсказки)

Сервер может заранее (до ответа) попросить браузер подгрузить критические CSS/JS (`Link: </app.abc.css>; rel=preload`). Ускоряет LCP.

### TLS-терминация

Nginx/Angie завершает TLS-соединения, снимая криптографическую нагрузку с бэкенда. Минимальные требования:
- TLS 1.2+ (рекомендуется TLS 1.3)
- Сертификат ECDSA P-256 или RSA 2048+
- `ssl_prefer_server_ciphers off` для приоритета клиентских шифров
- OCSP stapling для ускорения проверки отзыва сертификатов

Глубокие настройки TLS, HSTS и mTLS описаны в **[Security-заголовки и CSP](./frontend_security_headers.md)**.

### Наблюдаемость

Прокси должен предоставлять данные для диагностики:
- **Access log:** формат JSON с `$remote_addr`, `$request_time`, `$upstream_response_time`, `$upstream_cache_status`, `$status`.
- **Upstream health:** мониторинг `$upstream_status` (502/504 часто указывают на проблему с SSR-процессом).
- **Метрики:** `nginx_vts` или `stub_status` для RPS, активных соединений, состояния upstream.
- **Лимиты:** мониторинг `connecting` и `waiting` в stub_status помогает детектировать исчерпание пула.

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

### Сценарий 6: Security hardening для фронтенд-прокси
```nginx
server {
    # Скрываем версию Nginx
    server_tokens off;

    # Ограничения для SSR-эндпоинтов
    location /api/ {
        limit_req zone=frontend burst=20 nodelay;
        client_max_body_size 10m;
        proxy_pass http://ssr;
    }

    # Блокировка небезопасных методов
    if ($request_method !~ ^(GET|HEAD|POST|OPTIONS)$) {
        return 405;
    }
}
```

### Сценарий 7: Graceful reload и zero-downtime
```bash
# Проверка конфигурации перед применением
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Грациозная перезагрузка без потерь соединений
nginx -s reload
# → signal reload started

# При добавлении нового upstream-сервера — плавное добавление веса
sed -i 's/server 127.0.0.1:3002 weight=0;/server 127.0.0.1:3002 weight=1;/' /etc/nginx/conf.d/ssr-upstream.conf
nginx -s reload
```

---

## Проверка корректности

После изменения конфигурации убедитесь, что proxy работает корректно:

1. **Валидация конфигурации:**
   ```bash
   nginx -t
   # → syntax is ok
   ```

2. **Проверка keepalive:**
   ```bash
   ss -tnp | grep nginx | grep ESTAB | wc -l
   # → количество установленных соединений к upstream
   ```

3. **Проверка сжатия:**
   ```bash
   curl -H "Accept-Encoding: br" -I https://example.com/assets/app.js
   # → Content-Encoding: br
   ```

4. **Проверка CORS:**
   ```bash
   curl -H "Origin: https://app.example.com" -I https://cdn.example.com/fonts/font.woff2
   # → Access-Control-Allow-Origin: https://app.example.com
   ```

5. **Проверка Early Hints:**
   ```bash
   curl -I https://example.com/ 2>&1 | grep -i "103\|link:"
   # → 103 Early Hints
   # → Link: </assets/app.abc.css>; rel=preload; as=style
   ```

6. **Проверка безопасности:**
   ```bash
   curl -I https://example.com/ | grep -i "server:"
   # → (пусто) — server_tokens off работает
   ```

---

## Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Браузер получает gzip вместо brotli | Нет `Vary` / precompression | `brotli_static on` + `Vary: Accept-Encoding` |
| Шрифты не грузятся | CORS блокирует | `Access-Control-Allow-Origin` на `/fonts/` |
| Высокий latency на SSR | Нет keepalive | `keepalive 32` + `proxy_http_version 1.1` |
| Медленный LCP | Нет preload | Early Hints `Link: rel=preload` критических ассетов |
| 502 после деплоя | SSR процесс не поднялся | Health check + задержка перед снятием старого; проверка `systemctl status` |
| Процесс не виден снаружи | Bind на `127.0.0.1` без прокси | Nginx проксирует на `127.0.0.1`, процесс не открыт наружу |
| Исчерпание ephemeral-портов | Нет keepalive / `TIME_WAIT` | `keepalive` в upstream + `net.ipv4.ip_local_port_range` |
| Nginx не перезагружается | Ошибка в конфиге | `nginx -t`, проверить синтаксис и права на файлы |

## Лучшие практики

1. Отдавайте статику напрямую из nginx, не проксируя в Node/SSR-процесс.
2. Включайте `keepalive` к upstream и `proxy_http_version 1.1` с пустым `Connection`.
3. Генерируйте `.br`/`.gz` на сборке и отдавайте `static` — не сжимайте на лету.
4. Не используйте domain sharding при HTTP/2+.
5. Всегда `Vary: Accept-Encoding` на сжатых ответах.
6. Скрывайте версию Nginx (`server_tokens off`).
7. Ограничивайте методы и размер тела для публичных эндпоинтов.
8. Используйте `limit_req` для SSR-эндпоинтов, чтобы защититься от burst-трафика.
9. Логируйте `$upstream_response_time` и `$upstream_cache_status` для диагностики.
10. Проверяйте `nginx -t` перед каждым `reload`.

---

## Дополнительная информация

### См. также

- **[Деплой SSR/SSG/ISR](./ssr_ssg_deployment.md)** — lifecycle SSR-процесса, health checks, zero-downtime.
- **[Security-заголовки и CSP](./frontend_security_headers.md)** — HSTS, CSP nonce, X-Frame-Options.
- **[Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)** — атомарный деплой, cache busting, CDN инвалидация.
