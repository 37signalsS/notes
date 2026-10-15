# Самомониторинг Prometheus (Self-Monitoring)

## Определения

**Self-Monitoring (Meta-Monitoring)** — практика мониторинга самого стека мониторинга. Включает сбор метрик от Prometheus, Alertmanager, Grafana и связанных компонентов для обнаружения проблем с самой системой наблюдаемости до того, как они повлияют на бизнес-сервисы.

**Встроенные метрики (Built-in Metrics)** — Prometheus экспортирует собственные внутренние метрики через эндпоинт `/metrics`. Основные группы: `prometheus_engine_*` (запросы, вычисления), `prometheus_tsdb_*` (хранилище), `prometheus_remote_storage_*` (отправка данных).

**SLI стека мониторинга** — Service Level Indicators, специфичные для инфраструктуры наблюдаемости: доступность API Prometheus, задержка PromQL-запросов, целостность данных, время реакции Alertmanager.

> **См. также:** [Prometheus CRD](./kubernetes/operator/crd/prometheus.md), [Alertmanager CRD](./kubernetes/operator/crd/alertmanager.md), [PrometheusRule CRD](./kubernetes/operator/crd/prometheusrule.md).

## Базовые концепции

### Зачем мониторить сам Prometheus

Если Prometheus падает или деградирует, вы теряете видимость всех сервисов. Self-monitoring решает:

1. **Обнаружение проблем до пользователей** — алерт на `prometheus_tsdb_head_series` предупредит о взрыве кардинальности до OOM
2. **Валидация конфигурации** — метрики `prometheus_config_last_reload_successful` показывают, применилась ли конфигурация
3. **Мониторинг производительности** — отслеживание latencies запросов, использования памяти, состояния WAL
4. **Обеспечение SLO стека мониторинга** — SLI для Prometheus: доступность API, целостность данных, задержка алертов

### Архитектура самомониторинга

```
[Prometheus] --> [/metrics] --> [Prometheus (self-scrape)]
       |                              |
       |                              v
       |                        [Alertmanager] --> [Alerts]
       v
[Grafana Dashboard]
```

Prometheus скрейпит сам себя через внутренний эндпоинт `/metrics`. Это создает замкнутую петлю: мониторинг мониторит сам себя. При использовании Operator CRD self-scrape описывается через `ServiceMonitor`, указывающий на сервис Prometheus.

### Ключевые метрики для self-monitoring

| Группа метрик | Что отслеживает | Критичность |
|:---|:---|:---|
| `prometheus_engine_query_duration_seconds` | Задержка PromQL запросов | Высокая |
| `prometheus_tsdb_head_series` | Количество активных серий | Критическая |
| `prometheus_tsdb_head_chunks` | Количество чанков в памяти | Высокая |
| `prometheus_tsdb_storage_blocks_bytes` | Размер хранилища на диске | Средняя |
| `prometheus_remote_storage_samples_total` | Отправленные сэмплы через remote_write | Высокая |
| `prometheus_remote_storage_queue_length` | Длина очереди remote_write | Критическая |
| `prometheus_config_last_reload_successful` | Успешность перезагрузки конфигурации | Критическая |
| `prometheus_notifications_sent_total` | Отправленные уведомления | Средняя |
| `prometheus_rule_evaluation_duration_seconds` | Время вычисления правил | Высокая |
| `prometheus_rule_group_last_duration_seconds` | Длительность последнего вычисления группы | Средняя |
| `process_resident_memory_bytes` | Фактическое потребление RAM | Высокая |
| `prometheus_tsdb_head_max_time_seconds` | Свежесть данных (отставание от текущего времени) | Высокая |

### SLI для стека мониторинга

| SLI | Формула | Цель (Target) |
|:---|:---|:---|
| Доступность API | `avg_over_time(up{job="prometheus"}[5m])` | 99.9% |
| Задержка PromQL | `histogram_quantile(0.99, rate(prometheus_engine_query_duration_seconds_bucket[5m]))` | < 1s |
| Свежесть данных | `time() - prometheus_tsdb_head_max_time_seconds` | < 2m |
| Доставка алертов | `rate(prometheus_notifications_sent_total[5m]) / rate(prometheus_notifications_received_total[5m])` | > 0.99 |
| Remote Write лаг | `prometheus_remote_storage_queue_length` | < 10000 |

## Практические сценарии

### Сценарий 1: ServiceMonitor для self-scrape

Сбор метрик самого Prometheus через Operator:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: prometheus-self-monitoring
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: prometheus
  namespaceSelector:
    matchNames:
      - monitoring
  endpoints:
    - port: web
      interval: 15s
      path: /metrics
```

### Сценарий 2: Алерты на здоровье Prometheus

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: prometheus-health-alerts
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  groups:
    - name: prometheus-health
      rules:
        - alert: PrometheusDown
          expr: up{job="prometheus"} == 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Prometheus недоступен"
            runbook_url: "https://wiki.internal/runbooks/prometheus-down"

        - alert: PrometheusHighMemoryUsage
          expr: process_resident_memory_bytes{job="prometheus"} / on() group() prometheus_tsdb_storage_blocks_bytes > 2
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Prometheus потребляет много памяти"

        - alert: PrometheusCardinalityExplosion
          expr: prometheus_tsdb_head_series > 10000000
          for: 15m
          labels:
            severity: critical
          annotations:
            summary: "Кардинальность метрик превысила 10M серий"

        - alert: PrometheusRemoteWriteBehind
          expr: prometheus_remote_storage_queue_length > 100000
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Очередь remote_write переполнена"

        - alert: PrometheusConfigReloadFailed
          expr: prometheus_config_last_reload_successful == 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Перезагрузка конфигурации Prometheus не удалась"

        - alert: PrometheusDataStale
          expr: time() - prometheus_tsdb_head_max_time_seconds > 300
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Данные Prometheus устарели более чем на 5 минут"
```

### Сценарий 3: Алерты на Alertmanager

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: alertmanager-health-alerts
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  groups:
    - name: alertmanager-health
      rules:
        - alert: AlertmanagerDown
          expr: up{job="alertmanager"} == 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Alertmanager недоступен"
            runbook_url: "https://wiki.internal/runbooks/alertmanager-down"

        - alert: AlertmanagerClusterIncomplete
          expr: alertmanager_cluster_members < 3
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Кластер Alertmanager неполный: {{ $value }} из 3"

        - alert: AlertmanagerNotificationFailing
          expr: rate(alertmanager_notifications_failed_total[5m]) > 0
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Уведомления Alertmanager не доставляются"
```

### Сценарий 4: Алерты на правила

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: prometheus-rules-health
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  groups:
    - name: prometheus-rules-health
      rules:
        - alert: PrometheusRuleEvaluationFailures
          expr: rate(prometheus_rule_evaluation_failures_total[5m]) > 0
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Ошибки вычисления правил Prometheus"

        - alert: PrometheusRuleSlowEvaluation
          expr: prometheus_rule_group_last_duration_seconds > 60
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "Группа правил вычисляется дольше 60 секунд"

        - alert: PrometheusScrapeTooSlow
          expr: prometheus_target_interval_length_seconds{quantile="0.99"} > 60
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Скрейпинг целей замедлился"
```

### Сценарий 5: Recording rules для self-monitoring

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: prometheus-self-recording
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  groups:
    - name: prometheus-recording
      interval: 1m
      rules:
        - record: prometheus:availability:hourly
          expr: 1 - (sum_over_time(up{job="prometheus"}[1h]) / count_over_time(up{job="prometheus"}[1h]))

        - record: prometheus:query_latency:p99
          expr: histogram_quantile(0.99, rate(prometheus_engine_query_duration_seconds_bucket[5m]))

        - record: prometheus:tsdb_head_series:count
          expr: prometheus_tsdb_head_series

        - record: prometheus:remote_write:queue_length:max
          expr: max_over_time(prometheus_remote_storage_queue_length[5m])
```

### Сценарий 6: Мониторинг config-reloader

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: config-reloader-health
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  groups:
    - name: config-reloader
      rules:
        - alert: ConfigReloaderErrors
          expr: rate(config_reloader_errors_total[5m]) > 0
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Config-reloader обнаруживает ошибки"
            description: "Контейнер config-reloader в {{ $labels.pod }} сообщает об ошибках при перезагрузке конфигурации"
```

## Дополнительная информация

### Диагностика проблем self-monitoring

| Симптом | Вероятная причина | Диагностика |
|:---|:---|:---|
| `up{job="prometheus"} == 0` | Под Prometheus не запущен или порт недоступен | `kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus` |
| `prometheus_tsdb_head_series` растет | Взрыв кардинальности метрик | `curl -s localhost:9090/api/v1/label/__name__/values | wc -l`; кардинальность по job: `count by (job) ({__name__=~".+"})` |
| `prometheus_remote_storage_queue_length` растет | LTS недоступен, сеть | `kubectl logs -n monitoring prometheus-main-0 | grep remote` |
| `prometheus_config_last_reload_successful == 0` | Ошибка в prometheus.yaml | `promtool check config prometheus.yaml` |
| `prometheus_rule_evaluation_failures_total > 0` | Ошибка в PromQL правиле | `promtool check rules rules.yaml` |
| Высокий `process_resident_memory_bytes` | Много активных серий, нет compaction | Проверьте `goGC`, увеличьте ресурсы |

### Лучшие практики

1. **Разделяйте self-monitoring правила** в отдельный `PrometheusRule` для изоляции от бизнес-правил
2. **Используйте `for: 5m+`** для всех self-monitoring алертов, чтобы избежать ложных срабатываний при кратковременных просадках
3. **Настройте `runbook_url`** для каждого алерта — инженер должен знать, что делать
4. **Не мониторьте self-monitoring через тот же Prometheus**, если критична Availability — используйте внешний Prometheus или Pushgateway для критических алертов
5. **Храните recording rules** для self-monitoring в отдельной группе с `interval: 1m` для минимизации нагрузки
6. **Мониторьте Grafana** аналогично: настройте `ServiceMonitor` для метрик `grafana_*` (см. [grafana_integration.md](./kubernetes/operator/grafana_integration.md))

### Мета-мониторинг в kube-prometheus-stack

При использовании Helm-чарта `kube-prometheus-stack` базовый self-monitoring настраивается автоматически через значения:

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    scrapeSelfMonitor: true

# По умолчанию включены ServiceMonitor для:
# - prometheus (метрики Prometheus)
# - alertmanager (метрики Alertmanager)
# - kube-state-metrics (метрики Kubernetes)
# - node-exporter (метрики узлов)
# - grafana (метрики Grafana)
```

### Связанные темы

- [Prometheus CRD](./kubernetes/operator/crd/prometheus.md) — конфигурация сервера Prometheus
- [Alertmanager CRD](./kubernetes/operator/crd/alertmanager.md) — развёртывание Alertmanager
- [Grafana Integration](./kubernetes/operator/grafana_integration.md) — интеграция с Grafana
- [PromQL troubleshooting](./concepts/promql/troubleshooting.md) — диагностика запросов
- [Capacity Planning](../Concepts/capacity-planning.md) — планирование ресурсов
