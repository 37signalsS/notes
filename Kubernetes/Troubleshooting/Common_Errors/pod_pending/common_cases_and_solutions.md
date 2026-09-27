# Pod в состоянии `Pending`: Распространенные случаи и решения

---

## Определения

**Сценарии Pending-статуса** — типовые конфигурационные или инфраструктурные ситуации, при которых планировщик (`kube-scheduler`) или внешние контроллеры не позволяют Pod перейти в фазу `Running`. Решения классифицируются по стратегиям: оптимизация нагрузки, масштабирование или устранение блокировок.

**Right-sizing (подбор ресурсов)** — процесс оптимизации `requests` и `limits` Pod на основе реального потребления. Некорректные значения (завышенные или заниженные) являются наиболее частой причиной `Pending`. Используйте `kubectl top pods` или VPA для анализа.

**Rolling Update Deadlock (взаимоблокировка обновления)** — ситуация, когда новые Pod не могут быть запланированы из-за `podAntiAffinity` или `TopologySpreadConstraints`, так как старые Pod (с предыдущей версией шаблона) занимают все допустимые домены.

**Зональный конфликт (Zonal Mismatch)** — ситуация, при которой требования пода к хранилищу (PV/PVC) жестко привязаны к одной зоне доступности (Availability Zone), а вычислительные ресурсы (Nodes) доступны только в другой.

**Volume Binding Deadlock (взаимоблокировка привязки томов)** — циклическая зависимость: Pod не может быть запланирован из-за других ограничений, а PVC не привязывается, потому что `volumeBindingMode: WaitForFirstConsumer` требует назначения Pod на узел.

**Preemption Cascading (каскадное вытеснение)** — ситуация, когда вытеснение Pod с более низким приоритетом вызывает ошибки планирования для других Pod, создавая цепную реакцию `Pending`.

---

## Базовые концепции

### Стратегии устранения Pending

Для устранения состояния `Pending` необходимо сопоставить требования Pod (`requests`, `affinity`, `PVC`) с текущим состоянием кластера. Решения классифицируются по трем стратегиям:

1. **Оптимизация нагрузки:** Корректировка манифестов (уменьшение `requests`, использование мягких правил `affinity`, исправление `tolerations`).
2. **Масштабирование:** Добавление узлов через Cluster Autoscaler или ручное расширение пулов.
3. **Устранение блокировок:** Исправление ошибок в зависимых объектах (PVC, PriorityClass, Scheduling Gates, taints).

### Типичные категории Pending

| Категория | Описание | Частота |
|:---|:---|:---|
| **Нехватка ресурсов** | `requests` Pod превышают доступную емкость узлов | Очень высокая |
| **Taints/Tolerations** | Узлы имеют метки, которые не допускают Pod | Высокая |
| **Affinity/Topology** | Правила привязки не могут быть выполнены | Высокая |
| **Хранилище** | PVC не привязан, StorageClass недоступен | Средняя |
| **Квоты** | ResourceQuota в Namespace превышен | Средняя |
| **Scheduling Gates** | Pod заблокирован внешним контроллером | Низкая |
| **Приоритеты** | Вытеснение невозможно из-за PDB или низкого приоритета | Низкая |

### Связь с другими механизмами

- **Cluster Autoscaler:** Масштабирует кластер только для Pod с `Unschedulable` (не `SchedulingGated`).
- **PodDisruptionBudget:** Блокирует вытеснение, но не блокирует планирование.
- **PriorityClass:** Определяет порядок планирования и вытеснения.
- **ResourceQuota:** Проверяется на уровне Namespace перед планированием.

---

## Практические сценарии

### 1. Нехватка ресурсов (CPU, Memory, GPU)

**Симптом:** События `FailedScheduling` с сообщениями `Insufficient cpu`, `Insufficient memory` или `Insufficient nvidia.com/gpu`.

**Мини-кейс: Ошибка копирования (Ambiguous Requests)**
Разработчик развернул микросервис с `requests.cpu: 4`. В кластере используются узлы `t3.medium` (2 vCPU).
*   **Диагностика:** `kubectl describe pod` показывает `0/5 nodes are available: 5 Insufficient cpu`.
*   **Решение:** Уменьшение `requests.cpu` до реальных `200m`. Под запланировался на первый же свободный узел.

**Диагностика:**
```bash
# Проверка ресурсов узлов
kubectl describe nodes | grep -A 5 "Allocated resources"
# → CPU (cores)   4500m / 8000m
# → Memory (Gi)   12Gi / 32Gi

# Проверка ресурсов Pod
kubectl describe pod <name> | grep -A 3 "Requests:"
# → Limits:   cpu:  4,   memory: 8Gi
# → Requests: cpu:  4,   memory: 4Gi

# Проверка реального потребления
kubectl top pods
# → NAME    CPU(cores)   MEMORY(bytes)
# → my-app  250m         256Mi
```

**Решения:**
1. **Right-sizing:** Уменьшите `requests` до реальных значений (используйте `kubectl top pods` или VPA).
2. **Масштабирование:** Добавьте узлы через Cluster Autoscaler или вручную.
3. **Приоритеты:** Используйте `PriorityClass` для критических сервисов (они вытесняют менее важные Pod).

**Рекомендации:**
*   **Right-sizing:** Используйте `kubectl top pods` или VPA (Vertical Pod Autoscaler) для определения реального потребления.
*   **Extended Resources:** Проверьте наличие NVIDIA Device Plugin, если под требует GPU. Узлы без плагина имеют `Capacity: 0` для этого ресурса.
*   **Мониторинг:** Настройте алерты на `kube_pod_status_phase{phase="Pending"} > 0`.

---

### 2. Конфликты планирования (Affinity и Topology)

**Симптом:** Сообщения `node(s) didn't match Pod's node affinity/selector` или `node(s) had topology spread constraint slack conflict`.

**Сценарий: Rolling Update Deadlock**
При обновлении приложения с `podAntiAffinity` новые поды не могут встать на узлы, где еще работают старые.
*   **Решение:** Используйте `matchLabelKeys` (v1.31+), чтобы планировщик игнорировал поды предыдущих версий при расчете ограничений распределения.
*   **Мягкие правила:** Замените жесткое условие `requiredDuringScheduling...` на `preferredDuringScheduling...`.

**Диагностика:**
```bash
# Проверка распределения по зонам
kubectl get pods -l app=my-app -o custom-columns=NAME:.metadata.name,NODE:.spec.nodeName,ZONE:.metadata.labels.topology\.kubernetes\.io/zone
# → NAME           NODE      ZONE
# → my-app-abc     node-1    zone-a
# → my-app-def     node-2    zone-b

# Проверка events
kubectl describe pod <name> | grep -A 10 Events
# → Warning  FailedScheduling  0/3 nodes are available: 1 didn't match pod topology spread constraints...
```

**Решения:**
1. **matchLabelKeys:** Добавьте `matchLabelKeys: [pod-template-hash]` для Deployments с Rolling Update.
2. **Мягкие правила:** Используйте `preferredDuringScheduling...` вместо `requiredDuringScheduling...`.
3. **Увеличение maxSkew:** Увеличьте `maxSkew` с 1 до 2 (временно для отладки).
4. **ScheduleAnyway:** Используйте `whenUnsatisfiable: ScheduleAnyway` вместо `DoNotSchedule`.

---

### 3. Ошибки Taints и Tolerations

**Симптом:** Сообщение `node(s) had taint {key: value}, that the pod didn't tolerate`.

**Решение:**
*   **Корректировка Tolerations:** Добавьте допуски в `spec.tolerations`.
*   **Системные Taints:** Если узел имеет `node.kubernetes.io/disk-pressure`, не добавляйте допуски, а очистите место на диске узла.

**Диагностика:**
```bash
# Проверка taints на узлах
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, taints: .spec.taints}'
# → {"name":"master-1","taints":[{"key":"node-role.kubernetes.io/control-plane","effect":"NoSchedule"}]}

# Проверка tolerations в Pod
kubectl describe pod <name> | grep -A 5 Tolerations
# → Tolerations: node-role.kubernetes.io/control-plane:NoExecute op=Exists
```

**Решения:**
1. **Добавить tolerations:** Добавьте `tolerations` в манифест Pod.
2. **nodeSelector:** Используйте `nodeSelector` для выбора других узлов.
3. **nodeAffinity:** Используйте `nodeAffinity` для более гибкого выбора.
4. **Очистка узла:** Если узел имеет `disk-pressure` или `memory-pressure`, очистите ресурсы.

---

### 4. Проблемы хранилища (PVC и StorageClass)

**Симптом:** Сообщения `pod has unbound immediate PersistentVolumeClaims` или `volume node affinity conflict`.

**Зональный конфликт (Cloud Zonal Issue):**
Под требует диск, созданный в зоне `us-east-1a`, но `nodeSelector` или планировщик пытаются отправить его в `us-east-1b`.
*   **Диагностика:** `kubectl describe pvc <name>` покажет ошибку привязки тома.
*   **Решение:** Убедитесь, что в `StorageClass` установлено `volumeBindingMode: WaitForFirstConsumer`. Это заставляет PVC "ждать" решения планировщика и создаваться в той же зоне, где найден свободный узел.

**Диагностика:**
```bash
# Проверка PVC
kubectl describe pvc <pvc-name>
# → Status: Pending
# → Events: Waiting for a volume to be created...

# Проверка StorageClass
kubectl get sc
# → NAME                 PROVISIONER                    AGE
# → local-path           rancher.io/local-path          10d

# Проверка PV
kubectl get pv
# → NAME        CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   CLAIM
```

**Решения:**
1. **WaitForFirstConsumer:** Установите `volumeBindingMode: WaitForFirstConsumer` в StorageClass.
2. **Проверка provisioner:** Убедитесь, что provisioner (CSI-драйвер) запущен и работает.
3. **Проверка квот:** Проверьте лимиты хранилища в ResourceQuota.

---

### 5. Лимиты и квоты (ResourceQuota)

**Симптом:** Сообщение `exceeded quota: <name>, requested: cpu=..., used: cpu=..., limited: cpu=...`.

**Решение:**
*   **Аудит квот:** Проверьте текущее использование: `kubectl describe quota -n <namespace>`.
*   **Приоритеты:** Высокоприоритетные поды могут потреблять квоту, предназначенную для других задач. Используйте раздельные `ResourceQuota` по `scope` (например, `BestEffort` vs `NotBestEffort`).

**Диагностика:**
```bash
# Проверка квот
kubectl describe quota -n <namespace>
# → Name:                   my-quota
# → Resource                Used  Hard
# ─────────────────────────────────────
# → requests.cpu            4500m 8000m
# → requests.memory         12Gi  32Gi
# → pods                    15    20

# Проверка LimitRange
kubectl describe limitrange -n <namespace>
# → Name:       my-limitrange
# → Type        Resource  Min   Max   Default Request  Default Limit
# ──────────────────────────────────────────────────────────────────
# → Container   cpu       100m  4     200m             500m
```

**Решения:**
1. **Увеличение лимитов:** Увеличьте `hard` в ResourceQuota (если ресурсы доступны).
2. **Раздельные квоты:** Используйте `scope` для разделения квот (например, `BestEffort` для dev и `NotBestEffort` для prod).
3. **LimitRange:** Настройте `Default Request` и `Default Limit` для Pod без явных указаний.

---

### 6. Врата планирования (Scheduling Gates)

**Симптом:** Под в состоянии `Pending`, статус `SchedulingGated`. События планировщика отсутствуют.

**Решение:**
*   **Проверка манифеста:** Выполните `kubectl get pod <name> -o jsonpath='{.spec.schedulingGates}'`.
*   **Внешние контроллеры:** Проверьте работоспособность контроллеров (например, для подготовки данных или внешних проверок безопасности), которые должны удалять эти ворота.

**Диагностика:**
```bash
# Проверка gates
kubectl get pod <pod-name> -o jsonpath='{.spec.schedulingGates}'
# → [{"gateName":"example.com/data-ready"}]

# Проверка статуса
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="PodScheduled")]}'
# → {"type":"PodScheduled","status":"False","reason":"SchedulingGated"}
```

**Решения:**
1. **Проверка логов:** Проверьте логи контроллера, установившего gates.
2. **Удаление gates:** Временно удалите Pod и пересоздайте без gates (для отладки).
3. **Ожидание:** Если gate удаляется после выполнения условия, дождитесь его выполнения.

---

### 7. Вытеснение и приоритеты (Preemption)

**Симптом:** Под висит в `Pending`, в событиях сообщение `PreemptionVictims`.

**Решение:**
*   **PDB Conflict:** Если низкоприоритетные поды защищены `PodDisruptionBudget`, планировщик не сможет их выселить. Увеличьте количество узлов или временно смягчите PDB.
*   **PriorityClass:** Убедитесь, что `priorityClassName` указан верно и имеет достаточный вес относительно других подов.

**Диагностика:**
```bash
# Проверка PDB
kubectl get pdb -A
# → NAME      MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → my-pdb    2               <none>            0                     10d

# Проверка приоритетов
kubectl get pods -o custom-columns=NAME:.metadata.name,PRIORITY:.spec.priority,PRIORITYCLASS:.spec.priorityClassName
# → NAME            PRIORITY    PRIORITYCLASS
# → my-app          1000        high-priority
# → other-app       100         low-priority
```

**Решения:**
1. **Увеличение PDB:** Увеличьте `minAvailable` или уменьшите `maxUnavailable` в PDB.
2. **Увеличение приоритета:** Используйте `PriorityClass` с более высоким значением.
3. **Увеличение кластера:** Добавьте узлы для размещения Pod без вытеснения.

---

### 8. Специализированные ресурсы (DRA)

**Симптом:** Ожидание `ResourceClaim` (v1.32+).

**Решение:**
*   Проверьте статус претензии: `kubectl get resourceclaims`.
*   Убедитесь, что DRA-драйвер (например, для специфических ускорителей) запущен и корректно сообщает о ресурсах API-серверу.

**Диагностика:**
```bash
# Проверка ResourceClaims
kubectl get resourceclaims -A
# → NAME                    STATUS    AGE
# → my-gpu-claim            Pending   5m

# Проверка DRA-драйвера
kubectl get pods -n kube-system | grep dra
# → dra-driver-xxxxx        1/1     Running   0          10d
```

**Решения:**
1. **Проверка драйвера:** Убедитесь, что DRA-драйвер запущен и работает.
2. **Проверка ресурсов:** Убедитесь, что ресурсы (GPU, FPGA) доступны на узлах.
3. **Проверка claim:** Убедитесь, что ResourceClaim указывает правильный драйвер и ресурсы.

---

### 9. Конфликт nodeSelector и nodeAffinity

**Симптом:** Сообщение `0/X nodes are available: Y node(s) didn't match node selector`.

**Диагностика:**
```bash
# Проверка labels на узлах
kubectl get nodes --show-labels | tr ',' '\n' | grep -E "^(kubernetes.io/|topology)"
# → kubernetes.io/hostname=node-1
# → topology.kubernetes.io/zone=zone-a

# Проверка nodeSelector в Pod
kubectl describe pod <name> | grep -A 5 NodeSelector
# → NodeSelector:  kubernetes.io/hostname: node-1
```

**Решения:**
1. **Проверка labels:** Убедитесь, что нужные labels есть на узлах.
2. **Использование affinity:** Замените `nodeSelector` на `nodeAffinity` для более гибкого выбора.
3. **Удаление ограничений:** Временно удалите `nodeSelector` для отладки.

---

### 10. Конфликт Inter-Pod Affinity

**Симптом:** Сообщение `0/X nodes are available: Y node(s) didn't match inter-pod affinity`.

**Диагностика:**
```bash
# Проверка Pod с affinity
kubectl get pods -l app=frontend -o custom-columns=NAME:.metadata.name,NODE:.spec.nodeName
# → NAME            NODE
# → frontend-abc    node-1
# → frontend-def    node-2

# Проверка affinity в Pod
kubectl describe pod <name> | grep -A 10 "RequiredDuringScheduling"
# → RequiredDuringSchedulingIgnoredDuringExecution:
# →   - labelSelector:
# →       matchLabels:
# →         app: backend
# →     topologyKey: kubernetes.io/hostname
```

**Решения:**
1. **Проверка целевых Pod:** Убедитесь, что Pod с нужными labels существуют и запущены.
2. **Мягкие правила:** Используйте `preferredDuringScheduling...` вместо `requiredDuringScheduling...`.
3. **Удаление affinity:** Временно удалите affinity для отладки.

---

### 11. ServiceAccount и монтирование токена

**Симптом:** Pod в Pending или `ContainerCreating` с ошибками `FailedMount` или `FailedCreatePodConfigMap`.

**Мини-кейс:** Deployment ссылается на `serviceAccountName: my-sa`, но ServiceAccount не создан в target namespace.

**Диагностика:**
```bash
# Проверка ServiceAccount
kubectl get sa my-sa -n <namespace>
# → Error from server (NotFound): serviceaccounts "my-sa" not found

# Проверка Secret SA
kubectl get sa my-sa -n <namespace> -o jsonpath='{.secrets}'
# → (пусто — SA без секрета)

# Проверка событий монтирования
kubectl describe pod <name> | grep -A 5 "Events:"
# → Warning  FailedMount  ... MountVolume.SetUp failed for volume "xxx": secret "my-sa-token-xxx" not found
```

**Решения:**
1. **Создать SA:** `kubectl create serviceaccount my-sa -n <namespace>`
2. **Проверить автоматическое создание Secret:** SA автоматически создаёт Secret с токеном (v1.24+). Если `automountServiceAccountToken: false` — токен не создаётся.
3. **RBAC:** Убедитесь, что SA имеет права на required ресурсы (RoleBinding/ClusterRoleBinding).

**Важно:** ServiceAccount с `automountServiceAccountToken: false` не создаёт Secret → Pod не может смонтировать токен → Pending/ContainerCreating.

---

### 12. Spot-инстансы и taints

**Симптом:** `0/X nodes are available: Y had taint {spot-instance: true}, that pod didn't tolerate`.

**Мини-кейс:** Кластер на spot-инстансах (AWS/GCP/Azure). Spot-узлы имеют taint `spot-instance=true:NoSchedule`. Pod без `tolerations` не может быть запланирован.

**Диагностика:**
```bash
# Проверка taints на spot-узлах
kubectl get nodes -o json | jq '.items[] | select(.spec.taints[]? | .key=="spot-instance") | {name:.metadata.name, taints:.spec.taints}'
# → {"name":"spot-node-1","taints":[{"key":"spot-instance","value":"true","effect":"NoSchedule"}]}

# Проверка tolerations в Pod
kubectl describe pod <name> | grep -A 5 Tolerations
# → Tolerations: <пусто>
```

**Решения:**
1. **Добавить tolerations:** Добавьте `tolerations` для spot-узлов в манифест Pod.
2. **nodeSelector для on-demand:** Используйте `nodeSelector: node.kubernetes.io/instance-type=~"m5.*"` для выбора on-demand узлов.
3. **PriorityClass:** Для критических сервисов используйте `preemptionPolicy: PreemptLowerPriority` для вытеснения с spot-узлов.

---

### 13. DaemonSet Pending на отдельном узле

**Симптом:** DaemonSet работает на 9 узлах из 10. На одном узле Pod не создан.

**Диагностика:**
```bash
# Проверка статуса DaemonSet
kubectl get daemonset <ds-name>
# → DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR
# → 10        9         9       9            9           <none>

# Проверка conditions узла
kubectl describe node <node> | grep -A 10 "Conditions:"
# → MemoryPressure   True    ...   ← блокирует запуск Pod

# Проверка taints
kubectl get node <node> -o jsonpath='{.spec.taints}'
# → [{"key":"node.kubernetes.io/disk-pressure","effect":"NoSchedule"}]
```

**Решения:**
1. **Очистить узел:** Если `DiskPressure` — освободить место на диске.
2. **Удалить taint:** Если taint не критичен — `kubectl taint nodes <node> node.kubernetes.io/disk-pressure:NoSchedule-`
3. **DaemonSet tolerations:** DaemonSet автоматически добавляет toleration для `node.kubernetes.io/unschedulable:NoSchedule`, но не для других taints.

---

### 14. StatefulSet Pending из-за unbound PVC

**Симптом:** StatefulSet с 3 репликами: 2 Pod запущены, 3-й Pending.

**Диагностика:**
```bash
# Проверка PVC
kubectl get pvc -n <namespace>
# → NAME              STATUS    VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS
# → data-myapp-0      Bound     pvc-xxx  10Gi       RWO            standard
# → data-myapp-1      Bound     pvc-yyy  10Gi       RWO            standard
# → data-myapp-2      Pending                                       standard

# Проверка StorageClass
kubectl get sc standard -o jsonpath='{.volumeBindingMode}'
# → WaitForFirstConsumer (ожидает назначения Pod)

# Проверка Availability Zone
kubectl get node <node> -o jsonpath='{.metadata.labels.topology\.kubernetes\.io/zone}'
# → zone-c (все узлы в zone-c заняты)
```

**Решения:**
1. **Добавить узлы:** Добавить узлы в zone-c через CA или вручную.
2. **Изменить zone:** Убрать `nodeSelector` или использовать `topologySpreadConstraints` с `ScheduleAnyway`.
3. **Immediate binding:** Изменить `volumeBindingMode` на `Immediate` (риск zonal mismatch).

---

### 15. Ephemeral Storage exhaustion

**Симптом:** `0/X nodes are available: Y Insufficient ephemeral-storage`. Pod в Pending без видимых причин (CPU/RAM достаточно).

**Диагностика:**
```bash
# Проверка ephemeral-storage на узлах
kubectl describe nodes | grep -A 3 "ephemeral-storage"
# → ephemeral-storage:  100Gi   ← Capacity
# →   Allocatable:      95Gi    ← после вычета reserved

# Проверка использованного пространства
kubectl describe node <node> | grep -A 10 "Allocated resources"
# → ephemeral-storage
# →   Requests:  85Gi   ← 85Gi занято, свободно 10Gi

# Проверка Pod с высоким ephemeral-storage usage
kubectl get pods -A -o json | jq '.items[] | select(.spec.containers[].resources.requests["ephemeral-storage"] != null) | {name:.metadata.name, ns:.metadata.namespace, requests:.spec.containers[].resources.requests["ephemeral-storage"]}' | head -20
```

**Решения:**
1. **Уменьшить ephemeral-storage requests:** Снизить требования Pod.
2. **Очистить Pod/логи:** Удалить завершённые Pod, очистить логи контейнеров.
3. **Увеличить ephemeral-storage:** Расширить disk на узле или добавить узлы с большим диском.
4. **Настроить imageGC:** Увеличить `imageGCHighThresholdPercent` для автоматической очистки образов.

---

## Граничные случаи и известные ограничения

1. **ResourceQuota vs LimitRange:** ResourceQuota проверяется на уровне Namespace, LimitRange — на уровне Pod. Оба могут блокировать создание.
2. **Preemption игнорирует PDB:** По умолчанию вытеснение не проверяет PDB. С Kubernetes 1.21+ настраивается через feature gate `PreferNominatedNodeWithPDB`.
3. **CA не учитывает Scheduling Gates:** Cluster Autoscaler не масштабирует кластер для Pod с Scheduling Gates.
4. **Static Pods:** Pod, созданные kubelet напрямую (без API-сервера), не обрабатываются планировщиком.
5. **DaemonSet:** Автоматически добавляет `tolerations` для `node.kubernetes.io/unschedulable:NoSchedule`.
6. **StatefulSet:** PVC создаются до Pod и должны перейти в `Bound` перед запуском.
7. **MatchLabelKeys + StatefulSet:** `matchLabelKeys` не работает с StatefulSet (уникальные имена Pod).
8. **Immediate Binding:** PVC с `volumeBindingMode: Immediate` может привести к зональному конфликту.
9. **Preemption Cascading:** Вытеснение Pod может вызвать ошибки планирования для других Pod.
10. **Taint Effects:** `NoExecute` эвиктирует существующие Pod, `NoSchedule` блокирует только новые.

---

## Лучшие практики

### Профилактика Pending

1. **Ресурсы:** Всегда указывайте `requests` для CPU и memory. Используйте `kubectl top pods` для оценки реального потребления.
2. **Taints:** Для критических сервисов добавляйте `tolerations` и `nodeAffinity`. Для системных Pod используйте `PriorityClass` выше 2000000000.
3. **Хранилище:** Используйте `volumeBindingMode: WaitForFirstConsumer` для зональных дисков. Проверяйте доступность StorageClass перед созданием PVC.
4. **Topology Spread:** Всегда добавляйте `matchLabelKeys: [pod-template-hash]` для Deployments с Rolling Update (Beta v1.27+, GA v1.31).
5. **PriorityClass:** Создайте иерархию классов приоритета для критических сервисов и временных задач.

### Диагностика Pending

1. **Начните с `kubectl describe pod`:** Секция `Events` содержит причину.
2. **Проверьте квоты:** `kubectl describe quota -n <namespace>`
3. **Проверьте узлы:** `kubectl describe nodes | grep -A 5 "Allocated resources"`
4. **Проверьте taints:** `kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, taints: .spec.taints}'`
5. **Проверьте PDB:** `kubectl get pdb -A`

### Быстрое восстановление

1. **Ресурсы:** Уменьшите `requests` или добавьте узлы
2. **Taints:** Добавьте `tolerations` или выберите другие узлы через `nodeSelector`
3. **Хранилище:** Проверьте provisioner и `volumeBindingMode`
4. **Topology Spread:** Временно используйте `ScheduleAnyway` или увеличьте `maxSkew`

---

## Полезные команды для диагностики

| Задача | Команда |
|:---|:---|
| **Причина Pending** | `kubectl describe pod <pod-name> \| grep -A 10 Events` |
| **Ресурсы узлов** | `kubectl describe nodes \| grep -A 5 "Allocated resources"` |
| **Taints на узлах** | `kubectl get nodes -o json \| jq '.items[] \| {name: .metadata.name, taints: .spec.taints}'` |
| **Квоты Namespace** | `kubectl describe quota -n <namespace>` |
| **PDB** | `kubectl get pdb -A` |
| **StorageClass** | `kubectl get sc` |
| **PVC статус** | `kubectl get pvc -A \| grep Pending` |
| **Поды с gates** | `kubectl get pods -A -o json \| jq '.items[] \| select(.spec.schedulingGates != null) \| {name: .metadata.name, ns: .metadata.namespace}'` |
| **Распределение по зонам** | `kubectl get pods -l app=<app> -o custom-columns=NAME:.metadata.name,NODE:.spec.nodeName,ZONE:.metadata.labels.topology\.kubernetes\.io/zone` |

---

## Связанные ресурсы

- **[Диагностика](./diagnostics.md)** — алгоритм поиска причин Pending.
- **[Продвинутые темы](./advanced_topics.md)** — глубокий разбор Scheduling Gates и DRA.
- **[Определения и концепции](./definitions_and_concepts.md)** — базовые термины и архитектура планирования.
- **[Вопросы для собеседования](./interview_questions.md)** — типичные вопросы и ответы по Pending.
- **[Postmortem кейсы](./postmortem_cases.md)** — реальные сценарии из продакшена.
- **[Kubelet](../../../Concepts/kubelet.md)** — system-reserved, kube-reserved, Allocatable.
- **[Container Runtime](../../../Concepts/container_runtime.md)** — containerd, CRI-O, crictl.
