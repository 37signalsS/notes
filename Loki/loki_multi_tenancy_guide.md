# Multi-tenancy в Grafana Loki

## Определения

**Tenant (Тенант)** — изолированная единица в Loki, определяющая набор логов и пользователей, имеющих доступ к ним. Каждый tenant имеет собственные limits, retention policies и RBAC. Multi-tenancy обеспечивает изоляцию данных между командами/проектами.

**X-Scope-OrgID** — HTTP header, определяющий tenant ID для запроса. Используется в Push API, Query API и Admin API. При `auth_enabled: true` все запросы должны содержать этот header.

**Per-tenant Limits (Лимиты на tenant)** — набор ограничений, применяемых к каждому tenant: ingestion rate, max streams, retention period, max query length. Позволяет контролировать ресурсы для разных tenants.

**Tenant Federation (Федерация tenant)** — возможность выполнять запросы跨越多个 tenants. Позволяет агрегировать данные из разных tenants в одном запросе. Требует специальных прав доступа.

**RBAC (Role-Based Access Control)** — система контроля доступа, определяющая кто может читать/писать логи для конкретного tenant. Управляется через Loki Ruler или внешние IdP.

**Pipeline Stages (Стадии pipeline)** — конфигурация обработки логов на агенте. В multi-tenant окружении pipeline может маршрутизировать логи разных tenants в разные destinations.

---

## Основные концепции

### Архитектура multi-tenancy в Loki

```
┌─────────────────────────────────────────────────────────────┐
│                     Kubernetes Cluster                        │
│                                                             │
│  ┌─────────────┐     ┌─────────────────────────────────┐   │
│  │  Tenant A   │────▶│       Loki Cluster              │   │
│  │  (team-a)   │     │  ┌─────────────────────────┐   │   │
│  └─────────────┘     │  │   Ingester (Tenant A)    │   │   │
│                      │  └─────────────────────────┘   │   │
│  ┌─────────────┐     │  ┌─────────────────────────┐   │   │
│  │  Tenant B   │────▶│  │   Ingester (Tenant B)    │   │   │
│  │  (team-b)   │     │  └─────────────────────────┘   │   │
│  └─────────────┘     │  ┌─────────────────────────┐   │   │
│                      │  │   Querier (All Tenants)   │   │   │
│  ┌─────────────┐     │  └─────────────────────────┘   │   │
│  │  Tenant C   │────▶│  ┌─────────────────────────┐   │   │
│  │  (team-c)   │     │  │   Compactor (All Tenants)│   │   │
│  └─────────────┘     │  └─────────────────────────┘   │   │
│                      └─────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Object Storage (S3/MinIO)               │   │
│  │  /tenant-a/chunks  /tenant-b/chunks  /tenant-c/chunks│   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Изоляция tenants

| Уровень | Описание | Метод |
| :--- | :--- | :--- |
| **Data isolation** | Логи разных tenants разделены | Label `X-Scope-OrgID` → path в S3 |
| **Resource isolation** | Лимиты ресурсов для каждого tenant | Per-tenant limits |
| **Query isolation** | Запросы не穿越 tenants | RBAC + X-Scope-OrgID |
| **Network isolation** | Разные network policies | Kubernetes NetworkPolicy |

### Per-tenant Limits

| Лимит | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `ingestion_rate_mb` | Максимальная скорость ingestion (MB/s) | Глобальное значение |
| `ingestion_burst_size_mb` | Burst size для ingestion | Глобальное значение |
| `max_query_length` | Максимальная длина LogQL запроса | 721h |
| `max_query_series` | Максимальное количество series | 5000 |
| `max_entries_limit_per_query` | Максимум логов на запрос | 10000 |
| `retention_period` | Период хранения данных | Глобальное значение |
| `per_stream_rate_limit` | Rate limit на stream | 5 MB/s |
| `per_stream_rate_limit_burst` | Burst limit на stream | 15 MB |

### Когда нужна multi-tenancy

| Сценарий | Multi-tenancy | Причина |
| :--- | :--- | :--- |
| Команда из 5 человек, один проект | Нет | Проще использовать один tenant |
| Компания с 10+ командами | Да | Изоляция данных и ресурсов |
| SaaS платформа с клиентами | Да | Каждый клиент — tenant |
| Разные окружения (dev/staging/prod) | Да | Разные limits и retention |
| Аудит-логи | Да | Долгое хранение, отдельные limits |
| Тестирование в production | Да | Изоляция тестовых данных |

---

## Практические сценарии

### Сценарий 1: Включение multi-tenancy (Simple Scalable)

```yaml
# loki.yaml
auth_enabled: true    # ← КЛЮЧЕВОЙ ПАРАМЕТР

server:
  http_listen_port: 3100

common:
  path_prefix: /loki
  storage:
    s3:
      endpoint: s3.amazonaws.com
      region: us-east-1
      bucketnames: loki-data
  replication_factor: 3
  ring:
    kvstore:
      store: memberlist

schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: s3
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  # Глобальные limits (действуют для всех tenants)
  ingestion_rate_mb: 16
  ingestion_burst_size_mb: 32
  max_query_length: 721h
  max_query_series: 5000
  retention_period: 30d

  # Per-tenant limits (переопределяют глобальные)
  per_tenant_overrides:
    team-a:
      ingestion_rate_mb: 32          # Больше ingestion для team-a
      max_query_length: 1440h        # Больше retention для team-a
      retention_period: 90d          # Дольше хранение для team-a
    team-b:
      ingestion_rate_mb: 8           # Меньше ingestion для team-b
      max_query_series: 3000         # Меньше series для team-b
    audit-logs:
      retention_period: 365d         # Год хранения для аудита
      ingestion_rate_mb: 4           # Малый ingestion для аудита
```

### Сценарий 2: Push API с X-Scope-OrgID

```bash
# Отправка логов для tenant-a
curl -X POST http://localhost:3100/loki/api/v1/push \
  -H "Content-Type: application/json" \
  -H "X-Scope-OrgID: team-a" \
  -d '{
    "streams": [
      {
        "stream": {
          "app": "nginx",
          "env": "prod"
        },
        "values": [
          ["'$(date +%s)000000000'", "2023-10-11T12:00:00Z ERROR Something went wrong"]
        ]
      }
    ]
  }'

# Отправка логов для tenant-b
curl -X POST http://localhost:3100/loki/api/v1/push \
  -H "Content-Type: application/json" \
  -H "X-Scope-OrgID: team-b" \
  -d '{
    "streams": [
      {
        "stream": {
          "app": "api-gateway",
          "env": "staging"
        },
        "values": [
          ["'$(date +%s)000000000'", "2023-10-11T12:00:00Z INFO Request processed"]
        ]
      }
    ]
  }'

# Запрос логов для tenant-a
curl -G http://localhost:3100/loki/api/v1/query_range \
  -H "X-Scope-OrgID: team-a" \
  --data-urlencode "query={app=\"nginx\"}" \
  --data-urlencode "start=$(date -v-1H +%s)000000000" \
  --data-urlencode "end=$(date +%s)000000000"

# Запрос логов для tenant-b
curl -G http://localhost:3100/loki/api/v1/query_range \
  -H "X-Scope-OrgID: team-b" \
  --data-urlencode "query={app=\"api-gateway\"}" \
  --data-urlencode "start=$(date -v-1H +%s)000000000" \
  --data-urlencode "end=$(date +%s)000000000"
```

### Сценарий 3: Alloy с tenant routing

```hcl
// Alloy config: маршрутизация по tenants

// Сбор логов из всех контейнеров
loki.source.kubernetes "containers" {
  targets    = discovery.kubernetes.pods.targets
  forward_to = [loki.process.route_by_tenant.receiver]
}

// Маршрутизация по tenants
loki.process "route_by_tenant" {
  forward_to = [loki.write.output.receiver]

  // Определение tenant по namespace
  stage.labels {
    values = {
      "X-Scope-OrgID" = "namespace"
    }
  }

  // Фильтрация по namespace → tenant mapping
  stage.match {
    selector = "{namespace=\"team-a\"}"
    stages = [
      stage.labels {
        values = {
          "X-Scope-OrgID" = "team-a"
        }
      },
    ]
  }

  stage.match {
    selector = "{namespace=\"team-b\"}"
    stages = [
      stage.labels {
        values = {
          "X-Scope-OrgID" = "team-b"
        }
      },
    ]
  }

  stage.match {
    selector = "{namespace=\"audit\"}"
    stages = [
      stage.labels {
        values = {
          "X-Scope-OrgID" = "audit-logs"
        }
      },
    ]
  }
}

// Запись в Loki
loki.write "output" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }

  // Добавление X-Scope-OrgID header
  external_labels = {
    "X-Scope-OrgID" = "{{ .Labels.X-Scope-OrgID }}"
  }
}
```

### Сценарий 4: Per-tenant retention policies

```yaml
# loki.yaml
limits_config:
  retention_period: 30d  # Глобальный retention

  per_tenant_overrides:
    # Team A: 90 дней retention
    team-a:
      retention_period: 90d

    # Team B: 7 дней retention (debug only)
    team-b:
      retention_period: 7d

    # Audit logs: 365 дней retention
    audit-logs:
      retention_period: 365d

    # Development: 3 дня retention
    dev:
      retention_period: 72h

compactor:
  working_directory: /loki/compactor
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 150
```

### Сценарий 5: Tenant federation (запрос跨越 tenants)

```bash
# Запрос跨越 несколько tenants
# В Loki 3.x: используйте multiple X-Scope-OrgID headers

curl -G http://localhost:3100/loki/api/v1/query_range \
  -H "X-Scope-OrgID: team-a|team-b" \
  --data-urlencode "query={app=\"nginx\"}" \
  --data-urlencode "start=$(date -v-1H +%s)000000000" \
  --data-urlencode "end=$(date +%s)000000000"

# Агрегация跨越 tenants
curl -G http://localhost:3100/loki/api/v1/query \
  -H "X-Scope-OrgID: team-a|team-b" \
  --data-urlencode "query=sum(count_over_time({app=\"nginx\"}[1h]))"
```

### Сценарий 6: Мониторинг multi-tenancy

**Ключевые метрики:**

| Метрика | Описание | Критическое значение |
| :--- | :--- | :--- |
| `loki_ingester_memory_streams` | Количество streams по tenants | Рост выше limits |
| `loki_push_requests_bytes_total` | Volume по tenants | Превышение ingestion_rate |
| `loki_request_duration_seconds` | Latency по tenants | P99 > 10s |
| `loki_ingester_samples_per_request` | Количество series на запрос | Превышение max_query_series |

**Прометеус-правила:**

```yaml
groups:
  - name: loki-multi-tenancy
    rules:
      - alert: LokiTenantIngestionRateExceeded
        expr: |
          sum(rate(loki_push_requests_bytes_total[5m])) by (X-Scope-OrgID)
          > on(X-Scope-OrgID)
          (sum(loki_ingester_memory_streams) by (X-Scope-OrgID) * 1024 * 1024)
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Tenant {{ $labels.X-Scope-OrgID }} exceeds ingestion rate"
          description: "Current rate: {{ $value | humanize1024 }}B/s"

      - alert: LokiTenantQueryLatencyHigh
        expr: |
          histogram_quantile(0.99, sum(rate(loki_request_duration_seconds_bucket[5m])) by (le, X-Scope-OrgID)) > 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Tenant {{ $labels.X-Scope-OrgID }} query latency is high"
          description: "P99 latency: {{ $value | humanizeDuration }}"
```

**Dashboard в Grafana:**

```logql
// Panel: Volume per Tenant (Time Series)
sum(rate(loki_push_requests_bytes_total[5m])) by (X-Scope-OrgID)

// Panel: Active Streams per Tenant (Gauge)
sum(loki_ingester_memory_streams) by (X-Scope-OrgID)

// Panel: Query Latency per Tenant (Heatmap)
histogram_quantile(0.99, sum(rate(loki_request_duration_seconds_bucket[5m])) by (le, X-Scope-OrgID))
```

---

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **401 Unauthorized** | Нет X-Scope-OrgID header | Добавьте `X-Scope-OrgID: tenant-id` в заголовки |
| **Tenant A видит данные Tenant B** | auth_enabled: false | Включите `auth_enabled: true` |
| **Tenant превышает ingestion rate** | Per-tenant limits не настроены | Установите `ingestion_rate_mb` в per_tenant_overrides |
| **Tenant не может запрашивать данные** | RBAC не настроен | Настройте Ruler или внешний IdP |
| **Compactor не удаляет старые данные** | retention_period не настроен | Установите retention_period для tenant |
| **Federation запросы не работают** | Loki версия < 3.0 | Обновите Loki до 3.x |
| **Высокая кардинальность для tenant** | Labels не оптимизированы | Удалите trace_id, span_id из labels |

---

## Дополнительная информация

### Лучшие практики

1. **Включайте auth_enabled: true** для production — изоляция tenants обязательна.
2. **Используйте descriptive tenant IDs:** `team-a`, `audit-logs`, `dev` — не `tenant-1`, `tenant-2`.
3. **Настройте per-tenant limits:** Разные teams имеют разные потребности в ingestion/query.
4. **Мониторьте per-tenant metrics:** Отдельные дашборды для каждого tenant.
5. **Используйте RBAC:** Не доверяйте X-Scope-OrgID — проверяйте через Ruler/IdP.
6. **Федерация только для admin:** Не позволяйте обычным tenant запрашивать данные跨越 tenants.
7. **Тестируйте multi-tenancy:** Сначала в dev/test, затем в production.
8. **Документируйте tenant policies:** Запишите limits, retention, RBAC для каждого tenant.

### См. также

- [Обзор Grafana Loki](./loki_overview.md) — архитектура и жизненный цикл данных
- [API Reference](./loki_api_reference.md) — Push/Query API с X-Scope-OrgID
- [Установка Loki в Kubernetes](./loki_stack_setup/loki_installation.md) — Helm-конфигурация
- [Compaction и Retention](./loki_compaction_retention.md) — per-tenant retention
- [Установка Alloy](./loki_stack_setup/alloy_installation.md) — конфигурация pipeline
