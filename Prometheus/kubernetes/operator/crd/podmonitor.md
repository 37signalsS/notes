# CRD PodMonitor

## Определения

**`kind: PodMonitor`** — Custom Resource Definition для описания целей для скрейпинга напрямую из подов (без Kubernetes Service).

## Пример конфигурации

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

## Основные параметры spec

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`selector`** | Селектор Pod | `matchLabels: {app: my-app}` |
| **`namespaceSelector`** | Селектор namespace | `matchNames: [production]` |
| **`podMetricsEndpoints`** | Список endpoints для скрейпинга | См. ниже |
| **`jobLabel`** | Лейбл для имени задачи | `app` |
| **`podTargetLabels`** | Лейблы из пода для добавления | `[pod, container]` |
| **`sampleLimit`** | Лимит сэмплов | `10000` |
| **`targetLimit`** | Лимит целей | `100` |

## Параметры podMetricsEndpoints

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
| **`metricRelabelings`** | Релейблинг метрик | См. ниже |
| **`relabelings`** | Релейблинг целей | См. ниже |

## Пример с несколькими портами

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

## PodMonitor vs ServiceMonitor

| Характеристика | PodMonitor | ServiceMonitor |
| :--- | :--- | :--- |
| **Объект** | Pod | Service |
| **Требует Service** | Нет | Да |
| **Использование** | Прямой мониторинг подов | Мониторинг через Service |
| **Гибкость** | Выше (прямой доступ) | Ниже (через Service) |
| **Рекомендация** | Для stateful-приложений | Для stateless-приложений |

**Преимущество PodMonitor:** Не требует создания Service для мониторинга.

## Релейблинг

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

## Связанные темы

* **[ServiceMonitor](./servicemonitor.md)** — мониторинг через Service
* **[Service Discovery](../../service_discovery.md)** — обнаружение целей
* **[Prometheus CRD](./prometheus.md)** — описание Prometheus
