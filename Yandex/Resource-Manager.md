# Yandex Resource Manager

## Определения

**Resource Manager** — сервис управления иерархией ресурсов и доступом в Yandex Cloud. Определяет базовые сущности для организации инфраструктуры: облака, каталоги, метки и привязки прав.

**Облако (Cloud)** — верхний уровень изоляции с единым биллингом и квотами.

**Каталог (Folder)** — логическая единица развёртывания внутри облака. Соответствует окружению (dev, stage, prod) или продукту.

**Сервисный аккаунт (Service Account)** — учётная запись для аутентификации приложений и сервисов в Yandex Cloud.

---

## Основные концепции

### Иерархия ресурсов

```
┌─────────────────────────────────────────┐
│              Cloud (Облако)             │
│         Биллинг, квоты, лимиты          │
└─────────────────────────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
┌───▼────┐   ┌────▼────┐   ┌────▼────┐
│ Folder │   │ Folder  │   │ Folder  │
│  (dev) │   │ (stage) │   │  (prod) │
└────────┘   └─────────┘   └─────────┘
```

### Ключевые сущности

| Сущность | Назначение | Пример |
| :--- | :--- | :--- |
| **Cloud** | Изоляция, биллинг, квоты | `my-company-cloud` |
| **Folder** | Окружение, продукт, команда | `dev`, `stage`, `prod`, `analytics` |
| **Labels** | Метки для группировки, биллинга, политик | `env=prod`, `owner=team-a`, `cost-center=123` |
| **Service Account** | Аутентификация приложений | `sa-deploy`, `sa-monitoring` |
| **Access Bindings** | Привязки ролей к субъектам | `editor → sa-deploy` |

### Роли и права

**Системные роли:**
- **admin** — полное управление ресурсом
- **editor** — создание и изменение ресурсов
- **viewer** — только просмотр
- **usage** — использование ресурсов

**Сервисные роли:**
- `compute.admin` — управление Compute Cloud
- `vpc.admin` — управление сетями
- `mdb.admin` — управление Managed Databases
- `storage.admin` — управление Object Storage

**Принцип минимальных прав:**
- Назначайте роли на уровне каталога, а не облака
- Используйте узкие сервисные роли вместо `editor`
- Разделяйте права для dev/stage/prod

### Паттерны автоматизации

**Разделение окружений по каталогам:**
- Каждый каталог — отдельный контур развёртывания
- Изолированные права доступа
- Отдельный биллинг и метки

**Bootstrap через сервисный аккаунт:**
- CI/CD работает от имени сервисного аккаунта
- Ограниченные права только на необходимые ресурсы
- Автоматическая ротация ключей

**Декларативное управление доступом:**
- Роли описываются как код (Terraform)
- Версионирование изменений прав
- Аудит через Git history

**Метки как обязательный атрибут:**
- Все ресурсы снабжаются метками `env`, `owner`, `cost-center`
- Автоматическая группировка для биллинга
- Политики доступа на основе меток

---

## Практические сценарии

### Создание каталога и базовых прав через yc CLI

```bash
# Предполагается настроенная аутентификация:
# yc init

# Получить ID облака
CLOUD_ID=$(yc resource-manager cloud list --format json | jq -r '.[0].id')
echo "Cloud ID: $CLOUD_ID"

# Создать каталог с метками
FOLDER_ID=$(yc resource-manager folder get --name ci --format json | jq -r '.id' 2>/dev/null || \
  yc resource-manager folder create \
    --name ci \
    --cloud-id "$CLOUD_ID" \
    --labels env=ci,owner=devops,cost-center=infra \
    --format json | jq -r '.id')

echo "Folder ID: $FOLDER_ID"

# Создать сервисный аккаунт для деплоя
SA_ID=$(yc iam service-account get --name sa-deploy --folder-id "$FOLDER_ID" --format json | jq -r '.id' 2>/dev/null || \
  yc iam service-account create \
    --name sa-deploy \
    --folder-id "$FOLDER_ID" \
    --description "CI/CD deployments" \
    --format json | jq -r '.id')

echo "Service Account ID: $SA_ID"

# Назначить минимально необходимые роли
yc resource-manager folder add-access-binding \
  --id "$FOLDER_ID" \
  --role compute.editor \
  --subject serviceAccount:$SA_ID

yc resource-manager folder add-access-binding \
  --id "$FOLDER_ID" \
  --role vpc.editor \
  --subject serviceAccount:$SA_ID

yc resource-manager folder add-access-binding \
  --id "$FOLDER_ID" \
  --role storage.admin \
  --subject serviceAccount:$SA_ID

# Создать API-ключ для сервисного аккаунта
yc iam key create \
  --service-account-id $SA_ID \
  --output key.json \
  --folder-id "$FOLDER_ID"

# Проверка: список привязок
yc resource-manager folder list-access-bindings --id "$FOLDER_ID"
```

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

CLOUD_ID=$(yc resource-manager cloud list --format json | jq -r '.[0].id')
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

### Аудит и мониторинг ресурсов

```bash
# Список всех каталогов с метками
yc resource-manager folder list --format json | jq '.[] | {
  id: .id,
  name: .name,
  labels: .labels,
  cloud_id: .cloud_id
}'

# Поиск каталогов без меток
yc resource-manager folder list --format json | jq '.[] | select(.labels == null or .labels == {}) | .name'

# Список сервисных аккаунтов в каталоге
yc iam service-account list --folder-id <FOLDER_ID>

# Проверка привязок прав
yc resource-manager folder list-access-bindings --id <FOLDER_ID>

# Экспорт для аудита
yc resource-manager folder list --format json > folders-audit-$(date +%Y%m%d).json
```

### Очистка неиспользуемых ресурсов

```bash
#!/bin/bash
# cleanup-unused.sh

FOLDER_ID=$1

if [ -z "$FOLDER_ID" ]; then
  echo "Usage: $0 <folder-id>"
  exit 1
fi

echo "Scanning folder: $FOLDER_ID"

# Остановленные ВМ
echo "Stopped VMs:"
yc compute instance list --folder-id "$FOLDER_ID" --format json | 
  jq -r '.[] | select(.status == "STOPPED") | "  \(.name) (\(.id))"'

# Несвязанные диски
echo "Unattached disks:"
yc compute disk list --folder-id "$FOLDER_ID" --format json | 
  jq -r '.[] | select(.instance_ids == [] or .instance_ids == null) | "  \(.name) (\(.id))"'

# Старые снапшоты (>30 дней)
echo "Old snapshots:"
yc compute snapshot list --folder-id "$FOLDER_ID" --format json | 
  jq -r '.[] | select(.created_at < "'$(date -d '30 days ago' -Iseconds)'") | "  \(.name) (\(.id))"'

# Удаление (раскомментировать для включения)
# yc compute instance delete --instance-name <name>
# yc compute disk delete --disk-name <name>
# yc compute snapshot delete --snapshot-name <name>
```

---

## Дополнительная информация

### Связанные документы

- **[Compute Cloud](./Compute-Cloud.md)** — управление ВМ в каталогах
- **[VPC](./VPC.md)** — сети и security groups
- **[Storage](./Storage.md)** — хранилища и бакеты

### Интеграции

- **[Terraform](../Concepts/iac_overview.md)** — декларативное управление ресурсами
- **[GitLab CI](../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md)** — автоматизация деплоя
- **[Crossplane](../GitOps/Crossplane/provider_yandex_cloud_setup.md)** — управление через Kubernetes

### Безопасность

- **Принцип минимальных прав** — узкие роли вместо editor
- **Ротация ключей** — регулярная смена API-ключей сервисных аккаунтов
- **Аудит** — логирование всех операций через Cloud Logging
- **Метки** — обязательная маркировка ресурсов

### Best Practices

**Организация каталогов:**
- Один каталог = одно окружение или сервис
- Избегайте более 10 каталогов на облако
- Используйте последовательный нейминг

**Метки:**
- Обязательные: `env`, `owner`, `cost-center`
- Дополнительные: `service`, `team`, `project`
- Автоматическое применение через Terraform

**Сервисные аккаунты:**
- Один аккаунт = одна цель (sa-deploy, sa-monitoring)
- Ротация ключей каждые 90 дней
- Хранение ключей в secrets manager

**Биллинг:**
- Метки для группировки затрат
- Регулярный аудит неиспользуемых ресурсов
- Квоты на уровне каталогов

### Актуальная информация (2025–2026)

- **Лимиты:** до 50 каталогов на облако
- **Метки:** до 20 меток на ресурс
- **IAM:** поддержка OIDC для федерации идентити
