# Api Access Forbidden: 403 Forbidden (распространённые случаи)

## 403 Forbidden — отсутствие прав на чтение подов

**Сообщение:**
```
Error from server (Forbidden): pods is forbidden:
User "system:serviceaccount:my-ns:my-sa" cannot list resource "pods"
in API group "" in the namespace "my-ns"
```

**Причина:** У ServiceAccount нет RoleBinding с необходимыми правами.

**Решение:**
```yaml
# Создание Role
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
  namespace: my-ns
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
---
# Привязка к ServiceAccount
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: my-sa-pod-reader
  namespace: my-ns
subjects:
- kind: ServiceAccount
  name: my-sa
  namespace: my-ns
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

## 403 — доступ к Secrets

**Сообщение:**
```
secrets is forbidden: User "system:serviceaccount:..."
cannot list resource "secrets" in API group "" in the namespace "..."
```

**Причина:** Доступ к Secrets ограничен по умолчанию.

**Решение:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: secret-reader
  namespace: my-ns
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
```

> **Warning:** Предоставляйте доступ к Secrets только когда это абсолютно необходимо.

## 403 — создание/удаление ресурсов

**Сообщение:**
```
deployments is forbidden: User "..." cannot create resource "deployments"
```

**Решение:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: deployment-manager
  namespace: my-ns
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```
