# Выселенные поды (`Evicted`)

## Определения

**`Evicted`** — статус пода, означающий, что Kubernetes принудительно выселил под с узла. Происходит при нехватке ресурсов на узле (память, диск, PID) или при выводе узла из эксплуатации.

> - QoS и ресурсы: [`qos_limit_and_requests.md`](../../Scheduling/qos_limit_and_requests.md)
> - OOMKilled: [`oomkilled_pods.md](./oomkilled_pods.md)
> - Taints: [`taints_and_tolerations.md`](../../Scheduling/taints_and_tolerations.md)
> - Обслуживание узлов: [`node_maintenance.md`](../../Operations/node_maintenance.md)
> - Pod Disruption Budget: [`pod_disruption_budget.md`](../../Autoscaling/pod_disruption_budget.md)

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

### Связь с QoS классами

При нехватке ресурсов Kubernetes выселяет поды в порядке приоритета:

```
1. BestEffort (нет requests/limits)
   ↓
2. Burstable (requests < limits)
   ↓
3. Guaranteed (requests == limits)
```

> **См. также:** [`qos_limit_and_requests.md`](../../Scheduling/qos_limit_and_requests.md)

| QoS Класс | Условия | Приоритет вытеснения |
|-----------|---------|---------------------|
| **`BestEffort`** | Нет `requests`/`limits` | **Первые** |
| **`Burstable`** | `requests` < `limits` | **Вторые** |
| **`Guaranteed`** | `requests` == `limits` | **Последние** |

### Eviction Manager

Компонент `kubelet`, который мониторит ресурсы узла и принимает решения о выселении подов.

**Workflow:**
```
Ресурсы узла < threshold
    ↓
Eviction Manager активируется
    ↓
Сортировка подов по QoS и потреблению
    ↓
Выселение подов (начиная с BestEffort)
    ↓
Ресурсы освобождены → Stop
```

## Практические сценарии

### Диагностика: пошаговый чек-лист

#### Шаг 1: Проверка статуса пода

```bash
kubectl describe pod <pod-name>
```

**Ищите в выводе:**
```
Reason:   Evicted
Message:  The node was low on resource: memory.
          The node was low on resource: ephemeral-storage.
```

#### Шаг 2: Проверка состояния узла

```bash
# Conditions узлов
kubectl describe node <node-name> | grep -A 5 "Conditions:"

# Поиск узлов в Pressure
kubectl get nodes -o custom-columns=NAME:.metadata.name,MEMORY_PRESSURE:.status.conditions[?(@.type=="MemoryPressure")].status,DISK_PRESSURE:.status.conditions[?(@.type=="DiskPressure")].status
```

#### Шаг 3: Анализ потребления ресурсов

```bash
# Потребление памяти узлом
kubectl top node <node-name>

# Потребление подами на узле
kubectl top pod --all-namespaces --sort-by=cpu

# Проверка дискового пространства (требуется SSH)
ssh <node-name> "df -h /var/lib/kubelet"
ssh <node-name> "du -sh /var/lib/kubelet/pods/*"
```

#### Шаг 4: Проверка событий узла

```bash
# События eviction
kubectl get events --field-selector reason=Eviction --sort-by='.lastTimestamp'

# Все события узла
kubectl get events --field-selector involvedObject.kind=Node --sort-by='.lastTimestamp'
```

### Распространенные случаи и решения

#### 1. Eviction из-за нехватки памяти (`MemoryPressure`)

**Сообщение:**
```
The node was low on resource: memory.
```

**Причина:** Суммарное потребление памяти подами превышает доступную память узла.

**Диагностика:**
```bash
# Проверка доступной памяти
free -h

# Потребление подами
kubectl top pod --all-namespaces --sort-by=memory

# OOM события в ядре
dmesg -T | grep -i "oom"
```

**Решение:**
| Вариант | Описание |
|---------|----------|
| **Увеличить `limits.memory`** | Для подов с низким приоритетом |
| **Добавить узлы** | Горизонтальное масштабирование |
| **Уменьшить потребление** | Оптимизация приложений |
| **Настроить QoS** | Использовать `Guaranteed` для критичных подов |

**Prevention:**
```yaml
# Настройка eviction thresholds в kubelet
# /var/lib/kubelet/config.yaml
evictionHard:
  memory.available: "200Mi"
  nodefs.available: "10%"
evictionSoft:
  memory.available: "500Mi"
evictionSoftGracePeriod:
  memory.available: 2m
```

> **См. также:** [`oomkilled_pods.md`](./oomkilled_pods.md)

#### 2. Eviction из-за нехватки диска (`DiskPressure`)

**Сообщение:**
```
The node was low on resource: ephemeral-storage.
```

**Причина:** Нехватка места на диске для ephemeral-данных (логи, temporary files, emptyDir).

**Диагностика:**
```bash
# Проверка дискового пространства
df -h /var/lib/kubelet

# Поиск больших файлов
du -ah /var/lib/kubelet | sort -rh | head -20

# Проверка логов контейнеров
du -sh /var/log/containers/*
```

**Решение:**
| Вариант | Описание |
|---------|----------|
| **Очистка логов** | Настроить log rotation |
| **Очистка образов** | `crictl rmi --prune` или `docker image prune` |
| **Увеличение диска** | Расширить volume узла |
| **Настройка limits** | `ephemeral-storage` limits для подов |

**Настройка limits для ephemeral-storage:**
```yaml
resources:
  requests:
    ephemeral-storage: "1Gi"
  limits:
    ephemeral-storage: "5Gi"
```

**Настройка log rotation для containerd:**
```toml
# /etc/containerd/config.toml
[plugins."io.containerd.grpc.v1.cri".containerd.log]
  level = "info"
  max_size = "100Mi"
  max_backups = 5
```

#### 3. Eviction при обслуживании узла (`drain`)

**Сообщение:**
```
pod evicted from node <node-name> by user request
```

**Причина:** Администратор выполнил `kubectl drain` для обслуживания узла.

**Решение:**
```bash
# Стандартная процедура обслуживания
# 1. Cordon (запрет новых подов)
kubectl cordon <node-name>

# 2. Drain (выселение подов)
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data

# 3. Обслуживание узла
# ... reboot, update, etc.

# 4. Uncordon (возврат в работу)
kubectl uncordon <node-name>
```

> **См. также:** [`node_maintenance.md`](../../Operations/node_maintenance.md)

#### 4. Eviction из-за `PodDisruptionBudget`

**Сценарий:** PDB не позволяет выселить достаточно подов для обслуживания.

**Диагностика:**
```bash
# Проверка PDB
kubectl get pdb
kubectl describe pdb <pdb-name>

# Проверка disrupted подов
kubectl get events --field-selector reason=DisruptionBudgetExceeded
```

**Решение:**
- Пересмотреть PDB (увеличить `maxUnavailable`)
- Добавить узлы для размещения подов
- Временно удалить PDB (не рекомендуется для production)

> **См. также:** [`pod_disruption_budget.md`](../../Autoscaling/pod_disruption_budget.md)

#### 5. Taint-based Eviction (`NoExecute`)

**Сообщение:**
```
Marking for deletion Pod <pod-name>
```

**Причина:** Узел получил taint с эффектом `NoExecute`, под не имеет соответствующего `toleration`.

**Диагностика:**
```bash
# Проверка taints узла
kubectl get node <node-name> -o jsonpath='{.spec.taints}'

# Проверка tolerations пода
kubectl get pod <pod-name> -o jsonpath='{.spec.tolerations}'
```

**Решение:**
```yaml
# Добавить toleration в под
spec:
  tolerations:
  - key: "node.kubernetes.io/unreachable"
    operator: "Exists"
    effect: "NoExecute"
    tolerationSeconds: 300
```

> **См. также:** [`taints_and_tolerations.md`](../../Scheduling/taints_and_tolerations.md)

### Prevention (Профилактика)

#### 1. Настройка QoS для критичных подов

```yaml
# Guaranteed QoS для критичных сервисов
resources:
  requests:
    memory: "512Mi"
    cpu: "500m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

#### 2. Pod Disruption Budget

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: my-app
```

#### 3. Мониторинг и алерты

```yaml
# Prometheus alerts
- alert: NodeMemoryPressure
  expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning

- alert: NodeDiskPressure
  expr: kube_node_status_condition{condition="DiskPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning

- alert: PodEvicted
  expr: kube_pod_status_reason{reason="Evicted"} == 1
  for: 1m
  labels:
    severity: critical
```

#### 4. Cluster Autoscaler

Автоматическое добавление узлов при нехватке ресурсов:

```yaml
# Cluster Autoscaler автоматически добавит узлы
# при появлении Pending подов из-за нехватки ресурсов
```

> **См. также:** [`cluster_autoscaler_detailed.md`](../../Autoscaling/cluster_autoscaler_detailed.md)

## Дополнительная информация

### Удаление выселенных подов

Выселенные поды не удаляются автоматически:

```bash
# Удаление одного пода
kubectl delete pod <pod-name>

# Удаление всех выселенных подов в namespace
kubectl delete pods --field-selector status.reason=Evicted -n <namespace>

# Удаление всех выселенных подов в кластере
kubectl delete pods --field-selector status.reason=Evicted --all-namespaces
```

> **Важно:** Deployment/ReplicaSet автоматически создаст новые поды взамен удаленных.

### Сравнение Eviction и OOMKilled

| Характеристика | Eviction | OOMKilled |
|----------------|----------|-----------|
| **Инициатор** | Eviction Manager / kubelet | OOM Killer (ядро) |
| **Причина** | Нехватка ресурсов на узле | Превышен limits.memory контейнера |
| **Статус** | `Evicted` | `OOMKilled` (Reason в Last State) |
| **QoS влияние** | Выселение по приоритету | Не зависит от QoS |
| **Решение** | Освободить ресурсы узла | Увеличить limits или оптимизировать приложение |

### Best Practices

| Практика | Описание |
|----------|----------|
| **Всегда указывайте `requests` и `limits`** | Избегайте QoS `BestEffort` |
| **Используйте `Guaranteed` для критичных подов** | Максимальная защита от eviction |
| **Настройте PDB** | Защита от массового выселения |
| **Мониторьте ресурсы узлов** | Алерты на Memory/Disk Pressure |
| **Используйте Cluster Autoscaler** | Автоматическое масштабирование |

### Ссылки

- [Node Pressure Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/)
- [Pod Disruption Budgets](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)
- [Configure Quality of Service](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/)
