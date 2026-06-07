# Ошибка 403 Forbidden (Api Access Forbidden): расширенные сценарии

## Определения

**Доступ к подресурсам API (Application Programming Interface)** — доступ к вложенным ресурсам Kubernetes API (например, `pods/log`, `nodes/metrics`, `nodes/proxy`), который требует отдельного явного разрешения в правилах **RBAC (Role-Based Access Control — управление доступом на основе ролей)**.

**Кросс-пространственный доступ (Cross-namespace access)** — доступ к ресурсам во всех пространствах имён (namespace) кластера одновременно или к ресурсам вне пространств имён (узлы, **PV (PersistentVolume)**), требующий использования `ClusterRole`.

## Основные концепции

### Когда требуются расширенные права

Стандартные роли `Role` и привязки `RoleBinding` обеспечивают доступ к основным ресурсам в рамках одного пространства имён. Расширенные сценарии необходимы в следующих случаях:

| Ресурс | Цель доступа | Тип роли |
|--------|--------------|----------|
| `pods/log` | Сбор логов (Fluent Bit, Filebeat, Loki) | ClusterRole |
| `nodes`, `nodes/metrics` | Мониторинг узлов (Prometheus, metrics-server) | ClusterRole |
| `namespaces` | Получение списка пространств имён кластера | ClusterRole |

### Диагностика расширенных прав

```bash
# Проверка прав на подресурс
kubectl auth can-i get pods/log \
  --as=system:serviceaccount:<namespace>:<sa-name> \
  -n <namespace>

# Проверка прав на узлы (Nodes)
kubectl auth can-i get nodes \
  --as=system:serviceaccount:<namespace>:<sa-name>

# Проверка прав на пространства имён (Namespaces)
kubectl auth can-i get namespaces \
  --as=system:serviceaccount:<namespace>:<sa-name>
```

> Пошаговая диагностика: [diagnostics.md](diagnostics.md)

## Практические сценарии

### Сценарий 1: Доступ к pods/log (сборщик логов)

**Контекст:** Контейнер-сборщик логов (Fluent Bit, Filebeat, Loki Promtail) пытается читать логи подов во всех пространствах имён.

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

### Сценарий 2: Доступ к узлам (Nodes) и метрикам (Мониторинг)

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

### Сценарий 3: Доступ к пространствам имён (Namespaces)

**Контекст:** Приложение пытается получить список пространств имён или информацию о своём пространстве имён для динамического обнаружения сервисов.

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

## Дополнительная информация

### Использование ClusterRole вместо Role

Для ресурсов `pods/log` (при доступе ко всем пространствам имён), `nodes` и `namespaces` требуется доступ на уровне кластера. Объект `Role` ограничен одним пространством имён и не может предоставить доступ к:

- Узлам кластера (Nodes) — это кластерный ресурс.
- Пространствам имён (Namespaces) — это кластерный ресурс.
- Подресурсам или ресурсам в других пространствах имён (например, чтение логов по всему кластеру).

Подробное сравнение `Role` и `ClusterRole` приведено в разделе **[Роли и кластерные роли](../../../Security/rbac/roles.md#sravnenie-role-i-clusterrole)**.

### Связанные ресурсы

- Распространённые случаи 403 (Namespaced): [common.md](common.md)
- Пошаговая диагностика: [diagnostics.md](diagnostics.md)
- Роли и кластерные роли: [../../../Security/rbac/roles.md](../../../Security/rbac/roles.md)
