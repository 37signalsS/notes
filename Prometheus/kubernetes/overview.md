# Мониторинг Kubernetes: Обзор

## Определения

**kube-prometheus-stack** — Helm-чарт для развертывания полноценной системы мониторинга на базе Prometheus в Kubernetes. Упрощает установку, настройку и управление всеми компонентами стека.

**Prometheus Operator** — контроллер Kubernetes для автоматизации управления Prometheus, Alertmanager и связанными компонентами через Custom Resource Definitions (CRD).

> **См. также:** [Prometheus Operator](./operator/concepts.md), [Service Discovery](./service_discovery.md).

## Основные концепции

### Актуальные версии

| Компонент | Версия |
|---|---|
| **kube-prometheus-stack** | 82.4.3 |
| **Prometheus Operator** | 0.89.0 |
| **Prometheus** | 3.10.0 |
| **Alertmanager** | 0.31.0 |
| **Grafana** | 11.x |

> **Важно:** Проверяйте [Artifact Hub](https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack) и [GitHub Releases](https://github.com/prometheus-operator/prometheus-operator/releases) для получения последних версий.

### Экосистема Prometheus

* **[Prometheus Server](./overview.md):** Центральный компонент для сбора, хранения и обработки метрик. Разворачивается как `StatefulSet`.
* **[Alertmanager](../alertmanager.md):** Дедупликация, группировка и маршрутизация оповещений.
* **[Push Gateway](../pushgateway.md):** Сбор метрик от кратковременных задач (batch jobs).
* **[Экспортеры](../Exporters/overview.md):** Сбор метрик из различных систем (ОС, БД, приложения).
* **[Grafana](../../Grafana/grafana_overview.md):** Визуализация метрик, дашборды, алерты.

### Архитектура kube-prometheus-stack

**Компоненты:**

* **Prometheus Operator** — контроллер для управления стеком
* **Prometheus Server** — сбор и хранение метрик
* **Alertmanager** — обработка оповещений
* **Grafana** — визуализация
* **Node Exporter** — метрики хостов (DaemonSet)
* **Kube-State-Metrics** — метрики объектов Kubernetes

### Custom Resource Definitions (CRD)

**Ключевые CRD:**

* **ServiceMonitor** — описание целей для скрейпинга через Service
* **PodMonitor** — мониторинг подов напрямую по лейблам
* **PrometheusRule** — правила алертинга и записи
* **Probe** — blackbox-мониторинг через Blackbox Exporter
* **AlertmanagerConfig** — конфигурация маршрутизации Alertmanager

> **См. также:** [Prometheus Operator](./operator/concepts.md) — детальное описание CRD.

### Service Discovery в Kubernetes

Prometheus использует Kubernetes API для автоматического обнаружения целей:

* **endpoints** — обнаружение Endpoint объектов
* **service** — обнаружение Service объектов
* **pod** — обнаружение Pod объектов
* **node** — обнаружение Node объектов
* **ingress** — обнаружение Ingress объектов

> **См. также:** [Service Discovery](./service_discovery.md) — детальное руководство.

## Практические сценарии

### Быстрый старт

```bash
# Создание namespace
kubectl create namespace monitoring

# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка kube-prometheus-stack
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
```

> **См. также:** [Kube-Prometheus-Stack Helm](./Kube_Prometheus_Stack_Helm/overview.md).

### Проверка установки

```bash
# Проверка подов
kubectl get pods -n monitoring

# Проверка ServiceMonitor
kubectl get servicemonitor -n monitoring

# Доступ к Prometheus
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090

# Доступ к Grafana
kubectl port-forward svc/monitoring-grafana -n monitoring 3000:80
```

### Мониторинг внешних ресурсов

**Blackbox-мониторинг через CRD Probe:**

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
```

**Whitebox-мониторинг внешних хостов:**

```yaml
# В values.yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
      - job_name: 'external-host'
        static_configs:
          - targets: ['192.168.1.100:9100']
            labels:
              env: 'production'
```

> **См. также:** [Blackbox Exporter](./Exporters/blackbox_exporter.md).

## Дополнительная информация

### Observability: Метрики, Логи, Трассировка

| Тип | Инструменты | Вопрос |
|---|---|---|
| **Метрики** | Prometheus, Grafana | **Что происходит?** |
| **Логи** | ELK Stack, Grafana Loki | **Почему это произошло?** |
| **Трассировка** | Jaeger, OpenTelemetry | **Как это произошло?** |

> **См. также:** [Observability overview](../../Concepts/Observability_and_Monitoring/observability_overview.md).

### Рекомендации по безопасности

**1. Аутентификация Prometheus:**

* Используйте встроенную аутентификацию (доступна в новых версиях)
* Или Basic-аутентификацию на Ingress + Network Policies

**2. Ограничение доступа:**

```yaml
# NetworkPolicy для Prometheus
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prometheus-network-policy
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

**3. TLS для внешних соединений:**

* Используйте Ingress с TLS для доступа к UI
* Настройте mTLS для внутренних соединений (опционально)

### Высокая доступность

**Prometheus:**

* Минимум 2 реплики (StatefulSet)
* Одинаковая конфигурация на всех репликах
* Внешнее хранилище для долгосрочных данных

**Alertmanager:**

* Минимум 3 реплики для кворума
* Кластеризация для дедупликации алертов

> **См. также:** [Scaling](../scaling/overview.md), [Thanos](../scaling/thanos_overview.md).

### Полезные метрики Kubernetes

* `kube_deployment_status_replicas_unavailable` — недоступные реплики
* `kube_node_status_capacity_memory_bytes` — ёмкость памяти ноды
* `kube_pod_container_status_restart_total` — перезапуски контейнеров
* `kube_pod_container_status_ready` — готовность контейнера
* `kubelet_running_pods` — количество запущенных подов на ноде

### Связанные темы

* [Prometheus Operator](./operator/concepts.md) — управление стеком
* [Service Discovery](./service_discovery.md) — обнаружение целей
* [Kube-Prometheus-Stack Helm](./Kube_Prometheus_Stack_Helm/overview.md) — установка
* [Installation](../installation/overview.md) — установка на хост
* [Configuration](../configuration.md) — настройка Prometheus
* [Rules](../rules.md) — правила алертинга
* [Scaling](../scaling/overview.md) — масштабирование
