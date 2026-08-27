# Логирование и инструменты диагностики HTTP

## Определения

**Логирование (Logging)** — запись событий HTTP-сервиса (запросы, ответы, ошибки) для последующего анализа, аудита и отладки. В продакшене используется **структурированное логирование** (JSON) для удобства парсинга и поиска.

**Access Log** — журнал всех запросов к серверу/прокси. Содержит IP клиента, метод, URI, код ответа, размер ответа, User-Agent, время.

**Error Log** — журнал ошибок и предупреждений серверного ПО (Nginx, HAProxy, приложения).

**Correlation ID (Request ID)** — уникальный идентификатор, связывающий все записи логов и трассировок, относящиеся к одному HTTP-запросу.

**Packet Capture (PCAP)** — запись сетевых пакетов для анализа на транспортном уровне. Используется `tcpdump`, `tshark`, `ngrep`.

## Основные концепции

### Форматы логов

| Формат | Пример | Преимущества |
| :--- | :--- | :--- |
| **Combined** (Nginx default) | `127.0.0.1 - frank [10/Oct/2023:13:55:36 +0000] "GET /apache_pb.gif HTTP/1.0" 200 2326` | Читаемый, поддержка большинством инструментов |
| **JSON** | `{"remote_addr":"...","method":"GET","uri":"/","status":200,"request_time":0.045}` | Структурированный; легко парсится и индексируется |
| **CEF (Common Event Format)** | `CEF:0\|...` | Стандарт SIEM; поддерживается ArcSight, QRadar |
| **ELF (Extended Log Format)** | `Fields: ...` | W3C-стандарт; поддержка в аналитических платформах |

### Nginx: формат JSON-логов

```nginx
log_format json_combined escape=json
    '{'
        '"time":"$time_iso8601",'
        '"remote_addr":"$remote_addr",'
        '"request_id":"$request_id",'
        '"method":"$request_method",'
        '"uri":"$request_uri",'
        '"status":$status,'
        '"request_time":$request_time,'
        '"upstream_response_time":"$upstream_response_time",'
        '"bytes_sent":$body_bytes_sent,'
        '"http_user_agent":"$http_user_agent",'
        '"http_referer":"$http_referer"'
    '}';

access_log /var/log/nginx/access.log json_combined;
error_log  /var/log/nginx/error.log warn;
```

### Nginx: генерация $request_id

```nginx
# В http{} блоке
log_format json_combined escape=json
    '{'
        '"request_id":"$request_id",'
        '"remote_addr":"$remote_addr",'
        '"method":"$request_method",'
        '"uri":"$request_uri",'
        '"status":$status,'
        '"request_time":$request_time'
    '}';

server {
    listen 80;
    server_name api.example.com;

    location / {
        proxy_set_header X-Request-ID $request_id;
        proxy_pass http://api_backend;
    }
}
```

### HAProxy: формат логов HTTP

```haproxy
frontend http-in
    bind *:80
    option httplog
    log /dev/log local0 info
```

### Ротация логов (Logrotate)

```bash
# /etc/logrotate.d/nginx
/var/log/nginx/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        [ -f /var/run/nginx.pid ] && kill -USR1 `cat /var/run/nginx.pid`
    endscript
}
```

### Централизованное логирование

| Инструмент | Роль | Особенности |
| :--- | :--- | :--- |
| **Fluentd** | Collector | Поддерживает 500+ плагинов; CNCF |
| **Fluent Bit** | Lightweight collector | Меньше ресурсов; подходит для edge |
| **Loki** | Log aggregation | Индексирует labels, а не полный текст; дешевле Elasticsearch |
| **Elasticsearch** | Search & analytics | Полнотекстовый поиск; высокое потребление памяти |
| **Grafana** | Visualization | Подключение к Loki/Elasticsearch для дашбордов |

## Практические инструменты

### tcpdump — захват пакетов

```bash
# Захват HTTP-трафика на интерфейсе eth0, порт 80
tcpdump -i eth0 -n port 80 -w /tmp/http.pcap

# Фильтр по хосту
tcpdump -i eth0 -n host api.example.com and port 443 -w /tmp/api.pcap

# Отображение HTTP-запросов в реальном времени
tcpdump -i eth0 -n -A -s 0 port 80 | grep -i "GET\|POST\|Host:"

# Анализ TLS Client Hello (SNI, cipher suites)
tcpdump -i eth0 -n -s 0 -vvv port 443 | grep -E "Client Hello|Server Hello|Cipher|Extension: server_name"
```

### ngrep — grep для сетевых пакетов

```bash
# Поиск HTTP GET-запросов
ngrep -q -d eth0 -W byline "^GET |^POST " tcp port 80

# Поиск по заголовку Host
ngrep -q -d eth0 -W byline "Host: api.example.com" tcp port 80

# Поиск HTTP-ответов
ngrep -q -d eth0 -W byline "HTTP/1\.[01] [45][0-9][0-9]" tcp port 80
```

### tshark (Wireshark CLI) — анализ протоколов

```bash
# Статистика HTTP-методов
tshark -r /tmp/http.pcap -Y "http.request.method" -T fields -e http.request.method | sort | uniq -c

# Извлечение URI
tshark -r /tmp/http.pcap -Y "http.request" -T fields -e http.request.uri | head -20

# Анализ TCP retransmissions
tshark -r /tmp/http.pcap -Y "tcp.analysis.retransmission" -T fields -e ip.src -e ip.dst -e tcp.analysis.retransmission
```

### wrk — нагрузочное тестирование

```bash
# Базовый тест: 12 потоков, 400 соединений, 30 секунд
wrk -t12 -c400 -d30s http://api.example.com/

# С кастомным Lua-скриптом для POST
wrk -t12 -c400 -d30s -s post.lua http://api.example.com/

# post.lua
wrk.method = "POST"
wrk.body   = '{"query":"test"}'
wrk.headers["Content-Type"] = "application/json"
```

### ab (ApacheBench) — простое нагрузочное тестирование

```bash
# 1000 запросов, 100 параллельных
ab -n 1000 -c 100 http://api.example.com/

# С POST-запросом
ab -n 1000 -c 50 -p post.json -T application/json http://api.example.com/api/
```

### hey — современный аналог ab

```bash
# 1000 запросов, 100 параллельных, 30 секунд
hey -n 1000 -c 100 -z 30s http://api.example.com/

# С заголовками
hey -n 1000 -c 100 -H "Authorization: Bearer token" http://api.example.com/api/
```

### ss — анализ сокетов

```bash
# Все установленные соединения на порту 80
ss -tn state established '( dport = :80 )'

# Счётчик соединений по состоянию
ss -s

# Детализация по процессам
ss -tnp | grep nginx

# UDP-соединения (QUIC/HTTP/3)
ss -u -a | grep :443
```

### openssl s_client — TLS диагностика

```bash
# Проверка сертификата и цепочки
openssl s_client -connect api.example.com:443 -servername api.example.com

# Проверка cipher suites
openssl s_client -connect api.example.com:443 -servername api.example.com -cipher 'ECDHE+AESGCM'

# Проверка ALPN
openssl s_client -connect api.example.com:443 -alpn h2,h3 -servername api.example.com

# Проверка OCSP staple
openssl s_client -connect api.example.com:443 -status -servername api.example.com

# Проверка TLS 1.3 only
openssl s_client -connect api.example.com:443 -tls1_3 -servername api.example.com
```

### mitmproxy — отладка и replay

```bash
# Запуск прокси на порту 8080
mitmproxy --listen-port 8080

# Запись в файл
mitmproxy -w /tmp/traffic.flow

# Повторный replay записей
mitmdump -nr /tmp/traffic.flow --mode reverse:http://api.example.com

# Изменение запросов на лету (inline script)
mitmproxy -s modify_headers.py
```

## Практические сценарии

### Сценарий 1: Структурированные логи Nginx в JSON

Конфигурация с Correlation ID:

```nginx
http {
    log_format json_combined escape=json
        '{'
            '"request_id":"$request_id",'
            '"time":"$time_iso8601",'
            '"remote_addr":"$remote_addr",'
            '"method":"$request_method",'
            '"uri":"$request_uri",'
            '"status":$status,'
            '"request_time":$request_time,'
            '"upstream_response_time":"$upstream_response_time",'
            '"bytes_sent":$body_bytes_sent,'
            '"http_referer":"$http_referer",'
            '"http_user_agent":"$http_user_agent",'
            '"http_host":"$http_host"'
        '}';

    access_log /var/log/nginx/access.log json_combined;
    error_log  /var/log/nginx/error.log warn;
}
```

**Валидация:**
- `tail -f /var/log/nginx/access.log | jq .` — валидный JSON.
- Каждая строка содержит `request_id`, `status`, `request_time`.

### Сценарий 2: Корреляция логов через Request ID

Генерация Request ID в Nginx и передача в приложение:

```nginx
server {
    listen 80;
    server_name api.example.com;

    location / {
        proxy_set_header X-Request-ID $request_id;
        proxy_pass http://api_backend;
    }
}
```

Приложение (Python):
```python
import logging
from flask import request

request_id = request.headers.get("X-Request-ID", "-")
logger = logging.getLogger("app")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    '{"time":"%(asctime)s","request_id":"' + request_id + '","level":"%(levelname)s","msg":"%(message)s"}'
))
logger.addHandler(handler)
```

**Валидация:**
- `curl -H "X-Request-ID: test-123" http://api.example.com/` — в логах Nginx и приложения `request_id = "test-123"`.
- `grep "test-123" /var/log/nginx/access.log /var/log/app/app.log` — обе строки найдены.

### Сценарий 3: Анализ 502/504 через tcpdump

```bash
# Захват трафика между Nginx и бэкендом
tcpdump -i any -n host 10.0.1.10 and port 8080 -w /tmp/backend.pcap

# Анализ в tshark
tshark -r /tmp/backend.pcap -Y "tcp.analysis.retransmission" -T fields -e ip.src -e ip.dst -e tcp.analysis.retransmission

# Проверка RST-пакетов
tshark -r /tmp/backend.pcap -Y "tcp.flags.reset == 1" -T fields -e ip.src -e ip.dst -e tcp.flags
```

**Валидация:**
- При 504: `tcpdump` показывает, что Nginx отправил RST бэкенду (бэкенд не ответил за `proxy_read_timeout`).
- При 502: бэкенд закрыл соединение до отправки ответа (RST от бэкенда).

### Сценарий 4: Нагрузочное тестирование wrk

```bash
# 12 потоков, 400 соединений, 30 секунд, Lua-скрипт с POST
wrk -t12 -c400 -d30s -s post_json.lua http://api.example.com/api/

# post_json.lua
wrk.method = "POST"
wrk.body = '{"name":"test","email":"test@example.com"}'
wrk.headers["Content-Type"] = "application/json"
wrk.headers["Authorization"] = "Bearer token123"
```

**Валидация:**
- Вывод wrk: `Latency`, `Req/Sec`, `Requests/sec`, `Transfer/sec`.
- Сравнение до/после оптимизации: latency p99 уменьшился в 2 раза.

### Сценарий 5: Анализ соединений через ss

```bash
# Активные соединения к порту 80/443
ss -tn state established '( dport = :80 or dport = :443 )' | wc -l

# Соединения в TIME-WAIT
ss -tn state time-wait '( dport = :80 )' | wc -l

# Группировка по состоянию
ss -s

# Детализация с процессами
ss -tnp | grep nginx
```

**Валидация:**
- `ss -s` — `time-wait` > 10000 при высокой нагрузке (нормально для коротких HTTP/1.1 соединений).
- `ss -tnp` — много `ESTAB` на `10.0.1.10:8080` — бэкенд перегружен.

### Сценарий 6: TLS диагностика через openssl

```bash
# Полная проверка TLS-соединения
openssl s_client -connect api.example.com:443 -servername api.example.com -brief

# Проверка cipher suites
openssl s_client -connect api.example.com:443 -servername api.example.com \
  -cipher 'ECDHE+AESGCM:ECDHE+CHACHA20' -brief

# Проверка OCSP staple
openssl s_client -connect api.example.com:443 -status -servername api.example.com -brief

# Проверка HTTP/2 (ALPN)
openssl s_client -connect api.example.com:443 -alpn h2 -servername api.example.com -brief
```

**Валидация:**
- `OCSP Response Status: successful` — OCSP stapling работает.
- `ALPN protocol: h2` — HTTP/2 включён.
- `Cipher    : TLS_AES_256_GCM_SHA384` — только современные cipher suites.

### Сценарий 7: Отладка через mitmproxy

```bash
# Запуск с записью
mitmproxy --listen-port 8080 -w /tmp/session.flow

# Настройка клиента (curl)
curl -x http://localhost:8080 https://api.example.com/ -k

# Повторный replay через mitmdump
mitmdump -nr /tmp/session.flow --mode reverse:http://api.example.com

# Изменение заголовков на лету (modify_headers.py)
def request(flow):
    flow.request.headers["X-Forwarded-For"] = "1.2.3.4"
```

**Валидация:**
- В mitmproxy: запросы и ответы отображаются с раскладкой.
- После replay: сервер получает изменённые заголовки.

## Типичные проблемы и диагностика

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Слишком большие логи** | Диск заполнен за часы | `du -sh /var/log/nginx/` | Настроить logrotate, компрессию, retention |
| **Нет Correlation ID** | Невозможно связать логи прокси и приложения | `grep -c "request_id" access.log` | Добавить `$request_id` в Nginx log_format |
| **Таймауты в tcpdump** | Медленные запросы без ответов | `tshark -r file.pcap -Y "tcp.analysis.retransmission"` | Увеличить `proxy_read_timeout` |
| **Высокий TIME-WAIT** | Много соединений в `TIME-WAIT` | `ss -s` | Включить `net.ipv4.tcp_tw_reuse = 1` |
| **RST-пакеты** | Соединения разрываются до завершения | `tcpdump ... 'tcp[tcpflags] & tcp-rst != 0'` | Проверить `client_body_timeout`, `send_timeout` |
| **Неверный SNI** | Сервер возвращает не тот сертификат | `openssl s_client -connect host:443 -servername wrong` | Проверить `server_name` в Nginx |
| **Cipher mismatch** | `ssl_choose_cipher` — нет общих cipher suites | `openssl s_client -connect host:443 -cipher '...'` | Обновить `ssl_ciphers` на сервере |
| **Slow HTTP-заголовки** | Slowloris: медленная отправка заголовков | `tcpdump -i eth0 -n -A port 80` — неполные заголовки | `client_header_timeout 10s; limit_conn` |
| **DNS-задержки в логах** | Высокий `request_time` при быстром `upstream_response_time` | `$request_time - $upstream_response_time` — разница > RTT | Проверить DNS (`dig`, `resolver`) |
| **JSON parse error** | Логи не парсятся в ELK/Loki | `jq . < access.log` — ошибка | Проверить `escape=json` и кавычки в `log_format` |

## Лучшие практики

1. **JSON-логи для всех компонентов:** Nginx, HAProxy, приложения — единый формат. Упрощает парсинг и корреляцию.
2. **Request ID на всех уровнях:** Генерация в Nginx (`$request_id`), передача через `X-Request-ID`, логирование в приложении.
3. **logrotate с compression:** `compress`, `delaycompress`, retention 30–90 дней. Для JSON-логов compression даёт 90% сжатия.
4. **Structured logging (JSON):** Каждое поле — отдельный ключ. Не используйте `printf` в production.
5. **`$upstream_response_time` в access log:** Критично для диагностики медленных бэкендов.
6. **`client_header_timeout` и `client_body_timeout`:** Защита от slowloris. `10s` для заголовков, `60s` для тела.
7. **`tcpdump` с BPF filters:** Используйте `host`, `port`, `tcp flags` для минимизации захвата. Не записывайте весь трафик без фильтра.
8. **`ss` вместо `netstat`:** `ss` быстрее и показывает больше информации (TCP info, процессы).
9. **`wrk`/`hey` вместо `ab`:** Современные инструменты поддерживают keepalive, HTTP/2, Lua-скрипты.
10. **`openssl s_client` для TLS-аудит:** Регулярно проверяйте cipher suites, ALPN, OCSP staple.
11. **mitmproxy для API-отладки:** Лучше, чем `curl -v` для сложных сценариев (replay, модификация).
12. **Централизованное логирование:** Loki + Grafana или ELK. Не храните логи только на хосте.

## Граничные случаи и ограничения

1. **JSON-логи и размер строки:** Очень длинные URI или User-Agent могут превысить лимиты лог-файлов. Обрезайте или хэшируйте чувствительные данные.
2. **`$request_id` и load balancer:** Если за Nginx стоит HAProxy, генерируйте Request ID на HAProxy (через `http-request set-var`) или на приложении.
3. **`ss` и permissions:** Для просмотра процессов (`-p`) требуются root-привилегии. В контейнерах без `SYS_PTRACE` capability `ss -tnp` не покажет PIDs.
4. **`tcpdump` и MTU:** При захвате на интерфейсе с jumbo frames (MTU > 1500) увеличьте snaplen (`-s 0` для полного захвата).
5. **`wrk` и keepalive:** wrk использует keepalive по умолчанию. Для тестирования коротких соединений добавьте `--no-keepalive`.
6. **`ab` и HTTP/2:** ApacheBench не поддерживает HTTP/2. Используйте `wrk` или `hey` с `--http2`.
7. **`openssl s_client` и SNI:** Без `-servername` проверка не пройдёт для shared hosting (SNI). Всегда указывайте домен.
8. **mitmproxy и mTLS:** Для отладки mTLS добавьте корневой сертификат mitmproxy в trust store клиента/сервера.
9. **logrotate и file descriptors:** Nginx открывает log-файлы при старте. После logrotate он не переоткрывает файлы автоматически. Используйте `kill -USR1`.
10. **Централизованное логирование и latency:** Отправка логов по сети (Fluentd → Loki) добавляет 1–5ms latency. Для high-throughput сервисов используйте sidecar-паттерн или async shipping.

## Дополнительная информация

### Loki: эффективное хранение логов

```yaml
# promtail-config.yaml (агент для сбора логов)
server:
  http_listen_port: 9080

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: nginx
    static_configs:
      - targets:
          - localhost
        labels:
          job: nginx
          __path__: /var/log/nginx/*.log
```

### ngrep: фильтры для HTTP

```bash
# Только POST-запросы
ngrep -q -d eth0 -W byline "^POST " tcp port 80

# Поиск по заголовку Authorization
ngrep -q -d eth0 -W byline "Authorization: Bearer" tcp port 443

# HTTP-ответы с 5xx
ngrep -q -d eth0 -W byline "HTTP/1\.[01] 5[0-9][0-9]" tcp port 80
```

### Анализ pcap через tshark

```bash
# Top 10 IP по количеству запросов
tshark -r /tmp/http.pcap -Y "http.request" -T fields -e ip.dst | sort | uniq -c | sort -rn | head -10

# Распределение latency (TCP)
tshark -r /tmp/http.pcap -Y "tcp.flags.fin==1" -T fields -e tcp.analysis.ack_rtt | sort -n | uniq -c
```

## Смотрите также

- **[HTTP-серверы и прокси](./http_servers_proxies.md)** — конфигурация логирования в Nginx/HAProxy.
- **[Наблюдаемость HTTP-сервисов](./http_monitoring_observability.md)** — корреляция логов с метриками и трассировками.
- **[Тонкая настройка соединений](./http_connection_management.md)** — `client_header_timeout`, `client_body_timeout`.
- **[Коды ответа HTTP](./http_status_codes.md)** — диагностика ошибок по логам.
- **[Диагностика Nginx](../../../WebServers/Nginx/Operations/nginx_troubleshooting.md)** — анализ error log.
