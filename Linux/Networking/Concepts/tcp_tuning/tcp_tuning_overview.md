# Оптимизация TCP в Linux: Обзор

## Определения

**Оптимизация TCP** — комплексная настройка параметров сетевого стека ядра Linux (через `sysctl`, `ip route` и `ethtool`) для достижения баланса между пропускной способностью, минимальными задержками и стабильностью при высоких нагрузках. Затрагивает все уровни обработки пакетов: от дескрипторов NIC до прикладных буферов.

**BBR (Bottleneck Bandwidth and RTT)** — алгоритм контроля перегрузки, который моделирует пропускную способность канала и RTT, обеспечивая высокую скорость даже при наличии сетевых потерь. В отличие от loss-based алгоритмов (CUBIC, Reno), BBR использует модель канала и целится в оптимальное заполнение буферов, а не в заполнение до потерь.

**Multi-path TCP (MPTCP)** — расширение TCP, позволяющее передавать данные одного логического соединения через несколько сетевых интерфейсов одновременно (агрегация каналов). Обеспечивает отказоустойчивость и балансировку нагрузки.

**L4S (Low Latency, Low Loss, Scalable throughput)** — современная архитектура (RFC 9330), обеспечивающая экстремально низкие задержки в очередях за счет тесного взаимодействия хоста и сетевого оборудования. Позволяет достичь задержек < 1 мс даже при высокой загрузке.

**BDP (Bandwidth-Delay Product)** — произведение пропускной способности на задержку. Определяет объем данных, необходимых для полной утилизации сетевого канала. Формула: `BDP = Bandwidth (bps) × RTT (s)`.

**Congestion Window (cwnd)** — размер окна перегрузки, определяющий максимальное количество данных (в байтах), которое отправитель может передать без получения ACK. Управляется алгоритмом контроля перегрузки и является ключевым параметром производительности TCP.

**Slow Start** — начальная фаза алгоритма контроля перегрузки, при которой `cwnd` увеличивается экспоненциально (удваивается за каждый RTT) до достижения порога `ssthresh` или возникновения потерь. Цель — быстрое заполнение канала без перегрузки.

**qdisc (Queueing Discipline)** — дисциплина очередей в ядре Linux, определяющая порядок и способ обработки пакетов в очереди интерфейса. Ключевые типы: `pfifo_fast` (по умолчанию), `fq` (для BBR/Pacing), `fq_codel` (борьба с Bufferbloat), `htb` (иерархическая тарификация).

**ECN (Explicit Congestion Notification)** — механизм (RFC 3168), позволяющий маршрутизаторам уведомлять хосты о перегрузке без отбрасывания пакетов. Хосты снижают скорость передачи при получении ECN-уведомления, что снижает потери и задержки.

## Базовые концепции

### Иерархия параметров настройки

Для эффективной оптимизации необходимо учитывать все уровни обработки пакетов:

1.  **Канальный уровень (L2/NIC):** Настройка дескрипторов колец (Ring Buffers), объединение прерываний (Coalescing) и распределение нагрузки (RSS/RPS). Определяет, сколько пакетов NIC может буферизировать до обработки ядром.
2.  **Сетевой уровень (L3/IP):** Управление очередями интерфейса (`netdev_max_backlog`) и параметрами Path MTU Discovery. Определяет максимальный размер пакета без фрагментации.
3.  **Транспортный уровень (L4/TCP):** Настройка алгоритмов перегрузки, буферов (`tcp_rmem`/`tcp_wmem`) и очередей соединений (`somaxconn`). Основной фокус тюнинга производительности.
4.  **Прикладной уровень (L7):** Оптимизация буферов приложения, использование `TCP_NODELAY`, `TCP_CORK`, `TCP_QUICKACK`. Влияет на задержку и эффективность использования буферов.

### Механизмы настройки в 2026 году

*   **Классический `sysctl`:** Основной интерфейс для глобальных параметров (`/proc/sys/net/ipv4/*`). Простой, предсказуемый, работает на всех версиях ядра.
*   **eBPF (Programmatic Tuning):** Использование eBPF-программ для динамического изменения параметров сокетов (например, через `BPF_PROG_TYPE_SOCK_OPS`) в зависимости от контекста приложения. Позволяет настраивать соединения индивидуально.
*   **Per-route Tuning:** Настройка специфичных параметров (например, `initcwnd`, `advmss`) через таблицу маршрутизации (`ip route`). Позволяет применять разные настройки к разным маршрутам.
*   **Per-socket Tuning:** Установка параметров через `setsockopt()` для конкретных сокетов приложения. Требует модификации кода приложения.

### Взаимодействие параметров

Параметры TCP тесно связаны между собой. Изменение одного может потребовать корректировки других:

| Параметр | Влияет на | Зависит от |
| :--- | :--- | :--- |
| `tcp_rmem` / `tcp_wmem` | Throughput, Memory usage | `rmem_max` / `wmem_max`, `tcp_mem` |
| `tcp_congestion_control` | Throughput, Latency | `fq` qdisc (для BBR), ECN |
| `somaxconn` | Connection rate, Backlog | `tcp_max_syn_backlog`, `netdev_max_backlog` |
| `tcp_tw_reuse` | Connection rate | `ip_local_port_range` |
| `tcp_fastopen` | Latency | Client/Server support, Firewall rules |
| `busy_poll` | Latency | CPU usage, NIC driver support |

## Практические сценарии

### 1. Высоконагруженные Edge-серверы (Nginx, Envoy)

**Задача:** Обработка более 100 000 RPS, минимизация TIME_WAIT и эффективное использование портов.

*   **Управление очередями:**
    *   `net.core.somaxconn = 65535` — максимальный размер очереди полностью установленных соединений.
    *   `net.ipv4.tcp_max_syn_backlog = 16384` — очередь полуоткрытых соединений (защита от SYN-флуда).
*   **Эфемерные порты:**
    *   `net.ipv4.ip_local_port_range = 1024 65535` — расширение диапазона исходящих соединений.
    *   `net.ipv4.tcp_tw_reuse = 1` — разрешение повторного использования сокетов в состоянии `TIME_WAIT`.
*   **Тюнинг Keep-Alive:**
    ```ini
    net.ipv4.tcp_keepalive_time = 60
    net.ipv4.tcp_keepalive_intvl = 10
    net.ipv4.tcp_keepalive_probes = 6
    ```
    См. [TCP Keepalive](./tcp_keepalive_production.md) для детальных сценариев по бэкендам.

**Валидация:**
```bash
# Проверка очередей
ss -ltn | grep -E "State|LISTEN"
# Ожидаемый результат: Recv-Q = 0 для всех LISTEN сокетов

# Проверка TIME_WAIT
ss -s | grep timewait
# Ожидаемый результат: timewait < somaxconn
```

### 2. Микросервисы и Low-Latency системы (gRPC, Redis)

**Задача:** Минимизация хвостовых задержек (Tail Latency) и быстрое установление связи.

*   **Быстрый старт:**
    *   `net.ipv4.tcp_fastopen = 3` — включение [TCP Fast Open](./tcp_fast_open.md) для экономии 1 RTT.
    *   Увеличение [initcwnd](./tcp_initcwnd.md) до 32 MSS для быстрой отдачи мелких ответов.
*   **Оптимизация очередей приложения:**
    *   `net.ipv4.tcp_notsent_lowat = 16384` — ограничивает объем непереданных данных в буфере отправки, улучшая реакцию на смену приоритетов HTTP/2 потоков.
    *   `TCP_NODELAY` для всех latency-sensitive соединений (gRPC, Redis, WebSocket). См. [TCP_NODELAY / TCP_CORK](./tcp_nodelay_cork_practical.md).
*   **Активный опрос (Busy Polling):**
    *   `net.core.busy_poll = 50` — время в микросекундах для активного ожидания пакетов драйвером, снижающее задержки на прерываниях. См. [Busy Polling](./tcp_busy_polling.md).
*   **SO_REUSEPORT:**
    *   Для multi-worker серверов включить `reuseport` в конфигурации слушающих сокетов. См. [SO_REUSEPORT](./tcp_reuseport.md).

**Валидация:**
```bash
# Проверка TFO
sysctl net.ipv4.tcp_fastopen
# → net.ipv4.tcp_fastopen = 3

# Проверка busy_poll
sysctl net.core.busy_poll
# → net.core.busy_poll = 50

# Замер задержки
ping -c 10 <target>
# Ожидаемый результат: avg < 1 мс
```

### 3. Сверхвысокие скорости (100G/400G+ линки)

**Задача:** Полная утилизация канала при высоком BDP.

*   **Буферы экстремальных размеров:**
    *   `net.core.rmem_max = 268435456` (256 МБ).
    *   `net.ipv4.tcp_rmem = 4096 131072 268435456`.
*   **Современный стек:**
    *   `net.ipv4.tcp_congestion_control = bbr` (требует `fq` qdisc для реализации Pacing).
    *   `net.ipv4.tcp_timestamps = 1` — критично для Window Scaling на высоких скоростях.
*   **L4S и ECN:**
    *   `net.ipv4.tcp_ecn = 1` — включение явного уведомления о перегрузке.

**Валидация:**
```bash
# Проверка BBR
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = bbr

# Проверка ECN
sysctl net.ipv4.tcp_ecn
# → net.ipv4.tcp_ecn = 1

# Проверка throughput через iperf3
iperf3 -c <server> -t 30 -P 8
# Ожидаемый результат: > 90% от линковой скорости
```

### 4. Базы данных и репликация (PostgreSQL, MySQL)

**Задача:** Стабильная репликация, минимальные задержки транзакций.

*   **Буферы для репликации:**
    ```ini
    net.ipv4.tcp_rmem = 4096 87380 16777216
    net.ipv4.tcp_wmem = 4096 65536 16777216
    net.core.rmem_max = 16777216
    net.core.wmem_max = 16777216
    ```
*   **Keep-Alive для длинных соединений:**
    ```ini
    net.ipv4.tcp_keepalive_time = 300
    net.ipv4.tcp_keepalive_intvl = 30
    net.ipv4.tcp_keepalive_probes = 5
    ```
*   **Отключение Nagle для малых пакетов:** В приложении использовать `TCP_NODELAY`.

**Валидация:**
```bash
# Проверка соединений репликации
ss -tn state established | grep -E "5432|3306"
# Ожидаемый результат: stable connections, no retransmits

# Мониторинг ретрансмитов
nstat -az | grep RetransSegs
```

### 5. Стриминг и CDN (Nginx, HAProxy)

**Задача:** Максимальная пропускная способность для тяжелого контента.

*   **Большие буферы:**
    ```ini
    net.ipv4.tcp_rmem = 4096 131072 67108864
    net.ipv4.tcp_wmem = 4096 65536 67108864
    net.core.rmem_max = 67108864
    net.core.wmem_max = 67108864
    ```
*   **BBR для стабильного throughput:**
    ```ini
    net.ipv4.tcp_congestion_control = bbr
    net.core.default_qdisc = fq
    ```
*   **Оптимизация socket options в приложении:**
    ```c
    int optval = 1;
    setsockopt(sockfd, SOL_TCP, TCP_CORK, &optval, sizeof(optval));
    // После отправки всех данных:
    optval = 0;
    setsockopt(sockfd, SOL_TCP, TCP_CORK, &optval, sizeof(optval));
    ```

### 6. Kafka и высокопроизводительные очереди

**Задача:** Максимальный throughput для батчей сообщений.

*   **Буферы и keep-alive:**
    ```ini
    net.ipv4.tcp_rmem = 4096 87380 33554432
    net.ipv4.tcp_wmem = 4096 65536 33554432
    net.core.rmem_max = 33554432
    net.core.wmem_max = 33554432
    net.ipv4.tcp_keepalive_time = 60
    net.ipv4.tcp_keepalive_intvl = 10
    net.ipv4.tcp_keepalive_probes = 6
    ```
*   **Настройка `so_buffer` в Kafka:**
    ```properties
    # server.properties
    socket.send.buffer.bytes=1048576
    socket.receive.buffer.bytes=1048576
    ```

### 7. Docker и контейнеры

**Задача:** Оптимизация TCP для контейнеризированных приложений.

**Системные настройки (на хосте):**
```bash
# Увеличение лимитов для контейнеров
sudo sysctl -w net.core.rmem_max=134217728
sudo sysctl -w net.core.wmem_max=134217728
sudo sysctl -w net.ipv4.tcp_rmem="4096 131072 134217728"
sudo sysctl -w net.ipv4.tcp_wmem="4096 131072 134217728"
```

**Настройки для Docker:**
```bash
# При запуске контейнера
docker run --sysctl net.ipv4.tcp_rmem="4096 131072 134217728" \
           --sysctl net.ipv4.tcp_wmem="4096 131072 134217728" \
           your_image
```

**Для Kubernetes:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: high-perf-pod
spec:
  containers:
  - name: app
    image: your_image
    securityContext:
      sysctls:
      - name: net.ipv4.tcp_rmem
        value: "4096 131072 134217728"
      - name: net.ipv4.tcp_wmem
        value: "4096 131072 134217728"
```

### 8. Сохранение настроек

**Постоянное сохранение (`/etc/sysctl.d/99-network-performance.conf`):**
```ini
# Глобальные максимумы (128 МБ)
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728

# TCP буферы: min (4K), default (стандарт), max (128M)
net.ipv4.tcp_rmem = 4096 131072 134217728
net.ipv4.tcp_wmem = 4096 131072 134217728

# Очереди соединений
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 16384
net.core.netdev_max_backlog = 16384

# BBR + fq
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq

# Включение автотюнинга
net.ipv4.tcp_moderate_rcvbuf = 1

# Keep-Alive
net.ipv4.tcp_keepalive_time = 60
net.ipv4.tcp_keepalive_intvl = 10
net.ipv4.tcp_keepalive_probes = 6

# TIME_WAIT
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535
```

Применить: `sudo sysctl -p /etc/sysctl.d/99-network-performance.conf`

**Откат настроек:**
```bash
# Временный откат (до перезагрузки)
sudo sysctl -w net.core.rmem_max=212992
sudo sysctl -w net.core.wmem_max=212992

# Полный откат
sudo rm /etc/sysctl.d/99-network-performance.conf
sudo sysctl --system
```

## Современные технологии (2026)

### Multi-path TCP (MPTCP) в Linux 6.x+
Позволяет приложению прозрачно использовать несколько путей (например, Ethernet + Wi-Fi).
*   **Управление:** Утилита `ip mptcp` (пакет `iproute2`).
*   **Настройка:** `net.mptcp.enabled = 1`.
*   **Преимущества:** Отказоустойчивость, балансировка нагрузки, агрегация каналов.
*   **Ограничения:** Требует поддержки на стороне сервера, не работает с NAT без MPTCP-поддержки.

### eBPF и динамический тюнинг
В современных инфраструктурах eBPF используется для:
*   Автоматического подбора размера буферов под конкретный тип трафика.
*   Реализации продвинутых алгоритмов балансировки на уровне L4.
*   Мониторинга и диагностики в реальном времени без остановки приложения.

**Примеры eBPF-программ для TCP:**
```bash
# Мониторинг задержки установления соединений
tcpconnlat

# Отслеживание ретрансмитов в реальном времени
tcpretrans

# Визуализация сетевой активности по процессам
tcptop

# Мониторинг размера окна
tcpaccept
```

**Настройка через BPF_PROG_TYPE_SOCK_OPS:**
```c
// Пример: динамическое изменение initcwnd для конкретных соединений
SEC("sockops")
int bpf_set_initcwnd(struct bpf_sock_ops *skops) {
    // Установка initcwnd = 32 для соединений к определенному серверу
    if (skops->remote_port == htons(5432)) {
        bpf_setsockopt(skops, SOL_TCP, TCP_BPF_IW, &initcwnd, sizeof(initcwnd));
    }
    return 1;
}
```

### io_uring и сетевая производительность
Использование `io_uring` позволяет выполнять сетевые операции без копирования данных и с минимальным количеством системных вызовов, что дополняет тюнинг TCP на уровне приложения.

**Преимущества io_uring для TCP:**
*   Снижение количества контекстных переключений (context switches).
*   Уменьшение копирований данных (zero-copy).
*   Пакетная обработка нескольких соединений одновременно.

**Пример использования io_uring для TCP:**
```c
// Инициализация io_uring для TCP
struct io_uring ring;
io_uring_queue_init(256, &ring, 0);

// Регистрация TCP сокета
struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
io_uring_prep_recv(sqe, sockfd, buf, len, 0);
io_uring_sqe_set_data(sqe, context);
io_uring_submit(&ring);
```

### Corking и batching
Механизмы группировки пакетов для повышения эффективности:
*   **TCP_CORK:** Приложение может «закоротить» сокет, накапливая данные перед отправкой. Используется для отправки заголовков и тела ответа одним макетом.
*   **TCP_QUICKACK:** Принудительная немедленная отправка ACK (вместо отложенного). Полезно для протоколов с частыми обменами.

```c
// Пример использования TCP_CORK
int cork = 1;
setsockopt(sockfd, IPPROTO_TCP, TCP_CORK, &cork, sizeof(cork));
// Отправка заголовков и тела
write(sockfd, headers, headers_len);
write(sockfd, body, body_len);
// Сброс cork для немедленной отправки
cork = 0;
setsockopt(sockfd, IPPROTO_TCP, TCP_CORK, &cork, sizeof(cork));
```

## Диагностика и профилирование

### Основные инструменты

1.  **`ss -tin`** — просмотр детальных метрик (`cwnd`, `rtt`, `rto`, `pacing_rate`) для конкретных соединений.
    ```bash
    # Просмотр всех установленных соединений
    ss -tin state established

    # Просмотр соединений с конкретным хостом
    ss -tin state established dst 10.0.0.1

    # Просмотр с фильтрацией по порту
    ss -tin state established sport = :80
    ```

2.  **`nstat -az`** — анализ глобальных счетчиков.
    ```bash
    # Просмотр всех счетчиков TCP
    nstat -az

    # Фильтрация по ключевым счетчикам
    nstat -az | grep -E "Retrans|Memory|ZeroWindow|WindowFull"

    # Ключевые счетчики для мониторинга:
    # TcpRetransSegs — количество ретрансмитов
    # TcpExtTCPMemoryPressures — давление памяти
    # TcpExtTCPMemoryPressuresScheduled — запланированные освобождения
    # TcpExtTCPOFOQueue — out-of-order пакеты
    ```

3.  **eBPF-инструменты (bpftrace):**
    *   `tcpconnlat` — задержка установления соединений.
    *   `tcpretrans` — отслеживание ретрансмитов в реальном времени.
    *   `tcptop` — визуализация сетевой активности по процессам.
    *   `tcpaccept` — мониторинг входящих соединений.
    *   `tcpdrop` — отслеживание отброшенных пакетов.

### Диагностика типичных проблем

**Проблема: Низкий throughput**
```bash
# 1. Проверка размера окна
ss -tin state established | grep -E "cwnd|rcv_space"
# → Если rcv_space мал, увеличить tcp_rmem

# 2. Проверка ретрансмитов
nstat -az | grep RetransSegs
# → Если ретрансмиты растут, проверить сеть или алгоритм контроля перегрузки
# См. [Retransmission / RACK-TLP](./tcp_retransmission_rack.md)

# 3. Проверка ошибок
netstat -s | grep -i error
```

**Проблема: Высокая задержка**
```bash
# 1. Проверка busy_poll
sysctl net.core.busy_poll
# → Если busy_poll = 0, увеличить до 50
# См. [Busy Polling](./tcp_busy_polling.md)

# 2. Проверка Nagle + Delayed ACK
ss -tin | grep -E "nagle|ato"
# → Если ato:200 (Delayed ACK), включить TCP_NODELAY
# См. [TCP_NODELAY / TCP_CORK](./tcp_nodelay_cork_practical.md)

# 3. Проверка queue discipline
tc qdisc show dev eth0
# → Если pfifo_fast, заменить на fq для BBR
```

**Проблема: Connection refused**
```bash
# 1. Проверка somaxconn
sysctl net.core.somaxconn
# → Если somaxconn < 65535, увеличить

# 2. Проверка SYN backlog
sysctl net.ipv4.tcp_max_syn_backlog
# → Если tcp_max_syn_backlog < 16384, увеличить

# 3. Проверка Listen drops
nstat -az | grep ListenDrops
# → Если ListenDrops растет, увеличить очереди
```

**Проблема: Соединения зависают (MTU blackhole)**
```bash
# 1. Проверка PMTU
tracepath 10.0.0.1
# → Если MTU < 1500, проверить ICMP

# 2. Включение blackhole detection
sysctl -w net.ipv4.tcp_mtu_probing=2
# См. [PMTUD / MTU Probing](./tcp_pmtud_mtu_probing.md)
```

**Проблема: Много CLOSE-WAIT соединений**
```bash
# 1. Найти приложение
ss -tanp state close-wait | head
# → CLOSE-Wait = приложение не закрывает сокет

# 2. Решение: перезапуск приложения или исправление кода
# См. [TCP Connection States](./tcp_states_practical.md)
```

### Мониторинг и алерты

**Настройка мониторинга через Prometheus + node_exporter:**
См. [TCP Monitoring / Prometheus](./tcp_metrics_prometheus.md) для полного набора alerting rules и Grafana dashboards.
```yaml
# Примеры алертов
groups:
- name: tcp_alerts
  rules:
  - alert: HighTCPRetransmits
    expr: rate(node_netstat_Tcp_RetransSegs[5m]) > 0.01
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Высокий уровень ретрансмитов TCP"
      description: "Rate ретрансмитов > 1% в течение 5 минут"

  - alert: TCPMemoryPressure
    expr: node_netstat_TcpExt_TCPMemoryPressures > 100
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Давление памяти TCP"
      description: "Обнаружены TCPMemoryPressures > 100"

  - alert: HighZeroWindow
    expr: rate(node_netstat_TcpExt_TCPMemoryPressures[5m]) > 0
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Zero Window обнаружен"
      description: "Приложение не успевает читать данные из сокета"
```

**Автоматизация диагностики:**
```bash
# Скрипт быстрой диагностики TCP
#!/bin/bash
echo "=== TCP Diagnostics ==="
echo "--- Buffer sizes ---"
sysctl net.ipv4.tcp_rmem net.ipv4.tcp_wmem net.core.rmem_max net.core.wmem_max
echo "--- Congestion control ---"
sysctl net.ipv4.tcp_congestion_control net.core.default_qdisc
echo "--- Connection queues ---"
sysctl net.core.somaxconn net.ipv4.tcp_max_syn_backlog
echo "--- Memory pressure ---"
nstat -az | grep -E "TCPMemory|ZeroWindow|WindowFull"
echo "--- Retransmits ---"
nstat -az | grep RetransSegs
echo "--- Active connections ---"
ss -s
```

## Дополнительная информация

### Устаревшие параметры
*   **`net.ipv4.tcp_tw_recycle`** — удален в ядре 4.12. Ломает соединения через NAT.
*   **`net.ipv4.tcp_low_latency`** — устарел (no-op), заменен более совершенной логикой в планировщике пакетов.
*   **`net.ipv4.tcp_abort_on_overflow`** — не рекомендуется включать (значение 1). Лучше увеличить `somaxconn`.

### Выбор алгоритма перегрузки (BBRv3)
В 2026 году **BBRv3** является стандартом де-факто для сетей с потерями, так как он лишен проблем v1 с "несправедливым" захватом полосы и более корректно работает в сетях с потерями, не связанными с перегрузкой.

**Сравнение алгоритмов:**
| Алгоритм | Throughput | Latency | Loss tolerance | Год выпуска |
| :--- | :--- | :--- | :--- | :--- |
| **CUBIC** | Высокий | Средняя | Низкая | 2006 |
| **BBR v1** | Очень высокий | Низкая | Средняя | 2016 |
| **BBR v2** | Высокий | Низкая | Высокая | 2019 |
| **BBR v3** | Очень высокий | Очень низкая | Очень высокая | 2023 |

**Настройка BBR v3:**
```bash
# Проверка доступности
modprobe tcp_bbr
sysctl net.ipv4.tcp_available_congestion_control
# → cubic bbr

# Включение
sysctl -w net.ipv4.tcp_congestion_control=bbr
sysctl -w net.core.default_qdisc=fq

# Проверка
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = bbr
```

### Типичные ошибки при тюнинге

| Ошибка | Последствие | Решение |
| :--- | :--- | :--- |
| Слишком большие буферы | Bufferbloat, высокая задержка | Использовать BBR, ограничить `tcp_rmem` max |
| `tcp_tw_recycle` включена | Ломает соединения через NAT | Удалить параметр (ядро 4.12+) |
| `somaxconn` слишком мал | Connection refused при высокой нагрузке | Увеличить до 65535 |
| `busy_poll` = 0 | Высокая задержка на прерываниях | Увеличить до 50-100 |
| Неправильный `fq` qdisc | BBR не работает корректно | Установить `net.core.default_qdisc=fq` |

### Рекомендации по мониторингу

1. **Ежедневная проверка:**
   ```bash
   # Проверка ключевых счетчиков
   nstat -az | grep -E "Retrans|Memory|ZeroWindow"
   ```

2. **Еженедельный анализ:**
   ```bash
   # Анализ соединений по состояниям
   ss -s
   # Просмотр топ-10 соединений по throughput
   ss -tin state established | sort -k 10 -n -r | head -10
   ```

3. **Настройка алертов:**
   ```yaml
   # Prometheus alerting rules
   - alert: HighTCPRetransmits
     expr: rate(node_netstat_Tcp_RetransSegs[5m]) > 0.01
     for: 5m
   ```

### См. также
*   **[Оптимизация буферов TCP](./tcp_buffer_tuning.md)** — детальный разбор rmem/wmem.
*   **[Управление очередями соединений](./tcp_connection_queues.md)** — настройка backlog и somaxconn.
*   **[Алгоритмы контроля перегрузки](./tcp_congestion_algorithms.md)** — глубокое сравнение CUBIC и BBR.
*   **[Диагностика сокетов TCP](./tcp_socket_diagnostics.md)** — продвинутые методы анализа.
*   **[TCP Keepalive](./tcp_keepalive_production.md)** — production настройка keepalive по сценариям.
*   **[TCP_NODELAY / TCP_CORK](./tcp_nodelay_cork_practical.md)** — управление latency через socket options.
*   **[PMTUD / MTU Probing](./tcp_pmtud_mtu_probing.md)** — Path MTU Discovery и blackhole detection.
*   **[Retransmission / RACK-TLP](./tcp_retransmission_rack.md)** — механизмы обнаружения потерь.
*   **[TCP Connection States](./tcp_states_practical.md)** — CLOSE-WAIT, FIN-WAIT-2, orphan sockets.
*   **[TCP Monitoring](./tcp_metrics_prometheus.md)** — Prometheus/Grafana метрики и алерты.
*   **[TCP_USER_TIMEOUT](./tcp_user_timeout.md)** — таймаут ожидания ACK данных.
*   **[Busy Polling](./tcp_busy_polling.md)** — low-latency networking через активный опрос NIC.
*   **[TCP Small Queues](./tcp_small_queues.md)** — ограничение исходящих данных.
*   **[SO_REUSEPORT](./tcp_reuseport.md)** — балансировка соединений через ядро.
