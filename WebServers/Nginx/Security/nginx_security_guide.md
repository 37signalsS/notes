# Безопасность веб-сервера Nginx и Angie

**Актуально для:** Nginx 1.26+ (OSS/Plus) / 1.28+ – 1.30.x (Mainline), Angie 1.6+ / 1.12.x, ModSecurity v3 / Coraza

## Определения

**DoS (Denial of Service) / DDoS** — атаки, направленные на нарушение доступности сервиса через исчерпание ресурсов сервера (CPU, оперативная память, пул соединений, дескрипторы файлов). В контексте Nginx/Angie нейтрализуются на уровне L7 (HTTP-флуд, Slowloris, Slow POST, HPACK Bomb, Rapid Reset).

**Rate Limiting** — механизм ограничения частоты запросов за единицу времени на основе алгоритма Leaky Bucket (протекающее ведро), сглаживающий всплески трафика (`burst`, `delay`) и отсекающий избыточные запросы с кодом ответа `429 Too Many Requests`.

**Connection Limiting** — ограничение количества одновременно поддерживаемых соединений с одного адреса или виртуального хоста, защищающее воркеры от исчерпания `worker_connections`.

**WAF (Web Application Firewall)** — межсетевой экран прикладного уровня L7, анализирующий HTTP-трафик на наличие признаков атак (SQLi, XSS, RCE, Path Traversal) с использованием наборов сигнатурных правил (OWASP CRS). В Nginx/Angie развертывается локально через `ngx_http_modsecurity_module` (ModSecurity v3) или модуль Coraza.

**Базовая аутентификация (`auth_basic`)** — метод проверки учетных данных по стандарту HTTP Basic Authentication, передаваемых в заголовке `Authorization` в формате Base64. Требует обязательного использования TLS для предотвращения перехвата паролей в открытом виде.

**Субреквест-аутентификация (`auth_request`)** — механизм делегирования авторизации внешнему сервису через внутренний HTTP-субреквест перед обработкой основного запроса.

**Цифровая подпись ссылок (`secure_link`)** — модуль проверки подлинности URL-адресов через валидацию криптографического хеша (MD5) и временной метки истечения срока жизни ссылки, предотвращающий хотлинкинг и несанкционированное скачивание.

**HTTP-заголовки безопасности (Security Headers)** — директивы в HTTP-ответе веб-сервера, предписывающие браузеру включение механизмов изоляции и защиты (HSTS, CSP, X-Content-Type-Options, Permissions-Policy, COOP, COEP, CORP).

**Content Security Policy (CSP)** — заголовок контроля доверенных источников контента. Исключает несанкционированное выполнение скриптов (`unsafe-inline`) и блокирует утечку данных через XSS.

**HSTS (HTTP Strict Transport Security)** — директива принудительного использования исключительно протокола HTTPS клиентом на заданный период времени (`max-age`), предотвращающая атаки класса SSL Stripping.

**Изоляция браузерного контекста (COOP/COEP/CORP)** — заголовки `Cross-Origin-Opener-Policy`, `Cross-Origin-Embedder-Policy` и `Cross-Origin-Resource-Policy`, изолирующие сайт в отдельном процессе браузера для защиты от атак по побочным каналам (Spectre, Meltdown).

**Request Smuggling (десинхронизация HTTP-запросов)** — класс атак, возникающий из-за расхождений в интерпретации границ запросов (`Content-Length` против `Transfer-Encoding`) между reverse proxy и бэкенд-сервером.

**Fail2ban / Host IPS** — служба локального мониторинга журналов веб-сервера, автоматически транслирующая обнаруженные аномалии (перебор паролей, сканирование уязвимостей, срабатывание rate limit) в правила блокировки пакетного фильтра ядра Linux (`nftables`).

**MTTR (Mean Time To Repair)** — среднее время восстановления штатной работы сервиса после сбоя или атаки. Наличие формализованных runbook'ов позволяет минимизировать простой при блокировках легитимного трафика или атаках на отказ.

**Runbook** — регламентная пошаговая инструкция для системного администратора и SRE по локализации, диагностике и нейтрализации конкретных инцидентов безопасности.

## Основные концепции

### Многоуровневая архитектура защиты (Defense in Depth)

Харденинг веб-сервера не является изолированной мерой, а функционирует как центральное звено эшелонированной защиты инфраструктуры:

```text
Сетевой периметр (L3/L4: nftables, SYN cookies, conntrack, BGP-маршрутизация)
    ↓
Nginx / Angie (L7: Real IP, SSL termination, geo-filtering, timeouts, rate & connection limits)
    ↓
Host-based WAF (ModSecurity v3 / Coraza: OWASP CRS, глубокая инспекция L7 payload)
    ↓
Бэкенд-приложение (Аутентификация, валидация входных данных, параметризованные запросы)
```

Nginx/Angie выполняет функции пограничного шлюза (Reverse Proxy), принимая на себя основной объем сетевого и прикладного мусора. Отсечение атак до передачи запроса бэкенду сохраняет вычислительные ресурсы приложений и баз данных.

### Сравнение возможностей Angie и Nginx OSS в сфере безопасности

| Возможность / Механизм | Nginx Open Source | Angie | Архитектурное преимущество для SRE |
| :--- | :--- | :--- | :--- |
| **Cluster Zone Sync (`sync`)** | Отсутствует (только Nginx Plus) | Поддерживается из коробки | Синхронизация разделяемой памяти `limit_req` и `limit_conn` между несколькими серверами через cluster stream socket. Защищает от распределенных DoS, где отдельные узлы не видят суммарного трафика бота. |
| **Лимит количества заголовков** | Косвенно через `large_client_header_buffers` | Директива `max_headers` (Angie 1.4+) | Прямой запрет запросов с аномальным количеством заголовков (защита от HPACK Bomb). |
| **API метрик лимитов** | Требуются сторонние модули (`vts`) | Встроенный REST API (`/api/v1/http/limit_reqs/`) | Получение счетчиков `passed`, `delayed`, `rejected` в реальном времени для Prometheus без разбора логов. |
| **ACME / Автоматизация сертификатов** | Внешние утилиты (Certbot, acme.sh) | Встроенный модуль `acme` | Автоматическая ротация TLS-сертификатов без внешних cron-скриптов. |

### Анатомия векторов атак на веб-сервер

| Вектор атаки | Механизм воздействия | Последствия для инфраструктуры | Метод нейтрализации в Nginx/Angie |
| :--- | :--- | :--- | :--- |
| **Slowloris** | Медленная побайтовая передача заголовков с удержанием открытых сокетов | Исчерпание пула `worker_connections`, отказ в обслуживании новых клиентов | `client_header_timeout 10s;` `large_client_header_buffers` |
| **Slow POST (R.U.D.Y.)** | Медленная передача тела запроса (1 байт в несколько секунд) через `Content-Length` | Блокировка воркеров Nginx на чтении сокетов | `client_body_timeout 10s;` `client_body_buffer_size` |
| **HPACK Bomb (HTTP/2)** | Отправка сжатых заголовков с циклическими ссылками в динамической таблице | Взрывное потребление памяти, OOM-killer воркера | Ограничение буферов заголовков, `max_headers` в Angie |
| **HTTP/2 Rapid Reset (CVE-2023-44487)** | Мгновенная отправка кадров `RST_STREAM` сразу после открытия потоков | 100% утилизация CPU на обработку управляющих структур | `keepalive_requests`, обновление версий Nginx (1.25.3+), `limit_req` |
| **HTTP Request Smuggling** | Разночтения `Content-Length` и `Transfer-Encoding: chunked` между прокси и бэкендом | Обход авторизации WAF, отравление кэша, подмена сессий | `proxy_request_buffering on;`, `proxy_http_version 1.1;`, очистка `Transfer-Encoding` |
| **Web Shell в каталогах загрузки** | Загрузка файла `.php`/`.py` в общедоступный каталог и прямой вызов через URL | Удаленное исполнение кода (RCE) на сервере | Запрет исполнения скриптов в каталогах загрузки, принудительный `return 403` |
| **Утечка служебных файлов** | Прямые запросы к `.git`, `.env`, `.bak`, `.conf` | Компрометация секретов, паролей к БД, API-ключей | `location ~ /\.(?!well-known)` с `return 404;` |

### Жизненный цикл защищенного запроса в Nginx

```text
1. TCP Handshake → TLS Handshake (TLS 1.3, OCSP Stapling)
   ↓
2. Модуль Real IP (восстановление истинного $remote_addr из PROXY Protocol или X-Forwarded-For)
   ↓
3. Географическая и списочная фильтрация (allow / deny / geoip2 / map whitelist)
   ↓
4. Проверка лимитов соединений (limit_conn_zone)
   ↓
5. Проверка частоты запросов (limit_req_zone: leaky bucket, burst, delay/nodelay)
   ↓
6. Буферизация и тайм-ауты (client_header_timeout, client_body_timeout, client_max_body_size)
   ↓
7. Модуль WAF (инспекция ModSecurity v3 / Coraza: OWASP CRS)
   ↓
8. Проверка аутентификации (auth_basic / auth_request)
   ↓
9. Проксирование на бэкенд / отдача статики (proxy_request_buffering on, скрытие upstream-заголовков)
   ↓
10. Формирование ответа: Security Headers (HSTS, CSP, COOP/COEP с флагом always)
```

### Критическая ловушка наследования директивы `add_header`

В Nginx действует строгое архитектурное правило наследования директив модуля `ngx_http_headers_module`:

> **Важно:** Если в дочернем блоке (например, `location`) определена хотя бы одна директива `add_header`, **все** директивы `add_header` из родительских блоков (`http`, `server`) полностью игнорируются и не применяются к ответу!

Типичная ошибка SRE: задать базовые заголовки HSTS, CSP и X-Frame-Options в блоке `http {}`, а затем объявить `add_header Cache-Control ...` или CORS в `location /api/`. В результате все заголовки безопасности в ответах эндпоинта `/api/` полностью пропадают.

**Архитектурное решение:** выносить эталонный набор заголовков безопасности в отдельный сниппет конфигурации (например, `/etc/nginx/snippets/security_headers.conf`) и подключать его через `include` во все блоки `server` и в каждый `location`, где объявляются локальные заголовки.

Вторая обязательная деталь — параметр `always`. Без параметра `always` заголовки безопасности отправляются клиенту **только** при успешных статус-кодах (200, 201, 204, 206, 301, 302, 303, 304, 307, 308). При ошибках бэкенда или блокировках (400, 401, 403, 404, 429, 500, 502, 503) заголовки будут потеряны, если не указано `always`.

### Алгоритм Rate Limiting: Leaky Bucket, Burst, Delay и Nodelay

Директива `limit_req` работает по модели «протекающего ведра» с фиксированной скоростью утечки (`rate` в `r/s` или `r/m`).

- **Без `burst`:** любой входящий запрос сверх частоты `rate` немедленно отклоняется с кодом `limit_req_status` (по умолчанию 503, в API рекомендуется 429).
- **С параметром `burst=N`:** создается очередь ожидания на `N` слотов. Запросы, превышающие `rate`, помещаются в очередь и обрабатываются с искусственной задержкой `1/rate`, сглаживая пики.
- **С параметрами `burst=N nodelay`:** запросы из очереди `N` обрабатываются немедленно без добавления задержки (без искусственного замедления ответа). Если входящий всплеск превышает размер очереди `burst`, избыток немедленно сбрасывается с кодом 429.
- **С параметрами двухфазного лимитирования `burst=N delay=M`:** запросы до `M` слотов отдаются без задержки (`nodelay`), запросы между `M` и `N` обрабатываются с нарастающей задержкой, а все запросы сверх `N` — блокируются с кодом 429. Это оптимальная стратегия для интерактивных пользовательских интерфейсов.

## Практические сценарии

### Сценарий 1: Защита от Slowloris, Slow POST и DoS по заголовкам

Конфигурация блокирует медленные атаки удержания соединений и переполнения памяти HTTP/2-заголовками на уровне блока `http`.

`/etc/nginx/conf.d/00_dos_timeouts.conf`:

```nginx
http {
    # Лимит времени на чтение заголовков и тела запроса между операциями чтения
    client_header_timeout 10s;
    client_body_timeout   10s;

    # Тайм-аут передачи ответа клиенту и поддержания keepalive
    send_timeout          10s;
    keepalive_timeout     65s 60s;
    keepalive_requests    1000;

    # Защита от исчерпания памяти при парсинге заголовков
    client_header_buffer_size    1k;
    large_client_header_buffers  4 8k;

    # Ограничение размера тела запроса (предотвращает заливку терабайтов мусора)
    client_max_body_size         10m;
    client_body_buffer_size      128k;

    # Для серверов Angie: прямой лимит на количество заголовков в запросе (защита от HPACK Bomb)
    # В стандартном Nginx OSS закомментируйте эту строку (лимит определяется large_client_header_buffers)
    max_headers                  100;

    # Ограничение параллельных потоков HTTP/2 на одно соединение (снижение эффекта Rapid Reset)
    http2_max_concurrent_streams 128;
}
```

Проверка конфигурации и применения:

```bash
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

systemctl reload nginx
```

### Сценарий 2: Комплексный Rate Limiting с белым списком для SRE и мониторинга

Проблема: включение жесткого Rate Limiting блокирует системы синтетического мониторинга (Prometheus Blackbox Exporter), внутренние чекеры балансировщиков и запросы системных инженеров.

Решение: использование модуля `geo` совместно с `map`. Если IP-адрес входит в белый список, ключ зоны рассчитывается как пустая строка `""`. В Nginx запросы с пустым ключом лимитирования не учитываются в зонах и не блокируются.

`/etc/nginx/conf.d/rate_limiting.conf`:

```nginx
# Определение белого списка доверенных IP (офис, мониторинг, локальные подсети)
geo $whitelist_clients {
    default        0;
    127.0.0.1/32   1;
    10.0.0.0/8     1;
    192.168.1.0/24 1;
}

# Если клиент в белом списке — ключ зоны пуст (лимит не применяется)
# Если клиент внешний — ключом становится компактный бинарный IP-адрес
map $whitelist_clients $limit_key_by_ip {
    0       $binary_remote_addr;
    1       "";
}

# 10 МБ зоны памяти вмещают около 160 000 уникальных IPv4-адресов
# cluster sync доступен в Angie PRO; в Nginx OSS параметр sync опускается
limit_req_zone $limit_key_by_ip zone=api_general:10m rate=10r/s;
limit_req_zone $limit_key_by_ip zone=login_strict:10m rate=1r/s;
limit_conn_zone $limit_key_by_ip zone=conn_per_ip:10m;

# Статус-код превышения лимитов (429 вместо устаревшего 503)
limit_req_status 429;
limit_conn_status 429;

# Уровень логирования срабатывания лимитов
limit_req_log_level warn;

server {
    listen 443 ssl;
    server_name api.example.corp;

    # Ограничение числа параллельных соединений с одного не доверенного IP
    limit_conn conn_per_ip 20;

    # Публичный API с двухфазным сглаживанием всплесков
    location /api/ {
        # Первые 10 запросов сверх rate идут без задержки, следующие 10 — с задержкой
        limit_req zone=api_general burst=20 delay=10;

        proxy_pass http://backend_api;
        proxy_set_header Host $host;

        # Обработка ошибки превышения лимита с отдачей структурированного JSON
        error_page 429 = @rate_limited_json;
    }

    # Чувствительный эндпоинт аутентификации (защита от брутфорса)
    location /api/v1/auth/login {
        limit_req zone=login_strict burst=3 nodelay;

        proxy_pass http://backend_api;
        error_page 429 = @rate_limited_json;
    }

    # Именованный location для отдачи информативного JSON при 429
    location @rate_limited_json {
        default_type application/json;
        return 429 '{"error":"too_many_requests","message":"Rate limit exceeded. Please retry later."}';
    }
}
```

### Сценарий 3: Восстановление реального IP-клиента (Real IP)

При установке Nginx за L4/L7-балансировщиком или реверс-прокси все входящие запросы приходят с IP-адреса этого шлюза. Без настройки модуля `ngx_http_realip_module` rate limiting будет применять лимиты к балансировщику и заблокирует сразу всех пользователей сервиса.

`/etc/nginx/conf.d/real_ip.conf`:

```nginx
# Доверенные адреса внутренних балансировщиков
set_real_ip_from 10.100.0.0/24;
set_real_ip_from 192.168.10.15/32;

# Заголовок, содержащий цепочку клиентских IP
real_ip_header   X-Forwarded-For;

# При значении on берется последний недоверенный IP из цепочки X-Forwarded-For
real_ip_recursive on;
```

При использовании PROXY Protocol (например, за HAProxy) директива меняется:

```nginx
server {
    listen 443 ssl proxy_protocol;
    set_real_ip_from 10.100.0.1;
    real_ip_header   proxy_protocol;
}
```

### Сценарий 4: Эталонный набор Security Headers (Production Baseline)

Создаем переиспользуемый файл сниппета заголовков.

`/etc/nginx/snippets/security_headers.conf`:

```nginx
# Принудительный HTTPS на 2 года с поддоменами и включением в список HSTS Preload
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

# Защита от MIME-sniffing (принудительное соблюдение Content-Type браузером)
add_header X-Content-Type-Options "nosniff" always;

# Защита от Clickjacking через iframes (разрешено только в рамках того же origin)
add_header X-Frame-Options "SAMEORIGIN" always;

# Политика передачи Referer (полный URL для Same-Origin, только домен для HTTPS cross-origin)
add_header Referrer-Policy "strict-origin-when-cross-origin" always;

# Отключение доступа браузера к чувствительным API устройства (камера, микрофон, геолокация)
add_header Permissions-Policy "geolocation=(), microphone=(), camera=(), payment=(), usb=()" always;

# Заголовки строгой изоляции процессов браузера (защита от атак Spectre/Meltdown по побочным каналам)
add_header Cross-Origin-Opener-Policy "same-origin" always;
add_header Cross-Origin-Resource-Policy "same-origin" always;

# Базовая политика безопасности контента (Content Security Policy)
# В production настраивается под фронтенд-стек приложения
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'self'; form-action 'self'; base-uri 'self';" always;
```

Подключение сниппета в виртуальном хосте:

```nginx
server {
    listen 443 ssl;
    server_name service.example.corp;

    include /etc/nginx/snippets/security_headers.conf;

    location / {
        proxy_pass http://backend_app;
    }

    # При переопределении заголовков в location сниппет подключается повторно!
    location /static/ {
        alias /var/www/static/;
        add_header Cache-Control "public, max-age=31536000, immutable";
        include /etc/nginx/snippets/security_headers.conf;
    }
}
```

### Сценарий 5: Блокировка конфиденциальных файлов и защита от Path Traversal

Предотвращение утечки исходного кода, резервных копий, переменных окружения и конфигурационных файлов:

`/etc/nginx/conf.d/block_sensitive_files.conf`:

```nginx
# 1. Блокировка доступа ко всем скрытым файлам и каталогам (начинающимся с точки),
# кроме каталога .well-known (критично для прохождения проверок ACME Let's Encrypt / ECH)
location ~ /\.(?!well-known).* {
    deny all;
    access_log off;
    log_not_found off;
    return 404;
}

# 2. Блокировка резервных копий, дампов БД, архивов, системных логов и файлов окружения
location ~* (?i)\.(?:bak|backup|sql|tar|gz|tgz|zip|rar|env|conf|config|orig|old|swp|log|key|cert|pem|ini)$ {
    deny all;
    access_log off;
    log_not_found off;
    return 404;
}

# 3. Блокировка каталогов систем контроля версий и пакетных менеджеров
location ~* /(?:\.git|\.svn|\.hg|node_modules|vendor|composer\.(?:json|lock)|package(?:-lock)?\.json) {
    deny all;
    access_log off;
    log_not_found off;
    return 404;
}

# 4. Защита служебных ресурсов через директиву internal (доступ только изнутри Nginx)
location /internal-files/ {
    internal;
    alias /var/storage/protected/;
}

# ВНИМАНИЕ SRE (Критическая уязвимость Off-by-slash / Alias Path Traversal):
# Если префикс location не завершается слэшем, а alias завершается (или наоборот):
# ДЕФЕКТНАЯ КОНФИГУРАЦИЯ:
# location /static {
#     alias /var/www/static/;
# }
# Запрос GET /static../etc/passwd транслируется ядром Nginx в чтение:
# /var/www/static/../etc/passwd -> /var/www/etc/passwd (обход родительского каталога!)
# ПРАВИЛО: Всегда синхронизируйте замыкающие слэши: location /static/ { alias /var/www/static/; }
# Детальный разбор уязвимости: [Раздача статических файлов и уязвимость off-by-slash](../../Core/Location/serving_files.md).
```

### Сценарий 6: Запрет исполнения скриптов в каталогах загрузки (Anti-Webshell)

Если веб-приложение позволяет пользователям загружать файлы (аватары, документы), злоумышленник может попытаться загрузить скрипт (`shell.php`, `.py`, `.sh`, `.jsp`) и вызвать его исполнение.

`/etc/nginx/conf.d/uploads_hardening.conf`:

```nginx
server {
    listen 443 ssl;
    server_name app.example.corp;
    root /var/www/app/public;

    # Каталог пользовательских загрузок
    location /uploads/ {
        # Принудительное отключение исполнения PHP и любых интерпретаторов
        location ~* \.(php|phtml|php3|php4|php5|php7|php8|phps|pl|py|cgi|sh|bash|exe|bin|jsp|asp|aspx)$ {
            deny all;
            return 403;
        }

        # Отдача только статики; файлы без совпадения возвращают 404
        try_files $uri =404;

        # Защита от MIME Confusion при загрузке вредоносных SVG/HTML
        add_header X-Content-Type-Options "nosniff" always;
        add_header Content-Disposition "attachment" always;
    }
}
```

### Сценарий 7: Ограничение HTTP-методов (`limit_except`)

Большинство веб-интерфейсов требуют только безопасные методы чтения (`GET`, `HEAD`) и отправки форм (`POST`). Разрешение редких или небезопасных методов (`PUT`, `DELETE`, `CONNECT`, `TRACE`) создает вектор атаки на бэкенд.

```nginx
location / {
    # Разрешаем только GET, HEAD, POST. Все остальные методы блокируются с кодом 405
    limit_except GET HEAD POST {
        deny all;
    }

    proxy_pass http://backend_app;
}
```

### Сценарий 8: Сокрытие информации о стеке (Information Disclosure)

Минимизация сведений о версиях серверного ПО затрудняет автоматизированное профилирование злоумышленниками.

`/etc/nginx/conf.d/hide_server_info.conf`:

```nginx
http {
    # 1. Скрытие версии Nginx в заголовке Server и на стандартных страницах ошибок
    # ВНИМАНИЕ: директива server_tokens off скрывает только номер версии,
    # но оставляет заголовок "Server: nginx".
    server_tokens off;

    # 2. Полное удаление или подмена заголовка Server в Nginx Open Source:
    # Требует динамического модуля headers_more (пакет libnginx-mod-http-headers-more-filter):
    # load_module modules/ngx_http_headers_more_filter_module.so;
    # Полное удаление заголовка Server из всех ответов:
    more_clear_headers Server;
    # Либо подмена на нейтральную строку:
    # more_set_headers "Server: Protected-Gateway";

    # В сервере Angie переопределение строки Server доступно из коробки:
    # server_tokens "Web-Perimeter";

    # 3. Защита от подмены заголовков (Namespace Collision в CGI/FastCGI/uWSGI)
    # По умолчанию Nginx сбрасывает заголовки с подчеркиваниями (underscores_in_headers off;).
    # ОПАСНОСТЬ ВКЛЮЧЕНИЯ: в протоколах CGI/WSGI дефисы заменяются на подчеркивания:
    # заголовок "X-Auth-Token" и атакующий "X_Auth_Token" превращаются в одну переменную
    # HTTP_X_AUTH_TOKEN на стороне бэкенда! Никогда не включайте underscores_in_headers on;
    # без крайней необходимости и аудита бэкенда.
    underscores_in_headers off;
}

server {
    listen 443 ssl;
    server_name portal.example.corp;

    location / {
        proxy_pass http://backend_cluster;

        # Удаление заголовков, раскрывающих бэкенд-стек (Express, PHP, Kestrel, Python)
        proxy_hide_header X-Powered-By;
        proxy_hide_header Server;
        proxy_hide_header X-AspNet-Version;
        proxy_hide_header X-Runtime;
    }
}
```

### Сценарий 9: Предотвращение Request Smuggling и защита от SSRF

1. **Десинхронизация HTTP (Request Smuggling):** возникает при расхождении интерпретации границ запросов (`Content-Length` против `Transfer-Encoding`) между Nginx и бэкендами.
2. **SSRF (Server-Side Request Forgery):** возникает при динамическом формировании адреса бэкенда (например, `proxy_pass http://$http_host;` или `proxy_pass http://$arg_target;`), позволяя атакующему сканировать локальные сервисы хоста (Redis, etcd, link-local metadata `169.254.169.254`).

`/etc/nginx/conf.d/request_smuggling_and_ssrf.conf`:

```nginx
# Белый список целевых хостов для защиты от SSRF при динамическом проксировании
map $arg_target $safe_upstream_host {
    default                  "";
    "api.partner-service.ru" "api.partner-service.ru";
    "cdn.trusted-assets.net" "cdn.trusted-assets.net";
}

http {
    # Обязательная буферизация тела запроса: Nginx читает тело целиком,
    # пересчитывает точный Content-Length и отправляет бэкенду нормализованный запрос
    proxy_request_buffering on;

    # Явный протокол HTTP/1.1 к апстриму и разрыв постоянного keepalive в сомнительных окружениях
    proxy_http_version 1.1;
    proxy_set_header Connection "";

    # Принудительное удаление опасного заголовка Transfer-Encoding при проксировании
    proxy_set_header Transfer-Encoding "";

    # Отклонение запросов с некорректными символами в именах заголовков
    ignore_invalid_headers on;
}

server {
    listen 443 ssl;
    server_name gateway.corp.internal;

    # Динамический прокси с защитой от SSRF
    location /outbound-proxy {
        # Блокировка неизвестных или внутренних адресов (127.0.0.1, localhost, 169.254.169.254)
        if ($safe_upstream_host = "") {
            return 403 "Forbidden: Target upstream is not in whitelist\n";
        }

        # Использование безопасного разрешенного хоста
        proxy_pass https://$safe_upstream_host$uri;
        proxy_set_header Host $safe_upstream_host;
    }
}
```

Детальный архитектурный анализ векторов SSRF на веб-серверах: [SSRF: Server-Side Request Forgery для веб-серверов](../../Concepts/ssrf.md).

### Сценарий 10: Защита ссылок от хотлинкинга (`secure_link`)

Модуль `ngx_http_secure_link_module` генерирует хеш ссылки на основе секрета, URI и времени жизни.

```nginx
location /content/downloads/ {
    root /var/storage;

    # Ожидаются аргументы URL вида: /content/downloads/archive.tar.gz?md5=HASH&expires=1798765432
    secure_link $arg_md5,$arg_expires;
    secure_link_md5 "$secure_link_expires$uri $remote_addr HardcodedClusterSecretKey2026";

    # Если подпись не передана или некорректна
    if ($secure_link = "") {
        return 403;
    }

    # Если срок действия ссылки истек
    if ($secure_link = "0") {
        return 410; # Gone
    }

    # Файл отдается только при $secure_link = "1"
}
```

### Сценарий 11: Контроль доступа: `auth_basic` и `auth_request`

#### Вариант А: Ограничение доступа через `auth_basic` (для внутренних утилит SRE)

```nginx
location /monitoring/ {
    auth_basic           "Restricted Access for Operations";
    auth_basic_user_file /etc/nginx/.htpasswd;

    # Белый список сетей, для которых пароль не требуется
    satisfy any;
    allow 192.168.1.0/24;
    deny  all;

    proxy_pass http://internal_monitoring;
}
```

Генерация файла паролей с использованием хэширования `bcrypt` (утилита `htpasswd` из пакета `apache2-utils`):

```bash
htpasswd -B -c /etc/nginx/.htpasswd admin_sre
# → New password: ...
# → Re-type new password: ...
# → Adding password for user admin_sre

chmod 640 /etc/nginx/.htpasswd
chown root:www-data /etc/nginx/.htpasswd
```

#### Вариант Б: Централизованная проверка через `auth_request` с редиректом на SSO и кэшированием

```nginx
# Зона кэширования вердиктов авторизации для исключения задержек (10 МБ RAM)
proxy_cache_path /var/cache/nginx/auth_cache levels=1:2 keys_zone=auth_cache:10m inactive=10m;

server {
    listen 443 ssl;
    server_name portal.example.corp;

    location /private/ {
        # 1. Отправка субреквеста на локальный сервис проверки прав
        auth_request /auth-validator;

        # 2. Передача контекста пользователя из ответа auth-сервиса в приложение
        auth_request_set $user_id $upstream_http_x_user_id;
        auth_request_set $user_role $upstream_http_x_user_role;
        proxy_set_header X-User-Id $user_id;
        proxy_set_header X-User-Role $user_role;

        # 3. Перехват 401 ошибки и перенаправление пользователя на страницу входа SSO/IdP
        error_page 401 = @login_redirect;

        proxy_pass http://backend_app;
    }

    # Именованный location перенаправления на SSO с передачей URL возврата
    location @login_redirect {
        return 302 https://auth.example.corp/login?rd=$scheme://$http_host$request_uri;
    }

    # Внутренний эндпоинт валидатора с кэшированием успешной авторизации
    location = /auth-validator {
        internal;
        proxy_pass http://127.0.0.1:9090/validate;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI $request_uri;
        proxy_set_header X-Original-Method $request_method;

        # Кэширование успешных ответов авторизации на 5 минут по токену/сессионной куке
        proxy_cache auth_cache;
        proxy_cache_key "$http_authorization$cookie_session_id";
        proxy_cache_valid 200 5m;
        proxy_cache_use_stale error timeout updating;
    }
}
```

### Сценарий 12: Интеграция Host-based WAF (ModSecurity v3 и Coraza)

Интеграция WAF-модулей с правилами OWASP Core Rule Set (CRS) v4.

> **Статус WAF в 2026 году:** Компания Trustwave официально объявила **End-of-Life (EOL)** для проекта ModSecurity. Основным развиваемым открытым стандартом WAF является **OWASP Coraza**. На bare-metal Nginx стабильно эксплуатируется `ngx_http_modsecurity_module` (на базе `libmodsecurity3` 3.0.17+), в то время как Coraza внедряется через SPOE-демон в HAProxy (`coraza-spoa`) или Wasm в Envoy.

`/etc/nginx/conf.d/waf.conf`:

```nginx
server {
    listen 443 ssl;
    server_name portal.example.corp;

    # Включение WAF для виртуального хоста
    modsecurity on;
    modsecurity_rules_file /etc/nginx/modsecurity/modsec_main.conf;

    location / {
        proxy_pass http://backend_portal;
    }

    # Исключение правил WAF для статики ради снижения задержки (latency)
    location /static/ {
        modsecurity off;
        alias /var/www/portal/static/;
    }
}
```

Файл конфигурации `/etc/nginx/modsecurity/modsec_main.conf`:

```apache
# На начальном этапе внедрения используйте DetectionOnly
# После тюнинга исключений переведите в On
SecRuleEngine On

# Обработка тела запроса
SecRequestBodyAccess On
SecRequestBodyLimit 13107200
SecRequestBodyNoFilesLimit 131072

# Журналирование инцидентов
SecAuditEngine RelevantOnly
SecAuditLogParts ABIJDEFHZ
SecAuditLogType Serial
SecAuditLog /var/log/modsecurity/audit.log

# Подключение OWASP CRS
Include /etc/nginx/modsecurity/crs/crs-setup.conf
Include /etc/nginx/modsecurity/crs/rules/*.conf

# SRE Тюнинг: отключение ложно сработавшего правила для конкретного пути
# Например, правило 942100 (SQLi detection в специфическом API-пейлоаде)
SecRuleUpdateTargetById 942100 "!ARGS:json_payload"
```

Подробная установка, сборка и сравнительный анализ движков приведены в [WAF для веб-приложений (ModSecurity, NAXSI, Coraza)](../../../Security/ApplicationSecurity/waf.md).

### Сценарий 13: Харденинг прав доступа к файлам и каталогам (Linux DAC)

Разграничение прав на файловую систему предотвращает подмену конфигурации и кражу TLS-ключей в случае компрометации непривилегированного процесса воркера:

```bash
# 1. Каталог конфигурации: владелец root, чтение воркерам
chown -R root:root /etc/nginx
find /etc/nginx -type d -exec chmod 755 {} \;
find /etc/nginx -type f -exec chmod 644 {} \;

# 2. Приватные ключи TLS: чтение доступно ТОЛЬКО мастер-процессу (root)
chmod 700 /etc/nginx/ssl
chmod 600 /etc/nginx/ssl/*.key

# 3. Рабочие каталоги кэша и временных файлов: владелец www-data / nginx
chown -R www-data:www-data /var/cache/nginx /var/log/nginx
chmod 750 /var/cache/nginx /var/log/nginx

# 4. Каталог веб-документов: файлы read-only для веб-сервера
chown -R deployer:www-data /var/www/site
find /var/www/site -type d -exec chmod 755 {} \;
find /var/www/site -type f -exec chmod 644 {} \;
```

Полная изоляция процесса на уровне ядра через systemd-юнит и SELinux/AppArmor документирована в [Харденинге Nginx на уровне системы](./nginx_systemd_selinux_hardening.md).

### Сценарий 14: Защита WebSocket и предотвращение Cross-Site WebSocket Hijacking (CSWSH)

**Проблема безопасности:** Браузеры **не применяют** политику Same-Origin Policy (SOP) к соединениям WebSocket. Злоумышленник может разместить вредоносный скрипт на стороннем сайте, который открывает полнодуплексный веб-сокет к вашему API (`wss://api.example.corp/ws`), и браузер автоматически прикрепит сессионные cookies пользователя.

**Решение:** Обязательная проверка заголовка `$http_origin` при рукопожатии переключения протокола (`Upgrade`) и ограничение числа одновременных сокетов.

`/etc/nginx/conf.d/websocket_secure.conf`:

```nginx
# 1. Белый список разрешенных Origin-доменов для WebSocket
map $http_origin $ws_origin_allowed {
    default                         0;
    "https://portal.example.corp"   1;
    "https://admin.example.corp"    1;
    ""                              0; # Запрет запросов без Origin для веб-сокетов
}

# 2. Корректная обработка заголовка Connection для WebSocket
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

# Ограничение параллельных WebSocket-соединений с одного IP
limit_conn_zone $binary_remote_addr zone=ws_conn_per_ip:10m;

server {
    listen 443 ssl;
    server_name portal.example.corp;

    location /ws/ {
        # Валидация Origin: немедленный сброс чужих сайтов
        if ($ws_origin_allowed = 0) {
            return 403 "Forbidden: Cross-Site WebSocket connection rejected\n";
        }

        # Ограничение числа сокетов (защита от исчерпания worker_connections)
        limit_conn ws_conn_per_ip 10;

        proxy_pass http://backend_websocket_cluster;
        proxy_http_version 1.1;

        # Проброс заголовков апгрейда
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;

        # Таймауты для долгоживущих сокетов
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

### Сценарий 15: Маскирование конфиденциальных данных и PII в журналах (Log Sanitization / GDPR)

**Проблема:** В стандартных журналах `access.log` оседают токены аутентификации (`Authorization: Bearer <secret>`), пароли и API-ключи из query-параметров (`?token=...`, `?password=...`), а также полные IP-адреса пользователей, что нарушает требования регуляторов (GDPR, 152-ФЗ, PCI-DSS).

**Решение:** Использование директив `map` с регулярными выражениями для очистки чувствительных полей перед записью в лог.

`/etc/nginx/conf.d/log_sanitization.conf`:

```nginx
# 1. Маскирование заголовка Authorization (оставляем только тип токена, скрывая тело)
map $http_authorization $sanitized_authorization {
    default                           "[NO_AUTH]";
    "~*^Bearer\s+(.{4}).*$"          "Bearer $1****[REDACTED]";
    "~*^Basic\s+.*$"                  "Basic [REDACTED]";
}

# 2. Очистка query-параметров URI от паролей, токенов и секретов
map $request_uri $sanitized_request_uri {
    # Маскирование значений параметров token, password, secret, key, api_key
    "~*(?i)^(?<prefix>.*[?&](?:token|password|secret|key|api_key|auth)=)[^&]*(?<suffix>.*)$"  "$prefix[REDACTED]$suffix";
    default                           $request_uri;
}

# 3. Анонимизация IP-адреса (обнуление последнего октета IPv4 для комплаенса)
map $remote_addr $anonymized_ip {
    "~*(?<prefix>\d+\.\d+\.\d+)\.\d+"  "$prefix.0";
    "~*(?<prefix>[0-9a-fA-F:]+):[0-9a-fA-F]+" "$prefix:0000";
    default                           "0.0.0.0";
}

# 4. Безопасный структурированный JSON-формат логирования
log_format sanitized_json escape=json '{'
    '"time_local":"$time_iso8601",'
    '"client_ip":"$anonymized_ip",'
    '"request_method":"$request_method",'
    '"request_uri":"$sanitized_request_uri",'
    '"status":$status,'
    '"bytes_sent":$bytes_sent,'
    '"request_time":$request_time,'
    '"http_referrer":"$http_referer",'
    '"http_user_agent":"$http_user_agent",'
    '"auth_header":"$sanitized_authorization"'
'}';

access_log /var/log/nginx/access_sanitized.log sanitized_json;
```

### Сценарий 16: Валидация JWT в Nginx Open Source через njs (`ngx_http_js_module`)

**Контекст:** В коммерческой версии Nginx Plus доступен нативный модуль `ngx_http_auth_jwt_module`. В бесплатной версии Nginx Open Source валидация JWT реализуется через скриптовый модуль **njs**, позволяя верифицировать подпись и срок действия токена до передачи запроса бэкенду без внешних сетевых вызовов.

#### 1. Файл валидатора `/etc/nginx/njs/jwt_validator.js`

```javascript
// njs скрипт валидации JWT с алгоритмом HMAC-SHA256 (HS256)
async function verifyJwt(r) {
    const authHeader = r.headersIn['Authorization'];
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
        r.return(401, JSON.stringify({ error: 'unauthorized', message: 'Missing Bearer token' }));
        return;
    }

    const token = authHeader.substring(7);
    const parts = token.split('.');
    if (parts.length !== 3) {
        r.return(400, JSON.stringify({ error: 'bad_request', message: 'Malformed JWT' }));
        return;
    }

    try {
        // Декодирование Payload
        const payloadJson = Buffer.from(parts[1], 'base64url').toString('utf8');
        const payload = JSON.parse(payloadJson);

        // 1. Проверка срока жизни токена (exp)
        const now = Math.floor(Date.now() / 1000);
        if (payload.exp && payload.exp < now) {
            r.return(401, JSON.stringify({ error: 'token_expired', message: 'Token has expired' }));
            return;
        }

        // 2. Верификация криптографической подписи HS256 через WebCrypto API
        const secret = r.variables.jwt_secret;
        const key = await crypto.subtle.importKey(
            'raw',
            Buffer.from(secret, 'utf8'),
            { name: 'HMAC', hash: 'SHA-256' },
            false,
            ['verify']
        );

        const dataToVerify = Buffer.from(`${parts[0]}.${parts[1]}`, 'utf8');
        const signature = Buffer.from(parts[2], 'base64url');

        const isValid = await crypto.subtle.verify('HMAC', key, signature, dataToVerify);
        if (!isValid) {
            r.return(403, JSON.stringify({ error: 'forbidden', message: 'Invalid JWT signature' }));
            return;
        }

        // 3. Проброс пользователя в переменные Nginx и пропуск запроса
        r.variables.jwt_user_id = payload.sub || 'anonymous';
        r.pass();
    } catch (e) {
        r.error(`JWT validation error: ${e.message}`);
        r.return(401, JSON.stringify({ error: 'auth_failed', message: 'JWT verification failed' }));
    }
}

export default { verifyJwt };
```

#### 2. Конфигурация Nginx `/etc/nginx/conf.d/jwt_api.conf`

```nginx
# Подключение JavaScript-модуля (load_module modules/ngx_http_js_module.so;)
js_import jwt from /etc/nginx/njs/jwt_validator.js;

server {
    listen 443 ssl;
    server_name api.example.corp;

    # Секретный ключ подписи (в prod загружается из защищенного файла или env)
    set $jwt_secret "super-secret-cluster-signing-key-2026";
    set $jwt_user_id "";

    location /api/v1/protected/ {
        # Выполнение проверки на фазе доступа
        js_access jwt.verifyJwt;

        proxy_pass http://backend_api_cluster;
        proxy_http_version 1.1;

        # Передача аутентифицированного пользователя бэкенду
        proxy_set_header X-Authenticated-User $jwt_user_id;
    }
}
```

## Операции и команды

### Валидация и применение конфигурации

```bash
# Полная проверка синтаксиса перед перезагрузкой
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Просмотр полной собранной конфигурации с инспектированием директив безопасности
nginx -T 2>/dev/null | grep -iE 'server_tokens|limit_req|limit_conn|ssl_protocols' | head -n 10
# → server_tokens off;
# → limit_req_zone $limit_key_by_ip zone=api_general:10m rate=10r/s;
# → limit_req_status 429;
# → ssl_protocols TLSv1.2 TLSv1.3;

# Плавное применение изменений без разрыва активных соединений (Graceful Reload)
systemctl reload nginx
# → процесс перечитывает конфигурацию и запускает новых воркеров
```

### Инспекция сетевых сокетов и портов

```bash
# Проверка слушающих TCP-сокетов Nginx
ss -tlnpn '( sport = :80 or sport = :443 )'
# → LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=1542,fd=6),("nginx",pid=1543,fd=6))

# Проверка UDP-сокета 443 (HTTP/3 / QUIC)
ss -ulpn '( sport = :443 )'
# → UNCONN 0 0 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=1542,fd=7))
```

### Аудит заголовков безопасности через curl

```bash
# Проверка отправляемых заголовков безопасности
curl -sI https://service.example.corp | grep -iE "strict-transport|x-frame|x-content|permissions|cross-origin|content-security|server"
# → strict-transport-security: max-age=63072000; includeSubDomains; preload
# → x-content-type-options: nosniff
# → x-frame-options: SAMEORIGIN
# → referrer-policy: strict-origin-when-cross-origin
# → permissions-policy: geolocation=(), microphone=(), camera=(), payment=(), usb=()
# → cross-origin-opener-policy: same-origin
# → cross-origin-resource-policy: same-origin
# → content-security-policy: default-src 'self'; ...
# → server: nginx (версия отсутствует)
```

### Мониторинг событий безопасности в реальном времени

```bash
# Отслеживание срабатываний Rate Limiting в логах Nginx
tail -f /var/log/nginx/error.log | grep --line-buffered "limiting requests"
# → 2026/10/17 14:10:05 [warn] 1543#1543: *12045 limiting requests, excess: 20.450 by zone "api_general", client: 198.51.100.44, server: api.example.corp, request: "GET /api/v1/feed HTTP/1.1"

# Проверка журнала системного юнита на наличие аварий воркеров и OOM
journalctl -u nginx --since "1 hour ago" -p warning..alert --no-pager
```

### Интеграция с Fail2ban и управление блокировками

Интеграция с демоном Fail2ban позволяет делегировать повторяющиеся блокировки нарушителей с L7 веб-сервера на уровень пакетного фильтра ядра Linux (`nftables` / `iptables`), защищая воркеры Nginx от расходования ресурсов.

#### 1. Фильтр `/etc/fail2ban/filter.d/nginx-limit-req.conf`

```ini
[Definition]
# Поиск сообщений о превышении лимитов rate limit в журнале ошибок Nginx
failregex = ^\s*\[warn\]\s+\d+#\d+:\s+\*\d+\s+limiting requests, excess:\s+[\d\.]+\s+by zone "(?:[^"]+)", client:\s+<HOST>,
ignoreregex =
```

#### 2. Конфигурация джейла `/etc/fail2ban/jail.d/nginx-limit-req.local`

```ini
[nginx-limit-req]
enabled  = true
port     = http,https
filter   = nginx-limit-req
logpath  = /var/log/nginx/error.log
maxretry = 5
findtime = 60
bantime  = 3600
banaction = nftables-multiport
```

> **КРИТИЧЕСКАЯ ПРОИЗВОДСТВЕННАЯ ЛОВУШКА (Fail2ban за Reverse Proxy / CDN):**
> Если Nginx работает за внешним балансировщиком нагрузки (HAProxy, Keepalived, Cloudflare, AWS ALB), стандартное действие `nftables` / `iptables` заблокирует сетевой пакет по IP-адресу источника.
> Источником для ОС является **IP-адрес самого балансировщика**, а не клиента! Блокировка этого адреса приведет к **полному отказу сервиса (DoS) для всех 100% пользователей**!
> **Решение:**
> 1. Если перед сервером есть L4/L7-балансировщик, разворачивайте Fail2ban/CrowdSec **на пограничном балансировщике**, а не на внутренних нодах Nginx.
> 2. Либо используйте кастомное действие бана, которое добавляет строку `deny <HOST>;` в конфигурационный файл `/etc/nginx/conf.d/banned_ips.conf` с вызовом `nginx -s reload`, чтобы блокировка происходила на уровне L7 с учетом `ngx_http_realip_module`.

```bash
# Просмотр активного статуса джейла rate-limit блокировок
fail2ban-client status nginx-limit-req
# → Status for the jail: nginx-limit-req
# → |- Filter
# → |  |- Currently failed: 4
# → |  |- Total failed:     285
# → `- Actions
# →    |- Currently banned: 2
# →    `- Banned IP list:   198.51.100.44 203.0.113.19

# Ручная разблокировка ложно заблокированного IP инженера
fail2ban-client set nginx-limit-req unbanip 198.51.100.44
# → 198.51.100.44
```

### Нагрузочное тестирование Rate Limiting

Проверка корректности выдачи кода `429 Too Many Requests` перед выводом в бой:

```bash
# Генерация всплеска запросов циклом curl
for i in {1..25}; do curl -s -o /dev/null -w "%{http_code}\n" https://api.example.corp/api/test; done | sort | uniq -c
# → 10 200
# → 15 429
```

## Устранение неполадок

### Диагностическая методология SRE

При возникновении инцидента безопасности или жалоб на блокировку легитимных клиентов:

1. **Локализация уровня сбоя:**
   - L3/L4 (сеть, nftables, SYN cookies, conntrack table exhaustion).
   - L7 Nginx Core (ошибки парсинга, тайм-ауты, переполнение пула `worker_connections`).
   - Модули безопасности (Rate Limiting `limit_req`, Connection Limiting `limit_conn`).
   - Модуль WAF (ложные срабатывания ModSecurity/Coraza с кодом 403).
2. **Сбор фактов:**
   - Код ответа клиенту (`curl -v -I`).
   - Системный лог ошибок: `/var/log/nginx/error.log`.
   - Аудит WAF: `/var/log/modsecurity/audit.log`.
   - Статус джейлов: `fail2ban-client status`.
3. **Безопасная нейтрализация:** внесение корректировок, `nginx -t`, `systemctl reload nginx`, проверка метрик.

### Сводная таблица инцидентов и решений

| Симптом / Ошибка в логе | Первопричина | Пошаговое решение для инженера |
| :--- | :--- | :--- |
| **Security Headers отсутствуют в ответах конкретного `/endpoint/`** | В целевом блоке `location` объявлена директива `add_header`, стершая родительские заголовки | Добавить `include /etc/nginx/snippets/security_headers.conf;` непосредственно внутрь данного `location`. |
| **Заголовки безопасности пропадают при ошибках 404, 500, 502** | Директивы `add_header` объявлены без параметра `always` | Добавить параметр `always` в конец каждой директивы `add_header`. |
| **Легитимные пользователи массово получают 429 при переходе на сайт** | 1. Запросы идут через внутренний балансировщик без восстановления Real IP.<br>2. Rate limit настроен без `burst`. | 1. Настроить `set_real_ip_from` и `real_ip_header X-Forwarded-For;`.<br>2. Добавить `burst=20 delay=10;` для сглаживания всплесков загрузки статических ассетов страницы. |
| `could not allocate new entry in limit_req zone "..."` | Зона разделяемой памяти переполнена уникальными IP-адресами под воздействием распределенного DoS | 1. Увеличить размер зоны: `limit_req_zone ... zone=api_general:50m`.<br>2. Включить сброс неактивных записей или ужесточить фильтрацию на L3/L4. |
| `ModSecurity: Access denied with code 403 (phase 2)` | Ложное срабатывание правила OWASP CRS на легитимный запрос приложения | Найти в `/var/log/modsecurity/audit.log` идентификатор сработавшего правила (`id "942100"`) и добавить `SecRuleRemoveById 942100` в конфигурацию хоста. |
| `worker_connections are not enough while connecting to upstream` | Исчерпан пул соединений процесса воркера из-за флуда или медленных клиентов Slowloris | 1. Увеличить `worker_connections 4096;` в секции `events`.<br>2. Проверить системный лимит `worker_rlimit_nofile 65535;` и лимиты systemd-юнита (`LimitNOFILE=65535`). |
| `client intended to send too large body` (код 413) | Тело загружаемого файла превышает лимит `client_max_body_size` | Увеличить `client_max_body_size 50m;` в целевом блоке `location /upload/`. |
| `client sent invalid header line` (код 400) | Запрос содержит заголовки с нижним подчеркиванием (`_`), отброшенные директивой `underscores_in_headers off;`. | Если API действительно требует подчеркиваний, включить `underscores_in_headers on;`, но предварительно убедиться, что бэкенд не подвержен коллизиям заголовков в CGI/WSGI окружении. |

### Аварийные регламенты (SRE Runbooks)

#### Runbook 1: Отражение активного HTTP-флуда (L7 DoS / DDoS)

```text
1. Локализация источника:
   tail -n 1000 /var/log/nginx/access.log | awk '{print $1}' | sort | uniq -c | sort -rn | head -n 10
2. Выявление целевого URL:
   tail -n 1000 /var/log/nginx/access.log | awk '{print $7}' | sort | uniq -c | sort -rn | head -n 10
3. Если атака идет с группы фиксированных IP:
   Блокировка на уровне ядра Linux через nftables в обход Nginx:
   nft add element inet filter blackhole { 198.51.100.55, 203.0.113.88 }
4. Если атака распределенная (ботнет по всему пулу IP):
   - Временное ужесточение зоны rate limiting в /etc/nginx/conf.d/rate_limiting.conf:
     limit_req_zone $limit_key_by_ip zone=emergency:20m rate=3r/s;
   - Перевод подозрительного location на аварийный лимит:
     limit_req zone=emergency burst=5 nodelay;
   - Сокращение таймаутов чтения:
     client_body_timeout 5s; client_header_timeout 5s;
   - Применение:
     nginx -t && systemctl reload nginx
5. Мониторинг стабилизации:
   watch -n 1 "ss -s; ss -tlnpn '( sport = :443 )'"
```

#### Runbook 2: Массовый шторм ложных срабатываний WAF после релиза приложения

```text
1. Подтверждение причины сбоя в логах аудита:
   tail -n 50 /var/log/modsecurity/audit.log | grep -E "ModSecurity: Access denied|\[id \""
2. Идентификация ID правила (например, [id "941100"] - XSS filter):
   grep -o '\[id "[0-9]\+"\]' /var/log/modsecurity/audit.log | sort | uniq -c | sort -rn
3. Вариант оперативного решения А (целевое исключение правила):
   Добавить в /etc/nginx/modsecurity/modsec_main.conf:
   SecRuleRemoveById 941100
   Применить: nginx -t && systemctl reload nginx
4. Вариант оперативного решения Б (аварийный перевод в DetectionOnly, если сбоят десятки правил):
   В /etc/nginx/modsecurity/modsec_main.conf заменить:
   SecRuleEngine DetectionOnly
   Применить: nginx -t && systemctl reload nginx
   Зафиксировать инцидент, передать логи разработчикам для адаптации правил.
```

## Рекомендации и лучшие практики

### Чеклист SRE по харденингу Nginx/Angie

- [ ] **Тайм-ауты соединений:** `client_body_timeout 10s`, `client_header_timeout 10s`, `send_timeout 10s` настроены глобально.
- [ ] **Лимиты буферов:** `large_client_header_buffers 4 8k`, `client_header_buffer_size 1k`, `client_max_body_size` ограничен минимально необходимым значением.
- [ ] **HTTP/2 & HTTP/3:** `http2_max_concurrent_streams 128`, версии Nginx обновлены для защиты от Rapid Reset.
- [ ] **Rate Limiting:** `limit_req_zone` настроен с двухфазным сглаживанием (`burst` + `delay`), статус возврата переведен на `429`.
- [ ] **Белые списки:** Мониторинг Prometheus, офисные VPN и внутренние балансировщики исключены из rate limiting через `geo` + `map`.
- [ ] **Real IP:** Корректно восстановлен истинный `$remote_addr` через `set_real_ip_from` и `real_ip_header`.
- [ ] **Security Headers:** Подключен сниппет с HSTS, CSP, X-Content-Type-Options, Permissions-Policy, COOP/COEP с обязательным флагом `always`.
- [ ] **Проверка наследования `add_header`:** Все блоки `location`, переопределяющие заголовки, повторно подключают сниппет `security_headers.conf`.
- [ ] **Сокрытие версий:** `server_tokens off;` включен, upstream-заголовки `Server` и `X-Powered-By` удаляются через `proxy_hide_header`.
- [ ] **Скрытые и конфиденциальные файлы:** Блокировка `.git`, `.env`, `.bak`, `.sql`, `wp-config` с кодом ответа `404`.
- [ ] **Каталоги загрузок:** Исполнение скриптов в каталогах пользовательских файлов заблокировано (`return 403`).
- [ ] **Request Smuggling:** `proxy_request_buffering on;`, `proxy_http_version 1.1;`, `proxy_set_header Transfer-Encoding "";`.
- [ ] **Модуль WAF:** ModSecurity v3 или Coraza подключен, настроено исключение ложных срабатываний через `SecRuleRemoveById`.
- [ ] **Файловые права:** Конфигурация доступна только root (644/755), приватные ключи изолированы (600), кэш принадлежит `www-data`.
- [ ] **Fail2ban:** Активны джейлы для блокировки повторяющихся нарушителей rate limit и 401/403 ошибок на уровне `nftables`.

### Базовые требования к версиям ПО (2026 Baseline)

| Компонент | Рекомендуемая версия | Обоснование для производственной среды |
| :--- | :--- | :--- |
| **Nginx OSS** | 1.26.x (Stable) / 1.28+ (Mainline) | Закрыты критические уязвимости HTTP/2 Rapid Reset (CVE-2023-44487), стабильный HTTP/3 QUIC. |
| **Angie** | 1.6+ / 1.12.x | Нативная кластерная синхронизация лимитов `sync`, директива `max_headers`, встроенный API статистики. |
| **ModSecurity** | 3.0.12+ | Стабильная кодовая база libmodsecurity3 с коннектором для Nginx. |
| **OWASP CRS** | v4.x | Существенно снижен уровень ложных срабатываний по сравнению с v3, улучшена поддержка JSON API. |
| **Fail2ban** | 0.11.x+ | Нативный бэкенд для `nftables` (высокая производительность блокировок O(1) без оверхеда iptables). |
| **OpenSSL** | 3.0 LTS / 3.4+ / 3.5+ | Поддержка TLS 1.3, современных наборов шифров и аппаратного ускорения AES-NI. |

### Производительность и накладные расходы уровней защиты

| Уровень / Механизм защиты | Дополнительная задержка (Latency) | Нагрузка на RAM / CPU | Рекомендация SRE |
| :--- | :--- | :--- | :--- |
| `server_tokens off;` | 0 мс | 0% | Включать повсеместно во всех окружениях. |
| Security Headers (`always`) | < 0.05 мс | < 0.1% | Включать повсеместно во всех окружениях. |
| `limit_req` / `limit_conn` | < 0.5 мс | ~10 МБ RAM на 160k IP, минимальный CPU | Обязательный базовый слой для публичных API и форм аутентификации. |
| `ngx_http_realip_module` | < 0.1 мс | Незначительная | Обязательно при наличии upstream-балансировщиков. |
| `secure_link` (MD5) | < 0.3 мс | Минимальный оверхед CPU на хэш | Для защищенной раздачи медиаконтента и защиты от хотлинкинга. |
| **ModSecurity v3 (OWASP CRS)** | **5 – 20 мс** | **~50–100 МБ RAM на воркер, до 25% CPU** | Использовать избирательно для публичных веб-форм и API. Отключать (`modsecurity off;`) для статических ассетов и медиа. |
| **Coraza WAF (Go/Wasm)** | **2 – 8 мс** | **~30–50 МБ RAM, умеренный CPU** | Высокопроизводительная альтернатива ModSecurity для RPS > 10 000. |

## Дополнительная информация

### См. также

*   **[Харденинг Nginx на уровне системы: systemd-юнит, SELinux, AppArmor](./nginx_systemd_selinux_hardening.md)** — глубокая изоляция процесса Nginx, непривилегированный запуск (`User=nginx`), capability `CAP_NET_BIND_SERVICE`.
*   **[Параметры виртуального хоста TLS/SSL](./TLS_SSL/nginx_tls_virtual_host_config.md)** — эталонная настройка TLS 1.3, шифров, сессионных тикетов и OCSP Stapling.
*   **[Глобальные параметры TLS/SSL в Nginx](./TLS_SSL/nginx_tls_global_parameters.md)** — тюнинг SSL-кэша, криптографических библиотек и буферов TLS.
*   **[Диагностика TLS/SSL](./TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md)** — решение проблем с рукопожатием, сертификатами и совместимостью клиентов.
*   **[Конфигурация mTLS в Nginx](./TLS_SSL/nginx_mtls_configuration.md)** — взаимная аутентификация клиентов по сертификатам x509.
*   **[Защита Upstream TLS и mTLS к бэкендам](./TLS_SSL/nginx_upstream_tls_and_mtls.md)** — Zero-Trust валидация сертификатов бэкендов, передача SNI и взаимная аутентификация.
*   **[Географическая фильтрация и модуль GeoIP2](./nginx_geoip2_access_control.md)** — блокировка стран, ASN-фильтрация, MaxMind MMDB и связка с Real-IP.
*   **[Защита от DoS-атак в Angie](../../Angie/High_Load/dos_protection.md)** — кластерная синхронизация зон `sync`, мониторинг лимитов через REST API.
*   **[Контроль доступа в Angie](../../Angie/angie_access_control.md)** — разграничение доступа по IP, JWT-валидация и модули аутентификации.
*   **[Скриптовый модуль njs в Nginx](../Core/nginx_njs_module.md)** — валидация JWT, кастомные фильтры и интеграция с WebCrypto API.
*   **[SSRF: Server-Side Request Forgery для веб-серверов](../../Concepts/ssrf.md)** — векторы атак через обратный прокси и методы изоляции локальных адресов.
*   **[CORS в Nginx](./nginx_cors_guide.md)** — архитектура настройки Cross-Origin Resource Sharing, Preflight OPTIONS и белый список Origin.
*   **[CORS в Angie](../../Angie/angie-cors.md)** — корректная обработка preflight-запросов и заголовков `Access-Control-*`.
*   **[Безопасность HTTP в продакшене](../../../Networking/Protocols/HTTP/http_security_hardening.md)** — протокольный анализ Security Headers, CORS и предотвращения атак.
*   **[Rate Limiting и устойчивость HTTP-сервисов](../../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md)** — алгоритмы Token Bucket, Leaky Bucket и Circuit Breakers.
*   **[WAF для веб-приложений (ModSecurity, NAXSI, Coraza)](../../../Security/ApplicationSecurity/waf.md)** — архитектура WAF, настройка OWASP CRS и управление правилами.
*   **[fail2ban для защиты Linux-серверов](../../../Linux/Security/Tools/fail2ban.md)** — архитектура джейлов, фильтры логов и интеграция с `nftables`.
*   **[Защита веб-серверов от ботов](../../Concepts/bot_protection.md)** — поведенческий анализ, honeypot-ловушки и гибридная фильтрация.
*   **[Устранение неполадок Nginx](../Operations/nginx_troubleshooting.md)** — диагностика аварийных состояний, переполнения буферов и сбоев проксирования.
