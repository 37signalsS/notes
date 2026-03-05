# HashiCorp Nomad: Практические сценарии

## 1. Развёртывание микросервисов

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

---

## 2. Выполнение пакетных заданий (Batch Jobs)

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

---

## 3. Оркестрация виртуальных машин (QEMU)

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

---

## 4. GPU и AI/ML Workloads

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

---

## 5. Edge Computing

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

---

## 6. Мульти-регион федерация

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

---

## Ссылки

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация
- [Дополнительная информация](./advanced_topics.md) — версии, production adoption, ресурсы
