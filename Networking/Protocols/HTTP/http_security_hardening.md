# Безопасность HTTP в продакшене

## Определения

**WAF (Web Application Firewall)** — средство защиты веб-приложений, анализирующее HTTP-трафик и блокирующее вредоносные запросы (SQL injection, XSS, RCE). Реализуется как модуль веб-сервера (ModSecurity, NAXSI) или отдельный сервис (Cloudflare WAF).

**Request Smuggling (Контрабанда запросов)** — класс атак, при котором злоумышленник отправляет сконструированный HTTP-запрос, который интерпретируется по-разному фронтенд-прокси и бэкендом. Возникает из-за несоответствий в разборе заголовков `Content-Length` и `Transfer-Encoding`.

**DDoS (Distributed Denial of Service)** — атака, при которой множество источников overwhelm сервис запросами, делая его недоступным для легитимных пользователей.

**Slowloris** — вид DDoS-атаки, при которой злоумышленник открывает множество HTTP-соединений и медленно отправляет заголовки, удерживая соединения открытыми до исчерпания пула воркеров.

**Security Headers** — HTTP-заголовки ответа, усиливающие безопасность браузера: `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`.

**CORS (Cross-Origin Resource Sharing)** — механизм, позволяющий браузеру отправлять запросы между разными origins. Контролируется заголовками `Access-Control-Allow-*`.

## Основные концепции

### Контрабанда запросов (Request Smuggling)

| Тип атаки | Механизм | Условие |
| :--- | :--- | :--- |
| **CL.TE** | Frontend использует `Content-Length`, backend — `Transfer-Encoding: chunked` | Frontend игнорирует chunked или не валидирует CL |
| **TE.CL** | Frontend использует `Transfer-Encoding: chunked`, backend — `Content-Length` | Backend игнорирует chunked |
| **TE.TE** | Оба используют chunked, но с разной валидацией заголовков | Несоответствие в обработке заголовков |

**Защита от request smuggling:**
```nginx
# Nginx/Angie: явное указание HTTP-версии и отключение Transfer-Encoding
proxy_http_version 1.1;
proxy_set_header Connection "";

# Или принудительное использование Content-Length
proxy_request_buffering on;
```

### DDoS mitigation на уровне прокси

| Метод | Механизм | Инструмент |
| :--- | :--- | :--- |
| **Rate limiting** | Ограничение запросов в секунду | Nginx `limit_req_zone` |
| **Connection limiting** | Ограничение соединений с одного IP | Nginx `limit_conn_zone` |
| **Geo-blocking** | Блокировка по географическому расположению | Nginx `geo` + `deny`, HAProxy `peers` |
| **IP reputation** | Блокировка известных ботнет-IP | Fail2ban, CrowdSec |
| **SYN cookies** | Защита от SYN flood | `net.ipv4.tcp_syncookies = 1` |
| **Slowloris protection** | Ограничение времени отправки заголовков | `client_header_timeout 10s` |
| **Request size limit** | Ограничение размера запроса | `client_max_body_size` |
| **Burstable rate limiting** | Обработка всплесков с задержкой | `limit_req burst=20 delay=10` |

### Slowloris и Slow Read

| Атака | Механизм | Защита |
| :--- | :--- | :--- |
| **Slowloris** | Медленная отправка заголовков, удержание соединения | `client_header_timeout 10s; limit_conn` |
| **Slow Read** | Медленное чтение ответа сервером (атака на бэкенд) | `proxy_read_timeout 10s;` |
| **Slow POST** | Медленная отправка тела POST-запроса | `client_body_timeout 10s;` |
| **R.U.D.Y.** (R-U-Dead-Yet) | Медленная отправка тела POST через `Expect: 100-continue` | Ограничить `client_body_timeout` |

### Заголовки безопасности (Security Headers)

| Заголовок | Значение | Назначение |
| :--- | :--- | :--- |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` | Принудительный HTTPS |
| `X-Content-Type-Options` | `nosniff` | Блокировка MIME-sniffing |
| `X-Frame-Options` | `DENY` или `SAMEORIGIN` | Защита от clickjacking |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'` | Защита от XSS, injection |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Контроль Referer заголовка |
| `Permissions-Policy` | `geolocation=(), microphone=()` | Ограничение доступа к API браузера |
| `Cross-Origin-Opener-Policy` | `same-origin` | Изоляция origins (COOP) |
| `Cross-Origin-Embedder-Policy` | `require-corp` | Изоляция embedded content (COEP) |

### ModSecurity и NAXSI (WAF)

| Характеристика | ModSecurity | NAXSI |
| :--- | :--- | :--- |
| **Язык правил** | SecRules (собственный DSL) | Nginx-специфичные директивы |
| **Наборы правил** | OWASP Core Rule Set (CRS), Comodo | Собственные правила |
| **Режимы** | DetectionOnly, On, Off | Naxsi:learning, Naxsi:off |
| **Производительность** | Средняя (регулярные выражения) | Высокая (whitelist-based) |
| **Интеграция** | Nginx, Apache, HAProxy, Envoy | Только Nginx |
| **False Positive Rate** | Средний (требует тонкой настройки) | Низкий (whitelist) |

## Практические сценарии

### Сценарий 1: Полная security-hardening конфигурация Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
    ssl_prefer_server_ciphers on;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;

    # Скрытие версии Nginx
    server_tokens off;

    # Ограничение методов
    limit_except GET HEAD POST OPTIONS {
        deny all;
    }

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

    # Slowloris protection
    client_header_timeout 10s;
    client_body_timeout   60s;
    keepalive_timeout     65s;
    keepalive_requests    1000;

    location / {
        limit_req zone=api burst=20 nodelay;
        proxy_pass http://api_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Валидация:**
- `curl -I https://api.example.com/` — все security headers присутствуют.
- `curl -s https://api.example.com/ | grep "Server:"` — `Server: nginx` (без версии).
- `curl -X DELETE https://api.example.com/` — `403 Forbidden`.
- `ab -n 100 -c 25 https://api.example.com/` — после burst `429 Too Many Requests`.

### Сценарий 2: CORS конфигурация

```nginx
server {
    listen 80;
    server_name api.example.com;

    # Preflight
    location / {
        if ($request_method = 'OPTIONS') {
            add_header 'Access-Control-Allow-Origin' 'https://app.example.com';
            add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS';
            add_header 'Access-Control-Allow-Headers' 'Authorization, Content-Type, X-Request-ID';
            add_header 'Access-Control-Max-Age' '1728000';
            add_header 'Content-Type' 'text/plain charset=UTF-8';
            return 204;
        }

        add_header 'Access-Control-Allow-Origin' 'https://app.example.com' always;
        add_header 'Access-Control-Allow-Credentials' 'true' always;

        proxy_pass http://api_backend;
    }
}
```

**Валидация:**
- `curl -H "Origin: https://app.example.com" -X OPTIONS https://api.example.com/ -i` — `204 No Content`, все CORS-заголовки.
- `curl -H "Origin: https://evil.example.com" -X OPTIONS https://api.example.com/ -i` — `Access-Control-Allow-Origin` отсутствует.

### Сценарий 3: Geo-blocking в Nginx

```nginx
http {
    geo $allowed_country {
        default          1;
        127.0.0.1        1;
        10.0.0.0/8       1;
        RU               0;
        CN               0;
        KP               0;
    }

    map $allowed_country $blocked {
        1   "";
        0   1;
    }

    server {
        listen 80;
        server_name api.example.com;

        if ($blocked) {
            return 403;
        }

        location / {
            proxy_pass http://api_backend;
        }
    }
}
```

**Валидация:**
- `curl -H "X-Forwarded-For: 1.2.3.4" https://api.example.com/` — `403 Forbidden` (если IP из заблокированной страны).
- `curl -H "X-Forwarded-For: 8.8.8.8" https://api.example.com/` — `200 OK`.

### Сценарий 4: ModSecurity с OWASP CRS

Базовая установка ModSecurity + CRS на Nginx (и версии libmodsecurity3 >= 3.0.17, CVE-2026-30923) детально описана в **[WAF: установка и конфигурация ModSecurity](../../../Security/ApplicationSecurity/waf.md)**. Здесь — лаконичный набор директив для HTTP-харднинга:

- в блоке `http`: `modsecurity on;` + `modsecurity_rules_file /etc/nginx/modsecurity.conf;`;
- `SecRuleEngine On`, `SecRequestBodyAccess On`, `Include .../crs-setup.conf` и `Include .../crs/rules/*.conf`;
- `SecRuleRemoveById 920350` для шумных правил (пример).

**Валидация:** `curl "https://api.example.com/?q=<script>alert(1)</script>"` → `403` (XSS); `curl "https://api.example.com/?id=1 OR 1=1"` → `403` (SQLi); `tail -f /var/log/modsec_audit.log` — логи блокировок.

### Сценарий 5: Fail2ban для защиты от brute-force

```ini
# /etc/fail2ban/jail.local
[nginx-http-auth]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/access.log
maxretry = 5
bantime  = 3600
findtime = 600

[nginx-badbots]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/access.log
maxretry = 2
bantime  = 86400
findtime = 600
```

```bash
# Применение
fail2ban-client reload
fail2ban-client status nginx-http-auth
```

**Валидация:**
- 5 неудачных попыток аутентификации с одного IP за 10 минут.
- `fail2ban-client status` — IP в списке забаненных.
- `iptables -L -n` — правило DROP для IP.

### Сценарий 6: Защита от Slowloris

```nginx
server {
    listen 80;
    server_name api.example.com;

    # Slowloris protection
    client_header_timeout 10s;
    client_body_timeout   60s;
    keepalive_timeout     65s;
    keepalive_requests    1000;
    reset_timedout_connection on;

    # Ограничение размера заголовков
    client_header_buffer_size 1k;
    large_client_header_buffers 4 8k;

    # Ограничение соединений
    limit_conn_zone $binary_remote_addr zone=addr:10m;
    limit_conn addr 10;

    location / {
        proxy_pass http://api_backend;
    }
}
```

**Валидация:**
- slowhttptest — атака на заголовки:
  ```bash
  slowhttptest -c 1000 -H -i 10 -r 200 -t GET -u http://api.example.com/ -x 24 -p 3
  ```
- `ss -tn state established '( dport = :80 )' | wc -l` — соединения не растут бесконечно (ограничены `limit_conn` и `client_header_timeout`).
- В логах Nginx: `client timed out (110: Connection timed out)`.

### Сценарий 7: Request Smuggling Prevention

```nginx
http {
    # Явное указание HTTP/1.1 и очистка заголовков
    proxy_http_version 1.1;
    proxy_set_header Connection "";

    # Отключение Transfer-Encoding при необходимости
    proxy_set_header Transfer-Encoding "";

    # Буферизация запроса (Content-Length)
    proxy_request_buffering on;
    client_body_buffer_size 128k;

    server {
        listen 80;
        server_name api.example.com;

        location / {
            proxy_pass http://api_backend;
        }
    }
}
```

**Валидация:**
- `curl -v -H "Transfer-Encoding: chunked" -H "Content-Length: 4" -d "SMUGGLED" http://api.example.com/` — Nginx игнорирует `Transfer-Encoding` (если `proxy_request_buffering on`) и использует `Content-Length`.
- В логах Nginx: запрос обработан корректно, без двойного парсинга.

## Типичные проблемы и диагностика

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Request Smuggling** | Два запроса в одном соединении, неверный routing | `tcpdump -i any -n -A port 80` — двойной CRLF | `proxy_http_version 1.1; proxy_set_header Connection "";` |
| **XSS через CSP bypass** | `script-src 'self'` обходит через `unsafe-inline` | Browser DevTools — blocked scripts | Убрать `unsafe-inline`, использовать nonce/hash |
| **Clickjacking** | Сайт в `<iframe>` на другом домене | `X-Frame-Options: DENY` отсутствует | Добавить `X-Frame-Options DENY` |
| **MIME sniffing** | Браузер интерпретирует `text/plain` как `text/html` | `X-Content-Type-Options: nosniff` отсутствует | Добавить заголовок |
| **CORS misconfiguration** | Любой origin может делать запросы | `Access-Control-Allow-Origin: *` с credentials | Использовать whitelist origin |
| **Slowloris** | Всё соединения заняты, сервер не отвечает | `ss -s` — много соединений в `ESTAB` | `client_header_timeout 10s; limit_conn` |
| **Brute-force** | Всплеск 401/403 с одного IP | `grep "401" /var/log/nginx/access.log | awk '{print $1}' | sort \| uniq -c \| sort -rn` | Fail2ban или CrowdSec |
| **SQL Injection** | `?id=1 OR 1=1` возвращает данные | WAF logs: `941` (SQL injection) | ModSecurity CRS, параметризованные запросы |
| **Path traversal** | `../../../etc/passwd` возвращает файл | WAF logs: `930` (path traversal) | Валидация пути на приложении, `alias` вместо `root` |
| **Open redirect** | `?next=https://evil.com` перенаправляет | `curl -I "https://api.example.com/redirect?next=https://evil.com"` | Валидация `next` параметра (whitelist) |

## Лучшие практики

1. **ModSecurity с OWASP CRS:** `SecRuleEngine On`, `Include /etc/modsecurity/crs/rules/*.conf`. Оставляйте в DetectionOnly на первый месяц.
2. **`server_tokens off;`:** Скрывайте версию Nginx. `curl -I` не должен показывать `Server: nginx/1.25.1`.
3. **`proxy_http_version 1.1; proxy_set_header Connection "";`:** Защита от request smuggling. Явное указание HTTP/1.1 и очистка Connection.
4. **`client_header_timeout 10s; client_body_timeout 60s;`:** Защита от slowloris и slow POST.
5. **`limit_conn` и `limit_req`:** Ограничение соединений и запросов по IP. Защита от DDoS на уровне прокси.
6. **Geo-blocking дляKnown bad actors:** Блокируйте страны, из которых не ожидается трафик.
7. **Fail2ban / CrowdSec:** Автоматическая блокировка IP при 5+ неудачных попытках за 10 минут.
8. **CORS с whitelist:** Никогда не используйте `Access-Control-Allow-Origin: *` с credentials. Whitelist конкретные origins.
9. **CSP без `unsafe-inline`:** Используйте nonce или hash для inline-скриптов. `unsafe-inline` делает CSP бесполезной против XSS.
10. **HSTS с `preload`:** Подключите домен к hstspreload.org. Это гарантирует HTTPS даже при первом посещении.
11. **WAF в DetectionOnly на прод:** Включайте WAF на продакшен в DetectionOnly на 2–4 недели, затем анализируйте false positives и переключайте в `On`.
12. **Regular security headers audit:** Запускайте securityheaders.com или Mozilla Observatory scan при каждом релизе.

## Граничные случаи и ограничения

1. **ModSecurity и performance:** ModSecurity добавляет 5–20ms latency на каждый запрос (регулярные выражения). На высоконагруженных сервисах (RPS > 10k) используйте NAXSI или внешний WAF.
2. **WAF false positives:** OWASP CRS может блокировать легитимные запросы (особенно API с нестандартными форматами). Настраивайте исключения (`SecRuleRemoveById`).
3. **Request smuggling и HTTP/2:** В HTTP/2 request smuggling невозможен (бинарный фрейминг, нет CL/TE). Но HTTP/1.1 downgrade атаки возможны. Принудительно отклоняйте HTTP/1.0.
4. **Geo-blocking и VPN:** Пользователи с VPN получают IP другой страны. Используйте дополнительную проверку (Accept-Language, Timezone) или белые списки для VPN-диапазонов.
5. **CORS и credentials:** `Access-Control-Allow-Credentials: true` запрещает `Access-Control-Allow-Origin: *`. Указывайте конкретный origin.
6. **CSP и inline styles:** `style-src 'self'` блокирует inline styles (`<div style="...">`). Используйте `nonce-...` или перемещайте стили в CSS-файлы.
7. **Slowloris и CDN:** CDN (Cloudflare, Fastly) защищает от slowloris автоматически. Если вы за CDN, настройку slowloris можно ослабить.
8. **Fail2ban и CDN:** За CDN все клиенты имеют IP edge-сервера. Fail2ban заблокирует весь CDN. Используйте Fail2ban на CDN или анализируйте `X-Forwarded-For` за доверенным прокси.
9. **Referrer-Policy и analytics:** `strict-origin-when-cross-origin` отправляет Referer только для same-origin и HTTPS→HTTPS. Это может сломать analytics. Настройте под нужды.
10. **Permissions-Policy и legacy browsers:** Старые браузеры игнорируют Permissions-Policy. Это progressive enhancement, не breaking change.

## Дополнительная информация

### CrowdSec — open-source альтернатива Fail2ban

```bash
# Установка
curl -s https://install.crowdsec.net | sudo bash
cscli hub install crowdsecurity/nginx
cscli parsers install crowdsecurity/nginx-logs
cscli scenarios install crowdsecurity/http-bad-user-agent

# Добавление Nginx source
cscli sources add nginx /var/log/nginx/access.log
systemctl restart crowdsec
```

### Сравнение заголовков безопасности

| Заголовок | Безопасный | Уязвимый |
| :--- | :--- | :--- |
| `X-Frame-Options` | `DENY` | Отсутствует |
| `X-Content-Type-Options` | `nosniff` | Отсутствует |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` | Отсутствует или `max-age=0` |
| `Content-Security-Policy` | `default-src 'self'` | `unsafe-inline`, `unsafe-eval` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | `unsafe-url` |
| `Permissions-Policy` | Ограничение геолокации, камеры, микрофона | Отсутствует |

### Правила WAF: покрытие OWASP Top 10

| OWASP Top 10 (2021) | CRS Rule ID | Пример |
| :--- | :--- | :--- |
| A01:2021 — Broken Access Control | 941 | IDOR, path traversal |
| A02:2021 — Cryptographic Failures | 942 | Weak TLS, sensitive data in URL |
| A03:2021 — Injection | 941, 942, 943 | SQL injection, XSS, command injection |
| A04:2021 — Insecure Design | — | Требует архитектурного анализа |
| A05:2021 — Security Misconfiguration | 100 | Default credentials, verbose errors |
| A06:2021 — Vulnerable Components | 100 | Устаревшие библиотеки (вне CRS) |
| A07:2021 — Auth Failures | 941 | Brute-force, weak passwords |
| A08:2021 — Software Integrity | — | Unsigned updates, CI/CD compromise |
| A09:2021 — Logging Failures | 100 | Отсутствие логов атак |
| A10:2021 — SSRF | 941 | Server-Side Request Forgery |

## Смотрите также

- **[HTTP-серверы и прокси](./http_servers_proxies.md)** — `limit_except`, `server_tokens off`, security headers.
- **[Аутентификация HTTP](./http_authentication.md)** — brute-force protection, мTLS.
- **[Health Checks и Readiness Probes](./http_health_checks_readiness.md)** — probes в Kubernetes.
- **[Rate Limiting и устойчивость](./http_rate_limiting_circuit_breakers.md)** — защита от перегрузки и DDoS.
- **[Логирование и инструменты диагностики](./http_logging_troubleshooting_tools.md)** — fail2ban, анализ логов.
- **[TLS-шифрование и сертификаты](./http_tls_hardening.md)** — mTLS, cipher suites, OCSP.
