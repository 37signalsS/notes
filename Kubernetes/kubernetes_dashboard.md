# Kubernetes Dashboard

## Definitions

**Kubernetes Dashboard** — официальный веб-интерфейс для управления кластерами Kubernetes. Позволяет управлять приложениями, устранять неполадки и администрировать сам кластер через графический интерфейс.

> **⚠️ Критическое предупреждение (статус на 2026 г.):**
> Проект Kubernetes Dashboard **архивирован и больше не поддерживается** (репозиторий перемещён в `kubernetes-retired`). Для новых установок официально рекомендуется использовать **[Headlamp](https://headlamp.dev/)** — подпроект Kubernetes SIG UI. Существующие инсталляции Dashboard продолжают функционировать, но не получат обновлений безопасности.

## Basic Concepts

### Архитектура и компоненты

Dashboard разворачивается как набор ресурсов Kubernetes в отдельном namespace `kubernetes-dashboard`:
- **Deployment** — поды с веб-интерфейсом
- **Service** — внутренний сервис для доступа
- **Role/RoleBinding** — RBAC-правила для функционирования дашборда
- **Metrics Scraper** — компонент для сбора метрик (опционально)

### Аутентификация и авторизация

Dashboard не имеет собственной системы пользователей — он делегирует аутентификацию механизмам Kubernetes:
- **kubectl proxy** — использует локальный `kubeconfig`, предоставляя права текущего пользователя
- **ServiceAccount + Token** — вход по токену сервисного аккаунта с заданными RBAC-ролями
- **OIDC / Webhook** — внешние провайдеры (зависит от конфигурации API-сервера)

### Статус проекта и альтернативы

| Параметр | Kubernetes Dashboard | Headlamp (рекомендуемая замена) |
| :--- | :--- | :--- |
| **Статус** | Архивирован (`kubernetes-retired`) | Активно развивается (SIG UI) |
| **Установка** | Helm / манифест | Helm / манифест / Flatpak / `minikube addons enable` |
| **Плагины** | Нет | Официальная поддержка |
| **Режимы** | Только веб-интерфейс | Веб-клиент + десктопное приложение |
| **RBAC-адаптивность** | Базовая | Автоматическое скрытие недоступных элементов UI |

## Practical Scenarios

### Установка Kubernetes Dashboard (для существующих инсталляций)

> Используйте этот раздел только если Dashboard уже развёрнут в вашей инфраструктуре. Для новых кластеров устанавливайте [Headlamp](https://headlamp.dev/docs/latest/installation/).

Рекомендуемый способ установки — применение официального манифеста:

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/dashboard/v2.7.0/aio/deploy/recommended.yaml
```

> **Примечание:** Версия `v2.7.0` — последняя стабильная перед архивированием. Репозиторий больше не обновляется.

Команда создаёт все ресурсы в namespace `kubernetes-dashboard`.

### Доступ к Dashboard

#### Способ 1: `kubectl proxy` (локальный доступ)

Наиболее простой и безопасный способ для работы с локальной машины:

1. **Запустите прокси:**

    ```bash
    kubectl proxy
    ```

2. **Откройте URL в браузере:**

    ```
    http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https-kubernetes-dashboard:/proxy/
    ```

Аутентификация происходит через локальный `kubeconfig` — права соответствуют правам текущего пользователя `kubectl`.

#### Способ 2: Вход по токену (ServiceAccount)

Создание отдельного пользователя с полными правами администратора:

**1. Создание `ServiceAccount`:**

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

**2. Создание `ClusterRoleBinding`:**

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

**3. Получение токена:**

```bash
# Для Kubernetes v1.24+
kubectl -n kubernetes-dashboard create token admin-user
```

> **Kubernetes < v1.24:** Токен извлекался из автоматически созданного Secret:
> ```bash
> kubectl -n kubernetes-dashboard get secret $(kubectl -n kubernetes-dashboard get sa/admin-user -o jsonpath="{.secrets[0].name}") -o go-template="{{.data.token | base64decode}}"
> ```

**4. Вход:** На странице выбора аутентификации выберите «Токен» и вставьте полученное значение.

### Troubleshooting

#### Ошибка `Forbidden` для `system:anonymous`

**Симптом:** При доступе через Ingress/NodePort (без `kubectl proxy`) возвращается ошибка для анонимного пользователя.

**Причина:** По умолчанию `system:anonymous` не имеет прав на `services/proxy`.

**Решение:** Создать `ClusterRole` и `ClusterRoleBinding` для проксирования только к сервису Dashboard:

```yaml
# dashboard-anonymous-access.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kubernetes-dashboard-anonymous
rules:
- apiGroups: [""]
  resources: ["services/proxy"]
  resourceNames: ["https:kubernetes-dashboard:"]
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
  apiGroup: rbac.authorization.k8s.io
```

> **Внимание:** Манифест открывает страницу входа для всех анонимных пользователей. Сама аутентификация по токену остаётся обязательной.

#### Полная переустановка Dashboard

Если Dashboard установлен кастомным скриптом (например, старой версией Kubespray) и работает некорректно:

1. **Удаление через исходный манифест:**

    ```bash
    kubectl delete -f path/to/your/old-dashboard.yaml
    ```

    Простого `kubectl delete deployment` недостаточно — установка включает множество ресурсов (Service, Role, RoleBinding и др.).

2. **Установка актуальной версии** — см. раздел «Установка Kubernetes Dashboard» выше.

> **Рекомендация:** Вместо переустановки Dashboard рассмотрите миграцию на [Headlamp](https://headlamp.dev/docs/latest/installation/).

## Additional Information

### Ссылки

- [Официальная документация Kubernetes Dashboard (архив)](https://kubernetes.io/docs/tasks/access-application-cluster/web-ui-dashboard/)
- [Headlamp — рекомендуемая замена](https://headlamp.dev/)
- [Репозиторий kubernetes-retired/dashboard](https://github.com/kubernetes-retired/dashboard)

### Связанные темы

- Установка через Kubespray: [Kubespray examples](../Installation/Kubespray/examples.md)
- Namespace `kubernetes-dashboard`: [namespace.md](./Base/namespace.md)
- Dashboard в Minikube: [minikube_practical_scenarios.md](./Installation/minikube/minikube_practical_scenarios.md)
