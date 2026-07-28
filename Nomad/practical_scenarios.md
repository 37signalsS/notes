# Nomad — практические сценарии

## Обзор сценариев

В данном разделе представлены практические примеры использования Nomad для различных типов нагрузок. Базовые сущности (Job, Group, Task) описаны в [основном файле определений](./definitions_and_concepts.md).

## Ключевые паттерны

Подробная информация о типах задач и структуре job-файлов доступна в [базовых концепциях](./definitions_and_concepts.md#типы-jobs).

## Практические сценарии

### 1. Развёртывание микросервисов

Микросервисная архитектура с автоматическим обнаружением сервисов (Service Discovery) и использованием **Workload Identity** для безопасного доступа к Vault:

```hcl
job "webapp" {
  datacenters = ["dc1"]
  type        = "service"

  group "web" {
    count = 3

    network {
      port "http" {
        to = 8080
      }
    }

    service {
      name = "webapp"
      port = "http"
      provider = "nomad" # Использование встроенного Service Discovery (v1.6+)

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

      # Использование Workload Identity (v1.6+) вместо статического блока vault
      identity {
        env  = true
        file = true
      }

      template {
        data = <<EOH
{{ with secret "secret/data/webapp/config" }}
DB_PASSWORD="{{ .Data.data.password }}"
{{ end }}
EOH
        destination = "secrets/file.env"
        env         = true
      }

      consul {
        connect {
          sidecar_service {}
        }
      }
    }
  }
}
```

Документация: [Workload Identity](https://developer.hashicorp.com/nomad/docs/concepts/workload-identity), [Consul Connect Integration](https://developer.hashicorp.com/nomad/tutorials/connect).

### 2. Периодические пакетные задания (Batch)

ETL-процессы, бэкапы, обработка данных с использованием **Nomad Variables**:

```hcl
job "backup" {
  datacenters = ["dc1"]
  type        = "batch"

  group "backup-db" {
    task "postgres-backup" {
      driver = "docker"

      config {
        image   = "postgres:15"
        command = "pg_dump"
        args    = ["-h", "${attr.unique.network.ip-address}", "-U", "postgres", "mydb"]
      }

      # Использование Nomad Variables (встроенное хранилище)
      template {
        data = <<EOH
{{ with nomadVar "nomad/jobs/backup" }}
PGPASSWORD="{{ .password }}"
{{ end }}
EOH
        destination = "secrets/file.env"
        env         = true
      }
    }
  }

  periodic {
    cron     = "0 3 * * *"
    timeZone = "UTC"
  }
}
```

### 3. Оркестрация виртуальных машин

Запуск изолированных приложений или Windows-нагрузок через драйвер QEMU:

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

### 4. Нагрузки с использованием GPU и AI/ML

Обучение моделей, инференс и обработка видео с аппаратным ускорением:

```hcl
job "ml-training" {
  datacenters = ["dc1"]
  type        = "batch"

  group "trainer" {
    count = 1

    task "train" {
      driver = "docker"

      config {
        image   = "tensorflow/tensorflow:latest-gpu"
        command = "python"
        args    = ["train.py", "--epochs", "100"]
      }

      resources {
        cpu    = 8000
        memory = 32768
        gpu    = 2
      }
    }
  }
}
```

**Возможности GPU:** автоматическое обнаружение NVIDIA GPU через fingerprinting, поддержка MIG (Multi-Instance GPU), интеграция с NVIDIA Device Plugin.

### 5. Периферийные вычисления (Edge Computing)

Развёртывание на устройствах с ограниченными ресурсами.

**Преимущества Nomad для Edge:** минимальные требования (~50 MB RAM для клиента), работа в нестабильных сетях, нативная федерация.

```hcl
job "edge-processor" {
  datacenters = ["edge-dc"]
  type        = "service"

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

### 6. Состояние и хранение данных (Stateful с CSI)

Использование внешних систем хранения через интерфейс CSI (Container Storage Interface):

```hcl
job "database" {
  datacenters = ["dc1"]
  type        = "service"

  group "db" {
    network {
      port "db" { to = 5432 }
    }

    volume "postgres-data" {
      type            = "csi"
      source          = "pg-volume"
      read_only       = false
      attachment_mode = "file-system"
      access_mode     = "single-node-writer"
    }

    task "postgres" {
      driver = "docker"

      volume_mount {
        volume      = "postgres-data"
        destination = "/var/lib/postgresql/data"
      }

      config {
        image = "postgres:16"
        ports = ["db"]
      }
    }
  }
}
```

### 7. Федерация между регионами

Глобальное развёртывание с репликацией ACL-политик и квот:

```hcl
# server-dc1.hcl
datacenter       = "dc1"
server           = true
bootstrap_expect = 3

acl {
  enabled = true
}

replication {
  enabled = true
}
```

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

См. также:

- [Определения и базовые концепции](./definitions_and_concepts.md)
- [Продвинутые темы и версии](./advanced_topics.md)
