# Crossplane: сравнение с Terraform и OpenTofu

## Определения

**Crossplane** — это Kubernetes-native решение для управления инфраструктурой, превращающее кластер в полноценную платформу управления (Control Plane). Оно расширяет API Kubernetes для декларативного управления облачными ресурсами через контроллеры и систему непрерывной сверки (reconciliation loop). Актуальная мажорная линия — **Crossplane v2.x** (стабильный релиз **v2.4** на август 2026 года). Ресурсы описываются как объекты Kubernetes (`Managed Resources`, `Composite Resources`), а желаемое состояние хранится в `etcd`.

**Terraform** — индустриальный стандарт **IaC (Infrastructure as Code)**. После приобретения HashiCorp компанией IBM в 2024 году инструмент стал частью портфеля IBM (под лицензией **BUSL-1.1**, source-available). Использует язык **HCL** и ориентирован на событийное выполнение (workflow-based, модель **Push**). Актуальная стабильная линия — **Terraform 1.15.x** (последний патч **1.15.9**, август 2026); более старые линии (включая 1.10) к августу 2026 года достигли EOL и официально не поддерживаются.

**OpenTofu** — открытый форк Terraform под эгидой Linux Foundation (CNCF Sandbox, MPL 2.0). Возник как ответ на смену лицензии HashiCorp на BSL и формально является форком Terraform 1.5 (полностью совместимый HCL и формат состояния). К 2026 году проект развился в независимую экосистему и внедрил уникальные функции: нативное шифрование состояния, ephemeral-значения, `enabled`-мета-аргумент, `for_each` для провайдеров. Актуальная стабильная линия — **OpenTofu 1.12.x** (последний патч **1.12.6**, август 2026). Для большинства команд `tofu` является drop-in заменой `terraform` (те же HCL, провайдеры и формат состояния).

## Базовые концепции

### Ключевые различия (актуально на 2026 год)

| Характеристика | Crossplane (v2.x, актуально v2.4) | Terraform (v1.15.x, стабильная линия) | OpenTofu (v1.12.x, актуально v1.12.6) |
| :--- | :--- | :--- | :--- |
| **Модель управления** | Pull (Continuous Reconciliation) | Push (Plan/Apply Workflow) | Push (Plan/Apply Workflow) |
| **Среда выполнения** | Kubernetes Cluster | CLI / CI-CD / Runner | CLI / CI-CD / Runner |
| **Хранение состояния** | etcd (встроено в объекты) | Файл `.tfstate` (Remote Backend) | Файл `.tfstate` (Remote Backend) |
| **Исправление дрейфа** | **Автоматическое** (Self-healing) | Ручное (через запуск пайплайна) | Ручное (через запуск пайплайна) |
| **Логика и шаблоны** | **Composition Functions** (Go, Python, CEL) | HCL Logic / Terraform Stacks | HCL Logic / State Encryption |
| **Интерфейс** | K8s API (kubectl, GitOps) | CLI / UI (HCP Terraform) | CLI / Open Source UI |
| **Безопасность** | RBAC K8s, OPA/Kyverno, ESO | Sentinel, Vault, OPA | OPA, KMS State Encryption (нативно) |
| **Лицензия** | Apache-2.0 | BUSL-1.1 (source-available) | MPL 2.0 (OSI open source) |

**Почему модель важна на практике:** в Pull-модели Crossplane агент находится внутри кластера и постоянно сверяет фактическое состояние облака с желаемым (YAML). В Push-модели Terraform/OpenTofu изменения применяются только в момент явного запуска `plan`/`apply` (локально или из CI). Это определяет ключевое различие в детекции дрейфа (см. ниже) и в требованиях к безопасности: у Crossplane креденшелы к облаку хранятся в кластере и не покидают периметр, а у Terraform — в CI-runner или remote backend.

### Модели управления: Pull (Continuous Reconciliation) против Push (Plan/Apply)

*   **Crossplane (Pull):** Контроллер внутри кластера выполняет бесконечный цикл `Считать YAML -> Считать состояние облака (через провайдер) -> Вычислить расхождение -> Привести к желаемому`. Цикл реконсиляции запускается при каждом изменении объекта и периодически (poll interval), что даёт непрерывную сверку в реальном времени.
*   **Terraform / OpenTofu (Push):** Изменения применяются императивно — `tofu plan` строит diff, `tofu apply` вносит изменения. Никакой фоновой сверки не происходит; дрейф обнаруживается только при следующем запуске планирования. Для GitOps поверх Terraform используют либо CI, запускающий `apply` (теряет преимущества непрерывной детекции), либо специализированные контроллеры (см. практический сценарий про Flux TF-controller).

Развёрнутое сравнение Push/Pull-архитектур в контексте GitOps — в [обзоре методологии](../GitOps_overview.md#модели-доставки-push-против-pull).

### Управление состоянием и дрейфом (Drift)

*   **Crossplane:** Не имеет внешнего state-файла. «Состояние» — это статус ресурса в Kubernetes (`status` объекта `Managed Resource`), который контроллер постоянно сверяет с облаком. Если ресурс изменён вручную в консоли облака (например, изменён размер инстанса БД), Crossplane обнаружит расхождение и автоматически вернёт параметр к значению, описанному в YAML. При этом политику реакции можно тонко настраивать через `managementPolicies` (например, режим `ObserveOnly` только детектирует дрейф, не исправляя его — удобно для аудита существующей инфраструктуры без риска нежелательных изменений).
*   **Terraform / OpenTofu:** Состояние хранится как статический снимок (`.tfstate`) в remote backend (S3 + DynamoDB lock, GCS, Azure Blob, HCP Terraform). Дрейф обнаруживается только при запуске `plan`. Облачные редакции (HCP Terraform) добавляют «Continuous Validation» / Drift Detection, выполняющие периодический `plan` на стороне сервиса, но это платная функция, и автоматическое исправление без явного рабочего процесса (Workflow) остаётся ограниченным. В открытом коде классический инструмент `driftctl` архивирован — его роль перешла к нативным механизмам детекции поставщиков и к Crossplane.

### Логика композиции vs HCL

*   **HCL (Terraform/OpenTofu):** Мощный DSL для описания инфраструктуры с поддержкой условий, циклов (`for`), модулей и `for_each` для провайдеров (итерация по регионам/аккаунтам — нативно в OpenTofu 1.9 и Terraform 1.10+). **Terraform Stacks** (HCP Terraform) позволяет оркестровать сложные зависимости между множеством модулей и регионов как единый деплой.
*   **Composition Functions (Crossplane):** Позволяет использовать полноценные языки программирования (Go, Python) или CEL (Common Expression Language) для формирования графа ресурсов внутри `Composition`. Это решает проблему «многословного YAML» и позволяет реализовывать логику, недоступную в HCL (например, динамические запросы к внешним API в процессе рендеринга, переиспользование кода на Go). `Composition` превращает набор `Managed Resources` в типизированный «продукт» для разработчиков (`Composite Resource` / `Claim`), что лежит в основе Internal Developer Platform.

### Архитектура и позиционирование

*   **Где выполняется:** Crossplane живёт внутри Kubernetes-кластера и сам является control plane; Terraform/OpenTofu — это CLI, который запускается где угодно (локально, в CI, в agent). Это значит, что Crossplane требует уже существующего кластера (обычно созданного внешним IaC-инструментом), а Terraform/OpenTofu могут создавать сам фундамент, включая этот кластер.
*   **Экосистема провайдеров:** Terraform/OpenTofu используют единый Registry (`registry.terraform.io` / `registry.opentofu.org) с тысячами провайдеров. У Crossplane провайдеры распространяются как OCI-пакеты (`xpkg.upbound.io`, family-провайдеры Upbound и сообщества, например `provider-aws`, `provider-gcp`, `provider-azure`); «jet»-провайдеры (генерируемые из Terraform-провайдеров) закрывают ~95% потребностей. Для редких/нишевых ресурсов Crossplane может напрямую исполнять Terraform-модули (см. сценарий про `provider-terraform`).
*   **Блокировка состояния:** У Terraform/OpenTofu блокировка реализуется backend'ом (DynamoDB, consul, native GCS/Azure); у Crossplane блокировка не нужна — состояние в `etcd` согласованно самой etcd и механизмами контроллеров.

### Безопасность и секреты

*   **Terraform:** Политика как код — Sentinel (в HCP Terraform, платно) или OPA (через сторонние хуки). Состояние может содержать чувствительные данные (пароли, ключи в `output`); защита — remote backend с шифрованием покоя и ограничением доступа. **Важно:** open-source ядро Terraform не имеет нативного шифрования state-файла — только через внешние механизмы (Vault, KMS backend).
*   **OpenTofu:** Имеет **нативное шифрование состояния** (с версии 1.7) — AES-GCM с ключевыми провайдерами PBKDF2, AWS KMS, GCP KMS, Azure Key Vault, OpenBao. Это ключевое отличие от Terraform для команд, которым критична защита state-at-rest без сторонних сервисов.
*   **Crossplane:** Использует RBAC Kubernetes, OPA/Kyverno для admission-контроля и хранит креденшелы облака в `Secret`, на который ссылается `ProviderConfig`. Синхронизация секретов из внешних хранилищ (Vault, AWS SM) выполняется через External Secrets Operator — см. [управление секретами в GitOps](../secrets_encryption.md).

## Практические сценарии

> **Предварительные требования (общие):** доступ к облачному аккаунту с выданными креденшелами; для Crossplane — Kubernetes-кластер v1.28+ и установленный Crossplane v2.x; для Terraform/OpenTofu — бинарный `tofu`/`terraform` (через `tfenv`/`mise`) и настроенный remote backend; Git-репозиторий под желаемое состояние. Версии фиксируйте в `required_providers` / `.opentofu-version` / `crossplane` CLI, чтобы избежать расхождений между средами.

### Выбор инструмента

**Выбирайте Crossplane, когда:**
*   Вы строите **Internal Developer Platform (IDP)** и внедряете подход «Infrastructure as a Product».
*   Приложения и их инфраструктурные зависимости (БД, очереди) должны иметь единый жизненный цикл в рамках GitOps (ArgoCD/Flux).
*   Требуется строгая гарантия отсутствия ручных изменений (Zero Drift) и непрерывное самовосстановление.
*   Команда глубоко интегрирована в экосистему Kubernetes.

**Выбирайте Terraform / OpenTofu, когда:**
*   Нужно управлять «фундаментальной» инфраструктурой (сети, Peering, IAM, сами кластеры K8s) — то есть тем, что предшествует появлению кластера для Crossplane.
*   Проект требует использования редких провайдеров, которых нет в экосистеме Crossplane (хотя jet-провайдеры Crossplane закрывают 95% потребностей).
*   Инфраструктура статична и не требует постоянной сверки.
*   Команде требуется визуальный «план» изменений перед их применением для критически важных систем (см. `tofu plan -out`).

### Гибридный подход (Стандарт 2026 года)

Современная архитектура SRE-платформ предполагает разделение ответственности:

1.  **OpenTofu (или Terraform):** Создание базового уровня (VPC, Subnets, IAM, K8s Clusters). Используется как «bootstrap» инструмент.
2.  **Crossplane:** Разворачивается внутри созданных кластеров для предоставления «Self-Service» инфраструктуры разработчикам (Managed Databases, S3, Pub/Sub).

Этот подход объединяет надёжность HCL для фундаментальных изменений и гибкость Kubernetes-native API для сервисов приложений. Конкретная реализация bootstrap через Flux описана в практическом сценарии 6.

### Сценарий 3: Запуск Terraform внутри кластера через Flux TF-controller (Terraform-in-GitOps)

Если нужен GitOps-стиль управления Terraform-ресурсами без отказа от существующих HCL-модулей, используется **Flux TF-controller** (`phoban01/tf-controller`) — контроллер, который реконсилирует Terraform-ресурсы по модели Pull: сам вызывает `plan`/`apply` внутри кластера на основе изменений в Git/OCI и периодически детектирует дрейф.

**Предварительные требования:** установленный Flux (`flux bootstrap`), кластер с доступом к облаку, Git-репозиторий с Terraform-модулем.

**Шаг 1. Установка TF-controller (Helm через Flux):**
```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: tf-controller
  namespace: flux-system
spec:
  interval: 1h
  url: https://phoban01.github.io/tf-controller
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: tf-controller
  namespace: flux-system
spec:
  interval: 1h
  chart:
    spec:
      chart: tf-controller
      version: "0.16.x"        # актуальную версию сверяйте в реестре
      sourceRef:
        kind: HelmRepository
        name: tf-controller
        namespace: flux-system
  install:
    createNamespace: true
```

**Шаг 2. Источник модуля и объект `Terraform`:**
```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: infra
  namespace: flux-system
spec:
  interval: 1m
  url: https://github.com/my-org/infra.git
  ref:
    branch: main
---
apiVersion: infra.contrib.fluxcd.io/v1alpha1
kind: Terraform
metadata:
  name: s3-buckets
  namespace: flux-system
spec:
  interval: 1m                 # частота реконсиляции = частота детекции дрейфа
  path: ./terraform/s3         # путь к модулю внутри репозитория
  sourceRef:
    kind: GitRepository
    name: infra
    namespace: flux-system
  approvePlan: "auto"          # "auto" — применять план автоматически;
                               # строка вида "plan-main-*" или "manual" — требует ручного подтверждения
  # destroy: false             # при удержании ресурсов при удалении объекта (по умолчанию ресурсы удаляются)
```

**Шаг 3. Валидация:**
```bash
flux get tf s3-buckets -n flux-system          # → готовность и статус плана/апплая
kubectl get terraform s3-buckets -n flux-system -o wide
kubectl describe terraform s3-buckets -n flux-system   # → события plan/apply, ошибки
```
**Ожидаемый результат:** контроллер создаёт под с `terraform init/plan/apply`, а в статусе объекта появляется `APPLIED` и идентификатор плана. При ручном изменении ресурса в облаке следующая реконсиляция (через `interval`) покажет расхождение и, при `approvePlan: auto`, вернёт состояние к модулю.

### Сценарий 4: Управление Terraform-модулями как Kubernetes-ресурсами через provider-terraform

Когда нужен конкретный ресурс, отсутствующий у Crossplane-провайдеров, но хочется оставить его в Kubernetes API, используется **provider-terraform** (`crossplane-contrib`): Crossplane запускает бинарный Terraform/OpenTofu внутри пода провайдера и управляет модулем как `Managed Resource` (`Workspace`).

**Предварительные требования:** установленный Crossplane v2.x, `provider-terraform`, `ProviderConfig` с креденшелами облака.

**Шаг 1. Провайдер и ProviderConfig:**
```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-terraform
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-terraform:v0.17.0   # версию сверяйте в registry
---
apiVersion: tf.crossplane.io/v1beta1
kind: ProviderConfig
metadata:
  name: default
spec:
  configuration: |
    terraform {
      # backend "remote" { organization = "my-org" workspaces { name = "crossplane" } }
    }
  credentials:
    source: Secret
    secretRef:
      namespace: crossplane-system
      name: tf-credentials          # содержит ключи облака (AWS_ACCESS_KEY_ID и т.п.)
      key: credentials
```

**Шаг 2. Workspace (модуль inline):**
```yaml
apiVersion: tf.crossplane.io/v1beta1
kind: Workspace
metadata:
  name: app-bucket
  namespace: crossplane-system
spec:
  forProvider:
    source: Inline                 # либо Remote + module = "git::https://..."
    module: |
      resource "aws_s3_bucket" "this" {
        bucket = var.bucket_name
      }
      variable "bucket_name" {}
    vars:
      - key: bucket_name
        value: my-app-bucket
  providerConfigRef:
    name: default
  writeConnectionSecretToRef:
    name: app-bucket-conn
    namespace: crossplane-system
```

**Шаг 3. Валидация:**
```bash
kubectl get workspace app-bucket -n crossplane-system
kubectl describe workspace app-bucket -n crossplane-system   # → фазы init/plan/apply
```
**Ожидаемый результат:** `STATUS` переходит в `Ready`, в облаке появляется бакет, а в `crossplane-system` создаётся `Secret` `app-bucket-conn` с выходными данными модуля.
**Ограничение:** этот паттерн запускает Terraform-бинарь внутри кластера и фактически превращается в «Terraform внутри Crossplane» — используйте его точечно для нишевых ресурсов, а не как основу платформы.

### Сценарий 5: Миграция существующей инфраструктуры

*   **Постепенный переход (рекомендуемый):** оставьте Terraform/OpenTofu для фундамента (VPC, кластеры) и добавьте Crossplane для сервисных ресурсов приложений. Новые ресурсы описываются `Managed Resources`/`Claims`, старые продолжают управляться HCL.
*   **Импорт в Crossplane:** существующие облачные ресурсы можно подтянуть в Crossplane в режиме наблюдения через `ProviderConfig`/`ObserveOnly` (`managementPolicies: ["Observe"]`) — Crossplane начнёт отслеживать их без изменений, после чего можно перейти к полному управлению.
*   **Импорт в Terraform/OpenTofu:** `tofu import <address> <id>` либо блок `import {}` (loopable import доступен с 1.7 в обоих инструментах) заполняет `.tfstate` без пересоздания ресурса.

**Валидация миграции:**
```bash
tofu state list                 # → список ресурсов в state
tofu plan                       # → должен показывать No changes (ресурсы совпадают с облаком)
kubectl get managed            # Crossplane: все MR в Ready
```

### Сценарий 6: Конкретный гибридный bootstrap (Terraform → Flux → Crossplane)

**Шаг 1. Фундамент через OpenTofu:**
```bash
tofu init -upgrade
tofu plan -out=tfplan
tofu apply tfplan              # → создаёт VPC, EKS/IAM, права для Crossplane (IRSA/OIDC)
```

**Шаг 2. GitOps-контроллер и установка Crossplane через Flux:**
```bash
flux bootstrap github \
  --owner=my-org --repository=infra --branch=main --path=./clusters/management
```
Далее в репозитории — `HelmRepository` + `HelmRelease` для Crossplane (тот же паттерн, что в сценарии 3, шаг 1), либо декларативная установка через ArgoCD Application.

**Шаг 3. Валидация:**
```bash
kubectl get pods -n crossplane-system        # → crossplane и провайдеры Ready
flux get kustomizations -A                    # → все Kustomization синхронизированы
```
**Ожидаемый результат:** управляющий кластер поднят, Crossplane установлен декларативно, дальнейшее добавление провайдеров и Composition происходит коммитами в Git без ручных действий.

### Предполётная валидация (CI)

| Инструмент | Команды | Что проверяет |
| :--- | :--- | :--- |
| **OpenTofu / Terraform** | `tofu init -upgrade`, `tofu validate`, `tofu plan -out`, `tfsec`, `conftest` | Корректность HCL, совместимость провайдеров, политики безопасности, отсутствие секретов в плане |
| **Crossplane** | `crossplane render xr.yaml composition.yaml functions.yaml`, `crossplane beta validate`, `kubeconform` | Рендер Composition Functions без кластера, валидность CRD, схемы K8s API |

Пример стадии для HCL-модулей:
```bash
tofu fmt -check -recursive
tofu init -backend=false
tofu validate
tfsec .                        # статический анализ безопасности (секреты, открытые бакеты)
```

### Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Terraform/OpenTofu: `Error: Lock Info` | State заблокирован другим запущенным `apply` или упавшим CI | `tofu force-unlock <ID>` после подтверждения, что параллельного запуска нет; настроить DynamoDB lock |
| Дрейф не исправляется автоматически (Terraform) | `apply` не запускается периодически | Добавить scheduled `plan` в CI или перейти на HCP Terraform Drift Detection / TF-controller |
| Crossplane: `MR` в `Creating` вечно | Неверный `ProviderConfig` / креденшелы | `kubectl describe providerconfig default`, `kubectl -n crossplane-system get secret`, `crossplane alpha trace <xr>` |
| Crossplane: ресурс пересоздаётся вместо обновления | изменено immutable-поле облака | проверить events контроллера; для безопасного наблюдения — `managementPolicies: ["Observe"]` |
| TF-controller: план ждёт подтверждения | `approvePlan: manual` | `tfctl approve --name s3-buckets -n flux-system` либо переключить на `auto` |
| provider-terraform: `Workspace` не переходит в Ready | нет бинаря/креденшелов в поде провайдера | `kubectl -n crossplane-system logs -l pkg.crossplane.io/provider=provider-terraform` |
| Секреты не синхронизируются в Crossplane | ESO не видит `ClusterSecretStore` | проверить `ExternalSecret`/`SecretStore` и доступ к Vault (см. [секреты](../secrets_encryption.md)) |

### Лучшие практики и очистка

*   **Версионирование:** фиксируйте `required_providers`/`required_version` и версию Crossplane/провайдеров в манифестах; используйте `tfenv`/`mise` для бинарей.
*   **Состояние:** Terraform/OpenTofu — только remote backend с шифрованием покоя и блокировкой; чувствительные переменные не коммитьте (SOPS или Vault). Для OpenTofu включите нативное шифрование state.
*   **GitOps-дисциплина:** все изменения — только через PR; включите `selfHeal`/`prune` (ArgoCD) или `interval` (Flux/TF-controller) для непрерывной сверки.
*   **Очистка:** Terraform/OpenTofu — `tofu destroy` (или удаление объекта `Terraform` при `destroy: true` в TF-controller). Crossplane — `kubectl delete` ресурса; поведение при удалении задаётся `spec.deletionPolicy` (`Delete` по умолчанию уничтожает облачный ресурс, `Orphan` оставляет). Удаляйте инфраструктуру в порядке, обратном созданию (сервисы → фундамент), чтобы не заблокировать удаление сети занятыми ресурсами.

### Ограничения и пограничные случаи

*   **Crossplane** не предназначен для создания самого фундамента (сети, кластеров) — ему нужен работающий Kubernetes. Реконсиляция eventual-consistent: между коммитом и готовностью ресурса проходит несколько циклов; высоконагруженные кластеры с сотнями MR требуют тюнинга производительности контроллеров.
*   **Terraform / OpenTofu** не имеют фоновой сверки в open-source ядре: дрейф остаётся незамеченным, пока кто-то не запустит `plan`. Большие `.tfstate` (тысячи ресурсов) замедляют `plan`/`apply`.
*   **Совместимость состояния:** формат `.tfstate` взаимозаменяем между Terraform и OpenTofu **до** включения OpenTofu-специфичных функций (шифрование state, ephemeral, `enabled`). После их включения state перестаёт быть round-trippable — планируйте миграцию осознанно.
*   **provider gaps:** для редких облачных сервисов Crossplane-провайдера может не быть — тогда используйте `provider-terraform` (сценарий 4) или оставьте ресурс на HCL.

## Дополнительная информация

Концептуальный обзор технологии: [Crossplane: обзор](./overview.md).
Интеграция в GitOps-пайплайны: [Интеграция с GitOps](./gitops_integration.md).
Управление креденшелами и секретами: [Управление секретами в GitOps](../secrets_encryption.md).

Внешние ресурсы:
* [Terraform Stacks Overview](https://developer.hashicorp.com/terraform/cloud-docs/stacks) — оркестрация модулей в HCP Terraform.
* [OpenTofu State Encryption](https://github.com/opentofu/opentofu/blob/main/docs/state_encryption.md) — нативное шифрование состояния (AES-GCM, KMS-провайдеры).
* [Crossplane Composition Functions](https://docs.crossplane.io/latest/composition/compositions/) — программируемая инфраструктура (Go/Python/CEL).
* [Flux TF-controller](https://github.com/phoban01/tf-controller) — запуск Terraform в GitOps-стиле внутри кластера.
* [Crossplane provider-terraform](https://github.com/crossplane-contrib/provider-terraform) — управление Terraform-модулями как Kubernetes-ресурсами.
