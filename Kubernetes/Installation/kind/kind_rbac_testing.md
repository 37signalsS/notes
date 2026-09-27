# kind — тестирование RBAC

## Определения

**RBAC (Role-Based Access Control)** — механизм контроля доступа в Kubernetes, определяющий, какие действия (получение, создание, обновление, удаление ресурсов) разрешены конкретному пользователю или сервисному аккаунту в конкретном неймспейсе или на уровне всего кластера.

**Role** — объект Kubernetes, задающий набор разрешений (правил) в рамках конкретного неймспейса.

**ClusterRole** — объект Kubernetes, задающий набор разрешений на уровне всего кластера (включая кластерные ресурсы, такие как Nodes, PersistentVolumes, Namespaces).

**RoleBinding** — связывает Role с конкретными субъектами (пользователями, группами или ServiceAccount) в рамках неймспейса.

**ClusterRoleBinding** — связывает ClusterRole с субъектами на уровне всего кластера.

**ServiceAccount** — объект Kubernetes, предоставляющий идентификацию для подов при взаимодействии с API-сервером. Используется для автоматизации (CI/CD, операторы, контроллеры).

---

## Основные концепции

### Зачем тестировать RBAC в kind

kind позволяет безопасно и быстро экспериментировать с политиками доступа перед применением в production-кластере. Тестирование RBAC в kind позволяет:

- Эмулировать ограничения доступа для разных ролей (разработчик, SRE, деплоер)
- Проверить, что политики не блокируют необходимые операции
- Убедиться, что политики действительно запрещают лишние действия
- Отработать ошибки доступа (403 Forbidden) и их диагностику

### Субъекты в Kubernetes

| Тип | Описание | Пример |
|:---|:---|:---|
| **User** | Внешний пользователь (аутентифицируется через сертификат, OIDC, token) | `dev-user`, `sre-admin` |
| **Group** | Группа пользователей (определяется провайдером аутентификации) | `dev-team`, `platform-admins` |
| **ServiceAccount** | Субъект для подов и автоматизации | `ci-deployer`, `monitoring-agent` |

> **Важно:** Kubernetes не хранит объекты `User` или `Group` в etcd. Информация о субъектах извлекается из сертификатов, OIDC-токенов или заголовков запроса в момент аутентификации.

### Уровни разрешений

| Область | Объект | Кластерные ресурсы | Namespaced ресурсы |
|:---|:---|:---|:---|
| **Namespace** | Role + RoleBinding | Нет | Да |
| **Cluster** | ClusterRole + ClusterRoleBinding | Да | Да (через ClusterRoleBinding) |

### Типы API-групп для разрешений

| API-группа | Ресурсы | Примеры |
|:---|:---|:---|
| `""` (core) | Pod, Service, ConfigMap, Secret, Namespace, Node, PV | `pods`, `services`, `configmaps` |
| `apps` | Deployment, StatefulSet, DaemonSet, ReplicaSet | `deployments`, `statefulsets` |
| `batch` | Job, CronJob | `jobs`, `cronjobs` |
| `networking.k8s.io` | Ingress, NetworkPolicy | `ingresses`, `networkpolicies` |
| `rbac.authorization.k8s.io` | Role, ClusterRole, RoleBinding, ClusterRoleBinding | `roles`, `clusterroles` |
| `storage.k8s.io` | StorageClass, CSIDriver, PersistentVolume | `storageclasses` |

---

## Практические сценарии

### Создание кластера для тестирования RBAC

```bash
kind create cluster --name rbac-test
```

### Сценарий 1: Ограничение доступа к конкретному неймспейсу

**Цель:** Создать роль `namespace-reader`, которая позволяет только читать поды в неймспейсе `app-team-a`.

```yaml
# rbac-namespace-reader.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: app-team-a
---
# Role: только чтение подов
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: namespace-reader
  namespace: app-team-a
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["services", "configmaps"]
  verbs: ["get", "list"]
---
# RoleBinding: привязка к ServiceAccount
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: read-pods-binding
  namespace: app-team-a
subjects:
- kind: ServiceAccount
  name: app-team-a-reader
  namespace: app-team-a
roleRef:
  kind: Role
  name: namespace-reader
  apiGroup: rbac.authorization.k8s.io
---
# ServiceAccount для тестирования
apiVersion: v1
kind: ServiceAccount
metadata:
  name: app-team-a-reader
  namespace: app-team-a
```

```bash
kubectl apply -f rbac-namespace-reader.yaml

# Создание тестового пода в неймспейсе
kubectl run test-app --image=nginx --namespace=app-team-a

# Создание пода-клиента для проверки доступа
kubectl run rbac-tester --image=curlimages/curl --namespace=app-team-a --rm -it --restart=Never -- /bin/sh
```

**Проверка доступа из пода-клиента:**

```bash
# Получение ServiceAccount токена
TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
CACERT=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
APISERVER=https://kubernetes.default.svc

# Разрешено: чтение подов
curl -s --cacert $CACERT -H "Authorization: Bearer $TOKEN" \
  $APISERVER/api/v1/namespaces/app-team-a/pods | jq '.items[].metadata.name'
# → "test-app"

# Запрещено: создание подов
curl -s --cacert $CACERT -H "Authorization: Bearer $TOKEN" \
  -X POST -H "Content-Type: application/json" \
  -d '{"apiVersion":"v1","kind":"Pod","metadata":{"name":"hack"},"spec":{"containers":[{"name":"test","image":"nginx"}]}}' \
  $APISERVER/api/v1/namespaces/app-team-a/pods
# → Error: forbidden (.createUser forbidden for "system:serviceaccount:app-team-a:app-team-a-reader")
```

### Сценарий 2: ClusterRole для мониторинга (read-only на весь кластер)

**Цель:** ServiceAccount `monitoring-agent` может читать метрики и поды во всех неймспейсах.

```yaml
# rbac-monitoring-agent.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: monitoring
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: monitoring-agent
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: monitoring-reader
rules:
- apiGroups: [""]
  resources: ["pods", "nodes", "services", "endpoints", "namespaces"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["metrics.k8s.io"]
  resources: ["pods", "nodes"]
  verbs: ["get", "list"]
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets", "daemonsets"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: monitoring-agent-binding
subjects:
- kind: ServiceAccount
  name: monitoring-agent
  namespace: monitoring
roleRef:
  kind: ClusterRole
  name: monitoring-reader
  apiGroup: rbac.authorization.k8s.io
```

```bash
kubectl apply -f rbac-monitoring-agent.yaml

# Проверка: monitoring-agent видит поды во всех неймспейсах
kubectl auth can-i list pods --as=system:serviceaccount:monitoring:monitoring-agent --all-namespaces
# → yes

# Проверка: monitoring-agent НЕ может удалять поды
kubectl auth can-i delete pods --as=system:serviceaccount:monitoring:monitoring-agent --all-namespaces
# → no
```

### Сценарий 3: Деплоер с ограниченными правами

**Цель:** CI/CD-пайплайн может обновлять Deployment в неймспейсе `production`, но не может удалять поды или изменять ServiceAccount.

```yaml
# rbac-deployer.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ci-deployer
  namespace: production
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: deployer
  namespace: production
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "replicasets"]
  verbs: ["get", "list", "watch", "update", "patch"]
- apiGroups: [""]
  resources: ["services", "configmaps"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
# Запрещено: удаление подов, изменение ServiceAccount, доступ к Secret
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ci-deployer-binding
  namespace: production
subjects:
- kind: ServiceAccount
  name: ci-deployer
  namespace: production
roleRef:
  kind: Role
  name: deployer
  apiGroup: rbac.authorization.k8s.io
```

**Проверка ограничений:**

```bash
# Разрешено: обновление Deployment
kubectl auth can-i update deployments --as=system:serviceaccount:production:ci-deployer -n production
# → yes

# Запрещено: удаление подов
kubectl auth can-i delete pods --as=system:serviceaccount:production:ci-deployer -n production
# → no

# Запрещено: доступ к Secret
kubectl auth can-i get secrets --as=system:serviceaccount:production:ci-deployer -n production
# → no

# Запрещено: изменение ServiceAccount
kubectl auth can-i patch serviceaccounts --as=system:serviceaccount:production:ci-deployer -n production
# → no
```

### Сценарий 4: Диагностика ошибок доступа

**Типичные ошибки и их причины:**

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Error: Forbidden` | Role/ClusterRole не содержит нужных правил | Добавить недостающие `verbs` или `resources` |
| `Error: Unauthorized` | Токен ServiceAccount истёк или невалиден | Пересоздать ServiceAccount или токен |
| `Error: the server doesn't have a resource type "X"` | RoleBinding ссылается на несуществующий ресурс | Проверить имя ресурса в `rules[].resources` |
| `Error: forbidden: User "X" cannot list resource "Y"` | Пользователь не привязан к нужной Role | Создать RoleBinding для пользователя |

**Команды диагностики:**

```bash
# Проверка прав для конкретного ServiceAccount
kubectl auth can-i --list --as=system:serviceaccount:default:my-sa

# Проверка конкретной операции
kubectl auth can-i create pods --as=system:serviceaccount:default:my-sa -n default

# Просмотр всех RoleBinding в неймспейсе
kubectl get rolebindings -n default -o wide

# Просмотр всех ClusterRoleBinding
kubectl get clusterrolebindings -o wide | grep my-sa

# Детальный просмотр Role
kubectl describe role namespace-reader -n app-team-a

# Детальный просмотр RoleBinding
kubectl describe rolebinding read-pods-binding -n app-team-a
```

### Сценарий 5: Миграция от auto-mount к явному токену

По умолчанию каждый ServiceAccount автоматически монтирует токен в каждый под. В production рекомендуется отключать это поведение.

```yaml
# rbac-sa-no-auto-mount.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ci-deployer
  namespace: production
automountServiceAccountToken: false  # Отключение автоматического монтирования
---
# Под с явно указанным ServiceAccount и токеном
apiVersion: v1
kind: Pod
metadata:
  name: deploy-pod
  namespace: production
spec:
  serviceAccountName: ci-deployer
  automountServiceAccountToken: true  # Включение для конкретного пода
  containers:
  - name: kubectl
    image: bitnami/kubectl
    command: ["sleep", "3600"]
```

### Сценарий 6: Тестирование ограничений на уровне кластера

```yaml
# rbac-cluster-limits.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: namespace-creator
rules:
# Разрешено: создавать неймспейсы
- apiGroups: [""]
  resources: ["namespaces"]
  verbs: ["create", "get", "list"]
# Запрещено: удалять неймспейсы
# Запрещено: работать с подами, сервисами, etc.
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: namespace-creator-binding
subjects:
- kind: User
  name: junior-dev
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: namespace-creator
  apiGroup: rbac.authorization.k8s.io
```

```bash
# Проверка: junior-dev может создавать неймспейсы
kubectl auth can-i create namespaces --as=junior-dev
# → yes

# Проверка: junior-dev НЕ может удалять неймспейсы
kubectl auth can-i delete namespaces --as=junior-dev
# → no

# Проверка: junior-dev НЕ может создавать поды
kubectl auth can-i create pods --as=junior-dev
# → no
```

---

## Дополнительная информация

### Ссылки

- [kind — определения и концепции](./kind_concepts.md) — архитектура и внутреннее устройство узлов
- [RBAC Overview](../../Security/rbac/rbac_overview.md) — полная теория RBAC в Kubernetes
- [RBAC: субъекты](../../Security/rbac/subjects.md) — определения User, Group, ServiceAccount
- [Pod Security Context](../../Security/pod_security_context.md) — дополнение к RBAC на уровне подов
- [Официальная документация RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
