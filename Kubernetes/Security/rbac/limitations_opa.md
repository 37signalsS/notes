# Продвинутая авторизация: Ограничения RBAC, OPA Gatekeeper и Kyverno

## Определения

**RBAC (Role-Based Access Control)** — стандартный механизм авторизации Kubernetes, работающий на уровне API-запросов. Его логика ограничена исключительно разрешающими (allow) правилами: "кто может выполнять действие X над ресурсом Y".

**Admission Controller (Контроллер допуска)** — специализированный компонент API-сервера, который перехватывает запросы к кластеру после успешной аутентификации и авторизации (RBAC), но до фиксации изменений в etcd. Существует два типа: **Validating** (проверка соответствия) и **Mutating** (автоматическое изменение манифеста).

**OPA (Open Policy Agent)** — универсальный декларативный движок политик (Policy as Code). В Kubernetes используется через проект **Gatekeeper**, который реализует политики в виде Admission Webhook.

**Rego** — специализированный язык запросов для OPA, позволяющий описывать сложные логические условия для проверки JSON/YAML-структур.

**Kyverno** — движок политик, разработанный специально для Kubernetes. В отличие от OPA, политики описываются в нативном формате YAML, что позволяет использовать стандартные инструменты (kubectl, GitOps) без изучения нового языка программирования.

**ValidatingAdmissionPolicy** — встроенный механизм Kubernetes (v1.26+, GA в v1.30), позволяющий реализовывать логику валидации на стороне API-сервера с использованием **CEL (Common Expression Language)**. Это исключает задержки на сетевые вызовы к внешним вебхукам.

## Основные концепции

### Критические ограничения встроенного RBAC

RBAC является фундаментом безопасности, но он не предназначен для решения сложных задач управления доступом:

1.  **Отсутствие Deny-правил:** RBAC работает по принципу "белого списка". Если субъекту выданы права администратора в namespace, вы не можете точечно запретить ему удаление одного конкретного секрета через RBAC.
2.  **Отсутствие проверки контекста:** RBAC не "знает" о внешних факторах. Нельзя разрешить доступ к API только из определенной подсети (IP) или только в рабочее время администратора.
3.  **Слепота к содержимому (Payload Blindness):** RBAC проверяет только право на операцию (`create`, `update`). Он не может проверить, что в манифесте Pod-а указан `privileged: true`, не заданы `limits` или используется небезопасный образ из публичного реестра.
4.  **Статичность манифестов:** RBAC не может изменять запрос. Если разработчик забыл указать метку (label) или обязательную аннотацию, RBAC может либо разрешить создание "плохого" ресурса, либо запретить его целиком, но не может исправить его "на лету" (Mutation).

### Экосистема Admission Control

Для преодоления ограничений RBAC используется цепочка контроля:

*   **Pod Security Admission (PSA):** Встроенный контроллер, заменяющий PSP. Реализует три профиля безопасности: `Privileged`, `Baseline`, `Restricted`. См. **[Pod Security Context](../pod_security_context.md)**.
*   **ValidatingAdmissionPolicy (CEL):** Оптимальный выбор для валидации spec-полей ресурсов. Работает внутри API-сервера.
*   **OPA Gatekeeper:** Лидер в области сложных корпоративных политик. Позволяет сопоставлять данные из разных ресурсов (например, запретить Ingress, если его host уже занят в другом namespace).
*   **Kyverno:** Лучший выбор для автоматизации. Поддерживает три ключевых действия: `validate`, `mutate` и `generate` (например, автоматическое создание `NetworkPolicy` при создании нового `Namespace`).

## Практические сценарии

### Сценарий 1: Запрещающие политики (Explicit Deny)

RBAC не поддерживает запрет. В OPA Gatekeeper это реализуется через `Constraint`.

**Rego-политика для запрета удаления в kube-system:**
```rego
package kubernetes.admission

deny[msg] {
    input.request.kind.kind == "Pod"
    input.request.operation == "DELETE"
    input.request.namespace == "kube-system"
    msg := "Удаление подов в системном пространстве имен kube-system запрещено администратором."
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
          kinds:
          - Pod
          namespaces:
          - kube-system
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

RBAC не может ограничить доступ по расписанию. OPA позволяет использовать функции времени.

**Rego-политика для ограничения деплоя в выходные дни:**
```rego
package kubernetes.admission

deny[msg] {
    input.request.operation == "CREATE"
    is_weekend
    msg := "Развертывание новых ресурсов в выходные дни запрещено (Policy: No-Prod-Changes-On-Weekend)."
}

is_weekend {
    day := time.weekday(time.now_ns())
    day == "Saturday"
}

is_weekend {
    day := time.weekday(time.now_ns())
    day == "Sunday"
}
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
    msg := sprintf("Контейнер '%s' в поде запросил привилегированный режим, что запрещено.", [container.name])
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

Разрешить редактирование `ConfigMap` только в том случае, если имя пользователя совпадает с меткой `owner`.

```rego
package kubernetes.admission

deny[msg] {
    input.request.kind.kind == "ConfigMap"
    input.request.operation == "UPDATE"
    old_owner := input.request.oldObject.metadata.labels.owner
    new_owner := input.request.userInfo.username
    old_owner != new_owner
    msg := sprintf("Редактирование запрещено: владельцем ресурса является '%s', а вы — '%s'.", [old_owner, new_owner])
}
```

### Сценарий 6: Нативная валидация через CEL (Kubernetes 1.28+)

Встроенный механизм, не требующий установки OPA/Kyverno. Пример запрета использования `latest` тега в образах.

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
      message: "Использование тега ':latest' запрещено политикой безопасности."
```

### Сценарий 7: Мутация и генерация (Kyverno)

Автоматическое создание `NetworkPolicy` по умолчанию в каждом новом `Namespace`.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: default-deny-all
spec:
  rules:
  - name: create-default-deny
    match:
      any:
      - resources:
          kinds:
          - Namespace
    generate:
      apiVersion: networking.k8s.io/v1
      kind: NetworkPolicy
      name: default-deny
      namespace: "{{request.object.metadata.name}}"
      synchronize: true
      data:
        spec:
          podSelector: {}
          policyTypes:
          - Ingress
          - Egress
```

## Дополнительная информация

### Сравнение технологий авторизации

| Возможность | RBAC | CEL (Validating) | OPA Gatekeeper | Kyverno |
|-------------|------|------------------|----------------|---------|
| **Разрешения CRUD** | Да | Нет (только проверка) | Да | Да |
| **Запрещающие правила** | Нет | Да | Да | Да |
| **Условия (time, IP)** | Нет | Ограниченно | Да (через Rego) | Да |
| **Проверка содержимого** | Нет | Да | Да | Да |
| **Мутация ресурсов** | Нет | В разработке | Да (v3.13+) | Да (полная) |
| **Сложность внедрения** | Низкая | Средняя | Высокая (Rego) | Средняя (YAML) |
| **Верификация образов** | Нет | Нет | Да (через Ratify) | Да (Native Sigstore) |

### Рекомендации по архитектуре

1.  **RBAC как база:** Всегда начинайте с настройки RBAC. Политики OPA/Kyverno должны дополнять, а не заменять его.
2.  **CEL для простых проверок:** Если ваша версия Kubernetes позволяет, используйте `ValidatingAdmissionPolicy` для базовых запретов (метки, лимиты, теги образов). Это максимально производительно.
3.  **Kyverno для автоматизации:** Если вам нужно инжектить `Sidecar` контейнеры, мутировать `ServiceAccount` или генерировать ресурсы — Kyverno является де-факто стандартом.
4.  **OPA Gatekeeper для Enterprise:** Выбирайте OPA, если в компании уже используется Rego (например, в Terraform или Envoy) или требуются сложные кросс-ресурсные проверки (Inventory-based policies).

### Связанные темы

- **[Общий обзор RBAC](./rbac_overview.md)**
- **[Определение ролей (Role и ClusterRole)](./roles.md)**
- **[Основные концепции Kyverno](../kyverno/concepts.md)**
- **[Pod Security Context](../pod_security_context.md)**
- **[Аудит в Kubernetes](../../Concepts/Observability_and_Monitoring/audit_logging.md)**
