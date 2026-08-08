# Выселение подов: Блокировки PDB и Taint-based Eviction

## Определения

**PDB-blocked Eviction (Блокировка по PDB)** — состояние, при котором объект `PodDisruptionBudget` препятствует удалению пода через Eviction API. Это происходит при "добровольных" прерываниях (voluntary disruptions), таких как `kubectl drain` или Rolling Update, когда удаление пода нарушит заданный порог доступности (`minAvailable` или `maxUnavailable`).

**Taint-based Eviction (Выселение на основе Taints)** — автоматический процесс удаления подов с узла при добавлении taint с эффектом `NoExecute`. В отличие от PDB, этот механизм предназначен для "вынужденных" прерываний (involuntary disruptions) и срабатывает при потере узлом работоспособности.

**Eviction API** — часть Kubernetes API (`policy/v1`), используемая для безопасного удаления подов. Запрос к Eviction API возвращает ошибку `429 Too Many Requests`, если бюджет PDB не позволяет выполнить операцию.

**DisruptionTarget** — диагностическое условие (condition) в статусе пода (GA в K8s 1.31), которое фиксирует причину инициированного удаления пода (например, `EvictionByEvictionAPI`).

## Основные концепции

### Сравнение механизмов выселения

| Характеристика | Блокировка по PDB | Taint-based Eviction |
|:---|:---|:---|
| **Инициатор** | `kubectl drain` /rolling update | `NodeLifecycleController` (авто) |
| **Уважает PDB** | Да | **Нет** |
| **Результат при конфликте** | Операция `drain` блокируется | Под удаляется безусловно |
| **Сообщение в событиях** | `DisruptionBudgetExceeded` | `TaintManagerEviction` |
| **Причина** | Плановое обслуживание | Сбой узла (`NotReady`, `Unreachable`) |
| **Основной параметр** | `minAvailable` / `maxUnavailable` | `tolerationSeconds` |

### Механика работы Eviction API

При вызове Eviction API (который лежит в основе `kubectl drain`) выполняются следующие шаги:
1.  **Поиск PDB:** API-сервер идентифицирует все PDB, соответствующие меткам пода.
2.  **Валидация:** Проверяется `status.disruptionsAllowed` в объекте PDB.
3.  **Отказ:** Если `disruptionsAllowed: 0`, возвращается ошибка `429`. Клиент (например, `kubectl`) должен повторить попытку позже.
4.  **Удаление:** Если бюджет позволяет, под удаляется так же, как при `kubectl delete pod`.

### Политика выселения нездоровых подов (Kubernetes 1.30+)

Поле `spec.unhealthyPodEvictionPolicy` в PDB позволяет избежать ситуации, когда "зависшие" поды (например, в `CrashLoopBackOff`) блокируют обслуживание узла:
- **`IfHealthyBudget`** (по умолчанию): Нездоровые поды выселяются только если соблюден бюджет для здоровых реплик. Если бюджет уже на пределе, нездоровый под останется на узле, блокируя `drain`.
- **`AlwaysAllow`**: Нездоровые поды выселяются всегда, даже если бюджет нарушен. Это позволяет очистить узел от проблемных нагрузок и завершить обслуживание.

### Условия DisruptionTarget (Kubernetes 1.31+)

В Kubernetes 1.31 условие `DisruptionTarget` стало GA. Оно позволяет точно определить, *почему* под был удален:

| Reason | Описание |
|:---|:---|
| **`EvictionByEvictionAPI`** | Выселение через `drain` или Descheduler (учитывает PDB). |
| **`DeletionByTaintManager`** | Удаление из-за появления taint `NoExecute` (игнорирует PDB). |
| **`PreemptionByKubeScheduler`** | Вытеснение более приоритетным подом. |
| **`EvictionByKubelet`** | Выселение из-за Resource Pressure (Disk/Memory). |

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
2.  Проверьте текущее состояние (ищите `ALLOWED DISRUCTIONS: 0`):
    ```bash
    kubectl describe pdb <pdb-name>
    ```

**Решение:**
- **Масштабирование:** Временно увеличьте `replicas` в контроллере (Deployment/StatefulSet).
- **Корректировка PDB:** Измените `minAvailable` на меньшее значение или используйте проценты (`minAvailable: 50%`).
- **Unhealthy Policy:** Для K8s 1.30+ установите `unhealthyPodEvictionPolicy: AlwaysAllow`.
- **Force:** Прямое удаление пода (`kubectl delete pod`) проигнорирует PDB и Eviction API.

### Сценарий 2: Автоматическое выселение при сбое узла (NoExecute)

**Симптом:**
Узел перешел в `NotReady`. По истечении времени ожидания поды переходят в `Terminating` и пересоздаются на других узлах.

**Диагностика:**
1.  Проверьте taints на узле:
    ```bash
    kubectl describe node <node-name> | grep Taints
    # → node.kubernetes.io/unreachable:NoExecute
    ```
2.  Проверьте настройки в поде:
    ```bash
    kubectl get pod <pod-name> -o jsonpath='{.spec.tolerations}'
    ```

**Техническая деталь:**
По умолчанию `tolerationSeconds` для `not-ready` и `unreachable` равен **300 секундам** (5 минут). Для критичных баз данных (StatefulSet) рекомендуется увеличивать это время, чтобы избежать лишних переездов при кратковременных сбоях.

### Сценарий 3: Ручное выселение в обход PDB через taints

Если нужно очистить узел, а PDB настроен некорректно и блокирует API, можно использовать эффект `NoExecute` вручную.

```bash
# Наложение taint, который спровоцирует выселение всех подов без toleration
kubectl taint node <node-name> manual-eviction=true:NoExecute
```

**ПРЕДУПРЕЖДЕНИЕ (StatefulSet):**
Для `StatefulSet` принудительное выселение при недоступном узле несет риск **split-brain**. Если старый узел на самом деле жив, но отрезан сетью, Control Plane может запустить вторую копию пода на другом узле, что приведет к повреждению данных при использовании общего хранилища.

## Дополнительная информация

### Сравнение поведения при разных типах прерываний

| Аспект | Добровольные (drain/update) | Принудительные (taints/pressure) |
|:---|:---|:---|
| **Учет PDB** | Да | Нет |
| **API** | Eviction API | Garbage Collector / TaintManager |
| **Сигнал** | SIGTERM | SIGTERM (Taints) / SIGKILL (Hard Pressure) |
| **Статус в API** | Под удаляется/пересоздается | Под может остаться в `Failed (Evicted)` |

### Смотрите также

- **[Подробный разбор Pod Disruption Budget (PDB)](../../../Autoscaling/pod_disruption_budget.md)** — параметры конфигурации.
- **[Taints и Tolerations](../../../Scheduling/taints_and_tolerations.md)** — управление размещением.
- **[Диагностика выселения подов](./diagnostics.md)** — поиск первопричин.
- **[QoS и выселение](./qos_and_eviction.md)** — приоритеты при нехватке ресурсов.
