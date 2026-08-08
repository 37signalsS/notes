# Pod в состоянии `Pending`: Продвинутые темы

## Определения

**Продвинутая диагностика Pending** — глубокий анализ взаимодействия механизмов планирования, мониторинг состояния очереди планировщика и исследование специфических ограничений (Scheduling Gates, DRA, Topology Spread), блокирующих запуск подов в сложных или высоконагруженных инфраструктурных условиях.

**Scheduling Gates (врата планирования)** — механизм (GA v1.30), позволяющий удерживать под в состоянии `Pending` (статус `SchedulingGated`) до завершения внешних проверок (безопасность, квоты, подготовка данных). Планировщик полностью игнорирует такие поды, что снижает нагрузку на Control Plane.

**Queuing Hints** — оптимизация планировщика (Beta v1.32), позволяющая плагинам указывать, при каких именно изменениях в кластере (например, освобождение конкретного ресурса) стоит повторно пытаться запланировать под из очереди `Unschedulable`.

**Dynamic Resource Allocation (DRA)** — API для управления специализированными ресурсами (GPU, FPGA, NVMe) через `ResourceClaims` (Beta v1.32), заменяющее Device Plugins и позволяющее планировщику учитывать параметры ресурсов в структурированном виде.

---

## Основные концепции

### 1. Жизненный цикл планирования (Scheduling Framework)

Если под застрял в `Pending`, важно определить, на какой точке расширения (Extension Point) происходит задержка:

1.  **PreFilter / Scheduling Gates:** Проверка `.spec.schedulingGates`. Если не пусто — под не попадает в основной цикл планирования.
2.  **Filter (Predicates):** Последовательная проверка жестких ограничений:
    *   `NodeResourcesFit`: Наличие CPU/RAM/Ports.
    *   `Taints/Tolerations`: Соответствие допускам.
    *   `NodeAffinity`: Проверка `requiredDuringSchedulingIgnoredDuringExecution`.
    *   `Volume Restrictions`: Доступность PV в конкретной зоне (Zonal Availability).
3.  **PostFilter (Preemption):** Если узлы не найдены, запускается логика вытеснения. **Asynchronous Preemption (v1.32+)** позволяет удалять "жертв" асинхронно, ускоряя назначение высокоприоритетных подов.
4.  **Reserve / Permit:** Этап резервирования ресурсов. Если используется `Permit`, под может ожидать в состоянии `Pending` одобрения от внешнего плагина (например, для Gang Scheduling).

### 2. Продвинутые механизмы размещения

#### MatchLabelKeys (Beta v1.31)
Используется в `PodAffinity` и `TopologySpreadConstraints` для предотвращения тупиковых ситуаций (deadlocks) при Rolling Update. Позволяет новым подам учитывать распределение только своей версии (по ключу, например, `pod-template-hash`), игнорируя старые поды, которые скоро будут удалены.

#### Dynamic Resource Allocation (DRA)
В отличие от Device Plugins, DRA позволяет динамически выделять ресурсы на уровне всего пода. Под остается в `Pending`, если соответствующий `ResourceClaim` не может быть удовлетворен или ожидает действий от драйвера ресурса.

### 3. Взаимодействие с Cluster Autoscaler (CA) и PDB

Наличие `Pending` пода инициирует Scale-Up в CA, но процесс может блокироваться:

*   **PDB (Pod Disruption Budget):** Если для размещения нового пода требуется вытеснение старых, а PDB блокирует их удаление, новый под останется в `Pending`.
*   **Региональные лимиты (Regional Quotas):** CA может пытаться добавить узлы, но получать отказ от облачного провайдера (например, исчерпан лимит на GPU в конкретном регионе).
*   **Unexpandable Node Groups:** CA помечает группы узлов как не подлежащие расширению при повторяющихся ошибках API.

---

## Практические сценарии

### Анализ Scheduling Gates
Если под имеет статус `SchedulingGated`, проверьте список ворот:
```bash
kubectl get pod <pod-name> -o jsonpath='{.spec.schedulingGates}'
```
**Диагностика:** Если список не пуст более 30-60 секунд, ищите сбой в контроллере, ответственном за эти ворота (например, Gatekeeper, Kyverno или кастомный провижинер данных).

### Диагностика тупиков в Topology Spread
При использовании `maxSkew` и Rolling Update новые поды могут не находить места из-за старых версий.
```bash
# Проверка событий планировщика
kubectl describe pod <pod-name> | grep "FailedScheduling"
```
**Решение:** Внедрите `matchLabelKeys` (v1.31+), чтобы планировщик игнорировал поды старого ReplicaSet при расчете перекоса (skew).

### Мониторинг очередей планировщика
Используйте метрики для понимания состояния подов в очереди:
```bash
# Метрика доступна на эндпоинте :10251/metrics
scheduler_pending_pods{queue="active"}    # Готовы к планированию
scheduler_pending_pods{queue="backoff"}   # Ожидают повтора после неудачи
scheduler_pending_pods{queue="gated"}     # Заблокированы Scheduling Gates
```
Если `queue="backoff"` велика, это признак "flapping" конфигурации (под подходит по ресурсам, но отклоняется на этапе Binding/Permit).

### Отладка DRA (Dynamic Resource Allocation)
Если под требует спец-ресурсов через DRA:
```bash
# Проверка состояния требований ресурсов
kubectl get resourceclaims -n <namespace>
```
**Симптом:** `ResourceClaim` в состоянии `Pending` или `WaitingForFirstConsumer`. Проверьте логи соответствующего DRA-драйвера в кластере.

---

## Дополнительная информация

### Рекомендуемые практики

| Технология | Совет по использованию |
| :--- | :--- |
| **PriorityClass** | Используйте `preemptionPolicy: PreemptLowerPriority` только для критических сервисов. |
| **Queuing Hints** | Включайте `feature-gate` (v1.32+), если в кластере много долгоживущих Pending подов. |
| **Wait For First Consumer** | Всегда используйте этот режим для зональных дисков, чтобы избежать `Pending` из-за Zonal Mismatch. |

### Связанные ресурсы

*   **[Диагностика](./diagnostics.md)** — базовый алгоритм поиска неисправностей.
*   **[Kube-scheduler — архитектура](../../../Concepts/kube_scheduler.md)** — детали Scheduling Framework и плагинов.
*   **[PriorityClass — приоритеты подов](../../../Concepts/priorityclass.md)** — очереди и механизмы вытеснения.
*   **[Cluster Autoscaler — детальный обзор](../../Autoscaling/cluster_autoscaler_detailed.md)** — логика Scale-Up/Down.
*   **[Dynamic Resource Allocation (v1.32)](../../../Concepts/resource_management/dra_overview.md)** — управление GPU и ускорителями.
