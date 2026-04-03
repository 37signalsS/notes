# CreateContainerConfigError: Проблемы с RBAC

## Definitions

**RBAC-related CreateContainerConfigError** — ошибка, возникающая когда ServiceAccount пода не имеет прав на чтение ConfigMap, Secret или других ресурсов, необходимых для создания конфигурации контейнера.

## Basic Concepts

### Типичное сообщение об ошибке

```
user "system:serviceaccount:default:default" cannot get resource "configmaps"
in API group "" in the namespace "default"
```

### Механизм ошибки

```
Pod использует ServiceAccount
         ↓
kubelet запрашивает ресурс (ConfigMap/Secret) от имени SA
         ↓
API-сервер проверяет RBAC-права SA
         ↓
❌ Нет прав get/list → CreateContainerConfigError
```

### Почему это происходит

| Причина | Описание |
|---------|----------|
| **Default ServiceAccount** | Pod использует SA `default` без настроенных прав |
| **Role отсутствует** | Нет Role с правами на нужный ресурс |
| **RoleBinding отсутствует** | Role существует, но не привязана к SA пода |
| **Namespace mismatch** | RoleBinding в другом namespace |
| **Неверный apiGroup** | В rules указан неверный apiGroup для ресурса |

> Общие концепции RBAC: [rbac_overview.md](../../../Security/rbac/rbac_overview.md).

## Practical Scenarios

### Сценарий 1: Диагностика RBAC-прав

```bash
# Проверка: может ли SA читать ConfigMap
kubectl auth can-i get configmaps \
  --as=system:serviceaccount:<namespace>:<sa-name> \
  -n <namespace>

# Проверка: может ли SA читать Secrets
kubectl auth can-i get secrets \
  --as=system:serviceaccount:<namespace>:<sa-name> \
  -n <namespace>

# Проверка всех прав SA
kubectl auth can-i --list \
  --as=system:serviceaccount:<namespace>:<sa-name> \
  -n <namespace>
```

### Сценарий 2: Создание Role и RoleBinding

**Проблема:** SA пода не имеет прав на ConfigMap/Secret.

**Решение:** Создать Role с минимальными правами и привязать к SA.

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

### Сценарий 3: Проверка ServiceAccount пода

```bash
# Узнать SA пода
kubectl get pod <pod-name> -n <namespace> \
  -o jsonpath='{.spec.serviceAccountName}'

# Проверить, существует ли SA
kubectl get serviceaccount <sa-name> -n <namespace>
```

Если поле `serviceAccountName` пустое — используется `default`.

### Сценарий 4: Namespace mismatch

**Симптом:** RoleBinding существует, но ошибка сохраняется.

**Причина:** RoleBinding и Pod находятся в разных namespace.

**Диагностика:**

```bash
# Namespace RoleBinding
kubectl get rolebinding <binding-name> -n <namespace-a>

# Namespace Pod
kubectl get pod <pod-name> -n <namespace-b>
```

**Решение:** RoleBinding всегда работает на уровне namespace — создать в том же namespace, где находится Pod.

### Сценарий 5: Неверный apiGroup в rules

**Симптом:** RoleBinding есть, но `auth can-i` возвращает `no`.

**Причина:** В rules указан неверный `apiGroups`.

| Ресурс | apiGroup |
|--------|----------|
| ConfigMap, Secret, Pod, Service | `""` (core, пустая строка) |
| Deployment, ReplicaSet | `"apps"` |
| Role, RoleBinding | `"rbac.authorization.k8s.io"` |
| Ingress | `"networking.k8s.io"` |

**Частая ошибка:** `apiGroups: ["configmaps"]` вместо `apiGroups: [""]`.

## Additional Information

### Связанные ресурсы

- Определения: [definitions.md](./definitions.md)
- Диагностика: [diagnostics.md](./diagnostics.md)
- RBAC overview (SSoT): [rbac_overview.md](../../../Security/rbac/rbac_overview.md)
- Roles: [roles.md](../../../Security/rbac/roles.md)
- Bindings: [bindings.md](../../../Security/rbac/bindings.md)
