# Crossplane: Настройка с провайдером Yandex Cloud

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); crossplane-provider-yc v0.14.x–v0.15.x; Kubernetes 1.28–1.32+

---

## Определения

**provider-yandex-cloud** (`crossplane-provider-yc`, `provider-jet-yc`) — официальный Crossplane-провайдер для Yandex Cloud (пакет `xpkg.upbound.io/yandexcloud/crossplane-provider-yc`), построенный на базе кодогенератора Upjet. Провайдер превращает Kubernetes в централизованную плоскость управления (Control Plane), позволяя декларативно развертывать вычислительные узлы (Compute), виртуальные сети (VPC), управляемые базы данных (MDB), объектные хранилища (S3/Storage), политики доступа (IAM) и каталоги (Resource Manager) через Kubernetes Custom Resources.

**Upjet (бывший Terrajet)** — фреймворк от Upbound для автоматической генерации CRD и Go-контроллеров Crossplane на базе Terraform-провайдеров (`terraform-provider-yandex`). Выполняет трансляцию вызовов Kubernetes API в операции Terraform CLI/SDK, управляет состоянием и транслирует вычисляемые атрибуты целевой инфраструктуры обратно в поля `status.atProvider`.

**Managed Resource (MR)** — низкоуровневый управляемый ресурс Kubernetes (CRD в группе `*.yandex-cloud.jet.crossplane.io`), представляющий конкретную сущность инфраструктуры Yandex Cloud (например, `ComputeInstance`, `Subnet`, `Network`, `SecurityGroup`, `Cluster` MDB).

**ProviderConfig** — конфигурационный ресурс (`kind: ProviderConfig`), определяющий глобальные параметры подключения провайдера к облачной платформе: идентификатор облака по умолчанию (`cloudId`), идентификатор каталога (`folderId`), эндпоинты API и ссылку на Kubernetes Secret с авторизованным ключом сервисного аккаунта.

**DeploymentRuntimeConfig** — ресурс расширения среды выполнения Crossplane v1.14+ и v2.x (`pkg.crossplane.io/v1beta1`), позволяющий SRE и системным администраторам декларативно настраивать Deployment пода провайдера: лимиты CPU/Memory, переменные окружения, прокси-серверы, аргументы запуска контроллера и политики безопасности (`securityContext`). Пришел на смену устаревшему `ControllerConfig`.

**Server-Side Apply (SSA)** — нативный механизм применения манифестов Kubernetes API, при котором вычисление различий и слияние конфигураций происходят на стороне `kube-apiserver`. Предотвращает конфликты менеджеров полей между GitOps-агентом (Argo CD) и контроллером Crossplane.

**Management Policies (`spec.managementPolicies`)** — гранулярный список операций жизненного цикла (`["*"]`, `["Create", "Update"]`, `["Observe"]`), разрешенных контроллеру Crossplane над облачным ресурсом. Позволяет организовывать безопасный аудит существующей инфраструктуры без риска непреднамеренного изменения или удаления.

**DeletionPolicy (`spec.deletionPolicy`)** — директива защиты ресурсов при удалении манифеста из кластера. Значение `Delete` (по умолчанию) отправляет API-запрос на физическое удаление ресурса в Yandex Cloud. Значение `Orphan` удаляет только Kubernetes MR, сохраняя реальный объект в облаке («осиротение»).

**External-Name (`crossplane.io/external-name`)** — аннотация Kubernetes, хранящая уникальный идентификатор ресурса в облаке (например, ID виртуальной машины или ID подсети). Служит якорным маркером для привязки существующих объектов (brownfield import) и восстановления после аварий.

**Connection Secret (`spec.writeConnectionSecretToRef`)** — механизм безопасного экспорта чувствительных данных (паролей баз данных, приватных ключей, реквизитов подключения), генерируемых провайдером при создании ресурса, в отдельный Kubernetes Secret в заданном пространстве имен.

---

## Базовые концепции и архитектура

### Архитектура Upjet-провайдера и плоскости управления

Crossplane Control Plane интегрирует GitOps-конвейер компании с облачной инфраструктурой Yandex Cloud без необходимости хранения стейт-файлов на файловых серверах или в Terraform Cloud:

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        KUBERNETES CONTROL PLANE                                 │
│                                                                                 │
│   GitOps (Argo CD / Flux) ────▶ kube-apiserver                                  │
│                                       │                                         │
│                      ┌────────────────┴────────────────┐                        │
│                      ▼                                 ▼                        │
│             Composite Resource (XR)         ProviderConfig (default)            │
│                      │                                 │                        │
│                      ▼                                 ▼                        │
│          Managed Resource (MR, ComputeInstance) ──▶ Secret (yc-creds)           │
│                      │                                 │                        │
│                      ▼                                 ▼                        │
│         ┌─────────────────────────────────────────────────────────────┐         │
│         │         crossplane-provider-yc Pod (crossplane-system)      │         │
│         │                                                             │         │
│         │  ┌────────────────────────┐     ┌────────────────────────┐  │         │
│         │  │ controller-runtime     │────▶│ Upjet Runtime Bridge   │  │         │
│         │  │ (Reconciliation Loop)  │     │ (terraform-provider-yc)│  │         │
│         │  └────────────────────────┘     └───────────┬────────────┘  │         │
│         └─────────────────────────────────────────────┼───────────────┘         │
└───────────────────────────────────────────────────────┼─────────────────────────┘
                                                        │ gRPC / HTTPS :443
                                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                 YANDEX CLOUD                                    │
│                                                                                 │
│   iam.api.cloud.yandex.net      compute.api.cloud.yandex.net      vpc.api...    │
│   ┌──────────────────────┐      ┌──────────────────────────┐      ┌───────────┐ │
│   │ IAM Service Account  │      │ Compute Instance (VM)    │      │ VPC Subnet│ │
│   │ Access Bindings      │      │ Disks, Snapshots, Images │      │ SecGroups │ │
│   └──────────────────────┘      └──────────────────────────┘      └───────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Цикл реконсиляции (Reconciliation Loop)

Контроллер `provider-yandex-cloud` выполняется в пространстве имен `crossplane-system` и непрерывно выполняет цикл синхронизации состояния:

1. **Observe (Наблюдение):** Контроллер опрашивает API Yandex Cloud через SDK/Terraform Bridge, проверяя существование ресурса по внешнему идентификатору (`crossplane.io/external-name`). Если ресурс найден, его фактические параметры считываются и записываются в `status.atProvider`.
2. **Late-Initialization (Поздняя инициализация):** Если облачный ресурс вернул значения полей, не заданные явно в `spec.forProvider` (например, автоматически назначенный приватный IP-адрес, шлюз по умолчанию или тип диска), контроллер обновляет манифест MR в кластере, сохраняя консистентность.
3. **Drift Detection & Update (Сверка дрейфа и обновление):** Если обнаружено расхождение между декларативной спецификацией `spec.forProvider` и фактическим состоянием в облаке, контроллер выполняет мутирующий API-запрос к Yandex Cloud для устранения дрейфа.
4. **Create / Delete:** При создании ресурса контроллер вызывает создание объекта и проставляет аннотацию `crossplane.io/external-name` с полученным облачным ID. При удалении манифеста проверяется `spec.deletionPolicy`: если установлена `Delete`, вызывается деструкция в API облака; если `Orphan`, объект в облаке остается нетронутым, а финалайзер `finalizer.managedresource.crossplane.io` удаляется.

### Поддерживаемые группы API

CRD провайдера сгруппированы по доменам сервисов Yandex Cloud под общим корнем `yandex-cloud.jet.crossplane.io`:

| Домен API | Ключевые ресурсы (Kinds) | Назначение |
| :--- | :--- | :--- |
| `compute` | `ComputeInstance`, `ComputeDisk`, `ComputeImage`, `ComputeInstanceGroup` | Виртуальные машины, блочные устройства, пользовательские образы |
| `vpc` | `Network`, `Subnet`, `SecurityGroup`, `SecurityGroupRule`, `RouteTable` | Сетевая изоляция, маршрутизация, фильтрация сетевого трафика |
| `mdb` | `PostgresqlCluster`, `MysqlCluster`, `RedisCluster`, `KafkaCluster` | Управляемые базы данных и брокеры сообщений |
| `iam` | `ServiceAccount`, `ServiceAccountKey`, `ServiceAccountStaticAccessKey` | Идентификация, сервисные аккаунты, статичные ключи доступа |
| `storage` | `Bucket`, `BucketObject`, `BucketAcl` | S3-совместимые объектные хранилища |
| `resourcemanager`| `Cloud`, `Folder` | Иерархическая структура каталогов и облаков |

Проверка установленных групп CRD:
```bash
kubectl get crd | grep yandex-cloud.jet.crossplane.io
```

### Модель безопасности и аутентификации

Провайдер аутентифицируется в Yandex Cloud через авторизованный ключ сервисного аккаунта (Authorized Service Account Key).
- Авторизованный ключ представляет собой JSON-документ, содержащий идентификатор ключа (`id`), идентификатор сервисного аккаунта (`service_account_id`) и закрытый ключ в формате RSA/PEM (`private_key`).
- Провайдер читает этот JSON из Kubernetes Secret в пространстве имен `crossplane-system` и подписывает gRPC/REST-запросы к эндпоинтам `api.cloud.yandex.net`.
- **Принцип наименьших привилегий (Least Privilege):** Сервисный аккаунт провайдера не должен обладать административными правами на уровне всего облака (`admin` on Cloud). Права должны быть изолированы в рамках конкретного рабочего каталога (`folder-id`) с назначением специализированных ролей (`compute.admin`, `vpc.admin`, `mdb.admin`, `iam.serviceAccounts.user`).

---

## Практические сценарии и настройка

### Предварительные требования

* **Кластер Kubernetes:** Версия 1.28–1.32+ (Bare-Metal, On-Premise или Managed Service for Kubernetes).
* **Helm:** Версия 3.10+ с поддержкой OCI.
* **Yandex Cloud CLI (`yc`):** Установлен и настроен профиль администратора (`yc init`).
* **Утилиты Linux:** `kubectl`, `jq`, `curl`.

### Установка Crossplane Core

1. **Добавление официального Helm-репозитория:**
```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update
```

2. **Развертывание ядра Crossplane с поддержкой Server-Side Apply:**
```bash
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system \
  --create-namespace \
  --set args='{--enable-ssa-claims}'
```

3. **Проверка состояния контроллеров ядра:**
```bash
kubectl get pods -n crossplane-system
# → NAME                                       READY   STATUS    RESTARTS   AGE
#   crossplane-78487955c-k98xz                 1/1     Running   0          45s
#   crossplane-rbac-manager-67998b584b-v2x4r   1/1     Running   0          45s
```

### Настройка среды выполнения провайдера (DeploymentRuntimeConfig)

Для управления системными ресурсами пода провайдера, защиты от OOMKill и проброса сетевых настроек создается `DeploymentRuntimeConfig`:

```yaml
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: yc-provider-runtime
spec:
  deploymentTemplate:
    spec:
      replicas: 1
      template:
        spec:
          securityContext:
            runAsNonRoot: true
            runAsUser: 65532
          containers:
            - name: package-runtime
              resources:
                requests:
                  cpu: 200m
                  memory: 512Mi
                limits:
                  cpu: 1000m
                  memory: 2Gi
              env:
                - name: POLL_INTERVAL
                  value: 10m
```

Применение манифеста конфигурации среды:
```bash
kubectl apply -f yc-provider-runtime.yaml
# → result: deploymentruntimeconfig.pkg.crossplane.io/yc-provider-runtime created
```

### Установка провайдера Yandex Cloud

**Вариант А: Декларативный манифест `Provider` (Рекомендуется для GitOps):**

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-yandex-cloud
spec:
  package: xpkg.upbound.io/yandexcloud/crossplane-provider-yc:v0.14.1
  runtimeConfigRef:
    name: yc-provider-runtime
```

Применение манифеста провайдера:
```bash
kubectl apply -f provider.yaml
# → result: provider.pkg.crossplane.io/provider-yandex-cloud created
```

**Вариант Б: Установка через Crossplane CLI:**
```bash
crossplane xpkg install provider xpkg.upbound.io/yandexcloud/crossplane-provider-yc:v0.14.1 \
  --runtime-config-ref=yc-provider-runtime
```

**Вариант В: Установка из Yandex Cloud Marketplace (для Managed Kubernetes):**
В консоли Managed Service for Kubernetes выберите приложение «Crossplane с поддержкой Yandex Cloud». При развертывании через Helm из OCI-реестра Cloud Marketplace:
```bash
helm pull oci://cr.yandex/yc-marketplace/yandex-cloud/crossplane/charts/crossplane \
  --version 2.3.4+yc0.15.2 \
  --untar && \
helm install crossplane ./crossplane/ \
  --namespace crossplane-system \
  --create-namespace \
  --set-file providerJetYc.creds=sa-key.json
```

**Проверка статуса провайдера:**
```bash
kubectl get providers
# → NAME                    INSTALLED   HEALTHY   PACKAGE                                                       AGE
#   provider-yandex-cloud   True        True      xpkg.upbound.io/yandexcloud/crossplane-provider-yc:v0.14.1    60s
```

### Настройка IAM и безопасного хранения секретов

1. **Создание сервисного аккаунта с гранулярными правами в каталоге:**
```bash
# Получение текущего идентификатора каталога
FOLDER_ID=$(yc config get folder-id)

# Создание сервисного аккаунта для Crossplane
yc iam service-account create --name crossplane-infra-controller

# Получение ID созданного сервисного аккаунта
SA_ID=$(yc iam service-account get crossplane-infra-controller --format json | jq -r .id)

# Назначение гранулярных ролей на каталог (принцип наименьших привилегий)
for ROLE in compute.admin vpc.admin iam.serviceAccounts.user mdb.admin; do
  yc resource-manager folder add-access-binding "$FOLDER_ID" \
    --role "$ROLE" \
    --subject "serviceAccount:$SA_ID"
done
# → result: done (0.4s)
```

2. **Генерация авторизованного ключа:**
```bash
yc iam key create \
  --service-account-name crossplane-infra-controller \
  --output sa-key.json
# → result: id: aje... service_account_id: aje... created_at: ...
```

3. **Создание Kubernetes Secret в пространстве имен провайдера:**
```bash
kubectl create secret generic yc-creds \
  --namespace crossplane-system \
  --from-file=credentials=./sa-key.json
# → result: secret/yc-creds created

# Безопасное удаление локального файла ключа после импорта
shred -u sa-key.json
```

> **Безопасность в Production:** Для исключения передачи статических файлов ключей вручную используйте **External Secrets Operator (ESO)** в связке с HashiCorp Vault или Yandex Lockbox. ESO автоматически синхронизирует и ротирует секрет `yc-creds` непосредственно в namespace `crossplane-system`.

### Настройка ProviderConfig

Ресурс `ProviderConfig` связывает установленный провайдер с секретом авторизации и задает параметры по умолчанию:

```yaml
apiVersion: yandex-cloud.jet.crossplane.io/v1beta1
kind: ProviderConfig
metadata:
  name: default
spec:
  credentials:
    cloudId: b1gxxxxxxxxxxxxxxxxx   # ID облака по умолчанию
    folderId: b1gxxxxxxxxxxxxxxxxx  # ID каталога по умолчанию
    source: Secret
    secretRef:
      name: yc-creds
      namespace: crossplane-system
      key: credentials
```

Применение конфигурации:
```bash
kubectl apply -f providerconfig.yaml
# → result: providerconfig.yandex-cloud.jet.crossplane.io/default created
```

Проверка доступности:
```bash
kubectl get providerconfig
# → NAME      AGE
#   default   30s
```

### Декларативное развертывание инфраструктуры (VPC, Security Group, Compute)

Ниже представлен целостный пример инфраструктурного стека: изолированная сеть, подсеть, группа безопасности и виртуальная машина, инициализируемая через `cloud-init`.

#### 1. Сетевая инфраструктура (`vpc.yaml`)

```yaml
apiVersion: vpc.yandex-cloud.jet.crossplane.io/v1alpha1
kind: Network
metadata:
  name: prod-vpc-network
spec:
  deletionPolicy: Orphan
  forProvider:
    name: prod-vpc-network
  providerConfigRef:
    name: default
---
apiVersion: vpc.yandex-cloud.jet.crossplane.io/v1alpha1
kind: Subnet
metadata:
  name: prod-vpc-subnet-a
spec:
  deletionPolicy: Orphan
  forProvider:
    name: prod-vpc-subnet-a
    zone: ru-central1-a
    v4CidrBlocks:
      - 10.100.1.0/24
    networkIdRef:
      name: prod-vpc-network
  providerConfigRef:
    name: default
---
apiVersion: vpc.yandex-cloud.jet.crossplane.io/v1alpha1
kind: SecurityGroup
metadata:
  name: prod-web-secgroup
spec:
  deletionPolicy: Delete
  forProvider:
    name: prod-web-secgroup
    networkIdRef:
      name: prod-vpc-network
    ingress:
      - protocol: TCP
        port: 80
        v4CidrBlocks: ["0.0.0.0/0"]
      - protocol: TCP
        port: 443
        v4CidrBlocks: ["0.0.0.0/0"]
      - protocol: TCP
        port: 22
        v4CidrBlocks: ["10.0.0.0/8", "192.168.0.0/16"]
    egress:
      - protocol: ANY
        fromPort: 0
        toPort: 65535
        v4CidrBlocks: ["0.0.0.0/0"]
  providerConfigRef:
    name: default
```

#### 2. Вычислительный узел (`compute.yaml`)

```yaml
apiVersion: compute.yandex-cloud.jet.crossplane.io/v1beta1
kind: ComputeInstance
metadata:
  name: prod-web-server-01
spec:
  deletionPolicy: Delete
  forProvider:
    name: prod-web-server-01
    zone: ru-central1-a
    platformId: standard-v3
    resources:
      memory: 4G
      cores: 2
      coreFraction: 100
    bootDisk:
      initializeParams:
        imageId: fd80m5rnb5lsvj0s2k91 # Ubuntu 24.04 LTS
        size: 30G
        type: network-ssd
    networkInterfaces:
      - subnetIdRef:
          name: prod-vpc-subnet-a
        primaryV4Address: {}          # Назначение динамического публичного IP
        securityGroupIdsRefs:
          - name: prod-web-secgroup
    metadata:
      user-data: |
        #cloud-config
        package_update: true
        package_upgrade: true
        packages:
          - nginx
          - prometheus-node-exporter
        write_files:
          - content: |
              <!DOCTYPE html>
              <html>
              <body>
                <h1>Managed by Crossplane & GitOps</h1>
                <p>Node: prod-web-server-01</p>
              </body>
              </html>
            path: /var/www/html/index.html
        runcmd:
          - systemctl enable --now nginx
          - systemctl enable --now prometheus-node-exporter
  providerConfigRef:
    name: default
```

Применение манифестов:
```bash
kubectl apply -f vpc.yaml
# → result: network.vpc.yandex-cloud.jet.crossplane.io/prod-vpc-network created
# → result: subnet.vpc.yandex-cloud.jet.crossplane.io/prod-vpc-subnet-a created
# → result: securitygroup.vpc.yandex-cloud.jet.crossplane.io/prod-web-secgroup created

kubectl apply -f compute.yaml
# → result: computeinstance.compute.yandex-cloud.jet.crossplane.io/prod-web-server-01 created
```

Проверка статуса развертывания:
```bash
kubectl get managed
# → NAME                                                                      READY   SYNCED   AGE
#   network.vpc.yandex-cloud.jet.crossplane.io/prod-vpc-network               True    True     2m
#   subnet.vpc.yandex-cloud.jet.crossplane.io/prod-vpc-subnet-a               True    True     90s
#   securitygroup.vpc.yandex-cloud.jet.crossplane.io/prod-web-secgroup        True    True     60s
#   computeinstance.compute.yandex-cloud.jet.crossplane.io/prod-web-server-01 True    True     45s
```

### Интеграция с GitOps (Argo CD) и предотвращение дрейфа

При управлении Upjet-ресурсами через Argo CD возникает специфика: контроллер Upjet выполняет **Late-Initialization**, дописывая значения по умолчанию и вычисленные параметры непосредственно в `spec.forProvider`. Если Argo CD работает с политикой `selfHeal: true`, он будет воспринимать эти поля как дрейф и пытаться их перезаписать, вызывая бесконечную конкурентную сверку (reconciliation fight).

Для устранения конфликтов в манифесте `Application` настраивается секция `ignoreDifferences`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: yc-infrastructure-stack
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/my-org/infra-gitops.git
    targetRevision: main
    path: crossplane/environments/production
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ApplyOutOfSyncOnly=true
  ignoreDifferences:
    - group: "*.yandex-cloud.jet.crossplane.io"
      kind: "*"
      jsonPointers:
        - /spec/forProvider/id
        - /spec/initProvider
        - /metadata/annotations/crossplane.io~1external-name
```

### Импорт существующих ресурсов (Brownfield Adoption)

Для взятия под управление ресурсов, созданных вручную или через сторонний Terraform, без их пересоздания и даунтайма:

1. Получите ID ресурса в Yandex Cloud (например, каталог `Folder` или подсеть `Subnet`):
```bash
yc resource-manager folder get my-existing-folder --format json | jq -r .id
# → b1g2345678abcdef0123
```

2. Создайте манифест с аннотацией `crossplane.io/external-name` и политикой `managementPolicies: ["Observe"]`:

```yaml
apiVersion: resourcemanager.yandex-cloud.jet.crossplane.io/v1alpha1
kind: Folder
metadata:
  name: imported-folder
  annotations:
    crossplane.io/external-name: b1g2345678abcdef0123
spec:
  managementPolicies:
    - Observe
  forProvider:
    cloudId: b1g9876543210fedcba9
    name: my-existing-folder
  providerConfigRef:
    name: default
```

3. Убедитесь, что ресурс синхронизирован:
```bash
kubectl get folder.resourcemanager.yandex-cloud.jet.crossplane.io imported-folder
# → NAME              READY   SYNCED   AGE
#   imported-folder   True    True     25s
```

4. После сверки параметров спецификации с выводом `kubectl get folder imported-folder -o yaml` политику можно безопасно расширить до полного управления:
```yaml
  managementPolicies:
    - "*"
```

### Защита критической инфраструктуры (Deletion Policies)

По умолчанию при удалении манифеста MR из Kubernetes контроллер вызывает физическое удаление объекта в облаке. Для ключевых инфраструктурных элементов (сети, каталоги, подсети, диски баз данных) установите:

```yaml
spec:
  deletionPolicy: Orphan
```

* Если такой манифест будет случайно удален из Git или через `kubectl delete`, объект в Yandex Cloud останется активным.
* В Kubernetes удалится только обертка MR.

---

## Операции и команды (Day-2 Operations)

| Операция | Команда | Назначение |
| :--- | :--- | :--- |
| **Список всех MR** | `kubectl get managed` | Отображение статусов `READY` и `SYNCED` всех облачных ресурсов |
| **Инспекция ВМ** | `kubectl get computeinstance -o wide` | Просмотр сетевых IP, зон и статусов реконсиляции |
| **Детальная диагностика** | `kubectl describe computeinstance <name>` | Анализ секций `Status.Conditions` и последних Kubernetes Events |
| **Заморозка сверки** | `kubectl annotate managed <name> crossplane.io/paused="true"` | Экстренная остановка опроса и изменений ресурса провайдером |
| **Возобновление сверки**| `kubectl annotate managed <name> crossplane.io/paused-` | Снятие паузы и возврат ресурса в штатный цикл реконсиляции |
| **Трассировка Crossplane**| `crossplane beta trace computeinstance <name>` | Построение графа зависимостей и выявление блокировок условий |
| **Логи провайдера** | `kubectl -n crossplane-system logs -l pkg.crossplane.io/provider=provider-yandex-cloud -c package-runtime -f` | Мониторинг системных gRPC-вызовов и ответов Terraform Bridge |
| **Принудительное удаление**| `kubectl patch managed <name> -p '{"metadata":{"finalizers":[]}}' --type=merge` | Аварийный сброс финалайзера при зависании удаления (требует ручной очистки в облаке) |

---

## Диагностика и устранение неполадок (Troubleshooting)

### Матрица типовых неисправностей

| Симптом | Вероятная причина | Диагностика / Решение |
| :--- | :--- | :--- |
| `ProviderConfig` не переходит в `Healthy` | Ошибка структуры Secret `yc-creds` или неверный ключ JSON | Выполнить `kubectl -n crossplane-system get secret yc-creds -o jsonpath='{.data.credentials}' \| base64 -d \| jq .`. Убедиться в наличии полей `id`, `service_account_id`, `private_key`. |
| Ресурс зависает в `Ready=False, Synced=False` | Недостаточно прав у SA или превышена квота каталога | Проверить `kubectl describe <kind> <name>`. При ошибке `403 Permission Denied` выдать сервисному аккаунту требуемую роль через `yc resource-manager folder add-access-binding`. |
| Ошибка `Resource Exhausted` (HTTP 429) | Превышен лимит запросов к gRPC API Yandex Cloud | Увеличить `POLL_INTERVAL` в `DeploymentRuntimeConfig` (например, с `1m` до `10m`). Уменьшить параллелизм воркеров. |
| Ресурс удален из Git, но `kubectl delete` висит бесконечно | Дочерние ресурсы не отвязаны (например, подсеть содержит IP или ВМ) | Проверить зависимости: `yc vpc subnet list-used-addresses --id <subnet-id>`. Удалить зависимые ресурсы в облаке перед удалением подсети. |
| Argo CD бесконечно показывает статус `OutOfSync` | Конфликт полей между Late-Initialization и манифестом Git | Добавить `ignoreDifferences` для полей `/spec/forProvider/id` и `/spec/initProvider` в манифесте `Application`. |
| Под провайдера в `CrashLoopBackOff` (OOMKilled) | Недостаточно оперативной памяти при загрузке сотен CRD | Проверить `kubectl -n crossplane-system describe pod -l pkg.crossplane.io/provider=provider-yandex-cloud`. Увеличить `limits.memory` до `2Gi`–`4Gi` в `DeploymentRuntimeConfig`. |
| Не удается разрешить DNS API облака | Ограничения NetworkPolicy или сбой CoreDNS | Проверить доступность: `kubectl run debug --rm -it --image=curlimages/curl -- curl -Iv https://api.cloud.yandex.net`. Настроить Egress NetworkPolicy. |

### Разбор критических сбоев

#### 1. Аварийный сброс застрявших финалайзеров (Stuck Finalizers)

При удалении ресурса, если облачный API недоступен или учетные данные были отозваны, Crossplane блокирует удаление объекта из etcd с помощью финалайзера `finalizer.managedresource.crossplane.io`:

```bash
# Диагностика блокировки
kubectl get computeinstance prod-web-server-01 -o jsonpath='{.metadata.finalizers}'
# → ["finalizer.managedresource.crossplane.io"]

# Если физический ресурс в Yandex Cloud уже удален вручную, снимите финалайзер:
kubectl patch computeinstance prod-web-server-01 \
  --type=merge \
  -p '{"metadata":{"finalizers":null}}'
# → result: computeinstance.compute.yandex-cloud.jet.crossplane.io/prod-web-server-01 patched
```

#### 2. Ошибки несовместимости версий ревизии (ProviderRevision)

При обновлении пакета провайдера старая ревизия может конфликтовать с новой:
```bash
kubectl get providerrevisions
# → NAME                                   HEALTHY   REVISION   IMAGE                                                        STATE
#   provider-yandex-cloud-8b9a2c3d4e       True      1          xpkg.upbound.io/yandexcloud/crossplane-provider-yc:v0.14.1   Active
#   provider-yandex-cloud-f1e2d3c4b5       False     2          xpkg.upbound.io/yandexcloud/crossplane-provider-yc:v0.15.2   Inactive

# Детальный просмотр ошибки ревизии
kubectl describe providerrevision provider-yandex-cloud-f1e2d3c4b5
```

---

## Лучшие практики (Best Practices)

### Надежность и SRE (Site Reliability Engineering)

1. **Мониторинг метрик контроллера через Prometheus:**
   Провайдер экспортирует системные метрики `controller-runtime` на порту `:8080`. Настройте сбор метрик с помощью `PodMonitor`:

   ```yaml
   apiVersion: monitoring.coreos.com/v1
   kind: PodMonitor
   metadata:
     name: provider-yandex-cloud-monitor
     namespace: crossplane-system
   spec:
     selector:
       matchLabels:
         pkg.crossplane.io/provider: provider-yandex-cloud
     podMetricsEndpoints:
       - port: metrics
         interval: 30s
   ```

2. **Ключевые SLI / PromQL метрики для алертинга:**
   * **Частота ошибок реконсиляции:**
     ```promql
     sum(rate(controller_runtime_reconcile_errors_total{controller=~".*yandex-cloud.*"}[5m]))
       /
     sum(rate(controller_runtime_reconcile_total{controller=~".*yandex-cloud.*"}[5m])) > 0.05
     ```
   * **Длительно несинхронизированные ресурсы (Unsynced MRs):**
     ```promql
     sum(crossplane_managed_resource_ready{group=~".*yandex-cloud.*", status="False"}) > 0
     ```

3. **Защита от исчерпания квот API (Rate Limiting & Polling):**
   По умолчанию контроллеры опрашивают облачный API с интервалом в 1 минуту. В средних и крупных инсталляциях (более 100 MR) это вызывает троттлинг API Yandex Cloud.
   * Увеличьте интервал опроса через флаг `--poll-interval=10m` в аргументах запуска контейнера.
   * Для ресурсов, не требующих частого контроля дрейфа (архивные бакеты, статические сети), используйте аннотацию `crossplane.io/paused: "true"`.

### Системное администрирование и безопасность (Sysadmin & Security)

1. **Сетевая изоляция через NetworkPolicy:**
   Ограничьте исходящий трафик пода провайдера только необходимыми эндпоинтами Yandex Cloud и DNS:

   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: provider-yc-egress-lockdown
     namespace: crossplane-system
   spec:
     podSelector:
       matchLabels:
         pkg.crossplane.io/provider: provider-yandex-cloud
     policyTypes:
       - Egress
     egress:
       # Разрешение DNS
       - to:
           - namespaceSelector: {}
             podSelector:
               matchLabels:
                 k8s-app: kube-dns
         ports:
           - protocol: UDP
             port: 53
           - protocol: TCP
             port: 53
       # Разрешение Kubernetes API
       - to:
           - ipBlock:
               cidr: 10.96.0.1/32 # ClusterIP kube-apiserver
         ports:
           - protocol: TCP
             port: 443
       # Разрешение публичных API Yandex Cloud
       - to:
           - ipBlock:
               cidr: 0.0.0.0/0
         ports:
           - protocol: TCP
             port: 443
   ```

2. **Регулярная ротация сервисных ключей:**
   * Срок жизни авторизованного ключа SA не должен быть бессрочным.
   * Настройте автоматическую ротацию ключа через CI/CD или скрипты администрирования: выпуск нового ключа `yc iam key create`, обновление Kubernetes Secret `yc-creds`, валидация статуса провайдера и последующий отзыв старого ключа `yc iam key delete`.

3. **Изоляция прав доступа к пространству имен `crossplane-system`:**
   * Доступ к `crossplane-system` должен быть строго ограничен платформенными инженерами. Обычные разработчики не должны иметь прав на чтение Secret `yc-creds` во избежание компрометации закрытого ключа облачной инфраструктуры.

### DevOps и автоматизация GitOps

1. **Многоуровневая структура репозиториев (Repository Layering):**
   * Разделяйте репозиторий платформы (Platform Repo: `Provider`, `DeploymentRuntimeConfig`, `ProviderConfig`) и репозитории прикладных команд (App Repos: Claims, MR виртуальных машин и баз данных).
2. **Селективное удаление и защита данных:**
   * Всегда объявляйте `spec.deletionPolicy: Orphan` для ресурсов хранения (`Bucket`, `ComputeDisk`, кластеры СУБД) во избежание необратимой утери данных при случайном удалении манифеста в Git.

---

## Дополнительная информация

### Смежные разделы базы знаний

* [Crossplane: Интеграция с GitOps](./gitops_integration.md) — совместная архитектура Crossplane, Argo CD и Flux, двухконтурная сверка.
* [Crossplane: Observability](./observability.md) — метрики, мониторинг, распределенная трассировка и алертинг для Crossplane.
* [Crossplane: Резервное копирование и Disaster Recovery](./backup_dr.md) — резервное копирование etcd, восстановление и защита от split-brain.
* [Crossplane: Управление ресурсами Kubernetes](./provider_kubernetes_setup.md) — мультикластерное управление через `provider-kubernetes`.
* [Crossplane: Безопасность пакетов](./package_security.md) — верификация OCI-пакетов через Cosign и безопасность рантайма.
* [Yandex Cloud: Обзор Resource Manager](../../Yandex/Resource_Manager/overview.md) — иерархия облаков, каталогов и прав.
* [Yandex Cloud: IAM роли](../../Yandex/Resource_Manager/iam_roles.md) — матрица ролей доступа сервисных аккаунтов.
* [Yandex Cloud: Compute Cloud](../../Yandex/Compute-Cloud.md) — виртуальные машины, диски и группы узлов.
* [Yandex Cloud: VPC](../../Yandex/VPC.md) — виртуальные частные сети, подсети и маршрутизация.

### Внешние источники

* [Официальный репозиторий провайдера Yandex Cloud для Crossplane (GitHub)](https://github.com/yandex-cloud/crossplane-provider-yc)
* [Пакет crossplane-provider-yc в Upbound Marketplace](https://marketplace.upbound.io/providers/yandexcloud/crossplane-provider-yc/latest)
* [Документация Yandex Cloud: Установка Crossplane в Managed Service for Kubernetes](https://yandex.cloud/ru/docs/managed-kubernetes/operations/applications/crossplane)
* [Документация Upjet Framework (Upbound)](https://github.com/crossplane/upjet)
* [Официальная документация Crossplane Control Plane](https://docs.crossplane.io/)
