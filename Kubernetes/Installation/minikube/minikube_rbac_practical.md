# Minikube: практика RBAC (Role-Based Access Control)

## Определения

**RBAC (Role-Based Access Control)** — основной механизм авторизации в Kubernetes, определяющий «кто» (субъект) может выполнять «что» (действия) с «какими» ресурсами. Подробнее: [RBAC: Overview](../../../Security/rbac/rbac_overview.md).

**Role** — набор правил (permissions), ограниченный конкретным Namespace. Определяет разрешения на API-глаголы (`get`, `list`, `create`, `delete`) для конкретных ресурсов.

**ClusterRole** — аналог Role, но применяемый на уровне кластера (для кластерных ресурсов: nodes, persistentVolumes) или к нескольким Namespace одновременно.

**RoleBinding / ClusterRoleBinding** — связывает Role/ClusterRole с субъектом (User, Group, ServiceAccount).

**ServiceAccount** — специальный субъект для подов. Каждый под ассоциируется с ServiceAccount, через который он аутентифицируется в API-сервере.

---

## Базовые концепции

### RBAC в Minikube

| Аспект | Описание |
| :--- | :--- |
| **По умолчанию** | RBAC включён (`--authorization-mode=RBAC`) |
| **Администратор** | `minikube` user с cluster-admin (через ~/.kube/config) |
| **Дополнительные SA** | Создаются через `kubectl create serviceaccount` |
| **Проверка доступа** | `kubectl auth can-i <verb> <resource>` |

### Зачем тестировать RBAC в Minikube

- Настройка минимальных привилегий для ServiceAccount приложения.
- Проверка политик перед деплоем в production (где RBAC строже).
- Отладка ошибок `Forbidden` (403) при деплое.
- Тестирование OPA/Gatekeeper или Kyverno политик, зависимых от RBAC.

---

## Практические сценарии

### Шаг 1: Проверка текущего RBAC

```bash
# Кто я? (какой контекст используется)
kubectl config current-context
# → minikube

# Какие права есть у текущего пользователя?
kubectl auth can-i --list
# → Resources   Non-Resource URLs   Verbs
# → *.*         []                  [*]     ← cluster-admin

# Проверка конкретного действия
kubectl auth can-i create pods
# → yes
kubectl auth can-i delete nodes
# → yes (cluster-admin)
```

### Шаг 2: Создание ServiceAccount для приложения

```yaml
# app-serviceaccount.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: app-ns
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: app-sa
  namespace: app-ns
```

```bash
kubectl apply -f app-serviceaccount.yaml

# Проверка
kubectl get sa -n app-ns
# → NAME      SECRETS   AGE
# → app-sa    0         10s
```

### Шаг 3: Ограничение прав через Role

```yaml
# app-role.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: app-reader
  namespace: app-ns
rules:
# Разрешено: читать Pods, Services, ConfigMaps
- apiGroups: [""]
  resources: ["pods", "services", "configmaps"]
  verbs: ["get", "list", "watch"]
# Разрешено: читать Deployments
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list"]
# Запрещено: создавать/удалять поды
# (отсутствие verbs = запрет)
```

```yaml
# app-rolebinding.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: app-reader-binding
  namespace: app-ns
subjects:
- kind: ServiceAccount
  name: app-sa
  namespace: app-ns
roleRef:
  kind: Role
  name: app-reader
  apiGroup: rbac.authorization.k8s.io
```

```bash
kubectl apply -f app-role.yaml
kubectl apply -f app-rolebinding.yaml
```

### Шаг 4: Проверка прав ServiceAccount

```bash
# Проверка прав SA "app-sa" в namespace "app-ns"
kubectl auth can-i get pods --namespace=app-ns --as=system:serviceaccount:app-ns:app-sa
# → yes
kubectl auth can-i list pods --namespace=app-ns --as=system:serviceaccount:app-ns:app-sa
# → yes
kubectl auth can-i create pods --namespace=app-ns --as=system:serviceaccount:app-ns:app-sa
# → no  ← Role не разрешает создание
kubectl auth can-i delete pods --namespace=app-ns --as=system:serviceaccount:app-ns:app-sa
# → no
kubectl auth can-i get deployments --namespace=app-ns --as=system:serviceaccount:app-ns:app-sa
# → yes
kubectl auth can-i create deployments --namespace=app-ns --as=system:serviceaccount:app-ns:app-sa
# → no
```

### Шаг 5: Тестирование пода с ServiceAccount

```yaml
# test-pod.yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-reader
  namespace: app-ns
spec:
  serviceAccountName: app-sa
  containers:
  - name: kubectl
    image: bitnami/kubectl:latest
    command: ["sleep", "3600"]
```

```bash
kubectl apply -f test-pod.yaml

# Попытка чтения (успешно)
kubectl exec -n app-ns test-reader -- kubectl get pods
# → NAME           READY   STATUS    RESTARTS   AGE
# → test-reader    1/1     Running   0          30s

# Попытка записи (ошибка Forbidden)
kubectl exec -n app-ns test-reader -- kubectl create namespace evil
# → Error from server (Forbidden): namespaces is forbidden:
# → User "system:serviceaccount:app-ns:app-sa" cannot create resource
# → "namespaces" in API group "" at the cluster scope
```

### Шаг 6: ClusterRole для кластерных ресурсов

```yaml
# node-reader-clusterrole.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-reader
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["namespaces"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: node-reader-binding
subjects:
- kind: ServiceAccount
  name: app-sa
  namespace: app-ns
roleRef:
  kind: ClusterRole
  name: node-reader
  apiGroup: rbac.authorization.k8s.io
```

```bash
kubectl apply -f node-reader-clusterrole.yaml

# Проверка: SA может читать nodes (кластерный ресурс)
kubectl auth can-i get nodes --as=system:serviceaccount:app-ns:app-sa
# → yes

# Проверка: SA НЕ может удалять nodes
kubectl auth can-i delete nodes --as=system:serviceaccount:app-ns:app-sa
# → no
```

### Шаг 7: Диагностика RBAC

```bash
# Список всех Role в namespace
kubectl get roles -n app-ns

# Список RoleBinding
kubectl get rolebindings -n app-ns

# Детали роли
kubectl describe role app-reader -n app-ns

# Кто имеет доступ к конкретному ресурсу?
kubectl auth can-i --list --namespace=app-ns | grep pods

# Просмотр CA (ClusterRole) привязок
kubectl get clusterrolebindings | grep app-sa
```

### Очистка

```bash
kubectl delete namespace app-ns
kubectl delete clusterrole node-reader
kubectl delete clusterrolebinding node-reader-binding
```

---

## Дополнительная информация

### См. также

- [RBAC: Overview](../../../Security/rbac/rbac_overview.md) — архитектура и Request Pipeline
- [RBAC: Roles](../../../Security/rbac/roles.md) — Role и ClusterRole
- [RBAC: Bindings](../../../Security/rbac/bindings.md) — RoleBinding и ClusterRoleBinding
- [RBAC: Subjects](../../../Security/rbac/subjects.md) — User, Group, ServiceAccount
- [RBAC: Privilege Escalation](../../../Security/rbac/privilege_escalation.md) — атаки и защита

### Полезные ссылки

- [RBAC Authorization](https://kubernetes.io/docs/reference/access-authn-authz/rbac/) — официальная документация
- [kubectl auth can-i](https://kubernetes.io/docs/reference/access-authn-authz/authorization/#checking-api-access) — проверка доступа
