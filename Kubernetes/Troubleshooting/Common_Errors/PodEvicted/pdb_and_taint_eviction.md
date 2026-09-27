# Выселение подов: Блокировки PDB и Taint-based Eviction

## Определения

**PDB-blocked Eviction (Блокировка по PDB)** — состояние, при котором объект `PodDisruptionBudget` препятствует удалению пода через Eviction API. Это происходит при "добровольных" прерываниях (voluntary disruptions), таких как `kubectl drain` или Rolling Update, когда удаление пода нарушит заданный порог доступности (`minAvailable` или `maxUnavailable`).

**Taint-based Eviction (Выселение на основе Taints)** — автоматический процесс удаления подов с узла при добавлении taint с эффектом `NoExecute`. В отличие от PDB, этот механизм предназначен для "вынужденных" прерываний (involuntary disruptions) и срабатывает при потере узлом работоспособности.

**Eviction API** — часть Kubernetes API (`policy/v1`), используемая для безопасного удаления подов. Запрос к Eviction API возвращает ошибку `429 Too Many Requests`, если бюджет PDB не позволяет выполнить операцию.

**DisruptionTarget** — диагностическое условие (condition) в статусе пода (GA в K8s 1.31), которое фиксирует причину инициированного удаления пода (например, `EvictionByEvictionAPI`).

**`out-of-service` taint** — механизм Kubernetes (GA с K8s 1.31), позволяющий администратору пометить узел как находящийся "вне обслуживания". При наложении taint `node.kubernetes.io/out-of-service:NoExecute` все поды с соответствующим toleration удаляются **в обход PDB**, но при условии, что контроллер PotentiallyUnsafeNodeOps корректно завершает поды (с `terminationGracePeriodSeconds`).

**Node Lifecycle Controller** — компонент kube-controller-manager, который управляет taints на узлах. Он накладывает автоматические taints (`not-ready`, `unreachable`, `out-of-service`) и запускает таймеры выселения подов через `tolerationSeconds`.

## Основные концепты

### Сравнение механизмов выселения

| Характеристика | Блокировка по PDB | Taint-based Eviction | `out-of-service` taint |
|:---|:---|:---|:---|
| **Инициатор** | `kubectl drain` / rolling update | `NodeLifecycleController` (авто) | Администратор |
| **Уважает PDB** | Да | **Нет** | **Нет** (но безопасно) |
| **Результат при конфликте** | Операция `drain` блокируется | Под удаляется безусловно | Под удаляется после graceful shutdown |
| **Сообщение в событиях** | `DisruptionBudgetExceeded` | `TaintManagerEviction` | `EvictionByNodeController` |
| **Причина** | Плановое обслуживание | Сбой узла (`NotReady`, `Unreachable`) | Аварийное обслуживание |
| **Основной параметр** | `minAvailable` / `maxUnavailable` | `tolerationSeconds` | `tolerationSeconds` |
| **Риск split-brain** | Нет | Да (если узел жив) | Минимален (узел гарантированно недоступен) |

### Механика работы Eviction API

При вызове Eviction API (который лежит в основе `kubectl drain`) выполняются следующие шаги:
1.  **Поиск PDB:** API-сервер идентифицирует все PDB, соответствующие меткам пода.
2.  **Валидация:** Проверяется `status.disruptionsAllowed` в объекте PDB.
3.  **Отказ:** Если `disruptionsAllowed: 0`, возвращается ошибка `429`. Клиент (например, `kubectl`) должен повторить попытку позже.
4.  **Удаление:** Если бюджет позволяет, под удаляется так же, как при `kubectl delete pod`.

**Важно:** PDB проверяется только при запросе к Eviction API. Прямое удаление пода (`kubectl delete pod`) **полностью игнорирует PDB**. Однако `kubectl drain` всегда использует Eviction API, поэтому PDB блокирует drain.

### Правила расчета minAvailable / maxUnavailable

Kubernetes поддерживает два способа задания бюджета:

| Параметр | Тип значения | Формула расчета | Пример |
|:---|:---|:---|:---|
| `minAvailable` | Целое число или процент | `count(ready) >= minAvailable` | `minAvailable: 3` — минимум 3 пода должны быть ready |
| `maxUnavailable` | Целое число или процент | `count(unavailable) <= maxUnavailable` | `maxUnavailable: 1` — максимум 1 под может быть unavailable |

**Проценты:** Если `replicas: 5` и `maxUnavailable: "20%"`, то `maxUnavailable = 1` (20% от 5 = 1, округление вниз).

**Критические нюансы:**
*   Нельзя указать одновременно `minAvailable` и `maxUnavailable` — это ошибка валидации.
*   `minAvailable: 0` **не отключает PDB**. Он разрешает выселение всех подов, но PDB по-прежнему проверяется через Eviction API (всегда возвращает `disruptionsAllowed: maxUnavailable`).
*   `maxUnavailable: 1` — самый безопасный вариант для production: разрешает выселение только одного пода за раз.
*   Если подов меньше, чем `minAvailable`, ни один под не может быть выселен — drain застрянет навсегда.

### Политика выселения нездоровых подов (Kubernetes 1.30+)

Поле `spec.unhealthyPodEvictionPolicy` в PDB позволяет избежать ситуации, когда "зависшие" поды (например, в `CrashLoopBackOff`) блокируют обслуживание узла:
- **`IfHealthyBudget`** (по умолчанию): Нездоровые поды выселяются только если соблюден бюджет для здоровых реплик. Если бюджет уже на пределе, нездоровый под останется на узле, блокируя `drain`.
- **`AlwaysAllow`**: Нездоровые поды выселяются всегда, даже если бюджет нарушен. Это позволяет очистить узел от проблемных нагрузок и завершить обслуживание.

**Рекомендация для production:** Всегда устанавливайте `unhealthyPodEvictionPolicy: AlwaysAllow` для предотвращения deadlocks при обслуживании узлов.

### Условия DisruptionTarget (Kubernetes 1.31+)

В Kubernetes 1.31 условие `DisruptionTarget` стало GA. Оно позволяет точно определить, *почему* под был удален:

| Reason | Описание |
|:---|:---|
| **`EvictionByEvictionAPI`** | Выселение через `drain` или Descheduler (учитывает PDB). |
| **`DeletionByTaintManager`** | Удаление из-за появления taint `NoExecute` (игнорирует PDB). |
| **`PreemptionByKubeScheduler`** | Вытеснение более приоритетным подом. |
| **`EvictionByKubelet`** | Выселение из-за Resource Pressure (Disk/Memory). |

### Механизм работы Node Lifecycle Controller

Node Lifecycle Controller — компонент kube-controller-manager, отвечающий за управление taints и выселение подов:

1.  **Мониторинг:** Контроллер опрашивает статус узлов каждые `--node-monitor-grace-period` (по умолчанию 40с).
2.  **Tainting:** При потере связи контроллер накладывает `not-ready:NoExecute` или `unreachable:NoExecute`.
3.  **Таймеры:** Для каждого пода без toleration запускается индивидуальный таймер `tolerationSeconds` (по умолчанию 300с = 5 минут).
4.  **Выселение:** По истечении таймера под удаляется.

**Параметры Node Controller:**

| Параметр | По умолчанию | Описание |
|:---|:---|:---|
| `--node-monitor-grace-period` | 40s | Время до присвоения статуса `Unknown` |
| `--pod-eviction-timeout` | 5m | Интервал между попытками выселения (в современных версиях приоритет отдается логике `tolerationSeconds`) |
| `--terminated-pod-gc-threshold` | 12500 | Максимум завершенных подов перед запуском сборщика мусора |

### Taint flip-flopping (осцилляция)

Если `memory.available` осциллирует вокруг порога `evictionHard`, узел будет постоянно получать и сбрасывать taint `MemoryPressure`. Это вызывает:
*   Постоянное выселение и перепланирование подов.
*   Нестабильность сервисов и ложные срабатывания алертов.

**Решения:**
*   Увеличить `evictionSoftGracePeriod` (например, до 5 минут).
*   Установить `evictionMinimumReclaim` для создания буфера.
*   Увеличить `evictionHard` (например, с `memory.available<100Mi` до `memory.available<500Mi`).

### PDB и DaemonSet

DaemonSet имеет особую логику взаимодействия с PDB:
*   **Drain узла:** Когда `kubectl drain` удаляет DaemonSet-под, он использует Eviction API. PDB **не блокирует** удаление DaemonSet-подов, если на узле остается только один такой под (что типично).
*   **Autoscaling:** Cluster Autoscaler и Karpenter уважают PDB при удалении подов, но DaemonSet-поды не могут быть выселены, так как они не могут "переехать" на другой узел.

### PDB и Cluster Autoscaler

Cluster Autoscaler (CA) при scale-down проверяет PDB:
*   CA удаляет узлы, только если все поды на них могут быть безопасно выселены (с учетом PDB).
*   Если PDB блокирует выселение пода, CA не удалит узел, даже если он пуст除 этого пода.
*   CA не создает поды для восстановления PDB — это ответственность контроллера приложения.

**Критическое замечание:** Если узел переведен в `NotReady`, CA не может корректно вычислить PDB и может удалить узел без учета бюджета. В этом случае таймер `tolerationSeconds` (по умолчанию 300с) дает время на восстановление.

### PDB и Descheduler

Descheduler — инструмент для балансировки нагрузки между узлами. Он уважает PDB при удалении подов:
*   Descheduler проверяет `status.disruptionsAllowed` перед каждым удалением.
*   Если PDB блокирует выселение, descheduler пропускает этот под.
*   Descheduler может удалить нездоровые поды, если `unhealthyPodEvictionPolicy: AlwaysAllow`.

### PDB и Preemption

При вытеснении (preemption) планировщик проверяет PDB:
*   Если вытеснение пода нарушит PDB, планировщик попытается найти другой узел.
*   Если других узлов нет, под останется в `Pending`.
*   Это поведение можно отключить через feature gate `CheckNodeUnschedulable` (deprecated) или `SchedulerAsyncPreemption` (K8s 1.33+).

### PDB метрики и мониторинг

Встроенные метрики kube-controller-manager для мониторинга PDB:

```promql
# Количество PDB в кластере
pod_disruption_budgets

# Количество успешных синхронизаций PDB
pod_disruption_budgets_sync_total

# Ошибки синхронизации PDB
pod_disruption_budgets_sync_errors_total

# Количество подов, защищенных PDB
kube_poddisruptionbudget_status_desired_healthy

# Количество фактически здоровых подов
kube_poddisruptionbudget_status_current_healthy

# Количество подов, которые могут быть выселены
kube_poddisruptionbudget_status_disruptions_allowed
```

**Алерты Prometheus:**
```yaml
# PDB заблокирован
- alert: PDBBlocked
  expr: kube_poddisruptionbudget_status_disruptions_allowed == 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "PDB {{ $labels.poddisruptionbudget }} заблокирован"

# PDB близок к лимиту
- alert: PDBNearLimit
  expr: kube_poddisruptionbudget_status_current_healthy / kube_poddisruptionbudget_status_desired_healthy < 1.2
  for: 5m
  labels:
    severity: info
  annotations:
    summary: "PDB {{ $labels.poddisruptionbudget }} близок к лимиту"

# Ошибки синхронизации PDB
- alert: PDBSyncErrors
  expr: rate(pod_disruption_budgets_sync_errors_total[5m]) > 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Ошибки синхронизации PDB {{ $labels.poddisruptionbudget }}"
```

## Практические сценарии

### Сценарий 1: drain блокируется из-за PDB

**Симптом:**
Команда `kubectl drain <node>` останавливается и циклически выводит:
`error: cannot evict pod as it would violate the pod's disruption budget`.

**Диагностика:**
1.  Найдите заблокированный PDB:
    ```bash
    kubectl get pdb -A
    ```
2.  Проверьте текущее состояние (ищите `ALLOWED DISRUPTIONS: 0`):
    ```bash
    kubectl describe pdb <pdb-name>
    # → Current healthy: 3
    # → Desired healthy: 3
    # → Allowed disruptions: 0
    ```

**Решения (от быстрого к стратегическому):**

1.  **Увеличение replicas (быстрое):**
    ```bash
    kubectl scale deployment <name> --replicas=<current+2>
    kubectl drain <node> --ignore-daemonsets
    # После drain:
    kubectl scale deployment <name> --replicas=<original>
    ```

2.  **Корректировка PDB (среднее):**
    ```yaml
    apiVersion: policy/v1
    kind: PodDisruptionBudget
    metadata:
      name: my-pdb
    spec:
      minAvailable: 1  # Было 3
      selector:
        matchLabels:
          app: my-app
    ```

3.  **Unhealthy Policy (K8s 1.30+):**
    ```yaml
    spec:
      unhealthyPodEvictionPolicy: AlwaysAllow
    ```

4.  **Force (крайний случай):**
    ```bash
    kubectl delete pod <pod-name> --force --grace-period=0
    # Или через прямое удаление:
    kubectl delete pod <pod-name>
    ```

### Сценарий 2: Автоматическое выселение при сбое узла (NoExecute)

**Симптом:**
Узел перешел в `NotReady`. По истечении времени ожидания поды переходят в `Terminating` и пересоздаются на других узлах.

**Диагностика:**
1.  Проверьте taints на узле:
    ```bash
    kubectl describe node <node-name> | grep Taints
    # → node.kubernetes.io/unreachable:NoExecute
    # → node.kubernetes.io/not-ready:NoExecute
    ```
2.  Проверьте настройки в поде:
    ```bash
    kubectl get pod <pod-name> -o jsonpath='{.spec.tolerations}'
    ```
3.  Проверьте событие выселения:
    ```bash
    kubectl get events --field-selector reason=TaintManagerEviction
    ```

**Техническая деталь:**
По умолчанию `tolerationSeconds` для `not-ready` и `unreachable` равен **300 секундам** (5 минут). Для критичных баз данных (StatefulSet) рекомендуется увеличивать это время, чтобы избежать лишних переездов при кратковременных сбоях.

**Пример увеличения tolerationSeconds для StatefulSet:**
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  template:
    spec:
      tolerations:
      - key: "node.kubernetes.io/unreachable"
        operator: "Exists"
        effect: "NoExecute"
        tolerationSeconds: 900  # 15 минут
      - key: "node.kubernetes.io/not-ready"
        operator: "Exists"
        effect: "NoExecute"
        tolerationSeconds: 900
```

### Сценарий 3: Ручное выселение в обход PDB через taints

Если нужно очистить узел, а PDB настроен некорректно и блокирует API, можно использовать эффект `NoExecute` вручную.

```bash
# Наложение taint, который спровоцирует выселение всех подов без toleration
kubectl taint node <node-name> manual-eviction=true:NoExecute
```

**ПРЕДУПРЕЖДЕНИЕ (StatefulSet):**
Для `StatefulSet` принудительное выселение при недоступном узле несет риск **split-brain**. Если старый узел на самом деле жив, но отрезан сетью, Control Plane может запустить вторую копию пода на другом узле, что приведет к повреждению данных при использовании общего хранилища.

**Безопасный способ для StatefulSet:**
```bash
# 1. Пометьте узел как недоступный (cordon)
kubectl cordon <node-name>

# 2. Дождитесь завершения подов (или принудительно через 15 минут)
kubectl drain <node-name> --ignore-daemonsets --timeout=900s

# 3. Если drain застрял из-за PDB, удалите PDB
kubectl delete pdb <pdb-name>

# 4. Продолжите drain
kubectl drain <node-name> --ignore-daemonsets

# 5. Удалите taint manual-eviction
kubectl taint node <node-name> manual-eviction=true:NoExecute-
```

### Сценарий 4: Использование out-of-service taint (K8s 1.24+)

Для безопасной эвакуации подов с заведомо мертвого узла:

```bash
# 1. Пометьте узел как "вне обслуживания"
kubectl taint node <node-name> node.kubernetes.io/out-of-service=disabled:NoExecute

# 2. Контроллер PotentiallyUnsafeNodeOps начнет выселение подов
#    с учетом terminationGracePeriodSeconds (в обход PDB)

# 3. После обслуживания снимите taint
kubectl taint node <node-name> node.kubernetes.io/out-of-service=disabled:NoExecute-
```

**Примечание:** Этот taint гарантирует, что узел действительно недоступен и не вызовет split-brain. Используйте только когда уверены, что узел не может работать.

### Сценарий 5: PDB deadlock при одновременных операциях

**Симптом:**
PDB блокирует drain, одновременно HPA масштабирует вниз, и ни одна операция не может завершиться.

**Диагностика:**
```bash
# Проверка PDB и их статуса
kubectl get pdb -A -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,ALLOWED:.status.disruptionsAllowed,DESIRED:.status.desiredHealthy,CURRENT:.status.currentHealthy"

# Проверка pending evictions
kubectl get events --field-selector reason=EvictionFailed

# Проверка HPA
kubectl get hpa -A
```

**Решение:**
1.  Временно остановите HPA: `kubectl delete hpa <name>`
2.  Увеличьте replicas: `kubectl scale deployment <name> --replicas=<current+2>`
3.  Выполните drain: `kubectl drain <node>`
4.  Восстановите HPA и replicas

### Сценарий 6: Мониторинг PDB и алерты

```bash
# Все PDB и их статус
kubectl get pdb -A -o yaml | grep -E "(name:|disruptionsAllowed:|desiredHealthy:|currentHealthy:)"

# PDB с disruptionsAllowed=0
kubectl get pdb -A -o json | jq '.items[] | select(.status.disruptionsAllowed == 0) | {name: .metadata.name, namespace: .metadata.namespace, desired: .status.desiredHealthy, current: .status.currentHealthy}'

# Поды, защищенные PDB
kubectl get pods -A -o json | jq '[.items[] | select(.metadata.ownerReferences[]? | select(.kind=="ReplicaSet" or .kind=="StatefulSet")) | .metadata.name] | length'
```

**PromQL для мониторинга:**
```promql
# Количество PDB в каждом namespace
count by (namespace) (kube_poddisruptionbudget_info)

# PDB, которые могут быть выселены (disruptionsAllowed > 0)
kube_poddisruptionbudget_status_disruptions_allowed > 0

# PDB, которые заблокированы (disruptionsAllowed == 0)
kube_poddisruptionbudget_status_disruptions_allowed == 0

# Процент здоровых подов по PDB
kube_poddisruptionbudget_status_current_healthy / kube_poddisruptionbudget_status_desired_healthy * 100
```

## Дополнительная информация

### Сравнение поведения при разных типах прерываний

| Аспект | Добровольные (drain/update) | Принудительные (taints/pressure) | out-of-service |
|:---|:---|:---|:---|
| **Учет PDB** | Да | Нет | Нет |
| **API** | Eviction API | Garbage Collector / TaintManager | TaintManager |
| **Сигнал** | SIGTERM | SIGTERM (Taints) / SIGKILL (Hard Pressure) | SIGTERM |
| **Статус в API** | Под удаляется/пересоздается | Под может остаться в `Failed (Evicted)` | Под удаляется |
| **Split-brain** | Нет | Да (если узел жив) | Минимален |
| **terminationGracePeriodSeconds** | Учитывается | Учитывается (Taints) | Учитывается |
| **Таймер** | Нет (мгновенно) | `tolerationSeconds` | `tolerationSeconds` |

### Типичные ошибки при настройке PDB

| Ошибка | Последствие | Решение |
|:---|:---|:---|
| `minAvailable: 100%` | Ни один под не может быть вылен — drain застрянет | Используйте `maxUnavailable: 1` или `minAvailable: N-1` |
| `minAvailable` больше текущего count реплик | PDB всегда заблокирован | Убедитесь, что `minAvailable <= replicas` |
| Нет PDB для critical сервисов | Все реплики могут быть удалены одновременно | Создайте PDB с `maxUnavailable: 1` |
| `unhealthyPodEvictionPolicy` не установлен | Нездоровые поды блокируют drain | Установите `AlwaysAllow` для K8s 1.30+ |
| PDB для DaemonSet | Бессмысленно (на узле только один под) | Не создавайте PDB для DaemonSet |
| Игнорирование split-brain | Повреждение данных StatefulSet | Используйте `out-of-service` taint |

### Типичные ошибки при настройке Tolerations

| Ошибка | Последствие | Решение |
|:---|:---|:---|
| `tolerationSeconds: null` для production подов | Под никогда не выселяется с проблемного узла | Установите конкретное значение (300-900) |
| Слишком малое `tolerationSeconds` (<30s) | Частое выселение при кратковременных сбоях | Увеличьте до 300+ секунд |
| Слишком большое `tolerationSeconds` (>1800s) | Долгое ожидание при реальном отказе узла | Используйте 300-900 для大多数工作loads |
| Нет toleration для critical taints | Под выселится при любом сбое узла | Добавьте toleration с разумным timeout |

### Рекомендации по настройке для production

1.  **PDB для каждого сервиса:** Всегда создавайте PDB для production-сервисов, даже если реплик всего 2.
2.  **maxUnavailable: 1:** Для大多数 сервисов безопаснее использовать `maxUnavailable: 1`, чем `minAvailable`.
3.  **unhealthyPodEvictionPolicy:** Устанавливайте `AlwaysAllow` для K8s 1.30+.
4.  **tolerationSeconds:** Для Stateless — 30-60с. Для StatefulSet — 300-900с. Для DaemonSet — `null` (никогда).
5.  **out-of-service taint:** Используйте только когда уверены, что узел мертв и не может восстановиться.
6.  **Мониторинг:** Настройте алерты на `disruptionsAllowed == 0` для критических PDB.
7.  **Регулярные учения:** Проводите учения по обслуживанию узлов для проверки корректности PDB.

### Смотрите также

- **[Подробный разбор Pod Disruption Budget (PDB)](../../../Autoscaling/pod_disruption_budget.md)** — параметры конфигурации, edge cases, метрики Prometheus.
- **[Taints и Tolerations](../../../Scheduling/taints_and_tolerations.md)** — управление размещением, DaemonSet, Node Affinity.
- **[Недоступность узла: Taints и выселение](../../../Troubleshooting/Common_Errors/NodeUnavailability/taints_and_eviction.md)** — глубокий разбор аварийных сценариев.
- **[Диагностика выселения подов](./diagnostics.md)** — поиск первопричин.
- **[QoS и выселение](./qos_and_eviction.md)** — приоритеты при нехватке ресурсов.
- **[Профилактика выселения](./prevention.md)** — архитектурные меры защиты.
- **[PriorityClass и вытеснение](../../../Concepts/priorityclass.md)** — различия между Preemption и Eviction.
- **[Cluster Autoscaler](../../../Autoscaling/cluster_autoscaler_detailed.md)** — взаимодействие с PDB при scale-down.
- **[Descheduler](../../../Autoscaling/descheduler.md)** — автоматическое перераспределение подов.
- **[HPA: Продвинутые конфликты с PDB](../../../Autoscaling/HPA/hpa_advanced.md#взаимодействие-hpa-с-resourcequota-и-limitrange)** — HPA scale-down vs PDB, deadlock-сценарии.
- **[HPA Troubleshooting: Сценарий 6](../hpa_troubleshooting.md#сценарий-6-конфликт-hpa-и-poddisruptionbudget-pdb)** — практический разбор конфликта HPA и PDB.
