# Интеграция Jaeger с Kubernetes

Интеграция Jaeger в кластер Kubernetes подразумевает развёртывание компонентов трассировки и корректное подключение приложений к сборщику трейсингов. Варианты зависят от требований к отказоустойчивости и объёму данных: от all-in-one для разработческой среды до распределённой продакшен-архитектуры с устойчивым хранилищем.

## Подходы к развёртыванию

*   **All-in-One**: единый Pod с агентом, коллектором, UI и in-memory хранилищем. Подойдёт для демо и отладки.
*   **Production**: отдельные Deployment-ы для Collector и Query, агент в виде DaemonSet или сайдкара; внешнее хранилище (Elasticsearch, Cassandra).
*   **Через оператор**: Jaeger Operator управляет жизненным циклом, предоставляет CRD и автоматизирует сайдкар-инъекцию агента.

## Jaeger Operator и CRD

Оператор упрощает установку: создаётся ресурс Jaeger, а оператор разворачивает нужные объекты. Пример dev-конфигурации:

```yaml
apiVersion: jaegertracing.io/v1
kind: Jaeger
metadata:
  name: jaeger-dev
spec:
  strategy: allInOne
  storage:
    type: memory
  ingress:
    enabled: true
```

Минимальная продакшен-конфигурация с Elasticsearch:

```yaml
apiVersion: jaegertracing.io/v1
kind: Jaeger
metadata:
  name: jaeger-prod
spec:
  strategy: production
  storage:
    type: elasticsearch
    options:
      es:
        server-urls: http://elasticsearch:9200
  collector:
    replicas: 3
  query:
    replicas: 2
```

Для автоматической инъекции агента в Pod добавляется аннотация. Оператор подставит сайдкар и направит трафик на Collector:

```yaml
metadata:
  annotations:
    sidecar.jaegertracing.io/inject: "true"
```

## Сети и порты

| Компонент | Порты | Назначение |
| --- | --- | --- |
| Agent | 6831/6832 UDP, 5778 | Приём трейсингов от SDK, конфигурация |
| Collector | 14250 gRPC, 14268 HTTP, 9411 | Приём трейсингов (gRPC/Thrift/Zipkin) |
| Query (UI) | 16686 | Веб-интерфейс |

В Kubernetes обычно создаются Service-объекты:

*   `jaeger-collector` для приёма трафика от приложений/агентов.
*   `jaeger-query` для доступа к UI (через Ingress/LoadBalancer).
*   `jaeger-agent` как DaemonSet или сайдкар, чтобы приложения могли отправлять данные на `localhost:6831` без дополнительных DNS-зависимостей.

## Интеграция приложений

### Вариант 1: агент как сайдкар
Аннотация подставит агент, а приложение отправляет трейсы на `localhost`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payments
spec:
  replicas: 2
  selector: { matchLabels: { app: payments } }
  template:
    metadata:
      labels: { app: payments }
      annotations:
        sidecar.jaegertracing.io/inject: "true"
    spec:
      containers:
      - name: app
        image: registry.example.com/payments:1.2.3
        env:
        - name: JAEGER_AGENT_HOST
          value: "localhost"
        - name: JAEGER_AGENT_PORT
          value: "6831"
        - name: JAEGER_SERVICE_NAME
          value: "payments"
```

### Вариант 2: через OpenTelemetry Collector
Приложение направляет OTLP-трейсы на Collector.

Конфигурация `otel-collector`:
```yaml
receivers:
  otlp:
    protocols:
      http:
exporters:
  jaeger:
    endpoint: jaeger-collector:14250
    tls:
      insecure: true
service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [jaeger]
```

Конфигурация приложения:
```yaml
env:
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: "http://otel-collector:4318"
- name: OTEL_TRACES_EXPORTER
  value: "otlp"
- name: OTEL_EXPORTER_OTLP_PROTOCOL
  value: "http/protobuf"
```

## Практические аспекты эксплуатации

*   Масштабирование Collector горизонтально с учётом пропускной способности и очередей.
*   Выделение ресурсов и лимитов CPU/Memory для Collector/Query, чтобы избежать троттлинга.
*   Развёртывание UI за Ingress с аутентификацией уровня платформы.
*   Сетевые политики ограничивают исходящий трафик приложений только до агента/коллектора.
*   Бэкенд-хранилище разворачивается в отдельном пуле узлов и изолируется по StorageClass для стабильно низких задержек.
