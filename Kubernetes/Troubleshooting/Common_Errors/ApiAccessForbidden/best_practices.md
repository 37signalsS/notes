# Api Access Forbidden: Best Practices

## Definitions

**RBAC Best Practices** — набор рекомендаций для предотвращения ошибок 401/403 и минимизации поверхности атаки при управлении доступом к Kubernetes API.

> Общие лучшие практики RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)

## Basic Concepts

### Ключевые принципы предотвращения 403

| Принцип | Что предотвращает | Как реализовать |
|---------|-------------------|-----------------|
| **Наименьшие привилегии** | Избыточные права, эскалацию | Конкретные `resources` + `verbs`, не `*` |
| **Namespace изоляция** | Доступ к чужим namespace | `Role` вместо `ClusterRole` |
| **Отключение automount** | Утечка токена из пода | `automountServiceAccountToken: false` |
| **Регулярный аудит** | Накопление лишних прав | `kubectl auth can-i --list`, `kubectl auth reconcile` |
| **Выделенные ServiceAccount** | Использование `default` SA | Создать SA для каждого приложения |

### Почему `default` ServiceAccount — риск

Каждый namespace имеет SA `default`, который автоматически монтируется в поды без явного указания. Злоумышленник, получивший доступ к такому поду, наследует все права `default` SA.

## Practical Scenarios

### Сценарий 1: Отключение автомонтирования токенов

**Проблема:** Токен ServiceAccount автоматически монтируется во все поды, даже если они не обращаются к API.

**Решение на уровне ServiceAccount:**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: default
  namespace: default
automountServiceAccountToken: false
```

**Решение на уровне Pod:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  automountServiceAccountToken: false
  serviceAccountName: my-sa
```

> Подробно в SSoT: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md#3-отключение-автомонтирования-токенов)

### Сценарий 2: Аудит RBAC — поиск опасных привязок

**Проблема:** Со временем накапливаются избыточные права, binding'и с `cluster-admin`, доступ для `system:unauthenticated`.

**Диагностика:**

```bash
# Поиск всех binding с cluster-admin
kubectl get clusterrolebinding -o yaml | \
  grep -B 10 "name: cluster-admin"

# Поиск binding для system:unauthenticated
kubectl get clusterrolebinding -o yaml | \
  grep -B 5 "system:unauthenticated"

# Проверка прав конкретного ServiceAccount
kubectl auth can-i --list --as=system:serviceaccount:<namespace>:<sa-name>

# Синхронизация манифеста с кластером (удаление лишних прав)
kubectl auth reconcile -f my-rbac-rules.yaml \
  --remove-extra-subjects --remove-extra-permissions
```

### Сценарий 3: Мониторинг и алерты на 401/403

**Проблема:** Ошибки аутентификации/авторизации обнаруживаются постфактум.

**Решение — Prometheus-алерты:**

```yaml
- alert: KubernetesAPIForbidden
  expr: sum(rate(rest_client_requests_total{code="403"}[5m])) > 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Обнаружены 403 ошибки к Kubernetes API"

- alert: KubernetesAPIUnauthorized
  expr: sum(rate(rest_client_requests_total{code="401"}[5m])) > 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Обнаружены 401 ошибки к Kubernetes API"
```

## Additional Information

### Чек-лист при создании нового ServiceAccount

1. Создать выделенный SA (не использовать `default`)
2. Установить `automountServiceAccountToken: false`
3. Создать Role с минимальными правами
4. Создать RoleBinding/ClusterRoleBinding
5. Проверить права: `kubectl auth can-i --list --as=system:serviceaccount:<ns>:<sa>`

### Связанные ресурсы

- SSoT — лучшие практики RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)
- Пошаговая диагностика: [diagnostics.md](diagnostics.md)
- Методы аутентификации и 401: [authentication_methods.md](authentication_methods.md)
- Расширенные сценарии 403: [advanced.md](advanced.md)
- RBAC объекты: [rbac_objects.md](rbac_objects.md)
