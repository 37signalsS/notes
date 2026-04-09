# CRD PodMonitor

## Definitions

**`kind: PodMonitor`** — Custom Resource Definition в Prometheus Operator для описания целей скрейпинга напрямую из Pod, без промежуточного Kubernetes Service. Альтернатива [ServiceMonitor](./servicemonitor.md), когда создание Service избыточно.

**API version:** `monitoring.coreos.com/v1`

## Basic Concepts

### Принцип работы

1. Prometheus Operator находит PodMonitor по label selector
2. Запрашивает Kubernetes API для получения Pod, соответствующих селектору
3. Генерирует `scrape_config` для Prometheus
4. Обновляет конфигурацию через Secret
5. `prometheus-config-reloader` перезагружает Prometheus

### Когда использовать PodMonitor

- **Stateful-приложения** (базы данных, очереди) — прямой доступ к подам
- **Приложения без Service** — не требуется создавать Service только для мониторинга
- **Специфические порты контейнеров** — скрейпинг напрямую с конкретного порта
- **Высокая гибкость** — полный контроль над подами

### Отличие от ServiceMonitor

| Характеристика | PodMonitor | ServiceMonitor |
| :--- | :--- | :--- |
| **Объект** | Pod | Service |
| **Требует Service** | Нет | Да |
| **Meta-лейблы** | `__meta_kubernetes_pod_*` | `__meta_kubernetes_endpoint_*`, `__meta_kubernetes_service_*` |
| **Рекомендация** | Stateful-приложения | Stateless-приложения |

> **См. также:** [ServiceMonitor CRD](./servicemonitor.md) — мониторинг через Service.

## Practical Scenarios

### Базовая конфигурация

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: my-app
  namespace: production
  labels:
    release: monitoring
spec:
  selector:
    matchLabels:
      app: my-app
  namespaceSelector:
    matchNames:
      - production
  podMetricsEndpoints:
    - port: metrics
      interval: 15s
      path: /metrics
```

### Несколько портов

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: multi-port-app
  namespace: production
spec:
  selector:
    matchLabels:
      app: multi-port-app
  podMetricsEndpoints:
    - port: metrics
      path: /metrics
      interval: 15s
    - port: admin
      path: /admin/metrics
      interval: 30s
```

### С аутентификацией и TLS

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: secure-app
  namespace: production
spec:
  selector:
    matchLabels:
      app: secure-app
  namespaceSelector:
    matchNames:
      - production
  podMetricsEndpoints:
    - port: metrics
      path: /metrics
      scheme: https
      interval: 15s
      tlsConfig:
        caFile: /etc/prometheus/secrets/ca.crt
        certFile: /etc/prometheus/secrets/client.crt
        keyFile: /etc/prometheus/secrets/client.key
      bearerTokenSecret:
        name: prometheus-token
        key: token
```

### Relabelings (цели)

```yaml
podMetricsEndpoints:
  - port: metrics
    relabelings:
      - sourceLabels: [__meta_kubernetes_namespace]
        targetLabel: namespace
      - sourceLabels: [__meta_kubernetes_pod_name]
        targetLabel: pod
      - sourceLabels: [__meta_kubernetes_pod_container_name]
        targetLabel: container
```

### Metric Relabelings (метрики)

```yaml
podMetricsEndpoints:
  - port: metrics
    metricRelabelings:
      - sourceLabels: [__name__]
        regex: "go_.*"
        action: drop
```

### Ограничения (limits)

```yaml
spec:
  sampleLimit: 10000    # Лимит сэмплов на PodMonitor
  targetLimit: 100      # Лимит целей на PodMonitor
```

### Основные параметры spec

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`selector`** | Label selector Pod | `matchLabels: {app: my-app}` |
| **`namespaceSelector`** | Селектор namespace | `matchNames: [production]` |
| **`podMetricsEndpoints`** | Список endpoints для скрейпинга | См. примеры выше |
| **`jobLabel`** | Лейбл Pod для имени задачи | `app` |
| **`podTargetLabels`** | Лейблы Pod для добавления к метрикам | `[pod, container]` |
| **`sampleLimit`** | Лимит сэмплов | `10000` |
| **`targetLimit`** | Лимит целей | `100` |

### Параметры podMetricsEndpoints

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`port`** | Имя порта контейнера | `metrics`, `web` |
| **`path`** | Путь к метрикам | `/metrics` |
| **`interval`** | Интервал скрейпинга | `15s`, `30s` |
| **`scheme`** | Протокол | `http`, `https` |
| **`tlsConfig`** | TLS конфигурация | `caFile`, `certFile`, `keyFile` |
| **`bearerTokenSecret`** | Bearer token из Secret | `name: token-secret, key: token` |
| **`basicAuth`** | Basic аутентификация | `username`, `password` из Secret |
| **`honorLabels`** | Сохранять лейблы из метрик | `true`, `false` |
| **`scrapeTimeout`** | Тайм-аут скрейпинга | `10s` |
| **`metricRelabelings`** | Релейблинг метрик | См. выше |
| **`relabelings`** | Релейблинг целей | См. выше |

## Additional Information

### Связанные CRD

- [ServiceMonitor](./servicemonitor.md) — мониторинг через Service
- [Prometheus CRD](./prometheus.md) — описание экземпляра Prometheus
- [Probe](./probe.md) — blackbox-мониторинг

### Доступные meta-лейблы для PodMonitor

| Meta-лейбл | Описание |
| :--- | :--- |
| `__meta_kubernetes_namespace` | Namespace пода |
| `__meta_kubernetes_pod_name` | Имя пода |
| `__meta_kubernetes_pod_container_name` | Имя контейнера |
| `__meta_kubernetes_pod_container_image` | Image контейнера |
| `__meta_kubernetes_pod_container_port_name` | Имя порта |
| `__meta_kubernetes_pod_container_port_number` | Номер порта |
| `__meta_kubernetes_pod_node_name` | Имя узла |
| `__meta_kubernetes_pod_label_<labelname>` | Лейблы пода |
| `__meta_kubernetes_pod_annotation_<annotationname>` | Аннотации пода |

> **Примечание:** Для Node Exporter через PodMonitor доступен `__meta_kubernetes_pod_node_name` как ключ связывания с узлом.
