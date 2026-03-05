# Pod в состоянии `Pending`: Диагностика

## Пошаговый чек-лист

### Шаг 1: Проверка статуса пода

```bash
kubectl describe pod <pod-name>
```

**Ищите в разделе `Events`:**

```
Type     Reason            Age        From               Message
----     ------            ----       ----               -------
Warning  FailedScheduling  <unknown>  default-scheduler  0/3 nodes are available: 3 Insufficient cpu.
```

---

### Шаг 2: Анализ доступных ресурсов

```bash
# Ресурсы узлов
kubectl top nodes

# Запрошенные ресурсы (requires metrics-server)
kubectl describe nodes | grep -A 5 "Allocated resources"

# Свободные ресурсы
kubectl get nodes -o custom-columns=NAME:.metadata.name,CPU:.status.capacity.cpu,MEM:.status.capacity.memory
```

---

### Шаг 3: Проверка Taints

```bash
# Taints на узлах
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints

# Детальная информация
kubectl describe node <node-name> | grep -A 5 "Taints:"
```

---

### Шаг 4: Проверка Affinity и NodeSelector

```bash
# NodeSelector пода
kubectl get pod <pod-name> -o jsonpath='{.spec.nodeSelector}'

# Affinity пода
kubectl get pod <pod-name> -o jsonpath='{.spec.affinity}'

# Метки на узлах
kubectl get nodes --show-labels
```

---

### Шаг 5: Проверка PVC

```bash
# Статус PVC
kubectl get pvc -n <namespace>

# Описание PVC
kubectl describe pvc <pvc-name>

# Доступные PV
kubectl get pv
```

---

### Шаг 6: Проверка ResourceQuota

```bash
# Квоты в namespace
kubectl describe resourcequota -n <namespace>

# LimitRange
kubectl describe limitrange -n <namespace>
```

---

## Ссылки

- **[Распространенные случаи и решения](./common_cases_and_solutions.md)** — решения для типичных проблем
- **[Определения и концепции](./definitions_and_concepts.md)** — базовая информация
