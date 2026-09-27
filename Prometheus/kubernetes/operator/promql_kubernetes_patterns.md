# PromQL-паттерны для Kubernetes-метрик

## Определения

**PromQL Patterns для Kubernetes** — проверенные выражения PromQL, специфичные для метрик Kubernetes: `kube_*` (kube-state-metrics), `container_*` (cAdvisor/kubelet) и `node_*` (node-exporter). Эти паттерны используются в PrometheusRule CRD для алертинга, recording rules и диагностики инфраструктуры.

**kube-state-metrics (KSM)** — компонент, преобразующий состояние объектов Kubernetes (Pods, Deployments, Nodes) в метрики Prometheus. Метрики начинаются с `kube_` и предоставляют информацию о репликах, статусах, лейблах.

**cAdvisor** — встроенный в kubelet агент сбора метрик контейнеров. Метрики начинаются с `container_` и включают CPU, RAM, Disk I/O, Network I/O для каждого контейнера.

**Recording Rules** — предвычисленные PromQL-выражения, результат которых сохраняется как новая метрика. Используются для ускорения сложных запросов и снижения нагрузки на TSDB.

> **Смотрите также:** [PromQL Functions](../../../Prometheus/concepts/promql/functions.md); [Query Patterns](../../../Prometheus/concepts/promql/query_patterns.md); [Troubleshooting PromQL](../../../Prometheus/concepts/promql/troubleshooting.md).

---

## Базовые концепции

### Источники Kubernetes-метрик

| Источник | Префикс метрик | Что собирает |
|:---|:---|:---|
| kube-state-metrics | `kube_*` | Состояние объектов K8s (replicas, status, labels) |
| cAdvisor (kubelet) | `container_*` | Ресурсы контейнеров (CPU, RAM, Disk, Network) |
| node-exporter | `node_*` | Метрики ОС (filesystem, memory, CPU, network) |
| kubelet | `kubelet_*` | Состояние kubelet, pod lifecycle |
| apiserver | `apiserver_*` | Метрики API-сервера |
| etcd | `etcd_*` | Метрики etcd |

### Типы Kubernetes-алертов

| Тип | Метрики | Пример |
|:---|:---|:---|
| **Node Health** | `kube_node_status_condition` | NodeNotReady, DiskPressure, MemoryPressure |
| **Pod Health** | `kube_pod_status_phase` | CrashLoopBackOff, OOMKilled, Evicted |
| **Resource Usage** | `container_*` | CPU throttling, memory near limit |
| **Deployment** | `kube_deployment_status_replicas` | Unavailable replicas, scaling failures |

---

## Практические сценарии

### Node Health Alerts

```yaml
# PrometheusRule для мониторинга состояния нод
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: node-health
  namespace: monitoring
  labels:
    release: monitoring
spec:
  groups:
    - name: node-health
      rules:
        # Нода не готова
        - alert: NodeNotReady
          expr: kube_node_status_condition{condition="Ready", status="true"} == 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Нода {{ $labels.node }} не готова"
            description: "Недоступна более 5 минут"

        # Давление на память
        - alert: NodeMemoryPressure
          expr: kube_node_status_condition{condition="MemoryPressure", status="true"} == 1
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Давление памяти на ноде {{ $labels.node }}"

        # Давление на диск
        - alert: NodeDiskPressure
          expr: kube_node_status_condition{condition="DiskPressure", status="true"} == 1
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Давление на диск на ноде {{ $labels.node }}"

        # Давление на PID
        - alert: NodePIDPressure
          expr: kube_node_status_condition{condition="PIDPressure", status="true"} == 1
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Давление на PID на ноде {{ $labels.node }}"

        # Нода будет удалена (drain)
        - alert: NodeBeingDrained
          expr: kube_node_spec_unschedulable == 1
          for: 0m
          labels:
            severity: info
          annotations:
            summary: "Нода {{ $labels.node }} в режиме drain"
```

### Pod Health Alerts

```yaml
groups:
  - name: pod-health
    rules:
      # Pod в CrashLoopBackOff
      - alert: PodCrashLooping
        expr: rate(kube_pod_container_status_restarts_total[15m]) * 60 * 5 > 0
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Pod {{ $labels.namespace }}/{{ $labels.pod }} перезапускается"

      # OOMKilled
      - alert: PodOOMKilled
        expr: kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Pod {{ $labels.namespace }}/{{ $labels.pod }} завершен из-за OOM"

      # Pod не готов ( readiness probe failed)
      - alert: PodNotReady
        expr: |
          kube_pod_status_condition{condition="Ready", status="true"} == 0
          and kube_pod_status_phase{phase=~"Running|Pending"} == 1
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Pod {{ $labels.namespace }}/{{ $labels.pod }} не готов"

      # Pod terminated с ошибкой
      - alert: PodTerminatedWithError
        expr: increase(kube_pod_container_status_terminated_reason{reason!~"Completed|OOMKilled"}[1h]) > 0
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Pod {{ $labels.namespace }}/{{ $labels.pod }} завершен с ошибкой: {{ $labels.reason }}"

      # Pod evicted (недостаточно ресурсов)
      - alert: PodEvicted
        expr: increase(kube_pod_status_reason{reason="Evicted"}[1h]) > 0
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Pod {{ $labels.namespace }}/{{ $labels.pod }} был вытеснен"
```

### Resource Usage Alerts

```yaml
groups:
  - name: resource-usage
    rules:
      # CPU Throttling (>25%)
      - alert: ContainerCPUThrottling
        expr: |
          sum by (namespace, pod, container) (
            rate(container_cpu_cfs_throttled_seconds_total{container!=""}[5m])
          ) / sum by (namespace, pod, container) (
            rate(container_cpu_usage_seconds_total{container!=""}[5m])
          ) > 0.25
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "CPU throttling {{ $labels.namespace }}/{{ $labels.pod }}/{{ $labels.container }}"

      # Память >90% от лимита
      - alert: ContainerMemoryNearLimit
        expr: |
          container_memory_working_set_bytes{container!=""}
          / container_spec_memory_limit_bytes{container!=""}
          > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Память >90% лимита: {{ $labels.namespace }}/{{ $labels.pod }}"

      # Прогноз OOMKill через 1 час
      - alert: PredictedOOMKill
        expr: |
          predict_linear(container_memory_working_set_bytes{container!=""}[30m], 3600)
          > container_spec_memory_limit_bytes{container!=""}
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Прогноз OOMKill через 1 час: {{ $labels.namespace }}/{{ $labels.pod }}"

      # Диск заполнен >85%
      - alert: DiskSpaceHigh
        expr: |
          (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) > 0.85
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Диск >85% на {{ $labels.instance }}"

      # Прогноз заполнения диска через 24 часа
      - alert: DiskWillFull
        expr: predict_linear(node_filesystem_avail_bytes{mountpoint="/"}[6h], 3600 * 24) < 0
        for: 30m
        labels:
          severity: critical
        annotations:
          summary: "Диск будет заполнен через 24 часа: {{ $labels.instance }}"
```

### Deployment Alerts

```yaml
groups:
  - name: deployment-health
    rules:
      # Недоступные реплики
      - alert: DeploymentReplicasUnavailable
        expr: |
          kube_deployment_spec_replicas
          - kube_deployment_status_replicas_available > 0
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Deployment {{ $labels.namespace }}/{{ $labels.deployment }}: реплики недоступны"

      # HPA не может масштабироваться
      - alert: HPAScalingFailure
        expr: |
          increase(kube_hpa_status_current_replicas[5m]) > 0
          and kube_hpa_status_condition{condition="ScalingActive", status="false"} == 1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "HPA {{ $labels.namespace }}/{{ $labels.hpa }} не может масштабироваться"

      # HPA на максимуме
      - alert: HPAMaxedOut
        expr: |
          kube_hpa_status_current_replicas == kube_hpa_spec_max_replicas
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "HPA {{ $labels.namespace }}/{{ $labels.hpa }} на максимуме"
```

### Recording Rules для ускорения запросов

```yaml
groups:
  - name: kubernetes-recording-rules
    interval: 30s
    rules:
      # CPU usage percentage
      - record: node:cpu_utilization:ratio
        expr: |
          sum(rate(container_cpu_usage_seconds_total{container!=""}[5m])) by (node)
          / sum(kube_node_status_allocatable{resource="cpu"}) by (node)

      # Memory usage percentage
      - record: node:memory_utilization:ratio
        expr: |
          sum(container_memory_working_set_bytes) by (node)
          / sum(kube_node_status_allocatable{resource="memory"}) by (node)

      # Pod CPU throttling ratio
      - record: pod:cpu_throttled:ratio5m
        expr: |
          sum by (namespace, pod, container) (
            rate(container_cpu_cfs_throttled_seconds_total{container!=""}[5m])
          ) / sum by (namespace, pod, container) (
            rate(container_cpu_usage_seconds_total{container!=""}[5m])
          )

      # Deployment readiness ratio
      - record: deployment:ready_ratio
        expr: |
          kube_deployment_status_replicas_available
          / kube_deployment_spec_replicas
```

### Диагностика через PromQL

```bash
# 1. Топ-10 подов по потреблению RAM
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- \
  'http://localhost:9090/api/v1/query?query=topk(10,container_memory_working_set_bytes{container!=""})' | jq .

# 2. Топ-10 подов по CPU throttling
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- \
  'http://localhost:9090/api/v1/query?query=topk(10,rate(container_cpu_cfs_throttled_seconds_total{container!=""}[5m]))' | jq .

# 3. Pods с OOMKill за последние 24 часа
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- \
  'http://localhost:9090/api/v1/query?query=increase(kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}[24h])' | jq .

# 4. Прогноз памяти через 1 час
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- \
  'http://localhost:9090/api/v1/query?query=predict_linear(container_memory_working_set_bytes{container!=""}[30m], 3600)' | jq .

# 5. Ноды с DiskPressure
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- \
  'http://localhost:9090/api/v1/query?query=kube_node_status_condition{condition="DiskPressure", status="true"} == 1' | jq .
```

---

## Дополнительная информация

### Связанные файлы

| Файл | Содержание |
|:---|:---|
| [PromQL Functions](../../../Prometheus/concepts/promql/functions.md) | rate, increase, histogram_quantile, predict_linear |
| [Query Patterns](../../../Prometheus/concepts/promql/query_patterns.md) | RED, USE, Four Golden Signals |
| [PrometheusRule CRD](./crd/prometheusrule.md) | Формат и структура правил |
| [cAdvisor Metrics](../../../Prometheus/Exporters/cadvisor.md) | Полный справочник container_* метрик |
| [Grafana Kubernetes Alerts](../../../../Grafana/alerting/kubernetes_alerts.md) | Примеры алертов для Grafana |

### Частые ошибки на собеседованиях

1. **"rate() и increase() — одно и то же"** — Нет. `rate()` возвращает скорость (значение в секунду), `increase()` — абсолютное изменение за период. Для алертов используйте `increase()`.
2. **"predict_linear предсказывает будущее точно"** — Нет. Это экстраполяция линейного тренда. Не работает для экспоненциального роста. Используйте окна 1-6 часов для window.
3. **"container_memory_working_set_bytes = RSS"** — Нет. Working Set = RSS + файловый кэш (без eternal caches). OOMKill срабатывает по Working Set, а не по RSS.
