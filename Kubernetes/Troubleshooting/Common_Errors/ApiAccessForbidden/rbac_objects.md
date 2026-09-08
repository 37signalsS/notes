# Объекты RBAC: структура и типичные ошибки конфигурации

## Определения

**Объекты RBAC (Role-Based Access Control)** — набор ресурсов Kubernetes, определяющих политику авторизации. При возникновении ошибки **403 Forbidden** проблема всегда локализована в одном из этих объектов или в нарушении логической связи между ними.

**Субъект (Subject)** — личность (User), группа (Group) или учетная запись приложения (ServiceAccount).

**Правило (Rule)** — описание разрешенного действия (`verb`) над ресурсом (`resource`) в конкретной группе API (`apiGroup`).

**Связь (Binding)** — мост между субъектом и набором правил (Role/ClusterRole).

**Неизменяемость (Immutability)** — после создания объекта `RoleBinding` или `ClusterRoleBinding` поле `roleRef` нельзя изменить без удаления и пересоздания объекта. Это ключевой аспект при отладке "зависших" прав.

**Агрегация (AggregationRule)** — механизм автоматического сбора правил из нескольких `ClusterRole` в одну агрегированную роль по селектору меток (`matchLabels` или `matchExpressions`).

> Полное архитектурное описание RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)

## Основные концепции

### Структурная модель доступа

Авторизация успешна только при наличии корректно настроенной цепочки:

```text
КТО? (Subject) ← [БИНДИНГ] → ЧТО МОЖНО? (Role / ClusterRole)
    ↓                ↓                   ↓
Namespace/Name   Immutable Ref        API Group + Verb + Resource
```

### Алгоритм проверки RBAC при 403 Forbidden

```text
ОШИБКА 403 FORBIDDEN
    ↓
1. Проверить субъекта (Subject)
   ├── Верно ли указано имя?
   ├── Верно ли указан namespace (для SA)?
   └── Есть ли SA с таким именем?
    ↓
2. Проверить биндинг (Binding)
   ├── Существует ли RoleBinding/ClusterRoleBinding?
   ├── Указана ли правильная роль в roleRef?
   └── roleRef не был изменен после создания?
    ↓
3. Проверить роль (Role/ClusterRole)
   ├── Указана ли правильная apiGroup?
   ├── Ресурс указан во множественном числе?
   ├── Указаны нужные verbs?
   └── Есть ли resourceNames ограничения?
    ↓
4. Проверить scope (область видимости)
   ├── Role виден только в своем namespace?
   ├── ClusterRole дает доступ ко всем namespace?
   └── RoleBinding с ClusterRole работает только в одном namespace?
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
*   ServiceAccount был удален и пересоздан с тем же именем (старый биндинг на пересозданный SA может не работать).

**Диагностика:**
```bash
# Просмотр сырых данных биндинга для выявления ошибок в subjects
kubectl get rolebinding <name> -n <ns> -o jsonpath='{.subjects}'

# Проверка существования SA
kubectl get sa <sa-name> -n <ns>

# Просмотр всех SA с токенами
kubectl get sa -n <ns> -o custom-columns=NAME:.metadata.name,SECRETS:.secrets[*].name,automount:.automountServiceAccountToken

# Проверка, какой SA используется в поде
kubectl get pod <pod-name> -n <ns> -o jsonpath='{.spec.serviceAccountName}'
```

**Ожидаемый результат:**
```text
[{"kind":"ServiceAccount","name":"my-sa","namespace":"default","apiGroup":"rbac.authorization.k8s.io"}]
```

Если поле `namespace` пустое или отсутствует — это типичная ошибка.

### Сценарий 2: Идентификация API-группы ресурса

**Проблема:** Ошибка 403 из-за неверного `apiGroups` в роли (например, попытка использовать `""` для `deployments`).

**Диагностика:**
```bash
# Получение группы и версии для любого ресурса
kubectl api-resources -o wide | grep "ingresses"
# → ingresses  networking.k8s.io/v1  true  Ingress

# Проверка всех доступных групп API
kubectl api-resources -o wide | awk '{print $3}' | sort -u

# Проверка конкретной группы API
kubectl api-resources --api-group=apps

# Проверка всех ресурсов core группы
kubectl api-resources --api-group=""
```

**Типичные ошибки:**
```yaml
# ❌ Неправильно: deployments в core группе
rules:
- apiGroups: [""]
  resources: ["deployments"]
  verbs: ["get"]

# ✅ Правильно: deployments в группе apps
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get"]
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

### Сценарий 4: Неизменяемость roleRef

**Проблема:** При попытке обновить `roleRef` через `kubectl apply` обновление не применяется, и субъект получает старые права.

**Причины:**
*   Поле `roleRef` является **неизменяемым** после создания объекта.
*   Kubernetes не позволяет изменить роль в существующем биндинге.

**Диагностика:**
```bash
# Проверка текущего roleRef
kubectl get rolebinding <name> -n <ns> -o jsonpath='{.roleRef}'

# Сравнение с ожидаемым значением из манифеста
kubectl diff -f manifest.yaml
```

**Решение:**
```bash
# Удаление старого биндинга и создание нового
kubectl delete rolebinding <name> -n <ns>
kubectl apply -f updated-binding.yaml
```

### Сценарий 5: Агрегация ролей (AggregationRule)

**Проблема:** Права субъекта внезапно расширились или сузились без видимых изменений в его ClusterRole.

**Причины:**
*   ClusterRole использует `aggregationRule` и собирает правила из других ролей.
*   Изменение меток в дочерних ролях влияет на агрегированную роль.

**Диагностика:**
```bash
# Проверка агрегации в роли
kubectl get clusterrole <name> -o jsonpath='{.aggregationRule}'

# Поиск всех ролей, агрегирующихся в данную
kubectl get clusterroles -o json | jq '.items[] | select(.aggregationRule.matchLabels != null) | {name: .metadata.name, labels: .aggregationRule.matchLabels}'

# Просмотр всех прав в агрегированной роли
kubectl describe clusterrole <name>
```

### Сценарий 6: Кросс-неймспейс доступ

**Проблема:** ServiceAccount из одного namespace получает доступ к ресурсам в другом namespace.

**Причины:**
*   `RoleBinding` в целевом namespace ссылается на SA из исходного namespace.
*   `ClusterRoleBinding` дает доступ ко всем namespace.

**Диагностика:**
```bash
# Поиск всех RoleBinding с кросс-неймспейс субъектами
kubectl get rolebindings -A -o json | jq '.items[] | select(.subjects[]? | .kind == "ServiceAccount" and .namespace != null) | {namespace: .metadata.namespace, name: .metadata.name, subjects: .subjects[]}'

# Проверка всех кросс-неймспейс привязок для конкретного SA
kubectl get rolebindings -A -o json | jq --arg sa "my-sa" --arg ns "source-ns" '.items[] | select(.subjects[]? | .kind == "ServiceAccount" and .name == $sa and .namespace == $ns) | "\(.metadata.namespace)/\(.metadata.name)"'
```

### Сценарий 7: Ошибки в подресурсах

**Проблема:** Доступ к `pods/log` или `pods/exec` запрещен, хотя доступ к `pods` разрешен.

**Причины:**
*   Подресурсы требуют **явного указания** в правилах RBAC.
*   `verbs: ["*"]` не включает автоматический доступ ко всем подресурсам.

**Диагностика:**
```bash
# Проверка доступа к подресурсам
kubectl auth can-i get pods/log --as=system:serviceaccount:default:my-sa -n default
kubectl auth can-i create pods/exec --as=system:serviceaccount:default:my-sa -n default

# Просмотр всех подресурсов
kubectl api-resources | grep -E "pods|nodes" | head -20
```

**Правильная конфигурация:**
```yaml
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log", "pods/exec"]
  verbs: ["get", "create"]
```

## Дополнительная информация

### Чек-лист системного аудита объектов

1.  **Множественное число:** Ресурсы всегда во множественном числе (`configmaps`, а не `configmap`).
    ```bash
    # Проверка правильного написания ресурса
    kubectl auth can-i get configmaps --as=system:serviceaccount:default:my-sa
    kubectl auth can-i get configmap --as=system:serviceaccount:default:my-sa  # ❌ Ошибка
    ```

2.  **Подресурсы:** Проверьте доступ к `pods/log`, `pods/exec`, `nodes/metrics`. Они требуют явного указания.
    ```bash
    # Проверка доступа к подресурсам
    kubectl auth can-i get pods/log --as=system:serviceaccount:default:my-sa
    kubectl auth can-i create pods/exec --as=system:serviceaccount:default:my-sa
    ```

3.  **Core Group:** Для базовых ресурсов (Pods, Secrets) `apiGroups` — `[""]`.
    ```bash
    # Проверка группы для ресурса
    kubectl api-resources -o wide | grep pods
    # → pods  v1  true  Pod
    ```

4.  **Immutability:** Помните о `roleRef`. Если роль изменилась в манифесте, `kubectl apply` не обновит биндинг без удаления.
    ```bash
    # Проверка roleRef в существующем биндинге
    kubectl get rolebinding <name> -n <ns> -o jsonpath='{.roleRef}'
    ```

5.  **Case Sensitivity:** Имена ресурсов и глаголы (verbs) всегда в нижнем регистре.
    ```yaml
    # ❌ Неправильно
    rules:
    - apiGroups: [""]
      resources: ["ConfigMaps"]
      verbs: ["Get"]
    
    # ✅ Правильно
    rules:
    - apiGroups: [""]
      resources: ["configmaps"]
      verbs: ["get"]
    ```

### Справочник групп и ресурсов (Troubleshooting Map)

| Ресурс | Группа API | Типичная область (Scope) | Пример roleRef |
|--------|------------|--------------------------|----------------|
| `pods`, `secrets`, `services` | `""` (core) | Namespace | `[""]` |
| `deployments`, `statefulsets` | `apps` | Namespace | `["apps"]` |
| `ingresses`, `networkpolicies`| `networking.k8s.io` | Namespace | `["networking.k8s.io"]` |
| `nodes`, `namespaces`, `pv` | `""` (core) | Cluster | `[""]` |
| `metrics` | `metrics.k8s.io` | Cluster (Aggregated) | `["metrics.k8s.io"]` |
| `customresourcedefinitions` | `apiextensions.k8s.io` | Cluster | `["apiextensions.k8s.io"]` |
| `validatingwebhookconfigurations` | `admissionregistration.k8s.io` | Cluster | `["admissionregistration.k8s.io"]` |

### Команды быстрой диагностики

```bash
# Просмотр всех разрешений для субъекта
kubectl auth can-i --list --as=system:serviceaccount:default:my-sa -n default

# Проверка конкретного действия
kubectl auth can-i create deployments --as=system:serviceaccount:default:my-sa -n default

# Просмотр всех RoleBinding в namespace
kubectl get rolebindings -n <ns> -o custom-columns=NAME:.metadata.name,ROLE:.roleRef.name,SUBJECTS:.subjects[*].name

# Просмотр всех ClusterRoleBinding
kubectl get clusterrolebindings -o custom-columns=NAME:.metadata.name,ROLE:.roleRef.name,SUBJECTS:.subjects[*].name

# Поиск всех привязок для конкретного SA
kubectl get rolebindings,clusterrolebindings -A -o json | jq '.items[] | select(.subjects[]? | .kind == "ServiceAccount" and .name == "my-sa") | {kind: .kind, name: .metadata.name, namespace: .metadata.namespace, role: .roleRef.name}'
```

### Распространенные ошибки конфигурации

| Ошибка | Симптомы | Причина | Решение |
|--------|----------|---------|---------|
| **Неверный namespace в subjects** | SA не получает права | namespace не указан или указан неверно | Указать правильный namespace для SA |
| **Ресурс не во множественном числе** | 403 Forbidden | `configmap` вместо `configmaps` | Использовать множественное число |
| **Неверная apiGroup** | 403 Forbidden | `""` вместо `apps` для deployments | Проверить группу через `kubectl api-resources` |
| **roleRef изменен** | Права не обновляются | roleRef неизменяем | Удалить и пересоздать биндинг |
| **Подресурс не указан** | Доступ к logs/exec запрещен | Требуется явное указание | Добавить `pods/log`, `pods/exec` в resources |
| **Case sensitivity** | 403 Forbidden | `ConfigMaps` вместо `configmaps` | Использовать нижний регистр |

### Сценарии восстановления после ошибок

**Сценарий A: Неверно настроенный RoleBinding**
```bash
# 1. Диагностика
kubectl get rolebinding <name> -n <ns> -o yaml

# 2. Удаление неверного биндинга
kubectl delete rolebinding <name> -n <ns>

# 3. Создание правильного биндинга
kubectl apply -f correct-binding.yaml

# 4. Проверка
kubectl auth can-i <verb> <resource> --as=<subject> -n <ns>
```

**Сценарий B: Агрегация ролей изменила права**
```bash
# 1. Проверка агрегации
kubectl get clusterrole <name> -o jsonpath='{.aggregationRule}'

# 2. Просмотр дочерних ролей
kubectl get clusterroles -l <label-key>=<label-value>

# 3. Корректировка меток в дочерних ролях
kubectl label clusterrole <child-role> <label-key>=<label-value> --overwrite

# 4. Проверка результата
kubectl describe clusterrole <name>
```

### Связанные ресурсы

- [Детально о ролях (Role/ClusterRole)](../../../Security/rbac/roles.md)
- [Детально о привязках (Binding)](../../../Security/rbac/bindings.md)
- [Субъекты доступа (Subjects)](../../../Security/rbac/subjects.md)
- [Алгоритм диагностики 401/403](diagnostics.md)
- [Распространенные ошибки (RBAC)](common.md)
