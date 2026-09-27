# Диагностика сетевого мониторинга (Prometheus + node_exporter + Blackbox)

## Определения

**Prometheus** — система мониторинга и алертинга с pull-моделью сбора метрик. Хранит данные в time-series базе, поддерживает PromQL для запросов.

**node_exporter** — экспортер Prometheus для метрик хоста, включая сетевые счётчики из `/sys/class/net/` и `/proc/net/`.

**Blackbox Exporter** — экспортер Prometheus для проверки внешних ресурсов: HTTP/HTTPS, TCP, ICMP (ping), DNS. Работает как "prober" — проверяет цели со стороны Prometheus.

**USE методика (Utilization, Saturation, Errors)** — методология мониторинга ресурсов. Для сети: Utilization (загрузка интерфейса), Saturation (очереди/drops), Errors (ошибки на NIC/стеке).

## Основные концепции

### Архитектура сетевого мониторинга

```
                    ┌──────────────────┐
                    │    Prometheus     │
                    │   (scrape周期)    │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│ node_exporter │ │ node_exporter │ │ Blackbox Exporter │
│   :9100       │ │   :9100       │ │   :9115           │
│  (localhost)  │ │  (remote)     │ │ (prober)          │
└──────────────┘ └──────────────┘ └────────┬─────────┘
                                           │
                    ┌──────────────────────┼──────────────────────┐
                    │                      │                      │
                    ▼                      ▼                      ▼
               HTTP/HTTPS              TCP/ICMP                  DNS
            (внешний сайт)         (хост:порт)             (nslookup)
```

### Ключевые сетевые метрики node_exporter

| Метрика | Описание | USE-уровень |
|:---|:---|:---|
| `node_network_speed_bytes` | Скорость линка (bps) | Utilization |
| `node_network_receive_bytes_total` | Получено байт (RX) | Utilization |
| `node_network_transmit_bytes_total` | Отправлено байт (TX) | Utilization |
| `node_network_receive_errs_total` | RX ошибки | Errors |
| `node_network_transmit_errs_total` | TX ошибки | Errors |
| `node_network_receive_drop_total` | RX дропы | Saturation |
| `node_network_transmit_drop_total` | TX дропы | Saturation |
| `node_network_up` | Состояние линка (0/1) | Errors |
| `node_network_receive_packets_total` | Получено пакетов | Utilization |
| `node_network_transmit_packets_total` | Отправлено пакетов | Utilization |
| `node_netstat_Tcp_CurrEstab` | Активные TCP-сессии | Utilization |
| `node_netstat_Tcp_RetransSegs` | TCP-ретрансмиссии | Errors |
| `node_sockstat_TCP_tw` | TIME-WAIT сокеты | Saturation |
| `node_nf_conntrack_entries` | Conntrack записи | Saturation |

## Практические сценарии

### 1. Быстрая проверка сетевых метрик через API

```bash
# Проверка доступности node_exporter
curl -s http://localhost:9100/metrics | grep -E "^node_network_" | head -20

# Запрос через Prometheus API (Instant Query)
curl -s 'http://prometheus:9090/api/v1/query?query=rate(node_network_receive_bytes_total{device="eth0"}[5m]) * 8'

# Запрос через Prometheus API (Range Query — для графиков)
curl -s 'http://prometheus:9090/api/v1/query_range?query=rate(node_network_receive_bytes_total{device="eth0"}[5m]) * 8&start=2025-09-16T00:00:00Z&end=2025-09-16T12:00:00Z&step=300'

# Проверка Blackbox Exporter
curl -s 'http://blackbox:9115/probe?target=google.com:443&module=tcp_connect' | grep probe_success
# → probe_success 1  ← успех

curl -s 'http://blackbox:9115/probe?target=google.com&module=http_2xx' | grep probe_duration_seconds
# → probe_duration_seconds 0.123  ← задержка ответа
```

### 2. PromQL запросы для диагностики

```bash
# Загрузка интерфейса (% от скорости линка)
# rate(node_network_receive_bytes_total{device="eth0"}[5m]) * 8 / node_network_speed_bytes{device="eth0"} * 100

# Рост ошибок NIC
# rate(node_network_receive_errs_total{device="eth0"}[5m]) > 0

# Рост дропов
# rate(node_network_receive_drop_total{device="eth0"}[5m]) > 0

# TCP-ретрансмиссии в секунду
# rate(node_netstat_Tcp_RetransSegs[5m])

# Conntrack заполнен > 80%
# node_nf_conntrack_entries / node_nf_conntrack_entries_limit > 0.8

# TIME-WAIT сокеты > порога
# node_sockstat_TCP_tw > 10000

# Активные TCP-сессии
# node_netstat_Tcp_CurrEstab

# Скорость RX в Mbit/s
# rate(node_network_receive_bytes_total{device="eth0"}[5m]) * 8 / 1024 / 1024
```

### 3. Alert rules для сети

```yaml
groups:
  - name: network_alerts
    rules:
      # NIC ошибки
      - alert: NICReceiveErrors
        expr: rate(node_network_receive_errs_total[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "NIC errors on {{ $labels.instance }}:{{ $labels.device }}"

      # NIC дропы
      - alert: NICReceiveDrops
        expr: rate(node_network_receive_drop_total[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "NIC drops on {{ $labels.instance }}:{{ $labels.device }}"

      # Link down
      - alert: NICLinkDown
        expr: node_network_up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Link down on {{ $labels.instance }}:{{ $labels.device }}"

      # Conntrack table full
      - alert: ConntrackTableAlmostFull
        expr: node_nf_conntrack_entries / node_nf_conntrack_entries_limit > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Conntrack table > 80% full on {{ $labels.instance }}"

      # TCP ретрансмиссии
      - alert: TCPRetransmissionsHigh
        expr: rate(node_netstat_Tcp_RetransSegs[5m]) > 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High TCP retransmissions on {{ $labels.instance }}"

      # Listen queue overflow
      - alert: ListenQueueOverflow
        expr: rate(node_netstat_TcpExt_ListenOverflows[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Listen queue overflow on {{ $labels.instance }}"

      # Blackbox probe failed
      - alert: BlackboxProbeFailed
        expr: probe_success == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Probe failed for {{ $labels.instance }}"

      # High latency
      - alert: HighNetworkLatency
        expr: probe_duration_seconds{phase="resolve"} > 0.5 or probe_duration_seconds{phase="connect"} > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High network latency to {{ $labels.instance }}"
```

### 4. Конфигурация Blackbox Exporter

```yaml
# blackbox.yml
modules:
  tcp_connect:
    prober: tcp
    timeout: 5s
    tcp:
      preferred_ip_protocol: ip4

  http_2xx:
    prober: http
    timeout: 10s
    http:
      valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
      valid_status_codes: [200]
      method: GET
      follow_redirects: true
      preferred_ip_protocol: ip4

  icmp_ping:
    prober: icmp
    timeout: 5s
    icmp:
      preferred_ip_protocol: ip4

  dns_resolve:
    prober: dns
    timeout: 5s
    dns:
      query_name: "example.com"
      query_type: "A"
      preferred_ip_protocol: ip4

# prometheus.yml scrape config
scrape_configs:
  - job_name: 'blackbox_tcp'
    metrics_path: /probe
    params:
      module: [tcp_connect]
    static_configs:
      - targets:
          - 10.0.1.1:443
          - 10.0.2.1:443
          - 8.8.8.8:53
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox:9115

  - job_name: 'blackbox_http'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
          - https://google.com
          - https://github.com
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox:9115

  - job_name: 'blackbox_icmp'
    metrics_path: /probe
    params:
      module: [icmp_ping]
    static_configs:
      - targets:
          - 8.8.8.8
          - 1.1.1.1
          - 192.168.1.1
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox:9115
```

### 5. Диагностика через Grafana Dashboard

```bash
# Дашборд для диагностики сети (импорт в Grafana):
# ID 1860 — Node Exporter Full (включает сетевые панели)
# ID 14666 — Network Traffic Dashboard
# ID 11941 — Linux Network Statistics

# Ключевые панели для SRE:
# 1. Network Traffic (RX/TX в битах)
# 2. Network Errors (NIC ошибки)
# 3. Network Drops (дропы)
# 4. TCP Retransmissions
# 5. TCP Connections (ESTABLISHED, TIME-WAIT)
# 6. Conntrack Usage
```

### 6. Проверка метрик вручную (без Grafana)

```bash
# Все сетевые метрики хоста
curl -s http://localhost:9100/metrics | grep -E "^node_network_" | \
  awk '{printf "%-45s %s\n", $1, $2}'

# Только не-нулевые ошибки
curl -s http://localhost:9100/metrics | grep -E "errs|drops" | \
  awk '$2 > 0 {printf "%-45s %s\n", $1, $2}'

# Текущая скорость RX/TX
curl -s http://localhost:9100/metrics | grep "node_network_receive_bytes_total" | \
  head -5
```

## Дополнительная информация

### Оптимизации для production

```yaml
# Рекомендуемый scrape interval для сети
scrape_configs:
  - job_name: 'node'
    scrape_interval: 15s      # стандарт
    scrape_timeout: 10s

  - job_name: 'blackbox'
    scrape_interval: 30s      # внешние проверки
    scrape_timeout: 15s

# Для высокочастотных метрик (5s)
  - job_name: 'node_network_fast'
    scrape_interval: 5s
    metric_relabel_configs:
      - source_labels: [__name__]
        regex: 'node_network_.*'
        action: keep
```

### Связанные инструменты

- **[Prometheus](../../Monitoring/Prometheus/)** — полная документация Prometheus.
- **[node_exporter](../../Monitoring/Prometheus/node_exporter/)** — метрики хоста (SSoT).
- **[Blackbox Exporter](../../Monitoring/Prometheus/BlackboxExporter/blackbox_exporter.md)** — внешний мониторинг.
- **[Alert rules](../../Monitoring/Prometheus/Alerting/alerting_rules_with_alertmanager.md)** — настройка алертов.
- **[NIC hardware diagnostics](./nic_hardware_diagnostics.md)** — аппаратная диагностика NIC.
- **[conntrack diagnostics](./conntrack_diagnostics.md)** — диагностика conntrack.
- **[nstat diagnostics](./nstat_diagnostics.md)** — SNMP-счётчики ядра.
