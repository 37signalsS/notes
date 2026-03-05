# CreateContainerConfigError: Проблемы с RBAC

## Проблемы с правами доступа (RBAC)

**Сообщение:**

```
user "system:serviceaccount:default:default" cannot get resource "configmaps" in API group "" in the namespace "default"
```

**Причина:** У ServiceAccount пода нет прав на чтение ConfigMap/Secret.

**Диагностика:**

```bash
kubectl auth can-i get configmaps \
  --as=system:serviceaccount:default:default \
  -n default
```

**Решение:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: config-reader
  namespace: default
rules:
- apiGroups: [""]
  resources: ["configmaps", "secrets"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: default-config-reader
  namespace: default
subjects:
- kind: ServiceAccount
  name: default
  namespace: default
roleRef:
  kind: Role
  name: config-reader
  apiGroup: rbac.authorization.k8s.io
```

> **См. также:** [`../../../Security/rbac/rbac_overview.md`](../../../Security/rbac/rbac_overview.md)
