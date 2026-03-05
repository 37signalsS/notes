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

### Историческая справка

В **Kubernetes 1.25** были удалены **Pod Security Policies (PSP)**. Kyverno рассматривался как одна из альтернатив для замены PSP, наряду с другими решениями:

| Решение | Тип | Преимущества | Недостатки |
|---------|-----|--------------|------------|
| **Kyverno** | Policy Engine | YAML-политики, нативная интеграция | Меньше зрелости чем OPA |
| **OPA Gatekeeper** | Policy Engine | Мощный язык Rego, большая экосистема | Сложнее в изучении |
| **Pod Security Admission (PSA)** | Built-in | Встроен в Kubernetes, простота | Ограниченный функционал |

### Сравнение с PSA

| Характеристика | PSA | Kyverno |
|----------------|-----|---------|
| **Сложность** | Низкая | Средняя |
| **Гибкость** | Ограниченная | Высокая |
| **Язык** | Labels/Annotations | YAML/JSON |
| **Мутация** | Нет | Да |
| **Генерация** | Нет | Да |
| **Отчеты** | Ограниченные | Policy Reports |

### Рекомендации по миграции с PSP

1. **Аудит текущих PSP**: Определить, какие ограничения использовались
2. **Выбор стратегии**: PSA для простых случаев, Kyverno для сложных
3. **Создание политик**: Перевод PSP в политики Kyverno
4. **Тестирование**: Включение режима `audit` перед `enforce`
5. **Постепенное внедрение**: Namespace-by-namespace миграция

### Пример: Замена PSP на Kyverno

**PSP (удалено в 1.25)**:

```yaml
apiVersion: policy/v1beta1
kind: PodSecurityPolicy
metadata:
  name: restricted
spec:
  privileged: false
  runAsUser:
    rule: MustRunAsNonRoot
  seLinux:
    rule: RunAsAny
  fsGroup:
    rule: RunAsAny
  supplementalGroups:
    rule: RunAsAny
  volumes:
    - 'configMap'
    - 'emptyDir'
    - 'projected'
    - 'secret'
    - 'downwardAPI'
    - 'persistentVolumeClaim'
```

**Kyverno (эквивалент)**:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: restricted-pss
spec:
  validationFailureAction: Enforce
  rules:
    - name: require-run-as-non-root
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "Containers must run as non-root"
        pattern:
          spec:
            securityContext:
              runAsNonRoot: true
    - name: restrict-volumes
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "Only allowed volume types"
        pattern:
          spec:
            volumes:
              - (configMap|emptyDir|projected|secret|downwardAPI|persistentVolumeClaim): {}
```

### Связанные темы

- [RBAC](../rbac/rbac_overview.md) — управление доступом в Kubernetes
- [Pod Security Context](../pod_security_context.md) — PSS/PSA для контроля безопасности
- [Установка](./install.md) — установка Kyverno с правильными правами
