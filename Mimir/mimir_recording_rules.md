# Mimir: Recording Rules и Alerting Rules через Ruler

## 1. Определения

**Ruler** — компонент Mimir, отвечающий за выполнение recording rules (правил записи) и alerting rules (правил алертинга) для каждого тенанта независимо. Ruler вычисляет PromQL-выражения на расписании и записывает результаты в объектное хранилище (S3) как временные ряды, которые затем доступны для запросов через Querier/Query Frontend.

**Recording Rules** — правила, которые предварительно вычисляют сложные PromQL-выражения и сохраняют результат как новую метрику. Это снижает нагрузку на Querier при визуализации в Grafana и ускоряет алерты.

**Alerting Rules** — правила, которые при выполнении условия генерируют алерты и отправляют их в Alertmanager.

**Отличие от Prometheus:** В Prometheus recording/alerting rules выполняются локально. В Mimir Ruler работает как отдельный микросервис, который читает данные из S3/Ingester и записывает результаты обратно в S3. Это позволяет масштабировать правила независимо от Prometheus.

## 2. Теоретический блок

### Архитектура Ruler в Mimir

```
Ruler → (чтение) → S3 (historical) + Ingester (recent)
    → (вычисление) → PromQL engine
    → (запись) → S3 (recording rules) + Alertmanager (alerting rules)
```

Ruler поддерживает:
- **Tenant isolation:** Каждый тенант имеет свои правила, изолированные через `X-Scope-OrgID`
- **Sharding:** Правила шардируются между репликами Ruler через hash ring
- **Chaining:** Recording rules одной группы могут использоваться в alerting rules той же группы
- **Runtime Configuration:** Лимиты на количество правил, интервал вычисления, таймауты

### Конфигурация Ruler

```yaml
# mimir-config.yaml
ruler:
  ruler_api_enabled: true
  ruler_storage:
    backend: s3
    s3:
      bucket_name: mimir-rules
      endpoint: s3.mimir.svc:9000
    # Альтернатива: local для тестов
    # local:
    #   dir: /data/rules

  # Шардирование правил между репликами Ruler
  sharding_ring:
    kvstore:
      store: memberlist
    replication_factor: 1  # Ruler Stateless, RF=1 достаточно

  # Лимиты (Runtime Configuration)
  evaluation_delay: 0s
  enabled_tenants: ""  # Пустая строка = все тенанты
```

### Правила через Ruler API

Ruler предоставляет HTTP API для управления правилами:

```bash
# GET — получить все правила тенанта
curl -s -H "X-Scope-OrgID: production" \
  http://mimir-ruler:8080/api/v1/rules | jq

# POST — создать/обновить правила
curl -X POST -H "X-Scope-OrgID: production" \
  -H "Content-Type: application/yaml" \
  http://mimir-ruler:8080/api/v1/rules \
  --data-binary @rules.yaml

# DELETE — удалить все правила тенанта
curl -X DELETE -H "X-Scope-OrgID: production" \
  http://mimir-ruler:8080/api/v1/rules

# GET — получить правила конкретной группы
curl -s -H "X-Scope-OrgID: production" \
  http://mimir-ruler:8080/api/v1/rules/{group_name}
```

## 3. Практический блок

### Recording Rules для HTTP-метрик

```yaml
# mimir-recording-rules.yaml
groups:
  - name: http_metrics
    interval: 30s
    rules:
      # Rate запросов по job и коду ответа
      - record: job:http_requests:rate5m
        expr: sum(rate(http_requests_total[5m])) by (job, method, code)

      # Доля ошибок 5xx
      - record: job:http_errors:ratio5m
        expr: |
          sum(rate(http_requests_total{code=~"5.."}[5m])) by (job)
          /
          sum(rate(http_requests_total[5m])) by (job)

      # P99 latency через native histogram
      - record: job:http_latency:p99
        expr: histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, job))

      # P95 latency
      - record: job:http_latency:p95
        expr: histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, job))
```

### Alerting Rules для HTTP-метрик

```yaml
# mimir-alerting-rules.yaml
groups:
  - name: http_alerts
    rules:
      - alert: HighErrorRate
        expr: job:http_errors:ratio5m > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Высокий процент ошибок в {{ $labels.job }}"
          description: "Доля ошибок 5xx превышает 5% на протяжении 5 минут"
          runbook_url: "https://wiki.example.com/runbooks/high-error-rate"

      - alert: HighLatency
        expr: job:http_latency:p99 > 1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Высокий P99 latency в {{ $labels.job }}"
          description: "P99 latency превышает 1 секунду на протяжении 10 минут"
          runbook_url: "https://wiki.example.com/runbooks/high-latency"
```

### Recording Rules для инфраструктуры

```yaml
groups:
  - name: infrastructure
    interval: 60s
    rules:
      # Утилизация CPU по нодам
      - record: node:cpu_utilization:percent
        expr: 100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) by (instance) * 100)

      # Использование памяти
      - record: node:memory_utilization:percent
        expr: (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100

      # Диск I/O
      - record: node:disk_io_utilization:percent
        expr: rate(node_disk_io_time_seconds_total[5m]) * 100
```

### Управление правилами через ConfigMap (Kubernetes)

```yaml
# mimir-rules-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mimir-rules
  namespace: mimir
data:
  recording-rules.yaml: |
    groups:
      - name: http_metrics
        interval: 30s
        rules:
          - record: job:http_requests:rate5m
            expr: sum(rate(http_requests_total[5m])) by (job, method, code)

  alerting-rules.yaml: |
    groups:
      - name: http_alerts
        rules:
          - alert: HighErrorRate
            expr: job:http_errors:ratio5m > 0.05
            for: 5m
            labels:
              severity: critical
```

```bash
# Применение правил
kubectl apply -f mimir-rules-configmap.yaml

# Ruler автоматически подхватывает правила из ConfigMap
# Проверка:
kubectl exec -n mimir deploy/mimir-ruler -- \
  curl -s http://localhost:8080/api/v1/rules | jq '.data.groups | length'
```

### Мониторинг Ruler

```bash
# Ключевые метрики Ruler
curl -s "http://mimir-ruler:8080/metrics" | grep mimir_ruler

# Метрики для алертов:
# mimir_ruler_evaluation_duration_seconds — время вычисления правил
# mimir_ruler_rule_evaluation_failures_total — ошибки вычисления
# mimir_ruler_push_failures_total — ошибки записи результатов
```

```yaml
# Алерт на ошибки Ruler
groups:
  - name: ruler_alerts
    rules:
      - alert: RulerEvaluationFailures
        expr: rate(mimir_ruler_rule_evaluation_failures_total[5m]) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Ruler: ошибки вычисления правил"
          description: "Ruler не может вычислить правила для тенанта {{ $labels.user }}"

      - alert: RulerEvaluationSlow
        expr: mimir_ruler_evaluation_duration_seconds > 30
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Ruler: медленное вычисление правил"
```

### Best Practices

1. **Именование recording rules:** Используйте паттерн `level:metric:operations` (например, `job:http_requests:rate5m`)
2. **Интервал recording rules:** Должен быть кратен интервалу скрапинга (30s, 60s)
3. **Chaining:** Записывайте recording rules в одной группе с alerting rules, которые от них зависят
4. **Версионирование:** Храните правила в Git и доставляйте через GitOps (ArgoCD/Flux)
5. **Тестирование:** Используйте `promtool check rules` перед применением

## 4. Дополнительная информация

### См. также
- [Mimir: Обзор](./mimir_overview.md) — архитектура компонентов и Ruler
- [Prometheus Rules](../Prometheus/rules.md) — базовые концепции recording/alerting rules
- [Alerting Best Practices](../Grafana/alerting/best_practices.md) — методология алертинга (Burn Rate, SLO)
- [Grafana: Recording Rules в Provisioning](../Grafana/alerting/provisioning.md) — Grafana-managed vs Data source-managed rules
- [SLO/SLI для Mimir](./mimir_slo_sli.md) — построение SLO с использованием recording rules

### Официальные ресурсы
- **[Mimir Ruler](https://grafana.com/docs/mimir/latest/configure/configure-ruler/)** — конфигурация Ruler
- **[Mimir Ruler API](https://grafana.com/docs/mimir/latest/references/http-api/#ruler-api)** — HTTP API для управления правилами
