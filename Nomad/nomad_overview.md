# HashiCorp Nomad: Обзор

## Определения

**Nomad** — это легковесный и гибкий оркестратор от HashiCorp для планирования (scheduling) и запуска приложений (workloads). В отличие от Kubernetes, который является комплексной платформой «всё в одном», Nomad придерживается философии UNIX: делать одну вещь, но делать её хорошо.

**Ключевая особенность:** единый бинарный файл без внешних зависимостей, поддерживающий контейнеры, бинарные приложения, Java, QEMU/VM и другие типы workload'ов.

**Актуальная версия:** v1.11.x (февраль 2026) — [официальная документация](https://developer.hashicorp.com/nomad/docs)

## Основные концепции

### Архитектура

Nomad состоит из двух типов агентов, объединённых в один бинарный файл:

| Компонент | Назначение |
| :--- | :--- |
| **Server** | Управление кластером, хранение состояния, планирование |
| **Client** | Запуск задач, отчёт о ресурсах, взаимодействие с runtime |

**Режимы развёртывания:**
- **Standalone:** один сервер для разработки/тестирования
- **High Availability:** 3–5 серверов для production (консенсус через Raft)

### Ключевые особенности

| Характеристика | Описание |
| :--- | :--- |
| **Простота** | Один бинарный файл, тривиальная установка |
| **Гибкость workload'ов** | Docker, Podman, exec, Java, QEMU/VM, raw_exec |
| **Масштабируемость** | До 10 000+ узлов в production |
| **Мульти-регион** | Нативная федерация кластеров |
| **Гибридность** | Единый workflow для on-prem, cloud, edge |
| **Лицензия** | Полностью open source (BSL → MPL) |

### Интеграция с экосистемой HashiCorp

Nomad полагается на другие инструменты HashiCorp для полноценной работы:

- **[Consul](../Consul/consul_overview.md):** Service discovery, health checking, service mesh
- **[Vault](../Vault/overview.md):** Управление секретами, динамические credentials
- **[Terraform](../Terraform/terraform_overview.md):** Provisioning инфраструктуры
- **Boundary:** Безопасный доступ к workload'ам (интеграция через Consul)

### Сравнение с другими оркестраторами

| Критерий | **Nomad** | **[Kubernetes](../Kubernetes/kubernetes_overview.md)** | **[Docker Swarm](../Docker_swarm/docker_swarm_overview.md)** |
| :--- | :--- | :--- | :--- |
| **Архитектура** | Единый бинарник, нет внешних зависимостей | 12+ компонентов, требует etcd | Встроен в Docker Engine |
| **Workload'ы** | Контейнеры + legacy (Windows, Java, VM) | Только Linux-контейнеры | Только Docker-контейнеры |
| **Масштабируемость** | До 10 000+ узлов | До 5 000 узлов | До ~1 000 узлов |
| **Сложность** | Минимальная | Высокая операционная сложность | Низкая |
| **Мульти-регион** | Нативная федерация | Ограниченная, высокая сложность | Отсутствует |
| **Экосистема** | Интеграция с Vault, Consul, Terraform | Встроенные сервисы + Helm charts | Ограниченная |
| **Service Discovery** | Через Consul | Встроенный (CoreDNS, Services) | Встроенный (Routing Mesh) |
| **Secrets Management** | Через Vault | Встроенный (Secrets) + External | Встроенный (Secrets) |
| **GPU / AI / ML** | Встроенная поддержка | Через Device Plugins | Ограниченная |
| **Сообщество (RF)** | Нишевое, растущее | Доминирующее, enterprise-стандарт | Угасающее |

### Преимущества

- **Простота установки и эксплуатации:** Легко начать работу, эффективен в управлении кластером
- **Фокус на оркестрации:** Эффективно справляется с задачей планирования и запуска нагрузок
- **Гибридные workload'ы:** Микс контейнеров и legacy-приложений в одном кластере
- **Малые команды:** Требует меньше ресурсов на поддержку по сравнению с Kubernetes
- **Edge computing:** Благодаря легковесности подходит для развёртывания на периферийных устройствах

### Недостатки

- **Требует дополнительных инструментов:** Для полноценной системы необходимы Consul (service discovery) и Vault (secrets)
- **Меньшая экосистема:** Меньше готовых инструментов и community tools по сравнению с Kubernetes
- **Нишевое решение:** Меньшая распространённость, сложнее найти специалистов
- **Не для cloud-native greenfield:** Kubernetes предпочтительнее для новых cloud-native проектов

## Практические сценарии

### 1. Развёртывание микросервисов

**Сценарий:** Микросервисная архитектура с service discovery и управлением секретами.

**Конфигурация:**
```hcl
job "webapp" {
  datacenters = ["dc1"]
  type        = "service"

  group "web" {
    count = 3

    network {
      port "http" {
        static = 8080
      }
    }

    service {
      name = "webapp"
      port = "http"
      
      check {
        name     = "http_health"
        type     = "http"
        path     = "/health"
        interval = "10s"
        timeout  = "2s"
      }
    }

    task "server" {
      driver = "docker"

      config {
        image = "webapp:latest"
        ports = ["http"]
      }

      # Интеграция с Vault для секретов
      vault {
        policies = ["webapp-policy"]
      }

      # Интеграция с Consul Connect
      consul {
        connect {
          sidecar_service {}
        }
      }
    }
  }
}
```

**Ресурсы:**
- [Secret Management с Vault](https://developer.hashicorp.com/nomad/tutorials/enterprise/nomad-vault-secret-management)
- [Consul Connect Integration](https://developer.hashicorp.com/nomad/tutorials/connect)

### 2. Выполнение пакетных заданий (Batch Jobs)

**Сценарий:** Периодические задачи (cron), ETL-процессы, обработка данных.

```hcl
job "backup" {
  datacenters = ["dc1"]
  type        = "batch"

  group "backup-db" {
    task "postgres-backup" {
      driver = "docker"

      config {
        image = "postgres:15"
        command = "pg_dump"
        args    = ["-h", "${attr.unique.network.ip-address}", "-U", "postgres", "mydb"]
      }

      env {
        PGPASSWORD = "${vault.secret.data.password}"
      }
    }
  }

  # Расписание: каждый день в 3:00
  periodic {
    cron = "0 3 * * *"
    timeZone = "UTC"
  }
}
```

### 3. Оркестрация виртуальных машин (QEMU)

**Сценарий:** Запуск legacy-приложений или Windows-workload'ов в VM.

```hcl
job "legacy-app" {
  datacenters = ["dc1"]
  type        = "service"

  group "vm" {
    count = 1

    task "windows-app" {
      driver = "qemu"

      config {
        image_path = "/opt/images/windows-app.qcow2"
        args = [
          "-cpu", "host",
          "-smp", "4",
          "-m", "8192",
          "-drive", "file=/opt/data/app-data.raw,format=raw"
        ]
      }

      resources {
        cpu    = 4000
        memory = 8192
      }
    }
  }
}
```

### 4. GPU и AI/ML Workloads

**Сценарий:** Обучение моделей машинного обучения, инференс, обработка видео.

```hcl
job "ml-training" {
  datacenters = ["dc1"]
  type        = "batch"

  group "trainer" {
    count = 1

    task "train" {
      driver = "docker"

      config {
        image = "tensorflow/tensorflow:latest-gpu"
        command = "python"
        args    = ["train.py", "--epochs", "100"]
      }

      resources {
        cpu    = 8000
        memory = 32768
        gpu    = 2  # Автоматическое обнаружение GPU через fingerprinting
      }
    }
  }
}
```

**Возможности GPU:**
- Автоматическое обнаружение NVIDIA GPU через fingerprinting
- Поддержка MIG (Multi-Instance GPU)
- Интеграция с NVIDIA Device Plugin

### 5. Edge Computing

**Сценарий:** Развёртывание на периферийных устройствах с ограниченными ресурсами.

**Преимущества Nomad для Edge:**
- Минимальные требования к ресурсам (~50 MB RAM для клиента)
- Работа в нестабильных сетях (автоматическое переподключение)
- Мульти-регион федерация для централизованного управления
- Поддержка разнородных workload'ов (контейнеры + бинарники)

```hcl
job "edge-processor" {
  datacenters = ["edge-dc"]
  type        = "service"

  # Ограничиваем размещение на edge-узлах
  constraint {
    attribute = "${attr.unique.hostname}"
    operator  = "prefix"
    value     = "edge-"
  }

  group "processor" {
    count = 1

    task "process" {
      driver = "exec"

      config {
        command = "/opt/edge/processor"
        args    = ["--config", "/etc/edge/config.yaml"]
      }
    }
  }
}
```

### 6. Мульти-регион федерация

**Сценарий:** Глобальное развёртывание с автоматической репликацией ACL-политик и квот.

**Конфигурация серверов:**
```hcl
# server-dc1.hcl
datacenter = "dc1"
server     = true
bootstrap_expect = 3

acl {
  enabled = true
}

replication {
  enabled = true
}

# server-dc2.hcl
datacenter = "dc2"
server     = true
bootstrap_expect = 3
```

**Команды федерации:**
```bash
# Получение токена репликации из dc1
nomad acl token create -name "Replication Token" \
  -policy "global-management"

# Присоединение dc2 к dc1
nomad system federation join dc1 \
  -token "<replication-token>" \
  -address "https://nomad-dc1.example.com:4646"
```

## Дополнительная информация

### Версии и поддержка

| Версия | Дата выпуска | Статус |
| :--- | :--- | :--- |
| **v1.11.2** | Февраль 2026 | **Latest** |
| v1.10.8 | Февраль 2026 | Поддерживаемая |
| v1.8.20 | Февраль 2026 | LTS |
| v1.7.x и ранее | — | Устаревшие |

**Ключевые нововведения v1.11.x:**
- **Client Identity:** Автоматическая генерация и ротация идентичностей клиентов
- **Deployments для system jobs:** Поддержка развёртываний для системных задач
- **Secrets Block:** Новый блок `secret` для получения секретов из Vault
- **GPU Fingerprinting:** Улучшенное обнаружение GPU, FPGA, TPU
- **Sentinel:** Новый `nomad_var` built-in для переменных

**Enterprise-версии:** С апреля 2026 HashiCorp меняет модель выпуска enterprise-версий — [подробности](https://support.hashicorp.com/hc/en-us/articles/48015293517203)

### Production Adoption

**Компании в production:** PagerDuty, Target, Citadel, Trivago, SAP, Pandora, Roblox, eBay, Deluxe Entertainment

### Когда выбирать Nomad

| Критерий | Nomad | Kubernetes |
| :--- | :--- | :--- |
| **Workload'ы** | Микс контейнеров и legacy (Windows, Java, VM) | Только контейнеры |
| **Команда** | Малые/средние, ограниченные ресурсы на поддержку | Крупные, выделенная SRE-команда |
| **Среда** | On-premises или гибридная | Преимущественно cloud |
| **Приложения** | Существующие core-приложения + новые | Cloud-native greenfield |
| **Приоритет** | Простота и скорость внедрения | Полнота функциональности |
| **Бюджет** | Ограниченный | Значительный |

**Тренд 2025–2026:** Сосуществование обоих оркестраторов в крупных предприятиях (Intel, Autodesk, GitHub).

### Полезные ресурсы

- [Официальная документация](https://developer.hashicorp.com/nomad/docs)
- [Сравнение Nomad и Kubernetes](https://developer.hashicorp.com/nomad/docs/nomad-vs-kubernetes)
- [A Kubernetes User's Guide to HashiCorp Nomad](https://developer.hashicorp.com/nomad/tutorials/enterprise/kubernetes-to-nomad)
- [The Kubernetes to Nomad Cheat Sheet](https://developer.hashicorp.com/nomad/tutorials/enterprise/kubernetes-to-nomad-cheat-sheet)
- [GitHub Releases](https://github.com/hashicorp/nomad/releases)

### Связанные концепты

- **Оркестрация контейнеров** — общие принципы (см. [`kubernetes_overview.md`](../Kubernetes/kubernetes_overview.md), [`docker_swarm_overview.md`](../Docker_swarm/docker_swarm_overview.md))
- **[Edge computing](../Concepts/edge_computing_overview.md)** — периферийные вычисления
- **[Service Mesh](../Service_Mesh/service_mesh_concepts.md)** — Consul Connect
- **[High Availability](../Concepts/High_Availability/ha_overview.md)** — отказоустойчивость кластеров
