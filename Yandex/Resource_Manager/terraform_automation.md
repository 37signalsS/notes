# Yandex Resource Manager: Автоматизация через Terraform

## Определения

**Terraform Automation** — декларативное управление ресурсами Yandex Cloud через HashiCorp Terraform с версионированием и аудитом изменений.

---

## Практические сценарии

### Terraform: декларативное описание

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
    env        = "ci"
    owner      = "devops"
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

    # Проверка наличия сервисного аккаунта
    - yc iam service-account get --name sa-deploy --folder-id "$YC_FOLDER_ID"

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

### Создание структуры каталогов для микросервисов

```bash
#!/bin/bash
# setup-folders.sh

CLOUD_ID=$(yc resource-manager cloud list --format json | jq -r '.[0](id')
SERVICES=("checkout" "payment" "delivery" "notifications")
ENVIRONMENTS=("dev" "stage" "prod")

for service in "${SERVICES[@]}"; do
  for env in "${ENVIRONMENTS[@]}"; do
    FOLDER_NAME="${service}-${env}"

    # Проверка существования
    FOLDER_ID=$(yc resource-manager folder get --name "$FOLDER_NAME" --format json | jq -r '.id' 2>/dev/null)

    if [ -z "$FOLDER_ID" ]; then
      echo "Creating folder: $FOLDER_NAME"

      FOLDER_ID=$(yc resource-manager folder create \
        --name "$FOLDER_NAME" \
        --cloud-id "$CLOUD_ID" \
        --labels "service=$service,env=$env,owner=platform-team" \
        --format json | jq -r '.id')

      echo "  Folder ID: $FOLDER_ID"
    else
      echo "Folder exists: $FOLDER_NAME (ID: $FOLDER_ID)"
    fi
  done
done
```

---

## Дополнительная информация

### Связанные документы

- **[Overview](./overview.md)** — базовые концепции Resource Manager
- **[IAM Roles](./iam_roles.md)** — роли и права доступа
- **[IAC Overview](../../Concepts/iac_overview.md)** — концепции Infrastructure as Code
