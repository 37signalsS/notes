# Объекты RBAC: структура и типичные ошибки конфигурации

## Определения

**Объекты RBAC (Role-Based Access Control)** — это набор ресурсов Kubernetes, которые описывают политику доступа к API. При возникновении ошибки **403 Forbidden** проблема всегда кроется в конфигурации одного из этих объектов или в отсутствии связи между ними.

**Субъект (Subject)** — личность (User), группа (Group) или учетная запись приложения (ServiceAccount), запрашивающая доступ.

**Правило (Rule)** — описание разрешенного действия (`verb`) над конкретным ресурсом (`resource`) в определенной группе API (`apiGroup`).

> Полное описание архитектуры RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)

## Основные концепции

### Структурная модель доступа

Доступ предоставляется только тогда, когда все три элемента связаны воедино объектом **Binding**.

```text
КТО? (Subject) ← [БИНДИНГ] → ЧТО МОЖНО? (Role / ClusterRole)
                                    ↓
                            ПРАВИЛА (Verbs + Resources)
```

### Основные объекты и их область видимости

| Объект | Область видимости | Назначение в диагностике |
|--------|-------------------|--------------------------|
| **ServiceAccount** | Namespace | Проверьте, под каким аккаунтом запущен Pod (`spec.serviceAccountName`). |
| **Role** | Namespace | Содержит правила для ресурсов внутри одного пространства имен. |
| **ClusterRole** | Кластер | Содержит правила для кластерных ресурсов или общие правила для всех пространств имен. |
| **RoleBinding** | Namespace | Связывает субъекта с `Role` или `ClusterRole` (в рамках одного namespace). |
| **ClusterRoleBinding**| Кластер | Связывает субъекта с `ClusterRole` на уровне всего кластера. |

### Ключевые атрибуты правил

Для успешной авторизации в объекте `Role` или `ClusterRole` должны быть точно указаны:

1.  **apiGroups:** Группа API (например, `apps`, `batch`, `networking.k8s.io`). Для базовых ресурсов (поды, секреты) используется пустая строка `""`.
2.  **resources:** Список ресурсов во **множественном числе** (`pods`, `services`).
3.  **verbs:** Допустимые действия (`get`, `list`, `watch`, `create`, `update`, `patch`, `delete`).

## Практические сценарии

### Сценарий 1: Проверка соответствия субъекта и биндинга

Частая причина ошибки 403 — опечатка в имени субъекта или неверный namespace в `RoleBinding`.

**Как проверить:**
```bash
# Получение списка всех биндингов в неймспейсе с деталями субъектов
kubectl get rolebindings -n <namespace> -o custom-columns='NAME:.metadata.name,SUBJECT_KIND:.subjects[*].kind,SUBJECT_NAME:.subjects[*].name'
```

### Сценарий 2: Определение правильной API-группы

Ошибка в `apiGroups` — самая частая причина нерабочих ролей. Если вы не уверены, к какой группе относится ресурс, используйте встроенную справку.

**Команда:**
```bash
# Поиск группы и версии для ресурса (например, Ingress)
kubectl api-resources | grep ingress
# → ingresses  networking.k8s.io/v1  true  Ingress

# В правиле RBAC это будет:
# apiGroups: ["networking.k8s.io"]
# resources: ["ingresses"]
```

### Сценарий 3: Использование ClusterRole в локальном RoleBinding

Вы можете привязать глобальную роль (например, встроенную `view`) к локальному субъекту через `RoleBinding`. Это даст субъекту права только в том неймспейсе, где создан `RoleBinding`.

**Пример (YAML):**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: read-only-access
  namespace: my-app
subjects:
- kind: ServiceAccount
  name: default
  namespace: my-app
roleRef:
  kind: ClusterRole
  name: view # Использование стандартной кластерной роли
  apiGroup: rbac.authorization.k8s.io
```

## Дополнительная информация

### Чек-лист проверки объектов при ошибке 403

1.  **Множественное число:** Убедитесь, что ресурсы указаны как `secrets`, а не `secret`.
2.  **Подресурсы:** Для доступа к логам используйте `pods/log`, для выполнения команд — `pods/exec`.
3.  **Core Group:** Для базовых ресурсов (Pods, ConfigMaps, Secrets, Services, PV, PVC) `apiGroups` ВСЕГДА `[""]`.
4.  **Case Sensitivity:** Имена ресурсов и глаголы должны быть в нижнем регистре.
5.  **ServiceAccount Namespace:** При указании ServiceAccount в качестве субъекта убедитесь, что его namespace указан верно, иначе API-сервер его не узнает.

### Справочник типичных API-групп

| Группа | Ресурсы |
|--------|---------|
| `""` (core) | `pods`, `services`, `configmaps`, `secrets`, `persistentvolumeclaims`, `nodes`, `namespaces` |
| `apps` | `deployments`, `statefulsets`, `daemonsets`, `replicasets` |
| `batch` | `jobs`, `cronjobs` |
| `networking.k8s.io` | `ingresses`, `networkpolicies` |
| `rbac.authorization.k8s.io` | `roles`, `clusterroles`, `rolebindings`, `clusterrolebindings` |
| `autoscaling` | `horizontalpodautoscalers` |

### Связанные ресурсы

- Роли и кластерные роли (Детально): [../../../Security/rbac/roles.md](../../../Security/rbac/roles.md)
- Привязки (Детально): [../../../Security/rbac/bindings.md](../../../Security/rbac/bindings.md)
- Алгоритм диагностики: [diagnostics.md](diagnostics.md)
- Распространенные ошибки 403: [common.md](common.md)
