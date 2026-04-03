# Api Access Forbidden: RBAC объекты

## Definitions

**RBAC-объекты** — сущности Kubernetes, определяющие кто (`subjects`) и к чему (`rules`) имеет доступ. При ошибках 403 проблема всегда в одном из этих объектов или их связях.

> Полное описание RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)

## Basic Concepts

### Связь объектов RBAC

```
Subject (кто?)
    ↓
Binding (привязка)
    ↓
Role (что можно?)
    ↓
Resources (к чему?)
```

### Таблица RBAC-объектов

| Объект | Уровень | Назначение | Подробнее |
|--------|---------|------------|-----------|
| **ServiceAccount** | Namespace | Учётная запись для pod | [roles.md](../../../Security/rbac/roles.md#serviceaccount) |
| **Role** | Namespace | Права в одном namespace | [roles.md](../../../Security/rbac/roles.md#role) |
| **ClusterRole** | Кластер | Права на кластер или все namespace | [roles.md](../../../Security/rbac/roles.md#clusterrole) |
| **RoleBinding** | Namespace | Привязка субъекта к Role | [bindings.md](../../../Security/rbac/bindings.md#rolebinding) |
| **ClusterRoleBinding** | Кластер | Глобальная привязка | [bindings.md](../../../Security/rbac/bindings.md#clusterrolebinding) |

### Частые ошибки конфигурации

| Ошибка | Результат | Как обнаружить |
|--------|-----------|----------------|
| Role создан, но нет RoleBinding | 403 — права не привязаны | `kubectl auth can-i --list` |
| RoleBinding ссылается на несуществующий Role | 403 — правила не найдены | `kubectl get role <role-name>` |
| ClusterRole привязан через RoleBinding без namespace | 403 — ограничение scope | Проверить `metadata.namespace` |
| Неправильный `apiGroups` | 403 — ресурс не найден | Сравнить `apiGroups` с ресурсом |

## Practical Scenarios

### Сценарий 1: Диагностика через проверку RBAC-объектов

**Проблема:** 403 на чтение pods.

```bash
# 1. SA пода
kubectl get pod <pod> -o jsonpath='{.spec.serviceAccountName}'

# 2. RoleBinding для SA
kubectl get rolebinding -n <ns> -o wide | grep <sa-name>

# 3. Rules привязанной роли
kubectl get rolebinding <binding-name> -n <ns> -o yaml

# 4. Содержимое Role
kubectl get role <role-name> -n <ns> -o yaml
```

### Сценарий 2: Использование встроенных ClusterRole

Kubernetes предоставляет встроенные роли для типовых сценариев.

| Role | Описание | Когда использовать |
|------|----------|-------------------|
| `view` | Только чтение (без Secrets) | Мониторинг, дашборды |
| `edit` | Чтение + запись (без RBAC) | Разработчики |
| `admin` | Edit + RBAC в namespace | Админы namespace |
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
  name: view
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 3: Неправильный apiGroups — частая ошибка

**Проблема:** RoleBinding создан, но 403 остаётся.

**Частая причина:** Неправильный `apiGroups` в правилах Role.

```yaml
# ❌ НЕПРАВИЛЬНО: deployments в группе "" (core)
rules:
- apiGroups: [""]
  resources: ["deployments"]
  verbs: ["get", "list"]

# ✅ ПРАВИЛЬНО: deployments в группе "apps"
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list"]
```

**Проверка:**

```bash
# Тест прав
kubectl auth can-i get deployments \
  --as=system:serviceaccount:my-ns:my-sa -n my-ns
```

## Additional Information

### Соответствие ресурсов и apiGroups

| Ресурс | API Group | Пример команды |
|--------|-----------|----------------|
| pods, services, configmaps | `""` (core) | `kubectl auth can-i get pods` |
| deployments, replicasets | `apps` | `kubectl auth can-i get deployments` |
| ingress | `networking.k8s.io` | `kubectl auth can-i get ingress` |
| cronjobs, jobs | `batch` | `kubectl auth can-i get jobs` |
| clusterrole, rolebinding | `rbac.authorization.k8s.io` | `kubectl auth can-i get roles` |

### Связанные ресурсы

- SSoT — RBAC обзор: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)
- SSoT — роли: [../../../Security/rbac/roles.md](../../../Security/rbac/roles.md)
- SSoT — привязки: [../../../Security/rbac/bindings.md](../../../Security/rbac/bindings.md)
- Распространённые 403: [common.md](common.md)
- Диагностика: [diagnostics.md](diagnostics.md)
