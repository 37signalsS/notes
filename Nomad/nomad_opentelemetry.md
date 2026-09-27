# Nomad — OpenTelemetry и Distributed Tracing

## Определения

**OpenTelemetry (OTel)** — стандартный фреймворк для сбора телеметрии (traces, metrics, logs) из приложений,提供ющий единый API и SDK для инструментации.

**Distributed Tracing** — метод отслеживания запросов через распределённые сервисы, позволяющий визуализировать цепочку вызовов и выявлять узкие места.

**OTLP (OpenTelemetry Protocol)** — протокол передачи телеметрических данных от инструментированных приложений до collector'а.

**Span** — базовая единица трассировки, представляющая отдельную операцию (HTTP-запрос, DB-вызов) с началом, концей и метаданными.

## Основные концепции

### Архитектура OTel в Nomad

```
Nomad Tasks (OTel SDK)
  ↓ (OTLP/gRPC or HTTP)
OTel Collector (system job or sidecar)
  ↓
┌───────────────────────┐
│ Backend: Jaeger / Tempo│
│ or Prometheus (metrics)│
└───────────┬───────────┘
            ↓
       Grafana (visualization)
```

### Компоненты

| Компонент | Роль | Размещение |
| :--- | :--- | :--- |
| **OTel SDK** | Инструментация приложения | Внутри задачи |
| **OTel Collector** | Сбор, обработка, маршрутизация | System job или sidecar |
| **Backend** | Хранение traces | Jaeger, Tempo |
| **Grafana** | Визуализация | Отдельный сервис |

## Практические сценарии

### Сценарий 1: OTel Collector как System Job

```hcl
job "otel-collector" {
  datacenters = ["dc1"]
  type        = "system"

  group "observability" {
    task "collector" {
      driver = "docker"

      config {
        image = "otel/opentelemetry-collector-contrib:0.96.0"
        args  = ["--config=/etc/otel/config.yml"]

        ports {
          name = "otlp-grpc"
          to   = 4317
        }
        ports {
          name = "otlp-http"
          to   = 4318
        }
        ports {
          name = "metrics"
          to   = 8888
        }
      }

      template {
        data = <<EOH
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 5s
    send_batch_size: 1024

exporters:
  otlp/jaeger:
    endpoint: jaeger.service.consul:4317
    tls:
      insecure: true

  prometheus:
    endpoint: "0.0.0.0:8888"
    namespace: otel

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/jaeger]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheus]
EOH
        destination = "local/config.yml"
      }

      resources {
        cpu    = 200
        memory = 256
      }
    }
  }
}
```

### Сценарий 2: Интеграция OTel SDK в приложение (Go)

```go
import (
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
    "go.opentelemetry.io/otel/sdk/trace"
)

func initTracer() (*trace.TracerProvider, error) {
    exporter, err := otlptracegrpc.New(
        context.Background(),
        otlptracegrpc.WithEndpoint("otel-collector.service.consul:4317"),
        otlptracegrpc.WithInsecure(),
    )
    if err != nil {
        return nil, err
    }

    tp := trace.NewTracerProvider(
        trace.WithBatcher(exporter),
        trace.WithSampler(trace.AlwaysSample()),
    )
    otel.SetTracerProvider(tp)
    return tp, nil
}
```

### Сценарий 3: Конфигурация приложения через переменные окружения

Nomad передаёт OTel-конфигурацию через environment:

```hcl
task "server" {
  driver = "docker"

  config {
    image = "registry/webapp:v2"
    ports = ["http"]
  }

  env {
    OTEL_SERVICE_NAME = "webapp"
    OTEL_EXPORTER_OTLP_ENDPOINT = "http://otel-collector.service.consul:4317"
    OTEL_EXPORTER_OTLP_INSECURE = "true"
    OTEL_TRACES_SAMPLER = "always_on"
  }
}
```

### Сценарий 4: Correlation traces ↔ logs

Связывание trace ID с логами для корреляции:

```go
import "go.opentelemetry.io/otel/trace"

func handleRequest(w http.ResponseWriter, r *http.Request) {
    span := trace.SpanFromContext(r.Context())
    spanID := span.SpanContext().SpanID().String()
    traceID := span.SpanContext().TraceID().String()

    log.Printf("request processed trace_id=%s span_id=%s", traceID, spanID)
}
```

**VRL-трансформация для Vector:**
```ruby
# Извлечение trace_id из логов
pattern = /\btrace_id=(?P<trace_id>[a-f0-9]+)\b/
parsed = parse_regex!(.message, pattern)
.trace_id = parsed.trace_id
```

### Сценарий 5: Prometheus метрики через OTel Collector

```hcl
# Экспорт метрик из OTel Collector в Prometheus
exporters:
  prometheus:
    endpoint: "0.0.0.0:8888"
    namespace: nomad_custom

# В Prometheus scrape конфиге
scrape_configs:
  - job_name: 'otel-collector'
    static_configs:
      - targets: ['otel-collector.service.consul:8888']
```

## Диагностика

```bash
# Проверка OTel Collector
curl http://localhost:8888/metrics

# Проверка портов OTLP
ss -tlnp | grep -E "4317|4318"

# Логи Collector
nomad alloc logs <alloc-id> collector
```

## Дополнительная информация

- [OpenTelemetry: Обзор](../OpenTelemetry/opentelemetry_overview.md) — архитектура OTel.
- [OpenTelemetry: OTLP](../OpenTelemetry/otlp_protocol.md) — протокол передачи данных.
- [Nomad — мониторинг](./nomad_monitoring.md) — Prometheus интеграция.
- [Nomad — логирование](./nomad_logging.md) — корреляция с логами.
