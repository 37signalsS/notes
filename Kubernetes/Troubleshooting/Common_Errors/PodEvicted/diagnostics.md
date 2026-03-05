# Pod Evicted: Диагностика

## Диагностика: пошаговый чек-лист

### Шаг 1: Проверка статуса пода

```bash
kubectl describe pod <pod-name>
```

**Ищите в выводе:**

```
Reason:   Evicted
Message:  The node was low on resource: memory.
          The node was low on resource: ephemeral-storage.
```

### Шаг 2: Проверка состояния узла

```bash
# Conditions узлов
kubectl describe node <node-name> | grep -A 5 "Conditions:"

# Поиск узлов в Pressure
kubectl get nodes -o custom-columns=NAME:.metadata.name,MEMORY_PRESSURE:.status.conditions[?(@.type=="MemoryPressure")].status,DISK_PRESSURE:.status.conditions[?(@.type=="DiskPressure")].status
```

### Шаг 3: Анализ потребления ресурсов

```bash
# Потребление памяти узлом
kubectl top node <node-name>

# Потребление подами на узле
kubectl top pod --all-namespaces --sort-by=cpu

# Проверка дискового пространства (требуется SSH)
ssh <node-name> "df -h /var/lib/kubelet"
ssh <node-name> "du -sh /var/lib/kubelet/pods/*"
```

### Шаг 4: Проверка событий узла

```bash
# События eviction
kubectl get events --field-selector reason=Eviction --sort-by='.lastTimestamp'

# Все события узла
kubectl get events --field-selector involvedObject.kind=Node --sort-by='.lastTimestamp'
```
