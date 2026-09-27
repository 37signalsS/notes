# OpenTelemetry: Обзор

## Определения

**OpenTelemetry (OTel)** — открытый, независимый от поставщика набор спецификаций, API, SDK, инструментов инструментации и Collector для генерации, обработки и экспорта телеметрии. OTel поддерживает трассировки, метрики и логи; сигнал профилей продолжает развиваться. Проект входит в [Cloud Native Computing Foundation (CNCF)](https://www.cncf.io/).

**Текущие статусы:**

- OpenTelemetry имеет статус **CNCF Graduated**.
- API и основные возможности трассировок и метрик стабильны.
- Logs API имеет статус **Stable**, за исключением явно отмеченных частей спецификации; готовность API, SDK, автоинструментации и мостов логирования зависит от языка.
- Profiles имеет статус **Alpha**. Формат совместим с существующими профилями, но универсальная поддержка в SDK, Collector и бэкендах ещё не гарантирована.
- OTLP является стабильным протоколом передачи телеметрии.
- OTel-Arrow, также называемый OTAP, — отдельный эффективный транспорт на базе Apache Arrow. Он дополняет OTLP, но не является его обязательной или универсальной заменой.

OTel не требует одного конкретного хранилища. Приложение может отправлять данные напрямую в совместимый backend или использовать Collector как промежуточный слой.

## Основные концепции

### Архитектура сбора

Типовой поток данных выглядит следующим образом:

```text
Приложение
  ├── ручная инструментация
  ├── автоматическая инструментация
  └── мосты существующих библиотек
          │
          ▼
   OTel API и SDK
          │ OTLP
          ▼
   OTel Collector (опционально)
          │ OTLP или формат backend
          ▼
   backend: traces, metrics, logs, profiles
```

SDK формирует телеметрию и может экспортировать её напрямую в backend, если backend понимает нужный протокол. Для разработки и небольших систем прямой экспорт — допустимый и практичный вариант. В production Collector обычно предпочтительнее: он принимает данные от многих сервисов, выполняет batching, retry, фильтрацию, обогащение, сэмплирование и маршрутизацию, а также позволяет отправлять один сигнал в несколько backend-систем.

### Компоненты системы

1. **[API и SDK](./instrumentation_sdk.md):**
   - API задаёт независимые от реализации интерфейсы для создания трассировок, метрик и логов.
   - SDK реализует API, управляет ресурсами, контекстом, обработчиками, сэмплированием и экспортом.
   - Инструментация может быть ручной, автоматической или реализованной через мосты существующих библиотек.
2. **[Протокол OTLP](./otlp_protocol.md):** унифицированный протокол на основе Protobuf с транспортами gRPC и HTTP. Для gRPC обычно используется порт `4317`, для HTTP — `4318`.
3. **Collector:** независимый от поставщика прокси, который принимает, обрабатывает и экспортирует телеметрию. Он может работать как локальный агент, шлюз или в комбинированной топологии.
4. **Backend:** система хранения и анализа. Выбор backend зависит от типов сигналов, запросов, retention, стоимости, кардинальности и требований эксплуатации.

### Анатомия Collector

Collector строится из компонентов, которые соединяются в pipeline:

- **Receivers (приёмники):** принимают данные по OTLP, Prometheus, Jaeger, Zipkin, Fluent Bit, Syslog, filelog и другим протоколам.
- **Processors (обработчики):** изменяют поток данных. Часто применяются `memory_limiter`, `batch`, `attributes`, `resource`, `transform`, `filter`, `tail_sampling` и `spanmetrics`.
- **Exporters (экспортёры):** отправляют данные в backend или другой транспорт. Один pipeline может иметь несколько exporters.
- **Connectors (коннекторы):** передают результат одного pipeline в другой. Например, `spanmetrics` создаёт метрики на основе трассировок.
- **Extensions (расширения):** предоставляют служебные возможности, такие как health check, authentication, pprof и управление конфигурацией. Они не являются обычными этапами pipeline.

Порядок processors важен. `memory_limiter` обычно размещают первым, чтобы ограничить потребление памяти и создать backpressure до остальной обработки. `batch` обычно размещают ближе к экспорту, чтобы уменьшить количество сетевых запросов.

#### Пример минимальной конфигурации Collector

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
    spike_limit_mib: 128
  batch:
    timeout: 10s
    send_batch_size: 1024

exporters:
  otlp:
    endpoint: backend:4317
    tls:
      insecure: false
      cert_file: /etc/otel/cert.pem
      key_file: /etc/otel/key.pem

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp]
```

### Топологии развертывания

- **Direct export:** SDK отправляет данные напрямую в backend. Подходит для локальной разработки, демонстраций и небольших систем.
- **Agent:** Collector работает рядом с приложением или на каждом узле, принимает локальный трафик и передаёт его дальше.
- **Gateway:** централизованный Collector агрегирует данные, выполняет фильтрацию, сэмплирование и маршрутизацию.
- **Agent + Gateway:** агенты собирают данные на узлах, а шлюзы выполняют общую обработку. Эта схема полезна для масштабирования, но требует балансировки и контроля состояния, особенно для tail-based sampling.
- **Sidecar:** Collector размещается в том же Pod или рабочей нагрузке. Даёт изоляцию, но увеличивает количество экземпляров и операционные затраты.
- **eBPF/OBI:** может собирать часть сетевых и системных данных без изменения кода, но не заменяет бизнес-инструментацию и требует поддержки платформы, прав и совместимого backend.

## Практические сценарии

### Выбор backend

Backend выбирают не по названию стека, а по требованиям нагрузки и эксплуатации:

| Критерий | Что проверить |
| :--- | :--- |
| Поддержка сигналов | Какие версии traces, metrics, logs и profiles принимает backend |
| OTLP | Поддерживаются ли gRPC, HTTP/Protobuf и нужные signal-specific endpoints |
| Кардинальность | Как backend обрабатывает большое число уникальных label и attribute combinations |
| Запросы | Какие языки запросов, индексация, агрегации и корреляция доступны |
| Стоимость | Объем хранения, сжатие, ingestion, query-нагрузка и retention |
| Надёжность | Очереди, retry, backpressure, репликация и восстановление после сбоя |
| Безопасность | TLS, аутентификация, авторизация, маскирование PII и аудит |
| Эксплуатация | Обновления, мониторинг, масштабирование и наблюдаемость самого pipeline |

Перед окончательным выбором нужно прогнать репрезентативный набор данных через кандидатные backend-системы и сравнить фактический объем хранения, задержку, качество поиска и стоимость. Один backend может хорошо подходить для метрик, но быть неоптимальным для логов или трассировок.

### Сэмплирование и кардинальность

Сэмплирование уменьшает объем трассировок без потери репрезентативной картины:

- **Head-based sampling** принимает решение в SDK до завершения трейса. Оно эффективно и дешево, но не может учитывать ошибки или задержку, обнаруженные позже.
- **Tail-based sampling** принимает решение после получения достаточной части трейса. Позволяет сохранять ошибки, медленные запросы и другие важные сценарии, но требует памяти, состояния и правильной маршрутизации всех span одного trace в один экземпляр Collector.
- **Комбинированный подход** может сначала ограничивать поток на SDK, а затем применять tail-based правила на Gateway.

Для метрик особенно важно управлять кардинальностью. Не следует помещать `user_id`, `order_id`, request ID и другие почти уникальные значения в metric attributes или labels. Такие значения лучше хранить в теле структурированного лога или в tracing attributes, где они не создают отдельный временной ряд. Для снижения стоимости применяют фильтрацию, агрегацию, нормализацию имен, ограничение набора атрибутов и retention policies.

### Data Prepper и OpenSearch

**Data Prepper** — pipeline-движок экосистемы OpenSearch. Он может принимать OTLP, маршрутизировать события по типам сигналов, применять processors и записывать данные в OpenSearch или другие sinks. В типовом OpenSearch-стеке он преобразует traces и logs в документы, формирует service map и может отправлять производные метрики в Prometheus.

Data Prepper не является обязательным компонентом OpenTelemetry. Его используют, когда выбран OpenSearch и требуется соответствующая обработка или индексация. Для других backend-систем можно отправлять данные напрямую из Collector или использовать их собственные ingest-компоненты.

### Мониторинг Collector

Collector следует мониторить как обычный production-сервис. По умолчанию он выводит внутренние метрики через Prometheus endpoint на порту `8888`, а внутренние логи — в `stderr`.

Проверяют как минимум:

- `otelcol_receiver_accepted_*` и `otelcol_receiver_refused_*`;
- `otelcol_processor_incoming_items` и `otelcol_processor_outgoing_items`;
- `otelcol_exporter_queue_size` и `otelcol_exporter_queue_capacity`;
- `otelcol_exporter_enqueue_failed_*` и `otelcol_exporter_send_failed_*`;
- потребление CPU, RSS, heap и длительность export requests.

Наличие refused items, переполненной очереди или устойчивых export failures требует проверки backend, сети, ресурсов Collector и настроек retry.

#### Конфигурация Prometheus для сбора метрик Collector

```yaml
scrape_configs:
  - job_name: 'otel-collector'
    static_configs:
      - targets: ['otel-collector:8888']
```

#### Пример алертов для Collector

```yaml
groups:
  - name: otel-collector-alerts
    rules:
      - alert: OTelCollectorReceiverRefused
        expr: increase(otelcol_receiver_refused_spans_total[5m]) > 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "OTel Collector отклоняет входящие спаны"
          description: "{{ $labels.job }} отклоняет {{ $value }} спанов за 5m"

      - alert: OTelCollectorExporterQueueFull
        expr: otelcol_exporter_queue_size / otelcol_exporter_queue_capacity > 0.8
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Очереди экспортёров OTel Collector почти заполнены"
          description: "{{ $labels.job }}: {{ $value | humanizePercentage }}"

      - alert: OTelCollectorExportFailures
        expr: increase(otelcol_exporter_send_failed_spans_total[5m]) > 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "OTel Collector имеет сбои отправки"
          description: "{{ $labels.job }}: {{ $value }} ошибок отправки за 5m"
```

### Валидация pipeline

После развертывания Collector проверяют сквозной поток данных на каждом сигнале:

1. **Traces:** Отправить тестовый запрос через приложение с инструментацией, найти соответствующий trace в backend UI и убедиться, что все span имеют корректный `trace_id`, `service.name` и временные метки.
2. **Metrics:** Проверить, что Prometheus или другой scraper видит метрики от целевых endpoints, и что они имеют ожидаемые labels.
3. **Logs:** Найти тестовое сообщение в logging backend и убедиться, что ему сопоставлены `trace_id` и `span_id` из соответствующего trace.
4. **Correlation:** Создать один запрос, найти его trace, перейти к связанным logs через `trace_id`, а затем проверить, что метрики latency этого сервиса отражают время запроса.

Для диагностики можно использовать curl к метрикам Collector:

```bash
curl -s http://otel-collector:8888/metrics | grep otelcol_receiver_accepted_spans
curl -s http://otel-collector:8888/metrics | grep otelcol_exporter_queue_size
```

### Планирование ресурсов

Collector потребляет CPU и память пропорционально объёму обрабатываемых данных. Для начальной оценки:

1. **CPU:** Зависит от количества span, сложности processors и compression. Batch processor и transform требуют больше CPU, чем простой pass-through. Ориентир: 1 CPU на 10 000–20 000 spans/second на инстанс.
2. **Память:** Определяется `memory_limiter` и размером очередей. Tail-based sampling и spanmetrics хранят состояния span в памяти. Ориентир: 2 GiB RAM на инстанс для нагрузки до 50k spans/second.
3. **Сеть:** OTLP/gRPC использует HTTP/2. Сжатие (`zstd`, `gzip`) снижает bandwidth, но увеличивает CPU.

Начинают с 1 CPU и 2 GiB RAM на инстанс Collector. При нагрузке выше 50k spans/second масштабируют горизонтально. Мониторят `otelcol_processor_memory_limiter_refused_spans_total` — этот индикатор сигнализирует о необходимости увеличения лимитов или количества инстансов.

### Демо OpenTelemetry

Официальный демо-проект показывает многопоточное приложение, Collector, backend-системы и различные варианты инструментации. Для полного запуска репозитория:

```bash
git clone https://github.com/open-telemetry/opentelemetry-demo.git
cd opentelemetry-demo
docker compose up --force-recreate --remove-orphans --detach
```

Для минимального режима в версиях репозитория, где предоставлен отдельный compose-файл:

```bash
docker compose -f docker-compose.minimal.yml up --force-recreate --remove-orphans --detach
```

В актуальных версиях демо также предусмотрены режимы `make start-minimal`, `make start-no-o11y` и `make start-profiling`; конкретный набор compose-файлов следует сверять с README выбранной версии репозитория. После запуска проверяют web store, Collector, backend UI и наличие traces, metrics и logs.

## Безопасность и управление

- Для внешних соединений используют TLS или mTLS; параметры безопасности задают явно, а не полагаются на случайные значения по умолчанию.
- Для аутентификации могут применяться заголовки, bearer token, OIDC и другие механизмы backend.
- Конфиденциальные данные фильтруют или маскируют до экспорта с помощью processors и политик сбора.
- Telemetry Schemas помогают управлять изменениями семантических конвенций и совместимостью данных.
- Конфигурацию Collector хранят в системе контроля версий, проверяют перед внедрением и сопровождают метриками pipeline.

## Устранение неполадок

Для детального устранения неполадок см. [Архитектура и сигналы](./architecture_signals.md).

Частые проблемы production-сред:

| Проблема | Первичное действие |
| :--- | :--- |
| Traces/metrics/logs не появляются | Проверить endpoint Collector, логи SDK, сетевую доступность |
| Collector потребляет много CPU | Включить `zstd` compression, ограничить `max_recv_msg_size` |
| Очереди экспортёров растут | Проверить доступность backend, настроить retry и timeout |
| Collector перезапускается | Проверить `dmesg` на OOM-kill, увеличить `memory_limiter` |
| Кардинальность метрик растет | Фильтровать атрибуты, применять агрегацию до экспорта |
| Loss данных при перезапуске | Добавить `sending_queue` с `file_storage` в exporters |

## Смотрите также

- [Архитектура и сигналы](./architecture_signals.md)
- [Инструментация и SDK](./instrumentation_sdk.md)
- [Протокол OTLP](./otlp_protocol.md)
- [Интеграция с Prometheus](./prometheus_integration.md)
- [Интеграция с Grafana](./grafana_integration.md)
- [Миграция с Jaeger/Zipkin](./migration_from_jaeger_zipkin.md)
- [GitOps для Collector](./gitops_collector.md)
- [Безопасность в Kubernetes](./security_kubernetes.md)
- [Управление ресурсами](./resource_management.md)
- [Collector в не-Kubernetes средах](./collector_without_kubernetes.md)
- [Управление кардинальностью](./cardinality_management.md)
- [Продвинутое сэмплирование](./advanced_sampling.md)
- [Отказоустойчивость Collector](./collector_high_availability.md)
