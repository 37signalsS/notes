# Архитектура и операции Tempo

## Определения

**Архитектура Tempo** — компоненты системы: Distributor, Ingester, Querier, Compactor, Metric Generator.

**Операции Tempo** — конфигурация, интеграции, рекомендации по эксплуатации.

> **Навигация:** [Главная Tempo](./index.md) | [Установка](./installation_traceql.md)

---

## Basic Concepts

### Архитектура

Архитектура Tempo очень похожа на [Loki](../Loki/loki_overview.md) и [Mimir](../Mimir/mimir_overview.md), что упрощает администрирование Grafana Stack. Tempo может быть развернут как в монолитном, так и в распределенном режиме.

#### Основные компоненты Tempo

* **Distributor (Диспетчер):** Принимает входящие трассировки в различных форматах ([OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md), [Jaeger](../Jaeger/jaeger_overview.md), Zipkin), выполняет базовую валидацию и распределяет их между инжестерами.
* **Ingester (Инжестер):** Принимает трассировки от Distributor, буферизует их в памяти, а затем записывает в долгосрочное хранилище (S3/NFS) в сжатом виде.
* **Querier (Запросчик):** Обрабатывает запросы TraceQL. Получает трассировки из инжестеров (для недавних данных) и из долгосрочного хранилища.
* **Query Frontend:** Опциональный компонент, который ставится перед Querier'ами для улучшения производительности запросов на чтение за счет кэширования и параллелизации.
* **Compactor:** Фоновый процесс, который отвечает за оптимизацию хранения трассировок в долгосрочном хранилище, объединяя небольшие файлы и применяя политики хранения.
* **Metric Generator (Генератор метрик):** Опциональный компонент, который может генерировать метрики на основе поступающих трассировок (например, количество запросов, среднее время выполнения, количество ошибок). Эти метрики затем могут быть собраны [Prometheus](../Prometheus/overview.md) или [Mimir](../Mimir/mimir_overview.md) и визуализированы в [Grafana](../Grafana/grafana_overview.md), что позволяет коррелировать метрики с трассировками.

#### Форматы хранения (vParquet)

Tempo использует собственный формат хранения на базе Parquet:

| Версия | Tempo | Статус |
| :--- | :--- | :--- |
| vParquet2 | <2.4 | Устаревший |
| vParquet3 | 2.4-2.5 | Поддерживается |
| **vParquet4** | **≥2.5** | **Формат по умолчанию** (требуется для новых функций TraceQL) |
| vParquet5 | 2026 (ожидается) | В разработке |

> **Breaking Change:** Новые функции TraceQL (events, links) работают только с vParquet4+.

---

## Practical Scenarios

### Breaking changes (v2.6+)

| Изменение | Описание | Требуемое действие |
| :--- | :--- | :--- |
| **vParquet4 по умолчанию** | Новый формат хранения | Требуется Tempo ≥2.5 для чтения |
| **TraceQL Metrics** | Экспериментальная функция | Настройка `local-blocks` processor, `replication_factor: 1` |
| **tempo-query** | Отдельный сервер (не gRPC plugin) | Обновление конфигурации на `0.0.0.0:7777` |
| **Удалённые параметры** | `storage.azure.use_v2_sdk`, `autocomplete_filtering_enabled` | Проверка конфигурации |

---

### Конфигурация

#### Минимальная конфигурация (монолит)

```yaml
# tempo.yaml
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

#### TraceQL Metrics configuration

```yaml
overrides:
  defaults:
    metrics_generator:
      processors: [local-blocks]  # Обязательно для Metrics
      storage_path: /var/tempo/metrics-generator
    tracing:
      enabled: true

# Для исторических данных
metrics_generator:
  processor:
    local_blocks:
      flush_to_storage: true
```

---

### Интеграции

#### Grafana (визуализация)

Tempo не имеет собственного UI. Визуализация осуществляется через [Grafana](../Grafana/grafana_overview.md):

* Поиск и фильтрация трассировок через TraceQL
* Просмотр диаграммы Ганта для трассировки
* Корреляция с метриками (Exemplars) и логами (Derived Fields)

> **См. также:** [Grafana datasources](../Grafana/grafana_datasources.md#сценарий-2-интеграция-loki-и-tempo-derived-fields)

#### OpenTelemetry Collector

Рекомендуемый способ отправки трассировок в Tempo:

```yaml
# otel-collector.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

exporters:
  otlphttp:
    endpoint: http://tempo:4318

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlphttp]
```

> **См. также:** [OTLP Protocol](../OpenTelemetry/otlp_protocol.md)

#### Loki (корреляция логов и трассировок)

Настройка Derived Fields в Loki позволяет переходить от логов к трассировкам:

1. Извлечение `trace_id` из логов через regex
2. Создание внутренней ссылки на datasource Tempo
3. Клик по `trace_id` в логах открывает трассировку в Grafana

> **См. также:** [Loki overview](../Loki/loki_overview.md)

---

### Рекомендации по эксплуатации

| Рекомендация | Описание |
| :--- | :--- |
| **Head sampling** | Настройка сэмплирования на уровне приложения для управления объёмом данных |
| **Retention policy** | Настройка политик хранения до развёртывания в production |
| **Единые trace_id** | Поддержка единых идентификаторов для трассировок, метрик и логов |
| **Кэширование** | Использование Redis/Memcached для Query Frontend |
| **Мониторинг Tempo** | Развёртывание Prometheus для мониторинга метрик самого Tempo |
| **TLS** | Включение TLS для всех внутренних коммуникаций в production |

---

## Additional Information

### Дополнительные ресурсы

* **[Официальная документация](https://grafana.com/docs/tempo/latest/)** — полное руководство по установке и конфигурации
* **[GitHub-репозиторий](https://github.com/grafana/tempo)** — исходный код, release notes, issues
* **[TraceQL Documentation](https://grafana.com/docs/tempo/latest/traceql/)** — полный справочник по языку запросов
* **[Tempo 2.10 Release Notes](https://grafana.com/docs/tempo/latest/release-notes/v2-10/)** — последние изменения
* **[Grafana Cloud](https://grafana.com/products/cloud/tempo/)** — управляемая версия Tempo от Grafana Labs

### Связанные темы

* **[OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md)** — стандарт телеметрии
* **[Grafana](../Grafana/grafana_overview.md)** — визуализация
* **[Loki](../Loki/loki_overview.md)** — корреляция логов
* **[Prometheus](../Prometheus/overview.md)** — метрики
