# Multi-tenancy в Prometheus

## Определения

**Multi-tenancy (Мультитенантность)** — архитектурный паттерн, при котором один экземпляр Prometheus обслуживает несколько независимых команд (tenant) с гарантированной изоляцией данных. Каждый tenant видит только свои метрики и не может повлиять на метрики других.

**Tenant ID (Идентификатор тенанта)** — уникальная метка, идифицирующая принадлежность метрик к конкретному tenant. Используется для фильтрации при запросах и записи.

> **См. также:** [Labels and Cardinality](./concepts/labels_and_cardinality.md) — управление метками; [Security](./security.md) — аутентификация и авторизация; [Концепции multi-tenancy](../Kubernetes/Concepts/multi-tenancy.md) — общие паттерны в K8s.

---

## Базовые концепции

### Зачем нужна multi-tenancy

| Проблема | Решение через multi-tenancy |
|:---|:---|
| Команды смешивают метрики | Label-based изоляция (`team`, `namespace`) |
| Нет chargeback (атрибуция затрат) | Подсчёт series/queries по tenant |
| Один tenant может исчерпать ресурсы | Rate limiting и quotas per tenant |
| Нет изоляции данных | Виртуальная изоляция через relabeling |

### Модели изоляции

| Модель | Описание | Сложность | Уровень изоляции |
|:---|:---|:---|:---|
| **Label-based** | Один Prometheus, фильтрация по labels | Низкая | Низкий (логический) |
| **Per-namespace** | Отдельный Prometheus на namespace/команду | Средняя | Высокий (физический) |
| **Thanos Receive** | Multi-tenant через `receive_tenant_id` | Средняя | Средний |
| **VictoriaMetrics** | `extra_labels` или `X-Scope-OrgID` | Низкая | Средний |
| **Mimir** | `X-Scope-OrgID` header | Низкая | Высокий |

---

## Практические сценарии

### Модель 1: Label-based изоляция (простейшая)

Разделение метрик через label `team` в relabel_configs:

```yaml
# prometheus.yml — scrape configs для разных команд
scrape_configs:
  - job_name: 'team-backend'
    file_sd_configs:
      - files: ['/etc/prometheus/file_sd/team_backend.yml']
    relabel_configs:
      - target_label: team
        replacement: 'backend'

  - job_name: 'team-frontend'
    file_sd_configs:
      - files: ['/etc/prometheus/file_sd/team_frontend.yml']
    relabel_configs:
      - target_label: team
        replacement: 'frontend'
```

Запросы с фильтрацией по tenant:

```promql
# Только метрики backend-команды
rate(http_requests_total{team="backend"}[5m])

# Агрегация по командам
sum by(team) (rate(http_requests_total[5m]))
```

### Модель 2: Nginx reverse proxy с tenant isolation

```nginx
# /etc/nginx/conf.d/prometheus-tenants.conf
# Tenant A — доступ только к своим метрикам
server {
    listen 9091;
    server_name prom-backend.corp.local;

    location / {
        # Проксируем на Prometheus, добавляя label фильтр
        proxy_pass http://localhost:9090;
        proxy_set_header X-Prometheus-Extra-Labels "team=backend";
    }

    # Запрет доступа к admin API
    location /-/admin {
        deny all;
    }
}
```

### Модель 3: Alertmanager с tenant-based routing

```yaml
# alertmanager.yml — маршрутизация по tenant
route:
  group_by: ['alertname', 'team']
  receiver: 'default'
  routes:
    - match:
        team: backend
      receiver: 'backend-slack'
    - match:
        team: frontend
      receiver: 'frontend-slack'
    - match:
        team: sre
      receiver: 'sre-pager'

receivers:
  - name: 'backend-slack'
    slack_configs:
      - api_url: '${BACKEND_SLACK_WEBHOOK}'
        channel: '#backend-alerts'
  - name: 'frontend-slack'
    slack_configs:
      - api_url: '${FRONTEND_SLACK_WEBHOOK}'
        channel: '#frontend-alerts'
  - name: 'sre-pager'
    pagerduty_configs:
      - service_key: '${SRE_PAGERDUTY_KEY}'
```

### Модель 4: Thanos Receive (multi-tenant)

```yaml
# thanos-receive.yaml
type: RECEIVE
receiver:
  default-tenant-id: "default"
  endpoints:
    - endpoint: "http://prometheus-0:9090/api/v1/receive"
      labels: { cluster: "prod" }
    - endpoint: "http://prometheus-1:9090/api/v1/receive"
      labels: { cluster: "prod" }
  hashrings:
    - endpoints:
        - "http://thanos-receive-0:19291"
        - "http://thanos-receive-1:19291"
```

### Модель 5: VictoriaMetrics multi-tenancy

```yaml
# vminsert — multi-tenant через extra_labels
vminsert:
  extra_labels:
    - name: team
      value: "backend"
    - name: env
      value: "production"

# Конфиг Prometheus для remote_write в VictoriaMetrics
remote_write:
  - url: "http://vminsert:8480/insert/0/prometheus/api/v1/write"
    write_relabel_configs:
      - source_labels: [__name__]
        regex: '(.*)'
        target_label: team
        replacement: 'backend'
```

### Модель 6: kube-prometheus-stack multi-tenant (ServiceMonitor)

```yaml
# Ограничение ServiceMonitor по namespace через label
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: tenant-backend
spec:
  serviceMonitorSelector:
    matchLabels:
      team: backend
  serviceMonitorNamespaceSelector:
    matchLabels:
      tenant: backend
  resources:
    requests:
      memory: 4Gi
      cpu: 2000m
```

---

## Дополнительная информация

### Метрики для chargeback

```promql
# Количество series по tenant
count by(team) ({__name__=~".+"})

# Объём данных по tenant (в TSDB)
prometheus_tsdb_head_series{team="backend"}

# Количество scrape targets по tenant
count by(team) (up)
```

### Типичные ошибки

| Проблема | Причина | Решение |
|:---|:---|:---|
| Tenant видит чужие метрики | Отсутствие фильтрации | Добавить relabel_configs с tenant label |
| Высокий шум от одного tenant | Нет rate limiting | Настроить `sample_limit` в scrape_configs |
| Алерты утекают в чужой канал | Нет group_by по tenant | Добавить `team` в `group_by` маршрутизации |
| OOM из-за cardinality одного tenant | Нет квот | `max_series` на job level |
