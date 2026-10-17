# Производительность и тюнинг Vault

> **Актуально для:** Vault 2.x (latest 2.1.2; ветка 1.21.x поддерживается)

## Определения

**Performance Tuning** — процесс оптимизации конфигурации Vault для достижения максимальной производительности и минимальной задержки в production-среде.

**Throughput (Пропускная способность)** — количество запросов, которые Vault может обработать за единицу времени (обычно секунду). Для Raft-хранилища ограничена IOPS и сетевой latency.

**Latency (Задержка)** — время, которое требуется Vault для обработки запроса (от получения запроса до отправки ответа).

**Tail Latency** — максимальная задержка в распределении (p95, p99). Критична для SLA. Vault обслуживает запросы только на active-лидере (strong consistency); standby-узлы и Performance Standby снижают tail latency для read-only операций.

**IOPS (Input/Output Operations Per Second)** — количество операций ввода-вывода в секунду. Критично для Raft-хранилища.

**Raft Log Compaction** — процесс очистки и сжатия Raft-лога для предотвращения роста диска и поддержания производительности. Vault выполняет автоматическую compaction после создания snapshot.

**BoltDB Freelist Fragmentation** — при высокой частоте записей/удалений BoltDB freelist может фрагментироваться, увеличивая время транзакций. Мониторинг: `bbolt` page usage, `du -sh` рост файла.

**Write-Ahead Log (raft-wal)** — экспериментальная библиотека для Raft-логов, использующая директорию файлов вместо BoltDB. Меньше фрагментации при spiky writes.

**Cache Hit Ratio** — доля запросов, обслуженных из кэша. Высокий hit ratio снижает нагрузку на хранилище.

**Performance Standby (Enterprise)** — standby-узел, обслуживающий read-only запросы локально без перенаправления на лидера. Масштабирует read throughput.

**Stale Read** — режим чтения с standby-узла без специальных заголовков. Данные могут устаревать до 100 мс. Для read-after-write consistency на standby используйте `X-Vault-Forward: active-node` или `X-Vault-Inconsistent: forward-active-node` + `X-Vault-Index`.

**Connection Pooling** — механизм повторного использования соединений с backend для снижения overhead.

**Quorum** — большинство узлов в Raft-кластере. Для N узлов требуется ceil((N+1)/2). Потеря quorum = потеря доступности для записей.

**Advisory Lease Limit** — рекомендованный лимит ≈ 256 000 активных leases. Выше — деградация производительности из-за роста memory usage. Принудительное ограничение — lease count quotas ([Rate limit и lease quotas](./quotas.md)).

**max_request_size** — параметр listener (по умолчанию 32 MiB), ограничивающий размер HTTP-запросов.

## Архитектура и принцип работы

### Факторы, влияющие на производительность

1. **Хранилище:** SSD vs HDD, IOPS, latency. Vault bound by storage I/O.
2. **Сеть:** Задержка между узлами кластера (< 5ms для production), bandwidth.
3. **Конфигурация:** Размеры пулов, лимиты соединений, кэширование, TTL lease.
4. **Нагрузка:** Количество запросов, размер секретов, сложность политик.
5. **Узлы:** active/standby, Performance Standby (Enterprise), HA failover.

### Лимиты и максимумы

| Лимит | Значение | Комментарий |
| :--- | :--- | :--- |
| **max_request_size** | 32 MiB | [listener.stanza](https://developer.hashicorp.com/vault/docs/configuration/listener/tcp#max_request_size) |
| **max_request_duration** | 90s | [listener.stanza](https://developer.hashicorp.com/vault/docs/configuration/listener/tcp#max_request_duration) |
| **VAULT_CLIENT_TIMEOUT** | 60s | клиент-side timeout |
| **max_token_header_size** | 8 KB | [listener.tcp](https://developer.hashicorp.com/vault/docs/configuration/listener/tcp#max_token_header_size) |
| **Advisory lease limit** | 256 000 | [Limits and Maximums](https://developer.hashicorp.com/vault/docs/internals/limits#lease-limits) |
| **Default lease TTL** | 768 hours (32 дня) | [configuration](https://developer.hashicorp.com/vault/docs/configuration#lease_ttl_seconds) |
| **Max lease TTL** | 768 hours (32 дня) | [configuration](https://developer.hashicorp.com/vault/docs/configuration#max_lease_ttl_seconds) |
| **KV-v2 versions limit** | default 10; max 24 000+ | [KV secrets engine](https://developer.hashicorp.com/vault/docs/secrets/kv/kv-v2) |

### Quorum и fault tolerance для Raft

| Servers | Quorum size | Failure tolerance |
| :--- | :--- | :--- |
| 1 | 1 | 0 |
| 3 | 2 | 1 |
| 5 | 3 | 2 |
| 7 | 4 | 3 |

**Best practice:** минимум 5 узлов для production (failure tolerance ≥ 2).

### Параметры, влияющие на производительность

| Параметр | Описание | Влияние |
| :--- | :--- | :--- |
| `default_lease_ttl_seconds` | TTL lease по умолчанию | Короткий TTL ↓ нагрузка |
| `max_lease_ttl_seconds` | Максимальный TTL lease | Ограничивает backlog |
| `cache` | Размер и тип кэша | Hit ratio, latency |
| `listener` | TCP backlog, timeouts, max_request_size | обработка соединений |
| `storage` | Тип хранилища, max_entry_size, performance_multiplier | latency и throughput |
| `disable_mlock` | Отключить mlock (containers) | Избегает ENOMEM в контейнерах |
| `ui` | Включить GUI | не влияет на perf |

## Настройка и развертывание

### Prerequisites

- Vault 1.16+ (для `max_mount_and_namespace_table_entry_size`, `raft-wal`)
- SSD/NVMe для Raft-хранилища (минимум 10K IOPS для production)
- Сеть с latency < 5ms между узлами кластера
- File audit device с logrotate + выделенный том

### Сценарий 1: Оптимизация Raft-хранилища

#### Выбор хранилища

| Тип хранилища | IOPS | Latency | Рекомендация |
| :--- | :--- | :--- | :--- |
| **NVMe SSD** | 100K+ | < 1ms | Production |
| **SSD** | 50K–100K | 1–5ms | Production |
| **HDD** | 100–500 | 5–20ms | Dev/Test only |

#### Настройка systemd для оптимизации диска

```ini
# /etc/systemd/system/vault.service
[Unit]
Description="HashiCorp Vault"
Requires=network-online.target
After=network-online.target

[Service]
User=vault
Group=vault

# File descriptors — Vault может иметь тысячи соединений
LimitNOFILE=65536
LimitNPROC=65536

# mlock — предотвращает swap секретов
LimitMEMLOCK=infinity
AmbientCapabilities=CAP_IPC_LOCK

# I/O — приоритет для Vault disk I/O
IOSchedulingClass=realtime
IOSchedulingPriority=1
IOWeight=1000

# NUMA binding (single-socket серверы пропустите)
NUMAPolicy=preferred
NUMANode=0

# OOM — Vault не должен убиваться
OOMScoreAdjust=-1000

ExecStart=/usr/bin/vault server -config=/etc/vault.d/vault.hcl
ExecReload=/bin/kill -HUP $MAINPID
KillMode=process
KillSignal=SIGINT
TimeoutStopSec=90s

[Install]
WantedBy=multi-user.target
```

#### sysctl оптимизации

```bash
# /etc/sysctl.d/99-vault.conf
# Размер таблицы страниц
vm.max_map_count=262144
vm.swappiness=1

# Максимальное количество file descriptors
fs.file-max=10000000

# TCP оптимизации (Vault обслуживает тысячи соединений)
net.core.somaxconn=65535
net.core.netdev_max_backlog=5642
net.ipv4.tcp_max_syn_backlog=8192
net.ipv4.tcp_fin_timeout=30
net.ipv4.tcp_keepalive_time=600
net.ipv4.tcp_tw_reuse=1
net.ipv4.ip_local_port_range=1024 65535

# Применить
sudo sysctl -p /etc/sysctl.d/99-vault.conf
```

#### Vault HCL конфигурация хранилища

```hcl
# /etc/vault.d/vault.hcl
storage "raft" {
  path    = "/opt/vault/data"
  node_id = "vault-0"

  # Raft log truncation
  trailing_logs = 10000
  snapshot_interval = "30m"
  max_entry_size = "1MiB"

  # Autopilot для автоматической очистки dead nodes
  autopilot {
    cleanup_interval = "10m"
    last_contact_threshold = "10s"
    last_contact_failure_threshold = "30s"
    conflict_threshold = "1m"
  }
}

# Write-ahead Raft logs (experimental)
# storage "raft" {
#   path    = "/opt/vault/data"
#   node_id = "vault-0"
#   log_in_memory = false
# }
```

### Сценарий 2: Оптимизация конфигурации сервера

#### Оптимизация listener

```hcl
listener "tcp" {
  address       = "0.0.0.0:8200"
  cluster_address = "0.0.0.0:8201"

  # TLS
  tls_disable = 0
  tls_cert_file = "/etc/vault.d/tls/vault.crt"
  tls_key_file = "/etc/vault.d/tls/vault.key"
  tls_min_version = "tls12"
  tls_cipher_suites = "TLS_ECDHE_RSA_WITH_AEAD_TLS12_GCM_SHA256,TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384"

  # Timeouts
  http_read_timeout = "30s"
  http_write_timeout = "30s"
  http_idle_timeout = "5m"

  # Limits
  max_request_size = "33554432"  # 32 MiB (default)
  max_request_duration = "90s"   # 90s (default)
}
```

#### Оптимизация lease TTL

```hcl
# server.hcl
# Короткий TTL по умолчанию для снижения нагрузки на lease manager
default_lease_ttl_seconds = 3600   # 1 час (best practice)
max_lease_ttl_seconds     = 86400  # 24 часа

# Для high-write сред: ещё короче
# default_lease_ttl_seconds = 1800  # 30 минут
# max_lease_ttl_seconds     = 14400 # 4 часа
```

### Сценарий 3: Оптимизация кэширования

#### Настройка кэша на сервере

```hcl
# server.hcl
cache {
  use_auto_auth_token = true

  # Размер LRU кэша (количество записей)
  size = 16384

  # Persistent cache для Vault Agent (Enterprise)
  # На сервере cache.persist используется только в Agent
}

# Disable mlock в контейнерах (иначе ENOMEM)
disable_mlock = false  # true для containers

# Telemetry
telemetry {
  disable_hostname = false
  enable_hostname_as_label = true
  prometheus_enabled = true
  prometheus_retention_time = "96h"
  statsd_address = "127.0.0.1:8125"
  use_rst_flavor = true  # RST для UDP
}
```

#### Мониторинг hit ratio

```promql
# Hit ratio кэша
sum(rate(vault_cache_hit[5m])) / (sum(rate(vault_cache_hit[5m])) + sum(rate(vault_cache_miss[5m])))
```

#### Vault Agent с persistent cache (devops)

```hcl
# agent-config.hcl
auto_auth {
  method {
    type = "kubernetes"
    mount_path = "auth/kubernetes"
    config = {
      role = "vault-agent-role"
    }
  }
}

cache {
  use_auto_auth_token = true
  # Persistent cache на диск (Enterprise)
  persist "kubernetes" {
    path = "/var/lib/vault/agent-cache.db"
  }
}
```

### Сценарий 4: Оптимизация для high-load

#### Разделение компонентов (Load Balancer + Performance Standby)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│   Load      │────▶│   Vault     │
│             │     │   Balancer  │     │   Primary   │ (active, write)
└─────────────┘     └────┬───────┘     └──────┬──────┘
                         │                    │
                         ▼                    ▼
                    ┌─────────────┐     ┌─────────────┐
                    │   Vault     │     │   Vault     │
                    │   Standby   │────▶│  Perf.Standby│ (read cache)
                    │   (read)    │     │  (Enterprise)│
                    └─────────────┘     └─────────────┘
```

#### Настройка Load Balancer (nginx)

```nginx
# /etc/nginx/conf.d/vault-lb.conf
upstream vault_cluster {
    least_conn;
    server vault-0.example.com:8200 max_fails=3 fail_timeout=10s;
    server vault-1.example.com:8200 max_fails=3 fail_timeout=10s;
    server vault-2.example.com:8200 max_fails=3 fail_timeout=10s;
}

server {
    listen 8200;
    server_name vault.example.com;

    location / {
        proxy_pass https://vault_cluster;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Vault-Request true;

        # Keepalive (reuse connections)
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # Timeouts
        proxy_connect_timeout 5s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;

        # TLS к backend
        proxy_ssl_verify on;
        proxy_ssl_trusted_certificate /etc/nginx/ca.crt;
    }

    # Health check endpoint (не нагружает active node)
    location /v1/sys/health {
        proxy_pass https://vault_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        access_log off;
    }
}
```

### Сценарий 5: Бенчмаркинг и нагрузка

#### Бенчмарк запросов (hey)

```bash
# Установка hey (HTTP load generator)
go install github.com/rakyll/hey@latest

# Бенчмарк чтения секретов (KV v2)
hey -n 10000 -c 100 -m GET \
    -H "X-Vault-Token: $VAULT_TOKEN" \
    https://vault.example.com:8200/v1/secret/data/myapp/config

# Бенчмарк записи секретов
hey -n 1000 -c 10 -m POST \
    -H "X-Vault-Token: $VAULT_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"data": {"password": "test"}}' \
    https://vault.example.com:8200/v1/secret/data/myapp/config

# Бенчмарк с JWT auth
hey -n 5000 -c 50 -m POST \
    -H "Content-Type: application/json" \
    -d '{"role":"web-app","jwt":"<jwt-token>"}' \
    https://vault.example.com:8200/v1/auth/jwt/login
```

#### Интерпретация результатов

| Метрика | Хорошо | Плохо | Действие |
| :--- | :--- | :--- | :--- |
| **Requests/sec** | > 1000 | < 100 | Масштабировать узлы |
| **Latency p50** | < 10ms | > 100ms | Проверить кэш, сеть |
| **Latency p95** | < 50ms | > 500ms | Performance Standby |
| **Latency p99** | < 100ms | > 1000ms | Добавить standby-узлы |
| **Error rate** | < 0.1% | > 1% | Проверить audit device, disk |

#### Использование для анализа audit логов

```bash
# Медленные запросы (duration в audit записях)
jq 'select(.type=="response" and (.response.request_id as $id | [.request.duration, .request.path, $id]))' /var/log/vault/audit.log | \
  jq 'select(.request.duration > 100) | {path: .request.path, duration: .request.duration, time: .time}'
```

### Сценарий 6: Диагностика проблем производительности

#### Проверка Raft-лога

```bash
# Информация о Raft
vault operator raft info
# → Raft Log
# →   Last Log Index: 12345
# →   Last Log Term: 3
# →   Commit Index: 12340
# →   Applied Index: 12340

# Проверка размера Raft-лога (фрагментация BoltDB)
du -sh /opt/vault/data/raft/
# → Если резко вырос — возможна фрагментация
# → Решение: snapshot + restore для compaction
```

#### Raft log compaction (cleanup)

```bash
# Создание snapshot для compaction
vault operator raft snapshot save /opt/vault/backups/vault-compact.snap

# Автоматический cleanup (Autopilot)
vault operator raft autopilot status
# → cleanup_interval: "10m"

# Ручной compaction (если файл BoltDB сильно фрагментирован)
# 1. Создать snapshot
vault operator raft snapshot save /tmp/vault-before.snap
# 2. Восстановить на остановленном кластере (compaction)
# vault operator raft snapshot restore /tmp/vault-before.snap
```

#### Проверка метрик

```bash
# Метрики через Prometheus exporter
curl -s https://vault.example.com:8200/v1/sys/metrics?format=prometheus | grep vault_

# Ключевые метрики для диагностики
curl -s https://vault.example.com:8200/v1/sys/metrics | jq -r '.[] | select(.name | contains("vault_raft")) | .name'
# → vault.raft.commitTime
# → vault.raft.apply
# → vault.raft.replication
# → vault.raft.leader
# → vault.raft.state.leader
# → vault.raft.state.candidate
# → vault.raft.state.follower

# Аудит device metrics (узнать, если аудит логи задерживают)
curl -s https://vault.example.com:8200/v1/sys/metrics | jq -r '.[] | select(.name | contains("vault_audit")) | .name'
# → vault.audit.log_request_failure
# → vault.audit.log_response_failure
# → vault.audit.log_request
# → vault.audit.log_response
```

#### Анализ audit логов для проблем производительности

```bash
# Медленные запросы (> 100ms) из audit response записей
jq 'select(.type=="response") | select(.response.duration > 100)' /var/log/vault/audit.log

# Топ-10 самых медленных путей
jq -r 'select(.type=="response") | .request.path, .response.duration' /var/log/vault/audit.log | \
  paste - - | sort -t$'\t' -k2 -rn | head -10

# Запросы с ошибками
jq 'select(.type=="response" and .response.status_code >= 500)' /var/log/vault/audit.log

# Проверка audit device latency (если аудит задерживает ответы)
curl -s https://vault.example.com:8200/v1/sys/metrics | jq -r '.[] | select(.name == "vault.audit.log_request") | "Sum: \(.sum), Count: \(.count), Mean: \(.sum / .count)"'
```

#### Ротация audit логов

```bash
# logrotate для file audit device (см. audit_log_analysis.md для деталей)
# /etc/logrotate.d/vault-audit
/var/log/vault/audit.log {
    daily
    rotate 90
    compress
    delaycompress
    missingok
    notifempty
    create 0640 vault vault
    sharedscripts
    postrotate
        kill -HUP $(cat /var/run/vault.pid 2>/dev/null) 2>/dev/null || true
    endscript
}
```

## Операции и команды

### CLI команды для диагностики производительности

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `vault status` | Статус кластера (sealed, active, HA) | `vault status` |
| `vault operator raft info` | Информация о Raft (commit index, leader) | `vault operator raft info` |
| `vault operator raft list-peers` | Список узлов кластера | `vault operator raft list-peers` |
| `vault operator raft snapshot save` | Создание snapshot | `vault operator raft snapshot save backup.snap` |
| `vault operator raft snapshot restore` | Восстановление из snapshot | `vault operator raft snapshot restore backup.snap` |
| `vault operator raft snapshot inspect` | Проверка snapshot | `vault operator raft snapshot inspect backup.snap` |
| `vault operator raft autopilot status` | Статус Autopilot | `vault operator raft autopilot status` |
| `vault secrets tune` | Настройка TTL mount point | `vault secrets tune -max-lease-ttl=86400 secret/` |
| `vault auth tune` | Настройка TTL auth mount | `vault auth tune -default-lease-ttl=3600 userpass/` |

### API эндпоинты мониторинга

| Метод | Путь | Описание | auth |
| :--- | :--- | :--- | :--- |
| `GET` | `/sys/health` | Health check (unauth) | — |
| `GET` | `/sys/metrics` | Метрики в JSON | `root` |
| `GET` | `/sys/metrics?format=prometheus` | Prometheus metrics | `root` |
| `GET` | `/sys/stats` | Статистика по запросам | `root` |
| `GET` | `/sys/leader` | Информация о лидере | — |
| `GET` | `/sys/host-info` | Хост-информация | `root` |
| `GET` | `/sys/config/state` | Конфигурация state | `root` |
| `GET` | `/sys/raw/sys/audit/*` | Raw audit config (debug) | root |
| `GET` | `/sys/storage/raft/autopilot/configuration` | Autopilot config | `root` |

### Ключевые Prometheus метрики

| Метрика | Описание | Порог |
| :--- | :--- | :--- |
| `vault_raft_commit_time` | Время коммита записи в Raft (ms) | < 50ms (alert > 100ms) |
| `vault_raft_apply` | Время применения записи (ms) | < 10ms (alert > 50ms) |
| `vault_raft_replication` | Метрики репликации | — |
| `vault_core_leader` | Лидер (1) / follower (0) | 1 on active node |
| `vault_core_unsealed` | Распечатан (1) / запечатан (0) | 1 |
| `vault_cache_hit` / `vault_cache_miss` | Hit/miss кэша | hit ratio > 80% |
| `vault_runtime_lease_count` | Количество активных lease | < 256K (advisory) |
| `vault_request_count` | Общее число запросов | — |
| `vault_token_count_by_policy` | Токены по политикам | мониторинг роста |
| `vault.expire.num_leases` | Активные lease (alt) | < 256K |
| `vault_audit_log_request_failure` | Audit request failures | 0 |
| `vault_audit_log_response_failure` | Audit response failures | 0 |
| `vault_audit_sink_failure` | Audit device sink failures | 0 |

### AlertManager правила (Prometheus)

```yaml
groups:
- name: vault-performance
  rules:
  - alert: VaultUnsealed
    expr: vault_core_unsealed == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Vault sealed on {{ $labels.instance }}"

  - alert: VaultHighRaftCommitTime
    expr: histogram_quantile(0.95, sum(rate(vault_raft_commit_time_bucket[5m])) by (le)) > 100
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High Raft commit latency"

  - alert: VaultLowCacheHitRatio
    expr: sum(rate(vault_cache_hit[5m])) / (sum(rate(vault_cache_hit[5m])) + sum(rate(vault_cache_miss[5m]))) < 0.5
    for: 10m
    labels:
      severity: warning

  - alert: VaultHighLeaseCount
    expr: vault_expire_num_leases > 256000
    for: 5m
    labels:
      severity: warning

  - alert: VaultAuditLogFailure
    expr: rate(vault_audit_log_request_failure[5m]) > 0 or rate(vault_audit_log_response_failure[5m]) > 0
    for: 1m
    labels:
      severity: critical
```

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Error locking memory (mlock)** | Process не имеет CAP_IPC_LOCK или LimitMEMLOCK | `sudo setcap cap_ipc_lock=+eip /usr/bin/vault`, `LimitMEMLOCK=infinity` в systemd, либо `disable_mlock = true` в контейнере |
| **High commit latency** | Низкие IOPS диска, high сетевая latency, большой Raft-лог | SSD/NVMe (≥10K IOPS), < 5ms latency, настроить log compaction, snapshot |
| **BoltDB файл растёт** | Фрагментация freelist при высокой churn | Snapshot + restore для compaction; рассмотреть `raft-wal` (experimental) |
| **Disk full** | Audit логи, lease backlog, snapshot рост | Настроить logrotate для audit; short TTL leases; авто-снапшоты с cleanup |
| **Too many open files** | Недостаточно file descriptors | `LimitNOFILE=65536` в systemd, `fs.file-max=10000000` в sysctl |
| **OOMKilled** | Много leases в памяти | Short TTL lease; `default_lease_ttl_seconds=3600`; мониторинг `vault_runtime_lease_count` |
| **Request timeout (90s)** | Долгие операции (Transit/GPG), большой max_request_size | `max_request_duration=180s`; разбить операции; `VAULT_CLIENT_TIMEOUT=180s` |
| **Slow KV reads** | Отсутствие кэширования | Vault Agent с persistent cache; `cache.size=16384`; sticky sessions в LB |
| **Performance Standby не работает** | Enterprise-only; OSS standby не обслуживает чтения | Использовать OSS с sticky sessions к standby-узлу для stale reads (без специальных заголовков); см. [Производительность и репликация](./performance_and_replication.md#сценарий-2-stale-reads) |
| **Request size > 32MB** | `max_request_size` exceeded | `max_request_size = "67108864"` (64 MiB) в listener; или хранить большие секреты в external storage |
| **Token header > 8KB** | Большой токен (Enterprise authz claims) | `max_token_header_size = "16384"` в listener; или уменьшить claims |
| **Quorum lost (>50% nodes)** | Кластер недоступен для записей | Восстановить из snapshot; ручная правка peers.json; sequential scaling |
| **Stale reads inconsistent** | Lag > 100ms | Использовать strong consistency для критичных операций; уменьшить load на активном узле |
| **Audit device blocking requests** | Audit device недоступен | Минимум 2 audit device; logrotate для file; syslog fallback |
| **Lease count advisory limit** | > 256K lease | Short TTL; `vault write sys/leases/revoke-force-prefix`; cleanup expired lease |
| **High token churn** | Частое создание/удаление токенов | Token batch mode (`token_type=batch`); `orphan=true`; token reuse |

## Лучшие практики

1. **SSD/NVMe:** Используйте SSD или NVMe для Raft-хранилища. HDD непригодны для production. Минимум 10K IOPS.
2. **IOPS:** Обеспечьте достаточное количество IOPS (≥ 10K для production). [Recommended Patterns](https://developer.hashicorp.com/vault/docs/internals/recommended-patterns#increase-iops)
3. **Сеть:** Низколатентная сеть между узлами (< 5ms). Избегайте cross-AZ трафика.
4. **Кэширование:** Включите кэширование на сервере и используйте Vault Agent с persistent cache для read-heavy нагрузки.
5. **Load Balancer:** Настройте LB с `least_conn`, `keepalive` и health checks (`/v1/sys/health`).
6. **TTL leases:** Короткий TTL по умолчанию (`3600s`). [Recommended Patterns](https://developer.hashicorp.com/vault/docs/internals/recommended-patterns#adjust-the-default-lease-time)
7. **Audit rotation:** Регулярно ротатируйте audit логи. [Recommended Patterns](https://developer.hashicorp.com/vault/docs/internals/recommended-patterns#rotate-audit-device-logs)
8. **Мониторинг:** Отслеживайте `vault.raft.commitTime`, `vault.raft.apply`, `vault_audit_*_failure`, `vault.expire.num_leases`. [Monitoring Guide](./monitoring_and_alerting.md)
9. **Benchmark:** Регулярно проводите нагрузочное тестирование с `hey`.
10. **Cluster size:** Минимум 5 узлов для production (failure tolerance ≥ 2). [Integrated Storage](https://developer.hashicorp.com/vault/docs/internals/integrated-storage#quorum-size-and-failure-tolerance)
11. **Autopilot:** Оставляйте включённым для dead server cleanup и автоматического удаления.
12. **Token optimization:** Используйте `token_type=batch` для ephemeral токенов; избегайте root токенов в приложлениях.
13. **Snapshot strategy:** Авто-снапшоты каждые 2–6 часов с retention policy. [Vault API](https://developer.hashicorp.com/vault/api-docs/system/storage/raftautosnapshots)
14. **systemd tuning:** `LimitNOFILE=65536`, `LimitMEMLOCK=infinity`, `IOSchedulingPriority=1`, `OOMScoreAdjust=-1000`.
15. **Request limits:** При необходимости увеличьте `max_request_size` и `max_request_duration` в listener.

## Ограничения и известные проблемы

- **Write-through scaling:** Vault основной bottleneck на записи (≈ 100–500 записей/сек/узел) из-за Raft quorum. Read масштабируется через stale reads или Performance Standby.
- **BoltDB fragmentation:** При высокой churn freelist фрагментируется, файл растёт. Требуется manual compaction через snapshot restore. Используйте `raft-wal` для spiky writes.
- **Audit device overhead:** Каждая запись × 2 (request + response) = I/O нагрузка. Используйте выделенный том и logrotate. [Audit Log Analysis](./audit_log_analysis.md)
- **32MB request limit:** `max_request_size` по умолчанию 32 MiB. Увеличьте для больших секретов или используйте external storage.
- **90s operation timeout:** `max_request_duration` и `VAULT_CLIENT_TIMEOUT=60s`. Долгие операции (Transit) могут timeoutнутьь.
- **Stale read lag:** до 100ms. Не подходит для strong consistency операций.
- **Performance Standby Enterprise-only:** OSS standby не обслуживает чтения локально.
- **Lease advisory limit:** 256K lease в памяти. Выше — деградация. Short TTL + cleanup. [Limits](https://developer.hashicorp.com/vault/docs/internals/limits#lease-limits)
- **KV secret size:** ≤ 1 MiB (storage entry limit). Большие данные — external storage.
- **Cross-region latency:** Performance Replication асинхронна внутри региона, синхронна внутри cluster. High latency → slow commits.
- **Namespaces + mount limits:** ~7000 mounts (Consul), ~14000 (Raft) на namespace level. [Limits](https://developer.hashicorp.com/vault/docs/internals/limits#mount-point-limits)
- **Policy size:** ≤ 1 MiB (Consul) / 1 MiB (Raft). Large policy → slow ACL assembly. Мониторинг: `vault.core.fetch_acl_and_token`.

## Дополнительная информация

*   **[Производительность и репликация](./performance_and_replication.md)** — HA-кластер, Performance Standby, DR Replication.
*   **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — метрики, дашборды, SLO.
*   **[Анализ audit логов](./audit_log_analysis.md)** — log rotation, SIEM, forensic, audit telemetry.
*   **[Установка Vault](./vault_installation.md)** — hardware requirements, systemd hardening.
*   **[Обзор Vault](../overview.md)** — архитектура, HA.
*   **[Основные концепции Vault](../concepts.md)** — Raft, Seal/Unseal, Identity.
*   [Recommended patterns (Vault docs)](https://developer.hashicorp.com/vault/docs/internals/recommended-patterns)
*   [Limits and Maximums (Vault docs)](https://developer.hashicorp.com/vault/docs/internals/limits)
*   [Raft Integrated Storage (Vault docs)](https://developer.hashicorp.com/vault/docs/internals/integrated-storage)
*   [Telemetry (Vault docs)](https://developer.hashicorp.com/vault/docs/internals/telemetry)
*   [Performance tuning tutorial](https://developer.hashicorp.com/vault/tutorials/operations/performance-tuning)