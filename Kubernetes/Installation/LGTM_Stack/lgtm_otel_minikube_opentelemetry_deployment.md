#### 5. Развертывание OpenTelemetry

##### 5.1. OpenTelemetry Operator

```bash
helm upgrade --install opentelemetry-operator open-telemetry/opentelemetry-operator 
  --namespace opentelemetry-operator 
  --create-namespace
```

##### 5.2. OpenTelemetry Collector

Создайте файл `otel-collector.yaml` и примените его.

```yaml
# otel-collector.yaml
apiVersion: opentelemetry.io/v1alpha1
kind: OpenTelemetryCollector
metadata:
  name: default
  namespace: opentelemetry
spec:
  mode: deployment
  replicas: 1
  config: |
    receivers:
      otlp:
        protocols:
          grpc:
          http:
    processors:
      batch: 
      attributes:
        actions:
          - key: service.name
            from_attribute: k8s.pod.name
            action: upsert
      spanmetrics:
        metrics_exporter: prometheus
        dimensions:
          - name: span.name
            default: "unspecified"
          - name: http.method
            default: "unspecified"
          - name: http.url
            default: "unspecified"
          - name: http.status_code
            default: "unspecified"
        histogram:
          explicit_bounds: [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000]
    exporters:
      otlp:
        endpoint: "tempo.tempo:4317"
        tls:
          insecure: true
      loki:
        endpoint: "http://loki.loki:3100/loki/api/v1/push"
      prometheus:
        endpoint: "http://prometheus-kube-prometheus-prometheus.monitoring:9090/api/v1/write"
        tls:
          insecure: true
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [batch, spanmetrics]
          exporters: [otlp]
        metrics:
          receivers: [otlp]
          processors: [batch]
          exporters: [prometheus]
        logs:
          receivers: [otlp]
          processors: [batch, attributes]
          exporters: [loki]
```

```bash
kubectl apply -f otel-collector.yaml
```

##### 5.3. OpenTelemetry Auto-Instrumentation

Создайте файл `otel-instrumentation.yaml` для автоматической инъекции агента.

```yaml
# otel-instrumentation.yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: default
  namespace: opentelemetry
spec:
  exporter:
    endpoint: http://default.opentelemetry:4317
  java:
    env:
      - name: OTEL_LOGS_EXPORTER
        value: otlp
      - name: OTEL_SERVICE_NAME
        value: "$(OTEL_RESOURCE_ATTRIBUTES_SERVICE_NAME)"
    resources:
      limits:
        cpu: 200m
        memory: 256Mi
      requests:
        cpu: 100m
        memory: 128Mi
```

Примените манифест:

```bash
kubectl apply -f otel-instrumentation.yaml
```
