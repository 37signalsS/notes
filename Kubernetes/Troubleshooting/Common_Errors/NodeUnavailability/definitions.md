# Node Unavailability: Определения

## Определения

**`NodeNotReady`** — статус узла (`Node`), означающий, что `kubelet` на узле работает, но сообщает, что узел не готов принимать новые поды.

**`Node Unreachable`** — состояние, при котором `kube-apiserver` не может связаться с `kubelet` на узле через контрольный канал (health check timeout).

> - Taints: [`../../../Scheduling/taints_and_tolerations.md`](../../../Scheduling/taints_and_tolerations.md)
> - Eviction: [`pod_evicted.md`](./pod_evicted.md)
> - Обслуживание узлов: [`../../../Operations/node_maintenance.md`](../../../Operations/node_maintenance.md)
> - High Availability: [`../../../Base/high_availability.md`](../../../Base/high_availability.md)
> - Cluster Autoscaler: [`../../../Autoscaling/cluster_autoscaler_detailed.md`](../../../Autoscaling/cluster_autoscaler_detailed.md)

**Важно:** Это статусы узла, а не пода. Влияют на все поды, размещенные на проблемном узле.

## Основные концепции

### Node Conditions

Kubernetes отслеживает следующие условия узла:

| Condition | Описание | Нормальный статус |
|-----------|----------|-------------------|
| **`Ready`** | Узел готов принимать поды | `True` |
| **`MemoryPressure`** | Нехватка памяти | `False` |
| **`DiskPressure`** | Нехватка диска | `False` |
| **`PIDPressure`** | Исчерпание PID | `False` |
| **`NetworkUnavailable`** | Сеть недоступна | `False` |

### Статусы узлов

| Статус | Condition | Описание |
|--------|-----------|----------|
| **`Ready`** | `Ready=True` | Узел работает нормально |
| **`NotReady`** | `Ready=False` | Kubelet работает, но узел не готов |
| **`Unknown`** | `Ready=Unknown` | Kubelet не отвечает (Unreachable) |
| **`SchedulingDisabled`** | `unschedulable=true` | Узел в cordon (обслуживание) |

### Влияние на поды

| Статус узла | Влияние на поды |
|-------------|-----------------|
| **`NotReady`** | Поды продолжают работать, новые не планируются |
| **`Unknown`** (>40s) | Добавляется taint `unreachable:NoExecute` |
| **`Unknown`** (>5m) | Поды без toleration выселяются |
