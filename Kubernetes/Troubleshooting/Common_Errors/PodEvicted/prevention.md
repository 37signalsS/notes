# Pod Evicted: Профилактика

## Определения

**Профилактика eviction (выселения)** — комплекс мер по конфигурации ресурсов, мониторингу и планированию, направленный на минимизацию вероятности выселения подов.

**Цели профилактики:**

1. Не допустить Node Pressure (давление на ресурсы узла: MemoryPressure, DiskPressure).
2. Гарантировать доступность критичных подов при drain (выводе узла из эксплуатации).
3. Своевременно обнаруживать деградацию ресурсов через мониторинг.

## Основные концепции

### Уровни профилактики

| Уровень | Мера | От какого выселения защищает |
|---------|------|---------------------------|
| **Под** | requests + limits = Guaranteed | Node Pressure (приоритет) |
| **Приложение** | PDB (Pod Disruption Budget) | Массовый drain |
| **Узел** | kubeReserved + eviction thresholds | System starvation (голодание системы) |
| **Кластер** | Cluster Autoscaler | Capacity exhaustion (исчерпание емкости) |
| **Мониторинг** | Prometheus alerts | Все типы (раннее обнаружение) |

### QoS как фундамент защиты

QoS (Quality of Service — качество обслуживания) определяет приоритет пода при выселении:

```
Guaranteed (requests == limits)
    ← максимальная защита от eviction
Burstable (requests < limits)
    ← средняя защита
BestEffort (нет requests/limits)
    ← первые кандидаты на eviction
```

> Детали: [qos_and_eviction.md](./qos_and_eviction.md), [qos_limit_and_requests.md](../../../Scheduling/qos_limit_and_requests.md)

## Практические сценарии

### 1. Настройка Guaranteed QoS для критичных подов

Для перевода пода в класс Guaranteed необходимо, чтобы лимиты (limits) были равны запросам (requests) для всех контейнеров.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: critical-app
spec:
  containers:
  - name: app
    image: critical-app:latest
    resources:
      requests:
        memory: "512Mi"
        cpu: "500m"
      limits:
        memory: "512Mi"    # == requests → Guaranteed
        cpu: "500m"        # == requests → Guaranteed
```

### 2. Использование Pod Disruption Budget

PDB (Pod Disruption Budget) ограничивает количество одновременно завершаемых подов приложения при добровольных прерываниях (например, drain узла).

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
spec:
  minAvailable: 2                # или maxUnavailable: 1
  selector:
    matchLabels:
      app: my-app
```

| Подход | Когда использовать |
|--------|-------------------|
| `minAvailable: N` | Важно сохранить минимум N работающих подов |
| `maxUnavailable: 1` | Допустимо потерять не более 1 пода при drain |

> Защита действует **только** при drain или rolling update. Детали: [pod_disruption_budget.md](../../../Autoscaling/pod_disruption_budget.md)

### 3. Настройка мониторинга и алертов

Использование Prometheus для раннего обнаружения признаков грядущего выселения.

```yaml
# Prometheus alerts
- alert: NodeMemoryPressure
  expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "MemoryPressure на узле {{ $labels.node }}"

- alert: NodeDiskPressure
  expr: kube_node_status_condition{condition="DiskPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "DiskPressure на узле {{ $labels.node }}"

- alert: NodeFilesystemAlmostFull
  expr: node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes * 100 < 15
  for: 10m
  labels:
    severity: warning

- alert: PodEvicted
  expr: kube_pod_status_reason{reason="Evicted"} == 1
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Pod {{ $labels.pod }} evicted в namespace {{ $labels.namespace }}"
```

### 4. Cluster Autoscaler

Автоматическое добавление узлов при невозможности запланировать поды из-за нехватки ресурсов.

```yaml
# Cluster Autoscaler автоматически добавит узлы
# при появлении Pending подов из-за нехватки CPU/memory
```

Работает в облачных средах: AWS ASG (Auto Scaling Group), GCP MIG (Managed Instance Group), Azure VMSS (Virtual Machine Scale Set). Для bare metal решений используется [Karpenter](https://karpenter.sh/).

### 5. Очистка выселенных подов

Выселенные поды остаются в кластере со статусом `Failed/Evicted` и требуют ручного или автоматизированного удаления.

```bash
# Удаление всех выселенных подов в namespace
kubectl delete pods --field-selector status.reason=Evicted -n <namespace>

# Удаление всех выселенных подов в кластере
kubectl delete pods --field-selector status.reason=Evicted --all-namespaces
```

## Дополнительная информация

### Резюме лучших практик

| Практика | Описание | Ссылка |
|----------|----------|--------|
| **Всегда указывайте requests и limits** | Избегайте использования QoS `BestEffort` | [qos_limit_and_requests.md](../../../Scheduling/qos_limit_and_requests.md) |
| **PDB для критичных сервисов** | Защита от массового выселения при обслуживании | [pod_disruption_budget.md](../../../Autoscaling/pod_disruption_budget.md) |
| **kubeReserved на узлах** | Резервирование ресурсов для системных процессов | [memory_eviction.md](./memory_eviction.md) |

### Смотрите также

- [Node Pressure Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/)
- [Pod Disruptions](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)
- [Pod QoS](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/)
