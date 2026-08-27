# Connection Pooling (Пулы соединений)

## Определения

**Connection Pool (Пул соединений)** — механизм переиспользования ранее установленных сетевых соединений (обычно TCP) вместо создания нового для каждого запроса. Пул поддерживает фиксированный набор «тёплых» соединений между клиентом и сервером, которые передаются из одного запроса в другой без повторного TCP handshake и TLS negotiation.

**Проблема, которую решает:** Установка TCP-соединения требует 3-way handshake (1 RTT), а для HTTPS — ещё и TLS handshake (1-2 RTT). При высокой частоте запросов (тысячи RPS) эти накладные расходы становятся критичными: рост латентности, исчерпание ephemeral ports, перегрузка CPU на handshake.

**Эффективность:** Переиспользование соединения устраняет overhead handshake и экономит ресурсы как на стороне клиента, так и на стороне сервера. Для короткоживущих соединений (HTTP/1.0, health checks) пул позволяет поддерживать готовые TCP-сессии.

## Базовые концепции

### Жизненный цикл соединения в пуле

```
Клиент               Connection Pool              Backend (сервер)
  │                       │                            │
  │  1. Запрос            │                            │
  │ ─────────────────────►│                            │
  │                       │  2. Взять соединение из пула
  │                       │     (или создать новое)     │
  │                       │ ──────────────────────────►│
  │                       │                            │
  │                       │  3. Отправить запрос        │
  │                       │ ◄──────────────────────────│
  │                       │                            │
  │                       │  4. Получить ответ          │
  │                       │ ──────────────────────────►│
  │  5. Вернуть ответ     │                            │
  │ ◄─────────────────────│                            │
  │                       │                            │
  │                       │  6. Вернуть соединение в пул
  │                       │     (не закрывать!)         │
  │                       │                            │
```

### Ключевые параметры пула

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| **Min idle** | Минимальное количество «тёплых» соединений в пуле | Достаточно для покрытия базовой нагрузки (5-20) |
| **Max size** | Максимальное количество соединений в пуле | Не превышать `ulimit -n` / `worker_connections`; зависит от бэкенда |
| **Max lifetime** | Максимальное время жизни соединения в пуле | 300-600 сек; предотвращает утечки и устаревшие коннекты |
| **Idle timeout** | Время простоя соединения перед закрытием | 60-120 сек; освобождает ресурсы на бэкенде |
| **Connection timeout** | Таймаут на установку нового соединения | 5-10 сек; не должен быть слишком длинным |
| **Validation query** | Запрос для проверки работоспособности соединения | `SELECT 1` (DB), HTTP HEAD (web) |

### TCP Keepalive vs Connection Pool

Это разные механизмы, решающие разные задачи:

| Параметр | TCP Keepalive | Connection Pool |
| :--- | :--- | :--- |
| **Назначение** | Обнаружение «мёртвых» соединений | Переиспользование соединений |
| **Когда работает** | Наедине с соединением (no traffic) | При передаче данных |
| **Что делает** | Отправляет пустые ACK для проверки доступности хоста | Хранит готовые соединения для повторного использования |
| **Настраивается через** | `sysctl net.ipv4.tcp_keepalive_*` | Приложение / прокси / пул |
| **Влияние на производительность** | Минимальное (1 пакет каждые N сек) | Значительное (снижение handshake overhead) |

**Важно:** Keepalive НЕ переиспользует соединения — он только проверяет, жив ли удалённый хост. Connection pool — это механизм переиспользования. Оба механизма дополняют друг друга.

### Почемупулы необходимы

1. **Снижение латентности:** TCP handshake = 1 RTT (~1 мс в дата-центре, ~50 мс между континентами). TLS handshake = ещё 1-2 RTT. При 1000 RPS экономия составляет ~1-2 секунды CPU-времени в секунду.
2. **Ephemeral ports:** Каждое новое соединение занимает порт из диапазона `49152-65535` (~16k портов). При 10k одновременных соединениях к одному бэкенду порты могут исчерпаться за минуты.
3. **CPU на бэкенде:** Каждый TCP handshake требует работы CPU (SYN-ACK, handshake, allocate socket buffer). При 10k RPS handshake потребляет ~10-20% CPU на бэкенде.
4. **Conntrack:** Каждое новое соединение создаёт запись в таблице conntrack (~300 байт RAM). Пулы снижают нагрузку на conntrack.

---

## Практические сценарии

### Connection Pool в nginx (upstream keepalive)

Nginx поддерживает keepalive-соединения к backend-серверам через директиву `keepalive` в блоке `upstream`:

```nginx
# /etc/nginx/conf.d/upstream.conf

upstream backend {
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;

    # Количество keepalive-соединений на один worker process
    keepalive 32;

    # Количество keepalive-соединений на один upstream server
    # (по умолчанию = keepalive / number_of_servers)
    keepalive_requests 1000;

    # Таймаут простоя keepalive-соединения
    keepalive_timeout 60s;
}

server {
    listen 80;

    location / {
        proxy_pass http://backend;

        # Протокол для keepalive (должен быть HTTP/1.1)
        proxy_http_version 1.1;

        # Удалить заголовок Connection: close (keepalive работает с HTTP/1.1)
        proxy_set_header Connection "";

        # Передать оригинальные заголовки
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

**Ключевые моменты:**
- `proxy_http_version 1.1` — keepalive работает только с HTTP/1.1 (HTTP/1.0 использует `Connection: close`).
- `proxy_set_header Connection ""` — удаляет заголовок `Connection: close`, который nginx добавляет по умолчанию.
- `keepalive 32` — это 32 соединения **на worker process**. При 4 worker'ах искомое = 128 keepalive-соединений к каждому backend.

**Мониторинг:**
```bash
# Активные keepalive-соединения
curl http://localhost/nginx_status | grep -i active
# Или через stub_status
stub_status on;

# Проверка через ss
ss -tnp | grep :8080 | grep ESTAB | wc -l
```

### Connection Pool в HAProxy

```haproxy
# /etc/haproxy/haproxy.cfg

defaults
    mode http
    timeout connect 5s
    timeout client  30s
    timeout server  30s

backend web_servers
    balance roundrobin
    option httpchk GET /health

    # Keepalive к backend
    option http-keep-alive
    http-reuse safe

    server web1 10.0.0.1:8080 check
    server web2 10.0.0.2:8080 check

    # Максимальное количество соединений к backend
    maxconn 256
```

**Параметры `http-reuse`:**
- `never` — никогда не переиспользуй keepalive-соединения (по умолчанию в older versions).
- `safe` — переиспользуй только для запросов от одного клиента (default в modern versions).
- `aggressive` — переиспользуй для разных клиентов (опасно при HTTP pipelining).
- `always` — как `aggressive`, но с дополнительными проверками.

### Connection Pool для PostgreSQL (PgBouncer)

PgBouncer — это connection pooler для PostgreSQL, работающий как промежуточный процесс между приложением и базой данных.

```ini
; /etc/pgbouncer/pgbouncer.ini

[databases]
mydb = host=127.0.0.1 port=5432 dbname=mydb

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432

; Режим пула: transaction — соединение возвращается в пул после каждой транзакции
pool_mode = transaction

; Максимальное количество клиентских соединений
max_client_conn = 1000

; Максимальное количество соединений к PostgreSQL
default_pool_size = 20

; Минимальное количество соединений в пуле
min_pool_size = 5

; Максимальное время простоя соединения в пуле
server_idle_timeout = 300

; Таймаут на установку соединения с PostgreSQL
server_connect_timeout = 5

; Проверка соединений перед выдачей
server_check_query = SELECT 1
server_check_delay = 10
```

**Режимы пула:**

| Режим | Описание | Когда использовать |
| :--- | :--- | :--- |
| **session** | Соединение закрепляется за клиентом на всё время сессии | Клиент использует `SET`, `PREPARE` и другие session-состояния |
| **transaction** | Соединение возвращается после каждой транзакции | Большинство приложений (рекомендуется) |
| **statement** | Соединение возвращается после каждого запроса | Только для простых запросов без транзакций |

### Connection Pool для MySQL (ProxySQL)

```sql
-- Конфигурация пула в ProxySQL

-- Добавление backend-серверов
INSERT INTO mysql_servers(hostgroup_id, hostname, port, weight)
VALUES (1, '10.0.0.1', 3306, 1000),
       (1, '10.0.0.2', 3306, 1000);

-- Настройка пула
SET mysql-connect_timeout_server=5000;
SET mysql-connection_max_age_server=0;
SET mysql-free_connections_pct=10;

-- Применение
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

### Connection Pool в приложении (пример: Python)

```python
import psycopg2
from psycopg2 import pool

# Создание пула соединений
connection_pool = psycopg2.pool.ThreadedConnectionPool(
    minconn=5,
    maxconn=20,
    host="10.0.0.1",
    database="mydb",
    user="app",
    password="secret",
    connect_timeout=5
)

# Использование соединения из пула
conn = connection_pool.getconn()
try:
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    result = cur.fetchone()
    conn.commit()
finally:
    # Вернуть соединение в пул (НЕ закрывать!)
    connection_pool.putconn(conn)
```

---

## Устранение неполадок

### Симптом: «connection pool exhausted» / «too many connections»

**Причина:** Все соединения в пуле заняты, новые запросы ждут освобождения (или получают ошибку).

**Диагностика:**
```bash
# Проверка количества соединений к сервису
ss -tnp | grep :5432 | wc -l
# → Если = max_pool_size — пул исчерпан

# Проверка ACTIVE vs IDLE соединений
ss -tnp state established | grep :5432 | awk '{print $4}' | sort | uniq -c

# В PostgreSQL: проверка количества подключений
SELECT count(*) FROM pg_stat_activity;
SELECT state, count(*) FROM pg_stat_activity GROUP BY state;
```

**Решения:**
1. Увеличить `max_pool_size` (но не превышать `max_connections` на бэкенде).
2. Уменьшить `idle_timeout` для быстрого освобождения неиспользуемых соединений.
3. Добавить connection pooler (PgBouncer/ProxySQL) перед базой данных.
4. Проверить на утечки соединений в приложении (getconn без putconn).

### Симптом: Рост латентности при стабильной нагрузке

**Причина:** Keepalive-соединения умирают на стороне бэкенда (таймаут), но клиентский пул не знает об этом и пытается использовать «мёртвое» соединение.

**Диагностика:**
```bash
# Проверка keepalive-соединений
ss -tnp | grep :8080 | grep ESTAB

# На бэкенде: проверка TIME_WAIT
ss -tnp | grep :8080 | grep TIME_WAIT | wc -l
# → Если много TIME_WAIT — бэкенд закрывает соединения

# Проверка tcp_keepalive на клиенте
sysctl net.ipv4.tcp_keepalive_time
# → По умолчанию 7200 сек (2 часа!) — слишком долго для пулов
```

**Решения:**
```bash
# 1. Настроить keepalive на клиенте (снижение tcp_keepalive_time)
sysctl -w net.ipv4.tcp_keepalive_time=60
sysctl -w net.ipv4.tcp_keepalive_intvl=10
sysctl -w net.ipv4.tcp_keepalive_probes=3

# 2. Настроить keepalive на стороне nginx
keepalive_timeout 60s;

# 3. Добавить health check в пул
# В PgBouncer:
server_check_query = SELECT 1
server_check_delay = 10
```

### Симптом: Много TCP RST при использовании пула

**Причина:** Бэкенд закрыл соединение (по таймауту или ошибке), но клиент попытался отправить запрос через уже закрытое соединение.

**Диагностика:**
```bash
# Мониторинг RST-пакетов
ss -tnp | grep RST | wc -l

# tcpdump для анализа
tcpdump -i eth0 'tcp[tcpflags] & (tcp-rst) != 0' -n
```

**Решения:**
1. Убедиться, что `keepalive_timeout` на бэкенде > `idle_timeout` в пуле.
2. Включить retry logic в приложении (повторная попытка при RST).
3. Добавить connection validation перед использованием.

### Симптом: Conntrack переполняется из-за коротких соединений

**Причина:** При отсутствии пула каждое соединение создаёт запись conntrack. При высоком RPS таблица переполняется.

**Диагностика:**
```bash
conntrack -S | grep insert_failed
# → insert_failed > 0 — таблица переполнялась

# Текущее использование
cat /proc/sys/net/netfilter/nf_conntrack_count
cat /proc/sys/net/netfilter/nf_conntrack_max
```

**Решения:**
1. Включить connection pooling на уровне прокси (nginx keepalive, PgBouncer).
2. Увеличить `nf_conntrack_max` и уменьшить таймауты conntrack.
3. Для внутреннего трафика использовать `NOTRACK` в таблице `raw`.

---

## Дополнительная информация

### Связанные темы

- **[TCP Keepalive](../../Linux/Networking/Concepts/tcp_keepalive.md)** — настройка keepalive в Linux через `sysctl`.
- **[Socket API](./socket_api.md)** — управление TCP-сокетами, `SO_REUSEADDR`, `SO_REUSEPORT`.
- **[Conntrack и таймауты](./nat/overview.md#таймауты-conntrack-ключевые-параметры-linux)** — влияние connection pooling на таблицу conntrack.
- **[nginx: reverse proxy](../../WebServers/nginx_overview.md)** — настройка keepalive к backend в nginx.
- **[HAProxy: балансировка](../../WebServers/haproxy_overview.md)** — http-reuse и connection pooling в HAProxy.
- **[PgBouncer](../../Databases/PostgreSQL/Operations/pgbouncer_setup.md)** — connection pooler для PostgreSQL.
- **[ProxySQL](../../Databases/MySQL/ProxySQL/proxysql_overview.md)** — connection pooler для MySQL.
- **[IO Multiplexing](./io_multiplexing.md)** — epoll/kqueue как основа для efficient connection pooling.

### Вопросы на собеседованиях

1. **Зачем нужен connection pool?** — Ответ: для переиспользования TCP-соединений и устранения overhead handshake (1-3 RTT на каждое соединение).
2. **Чем keepalive отличается от connection pool?** — Ответ: keepalive проверяет доступность хоста, connection pool переиспользует соединения.
3. **Какой max_pool_size выбрать?** — Ответ: зависит от количества backend-серверов и RPS; формула: `(RPS * avg_latency) / number_of_backends`. Не превышать `max_connections` на бэкенде.
4. **Что такое PgBouncer и зачем он нужен?** — Ответ: connection pooler для PostgreSQL, работает в режимах session/transaction/statement; снижает нагрузку на PostgreSQL от 10k+ клиентов.
5. **Как диагностировать «connection pool exhausted»?** — Ответ: `ss -tnp | grep :port | wc -l`, проверка ACTIVE vs IDLE соединений, мониторинг `max_pool_size` usage.
