# Pod Evicted: Определения

## Определения

**`Evicted`** — статус пода, означающий, что Kubernetes принудительно выселил под с узла. Происходит при нехватке ресурсов на узле (память, диск, PID) или при выводе узла из эксплуатации.

> - QoS и ресурсы: [`../../../Scheduling/qos_limit_and_requests.md`](../../../Scheduling/qos_limit_and_requests.md)
> - OOMKilled: [`oomkilled_pods.md`](./oomkilled_pods.md)
> - Taints: [`../../../Scheduling/taints_and_tolerations.md`](../../../Scheduling/taints_and_tolerations.md)
> - Обслуживание узлов: [`../../../Operations/node_maintenance.md`](../../../Operations/node_maintenance.md)
> - Pod Disruption Budget: [`../../../Autoscaling/pod_disruption_budget.md`](../../../Autoscaling/pod_disruption_budget.md)

## Основные концепции

### Типы eviction

| Тип | Инициатор | Описание |
|-----|-----------|----------|
| **Node Pressure Eviction** | kubelet (автоматически) | При нехватке ресурсов на узле |
| **API-Initiated Eviction** | Пользователь/контроллер | Через API (drain, PDB) |
| **Taint-Based Eviction** | Control Plane | При недоступности узла |

### Node Pressure Conditions

| Condition | Описание | Threshold (по умолчанию) |
|-----------|----------|-------------------------|
| **`MemoryPressure`** | Нехватка памяти | < 100Mi или < 5% |
| **`DiskPressure`** | Нехватка места на диске | < 10% или < 1Gi |
| **`PIDPressure`** | Исчерпание PID | Зависит от ОС |

### Сравнение Eviction и OOMKilled

| Характеристика | Eviction | OOMKilled |
|----------------|----------|-----------|
| **Инициатор** | Eviction Manager / kubelet | OOM Killer (ядро) |
| **Причина** | Нехватка ресурсов на узле | Превышен limits.memory контейнера |
| **Статус** | `Evicted` | `OOMKilled` (Reason в Last State) |
| **QoS влияние** | Выселение по приоритету | Не зависит от QoS |
| **Решение** | Освободить ресурсы узла | Увеличить limits или оптимизировать приложение |
