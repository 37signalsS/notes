# Let's Encrypt: Управление сертификатами через Terraform

## Определения

**ACME Terraform Provider** (`vancluever/terraform-provider-acme`) — Terraform-провайдер, позволяющий автоматизировать жизненный цикл сертификатов Let's Encrypt (и других ACME-совместимых CA) через HCL-конфигурации. Провайдер взаимодействует с ACME API напрямую, без посредников (cert-manager, certbot), и управляет ресурсами: аккаунт, регистрация, сертификат и приватный ключ.

**`tls_private_key`** — встроенный ресурс Terraform (`hashicorp/tls` провайдер) для генерации асимметричных ключей (RSA, ECDSA) прямо в Terraform-state. Используется для создания CSR и ключей, передаваемых в ACME-провайдер.

**`tls_locally_signed_cert`** — ресурс Terraform для подписания сертификатов локальным CA. Применим для создания внутренних сертификатов в связке с Vault PKI или self-signed CA.

**`terraform-provider-acme`** — основной провайдер для интеграции Terraform с ACME. Поддерживает HTTP-01 и DNS-01 через встроенные провайдеры DNS (Cloudflare, Route53, AzureDNS, GoogleDNS, Gandi, DigitalOcean, OVH, 暂不支持 Webhook).

**`acme_certificate`** — ресурс Terraform, управляющий заказом сертификата через ACME. Содержит URI аккаунта, CSR, ключи и настройки проверки владения доменом.

---

## Основные концепции

### Когда использовать Terraform вместо cert-manager

| Сценарий | Terraform ACME | cert-manager |
| :--- | :--- | :--- |
| **Non-Kubernetes инфраструктура** | Да — VM, bare metal, CI/CD | Только Kubernetes |
| **IaC-first подход** | Да — сертификаты как код | Да — через CRD |
| **Простая автоматизация** | Да — несколько ресурсов | Да — но требует Kubernetes API |
| **Управление state** | Terraform state | Kubernetes etcd |
| **Multi-cloud DNS-01** | Да — через TLS-провайдеры DNS | Да — через DNS-01 solver |
| **Сложная логика условий** | Да — HCL-выражения | Ограниченно |
| **GitOps / ArgoCD** | Ограниченно | Да — CRD в Git |

**Рекомендация:** Для Kubernetes-кластеров cert-manager является стандартом de facto. Terraform ACME provider подходит для:
- Внешних серверов (nginx, HAProxy, Traefik без Kubernetes)
- DNS-провайдеров, которые cert-manager не поддерживает
- Гибридных сред (VM + Kubernetes)
- Простых автоматизаций (один сервер, один домен)

### Архитектура Terraform ACME

```
┌─────────────────────────────────────────────┐
│  Terraform HCL                              │
│  ├── provider "acme" (URL, email)           │
│  ├── resource "acme_registration"           │
│  ├── resource "tls_private_key"             │
│  ├── resource "acme_certificate"            │
│  └── resource "local_file" (cert, key)      │
└──────────────────────┬──────────────────────┘
                       │ ACME API (RFC 8555)
                       ▼
┌─────────────────────────────────────────────┐
│  Let's Encrypt                              │
│  ├── newAccount → Регистрация               │
│  ├── newOrder → Заказ сертификата           │
│  ├── Challenge → Проверка владения (DNS)    │
│  └── certificate → Получение сертификата    │
└─────────────────────────────────────────────┘
```

### Провайдеры DNS-01 для Terraform

Terraform ACME provider поддерживает DNS-01 через встроенные провайдеры:

| DNS-провайдер | Terraform-провайдер | Ключевые параметры |
| :--- | :--- | :--- |
| **Cloudflare** | `cloudflare` | `api_token`, `zone_id` |
| **AWS Route53** | `aws` | `aws_region`, IAM credentials |
| **Azure DNS** | `azurerm` | `subscription_id`, `tenant_id`, Service Principal |
| **Google Cloud DNS** | `google` | `project`, Service Account |
| **Gandi** | `gandi` | `personal_access_token` |
| **DigitalOcean** | `digitalocean` | `token` |
| **OVH** | `ovh` | `application_key`, `application_secret`, `consumer_key` |

> **Ограничение:** Terraform ACME provider **не поддерживает** произвольные DNS-провайдеры через webhook (в отличие от cert-manager). Для нестандартных DNS-провайдеров используется `acme_certificate` с ресурсами `dns TXT` через API-провайдер конкретного DNS.

---

## Практические сценарии

### Сценарий 1: Базовый сертификат через HTTP-01 (Cloudflare + Nginx)

Минимальная конфигурация для получения сертификата Let's Encrypt на внешнем сервере.

```hcl
terraform {
  required_providers {
    acme = {
      source  = "vancluever/acme"
      version = "~> 2.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }
  required_version = ">= 1.5"
}

# Провайдер ACME
provider "acme" {
  server_url = "https://acme-v02.api.letsencrypt.org/directory"
}

# Провайдер Cloudflare (для DNS-01)
provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

variable "cloudflare_api_token" {
  description = "Cloudflare API Token с правами Zone:DNS:Edit"
  type        = string
  sensitive   = true
}

# Регистрация ACME-аккаунта
resource "acme_registration" "letsencrypt" {
  account_key_pem = tls_private_key.acme_account.private_key_pem
  email_address   = "admin@example.com"
}

# Генерация ключа аккаунта
resource "tls_private_key" "acme_account" {
  algorithm = "ECDSA"
  ecdsa_curve = "P-256"
}

# Генерация ключа сертификата
resource "tls_private_key" "cert" {
  algorithm = "ECDSA"
  ecdsa_curve = "P-256"
}

# Создание CSR
resource "tls_cert_request" "cert" {
  private_key_pem = tls_private_key.cert.private_key_pem
  subject {
    common_name  = "app.example.com"
    organization = "Example Org"
  }
}

# Получение сертификата через ACME с DNS-01
resource "acme_certificate" "cert" {
  account_key_pem           = acme_registration.letsencrypt.account_key_pem
  common_name               = "app.example.com"
  subject_alternative_names = ["www.example.com"]

  # DNS-01 через Cloudflare
  dns_challenge {
    provider = "cloudflare"

    config = {
      CLOUDFLARE_API_TOKEN = var.cloudflare_api_token
      CLOUDFLARE_ZONE_ID   = var.cloudflare_zone_id
    }
  }

  # Принудительное продление за 30 дней до истечения
  min_days_remaining = 30
}

variable "cloudflare_zone_id" {
  description = "Cloudflare Zone ID для DNS-записей"
  type        = string
  sensitive   = true
}

# Сохранение сертификата и ключа
resource "local_file" "cert" {
  content         = acme_certificate.cert.certificate_pem
  filename        = "/etc/ssl/certs/app.example.com.crt"
  file_permission = "0644"
}

resource "local_file" "key" {
  content         = tls_private_key.cert.private_key_pem
  filename        = "/etc/ssl/private/app.example.com.key"
  file_permission = "0600"
}

resource "local_file" "chain" {
  content         = acme_certificate.cert.certificate_pem
  filename        = "/etc/ssl/certs/app.example.com.chain.crt"
  file_permission = "0644"
}

output "certificate_id" {
  value = acme_certificate.cert.id
}

output "certificate_expiry" {
  value = acme_certificate.cert.certificate_pem
}
```

### Сценарий 2: Wildcard-сертификат через DNS-01 (Cloudflare)

```hcl
resource "acme_certificate" "wildcard" {
  account_key_pem           = acme_registration.letsencrypt.account_key_pem
  common_name               = "*.example.com"
  subject_alternative_names = ["example.com"]

  dns_challenge {
    provider = "cloudflare"

    config = {
      CLOUDFLARE_API_TOKEN = var.cloudflare_api_token
    }
  }

  min_days_remaining = 30
}

# Установка сертификата в Nginx
resource "null_resource" "install_cert" {
  depends_on = [acme_certificate.wildcard]

  connection {
    type     = "ssh"
    host     = var.server_ip
    user     = "deploy"
    private_key = var.ssh_private_key
  }

  provisioner "remote-exec" {
    inline = [
      "sudo mkdir -p /etc/ssl/wildcard",
      "sudo tee /etc/ssl/wildcard/fullchain.pem > /dev/null <<'CERT'\n${acme_certificate.wildcard.certificate_pem}\nCERT",
      "sudo tee /etc/ssl/wildcard/privkey.pem > /dev/null <<'KEY'\n${tls_private_key.cert.private_key_pem}\nKEY",
      "sudo chmod 600 /etc/ssl/wildcard/privkey.pem",
      "sudo systemctl reload nginx"
    ]
  }
}
```

### Сценарий 3: Reverse-прокси с автоматическим обновлением (Traefik)

```hcl
# Для Traefik используется файловый провайдер ACME
resource "acme_certificate" "traefik" {
  account_key_pem           = acme_registration.letsencrypt.account_key_pem
  common_name               = "app.example.com"
  subject_alternative_names = ["api.example.com", "*.api.example.com"]

  dns_challenge {
    provider = "cloudflare"

    config = {
      CLOUDFLARE_API_TOKEN = var.cloudflare_api_token
    }
  }

  min_days_remaining = 30
}

# Генерация acme.json для Traefik
resource "local_file" "acme_json" {
  content = jsonencode({
    acme = {
      email         = "admin@example.com"
      caServer      = "https://acme-v02.api.letsencrypt.org/directory"
      keyType       = "EC256"
      certificates = [
        {
          certFile    = acme_certificate.traefik.certificate_pem
          keyFile     = tls_private_key.cert.private_key_pem
          domain      = "app.example.com"
          sans        = ["api.example.com", "*.api.example.com"]
          constraint  = ""
        }
      ]
    }
  })
  filename        = "/etc/traefik/acme.json"
  file_permission = "0600"
}
```

### Сценарий 4: CI/CD pipeline — сертификат для staging-окружения

```hcl
# Один сертификат для всех staging-доменов
resource "acme_certificate" "staging" {
  account_key_pem           = acme_registration.staging.account_key_pem
  common_name               = "*.staging.example.com"
  subject_alternative_names = ["staging.example.com"]

  # Staging Let's Encrypt (не тратит лимиты)
  server_url = "https://acme-staging-v02.api.letsencrypt.org/directory"

  dns_challenge {
    provider = "cloudflare"

    config = {
      CLOUDFLARE_API_TOKEN = var.cloudflare_api_token
    }
  }

  min_days_remaining = 7
}

# Production
resource "acme_certificate" "production" {
  account_key_pem           = acme_registration.production.account_key_pem
  common_name               = "app.example.com"
  subject_alternative_names = ["api.example.com", "www.example.com"]

  dns_challenge {
    provider = "cloudflare"

    config = {
      CLOUDFLARE_API_TOKEN = var.cloudflare_api_token
    }
  }

  min_days_remaining = 30
}

# Отдельный аккаунт для Production (изоляция rate limits)
resource "tls_private_key" "acme_production" {
  algorithm   = "ECDSA"
  ecdsa_curve = "P-256"
}

resource "acme_registration" "production" {
  account_key_pem = tls_private_key.acme_production.private_key_pem
  email_address   = "prod-admin@example.com"
}
```

### Сценарий 5: Multi-domain сертификат с_CONDITIONAL_

```hcl
locals {
  domains = {
    "app" = {
      common_name = "app.example.com"
      sans        = ["www.example.com"]
    }
    "api" = {
      common_name = "api.example.com"
      sans        = ["api-v2.example.com", "api-internal.example.com"]
    }
    "grafana" = {
      common_name = "grafana.example.com"
      sans        = ["prometheus.example.com"]
    }
  }
}

resource "tls_private_key" "domain_keys" {
  for_each    = local.domains
  algorithm   = "ECDSA"
  ecdsa_curve = "P-256"
}

resource "acme_certificate" "domain_certs" {
  for_each = local.domains

  account_key_pem           = acme_registration.letsencrypt.account_key_pem
  common_name               = each.value.common_name
  subject_alternative_names = each.value.sans

  dns_challenge {
    provider = "cloudflare"

    config = {
      CLOUDFLARE_API_TOKEN = var.cloudflare_api_token
    }
  }

  min_days_remaining = 30
}
```

---

## Дополнительная информация

### Интеграция с cert-manager (гибридный подход)

Terraform можно использовать для управления DNS-записями, а cert-manager — для выпуска сертификатов в Kubernetes:

```hcl
# Terraform управляет DNS-зоной
resource "cloudflare_zone" "main" {
  zone = "example.com"
}

# cert-manager выпускает сертификат через DNS-01
# DNS-записи создаются Terraform, а cert-manager использует API Cloudflare
```

### Сравнение Terraform ACME vs certbot

| Критерий | Terraform ACME | certbot |
| :--- | :--- | :--- |
| **Язык** | HCL (declarative) | CLI (imperative) |
| **State** | Terraform state (remote) | Нет state (magic folders) |
| **Сложность** | Средняя | Низкая |
| **Multi-cloud** | Да (через провайдеры) | Да (через плагины) |
| **GitOps** | Да (Terraform Cloud/Enterprise) | Ограниченно |
| **CI/CD** | terraform plan/apply | certbot renew |
| **DNS-01** | Встроенные провайдеры DNS | 100+ плагинов |
| **Откат** | terraform destroy | certbot revoke |
| **Рекомендация** | Для IaC-сред | Для standalone-серверов |

### Terraform и rate limits Let's Encrypt

```hcl
# Стратегия защиты от rate limits:
# 1. Staging-first: test через Staging, затем Production
# 2. Разделение аккаунтов: отдельный acme_registration для каждого окружения
# 3. min_days_remaining: обновление за 30 дней до истечения

resource "acme_certificate" "safe" {
  account_key_pem = acme_registration.letsencrypt.account_key_pem
  common_name     = "app.example.com"

  # Обновление за 30 дней (ARI в cert-manager делает это автоматически)
  min_days_remaining = 30

  dns_challenge {
    provider = "cloudflare"
    config = {
      CLOUDFLARE_API_TOKEN = var.cloudflare_api_token
    }
  }
}
```

### Смотрите также

- **[Let's Encrypt: Обзор](./index.md)** — лимиты, solvers и окружения
- **[Практические сценарии Let's Encrypt](./letsencrypt_scenarios.md)** — cert-manager в Kubernetes
- **[Certbot и acme.sh](../../../../WebServers/Concepts/https_with_certbot.md)** — альтернативные ACME-клиенты
- **[Ansible: Управление сертификатами](../../../../Ansible/ansible_certificate_management.md)** — автоматизация через Ansible
- **[Vault PKI интеграция](../Private_CA/vault_integration.md)** — внутренний CA через Vault
