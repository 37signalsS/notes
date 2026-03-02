# Prometheus Operator

## Определения

**Prometheus Operator** — контроллер Kubernetes для автоматизации управления стеком мониторинга (Prometheus, Alertmanager, Grafana). Использует Custom Resource Definitions (CRD) для декларативного управления конфигурацией.

> **См. также:** [Kubernetes Operators](../../Kubernetes/Concepts/kubernetes_operators.md), [kube-prometheus-stack](./overview.md).

## Основные концепции

### Актуальная версия (март 2026)

| Параметр | Значение |
|---|---|
| **Последняя версия** | `0.89.0` |
| **Дата выпуска** | 5 февраля 2026 |
| **Репозиторий** | [prometheus-operator/prometheus-operator](https://github.com/prometheus-operator/prometheus-operator) |
| **Минимальный Kubernetes** | 1.16.0 |

> **Важно:** Проверяйте [GitHub Releases](https://github.com/prometheus-operator/prometheus-operator/releases) для получения последних версий.

### Архитектура

Prometheus Operator работает как контроллер Kubernetes:

1. Отслеживает изменения в CRD (ServiceMonitor, PrometheusRule, etc.)
2. Генерирует конфигурацию Prometheus/Alertmanager
3. Создает/обновляет Kubernetes-объекты (StatefulSet, ConfigMap, Secret)
4. Автоматически перезагружает конфигурацию при изменениях

## Custom Resource Definitions (CRD)

### Prometheus

**`kind: Prometheus`** — описание экземпляра Prometheus Server:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  version: v3.10.0
  serviceAccountName: prometheus
  serviceMonitorSelector:
    matchLabels:
      release: monitoring
  resources:
    requests:
      memory: 400Mi
      cpu: 200m
    limits:
      memory: 2Gi
      cpu: 1000m
  retention: 15d
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: standard
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 50Gi
```

> **См. также:** [Prometheus Server](../installation/prometheus_server_installation.md).

### Alertmanager

**`kind: Alertmanager`** — описание экземпляра Alertmanager:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 3
  version: v0.31.0
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: standard
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
```

> **См. также:** [Alertmanager](../alertmanager.md).

### ServiceMonitor

**`kind: ServiceMonitor`** — описание целей для скрейпинга через Service:

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

**Как работает:**

1. Prometheus Operator находит ServiceMonitor по селектору
2. Запрашивает Kubernetes API для получения Endpoints сервиса
3. Генерирует scrape_config для Prometheus
4. Обновляет конфигурацию через Secret
5. `prometheus-config-reloader` перезагружает Prometheus

> **См. также:** [Service Discovery](./service_discovery.md).

### PodMonitor

**`kind: PodMonitor`** — мониторинг подов напрямую (без Service):

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

> **Преимущество:** Не требует создания Service для мониторинга.

### PrometheusRule

**`kind: PrometheusRule`** — правила алертинга и записи:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: my-app-rules
  namespace: monitoring
  labels:
    release: monitoring
spec:
  groups:
    - name: my-app-alerts
      rules:
        - alert: HighErrorRate
          expr: rate(http_requests_total{status="500"}[5m]) > 0.1
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "High error rate detected"
            description: "Error rate is {{ $value }} errors/sec"
```

> **См. также:** [Rules](../rules.md).

### Probe

**`kind: Probe`** — blackbox-мониторинг через Blackbox Exporter:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: google-probe
  namespace: monitoring
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: http_2xx
  targets:
    staticConfig:
      static:
        - https://google.com
        - https://example.com
```

> **См. также:** [Blackbox Exporter](../Exporters/blackbox_exporter.md).

### AlertmanagerConfig

**`kind: AlertmanagerConfig`** — маршрутизация и получатели:

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: AlertmanagerConfig
metadata:
  name: slack-config
  namespace: monitoring
spec:
  route:
    groupBy: ['alertname', 'job']
    groupWait: 30s
    groupInterval: 5m
    repeatInterval: 12h
    receiver: 'slack'
    routes:
      - matchers:
          - name: severity
            value: critical
        receiver: 'slack-critical'
  receivers:
    - name: 'slack'
      slackConfigs:
        - channel: '#monitoring'
          apiURL:
            name: slack-webhook
            key: url
    - name: 'slack-critical'
      slackConfigs:
        - channel: '#alerts-critical'
          apiURL:
            name: slack-webhook-critical
            key: url
```

> **См. также:** [Alertmanager configuration](../alertmanager.md).

## Практические сценарии

### Управление Grafana

Grafana не имеет CRD, но использует ConfigMap с лейблами:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboard-my-app
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: "My App"
data:
  my-app-dashboard.json: |
    {
      "title": "My App Dashboard",
      "panels": [...]
    }
```

**Принцип работы:**

1. ConfigMap с лейблом `grafana_dashboard: "1"` создается в namespace
2. Grafana sidecar обнаруживает ConfigMap
3. Монтирует JSON в Grafana
4. Grafana загружает дашборд

> **См. также:** [Grafana provisioning](../../Grafana/grafana_provisioning.md).

### Ручная установка Operator

```bash
# Установка CRD
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_servicemonitors.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_prometheusrules.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_podmonitors.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_probes.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_alertmanagers.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_prometheuses.yaml

# Установка Operator
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/bundle.yaml
```

> **Предпочтительный способ:** Используйте [Helm-чарт](./Kube_Prometheus_Stack_Helm/overview.md).

## Дополнительная информация

### Высокая доступность

**Prometheus:**

* Минимум 2 реплики для HA
* StatefulSet не перезапускается при падении ноды
* Используйте external storage для долгосрочных данных

**Alertmanager:**

* Минимум 3 реплики для кворума
* Кластеризация через `--cluster.listen-address`
* Дедупликация алертов между репликами

> **См. также:** [Alertmanager HA](../alertmanager.md#кластеризация).

### Безопасность

**1. Аутентификация:**

* Prometheus: встроенная (новые версии) или Ingress с Basic Auth
* Alertmanager: Ingress с аутентификацией
* Grafana: встроенная

**2. Network Policies:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prometheus-access
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
        - podSelector:
            matchLabels:
              app: grafana
      ports:
        - port: 9090
          protocol: TCP
```

**3. TLS:**

* Используйте Ingress с TLS для внешних соединений
* mTLS для внутренних соединений (опционально)

### Полезные метрики Operator

* `prometheus_operator_reconcile_duration_seconds` — длительность reconciliation
* `prometheus_operator_reconcile_errors_total` — ошибки reconciliation
* `prometheus_operator_spec_replicas` — количество реплик из spec
* `prometheus_operator_node_address_lookup_errors_total` — ошибки DNS

### Устранение неполадок

**ServiceMonitor не работает:**

```bash
# Проверка ServiceMonitor
kubectl get servicemonitor -n monitoring

# Проверка лейблов
kubectl get servicemonitor my-app -n production -o yaml | grep release

# Проверка Endpoints
kubectl get endpoints -n production -l app=my-app

# Логи Operator
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator
```

**Prometheus не скрейпит цели:**

* Проверьте лейбл `release` в ServiceMonitor
* Убедитесь, что Endpoint существует
* Проверьте логи Prometheus: `kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus`

### Связанные темы

* [Overview](./overview.md) — обзор мониторинга в Kubernetes
* [Service Discovery](./service_discovery.md) — обнаружение целей
* [Kube-Prometheus-Stack Helm](./Kube_Prometheus_Stack_Helm/overview.md) — установка через Helm
* [Configuration](../configuration.md) — настройка Prometheus
* [Rules](../rules.md) — правила алертинга
