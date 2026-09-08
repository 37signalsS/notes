# Продвинутая авторизация: Ограничения RBAC, OPA Gatekeeper, Kyverno и ValidatingAdmissionPolicy

## Определения

**RBAC (Role-Based Access Control)** — стандартный механизм авторизации Kubernetes, работающий на уровне API-запросов. Его логика ограничена исключительно разрешающими (allow) правилами: "кто может выполнять действие X над ресурсом Y".

**Admission Controller (Контроллер допуска)** — специализированный компонент API-сервера, который перехватывает запросы к кластеру после успешной аутентификации и авторизации (RBAC), но до фиксации изменений в etcd. Существует два типа:
- **Validating** (валидирующий): проверка соответствия политике (решение Allow/Deny).
- **Mutating** (мутирующий): автоматическое изменение манифеста "на лету".

**OPA (Open Policy Agent)** — универсальный декларативный движок политик (Policy as Code). В Kubernetes реализуется через проект **Gatekeeper**, использующий Admission Webhooks. Использует язык **Rego**.

**Gatekeeper** — OPA-проект для Kubernetes, реализующий политики через **Constraint Templates** (шаблоны правил) и **Constraints** (экземпляры шаблонов с конкретными параметрами). Работает как Validating Admission Webhook с встроенным механизмом аудита существующих ресурсов.

**Kyverno** — движок политик, разработанный специально для Kubernetes. Описывает политики в нативном YAML-формате, что позволяет использовать стандартные инструменты без изучения Rego. Поддерживает три типа операций: валидацию, мутацию и генерацию ресурсов.

**ValidatingAdmissionPolicy (VAP)** — встроенный в ядро Kubernetes (GA в v1.30) механизм декларативной валидации на базе **CEL (Common Expression Language)**. Работает внутри процесса API-сервера без вызова внешних вебхуков. Наиболее производительный и надежный вариант для базовых политик валидации.

**CEL (Common Expression Language)** — язык выражений, разработанный Google для безопасной оценкиexpr-essions в белом режиме (sandbox). Используется в VAP, Audit и других компонентах Kubernetes. Поддерживает типизацию, работу со строками, списками, картами и встроенными функциями (regex, datetime, existence checks).

---

## Основные концепции

### Критические ограничения встроенного RBAC

RBAC является фундаментом безопасности, но имеет четыре фундаментальных "слепых пятна":

1.  **Отсутствие Deny-правил:** RBAC работает только на дополнение (аддитивность). Если субъекту выданы права администратора в namespace, вы не можете точечно запретить ему удаление конкретного Secret или ConfigMap.
2.  **Слепота к контексту (Context Blindness):** RBAC не учитывает внешние атрибуты запроса. Нельзя ограничить доступ по времени суток, IP-адресу или типу клиента (User-Agent).
3.  **Слепота к содержимому (Payload Blindness):** RBAC проверяет только глагол и ресурс. Он не может проверить, что в `Pod` указан `privileged: true`, не заданы `limits` или используется образ из недоверенного Registry.
4.  **Статичность манифестов:** RBAC не может изменять (мутировать) ресурсы. Он либо разрешает запрос целиком, либо блокирует его.

### Полная цепочка обработки запроса

Для понимания места Admission Control в жизненном цикле запроса:

```text
ЗАПРОС КЛИЕНТА
     ↓
1. AUTHENTICATION (аутентификация) — проверка личности
     ↓
2. AUTHORIZATION (авторизация) — RBAC проверяет права
     ↓
3. MUTATING ADMISSION (мутирующий контроль допуска)
   ├── Встроенные контроллеры (LimitRanger, ServiceAccount, PSA, и т.д.)
   ├── Внешние MutatingWebhook (Kyverno, Istio Sidecar Injection)
   └── Результат: модифицированный объект
     ↓
4. VALIDATING ADMISSION (валидирующий контроль допуска)
   ├── Встроенные контроллеры (PodSecurity, NamespaceLifecycle, ResourceQuota)
   ├── ValidatingAdmissionPolicy (CEL)
   ├── Внешние ValidatingWebhook (OPA Gatekeeper, Kyverno)
   └── Результат: Allow или 403 Forbidden
     ↓
5. СОХРАНЕНИЕ В etcd
```

**Порядок выполнения мутирующих вебхуков** имеет значение: изменения, внесенные одним контроллером, видны последующим. Если мутирующие вебхуки изменили объект, API-сервер запускает цикл мутации повторно (кроме контроллеров с `reinvocationPolicy: Never`), чтобы гарантировать согласованность финального состояния.

**Порядок выполнения валидирующих контроллеров** не имеет значения: они запускаются параллельно для минимизации задержек. Объекты на этом этапе доступны только для чтения.

### Архитектура OPA Gatekeeper

Gatekeeper реализует три ключевых концепции:

```text
Constraint Template (шаблон правила)
     ├── Определяет: Rego-логику + параметры (schema)
     ├── Пример: "запрет privileged контейнеров, параметр — список namespace"
     └── Сущность: кластерная (ClusterConstraintTemplate)
            ↓
Constraint (конкретный запрет)
     ├── Применяет шаблон к конкретным ресурсам
     ├── Задаёт параметры: namespaces: ["kube-system", "production"]
     └── Сущность: ClusterConstraint или NamespaceConstraint
```

**Потоки данных в Gatekeeper:**

1. **Admission (Валидация):** API-сервер вызывает Gatekeeper webhook → Gatekeeper загружает Constraint Template и Constraint → выполняет Rego-политику → возвращает Allow/Deny.
2. **Audit (Аудит):** Фоновый процесс.periodically сканирует все ресурсы кластера и применяет к ним Constraint Templates. Результаты записываются в `status.violations` каждого Constraint. Позволяет обнаружить нарушения политик в уже существующих ресурсах.
3. **Sync (Синхронизация):** Кэширование данных из API-сервера (например, списка Namespace или Pod) для использования в Rego-политиках. Уменьшает количество запросов к API и повышает производительность.

**Constraint Template — пример:**

```yaml
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8spspprivilegedcontainer
spec:
  crd:
    spec:
      names:
        kind: K8sPSPPrivilegedContainer
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        package k8spspprivilegedcontainer
        violation[{"msg": msg}] {
          container := input.review.object.spec.containers[_]
          container.securityContext.privileged == true
          msg := sprintf("Контейнер '%v' работает в привилегированном режиме.", [container.name])
        }
```

**Constraint — применение шаблона:**

```yaml
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sPSPPrivilegedContainer
metadata:
  name: deny-privileged
spec:
  match:
    kinds:
      - apiGroups: [""]
        kinds: ["Pod"]
    excludedNamespaces:
      - kube-system
      - gatekeeper-system
```

**Важно:** Rego — язык декларативный, работающий по принципу "всё что не запрещено — разрешено" (closed world assumption). Правила определяют условия нарушения (`violation`), а не разрешения. Если ни одно правило не срабатывает — запрос разрешается.

### Архитектура Kyverno

Kyverno использует модульную архитектуру с четырьмя контроллерами:

| Контроллер | Функция | Тип операций |
|:---|:---|:---|
| **Admission Controller** | Обработка Admission-запросов | Валидация + Мутация |
| **Background Controller** | Фоновая проверка существующих ресурсов | Валидация + Мутация + Генерация |
| **Cleanup Controller** | Автоматическое удаление ресурсов по TTL/расписанию | Delete |
| **Reports Controller** | Агрегация результатов в PolicyReport | Read-only |

**Типы политик Kyverno:**

1. **Validate:** Проверяет ресурсы на соответствие правилам. Аналог OPA Constraints.
2. **Mutate:** Изменяет ресурсы "на лету" (добавляет лейблы, аннотации, env-переменные, securityContext).
3. **Generate:** Создаёт новые ресурсы (NetworkPolicy, ResourceQuota, ConfigMap) при определённых условиях (например, при создании Namespace).

**CEL-first архитектура (v1.13+):**
Kyverno может транслировать простые validate-политики в нативные **ValidatingAdmissionPolicy (VAP)** Kubernetes. Преимущества: проверки выполняются API-сервером без сетевых вызовов, политики работают даже при недоступности контроллера Kyverno.

### ValidatingAdmissionPolicy (VAP) — нативная валидация CEL

VAP — наиболее производительный и надежный вариант для базовых политик, поскольку работает внутри API-сервера без внешних зависимостей.

**Ключевые особенности (GA v1.30+):**

- **Без внешних вебхуков:** Проверки выполняются непосредственно в процессе API-сервера. Нет сетевой задержки, нет зависимости от внешнего сервиса.
- **CEL без побочных эффектов:** CEL работает в sandbox-режиме — не может обращаться к внешним системам, модифицировать файлы или выполнять сетевые запросы.
- **Parametrized Policies:** Шаблоны с параметрами, позволяющие переиспользовать одну политику для разных namespace/групп ресурсов.

**ValidatingAdmissionPolicyBinding — связывание:**

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: "deny-latest-binding"
spec:
  policyName: "deny-latest-tag"
  matchResources:
    namespaceSelector:
      matchLabels:
        enforce-image-policy: "true"
```

**Продвинутые возможности CEL:**

```yaml
# Проверка наличия всех обязательных лейблов
validations:
  - expression: "has(object.metadata.labels) && ['team', 'env', 'app'].all(l, l in object.metadata.labels)"
    message: "Отсутствуют обязательные лейблы: team, env, app."

# Запрет определённых комбинаций (нельзя использовать :latest в production)
validations:
  - expression: |
      !(namespace in ['production', 'staging']) || 
      object.spec.containers.all(c, !c.image.endsWith(':latest'))
    message: "Использование :latest запрещено в production/staging."

# Проверка что образ coming из доверенного registry
validations:
  - expression: "object.spec.containers.all(c, c.image.startsWith('registry.internal.company.com/'))"
    message: "Разрешены только образы из registry.internal.company.com."
```

### Наблюдаемость и аудит (Monitoring)

Валидация политик требует прозрачности. Стандартный Gatekeeper ограничен в экспорте метрик нарушений.

**Режимы работы (и для OPA, и для Kyverno):**

| Режим | Назначение | Влияние на кластер |
|:---|:---|:---|
| **Audit** | Обнаружение нарушений в существующих ресурсах без блокировки | Минимальное (фоновое сканирование) |
| **Enforce** | Блокировка новых ресурсов, не соответствующих политике | Полное (Admission Reject) |
| **DryRun** | Тестирование политик без фактического применения | Нет |

- **Audit-режим:** Первоначальное внедрение политик без блокировки ресурсов. Рекомендуется для оценки влияния политики на текущие рабочие нагрузки перед включением Enforce.
- **[opus-scorecard](../../../GitOps/Concepts/gitops-policy-management.md#наблюдаемость-и-мониторинг-нарушений):** Решение для экспорта детальных сведений о нарушениях (объекты, неймспейсы) в Prometheus/Grafana.
- **Policy Reports (Kyverno):** Нативные Kubernetes-ресурсы (`PolicyReport`, `ClusterPolicyReport`) с результатами проверки. Поддержка стандартов `policy.openk8s.io/v1beta1` и `openreports.io` (v1.15+).
- **Gatekeeper Audit Violations:** Результаты аудита записываются в `status.violations` Constraint-ресурсов. Можно мониторить через `kubectl get constraints -o json`.

### Риски и надежность (Failure Policy)

Внешние контроллеры (OPA/Kyverno) вносят риски в стабильность Control Plane:

- **Latency (Задержка):** Каждый запрос к API требует сетевого вызова к вебхуку. При проблемах с сетью создание ресурсов замедляется.
- **Failure Policy:** Определяет поведение API-сервера, если вебхук недоступен:
    - `Ignore`: запрос пропускается (безопасность под угрозой).
    - `Fail`: запрос блокируется (доступность кластера под угрозой).
- **Audit vs Enforce:** Рекомендуется начинать внедрение политик в режиме `Audit`, чтобы оценить влияние на текущие рабочие нагрузки без их блокировки.

**Рекомендации по Failure Policy:**

| Тип политики | Failure Policy | Причина |
|:---|:---|:---|
| Критические проверки безопасности (privileged, root) | `Fail` | Нарушение безопасности недопустимо |
| Метки и аннотации (стандартизация) | `Ignore` | Блокировка API из-за меток нерациональна |
| Генерация ресурсов (NetworkPolicy) | `Fail` | Отсутствие сетевой политики — критический риск |
| Вспомогательные проверки (лишь рекомендации) | `Ignore` | Доступность важнее комплаенса |

### Производительность и масштабирование

**Факторы влияния на производительность:**

| Фактор | Влияние | Рекомендация |
|:---|:---|:---|
| Количество Constraint Templates | Умеренное (загрузка Rego при старте) | Оптимизируйте количество шаблонов |
| Количество Constraints | Среднее (каждый запрос проверяется всеми Constraints) | Используйте `spec.match` для фильтрации |
| Сложность Rego/CEL | Высокое (сложные регулярные выражения, вложенные циклы) | Профилируйте Rego через `opa eval` |
| Сетевая задержка к webhook | Критическое (+50-200ms на запрос) | Размещайте контроллеры в同一个 zone |
| Audit scanning | Умеренное (фоновое сканирование всех ресурсов) | Настройте `--audit-interval` (по умолчанию 60s) |

**Оптимизации для крупных кластеров:**

1. **match-правила:** Используйте `spec.match.kinds`, `spec.match.namespaces`, `spec.match.excludedNamespaces` для ограничения области действия Constraints.
2. **CEL-first (Kyverno):** Для простых политик транслируйте в VAP — проверки выполняются без сетевых вызовов.
3. **Кэширование (Gatekeeper):** Настройте `config` ресурс Gatekeeper для кэшированияrequently запрашиваемых данных (Namespace, Pod).
4. **Приоритет вебхуков:** Используйте `matchConditions` (CEL-фильтры) для исключения лишних вызовов (например, "вызывать вебхук только для подов без метки `skip-scan`").
5. **Ресурсы контроллеров:** Увеличьте CPU/Limits для Gatekeeper/Kyverno при большом количестве Constraints (>100).

### Миграция между механизмами

**Миграция PSP → OPA/Kyverno/VAP:**
PodSecurityPolicy (PSP) удалён в Kubernetes v1.25. Миграция обязательна.

| PSP-правило | OPA/Rego эквивалент | Kyverno эквивалент | VAP/CEL эквивалент |
|:---|:---|:---|:---|
| `privileged: false` | `container.securityContext.privileged == false` | `validate.securityContext.privileged` | `object.spec.containers.all(c, !c.securityContext.privileged)` |
| `readOnlyRootFilesystem: true` | `container.securityContext.readOnlyRootFilesystem == true` | `validate.securityContext.readOnlyRootFilesystem` | `object.spec.containers.all(c, c.securityContext.readOnlyRootFilesystem)` |
| `runAsNonRoot: true` | `input.review.object.spec.securityContext.runAsNonRoot == true` | `validate.podSecurity.runAsNonRoot` | `object.spec.securityContext.runAsNonRoot == true` |
| `allowedCapabilities` | `not container.securityContext.capabilities.add[_]` | `validate.securityContext.capabilities` | Каждая capability отдельно |

**Миграция OPA → Kyverno:**
1. Определите OPA-политики, требующие мутации или генерации (Rego не поддерживает эти операции).
2. Переведите Rego-логику в Kyverno YAML (validate-политики обычно мигрируются легко).
3. Для кросс-ресурсных проверок оцените, нужны ли они — Kyverno поддерживает `foreach` и `context` для обращения к другим ресурсам.
4. Тестирование: используйте `kyverno test` для локальной проверки политик.

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

**Kyverno-аналог:**
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: deny-weekend-deploy
spec:
  validationFailureAction: Enforce
  rules:
  - name: check-weekend
    match:
      any:
      - resources:
          kinds: [Deployment, StatefulSet, DaemonSet]
    preconditions:
      all:
      - key: "{{request.operation}}"
        operator: Equals
        value: CREATE
    validate:
      message: "Создание ресурсов в выходные запрещено."
      deny:
        conditions:
          any:
          - key: "{{time_now_utc()}}"
            operator: RegexMatch
            value: ".*Saturday.*|.*Sunday.*"
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

**VAP-эквивалент (CEL):**
```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: "require-resource-limits"
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["pods"]
  validations:
    - expression: "object.spec.containers.all(c, has(c.resources.limits.memory) && has(c.resources.limits.cpu))"
      message: "Все контейнеры должны иметь memory и cpu limits."
    - expression: "!object.spec.containers.exists(c, c.securityContext.privileged == true)"
      message: "Привилегированные контейнеры запрещены."
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

### Сценарий 8: Установка OPA Gatekeeper

**Предварительные требования:**
- Kubernetes v1.25+
- `kubectl` с правами администратора
- Helm v3.x

```bash
# Добавление репозитория OPA
helm repo add gatekeeper https://open-policy-agent.github.io/gatekeeper/charts
helm repo update

# Установка Gatekeeper (namespace gatekeeper-system создаётся автоматически)
helm install gatekeeper gatekeeper/gatekeeper \
  --namespace gatekeeper-system \
  --set replicas=3 \
  --set audit.replicas=2 \
  --set audit.interval=60

# Проверка установки
kubectl get pods -n gatekeeper-system
# → gatekeeper-audit-xxx         1/1     Running
# → gatekeeper-controller-xxx    1/1     Running
# → gatekeeper-policy-controller-xxx  1/1     Running

# Загрузка Catalog Template (пример: запрет privileged контейнеров)
kubectl apply -f - <<EOF
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8spspprivilegedcontainer
spec:
  crd:
    spec:
      names:
        kind: K8sPSPPrivilegedContainer
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        package k8spspprivilegedcontainer
        violation[{"msg": msg}] {
          container := input.review.object.spec.containers[_]
          container.securityContext.privileged == true
          msg := sprintf("Контейнер '%v' работает в привилегированном режиме.", [container.name])
        }
EOF

# Создание Constraint (применение шаблона)
kubectl apply -f - <<EOF
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sPSPPrivilegedContainer
metadata:
  name: deny-privileged
spec:
  match:
    kinds:
      - apiGroups: [""]
        kinds: ["Pod"]
    excludedNamespaces:
      - kube-system
      - gatekeeper-system
EOF

# Проверка (попытка создания привилегированного пода должна быть отклонена)
kubectl run test-pod --image=nginx --privileged
# → Error from server (Forbidden): admission webhook "validation.gatekeeper.sh" denied the request...
```

### Сценарий 9: Установка Kyverno

```bash
# Добавление репозитория
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update

# Установка (namespace kyverno создаётся автоматически)
helm install kyverno kyverno/kyverno \
  --namespace kyverno \
  --set replicaCount=3 \
  --set backgroundController.replicaCount=2 \
  --set cleanupController.replicaCount=1 \
  --set reportsController.replicaCount=1

# Проверка
kubectl get pods -n kyverno
# → kyverno-admission-controller-xxx    1/1     Running
# → kyverno-background-controller-xxx   1/1     Running
# → kyverno-cleanup-controller-xxx      1/1     Running
# → kyverno-reports-controller-xxx      1/1     Running

# Применение политики
kubectl apply -f - <<EOF
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-labels
spec:
  validationFailureAction: Enforce
  rules:
  - name: check-team-label
    match:
      any:
      - resources:
          kinds: ["Deployment", "StatefulSet", "DaemonSet"]
    validate:
      message: "Метка 'team' обязательна для всех рабочих нагрузок."
      pattern:
        metadata:
          labels:
            team: "?*"
EOF

# Проверка (попытка создания деплоя без метки team)
kubectl create deployment test --image=nginx
# → Error from server (Forbidden): admission webhook "validate.kyverno.svc-fail" denied the request...
```

### Сценарий 10: Тестирование политик в CI/CD

**OPA/Conftest (для проверки манифестов перед деплоем):**

```bash
# Установка conftest
# brew install conftest (macOS) или https://github.com/open-policy-agent/conftest

# Проверка манифеста
conftest test deployment.yaml --policy policy/
# → FAIL - deployment.yaml - к8spspprivilegedcontainer: Контейнер 'app' привилегирован

# Генерация отчёта
conftest test deployment.yaml --policy policy/ --output json
```

**Kyverno CLI (для тестирования политик локально):**

```bash
# Установка kyverno CLI
# brew install kyverno-cli (macOS)

# Тестирование политики
kyverno test ./tests/
# → Applying 3 test cases...
# → test-case-1: PASSED
# → test-case-2: PASSED  
# → test-case-3: PASSED (expected: FAIL)

# Проверка конкретного манифеста
kyverno apply policy.yaml --resource deployment.yaml
```

### Сценарий 11: Диагностика и отладка политик

**OPA Gatekeeper:**

```bash
# Проверка Constraint на наличие violations
kubectl get constraint deny-privileged -o json | jq '.status.violations'

# Просмотр логов контроллера
kubectl logs -n gatekeeper-system -l control-plane=controller-manager --tail=100

# Включение подробного логирования
kubectl set env deployment/gatekeeper-controller-manager -n gatekeeper-system GATEKEEPER_LOG_LEVEL=DEBUG

# Ручная проверка Rego через OPA CLI
opa eval -d policy/ 'data.k8spspprivilegedcontainer.violation'
```

**Kyverno:**

```bash
# Просмотр PolicyReport
kubectl get policyreport -A
kubectl get policyreport -n default -o yaml

# Просмотр логов контроллера
kubectl logs -n kyverno -l app.kubernetes.io/name=kyverno --tail=100

# Проверка конкретной политики
kubectl get clusterpolicy require-labels -o yaml

# Включение debug-логирования
kubectl set env deployment/kyverno-admission-controller -n kyverno KYVERNO_LOG_LEVEL=debug

# Тестирование политики через CLI
kyverno apply policy.yaml --resource bad-deployment.yaml -v 4
```

### Сценарий 12: Исключения из политик (Policy Exceptions)

**OPA Gatekeeper — используется ресурс `Constraint` с `match.excludedNamespaces`:**

```yaml
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sPSPPrivilegedContainer
metadata:
  name: deny-privileged
spec:
  match:
    kinds:
      - apiGroups: [""]
        kinds: ["Pod"]
    excludedNamespaces:
      - kube-system
      - gatekeeper-system
      - monitoring
```

**Kyverno — ресурс `PolicyException` (POLE):**

```yaml
apiVersion: kyverno.io/v1alpha2
kind: PolicyException
metadata:
  name: allow-privileged-monitoring
  namespace: monitoring
spec:
  exceptions:
  - policyName: deny-privileged
    ruleNames:
    - check-privileged
  match:
    any:
    - resources:
        kinds: [Pod]
        namespaces: [monitoring]
```

### Сценарий 13: GitOps для управления политиками

Политики безопасности должны управляться через Git для аудита, версионирования и воспроизводимости.

**Структура репозитория:**
```
policies/
├── gatekeeper/
│   ├── templates/
│   │   ├── k8spspprivilegedcontainer.yaml
│   │   ├── k8spspreadonlyrootfilesystem.yaml
│   │   └── k8spsplimits.yaml
│   └── constraints/
│       ├── deny-privileged.yaml
│       ├── require-readonly-rootfs.yaml
│       └── require-limits.yaml
├── kyverno/
│   ├── require-labels.yaml
│   ├── deny-latest-tag.yaml
│   └── generate-default-networkpolicy.yaml
├── vap/
│   ├── deny-latest.yaml
│   └── require-labels.yaml
└── tests/
    ├── gatekeeper/
    │   └── test-privileged.rego
    └── kyverno/
        └── test-require-labels/
```

**Применение через Argo CD:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: security-policies
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://git.internal.company.com/security/policies.git
    targetRevision: main
    path: gatekeeper/constraints
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### Сценарий 14: Верификация образов (Supply Chain Security)

**Kyverno + Cosign (Sigstore) — проверка подписи образа:**

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signature
spec:
  validationFailureAction: Enforce
  rules:
  - name: verify-cosign-signature
    match:
      any:
      - resources:
          kinds: [Pod]
    verifyImages:
    - imageReferences:
      - "registry.internal.company.com/*"
      attestors:
      - entries:
        - keys:
            publicKeys: |-
              -----BEGIN PUBLIC KEY-----
              MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
              -----END PUBLIC KEY-----
          rekor:
            url: https://rekor.sigstore.dev
```

**Проверка SBOM через Kyverno:**
```yaml
    verifyImages:
    - imageReferences:
      - "registry.internal.company.com/*"
      attestors:
      - entries:
        - attestors:
          - entries:
            - keyless:
                subject: "https://github.com/company/app"
                issuer: "https://token.actions.githubusercontent.com"
              rekor:
                url: https://rekor.sigstore.dev
      attestations:
      - type: https://spdx.dev/Document
        conditions:
        - all:
          - key: "{{licenseInfo[*].licenseId}}"
            operator: AnyIn
            value: ["Apache-2.0", "MIT", "BSD-2-Clause"]
```

---

## Дополнительная информация

### Сравнение технологий авторизации

| Возможность | RBAC | CEL (VAP) | OPA Gatekeeper | Kyverno |
|:---|:---|:---|:---|:---|
| **Разрешения CRUD** | Да | Нет | Да | Да |
| **Запрещающие правила** | Нет | Да | Да | Да |
| **Условия (время, IP)** | Нет | Да | Да (Rego) | Да |
| **Мутация (Mutation)** | Нет | Нет | Да (v3.13+) | Да (полная) |
| **Генерация ресурсов** | Нет | Нет | Нет | Да |
| **Производительность** | Высокая | **Максимальная** | Средняя | Средняя/Высокая |
| **Зависимость от внешних сервисов** | Нет | Нет | Да (Webhook) | Да (Webhook) |
| **Сложность внедрения** | Низкая | Средняя | Высокая (Rego) | Средняя (YAML) |
| **Влияние на API Latency** | Нет | Нет | Да (+50-200ms) | Да (+30-150ms) |
| **Верификация образов** | Нет | Нет | Да (Ratify) | Да (Native Cosign) |
| **Audit (фоновая проверка)** | Нет | Нет | Да | Да |
| **Policy Reports** | Нет | Нет | Ограниченно | Да (нативные CR) |
| **Пригодность для GitOps** | Высокая | Высокая | Высокая | Высокая |

### Рекомендации по выбору

1.  **Принцип "CEL-First":** Если политика может быть описана через `ValidatingAdmissionPolicy`, используйте её. Это снижает нагрузку на кластер и риск блокировки API-сервера.
2.  **Kyverno для K8s-native:** Лучший выбор для мутаций, генерации ресурсов и автоматизации в YAML-стеке. Поддерживает CEL-first (трансляция в VAP) для базовых проверок.
3.  **OPA для сложных иерархий:** Используйте OPA, если нужны кросс-ресурсные проверки на основе всего состояния кластера (inventory) или если Rego уже используется в компании.
4.  **Failure Policy:** Для критических политик безопасности используйте `Fail`, обеспечивая HA контроллера. Для вспомогательных (метки, аннотации) — `Ignore`.
5.  **Мониторинг:** Начинайте внедрение с `Audit`-режима. Переключайтесь на `Enforce` после анализа PolicyReport/Gatekeeper Violations.
6.  **Тестирование:** Тестируйте политики в CI/CD через `conftest` (OPA), `kyverno test` (Kyverno) или `kubectl apply --dry-run=server` (VAP).
7.  **Масштабирование:** При >100 Constraints/Политик используйте match-правила для фильтрации, CEL-first для базовых проверок и выделенные ресурсы для контроллеров.

### Источники

- [Open Policy Agent Gatekeeper](https://open-policy-agent.github.io/gatekeeper/)
- [Kyverno Documentation](https://kyverno.io/docs/)
- [Kubernetes ValidatingAdmissionPolicy](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/)
- [CEL Language Definition](https://kubernetes.io/docs/reference/using-api/cel/)
- [Gatekeeper Library](https://github.com/open-policy-agent/gatekeeper-library)

### Связанные темы

- **[Общий обзор RBAC](./rbac_overview.md)**
- **[Определение ролей (Role и ClusterRole)](./roles.md)**
- **[Основные концепции Kyverno](../kyverno/concepts.md)**
- **[Pod Security Context](../pod_security_context.md)**
