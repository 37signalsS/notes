# Api Access Forbidden: 403 Forbidden (расширенные сценарии)

## Definitions

**Subresource API access** — доступ к подресурсам Kubernetes API (`pods/log`, `nodes/metrics`, `nodes/proxy`), требующий отдельных прав в RBAC.

**Cross-namespace access** — доступ к ресурсам во всех namespace кластера, требующий ClusterRole вместо Role.

## Basic Concepts

### Когда требуются расширенные права

Стандартные Role/RoleBinding обеспечивают доступ к основным ресурсам (pods, services, deployments). Расширенные сценарии требуют:

| Ресурс | Зачем | Тип роли |
|--------|-------|----------|
| `pods/log` | Сбор логов (Fluent Bit, Filebeat, Loki) | ClusterRole |
| `nodes`, `nodes/metrics` | Мониторинг узлов (Prometheus, metrics-server) | ClusterRole |
| `namespaces` | Получение информации о namespace кластера | ClusterRole |

### Диагностика расширенных прав

```bash
# Проверка прав на подресурс
kubectl auth can-i get pods/log \
  --as=system:serviceaccount:<namespace>:<sa-name> \
  -n <namespace>

# Проверка прав на узлы
kubectl auth can-i get nodes \
  --as=system:serviceaccount:<namespace>:<sa-name>

# Проверка прав на namespace
kubectl auth can-i get namespaces \
  --as=system:serviceaccount:<namespace>:<sa-name>
```

> См. пошаговую диагностику: [diagnostics.md](diagnostics.md)

## Practical Scenarios

### Сценарий 1: 403 — доступ к pods/log (log shipper)

**Контекст:** Контейнер-сборщик логов (Fluent Bit, Filebeat, Loki Promtail) пытается читать логи других подов.

**Сообщение об ошибке:**

```
pods/log is forbidden: User "system:serviceaccount:..."
cannot get resource "pods/log" in API group "" in the namespace "..."
```

**Решение:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: pod-log-reader
rules:
- apiGroups: [""]
  resources: ["pods/log"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: fluent-bit-pod-log-reader
subjects:
- kind: ServiceAccount
  name: fluent-bit
  namespace: monitoring
roleRef:
  kind: ClusterRole
  name: pod-log-reader
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 2: 403 — доступ к nodes (monitoring)

**Контекст:** Prometheus node-exporter, metrics-server или kube-state-metrics нуждаются в доступе к узлам и их метрикам.

**Сообщение об ошибке:**

```
nodes is forbidden: User "system:serviceaccount:..."
cannot get resource "nodes" in API group ""
```

**Решение:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-reader
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["nodes/metrics"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus-node-reader
subjects:
- kind: ServiceAccount
  name: prometheus
  namespace: monitoring
roleRef:
  kind: ClusterRole
  name: node-reader
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 3: 403 — доступ к namespaces

**Контекст:** Приложение пытается получить список namespace или информацию о своем namespace (например, для динамического обнаружения сервисов).

**Сообщение об ошибке:**

```
namespaces is forbidden: User "system:serviceaccount:..."
cannot list resource "namespaces" in API group ""
```

**Решение:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: namespace-reader
rules:
- apiGroups: [""]
  resources: ["namespaces"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: app-namespace-reader
subjects:
- kind: ServiceAccount
  name: <sa-name>
  namespace: <namespace>
roleRef:
  kind: ClusterRole
  name: namespace-reader
  apiGroup: rbac.authorization.k8s.io
```

## Additional Information

### Почему ClusterRole вместо Role?

Для ресурсов `pods/log`, `nodes`, `namespaces` требуется доступ на уровне кластера, а не отдельного namespace. Role ограничена одним namespace и не может предоставить доступ к:

- Узлам кластера (nodes)
- Подресурсам в других namespace (pods/log)
- Глобальным ресурсам (namespaces)

### Связанные ресурсы

- Основные сценарии 403: [common.md](common.md)
- RBAC объекты: [rbac_objects.md](rbac_objects.md)
- Диагностика: [diagnostics.md](diagnostics.md)
- Лучшие практики: [best_practices.md](best_practices.md)
