# Примеры алертов для разных типов метрик

## Алерт на основе Counter (доля ошибок > 5%)

```yaml
- alert: HighErrorRate
  expr: |
    sum(rate(http_requests_total{status=~"5.."}[5m]))
    /
    sum(rate(http_requests_total[5m])) > 0.05
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Высокая доля ошибок HTTP 5xx"
    description: "Доля ошибок составляет {{ $value | humanizePercentage }}"
```

## Алерт на основе Gauge (мало свободной памяти)

```yaml
- alert: LowMemory
  expr: |
    (node_memory_mem_available_bytes / node_memory_mem_total_bytes) * 100 < 10
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Мало свободной памяти на {{ $labels.instance }}"
    description: "Свободно только {{ $value | humanize }}%"
```

## Алерт на основе Histogram (медленные запросы)

```yaml
- alert: HighLatency
  expr: |
    histogram_quantile(0.95,
      sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
    ) > 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Высокая латентность запросов"
    description: "95-й перцентиль: {{ $value | humanizeDuration }}"
```

> **См. также:** [Rules и алертинг](../rules.md) — полное руководство по созданию правил.

---

**Связанные темы:**

* [Counter](./counter.md) — алерты на основе счётчиков
* [Gauge](./gauge.md) — алерты на основе измерителей
* [Histogram](./histogram.md) — алерты на основе гистограмм
* [Rules и алертинг](../rules.md)
