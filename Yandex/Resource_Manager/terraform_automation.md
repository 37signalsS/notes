# Yandex Resource Manager: Автоматизация через Terraform

## 1. Определения

**Terraform Automation** — декларативное управление ресурсами Yandex Cloud через HashiCorp Terraform с версионированием и аудитом изменений.

---

## 2. Базовые концепции

### Ресурсы Terraform для Resource Manager

Основные ресурсы провайдера `yandex`:

- `yandex_resourcemanager_folder` — создание и настройка каталогов.
- `yandex_iam_service_account` — сервисные аккаунты.
- `yandex_resourcemanager_folder_iam_binding` — привязка ролей к субъектам.
- `yandex_iam_service_account_key` — API-ключи сервисных аккаунтов.

### Структура конфигурации

Конфигурация состоит из трёх блоков: `variable` (входные параметры), `provider` (аутентификация в Yandex Cloud), `resource` (описание ресурсов). Чувствительные данные (`token`, `key_file`) маркируются как `sensitive`.

### Интеграция с CI/CD

Terraform запускается из CI/CD-пайплайна ([GitLab CI](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md)): валидация через `terraform plan`, применение через `terraform apply`. Ключи сервисных аккаунтов передаются через CI/CD-переменные.

---

## 3. Практические сценарии

### Terraform: декларативное описание структуры

```hcl
# main.tf
variable "cloud_id" {
  type        = string
  description = "Yandex Cloud ID"
}

variable "yc_token" {
  type        = string
  description = "Yandex Cloud IAM token"
  sensitive   = true
}

provider "yandex" {
  token                  = var.yc_token
  cloud_id               = var.cloud_id
  service_account_key_file = "key.json"
}

# Каталог для CI/CD
resource "yandex_resourcemanager_folder" "ci" {
  cloud_id = var.cloud_id
  name     = "ci"

  labels = {
    env         = "ci"
    owner       = "devops"
    cost_center = "infra"
  }
}

# Сервисный аккаунт для деплоя
resource "yandex_iam_service_account" "deploy" {
  name        = "sa-deploy"
  folder_id   = yandex_resourcemanager_folder.ci.id
  description = "CI/CD deployments"
}

# Роли для сервисного аккаунта
resource "yandex_resourcemanager_folder_iam_binding" "compute_editor" {
  folder_id = yandex_resourcemanager_folder.ci.id
  role      = "compute.editor"

  members = [
    "serviceAccount:${yandex_iam_service_account.deploy.id}"
  ]
}

resource "yandex_resourcemanager_folder_iam_binding" "vpc_editor" {
  folder_id = yandex_resourcemanager_folder.ci.id
  role      = "vpc.editor"

  members = [
    "serviceAccount:${yandex_iam_service_account.deploy.id}"
  ]
}

resource "yandex_resourcemanager_folder_iam_binding" "storage_admin" {
  folder_id = yandex_resourcemanager_folder.ci.id
  role      = "storage.admin"

  members = [
    "serviceAccount:${yandex_iam_service_account.deploy.id}"
  ]
}

# API-ключ для сервисного аккаунта
resource "yandex_iam_service_account_key" "deploy_key" {
  service_account_id = yandex_iam_service_account.deploy.id
  description        = "API key for CI/CD"
  output_file        = "sa-deploy-key.json"
}
```

### GitLab CI: интеграция с Resource Manager

```yaml
# .gitlab-ci.yml
variables:
  YC_CLOUD_ID: $YC_CLOUD_ID
  YC_FOLDER_ID: $YC_FOLDER_ID
  YC_SERVICE_ACCOUNT_KEY_FILE: $YC_SA_KEY_FILE

stages:
  - validate
  - deploy

validate:
  stage: validate
  image: yandexcloud/yandex-cli:latest
  script:
    # Проверка контекста перед деплоем
    - echo "$YC_SERVICE_ACCOUNT_KEY_FILE" > key.json
    - yc config set cloud-id "$YC_CLOUD_ID"
    - yc config set folder-id "$YC_FOLDER_ID"

    # Проверка доступов и меток каталога
    - yc resource-manager folder get --id "$YC_FOLDER_ID" --format json |
      jq -e '.labels.env=="ci"'

deploy:
  stage: deploy
  image: hashicorp/terraform:latest
  script:
    - echo "$YC_SERVICE_ACCOUNT_KEY_FILE" > key.json
    - terraform init
    - terraform plan -out=tfplan
    - terraform apply -auto-approve tfplan
  only:
    - main
```

---

## 4. Дополнительная информация

### Связанные документы

- **[Overview](./overview.md)** — базовые концепции Resource Manager.
- **[IAM Роли и права доступа](./iam_roles.md)** — управление доступом.
- **[IAC Overview](../../Concepts/iac_overview.md)** — концепции Infrastructure as Code.
