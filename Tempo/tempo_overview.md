# Grafana Tempo

## 1. Определения

**Tempo** — это высокомасштабируемое распределенное хранилище для трассировок (traces), разработанное Grafana Labs. Tempo было анонсировано в 2020 году и достигло статуса General Availability (GA) в 2021. Tempo написано на Go и распространяется под лицензией **AGPLv3**, как и другие компоненты Grafana Stack, что обеспечивает открытость и прозрачность проекта. Основная цель Tempo — предоставить экономичное и эффективное решение для хранения трассировок.

В контексте распределенных систем, **трассировка (Trace)** — это запись полного жизненного цикла запроса или транзакции, проходящего через несколько сервисов. Она показывает, какие сервисы были задействованы, в какой последовательности, сколько времени занял каждый этап, и как они взаимодействовали друг с другом.

**Span (Спан)** — это фундаментальная единица трассировки. Спан представляет собой отдельную операцию в рамках трассировки (например, HTTP-запрос к другому сервису, вызов функции, запрос к базе данных). Каждый спан имеет имя, время начала, время окончания, набор атрибутов (ключ-значение) и может иметь ссылки на другие спаны (родительские, дочерние).

**TraceQL** — язык запросов для поиска и фильтрации трассировок в Tempo, вдохновленный PromQL и LogQL. Поддерживает фильтрацию по атрибутам, длительности, событиям (events), ссылкам (links) и агрегацию (metrics).

## 2. Базовые концепции

Ключевая задача трассировок — дать возможность разработчикам и инженерам быстро находить и анализировать распределенные трассировки в своих микросервисных архитектурах.

Трассировки позволяют:

* Определять задержки и "узкие места" в распределенных системах.
* Визуализировать потоки выполнения запросов.
* Отлаживать ошибки, происходящие на стыке сервисов.

### 2.1. Ключевые особенности

* **Масштабируемость:** Разработано для горизонтального масштабирования, способное обрабатывать огромные объемы трассировок.
* **Экономичное хранение:** Хранит трассировки в объектных хранилищах (например, S3, GCS, Azure Blob Storage, MinIO) или на NFS, что делает хранение данных дешевым. Данные хранятся в сжатом виде.
* **Полная поддержка OpenTelemetry:** Tempo полностью поддерживает стандарт [OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md) для сбора, обработки и экспорта телеметрии. Grafana Labs активно контрибьютит в его развитие.
* **Мульти-тенатность:** Встроенная поддержка изоляции данных для разных команд или клиентов (tenants).
* **Интеграция с Grafana:** Глубокая интеграция с [Grafana](../Grafana/grafana_overview.md) для визуализации трассировок и корреляции их с метриками и логами. У Tempo нет собственного UI.
* **Гибкость:** Поддерживает различные форматы трассировок, включая [Jaeger](../Jaeger/jaeger_overview.md), Zipkin и [OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md).
* **Exemplars (кросс-сигнальная корреляция):** Связь трассировок с метриками Prometheus через `trace_id`. Позволяет переходить от графика метрик к конкретной трассировке в один клик.
* **Нативные гистограммы Prometheus:** Поддержка native histograms для данных высокой точности (с v2.6).

### 2.2. Сравнение с Jaeger

| Характеристика | Tempo | Jaeger v2 |
| :--- | :--- | :--- |
| **Индексация** | Только по `trace_id` | Полная индексация метаданных (теги) |
| **Хранилище** | Object storage (S3, GCS, Azure, MinIO) | Elasticsearch, OpenSearch, Cassandra, ClickHouse, Badger |
| **Стоимость хранения** | Низкая (дешёвое object storage) | Высокая (требует БД) |
| **Поиск** | Ограничен (по trace_id и атрибутам через TraceQL) | Гибкий поиск по тегам, сервисам, операциям |
| **UI** | Интеграция с Grafana | Собственный Jaeger UI |
| **Масштабируемость** | Неограниченная (object storage) | Ограничена возможностями БД |
| **Операционная сложность** | Низкая | Средняя/Высокая (тюнинг БД) |
| **Экосистема** | Grafana Stack (Loki, Mimir, Grafana) | CNCF, независимый проект |

**Вывод:** Tempo — выбор для экономичного хранения больших объёмов трассировок в экосистеме Grafana. Jaeger — для сценариев с требованием гибкого поиска и независимого развёртывания.

> **См. также:** [Jaeger overview](../Jaeger/jaeger_overview.md)

## 3. Практические сценарии

### 3.1. Установка

#### Способы установки

* **Бинарный файл:** Доступны бинарники для Linux, macOS и Windows.
* **Docker:** Использовать официальный [Docker-образ](../Docker/docker_overview.md).
* **Kubernetes:** Развернуть с помощью Helm-чарта в [Kubernetes](../Kubernetes/kubernetes_overview.md).
* **Grafana Cloud:** Использовать Tempo как сервис.

#### Развёртывание в Kubernetes

```bash
# Добавление репозитория
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Установка Tempo (распределённая версия)
helm install tempo grafana/tempo-distributed \
  --namespace tempo \
  --create-namespace
```

> **См. также:** [LGTM Stack в Minikube](../Kubernetes/Installation/LGTM_Stack/lgtm_otel_minikube_overview.md)

### 3.2. Язык запросов TraceQL

**TraceQL** — это язык запросов для поиска и фильтрации трассировок в Tempo. Он позволяет искать трассировки по атрибутам спанов, продолжительности, времени выполнения и другим параметрам. TraceQL вдохновлен PromQL и LogQL, что обеспечивает схожесть синтаксиса и упрощает освоение.

#### Базовый синтаксис

```traceql
// Фильтрация по атрибутам спанов
{.service.name = "frontend" && .http.status_code = 500}

// Фильтрация по продолжительности спанов
{.duration > 100ms}

// Поиск по событиям (events)
{ event.name = "exception" }

// Поиск по ссылкам (links)
{ link.opentracing.ref_type = "child_of" }

// Комбинированные запросы
{ .service.name = "auth" } && { .service.name = "payment" }
```

#### TraceQL Metrics (экспериментально, с v2.6)

TraceQL поддерживает агрегацию и подсчет метрик на основе трассировок:

```traceql
// Подсчёт по сервисам
count_by(.service.name)

// Сравнение метрик
compare(rate({.status = error}[1h]))

// Мгновенные запросы (быстрее диапазонных)
/api/metrics/query?q={.duration > 1s}
```

> **Важно:** Для TraceQL Metrics требуется `replication_factor: 1` и настройка `local-blocks` processor.

#### Примеры возможностей TraceQL

* Фильтрация по атрибутам спанов: `{.service.name = "frontend" && .http.status_code = 500}`
* Фильтрация по продолжительности спанов: `{.duration > 100ms}`
* Поиск по событиям (events) и ссылкам (links)
* Агрегация и подсчет: `count_by(.service.name)`
* Функция `compare()` для сравнения метрик
* Мгновенные запросы метрик (instant queries)

## 4. Дополнительная информация

### 4.1. Архитектура

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

### 4.2. Breaking changes (v2.6+)

| Изменение | Описание | Требуемое действие |
| :--- | :--- | :--- |
| **vParquet4 по умолчанию** | Новый формат хранения | Требуется Tempo ≥2.5 для чтения |
| **TraceQL Metrics** | Экспериментальная функция | Настройка `local-blocks` processor, `replication_factor: 1` |
| **tempo-query** | Отдельный сервер (не gRPC plugin) | Обновление конфигурации на `0.0.0.0:7777` |
| **Удалённые параметры** | `storage.azure.use_v2_sdk`, `autocomplete_filtering_enabled` | Проверка конфигурации |

### 4.3. Конфигурация

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

### 4.4. Интеграции

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

### 4.5. Рекомендации по эксплуатации

| Рекомендация | Описание |
| :--- | :--- |
| **Head sampling** | Настройка сэмплирования на уровне приложения для управления объёмом данных |
| **Retention policy** | Настройка политик хранения до развёртывания в production |
| **Единые trace_id** | Поддержка единых идентификаторов для трассировок, метрик и логов |
| **Кэширование** | Использование Redis/Memcached для Query Frontend |
| **Мониторинг Tempo** | Развёртывание Prometheus для мониторинга метрик самого Tempo |
| **TLS** | Включение TLS для всех внутренних коммуникаций в production |

### 4.6. Дополнительные ресурсы

* **[Официальная документация](https://grafana.com/docs/tempo/latest/)** — полное руководство по установке и конфигурации
* **[GitHub-репозиторий](https://github.com/grafana/tempo)** — исходный код, release notes, issues
* **[TraceQL Documentation](https://grafana.com/docs/tempo/latest/traceql/)** — полный справочник по языку запросов
* **[Tempo 2.10 Release Notes](https://grafana.com/docs/tempo/latest/release-notes/v2-10/)** — последние изменения
* **[Grafana Cloud](https://grafana.com/products/cloud/tempo/)** — управляемая версия Tempo от Grafana Labs
