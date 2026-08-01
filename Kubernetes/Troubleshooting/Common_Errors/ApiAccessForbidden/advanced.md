# Ошибка 403 Forbidden: расширенные сценарии и контроль допуска

## Определения

**Доступ к подресурсам API** — права на операции с вложенными объектами Kubernetes API (например, `pods/log`, `pods/exec`, `nodes/proxy`). Эти права не входят в базовый набор прав для основного ресурса и требуют явного перечисления в **RBAC**.

**Admission Control (Контроль допуска)** — механизмы API-сервера, которые проверяют запрос ПОСЛЕ успешной авторизации (RBAC). Если запрос нарушает политики безопасности или квоты, возвращается код **403 Forbidden**, даже если у пользователя есть полные права (включая `cluster-admin`).

**Impersonation (Имитация пользователя)** — механизм отладки, позволяющий проверять права доступа от имени другого субъекта, группы или UID.

## Основные концепции

### Источники ошибки 403 Forbidden

| Уровень проверки | Причина отказа | Типичный пример |
|------------------|----------------|-----------------|
| **RBAC** | Отсутствие прав в Role/ClusterRole | Нет прав на `list pods` |
| **PSA (Pod Security Admission)** | Нарушение профиля безопасности | Попытка запустить привилегированный контейнер |
| **NodeRestriction** | Попытка узла изменить чужой ресурс | Kubelet пытается обновить статус чужого узла |
| **Resource Quotas** | Превышение лимитов ресурсов | Запрет на создание пода из-за нехватки CPU/MEM |

### Продвинутая диагностика (Impersonation)

Для выявления сложных проблем доступа используйте флаги имитации. Это позволяет проверить, как API-сервер видит права конкретного ServiceAccount или внешней группы.

```bash
# Проверка прав ServiceAccount с имитацией
kubectl auth can-i list pods \
  --as=system:serviceaccount:my-ns:my-sa \
  -n my-ns

# Проверка прав группы (например, из OIDC/Azure AD)
kubectl auth can-i create deployments \
  --as=dev-user \
  --as-group=developers \
  -n project-x

# Проверка от имени конкретного UID (редкие случаи)
kubectl auth can-i get secrets --as=admin --as-uid=1000
```

> Пошаговая диагностика: [diagnostics.md](diagnostics.md)

## Практические сценарии

### Сценарий 1: Доступ к подресурсам (exec, logs, port-forward)

**Контокст:** Разработчику или инструменту автоматизации требуется доступ к логам или консоли пода.

**Ошибка:** `User "..." cannot create resource "pods/exec" in API group "" in the namespace "..."`

**Решение (YAML):**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-troubleshooter
  namespace: debug-ns
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log", "pods/exec", "pods/portforward"]
  verbs: ["get", "list", "create"] # Для exec/portforward нужен 'create'
```

### Сценарий 2: Pod Security Admission (PSA)

**Контекст:** Пользователь с правами `cluster-admin` не может запустить под в namespace.

**Ошибка:**
```text
Error from server (Forbidden): pods "my-pod" is forbidden: 
violates PodSecurity "restricted:latest": allowPrivilegeEscalation != false, 
unrestricted capabilities, runAsNonRoot != true
```

**Анализ:** Это не проблема RBAC. Namespace помечен меткой `pod-security.kubernetes.io/enforce=restricted`.
**Решение:** Привести манифест пода в соответствие с профилем безопасности (см. [Security Context в Kubernetes — Раздел PSA](../../../Security/pod_security_context.md#pod-security-standards-pss-и-pod-security-admission-psa)).

### Сценарий 3: NodeRestriction (Безопасность узлов)

**Контекст:** Специфический ServiceAccount, имитирующий поведение узла, или скомпрометированный kubelet пытается изменить объект, к которому не имеет отношения.

**Ошибка:**
```text
Error from server (Forbidden): nodes "other-node" is forbidden: 
node "this-node" is not allowed to modify node "other-node"
```

**Анализ:** Плагин `NodeRestriction` ограничивает права `kubelet` так, чтобы он мог изменять только "свои" объекты (Node, Pod, PV).
**Решение:** Проверить, почему запрос идет не к своему ресурсу. Исправить логику приложения/контроллера.

### Сценарий 4: Доступ к Custom Resource Definitions (CRDs)

**Контекст:** Оператор или CLI-инструмент работает с кастомными ресурсами (например, `PrometheusRule` или `Certificates`).

**Ошибка:** `cannot list resource "certificates" in API group "cert-manager.io"`

**Решение:** Всегда указывайте правильную `apiGroup`.
```yaml
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["certificates", "issuers"]
  verbs: ["get", "list", "watch"]
```

## Дополнительная информация

### Кластерные ресурсы vs Ресурсы неймспейса

Для ресурсов, не привязанных к неймспейсу, использование `Role` невозможно — всегда требуется `ClusterRole` и `ClusterRoleBinding`.

| Кластерные ресурсы | Ресурсы неймспейса |
|--------------------|--------------------|
| Nodes | Pods |
| Namespaces | Services |
| PersistentVolumes (PV) | ConfigMaps |
| PriorityClasses | RoleBindings |
| StorageClasses | Secrets |

### Ограничение доступа по именам (ResourceNames)

Для максимальной безопасности (Least Privilege) ограничивайте доступ к критическим объектам по их именам.

```yaml
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  resourceNames: ["shared-config"] # Только этот ConfigMap
  verbs: ["get", "update"]
```

### Связанные ресурсы

- Распространенные случаи (Namespaced): [common.md](common.md)
- Пошаговая диагностика: [diagnostics.md](diagnostics.md)
- Объекты RBAC (Role, Binding): [rbac_objects.md](rbac_objects.md)
- Роли и кластерные роли: [../../../Security/rbac/roles.md](../../../Security/rbac/roles.md)
