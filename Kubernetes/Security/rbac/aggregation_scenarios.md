# Агрегируемые кластерные роли (ClusterRole)

## Определения

**Агрегация ролей (Role Aggregation)** — высокоуровневый механизм в системе **RBAC (Role-Based Access Control)** Kubernetes, предназначенный для динамического и автоматического объединения наборов разрешений из нескольких [ClusterRole](./roles.md) в одну итоговую роль. Этот механизм позволяет реализовать модульную и расширяемую архитектуру управления доступом.

**Агрегирующая ClusterRole** — объект ClusterRole, определяющий логику сборки через поле `aggregationRule`. Она не содержит правил `rules` напрямую (или содержит только базовый набор), а делегирует их формирование контроллеру.

**Субъект агрегации** — любая ClusterRole, имеющая метки (labels), соответствующие селекторам агрегирующей роли.

## Основные концепции

### Механизм работы контроллера (Control Plane)

Процесс агрегации управляется встроенным в `kube-controller-manager` контроллером RBAC:
1. **Обнаружение (Discovery):** Контроллер постоянно отслеживает изменения всех объектов `ClusterRole`.
2. **Селекция (Selection):** При обнаружении роли с заполненным `aggregationRule`, контроллер выполняет поиск всех существующих ClusterRole, чьи метки удовлетворяют условиям `clusterRoleSelectors`.
3. **Объединение (Union):** Контроллер вычисляет объединение (логическое OR) всех списков `rules` из найденных ролей.
4. **Синхронизация (Synchronization):** Результат записывается в поле `rules` агрегирующей роли. Любое изменение в "дочерних" ролях инициирует немедленное обновление агрегирующей роли.

> **Важное архитектурное ограничение:** Агрегация поддерживается **только на уровне ClusterRole**. Обычные [роли (Role)](./roles.md) не имеют поля `aggregationRule`. Это связано с тем, что Role привязаны к конкретному Namespace, в то время как агрегация предназначена для формирования глобальных или кросс-пространственных шаблонов доступа.

### Структура и синтаксис aggregationRule

Поле `aggregationRule` использует стандартный механизм `LabelSelector`, поддерживающий как простые равенства, так и сложные выражения:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: system:aggregated-manager
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:          # Селектор по точному совпадению
      rbac.example.io/aggregate-to-manager: "true"
  - matchExpressions:     # Селектор по сложным условиям
    - key: rbac.example.io/tier
      operator: In
      values: ["infra", "security"]
rules: []  # Рекомендуется оставлять пустым, так как контроллер будет управлять этим полем
```

### Встроенные роли и системная агрегация

Kubernetes поставляется с набором стандартных ролей, которые уже настроены на агрегацию. Это позволяет администраторам расширять права `admin`, `edit` и `view` для новых типов ресурсов (например, CRD), просто помечая свои роли соответствующими метками.

| Системная метка (Label) | Целевая роль | Назначение |
|-------------------------|--------------|------------|
| `rbac.authorization.k8s.io/aggregate-to-admin: "true"` | `admin` | Позволяет расширить права администратора пространства имен. |
| `rbac.authorization.k8s.io/aggregate-to-edit: "true"` | `edit` | Позволяет добавить права на редактирование ресурсов. |
| `rbac.authorization.k8s.io/aggregate-to-view: "true"` | `view` | Позволяет добавить права на просмотр ресурсов. |

## Практические сценарии

### Сценарий 1: Модульное управление доступом команды (Hierarchy)

Разделение ответственности между командами инфраструктуры и CI/CD при формировании итоговой роли разработчика.

```yaml
# 1. Корневая агрегирующая роль (создается один раз)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: developer-base
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:
      rbac.company.io/aggregate-to-developer: "true"
rules: []
---
# 2. Модуль от Infra-команды: доступ к логам и чтению подов
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: developer-logs-module
  labels:
    rbac.company.io/aggregate-to-developer: "true"
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log"]
  verbs: ["get", "list", "watch"]
---
# 3. Модуль от CI/CD-команды: управление деплойментами
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: developer-deploy-module
  labels:
    rbac.company.io/aggregate-to-developer: "true"
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["create", "update", "patch", "delete", "get", "list", "watch"]
```

### Сценарий 2: Расширение стандартной роли edit для отладки

Предоставление возможности выполнять `kubectl exec` всем пользователям с ролью `edit` через создание дополняющей роли.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aggregate-edit-exec-access
  labels:
    # Эта метка заставит контроллер добавить правила ниже в ClusterRole 'edit'
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
rules:
- apiGroups: [""]
  resources: ["pods/exec"]
  verbs: ["create"]
```

### Сценарий 3: Агрегация по сложным условиям (matchExpressions)

Использование выражений для фильтрации ролей, относящихся к разным средам или командам.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: team-security-auditor
aggregationRule:
  clusterRoleSelectors:
  - matchExpressions:
    - key: rbac.company.io/scope
      operator: In
      values: ["security", "audit"]
    - key: rbac.company.io/team
      operator: Exists
rules: []
```

### Сценарий 4: Исправление совместимости и безопасности (CVE-2021-25740)

В Kubernetes v1.22+ из стандартных ролей `admin`/`edit` были удалены права на запись в `endpoints` из-за рисков безопасности. Если ваше приложение (например, старый Ingress-контроллер) требует этого:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: fix:aggregate-to-edit:endpoints
  labels:
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
rules:
- apiGroups: [""]
  resources: ["endpoints"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
```

> **Внимание:** Это действие снижает безопасность кластера. Используйте его только как временную меру при миграции.

## Дополнительная информация

### Проверка и диагностика

Для проверки того, как контроллер собрал итоговую роль, используйте `kubectl describe` или вывод в YAML:

```bash
# Проверка итогового набора правил
kubectl get clusterrole developer-base -o yaml

# Поиск всех ролей, участвующих в агрегации для конкретной метки
kubectl get clusterrole -l rbac.company.io/aggregate-to-developer=true

# Проверка прав доступа конкретного пользователя (с учетом агрегации)
kubectl auth can-i create deployments --as=system:serviceaccount:dev:default -n dev
# → yes (если агрегация прошла успешно)
```

### Автоматическое обновление системных ролей (Auto-reconciliation)

Kubernetes защищает свои встроенные роли от случайного изменения. Если вы попытаетесь вручную отредактировать `ClusterRole/view`, контроллер вернет её к исходному состоянию при следующем цикле.

**Как вносить изменения:**
1. **Рекомендуемый способ:** Всегда используйте агрегацию (создание новой роли с меткой `aggregate-to-...`).
2. **Принудительный способ:** Чтобы остановить автоматическое восстановление системной роли (не рекомендуется), добавьте аннотацию:

```yaml
metadata:
  annotations:
    rbac.authorization.kubernetes.io/autoupdate: "false"
```

### Лучшие практики (Best Practices)

1. **Имена-префиксы:** Используйте префиксы в именах агрегируемых ролей (например, `ext:`, `custom:`), чтобы отличать их от системных.
2. **Минимализм matchExpressions:** Избегайте слишком сложных селекторов, которые могут случайно захватить лишние роли.
3. **Пустые `rules`:** В агрегирующих ролях оставляйте поле `rules` пустым, чтобы избежать путаницы между статическими и динамическими правилами.
4. **Документирование меток:** Ведите реестр используемых в компании меток для агрегации, чтобы избежать конфликтов имен.

### Связанные темы

- **[Общий обзор RBAC](./rbac_overview.md)** — архитектура управления доступом.
- **[Определение ролей (Role и ClusterRole)](./roles.md)** — описание базовых объектов.
- **[Привязки ролей (RoleBinding)](./bindings.md)** — назначение прав субъектам.
- **[Дополнительная информация Kyverno: Агрегированные роли](../Security/kyverno/additional.md)** — практическое применение агрегации в контроллерах.
