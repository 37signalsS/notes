# Ошибка 403 Forbidden (Доступ запрещен): распространенные случаи

## Определения

**403 Forbidden (RBAC)** — состояние, при котором API-сервер успешно идентифицировал субъекта (аутентификация пройдена), но отклонил запрос, так как в системе **RBAC (Role-Based Access Control)** отсутствуют правила, разрешающие данному субъекту выполнение конкретного действия (`verb`) над указанным ресурсом (`resource`).

**403 Forbidden (Admission Control)** — отказ, возникающий на этапе контроля допуска. Даже если RBAC разрешает действие, запрос может быть заблокирован политиками безопасности (например, **Pod Security Admission**), квотами (**ResourceQuotas**) или внешними вебхуками.

> Подробное сравнение 401 vs 403: [definitions.md](definitions.md)
> Теория и архитектура RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)

## Основные концепции

### Структура сообщения об ошибке

Сообщение об ошибке от API-сервера является самодокументированным и содержит пять критических параметров для отладки:

```text
Error from server (Forbidden): <resource> is forbidden:
User "<subject>" cannot <verb> resource "<resource>"
in API group "<group>" in the namespace "<namespace>"
```

1.  **Subject:** Кто пытается выполнить действие (User, Group или ServiceAccount).
2.  **Verb:** Какое действие выполняется (`get`, `list`, `create`, `update`, `patch`, `delete`, `watch`).
3.  **Resource:** Тип объекта (`pods`, `secrets`, `deployments`, `pods/log`).
4.  **API Group:** Группа, к которой принадлежит ресурс (например, `apps`, `networking.k8s.io` или `""` для core).
5.  **Namespace:** Пространство имен, в котором запрашивается доступ (актуально для RoleBinding).

### Инструментарий для быстрой проверки

Основным инструментом является `kubectl auth can-i`. Использование флага `--as` (impersonation) позволяет проверить права от имени другого пользователя или ServiceAccount без переключения контекста `kubeconfig`.

```bash
# Проверка прав конкретного ServiceAccount
kubectl auth can-i <verb> <resource> \
  --as=system:serviceaccount:<namespace>:<sa-name> \
  -n <namespace>

# Пример: может ли приложение читать логи своих подов
kubectl auth can-i get pods/log \
  --as=system:serviceaccount:prod-ns:app-sa \
  -n prod-ns
# → yes / no
```

> Полный алгоритм и пошаговая диагностика: [diagnostics.md](diagnostics.md)

## Практические сценарии

### Сценарий 1: Чтение подов (отсутствует RoleBinding)

**Контекст:** Приложение (например, Prometheus или Service Discovery) пытается получить список подов в своем пространстве имен.

**Ошибка:** `User "system:serviceaccount:my-ns:my-sa" cannot list resource "pods" in API group ""`

**Решение:** Необходимо создать пару `Role` и `RoleBinding`.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
  namespace: my-ns
rules:
- apiGroups: [""] # Core API group
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

### Сценарий 2: Доступ к секретам (Least Privilege)

**Контекст:** Приложению требуется доступ к конкретному секрету с конфигурацией.

**Проблема:** Предоставление доступа ко всем секретам в namespace (`resources: ["secrets"]`) нарушает принцип наименьших привилегий.

**Решение:** Использование `resourceNames` для ограничения доступа.

```yaml
rules:
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["db-credentials", "api-keys"] # Доступ только к этим объектам
  verbs: ["get"]
```

### Сценарий 3: Управление ресурсами группы apps (Deployments)

**Контекст:** CI/CD конвейер или оператор пытается обновить `Deployment`.

**Ошибка:** `cannot patch resource "deployments" in API group "apps"`

**Особенность:** Ресурсы `deployments`, `statefulsets`, `daemonsets` и `replicasets` находятся в группе `apps`. Указание пустой группы `""` приведет к ошибке 403.

**Решение:**
```yaml
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

### Сценарий 4: Доступ к подресурсам (logs, exec, status)

**Контекст:** Администратору или инструменту автоматизации требуется доступ к логам или возможность выполнения команд внутри контейнера.

**Ошибка:** `cannot create resource "pods/exec" in API group ""`

**Особенность:** Права на `pods` не дают автоматического доступа к `pods/log` или `pods/exec`. Подресурсы указываются через слэш.

**Решение:**
```yaml
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log", "pods/exec"]
  verbs: ["get", "list", "create"] # exec требует 'create'
```

### Сценарий 5: Работа с Custom Resource Definitions (CRDs)

**Контекст:** Использование внешних контроллеров (Cert-Manager, Istio, Prometheus Operator).

**Ошибка:** `cannot list resource "certificates" in API group "cert-manager.io"`

**Решение:** Всегда проверяйте `apiGroup` кастомного ресурса через `kubectl get crd <name> -o yaml`.

```yaml
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["certificates", "issuers"]
  verbs: ["*"]
```

### Сценарий 6: Доступ к кластерным ресурсам через Role (Ошибочно)

**Контекст:** Попытка разрешить чтение списка `Namespaces` или `Nodes` с помощью объекта `Role`.

**Проблема:** `Role` и `RoleBinding` действуют только внутри одного пространства имен. Кластерные ресурсы (Nodes, Namespaces, PV, ClusterRoles) требуют использования `ClusterRole` и `ClusterRoleBinding`.

**Решение:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-reader
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: read-nodes-global
subjects:
- kind: User
  name: monitor-user
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: node-reader
  apiGroup: rbac.authorization.k8s.io
```

## Дополнительная информация

### Справочник API-групп и ресурсов

| Ресурс | API Group | Тип привязки (обычно) |
|--------|-----------|-----------------------|
| pods, services, configmaps, secrets, events | `""` (core) | Role |
| deployments, daemonsets, statefulsets | `apps` | Role |
| ingress, networkpolicies | `networking.k8s.io` | Role |
| jobs, cronjobs | `batch` | Role |
| horizontalpodautoscalers | `autoscaling` | Role |
| nodes, namespaces, persistentvolumes | `""` (core) | ClusterRole |
| storageclasses | `storage.k8s.io` | ClusterRole |
| certificates, issuers | `cert-manager.io` | Role / ClusterRole |

### Чек-лист для устранения 403 Forbidden

1.  **Множественное число:** Ресурсы в правилах ВСЕГДА во множественном числе (`pods`, а не `pod`).
2.  **API Group:** Проверьте группу через `kubectl api-resources`. Для ядра — `""`.
3.  **Namespace Match:** Убедитесь, что `ServiceAccount`, `Role` и `RoleBinding` находятся в одном пространстве имен (если не используется ClusterRole).
4.  **Verbs для подресурсов:** Помните, что `exec` и `portforward` требуют глагола `create`.
5.  **Impersonation:** Всегда проверяйте гипотезу через `kubectl auth can-i --as=...`.
6.  **Admission Control:** Если RBAC настроен верно, но ошибка сохраняется — проверьте события неймспейса (`kubectl get events`) на предмет блокировок PSA или квот.

### Связанные ресурсы

- [Алгоритмы диагностики 401/403](diagnostics.md)
- [Определения и модель безопасности API](definitions.md)
- [Расширенные сценарии (Admission, NodeRestriction)](advanced.md)
- [Объекты RBAC: детальный разбор](rbac_objects.md)
- [Официальная документация по RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
