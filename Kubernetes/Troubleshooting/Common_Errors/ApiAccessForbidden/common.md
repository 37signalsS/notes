# Api Access Forbidden: 403 Forbidden (распространённые случаи)

## Definitions

**403 Forbidden (namespaced resources)** — ошибка возникает, когда аутентифицированный субъект обращается к ресурсам в пределах namespace, но не имеет соответствующих прав RBAC.

> Различие 401 vs 403: [definitions.md](definitions.md)
> Общие лучшие практики RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)

## Basic Concepts

### Паттерн сообщения об ошибке

```
Error from server (Forbidden): <resource> is forbidden:
User "<subject>" cannot <verb> resource "<resource>"
in API group "<group>" in the namespace "<namespace>"
```

### Алгоритм быстрого решения

1. Извлечь из сообщения: `subject`, `verb`, `resource`, `apiGroup`, `namespace`
2. Проверить: есть ли Role с нужными `resources` + `verbs`
3. Проверить: привязан ли `subject` к этой Role через RoleBinding
4. Если нет — создать Role + RoleBinding

### Диагностика

```bash
# Проверка прав субъекта
kubectl auth can-i <verb> <resource> \
  --as=<subject> -n <namespace>

# Пример
kubectl auth can-i list pods \
  --as=system:serviceaccount:my-ns:my-sa -n my-ns

# Поиск существующих RoleBinding
kubectl get rolebinding -n <namespace> -o wide | grep <sa-name>
```

> Пошаговая диагностика: [diagnostics.md](diagnostics.md)

## Practical Scenarios

### Сценарий 1: Чтение pods (отсутствует RoleBinding)

**Контекст:** Приложение пытается получить список подов в своем namespace.

**Сообщение:**

```
Error from server (Forbidden): pods is forbidden:
User "system:serviceaccount:my-ns:my-sa" cannot list resource "pods"
in API group "" in the namespace "my-ns"
```

**Анализ ошибки:**

| Поле | Значение |
|------|----------|
| Subject | `system:serviceaccount:my-ns:my-sa` |
| Verb | `list` |
| Resource | `pods` |
| API Group | `""` (core) |
| Namespace | `my-ns` |

**Решение:**

```yaml
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

### Сценарий 2: Доступ к Secrets

**Контекст:** Приложению требуется прочитать Secrets (например, для rotation или cross-namespace sync).

**Сообщение:**

```
secrets is forbidden: User "system:serviceaccount:..."
cannot list resource "secrets" in API group "" in the namespace "..."
```

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
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: app-secret-reader
  namespace: my-ns
subjects:
- kind: ServiceAccount
  name: <sa-name>
  namespace: my-ns
roleRef:
  kind: Role
  name: secret-reader
  apiGroup: rbac.authorization.k8s.io
```

> **Warning:** Предоставляйте доступ к Secrets только когда это абсолютно необходимо. По возможности используйте `resourceNames` для ограничения конкретными секретами.

### Сценарий 3: Создание/удаление deployments

**Контекст:** CI/CD pipeline или оператор пытается управлять deployments.

**Сообщение:**

```
deployments is forbidden: User "..." cannot create resource "deployments"
in API group "apps" in the namespace "..."
```

**Особенность:** `deployments` принадлежат API-группе `apps` (не core).

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
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: cicd-deployment-manager
  namespace: my-ns
subjects:
- kind: ServiceAccount
  name: <ci-sa-name>
  namespace: my-ns
roleRef:
  kind: Role
  name: deployment-manager
  apiGroup: rbac.authorization.k8s.io
```

## Additional Information

### Таблица apiGroups для распространённых ресурсов

| Ресурс | API Group | Тип роли |
|--------|-----------|----------|
| pods, services, configmaps, secrets | `""` (core) | Role |
| deployments, replicasets, statefulsets | `apps` | Role |
| ingress | `networking.k8s.io` | Role |
| cronjobs, jobs | `batch` | Role |
| roles, rolebindings | `rbac.authorization.k8s.io` | Role |

### Связанные ресурсы

- SSoT — Role и ClusterRole: [../../../Security/rbac/roles.md](../../../Security/rbac/roles.md)
- SSoT — лучшие практики RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)
- Определения 401/403: [definitions.md](definitions.md)
- Пошаговая диагностика: [diagnostics.md](diagnostics.md)
- Расширенные сценарии (ClusterRole): [advanced.md](advanced.md)
