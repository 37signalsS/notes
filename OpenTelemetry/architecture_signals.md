# Архитектура OpenTelemetry: Трейсинг, Метрики, Логи

OpenTelemetry объединяет три столпа наблюдаемости в единую модель и протокол OTLP. Архитектура отделяет сбор и передачу данных (SDK) от их маршрутизации и экспорта (Collector), обеспечивая единообразие форматов и сквозную корреляцию между событиями.

## Сигналы и модель данных

- **Трейсинг**: Представляет выполнение запроса как дерево спанов. Каждый спан содержит имя операции, временные метки, атрибуты (ключ-значение), события и статус. Идентификаторы `trace_id`/`span_id` обеспечивают связывание распределённых вызовов.
- **Метрики**: Периодические числовые измерения. Типы данных в OTel: `Sum` (счетчики/измерители), `Gauge` (моментальные значения), `Histogram` и `ExponentialHistogram` (распределения). Агрегации происходят при чтении/экспорте.
- **Логи**: Неизменяемые записи о событиях. `LogRecord` содержит `timestamp`, `severity`, `body` и набор атрибутов. При наличии активного контекста логи могут включать `trace_id`/`span_id` для корреляции.

Общая модель включает **Resource** (атрибуты среды: `service.name`, `service.version`, `cloud.region`), **Instrumentation Scope** (библиотека/версия), а также единые семантические конвенции для названий атрибутов.

## Поток данных и компоненты

- **Приложение**: Ручная или автоинструментация с помощью SDK; экспорт по OTLP/HTTP или OTLP/gRPC.
- **OpenTelemetry Collector**: Независимый агент/шлюз с конвейерами для каждого сигнала (per-signal):
  - **Receivers**: Приёмники данных (например, `otlp`).
  - **Processors**: Обработчики (например, `batch`, `attributes`, `sampling`, `transform`).
  - **Exporters**: Экспортёры (например, `otlp`, `jaeger`, `prometheus`, `logging`).
- **Хранилища/визуализация**: Системы APM, трейсинг-бэкенды, TSDB/дашборды, стеки логов.

Конвейеры разных сигналов настраиваются независимо, но могут разделять обработчики.

## Корреляция и контекст

W3C Trace Context обеспечивает перенос `traceparent` и `tracestate` между сервисами. **Baggage** переносит ключи бизнес-контекста. Корреляция достигается за счет:

- Встраивания `trace_id`/`span_id` в логи.
- Метрических **exemplars**, которые сохраняют ссылки на конкретные трассы в выборочных наблюдениях гистограмм.
- Согласованных `Resource`-атрибутов на всех сигналах.

## Сэмплирование и агрегирование

- **Трейсинг**: Допускает head- и tail-сэмплирование. **Head-сэмплирование** выполняется в SDK до отправки; **tail-сэмплирование** — в Collector после анализа завершенных трасс.
- **Метрики**: Агрегируются в SDK/читателях (readers), снижая трафик и объем хранилища.
- **Логи**: Чаще всего фильтруются и нормализуются процессорами; допускается понижение уровня детализации для «шумных» источников.

## Сравнение сигналов

| Сигнал  | Форма данных              | Назначение                  | Чувствительность ко времени | Корреляция |
|---------|---------------------------|-----------------------------|-----------------------------|------------|
| Трейсы  | Дерево спанов             | Диагностика пути запроса    | Высокая                     | `trace_id` |
| Метрики | Временные ряды/агрегаты   | Здоровье и тренды           | Высокая/периодическая       | `exemplars`|
| Логи    | Записи событий            | Детали и аудит              | Средняя                     | `trace_id` |

## Минимальные примеры

### Инициализация SDK и корреляция логов

```python
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader

# Трейсинг
tp = TracerProvider()
tp.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(tp)
tracer = trace.get_tracer("checkout")

# Метрики
reader = PeriodicExportingMetricReader(ConsoleMetricExporter())
metrics.set_meter_provider(MeterProvider(metric_readers=[reader]))
meter = metrics.get_meter("checkout")
orders = meter.create_counter("orders_total")

with tracer.start_as_current_span("create_order") as span:
    span.set_attribute("user.tier", "gold")
    orders.add(1, {"region": "eu-west-1"})
    tid = format(span.get_span_context().trace_id, "032x")
    print(f"INFO order created trace_id={tid} user=42")
```

### Конвейеры в Collector

```yaml
receivers:
  otlp:
    protocols:
      http:
      grpc:

processors:
  batch:

exporters:
  logging:
    loglevel: info
  otlp:
    endpoint: my-apm.example:4317
    tls:
      insecure: true
  prometheus:
    endpoint: "0.0.0.0:9464"

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp, logging]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheus, logging]
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp, logging]
```
