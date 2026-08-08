# OpenTelemetry: Архитектура и сигналы

## Определения

**Сигналы (Signals)** в OpenTelemetry — это стандартизированные типы телеметрических данных. К ним относятся трассировки, метрики, логи и профили. Единая модель данных и семантические конвенции позволяют коррелировать сигналы между собой, обеспечивая глубокую наблюдаемость системы.

**Статус в 2026 году:**
- Проект OpenTelemetry официально имеет статус **CNCF Graduated**.
- Все основные сигналы (**Traces**, **Metrics**, **Logs**, **Profiles**) полностью стабильны и готовы к использованию в Production.

Все сигналы разделяют общую структуру метаданных через **Resource** (описание источника телеметрии) и **Instrumentation Scope** (описание библиотеки-генератора).

## Основные концепции

### 1. Трассировки (Traces)

Представляют собой дерево **спанов (Spans)**, иллюстрирующее путь выполнения запроса через распределённую систему.
- **Анатомия спана:**
  - **Span Context:** Содержит `trace_id`, `span_id` и флаги трассировки.
  - **Attributes:** Ключ-значение метаданные (например, `http.method`, `db.statement`).
  - **Events:** Структурированные логи с временной меткой внутри спана (например, информация об исключениях).
  - **Links:** Связи со спанами из других трассировок (полезно для асинхронных операций и пакетной обработки).
- **Контекст (Context Propagation):** Передача идентификаторов между сервисами через заголовки (стандарт W3C Trace Context).
- **Baggage:** Передача произвольных метаданных сквозь всю цепочку вызовов.
- Подробнее: **[Трассировки: детали](../Concepts/Observability_and_Monitoring/traces_deep_dive.md)**.

### 2. Метрики (Metrics)

Агрегированные числовые измерения производительности и состояния системы.
- **Типы:** `Sum` (счётчик), `Gauge` (текущее значение), `Histogram` (распределение).
- **Exponential Histograms:** В 2026 году являются стандартом для высокоточного измерения перцентилей без предварительной настройки границ корзин (buckets).
- **Temporality:** Поддержка `Delta` и `Cumulative` способов агрегации.
- Подробнее: **[Метрики: детали](../Concepts/Observability_and_Monitoring/metrics_deep_dive.md)**.

### 3. Логи (Logs)

Записи о событиях, интегрированные в OTel через **Log Bridge API**.
- **Log Bridge:** Позволяет использовать стандартные библиотеки (Log4j, Python logging) для отправки логов в OTel, автоматически добавляя контекст трассировки.
- **Корреляция:** Автоматическая привязка `trace_id` и `span_id` к каждой записи при наличии активного спана.
- Подробнее: **[Логи: детали](../Concepts/Observability_and_Monitoring/logs_deep_dive.md)**.

### 4. Профили (Profiles)

Стабильный сигнал для непрерывного профилирования (Continuous Profiling). Позволяет анализировать потребление ресурсов (CPU, Memory) на уровне функций кода и сопоставлять их с конкретными трейсами (Span-to-Profile).

### Корреляция сигналов и Exemplars

OpenTelemetry обеспечивает бесшовный переход между типами данных:
- **Трассировки ↔ Логи:** Сквозной `trace_id` для фильтрации логов конкретного запроса.
- **Трассировки ↔ Метрики (Exemplars):** Механизм **Exemplars** прикрепляет `trace_id` к точкам на графиках метрик, позволяя из графика задержек сразу перейти к проблемному трейсу.
- **Трассировки ↔ Профили:** Позволяет анализировать нагрузку на CPU именно в момент выполнения конкретного спана.

### Архитектура Collector: Коннекторы (Connectors)

Коннекторы позволяют выход одного пайплайна использовать как вход для другого:
- **SpanMetrics Connector:** Генерирует RED-метрики (RPS, Errors, Duration) на основе трейсов.
- **ServiceGraph Connector:** Строит карту зависимостей сервисов.
- **Routing Connector:** Маршрутизирует данные на основе атрибутов.

## Практические сценарии

### Конвейер Collector с использованием коннекторов и Arrow

Пример современной конфигурации для высоконагруженных систем:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        arrow: true # Включение поддержки Arrow для оптимизации трафика
      http:

connectors:
  spanmetrics: # Генерация метрик из трейсов
    histogram:
      explicit:
        buckets: [2ms, 10ms, 50ms, 250ms, 1s, 5s]

processors:
  batch:
    timeout: 5s
  resourcedetection: # Автоматическое определение метаданных инфраструктуры
    detectors: [env, system, k8snode, gcp]
  transform: # Использование OTTAL для модификации данных на лету
    error_mode: ignore
    trace_statements:
      - context: span
        statements:
          - replace_pattern(name, "password", "***")

exporters:
  prometheus:
    endpoint: "0.0.0.0:9464"
    add_metric_suffixes: false
  otlp/tempo:
    endpoint: "tempo:4317"
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [resourcedetection, transform, batch]
      exporters: [otlp/tempo, spanmetrics]
    metrics:
      receivers: [otlp, spanmetrics]
      processors: [resourcedetection, batch]
      exporters: [prometheus]
```

## Дополнительная информация

### Сравнение стабильности и применения (2026)

| Сигнал | Статус | Основное применение | Особенности |
| :--- | :--- | :--- | :--- |
| **Трассировки** | **Stable** | Анализ распределённых запросов | Требуют сэмплинга (Tail Sampling) |
| **Метрики** | **Stable** | Мониторинг SLO и алертинг | Поддержка Exponential Histograms |
| **Логи** | **Stable** | Детальное расследование | Интеграция через Log Bridge |
| **Профили** | **Stable** | Оптимизация производительности | Сбор через eBPF или SDK |

### Рекомендации по выбору форматов и экспортеров

- **Транспорт:** Используйте **OTLP/Arrow** для передачи данных между коллекторами в High-Load средах.
- **Протоколы:** Забудьте про Zipkin/Jaeger-thrift, используйте исключительно **OTLP**.
- **Хранение:** Стек LGTM (Loki, Grafana, Tempo, Mimir) обеспечивает лучшую поддержку корреляции сигналов «из коробки».

## Смотрите также

- [OpenTelemetry: Обзор](./opentelemetry_overview.md)
- [Протокол OTLP](./otlp_protocol.md)
- [Инструментация и SDK](./instrumentation_sdk.md)
- [Четыре столпа Observability](../Concepts/Observability_and_Monitoring/four_pillars_of_observability.md)
