# Observability для Chaos Engineering

## Определения

**Chaos Observability** — специализированный слой наблюдаемости, предназначенный для мониторинга, трассировки и анализа хаос-экспериментов в реальном времени. Включает метрики экспериментов, traces, логи и аудит-траil.

**Experiment Timeline** — хронология хаос-эксперимента: время начала инъекции, время первого алерта, время остановки, время восстановления.

**Chaos Audit Trail** — запись всех хаос-экспериментов: кто, когда, что сломал, какие метрики были зафиксированы. Требуется для compliance и post-mortem анализа.

**Correlation ID (Trace ID)** — уникальный идентификатор, propagating через все сервисы во время эксперимента. Позволяет коррелировать traces, логи и метрики.

**Chaos-Specific Dashboard** — Grafana дашборд, специально designed для наблюдения за хаос-экспериментом: blast radius visualization, experiment timeline, real-time metrics. Включает experiment info panel, golden signals panels, chaos-specific panels, alert panel.

**Baseline Comparison View** — визуализация текущих метрик рядом с baseline для быстрого определения деградации. Использует PromQL с `offset 1h` или `offset 1d` для сравнения.

**Experiment Timeline** — хронология хаос-эксперимента: время начала инъекции, время первого алерта, время остановки, время восстановления. Используется для post-mortem анализа.

**Chaos Audit Trail** — запись всех хаос-экспериментов: кто, когда, что сломал, какие метрики были зафиксированы. Требуется для compliance и post-mortem анализа. Хранится в Git или dedicated DB.

## Основные концепции

### Требования к observability stack для chaos

```
1. Real-time metrics: Prometheus с scrape_interval=15s или менее.
2. Distributed tracing: Jaeger/Zipkin для корреляции запросов.
3. Log aggregation: Loki/ELK для поиска ошибок во время эксперимента.
4. Alerting: Alertmanager с chaos-specific rules.
5. Visualization: Grafana dashboards для real-time monitoring.
6. Audit trail: хранение истории экспериментов в Git/DB.
```

### Three pillars of chaos observability

**Metrics (Prometheus):**
- Golden Signals: latency, traffic, errors, saturation.
- Chaos-specific: `experiment_duration_seconds`, `blast_radius_percent`, `injection_latency_seconds`.
- SRE: SLI/SLO, Error Budget burn rate.

**Traces (Jaeger):**
- Correlation ID propagation через все сервисы.
- Identification of fault injection point.
- Latency breakdown: где именно произошла задержка.

**Logs (Loki):**
- Structured logging с `experiment_id`, `blast_radius`, `injection_type`.
- Correlation через `trace_id` и `experiment_id`.
- Alert на аномалии в логах.

### Observability before chaos

**Pre-flight checks:**
- Все алерты работают.
- Дашборды обновляются в реальном времени.
- Traces покрывают критичные пути.
- Logs индексируются и доступны для поиска.
- Baseline метрики собраны за 7-14 дней.

Если observability не видит сбой — эксперимент бессмысленен.

## Практические сценарии

### Сценарий 1: Chaos-specific Grafana dashboard

**Цель:** Создать дашборд для наблюдения за хаос-экспериментом в реальном времени.

**Компоненты дашборда:**

1. **Experiment Info panel:**
   - Experiment ID, name, start time, expected duration.
   - Blast radius: % pods, % traffic.
   - Injection type: delay, loss, abort, CPU hog.

2. **Golden Signals panels:**
   - Latency p50/p95/p99 (current vs baseline).
   - Traffic RPS (current vs baseline).
   - Error rate 5xx (current vs baseline).
   - Saturation CPU/memory/disk.

3. **Chaos-specific panels:**
   - Experiment duration timer.
   - Stop-switch status: armed/disarmed/triggered.
   - Blast radius visualization: список затронутых подов.

4. **Alert panel:**
   - Active alerts during experiment.
   - Alert history.

**Пример панели PromQL (Latency with baseline):**

```promql
# Current p99 latency
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{namespace="production"}[5m])))

# Baseline p99 (1 hour ago)
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{namespace="production"}[5m] offset 1h)))

# Ratio: current / baseline
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{namespace="production"}[5m])))
/
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{namespace="production"}[5m] offset 1h)))
```

**Grafana переменные:**

```json
{
  "templating": {
    "list": [
      {
        "name": "experiment_id",
        "type": "query",
        "datasource": "Prometheus",
        "query": "label_values(chaos_experiment_active, experiment_id)"
      },
      {
        "name": "namespace",
        "type": "query",
        "datasource": "Prometheus",
        "query": "label_values(chaos_experiment_active, namespace)"
      }
    ]
  }
}
```

### Сценарий 2: Distributed tracing during chaos

**Цель:** Коррелировать traces с экспериментом для определения точки сбоя.

**Инструмент:** Jaeger + OpenTelemetry.

**Шаги:**

1. **Добавьте experiment_id в trace tags:**
   ```go
   ctx, span := tracer.Start(ctx, "api-handler",
     trace.WithAttributes(attribute.String("experiment_id", "exp-123")))
   ```

2. **Настройте Jaeger для фильтрации по experiment_id:**
   ```bash
   jaeger-query --query.base-path=/jaeger --experiment-id=exp-123
   ```

3. **Анализ traces:**
   - Найдите spans с increased latency.
   - Определите, на каком hop произошла задержка.
   - Проверьте, что circuit breaker сработал на правильном уровне.

**Пример trace analysis:**

```bash
# Экспорт traces в JSON
curl -s "http://jaeger:16686/api/traces?service=api-service&operation=GET%2Fapi%2Fhealth&limit=100&tags=%7B%22experiment_id%22%3A%22exp-123%22%7D" | jq '.data[] | {traceID: .traceID, spans: [.spans[] | {operationName: .operationName, duration: .duration}]}'
```

### Сценарий 3: Log correlation during chaos

**Цель:** Коррелировать логи всех сервисов во время эксперимента через experiment_id.

**Инструмент:** Loki + Promtail.

**Шаги:**

1. **Добавьте structured fields в логи:**
   ```json
   {
     "timestamp": "2024-01-15T10:00:00Z",
     "level": "info",
     "service": "api-gateway",
     "experiment_id": "exp-123",
     "trace_id": "abc123",
     "message": "Request processed",
     "latency_ms": 150
   }
   ```

2. **Настройте Promtail для извлечения experiment_id:**
   ```yaml
   scrape_configs:
     - job_name: kubernetes-pods
       pipeline_stages:
         - json:
             expressions:
               experiment_id: experiment_id
               trace_id: trace_id
         - labels:
             experiment_id:
             trace_id:
   ```

3. **Поиск логов по эксперименту:**
   ```bash
   # Loki: все логи эксперимента
   curl -s "http://loki:3100/loki/api/v1/query_range?query={experiment_id=\"exp-123\"}&limit=1000" | jq '.data.result[].values[]'
   ```

### Сценарий 4: Chaos experiment audit trail

**Цель:** Ведение истории всех экспериментов для compliance и post-mortem.

**Хранилище audit trail:**

```yaml
# chaos-audit.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: chaos-audit-log
  namespace: chaos-testing
data:
  exp-001.yaml: |
    experiment_id: exp-001
    name: network-delay-api-service
    created_at: "2024-01-15T10:00:00Z"
    created_by: @platform-team
    blast_radius: 5% traffic
    injection_type: network delay 200ms
    duration: 5m
    status: completed
    steady_state: upheld
    metrics:
      error_rate: 0.02%
      latency_p99: 250ms (baseline: 180ms)
    stop_switches:
      - alert: ChaosExperimentCriticalErrorRate
        triggered: false
      - alert: ChaosExperimentLatencyDegradation
        triggered: false
    post_mortem: |
      Experiment successful. Circuit breaker activated.
      No user impact detected.
```

**Automation (GitOps):**

```bash
# После эксперимента автоматически создаем audit record
kubectl get networkchaos -n chaos-testing -o json > audit/exp-$(date +%Y%m%d-%H%M%S).json

# Commit в Git
git add audit/
git commit -m "chaos: experiment network-delay-api-service completed"
git push
```

### Сценарий 5: Experiment timeline visualization

**Цель:** Визуализировать timeline эксперимента: когда началась инъекция, когда сработали алерты, когда остановился эксперимент.

**Инструмент:** Grafana + Prometheus + custom exporter.

**Timeline events:**

| Time | Event | Metric | Value |
|:---|:---|:---|:---|
| 10:00:00 | Experiment start | - | - |
| 10:00:05 | Injection started | `experiment_active{experiment_id="exp-123"}` | 1 |
| 10:00:12 | First alert | `ChaosExperimentLatencyDegradation` | triggered |
| 10:00:15 | Stop-switch triggered | `experiment_active` | 0 |
| 10:00:16 | Experiment stopped | - | - |
| 10:01:00 | Recovery complete | latency p99 | < baseline |

**Prometheus recording rules:**

```yaml
groups:
  - name: chaos_timeline
    interval: 10s
    rules:
      - record: experiment_active
        expr: chaos_experiment_status{status="running"} == 1

      - record: experiment_duration_seconds
        expr: time() - timestamp(chaos_experiment_status{status="running"} == 1)

      - record: injection_latency_seconds
        expr: histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{experiment_id!=""}[5m])))
```

### Сценарий 6: Baseline drift detection

**Цель:** Автоматически detecting drift baseline во время эксперимента.

**Инструмент:** Prometheus + Alertmanager.

**Alert rules:**

```yaml
groups:
  - name: chaos_baseline_drift
    rules:
      - alert: ChaosBaselineDriftDetected
        expr: |
          histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])))
          >
          histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m] offset 1d))) * 1.5
          and
          chaos_experiment_active == 1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Latency p99 вырос в 1.5+ раза относительно baseline во время эксперимента"

      - alert: ChaosBaselineDriftCritical
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) > 0.05
          and
          chaos_experiment_active == 1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Error rate > 5% во время эксперимента"
```

## Операции и команды

### Prometheus: chaos-specific queries

```promql
# Experiment active
chaos_experiment_active{experiment_id="exp-123"}

# Experiment duration
time() - timestamp(chaos_experiment_status{status="running"} == 1)

# Blast radius visualization
count(chaos_experiment_active{experiment_id="exp-123"}) by (namespace, app)

# Error rate during experiment
sum(rate(http_requests_total{experiment_id="exp-123", status=~"5.."}[5m])) / sum(rate(http_requests_total{experiment_id="exp-123"}[5m]))

# Latency comparison
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{experiment_id="exp-123"}[5m])))
/
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{experiment_id="exp-123"}[5m] offset 1h)))
```

### Jaeger: поиск traces по эксперименту

```bash
# Поиск traces с experiment_id
curl -s "http://jaeger:16686/api/traces?service=api-service&operation=GET%2Fapi%2Fhealth&limit=100&tags=%7B%22experiment_id%22%3A%22exp-123%22%7D"

# Экспорт traces для анализа
curl -s "http://jaeger:16686/api/traces?service=api-service&operation=GET%2Fapi%2Fhealth&limit=100&tags=%7B%22experiment_id%22%3A%22exp-123%22%7D" | jq '.data[] | {traceID: .traceID, spans: [.spans[] | select(.duration > 500000) | {operationName: .operationName, duration: .duration}]}'
```

### Loki: поиск логов по эксперименту

```bash
# Все логи эксперимента
curl -s "http://loki:3100/loki/api/v1/query_range?query={experiment_id=\"exp-123\"}&limit=1000" | jq '.data.result[].values[]'

# Логи с ошибками
curl -s "http://loki:3100/loki/api/v1/query_range?query={experiment_id=\"exp-123\", level=\"error\"}&limit=1000" | jq '.data.result[].values[]'

# Корреляция по trace_id
curl -s "http://loki:3100/loki/api/v1/query_range?query={trace_id=\"abc123\"}&limit=1000" | jq '.data.result[].values[]'
```

### Grafana: chaos dashboard import

```json
{
  "dashboard": {
    "title": "Chaos Engineering — Experiment Dashboard",
    "panels": [
      {
        "title": "Experiment Active",
        "targets": [
          {
            "expr": "chaos_experiment_active{experiment_id=\"$experiment_id\"}",
            "legendFormat": "Active"
          }
        ]
      },
      {
        "title": "Latency p99 (current vs baseline)",
        "targets": [
          {
            "expr": "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{namespace=\"production\"}[5m])))",
            "legendFormat": "Current"
          },
          {
            "expr": "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{namespace=\"production\"}[5m] offset 1h)))",
            "legendFormat": "Baseline"
          }
        ]
      },
      {
        "title": "Error Rate",
        "targets": [
          {
            "expr": "sum(rate(http_requests_total{status=~\"5..\"}[5m])) / sum(rate(http_requests_total[5m]))",
            "legendFormat": "Error Rate"
          }
        ]
      },
      {
        "title": "Blast Radius",
        "targets": [
          {
            "expr": "count(chaos_experiment_active{experiment_id=\"$experiment_id\"}) by (namespace, app)",
            "legendFormat": "{{namespace}}/{{app}}"
          }
        ]
      }
    ]
  }
}
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| **Дашборд не обновляется** | scrape_interval слишком большой | Уменьшите `scrape_interval` до 15s в Prometheus |
| **Traces не коррелируются** | Trace ID не propagates через сервисы | Проверьте OpenTelemetry instrumentation, `traceparent` header |
| **Логи не индексируются** | Promtail не может парсить JSON | Проверьте `pipeline_stages` в Promtail config |
| **Алерты не срабатывают** | `chaos_experiment_active` метрика отсутствует | Добавьте экспорт метрики из chaos platform или custom exporter |
| **Baseline comparison неточная** | Offset слишком большой или сезонный пик | Используйте `offset 1w` вместо `offset 1h`, исключите патч-вторники |
| **Grafana показывает no data** | Неверные labels или namespace | Проверьте `label_values` в переменных, убедитесь, что experiment_id существует |
| **Jaeger не находит traces** | experiment_id не добавлен в span tags | Добавьте `experiment_id` в trace attributes при старте эксперимента |
| **Audit trail не создается** | Git commit не запускается | Проверьте CI/CD pipeline, добавьте post-experiment hook |

## Лучшие практики

### Pre-flight checks

1. **Валидируйте observability перед экспериментом** — если мониторинг не видит сбой, эксперимент бессмысленен.
2. **Проверьте алерты** — все chaos-specific алерты должны срабатывать в staging.
3. **Проверьте traces coverage** — критичные пути должны быть покрыты tracing.
4. **Проверьте logs indexing** — Loki/ELK должны индексировать логи за <5 минут.
5. **Зафиксируйте baseline** — собрать метрики за 7-14 дней.

### During experiment

6. **Мониторьте в реальном времени** — Grafana dashboard на втором мониторе.
7. **Коррелируйте метрики** — latency spike + error rate spike + saturation spike = деградация.
8. **Используйте traces для диагностики** — если алерт сработал, найдите trace и определите точку сбоя.
9. **Фиксируйте timeline** — время начала, время первого алерта, время остановки.

### Post-experiment

10. **Архивируйте метрики** — сохраните графики Prometheus за время эксперимента.
11. **Экспортируйте traces** — сохраните все traces с experiment_id.
12. **Создайте audit record** — фиксируйте все метрики, алерты, timeline в Git.
13. **Проанализируйте logs** — найдите аномалии, которые не попали в метрики.

### Дашборд дизайн

14. **Используйте baseline comparison** — показывайте current и baseline на одном графике.
15. **Визуализируйте blast radius** — список затронутых подов/сервисов.
16. **Показывайте experiment status** — active/stopped/completed.
17. **Добавьте alert panel** — список active alerts во время эксперимента.

## Дополнительная информация

### Интеграция с инструментами

- **Prometheus + Chaos Mesh exporter:** `chaos-mesh-exporter` экспортирует метрики экспериментов.
- **Grafana + Loki:** корреляция метрик и логов через `experiment_id`.
- **Jaeger + OpenTelemetry:** propagation `experiment_id` через trace context.
- **Alertmanager + Webhook:** автоматический stop experiment при алерте.

### См. также

- [Chaos Engineering — метрики](chaos_engineering_metrics.md) — SLI/SLO/Error Budget.
- [Chaos Engineering — инструменты](chaos_engineering_tools.md) — chaos-mesh-exporter.
- [Chaos Engineering — практическое руководство](chaos_engineering_practical.md) — Game Days observability.
