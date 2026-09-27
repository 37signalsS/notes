# PodDisruptionBudget для компонентов мониторинга

## Определения

**PodDisruptionBudget (PDB)** — объект Kubernetes API, ограничивающий количество одновременных прерываний (disruptions) подов при плановых действиях: `kubectl drain`, обновление ноды, cluster autoscaling. Для компонентов мониторинга PDB защищает от одновременного удаления всех реплик Prometheus/Alertmanager, что приведет к потере данных и прерыванию алертинга.

**Planned Disruption (Плановое прерывание)** — удаление пода оператором Kubernetes (drain, rolling update, preemption). PDB контролирует только planned disruptions; при остановке пода через `kubectl delete pod` PDB применяется.

**Voluntary Disruption (Добровольное прерывание)** — событие, которое инициирует пользователь или автоматизация (drain, scale down). PDB защищает от этого типа.

**Involuntary Disruption (Невольное прерывание)** — аппаратный сбой ноды, OOMKill, network partition. PDB не защищает от этого; используется HA (replicas).

> **Смотрите также:** [Высокая доступность](./high_availability.md) — репликация и кворум Alertmanager.

---

## Базовые концепции

### Правила PDB для компонентов мониторинга

| Компонент | replicas | PDB strategy | minAvailable / maxUnavailable |
|:---|:---|:---|:---|
| **Prometheus** (HA) | 2 | minAvailable | 1 |
| **Prometheus** (3+ replicas) | 3+ | maxUnavailable | 1 |
| **Alertmanager** (кворум) | 3 | minAvailable | 2 |
| **Alertmanager** (5 replicas) | 5 | minAvailable | 3 |
| **Grafana** | 1 | Без PDB | Не критично |

**Важно:** Для Alertmanager кворум = `floor(replicas/2) + 1`. При 3 репликах кворум = 2. Потеря 2 реплик приводит к потере кворума и inability дедуплицировать алерты.

---

## Практические сценарии

### PDB для Prometheus (2 реплики, HA)

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: prometheus-main-pdb
  namespace: monitoring
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: prometheus
      app.kubernetes.io/instance: main
```

**Behavior:** При `kubectl drain` ноды с подом Prometheus Operator будет ждать, пока вторая реплика не станет Ready, прежде чем удалять первый под.

### PDB для Alertmanager (3 реплики, кворум)

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: alertmanager-main-pdb
  namespace: monitoring
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: alertmanager
      app.kubernetes.io/instance: main
```

**Behavior:** При 3 репликах PDB разрешает удаление только 1 пода за раз (3 - 2 = 1). Если одна реплика уже недоступна, drain будет заблокирован.

### PDB для Grafana

Grafana обычно не требует PDB при replicas=1, так как кратковременная недоступность UI не критична. При replicas=2+:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: grafana-pdb
  namespace: monitoring
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: grafana
```

### Проверка PDB перед drain

```bash
# 1. Проверка PDB в namespace
kubectl get pdb -n monitoring
# → NAME                      MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → prometheus-main-pdb       1               N/A               1                     5d
# → alertmanager-main-pdb     2               N/A               1                     5d

# 2. Проверка allowed disruptions перед drain
kubectl describe pdb prometheus-main-pdb -n monitoring
# → Allowed disruptions: 1
# → Current: 2 pods, 2 ready, 2 available

# 3. Проверка состояния drain (dry-run)
kubectl drain <node> --dry-run=client --ignore-daemonsets

# 4. Если drain блокируется — проверьте PDB
kubectl describe pdb -n monitoring | grep -A5 "Conditions"
```

### Взаимодействие с StatefulSet updateStrategy

При обновлении `spec.version` в Prometheus CRD Operator выполняет Rolling Update StatefulSet:

```yaml
spec:
  version: v3.12.0
  # Control pace of rolling update via partition:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 0  # Обновить ВСЕ поды
```

**PDB + Rolling Update:**
- Operator обновляет поды по одному (Rolling Update).
- PDB проверяет `minAvailable` перед удалением каждого пода.
- Если `minAvailable: 1` и обе реплики Ready — разрешено удаление 1 пода.
- Если одна реплика уже обновляется — вторая не будет удалена до Ready.

### Диагностика

```bash
# 1. Проверка что PDB не блокирует обновления
kubectl get pdb -n monitoring -o wide

# 2. Проверка Events при блокировке drain
kubectl get events -n monitoring --field-selector reason=DisruptionTarget

# 3. Проверка текущего количества готовых подов
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus \
  -o custom-columns=NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status

# 4. Принудительный drain (если PDB не критичен)
kubectl drain <node> --force --ignore-daemonsets --delete-emptydir-data
```

---

## Дополнительная информация

### Связанные файлы

| Файл | Содержание |
|:---|:---|
| [Высокая доступность](./high_availability.md) | HA-архитектура, replicas, шарды |
| [Обновление Operator](./installation.md) | Rolling Update, partition, откат |
| [PDB в Kubernetes](../../../../Kubernetes/Scheduling/pod_disruption_budget.md) | Общий справочник PDB |

### Частые ошибки на собеседованиях

1. **"PDB защищает от аппаратных сбоев"** — Нет. PDB защищает только от planned disruptions (drain, rolling update). От hardware failure защищает HA (replicas + anti-affinity).
2. **"minAvailable: 1 при 2 репликах — безопасно"** — Да, но только для Prometheus. Для Alertmanager при 2 репликах minAvailable: 1 означает, что обе реплики могут быть удалены одновременно (2 - 1 = 1 allowed disruption). Используйте 3 реплики с minAvailable: 2.
3. **"PDB блокирует drain навсегда"** — Нет. PDB блокирует drain до тех пор, пока не будет достигнуто minAvailable. Если под восстанавливается, drain продолжится.
