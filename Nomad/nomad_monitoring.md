# Nomad — Мониторинг (Prometheus + Grafana)

## Определения

**Nomad Metrics** — метрики, экспортируемые Nomad через HTTP API `/v1/metrics`, включая данные о клиентах, серверах, аллокациях, задачах и Raft.

**nomad_sd_configs** — механизм Service Discovery в Prometheus для автоматического обнаружения целей сбора метрик из Nomad-кластера.

**Alerting Rules** — правила Prometheus для генерации алертов при нарушении пороговых значений метрик Nomad.

**Grafana Dashboard** — визуальная панель для мониторинга Nomad-кластера в реальном времени.

## Основные концепции

### Архитектура мониторинга

```
Nomad Servers/Clients
  ↓ (HTTP /v1/metrics)
Prometheus (nomad_sd_configs)
  ↓
Alertmanager → Slack/PagerDuty
  ↓
Grafana Dashboards
```

### Ключевые метрики Nomad

| Метрика | Тип | Назначение |
| :--- | :--- | :--- |
| `nomad_client_allocations_running` | Gauge | Количество запущенных аллокаций |
| `nomad_client_allocations_cpu_total_ticks` | Counter | Суммарное потребление CPU |
| `nomad_client_allocations_memory_rss` | Gauge | Фактическое потребление RAM |
| `nomad_client_allocations_memory_cache` | Gauge | Кэшированная память |
| `nomad_server_evaluations_total` | Counter | Количество эвалюаций |
| `nomad_server_evaluations_pending` | Gauge | Очередь необработанных эвалюаций |
| `nomad_server_plan_apply_duration_seconds` | Histogram | Задержки планировщика |
| `nomad_raft_leader` | Gauge | Текущий лидер Raft (1/0) |
| `nomad_raft_commit_time_seconds` | Histogram | Время коммита Raft |
| `nomad_client_uptime` | Gauge | Аптайм клиента |
| `nomad_client_nodes` | Gauge | Количество узлов в кластере |
| `nomad_job_summary_running` | Gauge | Запущенные задачи по джобам |

## Практические сценарии

### Сценарий 1: Конфигурация Prometheus для Nomad

**prometheus.yml:**
```yaml
scrape_configs:
  - job_name: 'nomad'
    metrics_path: '/v1/metrics'
    params:
      format: ['prometheus']
    nomad_sd_configs:
      - server: 'http://nomad.service.consul:4646'
        token: '${NOMAD_ACL_TOKEN}'
    relabel_configs:
      # Добавление метки datacenter
      - source_labels: [__meta_nomad_dc]
        target_label: datacenter

      # Добавление метки node_id
      - source_labels: [__meta_nomad_node_id]
        target_label: node_id

      # Добавление метки node_name
      - source_labels: [__meta_nomad_node_name]
        target_label: node_name

      # Фильтрация только серверов
      - source_labels: [__meta_nomad_node_class]
        regex: 'server'
        action: keep

  - job_name: 'nomad-client'
    metrics_path: '/v1/metrics'
    params:
      format: ['prometheus']
    nomad_sd_configs:
      - server: 'http://nomad.service.consul:4646'
        token: '${NOMAD_ACL_TOKEN}'
    relabel_configs:
      - source_labels: [__meta_nomad_node_class]
        regex: 'client'
        action: keep
```

### Сценарий 2: Alerting Rules для Nomad

**nomad-alerts.yml:**
```yaml
groups:
  - name: nomad
    rules:
      # Лидер Raft потерян
      - alert: NomadLeaderLost
        expr: nomad_raft_leader == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Nomad Raft leader lost"
          description: "Nomad cluster has no Raft leader for {{ $value }} minutes"
          runbook: "https://wiki.example.com/runbooks/nomad-leader-lost"

      # Высокий stale evals
      - alert: NomadHighEvalPending
        expr: nomad_server_evaluations_pending > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High pending evaluations"
          description: "{{ $value }} evaluations pending in Nomad"

      # Медленный планировщик
      - alert: NomadSlowScheduler
        expr: histogram_quantile(0.95, rate(nomad_server_plan_apply_duration_seconds_bucket[5m])) > 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Nomad scheduler latency high"
          description: "P95 plan apply duration is {{ $value }}s"

      # Аллокации в unhealthy состоянии
      - alert: NomadAllocUnhealthy
        expr: nomad_client_allocations_running == 0 and nomad_client_allocations_pending > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Nomad allocations unhealthy"

      # Узел недоступен
      - alert: NomadNodeDown
        expr: nomad_client_uptime == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Nomad node is down"
          description: "Node {{ $labels.node_name }} has been down for {{ $value }} minutes"

      # Высокое потребление CPU
      - alert: NomadHighCPU
        expr: rate(nomad_client_allocations_cpu_total_ticks[5m]) > 80000
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage on Nomad client"
          description: "Client {{ $labels.node_name }} CPU usage is {{ $value }}"

      # Высокое потребление памяти
      - alert: NomadHighMemory
        expr: nomad_client_allocations_memory_rss / (1024*1024*1024) > 8
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage on Nomad client"
          description: "Client {{ $labels.node_name }} using {{ $value }}GB RSS"
```

### Сценарий 3: Grafana Dashboard

**Основные панели для Nomad Dashboard:**

| Секция | Панели | PromQL |
| :--- | :--- | :--- |
| **Cluster Overview** | Узлы, аллокации, джобы | `count(nomad_client_uptime)` |
| **Raft Health** | Leader, commit time | `nomad_raft_leader` |
| **Scheduler** | Pending evals, latency | `nomad_server_evaluations_pending` |
| **Resource Usage** | CPU, Memory по клиентам | `nomad_client_allocations_memory_rss` |
| **Allocations** | Running/Failed/Pending | `nomad_client_allocations_running` |

**JSON-модель дашборда ( Skim):**
```json
{
  "dashboard": {
    "title": "Nomad Cluster",
    "panels": [
      {
        "title": "Nomad Leader",
        "type": "stat",
        "targets": [
          {
            "expr": "nomad_raft_leader",
            "legendFormat": "{{ node_name }}"
          }
        ]
      },
      {
        "title": "Running Allocations",
        "type": "timeseries",
        "targets": [
          {
            "expr": "sum(nomad_client_allocations_running) by (node_name)",
            "legendFormat": "{{ node_name }}"
          }
        ]
      }
    ]
  }
}
```

**Импорт готового дашборда:**
- ID 12740 — Nomad Cluster Overview
- ID 12741 — Nomad Client Overview

### Сценарий 4: ACL-токен для Prometheus

```hcl
# nomad-metrics-policy.hcl
namespace "*" {
  policy       = "read"
  capabilities = ["read-job", "list-jobs", "list-allocations"]
}

node {
  policy = "read"
}

agent {
  policy = "read"
}

operator {
  policy = "read"
}
```

```bash
# Создание токена
nomad acl token create \
  -name="prometheus-metrics" \
  -policy="nomad-metrics-policy" \
  -type="client"
```

### Сценарий 5: Recording Rules для агрегации

**nomad-recording.yml:**
```yaml
groups:
  - name: nomad_recording
    interval: 30s
    rules:
      # Среднее CPU по кластеру
      - record: nomad:cluster:cpu_avg
        expr: avg(rate(nomad_client_allocations_cpu_total_ticks[5m]))

      # Общее потребление памяти
      - record: nomad:cluster:memory_total_rss_bytes
        expr: sum(nomad_client_allocations_memory_rss)

      # Количество запущенных аллокаций
      - record: nomad:cluster:allocations_running
        expr: sum(nomad_client_allocations_running)
```

## Диагностика

```bash
# Проверка метрик
curl -s http://localhost:4646/v1/metrics?format=prometheus | grep nomad_client

# Проверка nomad_sd в Prometheus
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="nomad")'

# Валидация правил
promtool check rules nomad-alerts.yml
```

## Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `no targets` | nomad_sd_configs не работает | Проверьте ACL-токен и доступность API |
| `permission denied` | Токен не имеет прав на чтение | Обновите ACL-политику |
| `high cardinality` | Слишком много метрик | Используйте relabel_configs для фильтрации |
| `scrape timeout` | Метрики не успевают собраться | Увеличьте scrape_interval |

## Дополнительная информация

- [Nomad — определения и базовые концепции](./definitions_and_concepts.md) — архитектура Nomad.
- [Prometheus: Service Discovery](../Prometheus/service_discovery_and_relabeling.md) — nomad_sd_configs.
- [Prometheus: Alerting Rules](../Prometheus/rules.md) — создание правил.
- [Grafana: Дашборды](../Grafana/grafana-dashboards.md) — настройка панелей.
