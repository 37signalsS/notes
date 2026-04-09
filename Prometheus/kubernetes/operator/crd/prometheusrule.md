# CRD PrometheusRule

## Definitions

**`kind: PrometheusRule`** — Custom Resource Definition в Prometheus Operator для декларативного описания alerting rules и recording rules. Operator преобразует PrometheusRule в ConfigMap, который монтируется в Prometheus Server.

**API version:** `monitoring.coreos.com/v1`

> **См. также:** [Правила Recording и Alerting](../../../rules.md) — общие концепции, синтаксис, состояния алертов.

## Basic Concepts

### Принцип работы

1. Пользователь создаёт PrometheusRule CRD с группами правил
2. Prometheus Operator преобразует CRD в ConfigMap в том же namespace
3. Operator обновляет `ruleFiles` в конфигурации Prometheus через Secret
4. `prometheus-config-reloader` перезагружает Prometheus
5. Prometheus вычисляет правила с заданным интервалом

### Связь с Prometheus CRD

Prometheus выбирает PrometheusRule CRD через селекторы:

```yaml
# В Prometheus CRD
spec:
  ruleSelector:
    matchLabels:
      release: monitoring        # Выборка по labelSelector
  ruleNamespaceSelector:
    matchNames:
      - monitoring               # Из каких namespace брать правила
```

Если `ruleSelector` не указан — Prometheus загружает все PrometheusRule из разрешённых namespace.

### Когда использовать PrometheusRule

| Сценарий | Решение |
|---|---|
| **Alerting rules** | Определение условий для алертов (CPU, memory, errors, latency) |
| **Recording rules** | Предварительное вычисление тяжёлых PromQL-запросов |
| **Мультикластерные правила** | Единый источник правил через GitOps |
| **Динамическое обновление** | Без перезагрузки Prometheus — Operator обновляет ConfigMap |

### Структура правил

Каждый PrometheusRule содержит одну или несколько групп (`groups`). Группа — это набор правил, выполняемых последовательно с общим интервалом.

```
PrometheusRule
  └── groups[]
        ├── name: "группа"
        ├── interval: "30s" (опционально)
        └── rules[]
              ├── alert: "имя" / record: "метрика"
              ├── expr: "PromQL"
              ├── for: "duration"  (только alerting)
              ├── labels: {}       (alerting + recording)
              └── annotations: {}  (только alerting)
```

> **Синтаксис правил** и состояния алертов (`Pending` → `Firing`) описаны в SSoT: [Правила Recording и Alerting](../../../rules.md).

## Practical Scenarios

### Базовый PrometheusRule с алертом

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
      interval: 30s
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

### Алерт на высокую загрузку CPU

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

### Алерт на недоступность пода

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

### Алерт на нехватку памяти

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

### Алерт на перезапуск контейнера

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

### Recording rule для агрегации

```yaml
- record: job:http_requests_total:rate5m
  expr: sum(rate(http_requests_total[5m])) by (job)
```

### Несколько групп правил в одном CRD

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: platform-rules
  namespace: monitoring
  labels:
    release: monitoring
spec:
  groups:
    - name: application-alerts
      interval: 30s
      rules:
        - alert: HighErrorRate
          expr: rate(http_requests_total{status="500"}[5m]) > 0.1
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "High error rate detected"
    - name: infrastructure-alerts
      interval: 1m
      rules:
        - alert: HighCPUUsage
          expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "High CPU usage on {{ $labels.instance }}"
    - name: recording-rules
      rules:
        - record: job:http_requests_total:rate5m
          expr: sum(rate(http_requests_total[5m])) by (job)
```

## Additional Information

### Основные параметры spec

| Параметр | Описание | Пример |
|---|---|---|
| **`groups`** | Список групп правил | См. ниже |
| **`groups[].name`** | Имя группы | `my-app-alerts` |
| **`groups[].interval`** | Интервал вычисления | `30s`, `1m` (опционально) |
| **`groups[].rules`** | Список правил в группе | См. ниже |

### Параметры alerting rules

| Параметр | Описание | Пример |
|---|---|---|
| **`alert`** | Имя алерта | `HighErrorRate` |
| **`expr`** | PromQL выражение | `rate(http_requests_total[5m]) > 0.1` |
| **`for`** | Время срабатывания | `5m`, `1h` |
| **`labels`** | Лейблы алерта | `severity: warning` |
| **`annotations`** | Аннотации алерта | `summary`, `description` |

### Параметры recording rules

| Параметр | Описание | Пример |
|---|---|---|
| **`record`** | Имя записываемой метрики | `job:http_requests_total:rate5m` |
| **`expr`** | PromQL выражение | `sum(rate(http_requests_total[5m])) by (job)` |
| **`labels`** | Лейблы для метрики | `{aggregation: "rate5m"}` |

### Валидация правил

```bash
# Проверка синтаксиса
promtool check rules prometheusrule.yaml

# Просмотр загруженных правил
kubectl get prometheusrule -n monitoring

# Проверка в Prometheus UI
# Status → Rules
```

> **См. также:** [promtool и лучшие практики](../../../promtool_and_best_practices.md).

### Связанные CRD и компоненты

- [Prometheus CRD](./prometheus.md) — описание экземпляра Prometheus, `ruleSelector`
- [Alertmanager CRD](./alertmanager.md) — маршрутизация алертов
- [AlertmanagerConfig](./alertmanagerconfig.md) — конфигурация получателей
- [Alerting rules — примеры](../../../concepts/metric_types/alerts.md) — алерты для Counter, Gauge, Histogram
