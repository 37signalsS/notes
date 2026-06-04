# Ручная установка Prometheus Operator

## Определения

**Ручная установка Prometheus Operator** — способ развёртывания Prometheus Operator без использования Helm. CRD и Operator устанавливаются напрямую через `kubectl apply` из манифестов репозитория `prometheus-operator/prometheus-operator`. Применяется при кастомных требованиях к установке или когда Helm недоступен.

> **Рекомендация:** Для большинства сценариев используйте [Helm-чарт kube-prometheus-stack](../Kube_Prometheus_Stack_Helm/overview.md). Ручная установка требует самостоятельного управления всеми компонентами стека.

> **См. также:** [Концепции Prometheus Operator](./concepts.md), [Online Installation через Helm](../Kube_Prometheus_Stack_Helm/practical_scenarios/online_installation.md).

## Базовые концепции

### Состав ручной установки

В отличие от Helm-чарта, ручная установка включает только Prometheus Operator (контроллер). Остальные компоненты (Prometheus, Alertmanager, Grafana, экспортеры) создаются отдельно через CRD или стандартные Kubernetes-манифесты.

| Компонент | Helm (kube-prometheus-stack) | Ручная установка |
|---|---|---|
| **CRD** | Автоматически | Вручную (`kubectl apply`) |
| **Prometheus Operator** | Автоматически | Вручную (`bundle.yaml`) |
| **Prometheus Server** | Через `prometheus.prometheusSpec` | Через [CRD Prometheus](./crd/prometheus.md) |
| **Alertmanager** | Через `alertmanager.alertmanagerSpec` | Через [CRD Alertmanager](./crd/alertmanager.md) |
| **Grafana** | Через subchart `grafana` | Отдельно (Deployment + Sidecar) |
| **Node Exporter** | Через `nodeExporter` | Отдельно (DaemonSet) |
| **Kube-State-Metrics** | Через subchart | Отдельно (Deployment) |

### Источники манифестов

Официальные манифесты расположены в репозитории [prometheus-operator/prometheus-operator](https://github.com/prometheus-operator/prometheus-operator):

- **CRD** — `example/prometheus-operator-crd/`
- **Bundle (Operator + RBAC + Deployment)** — `bundle.yaml`

### Актуальные версии

| Параметр | Значение |
|---|---|
| **Версия Operator** | `0.90.1` |
| **Минимальный Kubernetes** | `1.27+` |

> **Важно:** Проверяйте актуальную версию в [GitHub Releases](https://github.com/prometheus-operator/prometheus-operator/releases) и в [Концепциях Prometheus Operator](./concepts.md).

## Практические сценарии

### Сценарий 1: Установка CRD

Перед запуском Operator необходимо установить Custom Resource Definitions.

```bash
# Установка всех CRD из официального репозитория
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.90.1/example/prometheus-operator-crd/
```

Если требуется выборочная установка, можно указать конкретные файлы:
`monitoring.coreos.com_servicemonitors.yaml`, `monitoring.coreos.com_prometheuses.yaml` и др.

### Сценарий 2: Установка Operator

Установка контроллера, ролей RBAC и необходимых прав доступа.

```bash
# Создание namespace
kubectl create namespace monitoring

# Установка bundle (Operator + RBAC + Deployment)
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.90.1/bundle.yaml
```

### Сценарий 3: Проверка состояния

```bash
# Проверка регистрации CRD
kubectl get crd | grep monitoring.coreos.com

# Проверка работоспособности Operator
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator
```

### Сценарий 4: Создание экземпляра Prometheus

После установки Operator необходимо создать ресурс `Prometheus`, на основе которого будет запущен StatefulSet.

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
```

> **Детали конфигурации:** Полный список параметров и примеры доступны в [CRD Prometheus — Практические сценарии](./crd/prometheus.md#практические-сценарии).

### Сценарий 5: Создание ServiceMonitor

Для автоматического обнаружения целей (Service Discovery) используется ресурс `ServiceMonitor`.

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
  endpoints:
    - port: web
      interval: 15s
```

> **Детали конфигурации:** [CRD ServiceMonitor — Практические сценарии](./crd/servicemonitor.md#практические-сценарии).

### Сценарий 6: Удаление всех компонентов

```bash
# Удаление Operator и связанных RBAC
kubectl delete -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.90.1/bundle.yaml

# Удаление CRD (ВНИМАНИЕ: удалит все ресурсы Prometheus, ServiceMonitor и др.)
kubectl delete -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.90.1/example/prometheus-operator-crd/
```

## Дополнительная информация

### Сравнение с Helm-установкой

| Критерий | Ручная установка | Helm (kube-prometheus-stack) |
|---|---|---|
| **Сложность** | Высокая | Низкая |
| **Управление CRD** | Вручную | Автоматически |
| **Grafana** | Отдельно | Включена |
| **Экспортеры** | Отдельно | Включены (Node Exporter, KSM) |
| **Дашборды** | Вручную | Встроенные |
| **Обновление** | Вручную (`kubectl apply`) | `helm upgrade` |
| **Откат** | Вручную | `helm rollback` |

### Связанные компоненты

- **[Концепции Prometheus Operator](./concepts.md)** — архитектура и принцип работы
- **[Troubleshooting](./troubleshooting.md)** — диагностика проблем установки и работы
- **[High Availability](./high_availability.md)** — настройка отказоустойчивости
- **[Grafana Integration](./grafana_integration.md)** — подключение Grafana к стеку
