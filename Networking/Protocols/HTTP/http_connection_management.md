# Управление соединениями HTTP

## Определения

**Управление соединениями** — набор механизмов и конфигураций, контролирующих жизненный цикл TCP/TLS-соединений между клиентом и сервером (или прокси и бэкендом). Цель: минимизировать latency, предотвратить исчерпание ресурсов, защитить от атак.

**Keep-Alive** — механизм удержания TCP-соединения открытым после ответа для повторного использования. В HTTP/1.1 включён по умолчанию; в HTTP/2 и HTTP/3 обязателен.

**Connection Pool (Пул соединений)** — набор предустановленных соединений к бэкенду, переиспользуемых для множества запросов. Уменьшает накладные расходы TCP/TLS handshake.

**TIME-WAIT** — состояние TCP-соединения после закрытия, в течение которого порт/соединение не могут быть переиспользованы (2MSL = 2×Maximum Segment Lifetime, обычно 60 секунд).

**Socket Exhaustion (Исчерпание сокетов)** — ситуация, когда сервер исчерпал лимит файловых дескрипторов (ulimit -n) или портов, и не может принимать новые соединения.

## Основные концепции

### Параметры keepalive (Nginx)

| Директива | Назначение | Типичное значение |
| :--- | :--- | :--- |
| `keepalive_timeout` | Время удержания idle-соединения | `65s` |
| `keepalive_requests` | Максимум запросов на одном keepalive-соединении | `1000` |
| `keepalive_time` | Максимальное время жизни keepalive-соединения | `1h` (Angie/Nginx 1.25+) |

### Параметры таймаутов (Nginx)

| Директива | Назначение | Типичное значение |
| :--- | :--- | :--- |
| `client_header_timeout` | Таймаут на чтение заголовков запроса | `60s` |
| `client_body_timeout` | Таймаут на передачу тела запроса | `60s` |
| `send_timeout` | Таймаут на передачу ответа клиенту | `60s` |
| `proxy_connect_timeout` | Таймаут на установление соединения с upstream | `5s`–`10s` |
| `proxy_read_timeout` | Таймаут на чтение ответа от upstream | `60s`–`300s` |
| `proxy_send_timeout` | Таймаут на отправку запроса upstream | `60s`–`300s` |
| `lingering_timeout` | Таймаут для lingering close (завершение соединения) | `5s` |

### Параметры таймаутов (HAProxy)

| Директива | Назначение | Типичное значение |
| :--- | :--- | :--- |
| `timeout connect` | Таймаут на установление соединения | `5s` |
| `timeout client` | Таймаут inactivity на стороне клиента | `50s` |
| `timeout server` | Таймаут inactivity на стороне сервера | `50s` |
| `timeout http-keep-alive` | Таймаут keepalive | `10s` |
| `timeout http-request` | Таймаут на полный HTTP-запрос | `10s` |
| `timeout queue` | Таймаут в очереди (если все бэкенды загружены) | `30s` |

### Буферы и лимиты (Nginx)

| Директива | Назначение | Типичное значение |
| :--- | :--- | :--- |
| `client_body_buffer_size` | Размер буфера для тела запроса (до записи в temp file) | `8k`–`16k` |
| `client_max_body_size` | Максимальный размер тела запроса | `10M` |
| `client_header_buffer_size` | Размер буфера для заголовков запроса | `1k`–`4k` |
| `large_client_header_buffers` | Количество и размер буферов для больших заголовков | `4 8k`–`16k` |
| `proxy_buffer_size` | Размер буфера для заголовков ответа upstream | `4k`–`16k` |
| `proxy_buffers` | Количество и размер буферов для тела ответа upstream | `8 4k`–`16k` |
| `proxy_busy_buffers_size` | Максимум busy-буферов при медленной отправке | `16k`–`64k` |
| `proxy_max_temp_file_size` | Максимальный размер temp file при превышении буферов | `1024m` (0 = отключить) |

### Настройка воркеров (Nginx)

| Директива | Назначение | Типичное значение |
| :--- | :--- | :--- |
| `worker_processes` | Количество воркеров (обычно = CPU cores) | `auto` |
| `worker_cpu_affinity` | Привязка воркеров к CPU cores | `auto` или `0001 0010 0100 1000` |
| `worker_rlimit_nofile` | Максимум открытых файлов (ulimit) на воркер | `65535` |
| `worker_shutdown_timeout` | Таймаут на завершение воркера при reload | `10s` |
| `events { worker_connections }` | Максимум соединений на воркер | `4096`–`65535` |

### Пул соединений

| Тип пула | Инструмент | Рекомендация |
| :--- | :--- | :--- |
| **HTTP Keepalive** | Nginx `keepalive 32` в upstream | Обязательно для всех upstream |
| **HTTP/2 multiplexing** | `http2` в listen | Один TCP-соединение = много потоков |
| **QUIC 0-RTT** | QUIC, HTTP/3 | Только для идемпотентных запросов |
| **Application pool** | `requests.Session()` (Python), `http.Client` (Go) | Один пул на приложение |
| **Database connection pool** | PgBouncer, HikariCP | Отдельный пул для БД |

## Практические сценарии

### Сценарий 1: Оптимизация keepalive и таймаутов

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

        client_header_timeout 30s;
        client_body_timeout   60s;
        send_timeout          60s;

        location / {
            proxy_pass http://api_backend;
            proxy_http_version 1.1;
            proxy_set_header Connection "";

            proxy_connect_timeout 5s;
            proxy_read_timeout    60s;
            proxy_send_timeout    60s;
        }
    }
}
```

**Валидация:**
- `ss -tn state established '( dport = :80 )' | wc -l` — много установленных соединений (keepalive работает).
- `curl -o /dev/null -w "%{time_connect}\n" http://api.example.com/` — соединение переиспользуется, latency <10ms (без TCP handshake).

### Сценарий 2: Worker tuning для высокой нагрузки

```nginx
worker_processes auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 65535;
    multi_accept on;
    use epoll;
}

http {
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;

    keepalive_timeout 65s;
    keepalive_requests 1000;
}
```

**Валидация:**
- `cat /proc/$(pgrep nginx | head -1)/limits | grep "open files"` — `Max open files 65535`.
- `ss -s` — `estab` соединений стабильны при высокой нагрузке.
- `nginx -t` — конфиг без ошибок.

### Сценарий 3: Connection pool в Python

```python
import requests

session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=20,   # Количество пулов к разным хостам
    pool_maxsize=100,      # Максимум соединений в пуле
    pool_block=False       # Не блокировать при исчерпании
)
session.mount("https://", adapter)

# Использование
for _ in range(1000):
    resp = session.get("http://api.example.com/", timeout=5)
```

**Валидация:**
- `ab -n 1000 -c 100 http://api.example.com/` — latency p99 стабилен, нет `ESTABLISH` на каждый запрос.
- В логах приложения: один и тот же `Session` переиспользуется.

### Сценарий 4: Уменьшение TIME-WAIT

```bash
# sysctl.conf
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_probes = 5
net.ipv4.tcp_keepalive_intvl = 15

# Применение
sysctl -p
```

**Валидация:**
- `ss -s` — `time-wait` уменьшилось с ~10000 до ~1000.
- `cat /proc/sys/net/ipv4/tcp_tw_reuse` — `1`.

### Сценарий 5: Ограничение соединений по IP

```nginx
http {
    limit_conn_zone $binary_remote_addr zone=addr:10m;

    server {
        listen 80;
        server_name api.example.com;

        location / {
            limit_conn addr 10;
            limit_conn_status 429;
            proxy_pass http://api_backend;
        }
    }
}
```

**Валидация:**
- `for i in $(seq 1 20); do curl -s -o /dev/null -w "%{http_code}\n" http://api.example.com/ & done` — после 10 соединений `429 Too Many Requests`.

### Сценарий 6: Лимит размера заголовков и тела

```nginx
server {
    listen 80;
    server_name api.example.com;

    client_header_buffer_size 1k;
    large_client_header_buffers 4 8k;
    client_body_buffer_size 8k;
    client_max_body_size 20m;

    location / {
        proxy_pass http://api_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Валидация:**
- `curl -X POST http://api.example.com/ -d "$(python -c 'print("A"*100000)')"` — `413 Request Entity Too Large` при >20M.
- `curl -H "X-Large-Header: $(python -c 'print("A"*10000)')" http://api.example.com/` — `400 Bad Request` при слишком больших заголовках.

### Сценарий 7: Graceful shutdown с linger

```bash
# Nginx graceful reload
nginx -t && nginx -s reload

# Проверка: рабочие процессы перезапускаются, соединения не разрываются
watch -n1 'ss -tn state established '( dport = :443 )' | wc -l'
```

**Валидация:**
- Во время reload: количество соединений стабильно.
- Новые соединения обслуживаются новыми воркерами.
- Старые соединения завершаются gracefully (без RST).

## Типичные проблемы и диагностика

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Too many open files** | `EMFILE` в логах, сервер не принимает соединения | `cat /proc/$(pgrep nginx)/limits | grep "open files"` | Увеличить `worker_rlimit_nofile` и `ulimit -n` |
| **Socket exhaustion** | `Cannot assign requested address` | `ss -s` — много `TIME-WAIT` | `tcp_tw_reuse`, уменьшить `keepalive_timeout` |
| **Keepalive exhaustion** | Много idle-соединений, исчерпание `worker_connections` | `ss -tn state established '( dport = :80 )'` | Уменьшить `keepalive_timeout`, увеличить `worker_connections` |
| **Slowloris** | Медленная отправка заголовков, исчерпание воркеров | `tcpdump -i eth0 -n -A port 80` — неполные заголовки | `client_header_timeout 10s`, `limit_conn` |
| **Linger timeout** | Соединения зависают в `FIN-WAIT-2` | `ss -tn state fin-wait-2 '( dport = :80 )'` | Уменьшить `lingering_timeout`, `lingering_time` |
| **Proxy buffering lag** | Ответы приходят с задержкой при медленном клиенте | `tcpdump` — данные удерживаются в буфере Nginx | Увеличить `proxy_busy_buffers_size` или отключить буферизацию |
| **Large headers** | `400 Bad Request` при больших cookies/токенах | `grep -c "client intended to send too large header" error.log` | Увеличить `large_client_header_buffers` |
| **TCP retransmissions** | Высокий latency, потери пакетов | `tshark -r file.pcap -Y "tcp.analysis.retransmission"` | Проверить сеть, MTU, включить PMTU discovery |
| **Connection reset by peer** | `104 Connection reset by peer` | `dmesg | grep -i "connection reset"` | Проверить `send_timeout`, `proxy_read_timeout` |
| **Worker shutdown hang** | `nginx -s reload` висит | `ps aux | grep nginx` — старые воркеры не завершаются | Увеличить `worker_shutdown_timeout` |

## Лучшие практики

1. **`worker_processes auto` и `worker_cpu_affinity`:** Равняйте `worker_processes` по CPU cores. Используйте `worker_cpu_affinity auto` или явное назначение ядер.
2. **`keepalive` в upstream:** Всегда включайте `keepalive 32` (или больше). Это уменьшает TCP handshake overhead в 10–100 раз.
3. **`proxy_http_version 1.1` + `Connection ""`:** Для keepalive в upstream. Без этого Nginx закроет соединение после каждого запроса.
4. **`tcp_nopush on; tcp_nodelay on;`:** `tcp_nopush` отправляет заголовок и тело в одном пакете (HTTP/1.1). `tcp_nodelay` отключает Nagle для интерактивных запросов. Вместе дают оптимальную производительность.
5. **`sendfile on;`:** Отправка файлов напрямую из ядра, без копирования в userspace. Для статики критично.
6. **`client_body_timeout` и `client_header_timeout`:** Защита от slowloris. `10s` для заголовков, `60s` для тела.
7. **`proxy_connect_timeout` минимальный:** `5s` достаточно. Увеличение скрывает проблемы с сетью.
8. **`proxy_read_timeout` под сервис:** Для API с долгими операциями — 300s. Для обычных — 60s.
9. **`worker_rlimit_nofile` и `ulimit -n`:** Устанавливайте `65535` или выше. Проверяйте через `cat /proc/$(pgrep nginx)/limits`.
10. **`tcp_tw_reuse`:** Включите `net.ipv4.tcp_tw_reuse = 1` для уменьшения TIME-WAIT. Безопасно для Linux.
11. **`limit_conn` по IP:** Защита от одного клиента, исчерпывающего все соединения. `limit_conn addr 10`.
12. **`ssl_session_cache`:** `shared:SSL:10m` для ~40 000 сессий. Включайте TLS session resumption.

## Граничные случаи и ограничения

1. **`keepalive_timeout 0`:** Отключает keepalive. Каждый запрос — новое TCP-соединение. Увеличивает latency на 30–50%.
2. **`worker_connections` и `limit_conn`:** `limit_conn` ограничивает соединения на воркер. При 4 воркерах и `worker_connections 1024` общий лимит = 4096.
3. **`proxy_buffering off` и streaming:** Отключайте буферизацию для SSE, long polling. Иначе данные будут накапливаться в буфере до его заполнения.
4. **`tcp_nopush` и HTTP/2:** В HTTP/2 `tcp_nopush` игнорируется (фрейминг на уровне HTTP/2). Накладные расходы минимальны.
5. **`client_body_temp_path` и разделы:** При использовании разделов для temp-директории убедитесь, что Nginx имеет права на запись.
6. **`proxy_max_temp_file_size` и RAM:** При `0` (отключено) большие ответы не пишутся на диск, но потребляют RAM. Установите `1024m` для буферизации до 1GB.
7. **`linger_timeout` и 100-continue:** При `100 Continue` сервер ждёт тело. Увеличьте `lingering_timeout`, если клиент медленно отправляет данные после `100 Continue`.
8. **`worker_shutdown_timeout` и длинные запросы:** При reload старые воркеры завершают текущие запросы. Увеличьте `worker_shutdown_timeout`, если запросы могут длиться >10s.
9. **`tcp_tw_reuse` и NAT:** При reuse TIME-WAIT сокетов за NAT возможны конфликты, если NAT переиспользует тот же порт. В продакшене обычно безопасно.
10. **Connection pool exhaustion в приложении:** Приложение может исчерпать пул соединений (`pool_maxsize`), если бэкенд медленный. Настройте `timeout` и `pool_block`.

## Дополнительная информация

### sysctl tuning для HTTP-серверов

```bash
# /etc/sysctl.d/99-http-tuning.conf
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_synack_retries = 2
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_probes = 5
net.ipv4.tcp_keepalive_intvl = 15
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_tw_recycle = 0  # Опасно за NAT!
net.ipv4.ip_local_port_range = 1024 65535
net.core.netdev_max_backlog = 5000
```

### HAProxy: tune-параметры

```haproxy
global
    tune.maxaccept    100
    tune.ssl.default-dh-param 2048
    tune.bufsize      16384
    tune.sslcache.size    100000
```

## Смотрите также

- **[HTTP-серверы и прокси](./http_servers_proxies.md)** — `keepalive`, `proxy_buffer_size`, `worker_processes`.
- **[Эволюция HTTP](./http_versions.md)** — multiplexing в HTTP/2, 0-RTT в HTTP/3.
- **[Rate Limiting и устойчивость](./http_rate_limiting_circuit_breakers.md)** — `limit_conn`, protection от исчерпания.
- **[Диагностика Nginx](../../../WebServers/Nginx/Operations/nginx_troubleshooting.md)** — устранение проблем с соединениями.
- **[TCP: Обзор](../../Protocols/TCP/overview.md)** — TCP handshake, TIME-WAIT, socket exhaustion.
