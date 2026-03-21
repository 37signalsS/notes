# Yandex Cloud — навигатор

**Yandex Cloud** — платформа облачных сервисов для развёртывания и управления инфраструктурой. Этот каталог содержит документацию по основным сервисам YC для DevOps-практик.

---

## Сервисы

### Вычисления

| Документ | Описание |
| :--- | :--- |
| **[Compute Cloud](./Compute-Cloud.md)** | Виртуальные машины, прерываемые инстансы, диски, снапшоты |

**Ключевые темы:**

- Платформы виртуализации (standard-v3, standard-v4a, highfreq, gpu)
- Типы дисков (network-ssd, network-hdd, network-ssd-nonreplicated)
- Прерываемые ВМ для CI/CD и HPC
- Cloud-init и автоматизация настройки

---

### Сети

| Документ | Описание |
| :--- | :--- |
| **[VPC](./VPC.md)** | Виртуальные частные сети, подсети, маршрутизация, security groups |

**Ключевые темы:**

- Публичные и приватные подсети
- NAT Gateway и Internet Gateway
- Security Groups для сегментации
- Cloud VPN и VPC Peering

---

### Базы данных

| Документ | Описание |
| :--- | :--- |
| **[Managed Databases](./Managed-Databases.md)** | Управляемые СУБД: PostgreSQL, MySQL, ClickHouse, Redis, MongoDB |

**Ключевые темы:**

- Выбор движка (OLTP vs OLAP)
- Автоматические бэкапы и PITR
- Репликация и высокая доступность
- Масштабирование (вертикальное/горизонтальное)

---

### Хранилища

| Документ | Описание |
| :--- | :--- |
| **[Storage](../Kubernetes/Base/secrets/etcd_storage.md)** | Object Storage, Block Storage, File Storage |

**Ключевые темы:**

- S3-совместимый API для объектов
- Версионирование и lifecycle-политики
- Снимки дисков для бэкапов
- NFS для общего доступа

---

### Мониторинг и логирование

| Документ | Описание |
| :--- | :--- |
| **[Monitoring](./Monitoring.md)** | Сбор метрик, дашборды, алертинг, интеграция с логами |

**Ключевые темы:**

- Модель данных (метрики, метки, точки)
- Пользовательские метрики через API
- Log-based metrics
- Интеграция с Grafana и Prometheus

---

### Управление ресурсами

| Документ | Описание |
| :--- | :--- |
| **[Resource Manager](./index.md)** | Иерархия ресурсов, каталоги, сервисные аккаунты, IAM |

**Ключевые темы:**

- Организация каталогов (dev/stage/prod)
- Сервисные аккаунты для CI/CD
- Принцип минимальных прав
- Terraform для декларативного управления

---

## Интеграции

### Infrastructure as Code

- **[Terraform](../Concepts/iac_overview.md)** — декларативное описание инфраструктуры
- **[Crossplane](../GitOps/Crossplane/provider_yandex_cloud_setup.md)** — управление через Kubernetes

### CI/CD

- **[GitLab CI](../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md)** — пайплайны для деплоя в YC
- **[Artifact Management](../CI-CD/artifact_management.md)** — хранение артефактов в Object Storage

### Контейнеризация

- **[Kubernetes](../Kubernetes/)** — управляемые кластеры K8s в YC
- **[Docker](../Docker/docker_overview.md)** — запуск контейнеров на Compute Cloud

### Мониторинг

- **[Grafana](../Grafana/grafana_overview.md)** — визуализация метрик YC
- **[Prometheus](../Prometheus/overview.md)** — альтернативная система мониторинга

---

## Быстрый старт

### 1. Инициализация yc CLI

```bash
yc init
# Выбор облака, каталога, зоны доступности
```

### 2. Создание тестовой ВМ

```bash
yc compute instance create \
  --name demo-vm \
  --zone ru-central1-a \
  --cores 2 --memory 4 \
  --create-boot-disk image-folder-id=standard-images,image-family=ubuntu-2204-lts,size=20 \
  --network-interface subnet-name=default-ru-central1-a,nat-ip-version=ipv4 \
  --ssh-key ~/.ssh/id_rsa.pub
```

### 3. Развёртывание через Terraform

```bash
# main.tf
provider "yandex" {
  token     = var.yc_token
  cloud_id  = var.cloud_id
  folder_id = var.folder_id
}

resource "yandex_compute_instance" "app" {
  name        = "app-vm"
  platform_id = "standard-v3"
  zone        = "ru-central1-a"

  resources {
    cores  = 2
    memory = 4
  }

  boot_disk {
    initialize_params {
      image_id = "fd8vj3j1l015********"
    }
  }

  network_interface {
    subnet_id = var.subnet_id
    nat       = true
  }
}
```

---

## Актуальные версии

| Сервис | Версии / Состояние |
| :--- | :--- |
| **Compute Cloud** | Платформы: standard-v3, standard-v4a (AMD Zen 4), highfreq-v3, highfreq-v4a |
| **PostgreSQL** | 14, 15, 16, 17, 18 (10–13 прекращены) |
| **MySQL** | 8.0, 8.4 |
| **Redis** | 6.2, 7.0, 7.2 |
| **ClickHouse** | 23.8+, 24.8+ |
| **VPC** | NAT Gateway (Egress NAT устарел) |
| **Monitoring** | Интеграция с Managed Service for Prometheus, вкладка Alerts |

---

## Ссылки

- **[Официальная документация Yandex Cloud](https://yandex.cloud/ru/docs/)**
- **[Yandex Cloud CLI Reference](https://yandex.cloud/ru/docs/cli/)**
- **[Terraform Provider](https://registry.terraform.io/providers/yandex-cloud/yandex/latest/docs)**
- **[Cloud Marketplace](https://yandex.cloud/ru/marketplace)**
