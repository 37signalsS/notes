# Продвинутая авторизация: Ограничения RBAC, OPA Gatekeeper и Kyverno

## Определения

**RBAC (Role-Based Access Control)** — стандартный механизм авторизации Kubernetes, работающий на уровне API-запросов. Его логика ограничена исключительно разрешающими (allow) правилами: "кто может выполнять действие X над ресурсом Y".

**Admission Controller (Контроллер допуска)** — специализированный компонент API-сервера, который перехватывает запросы к кластеру после успешной аутентификации и авторизации (RBAC), но до фиксации изменений в etcd. Существует два типа:
- **Validating** (валидирующий): проверка соответствия политике (решение Allow/Deny).
- **Mutating** (мутирующий): автоматическое изменение манифеста "на лету".

**OPA (Open Policy Agent)** — универсальный декларативный движок политик (Policy as Code). В Kubernetes реализуется через проект **Gatekeeper**, использующий Admission Webhooks. Использует язык **Rego**.

**Kyverno** — движок политик, разработанный специально для Kubernetes. Описывает политики в нативном YAML-формате, что позволяет использовать стандартные инструменты без изучения Rego.

**ValidatingAdmissionPolicy (VAP)** — встроенный в ядро Kubernetes (GA в v1.30) механизм декларативной валидации на базе **CEL (Common Expression Language)**. Работает внутри процесса API-сервера без вызова внешних вебхуков.

---

## Основные концепции

### Критические ограничения встроенного RBAC

RBAC является фундаментом безопасности, но имеет четыре фундаментальных "слепых пятна":

1.  **Отсутствие Deny-правил:** RBAC работает только на дополнение (аддитивность). Если субъекту выданы права администратора в namespace, вы не можете точечно запретить ему удаление конкретного Secret или ConfigMap.
2.  **Слепота к контексту (Context Blindness):** RBAC не учитывает внешние атрибуты запроса. Нельзя ограничить доступ по времени суток, IP-адресу или типу клиента (User-Agent).
3.  **Слепота к содержимому (Payload Blindness):** RBAC проверяет только глагол и ресурс. Он не может проверить, что в `Pod` указан `privileged: true`, не заданы `limits` или используется образ из недоверенного Registry.
4.  **Статичность манифестов:** RBAC не может изменять (мутировать) ресурсы. Он либо разрешает запрос целиком, либо блокирует его.

### Экосистема Admission Control

Для преодоления ограничений RBAC используется цепочка контроля допуска. Полный разбор механизмов, фаз и встроенных контроллеров см. в **[Контроллеры допуска (Admission Controllers)](../../Concepts/admission_controllers.md)**.

Краткий обзор дополняющих технологий:
*   **Pod Security Admission (PSA):** Обязательный минимум. Реализует стандарты безопасности подов через метки неймспейсов.
*   **ValidatingAdmissionPolicy (CEL):** Рекомендуемый выбор для 80% задач валидации в современных кластерах (1.30+). Работает внутри API-сервера.
*   **Kyverno:** Лидер в области автоматизации. Идеален для мутации ресурсов (инъекция Sidecars) и генерации (автосоздание NetworkPolicy).
*   **OPA Gatekeeper:** Enterprise-стандарт для сложных кросс-ресурсных проверок и унификации политик.

### Риски и надежность (Failure Policy)

Внешние контроллеры (OPA/Kyverno) вносят риски в стабильность Control Plane:

- **Latency (Задержка):** Каждый запрос к API требует сетевого вызова к вебхуку. При проблемах с сетью создание ресурсов замедляется.
- **Failure Policy:** Определяет поведение API-сервера, если вебхук недоступен:
    - `Ignore`: запрос пропускается (безопасность под угрозой).
    - `Fail`: запрос блокируется (доступность кластера под угрозой).
- **Audit vs Enforce:** Рекомендуется начинать внедрение политик в режиме `Audit`, чтобы оценить влияние на текущие рабочие нагрузки без их блокировки.

---

## Практические сценарии

### Сценарий 1: Явный запрет (Explicit Deny)

RBAC не поддерживает запрет. В OPA это реализуется через `Constraint`.

**Rego-политика для защиты системного неймспейса:**
```rego
package kubernetes.admission

deny[msg] {
    input.request.kind.kind == "Pod"
    input.request.operation == "DELETE"
    input.request.namespace == "kube-system"
    msg := "Удаление системных подов в kube-system запрещено политикой организации."
}
```

**Аналогичная политика в Kyverno:**
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: deny-delete-kube-system
spec:
  validationFailureAction: Enforce
  rules:
  - name: block-system-delete
    match:
      any:
      - resources:
          kinds: [Pod]
          namespaces: [kube-system]
    preconditions:
      all:
      - key: "{{request.operation}}"
        operator: Equals
        value: DELETE
    validate:
      message: "Удаление ресурсов в kube-system запрещено."
      deny:
        conditions:
          all:
          - key: "{{request.object.metadata.namespace}}"
            operator: Equals
            value: kube-system
```

### Сценарий 2: Условия на основе времени

**Rego-политика для запрета деплоя в выходные дни:**
```rego
package kubernetes.admission

deny[msg] {
    input.request.operation == "CREATE"
    day := time.weekday(time.now_ns())
    is_weekend(day)
    msg := "Развертывание новых ресурсов в выходные дни запрещено (Policy: No-Prod-Changes-On-Weekend)."
}

is_weekend(day) { day == "Saturday" }
is_weekend(day) { day == "Sunday" }
```

### Сценарий 3: Валидация содержимого (Resource Guarding)

Проверка наличия лимитов ресурсов и запрет привилегированных контейнеров.

**Rego-политика (OPA):**
```rego
package kubernetes.admission

# 1. Запрет privileged контейнеров
deny[msg] {
    input.request.kind.kind == "Pod"
    container := input.request.object.spec.containers[_]
    container.securityContext.privileged
    msg := sprintf("Контейнер '%s' запросил привилегированный режим, что запрещено.", [container.name])
}

# 2. Обязательные лимиты памяти
deny[msg] {
    input.request.kind.kind == "Pod"
    container := input.request.object.spec.containers[_]
    not container.resources.limits.memory
    msg := sprintf("Для контейнера '%s' не указаны memory limits.", [container.name])
}
```

### Сценарий 4: Проверка на основе сетевых атрибутов (IP-адрес)

OPA Gatekeeper имеет доступ к `remoteAddress` субъекта, выполняющего запрос.

```rego
package kubernetes.admission

deny[msg] {
    input.request.kind.kind == "Secret"
    input.request.operation == "GET"
    not net.cidr_contains("10.50.0.0/16", input.request.remoteAddress)
    msg := "Доступ к секретам разрешен только из доверенной VPN-подсети управления."
}
```

### Сценарий 5: Логика владения ресурсами (Resource Ownership)

Разрешить редактирование `ConfigMap` только если имя пользователя совпадает с меткой `owner`.

```rego
package kubernetes.admission

deny[msg] {
    input.request.kind.kind == "ConfigMap"
    input.request.operation == "UPDATE"
    old_owner := input.request.oldObject.metadata.labels.owner
    new_owner := input.request.userInfo.username
    old_owner != new_owner
    msg := sprintf("Владельцем ресурса является '%s', а вы — '%s'.", [old_owner, new_owner])
}
```

### Сценарий 6: Нативная валидация через CEL (K8s 1.30+)

Пример запрета использования тега `:latest`. Работает максимально производительно.

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: "deny-latest-tag"
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["pods"]
  validations:
    - expression: "object.spec.containers.all(c, !c.image.endsWith(':latest'))"
      message: "Использование тега ':latest' запрещено. Используйте фиксированные версии образов."
```

### Сценарий 7: Мутация и генерация (Kyverno)

Автоматическая инъекция `NetworkPolicy` "Deny All" в каждый новый `Namespace`.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: default-network-policy
spec:
  rules:
  - name: create-default-deny
    match:
      any:
      - resources:
          kinds: [Namespace]
    generate:
      apiVersion: networking.k8s.io/v1
      kind: NetworkPolicy
      name: default-deny-all
      namespace: "{{request.object.metadata.name}}"
      synchronize: true
      data:
        spec:
          podSelector: {}
          policyTypes: [Ingress, Egress]
```

---

## Дополнительная информация

### Сравнение технологий авторизации

| Возможность | RBAC | CEL (VAP) | OPA Gatekeeper | Kyverno |
|-------------|------|-----------|----------------|---------|
| **Разрешения CRUD** | Да | Нет | Да | Да |
| **Запрещающие правила** | Нет | Да | Да | Да |
| **Условия (время, IP)** | Нет | Да | Да (Rego) | Да |
| **Производительность** | Высокая | **Максимальная** | Средняя | Средняя/Высокая |
| **Мутация (Mutation)** | Нет | Нет | Да (v3.13+) | Да (полная) |
| **Сложность внедрения** | Низкая | Средняя | Высокая (Rego) | Средняя (YAML) |
| **Влияние на API Latency** | Нет | Нет | Да (+50-200ms) | Да (+30-150ms) |
| **Верификация образов** | Нет | Нет | Да (Ratify) | Да (Native) |

### Рекомендации по выбору

1.  **Принцип "CEL-First":** Если политика может быть описана через `ValidatingAdmissionPolicy`, используйте её. Это снижает нагрузку на кластер и риск блокировки API-сервера.
2.  **Kyverno для K8s-native:** Лучший выбор для мутаций, генерации ресурсов и автоматизации в YAML-стеке.
3.  **OPA для сложных иерархий:** Используйте OPA, если нужны кросс-ресурсные проверки на основе всего состояния кластера (inventory) или если Rego уже используется в компании.
4.  **Failure Policy:** Для критических политик безопасности используйте `Fail`, обеспечивая HA контроллера. Для вспомогательных (метки, аннотации) — `Ignore`.

### Связанные темы

- **[Общий обзор RBAC](./rbac_overview.md)**
- **[Определение ролей (Role и ClusterRole)](./roles.md)**
- **[Основные концепции Kyverno](../kyverno/concepts.md)**
- **[Pod Security Context](../pod_security_context.md)**
- **[Аудит в Kubernetes](../audit.md)**
