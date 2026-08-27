# TCP Production Tuning — Практическое руководство

## Определения

**TCP Production Tuning** — настройка параметров TCP-стека ядра Linux для конкретных production-сценариев (высоконагруженные прокси, базы данных, долгоживущие соединения, L4 балансировка). Фокус — наطرебleshooting и оптимизацию, а не на теорию.

**TCP Metrics Caching (`ip tcp_metrics`)** — механизм ядра Linux, кэширующий параметры TCP-соединений (RTT, cwnd, ssthresh, PMTU) по IP-адресам. Позволяет новому соединению к тому же хосту сразу использовать сохраненные метрики вместо начальных значений.

**TCP Keepalive** — механизм обнаружения «мёртвых» TCP-соединений (партнер не отвечает) путём периодической отправки ACK-сегментов с incremented Sequence Number.

**SO_REUSEPORT** — опция сокета (Linux 3.9+), позволяющая нескольким процессам/потокам слушать один и тот же порт с балансировкой нагрузки через хеш в ядре.

---

## 1. TCP Keepalive — Production тюнинг

### Механизм

Keepalive работает на уровне ядра. Если соединение простаивает дольше `tcp_keepalive_time` секунд, ядро отправляет 1-байтовый ACK (с `seq = snd_nxt - 1`). Если ответ не поступает, повторяет с интервалом `tcp_keepalive_intvl` до `tcp_keepalive_probes` попыток. При отсутствии ответа соединение закрывается с ошибкой `ETIMEDOUT`.

### Sysctl-параметры

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `net.ipv4.tcp_keepalive_time` | 7200 (2 часа) | Время простоя (в секундах) перед отправкой первого keepalive. |
| `net.ipv4.tcp_keepalive_intvl` | 75 | Интервал (в секундах) между повторными keepalive. |
| `net.ipv4.tcp_keepalive_probes` | 9 | Количество неудачных попыток перед закрытием соединения. |

**Общее время до закрытия:** `tcp_keepalive_time + (tcp_keepalive_intvl × tcp_keepalive_probes)` = 7200 + (75 × 9) = 7875 сек (~2.2 часа) по умолчанию.

### Значения по сценариям

| Сценарий | time | intvl | probes | Общее время | Примечание |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Nginx/Envoy upstream** | 60 | 10 | 6 | 120 сек | Быстрое обнаружение мёртвых бэкендов. |
| **Redis client** | 300 | 30 | 3 | 390 сек | Баланс между чувствительностью и overhead. |
| **PostgreSQL** | 60 | 10 | 6 | 120 сек | Рекомендация PostgreSQL для cloud. |
| **gRPC (HTTP/2)** | 60 | 10 | 6 | 120 сек | HTTP/2 multiplexing требует быстрого detection. |
| **Kafka broker** | 600 | 60 | 3 | 780 сек | Длинные партиции, допустимы задержки. |
| **SSH tunnel** | 60 | 15 | 3 | 105 сек | Быстрое закрытие висящих соединений. |

### Проверка текущих значений

```bash
# Просмотр всех keepalive параметров
sysctl net.ipv4.tcp_keepalive_time net.ipv4.tcp_keepalive_intvl net.ipv4.tcp_keepalive_probes

# Проверка keepalive для конкретного соединения через ss
ss -tin dst 10.0.0.1 | grep -E 'keepalive|ato'

# Пример вывода:
# keepalive:(23s/60s/3) — 23 сек прошло из 60, 3 probes.max
```

### Включение keepalive на уровне приложения

```c
// C: включение keepalive на сокете
int enable = 1;
setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &enable, sizeof(enable));

// Настройка переопределения (per-socket)
int idle = 60;      // tcp_keepalive_time
setsockopt(fd, IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof(idle));

int interval = 10;  // tcp_keepalive_intvl
setsockopt(fd, IPPROTO_TCP, TCP_KEEPINTVL, &interval, sizeof(interval));

int count = 3;      // tcp_keepalive_probes
setsockopt(fd, IPPROTO_TCP, TCP_KEEPCNT, &count, sizeof(count));
```

```python
# Python: включение keepalive
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
```

---

## 2. TCP для баз данных (MySQL, PostgreSQL, Redis)

### Общие принципы

Базы данных используют TCP двумя способами:
- **Короткие соединения** (each query = new TCP connection) — критичны TIME_WAIT, backlog, keepalive.
- **Connection pooling** (long-lived соединения) — критичны buffer sizes, keepalive, TCP_NODELAY.

### MySQL / MariaDB

```ini
# /etc/sysctl.d/99-mysql-networking.conf

# Backlog для MySQL (по умолчанию 50, увеличить при большом количестве клиентов)
# В MySQL: SET GLOBAL max_connections = 500; (согласовать с somaxconn)
net.core.somaxconn = 4096

# Keepalive для long-running queries и replication
net.ipv4.tcp_keepalive_time = 60
net.ipv4.tcp_keepalive_intvl = 10
net.ipv4.tcp_keepalive_probes = 6

# Буферы для больших result sets
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
```

**Типичные проблемы MySQL + TCP:**
- `Too many connections` → увеличить `max_connections` + `somaxconn`.
- Медленная репликация → keepalive для replication connection, `initcwnd` для distant replicas.
- Connection storm после рестарта → `tcp_abort_on_overflow=0` (тихий retry клиентов).

### PostgreSQL

```ini
# /etc/sysctl.d/99-postgresql-networking.conf

# Keepalive (рекомендация PostgreSQL wiki)
net.ipv4.tcp_keepalive_time = 60
net.ipv4.tcp_keepalive_intvl = 10
net.ipv4.tcp_keepalive_probes = 6

# Backlog (pgbouncer default: 128, увеличить)
net.core.somaxconn = 4096

# Буферы для COPY и больших запросов
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
```

**Типичные проблемы PostgreSQL + TCP:**
- `connection reset by peer` → keepalive обнаружил мёртвого партнера; проверить `tcp_keepalive_time`.
- Slow COPY → увеличить `tcp_wmem`, `SO_SNDBUF` на клиенте.
- Pgbouncer connection storms → `tcp_abort_on_overflow=1` перед pgbouncer.

### Redis

```ini
# /etc/sysctl.d/99-redis-networking.conf

# Redis по умолчанию: tcp-backlog 511
net.core.somaxconn = 65535

# Keepalive (Redis не имеет встроенного keepalive, настраивается через ОС)
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3
```

**Типичные проблемы Redis + TCP:**
- `Connection reset` → Redis не отправляет keepalive по умолчанию; настроить на клиенте.
- Слишком много соединений → увеличить `tcp_max_syn_backlog`, `somaxconn`.
- Slow replication → `initcwnd` для replication link, keepalive.

---

## 3. TCP Metrics Caching (`ip tcp_metrics`)

### Механизм

Ядро Linux кэширует по IP-адресу:
- **RTT** и **RTT variance** (измеренные через Timestamps).
- **ssthresh** (congestion window threshold).
- **cwnd** (congestion window).
- **PMTU** (Path MTU).
- **Состояние sack** (SACK включен/выключен).

Кэш сохраняется после закрытия соединения и применяется к новому соединению к тому же IP. Это ускоряет повторные соединения (например, при reconnect в connection pool).

### Управление через ip

```bash
# Просмотр кэша
ip tcp_metrics show

# Просмотр для конкретного IP
ip tcp_metrics show 10.0.0.1

# Очистка кэша для конкретного IP (при смене маршрута или после failover)
ip tcp_metrics flush 10.0.0.1

# Очистка всего кэша
ip tcp_metrics flush

# Фильтрация по интерфейсу
ip tcp_metrics show | grep -E 'metric rto|metric rtt|metric ssthresh'
```

### Структура записи

```bash
ip tcp_metrics show 10.0.0.1
# → 10.0.0.1 age 123sec rto 204 rtt 15.2/0.5 ato 40 mss 1448
#     rcvmss 1448 advmss 1448 cwnd 10 ssthresh 7 bytes_sent 12345
#     bytes_acked 12345 segs_out 100 segs_in 80 data_segs_out 50
#     send 7.6Mbps lastsnd 123 lastrcv 123 lastack 123
#     pacing_rate 15.2Mbps delivery_rate 7.6Mbps
#     busy 1000ms retrans 0/0
```

### Sysctl

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `net.ipv4.tcp_mtu_probing` | 0 | 0=отключен, 1=только lookup, 2=blackhole detection. Влияет на PMTU кэш. |
| `net.ipv4.ip_no_pmtu_disc` | 0 | 1=отключить PMTU discovery (опасно). |

### Когда чистить кэш

- После смены маршрута (failover, change default gateway).
- После смены PMTU (новый путь в сети).
- При диагностике «старых» проблем с RTT (кэш хранит historical данные).
- При миграции сервисов (старый IP переназначен новому хосту).

---

## 4. L4 Load Balancing и TCP

### SO_REUSEPORT

SO_REUSEPORT (Linux 3.9+) позволяет нескольким процессам слушать один порт. Ядро балансирует входящие соединения через хеш 4-tuple (src_ip, src_port, dst_ip, dst_port).

> *Подробнее:* [SO_REUSEPORT в network_ports](../../../Networking/Concepts/network_ports.md#so_reuseport), [Socket API](../../../Networking/Concepts/socket_api.md).

```bash
# Проверка:有多少进程 слушают порт 80
ss -tlnp | grep :80
```

### IPVS (LVS) — Kernel L4 Balancing

IPVS работает на уровне ядра и не требует пользовательского пространства для балансировки:

```bash
# Добавление виртуального сервера (TCP)
ipvsadm -A -t 10.0.0.100:80 -s rr

# Добавление бэкендов
ipvsadm -a -t 10.0.0.100:80 -r 10.0.0.1:80 -g    # г NAT
ipvsadm -a -t 10.0.0.100:80 -r 10.0.0.2:80 -g

# Просмотр таблицы
ipvsadm -Ln

# Статистика
ipvsadm -Ln --stats
```

> *Подробнее:* [HA clustering](../../../Concepts/High_Availability/ha_clustering_and_load_balancing.md), [IPVS в K8s](../../../Kubernetes/Networking/Network/CNI/ipvs.md).

---

## 5. Busy Polling (SO_BUSY_POLL)

Busy polling позволяет сокету активно опрашивать NIC вместо ожидания прерывания. Радикально снижает tail latency (p99/p99.9).

> *Подробнее:* [Network Latency Optimization](../../../Linux/Networking/Concepts/network_latency_optimization.md#%D1%83%D1%80%D0%BE%D0%B2%D0%B5%D0%BD%D1%8C-4-%D0%BE%D0%BF%D1%82%D0%B8%D0%BC%D0%B8%D0%B7%D0%B0%D1%86%D0%B8%D1%8F-%D0%BD%D0%B0-%D1%83%D1%80%D0%BE%D0%B2%D0%BD%D0%B5-%D1%81%D0%BE%D0%BA%D0%B5%D1%82%D0%BE%D0%B2-%D0%BF%D1%80%D0%B8%D0%BB%D0%BE%D0%B6%D0%B5%D0%BD%D0%B8%D1%8F), [NAPI Optimization](../../../Linux/Networking/Concepts/napi_optimization.md).

```bash
# Глобальные настройки
sysctl -w net.core.busy_poll=50    # мкс для epoll/select/poll
sysctl -w net.core.busy_read=50    # мкс для read/write

# Per-socket (C)
int val = 50;
setsockopt(fd, SOL_SOCKET, SO_BUSY_POLL, &val, sizeof(val));
setsockopt(fd, SOL_SOCKET, SO_PREFER_BUSY_POLL, &val, sizeof(val));
```

---

## 6. Production Sysctl — Quick Reference

### Универсальный набор для Linux-серверов (2026)

```ini
# /etc/sysctl.d/99-tcp-production.conf

# === Connection establishment ===
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 16384
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_abort_on_overflow = 1

# === Connection keepalive ===
net.ipv4.tcp_keepalive_time = 60
net.ipv4.tcp_keepalive_intvl = 10
net.ipv4.tcp_keepalive_probes = 6

# === TIME_WAIT ===
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535

# === Buffers ===
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.ipv4.tcp_rmem = 4096 131072 134217728
net.ipv4.tcp_wmem = 4096 65536 134217728
net.ipv4.tcp_moderate_rcvbuf = 1

# === Congestion control ===
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq

# === Loss detection ===
net.ipv4.tcp_recovery = 1
net.ipv4.tcp_reordering = 3

# === Window scaling ===
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_timestamps = 1
net.ipv4.tcp_sack = 1

# === Low latency (optional) ===
net.core.busy_poll = 50
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_notsent_lowat = 16384
```

### Проверка после применения

```bash
# Применение
sudo sysctl -p /etc/sysctl.d/99-tcp-production.conf

# Проверка критичных параметров
sysctl net.core.somaxconn net.ipv4.tcp_syncookies net.ipv4.tcp_tw_reuse \
       net.ipv4.tcp_congestion_control net.core.default_qdisc

# Быстрая оценка TCP стека
ss -s
nstat -az | grep -E 'ListenOverflows|ListenDrops|Syncookies|TCPTimeouts|RetransSegs'
```

---

## 7. Диагностика

### Чек-лист при проблемах с TCP

```bash
# 1. Общее состояние TCP
ss -s

# 2. Поиск проблемных соединений (высокий RTT, мало cwnd, потеря)
ss -tin | awk '$4 != "0" || $6 < 10 {print}'

# 3. Проверка переполнения очередей
nstat -az | grep -E 'ListenOverflows|ListenDrops|TCPBacklogDrop'

# 4. Проверка ретрансмиссий
nstat -az | grep -E 'TCPRetransSegs|TCPSpuriousRto|TCPLossProbes'

# 5. Проверка keepalive срабатываний
nstat -az | grep -E 'TCPKeepAlive'

# 6. Проверка PAWS
nstat -az | grep -E 'TcpExtPAWS'

# 7. Проверка ip tcp_metrics
ip tcp_metrics show | head -20

# 8. Проверка conntrack (если используется NAT/firewall)
conntrack -S
```

### Типичные симптомы → причины → решения

| Симптом | Причина | Команда диагностики | Решение |
| :--- | :--- | :--- | :--- |
| `Connection refused` | Порт закрыт / backlog полон | `ss -tlnp \| grep :PORT` | Открыть порт / увеличить backlog |
| `Connection timed out` | Keepalive не сработал / firewall DROP | `ss -tin dst HOST` + `iptables -L -v -n` | Настроить keepalive / проверить firewall |
| `Connection reset` | Приложение закрыло / RST от firewall | `nstat -az \| grep Abort` | Проверить `tcp_abort_on_overflow` |
| Высокий RTT (100+ мс) | Bufferbloat / очередь на линке | `ss -ti \| grep rtt` | FQ-Codel qdisc, BBR |
| Малый cwnd (<10) | Slow start / потеря пакета | `ss -ti \| grep cwnd` | Проверить loss: `nstat \| grep Retrans` |
| `ECONNRESET` в контейнере | Conntrack overflow / NAT timeout | `conntrack -S` | Увеличить `nf_conntrack_max` |

---

## Дополнительная информация

### См. также
- **[Управление очередями TCP](../../Linux/Networking/Concepts/tcp_tuning/tcp_connection_queues.md)** — somaxconn, SYN backlog, netdev_max_backlog.
- **[Оптимизация буферов](../../Linux/Networking/Concepts/tcp_tuning/tcp_buffer_tuning.md)** — rmem/wmem, autotuning, BDP.
- **[TIME_WAIT](../../Linux/Networking/Concepts/tcp_tuning/tcp_time_wait_management.md)** — tw_reuse, эфемерные порты.
- **[Обзор оптимизации TCP](../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — иерархия параметров, BBR, L4S.
- **[SO_REUSEPORT](../../../Networking/Concepts/network_ports.md#so_reuseport)** — балансировка на уровне ядра.
- **[Network Latency Optimization](../../Linux/Networking/Concepts/network_latency_optimization.md)** — busy polling, RSS/RPS, Kernel Bypass.
- **[NAPI Optimization](../../Linux/Networking/Concepts/napi_optimization.md)** — busy_read, interrupt coalescing.
- **[HA Clustering & Load Balancing](../../../Concepts/High_Availability/ha_clustering_and_load_balancing.md)** — L4 LB, IPVS, DSR.
- **[Diagnostics](./reliability_mechanisms/diagnostics.md)** — eBPF, nstat, ss, Prometheus/Grafana.

### Стандарты (RFC)
- **RFC 1122:** Requirements for Internet Hosts — keepalive purpose.
- **RFC 7323:** TCP Extensions for High Performance — Timestamps, PAWS.
- **RFC 9293:** Transmission Control Protocol (2022).
