# Loki — Alerting (Ruler и LogQL-алерты)

## Определения

**Loki Ruler** — компонент Loki, выполняющий LogQL-запросы как правила (recording rules и alerting rules) на расписании. Результаты recording rules записываются обратно в Loki как временные ряды, а alerting rules отправляют алерты в Alertmanager.

**Recording Rule** — правило Loki, вычисляющее агрегированное значение (count, sum, rate) по LogQL-запросу и сохраняющее результат как новую метрику. Используется для ускорения дашбордов и снижения нагрузки при визуализации.

**Alerting Rule** — правило Loki, мониторящее LogQL-выражение и отправляющее алерт в Alertmanager при выполнении условия (threshold). Поддерживает `for` для стабильности и labels для маршрутизации.

**LogQL Alerting Pipeline** — цепочка: LogQL-запрос → evaluation interval → condition check → Alertmanager → notification channel (Slack, PagerDuty, webhook).

---

## Основные концепции

### Архитектура Loki Alerting

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐
│  Loki Ruler  │────▶│  Alertmanager│────▶│  Notification│
│  (LogQL)     │     │  (routing)   │     │  (Slack/PD)  │
└─────────────┘     └─────────────┘     └──────────────┘
       │
       ▼
┌─────────────┐
│   Loki      │
│   (queries) │
└─────────────┘
```

### Когда использовать LogQL-алерты vs Metrics-алерты

| Сценарий | LogQL Alerting | Prometheus Alerting |
| :--- | :--- | :--- |
| Ошибки в логах (HTTP 5xx) | **Да** | Нет (нет метрик) |
| Аномальные паттерны логов | **Да** | Нет |
| Медленные запросы (latency) | Через log labels | **Да** (из метрик) |
| Мониторинг метрик | Нет | **Да** |
| Структурированные логи с labels | **Да** | Опционально |

### Компонент Ruler вopsis:

**modes:**
- **Local mode:** Ruler запускается внутри monolith (все-в-одном) — подходит для dev/small prod
- **Microservices mode:** Ruler как отдельный компонент с.remote access — для production кластеров

### Настройка Ruler

**minimal Loki config (monolith):**

```yaml
# loki.yaml
auth_enabled: false

server:
  http_listen_port: 3100

ruler:
  storage:
    type: local
    local:
      directory: /loki/rules
  rule_path: /loki/rules-temp
  alertmanager_url: http://alertmanager:9093
  ring:
    kvstore:
      store: inmemory
  enable_api: true

limits_config:
  ruler_evaluation_delay_duration: 10s
  ruler_max_rules_per_tenant: 0    # unlimited
```

**microservices mode (separate Ruler):**

```yaml
# ruler.yaml
target: ruler

ruler:
  storage:
    type: s3
    s3:
      bucketnames: loki-ruler-storage
      region: eu-central-1
  rule_path: /data/rules-temp
  alertmanager_url: http://alertmanager:9093
  ring:
    kvstore:
      store: memberlist
  enable_api: true

memberlist:
  join_members:
    - loki-0.loki-headless
    - loki-1.loki-headless
    - loki-2.loki-headless
```

---

## Recording Rules

### Структура recording rule

```yaml
groups:
  - name: http_requests_log_metrics
    interval: 30s
    rules:
      - record: http_requests:count:rate5m
        expr: |
          sum(rate({job="nginx"} |= "HTTP" [5m])) by (method, status)
        labels:
          source: loki
```

### Практические примеры

#### Rate ошибок по сервисам

```yaml
groups:
  - name: error_rates
    interval: 1m
    rules:
      - record: app_errors:rate5m
        expr: |
          sum(rate({job=~".+"} |~ "(?i)(error|exception|panic)" [5m])) by (job)
        labels:
          source: loki

      - record: app_errors:rate1h
        expr: |
          sum(rate({job=~".+"} |~ "(?i)(error|exception|panic)" [1h])) by (job)
        labels:
          source: loki
```

#### Throughput (запросы в секунду)

```yaml
      - record: http_throughput:rate5m
        expr: |
          sum(rate({job="api-gateway"} | json | unwrap status [5m])) by (method, path)
        labels:
          source: loki
```

#### Статус-коды (из structured logs)

```yaml
      - record: http_status_distribution:rate5m
        expr: |
          sum(rate({job=~".+"} | json | unwrap status [5m])) by (job, status)
        labels:
          source: loki
```

### Интеграция с Grafana

Recording rules позволяют использовать LogQL-метрики в дашбордах:

```yaml
# После создания recording rule, метрика доступна как:
# {__name__="http_requests:count:rate5m", method="GET", status="200"}

# В Grafana datasource Loki → создайте запрос:
# {"job"="nginx"} | json | unwrap status | rate(__name__="http_requests:count:rate5m" [5m])
```

---

## Alerting Rules

### Структура alerting rule

```yaml
groups:
  - name: loki-alerts
    interval: 1m
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate({job=~".+"} |~ "error" [5m])) by (job)
          / sum(rate({job=~".+"} [5m])) by (job)
          > 0.05
        for: 5m
        labels:
          severity: critical
          team: backend
        annotations:
          summary: "High error rate on {{ $labels.job }}"
          description: |
            Error rate is {{ $value | humanizePercentage }}
            for job {{ $labels.job }}.
          runbook_url: "https://wiki/runbooks/high-error-rate"
```

### Практические примеры

#### Critical: Error rate > 5% за 5 минут

```yaml
groups:
  - name: application-alerts
    interval: 1m
    rules:
      - alert: HighErrorRate
        expr: |
          (
            sum(rate({job=~".+"} |~ "(?i)(error|exception|panic|fatal)" [5m])) by (job)
          )
          /
          (
            sum(rate({job=~".+"} [5m])) by (job)
          )
          > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate on {{ $labels.job }}"
          description: "Error rate is {{ $value | humanizePercentage }} (threshold: 5%)"
```

#### Warning: OOMKill detected

```yaml
      - alert: OOMKillDetected
        expr: |
          sum(count_over_time({job=~".+"} |~ "OOMKill|Out of Memory|oom-kill" [5m])) by (job)
          > 0
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "OOM kill detected on {{ $labels.job }}"
          description: "OOM kill event found in logs of {{ $labels.job }}"
          runbook_url: "https://wiki/runbooks/oom-kill"
```

#### Warning: Pod restart loop

```yaml
      - alert: PodRestartLoop
        expr: |
          sum(increase({job=~".+", container=~".+"} |~ "Started container" [10m])) by (pod, container)
          > 3
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Pod {{ $labels.pod }} restarting frequently"
          description: "Container {{ $labels.container }} restarted {{ $value }} times in 10 minutes"
```

#### Critical: Certificate expiring soon (from logs)

```yaml
      - alert: CertificateExpiringSoon
        expr: |
          sum(count_over_time({job=~".+"} |~ "certificate.*expir|TLS.*expir" [1h])) by (job)
          > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Certificate expiry detected on {{ $labels.job }}"
          description: "Certificate expiration warning found in logs"
```

#### Critical: Database connection pool exhausted

```yaml
      - alert: DBConnectionPoolExhausted
        expr: |
          sum(rate({job=~".+"} |~ "(?i)(connection pool|pool exhausted|too many connections)" [5m])) by (job)
          > 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "DB connection pool exhausted on {{ $labels.job }}"
          description: "Database connection pool errors detected"
```

#### Warning: High latency (from access logs)

```yaml
      - alert: HighLatencyFromLogs
        expr: |
          histogram_quantile(0.99,
            sum(rate({job="nginx"} | json | unwrap request_time [5m])) by (le, job)
          )
          > 2.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High P99 latency on {{ $labels.job }}"
          description: "P99 latency is {{ $value }}s (threshold: 2s)"
```

#### Security: успешный SSH-вход

Минимальный набор security-алертов для сервера, подключённого к интернету. Ловит вход после подбора пароля/ключа — раньше, чем сработают алерты на нагрузку от майнера или спам-рассылки. `job` и фильтр по строке зависят от того, как логи SSH доставлены в Loki (journald → Alloy, rsyslog и т.д.) — подставьте свой stream.

```yaml
      - alert: SSHAcceptedLogin
        expr: |
          sum(count_over_time({job=~".+"} |~ "Accepted (password|publickey|keyboard-interactive)" [5m]))
          > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Успешный SSH-вход: {{ $value }} событий за 5 минут"
          description: "Каждый Accepted должен быть объясним: кто, откуда, почему именно сейчас"
```

#### Warning: всплеск неудачных попыток SSH (прицельный подбор)

`Invalid user` — шум ботов по несуществующим именам; сотни `Failed password` для **существующего** пользователя — признак целенаправленного перебора, часто предшествует успешному входу.

```yaml
      - alert: SSHFailedPasswordSpike
        expr: |
          sum(count_over_time({job=~".+"} |= "Failed password" [10m])) by (job)
          > 50
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Всплеск Failed password на {{ $labels.job }}"
          description: "{{ $value }} неудачных попыток за 10 минут — проверить fail2ban и ignoreip"
```

#### Warning: создан новый пользователь системы

Создание учётной записи вне change-window — типичный шаг при удержании доступа (attacker persistence). Источник: строки `useradd`/`adduser`/`newusers` в auth-логах или auditd (`USER_ADD`).

```yaml
      - alert: SystemUserCreated
        expr: |
          sum(count_over_time({job=~".+"} |~ "(useradd|adduser|newusers|USER_ADD)" [5m])) by (job)
          > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Создан новый пользователь на {{ $labels.job }}"
          description: "Проверить: легитимен ли useradd; сверить с cron, authorized_keys, sudoers"
```

#### Critical: логи сервера перестали приходить (absence alerting)

Алерты на присутствие аномалий не спасают, когда **нет данных**. Если агент (Alloy) упал, сервер скомпрометирован и выключил логирование, или сеть отвалилась — Loki просто перестаёт получать строки. Алерт на отсутствие потока с конкретного job за окно, большее интервала скрейпа.

```yaml
      - alert: LogsStoppedArriving
        expr: |
          absent_over_time({job="ssh"}[10m])
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Логи {{ $labels.job }} не приходят в Loki более 10 минут"
          description: "Агент умер, хост недоступен или логирование отключено. Проверить Alloy/node_exporter"
```

> **Связанные темы:** мониторинг хостовых метрик (CPU/диск/трафик) — [Prometheus alerts](../Prometheus/concepts/metric_types/alerts.md), [Node Exporter](../Prometheus/Exporters/node_exporter.md); поведение при компрометации — [Incident Response](../Linux/Security/Concepts/incident_response.md).

---

## Интеграция с Alertmanager

### Конфигурация Loki → Alertmanager

```yaml
# loki.yaml
ruler:
  alertmanager_url: http://alertmanager:9093  # HTTP endpoint
  enable_api: true
```

### Alertmanager routing для LogQL-алертов

```yaml
# alertmanager.yml
global:
  resolve_timeout: 5m

route:
  receiver: default
  group_by: ['alertname', 'job', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

  routes:
    - match:
        severity: critical
      receiver: pagerduty-critical
      group_wait: 10s

    - match:
        severity: warning
      receiver: slack-warnings

receivers:
  - name: default
    webhook_configs:
      - url: 'http://loki-gateway:3100/loki/api/v1/alerts'

  - name: pagerduty-critical
    pagerduty_configs:
      - service_key: '<pagerduty-key>'

  - name: slack-warnings
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/xxx'
        channel: '#alerts-warning'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
```

### Alertmanager webhook → Loki (обратная связь)

Loki Ruler отправляет алерты в Alertmanager через HTTP API:

```
POST /api/v2/alerts
Content-Type: application/json

{
  "labels": {
    "alertname": "HighErrorRate",
    "job": "api-gateway",
    "severity": "critical"
  },
  "annotations": {
    "summary": "High error rate on api-gateway",
    "description": "Error rate is 12.5%"
  },
  "startsAt": "2024-01-15T10:30:00Z"
}
```

---

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
| --- | --- | --- |
| **Ruler не запускает правила** | Нет `enable_api: true` | Добавьте `ruler.enable_api: true` |
| **Rules не записываются** | Ruler storage не настроен | Проверьте `ruler.storage.type` |
| **Алерты не отправляются** | Alertmanager URL неверен | Проверьте `ruler.alertmanager_url` |
| **False positive алерты** | Слишком короткий `for` | Увеличьте `for: 5m` → `for: 15m` |
| **Алерты не группируются** | Нет `group_by` в Alertmanager | Настройте `group_by: ['alertname', 'job']` |
| **Recording rule chậm** | Слишком частый interval | Увеличьте `interval: 30s` → `interval: 1m` |
| **High memory usage Ruler** | Много правил, сложные запросы | Оптимизируйте LogQL, уменьшите `evaluation_delay` |

---

## Дополнительная информация

### Сравнение: LogQL Alerting vs Prometheus Alerting

| Характеристика | LogQL Alerting | Prometheus Alerting |
| :--- | :--- | :--- |
| **Источник данных** | Логи (текст, JSON) | Метрики (数值) |
| **Вычисления** | Aggregations по логам | Aggregations по метрикам |
| **Производительность** | Зависит от объёма логов | Зависит от cardinality метрик |
| **Use case** | Ошибки, паттерны, аномалии | Latency, throughput, saturation |
| **Интеграция** | Alertmanager (тот же) | Alertmanager (тот же) |

### Лучшие практики

1. **Используйте recording rules** для ускорения дашбордов с LogQL
2. **Настройте `evaluation_delay`** чтобы данные успели поступить в Loki
3. **Используйте `for`** для стабильности — фильтрует кратковременные всплески
4. **Группируйте алерты** по `job` и `severity` для маршрутизации
5. **Включите `runbook_url`** в annotations для быстрого доступа к инструкциям
6. **Тестируйте правила** через API Ruler: `GET /loki/api/v1/rules`
7. **Мониторьте Ruler** через метрики: `ruler_rules_loaded`, `ruler_evaluate_duration`

### См. также

- **[Loki Overview](./loki_overview.md)** — архитектура и основные компоненты Loki
- **[PromQL Alerting](../Prometheus/Alerts_and_Rules/PromQL_alerting_rules.md)** — алерты на PromQL
- **[Alertmanager](../Prometheus/Alerts_and_Rules/Alertmanager_routing.md)** — маршрутизация алертов
- **[Grafana Alerting](../Grafana/alerting/grafana_alerting_overview.md)** — нативные алерты Grafana
