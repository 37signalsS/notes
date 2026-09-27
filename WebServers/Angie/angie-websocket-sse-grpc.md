# Проксирование WebSocket, SSE и gRPC в Angie

## Определения

*   **WebSocket (RFC 6455)** — двунаправленный протокол поверх TCP. Устанавливается как HTTP-запрос с заголовками `Upgrade: websocket` и `Connection: Upgrade`, после чего соединение переключается в дуплексный режим. Используется для чатов, уведомлений, онлайн-игр, live-обновлений.
*   **Server-Sent Events (SSE / EventSource)** — однонаправленный (сервер → клиент) поток событий поверх обычного HTTP. Клиент держит долгое GET-соединение; данные передаются порциями `text/event-stream`.
*   **gRPC** — RPC-фреймворк на базе HTTP/2 (двоичный кадр, мультиплексирование потоков). Angie проксирует gRPC-трафик через модуль `ngx_http_grpc_module`, работающий поверх `ngx_http_v2_module`/`ngx_http_v3_module`.
*   **`grpcs://`** — схема для проксирования gRPC на бэкенд по TLS (по аналогии с `https://`).

## Базовые концепции

### WebSocket через прокси

Для прохождения Upgrade-запроса Angie должен:

1. Отправить бэкенду запрос с версией HTTP 1.1: `proxy_http_version 1.1;`.
2. Передать заголовки `Upgrade: $http_upgrade` и `Connection: "upgrade"`.
3. Настроить большие `proxy_read_timeout`/`proxy_send_timeout` — долгоживущие соединения не должны обрываться таймаутом чтения.

Со стороны `upstream` соединения к WebSocket-бэкенду не являются keepalive по умолчанию, поэтому они создаются на каждый новый handshake.

### SSE через прокси

SSE — это обычный долгий HTTP GET. Проблемой становится буферизация: если `proxy_buffering on`, Angie накапливает поток событий и отдаёт порциями, ломая реальное время доставки. Для SSE следует:

*   `proxy_buffering off;` для SSE-location (и/или `proxy_set_header X-Accel-Buffering no;`, который бэкенд может выставить сам).
*   `proxy_read_timeout` — больше максимальной паузы между событиями.
*   Отключение сжатия для потокового контента (иначе клиент получит задержки из-за буферизации).

### gRPC через прокси

Модуль транслирует HTTP/2-трафик клиента в HTTP/2-трафик к бэкенду. Требования:

*   На стороне клиента — входящее соединение с включённым HTTP/2 (`listen 443 ssl http2;` или `http2 on;`).
*   `grpc_pass grpc://backend:50051;` (или `grpcs://...` для TLS к бэкенду).
*   Управление таймаутами: `grpc_connect_timeout`, `grpc_send_timeout`, `grpc_read_timeout`.
*   Мультиплексирование потоков и повторные попытки: `grpc_next_upstream`, `grpc_next_upstream_timeout`, `grpc_next_upstream_tries`.
*   Keepalive на транспортном уровне: `grpc_socket_keepalive on;` (управляет TCP keepalive к gRPC-серверу).

Общие положения о gRPC/SSE через CDN и веб-серверы — [CDN: WebSocket, SSE и gRPC](../../Networking/CDN/cdn_websocket_sse_grpc.md).

### HTTP/3 к бэкенду (особенность Angie)

В отличие от Nginx, Angie умеет проксировать на бэкенд не только HTTP/1.x и HTTP/2, но и HTTP/3 (`proxy_http_version 3.0;`) для внутренних соединений. Это редко требуется, но полезно для внутренних сетей с QUIC.

## Практические сценарии

### Сценарий 1: WebSocket-проксирование с балансировкой

```nginx
upstream ws_backends {
    zone ws_backends 64k;
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;
}

map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl http2;
    server_name ws.example.com;

    location /ws/ {
        proxy_pass http://ws_backends;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # Долгоживущие соединения
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_connect_timeout 5s;
    }
}
```

`map` для `Connection` возвращает `upgrade` для реальных Upgrade-запросов и `close` для обычных — защита от протаскивания чужих заголовков.

### Сценарий 2: gRPC passthrough (HTTP/2 до бэкенда)

```nginx
server {
    listen 443 ssl http2;
    server_name api.example.com;

    location /my.service.EventService/ {
        grpc_pass grpc://grpc_backend;
        grpc_socket_keepalive on;

        grpc_connect_timeout 5s;
        grpc_read_timeout 300s;
        grpc_send_timeout 300s;

        grpc_next_upstream error timeout;
        grpc_next_upstream_tries 3;

        grpc_set_header Host $host;
        grpc_set_header X-Real-IP $remote_addr;
    }
}
```

Бэкенд определяется точечно через full method path (`/package.Service/Method`) либо префиксом сервиса (`/my.service.EventService/`) — последнее популярно в микросервисных маршрутизаторах.

### Сценарий 3: gRPC с TLS к бэкенду (grpcs)

```nginx
location /my.service.EventService/ {
    grpc_pass grpcs://internal.events.svc:5081;

    # Проверка сертификата бэкенда
    grpc_ssl_certificate /etc/angie/ssl/backend.crt;
    grpc_ssl_certificate_key /etc/angie/ssl/backend.key;
    grpc_ssl_verify on;
    grpc_ssl_trusted_certificate /etc/angie/ssl/internal-ca.crt;
    grpc_ssl_verify_depth 2;
    grpc_ssl_server_name internal.events.svc;
}
```

### Сценарий 4: SSE (долгий поток) через прокси

```nginx
location /events/ {
    proxy_pass http://sse_backend;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header X-Accel-Buffering no;

    proxy_buffering off;
    proxy_cache off;

    proxy_read_timeout 600s;

    add_header Content-Type text/event-stream;
}
```

Убедитесь, что бэкенд выставляет `X-Accel-Buffering: no`, а Nagios/мониторинг не считает открытый поток ошибкой (SSE-соединения долго «висят» активными).

### Сценарий 5: Валидация Origin для WebSocket

Для защиты от CSWSH (Cross-Site WebSocket Hijacking) проверяйте заголовок `Origin`:

```nginx
if ($http_origin) {
    if ($http_origin !~ '^https?://(ws\.)?example\.com$') {
        return 403;
    }
}
```

Либо `map $http_origin $ws_allowed` + `if ($ws_allowed = "") { return 403; }`.

## Операции и команды

```bash
# Проверка, что WebSocket-конфиг применен
angie -t

# Ручной handshake WebSocket (curl 7.86+)
curl --include --no-buffer \
     -H "Connection: Upgrade" -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
     http://ws.example.com/
# → HTTP/1.1 101 Switching Protocols

# Проверка gRPC-бэкенда через grpcurl
grpcurl -plaintext 10.0.0.1:50051 list my.service.EventService

# Активные долгоживущие соединения (по пользователю процесса)
ss -tnp | grep angie | grep ESTAB | wc -l

# Мониторинг активных соединений и зоны ws через API
curl http://127.0.0.1/status/http/server_zones/ws.example.com
```

## Устранение неисправностей

### WebSocket: 400 Bad Request / Upgrade не проходит

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `400 Bad Request` от бэкенда | Бэкенд не получает `Upgrade`/`Connection` | Проверить `proxy_http_version 1.1;` и `proxy_set_header Connection $connection_upgrade;` |
| Соединение рвётся через ~1 мин | `proxy_read_timeout` мал или бэкенд сам закрывает | Поднять `proxy_read_timeout`; проверить keepalive на бэкенде |
| 502 при многих клиентах | Исчерпаны ресурсы воркеров (`worker_connections`) | Увеличить `worker_connections`/`worker_rlimit_nofile`; проверить метрики активных соединений |

### SSE: события приходят пачками

Причина — бидинг буфера (`proxy_buffering on`). Решение — `proxy_buffering off;` и `X-Accel-Buffering no` от бэкенда.

### gRPC: 502/интерфейсное зависание

*   Проверьте, что входящий listener поддерживает HTTP/2 (`listen 443 ssl http2;`).
*   Проверьте match-путь сервиса — gRPC-метод должен попадать в `location` (`grpc_pass` точный).
*   Смотрите `$upstream_status` (gRPC-статусы 12 = UNIMPLEMENTED, 14 = UNAVAILABLE) в access-log.
*   Убедитесь, что `grpc_read_timeout` не меньше максимального времени ответа метода.

## Лучшие практики

*   Для WebSocket/gRPC поднимайте `worker_shutdown_timeout` — graceful shutdown не должен обрывать активные долгие соединения мгновенно.
*   Мониторьте `active` соединения по зонам; рост без роста трафика = утечка соединений в приложении.
*   Не включайте агрессивное сжатие для потоковых ответов (SSE), иначе клиент не увидит события в реальном времени.
*   Для gRPC настройте `grpc_next_upstream` с осторожностью: повтор на неидемпотентный метод опасен.
*   При росте числа WebSocket-соединений учитывайте лимиты дескрипторов и `keepalive_requests` на client-стороне.

## Дополнительная информация

*   [Обратный прокси в Angie](./angie_reverse_proxy.md) — общий контекст проксирования и таймаутов.
*   [CDN: WebSocket, SSE и gRPC](../../Networking/CDN/cdn_websocket_sse_grpc.md) — сравнение протоколов на уровне сетей доставки.
*   [Nginx — примеры интеграции (Node.js + WebSocket)](../Nginx/Core/Location/integration_examples.md) — полный пример терминации SSL с WebSocket.

## См. также

*   [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)
*   [Настройка TLS в Angie](./angie_tls_setup.md)