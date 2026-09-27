# OpenTelemetry: Управление кардинальностью

## Определения

**Кардинальность (Cardinality)** — количество уникальных комбинаций значений атрибутов (labels) в метриках. Высокая кардинальность приводит к увеличению потребления ресурсов, замедлению запросов и росту стоимости хранения.

В 2026 году управление кардинальностью является критическим навыком для работы с OpenTelemetry и Prometheus.

## Теоретический блок

### Влияние кардинальности

```text
Кардинальность = Количество уникальных комбинаций labels
Пример: http_method × http_status × service_name

Если:
- http_method: 5 значений (GET, POST, PUT, DELETE, PATCH)
- http_status: 6 значений (200, 201, 400, 404, 500, 503)
- service_name: 10 сервисов

Общая кардинальность: 5 × 6 × 10 = 300 метрик
```

### Источники высокой кардинальности

| Источник | Пример | Проблема |
| :--- | :--- | :--- |
| **Уникальные ID** | user_id, order_id, request_id | Тысячи метрик |
| **Временные метки** | timestamp, request_time | Бесконечные метрики |
| **Текстовые поля** | error_message, stack_trace | Неограниченные значения |
| **Динамические данные** | ip_address, user_agent | Постоянно растущие метрики |

## Практические сценарии

### Сценарий 1: Фильтрация атрибутов в Collector

**Использование attributes processor для удаления высококардинальных атрибутов:**

```yaml
processors:
  attributes:
    actions:
      - key: user_id
        action: delete
      - key: order_id
        action: delete
      - key: request_id
        action: delete
      - key: ip_address
        action: delete
```

**Использование filter processor для фильтрации метрик:**

```yaml
processors:
  filter:
    metrics:
      exclude:
        match_type: regexp
        metric_names:
          - ".*user_id.*"
          - ".*order_id.*"
```

### Сценарий 2: Агрегация метрик

**Использование transform processor для агрегации:**

```yaml
processors:
  transform:
    metric_statements:
      - context: metric
        statements:
          - set(description, "Aggregated HTTP request duration") where name == "http.request.duration"
          - set(unit, "ms") where name == "http.request.duration"
```

**Использование aggregation processor:**

```yaml
processors:
  aggregation:
    metrics:
      http.request.duration:
        aggregation: sum
        attributes:
          - service.name
          - http.method
```

### Сценарий 3: Нормализация имен

**Нормализация URL и route:**

```yaml
processors:
  attributes:
    actions:
      - key: http.url
        action: update
        value: "/api/v1/users/{id}"
        pattern: "/api/v1/users/[0-9]+"
      - key: http.route
        action: upsert
        value: "/api/v1/users/{id}"
```

### Сценарий 4: Ограничение набора атрибутов

**Использование allowed_attributes:**

```yaml
processors:
  attributes:
    actions:
      - key: service.name
        action: keep
      - key: http.method
        action: keep
      - key: http.status_code
        action: keep
      - key: http.url
        action: delete
```

### Сценарий 5: Мониторинг кардинальности

**Метрики для мониторинга:**

```bash
# Проверка количества метрик в Prometheus
curl -s 'http://prometheus:9090/api/v1/label/__name__/values' | jq 'length'

# Проверка кардинальности по label
curl -s 'http://prometheus:9090/api/v1/label/service.name/values' | jq 'length'

# Проверка метрик с высокой кардинальностью
curl -s 'http://prometheus:9090/api/v1/series' | jq '[.[] | select(.service.name | length > 100)] | length'
```

**Алерты на высокую кардинальность:**

```yaml
groups:
  - name: cardinality
    rules:
      - alert: HighCardinalityMetrics
        expr: prometheus_tsdb_head_series > 1000000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая кардинальность метрик"
```

## Дополнительная информация

### Типичные проблемы и решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Prometheus потребляет много памяти** | Высокая кардинальность метрик | Фильтровать атрибуты, агрегировать метрики |
| **Медленные запросы в Grafana** | Слишком много временных рядов | Ограничивать количество лейблов |
| **Высокая стоимость хранения** | Много метрик с высокой кардинальностью | Настроить retention, фильтровать ненужные метрики |
| **Медленная обработка в Collector** | Слишком много атрибутов | Уменьшить количество атрибутов |

### Best Practices

1. **Избегайте уникальных ID** — не используйте user_id, order_id как labels.
2. **Нормализуйте данные** — приводите URL, route к единому формату.
3. **Фильтруйте атрибуты** — удаляйте ненужные атрибуты до отправки.
4. **Агрегируйте метрики** — используйте sum, count, avg вместо детальных значений.
5. **Мониторьте кардинальность** — настройте алерты на высокие значения.

### Ссылки

- [Prometheus Cardinality](https://prometheus.io/docs/practices/naming/)
- [OTel Collector Processors](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor)
- [High Cardinality in Metrics](https://grafana.com/blog/2022/02/24/what-to-do-when-metrics-become-too-high-cardinality/)
