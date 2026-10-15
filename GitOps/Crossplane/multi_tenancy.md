# Crossplane: Мультитенантность и изоляция

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); Kubernetes 1.28–1.32+; On-Premise / Bare-Metal

---

## Определения

**Мультитенантность в Crossplane** — архитектурная модель совместного использования одного управляющего контура (Control Plane на базе Kubernetes) несколькими независимыми продуктовыми командами (тенантами) с гарантированной изоляцией их ресурсов, секретов, прав доступа и лимитов потребления.

**Soft Multi-Tenancy (мягкая мультитенантность)** — изоляция команд внутри одного общего Kubernetes-кластера с использованием пространств имён (`Namespaces`), ролевой модели (`RBAC`), сетевых политик (`NetworkPolicy`), квот (`ResourceQuota`) и валидаторов (`ValidatingAdmissionPolicy`). Применительно к Crossplane: команды взаимодействуют исключительно с локализованными ресурсами запросов (`Claims`), не имея прямого доступа к определениям инфраструктуры (`XRD`, `Composition`) и глобальным учётным записям (`ProviderConfig`).

**Hard Multi-Tenancy (жёсткая мультитенантность)** — изоляция команд на уровне раздельных плоскостей управления (Control Planes), например с использованием виртуальных кластеров (**vcluster** / Kube-in-Kube) или выделенных инсталляций Crossplane на команду. Исключает атаки через разделяемый API-сервер, общие etcd и коллизии глобальных `CustomResourceDefinitions` (CRD).

**Crossplane RBAC Manager** — встроенный контроллер (`crossplane-rbac-manager`), автоматически генерирующий и обновляющий роли Kubernetes (`ClusterRole`/`Role`) для каждого зарегистрированного CRD (MR, XRD, Claims) и связывающий их с правами пользователей и сервисных аккаунтов через механизм агрегации ролей (`crossplane:aggregate-to-admin`, `crossplane:aggregate-to-edit`, `crossplane:aggregate-to-view`).

**Composite Resource Claim (Claim / XRC)** — пространство-зависимый (`Namespace-scoped`) пользовательский манифест заказа инфраструктуры. Выступает единственной точкой входа для прикладных команд в парадигме Self-Service.

**Composite Resource (XR)** — экземпляр композитного ресурса. В Crossplane v1.x был строго `Cluster-scoped`. В архитектуре Crossplane v2.x поддерживаются **Namespaced XR**, что позволяет удерживать жизненный цикл и права XR внутри пространства имён тенанта.

**Namespace-scoped Managed Resources (MR)** — управляемые ресурсы нового поколения (например, API-группа `kubernetes.m.crossplane.io` в `provider-kubernetes` v1.x+ под Crossplane v2), создаваемые внутри пространства имён тенанта с привязкой к общему `ClusterProviderConfig` или локальному `ProviderConfig`.

**OOO (Only One Of / Owner Only Orphan — статус концепта)** — историческое проектное обозначение шаблонов мультитенантной изоляции:
1. *Only One Of (Singleton)* — ограничение, запрещающее создание более одного ресурса определённого типа на пространство имён тенанта. В актуальном production-стеке Crossplane реализуется через соглашения об именовании (`metadata.name: default`) либо через нативные политики `ValidatingAdmissionPolicy` (CEL).
2. *Owner Only Orphan* — защита дочерних/зависимых ресурсов от непреднамеренного каскадного удаления при удалении родительского XR. Реализуется через политику `deletionPolicy: Orphan` на Managed Resources и механизм `Usage` (`protection.crossplane.io/v1beta1`).

---

## Базовые концепции и архитектура

### Модели изоляции: Soft Multi-Tenancy vs Hard Multi-Tenancy

В инфраструктурах On-Premise и Bare-Metal выбор между мягкой и жёсткой изоляцией определяется требованиями информационной безопасности, сложностью эксплуатации и нагрузкой на Kubernetes API.

```
                    ┌────────────────────────────────────────────────────────┐
                    │               Kubernetes Control Plane                 │
                    ├────────────────────────────────────────────────────────┤
                    │  Platform Team (SRE):                                  │
                    │  - XRD (Схемы API)                                     │
                    │  - Compositions (Шаблоны)                              │
                    │  - ClusterProviderConfig / Root Secrets                │
                    │  - EnvironmentConfig (Параметры ДЦ)                    │
                    └───────────────┬────────────────────────┬───────────────┘
                                    │                        │
                    ┌───────────────▼────────┐      ┌────────▼───────────────┐
                    │ Namespace: team-alpha  │      │ Namespace: team-beta   │
                    ├────────────────────────┤      ├────────────────────────┤
                    │ - Claim (Postgresql)   │      │ - Claim (Postgresql)   │
                    │ - Secret (Connection)  │      │ - Secret (Connection)  │
                    │ - ResourceQuota        │      │ - ResourceQuota        │
                    │ - NetworkPolicy        │      │ - NetworkPolicy        │
                    └────────────────────────┘      └────────────────────────┘
```

| Параметр | Soft Multi-Tenancy (Namespaces + RBAC) | Hard Multi-Tenancy (vcluster / Multi-CP) |
| --- | --- | --- |
| **Граница изоляции** | Kubernetes Namespace, RBAC, Admission Webhooks | Отдельный API Server + etcd (vcluster под) |
| **Уровень доверия** | Внутренние команды одной организации | Враждебные среды, разные клиенты/юридические лица |
| **Конфликты CRD** | Возможны: все XRD и CRD разделяются глобально | Исключены: каждый vcluster имеет собственный набор CRD |
| **Лимиты API & etcd** | Общие: «шумный сосед» может перегрузить API-сервер | Раздельные: локальные запросы не нагружают Host API |
| **Накладные расходы** | Минимальные (один кластер, одни контроллеры) | Умеренные (дополнительный под API/etcd на тенанта) |
| **Сложность SRE** | Средняя: строгий аудит RBAC и CEL-политик | Повышенная: синхронизация ресурсов между host и vcluster |

### Границы ответственности: Control Plane vs Tenant Namespaces

Главный принцип безопасности мультитенантного Crossplane — **четкое разделение привилегий**:

1. **Контур платформы (Platform Engineering / SRE):**
   - Управляет пространством имён `crossplane-system`.
   - Публикует определения API (`CompositeResourceDefinition`), логику композиции (`Composition`, `Function`), профили окружений (`EnvironmentConfig`).
   - Регистрирует пакеты провайдеров (`Provider`) и глобальные учётные записи доступа к физической инфраструктуре (`ClusterProviderConfig`, корневые `Secret`).
   - Настраивает лимиты потребления и политики безопасности (`ValidatingAdmissionPolicy`, `Kyverno`).

2. **Контур тенанта (Прикладные команды разработчиков):**
   - Ограничен выделенным пространством имён (например, `team-billing`, `team-analytics`).
   - Не имеет доступа на чтение или запись к `crossplane-system`, секретам инфраструктуры и объектам `Composition`.
   - Создаёт только высокоуровневые запросы (`Claims`), например `PostgreSQLInstance`, `RedisCluster`, `KafkaTopic`.
   - Получает сгенерированные креденшелы подключения исключительно в виде локального `Secret` в своём пространстве имён (`spec.writeConnectionSecretToRef`).

### Архитектура Crossplane RBAC Manager и агрегация прав

По умолчанию Crossplane разворачивает компонент `crossplane-rbac-manager`. Его работа строится на автоматической агрегации ролей Kubernetes:

- Для каждого зарегистрированного `XRD` RBAC Manager создает набор `ClusterRole`:
  - `crossplane:admin:<plural>.<group>` (полный доступ)
  - `crossplane:edit:<plural>.<group>` (создание, изменение, удаление)
  - `crossplane:view:<plural>.<group>` (только чтение)
- Если в XRD указан блок `claimNames`, создаются роли для соответствующего Claim с лейблами агрегации:
  ```yaml
  labels:
    rbac.crossplane.io/aggregate-to-admin: "true"
    rbac.crossplane.io/aggregate-to-edit: "true"
    rbac.crossplane.io/aggregate-to-view: "true"
  ```
- Стандартные роли Kubernetes (`admin`, `edit`, `view`) автоматически наследуют эти правила. Таким образом, разработчик, обладающий ролью `edit` в пространстве имён `team-billing`, автоматически получает право создавать объявленные Claim без ручного вмешательства администратора.
- **Риск для SRE:** Если прикладная команда получает права `admin` в своём namespace, по умолчанию агрегация может открыть ей доступ к управлению внутренними объектами провайдеров. В мультитенантной среде рекомендуется либо отключать агрегацию для чувствительных CRD, либо использовать выделенные роли с минимальными привилегиями.

### Безопасность Connection Secrets и предотвращение Cross-Namespace Hijacking

При создании Claim пользователь указывает, куда записать реквизиты доступа к созданному сервису:
```yaml
spec:
  writeConnectionSecretToRef:
    name: db-connection
    namespace: team-billing # Потенциальная точка атаки!
```

**Угроза Cross-Namespace Hijacking:** Если злоумышленник в `team-billing` укажет в поле `namespace` значение `kube-system` или чужой namespace `team-finance`, контроллер Crossplane (работающий с высокими привилегиями) попытается создать или перезаписать секрет в чужом пространстве имён.
**Защита:**
1. Начиная с Crossplane v1.11+, валидационный вебхук блокирует запись секрета в пространство имён, отличное от пространства имён Claim (поле `namespace` в `writeConnectionSecretToRef` игнорируется или должно строго совпадать).
2. На уровне кластера обязательна валидация через `ValidatingAdmissionPolicy` (Kubernetes 1.30+), гарантирующая невозможность подмены целевого пространства имён.

### Жизненный цикл ресурсов, паттерн Singleton и защита от каскадного удаления

1. **Паттерн Singleton (Only One Of):**
   - В ряде архитектур тенанту разрешено иметь строго один экземпляр инфраструктурного ресурса на проект (например, одна выделенная база данных, одна балансировочная группа, один пул очередей сообщений).
   - Поскольку в CRD Kubernetes нет нативного флага `singleton: true`, шаблон реализуется фиксацией имени (`metadata.name: default`) в схеме валидации либо предикатом `ValidatingAdmissionPolicy`, проверяющим отсутствие других объектов этого Kind в текущем namespace.

2. **Защита от каскадного разрушения (Owner Only Orphan / Usages):**
   - По умолчанию удаление Claim приводит к каскадному удалению XR и всех сгенерированных Managed Resources (MR), что чревато безвозвратной потерей данных в On-Premise хранилищах (Ceph, локальные СУБД).
   - Для предотвращения катастрофы в мультитенантной среде применяются:
     - `spec.deletionPolicy: Orphan` на уровне композиции для критичных баз данных и хранилищ.
     - Механизм `Usage` (`protection.crossplane.io/v1beta1`) — блокирует удаление ресурса, пока существует зависимый объект (см. [Защита зависимостей (Usage)](GitOps/Crossplane/usage_protection.md)).
     - `defaultCompositeDeletePolicy: Foreground` в XRD — гарантирует, что удаление Claim будет заблокировано до тех пор, пока не завершатся все проверки зависимостей.

---

## Практические сценарии и конфигурация

### 1. Per-namespace изоляция тенанта и гранулярный RBAC для Claims

Платформенная команда регистрирует определение композитного ресурса СУБД PostgreSQL на локальном оборудовании:

```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: xpostgresqlinstances.storage.corp.internal
spec:
  group: storage.corp.internal
  names:
    kind: XPostgreSQLInstance
    plural: xpostgresqlinstances
  claimNames:
    kind: PostgreSQLInstance
    plural: postgresqlinstances
  defaultCompositeDeletePolicy: Foreground
  versions:
    - name: v1alpha1
      served: true
      referenceable: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              required: ["parameters"]
              properties:
                parameters:
                  type: object
                  required: ["storageGb", "databaseName"]
                  properties:
                    databaseName:
                      type: string
                    storageGb:
                      type: integer
                      minimum: 5
                      maximum: 500
```

Создание пространства имён тенанта и привязка строго ограниченной роли (разработчики могут только заказывать СУБД и читать свой секрет):

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: tenant-billing
  labels:
    corp.internal/tenant: billing
    corp.internal/tier: app-workload
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: billing-developer
  namespace: tenant-billing
rules:
  # Право управлять Claim СУБД
  - apiGroups: ["storage.corp.internal"]
    resources: ["postgresqlinstances"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  # Право читать статус своего Claim
  - apiGroups: ["storage.corp.internal"]
    resources: ["postgresqlinstances/status"]
    verbs: ["get"]
  # Право читать только сгенерированный Connection Secret
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: billing-developer-binding
  namespace: tenant-billing
subjects:
  - kind: Group
    name: "oidc:team-billing-devs"
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: billing-developer
  apiGroup: rbac.authorization.k8s.io
```

Манифест заказа инфраструктуры разработчиком команды `tenant-billing`:

```yaml
apiVersion: storage.corp.internal/v1alpha1
kind: PostgreSQLInstance
metadata:
  name: billing-db
  namespace: tenant-billing
spec:
  parameters:
    databaseName: billing_ledger
    storageGb: 50
  writeConnectionSecretToRef:
    name: billing-db-credentials
```

### 2. Защита от Cross-Namespace Secret Hijacking через ValidatingAdmissionPolicy

Нативная политика Kubernetes 1.30+ с движком CEL, полностью исключающая попытку тенанта записать секрет подключения в чужое пространство имён:

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: enforce-tenant-secret-namespace
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: ["storage.corp.internal"]
        apiVersions: ["v1alpha1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["postgresqlinstances"]
  validations:
    - expression: >-
        !has(object.spec.writeConnectionSecretToRef.namespace) ||
        object.spec.writeConnectionSecretToRef.namespace == request.namespace
      message: "Безопасность мультитенантности: запрещено указывать чужой namespace в writeConnectionSecretToRef!"
      reason: Forbidden
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: enforce-tenant-secret-namespace-binding
spec:
  policyName: enforce-tenant-secret-namespace
  validationActions: [Deny]
  matchResources:
    namespaceSelector:
      matchLabels:
        corp.internal/tier: app-workload
```

### 3. Паттерн Singleton (один Claim на namespace) через ValidatingAdmissionPolicy

Гарантия того, что команда может заказать только одну основную СУБД в рамках своего пространства имён:

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: singleton-postgres-per-namespace
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: ["storage.corp.internal"]
        apiVersions: ["v1alpha1"]
        operations: ["CREATE"]
        resources: ["postgresqlinstances"]
  validations:
    # Запрещает создание ресурса с любым именем, отличным от "default-db"
    - expression: "object.metadata.name == 'default-db'"
      message: "Паттерн Singleton: разрешён ровно один экземпляр СУБД с фиксированным именем 'default-db'!"
      reason: Invalid
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: singleton-postgres-binding
spec:
  policyName: singleton-postgres-per-namespace
  validationActions: [Deny]
  matchResources:
    namespaceSelector:
      matchLabels:
        corp.internal/tier: app-workload
```

### 4. Namespace-scoped MR и разделение ProviderConfig (на примере provider-kubernetes)

В Crossplane v2 провайдеры поддерживают пространства имён для управляемых ресурсов (`kubernetes.m.crossplane.io`). Это даёт возможность делегировать тенанту управление объектами Kubernetes через GitOps без предоставления глобального `cluster-admin`.

Глобальный профиль подключения, настроенный SRE:

```yaml
apiVersion: kubernetes.m.crossplane.io/v1alpha1
kind: ClusterProviderConfig
metadata:
  name: onprem-cluster-workloads
spec:
  credentials:
    source: InjectedIdentity # Использует токен ServiceAccount провайдера с ограниченными правами
```

Тенант разворачивает нативный объект внутри своего пространства имён:

```yaml
apiVersion: kubernetes.m.crossplane.io/v1beta1
kind: Object
metadata:
  name: billing-configmap
  namespace: tenant-billing
spec:
  providerConfigRef:
    name: onprem-cluster-workloads
    kind: ClusterProviderConfig
  forProvider:
    manifest:
      apiVersion: v1
      kind: ConfigMap
      metadata:
        name: billing-runtime-config
        namespace: tenant-billing
      data:
        LOG_LEVEL: "info"
        DB_POOL_SIZE: "20"
```

> [!IMPORTANT]
> Если прикладной команде разрешено создавать объекты `Object`, вебхук или ValidatingAdmissionPolicy обязаны блокировать вложенные манифесты с `kind: ClusterRoleBinding`, `kind: PrivilegedPod` или попытки создать ресурсы вне собственного `request.namespace`.

### 5. Сетевая изоляция (NetworkPolicy) и квотирование ресурсов Crossplane (ResourceQuota)

Защита управляющего контура Crossplane от компрометации со стороны подов тенантов и предотвращение DoS-атак на API-сервер:

```yaml
# Сетевая изоляция системного контура Crossplane
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: isolate-crossplane-system
  namespace: crossplane-system
spec:
  podSelector: {} # Применяется ко всем подам в crossplane-system
  policyTypes:
    - Ingress
  ingress:
    # Разрешаем доступ к Admission Webhook (порт 9443) только от Kube API Server
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - protocol: TCP
          port: 9443
    # Разрешаем сбор метрик только агентам Prometheus
    - from:
        - namespaceSelector:
            matchLabels:
              corp.internal/tier: monitoring
      ports:
        - protocol: TCP
          port: 8080
---
# Квотирование числа Claim для предотвращения перегрузки etcd и контроллеров
apiVersion: v1
kind: ResourceQuota
metadata:
  name: crossplane-claims-quota
  namespace: tenant-billing
spec:
  hard:
    count/postgresqlinstances.storage.corp.internal: "3"
    count/secrets: "50"
    requests.cpu: "16"
    requests.memory: "32Gi"
```

---

## Операционные команды и валидация

### Проверка сгенерированных ролей RBAC Manager

```bash
# Просмотр автоматически созданных ClusterRole для композитных ресурсов
kubectl get clusterroles -l rbac.crossplane.io/aggregate-to-edit=true
```
```
# → NAME                                              AGE
# → crossplane:edit:postgresqlinstances.storage.corp.internal   14d
# → crossplane:edit:redisclusters.storage.corp.internal         14d
```

### Валидация прав тенанта через impersonation (kubectl auth can-i)

Инженер SRE проверяет права сервисного аккаунта или пользователя команды перед допуском к кластеру:

```bash
# 1. Проверка прав на создание Claim в своем namespace
kubectl auth can-i create postgresqlinstances.storage.corp.internal -n tenant-billing --as=billing-dev
```
```
# → yes
```

```bash
# 2. Проверка изоляции: запрет на доступ к кластерным определениям XRD
kubectl auth can-i get compositeresourcedefinitions --as=billing-dev
```
```
# → no
```

```bash
# 3. Проверка изоляции: запрет на чтение инфраструктурных ProviderConfig
kubectl auth can-i get providerconfigs --as=billing-dev
```
```
# → no
```

```bash
# 4. Проверка изоляции: запрет на создание Claim в чужом namespace
kubectl auth can-i create postgresqlinstances.storage.corp.internal -n tenant-analytics --as=billing-dev
```
```
# → no
```

### Аудит и отслеживание привязки Claims к неймспейсам

```bash
# Получение списка всех Claim во всех пространствах имён с их статусом
kubectl get postgresqlinstances -A -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,SYNCED:.status.conditions[?(@.type=="Synced")].status,READY:.status.conditions[?(@.type=="Ready")].status
```
```
# → NAMESPACE        NAME         SYNCED   READY
# → tenant-billing   billing-db   True     True
# → tenant-analytics analytics-db True     True
```

---

## Диагностика и устранение неисправностей

### 1. Ошибка Forbidden при записи Connection Secret в чужой namespace

- **Симптом:** Объект Claim зависает в статусе `Synced=False`. В событиях (`kubectl describe`) отображается:
  ```
  Warning  CannotPublishConnectionDetails  composite/xpostgres-xyz  cannot write connection secret to namespace kube-system: forbidden
  ```
- **Причина:** Тенант попытался нарушить границу мультитенантности и указал чужое пространство имён в поле `writeConnectionSecretToRef.namespace`. Сработала блокировка Admission Webhook или ValidatingAdmissionPolicy.
- **Решение:** Исправить манифест Claim тенанта, убрав поле `namespace` или установив его равным локальному неймспейсу:
  ```yaml
  spec:
    writeConnectionSecretToRef:
      name: valid-local-secret-name
  ```

### 2. Тенант не может создать Claim (отсутствуют агрегированные права)

- **Симптом:** Разработчик получает отказ:
  ```
  Error from server (Forbidden): postgresqlinstances.storage.corp.internal is forbidden: User "billing-dev" cannot create resource in API group "storage.corp.internal"
  ```
- **Причина:**
  1. В `CompositeResourceDefinition` не был указан блок `claimNames` (создан только cluster-scoped XR).
  2. Отключен `crossplane-rbac-manager` (`--enable-rbac-manager=false`), либо у пользователя привязана кастомная Role вместо стандартной `edit`/`admin`.
- **Диагностика:**
  ```bash
  # Проверить наличие claimNames в XRD
  kubectl get xrd xpostgresqlinstances.storage.corp.internal -o jsonpath='{.spec.claimNames.kind}'
  # → PostgreSQLInstance
  ```
- **Решение:** Если используется RBAC с минимальными привилегиями, явно выдать права на группу API и ресурс в Role тенанта (см. [Сценарий 1](#1-per-namespace-изоляция-тенанта-и-гранулярный-rbac-для-claims)).

### 3. Зависание удаления Claim из-за блокировок Usage или Foreground Deletion

- **Симптом:** Команда выполняет `kubectl delete postgresqlinstance billing-db -n tenant-billing`, но ресурс остаётся в статусе `Terminating` бесконечно.
- **Причина:**
  1. На ресурс наложена блокировка `Usage` (`protection.crossplane.io/v1beta1`) зависимым сервисом.
  2. Установлена политика `defaultCompositeDeletePolicy: Foreground`, а дочерний Managed Resource не может удалиться (например, висит Finalizer провайдера).
- **Диагностика:**
  ```bash
  # 1. Поиск активных блокировок Usage в namespace тенанта
  kubectl get usage -n tenant-billing
  # 2. Проверка событий блокировки
  kubectl describe usage -n tenant-billing
  ```
- **Решение:** Удалить или обновить ресурс, использующий данную СУБД, либо снять некорректно зависший finalizer после подтверждения безопасности операции SRE-инженером.

### 4. Истощение лимитов API-сервера и Rate Limiting контроллера Crossplane

- **Симптом:** Задержки создания ресурсов возрастают с секунд до десятков минут. В логах контроллера Crossplane:
  ```
  waited for 15.234s due to client-side throttling, not priority and fairness
  ```
- **Причина:** Проблема «шумного соседа» (Noisy Neighbor). Один из тенантов сгенерировал сотни Claim или циклически изменяет спецификацию, перегружая очереди реконсиляции и API-сервер.
- **Диагностика:**
  ```bash
  # Подсчет количества Claims по неймспейсам
  kubectl get postgresqlinstances -A --no-headers | awk '{print $1}' | sort | uniq -c | sort -nr
  ```
- **Решение:**
  1. Установить жесткий `ResourceQuota` на типы ресурсов Crossplane в каждом namespace тенанта.
  2. Настроить API Priority and Fairness (APF) в Kubernetes для изоляции запросов контроллеров от пользовательских потоков.
  3. Для высоконагруженных изолированных сред вынести тенанта в **vcluster**.

### 5. RBAC Manager затирает кастомные ClusterRole или не реагирует на XRD

- **Симптом:** Изменения в системных ClusterRole, внесенные вручную администратором безопасности, сбрасываются каждые несколько минут.
- **Причина:** `crossplane-rbac-manager` непрерывно reconciles роли с аннотациями и метками Crossplane, приводя их к декларативному состоянию XRD.
- **Решение:** Никогда не редактировать роли, управляемые RBAC Manager. Создавать собственные независимые `ClusterRole` / `Role` без системных меток `rbac.crossplane.io/*` и привязывать их через отдельные `RoleBinding`.

---

## Лучшие практики

1. **Принцип наименьших привилегий (Least Privilege):** Прикладные команды ни при каких обстоятельствах не должны иметь прав `cluster-admin`, доступа к пространству имён `crossplane-system`, секретам инфраструктурных провайдеров и глобальным манифестам `ProviderConfig` / `ClusterProviderConfig`.
2. **Изоляция секретов по умолчанию:** Обязательно активируйте `ValidatingAdmissionPolicy` для проверки `writeConnectionSecretToRef.namespace == request.namespace`. Включение этой политики исключает эскалацию привилегий и чтение чужих секретов.
3. **Обязательное квотирование пространств имён:** Всегда определяйте `ResourceQuota` не только для CPU/Memory, но и по счетчикам CRD (`count/<plural>.<group>`). Это предотвратит перегрузку API-сервера и исчерпание пулов ресурсов на bare-metal хостах.
4. **Сетевое экранирование контроллеров:** Закрывайте входящие подключения к портам вебхуков (`9443`) и метрик (`8080`) контроллеров Crossplane с помощью `NetworkPolicy`. Поды прикладных приложений не должны иметь сетевого доступа к управляющему контуру.
5. **Разделение Soft и Hard изоляции:**
   - Для внутренних команд разработчиков в рамках одной компании достаточна связка: **Namespaces + RBAC + Claims + ValidatingAdmissionPolicy**.
   - Для внешних клиентов, независимых подразделений с собственными требованиями к CRD или сред с повышенными требованиями безопасности разворачивайте **vcluster** (виртуальные кластеры).
6. **Защита данных от удаления (Orphan Deletion):** Для баз данных, персистентных томов Ceph и очередей сообщений всегда устанавливайте `spec.deletionPolicy: Orphan` на уровне композиции, дополняя защиту механизмом `Usage`. Удаление Claim разработчиком не должно приводить к уничтожению физических данных на On-Premise дисках.

---

## Дополнительная информация

Смежные материалы базы знаний:
- [Обзор Crossplane](GitOps/Crossplane/overview.md) — базовая архитектура, XRD, Compositions и функции.
- [Интеграция с GitOps](GitOps/Crossplane/gitops_integration.md) — доставка манифестов через Argo CD и Flux в мультитенантных средах.
- [Composition Functions](GitOps/Crossplane/composition_functions.md) — конвейеры генерации инфраструктуры и работа с `EnvironmentConfig`.
- [Защита зависимостей (Usage)](GitOps/Crossplane/usage_protection.md) — предотвращение случайного удаления зависимых ресурсов через `protection.crossplane.io/v1beta1`.
- [Политики и Governance (Kyverno / OPA)](GitOps/Crossplane/policy_governance.md) — декларативный аудит и валидация манифестов до применения.
- [Self-Service и Internal Developer Portal](GitOps/Crossplane/self_service.md) — организация каталога платформенных сервисов для команд.
- [Управление ресурсами Kubernetes (provider-kubernetes)](GitOps/Crossplane/provider_kubernetes_setup.md) — работа с `kubernetes.m.crossplane.io` и `ClusterProviderConfig`.
- [Резервное копирование и Disaster Recovery](GitOps/Crossplane/backup_dr.md) — защита etcd, состояний и восстановления после сбоев.
- [Argo CD: Мультитенантность и изоляция](GitOps/ArgoCD/argocd_multi_tenancy.md) — шаблоны изоляции на уровне AppProject и tenant namespaces.
- [NetworkPolicy: Изоляция тенантов](Kubernetes/Networking/Network/NetworkPolicy/multi_tenancy.md) — сетевая безопасность и разграничение трафика между пространствами имён.
