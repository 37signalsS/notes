# Ручная установка Prometheus Operator

## Определения

**Ручная установка Prometheus Operator** — способ развёртывания Prometheus Operator без использования Helm. CRD и Operator устанавливаются напрямую через `kubectl apply` из манифестов репозитория `prometheus-operator/prometheus-operator`. Применяется при кастомных требованиях к установке или когда Helm недоступен.

> **Рекомендация:** Для большинства сценариев используйте [Helm-чарт kube-prometheus-stack](../Kube_Prometheus_Stack_Helm/overview.md). Ручная установка требует самостоятельного управления всеми компонентами стека.

> **См. также:** [Концепции Prometheus Operator](./concepts.md), [Online Installation через Helm](../Kube_Prometheus_Stack_Helm/practical_scenarios/online_installation.md).

## Основные концепции

### Что устанавливается вручную

В отличие от Helm-чарта, ручная установка включает только Prometheus Operator (контроллер). Остальные компоненты (Prometheus, Alertmanager, Grafana, экспортеры) создаются отдельно через CRD.

| Компонент | Helm (kube-prometheus-stack) | Ручная установка |
|---|---|---|
| CRD | Автоматически | Вручную (`kubectl apply`) |
| Prometheus Operator | Автоматически | Вручную (`bundle.yaml`) |
| Prometheus Server | Через `prometheus.prometheusSpec` | Через CRD `Prometheus` |
| Alertmanager | Через `alertmanager.alertmanagerSpec` | Через CRD `Alertmanager` |
| Grafana | Через subchart `grafana.*` | Отдельно (Deployment + Sidecar) |
| Node Exporter | Через `nodeExporter.*` | Отдельно (DaemonSet) |
| Kube-State-Metrics | Через subchart | Отдельно (Deployment) |

### Источники манифестов

Официальные манифесты расположены в репозитории [prometheus-operator/prometheus-operator](https://github.com/prometheus-operator/prometheus-operator):

- **CRD** — `example/prometheus-operator-crd/`
- **Bundle (Operator + RBAC + Deployment)** — `bundle.yaml`

### Версии

| Параметр | Значение |
|---|---|
| **Версия Operator** | `0.89.0` (в манифестах) |
| **Минимальный Kubernetes** | `1.16+` |

> **Важно:** Версии в примерах ниже могут быть устаревшими. Проверяйте актуальную версию в [GitHub Releases](https://github.com/prometheus-operator/prometheus-operator/releases) и в [Концепциях Prometheus Operator](./concepts.md).

## Практические сценарии

### Сценарий 1: Установка CRD

**Отдельная установка каждого CRD:**

```bash
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_servicemonitors.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_prometheusrules.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_podmonitors.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_probes.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_alertmanagers.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_prometheuses.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/monitoring.coreos.com_alertmanagerconfigs.yaml
```

**Установка всех CRD сразу:**

```bash
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/
```

### Сценарий 2: Установка Operator

```bash
# Создание namespace
kubectl create namespace monitoring

# Установка bundle (Operator + RBAC + Deployment)
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/bundle.yaml
```

### Сценарий 3: Проверка установки

```bash
# Проверка CRD
kubectl get crd | grep monitoring.coreos.com

# Проверка Pod Operator
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator
```

### Сценарий 4: Создание Prometheus через CRD

После установки Operator создайте экземпляр Prometheus:

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

```bash
kubectl apply -f prometheus-instance.yaml
```

### Сценарий 5: Создание ServiceMonitor

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

```bash
kubectl apply -f servicemonitor.yaml
```

### Сценарий 6: Удаление

```bash
# Удаление Operator
kubectl delete -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/bundle.yaml

# Удаление CRD
kubectl delete -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.89.0/example/prometheus-operator-crd/
```

> **Важно:** Удаление CRD приведёт к потере всех Custom Resources — Prometheus, Alertmanager, ServiceMonitor, PrometheusRule и др.

## Дополнительная информация

### Сравнение с Helm-установкой

| Критерий | Ручная установка | Helm (kube-prometheus-stack) |
|---|---|---|
| Сложность | Высокая | Низкая |
| CRD | Вручную | Автоматически |
| Grafana | Отдельно | Включена (subchart) |
| Экспортеры | Отдельно | Включены (Node Exporter, KSM) |
| Дашборды | Вручную | Встроенные |
| Обновление | Вручную | `helm upgrade` |
| Откат | Вручную | `helm rollback` |
| Версионирование | Git + манифесты | Helm release + `values.yaml` |

> **Подробности Helm-установки:** [Online Installation](../Kube_Prometheus_Stack_Helm/practical_scenarios/online_installation.md), [Обзор kube-prometheus-stack](../Kube_Prometheus_Stack_Helm/overview.md).

### Связанные темы

- **[Концепции Prometheus Operator](./concepts.md)** — CRD и архитектура
- **[Prometheus CRD](./crd/prometheus.md)** — описание CRD Prometheus
- **[ServiceMonitor CRD](./crd/servicemonitor.md)** — описание CRD ServiceMonitor
- **[High Availability](./high_availability.md)** — HA конфигурация
- **[Troubleshooting](./troubleshooting.md)** — диагностика проблем
- **[Grafana Integration](./grafana_integration.md)** — интеграция с Grafana
