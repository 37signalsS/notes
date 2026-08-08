# Nomad — практические сценарии

## Определения

**Практические сценарии Nomad** — это набор типовых конфигураций и архитектурных паттернов для развёртывания различных типов нагрузок (контейнеры, процессы, виртуальные машины) в распределенной среде.

**Blue-Green Deployment** — стратегия обновления, при которой одновременно запускаются две версии приложения (старая и новая), а трафик переключается мгновенно на уровне балансировщика.

**Canary Deployment** — стратегия постепенного перенаправления части трафика на новую версию приложения для проверки её стабильности.

**Workload Identity** — механизм OIDC-аутентификации, позволяющий задачам получать доступ к секретам Vault и сервисам Consul без долгоживущих токенов.

## Базовые концепции реализации

Все сценарии базируются на использовании HCL (HashiCorp Configuration Language) и интеграции с экосистемой HashiCorp.

- **Типы задач:** `service` (демоны), `batch` (разовые задачи), `system` (на каждом узле), `sysbatch`.
- **Драйверы:** `docker`, `exec2` (безопасные процессы), `virt` (VM), `java`.
- **Обновление:** Блок `update` определяет логику раскатки (Canary, Blue-Green).

## Практические сценарии

### 1. Развёртывание микросервисов (Service Discovery + Identity) {#секреты-через-vault}

Сценарий для облачных приложений с использованием **Native Service Discovery** и **Workload Identity**:

```hcl
job "webapp" {
  datacenters = ["dc1"]
  type        = "service"

  group "web-cluster" {
    count = 3

    network {
      port "http" { to = 8080 }
    }

    # Регистрация в Nomad Service Discovery (v1.6+)
    service {
      name     = "frontend"
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
        image = "my-registry/webapp:v2.1"
        ports = ["http"]
      }

      # OIDC-идентификация для доступа к Vault
      identity {
        env  = true
        file = true
      }

      template {
        data = <<EOH
{{ with secret "kv/data/webapp/config" }}
API_KEY="{{ .Data.data.api_key }}"
{{ end }}
EOH
        destination = "secrets/app.env"
        env         = true
      }
    }
  }
}
```

### 2. Высокобезопасная изоляция процессов (Exec2 + Landlock)

Использование драйвера `exec2` (GA v1.9) для запуска бинарных файлов с минимальным оверхедом и аппаратной изоляцией через **Landlock LSM**:

```hcl
job "secure-api" {
  datacenters = ["dc1"]

  group "api" {
    task "binary-task" {
      driver = "exec2"

      config {
        command = "local/api-server"
        args    = ["--port", "${NOMAD_PORT_http}"]

        # Ограничение доступа к файловой системе через Landlock
        landlock {
          allow_read = ["/etc/ssl/certs", "/etc/hosts"]
          allow_write = ["/tmp"]
        }
      }

      artifact {
        source = "https://internal-repo.example.com/api-v1.9.tar.gz"
      }

      resources {
        cpu    = 500
        memory = 256
      }
    }
  }
}
```

### 3. Пакетная обработка и Cron (Nomad Variables)

Автоматизация ETL-задач с хранением конфигурации во встроенном хранилище переменных:

```hcl
job "data-cleanup" {
  datacenters = ["dc1"]
  type        = "batch"

  periodic {
    cron     = "@daily"
    timeZone = "Europe/Moscow"
  }

  group "cleanup" {
    task "purge-logs" {
      driver = "docker"

      config {
        image = "alpine:latest"
        command = "/bin/sh"
        args = ["-c", "rm -rf /data/logs/*.log"]
      }

      # Получение параметров из Nomad Variables
      template {
        data = <<EOH
{{ with nomadVar "nomad/jobs/data-cleanup" }}
RETENTION_DAYS="{{ .retention_days }}"
{{ end }}
EOH
        destination = "local/config.env"
        env         = true
      }
    }
  }
}
```

### 4. Оркестрация виртуальных машин (Libvirt/Virt)

Запуск legacy-приложений или изолированных окружений через драйвер `virt` (v1.9):

```hcl
job "legacy-vm" {
  datacenters = ["dc1"]

  group "vms" {
    task "windows-node" {
      driver = "virt"

      config {
        image = "local/win2022-template.qcow2"
        cpu   = 4
        memory = 8192
        
        # Настройка сети через bridge
        network_interface {
          bridge {
            name = "virbr0"
          }
        }
      }

      artifact {
        source = "s3::https://s3.example.com/vms/win2022.qcow2"
        destination = "local/win2022-template.qcow2"
      }
    }
  }
}
```

### 5. Использование GPU и AI (MIG Support)

Разделение видеокарты на логические инстансы (**Multi-Instance GPU**) для эффективного инференса:

```hcl
job "ai-inference" {
  datacenters = ["gpu-cluster"]

  group "inference-group" {
    task "model-server" {
      driver = "docker"

      config {
        image = "nvidia/cuda:12.0-base"
      }

      resources {
        cpu    = 2000
        memory = 4096
        # Запрос конкретного профиля MIG
        device "nvidia/gpu" {
          count = 1
          constraints = [ "${device.model} == 'A100'", "${device.mig_profile} == '1g.5gb'" ]
        }
      }
    }
  }
}
```

### 6. Blue-Green развёртывание (Consul API Gateway)

Использование блока `update` и тегов для бесшовного переключения трафика:

```hcl
job "payment-gateway" {
  datacenters = ["dc1"]

  update {
    max_parallel     = 3
    canary           = 3
    auto_promote     = false # Ручное переключение после верификации
    auto_revert      = true
    health_check     = "checks"
    min_healthy_time = "1m"
  }

  group "api" {
    count = 3

    service {
      name = "payments"
      port = "http"
      
      # Теги для маршрутизации в Consul HTTPRoute
      tags = [
        "version=v2",
        "color=${NOMAD_DEPLOYMENT_CANARY == "true" ? "green" : "blue"}"
      ]
    }

    task "app" {
      driver = "docker"
      config { image = "payments:v2" }
    }
  }
}
```

### 7. Работа с данными (CSI Volume)

Монтирование внешних блочных устройств или файловых систем:

```hcl
job "stateful-app" {
  datacenters = ["dc1"]

  group "storage-group" {
    volume "ebs-data" {
      type            = "csi"
      source          = "production-db-vol"
      attachment_mode = "file-system"
      access_mode     = "single-node-writer"
    }

    task "db" {
      driver = "docker"
      
      volume_mount {
        volume      = "ebs-data"
        destination = "/var/lib/data"
      }

      config {
        image = "postgres:15"
      }
    }
  }
}
```

### 8. Периферийные вычисления (Edge Computing)

Сценарий с использованием `system` job и `exec2` для работы на слабых ARM-устройствах:

```hcl
job "edge-monitor" {
  datacenters = ["edge-region"]
  type        = "system" # Запуск на каждом узле

  constraint {
    attribute = "${node.class}"
    value     = "raspberry-pi"
  }

  group "monitoring" {
    task "collector" {
      driver = "exec2"
      config {
        command = "/usr/bin/sensor-collector"
      }
      resources {
        cpu    = 100
        memory = 64
      }
    }
  }
}
```

### 9. Глобальная федерация (Multi-Region)

Настройка репликации между регионами для отказоустойчивости:

```hcl
# server.hcl (Регион 1)
region           = "europe"
datacenter       = "eu-west-1"
server           = true
bootstrap_expect = 3

replication {
  enabled = true # Включение репликации ACL и токенов
}
```

```bash
# Присоединение второго региона (US) к первому (EU)
nomad system federation join nomad-eu.example.com:4646
```

## Дополнительная информация

См. также:

- **[Nomad — определения и базовые концепции](./definitions_and_concepts.md)** — теоретическая база.
- **[Nomad — продвинутые темы и версии](./advanced_topics.md)** — детали LTS и Enterprise.
- **[Интеграция с Vault](../Vault/overview.md)** — управление секретами.
- **[Интеграция с Consul](../Consul/consul_overview.md)** — сетевое взаимодействие.
