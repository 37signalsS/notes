# HTTP-серверы и прокси: Конфигурация и эксплуатация

## Определения

**HTTP-сервер** — программное обеспечение, принимающее HTTP-запросы от клиентов и возвращающее HTTP-ответы. В продакшене под «сервером» обычно понимается связка **веб-сервер + обратный прокси** (Reverse Proxy), который terminates TLS, распределяет нагрузку и кэширует контент.

**Обратный прокси (Reverse Proxy)** — промежуточный узел, стоящий перед серверами приложений (backend). Клиент взаимодействует только с прокси, который перенаправляет запросы на соответствующий backend. Основные роли: SSL termination, load balancing, кэширование, WAF, логирование.

**Прямой прокси (Forward Proxy)** — узел, через который клиент инициирует соединение с внешними ресурсами. Используется корпоративными сетями для фильтрации и кэширования.

**Upstream (Backend Pool)** — группа серверов приложений, на которые Reverse Proxy распределяет запросы. В контексте Nginx — блок `upstream`; в HAProxy — секция `backend`.

## Основные концепции

### Nginx: базовые директивы

Nginx работает по асинхронному событийному циклу (event-driven), что позволяет обрабатывать тысячи соединений на одном воркере с минимальным потреблением памяти.

| Директива | Назначение | Типичное значение |
| :--- | :--- | :--- |
| `worker_processes` | Количество воркеров (обычно = CPU cores) | `auto` |
| `worker_connections` | Максимум соединений на воркер | `4096`–`65535` |
| `keepalive_timeout` | Время удержания idle-соединений | `65s` |
| `keepalive_requests` | Максимум запросов на одном keepalive-соединении | `1000` |
| `client_max_body_size` | Максимальный размер тела запроса | `10M`–`100M` |
| `client_body_timeout` | Таймаут на передачу тела запроса | `60s` |
| `client_header_timeout` | Таймаут на чтение заголовков | `60s` |
| `send_timeout` | Таймаут на передачу ответа | `60s` |
| `proxy_connect_timeout` | Таймаут соединения с upstream | `5s`–`10s` |
| `proxy_read_timeout` | Таймаут чтения ответа от upstream | `60s`–`300s` |
| `proxy_send_timeout` | Таймаут отправки запроса upstream | `60s`–`300s` |
| `proxy_buffer_size` | Размер буфера для заголовков ответа upstream | `4k`–`16k` |
| `proxy_buffers` | Количество и размер буферов для тела ответа | `8 4k`–`16k` |
| `proxy_busy_buffers_size` | Максимум буферов при медленной отправке клиенту | `16k`–`64k` |
| `limit_req_zone` | Зона rate limiting по ключу | `$binary_remote_addr zone=...` |
| `limit_conn_zone` | Зона ограничения соединений по ключу | `$binary_remote_addr zone=...` |
| `limit_except` | Ограничение методов внутри location | `GET HEAD` |
| `real_ip_header` | Заголовок с реальным IP клиента | `X-Forwarded-For` |
| `set_real_ip_from` | Диапазон доверенных прокси (proxy/load balancer) | `10.0.0.0/8` |

### Nginx: upstream и балансировка

Блок `upstream` определяет пул бэкендов. Nginx поддерживает несколько алгоритмов балансировки:

| Алгоритм | Директива | Описание |
| :--- | :--- | :--- |
| Round-robin | (по умолчанию) | Равномерное распределение по очереди |
| Least-conn | `least_conn` | На least-conn сервер с наименьшим количеством активных соединений |
| IP-hash | `ip_hash` | Sticky sessions: хэш от IP клиента |
| Hash | `hash $request_id consistent` | Хэш по произвольному ключу (URL, cookie, header) |
| Random | `random two least_conn` | Случайный выбор с fallback на least-conn |

### Nginx: proxy_set_header и передача заголовков

При reverse proxy Nginx по умолчанию передаёт upstream только минимальный набор заголовков. Важно явно передавать `Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`:

```nginx
proxy_set_header Host              $host;
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

Без `X-Forwarded-Proto` бэкенд не может знать, пришёл ли запрос по HTTP или HTTPS, что ломает редиректы и CSP.

### HAProxy: базовые концепции

HAProxy — высокопроизводительный TCP/HTTP балансировщик. Основные секции:

| Секция | Назначение |
| :--- | :--- |
| `global` | Ограничения процесса, максимальное число соединений, дефолты |
| `defaults` | Общие параметры для всех `frontend`/`backend` (mode, timeout, log) |
| `frontend` | Принимает соединения от клиентов; определяет routing |
| `backend` | Определяет пул серверов, балансировку, health checks |
| `listen` | Объединённый frontend + backend для простых случаев |

### HAProxy: алгоритмы балансировки

| Алгоритм | Директива | Описание |
| :--- | :--- | :--- |
| Round-robin | `balance roundrobin` | Равномерное циклическое распределение |
| Least-conn | `balance leastconn` | На сервер с наименьшим числом соединений |
| Source | `balance source` | Хэш от source IP (sticky sessions) |
| URI | `balance uri` | Хэш от URI (устойчивое кэширование) |
| HDR | `balance hdr(Host)` | Хэш от заголовка |
| Random | `balance random` | Случайный выбор |

### Протокол PROXY Protocol

PROXY Protocol (v1/v2) позволяет передать реальный IP клиента через TCP-прокси (HAProxy, Nginx stream, Envoy), которые не могут обработать HTTP-заголовки `X-Forwarded-For`. Протокол добавляет строку с IP и портом в начало TCP-потока.

## Практические сценарии

### Сценарий 1: Базовая конфигурация Nginx с upstream

Создаём reverse proxy для двух бэкендов на `8080` и `8081`:

```nginx
http {
    upstream api_backend {
        server 10.0.1.10:8080;
        server 10.0.1.11:8080;
        keepalive 32;
    }

    server {
        listen 80;
        server_name api.example.com;

        client_max_body_size 20M;
        client_body_timeout 60s;
        client_header_timeout 60s;

        location / {
            proxy_pass http://api_backend;
            proxy_set_header Host              $host;
            proxy_set_header X-Real-IP         $remote_addr;
            proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            proxy_connect_timeout 5s;
            proxy_read_timeout    60s;
            proxy_send_timeout    60s;

            proxy_buffer_size        16k;
            proxy_buffers            8 16k;
            proxy_busy_buffers_size  64k;

            proxy_http_version 1.1;
            proxy_set_header Connection "";
        }
    }
}
```

**Валидация:**
- `nginx -t` — конфиг без ошибок.
- `curl -I http://api.example.com/health` — заголовки `X-Real-IP` и `X-Forwarded-For` присутствуют в запросе к бэкенду.
- `ss -tn state established '( dport = :8080 or dport = :8081 )' | wc -l` — соединения распределяются между бэкендами.

### Сценарий 2: Rate limiting в Nginx (limit_req)

Ограничиваем `/api` до 10 запросов в секунду с burst=20:

```nginx
http {
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

    server {
        listen 80;
        server_name api.example.com;

        location /api/ {
            limit_req zone=api_limit burst=20 nodelay;
            proxy_pass http://api_backend;
        }
    }
}
```

**Валидация:**
- `ab -n 100 -c 10 http://api.example.com/api/` — при превышении лимита ответ `429 Too Many Requests`.
- В логах Nginx: `limit_req_status=429`.

### Сценарий 3: Ограничение методов и размера запроса (limit_except)

Разрешаем только GET/HEAD/POST в location `/static`:

```nginx
server {
    listen 80;
    server_name static.example.com;

    root /var/www/static;

    location / {
        limit_except GET HEAD POST {
            deny all;
        }

        client_max_body_size 5M;
        add_header X-Content-Type-Options "nosniff";
    }
}
```

**Валидация:**
- `curl -X DELETE http://static.example.com/file.txt -i` — `403 Forbidden`.
- `curl -X POST http://static.example.com/file.txt -d @largefile -i` — `413 Payload Too Large`, если файл > 5M.

### Сценарий 4: HAProxy с активными health checks

Балансировщик распределяет трафик на 3 бэкенда с проверкой каждые 5 секунд:

```haproxy
frontend http-in
    bind *:80
    default_backend api_servers

backend api_servers
    balance roundrobin
    option httpchk GET /healthz

    server app1 10.0.1.10:8080 check inter 5s rise 2 fall 3
    server app2 10.0.1.11:8080 check inter 5s rise 2 fall 3
    server app3 10.0.1.12:8080 check inter 5s rise 2 fall fall 3
```

**Валидация:**
- `echo "show stat" | socat /var/run/haproxy.sock stdio | awk -F, 'NR>1 {print $1, $2, $18}'` — статус `UP`/`DOWN` для каждого сервера.
- Остановка бэкенда (`systemctl stop app1`) — после 3 проверок (`fall 3`) сервер помечен `DOWN`, трафик перетекает на остальных.

### Сценарий 5: Graceful shutdown (drain mode) в Nginx

Снимаем сервер из ротации перед redeploy:

```nginx
upstream api_backend {
    server 10.0.1.10:8080 max_fails=3 fail_timeout=30s;
    server 10.0.1.11:8080 max_fails=3 fail_timeout=30s;
    keepalive 32;
}

server {
    listen 80;
    server_name api.example.com;

    location / {
        proxy_pass http://api_backend;
        proxy_next_upstream error timeout http_500 http_502 http_503 http_504;
    }
}
```

Для graceful shutdown бэкенда:
```bash
# 1. Убрать сервер из upstream (необязательно, Nginx помечает DOWN при ошибках)
# 2. Остановить приём новых соединений на бэкенде (systemd / application-level)
# 3. Дождаться завершения текущих запросов (proxy_read_timeout)
# 4. Остановить сервис
systemctl stop api@10.0.1.10
```

**Валидация:**
- В логах бэкенда: все текущие запросы завершились до SIGTERM.
- В логах Nginx: `101 Switching Protocols` или нормальные ответы до отключения.

### Сценарий 6: Real IP и PROXY Protocol

Nginx получает запросы через HAProxy. Настраиваем передачу реального IP:

```nginx
# В http{} блоке
real_ip_header proxy protocol v2;
set_real_ip_from 10.0.1.0/24;  # HAProxy internal IP range
real_ip_recursive on;

# Или через заголовок (если прокси не поддерживает PROXY Protocol)
real_ip_header X-Forwarded-For;
set_real_ip_from 10.0.1.0/24;
```

**Валидация:**
- `curl http://nginx-host/ip` — возвращает реальный IP клиента, а не IP HAProxy.
- `tail -f /var/log/nginx/access.log` — в логах записан реальный IP.

### Сценарий 7: Sticky sessions через ip_hash

Сессии пользователей привязаны к конкретному бэкенду:

```nginx
upstream api_backend {
    ip_hash;
    server 10.0.1.10:8080 max_fails=3 fail_timeout=30s;
    server 10.0.1.11:8080 max_fails=3 fail_timeout=30s;
}

server {
    listen 80;
    server_name app.example.com;

    location / {
        proxy_pass http://api_backend;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Валидация:**
- `for i in $(seq 1 10); do curl -s http://app.example.com/api/host; done` — все 10 запросов с одного IP попадают на один и тот же бэкенд.
- При отключении бэкенда (`down` в конфиге или `fail_timeout`) запросы с его IP перетекают на другой сервер.

## Типичные проблемы и диагностика

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **502 Bad Gateway** | `502` от Nginx/HAProxy | `curl -v http://upstream:8080` — проверка бэкенда | Бэкенд упал или не служит порт; проверить `systemctl status app` |
| **504 Gateway Timeout** | `504` от Nginx | `curl -o /dev/null -w "%{time_total}" http://upstream:8080/health` — TTFB | Увеличить `proxy_read_timeout` или исправить медленный бэкенд |
| **408 Request Timeout** | `408` от Nginx | `tcpdump` на порту 80 — клиент не отправляет заголовки | Увеличить `client_header_timeout` или проверять сеть |
| **413 Payload Too Large** | `413` | `curl -X POST http://host/upload -F "file=@big"` — размер файла | Увеличить `client_max_body_size` |
| **499 Client Closed Request** | `499` в логах Nginx | `ss -tn state established '( dport = :80 )' | wc -l` — клиент разорвал соединение | Увеличить `proxy_read_timeout` или исправить медленный бэкенд |
| **Upstream prematurely closed** | `upstream prematurely closed connection` в логах | `journalctl -u app` — бэкенд упал во время обработки | Увеличить буферы (`proxy_buffer_size`) или исправить segfault |
| **No live upstreams** | `no live upstreams` в логах | `getent hosts upstream-host` — DNS | Проверить upstream, DNS, сеть |
| **worker_connections exhausted** | `worker_connections are not enough` | `ss -s` — много соединений в `time-wait` | Увеличить `worker_connections`, проверить `maxconn` |
| **Too many open files** | `Too many open files` | `cat /proc/$(pgrep nginx)/limits | grep "open files"` | Увеличить `worker_rlimit_nofile` и `ulimit -n` |
| **Slowloris attack** | Медленное заполнение заголовков, исчерпание воркеров | `tcpdump` — FIN/SYN без полных заголовков | `client_body_timeout 10s; client_header_timeout 10s; limit_conn` |

## Лучшие практики

1. **`worker_processes auto` и `worker_cpu_affinity`:** Равняйте `worker_processes` по количеству CPU cores. На многоядерных системах привязывайте воркеры к ядрам.
2. **`keepalive` в upstream:** Всегда включайте `keepalive` в блоке `upstream` (например, `keepalive 32`). Это уменьшает накладные расходы TCP handshake.
3. **`proxy_set_header Connection ""`:** При использовании `keepalive` в upstream очищайте заголовок `Connection`, чтобы Nginx не закрывал соединение после каждого запроса.
4. **`proxy_next_upstream`:** Настраивайте `proxy_next_upstream error timeout http_500 http_502 http_503 http_504;` для автоматического failover.
5. **`limit_except` вместо `allow/deny` по location:** Используйте `limit_except` внутри `location`, чтобы разрешать безопасные методы и запрещать опасные.
6. **`real_ip` только для доверенных прокси:** Никогда не доверяйте `X-Forwarded-For` от внешних клиентов — они могут подделать заголовок. Используйте `set_real_ip_from` с внутренними IP.
7. **`client_max_body_size` по endpoint'ам:** Устанавливайте лимит глобально и переопределяйте для upload-эндпоинтов. Не оставляйте `1m` на `/api` и `50m` на `/upload` одним значением.
8. **`proxy_buffer_size` под размер заголовков:** Если заголовки ответа бэкенда превышают `proxy_buffer_size`, Nginx пишет в временный файл, что замедляет ответ. Настройте `proxy_buffer_size 16k` или больше.
9. **`limit_req` с `burst` и `nodelay`:** `burst` absorbs всплески, `nodelay` обрабатывает их сразу (штрафуя за превышение). Без `nodelay` запросы станут в очередь, что увеличит latency.
10. **Graceful shutdown:** При redeploy используйте `nginx -s reload` (zero-downtime). Для бэкендов — сначала `stop` (graceful), потом `kill` (hard).
11. **Мониторинг `$upstream_response_time`:** Добавьте в `log_format` `$upstream_response_time` для измерения latency бэкендов.
12. **Валидация конфига перед reload:** Всегда запускайте `nginx -t` перед `nginx -s reload`. Ошибка в конфиге упадёт рабочий процесс.

## Граничные случаи и ограничения

1. **`ip_hash` и uneven distribution:** При неравномерном трафике `ip_hash` может перегружать отдельные серверы. Используйте `hash` с `consistent` для равномерного распределения.
2. **`keepalive` > `worker_connections`:** Суммарное количество keepalive-соеединений не должна превышать `worker_connections` (с учётом соединений с клиентами).
3. **`proxy_http_version 1.0`:** Для старых бэкендов, не поддерживающих keepalive. Нужно добавлять `Connection ""` или `Connection close` явно.
4. **`limit_req` и распределение по IP:** При использовании CDN или NAT `$binary_remote_addr` будет IP NAT, а не реального клиента. Используйте `$http_x_forwarded_for` только за доверенным прокси.
5. **`proxy_buffering off` для SSE/long-poll:** Отключайте буферизацию для streaming-эндпоинтов (Server-Sent Events, long polling), иначе клиент получит данные с задержкой.
6. **`client_body_temp_path` и разделы:** При использовании разделов (partitions) для temp-директории убедитесь, что Nginx имеет права на запись.
7. **`upstream` и DNS TTL:** Nginx кэширует DNS-имена upstream на 5 минут по умолчанию. Используйте `resolver` для динамического обновления.
8. **`limit_conn` и keepalive:** Ограничение соединений считается на уровне воркера. При `keepalive` одно TCP-соединение может выполнить много запросов, что снижает эффективность `limit_conn`.
9. **`proxy_set_header` и пустые значения:** Если заголовок отсутствует, Nginx передаёт пустую строку. Используйте `proxy_set_header X-Request-ID $request_id;` для гарантированной генерации.
10. **HAProxy `option httpchk` и POST:** По умолчанию `httpchk` отправляет `GET /`. Для API, требующих POST, используйте `option httpchk POST /healthz`.

## Дополнительная информация

### Выбор между Nginx и HAProxy

| Критерий | Nginx | HAProxy |
| :--- | :--- | :--- |
| **HTTP-фичи** | Полные (кэш, rewrite, gzip) | Базовые, но стабильные |
| **TCP-режим** | Stream-модуль | Нативная TCP-балансировка |
| **L7-фичи** | WebSocket, gRPC, HTTP/3 | HTTP/2, gRPC через `http-request set-var` |
| **Производительность** | Высокая (event-driven) | Высочайшая (user-space, epoll/kqueue) |
| **WAF** | ModSecurity, NAXSI | Нет встроенного WAF |
| **Сложность конфига** | Средняя | Низкая для простых случаев |

**Рекомендация:** Nginx — для полноценного reverse proxy с кэшированием и rewrite. HAProxy — для pure load balancing с минимальной задержкой.

### Мониторинг метрик

Nginx и HAProxy экспортируют метрики через `stub_status` и Prometheus exporter:

- **Nginx:** `ngx_http_stub_status_module` или `nginx-prometheus-exporter`.
- **HAProxy:** `stats socket` + `prometheus-exporter` или встроенный `prometheus-http` (v2.0+).

Ключевые метрики: `connections_active`, `connections_requests_total`, `requests_per_second`, `upstream_response_time`, `http_requests_rejected_total` (rate limiting).

## Смотрите также

- **[Базовые концепции HTTP](./http_basics.md)** — модель «запрос-ответ», заголовки.
- **[Эволюция HTTP](./http_versions.md)** — HTTP/2 и HTTP/3 в продакшене.
- **[HTTP-кэширование](./http_caching.md)** — кэширование в Nginx/Angie.
- **[Конфигурация HTTP/2 и HTTP/3 в Nginx](../../../WebServers/Nginx/Performance/nginx_http_versions.md)** — практическая настройка.
- **[Диагностика Nginx](../../../WebServers/Nginx/Operations/nginx_troubleshooting.md)** — устранение 502/504 ошибок.
- **[Управление соединениями](./http_connection_management.md)** — keepalive, таймауты, лимиты.
- **[Наблюдаемость HTTP-сервисов](./http_monitoring_observability.md)** — RED, Golden Signals, Prometheus.
