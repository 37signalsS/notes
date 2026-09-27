# TCP Keepalive — Production настройка

## Определения

**TCP Keepalive** — механизм обнаружения «мёртвых» TCP-соединений путём периодической отправки ACK-сегментов с Sequence Number, равным `snd_nxt - 1`. Если удалённый хост не отвечает на `tcp_keepalive_probes` подряд, соединение закрывается с ошибкой `ETIMEDOUT`.

**SO_KEEPALIVE** — опция сокета, включающая keepalive для конкретного соединения. По умолчанию отключена.

**TCP_KEEPIDLE / TCP_KEEPINTVL / TCP_KEEPCNT** — per-socket опции, переопределяющие глобальные sysctl-значения для отдельного соединения.

**Connection Pool** — механизм переиспользования ранее установленных TCP-соединений. Keepalive и connection pool дополняют друг друга: keepalive проверяет живучесть, pool переиспользует соединения.

---

## Теоретический блок

### Механизм работы

```
Приложение               Ядро Linux                Удалённый хост
    │                        │                          │
    │  Нет трафика > time    │                          │
    │                        │  ACK (seq = snd_nxt-1)   │
    │                        │ ─────────────────────────►│
    │                        │                          │
    │                        │     ACK (подтверждение)   │
    │                        │ ◄─────────────────────────│
    │                        │                          │
    │  (таймер сбрасывается) │                          │
    │                        │                          │
    │  Нет ответа            │                          │
    │                        │  ACK (повтор)            │
    │                        │ ─────────────────────────►│  intvl сек
    │                        │                          │
    │  ...重复 probes раз...  │                          │
    │                        │                          │
    │  Нет ответа после      │                          │
    │  всех probes           │  Закрытие соединения     │
    │                        │  ETIMEDOUT               │
```

### Формула расчёта общего времени

```
Общее время = tcp_keepalive_time + (tcp_keepalive_intvl × tcp_keepalive_probes)
```

По умолчанию: `7200 + (75 × 9) = 7875 сек` (~2.2 часа).

### Уровни настройки

| Уровень | Механизм | Область действия | Приоритет |
|---|---|---|---|
| **sysctl (глобальный)** | `net.ipv4.tcp_keepalive_*` | Все соединения | Низший |
| **Per-socket** | `setsockopt(TCP_KEEPIDLE/INTVL/CNT)` | Конкретное соединение | Высший |
| **Per-route** | `ip route ... quickack` | Маршрут | Средний |

### sysctl vs Per-socket

Глобальные sysctl-параметры действуют как значения по умолчанию. Per-socket опции переопределяют их для конкретного соединения:

```c
// Per-socket переопределение
setsockopt(fd, IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof(idle));
setsockopt(fd, IPPROTO_TCP, TCP_KEEPINTVL, &interval, sizeof(interval));
setsockopt(fd, IPPROTO_TCP, TCP_KEEPCNT, &count, sizeof(count));
```

```python
# Python эквивалент
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
```

### Keepalive vs Connection Pool vs Health Check

| Механизм | Назначение | Когда работает | Overhead |
|---|---|---|---|
| **TCP Keepalive** | Обнаружение мёртвых соединений | Простой (нет трафика) | Минимальный (1 пакет/N сек) |
| **Connection Pool** | Переиспользование соединений | При передаче данных | Снижение handshake overhead |
| **Application Health Check** | Проверка работоспособности сервиса | Периодически | Зависит от check |

### Оптимальные значения по сценариям

| Сценарий | time | intvl | probes | Общее время | Обоснование |
|---|---|---|---|---|---|
| **Nginx/Envoy upstream** | 60 | 10 | 6 | 120 сек | Быстрое обнаружение мёртвых бэкендов за <2 мин |
| **PostgreSQL** | 60 | 10 | 6 | 120 сек | Рекомендация PostgreSQL для production |
| **Redis client** | 300 | 30 | 3 | 390 сек | Баланс между чувствительностью и overhead |
| **gRPC (HTTP/2)** | 60 | 10 | 6 | 120 сек | Multiplexing требует быстрого detection |
| **Kafka broker** | 600 | 60 | 3 | 780 сек | Длинные партиции, допустимы задержки |
| **SSH tunnel** | 60 | 15 | 3 | 105 сек | Быстрое закрытие висящих соединений |
| **iSCSI** | 600 | 15 | 5 | 1350 сек | Стабильность хранения, минимальный overhead |
| **RPC (internal)** | 30 | 5 | 3 | 45 сек | Агрессивное обнаружение в service mesh |
| **Database pool** | 60 | 10 | 3 | 90 сек | Быстрое переключение на реплику |

---

## Практический блок

### Проверка текущих значений

```bash
# Глобальные sysctl-значения
sysctl net.ipv4.tcp_keepalive_time net.ipv4.tcp_keepalive_intvl net.ipv4.tcp_keepalive_probes

# Вывод:
# net.ipv4.tcp_keepalive_time = 7200
# net.ipv4.tcp_keepalive_intvl = 75
# net.ipv4.tcp_keepalive_probes = 9

# Keepalive для конкретного соединения
ss -tin dst 10.0.0.1 | grep -E 'keepalive|ato'
# → keepalive:(23s/60s/3) — 23 сек прошло из 60, 3 probes.max

# Все соединения с keepalive
ss -tin | grep keepalive
```

### Production sysctl-конфигурация

```bash
# /etc/sysctl.d/99-tcp-keepalive.conf
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 5
# → Общее время: 600 + (30 × 5) = 750 сек (12.5 мин)
```

```bash
# Применение
sudo sysctl --system
# Проверка
sysctl net.ipv4.tcp_keepalive_time net.ipv4.tcp_keepalive_intvl net.ipv4.tcp_keepalive_probes
```

### Настойка per-socket через setsockopt

```c
// C: production-пример для database connection pool
int enable = 1;
setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &enable, sizeof(enable));

// Переопределение глобальных значений
int idle = 60;       // tcp_keepalive_time (60 сек вместо 7200)
int interval = 10;   // tcp_keepalive_intvl (10 сек вместо 75)
int count = 3;        // tcp_keepalive_probes (3 вместо 9)

setsockopt(fd, IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof(idle));
setsockopt(fd, IPPROTO_TCP, TCP_KEEPINTVL, &interval, sizeof(interval));
setsockopt(fd, IPPROTO_TCP, TCP_KEEPCNT, &count, sizeof(count));

// Общее время: 60 + (10 × 3) = 90 сек
```

```python
# Python: production-пример
import socket

def create_keepalive_socket(host, port, idle=60, intvl=10, cnt=3):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idle)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, intvl)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, cnt)
    sock.connect((host, port))
    return sock
```

```go
// Go: production-пример
conn, _ := net.Dial("tcp", "10.0.0.1:5432")
tcpConn := conn.(*net.TCPConn)
tcpConn.SetKeepAlive(true)
tcpConn.SetKeepAlivePeriod(60 * time.Second)
// Go автоматически настраивает intvl и cnt
```

### Nginx upstream keepalive

```nginx
# /etc/nginx/nginx.conf
upstream backend {
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;

    # Keepalive соединений к upstream
    keepalive 32;
    keepalive_timeout 60s;
    keepalive_requests 1000;
}

server {
    listen 80;

    location / {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

### HAProxy backend keepalive

```haproxy
# /etc/haproxy/haproxy.cfg
backend http_servers
    option httpchk GET /health
    http-check expect status 200

    server web1 10.0.0.1:8080 check inter 5s fall 3 rise 2
    server web2 10.0.0.2:8080 check inter 5s fall 3 rise 2

    # Keepalive к backend
    option http-keep-alive
    timeout server 30s
    timeout connect 5s
```

### Diagnostics

```bash
# Мониторинг keepalive соединений
ss -tin state established | awk '{print $1, $2, $3}' | head -20

# Найти соединения без keepalive
ss -tin state established | grep -v keepalive | wc -l

# Мониторинг через nstat
nstat -az | grep -i keepalive
# TcpExtTCPKeepAlive       → количество отправленных keepalive probes

# Найти мёртвые соединения (голый ACK без ответа)
ss -tin state established | awk '/keepalive/ {
    split($0, a, "keepalive:(");
    split(a[2], b, "/");
    if (b[1]+0 > 300) print $0
}'

# Через eBPF (bcc-tools)
tcpkeepalive           # Выводит все keepalive probes с PID/comm
```

### Проблемы и решения

| Проблема | Симптомы | Причина | Решение |
|---|---|---|---|
| **Мёртвые соединения в pool** | Запросы падают с ETIMEDOUT | Keepalive не настроен или слишком долгий | Уменьшить time/intvl/probes |
| **Keepalive overhead** | Рост CPU, сетевой трафик | Слишком агрессивные настройки при большом количестве соединений | Увеличить time до 300-600 |
| **NAT timeout** | Соединения рвутся за NAT | Conntrack timeout < keepalive time | Уменьшить keepalive_time < conntrack_tcp_timeout |
| **Connection pool leak** | Рост числа соединений, FD exhaustion | Keepalive не обнаруживает half-open | Настроить keepalive + pool max idle |
| **Load balancer timeout** | LB рвёт соединения | LB timeout < keepalive time | Синхронизировать timeouts |

### Мониторинг и алертинг

```yaml
# Prometheus alerting rules
groups:
  - name: tcp_keepalive_alerts
    rules:
      - alert: HighKeepAliveProbes
        expr: rate(node_netstat_TcpExtTCPKeepAlive[5m]) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий rate keepalive probes"

      - alert: HighETIMEDOUT
        expr: rate(node_netstat_TcpExtTCPTimeouts[5m]) > 10
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Высокий rate ETIMEDOUT — возможны мёртвые соединения"
```

---

## Дополнительная информация

### Связанные файлы

- [TCP Production Tuning](../../../Networking/Protocols/TCP/production_tuning.md) — keepalive настройка per-socket (C/Python)
- [Connection Pooling](../../../Networking/Concepts/connection_pooling.md) — keepalive vs connection pool
- [TCP Buffer Tuning](tcp_buffer_tuning.md) — буферы сокетов
- [TCP Socket Diagnostics](tcp_socket_diagnostics.md) — диагностика соединений

### Важные замечания

1. **Keepalive НЕ переиспользует соединения** — он только обнаруживает мёртвые. Для переиспользования нужен connection pool.
2. **Per-socket опции требуют поддержки приложением** — не все клиенты (Redis, PostgreSQL drivers) позволяют настроить keepalive через API.
3. **Для containerized workloads** keepalive настраивается на уровне node (sysctl) или через security context в Kubernetes.
4. **При работе через NAT** keepalive timeout должен быть меньше `nf_conntrack_tcp_timeout_time_wait`.
