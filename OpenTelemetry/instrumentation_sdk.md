# OpenTelemetry: Инструментация и SDK

## Определения

**Инструментация (Instrumentation)** — это процесс встраивания в код приложения механизмов для генерации и сбора телеметрических данных (трейсов, метрик, логов, профилей). OpenTelemetry разделяет этот процесс на два уровня:

- **API (Application Programming Interface):** Набор абстрактных интерфейсов (`Tracer`, `Meter`, `Logger`), используемых в коде для генерации сигналов. API не зависит от реализации, что гарантирует стабильность кода при смене инструментов мониторинга.
- **SDK (Software Development Kit):** Конкретная реализация API. SDK управляет жизненным циклом телеметрии: сэмплированием, обработкой, агрегацией и экспортом данных по протоколу OTLP.

**Статус в 2026 году:** Проект OpenTelemetry официально имеет статус **CNCF Graduated**, подтвердив статус индустриального стандарта. Все ключевые SDK стабильны и поддерживают полную корреляцию сигналов (Traces, Metrics, Logs, Profiles).

### Статус SDK по языкам (2026)

| Язык | Статус | Основной метод (Zero-Code) | Особенности профилирования |
| :--- | :--- | :--- | :--- |
| **Java** | `stable` | Javaagent (runtime injection) | Встроенный OTel JFR Profiler |
| **Python** | `stable` | `opentelemetry-instrument` wrapper | Py-spy интеграция |
| **Go** | `stable` | `otelc` (compile-time) / eBPF (runtime) | Нативная интеграция `pprof` |
| **Node.js** | `stable` | Auto-loader / `instrumentation-all` | V8 Profiling |
| **.NET** | `stable` | CLR Profiler / Native DiagnosticSource | EventPipe интеграция |
| **Rust** | `stable` | Macros / Modular SDK | eBPF фокус |
| **C++** | `stable` | Manual / Compilation flags | eBPF фокус |

## Основные концепции

### Автоматическая vs. Ручная инструментация

**Автоматическая (Zero-Code) инструментация**
- **Принцип:** Использование агентов, обёрток или инструментов компиляции для перехвата вызовов стандартных библиотек (HTTP, gRPC, DB).
- **Плюсы:** Мгновенный результат, отсутствие правок в коде, поддержка сторонних библиотек.
- **Минусы:** Не учитывает специфику бизнес-логики, требует прав на инъекцию кода.

**Ручная инструментация**
- **Принцип:** Использование OTel API для создания кастомных спанов и метрик, отражающих бизнес-процессы (например, `process_order`).
- **Плюсы:** Максимальная точность, возможность добавления бизнес-атрибутов (`customer_tier`, `order_value`).
- **Минусы:** Требует времени на разработку и поддержку.

**Рекомендация:** Используйте **Zero-Code** для 100% покрытия инфраструктуры и **Ручную инструментацию** для 5-10% критической бизнес-логики.

### Ключевые компоненты SDK

1.  **Resource:** Статическое описание источника (`service.name`, `k8s.pod.name`). Обязательно для корреляции данных.
2.  **Sampler:** Определяет, какие трейсы сохранять. В 2026 году стандарт — `ParentBased_TraceIdRatio`.
3.  **Processor:** Обрабатывает сигналы перед отправкой. Всегда используйте `BatchProcessor` (для трейсов/логов) для оптимизации сетевой нагрузки.
4.  **Exporter:** Отправляет данные. Рекомендуется использовать **OTLP/gRPC** (порт 4317) или **OTLP/Arrow** для высокой нагрузки.
5.  **Propagator:** Обеспечивает передачу контекста (Trace Context) между сервисами. Стандарт по умолчанию — **W3C Trace Context**.

### Log Bridge API и Semantic Conventions

- **Log Bridge (Мост логов):** В 2026 году OTel SDK не требует замены привычных библиотек логирования (Log4j, Logback, Python logging). Вместо этого используется Log Bridge — специальный аппендер, который перехватывает логи из стандартной библиотеки, обогащает их текущим `trace_id`/`span_id` и отправляет через OTLP Exporter.
- **Semantic Conventions:** Использование предопределенных библиотек конвенций (например, `opentelemetry-semconv-java`) вместо сырых строк. Например, использование `HttpAttributes.HTTP_STATUS_CODE` вместо `"http.status_code"`. Это гарантирует совместимость с дашбордами вендоров.

---

## Практические сценарии

### Сценарий 1: Инструментация в Kubernetes через OpenTelemetry Operator

Современный стандарт для Kubernetes — это использование OTel Operator для автоматической инъекции агентов (Java, Python, Node.js, .NET) через механизм Mutating Webhook.

**Шаг 1. Создание ресурса Instrumentation CRD:**

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: global-instrumentation
  namespace: my-app
spec:
  exporter:
    endpoint: http://otel-collector.opentelemetry:4317
  propagators:
    - tracecontext
    - baggage
  sampler:
    type: parentbased_traceidratio
    argument: "0.1" # 10% сэмплирования
  java:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:latest
```

**Шаг 2. Подключение приложения через аннотацию:**
В манифесте Deployment достаточно добавить аннотацию, и Operator автоматически внедрит init-container с агентом:

```yaml
  template:
    metadata:
      annotations:
        instrumentation.opentelemetry.io/inject-java: "true"
```

### Сценарий 2: Гибридная инструментация в Python (API + Zero-Code)

Автоматическое покрытие библиотек (через `opentelemetry-instrument`) плюс ручные спаны для бизнес-логики.

```python
from opentelemetry import trace
# Использование библиотеки семантических конвенций
from opentelemetry.semconv.trace import SpanAttributes

# Трейсер получается через API, сам SDK инициализирован агентом-оберткой
tracer = trace.get_tracer(__name__)

def finalize_order(order_id):
    # Ручной спан для важного бизнес-события
    with tracer.start_as_current_span("finalize_order") as span:
        # Добавление бизнес-атрибутов
        span.set_attribute("order.id", order_id)
        # Использование Semantic Conventions
        span.set_attribute(SpanAttributes.PEER_SERVICE, "payment-gateway")
        span.add_event("validation_started")
        # ... логика ...
```

### Сценарий 3: .NET и связывание метрик с трейсами (Exemplars)

Использование нативных механизмов .NET (`ActivitySource`) и API метрик с поддержкой Exemplars (автоматическое прикрепление `trace_id` к точке на графике).

```csharp
builder.Services.AddOpenTelemetry()
    .WithTracing(tpb => tpb
        .AddAspNetCoreInstrumentation()
        .AddSource("MyBusinessApp")
        .AddOtlpExporter())
    .WithMetrics(mpb => tpb
        .AddMeter("MyBusinessMetrics")
        .AddOtlpExporter());

// В коде генерация метрики. SDK автоматически прикрепит текущий Trace ID как Exemplar
var meter = new Meter("MyBusinessMetrics");
var counter = meter.CreateCounter<int>("orders_processed");

using var activity = new ActivitySource("MyBusinessApp").StartActivity("ProcessPayment");
counter.Add(1, new KeyValuePair<string, object?>("status", "success"));
```

---

## Дополнительная информация

### Инструментация через eBPF (Sidecar-less)

Для Linux-окружений (Kubernetes) в 2026 году широко применяется **OTel eBPF Agent** (наследник проекта Odigos/Pixie).
- **Как работает:** Агент работает на уровне узла (DaemonSet), перехватывает системные вызовы в пространстве ядра и автоматически генерирует телеметрию для ЛЮБЫХ процессов (даже написанных на C++, Rust или Fortran) без инъекции в память пода.
- **Преимущества:** Нулевое изменение манифестов приложений, работа со статически скомпилированными legacy-системами, видимость TLS-трафика до шифрования.
- **Ограничения:** Требует привилегий уровня узла, собирает только базовые метрики и трейсы (HTTP/RPC), не видит внутренние детали бизнес-логики и пользовательские переменные.

### Типичные ошибки и антипаттерны

- **Игнорирование Propagators:** Если в распределённой системе один сервис не передаёт заголовки W3C Trace Context (особенно в асинхронных очередях типа Kafka), сквозная трассировка будет разорвана. Очереди требуют явного извлечения/инъекции контекста.
- **Использование устаревших стандартов:** Использование Zipkin B3, OpenCensus или кастомных заголовков `x-request-id` для трассировки в 2026 году считается Legacy.
- **Отсутствие Resource Detectors:** Попытка вручную прописать имя пода или хоста в коде (например, через переменные среды приложения). Используйте стандартные Kubernetes/AWS/GCP детекторы SDK.
- **Синхронный экспорт:** Использование `SimpleSpanProcessor` в production-средах приводит к блокировке потоков приложения при задержках на стороне коллектора. Обязателен `BatchSpanProcessor`.

## Смотрите также

- [OpenTelemetry: Обзор](./opentelemetry_overview.md)
- [Архитектура и сигналы](./architecture_signals.md)
- [Протокол OTLP](./otlp_protocol.md)
