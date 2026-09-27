# Alert Rules: практические примеры для продакшена

## Определения

**Alerting Rule** — правило, определяющее условие (PromQL-выражение), при выполнении которого Prometheus генерирует алерт и отправляет его в Alertmanager.

**For** — время ожидания перед переходом алерта в состояние `Firing`. Рекомендация: `>= 3-5 × evaluation_interval`.

**Keep Firing For** — (v2.42+) время удержания алерта в `Firing` после нормализации метки. Предотвращает дребезг.

> **См. также:** [Alerting Rules — теория](../concepts/alerting_rules.md); [Alertmanager — установка](./alertmanager_installation.md); [Правила](../rules.md) — recording и alerting rules.

## Основные концепции

### Структура alerting rule

```yaml
groups:
  - name: group_name
    interval: 30s          # Интервал вычисления (по умолчанию = evaluation_interval)
    rules:
      - alert: AlertName           # Уникальное имя алерта
        expr: PromQL expression    # Условие срабатывания
        for: 5m                    # Время ожидания перед Firing
        keep_firing_for: 10m       # Удержание после нормализации
        labels:
          severity: critical       # Метка для маршрутизации в Alertmanager
        annotations:
          summary: "Краткое описание"     # Для уведомлений
          description: "Подробности"      # Дополнительная информация
          runbook_url: "https://..."      # Ссылка на инструкцию
```

### Принципы хорошего алертинга

1. **Symptom-based, не cause-based** — алертьте на последствия (ошибки, задержки), а не на причины (CPU, RAM).
2. **Каждый алерт — actionable** — если на алерт нельзя отреагировать, это не алерт, а шум.
3. **Runbook обязателен** — каждая аннотация `runbook_url` ссылается на инструкцию по устранению.
4. **Адекватный `for`** — не слишком короткий (ложные срабатывания), не слишком длинный (задержка реакции).
5. **Severity** — строго классифицирован: `critical`, `warning`, `info`.

## Практические примеры

### 1. Инфраструктурные алерты (Node Exporter)

```yaml
groups:
  - name: infrastructure_alerts
    rules:
      # Сервис недоступен
      - alert: InstanceDown
        expr: up == 0
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "Instance {{ $labels.instance }} down"
          description: "{{ $labels.job }} on {{ $labels.instance }} is unreachable for 3+ minutes."
          runbook_url: "https://wiki.corp.local/runbooks/instance-down"

      # Высокое использование CPU
      - alert: HighCpuUsage
        expr: |
          100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "High CPU on {{ $labels.instance }}"
          description: "CPU usage is {{ $value | printf \"%.1f\" }}% for 15+ minutes."

      # Мало свободной памяти
      - alert: LowMemory
        expr: |
          (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 < 10
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Low memory on {{ $labels.instance }}"
          description: "Available memory is {{ $value | printf \"%.1f\" }}%."

      # Диск заполняется
      - alert: DiskSpaceLow
        expr: |
          (node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes) * 100 < 15
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Low disk space on {{ $labels.instance }}"
          description: "Filesystem {{ $labels.mountpoint }} has {{ $value | printf \"%.1f\" }}% free."

      # Диск критически полон
      - alert: DiskSpaceCritical
        expr: |
          (node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes) * 100 < 5
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "CRITICAL: Disk nearly full on {{ $labels.instance }}"
          description: "Filesystem {{ $labels.mountpoint }} has only {{ $value | printf \"%.1f\" }}% free."

      # Высокий I/O диска
      - alert: HighDiskIOWait
        expr: |
          rate(node_cpu_seconds_total{mode="iowait"}[5m]) * 100 > 20
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "High disk I/O wait on {{ $labels.instance }}"
          description: "I/O wait is {{ $value | printf \"%.1f\" }}%."
```

### 2. Прикладные алерты (HTTP-сервисы)

```yaml
groups:
  - name: application_alerts
    rules:
      # Высокий error rate (5xx)
      - alert: HighHttpErrorRate
        expr: |
          sum by (job, instance) (rate(http_requests_total{status=~"5.."}[5m]))
          /
          sum by (job, instance) (rate(http_requests_total[5m])) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate on {{ $labels.job }}@{{ $labels.instance }}"
          description: "5xx error rate is {{ $value | printf \"%.2f\" }}%."
          runbook_url: "https://wiki.corp.local/runbooks/high-error-rate"

      # Высокая задержка (p99)
      - alert: HighLatency
        expr: |
          histogram_quantile(0.99,
            sum by (job, le) (rate(http_request_duration_seconds_bucket[5m]))
          ) > 2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High p99 latency for {{ $labels.job }}"
          description: "p99 latency is {{ $value | printf \"%.2f\" }}s."

      # Сервис полностью недоступен
      - alert: ServiceUnavailable
        expr: up{job=~"api-.*|web-.*"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Service {{ $labels.job }} is DOWN"
          description: "Service {{ $labels.job }} on {{ $labels.instance }} is unreachable."

      # Слишком много запросов (potential DoS)
      - alert: HighRequestRate
        expr: |
          sum by (job) (rate(http_requests_total[5m])) > 1000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High request rate for {{ $labels.job }}"
          description: "{{ $value | printf \"%.0f\" }} req/s."
```

### 3. Алерты на Prometheus (self-monitoring)

```yaml
groups:
  - name: prometheus_alerts
    rules:
      # Prometheus недоступен
      - alert: PrometheusDown
        expr: up{job="prometheus"} == 0
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "Prometheus {{ $labels.instance }} is DOWN"
          description: "Prometheus instance is unreachable."

      # Конфигурация не применилась
      - alert: PrometheusConfigReloadFailed
        expr: prometheus_config_last_reload_successful == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Prometheus config reload failed"
          description: "Last config reload was unsuccessful."

      # Много активных серий (cardinality explosion)
      - alert: PrometheusHighActiveSeries
        expr: prometheus_tsdb_head_series > 1000000
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "High active series count: {{ $value }}"
          description: "Active series exceed 1M. Check for cardinality explosion."

      # Данные устарели
      - alert: PrometheusDataStale
        expr: time() - prometheus_tsdb_head_max_time_seconds > 300
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Prometheus data is stale"
          description: "Latest data is {{ $value | printf \"%.0f\" }}s old."

      # Очередь remote_write переполнена
      - alert: PrometheusRemoteWriteQueueBacklog
        expr: prometheus_remote_storage_queue_length > 10000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Remote write queue backlog"
          description: "Queue length is {{ $value }}."

      # Высокое время вычисления правил
      - alert: PrometheusRuleEvaluationSlow
        expr: |
          prometheus_rule_group_last_duration_seconds
          / prometheus_rule_group_interval_seconds > 0.9
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Rule evaluation taking too long"
          description: "Rule group {{ $labels.rule_group }} is taking {{ $value | printf \"%.1f\" }}x of its interval."
```

### 4. Алерты на Alertmanager

```yaml
groups:
  - name: alertmanager_alerts
    rules:
      # Alertmanager недоступен
      - alert: AlertmanagerDown
        expr: up{job="alertmanager"} == 0
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "Alertmanager {{ $labels.instance }} is DOWN"

      # Уведомления не доставляются
      - alert: AlertmanagerNotificationsFailing
        expr: |
          rate(alertmanager_notifications_failed_total[5m]) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Alertmanager notifications failing"
          description: "Failed notifications detected."
          runbook_url: "https://wiki.corp.local/runbooks/alertmanager-notifications-failing"
```

### 5. Recording Rules (для оптимизации алертов)

```yaml
groups:
  - name: recording_rules
    interval: 30s
    rules:
      # Утилизация CPU
      - record: node:cpu_utilization:ratio
        expr: |
          1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))

      # Использование памяти
      - record: node:memory_utilization:ratio
        expr: |
          1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)

      # Error rate
      - record: job:http_requests_error_ratio:rate5m
        expr: |
          sum by (job) (rate(http_requests_total{status=~"5.."}[5m]))
          /
          sum by (job) (rate(http_requests_total[5m]))

      # Latency p99
      - record: job:http_request_duration_p99:histogram_quantile
        expr: |
          histogram_quantile(0.99,
            sum by (job, le) (rate(http_request_duration_seconds_bucket[5m]))
          )
```

## Валидация правил

```bash
# Проверка синтаксиса
promtool check rules /etc/prometheus/alerting_rules.yml
# → SUCCESS: 12 rules found

# Тестирование конкретного правила
promtool test rules /etc/prometheus/rules_test.yml

# Проверка что правила загружены
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[].rules[] | select(.type=="alerting") | .name'
```

## Рекомендации SRE

1. **`for: 5m+`** — минимальное значение для production. Меньше 3 минут = ложные срабатывания.
2. **`runbook_url` обязателен** — без него алерт бесполезен в 3 часа ночи.
3. **Severity строго классифицирован:** `critical` = телефон звонит, `warning` = в рабочее время, `info` = только в дашборде.
4. **Не дублируйте алерты** — один симптом = один алерт. Не мониторьте CPU и RAM одного сервиса дважды.
5. **Recording rules для сложных запросов** — вычисляйте заранее, не в alerting rules.
6. **Тестируйте rules** — используйте `promtool test rules` перед деплоем.

## См. также

*   **[Alerting Rules — теория](../concepts/alerting_rules.md)** — жизненный цикл, параметры, шаблоны.
*   **[Recording Rules](../concepts/recording_rules.md)** — правила записи для оптимизации.
*   **[Alertmanager — установка](./alertmanager_installation.md)** — настройка доставки уведомлений.
*   **[Self-Monitoring](../self_monitoring.md)** — мониторинг самого Prometheus.
