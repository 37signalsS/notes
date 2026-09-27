# Оптимизация PromQL-запросов

## Определения

**Оптимизация PromQL** — процесс уменьшения времени выполнения запросов, потребления ресурсов и нагрузки на TSDB без потери точности данных. Включает использование recording rules, правильный выбор функций и агрегацию.

**Recording Rule** — правило Prometheus, предварительно вычисляющее сложный PromQL-запрос и сохраняющее результат как новую метрику. Переносит вычисления с read-time на write-time.

**Subquery** — вложенная подвыборка в PromQL, позволяющая выполнять агрегации поверх временных рядов. Мощный, но ресурсоемкий инструмент.

> **См. также:** [Recording Rules](../recording_rules.md) — определения и примеры; [Functions](./functions.md) — справочник функций; [Query Patterns](./query_patterns.md) — типовые паттерны; [Troubleshooting](./troubleshooting.md) — диагностика проблем.

---

## Базовые концепции

### Принципы оптимизации

| Принцип | Описание |
|:---|:---|
| **Записывай один, читай много** | Recording rules для frequently used queries |
| **Минимизируй выборку** | Точные селекторы вместо wildcard |
| **Избегай subquery** | Заменяй на recording rules или более простые функции |
| **Используй appropriately sized intervals** | `[5m]` вместо `[1h]` для rate() |
| **Кэшируй результаты** | Recording rules = кэш на write-time |

### Приоритеты оптимизации

1. **Recording rules** — для queries, выполняемых >1 раза в час
2. **Правильные интервалы** — `rate()` всегда >= 4x scrape_interval
3. **Агрегация по label** — `sum by()` вместо `sum()` для reduced cardinality
4. **Избегай `group_left`/`group_right`** — для сложных join операций
5. **limit series** — точные селекторы, не `=~".*"`

---

## Практические сценарии

### Проблема 1: Медленный rate() с коротким интервалом

**Плохо:**
```promql
rate(http_requests_total[1h])
# Проблема: 1200 данных точек за 1h, много вычислений
```

**Хорошо (recording rule):**
```yaml
groups:
  - name: http_recording
    interval: 15s
    rules:
      - record: job:http_requests:rate5m
        expr: rate(http_requests_total[5m])
```

```promql
# Теперь запрос мгновенный:
job:http_requests:rate5m
```

### Проблема 2: Сложный percentile запрос

**Плохо:**
```promql
histogram_quantile(0.99,
  sum by(job, le) (
    rate(http_request_duration_seconds_bucket[5m])
  )
)
# Вычисляется каждый раз при запросе из Grafana
```

**Хорошо (recording rules):**
```yaml
groups:
  - name: latency_recording
    interval: 30s
    rules:
      - record: job:http_request_duration:p99_5m
        expr: histogram_quantile(0.99,
          sum by(job, le) (
            rate(http_request_duration_seconds_bucket[5m])
          )
        )
      - record: job:http_request_duration:p95_5m
        expr: histogram_quantile(0.95,
          sum by(job, le) (
            rate(http_request_duration_seconds_bucket[5m])
          )
        )
```

### Проблема 3: Subquery для аномалий

**Плохо:**
```promql
# Subquery — ресурсоемко
avg_over_time(
  cpu_usage[1h]
) > 2 * avg_over_time(
  cpu_usage[1h] offset 1w
)
# Subquery вычисляет 240 точек за каждый момент времени
```

**Хорошо (recording rules):**
```yaml
groups:
  - name: anomaly_recording
    interval: 5m
    rules:
      - record: cpu:usage:avg_current_1h
        expr: avg_over_time(cpu_usage[1h])
      - record: cpu:usage:avg_last_week_1h
        expr: avg_over_time(cpu_usage[1h] offset 1w)
```

```promql
# Теперь запрос простой:
cpu:usage:avg_current_1h > 2 * cpu:usage:avg_last_week_1h
```

### Проблема 4: Высокая кардинальность в агрегации

**Плохо:**
```promql
# Без group_by — огромный результат
sum(rate(http_requests_total[5m]))
# Если 100k series — агрегация займёт много RAM
```

**Хорошо:**
```promql
# Агрегация по конкретным labels
sum by(job, status) (rate(http_requests_total[5m]))
# Результат: количество уникальных комбинаций job x status
```

### Проблема 5: label_replace для нормализации

**Плохо (много label_replace в цепочке):**
```promql
label_replace(
  label_replace(
    label_replace(
      rate(http_requests_total[5m]),
      "service", "$1", "job", "(.*)-.*"
    ),
    "method", "$1", "path", "/(.*)/.*"
  ),
  "status", "$1", "code", "(\\d{3}).*"
)
```

**Хорошо (recording rule):**
```yaml
groups:
  - name: http_normalized
    interval: 15s
    rules:
      - record: http_requests:normalized
        expr: rate(http_requests_total[5m])
        labels:
          service: "{{ $labels.job }}"
```

### Проблема 6: Оптимизация for в алертах

**Плохо:**
```yaml
- alert: HighErrorRate
  expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.01
  for: 1m
  # Слишком короткое окно — ложные срабатывания
```

**Хорошо:**
```yaml
# Recording rule для алерта
- record: job:http_error_rate:ratio5m
  expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])

# Алерт на предвычисленное значение
- alert: HighErrorRate
  expr: job:http_error_rate:ratio5m > 0.01
  for: 5m
  # Longer window reduces false positives
```

### Проблема 7: Оптимизация histogram_quantile

```promql
# Вместо вычисления на лету — recording rules для всех нужных перцентилей
groups:
  - name: latency_percentiles
    interval: 30s
    rules:
      - record: job:http_latency:p50
        expr: histogram_quantile(0.50, sum by(job, le) (rate(http_duration_seconds_bucket[5m])))
      - record: job:http_latency:p95
        expr: histogram_quantile(0.95, sum by(job, le) (rate(http_duration_seconds_bucket[5m])))
      - record: job:http_latency:p99
        expr: histogram_quantile(0.99, sum by(job, le) (rate(http_duration_seconds_bucket[5m])))
```

---

## Дополнительная информация

### Диагностика медленных запросов

```bash
# Поиск медленных запросов в логах Prometheus
grep "query processing" /var/log/prometheus/prometheus.log | \
  grep "duration" | sort -t'=' -k5 -n -r | head -10

# Просмотр активных запросов
curl -s http://localhost:9090/api/v1/status/tsdb | jq '.data.seriesCountByMetricName[:10]'
```

### Метрики для мониторинга производительности PromQL

```promql
# Время выполнения правил
prometheus_rule_evaluation_duration_seconds

# Количество активных series
prometheus_tsdb_head_series

# Размер блоков
prometheus_tsdb_storage_blocks_bytes

# Время query
prometheus_engine_query_duration_seconds
```
