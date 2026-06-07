# Выселение подов: Блокировки PDB и Taint-based Eviction

## Определения

**PDB-blocked Eviction (Блокировка по PDB)** — ситуация, при которой объект PodDisruptionBudget препятствует выселению пода через Eviction API (например, при выполнении `kubectl drain` или Rolling Update). В этом случае под остается на узле, а операция выселения завершается с ошибкой.

**Taint-based Eviction (Выселение на основе Taints)** — автоматический процесс удаления подов с узла при добавлении taint с эффектом `NoExecute`. Это происходит при потере готовности узла или ручном вводе ограничений администратором.

**NoExecute** — эффект taint, инициирующий немедленное или отложенное (через `tolerationSeconds`) выселение всех подов, не имеющих соответствующего toleration.

## Основные концепции

### Сравнение механизмов выселения без учета ресурсов

В отличие от выселения при нехватке ресурсов (Memory/Disk Pressure), данные механизмы управляются логикой доступности или административными правилами.

| Характеристика | Блокировка по PDB | Taint-based Eviction |
|----------------|-------------------|----------------------|
| **Инициатор** | `kubectl drain` / rollout | Control Plane (автоматически) |
| **Результат** | Выселение **блокируется** | Выселение **происходит** |
| **Сообщение в событиях** | `violates PDB` | `Marking for deletion Pod` |
| **Причина** | Нарушение лимита доступности | Наличие taint `NoExecute` |
| **Автоматизация** | Только при внешнем запросе | Постоянный мониторинг состояния |
| **Решение** | Изменение PDB или масштабирование | Добавление toleration или ремонт узла |

### Взаимодействие с Eviction API

PDB (Pod Disruption Budget) защищает поды **только** при использовании Eviction API. Подробное описание параметров PDB доступно в файле **[Бюджет прерывания подов](../../../Autoscaling/pod_disruption_budget.md)**.

Механизм проверки:

1. Выполняется запрос к Eviction API (например, через `drain`).
2. API-сервер проверяет текущее количество здоровых реплик.
3. Если выселение нарушит `minAvailable` или `maxUnavailable`, запрос отклоняется с ошибкой `429 Too Many Requests`.

### Стандартные Taints и задержка выселения

Kubernetes автоматически накладывает taints при проблемах с узлом. По умолчанию подам дается 300 секунд (5 минут) до начала выселения при статусах `NotReady` или `Unreachable`. Подробности механизмов описаны в **[Taints и Tolerations](../../../Scheduling/taints_and_tolerations.md)**.

## Практические сценарии

### Сценарий 1: drain блокируется PDB

**Симптом:**
Команда `kubectl drain` останавливается, и в терминале появляется ошибка:
`error: cannot evict pod as it would violate the pod's disruption budget`.

**Диагностика:**

1. Проверьте состояние PDB:

   ```bash
   kubectl get pdb -A
   kubectl describe pdb <pdb-name>
   ```

2. Найдите события блокировки:

   ```bash
   kubectl get events --field-selector reason=DisruptionBudgetExceeded
   ```

**Решение:**

- Добавьте реплики в Deployment/StatefulSet, чтобы создать "запас" для выселения.
- Временно отредактируйте PDB, увеличив `maxUnavailable`.
- Если обслуживание критично, удалите PDB и восстановите его после завершения работ.

### Сценарий 2: Автоматическое выселение при недоступности узла

**Симптом:**
Под переходит в статус `Terminating` или исчезает с узла, а затем появляется статус `Evicted`.

**Диагностика:**

1. Проверьте taints узла:

   ```bash
   kubectl describe node <node-name> | grep Taints
   ```

2. Проверьте tolerations пода:

   ```bash
   kubectl get pod <pod-name> -o jsonpath='{.spec.tolerations}'
   ```

**Решение:**
Если выселение нежелательно при кратковременных сбоях сети, увеличьте `tolerationSeconds` в спецификации пода для ключей `node.kubernetes.io/unreachable` и `node.kubernetes.io/not-ready`.

### Сценарий 3: Ручное выселение через taints

Для вывода подов с узла без использования `kubectl drain` (например, если нужно обойти PDB):

```bash
# Наложение taint NoExecute
kubectl taint node <node-name> maintenance=planned:NoExecute

# Проверка очистки узла
kubectl get pods --field-selector spec.nodeName=<node-name>

# Снятие taint после работ
kubectl taint node <node-name> maintenance=planned-
```

## Дополнительная информация

### Сводная таблица механизмов выселения

| Механизм | Инициатор | Уважает PDB | Grace Period |
|----------|-----------|-------------|--------------|
| **Drain (Eviction API)** | Пользователь | Да | `terminationGracePeriodSeconds` |
| **Node Pressure** | Kubelet | Нет | `evictionMaxPodGracePeriod` |
| **Taint-based NoExecute** | Control Plane | Нет | `tolerationSeconds` (300с по умолчанию) |
| **kubectl delete** | Пользователь | Нет | `terminationGracePeriodSeconds` |

### Рекомендации по настройке

- **Для критичных сервисов:** Всегда настраивайте PDB, но избегайте `maxUnavailable: 0`, так как это полностью заблокирует обслуживание узлов.
- **Для StatefulSet:** Используйте `maxUnavailable: 1`, чтобы гарантировать последовательное выселение реплик.
- **Мониторинг:** Настройте алерты на событие `DisruptionBudgetExceeded` для проактивного выявления проблем с обслуживанием.

### Смотрите также

- [Диагностика выселенных подов](./diagnostics.md) — общий алгоритм поиска причин.
- [Обслуживание узлов: Cordon и Drain](../../../Operations/node_maintenance.md) — основной источник по процедурам обслуживания.
- [Бюджет прерывания подов (PDB)](../../../Autoscaling/pod_disruption_budget.md) — подробное описание и параметры.
- [Taints и Tolerations](../../../Scheduling/taints_and_tolerations.md) — механика работы и стандартные значения.
