# Эскалация привилегий: векторы атак и защита

## Определения

**Эскалация привилегий (Privilege Escalation)** — процесс получения пользователем или процессом прав, превышающих изначально выданные. В контексте Kubernetes RBAC это означает выход за рамки назначенных Role/ClusterRole.

**Три критических глагола RBAC, связанных с эскалацией:**

- **`bind`** — позволяет привязывать роли к субъектам. Злоумышленник может привязать `cluster-admin` к себе.
- **`escalate`** — позволяет расширять права собственной роли. Злоумышленник может добавить в свою Role любые правила.
- **`impersonate`** — позволяет действовать от имени другого субъекта. Злоумышленник может представиться `system:masters`.

**Принцип наименьших привилгий (PoLP)** — фундаментальная защита: выдавайте только минимум прав, необходимых для задачи. Избегайте `*` в глаголах и ресурсах.

---

## Основные концепции

### Как работает эскалация через `bind`

Если пользователь имеет право `bind` на `rolebindings`/`clusterrolebindings`, он может привязать **любую роль** к **любому субъекту** (включая себя):

```yaml
# Злоумышленник с правами bind создает:
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: my-escalated-binding
subjects:
- kind: User
  name: attacker@example.com  # Сам себя
roleRef:
  kind: ClusterRole
  name: cluster-admin  # Полный доступ
  apiGroup: rbac.authorization.k8s.io
```

**Результат:** `attacker@example.com` получает полный доступ ко всему кластеру.

### Как работает эскалация через `escalate`

Если пользователь имеет право `escalate` на `roles`/`clusterroles`, он может редактировать свою собственную роль, добавляя любые правила:

```yaml
# Злоумышленник изменяет свою существующую роль:
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: my-limited-role
  namespace: production
rules:
# Было:
# - apiGroups: [""]
#   resources: ["pods"]
#   verbs: ["get", "list"]

# Стало после эскалации:
- apiGroups: [""]
  resources: ["secrets"]  # Добавил доступ к секретам
  verbs: ["get", "list"]
- apiGroups: ["rbac.authorization.k8s.io"]
  resources: ["roles", "rolebindings"]  # Добавил bind для дальнейшей эскалации
  verbs: ["create", "update", "patch"]
```

### Как работает эскалация через `impersonate`

Если пользователь имеет право `impersonate` на `users`, он может выступать от имени любого субъекта:

```bash
# Злоумышленник с impersonate отправляет запрос от имени system:masters
kubectl get pods --as=system:masters --as-group=system:masters
# → Получает полный доступ кластера
```

**Риски impersonate:**
- Нет mechanisms для ограничения impersonation через RBAC (если право выдано — оно действует)
- Все действия записываются в аудит с указанием реального отправителя, но это не мешает выполнению
- Компрометация SA с impersonate = компрометация кластера

### Встроенные защиты Kubernetes

| Защита | Описание |
|--------|----------|
| **RBAC на impersonate** | Для impersonate required `verb=impersonate` на ресурс `users`/`groups`/`serviceaccounts` |
| **system:masters** | Члены группы `system:masters` обходят все проверки RBAC. Не добавляйте пользователей в эту группу. |
| **Контроллер Node** | Модуль `Node` authorizer ограничивает Kubelet только ресурсами на его ноде |
| **NodeRestriction** | Admission controller ограничивает Kubelet в изменении node/pod STATUS |
| **Audit logging** | Все impersonate-действия логируются с реальным отправителем |

---

## Практические сценарии

### Сценарий 1: Атака через `bind`

**Условие:** Пользователь `dev-user` имеет RoleBinding с ролью, содержащей `verb: bind` на `rolebindings`.

```bash
# 1. Проверка: есть ли у dev-user право bind?
kubectl auth can-i create rolebindings --as=dev-user
# → yes

# 2. Атака: dev-user привязывает себя к cluster-admin
kubectl create clusterrolebinding my-escalation \
  --clusterrole=cluster-admin \
  --user=dev-user
# → clusterrolebinding.rbac.authorization.k8s.io/my-escalation created

# 3. Проверка: dev-user теперь cluster-admin?
kubectl auth can-i '*' '*' --as=dev-user
# → yes

# 4. Откат: удалить bindings
kubectl delete clusterrolebinding my-escalation
```

**Защита:**
```yaml
# НЕ выдавайте bind без необходимости
# Если bind нужен — ограничивайте конкретными ролями:
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: limited-bind
rules:
- apiGroups: ["rbac.authorization.k8s.io"]
  resources: ["rolebindings"]
  verbs: ["create", "update"]
  # Ограничение конкретными ролями:
  # (不行 через RBAC — нет механизма deny или conditions)
  # Используйте OPA/Kyverno для ограничения roleRef:
  # deny в roleRef.name != "view" && roleRef.name != "edit"
```

### Сценарий 2: Атака через `escalate`

**Условие:** Пользователь `namespace-admin` имеет RoleBinding с ролью, содержащей `verb: escalate` на `roles`.

```yaml
# 1. Атака: admin изменяет свою роль, добавляя себе права
kubectl patch role namespace-admin-role -n production --type=merge \
  -p '{"rules":[{"apiGroups":["rbac.authorization.k8s.io"],"resources":["roles","rolebindings"],"verbs":["create","update","patch","delete","bind","escalate"]}]}'

# 2. Теперь admin может:
# - Создавать привязки к cluster-admin (bind)
# - Расширять другие роли (escalate)
# - Распространять права на другие namespace (через clusterrole + rolebinding)
```

**Защита через Kyverno:**
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: deny-self-escalation
spec:
  validationFailureAction: Enforce
  rules:
  - name: block-role-escalation
    match:
      any:
      - resources:
          kinds: ["Role"]
          operations: ["create", "update", "patch"]
    validate:
      message: "Добавление глаголов bind/escalate в Role запрещено политикой безопасности."
      deny:
        conditions:
          all:
          - key: "{{request.object.rules[]?.verbs[]}}"
            operator: AnyIn
            value: ["bind", "escalate"]
```

### Сценарий 3: Атака через `impersonate`

**Условие:** Пользователь `auditor` имеет ClusterRole с `verb: impersonate` на `users`.

```bash
# 1. Проверка: может ли auditor имперсонировать?
kubectl auth can-i impersonate users --as=auditor
# → yes

# 2. Атака: auditor действует от имени system:masters
kubectl get secrets -A --as=system:masters
# → Получает доступ ко всем секретам кластера

# 3. В аудит-логах будет запись:
# user.username=auditor, impersonatedUser.username=system:masters
```

**Защита:**
```yaml
# Ограничивайте impersonate конкретными пользователями/группами
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: audit-impersonator
rules:
- apiGroups: [""]
  resources: ["users"]
  verbs: ["impersonate"]
  # Ограничение по конкретному имени:
  resourceNames: ["dev-user", "staging-user"]
  # НЕ используйте: resourceNames: ["system:masters"]
```

### Автоматический поиск избыточных привилегий

```bash
#!/bin/bash
# audit_escalation_risks.sh — поиск рисков эскалации

echo "=== Поиск ClusterRoleBinding на cluster-admin (кроме системных) ==="
kubectl get clusterrolebindings -o json | \
  jq -r '.items[] |
    select(.roleRef.name == "cluster-admin") |
    select(.subjects[]?.name | test("^system:") | not) |
    "\(.metadata.name): \(.subjects[]?.kind)/\(.subjects[]?.name)"'

echo ""
echo "=== Поиск RoleBinding с bind/escalate/impersonate ==="
kubectl get rolebindings,clusterrolebindings -A -o json | \
  jq -r '.items[] |
    select(.roleRef.name != "cluster-admin") |
    . as $binding |
    $binding.metadata.namespace // "cluster" as $ns |
    $binding.metadata.name as $name |
    $binding.roleRef.name as $role |
    $role | @base64d | . as $decoded |
    {ns: $ns, name: $name, role: $role} |
    "\(.ns)/\(.name) -> \(.role)"'

echo ""
echo "=== Поиск Roles с bind/escalate/impersonate ==="
kubectl get roles,clusterroles -A -o json | \
  jq -r '.items[] |
    select(.rules[]?.verbs[]? == "bind" or .rules[]?.verbs[]? == "escalate" or .rules[]?.verbs[]? == "impersonate") |
    "\(.metadata.namespace // "cluster")/\(.metadata.name): \(
      [.rules[] | select(.verbs[]? == "bind" or .verbs[]? == "escalate" or .verbs[]? == "impersonate") | .verbs[]] | unique | join(", ")
    )"'

echo ""
echo "=== Поиск SA с доступом к secrets ==="
kubectl get rolebindings,clusterrolebindings -A -o json | \
  jq -r '.items[] |
    select(.subjects[]?.kind == "ServiceAccount") |
    . as $binding |
    $binding.metadata.namespace // "cluster" as $ns |
    $binding.metadata.name as $name |
    $binding.roleRef.name as $role |
    {ns: $ns, name: $name, role: $role} |
    "\(.ns)/\(.name) -> \(.role)"'
```

### Защитный чек-лист

| Проверка | Команда | Ожидаемый результат |
|----------|---------|-------------------|
| Есть ли `cluster-admin` привязки кроме системных? | `kubectl get clusterrolebindings -o json \| jq '.items[] \| select(.roleRef.name=="cluster-admin")'` | Только `system:masters` |
| Есть ли Roles с bind/escalate? | `kubectl get roles,clusterroles -A -o json \| jq '.items[] \| select(.rules[]?.verbs[]? == "bind" or .rules[]?.verbs[]? == "escalate")'` | Пустой результат |
| Есть ли impersonate-привязки? | `kubectl get clusterrolebindings -o json \| jq '.items[] \| select(.subjects[]?.name \| test("system:masters"))'` | Пустой результат |
| SA с `list` на secrets? | `kubectl auth can-i list secrets --as=system:serviceaccount:prod:app-sa -n prod` | `no` (если SA не должен) |
| Используется ли default SA? | `kubectl get pods -A -o jsonpath='{.items[?(@.spec.serviceAccountName=="default")].metadata.name}'` | Пустой результат |

---

## Дополнительная информация

### Инструменты аудита

| Инструмент | Назначение |
|-----------|-----------|
| `kubectl auth can-i --list` | Быстрый просмотр всех прав |
| `rakkess` | Интерактивный анализ прав доступа |
| `rbac-lookup` | Поиск ролей по субъекту |
| `kubescape` | Сканирование на избыточные привилегии |
| `kube-bench` | Проверка CIS-бенчмарка (включая RBAC) |

### Ограничения защиты

- **RBAC не поддерживает deny:** нельзя явно запретить действие. Если любая привязка разрешает — оно разрешено.
- **system:masters не блокируется:** членство в этой группе полностью обходит RBAC. Контроль — только на уровне аутентификации (OIDC, сертификаты).
- **ResourceNames не работает с create:** нельзя ограничить создание конкретных имен через RBAC.
- **Audit задерживается:** аудит-логи записываются с задержкой. Эскалация через bind может быть выполнена до обнаружения.

### Связанные темы

- **[Обзор RBAC](./rbac_overview.md)** — модель разрешений (аддитивность, deny-by-default)
- **[Роли и ClusterRole](./roles.md)** — описание глаголов bind, escalate, impersonate
- **[Субъекты доступа](./subjects.md)** — impersonate через HTTP-заголовки
- **[OPA Gatekeeper и Kyverno](./limitations_opa.md)** — политики для защиты от эскалации
