# Api Access Forbidden: 403 Forbidden (расширенные сценарии)

## 403 — доступ к pods/log (для log shipper)

**Сценарий:** Контейнер-сборщик логов (Fluent Bit, Filebeat) пытается читать логи других подов.

**Сообщение:**
```
pods/log is forbidden: User "system:serviceaccount:..."
cannot get resource "pods/log" in API group "" in the namespace "..."
```

**Диагностика:**
```bash
# Проверка прав
kubectl auth can-i get pods/log \
  --as=system:serviceaccount:monitoring:fluent-bit \
  -n monitoring
```

**Решение:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole  # ClusterRole для доступа ко всем namespace
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

## 403 — доступ к nodes (для monitoring)

**Сценарий:** Prometheus node-exporter или metrics-server нуждается в доступе к узлам.

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

## 403 — доступ к namespaces

**Сценарий:** Приложение пытается получить список namespace или информацию о своем namespace.

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
```
