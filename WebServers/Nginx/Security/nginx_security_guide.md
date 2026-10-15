# Безопасность веб-сервера Nginx и Angie

## Определения

**DoS (Denial of Service) / DDoS** — атаки, направленные на нарушение доступности сервиса через исчерпание ресурсов сервера (CPU, RAM, пропускная способность сети). В контексте Nginx/Angie рассматриваются на уровне L7 (HTTP-флуд, Slowloris, HPACK Bomb, Rapid Reset) и ниже.

**WAF (Web Application Firewall)** — защитный экран прикладного уровня, анализирующий HTTP-трафик на наличие признаков атак (SQLi, XSS, RCE) с использованием наборов правил (например, OWASP CRS). В экосистеме Nginx/Angie реализуется через ModSecurity v3 или Coraza.

**Базовая аутентификация (`auth_basic`)** — метод проверки учетных данных в HTTP, передаваемых в заголовке `Authorization` в Base64. Требует обязательного TLS для защиты паролей от перехвата.

**Цифровая подпись ссылок (`secure_link`)** — механизм защиты контента от хотлинкинга и несанкционированного доступа через проверку хеш-суммы и времени жизни ссылки.

**HTTP-заголовки безопасности (Security Headers)** — специальные инструкции для браузера, предотвращающие атаки на стороне клиента (XSS, Clickjacking, MIME-sniffing, Spectre/MDS через COOP/COEP).

**Content Security Policy (CSP)** — механизм контроля доверенных источников контента. В 2026 году стандарт использует `strict-dynamic` с nonces для защиты от обхода через доверенные CDN и исключает `unsafe-inline`.

**HSTS (HTTP Strict Transport Security)** — заголовок, заставляющий браузер использовать исключительно HTTPS, предотвращая атаки SSL Stripping. В 2026 году базовый период — 2 года (`max-age=63072000`) с `includeSubDomains` и `preload`.

**Изоляция ресурсов (COOP/COEP/CORP)** — заголовки, предотвращающие утечки данных через побочные каналы (Spectre, MDS) в браузерной среде. В 2026 году являются обязательными для production-сайтов, обрабатывающих пользовательский контент.

**MTTR (Mean Time To Repair)** — среднее время восстановления сервиса после инцидента. TLS-инциденты (сертификат, шифры, ECH), сбои WAF или обход rate limiting напрямую влияют на MTTR, поэтому наличие runbook'ов и автоматизированных проверок является обязательным.

**Runbook** — пошаговая инструкция (playbook) для оператора/SRE по реагированию на типичный инцидент. Для Nginx/Angie включает команды диагностики, критерии escalation и шаги отката.

## Основные концепции

### Многоуровневая архитектура защиты (Defense in Depth)

Защита Nginx/Angie строится на эшелонированной модели. Каждый уровень закрывает определенный класс угроз, и прорыв на одном уровне не должен приводить к полной компрометации сервиса.

```text
Edge (L3/L4: scrubbing, nftables, BGP Flowspec)
    ↓
Load Balancer (L4: SYN cookies, XDP, conntrack)
    ↓
Nginx/Angie (L7: rate limiting, connection limiting, WAF, security headers)
    ↓
Backend (приложение: auth, input validation, parameterized queries)
```

В отличие от отдельного WAF или файрвола, Nginx/Angie обеспечивает защиту на стыке L4 и L7, что делает его критическим элементом perimeter defense. Ключевое преимущество — обработка каждого запроса в рамках одного процесса с минимальной латентностью.

### Особенности Angie по сравнению с Nginx OSS

Angie расширяет базовые механизмы защиты Nginx двумя критически важными возможностями:

1. **Cluster Zone Sync (`sync`)**: Параметр `sync` в директивах `limit_req_zone` и `limit_conn_zone` позволяет синхронизировать состояние лимитов между несколькими узлами балансировщика в реальном времени. Это обеспечивает «честное» ограничение трафика во всем кластере, предотвращая обход порогов при распределенных атаках, где каждый отдельный бот не превышает локальный порог.

2. **Расширенный API для observability**: Встроенные эндпоинты статуса (`/api/v1/http/limit_reqs/`, `/api/v1/http/limit_conns/`) позволяют автоматизированным системам мониторинга получать детальную статистику по лимитам в реальном времени без парсинга логов.

### Векторы атак, специфичные для Nginx/Angie

| Вектор | Механизм | Влияние | Критичность |
| :--- | :--- | :--- | :--- |
| **Slowloris** | Медленная отправка заголовков, удержание соединений | Исчерпание `worker_connections` | Высокая |
| **Slow POST (R.U.D.Y.)** | Медленная отправка тела через `Expect: 100-continue` | Исчерпание воркеров | Высокая |
| **HPACK Bomb (HTTP/2)** | Переполнение сжатой таблицы заголовков | OOM, падение процесса | Высокая |
| **Rapid Reset (HTTP/2/3)** | Каскадное открытие/сброс потоков | Высокая CPU нагрузка | Средняя |
| **QUIC Flood (HTTP/3)** | UDP-флуд с поддельными Source IP | Исчерпание bandwidth/CPU | Средняя |
| **Request Smuggling** | Несоответствие `Content-Length` и `Transfer-Encoding` | Обход WAF, кэш-отравление | Высокая |
| **Hotlinking** | Несанкционированное использование статических файлов | Исчерпание bandwidth | Средняя |

### Жизненный цикл защищенного соединения

```text
Клиент → TCP handshake → TLS handshake (TLS 1.3, ECH, OCSP Stapling) →
HTTP request → Nginx/Angie:
  1. IP-фильтрация (allow/deny)
  2. Rate limiting (limit_req)
  3. Connection limiting (limit_conn)
  4. WAF (ModSecurity/Coraza) — L7 инспекция
  5. auth_request / auth_basic / auth_jwt
  6. Backend response → Security Headers (CSP, HSTS, COOP/COEP)
```

## Практические сценарии

### 1. Защита от Slowloris и Header Flooding на уровне Nginx

Ограничение количества заголовков и размеров буферов для борьбы с медленными соединениями и HPACK Bomb.

```nginx
http {
    # Лимит количества заголовков (Nginx 1.25.1+ / Angie 1.4+)
    # Защищает от атак на парсер заголовков (HPACK Bomb в HTTP/2)
    max_headers 100;

    # Тайм-ауты для борьбы с медленными соединениями (Slowloris, Slow POST)
    client_body_timeout 10s;
    client_header_timeout 10s;
    keepalive_timeout 65s;
    send_timeout 10s;

    # Буферы: защищают RAM от переполнения большими запросами
    client_body_buffer_size 16k;
    client_header_buffer_size 1k;
    large_client_header_buffers 4 8k;

    # Лимиты с корректным статус-кодом (429 Too Many Requests)
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    limit_req_status 429;
    limit_conn_zone $binary_remote_addr zone=perip:10m;
    limit_conn_status 429;
}
```

### 2. Защита внутренних ресурсов (директива `internal`)

Предотвращение прямого доступа к служебным эндпоинтам, доступным только для внутренних перенаправлений (`X-Accel-Redirect`, `error_page`, `auth_request`).

```nginx
location /internal-api/ {
    # Эндпоинт доступен только через внутренние перенаправления
    internal;
    proxy_pass http://backend;
}

# Пример использования через X-Accel-Redirect
location /download/ {
    proxy_pass http://backend;
    proxy_set_header X-Accel-Redirect /protected-files$uri;
}
```

### 3. Блокировка конфиденциальных данных

Защита файлов систем контроля версий и окружения. Полная методология с системным подходом описана в соответствующем SSoT.

```nginx
# Блокировка доступа ко всем скрытым файлам (начинающимся с точки),
# кроме .well-known (для ACME, ECH)
location ~ /\.(?!well-known) {
    deny all;
    return 404;
}

# Блокировка специфических файлов
location ~ /(config\.php|wp-config\.php|\.env|composer\.json|\.git) {
    deny all;
    return 404;
}

    # Блокировка диапазона IP
    deny 192.168.1.0/24;
    deny 10.0.0.1;
    allow all;
}

### 4. Запрет на выполнение скриптов в каталогах загрузки

Критично для предотвращения атак типа Web Shell. Многокластерный контекст и тонкости настройки описаны в соответствующем SSoT.

```nginx
location /static/uploads/ {
    # Запрет на выполнение PHP
    location ~ \.php$ {
        deny all;
        return 403;
    }
    # Запрет на выполнение других скриптовых языков
    location ~ \.(pl|py|sh|cgi|exe|js|jar)$ {
        return 403;
    }
    # Принудительная отдача как статики (без обработки)
    try_files $uri =404;
}
```

### 5. Ограничение скорости отдачи (Bandwidth Limiting)

Защита от исчерпания полосы пропускания при загрузке тяжелого контента.

```nginx
location /downloads/ {
    # Первые 10 МБ отдаем без ограничений
    limit_rate_after 10m;
    # Затем ограничиваем скорость до 500 КБ/с
    limit_rate 500k;
}
```

### 6. Проверка подписи ссылок (secure_link)

Защита от несанкционированного скачивания файлов и хотлинкинга.

```nginx
location /protected/ {
    secure_link $arg_md5,$arg_expires;
    secure_link_md5 "$secure_link_expires$uri secret_key";

    if ($secure_link = "") { return 403; }
    if ($secure_link = "0") { return 410; }
    # Если проверка прошла, $secure_link будет "1"
}
```

### 7. Сокрытие версии и заголовков бэкенда

```nginx
http {
    # Скрытие версии Nginx/Angie в ответах
    server_tokens off;
    
    # Лимит размера тела запроса (защита от загрузки гигантских файлов)
    client_max_body_size 10M;
}

# В контексте проксирования
location / {
    # Скрытие информации о стеке бэкенда
    proxy_hide_header X-Powered-By;
    proxy_hide_header Server;
    proxy_pass http://backend;
}
```

### 8. Системные права доступа (Hardening)

```bash
# Исполняемые файлы и конфиги — только для root
sudo chown -R root:root /etc/nginx
sudo chmod -R 755 /etc/nginx
sudo chmod 640 /etc/nginx/nginx.conf

# Директории сайта — владелец myuser, группа www-data
sudo chown -R myuser:www-data /var/www/mysite
sudo find /var/www/mysite -type d -exec chmod 755 {} \;
sudo find /var/www/mysite -type f -exec chmod 644 {} \;
```

### 9. Гео-блокировка и условный доступ (geo, geoip2)

Отсечение трафика из нецелевых регионов и гибкие правила на основе IP — типичный слой защиты перед WAF. Nginx-часть строится на `map`/`geo` (без внешних баз) и на `ngx_http_geoip2_module` (MaxMind GeoLite2) для геолокации.

```nginx
# Условная блокировка по стране через geoip2 + map
geoip2 /etc/nginx/geo/Country.mmdb {
    $geoip2_country_code default=RU country iso_code;
}

map $geoip2_country_code $is_blocked {
    default    0;
    RU         1;
    CN         1;
    KP         1;
}

server {
    if ($is_blocked) { return 403; }   # не рекомендуется: используйте limit_req/deny для масштаба
}
```

Более масштабируемый путь — блокировка на уровне `deny`/allow по `geo`-директиве и внешнем firewall (nftables), т.к. `geo` статичен и не требует базы:

```nginx
geo $blocked_zone {
    include /etc/nginx/geo/*.conf;   # Nginx 1.29.8+ поддерживает wildcards в include
    default 0;
}
server {
    if ($blocked_zone) { return 403; }
}
```

Полные примеры `geoip2`/`map` и настройка баз — в [Контроле доступа в Angie](../../Angie/angie_access_control.md) (директивы идентичны для Nginx OSS) и [Защите от DoS в Angie](../../Angie/High_Load/dos_protection.md). Поддержка `include`-wildcards в `geo` — в [Установке и базовой настройке Nginx](../Core/nginx_setup.md).

**Важно:** гео-блокировка по странам может ложно отсекать трафик через CDN/прокси (Source IP = IP CDN, а не клиента). Корректно обрабатывайте реальные IP через `real_ip`/Proxy Protocol (см. [Практическую конфигурацию балансировки](../Proxy/Load_Balancing/practical_configuration.md)), иначе блокировка по геолокации будет работать против легитимных пользователей.

### 10. Rate Limiting: алгоритм limit_req в деталях

`limit_req` реализует **leaky bucket**: запросы сверх `rate` ставятся в очередь размера `burst` и обрабатываются с паузой `1/rate` (режим `delay`, по умолчанию). Флаг `nodelay` убирает задержку — запросы из очереди обрабатываются немедленно. Превышение очереди возвращает `limit_req_status` (по умолчанию **503**, для API принято менять на **429**).

```nginx
http {
    # Зона: 1MB ≈ 16000 ключей $binary_remote_addr (32 байта ключ + служебные данные).
    # Для rate в r/s на одного клиента делите объём зоны на ожидаемый RPS (правило 1/4).
    limit_req_zone $binary_remote_addr zone=api:20m rate=10r/s;

    # Логирование факта срабатывания лимита (для алертов и анализа)
    log_format access '$remote_addr - $status "$request" '
                      'limit_req_status=$limit_req_status rt=$request_time';
}

server {
    location /api/ {
        limit_req zone=api burst=20 nodelay;      # очередь 20, без паузы
        limit_req_status 429;
        limit_req_log_level notice;
        proxy_pass http://backend;

        # Кастомное JSON-тело для 429 (опционально)
        error_page 429 = @429_json;
        location @429_json {
            default_type application/json;
            return 429 '{"error":"rate_limited"}';
        }
    }

    # Режим dry run (Nginx 1.23.4+ / Angie): только логировать, не блокировать.
    # Используйте для нагрузочного теста перед включением лимита в бой.
    location /api/experimental/ {
        limit_req zone=api burst=100 nodelay;
        limit_req_dry_run on;                     # $limit_req_status = DRY_RUN
        proxy_pass http://backend;

        # Кастомное JSON-тело для 429 (опционально)
        error_page 429 = @429_json;
        location @429_json {
            default_type application/json;
            return 429 '{"error":"rate_limited"}';
        }
    }
}
```

Ключевое:
- **Размер зоны:** 1MB зоны ≈ 16k записей `$binary_remote_addr`. При высоком RPS выбирайте ключ точнее — `map`+`$server_name`+`$binary_remote_addr` или `limit_req_zone ... key=$binary_remote_addr zone=...` для раздельного лимита на маршрут.
- **Несколько директив `limit_req`** в одном `location` суммируются как AND-условия (срабатывает самый строгий).
- **`$limit_req_status`** (Nginx 1.17.1+): `PASSED`, `DELAYED`, `REJECTED`, `DELAYED_DRY_RUN`, `REJECTED_DRY_RUN` — пишите его в `log_format` для метрик отказа.
- Для точного лимита по одновременным соединениям используйте `limit_conn` (не путать с частотой).

Глубокий разбор (token bucket, кластерная синхронизация `sync`, Slowloris, HTTP/2 flood) — в [Защите от DoS в Angie](../../Angie/High_Load/dos_protection.md) и [Rate limiting и circuit breakers в HTTP](../../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md).

### 11. CORS (Cross-Origin Resource Sharing)

CORS — политика браузера, разрешающая кросс-доменные запросы. Nginx как reverse proxy должен отдавать корректные `Access-Control-*` заголовки и обрабатывать **preflight** (`OPTIONS`) запросы, но не ослаблять их.

```nginx
# В контексте http: разрешённые Origin'ы без жёсткого списка в каждом server
map $http_origin $cors_origin {
    default                      "";
    "~^https://app\.example\.com$"  $http_origin;
    "~^https://(www\.)?admin\.example\.com$" $http_origin;
}

server {
    listen 443 ssl;
    server_name api.example.com;

    location /api/ {
        if ($request_method = 'OPTIONS') {
            add_header 'Access-Control-Allow-Origin' $cors_origin;
            add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS';
            add_header 'Access-Control-Allow-Headers' 'Authorization, Content-Type, X-Request-ID';
            add_header 'Access-Control-Max-Age' '1728000';
            add_header 'Content-Type' 'text/plain charset=UTF-8';
            return 204;
        }

        add_header 'Access-Control-Allow-Origin' $cors_origin always;
        add_header 'Access-Control-Allow-Credentials' 'true' always;
        proxy_pass http://api_backend;
    }
}
```

- При пустом `$cors_origin` (Origin не в списке) заголовки не выдаются — браузер блокирует запрос.
- **Не используйте `*`** вместе с `Allow-Credentials: true` — браузеры обязаны отклонить такой ответ.
- Кэшируемые ответы с CORS требуют `add_header Vary "Origin"`: заголовок должен отличаться в зависимости от Origin, иначе CDN/кэш отдаст неверный вариант.
- Полный разбор CORS (restricted origins, preflight, credentials) — в [CORS в Angie](../../Angie/angie-cors.md), готовый конфиг — [Сценарий 2 в «Безопасности HTTP»](../../../Networking/Protocols/HTTP/http_security_hardening.md).

### 12. Контрабанда запросов (Request Smuggling)

Атака основана на расхождении парсинга `Content-Length` и `Transfer-Encoding` между фронтендом (Nginx) и бэкендом/кэшем (см. типы CL.TE/TE.CL в таблице выше). Защита — единообразная обработка тела запроса на Nginx:

```nginx
http {
    # Явный HTTP/1.1 к апстриму и очистка опасных заголовков
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Transfer-Encoding "";

    # Буферизация тела — Nginx передаёт бэкенду единый Content-Length
    proxy_request_buffering on;
    client_body_buffer_size 128k;
}
```

- `proxy_request_buffering on` (по умолчанию) читает тело целиком и передаёт его с корректным `Content-Length`, исключая двойной парсинг на стороне апстрима.
- **Проверка:** `curl -v -H "Transfer-Encoding: chunked" -H "Content-Length: 4" -d "SMUGGLED" https://api.example.com/` — Nginx должен обработать запрос с `Content-Length`, а бэкенд не получить оба значения.
- Полный сценарий предотвращения с валидацией — [Сценарий 7 в «Безопасности HTTP»](../../../Networking/Protocols/HTTP/http_security_hardening.md).

### 13. Аутентификация клиентов: выбор метода

| Метод | Механизм | Применение |
| :--- | :--- | :--- |
| **`auth_basic`** | htpasswd + `Authorization: Basic` | Внутренние инструменты, защита dev-окружений; только поверх TLS |
| **`auth_request`** | Внутренний subrequest к auth-эндпоинту (200/401/403) | SSO, OIDC, кастомные валидации со стороны приложения |
| **JWT (`auth_jwt`)** | Валидация подписи/срока токена на Nginx (OpenSSL-based) | API-шлюзы без обращения к бэкенду; сотрудничает с `auth_request` |
| **OIDC / LDAP / PAM** | Внешняя проверка через модули (обычно в Angie) | Корпоративный SSO, интеграция с Identity Provider |

Базовые примеры `auth_basic`/`auth_request`/JWT и гео-доступ — в [Контроле доступа в Angie](../../Angie/angie_access_control.md). Протокольный уровень (Basic, Digest, Bearer, TLS client certs) — в [Аутентификации HTTP](../../../Networking/Protocols/HTTP/http_authentication.md); OAuth2/OIDC и JWT — в [oauth2_overview.md](../../../Security/Concepts/oauth2_overview.md) и [jwt_overview.md](../../../Security/Concepts/jwt_overview.md). Для mTLS запросов к серверу — [mTLS в Nginx](./TLS_SSL/nginx_mtls_configuration.md).

## Операции и команды

### Валидация конфигурации перед применением

```bash
# Проверка синтаксиса (обязательно перед reload)
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Graceful reload без разрыва соединений
systemctl reload nginx

# Принудительная перезагрузка (при проблемах с graceful)
systemctl restart nginx

# Проверка статуса
systemctl status nginx
# → Active: active (running) since Tue 2025-09-22 12:00:00 UTC; 2h ago
```

### Проверка активных слушающих портов

```bash
# TCP-порт 443
ss -tlnpn | grep :443
# → LISTEN 0 128 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=1234,fd=6))

# UDP-порт 443 (для HTTP/3)
ss -ulpn | grep :443
# → UNCONN 0 0 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=1234,fd=7))
```

### Проверка безопасности заголовков

```bash
# Проверка заголовков через curl
curl -I https://example.com 2>/dev/null | grep -iE "strict-transport|x-frame|x-content|permissions|cross-origin|content-security|server|server-tokens"
# → Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
# → X-Frame-Options: SAMEORIGIN
# → X-Content-Type-Options: nosniff
# → Permissions-Policy: geolocation=(), microphone=()
# → Cross-Origin-Opener-Policy: same-origin
# → Cross-Origin-Resource-Policy: same-origin
# → Content-Security-Policy: default-src 'self'; ...
# → Server: nginx  # должно отсутствовать при server_tokens off;
```

### Мониторинг безопасности в реальном времени

```bash
# Логи Nginx с фильтром по security events
journalctl -u nginx --since "1 hour ago" | grep -iE "denied|forbidden|limit_req|limit_conn|modsecurity|waf|blocked"

# Проверка количества заблокированных IP (если используется fail2ban)
fail2ban-client status nginx-http-auth
# → Status for the jail: nginx-http-auth
# → |- Filter
# → |  |- Currently failed: 3
# → |  |- Total failed:     142
# → |  `- Journal matches:  _SYSTEMD_UNIT=nginx.service

# Статистика WAF (ModSecurity)
tail -100 /var/log/modsecurity/audit.log | jq -r '.messages[].transaction.request.headers.host' | sort | uniq -c | sort -rn | head -10
```

### Управление службой Nginx

```bash
# Проверка синтаксиса (обязательно перед reload)
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Graceful reload без разрыва соединений
systemctl reload nginx

# Принудительная перезагрузка (при проблемах с graceful)
systemctl restart nginx

# Проверка статуса
systemctl status nginx
# → Active: active (running) since Tue 2025-09-22 12:00:00 UTC; 2h ago
```

## Устранение неполадок

### Общая методология

При поступлении alert'а или жалобы на доступность сервиса следуйте алгоритму:

1. **Локализация уровня**: Определите, является ли проблема связанной с сетью (L3/L4), приложением (L7), WAF или конфигурацией Nginx/Angie.
2. **Сбор контекста**: `nginx -T` (активная конфигурация), `journalctl -u nginx --since "10 minutes ago"`, `tail -100 /var/log/nginx/error.log`.
3. **Валидация гипотезы**: `nginx -t`, `curl -I`, `ss -tlnpn`.
4. **Устранение**: Внесите исправление, проверьте синтаксис, примените `reload`.
5. **Верификация**: Повторите проверку, убедитесь, что alert'ы сняты.

### Типичные ошибки и решения

#### Глобальный уровень (`http`)

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `no shared cipher` | В `ssl_ciphers` нет пересечения с клиентом | См. [Диагностика TLS/SSL](./TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md) |
| `shared zone "SSL" too small` | Переполнен `ssl_session_cache` | Увеличить размер зоны в `ssl_session_cache shared:SSL:50m;` |
| `ssl_stapling: no data` | Отсутствует AIA или недоступен OCSP-responder | См. [Диагностика TLS/SSL](./TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md) |
| `limit_req zone ... not found` | Зона не определена в `http` блоке | Добавить `limit_req_zone` в `http`, выполнить `nginx -t` и `reload` |
| `limit_conn_zone ... too small` | Зона переполнена | Увеличить размер зоны: `limit_conn_zone $binary_remote_addr zone=perip:20m;` |
| `too many open files` | Достигнут лимит дескрипторов файлов | Увеличить `worker_rlimit_nofile` и `ulimit -n` в systemd-юните |
| `worker_connections are not enough` | Исчерпан пул воркеров | Увеличить `worker_connections` в `events` блоке |

#### Уровень `server`

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `certificate verify failed` | Неполная цепочка или просроченный сертификат | См. [Диагностика TLS/SSL](./TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md) |
| `400 Bad Request (No required SSL certificate was sent)` | mTLS-конфигурация требует клиентский сертификат | См. [Конфигурация mTLS](./TLS_SSL/nginx_mtls_configuration.md) |
| `403 Forbidden` | IP не в allow-списке или `deny all` | Проверить `allow`/`deny` в `location` или `server` блоке |
| `404 Not Found` для скрытых файлов | Сработало правило блокировки `location ~ /\.` | Проверить regex в блоке, убедиться в корректности `deny` |
| `413 Request Entity Too Large` | Превышен `client_max_body_size` | Увеличить `client_max_body_size` в соответствующем `server`/`location` |

#### mTLS

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `400 Bad Request (No required SSL certificate was sent)` | Клиент не предоставил сертификат | См. [Конфигурация mTLS](./TLS_SSL/nginx_mtls_configuration.md) |
| `Handshake failure (Unknown CA)` | Издатель клиентского сертификата отсутствует в `ssl_client_certificate` | Добавить CA в `ssl_client_certificate`, проверить `ssl_verify_depth` |
| `CRL is not valid yet` | Некорректная дата в CRL | Проверить `ssl_crl` и синхронизацию времени (NTP) |

### Диагностика после изменений

```bash
# 1. Проверка синтаксиса
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Применение конфигурации
systemctl reload nginx

# 3. Логи
journalctl -u nginx --since "1 minute ago"

# 4. Проверка заголовков
curl -I https://example.com 2>/dev/null | grep -iE "strict-transport|x-frame|x-content|permissions|cross-origin|content-security|server"
```

## Рекомендации и лучшие практики

### Чеклист SRE для Nginx/Angie безопасности

- [ ] **DoS-защита**: `limit_req_zone`, `limit_conn_zone`, `client_header_timeout`, `client_body_timeout`, `max_headers` настроены на всех уровнях.
- [ ] **Security Headers**: HSTS, CSP, COOP/COEP, Permissions-Policy присутствуют в production с `always`.
- [ ] **WAF**: ModSecurity v3 или Coraza включен в режиме DetectionOnly на новых конфигурациях, затем переключен в `On`.
- [ ] **Сокрытие версии**: `server_tokens off;` в `http` блоке.
- [ ] **Скрытие заголовков бэкенда**: `proxy_hide_header Server`, `proxy_hide_header X-Powered-By`.
- [ ] **Защита чувствительных файлов**: Регулярные выражения для `.git`, `.env`, `.ssh`, `wp-config.php` и т.д.
- [ ] **Скрипты в uploads**: Запрет выполнения PHP/Perl/Python в каталогах загрузки.
- [ ] **Мониторинг**: Alert'ы на `429`, `403`, `500`, рост `limit_req`/`limit_conn` отказов.
- [ ] **Мониторинг fail2ban**: Проверка статуса джail'ов и количества заблокированных IP.
- [ ] **Runbook**: Наличие пошаговой инструкции для инцидентов WAF, DoS, обхода rate limiting.

### Процедуры операционной поддержки

**Валидация после изменений:**
```bash
# 1. Проверка синтаксиса
nginx -t

# 2. Применение
systemctl reload nginx

# 3. Логи
journalctl -u nginx --since "1 minute ago"

# 4. Проверка заголовков
curl -I https://example.com 2>/dev/null | grep -iE "strict-transport|x-frame|x-content|server"
```

**Откат изменений:**
```bash
# Если reload вызвал проблемы
git checkout /etc/nginx/conf.d/example.com.conf  # или восстановите из бэкапа
systemctl reload nginx
```

**Бэкап конфигурации:**
```bash
# Бэкап конфигурации
tar czf /backup/nginx-vhosts-$(date +%F).tar.gz /etc/nginx/conf.d/

# Бэкап сертификатов (если не используются Let's Encrypt)
tar czf /backup/nginx-ssl-$(date +%F).tar.gz /etc/nginx/ssl/
```

### Совместимость и baseline (2026)

| Компонент | Версия / Статус 2026 | Рекомендация |
| :--- | :--- | :--- |
| **Nginx OSS** | 1.27+ LTS | Использовать модуль `ngx_http_modsecurity_module` или внешний reverse proxy для WAF. |
| **Angie** | 1.5+ | Предпочтительна для кластерных сценариев с `sync` в лимитах. |
| **ModSecurity** | 3.0.12+ | Использовать с OWASP CRS v4. |
| **Coraza** | 1.x (Go + Wasm) | Современная альтернатива для высоконагруженных сред. |
| **fail2ban** | 0.11.x (nftables backend) | Использовать nftables вместо ipset для O(1) блокировок. |
| **TLS** | TLS 1.3 mandatory, 1.2 fallback | TLS 1.0/1.1 полностью выведены (RFC 8996). |

### Производительность и overhead

| Механизм | Влияние на latency | Рекомендация |
| :--- | :--- | :--- |
| `limit_req` / `limit_conn` | <1ms | Без ограничений, базовый hardening. |
| `server_tokens off` | 0ms | Обязательно на production. |
| Security Headers | 0ms | Обязательно на production. |
| `auth_basic` | <5ms | Для внутренних ресурсов; для production используйте `auth_request` с OIDC. |
| ModSecurity v3 | 5–20ms | На RPS > 10k рассмотреть Coraza или внешний WAF. |
| Coraza | 2–10ms | Высокая производительность на Go. |
| `secure_link` | <1ms | Для защиты статики от хотлинкинга. |

## Дополнительная информация

### См. также

*   **[Защита от DoS/DDoS в Angie/Nginx](../../Angie/High_Load/dos_protection.md)** — Rate Limiting, Connection Limiting, кластерная синхронизация и QUIC-защита.
*   **[Безопасность HTTP в продакшене](../../../Networking/Protocols/HTTP/http_security_hardening.md)** — Security Headers, CORS, request smuggling, ModSecurity/NAXSI.
*   **[WAF для Nginx/Angie (ModSecurity, Coraza)](../../../Security/ApplicationSecurity/waf.md)** — установка `ngx_http_modsecurity_module`, OWASP CRS, режимы DetectionOnly/On.
*   **[fail2ban для защиты Nginx](../../../Linux/Security/Tools/fail2ban.md)** — джail'ы `nginx-limit-req`, `nginx-http-auth`, бан по Rate Limit/Auth-логам.
*   **[Контроль доступа в Angie](../../Angie/angie_access_control.md)** — IP-фильтрация, `auth_basic`, `auth_request`, JWT, LDAP, PAM, гео-блокировка.
*   **[CORS в Angie](../../Angie/angie-cors.md)** — `map $http_origin`, preflight, restricted origins, credentials.
*   **[Rate limiting и circuit breakers](../../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md)** — token/leaky bucket, burst, backpressure.
*   **[Аутентификация HTTP](../../../Networking/Protocols/HTTP/http_authentication.md)** — схемы аутентификации на протокольном уровне.
