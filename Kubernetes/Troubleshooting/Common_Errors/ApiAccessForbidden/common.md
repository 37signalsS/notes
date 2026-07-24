# Ошибка 403 Forbidden (Доступ запрещен): распространенные случаи

## Определения

**403 Forbidden (ресурсы в пространствах имен)** — ошибка возникает, когда субъект успешно прошел проверку личности (аутентификацию), но не имеет достаточных прав в системе **RBAC (Role-Based Access Control)** для выполнения конкретного действия над ресурсом в определенном пространстве имен (**namespace**).

**403 Forbidden (Admission Control)** — отказ API-сервера на этапе контроля допуска. Даже если RBAC разрешает действие, политики безопасности (например, PSA) могут заблокировать запрос.

> Различие 401 vs 403: [definitions.md](definitions.md)
> Общие лучшие практики RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)

## Основные концепции

### Шаблон сообщения об ошибке

Стандартный ответ API-сервера содержит все детали, необходимые для идентификации проблемы:

```text
Error from server (Forbidden): <resource> is forbidden:
User "<subject>" cannot <verb> resource "<resource>"
in API group "<group>" in the namespace "<namespace>"
```

### Алгоритм быстрого решения

1. **Извлечь данные** из сообщения: кто (`subject`), что делает (`verb`), над чем (`resource`), в какой группе (`apiGroup`) и где (`namespace`).
2. **Проверить Role:** существует ли роль с подходящими `resources` и `verbs`.
3. **Проверить RoleBinding:** привязан ли нужный `subject` к этой роли в целевом namespace.
4. **Устранить разрыв:** создать или дополнить Role/RoleBinding.

### Инструменты диагностики

Основной инструмент для проверки прав — `kubectl auth can-i`. Рекомендуется использовать механизм **impersonation** (выполнение от имени другого пользователя) для точной имитации условий ошибки.

```bash
# Проверка прав конкретного ServiceAccount
kubectl auth can-i <verb> <resource> --as=system:serviceaccount:<namespace>:<sa-name> -n <namespace>

# Пример: может ли SA 'my-sa' получать список секретов в 'my-ns'
kubectl auth can-i list secrets --as=system:serviceaccount:my-ns:my-sa -n my-ns
# → no
```

> Пошаговая диагностика: [diagnostics.md](diagnostics.md)

## Практические сценарии

### Сценарий 1: Чтение подов (отсутствует RoleBinding)

**Контекст:** Приложение пытается получить список подов в своем пространстве имен для обнаружения соседей.

**Сообщение:**
```text
Error from server (Forbidden): pods is forbidden:
User "system:serviceaccount:my-ns:my-sa" cannot list resource "pods"
in API group "" in the namespace "my-ns"
```

**Решение (YAML):**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
  namespace: my-ns
rules:
- apiGroups: [""] # "" указывает на core API group
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

### Сценарий 2: Доступ к секретам (Secrets)

**Контекст:** Приложению требуется прочитать `Secrets` для получения учетных данных базы данных.

**Внимание:** Предоставляйте доступ к секретам только по необходимости. Используйте `resourceNames` для ограничения доступа конкретными объектами.

**Решение (ограниченный доступ):**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: db-secret-reader
  namespace: my-ns
rules:
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["db-credentials"] # Доступ только к этому секрету
  verbs: ["get"]
```

### Сценарий 3: Создание/удаление Deployment (группа apps)

**Контекст:** CI/CD конвейер или оператор пытается управлять ресурсами `Deployment`.

**Ошибка:** `deployments is forbidden: User "..." cannot create resource "deployments" in API group "apps"`

**Особенность:** `deployments` принадлежат API-группе `apps`. Использование пустой строки `""` в `apiGroups` является частой ошибкой.

**Решение:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: deployment-manager
  namespace: my-ns
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets"]
  verbs: ["get", "list", "create", "update", "patch", "delete"]
```

## Дополнительная информация

### Таблица API-групп для часто используемых ресурсов

| Ресурс | API Group | Тип роли |
|--------|-----------|----------|
| pods, services, configmaps, secrets, events | `""` (core) | Role |
| deployments, daemonsets, statefulsets | `apps` | Role |
| ingress, networkpolicies | `networking.k8s.io` | Role |
| jobs, cronjobs | `batch` | Role |
| horizontalpodautoscalers | `autoscaling` | Role |
| persistentvolumeclaims | `""` | Role |

### Частые причины ошибок (чек-лист)

1.  **Множественное число:** Ресурсы в правилах ВСЕГДА во множественном числе (`pods`, `services`, `secrets`).
2.  **Верная API Group:** Проверьте группу ресурса (например, `ingress` в `networking.k8s.io`).
3.  **Соответствие Namespace:** Проверьте, что `Role` и `RoleBinding` созданы в том же пространстве имен, где находится ресурс и субъект.
4.  **Подресурсы:** Для доступа к логам (`pods/log`) или статусу требуется явное указание подресурса.
5.  **Pod Security Admission (PSA):** Если RBAC корректен, но создание подов запрещено — проверьте метки пространства имен на соответствие политикам безопасности (`privileged`, `baseline`, `restricted`).

### Связанные ресурсы

- Роли и кластерные роли: [../../../Security/rbac/roles.md](../../../Security/rbac/roles.md)
- Пошаговая диагностика: [diagnostics.md](diagnostics.md)
- Расширенные сценарии (Cluster-wide): [advanced.md](advanced.md)
- Определения ошибок 401/403: [definitions.md](definitions.md)
