# Terraform и GitLab CI интеграция

**Актуально для:** Terraform 1.7+–1.10+, GitLab 17.x–19.x

> **Примечание:** Полная теория Infrastructure as Code и GitLab CI интеграции описана в **[Infrastructure as Code — обзор](../../Concepts/iac_overview.md)**. Это руководство фокусируется на production-grade настройке Terraform в GitLab CI/CD с state management, plan automation и drift detection.

## Определения

**Terraform** — инструмент Infrastructure as Code (IaC) от HashiCorp для создания, изменения и версионирования инфраструктуры через декларативные конфигурации на языке HCL.

**State file (terraform.tfstate)** — JSON-файл, содержащий текущее состояние управляемой инфраструктуры. Хранится в remote backend для коллективной работы.

**Backend** — механизм хранения state-файла удалённо. Для production используется S3-совместимое хранилище с locking или Consul/etcd/Kubernetes Secrets.

**Workspace** — изолированное окружение внутри одного backend. Позволяет разделить `dev`, `staging`, `production` без дублирования инфраструктуры backend.

**Drift detection** — процесс обнаружения расхождений между желаемым состоянием (код) и фактическим состоянием (инфраструктура). Реализуется через `terraform plan -detailed-exitcode` или `-refresh-only`.

**Quality Gate для IaC** — набор проверок (fmt, validate, plan, security scan), которые должны пройти перед применением изменений.

**Resource group** — механизм GitLab CI/CD, предотвращающий параллельные deployments в одну среду. Гарантирует, что только один `apply` выполняется одновременно.

## Предварительные требования

### Роли и ответственные

| Роль | Обязанности |
| :--- | :--- |
| **DevOps/SRE Engineer** | Настройка пайплайна, backend, drift detection, мониторинг |
| **Terraform Administrator** | Управление модулями, версиями провайдеров, state lifecycle |
| **GitLab Maintainer** | Настройка CI/CD переменных, protected branches, runner'ы |
| **Developer** | Написание HCL-кода, запуск plan, исправление ошибок |
| **Security Engineer** | Настройка SAST/DAST для Terraform, политики Checkov/TFSec |

### Инфраструктура

| Компонент | Требование |
| :--- | :--- |
| **GitLab Runner** | Linux, Docker executor или Kubernetes executor; доступ к backend |
| **State backend** | S3-совместимое хранилище (MinIO, Ceph) + DynamoDB/Consul для locking |
| **Secrets manager** | HashiCorp Vault или GitLab protected/masked variables |
| **Notification** | Slack/PagerDuty/webhook для drift alerts |
| **Linters** | `tflint`, `checkov`, `trivy` в составе pipeline |

### Безопасность

- **Принцип наименьших привилегий:** Runner service account имеет доступ только к необходимым backend/path.
- **Шифрование state:** TLS для backend, encryption at rest для bucket.
- **Секреты:** Никогда не храните `GITLAB_TOKEN`, `AWS_ACCESS_KEY_ID` в коде. Используйте `masked: true`, `protected: true`.
- **Аудит:** Включено логирование всех `terraform apply` через GitLab CI job logs и backend audit log.
- **State locking:** Обязательно для production; предотвращает повреждение state при параллельных запусках.

## Практические сценарии

### Сценарий 1: Базовый Terraform pipeline

```yaml
stages:
  - validate
  - plan
  - apply

variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform
  TF_VERSION: "1.10.0"
  STATE_BUCKET: "terraform-state-$CI_PROJECT_ID"
  STATE_TABLE: "terraform-state-lock"
  TF_IMAGE: "hashicorp/terraform:1.10.0"

before_script:
  - cd $TF_ROOT
  - terraform --version
  - terraform init -backend-config="bucket=$STATE_BUCKET" -backend-config="key=production/terraform.tfstate" -backend-config="region=us-east-1" -backend-config="dynamodb_table=$STATE_TABLE"

validate:
  stage: validate
  image: ${TF_IMAGE}
  script:
    - terraform fmt -check -recursive
    - terraform init -backend=false
    - terraform validate
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

plan:
  stage: plan
  image: ${TF_IMAGE}
  script:
    - terraform plan -out=tfplan -var-file="production.tfvars"
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 7 days
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  dependencies: []

apply:
  stage: apply
  image: ${TF_IMAGE}
  script:
    - terraform apply -auto-approve tfplan
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  dependencies:
    - plan
  allow_failure: false
```

**Валидация:**
- `validate` job завершается с `0` exit code, fmt/validate проходят
- `plan` job создаёт артефакт `tfplan`, видимый в UI GitLab
- `apply` job доступен только вручную, требует approvals

### Сценарий 2: Multi-environment Terraform

```yaml
stages:
  - validate
  - plan
  - apply

variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform
  TF_IMAGE: "hashicorp/terraform:1.10.0"

.validate:
  stage: validate
  image: ${TF_IMAGE}
  script:
    - cd $TF_ROOT
    - terraform init -backend=false
    - terraform fmt -check -recursive
    - terraform validate
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

.plan:
  stage: plan
  image: ${TF_IMAGE}
  script:
    - cd $TF_ROOT
    - terraform init -backend-config="bucket=terraform-state-$CI_PROJECT_ID" -backend-config="key=$ENVIRONMENT/terraform.tfstate" -backend-config="region=us-east-1" -backend-config="dynamodb_table=terraform-state-lock"
    - terraform plan -out=tfplan -var-file="$ENVIRONMENT.tfvars"
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 7 days
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  resource_group: ${CI_PROJECT_NAME}-${ENVIRONMENT}-plan

plan-staging:
  extends: .plan
  variables:
    ENVIRONMENT: "staging"

plan-production:
  extends: .plan
  variables:
    ENVIRONMENT: "production"

.apply:
  stage: apply
  image: ${TF_IMAGE}
  script:
    - cd $TF_ROOT
    - terraform apply -auto-approve tfplan
  environment:
    name: $ENVIRONMENT
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  resource_group: ${CI_PROJECT_NAME}-${ENVIRONMENT}-apply

apply-staging:
  extends: .apply
  variables:
    ENVIRONMENT: "staging"
  dependencies:
    - plan-staging

apply-production:
  extends: .apply
  variables:
    ENVIRONMENT: "production"
  dependencies:
    - plan-production
```

**Валидация:**
- Для каждого окружения создаётся отдельный workspace/state path
- `resource_group` предотвращает параллельные applies в одну среду
- Артефакты `tfplan` хранятся 7 дней

### Сценарий 3: Drift Detection

```yaml
stages:
  - drift-detection

variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform
  TF_IMAGE: "hashicorp/terraform:1.10.0"

drift-detection:
  stage: drift-detection
  image: ${TF_IMAGE}
  script:
    - cd $TF_ROOT
    - terraform init -backend-config="bucket=terraform-state-$CI_PROJECT_ID" -backend-config="key=production/terraform.tfstate" -backend-config="region=us-east-1" -backend-config="dynamodb_table=terraform-state-lock"
    - terraform plan -detailed-exitcode -var-file="production.tfvars" > tfplan.txt || true
    - |
      if [ $? -eq 2 ]; then
        echo "DRIFT_DETECTED=true" >> drift.env
        echo "Drift detected in production infrastructure"
        cat tfplan.txt
      else
        echo "DRIFT_DETECTED=false" >> drift.env
        echo "No drift detected"
      fi
  artifacts:
    reports:
      dotenv: drift.env
    paths:
      - tfplan.txt
    expire_in: 7 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      cron: "0 6 * * 1-5"
  resource_group: ${CI_PROJECT_NAME}-drift

notify-drift:
  stage: drift-detection
  image: curlimages/curl:8.8.0
  script:
    - |
      if [ "$DRIFT_DETECTED" = "true" ]; then
        curl -X POST "$SLACK_WEBHOOK" \
          -H "Content-Type: application/json" \
          -d '{
            "text": "⚠️ Drift detected in production infrastructure!\nPipeline: $CI_PIPELINE_URL"
          }'
      fi
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      cron: "0 6 * * 1-5"
  when: on_failure
```

**Валидация:**
- Scheduled pipeline запускается в будни в 06:00 UTC
- При drift создаётся artifact `tfplan.txt` и dotenv-отчёт
- Уведомление отправляется только при обнаружении drift

### Сценарий 4: Terraform с GitLab Provider

```hcl
# terraform/main.tf
terraform {
  required_version = ">= 1.7.0"

  backend "s3" {
    bucket         = "terraform-state"
    key            = "production/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "terraform-state-lock"
    encrypt        = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    gitlab = {
      source  = "gitlabhq/gitlab"
      version = "~> 17.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

provider "gitlab" {
  token = var.gitlab_token
  base_url = "https://gitlab.example.com"
}

resource "aws_s3_bucket" "app_data" {
  bucket = "myapp-data-${data.aws_caller_identity.current.account_id}"
}

resource "gitlab_project" "app_project" {
  name        = "my-app"
  namespace_id = data.gitlab_group.app_group.id
  visibility_level = "private"
}
```

```yaml
# .gitlab-ci.yml
variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform
  GITLAB_TOKEN: $GITLAB_TOKEN

stages:
  - validate
  - plan
  - apply

validate:
  stage: validate
  image: hashicorp/terraform:1.10.0
  script:
    - cd $TF_ROOT
    - terraform init -backend=false
    - terraform fmt -check -recursive
    - terraform validate

plan:
  stage: plan
  image: hashicorp/terraform:1.10.0
  script:
    - cd $TF_ROOT
    - terraform init -backend-config="bucket=terraform-state-$CI_PROJECT_ID" -backend-config="key=production/terraform.tfstate" -backend-config="region=us-east-1" -backend-config="dynamodb_table=terraform-state-lock"
    - terraform plan -out=tfplan
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 7 days

apply:
  stage: apply
  image: hashicorp/terraform:1.10.0
  script:
    - cd $TF_ROOT
    - terraform apply -auto-approve tfplan
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Валидация:**
- GitLab provider создаёт проекты/группы через API
- Переменная `GITLAB_TOKEN` должна быть `protected`, `masked`
- Plan включает изменения как в AWS, так и в GitLab ресурсы

### Сценарий 5: Automated Plan для MR

```yaml
stages:
  - validate
  - plan

variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform
  TF_IMAGE: "hashicorp/terraform:1.10.0"

.terraform:
  image: ${TF_IMAGE}
  before_script:
    - cd $TF_ROOT
    - terraform init -backend=false
    - terraform workspace select staging || terraform workspace new staging

terraform-plan:
  stage: plan
  extends: .terraform
  script:
    - terraform plan -out=tfplan -var-file="staging.tfvars"
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 7 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "terraform/**/*"
  allow_failure: false

terraform-fmt:
  stage: validate
  image: ${TF_IMAGE}
  script:
    - cd $TF_ROOT
    - terraform fmt -check -recursive
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "terraform/**/*"

terraform-validate:
  stage: validate
  image: ${TF_IMAGE}
  script:
    - cd $TF_ROOT
    - terraform init -backend=false
    - terraform validate
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "terraform/**/*"
```

**Валидация:**
- Jobs запускаются только при изменениях в директории `terraform/`
- Plan артефакт виден в Merge Request widget
- Workspace `staging` создаётся автоматически

### Сценарий 6: Security Scanning для Terraform

```yaml
stages:
  - security
  - plan

variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform
  TF_IMAGE: "hashicorp/terraform:1.10.0"

terraform-sast:
  stage: security
  image: aquasec/trivy:0.74.0
  script:
    - trivy fs --scanners vuln,secret --format json --output trivy-report.json $TF_ROOT
  artifacts:
    reports:
      sast: trivy-report.json
    expire_in: 30 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

terraform-compliance:
  stage: security
  image: eerkunt/terraform-compliance:1.4.0
  script:
    - terraform-compliance -p $TF_ROOT -f compliance/aws-iam.yml
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

terraform-tfsec:
  stage: security
  image: aquasec/tfsec:1.3.1
  script:
    - tfsec $TF_ROOT --format json --out tfsec-report.json
  artifacts:
    reports:
      sast: tfsec-report.json
    expire_in: 30 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Валидация:**
- `trivy` сканирует уязвимости и секреты в коде
- `terraform-compliance` проверяет соответствие политикам
- Отчёты экспортируются как SAST reports для GitLab Security Dashboard

### Сценарий 7: Air-gapped среда

```yaml
variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform
  TF_IMAGE: "registry.internal.company.com/hashicorp/terraform:1.10.0"
  STATE_BUCKET: "terraform-state-$CI_PROJECT_ID"

stages:
  - validate
  - plan
  - apply

before_script:
  - cd $TF_ROOT
  - terraform init -backend-config="bucket=$STATE_BUCKET" -backend-config="key=production/terraform.tfstate" -backend-config="region=us-east-1" -backend-config="dynamodb_table=terraform-state-lock" -backend-config="skip_credentials_validation=true"

validate:
  stage: validate
  image: ${TF_IMAGE}
  script:
    - terraform init -backend=false -plugin-dir=/terraform-plugins
    - terraform fmt -check -recursive
    - terraform validate
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

plan:
  stage: plan
  image: ${TF_IMAGE}
  script:
    - terraform plan -out=tfplan -var-file="production.tfvars"
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 7 days
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

apply:
  stage: apply
  image: ${TF_IMAGE}
  script:
    - terraform apply -auto-approve tfplan
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Валидация:**
- Образ Terraform загружен в внутренний registry
- Провайдеры кешируются в `/terraform-plugins`
- Backend инициализируется с `skip_credentials_validation=true` при отсутствии внешнего доступа

### Сценарий 8: Отключение Quality Gate для emergency

```yaml
variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform
  TF_IMAGE: "hashicorp/terraform:1.10.0"

stages:
  - validate
  - plan
  - apply

emergency-apply:
  stage: apply
  image: ${TF_IMAGE}
  script:
    - cd $TF_ROOT
    - terraform init -backend-config="bucket=terraform-state-$CI_PROJECT_ID" -backend-config="key=production/terraform.tfstate"
    - terraform apply -auto-approve -var-file="production.tfvars"
  environment:
    name: production
  rules:
    - if: $CI_PIPELINE_SOURCE == "push"
      when: manual
      allow_failure: false
    - if: $CI_PIPELINE_SOURCE == "web"
  when: manual
  allow_failure: false
```

**Валидация:**
- Job доступен только вручную или через web-триггер
- Требуется approval от настройщика protected branch
- Используйте только для production incidents

## Конфигурация

### Переменные окружения

| Переменная | Описание | Обязательность |
| :--- | :--- | :--- |
| `TF_ROOT` | Путь к директории с Terraform конфигурацией | Да |
| `TF_IMAGE` | Образ Terraform для runner'ов | Да |
| `STATE_BUCKET` | Имя bucket/backend для хранения state | Да |
| `STATE_TABLE` | Таблица/сервис для state locking | Да |
| `GITLAB_TOKEN` | Токен для GitLab provider | При использовании provider |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Credentials для S3 backend | При использовании S3 |
| `SLACK_WEBHOOK` | Webhook для уведомлений | При drift detection |

### Backend configuration

```hcl
# terraform/backend.hcl
bucket         = "terraform-state-${CI_PROJECT_ID}"
key            = "production/terraform.tfstate"
region         = "eu-central-1"
dynamodb_table = "terraform-state-lock"
encrypt        = true
```

```yaml
# .gitlab-ci.yml
before_script:
  - terraform init -backend-config="bucket=$STATE_BUCKET" -backend-config="key=production/terraform.tfstate" -backend-config="region=us-east-1" -backend-config="dynamodb_table=$STATE_TABLE"
```

### Caching provider plugins

```yaml
cache:
  key: ${TF_IMAGE}
  paths:
    - .terraform/
    - .terraform.d/plugin-cache/
```

Ускоряет пайплайн за счёт повторного использования провайдеров между job.

### GitLab Provider configuration

```hcl
variable "gitlab_token" {
  type        = string
  sensitive   = true
}

provider "gitlab" {
  token   = var.gitlab_token
  base_url = "https://gitlab.example.com"
}
```

## Валидация и проверка

1. **Plan output:** Проверьте output `terraform plan` — должен отображаться корректный план изменений без ошибок синтаксиса.
2. **State lock:** Запустите два plan параллельно — второй должен ждать освобождения lock (`resource_group` или backend locking).
3. **Drift detection:** Запустите drift detection job вручную — при наличии drift в выводе будет `2` exit code.
4. **Workspace:** Проверьте, что workspaces создаются корректно: `terraform workspace list`.
5. **Backend connectivity:** `terraform init` завершается без ошибок; `terraform state pull` возвращает валидный JSON.
6. **Secrets masking:** Проверьте логи job — чувствительные переменные не отображаются.
7. **Security scans:** `trivy`, `tfsec` завершаются с `0` exit code при отсутствии критических уязвимостей.
8. **Artifacts:** Plan артефакт (`tfplan`) загружен, доступен для скачивания в UI.

## Operations and Commands

### Управление пайплайном

```bash
# Запуск pipeline вручную
gitlab-runner exec docker terraform-plan --var-file="production.tfvars"

# Просмотр drift detection отчёта
gitlab-runner exec docker drift-detection

# Откат к предыдущему state
terraform state pull > backup.tfstate
terraform state push backup.tfstate
```

### Управление state

```bash
# Просмотр state
terraform state list
terraform state show aws_instance.example

# Импорт существующего ресурса
terraform import aws_instance.example i-1234567890abcdef0

# Удаление ресурса из state (не удаляет сам ресурс)
terraform state rm aws_instance.example

# Force-unlock при зависшем lock
terraform force-unlock LOCK_ID
```

### Управление workspaces

```bash
# Создание workspace
terraform workspace new staging

# Переключение workspace
terraform workspace select staging

# Список workspaces
terraform workspace list

# Удаление workspace
terraform workspace delete production
```

### Управление провайдерами

```bash
# Просмотр провайдеров
terraform providers

# Кеширование провайдеров
mkdir -p ~/.terraform.d/plugin-cache
terraform init -plugin-dir ~/.terraform.d/plugin-cache
```

### Резервное копирование state

```bash
# Backup через GitLab CI job
terraform state pull > backup-${CI_COMMIT_SHORT_SHA}.tfstate
terraform state push backup-${CI_COMMIT_SHORT_SHA}.tfstate
```

## Troubleshooting

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **State lock failed** | State занят другим процессом | Проверьте, что предыдущий apply завершился. Используйте `force-unlock` только при необходимости. |
| **Backend initialization failed** | Неверные credentials или bucket не существует | Проверьте AWS/GCP credentials и существование bucket |
| **Plan shows unexpected changes** | Drift в инфраструктуре | Запустите `terraform apply` или исправьте инфраструктуру вручную |
| **Workspace not found** | Workspace не создан | Создайте workspace: `terraform workspace new staging` |
| **Provider version mismatch** | Неверная версия провайдера | Укажите точную версию в `required_providers` |
| **Plan artifact missing** | Задача завершилась с ошибкой | Проверьте логи задачи и убедитесь, что `terraform plan` завершился успешно |
| **Drift false positive** | Некорректный plan | Проверьте, что backend-config корректен и state актуален |
| **Compute Engine OOM** | Недостаточно памяти для больших state | Увеличьте RAM runner'а или разбейте конфигурацию на модули |
| **Database connection failed** | Сеть между runner и backend/DB недоступна | Проверьте firewall, DNS, routing между runner и backend |
| **License plugin error** | Провайдер требует лицензию | Проверьте `TF_LICENSE` переменную или перейдите на OpenTofu |
| **GIT_DEPTH insufficient** | Shallow clone не содержит полной истории | Установите `GIT_DEPTH: 0` для полного клонирования |
| **Token expiry** | `GITLAB_TOKEN` истёк | Обновите токен в CI/CD variables, проверьте срок действия |
| **Compute Engine recovery** | State повреждён после падения runner | Восстановите из backup: `terraform state push backup.tfstate` |

## Лучшие практики (Best Practices)

### Разработка (Dev)

1. **Форматирование:** Запускайте `terraform fmt -check` на каждом коммите.
2. **Валидация:** `terraform validate` перед push; добавьте в pre-commit hook.
3. **Документация:** Используйте `terraform-docs` для генерации README из модулей.
4. **Версионирование провайдеров:** Указывайте exact версии в `required_providers`.
5. **Модульность:** Разбивайте конфигурацию на переиспользуемые модули.

### DevOps/SRE

1. **State locking:** Обязательно для production. Используйте `resource_group` + backend locking.
2. **Drift detection:** Запускайте по расписанию (weekly) с алертами в Slack/PagerDuty.
3. **Резервное копирование state:** Бэкап перед каждым `apply`, retention 30–90 дней.
4. **Мониторинг:** Алерты на недоступность backend, timeout'ы locking, failures drift detection.
5. **Ретенция артефактов:** Ограничьте хранение `tfplan` артефактов (7–30 дней).
6. **Очередь deployments:** Используйте `resource_group` для последовательного применения в production.

### Sysadmin

1. **Доступ к backend:** Только CI/CD service account имеет права на state bucket/table.
2. **TLS:** Для всех backend (Consul, etcd, HTTP, S3) используйте только TLS.
3. **Аудит:** Включите audit logging для backend и GitLab CI job logs.
4. **Ретенция state:** Удаляйте старые версии state (>90 дней) через lifecycle policy.
5. **Мониторинг backend:** Алерты при недоступности Consul/etcd/K8s API/S3.
6. **Резервное копирование:** Регулярный backup state в отдельный bucket/region.
7. **Сеть:** Runner'ы имеют статический IP, разрешённый в firewall backend.

### Monitoring

```yaml
# Пример метрик для Prometheus
terraform_plan_duration_seconds
terraform_apply_duration_seconds
terraform_state_lock_wait_seconds
terraform_drift_detection_status{project="..."}
terraform_backend_errors_total
```

## Ограничения и крайние случаи

### Ограничения

*   **State lock при long-running apply:** Длительные `terraform apply` (>30 минут) могут вызывать таймауты в GitLab Runner. Решение: увеличение `timeout` в job, использование `resource_group`, или split apply на несколько stage.
*   **Workspace naming conflicts:** OpenTofu/Terraform запрещают невалидные workspace names. Валидация имени workspace должна происходить до `terraform workspace select`.
*   **Concurrent apply protection:** Только один `resource_group` на среду. Для разных проектов, работающих с одним backend, требуется внешний координатор (Consul lock, etcd).
*   **State file size:** Большие state-файлы (>100 МБ) замедляют `plan` и `apply`. Решение: разделение на модули и workspaces.
*   **Provider plugin caching:** Повторная загрузка провайдеров на каждом job замедляет пайплайн. Решение: GitLab CI caching для `.terraform` directory.
*   **Local backend в CI:** Использование `local` backend в CI приводит к тому, что state теряется между job. Решение: всегда remote backend.
*   **Hardcoded credentials:** Хранение bucket names и credentials в коде. Решение: переменные окружения и secrets manager.

### Типичные ошибки

*   **Manual changes в production:** Прямые изменения через консоль/SSH приводят к drift. Решение: строгая политика "все изменения через IaC".
*   **Отсутствие `resource_group`:** Параллельные deployments в production могут вызвать state corruption. Решение: `resource_group` на apply stage.
*   **Drift false positive:** Некорректный backend-config или устаревший state. Решение: проверка `terraform init` и `terraform state pull`.

## Очистка

```bash
# Удаление resources через Terraform
cd terraform && terraform destroy -var-file="production.tfvars" -auto-approve

# Очистка orphaned resources
terraform state list | while read resource; do
  if ! terraform state show $resource > /dev/null 2>&1; then
    echo "Removing orphaned state: $resource"
    terraform state rm $resource
  fi
done

# Удаление workspace
terraform workspace delete production

# Очистка GitLab CI artifacts и кэша
gitlab-runner cache clear

# Удаление state backup'ов (старше 90 дней)
find ./backups -name "*.tfstate" -mtime +90 -delete
```

## Дополнительная информация

### Смотрите также

- **[Infrastructure as Code — обзор](../../Concepts/iac_overview.md)** — теория IaC, Terraform basics
- **[GitLab CI/CD для IaC пайплайнов](../Advanced/gitlab_ci_iac_pipelines.md)** — backends, drift detection, state management, OpenTofu
- **[Container Registry](../Advanced/container_registry.md)** — управление образами
- **[Policy-as-Code в GitLab CI](../Advanced/policy_as_code.md)** — OPA, Checkov, TFLint, Trivy
- **[Cost Optimization в CI/CD](../../Core_Concepts/cost-optimization.md)** — оценка стоимости инфраструктуры
- **[Terraform State Management](https://developer.hashicorp.com/terraform/language/state)** — официальная документация
- **[Terraform Best Practices](https://developer.hashicorp.com/terraform/language/state/workspaces)** — workspace management
