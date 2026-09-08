# Pod в состоянии `Pending`: Определения и концепции

---

## Определения

**Pending (ожидание)** — фаза жизненного цикла Pod (`status.phase`), означающая, что объект принят системой, но один или несколько контейнеров ещё не перешли в состояние `Running`. В контексте глубокой диагностики важно различать три подсостояния:

1.  **Не назначен (Unscheduled / Unschedulable):** Планировщик еще не выбрал узел для размещения. Поле `spec.nodeName` пустое. Основная причина — несоответствие требованиям ресурсов или политики.
2.  **Заблокирован (Gated):** Под удерживается механизмом **Scheduling Gates** (GA v1.30). Планировщик полностью игнорирует такой объект до удаления внешних блокировок из `spec.schedulingGates`.
3.  **Назначен, но не готов (Scheduled / ContainerCreating):** Узел выбран (`nodeName` заполнено), но запуск контейнеров заблокирован процессами подготовки (Init-контейнеры, монтирование томов, скачивание образов или настройка CNI).

**Планировщик (kube-scheduler)** — компонент плоскости управления, ответственный за поиск оптимального узла для Pod. Работает по принципу «однократного принятия решения» (в момент создания пода или его пересоздания контроллером). Архитектура и точки расширения описаны в [Kube-scheduler — архитектура](../../../Concepts/kube_scheduler.md).

**Scheduling Gates (врата планирования)** — механизм (GA v1.30), позволяющий удерживать Pod в состоянии `Pending` (статус `SchedulingGated`) до завершения внешних проверек (безопасность, квоты, подготовка данных). Планировщик полностью игнорирует такие поды, что снижает нагрузку на Control Plane. Подробнее: [Продвинутые темы](./advanced_topics.md#2-scheduling-gates-глубокий-анализ).

**Queueing Hints** — оптимизация планировщика (Beta v1.32), позволяющая плагинам указывать, при каких именно изменениях в кластере (например, освобождение конкретного ресурса) стоит повторно пытаться запланировать под из очереди `Unschedulable`. Снижает количество лишних попыток планирования.

**Node Affinity (привязка к узлам)** — правила в specifications Pod, определяющие предпочтения или требования к меткам узлов при планировании. Эволюция `nodeSelector` с поддержкой операторов `In`, `NotIn`, `Exists`, `DoesNotExist`. Подробнее: [Affinity и Anti-Affinity](../../Scheduling/affinity.md).

**Taints and Tolerations (метки и допуски)** — механизм изоляции узлов. `Taints` накладываются на узлы и «отталкивают» Pod без соответствующих `Tolerations`. Эффекты: `NoSchedule` (блокирует новые поды), `PreferNoSchedule` (мягкий отказ), `NoExecute` (эвикция существующих подов). Подробнее: [Taints и Tolerations](../../Scheduling/taints_and_tolerations.md).

**Pod Topology Spread Constraints** — ограничения на распределение Pod по доменам (узлы, зоны, регионы). Ключевые параметры: `maxSkew` (максимальная разница между доменами), `topologyKey` (ключ метки домена), `whenUnsatisfiable` (`DoNotSchedule` / `ScheduleAnyway`). Подробнее: [Affinity и Anti-Affinity](../../Scheduling/affinity.md#7-topology-spread-constraints).

**ResourceQuota (квота ресурсов)** — объект API, ограничивающий суммарное потребление ресурсов (CPU, RAM, количество Pod/Service/PVC) в рамках Namespace. При превышении лимита новые Pod могут оставаться в `Pending`.

**LimitRange (диапазон ресурсов)** — объект API, задающий минимальные и максимальные границы ресурсов для Pod и контейнеров в Namespace. Под без корректных `requests`/`limits` может быть отклонен.

**PersistentVolumeClaim (PVC)** — запрос на выделение хранилища. Связывается с PersistentVolume (PV) через StorageClass. При использовании `volumeBindingMode: WaitForFirstConsumer` PVC не привязывается к узлу, пока Pod не будет запланирован. Подробнее: [PV и PVC](../../Storage/pv_and_pvc.md).

**PodDisruptionBudget (PDB)** — объект API (`policy/v1`), ограничивающий количество Pod, unavailable при добровольных disruptions (drain, scale-down, preemption). Не защищает от вынужденных сбоев (аппаратные отказы, OOMKilled). Подробнее: [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md).

**Cluster Autoscaler (CA)** — системный контроллер для автоматического масштабирования кластера на основе `requests` Pod (не фактического использования). Масштабирование вверх происходит при наличии Pod в статусе `Pending` с причиной `Unschedulable`. Подробнее: [Cluster Autoscaler — детальный обзор](../../Autoscaling/cluster_autoscaler_detailed.md).

**Dynamic Resource Allocation (DRA)** — API для управления специализированными ресурсами (GPU, FPGA, NVMe) через `ResourceClaims` (Beta v1.32), заменяющее Device Plugins и позволяющее планировщику учитывать параметры ресурсов в структурированном виде.

**PriorityClass (класс приоритета)** — объект API, определяющий приоритет Pod при планировании и вытеснении. Pod с более высоким приоритетом может вытеснять Pod с более низким приоритетом. Подробнее: [PriorityClass — приоритеты](../../../Concepts/priorityclass.md).

---

## Базовые концепции

### Архитектура планирования

Планировщик обрабатывает Pod через **Scheduling Framework**, проходя этапы:

```
Pod Created
     │
     ▼
Queue (очередь: active / backoff / gated)
     │
     ▼
PreFilter → Filter → PostFilter → Reserve → Permit → PreBind → Bind → PostBind
```

1.  **Очередь (Queue):** Pod попадает в очередь `active` или `gated` (если есть Scheduling Gates). Поды в `backoff` ожидают повтора после неудачи.
2.  **Фильтрация (Filtering):** Последовательная проверка жестких ограничений для каждого узла:
    *   `NodeResourcesFit` — наличие CPU/RAM/ephemeral-storage/Ports
    *   `NodeAffinity` — соответствие `requiredDuringScheduling...`
    *   `TaintToleration` — наличие допусков для taints узла
    *   `PodTopologySpread` — выполнение ограничений распределения
    *   `InterPodAffinity` — совместимость с другими Pod
    *   `VolumeBinding` — доступность PVC/PV в зоне
    *   `NodeUnschedulable` — не помечен ли узел как `cordon`

3.  **Ранжирование (Scoring):** Присвоение баллов узлам (0-100):
    *   `LeastRequestedPriority` — приоритет узлам с наибольшим остатком ресурсов
    *   `MostRequestedPriority` — приоритет узлам с наибольшим использованием (bin-packing)
    *   `BalancedResourceAllocation` — баланс CPU/RAM
    *   `InterPodAffinity` — предпочтение узлов с подходящими Pod

4.  **Binding:** Запись выбранного узла в API-сервер (установка `spec.nodeName`).

**Ключевой момент:** Если ни один узел не прошел фильтрацию, планировщик переходит к **PostFilter** (вытеснение/preemption).

### Типы ресурсов

Планировщик сопоставляет `spec.resources.requests` Pod с доступной емкостью узлов (Allocatable):

| Тип | Примеры | Особенности |
|:---|:---|:---|
| **Standard Resources** | CPU, RAM, Ephemeral Storage | Обязательные для указания; влияют на планирование |
| **Extended Resources** | `nvidia.com/gpu`, SR-IOV, HugePages | Объявляются через Device Plugins или DRA |
| **Ports** | `hostPort`, `containerPort` | Проверяются на конфликт на одном узле |

**Важно:** Планировщик работает с `requests` (гарантированные ресурсы), а не с `limits` (максимум). Pod с `requests: cpu=1000m` требует 1 ядро, даже если `limits: cpu=2000m`.

### Ограничения планирования (Constraints)

#### Affinity / Anti-Affinity
*   **Node Affinity:** Требования к меткам узлов (`nodeSelector`, `requiredDuringScheduling...`)
*   **Pod Affinity:** Требования к совместному размещению с другими Pod (например, `app=frontend` рядом с `app=backend`)
*   **Pod Anti-Affinity:** Требования к раздельному размещению (например, не все поды в одной зоне)

#### Taints and Tolerations
*   **Taints:** Применяются к узлам, отталкивают Pod
*   **Tolerations:** Указываются в Pod, разрешают планирование на узлы с соответствующими taints
*   **Эффекты:** `NoSchedule` (блокирует новые), `PreferNoSchedule` (мягкий), `NoExecute` (эвикция существующих)

#### Topology Spread Constraints
*   **maxSkew:** Максимальная разница количества Pod между доменами
*   **topologyKey:** Ключ метки для определения домена (`topology.kubernetes.io/zone`, `kubernetes.io/hostname`)
*   **whenUnsatisfiable:** `DoNotSchedule` (блокирует) или `ScheduleAnyway` (планирует с нарушением)
*   **minDomains:** Минимальное количество доменов (Beta v1.25+)

#### Scheduler Name
Если Pod использует нестандартный планировщик (`spec.schedulerName`), стандартный `kube-scheduler` его игнорирует. Под остается в `Pending` без событий ошибок.

### Зависимости хранилища (Storage)

#### Volume Binding Modes
*   **Immediate:** PV создается сразу при создании PVC. Риск: PV может быть создан на узле A, а планировщик позже решит запустить Pod на узле B.
*   **WaitForFirstConsumer:** PV создается только после назначения Pod на узел. Гарантирует совместимость зон хранения и вычислений.

#### Типичные ошибки привязки
*   **Unbound PVC:** Отсутствие доступных PV, соответствующих требованиям PVC (размер, StorageClass, AccessMode).
*   **Zonal Mismatch:** PVC требует хранилище в зоне A, но все подходящие узлы в зоне B.
*   **WaitForFirstConsumer deadlock:** Pod не может быть запланирован из-за других ограничений, PVC не привязывается.

### Приоритеты и вытеснение (Preemption)

#### PriorityClass
*   **system-cluster-critical** (2000000000) — системные компоненты
*   **system-node-critical** (2000001000) — критические узловые сервисы
*   **Кастомные:** Пользовательские классы с значениями 0-1000000000

#### Механизм вытеснения
1.  Pod с высоким приоритетом не может быть запланирован (все узлы заняты)
2.  Планировщик ищет Pod с более низким приоритетом на узлах
3.  Проверяет PDB (по умолчанию **игнорирует** PDB!)
4.  Удаляет жертв и назначает узел для нового Pod

#### Asynchronous Preemption (Beta v1.33)
С включенным feature gate `SchedulerAsyncPreemption` удаление жертв происходит асинхронно после Bind, что ускоряет назначение.

### Cluster Autoscaler (CA)

#### Масштабирование вверх (Scale-Up)
*   **Триггер:** Только Pod в статусе `Pending` с причиной `Unschedulable`
*   **Процесс:** Сканирование (10с) → Симуляция логики планировщика → Запрос Cloud API → Ожидание 3-10 минут
*   **Ограничения:** Группы узлов могут иметь лимиты (квоты провайдера)

#### Масштабирование вниз (Scale-Down)
*   **Кандидат:** Узел с использованием <50%, все Pod могут быть эвиктированы, узел не нужен >10 минут
*   **Блокировка эвикции:** `safe-to-evict: false` аннотация, emptyDir/hostPath, PDB, системные Pod без PDB

---

## Практические сценарии

### Сценарий 1: Под не назначается на узел (`Node: <none>`)
Диагностика фокусируется на **событиях (Events)**.
*   **Действие:** `kubectl describe pod <name>` → Секция `Events`.
*   **Типовые сообщения:**
    *   `FailedScheduling` — все узлы отфильтрованы
    *   `SchedulingGated` — заблокирован Scheduling Gates
    *   `0/5 nodes are available: 2 Insufficient cpu, 3 had taint...` — конкретные причины
*   **Инструмент:** `kubectl describe quota -n <namespace>` для проверки лимитов Namespace.

### Сценарий 2: Под назначен, но "висит" (`Node: node-1`)
Диагностика фокусируется на **условиях (Conditions)** и **статусах контейнеров**.
*   **Действие:** `kubectl get pod <name> -o yaml` → Секция `status`.
*   **Типовые причины:**
    *   `FailedMount` — ошибки монтирования томов (PVC не Bound, таймауты)
    *   `ContainerCreating` — медленная сеть при скачивании образа
    *   Init-контейнеры в состоянии `Error` или `Waiting`

### Сценарий 3: Дефицит ресурсов (Insufficient cpu/memory)
*   **Симптом:** `0/X nodes are available: Y Insufficient cpu`
*   **Диагностика:**
    ```bash
    # Проверка ресурсов узлов
    kubectl describe nodes | grep -A 5 "Allocated resources"
    # → CPU (cores)   4500m / 8000m
    # → Memory (Gi)   12Gi / 32Gi
    ```
*   **Решения:**
    *   Уменьшить `requests` Pod
    *   Добавить узлы (manually или через CA)
    *   Проверить ResourceQuota в Namespace

### Сценарий 4: Taints/Tolerations не совпадают
*   **Симптом:** `0/X nodes are available: Y had taint {node-role.kubernetes.io/control-plane: }, that pod didn't tolerate`
*   **Диагностика:**
    ```bash
    # Проверка taints на узлах
    kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, taints: .spec.taints}'
    # → {"name":"master-1","taints":[{"key":"node-role.kubernetes.io/control-plane","effect":"NoSchedule"}]}
    ```
*   **Решения:**
    *   Добавить `tolerations` в Pod
    *   Использовать `nodeSelector` или `nodeAffinity` для выбора других узлов
    *   Удалить taint (если допустимо)

### Сценарий 5: PVC не привязывается (Volume Binding)
*   **Симптом:** `Waiting for a volume to be created, either by "external provisioner" or "local provisioner"`
*   **Диагностика:**
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
*   **Решения:**
    *   Убедиться, что StorageClass существует и provisioner работает
    *   Проверить `volumeBindingMode` (`Immediate` vs `WaitForFirstConsumer`)
    *   Для `WaitForFirstConsumer`: убедиться, что Pod может быть запланирован

### Сценарий 6: Scheduling Gates блокируют планирование
*   **Симптом:** `SchedulingGated` в статусе Pod
*   **Диагностика:**
    ```bash
    # Проверка gates
    kubectl get pod <pod-name> -o jsonpath='{.spec.schedulingGates}'
    # → [{"gateName":"example.com/data-ready"}]

    # Проверка статуса
    kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="PodScheduled")]}'
    # → {"type":"PodScheduled","status":"False","reason":"SchedulingGated"}
    ```
*   **Решения:**
    *   Проверить логи контроллера, установившего gates
    *   Убедиться, что gate удаляется после выполнения условия
    *   Временно: удалить Pod и пересоздать без gates (для отладки)

### Сценарий 7: Topology Spread Constraints конфликтуют
*   **Симптом:** `0/X nodes are available: Y didn't match topology spread constraints`
*   **Диагностика:**
    ```bash
    # Проверка распределения по зонам
    kubectl get pods -l app=my-app -o custom-columns=NAME:.metadata.name,NODE:.spec.nodeName,ZONE:.metadata.labels.topology\.kubernetes\.io/zone
    # → NAME           NODE      ZONE
    # → my-app-abc     node-1    zone-a
    # → my-app-def     node-2    zone-b
    ```
*   **Решения:**
    *   Увеличить `maxSkew` (например, с 1 до 2)
    *   Использовать `whenUnsatisfiable: ScheduleAnyway` вместо `DoNotSchedule`
    *   Добавить `matchLabelKeys: [pod-template-hash]` для Deployments

---

## Лучшие практики

### Профилактика Pending

1.  **Ресурсы:** Всегда указывайте `requests` для CPU и memory. Используйте `kubectl top pods` для оценки реального потребления.
2.  **Taints:** Для критических сервисов добавляйте `tolerations` и `nodeAffinity`. Для системных Pod используйте `PriorityClass` выше 2000000000.
3.  **Хранилище:** Используйте `volumeBindingMode: WaitForFirstConsumer` для зональных дисков. Проверяйте доступность StorageClass перед созданием PVC.
4.  **Topology Spread:** Всегда добавляйте `matchLabelKeys: [pod-template-hash]` для Deployments с Rolling Update (Beta v1.27+, GA v1.31).
5.  **PriorityClass:** Создайте иерархию классов приоритета для критических сервисов и временных задач.

### Диагностика Pending

1.  **Начните с `kubectl describe pod`:** Секция `Events` содержит причину.
2.  **Проверьте квоты:** `kubectl describe quota -n <namespace>`
3.  **Проверьте узлы:** `kubectl describe nodes | grep -A 5 "Allocated resources"`
4.  **Проверьте taints:** `kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, taints: .spec.taints}'`
5.  **Проверьте PDB:** `kubectl get pdb -A`

### Быстрое восстановление

1.  **Ресурсы:** Уменьшите `requests` или добавьте узлы
2.  **Taints:** Добавьте `tolerations` или выберите другие узлы через `nodeSelector`
3.  **Хранилище:** Проверьте provisioner и `volumeBindingMode`
4.  **Topology Spread:** Временно используйте `ScheduleAnyway` или увеличьте `maxSkew`

---

## Граничные случаи и известные ограничения

1.  **ResourceQuota vs LimitRange:** ResourceQuota проверяется на уровне Namespace, LimitRange — на уровне Pod. Оба могут блокировать создание.
2.  **Preemption игнорирует PDB:** По умолчанию вытеснение не проверяет PDB. С Kubernetes 1.21+ настраивается через feature gate `PreferNominatedNodeWithPDB`.
3.  **CA не учитывает Scheduling Gates:** Cluster Autoscaler не масштабирует кластер для Pod с Scheduling Gates.
4.  **Static Pods:** Pod, созданные kubelet напрямую (без API-сервера), не обрабатываются планировщиком.
5.  **DaemonSet:** Автоматически добавляет `tolerations` для `node.kubernetes.io/unschedulable:NoSchedule`.
6.  **StatefulSet:** PVC создаются до Pod и должны перейти в `Bound` перед запуском.
7.  **MatchLabelKeys + StatefulSet:** `matchLabelKeys` не работает с StatefulSet (уникальные имена Pod).

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

### Диагностика
- **[Диагностика Pending-статуса](./diagnostics.md)** — алгоритмы и команды для глубокой диагностики.
- **[Продвинутые темы](./advanced_topics.md)** — Scheduling Gates, DRA, Queuing Hints и мониторинг.

### Планирование
- **[Kube-scheduler — архитектура](../../../Concepts/kube_scheduler.md)** — как работают внутренние плагины.
- **[Affinity и Anti-Affinity](../../Scheduling/affinity.md)** — Node Affinity, Pod Affinity, Topology Spread.
- **[Taints и Tolerations](../../Scheduling/taints_and_tolerations.md)** — механизм изоляции узлов.
- **[PriorityClass — приоритеты](../../../Concepts/priorityclass.md)** — очереди и механизмы вытеснения.

### Хранилище
- **[PV и PVC](../../Storage/pv_and_pvc.md)** — привязка томов и динамический провижининг.

### Автомасштабирование
- **[Cluster Autoscaler — детальный обзор](../../Autoscaling/cluster_autoscaler_detailed.md)** — логика Scale-Up/Down.
- **[PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md)** — защита доступности при disruptions.

### Жизненный цикл
- **[Жизненный цикл Pod](../../Base/Pod/pod_lifecycle_and_state.md)** — глубокий разбор состояний и переходов.
- **[Распространенные случаи](./common_cases_and_solutions.md)** — практические решения по CPU, RAM и PVC.
