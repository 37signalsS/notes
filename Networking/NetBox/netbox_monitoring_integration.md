# NetBox: Мониторинг и интеграция с Prometheus/Grafana

Руководство по настройке мониторинга NetBox с использованием Prometheus и Grafana. Обзор концепций приведен в файле **[NetBox: Обзор и базовые концепции](./overview.md)**.

## Определения

**Prometheus** — система мониторинга и алертинга с открытым исходным кодом. Собирает метрики через HTTP-pull модель и хранит их в временных рядах (time-series database).

**Grafana** — платформа для визуализации данных и построения дашбордов. Поддерживает множество источников данных, включая Prometheus.

**Exporter** — программный компонент, который собирает метрики из внешней системы и экспортирует их в формате Prometheus.

**SLI (Service Level Indicator)** — количественная метрика качества сервиса (время отклика, доступность, ошибки).

**SLO (Service Level Objective)** — целевое значение SLI (например, 99.9% доступности за месяц).

**Alerting Rules** — правила Prometheus для генерации алертов при нарушении условий (например, время отклика > 2 секунд).

**黑盒 (Blackbox) Exporter** — компонент Prometheus для проверки доступности внешних сервисов через HTTP, TCP, ICMP, DNS.

## Базовые концепции

### Архитектура мониторинга NetBox

```
┌─────────────────────────────────────────────────────────┐
│                  Prometheus                              │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────┐  │
│  │ HTTP Pull   │  │ Alert Rules │  │  Time Series DB  │  │
│  │ /metrics   │  │            │  │                  │  │
│  └──────┬─────┘  └─────┬──────┘  └────────┬─────────┘  │
└─────────┼───────────────┼─────────────────┼─────────────┘
          │               │                 │
          ▼               ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│  NetBox      │  │ AlertManager │  │     Grafana      │
│  (custom     │  │  (уведомления│  │  (дашборды)      │
│   metrics)   │  │   в Slack)   │  │                  │
└──────────────┘  └──────────────┘  └──────────────────┘
```

### Ключевые метрики NetBox

| Метрика | Тип | Описание | Критичность |
| :--- | :--- | :--- | :--- |
| `netbox_http_requests_total` | Counter | Общее количество HTTP-запросов | Средняя |
| `netbox_http_request_duration_seconds` | Histogram | Время обработки запросов | Высокая |
| `netbox_db_connection_count` | Gauge | Количество соединений с БД | Высокая |
| `netbox_redis_connection_count` | Gauge | Количество соединений с Redis | Средняя |
| `netbox_rq_queue_length` | Gauge | Длина очереди задач | Высокая |
| `netbox_cache_hit_ratio` | Gauge | Коэффициент попаданий в кэш | Средняя |
| `netbox_uptime_seconds` | Gauge | Время работы с момента запуска | Низкая |
| `netbox_version_info` | Info | Версия NetBox | Низкая |

## Практические сценарии

### 1. Настройка кастомных метрик NetBox

Создайте файл `/opt/netbox/netbox/netbox/metrics.py`:

```python
from prometheus_client import Counter, Histogram, Gauge, Info
from django.db import connection
import time

# Метрики HTTP-запросов
http_requests_total = Counter(
    'netbox_http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

http_request_duration = Histogram(
    'netbox_http_request_duration_seconds',
    'HTTP request duration',
    ['method', 'endpoint'],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# Метрики БД
db_connections = Gauge(
    'netbox_db_connection_count',
    'Number of active DB connections'
)

db_query_duration = Histogram(
    'netbox_db_query_duration_seconds',
    'Database query duration',
    ['query_type'],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5]
)

# Метрики Redis
redis_operations = Counter(
    'netbox_redis_operations_total',
    'Total Redis operations',
    ['operation', 'status']
)

# Метрики RQ
rq_queue_length = Gauge(
    'netbox_rq_queue_length',
    'RQ queue length',
    ['queue']
)

# Метрики кэша
cache_hits = Counter(
    'netbox_cache_hits_total',
    'Cache hits'
)

cache_misses = Counter(
    'netbox_cache_misses_total',
    'Cache misses'
)

# Информация о версии
netbox_version = Info(
    'netbox',
    'NetBox version information'
)
netbox_version.info({
    'version': '4.4.8',
    'python_version': '3.11'
})
```

### 2. Django Middleware для сбора метрик

Создайте файл `/opt/netbox/netbox/netbox/middleware_metrics.py`:

```python
import time
from .metrics import http_requests_total, http_request_duration

class PrometheusMetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()
        response = self.get_response(request)
        duration = time.time() - start_time

        # Запись метрик
        http_requests_total.labels(
            method=request.method,
            endpoint=request.path,
            status=response.status_code
        ).inc()

        http_request_duration.labels(
            method=request.method,
            endpoint=request.path
        ).observe(duration)

        return response
```

Добавьте в `settings.py`:

```python
MIDDLEWARE = [
    'netbox.middleware_metrics.PrometheusMetricsMiddleware',  # Добавьте первую строку
    # ... остальные middleware
]
```

### 3. Экспорт метрик через HTTP-эндпоинт

Добавьте в `urls.py`:

```python
from django.urls import path
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

def metrics_view(request):
    return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)

urlpatterns = [
    # ... существующие URL
    path('metrics/', metrics_view, name='metrics'),
]
```

### 4. Настройка Prometheus

Создайте `/etc/prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'netbox'
    metrics_path: '/metrics/'
    bearer_token: 'YOUR_NETBOX_TOKEN'
    static_configs:
      - targets: ['netbox.example.com:443']
        labels:
          instance: 'netbox-production'
    tls_config:
      insecure_skip_verify: false

  - job_name: 'netbox-blackbox'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
          - https://netbox.example.com
        labels:
          instance: 'netbox-http'
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox-exporter:9115

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']

  - job_name: 'postgres-exporter'
    static_configs:
      - targets: ['postgres-exporter:9187']

  - job_name: 'redis-exporter'
    static_configs:
      - targets: ['redis-exporter:9121']

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['alertmanager:9093']

rule_files:
  - 'rules/*.yml'
```

### 5. Alert Rules для NetBox

Создайте `/etc/prometheus/rules/netbox_alerts.yml`:

```yaml
groups:
  - name: netbox_alerts
    rules:
      # NetBox недоступен
      - alert: NetBoxDown
        expr: up{job="netbox"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "NetBox недоступен"
          description: "NetBox не отвечает более 1 минуты"

      # Высокий time-to-first-byte
      - alert: NetBoxHighLatency
        expr: histogram_quantile(0.95, rate(netbox_http_request_duration_seconds_bucket[5m])) > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая задержка NetBox"
          description: "95-й перцентиль времени отклика: {{ $value }} секунд"

      # Высокий percentage ошибок
      - alert: NetBoxHighErrorRate
        expr: rate(netbox_http_requests_total{status=~"5.."}[5m]) / rate(netbox_http_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Высокий percentage ошибок NetBox"
          description: "Более 5% запросов возвращают ошибки 5xx"

      # Длинная очередь RQ
      - alert: NetBoxRQLongQueue
        expr: netbox_rq_queue_length > 100
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Длинная очередь задач NetBox"
          description: "Очередь RQ содержит {{ $value }} задач"

      # Нехватка соединений с БД
      - alert: NetBoxDBConnectionsHigh
        expr: netbox_db_connection_count > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Много соединений с PostgreSQL"
          description: "Активных соединений: {{ $value }}"

      # PostgreSQL недоступен
      - alert: PostgresDown
        expr: up{job="postgres-exporter"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "PostgreSQL недоступен"

      # Redis недоступен
      - alert: RedisDown
        expr: up{job="redis-exporter"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Redis недоступен"
```

### 6. Настройка AlertManager

Создайте `/etc/alertmanager/alertmanager.yml`:

```yaml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'slack-notifications'

  routes:
    - match:
        severity: critical
      receiver: 'pagerduty-critical'
    - match:
        severity: warning
      receiver: 'slack-notifications'

receivers:
  - name: 'slack-notifications'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK'
        channel: '#netbox-alerts'
        send_resolved: true
        title: '[[ .GroupLabels.alertname ]]'
        text: >-
          [[ range .Alerts ]]
          *Alert:* [[ .Annotations.summary ]]
          *Description:* [[ .Annotations.description ]]
          *Severity:* [[ .Labels.severity ]]
          [[ end ]]

  - name: 'pagerduty-critical'
    pagerduty_configs:
      - service_key: 'YOUR_PAGERDUTY_KEY'
        severity: critical
```

### 7. Docker Compose для стека мониторинга

Создайте `/opt/netbox-docker/docker-compose.monitoring.yml`:

```yaml
version: '3.8'

services:
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - ./prometheus/rules:/etc/prometheus/rules
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
    ports:
      - "9090:9090"
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:-admin}
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning
    ports:
      - "3000:3000"
    restart: unless-stopped

  alertmanager:
    image: prom/alertmanager:latest
    container_name: alertmanager
    volumes:
      - ./alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml
    ports:
      - "9093:9093"
    restart: unless-stopped

  postgres-exporter:
    image: prometheuscommunity/postgres-exporter:latest
    container_name: postgres-exporter
    environment:
      DATA_SOURCE_NAME: "postgresql://netbox:password@postgres:5432/netbox?sslmode=disable"
    ports:
      - "9187:9187"
    restart: unless-stopped

  redis-exporter:
    image: oliver006/redis_exporter:latest
    container_name: redis-exporter
    environment:
      REDIS_ADDR: "redis:6379"
      REDIS_PASSWORD: "your_redis_password"
    ports:
      - "9121:9121"
    restart: unless-stopped

  blackbox-exporter:
    image: prom/blackbox-exporter:latest
    container_name: blackbox-exporter
    volumes:
      - ./blackbox/blackbox.yml:/config/blackbox.yml
    command:
      - '--config.file=/config/blackbox.yml'
    ports:
      - "9115:9115"
    restart: unless-stopped

volumes:
  prometheus_data:
  grafana_data:
```

### 8. Настройка Grafana дашбордов

Импортируйте готовый дашборд NetBox:

1. Откройте Grafana (`http://grafana:3000`)
2. Добавьте Prometheus как источник данных (`http://prometheus:9090`)
3. Импортируйте дашборд ID `14600` (NetBox Overview) или создайте свой

Ключевые панели для дашборда:

| Панель | Метрика | Описание |
| :--- | :--- | :--- |
| **Request Rate** | `rate(netbox_http_requests_total[5m])` | Requests per second |
| **Response Time** | `histogram_quantile(0.95, ...)` | 95th percentile latency |
| **Error Rate** | `rate(...{status=~"5.."}[5m])` | Percentage of 5xx errors |
| **DB Connections** | `netbox_db_connection_count` | Active PostgreSQL connections |
| **RQ Queue** | `netbox_rq_queue_length` | Pending tasks |
| **Cache Hit Ratio** | `cache_hits / (cache_hits + cache_misses)` | Cache efficiency |

### 9. Мониторинг с Zabbix (альтернатива)

Для тех, кто использует Zabbix вместо Prometheus:

```bash
# Установка zabbix-agent2 на сервере NetBox
sudo apt install -y zabbix-agent2

# Конфигурация /etc/zabbix/zabbix_agent2.d/netbox.conf
Server=YOUR_ZABBIХ_SERVER
ServerActive=YOUR_ZABBIХ_SERVER
Hostname=netbox.example.com

# Пользовательский скрипт для проверки NetBox
# /etc/zabbix/scripts/check_netbox.sh
#!/bin/bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Token YOUR_TOKEN" \
  https://netbox.example.com/api/status/
```

### 10. Настройка SLI/SLO для NetBox

Определите ключевые SLI:

| SLI | Метрика | SLO |
| :--- | :--- | :--- |
| **Доступность** | `up{job="netbox"}` | 99.9% за месяц |
| **Время отклика** | `histogram_quantile(0.95, ...)` | < 1 секунды |
| **Ошибка API** | `rate(...{status=~"5.."}[5m])` | < 0.1% |
| **Очередь задач** | `netbox_rq_queue_length` | < 50 задач |

## Обслуживание и эксплуатация

### Типовые проблемы и их решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Prometheus не скрейпит метрики** | Неверный токен или URL | Проверьте `bearer_token` в `prometheus.yml` |
| **Grafana: No data** | Источник данных не настроен | Добавьте Prometheus как datasource |
| **Алерты не приходят** | AlertManager не настроен | Проверьте `alertmanager.yml` и webhook |
| **Высокий memory usage Prometheus** | Слишком много метрик | Увеличьте `retention.time` или уменьшите `scrape_interval` |
| **NetBox: ImportError metrics** | Не установлен prometheus_client | `pip install prometheus_client` |
| **Частые false positive алерты** | Слишком чувствительные правила | Увеличьте `for:` в alert rules |

### Оптимизация Prometheus для NetBox

```yaml
# Оптимизация storage
global:
  scrape_interval: 30s  # Увеличьте для снижения нагрузки
  evaluation_interval: 30s

# Фильтрация метрик (только нужные)
scrape_configs:
  - job_name: 'netbox'
    metric_relabel_configs:
      - source_labels: [__name__]
        regex: 'netbox_.*'
        action: keep
```

## Дополнительная информация

### Полезные ресурсы

- [Официальная документация Prometheus](https://prometheus.io/docs/)
- [Grafana: Создание дашбордов](https://grafana.com/docs/grafana/latest/)
- [NetBox: Метрики для мониторинга](https://docs.netbox.dev/en/stable/administration/health-checks/)

### См. также

- [NetBox: Обзор и базовые концепции](./overview.md)
- [Установка NetBox в Debian](./netbox_debian_installation_guide.md)
- [Развертывание NetBox в Docker](./netbox_docker_deployment.md)
- [Интеграция с конфигурационным бэкапом](./netbox_config_backup_integration.md)
