# Мониторинг и наблюдаемость GRE-туннелей

## Определения и назначение

**Мониторинг GRE** — комплексный процесс сбора, агрегации и анализа метрик состояния, производительности и безопасности GRE-туннелей в реальном времени. Включает обнаружение отказов (Fault Detection), измерение качества (Performance Monitoring) и управление алертами (Alerting).

**Зачем мониторить GRE в продакшене:**

| Проблема | Последствие | Что отслеживать |
|----------|-------------|-----------------|
| Туннель DOWN | Потеря связности между сайтами | `ifOperStatus`, BFD status |
| Packet loss | Деградация приложений | `ifInErrors`, `ifOutErrors` |
| MTU black hole | Зависание TCP-соединений | MSS, фрагментация |
| Jitter/latency | Проблемы с VOIP/video | RTT,抖动 |
| Неавторизованный доступ | Утечка данных | Traffic anomalies, NetFlow |

---

## Теоретический блок

### Метрики для мониторинга GRE

| Уровень | Метрика | Источник | Порог алерта |
|---------|---------|----------|--------------|
| **L2 (Link)** | `ifOperStatus` (1=UP, 2=DOWN) | SNMP IF-MIB | DOWN |
| **L2 (Link)** | `ifInErrors`, `ifOutErrors` | SNMP IF-MIB | >0 за интервал |
| **L2 (Link)** | `ifInDiscards`, `ifOutDiscards` | SNMP IF-MIB | Рост >5% |
| **L3 (IP)** | `ipForwarding` | SNMP IP-MIB | 0 (disabled) |
| **L3 (IP)** | Packet loss через GRE | iperf3/tcpdump | >0.1% |
| **L3 (IP)** | RTT через туннель | fping/icmp | >50ms |
| **Application** | OSPF/BGP neighbor state | FRRouting | State change |
| **Application** | BFD session state | FRRouting | DOWN |
| **System** | CPU load на инкапсуляции | node_exporter | >80% |
| **System** | Kernel drops (`ip_gre`) | `/proc/net/snmp` | >0 |

### Архитектура мониторинга

```
┌─────────────────────────────────────────────────┐
│                  Grafana Dashboard               │
│    (туннели, packet loss, latency, uptime)       │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│                  Prometheus                      │
│    (scrape, alert rules, recording rules)        │
└───┬──────────┬──────────┬──────────┬────────────┘
    │          │          │          │
┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───┐
│ node_ │ │ text  │ │ SNMP  │ │ FRR   │
│export │ │ file  │ │Export │ │Export │
│  er   │ │collec.│ │  er   │ │  er   │
└───────┘ └───────┘ └───────┘ └───────┘
    │          │          │          │
    ▼          ▼          ▼          ▼
 /sys/class /proc/net/  SNMP MIB  vtysh
 /net/      snmp        (IF-MIB)  (FRR)
```

### Источники метрик

| Источник | Что даёт | Как использовать |
|----------|----------|------------------|
| **sysfs** (`/sys/class/net/gre0/`) | Статистика интерфейса | `cat statistics/rx_errors` |
| **procfs** (`/proc/net/snmp`) | Счётчики протоколов | Парсинг для custom exporter |
| **ip -s link show** | Детальная статистика | Скрипт для textfile collector |
| **SNMP** (IF-MIB, IP-MIB) | Стандартные сетевые метрики | SNMP Exporter + Prometheus |
| **FRRouting** (`vtysh`) | OSPF/BGP/BFD state | FRR Exporter |
| **tcpdump/ipstat** | Deep packet analysis | Отладка, не для мониторинга |

---

## Практическая реализация

### Сбор метрик через textfile collector (node_exporter)

Самый простой способ — кастомный скрипт + `node_exporter --collector.textfile`.

**Скрипт сбора метрик** (`/usr/local/bin/gre_metrics.sh`):

```bash
#!/bin/bash
OUTPUT_DIR="/var/lib/node_exporter/textfile_collector"
OUTPUT_FILE="${OUTPUT_DIR}/gre_metrics.prom"

# Список GRE-интерфейсов для мониторинга
GRE_INTERFACES="gre0 gre1 mgre0"

# Очистка предыдущих данных
> "${OUTPUT_FILE}.tmp"

for IFACE in $GRE_INTERFACES; do
    if [ ! -d "/sys/class/net/${IFACE}" ]; then
        continue
    fi

    # Проверка состояния интерфейса (1=UP, 0=DOWN)
    OPER_STATE=$(cat /sys/class/net/${IFACE}/operstate 2>/dev/null)
    if [ "$OPER_STATE" = "up" ]; then
        OPER_STATUS=1
    else
        OPER_STATUS=0
    fi

    # Статистика
    RX_ERRORS=$(cat /sys/class/net/${IFACE}/statistics/rx_errors 2>/dev/null || echo 0)
    TX_ERRORS=$(cat /sys/class/net/${IFACE}/statistics/tx_errors 2>/dev/null || echo 0)
    RX_DISCARDS=$(cat /sys/class/net/${IFACE}/statistics/rx_dropped 2>/dev/null || echo 0)
    TX_DISCARDS=$(cat /sys/class/net/${IFACE}/statistics/tx_dropped 2>/dev/null || echo 0)
    RX_BYTES=$(cat /sys/class/net/${IFACE}/statistics/rx_bytes 2>/dev/null || echo 0)
    TX_BYTES=$(cat /sys/class/net/${IFACE}/statistics/tx_bytes 2>/dev/null || echo 0)
    RX_PACKETS=$(cat /sys/class/net/${IFACE}/statistics/rx_packets 2>/dev/null || echo 0)
    TX_PACKETS=$(cat /sys/class/net/${IFACE}/statistics/tx_packets 2>/dev/null || echo 0)

    # MTU
    MTU=$(cat /sys/class/net/${IFACE}/mtu 2>/dev/null || echo 0)

    cat >> "${OUTPUT_FILE}.tmp" <<EOF
# HELP gre_interface_up GRE tunnel interface operational status
# TYPE gre_interface_up gauge
gre_interface_up{interface="${IFACE}"} ${OPER_STATUS}

# HELP gre_interface_errors_total Total errors on GRE interface
# TYPE gre_interface_errors_total counter
gre_interface_errors_total{interface="${IFACE}",direction="rx"} ${RX_ERRORS}
gre_interface_errors_total{interface="${IFACE}",direction="tx"} ${TX_ERRORS}

# HELP gre_interface_discards_total Total discards on GRE interface
# TYPE gre_interface_discards_total counter
gre_interface_discards_total{interface="${IFACE}",direction="rx"} ${RX_DISCARDS}
gre_interface_discards_total{interface="${IFACE}",direction="tx"} ${TX_DISCARDS}

# HELP gre_interface_bytes_total Total bytes on GRE interface
# TYPE gre_interface_bytes_total counter
gre_interface_bytes_total{interface="${IFACE}",direction="rx"} ${RX_BYTES}
gre_interface_bytes_total{interface="${IFACE}",direction="tx"} ${TX_BYTES}

# HELP gre_interface_packets_total Total packets on GRE interface
# TYPE gre_interface_packets_total counter
gre_interface_packets_total{interface="${IFACE}",direction="rx"} ${RX_PACKETS}
gre_interface_packets_total{interface="${IFACE}",direction="tx"} ${TX_PACKETS}

# HELP gre_interface_mtu MTU of GRE interface
# TYPE gre_interface_mtu gauge
gre_interface_mtu{interface="${IFACE}"} ${MTU}
EOF
done

mv "${OUTPUT_FILE}.tmp" "${OUTPUT_FILE}"
```

**Установка:**
```bash
# Создание директории
sudo mkdir -p /var/lib/node_exporter/textfile_collector

# Установка скрипта
sudo install -m 755 gre_metrics.sh /usr/local/bin/gre_metrics.sh

# Cron (каждые 30 секунд)
echo '* * * * * root /usr/local/bin/gre_metrics.sh' | sudo tee /etc/cron.d/gre_metrics

# Проверка
/usr/local/bin/gre_metrics.sh
cat /var/lib/node_exporter/textfile_collector/gre_metrics.prom
```

**Запуск node_exporter с textfile collector:**
```bash
node_exporter --collector.textfile.directory=/var/lib/node_exporter/textfile_collector
```

### Алерт-правила Prometheus

Файл `gre_alerts.yml`:

```yaml
groups:
  - name: gre_tunnel_alerts
    rules:
      # Туннель DOWN
      - alert: GREInterfaceDown
        expr: gre_interface_up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "GRE tunnel {{ $labels.interface }} is DOWN"
          description: "GRE-туннель {{ $labels.interface }} недоступен более 1 минуты."

      # Packet loss
      - alert: GREPacketLoss
        expr: |
          rate(gre_interface_errors_total[5m]) > 0
          or rate(gre_interface_discards_total[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "GRE {{ $labels.interface }}: packet loss detected"
          description: "Обнаружены ошибки/дропы на GRE {{ $labels.interface }} более 5 минут."

      # Высокий CPU на инкапсуляции
      - alert: GREEncapsulationHighCPU
        expr: |
          100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High CPU on {{ $labels.instance }} may affect GRE performance"
          description: "CPU > 80% на {{ $labels.instance }}. Возможна деградация GRE-туннелей."

      # OSPF/BGP neighbor down (через FRR Exporter)
      - alert: GREOSPFNeighborDown
        expr: ospf_neighbor_state != 2
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "OSPF neighbor {{ $labels.neighbor }} on {{ $labels.interface }} is DOWN"
          description: "OSPF-сосед {{ $labels.neighbor }} недоступен через GRE."

      # BFD session down
      - alert: GREBFDDown
        expr: bfd_session_state != 1
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "BFD session DOWN on {{ $labels.interface }}"
          description: "BFD-сессия через GRE разорвана. Туннель может быть недоступен."

      #Throughput anomaly
      - alert: GREThroughputAnomaly
        expr: |
          rate(gre_interface_bytes_total{direction="rx"}[5m]) > 100 * 1024 * 1024
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High RX throughput on {{ $labels.interface }}"
          description: "RX throughput > 100 MB/s на {{ $labels.interface }}. Проверьте аномалии."
```

**Подключение к Prometheus:**
```yaml
# prometheus.yml
rule_files:
  - /etc/prometheus/rules/gre_alerts.yml
```

### SNMP-мониторинг

Для опроса коммутаторов/роутеров с GRE-туннелями:

**Настройка SNMP на Linux:**
```bash
# Установка Net-SNMP
sudo apt install snmpd snmp

# Конфигурация (/etc/snmp/snmpd.conf)
# rocommunity public 127.0.0.1
# sysLocation DataCenter
# sysContact admin@example.com

sudo systemctl enable snmpd
sudo systemctl start snmpd

# Проверка
snmpwalk -v2c -c public localhost IF-MIB::ifOperStatus
```

**Настройка SNMP Exporter для Prometheus:**
```yaml
# snmp_exporter snmp.yml (модуль gre)
gre:
  walk:
    - ifDescr
    - ifOperStatus
    - ifInErrors
    - ifOutErrors
    - ifInDiscards
    - ifOutDiscards
    - ifSpeed
    - ifHCInOctets
    - ifHCOutOctets
  metrics:
    - name: ifOperStatus
      oid: 1.3.6.1.2.1.2.2.1.8
      type: gauge
      lookups:
        - labels: [ifIndex]
          labelname: ifIndex
          oid: 1.3.6.1.2.1.2.2.1.1
    - name: ifInErrors
      oid: 1.3.6.1.2.1.2.2.1.14
      type: counter
    - name: ifOutErrors
      oid: 1.3.6.1.2.1.2.2.1.20
      type: counter
```

**Prometheus target:**
```yaml
scrape_configs:
  - job_name: 'snmp_gre'
    static_configs:
      - targets:
          - 198.51.100.1
          - 203.0.113.2
    metrics_path: /snmp
    params:
      module: [gre]
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9116
```

### NetFlow/IPFIX для анализа трафика

Для глубокого анализа трафика через GRE:

**Настройка NetFlow на Linux (softflowd):**
```bash
# Установка
sudo apt install softflowd

# Запуск на GRE-интерфейсе
sudo softflowd -i gre0 -n 127.0.0.1:9995 -t active_timeout=60

# Или через nftables (nflog)
nft add rule ip raw prerouting iifname "gre0" flow alert
```

**Анализ через nfdump:**
```bash
# Установка
sudo apt install nfdump

# Просмотр потоков
nfdump -r /var/log/nfsen/nfcapd.* -T proto

# Топ-10 по объёму трафика через GRE
nfdump -r /var/log/nfsen/nfcapd.* -i gre0 -s proto/bytes
```

**Метрики NetFlow для Prometheus (custom exporter):**
```python
#!/usr/bin/env python3
"""Простой NetFlow→Prometheus exporter для GRE."""
from prometheus_client import start_http_server, Counter, Gauge
import socket, struct

FLOW_RX = Counter('gre_netflow_bytes_total', 'NetFlow bytes', ['src_ip', 'dst_ip', 'proto'])
FLOWS = Counter('gre_netflow_flows_total', 'NetFlow flow count', ['src_ip', 'dst_ip'])

def parse_netflow(data):
    header = struct.unpack('!HHIII', data[:20])
    flows = []
    offset = 20
    for _ in range(header[2]):
        flow = struct.unpack('!IIIHHIIIIHHBBBB', data[offset:offset+48])
        flows.append({
            'src': socket.inet_ntoa(struct.pack('!I', flow[0])),
            'dst': socket.inet_ntoa(struct.pack('!I', flow[1])),
            'bytes': flow[9],
            'proto': flow[15],
        })
        offset += 48
    return flows

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('0.0.0.0', 9995))
start_http_server(9101)

while True:
    data, _ = sock.recvfrom(65535)
    for flow in parse_netflow(data):
        FLOW_RX.labels(flow['src'], flow['dst'], str(flow['proto'])).inc(flow['bytes'])
        FLOWS.labels(flow['src'], flow['dst']).inc()
```

### Grafana-дашборд

**Основные панели:**

| Панель | Тип | Метрика | Визуализация |
|--------|-----|---------|--------------|
| **Tunnel Status** | Stat | `gre_interface_up` | Gauge (UP/DOWN) |
| **Throughput** | Time Series | `rate(gre_interface_bytes_total[5m])` | Line (RX/TX) |
| **Packet Loss** | Time Series | `rate(gre_interface_errors_total[5m])` | Line |
| **Discards** | Time Series | `rate(gre_interface_discards_total[5m])` | Bar gauge |
| **MTU** | Stat | `gre_interface_mtu` | Stat |
| **CPU Impact** | Gauge | `node_cpu_seconds_total` | Gauge |
| **OSPF State** | Table | `ospf_neighbor_state` | Table |
| **BFD State** | Stat | `bfd_session_state` | Stat |

**Импорт дашборда:**
- ID 11002 (Node Exporter Full) — адаптировать фильтры для `gre*`
- ID 13820 (SNMP Interface) — для опроса коммутаторов с GRE

### Простой скрипт мониторинга (без Prometheus)

Для минимального мониторинга без стека:

```bash
#!/bin/bash
# /usr/local/bin/gre_healthcheck.sh
REMOTE_IP="203.0.113.2"
IFACE="gre0"
LOG="/var/log/gre_healthcheck.log"
ALERT_EMAIL="admin@example.com"

# Проверка 1: Интерфейс UP?
if ! cat /sys/class/net/${IFACE}/operstate | grep -q "up"; then
    echo "$(date) CRITICAL: ${IFACE} is DOWN" >> ${LOG}
    echo "GRE tunnel ${IFACE} is DOWN on $(hostname)" | mail -s "GRE ALERT" ${ALERT_EMAIL}
    exit 1
fi

# Проверка 2: ICMP через туннель
if ! ping -c 3 -W 2 -I ${IFACE} ${REMOTE_IP} > /dev/null 2>&1; then
    echo "$(date) WARNING: No ICMP through ${IFACE} to ${REMOTE_IP}" >> ${LOG}
    exit 1
fi

# Проверка 3: Packet errors
ERRORS=$(cat /sys/class/net/${IFACE}/statistics/rx_errors)
TX_ERRORS=$(cat /sys/class/net/${IFACE}/statistics/tx_errors)
if [ "$ERRORS" -gt 0 ] || [ "$TX_ERRORS" -gt 0 ]; then
    echo "$(date) WARNING: ${IFACE} errors rx=${ERRORS} tx=${TX_ERRORS}" >> ${LOG}
fi

# Проверка 4: MTU test
if ! ping -M do -s 1372 -c 1 -W 2 ${REMOTE_IP} > /dev/null 2>&1; then
    echo "$(date) WARNING: MTU black hole detected on ${IFACE}" >> ${LOG}
fi

echo "$(date) OK: ${IFACE} healthy" >> ${LOG}
```

**Cron:**
```bash
# Каждые 5 минут
*/5 * * * * root /usr/local/bin/gre_healthcheck.sh
```

---

## Дополнительная информация

### Связанные документы

*   [Протокол GRE](./gre.md) — архитектура, заголовки, диагностика.
*   [GRE: практические сценарии](./gre_practical_scenarios.md) — настройка, troubleshooting.
*   [GRE с IPsec](./gre_ipsec_integration.md) — защищённые туннели.
*   [OSPF (FRRouting)](../../Protocols/ospf.md) — динамическая маршрутизация через GRE.
*   [Prometheus](../../Prometheus/overview.md) — настройка стека мониторинга.
