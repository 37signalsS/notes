# Prometheus Operator — Концепции

## Definitions

**Prometheus Operator** — контроллер Kubernetes для автоматизации управления стеком мониторинга (Prometheus, Alertmanager, Grafana). Использует Custom Resource Definitions (CRD) для декларативного управления конфигурацией. Развертывается как Deployment в кластере.

> **См. также:** [Kubernetes Operators](../../../Kubernetes/Concepts/kubernetes_operators.md), [kube-prometheus-stack](../Kube_Prometheus_Stack_Helm/overview.md), [Ручная установка](./installation.md).

## Basic Concepts

### Архитектура и принцип работы

Prometheus Operator работает как контроллер Kubernetes с циклом reconciliation:

1. **Watch** — отслеживает изменения в CRD (ServiceMonitor, PrometheusRule, AlertmanagerConfig и др.)
2. **Generate** — генерирует конфигурацию Prometheus/Alertmanager на основе CRD
3. **Apply** — создает/обновляет Kubernetes-объекты (StatefulSet, ConfigMap, Secret, Service)
4. **Reload** — автоматически перезагружает конфигурацию при изменениях через sidecar `prometheus-config-reloader`

### Custom Resource Definitions (CRD)

Prometheus Operator расширяет Kubernetes API следующими CRD:

| CRD | Назначение | SSoT |
| :--- | :--- | :--- |
| **Prometheus** | Описание экземпляра Prometheus Server | [Prometheus CRD](./crd/prometheus.md) |
| **Alertmanager** | Описание экземпляра Alertmanager | [Alertmanager CRD](./crd/alertmanager.md) |
| **ServiceMonitor** | Описание целей для скрейпинга через Service | [ServiceMonitor](./crd/servicemonitor.md) |
| **PodMonitor** | Описание целей для скрейпинга напрямую из Pod | [PodMonitor](./crd/podmonitor.md) |
| **PrometheusRule** | Правила алертинга и recording rules | [PrometheusRule](./crd/prometheusrule.md) |
| **Probe** | Blackbox-мониторинг через Blackbox Exporter | [Probe](./crd/probe.md) |
| **AlertmanagerConfig** | Маршрутизация и получатели алертов | [AlertmanagerConfig](./crd/alertmanagerconfig.md) |

### Принцип работы Service Discovery

Operator автоматически обнаруживает цели через Kubernetes API:

- **ServiceMonitor** → выбирает Service по label selector → находит Endpoints → добавляет в scrape-конфигурацию
- **PodMonitor** → выбирает Pod по label selector → добавляет в scrape-конфигурацию
- **PrometheusRule** → выбирает ConfigMap с правилами → монтирует в Prometheus

### RBAC и права доступа

Prometheus Operator требует следующие права:

- **ClusterRole** — чтение Service, Endpoints, Pod, Node, Ingress
- **ClusterRoleBinding** — для доступа ко всем namespace
- **Role** — управление Prometheus, Alertmanager, ConfigMap, Secret в target namespace

> **См. также:** [Access Control](./Security/access_control.md), [Secrets Best Practices](./Security/secrets_best_practices.md).

## Practical Scenarios

### Когда использовать Prometheus Operator

| Сценарий | Решение |
| :--- | :--- |
| **Production мониторинг** | Helm-чарт `kube-prometheus-stack` |
| **Кастомная установка** | Ручная установка CRD + Operator |
| **Мультикластер** | Thanos или Cortex с федерацией |
| **Edge/IoT** | Упрощенная установка без Grafana |

### Установка: предпочтительный способ

```bash
# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка с настройками по умолчанию
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
```

> **Детали:** [Kube-Prometheus-Stack Helm](../Kube_Prometheus_Stack_Helm/overview.md), [Online Installation](../Kube_Prometheus_Stack_Helm/practical_scenarios/online_installation.md).

### Проверка работоспособности

```bash
# Проверка CRD
kubectl get crd | grep monitoring.coreos.com

# Проверка Operator
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator

# Проверка Prometheus
kubectl get prometheus -n monitoring

# Проверка ServiceMonitor
kubectl get servicemonitor -n monitoring
```

### Troubleshooting базовые команды

```bash
# Логи Operator
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator

# Метрики reconciliation
prometheus_operator_reconcile_duration_seconds
prometheus_operator_reconcile_errors_total
```

> **Детали:** [Troubleshooting](./troubleshooting.md).

## Additional Information

### Актуальные версии

| Параметр | Значение | Дата проверки |
|---|---|---|
| **Последняя версия Operator** | `0.90.1` | Март 2026 |
| **Репозиторий** | [prometheus-operator/prometheus-operator](https://github.com/prometheus-operator/prometheus-operator) |
| **Минимальный Kubernetes** | 1.27+ (для kube-prometheus-stack) |
| **Release Schedule** | [prometheus-operator.dev/docs/community/release/](https://prometheus-operator.dev/docs/community/release/) |

> **Важно:** Версия `0.90.1` выпущена 25 марта 2026. Проверяйте [GitHub Releases](https://github.com/prometheus-operator/prometheus-operator/releases) для получения последних версий.

### Связанные компоненты

| Компонент | Описание | Файл |
|---|---|---|
| **High Availability** | HA Prometheus и Alertmanager | [High Availability](./high_availability.md) |
| **Grafana Integration** | Provisioning дашбордов и datasources | [Grafana Integration](./grafana_integration.md) |
| **Security** | Аутентификация, TLS, NetworkPolicy, Secrets | [Security Overview](./Security/index.md) |

### Эволюция версий

- **v0.81–v0.85** (март–август 2025): поддержка Prometheus 2.x, улучшение Thanos sidecar
- **v0.86–v0.89** (октябрь 2025 – февраль 2026): поддержка Prometheus 3.x, улучшение AlertmanagerConfig
- **v0.90+** (март 2026): стабилизация API, улучшение reconciliation

### Метрики для мониторинга Operator

| Метрика | Описание |
| :--- | :--- |
| `prometheus_operator_reconcile_duration_seconds` | Длительность reconciliation |
| `prometheus_operator_reconcile_errors_total` | Ошибки reconciliation |
| `prometheus_operator_spec_replicas` | Количество реплик из spec |
| `prometheus_operator_node_sync_duration_seconds` | Длительность синхронизации узлов |

> **См. также:** [Troubleshooting](./troubleshooting.md), [Prometheus CRD](./crd/prometheus.md), [Alertmanager CRD](./crd/alertmanager.md).
