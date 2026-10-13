# Crossplane: Self-Service и Internal Developer Portal

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); Kubernetes 1.28–1.32+; On-Premise / Bare-Metal

---

## Определения

**Self-Service (инфраструктурное самообслуживание)** — операционная модель платформенной инженерии (Platform Engineering), при которой прикладные команды автономно заказывают, обновляют и выводят из эксплуатации необходимые сервисы и ресурсы через унифицированный декларативный API без прямого обращения к системным администраторам и инженерам инфраструктуры.

**Internal Developer Portal (IDP)** — централизованный интерфейс и каталог разработчика (например, Backstage, Port), предоставляющий прикладным командам доступ к сервисам платформы, документации, графам владения (Service Catalog) и интерактивным мастерам генерации инфраструктурного кода (Software Templates).

**Golden Path (золотой путь)** — стандартизированный, документированный и поддерживаемый платформенной командой шаблон развертывания сервиса или инфраструктуры (от создания манифеста до продакшн-мониторинга), снижающий когнитивную нагрузку на разработчиков и гарантирующий соблюдение корпоративных требований безопасности и надежности.

**Composite Resource Claim (Claim / XRC)** — пространство-зависимый (`Namespace-scoped`) пользовательский манифест в Kubernetes, выступающий интерфейсом заказа инфраструктуры. Прикладная команда объявляет только высокоуровневые бизнес-требования к ресурсу, не касаясь деталей провайдеров, учетных записей и низкоуровневых драйверов.

**CompositeResourceDefinition (XRD)** — кластерный ресурс Crossplane (`apiextensions.crossplane.io`), определяющий схему входных параметров (`OpenAPI v3 schema`), имя группы API, тип композитного ресурса (`XR`) и соответствующий ему пользовательский интерфейс заказа (`Claim`).

**Software Template (Scaffolder)** — исполняемый сценарий мастера самообслуживания в Backstage (`scaffolder.backstage.io`), который на основе введенных пользователем через веб-форму параметров формирует конфигурационные файлы, отправляет Pull Request в GitOps-репозиторий или регистрирует сущности в каталоге.

**Score Specification** — открытый стандарт (`score.dev`) декларативного описания требований рабочей нагрузки к среде выполнения (`score.yaml`), позволяющий абстрагировать конфигурацию приложений от конкретного оркестратора и инфраструктурных провайдеров.

**Connection Secret** — стандартный Kubernetes `Secret`, генерируемый Crossplane в пространстве имен тенанта по факту готовности инфраструктурного сервиса. Содержит реквизиты подключения (хост, порт, имя базы, сгенерированные учетные данные, сертификаты).

---

## Базовые концепции и архитектура

### Модель разделения ответственности (Platform Team vs Application Teams)

В архитектуре платформенного самообслуживания обязанности строго разделены между системными инженерами (SRE/Sysadmin/Platform) и потребителями платформы (App Teams):

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Platform Engineering (SRE)                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Разработка и публикация схем API (XRD)                                   │
│ 2. Реализация логики композиций (Compositions, Pipeline Functions)          │
│ 3. Подключение On-Premise инфраструктурных драйверов (ProviderConfig)       │
│ 4. Настройка политик лимитов и квот (ResourceQuota, ValidatingAdmission)    │
│ 5. Создание и поддержка шаблонов самообслуживания (Backstage Templates)     │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Публикация каталога
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Application Teams (Dev)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Выбор сервиса в каталоге IDP (Backstage) или через GitOps                │
│ 2. Заполнение бизнес-параметров (размер диска, число реплик, профиль среды)  │
│ 3. Создание манифеста Claim в своем локальном Namespace                      │
│ 4. Потребление Connection Secret внутри манифеста Deployment/StatefulSet    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Сквозная архитектура On-Premise платформы самообслуживания

Инфраструктура разворачивается полностью в закрытом локальном контуре (On-Premise / Bare-Metal) без обращений к публичным облакам. Все компоненты взаимодействуют через нативные API Kubernetes:

```
[Разработчик]
      │
      ▼ (Веб-форма Backstage)
[Backstage Scaffolder]
      │
      ▼ (Git Commit / Pull Request)
[GitOps Repository (GitLab / Gitea)]
      │
      ▼ (Reconciliation)
[Argo CD / Flux]
      │
      ▼ (kubectl apply -n team-alpha)
┌─────┴───────────────────────────────────────────────────────────────────────┐
│ Kubernetes Control Plane                                                    │
│                                                                             │
│  [Namespace: team-alpha]                                                    │
│    └─► Claim: PostgreSQLInstance (app-db)                                   │
│          │                                                                  │
│          │  (Crossplane Claim Engine: связывание и трансформация)           │
│          ▼                                                                  │
│  [Cluster-Scoped / Namespaced XR]                                           │
│    └─► XR: XPostgreSQLInstance (app-db-x7kq9)                               │
│          │                                                                  │
│          │  (Composition Pipeline: Function Patch & Transform)              │
│          ▼                                                                  │
│  [Managed Resources (On-Premise Providers)]                                 │
│    ├─► provider-kubernetes: Cluster (CloudNativePG / Zalando Operator)      │
│    ├─► provider-sql: Database & User Grants                                 │
│    ├─► provider-vault: AppRole / Static Secret / PKI Certificate            │
│    └─► provider-helm: Local Ingress / Monitoring Exporter                   │
│          │                                                                  │
│          ▼ (Формирование реквизитов подключения)                            │
│  [Namespace: team-alpha]                                                    │
│    └─► Secret: app-db-conn (host, port, username, password, ca.crt)         │
│          ▲                                                                  │
│          │ (envFrom / volumeMount)                                          │
│    └─► Deployment: billing-service                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Паттерны подачи заявок на инфраструктуру

1. **GitOps-Driven Self-Service (рекомендуемый производственный стандарт):**
   - Разработчик или IDP фиксирует манифест Claim в ветке прикладного репозитория (`tenants/team-alpha/infrastructure/postgres.yaml`).
   - Изменения проходят ревью (или авто-мерж при соблюдении лимитов) и синхронизируются в кластер через [GitOps Integration](file:///c:/Users/Elise/notes/GitOps/Crossplane/gitops_integration.md) (Argo CD / Flux).
   - Обеспечивается версионирование, аудит действий и простота отката (Disaster Recovery).

2. **Direct Portal Provisioning (интерактивный портал):**
   - Backstage через сервисный аккаунт с ограниченными правами создает Claim напрямую в пространстве имен тенанта.
   - Kubernetes-плагин Backstage отслеживает статус `Conditions: Ready=True, Synced=True` и отображает диагностику прямо в интерфейсе сервиса.
   - Подходит для сред разработки (Dev/Sandbox) и эфемерных тестовых окружений.

3. **Workload-Centric Specification (Score):**
   - Разработчик описывает зависимости в файле `score.yaml` вместе с кодом микросервиса.
   - Внутренний CLI-инструмент или CI/CD генератор транслирует секцию `resources` в манифесты Crossplane Claim, исключая необходимость ручного написания Kubernetes YAML для каждого окружения.

### Жизненный цикл заявки (Claim Lifecycle)

```
[Подача Claim] ──► [Поиск Composition] ──► [Создание XR] ──► [Создание MR]
       │                    │                     │                 │
       │                    ▼                     ▼                 ▼
       │               (No Match?)          (Validating?)     (Reconciling)
       │                    │                     │                 │
       ▼                    ▼                     ▼                 ▼
   [Pending]         [Error: No Comp]      [XR Created]      [MRs Waiting]
                                                                    │
                                                                    ▼
[Готово к работе] ◄── [Secret в Namespace] ◄── [XR Ready] ◄── [MRs Ready]
```

1. **Создание:** Разработчик применяет Claim с селектором `compositionSelector` или `compositionRef`.
2. **Связывание (Binding):** Crossplane сопоставляет Claim с подходящей композицией и создает/привязывает экземпляр Composite Resource (XR).
3. **Рендеринг и оркестрация:** Pipeline Functions генерируют набор управляемых ресурсов (MR) в локальном кластере (экземпляры баз данных, учетные записи, сетевые политики).
4. **Ожидание готовности:** Crossplane ожидает перехода всех дочерних MR в статус `Ready=True, Synced=True`.
5. **Публикация секретов:** Учетные данные агрегируются из MR, шифруются и записываются в пространство имен тенанта как Kubernetes Secret (`writeConnectionSecretToRef`).
6. **Day-2 обслуживание и удаление:** При изменении параметров Claim обновляются дочерние MR. При удалении Claim поведение определяется политикой `deletionPolicy` и механизмом [Usage Protection](file:///c:/Users/Elise/notes/GitOps/Crossplane/usage_protection.md).

---

## Практические сценарии и конфигурация

### Сценарий 1: Декларативное описание Claim для On-Premise PostgreSQL

Прикладная команда запрашивает отказоустойчивый кластер PostgreSQL, развертываемый внутри локального кластера оператором CloudNativePG через `provider-kubernetes` и `provider-sql`.

```yaml
# Файл: tenants/team-alpha/db-claim.yaml
apiVersion: storage.internal.corp/v1alpha1
kind: PostgreSQLInstance
metadata:
  name: billing-db
  namespace: team-alpha
  labels:
    app.kubernetes.io/part-of: billing-service
    environment: production
spec:
  parameters:
    storageGB: 100
    replicas: 3
    databaseName: billing_prod
    tier: high-availability
    backupRetentionDays: 14
  compositionSelector:
    matchLabels:
      provider: on-premise
      engine: cloudnative-pg
  writeConnectionSecretToRef:
    name: billing-db-connection
```

Платформенная схема XRD, определяющая этот API:

```yaml
# Файл: platform/xrd/postgresql-xrd.yaml
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: xpostgresqlinstances.storage.internal.corp
spec:
  group: storage.internal.corp
  names:
    kind: XPostgreSQLInstance
    plural: xpostgresqlinstances
  claimNames:
    kind: PostgreSQLInstance
    plural: postgresqlinstances
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
              required:
                - parameters
              properties:
                parameters:
                  type: object
                  required:
                    - databaseName
                    - storageGB
                  properties:
                    databaseName:
                      type: string
                      pattern: '^[a-z0-9_]{3,32}$'
                    storageGB:
                      type: integer
                      minimum: 10
                      maximum: 500
                    replicas:
                      type: integer
                      enum: [1, 2, 3]
                      default: 2
                    tier:
                      type: string
                      enum: [standard, high-availability]
                      default: standard
                    backupRetentionDays:
                      type: integer
                      minimum: 1
                      maximum: 90
                      default: 7
```

### Сценарий 2: Backstage Software Template (Scaffolder v1beta3)

Шаблон Backstage, создающий GitOps Pull Request с Claim-манифестом в репозиторий команды при заказе сервиса через веб-портал:

```yaml
# Файл: backstage/templates/postgres-selfservice-template.yaml
apiVersion: scaffolder.backstage.io/v1beta3
kind: Template
metadata:
  name: onprem-postgresql-template
  title: Заказ PostgreSQL кластера (On-Premise)
  description: Создание отказоустойчивого экземпляра PostgreSQL через Crossplane Claim
  tags:
    - infrastructure
    - database
    - on-premise
    - postgresql
spec:
  owner: platform-team
  type: service

  parameters:
    - title: Основные параметры сервиса
      required:
        - namespace
        - serviceName
        - databaseName
      properties:
        namespace:
          title: Пространство имен команды (Namespace)
          type: string
          description: Целевой Namespace тенанта
        serviceName:
          title: Имя сервиса
          type: string
          pattern: '^[a-z0-9-]+$'
        databaseName:
          title: Имя базы данных
          type: string
          pattern: '^[a-z0-9_]+$'
    - title: Конфигурация ресурсов
      required:
        - storageGB
        - tier
      properties:
        storageGB:
          title: Объем хранилища (GB)
          type: integer
          default: 50
          minimum: 10
          maximum: 500
        replicas:
          title: Количество реплик
          type: integer
          default: 2
          enum: [1, 2, 3]
        tier:
          title: Уровень надежности
          type: string
          default: standard
          enum:
            - standard
            - high-availability

  steps:
    - id: template
      name: Генерация манифеста Claim
      action: fetch:template
      input:
        url: ./skeleton
        values:
          serviceName: ${{ parameters.serviceName }}
          namespace: ${{ parameters.namespace }}
          databaseName: ${{ parameters.databaseName }}
          storageGB: ${{ parameters.storageGB }}
          replicas: ${{ parameters.replicas }}
          tier: ${{ parameters.tier }}

    - id: publish-pr
      name: Создание Pull Request в GitOps-репозиторий
      action: publish:gitlab:merge-request
      input:
        repoUrl: gitlab.internal.corp?repo=tenants-${{ parameters.namespace }}
        branch: infra/postgres-${{ parameters.serviceName }}
        title: "feat(infra): заказ базы данных ${{ parameters.serviceName }}"
        description: "Автоматически сгенерированный запрос инфраструктуры через IDP Backstage."
        targetBranch: main

  output:
    links:
      - title: Перейти к Pull Request
        url: ${{ steps['publish-pr'].output.mergeRequestUrl }}
```

Файл шаблона в поддиректории `./skeleton/db-claim.yaml`:

```yaml
apiVersion: storage.internal.corp/v1alpha1
kind: PostgreSQLInstance
metadata:
  name: ${{ values.serviceName }}-db
  namespace: ${{ values.namespace }}
spec:
  parameters:
    databaseName: ${{ values.databaseName }}
    storageGB: ${{ values.storageGB }}
    replicas: ${{ values.replicas }}
    tier: ${{ values.tier }}
  compositionSelector:
    matchLabels:
      provider: on-premise
  writeConnectionSecretToRef:
    name: ${{ values.serviceName }}-db-conn
```

### Сценарий 3: Интеграция с абстракцией рабочей нагрузки Score

Файл `score.yaml` микросервиса, декларирующий зависимость от локального PostgreSQL и кэша Redis:

```yaml
# Файл: app/score.yaml
apiVersion: score.dev/v1b1
metadata:
  name: order-processor
service:
  ports:
    http:
      port: 8080
      targetPort: 8080
containers:
  web:
    image: registry.internal.corp/apps/order-processor:v1.4.2
    variables:
      DB_HOST: ${resources.db.host}
      DB_PORT: ${resources.db.port}
      DB_USER: ${resources.db.username}
      DB_PASSWORD: ${resources.db.password}
      DB_NAME: ${resources.db.database}
      REDIS_HOST: ${resources.cache.host}
resources:
  db:
    type: postgres
    params:
      extensions:
        - uuid-ossp
  cache:
    type: redis
    params:
      memoryMb: 512
```

Внутренний транслятор платформы конвертирует спецификацию ресурсов Score в Claim Crossplane:

```yaml
# Сгенерированный манифест Claim для базы данных
apiVersion: storage.internal.corp/v1alpha1
kind: PostgreSQLInstance
metadata:
  name: order-processor-db
  namespace: team-orders
spec:
  parameters:
    databaseName: order_processor
    storageGB: 20
    replicas: 2
  writeConnectionSecretToRef:
    name: order-processor-db
```

### Сценарий 4: Контроль потребления через ValidatingAdmissionPolicy и ResourceQuota

Для защиты локальных узлов и СХД Bare-Metal кластера от бесконтрольного заказа ресурсов настраиваются лимиты Kubernetes.

#### Ограничение количества Claim на Namespace:

```yaml
# Файл: platform/governance/tenant-quota.yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: crossplane-claims-quota
  namespace: team-alpha
spec:
  hard:
    count/postgresqlinstances.storage.internal.corp: "5"
    count/redisinstances.cache.internal.corp: "10"
```

#### Валидация параметров через CEL (Kubernetes 1.28+):

```yaml
# Файл: platform/governance/claim-validation-policy.yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: postgres-claim-rules
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: ["storage.internal.corp"]
        apiVersions: ["v1alpha1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["postgresqlinstances"]
  validations:
    - expression: "object.spec.parameters.storageGB <= 200 || object.metadata.namespace == 'system-infrastructure'"
      message: "Превышен лимит дискового пространства: стандартным тенантам доступно не более 200 GB."
    - expression: "object.spec.writeConnectionSecretToRef.name.size() > 0"
      message: "Обязательно указание writeConnectionSecretToRef для получения учетных данных."
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: postgres-claim-rules-binding
spec:
  policyName: postgres-claim-rules
  validationActions: [Deny]
```

---

## Эксплуатация и команды диагностики

### Проверка состояния Claim и сопутствующих ресурсов

Просмотр списка зарегистрированных заявок тенанта:

```bash
kubectl get claim,postgresqlinstance -n team-alpha
# → NAME                                                  SYNCED   READY   CONNECTION-SECRET       AGE
# → postgresqlinstance.storage.internal.corp/billing-db   True     True    billing-db-connection   4m12s
```

Детальный просмотр статуса заявки и событий контроллера:

```bash
kubectl describe postgresqlinstance billing-db -n team-alpha
# → Name:         billing-db
# → Namespace:    team-alpha
# → API Version:  storage.internal.corp/v1alpha1
# → Kind:         PostgreSQLInstance
# → Spec:
# →   Composition Ref:
# →     Name:  pg-onpremise-ha
# →   Resource Ref:
# →     API Version:  storage.internal.corp/v1alpha1
# →     Kind:         XPostgreSQLInstance
# →     Name:         billing-db-7d84f
# → Status:
# →   Conditions:
# →     Last Transition Time:  2026-10-13T17:20:10Z
# →     Reason:                Available
# →     Status:                True
# →     Type:                  Ready
# →     Last Transition Time:  2026-10-13T17:19:40Z
# →     Reason:                ReconcileSuccess
# →     Status:                True
# →     Type:                  Synced
# → Events:
# →   Type    Reason                    Age   From                                 Message
# →   ----    ------                    ----  ----                                 -------
# →   Normal  CompositeResourceBound    4m    crossplane/composite-claim-binding   Bound composite resource: billing-db-7d84f
# →   Normal  ConnectionSecretWritten   3m    crossplane/composite-claim-binding   Wrote connection secret to team-alpha/billing-db-connection
```

### Сквозная трассировка графа ресурсов через Crossplane CLI

Анализ дерева дочерних On-Premise ресурсов от Claim до конечных Managed Resources:

```bash
crossplane trace postgresqlinstance billing-db -n team-alpha
# → NAME                                                            SYNCED   READY   STATUS
# → PostgreSQLInstance/billing-db (team-alpha)                     True     True    Available
# → └─ XPostgreSQLInstance/billing-db-7d84f                         True     True    Available
# →    ├─ Cluster/billing-db-cluster                                True     True    Cluster is healthy
# →    ├─ Database/billing-db-schema                                True     True    Database created
# →    └─ Secret/billing-db-secret                                  True     True    Available
```

Проверка содержимого Connection Secret (без декодирования пароля):

```bash
kubectl get secret billing-db-connection -n team-alpha -o jsonpath='{.data}' | jq 'keys'
# → [
# →   "endpoint",
# →   "host",
# →   "password",
# →   "port",
# →   "username"
# → ]
```

### Мониторинг ключевых метрик Self-Service платформы

Запрос метрик времени готовности ресурсов (Time to Provision) в Prometheus:

```bash
# Проверка количества готовых композитных ресурсов
curl -s http://crossplane-metrics.crossplane-system:8080/metrics | grep crossplane_composite_resource
# → # HELP crossplane_composite_resource_ready Number of composite resources in Ready state
# → # TYPE crossplane_composite_resource_ready gauge
# → crossplane_composite_resource_ready{group="storage.internal.corp",kind="XPostgreSQLInstance"} 18
# → crossplane_composite_resource_synced{group="storage.internal.corp",kind="XPostgreSQLInstance"} 18
```

---

## Устранение неполадок (Troubleshooting)

### 1. Заявка зависла в статусе `Waiting: composite resource is not ready`

**Симптомы:**
`kubectl get claim -n team-alpha` показывает `READY: False`, `SYNCED: True`. В событиях Claim: `Waiting: composite resource is not ready`.

**Причина:**
Один из дочерних Managed Resources не может завершить согласование. В On-Premise средах наиболее частые причины:
1. Отсутствие свободных ресурсов CPU/Memory на рабочих узлах кластера.
2. Нехватка места или сбой в On-Premise CSI драйвере (Ceph-RBD, Local-Path, LVM).
3. Ошибка авторизации оператора базы данных при выполнении SQL-скрипта инициализации.

**Диагностика:**
```bash
# 1. Выясняем имя привязанного XR
XR_NAME=$(kubectl get postgresqlinstance billing-db -n team-alpha -o jsonpath='{.spec.resourceRef.name}')

# 2. Проверяем статус дочерних MR
crossplane trace xpostgresqlinstance $XR_NAME

# 3. Детально осматриваем сбойный ресурс
kubectl describe cluster.postgresql.cnpg.io billing-db-cluster
```

**Решение:**
- Если сбой вызван `Pending PVC` — проверьте состояние CSI-плагина (`kubectl get volumeattachment,pvc -A`) и емкость пула хранилища.
- Если сбой вызван отсутствием ресурсов — добавьте вычислительные мощности узлам или скорректируйте параметры Claim в меньшую сторону.

---

### 2. Секрет подключения (Connection Secret) не создается в пространстве имен тенанта

**Симптомы:**
XR и MR находятся в статусе `Ready=True`, однако в пространстве имен `team-alpha` объект `Secret` с именем из `writeConnectionSecretToRef` отсутствует.

**Причина:**
1. Неверно настроена секция `writeConnectionSecretsToNamespace` в `spec` XRD.
2. Отсутствие прав RBAC у `crossplane-rbac-manager` на создание Secret в пространстве имен целевого тенанта.
3. Дочерние Managed Resources не передали ключи подключения в XR (в композиции не настроен `connectionDetails`).

**Диагностика:**
```bash
# Проверяем лог ядра Crossplane
kubectl logs -n crossplane-system deployment/crossplane | grep -i "secret" | grep "billing-db"
# → 2026-10-13T17:25:01Z ERROR cannot write connection secret to ref {"error": "secrets is forbidden: User system:serviceaccount:crossplane-system:crossplane cannot create resource secrets in namespace team-alpha"}
```

**Решение:**
Убедитесь, что сервисный аккаунт Crossplane наделен правами управления секретами через агрегированные роли или кластерную роль:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: crossplane-secret-writer
  labels:
    rbac.crossplane.io/aggregate-to-crossplane: "true"
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

---

### 3. Backstage Scaffolder падает с ошибкой валидации схемы

**Симптомы:**
При отправке формы в IDP Backstage мастер завершается с ошибкой `HTTP 422: Unprocessable Entity` или `Invalid schema parameters`.

**Причина:**
Рассинхронизация между валидационной схемой в Backstage Template (`postgres-selfservice-template.yaml`) и актуальной OpenAPI-схемой XRD в кластере Kubernetes. Например, в XRD был добавлен новый обязательный параметр `backupRetentionDays`, не указанный в макете формы IDP.

**Диагностика:**
```bash
# Извлечение актуальной схемы параметров из XRD
kubectl get xrd xpostgresqlinstances.storage.internal.corp -o jsonpath='{.spec.versions[0].schema.openAPIV3Schema.properties.spec.properties.parameters.required}'
# → ["databaseName","storageGB","backupRetentionDays"]
```

**Решение:**
- Актуализируйте `spec.parameters` в манифесте шаблона Backstage.
- Настройте линтинг манифестов IDP в CI/CD пайплайне с проверкой соответствия установленным в кластере XRD перед выкаткой обновлений портала.

---

### 4. Ошибка `cannot bind claim to already bound composite resource`

**Симптомы:**
При пересоздании Claim в статусе отображается ошибка:
`cannot bind claim: composite resource xpostgresqlinstance/billing-db-7d84f is already bound to another claim`.

**Причина:**
При удалении старого Claim экземпляр XR не был удален (например, из-за политики `deletionPolicy: Orphan` или зависших финализаторов), либо новый Claim случайно пытается связаться с чужим существующим ресурсом.

**Диагностика:**
```bash
kubectl get xpostgresqlinstance -o custom-columns=NAME:.metadata.name,CLAIM:.spec.claimRef.name,NS:.spec.claimRef.namespace
# → NAME                 CLAIM        NS
# → billing-db-7d84f     billing-db   team-alpha
```

**Решение:**
- Если XR остался от удаленного Claim и данные больше не нужны: снимите финализаторы и удалите осиротевший XR вручную:
  ```bash
  kubectl delete xpostgresqlinstance billing-db-7d84f
  ```
- Для предотвращения коллизий всегда используйте уникальные имена Claim либо гарантируйте каскадное удаление XR через `defaultCompositionUpdatePolicy: Automatic`.

---

## Рекомендации и Best Practices

### Архитектура и безопасность (Security & Tenant Isolation)

1. **Принцип минимальных привилегий (Least Privilege):**
   - Прикладным разработчикам и сервисным аккаунтам CI/CD предоставляется доступ исключительно к объектам Claim в границах их `Namespace`.
   - Доступ к кластерным ресурсам (`XRD`, `Compositions`, `ClusterProviderConfig`, корневые секреты СХД и баз данных) категорически запрещен.
   - Подробнее см. [Мультитенантность и изоляция](file:///c:/Users/Elise/notes/GitOps/Crossplane/multi_tenancy.md).

2. **Строгая валидация входных параметров:**
   - Каждое поле в `spec.parameters` XRD должно содержать строгие ограничения (`minimum`, `maximum`, `pattern`, `enum`).
   - Используйте [ValidatingAdmissionPolicy](file:///c:/Users/Elise/notes/GitOps/Crossplane/policy_governance.md) для динамической проверки соответствия корпоративным стандартам.

3. **Изоляция учетных данных:**
   - Не используйте единый суперпользовательский логин для всех баз данных. На стороне композиции через `provider-sql` или `provider-vault` создавайте уникальные роли с индивидуальными случайно сгенерированными паролями на каждый экземпляр Claim.

### Эксплуатация и SRE (Reliability & Lifecycle)

1. **Защита от непреднамеренного уничтожения данных:**
   - Для производственных окружений накладывайте `deletionPolicy: Orphan` на физические тома (PersistentVolume / Block Devices), чтобы при случайном удалении Claim данные на дисках сохранялись.
   - Используйте механизм [Usage Protection](file:///c:/Users/Elise/notes/GitOps/Crossplane/usage_protection.md) (`protection.crossplane.io/v1beta1`), блокирующий удаление инфраструктуры, пока к ней привязаны активные поды приложений.

2. **Декларативные SLO платформы:**
   - Измеряйте Time to Provision (TTP): 95% запросов на создание типовой базы данных должны переходить в статус `Ready=True` менее чем за 180 секунд.
   - Настройте Prometheus Alertmanager на обнаружение зависших заявок:
     ```yaml
     alert: CrossplaneClaimStuckNotReady
     expr: crossplane_composite_resource_ready{status="False"} == 1
     for: 15m
     labels:
       severity: warning
     annotations:
       summary: "Экземпляр {{ $labels.kind }} {{ $labels.name }} не может перейти в состояние Ready более 15 минут"
     ```

3. **Версионирование каталога самообслуживания:**
   - При обновлении схем API выпускайте новую версию (`v1beta1`, `v1`), сохраняя обратную совместимость через конверсионные вебхуки или поддерживая обе версии в XRD параллельно.
   - Не вносите ломающие изменения (`breaking changes`) в существующие Compositions без предварительного тестирования через [Testing Crossplane](file:///c:/Users/Elise/notes/GitOps/Crossplane/testing_crossplane.md).

---

## Связанные материалы и ссылки

- [Обзор Crossplane и архитектура](file:///c:/Users/Elise/notes/GitOps/Crossplane/overview.md) — базовые концепции XRD, XR, Composition и Claim.
- [Мультитенантность и изоляция](file:///c:/Users/Elise/notes/GitOps/Crossplane/multi_tenancy.md) — разделение прав команд, RBAC Manager и модели Soft/Hard Multi-Tenancy.
- [Интеграция с GitOps](file:///c:/Users/Elise/notes/GitOps/Crossplane/gitops_integration.md) — управление жизненным циклом Claim и пакетов через Argo CD и Flux.
- [Политики и Governance](file:///c:/Users/Elise/notes/GitOps/Crossplane/policy_governance.md) — контроль лимитов, Kyverno, Gatekeeper и ValidatingAdmissionPolicy.
- [Функции композиций (Composition Functions)](file:///c:/Users/Elise/notes/GitOps/Crossplane/composition_functions.md) — построение продвинутых pipeline-обработчиков для генерации инфраструктуры.
- [Мониторинг и Observability](file:///c:/Users/Elise/notes/GitOps/Crossplane/observability.md) — метрики, экспортеры и трассировка состояния ресурсов.
- [Защита зависимостей (Usage Protection)](file:///c:/Users/Elise/notes/GitOps/Crossplane/usage_protection.md) — предотвращение каскадного удаления зависимых ресурсов.
- [Backstage Documentation](https://backstage.io/docs/) — официальное руководство по настройке Software Templates и Service Catalog.
- [Score Specification](https://score.dev/docs/) — спецификация описания рабочих нагрузок для платформ разработки.
