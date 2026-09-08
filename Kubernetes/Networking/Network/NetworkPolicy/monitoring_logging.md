# NetworkPolicy для стека мониторинга и логирования

## Определения

**Monitoring Stack** — совокупность компонентов для сбора, хранения и визуализации метрик: Prometheus (сбор), Grafana (визуализация), Alertmanager (алерты), node_exporter (метрики узлов), kube-state-metrics (метрики Kubernetes). Требует сетевого доступа от подов приложений (метрики) и к подам приложений (scrape).

**Logging Stack** — совокупность компонентов для сбора и хранения логов: Fluentd/Fluent Bit (сбор), Loki/Elasticsearch (хранение), Kibana/Grafana (визуализация). Требует egress-доступа к storage-бэкендам и ingress-доступа от приложений.

**Scrape** — процесс Prometheus-сервера по извлечению метрик из подов через HTTP-эндпоинт `/metrics`. Требует, чтобы NetworkPolicy разрешал трафик от Prometheus к целевым подам на порту метрик.

**ServiceMonitor** — ресурс Prometheus Operator для декларативного описания того, какие поды должны скрапиться, на каком порту и с какой частотой. NetworkPolicy должен разрешать трафик на порту, указанном в ServiceMonitor.

**Log Shipping** — процесс доставки логов из подов в централизованное хранилище. Требует egress-доступа от приложений (или DaemonSet-агента) к storage-бэкенду (Loki, Elasticsearch).

## Базовые Концепции

### Типичные порты monitoring/logging компонентов

| Компонент | Порт | Протокол | Назначение |
| :--- | :--- | :--- | :--- |
| **Prometheus** | 9090 | TCP | Web UI, API |
| **Prometheus** | 9091 | TCP | Remote write |
| **node_exporter** | 9100 | TCP | Метрики узла |
| **kube-state-metrics** | 8080 | TCP | Метрики K8s |
| **Alertmanager** | 9093 | TCP | Алерты |
| **Grafana** | 3000 | TCP | Dashboard |
| **Fluentd** | 24224 | TCP | Forward логов |
| **Fluent Bit** | 2020 | TCP | HTTP server |
| **Loki** | 3100 | TCP | Log API |
| **Elasticsearch** | 9200 | TCP | REST API |

### Архитектура трафика monitoring

```
┌─────────────────────────────────────────────────────────┐
│ Namespace: monitoring                                     │
│ ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│ │ Prometheus  │  │ Grafana     │  │ Alertmanager│       │
│ └──────┬──────┘  └──────┬──────┘  └──────┬──────┘       │
│        │ scrape          │ query          │ alert         │
└────────┼────────────────┼────────────────┼───────────────┘
         │                │                │
    ┌────▼────┐     ┌─────▼─────┐    ┌────▼────┐
    │ app ns  │     │ app ns    │    │ email/  │
    │ pods    │     │ pods      │    │ slack   │
    │ :9100   │     │ :8080     │    │         │
    └─────────┘     └───────────┘    └─────────┘
```

## Практические сценарии

### Сценарий 1: Prometheus scrape с NetworkPolicy

Разрешение Prometheus скрапить метрики из подов в namespace `production`:

```yaml
# 1. NetworkPolicy для подов приложений (в namespace production)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-scrape
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
      podSelector:
        matchLabels:
          app: prometheus
    ports:
    - protocol: TCP
      port: 9090  # метрики приложения
    - protocol: TCP
      port: 8080  # альтернативный порт
---
# 2. Prometheus должен иметь egress к подам приложений
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-egress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app: prometheus
  policyTypes:
  - Egress
  egress:
  # DNS
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
  # Все поды во всех namespace (для scrape)
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 9090
    - protocol: TCP
      port: 8080
    - protocol: TCP
      port: 9100
```

### Сценарий 2: node_exporter + NetworkPolicy

node_exporter работает как DaemonSet и должен быть доступен для scrape:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-scrape-node
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app: node-exporter
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
      podSelector:
        matchLabels:
          app: prometheus
    ports:
    - protocol: TCP
      port: 9100
---
# node_exporter должен иметь доступ к метрикам узла
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-node-exporter-egress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app: node-exporter
  policyTypes:
  - Egress
  egress:
  # DNS
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
```

### Сценарий 3: Loki + Fluent Bit (логирование)

Fluent Bit собирает логи и отправляет в Loki:

```yaml
# 1. Fluent Bit DaemonSet (в namespace logging)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-fluent-bit-to-loki
  namespace: logging
spec:
  podSelector:
    matchLabels:
      app: fluent-bit
  policyTypes:
  - Egress
  egress:
  # DNS
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
  # Loki
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: logging
      podSelector:
        matchLabels:
          app: loki
    ports:
    - protocol: TCP
      port: 3100
---
# 2. Loki должен принимать логи
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-loki-ingress
  namespace: logging
spec:
  podSelector:
    matchLabels:
      app: loki
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: logging
      podSelector:
        matchLabels:
          app: fluent-bit
    ports:
    - protocol: TCP
      port: 3100
  # Grafana для запросов логов
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
      podSelector:
        matchLabels:
          app: grafana
    ports:
    - protocol: TCP
      port: 3100
```

### Сценарий 4: Alertmanager outbound (email, Slack)

Alertmanager отправляет алерты во внешние сервисы:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-alertmanager-egress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app: alertmanager
  policyTypes:
  - Egress
  egress:
  # DNS
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
  # SMTP (email)
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - protocol: TCP
      port: 587
    - protocol: TCP
      port: 465
  # Slack webhook
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - protocol: TCP
      port: 443
```

## Дополнительная информация

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Prometheus target DOWN | NetworkPolicy блокирует scrape | Разрешить Ingress от Prometheus на порту метрик |
| Grafana не показывает метрики | Prometheus не может скрапить поды | Разрешить egress от Prometheus ко всем namespace |
| Loki не получает логи | Fluent Bit не может достучаться до Loki | Разрешить egress от Fluent Bit к Loki (порт 3100) |
| Alertmanager не отправляет алерты | Egress SMTP/HTTPS заблокирован | Разрешить egress на порты 587, 465, 443 |
| node_exporter не скрапивается | DaemonSet в namespace с Default Deny | Добавить Ingress-правило для Prometheus |

### Рекомендации

| Компонент | Рекомендация |
| :--- | :--- |
| **Prometheus** | Egress на все namespace для scrape; Ingress на 9090 для Grafana |
| **Alertmanager** | Egress на SMTP и HTTPS для отправки алертов |
| **Loki** | Ingress от Fluent Bit и Grafana; egress к storage (S3, GCS) |
| **Fluent Bit** | Egress к Loki/Elasticsearch и DNS |
| **Grafana** | Egress к Prometheus (9090) и Loki (3100) |

### См. также

* [NetworkPolicy: Лучшие практики](./best_practices.md) — рекомендации
* [NetworkPolicy: Egress паттерны](./egress_patterns.md) — управление исходящим трафиком
* [NetworkPolicy: Multi-tenancy](./multi_tenancy.md) — изоляция тенантов
