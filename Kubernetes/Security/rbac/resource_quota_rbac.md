# RBAC для ResourceQuota и LimitRange

## Определения

**ResourceQuota** — ресурс Kubernetes, ограничивающий суммарное потребление ресурсов (CPU, память, количество объектов) в пределах namespace. Не даёт одному租ant исчерпать ресурсы кластера.

**LimitRange** — ресурс Kubernetes, устанавливающий дефолтные и максимальные лимиты ресурсов для контейнеров и подов в namespace. Заполняет пропуски, если разработчик не указал limits/requests.

**Связь с RBAC:** RBAC определяет, кто может создавать, изменять и удалять ResourceQuota и LimitRange. Это критически важно для multi-tenancy: неправильные права могут позволить租ant исчерпать ресурсы или обойти ограничения.

**Важно:** ResourceQuota и LimitRange работают на уровне Admission Control (после RBAC). Даже если RBAC разрешает создание пода, ResourceQuota может заблокировать его, если квота исчерпана.

---

## Основные концепции

### RBAC-роли для управления квотами

| Роль | Описание | Типичный субъект |
|------|----------|-----------------|
| Cluster Admin | Полный доступ ко всем ResourceQuota/LimitRange | Платформенная команда |
| Namespace Admin | Управление квотами в пределах namespace | Team Lead |
| Namespace Developer | **Без доступа** к ResourceQuota/LimitRange | Разработчик |
| Quota Administrator | Изменение квот, но не удаление namespace | SRE/Platform |

### Кто может что

| Действие | ClusterRole | Namespace Role |
|----------|------------|---------------|
| `create` ResourceQuota | `cluster-admin` | `admin` (в namespace) |
| `update` ResourceQuota | `cluster-admin` | `admin` (в namespace) |
| `delete` ResourceQuota | `cluster-admin` | `admin` (в namespace) |
| `get`/`list` ResourceQuota | `view` (read-only) | `view` (read-only) |
| `create` LimitRange | `cluster-admin` | `admin` (в namespace) |
| `update` LimitRange | `cluster-admin` | `admin` (в namespace) |
| `delete` LimitRange | `cluster-admin` | `admin` (в namespace) |

**Паттерн «Минимальных привилегий»:** Разработчики **не должны** иметь доступ к управлению ResourceQuota/LimitRange. Они должны только видеть текущие лимиты (read-only).

---

## Практические сценарии

### Роль для управления квотами (Quota Administrator)

```yaml
# Кластерная роль для SRE-команды
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: quota-administrator
rules:
- apiGroups: [""]
  resources: ["resourcequotas", "limitranges"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["resourcequotas"]
  verbs: ["create", "update", "patch"]
- apiGroups: [""]
  resources: ["limitranges"]
  verbs: ["create", "update", "patch"]
# Нет delete — квоты удаляются только через GitOps/Change Management
---
# Привязка к SRE-группе в конкретном namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: quota-admin-binding
  namespace: production
subjects:
- kind: Group
  name: sre-team
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: quota-administrator
  apiGroup: rbac.authorization.k8s.io
```

### Роль для разработчика (read-only)

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: quota-viewer
  namespace: production
rules:
- apiGroups: [""]
  resources: ["resourcequotas", "limitranges"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: quota-viewer-binding
  namespace: production
subjects:
- kind: Group
  name: developers
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: quota-viewer
  apiGroup: rbac.authorization.k8s.io
```

### Запрет удаления ResourceQuota через OPA Gatekeeper

```yaml
# Constraint Template: запрет удаления ResourceQuota
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8sdenyquota deletion
spec:
  crd:
    spec:
      names:
        kind: K8sDenyQuotaDeletion
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        package k8sdenyquotadeletion
        violation[{"msg": msg}] {
          input.review.kind.kind == "ResourceQuota"
          input.review.operation == "DELETE"
          msg := "Удаление ResourceQuota запрещено политикой. Используйте GitOps для управления квотами."
        }
---
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sDenyQuotaDeletion
metadata:
  name: deny-quota-deletion
spec:
  match:
    kinds:
      - apiGroups: [""]
        kinds: ["ResourceQuota"]
```

### Проверка текущих квот через RBAC

```bash
# 1. Просмотр квот в namespace
kubectl get resourcequotas -n production
# → NAME              AGE   REQUEST                    LIMIT
# → compute-quota     7d    requests.cpu: 20/40        limits.cpu: 40/80
#                            requests.memory: 40Gi/80Gi limits.memory: 80Gi/160Gi

# 2. Детали конкретной квоты
kubectl describe resourcequota compute-quota -n production

# 3. Проверка: может ли пользователь создать под, не превышающий квоту?
kubectl auth can-i create pods --as=alice@example.com -n production
# → yes (RBAC разрешает, но ResourceQuota может заблокировать)

# 4. Проверка лимитов в namespace
kubectl get limitranges -n production
kubectl describe limitranges default-limits -n production

# 5. Проверка: какие ресурсы исчерпаны?
kubectl get resourcequotas -n production -o json | \
  jq '.items[].status'
```

### Диагностика: «Pod отклонён из-за квоты»

```bash
# 1. Проверка ошибки
kubectl describe pod <pod-name> -n production
# → Warning  FailedCreate  ... exceeded quota: compute-quota

# 2. Проверка текущего использования
kubectl get resourcequotas -n production -o yaml | \
  jq '.items[].status.used'

# 3. Проверка: какие поды исчерпывают квоту?
kubectl get pods -n production -o json | \
  jq '.items[] | {
    name: .metadata.name,
    cpu_req: (.spec.containers[]?.resources.requests.cpu // "0"),
    mem_req: (.spec.containers[]?.resources.requests.memory // "0")
  }'

# 4. Проверка: можно ли освободить квоту?
kubectl delete pod <unnecessary-pod> -n production
```

### Автоматическое создание квот для нового namespace

```yaml
# Kyverno: автоматическое создание ResourceQuota при создании Namespace
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: auto-quota
spec:
  rules:
  - name: create-default-quota
    match:
      any:
      - resources:
          kinds: [Namespace]
    generate:
      apiVersion: v1
      kind: ResourceQuota
      name: default-quota
      namespace: "{{request.object.metadata.name}}"
      synchronize: true
      data:
        spec:
          hard:
            requests.cpu: "10"
            requests.memory: "20Gi"
            limits.cpu: "20"
            limits.memory: "40Gi"
            pods: "50"
            services: "10"
            persistentvolumeclaims: "5"
  - name: create-default-limits
    match:
      any:
      - resources:
          kinds: [Namespace]
    generate:
      apiVersion: v1
      kind: LimitRange
      name: default-limits
      namespace: "{{request.object.metadata.name}}"
      synchronize: true
      data:
        spec:
          limits:
          - type: Container
            default:
              cpu: "500m"
              memory: "512Mi"
            defaultRequest:
              cpu: "100m"
              memory: "128Mi"
            max:
              cpu: "2"
              memory: "4Gi"
            min:
              cpu: "50m"
              memory: "64Mi"
```

---

## Дополнительная информация

### Interaction с RBAC

```
Запрос клиента → RBAC (разрешает/запрещает) → Admission (ResourceQuota/LimitRange проверяют) → etcd
```

- **RBAC** отвечает на вопрос: «Может ли субъект выполнять это действие?»
- **ResourceQuota** отвечает на вопрос: «Ещё есть ресурсы в namespace?»
- **LimitRange** отвечает на вопрос: «Соответствуют ли лимиты контейнера допустимым значениям?»

**Важно:** Если RBAC разрешает создание пода, но ResourceQuota исчерпан — под будет отклонён с ошибкой 403 Forbidden (адmission control). Это не RBAC-ошибка, а quota exhaustion.

### Best Practices

1. **GitOps для квот:** Храните ResourceQuota/LimitRange в Git, применяйте через CD-пайплайн. Не редактируйте через kubectl вручную.
2. **Read-only для разработчиков:** Разработчики должны видеть квоты, но не менять их.
3. **Audit квот:** Регулярно проверяйте использование квот через Prometheus/Grafana.
4. **Delegated management:** Используйте RoleBinding для делегирования управления квотами командам.
5. **Защита от удаления:** Запретите удаление ResourceQuota через OPA/Kyverno.

### Связанные темы

- **[Обзор RBAC](./rbac_overview.md)** — основы управления доступом
- **[OPA Gatekeeper и Kyverno](./limitations_opa.md)** — политики для защиты квот
- **[Multi-tenancy](../../Concepts/multi-tenancy.md)** — полная модель изоляции租ant
