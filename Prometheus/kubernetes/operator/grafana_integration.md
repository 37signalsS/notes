# Интеграция с Grafana

## Обзор

Grafana не имеет собственного CRD в Prometheus Operator, но использует ConfigMap с лейблами для автоматического provisioning дашбордов.

## Управление дашбордами через ConfigMap

### Создание ConfigMap с дашбордом

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboard-my-app
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: "My App"
data:
  my-app-dashboard.json: |
    {
      "title": "My App Dashboard",
      "panels": [
        {
          "title": "Request Rate",
          "targets": [
            {
              "expr": "rate(http_requests_total[5m])",
              "legendFormat": "{{ method }}"
            }
          ]
        }
      ]
    }
```

## Принцип работы

1. ConfigMap с лейблом `grafana_dashboard: "1"` создается в namespace
2. Grafana sidecar обнаруживает ConfigMap
3. Монтирует JSON в Grafana
4. Grafana загружает дашборд

## Настройка Grafana Sidecar

В Helm-чарте kube-prometheus-stack:

```yaml
# values.yaml
grafana:
  sidecar:
    dashboards:
      enabled: true
      label: grafana_dashboard
      labelValue: "1"
      folder: /tmp/dashboards
      searchNamespace: ALL
```

## Источники данных (Datasources)

### Настройка через values.yaml

```yaml
grafana:
  datasources:
    datasources.yaml:
      apiVersion: 1
      datasources:
        - name: Prometheus
          type: prometheus
          access: proxy
          orgId: 1
          url: http://prometheus-server.monitoring.svc.cluster.local:80
          isDefault: true
          editable: false
        - name: Loki
          type: loki
          access: proxy
          orgId: 1
          url: http://loki-gateway.logging.svc.cluster.local:80
          editable: false
```

### Настройка через Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: grafana-datasources
  namespace: monitoring
type: Opaque
stringData:
  datasources.yaml: |
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        access: proxy
        url: http://prometheus-server.monitoring.svc.cluster.local:80
        isDefault: true
```

## Дашборды из Helm-чарта

kube-prometheus-stack включает встроенные дашборды:

* Kubernetes / Compute Resources / Cluster
* Kubernetes / Compute Resources / Namespace (pods)
* Kubernetes / Compute Resources / Node (pods)
* Prometheus / Overview
* Alertmanager / Overview

## Связанные темы

* **[Grafana Provisioning](../../../Grafana/grafana_provisioning.md)** — автоматическая настройка Grafana
* **[Prometheus CRD](./crd/prometheus.md)** — описание Prometheus
* **[Kube-Prometheus-Stack Helm](../Kube_Prometheus_Stack_Helm/overview.md)** — установка через Helm
