# Node Unavailability: Taints and Eviction

## Definitions

**Taint** — метка на узле, запрещающая размещение подов без соответствующего `toleration`. При проблемах с узлом Kubernetes автоматически добавляет taints.

**Eviction** — процесс выселения подов с проблемного узла. При недоступности узла eviction инициируется node-controller с задержкой, определяемой `tolerationSeconds`.

**tolerationSeconds** — период времени, в течение которого под может оставаться на узле с taint `NoExecute` перед удалением.

## Basic Concepts

### Automatic Taints при проблемах

Kubernetes автоматически добавляет следующие taints:

| Taint | Effect | Когда добавляется |
|-------|--------|-------------------|
| `node.kubernetes.io/not-ready:NoExecute` | `NoExecute` | Condition `Ready=False` (kubelet работает, но узел не готов) |
| `node.kubernetes.io/unreachable:NoExecute` | `NoExecute` | Condition `Ready=Unknown` (kubelet не отвечает) |
| `node.kubernetes.io/memory-pressure:NoSchedule` | `NoSchedule` | Condition `MemoryPressure=True` |
| `node.kubernetes.io/disk-pressure:NoSchedule` | `NoSchedule` | Condition `DiskPressure=True` |
| `node.kubernetes.io/pid-pressure:NoSchedule` | `NoSchedule` | Condition `PIDPressure=True` |
| `node.kubernetes.io/network-unavailable:NoSchedule` | `NoSchedule` | Condition `NetworkUnavailable=True` |

> ⚠️ Общие концепции taints и tolerations: [taints_and_tolerations.md](../../../Scheduling/taints_and_tolerations.md).

### Eviction Timeline

```
Узел становится Unreachable
    ↓
node-controller ждёт 40s (node-monitor-grace-period)
    ↓
Condition → Unknown, добавляется taint unreachable:NoExecute
    ↓
Поды без toleration начинают выселяться
    ↓
Через 300s (tolerationSeconds) поды удалены с узла
```

### Node Controller Parameters

| Параметр | По умолчанию | Описание |
|----------|--------------|----------|
| `--node-monitor-grace-period` | 40s | Время до присвоения статуса `Unknown` |
| `--pod-eviction-timeout` | 5m | Период между попытками eviction (не время до начала!) |

> **Примечание:** `--pod-eviction-timeout` — это интервал между попытками eviction, а не время ожидания. Реальная задержка определяется `tolerationSeconds` (по умолчанию 300s для not-ready/unreachable).

### Default Tolerations

Kubernetes автоматически добавляет ко всем подам:

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

## Practical Scenarios

### Scenario 1: Диагностика eviction при недоступности узла

**Симптомы:**

- Поды на узле удалены через ~5 минут после потери связи
- Событие: `TolerationNotReady` или `TolerationUnreachable`

**Диагностика:**

```bash
# Проверка taints узла
kubectl describe node <node-name> | grep -A 5 "Taints:"

# События eviction
kubectl get events --field-selector reason=TaintManagerEviction --sort-by='.lastTimestamp'

# Какие поды были на узле?
kubectl get pods -o wide --all-namespaces | grep <node-name>
```

### Scenario 2: PodDisruptionBudget блокирует eviction

**Симптомы:**

- Узел недоступен, но поды не выселяются
- PDB не позволяет удалить достаточно реплик

**Диагностика:**

```bash
# Проверка PDB
kubectl get pdb
kubectl get pdb <pdb-name> -o yaml

# Disruptions allowed
kubectl get pdb <pdb-name> -o jsonpath='{.status.disruptionsAllowed}'
```

**Решение:**

```bash
# Временное увеличение maxUnavailable (если допустимо)
kubectl patch pdb <pdb-name> --type='merge' -p '{"spec":{"maxUnavailable":2}}'
```

### Scenario 3: Кастомные tolerations для критичных подов

Если под должен выживать при недоступности узла дольше стандартных 300s:

```yaml
tolerations:
- key: "node.kubernetes.io/unreachable"
  operator: "Exists"
  effect: "NoExecute"
  tolerationSeconds: 600  # 10 минут вместо 5
```

> ⚠️ **Риск:** Увеличение `tolerationSeconds` означает, что под может долго оставаться "висящим" на недоступном узле, пока не будет удалён.

### Scenario 4: Принудительное удаление "зависших" подов

Когда узел не вернётся, а под не удаляется:

```bash
# Принудительное удаление без ожидания
kubectl delete pod <pod-name> --force --grace-period=0

# Или через финализатор
kubectl patch pod <pod-name> -p '{"metadata":{"finalizers":null}}'
```

> ⚠️ **Важно:** `--force --grace-period=0` удаляет объект из API, но не гарантирует остановку контейнера на недоступном узле.

## Additional Information

### Related Node Unavailability Paths

- Definitions: [definitions.md](./definitions.md)
- Diagnostics checklist: [diagnostics.md](./diagnostics.md)
- Resource pressure eviction: [resource_pressure.md](./resource_pressure.md)
- Maintenance drain: [maintenance.md](./maintenance.md)

### External References

- [Taints and Tolerations](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/)
- [Node Pressure Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/)
- [Pod Disruption Budgets](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)
