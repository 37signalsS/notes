# Pod Evicted: Определения

## Definitions

**`Evicted`** — статус пода, означающий, что Kubernetes принудительно выселил под с узла. Происходит при нехватке ресурсов на узле (память, диск, PID) или при выводе узла из эксплуатации.

**Eviction Manager** — компонент kubelet, который мониторит ресурсы узла и принимает решения о выселении подов при достижении eviction thresholds.

**QoS (Quality of Service)** — класс пода, определяющий приоритет при выселении: `BestEffort` → `Burstable` → `Guaranteed`.

## Basic Concepts

### Типы eviction

| Тип | Инициатор | Описание |
|-----|-----------|----------|
| **Node Pressure Eviction** | kubelet (автоматически) | При нехватке ресурсов на узле |
| **API-Initiated Eviction** | Пользователь/контроллер | Через Eviction API (drain, PDB) |
| **Taint-Based Eviction** | Control Plane | При недоступности узла (`NoExecute`) |

### Node Pressure Conditions

| Condition | Описание | Threshold (по умолчанию) |
|-----------|----------|-------------------------|
| **`MemoryPressure`** | Нехватка памяти | `< 100Mi` или `< 5%` |
| **`DiskPressure`** | Нехватка места на диске | `< 10%` или `< 1Gi` |
| **`PIDPressure`** | Исчерпание PID | Зависит от ОС |

### Eviction Workflow

```
Ресурсы узла < eviction threshold
    ↓
Eviction Manager активируется
    ↓
Сортировка подов по QoS и потреблению
    ↓
Выселение подов (начиная с BestEffort)
    ↓
Ресурсы освобождены → Stop
```

### QoS и приоритет вытеснения

| QoS Класс | Условия | Приоритет вытеснения |
|-----------|---------|---------------------|
| **`BestEffort`** | Нет `requests`/`limits` | **Первые** |
| **`Burstable`** | `requests` < `limits` | **Вторые** |
| **`Guaranteed`** | `requests` == `limits` | **Последние** |

### Сравнение Eviction и OOMKilled

| Характеристика | Eviction | OOMKilled |
|----------------|----------|-----------|
| **Инициатор** | Eviction Manager / kubelet | OOM Killer (ядро) |
| **Причина** | Нехватка ресурсов на узле | Превышен `limits.memory` контейнера |
| **Статус** | `Evicted` | `OOMKilled` (Reason в Last State) |
| **QoS влияние** | Выселение по приоритету | Не зависит от QoS |
| **Решение** | Освободить ресурсы узла | Увеличить limits или оптимизировать приложение |

## Practical Scenarios

### Диагностика

1. **Проверка статуса:** `kubectl describe pod <pod-name>` → `Reason: Evicted`
2. **Проверка узла:** `kubectl describe node <node-name>` → Conditions
3. **События eviction:** `kubectl get events --field-selector reason=Eviction`
4. **Потребление ресурсов:** `kubectl top node`, `kubectl top pod`

### Основные сценарии

| Сценарий | Сообщение | Решение |
|----------|-----------|---------|
| **MemoryPressure** | `low on resource: memory` | Увеличить limits, добавить узлы, оптимизировать приложение |
| **DiskPressure** | `low on resource: ephemeral-storage` | Очистка логов/образов, увеличить volume |
| **Drain** | `evicted by user request` | Штатная процедура: cordon → drain → uncordon |
| **Taint NoExecute** | `Marking for deletion Pod` | Добавить toleration или устранить причину taint |

### Удаление выселенных подов

```bash
# Удаление всех выселенных подов в namespace
kubectl delete pods --field-selector status.reason=Evicted -n <namespace>

# Удаление всех выселенных подов в кластере
kubectl delete pods --field-selector status.reason=Evicted --all-namespaces
```

## Additional Information

### Eviction thresholds в kubelet

```yaml
# /var/lib/kubelet/config.yaml
evictionHard:
  memory.available: "200Mi"
  nodefs.available: "10%"
evictionSoft:
  memory.available: "500Mi"
evictionSoftGracePeriod:
  memory.available: 2m
```

### Best Practices

| Практика | Описание |
|----------|----------|
| **Всегда указывайте `requests` и `limits`** | Избегайте QoS `BestEffort` |
| **Используйте `Guaranteed` для критичных подов** | Максимальная защита от eviction |
| **Настройте PDB** | Защита от массового выселения при drain |
| **Мониторьте ресурсы узлов** | Алерты на Memory/Disk Pressure |
| **Используйте Cluster Autoscaler** | Автоматическое масштабирование |

### Связанные файлы

- **Диагностика:** [diagnostics.md](./diagnostics.md) — пошаговый чек-лист
- **Memory eviction:** [memory_eviction.md](./memory_eviction.md) — нехватка памяти
- **Disk eviction:** [disk_eviction.md](./disk_eviction.md) — нехватка диска
- **QoS детали:** [qos_and_eviction.md](./qos_and_eviction.md) — QoS и Eviction Manager
- **PDB и Taints:** [pdb_and_taint_eviction.md](./pdb_and_taint_eviction.md) — PDB и taint-based eviction
- **Обслуживание:** [maintenance_eviction.md](./maintenance_eviction.md) — drain процедура
- **Профилактика:** [prevention.md](./prevention.md) — monitoring, alerts, best practices
- **QoS общий:** [qos_limit_and_requests.md](../../../Scheduling/qos_limit_and_requests.md)
- **OOMKilled:** [oomkilled_pods.md](../oomkilled_pods.md) — отличие от eviction

### External Links

- [Node Pressure Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/)
- [Pod Disruptions](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)
- [Pod QoS](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/)
