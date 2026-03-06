# CRD PrometheusRule

## Определения

**`kind: PrometheusRule`** — Custom Resource Definition для описания правил алертинга и записи (recording rules).

## Пример конфигурации

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: my-app-rules
  namespace: monitoring
  labels:
    release: monitoring
spec:
  groups:
    - name: my-app-alerts
      rules:
        - alert: HighErrorRate
          expr: rate(http_requests_total{status="500"}[5m]) > 0.1
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "High error rate detected"
            description: "Error rate is {{ $value }} errors/sec"
```

## Основные параметры spec

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`groups`** | Список групп правил | См. ниже |

## Параметры групп правил

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`name`** | Имя группы | `my-app-alerts` |
| **`interval`** | Интервал вычисления | `30s`, `1m` |
| **`rules`** | Список правил в группе | См. ниже |

## Параметры правил

### Alerting rules

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`alert`** | Имя алерта | `HighErrorRate` |
| **`expr`** | PromQL выражение | `rate(http_requests_total[5m]) > 0.1` |
| **`for`** | Время срабатывания | `5m`, `1h` |
| **`labels`** | Лейблы алерта | `severity: warning` |
| **`annotations`** | Аннотации алерта | `summary`, `description` |

### Recording rules

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`record`** | Имя записываемой метрики | `job:http_requests_total:rate5m` |
| **`expr`** | PromQL выражение | `sum(rate(http_requests_total[5m])) by (job)` |
| **`labels`** | Лейблы для метрики | `{aggregation: "rate5m"}` |

## Примеры правил

### 1. Алерт на высокую загрузку CPU

```yaml
- alert: HighCPUUsage
  expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "High CPU usage on {{ $labels.instance }}"
    description: "CPU usage is above 80% for more than 10 minutes"
```

### 2. Алерт на недоступность пода

```yaml
- alert: PodDown
  expr: up{job="kubernetes-pods"} == 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Pod {{ $labels.pod }} is down"
    description: "Pod {{ $labels.pod }} in namespace {{ $labels.namespace }} has been down for more than 5 minutes"
```

### 3. Recording rule для агрегации

```yaml
- record: job:http_requests_total:rate5m
  expr: sum(rate(http_requests_total[5m])) by (job)
```

### 4. Алерт на нехватку памяти

```yaml
- alert: HighMemoryUsage
  expr: (1 - (sum(container_memory_usage_bytes{container!=""}) by (pod) / sum(container_spec_memory_limit_bytes{container!=""}) by (pod))) * 100 > 90
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High memory usage on pod {{ $labels.pod }}"
    description: "Memory usage is above 90% of limit"
```

### 5. Алерт на перезапуск контейнера

```yaml
- alert: ContainerRestarted
  expr: increase(kube_pod_container_status_restarts_total[1h]) > 3
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Container {{ $labels.container }} restarted {{ $value }} times"
    description: "Container {{ $labels.container }} in pod {{ $labels.pod }} has restarted more than 3 times in the last hour"
```

## Группировка правил

```yaml
spec:
  groups:
    - name: application-alerts
      interval: 30s
      rules:
        - alert: HighErrorRate
          # ...
    - name: infrastructure-alerts
      interval: 1m
      rules:
        - alert: HighCPUUsage
          # ...
    - name: recording-rules
      rules:
        - record: job:http_requests_total:rate5m
          # ...
```

## Селектор Prometheus

Prometheus выбирает PrometheusRule по селектору:

```yaml
# В Prometheus CRD
spec:
  ruleSelector:
    matchLabels:
      release: monitoring
  ruleNamespaceSelector:
    matchNames:
      - monitoring
```

## Связанные темы

* **[Prometheus CRD](./prometheus.md)** — описание Prometheus
* **[Alertmanager CRD](./alertmanager.md)** — описание Alertmanager
* **[Rules](../../../rules.md)** — базовая настройка правил
* **[AlertmanagerConfig](./alertmanagerconfig.md)** — маршрутизация алертов
