# CRD ServiceMonitor

## Definitions

**`kind: ServiceMonitor`** — Custom Resource Definition в Prometheus Operator для описания целей скрейпинга через Kubernetes Service. Operator использует Service для обнаружения Endpoints и генерации scrape-конфигурации.

**API version:** `monitoring.coreos.com/v1`

## Basic Concepts

### Принцип работы

1. Prometheus Operator находит ServiceMonitor по label selector
2. Запрашивает Kubernetes API для получения Endpoints сервиса
3. Генерирует `scrape_config` для Prometheus
4. Обновляет конфигурацию через Secret
5. `prometheus-config-reloader` перезагружает Prometheus

### Когда использовать ServiceMonitor

- **Stateless-приложения** — стандартный подход для веб-сервисов
- **Service уже существует** — не требуется дополнительная настройка
- **Стабильные endpoints** — Service абстрагирует изменения pod'ов
- **Балансировка нагрузки** — Service распределяет запросы между endpoints

### Отличие от PodMonitor

| Характеристика | ServiceMonitor | PodMonitor |
|---|---|---|
| **Объект** | Service | Pod |
| **Требует Service** | Да | Нет |
| **Meta-лейблы** | `__meta_kubernetes_endpoint_*`, `__meta_kubernetes_service_*` | `__meta_kubernetes_pod_*` |
| **Рекомендация** | Stateless-приложения | Stateful-приложения |

> **См. также:** [PodMonitor](./podmonitor.md) — мониторинг pod'ов напрямую (без Service).

## Practical Scenarios

### Базовая конфигурация

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
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
  endpoints:
    - port: web
      interval: 15s
      path: /metrics
```

### С namespaceSelector для всех namespace

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: global-monitor
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: my-app
  namespaceSelector:
    any: true
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
```

### С аутентификацией и TLS

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

### Ограничения (limits)

```yaml
spec:
  sampleLimit: 10000    # Лимит сэмплов на ServiceMonitor
  targetLimit: 100      # Лимит целей на ServiceMonitor
```

### Основные параметры spec

| Параметр | Описание | Пример |
|---|---|---|
| **`selector`** | Label selector Service | `matchLabels: {app: my-app}` |
| **`namespaceSelector`** | Селектор namespace | `matchNames: [production]` или `any: true` |
| **`endpoints`** | Список endpoints для скрейпинга | См. примеры выше |
| **`jobLabel`** | Лейбл Service для имени задачи | `app.kubernetes.io/name` |
| **`targetLabels`** | Лейблы Service для добавления к метрикам | `[environment, team]` |
| **`podTargetLabels`** | Лейблы Pod для добавления к метрикам | `[pod, container]` |
| **`sampleLimit`** | Лимит сэмплов | `10000` |
| **`targetLimit`** | Лимит целей | `100` |

### Параметры endpoints

| Параметр | Описание | Пример |
|---|---|---|
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
| **`followRedirects`** | Следовать редиректам | `true`, `false` |
| **`params`** | Query параметры | `{module: ['http_2xx']}` |
| **`metricRelabelings`** | Релейблинг метрик | См. выше |
| **`relabelings`** | Релейблинг целей | См. выше |

## Additional Information

### Связанные CRD

- [PodMonitor](./podmonitor.md) — мониторинг pod'ов напрямую (без Service)
- [Prometheus CRD](./prometheus.md) — описание экземпляра Prometheus
- [Probe](./probe.md) — blackbox-мониторинг

### Доступные meta-лейблы для ServiceMonitor

| Meta-лейбл | Описание |
|---|---|
| `__meta_kubernetes_namespace` | Namespace Service |
| `__meta_kubernetes_service_name` | Имя Service |
| `__meta_kubernetes_service_label_<labelname>` | Лейблы Service |
| `__meta_kubernetes_service_annotation_<annotationname>` | Аннотации Service |
| `__meta_kubernetes_endpoint_node_name` | Имя узла endpoint'а |
| `__meta_kubernetes_pod_name` | Имя pod'а endpoint'а |
| `__meta_kubernetes_pod_container_name` | Имя контейнера |
| `__meta_kubernetes_pod_label_<labelname>` | Лейблы pod'а |
| `__meta_kubernetes_pod_node_name` | Имя узла pod'а |
