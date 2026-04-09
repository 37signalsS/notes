# Мониторинг Kubernetes: Обзор

## Определения

**Мониторинг Kubernetes** — практика наблюдения за состоянием кластера, его компонентов (control plane, worker nodes) и workload'ов (Pods, Deployments, Services) с использованием метрик, логов и трейсов.

**kube-prometheus-stack** — Helm-чарт для развёртывания полного стека мониторинга (Prometheus, Alertmanager, Grafana, Exporters, Prometheus Operator) в Kubernetes.

> **См. также:** [kube-prometheus-stack — Helm](./Kube_Prometheus_Stack_Helm/overview.md), [Prometheus Operator](./operator/concepts.md), [Service Discovery](./service_discovery.md).

## Основные концепции

### Экосистема Prometheus

* **[Prometheus Server](../overview.md):** Центральный компонент для сбора, хранения и обработки метрик.
* **[Alertmanager](../alertmanager.md):** Дедупликация, группировка и маршрутизация оповещений.
* **[Push Gateway](../pushgateway.md):** Сбор метрик от кратковременных задач (batch jobs).
* **[Экспортеры](../Exporters/overview.md):** Сбор метрик из различных систем (ОС, БД, приложения).
* **[Grafana](../../Grafana/grafana_overview.md):** Визуализация метрик, дашборды, алерты.

### Архитектура мониторинга в Kubernetes

**Компоненты стека:**

| Компонент | Тип объекта | Назначение |
|---|---|---|
| **Prometheus Server** | StatefulSet | Сбор и хранение метрик |
| **Alertmanager** | StatefulSet | Обработка оповещений |
| **Grafana** | Deployment | Визуализация |
| **Prometheus Operator** | Deployment | Управление стеком через CRD |
| **Node Exporter** | DaemonSet | Метрики хостов |
| **Kube-State-Metrics** | Deployment | Метрики объектов K8s |

### Service Discovery в Kubernetes

Prometheus использует Kubernetes API для автоматического обнаружения целей:

* **endpoints** — обнаружение Endpoint объектов
* **service** — обнаружение Service объектов
* **pod** — обнаружение Pod объектов
* **node** — обнаружение Node объектов
* **ingress** — обнаружение Ingress объектов

> **См. также:** [Service Discovery](./service_discovery.md) — детальное руководство.

### Ключевые метрики Kubernetes

**Control Plane:**

* `apiserver_request_total` — количество запросов к API Server
* `etcd_server_has_leader` — наличие лидера в etcd
* `scheduler_schedule_attempts_total` — попытки планирования подов

**Workloads:**

* `kube_deployment_status_replicas_unavailable` — недоступные реплики
* `kube_pod_container_status_restart_total` — перезапуски контейнеров
* `kube_pod_container_status_ready` — готовность контейнера
* `kube_pod_status_phase` — фаза пода (Running, Pending, Failed)

**Nodes:**

* `kube_node_status_capacity_memory_bytes` — ёмкость памяти ноды
* `kube_node_status_condition` — состояние ноды (Ready, MemoryPressure, DiskPressure)
* `kubelet_running_pods` — количество запущенных подов на ноде
* `node_cpu_seconds_total` — утилизация CPU (Node Exporter)

## Практические сценарии

### Подходы к мониторингу

**1. Whitebox (внутренний):**

Экспортеры работают внутри кластера или на хостах, собирают метрики через Kubernetes Service:
- Node Exporter → метрики хостов
- cAdvisor → метрики контейнеров
- Kube-State-Metrics → метрики объектов K8s

> **См. также:** [Экспортеры](../Exporters/overview.md).

**2. Blackbox (внешний):**

Проверка доступности эндпоинтов (HTTP/TCP/ICMP/DNS) извне через Probe CRD:
- Доступность Ingress
- Health-check эндпоинты
- DNS-резолвинг

> **См. также:** [Blackbox Exporter](../Exporters/blackbox/blackbox_exporter_installation_and_setup.md), [Probe CRD](./operator/crd/probe.md).

**3. Мониторинг внешних ресурсов:**

Интеграция внешних серверов с экспортерами через `additionalScrapeConfigs` + `static_configs`:

> **См. также:** [External Monitoring via static_configs (SSoT)](./Kube_Prometheus_Stack_Helm/practical_scenarios/external_monitoring.md).

## Дополнительная информация

### Observability: Метрики, Логи, Трассировка

| Тип | Инструменты | Вопрос |
|---|---|---|
| **Метрики** | Prometheus, Grafana | **Что происходит?** |
| **Логи** | ELK Stack, Grafana Loki | **Почему это произошло?** |
| **Трассировка** | Jaeger, OpenTelemetry | **Как это произошло?** |

> **См. также:** [Observability overview](../../Concepts/Observability_and_Monitoring/observability_definitions.md).

### Рекомендации по безопасности

**1. Аутентификация Prometheus:**

* Встроенная аутентификация (новые версии Prometheus)
* Basic-auth на Ingress + Network Policies

**2. Network Policies:**

```yaml
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

**3. TLS:**

* Ingress с TLS для внешнего доступа к UI
* mTLS для внутренних соединений (опционально)

> **См. также:** [Prometheus Security](../security.md).

### Высокая доступность

| Компонент | Минимум реплик | Механизм |
|---|---|---|
| **Prometheus** | 2 | StatefulSet, одинаковая конфигурация |
| **Alertmanager** | 3 | Кластеризация, кворум, дедупликация |

> **См. также:** [Scaling](../scaling/overview.md), [Thanos](../scaling/thanos_overview.md), [HA](./operator/high_availability.md).
