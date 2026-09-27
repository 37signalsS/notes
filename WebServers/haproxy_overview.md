# HAProxy

## Определения

**HAProxy** — высокопроизводительный балансировщик нагрузки и прокси-сервер для TCP/HTTP-приложений. Стандарт де-факто для распределения трафика в высоконагруженных системах. Обеспечивает отказоустойчивость, горизонтальное масштабирование и интеллектуальную маршрутизацию запросов.

**Frontend** — точка входа, определяющая IP/порт для приёма запросов и правила маршрутизации (ACL).

**Backend** — группа серверов, обрабатывающих запросы, с алгоритмами балансировки и проверкой состояния.

**Listener** — объединение frontend и backend в одной секции (`listen`), удобно для простых TCP/UDP конфигураций.

**ACL (Access Control List)** — механизм фильтрации и маршрутизации на основе условий запроса (IP, path, заголовки, cookies).

**Stick Table** — механизм хранения состояний в оперативной памяти HAProxy для реализации session persistence, rate limiting и защиты от DDoS/brute-force.

**Runtime API** — встроенный интерфейс для управления состоянием балансировщика в реальном времени через UNIX-сокет или TCP без перезагрузки конфигурации.

**PROMEX** — встроенный модуль Prometheus-экспортёра, компилируемый с флагом `USE_PROMEX=1` и активируемый директивой `http-request use-service prometheus-exporter`.

**OpenTelemetry filter** — нативный фильтр HAProxy 3.4+ для отправки трейсов, метрик и логов в OTLP-совместимые коллекторы.

---

## Основные концепции

### Архитектура и схема работы

HAProxy использует событийную модель (event loop) с поддержкой многопоточности (`nbthread`). В версии 3.4 LTS архитектура включает:

- **Master-процесс** — управляет worker-процессами, выполняет graceful reload через `SIGUSR2`.
- **Worker-процессы** — обрабатывают соединения, каждый поток имеет собственную событийную петлю.
- **Потоки (nbthread)** — привязываются к ядрам CPU через `cpu-map auto`, обеспечивая линейное масштабирование.

**Параметры запуска:**
- `-W` — master-worker режим (аналог `master-worker` в `global`).
- `-Ws` — master-worker с поддержкой `notify` для systemd.
- `-f` — путь к конфигурационному файлу (можно указать несколько для инкрементальной конфигурации).

**Схема обработки запроса:**
1. Клиент отправляет запрос на виртуальный IP (VIP).
2. HAProxy принимает запрос, выполняет TLS-терминацию (если настроено) и анализирует заголовки (`mode http`).
3. На основе ACL выбирается нужный `backend` и алгоритм балансировки.
4. Запрос перенаправляется на сервер, ответ возвращается клиенту.

### Режимы работы (mode)

| Режим | Уровень OSI | Что анализирует | Особенности |
| :--- | :--- | :--- | :--- |
| **`mode tcp`** | L4 (транспортный) | IP, порт, SNI, TLS-рукопожатие | Максимальная производительность, прозрачность для TLS |
| **`mode http`** | L7 (прикладной) | Заголовки, path, cookies, методы | Поддержка HTTP/2 и HTTP/3 (QUIC), ACL по контенту |

**Критично для ACL:** если прокси работает в `mode tcp`, правила ACL по HTTP-заголовкам, path или cookies **не сработают**, так как HAProxy не разбирает протокол прикладного уровня.

### Алгоритмы балансировки

| Алгоритм | Описание | Сценарий |
| :--- | :--- | :--- |
| **`roundrobin`** | Запросы распределяются поочерёдно, поддержка весов | По умолчанию, подходит для большинства HTTP-приложений |
| **`leastconn`** | Запрос идёт на сервер с наименьшим числом активных соединений | Длинные TCP-сессии (БД, WebSocket), HTTP с переменной нагрузкой |
| **`source`** | Хеширование IP клиента → фиксированный сервер | Session affinity без использования Cookies |
| **`uri`** | Хеширование URI → один ресурс на один сервер | Оптимизация кэширования, CDN |
| **`url_param`** | Балансировка по параметру в URL | Персонализированная или сегментированная маршрутизация |
| **`hdr`** | Хеширование HTTP-заголовка (User-Agent, Cookie) | A/B тестирование, канареечные релизы |
| **`first`** | Заполнение сервера до лимита `maxconn`, затем переход к следующему | Экономия ресурсов, консолидация нагрузки |
| **`random`** | Случайный выбор сервера | Простые сценарии без жестких требований к распределению |

### Наблюдаемость (Observability)

Современный HAProxy (v3.2+) предоставляет:

- **Prometheus Native Exporter (PROMEX):** встроенная поддержка экспорта метрик на эндпоинт `/metrics`. Требует компиляции с `USE_PROMEX=1` или использования образа с предустановленным модулем. Активация: `http-request use-service prometheus-exporter if { path /metrics }`.
- **OpenTelemetry filter:** нативная поддержка отправки трейсов и метрик в OTLP-совместимые коллекторы через фильтр, загружаемый в HAProxy 3.4+.
- **Runtime API:** управление состоянием серверов, просмотр статистики и изменение весов в реальном времени через UNIX-сокет без перезагрузки конфигурации.

### Безопасность

- **Валидация JWT:** возможность проверки токенов авторизации непосредственно на балансировщике перед проксированием запроса к бэкенду.
- **Stick Tables:** механизм хранения состояний в оперативной памяти для защиты от DDoS, перебора паролей (Brute-force) и реализации Rate Limiting.
- **SSL/TLS Hardening:** поддержка TLS 1.3, автоматизация ACME (Let's Encrypt), поддержка OCSP Stapling и строгие профили шифрования.

### Известные уязвимости (CVE)

- **CVE-2026-55203:** целочисленное переполнение в обработке FastCGI-записей через 3.4.0. Исправлено в коммите `5985276`.
- **CVE-2026-55204:** нулевой указатель в `hpack_dht_insert()` при исчерпании памяти. Исправлено в коммите `9a6d1fe`.

Рекомендуется использовать версию 3.4.1 или выше.

### Жизненный цикл запроса

```
Клиент → Frontend (ACL, TLS) → Backend (алгоритм, health check) → Сервер
    ↑                                                              |
    └──────────────────────────────────────────────────────────────┘
```

---

## Установка и базовая конфигурация

### Установка

**Debian/Ubuntu:**
```bash
apt update && apt install -y haproxy
# → haproxy is installed
haproxy -vv | head -5
# → HA-Proxy version 3.4.x ...
```

**RHEL/CentOS/AlmaLinux:**
```bash
dnf install -y haproxy
systemctl enable --now haproxy
```

**Docker:**
```bash
docker run -d --name haproxy \
  -p 80:80 -p 443:443 -p 8405:8405 \
  -v ./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro \
  --cap-add=NET_ADMIN \
  haproxy:3.4
```

### Структура конфигурации

```haproxy
global
    log /dev/log local0
    maxconn 4096
    nbthread 4
    cpu-map auto:1/1-4 0-3
    master-worker

defaults
    log     global
    mode    http
    option  httplog
    timeout connect 5s
    timeout client  50s
    timeout server  50s
```

---

## Практические сценарии

### Базовая балансировка HTTP (L7)

```haproxy
frontend http_frontend
    bind *:80
    mode http
    default_backend http_backend

backend http_backend
    mode http
    balance leastconn
    option forwardfor
    server web01 192.168.131.33:8080 check
    server web02 192.168.131.34:8080 check
```

### Терминация SSL/TLS и HTTP/2

```haproxy
frontend https_frontend
    bind *:443 ssl crt /etc/haproxy/certs/site.pem alpn h2,http/1.1
    mode http
    http-request redirect scheme https unless { ssl_fc }
    default_backend http_backend
```

### Настройка HTTP/3 (QUIC)

Требует HAProxy 3.0+ и QUIC-совместимой TLS-библиотеки.

```haproxy
frontend quic_frontend
    bind *:443 ssl crt /etc/haproxy/certs/site.pem alpn h3,h2,http/1.1
    bind *:443 quic4 alpn h3
    http-after-response add-header alt-svc 'h3=":443"; ma=60'
    default_backend http_backend
```

**Примечание:** UDP-порт 443 должен быть доступен на фаérволе. В сетях, где UDP заблокирован, используйте QMux (HTTP/3 over TCP), доступный в 3.4+.

### Проброс SSL/TLS (Passthrough)

```haproxy
frontend https_passthrough
    bind *:443
    mode tcp
    default_backend https_backend

backend https_backend
    mode tcp
    balance roundrobin
    server web01 192.168.131.33:443 check
```

### Балансировка kube-apiserver (bare-metal)

```haproxy
frontend k8s_api
    bind *:6443
    mode tcp
    default_backend k8s_api_backend

backend k8s_api_backend
    mode tcp
    balance roundrobin
    option httpchk GET /healthz
    http-check expect status 200
    server master1 192.168.1.11:6443 check check-ssl verify none inter 3s fall 3 rise 2
    server master2 192.168.1.12:6443 check check-ssl verify none inter 3s fall 3 rise 2
    server master3 192.168.1.13:6443 check check-ssl verify none inter 3s fall 3 rise 2
```

### Отказоустойчивая балансировка PostgreSQL (Patroni)

```haproxy
backend postgres_backend
    mode tcp
    option httpchk
    http-check expect status 200
    default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions

    server pg_node1 192.168.10.10:5432 maxconn 100 check port 8008
    server pg_node2 192.168.10.11:5432 maxconn 100 check port 8008
```

---

## Продвинутые паттерны

### Stick Tables: Rate Limiting и защита от Brute-force

Stick Tables — механизм хранения состояний в разделяемой памяти HAProxy. Позволяет реализовать rate limiting, защиту от перебора и sticky sessions без внешних зависимостей.

```haproxy
frontend http_frontend
    bind *:80
    mode http

    # Определяем stick table в памяти
    stick-table type ip size 200k expire 30s store http_req_rate(10s),conn_cur,bytes_out

    # Проверка rate limit: > 100 запросов за 10 секунд
    http-request deny deny_status 429 if { sc_http_req_rate(0) gt 100 }

    # Лимит одновременных соединений с одного IP
    http-request deny deny_status 429 if { sc_conn_cur(0) gt 50 }

    # Защита от фазеров (ботов): если > 1MB исходящего трафика за период
    http-request deny deny_status 429 if { sc_bytes_out_rate(0) gt 10485760 }

    default_backend http_backend
```

**Stick Table для session persistence (sticky cookies):**

```haproxy
backend http_backend
    mode http
    balance roundrobin
    cookie SERVERID insert indirect nocache

    stick-table type ip size 50k expire 30m
    stick on src

    server web01 192.168.1.10:8080 check cookie s1
    server web02 192.168.1.11:8080 check cookie s2
```

### Продвинутые Health Checks

#### Agent Check (детальная проверка здоровья)

Агент на бэкенде возвращает JSON с метриками. HAProxy может решать, исключать ли сервер из ротации на основе этих данных.

```haproxy
backend app_backend
    mode http
    option agent-check
    agent-inter 5s           # Интервал опроса агента
    agent-port 9999          # Порт агента на бэкенде
    agent-check expect string "status=healthy"

    default-server inter 3s fall 3 rise 2

    server app01 10.0.0.1:8080 check agent-port 9999
    server app02 10.0.0.2:8080 check agent-port 9999
```

**Пример агента на Python (бэкенд):**

```python
#!/usr/bin/env python3
import http.server
import json
import psutil

class AgentHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory().percent
        status = "healthy" if cpu < 80 and mem < 85 else "unhealthy"
        response = json.dumps({"status": status, "cpu": cpu, "mem": mem})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(response.encode())

http.server.HTTPServer(('0.0.0.0', 9999), AgentHandler).serve_forever()
```

#### On-marked-down / On-marked-up действия

```haproxy
backend rolling_deploy_backend
    mode http
    balance roundrobin

    # При падении сервера: завершить все сессии
    default-server on-marked-down shutdown-sessions

    # При восстановлении: плавно вернуть в ротацию
    default-server on-marked-up slowstart 60s

    server app01 10.0.0.1:8080 check inter 3s fall 3 rise 2
    server app02 10.0.0.2:8080 check inter 3s fall 3 rise 2
```

### Runtime API: управление на лету

HAProxy позволяет управлять состоянием без перезагрузки через UNIX-сокет:

```bash
# Просмотр статистики всех серверов
echo "show stat" | socat stdio /var/run/haproxy/admin.sock

# Просмотр информации о конкретном бэкенде
echo "show stat app_backend" | socat stdio /var/run/haproxy/admin.sock

# Вывести сервер из ротации (для деплоя)
echo "set server app_backend/app01 state drain" | socat stdio /var/run/haproxy/admin.sock

# Полностью отключить сервер
echo "set server app_backend/app01 state maint" | socat stdio /var/run/haproxy/admin.sock

# Вернуть сервер в ротацию
echo "set server app_backend/app01 state ready" | socat stdio /var/run/haproxy/admin.sock

# Изменить вес (для canary-релизов)
echo "set server app_backend/app01 weight 10%" | socat stdio /var/run/haproxy/admin.sock

# Показать информацию о сервере
echo "show servers state app_backend" | socat stdio /var/run/haproxy/admin.sock

# Проверить соединения на сервере
echo "show sess" | socat stdio /var/run/haproxy/admin.sock | grep app01
```

### Connection Draining для graceful деплоя

Паттерн плавного обновления серверов через HAProxy:

```bash
#!/bin/bash
# rolling_deploy.sh — пошаговое обновление серверов

BACKEND="app_backend"
SERVERS=("app01" "app02" "app03")
SOCKET="/var/run/haproxy/admin.sock"
DRAIN_WAIT=30  # секунд на завершение соединений

for SERVER in "${SERVERS[@]}"; do
    echo "=== Обновление $SERVER ==="

    # 1. Вывести из ротации (drain — новые соединения не идут, старые завершаются)
    echo "set server ${BACKEND}/${SERVER} state drain" | socat stdio "$SOCKET"
    echo "  → $SERVER в drain mode"

    # 2. Ждём завершения соединений
    sleep "$DRAIN_WAIT"

    # 3. Полностью в maint (для обновления)
    echo "set server ${BACKEND}/${SERVER} state maint" | socat stdio "$SOCKET"
    echo "  → $SERVER в maint (обновление...)"

    # 4. Здесь: деплой нового кода (ansible, docker pull, etc.)
    # ansible-playbook -l "$SERVER" deploy.yml

    # 5. Вернуть в ротацию
    echo "set server ${BACKEND}/${SERVER} state ready" | socat stdio "$SOCKET"
    echo "  → $SERVER вернулся в ротацию"

    # 6. Проверяем здоровье
    sleep 5
    echo "show stat ${BACKEND}" | socat stdio "$SOCKET" | grep "$SERVER" | awk -F',' '{print "  Status:", $18}'
done
```

### Prometheus-метрики HAProxy

```haproxy
frontend stats
    bind *:8405
    mode http
    stats enable
    stats uri /stats
    stats refresh 10s

    # Нативный Prometheus endpoint
    http-request use-service prometheus-exporter if { path /metrics }

    # Ограничение доступа к метрикам
    http-request allow if { path /metrics } src 10.0.0.0/8
    http-request deny if { path /metrics }
```

**Ключевые PromQL-запросы:**

```promql
# QPS по бэкендам
rate(haproxy_backend_http_requests_total[5m])

# Ошибки бэкендов
rate(haproxy_backend_http_responses_total{code=~"5.."}[5m])

# Латентность бэкендов
histogram_quantile(0.99, rate(haproxy_backend_http_request_duration_seconds_bucket[5m]))

# Активные соединения
haproxy_backend_current_sessions

# Серверы в down/мaint
haproxy_server_status{status=~"down|maint"}
```

---

## Операции и команды

### Управление службой (systemd)

```bash
systemctl start haproxy
# → служба запущена

systemctl restart haproxy
# → полная перезагрузка с разрывом соединений

systemctl reload haproxy
# → graceful reload без потерь соединений (SIGUSR2 мастеру)

systemctl status haproxy
# → active (running) since ...

haproxy -c -f /etc/haproxy/haproxy.cfg
# → Configuration file is valid
```

### Проверка конфигурации

```bash
haproxy -c -f /etc/haproxy/haproxy.cfg
# → Configuration file is valid

haproxy -c -f /etc/haproxy/haproxy.cfg -d
# → детальный вывод с locating errors
```

### Runtime API (UNIX-сокет)

```bash
# Просмотр статистики
echo "show stat" | socat stdio /var/run/haproxy/admin.sock

# Общая информация
echo "show info" | socat stdio /var/run/haproxy/admin.sock

# Изменение веса сервера
echo "set weight backend/server 50" | socat stdio /var/run/haproxy/admin.sock

# Вывод сервера из ротации (drain)
echo "set server app_backend/app01 state drain" | socat stdio /var/run/haproxy/admin.sock

# Полное отключение (maint)
echo "set server app_backend/app01 state maint" | socat stdio /var/run/haproxy/admin.sock

# Возврат в ротацию
echo "set server app_backend/app01 state ready" | socat stdio /var/run/haproxy/admin.sock

# Просмотр сессий
echo "show sess" | socat stdio /var/run/haproxy/admin.sock | grep app01
```

### Логирование

```bash
# Просмотр логов через journalctl
journalctl -u haproxy -f

# Поиск по флагам завершения
journalctl -u haproxy | grep -E "(CD|sC|cC|PH)"
```

---

## Устранение неисправностей

### Конфигурация не применяется

**Причины:**
- Синтаксическая ошибка в `haproxy.cfg`.
- Использование `restart` вместо `reload` (потеря соединений может выглядеть как падение).
- Права доступа к файлу сертификата.

**Диагностика:**
```bash
haproxy -c -f /etc/haproxy/haproxy.cfg
# → если есть ошибки, вывод указает строку

journalctl -u haproxy -n 50
# → поиск "[ALERT]" или "[WARNING]"
```

### ACL не срабатывает

**Причины:**
- Неправильный `mode` (tcp вместо http) — ACL по заголовкам не работает в TCP.
- Порядок правил: общий `default_backend` перехватывает запрос до специфичного ACL.
- Директивы `http-request` размещены после `use_backend`.

**Решение:** убедитесь, что `mode http` установлен, специфичные правила находятся выше общих, а `http-request` directives — до `use_backend`.

### Серверы в состоянии DOWN

**Причины:**
- Недоступен порт или health-эндпоинт.
- Таймаут проверки короче времени отклика бэкенда.
- TLS-проверка не проходит из-за невалидного сертификата.

**Диагностика:**
```bash
echo "show stat" | socat stdio /var/run/haproxy/admin.sock | grep -E ",DOWN,|,MAINT,"
# → вывод серверов с проблемами

curl -k https://backend:443/healthz
# → проверка доступности вручную
```

### Высокое потребление памяти

**Причины:**
- Слишком большой `maxconn` без ограничений на бэкенды.
- Большие stick tables без `expire`.
- Утечка в Lua-скриптах или SPOE-агентах.

**Диагностика:**
```bash
echo "show info" | socat stdio /var/run/haproxy/admin.sock | grep -i mem
# → MemAlloc, MaxMemory

ps aux | grep haproxy
# → проверка количества процессов/потоков
```

### Ошибки 502/503/504

| Код | Причина | Решение |
| :--- | :--- | :--- |
| **502** | Бэкенд закрыл соединение или вернул невалидный ответ | Проверьте логи бэкенда, увеличьте `timeout server` |
| **503** | Нет доступных серверов в ротации | Проверьте health checks, статус серверов через Runtime API |
| **504** | Таймаут ожидания ответа от бэкенда | Увеличьте `timeout server`, проверьте сетевую задержку |

---

## Лучшие практики

### Таймауты и лимиты

- `timeout connect 5s` — время на установку соединения с бэкендом.
- `timeout client 50s` — ожидание данных от клиента.
- `timeout server 50s` — ожидание ответа от сервера.
- `timeout http-request 10s` — защита от атак Slowloris.
- `timeout tunnel 1h` — для WebSocket-соединений.

### Системные настройки (sysctl)

```bash
net.ipv4.ip_nonlocal_bind = 1
# позволяет запускаться на IP, не назначенном интерфейсу (для Keepalived)

fs.file-max = 1000000
# лимит файловых дескрипторов для поддержки большого числа соединений

net.core.somaxconn = 65535
# размер очереди слушающих сокетов

net.ipv4.tcp_syncookies = 1
# защита от SYN flood
```

### Безопасность и изоляция

- **Изоляция:** используйте `chroot /var/lib/haproxy`.
- **Привилегии:** запускайте от пользователя `user haproxy` и группы `group haproxy`.
- **maxconn:** ограничивайте максимальное число соединений на глобальном уровне и для бэкендов.
- **Мониторинг доступа к метрикам:** ограничьте `/metrics` и `/stats` внутренней сетью.

### Управление конфигурацией

- **Идемпотентность:** храните конфигурацию в VCS (git). Используйте `haproxy -c` в CI/CD пайплайнах.
- **Incremental config:** используйте `-f /etc/haproxy/conf.d/*.cfg` для разделения конфигурации на компоненты.
- **Резервное копирование:** берите backup `/etc/haproxy/haproxy.cfg` и сертификатов перед каждым изменением.

### Высокая доступность

- Используйте `master-worker` режим (`-Ws`) с systemd для graceful reload.
- Настройте Keepalived для плавающего VIP.
- Используйте `on-marked-down shutdown-sessions` для rolling deploy.
- Настройте `on-marked-up slowstart 60s` для плавного возврата серверов.

### Производительность

- **Многопоточность:** предпочитайте `nbthread` нескольким процессам.
- **CPU affinity:** используйте `cpu-map auto` для привязки потоков к ядрам.
- **HTTP/2 и HTTP/3:** включите ALPN (`alpn h2,http/1.1`), учитывайте overhead QUIC в high-throughput средах.
- **Buffer allocation:** в 3.4+ адаптивное выделение памяти снижает footprint.

---


### Graceful shutdown

HAProxy поддерживает graceful reload через `SIGUSR2` в master-worker режиме. Для graceful shutdown используйте `on-marked-down shutdown-sessions` в backend:

```haproxy
backend http_backend
    mode http
    balance roundrobin
    on-marked-down shutdown-sessions
    server web01 192.168.1.10:8080 check
    server web02 192.168.1.11:8080 check
```

В systemd установите `TimeoutStopSec=30`, чтобы SIGTERM давал воркерам время завершить активные сессии.

### CORS

```haproxy
frontend http_frontend
    bind *:80
    mode http
    http-response set-header Access-Control-Allow-Origin "https://app.example.com"
    http-response set-header Access-Control-Allow-Methods "GET, POST, OPTIONS"
    http-response set-header Access-Control-Allow-Headers "Authorization, Content-Type"
    http-response set-header Access-Control-Allow-Credentials "true"

    acl is_options method OPTIONS
    http-request return status 204 if is_options

    default_backend http_backend
```

### PROXY protocol

```haproxy
frontend http_frontend
    bind *:80
    bind *:443 accept-proxy
    mode http
    default_backend http_backend

backend http_backend
    mode http
    server web01 192.168.1.10:8080 check send-proxy
    server web02 192.168.1.11:8080 check send-proxy
```

### WebSocket и gRPC

```haproxy
frontend ws_frontend
    bind *:8080
    mode http
    timeout tunnel 1h
    default_backend ws_backend

backend ws_backend
    mode http
    server ws01 192.168.1.10:8080 check
    server ws02 192.168.1.11:8080 check

frontend grpc_frontend
    bind *:50051
    mode http
    timeout connect 5s
    timeout server  50s
    default_backend grpc_backend

backend grpc_backend
    mode http
    server grpc01 192.168.1.10:50051 check
```

### Disaster Recovery

*   **RPO:** 15 минут (ротация логов раз в день).
*   **RTO:** 30 минут (восстановление конфигурации из Git и развертывание на резервном сервере).
*   **Failover:** Keepalived для плавающего VIP.

---
## Дополнительная информация

### Сравнение с Nginx

HAProxy — это узкоспециализированный балансировщик («скальпель»), в то время как Nginx — универсальный веб-сервер («швейцарский нож»).

| Характеристика | HAProxy | Nginx (OSS) |
| :--- | :--- | :--- |
| **Специализация** | Только балансировка и проксирование | Веб-сервер + балансировщик |
| **Алгоритмы** | Огромный выбор (leastconn, uri, hdr, stick) | Ограниченный набор (round-robin, ip_hash) |
| **Здоровье бэкендов** | Активные глубокие проверки встроены | Только базовые (пассивные) в бесплатной версии |
| **Мониторинг** | Глубокая статистика через сокет и Runtime API | Базовая страница `stub_status` |

### См. также

- **[Сравнение балансировщиков: Nginx, Angie, HAProxy, Traefik](../Nginx/Proxy/Load_Balancing/additional_info_and_comparisons.md)**
- **[Keepalived: Обзор и настройка](../Networking/ServicesAndTools/keepalived_overview.md)**
- **[Отказоустойчивость PostgreSQL](../Databases/PostgreSQL/Concepts/high_availability.md)**
