# Role и ClusterRole

`Role` и `ClusterRole` содержат правила (`rules`), которые представляют собой набор разрешений.

## Role

**Role**: представляет собой набор прав в пределах конкретного **пространства имен (`namespace`)**. Не может предоставлять доступ к кластерным ресурсам.

## ClusterRole

**ClusterRole**: является **кластерным объектом** и может использоваться для предоставления прав на:
*   Кластерные ресурсы (`nodes`, `persistentvolumes`)
*   Ресурсы во всех `namespace`
*   Нересурсные URL (например, `/healthz`)

## Структура правил (`rules`)

Каждая роль содержит список правил:
*   `apiGroups`: список API-групп (`""` для core API)
*   `resources`: типы ресурсов (`pods`, `configmaps`, `nodes` и т.д.)
*   `verbs`: действия (`get`, `list`, `watch`, `create`, `update`, `patch`, `delete`)
*   `resourceNames`: ограничение на конкретные имена ресурсов
*   `nonResourceURLs`: доступ к не-ресурсным HTTP путям

## Сравнение Role и ClusterRole

| Критерий | Role | ClusterRole |
| :--- | :--- | :--- |
| **Область действия** | Один `namespace` | Весь кластер |
| **Ресурсы** | Только `namespaced` ресурсы | Кластерные и `namespaced` ресурсы |
| **Привязка** | `RoleBinding` в том же `namespace` | `ClusterRoleBinding` или `RoleBinding` |
| **Агрегация** | Нет | Есть (`aggregationRule`) |
