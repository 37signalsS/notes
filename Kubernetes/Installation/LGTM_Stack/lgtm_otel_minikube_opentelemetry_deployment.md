# Развертывание OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)** (текущий)
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

## Определения

**OpenTelemetry (OTel)** — стандарт для сбора телеметрии. Подробнее: **[OpenTelemetry: Обзор](../../../OpenTelemetry/opentelemetry_overview.md)**.

**OpenTelemetry Operator** — контроллер Kubernetes для управления OTel Collector и автоматической инструментации. Управляет CRD `OpenTelemetryCollector` и `Instrumentation`.

**OTel Collector** — компонент для обработки данных. Архитектура описана в **[OpenTelemetry: Сигналы](../../../OpenTelemetry/architecture_signals.md)**.

**Автоматическая инструментация** — процесс внедрения SDK без изменения кода. Подробнее: **[OpenTelemetry: SDK](../../../OpenTelemetry/instrumentation_sdk.md)**.

**OTLP** — протокол передачи данных. Спецификация: **[OpenTelemetry: OTLP](../../../OpenTelemetry/otlp_protocol.md)**.

**Spanmetrics** — процессор Collector для генерации RED-метрик из трассировок.

---

## Основные концепции

### Архитектура OTel в Kubernetes

```
┌─────────────────────────────────────────────────────────────────┐
│                     Minikube Cluster                            │
│                                                                 │
│  ┌─────────────────┐     ┌─────────────────────────────────┐   │
│  │   Приложение    │     │   OpenTelemetry Operator        │   │
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
│            │  (трейсы)    │      │   (логи)     │   │(метрики)│
│            │  :4317       │      │  :3100       │   │ :9090  │
│            └──────────────┘      └──────────────┘   └────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Компоненты OTel Collector

| Компонент | Назначение | Примеры |
| :--- | :--- | :--- |
| **Receivers** | Приём данных | `otlp`, `jaeger`, `zipkin`, `prometheus` |
| **Processors** | Обработка данных | `batch`, `attributes`, `spanmetrics`, `memory_limiter` |
| **Exporters** | Отправка данных | `otlp`, `loki`, `prometheus` |

### Конвейеры обработки (Pipelines)

1. **Трассировки:** `otlp/receiver → batch/spanmetrics → otlp/exporter → Tempo`
2. **Метрики:** `otlp/receiver → batch → prometheus/exporter → Prometheus`
3. **Логи:** `otlp/receiver → batch/attributes → loki/exporter → Loki`

### Требования к ресурсам

| Компонент | CPU (request/limit) | Memory (request/limit) |
| :--- | :--- | :--- |
| **OTel Operator** | 100m / 500m | 128Mi / 512Mi |
| **OTel Collector** | 100m / 500m | 128Mi / 512Mi |
| **Авто-инструментация** | 100m / 200m (на Pod) | 128Mi / 256Mi (на Pod) |

---

## Практические сценарии

### Сценарий 1: Установка OpenTelemetry Operator

**Цель:** Развернуть оператор для управления коллектором и инструментацией.

#### Шаг 1: Добавление репозитория Helm

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

---

### Сценарий 2: Развертывание OTel Collector

**Цель:** Настройка Collector для экспорта в Loki, Tempo и Prometheus.

#### Шаг 1: Создание манифеста коллектора

Создайте файл `otel-collector.yaml`:

```yaml
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
        histogram:
          explicit_bounds: [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]
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

#### Шаг 2: Применение конфигурации

```bash
kubectl apply -f otel-collector.yaml
```

---

### Сценарий 3: Настройка автоматической инструментации

**Цель:** Включение автоматической инъекции SDK для Java-приложений.

#### Шаг 1: Создание ресурса Instrumentation

```yaml
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
      - name: OTEL_METRICS_EXPORTER
        value: otlp
      - name: OTEL_TRACES_EXPORTER
        value: otlp
```

#### Шаг 2: Активация в приложении

Добавьте аннотацию к Deployment приложения:

```yaml
metadata:
  annotations:
    instrumentation.opentelemetry.io/inject-java: "opentelemetry/default"
```

---

## Дополнительная информация

### Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Нет телеметрии** | Ошибка эндпоинта | Проверить сервисы `loki` и `tempo` в кластере |
| **Агент не внедряется** | Ошибка аннотации | Проверить имя ресурса `Instrumentation` и пространство имен |
| **OOM Collector** | Высокая нагрузка | Увеличить лимиты памяти или количество реплик |

### Диагностика

```bash
# Логи коллектора
kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector --tail=100

# Проверка статуса CRD
kubectl get otelcol -A
kubectl get instrumentation -A
```

### Связанные темы

- **[OpenTelemetry: Обзор](../../../OpenTelemetry/opentelemetry_overview.md)**
- **[OpenTelemetry: Сигналы](../../../OpenTelemetry/architecture_signals.md)**
- **[OpenTelemetry: SDK](../../../OpenTelemetry/instrumentation_sdk.md)**

### Безопасность

> **Внимание:** Данная конфигурация предназначена только для тестовых окружений.

| Аспект | Рекомендация для Production |
| :--- | :--- |
| **TLS** | Обязательное использование TLS для всех экспортеров |
| **Аутентификация** | Внедрение mTLS и токенов доступа |
| **Изоляция** | Настройка NetworkPolicies для ограничения трафика |

### Альтернативы для эксплуатации (Production)

| Компонент | Описание |
| :--- | :--- |
| **Режим Collector** | Использование `daemonset` для сбора локальных метрик узла |
| **Агент** | Рассмотреть **[Grafana Alloy](../../../Grafana/grafana_alloy_overview.md)** для экосистемы Grafana |

### Полезные ресурсы

- **[Официальная документация OpenTelemetry](https://opentelemetry.io/docs/)**
- **[Репозиторий OTel Helm Charts](https://github.com/open-telemetry/opentelemetry-helm-charts)**
