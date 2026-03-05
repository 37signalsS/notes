# Pod в состоянии `Pending` (Ожидание)

## Определения

**`Pending`** — статус пода, означающий, что API-сервер принял спецификацию пода, но планировщик (`kube-scheduler`) не может разместить его на одном из узлов. Под ожидает решения планировщика.

> - Taints и tolerations: [`taints_and_tolerations.md`](../../Scheduling/taints_and_tolerations.md)
> - Affinity: [`affinity.md`](../../Scheduling/affinity.md)
> - QoS и ресурсы: [`qos_limit_and_requests.md`](../../Scheduling/qos_limit_and_requests.md)
> - PV/PVC: [`pv_and_pvc.md`](../../Storage/pv_and_pvc.md)
> - PriorityClass: [`priorityclass.md`](../../Concepts/priorityclass.md)

## Основные концепции

### Workflow планировщика

```
Pod создан (Pending)
    ↓
kube-scheduler обнаруживает под
    ↓
Фильтрация узлов (Predicate)
    ↓
Оценка узлов (Priority)
    ↓
Выбор лучшего узла
    ↓
Binding → Pod запускается
```

### Причины Pending по категориям

| Категория | Причины | % случаев |
|-----------|---------|-----------|
| **Ресурсы** | Insufficient cpu/memory | ~40% |
| **Taints** | Узлы имеют taints без tolerations | ~25% |
| **Affinity** | Не выполнены правила affinity | ~20% |
| **PVC** | PVC в Pending (нет PV/StorageClass) | ~10% |
| **Другие** | NodeSelector, PodSecurityPolicy, Quota | ~5% |

### Механизмы ограничения планирования

| Механизм | Описание |
|----------|----------|
| **`requests`/`limits`** | Планировщик ищет узлы с достаточными ресурсами | [`qos_limit_and_requests.md`](../../Scheduling/qos_limit_and_requests.md) |
| **`nodeSelector`** | Простой выбор узлов по меткам | [`affinity.md`](../../Scheduling/affinity.md) |
| **`nodeAffinity`** | Продвинутое правило выбора узлов | [`affinity.md`](../../Scheduling/affinity.md) |
| **`podAffinity`/`podAntiAffinity`** | Размещение относительно других подов | [`affinity.md`](../../Scheduling/affinity.md) |
| **`taints`/`tolerations`** | "Отталкивание" подов от узлов | [`taints_and_tolerations.md`](../../Scheduling/taints_and_tolerations.md) |
| **`topologySpreadConstraints`** | Равномерное распределение по топологии | [`pod_distribution.md`](../../Autoscaling/pod_distribution.md) |
| **`PriorityClass`** | Приоритет планирования | [`priorityclass.md`](../../Concepts/priorityclass.md) |

## Практические сценарии

### Диагностика: пошаговый чек-лист

#### Шаг 1: Проверка статуса пода

```bash
kubectl describe pod <pod-name>
```

**Ищите в разделе `Events`:**
```
Type     Reason            Age        From               Message
----     ------            ----       ----               -------
Warning  FailedScheduling  <unknown>  default-scheduler  0/3 nodes are available: 3 Insufficient cpu.
```

#### Шаг 2: Анализ доступных ресурсов

```bash
# Ресурсы узлов
kubectl top nodes

# Запрошенные ресурсы (requires metrics-server)
kubectl describe nodes | grep -A 5 "Allocated resources"

# Свободные ресурсы
kubectl get nodes -o custom-columns=NAME:.metadata.name,CPU:.status.capacity.cpu,MEM:.status.capacity.memory
```

#### Шаг 3: Проверка Taints

```bash
# Taints на узлах
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints

# Детальная информация
kubectl describe node <node-name> | grep -A 5 "Taints:"
```

#### Шаг 4: Проверка Affinity и NodeSelector

```bash
# NodeSelector пода
kubectl get pod <pod-name> -o jsonpath='{.spec.nodeSelector}'

# Affinity пода
kubectl get pod <pod-name> -o jsonpath='{.spec.affinity}'

# Метки на узлах
kubectl get nodes --show-labels
```

#### Шаг 5: Проверка PVC

```bash
# Статус PVC
kubectl get pvc -n <namespace>

# Описание PVC
kubectl describe pvc <pvc-name>

# Доступные PV
kubectl get pv
```

#### Шаг 6: Проверка ResourceQuota

```bash
# Квоты в namespace
kubectl describe resourcequota -n <namespace>

# LimitRange
kubectl describe limitrange -n <namespace>
```

### Распространенные случаи и решения

#### 1. Нехватка ресурсов (`Insufficient cpu/memory`)

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

> **Best Practice:** Используйте `Burstable` QoS для гибкости. См. [`qos_limit_and_requests.md`](../../Scheduling/qos_limit_and_requests.md)

#### 2. Несоответствие `nodeSelector` / `nodeAffinity`

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

> **См. также:** [`affinity.md`](../../Scheduling/affinity.md)

#### 3. Узел имеет `Taints`, у пода нет `Tolerations`

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

> **См. также:** [`taints_and_tolerations.md`](../../Scheduling/taints_and_tolerations.md)

#### 4. `PersistentVolumeClaim` (PVC) в состоянии `Pending`

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

#### 5. Превышен `ResourceQuota`

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

#### 6. `PriorityClass` и вытеснение

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

> **См. также:** [`priorityclass.md`](../../Concepts/priorityclass.md)

### Мониторинг Pending подов

```bash
# Все Pending поды
kubectl get pods --field-selector status.phase=Pending

# Pending поды с сортировкой по времени
kubectl get pods --field-selector status.phase=Pending --sort-by='.metadata.creationTimestamp'

# Алерт Prometheus
alert: PendingPodsHigh
expr: count(kube_pod_status_phase{phase="Pending"}) > 5
for: 5m
```

> **См. также:** [`pod_distribution.md`](../../Autoscaling/pod_distribution.md)

## Дополнительная информация

### Взаимодействие механизмов планирования

```
Планировщик проверяет (в порядке):
1. NodeSelector (простой)
2. NodeAffinity (продвинутый)
3. Taints/Tolerations (фильтр)
4. PodAffinity/PodAntiAffinity (относительно других подов)
5. ResourceRequests (CPU, Memory)
6. TopologySpreadConstraints (распределение)
```

> **Важно:** Все правила должны выполняться одновременно. Слишком сложные комбинации могут привести к вечному `Pending`.

### Таблица решений

| Симптом | Первая команда | Вероятное решение |
|---------|----------------|-------------------|
| `Insufficient cpu/memory` | `kubectl top nodes` | Уменьшить requests / добавить узлы |
| `didn't match node affinity` | `kubectl get nodes --show-labels` | Добавить метку / исправить affinity |
| `had taint ... didn't tolerate` | `kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints` | Добавить toleration |
| `unbound PersistentVolumeClaims` | `kubectl describe pvc` | Создать PV / исправить StorageClass |
| `failed quota` | `kubectl describe resourcequota` | Увеличить квоту / уменьшить requests |

### Best Practices

| Практика | Описание |
|----------|----------|
| **Всегда указывайте `requests` и `limits`** | Предсказуемое планирование, QoS |
| **Используйте `nodeAffinity` вместо `nodeSelector`** | Больше гибкости |
| **Комбинируйте с `tolerations`** | Для системных подов |
| **Настройте `topologySpreadConstraints`** | Высокая доступность |
| **Мониторьте Pending поды** | Алерты на Pending > 5 минут |

### Ссылки

- [Kubernetes Scheduler](https://kubernetes.io/docs/concepts/scheduling-eviction/kube-scheduler/)
- [Pod Priority and Preemption](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/)
- [Configure Pod Assignment](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/)
