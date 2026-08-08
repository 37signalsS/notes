# Ошибка 403 Forbidden: расширенные сценарии и контроль допуска

## Определения

**Admission Control (Контроль допуска)** — специализированные плагины API-сервера, которые проверяют или изменяют запрос после успешной авторизации (RBAC), но до сохранения объекта в `etcd`. Если плагин отклоняет запрос, возвращается ошибка **403 Forbidden**.

**Admission Webhooks (Вебхуки допуска)** — механизмы расширения (Mutating и Validating), позволяющие API-серверу вызывать внешние сервисы (например, Kyverno или Gatekeeper) для реализации кастомных политик безопасности.

**NodeRestriction** — встроенный Admission-контроллер, ограничивающий права `kubelet`. Он гарантирует, что узел может изменять только "свои" объекты (свой `Node`, `Pod`, `PV`, `Secret` и `ConfigMap`, примонтированные к его подам).

**Агрегированные API (Aggregation Layer)** — механизм расширения Kubernetes API, позволяющий регистрировать дополнительные API-серверы (например, `metrics-server` для `metrics.k8s.io`). Ошибки 403 здесь часто связаны с правами на делегирование аутентификации.

**Impersonation (Имитация пользователя)** — механизм отладки, позволяющий проверять права доступа от имени другого субъекта, группы или UID.

> Различие 401 vs 403: [definitions.md](definitions.md)
> Распространенные сценарии (RBAC): [common.md](common.md)

## Основные концепции

### Фазы контроля допуска

Прохождение запроса через Admission Controllers разделено на две фазы. Ошибка 403 может возникнуть на любой из них.

1.  **Mutating Phase:** Изменяет объект (например, внедряет sidecar-контейнеры). Если вебхук недоступен или вернул отказ — запрос блокируется.
2.  **Object Validation:** Внутренняя проверка схемы и целостности объекта.
3.  **Validating Phase:** Проверяет итоговое состояние объекта на соответствие политикам (PSA, Quotas, Webhooks).

### Продвинутая диагностика (Impersonation)

Для выявления сложных проблем доступа используйте флаги имитации. Это позволяет проверить, как API-сервер интерпретирует права конкретного ServiceAccount или внешней группы (например, из OIDC).

```bash
# Проверка прав ServiceAccount с имитацией
kubectl auth can-i list pods \
  --as=system:serviceaccount:my-ns:my-sa \
  -n my-ns

# Проверка прав группы (например, из OIDC/Azure AD)
kubectl auth can-i create deployments \
  --as=dev-user \
  --as-group=developers \
  -n project-x

# Проверка от имени конкретного UID (для сложных случаев аудита)
kubectl auth can-i get secrets --as=admin --as-uid=1000
```

> Полный алгоритм диагностики: [diagnostics.md](diagnostics.md)

## Практические сценарии

### Сценарий 1: Admission Webhooks и ValidatingAdmissionPolicy

**Контекст:** В кластере установлены инструменты Policy-as-Code (Kyverno, OPA Gatekeeper) или используются нативные политики на базе CEL (Common Expression Language).

**Ошибка:**
```text
Error from server (Forbidden): admission webhook "validate.kyverno.svc" denied the request: 
validation error: labels "app.kubernetes.io/name" is required.
```

**Анализ:** Запрос прошел RBAC, но был заблокирован `ValidatingWebhookConfiguration` или нативной `ValidatingAdmissionPolicy` (доступна с Kubernetes 1.30+). Нативные политики работают быстрее, так как не требуют сетевого вызова к внешнему вебхуку.

**Решение:** 
1. Проверить конфигурации вебхуков: `kubectl get validatingwebhookconfigurations`.
2. Проверить нативные политики: `kubectl get validatingadmissionpolicies`.
3. Изучить логи контроллера политики или структуру VAP.
4. Привести манифест в соответствие с требованиями политики.

### Сценарий 2: NodeRestriction (Безопасность узлов)

**Контекст:** Специфический процесс на узле (или скомпрометированный `kubelet`) пытается изменить объект, к которому не имеет отношения.

**Ошибка:**
```text
Error from server (Forbidden): nodes "other-node" is forbidden: 
node "this-node" is not allowed to modify node "other-node"
```

**Анализ:** Плагин `NodeRestriction` блокирует попытки узла выйти за пределы своей зоны ответственности.
**Решение:** Проверить, почему запрос направлен на чужой ресурс. Если это легитимный контроллер, он должен использовать собственный `ServiceAccount` с правами `ClusterRole`, а не токен узла.

### Сценарий 3: Агрегированные API (metrics-server)

**Контекст:** Пользователь или система мониторинга пытается получить метрики ресурсов.

**Ошибка:** `User "..." cannot get resource "nodes/metrics" in API group "metrics.k8s.io"`

**Решение:** Для агрегированных API часто недостаточно стандартных прав. Требуется роль для доступа к метрикам.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: read-metrics
subjects:
- kind: User
  name: monitoring-bot
roleRef:
  kind: ClusterRole
  name: system:metrics-server
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 4: Ресурсные квоты (ResourceQuota)

**Контекст:** Попытка создать ресурс в пространстве имен, где исчерпан лимит.

**Ошибка:**
```text
Error from server (Forbidden): pods "my-pod" is forbidden: 
exceeded quota: compute-resources, requested: requests.cpu=1, used: requests.cpu=19, limited: requests.cpu=20
```

**Анализ:** RBAC разрешает создание, но `ResourceQuota` блокирует запрос из-за превышения квоты.
**Решение:** 
1. Проверить текущее состояние квот: `kubectl describe resourcequota -n <ns>`.
2. Удалить неиспользуемые ресурсы или запросить увеличение квоты у администратора.

### Сценарий 5: Pod Security Admission (PSA)

**Контекст:** Попытка запустить привилегированный под в защищенном пространстве имен.

**Ошибка:**
```text
Error from server (Forbidden): pods "privileged-pod" is forbidden: 
violates PodSecurity "restricted:latest": hostNetwork: true, privileged: true
```

**Анализ:** Пространство имен помечено меткой `pod-security.kubernetes.io/enforce=restricted`.
**Решение:** Использовать профили безопасности (Baseline или Restricted) или перенести под в неймспейсе с профилем Privileged.

## Дополнительная информация

### Кластерные ресурсы vs Ресурсы неймспейса

Для ресурсов кластерного уровня (Nodes, Namespaces, PV) использование `Role` невозможно — всегда требуется `ClusterRole` и `ClusterRoleBinding`.

| Уровень | Ресурсы | Объект RBAC |
|---------|---------|--------------|
| **Кластер** | `nodes`, `namespaces`, `pv`, `storageclasses` | `ClusterRole` |
| **Namespace**| `pods`, `services`, `secrets`, `configmaps` | `Role` |

### Изоляция через ResourceNames

Для критически важных объектов (например, секретов с ключами инфраструктуры) рекомендуется использовать `resourceNames` в правилах RBAC. Это предотвращает ошибку 403 при точечном доступе, не открывая права на все объекты типа.

```yaml
rules:
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["infra-master-key"]
  verbs: ["get", "patch"]
```

### Связанные ресурсы

- [Распространенные случаи (Namespaced)](common.md)
- [Пошаговая диагностика](diagnostics.md)
- [Объекты RBAC (Role, Binding)](rbac_objects.md)
- [Контроллеры допуска (Обзор)](../../Concepts/admission_controllers.md)
- [Продвинутая авторизация (OPA/Kyverno)](../../../Security/rbac/limitations_opa.md)
