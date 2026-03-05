# CRD ServiceMonitor

## Определения

**`kind: ServiceMonitor`** — Custom Resource Definition для описания целей для скрейпинга через Kubernetes Service.

## Пример конфигурации

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-app
  namespace: production
  labels:
    release: monitoring  # Важно для Helm-установки
spec:
  selector:
    matchLabels:
      app: my-app
  namespaceSelector:
    matchNames:
      - production
  endpoints:
    - port: web
      interval: 15s
      path: /metrics
```

## Основные параметры spec

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`selector`** | Селектор Service | `matchLabels: {app: my-app}` |
| **`namespaceSelector`** | Селектор namespace | `matchNames: [production]` |
| **`endpoints`** | Список endpoints для скрейпинга | См. ниже |
| **`jobLabel`** | Лейбл для имени задачи | `app` |
| **`targetLabels`** | Лейблы для добавления к метрикам | `[environment, team]` |
| **`podTargetLabels`** | Лейблы из пода для добавления | `[pod, container]` |
| **`sampleLimit`** | Лимит сэмплов | `10000` |
| **`targetLimit`** | Лимит целей | `100` |

## Параметры endpoints

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`port`** | Имя порта Service | `web`, `metrics` |
| **`path`** | Путь к метрикам | `/metrics` |
| **`interval`** | Интервал скрейпинга | `15s`, `30s` |
| **`scheme`** | Протокол | `http`, `https` |
| **`tlsConfig`** | TLS конфигурация | `caFile`, `certFile`, `keyFile` |
| **`bearerTokenSecret`** | Bearer token из Secret | `name: token-secret, key: token` |
| **`basicAuth`** | Basic аутентификация | `username`, `password` из Secret |
| **`honorLabels`** | Сохранять лейблы из метрик | `true`, `false` |
| **`honorTimestamps`** | Сохранять timestamps | `true`, `false` |
| **`scrapeTimeout`** | Тайм-аут скрейпинга | `10s` |
| **`metricRelabelings`** | Релейблинг метрик | См. ниже |
| **`relabelings`** | Релейблинг целей | См. ниже |

## Пример с аутентификацией

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: secure-app
  namespace: production
spec:
  selector:
    matchLabels:
      app: secure-app
  endpoints:
    - port: https
      path: /metrics
      scheme: https
      tlsConfig:
        caFile: /etc/prometheus/secrets/ca.crt
        certFile: /etc/prometheus/secrets/client.crt
        keyFile: /etc/prometheus/secrets/client.key
      bearerTokenSecret:
        name: prometheus-token
        key: token
```

## Релейблинг

### Relabelings (цели)

```yaml
endpoints:
  - port: web
    relabelings:
      - sourceLabels: [__meta_kubernetes_namespace]
        targetLabel: namespace
      - sourceLabels: [__meta_kubernetes_pod_name]
        targetLabel: pod
      - sourceLabels: [__meta_kubernetes_service_name]
        targetLabel: service
```

### Metric Relabelings (метрики)

```yaml
endpoints:
  - port: web
    metricRelabelings:
      - sourceLabels: [__name__]
        regex: "go_.*"
        action: drop
      - sourceLabels: [instance]
        targetLabel: instance
        replacement: "static-value"
```

## Как работает ServiceMonitor

1. Prometheus Operator находит ServiceMonitor по селектору
2. Запрашивает Kubernetes API для получения Endpoints сервиса
3. Генерирует scrape_config для Prometheus
4. Обновляет конфигурацию через Secret
5. `prometheus-config-reloader` перезагружает Prometheus

## Связанные темы

* **[PodMonitor](./podmonitor.md)** — мониторинг подов напрямую (без Service)
* **[Service Discovery](../../service_discovery.md)** — обнаружение целей
* **[Prometheus CRD](./prometheus.md)** — описание Prometheus
