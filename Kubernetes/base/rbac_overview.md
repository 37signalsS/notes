# Role-Based Access Control (RBAC) в Kubernetes

RBAC (Role-Based Access Control) — это механизм авторизации в Kubernetes, который позволяет управлять доступом пользователей и сервисных аккаунтов к ресурсам кластера. Существует пять основных типов объектов RBAC:

*   Role
*   RoleBinding
*   ClusterRole
*   ClusterRoleBinding
*   ServiceAccount

Давайте рассмотрим каждый из них по порядку.

## Role (Роль)

`Role` представляет собой набор прав, которые есть у некоего пользователя в кластере. Важно понимать, что `Role` не указывает, у кого именно есть эти права; она просто создает некий набор разрешений.

Пример описания `Role`:

```yaml
- apiGroups: ["extensions", "networking.k8s.io"]
  resources: ["ingresses"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

Эта часть `Role` разрешает выполнять операции `Get`, `List`, `Watch`, `Create`, `Update`, `Patch`, `Delete` с ресурсами `Ingress`.

Другой пример:

```yaml
- apiGroups: [""] # "" указывает на основную API-группу (core API group)
  resources: ["pods", "pods/log"]
  verbs: ["get", "list"]
```

Эта `Role` разрешает выполнять операции `Get` и `List` с ресурсами `Pods` и `Pods/Log`.

Если `apiGroups` пуста, это подразумевает `API Groups V1` (стандартная группа).

`Role` просто создает набор разрешений, который затем может быть применен к пользователю или сущности внутри Kubernetes. Например, `Role`, необходимая `IngressController` для работы в кластере Kubernetes.

## RoleBinding (Привязка роли)

`RoleBinding` — это объект, который связывает `Role` с конкретными пользователями или группами пользователей.

Пример `RoleBinding`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: nginx-ingress
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: nginx-ingress
subjects:
- kind: ServiceAccount
  name: nginx-ingress
  namespace: ingress-nginx
- kind: User
  name: jane # "name" чувствительно к регистру
  apiGroup: rbac.authorization.k8s.io
- kind: Group
  name: developer # например, организация в пользовательском сертификате
  apiGroup: rbac.authorization.k8s.io
```

Поле `subjects` определяет, кому выдаются права. `Subjects` бывают трех типов:

*   **ServiceAccount:** Сервисная учетная запись внутри Kubernetes.
*   **User:** Пользователь.
*   **Group:** Группа пользователей.

Для `ServiceAccount` также необходимо указать `namespace`.

**Важное замечание:** В самом Kubernetes нет таких объектов, как `user` или `group`. Для того чтобы Kubernetes мог аутентифицировать определенного пользователя или группу, требуются внешние механизмы аутентификации (например, Single Sign-On). В данном случае рассматриваются только `ServiceAccount`.

Поле `roleRef` указывает, какая `Role` (или `ClusterRole`) применяется к `subjects`.

Пример `RoleBinding` с `ClusterRole`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: user
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: view
subjects:
- kind: ServiceAccount
  name: user
  namespace: default
```

В этом примере `ServiceAccount` с именем `user` в `namespace default` получает права `ClusterRole` с именем `view`.

После создания `RoleBinding` можно проверить права доступа:

```bash
# Попытка получить сервисы в namespace default (успешно)
kubectl get service --as=system:serviceaccount:default:user

# Попытка получить сервисы в namespace kube-system (неуспешно)
kubectl get service --as=system:serviceaccount:default:user --namespace kube-system
# Error from server (Forbidden): services is forbidden: User "system:serviceaccount:default:user" cannot list resource "services" in API group "" in the namespace "kube-system"
```

## ServiceAccount (Сервисный аккаунт)

`ServiceAccount` — это простая абстракция, представляющая собой учетную запись, необходимую для работы внутри кластера Kubernetes.

Пример `ServiceAccount`:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: user
```

Создание `ServiceAccount`:

```bash
kubectl apply -f serviceaccount.yaml
# serviceaccount/user created
```

При создании `ServiceAccount` контроллер `ServiceAccount` автоматически создает секрет, содержащий токен для авторизации в Kubernetes API. 

```bash
kubectl get secret
# NAME                  TYPE                                  DATA   AGE
# default-token-hhcsn   kubernetes.io/service-account-token   3      4h2m
# user-token-4mps8      kubernetes.io/service-account-token   3      12s
```

Этот токен можно использовать для аутентификации в кластере.

Обычно `ServiceAccount` используются для авторизации приложений, работающих внутри кластера Kubernetes и обращающихся к Kubernetes API. В некоторых случаях `ServiceAccount` также могут использоваться для аутентификации внешних пользователей, например, разработчиков, которым выдаются токены для доступа к кластеру.

## ClusterRole (Кластерная роль)

В отличие от обычной `Role`, которая предоставляет права только в том `namespace`, где она была создана, `ClusterRole` предназначена для сбора прав на объекты во всем кластере (кластер-вайд ресурс). Если `ClusterRole` имеет имя `view`, она собирает права на объекты в любом `namespace`.

## ClusterRoleBinding (Привязка кластерной роли)

`ClusterRoleBinding` связывает `ClusterRole` с `subjects` (пользователями, группами или `ServiceAccount`) на уровне всего кластера. Это означает, что права, определенные в `ClusterRole`, будут применены ко всем `namespace` в кластере.

**Различия между `RoleBinding` и `ClusterRoleBinding`:**

*   **`RoleBinding`:** Выдает права `Role` (или `ClusterRole`) только в том `namespace`, где был создан `RoleBinding`.
*   **`ClusterRoleBinding`:** Выдает права `ClusterRole` на весь кластер Kubernetes.
