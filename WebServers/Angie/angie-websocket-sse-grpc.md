# Проксирование WebSocket, SSE и gRPC в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

*   **WebSocket (RFC 6455)** — двунаправленный (full-duplex) протокол постоянной связи поверх одного TCP-соединения. Инициализируется стандартным HTTP/1.1-запросом рукопожатия (Handshake) с заголовками `Upgrade: websocket` и `Connection: Upgrade`, после чего веб-сервер возвращает код `101 Switching Protocols` и переключает сокет в режим двустороннего туннелирования сырых кадров (frames). Применяется для систем обмена сообщениями, торговых терминалов, интерактивных дашбордов и real-time уведомлений.
*   **Server-Sent Events (SSE / W3C EventSource)** — однонаправленный (сервер → клиент) механизм непрерывной доставки событий по протоколам HTTP/1.1 или HTTP/2. Клиент открывает постоянное GET-соединение с заголовком `Accept: text/event-stream`; сервер удерживает поток открытым и передает текстовые фрагменты с разделителем `\n\n`. Включает встроенный в браузер механизм автопереподключения с отслеживанием `Last-Event-ID`.
*   **gRPC (Google Remote Procedure Call)** — высокопроизводительный RPC-фреймворк с открытым исходным кодом, использующий Protocol Buffers (Protobuf) для сериализации структурированных данных и работающий строго поверх HTTP/2 (или HTTP/3). Поддерживает четыре типа взаимодействия: Unary (одиночный запрос/ответ), Server Streaming, Client Streaming и Bidirectional Streaming.
*   **Модуль `ngx_http_grpc_module`** — встроенный модуль Angie для проксирования gRPC-вызовов к бэкендам по бинарному протоколу HTTP/2 с поддержкой мультиплексирования потоков, трансляции метаданных и завершающих заголовков (trailers).
*   **`grpc://` и `grpcs://`** — URI-схемы модуля gRPC-проксирования. Схема `grpc://` транслирует вызовы в незашифрованный HTTP/2 (h2c — HTTP/2 Cleartext) к апстриму, а `grpcs://` использует защищенный TLS-канал с согласованием ALPN `h2`.
*   **CSWSH (Cross-Site WebSocket Hijacking)** — атака класса CSRF на этапе WebSocket Handshake, при которой вредоносный сайт инициирует открытие веб-сокета к целевому приложению от имени аутентифицированного пользователя из-за отсутствия строгой валидации заголовка `Origin` на стороне прокси или приложения.
*   **Тихий сброс соединений (Silent Connection Drop)** — потеря связности в долгоживущих TCP-сессиях без отправки пакетов `FIN` или `RST`, вызванная тайм-аутами состояний в таблицах трансляции сетевых адресов (Stateful NAT, conntrack) или межсетевых экранах при отсутствии постоянного трафика или keepalive-проб.

---

## Архитектура и принцип работы

### 1. Механизм туннелирования WebSocket

В отличие от стандартного HTTP-проксирования, где Angie парсит каждый входящий запрос и исходящий ответ, обработка WebSocket разделена на две принципиально разные фазы:

```
[ Клиент ]                  [ Angie ]                 [ Upstream ]
    │                           │                          │
    ├── 1. HTTP GET /ws ───────►│                          │
    │   Upgrade: websocket      ├── 2. HTTP GET /ws ──────►│
    │   Connection: Upgrade     │   Upgrade: websocket     │
    │                           │   Connection: upgrade    │
    │                           │                          │
    │                           │◄── 3. 101 Switching ─────┤
    │◄── 4. 101 Switching ──────┤                          │
    │                           │                          │
════╪═══════════════════════════╪══════════════════════════╪══════════════════
    │   ФАЗА ДВУНАПРАВЛЕННОГО БИНАРНОГО ТУННЕЛЯ (Raw Stream Pass-through)  │
    │◄─────────────────────────►│◄────────────────────────►│
    │    Кадры WebSocket        │    Кадры WebSocket       │
    │    (Text, Binary, Ping)   │    (Text, Binary, Pong)  │
```

1. **Фаза согласования (Handshake):** Клиент передает HTTP/1.1 запрос с заголовками `Upgrade: websocket`, `Connection: Upgrade`, уникальным ключом `Sec-WebSocket-Key` и версией `Sec-WebSocket-Version: 13`.
2. **Трансляция заголовков прокси:** Angie отправляет запрос бэкенду. Для корректного прохождения рукопожатия требуется принудительно задать протокол `proxy_http_version 1.1;` (так как по умолчанию прокси-модуль использует HTTP/1.0, закрывающий сокет после ответа) и пробросить значения через директивы `proxy_set_header Upgrade` и `proxy_set_header Connection`.
3. **Фиксация переключения (Switching Protocols):** Получив от бэкенда статус `101 Switching Protocols`, Angie отправляет его клиенту и немедленно выводит сокет из стандартного HTTP-конвейера.
4. **Трансляция кадров (Raw Pass-through):** Обработчик переключается в режим прозрачного двустороннего копирования байтов. Angie не декодирует полезную нагрузку WebSocket-фреймов. На этой фазе управление переходит к тайм-аутам `proxy_read_timeout` и `proxy_send_timeout`. Если в течение интервала `proxy_read_timeout` ни клиент, ни бэкенд не передали ни одного байта данных или контрольного фрейма (Ping/Pong), Angie принудительно разрывает соединение.

### 2. Специфика проксирования Server-Sent Events (SSE)

SSE работает поверх стандартного долгоживущего HTTP GET-запроса, но имеет критические архитектурные особенности буферизации:

*   **Проблема прокси-буферизации (`proxy_buffering`):** По умолчанию в Angie включена буферизация ответов бэкенда (`proxy_buffering on;`). Сервер накапливает данные во внутренних буферах (`proxy_buffers`), стремясь освободить процесс бэкенда. При потоковой передаче SSE это приводит к полному зависанию доставки: клиент не получает событий до тех пор, пока буфер (например, 4 КБ или 8 КБ) не заполнится целиком.
*   **Отключение буферизации:** Для SSE-эндпоинтов необходимо гарантированно отключать буферизацию директивой `proxy_buffering off;` либо на стороне бэкенда с помощью заголовка ответа `X-Accel-Buffering: no`. При этом каждый фрагмент потока сбрасывается в клиентский сокет немедленно.
*   **Влияние алгоритмов сжатия (Gzip/Brotli):** Модули потокового сжатия сжимают трафик блоками. Если для MIME-типа `text/event-stream` включен gzip, события будут удерживаться компрессором. Для SSE-локаций сжатие должно быть отключено (`gzip off;`).
*   **Обрыв со стороны клиента (`proxy_ignore_client_abort`):** По умолчанию (`off`), когда пользователь закрывает вкладку браузера или разрывает сетевое соединение, Angie фиксирует событие в `epoll`, немедленно закрывает сокет к апстриму и прерывает фоновую генерацию событий.

### 3. Механизм работы gRPC поверх HTTP/2 и HTTP/3

Модуль `ngx_http_grpc_module` реализует шлюзование между клиентскими HTTP/2 (или HTTP/3) потоками и бэкенд-серверами gRPC:

```
[ gRPC Client ]                                [ Angie ]                              [ gRPC Backend ]
       │                                           │                                         │
       ├─── TLS + HTTP/2 (h2) ────────────────────►│                                         │
       │    HEADERS: path=/Service/Method          ├─── HTTP/2 (h2c или grpcs) ─────────────►│
       │    DATA: Protobuf payload                 │    HEADERS: path=/Service/Method        │
       │                                           │    DATA: Protobuf payload               │
       │                                           │                                         │
       │                                           │◄── HEADERS: :status=200 ────────────────┤
       │◄── HEADERS: :status=200 ──────────────────┤    DATA: Protobuf response              │
       │◄── DATA: Protobuf response ───────────────┤                                         │
       │                                           │◄── HEADERS (Trailers): ─────────────────┤
       │◄── HEADERS (Trailers): ───────────────────┤      grpc-status: 0                     │
       │      grpc-status: 0                       │      grpc-message: OK                   │
```

*   **Трансляция протоколов:** Клиент обязан подключаться по протоколу HTTP/2 (директива `http2 on;` в блоке `server`). Angie декодирует входящие кадры HTTP/2 и передает их в сторону бэкенда через директиву `grpc_pass`.
*   **HTTP/3 (QUIC) на входе и выходе:** Angie полноценно поддерживает прием входящего gRPC-трафика по HTTP/3 (`http3 on;`) с дальнейшей трансляцией в gRPC по HTTP/2 к бэкенду. Кроме того, Angie способна взаимодействовать с апстримами по протоколу HTTP/3 через `proxy_http_version 3.0;`.
*   **Мультиплексирование и пулы постоянных соединений (Connection Pooling):** В gRPC множество параллельных RPC-вызовов упаковываются в независимые потоки (streams) внутри одного TCP-соединения. Angie поддерживает пул постоянных HTTP/2 соединений к апстримам через директиву `keepalive` в блоке `upstream`. Это исключает накладные расходы на постоянный TCP/TLS-handshake между прокси и микросервисами.
*   **Трейлеры (HTTP Trailers):** В архитектуре gRPC статус завершения операции передается не в начальных заголовках ответа, а в завершающих трейлерах (`grpc-status`, `grpc-message`), следующих за телом ответа. Angie прозрачно проксирует трейлеры и предоставляет переменную `$sent_http_grpc_status` для анализа кодов завершения в журналах.

---

## Практические сценарии и конфигурация

### Сценарий 1: Отказоустойчивый WebSocket-шлюз с защитой от DoS и CSWSH

Конфигурация включает разделение обычных HTTP-запросов и Upgrade-соединений, валидацию домена `Origin`, ограничение интенсивности подключений и распределение сессий.

```nginx
# /etc/angie/http.d/websocket_gateway.conf

# 1. Корректная обработка заголовков переключения протокола
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

# 2. Белый список разрешенных доменов для защиты от CSWSH
map $http_origin $ws_origin_allowed {
    default                         0;
    "~^https?://(www\.)?example\.com(:[0-9]+)?$" 1;
    "~^https?://admin\.example\.com(:[0-9]+)?$"  1;
    ""                              1; # Разрешить прямые небраузерные клиенты (мобильные приложения, curl)
}

# 3. Зоны ограничения частоты рукопожатий и параллельных сокетов
limit_req_zone $binary_remote_addr zone=ws_handshake_limit:10m rate=10r/s;
limit_conn_zone $binary_remote_addr zone=ws_conn_per_ip:10m;

upstream ws_cluster {
    zone ws_cluster 256k;
    
    # Хеширование по IP для привязки клиента к конкретному ноду кластера
    hash $binary_remote_addr consistent;

    server 10.0.10.11:8080 max_fails=3 fail_timeout=10s;
    server 10.0.10.12:8080 max_fails=3 fail_timeout=10s;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name ws.example.com;

    http2 on;

    ssl_certificate /etc/angie/ssl/ws.example.com.crt;
    ssl_certificate_key /etc/angie/ssl/ws.example.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Зона мониторинга Angie
    status_zone ws_gateway;

    location /socket.io/ {
        # Валидация Origin
        if ($ws_origin_allowed = 0) {
            return 403;
        }

        # Защита от перегрузки сокетов воркера
        limit_req zone=ws_handshake_limit burst=20 nodelay;
        limit_conn ws_conn_per_ip 50;

        proxy_pass http://ws_cluster;
        proxy_http_version 1.1;

        # Проброс обязательных заголовков Upgrade
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        # Передача служебных клиентских метаданных
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Таймауты для удержания долгоживущего туннеля (1 час бездействия)
        proxy_connect_timeout 5s;
        proxy_send_timeout 3600s;
        proxy_read_timeout 3600s;

        # Отключение буферизации прокси для снижения задержек
        proxy_buffering off;
    }
}
```

### Сценарий 2: Потоковый Server-Sent Events (SSE) эндпоинт

Конфигурация оптимизирована для передачи потоков телеметрии, уведомлений и системных логов без задержек и накопления буферов.

```nginx
# /etc/angie/http.d/sse_streaming.conf

upstream sse_backend_cluster {
    zone sse_cluster 128k;
    server 10.0.20.15:9000;
    server 10.0.20.16:9000;

    # Пул постоянных HTTP/1.1 соединений к бэкенду
    keepalive 32;
}

server {
    listen 443 ssl;
    server_name stream.example.com;

    http2 on;

    ssl_certificate /etc/angie/ssl/stream.example.com.crt;
    ssl_certificate_key /etc/angie/ssl/stream.example.com.key;

    location /api/v1/events/ {
        proxy_pass http://sse_backend_cluster;
        proxy_http_version 1.1;

        # Сброс заголовка Connection для активации пула keepalive апстрима
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # КРИТИЧЕСКИ ВАЖНО: отключение буферизации и кэширования
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header X-Accel-Buffering no;

        # Отключение сжатия (gzip/brotli), чтобы события не удерживались компрессором
        gzip off;

        # Принудительное закрытие сессии бэкенда при отключении клиента
        proxy_ignore_client_abort off;

        # Допустимый интервал между передачей очередного события (10 минут)
        proxy_connect_timeout 5s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;

        # Заголовки ответа для браузера
        add_header Cache-Control "no-cache, no-transform";
        add_header X-Accel-Buffering "no";
    }
}
```

### Сценарий 3: gRPC API Gateway с балансировкой и пулом HTTP/2 соединений

Маршрутизация gRPC-методов к изолированным группам микросервисов с контролем повторных попыток (retries) и TCP keepalive.

```nginx
# /etc/angie/http.d/grpc_gateway.conf

# Формат лога с фиксацией gRPC-статусов
log_format grpc_detailed escape=default
    '$remote_addr - $remote_user [$time_local] "$request" '
    'status=$status grpc_status=$sent_http_grpc_status '
    'upstream_status=$upstream_status rt=$request_time '
    'urt=$upstream_response_time up="$upstream_addr"';

upstream billing_grpc_cluster {
    zone billing_grpc 256k;
    server 10.0.30.21:50051 max_fails=2 fail_timeout=5s;
    server 10.0.30.22:50051 max_fails=2 fail_timeout=5s;

    # Пул постоянных HTTP/2 соединений к апстримам
    keepalive 16;
    keepalive_time 1h;
    keepalive_timeout 300s;
}

server {
    listen 50051 ssl;
    server_name grpc.example.com;

    # Обязательно: включение HTTP/2 для входящего трафика
    http2 on;

    ssl_certificate /etc/angie/ssl/grpc.example.com.crt;
    ssl_certificate_key /etc/angie/ssl/grpc.example.com.key;
    ssl_protocols TLSv1.3;

    access_log /var/log/angie/grpc_access.log grpc_detailed;
    status_zone grpc_public_gateway;

    # Маршрутизация на уровне пакета/сервиса Protobuf
    location /billing.PaymentService/ {
        grpc_pass grpc://billing_grpc_cluster;

        # Защита соединений от сброса промежуточными межсетевыми экранами
        grpc_socket_keepalive on;

        # Размер буфера ответа gRPC
        grpc_buffer_size 32k;

        # Таймауты операций
        grpc_connect_timeout 2s;
        grpc_send_timeout 30s;
        grpc_read_timeout 30s;

        # Политика повторных попыток только для безопасных/идемпотентных сценариев
        grpc_next_upstream error timeout invalid_header http_502 http_503;
        grpc_next_upstream_tries 3;
        grpc_next_upstream_timeout 5s;

        # Проброс заголовков авторизации и трассировки
        grpc_set_header Host $host;
        grpc_set_header X-Real-IP $remote_addr;
        grpc_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        grpc_set_header X-Request-ID $request_id;
    }
}
```

### Сценарий 4: gRPC с взаимной TLS-аутентификацией (mTLS / `grpcs://`)

Организация безопасного шифрованного взаимодействия между Angie и внутренними gRPC-микросервисами в закрытом сетевом контуре.

```nginx
# /etc/angie/http.d/grpcs_secure_backend.conf

upstream secure_auth_grpc {
    zone secure_auth 128k;
    server auth-node1.internal.net:50052;
    server auth-node2.internal.net:50052;
    keepalive 8;
}

server {
    listen 443 ssl;
    server_name auth-api.example.com;

    http2 on;

    ssl_certificate /etc/angie/ssl/auth-api.example.com.crt;
    ssl_certificate_key /etc/angie/ssl/auth-api.example.com.key;

    location /auth.TokenService/ {
        # Схема grpcs:// для инициации TLS-рукопожатия к апстриму
        grpc_pass grpcs://secure_auth_grpc;

        # Клиентский сертификат Angie для авторизации перед апстримом (mTLS)
        grpc_ssl_certificate /etc/angie/ssl/angie_grpc_client.crt;
        grpc_ssl_certificate_key /etc/angie/ssl/angie_grpc_client.key;

        # Валидация подлинности сертификата бэкенда
        grpc_ssl_verify on;
        grpc_ssl_trusted_certificate /etc/angie/ssl/internal_ca_root.crt;
        grpc_ssl_verify_depth 2;

        # Проверка соответствия имени хоста (SNI)
        grpc_ssl_server_name on;
        grpc_ssl_name auth-node.internal.net;

        grpc_ssl_protocols TLSv1.3;
        grpc_ssl_ciphers HIGH:!aNULL:!MD5;

        grpc_read_timeout 15s;
        grpc_send_timeout 15s;
    }
}
```

### Сценарий 5: Смешанный хост (REST API + WebSocket + SSE + gRPC)

Конфигурация, совмещающая обслуживание статических файлов, классического REST API, потоков событий, веб-сокетов и gRPC в едином виртуальном сервере без конфликтов буферизации.

```nginx
# /etc/angie/http.d/unified_portal.conf

map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name app.example.com;

    http2 on;

    ssl_certificate /etc/angie/ssl/app.example.com.crt;
    ssl_certificate_key /etc/angie/ssl/app.example.com.key;

    # 1. Обычный REST API (стандартная буферизация включена)
    location /api/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering on;
        proxy_buffers 8 16k;
        proxy_read_timeout 30s;
    }

    # 2. WebSocket-канал для уведомлений
    location /ws/ {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_buffering off;
        proxy_read_timeout 86400s; # 24 часа
    }

    # 3. Server-Sent Events для ленты событий
    location /events/ {
        proxy_pass http://127.0.0.1:8082;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        gzip off;
        proxy_read_timeout 300s;
    }

    # 4. Внутренний gRPC микросервис
    location /analytics.EventCollector/ {
        grpc_pass grpc://127.0.0.1:50051;
        grpc_read_timeout 10s;
        grpc_send_timeout 10s;
    }
}
```

### Сценарий 6: Управление долгоживущими соединениями при Graceful Reload

При обновлении конфигурации или бинарных файлов Angie рабочие процессы старого поколения переходят в режим `shutting down`. Долгоживущие WebSocket и gRPC стримы удерживают воркер в памяти до бесконечности, если не настроен принудительный тайм-аут.

```nginx
# /etc/angie/angie.conf (контекст main)

user angie;
worker_processes auto;
worker_rlimit_nofile 262144;

# Ограничение времени жизни завершающихся воркеров при reload или остановке
worker_shutdown_timeout 60s;

events {
    worker_connections 65536;
    use epoll;
    multi_accept on;
}
```

Синхронизация с системным менеджером systemd во избежание сброса соединений сигналом `SIGKILL`:

```ini
# /etc/systemd/system/angie.service.d/timeout.conf
[Service]
# TimeoutStopSec должен превышать worker_shutdown_timeout минимум на 15 секунд
TimeoutStopSec=75s
```

---

## Операции, диагностика и мониторинг

### 1. Проверка синтаксиса и перезагрузка

```bash
# Валидация всей цепочки конфигурации с раскрытием директив
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Бесшовное применение настроек без разрыва активных соединений
angie -s reload
```

### 2. Тестирование WebSocket

Ручная проверка рукопожатия (Upgrade Handshake) через `curl`:

```bash
curl --include --no-buffer \
     --header "Connection: Upgrade" \
     --header "Upgrade: websocket" \
     --header "Sec-WebSocket-Version: 13" \
     --header "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
     --header "Origin: https://example.com" \
     https://ws.example.com/socket.io/
# → HTTP/1.1 101 Switching Protocols
# → Upgrade: websocket
# → Connection: upgrade
# → Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
```

Интерактивное тестирование отправки текстовых кадров с помощью утилиты `websocat`:

```bash
# Установка websocat (при необходимости) и подключение к WSS-эндпоинту
websocat --origin https://example.com wss://ws.example.com/socket.io/
# → Ввод: {"action":"ping"}
# → Вывод: {"action":"pong","timestamp":1728938400}
```

### 3. Тестирование Server-Sent Events

Проверка немедленной доставки чанков без буферизации с помощью флага `--no-buffer` (`-N`):

```bash
curl -N -v -H "Accept: text/event-stream" https://stream.example.com/api/v1/events/
# → < HTTP/1.1 200 OK
# → < Content-Type: text/event-stream
# → < Cache-Control: no-cache, no-transform
# → < X-Accel-Buffering: no
# → event: ping
# → data: {"time": "2026-10-14T21:00:00Z"}
# → (пауза 2 сек)
# → event: message
# → data: {"id": 101, "payload": "alert"}
```

### 4. Тестирование gRPC вызовов

Инспекция сервисов и выполнение удаленных вызовов через CLI-утилиту `grpcurl`:

```bash
# Просмотр зарегистрированных сервисов через gRPC Server Reflection
grpcurl -insecure grpc.example.com:50051 list
# → billing.PaymentService
# → grpc.reflection.v1alpha.ServerReflection

# Получение описания методов сервиса
grpcurl -insecure grpc.example.com:50051 describe billing.PaymentService
# → service PaymentService {
# →   rpc ProcessPayment ( .billing.PaymentRequest ) returns ( .billing.PaymentResponse );
# → }

# Выполнение Unary RPC вызова с передачей JSON-полезной нагрузки
grpcurl -insecure -d '{"account_id": 4201, "amount_cents": 5000}' \
        grpc.example.com:50051 billing.PaymentService/ProcessPayment
# → {
# →   "status": "APPROVED",
# →   "transaction_id": "tx_9982431"
# → }
```

### 5. Инспекция сетевых сокетов и дескрипторов ОС

```bash
# Подсчет общего числа активных ESTABLISHED-соединений процессов Angie
ss -tnp | grep angie | grep ESTAB | wc -l
# → 14250

# Анализ состояния сокетов конкретного воркера с подробной TCP-статистикой
ss -ti '( sport = :443 or sport = :50051 )' | head -n 20
# → ESTAB 0 0 10.0.0.5:443 192.168.1.50:54321
# →   cubic wscale:7,7 rto:200 rtt:0.12/0.04 ato:40 mss:1460 rcvspace:14600 ssthresh:10 cwnd:10

# Мониторинг воркеров старого поколения, зависших в фазе shutdown
ps -eo pid,cmd,etime | grep "angie: worker process is shutting down"
```

### 6. Мониторинг метрик через Status API и Prometheus

Angie собирает детальную статистику по соединениям и зонам апстримов:

```bash
# Запрос текущего состояния соединений через JSON Status API
curl -s http://127.0.0.1/status/http/server_zones/ws_gateway | jq .
# → {
# →   "processing": 3412,
# →   "requests": 158902,
# →   "responses": { "1xx": 3412, "2xx": 155000, "4xx": 450, "5xx": 40 }
# → }

# Запрос метрик Prometheus для gRPC и WebSocket апстримов
curl -s http://127.0.0.1/status/prometheus | grep -E "angie_http_upstreams.*(state|active|fails)"
# → angie_http_upstreams_server_state{upstream="billing_grpc_cluster",server="10.0.30.21:50051"} 1
# → angie_http_upstreams_server_active{upstream="ws_cluster",server="10.0.10.11:8080"} 1705
```

---

## Устранение неисправностей

### 1. Проблемы WebSocket

| Симптом | Первопричина | Диагностика | Способ устранения |
| :--- | :--- | :--- | :--- |
| **`400 Bad Request`** при попытке установления соединения | Отсутствует директива `proxy_http_version 1.1;` или заголовок `Connection` передан со значением `close` | Анализ запроса в `access.log`: проверить `$http_upgrade` и `$http_connection` | Настроить блок `map $http_upgrade $connection_upgrade` и принудительно задать `proxy_http_version 1.1;` |
| **`403 Forbidden`** при открытии сокета | Сработала проверка заголовка `Origin` (CSWSH filter) или директивы `limit_conn` | Журнал `error.log`: запись `[warn] 403 forbidden by limit_conn` или return 403 | Добавить домен клиентского приложения в карту `map $http_origin $ws_origin_allowed` |
| Соединение **обрывается ровно через 60 секунд** | Истекает стандартный таймаут `proxy_read_timeout` (по умолчанию 60s) при отсутствии данных | Запись в `access.log` с кодом 101 и длительностью `request_time=60.00x` | Увеличить `proxy_read_timeout 3600s;` и включить передачу Heartbeat/Ping фреймов в приложении |
| Соединение **«тихо» замерзает** через 5-15 минут простоя | Stateful NAT, conntrack или облачный файрвол удалили трансляцию сокета из таблицы | Клиент видит ошибку только при попытке записи (RST) или не получает ответы | Включить системный TCP Keepalive: `proxy_socket_keepalive on;` либо настроить application-level Ping/Pong |
| Ошибка **`1006 Abnormal Closure`** у клиентов при reload | Старый worker был завершен до того, как клиент добровольно отключился | Сообщения `worker process PID exited on signal 9` в системном dmesg/syslog | Настроить `worker_shutdown_timeout 60s;` в `angie.conf` и `TimeoutStopSec=75s` в systemd |

### 2. Проблемы Server-Sent Events

| Симптом | Первопричина | Диагностика | Способ устранения |
| :--- | :--- | :--- | :--- |
| События доставляются **пачками с задержкой** в десятки секунд | Включена буферизация `proxy_buffering on;` или потоковый компрессор gzip | Запуск `curl -N`: данные поступают только блоками по 4-16 КБ | Добавить `proxy_buffering off;`, отключить сжатие (`gzip off;`) и отправлять `X-Accel-Buffering: no` |
| Бэкенд **исчерпывает потоки/воркеры** при отключении клиентов | Включена директива `proxy_ignore_client_abort on;` — Angie удерживает запрос к бэкенду | Количество потоков сервиса растет, несмотря на закрытие вкладок пользователями | Установить `proxy_ignore_client_abort off;` (значение по умолчанию) |
| В браузере **блокируются новые запросы** к тому же домену | Браузер уперся в лимит параллельных HTTP/1.1 соединений (6 сокетов на origin) | В инструментах разработчика (Network) статус запросов `Queueing` / `Stalled` | Перевести сайт на HTTP/2 (`http2 on;`), где SSE мультиплексируется в общий поток |

### 3. Проблемы gRPC

| Симптом | Первопричина | Диагностика | Способ устранения |
| :--- | :--- | :--- | :--- |
| Ошибка **`502 Bad Gateway`** при вызове RPC | На бэкенд передан незашифрованный HTTP/1.x вместо HTTP/2, либо неверный порт | `error.log`: `upstream sent frame for unknown stream` или `invalid HTTP/2 format` | Использовать директиву `grpc_pass`, а не `proxy_pass`; проверить соответствие схемы (`grpc://` vs `grpcs://`) |
| Ошибка **`415 Unsupported Media Type`** | Запрос отправлен с некорректным `Content-Type` (требуется `application/grpc`) | Анализ заголовков запроса в `grpc_detailed` логе | Проверить реализацию клиента или проброс `grpc_set_header Content-Type application/grpc;` |
| Ошибка gRPC status **`12 (UNIMPLEMENTED)`** | Запрос направлен в некорректный `location` или не совпадает регистр имени метода | В логах `$sent_http_grpc_status = 12`; в теле ответа `unknown method` | Проверить соответствие пути: `/package.ServiceName/MethodName` с учетом регистра |
| Ошибка gRPC status **`14 (UNAVAILABLE)`** | Все бэкенды в блоке `upstream` недоступны или перегружены | В логах `$sent_http_grpc_status = 14`, `$upstream_status = 502/504` | Проверить статус процессов сервиса, сетевую связность и параметры `grpc_next_upstream` |
| Потоковые вызовы (Streaming RPC) **обрываются посреди диалога** | Сработал тайм-аут ожидания данных `grpc_read_timeout` | Запись в журнале ошибок `upstream timed out (110: Connection timed out)` | Увеличить `grpc_read_timeout` и `grpc_send_timeout` до значений, соответствующих логике стрима |

---

## Лучшие практики и системная оптимизация

### 1. Тюнинг сетевого стека ядра Linux (sysctl)

При обслуживании более 50 000–200 000 постоянных WebSocket или gRPC-соединений на одном физическом или виртуальном сервере стандартные параметры сетевого стека Linux вызывают исчерпание памяти и дескрипторов.

Примените параметры в файле `/etc/sysctl.d/99-angie-streaming.conf`:

```ini
# Максимальное число открытых файловых дескрипторов в системе
fs.file-max = 2097152

# Максимальный размер очереди входящих соединений
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535

# Ограничение минимального и стандартного размера буферов сокетов для экономии ОЗУ
# Формат: min default max (в байтах). Для 100k сокетов буфер по умолчанию не должен превышать 16 КБ!
net.ipv4.tcp_rmem = 4096 87380 4194304
net.ipv4.tcp_wmem = 4096 65536 4194304

# Агрессивное обнаружение «мертвых» сокетов через TCP Keepalive
# Первый зонд через 300 секунд (5 мин) вместо 7200 сек (2 часа) по умолчанию
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_intvl = 15
net.ipv4.tcp_keepalive_probes = 5

# Диапазон локальных портов для исходящих подключений к апстримам
net.ipv4.ip_local_port_range = 10240 65535

# Повторное использование сокетов в состоянии TIME_WAIT для исходящих TCP-сессий
net.ipv4.tcp_tw_reuse = 1

# Сокращение времени удержания сокета в состоянии FIN_WAIT_2
net.ipv4.tcp_fin_timeout = 15
```

Активация параметров без перезагрузки:

```bash
sysctl --system
```

### 2. Системные лимиты процессов (systemd и pam_limits)

Убедитесь, что воркеры Angie имеют доступ к необходимому количеству дескрипторов файлов:

```ini
# /etc/systemd/system/angie.service.d/limits.conf
[Service]
LimitNOFILE=262144
LimitNPROC=262144
```

Применение конфигурации:

```bash
systemctl daemon-reload
systemctl restart angie
```

### 3. Архитектурные рекомендации SRE и DevOps

1. **Не смешивайте настройки буферизации глобально:** Никогда не устанавливайте `proxy_buffering off;` на уровне блоков `http` или `server`. Это приведет к удержанию соединений бэкендов медленными мобильными клиентами для обычных запросов. Отключайте буферизацию **строго локально** в блоках `location` для SSE и WebSocket.
2. **Используйте Connection Pooling для gRPC:** Всегда объявляйте директиву `keepalive` внутри блока `upstream` для gRPC-сервисов. Мультиплексирование сотен gRPC-вызовов в пул из 8–32 постоянных соединений кардинально снижает задержки и нагрузку на CPU бэкендов.
3. **Всегда включайте `status_zone`:** Для всех локаций стриминга и gRPC создавайте выделенные сегменты памяти директивой `status_zone`. Это позволяет отслеживать зависшие сессии и аномалии в реальном времени через встроенный Prometheus-экспортер Angie.
4. **Контролируйте `worker_shutdown_timeout`:** Долгоживущие соединения не должны препятствовать выкатке релизов и перезагрузке серверов. Тайм-аут остановки в диапазоне от 30 до 60 секунд обеспечивает оптимальный компромисс между сохранением сессий клиентов и непрерывностью CI/CD конвейера.
5. **Разделяйте таймауты Handshake и Data Stream:** На этапе установки соединения используйте агрессивные короткие тайм-ауты (`proxy_connect_timeout 3s–5s;`, `grpc_connect_timeout 2s–5s;`), чтобы не блокировать пул при сбоях бэкенда, и длительные тайм-ауты чтения (`proxy_read_timeout 300s–3600s;`) только после успешного перехода в режим передачи данных.

---

## Дополнительная информация

*   [Обратный прокси в Angie](./angie_reverse_proxy.md) — базовые концепции проксирования, работа пулов соединений и проброс служебных заголовков.
*   [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md) — алгоритмы распределения запросов, зоны разделяемой памяти и активные проверки состояния.
*   [Бесшовный перезапуск и обновление Angie](./angie-graceful-reload.md) — детальная архитектура смены поколений master/worker-процессов и управление тайм-аутами graceful shutdown.
*   [Базовая конфигурация Angie](./angie-baseline-config.md) — проверенные production-шаблоны конфигурационного файла `angie.conf`.
*   [Настройка TLS в Angie](./angie_tls_setup.md) — оптимизация сессий TLSv1.3, генерация сертификатов и настройка ALPN для протоколов HTTP/2 и HTTP/3.
*   [CDN: WebSocket, SSE и gRPC](../../Networking/CDN/cdn_websocket_sse_grpc.md) — особенности туннелирования долгоживущих протоколов через граничные распределенные сети.

---

## См. также

*   [Мониторинг Angie: Status API](./angie_monitoring/angie_monitoring_api.md)
*   [Экспорт метрик Angie в Prometheus](./angie_monitoring/angie_monitoring_prometheus.md)
*   [Управление трафиком и директивы Location в Angie](./angie_location_directives.md)
*   [Защита от DoS-атак в Angie](./High_Load/dos_protection.md)
*   [Оптимизация производительности Angie при высоких нагрузках](./High_Load/performance_optimization.md)
*   [Управление постоянными соединениями Upstream](../Concepts/web_performance/upstream_keepalive_and_pooling.md)