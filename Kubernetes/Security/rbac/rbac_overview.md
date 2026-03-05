# Role-Based Access Control (RBAC) в Kubernetes

## Определения

**RBAC (Role-Based Access Control)** — механизм авторизации Kubernetes для гранулярного управления доступом субъектов (пользователей, групп, [ServiceAccount](./roles.md#serviceaccount)) к ресурсам кластера через декларативные правила.

Ключевые сущности:

- **Субъект** — кто запрашивает доступ: `User`, `Group`, [ServiceAccount](./roles.md#serviceaccount)
- **Роль** — набор разрешений: [Role](./roles.md#role), [ClusterRole](./roles.md#clusterrole)
- **Привязка** — связь субъекта с ролью: [RoleBinding](./bindings.md), [ClusterRoleBinding](./bindings.md)

### Предупреждения безопасности

- **`system:masters`** — группа обходит все проверки RBAC и вебхуки авторизации. Никогда не добавляйте пользователей в эту группу
- **Префикс `system:`** — зарезервирован для системных компонентов. Модификация system-ролей может нарушить работу кластера
- **`roleRef` неизменяем** — для изменения роли необходимо пересоздать binding

## Основные концепции

### Модель разрешений

RBAC опирается на три вопроса:

- **Что разрешено?** — определяется в [Role](./roles.md) и [ClusterRole](./roles.md#clusterrole)
- **Кому разрешено?** — определяется в поле `subjects` [привязок](./bindings.md)
- **Где разрешено?** — определяется уровнем привязки ([RoleBinding](./bindings.md#rolebinding) или [ClusterRoleBinding](./bindings.md#clusterrolebinding))

### Основные объекты RBAC

| Объект | Уровень | Назначение |
|--------|---------|------------|
| [Role](./roles.md#role) | Namespace | Права на namespaced-ресурсы в одном namespace |
| [ClusterRole](./roles.md#clusterrole) | Кластер | Права на кластерные ресурсы или все namespace |
| [RoleBinding](./bindings.md#rolebinding) | Namespace | Привязка роли к субъекту в одном namespace |
| [ClusterRoleBinding](./bindings.md#clusterrolebinding) | Кластер | Глобальная привязка ClusterRole к субъекту |

### Встроенные ClusterRole

Kubernetes предоставляет встроенные роли с префиксом `system:`:

| Роль | Описание |
|------|----------|
| `cluster-admin` | Полный доступ (суперпользователь). Привязка: `system:masters` |
| `admin` | Административный доступ в namespace (без управления resource quota и namespace) |
| `edit` | Чтение и запись большинства объектов в namespace |
| `view` | Только чтение (без Secrets и ролей) |
| `system:public-info-viewer` | Чтение несекретной информации о кластере (с v1.14) |
| `system:discovery` | Чтение endpoints обнаружения API |

> **Важно:** Для агрегации прав во встроенные роли используйте лейблы:
>
> - `rbac.authorization.k8s.io/aggregate-to-admin`
> - `rbac.authorization.k8s.io/aggregate-to-edit`
> - `rbac.authorization.k8s.io/aggregate-to-view`

### Принцип аддитивности

Права в RBAC **аддитивны**: итоговые возможности субъекта — это объединение всех разрешений из всех привязок. Отсутствие права означает запрет.

### Риски эскалации привилегий

| Вектор атаки | Описание | Митигация |
|--------------|----------|-----------|
| **Listing Secrets** | `list`/`watch` на Secrets раскрывает содержимое | Ограничивайте доступ к Secrets |
| **Workload Creation** | Создание Pod даёт доступ к Secrets, ConfigMaps, PV namespace'а | Используйте Pod Security Admission (Baseline/Restricted) |
| **Nodes/proxy** | Доступ к `nodes/proxy` = выполнение команд в Pod через Kubelet API | Запретить доступ |
| **escalate verb** | Позволяет создавать ClusterRole с большими правами | Запретить verb |
| **bind verb** | Позволяет создавать binding'и к ролям с недоступными правами | Запретить verb |
| **impersonate verb** | Позволяет действовать от имени других пользователей | Ограничить |
| **Token Request** | `create` на `serviceaccounts/token` выдаёт токены | Ограничить |

> **CVE-2021-25740 (v1.22+):** В новых кластерах удалён доступ на запись к EndpointSlices из ролей `admin`/`edit`.

## Практические сценарии

### Проверка прав доступа

```bash
# Проверка прав текущего пользователя
kubectl auth can-i create deployments --namespace default

# Проверка от имени другого пользователя
kubectl auth can-i list secrets --namespace dev --as jane

# Проверка от имени ServiceAccount
kubectl auth can-i list nodes --as=system:serviceaccount:observability:prometheus

# Список всех разрешений текущего пользователя
kubectl auth can-i --list

# Синхронизация RBAC-объектов из манифеста
kubectl auth reconcile -f my-rbac-rules.yaml --remove-extra-subjects --remove-extra-permissions
```

### Лучшие практики

#### 1. Принцип наименьших привилегий

```yaml
# ❌ ПЛОХО: избыточные права
rules:
- apiGroups: ["*"]
  resources: ["*"]
  verbs: ["*"]

# ✅ ХОРОШО: минимально необходимые права
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
  namespace: default
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
```

#### 2. Управление ServiceAccount (по убыванию безопасности)

| Уровень | Подход | Рекомендация |
|---------|--------|--------------|
| 1 | Роль для конкретного ServiceAccount приложения | ✅ Best Practice |
| 2 | Роль для `default` ServiceAccount в namespace | ⚠️ Permissions доступны всем pod |
| 3 | Роль для всех SA в namespace | ⚠️ Менее безопасно |
| 4 | Ограниченная роль для всех SA кластера | ❌ Не рекомендуется |
| 5 | cluster-admin для всех SA | ❌ Критическая уязвимость |

#### 3. Отключение автомонтирования токенов

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

### Изоляция по namespace

```yaml
# Доступ только к deployments в namespace 'development'
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: development
  name: deployment-manager
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "watch", "create", "update", "delete"]
---
# Привязка роли к группе разработчиков
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: devs-deployment-access
  namespace: development
subjects:
- kind: Group
  name: developers
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: deployment-manager
  apiGroup: rbac.authorization.k8s.io
```

## Дополнительная информация

### Ограничения RBAC

RBAC имеет принципиальные [ограничения](./limitations_opa.md):

- Нет запрещающих правил (deny)
- Нет условий (time, IP)
- Статичность правил
- Нет валидации содержимого ресурсов

Для расширенных сценариев используйте [OPA/Kyverno](./limitations_opa.md).

### Агрегация ролей

Для динамического объединения прав используйте [агрегируемые ClusterRole](./aggregation_scenarios.md).

### Аудит и мониторинг

- Регулярно проверяйте binding'и для группы `system:unauthenticated` и удаляйте лишние
- Удаляемые пользователи могут быть воссозданы злоумышленником с наследованием всех прав
- Используйте `kubectl auth reconcile` для синхронизации с декларативными манифестами
- Применяйте ResourceQuota для предотвращения DoS через создание объектов

### Предотвращение эскалации привилегий

API Kubernetes автоматически ограничивает создание/обновление ролей:

- Создание Role возможно только если у вас уже есть все разрешения из этой роли **ИЛИ** есть `escalate` verb
- Создание RoleBinding возможно только если у вас есть все разрешения из роли **ИЛИ** есть `bind` verb

### Ссылки

- Подробнее о ролях: [Role и ClusterRole](./roles.md)
- Подробнее о привязках: [RoleBinding и ClusterRoleBinding](./bindings.md)
- Практические сценарии агрегации: [Агрегируемые ClusterRole](./aggregation_scenarios.md)
- Ограничения и альтернативы: [Недостатки RBAC и OPA](./limitations_opa.md)
- [Kubernetes RBAC Documentation](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
- [Kubernetes RBAC Good Practices](https://kubernetes.io/docs/concepts/security/rbac-good-practices/)
