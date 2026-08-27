# sysctl — сводка параметров для диагностики TCP

> **SSoT:** Тюнинг TCP — в **[TCP Tuning Overview](../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)**. Параметры ядра — в **[sysctl](../../../Linux/Core/kernel/sysctl.md)**. Автотюнинг — в **[TCP Flow Control](../../../Networking/Protocols/TCP/Flow_Control/index.md)**. Конгестия — в **[Congestion Control](../../../Networking/Protocols/TCP/congestion/tcp_congestion_control_overview.md)**. Wireshark-диагностика — в **[TCP Performance Diagnostics](./tcp_performance/tcp_performance_diagnostics.md)**.

## Определения

**sysctl** — механизм ядра Linux для чтения и изменения параметров в runtime через `/proc/sys/`. Позволяет настраивать сетевой стек без перезагрузки.

**tcp_rmem** — трёхзначный параметр (min, default, max) для автоматического размера буфера приёма (SO_RCVBUF). min=4096, default=87380, max=6291456 (по умолчанию).

**tcp_wmem** — аналогично tcp_rmem, но для буфера отправки (SO_SNDBUF).

**tcp_moderate_rcvbuf** — включение автоматического масштабирования буфера приёма (DRS). По умолчанию 1 (включено).

**tcp_congestion_control** — алгоритм контроля перегрузки. По умолчанию cubic. Рекомендуется bbr для длинных каналов.

**somaxconn** — максимальный размер очереди прослушивания (listen backlog). По умолчанию 4096. Рекомендуется 65535.

## Базовые концепты

### Как связать sysctl с симптомами в Wireshark

| Симптом в Wireshark | sysctl для исправления |
| :--- | :--- |
| **Zero Window** | `tcp_rmem` max увеличить, `tcp_moderate_rcvbuf=1` |
| **Window Full** | `tcp_wmem` max увеличить |
| **Bufferbloat** | `tcp_congestion_control=bbr`, `net.core.default_qdisc=fq` |
| **Retransmissions** | `tcp_congestion_control=bbr` (BBR игнорирует единичные потери) |
| **SYN drops** | `somaxconn=65535`, `tcp_max_syn_backlog=16384` |
| **TIME-WAIT exhaustion** | `tcp_tw_reuse=1`, `tcp_timestamps=1` |
| **Connection refused** | `somaxconn`, проверить `ss -ltn` |
| **Nagle + Delayed ACK** | Приложение: `TCP_NODELAY` (не sysctl) |

### Быстрая диагностика текущих значений

```bash
# Все параметры TCP
sysctl -a | grep net.ipv4.tcp

# Ключевые параметры
sysctl net.ipv4.tcp_rmem \
  net.ipv4.tcp_wmem \
  net.ipv4.tcp_moderate_rcvbuf \
  net.ipv4.tcp_congestion_control \
  net.core.somaxconn \
  net.core.netdev_max_backlog \
  net.ipv4.tcp_tw_reuse \
  net.ipv4.tcp_timestamps

# Проверка через ss для конкретного соединения
ss -tin dst 10.0.0.1 | grep -E "rcv_space|snd_space|cwnd|rtt"
```

## Конфигурация

### Рекомендуемый sysctl для продакшена (Web/API сервер)

```bash
# /etc/sysctl.d/99-tcp-performance.conf

# === Буферы TCP ===
# Автоматическое масштабирование (DRS)
net.ipv4.tcp_moderate_rcvbuf = 1

# Буфер приёма: min 4KB, default 128KB, max 16MB
net.ipv4.tcp_rmem = 4096 131072 16777216

# Буфер отправки: min 4KB, default 64KB, max 16MB
net.ipv4.tcp_wmem = 4096 65536 16777216

# Максимальный размер буфера сокета
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216

# Доступно данных в буфере (50% для данных)
net.ipv4.tcp_adv_win_scale = 1

# === Congestion Control ===
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq

# === Очереди ===
# Max listen backlog
net.core.somaxconn = 65535

# Max SYN backlog
net.ipv4.tcp_max_syn_backlog = 16384

# Max device backlog
net.core.netdev_max_backlog = 5000

# === TIME-WAIT ===
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_timestamps = 1

# Таймауты TIME-WAIT
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3

# === Защита ===
# SYN cookies (защита от SYN flood)
net.ipv4.tcp_syncookies = 1

# Защита от IP spoofing
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1

# Отключение ICMP redirect (безопасность)
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
```

### Рекомендуемый sysctl для Docker/Kubernetes

```bash
# /etc/sysctl.d/99-kubernetes.conf

# Conntrack
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_tcp_timeout_established = 3600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30

# TCP
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_rmem = 4096 131072 67108864
net.ipv4.tcp_wmem = 4096 65536 67108864
net.core.rmem_max = 67108864
net.core.wmem_max = 67108864
net.ipv4.tcp_moderate_rcvbuf = 1
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq

# Очереди
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 16384
net.core.netdev_max_backlog = 5000

# ip_forward для Kubernetes
net.ipv4.ip_forward = 1

# ARP (предотвращение spoofing)
net.ipv4.conf.all.arp_announce = 2
net.ipv4.conf.all.arp_ignore = 1
```

### Безопасные sysctl для Pod'ов в Kubernetes

```yaml
# В PodSpec (только safe sysctl)
spec:
  securityContext:
    sysctls:
    - name: net.ipv4.tcp_keepalive_time
      value: "600"
    - name: net.ipv4.tcp_keepalive_intvl
      value: "30"
    - name: net.ipv4.tcp_keepalive_probes
      value: "3"

# Unsafe sysctl требуют --allowed-unsafe-sysctls в kubelet:
# kubelet --allowed-unsafe-sysctls=net.ipv4.tcp_rmem,net.ipv4.tcp_wmem
```

## Практические сценарии

### Сценарий 1: Wireshark Zero Window → sysctl fix

```bash
# 1. Диагностика в Wireshark
tshark -r capture.pcap -Y "tcp.analysis.zero_window" -T fields \
  -e frame.number -e tcp.stream -e ip.src -e ip.dst

# 2. Проверка буфера на сервере
ss -tin dst <CLIENT_IP> | grep rcv_space
# → rcv_space:4096  ← слишком мало!

# 3. Проверка sysctl
sysctl net.ipv4.tcp_rmem
# → net.ipv4.tcp_rmem = 4096 87380 6291456  ← max = 6MB (норма)

# 4. Проверка DRS
sysctl net.ipv4.tcp_moderate_rcvbuf
# → net.ipv4.tcp_moderate_rcvbuf = 1  ← включено (норма)

# 5. Если DRS включен, но rcv_space мал → приложение медленно читает
# Решение: оптимизировать приложение или увеличить tcp_rmem max
sudo sysctl -w net.ipv4.tcp_rmem='4096 131072 67108864'
```

### Сценарий 2: Wireshark Retransmissions → BBR

```bash
# 1. Диагностика в Wireshark
tshark -r capture.pcap -Y "tcp.analysis.retransmission" -q \
  -z "io,stat,1,COUNT(tcp.analysis.retransmission)tcp.analysis.retransmission"

# 2. Проверка текущего алгоритма
sysctl net.ipv4.tcp_congestion_control
# → cubic  ← реагирует на потери, снижает CWND

# 3. Включение BBR
sudo sysctl -w net.ipv4.tcp_congestion_control=bbr
sudo sysctl -w net.core.default_qdisc=fq

# 4. Проверка
sysctl net.ipv4.tcp_congestion_control
# → bbr
```

### Сценарий 3: Connection refused → somaxconn

```bash
# 1. В Wireshark: SYN → RST (или таймаут)
tshark -r capture.pcap -Y "tcp.flags.syn == 1 && tcp.flags.ack == 0" -T fields \
  -e frame.number -e ip.dst -e tcp.dstport | head -5

# 2. Проверка listen queue
ss -ltn | grep :80
# → LISTEN  0  128  0.0.0.0:80  ← Backlog = 128 (мало!)

# 3. Проверка somaxconn
sysctl net.core.somaxconn
# → 128  ← слишком мало

# 4. Увеличение
sudo sysctl -w net.core.somaxconn=65535

# 5. Проверка переполнения
nstat -az | grep -E "ListenOverflows|ListenDrops"
# → TcpExtListenOverflows 15  ← было переполнение
```

### Сценарий 4: Bufferbloat → fq + BBR

```bash
# 1. В Wireshark: RTT растёт с нагрузкой
tshark -r capture.pcap -Y "tcp.len > 0" -q \
  -z "io,stat,1,AVG(tcp.analysis.ack_rtt),SUM(tcp.len)*8/1"

# 2. Проверка qdisc
tc qdisc show dev eth0
# → qdisc pfifo_fast 0 refcnt 2 limit 1000p  ← стандартный (плохо)

# 3. Включение fq + BBR
sudo sysctl -w net.core.default_qdisc=fq
sudo sysctl -w net.ipv4.tcp_congestion_control=bbr

# 4. Проверка
tc qdisc show dev eth0
# → qdisc fq 0 refcnt 2 limit 10000p  ← fair queue (хорошо)
```

## Дополнительная информация

### Параметры для мониторинга (nstat)

```bash
# Ключевые counter для мониторинга
nstat -az | grep -E "TcpRetrans|TcpExtTCP.*Timeout|TcpExtListen|TcpInCsum|TcpExtTCPWindow"

# Нормы:
# TcpRetransSegs / TcpOutSegs < 0.01  (ретрансмиссии < 1%)
# TcpExtTCPTimeouts = 0               (RTO таймаутов нет)
# TcpExtListenOverflows = 0           (очередь не переполняется)
# TcpInCsumErrors = 0                 (ошибок checksum нет)
# TcpExtTCPWindowFull = 0             (окно не заполнено)
```

### Версионные особенности sysctl

| Параметр | Ядро | Примечание |
| :--- | :--- | :--- |
| `tcp_moderate_rcvbuf` | 2.6+ | DRS (Dynamic Receiver Sizing) |
| `tcp_congestion_control=bbr` | 4.9+ | BBR v1 |
| `tcp_congestion_control=bbr` | 5.18+ | BBR v2 |
| `tcp_congestion_control=bbr` | 6.6+ | BBR v3 |
| `tcp_rmem` max | 2.6+ | Автотюнинг |
| `tcp_adv_win_scale` | 2.6+ | Доступно данных |
| `tcp_tw_recycle` | 2.6-4.12 | DEPRECATED (былdangerous) |
| `io_uring_disabled` | 5.10+ | Ограничение io_uring |

### См. также
- **[TCP Tuning Overview](../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — полный гайд по тюнингу
- **[sysctl](../../../Linux/Core/kernel/sysctl.md)** — настройка параметров ядра
- **[TCP Congestion Control](../../../Networking/Protocols/TCP/congestion/tcp_congestion_control_overview.md)** — BBR, CUBIC
- **[TCP Flow Control](../../../Networking/Protocols/TCP/Flow_Control/index.md)** — autotuning, DRS
- **[TCP Performance Diagnostics](./tcp_performance/tcp_performance_diagnostics.md)** — анализ через Wireshark
- **[NAT Conntrack Analysis](./nat_conntrack_firewall_analysis.md)** — conntrack sysctl
