# PodMonitor — Концепции (CRD)

## Определения

**`kind: PodMonitor`** — Custom Resource Definition в Prometheus Operator для описания целей скрейпинга напрямую из Pod, без промежуточного Kubernetes Service. Альтернатива [ServiceMonitor](./servicemonitor.md), используемая в случаях, когда создание Service является избыточным или невозможным.

**API version:** `monitoring.coreos.com/v1`

## Базовые концепции

### Принцип работы

1. Prometheus Operator находит PodMonitor по label selector.
2. Запрашивает Kubernetes API для получения списка Pod, соответствующих селектору.
3. Генерирует `scrape_config` для Prometheus на основе обнаруженных IP-адресов подов.
4. Обновляет конфигурацию через Kubernetes Secret.
5. Sidecar-контейнер `prometheus-config-reloader` инициирует перезагрузку конфигурации Prometheus.

### Когда использовать PodMonitor

- **Stateful-приложения** (базы данных, очереди сообщений) — когда требуется прямой доступ к метрикам каждого пода.
- **Приложения без Service** — когда не требуется балансировка трафика или абстракция Service для работы мониторинга.
- **Специфические порты контейнеров** — скрейпинг напрямую с конкретного порта контейнера, который может не быть экспонирован через Service.
- **Динамические топологии** — когда количество и состав подов меняются часто, и прямое обнаружение эффективнее.

### Отличие от ServiceMonitor

| Характеристика | PodMonitor | ServiceMonitor |
| :--- | :--- | :--- |
| **Объект обнаружения** | Pod | Service |
| **Зависимость от Service** | Нет | Да |
| **Meta-лейблы** | `__meta_kubernetes_pod_*` | `__meta_kubernetes_endpoint_*`, `__meta_kubernetes_service_*` |
| **Рекомендация** | Stateful-приложения | Stateless-приложения |

> **См. также:** [ServiceMonitor CRD](./servicemonitor.md) — мониторинг через Service.

## Практические сценарии

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

### Мониторинг нескольких портов

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

### Конфигурация с TLS и аутентификацией

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
  podMetricsEndpoints:
    - port: https
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

### Настройка релейблинга (Relabelings)

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

### Лимиты и ограничения

```yaml
spec:
  sampleLimit: 10000    # Максимальное количество сэмплов на PodMonitor
  targetLimit: 100      # Максимальное количество целей на PodMonitor
```

## Дополнительная информация

### Основные параметры spec

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`selector`** | Label selector для поиска подов | `matchLabels: {app: my-app}` |
| **`namespaceSelector`** | Список namespace для поиска | `matchNames: [production]` или `any: true` |
| **`podMetricsEndpoints`** | Описание эндпоинтов скрейпинга | Список объектов (см. ниже) |
| **`jobLabel`** | Лейбл пода, используемый как имя job | `app` |
| **`podTargetLabels`** | Лейблы пода, переносимые в метрики | `[pod, container]` |
| **`sampleLimit`** | Глобальный лимит сэмплов | `10000` |
| **`targetLimit`** | Глобальный лимит целей | `100` |

### Параметры podMetricsEndpoints

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`port`** | Имя порта в контейнере | `metrics`, `web` |
| **`path`** | Путь к эндпоинту метрик | `/metrics` |
| **`interval`** | Интервал скрейпинга | `15s`, `30s` |
| **`scheme`** | Протокол (http/https) | `http` |
| **`tlsConfig`** | Настройки TLS | См. пример с TLS выше |
| **`bearerTokenSecret`** | Токен из Kubernetes Secret | `name: my-secret, key: token` |
| **`scrapeTimeout`** | Таймаут скрейпинга | `10s` |
| **`metricRelabelings`** | Релейблинг самих метрик | См. раздел Relabelings |

### Доступные meta-лейблы для PodMonitor

| Meta-лейбл | Описание |
| :--- | :--- |
| `__meta_kubernetes_namespace` | Пространство имен пода |
| `__meta_kubernetes_pod_name` | Имя пода |
| `__meta_kubernetes_pod_container_name` | Имя контейнера |
| `__meta_kubernetes_pod_container_port_name` | Имя порта контейнера |
| `__meta_kubernetes_pod_node_name` | Имя узла, на котором запущен под |
| `__meta_kubernetes_pod_label_<labelname>` | Лейблы пода |
| `__meta_kubernetes_pod_annotation_<annotationname>` | Аннотации пода |

### Связанные ресурсы

- [ServiceMonitor](./servicemonitor.md) — мониторинг через Kubernetes Service.
- [Prometheus CRD](./prometheus.md) — конфигурация экземпляра Prometheus Server.
- [Probe](./probe.md) — Blackbox-мониторинг внешних целей.
