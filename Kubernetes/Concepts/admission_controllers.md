# Контроллеры допуска (Admission Controllers)

**Актуально для:** Kubernetes 1.30 – 1.33

## Определения

**Контроллер допуска (Admission Controller)** — это специализированный подключаемый модуль API-сервера Kubernetes, который перехватывает HTTP-запросы к кластеру после успешной аутентификации (Authentication) и авторизации (Authorization), но строго до сохранения объекта в распределенное хранилище `etcd`.

В отличие от RBAC, который проверяет права субъекта на *действие* над ресурсом (например, разрешено ли сервисному аккаунту выполнять `POST /api/v1/namespaces/default/pods`), контроллеры допуска выполняют «Content-aware» инспекцию — они валидируют и при необходимости модифицируют *содержимое* самого объекта (спецификацию пода, параметры монтирования томов, запросы ресурсов, контекст безопасности).

**Мутирующий контроллер (Mutating Admission Controller)** — перехватывает запрос и может изменять (мутировать) спецификацию объекта перед его дальнейшей обработкой. Применяется для подстановки значений по умолчанию (например, дефолтных лимитов ресурсов), внедрения вспомогательных контейнеров (sidecar injection для Service Mesh) или проставления обязательных системных меток.

**Валидирующий контроллер (Validating Admission Controller)** — проверяет финальное состояние объекта на соответствие установленным политикам без права внесения изменений. Контроллер выносит вердикт: разрешить операцию (`Allow`) или отклонить ее (`Deny`) с возвратом клиенту HTTP-статуса 403 Forbidden и поясняющего сообщения.

**Динамический контроль допуска (Dynamic Admission Webhook)** — механизм расширения, позволяющий API-серверу отправлять HTTP POST-запросы во внешние сервисы (Admission Webhooks) для выполнения кастомной логики валидации (`ValidatingWebhookConfiguration`) или мутации (`MutatingWebhookConfiguration`).

**AdmissionReview** — стандартная структура данных API `admission.k8s.io/v1`, используемая для сериализации запроса (`AdmissionRequest`) от API-сервера к вебхуку и получения ответа (`AdmissionResponse`) с решением, JSONPatch-мутациями, предупреждениями и аудиторскими аннотациями.

**ValidatingAdmissionPolicy (VAP)** — нативный декларативный механизм валидации ресурсов в ядре Kubernetes (статус GA начиная с версии v1.30), использующий встраиваемый язык выражений **CEL (Common Expression Language)**. Позволяет описывать политики валидации манифестами без развертывания и поддержки внешних вебхуков.

**MutatingAdmissionPolicy (MAP)** — нативный декларативный механизм мутации ресурсов на базе CEL (статус Alpha в v1.32–v1.33 под feature-gate `MutatingAdmissionPolicy`). Позволяет выполнять мутации объектов через RFC 6902 JSONPatch или ApplyConfiguration прямо внутри процесса API-сервера.

**CEL (Common Expression Language)** — строго типизированный, безопасный и неполный по Тьюрингу язык выражений, выполняемый внутри процесса `kube-apiserver`. Вычисление выражений занимает микросекунды и ограничено строгим лимитом вычислительной сложности (cost budget), что исключает блокировку или исчерпание ресурсов API-сервера.

**Политика отказа (FailurePolicy)** — директива в конфигурации вебхука или VAP (`Fail` или `Ignore`), определяющая поведение API-сервера при недоступности внешнего сервиса, истечении таймаута или внутренней ошибке вычисления правила.

---

## Основные концепции и архитектура

### Место в цепочке обработки запроса

Жизненный цикл любого запроса на изменение состояния кластера (`CREATE`, `UPDATE`, `DELETE`, `CONNECT`) в `kube-apiserver` строго детерминирован:

```text
ЗАПРОС КЛИЕНТА (kubectl / CI/CD / Controller)
     ↓
1. AUTHENTICATION (Аутентификация)
   Проверка x509-сертификата, Bearer-токена, OIDC или Webhook Token Authenticator.
     ↓
2. AUTHORIZATION (Авторизация)
   Проверка прав через Node, RBAC, Webhook Authorizer.
     ↓
3. MUTATING ADMISSION (Фаза мутации)
   ├── Встроенные мутирующие плагины (NamespaceLifecycle, LimitRanger, ServiceAccount)
   ├── MutatingAdmissionPolicy (CEL, v1alpha1)
   └── Внешние Mutating Webhooks (Sidecar injection, Vault Agent Injector)
   └── Повторный прогон при необходимости (Re-invocation loop)
     ↓
4. OBJECT SCHEMA VALIDATION (Валидация схемы схемы объекта)
   Проверка соответствия OpenAPI v3 схеме ресурса (типы полей, обязательные ключи).
     ↓
5. VALIDATING ADMISSION (Фаза валидации)
   ├── Встроенные валидирующие плагины (PodSecurity, NodeRestriction, ResourceQuota)
   ├── ValidatingAdmissionPolicy (CEL, in-process)
   └── Внешние Validating Webhooks (OPA Gatekeeper, Kyverno)
     ↓
6. СОХРАНЕНИЕ В etcd
   Сериализация объекта в Protocol Buffers и запись в транзакционный журнал etcd.
```

### Фазы обработки: детальный механизм

#### 1. Фаза мутации (Mutating phase)
*   Выполняются строго **последовательно**. Порядок вызова встроенных плагинов и вебхуков имеет значение: изменения, внесенные одним контроллером, передаются на вход следующему.
*   **Цикл повторного вызова (Re-invocation loop):** Если какой-либо мутирующий вебхук изменил спецификацию объекта, API-сервер запускает повторный цикл мутации для всех контроллеров, у которых задан параметр `reinvocationPolicy: IfNeeded`. Контроллеры с `reinvocationPolicy: Never` повторно не вызываются.
*   **Защита от зацикливания:** В ядре `kube-apiserver` зашит лимит повторных итераций (максимум 12 проходов). Если мутирующие контроллеры продолжают бесконечно менять поля друг за другом, API-сервер прерывает обработку и возвращает клиенту ошибку `500 Internal Server Error`.

#### 2. Валидация схемы (Schema Validation)
*   После завершения всех мутаций объект проверяется на структурную корректность.
*   Если мутирующий контроллер добавил поле недопустимого типа или нарушил CRD-схему, запрос отклоняется еще до перехода к валидирующим контроллерам допуска.

#### 3. Фаза валидации (Validating phase)
*   Выполняются **параллельно** для снижения общей задержки (latency) API-вызова.
*   Объект на этом этапе неизменяем (read-only).
*   Если хотя бы один валидирующий контроллер (встроенный плагин, VAP или внешний вебхук) отклоняет запрос, запрос немедленно прерывается с кодом 403 Forbidden, в `etcd` ничего не записывается.
*   Если контроллеры допуска формируют предупреждения (`warnings`), они упаковываются в HTTP-заголовки `Warning:` (RFC 7234) и передаются клиенту (`kubectl`), не блокируя выполнение операции.

### Задачи контроллеров допуска в инфраструктуре DevOps и SRE

1.  **Безопасность (Guardrails & Compliance):** Принудительный запрет запуска контейнеров от `root`, блокировка небезопасных capability (`CAP_SYS_ADMIN`), запрет небезопасных типов томов (`hostPath`), контроль сетевых параметров (`hostNetwork`, `hostPID`).
2.  **Стандартизация и управление метаданными:** Проверка обязательного наличия меток окружения (`env`, `team`, `app.kubernetes.io/name`), валидация соглашений по именованию пространств имен и сервисов.
3.  **Управление емкостью и стабильностью (SRE):** Принудительное выставление лимитов и запросов CPU/RAM (`LimitRanger`), ограничение суммарного потребления в неймспейсе (`ResourceQuota`), предотвращение деградации планировщика из-за аномальных подов.
4.  **Автоматизация инфраструктуры:** Автоматическое монтирование служебных томов, инъекция сетевых прокси Service Mesh, добавление системных аннотаций аудита.

---

## Архитектурное сравнение: Webhooks vs CEL (VAP/MAP)

| Критерий | Внешние вебхуки (Webhooks) | Встроенный CEL (VAP / MAP) |
| :--- | :--- | :--- |
| **Среда выполнения** | Внешний Pod / HTTP-сервис в кластере | Внутри процесса `kube-apiserver` |
| **Сетевые задержки (Latency)** | 10–150 мс на запрос (TCP, TLS, serialization) | Микросекунды (0.1–1 мс, in-memory) |
| **Отказоустойчивость** | Зависит от CNI, CoreDNS, доступности Pod'ов | Максимальная (работает пока жив apiserver) |
| **Риск блокировки кластера** | Высокий при сбое сети или падении вебхука | Исключен (изолированный sandbox с cost budget) |
| **Вычислительные возможности** | Тьюринг-полный язык, доступ к БД, внешним API | Строго ограниченный sandbox, нет I/O |
| **Инфраструктурные накладные расходы** | Генерация сертификатов, Deployment, Service, PDB | Отсутствуют (чистые манифесты Kubernetes) |
| **Рекомендуемая сфера** | Проверка подписей образов (Cosign), сложные интеграции | 90% стандартных проверок безопасности и стандартов |

---

## Встроенные контроллеры допуска

В исходный код `kube-apiserver` скомпилировано более 30 встроенных плагинов допуска. Список включенных по умолчанию плагинов строго выверен разработчиками ядра Kubernetes.

| Контроллер | Тип | Статус по умолчанию | Назначение |
| :--- | :--- | :--- | :--- |
| **`NamespaceLifecycle`** | Validating | Включен | Блокирует создание объектов в несуществующих или находящихся в статусе `Terminating` пространствах имен. Предотвращает удаление системных неймспейсов (`default`, `kube-system`, `kube-public`). |
| **`LimitRanger`** | Mutating / Validating | Включен | Перехватывает создание подов и автоматически подставляет дефолтные запросы/лимиты ресурсов из объекта `LimitRange`, а также проверяет соответствие заданным минимальным/максимальным границам. |
| **`ServiceAccount`** | Mutating / Validating | Включен | Автоматически назначает поду `ServiceAccount: default` (если не указан явно), проверяет существование указанного аккаунта и монтирует секрет с проекцией токена (`ProjectedVolume`). |
| **`NodeRestriction`** | Validating | Включен в kubeadm | Ограничивает полномочия `kubelet`: узел может изменять только свой собственный объект `Node` и связанные с ним объекты `Pod`. Защищает кластер от компрометации control-plane через захваченный рабочий узел. Подробнее: [Безопасность Kubelet](../Security/kubelet_security.md). |
| **`PodSecurity`** | Validating | Включен | Реализует стандарты безопасности подов (**Pod Security Standards — PSS**). Проверяет манифесты на уровни `privileged`, `baseline`, `restricted` на основе меток неймспейса. Заменяет удаленный в v1.25 `PodSecurityPolicy`. Подробнее: [Стандарты безопасности подов (PSA)](../Security/pod_security_context.md). |
| **`ResourceQuota`** | Validating | Включен | Проверяет текущее суммарное потребление ресурсов в неймспейсе и отклоняет создание объектов, если операция приведет к превышению квоты. |
| **`MutatingAdmissionWebhook`** | Mutating | Включен | Вызывает зарегистрированные внешние мутирующие вебхуки. |
| **`ValidatingAdmissionPolicy`** | Validating | Включен (v1.30+) | Выполняет нативные декларативные политики на языке CEL. |
| **`ValidatingAdmissionWebhook`** | Validating | Включен | Вызывает зарегистрированные внешние валидирующие вебхуки. |
| **`AlwaysPullImages`** | Mutating | Отключен | Принудительно заменяет `imagePullPolicy` всех контейнеров на `Always`. Предотвращает несанкционированное использование локально закешированных образов на узлах. |
| **`EventRateLimit`** | Validating | Отключен | Защищает `etcd` и `kube-apiserver` от атак типа «отказ в обслуживании» (DoS) путем ограничения скорости записи событий (`Events`) от клиентов или сбойных подов. |
| **`ImagePolicyWebhook`** | Validating | Отключен | Передает метаданные образа во внешнюю систему проверки (проверка уязвимостей или подписи) до его запуска на узлах. |

---

## Архитектура Dynamic Admission Webhooks

### Протокол AdmissionReview v1

API-сервер взаимодействует с вебхуками по протоколу HTTPS, отправляя JSON-документ `AdmissionReview`.

#### Пример запроса API-сервера к вебхуку (AdmissionRequest):
```json
{
  "apiVersion": "admission.k8s.io/v1",
  "kind": "AdmissionReview",
  "request": {
    "uid": "705ab4f5-6393-11e8-b7cc-42010a800002",
    "kind": {"group": "", "version": "v1", "kind": "Pod"},
    "resource": {"group": "", "version": "v1", "resource": "pods"},
    "namespace": "production",
    "operation": "CREATE",
    "userInfo": {
      "username": "developer@company.local",
      "groups": ["system:authenticated", "dev-team"]
    },
    "object": {
      "metadata": {"name": "frontend", "namespace": "production"},
      "spec": {
        "containers": [{"name": "nginx", "image": "nginx:latest"}]
      }
    },
    "oldObject": null,
    "dryRun": false
  }
}
```

#### Пример ответа валидирующего вебхука (AdmissionResponse с предупреждением):
```json
{
  "apiVersion": "admission.k8s.io/v1",
  "kind": "AdmissionReview",
  "response": {
    "uid": "705ab4f5-6393-11e8-b7cc-42010a800002",
    "allowed": true,
    "warnings": [
      "Использование тега latest не рекомендуется для production-окружения."
    ],
    "auditAnnotations": {
      "security.policy/inspection-engine": "custom-validator-v2"
    }
  }
}
```

#### Пример ответа мутирующего вебхука (RFC 6902 JSONPatch):
```json
{
  "apiVersion": "admission.k8s.io/v1",
  "kind": "AdmissionReview",
  "response": {
    "uid": "705ab4f5-6393-11e8-b7cc-42010a800002",
    "allowed": true,
    "patchType": "JSONPatch",
    "patch": "W3sib3AiOiAiYWRkIiwgInBhdGgiOiAiL21ldGFkYXRhL2xhYmVscy9pbmplY3RlZCIsICJ2YWx1ZSI6ICJ0cnVlIn1d"
  }
}
```
*Примечание: Поле `patch` содержит Base64-закодированный массив операций: `[{"op": "add", "path": "/metadata/labels/injected", "value": "true"}]`.*

### Сетевая топология на On-Premise и Bare-Metal

На физических серверах процесс `kube-apiserver` обычно функционирует в сетевом пространстве имен хоста (`hostNetwork: true`), тогда как сервис вебхука развернут внутри виртуальной сети подов (CNI overlay/underlay).

```text
[ Control Plane Node (hostNetwork) ]
  kube-apiserver (IP хоста: 192.168.1.10)
        │
        ▼ HTTPS запрос на ClusterIP вебхука (10.96.120.45:443)
┌─────────────────────────────────────────────────────────────┐
│ Сетевой стек ядра: iptables / IPVS / eBPF (kube-proxy/CNI)  │
└─────────────────────────────────────────────────────────────┘
        │
        ▼ Маршрутизация через оверлей (Calico, Cilium, Flannel)
[ Worker Node (Pod Network) ]
  Pod вебхука (IP пода: 10.244.2.85:8443)
```

**Критические риски системного администратора:**
1.  **Маршрутизация Host -> Pod:** Убедитесь, что сетевой плагин (CNI) настроен для маршрутизации трафика от хостовых процессов мастер-узлов в сеть подов. При использовании изоляции или файрволов трафик от API-сервера к портам вебхуков (часто 8443, 9443) должен быть явно разрешен.
2.  **Петля зависимости DNS:** API-сервер не использует CoreDNS кластера по умолчанию для резолва доменных имен сервисов. При использовании `clientConfig.service` API-сервер напрямую разрешает эндпоинты через внутренние кэши. Если используется `clientConfig.url`, URL должен резолвиться системным DNS хоста.

---

## Язык выражений CEL в ValidatingAdmissionPolicy

CEL исполняется в изолированной песочнице API-сервера без возможности выполнения системных вызовов, ввода-вывода или зацикливания.

### Доступные контекстные переменные

| Переменная | Тип | Описание |
| :--- | :--- | :--- |
| `object` | `Object` | Текущий входящий объект (для `CREATE` и `UPDATE`). В операциях `DELETE` равен `null`. |
| `oldObject` | `Object` | Предыдущая версия объекта (для `UPDATE` и `DELETE`). В операции `CREATE` равен `null`. |
| `request` | `AdmissionRequest` | Метаданные запроса: `userInfo`, `operation`, `namespace`, `name`, `dryRun`. |
| `params` | `Object` | Параметрический объект, переданный через `ValidatingAdmissionPolicyBinding` (ConfigMap или CRD). |
| `authorizer` | `Authorizer` | Интерфейс встроенной авторизации (доступен в v1.31+). Позволяет проверить права субъекта запроса в теле CEL. |

### Практические примеры CEL-выражений

```text
# 1. Проверка наличия меток и их непустого значения
has(object.metadata.labels) && 'environment' in object.metadata.labels && object.metadata.labels['environment'].size() > 0

# 2. Проверка всех контейнеров на обязательное наличие лимита памяти
object.spec.containers.all(c, has(c.resources) && has(c.resources.limits) && 'memory' in c.resources.limits)

# 3. Запрет использования конкретного тега образа
object.spec.containers.all(c, !c.image.endsWith(':latest'))

# 4. Сравнение единиц измерения ресурсов (Kubernetes Quantity)
quantity(object.spec.containers[0].resources.limits.cpu).compareTo(quantity('4')) <= 0

# 5. Проверка неизменяемости (Immutability) поля при операции UPDATE
request.operation == 'UPDATE' ? object.spec.clusterIP == oldObject.spec.clusterIP : true
```

---

## Практические сценарии настройки

### Сценарий 1: Управление плагинами допуска в kubeadm на Bare-Metal

В self-hosted кластерах конфигурация контроллеров допуска выполняется через файл статического пода `/etc/kubernetes/manifests/kube-apiserver.yaml` или декларативно через `kubeadm-config.yaml`.

```yaml
# kubeadm-config.yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
kubernetesVersion: "v1.32.0"
apiServer:
  extraArgs:
    # Включение специфических плагинов сверх дефолтного набора
    enable-admission-plugins: "NodeRestriction,AlwaysPullImages"
    # Отключение ненужного встроенного плагина
    disable-admission-plugins: ""
    # Путь к файлу тонкой настройки плагинов
    admission-control-config-file: "/etc/kubernetes/admission-control.yaml"
  extraVolumes:
  - name: admission-config
    hostPath: "/etc/kubernetes/admission-control.yaml"
    mountPath: "/etc/kubernetes/admission-control.yaml"
    readOnly: true
    pathType: File
```

Применение конфигурации на работающем мастере:
```bash
# Редактирование аргументов запущенного API-сервера
sudo vim /etc/kubernetes/manifests/kube-apiserver.yaml

# Kubelet автоматически перезапустит статический под API-сервера после сохранения файла
# Проверка успешного старта процесса:
sudo crictl ps --name kube-apiserver
# → CONTAINER ID   IMAGE          CREATED          STATE     NAME
# → 8e3c12a7d4b1   kube-apiserver  10 seconds ago   Running   kube-apiserver
```

### Сценарий 2: Развертывание ValidatingAdmissionPolicy (VAP) с параметризацией

Создадим политику, которая проверяет, что образы контейнеров скачиваются только из доверенного корпоративного реестра, список которых хранится в отдельном `ConfigMap`.

#### Шаг 1: Определение политики (ValidatingAdmissionPolicy)
```yaml
# policy-trusted-registry.yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: check-trusted-registry
spec:
  failurePolicy: Fail
  paramKind:
    apiVersion: v1
    kind: ConfigMap
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["pods"]
  validations:
  - expression: |
      object.spec.containers.all(c,
        params.data.allowedRegistries.split(',').exists(reg, c.image.startsWith(reg.trim()))
      )
    message: "Образ контейнера скачивается из недоверенного реестра. Допустимые реестры указаны в политике."
```

#### Шаг 2: Создание ConfigMap с параметрами реестров
```yaml
# params-registries.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: allowed-registries-config
  namespace: default
data:
  allowedRegistries: "registry.internal.company.com/,docker.io/library/"
```

#### Шаг 3: Связывание политики с ресурсами (Binding)
```yaml
# binding-trusted-registry.yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: check-trusted-registry-binding
spec:
  policyName: check-trusted-registry
  validationActions: [Deny, Warn]
  paramRef:
    name: allowed-registries-config
    namespace: default
    parameterNotFoundAction: Deny
  matchResources:
    namespaceSelector:
      matchExpressions:
      - key: kubernetes.io/metadata.name
        operator: NotIn
        values: ["kube-system", "kube-public", "kube-node-lease"]
```

#### Шаг 4: Применение и тестирование
```bash
# Применение манифестов
kubectl apply -f policy-trusted-registry.yaml
kubectl apply -f params-registries.yaml
kubectl apply -f binding-trusted-registry.yaml

# Тест: Попытка запуска пода с недоверенным реестром через dry-run
kubectl run malicious-test --image=quay.io/unknown/app:v1 --dry-run=server
# → Error from server (Forbidden): admission webhook "check-trusted-registry" denied the request:
#   Образ контейнера скачивается из недоверенного реестра. Допустимые реестры указаны в политике.

# Тест: Запуск пода с доверенным образом
kubectl run valid-test --image=registry.internal.company.com/apps/web:1.0 --dry-run=server
# → pod/valid-test created (server dry run)
```

### Сценарий 3: Настройка внешнего Validating Webhook с фильтрацией через matchConditions

Использование выражений `matchConditions` (CEL) внутри конфигурации вебхука позволяет API-серверу производить отсечение запросов локально, не генерируя холостой сетевой трафик к подам вебхука.

```yaml
# validating-webhook-optimized.yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: corporate-security-validator
webhooks:
- name: pod-security.company.local
  admissionReviewVersions: ["v1"]
  sideEffects: None
  timeoutSeconds: 3
  failurePolicy: Fail
  matchPolicy: Equivalent
  clientConfig:
    service:
      namespace: security-tools
      name: validator-svc
      path: "/validate"
      port: 8443
    caBundle: LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCg== # Base64 корневого CA
  rules:
  - apiGroups: [""]
    apiVersions: ["v1"]
    operations: ["CREATE", "UPDATE"]
    resources: ["pods"]
    scope: Namespaced
  # Исключение системных неймспейсов
  namespaceSelector:
    matchExpressions:
    - key: kubernetes.io/metadata.name
      operator: NotIn
      values: ["kube-system", "kube-node-lease", "security-tools"]
  # CEL-фильтрация на уровне kube-apiserver:
  matchConditions:
  # Пропускать служебные поды сборщиков метрик без вызова вебхука
  - name: exclude-prometheus-exporters
    expression: "!has(object.metadata.labels) || !('app.kubernetes.io/component' in object.metadata.labels && object.metadata.labels['app.kubernetes.io/component'] == 'exporter')"
  # Вызывать вебхук только если у пода есть тома типа hostPath
  - name: check-hostpath-presence
    expression: "has(object.spec.volumes) && object.spec.volumes.exists(v, has(v.hostPath))"
```

### Сценарий 4: Декларативная мутация через MutatingAdmissionPolicy (MAP)

Механизм доступен в версиях Kubernetes 1.32+ в качестве Alpha-функционала.

Включение в API-сервере:
```text
--feature-gates=MutatingAdmissionPolicy=true
--runtime-config=admissionregistration.k8s.io/v1alpha1=true
```

Манифест политики мутации:
```yaml
# mutating-policy-labels.yaml
apiVersion: admissionregistration.k8s.io/v1alpha1
kind: MutatingAdmissionPolicy
metadata:
  name: inject-workload-labels
spec:
  failurePolicy: Fail
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
        {"op": "add", "path": "/metadata/labels/managed-by", "value": "gitops"},
        {"op": "add", "path": "/metadata/labels/audit-checked", "value": "true"}
      ]
```

---

## Эксплуатация, мониторинг и SRE

### Мониторинг метрик в Prometheus

API-сервер экспортирует детальные метрики задержек и ошибок контроля допуска по эндпоинту `/metrics`.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `apiserver_admission_webhook_admission_duration_seconds_bucket` | Histogram | Время ожидания ответа от внешних вебхуков (лейблы: `name`, `operation`, `type`, `rejected`). |
| `apiserver_admission_webhook_rejection_count_total` | Counter | Количество отклоненных запросов вебхуками (лейблы: `name`, `operation`, `error_type`). |
| `apiserver_admission_step_admission_duration_seconds_summary` | Summary | Задержка каждого встроенного шага фазы admission в микросекундах. |
| `apiserver_validating_admission_policy_check_duration_seconds_bucket` | Histogram | Время выполнения нативных CEL-выражений внутри процесса API-сервера. |

#### PromQL запросы для мониторинга:

```promql
# 99-й перцентиль задержки внешних вебхуков (должен быть < 50 мс)
histogram_quantile(0.99, sum(rate(apiserver_admission_webhook_admission_duration_seconds_bucket[5m])) by (le, name))

# Частота ошибок и таймаутов вебхуков (ошибки вызова внешнего сервиса)
sum(rate(apiserver_admission_webhook_rejection_count_total{error_type!="no_error"}[5m])) by (name, error_type)

# Доля отклоненных запросов политиками VAP
sum(rate(apiserver_validating_admission_policy_check_duration_seconds_count{validation_action="Deny"}[5m])) by (policy)
```

#### Правило алертинга (PrometheusRule):
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: admission-webhook-alerts
  namespace: monitoring
spec:
  groups:
  - name: admission-controllers.rules
    rules:
    - alert: AdmissionWebhookHighLatency
      expr: histogram_quantile(0.95, sum(rate(apiserver_admission_webhook_admission_duration_seconds_bucket[5m])) by (le, name)) > 1.0
      for: 2m
      labels:
        severity: warning
        tier: control-plane
      annotations:
        summary: "Вебхук допуска {{ $labels.name }} замедляет работу API-сервера"
        description: "95-й перцентиль задержки вебхука {{ $labels.name }} превышает 1 секунду. Это приводит к задержкам вызовов kubectl и деградации контроллеров."
    - alert: AdmissionWebhookFailureSpike
      expr: sum(rate(apiserver_admission_webhook_rejection_count_total{error_type!="no_error"}[2m])) by (name) > 5
      for: 1m
      labels:
        severity: critical
        tier: control-plane
      annotations:
        summary: "Сбой связи с Admission Webhook {{ $labels.name }}"
        description: "Вебхук недоступен или возвращает 5xx. При failurePolicy=Fail это полностью блокирует операции в кластере."
```

### Экстренное восстановление (Disaster Recovery & Break-Glass)

Если сбойный вебхук с `failurePolicy: Fail` упал и заблокировал создание ресурсов в кластере (включая собственное пересоздание или работу операторов):

#### Уровень 1: Штатное удаление через kubectl (если API доступен для типа конфигураций)
```bash
# Быстрый поиск и удаление проблемной конфигурации
kubectl get validatingwebhookconfigurations
kubectl get mutatingwebhookconfigurations

# Немедленное удаление конфигурации с таймаутом ожидания 0
kubectl delete validatingwebhookconfiguration corporate-security-validator --grace-period=0 --force
```

#### Уровень 2: Обход через флаги API-сервера на Control Plane (Break-Glass)
Если вебхук перехватывает изменения конфигураций вебхуков или удаление неймспейсов и не позволяет удалить себя:
1. Подключитесь по SSH на узел Control Plane:
   ```bash
   ssh root@cp-node-01.company.local
   ```
2. Отредактируйте манифест статического пода API-сервера:
   ```bash
   sudo vim /etc/kubernetes/manifests/kube-apiserver.yaml
   ```
3. В секцию `spec.containers.command` временно добавьте флаг:
   ```yaml
   - --disable-admission-plugins=MutatingAdmissionWebhook,ValidatingAdmissionWebhook
   ```
4. Сохраните файл. `kubelet` перезапустит `kube-apiserver` без поддержки внешних вебхуков.
5. Выполните удаление сломанной конфигурации вебхука локально:
   ```bash
   kubectl --kubeconfig /etc/kubernetes/admin.conf delete validatingwebhookconfiguration corporate-security-validator
   ```
6. Верните флаги в `/etc/kubernetes/manifests/kube-apiserver.yaml` в исходное состояние.

#### Уровень 3: Прямое удаление ключа из etcd (при полной недоступности apiserver)
```bash
# Подключение к локальному etcd на мастер-узле
ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  del /registry/validatingwebhookconfigurations/corporate-security-validator
# → 1 (успешно удален 1 ключ)
```

---

## Диагностика и устранение неисправностей (Troubleshooting)

### Сводная таблица типовых аварий

| Симптом | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| `Internal error occurred: failed calling webhook: Post "https://...": context deadline exceeded` | Сетевая изоляция между хостом master-узла и сетью подов CNI; зависание пода вебхука | `kubectl logs -n kube-system kube-apiserver-...`, пинг Pod IP вебхука с master-узла | Настроить маршруты CNI хост-под, проверить `NetworkPolicy`, увеличить `timeoutSeconds` (но не > 5c). |
| `x509: certificate signed by unknown authority` | Несоответствие между CA вебхука и полем `caBundle` в конфигурации вебхука | `kubectl get validatingwebhookconfigurations <name> -o jsonpath='{.webhooks[0].clientConfig.caBundle}' \| base64 -d \| openssl x509 -text -noout` | Обновить поле `caBundle` актуальным корневым сертификатом выпускающего центра (cert-manager CA). |
| Кластер заблокирован после рестарта (Deadlock): поды вебхука не могут запуститься | Вебхук проверяет создание собственных подов или подов CNI/CoreDNS при `failurePolicy: Fail` | `kubectl describe pod -n <webhook-ns> <webhook-pod>` показывает ошибку вызова вебхука | Добавить в `namespaceSelector` исключение системных неймспейсов и неймспейса вебхука; применить Break-Glass процедуру. |
| `mutation policy resulted in infinite loop` или HTTP 500 | Взаимный конфликт двух мутирующих вебхуков, циклически перезаписывающих поля друг друга | Логи `kube-apiserver` с уровнем `-v=4` по ключевому слову `re-invocation` | Установить на одном из вебхуков `reinvocationPolicy: Never` или согласовать алгоритмы мутации. |
| `CEL expression evaluation error: no such key` | Выражение в VAP обращается к необязательному полю объекта без предварительной проверки функцией `has()` | Проверить текст ошибки в ответе `kubectl apply --dry-run=server` | Исправить CEL: заменить `object.spec.securityContext.runAsUser` на `has(object.spec.securityContext) && has(object.spec.securityContext.runAsUser)`. |

### Пошаговый алгоритм расследования инцидентов

#### 1. Проверка состояния конфигураций вебхуков и VAP
```bash
# Получение списка всех вебхуков с подробностями
kubectl get mutatingwebhookconfigurations,validatingwebhookconfigurations -o wide

# Проверка нативных CEL политик и их биндингов
kubectl get validatingadmissionpolicies
kubectl get validatingadmissionpolicybindings -o wide
# → NAME                      POLICY                    VALIDATIONACTIONS   PARAMREF
# → check-trusted-registry-b   check-trusted-registry    [Deny,Warn]         allowed-registries-config
```

#### 2. Инспекция эндпоинтов сервиса вебхука
```bash
# Проверка доступности IP-адресов за сервисом вебхука
kubectl get endpoints -n security-tools validator-svc
# → NAME            ENDPOINTS                           AGE
# → validator-svc   10.244.1.45:8443,10.244.2.112:8443   12d
```
*Если список ENDPOINTS пуст — поды вебхука упали, находятся в CrashLoopBackOff или не прошли readiness-пробу.*

#### 3. Проверка логов пода вебхука
```bash
# Чтение логов с фильтрацией ошибок
kubectl logs -n security-tools -l app.kubernetes.io/name=validator --tail=100 -f
```

#### 4. Проверка сертификата TLS в конфигурации вебхука
```bash
# Сравнение отпечатка сертификата в секрете и в конфигурации
CERT_SECRET=$(kubectl get secret -n security-tools validator-tls -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -fingerprint -sha256)
CERT_WEBHOOK=$(kubectl get validatingwebhookconfigurations corporate-security-validator -o jsonpath='{.webhooks[0].clientConfig.caBundle}' | base64 -d | openssl x509 -noout -fingerprint -sha256)

echo "Secret:  $CERT_SECRET"
echo "Webhook: $CERT_WEBHOOK"
# Хеши должны совпадать. Если нет — обновите caBundle в конфигурации вебхука.
```

---

## Рекомендации (Best Practices)

1.  **Принцип «CEL-First»:** Для любых проверок валидации, которые могут быть описаны над метаданными или спецификацией объекта, используйте нативный `ValidatingAdmissionPolicy`. Это полностью исключает сетевой оверхед и риски недоступности внешних компонентов.
2.  **Защита от самоблокировки (Deadlock Prevention):**
    *   Всегда исключайте системные пространства имен (`kube-system`, `kube-node-lease`, `kube-public`) в блоке `namespaceSelector`.
    *   Всегда исключайте пространство имен, в котором запущен сам вебхук (например, `security-tools`, `kyverno`, `gatekeeper-system`).
3.  **Использование CEL-фильтрации через `matchConditions`:** Не направляйте в вебхук весь поток запросов кластера. Отсекайте нерелевантные ресурсы на стороне API-сервера до отправки HTTP-пакета.
4.  **Ограничение таймаута (`timeoutSeconds`):** По умолчанию таймаут вебхука составляет 10 секунд. Для высоконагруженных кластеров это критически много (приводит к исчерпанию пула потоков apiserver). Выставляйте `timeoutSeconds: 2` или `3`.
5.  **Высокая доступность вебхуков (HA):**
    *   Разворачивайте поды вебхука минимум в 3 репликах с распределением по узлам через `topologySpreadConstraints` или `podAntiAffinity`.
    *   Настраивайте `PodDisruptionBudget` (`minAvailable: 1` или `maxUnavailable: 1`).
    *   Задавайте гарантированные ресурсы (Guaranteed QoS: `limits` равны `requests`).
6.  **Поэтапный роллаут новых правил (Rollout Strategy):**
    *   Никогда не применяйте новые правила сразу в режиме `Deny` / `failurePolicy: Fail`.
    *   Этап 1: Развертывание с действием `Warn` или `Audit` (для VAP) либо временный `failurePolicy: Ignore` с мониторингом метрик отклонений.
    *   Этап 2: Анализ логов аудита за несколько дней для исключения ложных срабатываний (False Positives).
    *   Этап 3: Перевод политики в режим принудительного запрета (`Deny`).
7.  **Надежная автоматизация сертификатов:** Используйте `cert-manager` с механизмом инъекции CA (`cainjector`) для автоматического обновления поля `caBundle` в конфигурациях вебхуков до истечения срока действия TLS-сертификатов.

---

## Дополнительная информация

### См. также
* [Взаимодействие с API Kubernetes](./api_interaction.md)
* [Архитектура Control Plane в Kubernetes](./control_plane_architecture.md)
* [Стандарты безопасности подов (PSA)](../Security/pod_security_context.md)
* [Безопасность Kubelet](../Security/kubelet_security.md)
* [Ограничения RBAC, OPA Gatekeeper и Kyverno](../Security/rbac/limitations_opa.md)
* [Kyverno: Архитектура и политики](../Security/kyverno/concepts.md)
* [VPA Admission Controller](../Autoscaling/vpa_detailed.md)
* [Мониторинг kube-apiserver](../MonitoringLogging/kube_apiserver_monitoring.md)
