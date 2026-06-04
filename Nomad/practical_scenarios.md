# Nomad — практические сценарии

## Определения

Основные единицы работы в Nomad (Job, Group, Task) и их описание вынесены в основной файл определений.

Подробности: [Nomad — определения](./definitions_and_concepts.md#определения).

## Основные концепции

Концептуальная информация о типах задач и структуре job-файлов доступна в разделе базовых концепций.

Подробности: [Nomad — типы jobs и структура файла](./definitions_and_concepts.md#типы-jobs).

## Практические сценарии

### 1. Развёртывание микросервисов

Микросервисная архитектура с service discovery и управлением секретами:

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

      vault {
        policies = ["webapp-policy"]
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

Документация: [Secret Management с Vault](https://developer.hashicorp.com/nomad/tutorials/enterprise/nomad-vault-secret-management), [Consul Connect Integration](https://developer.hashicorp.com/nomad/tutorials/connect).

### 2. Периодические пакетные задания (Batch)

ETL-процессы, бэкапы, обработка данных:

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

      env {
        PGPASSWORD = "${vault.secret.data.password}"
      }
    }
  }

  periodic {
    cron     = "0 3 * * *"
    timeZone = "UTC"
  }
}
```

### 3. Оркестрация виртуальных машин (QEMU)

Legacy-приложения или Windows-workload'ы в VM:

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

Обучение моделей, инференс, обработка видео:

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

### 5. Edge Computing

Развёртывание на периферийных устройствах с ограниченными ресурсами.

**Преимущества Nomad для Edge:** минимальные требования (~50 MB RAM для клиента), работа в нестабильных сетях (автоматическое переподключение), мульти-регион федерация, поддержка разнородных workload'ов.

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

### 6. Мульти-регион федерация

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
