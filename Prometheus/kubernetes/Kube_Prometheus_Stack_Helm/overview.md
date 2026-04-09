# Обзор Helm-чарта kube-prometheus-stack

## Определения

**kube-prometheus-stack** — Helm-чарт для развёртывания полного стека мониторинга в Kubernetes. Управляет Prometheus, Alertmanager, Grafana, экспортерами и Prometheus Operator через декларативную конфигурацию `values.yaml`.

**Промежуточный чарт (umbrella chart)** — Helm-чарт, включающий зависимые subchart'ы (prometheus-node-exporter, kube-state-metrics, grafana).

> **См. также:** [Мониторинг Kubernetes — общий обзор](../overview.md), [Prometheus Operator](../operator/concepts.md), [Helm](../../../Kubernetes/ToolsUtilities/Helm/helm_overview.md).

## Основные концепции

### Актуальные версии

| Параметр | Значение | Дата проверки |
|---|---|---|
| **Версия чарта** | 82.x | Апрель 2026 |
| **Prometheus** | 3.10.x | Апрель 2026 |
| **Alertmanager** | 0.31.x | Апрель 2026 |
| **Grafana** | 12.x | Апрель 2026 |
| **Prometheus Operator** | 0.89.x | Апрель 2026 |
| **Минимальный Kubernetes** | 1.27+ | — |

> **Важно:** Проверяйте актуальные версии на [Artifact Hub](https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack).

### Архитектура стека

| Компонент | Тип объекта | Назначение |
|---|---|---|
| **Prometheus Server** | StatefulSet | Сбор и хранение метрик |
| **Alertmanager** | StatefulSet | Обработка и маршрутизация оповещений |
| **Grafana** | Deployment | Визуализация, дашборды, Unified Alerting |
| **Prometheus Operator** | Deployment | Управление стеком через CRD |
| **Node Exporter** | DaemonSet | Метрики хостов (CPU, память, диск, сеть) |
| **Kube-State-Metrics** | Deployment | Метрики объектов Kubernetes |
| **Blackbox Exporter** | Deployment | Blackbox-мониторинг (HTTP/TCP/ICMP) |
| **Configmap Reload** | Sidecar | Автоперезагрузка при изменении ConfigMap |

### Зависимости чарта

Чарт включает следующие subchart'ы:

| Subchart | Источник | Управление |
|---|---|---|
| `prometheus-node-exporter` | `prometheus-community/prometheus-node-exporter` | Через `nodeExporter.*` |
| `kube-state-metrics` | `prometheus-community/kube-state-metrics` | Через `kube-state-metrics.*` |
| `grafana` | `grafana-community/grafana` (субчарт) | Через `grafana.*` |
| `prometheus-windows-exporter` | `prometheus-community/prometheus-windows-exporter` | Через `windowsMonitoring.*` |

### Ключевые CRD

| CRD | Назначение | Файл |
|---|---|---|
| **ServiceMonitor** | Описание целей скрейпинга через Service | [Prometheus Operator CRD](../operator/crd/servicemonitor.md) |
| **PodMonitor** | Описание целей скрейпинга через Pod | [PodMonitor CRD](../operator/crd/podmonitor.md) |
| **PrometheusRule** | Правила алертинга и записи | [PrometheusRule CRD](../operator/crd/prometheusrule.md) |
| **Probe** | Blackbox-мониторинг | [Probe CRD](../operator/crd/probe.md) |
| **AlertmanagerConfig** | Маршрутизация алертов | [AlertmanagerConfig CRD](../operator/crd/alertmanagerconfig.md) |
| **Prometheus** | Описание экземпляра Prometheus | [Prometheus CRD](../operator/crd/prometheus.md) |
| **Alertmanager** | Описание экземпляра Alertmanager | [Alertmanager CRD](../operator/crd/alertmanager.md) |

## Практические сценарии

### Быстрый старт

```bash
# Создание namespace
kubectl create namespace monitoring

# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка с настройками по умолчанию
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
```

### Работа с локальной копией

**Рекомендация:** Используйте локальную копию чарта для версионирования конфигурации в Git.

```bash
# Скачивание чарта
helm pull prometheus-community/kube-prometheus-stack --untar
cd kube-prometheus-stack

# Копирование values.yaml в отдельный файл
cp values.yaml my-values.yaml

# Редактирование
vim my-values.yaml

# Установка с локальными значениями
helm install monitoring . \
  --namespace monitoring \
  --create-namespace \
  -f my-values.yaml
```

### Проверка установки

```bash
# Проверка подов
kubectl get pods -n monitoring

# Проверка ServiceMonitor
kubectl get servicemonitor -n monitoring

# Проверка CRD
kubectl get crd | grep monitoring.coreos.com

# Доступ к Prometheus
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090

# Доступ к Grafana
kubectl port-forward svc/monitoring-grafana -n monitoring 3000:80

# Пароль Grafana (из Secret)
kubectl get secret monitoring-grafana -n monitoring \
  -o jsonpath="{.data.admin-password}" | base64 -d
```

### Обновление

```bash
# Обновление репозитория
helm repo update

# Обновление релиза
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values.yaml

# Откат к предыдущей версии
helm rollback monitoring -n monitoring

# Проверка истории
helm history monitoring -n monitoring
```

### Удаление

```bash
# Удаление релиза
helm uninstall monitoring -n monitoring

# Удаление CRD (осторожно — удалит все Custom Resources!)
kubectl delete crd prometheuses.monitoring.coreos.com
kubectl delete crd alertmanagers.monitoring.coreos.com
kubectl delete crd servicemonitors.monitoring.coreos.com
kubectl delete crd podmonitors.monitoring.coreos.com
kubectl delete crd prometheusrules.monitoring.coreos.com
kubectl delete crd probes.monitoring.coreos.com
kubectl delete crd alertmanagerconfigs.monitoring.coreos.com
```

> **Важно:** Удаление CRD приведёт к потере всех Custom Resources — ServiceMonitor, PrometheusRule, Probe и др.

## Дополнительная информация

### Структура values.yaml

Основные секции `values.yaml`:

```yaml
# Prometheus Server
prometheus:
  prometheusSpec:
    retention: 15d
    resources:
      requests:
        memory: 400Mi
        cpu: 200m
      limits:
        memory: 2Gi
        cpu: 1000m
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 50Gi

# Alertmanager
alertmanager:
  alertmanagerSpec:
    replicas: 3
    storage:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn
          resources:
            requests:
              storage: 10Gi

# Grafana
grafana:
  adminPassword: "admin"
  persistence:
    enabled: true
    size: 10Gi
  sidecar:
    dashboards:
      enabled: true
      label: grafana_dashboard

# Экспортеры
nodeExporter:
  enabled: true

kubeStateMetrics:
  enabled: true
```

> **См. также:** [Prometheus config](./prometheus_config.md), [Alertmanager config](./alertmanager_config.md), [Grafana config](./grafana_config.md), [Exporters config](./exporters_config.md).

### Рекомендуемые ресурсы для small/medium кластеров

| Компонент | CPU request | Memory request | CPU limit | Memory limit |
|---|---|---|---|---|
| Prometheus | 200m | 400Mi | 1000m | 2Gi |
| Alertmanager | 100m | 128Mi | 200m | 256Mi |
| Grafana | 100m | 256Mi | 500m | 512Mi |
| Node Exporter | 50m | 64Mi | 150m | 128Mi |
| Kube-State-Metrics | 100m | 128Mi | 250m | 256Mi |

### Рекомендации по безопасности

**1. Пароль Grafana через Secret:**

```yaml
grafana:
  admin:
    existingSecret: "grafana-admin-secret"
    adminUserKey: "username"
    adminPasswordKey: "password"
```

**2. Network Policies:**

```yaml
prometheus:
  networkPolicy:
    enabled: true
    ingress:
      - from:
          - namespaceSelector:
              matchLabels:
                name: monitoring
          - podSelector:
              matchLabels:
                app: grafana
```

**3. TLS для Ingress:**

```yaml
prometheus:
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
      - prometheus.example.com
    tls:
      - secretName: prometheus-tls
        hosts:
          - prometheus.example.com
```

### Файлы конфигурации компонентов

| Компонент | Файл | Описание |
|---|---|---|
| Prometheus Server | [prometheus_config.md](./prometheus_config.md) | Ретенция, ресурсы, storage |
| Alertmanager | [alertmanager_config.md](./alertmanager_config.md) | Реплики, routing, PV |
| Grafana | [grafana_config.md](./grafana_config.md) | Sidecar, PV, плагины |
| Экспортеры | [exporters_config.md](./exporters_config.md) | Node Exporter, KSM, Blackbox |
| Прочие | [other_components_config.md](./other_components_config.md) | RBAC, defaultRules, Push Gateway |

### Связанные темы

* [Мониторинг Kubernetes — общий обзор](../overview.md) — концепции мониторинга в K8s
* [Prometheus Operator](../operator/concepts.md) — управление через CRD
* [Service Discovery](../service_discovery.md) — обнаружение целей
* [Практические сценарии](./practical_scenarios.md) — онлайн/оффлайн установка
* [Установка Prometheus на хост](../../installation/overview.md) — не-Kubernetes установка
* [Масштабирование](../../scaling/overview.md) — федерация, Thanos
