# Pod Evicted: Обслуживание узлов

## Definitions

**Maintenance Eviction** — выселение подов в результате выполнения `kubectl drain` администратором для планового обслуживания узла. Отличается от Node Pressure Eviction тем, что инициируется пользователем через Eviction API, а не kubelet'ом.

**Сообщение в Events:**

```
pod evicted from node <node-name> by user request
```

## Basic Concepts

### Отличие от Node Pressure Eviction

| Характеристика | Maintenance Eviction | Node Pressure Eviction |
|----------------|---------------------|----------------------|
| **Инициатор** | Пользователь (`kubectl drain`) | Eviction Manager (kubelet) |
| **Причина** | Плановое обслуживание | Нехватка ресурсов |
| **Сообщение** | `by user request` | `low on resource: memory/ephemeral-storage` |
| **Уважение PDB** | Да (drain остановится) | Нет (kubelet игнорирует PDB) |
| **Порядок выселения** | Все поды одновременно | По QoS: BestEffort → Burstable → Guaranteed |
| **Предсказуемость** | Планируемая операция | Аварийная ситуация |

### Как drain работает с подами

```
kubectl drain <node>
    ↓
Cordon узла (unschedulable)
    ↓
Eviction API для каждого пода
    ↓
PDB проверка → Если нарушение, drain останавливается
    ↓
Graceful shutdown (terminationGracePeriodSeconds)
    ↓
Pod переходит в Terminating → удалён
    ↓
ReplicaSet/Deployment создаёт под на другом узле
```

### Флаги drain и их влияние на поды

| Флаг | Что делает | Без флага |
|------|-----------|-----------|
| `--ignore-daemonsets` | Пропускает DaemonSet-поды | Ошибка: «cannot evict DaemonSet-managed Pod» |
| `--delete-emptydir-data` | Удаляет данные emptyDir | Ошибка: «pods with local storage» |
| `--force` | Принудительно выселяет «голые» поды | Ошибка: «cannot evict pod without controller» |
| `--grace-period=<sec>` | Таймаут завершения | Берётся из pod spec (по умолчанию 30s) |
| `--timeout=<duration>` | Максимальное время drain | Без таймаута (ждёт бесконечно) |

## Practical Scenarios

### Диагностика: под выселен из-за drain

**Шаг 1: Проверка статуса пода**

```bash
kubectl describe pod <pod-name> -n <namespace>
```

**Ищите в Events:**

```
LAST SEEN   TYPE     REASON      OBJECT          MESSAGE
10s         Normal   Evicted     pod/my-app      The node was low on resource: memory.
# ИЛИ
10s         Normal   Evicted     pod/my-app      pod evicted from node node-1 by user request
```

> `by user request` = drain, `low on resource` = Node Pressure.

**Шаг 2: Проверка состояния узла**

```bash
kubectl get nodes
# NAME     STATUS                        AGE
# node-1   Ready,SchedulingDisabled      30d  ← узел в cordon
# node-2   Ready                         30d
```

**Шаг 3: История drain (audit log)**

```bash
# Audit log API-запросов (если включён)
kubectl get events --field-selector reason=SuccessfulDrain --sort-by='.lastTimestamp'

# Или проверка через audit log узла
journalctl -u kube-apiserver | grep "drain"
```

### Drain остановился из-за PDB

**Симптом:**

```bash
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data
# error: cannot evict pod as it would violate the pod's disruption budget
```

**Диагностика:**

```bash
# Проверка PDB
kubectl get pdb
kubectl describe pdb <pdb-name>

# Поды, которые не могут быть выселены
kubectl get pods -n <namespace> -l app=<app-label> --field-selector spec.nodeName=<node-name>
```

**Решение:**

| Вариант | Команда | Риск |
|---------|---------|------|
| Увеличить `maxUnavailable` | `kubectl patch pdb <name> -p '{"spec":{"maxUnavailable":2}}'` | Средний |
| Временно удалить PDB | `kubectl delete pdb <name>` | Высокий |
| Подождать | Дождаться завершения других операций | Низкий |

### Drain «завис» — поды в Terminating

```bash
# Поды, застрявшие в Terminating
kubectl get pods --all-namespaces --field-selector status.phase=Running | grep Terminating

# Проверка finalizers
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.metadata.finalizers}'

# Принудительное удаление (если finalizer блокирует)
kubectl patch pod <pod-name> -n <namespace> -p '{"metadata":{"finalizers":null}}'
```

> **Важно:** `kubectl drain --timeout=5m` предотвратит бесконечное ожидание.

## Additional Information

### Best Practices для maintenance eviction

| Практика | Описание |
|----------|----------|
| **Всегда используйте `--ignore-daemonsets`** | DaemonSet-поды не могут быть перемещены |
| **Проверяйте PDB перед drain** | Убедитесь, что `minAvailable` позволяет выселение |
| **Используйте `--timeout`** | Ограничение времени ожидания |
| **Drain по одному узлу** | Не выводите из строя несколько узлов одновременно |
| **Мониторьте миграцию подов** | `kubectl get pods -o wide --watch` — поды должны переехать |

### Автоматизация

| Инструмент | Назначение |
|-----------|-----------|
| **Kured** | Автоматический drain при reboot после kernel update |
| **Draino** | Автоматический drain по taint-условиям |
| **Cluster Autoscaler** | Автоматический drain + удаление неиспользуемых узлов |

### Связанные файлы

- **Определения:** [definitions.md](./definitions.md) — типы eviction, QoS
- **Диагностика:** [diagnostics.md](./diagnostics.md) — общий чек-лист
- **PDB:** [pdb_and_taint_eviction.md](./pdb_and_taint_eviction.md) — PDB-блокировки
- **Профилактика:** [prevention.md](./prevention.md) — monitoring, best practices
- **SSoT drain:** [node_maintenance.md](../../../Operations/node_maintenance.md) — полное руководство по drain/cordon/uncordon
- **PDB:** [pod_disruption_budget.md](../../../Autoscaling/pod_disruption_budget.md) — настройка PDB
