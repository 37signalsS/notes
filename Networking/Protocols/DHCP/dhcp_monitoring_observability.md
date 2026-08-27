# Мониторинг и наблюдаемость DHCP

---

## Определения

**Наблюдаемость (Observability)** — способность внешнего наблюдателя оценить внутреннее состояние системы по её выходным данным: метрикам (metrics), логам (logs) и трассировкам (traces). Для DHCP ключевыми являются метрики и логи.

**Метрики DHCP** — числовые показатели, характеризующие работу DHCP-сервера: количество активных аренд, скорость выдачи адресов, время отклика, ошибки, заполненность пулов.

**Prometheus** — система мониторинга и алертинга, работающая по pull-модели (скрейпинг метрик по HTTP). Стандарт для cloud-native мониторинга.

**Grafana** — платформа визуализации метрик из различных источников (Prometheus, InfluxDB, Elasticsearch). Создаёт дашборды и графики.

**SIEM (Security Information and Event Management)** — система агрегации и корреляции событий безопасности. DHCP-события (Rogue DHCP, Snooping violations) являются источниками для SIEM.

---

## Основные концепции

### Ключевые метрики DHCP-сервера

| Метрика | Описание | Источник | Порог алерта |
| :--- | :--- | :--- | :--- |
| `dhcp_leases_active` | Количество активных аренд | Lease-файл / REST API | >80% пула |
| `dhcp_leases_total` | Общий размер пула | Конфигурация | - |
| `dhcp_pool_utilization` | Процент заполнения пула | Расчёт | >70% warning, >90% critical |
| `dhcp_discover_total` | Количество DISCOVER-запросов | Логи / snmptrap | Резкий рост |
| `dhcp_ack_total` | Количество выданных ACK | Логи | - |
| `dhcp_nak_total` | Количество отказов (NAK) | Логи | >5% от ACK |
| `dhcp_decline_total` | Количество DECLINE (конфликтов) | Логи | >0 |
| `dhcp_response_time_avg` | Среднее время отклика (ms) | tcpdump / API | >500ms |
| `dhcp_leases_abandoned` | Количество abandoned-адресов | Lease-файл | >0 |
| `dhcp_failover_state` | Состояние Failover/HA | Логи / API | != normal |

### Схема мониторинга

```
┌─────────────┐    ┌───────────────────┐    ┌─────────────────────┐
│  Kea DHCP   │───▶│  REST API (:8000) │───▶│  Prometheus         │
│  Server     │    │  (stat-get)       │    │  (скрейпинг /10s)   │
└─────────────┘    └───────────────────┘    └──────────┬──────────┘
                                                       │
┌─────────────┐    ┌───────────────────┐               ▼
│  ISC DHCP   │───▶│  dhcpd-leases-    │    ┌─────────────────────┐
│  Server     │    │  exporter (:9153) │    │  Grafana            │
└─────────────┘    └───────────────────┘    │  (Dashboard :3000)  │
                                            └──────────┬──────────┘
┌─────────────┐    ┌───────────────────┐               │
│  Switches   │───▶│  Syslog / SNMP   │               ▼
│  (Snooping) │    │  Trap            │    ┌─────────────────────┐
└─────────────┘    └───────────────────┘    │  Alertmanager       │
                                            │  (Webhook → Slack)  │
                                            └─────────────────────┘
```

---

## Практические сценарии

### Kea DHCP → Prometheus

Kea предоставляет нативный REST API. Для скрейпинга Prometheus используйте **kea-exporter** или кастомный exporter:

**kea-exporter (ГОТОВОЕ РЕШЕНИЕ):**

```bash
# Установка kea-exporter (Python)
pip install kea-exporter

# Конфигурация (/etc/kea-exporter.yaml):
cat > /etc/kea-exporter.yaml << 'EOF'
kea:
  host: localhost
  port: 8000
  timeout: 5
metrics:
  - subnet4
  - lease4
  - hook
EOF

# Запуск
kea-exporter --config /etc/kea-exporter.yaml --port 9153

# Prometheus job
# prometheus.yml:
# scrape_configs:
#   - job_name: 'kea-dhcp'
#     static_configs:
#       - targets: ['dhcp-server-1:9153', 'dhcp-server-2:9153']
#     scrape_interval: 15s
```

**Кастомный скрипт-экспортер (без зависимостей):**

```bash
#!/bin/bash
# /usr/local/bin/dhcp-metrics.sh — вывод метрик для Prometheus (textfile collector)
LEASE_FILE="/var/lib/kea/kea-leases4.csv"
PROM_DIR="/var/lib/node_exporter/textfile_collector"

mkdir -p "$PROM_DIR"

# Активные аренды
ACTIVE=$(grep -c "^," "$LEASE_FILE" 2>/dev/null || echo 0)
echo "dhcp_leases_active $ACTIVE" > "$PROM_DIR/dhcp.prom.$$"

# Abandoned
ABANDONED=$(grep -c "abandoned" "$LEASE_FILE" 2>/dev/null || echo 0)
echo "dhcp_leases_abandoned $ABANDONED" >> "$PROM_DIR/dhcp.prom.$$"

# Всего записей
TOTAL=$(wc -l < "$LEASE_FILE" 2>/dev/null || echo 0)
echo "dhcp_leases_total_records $TOTAL" >> "$PROM_DIR/dhcp.prom.$$"

mv "$PROM_DIR/dhcp.prom.$$" "$PROM_DIR/dhcp.prom"
```

### ISC DHCP → Prometheus

**dhcpd-leases-exporter:**

```bash
# Установка (GO-бинарник)
wget https://github.com/cspectian/dhcpd-leases-exporter/releases/latest/download/dhcpd-leases-exporter-linux-amd64
chmod +x dhcpd-leases-exporter-linux-amd64
sudo mv dhcpd-leases-exporter-linux-amd64 /usr/local/bin/dhcpd-leases-exporter

# Systemd unit
cat > /etc/systemd/system/dhcpd-leases-exporter.service << 'EOF'
[Unit]
Description=DHCPD Leases Exporter
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/dhcpd-leases-exporter \
  --dhcpd.leasesfile=/var/lib/dhcp/dhcpd.leases \
  --web.listen-address=:9153
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now dhcpd-leases-exporter

# Prometheus job
# scrape_configs:
#   - job_name: 'isc-dhcp'
#     static_configs:
#       - targets: ['dhcp-server:9153']
```

### Grafana Dashboard

**Ключевые панели для DHCP-дашборда:**

| Панель | Тип | Метрика | Виджет |
| :--- | :--- | :--- | :--- |
| **Pool Utilization** | Gauge | `dhcp_pool_utilization` | Зелёный <70%, жёлтый 70-90%, красный >90% |
| **Active Leases** | Time Series | `dhcp_leases_active` | График по времени |
| **Leases Rate** | Rate | `rate(dhcp_ack_total[5m])` | Скорость выдачи адресов/мин |
| **Error Rate** | Time Series | `dhcp_nak_total`, `dhcp_decline_total` | Ошибки по времени |
| **Response Time** | Heatmap | `dhcp_response_time_avg` | Распределение откликов |
| **Abandoned** | Stat | `dhcp_leases_abandoned` | Количество конфликтов |
| **Failover State** | State Timeline | `dhcp_failover_state` | Normal/Interrupted/Partner-Down |

**Пример provisioning-файла Grafana (JSON):**

```json
{
  "dashboard": {
    "title": "DHCP Server Monitoring",
    "panels": [
      {
        "title": "Pool Utilization",
        "type": "gauge",
        "targets": [
          {
            "expr": "dhcp_leases_active / dhcp_leases_total * 100",
            "legendFormat": "{{instance}}"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "thresholds": {
              "steps": [
                {"value": 0, "color": "green"},
                {"value": 70, "color": "yellow"},
                {"value": 90, "color": "red"}
              ]
            },
            "unit": "percent"
          }
        }
      },
      {
        "title": "DHCP ACKs per Minute",
        "type": "timeseries",
        "targets": [
          {
            "expr": "rate(dhcp_ack_total[5m]) * 60",
            "legendFormat": "{{instance}}"
          }
        ]
      }
    ]
  }
}
```

### Alerting Rules (Prometheus)

```yaml
# /etc/prometheus/rules/dhcp_alerts.yml
groups:
  - name: dhcp_alerts
    rules:
      # Пул заполнен >90%
      - alert: DhcpPoolNearExhaustion
        expr: dhcp_leases_active / dhcp_leases_total > 0.9
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "DHCP pool exhaustion (instance {{ $labels.instance }})"
          description: "Pool utilization {{ $value | humanizePercentage }}"

      # Нет ACK-ответов >5 минут
      - alert: DhcpServerUnresponsive
        expr: rate(dhcp_ack_total[5m]) == 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "DHCP server not responding ({{ $labels.instance }})"

      # Abandoned-адреса
      - alert: DhcpAbandonedLeases
        expr: dhcp_leases_abandoned > 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "DHCP abandoned lease detected ({{ $labels.instance }})"
          description: "IP conflict detected: {{ $value }} abandoned addresses"

      # DHCPNAK > 5% от ACK
      - alert: DhcpHighNakRate
        expr: rate(dhcp_nak_total[5m]) / rate(dhcp_ack_total[5m]) > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High DHCPNAK rate ({{ $labels.instance }})"
          description: "NAK rate {{ $value | humanizePercentage }}"

      # Failover != normal
      - alert: DhcpFailoverDegraded
        expr: dhcp_failover_state != 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "DHCP failover state != normal ({{ $labels.instance }})"
```

### Syslog → SIEM

**Формат CEF (Common Event Format) для DHCP:**

```
CEF:0|ISC|kea-dhcp4|2.0|lease-assigned|DHCP lease assigned|1|src=10.0.10.50 dst=10.0.0.100 dpt=67 cn1=1 cn1Label=subnet-id
CEF:0|ISC|kea-dhcp4|2.0|lease-expired|DHCP lease expired|1|src=10.0.10.50 dpt=67
CEF:0|ISC|kea-dhcp4|2.0|rogue-dhcp|Potential rogue DHCP detected|1|src={{src_ip}} dpt=67 cn1={{confidence}} cn1Label=confidence
```

**Корреляционные правила SIEM:**

```python
# Pseudocode для корреляции DHCP-событий

# 1. Обнаружение Rogue DHCP
IF (dhcp_discover FROM unknown_server_ip) AND (dhcp_discover NOT FROM authorized_servers):
    ALERT "Potential Rogue DHCP Server" SEVERITY=HIGH

# 2. DHCP Starvation Attack
IF (dhcp_discover_count FROM same_mac > 100) AND (time_window < 60s):
    ALERT "DHCP Starvation Attempt" SEVERITY=CRITICAL

# 3. Mass Lease Release (Storm)
IF (dhcp_release_count FROM same_subnet > 50) AND (time_window < 10s):
    ALERT "DHCP Release Storm" SEVERITY=HIGH
```

---

## Дополнительная информация

### Экспорт DHCP Snooping в SIEM

```bash
# Cisco IOS: настройка syslog для DHCP Snooping
ip dhcp snooping
ip dhcp snooping information option
logging host 10.0.0.200
logging trap informational

# Juniper JunOS
system syslog {
    file dhcp-snooping-log {
        daemon info;
        match "dhcp-snooping";
    }
    destination logserver {
        archive-sites {
            syslog.example.com;
        }
    }
}
```

### Связанные разделы

- **[Kea DHCP: Архитектура и настройка](../../../Linux/Networking/Services/DHCP/kea_dhcp_overview.md)** — REST API Kea.
- **[ISC DHCP: Проверка и мониторинг](../../../Linux/Networking/Services/DHCP/isc_dhcp_server_verification.md)** —ISC-специфичный мониторинг.
- **[Диагностика DHCP](./dhcp_analysis_troubleshooting.md)** — tcpdump, Wireshark, debug-режимы.
- **[Безопасность DHCP](./dhcp_security.md)** — DHCP Snooping, SIEM-интеграция.
- **RFC 8415** — Kea → structured logging.
- **[Prometheus Documentation](https://prometheus.io/docs/)** — официальная документация.
- **[Grafana Documentation](https://grafana.com/docs/)** — официальная документация.
