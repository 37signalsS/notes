# Consul Telemetry

**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x / 1.20.x / 1.19.x

## Определения

**Consul Telemetry** — встроенная система сбора runtime-метрик и диагностических данных от компонентов Consul (серверы, клиенты, Connect/xDS). Данные экспортируются через `/v1/agent/metrics` endpoint или внешние sink'и (Prometheus, StatsD, DogStatsD, statsite, файл) и используются для мониторинга здоровья кластера, алертинга и capacity planning.

**Metrics Sink** — destination для telemetry данных. Consul поддерживает несколько sink'ов одновременно: Prometheus pull endpoint, StatsD/DogStatsD/statsite push, файловый sink.

**Prometheus Retention Time** — параметр `telemetry.prometheus_retention_time`, определяющий, как долго Consul агрегирует метрики в памяти для pull-эндпоинта. По умолчанию `0s` (отключено). Рекомендуемое значение — минимум 2x от интервала скрапинга Prometheus.

**Metric Prefix** — префикс, добавляемый ко всем именам метрик. По умолчанию `consul`. Может быть изменен через `telemetry.metrics_prefix`. Исторически существовал параметр `statsite_prefix` (до Consul 1.0).

**Metrics Filter** — механизм фильтрации метрик. `metrics_filter` — whitelist префиксов для Prometheus endpoint; `prefix_filter` — правила allow/deny для RPC метрик, применяемые к StatsD/statsite sink'ам.

**Telemetry Dump** — моментальный снимок всех текущих метрик в stderr, инициируемый сигналом `USR1` (Unix) или `BREAK` (Windows). Используется для ad-hoc диагностики без внешнего мониторинга.

**Host Metrics** — метрики системных ресурсов хоста (CPU, память, диск), отключаемые по умолчанию. Включаются через `telemetry.enable_host_metrics = true`. В контейнерах показывают ресурсы хоста, а не лимиты контейнера.

**Certificate Telemetry** — метрики экспирации и обновления TLS-сертификатов Consul (root CA, signing CA, agent TLS, leaf certificates). Включены по умолчанию. В Enterprise поддерживают `telemetry.certificate` блок с пороговыми значениями.

**Dataplane Telemetry** — метрики traffic'а Service Mesh (Envoy-level), экспортируемые через Envoy и собираемые Consul. В Enterprise поддерживается отдельный дашборд.

## Основные концепции

### Архитектура telemetry

```
┌─────────────────────────────────────────────────────────────┐
│                    Consul Cluster                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ Server 1 │  │ Server 2 │  │ Server 3 │  │ Client N │    │
│  │ Metrics  │  │ Metrics  │  │ Metrics  │  │ Metrics  │    │
│  │ (raft,   │  │ (raft,   │  │ (raft,   │  │ (agent,  │    │
│  │  serf)   │  │  serf)   │  │  serf)   │  │  health) │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
│       │             │             │             │           │
│       └─────────────┴─────────────┴─────────────┘           │
│                         │                                    │
│                         ▼                                    │
│              ┌──────────────────┐                            │
│              │ Telemetry Sink   │                            │
│              │ (Prometheus/     │                            │
│              │  StatsD/File)    │                            │
│              └──────────────────┘                            │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
               ┌──────────────────┐
               │ Monitoring Stack │
               │ (Prometheus/     │
               │  Grafana)        │
               └──────────────────┘
```

Каждый агент экспортирует метрики независимо. Метрики собираются в内存 агрегируются с интервалом `10s` для push-режима (StatsD, DogStatsD, statsite) и `60s` для Prometheus retention. Endpoint `/v1/agent/metrics` доступен постоянно и возвращает текущий снимок метрик в JSON или Prometheus формате.

### Типы метрик

Consul экспортирует метрики следующих типов:

| Тип | Описание |
| :--- | :--- |
| `gauge` | Текущее значение (например, количество active соединений) |
| `counter` | Монотонно возрастающее значение (например, количество запросов) |
| `summary` / `timer` | Распределение значений (latency histograms) |
| `sample` | Одно значение из распределения за интервал |

### Порядок сбора и экспорта

1. Агент собирает метрики каждые `10s` (или интервал flush внешнего sink'а).
2. Метрики хранятся в памяти в течение `prometheus_retention_time` (если включен Prometheus sink).
3. При запросе `/v1/agent/metrics` возвращается агрегированный snapshot.
4. При получении сигнала `USR1`/`BREAK` текущий snapshot записывается в stderr.
5. Для push-режима метрики отправляются на внешний sink через UDP (StatsD, DogStatsD) или TCP (statsite).

### Разрешение имен метрик

По умолчанию gauge-метрики префиксируются hostname'ом агента: `consul.<hostname>.server.isLeader`. Это упрощает агрегацию в распределенных средах, но усложняет группировку в Prometheus. Отключение префикса через `disable_hostname = true` рекомендуется для большинства production deployments.

## Практические сценарии

### 1. Конфигурация telemetry (Prometheus)

```hcl
telemetry {
  # Включение Prometheus endpoint
  prometheus_retention_time = "120s"

  # Отключение hostname префикса для упрощения агрегации
  disable_hostname = true

  # Префикс метрик (по умолчанию "consul")
  metrics_prefix = "consul"

  # Whitelist метрик для Prometheus endpoint
  metrics_filter = [
    "consul.raft.*",
    "consul.serf.*",
    "consul.xds.*",
    "consul.health.*",
    "consul.catalog.*",
    "consul.dns.*",
    "consul.runtime.*",
    "consul.autopilot.*",
    "consul.acl.*"
  ]

  # Включение host metrics (опционально)
  enable_host_metrics = true
}
```

### 2. Конфигурация telemetry (StatsD/Datadog)

```hcl
telemetry {
  prometheus_retention_time = "120s"

  statsd {
    address = "127.0.0.1:8125"
    prefix = "consul"
  }

  # ИЛИ DogStatsD с тегами
  dogstatsd_addr = "127.0.0.1:8125"
  dogstatsd_tags = [
    "env:production",
    "dc:dc1"
  ]
}
```

### 3. Конфигурация telemetry (statsite/TCP)

```hcl
telemetry {
  prometheus_retention_time = "120s"

  statsite {
    address = "127.0.0.1:8125"
    prefix = "consul"
  }
}
```

### 4. Целевой destination: файл

```hcl
telemetry {
  prometheus_retention_time = "120s"

  metric_sink {
    type = "file"
    format = "json"
    path = "/var/log/consul/metrics.json"
    rotate_duration = "24h"
    rotate_max_files = 7
  }
}
```

### 5. Prometheus scrape конфигурация

```yaml
scrape_configs:
  - job_name: "consul"
    static_configs:
      - targets:
        - "server-1:8500"
        - "server-2:8500"
        - "server-3:8500"
    metrics_path: "/v1/agent/metrics"
    params:
      format: ["prometheus"]
    scrape_interval: 60s
    scrape_timeout: 30s
```

> **Важно:** Consul не использует стандартный путь `/metrics`. Необходимо явно указать `metrics_path: "/v1/agent/metrics"` и передать `format: ["prometheus"]` как параметр (не в query string `?format=prometheus`, так как `?` будет экранирован).

### 6. Конфигурация certificate telemetry (Enterprise)

```hcl
telemetry {
  certificate {
    enabled = true
    cache_duration = "5m"
    critical_threshold_days = 7
    warning_threshold_days = 30
    info_threshold_days = 90
    exclude_auto_renewable = false
  }
}
```

### 7. Валидация

```bash
# Проверка доступности метрик в JSON формате
curl -s http://localhost:8500/v1/agent/metrics | jq '.Gauges[] | select(.Name | startswith("consul.raft"))'
# → {"Name":"consul.raft.leader","Value":1,"Labels":{}}

# Проверка Prometheus формата
curl -s "http://localhost:8500/v1/agent/metrics?format=prometheus" | grep consul_raft_leader
# → consul_raft_leader 1

# Проверка host metrics
curl -s http://localhost:8500/v1/agent/metrics | jq '.Gauges[] | select(.Name | startswith("consul.host"))'

# Проверка certificate metrics
curl -s http://localhost:8500/v1/agent/metrics | jq '.Gauges[] | select(.Name | startswith("consul.mesh.active"))'

# Dump метрик в stderr через сигнал
kill -USR1 $(pidof consul)
# Или через CLI (если доступен consul monitor)
consul monitor -log-level=info
```

## Ключевые метрики для Grafana дашбордов

### Global Mesh Health

```promql
# Статус агентов
consul_up

# Количество серверов в кворуме
consul_raft_peers

# Общий статус кластера
consul_autopilot_healthy
```

### Leadership and Stability

```promql
# Задержка контакта лидера (должна быть <200ms)
histogram_quantile(0.99, sum(rate(consul_raft_leader_lastContact_bucket[5m])) by (le))

# Частота выборов лидера
rate(consul_raft_state_candidate[5m])

# Текущий лидер
consul_server_isLeader == 1
```

### Raft Performance

```promql
# Время фиксации Raft (должно быть <100ms)
histogram_quantile(0.99, sum(rate(consul_raft_commitTime_bucket[5m])) by (le))

# Насыщение Raft goroutine'ов (должно быть <50%)
consul_raft_thread_main_saturation
consul_raft_thread_fsm_saturation

# Длительность восстановления FSM
consul_raft_fsm_lastRestoreDuration
```

### Transaction Timing

```promql
# Время применения KV операций
histogram_quantile(0.99, sum(rate(consul_kvs_apply_bucket[5m])) by (le))

# Время применения транзакций
histogram_quantile(0.99, sum(rate(consul_txn_apply_bucket[5m])) by (le))

# Количество Raft транзакций за интервал
rate(consul_raft_apply[5m])
```

### Network Activity (RPC)

```promql
# Общее количество RPC запросов от агентов
rate(consul_client_rpc[5m])

# Rate limited RPC (признак перегрузки или misconfiguration)
rate(consul_client_rpc_exceeded[5m])

# Failed RPC
rate(consul_client_rpc_failed[5m])
```

### Certificate Health (Enterprise)

```promql
# Время до экспирации root CA (критично: <7 дней)
consul_mesh_active_root_ca_expiry < (7 * 24 * 60 * 60)

# Время до экспирации signing CA
consul_mesh_active_signing_ca_expiry < (7 * 24 * 60 * 60)

# Статус обновления leaf certificates
consul_leaf_certs_cert_renewal_failure > 0

# Последовательные rate-limit ошибки при обновлении
consul_leaf_certs_consecutive_rate_limit_errors > 0
```

### Memory and Runtime

```promql
# Потребление памяти процессом (критично: >90% от доступной)
consul_runtime_sys_bytes

# Количество goroutines (индикатор нагрузки)
consul_runtime_num_goroutines

# Время GC pause (предупреждение: >2s/min, критично: >5s/min)
rate(consul_runtime_total_gc_pause_ns[1m])
```

### Host Metrics

```promql
# CPU idle (по каждому ядру)
consul_host_cpu_idle

# Доступная память
consul_host_memory_available

# Использование диска
consul_host_disk_used_percent

# Использование inodes
consul_host_disk_inodes_percent
```

### WAL Logstore (Consul 1.20+)

```promql
# Возраст последнего сегмента WAL (индикатор скорости записи)
consul_raft_wal_last_segment_age_seconds

# Частота ротации сегментов
rate(consul_raft_wal_segment_rotations[5m])

# Объем записанных данных
rate(consul_raft_wal_log_entry_bytes_written[5m])
```

### Connect Performance

```promql
# Активные gRPC стримы
consul_xds_server_streams

# Отклоненные конфигурации
rate(consul_xds_server_nacks[5m])
```

## Операции и команды

### Получение метрик

```bash
# JSON формат (полный snapshot)
curl -s http://localhost:8500/v1/agent/metrics | jq .

# Prometheus формат (для скрапинга)
curl -s "http://localhost:8500/v1/agent/metrics?format=prometheus"

# Фильтрация метрик через jq
curl -s http://localhost:8500/v1/agent/metrics | jq '.Gauges[] | select(.Name | startswith("consul.raft"))'
```

### Диагностический dump

```bash
# Отправка сигнала USR1 для записи метрик в stderr (Unix)
kill -USR1 $(pidof consul)

# Проверка stderr агента
journalctl -u consul -f | grep "G] 'consul\."

# Windows: отправка BREAK
# Приводит к записи метрик в stderr процесса
```

### Проверка certificate metrics

```bash
# Root CA expiry
curl -s http://localhost:8500/v1/agent/metrics | jq '.Gauges[] | select(.Name == "consul.mesh.active_root_ca.expiry")'

# Leaf certificate renewal failures
curl -s http://localhost:8500/v1/agent/metrics | jq '.Gauges[] | select(.Name | startswith("consul.leaf-certs"))'
```

### Проверка host metrics

```bash
# Доступные host metrics
curl -s http://localhost:8500/v1/agent/metrics | jq '.Gauges[] | select(.Name | startswith("consul.host"))'

# CPU utilization
curl -s http://localhost:8500/v1/agent/metrics | jq '.Gauges[] | select(.Name | startswith("consul.host.cpu"))'
```

## Устранение неполадок

### Метрики не появляются в Prometheus

- **Диагностика:**
  ```bash
  curl -s "http://localhost:8500/v1/agent/metrics?format=prometheus" | head -20
  ```
- **Решение:**
  - Проверьте, что `prometheus_retention_time > 0s` в конфигурации.
  - Убедитесь, что `metrics_path: "/v1/agent/metrics"` и `params.format: ["prometheus"]` в Prometheus scrape config.
  - Проверьте, что `disable_hostname = true` установлен для корректного отображения метрик.

### Высокий `consul_raft_leader_lastContact`

- **Причина:** Высокая задержка сети или дисковая подсистема.
- **Диагностика:**
  ```bash
  iostat -x 1 5
  # await должен быть <10ms
  ping -c 10 <follower-ip>
  # Задержка <10ms RTT
  ```
- **Решение:** Используйте NVMe/SSD, проверьте сетевую задержку между серверами (<10ms). Убедитесь, что нет packet loss.

### xDS NACKs растут

- **Причина:** Прокси Envoy отклоняют конфигурацию от Consul.
- **Диагностика:**
  ```bash
  curl localhost:8500/v1/agent/xds | jq '.streams[] | select(.nacks > 0)'
  ```
- **Решение:** Проверьте конфигурацию service-router/service-splitter на синтаксические ошибки. Проверьте logs envoy proxy.

### Certificate renewal failures

- **Причина:** Проблемы с CA, rate limiting, или ACL permissions.
- **Диагностика:**
  ```bash
  curl -s http://localhost:8500/v1/agent/metrics | jq '.Gauges[] | select(.Name | startswith("consul.leaf-certs"))'
  consul monitor | grep -i "certificate\|renewal"
  ```
- **Решение:** Проверьте `reason` label на метрике. Убедитесь, что CA доступна. Увеличьте `CSRMaxPerSecond` при необходимости. Проверьте ACL permissions для certificate signing.

### Метрики дублируются в Prometheus

- **Причина:** Несколько экземпляров Consul имеют одинаковый `metrics_prefix` без label'ов для идентификации.
- **Решение:** Добавьте внешние label'ы в Prometheus scrape config или используйте `metrics_prefix` с уникальными суффиксами per-node.

### Raft thread saturation > 50%

- **Причина:** Высокая write нагрузка или недостаточные ресурсы сервера.
- **Диагностика:**
  ```bash
  curl -s http://localhost:8500/v1/agent/metrics | jq '.Samples[] | select(.Name | startswith("consul.raft.thread"))'
  ```
- **Решение:** Проверьте `consul.raft.commitTime` и `consul.raft.fsm.lastRestoreDuration`. Убедитесь, что сервер имеет достаточные CPU/memory/disk IO. Рассмотрите увеличение количества серверов.

## Лучшие практики

- **Prometheus retention:** Устанавливайте `prometheus_retention_time = "120s"` или выше (минимум 2x от интервала скрапинга). Для долгосрочного хранения используйте 24h+.
- **Metrics filter:** Используйте `metrics_filter` для уменьшения объема данных и фокуса на критичных метриках. Исключите debug-метрики из production.
- **Hostname:** Отключайте `disable_hostname = true` для упрощения агрегации в Prometheus в production environments.
- **Host metrics:** Включайте `enable_host_metrics = true` на серверах для мониторинга системных ресурсов.
- **Мониторинг:** Настройте алерты на:
  - `consul_raft_leader_lastContact > 200ms`
  - `consul_raft_peers < expected_quorum`
  - `consul_autopilot_healthy == 0`
  - `consul_client_rpc_exceeded > 0`
  - `consul_leaf_certs_cert_renewal_failure > 0`
- **Дашборды:** Используйте официальный Grafana Dashboard ID 13396 как основу, адаптируя под ваши нужды.
- **Certificate monitoring:** Мониторьте `consul_mesh_active_root_ca_expiry` и `consul_agent_tls_cert_expiry` с порогами 7/30/90 дней.
- **Cardinality:** Избегайте high-cardinality метрик. Используйте `metrics_filter` для фильтрации per-service/per-check метрик без агрегации.
- **Scrape interval:** Устанавливайте интервал скрапинга Prometheus `>= 60s` для минимизации нагрузки на лидера.
- **Raft snapshot monitoring:** Мониторьте `consul_raft_leader_oldestLogAge` и `consul_raft_fsm_lastRestoreDuration` для предотвращения replication capacity issues.
- **Rate limiting telemetry:** Мониторьте `consul_client_rpc_exceeded` для раннего обнаружения rate limiting агентов.

## Граничные случаи

- **Large clusters (>5000 узлов):** Метрики могут создавать значительную нагрузку на лидера. Увеличьте `prometheus_retention_time` или используйте внешний StatsD sink. Убедитесь, что `metrics_filter` исключает нерелевантные метрики.
- **StatsD over UDP:** Потеря пакетов UDP может привести к пропускам метрик. Используйте TCP через statsite или мониторьте потери через `statsd.metrics_sent` vs `statsd.metrics_received`.
- **Multi-DC:** Метрики экспортируются на каждом сервере independently. Добавляйте label `datacenter` через `dogstatsd_tags` или external labels в Prometheus для корреляции.
- **High cardinality:** Per-service/per-check метрики могут вызывать explosion cardinality в Prometheus. Используйте `metrics_filter` для агрегации или перейдите на push-режим с агрегацией на стороне sink'а.
- **Контейнеризация:** `enable_host_metrics` показывает ресурсы хоста, а не контейнера. Для container-level метрик используйте cAdvisor или node_exporter.
- **Leader transition:** При смене лидера некоторые метрики (CA expiry, some raft metrics) могут временно показывать `NaN` или отсутствовать. Учитывайте это при настройке алертов.
- **Prometheus scrape timing:** Скрапинг с интервалом меньше `60s` может привести к нестабильным значениям из-за внутренней агрегации Consul. Минимальный рекомендуемый интервал — `60s`.
- **WAL/BoltDB metrics availability:** `consul.raft.wal.*` метрики требуют Consul 1.20+. `consul.raft.boltdb.*` метрики требуют Consul 1.11+. На старых версиях эти метрики отсутствуют.
- **Certificate metrics NaN:** Root и signing CA метрики могут показывать `NaN` на non-leader серверах или во время startup. Настройте алерты только на лидеров или используйте `max` aggregation across instances.

## Дополнительная информация

- **[Consul Telemetry](https://developer.hashicorp.com/consul/docs/monitor/telemetry/agent)** — официальная документация по agent telemetry.
- **[Consul Telemetry Reference](https://developer.hashicorp.com/consul/docs/reference/agent/telemetry)** — полный список метрик.
- **[Telemetry Configuration Reference](https://developer.hashicorp.com/consul/docs/reference/agent/configuration-file/telemetry)** — все параметры конфигурации.
- **[Monitor Certificate Expiration](https://developer.hashicorp.com/consul/docs/monitor/telemetry/certificate-expiration)** — сертификаты и ротация.
- **[Monitor Dataplane Telemetry](https://developer.hashicorp.com/consul/docs/monitor/telemetry/dataplane)** — traffic метрики Service Mesh (Enterprise).
- **[Consul Agent HTTP API - Metrics](https://developer.hashicorp.com/consul/api-docs/agent/metrics)** — REST API для получения метрик.
- **[Grafana Dashboard for Consul](https://grafana.com/grafana/dashboards/13396)** — официальный дашборд от HashiCorp.
- **[Consul Rate Limiting и Quotas](./consul_rate_limiting.md)** — rate limiting метрики и лимиты RPC.
- **[Consul Service Mesh](./consul_service_mesh.md)** — архитектура Service Mesh и dataplane metrics.
- **[Consul Network Segments](./consul_network_segments.md)** — Serf метрики для сегментов сети.
- **[Consul DNS Caching](./consul_dns_caching.md)** — DNS-метрики и кэширование.
- **[Consul Audit Logging](./consul_audit_logging.md)** — audit log метрики и диагностика.
- **[Prometheus Export Format](https://prometheus.io/docs/instrumenting/exporters/)** — специформата Prometheus exposition format.
