# Kubernetes Dashboard

## Определения

**Kubernetes Dashboard** — это официальный веб-интерфейс для кластеров Kubernetes. Он позволяет пользователям управлять приложениями, работающими в кластере, устранять их неполадки, а также управлять самим кластером.

## Установка

Рекомендуемый способ установки — применение официального манифеста напрямую из репозитория Kubernetes.

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/dashboard/v2.7.0/aio/deploy/recommended.yaml
```
> **Примечание:** Указанная версия `v2.7.0` может быть изменена на более актуальную. Актуальную команду всегда можно найти в [официальной документации](https://kubernetes.io/docs/tasks/web-ui-dashboard/).

Эта команда создаст все необходимые ресурсы (Deployment, Service, Role и т.д.) в отдельном пространстве имен `kubernetes-dashboard`.

## Доступ к Dashboard

Существует несколько способов получить доступ к интерфейсу.

### Способ 1: `kubectl proxy` (для локального доступа)

Это самый простой способ для быстрого и безопасного доступа с вашей локальной машины.

1.  **Запустите прокси:**
    ```bash
    kubectl proxy
    ```
2.  **Откройте URL в браузере:**
    Используйте следующий URL для доступа к дашборду через прокси.
    ```
    http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https-kubernetes-dashboard:/proxy/
    ```

При доступе через `kubectl proxy` аутентификация и авторизация обрабатываются с использованием вашего локального файла `kubeconfig`, предоставляя вам те же права, что и при работе с `kubectl`.

### Способ 2: Создание Admin-пользователя (через ServiceAccount)

Этот способ позволяет создать отдельного пользователя с полными правами администратора и входить в систему по токену.

**1. Создание `ServiceAccount`**

Создадим сервисный аккаунт с именем `admin-user` в пространстве имен `kubernetes-dashboard`.

```yaml
# dashboard-admin-user.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: admin-user
  namespace: kubernetes-dashboard
```
```bash
kubectl apply -f dashboard-admin-user.yaml
```

**2. Создание `ClusterRoleBinding`**

Привяжем созданный `ServiceAccount` к существующей `ClusterRole` под названием `cluster-admin`, которая предоставляет полные права на весь кластер.

```yaml
# dashboard-admin-rb.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: admin-user
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- kind: ServiceAccount
  name: admin-user
  namespace: kubernetes-dashboard
```
```bash
kubectl apply -f dashboard-admin-rb.yaml
```

**3. Получение токена**

Извлечем токен, связанный с созданным сервисным аккаунтом.

```bash
# Для Kubernetes v1.24+
kubectl -n kubernetes-dashboard create token admin-user
```
> **Для старых версий Kubernetes (до v1.24):**
> Команда для получения токена была сложнее и требовала извлечения его из секрета, который создавался автоматически.
> ```bash
> kubectl -n kubernetes-dashboard get secret $(kubectl -n kubernetes-dashboard get sa/admin-user -o jsonpath="{.secrets[0].name}") -o go-template="{{.data.token | base64decode}}"
> ```

**4. Вход в систему**

На странице входа в Dashboard выберите опцию "Токен", вставьте скопированный токен и войдите в систему.

## Решение проблем (Troubleshooting)

### Проблема: Ошибка `Forbidden` для анонимного пользователя

Иногда при попытке получить доступ к Dashboard через Ingress или NodePort (без `kubectl proxy`) возникает ошибка, запрещающая доступ для `system:anonymous`. Это происходит потому, что по умолчанию анонимный пользователь не имеет прав на проксирование запросов к сервису дашборда.

*   **Причина:** Отсутствуют права на ресурс `services/proxy` для `system:anonymous`.
*   **Решение:** Создать `ClusterRole` и `ClusterRoleBinding`, разрешающие анонимный доступ для проксирования запросов **только** к сервису дашборда.

```yaml
# dashboard-anonymous-access.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kubernetes-dashboard-anonymous
rules:
- apiGroups: [""]
  resources: ["services/proxy"]
  resourceNames: ["http:kubernetes-dashboard:"] # Разрешает доступ только к этому сервису
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: kubernetes-dashboard-anonymous
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: kubernetes-dashboard-anonymous
subjects:
- kind: User
  name: system:anonymous
```
> **Внимание:** Этот манифест предоставляет доступ к странице входа для всех анонимных пользователей. Сама аутентификация по токену при этом остается обязательной.

### Проблема: Обновление или переустановка Dashboard

Если Dashboard был установлен кастомным скриптом (например, старой версией Kubespray) и работает некорректно, его может потребоваться полностью переустановить.

1.  **Полное удаление:** Простого `kubectl delete deployment` недостаточно, так как установка включает множество ресурсов. Для полного удаления необходимо использовать исходный манифест, с помощью которого производилась установка.
    ```bash
    # Если установка производилась из локального файла
    kubectl delete -f path/to/your/old-dashboard.yaml
    ```
2.  **Установка новой версии:** После полного удаления старой версии, установите новую, как описано в разделе "Установка".
