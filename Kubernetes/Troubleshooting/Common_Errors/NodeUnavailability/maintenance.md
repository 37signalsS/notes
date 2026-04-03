# Node Unavailability: Maintenance and Best Practices

## Definitions

**Planned Maintenance** — процедура планового вывода узла из эксплуатации для обслуживания (обновление ОС, ядра, замена оборудования). В отличие от аварийной недоступности, выполняется контролируемо с предварительным дренажем подов.

**Cordon / Drain / Uncordon** — стандартный цикл обслуживания: запретить новые поды → выселить существующие → обслужить узел → вернуть в пул. Подробнее: [node_maintenance.md](../../../Operations/node_maintenance.md).

## Basic Concepts

### Maintenance Procedure Overview

| Этап | Команда | Результат |
|------|---------|-----------|
| **1. Cordon** | `kubectl cordon <node>` | Узел помечен `unschedulable`, новые поды не планируются |
| **2. Drain** | `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data` | Поды выселяются на другие узлы |
| **3. Maintenance** | — | Выполнение работ на узле |
| **4. Uncordon** | `kubectl uncordon <node>` | Узел возвращается в пул планирования |

### Drain Flags

| Флаг | Назначение |
|------|-----------|
| `--ignore-daemonsets` | Пропустить DaemonSet-поды (невозможно выселить) |
| `--delete-emptydir-data` | Удалить данные `emptyDir` (риск потери данных) |
| `--force` | Принудительное выселение pod без controller |
| `--timeout` | Максимальное время ожидания завершения eviction |

### Monitoring and Alerting

```yaml
# Prometheus alerts
- alert: NodeNotReady
  expr: kube_node_status_condition{condition="Ready",status="true"} == 0
  for: 5m
  labels:
    severity: critical

- alert: NodeUnreachable
  expr: absent(kube_node_info) unless absent(kube_node_status_condition)
  for: 10m
  labels:
    severity: warning

- alert: NodeMemoryPressure
  expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning
```

### Best Practices

| Практика | Описание |
|----------|----------|
| **Минимум 3 узла** | Для HA control plane и устойчивости к потере узла |
| **PodDisruptionBudget** | Защита от массового выселения критичных workload |
| **Node Autoscaling** | Автоматическая замена неисправных узлов |
| **Мониторинг kubelet** | Алерты на статус и ресурсы узла |
| **Регулярное обновление** | Патчи безопасности, обновление ядра по расписанию |
| **PDB перед drain** | Всегда проверяйте `kubectl get pdb` перед дренажем |

## Practical Scenarios

### Scenario 1: Плановое обслуживание узла

```bash
# 1. Cordon — запрет новых подов
kubectl cordon <node-name>

# 2. Drain — выселение существующих подов
kubectl drain <node-name> \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --force

# 3. Обслуживание узла
# reboot, update kernel, hardware maintenance

# 4. Uncordon — возврат в работу
kubectl uncordon <node-name>
```

**Проверка после обслуживания:**

```bash
# Узел в Ready?
kubectl get nodes

# Все ли системные поды запущены?
kubectl get pods -n kube-system -o wide | grep <node-name>
```

### Scenario 2: Замена узла (hardware failure)

```bash
# 1. Drain неисправного узла
kubectl drain <source-node> --ignore-daemonsets --delete-emptydir-data

# 2. Добавить новый узел в кластер (kubeadm join / autoscaler)

# 3. Удалить старый узел из кластера
kubectl delete node <source-node>
```

### Scenario 3: Миграция workload между узлами

`kubectl drain` не позволяет указать целевой узел напрямую. Решения:

1. **Taint + Toleration** — затейнить источники, добавить toleration на целевые узлы
2. **Node Affinity** — изменить affinity подов перед drain

Подробнее: [node_maintenance.md#node-migration](../../../Operations/node_maintenance.md).

## Additional Information

### Detailed Guides

- Полное руководство по обслуживанию узлов: [node_maintenance.md](../../../Operations/node_maintenance.md)
- High availability concepts: [high_availability.md](../../../Base/high_availability.md)
- Pod Disruption Budget: [pod_disruption_budget.md](../../../Autoscaling/pod_disruption_budget.md)

### Node Unavailability Diagnostics

- Definitions: [definitions.md](./definitions.md)
- Diagnostics checklist: [diagnostics.md](./diagnostics.md)
- Taints and eviction: [taints_and_eviction.md](./taints_and_eviction.md)

### External Resources

- [Kubernetes: Safely Drain a Node](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)
- [Node Conditions](https://kubernetes.io/docs/concepts/architecture/node/#condition)
- [Node Pressure Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/)
