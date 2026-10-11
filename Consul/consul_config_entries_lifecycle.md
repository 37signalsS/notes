# Consul Config Entries Lifecycle

**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x / 1.20.x / 1.19.x

## Определения

**Consul Config Entries** — декларативные ресурсы конфигурации, управляющие поведением Service Mesh, маршрутизацией, балансировкой и доступом. В отличие от статической HCL-конфигурации агента, config entries хранятся в Raft-логе и динамически доставляются до Envoy-прокси через xDS без перезапуска процессов.

**Discovery Chain** — последовательность правил `service-router` → `service-splitter` → `service-resolver`, которую Consul использует для преобразования исходящего запроса в конкретный набор инстансов. Порядок жестко задан; изменить его нельзя.

**xDS** — набор API (CDS, RDS, EDS, LDS/EDS), по которым серверы Consul push-обновляют конфигурацию Envoy через gRPC-стрим на порту 8502.

**Sidecar** — Envoy-прокси, внедренный рядом с сервисным инстансом. Consul управляет его конфигурацией через config entries.

**Envoy** — прокси, используемый Consul для реализации L7-функций Service Mesh (маршрутизация, circuit breaking, observability).

**Namespace / Partition** — изоляционные границы в Consul Enterprise. Config entries привязаны к namespace/partition и не видны за их пределами.

## Основные концепции

### Полный каталог типов config entries

| Kind | Назначение | Когда использовать |
| :--- | :--- | :--- |
| `service-defaults` | Дефолты для сервиса: протокол, TLS, circuit breaking, upstream limits | Обязателен для L7; включает `Protocol`, `UpstreamConfig`, `TransparentProxy` |
| `service-router` | L7-маршрутизация по пути, заголовкам, методам | Canary по заголовку, версионирование API |
| `service-splitter` | Разделение трафика между subset'ами по весам | Канареечный релиз, Blue/Green |
| `service-resolver` | Subsets, failover, locality balancing, load balancing | Переключение на другой ДЦ/peer при сбое |
| `service-intentions` | L4/L7 правила разрешения трафика между сервисами | Zero-trust: разрешить только нужные связи |
| `proxy-defaults` | Глобальные дефолты для всех sidecar-прокси | Единый timeout, transparent proxy, mesh gateway mode |
| `exported-services` | Экспорт сервисов в peered кластеры или admin partitions | Multi-cluster топологии |
| `api-gateway` | Конфигурация north-south шлюза (Kubernetes Gateway API) | Внешний доступ к сервисам |
| `mesh-gateway` | Конфигурация межкластерного шлюза WAN | Гибридные/многоДЦ-топологии |

### Жизненный цикл config entry

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────┐
│  Разработка │───►│   Проверка   │───►│   Применение  │───►│  Мониторинг │
│  (HCL/JSON) │    │  (validate)  │     │  (config write) │     │  (xDS push) │
└──────────┘     └──────────────┘     └──────────────┘     └──────────┘
        │                                       │
        ▼                                       ▼
┌──────────┐                         ┌──────────────┐
│  Git      │                         │  Откат       │
│  commit   │                         │  (config delete) │
└──────────┘                         └──────────────┘
```

### Механизм доставки xDS

1. Config entry записывается в Raft-лог через `consul config write`.
2. Лидер реплицирует запись на follower-серверы.
3. Серверы генерируют snapshot конфигурации для Envoy.
4. Прокси получают обновление через gRPC-стрим (порт 8502).
5. Envoy применяет новую конфигурацию hot-reload без перезапуска процесса.

**Важно:** Доставка асинхронна. Envoy подтверждает прием ACK/NACK через xDS. Рост NACK'ов указывает на ошибки в конфигурации.

### Оценка порядка применения (Discovery Chain evaluation)

Для сервиса Consul строит discovery chain в строгом порядке:

1. `service-router` — выбор destination subset'а на основе L7-правил.
2. `service-splitter` — распределение трафика между subset'ами.
3. `service-resolver` — разрешение subset'а в конкретные инстансы, failover, балансировка.

Изменение порядка не поддерживается. При конфликте правил Consul использует первый match в router, а в resolver — `defaultSubset`.

## Практические сценарии

### 1. Service Defaults (дефолты для сервиса)

```hcl
# service-defaults.hcl
kind = "service-defaults"
name = "billing-api"
protocol = "http"

# Circuit breaking на уровне сервиса
upstream_config {
  defaults {
    limits {
      max_connections        = 1024
      max_pending_requests   = 1024
      max_concurrent_requests = 1024
    }
    passive_health_check {
      interval                = "10s"
      max_failures            = 5
      enforcing_consecutive_5xx = 100
      max_ejection_percent    = 20
      base_ejection_time      = "30s"
    }
  }
}
```

```bash
# Применение
consul config write service-defaults.hcl
# → Config entry written

# Валидация
consul config validate service-defaults.hcl
# → Valid configuration

# Чтение конкретного entry (HCL)
consul config read -kind service-defaults -name billing-api

# Чтение в JSON (удобно для скриптов)
consul config read -kind service-defaults -name billing-api -format=json | jq '.Protocol'
# → "http"

# Список всех entries определенного типа
consul config list -kind service-defaults
# → billing-api, web-api, order-db

# Список в JSON
consul config list -kind service-defaults -format=json | jq '.[]'
```

> **Важно:** `Protocol = "http"` или `"grpc"` обязателен для L7-функций (router, splitter, intentions). Без него трафик обрабатывается на L4 (TCP), и L7-правила игнорируются.

### 2. Proxy Defaults (глобальные дефолты для прокси)

```hcl
# proxy-defaults.hcl
kind = "proxy-defaults"
name = "global"

# Таймаут подключения к апстриму по умолчанию
config {
  local_connect_timeout_ms = 1000
  handshake_timeout_ms     = 10000
}

# Глобальный transparent proxy
transparent_proxy {
  default_http_ports    = [15001]
  default_https_ports   = [15443]
  excluded_networks     = ["10.0.0.0/8"]
}

# Глобальный режим mesh gateway
mesh_gateway {
  mode = "remote"
}
```

```bash
# Применение
consul config write proxy-defaults.hcl

# Проверка
consul config read -kind proxy-defaults -name global

# Валидация
consul config validate proxy-defaults.hcl
```

> **Важно:** Только один `proxy-defaults` entry может существовать одновременно (с `Name = "global"`). Повторная запись перезаписывает существующий. В Enterprise запись из `default` partition переопределяет остальные.

### 3. Service Router (маршрутизация)

```hcl
# service-router.hcl
kind = "service-router"
name = "web-api"

routes = [
  {
    match {
      http {
        path_prefix = "/api/v2"
        header {
          name  = "x-version"
          exact = "canary"
        }
      }
    }
    destination {
      service        = "web-api"
      service_subset = "v2"
    }
  },
  {
    # Дефолтный маршрут
    destination {
      service        = "web-api"
      service_subset = "v1"
    }
  }
]
```

```bash
# Применение
consul config write service-router.hcl

# Проверка через Envoy config dump
curl localhost:19000/config_dump | jq '.configs[] | select(.type_url == "type.googleapis.com/envoy.config.route.v3.RouteConfiguration")'
```

### 4. Service Splitter (канареечный релиз)

```hcl
# service-splitter.hcl
kind = "service-splitter"
name = "web-api"

splits = [
  {
    weight        = 90
    service_subset = "v1"
  },
  {
    weight        = 10
    service_subset = "v2"
  }
]
```

```bash
# Применение
consul config write service-splitter.hcl

# Проверка
consul config read -kind service-splitter -name web-api

# Проверка в Envoy
curl localhost:19000/config_dump | jq '.configs[] | select(.type_url == "type.googleapis.com/envoy.config.route.v3.WeightedCluster")'
```

### 5. Service Resolver (failover и subsets)

```hcl
# service-resolver.hcl
kind = "service-resolver"
name = "order-db"

subsets = {
  "v1" = { filter = "Service.Tags contains v1" }
}

failover = {
  "*" = {
    targets = [
      { datacenter = "dc2" },
      { service = "order-db-backup", datacenter = "dc-backup" }
    ]
  }
}

prioritize_by_locality {
  mode = "failover"
}
```

```bash
# Применение
consul config write service-resolver.hcl

# Проверка
consul config read -kind service-resolver -name order-db

# Проверка failover через Envoy
curl localhost:19000/config_dump | jq '.configs[] | select(.type_url == "type.googleapis.com/envoy.config.cluster.v3.Cluster") | .cluster.failure_overflow'
```

### 6. Service Intentions (авторизация)

```hcl
# service-intentions.hcl
kind = "service-intentions"
name = "billing-api"

sources = [
  {
    name   = "web-api"
    action = "allow"
    permissions = [
      {
        http {
          methods     = ["GET", "POST"]
          path_prefix = "/api/"
        }
      }
    ]
  },
  {
    name   = "admin-api"
    action = "allow"
    permissions = [
      {
        http {
          path_prefix = "/admin/"
        }
      }
    ]
  }
]
```

```bash
# Применение
consul config write service-intentions.hcl

# Проверка
consul config read -kind service-intentions -name billing-api

# Проверка разрешения
consul intention match -source web-api -destination billing-api
# → Allowed
```

### 7. Exported Services (peering)

```hcl
# exported-services.hcl
kind = "exported-services"
name = "default"

services = [
  {
    name      = "web-api"
    namespace = "default"
    consumers = [
      { peer = "cluster-b" }
    ]
  },
  {
    name      = "*"
    namespace = "monitoring"
    consumers = [
      { peer = "cluster-b" }
    ]
  }
]
```

```bash
# Применение
consul config write exported-services.hcl

# Проверка
consul config read -kind exported-services -name default

# Проверка peered services
consul catalog services -peer=cluster-b
```

> **Важно:** `exported-services` требует настроенного peering между кластерами. Для wildcard `*` в `namespace` убедитесь, что ACL-токен имеет права на чтение всех namespaces.

### 8. API Gateway и Mesh Gateway (краткий обзор)

```hcl
# api-gateway.hcl
kind = "api-gateway"
name = "api-gateway"

listeners = [
  {
    name     = "http"
    port     = 8080
    protocol = "http"
  }
]

routes = [
  {
    parent_refs = [{ name = "http" }]
    hosts       = ["api.example.com"]
    rules = [
      {
        matches = [{ path { value = "/api" } }]
        services = [{ name = "web-api" }]
      }
    ]
  }
]
```

```hcl
# mesh-gateway.hcl (WAN-шлюз)
kind = "mesh-gateway"
name = "mesh-gateway"

gateway {
  address = "10.0.2.10"
  port    = 8443
}

wan_address {
  address = "203.0.113.10"
  port    = 8443
}
```

## Жизненный цикл: управление как кодом

### Рекомендуемый workflow

```bash
# 1. Создание config entry в Git
git checkout -b feat/billing-api-defaults
cat > service-defaults-billing-api.hcl <<EOF
kind = "service-defaults"
name = "billing-api"
protocol = "http"

upstream_config {
  defaults {
    limits {
      max_connections = 1024
      max_pending_requests = 1024
      max_concurrent_requests = 1024
    }
    passive_health_check {
      interval = "10s"
      max_failures = 5
      enforcing_consecutive_5xx = 100
      max_ejection_percent = 20
      base_ejection_time = "30s"
    }
  }
}
EOF

git add service-defaults-billing-api.hcl
git commit -m "feat: add service defaults for billing-api"

# 2. Применение через CI/CD
consul config write service-defaults-billing-api.hcl

# 3. Валидация
consul config read -kind service-defaults -name billing-api

# 4. Мониторинг (проверка доставки xDS)
consul troubleshoot proxy -upstream-ip <ip>

# 5. Откат при проблемах
consul config delete -kind service-defaults -name billing-api
# или возврат к предыдущей версии из Git
git revert HEAD
consul config write service-defaults-billing-api.hcl
```

### Импорт/экспорт

```bash
# Экспорт всех config entries определенного типа (JSON)
consul config list -kind service-defaults -format=json | jq -r '.[]' | while read name; do
  consul config read -kind service-defaults -name "$name" -format=json >> config-backup.json
done

# Импорт
consul config write config-backup.json

# Enterprise: встроенный import/export
consul config export -kind service-defaults > service-defaults-backup.json
consul config import service-defaults-backup.json
```

### Валидация и dry-run

```bash
# Проверка синтаксиса перед записью
consul config validate service-defaults.hcl
# → Valid configuration

# Проверка с невалидным файлом
consul config validate invalid.hcl
# → 1 error occurred:
#   * invalid.kind: must be one of [service-defaults service-router ...]
```

## Валидация и мониторинг

### Команды валидации

| Команда | Назначение |
| :--- | :--- |
| `consul config validate <file>` | Проверка синтаксиса HCL/JSON |
| `consul config read -kind <kind> -name <name>` | Чтение примененной конфигурации |
| `consul config list -kind <kind>` | Список всех entries типа `<kind>` |
| `consul config list -kind <kind> -format=json` | Список в JSON |
| `consul config read -kind <kind> -name <name> -format=json` | Чтение в JSON |

### Мониторинг xDS

```bash
# Проверка NACK'ов (ошибки доставки)
curl -s localhost:8500/v1/agent/xds | jq '.streams[] | select(.nacks > 0)'
# → проверяйте ProxyID и причину ошибки

# Метрики Envoy (Prometheus)
envoy_cluster_upstream_cx_connect_fail          # ошибки подключения
envoy_cluster_upstream_rq_5xx                  # 5xx от апстрима
envoy_http_downstream_rq_xx                     # статус-коды downstream

# Health check конфигурации
consul health checks -service web-api
# → проверяйте статус sidecar-прокси
```

## Устранение неполадок

### Config entry не применяется

- **Диагностика:**
  ```bash
  consul config validate service-defaults.hcl
  # → Configuration invalid: <ошибка>

  consul config read -kind service-defaults -name billing-api
  # → проверьте, что запись существует
  ```
- **Решение:** Исправьте синтаксические ошибки. Проверьте, что ACL-токен имеет права на `service:write` или `operator:write` в зависимости от типа config entry.

### Изменения не доставляются до Envoy

- **Диагностика:**
  ```bash
  curl -s localhost:8500/v1/agent/xds | jq '.streams[] | select(.nacks > 0)'
  # → ищите ProxyID с ненулевым nacks

  consul troubleshoot proxy -upstream-ip <ip>
  # → проверяете rejected configurations
  ```
- **Решение:** Проверьте синтаксис config entries в discovery chain. Исправьте ошибку и повторно примените. При критичных ошибках Envoy может игнорировать обновление.

### L7 правила не работают

- **Причина:** В `service-defaults` не указан `Protocol = "http"` или `"grpc"`.
- **Диагностика:**
  ```bash
  consul config read -kind service-defaults -name web-api -format=json | jq '.Protocol'
  ```
- **Решение:** Добавьте protocol в service-defaults и дождитесь доставки xDS.

### Permission denied при config write

- **Диагностика:**
  ```bash
  consul config write service-defaults.hcl
  # → Permission denied
  ```
- **Решение:** Проверьте ACL-токен. Для `service-defaults`, `service-router`, `service-splitter`, `service-resolver`, `proxy-defaults` требуется `service:write`. Для `exported-services` требуется `mesh:write` или `operator:write`.

### xDS push медленный или завис

- **Диагностика:**
  ```bash
  consul monitor -log-level=debug
  # → ищите ошибки xDS push

  consul info | grep xds
  # → xds_streams = 45
  ```
- **Решение:** Проверьте нагрузку на серверы Consul. Увеличьте `limits.max_connections` в proxy-defaults или уменьшите количество прокси на одном сервере.

### Config entry конфликтует со статической конфигурацией

- **Причина:** У сервиса есть статические `-service` и `-connect` флаги, конфликтующие с config entries.
- **Решение:** Удалите статические флаги и перейдите на управление через config entries.

## Лучшие практики

- **GitOps:** Храните config entries в Git; применяйте через CI/CD pipeline.
- **Валидация:** Всегда запускайте `consul config validate` перед `consul config write`.
- **Stale mode для read:** Для `config read` и `config list` используйте `-stale` для снижения нагрузки на лидера.
- **JSON для скриптов:** Используйте `-format=json` и `jq` для автоматизации; HCL удобен для ручного редактирования.
- **Версионирование:** Используйте имена, включающие сервис и контекст: `service-defaults-billing-api.hcl`.
- **Разделение:** Разделяйте config entries по сервисам; избегайте монолитных конфигураций.
- **Тестирование:** Применяйте изменения в staging перед production.
- **Monitoring:** После каждого изменения проверяйте `envoy_cluster_upstream_cx_connect_fail` и xDS NACK'ы.
- **Namespace isolation:** Используйте namespaces/partitions для изоляции команд и сред.
- **Управление токенами:** Используйте `CONSUL_HTTP_TOKEN_FILE` вместо переменной окружения; предоставляйте минимальные права.
- **Rollback plan:** Всегда имейте готовый `git revert` и `consul config delete` для быстрого отката.
- **Размер entries:** Config entries должны быть небольшими и сфокусированными. Большие entries усложняют откат и аудит.

## Граничные случаи

- **Order of evaluation:** Router → Splitter → Resolver. Изменение порядка не поддерживается.
- **Multi-port сервисы:** Config entries привязываются к сервису, а не к порту. Для multi-port сервисов используйте intentions с указанием порта.
- **Namespace isolation:** Config entries изолированы в рамках namespace. Политика из одного namespace не видна в другом.
- **Implicit defaults:** При отсутствии `service-defaults` Consul использует TCP по умолчанию; L7-правила игнорируются.
- **xDS на лидере:** При потере лидерства xDS-стримы переподключаются к новому лидеру автоматически.
- **Размер config entry:** Ограничен размером Raft-лога (по умолчанию 512 КБ). Большие entries могут быть отклонены.
- **Enterprise-only:** `exported-services`, `api-gateway`, `mesh-gateway`, namespaces, partitions доступны только в Enterprise.
- **Peering:** `exported-services` требует настроенного peering. Wildcard `*` в namespace требует прав на чтение всех namespaces.
- **Envoy hot-reload:** Envoy применяет конфигурацию hot-reload, но некоторые изменения (например, `mode` в proxy-defaults) требуют перезапуска sidecar.
- **Transparent proxy:** При включенном transparent proxy не применяйте config entries к апстримам, которые должны bypass'ить mesh.
- **Конфликт с static config:** Config entries несовместимы со статическими флагами Envoy (`-service`, `-connect`). Используйте один подход.
- **Multi-DC:** Config entries реплицируются между дата-центрами только при настроенном WAN gossip. `-stale` на `config read` снижает задержку.

## Дополнительная информация

- **[Consul Config Entries](https://developer.hashicorp.com/consul/docs/fundamentals/config-entry)** — официальная документация.
- **[Service Defaults Reference](https://developer.hashicorp.com/consul/docs/reference/config-entry/service-defaults)** — справочник.
- **[Service Resolver Reference](https://developer.hashicorp.com/consul/docs/reference/config-entry/service-resolver)** — справочник.
- **[Proxy Defaults Reference](https://developer.hashicorp.com/consul/docs/reference/config-entry/proxy-defaults)** — справочник.
- **[Exported Services Reference](https://developer.hashicorp.com/consul/docs/reference/config-entry/exported-services)** — справочник.
- **[Consul Config Reference](https://developer.hashicorp.com/consul/docs/reference/config-entry)** — все типы config entries.
- **[Consul Service Mesh Configuration](./consul_service_mesh.md)** — общий обзор Service Mesh и config entries.
- **[Consul CLI Reference](./consul_cli_reference.md)** — команды CLI для управления config entries.
- **[Consul Disaster Recovery](./consul-disaster-recovery.md)** — восстановление config entries из снапшотов.
- **[Consul ACL Reference](./consul_acl.md)** — права для управления config entries.
- **[Consul Backup Verification](./consul_backup_verification.md)** — проверка резервных копий.
