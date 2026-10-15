# Argo CD: Динамические окружения с Crossplane и GitLab CI

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; ApplicationSet scmProvider / pullRequest генераторы, Progressive Syncs; Crossplane v1.18+ / v2.x; GitLab 17.x+ Self-Managed; bare-metal / on-premise)

Динамические окружения (Review Apps / Preview Environments) — практика автоматического развертывания изолированного экземпляра приложения и необходимой ему инфраструктуры для каждой функциональной ветки или открытого Merge Request (MR). Связка Argo CD ApplicationSet и Crossplane позволяет реализовать полноценный GitOps-жизненный цикл без привязки к публичным облакам: ApplicationSet отслеживает состояние репозиториев во внутреннем GitLab и создает объекты `Application`, а Crossplane декларативно выделяет инфраструктурные зависимости (выделенные базы данных, схемы, системные учетные записи, очереди сообщений и локальные S3-бакеты в Ceph/MinIO) на базе существующей корпоративной on-premise инфраструктуры.

## Предварительные требования

Для развертывания и промышленной эксплуатации динамических окружений в on-premise контуре необходимы:

| Компонент | Минимальная версия | Назначение в on-premise архитектуре |
| :--- | :--- | :--- |
| **Kubernetes** | v1.28–v1.32+ | On-premise кластер (bare-metal, Kube-OVN / Calico / Cilium CNI, local/SAN CSI) |
| **Argo CD** | v3.4+ / v3.5.x | Центральный GitOps-контроллер с встроенным ApplicationSet Controller ([руководство по установке](./argocd_installation_and_setup.md)) |
| **Crossplane** | v1.18+ / v2.x | Control Plane для декларативного управления инфраструктурой ([обзор Crossplane](../Crossplane/overview.md)) |
| **Провайдеры Crossplane** | `provider-sql`, `provider-kubernetes` | Управление объектами СУБД (PostgreSQL/MySQL) и ресурсами K8s ([настройка provider-kubernetes](../Crossplane/provider_kubernetes_setup.md)) |
| **GitLab Self-Managed** | v16.x–v17.x | Внутренний Git-хостинг с настроенным API-токеном (Project/Group Access Token) и GitLab CI |
| **Container Registry** | Harbor v2.8+ / GitLab Registry | Локальный реестр образов с поддержкой автоматической очистки тегов (Retention Policy) |
| **Ingress Controller** | Ingress-NGINX / Envoy Gateway | Маршрутизация HTTP/HTTPS-трафика на preview-сервисы через Wildcard DNS |
| **cert-manager** | v1.14+ | Автоматический выпуск TLS-сертификатов через корпоративный CA / Step-CA / Vault PKI |
| **ExternalDNS** | v0.14+ | Автоматическая регистрация DNS-записей во внутреннем DNS-сервере (RFC2136 / BIND9 / PowerDNS / CoreDNS) |

---

## Определения

- **Динамическое окружение (Preview Environment / Review App)** — временный, изолированный контур (выделенный namespace в Kubernetes и сопутствующие сервисные ресурсы), создаваемый автоматически при открытии Merge Request и уничтожаемый при его закрытии или слиянии.
- **ApplicationSet Controller** — встроенный в ядро Argo CD контроллер, автоматизирующий генерацию дочерних объектов `Application` на основе внешних источников данных (генераторов).
- **Pull Request Generator (`pullRequest`)** — генератор ApplicationSet, опрашивающий API Git-хостинга (GitLab, Gitea, Bitbucket Server) на наличие открытых MR/PR с возможностью фильтрации по меткам (labels), веткам и статусу драфта (`draft: false`).
- **SCM Provider Generator (`scmProvider`)** — генератор ApplicationSet, сканирующий репозитории группы или организации и генерирующий приложения на основе веток (`allBranches: true`) или найденных манифестов.
- **Crossplane** — открытый Kubernetes-native фреймворк для управления внешними и внутренними инфраструктурными сервисами через единый декларативный API Kubernetes.
- **Crossplane Managed Resource (MR)** — низкоуровневый декларативный ресурс, управляемый контроллером провайдера (например, база данных `Database`, пользователь `Role` или грант `Grant` в `provider-sql`).
- **Composite Resource Definition (XRD)** — кластерная схема пользовательского API платформы (например, абстракция `XPostgresDatabase`), определяющая параметры, доступные разработчику.
- **Composition** — реализация XRD в Crossplane v2.x (через `mode: Pipeline`), определяющая, какие конкретно Managed Resources создаются при запросе Claim и как передаются параметры подключения.
- **Composite Resource Claim (Claim)** — namespace-scoped запрос разработчика на получение инфраструктурного ресурса, жизненный цикл которого привязан к namespace preview-окружения.
- **Review App Namespace** — изолированное пространство имен в Kubernetes, создаваемое по шаблону `preview-mr-<id>` или `preview-<branch>`, содержащее рабочие нагрузки приложения, сетевые политики и квоты.

---

## Базовые концепции и архитектура

### Архитектура и поток данных (Workflow)

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│              On-Premise GitOps-пайплайн динамических окружений                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. GitLab Event        2. GitLab CI               3. Argo CD ApplicationSet    │
│  ┌──────────────┐      ┌─────────────────┐        ┌─────────────────────────┐   │
│  │ Open MR #104 │─────▶│ Сборка и пуш    │───────▶│ Обнаружение открытого   │   │
│  │ label:preview│      │ образа в Harbor │        │ MR через GitLab API     │   │
│  └──────────────┘      └─────────────────┘        └─────────────────────────┘   │
│                                                                │                │
│                                                                ▼ Рендеринг      │
│  6. Очистка по MR       5. Сеть и TLS             4. Дочерний Application       │
│  ┌──────────────┐      ┌─────────────────┐        ┌─────────────────────────┐   │
│  │ Удаление MR  │◀─────│ Ingress-NGINX + │◀───────│ Sync: Deploy, Service,  │   │
│  │ → Prune App  │      │ RFC2136 DNS +   │        │ Ingress, Crossplane DB  │   │
│  │ → Drop DB/NS │      │ cert-manager    │        └─────────────────────────┘   │
│  └──────────────┘      └─────────────────┘                     │                │
│                                                                ▼                │
│                                                   ┌─────────────────────────┐   │
│                                                   │ Crossplane provider-sql │   │
│                                                   │ CREATE DATABASE mr_104  │   │
│                                                   │ на shared HA PostgreSQL │   │
│                                                   └─────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Этапы жизненного цикла

1. **Событие в Git:** Инженер открывает Merge Request в GitLab (например, `MR !104`) и назначает метку `deploy-preview`.
2. **CI-пайплайн (GitLab CI):**
   - Выполняются линтеры и модульные тесты.
   - Собирается образ сервиса с тегом `mr104-<commit_sha>` и публикуется в локальный Harbor.
   - Пайплайн регистрирует preview-окружение в секции `environment` GitLab CI.
3. **Обнаружение и генерация (Argo CD):**
   - ApplicationSet Controller через генератор `pullRequest` опрашивает GitLab API (или принимает Webhook).
   - Обнаружив MR с меткой `deploy-preview`, контроллер создает объект `Application` с именем `preview-billing-mr-104`.
4. **Выделение инфраструктуры (Crossplane):**
   - Внутри сгенерированного namespace `preview-mr-104` создается Claim на инфраструктурную зависимость (например, изолированная БД PostgreSQL).
   - Контроллер `provider-sql` подключается к корпоративному HA-кластеру PostgreSQL (Patroni / bare-metal), создает базу данных `preview_billing_104`, генерирует изолированного пользователя со случайным паролем, выставляет права и записывает реквизиты в Kubernetes Secret.
5. **Сетевой доступ и публикация:**
   - Ingress-контроллер публикует приложение по адресу `mr-104.preview.internal.corp`.
   - `ExternalDNS` через протокол RFC2136 (TSIG-ключ) создает запись в корпоративном BIND9/PowerDNS сервере.
   - `cert-manager` выпускает TLS-сертификат от внутреннего центра сертификации (Vault PKI / Step-CA).
6. **Очистка ресурсов (Teardown):**
   - При слиянии или закрытии MR генератор `pullRequest` удаляет приложение из своего списка.
   - Argo CD удаляет дочерний `Application` и запускает каскадное удаление (Prune) namespace.
   - Финализатор Crossplane перехватывает удаление Claim/MR: `provider-sql` выполняет команду `DROP DATABASE` и `DROP ROLE`, гарантируя отсутствие утечек ресурсов на корпоративных серверах СУБД.

---

### Сравнение подходов: Pull Request vs SCM Provider (Branch-based)

В производственной on-premise среде выбор генератора определяет стабильность и утилизацию серверных мощностей:

| Критерий | `pullRequest` генератор (Рекомендуется) | `scmProvider` генератор (Branch-based) |
| :--- | :--- | :--- |
| **Триггер создания** | Открытие MR/PR с проверкой меток (`labels: [preview]`) | Любой push в ветку, удовлетворяющую regex (`feat/*`) |
| **Утилизация CPU/RAM** | **Минимальная и контролируемая:** окружения создаются только для активного ревью | **Высокий риск перегрузки:** десятки заброшенных веток исчерпывают ресурсы кластера |
| **Защита от Draft-кода** | Нативная поддержка `draft: false` (черновики игнорируются) | Не поддерживается (ветка создана — окружение развернуто) |
| **Интеграция с CI/CD** | Прямая связь с номером MR (`{{ .number }}`), URL в интерфейсе ревью | Привязка только к имени ветки (`{{ .branch }}`) |
| **Очистка окружений** | Автоматическая при нажатии кнопки Close / Merge в GitLab | Только после физического удаления ветки в Git |

---

### Шаблонизация: fasttemplate vs goTemplate v2

Исторически ApplicationSet использовал простой строковый подстановщик `fasttemplate` (`{{branchNormalized}}`). В актуальных версиях Argo CD v3.5+ промышленным стандартом является использование движка `goTemplate: true`:

```yaml
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
```

**Преимущества `goTemplate` для Sysadmin / DevOps:**
- Полный доступ к функциям библиотеки Sprig: обрезка строк (`trunc 50`), хеширование (`sha1sum`), приведение регистра (`lower`), замена символов (`replace "/" "-"`).
- Строгая проверка отсутствующих ключей (`missingkey=error`), исключающая развертывание поврежденных `Application`.
- Условная логика (`if/else`) и циклы внутри шаблона манифеста.

---

### Нормализация имен для DNS и Kubernetes

Имена веток в Git часто содержат символы, недопустимые в DNS-записях (RFC 1123) и именах namespace Kubernetes: слэши, подчеркивания, точки, заглавные буквы. Максимальная длина метки DNS составляет **63 символа**.

Пример нормализации через функции Sprig в `goTemplate`:

```yaml
# Преобразование "feat/CORE-104_payment-gate" -> "preview-core-104-payment-gate"
name: 'preview-{{ .branch | lower | replace "/" "-" | replace "_" "-" | trunc 40 }}'
```

Таблица допустимых трансформаций:

| Исходное имя в Git | Требование RFC 1123 | Корректный Namespace | Корректный DNS FQDN |
| :--- | :--- | :--- | :--- |
| `feat/billing-v2` | Нижний регистр, дефисы | `preview-billing-v2` | `billing-v2.preview.internal.corp` |
| `fix/issue_482` | Замена `_` на `-` | `preview-fix-issue-482` | `fix-issue-482.preview.internal.corp` |
| `MR !104` (pullRequest) | Целочисленный ID | `preview-mr-104` | `mr-104.preview.internal.corp` |

---

## Практические сценарии

### Сценарий 1: ApplicationSet с Pull Request Generator для GitLab Self-Managed

Основной производственный сценарий: развертывание preview-окружения только при открытии MR с явной меткой `deploy-preview`.

#### 1.1 Создание секрета доступа к API GitLab

Токен GitLab (Project Access Token или Group Access Token с правами `read_api`) размещается в namespace `argocd`:

```bash
kubectl -n argocd create secret generic gitlab-api-secret \
  --from-literal=token="glpat-xxxxxxxxxxxxxxxxxxxx" \
  --dry-run=client -o yaml | kubectl apply -f -
# → secret/gitlab-api-secret created
```

#### 1.2 Манифест ApplicationSet

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: preview-pull-requests
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: argocd-preview
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  syncPolicy:
    applicationsSync: create-update-delete # Удалять Application при закрытии MR
    preserveResourcesOnDeletion: false
  generators:
    - pullRequest:
        gitlab:
          project: "42" # Числовой ID проекта в GitLab Self-Managed
          api: https://gitlab.internal.corp/ # Внутренний адрес GitLab
          tokenRef:
            secretName: gitlab-api-secret
            key: token
          pullRequestState: opened
          labels:
            - deploy-preview # Фильтрация: создавать только при наличии метки
        requeueAfterSeconds: 180 # Резервный интервал опроса API (3 мин)
  template:
    metadata:
      name: 'preview-app-mr-{{ .number }}'
      labels:
        environment: preview
        mr-id: '{{ .number }}'
        managed-by: applicationset
    spec:
      project: preview-apps # Выделенный AppProject с ограничениями
      source:
        repoURL: https://gitlab.internal.corp/core/manifests.git
        targetRevision: '{{ .head_sha }}'
        path: charts/microservice
        helm:
          releaseName: 'app-mr-{{ .number }}'
          valuesObject:
            image:
              tag: 'mr-{{ .number }}-{{ .head_sha | trunc 8 }}'
            ingress:
              enabled: true
              host: 'mr-{{ .number }}.preview.internal.corp'
            infrastructure:
              database:
                enabled: true
                instanceName: 'db-mr-{{ .number }}'
      destination:
        server: https://kubernetes.default.svc
        namespace: 'preview-mr-{{ .number }}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
          - PruneLast=true
          - ApplyOutOfSyncOnly=true
```

---

### Сценарий 2: ApplicationSet с SCM Provider Generator (Branch-based)

Сценарий для автоматического развертывания веток с префиксом `feat/*` во всей группе проектов `fintech`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: preview-branches-scm
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  syncPolicy:
    applicationsSync: create-update-delete
    preserveResourcesOnDeletion: false
  generators:
    - scmProvider:
        gitlab:
          group: "fintech/services"
          url: https://gitlab.internal.corp/
          allBranches: true
          tokenRef:
            secretName: gitlab-api-secret
            key: token
        filters:
          - branchMatch: ^feat/.*
  template:
    metadata:
      name: '{{ .repository }}-{{ .branch | lower | replace "/" "-" | trunc 30 }}'
    spec:
      project: preview-apps
      source:
        repoURL: '{{ .url }}'
        targetRevision: '{{ .branch }}'
        path: deploy/helm
        helm:
          valuesObject:
            ingress:
              host: '{{ .repository }}-{{ .branch | lower | replace "/" "-" | trunc 30 }}.preview.internal.corp'
      destination:
        server: https://kubernetes.default.svc
        namespace: 'preview-{{ .repository }}-{{ .branch | lower | replace "/" "-" | trunc 25 }}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

---

### Сценарий 3: Matrix Generator для Multi-Cluster On-Premise сред

Если в организации эксплуатируется несколько изолированных bare-metal тестовых кластеров (например, кластеры ЦОД-1 и ЦОД-2):

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: preview-multicluster
  namespace: argocd
spec:
  goTemplate: true
  syncPolicy:
    applicationsSync: create-update-delete
  generators:
    - matrix:
        generators:
          - pullRequest:
              gitlab:
                project: "42"
                api: https://gitlab.internal.corp/
                tokenRef:
                  secretName: gitlab-api-secret
                  key: token
                labels:
                  - deploy-preview
          - clusters:
              selector:
                matchLabels:
                  environment: preview-pool
  template:
    metadata:
      name: 'preview-{{ .name }}-mr-{{ .number }}'
    spec:
      project: preview-apps
      source:
        repoURL: https://gitlab.internal.corp/core/manifests.git
        targetRevision: '{{ .head_sha }}'
        path: deploy/helm
      destination:
        server: '{{ .server }}'
        namespace: 'preview-mr-{{ .number }}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

---

### Сценарий 4: Декларативная БД через Crossplane `provider-sql` (On-Premise)

Вместо медленного создания отдельных тяжелых СУБД, в on-premise среде используется общий высокодоступный кластер PostgreSQL (Patroni / bare-metal). Crossplane декларативно создает изолированную логическую БД, пользователя и выдает Secret в namespace preview-окружения.

#### 4.1 Установка провайдера и настройка ProviderConfig

Манифест установки `provider-sql`:

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-sql
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-sql:v0.9.0
```

Секрет подключения администратора к shared PostgreSQL:

```bash
kubectl -n crossplane-system create secret generic postgres-admin-creds \
  --from-literal=username="postgres" \
  --from-literal=password="SecretAdminPass123" \
  --dry-run=client -o yaml | kubectl apply -f -
# → secret/postgres-admin-creds created
```

Манифест `ProviderConfig`:

```yaml
apiVersion: postgresql.sql.crossplane.io/v1alpha1
kind: ProviderConfig
metadata:
  name: postgres-shared-cluster
spec:
  credentials:
    source: PostgreSQLConnectionSecret
    connectionSecretRef:
      namespace: crossplane-system
      name: postgres-admin-creds
      key: password
  address: "postgres-ha.infra.internal.corp"
  port: 5432
  sslMode: "require"
```

#### 4.2 Crossplane Composition Pipeline (Crossplane v2.x)

Создание XRD (`CompositeResourceDefinition`):

```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: xpostgresdatabases.database.internal.corp
spec:
  group: database.internal.corp
  names:
    kind: XPostgresDatabase
    plural: xpostgresdatabases
  claimNames:
    kind: PostgresDatabaseClaim
    plural: postgresdatabaseclaims
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
              required: [dbName]
              properties:
                dbName:
                  type: string
                  description: "Имя создаваемой базы данных и префикс пользователя"
```

Манифест Composition с Pipeline-функциями (`function-patch-and-transform` и `function-auto-ready`):

```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: onprem-postgres-pipeline
  labels:
    provider: sql
spec:
  compositeTypeRef:
    apiVersion: database.internal.corp/v1alpha1
    kind: XPostgresDatabase
  mode: Pipeline
  pipeline:
    - step: patch-and-transform
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          # 1. Физическая база данных
          - name: postgresql-database
            base:
              apiVersion: postgresql.sql.crossplane.io/v1alpha1
              kind: Database
              spec:
                providerConfigRef:
                  name: postgres-shared-cluster
                forProvider:
                  encoding: "UTF8"
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: spec.dbName
                toFieldPath: metadata.name
          # 2. Изолированный пользователь
          - name: postgresql-role
            base:
              apiVersion: postgresql.sql.crossplane.io/v1alpha1
              kind: Role
              spec:
                providerConfigRef:
                  name: postgres-shared-cluster
                forProvider:
                  login: true
                  superuser: false
                writeConnectionSecretToRef:
                  namespace: crossplane-system
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: spec.dbName
                toFieldPath: metadata.name
              - type: FromCompositeFieldPath
                fromFieldPath: spec.dbName
                toFieldPath: spec.writeConnectionSecretToRef.name
                transforms:
                  - type: string
                    string:
                      fmt: "%s-db-creds"
          # 3. Выдача привилегий
          - name: postgresql-grant
            base:
              apiVersion: postgresql.sql.crossplane.io/v1alpha1
              kind: Grant
              spec:
                providerConfigRef:
                  name: postgres-shared-cluster
                forProvider:
                  privileges:
                    - ALL
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: spec.dbName
                toFieldPath: metadata.name
              - type: FromCompositeFieldPath
                fromFieldPath: spec.dbName
                toFieldPath: spec.forProvider.database
              - type: FromCompositeFieldPath
                fromFieldPath: spec.dbName
                toFieldPath: spec.forProvider.role
    - step: auto-ready
      functionRef:
        name: function-auto-ready
```

#### 4.3 Claim внутри Helm-чарта приложения

В манифесте чарта приложения объявляется Claim:

```yaml
apiVersion: database.internal.corp/v1alpha1
kind: PostgresDatabaseClaim
metadata:
  name: preview-db
  namespace: {{ .Release.Namespace }}
spec:
  dbName: {{ .Values.infrastructure.database.instanceName | replace "-" "_" }}
  writeConnectionSecretToRef:
    name: db-connection-secret
```

Приложение монтирует стандартный Kubernetes Secret `db-connection-secret`, в котором содержатся `endpoint`, `port`, `username` и сгенерированный `password`.

---

### Сценарий 5: Автоматизация On-Premise DNS (RFC2136) и Wildcard TLS

В локальной сети для динамических сред разворачивается Wildcard DNS (`*.preview.internal.corp`), либо используется связка `ExternalDNS` с локальным BIND9 / PowerDNS сервером через протокол RFC2136.

#### 5.1 Настройка ExternalDNS для BIND9 / PowerDNS (RFC2136)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: external-dns-rfc2136
  namespace: kube-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: external-dns-rfc2136
  template:
    metadata:
      labels:
        app: external-dns-rfc2136
    spec:
      containers:
        - name: external-dns
          image: registry.k8s.io/external-dns/external-dns:v0.14.2
          args:
            - --source=ingress
            - --provider=rfc2136
            - --rfc2136-host=dns-master.internal.corp
            - --rfc2136-port=53
            - --rfc2136-zone=preview.internal.corp
            - --rfc2136-tsig-secret-alg=hmac-sha256
            - --rfc2136-tsig-keyname=k8s-preview-key
            - --rfc2136-tsig-secret=yvd...TSIG_KEY...==
            - --rfc2136-tsig-axfr
            - --domain-filter=preview.internal.corp
            - --txt-owner-id=k8s-preview-cluster
```

#### 5.2 Wildcard TLS сертификат от внутреннего CA

Для preview-окружений выпуск индивидуальных сертификатов на каждый MR неэффективен. Оптимальное решение — единый Wildcard сертификат, выпускаемый cert-manager:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: wildcard-preview-tls
  namespace: ingress-nginx
spec:
  secretName: wildcard-preview-tls-cert
  issuerRef:
    name: corporate-vault-issuer # Или Step-CA / Local Root CA
    kind: ClusterIssuer
  dnsNames:
    - "*.preview.internal.corp"
    - "preview.internal.corp"
```

Ingress-контроллер настраивается на использование `wildcard-preview-tls-cert` в качестве `default-ssl-certificate`, освобождая разработчиков от необходимости конфигурировать TLS в каждом Helm-чарте.

---

### Сценарий 6: SRE-защита кластера: Quotas, Limits и PriorityClass

Динамические окружения несут прямую угрозу отказоустойчивости production-нагрузок при неконтролируемом росте открытых MR. В on-premise кластерах обязательны три рубежа защиты:

#### 6.1 PriorityClass с низким приоритетом (Preemption)

Preview-поды должны иметь низкий приоритет, позволяя планировщику K8s вытеснять (preempt) их при нехватке ресурсов для production:

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: preview-low-priority
value: 1000
preemptionPolicy: Never # Не могут вытеснять другие поды
globalDefault: false
description: "Приоритет для временных Review Apps"
```

#### 6.2 Шаблон ResourceQuota и LimitRange

Каждое сгенерированное пространство имен ограничивается жесткой квотой:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: preview-compute-quota
  namespace: {{ .Release.Namespace }}
spec:
  hard:
    requests.cpu: "1"
    requests.memory: "2Gi"
    limits.cpu: "4"
    limits.memory: "8Gi"
    count/pods: "15"
    count/services: "10"
    count/persistentvolumeclaims: "0" # Запрет создания локальных PVC (stateless)
---
apiVersion: v1
kind: LimitRange
metadata:
  name: preview-limits
  namespace: {{ .Release.Namespace }}
spec:
  limits:
    - type: Container
      default:
        cpu: 250m
        memory: 512Mi
      defaultRequest:
        cpu: 100m
        memory: 128Mi
      max:
        cpu: "2"
        memory: "4Gi"
```

---

### Сценарий 7: Сетевая изоляция через NetworkPolicy

По соображениям информационной безопасности preview-окружение должно быть изолировано от других веток и корпоративных VLAN:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: preview-isolation-policy
  namespace: {{ .Release.Namespace }}
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Разрешить вход только от Ingress-контроллера
    - from:
        - namespaceSelector:
            matchLabels:
              app.kubernetes.io/name: ingress-nginx
      ports:
        - port: 8080
          protocol: TCP
  egress:
    # Разрешить DNS
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    # Разрешить подключение к shared PostgreSQL кластеру
    - to:
        - ipBlock:
            cidr: 192.168.10.50/32 # IP адрес PostgreSQL HA
      ports:
        - port: 5432
          protocol: TCP
    # Запретить доступ к другим preview-неймспейсам
```

---

### Сценарий 8: Управление секретами через External Secrets Operator (ESO)

Секреты для динамических сред (ключи шифрования, токены сервисов) извлекаются из корпоративного HashiCorp Vault:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: preview-app-secrets
  namespace: {{ .Release.Namespace }}
spec:
  refreshInterval: "1h"
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: app-runtime-secrets
    creationPolicy: Owner
  data:
    - secretKey: JWT_SECRET
      remoteRef:
        key: secret/data/preview/common
        property: jwt_secret
```

---

### Сценарий 9: Интеграция с GitLab CI Pipeline

Пайплайн `.gitlab-ci.yml` регистрирует среду в GitLab, позволяя инженерам видеть кнопку перехода в окружение прямо в интерфейсе Merge Request:

```yaml
stages:
  - build
  - review
  - stop-review

variables:
  HARBOR_REGISTRY: "harbor.internal.corp/fintech/billing"
  PREVIEW_HOST: "mr-${CI_MERGE_REQUEST_IID}.preview.internal.corp"

build_preview_image:
  stage: build
  script:
    - docker build -t ${HARBOR_REGISTRY}:mr-${CI_MERGE_REQUEST_IID}-${CI_COMMIT_SHORT_SHA} .
    - docker push ${HARBOR_REGISTRY}:mr-${CI_MERGE_REQUEST_IID}-${CI_COMMIT_SHORT_SHA}
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

deploy_review:
  stage: review
  script:
    - echo "Preview environment generated via Argo CD ApplicationSet for MR !${CI_MERGE_REQUEST_IID}"
    - echo "Endpoint URL: https://${PREVIEW_HOST}"
  environment:
    name: review/mr-${CI_MERGE_REQUEST_IID}
    url: https://${PREVIEW_HOST}
    on_stop: stop_review
    auto_stop_in: 3 days # Автоматический stop в GitLab через 72 часа
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

stop_review:
  stage: stop-review
  variables:
    GIT_STRATEGY: none
  script:
    - echo "Stopping environment for MR !${CI_MERGE_REQUEST_IID}..."
  environment:
    name: review/mr-${CI_MERGE_REQUEST_IID}
    action: stop
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      when: manual
```

---

## Операции и команды

Справочник базовых операций инженера DevOps/SRE:

| Операция | Команда | Назначение |
| :--- | :--- | :--- |
| **Список всех preview apps** | `argocd app list -l managed-by=applicationset` | Просмотр статусов синхронизации и здоровья сгенерированных приложений |
| **Логи контроллера ApplicationSet** | `kubectl -n argocd logs deploy/argocd-applicationset-controller -f --tail=100` | Отладка опроса GitLab API и процесса рендеринга шаблонов |
| **Проверка статуса Crossplane Claim** | `kubectl get postgresdatabaseclaims -A` | Контроль готовности выделенных баз данных |
| **Проверка сгенерированных MR** | `kubectl get managed -l crossplane.io/claim-namespace=preview-mr-104` | Просмотр низкоуровневых объектов Crossplane |
| **Ручной триггер сверки ApplicationSet** | `kubectl -n argocd annotate applicationset preview-pull-requests argocd.argoproj.io/refresh=now --overwrite` | Принудительный опрос GitLab без ожидания таймаута |

### Примеры команд с ожидаемым выводом

```bash
# 1. Проверка активных preview-приложений в Argo CD
argocd app list -l environment=preview
# → NAME                   CLUSTER                         NAMESPACE         STATUS  HEALTH   AUTO
# → preview-app-mr-104     https://kubernetes.default.svc  preview-mr-104    Synced  Healthy  y
# → preview-app-mr-105     https://kubernetes.default.svc  preview-mr-105    Synced  Healthy  y

# 2. Проверка статуса базы данных в Crossplane
kubectl get postgresdatabaseclaims -n preview-mr-104
# → NAME         SYNCED   READY   CONNECTION-SECRET       AGE
# → preview-db   True     True    db-connection-secret    4m12s

# 3. Проверка созданных managed-ресурсов provider-sql
kubectl get database,role,grant -l crossplane.io/claim-name=preview-db
# → NAME                                                   READY   SYNCED   AGE
# → database.postgresql.sql.crossplane.io/mr_104_db        True    True     4m10s
# → role.postgresql.sql.crossplane.io/mr_104_user          True    True     4m8s
# → grant.postgresql.sql.crossplane.io/mr_104_grant        True    True     4m5s

# 4. Проверка Ingress и DNS
kubectl get ingress -n preview-mr-104
# → NAME         CLASS   HOSTS                             ADDRESS         PORTS     AGE
# → app-mr-104   nginx   mr-104.preview.internal.corp      192.168.10.20   80, 443   4m20s
```

---

## Диагностика и устранение неполадок

| Симптом / Ошибка | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| `failed to get pull requests: 429 Too Many Requests` | Исчерпан лимит запросов к GitLab API из-за частых опросов | `kubectl -n argocd logs deploy/argocd-applicationset-controller \| grep 429` | Увеличить `requeueAfterSeconds` до 300+ или настроить получение GitLab Webhooks в Argo CD |
| `Namespace "preview-mr-..." stuck in Terminating` | Зависшие финализаторы Crossplane из-за недоступности PostgreSQL | `kubectl get ns preview-mr-104 -o jsonpath='{.spec.finalizers}'` | Проверить сетевую доступность СУБД; при аварии вручную снять финализатор с MR: `kubectl patch <resource> -p '{"metadata":{"finalizers":[]}}' --type=merge` |
| `Crossplane: cannot create database: connection refused` | `ProviderConfig` указывает на недоступный хост/порт или неверный Secret | `kubectl describe database <db-name>` | Проверить DNS-имя СУБД, параметры `sslMode`, актуальность пароля в Secret `postgres-admin-creds` |
| `ApplicationSet generation failed: template: ... function "trunc" not defined` | Включен устаревший движок fasttemplate вместо `goTemplate` | `kubectl -n argocd describe applicationset <name>` | Добавить в спецификацию `spec.goTemplate: true` |
| `RFC2136 TSIG error: BADKEY / BADSIG` | Рассинхронизация времени или неверный TSIG secret в ExternalDNS | `kubectl -n kube-system logs deploy/external-dns-rfc2136 \| grep TSIG` | Синхронизировать NTP на всех узлах и DNS-сервере; перепроверить алгоритм хеширования (HMAC-SHA256) |
| `ResourceQuota exceeded: forbidden: exceeded quota: preview-compute-quota` | Pod запрашивает больше CPU/RAM, чем выделено квотой | `kubectl describe resourcequota preview-compute-quota -n preview-mr-104` | Оптимизировать Helm values приложения, снизив requests/limits для тестового контура |
| `Storage leak: PVCs left behind after namespace deletion` | Использование Stateful-нагрузок со storage-классом `reclaimPolicy: Retain` | `kubectl get pv \| grep Released` | Перевести storage-классы для preview в режим `reclaimPolicy: Delete`, либо использовать stateless-архитектуру |

---

## Рекомендации и Best Practices

### 1. Архитектурные рекомендации SRE и Sysadmin

1. **Используйте pullRequest генератор вместо scmProvider:** Открытие окружений только для реальных Merge Request с меткой `deploy-preview` экономит до 80% мощностей по сравнению с генерацией на каждую Git-ветку.
2. **Stateless Preview-нагрузки:** Запрещайте создание `PersistentVolumeClaim` внутри preview-неймспейсов (`count/persistentvolumeclaims: "0"` в ResourceQuota). Все данные должны храниться либо в shared PostgreSQL, либо во временных `emptyDir`. Это гарантирует мгновенное удаление окружений без зависания отмонтирования SAN/CSI дисков.
3. **Общие ресурсы СУБД (Shared Instances):** Создание виртуальных машин или отдельных подов БД под каждый MR перегружает IOPS дисковой подсистемы. Схема с `provider-sql` (создание логической схемы/БД на существующем кластере) отрабатывает за 2–3 секунды против 5–10 минут при развертывании отдельного экземпляра.
4. **Безопасность сетевого контура:** Обязательно блокируйте трафик между соседними preview-окружениями с помощью default-deny NetworkPolicy. Превью не должно иметь доступа к базам данных production-контура.
5. **Wildcard DNS и SSL:** Используйте единую DNS-запись `*.preview.internal.corp` на VIP-адрес балансировщика Ingress и единый Wildcard сертификат. Это устраняет задержки ожидания выпуска сертификатов и распространения DNS-записей.

### 2. Автоматическая очистка заброшенных окружений (TTL Garbage Collection)

Для очистки забытых сред, авторы которых ушли в отпуск или забросили MR, в кластере настраивается `CronJob`, удаляющий пространства имен старше 72 часов:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: preview-ttl-cleanup
  namespace: argocd
spec:
  schedule: "0 */4 * * *" # Каждые 4 часа
  successfulJobsHistoryLimit: 1
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: preview-cleaner-sa
          restartPolicy: OnFailure
          containers:
            - name: cleaner
              image: bitnami/kubectl:latest
              command:
                - /bin/bash
                - -c
                - |
                  set -eo pipefail
                  MAX_AGE_SEC=259200 # 72 часа
                  NOW=$(date +%s)
                  
                  kubectl get ns -l managed-by=applicationset -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.creationTimestamp}{"\n"}{end}' | \
                  while read -r ns created; do
                    [ -z "$ns" ] && continue
                    CREATED_SEC=$(date -d "$created" +%s)
                    AGE=$((NOW - CREATED_SEC))
                    if [ $AGE -gt $MAX_AGE_SEC ]; then
                      echo "Namespace $ns age is $AGE sec (> $MAX_AGE_SEC). Triggering deletion..."
                      kubectl delete ns "$ns" --timeout=60s || true
                    fi
                  done
```

---

## Дополнительная информация и ссылки

- [ApplicationSet — генераторы приложений и автоматизация флота](./argocd_applicationsets.md) — Детальное описание всех типов генераторов, шаблонизации и Progressive Syncs.
- [Установка и настройка Argo CD](./argocd_installation_and_setup.md) — Базовое развертывание hub-кластера Argo CD.
- [RBAC — модель доступа](./argocd_rbac_deep.md) — Разграничение прав и Casbin-политики.
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — Настройка квот и ограничений для проекта `preview-apps`.
- [Crossplane: Обзор](../Crossplane/overview.md) — Архитектура Crossplane, XRD, Compositions и Functions.
- [Crossplane: Интеграция с GitOps](../Crossplane/gitops_integration.md) — Паттерны совместной работы Crossplane и Argo CD.
- [Crossplane: Настройка provider-kubernetes](../Crossplane/provider_kubernetes_setup.md) — Оркестрация объектов Kubernetes через Crossplane.
- [Документация Argo CD ApplicationSet: Pull Request Generator](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Generators-Pull-Request/)
- [Документация Crossplane: Provider SQL](https://github.com/crossplane-contrib/provider-sql)
