# RoleBinding и ClusterRoleBinding

`RoleBinding` и `ClusterRoleBinding` используются для привязки ролей к субъектам.

## RoleBinding

**RoleBinding**: назначает права в пределах **одного `namespace`**. Может ссылаться как на `Role` (в том же `namespace`), так и на `ClusterRole` (в этом случае права будут действовать только в `namespace`, где создан `RoleBinding`).

## ClusterRoleBinding

**ClusterRoleBinding**: назначает права на **весь кластер**. Ссылается только на `ClusterRole`.

## Субъекты (`subjects`)

В качестве субъектов могут выступать:
- `User`: `kind: User, name: "jane"`
- `Group`: `kind: Group, name: "developers"`
- `ServiceAccount`: `kind: ServiceAccount, name: "ci-bot", namespace: "dev"`

> **Важно:** `User` и `Group` не являются объектами Kubernetes. Они приходят из внешних систем аутентификации.

## Сравнение RoleBinding и ClusterRoleBinding

| Характеристика | RoleBinding | ClusterRoleBinding |
| :--- | :--- | :--- |
| **Область действия** | Один `namespace` | Весь кластер |
| **`roleRef`** | `Role` или `ClusterRole` | Только `ClusterRole` |
| **Типовые сценарии**| Делегирование ролей в команде | Глобальные роли для администраторов |
