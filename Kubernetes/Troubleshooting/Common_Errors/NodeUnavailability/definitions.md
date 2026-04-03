# Node Unavailability: Definitions

## Definitions

**`NodeNotReady`** — статус узла (`Node`), означающий, что `kubelet` на узле работает, но сообщает, что узел не готов принимать новые поды.

**`Node Unreachable`** — состояние, при котором `kube-apiserver` не может связаться с `kubelet` на узле через контрольный канал (health check timeout).

**Важно:** Это статусы узла, а не пода. Влияют на все поды, размещённые на проблемном узле.

## Basic Concepts

### Node Conditions

Kubernetes отслеживает следующие условия узла:

| Condition | Описание | Нормальный статус |
|-----------|----------|-------------------|
| **`Ready`** | Узел готов принимать поды | `True` |
| **`MemoryPressure`** | Нехватка памяти | `False` |
| **`DiskPressure`** | Нехватка диска | `False` |
| **`PIDPressure`** | Исчерпание PID | `False` |
| **`NetworkUnavailable`** | Сеть недоступна | `False` |

### Node Statuses

| Статус | Condition | Описание |
|--------|-----------|----------|
| **`Ready`** | `Ready=True` | Узел работает нормально |
| **`NotReady`** | `Ready=False` | Kubelet работает, но узел не готов |
| **`Unknown`** | `Ready=Unknown` | Kubelet не отвечает (Unreachable) |
| **`SchedulingDisabled`** | `unschedulable=true` | Узел в cordon (обслуживание) |

### Impact on Pods

| Статус узла | Влияние на поды |
|-------------|-----------------|
| **`NotReady`** | Поды продолжают работать, новые не планируются |
| **`Unknown`** (>40s) | Добавляется taint `unreachable:NoExecute` |
| **`Unknown`** (>5m) | Поды без toleration выселяются |

### Node Controller Timeouts

| Параметр | По умолчанию | Описание |
|----------|--------------|----------|
| `--node-monitor-grace-period` | 40s | Время до присвоения статуса `Unknown` |
| `--pod-eviction-timeout` | 5m | Время до начала eviction подов |

## Practical Scenarios

### When to use this diagnostic path

- `kubectl get nodes` показывает `NotReady` или `Unknown`
- Поды на узле не обновляются или теряют связь
- Alert `NodeNotReady` / `NodeUnreachable` в Prometheus
- После reboot/обновления узел не возвращается в кластер

### Common root causes

| Причина | Типичный статус | См. |
|---------|-----------------|-----|
| Kubelet упал/завис | `NotReady` | [kubelet_issues.md](./kubelet_issues.md) |
| Нехватка CPU/RAM/Disk | `NotReady` + Pressure | [resource_pressure.md](./resource_pressure.md) |
| Сетевая связность потеряна | `Unknown` | [network_issues.md](./network_issues.md) |
| Container runtime недоступен | `NotReady` | [runtime_issues.md](./runtime_issues.md) |
| Плановое обслуживание | `SchedulingDisabled` | [maintenance.md](./maintenance.md) |

### Diagnostic entry point

Начните с [diagnostics.md](./diagnostics.md) — пошаговый чек-лист проверки узла.

## Additional Information

### Taints при проблемах с узлом

Kubernetes автоматически добавляет taints при проблемах. Детали: [taints_and_eviction.md](./taints_and_eviction.md).

### Monitoring & Alerting

Примеры Prometheus-алертов: [maintenance.md#monitoring-i-alerts](./maintenance.md).

### Related topics

- [Overview: Common Errors](../overview.md) — общие ошибки Kubernetes
- [Node Maintenance](../../../Operations/node_maintenance.md) — плановое обслуживание узлов
