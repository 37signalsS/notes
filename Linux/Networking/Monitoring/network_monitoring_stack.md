# Network Monitoring Stack (Prometheus + Grafana)

## Определения

**Network Monitoring Stack** — комплект инструментов для сбора, хранения, визуализации и алертинга метрик сетевой инфраструктуры. В продакшене стандартным решением является связка **Prometheus** (сбор и хранение time-series) + **Grafana** (визуализация) + **node_exporter** (агент на хосте) + **Blackbox Exporter** (внешние проверки).

**node_exporter** — агент Prometheus, собирающий системные метрики Linux, включая сетевые: `node_network_*` (трафик, ошибки, пакеты), `node_netstat_*` (TCP/UDP статистика), `node_nf_conntrack_*` (conntrack).

**Blackbox Exporter** — компонент Prometheus для проверки доступности внешних эндпоинтов по протоколам HTTP, HTTPS, TCP, ICMP, DNS. Работает "извне" — проверяет, как клиент видит сервис.

**SNMP (Simple Network Management Protocol)** — протокол мониторинга сетевого оборудования (коммутаторы, маршрутизаторы, IP-UPS). Используется когда node_exporter недоступен (несерверные устройства).

**NetFlow/sFlow** — протоколы анализа потока трафика. Позволяют увидеть "кто с кем общается", объёмы трафика по приложениям, топ-потребителей.

## Теоретический блок

### Архитектура стека мониторинга

```
┌─────────────────────────────────────────────────────────┐
│                    Grafana (Dashboard)                   │
│              Визуализация, алерты, отчёты                │
└────────────────────────┬────────────────────────────────┘
                         │ query
┌────────────────────────▼────────────────────────────────┐
│                   Prometheus (TSDB)                      │
│            Сбор, хранение, AlertManager                  │
└───┬──────────┬──────────┬──────────┬────────────────────┘
    │          │          │          │
    ▼          ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────────┐
│node_   │ │node_   │ │Blackbox│ │  SNMP      │
│exporter│ │exporter│ │Exporter│ │  Exporter  │
│(хост A)│ │(хост B)│ │(внешн.)│ │(коммутатор)│
└────────┘ └────────┘ └────────┘ └────────────┘
```

### Ключевые сетевые метрики node_exporter

| Метрика | Описание | Единицы | Источник |
|:---|:---|:---|:---|
| `node_network_receive_bytes_total` | Входящий трафик | bytes | `/proc/net/dev` |
| `node_network_transmit_bytes_total` | Исходящий трафик | bytes | `/proc/net/dev` |
| `node_network_receive_errs_total` | Ошибки приёма | count | `/proc/net/dev` |
| `node_network_transmit_errs_total` | Ошибки передачи | count | `/proc/net/dev` |
| `node_network_receive_drop_total` | Входящие дропы | count | `/proc/net/dev` |
| `node_network_transmit_drop_total` | Исходящие дропы | count | `/proc/net/dev` |
| `node_network_receive_packets_total` | Входящие пакеты | count | `/proc/net/dev` |
| `node_network_transmit_packets_total` | Исходящие пакеты | count | `/proc/net/dev` |
| `node_network_carrier_changes_total` | Смены состояния линка | count | `/sys/class/net/*/operstate` |
| `node_netstat_Tcp_RetransSegs` | TCP-ретрансмиссии | count | `/proc/net/netstat` |
| `node_netstat_Tcp_InErrs` | TCP-входящие ошибки | count | `/proc/net/netstat` |
| `node_netstat_Udp_InErrors` | UDP-входящие ошибки | count | `/proc/net/netstat` |
| `node_nf_conntrack_entries` | Текущее использование conntrack | count | `/proc/sys/net/netfilter/nf_conntrack_count` |
| `node_nf_conntrack_max` | Максимум conntrack | count | `/proc/sys/net/netfilter/nf_conntrack_max` |

### Ключевые метрики Blackbox Exporter

| Метрика | Описание | Алерт |
|:---|:---|:---|
| `probe_success` | 0/1 — доступность | `probe_success == 0` |
| `probe_duration_seconds` | Латентность проверки | `p99 > 2s` |
| `probe_http_duration_seconds` | HTTP-латентность | `p99 > 3s` |
| `probe_http_ssl_verify` | Валидность SSL | `probe_http_ssl_verify == 0` |
| `probe_dns_lookup_time_seconds` | DNS-резолвинг | `> 1s` |
| `probe_icmp_duration_seconds` | ICMP-латентность | `> 0.5s` |

### Методология: USE vs RED vs Four Golden Signals

| Методология | Фокус | Метрики |
|:---|:---|:---|
| **USE (Utilization, Saturation, Errors)** | Ресурсы (CPU, RAM, сеть) | Утилизация интерфейса, очередь дропов, ошибки |
| **RED (Rate, Errors, Duration)** | Сервисы | QPS, ошибки, latency |
| **Four Golden Signals** | SLO-ориентированный | Latency, Traffic, Errors, Saturation |

**Для сети USE — наиболее применим:**
- **U**tilization: `%` утилизации полосы пропускания интерфейса
- **S**aturation: `node_network_transmit_drop_total` (дропы = NIC не успевает)
- **E**rrors: `node_network_receive_errs_total`, TCP retransmits

## Практические сценарии

### Сценарий 1: Установка node_exporter на bare-metal сервере

```bash
VERSION="1.8.2"
wget https://github.com/prometheus/node_exporter/releases/download/v${VERSION}/node_exporter-${VERSION}.linux-amd64.tar.gz
tar xzf node_exporter-${VERSION}.linux-amd64.tar.gz
sudo cp node_exporter-${VERSION}.linux-amd64/node_exporter /usr/local/bin/

# Systemd unit
cat > /etc/systemd/system/node_exporter.service <<'EOF'
[Unit]
Description=Prometheus Node Exporter
After=network-online.target

[Service]
Type=simple
User=node_exporter
ExecStart=/usr/local/bin/node_exporter \
  --collector.textfile.directory=/var/lib/node_exporter/textfile_metrics \
  --web.listen-address=:9100
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo useradd --no-create-home --shell /bin/false node_exporter
sudo mkdir -p /var/lib/node_exporter/textfile_metrics
sudo chown node_exporter:node_exporter /var/lib/node_exporter/textfile_metrics
sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter

# Проверка
curl -s http://localhost:9100/metrics | grep node_network_receive_bytes_total | head -5
```

### Сценарий 2: Настройка Blackbox Exporter для проверки сервисов

```bash
# Установка
VERSION="0.25.0"
wget https://github.com/prometheus/blackbox_exporter/releases/download/v${VERSION}/blackbox_exporter-${VERSION}.linux-amd64.tar.gz
tar xzf blackbox_exporter-${VERSION}.linux-amd64.tar.gz
sudo cp blackbox_exporter-${VERSION}.linux-amd64/blackbox_exporter /usr/local/bin/

# Конфигурация /etc/blackbox_exporter/blackbox.yml
cat > /etc/blackbox_exporter/blackbox.yml <<'EOF'
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
      valid_status_codes: [200]
      method: GET
      follow_redirects: true
      preferred_ip_protocol: "ip4"

  tcp_connect:
    prober: tcp
    timeout: 5s

  icmp:
    prober: icmp
    timeout: 5s

  dns_resolve:
    prober: dns
    timeout: 5s
    dns:
      query_name: "google.com"
      query_type: "A"
      valid_rcodes:
        - NOERROR
EOF

# Systemd unit
cat > /etc/systemd/system/blackbox_exporter.service <<'EOF'
[Unit]
Description=Prometheus Blackbox Exporter
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/blackbox_exporter \
  --config.file=/etc/blackbox_exporter/blackbox.yml
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now blackbox_exporter
```

### Сценарий 3: Конфигурация Prometheus для сбора сетевых метрик

```yaml
# /etc/prometheus/prometheus.yml

global:
  scrape_interval: 15s
  evaluation_interval: 15s

# Сбор метрик с хостов
scrape_configs:
  # node_exporter на всех серверах
  - job_name: 'node_exporter'
    static_configs:
      - targets:
          - '10.0.0.1:9100'  # web-серверы
          - '10.0.0.2:9100'
          - '10.0.0.3:9100'
          - '10.0.1.1:9100'  # БД серверы
          - '10.0.1.2:9100'
    relabel_configs:
      - source_labels: [__address__]
        regex: '(.*):\d+'
        target_label: instance

  # Blackbox Exporter — проверка внешних сервисов
  - job_name: 'blackbox_http'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
          - https://example.com
          - https://api.example.com/health
          - https://grafana.internal:3000
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9115  # Blackbox Exporter

  # Blackbox — TCP-проверка
  - job_name: 'blackbox_tcp'
    metrics_path: /probe
    params:
      module: [tcp_connect]
    static_configs:
      - targets:
          - 10.0.0.1:22    # SSH
          - 10.0.0.1:5432  # PostgreSQL
          - 10.0.0.2:3306  # MySQL
          - 10.0.0.3:6379  # Redis
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9115

  # Blackbox — ICMP (ping)
  - job_name: 'blackbox_icmp'
    metrics_path: /probe
    params:
      module: [icmp]
    static_configs:
      - targets:
          - 10.0.0.1
          - 10.0.0.2
          - 192.168.1.1    # Шлюз
          - 8.8.8.8        # DNS Google
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9115
```

### Сценарий 4: Правила алертинга для сети

```yaml
# /etc/prometheus/rules/network_alerts.yml

groups:
  - name: network_alerts
    rules:
      # Интерфейс упал
      - alert: NetworkInterfaceDown
        expr: node_network_up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Интерфейс {{ $labels.device }} на {{ $labels.instance }} упал"
          description: "Интерфейс неактивен более 2 минут"

      # Высокий % утилизации полосы пропускания
      - alert: HighBandwidthUtilization
        expr: |
          (
            rate(node_network_receive_bytes_total{device!~"lo|veth.*|docker.*|br-.*"}[5m])
            + rate(node_network_transmit_bytes_total{device!~"lo|veth.*|docker.*|br-.*"}[5m])
          ) / (node_network_speed_bytes{device!~"lo|veth.*|docker.*|br-.*"} > 0) * 100 > 80
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Высокая утилизация {{ $labels.device }} на {{ $labels.instance }}"
          description: "Утилизация {{ $value | printf \"%.1f\" }}% более 10 минут"

      # Дропы на интерфейсе
      - alert: NetworkInterfaceDrops
        expr: |
          rate(node_network_receive_drop_total{device!~"lo|veth.*"}[5m]) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Дропы на {{ $labels.device }} ({{ $labels.instance }})"
          description: "Более 100 дропов/сек на интерфейсе"

      # TCP-ретрансмиссии
      - alert: HighTcpRetransmissions
        expr: |
          rate(node_netstat_Tcp_RetransSegs[5m])
          / rate(node_netstat_Tcp_OutSegs[5m]) * 100 > 5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Высокий уровень TCP-ретрансмиссий на {{ $labels.instance }}"
          description: "Ретрансмиссии {{ $value | printf \"%.1f\" }}% — возможны проблемы с сетью"

      # Conntrack near limit
      - alert: ConntrackNearLimit
        expr: |
          node_nf_conntrack_entries / node_nf_conntrack_max * 100 > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Conntrack на {{ $labels.instance }} заполнен на {{ $value | printf \"%.0f\" }}%"
          description: "При превышении 100% новые соединения будут отброшены"

      # Conntrack table full
      - alert: ConntrackTableFull
        expr: |
          node_nf_conntrack_entries / node_nf_conntrack_max * 100 > 95
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "CRITICAL: Conntrack на {{ $labels.instance }} заполнен на {{ $value | printf \"%.0f\" }}%"
          description: "Немедленно увеличить nf_conntrack_max или оптимизировать таймауты"

      # Blackbox — сервис недоступен
      - alert: ServiceDown
        expr: probe_success == 0
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "Сервис {{ $labels.instance }} недоступен"
          description: "Blackbox-проверка не проходит более 3 минут"

      # Высокая латентность
      - alert: HighLatency
        expr: probe_duration_seconds > 2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Высокая латентность до {{ $labels.instance }}"
          description: "Латентность {{ $value | printf \"%.2f\" }}s более 10 минут"

      # Ошибки сетевых интерфейсов
      - alert: NetworkInterfaceErrors
        expr: |
          rate(node_network_receive_errs_total{device!~"lo|veth.*"}[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Ошибки на {{ $labels.device }} ({{ $labels.instance }})"
          description: "Более 10 ошибок приёма/сек"
```

### Сценарий 5: SNMP-мониторинг сетевого оборудования

```yaml
# Установка snmp_exporter
# https://github.com/prometheus/snmp_exporter

# /etc/prometheus/prometheus.yml — добавить:
scrape_configs:
  - job_name: 'snmp_switches'
    metrics_path: /snmp
    params:
      module: [if_mib]
    static_configs:
      - targets:
          - 192.168.1.10  # Cisco switch
          - 192.168.1.11  # Juniper switch
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9116  # snmp_exporter

# Конфигурация snmp_exporter — module if_mib
# Генерируется через snmp_exporter generator
```

### Сценарий 6: Быстрый поиск проблем с сетью через Grafana

**Типовые запросы (PromQL) для дашбордов:**

```promql
# Утилизация интерфейса (%)
100 - (
  rate(node_network_receive_bytes_total{device="eth0"}[5m]) * 8
  / node_network_speed_bytes{device="eth0"} * 100
)

# Входящий трафик в Mbps
rate(node_network_receive_bytes_total{device="eth0"}[5m]) * 8 / 1e6

# Дропы в секунду
rate(node_network_receive_drop_total{device="eth0"}[5m])

# TCP retransmit ratio
rate(node_netstat_Tcp_RetransSegs[5m]) / rate(node_netstat_Tcp_OutSegs[5m]) * 100

# Conntrack utilization (%)
node_nf_conntrack_entries / node_nf_conntrack_max * 100

# Blackbox HTTP success rate
avg_over_time(probe_success{job="blackbox_http"}[5m])

# Blackbox latency p99
histogram_quantile(0.99, rate(probe_http_duration_seconds_bucket[5m]))
```

## Диагностика и устранение неполадок

### Типичные проблемы мониторинга

| Проблема | Причина | Решение |
|:---|:---|:---|
| node_exporter не показывает сетевые метрики | Интерфейс `lo` или `veth` в фильтре | Исключите виртуальные: `device!~"lo\|veth.*"` |
| SNMP exporter не подключается к коммутатору | SNMPv2 community или ACL | Проверьте `snmpwalk -v2c -c community 192.168.1.10` |
| Blackbox показывает `probe_success=0` | Firewall блокирует ICMP/TCP | Проверьте `iptables -L -n` на сервере с Blackbox |
| Prometheus не скрапивает таргет | Network connectivity | `curl http://target:9100/metrics` вручную |
| Высокий CPU на Prometheus | Много таргетов, короткий interval | Увеличьте `scrape_interval`, используйте relabeling для фильтрации |
| conntrack метрики отсутствуют | Модуль `nf_conntrack` не загружен | `lsmod | grep nf_conntrack; modprobe nf_conntrack` |

### Рекомендуемые дашборды Grafana

| Дашборд | ID | Описание | Источник метрик |
|:---|:---|:---|:---|
| **Node Exporter Full** | 1860 | Системные метрики включая сеть | node_exporter |
| **Node Exporter for Prometheus** | 11074 | Упрощённый вариант | node_exporter |
| **Blackbox Exporter** | 7587 | Мониторинг внешних сервисов | blackbox_exporter |
| **SNMP Exporter** | 14511 | Мониторинг сетевого оборудования | snmp_exporter |
| **Linux Network Stack** | 12900 | TCP/UDP, conntrack, ошибки ядра | node_exporter |
| **Conntrack Dashboard** | 14724 | Мониторинг таблицы conntrack | node_exporter |
| **TCP Retransmissions** | 14503 | TCP-ретрансмиссии и ошибки | node_exporter |

**Установка дашбордов:**
```bash
# Импорт через Grafana API
curl -X POST http://grafana:3000/api/dashboards/import \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  -d '{
    "dashboard": { "id": 1860 },
    "overwrite": true,
    "inputs": [{ "name": "DS_PROMETHEUS", "type": "datasource", "pluginId": "prometheus", "value": "Prometheus" }]
  }'
```

**Настройка target groups для сетевого мониторинга:**

```yaml
# prometheus.yml — дополнительные job'ы
scrape_configs:
  # Базовые системные метрики
  - job_name: 'node'
    static_configs:
      - targets: ['10.0.0.1:9100', '10.0.0.2:9100']
    relabel_configs:
      - source_labels: [__address__]
        regex: '(.+):(\d+)'
        target_label: instance
        replacement: '$1'

  # Blackbox: HTTP probing
  - job_name: 'blackbox_http'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
        - https://example.com
        - https://api.example.com/healthz
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox-exporter:9115

  # Blackbox: TCP probing
  - job_name: 'blackbox_tcp'
    metrics_path: /probe
    params:
      module: [tcp_connect]
    static_configs:
      - targets:
        - 10.0.0.1:3306    # MySQL
        - 10.0.0.2:5432    # PostgreSQL
        - 10.0.0.3:6379    # Redis
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox-exporter:9115

  # SNMP: сетевое оборудование
  - job_name: 'snmp_switches'
    metrics_path: /snmp
    params:
      module: [if_mib]
      auth: [public_v2]
    static_configs:
      - targets:
        - 192.168.1.10    # Коммутатор
        - 192.168.1.11    # Маршрутизатор
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: snmp-exporter:9116
```

### Масштабирование мониторинга

- **До 500 таргетов:** один Prometheus instance.
- **500-5000 таргетов:** Federation или Remote Write в централизованный Prometheus.
- **Более 5000:** VictoriaMetrics, Thanos или Mimir для горизонтального масштабирования.

### См. также

- [Node Exporter — полное руководство](../../../Prometheus/Exporters/node_exporter.md) — все коллекторы и настройки
- [Blackbox Exporter — обзор](../../../Prometheus/Exporters/blackbox/blackbox_exporter_overview.md) — конфигурация модулей
- [nftables — мониторинг и алертинг](../Settings/tools/nftables/monitoring_and_alerting.md) — метрики файрвола
- [TCP Metrics для Prometheus](../Concepts/tcp_tuning/tcp_metrics_prometheus.md) — TCP-метрики через node_exporter
