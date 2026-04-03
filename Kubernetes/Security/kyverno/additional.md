# Дополнительная информация Kyverno

## Определения

**Aggregated Cluster Roles** — механизм Kubernetes для динамического расширения прав через лейблы. Используется Kyverno для получения прав на создание и управление ресурсами.

---

## Basic Concepts

### Aggregated Cluster Roles в Kyverno

По умолчанию Kyverno не имеет прав на создание некоторых ресурсов (например, `Secret`). Для расширения прав используются **Aggregated Cluster Roles**.

**Механизм работы**:

1. Создается `ClusterRole` с лейблом `kyverno.io/aggregate-to-<controller>-controller: "true"`
2. Kubernetes автоматически агрегирует права из этого `ClusterRole` в соответствующий контроллер
3. Контроллер получает дополнительные права без изменения основных ролей

### Контроллеры Kyverno

| Контроллер | Лейбл для агрегации | Назначение |
|------------|---------------------|------------|
| **admission-controller** | `kyverno.io/aggregate-to-admission-controller: "true"` | Обработка admission webhooks |
| **background-controller** | `kyverno.io/aggregate-to-background-controller: "true"` | Фоновое сканирование и генерация ресурсов |
| **reports-controller** | `kyverno.io/aggregate-to-reports-controller: "true"` | Обработка Policy Reports |
| **cleanup-controller** | `kyverno.io/aggregate-to-cleanup-controller: "true"` | Удаление ресурсов по расписанию |

---

## Practical Scenarios

### Пример: Права для генерации Secret

Для генерации `Secret` необходимы права `create` на ресурсы `Secret`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kyverno-generate-secret
  labels:
    kyverno.io/aggregate-to-background-controller: "true"
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["create", "update", "delete", "get", "list", "watch"]
```

### Пример: Права для генерации NetworkPolicy

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kyverno-generate-network-policy
  labels:
    kyverno.io/aggregate-to-background-controller: "true"
rules:
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies"]
    verbs: ["create", "update", "delete", "get", "list", "watch"]
```

### Пример: Права для работы с ConfigMap

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kyverno-manage-configmap
  labels:
    kyverno.io/aggregate-to-admission-controller: "true"
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list", "watch"]
```

### Проверка агрегированных прав

```bash
# Проверка ClusterRole с лейблами
kubectl get clusterrole -l kyverno.io/aggregate-to-background-controller

# Проверка агрегированных прав
kubectl get clusterrole kyverno:background -o yaml

# Проверка прав контроллера
kubectl auth can-i create secrets --as=system:serviceaccount:kyverno:kyverno-background-controller
```

### Политика генерации Secret

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: generate-docker-registry-secret
spec:
  rules:
    - name: generate-secret
      match:
        resources:
          kinds:
            - Namespace
      generate:
        kind: Secret
        name: docker-registry-credentials
        namespace: "{{request.object.metadata.name}}"
        synchronize: true
        data:
          type: kubernetes.io/dockerconfigjson
          data:
            .dockerconfigjson: |
              {"auths":{...}}
```

---

## Additional Information

### Связанные темы

- [RBAC](../rbac/rbac_overview.md) — управление доступом в Kubernetes
- [Агрегация ролей](../rbac/aggregation_scenarios.md) — общий механизм Aggregated ClusterRoles
- [Pod Security Context](../pod_security_context.md) — PSS/PSA, миграция с PSP
- [Установка Kyverno](./install.md) — установка и настройка
- [Основные концепции](./concepts.md) — сравнение Kyverno с PSA/OPA/Falco
