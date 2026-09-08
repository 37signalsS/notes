# Pod в состоянии `Pending`: Продвинутые темы

## Предварительные требования

Для понимания этого раздела необходимы:
*   Базовое понимание архитектуры `kube-scheduler` (см. [Kube-scheduler — архитектура](../../../Concepts/kube_scheduler.md)).
*   Знакомство с базовой диагностикой Pending (см. [Диагностика](./diagnostics.md)).
*   Kubernetes v1.28+ (для большинства описанных механизмов; конкретные версии указаны в тексте).

---

## Определения

**Продвинутая диагностика Pending** — глубокий анализ взаимодействия механизмов планирования, мониторинг состояния очереди планировщика и исследование специфических ограничений (Scheduling Gates, DRA, Topology Spread, Gang Scheduling), блокирующих запуск подов в сложных или высоконагруженных инфраструктурных условиях.

**Scheduling Gates (врата планирования)** — механизм (GA v1.30), позволяющий удерживать под в состоянии `Pending` (статус `SchedulingGated`) до завершения внешних проверек (безопасность, квоты, подготовка данных). Планировщик полностью игнорирует такие поды, что снижает нагрузку на Control Plane.

**Queuing Hints** — оптимизация планировщика (Beta v1.32), позволяющая плагинам указывать, при каких именно изменениях в кластере (например, освобождение конкретного ресурса) стоит повторно пытаться запланировать под из очереди `Unschedulable`. Снижает количество лишних попыток планирования.

**Dynamic Resource Allocation (DRA)** — API для управления специализированными ресурсами (GPU, FPGA, NVMe) через `ResourceClaims` (Beta v1.32), заменяющее Device Plugins и позволяющее планировщику учитывать параметры ресурсов в структурированном виде.

**Gang Scheduling (Групповое планирование)** — паттерн, при котором группа подов планируется одновременно: либо все поды группы получают узлы, либо ни один. Используется для HPC/ML-задач, где поды должны работать совместно.

**Asynchronous Preemption (Асинхронное вытеснение)** — механизм (Beta v1.33), при котором удаление жертв выполняется асинхронно после назначения высокоприоритетного пода, ускоряя процесс планирования.

---

## Базовые концепции

### 1. Жизненный цикл планирования (Scheduling Framework)

Если под застрял в `Pending`, важно определить, на какой точке расширения (Extension Point) происходит задержка. Scheduling Framework определяет 9 точек расширения:

```
Pod Created
     │
     ▼
Queue (очередь)
     │
     ▼
PreFilter → Filter → PostFilter → Reserve → Permit → PreBind → Bind → PostBind
     │         │         │          │         │        │         │
     └─────────┴─────────┴──────────┴─────────┴────────┴─────────┘
                    (если все прошли успешно)
```

#### PreFilter
Предварительная проверка пода. Плагины могут отклонить под до начала фильтрации узлов.
*   **Пример:** `NodeResourcesFit` проверяет, что под требует корректные значения ресурсов.
*   **Диагностика:** Если под отклоняется на этом этапе, в событиях будет `PreFilter failed`.

#### Filter (Predicates)
Последовательная проверка жестких ограничений для каждого узла:
*   `NodeResourcesFit` — наличие CPU/RAM/ephemeral-storage/Ports
*   `TaintToleration` — соответствие допускам
*   `NodeAffinity` — проверка `requiredDuringSchedulingIgnoredDuringExecution`
*   `VolumeRestrictions` — доступность PV в конкретной зоне (Zonal Availability)
*   `PodTopologySpread` — выполнение ограничений распределения
*   `InterPodAffinity` — совместимость с другими Pod
*   `NodeUnschedulable` — не помечен ли узел как `cordon`
*   `VolumeBinding` — доступность PVC/PV в зоне

**Ключевой момент:** Если ни один узел не прошел фильтрацию, планировщик переходит к PostFilter.

#### PostFilter (Preemption)
Запускается только если ни один узел не прошел Filter. Здесь реализуется логика **вытеснения (preemption)**:
1. Поиск кандидатов на вытеснение (поды с более низким приоритетом)
2. Проверка PDB (PodDisruptionBudget) — по умолчанию preemption **игнорирует PDB**
3. Удаление жертв и назначение узла для нового пода

**Asynchronous Preemption (v1.33+):** С включенным feature gate `SchedulerAsyncPreemption` удаление жертв происходит асинхронно после Bind, что ускоряет назначение.

#### Reserve
Резервирование ресурсов в памяти планировщика до записи в etcd. Предотвращает Race Condition, когда два планировщика отдают один и тот же остаток ресурсов разным подам.

**Важно:** Если под отклоняется на этом этапе (например, через Permit), ресурсы освобождаются автоматически.

#### Permit
Этап одобрения/отклонения пода перед привязкой к узлу. Под может находиться в трех состояниях:
*   **Approve** — под одобрен, переход к PreBind
*   **Deny** — под отклонен, возврат в очередь
*   **Wait** — под ожидает одобрения от внешнего плагина

**Применение:** Gang Scheduling — все поды группы должны получить Permit, иначе ни один не привязывается.

#### PreBind
Выполнение операций перед привязкой (например, монтирование сетевых ресурсов, проверка доступности внешних систем).

#### Bind
Присвоение узла поду (установка `spec.nodeName`). После этого kubelet на целевом узле начинает запуск контейнеров.

#### PostBind
Уведомление о завершении планирования. Используется для метрик и аудита.

### 2. Scheduling Gates: глубокий анализ

Scheduling Gates (GA v1.30) позволяют удерживать Pod в Pending до тех пор, пока внешний контроллер не разрешит планирование. В отличие от `readinessGates` (которые влияют на готовность), Scheduling Gates блокируют сам процесс размещения Pod на узле.

**Как это работает:**
1. Pod создается с заполненным `.spec.schedulingGates`
2. Планировщик проверяет gates в очереди `gated` (не в `active`)
3. Внешний контроллер (Gatekeeper, Kyverno, кастомный) удаляет gates
4. Pod перемещается в очередь `active` и планируется нормально

**Диагностика зависших gates:**
```bash
# Проверка наличия gates
kubectl get pod <pod-name> -o jsonpath='{.spec.schedulingGates}'

# Проверка статуса PodScheduled
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="PodScheduled")]}'
# → {"type":"PodScheduled","status":"False","reason":"SchedulingGated",...}

# Все поды с gates в кластере
kubectl get pods -A -o json | jq '.items[] | select(.spec.schedulingGates != null) | {name: .metadata.name, ns: .metadata.namespace, gates: .spec.schedulingGates}'

# Проверка, какой контроллер управляет gates (по ownerReferences)
kubectl get pod <pod-name> -o json | jq '.metadata.ownerReferences[]'
```

**Типичные сценарии:**
*   Gatekeeper — ожидание прохождения admission policy
*   Kyverno — ожидание валидации ресурсов
*   Кастомный провижинер данных — ожидание создания PVC/Secret
*   Queue-proxy (Anthos) — ожидание регистрации в очереди

**Если gate не удаляется более 30-60 секунд:** проблема в внешнем контроллере. Проверьте его логи и состояние.

### 3. Queuing Hints: оптимизация повторных попыток

Queuing Hints (Beta v1.32) позволяют плагинам указывать, при каких изменениях в кластере стоит повторно планировать под. Без этого механизма планировщик повторяет попытки для каждого изменения в кластере, что неэффективно.

**Пример без Queuing Hints:**
```
Pod в очереди backoff
→ Изменилась нагрузка на узел A → повторная попытка (пустая)
→ Добавился новый узел B → повторная попытка (пустая)
→ Удалился Pod с узла C → повторная попытка (пустая)
```

**С Queuing Hints:**
```
Pod в очереди backoff
→ Pod планировался на узел A, но не хватило CPU
→ Queuing Hint: "планировать только когда освободился CPU на узле A"
→ Изменилась нагрузка на узел B → пропуск (не релевантно)
→ Удалился Pod с узла A (освободился CPU) → повторная попытка
```

**Включение:**
```yaml
apiVersion: kubescheduler.config.k8s.io/v1
kind: KubeSchedulerConfiguration
profiles:
- schedulerName: default-scheduler
  pluginConfig:
  - name: QueueingHint
    args:
      enabled: true
```

**Метрики:**
```bash
# Проверка эффективности Queuing Hints
kubectl get --raw /metrics | grep scheduler_queue_incoming_pods_total
# → scheduler_queue_incoming_pods_total{event="add",queue="active"} 150
# → scheduler_queue_incoming_pods_total{event="update",queue="backoff"} 12
```

### 4. Dynamic Resource Allocation (DRA)

DRA (Beta v1.32) заменяет Device Plugins для управления специализированными ресурсами. В отличие от Device Plugins, DRA позволяет динамически выделять ресурсы на уровне всего пода с использованием `ResourceClaims`.

**Архитектура DRA:**
```
Pod с resourceClaims
     │
     ▼
kube-scheduler (DRA plugin)
     │
     ▼
ResourceClaim Controller
     │
     ▼
DRA Driver (node)
     │
     ▼
Аппаратный ресурс (GPU, FPGA, NVMe)
```

**Ключевые объекты:**
*   **ResourceClass** — определяет параметры ресурса (драйвер, параметры,権限)
*   **ResourceClaim** — запрос на выделение ресурса (создается контроллером или вручную)
*   **ResourceClaimTemplate** — шаблон для создания ResourceClaims подами

**Диагностика DRA:**
```bash
# Проверка ResourceClaims
kubectl get resourceclaims -n <namespace>
# → NAME              STATE          AGE
# → my-gpu-claim      allocated      5m

# Проверка ResourceClasses
kubectl get resourceclasses
# → NAME                 DRIVER           AGE
# → nvidia-gpu           nvidia.com/gpu   10d

# Детальный статус ResourceClaim
kubectl describe resourceclaim <claim-name> -n <namespace>
# → Status:
# →   Driver: nvidia.com/gpu
# →   Allocation:
# →     DeviceIDs: [GPU-12345]
# →     NodeName: gpu-node-1

# Проверка DRA-драйвера
kubectl get pods -n kube-system -l app=nvidia-dra-driver
# → NAME                                READY   STATUS    RESTARTS   AGE
# → nvidia-dra-driver-xxx               1/1     Running   0          10d

# Проверка ошибок DRA
kubectl get events --field-selector reason=ProvisioningFailed
```

**Типичные ошибки DRA:**
*   `ResourceClaimPending` — DRA-драйвер не может выделить ресурс (все устройства заняты)
*   `AllocationFailed` — драйвер не найден или не готов
*   `NodeNotReady` — узел не готов к DRA (нужен feature gate `DynamicResourceAllocation`)

### 5. Gang Scheduling: групповое планирование

Gang Scheduling решает проблему, когда группа подов должна быть запланирована одновременно. Без этого механизма поды могут быть распределены по разным узлам, что критично для HPC/ML-задач.

**Как это работает:**
1. Все поды группы создают `ResourceClaim` или используют общий `ResourceClaimTemplate`
2. Плагин `Permit` устанавливает состояние `Wait` для каждого пода
3. Когда все поды группы получили `ResourceClaim`, `Permit` выдает `Approve`
4. Все поды одновременно переходят к `Bind`

**Пример конфигурации:**
```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: gang-scheduling
value: 1000000
preemptionPolicy: PreemptLowerPriority
---
apiVersion: v1
kind: Pod
metadata:
  name: ml-worker-0
spec:
  priorityClassName: gang-scheduling
  schedulerName: default-scheduler
  containers:
  - name: worker
    resources:
      claims:
      - name: gpu-claim
        resourceClaimName: ml-gpu-claim
```

**Диагностика:**
```bash
# Проверка подов в состоянии Wait
kubectl get pods -o json | jq '.items[] | select(.status.conditions[]? | select(.type=="PodScheduled" and .reason=="Waiting"))'

# Проверка ResourceClaims
kubectl get resourceclaims -o json | jq '.items[] | {name: .metadata.name, state: .status.state}'
```

### 6. MatchLabelKeys: предотвращение deadlocks при Rolling Update

MatchLabelKeys (Beta v1.31 для Affinity, v1.27+ для Topology Spread) предотвращает тупиковые ситуации при Rolling Update. Позволяет новым подам учитывать распределение только своей версии, игнорируя старые поды, которые скоро будут удалены.

**Проблема без MatchLabelKeys:**
```
Deployment: 5 реплик, maxSkew=1
Текущее состояние: v1 (3 пода), v2 (1 под)
→ v2 не может запланироваться: skew=2 (3-1=2 > maxSkew=1)
→ Rolling Update зависает
```

**Решение с MatchLabelKeys:**
```yaml
topologySpreadConstraints:
- maxSkew: 1
  topologyKey: topology.kubernetes.io/zone
  whenUnsatisfiable: DoNotSchedule
  matchLabelKeys:
  - pod-template-hash  # Игнорирует поды с другим hash
```

**Диагностика deadlock:**
```bash
# Проверка событий
kubectl describe pod <pod-name> | grep "FailedScheduling"
# → 0/5 nodes are available: 2 didn't match topology spread constraints

# Проверка распределения по зонам
kubectl get pods -l app=my-app -o custom-columns=NAME:.metadata.name,NODE:.spec.nodeName,ZONE:.metadata.labels.topology\.kubernetes\.io/zone
```

### 7. Topology Spread: продвинутые паттерны

**Минимальные домены (minDomains):**
```yaml
topologySpreadConstraints:
- maxSkew: 1
  topologyKey: topology.kubernetes.io/zone
  minDomains: 3  # Требуется минимум 3 зоны
  whenUnsatisfiable: DoNotSchedule
```
Если в кластере менее 3 зон, под останется в Pending.

**Расширение неудовлетворенных (Unsatisfiable):**
```yaml
topologySpreadConstraints:
- maxSkew: 1
  topologyKey: topology.kubernetes.io/zone
  whenUnsatisfiable: ScheduleAnyway  # Планировать даже с нарушением
```
С `ScheduleAnyway` планировщик добавляет баллы узлам, улучшающим равномерность, но не блокирует планирование.

**Взаимодействие с Cluster Autoscaler:**
CA учитывает `topologySpreadConstraints` при масштабировании. Если требуются узлы в конкретной зоне, CA добавляет их с учетом constraints.

### 8. Взаимодействие с Cluster Autoscaler и PDB

**PDB и Preemption:**
По умолчанию preemption **игнорирует PDB**. Это может привести к неожиданной потере доступности. С Kubernetes 1.21+ настраивается через feature gate `PreferNominatedNodeWithPDB`:
```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-priority
value: 1000000
preemptionPolicy: PreemptLowerPriority  # По умолчанию
# preemptionPolicy: Never  # Запретить preemption
```

**Региональные лимиты:**
CA может пытаться добавить узлы, но получать отказ от провайдера:
```bash
# Проверка логов CA
kubectl logs -n kube-system -l app=cluster-autoscaler | grep -i "quota\|limit\|error"
# → W0115 10:35:00.123456 1 autoscaler.go:456] Failed to increase group size: quota exceeded

# Проверка лимитов группы узлов
kubectl get nodegroup -o json | jq '.items[] | {name: .metadata.name, min: .spec.minSize, max: .spec.maxSize}'
```

**Unexpandable Node Groups:**
CA помечает группы узлов как не подлежащие расширению при повторяющихся ошибках API. Восстановление автоматическое через 15 минут.

### 9. Специфические сценарии планирования

#### Кастомный планировщик (Custom Scheduler)
Если под использует нестандартный планировщик, стандартный `kube-scheduler` его игнорирует:
```bash
# Проверка имени планировщика пода
kubectl get pod <pod-name> -o jsonpath='{.spec.schedulerName}'
# → custom-scheduler

# Проверка доступных планировщиков
kubectl get pods -n kube-system -l component=kube-scheduler
# → NAME                             READY   STATUS    RESTARTS   AGE
# → kube-scheduler-master            1/1     Running   0          10d
# → custom-scheduler                  1/1     Running   0          5d
```

**Если под ссылается на несуществующий `schedulerName`:** планировщик не обработает его, и под останется в `Pending` без событий ошибок.

#### Scheduler Extender
Кастомные планировщики могут быть реализованы через Scheduler Extender — HTTP-сервис, вызываемый стандартным `kube-scheduler` на этапах Filter, Prioritize, Bind:
```yaml
# KubeSchedulerConfiguration
apiVersion: kubescheduler.config.k8s.io/v1
kind: KubeSchedulerConfiguration
extenders:
- urlPrefix: http://custom-scheduler:8080
  filterVerb: filter
  prioritizeVerb: prioritize
  bindVerb: bind
```

### 10. Мониторинг и метрики планировщика

**Ключевые метрики Prometheus:**
```bash
# Размер очереди планировщика
scheduler_pending_pods{queue="active"}    # Готовы к планированию
scheduler_pending_pods{queue="backoff"}   # Ожидают повтора после неудачи
scheduler_pending_pods{queue="gated"}     # Заблокированы Scheduling Gates

# Длительность фаз планирования
scheduler_scheduling_algorithm_duration_seconds  # Общая длительность
scheduler_binding_duration_seconds              # Длительность Bind

# Количество попыток
scheduler_binding_attempts_total               # Попытки Bind
scheduler_preemption_attempts_total            # Попытки preemption
scheduler_preemption_victims_total             # Жертвы preemption
```

**Анализ "flapping":**
Если `queue="backoff"` велика, это признак "flapping" конфигурации — под подходит по ресурсам, но отклоняется на этапе Binding/Permit.

**Профилирование планировщика:**
```bash
# Включение профилирования (порт 10259)
kubectl get --raw /debug/pprof/heap > scheduler-heap.pprof
go tool pprof scheduler-heap.pprof

# Проверка длинных операций
kubectl get --raw /metrics | grep scheduler_scheduling_algorithm_duration_seconds_bucket
```

---

## Практические сценарии

### 1. Анализ Scheduling Gates

Если под имеет статус `SchedulingGated`, проверьте список ворот:
```bash
# Проверка наличия gates
kubectl get pod <pod-name> -o jsonpath='{.spec.schedulingGates}'
# → [{"gateName":"example.com/data-ready"}]

# Проверка статуса PodScheduled
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="PodScheduled")]}'
# → {"type":"PodScheduled","status":"False","reason":"SchedulingGated",...}

# Все поды с gates в кластере
kubectl get pods -A -o json | jq '.items[] | select(.spec.schedulingGates != null) | {name: .metadata.name, ns: .metadata.namespace, gates: .spec.schedulingGates}'

# Проверка ownerReferences (какой контроллер управляет pod)
kubectl get pod <pod-name> -o json | jq '.metadata.ownerReferences[]'
```

**Диагностика:** Если список не пуст более 30-60 секунд, ищите сбой в контроллере, ответственном за эти ворота. Типичные причины:
*   Gatekeeper — проверьте `kubectl get constrainttemplates` и логи gatekeeper-audit
*   Kyverno — проверьте `kubectl get clusterpolicies` и логи kyverno
*   Кастомный контроллер — проверьте его логи и состояние

### 2. Диагностика тупиков в Topology Spread

При использовании `maxSkew` и Rolling Update новые поды могут не находить места из-за старых версий:
```bash
# Проверка событий планировщика
kubectl describe pod <pod-name> | grep "FailedScheduling"
# → 0/5 nodes are available: 2 didn't match topology spread constraints

# Проверка распределения по зонам
kubectl get pods -l app=my-app -o custom-columns=NAME:.metadata.name,NODE:.spec.nodeName,ZONE:.metadata.labels.topology\.kubernetes\.io/zone

# Проверка текущего skew
kubectl get pods -l app=my-app -o json | jq '[.items[] | .metadata.labels["topology.kubernetes.io/zone"]] | group_by(.) | map({zone: .[0], count: length})'
```

**Решения:**
1. Внедрите `matchLabelKeys` (v1.31+), чтобы планировщик игнорировал поды старого ReplicaSet
2. Используйте `whenUnsatisfiable: ScheduleAnyway` вместо `DoNotSchedule`
3. Увеличьте `maxSkew` (например, с 1 до 2)
4. Уменьшите количество реплик в Deployment

### 3. Мониторинг очередей планировщика

Используйте метрики для понимания состояния подов в очереди:
```bash
# Проверка размера очереди
kubectl get --raw /metrics | grep scheduler_pending_pods
# → scheduler_pending_pods{queue="active"} 3
# → scheduler_pending_pods{queue="backoff"} 1
# → scheduler_pending_pods{queue="gated"} 2

# Проверка длительности планирования
kubectl get --raw /metrics | grep scheduler_scheduling_algorithm_duration_seconds
# → scheduler_scheduling_algorithm_duration_seconds_bucket{le="0.001"} 150
# → scheduler_scheduling_algorithm_duration_seconds_bucket{le="0.01"} 200

# Проверка preemption
kubectl get --raw /metrics | grep scheduler_preemption_attempts_total
# → scheduler_preemption_attempts_total 5
```

**Анализ:**
*   `active > 0` длительное время — планировщик перегружен или есть системные проблемы
*   `backoff > 0` — Pod多次 не прошёл фильтрацию и повторяет попытки (flapping)
*   `gated > 0` — Pod заблокированы Scheduling Gates
*   Длительность `scheduling_algorithm > 1s` — планировщик перегружен, проверьте количество подов и узлов

### 4. Отладка DRA

Если под требует спец-ресурсов через DRA:
```bash
# Проверка состояния требований ресурсов
kubectl get resourceclaims -n <namespace>
# → NAME              STATE          AGE
# → my-gpu-claim      allocated      5m

# Проверка ResourceClasses
kubectl get resourceclasses
# → NAME                 DRIVER           AGE
# → nvidia-gpu           nvidia.com/gpu   10d

# Детальный статус ResourceClaim
kubectl describe resourceclaim <claim-name> -n <namespace>
# → Status:
# →   Driver: nvidia.com/gpu
# →   Allocation:
# →     DeviceIDs: [GPU-12345]
# →     NodeName: gpu-node-1

# Проверка DRA-драйвера
kubectl get pods -n kube-system -l app=nvidia-dra-driver
# → NAME                                READY   STATUS    RESTARTS   AGE
# → nvidia-dra-driver-xxx               1/1     Running   0          10d

# Проверка ошибок DRA
kubectl get events --field-selector reason=ProvisioningFailed
# → Warning  ProvisioningFailed  2m  nvidia-dra-driver  Failed to allocate GPU: all GPUs busy
```

**Симптомы:**
*   `ResourceClaim` в состоянии `Pending` — DRA-драйвер не может выделить ресурс (все устройства заняты)
*   `AllocationFailed` — драйвер не найден или не готов
*   `NodeNotReady` — узел не готов к DRA (нужен feature gate `DynamicResourceAllocation`)

### 5. Диагностика Gang Scheduling

Если поды группы зависли в `Pending`:
```bash
# Проверка подов в состоянии Wait
kubectl get pods -o json | jq '.items[] | select(.status.conditions[]? | select(.type=="PodScheduled" and .reason=="Waiting"))'
# → {"name":"ml-worker-0","status":"Waiting","message":"waiting for Permit from plugin gang-scheduling"}

# Проверка ResourceClaims
kubectl get resourceclaims -o json | jq '.items[] | {name: .metadata.name, state: .status.state}'
# → {"name":"ml-gpu-claim","state":"pending"}

# Проверка подов с общей PriorityQueue
kubectl get pods -l app=ml-worker -o custom-columns=NAME:.metadata.name,PRIORITY:.spec.priority,STATUS:.status.phase
# → NAME           PRIORITY   STATUS
# → ml-worker-0    1000000    Pending
# → ml-worker-1    1000000    Pending
```

**Причины зависания:**
*   Один из подов группы не может получить ресурс (все GPU заняты)
*   Один из подов группы отклонен на Filter (например, из-за taint)
*   Конфликт с PDB (если используется preemption)

### 6. Diagnosing MatchLabelKeys Deadlock

Проверка deadlock при Rolling Update:
```bash
# Проверка распределения подов по версиям
kubectl get pods -l app=my-app -o json | jq '.items[] | {name: .metadata.name, hash: .metadata.labels["pod-template-hash"], node: .spec.nodeName}'
# → {"name":"my-app-v1-abc","hash":"abc123","node":"node-1"}
# → {"name":"my-app-v1-def","hash":"abc123","node":"node-2"}
# → {"name":"my-app-v2-xyz","hash":"xyz789","node":"node-1"}

# Проверка событий
kubectl describe pod my-app-v2-xyz | grep "FailedScheduling"
# → 0/5 nodes are available: 3 didn't match topology spread constraints
```

**Решение:** Добавьте `matchLabelKeys` в `topologySpreadConstraints`:
```yaml
topologySpreadConstraints:
- maxSkew: 1
  topologyKey: topology.kubernetes.io/zone
  whenUnsatisfiable: DoNotSchedule
  matchLabelKeys:
  - pod-template-hash
```

---

## Лучшие практики

### Профилактика продвинутых проблем

1.  **Scheduling Gates:** Используйте только при необходимости внешней проверки. Избегайте длинных цепочек gates (>3 шагов).
2.  **DRA:** Настройте `ResourceClass` с правильными `parametersRef` и убедитесь, что DRA-драйвер готов к работе.
3.  **Gang Scheduling:** Для ML/HPC-задач используйте `PriorityClass` с высоким значением и `preemptionPolicy: PreemptLowerPriority`.
4.  **Topology Spread:** Всегда используйте `matchLabelKeys` для Deployments с Rolling Update.
5.  **Queuing Hints:** Включайте в кластерах с >1000 подов для снижения нагрузки на планировщик.

### Быстрое восстановление

1.  **Scheduling Gates зависли:** Удалите под и пересоздайте без gates (для отладки).
2.  **DRA-ресурс недоступен:** Временно измените `ResourceClass` на менее требовательный.
3.  **Gang Scheduling deadlock:** Уменьшите количество подов в группе или увеличьте `maxSkew`.
4.  **Topology Spread deadlock:** Используйте `whenUnsatisfiable: ScheduleAnyway` временно.

---

## Граничные случаи и известные ограничения

1.  **Scheduling Gates + CA:** CA не учитывает gates при масштабировании. Под может остаться в Pending даже после добавления узла.
2.  **DRA + CA:** CA учитывает DRA-ресурсы при симуляции, но не может выделить их без DRA-драйвера на новом узле.
3.  **Gang Scheduling + PDB:** PDB может блокировать удаление жертв preemption, даже если все поды группы ждут.
4.  **MatchLabelKeys + StatefulSet:** MatchLabelKeys не работает с StatefulSet (уникальные имена подов).
5.  **Queuing Hints + Custom Scheduler:** Кастомные планировщики не поддерживают Queuing Hints.
6.  **Asynchronous Preemption:** Включение `SchedulerAsyncPreemption` может увеличить использование памяти планировщика.
7.  **Topology Spread + minDomains:** Если в кластере менее `minDomains` физических зон, под останется в Pending навсегда.
8.  **DRA + KinD:** DRA-драйверы не работают в KinD (нет реального оборудования).

---

## Полезные команды для мониторинга

| Задача | Команда |
| :--- | :--- |
| **Размер очереди планировщика** | `kubectl get --raw /metrics \| grep scheduler_pending_pods` |
| **Длительность планирования** | `kubectl get --raw /metrics \| grep scheduler_scheduling_algorithm_duration_seconds` |
| **Количество preemption** | `kubectl get --raw /metrics \| grep scheduler_preemption_attempts_total` |
| **ResourceClaims** | `kubectl get resourceclaims -A` |
| **ResourceClasses** | `kubectl get resourceclasses` |
| **Поды с Gang Scheduling** | `kubectl get pods -o json \| jq '.items[] \| select(.spec.priorityClassName=="gang-scheduling")'` |
| **Поды с MatchLabelKeys** | `kubectl get pods -l app=my-app -o json \| jq '.items[] \| {name: .metadata.name, hash: .metadata.labels["pod-template-hash"]}'` |
| **Состояние DRA-драйвера** | `kubectl get pods -n kube-system -l app=nvidia-dra-driver` |
| **События планирования** | `kubectl get events --field-selector involvedObject.kind=Pod --sort-by='.lastTimestamp'` |
| **Логи планировщика** | `kubectl logs -n kube-system -l component=kube-scheduler` |
| **Проверка feature gates** | `kubectl get --raw /metrics \| grep kubernetes_feature_enabled` |

---

## Дополнительная информация

### Рекомендуемые практики

| Технология | Совет по использованию |
| :--- | :--- |
| **PriorityClass** | Используйте `preemptionPolicy: PreemptLowerPriority` только для критических сервисов. |
| **Queuing Hints** | Включайте feature gate (v1.32+), если в кластере много долгоживущих Pending подов. |
| **Wait For First Consumer** | Всегда используйте этот режим для зональных дисков, чтобы избежать `Pending` из-за Zonal Mismatch. |
| **DRA** | Настройте `ResourceClass` с правильными параметрами и убедитесь, что драйвер готов к работе. |
| **Gang Scheduling** | Используйте для ML/HPC-задач с высоким приоритетом и `preemptionPolicy: PreemptLowerPriority`. |
| **Topology Spread** | Всегда добавляйте `matchLabelKeys` для Deployments с Rolling Update. |

### Связанные ресурсы

*   **[Диагностика](./diagnostics.md)** — базовый алгоритм поиска неисправностей.
*   **[Kube-scheduler — архитектура](../../../Concepts/kube_scheduler.md)** — детали Scheduling Framework и плагинов.
*   **[PriorityClass — приоритеты подов](../../../Concepts/priorityclass.md)** — очереди и механизмы вытеснения.
*   **[Cluster Autoscaler — детальный обзор](../../Autoscaling/cluster_autoscaler_detailed.md)** — логика Scale-Up/Down.
*   **[Dynamic Resource Allocation (v1.32)](../../../Concepts/resource_management/dra_overview.md)** — управление GPU и ускорителями.
