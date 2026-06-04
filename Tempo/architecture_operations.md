# Архитектура и операции Tempo

## Определения

**Tempo** — высокомасштабируемое распределённое хранилище трассировок. В данном файле рассматриваются технические аспекты архитектуры, режимы деплоя и эксплуатационные характеристики.

**Архитектура Tempo** — совокупность компонентов (Distributor, Ingester, Querier и др.), обеспечивающих прием, хранение и поиск трассировок в объектном хранилище.

**vParquet** — специализированный формат хранения Tempo на базе Apache Parquet, оптимизированный для TraceQL и эффективного сжатия данных трассировок.

Навигация: [Главная Tempo](./index.md).

---

## Основные концепции

### Архитектура и компоненты

Tempo построен на микросервисной архитектуре, аналогичной [Loki](../Loki/loki_overview.md) и [Mimir](../Mimir/mimir_overview.md).

| Компонент | Функции |
| :--- | :--- |
| **Distributor** | Принимает трассировки (OTLP, Jaeger, Zipkin), валидирует их и распределяет между Ingesters с помощью consistent hashing. |
| **Ingester** | Нарезает входящие трассировки на блоки (batches), буферизует их в оперативной памяти и записывает в долгосрочное хранилище (S3/GCS/Azure). |
| **Querier** | Отвечает за поиск трассировок по `trace_id` или выполнение запросов TraceQL. Запрашивает данные из Ingesters (свежие данные) и из объектного хранилища. |
| **Query Frontend** | Опциональный компонент для шардирования и кэширования запросов, обеспечивающий параллелизацию выполнения TraceQL. |
| **Compactor** | Фоновый процесс, который объединяет небольшие блоки в объектном хранилище в более крупные для оптимизации производительности чтения и стоимости хранения. |
| **Metric Generator** | Генерирует метрики (Service Graphs, Span Metrics) на основе проходящих трассировок и отправляет их в Prometheus/Mimir. |

### Режимы деплоя

1. **Монолит (Monolithic mode)** — все компоненты запускаются в одном процессе. Идеально для небольших инсталляций, тестирования или локальной разработки.
2. **Микросервисы (Microservices mode)** — каждый компонент запускается как отдельный сервис. Позволяет независимо масштабировать Ingesters (для записи) и Queriers (для чтения).

### Форматы хранения (vParquet)

Tempo использует собственный формат хранения на базе Apache Parquet. По умолчанию — vParquet4 (с Tempo 2.0).

| Версия | Tempo | Статус |
| :--- | :--- | :--- |
| v2 | <2.1 | Устаревший (удалён в Tempo 3.0) |
| vParquet3 | 2.1–2.5 | Устаревший (удалён в Tempo 3.0) |
| **vParquet4** | **≥2.0** | **Формат по умолчанию** (требуется для новых функций TraceQL) |
| **vParquet5** | **≥2.10** | **Добавлен в Tempo 2.10** |

> **Breaking Change:** Форматы v2 и vParquet3 удалены в Tempo 3.0. Для миграции требуется vParquet4+. Новые функции TraceQL (events, links) работают только с vParquet4+.

---

## Практические сценарии

### Breaking changes (v2.6+)

| Изменение | Описание | Требуемое действие |
| :--- | :--- | :--- |
| **vParquet4 по умолчанию** | Формат хранения по умолчанию | Требуется Tempo ≥2.0 для чтения |
| **TraceQL Metrics** | Экспериментальная функция | Настройка `local-blocks` processor, `replication_factor: 1` |
| **tempo-query** | Отдельный сервер (не gRPC plugin) | Обновление конфигурации на `0.0.0.0:7777` |
| **Удалённые параметры** | `storage.azure.use_v2_sdk`, `autocomplete_filtering_enabled` | Проверка конфигурации |

### Примеры конфигурации

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

### Конфигурация TraceQL Metrics

Для работы агрегаций и генерации метрик необходимо настроить `metrics_generator`:

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

---

## Дополнительная информация

### Рекомендации по эксплуатации

- **Retention:** Настраивается в секции `compactor`. По умолчанию данные хранятся вечно (если не настроены политики в облаке).
- **Object Storage:** Рекомендуется использовать облачные хранилища (S3, GCS) для обеспечения отказоустойчивости и неограниченного масштабирования.
- **Resource Limits:** Ingesters требуют значительного объема оперативной памяти для буферизации блоков перед записью.

### См. также

- [Официальная документация](https://grafana.com/docs/tempo/latest/)
- [Формат vParquet](https://grafana.com/docs/tempo/latest/configuration/parquet/)
- [Release notes v2.10](https://grafana.com/docs/tempo/latest/release-notes/v2-10/)
