# Ошибки доступа к API (`Forbidden` (403) / `Unauthorized` (401))

## Определения

**`401 Unauthorized`** — Kubernetes не смог аутентифицировать запрос. Проблема с токеном, сертификатом или другим методом аутентификации.

**`403 Forbidden`** — Kubernetes аутентифицировал запрос, но у субъекта нет прав (RBAC) на выполнение запрошенной операции.

> - RBAC: [`rbac_overview.md`](../../Security/rbac/rbac_overview.md)
> - Authentication: [`authentication.md`](../../Security/authentication.md)
> - ServiceAccount: [`roles.md`](../../Security/rbac/roles.md)
> - Troubleshooting: [`troubleshooting_overview.md`](../troubleshooting_overview.md)

### Различия

| Код | Этап | Причина | Решение |
|-----|------|---------|---------|
| **401** | Authentication | Неверный токен, истекший сертификат | Обновить credentials |
| **403** | Authorization | Недостаточно прав RBAC | Исправить Role/RoleBinding |

## Основные концепции

### Модель аутентификации и авторизации

```
Запрос к API
    ↓
Аутентификация (Кто вы?)
    ↓
401 если не удалось
    ↓
Авторизация RBAC (Что можно делать?)
    ↓
403 если нет прав
    ↓
200 OK
```

### Методы аутентификации

| Метод | Описание | Когда используется |
|-------|----------|-------------------|
| **ServiceAccount Token** | JWT токен в `/var/run/secrets/kubernetes.io/serviceaccount/token` | Pod → API |
| **Client Certificate** | X.509 сертификат | kubectl, внешние клиенты |
| **Bearer Token** | Статический токен | Интеграции |
| **Webhook** | Внешний сервис аутентификации | Кастомные сценарии |

### RBAC объекты

| Объект | Описание |
|--------|----------|
| **ServiceAccount** | Учетная запись для pod | [`roles.md`](../../Security/rbac/roles.md) |
| **Role** | Права в namespace | [`roles.md`](../../Security/rbac/roles.md) |
| **ClusterRole** | Права на кластер | [`roles.md`](../../Security/rbac/roles.md) |
| **RoleBinding** | Привязка в namespace | [`bindings.md`](../../Security/rbac/bindings.md) |
| **ClusterRoleBinding** | Глобальная привязка | [`bindings.md`](../../Security/rbac/bindings.md) |

> **См. также:** [`rbac_overview.md`](../../Security/rbac/rbac_overview.md)

## Практические сценарии

### Диагностика: пошаговый чек-лист

#### Шаг 1: Определение типа ошибки

```bash
# Запуск команды с подробным выводом
kubectl get pods -v=8

# Ищите в выводе:
# HTTP/1.1 401 Unauthorized → Аутентификация
# HTTP/1.1 403 Forbidden → Авторизация
```

#### Шаг 2: Проверка аутентификации (401)

```bash
# Проверка текущего контекста
kubectl config current-context

# Проверка пользователя
kubectl config view --minify -o jsonpath='{.users[0].name}'

# Проверка токена ServiceAccount
kubectl get secret $(kubectl get serviceaccount default -o jsonpath='{.secrets[0].name}') -o jsonpath='{.data.token}' | base64 -d
```

#### Шаг 3: Проверка авторизации (403)

**Основной инструмент — `kubectl auth can-i`:**

```bash
# Проверка прав текущего пользователя
kubectl auth can-i get pods -n default
kubectl auth can-i list secrets -n kube-system

# Проверка от имени ServiceAccount
kubectl auth can-i get pods \
  --as=system:serviceaccount:my-ns:my-sa \
  -n my-ns

# Проверка всех прав
kubectl auth can-i --list

# Проверка прав для конкретного ресурса
kubectl auth can-i get deployments --all-namespaces
```

#### Шаг 4: Определение ServiceAccount пода

```bash
# SA пода
kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}'

# Детали SA
kubectl get serviceaccount <sa-name> -n <namespace> -o yaml

# Secrets SA
kubectl get serviceaccount <sa-name> -o jsonpath='{.secrets}'
```

#### Шаг 5: Проверка RoleBinding

```bash
# RoleBinding в namespace
kubectl get rolebinding -n <namespace>

# ClusterRoleBinding
kubectl get clusterrolebinding

# Поиск binding для конкретного SA
kubectl get rolebinding -n <namespace> -o yaml | grep -B 5 -A 5 "name: <sa-name>"
```

### Распространенные случаи и решения

#### 1. 401 Unauthorized — проблемы с токеном

**Сообщение:**
```
Unauthorized: Invalid token
The token provided has expired
```

**Причины:**
- Истек срок действия токена ServiceAccount
- Token был отозван
- Неверный kubeconfig

**Решение:**
```bash
# Пересоздание token для ServiceAccount
kubectl delete secret <sa-token-secret>
# Kubernetes автоматически создаст новый

# Или явное создание token (Kubernetes 1.24+)
kubectl create token <sa-name> -n <namespace>

# Обновление kubeconfig
kubectl config set-credentials <user> --token=<new-token>
```

> **Важно:** С Kubernetes 1.24+ токены ServiceAccount не сохраняются в Secrets по умолчанию. Используйте `kubectl create token`.

#### 2. 403 Forbidden — отсутствие прав на чтение подов

**Сообщение:**
```
Error from server (Forbidden): pods is forbidden: 
User "system:serviceaccount:my-ns:my-sa" cannot list resource "pods" 
in API group "" in the namespace "my-ns"
```

**Причина:** У ServiceAccount нет RoleBinding с необходимыми правами.

**Решение:**
```yaml
# Создание Role
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
  namespace: my-ns
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
---
# Привязка к ServiceAccount
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: my-sa-pod-reader
  namespace: my-ns
subjects:
- kind: ServiceAccount
  name: my-sa
  namespace: my-ns
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

#### 3. 403 — доступ к Secrets

**Сообщение:**
```
secrets is forbidden: User "system:serviceaccount:..." 
cannot list resource "secrets" in API group "" in the namespace "..."
```

**Причина:** Доступ к Secrets ограничен по умолчанию.

**Решение:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: secret-reader
  namespace: my-ns
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
```

> **Warning:** Предоставляйте доступ к Secrets только когда это абсолютно необходимо.

#### 4. 403 — доступ к pods/log (для log shipper)

**Сценарий:** Контейнер-сборщик логов (Fluent Bit, Filebeat) пытается читать логи других подов.

**Сообщение:**
```
pods/log is forbidden: User "system:serviceaccount:..." 
cannot get resource "pods/log" in API group "" in the namespace "..."
```

**Диагностика:**
```bash
# Проверка прав
kubectl auth can-i get pods/log \
  --as=system:serviceaccount:monitoring:fluent-bit \
  -n monitoring
```

**Решение:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole  # ClusterRole для доступа ко всем namespace
metadata:
  name: pod-log-reader
rules:
- apiGroups: [""]
  resources: ["pods/log"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: fluent-bit-pod-log-reader
subjects:
- kind: ServiceAccount
  name: fluent-bit
  namespace: monitoring
roleRef:
  kind: ClusterRole
  name: pod-log-reader
  apiGroup: rbac.authorization.k8s.io
```

#### 5. 403 — доступ к nodes (для monitoring)

**Сценарий:** Prometheus node-exporter или metrics-server нуждается в доступе к узлам.

**Решение:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-reader
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["nodes/metrics"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus-node-reader
subjects:
- kind: ServiceAccount
  name: prometheus
  namespace: monitoring
roleRef:
  kind: ClusterRole
  name: node-reader
  apiGroup: rbac.authorization.k8s.io
```

#### 6. 403 — доступ к namespaces

**Сценарий:** Приложение пытается получить список namespace или информацию о своем namespace.

**Решение:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: namespace-reader
rules:
- apiGroups: [""]
  resources: ["namespaces"]
  verbs: ["get", "list", "watch"]
```

#### 7. 403 — создание/удаление ресурсов

**Сообщение:**
```
deployments is forbidden: User "..." cannot create resource "deployments"
```

**Решение:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: deployment-manager
  namespace: my-ns
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

### Встроенные ClusterRole

Kubernetes предоставляет готовые роли:

| Role | Описание | Когда использовать |
|------|----------|-------------------|
| `view` | Только чтение (без Secrets) | Мониторинг, дашборды |
| `edit` | Чтение + запись (без RBAC) | Разработчики |
| `admin` | Edit + управление RBAC в namespace | Админы namespace |
| `cluster-admin` | Полный доступ | Админы кластера |

**Привязка встроенной роли:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: developer-view
  namespace: my-ns
subjects:
- kind: ServiceAccount
  name: my-sa
  namespace: my-ns
roleRef:
  kind: ClusterRole
  name: view  # Встроенная роль
  apiGroup: rbac.authorization.k8s.io
```

> **См. также:** [`rbac_overview.md`](../../Security/rbac/rbac_overview.md)

### Автоматизация проверки прав

```bash
#!/bin/bash
# Скрипт проверки прав ServiceAccount

SA=${1:-default}
NS=${2:-default}

echo "=== Проверка прав для $SA в $NS ==="

# Получение всех RoleBinding
echo -e "\n=== RoleBinding ==="
kubectl get rolebinding -n $NS -o yaml | grep -B 5 -A 5 "$SA"

# Получение всех ClusterRoleBinding
echo -e "\n=== ClusterRoleBinding ==="
kubectl get clusterrolebinding -o yaml | grep -B 5 -A 5 "$SA"

# Проверка конкретных прав
echo -e "\n=== Проверка can-i ==="
kubectl auth can-i --list --as=system:serviceaccount:$NS:$SA
```

## Дополнительная информация

### Best Practices

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

### Ссылки

- [Kubernetes RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
- [Authenticate ServiceAccount](https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/)
- [RBAC Good Practices](https://kubernetes.io/docs/concepts/security/rbac-good-practices/)
