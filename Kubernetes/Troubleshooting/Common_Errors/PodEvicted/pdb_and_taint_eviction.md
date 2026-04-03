# Pod Evicted: PDB и Taint-based Eviction

## Definitions

**PDB-blocked Eviction** — ситуация, когда PodDisruptionBudget препятствует выселению пода через Eviction API (drain, rolling update). Под остаётся на узле, операция drain останавливается с ошибкой.

**Taint-based Eviction** — автоматическое выселение подов при добавлении taint с эффектом `NoExecute` на узел. Происходит при недоступности узла или ручном taint.

**NoExecute** — эффект taint, который вытесняет все поды без соответствующего toleration через `tolerationSeconds` (по умолчанию 300s для стандартных taints).

## Basic Concepts

### Два типа non-resource eviction

| Характеристика | PDB-blocked | Taint-based |
|----------------|-------------|-------------|
| **Инициатор** | drain / rolling update | Control Plane (автоматически) |
| **Результат** | Eviction **блокируется** | Eviction **происходит** |
| **Сообщение** | `violates PDB` | `Marking for deletion Pod` |
| **Причина** | Нарушение `minAvailable` / `maxUnavailable` | Taint `NoExecute` на узле |
| **Автоматическое** | Нет (только при drain/update) | Да (kubelet добавляет taint) |
| **Решение** | Изменить PDB или подождать | Добавить toleration |

### PDB и Eviction API

PDB работает **только** с Eviction API (`kubectl drain`). Он **не защищает** от:

- `kubectl delete pod` (обходит Eviction API)
- Node Pressure Eviction (kubelet игнорирует PDB)
- Taint-based Eviction (control plane не проверяет PDB)

**Механизм работы:**

```
kubectl drain <node>
    ↓
Eviction API запрос для каждого пода
    ↓
PDB проверка: current_available > minAvailable?
    ↓
Да → pod evicted
Нет → drain останавливается с ошибкой
```

### Taint-based Eviction: стандартные taints

Kubernetes автоматически добавляет taints при проблемах с узлом:

| Taint | Условие | tolerationSeconds |
|-------|---------|-------------------|
| `node.kubernetes.io/not-ready:NoExecute` | Узел NotReady | 300s |
| `node.kubernetes.io/unreachable:NoExecute` | Узел недоступен | 300s |
| `node.kubernetes.io/network-unavailable:NoSchedule` | Сеть недоступна | — (не eviction) |

> **Важно:** `tolerationSeconds: 300` означает 5-минутную задержку до eviction. Kubernetes ждёт, чтобы избежать ложных срабатываний при кратковременных проблемах сети.

## Practical Scenarios

### Сценарий 1: drain блокируется PDB

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

# События блокировки
kubectl get events --field-selector reason=DisruptionBudgetExceeded

# Поды, блокирующие drain
kubectl get pods -l app=<app-label> --field-selector spec.nodeName=<node-name>
```

**Интерпретация `kubectl describe pdb`:**

```
Name:           my-app-pdb
Min available:  2
# ↓ Если current < min — eviction заблокирован
Expected pods:  3
Current pods:   3
Disruptions allowed:  1    # ← можно выселить 1 под
Disruptions not allowed: 0 # ← после этого — стоп
```

**Решение:**

| Вариант | Команда | Риск | Когда применять |
|---------|---------|------|----------------|
| Подождать | — | Низкий | Под сам восстановится после rollout |
| Увеличить `maxUnavailable` | `kubectl patch pdb <name> -p '{"spec":{"maxUnavailable":2}}'` | Средний | Есть запасные узлы |
| Временно удалить PDB | `kubectl delete pdb <name>` | Высокий | Экстренное обслуживание |
| Добавить реплики | `kubectl scale deploy <app> --replicas=4` | Низкий | Есть capacity в кластере |

### Сценарий 2: Taint-based Eviction при недоступности узла

**Симптом:**

```bash
kubectl get pods
# NAME     READY   STATUS    RESTARTS   AGE
# my-app   0/1     Evicted   0          10m
```

**Диагностика:**

```bash
# Проверка taints узла
kubectl get node <node-name> -o jsonpath='{range .spec.taints[*]}{.key}={.value}:{.effect}{"\n"}{end}'

# Проверка tolerations пода
kubectl get pod <pod-name> -o jsonpath='{range .spec.tolerations[*]}{.key}={.effect} tolerationSeconds={.tolerationSeconds}{"\n"}{end}'

# События eviction
kubectl get events --field-selector involvedObject.name=<pod-name> --sort-by='.lastTimestamp'
```

**Сообщение в Events:**

```
Marking for deletion Pod <pod-name>
```

**Решение:**

| Причина taint | Действие |
|---------------|----------|
| `node.kubernetes.io/unreachable` | Восстановить узел → taint снимется автоматически |
| `node.kubernetes.io/not-ready` | Проверить kubelet: `systemctl status kubelet` |
| Ручной taint администратора | `kubectl taint node <name> <key>-` для удаления |

### Сценарий 3: Добавление toleration для критичных подов

Чтобы под пережил временную недоступность узла дольше 5 минут:

```yaml
spec:
  tolerations:
  - key: "node.kubernetes.io/unreachable"
    operator: "Exists"
    effect: "NoExecute"
    tolerationSeconds: 600   # 10 минут вместо 5
  - key: "node.kubernetes.io/not-ready"
    operator: "Exists"
    effect: "NoExecute"
    tolerationSeconds: 600
```

> **Осторожно:** Увеличение `tolerationSeconds` означает, что под будет ждать восстановления узла дольше. Если узел не восстановится — eviction произойдёт позже.

### Сценарий 4: Ручной taint для планового обслуживания

```bash
# 1. Добавить taint NoExecute — все поды без toleration будут выселены
kubectl taint node <node-name> maintenance=planned:NoExecute

# 2. Подождать выселение
kubectl get pods --field-selector spec.nodeName=<node-name>

# 3. Провести обслуживание

# 4. Удалить taint — поды вернутся
kubectl taint node <node-name> maintenance=planned-
```

> Это альтернатива `kubectl drain` — выселяет поды без учёта PDB.

## Additional Information

### Сравнение механизмов eviction

| Механизм | Инициатор | PDB уважает | Grace period |
|----------|-----------|-------------|--------------|
| **Drain (Eviction API)** | Пользователь | Да | `terminationGracePeriodSeconds` |
| **Node Pressure** | Eviction Manager | Нет | `evictionMaxPodGracePeriod` |
| **Taint-based NoExecute** | Control Plane | Нет | `tolerationSeconds` (300s default) |
| **kubectl delete** | Пользователь | Нет | `terminationGracePeriodSeconds` |

### Best Practices

| Практика | Описание |
|----------|----------|
| **PDB для stateful-приложений** | Защита доступности при drain |
| **`maxUnavailable: 1` для small replica sets** | Не более 1 пода одновременно |
| **`minAvailable: 50%` для large replica sets** | Минимум половина реплик |
| **tolerationSeconds для критичных подов** | Увеличить до 10-15 минут |
| **Мониторинг PDB событий** | Алерты на `DisruptionBudgetExceeded` |

### Связанные файлы

- **Определения:** [definitions.md](./definitions.md) — типы eviction, QoS
- **Диагностика:** [diagnostics.md](./diagnostics.md) — общий чек-лист
- **Maintenance eviction:** [maintenance_eviction.md](./maintenance_eviction.md) — drain процедура
- **PDB SSoT:** [pod_disruption_budget.md](../../../Autoscaling/pod_disruption_budget.md) — полное руководство по PDB
- **Taints SSoT:** [taints_and_tolerations.md](../../../Scheduling/taints_and_tolerations.md) — taints и tolerations
- **Node taints:** [taints_and_eviction.md](../NodeUnavailability/taints_and_eviction.md) — taints при недоступности узла
