# Node Unavailability: Taints и Eviction

## Taints при проблемах с узлом

Kubernetes автоматически добавляет taints при проблемах:

| Taint | Effect | Когда добавляется |
|-------|--------|-------------------|
| `node.kubernetes.io/not-ready:NoExecute` | `NoExecute` | Узел в статусе `NotReady` |
| `node.kubernetes.io/unreachable:NoExecute` | `NoExecute` | Узел в статусе `Unknown` |
| `node.kubernetes.io/memory-pressure:NoSchedule` | `NoSchedule` | Condition `MemoryPressure=True` |
| `node.kubernetes.io/disk-pressure:NoSchedule` | `NoSchedule` | Condition `DiskPressure=True` |
| `node.kubernetes.io/pid-pressure:NoSchedule` | `NoSchedule` | Condition `PIDPressure=True` |
| `node.kubernetes.io/network-unavailable:NoSchedule` | `NoSchedule` | Condition `NetworkUnavailable=True` |

> **См. также:** [`../../../Scheduling/taints_and_tolerations.md`](../../../Scheduling/taints_and_tolerations.md)

## Eviction Timeout

При недоступности узла:

```
Узел становится Unreachable
    ↓
node-controller ждет 40 секунд (по умолчанию)
    ↓
Добавляется taint `unreachable:NoExecute`
    ↓
Поды без toleration начинают выселяться
    ↓
Через 5 минут (tolerationSeconds) поды удалены
```

**Параметры:**

- `--pod-eviction-timeout` (по умолчанию 5m0s) — время до начала eviction
- `--node-monitor-grace-period` (по умолчанию 40s) — время до статуса `Unknown`

> **См. также:** [`../../../Base/high_availability.md`](../../../Base/high_availability.md)

## Taint tolerations для системных подов

Kubernetes автоматически добавляет tolerations ко всем подам:

```yaml
tolerations:
- key: "node.kubernetes.io/not-ready"
  operator: "Exists"
  effect: "NoExecute"
  tolerationSeconds: 300
- key: "node.kubernetes.io/unreachable"
  operator: "Exists"
  effect: "NoExecute"
  tolerationSeconds: 300
```
