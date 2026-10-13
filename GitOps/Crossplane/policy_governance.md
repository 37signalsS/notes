# Crossplane: Политики и Governance (Kyverno, Gatekeeper, ValidatingAdmissionPolicy)

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); Kubernetes 1.30–1.35; Kyverno v1.19.x; Gatekeeper v3.23.x; On-Premise / Bare-Metal

---

## Определения

**Policy-as-Code (PaC) в Crossplane** — подход к декларативному определению, автоматизированному тестированию и принудительному исполнению правил безопасности, комплаенса и квот на всех этапах жизненного цикла инфраструктуры Crossplane: от статических манифестов в Git до рантайма Kubernetes API и цикла реконсиляции управляемых ресурсов (Managed Resources).

**Многоуровневое управление (Multi-Layer Governance)** — архитектурная модель эшелонированной защиты (Defense-in-Depth), распределяющая проверки политик по пяти изолированным уровням: CI/CD (Shift-Left), схема OpenAPI v3 в XRD, контроллеры допуска Kubernetes (ValidatingAdmissionPolicy, Kyverno, Gatekeeper), конвейер Composition Functions и рантайм-блокировки зависимостей (`Usage`).

**ValidatingAdmissionPolicy (VAP)** — встроенный в ядро Kubernetes (GA с версии 1.30) механизм бессерверной валидации ресурсов на базе Common Expression Language (CEL). Исполняется непосредственно внутри процесса `kube-apiserver` без совершения сетевых HTTP-вызовов к внешним вебхукам, устраняя сетевые задержки и риски сбоев контроллеров допуска.

**Kyverno** — Kubernetes-native движок политик, использующий декларативный YAML для валидации, мутации, генерации ресурсов и очистки данных. Поддерживает фоновое сканирование etcd с публикацией отчетов в формате `PolicyReport` CRD.

**OPA Gatekeeper** — агент безопасности для Kubernetes на базе Open Policy Agent (OPA), реализующий политики через связку `ConstraintTemplate` (логика на Rego или CEL со схемой OpenAPI v3) и `Constraint` (экземпляр политики с параметрами).

**Claim Guarding** — практика изоляции и валидации пользовательских заявок (`CompositeResourceClaim` / Claim), подаваемых прикладными командами в пространствах имён тенантов. Позволяет перехватывать и блокировать недопустимые параметры инфраструктуры до того, как движок Crossplane запустит композицию и начнет создание низкоуровневых ресурсов.

**MR Hardening (Защита Managed Resources)** — комплекс правил на уровне управляемых ресурсов (`Managed Resources`, MR), предотвращающий прямое создание примитивов в обход платформенных Claim, запрещающий небезопасные политики удаления (`spec.deletionPolicy: Delete` для критических баз данных) и блокирующий несанкционированное изменение управляющих меток.

**Webhook Deadlock («Замкнутый круг admission»)** — критическое состояние отказа инфраструктуры, возникающее, когда контроллер вебхука политик с конфигурацией `failurePolicy: Fail` становится недоступен, блокируя запросы API-сервера, включая служебные операции самого контроллера Crossplane, что приводит к полной остановке реконсиляции кластера.

**Mutation Drift Loop («Война мутаций»)** — бесконечный цикл расхождения состояния (Configuration Drift), при котором мутирующий вебхук (например, Kyverno `mutate`) изменяет поля генерируемого Crossplane ресурса после его создания, а reconciler Crossplane при следующем проходе пытается вернуть исходное состояние, вызывая непрерывную перегрузку `kube-apiserver` и etcd.

---

## Базовые концепции и архитектура

### Эшелонированная архитектура управления (Defense-in-Depth)

В отличие от классического Infrastructure as Code (Terraform, OpenTofu), где проверки выполняются преимущественно до развертывания (pre-apply), в архитектуре Crossplane управляющий контур функционирует непрерывно. Эффективная стратегия Governance требует распределения проверок по уровням:

```text
  [ РАЗРАБОТЧИК / GITOPS ]
             │
             ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ УРОВЕНЬ 0: Shift-Left (CI/CD Static Gate)                             │
  │ • crossplane beta render + crossplane beta validate schemas            │
  │ • gator test / kyverno test / kubeconform                              │
  └────────────────────────────────────┬───────────────────────────────────┘
                                       │ git commit & push
                                       ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ УРОВЕНЬ 1: Schema Enforcement (OpenAPI v3 + CEL в XRD)                 │
  │ • Валидация типов данных, диапазонов (min/max), regex-шаблонов         │
  │ • x-kubernetes-validations (иммутабельность полей, кросс-валидация)   │
  └────────────────────────────────────┬───────────────────────────────────┘
                                       │ kubectl apply (Claim)
                                       ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ УРОВЕНЬ 2: Admission Control для Claim (VAP / Kyverno / Gatekeeper)    │
  │ • Ограничение квот ресурсов (CPU/RAM/Storage) на тенанта               │
  │ • Проверка обязательных меток (team, environment, cost-center)         │
  │ • Изоляция writeConnectionSecretToRef внутри своего namespace          │
  └────────────────────────────────────┬───────────────────────────────────┘
                                       │ Crossplane Reconciler
                                       ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ УРОВЕНЬ 3: Composition Pipeline Functions (Shift-Right Control Plane)   │
  │ • function-cel / function-kcl: программная проверка графа ресурсов    │
  │ • Прерывание композиции с возвратом ошибки валидации в статус XR       │
  └────────────────────────────────────┬───────────────────────────────────┘
                                       │ Генерация Composed Resources
                                       ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ УРОВЕНЬ 4: MR Admission Guardrails (Защита Managed Resources)          │
  │ • Запрет прямого создания MR непривилегированными пользователями       │
  │ • Принудительное enforcement deletionPolicy: Orphan для stateful СУБД  │
  │ • Bypass для сервис-аккаунта Crossplane (защита от Webhook Deadlock)   │
  └────────────────────────────────────┬───────────────────────────────────┘
                                       │ Применение к инфраструктуре
                                       ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ УРОВЕНЬ 5: Runtime Protection & Continuous Audit                       │
  │ • protection.crossplane.io/v1beta1 (Usage / ClusterUsage)              │
  │ • Фоновый аудит etcd (PolicyReport) и мониторинг метрик Prometheus     │
  └────────────────────────────────────────────────────────────────────────┘
```

### Сравнение движков политик в контексте Crossplane

| Критерий | Kubernetes VAP (CEL) | Kyverno (v1.19.x) | OPA Gatekeeper (v3.23.x) | Composition Functions |
|---|---|---|---|---|
| **Точка исполнения** | Внутри `kube-apiserver` (In-Tree) | Внешний вебхук (Out-of-Tree) | Внешний вебхук (Out-of-Tree) | Внутри конвейера Crossplane |
| **Сетевая задержка** | 0 мс (нет сетевого хопа) | 5–50 мс (mTLS HTTP POST) | 5–50 мс (mTLS HTTP POST) | Локальный gRPC к поду функции |
| **Риск Webhook Deadlock** | Полностью отсутствует | Присутствует при `failurePolicy: Fail` | Присутствует при `failurePolicy: Fail` | Отсутствует для K8s API |
| **Язык выражений** | CEL | YAML-паттерны, JMESPath, CEL | Rego, CEL (с v3.14+) | CEL, KCL, Python, Go |
| **Мутация ресурсов** | Не поддерживается (только валидация) | Полноценная (`mutate`-правила) | Ограниченная (`Assign`, `ModifySet`) | Нативная генерация целевого графа |
| **Фоновый аудит etcd** | Нет (только admission) | Да (`PolicyReport` CRD) | Да (статус `Constraint`, метрики) | Нет |
| **Основная роль в Crossplane** | Защита от удаления, проверка Claim | Обязательные метки, defaults, аудит | Комплексные enterprise-ограничения | Валидация логики композиции |

### Специфика SRE: риски и шаблоны отказоустойчивости

#### 1. Исключение контроллеров Crossplane (Bypass Controller ServiceAccounts)
Если вебхук Kyverno или Gatekeeper перехватывает операции над `Managed Resources` со строгой политикой `failurePolicy: Fail`, любой перезапуск или деградация подов вебхука парализует реконсиляцию всей инфраструктуры.
- **Правило SRE:** Вебхуки admission **обязаны** исключать служебные сервисные аккаунты Crossplane (`system:serviceaccount:crossplane-system:*`) из проверок низкоуровневых ресурсов.
- **Точка применения:** Строгая проверка применяется к пользователям и пайплайнам при создании Claim, но контроллер Crossplane должен иметь беспрепятственный доступ к управлению порождаемыми им MR.

#### 2. Предотвращение войн мутаций (Drift Loops)
Если мутирующий вебхук изменяет спецификацию ресурса (например, подставляет `spec.forProvider.storage = "50Gi"` вместо `"20Gi"`), управляемого Crossplane, наступает состояние гонки:
1. Crossplane отправляет желаемое состояние A.
2. Webhook перехватывает запрос и мутирует его в B.
3. Объект сохраняется в etcd как B.
4. В следующем цикле реконсиляции Crossplane сравнивает B с желаемым состоянием A, обнаруживает дрейф и отправляет PATCH A.
5. Процесс повторяется бесконечно, генерируя тысячи запросов в секунду и забивая etcd.
- **Правило:** Никогда не применяйте мутирующие вебхуки к `Composite Resources` (XR) и `Managed Resources` (MR). Мутацию полей по умолчанию следует производить либо на этапе создания `Claim` (до начала композиции), либо детерминированно внутри конвейера Composition Functions (`function-patch-and-transform` или `function-kcl`).

#### 3. Предотвращение межтенантных утечек (Namespace Escape)
Пользовательские Claim создаются в пространстве имён тенанта, но генерируют секреты подключения через поле `spec.writeConnectionSecretToRef`.
- **Угроза:** Злоумышленник в пространстве имён `tenant-a` указывает `writeConnectionSecretToRef: { name: "db-secret", namespace: "tenant-b" }` или ссылается на общий `ProviderConfig` с повышенными привилегиями.
- **Защита:** Политика обязана гарантировать, что `writeConnectionSecretToRef.namespace` либо отсутствует (тогда секрет создаётся в namespace Claim), либо строго совпадает с `request.namespace`. Ссылка на `compositionRef` должна быть ограничена разрешенным списком.

---

## Практические сценарии

### Сценарий 1. Валидация Claim через Kubernetes ValidatingAdmissionPolicy (VAP + CEL)

В этом сценарии проверяется Claim для локального PostgreSQL (`PostgreSQLInstance`):
1. Ограничение выделяемых ресурсов: запрет запроса более 16 ядер CPU и 64 ГБ памяти на экземпляр.
2. Обязательные метки: наличие меток `team`, `environment` (допустимы только `dev`, `stage`, `prod`).
3. Защита изоляции секретов: запрет записи учетных данных в чужой namespace.

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: postgres-claim-guard
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: ["platform.onprem.io"]
        apiVersions: ["v1alpha1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["postgresqlinstances"]
  validations:
    # 1. Проверка обязательных меток
    - expression: "has(object.metadata.labels) && 'team' in object.metadata.labels"
      message: "Отсутствует обязательная метка metadata.labels.team"
      reason: Invalid

    - expression: >-
        has(object.metadata.labels) &&
        object.metadata.labels['environment'] in ['dev', 'stage', 'prod']
      message: "Метка metadata.labels.environment должна иметь значение 'dev', 'stage' или 'prod'"
      reason: Invalid

    # 2. Проверка лимитов инфраструктурных параметров
    - expression: "object.spec.parameters.cpuCores <= 16"
      message: "Количество cpuCores не может превышать 16 для On-Premise кластера"
      reason: Forbidden

    - expression: "object.spec.parameters.memoryGiB <= 64"
      message: "Объем memoryGiB не может превышать 64 для On-Premise кластера"
      reason: Forbidden

    # 3. Защита от межтенантной утечки секрета подключения
    - expression: >-
        !has(object.spec.writeConnectionSecretToRef.namespace) ||
        object.spec.writeConnectionSecretToRef.namespace == object.metadata.namespace
      message: "Запрещено указывать чужой namespace в writeConnectionSecretToRef"
      reason: Forbidden
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: postgres-claim-guard-binding
spec:
  policyName: postgres-claim-guard
  validationActions: [Deny]
  matchResources:
    namespaceSelector:
      matchExpressions:
        # Применяем политику ко всем пространствам имён, кроме системных
        - key: kubernetes.io/metadata.name
          operator: NotIn
          values: ["kube-system", "crossplane-system", "monitoring"]
```

---

### Сценарий 2. Защита от непреднамеренного удаления через VAP (Deletion Guarding)

Предотвращение случайного выполнения команды `kubectl delete` над базой данных или хранилищем. Удаление разрешается только в случае, если администратор предварительно снял аннотацию `platform.onprem.io/delete-protection: "true"`.

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: stateful-deletion-guard
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: ["platform.onprem.io"]
        apiVersions: ["*"]
        operations: ["DELETE"]
        resources: ["postgresqlinstances", "redisinstances"]
  validations:
    - expression: >-
        !has(oldObject.metadata.annotations) ||
        !('platform.onprem.io/delete-protection' in oldObject.metadata.annotations) ||
        oldObject.metadata.annotations['platform.onprem.io/delete-protection'] != 'true'
      message: "Удаление заблокировано: ресурс защищен от удаления. Установите аннотацию platform.onprem.io/delete-protection в 'false' перед удалением."
      reason: Forbidden
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: stateful-deletion-guard-binding
spec:
  policyName: stateful-deletion-guard
  validationActions: [Deny]
  matchResources:
    namespaceSelector:
      matchExpressions:
        - key: environment
          operator: In
          values: ["prod", "stage"]
```

Проверка защиты удаления:
```bash
# Попытка удалить защищенный ресурс
kubectl delete postgresqlinstance prod-payment-db -n billing
# → Error from server (Forbidden): admission webhook "stateful-deletion-guard.admissionregistration.k8s.io" denied the request: Удаление заблокировано: ресурс защищен от удаления. Установите аннотацию platform.onprem.io/delete-protection в 'false' перед удалением.

# Корректное снятие блокировки администратором перед регламентным выводом из эксплуатации
kubectl annotate postgresqlinstance prod-payment-db -n billing platform.onprem.io/delete-protection="false" --overwrite
# → postgresqlinstance.platform.onprem.io/prod-payment-db annotated

kubectl delete postgresqlinstance prod-payment-db -n billing
# → postgresqlinstance.platform.onprem.io "prod-payment-db" deleted
```

---

### Сценарий 3. Kyverno: принудительная изоляция и мутация defaults на Claim

Kyverno используется для задач, где требуется:
1. Автоматическая простановка безопасных значений по умолчанию (например, принудительный выбор безопасного класса хранения Ceph RBD).
2. Валидация с генерацией детальных отчетов `PolicyReport` в режиме аудита.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: crossplane-claim-enforcement
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    # 1. Мутация: автоматическая простановка дефолтного storageClass для On-Premise
    - name: set-default-storage-tier
      match:
        any:
          - resources:
              kinds: ["platform.onprem.io/v1alpha1/PostgreSQLInstance"]
      mutate:
        patchStrategicMerge:
          spec:
            parameters:
              +(storageClass): "ceph-nvme-replicated"

    # 2. Валидация: запрет небезопасных сетевых параметров
    - name: disallow-insecure-network-exposing
      match:
        any:
          - resources:
              kinds: ["platform.onprem.io/v1alpha1/PostgreSQLInstance"]
      validate:
        message: "Прямой внешний доступ (ingressAccess/nodePort) для базы данных запрещен корпоративной политикой."
        deny:
          conditions:
            any:
              - key: "{{ request.object.spec.parameters.exposeExternally || false }}"
                operator: Equals
                value: true

    # 3. Проверка: требование backupTier
    - name: require-backup-schedule
      match:
        any:
          - resources:
              kinds: ["platform.onprem.io/v1alpha1/PostgreSQLInstance"]
      validate:
        message: "Параметр spec.parameters.backupTier обязателен (gold, silver, bronze)."
        pattern:
          spec:
            parameters:
              backupTier: "gold | silver | bronze"
```

---

### Сценарий 4. OPA Gatekeeper: предотвращение прямого создания Managed Resources

Защита кластера от обхода абстракций: обычные инженеры и CI/CD пайплайны не должны напрямую создавать низкоуровневые объекты провайдеров (`provider-sql`, `provider-helm`, `provider-kubernetes`). Все манипуляции с инфраструктурой должны идти строго через Claim платформы.

#### 1. ConstraintTemplate (логика на Rego)
```yaml
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: crossplanerestrictrawmr
spec:
  crd:
    spec:
      names:
        kind: CrossplaneRestrictRawMR
      validation:
        openAPIV3Schema:
          type: object
          properties:
            exemptUsers:
              type: array
              items:
                type: string
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        package crossplanerestrictrawmr

        is_exempt {
          user := input.review.userInfo.username
          exempt_user := input.parameters.exemptUsers[_]
          user == exempt_user
        }

        # Разрешаем сервис-аккаунтам контроллера Crossplane
        is_exempt {
          startswith(input.review.userInfo.username, "system:serviceaccount:crossplane-system:")
        }

        violation[{"msg": msg}] {
          not is_exempt
          # Блокируем операцию создания для непривилегированных пользователей
          input.review.operation == "CREATE"
          msg := sprintf("Прямое создание Managed Resource '%v' запрещено. Заказывайте инфраструктуру через Claim (CompositeResourceClaim).", [input.review.object.kind])
        }
```

#### 2. Constraint (применение к группам ресурсов On-Premise провайдеров)
```yaml
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: CrossplaneRestrictRawMR
metadata:
  name: disallow-raw-database-creation
spec:
  enforcementAction: deny
  match:
    kinds:
      - apiGroups: ["postgresql.sql.crossplane.io"]
        kinds: ["Database", "Role", "Extension"]
      - apiGroups: ["helm.crossplane.io"]
        kinds: ["Release"]
  parameters:
    exemptUsers:
      - "system:admin"
```

---

### Сценарий 5. Валидация внутри конвейера Composition Functions (Shift-Right Control Plane)

Политики допуска (Admission) перехватывают запрос при обращении к API-серверу. Однако Crossplane Composition выполняет генерацию динамического графа ресурсов. Для валидации согласованности компонентов внутри самой композиции используется `function-cel`.

Пример шага валидации в `Composition`:
```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: postgres-onprem-production
  labels:
    provider: onprem
spec:
  compositeTypeRef:
    apiVersion: platform.onprem.io/v1alpha1
    kind: XPostgreSQLInstance
  mode: Pipeline
  pipeline:
    - step: patch-and-transform
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: postgres-cluster
            base:
              apiVersion: postgresql.sql.crossplane.io/v1alpha1
              kind: Database
              spec:
                forProvider:
                  encoding: "UTF8"
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: "spec.parameters.storageSize"
                toFieldPath: "spec.forProvider.storageSize"

    # Шаг валидации результирующего состояния через CEL внутри конвейера
    - step: validate-composition-constraints
      functionRef:
        name: function-cel
      input:
        apiVersion: cel.fn.crossplane.io/v1beta1
        kind: Context
        conditions:
          - expression: "oxr.spec.parameters.replicas >= 2"
            message: "Для продакшн-композиции postgres-onprem-production требуется не менее 2 реплик (High Availability)."
          - expression: "oxr.spec.parameters.storageSize != '0Gi'"
            message: "Параметр storageSize не может быть пустым."
```

Если условие не выполняется, конвейер завершается с ошибкой, а в статусе составного ресурса (`XR`) выставляется флаг:
```yaml
status:
  conditions:
    - type: Synced
      status: "False"
      reason: FunctionError
      message: "pipeline step validate-composition-constraints failed: Для продакшн-композиции postgres-onprem-production требуется не менее 2 реплик"
```

---

### Сценарий 6. Shift-Left тестирование манифестов в CI/CD пайплайне

Проверка политик до коммита в GitOps-репозиторий предотвращает попадание невалидных манифестов в кластер.

Команды проверки в локальном окружении или GitLab CI:
```bash
# 1. Рендеринг композиции локально без запуска кластера Kubernetes
crossplane beta render \
  tests/claims/postgres-prod-claim.yaml \
  compositions/postgres-onprem.yaml \
  functions/functions.yaml > rendered-resources.yaml
# → [OK] Resources rendered successfully (3 resources generated)

# 2. Валидация сгенерированных ресурсов по схемам провайдеров
crossplane beta validate schemas rendered-resources.yaml
# → [OK] 3/3 resources conform to provider CRD OpenAPI schemas

# 3. Юнит-тестирование политик Kyverno локально через CLI
kyverno test policies/kyverno/
# → Executing test on policies/kyverno/kyverno-test.yaml...
# → Result: PASS (4/4 rules passed, 0 failed)

# 4. Проверка манифестов через Gator CLI (Gatekeeper)
gator test --manifests manifests/ --image-tags gator-test:latest
# → ok      manifests/postgres-claim.yaml  matched disallow-raw-database-creation
```

---

## Операции и команды

Сводка команд для SRE-инженера и системного администратора при диагностике и эксплуатации политик:

| Категория | Команда | Назначение |
|---|---|---|
| **VAP** | `kubectl get validatingadmissionpolicy` | Список зарегистрированных политик VAP |
| **VAP** | `kubectl get vapb` | Список связываний (Bindings) политик VAP |
| **Kyverno** | `kubectl get clusterpolicies,policies -A` | Список глобальных и локальных политик Kyverno |
| **Kyverno** | `kubectl get clusterpolicyreports,policyreports -A` | Просмотр отчетов о нарушениях аудита |
| **Gatekeeper** | `kubectl get constrainttemplates` | Список шаблонов политик OPA |
| **Gatekeeper** | `kubectl get constraints` | Просмотр активных ограничений и счетчиков нарушений |
| **Admission** | `kubectl get mutatingwebhookconfigurations,validatingwebhookconfigurations` | Просмотр системных конфигураций вебхуков |
| **Crossplane** | `crossplane beta render <claim> <comp> <fn>` | Локальный рендеринг композиции для отладки |

### Практическая диагностика через CLI

#### 1. Проверка состояния ValidatingAdmissionPolicy
```bash
kubectl get validatingadmissionpolicy postgres-claim-guard -o wide
# → NAME                   STRICT   AGE
# → postgres-claim-guard   true     14d

kubectl get validatingadmissionpolicybinding postgres-claim-guard-binding
# → NAME                           POLICYNAME             ACTION   AGE
# → postgres-claim-guard-binding   postgres-claim-guard   Deny     14d
```

#### 2. Анализ отчетов о нарушениях аудита (PolicyReport)
```bash
kubectl get policyreports -n billing
# → NAME                    PASS   FAIL   WARN   ERROR   SKIP   AGE
# → polr-billing-report     12     2      0      0       0      3d

# Детализация нарушений в пространстве имён
kubectl get policyreport polr-billing-report -n billing -o jsonpath='{range .results[?(@.result=="fail")]}{.policy}{" -> "}{.resources[0].name}{": "}{.message}{"\n"}{end}'
# → crossplane-claim-enforcement -> billing-cache: Метка metadata.labels.environment должна иметь значение 'dev', 'stage' или 'prod'
# → crossplane-claim-enforcement -> billing-legacy-db: Отсутствует обязательная метка metadata.labels.team
```

#### 3. Мониторинг нарушений Gatekeeper в реальном времени
```bash
kubectl get CrossplaneRestrictRawMR disallow-raw-database-creation -o jsonpath='{.status.totalViolations}'
# → 0

# Просмотр последних зарегистрированных нарушений в статусе объекта
kubectl describe CrossplaneRestrictRawMR disallow-raw-database-creation
# → Total Violations: 0
# → Enforcement Action: deny
```

---

## Диагностика и устранение неполадок (Troubleshooting)

| Симптом | Вероятная причина | Диагностика | Решение |
|---|---|---|---|
| **Reconciler Crossplane зависает** с ошибкой `context deadline exceeded` при обновлении MR | Внешний вебхук Kyverno/Gatekeeper недоступен при `failurePolicy: Fail` (Webhook Deadlock). | `kubectl logs -n crossplane-system deployment/crossplane`<br>`kubectl get endpoints -n kyverno` | Добавить исключение для `system:serviceaccount:crossplane-system:*` в вебхук или временно перевести `failurePolicy` в `Ignore`. |
| **Постоянная загрузка CPU и etcd (Drift Loop)**, Crossplane непрерывно отправляет PATCH | Мутирующий вебхук подменяет значения полей в MR, конфликтуя с реконсиляцией Crossplane. | Сравнить `resourceVersion` объекта и логи: объект непрерывно инкрементирует версию раз в секунду. | Удалить `mutate`-правило для MR. Перенести генерацию defaults на уровень Claim или в Composition Functions. |
| **Ошибка при удалении Claim:** `admission webhook denied the request: deletion protected` | Сработала политика защиты от удаления, аннотация защиты не снята. | `kubectl describe <claim>` — проверить блок annotations. | Выполнить регламент: `kubectl annotate <claim> platform.onprem.io/delete-protection="false" --overwrite`, затем повторить `delete`. |
| **Ошибка создания Claim:** `CEL evaluation error: no such key: parameters` | Выражение в VAP обратилось к опциональному полю без предварительной проверки существования. | `kubectl describe vap <policy-name>` — статус `message: evaluation error`. | Использовать безопасный доступ CEL: `has(object.spec.parameters) && object.spec.parameters.cpuCores <= 16`. |
| **Claim создан со статусом Synced=True, но ресурсы не появляются** | Политика Gatekeeper/VAP заблокировала создание порожденного MR, но пропустила Claim. | `kubectl describe xr <xr-name>` — статус содержит событие `CannotCreateExternalResource: admission denied`. | Настроить исключение контроллера Crossplane для уровня MR либо синхронизировать правила валидации между Claim и MR. |
| **Блокировка ротации сертификатов** admission-вебхука | Истек срок действия mTLS-сертификата вебхука, API-сервер отвергает подключение к вебхуку. | `curl -k -v https://kyverno-svc.kyverno.svc:443/validate`<br>`kubectl logs -n kube-system kube-apiserver` | Перезапустить pod cert-manager / kyverno-controller для автоматического перевыпуска TLS-секретов. |

---

## Лучшие практики (Best Practices)

1. **Валидируйте на уровне Claim, изолируйте на уровне MR:**
   - Основную массу бизнес-правил, квот, ограничений размеров хранилищ и обязательных меток реализуйте на уровне пользовательских Claim (`CompositeResourceClaim`).
   - На уровне Managed Resources (MR) применяйте только правила жесткой защиты: запрет прямого создания вручную в обход платформы и принудительное сохранение `deletionPolicy: Orphan` для критических данных.

2. **Предпочитайте ValidatingAdmissionPolicy для критических путей:**
   - Для блокировок удаления, проверки базовых лимитов и схем именования используйте нативный VAP на базе CEL. Он работает с нулевой сетевой задержкой, не зависит от сторонних подов и полностью исключает риски Webhook Deadlock при сбоях сети или падении нод.

3. **Всегда исключайте сервисные аккаунты Crossplane из внешних вебхуков:**
   - В правилах Kyverno и Gatekeeper накладывайте условие исключения:
     ```yaml
     exclude:
       subjects:
         - kind: ServiceAccount
           name: crossplane
           namespace: crossplane-system
     ```
   - Это гарантирует непрерывность цикла реконсиляции инфраструктуры даже при проведении плановых технических работ над кластером политик.

4. **Запрет мутаций на этапе реконсиляции (No Mutating Webhooks on Composed Resources):**
   - Ни при каких обстоятельствах не внедряйте мутирующие admission-правила на CRD с API-группами провайдеров (`*.crossplane.io`). Любая мутация вне конвейера композиции неизбежно приводит к циклической войне контроллеров за состояние полей.

5. **Безопасная стратегия выкатки политик (Canary Policy Rollout):**
   - **Фаза 1 (Audit):** Развертывание новой политики в режиме `Audit` (Kyverno) или `dryrun` (Gatekeeper) на 7–14 дней.
   - **Фаза 2 (Метрики):** Мониторинг нарушений через Prometheus (`kyverno_policy_results_total`, `gatekeeper_violations`) и разбор отчетов `PolicyReport`.
   - **Фаза 3 (Enforce):** Перевод политики в режим `Enforce` (`Deny`) только после устранения всех известных несоответствий в активных манифестах.

6. **Shift-Left тестирование в CI/CD:**
   - Каждый Pull Request, изменяющий манифесты композиций или файлы политик, должен автоматически проходить стадии `crossplane beta render` и валидацию политик через `kyverno test` / `gator test`. Это исключает попадание синтаксических и логических ошибок в продуктивный кластер.

---

## Дополнительная информация

- [Официальная документация Crossplane](https://docs.crossplane.io/)
- [Kubernetes: ValidatingAdmissionPolicy Reference](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/)
- [Kyverno Documentation: Writing Policies](https://kyverno.io/docs/writing-policies/)
- [Open Policy Agent Gatekeeper Documentation](https://open-policy-agent.github.io/gatekeeper/website/docs/)

Смежные разделы базы знаний:
- [Crossplane: Обзор](./overview.md) — фундаментальные концепции и архитектура Control Plane.
- [Crossplane: Защита зависимостей (Usage)](./usage_protection.md) — рантайм-блокировка удаления ресурсов через Usage API.
- [Crossplane: Мультитенантность и изоляция](./multi_tenancy.md) — разграничение прав и изоляция команд.
- [Crossplane: Composition Functions](./composition_functions.md) — конструирование конвейеров композиции и использование функций.
- [Crossplane: Безопасность цепочки поставок пакетов](./package_security.md) — подписание и верификация OCI-пакетов xpkg.
- [Crossplane: Тестирование платформы](./testing_crossplane.md) — локальный рендеринг и интеграционное тестирование композиций.
- [GitOps: Управление политиками безопасности](../Concepts/gitops-policy-management.md) — централизованная доставка политик через Argo CD и Teleport.
