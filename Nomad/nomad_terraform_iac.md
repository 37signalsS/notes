# Nomad — Terraform и Infrastructure as Code

## Определения

**Infrastructure as Code (IaC)** — подход к управлению инфраструктурой, при котором конфигурация серверов, сетей и приложений описывается декларативно в виде кода, версионируется в Git и применяется автоматически.

**Terraform Provider Nomad** — официальный провайдер HashiCorp, позволяющий управлять ресурсами Nomad-кластера (джобы, ACL-политики, неймспейсы, квоты, volumes) через HCL-конфигурацию Terraform.

**nomad_job** — ресурс Terraform для декларативного управления Nomad-джобами. Поддерживает параметризацию, plan перед применением и автоматический откат.

**nomad_acl_policy** — ресурс Terraform для управления ACL-политиками Nomad через код.

## Основные концепции

### Зачем Terraform для Nomad

| Задача | Без Terraform | С Terraform |
| :--- | :--- | :--- |
| Деплой джоба | `nomad job run` вручную | `terraform apply` с plan |
| Управление ACL | `nomad acl` CLI-команды | Декларативные политики в коде |
| Неймспейсы и квоты | Ручное создание | Версионированные ресурсы |
| Multi-environment | Копирование конфигов | Модули и workspace |
| State tracking | Нет | Terraform state |

### Архитектура взаимодействия

```
Git Repository (HCL)
       ↓
  terraform plan
       ↓
  terraform apply
       ↓
  Nomad Provider → Nomad API → Nomad Cluster
       ↓
  Terraform State (local/S3/Consul)
```

### Основные ресурсы провайдера

| Ресурс | Назначение |
| :--- | :--- |
| `nomad_job` | Управление джобами (основной ресурс) |
| `nomad_acl_policy` | ACL-политики |
| `nomad_acl_token` | ACL-токены |
| `nomad_namespace` | Неймспейсы (Enterprise) |
| `nomad_quota_spec` | Квоты (Enterprise) |
| `nomad_volume` | CSI и host-тома |
| `nomad_sentinel_policy` | Sentinel-политики (Enterprise) |

## Практические сценарии

### Сценарий 1: Базовая конфигурация провайдера

```hcl
# provider.tf
terraform {
  required_providers {
    nomad = {
      source  = "hashicorp/nomad"
      version = "~> 2.0"
    }
  }
}

provider "nomad" {
  address = var.nomad_addr
  token   = var.nomad_token
  # Для Self-Signed сертификатов:
  # cert_file = "nomad-client.pem"
  # key_file  = "nomad-client-key.pem"
  # ca_cert_file = "nomad-ca.pem"
}

variable "nomad_addr" {
  type        = string
  description = "Nomad API address"
}

variable "nomad_token" {
  type        = string
  sensitive   = true
  description = "Nomad ACL token"
}
```

### Сценарий 2: Деплой микросервиса

```hcl
# variables.tf
variable "app_version" {
  type    = string
  default = "latest"
}

variable "replicas" {
  type    = number
  default = 3
}

# main.tf
resource "nomad_job" "webapp" {
  jobspec = file("${path.module}/templates/webapp.nomad.hcl")

  var {
    name  = "image_version"
    value = var.app_version
  }

  var {
    name  = "replica_count"
    value = var.replicas
  }
}
```

**templates/webapp.nomad.hcl:**
```hcl
job "webapp" {
  datacenters = ["dc1"]
  type        = "service"

  update {
    max_parallel     = 2
    health_check     = "checks"
    min_healthy_time = "30s"
    healthy_deadline = "5m"
    auto_revert      = true
  }

  group "app" {
    count = var.replica_count

    network {
      port "http" { to = 8080 }
    }

    service {
      name     = "webapp"
      port     = "http"
      provider = "nomad"

      check {
        type     = "http"
        path     = "/health"
        interval = "10s"
        timeout  = "2s"
      }
    }

    task "server" {
      driver = "docker"

      config {
        image = "registry/webapp:${var.image_version}"
        ports = ["http"]
      }

      resources {
        cpu    = 500
        memory = 256
      }
    }
  }
}
```

### Сценарий 3: Управление ACL через Terraform

```hcl
# acl.tf
resource "nomad_acl_policy" "ci_cd" {
  name        = "ci-cd-deployer"
  description = "Policy for CI/CD pipelines"

  rules_hcl = <<-EOT
    namespace "production" {
      policy       = "write"
      capabilities = ["submit-job", "read-job", "list-jobs"]
    }

    namespace "staging" {
      policy       = "write"
      capabilities = ["submit-job", "read-job", "list-jobs", "destroy-job"]
    }
  EOT
}

resource "nomad_acl_token" "ci_cd" {
  name     = "ci-cd-token"
  type     = "client"
  policies = [nomad_acl_policy.ci_cd.name]
}

output "ci_cd_token" {
  value     = nomad_acl_token.ci_cd.secret_id
  sensitive = true
}
```

### Сценарий 4: Multi-environment через Workspace

```hcl
# environments/production/main.tf
module "app" {
  source = "../../modules/nomad-app"

  app_version   = var.app_version
  replicas      = 5
  datacenters   = ["dc1"]
  nomad_addr    = var.nomad_addr
  nomad_token   = var.nomad_token
}

# environments/staging/main.tf
module "app" {
  source = "../../modules/nomad-app"

  app_version   = var.app_version
  replicas      = 2
  datacenters   = ["dc1"]
  nomad_addr    = var.nomad_addr
  nomad_token   = var.nomad_token
}
```

**Использование workspace:**
```bash
# Создание workspace для staging
terraform workspace new staging
terraform apply -var="app_version=v2.1"

# Переключение на production
terraform workspace select production
terraform apply -var="app_version=v2.1"
```

### Сценарий 5: CSI Volume через Terraform

```hcl
resource "nomad_volume" "postgres" {
  type        = "csi"
  plugin_id   = "aws-ebs"
  volume_id   = "postgres-data"
  name        = "postgres-data"
  capacity_min = "10Gi"
  capacity_max = "100Gi"

  capability {
    access_mode     = "single-node-writer"
    attachment_mode = "file-system"
  }

  mount_options {
    fs_type = "ext4"
  }
}
```

### Сценарий 6: Nomad + Consul KV через Terraform

```hcl
resource "consul_key_prefix" "app_config" {
  path_prefix = "config/app/"

  value {
    key   = "database_url"
    value = "postgres://db.service.consul:5432/mydb"
  }

  value {
    key   = "log_level"
    value = "info"
  }
}
```

## Workflow: terraform plan → apply

```bash
# 1. Инициализация
terraform init

# 2. План (dry-run)
terraform plan -var="app_version=v2.1" -out=tfplan

# 3. Применение
terraform apply tfplan

# 4. Проверка
terraform state show nomad_job.webapp

# 5. Откат (если нужно)
terraform apply -var="app_version=v2.0"
# Или
terraform destroy -target=nomad_job.webapp
```

## Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Error: Failed to create job` | Невалидный HCL или нет прав | Проверьте `nomad job validate` и ACL |
| `Error: Job already exists` | Джоб уже управляетcя Terraform | Импортируйте: `terraform import nomad_job.webapp webapp` |
| `Error: State locked` | Другой процесс применяет state | Освободите lock: `terraform force-unlock <ID>` |
| `Provider produced inconsistent result` | API timeout при изменении | Повторите apply; увеличьте timeouts |

## Дополнительная информация

- [Nomad — CI/CD Pipeline](./nomad_cicd_pipeline.md) — автоматизация деплоя.
- [Nomad — определения и базовые концепции](./definitions_and_concepts.md) — основы Nomad.
- [Terraform Provider Nomad](https://registry.terraform.io/providers/hashicorp/nomad/latest/docs) — официальная документация.
