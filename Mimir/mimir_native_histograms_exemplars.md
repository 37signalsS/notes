# Mimir: Native Histograms и Exemplars

## 1. Определения

**Native Histograms** — формат хранения гистограмм Prometheus v3.x, где все бакеты упакованы в один временной ряд с динамическими границами (экспоненциальные бакеты). В отличие от классических гистistogramм, где каждый бакет — отдельный ряд с лейблом `le`, Native Histograms хранят все данные в одном ряду, что снижает кардинальность на порядки.

**Exemplars** — ссылки на конкретные трейсы (traceID), прикрепленные к точкам на временном ряде метрики. Позволяют переходить от всплеска на графике latency к конкретному запросу в Tempo/Jaeger.

**Поддержка в Mimir:** Начиная с версии 3.0, Mimir полностью поддерживает Native Histograms и Exemplars. Данные передаются через remote_write и хранятся в TSDB-блоках в S3.

## 2. Теоретический блок

### Native Histograms vs классические гистограммы

| Характеристика | Классическая Histogram | Native Histogram |
|---------------|----------------------|------------------|
| Количество серий | N+1 (каждый бакет + sum + count) | 1 (все бакеты в одном ряду) |
| Кардинальность | Взрывная при множестве бакетов | Фиксированная |
| Точность перцентилей | Зависит от границ бакетов | Экспоненциальные бакеты (высокая точность) |
| Совместимость | Все версии Prometheus | Prometheus 3.0+ |
| Поддержка в Mimir | Полная | Версия 3.0+ |

### Exemplars: связь метрик и трейсов

```
Приложение → [metрика с traceID] → Prometheus/Alloy → remote_write → Mimir
                                                              ↓
Grafana: график latency → клик на exemplar → Tempo/Jaeger: конкретный трейс
```

### Архитектурный поток данных

```
1. Приложение генерирует Native Histogram (через client_golang, OTel SDK)
2. Prometheus/Alloy скрапирует метрику + exemplar
3. remote_write отправляет в Mimir Distributor
4. Ingester записывает в WAL → RAM (TSDB Head) → Flush в S3
5. Querier/Store-Gateway отдают данные при запросе
6. Grafana отображает гистограмму и exemplars
```

## 3. Практический блок

### Инструментация приложения (Go)

```go
import (
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
)

// Классическая гистограмма (LEGACY)
var legacyHistogram = promauto.NewHistogramVec(
    prometheus.HistogramOpts{
        Name:    "http_request_duration_seconds",
        Help:    "Duration of HTTP requests",
        Buckets: []float64{0.01, 0.05, 0.1, 0.5, 1, 2, 5}, // Ручные границы
    },
    []string{"method", "code"},
)

// Native Histogram (РЕКОМЕНДУЕТСЯ)
var nativeHistogram = promauto.NewHistogramVec(
    prometheus.HistogramOpts{
        Name:                        "http_request_duration_seconds_native",
        Help:                        "Duration of HTTP requests (Native Histogram)",
        NativeHistogramBucketFactor: 1.1,  // Экспоненциальный коэффициент
        NativeHistogramZeroThreshold: 1e-12,
        NativeHistogramMaxBucketNumber: 160,
    },
    []string{"method", "code"},
)

// Native Histogram с Exemplar
func recordRequest(method, code string, duration float64, traceID string) {
    nativeHistogram.WithLabelValues(method, code).Observe(duration,
        prometheus.WithExemplars(
            prometheus.Labels{"trace_id": traceID},
        ),
    )
}
```

### Инструментация приложения (Python)

```python
from prometheus_client import Histogram, Counter
from opentelemetry import trace

# Native Histogram через prometheus_client
histogram = Histogram(
    'http_request_duration_seconds',
    'Duration of HTTP requests',
    ['method', 'code'],
    native_histogram_zero_threshold=1e-12,
    native_histogram_max_bucket_number=160,
    native_histogram_duration_factor=1.1,
)

def record_request(method, code, duration):
    histogram.labels(method=method, code=code).observe(duration)

# С привязкой к трейсу (exemplar)
tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("http_request") as span:
    span_id = span.get_span_context().span_id
    trace_id = span.get_span_context().trace_id
    histogram.labels(method="GET", code="200").observe(
        duration,
        exemplar={"trace_id": format(trace_id, '032x')}
    )
```

### Конфигурация Prometheus для Native Histograms

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'myapp'
    scrape_interval: 15s
    scrape_native_histograms: true  # Включение сбора Native Histograms

    # Включение exemplars
    enable_http2: true
```

### Конфигурация remote_write для Mimir

```yaml
remote_write:
  - url: "http://mimir-distributor:8080/api/v1/push"
    send_native_histograms: true  # Важно!
    send_exemplars: true          # Важно!

    # Для Alloy:
    # prometheus.remote_write "mimir" {
    #   endpoint { url = "http://mimir:9009/api/v1/push" }
    #   send_native_histograms = true
    #   send_exemplars = true
    # }
```

### PromQL-запросы к Native Histograms в Mimir

```promql
# P99 latency через Native Histogram
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_native_bucket[5m])) by (le, job)
)

# P95 latency
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_native_bucket[5m])) by (le, job)
)

# Среднее значение
histogram_avg(
  sum(rate(http_request_duration_seconds_native_sum[5m])) by (job)
  /
  sum(rate(http_request_duration_seconds_native_count[5m])) by (job)
)

# Количество наблюдений
sum(rate(http_request_duration_seconds_native_count[5m])) by (job, method)
```

### PromQL-запросы с Exemplars

```promql
# Запрос с exemplars (в Grafana автоматически)
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_native_bucket[5m])) by (le, job)
)
# В Grafana: на панели включить Exemplars → клик на точку → переход к трейсу

# Получение exemplar'ов через API
curl -s "http://mimir-query-frontend:9009/prometheus/api/v1/query?query=histogram_quantile(0.99,sum(rate(http_request_duration_seconds_native_bucket[5m]))by(le,job))" \
  -H "X-Scope-OrgID: production" | jq '.data.result[0].exemplars'
```

### Настройка Grafana для Exemplars

```yaml
# grafana-datasources.yaml
apiVersion: 1
datasources:
  - name: Mimir
    type: prometheus
    url: http://mimir-query-frontend:9009/prometheus
    jsonData:
      httpMethod: POST
      httpHeaderName1: "X-Scope-OrgID"
      exemplarTraceIdDestinations:
        - name: traceID
          datasourceUid: tempo  # UID источника Tempo в Grafana
```

### Миграция с классических на Native Histograms

```bash
# 1. Включите Native Histograms в Prometheus
# scrape_native_histograms: true

# 2. Дублируйте метрику (старая + новая) на переходный период
# var legacyHistogram = ...
# var nativeHistogram = ...

# 3. Обновите дашборды: замените запросы с le на histogram_quantile с native

# 4. После стабилизации удалите legacy-метрику

# В Mimir: данные自动 конвертируются при записи
```

## 4. Дополнительная информация

### См. также
- [Mimir: Обзор](./mimir_overview.md) — Native Histograms и Exemplars в контексте Mimir
- [Native Histograms в Prometheus](../Prometheus/concepts/metric_types/histogram.md) — теория бакетов
- [Exemplars в Grafana](../Grafana/grafana_correlation_exemplars.md) — настройка корреляции
- [PromQL: агрегация](../Prometheus/concepts/promql/aggregation.md) — работа с Native Histograms в PromQL
- [Multi-Region Deployment](./mimir_multi_region.md) — хранение Native Histograms в multi-region

### Официальные ресурсы
- **[Native Histograms](https://prometheus.io/docs/prometheus/latest/configuration/native_histograms/)** — документация Prometheus
- **[Exemplars](https://grafana.com/docs/grafana/latest/dashboards/build-dashboards/add-exemplars/)** — настройка в Grafana
