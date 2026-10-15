# Crossplane: сравнение с Terraform и OpenTofu

**Актуально для:** Crossplane v2.4 (v2.x); OpenTofu v1.12.x; Terraform v1.15.x; On-Premise / Bare-Metal / Private Virtualization

---

## Определения

- **Crossplane** — открытая платформа оркестрации инфраструктуры (CNCF Graduated, Apache-2.0), расширяющая Kubernetes API и превращающая кластер в универсальный уровень управления (Control Plane). Функционирует по непрерывной pull-модели сверки (Reconciliation Loop): контроллеры постоянно опрашивают целевые локальные системы и приводят их фактическое состояние к декларативно описанному в `etcd`.
- **Terraform** — индустриальный стандарт управления инфраструктурой как кодом (IaC). После приобретения HashiCorp компанией IBM распространяется под лицензией BUSL-1.1 (source-available). Использует декларативный язык HCL, исполняется по событийной push-модели (`plan`/`apply`) и сохраняет слепок окружения в файле состояния (`.tfstate`). Актуальная стабильная линейка — **Terraform v1.15.x**; версии 1.10 и старше достигли EOL.
- **OpenTofu** — открытый форк Terraform под эгидой Linux Foundation (CNCF Sandbox, MPL 2.0). Полностью совместим с синтаксисом HCL и реестрами провайдеров, но развивает независимый функционал: нативное шифрование состояния (`state_encryption`) без внешних сервисов, эфемерные значения (`ephemeral`), мета-аргумент `enabled` для ресурсов и модулей, итерация `for_each` в блоках `provider`. Актуальная стабильная ветка — **OpenTofu v1.12.x**.
- **Push-модель (Plan/Apply Workflow)** — архитектурный подход, при котором исполняемый бинарный файл (CLI или CI-runner) запускается по событию (ручной ввод инженера, вебхук коммита в GitLab CI), читает конфигурацию, рассчитывает граф изменений (diff) и отправляет команды на модификацию целевых систем. В промежутках между запусками дрейф параметров не отслеживается.
- **Pull-модель (Continuous Reconciliation)** — архитектурный подход, при котором управляющий агент (контроллер внутри Kubernetes) непрерывно опрашивает внешние и внутренние API систем, вычисляет расхождение между манифестом в `etcd` и реальностью и автоматически устраняет дрейф (self-healing) без внешнего вмешательства.
- **Drift (Дрейф конфигурации)** — расхождение между зафиксированным в коде желаемым состоянием и фактическим состоянием системы, вызванное ручными правками администраторов, авариями или неучтенными внешними скриптами.
- **State Locking (Блокировка состояния)** — механизм предотвращения одновременной модификации инфраструктуры несколькими процессами. В Terraform/OpenTofu реализуется распределенной блокировкой на уровне бэкенда (Consul, MinIO/S3 Lock, GitLab HTTP mutex); в Crossplane обеспечивается атомарными транзакциями `etcd` и optimistic concurrency control (OCC) Kubernetes API.
- **CompositeResourceDefinition (XRD) и Composition** — средства абстракции Crossplane: XRD задает схему пользовательского API (OpenAPI v3), а Composition через конвейер Composition Functions (Go, Python, CEL) транслирует обобщенную заявку разработчика в набор конкретных низкоуровневых ресурсов (Managed Resources).
- **Tofu-Controller / TF-Controller** — Kubernetes-оператор для экосистемы Flux (`flux-iac/tofu-controller`), исполняющий HCL-модули внутри изолированных подов кластера в pull-режиме с автоматическим контролем дрейфа.

---

## Базовые концепции и архитектура

### Сравнительный анализ архитектур (On-Premise / Bare-Metal)

| Характеристика | Crossplane (v2.x, актуально v2.4) | OpenTofu (v1.12.x, актуально v1.12.6) | Terraform (v1.15.x, стабильная линия) |
| :--- | :--- | :--- | :--- |
| **Модель доставки изменений** | **Pull** (Continuous Reconciliation Loop) | **Push** (Plan/Apply по событию) | **Push** (Plan/Apply по событию) |
| **Среда выполнения** | Kubernetes Control Plane (поды контроллеров) | CLI / CI-CD Runner (GitLab CI, Jenkins) | CLI / CI-CD Runner (GitLab CI, Jenkins) |
| **Хранилище состояния (State)** | Распределенный `etcd` (встроен в ресурсы K8s) | Файл `.tfstate` в Remote Backend (MinIO, GitLab, Consul) | Файл `.tfstate` в Remote Backend (MinIO, GitLab, Consul) |
| **Детекция и устранение дрейфа** | **Автоматическое самовосстановление** (Self-healing) | Только при вызове `tofu plan` (или cron в CI) | Только при вызове `terraform plan` (или cron в CI) |
| **Управление логикой и шаблонами** | **Composition Functions** (Go, Python, CEL) | Язык HCL (условия, `for_each`, модули) | Язык HCL (условия, `for_each`, модули) |
| **Шифрование состояния at-rest** | Нативное в `etcd` (K8s EncryptionConfiguration) | **Нативное встроенное** (AES-GCM, PBKDF2, Vault, OpenBao) | Только внешнее (шифрование хранилища бэкенда) |
| **Управление секретами** | Secrets K8s, External Secrets Operator (ESO), Vault | Plaintext в `.tfstate`, переменные окружения CI | Plaintext в `.tfstate`, переменные окружения CI |
| **Периметр сетевого доступа** | Изнутри кластера к целевым системам ЦОД | Из CI-раннеров/бастионов ко всем целевым системам | Из CI-раннеров/бастионов ко всем целевым системам |
| **Лицензия** | Apache-2.0 (CNCF Graduated) | MPL-2.0 (CNCF Sandbox, Open Source) | BUSL-1.1 (Source-Available) |

### Альтернативные инструменты IaC: Pulumi и CUE

Помимо Terraform/OpenTofu в корпоративном On-Premise стеке иногда встречаются Pulumi и CUE. Оба решают задачу управления инфраструктурой, но иначе, чем Crossplane:

* **Pulumi** — IaC-платформа, использующая языки общего назначения (Go, Python, TypeScript, C#, Java) вместо HCL. Состояние хранится в бэкенде (S3, Consul, Pulumi Cloud) по push-модели `pulumi up`. Отличается от Terraform тем, что логика (условия, циклы, обращения к внешним API) пишется полноценным кодом, а не DSL. Для Crossplane релевантна как источник библиотек провайдеров и как инструмент L0/L1-фундамента, где требуется программная логика; не предоставляет нативного reconciliation loop (дрейф обнаруживается только при `pulumi refresh`/`up`).
* **CUE** — язык конфигурации и генерации данных (экспрессивная схема + данные + вычисления), используемый для валидации и генерации манифестов Kubernetes. Не является полным IaC-движком (нет встроенного state и планировщика изменений) и позиционируется как слой конфигурационной логики. В экосистеме Crossplane есть `function-cel` (Common Expression Language), близкий по духу к CUE для декларативных выражений внутри Composition; CUE может использоваться на этапе CI для генерации/валидации XR-манифестов, но не заменяет Crossplane как reconciliation control plane.

| Инструмент | Модель | State | Логика | Роль в On-Premise стеке |
| :--- | :--- | :--- | :--- | :--- |
| **Crossplane** | Pull (reconciliation) | etcd (встроен) | Composition Functions (Go/Python/CEL) | L2/L3: самообслуживание, непрерывный контроль дрейфа |
| **OpenTofu / Terraform** | Push (`plan`/`apply`) | `.tfstate` (remote) | HCL (`for_each`, модули) | L0/L1: фундамент, bootstrap, редкие изменения |
| **Pulumi** | Push (`pulumi up`) | Pulumi state (remote) | Языки Go/Python/TS | L0/L1: программируемый фундамент; иногда замена HCL |
| **CUE** | Нет собственного цикла | Нет | Выражения CUE | Слой валидации/генерации конфигурации в CI; дополняет, не заменяет |

В корпоративных стеках, где уже выбран Crossplane как L2/L3 control plane, Pulumi применим для L0/L1 (где требуется программная логика над виртуализацией/сетями), а CUE — как дополнительный валидатор манифестов в CI до доставки в кластер. Непосредственной интеграции Crossplane↔Pulumi/CUE в виде готовых операторов нет; связка строится через Git (оба пишут манифесты в репозиторий) или через `provider-terraform` для исполнения HCL/Pulumi-подобных воркспейсов.

### Модели управления: Pull против Push

Главное архитектурное различие заключается в точке инициализации изменений и жизненном цикле процесса:

```text
PUSH-МОДЕЛЬ (OpenTofu / Terraform):
  Git Commit ──▶ GitLab CI Runner ──▶ tofu plan ──▶ [Approve] ──▶ tofu apply ──▶ On-Premise Инфраструктура
                                                                                    │
                                             (После завершения раннера дрейф        │
                                              остается незамеченным) ◀──────────────┘

PULL-МОДЕЛЬ (Crossplane):
  Git Commit ──▶ Argo CD / Flux ──▶ kube-apiserver (etcd)
                                          │
                                          ▼
                               ┌────────────────────────────────────────────────────────┐
                               │     Crossplane Continuous Reconciliation Loop          │
                               │                                                        │
                               │ 1. Чтение желаемого состояния из etcd                  │
                               │ 2. Опрос On-Premise API (vSphere, Proxmox, Patroni)    │
                               │ 3. Вычисление расхождения (Diff Calculation)           │
                               │ 4. Приведение к эталону (Active Remediation)           │
                               └────────────────────────────────────────────────────────┘
```

1. **Pull-модель Crossplane:**
   - Контроллер внутри кластера функционирует непрерывно. Каждые `pollInterval` (по умолчанию 1 минута, настраивается в манифесте) контроллер опрашивает конечную систему через установленный провайдер (`provider-sql`, `provider-vault`, `provider-proxmox`, `provider-kubernetes`).
   - Если администратор изменил конфигурацию вручную во внешней системе (например, сбросил права пользователя в PostgreSQL или удалил диск виртуальной машины), Crossplane зафиксирует отклонение и перезапишет параметры обратно в соответствии с манифестом.
   - Управление поведением регулируется через `spec.managementPolicies`:
     - `["*"]` — полный контроль (создание, наблюдение, обновление, удаление);
     - `["Observe"]` — режим аудита (только мониторинг и фиксация статуса без внесения изменений в целевую систему).
2. **Push-модель OpenTofu / Terraform:**
   - Бинарный файл запускается кратковременно в изолированном контексте.
   - `tofu plan` опрашивает API инфраструктуры, сверяет его со снимком `.tfstate` и строит граф изменений.
   - `tofu apply` отправляет команды в API и обновляет `.tfstate`.
   - Если в инфраструктуру вмешались после завершения команды, дрейф не будет обнаружен до следующего явного запуска пайплайна.

Развернутый анализ Push- и Pull-архитектур в инфраструктурных пайплайнах доступен в [обзоре методологии GitOps](../GitOps_overview.md#модели-доставки-push-против-pull).

### Управление состоянием и дрейфом (Drift)

#### Хранение состояния в Terraform и OpenTofu
- Состояние представляет собой сериализованный JSON-файл (`.tfstate`), сопоставляющий декларативные идентификаторы HCL с реальными ID объектов в инфраструктуре.
- В корпоративной On-Premise инфраструктуре файл сохраняется в сетевом бэкенде:
  - **S3-совместимое хранилище (MinIO, Ceph Object Gateway RGW):** требует настройки эндпоинта, блокировок и корректного Path-Style доступа;
  - **GitLab Managed Terraform State (HTTP Backend):** хранение внутри проекта GitLab с аутентификацией по CI-токену и нативной блокировкой;
  - **HashiCorp Consul:** K/V-хранилище с поддержкой распределенных сессий и мьютексов.
- **Проблема «разрастания state»:** в монолитных проектах с 500+ ресурсами выполнение команды `tofu plan` занимает минуты из-за последовательного опроса всех API. Сбой сети во время записи файла может привести к повреждению state или зависшей блокировке (`state lock`).

#### Хранение состояния в Crossplane
- Внешний state-файл отсутствует. Истинным состоянием является статус Custom Resource (CR) в базе `etcd` кластера Kubernetes (`status.atProvider`).
- Блокировки файлов не требуются: параллелизм и атомарность операций контролируются механизмом оптимистической блокировки Kubernetes (`metadata.resourceVersion`).
- Масштабирование достигается за счет шардирования контроллеров и распределения нагрузки между воркерами Kubernetes.

### Управление секретами и безопасность данных at-rest

Безопасность учетных данных — один из ключевых факторов выбора между инструментами в защищенных локальных контурах:

1. **Проблема секретов в Terraform:**
   - Ядро Terraform open-source сохраняет все атрибуты ресурсов (включая пароли от баз данных, приватные SSH-ключи, токены доступа) в открытом виде (plaintext) внутри JSON-файла `.tfstate`.
   - Любой сотрудник или процесс CI/CD, имеющий доступ на чтение бэкенда состояния, получает полный доступ к инфраструктурным секретам.
2. **Нативное шифрование в OpenTofu (`state_encryption`):**
   - Начиная с версии v1.7, OpenTofu решает проблему незашифрованного state на уровне ядра.
   - Файлы состояния (`.tfstate`) и файлы плана (`tfplan`) шифруются алгоритмом AES-GCM непосредственно перед отправкой в бэкенд.
   - Для генерации и ротации ключей используются провайдеры ключей: локальный PBKDF2 (по парольной фразе) либо корпоративные локальные хранилища секретов **HashiCorp Vault** и **OpenBao**.
3. **Безопасность в Crossplane:**
   - Учетные данные целевых систем (root-пароли к СУБД, токены API гипервизоров) хранятся в стандартных ресурсах `Secret` Kubernetes в служебном пространстве имен (например, `crossplane-system`).
   - Доступ к ним разграничивается с помощью Kubernetes RBAC. Разработчики, заказывающие сервисы через Claim в своих неймспейсах, физически не имеют доступа к учетным записям администратора инфраструктуры.
   - Выходные данные созданных ресурсов (сгенерированные пароли приложений, строки подключения) записываются контроллером в целевой неймспейс в виде Secret (`spec.writeConnectionSecretToRef`).

### Абстракция и композиция: HCL против Composition Functions

- **HCL-модули (Terraform/OpenTofu):**
  - Предоставляют параметризуемые шаблоны с валидацией типов, условиями (тернарные операторы) и циклами.
  - Ограничение: HCL является декларативным предметно-ориентированным языком (DSL). В нем сложно реализовать динамическое ветвление, обращение к внешним сетевым сервисам в процессе генерации манифестов или многократную обработку массивов без усложнения кодовой базы.
- **Composition Functions (Crossplane v2.x):**
  - В Crossplane v2.x композиция строится как gRPC-конвейер функций (`mode: Pipeline`).
  - Логика формирования ресурсов пишется на языках общего назначения (**Go**, **Python**) или декларативном языке выражений **CEL (Common Expression Language)**.
  - Позволяет строить платформенные абстракции корпоративного уровня: валидировать входные параметры по сложным правилам, динамически генерировать сетевые адреса, обращаться к локальному IPAM или каталогу сервисов во время рендеринга графа ресурсов.
  - Детальная реализация конвейеров функций представлена в [документации по Composition Functions](./composition_functions.md).

---

## Практические сценарии

### Сценарий 1: Матрица выбора инструментов для On-Premise / SRE

В корпоративной среде без публичных облаков инструменты решают принципиально разные задачи:

```text
ФУНДАМЕНТАЛЬНЫЙ УРОВЕНЬ (L0 / L1) ──▶ OpenTofu / Terraform
  • Bare-metal серверы (PXE, IPMI, Redfish)
  • Сетевые коммутаторы (VLAN, BGP, EVPN)
  • Гипервизоры (Proxmox VE, VMware vSphere, OpenStack)
  • Развертывание базовых Kubernetes-кластеров (Talos, kubeadm, RKE2)
  • Центральные сервисы (Vault, PowerDNS, FreeIPA)

ПЛАТФОРМЕННЫЙ УРОВЕНЬ СЕРВИСОВ (L2 / L3) ──▶ Crossplane
  • Самообслуживание для разработчиков (Self-Service Database / Storage)
  • Базы данных внутри Patroni / CloudNativePG / PostgreSQL
  • Бакеты и политики в корпоративном MinIO / Ceph S3
  • Сервисные учетные записи и роли в HashiCorp Vault / OpenBao
  • Выделение пространств имен и квот в дочерних кластерах K8s
```

**Выбирайте OpenTofu / Terraform, когда:**
1. Требуется создать фундамент, предшествующий появлению Kubernetes (сети, хранилища, сами виртуальные или физические ноды кластера).
2. Инфраструктура статична, изменения вносятся строго по графику релизов через ревью плана (`tofu plan`).
3. Команде требуется предварительный просмотр точного графа удалений и модификаций перед внесением изменений.

**Выбирайте Crossplane, когда:**
1. В компании строится **Internal Developer Platform (IDP)**: разработчики должны заказывать базы данных, очереди сообщений и бакеты через GitOps-манифесты вместе со своим кодом, не дожидаясь инженера инфраструктуры.
2. Критически важно исключить ручные неавторизованные изменения (Zero Drift) на уровне middleware и баз данных.
3. Команда стандартизировала операционные процессы вокруг Kubernetes API, Argo CD и Flux.

---

### Сценарий 2: Двухуровневый гибридный стек (OpenTofu Bootstrap + Crossplane Self-Service)

Стандарт построения корпоративной платформы: OpenTofu создает виртуальные машины и базовый кластер Kubernetes, после чего передает управление сервисами Crossplane.

#### Этап 1. Развертывание кластера через OpenTofu (L0/L1)
Конфигурация HCL создает ноды виртуализации в Proxmox VE и прописывает DNS-записи:

```hcl
# main.tf
terraform {
  required_version = ">= 1.8.0"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.73.0"
    }
  }
}

resource "proxmox_virtual_environment_vm" "k8s_control_plane" {
  count     = 3
  name      = "k8s-cp-0${count.index + 1}"
  node_name = "pve-node-01"
  vm_id     = 200 + count.index

  cpu {
    cores = 4
    type  = "host"
  }

  memory {
    dedicated = 8192
  }

  network_device {
    bridge = "vmbr0"
    vlan_id = 100
  }

  disk {
    datastore_id = "local-zfs"
    size         = 50
    interface    = "scsi0"
  }
}
```

Применение плана и проверка создания инфраструктуры:
```bash
tofu init -upgrade
# → Initializing provider plugins...
# → OpenTofu has been successfully initialized!

tofu plan -out=infra.tfplan
# → Plan: 3 to add, 0 to change, 0 to destroy.

tofu apply infra.tfplan
# → proxmox_virtual_environment_vm.k8s_control_plane[0]: Creation complete after 42s
# → Apply complete! Resources: 3 added, 0 changed, 0 destroyed.
```

#### Этап 2. Установка Crossplane и провайдера SQL в кластер (L2)
После инициализации кластера (через Talos/kubeadm) Flux или Argo CD устанавливает Crossplane и `provider-sql` для работы с существующим кластером PostgreSQL (Patroni):

```yaml
# provider-sql.yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-sql
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-sql:v0.9.0
---
apiVersion: postgresql.sql.crossplane.io/v1alpha1
kind: ProviderConfig
metadata:
  name: patroni-cluster
spec:
  credentials:
    source: Secret
    secretRef:
      namespace: crossplane-system
      name: patroni-admin-creds
      key: connection-string
```

#### Этап 3. Самообслуживание: Заказ БД разработчиком через Claim (L3)
Разработчик добавляет в Git-репозиторий приложения манифест заявки (Claim). Crossplane автоматически создает базу данных, генерирует пользователя со случайным паролем и отдает Secret в неймспейс приложения:

```yaml
apiVersion: database.corp.internal/v1alpha1
kind: PostgreSQLClaim
metadata:
  name: billing-db
  namespace: prod-billing
spec:
  parameters:
    storageGB: 50
    encoding: "UTF8"
  compositionRef:
    name: onprem-patroni-postgresql
  writeConnectionSecretToRef:
    name: billing-db-app-secret
```

Проверка состояния ресурса:
```bash
kubectl get postgresqlclaim billing-db -n prod-billing
# → NAME         SYNCED   READY   CONNECTION-SECRET       AGE
# → billing-db   True     True    billing-db-app-secret   2m15s

kubectl get secret billing-db-app-secret -n prod-billing -o jsonpath='{.data.endpoint}' | base64 -d
# → patroni.corp.internal:5432
```

---

### Сценарий 3: OpenTofu с нативным шифрованием состояния и On-Premise S3/MinIO Backend

Практическая настройка OpenTofu для безопасного хранения `.tfstate` в локальном хранилище MinIO с шифрованием на стороне клиента (Client-Side Encryption) через парольную фразу PBKDF2.

```hcl
# backend_and_encryption.tf
terraform {
  required_version = ">= 1.7.0"

  # Бэкенд в локальном MinIO
  backend "s3" {
    endpoint                    = "https://minio.corp.internal:9000"
    bucket                      = "tofu-states"
    key                         = "datacenter/networking.tfstate"
    region                      = "main"
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    use_path_style              = true
  }

  # Нативное шифрование OpenTofu
  encryption {
    key_provider "pbkdf2" "corp_key" {
      passphrase = var.state_encryption_passphrase
    }

    method "aes_gcm" "corp_aes" {
      keys = key_provider.pbkdf2.corp_key
    }

    state {
      method   = method.aes_gcm.corp_aes
      enforced = true
    }

    plan {
      method   = method.aes_gcm.corp_aes
      enforced = true
    }
  }
}

variable "state_encryption_passphrase" {
  type        = string
  sensitive   = true
  description = "Парольная фраза (минимум 16 символов) для шифрования файла состояния"
}
```

Проверка инициализации и шифрования:
```bash
export TF_VAR_state_encryption_passphrase="StrictEnterpriseSecretPassphrase2026!"
tofu init
# → Initializing the backend...
# → Successfully configured the backend "s3"! OpenTofu will automatically
# → use this backend unless the backend configuration changes.

tofu apply -auto-approve
# → Apply complete! Resources: 0 added, 0 changed, 0 destroyed.
```

При проверке объекта в корзине MinIO содержимое файла `networking.tfstate` представляет собой зашифрованный бинарный поток:
```bash
mc cat myminio/tofu-states/datacenter/networking.tfstate | head -n 3
# → {"OpenTofuEncryptedData":{"version":"1.0","method":"aes_gcm", ... бинарный payload ...}}
```

---

### Сценарий 4: Запуск OpenTofu/Terraform в GitOps через Tofu-Controller / TF-Controller

Если в организации уже написаны сотни HCL-модулей для настройки локальных сетевых коммутаторов или серверов FreeIPA/DNS, их можно перевести на Pull-модель с непрерывной сверкой через **Flux Tofu-Controller** (`flux-iac/tofu-controller`).

#### Шаг 1. Развертывание Tofu-Controller через Flux
```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: tofu-controller
  namespace: flux-system
spec:
  interval: 1h
  url: https://flux-iac.github.io/tofu-controller
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: tofu-controller
  namespace: flux-system
spec:
  interval: 30m
  chart:
    spec:
      chart: tofu-controller
      version: "0.16.x"
      sourceRef:
        kind: HelmRepository
        name: tofu-controller
        namespace: flux-system
  install:
    createNamespace: true
  values:
    runner:
      serviceAccount:
        create: true
```

#### Шаг 2. Декларативный манифест ресурса `Terraform`
Контроллер выгружает модуль из Git и периодически сверяет его с инфраструктурой:

```yaml
apiVersion: infra.contrib.fluxcd.io/v1alpha2
kind: Terraform
metadata:
  name: datacenter-powerdns-records
  namespace: flux-system
spec:
  interval: 5m                       # Периодичность проверки дрейфа
  approvePlan: "auto"                # Автоматическое применение подтвержденного плана
  path: ./terraform/modules/powerdns # Путь к HCL-модулю в репозитории
  sourceRef:
    kind: GitRepository
    name: corporate-infra-repo
    namespace: flux-system
  writeOutputsToSecret:
    name: dns-records-output
  runnerPodTemplate:
    spec:
      resources:
        limits:
          cpu: "1"
          memory: 1Gi
        requests:
          cpu: "200m"
          memory: 256Mi
```

#### Шаг 3. Валидация работы
```bash
kubectl get terraform datacenter-powerdns-records -n flux-system
# → NAME                          READY   STATUS                                 AGE
# → datacenter-powerdns-records   True    Applied 'main/a1b2c3d4' successfully   12m

kubectl describe terraform datacenter-powerdns-records -n flux-system
# → Events:
# →   Type    Reason   Age    From              Message
# →   ----    ------   ----   ----              -------
# →   Normal  Plan     4m10s  tofu-controller   Plan generated: 0 to add, 0 to change, 0 to destroy
# →   Normal  Apply    4m02s  tofu-controller   No changes required. State matches configuration.
```

---

### Сценарий 5: Управление HCL-модулями через Crossplane `provider-terraform`

Когда в платформе на базе Crossplane требуется управлять редким оборудованием (локальная СХД, устаревший SAN-коммутатор), для которого нет нативного Go-провайдера Crossplane, но существует рабочий Terraform-провайдер, используется `provider-terraform` (`crossplane-contrib`).

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-terraform
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-terraform:v0.17.0
---
apiVersion: tf.crossplane.io/v1beta1
kind: ProviderConfig
metadata:
  name: local-consul-backend
spec:
  configuration: |
    terraform {
      backend "consul" {
        address = "consul.corp.internal:8500"
        scheme  = "http"
        path    = "crossplane/workspaces"
      }
    }
---
apiVersion: tf.crossplane.io/v1beta1
kind: Workspace
metadata:
  name: netbox-ip-allocation
  namespace: crossplane-system
spec:
  forProvider:
    source: Inline
    module: |
      terraform {
        required_providers {
          netbox = {
            source  = "e-breuninger/netbox"
            version = "3.8.0"
          }
        }
      }
      provider "netbox" {
        server_url = "https://netbox.corp.internal"
        api_token  = var.netbox_token
      }
      variable "netbox_token" { type = string }
      resource "netbox_available_ip_address" "db_ip" {
        prefix_id = 15
      }
      output "assigned_ip" {
        value = netbox_available_ip_address.db_ip.ip_address
      }
    vars:
      - key: netbox_token
        secretKeyRef:
          namespace: crossplane-system
          name: netbox-credentials
          key: token
  providerConfigRef:
    name: local-consul-backend
  writeConnectionSecretToRef:
    name: netbox-allocated-ip-secret
    namespace: crossplane-system
```

Проверка статуса воркспейса:
```bash
kubectl get workspace netbox-ip-allocation -n crossplane-system
# → NAME                   READY   SYNCED   AGE
# → netbox-ip-allocation   True    True     3m45s

kubectl get secret netbox-allocated-ip-secret -n crossplane-system -o jsonpath='{.data.assigned_ip}' | base64 -d
# → 192.168.10.45/24
```

---

### Сценарий 6: Устранение дрейфа конфигурации (Drift Remediation на практике)

Сравнение реакции систем на несанкционированное ручное изменение параметров On-Premise инфраструктуры:

#### Исходная ситуация
Администратор вручную подключился к серверу PostgreSQL и изменил лимит подключений или отозвал права у служебной роли приложения:
```sql
ALTER ROLE app_billing NOSUPERUSER NOINHERIT CONNECTION LIMIT 1;
```

#### Поведение OpenTofu / Terraform (Push)
- Система находится в неведении. Файл `.tfstate` содержит старую информацию.
- Сервис приложения начинает отказывать из-за исчерпания пула соединений.
- Обнаружение проблемы: инженер запускает ручную диагностику:
```bash
tofu plan -detailed-exitcode
# → ~ update in-place:
# →   ~ connection_limit = 1 -> 100
# → Plan: 0 to add, 1 to change, 0 to destroy.
# → Exit code: 2 (Drift detected)
```
- Для восстановления работоспособности инженер обязан выполнить `tofu apply`.

#### Поведение Crossplane (Pull)
- В течение `pollInterval` (по умолчанию 60 секунд) фоновый воркер `provider-sql` выполняет запрос к системным таблицам PostgreSQL `pg_roles`.
- Контроллер фиксирует несовпадение поля `spec.forProvider.connectionLimit` в объекте `Role` и в СУБД.
- Контроллер формирует транзакцию `ALTER ROLE app_billing CONNECTION LIMIT 100` и восстанавливает эталонное состояние.
- В событиях объекта Kubernetes фиксируется исправление:
```bash
kubectl describe role.postgresql.sql.crossplane.io app_billing
# → Events:
# →   Type    Reason                 Age   From                         Message
# →   ----    ------                 ----  ----                         -------
# →   Normal  ReconcileSuccess       52s   postgresql.sql.crossplane.io  Successfully reconciled managed resource
# →   Normal  RemediationExecuted    52s   postgresql.sql.crossplane.io  Drift detected on field connectionLimit: reset from 1 to 100
```

---

## Операции и команды

Сводная таблица соответствия повседневных операций управления:

| Операция | OpenTofu / Terraform (Push) | Crossplane (Pull / K8s API) | Ожидаемый результат / Назначение |
| :--- | :--- | :--- | :--- |
| **Инициализация проекта** | `tofu init -upgrade` | `kubectl apply -f provider.yaml` | Загрузка плагинов/провайдеров и настройка бэкенда |
| **Статическая валидация** | `tofu validate` | `kubeconform -strict manifest.yaml` | Проверка синтаксиса и схемы типов |
| **Предварительный просмотр плана** | `tofu plan -out=plan.tfplan` | `crossplane render xr.yaml comp.yaml fn.yaml` | Локальный рендеринг графа без применения изменений |
| **Применение изменений** | `tofu apply plan.tfplan` | `git push` (GitOps Sync) / `kubectl apply` | Передача манифестов на исполнение в целевые системы |
| **Инспекция состояния ресурсов** | `tofu state list` / `tofu state show <addr>` | `kubectl get managed` / `kubectl describe <kind>` | Просмотр атрибутов зафиксированных объектов |
| **Проверка наличия дрейфа** | `tofu plan -detailed-exitcode` | Автоматически в фоне / `crossplane beta trace <xr>` | Код возврата 2 в OpenTofu; статус `Synced: True` в Crossplane |
| **Снятие аварийной блокировки** | `tofu force-unlock <LOCK-ID>` | Редактирование аннотаций / снятие Finalizers | Разблокировка зависшего процесса модификации |
| **Временная пауза сверки** | Не применимо (Push не работает в фоне) | `kubectl annotate <kind> <name> crossplane.io/paused=true` | Остановка reconciliation loop для сервисного обслуживания |
| **Уничтожение ресурсов** | `tofu destroy` | `kubectl delete -f resource.yaml` | Удаление объектов в соответствии с `spec.deletionPolicy` |

---

## Устранение неполадок

| Симптом / Ошибка | Первопричина | Пошаговое решение |
| :--- | :--- | :--- |
| **OpenTofu:** `Error: Error locking state: Error acquiring the state lock` | Падение предыдущего пайплайна CI/CD во время исполнения `apply`; lock-запись в MinIO/Consul не удалилась. | 1. Убедиться, что параллельный процесс CI гарантированно завершен.<br>2. Выполнить снятие блокировки:<br>`tofu force-unlock <LOCK-ID>`<br>3. В случае MinIO/S3 бэкенда удалить lock-объект вручную при необходимости. |
| **OpenTofu:** `Error: failed to decrypt state: invalid passphrase or corrupted key` | Изменилась парольная фраза `PBKDF2`, либо недоступен сетевой эндпоинт HashiCorp Vault. | 1. Проверить переменную окружения `TF_VAR_state_encryption_passphrase`.<br>2. Если проводилась ротация ключа, добавить старый ключ в блок `fallback {}` в секции `encryption`. |
| **Crossplane:** `Managed Resource` завис в состоянии `SYNCED: False`, `READY: False` | Неверные реквизиты в `Secret`, на который ссылается `ProviderConfig`, либо сетевая изоляция (NetworkPolicy/Firewall). | 1. Проверить события ресурса:<br>`kubectl describe <resource-kind> <name>`<br>2. Проверить доступность локального эндпоинта из пода провайдера:<br>`kubectl logs -n crossplane-system -l pkg.crossplane.io/provider=<name>`<br>3. Убедиться в корректности секрета подключения. |
| **Crossplane:** `Cannot delete resource: object has finalizers` | Внешний ресурс уже удален вручную, или провайдер не может авторизоваться для выполнения удаления. | 1. Если физический ресурс удален, и нужно очистить объект в K8s:<br>`kubectl patch <kind> <name> -p '{"metadata":{"finalizers":null}}' --type=merge`<br>2. Для предотвращения каскадных удалений задавать `spec.deletionPolicy: Orphan`. |
| **Tofu-Controller:** Runner-под падает с ошибкой `OOMKilled` (Exit Code 137) | Слишком большой граф HCL-модулей (более 1000 ресурсов); нехватка RAM при генерации плана. | 1. Увеличить лимиты памяти в манифесте ресурса `Terraform`:<br>`spec.runnerPodTemplate.spec.resources.limits.memory: "2Gi"`<br>2. Разбить монолитный модуль на несколько независимых манифестов. |
| **Crossplane:** Чрезмерная нагрузка на целевое API On-Premise (Rate Limiting) | Слишком частый цикл реконсиляции по умолчанию (1 минута) при наличии сотен Managed Resources. | 1. Увеличить интервал опроса в манифесте ресурса:<br>`spec.forProvider.pollInterval: 10m`<br>2. Настроить глобальный флаг `--poll-interval` в `DeploymentRuntimeConfig` провайдера. |

---

## Лучшие практики

### 1. Архитектурное эшелонирование (Layering)
- **Уровень фундамента (Undercloud / L0-L1):** Создание базовой сетевой инфраструктуры (VLAN, BGP), развертывание гипервизоров (Proxmox, vSphere), первоначальный бутстрап Kubernetes-нод выполняйте через **OpenTofu/Terraform**. Этот уровень меняется редко и требует обязательного согласования плана изменений (`plan review`).
- **Уровень сервисов платформы (Overcloud / L2-L3):** Настройку СУБД (PostgreSQL/Patroni), бакетов MinIO, очередей сообщений и пространств имен доверяйте **Crossplane**. Это обеспечивает разработчикам полностью автономный Self-Service через GitOps.

### 2. Защита данных при удалении в Crossplane
- Для всех критических On-Premise ресурсов (базы данных, тома Ceph, учетные записи безопасности) явно задавайте политику удаления:
  ```yaml
  spec:
    deletionPolicy: Orphan
  ```
- Значение `Orphan` гарантирует: если манифест Kubernetes или пространство имен будут случайно удалены из Git или кластера, физическая база данных на внешнем сервере PostgreSQL останется нетронутой.

### 3. Безопасность состояния OpenTofu в On-Premise
- Никогда не храните `.tfstate` на общедоступных сетевых файловых шарах (NFS, SMB) без шифрования.
- Всегда включайте встроенный блок `encryption {}` в OpenTofu с хранением ключей в корпоративном HashiCorp Vault / OpenBao либо безопасной передачей через переменные CI/CD.

### 4. Оптимизация производительности Control Plane
- Не допускайте запуска сотен Managed Resources с дефолтным интервалом опроса `pollInterval: 1m`. Для систем с медленными API (например, старые версии консолей виртуализации) увеличивайте интервал опроса до `10m`–`15m`.
- Для изоляции контроллеров используйте `DeploymentRuntimeConfig`, назначая подам провайдеров выделенные узлы с помощью `nodeSelector` и `tolerations`.

---

## Дополнительная информация

Внутренние связанные материалы базы знаний:
- [Crossplane: общий обзор архитектуры](./overview.md) — фундаментальные принципы работы Kubernetes как Control Plane.
- [Crossplane: интеграция с GitOps](./gitops_integration.md) — паттерн двухконтурной сверки (Two-Loop Reconciliation) с Argo CD и Flux.
- [Crossplane: Composition Functions](./composition_functions.md) — реализация логики платформенных абстракций на Go, Python и CEL.
- [Инструменты управления конфигурацией](../../Concepts/configuration_management_tools.md) — детальный разбор границ применения Ansible, Terraform и OpenTofu.
- [GitOps: обзор методологии](../GitOps_overview.md) — концептуальные основы Push и Pull подходов к инфраструктуре.
- [Управление секретами в GitOps](../secrets_encryption.md) — интеграция Vault, SOPS и External Secrets Operator.

Официальная документация и открытые репозитории:
- [Документация OpenTofu State Encryption](https://opentofu.org/docs/language/state/encryption/) — спецификация алгоритмов и конфигурации шифрования состояния.
- [Crossplane Documentation](https://docs.crossplane.io/latest/) — архитектура ядра Crossplane и спецификации Composition Functions.
- [Flux Tofu-Controller Repository](https://github.com/flux-iac/tofu-controller) — оператор запуска HCL-кода в Kubernetes по pull-модели.
- [Crossplane provider-terraform](https://github.com/crossplane-contrib/provider-terraform) — запуск HCL-воркспейсов в виде управляемых ресурсов Kubernetes.
