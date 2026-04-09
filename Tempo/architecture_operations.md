# Архитектура и операции Tempo

## Definitions

**Архитектура Tempo** — компоненты системы (Distributor, Ingester, Querier, Compactor, Query Frontend, Metric Generator), форматы хранения vParquet, режимы развёртывания (монолит/распределённый).

**Операции Tempo** — конфигурация хранилищ, breaking changes, рекомендации по эксплуатации.

Навигация: [Главная Tempo](./index.md). Компоненты описаны в [разделе архитектуры index.md](./index.md#архитектура).

---

## Basic Concepts

### Форматы хранения (vParquet)

Tempo использует собственный формат хранения на базе Apache Parquet. По умолчанию — vParquet4 (с Tempo 2.0). В Tempo 2.10 добавлен vParquet5.

| Версия | Tempo | Статус |
| :--- | :--- | :--- |
| v2 | <2.1 | Устаревший (удалён в Tempo 3.0) |
| vParquet3 | 2.1–2.5 | Устаревший (удалён в Tempo 3.0) |
| **vParquet4** | **≥2.0** | **Формат по умолчанию** (требуется для новых функций TraceQL) |
| **vParquet5** | **≥2.10** | **Добавлен в Tempo 2.10** |

> **Breaking Change:** Форматы v2 и vParquet3 удалены в Tempo 3.0. Для миграции требуется vParquet4+. Новые функции TraceQL (events, links) работают только с vParquet4+.

---

## Practical Scenarios

### Breaking changes (v2.6+)

| Изменение | Описание | Требуемое действие |
| :--- | :--- | :--- |
| **vParquet4 по умолчанию** | Формат хранения по умолчанию | Требуется Tempo ≥2.0 для чтения |
| **TraceQL Metrics** | Экспериментальная функция | Настройка `local-blocks` processor, `replication_factor: 1` |
| **tempo-query** | Отдельный сервер (не gRPC plugin) | Обновление конфигурации на `0.0.0.0:7777` |
| **Удалённые параметры** | `storage.azure.use_v2_sdk`, `autocomplete_filtering_enabled` | Проверка конфигурации |

### Конфигурация

#### Минимальная конфигурация (монолит)

```yaml
server:
  http_listen_port: 3200

distributor:
  receivers:
    otlp:
      protocols:
        http:
          endpoint: 0.0.0.0:4318
        grpc:
          endpoint: 0.0.0.0:4317

ingester:
  max_block_duration: 5m
  max_block_bytes: 1073741824

storage:
  trace:
    backend: local
    wal:
      path: /tmp/tempo/wal
    local:
      path: /tmp/tempo/blocks
```

#### Конфигурация для локального хранилища (production)

```yaml
storage:
  trace:
    backend: local
    local:
      path: /var/tempo/blocks
    wal:
      path: /var/tempo/wal
    pool:
      max_workers: 100
      queue_depth: 10000
```

#### Конфигурация для S3-совместимого хранилища (Yandex Object Storage / MinIO)

```yaml
storage:
  trace:
    backend: s3
    s3:
      bucket: tempo-traces
      endpoint: storage.yandexcloud.net
      region: ru-central1
      access_key: ${S3_ACCESS_KEY}
      secret_key: ${S3_SECRET_KEY}
      insecure: false
    wal:
      path: /var/tempo/wal
    pool:
      max_workers: 100
      queue_depth: 10000
```

### TraceQL Metrics configuration

```yaml
overrides:
  defaults:
    metrics_generator:
      processors: [local-blocks]
      storage_path: /var/tempo/metrics-generator
    tracing:
      enabled: true

metrics_generator:
  processor:
    local_blocks:
      flush_to_storage: true
```

### Интеграции и рекомендации

Интеграции с [Grafana](../Grafana/grafana_overview.md), [OpenTelemetry Collector](../OpenTelemetry/otlp_protocol.md), [Loki](../Loki/loki_overview.md) и рекомендации по эксплуатации описаны в [index.md](./index.md#интеграции).

---

## Additional Information

Документация: [официальная документация](https://grafana.com/docs/tempo/latest/), [формат vParquet](https://grafana.com/docs/tempo/latest/configuration/parquet/), [release notes v2.10](https://grafana.com/docs/tempo/latest/release-notes/v2-10/), [Tempo в Grafana Cloud](https://grafana.com/products/cloud/tempo/).
