# Reloader — Интеграция с Prometheus и Grafana

## Определения

**Мониторинг Reloader через Prometheus** — настройка сбора метрик, алертинга и визуализации для контроля состояния контроллера автоматической перезагрузки конфигураций.

**Основной источник:** [Мониторинг и лучшие практики Reloader](./reloader_monitoring_and_best_practices.md)

---

## ServiceMonitor

### Базовый ServiceMonitor

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: reloader
  namespace: reloader-system
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app: reloader
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
      honorLabels: true
```

### ServiceMonitor с фильтрацией

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: reloader-filtered
  namespace: reloader-system
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app: reloader
  namespaceSelector:
    matchNames:
      - reloader-system
  endpoints:
    - port: http
      path: /metrics
      interval: 15s
      scrapeTimeout: 10s
      honorLabels: true
      metricRelabelings:
        # Фильтрация ненужных метрик
        - sourceLabels: [__name__]
          regex: "go_.*"
          action: drop
```

---

## PrometheusRule (Alerting)

### Полный набор правил алертинга

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: reloader-alerts
  namespace: reloader-system
  labels:
    release: prometheus-stack
spec:
  groups:
    - name: reloader
      rules:
        # Критические алерты
        - alert: ReloaderNotReady
          expr: |
            kube_deployment_status_replicas_available{namespace="reloader-system",deployment="reloader"} == 0
          for: 1m
          labels:
            severity: critical
          annotations:
            summary: "Reloader не готов"
            description: "Reloader в namespace {{ $labels.namespace }} не имеет доступных реплик"

        - alert: ReloaderHighErrorRate
          expr: |
            sum(rate(reloader_failure_reload_total[5m])) / sum(rate(reloader_success_reload_total[5m])) > 0.1
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Критический уровень ошибок Reloader"
            description: "Reloader в namespace {{ $labels.namespace }} имеет уровень ошибок > 10%"

        # Предупреждения
        - alert: ReloaderHighMemoryUsage
          expr: |
            container_memory_working_set_bytes{namespace="reloader-system",container="reloader"} /
            container_spec_memory_limit_bytes{namespace="reloader-system",container="reloader"} > 0.8
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Высокое потребление памяти Reloader"
            description: "Reloader использует > 80% памяти"

        - alert: ReloaderHighCPUUsage
          expr: |
            rate(container_cpu_usage_seconds_total{namespace="reloader-system",container="reloader"}[5m]) * 1000 >
            container_spec_cpu_quota{namespace="reloader-system",container="reloader"} / container_spec_cpu_period{namespace="reloader-system",container="reloader"} * 1000 * 0.8
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Высокое потребление CPU Reloader"
            description: "Reloader использует > 80% CPU"

        - alert: ReloaderWorkqueueDepthHigh
          expr: |
            workqueue_depth{namespace="reloader-system"} > 100
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Глубокая очередь задач Reloader"
            description: "Очередь задач Reloader имеет > 100 элементов"

        - alert: ReloaderReconcileErrors
          expr: |
            sum(rate(reloader_reconcile_errors_total[5m])) by (namespace) > 0
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Ошибки согласования Reloader"
            description: "Reloader в namespace {{ $labels.namespace }} имеет ошибки согласования"

        - alert: ReloaderHighReconcileLatency
          expr: |
            histogram_quantile(0.95, sum(rate(reloader_reconcile_duration_seconds_bucket[5m])) by (le)) > 5
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Высокая латентность согласования"
            description: "95-й перцентиль времени согласования > 5 секунд"

        # Информационные
        - alert: ReloaderConfigChangeDetected
          expr: |
            increase(reloader_success_reload_total[5m]) > 0
          labels:
            severity: info
          annotations:
            summary: "Обнаружено изменение конфигурации"
            description: "Reloader выполнил {{ $value }} перезапусков за последние 5 минут"
```

### Записи правил (Recording Rules)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: reloader-recording-rules
  namespace: reloader-system
  labels:
    release: prometheus-stack
spec:
  groups:
    - name: reloader-recording
      interval: 30s
      rules:
        # Уровень успеха перезапусков
        - record: reloader:reload_success_rate:ratio_rate5m
          expr: |
            sum(rate(reloader_success_reload_total[5m])) /
            sum(rate(reloader_success_reload_total[5m]) + rate(reloader_failure_reload_total[5m]))

        # Среднее время согласования
        - record: reloader:reconcile_duration_seconds:p95_rate5m
          expr: |
            histogram_quantile(0.95, sum(rate(reloader_reconcile_duration_seconds_bucket[5m])) by (le))

        # Количество отслеживаемых ресурсов по namespace
        - record: reloader:watched_resources:sum_by_namespace
          expr: sum(reloader_watched_resources) by (namespace)

        # Глубина очереди
        - record: reloader:workqueue_depth:current
          expr: workqueue_depth{namespace="reloader-system"}
```

---

## Grafana Dashboard

### Основные панели

#### 1. Overview

| Панель | Метрика | Описание |
| :--- | :--- | :--- |
| Tracked Resources | `reloader_watched_resources` | Количество отслеживаемых ресурсов |
| Successful Reloads | `rate(reloader_success_reload_total[5m])` | Успешные перезапуски в секунду |
| Failed Reloads | `rate(reloader_failure_reload_total[5m])` | Ошибки перезапусков в секунду |
| Workqueue Depth | `workqueue_depth` | Глубина очереди задач |

#### 2. Performance

| Панель | Метрика | Описание |
| :--- | :--- | :--- |
| Reconcile Latency (p50) | `histogram_quantile(0.5, ...)` | Медианное время согласования |
| Reconcile Latency (p95) | `histogram_quantile(0.95, ...)` | 95-й перцентиль времени согласования |
| Reconcile Latency (p99) | `histogram_quantile(0.99, ...)` | 99-й перцентиль времени согласования |
| Reload Duration | `histogram_quantile(0.5, reloader_reload_duration_seconds_bucket)` | Время перезапуска |

#### 3. Resources

| Панель | Метрика | Описание |
| :--- | :--- | :--- |
| CPU Usage | `rate(container_cpu_usage_seconds_total{container="reloader"}[5m])` | Потребление CPU |
| Memory Usage | `container_memory_working_set_bytes{container="reloader"}` | Потребление памяти |
| Network I/O | `rate(container_network_receive_bytes_total{namespace="reloader-system"}[5m])` | Сетевой трафик |

#### 4. Business

| Панель | Метрика | Описание |
| :--- | :--- | :--- |
| Reloads by Namespace | `sum(rate(reloader_success_reload_total[5m])) by (namespace)` | Перезапуски по namespace |
| Reloads by Type | `sum(rate(reloader_success_reload_total[5m])) by (resource_type)` | Перезапуски по типу ресурса |
| Reload Frequency | `increase(reloader_success_reload_total[1h])` | Частота перезапусков за час |

### Пример queries для Grafana

```promql
# Количество перезапусков в секунду
sum(rate(reloader_success_reload_total[5m])) by (namespace)

# Процент ошибок
sum(rate(reloader_failure_reload_total[5m])) / sum(rate(reloader_success_reload_total[5m])) * 100

# Среднее время согласования
histogram_quantile(0.5, sum(rate(reloader_reconcile_duration_seconds_bucket[5m])) by (le))

# 95-й перцентиль времени согласования
histogram_quantile(0.95, sum(rate(reloader_reconcile_duration_seconds_bucket[5m])) by (le))

# Количество отслеживаемых ресурсов
sum(reloader_watched_resources) by (namespace)

# Глубина очереди
workqueue_depth{namespace="reloader-system"}

# Уровень успеха перезапусков
sum(rate(reloader_success_reload_total[5m])) /
(sum(rate(reloader_success_reload_total[5m])) + sum(rate(reloader_failure_reload_total[5m])))

# Перезапуски за последний час
increase(reloader_success_reload_total[1h])

# Среднее время обработки событий
histogram_quantile(0.5, sum(rate(reloader_event_processing_duration_seconds_bucket[5m])) by (le))
```

### Импорт дашбордов

1. **Официальные дашборды:**
   - [GitHub: Stakater/Reloader/dashboards](https://github.com/stakater/Reloader/tree/master/dashboards)
   - Импорт JSON-файла в Grafana → Dashboards → Import

2. **Создание собственного дашборда:**
   - Grafana → Dashboards → New Dashboard
   - Добавить панели с указанными выше queries
   - Настроить переменные: `$namespace`, `$interval`

3. **Рекомендуемые переменные:**

```json
{
  "name": "namespace",
  "type": "query",
  "query": "label_values(reloader_watched_resources, namespace)",
  "refresh": 2,
  "multi": true,
  "includeAll": true
}
```

---

## Проверка работоспособности мониторинга

### Проверка ServiceMonitor

```bash
# 1. Проверка создания ServiceMonitor
kubectl get servicemonitor -n reloader-system

# 2. Проверка конфигурации
kubectl get servicemonitor reloader -n reloader-system -o yaml

# 3. Проверка в Prometheus
# → result: В Prometheus должен появиться target с job="reloader"

# 4. Проверка метрик
curl -s http://localhost:9090/metrics | grep reloader_
```

### Проверка алертинга

```bash
# 1. Проверка PrometheusRule
kubectl get prometheusrule -n reloader-system

# 2. Проверка правил в Prometheus
# → result: В Prometheus → Alerts должны появиться правила reloader:*

# 3. Тестирование алерта (временно)
kubectl patch deployment reloader -n reloader-system -p '{"spec":{"template":{"spec":{"containers":[{"name":"reloader","resources":{"limits":{"memory":"1Mi"}}}]}}}}'
```

---

## См. также

- [Мониторинг и лучшие практики](./reloader_monitoring_and_best_practices.md)
- [Практические сценарии использования](./reloader_usage_scenarios.md)
- [GitHub: Дашборды Grafana](https://github.com/stakater/Reloader/tree/master/dashboards)
- [Prometheus Operator: Концепции](../../Prometheus/kubernetes/operator/concepts.md)
