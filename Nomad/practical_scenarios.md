# Nomad — практические сценарии

## Определения

**Практические сценарии Nomad** — набор типовых конфигураций и архитектурных паттернов для развёртывания различных типов нагрузок (контейнеры, процессы, виртуальные машины) в распределённой среде.

**Blue-Green Deployment** — стратегия обновления, при которой одновременно запускаются две версии приложения (старая и новая), а трафик переключается мгновенно на уровне балансировщика.

**Canary Deployment** — стратегия постепенного перенаправления части трафика на новую версию приложения для проверки её стабильности.

**Workload Identity** — механизм OIDC-аутентификации, позволяющий задачам получать доступ к секретам Vault и сервисам Consul без долгоживущих токенов.

**Namespace** — логическая изоляция задач внутри кластера для разделения окружений и команд.

**Quota** — ограничение потребления ресурсов (CPU, memory, задачи) на уровне региона или неймспейса.

**Drain** — режим узла, при котором Nomad прекращает размещение новых аллокаций и последовательно останавливает/перемещает существующие задачи.

## Базовые концепции реализации

Все сценарии базируются на использовании HCL (HashiCorp Configuration Language) и интеграции с экосистемой HashiCorp.

- **Типы задач:** `service` (демоны), `batch` (разовые задачи), `system` (на каждом узле), `sysbatch`.
- **Драйверы:** `docker`, `exec2` (безопасные процессы), `virt` (VM), `java`.
- **Обновление:** Блок `update` определяет логику раскатки (Canary, Blue-Green, Rolling).
- **Service Discovery:** Native Service Discovery (v1.6+) или Consul.
- **Секреты:** Интеграция с Vault через Workload Identity или статические токены.

## Практические сценарии

### 1. Развёртывание микросервисов (Service Discovery + Identity)

Сценарий для продакшен-приложений с использованием Native Service Discovery и Workload Identity:

```hcl
job "webapp" {
  datacenters = ["dc1"]
  type        = "service"

  group "web-cluster" {
    count = 3

    network {
      port "http" { to = 8080 }
    }

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

**Предусловия:**
- Vault включён и доступен на `http://vault.service.consul:8200`
- Политика Vault `webapp-policy` разрешает чтение `kv/data/webapp/config`
- ACL включён на сервере Nomad

**Развёртывание:**
```bash
nomad job run webapp.nomad.hcl
```

**Валидация:**
```bash
nomad job status webapp
# → Status: running, Successful deployments: 1

nomad alloc status <alloc-id>
# → task "server" state: running

curl http://<node-ip>:<port>/health
# → {"status":"ok"}
```

**Типичные ошибки:**
- `permission denied` — проверьте Vault policy и Workload Identity
- `no compatible servers` — убедитесь, что драйвер Docker установлен на клиентах

### 2. Высокобезопасная изоляция процессов (Exec2 + Landlock)

Использование драйвера `exec2` (GA v1.9) для запуска бинарных файлов с минимальным оверхедом и аппаратной изоляцией через Landlock LSM:

```hcl
job "secure-api" {
  datacenters = ["dc1"]

  group "api" {
    task "binary-task" {
      driver = "exec2"

      config {
        command = "local/api-server"
        args    = ["--port", "${NOMAD_PORT_http}"]

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

**Предусловия:**
- Драйвер `exec2` установлен и включён на клиентах
- Ядро Linux >= 5.13 с поддержкой Landlock
- Бинарный файл `api-server` доступен по указанному URL

**Развёртывание:**
```bash
nomad job run secure-api.nomad.hcl
```

**Валидация:**
```bash
nomad alloc status <alloc-id>
# → task "binary-task" state: running

nomad alloc logs <alloc-id> binary-task
# → Запуск API-сервера на порту ${NOMAD_PORT_http}
```

**Типичные ошибки:**
- `landlock: operation not permitted` — ядро не поддерживает Landlock или файловая система не настроена
- `exec2: file not found` — проверьте путь к бинарному файлу в `artifact`

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

**Предусловия:**
- Переменные Nomad созданы: `nomad var put nomad/jobs/data-cleanup retention_days=7`
- Docker драйвер доступен

**Развёртывание:**
```bash
nomad job run data-cleanup.nomad.hcl
```

**Валидация:**
```bash
nomad job status data-cleanup
# → Type: batch, Status: running/complete

nomad job periodic data-cleanup
# → Next launch: <время следующего запуска>
```

**Типичные ошибки:**
- `nomadVar: not found` — проверьте путь переменной: `nomad var list`
- `periodic: cron invalid` — используйте формат cron или `@daily`, `@hourly`

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

        network_interface {
          bridge {
            name = "virbr0"
          }
        }
      }

      artifact {
        source = "https://internal-repo.example.com/vms/win2022.qcow2"
        destination = "local/win2022-template.qcow2"
      }
    }
  }
}
```

**Предусловия:**
- Драйвер `virt` включён на клиентах
- Установлен `libvirt` и bridge `virbr0` настроен
- Образ VM доступен по указанному URL

**Развёртывание:**
```bash
nomad job run legacy-vm.nomad.hcl
```

**Валидация:**
```bash
nomad alloc status <alloc-id>
# → task "windows-node" state: running

virsh list --all
# → VM отображается в списке libvirt
```

**Типичные ошибки:**
- `virt: bridge not found` — проверьте конфигурацию сети libvirt
- `artifact download failed` — проверьте доступность URL и место на диске

### 5. Blue-Green развёртывание (Consul API Gateway)

Использование блока `update` и тегов для бесшовного переключения трафика:

```hcl
job "payment-gateway" {
  datacenters = ["dc1"]

  update {
    max_parallel     = 3
    canary           = 3
    auto_promote     = false
    auto_revert      = true
    health_check     = "checks"
    min_healthy_time = "1m"
  }

  group "api" {
    count = 3

    service {
      name = "payments"
      port = "http"

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

**Предусловия:**
- Consul настроен для service discovery
- Балансировщик (nginx/Envoy/F5) настроен на маршрутизацию по тегам

**Развёртывание:**
```bash
# 1. Запуск canary-версии
nomad job run -detach payment-gateway.nomad.hcl

# 2. Проверка canary-аллокаций
nomad deployment status
# → Покажет canary allocations

# 3. Ручной промоут после верификации
nomad deployment promote <deployment-id>

# 4. Проверка статуса
nomad job status payment-gateway
# → Successful deployments: 1
```

**Валидация:**
```bash
# Проверка сервисов в Consul
curl http://consul.service.consul:8500/v1/catalog/service/payments
# → Должны отображаться сервисы с тегом color=green

# Health check
curl http://<service-address>:<port>/health
# → {"status":"ok"}
```

**Типичные ошибки:**
- `canary allocations failed` — проверьте health check конфигурацию
- `deployment stuck` — выполните `nomad deployment fail <id>` для отката

### 6. Работа с данными (CSI Volume)

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

**Предусловия:**
- CSI плагин установлен и настроен на клиентах
- Volume `production-db-vol` создан в CSI backend

**Развёртывание:**
```bash
nomad job run stateful-app.nomad.hcl
```

**Валидация:**
```bash
nomad alloc status <alloc-id>
# → task "db" state: running

nomad volume status production-db-vol
# → Access Mode: single-node-writer, Attachment Mode: file-system
```

**Типичные ошибки:**
- `csi: plugin not found` — проверьте установку CSI плагина на клиентах
- `volume: already attached` — том уже примонтирован к другой аллокации

### 7. Периферийные вычисления (Edge Computing)

Сценарий с использованием `system` job и `exec2` для работы на слабых ARM-устройствах:

```hcl
job "edge-monitor" {
  datacenters = ["edge-region"]
  type        = "system"

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

**Предусловия:**
- Nomad клиент установлен на edge-устройстве
- Узел помечен классом `raspberry-pi`: `nomad node attr apply -set node.class=raspberry-pi`

**Развёртывание:**
```bash
nomad job run edge-monitor.nomad.hcl
```

**Валидация:**
```bash
nomad job status edge-monitor
# → Type: system, Status: running

nomad node status -self
# → Привязанные аллокации: 1
```

**Типичные ошибки:**
- `no nodes match constraints` — проверьте атрибут `node.class` на целевом узле
- `system job already running` — system job выполняется по одной копии на узел

### 8. Глобальная федерация (Multi-Region)

Настройка репликации между регионами для отказоустойчивости:

```hcl
# server.hcl (Регион 1)
region           = "europe"
datacenter       = "eu-west-1"
server           = true
bootstrap_expect = 3

replication {
  enabled = true
}
```

```bash
# Присоединение второго региона (US) к первому (EU)
nomad system federation join nomad-eu.example.com:4646

# Проверка статуса федерации
nomad system federation status
```

**Предусловия:**
- Оба региона имеют доступ друг к другу по порту 4646
- ACL включён и настроен в Authoritative Region

**Валидация:**
```bash
nomad system federation status
# → Regions: [europe us-east-1], Federation: active

# Проверка репликации токенов
nomad acl token list -global
# → Токены реплицируются в оба региона
```

**Типичные ошибки:**
- `federation join failed` — проверьте сетевую связность и ACL токены
- `replication disabled` — убедитесь, что `replication.enabled = true` в Authoritative Region

### 9. Мультитенантная среда (Namespaces + Quotas)

Разделение окружений dev/staging/prod внутри одного кластера с изоляцией ресурсов:

```hcl
# namespace.hcl
namespace "production" {
  description = "Production workloads"
}

namespace "staging" {
  description = "Staging environment"
}

namespace "development" {
  description = "Development workloads"
}

# quota.hcl
quota "spec" {
  name = "production-quota"
  description = "Production resource limits"

  region_limit {
    region = "global"
    cpu    = 16000
    memory = 32768
  }

  namespace_limit {
    namespace = "production"
    cpu       = 8000
    memory    = 16384
    max_jobs  = 50
  }
}
```

```bash
# Создание неймспейсов
nomad namespace apply namespace.hcl

# Применение квоты
nomad quota apply quota.hcl

# Развёртывание задания в production неймспейсе
nomad job run -namespace=production app.nomad.hcl
```

**Предусловия:**
- Enterprise-версия Nomad (Namespaces и Quotas требуют лицензии)
- ACL политики настроены для ограничения доступа к неймспейсам

**Валидация:**
```bash
nomad namespace list
# → [default, development, staging, production]

nomad quota status production-quota
# → Region: global, CPU: 8000/16000, Memory: 16384/32768

nomad job status -namespace=production webapp
# → Запущено в неймспейсе production
```

**Типичные ошибки:**
- `quota exceeded` — достигнут лимит ресурсов; проверьте `nomad quota status`
- `namespace not found` — неймспейс не создан; выполните `nomad namespace apply`

### 10. Rolling Update с Canary и Auto-Revert

Стратегия обновления с постепенной раскаткой и автоматическим откатом при провале:

```hcl
job "payment-api" {
  datacenters = ["dc1"]
  type        = "service"

  update {
    canary           = 2
    max_parallel     = 2
    auto_promote     = false
    auto_revert      = true
    health_check     = "checks"
    min_healthy_time = "30s"
    healthy_deadline = "5m"
    progress_deadline = "10m"
  }

  group "api" {
    count = 6

    service {
      name = "payments"
      port = "http"

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
        image = "registry/payment-api:v3"
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

**Предусловия:**
- Новый образ `payment-api:v3` протестирован в staging
- Health check `/health` доступен в новом образе

**Развёртывание:**
```bash
# 1. План обновления (dry-run)
nomad job plan payment-api.nomad.hcl
# → Покажет, какие аллокации будут обновлены

# 2. Запуск обновления
nomad job run payment-api.nomad.hcl

# 3. Мониторинг деплоя
nomad deployment status
# → Статус: running, Canary allocations: 2

# 4. Промоут после верификации
nomad deployment promote <deployment-id>

# 5. Проверка финального статуса
nomad job status payment-api
# → Successful deployments: 1
```

**Валидация:**
```bash
# Проверка метрик здоровья
curl http://<service-address>:<port>/metrics | grep http_requests_total

# Проверка логов
nomad alloc logs <alloc-id> server | grep "started"
```

**Типичные ошибки:**
- `deployment failed` — проверьте `auto_revert` и логи аллокаций
- `canary allocations unhealthy` — проверьте health check endpoint
- `progress deadline exceeded` — увеличьте `progress_deadline` или исправьте проблему с деплоем

### 11. Плановое обслуживание узлов (Node Drain)

Безопасное перемещение задач с узла для выполнения обслуживания:

```bash
# 1. Перевод узла в режим drain с дедлайном 10 минут
nomad node drain -enable -self -deadline="10m"

# 2. Ожидание завершения аллокаций
watch -n 5 nomad node status -self
# → Ожидаем статуса "drain"

# 3. Выполнение обслуживания (обновление ОС, драйверов, прошивок)
# ...

# 4. Снятие drain и возвращение в кластер
nomad node drain -disable -self
nomad node eligibility -enable -self

# 5. Валидация
nomad node status -self
# → Status: ready, Eligibility: eligible
```

**Предусловия:**
- Узел не является последним в кластере (проверьте `nomad node status`)
- Системные задачи (type=system) либо отсутствуют, либо помечены `-ignore-system-jobs`

**Валидация:**
```bash
# Проверка статуса слива
nomad node drain -status -self
# → Drain: true, Deadline: <время>

# Проверка аллокаций
nomad node status -self
# → allocations: 0 (все перемещены)
```

**Типичные ошибки:**
- `node is not eligible` — выполните `nomad node eligibility -enable`
- `allocations failed to stop` — используйте `-force` или увеличьте `deadline`
- `drain in progress` — дождитесь завершения текущей операции

### 12. Шаблонизация деплойментов (Nomad Pack)

Использование Nomad Pack для повторного использования конфигураций:

```bash
# 1. Инициализация пакета
nomad-pack init ./my-app-package

# 2. Установка с переопределением переменных
nomad-pack install my-app-package \
  -f overrides.hcl \
  -f environment-specific.hcl

# 3. Публикация в локальный registry
nomad-pack publish ./my-app-package
```

**overrides.hcl:**
```hcl
image = "my-registry/app:v3"
replicas = 5
```

**Предусловия:**
- Nomad Pack >= 0.9 установлен
- Регистр пакетов доступен (по умолчанию: community registry)

**Валидация:**
```bash
nomad-pack list
# → Установленные пакеты: my-app-package

nomad job status my-app-package-web
# → Job развёрнут успешно
```

**Типичные ошибки:**
- `pack not found` — проверьте имя пакета и registry
- `variable missing` — убедитесь, что все обязательные переменные указаны в overrides.hcl

### 13. Политики безопасности (Sentinel)

Запрет на использование небезопасных драйверов:

```sentinel
import "nomad"

main = rule {
    all_tasks_secure
}

all_tasks_secure = rule {
    all nomad.job.task_groups as tg {
        all tg.tasks as task {
            task.driver != "raw_exec"
        }
    }
}
```

**Предусловия:**
- Enterprise-версия Nomad с включённым Sentinel
- Политика прикреплена к ACL role

**Применение:**
```bash
# 1. Создание политики
nomad Sentinel policy create secure-drivers.sentinel

# 2. Прикрепление к role
nomad acl role create \
  -name="secure-role" \
  -policy="secure-drivers-policy"

# 3. Создание токена
nomad acl token create -role="secure-role"
```

**Валидация:**
```bash
# Попытка запуска задания с raw_exec
nomad job run insecure.nomad.hcl
# → Валидация отклонена: raw_exec запрещён политикой
```

**Типичные ошибки:**
- `sentinel: policy not found` — проверьте имя политики и её статус
- `permission denied` — убедитесь, что токен имеет прикреплённую политику

### 14. Резервное копирование и восстановление (Raft Snapshot)

Создание снапшота состояния кластера для disaster recovery:

```bash
# Создание снапшота (выполняется на серверном агенте)
nomad operator raft snapshot save /backup/nomad-raft.snap

# Проверка снапшота
nomad operator raft list
# → snapshots: nomad-raft.snap

# Восстановление (требуется остановка серверов)
# 1. Остановить все серверные агенты
# 2. Заменить состояние: nomad operator raft snapshot restore /backup/nomad-raft.snap
# 3. Запустить серверы
```

**Предусловия:**
- Доступ к серверному агенту (SSH/консоль)
- Достаточно места на диске для снапшота (обычно 10-30% от размера состояния)

**Валидация:**
```bash
# После восстановления
nomad status
# → Задания и аллокации восстановлены

nomad acl token list
# → ACL-токены присутствуют
```

**Типичные ошибки:**
- `snapshot: no snapshots found` — проверьте путь к файлу
- `restore: servers must be stopped` — убедитесь, что все серверы остановлены перед восстановлением

### 15. Мониторинг кластера (Prometheus)

Сбор метрик Nomad для SRE-дашборда:

```hcl
# agent.hcl (на сервере или клиенте)
prometheus {
  port = 9090
}
```

```bash
# Запуск агента с Prometheus exposition
nomad agent -config=agent.hcl

# Проверка метрик
curl -s http://localhost:9090/v1/metrics | grep nomad_client_allocations
# → nomad_client_allocations_running{...} 5
# → nomad_client_allocations_cpu_total_ticks{...} 1250
```

**Ключевые метрики для SRE:**
- `nomad_client_allocations_running` — количество запущенных аллокаций
- `nomad_client_allocations_cpu_total_ticks` — потребление CPU
- `nomad_client_allocations_memory_rss` — потребление RAM
- `nomad_server_evaluations_total` — количество эвалюаций (стабильность планирования)
- `nomad_server_plan_apply_duration_seconds` — задержки планировщика
- `nomad_raft_leader` — текущий лидер Raft (1 = да, 0 = нет)

**Валидация:**
```bash
# Проверка доступности метрик
curl -s http://localhost:9090/v1/metrics | head -20
# → Метрики начинаются с nomad_
```

**Типичные ошибки:**
- `connection refused` — проверьте, что порт 9090 открыт в конфигурации
- `no metrics` — убедитесь, что агент запущен с включённым Prometheus блоком

## Диагностика и устранение неисправностей

### Инструментарий CLI

| Команда | Назначение |
| :--- | :--- |
| `nomad node status -self` | Проверка здоровья текущего агента и его атрибутов. |
| `nomad node status -verbose` | Подробный статус узла, драйверы и порты. |
| `nomad job status -evals <job>` | История эвалюаций (причины невыполненного планирования). |
| `nomad job plan <job.hcl>` | Dry-run планирования: показывает, какие изменения будут применены. |
| `nomad monitor -level=debug` | Потоковый просмотр логов сервера в реальном времени. |
| `nomad alloc status <alloc-id>` | Детальный статус аллокации (события, задачи, ресурсы). |
| `nomad alloc logs <alloc-id> <task>` | Потоковый вывод логов задачи. |
| `nomad deployment status <dep>` | Отслеживание процесса раскатки Canary/Blue-Green. |
| `nomad node drain -status` | Текущий статус слива узла. |
| `nomad operator raft list` | Список доступных снапшотов Raft. |
| `nomad status` | Общий обзор кластера (задания, узлы, аллокации). |

### Типовые проблемы и решения

1.  **"No nodes are available":**
    - Проверьте `constraints` (например, требуемая версия ядра ОС).
    - Убедитесь, что драйвер (Docker/Exec2) установлен и виден в `nomad node status -stats`.
    - Проверьте квоты: `nomad quota status`.
    - Убедитесь, что узел не находится в `drain` или `ineligible` статусе.

2.  **ACL Access Denied:**
    - Проверьте `NOMAD_TOKEN`. В федерации убедитесь, что токен имеет флаг `-global`.
    - Проверьте, что политика токена включает необходимые capabilities и namespace.
    - Для management операций требуется management token, а не client.

3.  **Autoscaler Failure:**
    - Проверьте доступность источника метрик (Prometheus API).
    - Убедитесь, что лимиты `min/max` в политике не противоречат текущему состоянию кластера.
    - Проверьте логи autoscaler: `nomad-autoscaler -verbose`.

4.  **Template rendering error:**
    - Проверьте синтаксис Consul Template в блоке `template`.
    - Убедитесь, что Vault policy разрешает доступ к указанному пути.
    - Проверьте логи аллокации: `nomad alloc logs <alloc-id> <task>`.

5.  **Drain stuck:**
    - Проверьте, есть ли `system` jobs или задания без `kill_timeout`.
    - Используйте `nomad node drain -enable -self -ignore-system-jobs` для обхода.
    - Для аварийного освобождения узла: `nomad node drain -enable -self -force`.

## Дополнительная информация

См. также:

- **[Nomad — определения и базовые концепции](./definitions_and_concepts.md)** — теоретическая база.
- **[Nomad — продвинутые темы и версии](./advanced_topics.md)** — детали LTS и Enterprise.
- **[Nomad — мониторинг (Prometheus + Grafana)](./nomad_monitoring.md)** — метрики и алерты.
- **[Nomad — CI/CD Pipeline](./nomad_cicd_pipeline.md)** — автоматизация деплоя.
- **[Nomad — Security Hardening](./nomad_security_hardening.md)** — настройка безопасности.
- **[Интеграция с Vault](../Vault/overview.md)** — управление секретами.
- **[Интеграция с Consul](../Consul/consul_overview.md)** — сетевое взаимодействие.
- **[Критерии выбора платформы: Docker, Kubernetes, Nomad и IDP](../Kubernetes/Concepts/platform_selection_criteria.md)** — когда выбирать Nomad.
