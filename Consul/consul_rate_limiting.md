# Consul Rate Limiting и Quotas

**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x / 1.20.x / 1.19.x / 1.18.x

## Определения

**Consul Rate Limiting** — многоуровневая система защиты Consul от перегрузки RPC, gRPC и Service Mesh трафика. Включает server-side лимиты (OSS), cluster-wide глобальные лимиты (Enterprise), per-source IP лимиты (Enterprise) и L7 rate limiting в Service Mesh (Enterprise).

**Server Rate Limits** — статические лимиты, настроенные в конфигурации агента (`limits.rate_limit`). Применяются per-server, требуют перезапуска для изменения.

**Global Rate Limits** — динамические cluster-wide лимиты, настроенные через config entry `rate-limit` (Enterprise). Применяются ко всем серверам, поддерживают hot-reload.

**Control Plane Request Limits** — динамические лимиты для RPC/gRPC трафика от конкретных source IP, настроенные через config entry `control-plane-request-limit` (Enterprise). Поддерживают per-API гранулярность (KV, ACL, Catalog).

**Service Mesh Rate Limits** — L7 лимиты для traffic между сервисами, настроенные через `service-defaults` config entry (Enterprise). Включают instance-level token bucket и upstream connection limits.

**xDS Update Rate Limiting** — ограничение частоты push-обновлений конфигурации прокси через `xds.update_max_per_second`.

## Основные концепции

### Уровни защиты

Consul реализует rate limiting на четырех уровнях:

| Уровень | Механизм | Scope | Enterprise | Hot-reload |
| :--- | :--- | :--- | :--- | :--- |
| **Server config** | `limits.rate_limit` в agent config | per-server | Нет | Нет (restart) |
| **Global config entry** | `rate-limit` config entry | cluster-wide | Да | Да |
| **Control plane / Source IP** | `control-plane-request-limit` config entry | per-IP, per-API | Да | Да |
| **Service Mesh** | `service-defaults` RateLimits / UpstreamConfig | per-service | Да | Да |
| **xDS server** | `xds.update_max_per_second` | per-server | Нет | Да |

### Порядок применения лимитов

Consul применяет лимиты в следующем порядке приоритета:

1. **Global config entry** (`rate-limit`) с `priority=true` — высший приоритет.
2. **Server config** (`limits.rate_limit`) — применяется, если global entry не настроен или `priority=false`.
3. **IP limiter (global)** — per-IP read/write лимиты из `control-plane-request-limit`.
4. **IP limiter (category)** — per-IP лимиты для KV, ACL, Catalog.

> **Важно:** Установка `limits.request_limits.mode = "disabled"` в agent config отключает ВСЕ лимиты, включая config entries.

### Server Rate Limits (OSS/Enterprise)

Настраиваются в конфигурации серверного агента:

```hcl
# /etc/consul.d/server.hcl
limits {
  rate_limit {
    mode = "permissive"  # permissive | enforcing | disabled
    read_rate = 500.0
    write_rate = 200.0
  }

  # Дополнительные лимиты соединений (OSS/Enterprise)
  rpc_max_conns_per_client = 100
  http_max_conns_per_client = 200
}
```

```json
{
  "limits": {
    "rate_limit": {
      "mode": "enforcing",
      "read_rate": 500,
      "write_rate": 200
    },
    "rpc_max_conns_per_client": 100,
    "http_max_conns_per_client": 200
  }
}
```

- **`mode`**: `permissive` — логирует превышение, но не блокирует; `enforcing` — блокирует запросы; `disabled` — отключает все лимиты.
- Применяются к HTTP API, CLI и gRPC endpoint.
- Требуют перезапуска агента. Для применения без перезапуска используйте `consul reload` только если лимит настроен через config entry.

### Global Rate Limits (Enterprise)

Настраиваются через config entry `rate-limit`. Применяются cluster-wide, поддерживают hot-reload.

```hcl
# rate-limit.hcl
apiVersion = "consul.hashicorp.com/v1alpha1"
kind = "RateLimit"
metadata = {
  name = "global"
}
spec = {
  config = {
    readRate = 300
    writeRate = 200
    priority = true
    excludeEndpoints = [
      "Health.ServiceChecks",
      "Status.Leader",
      "Status.Ping"
    ]
  }
}
```

```json
{
  "Kind": "rate-limit",
  "Name": "global",
  "Config": {
    "readRate": 300,
    "writeRate": 200,
    "priority": true,
    "excludeEndpoints": [
      "Health.ServiceChecks",
      "Status.Leader",
      "Status.Ping"
    ]
  }
}
```

```bash
# Применение на VM
consul config write rate-limit.hcl
# → Config entry written

# Проверка
consul config read -kind rate-limit -name global
```

**Параметры:**

- **`readRate`** (default: `100`) — максимальное количество read RPC в секунду на сервер.
- **`writeRate`** (default: `100`) — максимальное количество write RPC в секунду на сервер.
- **`priority`** (default: `true`) — если `true`, global config entry имеет высший приоритет над server config.
- **`excludeEndpoints`** — список RPC методов, исключаемых из лимитирования. Полный список методов: `GET /v1/internal/rpc/methods`.

**Exempted endpoints по умолчанию:**
`Operator.AutopilotGetConfiguration`, `Operator.AutopilotSetConfiguration`, `Operator.AutopilotState`, `Operator.RaftGetConfiguration`, `Operator.RaftRemovePeerByAddress`, `Operator.RaftRemovePeerByID`, `Operator.ServerHealth`, `Status.Leader`, `Status.Peers`, `Status.Ping`, `Status.RaftStats`, `ConfigEntry.Apply`, `ConfigEntry.Delete`.

### Control Plane Request Limits / Source IP Rate Limits (Enterprise)

Настраиваются через config entry `control-plane-request-limit`. Применяются per-source IP с per-API гранулярностью.

```hcl
# control-plane-request-limit.hcl
apiVersion = "consul.hashicorp.com/v1alpha1"
kind = "ControlPlaneRequestLimit"
metadata = {
  name = "global-source-limits"
}
spec = {
  mode = "permissive"  # permissive | enforcing | disabled
  readRate = 500
  writeRate = 200

  # Per-API лимиты
  kv = {
    readRate = 1000
    writeRate = 100
  }
  acl = {
    readRate = 200
    writeRate = 50
  }
  catalog = {
    readRate = 800
    writeRate = 100
  }
}
```

```json
{
  "Kind": "control-plane-request-limit",
  "Name": "global-source-limits",
  "Mode": "permissive",
  "ReadRate": 500,
  "WriteRate": 200,
  "KV": {
    "ReadRate": 1000,
    "WriteRate": 100
  },
  "ACL": {
    "ReadRate": 200,
    "WriteRate": 50
  },
  "Catalog": {
    "ReadRate": 800,
    "WriteRate": 100
  }
}
```

**Важно:** Config entry записывается в `default` partition, но применяется ко всем client requests ко всем partitions.

### Service Mesh Rate Limits (Enterprise)

#### Instance-level rate limiting

`service-defaults` config entry поддерживает `RateLimits.InstanceLevel` — token bucket algorithm per service instance:

```hcl
# service-defaults-api.hcl
apiVersion = "consul.hashicorp.com/v1alpha1"
kind = "ServiceDefaults"
metadata = {
  name = "public-api"
}
spec = {
  rateLimits = {
    instanceLevel = {
      requestsPerSecond = 100
      requestsMaxBurst = 200

      routes = [
        {
          pathPrefix = "/api/v1"
          requestsPerSecond = 50
          requestsMaxBurst = 100
        },
        {
          pathExact = "/api/v1/health"
          requestsPerSecond = 200
          requestsMaxBurst = 50
        }
      ]
    }
  }
}
```

```json
{
  "Kind": "ServiceDefaults",
  "Name": "public-api",
  "RateLimits": {
    "InstanceLevel": {
      "RequestsPerSecond": 100,
      "RequestsMaxBurst": 200,
      "Routes": [
        {
          "PathPrefix": "/api/v1",
          "RequestsPerSecond": 50,
          "RequestsMaxBurst": 100
        },
        {
          "PathExact": "/api/v1/health",
          "RequestsPerSecond": 200,
          "RequestsMaxBurst": 50
        }
      ]
    }
  }
}
```

**Параметры:**
- **`requestsPerSecond`** — среднее количество запросов в секунду (refill rate токенового ведра).
- **`requestsMaxBurst`** — максимальный пиковый burst; должно быть >= `requestsPerSecond`.
- **`routes`** — список правил маршрутизации; в каждом элементе должен быть один из `pathExact`, `pathPrefix`, `pathRegex` плюс `requestsPerSecond`.

#### Upstream connection limits

`service-defaults` также содержит `upstreamConfig.defaults.limits` — лимиты соединений на upstream:

```hcl
upstream_config {
  defaults {
    limits {
      max_connections        = 0   # 0 = unlimited
      max_pending_requests   = 0
      max_concurrent_requests = 0
    }
  }
}
```

> **Примечание:** Подробное описание `upstream_config` с пассивными health checks приведено в [Consul Config Entries Lifecycle](./consul_config_entries_lifecycle.md).

### xDS Update Rate Limiting

`xds.update_max_per_second` ограничивает количество конфигурационных push-обновлений ко всем подключенным xDS streams:

```hcl
# /etc/consul.d/server.hcl
xds {
  update_max_per_second = 250  # default: 250
}
```

- **Default:** `250` updates/sec (на базе теста 5000 streams, 2 CPU cores).
- Hot-reloadable через `consul reload` или `SIGHUP`.
- Защищает Raft и Gossip от starvation при массовых изменениях config entries (wildcard intentions и т.д.).

## Практические сценарии

### 1. Server rate limits (OSS)

```hcl
# /etc/consul.d/server.hcl
limits {
  rate_limit {
    mode = "permissive"
    read_rate = 1000.0
    write_rate = 500.0
  }
  rpc_max_conns_per_client = 200
  http_max_conns_per_client = 200
}
```

```bash
# Проверка конфигурации
consul validate /etc/consul.d/server.hcl
# → Configuration valid

# Применение (требуется restart)
systemctl restart consul
# Или hot-reload для поддерживаемых параметров
consul reload
```

### 2. Global rate limits (Enterprise)

```hcl
# rate-limit.hcl
apiVersion = "consul.hashicorp.com/v1alpha1"
kind = "RateLimit"
metadata = { name = "global" }
spec = {
  config = {
    readRate = 500
    writeRate = 250
    priority = true
    excludeEndpoints = [
      "Health.ServiceChecks",
      "Status.Leader",
      "Status.Ping",
      "Status.RaftStats"
    ]
  }
}
```

```bash
# Применение
consul config write rate-limit.hcl
# → Config entry written

# Проверка
consul config read -kind rate-limit -name global
# Валидация
consul config validate rate-limit.hcl
```

### 3. Source IP rate limits (Enterprise)

```hcl
# control-plane-request-limit.hcl
apiVersion = "consul.hashicorp.com/v1alpha1"
kind = "ControlPlaneRequestLimit"
metadata = { name = "source-ip-limits" }
spec = {
  mode = "enforcing"
  readRate = 300
  writeRate = 100
  kv = {
    readRate = 500
    writeRate = 50
  }
  acl = {
    readRate = 100
    writeRate = 25
  }
  catalog = {
    readRate = 400
    writeRate = 50
  }
}
```

```bash
consul config write control-plane-request-limit.hcl
# → Config entry written
```

### 4. Service Mesh rate limiting (Enterprise)

```hcl
# service-defaults-api.hcl
apiVersion = "consul.hashicorp.com/v1alpha1"
kind = "ServiceDefaults"
metadata = { name = "public-api" }
spec = {
  rateLimits = {
    instanceLevel = {
      requestsPerSecond = 100
      requestsMaxBurst = 200
      routes = [
        {
          pathPrefix = "/api/v1"
          requestsPerSecond = 50
          requestsMaxBurst = 100
        }
      ]
    }
  }
  upstreamConfig = {
    defaults = {
      limits = {
        max_connections = 1024
        max_pending_requests = 1024
        max_concurrent_requests = 1024
      }
    }
  }
}
```

```bash
consul config write service-defaults-api.hcl
# → Config entry written
```

### 5. Nginx reverse proxy rate limiting

```nginx
# /etc/nginx/conf.d/consul-api.conf
limit_req_zone $binary_remote_addr zone=consul_api:10m rate=100r/s;

server {
  listen 8501 ssl;
  server_name consul.example.com;

  location /v1/ {
    limit_req zone=consul_api burst=50 nodelay;
    proxy_pass http://127.0.0.1:8500/v1/;

    proxy_ssl_verify on;
    proxy_ssl_verify_depth 2;
    proxy_ssl_trusted_certificate /etc/nginx/ssl/ca.crt;
  }
}
```

### 6. iptables rate limiting

```bash
# Ограничение: 100 новых соединений/сек на порт 8501
iptables -A INPUT -p tcp --dport 8501 -m conntrack --ctstate NEW \
  -m limit --limit 100/s --limit-burst 200 -j ACCEPT
iptables -A INPUT -p tcp --dport 8501 -j DROP
```

## Валидация

```bash
# Валидация config entries
consul config validate rate-limit.hcl
consul config validate control-plane-request-limit.hcl
consul config validate service-defaults-api.hcl

# Проверка active rate limit config
consul config read -kind rate-limit -name global
consul config read -kind control-plane-request-limit -name global-source-limits
consul config read -kind service-defaults -name public-api

# Проверка xDS config
consul info | grep xds
# → xds_update_max_per_second = 250

# Проверка metrics
curl -s http://127.0.0.1:8500/v1/agent/metrics | \
  jq '.Counters[] | select(.Name | contains("rate_limit"))'
```

## Устранение неполадок

### 429 Resource Exhausted

- **Диагностика:** Запрос отклонен сервером. Может быть retry на другом сервере.
  ```bash
  curl -v http://127.0.0.1:8500/v1/catalog/services
  # → HTTP/1.1 429 Resource Exhausted
  ```
- **Решение:** Увеличьте `read_rate`/`write_rate` в server config или global config entry. Для stale reads 429 означает, что другой сервер может выполнить запрос — клиент автоматически retry.

### 503 Service Unavailable

- **Диагностика:** Сервер перегружен, нет доступных серверов для fulfillment (обычно consistent reads или writes).
- **Решение:** Примените exponential backoff. Проверьте метрики `consul.rpc.rate_limit.exceeded` с label `limit_type=global/read` или `global/write`.

### Логи rate limit превышений

```bash
# Поиск в логах
journalctl -u consul -f | grep "rpc-rate-limit"
# → 2023-02-17T10:01:15.565-0500 [DEBUG] agent.server.rpc-rate-limit: RPC exceeded allowed rate limit: rpc=KVS.Apply source_addr=10.0.0.5:53562 limit_type=global/write limit_enforced=false
```

- **`limit_enforced=false`** — режим permissive, запрос выполнен.
- **`limit_enforced=true`** — режим enforcing, запрос отклонен.

### Высокий `xds.update_max_per_second`

- **Диагностика:** NACK ошибки от Envoy proxies.
  ```bash
  consul info | grep xds
  # → xds_nacks = 45
  ```
- **Решение:** Увеличьте `update_max_per_second` (default 250) или оптимизируйте частоту изменений config entries.

### Global config entry не применяется

- **Причина:** `priority=false` или server config задает более строгие лимиты.
- **Решение:** Убедитесь, что `priority=true` в `rate-limit` config entry. Проверьте precedence.

### Source IP лимит блокирует легитимный трафик

- **Диагностика:** Метрики `consul.rpc.rate_limit.exceeded` с label `limit_type=source/read` или `source/write`.
- **Решение:** Перейдите в `permissive` mode для сбора данных, затем скорректируйте лимиты.

## Лучшие практики

- **Server config:** Используйте как fallback; начинайте с permissive mode для сбора baseline метрик.
- **Global config entry:** Настраивайте для emergency throttling; всегда указывайте `excludeEndpoints` для критичных health checks.
- **Source IP limits:** Используйте permissive mode при инициализации; переходите в enforcing после анализа трафика.
- **Service Mesh rate limits:** Начинайте с `RateLimits.InstanceLevel` для API gateway сервисов; комбинируйте с `upstreamConfig.defaults.limits` для circuit breaking.
- **xDS update limits:** Default 250 достаточен для большинства кластеров; увеличивайте только при NACK ошибках.
- **Мониторинг:** Настройте алерты на `consul.rpc.rate_limit.exceeded > 0` и `consul.rpc.rate_limit.log_dropped > 0`.
- **Nginx:** Используйте `burst` для absorption пиков; настройте `proxy_ssl_verify` для защиты MITM.
- **Reload:** Используйте `consul reload` для hot-reload global config entries; избегайте restart для изменения глобальных лимитов.

## Граничные случаи

- **Multi-DC:** Global rate limits и source IP limits применяются per-datacenter. Настраивайте отдельно для каждого DC.
- **Multi-Partition:** `control-plane-request-limit` записывается в `default` partition, но применяется ко всем partitions. `rate-limit` config entry также cluster-wide.
- **Kubernetes:** Используйте Helm values `limits.request_limits` для server config; CRD `RateLimit` и `ControlPlaneRequestLimit` для Enterprise config entries. Требуется `globalConfigACLToken` secret для `RateLimit` CRD при включенных ACL.
- **Mode precedence:** `disabled` в agent config отключает все лимиты, включая Enterprise config entries. Используйте с осторожностью.
- **Priority=false:** Если `priority=false` в `rate-limit` config entry, применяются server config лимиты вместо global.
- **xDS без restart:** `update_max_per_second` поддерживает hot-reload через `consul reload` или `SIGHUP`.
- **Server rate limits и client agents:** Server rate limits применяются ко всем клиентам, включая client agents и proxies.
- **Stale reads:** При 429 на stale read Consul client автоматически retry на другом сервере.
- **Large clusters (>5000 узлов):** Начинайте с server config permissive mode, затем переходите на global config entry для централизованного управления.
- **Enterprise vs OSS:** Server rate limits и xDS rate limiting доступны в OSS. Global rate limits, source IP limits и Service Mesh rate limits требуют Enterprise.

## Дополнительная информация

- **[Consul Agent Traffic Rate Limiting](https://developer.hashicorp.com/consul/docs/manage/rate-limit)** — обзор уровней rate limiting.
- **[Set Server Traffic Rate Limits](https://developer.hashicorp.com/consul/docs/manage/rate-limit/server-limits/server)** — конфигурация server-side лимитов.
- **[Set Global Traffic Rate Limits](https://developer.hashicorp.com/consul/docs/manage/rate-limit/global)** — глобальные лимиты (Enterprise).
- **[Limit Traffic Rates from Source IP](https://developer.hashicorp.com/consul/docs/manage/rate-limit/source)** — per-IP лимиты (Enterprise).
- **[Monitor Traffic Rate Limits](https://developer.hashicorp.com/consul/docs/manage/rate-limit/server-limits/monitor)** — метрики и логи.
- **[Initialize Rate Limit Settings](https://developer.hashicorp.com/consul/docs/manage/rate-limit/server-limits/initialize)** — методология определения базовых значений.
- **[Rate Limit Config Entry](https://developer.hashicorp.com/consul/docs/reference/config-entry/rate-limit)** — глобальный rate-limit config entry (Enterprise).
- **[Control Plane Request Limit Config Entry](https://developer.hashicorp.com/consul/docs/reference/config-entry/control-plane-request-limit)** — per-IP лимиты (Enterprise).
- **[Service Defaults Config Entry — RateLimits](https://developer.hashicorp.com/consul/docs/reference/config-entry/service-defaults#ratelimits)** — Service Mesh rate limiting (Enterprise).
- **[xDS Configuration Parameters](https://developer.hashicorp.com/consul/docs/reference/agent/configuration-file/xds)** — `update_max_per_second`.
- **[Consul Config Entries Lifecycle](./consul_config_entries_lifecycle.md)** — управление конфигурацией как кодом, `upstream_config` limits.
- **[Consul Service Mesh](./consul_service_mesh.md)** — архитектура Service Mesh.
- **[Consul Telemetry](./consul_telemetry.md)** — метрики и дашборды.
- **[Nginx Rate Limiting](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html)** — модуль `limit_req`.
- **[Envoy Rate Limit Filter](https://www.envoyproxy.io/docs/envoy/latest/configuration/listeners/filters/network_filters/rate_limit_filter)** — документация Envoy.
