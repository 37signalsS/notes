# TCP Retransmission / RACK-TLP / SACK — Практическое руководство

## Определения

**RTO (Retransmission Timeout)** — таймаут, после которого TCP-стек считает сегмент потеряным и отправляет его заново. Рассчитывается на основе RTT и его вариации (RTTVAR). Минимальный RTO = 200 мс (ядро Linux), максимальный = 120 сек.

**RACK-TLP (Recent ACKnowledgment - Tail Loss Probe)** — RFC 8985, современный механизм обнаружения потерь. Заменяет classic Fast Retransmit. Работает на основе времени (а не количества дублирующих ACK), что делает его эффективным при reordered пакетах и переменном RTT.

**Fast Retransmit** — механизм немедленной ретрансмиссии при получении 3 дублирующих ACK (dupACK). Устаревший, заменён RACK-TLP.

**SACK (Selective Acknowledgment)** — RFC 2018, механизм избирательного подтверждения. Получатель сообщает отправителю какие именно диапазоны данных получены, позволяя ретранслировать только потерянные сегменты.

**D-SACK (Duplicate SACK)** — RFC 2883, расширение SACK. Получатель сообщает отправителю о дублирующих данных, что помогает обнаружить spurious retransmissions (ложные ретрансмиссии).

**tcp_retries2** — sysctl-параметр, определяющий максимальное количество RTO-ретрансмиссий для ESTABLISHED соединений (по умолчанию 15). Формула: общее время ≈ 13-30 мин.

---

## Теоретический блок

### Механизм RTO

```
Отправитель                          Получатель
    │                                    │
    │  Сегмент #1 (seq=1000)             │
    │ ──────────────────────────────────►│
    │                                    │
    │  Сегмент #2 (seq=2460)             │
    │ ─────────────────────── X (потерян) │
    │                                    │
    │  Сегмент #3 (seq=3920)             │
    │ ──────────────────────────────────►│
    │                                    │
    │  ACK #2460 (dupACK #1)             │
    │ ◄──────────────────────────────────│
    │                                    │
    │  ACK #2460 (dupACK #2)             │
    │ ◄──────────────────────────────────│
    │                                    │
    │  ACK #2460 (dupACK #3)             │
    │ ◄──────────────────────────────────│
    │                                    │
    │  Fast Retransmit #2                │
    │ ──────────────────────────────────►│
    │                                    │
    │  ACK #5380 (все данные получены)    │
    │ ◄──────────────────────────────────│
```

### RACK-TLP vs Classic Fast Retransmit

| Параметр | Classic Fast Retransmit | RACK-TLP |
|---|---|---|
| **Детекция** | 3 dupACK | Время (reorder window) |
| **_reordered пакеты** | Ложная ретрансмиссия | Корректно игнорирует |
| **Tail loss** | Ждёт RTO | TLP отправляет probe через 2×srtt |
| **RFC** | RFC 5681 | RFC 8985 |
| **Включение** | Всегда | `tcp_recovery=1` (по умолчанию) |

### Tail Loss Probe (TLP)

```
Отправитель                          Получатель
    │                                    │
    │  Сегмент #1                        │
    │ ──────────────────────────────────►│
    │                                    │
    │  Сегмент #2 (последний)            │
    │ ─────────────────────── X (потерян) │
    │                                    │
    │  ... нет ACK ...                   │
    │                                    │
    │  TLP Probe (seq=snd_nxt-1)         │
    │ ──────────────────────────────────►│
    │                                    │
    │  DupACK #2 (ordinated)             │
    │ ◄──────────────────────────────────│
    │                                    │
    │  → RACK обнаружил потерю по времени │
    │  → Ретрансмиссия без ожидания RTO   │
```

### RTO Exponential Backoff

| Retry # | Задержка | Кумулятивно |
|---|---|---|
| 1 | 200 мс | 200 мс |
| 2 | 400 мс | 600 мс |
| 3 | 800 мс | 1.4 сек |
| 4 | 1.6 сек | 3 сек |
| 5 | 3.2 сек | 6.2 сек |
| 6 | 6.4 сек | 12.6 сек |
| 7 | 12.8 сек | 25.4 сек |
| 8 | 25.6 сек | 51 сек |
| 9 | 51.2 сек | ~1 мин |
| 10 | 102.4 сек | ~2 мин |
| 15 | ~30 мин | ~30 мин |

### SACK: формат и использование

```
┌──────────────────────────────────────────────────────┐
│ TCP Header                                            │
│  ...                                                  │
│  Kind: 5 (SACK)                                       │
│  Length: 10 (2 блока × 8 байт)                        │
│  ┌─────────────────────────────────────────────┐      │
│  │ Left Edge: 3000    Right Edge: 4460         │      │
│  │ Left Edge: 5920    Right Edge: 7380         │      │
│  └─────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────┘
→ Получены: [3000-4460] и [5920-7380]
→ Потеряны: [4460-5920]
→ Отправитель ретранслирует только [4460-5920]
```

### sysctl-параметры

| Параметр | Значение | Описание |
|---|---|---|
| `net.ipv4.tcp_sack` | `1` | SABLE включён (по умолчанию) |
| `net.ipv4.tcp_dsack` | `1` | D-SACK включён (по умолчанию) |
| `net.ipv4.tcp_recovery` | `1` | RACK включён (по умолчанию) |
| `net.ipv4.tcp_early_retrans` | `3` | Early retransmit + TLP |
| `net.ipv4.tcp_retries1` | `3` | Уведомление сети о проблемах |
| `net.ipv4.tcp_retries2` | `15` | Макс. ретрансмиссий ESTABLISHED |
| `net.ipv4.tcp_rto_min` | 200 | Минимальный RTO (мс) |
| `net.ipv4.tcp_frto` | `2` | F-RTO (spurious RTO detection) |

---

## Практический блок

### Проверка текущего состояния

```bash
# SACK включён?
sysctl net.ipv4.tcp_sack net.ipv4.tcp_dsack net.ipv4.tcp_recovery
# → net.ipv4.tcp_sack = 1
# → net.ipv4.tcp_dsack = 1
# → net.ipv4.tcp_recovery = 1

# Текущие ретрансмиссии
nstat -az | grep -E 'Retrans|SACK|RACK|Timeout'
# → TcpExtTCPSpuriousRtxHostQueues  → RACK spurious retransmits
# → TcpExtTCPSACKRecovery          → SACK-based recovery
# → TcpExtTCPFastRetrans           → Fast retransmits
# → TcpExtTCPRetrans               → Общее число ретрансмиссий
# → TcpExtTCPTimeouts              → RTO-based timeouts

# Ретрансмиссии для конкретного соединения
ss -tin dst 10.0.0.1 | grep retrans
# → retrans:0/3 → 0丢失, 3 ретрансмиссии

# Детальный вывод
ss -tin dst 10.0.0.1
# → rto:204 rtt:1.23/0.45 ato:40 retrans:0/3 rcv_space:14600 rcv_ssthresh:14600
```

### Monitoring

```bash
# Мониторинг ретрансмиссий в реальном времени
watch -n1 'nstat -az | grep -E "Retrans|SACK|Timeout|TLP"'

# Счётчики через /proc
cat /proc/net/netstat | tr ' ' '\n' | grep -E 'Retrans|SACK|Timeout'

# Базовый мониторинг
netstat -s | grep -i retrans
# → 123 segments retransmitted
# → 45 timeouts

# ss: соединения с ретрансмиссиями
ss -tin state established | awk '/retrans/ && $NF !~ /retrans:0\// {print $0}'
```

### Diagnostics через eBPF

```bash
# bpftrace: все ретрансмиссии с деталями
bpftrace -e 'kprobe:tcp_retransmit_skb {
    printf("retransmit: %s pid=%d saddr=%d.%d.%d.%d daddr=%d.%d.%d.%d\n",
        comm, pid,
        arg0 & 0xff, (arg0 >> 8) & 0xff, (arg0 >> 16) & 0xff, (arg0 >> 24) & 0xff,
        arg1 & 0xff, (arg1 >> 8) & 0xff, (arg1 >> 16) & 0xff, (arg1 >> 24) & 0xff
    );
}'

# bcc-tools: tcpretrans
tcpretrans           # Показывает все ретрансмиссии с RTT и cwnd
tcpretrans -l        # Только tail losses (TLP)
```

### Diagnostics через Wireshark/tshark

```bash
# Все ретрансмиссии
tshark -r capture.pcap -Y "tcp.analysis.retransmission" -T fields \
    -e frame.number -e ip.src -e ip.dst -e tcp.stream -e tcp.len

# Только fast retransmits
tshark -r capture.pcap -Y "tcp.analysis.fast_retransmission"

# Spurious retransmissions (RACK)
tshark -r capture.pcap -Y "tcp.analysis.spurious_retransmission"

# SACK-annotated retransmissions
tshark -r capture.pcap -Y "tcp.analysis.retransmission && tcp.analysis.sack"

# Статистика по потокам
tshark -r capture.pcap -q -z "io,stat,1,tcp.analysis.retransmission,tcp.analysis.fast_retransmission"

# D-SACK блоки
tshark -r capture.pcap -Y "tcp.options.sack" -T fields \
    -e tcp.stream -e tcp.options.sack_le -e tcp.options.sack_re
```

### Production sysctl-конфигурация

```bash
# /etc/sysctl.d/99-tcp-retransmission.conf

# RACK-TLP (включён по умолчанию, убедиться)
net.ipv4.tcp_recovery = 1
net.ipv4.tcp_early_retrans = 3

# SACK (включён по умолчанию)
net.ipv4.tcp_sack = 1
net.ipv4.tcp_dsack = 1

# RTO tuning для типичных серверов
net.ipv4.tcp_rto_min = 200    # Минимальный RTO (мс)
net.ipv4.tcp_retries1 = 3     # Уведомление сети о проблемах
net.ipv4.tcp_retries2 = 15    # Макс. ретрансмиссий (~30 мин)

# Для low-latency (trading, gaming)
net.ipv4.tcp_rto_min = 100    # Снизить минимальный RTO
net.ipv4.tcp_retries2 = 8     # Быстрее закрывать мёртвые соединения (~5 мин)

# Для высоколатентных каналов (satellite,跨洋)
net.ipv4.tcp_rto_min = 500    # Увеличить минимальный RTO
net.ipv4.tcp_retries2 = 20    # Больше попыток
```

### Prometheus alerting

```yaml
groups:
  - name: tcp_retransmission_alerts
    rules:
      - alert: HighTCPRetransmissions
        expr: rate(node_netstat_Tcp_RetransSegs[5m]) > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Высокий rate ретрансмиссий: {{ $value }}/s"

      - alert: CriticalTCPRetransmissions
        expr: rate(node_netstat_Tcp_RetransSegs[1m]) > 100
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Критический rate ретрансмиссий: {{ $value }}/s"

      - alert: HighTCPTimeouts
        expr: rate(node_netstat_TcpExtTCPTimeouts[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий rate TCP timeout: {{ $value }}/s"

      - alert: SpuriousRetransmissions
        expr: rate(node_netstat_TcpExtTCPSpuriousRtxHostQueues[5m]) > 5
        for: 10m
        labels:
          severity: info
        annotations:
          summary: "Spurious retransmissions: {{ $value }}/s — проверьте RACK"
```

### Troubleshooting decision tree

```
Высокий rate ретрансмиссий?
│
├─ retrans:0/3+ в ss -tin? → Да
│   ├─ Проблемы на уровне сети (packet loss)
│   │   ├─ ethtool -S eth0 | grep error → NIC errors?
│   │   ├─ nstat -az | grep InErrors → ядро дропает?
│   │   └─ mtr --report → loss на промежуточном хопе?
│   └─ Проблемы на уровне приложения
│       ├─ ListenOverflows? → Увеличить somaxconn
│       ├─ Zero Window? → Увеличить TCP buffers
│       └─ Memory Pressure? → Увеличить rmem/wmem
│
├─ RTO timeout (ss показывает rto:200+)? → Да
│   ├─ RTT высокий (>100 мс)? → Увеличить rto_min
│   ├─ tcp_retries2 = 15 → Слишком долго? Уменьшить до 8
│   └─ Соединение висит 30 мин → Нормально для retries2=15
│
└─ Spurious retransmissions? → Да
    ├─ RACK reorder_win слишком мал → Увеличить tcp_recovery
    ├─ ECMP reordering → Нормально, RACK должен обработать
    └─ LRO/GRO → Отключить на NIC: ethtool -K gro off
```

---

## Дополнительная информация

### Связанные файлы

- [TCP Retransmission](../../../Networking/Protocols/TCP/reliability_mechanisms/retransmission.md) — SSoT по механизмам ретрансмиссии
- [TCP SACK](../../../Networking/Protocols/TCP/reliability_mechanisms/acknowledgments.md) — SSoT по ACK и SACK
- [TCP Congestion Control](tcp_congestion_algorithms.md) — взаимодействие с congestion control
- [TCP Socket Diagnostics](tcp_socket_diagnostics.md) — полная диагностика

### RFC

- **RFC 8985** — RACK-TLP (2021)
- **RFC 2018** — TCP SACK (1996)
- **RFC 2883** — D-SACK (2000)
- **RFC 6675** — SACK-based Loss Recovery (2012)
- **RFC 5681** — TCP Congestion Control (2009)

### Важные замечания

1. **SACK应当 включён всегда** — отключение снижает производительность при потерях.
2. **RACK-TLP работает по умолчанию** в современных ядрах (4.x+).
3. **tcp_retries2=15 = ~30 мин** — это нормально для production, но для latency-sensitive можно уменьшить до 8-10.
4. **Spurious retransmissions** не всегда проблема — RACK корректно обнаруживает reordered пакеты.
5. **Wireshark фильтр `tcp.analysis.retransmission`** — основной инструмент для анализа pcap.
