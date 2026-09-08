# Ошибка 403 Forbidden: расширенные сценарии и контроль допуска

## Определения

**Admission Control (Контроль допуска)** — специализированные плагины API-сервера, которые проверяют или изменяют запрос после успешной авторизации (RBAC), но до сохранения объекта в `etcd`. Если плагин отклоняет запрос, возвращается ошибка **403 Forbidden**.

**Admission Webhooks (Вебхуки допуска)** — механизмы расширения (Mutating и Validating), позволяющие API-серверу вызывать внешние сервисы (например, Kyverno или Gatekeeper) для реализации кастомных политик безопасности.

**failurePolicy** — политика поведения API-сервера при недоступности Admission Webhook. Два варианта: `Fail` (по умолчанию для валидирующих) — блокировать запрос при ошибке вебхука; `Ignore` — пропускать запрос, если вебхук недоступен. Опасность `Fail`: при падении внешнего контроллера политики (Kyverno, Gatekeeper) кластер может полностью заблокировать создание ресурсов.

**reinvocationPolicy** — политика повторного вызова Mutating Webhook. При значении `IfNeeded` API-сервер повторно вызывает мутирующие вебхуки, если предыдущие мутирующие контроллеры изменили объект. Значение `Never` предотвращает повторные вызовы.

**ValidatingAdmissionPolicy (VAP)** — нативный в Kubernetes (GA с v1.30) механизм валидации на базе CEL (Common Expression Language), работающий внутри процесса API-сервера без внешних вызовов. Объект `ValidatingAdmissionPolicyBinding` связывает политику с ресурсами/неймспейсами и определяет `validationActions` (Deny/Warn/Audit).

**NodeRestriction** — встроенный Admission-контроллер, ограничивающий права `kubelet`. Он гарантирует, что узел может изменять только "свои" объекты (свой `Node`, `Pod`, `PV`, `Secret` и `ConfigMap`, примонтированные к его подам).

**Агрегированные API (Aggregation Layer)** — механизм расширения Kubernetes API, позволяющий регистрировать дополнительные API-серверы (например, `metrics-server` для `metrics.k8s.io`). Ошибки 403 здесь часто связаны с правами на делегирование аутентификации и состоянием объекта `APIService`.

**Impersonation (Имитация пользователя)** — механизм отладки, позволяющий проверять права доступа от имени другого субъекта, группы или UID.

**ResourceQuota** — объект Namespace, ограничивающий суммарное потребление ресурсов (CPU, RAM, количество объектов). Поддерживает scope selectors для квотирования по `PriorityClass`, `BestEffort`/`Burstable` классам QoS.

**LimitRange** — объект Namespace, задающий min/max-границы ресурсов для контейнеров и Pod, а также значения `default` и `defaultRequest` для контейнеров без явных спецификаций.

**Pod Security Admission (PSA)** — встроенный Admission-контроллер (заменил PSP с v1.25), применяющий Pod Security Standards (PSS) на уровне Namespace через метки `pod-security.kubernetes.io/{enforce,audit,warn}`. Три профиля: `privileged`, `baseline`, `restricted`.

> Различие 401 vs 403: [definitions.md](definitions.md)
> Распространенные сценарии (RBAC): [common.md](common.md)

## Основные концепции

### Фазы контроля допуска

Прохождение запроса через Admission Controllers разделено на две фазы. Ошибка 403 может возникнуть на любой из них.

1.  **Mutating Phase:** Изменяет объект (например, внедряет sidecar-контейнеры). Если вебхук недоступен или вернул отказ — запрос блокируется.
2.  **Object Validation:** Внутренняя проверка схемы и целостности объекта.
3.  **Validating Phase:** Проверяет итоговое состояние объекта на соответствие политикам (PSA, Quotas, Webhooks).

### Пошаговый workflow диагностики 403 от Admission Control

```text
Получен 403 Forbidden
    ↓
Шаг 1: Определить источник блокировки
    kubectl <command> -v=8 2>&1 | grep -E "Audit-Id|HTTP/|admission webhook|Forbidden"
    ↓
    ├── Сообщение содержит "admission webhook" → Шаг 2A (Webhooks)
    ├── Сообщение содержит "violates PodSecurity" → Шаг 2B (PSA)
    ├── Сообщение содержит "exceeded quota" → Шаг 2C (ResourceQuota)
    ├── Сообщение содержит "exceeds the maximum" или "minimum" → Шаг 2D (LimitRange)
    └── Сообщение не содержит деталей → Шаг 2E (Общая диагностика)
    ↓
Шаг 2A: Диагностика Admission Webhooks
    2A.1 Проверить доступность webhook-сервиса:
        kubectl get endpoints <webhook-service> -n <ns>
    2A.2 Проверить конфигурацию:
        kubectl get validatingwebhookconfigurations -o wide
        kubectl get mutatingwebhookconfigurations -o wide
    2A.3 Проверить TLS-сертификаты:
        kubectl get secret <tls-secret> -n <ns> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates
    2A.4 Проверить логи контроллера:
        kubectl logs -n <ns> -l app=<controller> --tail=50
    2A.5 Проверить failurePolicy: если Fail и контроллер недоступен — временно сменить на Ignore
    ↓
Шаг 2B: Диагностика PSA
    2B.1 Проверить метки Namespace:
        kubectl get ns <ns> -o jsonpath='{.metadata.labels}' | grep pod-security
    2B.2 Определить нарушаемый профиль из сообщения об ошибке
    2B.3 Проверить audit-логи:
        kubectl get events -n <ns> --field-selector reason=FailedCreate
    ↓
Шаг 2C: Диагностика ResourceQuota
    2C.1 Проверить потребление:
        kubectl describe resourcequota -n <ns>
    2C.2 Проверить наличие LimitRange (подстановка defaults):
        kubectl get limitrange -n <ns> -o yaml
    ↓
Шаг 2D: Диагностика LimitRange
    2D.1 Проверить boundaries:
        kubectl get limitrange -n <ns> -o jsonpath='{.items[*].spec.limits[*]}'
    2D.2 Сравнить requests/limits пода с min/max из LimitRange
    ↓
Шаг 2E: Общая диагностика Admission
    2E.1 Проверить Audit-Id и найти событие в логах:
        grep <audit-id> /var/log/kubernetes/audit/audit.log
    2E.2 Проверить stage Introduced (номер этапа):
        "stage":"ResponseComplete" → запрос завершен
        "stage":"RequestReceived" → ошибка на этапе обработки
    2E.3 Проверить responseStatus.code в audit-log: 403 = admission deny
    2E.4 Проверить user.agent в audit-log для идентификации клиента
```

### Справочник команд диагностики Admission Control

| Задача | Команда |
|--------|---------|
| Просмотр webhook-конфигураций | `kubectl get validatingwebhookconfigurations -o wide` |
| Просмотр mutating webhook-конфигураций | `kubectl get mutatingwebhookconfigurations -o wide` |
| Детали конкретного webhook | `kubectl get validatingwebhookconfigurations <name> -o yaml` |
| Проверка APIService (aggregated) | `kubectl get apiservices \| grep -v True` |
| Просмотр VAP | `kubectl get validatingadmissionpolicies -o wide` |
| Просмотр VAP bindings | `kubectl get validatingadmissionpolicybindings -o wide` |
| Audit-log поиск по Audit-Id | `grep <audit-id> audit.log \| jq '.responseStatus.code'` |
| Audit-log: все deny-ответы | `jq 'select(.responseStatus.code==403)' audit.log` |
| Audit-log: этап обработки | `jq '.stage' audit.log \| sort \| uniq -c \| sort -rn` |
| Проверка PSA меток на NS | `kubectl get ns <ns> -o jsonpath='{.metadata.labels.pod-security\\.kubernetes\\.io/.*}'` |
| Проверка событий PSA | `kubectl get events --field-selector reason=FailedCreate -n <ns>` |
| Проверка потребления ResourceQuota | `kubectl describe resourcequota -n <ns>` |
| Проверка LimitRange | `kubectl get limitrange -n <ns> -o yaml` |
| Проверка TLS webhook-сертификата | `kubectl get secret <name> -n <ns> -o jsonpath='{.data.tls\.crt}' \| base64 -d \| openssl x509 -noout -dates` |
| Проверка доступности webhook-endpoints | `kubectl get endpoints <service> -n <ns>` |

## Практические сценарии

### Сценарий 1: Admission Webhooks и ValidatingAdmissionPolicy

**Контекст:** В кластере установлены инструменты Policy-as-Code (Kyverno, OPA Gatekeeper) или используются нативные политики на базе CEL (Common Expression Language).

**Ошибка:**
```text
Error from server (Forbidden): admission webhook "validate.kyverno.svc" denied the request: 
validation error: labels "app.kubernetes.io/name" is required.
```

**Анализ:** Запрос прошел RBAC, но был заблокирован `ValidatingWebhookConfiguration` или нативной `ValidatingAdmissionPolicy` (доступна с Kubernetes 1.30+). Нативные политики работают быстрее, так как не требуют сетевого вызова к внешнему вебхуку.

**Диагностика:**

```bash
# Шаг 1: Проверить конфигурации webhook
kubectl get validatingwebhookconfigurations -o wide
kubectl get mutatingwebhookconfigurations -o wide

# Шаг 2: Определить, какой webhook блокирует (из сообщения об ошибке)
# Типичный формат: "admission webhook "<name>" denied the request"

# Шаг 3: Проверить доступность webhook-сервиса
kubectl get endpoints kyverno-svc -n kyverno
# Если endpoints пусты — контроллер не запущен

# Шаг 4: Проверить TLS-сертификаты (webhook требует valid TLS)
kubectl get secret kyverno-svc-tls -n kyverno -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl x509 -noout -dates
# notBefore / notAfter — проверьте, не истёк ли сертификат

# Шаг 5: Проверить логи контроллера
kubectl logs -n kyverno -l app.kubernetes.io/name=kyverno --tail=50
```

**Ключевой параметр `failurePolicy`:**

| Значение | Поведение при недоступности webhook | Риск |
|----------|-------------------------------------|------|
| `Fail` (по умолчанию) | Блокирует все запросы, которые должны были пройти через webhook | Высокий: при падении контроллера кластер блокирует создание ресурсов |
| `Ignore` | Пропускает запрос без проверки | Низкий: политика временно не действует |

> **Рекомендация для production:** Используйте `failurePolicy: Fail` для валидирующих вебхуков безопасности, но обеспечьте высокую доступность контроллера (replicas >= 2, PDB, приоритетные классы). Для мониторинга и не критичных политик — `Ignore`.

**Мультивебхуки:**
Если несколько валидирующих webhook'ов обрабатывают один ресурс — они вызываются параллельно. Блокировка любого из них возвращает 403. Порядок Mutation Webhooks критичен: изменения одного webhook видны другим.

**Решение:** 
1. Проверить конфигурации вебхуков: `kubectl get validatingwebhookconfigurations`.
2. Проверить нативные политики: `kubectl get validatingadmissionpolicies`.
3. Изучить логи контроллера политики или структуру VAP.
4. Привести манифест в соответствие с требованиями политики.
5. При недоступности контроллера — временно сменить `failurePolicy` на `Ignore` или удалить webhook-конфигурацию.

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

**Анализ:** Агрегированные API (metrics.k8s.io, custom.metrics.k8s.io) требуют отдельных RBAC-прав и корректной работы APIService. Ошибки 403 здесь могут быть вызваны:

1. **Отсутствием RBAC-прав** на конкретный API-группу (стандартная проблема).
2. **Некорректным состоянием APIService** — если extension API-сервер недоступен или имеет невалидный сертификат.
3. **Делегированием аутентификации** — kube-apiserver转发ает запрос к extension API-серверу с данными аутентификации оригинального клиента.

**Диагностика:**

```bash
# Шаг 1: Проверить состояние APIService
kubectl get apiservices | grep metrics
# → v1beta1.metrics.k8s.io   True   metrics-server

# Шаг 2: Если Status=False — проверить доступность endpoints
kubectl get endpoints -n kube-system metrics-server
# Если endpoints пусты — metrics-server не запущен или не слушает порт

# Шаг 3: Проверить доступность напрямую
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes
# → список метрик (если OK) или ошибка (если проблема)

# Шаг 4: Проверить TLS-сертификат extension API-сервера
kubectl get apiservice v1beta1.metrics.k8s.io -o jsonpath='{.spec.caBundle}' | \
  base64 -d | openssl x509 -noout -subject -issuer

# Шаг 5: Проверить RBAC-права (кто запрашивает?)
kubectl auth can-i get nodes/metrics --as=<user> -n <ns>
```

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

> Детали metrics-server и Aggregation Layer: [../../../MonitoringLogging/metrics-server.md](../../../MonitoringLogging/metrics-server.md)
> Определение APIService: `kubectl get apiservice <name> -o yaml`

### Сценарий 4: Ресурсные квоты (ResourceQuota)

**Контекст:** Попытка создать ресурс в пространстве имен, где исчерпан лимит.

**Ошибка:**
```text
Error from server (Forbidden): pods "my-pod" is forbidden: 
exceeded quota: compute-resources, requested: requests.cpu=1, used: requests.cpu=19, limited: requests.cpu=20
```

**Анализ:** RBAC разрешает создание, но `ResourceQuota` блокирует запрос из-за превышения квоты.

**Типы ResourceQuota и их поведение:**

| Тип квоты | Ресурсы | Пример ошибки |
|-----------|---------|---------------|
| **Compute** | `requests.cpu`, `limits.cpu`, `requests.memory`, `limits.memory` | `exceeded quota: compute-resources` |
| **Object count** | `count/pods`, `count/secrets`, `count/configmaps`, `count/services` | `exceeded quota: object-count, used: 110, limited: 100` |
| **Storage** | `requests.storage`, `persistentvolumeclaims`, `storageclass.storage.k8s.io/...` | `exceeded quota: storage-quota` |
| **Scope-based** | Комбинации через `scopeSelector` (BestEffort, NotBestEffort, PriorityClass) | Зависит от scope |

**Scope selectors** позволяют квотировать ресурсы только для определённых классов подов:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: high-priority-quota
  namespace: production
spec:
  hard:
    pods: "10"
  scopeSelector:
    matchExpressions:
    - scopeName: PriorityClass
      operator: In
      values: ["high", "critical"]
```

**Взаимодействие с LimitRange:** Если в Namespace установлен `ResourceQuota` на `requests.cpu`/`requests.memory`, но поды не указывают ресурсы — LimitRange автоматически подставляет `default` и `defaultRequest` значения. Без LimitRange поды без ресурсов будут отклонены.

**Диагностика:**

```bash
# Шаг 1: Проверить потребление квоты
kubectl describe resourcequota -n <ns>
# → Name: compute-resources
# → Resource        Used  Hard
# → --------        ----  ----
# → requests.cpu    19    20
# → requests.memory 38Gi  40Gi

# Шаг 2: Определить, какие поды потребляют больше всего ресурсов
kubectl top pods -n <ns> --sort-by=cpu

# Шаг 3: Проверить LimitRange (defaults для подов без ресурсов)
kubectl get limitrange -n <ns> -o yaml
```

**Решение:** 
1. Проверить текущее состояние квот: `kubectl describe resourcequota -n <ns>`.
2. Удалить неиспользуемые ресурсы или запросить увеличение квоты у администратора.
3. Если поды не указывают ресурсы — установить LimitRange с defaults.

> Подробности по ResourceQuota и LimitRange: [../../../Scheduling/qos_limit_and_requests.md](../../../Scheduling/qos_limit_and_requests.md)

### Сценарий 5: Pod Security Admission (PSA)

**Контекст:** Попытка запустить привилегированный под в защищенном пространстве имен.

**Ошибка:**
```text
Error from server (Forbidden): pods "privileged-pod" is forbidden: 
violates PodSecurity "restricted:latest": hostNetwork: true, privileged: true
```

**Анализ:** Пространство имен помечено меткой `pod-security.kubernetes.io/enforce=restricted`.

**PSA профили и их ограничения:**

| Профиль | Ограничения | Применение |
|---------|-------------|------------|
| `privileged` | Без ограничений (все разрешено) | Системные поды (kube-system) |
| `baseline` | Запрещает privileged, hostNetwork, hostPID, hostIPC, capabilities, hostPath | Большинство прикладных подов |
| `restricted` | Baseline + требует runAsNonRoot, drop ALL capabilities, запрещает特权checkpoint | Production, PCI-DSS, SOC2 |

**Три режима работы PSA:**

| Режим | Действие | Влияние |
|-------|----------|---------|
| `enforce` | Блокирует создание пода | 403 Forbidden |
| `warn` | Возвращает предупреждение клиенту | Под создаётся, клиент видит warning |
| `audit` | Записывает нарушение в Audit-лог | Под создаётся, нарушение в логах |

**Исключения (Exemptions):** Начиная с Kubernetes 1.28, PSA поддерживает исключения для конкретных пользователей/групп:

```yaml
# Файл конфигурации PSA (в YAML-файле конфигурации API-сервера)
apiVersion: pod-security.config.k8s.io/v1
kind: PodSecurityConfiguration
defaults:
  enforce: "restricted"
  enforceVersion: "latest"
  warn: "restricted"
  warnVersion: "latest"
  audit: "restricted"
  auditVersion: "latest"
exemptions:
  usernames: ["system:serviceaccount:kube-system:*"]
  runtimeClassNames: ["gvisor"]
```

**Диагностика:**

```bash
# Шаг 1: Проверить метки Namespace
kubectl get ns <ns> -o jsonpath='{.metadata.labels}' | grep pod-security
# → {"pod-security.kubernetes.io/enforce":"restricted","pod-security.kubernetes.io/enforce-version":"latest"}

# Шаг 2: Проверить audit-события (нарушения фиксируются в логах)
kubectl get events -n <ns> --field-selector reason=FailedCreate --sort-by='.lastTimestamp'

# Шаг 3: Проверить, какой именно параметр нарушает профиль
# Сообщение об ошибке содержит: violates PodSecurity "<profile>:<version>": <violations>
# Примеры: hostNetwork: true, privileged: true, allowPrivilegeEscalation: true

# Шаг 4: Временное ослабление (для отладки)
kubectl label ns <ns> pod-security.kubernetes.io/enforce-  # удалить enforcement
kubectl label ns <ns> pod-security.kubernetes.io/enforce=baseline  # понизить профиль
```

**Решение:** Использовать профили безопасности (Baseline или Restricted) или перенести под в неймспейсе с профилем Privileged. При необходимости — временно сменить `enforce` на `warn` для выявления всех нарушений в кластере.

> Подробности PSA/PSS: [../../../Security/pod_security_context.md](../../../Security/pod_security_context.md)

## Дополнительная информация

### Сценарий 6: LimitRange — превышение min/max границ

**Контекст:** Разработчик создает под с ресурсами, не соответствующими ограничениям LimitRange в Namespace.

**Типичные ошибки:**
```text
# Превышение максимума:
Error from server (Forbidden): pods "my-pod" is forbidden: 
[maximum cpu usage per Container is 2, but limit is 4]

# Ниже минимума:
Error from server (Forbidden): pods "my-pod" is forbidden: 
[minimum cpu usage per Container is 100m, but request is 50m]

# Отсутствуют ресурсы (если LimitRange задает defaults, но под не проходит валидацию):
Error from server (BadRequest): pod "my-pod" is invalid: 
spec.containers[0].resources.requests: Required value
```

**Анализ:** LimitRange проверяется на уровне контейнера, а не Pod. Если в Namespace есть LimitRange с типом `Container`, каждый контейнер должен соответствовать `min`/`max` границам. Если `ResourceQuota` требует `requests`, а LimitRange не установлен — поды без ресурсов будут отклонены.

**Диагностика:**

```bash
# Шаг 1: Проверить LimitRange
kubectl get limitrange -n <ns> -o yaml
# → limits:
# → - max:
# │     cpu: "2"
# │     memory: "2Gi"
# │   min:
# │     cpu: "100m"
# │     memory: "128Mi"
# │   default:
# │     cpu: "500m"
# │     memory: "256Mi"
# │   defaultRequest:
# │     cpu: "100m"
# │     memory: "128Mi"
# │   type: Container

# Шаг 2: Сравнить ресурсы пода с LimitRange boundaries
kubectl get pod <name> -o jsonpath='{range .spec.containers[*]}{.name}{" → "}cpu:{.resources.limits.cpu} memory:{.resources.limits.memory}{"\n"}{end}'

# Шаг 3: Проверить ResourceQuota (если есть взаимодействие)
kubectl describe resourcequota -n <ns>
```

**Решение:**
1. Скорректировать ресурсы пода под границы LimitRange.
2. Если LimitRange установлен неправильно — обновить его (применяется только к новым подам).
3. При необходимости установить LimitRange с defaults для Namespace.

> LimitRange и ResourceQuota: [../../../Scheduling/qos_limit_and_requests.md](../../../Scheduling/qos_limit_and_requests.md)
> Типичные ошибки подов: [../../pod_pending/common_cases_and_solutions.md](../../pod_pending/common_cases_and_solutions.md)

### Сценарий 7: ValidatingAdmissionPolicy (VAP) — CEL-валидация

**Контекст:** Использование нативных политик Kubernetes на базе CEL для валидации ресурсов.

**Ошибка:**
```text
Error from server (Forbidden): pods "my-pod" is forbidden: 
[require-resource-limits] Все контейнеры должны иметь определенные resource limits
```

**Анализ:** VAP работает внутри процесса API-сервера (GA с v1.30). В отличие от webhook, ошибки VAP не зависят от доступности внешних сервисов, но могут блокировать создание ресурсов при `failurePolicy: Fail`.

**Параметр `validationActions`:**

| Действие | Описание |
|----------|----------|
| `Deny` | Возвращает 403 Forbidden (блокирует создание) |
| `Warn` | Возвращает предупреждение клиенту (под создаётся) |
| `Audit` | Записывает нарушение в Audit-лог (под создаётся) |

**Диагностика:**

```bash
# Шаг 1: Проверить VAP
kubectl get validatingadmissionpolicies -o wide
# → NAME                      AUDITED   FAILURE POLICY   AGE
# → require-resource-limits   true      Fail             2d

# Шаг 2: Проверить bindings
kubectl get validatingadmissionpolicybindings -o wide

# Шаг 3: Проверить, какие политики применяются к ресурсу
kubectl get validatingadmissionpolicy <name> -o jsonpath='{.spec.matchConstraints.resourceRules}'

# Шаг 4: Проверить audit-логи для VAP-нарушений
jq 'select(.objectRef.resource=="pods" and .responseStatus.code==403)' audit.log | jq '.user.username, .objectRef.namespace'
```

> Полная документация VAP: [../../../Concepts/admission_controllers.md](../../../Concepts/admission_controllers.md)
> Политики OPA/Kyverno: [../../../Security/rbac/limitations_opa.md](../../../Security/rbac/limitations_opa.md)

### Сводная таблица ошибок Admission Control

| Сообщение об ошибке | Вероятная причина | Шаг диагностики | Решение |
|---------------------|-------------------|-----------------|---------|
| `admission webhook "<name>" denied the request` | Webhook-контроллер отклонил ресурс по политике | Проверить логи контроллера, конфигурацию webhook | Привести манифест к политике или изменить политику |
| `admission webhook "<name>" failed to call webhook` | Webhook-сервис недоступен | `kubectl get endpoints <service>` | Проверить доступность контроллера, сменить `failurePolicy` на `Ignore` |
| `violates PodSecurity "<profile>:<version>"` | Нарушение PSA (Pod Security Admission) | Проверить метки NS, audit-логи | Исправить securityContext пода или сменить профиль PSA |
| `exceeded quota: <name>` | Превышен ResourceQuota | `kubectl describe resourcequota -n <ns>` | Увеличить квоту или удалить неиспользуемые ресурсы |
| `exceeds the maximum` / `minimum` | LimitRange min/max violation | `kubectl get limitrange -n <ns> -o yaml` | Скорректировать ресурсы пода под границы LimitRange |
| `cannot get resource "<resource>" in API group "<group>"` | Агрегированный API недоступен или нет RBAC | `kubectl get apiservices \| grep <group>` | Проверить APIService и RBAC-права |
| `user "<name>" was not found` | Невалидный субъект в webhook/VAP binding | Проверить subject в конфигурации | Исправить имя субъекта или ServiceAccount |
| `x509: certificate signed by unknown authority` | TLS-сертификат webhook-signed не доверен API-серверу | `openssl x509 -noout -text -in cert.pem` | Обновить CA Bundle в webhook-конфигурации |

## Кластерные ресурсы vs Ресурсы неймспейса

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

### RBAC pre-check перед отладкой Admission

Прежде чем отлаживать Admission Control, убедитесь, что проблема НЕ в RBAC. Команда `kubectl auth can-i` проверяет только RBAC, но не Admission — это частый источник путаницы.

```bash
# Шаг 1: Проверить, разрешает ли RBAC действие
kubectl auth can-i create pods --as=<user> -n <ns>
# → yes / no

# Шаг 2: Если RBAC разрешает, но ошибка 403 сохраняется — проблема в Admission
# Добавить -v=8 для деталей:
kubectl create -f pod.yaml -n <ns> -v=8 2>&1 | grep -E "Audit-Id|admission|Forbidden|HTTP/"

# Шаг 3: Проверить audit-log для полной картины
# Audit-log содержит поле "user.username", "objectRef", "responseStatus.code"
# и "annotations.authorization.k8s.io/decision" (allow/deny)
jq 'select(.responseStatus.code==403)' audit.log | jq '.user.username, .objectRef.resource, .annotations'
```

> Полный алгоритм диагностики RBAC: [diagnostics.md](diagnostics.md)
> Имперсонация для отладки: [../../../Security/authentication.md](../../../Security/authentication.md)

### Версионные особенности Admission Control

| Версия | Изменение | Влияние на 403 |
|--------|-----------|-----------------|
| **v1.25** | Удалён PodSecurityPolicy (PSP) | Переход на PSA. Политики PSP больше не работают. |
| **v1.26** | PSA: стабильные метки `pod-security.kubernetes.io` | Метки PSP заменены на PSA-метки. |
| **v1.28** | PSA: exemptions | Возможность исключения ServiceAccount/классов runtime из enforcement. |
| **v1.30** | VAP (GA) | ValidatingAdmissionPolicy стабилен. Нативная CEL-валидация доступна по умолчанию. |
| **v1.31** | MutatingAdmissionPolicy (beta) | Мутация на базе CEL (без webhook). |

### Связанные ресурсы

- [Распространенные случаи (Namespaced)](common.md)
- [Пошаговая диагностика](diagnostics.md)
- [Объекты RBAC (Role, Binding)](rbac_objects.md)
- [Контроллеры допуска (Обзор)](../../Concepts/admission_controllers.md)
- [Продвинутая авторизация (OPA/Kyverno/VAP)](../../../Security/rbac/limitations_opa.md)
