# Масштабирование в Kubernetes

## Scylla Operator

Scylla Operator — рекомендуемый способ развёртывания ScyllaDB в Kubernetes:

```yaml
# ScyllaCluster CRD
apiVersion: scylla.scylladb.com/v1
kind: ScyllaCluster
metadata:
  name: my-scylla-cluster
  namespace: scylla
spec:
  version: 6.2
  datacenter:
    - name: dc1
      racks:
        - name: rack1
          members: 3
          storage:
            capacity: 200Gi
          resources:
            requests:
              cpu: 2
              memory: 8Gi
            limits:
              cpu: 4
              memory: 16Gi
        - name: rack2
          members: 3
          storage:
            capacity: 200Gi
          resources:
            requests:
              cpu: 2
              memory: 8Gi
            limits:
              cpu: 4
              memory: 16Gi
```

**Ключевые преимущества:**
- Автоматическое обновление (Rolling Update) без простоя.
- Автоматический Backup и Restore через CRD.
- Управление Rack-aware размещением подов.
- Интеграция с Prometheus для мониторинга.

```bash
# Установка Scylla Operator
kubectl create namespace scylla
helm repo add scylla https://scylla-operator-charts.s3.amazonaws.com/stable
helm install scylla-operator scylla/scylla-operator --namespace scylla

# Проверка статуса
kubectl get scyllaclusters -n scylla
kubectl describe scyllaclusters my-scylla-cluster -n scylla
```

---

## См. также
- **[Установка и настройка](./installation.md)** — Docker Compose,裸-metal.
- **[Архитектура: Cassandra vs ScyllaDB](./architecture.md)** — ScyllaDB, Seastar.
- **[Мониторинг и observability](./monitoring.md)** — Prometheus метрики.
