# Pod Evicted: Выселение по памяти (Memory Eviction)

## Определения

**MemoryPressure Eviction** — защитный механизм `kubelet`, который принудительно завершает поды при критической нехватке оперативной памяти на узле. В отличие от системного OOM Killer, выселение является предиктивным: `kubelet` убивает поды до того, как память закончится полностью, чтобы сохранить стабильность системных компонентов.

**Состояние узла MemoryPressure** — флаг в `status.conditions`, который переходит в `True`, когда доступная память узла падает ниже заданных порогов выселения. При этом на узел автоматически накладывается taint `node.kubernetes.io/memory-pressure:NoSchedule`, запрещающий планировщику назначать новые поды.

**Рабочий набор (Working Set Size, WSS)** — основная метрика памяти, используемая Kubernetes для принятия решения о выселении. Формула: `WSS = RSS + Active(anon) + Active(file) -Inactive(file)`. Kubernetes считает по WSS, а не по RSS, потому что неактивный файловый кэш может быть мгновенно сброшен ядром.

**PSI (Pressure Stall Information)** — механизм мониторинга узких мест (bottlenecks) ресурсов, доступный начиная с ядра Linux 4.20. В отличие от `memory.available` (мгновенный снимок), PSI измеряет **процент времени**, в течение которого процессы ожидали освобождения ресурса. Доступен в `/proc/pressure/memory` и в cgroups v2 (`memory.pressure`).

**cgroup v2 memory controller** — подсистема управления памятью в cgroups v2. Основные контролы:
*   `memory.max` — жесткий лимит (аналог `limits.memory` в Kubernetes).
*   `memory.high` — порог мягкого торможения (throttling). При превышении процесс замедляется, но не убивается.
*   `memory.min` — гарантированный минимум (не может быть отобран другими cgroups). Аналог `requests.memory`.
*   `memory.swap.max` — лимит swap для конкретного cgroup (аналог Kubelet `memorySwap.swapBehavior`).

**KubeReserved / SystemReserved** — резерв памяти для системных процессов, которые не являются подами:
*   `kubeReserved` — для компонентов Kubernetes (kubelet, container runtime, containerd/CRI-O).
*   `systemReserved` — для системных сервисов (sshd, journald, systemd, kernel threads).

Общие определения и типы выселения: **[Pod Evicted: Определения](./definitions.md)**.

## Основные концепции

### Расчет доступной памяти в kubelet

Kubelet не использует метрику `free` из вывода команды `free -h`. Вместо этого он рассчитывает доступную память на основе данных из `cgroups`, которые собирает агент `cAdvisor`.

**Формула расчета доступной памяти (Node-level):**
```
memory.available = node.capacity - node.workingSet
```

**Что входит в Working Set (WSS):**
1.  **RSS (Resident Set Size):** Анонимная память процесса (стек, куча).
2.  **Cache (Page Cache):** Данные файлов, прочитанные с диска.
3.  **Минус Inactive File:** Часть дискового кэша, которую ядро Linux помечает как "неактивную" и может мгновенно переиспользовать без ущерба для производительности.

**Формула WSS (из `/proc/meminfo`):**
```
WSS = MemTotal - MemAvailable
MemAvailable ≈ Free + Buffers + Cache - MinReclaimable
```

**Почему это важно:** Если приложение активно работает с файлами (например, база данных или лог-агрегатор), его `workingSet` будет расти за счет кэша. Если ядро не успевает вовремя сбрасывать неактивные страницы, `kubelet` может инициировать выселение, даже если анонимной памяти (RSS) достаточно.

**Различия в расчете между cgroup v1 и v2:**

| Контроллер | cgroup v1 | cgroup v2 | Что считает Kubelet |
|:---|:---|:---|:---|
| Лимит памяти | `memory.limit_in_bytes` | `memory.max` | WSS контейнера |
| Текущее использование | `memory.usage_in_bytes` | `memory.current` | Актуальное потребление |
| Статистика | `memory.stat` | `memory.stat` | inactive_file, active_file |
| Swap | `memory.memsw.limit_in_bytes` | `memory.swap.max` | Учитывается в WSS |

### PSI (Pressure Stall Information) — более точный мониторинг

Вместо использования порогов `memory.available` (мгновенный снимок), PSI измеряет **процент времени**, который процессы теряют из-за нехватки памяти.

**PSI файлы:**
*   `/proc/pressure/memory` — системный PSI (node-level)
*   `/sys/fs/cgroup/kubepods.slice/.../memory.pressure` — PSI для конкретного контейнера (cgroups v2)

**Формат вывода:**
```
some avg10=0.50 avg60=0.25 avg300=0.10 total=12345678
full avg10=0.00 avg60=0.00 avg300=0.00 total=0
```

| Метрика | Описание | Порог предупреждения | Порог критический |
|:---|:---|:---|:---|
| `some avg10` | Хочет память, но может подождать | > 5% | > 15% |
| `full avg10` | Полностью останавливается из-за нехватки | > 1% | > 5% |

**Преимущества PSI перед `memory.available`:**
*   PSI учитывает **время**, а не мгновенный объем.
*   Приложение может потреблять 99% памяти, но если оно не останавливается (no page faults), PSI будет низким.
*   Наоборот: WSS может быть в пределах лимита, но если频繁ный page fault, PSI покажет проблему.

**Пример мониторинга PSI:**
```bash
# Системный PSI
cat /proc/pressure/memory
# → some avg10=2.35 avg60=1.12 avg300=0.45 total=98765432

# PSI для контейнера (cgroup v2)
cat /sys/fs/cgroup/kubepods.slice/kubepods-pod<uid>.slice/memory.pressure
```

**Алерт PSI в Prometheus:**
```promql
# Предупреждение: процессы теряют время из-за нехватки памяти
node_memory_pressure_stall_info{resource="memory", state="some"} > 0.05

# Критическое: процессы полностью останавливаются
node_memory_pressure_stall_info{resource="memory", state="full"} > 0.01
```

### Пороги выселения (Thresholds)

Настройки задаются в `KubeletConfiguration` (`/var/lib/kubelet/config.yaml`):

| Параметр | Тип | Описание | Типичное значение |
|:---|:---|:---|:---|
| `evictionHard.memory.available` | Hard | Немедленное выселение (SIGKILL) | `100Mi` или `5%` |
| `evictionSoft.memory.available` | Soft | Выселение после grace period (SIGTERM) | `500Mi` |
| `evictionSoftGracePeriod` | Time | Время удержания порога до начала выселения | `2m` |
| `evictionMinimumReclaim` | Size | Минимальное количество для освобождения | `0` (Kubelet освободит ровно столько, сколько нужно) |

**Полный пример конфигурации:**
```yaml
# /var/lib/kubelet/config.yaml
evictionHard:
  memory.available: "100Mi"
evictionSoft:
  memory.available: "500Mi"
evictionSoftGracePeriod:
  memory.available: "2m"
evictionMinimumReclaim:
  memory.available: "200Mi"
kubeReserved:
  memory: "1Gi"
systemReserved:
  memory: "500Mi"
```

**Формула Allocatable:**
```
Allocatable = Capacity - kubeReserved - systemReserved - evictionHard
```
На узле с 32Gi RAM: `32Gi - 1Gi - 500Mi - 100Mi = 30.4Gi` доступно для подов.

**Рекомендация для больших узлов:** На узлах с 128ГБ+ RAM порог в 5% (6.4ГБ) может быть избыточным. Используйте абсолютные значения (например, `2Gi`).

### Влияние Swap на выселение

Поддержка Swap в Kubernetes стала **стабильной (GA) в версии 1.31** (ранее — alpha в 1.22, beta в 1.28).

**Требования:**
1.  cgroup v2 (обязательно).
2.  `failSwapOn: false` в `KubeletConfiguration`.
3.  `memorySwap.swapBehavior: LimitedSwap` (рекомендуется).

**Влияние на выселение:**
*   **Swap отключен:** При нехватке памяти `kubelet` сразу переходит к выселению или срабатывает OOM Killer.
*   **Swap включен (LimitedSwap):** Kubernetes ограничивает использование swap для каждого пода пропорционально его `limits.memory`. Система может выгружать неактивные страницы на диск, что дает "запас времени".
*   **Опасность:** Если swap заполнен, OOM Killer срабатывает так же быстро, как и при отключенном swap. Дополнительно: активный swap снижает производительность из-за медленного чтения с диска.

**Контроль swap в cgroup v2:**
```bash
# Проверка лимита swap для контейнера
cat /sys/fs/cgroup/kubepods.slice/kubepods-pod<uid>.slice/memory.swap.max
# → max (без ограничений) или числовое значение в байтах

# Проверка текущего использования swap
cat /sys/fs/cgroup/kubepods.slice/kubepods-pod<uid>.slice/memory.swap.current
# → 0 (swap не используется)
```

> Подробнее: **[Управление Swap](../../../../Linux/Core/memory/swap_management.md)**.

### Taints и планирование

При переходе узла в состояние `MemoryPressure=True` на него автоматически накладывается taint:
`node.kubernetes.io/memory-pressure:NoSchedule`
Это запрещает планировщику (`kube-scheduler`) назначать новые поды на этот узел, пока ситуация не стабилизируется.

**Восстановление после MemoryPressure:**
*   `kubelet` проверяет `memory.available` каждые 10 секунд.
*   Когда `memory.available` превышает `evictionHard` + гистерезис, флаг `MemoryPressure` снимается.
*   Taint автоматически удаляется.
*   Новые поды снова могут планироваться на узел.

**Важно:** Если `memory.available` осциллирует вокруг порога, узел будет постоянно получать и сбрасывать taint. Это называется "flip-flopping". Решение: увеличить `evictionSoftGracePeriod` или установить `evictionMinimumReclaim`.

## Практические сценарии

### 1. Диагностика через kubectl

Если под выселен с причиной `Evicted`, проверьте сообщение в его статусе:

```bash
kubectl describe pod <pod-name>
# Результат: Message: The node was low on resource: memory. 
# Container app was using 1500Mi, which is over its request of 1Gi.
```

**Важно в сообщении:**
*   `Container app was using 1500Mi` — фактическое потребление (WSS).
*   `over its request of 1Gi` — превышение запроса. Под был выселен, потому что превысил `requests`, а не `limits`.

Проверьте состояние узла:
```bash
kubectl get nodes -o custom-columns="NAME:.metadata.name,MEMORY_PRESSURE:.status.conditions[?(@.type=='MemoryPressure')].status"
```

Проверьте Taints:
```bash
kubectl describe node <node-name> | grep Taints
# → node.kubernetes.io/memory-pressure:NoSchedule
```

### 2. Анализ на узле через SSH

Если `kubectl top` не дает полной картины (метрики усреднены), используйте инструменты узла.

**Проверка через crictl (runtime):**
```bash
crictl stats
# Показывает MEM (WSS) для каждого контейнера в реальном времени
# → CONTAINER   CPU %   MEM   DISK
# → app         5%      1.2G  100M
```

**Просмотр Working Set конкретного контейнера (cgroup v2):**
```bash
# Путь к cgroup контейнера
CGROUP_PATH=$(cat /proc/<PID>/cgroup | grep "memory" | cut -d: -f3)
# Или найдите через crictl inspect
PID=$(crictl inspect <container-id> | jq -r .info.pid)

# Проверка WSS
cat /proc/<PID>/memory.current
# → 1572864000 (1.5Gi)

# Детализация по типам памяти
cat /proc/<PID>/memory.stat | grep -E "^(anon|file|inactive_file|active_file)"
# → anon 1073741824     (RSS: 1Gi)
# → file 524288000      (кэш: 500Mi)
# → inactive_file 209715200  (неактивный кэш: 200Mi)
# → active_file 314572800    (активный кэш: 300Mi)
# → WSS = 1073741824 + 314572800 - 209715200 ≈ 1.18Gi

# Проверка лимита
cat /proc/<PID>/memory.max
# → 2147483648 (2Gi)
```

**Просмотр Working Set (cgroup v1):**
```bash
# Путь к cgroup v1
CGROUP_PATH=/sys/fs/cgroup/memory/kubepods/pod<uid>/<container-id>

# Проверка WSS
cat ${CGROUP_PATH}/memory.usage_in_bytes
# → 1572864000

# Детализация
cat ${CGROUP_PATH}/memory.stat | grep -E "^(inactive_file|active_file)"
# → inactive_file 209715200
# → active_file 314572800
```

**Анализ PSI:**
```bash
# Системный PSI
cat /proc/pressure/memory
# → some avg10=2.35 avg60=1.12 avg300=0.45 total=98765432
# → full avg10=0.00 avg60=0.00 avg300=0.00 total=0

# PSI для контейнера (cgroup v2)
cat /sys/fs/cgroup/kubepods.slice/kubepods-pod<uid>.slice/memory.pressure
```

**Анализ oom_score_adj:**
```bash
# Проверка приоритета процесса
cat /proc/<PID>/oom_score_adj
# → -997 (Guaranteed) или 1000 (BestEffort)
```

Детали по QoS и oom_score_adj: **[QoS и выселение](./qos_and_eviction.md)**.

**Проверка dmesg на OOM Killer:**
```bash
dmesg -T | grep -iE "oom-killer|killed process" | tail -20
# → [Sep  2 12:34:56] Out of memory: Killed process 12345 (java) total-vm:4096000kB, anon-rss:2048000kB

# Проверка memcg OOM (cgroup)
dmesg -T | grep -i "oom-kill" | grep -i "constraint=CONSTRAINT_MEMCG"
# → memory: usage 2097152kB, limit 2097152kB, swap 0kB
```

### 3. Проверка настроек kubelet

```bash
# Проверка текущих порогов через API
curl -sk https://localhost:10250/configz | jq '.kubeletconfig.evictionHard'
# → {"memory.available":"100Mi"}

# Проверка Allocatable ресурсов
kubectl describe node <node-name> | grep -A 10 "Allocated resources"
# → memory: 32768Mi (reserved: 1536Mi, allocatable: 31232Mi)

# Проверка kubeReserved и systemReserved
curl -sk https://localhost:10250/configz | jq '.kubeletconfig.kubeReserved'
curl -sk https://localhost:10250/configz | jq '.kubeletconfig.systemReserved'
```

**Типичные ошибки конфигурации:**
*   `evictionHard.memory.available` слишком агрессивный (например, `20%` на 256ГБ узле = 51ГБ запаса).
*   Нет `kubeReserved` / `systemReserved` — нет резерва для системных процессов.
*   `requests.memory` пода значительно ниже реального потребления — поды переуплотняют узел.
*   `evictionSoft` и `evictionSoftGracePeriod` слишком короткие — не дают времени на восстановление.
*   Swap выключен на узлах с большими рабочими наборами — нет "буфера" для пиковых нагрузок.

### 4. Анализ логов kubelet при выселении

```bash
# Поиск записей о начале выселения
journalctl -u kubelet -g "eviction manager: attempting to reclaim"

# Пример лога:
# eviction manager: attempting to reclaim memory
# eviction manager: node stats: available 52428800 capacity 33554432000
# eviction manager: starved pods (before evictions): ...

# Проверка ранжирования подов (кого выберут для выселения)
journalctl -u kubelet -g "eviction manager: ranking pods"
# → eviction manager: pod <pod-name> is evicted because it exceeds its memory request

# Проверка запуска GC
journalctl -u kubelet | grep -E "container GC|image GC"

# Мониторинг циклов вычисления давления ресурсов
journalctl -u kubelet | grep -E "eviction manager: (reclaim|attempting)"
```

### 5. Скрипт сбора данных об инциденте

```bash
#!/bin/bash
# save_memory_incident.sh — Сбор данных об инциденте с MemoryPressure
# Использование: ./save_memory_incident.sh <node-name>

NODE=$1
OUTPUT="memory_incident_$(date +%Y%m%d_%H%M%S).txt"

echo "=== Memory Pressure Incident Report ===" > $OUTPUT
echo "Node: $NODE" >> $OUTPUT
echo "Date: $(date)" >> $OUTPUT

echo -e "\n=== Node Conditions ===" >> $OUTPUT
kubectl describe node $NODE | grep -A 20 "Conditions:" >> $OUTPUT

echo -e "\n=== Node Taints ===" >> $OUTPUT
kubectl describe node $NODE | grep -A 5 "Taints:" >> $OUTPUT

echo -e "\n=== Allocated Resources ===" >> $OUTPUT
kubectl describe node $NODE | grep -A 10 "Allocated resources" >> $OUTPUT

echo -e "\n=== Evicted Pods ===" >> $OUTPUT
kubectl get pods -A --field-selector spec.nodeName=$NODE,status.reason=Evicted -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,MESSAGE:.status.message" >> $OUTPUT

echo -e "\n=== Events (Eviction) ===" >> $OUTPUT
kubectl get events --field-selector reason=Evicted --sort-by='.lastTimestamp' >> $OUTPUT 2>/dev/null

echo -e "\n=== Top Pods by Memory ===" >> $OUTPUT
kubectl top pods -A --sort-by=memory 2>/dev/null >> $OUTPUT

echo -e "\n=== kubelet Eviction Config ===" >> $OUTPUT
curl -sk https://localhost:10250/configz 2>/dev/null | jq '.kubeletconfig.evictionHard' >> $OUTPUT

echo -e "\n=== PSI (Memory Pressure) ===" >> $OUTPUT
cat /proc/pressure/memory >> $OUTPUT 2>/dev/null

echo -e "\n=== dmesg OOM ===" >> $OUTPUT
dmesg -T 2>/dev/null | grep -iE "oom-killer|killed process" | tail -20 >> $OUTPUT

echo "Report saved to $OUTPUT"
```

### 6. Диагностика через DisruptionTarget (K8s 1.31+)

Условие `DisruptionTarget` позволяет точно определить причину выселения:

```bash
# Проверка условия DisruptionTarget
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="DisruptionTarget")]}'
# → reason: EvictionByKubelet
# → message: Pod was evicted due to node pressure: MemoryPressure

# Проверка всех подов с DisruptionTarget по MemoryPressure
kubectl get pods -A -o json | jq -r '.items[] | select(.status.conditions[]? | select(.type=="DisruptionTarget" and .reason=="EvictionByKubelet")) | "\(.metadata.namespace)/\(.metadata.name): \(.status.conditions[] | select(.type=="DisruptionTarget") | .message)"'
```

### 7. Кросс-доменная корреляция

MemoryPressure может быть симптомом проблем в других доменах:

| Домен | Проблема | Симптом MemoryPressure |
|:---|:---|:---|
| **Disk I/O** | Медленный диск, I/O stall | Буферов логов копятся в памяти, не могут быть сброшены на диск |
| **Networking** | Сбой агента сбора логов | Логи копятся в буфере, не передаются |
| **Container Runtime** | Сбой containerd/CRI-O | Контейнеры не завершаются, память не освобождается |
| **Application** | Утечка памяти | WSS контейнера растет, превышая limits |
| **Swap** | Заполнен swap | OOM Killer срабатывает так же быстро, как при отключенном swap |
| **Kernel** | Фрагментация памяти | Процессы не могут выделить contiguous pages |

**Проверка корреляции:**
```bash
# Если MemoryPressure + DiskPressure одновременно — проблема с I/O
# Если MemoryPressure + высокий PSI — утечка памяти
# Если MemoryPressure + swap заполнен — swap death spiral
```

## Дополнительная информация

### Различия между MemoryPressure и OOMKilled

| Характеристика | MemoryPressure (Eviction) | OOMKilled |
|:---|:---|:---|
| **Инициатор** | `kubelet` (превентивно) | Ядро Linux (вынужденно) |
| **Сигнал** | SIGTERM (Soft) или SIGKILL (Hard) | SIGKILL |
| **Логика** | Предиктивная (запас на узле) | Реактивная (лимит контейнера превышен) |
| **Статус** | `Reason: Evicted` | `Reason: OOMKilled` |
| **Уровень** | Весь под целиком | Конкретный контейнер |
| **Grace Period** | `terminationGracePeriodSeconds` (Soft) или нет (Hard) | Нет |
| **Метрика** | `memory.available` на узле | `memory.current` в cgroup контейнера |
| **Taint** | `node.kubernetes.io/memory-pressure:NoSchedule` | Нет |
| **Восстановление** | Автоматическое (если память освободилась) | Рестарт контейнера (RestartPolicy) |

### Типичные ошибки при диагностике

| Ошибка | Последствия | Решение |
|:---|:---|:---|
| Путаница WSS и RSS | Неправильная оценка потребления | Используйте `memory.stat` для расчета WSS |
| Использование `free -h` вместо кgroup | Ложное ощущение достатка | Kubelet считает по cgroup, а не по системе |
| Нет `kubeReserved` / `systemReserved` | Systemd, containerd конкурируют с подами за память | Всегда резервируйте 1-2Gi |
| Swap выключен без альтернатив | Нет "буфера" для пиковых нагрузок | Включите Swap (K8s 1.31 GA) или увеличьте `evictionHard` |
| Игнорирование PSI | Незаметные проблемы с производительностью | Мониторьте PSI параллельно с WSS |
| Слишком частое flip-flopping | Uptime деградирует из-за постоянного перепланирования | Увеличьте `evictionSoftGracePeriod` |
| Нет мониторинга | Проблемы обнаруживаются только после вылета сервисов | Настройте алерты в Prometheus |

### Мониторинг (PromQL)

```promql
# Узлы в состоянии MemoryPressure
kube_node_status_condition{condition="MemoryPressure", status="true"} == 1

# Потребление памяти конкретным подом
container_memory_working_set_bytes{container!=""}

# Процент использования памяти подом относительно лимита
container_memory_working_set_bytes / container_spec_memory_limit_bytes * 100

# Прогноз исчерпания памяти на узле (на основе тренда за 6 часов)
predict_linear(node_memory_MemAvailable_bytes[6h], 3600 * 24) < 0

# Количество OOMKilled подов за 24 часа
increase(kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}[24h])

# Топ подов по потреблению памяти
topk(10, container_memory_working_set_bytes{container!=""})

# PSI: время, потерянное из-за нехватки памяти
node_memory_pressure_stall_info{resource="memory", state="some"} > 0.05
```

**Алерты Prometheus:**
```yaml
# Предупреждение: под приближается к лимиту памяти
- alert: PodMemoryNearLimit
  expr: container_memory_working_set_bytes / container_spec_memory_limit_bytes > 0.9
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Под {{ $labels.pod }} использует >90% лимита памяти"

# Предупреждение: узел близок к MemoryPressure
- alert: NodeMemoryPressure
  expr: kube_node_status_condition{condition="MemoryPressure", status="true"} == 1
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Узел {{ $labels.node }} в состоянии MemoryPressure"

# Критическое: узел критически перегружен
- alert: NodeMemoryCritical
  expr: (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 > 90
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Узел {{ $labels.instance }}: использовано >90% RAM"

# Мониторинг PSI
- alert: MemoryPressureStall
  expr: rate(node_memory_pressure_stall_info{resource="memory", state="full"}[5m]) > 0.01
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Процессы теряют время из-за нехватки памяти (PSI > 1%)"

# Мониторинг OOMKilled
- alert: PodOOMKilled
  expr: increase(kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}[1h]) > 0
  labels:
    severity: warning
  annotations:
    summary: "Под {{ $labels.pod }} завершился с OOMKilled"
```

### Смотрите также

- **[Pod Evicted: Определения](./definitions.md)** — база по типам выселений.
- **[QoS и выселение](./qos_and_eviction.md)** — влияние классов на приоритеты.
- **[Диагностика выселения](./diagnostics.md)** — общий алгоритм поиска первопричин.
- **[Профилактика выселения](./prevention.md)** — как избежать MemoryPressure.
- **[Разбор ошибки OOMKilled](../oomkilled_pods.md)** — когда лимиты превышены.
- **[Метрики памяти процесса](../../../../Linux/Core/memory/process_memory_metrics.md)** — RSS, WSS, PSS.
- **[Управление Swap](../../../../Linux/Core/memory/swap_management.md)** — настройка swap в Linux и Kubernetes.
- **[PSI (Pressure Stall Information)](../../../../Linux/Core/kernel/psi.md)** — мониторинг узких мест ресурсов.
- **[OOM Killer в контейнерах](../../../../Linux/Core/processes/oom_killer_containers.md)** — как работает OOM в контейнерной среде.
