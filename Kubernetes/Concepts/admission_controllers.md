# Контроллеры допуска (Admission Controllers)

## Определения

**Контроллер допуска (Admission Controller)** — это специализированный компонент API-сервера Kubernetes, который перехватывает запросы к кластеру после успешной аутентификации и авторизации, но до того как объект будет сохранен в `etcd`.

В отличие от RBAC, который проверяет права на *действие* (может ли пользователь создавать поды?), Admission Controllers выполняют «Content-aware» контроль — они проверяют *содержимое* объекта (например, соответствует ли спецификация пода стандартам безопасности или заданы ли лимиты ресурсов).

**Мутирующий контроллер (Mutating Admission Controller)** — изменяет (мутирует) объект запроса до его валидации. Примеры: подстановка ресурсов по умолчанию, внедрение sidecar-контейнеров (Istio, Linkerd) или инъекция секретов.

**Валидирующий контроллер (Validating Admission Controller)** — проверяет запрос на соответствие политикам без права изменения объекта. Может разрешить или отклонить операцию.

**Admission Webhook (Вебхук допуска)** — механизм расширения, позволяющий API-серверу вызывать внешние HTTP-сервисы (Webhook) для реализации кастомной логики.

**ValidatingAdmissionPolicy (VAP)** — современная альтернатива вебхукам (GA в v1.30), позволяющая описывать правила валидации декларативно с использованием языка **CEL (Common Expression Language)** непосредственно в манифестах Kubernetes.

**MutatingAdmissionPolicy (MAP)** — механизм мутации ресурсов на базе CEL (beta в v1.33). Позволяет декларативно описывать правила изменения объектов без написания внешних вебхуков.

**CEL (Common Expression Language)** — язык выражений, разработанный Google для безопасной оценки выражений в изолированном режиме (sandbox). Используется в VAP, MAP и других компонентах Kubernetes. Поддерживает типизацию, работу со строками, списками, картами и встроенными функциями (regex, datetime, existence checks). Выполняется внутри процесса API-сервера за микросекунды, в отличие от сетевых вызовов внешних вебхуков.

---

## Основные концепции

### Место в цепочке обработки запроса

Полный жизненный цикл API-запроса в Kubernetes:

```text
ЗАПРОС КЛИЕНТА
     ↓
1. AUTHENTICATION (аутентификация) — проверка личности
     ↓
2. AUTHORIZATION (авторизация) — RBAC проверяет права
     ↓
3. MUTATING ADMISSION (мутирующий контроль допуска)
   ├── Встроенные контроллеры (LimitRanger, ServiceAccount, PSA)
   ├── ValidatingAdmissionPolicy / MutatingAdmissionPolicy (CEL)
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

### Фазы обработки

Процесс обработки запроса состоит из двух последовательных этапов:

1.  **Фаза мутации (Mutating phase):**
    *   Выполняются мутирующие контроллеры (встроенные и внешние вебхуки).
    *   Порядок выполнения имеет значение: изменения, внесенные одним контроллером, видны последующим.
    *   **Re-invocation Policy (Повторный вызов):** Если мутирующие вебхуки изменили объект, API-сервер запускает цикл мутации повторно (за исключением уже выполненных контроллеров с `reinvocationPolicy: Never`), чтобы гарантировать, что все контроллеры согласны с финальным состоянием.
2.  **Фаза валидации (Validating phase):**
    *   Выполняются валидирующие контроллеры (встроенные, VAP и внешние вебхуки).
    *   Запускаются параллельно для минимизации задержек (Latency).
    *   Объекты на этом этапе доступны только для чтения.

*Важно: Если любой из контроллеров на любой фазе отклоняет запрос, операция немедленно завершается с ошибкой 403 (Forbidden), и объект не сохраняется в кластере.*

### Зачем нужны Admission Controllers?

1.  **Безопасность:** Запрет запуска контейнеров от `root`, требование подписей образов, ограничение доступа к `hostPath` или `hostNetwork`.
2.  **Стандартизация и управление (Governance):** Принудительное добавление меток (labels), аннотаций или проверка наличия обязательных владельцев ресурсов.
3.  **Автоматизация:** Внедрение Sidecar-контейнеров, инъекция переменных окружения из Vault или настройка прокси.
4.  **Управление ресурсами:** Автоматическая коррекция лимитов и запросов (Requests/Limits) через **[VPA Admission Controller](../Autoscaling/vpa_detailed.md)** или принудительное исполнение `ResourceQuota`.

### Сравнение подходов: Webhooks vs CEL

| Критерий | Admission Webhooks | CEL (VAP/MAP) |
| :--- | :--- | :--- |
| **Задержка (Latency)** | 10-100мс (сетевой вызов) | Микросекунды (in-process) |
| **Зависимость** | Внешний сервис доступен | Встроен в API-сервер |
| **Риск блокировки кластера** | Высокий (при `failurePolicy: Fail`) | Минимальный |
| **Гибкость** | Любая логика, внешние вызовы | Ограничена возможностями CEL |
| **Состояние (State)** | Может хранить состояние | Stateless |
| **Область применения** | Сложные политики с внешними вызовами | Простые правила на основе объекта |

**Рекомендация:** Используйте CEL (VAP/MAP) как первый выбор для базовых политик. Webhooks — только для сценариев, требующих внешних вызовов (проверка подписей образов, обращение к внешним сервисам).

---

## Популярные встроенные контроллеры

| Контроллер | Тип | Назначение |
| :--- | :--- | :--- |
| **`NamespaceLifecycle`** | Validating | Запрещает создание ресурсов в удаляемых или несуществующих неймспейсах. |
| **`LimitRanger`** | Mutating/Validating | Применяет ограничения ресурсов, заданные в `LimitRange` (подстановка `default` значений). |
| **`ResourceQuota`** | Validating | Проверяет, не превышает ли новый ресурс квоты, заданные для неймспейса. |
| **`ServiceAccount`** | Mutating | Автоматически внедряет `ServiceAccount` и монтирует токены доступа в поды. |
| **`AlwaysPullImages`** | Mutating | Принудительно устанавливает `imagePullPolicy: Always` (важно для безопасности). |
| **`PodSecurity`** | Validating | Реализует стандарты безопасности подов (**PSA**), заменяя устаревший PSP. |
| **`NodeRestriction`** | Validating | Ограничивает права `kubelet`, позволяя ему изменять только свои узлы и поды. Подробнее: [Безопасность Kubelet](../Security/kubelet_security.md). |
| **`MutatingAdmissionWebhook`** | Mutating | Обрабатывает внешние MutatingWebhookConfiguration. |
| **`ValidatingAdmissionWebhook`** | Validating | Обрабатывает внешние ValidatingWebhookConfiguration. |
| **`ValidatingAdmissionPolicy`** | Validating | Обрабатывает нативные VAP на базе CEL. |

---

## Язык CEL для Admission Controllers

### Основные концепции CEL

CEL — нетьюринг-полный язык, разработанный для безопасной оценки в средах с ограниченными ресурсами. В Kubernetes используется для декларативного описания правил валидации и мутации.

**Ключевые особенности:**
- Безопасность: нет возможности выполнения произвольного кода
- Производительность: оценка за микросекунды
- Типизация: статическая проверка типов
- Встроенные функции: работа со строками, списками, картами, регулярными выражениями

### Встроенные переменные CEL

| Переменная | Описание |
| :--- | :--- |
| `object` | Объект, создаваемый или обновляемый в запросе |
| `oldObject` | Существующий объект (для операций UPDATE) |
| `request` | Объект запроса, содержащий информацию о пользователе, операции и т.д. |
| `params` | Параметры, переданные из ValidatingAdmissionPolicyBinding |

### Основные функции CEL

```text
# Проверка существования поля
has(object.spec.containers)

# Итерация по списку
object.spec.containers.all(c, has(c.resources.limits))

# Регулярные выражения
object.metadata.name.matches('^[a-z]([a-z0-9-]*[a-z0-9])?$')

# Работа с количествами (quantity)
quantity(object.spec.containers[0].resources.limits.memory).compareTo(quantity('1Gi'))

# Условная логика
request.namespace.startsWith('prod-') ? has(object.metadata.labels) : true
```

### Часто используемые паттерны CEL

```yaml
# Проверка наличия обязательных полей
has(object.metadata.labels) && 'app' in object.metadata.labels

# Проверка всех контейнеров в поде
object.spec.containers.all(c, has(c.resources) && has(c.resources.limits))

# Проверка отсутствия привилегий
!has(object.spec.containers) || object.spec.containers.all(c,
  !has(c.securityContext) || !c.securityContext.privileged == true
)

# Проверка имени по регулярному выражению
object.metadata.name.matches('^[a-z]([a-z0-9-]*[a-z0-9])?$') &&
object.metadata.name.size() <= 63
```

---

## ValidatingAdmissionPolicy (VAP)

### Архитектура

VAP состоит из двух объектов:

1. **ValidatingAdmissionPolicy** — определяет CEL-выражения для валидации
2. **ValidatingAdmissionPolicyBinding** — связывает политику с конкретными ресурсами/неймспейсами

### Пример: Требование ресурсных лимитов

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: require-resource-limits
spec:
  failurePolicy: Fail  # Fail или Ignore
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["pods"]
  validations:
  - expression: "object.spec.containers.all(c, has(c.resources) && has(c.resources.limits))"
    message: "Все контейнеры должны иметь определенные resource limits"
    messageExpression: "'Контейнер ' + object.spec.containers[0].name + ' не имеет resource limits'"
```

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: require-resource-limits-binding
spec:
  policyName: require-resource-limits
  validationActions: ["Deny"]  # Deny, Warn или Audit
  matchResources:
    namespaceSelector:
      matchLabels:
        environment: production
```

### Пример: Запрет привилегированных контейнеров

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: block-privileged-containers
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["pods"]
  validations:
  - expression: |
      object.spec.containers.all(c,
        !has(c.securityContext) ||
        !has(c.securityContext.privileged) ||
        c.securityContext.privileged == false
      )
    message: "Привилегированные контейнеры запрещены"
  - expression: "!has(object.spec.hostNetwork) || object.spec.hostNetwork == false"
    message: "Доступ к host network запрещен"
  - expression: "!has(object.spec.hostPID) || object.spec.hostPID == false"
    message: "Доступ к host PID namespace запрещен"
```

### Пример: Управление метками для production

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: require-labels-in-production
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: ["apps"]
      apiVersions: ["v1"]
      operations: ["CREATE"]
      resources: ["deployments"]
  validations:
  - expression: |
      request.namespace.startsWith('prod-') ?
        has(object.metadata.labels) &&
        'owner' in object.metadata.labels &&
        'cost-center' in object.metadata.labels :
        true
    message: "Деплойменты в production неймспейсах должны иметь метки 'owner' и 'cost-center'"
```

### validationActions

| Действие | Описание |
| :--- | :--- |
| `Deny` | Запрос отклоняется, возвращается ошибка 403 |
| `Warn` | Запрос разрешается, но возвращается предупреждение клиенту |
| `Audit` | Запрос разрешается, нарушение записывается в Audit-лог |

**Рекомендация:** Начинайте с `Warn` или `Audit` для тестирования политик, затем переходите к `Deny`.

---

## MutatingAdmissionPolicy (MAP)

MAP (beta в Kubernetes 1.33) позволяет декларативно описывать правила мутации объектов с использованием CEL.

### Отличия от VAP

- **VAP** только проверяет и разрешает/отклоняет запросы
- **MAP** может изменять объекты перед сохранением в etcd

### Пример: Добавление меток по умолчанию

```yaml
apiVersion: admissionregistration.k8s.io/v1alpha1  # v1 в стабильной версии
kind: MutatingAdmissionPolicy
metadata:
  name: add-default-labels
spec:
  matchConstraints:
    resourceRules:
    - apiGroups: ["apps"]
      apiVersions: ["v1"]
      operations: ["CREATE"]
      resources: ["deployments"]
  mutations:
  - patchType: JSONPatch
    patch: |
      [
        {"op": "add", "path": "/metadata/labels/managed-by", "value": "platform"}
      ]
```

*Примечание: На момент написания MAP находится в beta. Синтаксис и API могут измениться в будущих версиях.*

---

## Расширение через Вебхуки (Dynamic Admission)

Kubernetes позволяет регистрировать собственные контроллеры через два типа ресурсов:
*   `MutatingWebhookConfiguration`
*   `ValidatingWebhookConfiguration`

### Ключевые параметры конфигурации

1.  **`failurePolicy` (Политика отказа):**
    *   `Fail` (по умолчанию): Если вебхук недоступен или вернул ошибку, запрос к API блокируется. Рекомендуется для критических проверок безопасности.
    *   `Ignore`: Если вебхук недоступен, запрос пропускается. Снижает риски блокировки кластера, но может нарушить комплаенс.
2.  **`matchConditions` (CEL-фильтры):**
    *   Позволяют выполнять предварительную фильтрацию запросов на стороне API-сервера с помощью CEL. Это исключает лишние сетевые вызовы к вебхуку (например, "вызывать вебхук только для подов, у которых нет метки `skip-scan`").
3.  **`sideEffects`:**
    *   Должен быть `None` или `NoneOnDryRun`. Указывает, есть ли у вебхука побочные эффекты вне API-сервера (например, запись в стороннюю БД).
4.  **`timeoutSeconds`:**
    *   Максимальное время ожидания ответа от вебхука (по умолчанию 10с). Слишком большие значения увеличивают Latency всего API.
5.  **`matchPolicy`:**
    *   `Exact`: Строгое соответствие версии API.
    *   `Equivalent`: Обрабатывает запросы разных версий одного и того же ресурса (например, `v1` и `v1beta1`).
6.  **`reinvocationPolicy`:**
    *   `Never`: Вебхук не вызывается повторно после мутации другими контроллерами.
    *   `IfNeeded`: Вебхук вызывается повторно, если объект был изменен другими мутирующими контроллерами.

### Пример MutatingWebhookConfiguration

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: MutatingWebhookConfiguration
metadata:
  name: sidecar-injection.example.com
webhooks:
- name: inject-sidecar.example.com
  admissionReviewVersions: ["v1", "v1beta1"]
  sideEffects: None
  failurePolicy: Fail
  timeoutSeconds: 5
  reinvocationPolicy: IfNeeded
  matchPolicy: Equivalent
  clientConfig:
    service:
      namespace: istio-system
      name: istiod
      path: "/inject"
      port: 443
    caBundle: <base64-encoded-ca-cert>
  rules:
  - apiGroups: [""]
    apiVersions: ["v1"]
    operations: ["CREATE"]
    resources: ["pods"]
    scope: Namespaced
  namespaceSelector:
    matchLabels:
      istio-injection: enabled
  objectSelector:
    matchExpressions:
    - key: sidecar.istio.io/inject
      operator: NotIn
      values: ["false"]
```

### Пример ValidatingWebhookConfiguration

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: validate-apps.example.com
webhooks:
- name: validate-deployments.example.com
  admissionReviewVersions: ["v1", "v1beta1"]
  sideEffects: None
  failurePolicy: Fail
  timeoutSeconds: 10
  matchPolicy: Equivalent
  clientConfig:
    service:
      namespace: validation-system
      name: validation-webhook
      path: "/validate/deployments"
      port: 443
    caBundle: <base64-encoded-ca-cert>
  rules:
  - apiGroups: ["apps"]
    apiVersions: ["v1"]
    operations: ["CREATE", "UPDATE"]
    resources: ["deployments"]
    scope: Namespaced
  namespaceSelector:
    matchLabels:
      environment: production
  matchConditions:
  - expression: "!object.metadata.labels.containsKey('skip-validation')"
    name: skip-validation-label-check
```

### Популярные движки политик
*   **[Kyverno](../../Security/kyverno/concepts.md)** — написание политик на нативном YAML. Поддерживает мутации, валидации и генерацию ресурсов.
*   **[OPA Gatekeeper](../../Security/rbac/limitations_opa.md)** — использование языка Rego. Позволяет создавать сложные политики, выходящие за рамки одного ресурса.

---

## DryRun и Audit Annotations

### DryRun для тестирования политик

Флаг `--dry-run=server` позволяет проверить манифест через Admission Controllers без фактического сохранения в etcd:

```bash
# Проверка манифеста через все admission-контроллеры
kubectl apply --dry-run=server -f deployment.yaml

# Проверка только валидации (без мутации)
kubectl create --dry-run=server -f pod.yaml -o yaml

# Пример вывода при нарушении политики
# Error: pods "test-pod" is forbidden: validation failed:
#   - require-resource-limits: Все контейнеры должны иметь определенные resource limits
```

### Audit Annotations

Admission Controllers могут добавлять аннотации к объектам для аудита:

```yaml
# Аннотации добавляются автоматически контроллерами
metadata:
  annotations:
    # Информация о том, какой контроллер мутировал объект
    admission.kubernetes.io/mutated-by: "limit-range-controller"
    # Информация о проверке
    admission.kubernetes.io/verified-by: "resource-quota-controller"
```

---

## Безопасность вебхуков

Поскольку Admission Webhook получает содержимое всех объектов (включая `Secret`), его защита критична:
1.  **HTTPS/TLS:** API-сервер взаимодействует с вебхуками только через HTTPS. CA-сертификат вебхука должен быть указан в `caBundle` конфигурации.
2.  **NetworkPolicies:** Ограничьте доступ к вебхуку — он должен принимать запросы только от IP-адресов API-сервера.
3.  **Аутентификация:** Используйте токены или сертификаты для проверки того, что запрос пришел именно от легитимного API-сервера.
4.  **Автоматическая ротация сертификатов:** Настройте cert-manager или аналогичный инструмент для автоматического обновления сертификатов вебхуков.
5.  **Ограничение scope:** Используйте `namespaceSelector` и `objectSelector` для минимизации количества перехватываемых запросов.

---

## Практические сценарии

### 1. Включение контроллеров

В управляемых кластерах (EKS, GKE) список контроллеров управляется провайдером. В `kubeadm` список настраивается через флаг API-сервера:

```bash
# Включение конкретных контроллеров
--enable-admission-plugins=NodeRestriction,NamespaceLifecycle,LimitRanger,...

# Просмотр включенных контроллеров
kube-apiserver --help | grep enable-admission-plugins

# Список доступных контроллеров (в конкретной версии)
kube-apiserver --help | grep -A 50 "admission-plugins"
```

### 2. Создание ValidatingAdmissionPolicy через kubectl

```bash
# Создание политики
kubectl apply -f policy.yaml

# Проверка статуса
kubectl get validatingadmissionpolicy
kubectl get validatingadmissionpolicybindings

# Просмотр деталей
kubectl describe validatingadmissionpolicy require-resource-limits
```

### 3. Тестирование политик

```bash
# Тест 1: Манифест, соответствующий политике
cat <<EOF | kubectl apply --dry-run=server -f -
apiVersion: v1
kind: Pod
metadata:
  name: test-pod-with-limits
spec:
  containers:
  - name: nginx
    image: nginx:latest
    resources:
      limits:
        memory: "128Mi"
        cpu: "500m"
      requests:
        memory: "64Mi"
        cpu: "250m"
EOF
# → Pod "test-pod-with-limits" created (dry run)

# Тест 2: Манифест, нарушающий политику
cat <<EOF | kubectl apply --dry-run=server -f -
apiVersion: v1
kind: Pod
metadata:
  name: test-pod-without-limits
spec:
  containers:
  - name: nginx
    image: nginx:latest
EOF
# → Error: pods "test-pod-without-limits" is forbidden:
#   require-resource-limits: Все контейнеры должны иметь определенные resource limits
```

### 4. Отладка вебхуков

Если создание ресурсов "зависает" или возвращает ошибки таймаута, проблема часто в недоступности Admission Webhook:

```bash
# Поиск конфигураций вебхуков
kubectl get mutatingwebhookconfigurations
kubectl get validatingwebhookconfigurations

# Просмотр конфигурации конкретного вебхука
kubectl get mutatingwebhookconfigurations istio-sidecar-injector -o yaml

# Проверка логов контроллера (например, Kyverno)
kubectl logs -n kyverno -l app.kubernetes.io/name=kyverno -f

# Проверка логов OPA Gatekeeper
kubectl logs -n gatekeeper-system -l control-plane=controller-manager -f

# Проверка доступности сервиса вебхука
kubectl get endpoints -n istio-system istiod

# Проверка сертификата
kubectl get secret -n istio-system istiod-admission -o jsonpath='{.data.ca-cert\.pem}' | base64 -d
```

### 5. Миграция с вебхуков на CEL (VAP)

Если у вас есть валидирующий вебхук, который можно заменить CEL-политикой:

```bash
# Шаг 1: Экспортируйте существующую логику вебхука
kubectl get validatingwebhookconfigurations old-webhook -o yaml > old-webhook.yaml

# Шаг 2: Создайте VAP на основе логики вебхука
cat <<EOF | kubectl apply -f -
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: migrated-policy
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["pods"]
  validations:
  - expression: "/* CEL-выражение, эквивалентное логике вебхука */"
    message: "Нарушение политики"
EOF

# Шаг 3: Переключите сначала на Warn, затем на Deny
kubectl patch validatingadmissionpolicy migrated-policy --type merge -p '
spec:
  validations:
  - expression: "/* ваше выражение */"
    message: "Нарушение политики"
'
# Обновите validationActions в Binding на Warn, затем Deny

# Шаг 4: Удалите старый вебхук после проверки
kubectl delete validatingwebhookconfigurations old-webhook
```

### 6. Тестирование вебхуков в staging перед production

```bash
# Разворачивание вебхука с failurePolicy: Ignore в staging
cat <<EOF | kubectl apply -f -
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: staging-webhook
webhooks:
- name: validate-staging.example.com
  failurePolicy: Ignore  # Безопасно для staging
  # ... остальная конфигурация
EOF

# После проверки — обновление на Fail для production
kubectl patch validatingwebhookconfigurations staging-webhook --type merge -p '
webhooks:
- name: validate-staging.example.com
  failurePolicy: Fail
'
```

---

## Дополнительная информация

### Риски и ограничения
*   **Производительность:** Каждый запрос к API-серверу должен пройти через все контроллеры. Медленные вебхуки увеличивают Latency управления кластером.
*   **Блокировка кластера:** Если критический вебхук (например, валидирующий все поды) недоступен и настроен с `failurePolicy: Fail`, создание любых подов в кластере будет остановлено.
*   **Циклическая зависимость:** Вебхук не должен зависеть от ресурсов, которые он же валидирует (например, вебхук, проверяющий ConfigMap, не должен загружать конфигурацию из ConfigMap).
*   **Версионирование:** При обновлении Kubernetes API может потребоваться обновление вебхуков для поддержки новых версий ресурсов.

### Troubleshooting: Частые ошибки

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `timeout` при создании подов | Вебхук недоступен | Проверьте логи контроллера, endpoints сервиса |
| `connection refused` | Сервис вебхука не запущен | `kubectl get pods -n <ns> -l app=<webhook>` |
| `certificate has expired` | Сертификат вебхука истек | Обновите сертификат через cert-manager |
| `no such service` | Сервис не найден | Проверьте имя/неймспейс сервиса в конфигурации |
| Запросы "зависают" | Медленный вебхук | Увеличьте `timeoutSeconds`, оптимизируйте логику |
| `field reference not supported` | Ошибка CEL-выражения | Проверьте синтаксис через `kubectl apply --dry-run=server` |

### Best Practices

1. **Начинайте с Warn/Audit:** Перед включением `Deny` протестируйте политику в режиме предупреждений.
2. **Используйте matchConditions:** Ограничьте область действия вебхуков с помощью CEL-фильтров.
3. **Мониторьте Latency:** Отслеживайте метрику `apiserver_admission_webhook_admission_duration_seconds_bucket`.
4. **Настройте timeoutSeconds:** Не используйте значения больше 10с без крайней необходимости.
5. **Автоматизируйте ротацию сертификатов:** Используйте cert-manager для вебхуков.
6. **Тестируйте в staging:** Разверните копию вебхука с `failurePolicy: Ignore` в staging-кластере.
7. **Используйте PolicyReport:** Для мониторинга нарушений политик (особенно с Kyverno).

### См. также
* [Взаимодействие с API Kubernetes](./api_interaction.md)
* [Стандарты безопасности подов (PSA)](../Security/pod_security_context.md)
* [Kyverno: Основные концепции](../../Security/kyverno/concepts.md)
* [VPA Admission Controller](../Autoscaling/vpa_detailed.md)
* [Ограничения RBAC и OPA/Kyverno](../../Security/rbac/limitations_opa.md)
