# Wazuh + Prometheus/Grafana: метрики, дашборды, алерты

## Определения

**Wazuh Exporter** — промежуточный компонент (sidecar или standalone), преобразующий внутренние метрики Wazuh (OTLP, REST API) в формат Prometheus (metrics endpoint на HTTP).

**OTLP (OpenTelemetry Protocol)** — стандарт передачи телеметрии (metrics, traces, logs). Wazuh 5.0 генерирует нативные OTLP-метрики через `wazuh.yaml`.

**Prometheus** — система мониторинга и алертинга, сканирующая HTTP-эндпоинты (targets) и хранящая метрики в time-series базе данных.

**Grafana** — платформа визуализации, подключающаяся к Prometheus (и другим источникам) для построения дашбордов и алертов.

**Alertmanager** — компонент Prometheus для маршрутизации алертов (email, Slack, Telegram, PagerDuty).

## Основные концепции

### Архитектура интеграции

```
┌──────────────┐     OTLP/gRPC      ┌──────────────────┐
│ Wazuh Manager│──────────────────→│  OTel Collector   │
│  (OTLP exporter)                  │  (optional)       │
└──────┬───────┘                    └────────┬─────────┘
       │                                     │
       │ REST API                            │
       ▼                                     ▼
┌──────────────┐                    ┌──────────────────┐
│ Wazuh        │                    │  Prometheus      │
│ Exporter     │──metrics──→        │  (scrape)        │
│ :9664/metrics│                    │                  │
└──────────────┘                    └────────┬─────────┘
                                             │
                                             ▼
                                    ┌──────────────────┐
                                    │  Grafana          │
                                    │  (dashboards)     │
                                    └──────────────────┘
```

### Ключевые метрики Wazuh для Prometheus

| Метрика | Тип | Описание |
|:---|:---|:---|
| `wazuh_manager_events_processed_total` | Counter | Всего обработанных событий |
| `wazuh_manager_events_per_second` | Gauge | Текущий EPS |
| `wazuh_manager_queue_latency_seconds` | Histogram | Задержка обработки |
| `wazuh_manager_queue_size` | Gauge | Размер очереди |
| `wazuh_manager_backpressure_active` | Gauge | Статус backpressure (0/1) |
| `wazuh_agents_total` | Gauge | Общее количество агентов |
| `wazuh_agents_active` | Gauge | Активные агенты |
| `wazuh_agents_disconnected` | Gauge | Отключённые агенты |
| `wazuh_indexer_disk_usage_bytes` | Gauge | Использование диска Indexer |
| `wazuh_indexer_cluster_health` | Gauge | Health cluster (green=1, yellow=2, red=3) |

## Практические сценарии

### 1. Wazuh Exporter (standalone)

```python
#!/usr/bin/env python3
"""wazuh-exporter: REST API → Prometheus metrics."""
import time
import requests
from prometheus_client import start_http_server, Gauge, Counter, Histogram

WAZUH_API = "https://localhost:55000"
WAZUH_USER = "monitor"
WAZUH_PASS = "MonitorPass123"
EXPORTER_PORT = 9664

# Метрики Prometheus
EVENTS_TOTAL = Counter('wazuh_manager_events_processed_total', 'Total events processed')
EVENTS_EPS = Gauge('wazuh_manager_events_per_second', 'Current EPS')
QUEUE_SIZE = Gauge('wazuh_manager_queue_size', 'Current queue size')
QUEUE_LATENCY = Gauge('wazuh_manager_queue_latency_seconds', 'Queue latency')
BACKPRESSURE = Gauge('wazuh_manager_backpressure_active', 'Backpressure active')
AGENTS_TOTAL = Gauge('wazuh_agents_total', 'Total agents')
AGENTS_ACTIVE = Gauge('wazuh_agents_active', 'Active agents')
AGENTS_DISCONNECTED = Gauge('wazuh_agents_disconnected', 'Disconnected agents')
INDEXER_DISK = Gauge('wazuh_indexer_disk_usage_bytes', 'Indexer disk usage')
INDEXER_HEALTH = Gauge('wazuh_indexer_cluster_health', 'Cluster health')

def get_token():
    resp = requests.post(
        f"{WAZUH_API}/security/user/authenticate",
        json={"username": WAZUH_USER, "password": WAZUH_PASS},
        verify=False
    )
    return resp.json()["data"]["token"]

def collect_metrics(token):
    headers = {"Authorization": f"Bearer {token}"}

    # Agent summary
    agents = requests.get(f"{WAZUH_API}/agents/summary", headers=headers, verify=False).json()["data"]
    AGENTS_TOTAL.set(agents.get("total", 0))
    AGENTS_ACTIVE.set(agents.get("active", 0))
    AGENTS_DISCONNECTED.set(agents.get("disconnected", 0))

    # Engine metrics (через OTLP или internal)
    try:
        engine = requests.get(f"{WAZUH_API}/manager/metrics?section=engine", headers=headers, verify=False).json()["data"]
        EVENTS_EPS.set(engine.get("events", {}).get("eps", 0))
        QUEUE_SIZE.set(engine.get("queue", {}).get("current_size", 0))
        QUEUE_LATENCY.set(engine.get("queue", {}).get("latency_avg", 0))
        BACKPRESSURE.set(1 if engine.get("backpressure", {}).get("active", False) else 0)
    except Exception:
        pass

    # Indexer health
    try:
        health = requests.get("https://localhost:9200/_cluster/health", headers={"Authorization": "Basic YWRtaW46YWRtaW4="}, verify=False).json()
        status_map = {"green": 1, "yellow": 2, "red": 3}
        INDEXER_HEALTH.set(status_map.get(health.get("status", ""), 0))
    except Exception:
        pass

def main():
    token = get_token()
    start_http_server(EXPORTER_PORT)
    print(f"Wazuh Exporter listening on :{EXPORTER_PORT}/metrics")

    while True:
        try:
            collect_metrics(token)
        except Exception as e:
            print(f"Error collecting metrics: {e}")
            token = get_token()  # Re-authenticate
        time.sleep(15)

if __name__ == "__main__":
    main()
```

### 2. Prometheus конфигурация

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'wazuh'
    scrape_interval: 15s
    static_configs:
      - targets: ['wazuh-exporter:9664']
    metrics_path: '/metrics'

  - job_name: 'wazuh-indexer'
    scrape_interval: 30s
    static_configs:
      - targets: ['wazuh-indexer:9200']
    metrics_path: '/_prometheus/metrics'
    scheme: https
    tls_config:
      insecure_skip_verify: true
    basic_auth:
      username: admin
      password: admin
```

### 3. Grafana дашборд: JSON импорт

```json
{
  "dashboard": {
    "title": "Wazuh SIEM Overview",
    "panels": [
      {
        "title": "Active Agents",
        "type": "stat",
        "targets": [{"expr": "wazuh_agents_active", "legendFormat": "Active"}],
        "fieldConfig": {"defaults": {"thresholds": {"steps": [{"value": 0, "color": "red"}, {"value": 100, "color": "green"}]}}}
      },
      {
        "title": "EPS (Events Per Second)",
        "type": "timeseries",
        "targets": [{"expr": "wazuh_manager_events_per_second", "legendFormat": "EPS"}]
      },
      {
        "title": "Queue Latency",
        "type": "timeseries",
        "targets": [{"expr": "wazuh_manager_queue_latency_seconds", "legendFormat": "Latency"}],
        "fieldConfig": {"defaults": {"thresholds": {"steps": [{"value": 0.5, "color": "yellow"}, {"value": 1, "color": "red"}]}}}
      },
      {
        "title": "Disconnected Agents",
        "type": "timeseries",
        "targets": [{"expr": "wazuh_agents_disconnected", "legendFormat": "Disconnected"}]
      },
      {
        "title": "Backpressure",
        "type": "stat",
        "targets": [{"expr": "wazuh_manager_backpressure_active", "legendFormat": "Active"}],
        "fieldConfig": {"defaults": {"mappings": [{"type": "value", "options": {"0": {"text": "Normal"}, "1": {"text": "BACKPRESSURE"}}]}}}
      },
      {
        "title": "Indexer Cluster Health",
        "type": "stat",
        "targets": [{"expr": "wazuh_indexer_cluster_health", "legendFormat": "Health"}],
        "fieldConfig": {"defaults": {"mappings": [{"type": "value", "options": {"1": {"text": "Green", "color": "green"}, "2": {"text": "Yellow", "color": "yellow"}, "3": {"text": "Red", "color": "red"}}]}}}
      }
    ]
  }
}
```

### 4. Alertmanager правила

```yaml
# alertmanager.yml
route:
  group_by: ['alertname']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'slack-notifications'

receivers:
  - name: 'slack-notifications'
    slack_configs:
      - channel: '#wazuh-alerts'
        send_resolved: true
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'

  - name: 'pagerduty'
    pagerduty_configs:
      - service_key: '<your-key>'
```

```yaml
# rules/wazuh_alerts.yml
groups:
  - name: wazuh
    rules:
      - alert: WazuhHighEPS
        expr: wazuh_manager_events_per_second > 10000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High EPS detected"
          description: "EPS is {{ $value }}, threshold is 10000"

      - alert: WazuhAgentsDisconnected
        expr: wazuh_agents_disconnected / wazuh_agents_total > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "More than 5% agents disconnected"
          description: "{{ $value | humanizePercentage }} agents are disconnected"

      - alert: WazuhBackpressure
        expr: wazuh_manager_backpressure_active == 1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Wazuh backpressure is active"

      - alert: WazuhIndexerHealthRed
        expr: wazuh_indexer_cluster_health == 3
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Wazuh Indexer cluster health is RED"

      - alert: WazuhQueueLatencyHigh
        expr: wazuh_manager_queue_latency_seconds > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Queue latency is high: {{ $value }}s"
```

### 5. Docker Compose: полный стек

```yaml
# docker-compose.yml
version: '3.8'
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - ./rules:/etc/prometheus/rules
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.retention.time=90d'

  grafana:
    image: grafana/grafana:latest
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards
      - ./grafana/datasources:/etc/grafana/provisioning/datasources
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin

  wazuh-exporter:
    build: ./wazuh-exporter
    environment:
      - WAZUH_API=https://wazuh-manager:55000
      - WAZUH_USER=monitor
      - WAZUH_PASS=MonitorPass123
    ports:
      - "9664:9664"

  alertmanager:
    image: prom/alertmanager:latest
    volumes:
      - ./alertmanager.yml:/etc/alertmanager/alertmanager.yml
    ports:
      - "9093:9093"

volumes:
  prometheus_data:
  grafana_data:
```

## Дополнительная информация

### Best Practices

1. **Scrape interval**: 15s для Wazuh, 30s для Indexer.
2. **Retention**: 90 дней в Prometheus, архив в Thanos/Mimir.
3. **Dashboards**: начните с общего Overview, добавляйте detail panels.
4. **Alerты**: не создавайте больше 10 правил (alert fatigue).
5. **Exporters**: один exporter на кластер, не на узел.

### Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Exporter не стартует** | Нет доступа к Wazuh API | Проверьте JWT-токен |
| **Метрики не обновляются** | Exporter не может авторизоваться | Пересоздайте токен |
| **Grafana "No data"** | Prometheus не скрейпит | Проверьте targets в Prometheus UI |
| **Alerты не приходят** | Alertmanager не настроен | Проверьте receiver в alertmanager.yml |

### См. также
- [Health Monitoring](./wazuh-health-monitoring.md) — Golden Signals.
- [Performance Tuning](./wazuh-performance-tuning.md) — метрики производительности.
- [Zabbix Integration](./zabbix-integration.md) — альтернатива Prometheus.
