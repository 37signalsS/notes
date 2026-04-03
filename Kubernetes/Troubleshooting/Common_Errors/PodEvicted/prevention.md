# Pod Evicted: Профилактика

## Definitions

**Профилактика eviction** — комплекс мер по конфигурации ресурсов, мониторингу и планированию, направленный на минимизацию вероятности выселения подов.

**Цели профилактики:**

1. Не допустить Node Pressure (MemoryPressure, DiskPressure)
2. Гарантировать доступность критичных подов при drain
3. Своевременно обнаруживать деградацию ресурсов

## Basic Concepts

### Уровни профилактики

| Уровень | Мера | От какого eviction защищает |
|---------|------|---------------------------|
| **Под** | requests + limits = Guaranteed | Node Pressure (приоритет) |
| **Приложение** | PodDisruptionBudget | Массовый drain |
| **Узел** | kubeReserved + eviction thresholds | System starvation |
| **Кластер** | Cluster Autoscaler | Capacity exhaustion |
| **Мониторинг** | Prometheus alerts | Все типы (раннее обнаружение) |

### QoS как фундамент защиты

```
Guaranteed (requests == limits)
    ← максимальная защита от eviction
Burstable (requests < limits)
    ← средняя защита
BestEffort (нет requests/limits)
    ← первые кандидаты на eviction
```

> Детали: [qos_and_eviction.md](./qos_and_eviction.md), [qos_limit_and_requests.md](../../../Scheduling/qos_limit_and_requests.md)

## Practical Scenarios

### 1. Настройка Guaranteed QoS для критичных подов

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: critical-app
spec:
  containers:
  - name: app
    image: critical-app:latest
    resources:
      requests:
        memory: "512Mi"
        cpu: "500m"
      limits:
        memory: "512Mi"    # == requests → Guaranteed
        cpu: "500m"        # == requests → Guaranteed
```

> requests == limits — обязательное условие для Guaranteed QoS.

### 2. Pod Disruption Budget

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
spec:
  minAvailable: 2                # или maxUnavailable: 1
  selector:
    matchLabels:
      app: my-app
```

| Подход | Когда использовать |
|--------|-------------------|
| `minAvailable: N` | Важно сохранить минимум N работающих подов |
| `maxUnavailable: 1` | Допустимо потерять не более 1 пода при drain |

> Защита действует **только** при drain / rolling update. Детали: [pod_disruption_budget.md](../../../Autoscaling/pod_disruption_budget.md)

### 3. Мониторинг и алерты

```yaml
# Prometheus alerts
- alert: NodeMemoryPressure
  expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "MemoryPressure на узле {{ $labels.node }}"

- alert: NodeDiskPressure
  expr: kube_node_status_condition{condition="DiskPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "DiskPressure на узле {{ $labels.node }}"

- alert: NodeFilesystemAlmostFull
  expr: node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes * 100 < 15
  for: 10m
  labels:
    severity: warning

- alert: PodEvicted
  expr: kube_pod_status_reason{reason="Evicted"} == 1
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Pod {{ $labels.pod }} evicted в namespace {{ $labels.namespace }}"
```

### 4. Cluster Autoscaler

Автоматическое добавление узлов при нехватке ресурсов:

```yaml
# Cluster Autoscaler автоматически добавит узлы
# при появлении Pending подов из-за нехватки CPU/memory
```

Работает в облачных средах (AWS ASG, GCP MIG, Azure VMSS). Для bare metal — [Karpenter](https://karpenter.sh/).

### 5. Удаление выселенных подов

Выселенные поды остаются в кластере со статусом `Failed/Evicted` и не удаляются автоматически:

```bash
# Удаление всех выселенных подов в namespace
kubectl delete pods --field-selector status.reason=Evicted -n <namespace>

# Удаление всех выселенных подов в кластере
kubectl delete pods --field-selector status.reason=Evicted --all-namespaces
```

> Deployment/ReplicaSet автоматически создаст новые поды взамен удалённых.

## Additional Information

### Сводная таблица best practices

| Практика | Описание | Детали |
|----------|----------|--------|
| **Всегда указывайте requests и limits** | Избегайте QoS `BestEffort` | [qos_limit_and_requests.md](../../../Scheduling/qos_limit_and_requests.md) |
| **Guaranteed для критичных подов** | Максимальная защита от eviction | См. [сценарий 1](#1-настройка-guaranteed-qos-для-критичных-подов) |
| **PDB для stateful-сервисов** | Защита от массового выселения при drain | [pdb_and_taint_eviction.md](./pdb_and_taint_eviction.md) |
| **kubeReserved на узлах** | Резерв для системных процессов | [memory_eviction.md](./memory_eviction.md) |
| **log rotation** | Предотвращение DiskPressure | [disk_eviction.md](./disk_eviction.md) |
| **Мониторинг узлов** | Алерты на Memory/Disk Pressure | См. [сценарий 3](#3-мониторинг-и-алерты) |
| **Cluster Autoscaler** | Автоматическое масштабирование | См. [сценарий 4](#4-cluster-autoscaler) |
| **tolerationSeconds** | Увеличение времени до taint-based eviction | [pdb_and_taint_eviction.md](./pdb_and_taint_eviction.md) |

### Внешние ресурсы

- [Node Pressure Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/)
- [Pod Disruptions](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)
- [Pod QoS](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/)
