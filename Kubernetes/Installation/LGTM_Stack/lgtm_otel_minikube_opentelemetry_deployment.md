# Развертывание OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)** ← текущий
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

## Определения

**OpenTelemetry (OTel)** — открытый стандарт CNCF для сбора, обработки и экспорта телеметрических данных (трассировки, метрики, логи). Полная документация: **[OpenTelemetry overview](../../../OpenTelemetry/opentelemetry_overview.md)**.

**OpenTelemetry Operator** — Kubernetes-оператор для автоматизации управления OTel Collector и автоматической инструментации приложений. Управляет CRD `OpenTelemetryCollector` и `Instrumentation`.

**OTel Collector** — центральный компонент OTel, действующий как конвейер для телеметрических данных. Состоит из receivers (приёмников), processors (обработчиков) и exporters (экспортёров). Полная архитектура: **[OTel Architecture](../../../OpenTelemetry/architecture_signals.md)**.

**Instrumentation** — процесс внедрения OTel SDK в приложение для генерации телеметрии. Поддерживает автоматическую инструментацию (Java, Python, Node.js) и ручную (через API). Подробнее: **[Instrumentation SDK](../../../OpenTelemetry/instrumentation_sdk.md)**.

**OTLP (OpenTelemetry Protocol)** — унифицированный протокол для передачи телеметрических данных между Collector и бэкендами. Подробнее: **[OTLP Protocol](../../../OpenTelemetry/otlp_protocol.md)**.

**Spanmetrics** — процессор OTel Collector для генерации метрик из трассировок (RED-метод: Rate, Errors, Duration).

---

## Основные концепции

### Архитектура OTel в Kubernetes

```
┌─────────────────────────────────────────────────────────────────┐
│                     Minikube Cluster                            │
│                                                                 │
│  ┌─────────────────┐     ┌─────────────────────────────────┐   │
│  │   Application   │     │   OpenTelemetry Operator        │   │
│  │   (Java/OTel)   │     │   (контроллер K8s)              │   │
│  │                 │     │                                 │   │
│  │  ┌───────────┐  │     │  ┌───────────────────────────┐  │   │
│  │  │ OTel SDK  │──┼─────┼─▶│  OpenTelemetryCollector   │  │   │
│  │  └───────────┘  │OTLP │  │  (Collector Deployment)   │  │   │
│  └─────────────────┘     │  └─────────────┬─────────────┘  │   │
│                          │                │                 │   │
│                          │  ┌─────────────▼─────────────┐  │   │
│                          │  │    Instrumentation CRD    │  │   │
│                          │  │  (auto-injection config)  │  │   │
│                          │  └───────────────────────────┘  │   │
│                          └─────────────────────────────────┘   │
│                                           │                     │
│                    ┌──────────────────────┼──────────────────┐ │
│                    │                      │                  │ │
│                    ▼                      ▼                  ▼ │
│            ┌──────────────┐      ┌──────────────┐   ┌────────┐│
│            │    Tempo     │      │   Loki       │   │Prometheus│
│            │  (traces)    │      │   (logs)     │   │(metrics)│
│            │  :4317       │      │  :3100       │   │ :9090  │
│            └──────────────┘      └──────────────┘   └────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Компоненты OTel Collector

| Компонент | Назначение | Примеры |
| :--- | :--- | :--- |
| **Receivers** | Приём данных в различных форматах | `otlp`, `jaeger`, `zipkin`, `prometheus` |
| **Processors** | Обработка данных (фильтрация, обогащение) | `batch`, `attributes`, `spanmetrics`, `memory_limiter` |
| **Exporters** | Отправка данных в бэкенды | `otlp`, `loki`, `prometheus`, `jaeger` |

### Потоки данных (Pipelines)

OTel Collector обрабатывает три типа сигналов через независимые pipeline:

1. **Traces:** `otlp/receiver → batch/spanmetrics → otlp/exporter → Tempo`
2. **Metrics:** `otlp/receiver → batch → prometheus/exporter → Prometheus`
3. **Logs:** `otlp/receiver → batch/attributes → loki/exporter → Loki`

### Требования к ресурсам (Minikube)

| Компонент | CPU (request/limit) | Memory (request/limit) |
| :--- | :--- | :--- |
| **OTel Operator** | 100m / 500m | 128Mi / 512Mi |
| **OTel Collector** | 100m / 500m | 128Mi / 512Mi |
| **Auto-instrumentation** | 100m / 200m (на Pod) | 128Mi / 256Mi (на Pod) |

---

## Практические сценарии

### Сценарий 1: Установка OpenTelemetry Operator

**Цель:** Развернуть оператор для управления OTel Collector и автоматической инструментации.

#### Шаг 1: Добавление Helm-репозитория

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update
```

#### Шаг 2: Установка оператора

```bash
helm upgrade --install opentelemetry-operator \
  open-telemetry/opentelemetry-operator \
  --namespace opentelemetry-operator \
  --create-namespace
```

#### Шаг 3: Проверка установки

```bash
# Проверка Pod оператора
kubectl get pods -n opentelemetry-operator

# Проверка CRD
kubectl get crds | grep opentelemetry.io
```

**Ожидаемый результат:**

```
NAME                                              READY   STATUS    RESTARTS   AGE
opentelemetry-operator-controller-manager-xxxxx   2/2     Running   0          2m

opentelemetrycollectors.opentelemetry.io          Created
instrumentations.opentelemetry.io                 Created
```

---

### Сценарий 2: Развёртывание OTel Collector

**Цель:** Настроить Collector для приёма телеметрии и экспорта в Loki, Tempo, Prometheus.

#### Шаг 1: Создание манифеста Collector

Создайте файл `otel-collector.yaml`:

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
  resources:
    limits:
      cpu: 500m
      memory: 512Mi
    requests:
      cpu: 100m
      memory: 128Mi
  config: |
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
          http:
            endpoint: 0.0.0.0:4318
    processors:
      batch:
        timeout: 1s
        send_batch_size: 1024
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
      memory_limiter:
        check_interval: 1s
        limit_mib: 400
        spike_limit_mib: 100
    exporters:
      otlp:
        endpoint: "tempo.tempo:4317"
        tls:
          insecure: true
      loki:
        endpoint: "http://loki.loki:3100/loki/api/v1/push"
      prometheus:
        endpoint: "0.0.0.0:8889"
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, batch, spanmetrics]
          exporters: [otlp]
        metrics:
          receivers: [otlp]
          processors: [memory_limiter, batch]
          exporters: [prometheus]
        logs:
          receivers: [otlp]
          processors: [memory_limiter, batch, attributes]
          exporters: [loki]
```

**Ключевые настройки:**

- **`spanmetrics`**: Генерирует метрики RED-метода из трассировок для экспорта в Prometheus
- **`memory_limiter`**: Защищает Collector от OOM при высокой нагрузке
- **`attributes`**: Обогащает логи метаданными (например, `service.name` из имени Pod)

#### Шаг 2: Применение манифеста

```bash
kubectl apply -f otel-collector.yaml
```

#### Шаг 3: Проверка Collector

```bash
# Проверка статуса
kubectl get otelcol -n opentelemetry

# Проверка Pod
kubectl get pods -n opentelemetry

# Просмотр логов
kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector --tail=50
```

**Ожидаемый статус:** `Ready=True`

---

### Сценарий 3: Настройка автоматической инструментации (Auto-Instrumentation)

**Цель:** Включить автоматическую инъекцию OTel SDK для Java-приложений.

#### Шаг 1: Создание манифеста Instrumentation

Создайте файл `otel-instrumentation.yaml`:

```yaml
# otel-instrumentation.yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: default
  namespace: opentelemetry
spec:
  exporter:
    endpoint: http://default-collector.opentelemetry:4317
  java:
    env:
      - name: OTEL_LOGS_EXPORTER
        value: otlp
      - name: OTEL_SERVICE_NAME
        value: "$(OTEL_RESOURCE_ATTRIBUTES_SERVICE_NAME)"
      - name: OTEL_METRICS_EXPORTER
        value: otlp
      - name: OTEL_TRACES_EXPORTER
        value: otlp
    resources:
      limits:
        cpu: 200m
        memory: 256Mi
      requests:
        cpu: 100m
        memory: 128Mi
```

**Параметры:**

- **`exporter.endpoint`**: Адрес OTel Collector для отправки телеметрии
- **`OTEL_LOGS_EXPORTER`**: Включает экспорт логов через OTLP
- **`OTEL_SERVICE_NAME`**: Устанавливает имя сервиса из аннотаций Pod

#### Шаг 2: Применение манифеста

```bash
kubectl apply -f otel-instrumentation.yaml
```

#### Шаг 3: Включение инструментации для приложения

Добавьте аннотацию к Pod или Deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-java-app
spec:
  template:
    metadata:
      annotations:
        instrumentation.opentelemetry.io/inject-java: "opentelemetry/default"
    spec:
      containers:
      - name: app
        image: my-java-app:latest
```

**Аннотации для различных языков:**

| Язык | Аннотация |
| :--- | :--- |
| **Java** | `instrumentation.opentelemetry.io/inject-java` |
| **Python** | `instrumentation.opentelemetry.io/inject-python` |
| **Node.js** | `instrumentation.opentelemetry.io/inject-nodejs` |
| **Go** | `instrumentation.opentelemetry.io/inject-go` |
| **Все** | `instrumentation.opentelemetry.io/inject` |

---

## Дополнительная информация

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Operator Pod не запускается** | Недостаточно памяти | Увеличить лимиты: `--set manager.resources.limits.memory=512Mi` |
| **Collector в статусе Pending** | CRD не установлены | Проверить `kubectl get crds \| grep opentelemetry` |
| **Нет телеметрии в бэкенде** | Неправильный endpoint | Проверить сервисы: `kubectl get svc -n tempo`, `kubectl get svc -n loki` |
| **OOMKilled Collector** | Высокая нагрузка | Увеличить `memory_limiter.limit_mib`, добавить реплики |
| **Auto-instrumentation не работает** | Аннотация не найдена | Проверить namespace Instrumentation и Pod, имя `default` |

### Диагностика

```bash
# Проверка CRD
kubectl get crds | grep opentelemetry.io

# Проверка Collector
kubectl get otelcol -n opentelemetry
kubectl describe otelcol default -n opentelemetry

# Проверка Instrumentation
kubectl get instrumentation -n opentelemetry

# Логи Collector
kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector --tail=100

# Проверка экспорта в Tempo
curl -k http://tempo.tempo:3200/ready

# Проверка экспорта в Loki
curl -k http://loki.loki:3100/loki/api/v1/labels

# Проверка метрик spanmetrics
kubectl port-forward svc/default-collector 8889:8889 -n opentelemetry
curl http://localhost:8889/metrics
```

### Ссылки на SSoT

- **OpenTelemetry:**
  - **[Overview](../../../OpenTelemetry/opentelemetry_overview.md)** — общая информация
  - **[Architecture & Signals](../../../OpenTelemetry/architecture_signals.md)** — сигналы и архитектура
  - **[OTLP Protocol](../../../OpenTelemetry/otlp_protocol.md)** — протокол передачи
  - **[Instrumentation SDK](../../../OpenTelemetry/instrumentation_sdk.md)** — инструментация
- **Helm Charts:**
  - **[OpenTelemetry Helm Charts](https://open-telemetry.github.io/opentelemetry-helm-charts/)**

### Безопасность

> **Внимание:** Данная конфигурация предназначена **только для локальных/тестовых окружений**.

| Аспект | Текущая конфигурация | Production-рекомендация |
| :--- | :--- | :--- |
| **TLS** | `insecure: true` для всех exporters | Включить TLS, использовать сертификаты |
| **Аутентификация** | Отсутствует | mTLS между Collector и бэкендами |
| **Сетевая изоляция** | Отсутствует | NetworkPolicies, отдельные namespace |
| **Сэмплирование** | Отсутствует | Включить `probabilistic_sampler` для снижения нагрузки |

### Альтернативы для production

| Компонент | Minikube (это руководство) | Production |
| :--- | :--- | :--- |
| **Collector режим** | `deployment` | `daemonset` или `statefulset` |
| **TLS** | Отключён | Включён с сертификатами от cert-manager |
| **Агент** | OTel Collector | Grafana Alloy (для логов и метрик) |
| **Сэмплирование** | Отсутствует | Head-based или Tail-based sampling |

### Ресурсы

- **[OTel Collector Documentation](https://opentelemetry.io/docs/collector/)**
- **[OTel Helm Charts](https://open-telemetry.github.io/opentelemetry-helm-charts/)**
- **[Instrumentation Annotations](https://github.com/open-telemetry/opentelemetry-operator/blob/main/docs/api.md)**

---

**Навигация по руководству:**

- **[← Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
- **[Тестирование и верификация →](./lgtm_otel_minikube_test_app_verification.md)**
