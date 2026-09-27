# Мониторинг стека LGTM (Self-Monitoring)

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**
> - **[Мониторинг стека](./lgtm_monitoring_self_monitoring.md)** (текущий)

---

## Определения

**Self-Monitoring (самомониторинг)** — практика мониторинга инфраструктуры мониторинга. Включает сбор метрик, логов и трассировок самих компонентов стека наблюдаемости.

**Meta-Monitoring (мета-мониторинг)** — мониторинг мониторинга. Позволяет обнаружить ситуации, когда сам стек наблюдаемости деградирует или работает некорректно.

**Health Check (проверка работоспособности)** — механизм проверки доступности и корректности работы компонента через специальные endpoints (например, `/api/health`, `/ready`, `/-/healthy`).

**Service Level Objective для мониторинга** — целевые показатели доступности и производительности самого стека наблюдаемости. Например: "Prometheus должен быть доступен 99.9% времени".

---

## Основные концепции

### Архитектура самомониторинга

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                    Self-Monitoring Architecture                          │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Prometheus                                      │  │
│  │  • Метрики自身的 performance                                       │  │
│  │  • scrape他自己自己的 /metrics                                      │  │
│  │  • Алерты на деградацию                                            │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Loki                                            │  │
│  │  • Логи компонентов стека                                          │  │
│  │  • Ошибки и предупреждения                                        │  │
│  │  • Аналитика по компонентам                                        │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Tempo                                           │  │
│  │  • Трассировки запросов к стеку                                    │  │
│  │  • Производительность запросов                                     │  │
│  │  • Анализ задержек                                                 │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Grafana                                         │  │
│  │  • Дашборды здоровья стека                                         │  │
│  │  • Алерты на инциденты                                             │  │
│  │  • Визуализация метрик самомониторинга                             │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Ключевые метрики самомониторинга

| Компонент | Метрика | Описание | Алерт |
| :--- | :--- | :--- | :--- |
| **Prometheus** | `prometheus_tsdb_head_series` | Количество активных временных рядов | > 1M |
| **Prometheus** | `prometheus_rule_evaluation_duration_seconds` | Время выполнения правил | > 10s |
| **Loki** | `loki_ingester_streams_created_total` | Количество создаваемых потоков | Резкий рост |
| **Tempo** | `tempo_ingester_bytes_received_total` | Объем принятых данных | Стабильность |
| **Grafana** | `grafana_http_request_duration_seconds` | Время обработки запросов | P99 > 5s |
| **OTel Collector** | `otelcol_receiver_accepted_spans` | Принятые спаны | Стабильность |
| **OTel Collector** | `otelcol_exporter_sent_spans` | Отправленные спаны | Стабильность |

---

## Практические сценарии

### Сценарий 1: Настройка Prometheus для самомониторинга

**Цель:** Настроить Prometheus на сбор метрик自身的 производительности.

#### Шаг 1: Включение self-scrape

```yaml
prometheus:
  prometheusSpec:
    enableFeatures:
      - exemplars
      - otlp-write-receiver
    additionalScrapeConfigs:
      - job_name: 'prometheus-self'
        static_configs:
          - targets: ['localhost:9090']
        metrics_path: /metrics
```

#### Шаг 2: Создание правил алертинга для Prometheus

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: prometheus-self-monitoring
  namespace: monitoring
spec:
  groups:
    - name: prometheus-self
      rules:
        - alert: PrometheusTargetMissing
          expr: up == 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Prometheus target недоступен"
            description: "Target {{ $labels.instance }} недоступен более 5 минут"

        - alert: PrometheusHighQueryLatency
          expr: histogram_quantile(0.99, rate(prometheus_engine_query_duration_seconds_bucket[5m])) > 10
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Высокая латентность запросов Prometheus"
            description: "P99 латентность запросов превышает 10 секунд"

        - alert: PrometheusStorageNearFull
          expr: prometheus_tsdb_storage_blocks_bytes / (1024*1024*1024) > 50
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "Диск Prometheus заполняется"
            description: "Использование хранилища превышает 50 ГБ"
```

---

### Сценарий 2: Настройка логирования компонентов стека

**Цель:** Сбор логов всех компонентов стека LGTM в Loki.

#### Шаг 1: Настройка OTel Collector для сбора системных логов

```yaml
receivers:
  filelog:
    include:
      - /var/log/pods/monitoring_*/*/*.log
      - /var/log/pods/loki_*/*/*.log
      - /var/log/pods/tempo_*/*/*.log
      - /var/log/pods/opentelemetry_*/*/*.log
    exclude:
      - /var/log/pods/monitoring_*/*otel-collector*.log
    operators:
      - type: container
        id: container-parser
```

#### Шаг 2: Создание правил алертинга на ошибки в логах

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: lgtm-log-alerts
  namespace: monitoring
spec:
  groups:
    - name: lgtm-logs
      rules:
        - alert: LGTMComponentErrors
          expr: |
            sum by (namespace, app) (
              count_over_time({namespace=~"monitoring|loki|tempo|opentelemetry"} |~ "error|ERROR|panic"[5m])
            ) > 10
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Ошибки в компонентах LGTM"
            description: "Обнаружено более 10 ошибок в namespace {{ $labels.namespace }} за 5 минут"
```

---

### Сценарий 3: Дашборд здоровья стека LGTM

**Цель:** Создание единого дашборда для мониторинга всех компонентов.

#### Шаг 1: Экспорт дашборда

```json
{
  "dashboard": {
    "title": "LGTM Stack Health",
    "panels": [
      {
        "title": "Prometheus Health",
        "type": "stat",
        "targets": [
          {
            "expr": "up{job=\"prometheus\"}",
            "legendFormat": "{{instance}}"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "mappings": [
              {
                "type": "value",
                "options": {
                  "0": { "text": "DOWN", "color": "red" },
                  "1": { "text": "UP", "color": "green" }
                }
              }
            ]
          }
        }
      },
      {
        "title": "Loki Health",
        "type": "stat",
        "targets": [
          {
            "expr": "up{job=\"loki\"}",
            "legendFormat": "{{instance}}"
          }
        ]
      },
      {
        "title": "Tempo Health",
        "type": "stat",
        "targets": [
          {
            "expr": "up{job=\"tempo\"}",
            "legendFormat": "{{instance}}"
          }
        ]
      },
      {
        "title": "Grafana Health",
        "type": "stat",
        "targets": [
          {
            "expr": "up{job=\"grafana\"}",
            "legendFormat": "{{instance}}"
          }
        ]
      },
      {
        "title": "OTel Collector Health",
        "type": "stat",
        "targets": [
          {
            "expr": "up{job=\"otel-collector\"}",
            "legendFormat": "{{instance}}"
          }
        ]
      }
    ]
  }
}
```

---

### Сценарий 4: Мониторинг ресурсов стека

**Цель:** Отслеживание потребления ресурсов компонентами стека.

#### Шаг 1: Создание дашборда ресурсов

```json
{
  "dashboard": {
    "title": "LGTM Stack Resources",
    "panels": [
      {
        "title": "CPU Usage by Component",
        "type": "graph",
        "targets": [
          {
            "expr": "sum(rate(container_cpu_usage_seconds_total{namespace=~\"monitoring|loki|tempo|opentelemetry\"}[5m])) by (namespace)",
            "legendFormat": "{{namespace}}"
          }
        ]
      },
      {
        "title": "Memory Usage by Component",
        "type": "graph",
        "targets": [
          {
            "expr": "sum(container_memory_working_set_bytes{namespace=~\"monitoring|loki|tempo|opentelemetry\"}) by (namespace)",
            "legendFormat": "{{namespace}}"
          }
        ]
      },
      {
        "title": "Disk Usage",
        "type": "graph",
        "targets": [
          {
            "expr": "sum(kubelet_volume_stats_used_bytes{namespace=~\"monitoring|loki|tempo\"}) by (namespace, persistentvolumeclaim)",
            "legendFormat": "{{namespace}}/{{persistentvolumeclaim}}"
          }
        ]
      }
    ]
  }
}
```

---

### Сценарий 5: Мониторинг производительности запросов

**Цель:** Отслеживание времени выполнения запросов к стеку.

#### Шаг 1: Метрики времени запросов

```yaml
# Prometheus метрики
prometheus_http_request_duration_seconds{handler="/api/v1/query"}
prometheus_http_request_duration_seconds{handler="/api/v1/query_range"}

# Loki метрики
loki_request_duration_seconds{method="GET", route="/loki/api/v1/query"}

# Tempo метрики
tempo_request_duration_seconds{method="GET", route="/api/traces"}

# Grafana метрики
grafana_http_request_duration_seconds{handler="/api/ds/query"}
```

#### Шаг 2: Алерты на высокую латентность

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: lgtm-latency-alerts
  namespace: monitoring
spec:
  groups:
    - name: lgtm-latency
      rules:
        - alert: PrometheusHighLatency
          expr: histogram_quantile(0.99, rate(prometheus_http_request_duration_seconds_bucket[5m])) > 5
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Высокая латентность Prometheus"
            description: "P99 латентность запросов Prometheus превышает 5 секунд"

        - alert: LokiHighLatency
          expr: histogram_quantile(0.99, rate(loki_request_duration_seconds_bucket[5m])) > 10
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Высокая латентность Loki"
            description: "P99 латентность запросов Loki превышает 10 секунд"

        - alert: TempoHighLatency
          expr: histogram_quantile(0.99, rate(tempo_request_duration_seconds_bucket[5m])) > 5
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Высокая латентность Tempo"
            description: "P99 латентность запросов Tempo превышает 5 секунд"
```

---

## Дополнительная информация

### Чек-лист самомониторинга

| Компонент | Проверка | Статус |
| :--- | :--- | :--- |
| **Prometheus** | Self-scrape включен | ☐ |
| **Prometheus** | Алерты на здоровье настроены | ☐ |
| **Loki** | Логи компонентов собираются | ☐ |
| **Loki** | Алерты на ошибки настроены | ☐ |
| **Tempo** | Трассировки запросов собираются | ☐ |
| **Grafana** | Дашборд здоровья создан | ☐ |
| **OTel Collector** | Метрики自身的 производительности собираются | ☐ |

### Связанные материалы

- **[Prometheus: Конфигурация](../../../Prometheus/configuration.md)** — настройка self-scrape
- **[Grafana: Мониторинг как код](../../../Grafana/monitoring_as_code.md)** — управление дашбордами через Git
- **[Kubernetes: Мониторинг](../../../Kubernetes/MonitoringLogging/kubernetes-monitoring-logging-architecture.md)** — архитектура мониторинга K8s

---

**Навигация по руководству:**

- **[Оптимизация производительности](./lgtm_performance_tuning.md)** (назад)
- **[Обзор стека](./lgtm_otel_minikube_overview.md)** (в начало)
