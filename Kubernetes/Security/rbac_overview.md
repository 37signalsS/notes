# Role-Based Access Control (RBAC) в Kubernetes

## Определения

**RBAC (Role-Based Access Control)** — это механизм авторизации в Kubernetes, который позволяет управлять доступом пользователей и сервисных аккаунтов к ресурсам кластера.

### Назначение RBAC

RBAC является фундаментом безопасности Kubernetes и необходим для:

*   Реализации принципа наименьших привилегий.
*   Разделения обязанностей между командами и пользователями.
*   Соответствия требованиям безопасности и комплаенса.
*   Предотвращения несанкционированного доступа к ресурсам кластера.

## Основные концепции

### Основные объекты RBAC

Существует пять основных типов объектов RBAC:

*   Role
*   RoleBinding
*   ClusterRole
*   ClusterRoleBinding
*   ServiceAccount

### Role (Роль)

`Role` представляет собой набор прав, которые есть у некоего пользователя в кластере. Важно понимать, что `Role` не указывает, у кого именно есть эти права; она просто создает некий набор разрешений. `Role` ограничена конкретным пространством имен (namespace).

Пример описания `Role` для управления Ingress-ресурсами:

```yaml
- apiGroups: ["extensions", "networking.k8s.io"]
  resources: ["ingresses"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

Эта `Role` разрешает выполнять операции `Get`, `List`, `Watch`, `Create`, `Update`, `Patch`, `Delete` с ресурсами `Ingress`.

Пример `Role` для просмотра подов и их логов:

```yaml
- apiGroups: [""] # "" указывает на основную API-группу (core API group)
  resources: ["pods", "pods/log"]
  verbs: ["get", "list"]
```

Эта `Role` разрешает выполнять операции `Get` и `List` с ресурсами `Pods` и `Pods/Log`.

Если `apiGroups` пуста, это подразумевает `API Groups V1` (стандартная группа).

`Role` просто создает набор разрешений, который затем может быть применен к пользователю или сущности внутри Kubernetes. Например, `Role`, необходимая `IngressController` для работы в кластере Kubernetes.

### RoleBinding (Привязка роли)

`RoleBinding` — это объект, который связывает `Role` (или `ClusterRole`) с конкретными пользователями (`User`), группами пользователей (`Group`) или сервисными аккаунтами (`ServiceAccount`) в пределах определенного `namespace`.

Пример `RoleBinding`, связывающего `Role` с `ServiceAccount`, `User` и `Group`:

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

Пример `RoleBinding` с `ClusterRole` `view`:

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

В этом примере `ServiceAccount` с именем `user` в `namespace default` получает права `ClusterRole` с именем `view` (эти права будут действовать только в `namespace default`).

После создания `RoleBinding` можно проверить права доступа:

```bash
# Попытка получить сервисы в namespace default (успешно)
kubectl get service --as=system:serviceaccount:default:user

# Попытка получить сервисы в namespace kube-system (неуспешно)
kubectl get service --as=system:serviceaccount:default:user --namespace kube-system
# Error from server (Forbidden): services is forbidden: User "system:serviceaccount:default:user" cannot list resource "services" in API group "" in the namespace "kube-system"
```

### ServiceAccount (Сервисный аккаунт)

`ServiceAccount` — это простая абстракция, представляющая собой учетную запись, необходимую для работы внутри кластера Kubernetes. Они используются для авторизации приложений, работающих внутри кластера Kubernetes и обращающихся к Kubernetes API. В некоторых случаях `ServiceAccount` также могут использоваться для аутентификации внешних пользователей, например, разработчиков, которым выдаются токены для доступа к кластеру.

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

При создании `ServiceAccount` контроллер автоматически создает секрет, содержащий токен для авторизации в Kubernetes API.

```bash
kubectl get secret
# NAME                  TYPE                                  DATA   AGE
# default-token-hhcsn   kubernetes.io/service-account-token   3      4h2m
# user-token-4mps8      kubernetes.io/service-account-token   3      12s
```

Этот токен можно использовать для аутентификации в кластере.

### ClusterRole (Кластерная роль)

В отличие от обычной `Role`, которая предоставляет права только в том `namespace`, где она была создана, `ClusterRole` предназначена для сбора прав на объекты во всем кластере (кластер-вайд ресурс). Например, если `ClusterRole` имеет имя `view`, она собирает права на объекты в любом `namespace`.

### ClusterRoleBinding (Привязка кластерной роли)

`ClusterRoleBinding` связывает `ClusterRole` с `subjects` (пользователями, группами или `ServiceAccount`) на уровне всего кластера. Это означает, что права, определенные в `ClusterRole`, будут применены ко всем `namespace` в кластере.

### Различия между RoleBinding и ClusterRoleBinding

*   **`RoleBinding`:** Выдает права `Role` (или `ClusterRole`) только в том `namespace`, где был создан `RoleBinding`.
*   **`ClusterRoleBinding`:** Выдает права `ClusterRole` на весь кластер Kubernetes.

## Практические сценарии

### Принцип минимальных привилегий

Kubernetes по умолчанию не является строгим. Можно по ошибке выдать слишком широкие права, например, `cluster-admin`. Это создает риски безопасности, так как компрометация одного компонента может привести к компрометации всего кластера.

Всегда следуйте принципу минимальных привилегий: предоставляйте пользователям и сервисным аккаунтам только те права, которые им абсолютно необходимы.

#### Ключевые принципы

**1. Минимальные привилегии (Minimal Privileges):**

Предоставляйте только минимально необходимые права для выполнения конкретной задачи.

```yaml
# Минимальные необходимые права для чтения подов в кластере
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: pod-reader
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
```

**2. Разделение по Namespace (Namespace Isolation):**

Используйте `Role` и `RoleBinding` для ограничения доступа к ресурсам в рамках определенного `namespace`. Это обеспечивает изоляцию и предотвращает горизонтальное распространение угроз.

```yaml
# Доступ только к Deployments в конкретном namespace 'development'
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: development
  name: deployment-manager
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "create", "update", "delete"]
```

### Критически важные практики

Правильная настройка RBAC является фундаментом безопасности Kubernetes и предотвращает большинство инцидентов, связанных с несанкционированным доступом.

**1. Ограничение сервисных аккаунтов (ServiceAccount Restriction):**

По умолчанию Kubernetes автоматически монтирует токен `ServiceAccount` в каждый под. Если приложение не нуждается в доступе к Kubernetes API, отключите эту функцию для повышения безопасности.

```yaml
# Автоматическое монтирование токена только когда это действительно необходимо
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app
automountServiceAccountToken: false
```

**2. Регулярный аудит RBAC (Regular RBAC Audit):**

Периодически проверяйте текущие права доступа, чтобы убедиться, что они соответствуют принципу минимальных привилегий и не содержат избыточных разрешений. Это особенно важно после изменений или развертывания новых компонентов.

```bash
# Проверка прав текущего пользователя: может ли он выполнять операцию 'list secrets' во всех namespace
kubectl auth can-i list secrets --all-namespaces

# Аудит всех ClusterRole и Role в кластере (вывод в YAML для анализа)
kubectl get clusterroles,roles --all-namespaces -o yaml
```

**3. Избегание Wildcard-прав (Avoid Wildcard Permissions):**

Использование `*` для `resources` или `verbs` в `Role` или `ClusterRole` предоставляет чрезмерные привилегии и является серьезной угрозой безопасности. Всегда указывайте конкретные ресурсы и действия.

```yaml
# ОПАСНО: Предоставляет полный доступ ко всем ресурсам
rules:
- apiGroups: [""]
  resources: ["*"]
  verbs: ["*"]

```yaml
# БЕЗОПАСНО: Предоставляет только необходимые права на конкретные ресурсы
rules:
- apiGroups: [""]
  resources: ["pods", "services"]
  verbs: ["get", "list", "watch"]
```

## Дополнительная информация

*   [RBAC Good Practices (Kubernetes Official Documentation)](https://kubernetes.k8s.io/docs/concepts/security/rbac-good-practices/)
