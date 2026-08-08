# Объекты RBAC: структура и типичные ошибки конфигурации

## Определения

**Объекты RBAC (Role-Based Access Control)** — набор ресурсов Kubernetes, определяющих политику авторизации. При возникновении ошибки **403 Forbidden** проблема всегда локализована в одном из этих объектов или в нарушении логической связи между ними.

**Субъект (Subject)** — личность (User), группа (Group) или учетная запись приложения (ServiceAccount).

**Правило (Rule)** — описание разрешенного действия (`verb`) над ресурсом (`resource`) в конкретной группе API (`apiGroup`).

**Связь (Binding)** — мост между субъектом и набором правил (Role/ClusterRole).

> Полное архитектурное описание RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)

## Основные концепции

### Структурная модель доступа

Авторизация успешна только при наличии корректно настроенной цепочки:

```text
КТО? (Subject) ← [БИНДИНГ] → ЧТО МОЖНО? (Role / ClusterRole)
    ↓                ↓                   ↓
Namespace/Name   Immutable Ref        API Group + Verb + Resource
```

### Сравнительный анализ объектов

| Объект | Область видимости | Ключевая особенность при отладке |
|--------|-------------------|-----------------------------------|
| **ServiceAccount** | Namespace | Проверьте поле `automountServiceAccountToken`. |
| **Role** | Namespace | Не может давать доступ к кластерным ресурсам (Nodes). |
| **ClusterRole** | Cluster | Может агрегировать правила через `aggregationRule`. |
| **RoleBinding** | Namespace | Поле `roleRef` является **неизменяемым (immutable)**. |
| **ClusterRoleBinding**| Cluster | Дает доступ ко всем пространствам имен одновременно. |

### Продвинутые механизмы

1.  **Неизменяемость roleRef:** Вы не можете изменить роль в существующем биндинге. Для смены роли необходимо удалить и создать `RoleBinding` заново. Это частая причина "зависания" старых прав при попытке их обновления через `kubectl apply`.
2.  **Агрегация ролей (AggregationRule):** ClusterRole может автоматически собирать правила из других ролей по селектору меток. Если права субъекта внезапно расширились или сузились — проверьте наличие `aggregationRule` в его ClusterRole.
3.  **Кросс-неймспейс доступ:** `RoleBinding` в одном namespace может ссылаться на `ServiceAccount` из другого namespace. Это стандартный паттерн для централизованных инструментов (например, операторов или систем мониторинга).

> Подробнее об агрегации: [../../../Security/rbac/aggregation_scenarios.md](../../../Security/rbac/aggregation_scenarios.md)

## Практические сценарии

### Сценарий 1: Ошибки в субъектах (Subjects)

**Проблема:** Права не применяются к ServiceAccount, хотя биндинг существует.

**Причины:**
*   Опечатка в имени SA.
*   Неверно указанный `namespace` в блоке `subjects`. Для SA поле `namespace` является **обязательным**.

**Команда для проверки:**
```bash
# Просмотр сырых данных биндинга для выявления ошибок в subjects
kubectl get rolebinding <name> -n <ns> -o jsonpath='{.subjects}'
```

### Сценарий 2: Идентификация API-группы ресурса

**Проблема:** Ошибка 403 из-за неверного `apiGroups` в роли (например, попытка использовать `""` для `deployments`).

**Решение:** Используйте `api-resources` для получения точной группы.

```bash
# Получение группы и версии для любого ресурса
kubectl api-resources -o wide | grep "ingresses"
# → ingresses  networking.k8s.io/v1  true  Ingress
```

### Сценарий 3: ClusterRole в локальном RoleBinding

**Контекст:** Предоставление стандартных прав (например, `view` или `edit`) пользователю в конкретном пространстве имен.

**Нюанс:** Использование `ClusterRole` в `RoleBinding` — это эффективный способ избежать дублирования ролей. Субъект получит права ClusterRole, но **только в границах namespace**, где создан `RoleBinding`.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: team-view-access
  namespace: app-prod
subjects:
- kind: User
  name: engineer@company.com
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: view # Глобальная роль, локальная привязка
  apiGroup: rbac.authorization.k8s.io
```

## Дополнительная информация

### Чек-лист системного аудита объектов

1.  **Множественное число:** Ресурсы всегда во множественном числе (`configmaps`, а не `configmap`).
2.  **Подресурсы:** Проверьте доступ к `pods/log`, `pods/exec`, `nodes/metrics`. Они требуют явного указания.
3.  **Core Group:** Для базовых ресурсов (Pods, Secrets) `apiGroups` — `[""]`.
4.  **Immutability:** Помните о `roleRef`. Если роль изменилась в манифесте, `kubectl apply` не обновит биндинг без удаления.
5.  **Case Sensitivity:** Имена ресурсов и глаголы (verbs) всегда в нижнем регистре.

### Справочник групп и ресурсов (Troubleshooting Map)

| Ресурс | Группа API | Типичная область (Scope) |
|--------|------------|--------------------------|
| `pods`, `secrets`, `services` | `""` (core) | Namespace |
| `deployments`, `statefulsets` | `apps` | Namespace |
| `ingresses`, `networkpolicies`| `networking.k8s.io` | Namespace |
| `nodes`, `namespaces`, `pv` | `""` (core) | Cluster |
| `metrics` | `metrics.k8s.io` | Cluster (Aggregated) |

### Связанные ресурсы

- [Детально о ролях (Role/ClusterRole)](../../../Security/rbac/roles.md)
- [Детально о привязках (Binding)](../../../Security/rbac/bindings.md)
- [Субъекты доступа (Subjects)](../../../Security/rbac/subjects.md)
- [Алгоритм диагностики 401/403](diagnostics.md)
- [Распространенные ошибки (RBAC)](common.md)
