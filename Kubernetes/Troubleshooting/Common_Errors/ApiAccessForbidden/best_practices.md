# Api Access Forbidden: Best Practices

## Best Practices

| Практика | Описание |
|----------|----------|
| **Принцип наименьших привилегий** | Давайте только необходимые права |
| **Namespace изоляция** | Используйте Role вместо ClusterRole |
| **Отключение automountServiceAccountToken** | Для подов, не нуждающихся в API |
| **Регулярный аудит** | `kubectl auth can-i --list` |
| **Избегайте cluster-admin** | Только для администраторов кластера |

### Отключение автомонтирования токенов

```yaml
# Глобально для namespace
apiVersion: v1
kind: ServiceAccount
metadata:
  name: default
  namespace: default
automountServiceAccountToken: false

# Индивидуально для Pod
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  automountServiceAccountToken: false
  serviceAccountName: my-sa
```

### Аудит RBAC

```bash
# Поиск всех binding с cluster-admin
kubectl get clusterrolebinding -o yaml | \
  grep -B 10 "name: cluster-admin"

# Поиск binding для system:unauthenticated
kubectl get clusterrolebinding -o yaml | \
  grep -B 5 "system:unauthenticated"

# Проверка прав текущего пользователя
kubectl auth can-i --list
```

### Мониторинг и алерты

```yaml
# Prometheus alert для 403 ошибок
- alert: KubernetesAPIForbidden
  expr: sum(rate(rest_client_requests_total{code="403"}[5m])) > 0
  for: 5m
  labels:
    severity: warning

- alert: KubernetesAPIUnauthorized
  expr: sum(rate(rest_client_requests_total{code="401"}[5m])) > 0
  for: 5m
  labels:
    severity: warning
```

## Ссылки

- [Kubernetes RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
- [Authenticate ServiceAccount](https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/)
- [RBAC Good Practices](https://kubernetes.io/docs/concepts/security/rbac-good-practices/)
