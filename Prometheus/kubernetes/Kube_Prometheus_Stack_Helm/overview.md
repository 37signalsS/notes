# Конфигурация Helm-чарта kube-prometheus-stack: Обзор

## Определения

**kube-prometheus-stack** — Helm-чарт для развертывания и управления полным стеком мониторинга в Kubernetes. Включает Prometheus, Alertmanager, Grafana, экспортеры и CRD.

**values.yaml** — файл конфигурации Helm для кастомизации компонентов.

> **См. также:** [Prometheus Operator](../operator/concepts.md), [Helm](../../../Kubernetes/ToolsUtilities/Helm/helm_overview.md).

## Основные концепции

### Актуальная версия

| Параметр | Значение |
|---|---|
| **Последняя версия чарта** | 82.4.3 |
| **Версия Prometheus** | 3.10.0 |
| **Версия Alertmanager** | 0.31.0 |
| **Версия Grafana** | 11.x |
| **Версия Operator** | 0.89.0 |

> **Важно:** Проверяйте [Artifact Hub](https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack) для получения последних версий.

### Компоненты чарта

* **Prometheus Server** — сбор и хранение метрик (StatefulSet)
* **Alertmanager** — обработка оповещений (StatefulSet)
* **Grafana** — визуализация и дашборды (Deployment)
* **Node Exporter** — метрики хостов (DaemonSet)
* **Kube-State-Metrics** — метрики объектов Kubernetes (Deployment)
* **Prometheus Operator** — управление стеком (Deployment)
* **Blackbox Exporter** — blackbox-мониторинг (Deployment)

## Практические сценарии

### Быстрый старт

```bash
# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка с настройками по умолчанию
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
```

### Работа с локальной копией

**Рекомендация:** Всегда работайте с локальной копией чарта для версионирования конфигурации.

```bash
# Скачивание чарта
helm pull prometheus-community/kube-prometheus-stack --untar
cd kube-prometheus-stack

# Редактирование values.yaml
vim values.yaml

# Установка с локальной копией
helm install monitoring . \
  --namespace monitoring \
  --create-namespace \
  -f values.yaml
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
kubectl get secret monitoring-grafana -n monitoring -o jsonpath="{.data.admin-password}" | base64 -d
```

### Обновление

```bash
# Обновление репозитория
helm repo update

# Обновление релиза
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values.yaml

# Откат
helm rollback monitoring -n monitoring

# Проверка истории
helm history monitoring -n monitoring
```

### Удаление

```bash
# Удаление релиза
helm uninstall monitoring -n monitoring

# Удаление CRD (осторожно!)
kubectl delete crd prometheuses.monitoring.coreos.com
kubectl delete crd alertmanagers.monitoring.coreos.com
kubectl delete crd servicemonitors.monitoring.coreos.com
kubectl delete crd podmonitors.monitoring.coreos.com
kubectl delete crd prometheusrules.monitoring.coreos.com
kubectl delete crd probes.monitoring.coreos.com
kubectl delete crd alertmanagerconfigs.monitoring.coreos.com
```

> **Важно:** Удаление CRD приведет к потере всех Custom Resources!

## Дополнительная информация

### Структура values.yaml

**Основные секции:**

```yaml
# Prometheus
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
          storageClassName: standard
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
          storageClassName: standard
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

# Node Exporter
nodeExporter:
  enabled: true

# Kube-State-Metrics
kubeStateMetrics:
  enabled: true
```

> **См. также:** [Prometheus config](./prometheus_config.md), [Alertmanager config](./alertmanager_config.md), [Grafana config](./grafana_config.md).

### Рекомендации по безопасности

**1. Пароль Grafana:**

```yaml
# Используйте Secret вместо plaintext
grafana:
  adminPassword: ""  # Пустое значение
  admin:
    existingSecret: "grafana-admin-secret"
    adminUserKey: "username"
    adminPasswordKey: "password"
```

**2. Network Policies:**

```yaml
# Ограничение доступа к Prometheus
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

### Ресурсы и квоты

**Рекомендуемые значения для small/medium кластеров:**

```yaml
prometheus:
  prometheusSpec:
    resources:
      requests:
        memory: 400Mi
        cpu: 200m
      limits:
        memory: 2Gi
        cpu: 1000m
    retention: 15d
    storageSpec:
      volumeClaimTemplate:
        spec:
          storage: 50Gi

alertmanager:
  alertmanagerSpec:
    resources:
      requests:
        memory: 128Mi
        cpu: 100m
      limits:
        memory: 256Mi
        cpu: 200m
```

### Связанные темы

* [Prometheus Operator](../operator/concepts.md) — управление через CRD
* [Service Discovery](../service_discovery.md) — обнаружение целей
* [Practical Scenarios](./practical_scenarios.md) — подробные руководства
* [Installation](../../installation/overview.md) — установка на хост
* [Scaling](../../scaling/overview.md) — масштабирование
