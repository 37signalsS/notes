# Pod Evicted: Профилактика

## Prevention (Профилактика)

### 1. Настройка QoS для критичных подов

```yaml
# Guaranteed QoS для критичных сервисов
resources:
  requests:
    memory: "512Mi"
    cpu: "500m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

### 2. Pod Disruption Budget

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: my-app
```

### 3. Мониторинг и алерты

```yaml
# Prometheus alerts
- alert: NodeMemoryPressure
  expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning

- alert: NodeDiskPressure
  expr: kube_node_status_condition{condition="DiskPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning

- alert: PodEvicted
  expr: kube_pod_status_reason{reason="Evicted"} == 1
  for: 1m
  labels:
    severity: critical
```

### 4. Cluster Autoscaler

Автоматическое добавление узлов при нехватке ресурсов:

```yaml
# Cluster Autoscaler автоматически добавит узлы
# при появлении Pending подов из-за нехватки ресурсов
```

> **См. также:** [`../../../Autoscaling/cluster_autoscaler_detailed.md`](../../../Autoscaling/cluster_autoscaler_detailed.md)

## Удаление выселенных подов

Выселенные поды не удаляются автоматически:

```bash
# Удаление одного пода
kubectl delete pod <pod-name>

# Удаление всех выселенных подов в namespace
kubectl delete pods --field-selector status.reason=Evicted -n <namespace>

# Удаление всех выселенных подов в кластере
kubectl delete pods --field-selector status.reason=Evicted --all-namespaces
```

> **Важно:** Deployment/ReplicaSet автоматически создаст новые поды взамен удаленных.

## Best Practices

| Практика | Описание |
|----------|----------|
| **Всегда указывайте `requests` и `limits`** | Избегайте QoS `BestEffort` |
| **Используйте `Guaranteed` для критичных подов** | Максимальная защита от eviction |
| **Настройте PDB** | Защита от массового выселения |
| **Мониторьте ресурсы узлов** | Алерты на Memory/Disk Pressure |
| **Используйте Cluster Autoscaler** | Автоматическое масштабирование |

## Ссылки

- [Node Pressure Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/)
- [Pod Disruption Budgets](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)
- [Configure Quality of Service](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/)
