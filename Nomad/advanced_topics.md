# Nomad — продвинутые темы

## Определения

**LTS (Long-Term Support)** — версия с расширенным периодом поддержки (12+ месяцев), рекомендуемая для стабильных production-сред.

**Enterprise-версия** — коммерческое издание HashiCorp с функциями для крупных организаций (Namespaces, Quotas, Sentinel).

**Федерация кластеров (Federation)** — объединение нескольких регионов Nomad в единую систему управления с общими ACL и неймспейсами через **Authoritative Region**.

**Nomad Pack** — пакетный менеджер и движок шаблонизации (аналог Helm для Kubernetes), позволяющий повторно использовать и распространять конфигурации приложений.

**Nomad Autoscaler** — внешний сервис для автоматического масштабирования ресурсов (узлов кластера или количества реплик задач) на основе метрик (Prometheus, InfluxDB).

**Sentinel** — фреймворк "Policy as Code", позволяющий определять тонкие правила допуска (например, ограничение используемых драйверов или образов) на уровне сервера.

**Workload Identity** — механизм OIDC-аутентификации, позволяющий задачам безопасно взаимодействовать с Vault, Consul и облачным провайдерам без статических токенов.

**Lifecycle Hooks** — (новое в v2.0) функции `Init` и `Shutdown` для драйверов задач, обеспечивающие подготовку и очистку ресурсов до и после выполнения основной нагрузки.

**Quota (Квота)** — ограничение на потребление ресурсов (CPU, memory, задачи) на уровне региона или неймспейса. Применяется при планировании: если квота исчерпана, новые аллокации отклоняются до освобождения ресурсов.

**Namespace (Неймспейс)** — логическая изоляция задач внутри кластера. ACL-политики, квоты и параметры планирования могут привязываться к неймспейсу, обеспечивая мультитенантность.

**Priority (Приоритет)** — числовое значение (0–100), определяющее порядок планирования задач. Задачи с более высоким приоритетом вытесняют (preempt) менее приоритетные при дефиците ресурсов.

**Drain (Слив)** — режим узла, при котором Nomad прекращает размещение новых аллокаций и последовательно останавливает/перемещает существующие задачи на другие узлы.

## Основные концепции

### Версии и поддержка

| Версия | Дата выпуска | Статус | Ключевые изменения |
| :--- | :--- | :--- | :--- |
| **v2.0.4** | Апрель 2026 | **Latest** | Lifecycle Hooks, полная миграция на Workload Identity, Batch Timeouts. |
| **v1.11.x** | Январь 2026 | Поддерживаемая | Оптимизация планировщика для AI/ML нагрузок. |
| **v1.8.x** | Май 2024 | **LTS** | Первая версия с долгосрочной поддержкой, стабильный API. |
| v1.7.x | — | EOL | Конец жизненного цикла, рекомендуется миграция. |

**Важно:** Для production рекомендуется использовать LTS-версии (v1.8.x) или последний стабильный релиз (v2.x). Перед обновлением проверяйте [Release Notes](https://developer.hashicorp.com/nomad/docs/upgrade) на предмет breaking changes.

### Безопасность и управление доступом (ACL)

В версии 2.0 реализована модель **Authoritative Region**, где один регион является источником правды для всех ACL-токенов и политик.

- **Global Tokens:** Создаются в главном регионе и автоматически реплицируются во все остальные.
- **SSO и OIDC:** Нативная поддержка аутентификации через Okta, Azure AD и Keycloak для доступа к CLI/UI.
- **Namespaces:** Логическая изоляция задач. В Enterprise-версии поддерживается иерархия неймспейсов.

#### ACL Policies и Roles

ACL-политики определяют, какие действия разрешены токену. Существует два основных типа:
- **Client Policies:** применяются к задачам и ограничивают взаимодействие с API Nomad.
- **Management Policies:** предоставляют полный доступ к управлению кластером (требуются для operators).

Политики связываются с токенами через `role` или напрямую. Пример гранулярной политики, разрешающей только чтение заданий в определённом неймспейсе:

```hcl
namespace "production" {
  policy       = "read"
  capabilities = ["jobs", "allocations"]
}

capability "read" {
  description = "Разрешено только чтение заданий и аллокаций"
}
```

**Валидация:** после создания политики проверьте её действие через `nomad acl token create` и `nomad job status` с соответствующим токеном.

### Неймспейсы (Namespaces)

Неймспейсы обеспечивают логическую изоляцию рабочих нагрузок внутри одного кластера. Это ключевой механизм мультитенантности в Enterprise-версии.

**Ключевые свойства:**
- Изоляция задач: задания из разных неймспейсов не видят друг друга при планировании.
- Разделение ACL: политики могут применяться к конкретным неймспейсам.
- Квоты: лимиты ресурсов настраиваются независимо для каждого неймспейса.
- Дефолтный неймспейс: `default` используется при отсутствии явного указания.

**Варианты использования:**
- Разделение окружений (dev/staging/prod) внутри одного кластера.
- Изоляция проектов/команд.
- Ограничение blast radius при сбоях.

### Квоты и ограничения (Quotas)

Quotas позволяют задавать жёсткие лимиты на ресурсы кластера или неймспейса. Применяются на уровне сервера при планировании.

**Типы квот:**
- **Region Quota:** общий лимит на все датацентры региона.
- **Namespace Quota:** лимиты внутри неймспейса.

**Ограничиваемые ресурсы:**
- `cpu` — общее количество MHz или cores.
- `memory` — объём RAM в MB.
- `jobs` — максимальное количество активных заданий.
- `allocations` — максимальное количество аллокаций.

**Важно:** При достижении квоты Nomad отклоняет планирование новых задач до освобождения ресурсов. Квоты не влияют на уже запущенные аллокации.

### Автоматическое масштабирование (Autoscaler)

Nomad Autoscaler v0.5+ поддерживает четыре типа масштабирования:

1.  **Horizontal Application Scaling:** Изменение параметра `count` в группе задач на основе нагрузки (CPU, RPS).
2.  **Horizontal Cluster Scaling:** Динамическое добавление/удаление узлов (AWS ASG, Azure Scale Sets).
3.  **Dynamic Application Sizing (DAS):** Анализ потребления ресурсов и выдача рекомендаций по изменению `resources.cpu/memory` (Enterprise).
4.  **Schedule-based Scaling:** Возможность изменять масштаб по расписанию (например, уменьшение количества реплик ночью).

#### Пример: Target-based autoscaling

```hcl
job "webapp" {
  datacenters = ["dc1"]
  type        = "service"

  group "app" {
    count = 3

    scaling {
      enabled = true
      min     = 2
      max     = 20

      policy {
        cooldown = "5m"

        check "cpu" {
          source = "prometheus"
          query  = "avg(rate(nomad_client_allocations_cpu_total_ticks[5m]))"
          strategy "target-value" {
            target = 70
          }
        }

        check "memory" {
          source = "prometheus"
          query  = "avg(nomad_client_allocations_memory_rss / (1024*1024*1024))"
          strategy "target-value" {
            target = 0.8
          }
        }
      }
    }

    task "server" {
      driver = "docker"
      config {
        image = "registry/webapp:v2"
        ports = ["http"]
      }
      resources {
        cpu    = 500
        memory = 512
      }
    }
  }
}
```

#### Пример: Schedule-based scaling

```hcl
scaling {
  enabled = true
  min     = 2
  max     = 10

  policy {
    cooldown = "10m"

    schedule "night-scale-down" {
      cron            = "0 22 * * *"
      timezone        = "Europe/Moscow"
      enabled         = true
      target_count    = 2
    }

    schedule "morning-scale-up" {
      cron            = "0 8 * * *"
      timezone        = "Europe/Moscow"
      enabled         = true
      target_count    = 5
    }

    check "avg_cpu" {
      source = "prometheus"
      query  = "avg(nomad_client_allocs_cpu_total_ticks)"
      strategy "target-value" {
        target = 70
      }
    }
  }
}
```

#### Запуск Autoscaler

```bash
# Запуск Nomad Autoscaler
nomad-autoscaler agent \
  -nomad-address=http://nomad.service.consul:4646 \
  -nomad-token=<token> \
  -prometheus-address=http://prometheus.service.consul:9090

# Проверка политик
nomad scaling status <job-name>
```

### Управление узлами и обслуживание (Node Management)

Управление жизненным циклом узлов критично для SRE-практик: плановые работы, обновления ОС и драйверов требуют безопасного перемещения задач.

#### Drain (Слив узла)

Режим `drain` останавливает размещение новых аллокаций и последовательно мигрирует существующие:

```bash
# Перевод узла в режим слива (без принудительного завершения)
nomad node drain -enable -self

# Принудительный слив (для аварийных случаев)
nomad node drain -enable -self -force

# Пометка узла как готового к обслуживанию
nomad node status -self
# Ожидайте статуса "ready" или "drain"
```

**Параметры:**
- `-force` — завершает запущенные аллокации без ожидания `kill_timeout`.
- `-deadline` — максимальное время ожидания завершения задач.
- `-ignore-system-jobs` — не затрагивает system jobs.

**Сценарий для SRE:**
1. Перевести узел в drain.
2. Дождаться завершения всех аллокаций.
3. Выполнить обслуживание (обновление ОС, драйверов, прошивок).
4. Снять drain: `nomad node drain -disable -self`.
5. Проверить статус: `nomad node status -self`.

#### Maintenance Mode (Режим обслуживания)

При включении maintenance режима Nomad исключает узел из планирования, но не останавливает существующие аллокации:

```bash
nomad node eligibility -disable -self
# Выполнить обслуживание
nomad node eligibility -enable -self
```

**Различие:**
- `drain` — перемещает существующие задачи.
- `maintenance/eligibility` — только запрещает новые размещения.

### Управление пакетами (Nomad Pack)

Nomad Pack упрощает деплой сложных стеков:
- **Registry:** Возможность подключения публичных и приватных репозиториев пакетов.
- **Dependency Management:** Пакеты могут зависеть от других пакетов (например, Web-app зависит от Redis).
- **Variables:** Гибкая настройка параметров через `overrides.hcl`.

#### Пример использования

```bash
# Публикация пакета в локальный registry
nomad-pack publish ./my-app-package

# Установка с переопределением переменных
nomad-pack install my-app-package \
  -f overrides.hcl \
  -f environment-specific.hcl
```

### Стратегии обновления (Update Strategies)

Блок `update` в задании определяет стратегию раскатки изменений. Понимание этих стратегий необходимо для SRE при выполнении deployments с минимальным downtime.

#### Rolling Update

Последовательное обновление реплик с контролем здоровья:

```hcl
update {
  max_parallel      = 2
  min_healthy_time  = "10s"
  healthy_deadline  = "5m"
  progress_deadline = "10m"
  auto_revert       = true
  auto_promote      = true
  canary            = 0
}
```

**Параметры:**
- `max_parallel` — максимальное количество одновременно обновляемых аллокаций.
- `min_healthy_time` — минимальное время здорового состояния перед продвижением.
- `healthy_deadline` — время ожидания здорового состояния до отката.
- `progress_deadline` — время ожидания завершения обновления.
- `auto_revert` — автоматический откат при провале health check.

#### Canary Deployment

Постепенное увеличение трафика на новую версию:

```hcl
update {
  canary           = 2
  max_parallel     = 1
  auto_promote     = false
  auto_revert      = true
  health_check     = "checks"
  min_healthy_time = "30s"
}
```

**Практика:** После ручного промоута (через `nomad deployment promote <dep-id>`) Nomad завершает оставшиеся обновления. Если `auto_promote = true`, промоут происходит автоматически после `min_healthy_time`.

#### Blue-Green Deployment

Используется комбинация `update` и сервисных тегов. В Consul или Native SD можно переключать трафик через теги:

```hcl
service {
  name = "payments"
  port = "http"
  tags = ["color=blue"]
}
```

Для переключения на «зелёный» релиз обновите тег в HCL и выполните `nomad job run`. Трафик переключится после обновления service definition.

### Хранилище и тома (Storage)

Nomad поддерживает два основных типа volumes:

#### Host Volumes

Монтирование путей с локального диска узла. Подходит для состояния, требующего быстрого доступа:

```hcl
volume "local-data" {
  type      = "host"
  source    = "nomad/alloc_mounts"
  read_only = false
}

task "app" {
  volume_mount {
    volume      = "local-data"
    destination = "/var/lib/app"
  }
}
```

#### CSI Volumes

Динамическое подключение внешних блочных устройств через Container Storage Interface:

```hcl
volume "csi-data" {
  type            = "csi"
  source          = "production-db-vol"
  attachment_mode = "file-system"
  access_mode     = "single-node-writer"
}
```

**Ограничения CSI:**
- Поддерживается только на клиентах с установленным CSI плагином.
- Для `block` attachment_mode требуется поддержка в драйвере задачи.
- Тома не перемещаются между узлами автоматически (требуется CSI controller).

#### Ephemeral Storage

Каждая задача получает ephemeral диск (tmpfs или корневой overlay) ограниченного размера. Размер задаётся в блоке `resources`:

```hcl
resources {
  cpu    = 500
  memory = 512
  # Ephemeral disk (Docker, Exec2)
  ephemeral_disk {
    size = 1024  # MB
    migrate = true
    sticky   = false
  }
}
```

### Сетевая модель (Networking)

Nomad предоставляет гибкие варианты сетевой конфигурации:

#### Режимы сети

| Режим | Назначение | Пример |
| :--- | :--- | :--- |
| **bridge** | Виртуальный мост (CNI или встроенный) | Docker-контейнеры с NAT |
| **host** | Прямое использование интерфейса узла | Высокопроизводительные сервисы |
| **none** | Без сети | Фоновые пакетные задачи |
| **cni** | Внешний CNI плагин (Calico, Cilium) | Продвинутые политики сети |

#### Port Allocation

- **Dynamic:** Nomad автоматически назначает свободный порт из указанного диапазона.
- **Static:** Фиксированный порт, требующий отсутствия конфликтов на узле.

```hcl
network {
  port "http" { to = 8080 }  # Dynamic allocation
  port "metrics" { static = 9090 }  # Static
}
```

**Резервирование портов:** Используйте `reserved_ports` в конфигурации клиента для исключения диапазонов из динамического распределения.

### Шаблонизация и работа с секретами (Templates)

Блок `template` использует синтаксис Consul Template для рендеринга конфигураций на лету. Это ключевой механизм интеграции с Vault и Consul.

#### Интеграция с Vault

```hcl
template {
  data        = <<EOH
{{ with secret "kv/data/webapp/config" }}
DB_PASSWORD="{{ .Data.data.db_password }}"
{{ end }}
EOH
  destination = "secrets/env"
  env         = true
  change_mode = "restart"
}
```

**Параметры:**
- `env = true` — экспорт переменных в окружение задачи.
- `change_mode = "restart"` — перезапуск задачи при изменении секрета.
- `splay = "5s"` — случайная задержка для предотвращения thundering herd.

#### Интеграция с Consul KV

```hcl
template {
  data        = <<EOH
{{ key "config/app/database_url" }}
EOH
  destination = "local/db.conf"
}
```

#### Change Notification

Template может генерировать события, которые Nomad использует для принятия решений:

```hcl
template {
  data          = <<EOH
{{ with service "webapp" }}
UPSTREAM="{{ .Address }}:{{ .Port }}"
{{ end }}
EOH
  destination   = "local/upstream.conf"
  change_mode   = "signal"
  change_signal = "SIGHUP"
}
```

### Мониторинг и метрики (Monitoring)

Для SRE-мониторинга Nomad exposes метрики через HTTP API. Интеграция с Prometheus осуществляется через статическую конфигурацию или service discovery.

#### Ключевые метрики

| Метрика | Назначение |
| :--- | :--- |
| `nomad_client_allocations_running` | Количество запущенных аллокаций на клиенте. |
| `nomad_client_allocations_cpu_total_ticks` | Суммарное потребление CPU (normalized). |
| `nomad_client_allocations_memory_rss` | Фактическое потребление RAM (RSS). |
| `nomad_server_evaluations_total` | Количество эвалюаций (показатель стабильности планирования). |
| `nomad_server_plan_append_total` | Время применения планов (latency планировщика). |
| `nomad_raft_leader` | Текущий лидер Raft (1 = да, 0 = нет). |

#### Сбор метрик

```hcl
# Прямой запрос к /v1/metrics (формат Prometheus)
curl -s http://localhost:4646/v1/metrics | grep nomad_client_allocations

# Или через agent-config (Prometheus exposition port)
prometheus {
  port = 9090
}
```

#### Мониторинг кластера

Критические метрики для SRE:
- **Plan latency:** `nomad_server_plan_apply_duration_seconds` — задержки планировщика.
- **Eval queue depth:** `nomad_server_evaluations_pending` — накопление необработанных эвалюаций.
- **Node status:** `nomad_client_status{status="ready"}` — количество готовых узлов.
- **Alloc failures:** `nomad_client_allocations_unknown` — аллокации в состоянии unknown.

### Приоритеты и вытеснение (Priority & Preemption)

Каждому заданию назначается приоритет (0–100, по умолчанию 50). При дефиците ресурсов Nomad может вытеснить (preempt) низкоприоритетные задачи в пользу высокоприоритетных.

**Правила работы:**
- Задания с `priority = 100` reserved для системных задач (`type = "system"`).
- Вытеснение происходит только между заданиями одного типа (service/batch) или при явном указании.
- При вытеснении Nomad отправляет `SIGTERM`, затем `SIGKILL` после `kill_timeout`.

**Рекомендации:**
- Используйте `priority` для разделения критических и фоновых задач.
- Настройте `kill_timeout` и `shutdown_delay` для корректного завершения.
- Для system jobs установите `priority = 100` и `coalesce = true`.

## Практические сценарии

### Настройка глобального ACL-токена

Для управления федерацией необходимо создать токен в Authoritative-регионе:

```bash
# Выполняется в главном регионе
nomad acl token create \
  -name="Global-Admin" \
  -type="client" \
  -global \
  -policy="admin-policy"
```

### Управление узлами и обслуживание

Сценарий планового обслуживания узла с минимальным влиянием на сервисы:

```bash
# 1. Перевод узла в режим drain (ожидание завершения задач)
nomad node drain -enable -self -deadline="10m"

# 2. Проверка статуса (ожидаем "drain")
nomad node status -self

# 3. Выполнение обслуживания (обновление ОС, драйверов)

# 4. Снятие drain и возвращение в кластер
nomad node drain -disable -self
nomad node eligibility -enable -self

# 5. Валидация
nomad node status -self
# → "Status: ready", "Eligibility: eligible"
```

**Типичные ошибки:**
- `node is not eligible` — выполните `nomad node eligibility -enable`.
- `allocations failed to stop` — используйте `-force` или увеличьте `deadline`.
- `drain in progress` — дождитесь завершения текущей операции.

### Настройка квот (Quotas)

Ограничение ресурсов для неймспейса `production`:

```hcl
# quota-spec.hcl
quota "spec" {
  name = "production-quota"
  description = "Лимиты для production неймспейса"

  region_limit {
    region = "global"
    cpu    = 16000  # 16 cores в MHz
    memory = 32768  # 32 GB
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
# Применение спецификации
nomad quota apply quota-spec.hcl

# Проверка статуса
nomad quota status production-quota
```

**Валидация:** при попытке запуска задания, превышающего квоту, Nomad вернёт `Quota exceeded` в эвалюации.

### Масштабирование по расписанию (Autoscaler)

Пример политики для снижения нагрузки в нерабочее время:

```hcl
scaling "horizontal_scaling" {
  enabled = true
  min     = 2
  max     = 10

  policy {
    cooldown = "5m"
    
    # Сценарий: отключение масштабирования ночью
    schedule {
      cron    = "0 22 * * *" # 22:00 UTC
      enabled = false
    }

    check "avg_cpu" {
      source = "prometheus"
      query  = "avg(nomad_client_allocs_cpu_total_ticks)"
      strategy "target-value" {
        target = 70
      }
    }
  }
}
```

### Использование Sentinel для безопасности

Запрет на использование драйвера `raw_exec` для всех пользователей:

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

### Стратегии обновления (Update Strategies)

Пример Canary deployment с ручным промоутом:

```hcl
job "payment-api" {
  datacenters = ["dc1"]
  type        = "service"

  update {
    canary           = 3
    max_parallel     = 1
    auto_promote     = false
    auto_revert      = true
    health_check     = "checks"
    min_healthy_time = "30s"
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

**Валидация:**
```bash
nomad job run payment-api.nomad
nomad deployment status
# → При наличии canary аллокаций выполните:
nomad deployment promote <deployment-id>
```

### Шаблонизация и интеграция с Vault/Consul

Динамическое получение секретов и конфигурации через шаблоны:

```hcl
job "webapp" {
  datacenters = ["dc1"]
  type        = "service"

  group "web" {
    count = 2

    network {
      port "http" { to = 8080 }
    }

    service {
      name     = "frontend"
      provider = "nomad"
      port     = "http"
      check {
        type     = "http"
        path     = "/health"
        interval = "10s"
      }
    }

    task "server" {
      driver = "docker"
      config {
        image = "registry/webapp:v2"
        ports = ["http"]
      }

      identity {
        env  = true
        file = true
      }

      template {
        data        = <<EOH
{{ with secret "kv/data/webapp/config" }}
DB_HOST="{{ .Data.data.db_host }}"
DB_PASSWORD="{{ .Data.data.db_password }}"
{{ end }}
EOH
        destination = "secrets/app.env"
        env         = true
        change_mode = "restart"
        splay       = "5s"
      }

      template {
        data        = <<EOH
{{ with service "database" }}
DB_HOST="{{ .Address }}:{{ .Port }}"
{{ end }}
EOH
        destination = "local/db.conf"
        change_mode = "signal"
        change_signal = "SIGHUP"
      }
    }
  }
}
```

### Резервное копирование состояния кластера

Состояние кластера (задания, аллокации, токены) хранится в Raft. Для disaster recovery необходимо регулярно создавать снимки.

```bash
# Создание снимка Raft (выполняется на серверном агенте)
nomad operator raft snapshot save /backup/nomad-raft.snap

# Восстановление из снимка (требуется остановка серверов)
# 1. Остановить все серверные агенты
# 2. Заменить состояние: nomad operator raft snapshot restore /backup/nomad-raft.snap
# 3. Запустить серверы
```

**Важно:**
- Снимок содержит все задания, аллокации и ACL-политики.
- Для полного восстановления дополнительно резервируйте конфигурацию клиентов (`/etc/nomad.d/`) и данные драйверов (тома, CSI volumes).
- В федеративной топологии снимок создаётся в Authoritative Region для сохранения глобальных ACL.

### Выбор между Nomad и Kubernetes

Актуальное сравнение для архитектурного выбора в 2026 году:

| Критерий | Nomad (Pragmatic) | Kubernetes (Platform) |
| :--- | :--- | :--- |
| **Сложность внедрения** | Низкая (1 бинарный файл) | Высокая (15+ компонентов) |
| **Управление узлами** | Нативное (Fingerprinting) | Через Kubelet и провайдеры |
| **Типы нагрузок** | Контейнеры, VM, Binaries, Wasm | Преимущественно контейнеры |
| **Edge Computing** | Идеально (малый footprint) | Требует облегченных дистрибутивов |

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
| `nomad system federation status` | Состояние связей между регионами в федерации. |
| `nomad node drain -status` | Текущий статус слива узла. |
| `nomad operator raft list` | Список доступных снимков Raft. |
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

- [Определения и базовые концепции](./definitions_and_concepts.md) — основы архитектуры.
- [Практические сценарии](./practical_scenarios.md) — шаблоны HCL для разных нагрузок.
- [CI/CD Pipeline](./nomad_cicd_pipeline.md) — автоматизация деплоя.
- [Terraform и IaC](./nomad_terraform_iac.md) — управление инфраструктурой.
- [Consul Connect (Service Mesh)](./nomad_consul_connect.md) — шифрование и маршрутизация.
- [Логирование](./nomad_logging.md) — централизованный сбор логов.
- [Security Hardening](./nomad_security_hardening.md) — настройка безопасности.
- [Linux OS Tuning](./nomad_linux_os_tuning.md) — оптимизация узлов.
- [Cluster Upgrade](./nomad_cluster_upgrade.md) — обновление кластера.
- [Мониторинг (Prometheus + Grafana)](./nomad_monitoring.md) — метрики и алерты.
- [OpenTelemetry](./nomad_opentelemetry.md) — distributed tracing.
- [Chaos Engineering](./nomad_chaos_engineering.md) — тестирование устойчивости.
- [Production Architecture](./nomad_production_architecture.md) — reference architecture.
- [Ansible Provisioning](./nomad_ansible_provisioning.md) — автоматизация настройки.
- [Вопросы для собеседования](./nomad_interview_questions.md) — технические вопросы.
- [Официальный портал Nomad Learn](https://developer.hashicorp.com/nomad/tutorials)
- [Nomad Pack Community Registry](https://github.com/hashicorp/nomad-pack-community-registry)
