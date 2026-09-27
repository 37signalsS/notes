# Pod в состоянии `Pending`: Диагностика и алгоритмы поиска

## Предварительные требования

Для эффективной диагностики необходимы:
*   **kubectl** — клиент командной строки, совместимый с версией кластера (рекомендуется последняя стабильная версия).
*   **Доступ к API-серверу** — права на выполнение `kubectl describe`, `kubectl get events`, `kubectl logs` в целевом Namespace.
*   **SSH-доступ к узлам** (опционально) — для проверки состояния kubelet, логов container runtime и сетевых интерфейсов.
*   **Мониторинг** (опционально) — доступ к Prometheus/Grafana для проверки метрик `scheduler_pending_pods`, `kube_pod_status_phase`.

---

## Определения

**Диагностика Pending-статуса** — системный процесс выявления факторов, препятствующих переходу Pod в фазу `Running`. В Kubernetes диагностика разделяется на два критических этапа:
1.  **Диагностика планирования (Unscheduled):** анализ причин, по которым `kube-scheduler` не может назначить Pod на узел (отсутствие `spec.nodeName`).
2.  **Диагностика запуска (Scheduled):** поиск причин задержки на конкретном узле после назначения (например, подготовка окружения, томов или выполнение Init-контейнеров).

---

## Базовые концепции

### Архитектура планирования в Kubernetes

Понимание внутреннего устройства `kube-scheduler` критично для эффективной диагностики. Планировщик работает как конвейер (pipeline) из последовательных фаз:

```
Pod Created → Queue → Filtering → Scoring → Binding → Node Assignment
```

**Фазы планирования:**

1. **Очередь (Queue):** Pod попадает в очередь планировщика. На этом этапе проверяются `schedulingGates` — если врата открыты, Pod остаётся в очереди.

2. **Фильт링 (Filtering):** Планировщик отсеивает неподходящие узлы. Каждый фильтр проверяет одно условие:
   - `NodeResourcesFit` — достаточно ли CPU/RAM/ephemeral-storage
   - `NodeAffinity` — соответствует ли `nodeSelector`/`nodeAffinity`
   - `TaintToleration` — есть ли `toleration` для всех `taint` узла
   - `PodTopologySpread` — не нарушены ли constraints
   - `InterPodAffinity` — совместим ли с другими Pod
   - `VolumeBinding` — доступен ли том в данной зоне
   - `NodeUnschedulable` — не помечен ли узел как `cordon`

3. **Скоринг (Scoring):** Каждый оставшийся узел получает балл по критериям:
   - `LeastRequestedPriority` — приоритет узлам с наименьшей загрузкой
   - `MostRequestedPriority` — для bin-packing (упаковка на минимальное число узлов)
   - `BalancedResourceAllocation` — баланс CPU/RAM
   - `InterPodAffinity` — соответствие предпочтениям

4. **Привязка (Binding):** Планировщик обновляет Pod, устанавливая `spec.nodeName`. После этого kubelet на целевом узле начинает запуск контейнеров.

**Ключевые метрики для мониторинга:**

```bash
# Размер очереди планировщика
kubectl get --raw /metrics | grep scheduler_pending_pods
# → scheduler_pending_pods{queue="active"} 3
# → scheduler_pending_pods{queue="backoff"} 1

# Длительность цикла планирования
kubectl get --raw /metrics | grep scheduler_scheduling_algorithm_duration_seconds

# Количество попыток фильтрации
kubectl get --raw /metrics | grep scheduler_filtering_duration_seconds
```

**Почему это важно для диагностики:**
- Если `active queue > 0` длительное время — планировщик перегружен или есть системные проблемы
- Если `backoff queue > 0` — Pod多次 не прошёл фильтрацию и повторяет попытки
- Отсутствие событий `FailedScheduling` при Pending Pod может означать, что Pod застрял на этапе `schedulingGates`

### Диагностическая матрица (SOP)

| Симптом | Основной источник | Вероятная причина |
| :--- | :--- | :--- |
| **Node: <none>** | `kubectl describe pod` | Дефицит ресурсов, Taints, Affinity, Resource Quotas |
| **Events: FailedScheduling** | `kubectl get events` | Планировщик не нашел подходящий узел |
| **Events: FailedMount** | `kubectl describe pod` | Проблемы с PVC, доступностью дисков или лимитами аттача |
| **Init:0/1** | `kubectl logs -c <init>` | Ошибка в логике Init-контейнера или ожидание зависимости |
| **SchedulingGates: [...]** | `kubectl get pod -o yaml` | Под удерживается внешним контроллером (v1.30+) |
| **No Events & Node: <none>** | `kubectl describe quota` | Исчерпана квота ресурсов в Namespace |
| **PodScheduled: False** | `kubectl get pod -o yaml` | Под не прошел этап планирования (.constraints[?(@.type=="PodScheduled")]) |
| **PodReadyToStartContainers: False** | `kubectl get pod -o yaml` | Sandbox или CNI не готов (v1.29+) |
| **Node: node-X, Conditions: MemoryPressure** | `kubectl describe node` | Узел исчерпал оперативную память |
| **Node: node-X, Conditions: DiskPressure** | `kubectl describe node` | Узел исчерпал дисковое пространство |
| **Node: node-X, Conditions: PIDPressure** | `kubectl describe node` | Узел исчерпал лимит процессов |

### Алгоритм диагностики (Flowchart)

```
Pod в Pending
     │
     ▼
kubectl describe pod → Node: <none>?
     │
     ├── ДА ──► Планирование (Unscheduled)
     │              │
     │              ▼
     │         Events содержат FailedScheduling?
     │              │
     │              ├── ДА ──► Анализ сообщения:
     │              │          • "Insufficient cpu/memory" → дефицит ресурсов
     │              │          • "had taint" → нет tolerations
     │              │          • "didn't match" → affinity/selector
     │              │          • "volume ... not found" → PVC/PV
     │              │
     │              └── НЕТ ──► Проверить schedulingGates
     │                         │
     │                         ├── Gates есть → внешний контроллер блокирует
     │                         └── Gates нет → проверить ResourceQuota
     │
     └── НЕТ (узел назначен) ──► Запуск на узле (Scheduled)
                                    │
                                    ▼
                               PodReadyToStartContainers?
                                    │
                                    ├── False ──► Sandbox/CNI проблемы
                                    │
                                    └── True ──► Проверить InitContainers
                                                 │
                                                 ├── Не завершены → логи init
                                                 └── Завершены → проверить Volume/Node Pressure
```

### Современный инструментарий (2025-2026)

*   **K8sGPT:** Автоматизированная диагностика с использованием LLM. Команда `k8sgpt analyze --explain` позволяет мгновенно получить интерпретацию сложных ошибок планирования.
*   **eBPF (Cilium/Hubble):** Позволяет выявить проблемы сетевой связности на этапе `ContainerCreating`, если CNI не может выделить IP-адрес.
*   **Ephemeral Containers:** Использование `kubectl debug` для инспекции состояния узла или томов "рядом" с зависшим подом.
*   **kube-scheduler metrics:** Метрики Prometheus `scheduler_pending_pods` и `scheduler_scheduling_algorithm_duration_seconds` для мониторинга состояния очередей планировщика.
*   **Node Problem Detector (NPD):** Автоматическое обнаружение проблем на узле (DiskPressure, MemoryPressure, CorruptDockerOverlay2) и генерация соответствующих Conditions.

---

## Алгоритм поиска неисправности

Для эффективной диагностики следуйте пошаговому протоколу:

1.  **Локализация этапа:**
    *   Если `Node: <none>` — исследуйте **Вектор 1 (Планирование)**.
    *   Если узел назначен — исследуйте **Вектор 2 (Запуск на узле)**.
2.  **Анализ событий (Events):** Выполните `kubectl describe pod <имя>`. Это приоритетный источник. Обратите внимание на сообщения `FailedScheduling`, так как они содержат точный отчет планировщика (например, `3 Insufficient cpu`).
3.  **Проверка условий (Conditions):** В выводе `describe` проверьте статус `PodScheduled`. Если он `False`, причина в планировщике.
4.  **Анализ зависимостей:** Проверьте состояние PVC (`kubectl get pvc`), Secret и ConfigMap, которые монтируются в Pod.

### Быстрый старт: 5-минутная диагностика

```bash
# 1. Найти все Pending поды
kubectl get pods -A --field-selector status.phase=Pending
# → NAME                    READY   STATUS    RESTARTS   AGE
# → my-app-6d4f5b8c9-x7k2m 0/1     Pending   0          5m

# 2. Определить этап (назначен ли узел)
kubectl get pod <pod-name> -o jsonpath='{.spec.nodeName}'
# → (пусто = Unscheduled, имя узла = Scheduled)

# 3. Получить событие планирования
kubectl describe pod <pod-name> | grep -A 5 "Events:"
# → Events:
# →   Type     Reason            Age   From               Message
# →   ----     ------            ----   ----               -------
# →   Warning  FailedScheduling  2m    default-scheduler  0/5 nodes are available: 2 Insufficient cpu, 3 had taint {node-role.kubernetes.io/control-plane: }.
```

---

## Практические сценарии

### Вектор 1: Ошибки на этапе планирования (Unscheduled)

#### 1. Дефицит ресурсов и квоты
Проверьте, достаточно ли ресурсов в кластере и не превышены ли лимиты пространства имен.
```bash
# Просмотр аллокации ресурсов на узлах
kubectl describe nodes | grep -A 5 "Allocated resources"
# → Allocated resources:
# →   Limits
# →     cpu:     4
# →     memory:  8Gi
# →   Requests
# →     cpu:     2
# →     memory:  4Gi

# Проверка Resource Quotas в Namespace
kubectl describe quota -n <namespace>
# → Name:                   my-quota
# → Resource                Used  Hard
# → --------                ----  ----
# → requests.cpu            1500m 2
# → requests.memory         2Gi   4Gi
# → pods                    8     10

# Проверка LimitRange в Namespace
kubectl get limitrange -n <namespace> -o yaml
# → apiVersion: v1
# → items:
# → - apiVersion: v1
# →   kind: LimitRange
# →   spec:
# →     limits:
# →     - default:
# →         cpu: "500m"
# →         memory: "256Mi"
# →       defaultRequest:
# →         cpu: "100m"
# →         memory: "128Mi"
# →       type: Container
```
*Белое пятно:* Если ресурсов на узлах достаточно, но под Pending — часто виновата именно `ResourceQuota`, блокирующая создание новых ресурсов сверх лимита. Проверяйте `kubectl describe quota -n <namespace>` — поле `Used` покажет текущее потребление.

#### 2. Ограничения размещения (Affinity/Taints/Conditions)
Убедитесь, что правила `nodeSelector`, `nodeAffinity` или `podAntiAffinity` физически выполнимы, а узлы не находятся в состоянии Pressure.
```bash
# Проверка Taints на узлах (блокирующие метки)
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
# → NAME     TAINTS
# → node-1   <none>
# → node-2   node-role.kubernetes.io/control-plane:NoSchedule
# → node-3   spot-instance=true:NoSchedule

# Проверка меток узлов (для nodeSelector)
kubectl get nodes --show-labels
# → NAME     LABELS
# → node-1   kubernetes.io/os=linux,beta.kubernetes.io/instance-type=t3.medium,...

# Проверка условий узлов (MemoryPressure, DiskPressure, PIDPressure)
kubectl get nodes -o custom-columns=NAME:.metadata.name,CONDITIONS:.status.conditions[*].type
# → NAME     CONDITIONS
# → node-1   Ready,MemoryPressure=False,DiskPressure=False,PIDPressure=False,...
# → node-2   Ready,MemoryPressure=True,DiskPressure=False,PIDPressure=False,...

# Детальная проверка Taints с effect
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, taints: .spec.taints}'
# → {
# →   "name": "node-3",
# →   "taints": [
# →     {
# →       "key": "spot-instance",
# →       "value": "true",
# →       "effect": "NoSchedule"
# →     }
# →   ]
# → }
```
*Нюанс:* Если все узлы имеют `MemoryPressure`, планировщик не назначит на них новые поды. Это защитный механизм Kubernetes — предотвращение OOM-kill критических компонентов.

#### 3. Приоритеты и вытеснение (Priority & Preemption)
Под может быть в Pending, если его приоритет ниже, чем у других подов, и в кластере нет места.
```bash
# Проверка PriorityClass пода
kubectl get pod <pod-name> -o jsonpath='{.spec.priorityClassName}'
# → system-cluster-critical

# Просмотр всех PriorityClass в кластере
kubectl get priorityclass
# → NAME                      VALUE   AGE   GLOBAL-DEFAULT
# → system-cluster-critical   1000000 10d   false
# → system-node-critical      2000000 10d   false
# → default                   1000000 10d   true

# Проверка значений приоритета
kubectl get pod <pod-name> -o jsonpath='{.spec.priority}'
# → 1000000

# Поиск подов с высоким приоритетом, которые могут блокировать
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.name}{" prio="}{.spec.priority}{"\n"}{end}' --field-selector=status.phase=Pending
# → high-priority-app prio=2000000
# → low-priority-app prio=100000
```
Если под ожидает вытеснения других, в событиях появится `PreemptionVictims`. Планировщик попытается удалить низкоприоритетные поды, но PDB (PodDisruptionBudget) может блокировать их удаление.

#### 4. Врата планирования (Scheduling Gates)
Новая механика (v1.30+ GA) для удержания подов.
```bash
# Проверка наличия врат
kubectl get pod <pod-name> -o jsonpath='{.spec.schedulingGates}'
# → [{"gateName":"example.com/data-ready"}]

# Проверка статуса SchedulingGated
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="PodScheduled")]}'
# → {"type":"PodScheduled","status":"False","lastTransitionTime":"2025-01-15T10:30:00Z","reason":"SchedulingGated","message":"Scheduling Gates blocked scheduling"}

# Просмотр всех подов с SchedulingGates в кластере
kubectl get pods -A -o json | jq '.items[] | select(.spec.schedulingGates != null) | {name: .metadata.name, gates: .spec.schedulingGates}'
# → {
# →   "name": "my-app-pending",
# →   "gates": [
# →     {
# →       "gateName": "gatekeeper.azure.com/audit"
# →     }
# →   ]
# → }
```
Если поле заполнено, планировщик игнорирует под, пока внешний контроллер не удалит врата. Типичные причины: ожидание проверки безопасности (Gatekeeper, Kyverno), подготовка данных, проверка квот.

---

### Вектор 2: Ошибки после назначения узла (Scheduled)

#### 1. Инициализация и Sidecars
Под остается в `Pending`, пока не завершатся все `InitContainers` и не станут Ready все `SidecarContainers` (native).
```bash
# Логи зависшего Init-контейнера
kubectl logs <pod-name> -c <init-container-name>
# → Error: connection refused to database at postgres:5432

# Проверка статуса Init-контейнеров
kubectl get pod <pod-name> -o jsonpath='{.status.initContainerStatuses[*]}'
# → [{"name":"init-db","state":{"waiting":{"reason":"CrashLoopBackOff","message":"..."},"ready":false,"started":false},...}]

# Проверка статуса нативных сайдкаров (v1.29+)
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[?(@.name=="<sidecar-name>")].ready}'
# → false

# Проверка логов завершенного init-контейнера (если crash)
kubectl logs <pod-name> -c <init-container-name> --previous
# → предыдущие логи (если контейнер перезапускался)
```
*Важно:* Если init-контейнер завершился с ошибкой, под будет перезапускаться бесконечно. Проверяйте `kubectl describe pod` → `State: Waiting → Reason: CrashLoopBackOff`.

#### 2. Проблемы с томами (Volume Mounting)
Самая частая причина "зависания" после назначения узла.
```bash
# Проверка событий на предмет FailedMount или FailedAttachVolume
kubectl describe pod <pod-name> | grep -E "MountVolume|AttachVolume"
# → Warning  FailedMount  30s  kubelet  MountVolume.SetUp failed for volume "pvc-data" : ...
# → Warning  FailedAttachVolume  2m  AttachDetachController  AttachVolume.Attach failed for volume "pvc-data" ...

# Проверка PVC
kubectl get pvc -n <namespace>
# → NAME          STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# → data-pvc      Bound    pvc-a1b2c3d4-e5f6-7890-abcd-ef1234567890   10Gi       RWO            local-path     5m
# → logs-pvc      Pending                                         0                          standard       2m

# Проверка статуса PVC (детально)
kubectl describe pvc <pvc-name> -n <namespace>
# → Events:
# →   Type    Reason                 Age   From                         Message
# →   ----    ------                 ----   ----                         -------
# →   Normal  WaitForFirstConsumer   2m    persistentvolume-controller  waiting for a volume to be created...

# Проверка доступных PV
kubectl get pv
# → NAME                                       CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   CLAIM                  STORAGECLASS   AGE
# → pvc-a1b2c3d4-e5f6-7890-abcd-ef1234567890   10Gi       RWO            Delete           Bound    default/data-pvc      local-path     5m

# Проверка StorageClass и volumeBindingMode
kubectl get storageclass
# → NAME                   PROVISIONER                    RECLAIMPOLICY   VOLUMEBINDINGMODE   ALLOWVOLUMEEXPANSION   AGE
# → local-path             rancher.io/local-path         Delete          WaitForFirstConsumer true                    10d
# → standard (default)     kubernetes.io/no-provisioner  Delete          Immediate           false                   10d
```
*Нюанс:* Если используется `volumeBindingMode: WaitForFirstConsumer`, PVC будет в Pending до момента успешного планирования пода. Это может создать тупик, если под требует определенную зону, а том доступен в другой.

#### 3. Подготовка Sandbox и CNI
Если `kubelet` не может создать сетевой стек:
```bash
# Проверка условий готовности сетевой среды
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="PodReadyToStartContainers")]}'
# → {"type":"PodReadyToStartContainers","status":"False","lastTransitionTime":"2025-01-15T10:35:00Z","reason":"SandboxNotReady","message":"CreatePodSandbox failed..."}

# Проверка событий CNI
kubectl describe pod <pod-name> | grep -i "cni\|network\|sandbox"
# → Warning  FailedCreatePodSandBox  1m   kubelet  Failed to create pod sandbox: ... cni plugin not initialized

# Проверка PodIP и NetworkReady
kubectl get pod <pod-name> -o jsonpath='{.status.podIP}'
# → (пусто если CNI не готов)

# Проверка готовности сети через Conditions
kubectl get pod <pod-name> -o jsonpath='{range .status.conditions[*]}{.type}={.status}{"\n"}{end}'
# → PodScheduled=True
# → Initialized=True
# → Ready=False
# → ContainersReady=False
# → PodReadyToStartContainers=False
```
*Типичные причины:* CNI-плагин не установлен (Calico, Cilium, Flannel), конфликт версий CNI, ошибки в конфигурации PodNetwork, недоступность API CNI-плагина.

#### 4. Давление на узел (Node Pressure)
Под назначен на узел, но kubelet не может запустить контейнеры из-за нехватки ресурсов на узле.
```bash
# Проверка Conditions узла
kubectl describe node <node-name> | grep -A 10 "Conditions:"
# → Conditions:
# →   Type             Status  LastHeartbeatTime                 LastTransitionTime                Reason                       Message
# →   ----             ------  -----------------                 ------------------                ------                       -------
# →   MemoryPressure   True    Wed, 15 Jan 2025 10:40:00 UTC    Wed, 15 Jan 2025 10:35:00 UTC    KubeletHasMemoryPressure     kubelet has memory pressure
# →   DiskPressure     False   Wed, 15 Jan 2025 10:40:00 UTC    Wed, 15 Jan 2025 10:30:00 UTC    KubeletHasDiskPressure       kubelet has no disk pressure

# Проверка Allocated resources на узле
kubectl describe node <node-name> | grep -A 15 "Allocated resources"
# → Allocated resources:
# →   Limits
# →     cpu:     8
# →     memory:  16Gi
# →   Requests
# →     cpu:     6
# →     memory:  12Gi

# Проверка доступных ресурсов
kubectl describe node <node-name> | grep -A 5 "Allocatable"
# → Allocatable:
# →   cpu:                8
# →   memory:             16Gi
# →   ephemeral-storage:  100Gi

# Проверка логов kubelet (если доступен SSH)
ssh <node-name> "journalctl -u kubelet --since '10 minutes ago' | grep -i 'pressure\|evict\|oom'"
# → Jan 15 10:35:00 node-1 kubelet[1234]: Attempting to reclaim ephemeral-storage
# → Jan 15 10:36:00 node-1 kubelet[1234]: Attempting to garbage collect required containers
```
*Механизм:* При `MemoryPressure` kubelet начинает вытеснять поды класса `BestEffort` (с наименьшим приоритетом). Если все поды `Burstable`/`Guaranteed`, вытеснение не происходит, и новые поды остаются в `Pending`.

#### 5. Логи kubelet и container runtime
Если под назначен на узел, но не запускается — проверьте логи kubelet и container runtime.
```bash
# Проверка логов kubelet (последние 50 строк)
ssh <node-name> "journalctl -u kubelet --no-pager -n 50"
# → Jan 15 10:35:00 node-1 kubelet[1234]: E0115 10:35:00.123456 1234 pod_workers.go:190] Error syncing pod...
# → Jan 15 10:35:01 node-1 kubelet[1234]: W0115 10:35:01.234567 1234 image_gc.go:252] Failed to GC image...

# Проверка containerd/cri-o
ssh <node-name> "crictl ps -a | grep <pod-name>"
# → CONTAINER ID   IMAGE          CREATED        STATE    NAME     ATTEMPT    POD ID
# → abc123def456   nginx:1.21     2 minutes ago  Running  nginx    0          pod-id-xyz

# Проверка состояния sandbox
ssh <node-name> "crictl pods | grep <pod-name>"
# → POD ID        NAMESPACE      NAME                STATE    CREATED
# → pod-id-xyz    default        my-app-pod-name     NotReady 2 minutes ago

# Проверка логов containerd
ssh <node-name> "journalctl -u containerd --since '10 minutes ago' | grep -i 'error\|fail'"
# → Jan 15 10:35:00 node-1 containerd[567]: level=error msg="failed to pull image..."
```
*Важно:* Логи kubelet доступны только через SSH на узел. Если узел managed (EKS, GKE, AKS), используйте `kubectl debug node/<node-name>` для доступа к логам.

#### 6. Кастомный планировщик (Custom Scheduler)
Если под использует нестандартный планировщик, стандартный `kube-scheduler` его игнорирует.
```bash
# Проверка имени планировщика пода
kubectl get pod <pod-name> -o jsonpath='{.spec.schedulerName}'
# → default-scheduler

# Проверка доступных планировщиков
kubectl get pods -n kube-system -l component=kube-scheduler
# → NAME                             READY   STATUS    RESTARTS   AGE
# → kube-scheduler-master            1/1     Running   0          10d
# → kube-scheduler-custom            1/1     Running   0          5d

# Проверка кастомного планировщика (если используется)
kubectl get deployment -n kube-system -l component=kube-scheduler
# → NAME                     READY   UP-TO-DATE   AVAILABLE   AGE
# → kube-scheduler            1/1     1            1           10d
# → custom-scheduler          1/1     1            1           5d
```
*Нюанс:* Если под ссылается на несуществующий `schedulerName`, планировщик не обработает его, и под останется в `Pending` без событий ошибок.

---

## Взаимодействие с Cluster Autoscaler

Cluster Autoscaler (CA) инициирует масштабирование вверх только при наличии `Pending` подов с причиной `Unschedulable`. Процесс может блокироваться:

```bash
# Проверка метрик CA
kubectl get --raw /metrics | grep cluster_autoscaler_unschedulable_pods_count
# → cluster_autoscaler_unschedulable_pods_count 3

# Проверка статуса CA
kubectl get deployment -n kube-system cluster-autoscaler
# → NAME                 READY   UP-TO-DATE   AVAILABLE   AGE
# → cluster-autoscaler   1/1     1            1           10d

# Проверка логов CA
kubectl logs -n kube-system -l app=cluster-autoscaler --tail=50
# → I0115 10:35:00.123456 1 autoscaler.go:234] Scale-up: group "my-node-group" size 3→5
# → W0115 10:36:00.234567 1 autoscaler.go:456] Failed to increase group size: ...

# Проверка лимитов группы узлов
kubectl get nodegroup -o json | jq '.items[] | {name: .metadata.name, min: .spec.minSize, max: .spec.maxSize}'
# → (в managed-кластерах EKS/GKE/AKS)
```

**Типичные блокировки CA:**
*   **PDB (Pod Disruption Budget):** Если для размещения нового пода требуется вытеснение старых, а PDB блокирует их удаление, новый под останется в `Pending`.
*   **Региональные лимиты:** CA может пытаться добавить узлы, но получать отказ от провайдера (исчерпан лимит на GPU в регионе).
*   **Unexpandable Node Groups:** CA помечает группы узлов как не подлежащие расширению при повторяющихся ошибках API.

---

## DaemonSet: специфические особенности Pending

DaemonSet автоматически создает поды на каждом узле. Типичные причины Pending для DaemonSet:

```bash
# Проверка статуса DaemonSet
kubectl get daemonset -n <namespace>
# → NAME         DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR   AGE
# → my-agent     3         3         2       3            2           <none>          10d

# Проверка, почему поды не на всех узлах
kubectl describe daemonset <ds-name> | grep -A 5 "Conditions"
# → Conditions:
# →   Type           Status  Reason
# →   ----           ------  ------
# →   Available      2/3     NotEnoughNodes

# Проверка тайтсов на узлах (DaemonSet автоматически добавляет tolerations)
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, taints: [.spec.taints[]? | select(.effect == "NoSchedule") | .key]}'
# → {"name": "node-3", "taints": ["spot-instance"]}

# Проверка, какие узлы игнорируются DaemonSet
kubectl get pods -n <namespace> -l app=my-agent -o custom-columns=NAME:.metadata.name,NODE:.spec.nodeName,STATUS:.status.phase
# → NAME           NODE     STATUS
# → my-agent-abc   node-1   Running
# → my-agent-def   node-2   Running
# → (нет пода на node-3 из-за taint)
```

**Особенности:**
*   DaemonSet автоматически добавляет `toleration` для `node.kubernetes.io/unschedulable:NoSchedule` (при `kubectl cordon`).
*   Если узел имеет `taint` без соответствующего `toleration`, под DaemonSet не будет создан на этом узле.
*   При нехватке ресурсов на узле (MemoryPressure, DiskPressure) kubelet не запустит контейнеры DaemonSet.

---

## Специфические сценарии

### RuntimeClass и Pod Overhead

`RuntimeClass` определяет контейнерный runtime для Pod. Каждый runtime может иметь `overhead` — дополнительные ресурсы, выделяемые на overhead самого runtime. Если Pod использует runtime с overhead, это влияет на планирование.

```bash
# Проверка доступных RuntimeClass
kubectl get runtimeclass
# → NAME                    HANDLER                 OVERHEAD   SCHEDULING-HINTS
# → gvisor                  runsc                   120Mi      <none>
# → kata                    kata                    160Mi      <none>
# → runc (default)          runc                    <none>     <none>

# Проверка overhead в RuntimeClass
kubectl get runtimeclass gvisor -o yaml
# → apiVersion: node.k8s.io/v1
# → handler: runsc
# → overhead:
# →   podFixed:
# →     memory: "120Mi"
# →     cpu: "250m"

# Проверка Pod с указанным RuntimeClass
kubectl get pod <pod-name> -o jsonpath='{.spec.runtimeClassName}'
# → gvisor

# Проверка реального потребления Pod с overhead
kubectl top pod <pod-name>
# → NAME                     CPU(cores)   MEMORY(bytes)
# → my-app-gvisor            150m         280Mi  (включая 120Mi overhead)
```

**Механизм:** При планировании учитывается `requests + overhead`. Если узел имеет 4Gi RAM, а Pod требует 3Gi + 120Mi overhead, планировщику нужно 3120Mi, а не 3Gi. При нехватке ресурсов под будет в Pending.

### GPU и специфические ресурсы

GPU и другие специфические ресурсы (FPGA, Infiniband, custom devices) планируются через extended resources.

```bash
# Проверка доступных GPU на узлах
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, gpu: .status.capacity["nvidia.com/gpu"]}'
# → {"name": "gpu-node-1", "gpu": "4"}
# → {"name": "gpu-node-2", "gpu": "2"}

# Проверка Pod с GPU
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].resources.limits}'
# → {"nvidia.com/gpu": "1", "cpu": "2", "memory": "4Gi"}

# Проверка выделенных GPU
kubectl describe node gpu-node-1 | grep -A 5 "Allocated resources"
# → nvidia.com/gpu
# →   Limits:
# →     nvidia.com/gpu:  3
# →   Requests:
# →     nvidia.com/gpu:  2

# Проверка Device Plugin
kubectl get pods -n kube-system -l name=nvidia-device-plugin-ds
# → NAME                                READY   STATUS    RESTARTS   AGE
# → nvidia-device-plugin-daemonset-xxx  1/1     Running   0          10d
```

**Типичные ошибки:**
- `Insufficient nvidia.com/gpu` — все GPU на узлах заняты
- GPU Device Plugin не установлен или не готов
- Узел не имеет GPU, но Pod требует его через `nodeSelector`

### Container Runtime (containerd/CRI-O) и Pending

Если Pod назначен на узел, но CRI не работает, Pod будет в Pending/ContainerCreating:
```bash
# Проверка CRI через crictl
ssh <node> "crictl info"
# → если ошибка — CRI не работает

# Проверка статуса CRI
ssh <node> "systemctl status containerd"
# → Active: active (running) или failed

# Проверка socket CRI
ssh <node> "ls -la /run/containerd/containerd.sock"
# → если socket отсутствует — containerd не запущен

# Проверка версии CRI
ssh <node> "crictl version"
# → Version:  1.7.x
# → RuntimeName:  containerd

# Проверка sandbox на узле
ssh <node> "crictl pods | grep <pod-name>"
# → если Pod отсутствует в выводе — sandbox не создан
```

**Типичные ошибки CRI:**
- `context deadline exceeded` — CRI не отвечает (containerd завис)
- `rpc error: code = Unavailable` — socket CRI недоступен
- `cannot find runtime endpoint` — kubelet не настроен на CRI socket

**Важно:** Версия kubelet и CRI должны совпадать. Проверка: `ssh <node> "kubelet --version"` и `ssh <node> "crictl version"`.

### kube-proxy и Pending

kube-proxy напрямую не блокирует планирование, но может косвенно влиять:
```bash
# Проверка времени обновления правил kube-proxy
ssh <node> "iptables -L -n | wc -l"
# → > 10000 правил — возможны задержки

# Проверка latency kube-proxy
kubectl logs -n kube-system -l k8s-app=kube-proxy --tail=50
# → если высокие задержки — kube-proxy перегружен

# Проверка IPVS (если используется)
ssh <node> "ipvsadm -L -n | wc -l"
# → > 5000 записей — возможны задержки
```

**Связь с Pending:** При большом количестве сервисов (>5000) kube-proxy тормозит обновление iptables/ipvs. Pod может быть в Running, но readiness probe не работает (DNS не резолвится) → Pod не готов → создаёт видимость Pending.

### Network Policy и DNS

Хотя Network Policy не блокирует планирование, они могут привести к тому, что Pod в Running не работает (看上去 как Pending из-за failing readiness probes).

```bash
# Проверка DNS-сервиса
kubectl get svc -n kube-system kube-dns
# → NAME       TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)         AGE
# → kube-dns   ClusterIP   10.96.0.10   <none>        53/UDP,53/TCP   10d

# Проверка DNS-подов
kubectl get pods -n kube-system -l k8s-app=kube-dns
# → NAME                       READY   STATUS    RESTARTS   AGE
# → coredns-xxx                1/1     Running   0          10d
# → coredns-yyy                1/1     Running   0          10d

# Проверка DNS из внутри Pod
kubectl exec <pod-name> -- nslookup kubernetes.default
# → Server:    10.96.0.10
# → Address:   10.96.0.10#53
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.96.0.1

# Проверка NetworkPolicy в Namespace
kubectl get networkpolicy -n <namespace>
# → NAME                  POD-SELECTOR   AGE
# → deny-all-ingress      <none>         10d
# → allow-web-to-api      app=api        5d
```

**Диагностика DNS:**
1. Если `nslookup` не работает — проверьте `kube-dns` Pod
2. Если DNS работает, но приложение не может достучаться до сервиса — проверьте `NetworkPolicy`
3. Используйте `kubectl exec` с `wget`/`curl` для проверки коннективности

### Эфемеральные контейнеры для отладки

Когда под в Pending и недоступен для `kubectl exec`, используйте `kubectl debug` для запуска отладочного контейнера.

```bash
# Отладка Pod с использованием ephemeral container
kubectl debug <pod-name> -it --image=busybox --target=<container-name>
# → If you don't see a command prompt, try pressing enter.
# → / #

# Отладка с сетевыми инструментами
kubectl debug <pod-name> -it --image=nicolaka/netshoot --target=<container-name>
# → bash-5.1# nslookup kubernetes.default
# → bash-5.1# curl -v http://api-service:8080

# Отладка узла (если Pod не запускается из-за проблем на узле)
kubectl debug node/<node-name> -it --image=busybox
# → Targeting node "node-1". Use `kubectl describe node/node-1` to see node resources.
# → If you don't see a command prompt, try pressing enter.
# → / #

# Проверка ресурсов узла из отладочного контейнера
kubectl exec <pod-name> -c debugger -- cat /proc/meminfo | head -5
# → MemTotal:       16384000 kB
# → MemFree:         2048000 kB
# → MemAvailable:    4096000 kB

# Проверка сетевых интерфейсов
kubectl exec <pod-name> -c debugger -- ip addr show
# → 1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536
# → 2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
```

**Применение:**
- Проверка доступности сервисов из сети Pod
- Проверка DNS-резолва
- Проверка доступности PVC/томов
- Проверка сетевых политик (с `netshoot`)

---

## Лучшие практики

### Профилактика Pending

1.  **Right-sizing:** Используйте `kubectl top pods` или VPA для определения реального потребления ресурсов. Установите `requests` на уровне 80-90% от пикового потребления.
2.  **LimitRange:** Установите `default` и `defaultRequest` для Namespace, чтобы поды без явных ресурсов не вызывали ошибки.
3.  **ResourceQuota:** Настройте квоты с запасом 20-30% от текущего потребления.
4.  **PodDisruptionBudget:** Убедитесь, что PDB позволяет временное превышение реплик при перемещении подов (для Drain).
5.  **Topology Spread:** Используйте `topologySpreadConstraints` вместо жестких `podAntiAffinity` для гибкого распределения.
6.  **Priority Classes:** Определите системы приоритетов для критических сервисов (database, API gateway) и фоновых задач (batch jobs).
7.  **Pod Overhead:** Учитывайте overhead runtime при использовании alternatives (gvisor, kata) — добавляйте к `requests` значение overhead из RuntimeClass.
8.  **Ephemeral Storage requests:** Явно указывайте `ephemeral-storage` requests, особенно для логов и временных файлов.

### Быстрое восстановление

1.  **Эскалация приоритета:** Если под критичен, временно увеличьте его `priorityClassName`.
2.  **Ручное назначение:** Временно укажите `spec.nodeName` для аварийного запуска (только для отладки).
3.  **Расширение кластера:** Добавьте узлы вручную, если CA не справляется.
4.  **Очистка квот:** Если `ResourceQuota` исчерпана — удалите неиспользуемые поды или увеличьте лимит.
5.  **Cordon проблемных узлов:** Если узел в `MemoryPressure` — пометьте его `kubectl cordon <node>` и перезапустите поды на другие узлы.

---

## Граничные случаи и известные ограничения

1.  **WaitingForFirstConsumer + Zonal Mismatch:** Том создается в зоне A, но под планируется в зону B. PVC и под остаются в `Pending` навсегда. Решение: `volumeBindingMode: WaitForFirstConsumer` + согласование `nodeSelector`.
2.  **MaxPods:** Узел достиг лимита `maxPods` (по умолчанию 110). Новые поды не планируются. Проверка: `kubectl describe node <node> | grep -A 3 "Allocated pods"`.
3.  **Ephemeral Storage:** Под требует больше `ephemeral-storage`, чем доступно на узле. Симптом: `Insufficient ephemeral-storage` в событиях.
4.  **Preemption Cycle:** Низкоприоритетный под вытесняет еще более низкоприоритетный, который пересоздается и снова вытесняет — бесконечный цикл. Решение: установите `preemptionPolicy: Never` для фоновых задач.
5.  **DaemonSet + Unschedulable:** При `kubectl cordon` DaemonSet продолжает работать (автоматический toleration), но если узел имеет `NoExecute` taint — поды удаляются.
6.  **Static Pods:** Поды, управляемые kubelet напрямую (в `/etc/kubernetes/manifests`), не проходят планировщик. Если static Pod в Pending — проблема в манифесте или kubelet.
7.  **Pod Security Admission (PSA):** Если Namespace имеет строгие `restricted` профили, Pod без соответствующих `securityContext` будет отклонён на уровне API (ошибка admission webhooks), что может выглядеть как Pending.
8.  **EndpointSlice неполный:** Если Service не имеет Ready endpoint'ов (все поды в Terminating/Failed), readiness probes могут быть вести себя неожиданно, создавая видимость Pending.
9.  **Hung Pending из-за finalizers:** Pod с `finalizers` может зависнуть в Terminal (Failed/Succeeded) и блокировать ресурсы, влияя на квоты и новые Pending поды.
10. **Pod with schedulingGate + goroutine leak:** Известны случаи, когда внешний контроллер падает и не удаляет schedulingGate, навсегда блокируя Pod. Проверяйте `kubectl get pod <pod> -o json | jq '.spec.schedulingGates'`.

---

## Полезные команды для мониторинга

| Задача | Команда |
| :--- | :--- |
| **Список всех Pending подов** | `kubectl get pods -A --field-selector status.phase=Pending` |
| **Анализ через K8sGPT** | `k8sgpt analyze --filter=Pod --explain` |
| **События планирования** | `kubectl get events --field-selector involvedObject.kind=Pod --sort-by='.lastTimestamp'` |
| **Просмотр логов планировщика** | `kubectl logs -n kube-system -l component=kube-scheduler` |
| **Метрики очереди планировщика** | `kubectl get --raw /metrics \| grep scheduler_pending_pods` |
| **Метрики вытеснения** | `kubectl get --raw /metrics \| grep scheduler_preemption_attempts` |
| **Все поды с SchedulingGates** | `kubectl get pods -A -o json \| jq '.items[] \| select(.spec.schedulingGates != null)'` |
| **Проверка Node Pressure** | `kubectl get nodes -o json \| jq '.items[] \| {name:.metadata.name, conditions:[.status.conditions[] \| select(.type!="Ready") \| {type:.type, status:.status}]}'` |
| **PDB блокирующие вытеснение** | `kubectl get pdb -A -o json \| jq '.items[] \| select(.status.currentHealthy < .spec.minAvailable)'` |
| **Очередь CA на масштабирование** | `kubectl get --raw /metrics \| grep cluster_autoscaler_unschedulable_pods_count` |
| **Проверка RuntimeClass overhead** | `kubectl get runtimeclass -o json \| jq '.items[] \| {name:.metadata.name, overhead:.overhead}'` |
| **GPU доступность** | `kubectl get nodes -o json \| jq '.items[] \| {name:.metadata.name, gpu:.status.capacity["nvidia.com/gpu"]}'` |
| **DNS-сервис** | `kubectl get svc -n kube-system kube-dns` |
| **NetworkPolicy в Namespace** | `kubectl get networkpolicy -n <namespace>` |
| **Эфемеральные контейнеры** | `kubectl debug <pod> -it --image=busybox` |
| **Отладка узла** | `kubectl debug node/<node> -it --image=busybox` |

---

## Дополнительная информация

### Дополнительные сценарии

- **[ServiceAccount и монтирование токена](./common_cases_and_solutions.md#11-serviceaccount-и-монтирование-токена)** — ошибки SA при монтировании секретов.
- **[Spot-инстансы и taints](./common_cases_and_solutions.md#12-spot-инстансы-и-taints)** — специфика планирования на spot-узлах.
- **[DaemonSet Pending](./common_cases_and_solutions.md#13-daemonset-pending-на-отдельном-узле)** — диагностика DaemonSet на проблемных узлах.
- **[StatefulSet Pending](./common_cases_and_solutions.md#14-statefulset-pending-из-за-unbound-pvc)** — PVC и zonal mismatch для StatefulSet.
- **[Ephemeral Storage exhaustion](./common_cases_and_solutions.md#15-ephemeral-storage-exhaustion)** — нехватка временного хранилища.
- **[Ресурсная фрагментация](./definitions_and_concepts.md#ресурсная-фрагментация-resource-fragmentation)** — granular requests и insufficient resources.

### Связанные ресурсы

*   **[Определения и концепции](./definitions_and_concepts.md)** — базовые термины и архитектура планирования.
*   **[Распространенные случаи и решения](./common_cases_and_solutions.md)** — инструкции по исправлению типовых ошибок (CPU, RAM, Taints).
*   **[Продвинутые темы](./advanced_topics.md)** — Topology Spread, Scheduling Framework и настройка профилей.
*   **[Диагностика PVC](../../../Storage/pv_and_pvc_scenarios.md#диагностика-pending-pvc)** — детальный разбор проблем с хранилищем.
*   **[Жизненный цикл Pod](../../../Base/Pod/pod_lifecycle_and_state.md)** — как фаза Pending соотносится с другими состояниями.
*   **[Kube-scheduler — архитектура](../../../Concepts/kube_scheduler.md)** — внутренние плагины и Scheduling Framework.
*   **[Taints и Tolerations](../../../Scheduling/taints_and_tolerations.md)** — механизмы изоляции узлов.
*   **[Affinity и Anti-Affinity](../../../Scheduling/affinity.md)** — правила привязки подов к узлам и друг к другу.
*   **[Cluster Autoscaler — детальный обзор](../../Autoscaling/cluster_autoscaler_detailed.md)** — логика Scale-Up/Down и взаимодействие с Pending подами.
*   **[QoS, LimitRange и ResourceQuota](../../../Scheduling/qos_limit_and_requests.md)** — управление ресурсами и квотами.
*   **[NetworkPolicy](../../../Networking/network_policies.md)** — политики сетевого взаимодействия.
*   **[DNS в Kubernetes](../../../Networking/dns_troubleshooting.md)** — диагностика DNS-резолва.
*   **[RuntimeClass](../../../Runtime/runtime_class.md)** — выбор контейнерного runtime и overhead.
*   **[Ephemeral Containers](../../../Base/Pod/ephemeral_containers.md)** — отладка через кратковременные контейнеры.
*   **[Container Runtime](../../../Concepts/container_runtime.md)** — containerd, CRI-O, crictl, диагностика CRI.
*   **[Kubelet](../../../Concepts/kubelet.md)** — system-reserved, kube-reserved, Allocatable, eviction.
*   **[Pod Security Context](../../../Security/pod_security_context.md)** — PSA и безопасность Pod.
*   **[Admission Controllers](../../../Concepts/admission_controllers.md)** — вебхуки admission.
*   **[Вопросы для собеседования](./interview_questions.md)** — типичные вопросы и ответы по Pending.
*   **[Postmortem кейсы](./postmortem_cases.md)** — реальные сценарии из продакшена.
