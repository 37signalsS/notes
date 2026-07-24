# Выселение подов: Блокировки PDB и Taint-based Eviction

## Определения

**PDB-blocked Eviction (Блокировка по PDB)** — состояние, при котором объект `PodDisruptionBudget` препятствует удалению пода через Eviction API. Это происходит при добровольных прерываниях (например, `kubectl drain`), когда удаление пода нарушит заданный порог доступности (`minAvailable` или `maxUnavailable`).

**Taint-based Eviction (Выселение на основе Taints)** — автоматический процесс удаления подов с узла при добавлении taint с эффектом `NoExecute`. Kubernetes использует этот механизм для реакции на сбои узлов (`NotReady`, `Unreachable`) или при ручном вводе ограничений.

**Eviction API** — программный интерфейс, используемый для "вежливого" удаления подов. В отличие от прямого удаления (`delete`), он учитывает PDB и возвращает ошибку `429 Too Many Requests`, если бюджет нарушен.

**DisruptionTarget** — условие (condition), добавляемое в статус пода в Kubernetes 1.31 (GA), которое указывает на причину выселения (например, `EvictionByEvictionAPI` или `DeletionByTaintManager`).

## Основные концепции

### Сравнение механизмов выселения

В отличие от выселения при нехватке ресурсов (Memory/Disk Pressure), данные механизмы управляются логикой доступности или административными правилами.

| Характеристика | Блокировка по PDB | Taint-based Eviction |
|:---|:---|:---|
| **Инициатор** | `kubectl drain` / Rolling Update | Control Plane (автоматически) |
| **Уважает PDB** | Да | **Нет** |
| **Результат при конфликте** | Операция блокируется | Под удаляется немедленно |
| **Сообщение в событиях** | `DisruptionBudgetExceeded` | `TaintManagerEviction` |
| **Причина** | Плановое обслуживание | Сбой узла или ручной taint |
| **Основной параметр** | `minAvailable` / `maxUnavailable` | `tolerationSeconds` |

### Политика выселения нездоровых подов (Kubernetes 1.30+)

Поле `spec.unhealthyPodEvictionPolicy` позволяет управлять поведением PDB для подов в состоянии `CrashLoopBackOff` или не прошедших Readiness Probe:

- **`IfHealthyBudget` (по умолчанию)** — нездоровые поды выселяются только если соблюдается бюджет для здоровых. Это может заблокировать `drain`, если в системе много проблемных подов.
- **`AlwaysAllow`** — нездоровые поды выселяются всегда, даже если бюджет нарушен. Рекомендуется для ускорения обслуживания узлов.

### Условия DisruptionTarget (Kubernetes 1.31+)

Для точной диагностики причины выселения следует проверять `status.conditions` пода:

```yaml
status:
  conditions:
    - type: DisruptionTarget
      status: "True"
      reason: EvictionByEvictionAPI # Выселен через drain
```

## Практические сценарии

### Сценарий 1: drain блокируется PDB

**Симптом:**
Команда `kubectl drain` останавливается с ошибкой:
`error: cannot evict pod as it would violate the pod's disruption budget`.

**Диагностика:**
1. Проверьте состояние PDB:
   ```bash
   kubectl get pdb -A
   ```
2. Проверьте количество здоровых реплик в `status`:
   ```bash
   kubectl describe pdb <pdb-name>
   ```

**Решение:**
- **Масштабирование:** Увеличьте количество реплик в Deployment/StatefulSet.
- **Корректировка политики:** Если поды нездоровы, установите `spec.unhealthyPodEvictionPolicy: AlwaysAllow`.
- **Принудительное удаление:** Если обслуживание критично, удалите под напрямую (`kubectl delete pod`), что проигнорирует PDB.

### Сценарий 2: Автоматическое выселение при недоступности узла

**Симптом:**
Узел перешел в статус `NotReady`, и через 5 минут поды начали переходить в `Terminating` и пересоздаваться на других узлах.

**Диагностика:**
1. Проверьте taints узла:
   ```bash
   kubectl describe node <node-name> | grep Taints
   # → node.kubernetes.io/unreachable:NoExecute
   ```
2. Проверьте `tolerationSeconds` пода:
   ```bash
   kubectl get pod <pod-name> -o jsonpath='{.spec.tolerations}'
   ```

**Решение:**
Для критичных приложений увеличьте `tolerationSeconds` до 600-900 (10-15 минут), чтобы избежать лишних переездов при кратковременных сбоях сети.

### Сценарий 3: Ручное выселение через taints (в обход PDB)

Если необходимо очистить узел, игнорируя PDB (например, если приложение "зависло" и блокирует `drain`), можно использовать taint:

```bash
# Наложение taint NoExecute
kubectl taint node <node-name> manual-eviction=true:NoExecute

# Очистка (после завершения работ)
kubectl taint node <node-name> manual-eviction-
```

**Предупреждение:** Для `StatefulSet` это может привести к запуску двух копий пода с одинаковым именем, если старый под на самом деле не завершился (проблема split-brain).

## Сводная таблица причин выселения

| Причина в DisruptionTarget | Описание | Что проверить |
|:---|:---|:---|
| **EvictionByEvictionAPI** | Выселение через API (drain) | PDB, бюджет доступности |
| **DeletionByTaintManager** | Выселение по taints (`NoExecute`) | Состояние узла, Tolerations |
| **PreemptionByKubeScheduler**| Вытеснение более приоритетным подом | `PriorityClass` |
| **EvictionByKubelet** | Нехватка ресурсов на узле | RAM/Disk Pressure |

## Смотрите также

- [Диагностика выселенных подов](./diagnostics.md) — поиск первопричин через события и метрики.
- [Бюджет прерывания подов (PDB)](../../../Autoscaling/pod_disruption_budget.md) — полная конфигурация параметров.
- [Taints и Tolerations](../../../Scheduling/taints_and_tolerations.md) — механизмы управления размещением.
