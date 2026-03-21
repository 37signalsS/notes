# Pod в состоянии `Pending`: Распространенные случаи и решения

## 1. Нехватка ресурсов (`Insufficient cpu/memory`)

**Сообщение:**

```
0/3 nodes are available: 3 Insufficient cpu.
0/5 nodes are available: 5 Insufficient memory.
```

**Причина:** Под запрашивает больше ресурсов (`requests`), чем доступно на любом узле.

**Решение:**

| Вариант | Команда / Действие |
|---------|-------------------|
| **Уменьшить `requests`** | Исправить манифест: `resources.requests.memory: "128Mi"` |
| **Добавить узлы** | `kubectl apply -f new-node.yaml` или через Cluster Autoscaler |
| **Освободить ресурсы** | Удалить/переместить другие поды |
| **Вертикальное масштабирование** | Увеличить ресурсы существующих узлов |

**Проверка:**

```bash
# Сколько ресурсов запрашивает под
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].resources.requests}'

# Сколько доступно на узлах
kubectl describe nodes | grep -A 10 "Allocated resources"
```

> **Best Practice:** Используйте `Burstable` QoS для гибкости. См. [`qos_limit_and_requests.md`](../../../Scheduling/qos_limit_and_requests.md)

---

## 2. Несоответствие `nodeSelector` / `nodeAffinity`

**Сообщение:**

```
0/3 nodes are available: 3 node(s) didn't match Pod's node affinity/selector.
```

**Причина:** Ни один узел не имеет требуемых меток.

**Решение:**

```bash
# Проверить метки на узлах
kubectl get nodes --show-labels

# Добавить метку на узел
kubectl label node <node-name> disktype=ssd

# Или исправить nodeSelector в манифесте
```

**Пример:**

```yaml
# ❌ Ошибка: метка не существует
nodeSelector:
  disktype: ssd

# ✅ Решение: добавить метку на узел
kubectl label node worker-1 disktype=ssd
```

> **См. также:** [`affinity.md`](../../../Scheduling/affinity.md)

---

## 3. Узел имеет `Taints`, у пода нет `Tolerations`

**Сообщение:**

```
0/3 nodes are available: 3 node(s) had taint {dedicated: master}, that the pod didn't tolerate.
```

**Причина:** Все узлы "отравлены" taints, которые под не "терпит".

**Решение:**

```yaml
# Добавить toleration в спецификацию пода
spec:
  tolerations:
  - key: "dedicated"
    operator: "Equal"
    value: "master"
    effect: "NoSchedule"
```

**Проверка taints:**

```bash
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

> **См. также:** [`taints_and_tolerations.md`](../../../Scheduling/taints_and_tolerations.md)

---

## 4. `PersistentVolumeClaim` (PVC) в состоянии `Pending`

**Сообщение:**

```
0/3 nodes are available: 3 pod has unbound immediate PersistentVolumeClaims.
```

**Причина:** PVC не может быть удовлетворен — нет подходящего PV или StorageClass.

**Диагностика:**

```bash
kubectl describe pvc <pvc-name>
```

**Возможные причины:**

| Причина | Решение |
|---------|---------|
| **Нет PV** | Создать PV: `kubectl create -f pv.yaml` |
| **Неверный StorageClass** | Проверить: `kubectl get storageclass` |
| **Нехватка места** | Освободить место или увеличить PV |
| **AccessMode несовместим** | Изменить accessMode или использовать другой PV |

**Пример:**

```yaml
# Проверка StorageClass
kubectl get storageclass

# Создание PV
apiVersion: v1
kind: PersistentVolume
metadata:
  name: my-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: manual
  hostPath:
    path: "/mnt/data"
```

> **См. также:** [`pv_and_pvc.md`](../../Storage/pv_and_pvc.md), [`csi_drivers_comparison.md`](../../Storage/CSI/csi_drivers_comparison.md)

---

## 5. Превышен `ResourceQuota`

**Сообщение:**

```
failed quota: team-a-quota: must specify limits.cpu,limits.memory
```

**Причина:** Namespace имеет квоты, которые не позволяют создать под.

**Диагностика:**

```bash
kubectl describe resourcequota -n <namespace>
```

**Решение:**

- Увеличить квоту
- Уменьшить `requests` пода
- Удалить другие поды

```yaml
# Увеличение квоты
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-a-quota
  namespace: team-a
spec:
  hard:
    requests.cpu: "20"      # Было 10
    requests.memory: 100Gi  # Было 50Gi
```

> **См. также:** [`qos_limit_and_requests.md`](../../Scheduling/qos_limit_and_requests.md)

---

## 6. `PriorityClass` и вытеснение

**Сценарий:** Под с высоким приоритетом остается в `Pending`, если не может вытеснить поды с низким приоритетом.

**Диагностика:**

```bash
# Проверка PriorityClass пода
kubectl get pod <pod-name> -o jsonpath='{.spec.priorityClassName}'

# Список PriorityClass
kubectl get priorityclass
```

**Решение:**

- Добавить ресурсы в кластер
- Настроить Preemption
- Уменьшить приоритет пода

> **См. также:** [PriorityClass](../../../Concepts/priorityclass.md)

---

## Ссылки

- **[Диагностика](./diagnostics.md)** — пошаговый чек-лист
- **[Определения и концепции](./definitions_and_concepts.md)** — базовая информация
