# Pod Evicted: Нехватка памяти

## Definitions

**MemoryPressure Eviction** — выселение подов kubelet'ом при нехватке доступной памяти на узле. Триггер — condition `MemoryPressure=True`.

**Сообщение в Events:**

```
The node was low on resource: memory.
```

**Причина:** Суммарное потребление памяти подами + системными процессами превышает доступную память узла с учётом eviction thresholds.

## Basic Concepts

### Как kubelet определяет нехватку памяти

```
Доступная память = Total - (working set всех подов + система)
    ↓
Доступная < evictionHard.memory.available
    ↓
MemoryPressure = True
    ↓
Eviction Manager активируется
```

**Working set memory** = RSS + cache (неподлежащий reclaim) — используется для принятия решения об eviction, а не просто RSS.

### Eviction thresholds для памяти

```yaml
# /var/lib/kubelet/config.yaml
evictionHard:
  memory.available: "200Mi"       # Hard threshold — немедленная eviction
evictionSoft:
  memory.available: "500Mi"       # Soft threshold — с grace period
evictionSoftGracePeriod:
  memory.available: 2m            # Время до начала eviction после soft threshold
evictionMaxPodGracePeriod: 120    # Максимальный grace period для подов
```

| Threshold | Тип | Действие |
|-----------|-----|----------|
| **evictionHard** | Жёсткий | Немедленная eviction при достижении |
| **evictionSoft** | Мягкий | Отсроченная eviction после grace period |

### Порядок выселения подов

```
MemoryPressure detected
    ↓
Сортировка по QoS (приоритет выселения):
  1. BestEffort — по текущему потреблению (больше → первый)
  2. Burstable — по % превышения requests (больше → первый)
  3. Guaranteed — только если 1 и 2 не помогли
    ↓
Graceful termination (SIGTERM → wait → SIGKILL)
    ↓
Page cache reclaim → проверка доступной памяти
    ↓
Если всё ещё Pressure → следующий под
```

### MemoryPressure vs OOMKilled

| Характеристика | MemoryPressure Eviction | OOMKilled |
|----------------|------------------------|-----------|
| **Инициатор** | Eviction Manager (kubelet) | OOM Killer (ядро Linux) |
| **Уровень** | Узел (node-level) | Контейнер (container-level) |
| **Причина** | Вся память узла исчерпана | Контейнер превысил `limits.memory` |
| **Сообщение** | `low on resource: memory` | `OOMKilled` (exit code 137) |
| **QoS влияние** | Выселение по приоритету | Не зависит от QoS |
| **Сообщение в Events** | `Evicted` | `Reason: OOMKilled` в `lastState` |

> **Ключевое отличие:** Eviction — узел спасает себя, OOMKilled — ядро убивает конкретный контейнер.

## Practical Scenarios

### Диагностика

**Шаг 1: Подтверждение MemoryPressure**

```bash
# Conditions узла
kubectl describe node <node-name> | grep -A 5 "MemoryPressure"

# Быстрая проверка всех узлов
kubectl get nodes -o custom-columns=NAME:.metadata.name,MEMORY_PRESSURE:.status.conditions[?(@.type=="MemoryPressure")].status
```

**Вывод при Pressure:**

```
  MemoryPressure   True    ...   KubeletHasInsufficientMemory   kubelet has insufficient memory available
```

**Шаг 2: Анализ потребления**

```bash
# Доступная память на узле (SSH)
ssh <node-name> "free -h"

# Топ подов по памяти
kubectl top pod --all-namespaces --sort-by=memory | head -20

# Детализация по контейнерам (CRI)
ssh <node-name> "crictl stats --sort-by=memory --descending | head -20"

# OOM-события в ядре
ssh <node-name> "dmesg -T | grep -i 'oom\|killed process' | tail -20"
```

**Шаг 3: Определение пода-виновника**

```bash
# Подробная статика потребления
kubectl describe node <node-name> | grep -A 30 "Allocated resources:"

# Pods с высоким потреблением памяти
kubectl get pods --all-namespaces -o custom-columns=NAME:.metadata.name,NS:.metadata.namespace,MEMORY_REQ:.spec.containers[*].resources.requests.memory,MEMORY_LIM:.spec.containers[*].resources.limits.memory | sort
```

### Решение

#### Быстрые меры

| Действие | Команда | Эффект |
|----------|---------|--------|
| Удалить выселенные поды | `kubectl delete pods --field-selector status.reason=Evicted -A` | Освобождение записей etcd |
| Рестарт проблемного пода | `kubectl delete pod <name>` | Пересоздание на другом узле |
| Drain узла | `kubectl drain <node> --ignore-daemonsets` | Миграция всех подов |

#### Долгосрочные меры

| Мера | Описание |
|------|----------|
| **Увеличить `limits.memory`** | Для подов, которые легитимно потребляют больше |
| **Добавить узлы** | Горизонтальное масштабирование кластера |
| **Оптимизировать приложение** | Найти и устранить утечки памяти |
| **Настроить QoS** | `Guaranteed` для критичных подов (requests == limits) |
| **Настроить `kubeReserved`** | Резерв памяти для системных процессов |

#### Настройка kubeReserved

```yaml
# /var/lib/kubelet/config.yaml
kubeReserved:
  cpu: "200m"
  memory: "512Mi"        # Резерв для kubelet + container runtime
  ephemeral-storage: "1Gi"
kubeReservedCgroup: "/kubelet"
systemReserved:
  memory: "256Mi"        # Резерв для ОС
systemReservedCgroup: "/system"
enforceNodeAllocatable:
  - pods
  - kubeReserved
  - systemReserved
```

> После изменения требуется restart kubelet: `systemctl restart kubelet`

## Additional Information

### Мониторинг и алерты

```yaml
# Prometheus alerts
- alert: NodeMemoryPressure
  expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "MemoryPressure на узле {{ $labels.node }}"

- alert: NodeMemoryHigh
  expr: (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 > 85
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Память узла {{ $labels.instance }} > 85%"

- alert: PodEvictedMemory
  expr: kube_pod_status_reason{reason="Evicted"} == 1
    and on(pod, namespace) (kube_pod_status_phase{phase="Failed"} == 1)
  for: 1m
  labels:
    severity: critical
```

### Типичные значения memory limits

| Приложение | Requests | Limits | Примечание |
|------------|----------|--------|------------|
| Nginx | 64Mi | 128Mi | Статический контент |
| Node.js API | 128Mi | 256Mi | Зависит от нагрузки |
| Java Spring Boot | 512Mi | 1Gi | Требуется `-XX:MaxRAMPercentage` |
| Python Flask | 128Mi | 256Mi | GIL, однопоточность |
| PostgreSQL | 256Mi | 512Mi | Зависит от `shared_buffers` |

> Значения зависят от конкретной нагрузки и требуют эмпирической настройки.

### Предотвращение

| Практика | Описание |
|----------|----------|
| **Всегда указывайте requests и limits** | Избегайте QoS `BestEffort` |
| **Используйте `Guaranteed` для критичных подов** | Максимальная защита от eviction |
| **Настройте `kubeReserved`** | Защита системных процессов |
| **Используйте VPA** | Автоматическая подстройка ресурсов |
| **Настройте PDB** | Защита от массового выселения |

### Связанные файлы

- **Определения:** [definitions.md](./definitions.md) — типы eviction, QoS, thresholds
- **Диагностика:** [diagnostics.md](./diagnostics.md) — общий чек-лист
- **Disk eviction:** [disk_eviction.md](./disk_eviction.md) — нехватка диска
- **QoS и Eviction Manager:** [qos_and_eviction.md](./qos_and_eviction.md)
- **OOMKilled:** [oomkilled_pods.md](../oomkilled_pods.md) — отличие от memory eviction
- **QoS общий:** [qos_limit_and_requests.md](../../../Scheduling/qos_limit_and_requests.md)
- **Kubelet:** [kubelet.md](../../../Concepts/kubelet.md) — конфигурация kubelet
