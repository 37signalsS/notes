# Pod Evicted: Диагностика и поиск первопричин

## Определения

**Диагностика выселения (Eviction Diagnostics)** — системный процесс выявления триггеров и условий, приведших к принудительному завершению пода компонентом `kubelet` или через Eviction API.

**Основные артефакты для анализа:**
*   **`status.reason: Evicted`**: Индикатор того, что под был выселен, а не просто упал или был удален.
*   **`status.message`**: Контекстное пояснение (например, `The node was low on resource: memory`).
*   **`status.conditions` (`DisruptionTarget`)**: Детальная причина выселения в современных версиях Kubernetes (1.31+).
*   **Node Pressure Conditions**: Флаги состояния узла (`MemoryPressure`, `DiskPressure`, `PIDPressure`).

Общие понятия и типы выселения описаны в файле **[Pod Evicted: Определения](./definitions.md)**.

## Основные концепции

### Диагностическая матрица

Для эффективного траблшутинга необходимо сопоставлять данные из разных источников.

| Уровень | Инструмент | Искомая информация |
|:---|:---|:---|
| **API/Pod** | `kubectl describe pod` | Сообщения в `status.message`, события (Events), условия (Conditions). |
| **Node Status** | `kubectl describe node` | Состояния Pressure, Capacity vs Allocatable, Taints. |
| **Node Logs** | `journalctl -u kubelet` | Логи `eviction manager`, расчеты Working Set, запуск GC. |
| **Metrics** | `Prometheus/Grafana` | Тренды потребления ресурсов перед инцидентом. |
| **OS/Runtime** | `dmesg`, `crictl stats` | OOM Killer ядра, статус контейнеров в рантайме. |
| **Config** | `kubectl get -o yaml` | Настройки `KubeletConfiguration`, `kubeReserved`, `systemReserved`. |

### Алгоритм траблшутинга

1.  **Сбор первичных данных:** Идентификация всех выселенных подов и узлов, на которых они находились.
2.  **Классификация по `status.message`:** Разделение на выселения по памяти, диску, PID или через API (drain).
3.  **Анализ состояния узла (Pressure):** Если флаги Pressure установлены (`True`), значит узел стабильно перегружен. Если `False` — имел место кратковременный всплеск.
4.  **Проверка QoS и лимитов:** Определение класса QoS выселенного пода. В первую очередь выселяются `BestEffort` и `Burstable`, превысившие свои `requests`.
5.  **Корреляция с системными событиями:** Проверка `dmesg` на предмет OOM Killer (если выселение по памяти) или переполнения разделов ФС.
6.  **Верификация через метрики:** Анализ графиков потребления ресурсов за 15-30 минут до выселения.
7.  **Проверка настроек kubelet:** Анализ `evictionHard`, `evictionSoft`, `kubeReserved`, `systemReserved`, чтобы понять, почему пороги были достигнуты.
8.  **Проверка DisruptionTarget:** Использование условия `DisruptionTarget` (K8s 1.31+) для точного определения причины выселения.

### Связь Conditions, Taints и Events

При выселении формируется цепочка артефактов:

```
Eviction Manager обнаруживает Pressure
  → Узел помечается Condition (MemoryPressure/DiskPressure/PIDPressure)
  → Автоматически накладывается taint (NoSchedule)
  → Поду отправляется SIGTERM/SIGKILL
  → В поде появляется status.reason=Evicted
  → Генерируется Event (reason=Evicted)
  → В поде появляется Condition DisruptionTarget (K8s 1.31+)
```

Каждый из этих шагов можно проверить через `kubectl` или логи.

### Время жизни событий (Events)

События хранятся ограниченно:
*   **По умолчанию:** 1 час (可通过 `kube-apiserver --event-ttl` изменить).
*   **Критические события:** `Warning`-события могут быть потеряны, если не включен логирование в файл.
*   **Проверка настроек TTL:**
    ```bash
    # Проверка текущего TTL (если доступ к манифесту)
    grep -A1 "event-ttl" /etc/kubernetes/manifests/kube-apiserver.yaml
    # → --event-ttl=1h0m0s
    ```

### Кросс-доменная корреляция

Выселение может быть симптомом проблем в других доменах:

| Домен | Проблема | Симптом выселения |
|:---|:---|:---|
| **Networking** | Сетевой сбой, потеря связи с API | Узел помечен `NotReady`, taint `node.kubernetes.io/network-unavailable` |
| **Storage** | NFS/Ceph сбой, I/O stall | `DiskPressure`, диски не монтируются |
| **Container Runtime** | Сбой `containerd`/`CRI-O` | `PLEG is unhealthy`, поды не запускаются |
| **OS** | Критическая ошибка ядра | `dmesg` показывает kernel panic, OOM Killer |

## Практические сценарии

### 1. Первичный анализ через kubectl

```bash
# Получение списка выселенных подов с именами узлов и сообщениями
kubectl get pods -A --field-selector status.reason=Evicted -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,NODE:.spec.nodeName,MESSAGE:.status.message"

# Проверка условия DisruptionTarget (для K8s 1.31+)
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="DisruptionTarget")]}'
```

### 2. Анализ логов Kubelet на узле

Логи `kubelet` содержат детальную информацию о том, как `Eviction Manager` принимал решение.

```bash
# Поиск записей о начале выселения
journalctl -u kubelet -g "eviction manager: attempting to reclaim"

# Пример лога:
# eviction manager: attempting to reclaim memory
# eviction manager: unit of reclaim is nodes
# eviction manager: pod <pod_name> is evicted
```

**Дополнительные паттерны поиска в логах:**
```bash
# Проверка циклов вычисления давления ресурсов
journalctl -u kubelet | grep -E "eviction manager: (reclaim|attempting)"

# Поиск конкретного пода в логах выселения
journalctl -u kubelet | grep -A 5 "pod <pod-name>"

# Проверка запуска Garbage Collection перед выселением
journalctl -u kubelet | grep -E "container GC|image GC"
```

### 3. Диагностика через Prometheus (PromQL)

Метрики позволяют увидеть картину в динамике, когда события уже стерты.

*   **Поиск узлов с MemoryPressure:**
    ```promql
    kube_node_status_condition{condition="MemoryPressure", status="true"} == 1
    ```
*   **Топ подов, потребляющих больше запросов (Candidate for Eviction):**
    ```promql
    sum(container_memory_working_set_bytes) by (pod) - sum(kube_pod_container_resource_requests{resource="memory"}) by (pod) > 0
    ```
*   **Всплеск Disk Usage на nodefs:**
    ```promql
    node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"} < 0.1
    ```

**Дополнительные полезные запросы:**
```promql
# Узлы с DiskPressure
kube_node_status_condition{condition="DiskPressure", status="true"} == 1

# Узлы с PIDPressure
kube_node_status_condition{condition="PIDPressure", status="true"} == 1

# Прогноз исчерпания памяти на узле (на основе тренда за 6 часов)
predict_linear(node_memory_MemAvailable_bytes[6h], 3600 * 24) < 0

# Количество выселенных подов за последние 24 часа
increase(kube_pod_status_reason{reason="Evicted"}[24h])
```

### 4. Анализ причин через события (Events)

События — это основной способ понять хронологию. Помните, что по умолчанию они хранятся всего 1 час.

```bash
# Фильтрация событий выселения по всему кластеру
kubectl get events -A --field-selector reason=Evicted --sort-by='.lastTimestamp'
```

**Паттерны в событиях:**
*   `The node was low on resource: memory`: Выселение по памяти.
*   `The node was low on resource: ephemeral-storage`: Переполнение `emptyDir` или логов.
*   `Evicted by Eviction API`: Результат `kubectl drain`.
*   `Preempted by scheduler`: Вытеснение более приоритетным подом.

**Детальный анализ конкретного события:**
```bash
kubectl describe event <event-name> -n <namespace>
# Поля для анализа:
# - reason: Причина (Evicted, Scheduled, Pulled, etc.)
# - message: Детали (какой ресурс, сколько использовано)
# - firstTimestamp / lastTimestamp: Когда началось и закончилось
# - count: Сколько раз произошло
# - involvedObject.name: Какой ресурс затронут
```

### 5. Использование эфемерных контейнеров для отладки

Если узел в критическом состоянии, вы можете запустить отладочный контейнер с доступом к хостовой ФС.

```bash
kubectl debug node/<node-name> -it --image=busybox
# Внутри контейнера:
# chroot /host
# df -h  # Проверка дисков узла
# free -m # Проверка памяти узла
```

**Проверка cAdvisor метрик напрямую на узле:**
```bash
# После chroot /host
curl -sk https://localhost:10250/stats/summary | jq '.node.memory.availableBytes'
curl -sk https://localhost:10250/stats/summary | jq '.pods[].containers[].memory.usageBytes' | sort -rn | head
```

### 6. Диагностика через DisruptionTarget (K8s 1.31+)

Условие `DisruptionTarget` позволяет точно определить причину выселения:

```bash
# Проверка условия DisruptionTarget
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="DisruptionTarget")]}'
# → reason: EvictionByKubelet
# → message: Pod was evicted due to node pressure: MemoryPressure

# Проверка всех подов с DisruptionTarget за последние события
kubectl get pods -A -o json | jq -r '.items[] | select(.status.conditions[]? | select(.type=="DisruptionTarget")) | "\(.metadata.namespace)/\(.metadata.name): \(.status.conditions[] | select(.type=="DisruptionTarget") | .reason)"'
```

**Возможные значения `reason`:**
*   `EvictionByEvictionAPI` — выселен через `kubectl drain` или Descheduler.
*   `DeletionByTaintManager` — удален из-за Taint `NoExecute`.
*   `PreemptionByKubeScheduler` — вытеснен более приоритетным подом.
*   `EvictionByKubelet` — выселен из-за давления ресурсов (MemoryPressure, DiskPressure).

### 7. Проверка PDB перед обслуживанием

Перед `kubectl drain` убедитесь, что PDB не блокирует выселение:

```bash
# Просмотр всех PDB в кластере
kubectl get pdb -A

# Детали конкретного PDB
kubectl describe pdb <pdb-name> -n <namespace>

# Проверка, сколько подов можно выселить
kubectl get pdb <pdb-name> -o jsonpath='{.status.disruptionsAllowed}'
# → 1
```

**Анализ блокировки PDB:**
```bash
# Проверка, какие поды "блокируют" PDB
kubectl get pdb <pdb-name> -o jsonpath='{.status.currentHealthy}'
kubectl get pdb <pdb-name> -o jsonpath='{.status.desiredHealthy}'

# Если disruptionsAllowed = 0, проверьте:
# 1. Количество здоровых подов (currentHealthy) >= желаемого (desiredHealthy)
# 2. Есть ли поды в статусе Terminating, которые блокируют
# 3. Настроен ли unhealthyPodEvictionPolicy
```

### 8. Диагностика Taint-Based Eviction

Если узел перешел в `NotReady` и поды выселяются через taint `NoExecute`:

```bash
# Проверка taints на узле
kubectl describe node <node-name> | grep Taints
# → Taints: node.kubernetes.io/not-ready:NoExecute

# Проверка подов с tolerations для этого taint
kubectl get pods -A -o json | jq '.items[] | select(.spec.tolerations[]? | select(.key=="node.kubernetes.io/not-ready")) | .metadata.name'

# Проверка TolerationSeconds (сколько секунд ждать перед выселением)
kubectl get pods -A -o json | jq '.items[] | select(.spec.tolerations[]? | select(.key=="node.kubernetes.io/not-ready")) | {name: .metadata.name, tolerationSeconds: .spec.tolerations[] | select(.key=="node.kubernetes.io/not-ready") | .tolerationSeconds}'
```

### 9. Проверка настроек kubelet

Проверка текущих порогов выселения и резервирования:

```bash
# Через API kubelet (требуется аутентификация)
curl -sk https://<node-ip>:10250/configz | jq '.kubeletconfig.evictionHard'
curl -sk https://<node-ip>:10250/configz | jq '.kubeletconfig.kubeReserved'
curl -sk https://<node-ip>:10250/configz | jq '.kubeletconfig.systemReserved'

# Через манифест (если доступен)
cat /etc/kubernetes/manifests/kubelet.yaml | grep -A 20 "evictionHard"
```

**Типичные проблемы конфигурации:**
*   `evictionHard` слишком агрессивный (например, `memory.available<256Mi` на 128GB узле).
*   Отсутствие `kubeReserved` / `systemReserved` — нет резерва для системных процессов.
*   `evictionSoft` и `evictionSoftGracePeriod` слишком короткие — не дают времени на восстановление.

### 10. Анализ OOM Killer на узле

Если вы怀疑 что выселение вызвано OOM Killer (а не `kubelet`):

```bash
# Проверка dmesg на OOM
dmesg | grep -i "oom\|out of memory"

# Проверка логов ядра
journalctl -k | grep -i "oom\|out of memory"

# Проверка счетчиков OOM в /proc
cat /proc/vmstat | grep oom_kill
# → oom_kill 15
```

### 11. Диагностика через скрипт

Быстрый скрипт для сбора всех данных об инциденте:

```bash
#!/bin/bash
# save_incident.sh — Сбор данных об инциденте с выселением
# Использование: ./save_incident.sh <pod-name> <namespace>

POD=$1
NAMESPACE=$2
OUTPUT="incident_$(date +%Y%m%d_%H%M%S).txt"

echo "=== Incident Report ===" > $OUTPUT
echo "Pod: $POD" >> $OUTPUT
echo "Namespace: $NAMESPACE" >> $OUTPUT
echo "Date: $(date)" >> $OUTPUT

echo -e "\n=== Pod Status ===" >> $OUTPUT
kubectl get pod $POD -n $NAMESPACE -o yaml >> $OUTPUT

echo -e "\n=== Pod Describe ===" >> $OUTPUT
kubectl describe pod $POD -n $NAMESPACE >> $OUTPUT

echo -e "\n=== Node Conditions ===" >> $OUTPUT
NODE=$(kubectl get pod $POD -n $NAMESPACE -o jsonpath='{.spec.nodeName}')
kubectl describe node $NODE | grep -A 20 "Conditions:" >> $OUTPUT

echo -e "\n=== Node Taints ===" >> $OUTPUT
kubectl describe node $NODE | grep -A 5 "Taints:" >> $OUTPUT

echo -e "\n=== Events (Pod) ===" >> $OUTPUT
kubectl get events -n $NAMESPACE --field-selector involvedObject.name=$POD --sort-by='.lastTimestamp' >> $OUTPUT

echo -e "\n=== Events (Node) ===" >> $OUTPUT
kubectl get events --field-selector involvedObject.name=$NODE --sort-by='.lastTimestamp' >> $OUTPUT 2>/dev/null

echo -e "\n=== DisruptionTarget ===" >> $OUTPUT
kubectl get pod $POD -n $NAMESPACE -o jsonpath='{.status.conditions[?(@.type=="DisruptionTarget")]}' >> $OUTPUT

echo "Report saved to $OUTPUT"
```

## Устранение последствий

### Массовая очистка выселенных подов

Выселенные поды остаются в API в статусе `Failed`. Их нужно периодически удалять, чтобы не нагружать `kube-apiserver` и не замусоривать выдачу `kubectl`.

```bash
# Удаление всех выселенных подов во всех пространствах имен
kubectl delete pods --field-selector status.reason=Evicted -A
```

**Автоматизация:** Kubernetes имеет встроенный параметр `terminated-pod-gc-threshold` (в `kube-controller-manager`), который определяет, сколько завершенных подов хранить до начала автоматической очистки.

### Проверка количества выселенных подов

```bash
# Подсчет выселенных подов по namespace
kubectl get pods -A --field-selector status.reason=Evicted --no-headers | awk '{print $1}' | sort | uniq -c | sort -rn

# Результат:
#  15 default
#   8 kube-system
#   3 monitoring
```

## Дополнительная информация

### Диагностическая матрица ресурсов

| Ресурс | Что проверить на узле | Файл-руководство |
|:---|:---|:---|
| **Memory** | `WorkingSet`, `oom_score_adj` | **[Выселение по памяти](./memory_eviction.md)** |
| **Disk** | `/var/lib/kubelet`, `/var/lib/docker` | **[Выселение по диску](./disk_eviction.md)** |
| **PID** | `pids.current` в cgroups | **[Давление ресурсов](../NodeUnavailability/resource_pressure.md)** |
| **API** | `PodDisruptionBudget` | **[PDB и Taint Eviction](./pdb_and_taint_eviction.md)** |

### Типовые ошибки при диагностике

| Ошибка | Последствия | Решение |
|:---|:---|:---|
| Путаница Eviction и OOMKilled | Неправильный выбор стратегии исправления | Проверяйте `status.reason` и `status.message` |
| Игнорирование PDB при drain | `kubectl drain` зависает на часы | Проверяйте PDB перед обслуживанием |
| Отсутствие мониторинга Pressure | Проблемы обнаруживаются только после вылета сервисов | Настройте алерты в Prometheus |
| Неправильные requests/limits | Частые выселения или недоресурсирование | Используйте VPA для автоматической настройки |
| Потеря событий | Невозможно восстановить хронологию | Настройте `event-ttl` или централизованное логирование |
| Игнорирование kubeReserved | Системные процессы выселяются первыми | Всегда резервируйте память для `kubelet` и ОС |

### Смотрите также

- **[Pod Evicted: Определения](./definitions.md)** — база по типам выселений.
- **[Профилактика выселения](./prevention.md)** — как не допустить повторения.
- **[QoS и выселение](./qos_and_eviction.md)** — влияние лимитов на выбор жертвы.
