# Диагностика сетевой производительности

## Определения

**Network Performance Diagnostics** — процесс анализа пропускной способности, задержек, потерь пакетов и перегрузки сетевого стека Linux. Ключевые инструменты: `ss`, `nstat`, `iperf3`, `sar -n`, `ethtool`, `/proc/net/softnet_stat`.

**TCP Retransmission** — повторная передача сегмента TCP из-за потери или задержки ACK. Высокий уровень ретрансмитов (> 1% от сегментов) указывает на проблемы с сетью: потери на коммутаторе, перегрузку буферов, некорректный MTU.

**Ring Buffer** — аппаратный буфер NIC, куда DMA записывает входящие пакеты до обработки ядром. Если ring buffer переполняется ( rx_missed_errors ), пакеты отбрасываются. Увеличение ring buffer решает проблему потерь на high-traffic серверах.

**SoftIRQ (NET_RX/NET_TX)** — программные прерывания для обработки сетевых пакетов. Высокий `%soft` в `mpstat` или рост `NET_RX_SOFTIRQ` в `/proc/softirqs` указывает на перегрузку сетевого стека.

**Socket Buffer (rmem/wmem)** — буферы ядра для хранения данных в сокете. `rmem` — для входящих данных (чтение приложением), `wmem` — для исходящих. Недостаточный размер буферов → задержки и потери.

**Backlog overflow** — переполнение очереди входящих соединений (`listen()` backlog). Если `Recv-Q` в `ss -tlnp` стабильно равен `Send-Q` — приложение не успевает принимать соединения. Увеличить `net.core.somaxconn`.

---

## Основные концепции

### Алгоритм быстрой оценки сетевой производительности

```bash
# Шаг 1: Состояние сокетов
ss -s

# Шаг 2: Ретрансмиты
nstat -az | grep -i retrans

# Шаг 3: Пропускная способность (если есть вторая нода)
iperf3 -c <target> -t 10 -P 4

# Шаг 4: Потери на уровне NIC
ethtool -S eth0 | grep -E "error|drop|miss|fifo|overflow"

# Шаг 5: SoftIRQ нагрузка
cat /proc/softirqs | grep NET_RX
mpstat -P ALL 1 3 | grep -v CPU | awk '{print $7}'  # %soft

# Шаг 6: Статистика ядра
nstat -az | grep -E "TcpRetransSegs|TcpOutSegs|TcpExtTCPTimeout|TcpExtListenOverflows"
```

### ss -s: быстрая сводка

```bash
$ ss -s
Total: 2845
TCP:   2421 (estab 1850, closed 320, orphaned 12, timewait 320)
Transport     Total     IPv6     IPv4
UDP           424       210      214
```

| Метрика | Норма | Тревога |
|:---|:---|:---|
| `TCP total` | Стабильно | Резкий рост |
| `estab` | Стабильно | Рост = рост нагрузки |
| `orphaned` | < 100 | > 500 (утечка соединений) |
| `timewait` | < 1000 | > 5000 (много коротких соединений) |
| `closed` | ≈ 0 | > 100 (проблема с accept) |

### nstat: метрики TCP

```bash
$ nstat -az | grep -E "Retrans|Timeout|ListenOverflow|ListenDrop|TCPBacklogDrop|TCPRetransFail"
TcpRetransSegs          1250    0.0
TcpExtTCPTimeout        320     0.0
TcpExtListenOverflows   45      0.0
TcpExtListenDrops       45      0.0
TcpExtTCPBacklogDrop    12      0.0
```

| Метрика | Норма | Проблема | Действие |
|:---|:---|:---|:---|
| `TcpRetransSegs` | < 1% от `TcpOutSegs` | > 2% | `ss -tin` → rtt, check network path |
| `TcpExtTCPTimeout` | < 10/мин | > 50/мин | Таймауты соединений, проверить firewall |
| `ListenOverflows` | 0 | > 0 | Увеличить `somaxconn` и backlog |
| `ListenDrops` | 0 | > 0 | Приложение не accept()ает |
| `TCPBacklogDrop` | 0 | > 0 | `net.core.netdev_max_backlog` слишком мал |

### iperf3: бенчмаркинг пропускной способности

```bash
# Сервер
iperf3 -s

# Клиент: TCP throughput
iperf3 -c <server> -t 10 -P 4

# Клиент: UDP throughput
iperf3 -c <server> -u -b 10G -t 10

# Сравнение до/после тюнинга
iperf3 -c <server> -t 30 --json > before.json
# ... тюнинг ...
iperf3 -c <server> -t 30 --json > after.json
```

**Ожидаемая пропускная способность:**

| Канал | TCP throughput | Факторы |
|:---|:---|:---|
| 1 Gbps | ~940 Mbps | NIC offloading, MTU |
| 10 Gbps | ~9.4 Gbps | Ring buffer, IRQ affinity |
| 25 Gbps | ~23 Gbps | NUMA, driver |
| 100 Gbps | ~90+ Gbps | DPDK, XDP |

### NIC ring buffer: диагностика и тюнинг

```bash
# Текущий размер
ethtool -g eth0

# Увеличение (до максимума)
ethtool -G eth0 rx 4096 tx 4096

# Проверка потерь
ethtool -S eth0 | grep -E "rx_missed|rx_fifo|rx_crc|rx_frame|tx_dropped"
```

| Счётчик | Норма | Проблема | Решение |
|:---|:---|:---|:---|
| `rx_missed_errors` | 0 | > 0 | Увеличить ring buffer |
| `rx_fifo_errors` | 0 | > 0 | NIC не справляется (driver/budget) |
| `rx_crc_errors` | 0 | > 0 | Плохой кабель/SFP |
| `tx_dropped` | 0 | > 0 | TC qdisc переполнен |

### SoftIRQ: диагностика сетевого стека

```bash
# Нагрузка на ядра
cat /proc/softirqs | grep -E "NET_RX|NET_TX"
# → NET_RX: CPU0=500000 CPU1=5000 CPU2=5000 CPU3=5000
# Проблема: 95% трафика на CPU0

# Динамическое наблюдение
watch -d -n 1 'cat /proc/softirqs | grep NET'

# Проверка irqbalance
systemctl status irqbalance

# Проверка softnet_stat
cat /proc/net/softnet_stat
# col 0: processed
# col 1: dropped
# col 2: time_squeeze
```

| Счётчик | Норма | Проблема |
|:---|:---|:---|
| `NET_RX` processed | Растёт с трафиком | — |
| `NET_RX` dropped | 0 | > 0: `netdev_max_backlog` мал |
| `NET_RX` time_squeeze | 0 | > 0: `netdev_budget` мал или IRQ на одном ядре |
| Неравномерность по CPU | ±20% | > 50%: настроить RSS/RPS |

### RSS/RPS: распределение трафика по ядрам

```bash
# Текущий RSS (Receive Side Scaling)
ethtool -k eth0 | grep receive-hashing
# → receive-hashing: on

# Настройка RPS (Receive Packet Steering) — программный RSS
echo "f" > /sys/class/net/eth0/queues/rx-0/rps_cpus  # ядра 0-3

# Настройка RFS (Receive Flow Steering)
echo 32768 > /sys/class/net/eth0/queues/rx-0/rps_flow_cnt
echo 32768 > /proc/sys/net/core/rps_sock_flow_entries
```

---

## Практические сценарии

### Сценарий 1: Высокий %soft в mpstat

**Симптом:** Сетевой сервер, `mpstat` показывает `%soft = 35%` на одном ядре.

```bash
# 1. Подтверждение
mpstat -P ALL 1 3
# → CPU0: %soft=35, остальные: %soft=1-2

# 2. Источник softirq
cat /proc/softirqs | grep NET_RX
# → CPU0: 850000, CPU1: 12000, CPU2: 11500, CPU3: 11000

# 3. Проверка IRQ
cat /proc/interrupts | grep eth0
# → eth0: 1500000  PCI-MSI-edge  eth0-TxRx-0

# 4. Проверка rss
ethtool -k eth0 | grep -i "receive.*hash"
```

**Решение:**
```bash
# Включить irqbalance
systemctl enable --now irqbalance

# Или ручная настройка RPS
echo "f" > /sys/class/net/eth0/queues/rx-0/rps_cpus

# Увеличить budget
echo 600 > /proc/sys/net/core/netdev_budget
```

### Сценарий 2: Retransmissions и латентность

**Симптом:** P99 latency растет, `ss -tin` показывает `retrans:1/15`.

```bash
# 1. Статистика ретрансмитов
nstat -az | grep -i retrans
# → TcpRetransSegs  1250   (за 10 сек = 125/сек)

# 2. Детали соединения
ss -tin dst <server_ip>
# → retrans:1/15 rtt:25/10 rcv_space:14600

# 3. Проверка MTU
ip link show eth0 | grep mtu
# → mtu 1500 (нормально)

# 4. Проверка path MTU
ping -M do -s 1472 <server_ip>
# → OK (MTU 1500 работает)

# 5. tcpdump для захвата retransmits
tcpdump -i eth0 'tcp[tcpflags] & (tcp-syn|tcp-fin) != 0' -c 100
```

**Решение:**
1. Увеличить TCP буферы: `net.ipv4.tcp_rmem`, `net.ipv4.tcp_wmem`
2. Включить BBR: `sysctl net.ipv4.tcp_congestion_control=bbr`
3. Проверить сеть: `iperf3 -c <server> -u -b 1G -t 10` (UDP loss)

### Сценарий 3: Listen overflow

**Симптом:** В логах `connection refused`, `nstat` показывает `ListenOverflows`.

```bash
# 1. Проверка
nstat -az | grep ListenOverflow
# → TcpExtListenOverflows  45

# 2. Текущий somaxconn
sysctl net.core.somaxconn
# → 128 (слишком мало!)

# 3. Backlog в приложении
ss -tlnp | grep :80
# → Recv-Q: 128  Send-Q: 128  ← переполнено!

# 4. Количество соединений
ss -s
# → TCP: 5000 (estab 4800)
```

**Решение:**
```bash
# Увеличить somaxconn
sysctl -w net.core.somaxconn=65535

# Постоянно
echo "net.core.somaxconn = 65535" >> /etc/sysctl.d/99-network.conf

# В приложении (nginx)
# listen 80 backlog=65535;
```

### Сценарий 4: Packet drops на NIC

**Симптом:** `ethtool -S` показывает рост `rx_missed_errors`.

```bash
# 1. Проверка
ethtool -S eth0 | grep -E "missed|fifo|drop|overflow"
# → rx_missed_errors: 15000
# → rx_fifo_errors: 5000

# 2. Текущий ring buffer
ethtool -g eth0
# → Pre-set: RX: 256, TX: 256
# → Current: RX: 256, TX: 256

# 3. Максимум
# → Max: RX: 4096, TX: 4096
```

**Решение:**
```bash
# Увеличить ring buffer
ethtool -G eth0 rx 4096 tx 4096

# Проверка
ethtool -S eth0 | grep -E "missed|fifo"
# → rx_missed_errors: 15000 (не растёт = решение работает)
```

---

## Дополнительная информация

### Связанные темы

- [**ss**](../Networking/ss.md) — полная справочная по ss
- [**nstat**](../Networking/nstat_diagnostics.md) — метрики TCP
- [**iperf3**](../Networking/iperf3.md) — бенчмаркинг сети
- [**nic_hardware_diagnostics**](../Networking/nic_hardware_diagnostics.md) — аппаратная диагностика NIC
- [**TCP tuning**](../../Networking/Concepts/tcp_tuning/tcp_tuning_overview.md) — тюнинг TCP
- [**TCP production tuning**](../../../Networking/Protocols/TCP/production_tuning.md) — production-параметры
- [**TCP retransmission**](../../../Networking/Protocols/TCP/reliability_mechanisms/retransmission.md) — ретрансмиты
- [**TCP congestion**](../../../Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md) — алгоритмы перегрузки
- [**netstat**](../Networking/netstat.md) — устаревший netstat
- [**tcpdump**](../Networking/tcpdump.md) — захват пакетов
- [**tc_diagnostics**](../Networking/tc_diagnostics.md) — traffic control
- [**conntrack**](../Networking/conntrack_diagnostics.md) — connection tracking
- [**sysctl network**](../../Networking/Settings/sysctl_network.md) — сетевые sysctl

### Справочная: ключевые sysctl для сети

```bash
# /etc/sysctl.d/99-network-performance.conf

# Буферы сокетов
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Очереди
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65535

# Congestion control
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq

# Keepalive
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3

# Retries
net.ipv4.tcp_synack_retries = 2
net.ipv4.tcp_retries2 = 8

# Time wait
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
```

### Чек-лист быстрой диагностики сети

```bash
# 1. Общая сводка
ss -s

# 2. Ретрансмиты
nstat -az | grep -iE "retrans|timeout|overflow|drop"

# 3. NIC ошибки
ethtool -S eth0 | grep -E "error|drop|miss|fifo"

# 4. SoftIRQ
mpstat -P ALL 1 3 | awk '{print $1, $7}'

# 5. Пропускная способность
iperf3 -c <target> -t 10 -P 4

# 6. Сокеты с высоким RTT
ss -tin | awk '$4 > 50 {print}'

# 7. Conntrack
cat /proc/sys/net/netfilter/nf_conntrack_count
cat /proc/sys/net/netfilter/nf_conntrack_max
```
