# TCP Monitoring / Prometheus / Grafana — Практическое руководство

## Определения

**TCP Metrics** — набор метрик для мониторинга состояния TCP-стека: ретрансмиссии, очереди, соединения, ошибки. Собираются через `node_exporter` (collector `netstat` или `tcpstat`) и отображаются в Prometheus/Grafana.

**node_netstat_Tcp_*** — метрики Prometheus, экспортируемые `node_exporter` из `/proc/net/netstat`. Формат: `node_netstat_Tcp_<CounterName>`.

**node_sockstat_*** — метрики состояния сокетов из `/proc/net/sockstat`. Формат: `node_sockstat_TCP_<metric>`.

**TcpExt*** — счётчики расширенной статистики TCP из `/proc/net/netstat` (раздел TcpExt). Включают ~60 метрик для детальной диагностики.

---

## Теоретический блок

### Архитектура мониторинга

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Ядро Linux │     │node_exporter │     │  Prometheus  │
│              │     │              │     │              │
│ /proc/net/   │────►│ /proc/net/   │────►│ scrape       │
│   netstat    │     │   sockstat   │     │ (15-30 сек)  │
│   sockstat   │     │   iface      │     │              │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                  │
                                           ┌──────▼───────┐
                                           │   Grafana    │
                                           │   Dashboard  │
                                           └──────────────┘
```

### Ключевые TCP-метрики

| Метрика | Источник | Описание | Порог алерта |
|---|---|---|---|
| `node_netstat_Tcp_RetransSegs` | TcpExt | Ретрансмиссии | > 0.05/s warning |
| `node_netstat_Tcp_InSegs` | Tcp | Входящие сегменты | — |
| `node_netstat_Tcp_OutSegs` | Tcp | Исходящие сегменты | — |
| `node_netstat_Tcp_CurrEstab` | Tcp | ESTABLISHED соединения | > 10000 warning |
| `node_netstat_TcpExt_ListenOverflows` | TcpExt | Превышение listen queue | > 0 warning |
| `node_netstat_TcpExt_ListenDrops` | TcpExt | Дропы в listen queue | > 0 critical |
| `node_netstat_TcpExt_TCPTimeouts` | TcpExt | RTO таймауты | > 10/s warning |
| `node_netstat_TcpExt_TCPFastRetrans` | TcpExt | Fast retransmits | > 5/s warning |
| `node_netstat_TcpExt_TCPSpuriousRtxHostQueues` | TcpExt | Spurious retransmits | > 5/s info |
| `node_netstat_TcpExt_TCPMemoryPressures` | TcpExt | Memory pressure events | > 0 warning |
| `node_netstat_TcpExt_TCPWindowFull` | TcpExt | Full window (receiver) | > 10/s warning |
| `node_netstat_TcpExt_TCPRecvQueueFull` | TcpExt | Receive queue overflow | > 0 critical |
| `node_netstat_TcpExt_TCPSACKRecovery` | TcpExt | SACK-based recovery | — |
| `node_netstat_TcpExt_TCPACKDelayed` | TcpExt | Delayed ACK | — |
| `node_netstat_TcpExt_TCPACKCompressed` | TcpExt | Compressed ACK | — |
| `node_sockstat_TCP_alloc` | sockstat | Allocated TCP sockets | — |
| `node_sockstat_TCP_inuse` | sockstat | In-use TCP sockets | — |
| `node_sockstat_TCP_orphan` | sockstat | Orphaned sockets | > 1000 warning |
| `node_sockstat_TCP_tw` | sockstat | TIME_WAIT sockets | > 50000 warning |
| `node_sockstat_TCP_mem` | sockstat | TCP memory (pages) | — |

### Расчётные метрики (PromQL)

```promql
# Rate ретрансмиссий за 5 минут
rate(node_netstat_Tcp_RetransSegs[5m])

# Процент ретрансмиссий от общего числа сегментов
rate(node_netstat_Tcp_RetransSegs[5m]) / rate(node_netstat_Tcp_OutSegs[5m]) * 100

# Rate TCP timeout за 5 минут
rate(node_netstat_TcpExt_TCPTimeouts[5m])

# Listen overflow rate
rate(node_netstat_TcpExt_ListenOverflows[5m])

# Memory pressure rate
rate(node_netstat_TcpExt_TCPMemoryPressures[5m])

# Orphan growth rate
deriv(node_sockstat_TCP_orphan[1h])

# TIME_WAIT ratio
node_sockstat_TCP_tw / (node_sockstat_TCP_alloc - node_sockstat_TCP_tw) * 100
```

---

## Практический блок

### Настройка node_exporter

```bash
# Убедиться что collectors включены
# /etc/default/node_exporter или Systemd unit
--collector.netstat \
--collector.tcpstat \
--collector.sockstat

# Проверка метрик
curl -s http://localhost:9100/metrics | grep -E "node_netstat_Tcp|node_sockstat_TCP"
```

### Prometheus alerting rules

```yaml
# /etc/prometheus/rules/tcp_alerts.yml
groups:
  - name: tcp_alerts
    rules:
      # === Retransmissions ===
      - alert: HighTCPRetransmissions
        expr: rate(node_netstat_Tcp_RetransSegs[5m]) > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High TCP retransmissions on {{ $labels.instance }}"
          description: "Rate: {{ $value }}/s"

      - alert: CriticalTCPRetransmissions
        expr: rate(node_netstat_Tcp_RetransSegs[1m]) > 100
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Critical TCP retransmissions on {{ $labels.instance }}"

      # === Listen Queue ===
      - alert: HighListenOverflows
        expr: rate(node_netstat_TcpExt_ListenOverflows[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Listen queue overflow on {{ $labels.instance }}"

      - alert: HighListenDrops
        expr: rate(node_netstat_TcpExt_ListenDrops[5m]) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Listen queue drops on {{ $labels.instance }}"

      # === Memory ===
      - alert: TCPMemoryPressure
        expr: rate(node_netstat_TcpExt_TCPMemoryPressures[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "TCP memory pressure on {{ $labels.instance }}"

      # === Timeouts ===
      - alert: HighTCPTimeouts
        expr: rate(node_netstat_TcpExt_TCPTimeouts[5m]) > 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High TCP timeouts on {{ $labels.instance }}"

      # === Orphan Sockets ===
      - alert: HighOrphanedSockets
        expr: node_sockstat_TCP_orphan > 1000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High orphaned sockets on {{ $labels.instance }}: {{ $value }}"

      # === TIME_WAIT ===
      - alert: HighTimeWait
        expr: node_sockstat_TCP_tw > 50000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High TIME_WAIT sockets on {{ $labels.instance }}: {{ $value }}"

      # === Zero Window ===
      - alert: HighZeroWindow
        expr: rate(node_netstat_TcpExt_TCPWindowFull[5m]) > 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High TCP window full events on {{ $labels.instance }}"
```

### Grafana Dashboard: Key TCP Metrics

```json
{
  "dashboard": {
    "title": "TCP Stack Monitoring",
    "panels": [
      {
        "title": "TCP Retransmissions Rate",
        "type": "timeseries",
        "targets": [
          {
            "expr": "rate(node_netstat_Tcp_RetransSegs[5m])",
            "legendFormat": "{{ instance }}"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "short",
            "custom": {
              "drawStyle": "line",
              "lineWidth": 2,
              "fillOpacity": 20
            }
          }
        }
      },
      {
        "title": "Retransmission %",
        "type": "gauge",
        "targets": [
          {
            "expr": "rate(node_netstat_Tcp_RetransSegs[5m]) / rate(node_netstat_Tcp_OutSegs[5m]) * 100"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "percent",
            "thresholds": {
              "steps": [
                { "value": 0, "color": "green" },
                { "value": 0.1, "color": "yellow" },
                { "value": 1, "color": "red" }
              ]
            }
          }
        }
      },
      {
        "title": "Listen Queue Overflow",
        "type": "timeseries",
        "targets": [
          {
            "expr": "rate(node_netstat_TcpExt_ListenOverflows[5m])",
            "legendFormat": "{{ instance }}"
          }
        ]
      },
      {
        "title": "TCP Memory Pressure",
        "type": "timeseries",
        "targets": [
          {
            "expr": "rate(node_netstat_TcpExt_TCPMemoryPressures[5m])",
            "legendFormat": "{{ instance }}"
          }
        ]
      },
      {
        "title": "Orphaned Sockets",
        "type": "stat",
        "targets": [
          {
            "expr": "node_sockstat_TCP_orphan"
          }
        ]
      },
      {
        "title": "TIME_WAIT Sockets",
        "type": "stat",
        "targets": [
          {
            "expr": "node_sockstat_TCP_tw"
          }
        ]
      },
      {
        "title": "ESTABLISHED Connections",
        "type": "timeseries",
        "targets": [
          {
            "expr": "node_netstat_Tcp_CurrEstab",
            "legendFormat": "{{ instance }}"
          }
        ]
      }
    ]
  }
}
```

### Diagnostics: быстрая оценка TCP-стека

```bash
# Базовый health check TCP-стека
echo "=== TCP Summary ==="
ss -s

echo "=== Retransmissions ==="
nstat -az | grep -E 'TCPRetrans|TCPTimeouts|TCPFastRetrans'

echo "=== Listen Queue ==="
nstat -az | grep -E 'ListenOverflows|ListenDrops'

echo "=== Memory ==="
nstat -az | grep TCPMemoryPressure

echo "=== Orphaned Sockets ==="
ss -s | grep orphaned

echo "=== Top Connections by RTT ==="
ss -tin state established | awk '/rtt/ {
    match($0, /rtt:([0-9.]+)/, a);
    if (a[1]+0 > 10) print $0
}' | head -10
```

### Быстрый мониторинг через watch

```bash
# Watch: ретрансмиссии + listen overflows
watch -n1 'nstat -az | grep -E "Retrans|ListenO|ListenD|Timeout|Memory"'

# Watch: соединения по состояниям
watch -n5 'ss -tan | awk "{print \$1}" | sort | uniq -c | sort -rn'
```

---

## Дополнительная информация

### Связанные файлы

- [TCP Socket Diagnostics](tcp_socket_diagnostics.md) — полная диагностика соединений
- [TCP Connection Queues](tcp_connection_queues.md) — listen queue overflow
- [TCP Congestion Control](tcp_congestion_algorithms.md) — мониторинг congestion
- [node_exporter collectors](../../../Prometheus/) — настройка Prometheus

### Важные замечания

1. **node_exporter collectors** `netstat` и `sockstat`应当 включены явно.
2. **Ретрансмиссии > 0.05/s** — признак проблем с сетью или NIC.
3. **ListenOverflows > 0** — признак переполнения backlog, увеличить somaxconn.
4. **TCPMemoryPressure > 0** — признак нехватки памяти для TCP-стека.
5. **Orphaned > 1000** — возможна утечка соединений в приложении.
