# Node Unavailability: Обслуживание и Best Practices

## Обслуживание узлов (Planned Maintenance)

**Стандартная процедура:**

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

## Мониторинг и алерты

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

## Best Practices

| Практика | Описание |
|----------|----------|
| **Минимум 3 узла** | Для HA control plane |
| **PodDisruptionBudget** | Защита от массового выселения |
| **Node Autoscaling** | Автоматическая замена неисправных узлов |
| **Мониторинг kubelet** | Алерты на статус и ресурсы |
| **Регулярное обновление** | Патчи безопасности, обновление ядра |

## Ссылки

- [Node Condition](https://kubernetes.io/docs/concepts/architecture/node/#condition)
- [Node Maintenance](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)
- [Critical Pod Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/)
