# Api Access Forbidden: RBAC объекты

## RBAC объекты

| Объект | Описание |
|--------|----------|
| **ServiceAccount** | Учетная запись для pod | [`../../../Security/rbac/roles.md`](../../../Security/rbac/roles.md) |
| **Role** | Права в namespace | [`../../../Security/rbac/roles.md`](../../../Security/rbac/roles.md) |
| **ClusterRole** | Права на кластер | [`../../../Security/rbac/roles.md`](../../../Security/rbac/roles.md) |
| **RoleBinding** | Привязка в namespace | [`../../../Security/rbac/bindings.md`](../../../Security/rbac/bindings.md) |
| **ClusterRoleBinding** | Глобальная привязка | [`../../../Security/rbac/bindings.md`](../../../Security/rbac/bindings.md) |

> **См. также:** [`../../../Security/rbac/rbac_overview.md`](../../../Security/rbac/rbac_overview.md)

### Встроенные ClusterRole

Kubernetes предоставляет готовые роли:

| Role | Описание | Когда использовать |
|------|----------|-------------------|
| `view` | Только чтение (без Secrets) | Мониторинг, дашборды |
| `edit` | Чтение + запись (без RBAC) | Разработчики |
| `admin` | Edit + управление RBAC в namespace | Админы namespace |
| `cluster-admin` | Полный доступ | Админы кластера |

**Привязка встроенной роли:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: developer-view
  namespace: my-ns
subjects:
- kind: ServiceAccount
  name: my-sa
  namespace: my-ns
roleRef:
  kind: ClusterRole
  name: view  # Встроенная роль
  apiGroup: rbac.authorization.k8s.io
```
