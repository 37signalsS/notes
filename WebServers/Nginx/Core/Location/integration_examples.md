# Nginx location: примеры интеграции

**Актуально для:** Nginx 1.26.x (Stable) / 1.27.x (Mainline)

## Определения

**Примеры интеграции (Integration Examples)** — эталонные и проверенные конфигурации блоков `location`, предназначенные для сопряжения Nginx с вышестоящими бэкендами (application servers, runtime-демонами) в промышленной эксплуатации системных администраторов, DevOps и SRE.

**Бэкенд-сервис (Backend Service / Upstream)** — процесс или группа процессов (PHP-FPM, Gunicorn, Uvicorn, Node.js, Go/Rust binary), выполняющих динамическую бизнес-логику и принимающих запросы от Nginx.

**FastCGI (Fast Common Gateway Interface)** — бинарный клиент-серверный протокол для взаимодействия веб-сервера с долгоживущими изолированными процессами приложений (преимущественно PHP), исключающий накладные расходы классического CGI на создание отдельного процесса ОС на каждый запрос.

**uWSGI (Universal Web Server Gateway Interface)** — высокопроизводительный модульный сервер приложений и бинарный протокол взаимодействия с приложениями на языках Python, Perl, Ruby.

**ASGI (Asynchronous Server Gateway Interface)** — асинхронный стандарт интерфейса между веб-серверами и приложениями на языке Python (FastAPI, Starlette, Django Channels) с нативной поддержкой WebSockets, HTTP/2 и Server-Sent Events под управлением серверов Uvicorn или Hypercorn.

**SCGI (Simple Common Gateway Interface)** — облегченный текстовый протокол шлюза на базе формата Netstrings, используемый как альтернатива FastCGI в ряде системных сервисов (например, rTorrent).

**gRPC (gRPC Remote Procedure Calls)** — современный бинарный протокол удаленного вызова процедур на базе транспорта HTTP/2 и формата сериализации Protocol Buffers, поддерживающий потоковую передачу данных и мультиплексирование.

**Unix Domain Socket (UDS)** — механизм межпроцессного взаимодействия (IPC) в рамках одной операционной системы (семейство `AF_UNIX`), передающий поток байтов через кольцевые буферы ядра Linux без накладных расходов сетевого стека, контрольных сумм и сетевых интерфейсов.

**TCP Socket** — сетевой сокет (`IP:Port`), использующий стек TCP/IP для взаимодействия между процессами на одном сервере (через loopback `127.0.0.1`) или между физически разделенными узлами инфраструктуры.

**Upstream Keepalive (Пул постоянных соединений)** — механизм кэширования и повторного использования открытых сокетов между Nginx и бэкендами, устраняющий задержки на повторное выполнение TCP 3-way handshake и предотвращающий исчерпание пула эфемерных портов.

**Буферизация прокси (Proxy Buffering)** — режим работы Nginx, при котором ответ бэкенда считывается в буферы оперативной памяти (или временные файлы на диске) на максимально возможной скорости, освобождая воркер бэкенда еще до того, как медленный клиент завершит прием данных.

**WebSocket Upgrade** — протокольное переключение активного HTTP/1.1 соединения на двунаправленный дуплексный протокол WebSocket через передачу клиентом и проксирование заголовков `Upgrade: websocket` и `Connection: Upgrade`.

**FastCGI Microcaching** — техника кратковременного (1–5 секунд) кэширования ответов динамических бэкендов в оперативной памяти Nginx для предотвращения каскадного отказа (thundering herd problem) при пиковых нагрузках на CMS.

---

## Архитектура и базовые концепции

### Архитектура обратного проксирования в Nginx

В роли обратного прокси (Reverse Proxy) Nginx принимает клиентские запросы, маршрутизирует их на основе правил директивы `location`, трансформирует метаданные (заголовки, URI) и транслирует в вышестоящий сервис по соответствующему протоколу.

```
[ Клиент (Браузер / API / curl) ]
               │
               │ HTTP/1.1, HTTP/2 (TLS)
               ▼
┌────────────────────────────────────────────────────────┐
│                   Nginx Worker Process                 │
│                                                        │
│  1. Прием соединения (epoll event loop)                │
│  2. Выбор server_name и сопоставление location         │
│  3. Модификация заголовков (proxy_set_header)          │
│  4. Проверка прав, лимитов (limit_req) и кэша          │
└────────────────────────────────────────────────────────┘
               │
   ┌───────────┼──────────────┬──────────────┬───────────┐
   │ FastCGI   │ HTTP/1.1     │ uwsgi        │ gRPC      │ SCGI
   ▼           ▼              ▼              ▼           ▼
[PHP-FPM]  [Node/Go/Uvicorn] [uWSGI]     [gRPC Server] [rTorrent]
 (UDS/TCP)   (TCP/UDS)      (UDS/TCP)      (h2c/TCP)     (UDS/TCP)
```

Жизненный цикл проксированного запроса:
1. **Прием и парсинг:** Worker process принимает соединение через `epoll`, разбирает HTTP-запрос и находит наиболее специфичный блок `location` в соответствии с алгоритмом приоритетов.
2. **Инициализация upstream-соединения:** Модуль шлюза (`proxy`, `fastcgi`, `uwsgi`, `grpc`) извлекает свободное соединение из пула `keepalive` или инициирует новое подключение через системный вызов `connect()` к сокету (UDS или TCP).
3. **Сериализация и отправка:** Запрос трансформируется в целевой протокол. Применяются директивы добавления/переопределения заголовков (`proxy_set_header`, `fastcgi_param`), формируются служебные структуры данных.
4. **Прием и буферизация ответа:** Nginx вычитывает заголовки ответа в `proxy_buffer_size` / `fastcgi_buffer_size`. Если включена буферизация, тело ответа сохраняется в цепочку буферов памяти `proxy_buffers`. Если ответ превышает лимит буферов памяти, излишек сбрасывается во временный файл на диске (`proxy_temp_path`).
5. **Трансляция клиенту:** Заголовки бэкенда фильтруются (директивы `proxy_hide_header`), и ответ отдается клиенту через клиентский сокет.

### Протоколы интеграции и соответствующие модули Nginx

| Модуль Nginx | Директива шлюза | Протокол взаимодействия | Поддерживаемый транспорт | Типовые бэкенды |
| :--- | :--- | :--- | :--- | :--- |
| `ngx_http_proxy_module` | `proxy_pass` | HTTP/1.0, HTTP/1.1, WebSocket | Unix Domain Socket, TCP Socket | Node.js, Go, Python (Gunicorn, Uvicorn), Java (Spring), Rust |
| `ngx_http_fastcgi_module` | `fastcgi_pass` | FastCGI (бинарный) | Unix Domain Socket, TCP Socket | PHP-FPM, C/C++ FastCGI-демоны |
| `ngx_http_uwsgi_module` | `uwsgi_pass` | `uwsgi` (бинарный) | Unix Domain Socket, TCP Socket | uWSGI (Python, Ruby, Perl) |
| `ngx_http_grpc_module` | `grpc_pass` | gRPC over HTTP/2 | TCP Socket (cleartext `grpc://`, TLS `grpcs://`) | gRPC microservices (Go, Python, Java, C++) |
| `ngx_http_scgi_module` | `scgi_pass` | SCGI (Netstrings) | Unix Domain Socket, TCP Socket | rTorrent, специализированные утилиты |

### Сравнение сокетов: Unix Domain Socket vs TCP Socket

В локальной среде (Nginx и бэкенд размещены на одном хосте ОС) выбор типа сокета существенно влияет на задержку (latency), пропускную способность (throughput) и безопасность.

| Параметр | Unix Domain Socket (`unix:/path/to/sock`) | TCP Socket (`127.0.0.1:port`) |
| :--- | :--- | :--- |
| **Сетевой стек ОС** | Обходит стек TCP/IP; передача данных в памяти через буферы ядра (IPC) | Полное прохождение стека TCP/IP (loopback interface `lo`) |
| **Вычисление чексумм** | Отсутствует (гарантируется ядром) | Выполняется расчет и проверка контрольных сумм TCP/IP пакетов |
| **Задержка (Latency)** | Минимальная (~10–15 мкс на запрос) | Выше на 25–40% из-за TCP-накладных расходов (~20–35 мкс) |
| **Пропускная способность** | На 15–20% выше на операциях малого размера | Ограничена системными буферами loopback |
| **Безопасность доступа** | Стандартные права файловой системы Linux (`chmod`, `chown`, POSIX ACL) | Доступен любому локальному процессу, если не ограничен iptables/nftables |
| **Масштабируемость** | Только локальный хост (одна ОС) | Локальный хост или распределенная сеть |
| **Очередь соединений** | Ограничена `net.core.somaxconn` и параметром `backlog` демона | Ограничена `net.core.somaxconn`, `net.ipv4.tcp_max_syn_backlog` |
| **Риск исчерпания портов** | Отсутствует | При высокой нагрузке возможен TIME_WAIT exhaustion эфемерных портов |

### Механизм буферизации ответов и управление памятью

По умолчанию в Nginx включена буферизация для всех шлюзовых модулей (`proxy_buffering on;`, `fastcgi_buffering on;`).

**Поведение при включенной буферизации (`proxy_buffering on;`):**
1. Nginx забирает ответ бэкенда на максимальной скорости локальной сети или UDS.
2. Первые байты (заголовки) помещаются в `proxy_buffer_size`.
3. Тело ответа складывается в пул буферов `proxy_buffers <число> <размер>` (например, `8 16k`).
4. Если тело ответа превышает суммарный объем буферов памяти, активируется механизм сброса на диск: порциями до `proxy_busy_buffers_size` ответ отправляется клиенту, а оставшаяся часть временно записывается в файл каталога `proxy_temp_path` (максимальный размер регулируется `proxy_max_temp_file_size`).
5. **Преимущество:** рабочий процесс бэкенда быстро завершает выполнение задачи и освобождается для следующего запроса, не простаивая в ожидании медленных клиентов (клиенты на 3G/мобильных сетях).

**Поведение при отключенной буферизации (`proxy_buffering off;`):**
1. Nginx транслирует входящие байты от бэкенда клиенту синхронно по мере их поступления.
2. Используется только один буфер `proxy_buffer_size` для разбора заголовков.
3. **Обязательно для:** Server-Sent Events (SSE), потокового HTTP/REST API, интерактивных консолей, долгих выгрузок данных (Streaming CSV/JSON).

### Upstream Keepalive и повторное использование соединений

По умолчанию директива `proxy_pass` работает по протоколу HTTP/1.0 и закрывает TCP-соединение после каждого запроса (заголовок `Connection: close`). Это порождает тысячи сокетов в состоянии `TIME_WAIT` и перегружает бэкенды постоянными рукопожатиями TCP.

Для включения постоянных соединений обязательно настраиваются два элемента:
1. В блоке `upstream` объявляется директива `keepalive <N>;` — кэш открытых неактивных (idle) соединений на каждый worker-процесс.
2. В блоке `location` включается HTTP/1.1 и очищается заголовок закрытия:
   ```nginx
   proxy_http_version 1.1;
   proxy_set_header Connection "";
   ```

### Сквозная цепочка таймаутов

Несогласованность таймаутов между веб-сервером, приложением и базой данных приводит к зависанию процессов и ошибкам `504 Gateway Timeout`. В промышленной эксплуатации применяется строгое правило монотонного убывания таймаутов вглубь архитектуры:

$$\text{client\_header\_timeout} \ge \text{proxy\_read\_timeout} > \text{app\_execution\_timeout} > \text{database\_query\_timeout}$$

Например, для PHP-FPM:
```
База данных: statement_timeout = 10s
     ▲
     │ (должен быть меньше лимита PHP)
PHP-FPM: max_execution_time = 30s, request_terminate_timeout = 35s
     ▲
     │ (должен быть больше аварийного завершения FPM на 5-10 секунд)
Nginx: fastcgi_read_timeout = 45s
```
Такой порядок гарантирует: если база данных или бэкенд зависают, процесс аварийно завершается приложением с фиксацией понятной трассировки в журнале ошибок (`slowlog`), а не обрывается веб-сервером с "немой" ошибкой 504.

### Передача метаданных и заголовков

При проксировании клиентский IP-адрес и атрибуты исходного запроса теряются, если их явно не транслировать бэкенду.

| Заголовок | Значение переменной Nginx | Назначение |
| :--- | :--- | :--- |
| `Host` | `$host` | Имя виртуального хоста (предотвращает Host Header Injection и сбои роутинга) |
| `X-Real-IP` | `$remote_addr` | Физический IP-адрес клиента, установившего соединение с Nginx |
| `X-Forwarded-For` | `$proxy_add_x_forwarded_for` | Полная цепочка всех прокси-серверов в формате `client, proxy1, proxy2` |
| `X-Forwarded-Proto` | `$scheme` | Протокол клиента (`http` или `https`) для генерации безопасных ссылок и редиректов |
| `X-Forwarded-Host` | `$host` | Исходный запрошенный хост |
| `X-Forwarded-Port` | `$server_port` | Порт, на который поступил запрос (`80` или `443`) |

---

## Практические сценарии

### Сценарий 1: PHP-приложение (PHP-FPM 8.3/8.4 через UDS)

Конфигурация для современных фреймворков (Laravel, Symfony, Yii2) на базе операционных систем Debian 12 / Ubuntu 24.04 с защитой от исполнения произвольного кода.

#### Требования (Prerequisites)
- Nginx версии 1.26+ с директивой `http2 on;`.
- Пул PHP-FPM запущен и слушает локальный сокет `/run/php/php8.3-fpm.sock` (права `www-data:www-data`, маска `0660`).
- Корневая директория приложения: `/var/www/html/public`.

```nginx
# /etc/nginx/sites-available/app.example.com.conf

server {
    listen 80;
    server_name app.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name app.example.com;

    root /var/www/html/public;
    index index.php index.html;

    ssl_certificate     /etc/letsencrypt/live/app.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.example.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # Логирование с детализацией upstream
    access_log /var/log/nginx/app_access.log combined;
    error_log  /var/log/nginx/app_error.log warn;

    # Ограничение размера загружаемого контента
    client_max_body_size 32M;

    # Защита скрытых системных файлов (.env, .git)
    location ~ /\.(?!well-known) {
        deny all;
        access_log off;
        log_not_found off;
    }

    # Единая точка входа для Front Controller (try_files)
    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }

    # Обработка PHP-скриптов
    location ~ \.php$ {
        # Защита от передачи несуществующих файлов интерпретатору (предотвращение атак фиксации пути)
        try_files $uri =404;

        fastcgi_split_path_info ^(.+\.php)(/.+)$;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
        fastcgi_index index.php;

        include fastcgi_params;

        # Критические переменные окружения FastCGI
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param PATH_INFO       $fastcgi_path_info;
        fastcgi_param HTTP_PROXY      ""; # Защита от уязвимости HTTPoxy

        # Тюнинг буферизации FastCGI для защиты памяти
        fastcgi_buffer_size          32k;
        fastcgi_buffers              8 16k;
        fastcgi_busy_buffers_size    64k;
        fastcgi_temp_file_write_size 64k;

        # Таймауты ожидания бэкенда
        fastcgi_connect_timeout 5s;
        fastcgi_send_timeout    60s;
        fastcgi_read_timeout    60s;

        # Перехват ошибок бэкенда для централизованной обработки
        fastcgi_intercept_errors on;
    }

    # Клиентское кэширование статических ресурсов
    location ~* \.(css|js|jpg|jpeg|png|gif|ico|svg|webp|avif|woff2)$ {
        expires 30d;
        add_header Cache-Control "public, no-transform, immutable";
        access_log off;
        log_not_found off;
    }
}
```

#### Валидация и проверка
```bash
# 1. Проверка синтаксиса конфигурации Nginx
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Проверка доступности сокета PHP-FPM и прав доступа
ls -la /run/php/php8.3-fpm.sock
# → srw-rw---- 1 www-data www-data 0 Oct 16 10:00 /run/php/php8.3-fpm.sock

# 3. Применение конфигурации без разрыва соединений
sudo systemctl reload nginx
# → (код возврата 0)

# 4. Проверка ответа через curl
curl -sI https://app.example.com/
# → HTTP/2 200
# → content-type: text/html; charset=UTF-8
```

---

### Сценарий 2: WordPress / CMS (Защищенная конфигурация и кэширование)

Конфигурация с изоляцией директорий загрузки пользователей (uploads), запретом исполнения скриптов вне ядра и оптимизацией статики.

```nginx
# /etc/nginx/sites-available/blog.example.com.conf

server {
    listen 443 ssl;
    http2 on;
    server_name blog.example.com;
    root /var/www/wordpress;
    index index.php;

    ssl_certificate     /etc/letsencrypt/live/blog.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/blog.example.com/privkey.pem;

    # 1. Запрет выполнения PHP в директории пользовательских загрузок (Security Hardening)
    location ~* ^/wp-content/uploads/.*\.php$ {
        deny all;
    }

    # 2. Защита служебных файлов ядра и конфигураций
    location = /wp-config.php {
        deny all;
    }
    location = /xmlrpc.php {
        deny all;
        access_log off;
        log_not_found off;
    }
    location ~ /\.(?!well-known) {
        deny all;
        access_log off;
        log_not_found off;
    }

    # 3. Маршрутизация WordPress
    location / {
        try_files $uri $uri/ /index.php?$args;
    }

    # 4. Обработка PHP через сокет
    location ~ \.php$ {
        try_files $uri =404;
        include fastcgi_params;
        fastcgi_pass unix:/run/php/php-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;

        fastcgi_buffer_size 16k;
        fastcgi_buffers 8 16k;
        fastcgi_read_timeout 60s;
    }

    # 5. Оптимизированная отдача медиа и шрифтов
    location ~* \.(webp|avif|css|js|png|jpg|jpeg|gif|ico|svg|woff2)$ {
        expires 365d;
        add_header Cache-Control "public, no-transform";
        log_not_found off;
    }
}
```

---

### Сценарий 3: Node.js / Go / Rust (Reverse Proxy с WebSocket и Upstream Keepalive)

Обеспечивает HTTP reverse proxying с пулом постоянных соединений (`keepalive`) и прозрачным обновлением протокола до WebSocket на одном домене.

```nginx
# /etc/nginx/conf.d/upstreams.conf (или контекст http)
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

upstream nodejs_backend {
    server 127.0.0.1:3000 max_fails=3 fail_timeout=10s;
    server 127.0.0.1:3001 backup;
    # Пул постоянных соединений между Nginx и Node.js
    keepalive 32;
}

# /etc/nginx/sites-available/api.example.com.conf
server {
    listen 443 ssl;
    http2 on;
    server_name api.example.com;

    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    # Стандартный REST API маршрут с Upstream Keepalive
    location /api/ {
        proxy_pass http://nodejs_backend;

        # Обязательные параметры для работы upstream keepalive
        proxy_http_version 1.1;
        proxy_set_header   Connection "";

        # Передача метаданных клиента
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # Таймауты для API
        proxy_connect_timeout 3s;
        proxy_send_timeout    15s;
        proxy_read_timeout    30s;

        # Буферизация для защиты бэкенда от медленных клиентов
        proxy_buffering on;
        proxy_buffer_size 8k;
        proxy_buffers 8 8k;
    }

    # WebSocket-маршрут (чат, котировки, телеметрия)
    location /ws/ {
        proxy_pass http://nodejs_backend;

        proxy_http_version 1.1;
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection $connection_upgrade;

        proxy_set_header   Host            $host;
        proxy_set_header   X-Real-IP       $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;

        # Отключение буферизации для мгновенной доставки сообщений
        proxy_buffering off;

        # Длительные таймауты для удержания дуплексного соединения
        proxy_connect_timeout 5s;
        proxy_send_timeout    3600s;
        proxy_read_timeout    3600s;
    }
}
```

#### Проверка WebSocket-рукопожатия
```bash
# Проверка HTTP Switching Protocols (101)
curl -i -N \
     -H "Connection: Upgrade" \
     -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Key: SGVsbG8sIHdvcmxkIQ==" \
     -H "Sec-WebSocket-Version: 13" \
     https://api.example.com/ws/
# → HTTP/1.1 101 Switching Protocols
# → Upgrade: websocket
# → Connection: Upgrade
```

---

### Сценарий 4: Python-приложения (WSGI / Gunicorn vs ASGI / Uvicorn)

#### Вариант 4.1: Gunicorn (WSGI для Django / Flask) через Unix Domain Socket
Классическая синхронная модель. Сокет создается Gunicorn в `/run/gunicorn/gunicorn.sock`.

```nginx
upstream django_app {
    server unix:/run/gunicorn/gunicorn.sock fail_timeout=0;
}

server {
    listen 443 ssl;
    http2 on;
    server_name django.example.com;

    ssl_certificate     /etc/ssl/certs/django.crt;
    ssl_certificate_key /etc/ssl/private/django.key;

    # Статика Django отдается напрямую Nginx (минуя Python)
    location /static/ {
        alias /var/www/django_project/static/;
        expires 30d;
        access_log off;
    }

    location /media/ {
        alias /var/www/django_project/media/;
        expires 30d;
        access_log off;
    }

    location / {
        proxy_pass http://django_app;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Буферизация и таймауты
        proxy_buffering on;
        proxy_buffer_size 16k;
        proxy_buffers 4 32k;
        proxy_read_timeout 60s;
    }
}
```

#### Вариант 4.2: Uvicorn (ASGI для FastAPI / Starlette)
Асинхронная модель с поддержкой долгоживущих соединений.

```nginx
upstream fastapi_app {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 443 ssl;
    http2 on;
    server_name fastapi.example.com;

    ssl_certificate     /etc/ssl/certs/fastapi.crt;
    ssl_certificate_key /etc/ssl/private/fastapi.key;

    location / {
        proxy_pass http://fastapi_app;
        proxy_http_version 1.1;

        # Поддержка заголовков обновления для ASGI WebSocket
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 120s;
    }
}
```

---

### Сценарий 5: gRPC-интеграция (HTTP/2 Cleartext и TLS)

Требует Nginx с модулем `ngx_http_grpc_module` и директивой `http2 on;`.
Поддерживаются схемы `grpc://` (незашифрованный HTTP/2 cleartext / h2c) и `grpcs://` (gRPC поверх TLS).

```nginx
upstream grpc_order_servers {
    server 127.0.0.1:50051;
    server 127.0.0.1:50052;
}

server {
    listen 443 ssl;
    http2 on;
    server_name grpc.example.com;

    ssl_certificate     /etc/letsencrypt/live/grpc.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/grpc.example.com/privkey.pem;

    # Маршрутизация по пакету и имени gRPC сервиса
    location /api.v1.OrderService/ {
        # Схема grpc:// для локального взаимодействия без повторного шифрования
        grpc_pass grpc://grpc_order_servers;

        # Передача служебных метаданных вызова
        grpc_set_header Host              $host;
        grpc_set_header X-Real-IP         $remote_addr;
        grpc_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;

        # Тюнинг таймаутов gRPC потоков
        grpc_connect_timeout 5s;
        grpc_send_timeout    60s;
        grpc_read_timeout    60s;

        # Размер буфера ответа
        grpc_buffer_size 16k;

        # Централизованная трансляция gRPC ошибок
        error_page 502 = /grpc_fallback;
    }

    location = /grpc_fallback {
        internal;
        default_type application/grpc;
        add_header grpc-status 14; # UNAVAILABLE
        add_header grpc-message "Backend service currently unavailable";
        return 204;
    }
}
```

#### Проверка через `grpcurl`
```bash
# Список методов удаленного сервиса
grpcurl -insecure grpc.example.com:443 list api.v1.OrderService
# → api.v1.OrderService.CreateOrder
# → api.v1.OrderService.GetOrder

# Вызов RPC-метода
grpcurl -insecure -d '{"order_id": "1001"}' grpc.example.com:443 api.v1.OrderService/GetOrder
# → {
#     "order_id": "1001",
#     "status": "APPROVED"
#   }
```

---

### Сценарий 6: Server-Sent Events (SSE) и потоковая передача (Streaming API)

Для передачи потоковых данных (логов, прогресса выполнения длительных фоновых задач, телеметрии) буферизация Nginx должна быть полностью отключена, иначе клиент не получит событий до заполнения системных буферов или закрытия потока бэкендом.

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name stream.example.com;

    ssl_certificate     /etc/ssl/certs/stream.crt;
    ssl_certificate_key /etc/ssl/private/stream.key;

    location /events/ {
        proxy_pass http://127.0.0.1:4000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # КРИТИЧЕСКИ ВАЖНО: полное отключение буферизации и кэша
        proxy_buffering off;
        proxy_cache off;

        # Отключение передачи в сжатом виде (gzip буферизует блоки перед отдачей)
        gzip off;

        # Защита от разрыва долгоживущего одностороннего потока
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;

        # Отключение сброса буферов на диск
        chunked_transfer_encoding off;
    }
}
```

#### Проверка потоковой отдачи
```bash
# Флаг -N отключает буферизацию в самом клиенте curl
curl -N -sI https://stream.example.com/events/
# → HTTP/2 200
# → content-type: text/event-stream
# → cache-control: no-cache
```

---

### Сценарий 7: SCGI (Simple Common Gateway Interface)

Применяется для взаимодействия с сервисами, реализующими протокол SCGI (например, BitTorrent-клиент rTorrent).

```nginx
server {
    listen 127.0.0.1:8080;
    server_name localhost;

    location /RPC2 {
        include scgi_params;
        scgi_pass unix:/run/rtorrent/rpc.sock;

        # Ограничение доступа только с локального хоста
        allow 127.0.0.1;
        deny all;

        scgi_read_timeout 30s;
        scgi_send_timeout 30s;
    }
}
```

---

## Операции и команды

### Валидация и применение конфигурации

```bash
# 1. Проверка корректности синтаксиса всех подключенных файлов конфигурации
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Вывод объединенной конфигурации с раскрытием всех include и поиском шлюзовых директив
sudo nginx -T | grep -n "fastcgi_pass\|proxy_pass\|uwsgi_pass\|grpc_pass\|scgi_pass"
# → 48:        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
# → 112:       proxy_pass http://nodejs_backend;
# → 184:       grpc_pass grpc://grpc_order_servers;

# 3. Безопасная перезагрузка конфигурации без разрыва клиентских соединений (Zero-Downtime Reload)
sudo systemctl reload nginx
# Проверка кода возврата
echo $?
# → 0

# Альтернативная прямая отправка сигнала HUP процессу master
sudo nginx -s reload
# → signal processed
```

### Диагностика сокетов и бэкенд-процессов

```bash
# 1. Проверка существования, типа и прав UDS-сокета FastCGI
stat -c "%A %U:%G %N" /run/php/php8.3-fpm.sock
# → srw-rw---- www-data:www-data /run/php/php8.3-fpm.sock

# 2. Проверка состояния очереди соединений к Unix domain сокетам ядра
ss -xlnp | grep -E "php|gunicorn|uwsgi"
# → u_str LISTEN 0 511 /run/php/php8.3-fpm.sock 12345 * 0 users:(("php-fpm8.3",pid=1420,fd=7))

# 3. Проверка прослушивания локальных TCP портов бэкендов
ss -tulpn | grep -E ":3000|:50051|:8000"
# → tcp LISTEN 0 128 127.0.0.1:3000 0.0.0.0:* users:(("node",pid=2150,fd=18))
# → tcp LISTEN 0 128 127.0.0.1:50051 0.0.0.0:* users:(("order-svc",pid=3120,fd=3))

# 4. Проверка системного лимита очереди сокетов ядра (backlog)
cat /proc/sys/net/core/somaxconn
# → 4096
```

### Smoke-тестирование и верификация шлюзов

```bash
# 1. Проверка сквозного кода HTTP и времени выполнения запроса (TTFB)
curl -s -o /dev/null -w "HTTP: %{http_code} | TTFB: %{time_starttransfer}s | Total: %{time_total}s\n" https://app.example.com/
# → HTTP: 200 | TTFB: 0.042s | Total: 0.045s

# 2. Проверка трансляции метаданных проксирования в ответных заголовках
curl -sI https://api.example.com/api/v1/health | grep -iE "x-real-ip|x-forwarded|server"
# → server: nginx
# → x-matched-location: /api/

# 3. Прямая проверка работоспособности PHP-FPM сокета в обход веб-сервера (пакет libfcgi0ldbl / fcgiwrap)
SCRIPT_NAME=/ping SCRIPT_FILENAME=/ping REQUEST_METHOD=GET cgi-fcgi -bind -connect /run/php/php8.3-fpm.sock
# → X-Powered-By: PHP/8.3.6
# → Content-type: text/plain;charset=UTF-8
# → pong
```

### Управление правами и контекстом безопасности (Sysadmin)

```bash
# 1. Назначение владельца веб-директории и прав доступа
sudo chown -R www-data:www-data /var/www/html
sudo find /var/www/html -type d -exec chmod 755 {} \;
sudo find /var/www/html -type f -exec chmod 644 {} \;

# 2. Запрет на запись в корневые директории для всех пользователей
sudo chmod -R go-w /var/www/html

# 3. Добавление пользователя nginx в группу бэкенда при раздельных правах
# Например, если Nginx работает как 'nginx', а PHP-FPM как 'www-data':
sudo usermod -aG www-data nginx

# 4. Проверка и переключение булевых флагов SELinux (RHEL / Rocky / AlmaLinux)
# Разрешение Nginx устанавливать сетевые TCP-соединения к локальным бэкендам
sudo getsebool httpd_can_network_connect
# → httpd_can_network_connect --> on
sudo setsebool -P httpd_can_network_connect on

# 5. Проверка профиля AppArmor для процесса Nginx (Ubuntu / Debian)
sudo aa-status | grep nginx
# → /usr/sbin/nginx (enforce)
```

### Ротация логов и очистка буферов

```bash
# 1. Проверка конфигурационного файла утилиты logrotate
sudo logrotate -d /etc/logrotate.d/nginx
# → reading config file /etc/logrotate.d/nginx
# → ... syntax ok

# 2. Принудительный запуск ротации журналов
sudo logrotate -f /etc/logrotate.d/nginx

# 3. Поиск незакрытых удаленных дескрипторов временных буферов прокси (unlinked temp files)
lsof +L1 | grep nginx | grep proxy_temp
# → (при нормальной работе вывод пуст или содержит краткосрочные активные дескрипторы)
```

---

## Диагностика и устранение неисправностей

### Типовые ошибки интеграции и пошаговые решения

| Код / Симптом | Типичная причина | Диагностика в логах | Пошаговое решение |
| :--- | :--- | :--- | :--- |
| **502 Bad Gateway** | UDS-сокет бэкенда не существует или процесс упал | `connect() to unix:/run/php/php8.3-fpm.sock failed (2: No such file or directory)` | 1. Проверить статус демона: `systemctl status php8.3-fpm`.<br>2. Проверить путь директивы `fastcgi_pass` командой `ls -la /run/php/`. |
| **502 Bad Gateway** | Недостаточно прав для чтения/записи в UDS-сокет | `connect() to unix:/tmp/gunicorn.sock failed (13: Permission denied)` | 1. Проверить пользователя Nginx: `ps aux \| grep nginx`.<br>2. Назначить группу: `chown :www-data /run/gunicorn.sock && chmod 660 /run/gunicorn.sock`.<br>3. Перенести сокет из `/tmp` в `/run/` (в systemd включен `PrivateTmp=true`). |
| **502 Bad Gateway** | Бэкенд не слушает указанный TCP порт | `connect() failed (111: Connection refused) while connecting to upstream` | 1. Проверить сокеты: `ss -tulpn \| grep 3000`.<br>2. Убедиться, что бэкенд запущен и привязан к `127.0.0.1` или `0.0.0.0`, а не к внешнему интерфейсу. |
| **502 Bad Gateway** | Бэкенд аварийно упал во время генерации ответа | `recv() failed (104: Connection reset by peer) while reading response header from upstream` | 1. Изучить журнал приложения (OOM killer, segfault в расширениях PHP).<br>2. Проверить лимиты памяти в `php.ini` (`memory_limit`) или `systemd` cgroup. |
| **504 Gateway Timeout** | Время ответа бэкенда превысило лимит веб-сервера | `upstream timed out (110: Connection timed out) while reading response header from upstream` | 1. Найти медленный запрос в slowlog бэкенда.<br>2. Увеличить `proxy_read_timeout` / `fastcgi_read_timeout` для тяжелых location.<br>3. Оптимизировать блокирующие SQL-запросы или внешние HTTP-вызовы. |
| **upstream sent too big header** | Размер HTTP-заголовков бэкенда (большие cookies, JWT) превысил буфер | `upstream sent too big header while reading response header from upstream, client: ...` | Увеличить размер начального буфера в целевом `location`:<br>`proxy_buffer_size 32k;` или `fastcgi_buffer_size 32k;`. |
| **an upstream response is buffered to a temporary file** | Ответ бэкенда не помещается в буферы оперативной памяти | `an upstream response is buffered to a temporary file /var/cache/nginx/proxy_temp/1/00/...` | 1. Увеличить объем буферов в памяти: `proxy_buffers 16 32k; proxy_busy_buffers_size 64k;`.<br>2. Либо отключить буферизацию для тяжелых файлов: `proxy_buffering off;`. |
| **Primary script unknown** (FastCGI) | Неверно передан параметр `SCRIPT_FILENAME` в PHP-FPM | В логе Nginx: 404/403. В теле ответа: `File not found.` или `Primary script unknown` | 1. Проверить `fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;`.<br>2. Убедиться, что `root` задан в контексте `server` или `location` и доступен процессу PHP-FPM. |
| **WebSocket 400 / 502 Failure** | Заголовки Upgrade не переданы или соединение закрыто | `WebSocket connection failed: Error during WebSocket handshake: Unexpected response code: 400` | 1. Добавить блок `map $http_upgrade $connection_upgrade`.<br>2. Указать `proxy_http_version 1.1;`.<br>3. Передать `proxy_set_header Upgrade $http_upgrade;` и `proxy_set_header Connection $connection_upgrade;`. |
| **413 Request Entity Too Large** | Тело POST/PUT запроса клиента больше лимита Nginx | `client intended to send too large body: 15728640 bytes` | Увеличить лимит в контексте `location` или `server`:<br>`client_max_body_size 64M;`. |

### Диагностические команды и трассировка

```bash
# 1. Потоковый мониторинг только критических ошибок шлюзов в реальном времени
tail -f /var/log/nginx/error.log | grep -E "upstream|connect\(\)|timed out|too big"

# 2. Трассировка системных вызовов активного worker-процесса Nginx при общении с бэкендом
# Определение PID рабочего процесса
WORKER_PID=$(pgrep -f "nginx: worker process" | head -n1)
# Трассировка сетевых вызовов connect, read, write, recvfrom
sudo strace -p $WORKER_PID -e trace=network,read,write -s 256

# 3. Перехват локального TCP-трафика на loopback интерфейсе (например, порт 3000)
sudo tcpdump -i lo -nn -s 0 -A "tcp port 3000 and (((ip[2:2] - ((ip[0]&0xf)<<2)) - ((tcp[12:1] & 0xf0)>>2)) != 0)"
```

---

## Лучшие практики

### Эксплуатация и надежность (SRE / Sysadmin)

1. **Обязательная проверка перед применением (`nginx -t`).** Любое изменение конфигурации должно тестироваться вызовом `nginx -t` в рамках автоматизированных конвейеров или ручных операций. При ошибке синтаксиса текущий рабочий процесс продолжит обслуживание трафика без сбоев.
2. **Использование пулов соединений (`keepalive`).** Для любого upstream с протоколами HTTP/1.1 или FastCGI настраивайте пул `keepalive` в контексте `upstream`, уменьшая задержку на $1\text{--}3 \times \text{RTT}$ и предотвращая исчерпание эфемерных портов в Linux.
3. **Согласование таймаутов.** Настраивайте сквозную цепочку таймаутов так, чтобы бэкенд гарантированно прерывал выполнение зависшего запроса раньше, чем Nginx разорвет соединение по `proxy_read_timeout` / `fastcgi_read_timeout`.
4. **Контроль размеров буферов.** Не устанавливайте чрезмерно большие значения `proxy_buffers` глобально в блоке `http`. Каждый открытый запрос резервирует эти буферы в памяти воркера; при всплеске трафика в 10 000 соединений это приведет к исчерпанию оперативной памяти (OOM Killer). Тюнинг буферов должен производиться точечно в целевых блоках `location`.
5. **Безопасное размещение сокетов.** Никогда не создавайте Unix domain сокеты в общедоступной директории `/tmp`, так как современные дистрибутивы Linux изолируют службы через `PrivateTmp=true` в systemd unit-файлах. Размещайте сокеты в `/run/<имя_демона>/` или `/var/run/`.
6. **Процедура отката (Rollback plan).** Перед ручным редактированием конфигурации создавайте резервную копию файла с отметкой времени:
   ```bash
   sudo cp /etc/nginx/sites-available/app.conf /etc/nginx/sites-available/app.conf.bak.$(date +%Y%m%d%H%M%S)
   ```
   В случае сбоя восстановите файл и перезагрузите Nginx:
   ```bash
   sudo cp /etc/nginx/sites-available/app.conf.bak.<TIMESTAMP> /etc/nginx/sites-available/app.conf
   sudo nginx -t && sudo systemctl reload nginx
   ```

### Безопасность (Hardening)

1. **Защита от передачи несуществующих файлов в FastCGI (`try_files $uri =404;`).** Без этой проверки Nginx передаст любой URI вида `/uploads/avatar.jpg/some.php` в PHP-FPM. Если в PHP включен `cgi.fix_pathinfo=1`, интерпретатор выполнит код из файла `avatar.jpg`, что приводит к удаленному выполнению произвольного кода (RCE).
2. **Блокировка доступа к служебным каталогам и метаданным:**
   ```nginx
   location ~ /\.(?!well-known) {
       deny all;
       access_log off;
       log_not_found off;
   }
   ```
3. **Сокрытие заголовков идентификации бэкенда:**
   ```nginx
   proxy_hide_header X-Powered-By;
   proxy_hide_header Server;
   fastcgi_hide_header X-Powered-By;
   ```
4. **Ограничение опасных HTTP-методов через `limit_except`:**
   ```nginx
   location /api/public/ {
       limit_except GET HEAD OPTIONS {
           deny all;
       }
       proxy_pass http://backend_pool;
   }
   ```

### Наблюдаемость (Observability)

1. **Включение метрик upstream в журнал доступа.** Стандартный лог `combined` не содержит сведений о производительности бэкендов. Добавьте формат с переменными задержек:
   ```nginx
   log_format upstream_perf '$remote_addr - $remote_user [$time_local] "$request" '
                            '$status $body_bytes_sent "$http_referer" "$http_user_agent" '
                            'rt=$request_time uct="$upstream_connect_time" '
                            'uht="$upstream_header_time" urt="$upstream_response_time" '
                            'addr="$upstream_addr" ustatus="$upstream_status"';
   ```
2. **Заголовок трассировки выбранного location.** Для быстрой отладки в средах staging/production используйте:
   ```nginx
   add_header X-Matched-Location $upstream_addr always;
   ```

---

## Дополнительная информация

### См. также

- **[Директива location: основы и приоритеты](./basics.md)** — точные правила сопоставления URI и порядок применения модификаторов.
- **[Директива location: лучшие практики и отладка](./best_practices.md)** — плоская структура, наследование директив, ограничение частоты запросов.
- **[Директива location: отдача статических файлов](./serving_files.md)** — директивы `root`, `alias`, оптимизация `sendfile` и `tcp_nopush`.
- **[Директива location: внутренняя маршрутизация](./internal_routing.md)** — директивы `try_files`, `error_page`, именованные локации и `X-Accel-Redirect`.
- **[Практическая конфигурация балансировки](../../Proxy/Load_Balancing/practical_configuration.md)** — расширенные сценарии upstream, алгоритмы распределения нагрузки и failover.
- **[Upstream Keepalive и Connection Pooling](../../../Concepts/web_performance/upstream_keepalive_and_pooling.md)** — математика сетевых задержек, TIME_WAIT сокеты и тюнинг пулов соединений.
- **[uWSGI, SCGI, WSGI, FastCGI: интерфейсы бэкендов](../../../Concepts/uwsgi_scgi.md)** — сравнительный анализ шлюзовых интерфейсов, бинарных фреймов и режимов Emperor/Harakiri.
- **[FastCGI и PHP-FPM в Angie](../../../Angie/angie-fastcgi-php-fpm.md)** — архитектура пулов FastCGI и расширенные директивы в сервере Angie.
- **[Настройка и тюнинг PHP-FPM](../../../PHP/php-fpm-tuning.md)** — расчет процессов пула, директивы `pm = dynamic/ondemand` и цепочки таймаутов.
- **[Мониторинг PHP-FPM](../../../PHP/php-fpm-monitoring.md)** — статусная страница FPM, slowlog и метрики производительности.
- **[Диагностика Nginx](../../Operations/nginx_troubleshooting.md)** — алгоритмы анализа аварийных ситуаций и системный траблшутинг.
