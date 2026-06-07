# Api Access Forbidden: объекты RBAC

## Определения

**Объекты RBAC (Role-Based Access Control — управление доступом на основе ролей)** — сущности Kubernetes, определяющие кто (`subjects`) и к чему (`rules`) имеет доступ. При ошибках 403 проблема всегда заключается в конфигурации одного из этих объектов или их связей.

> Полное описание RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)

## Основные концепции

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

## Практические сценарии

### Сценарий 1: Исследование связей RBAC

Для пошагового анализа цепочки `Subject -> RoleBinding -> Role` используйте **[руководство по проверке привязок](diagnostics.md#шаг-5-проверка-привязок-ролей)**.

Основные шаги:

1. Определение **SA (ServiceAccount)** пода.
2. Поиск привязок (**RoleBinding**) для этого субъекта.
3. Проверка правил (**rules**) в связанной роли.

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

## Дополнительная информация

### Соответствие ресурсов и apiGroups

| Ресурс | API Group | Пример команды |
|--------|-----------|----------------|
| pods, services, configmaps | `""` (core) | `kubectl auth can-i get pods` |
| deployments, replicasets | `apps` | `kubectl auth can-i get deployments` |
| ingress | `networking.k8s.io` | `kubectl auth can-i get ingress` |
| cronjobs, jobs | `batch` | `kubectl auth can-i get jobs` |
| clusterrole, rolebinding | `rbac.authorization.k8s.io` | `kubectl auth can-i get roles` |

### Связанные ресурсы

- Обзор RBAC: [../../../../Security/rbac/rbac_overview.md](../../../../Security/rbac/rbac_overview.md)
- Роли: [../../../../Security/rbac/roles.md](../../../../Security/rbac/roles.md)
- Привязки: [../../../../Security/rbac/bindings.md](../../../../Security/rbac/bindings.md)
- Распространённые 403: [common.md](common.md)
- Диагностика: [diagnostics.md](diagnostics.md)
