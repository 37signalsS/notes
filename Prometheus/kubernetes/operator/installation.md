# Ручная установка Prometheus Operator

## Установка CRD

```bash
# Установка CRD по отдельности
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_servicemonitors.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_prometheusrules.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_podmonitors.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_probes.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_alertmanagers.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_prometheuses.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_alertmanagerconfigs.yaml
```

### Установка всех CRD сразу

```bash
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/
```

## Установка Operator

```bash
# Установка bundle.yaml (включает Operator, RBAC, Deployment)
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/bundle.yaml
```

## Проверка установки

```bash
# Проверка подов Operator
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator

# Проверка CRD
kubectl get crd | grep monitoring.coreos.com

# Проверка доступных CRD
kubectl get prometheus
kubectl get servicemonitor
kubectl get alertmanager
```

## Создание Prometheus через CRD

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 1
  version: v3.10.0
  serviceAccountName: prometheus
  serviceMonitorSelector:
    matchLabels:
      release: monitoring
  resources:
    requests:
      memory: 400Mi
      cpu: 200m
```

## Создание ServiceMonitor

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-app
  namespace: default
  labels:
    release: monitoring
spec:
  selector:
    matchLabels:
      app: my-app
  namespaceSelector:
    matchNames:
      - default
  endpoints:
    - port: web
      interval: 15s
      path: /metrics
```

## Предпочтительный способ: Helm

> **Рекомендация:** Используйте [Helm-чарт kube-prometheus-stack](../Kube_Prometheus_Stack_Helm/overview.md) для установки.

**Преимущества Helm:**

* Автоматическая установка всех CRD
* Настроенные дашборды Grafana
* Встроенные правила алертинга
* Простое обновление и откат

## Удаление

```bash
# Удаление Operator
kubectl delete -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/bundle.yaml

# Удаление CRD
kubectl delete -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/
```

**Важно:** Удаление CRD удалит все объекты Prometheus, Alertmanager, ServiceMonitor и т.д.

## Связанные темы

* **[Concepts](./concepts.md)** — базовые концепции Operator
* **[Kube-Prometheus-Stack Helm](../Kube_Prometheus_Stack_Helm/overview.md)** — установка через Helm
* **[CRD Prometheus](./crd/prometheus.md)** — описание Prometheus
