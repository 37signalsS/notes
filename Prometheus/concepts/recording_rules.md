# Recording Rules в Prometheus

> **См. также:** [Recording Rules и Alerting Rules](../rules.md), [Recording Rules в масштабе](../scaling/recording_rules_at_scale.md), [PromQL функции](./promql/functions.md), [Рекомендации по мониторингу и алертингу](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md).

## Определения

* **Recording Rule** — правило, предварительно вычисляющее PromQL-выражение и сохраняющее результат как новую временную серию (виртуальную метрику). Результат доступен мгновенно при запросе, что ускоряет дашборды и алерты.
* **Виртуальная метрика** — метрика, созданная recording rule (например, `job:http_requests:rate5m`). Не существует в приложении — только в TSDB.
* **Группа правил (Rule Group)** — логическое объединение правил, которые выполняются последовательно внутри группы с единым интервалом вычисления.
* **Цепочка правил (Chaining)** — последовательность recording rules, где результат одной правила используется в качестве входных данных для следующего правила в той же группе.

## Основные концепции

### Зачем нужны recording rules

1. **Производительность:** Запрос `sum(rate(http_requests_total{status=~"5.."}[5m])) by (job)` по миллиарду рядов может занимать секунды. Recording rule вычисляет это один раз и сохраняет результат.
2. **Стабильность алертов:** Алерты на сложные выражения могут «дрожать» из-за вариативности данных. Recording rules вычисляются с фиксированным интервалом, обеспечивая стабильные пороги.
3. **Кросс-кластерная агрегация:** При федерации или Thanos recording rules позволяют агрегировать данные на уровне Leaf и передавать на Master только готовые агрегаты.

### Параметры recording rule

| Параметр | Описание | Рекомендации |
|:---|:---|:---|
| `record` | Имя создаваемой метрики | Формат `level:metric:operations` (например, `job:http_requests:rate5m`) |
| `expr` | PromQL-выражение | Выражение для предварительного вычисления |
| `labels` | Дополнительные метки | Добавляются к результирующей метрике |

### Группировка и интервалы

**Правила объединяются в группы** с общим интервалом вычисления:

- **`interval`**: Частота выполнения правил в группе. По умолчанию наследуется из `evaluation_interval`. Рекомендуется: `interval >= scrape_interval`.
- **`limit`**: Максимальное количество временных рядов, которые могут быть созданы recording rules в группе. Защита от взрывного роста кардинальности.
- **Последовательность:** Внутри группы правила выполняются **строго последовательно**. Это позволяет использовать результат предыдущего `record` в следующем правиле.
- **Между группами:** Разные группы выполняются **параллельно**. Нельзя полагаться на порядок выполнения между группами.

### Гонка данных (Race Conditions)

Поскольку recording rules вычисляются до alerting rules в той же группе, можно безопасно использовать виртуальные метрики в выражениях алертов **той же группы**. Однако между разными группами такой гарантии нет.

**Рекомендация:** Размещайте recording rules и зависящие от них alerting rules в **одной группе** или синхронизируйте интервалы.

### Соглашение об именовании

Формат `level:metric:operations` обеспечивает единообразие и удобство поиска:

| Уровень | Описание | Пример |
|:---|:---|:---|
| `level` | Уровень агрегации | `job`, `cluster`, `instance` |
| `metric` | Исходная метрика | `http_requests`, `cpu_usage` |
| `operations` | Операции | `rate5m`, `sum`, `p95` |

**Примеры:**
- `job:http_requests:rate5m` — rate запросов по job за 5 минут
- `job:http_errors:ratio5m` — доля ошибок по job за 5 минут
- `cluster:node_cpu:sum_rate1h` — суммарный rate CPU по кластеру за 1 час

## Практические примеры

### Базовая recording rule

```yaml
groups:
  - name: http_agg
    interval: 30s
    rules:
      - record: job:http_requests:rate5m
        expr: sum(rate(http_requests_total[5m])) by (job)
```

### Цепочка recording rules

```yaml
groups:
  - name: http_agg
    interval: 30s
    rules:
      - record: job:http_requests:rate5m
        expr: sum(rate(http_requests_total[5m])) by (job)
      - record: job:http_requests_errors:rate5m
        expr: sum(rate(http_requests_total{status=~"5.."}[5m])) by (job)
      - record: job:http_errors:ratio5m
        expr: job:http_requests_errors:rate5m / job:http_requests:rate5m
  - name: http_alerts
    rules:
      - alert: HighErrorRate
        expr: job:http_errors:ratio5m > 0.05
        for: 5m
```

### Recording rules для SLO

```yaml
groups:
  - name: slo_rules
    interval: 5m
    rules:
      - record: slo:error_ratio:rate5m
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m])) by (job)
          /
          sum(rate(http_requests_total[5m])) by (job)
      - record: slo:availability:score
        expr: 1 - slo:error_ratio:rate5m
```

### Recording rules для динамических порогов

```yaml
groups:
  - name: dynamic_thresholds
    interval: 1h
    rules:
      - record: job:api:p95_latency_baseline_7d
        expr: |
          quantile_over_time(0.95, http_request_duration_seconds_bucket{job="api"}[7d])
      - alert: LatencyRegression
        expr: |
          histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job="api"}[5m]))
          > 1.5 * job:api:p95_latency_baseline_7d
        for: 10m
```

### Мониторинг производительности правил

```promql
# Время выполнения группы правил (в секундах)
prometheus_rule_group_duration_seconds

# Если время выполнения приближается к interval — правило нужно оптимизировать
prometheus_rule_group_duration_seconds > prometheus_rule_group_interval_seconds * 0.8
```

## Дополнительная информация

* **Подробное описание параметров правил:** [Recording и Alerting Rules](../rules.md)
* **Оптимизация в масштабе:** [Recording Rules в масштабе](../scaling/recording_rules_at_scale.md)
* **Промежуточные вычисления:** [PromQL функции](./promql/functions.md)
* **Рекомендации SRE:** [Рекомендации по мониторингу и алертингу](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md)
* **Валидация правил:** [promtool и лучшие практики](../promtool_and_best_practices.md)
* **Recording rules в Mimir:** [Mimir Recording Rules](../../Mimir/mimir_recording_rules.md)
