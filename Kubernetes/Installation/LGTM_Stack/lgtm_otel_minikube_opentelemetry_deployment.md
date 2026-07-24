# Развертывание OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)** (текущий)
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

---

## Определения

**OpenTelemetry (OTel)** — это открытый стандарт и набор инструментов для сбора, обработки и экспорта телеметрических данных (метрик, логов и трассировок). Подробнее: **[OpenTelemetry: Обзор](../../../OpenTelemetry/opentelemetry_overview.md)**.

**OpenTelemetry Operator** — Kubernetes-контроллер, автоматизирующий управление жизненным циклом OTel Collector и процессом инструментации приложений. Управляет ресурсами через CRD `OpenTelemetryCollector` и `Instrumentation`.

**OTel Collector** — центральный компонент для обработки данных, работающий по принципу конвейера (Receivers -> Processors -> Exporters). Подробнее: **[Архитектура и сигналы](../../../OpenTelemetry/architecture_signals.md)**.

**Автоматическая инструментация** — механизм внедрения OTel SDK в среду выполнения приложения (например, через Java Agent) без изменения исходного кода. Подробнее: **[Инструментация и SDK](../../../OpenTelemetry/instrumentation_sdk.md)**.

**OTLP (OpenTelemetry Line Protocol)** — универсальный протокол передачи телеметрии, используемый для взаимодействия всех компонентов OTel. Подробнее: **[Протокол OTLP](../../../OpenTelemetry/otlp_protocol.md)**.

---

## Основные концепции

### Архитектура OpenTelemetry в кластере

```text
┌─────────────────────────────────────────────────────────────────┐
│                     Minikube Cluster                            │
│                                                                 │
│  ┌─────────────────┐     ┌─────────────────────────────────┐   │
│  │   Приложение    │     │   OpenTelemetry Operator        │   │
│  │   (Java/OTel)   │     │   (v0.156.0)                    │   │
│  │                 │     │                                 │   │
│  │  ┌───────────┐  │     │  ┌───────────────────────────┐  │   │
│  │  │ OTel SDK  │──┼─────┼─▶│  OpenTelemetryCollector   │  │   │
│  │  └───────────┘  │OTLP │  │  (v0.155.0)               │  │   │
│  └─────────────────┘     │  └─────────────┬─────────────┘  │   │
│                          │                │                 │   │
│                          │  ┌─────────────▼─────────────┐  │   │
│                          │  │    Instrumentation CRD    │  │   │
│                          │  │  (Auto-instrumentation)   │  │   │
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

### Основные компоненты Collector

| Группа | Назначение | Используемые в Minikube |
| :--- | :--- | :--- |
| **Receivers** | Прием входящих данных | `otlp` (gRPC/HTTP) |
| **Processors** | Преобразование и фильтрация | `batch`, `spanmetrics`, `memory_limiter`, `resourcedetection` |
| **Exporters** | Отправка в системы хранения | `otlp` (Tempo), `loki`, `prometheus` |

### Ресурсные профили (Minikube)

| Компонент | CPU (request/limit) | Memory (request/limit) |
| :--- | :--- | :--- |
| **OTel Operator** | 100m / 500m | 128Mi / 512Mi |
| **OTel Collector** | 100m / 500m | 256Mi / 1024Mi |
| **Java Agent** | 50m / 200m (на Pod) | 128Mi / 512Mi (на Pod) |

---

## Практические сценарии

### Сценарий 1: Установка OpenTelemetry Operator

**Цель:** Подготовить кластер к управлению ресурсами OpenTelemetry.

#### Шаг 1: Добавление репозитория Helm

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update
```

#### Шаг 2: Установка оператора

На июль 2026 г. используется версия чарта v0.120.0 (Operator v0.156.0).

```bash
helm upgrade --install opentelemetry-operator \
  open-telemetry/opentelemetry-operator \
  --namespace opentelemetry-operator \
  --create-namespace \
  --set admissionWebhooks.certManager.enabled=true
```

---

### Сценарий 2: Развертывание и настройка OTel Collector

**Цель:** Настройка конвейера обработки сигналов для передачи в стек LGTM.

#### Шаг 1: Применение конфигурации Collector

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: OpenTelemetryCollector
metadata:
  name: otel-collector
  namespace: opentelemetry
spec:
  mode: deployment
  replicas: 1
  config: |
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
          http:
            endpoint: 0.0.0.0:4318
    
    processors:
      memory_limiter:
        check_interval: 1s
        limit_percentage: 80
        spike_limit_percentage: 25
      
      batch:
        timeout: 1s
        send_batch_size: 1024
      
      resourcedetection:
        detectors: [env, system, k8snode]
      
      spanmetrics:
        metrics_exporter: prometheus
        dimensions:
          - name: service.name
          - name: span.name
    
    exporters:
      otlp:
        endpoint: tempo.tempo:4317
        tls:
          insecure: true
      
      loki:
        endpoint: http://loki.loki:3100/loki/api/v1/push
      
      prometheus:
        endpoint: 0.0.0.0:8889
    
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, resourcedetection, spanmetrics, batch]
          exporters: [otlp]
        metrics:
          receivers: [otlp]
          processors: [memory_limiter, resourcedetection, batch]
          exporters: [prometheus]
        logs:
          receivers: [otlp]
          processors: [memory_limiter, resourcedetection, batch]
          exporters: [loki]
```

#### Шаг 2: Применение манифеста

```bash
kubectl apply -f - <<EOF
# (вставить содержимое yaml выше)
EOF
```

---

### Сценарий 3: Настройка автоматической инструментации

**Цель:** Подготовка глобального профиля инструментации для Java-приложений.

#### Шаг 1: Создание ресурса Instrumentation

Используется актуальный агент v2.29.0.

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: java-instrumentation
  namespace: opentelemetry
spec:
  exporter:
    endpoint: http://otel-collector.opentelemetry:4317
  java:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:2.29.0
    env:
      - name: OTEL_LOGS_EXPORTER
        value: otlp
      - name: OTEL_METRICS_EXPORTER
        value: otlp
      - name: OTEL_TRACES_EXPORTER
        value: otlp
```

---

## Дополнительная информация

### Поиск и устранение неисправностей

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Collector в CrashLoopBackOff** | Ошибка в YAML-конфигурации | Проверить логи: `kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector` |
| **Нет трейсов в Tempo** | Неверный эндпоинт экспортера | Проверить доступность `tempo.tempo:4317` внутри кластера |
| **Метрики не доходят до Prometheus** | Ошибка скрейпинга | Проверить порт `8889` и наличие аннотаций Prometheus в сервисе коллектора |
| **Агент не внедряется** | Отсутствует cert-manager | Убедиться, что cert-manager установлен (необходим для webhooks оператора) |

### Диагностика

```bash
# Статус ресурсов оператора
kubectl get otelcol,instrumentation -n opentelemetry

# Внутренние метрики коллектора (длина очередей, батчи)
kubectl port-forward -n opentelemetry svc/otel-collector-monitoring 8888:8888
# curl localhost:8888/metrics
```

### Связанные темы

- **[OpenTelemetry: Обзор](../../../OpenTelemetry/opentelemetry_overview.md)**
- **[Архитектура и сигналы](../../../OpenTelemetry/architecture_signals.md)**
- **[Инструментация и SDK](../../../OpenTelemetry/instrumentation_sdk.md)**
- **[Grafana Alloy](../../../Grafana/grafana_alloy_overview.md)** — современная альтернатива для экосистемы Grafana.

### Безопасность и Production

> **Внимание:** Данная конфигурация оптимизирована для Minikube.

| Аспект | Minikube (Dev) | Production (рекомендация) |
| :--- | :--- | :--- |
| **TLS** | Insecure (отключен) | mTLS между всеми компонентами |
| **Режим Collector** | Deployment | DaemonSet (Agent) + Deployment (Gateway) |
| **Сэмплирование** | 100% (без сэмплирования) | Tail-based sampling для снижения нагрузки |
| **Хранение** | Эфемерное | S3/GCS для Tempo/Loki, EBS для Prometheus |

---

**Навигация по руководству:**

- **[Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)** (назад)
- **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)** (вперед)

