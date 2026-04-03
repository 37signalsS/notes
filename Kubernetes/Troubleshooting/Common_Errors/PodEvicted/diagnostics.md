# Pod Evicted: Диагностика

## Definitions

**Диагностика Evicted** — процесс выявления причины выселения пода через анализ статуса пода, состояния узла, событий кластера и потребления ресурсов.

**Ключевые артефакты:**
- `Reason: Evicted` — поле в статусе пода
- `Message` — содержит конкретную причину (memory, ephemeral-storage, PID)
- Node Conditions — `MemoryPressure`, `DiskPressure`, `PIDPressure`

## Basic Concepts

### Источники информации

| Источник | Что показывает | Команда |
|----------|---------------|---------|
| Статус пода | Причина eviction | `kubectl describe pod <name>` |
| Conditions узла | Давление ресурсов | `kubectl describe node <name>` |
| События кластера | Хронология eviction | `kubectl get events --field-selector reason=Eviction` |
| Метрики ресурсов | Текущее потребление | `kubectl top node`, `kubectl top pod` |
| Логи узла (SSH) | Детали на уровне ОС | `ssh <node> "df -h"`, `dmesg` |

### Порядок диагностики

```
kubectl describe pod → Reason/Message
    ↓
kubectl describe node → Conditions
    ↓
kubectl get events → Хронология
    ↓
kubectl top → Потребление ресурса
    ↓
SSH на узел → Детали ОС (если нужно)
```

## Practical Scenarios

### Шаг 1: Проверка статуса пода

```bash
kubectl describe pod <pod-name>
```

**Ключевые поля в выводе:**

```
Status:      Failed
Reason:      Evicted
Message:     The node was low on resource: memory.
             The node was low on resource: ephemeral-storage.
```

**Интерпретация Message:**

| Message | Причина | Следующий шаг |
|---------|---------|---------------|
| `low on resource: memory` | MemoryPressure | [Шаг 3a: Память](#шаг-3а-анализ-памяти) |
| `low on resource: ephemeral-storage` | DiskPressure | [Шаг 3b: Диск](#шаг-3b-анализ-диска) |
| `evicted by user request` | Drain | Проверить журнал изменений |
| `Marking for deletion Pod` | Taint NoExecute | Проверить taints узла |

### Шаг 2: Проверка состояния узла

```bash
# Conditions узлов
kubectl describe node <node-name> | grep -A 5 "Conditions:"

# Быстрый поиск узлов в Pressure
kubectl get nodes -o custom-columns=NAME:.metadata.name,MEMORY_PRESSURE:.status.conditions[?(@.type=="MemoryPressure")].status,DISK_PRESSURE:.status.conditions[?(@.type=="DiskPressure")].status
```

**Интерпретация Conditions:**

| Condition | Status | Значение |
|-----------|--------|----------|
| `MemoryPressure` | `True` | Узел испытывает нехватку памяти |
| `DiskPressure` | `True` | Нехватка места на диске |
| `PIDPressure` | `True` | Исчерпаны PID |
| `Ready` | `False` | Узел не готов (возможен Taint-based eviction) |

### Шаг 3a: Анализ памяти

```bash
# Потребление памяти узлом
kubectl top node <node-name>

# Топ подов по памяти
kubectl top pod --all-namespaces --sort-by=memory | head -20

# OOM-события в ядре (требует SSH)
ssh <node-name> "dmesg -T | grep -i 'oom' | tail -20"

# Доступная память
ssh <node-name> "free -h"
```

### Шаг 3b: Анализ диска

```bash
# Дисковое пространство
ssh <node-name> "df -h /var/lib/kubelet"

# Топ по размеру в kubelet
ssh <node-name> "du -sh /var/lib/kubelet/pods/* | sort -rh | head -20"

# Логи контейнеров
ssh <node-name> "du -sh /var/log/containers/* | sort -rh | head -10"
```

### Шаг 4: Проверка событий кластера

```bash
# События eviction (хронология)
kubectl get events --field-selector reason=Eviction --sort-by='.lastTimestamp'

# Все события конкретного узла
kubectl get events --field-selector involvedObject.kind=Node,involvedObject.name=<node-name> --sort-by='.lastTimestamp'
```

**Типичные события:**

| Event | Причина |
|-------|---------|
| `EvictionThresholdMet` | Достигнут порог eviction |
| `AttemptingToEvict` | Eviction Manager начал выселение |
| `Evicted` | Под успешно выселен |
| `FailedToEvict` | Ошибка выселения (PDB блокирует) |

### Шаг 5: Диагностика PDB-блокировок

```bash
# Проверка PDB
kubectl get pdb
kubectl describe pdb <pdb-name>

# События блокировки
kubectl get events --field-selector reason=DisruptionBudgetExceeded
```

### Шаг 6: Диагностика Taint-based Eviction

```bash
# Taints узла
kubectl get node <node-name> -o jsonpath='{.spec.taints}'

# Toleration'ы пода (из YAML)
kubectl get pod <pod-name> -o jsonpath='{.spec.tolerations}'
```

## Additional Information

### Полезные one-liner'ы

```bash
# Все Evicted поды в кластере
kubectl get pods --all-namespaces --field-selector status.reason=Evicted

# Количество Evicted подов на узел
kubectl get pods --all-namespaces --field-selector status.reason=Evicted -o json | jq '.items[].spec.nodeName' | sort | uniq -c | sort -rn

# Узлы с MemoryPressure
kubectl get nodes -o jsonpath='{range .items[?(@.status.conditions[?(@.type=="MemoryPressure")].status=="true")]}{.metadata.name}{"\n"}{end}'

# Топ подов-кандидатов на eviction (BestEffort)
kubectl get pods --all-namespaces -o json | jq '.items[] | select(.status.qosClass=="BestEffort") | .metadata.name'
```

### Связанные файлы

- **Определения:** [definitions.md](./definitions.md) — типы eviction, QoS, thresholds
- **Memory eviction:** [memory_eviction.md](./memory_eviction.md) — детали и решение
- **Disk eviction:** [disk_eviction.md](./disk_eviction.md) — детали и решение
- **QoS и Eviction Manager:** [qos_and_eviction.md](./qos_and_eviction.md)
- **PDB и Taints:** [pdb_and_taint_eviction.md](./pdb_and_taint_eviction.md)
- **Профилактика:** [prevention.md](./prevention.md) — мониторинг, алерты
- **OOMKilled:** [oomkilled_pods.md](../oomkilled_pods.md) — отличие от eviction
- **Общий troubleshooting:** [troubleshooting_overview.md](../../troubleshooting_overview.md)
