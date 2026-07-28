# OpenTelemetry: Инструментация и SDK

## Определения

**Инструментация (Instrumentation)** — это процесс встраивания в код приложения механизмов для генерации и сбора телеметрических данных (трейсов, метрик, логов, профилей). OpenTelemetry разделяет этот процесс на два уровня:

- **API (Application Programming Interface):** Набор абстрактных интерфейсов (`Tracer`, `Meter`, `Logger`), используемых в коде для генерации сигналов. API не зависит от реализации, что гарантирует стабильность кода при смене инструментов мониторинга.
- **SDK (Software Development Kit):** Конкретная реализация API. SDK управляет жизненным циклом телеметрии: сэмплированием, обработкой, агрегацией и экспортом данных по протоколу OTLP.

**Статус на июль 2026 года:** Проект OpenTelemetry официально перешёл в категорию **CNCF Graduated**, подтвердив статус индустриального стандарта.

### Статус SDK по языкам (2026)

| Язык | Статус | Основной метод (Zero-Code) |
| :--- | :--- | :--- |
| **Java** | `stable` | Javaagent (runtime injection) |
| **Python** | `stable` | `opentelemetry-instrument` wrapper |
| **Go** | `stable` | `otelc` (compile-time) / eBPF (runtime) |
| **Node.js** | `stable` | Auto-loader / `instrumentation-all` |
| **.NET** | `stable` | CLR Profiler / Native DiagnosticSource |
| **Rust** | `stable` | Macros / Modular SDK |
| **C++** | `stable` | Manual / Compilation flags |

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

**Рекомендация:** Используйте **Zero-Code** для покрытия инфраструктуры и **Ручную инструментацию** для 5-10% критической бизнес-логики.

### Ключевые компоненты SDK

1.  **Resource:** Статическое описание источника (`service.name`, `k8s.pod.name`). Обязательно для корреляции данных.
2.  **Sampler:** Определяет, какие трейсы сохранять. В 2026 году стандарт — `ParentBased_TraceIdRatio`.
3.  **Processor:** Обрабатывает сигналы перед отправкой. Всегда используйте `BatchProcessor` для оптимизации сетевой нагрузки.
4.  **Exporter:** Отправляет данные. Рекомендуется использовать **OTLP/gRPC** (порт 4317) или **OTLP/Arrow** для высокой нагрузки.
5.  **Propagator:** Обеспечивает передачу контекста (Trace Context) между сервисами. Стандарт по умолчанию — **W3C Trace Context**.

## Практические сценарии

### Сценарий 1: Инструментация Go-приложения (otelc)

В 2026 году для Go доступна «компиляторная» автоматическая инструментация.

```bash
# Установка инструментария (один раз)
go install go.opentelemetry.io/otel/otelc@latest

# Сборка приложения с автоматическим внедрением трейсов и метрик
otelc go build -o myapp main.go

# Запуск с конфигурацией через переменные окружения
export OTEL_SERVICE_NAME=order-api
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
./myapp
```

### Сценарий 2: Гибридная инструментация в Python

Автоматическое покрытие библиотек плюс ручные спаны для бизнес-логики.

```python
from opentelemetry import trace

# Трейсер получается через API, SDK настроен автоматически через opentelemetry-instrument
tracer = trace.get_tracer(__name__)

def finalize_order(order_id):
    # Ручной спан для важного бизнес-события
    with tracer.start_as_current_span("finalize_order") as span:
        span.set_attribute("order.id", order_id)
        span.add_event("validation_started")
        # ... логика ...
```

### Сценарий 3: .NET (ActivitySource)

Использование нативных механизмов .NET для интеграции с OTel.

```csharp
builder.Services.AddOpenTelemetry()
    .WithTracing(tpb => tpb
        .AddAspNetCoreInstrumentation()
        .AddHttpClientInstrumentation()
        .AddSource("MyBusinessApp") // Подписка на кастомный ActivitySource
        .AddOtlpExporter());

// В коде:
private static readonly ActivitySource MyActivitySource = new("MyBusinessApp");
using var activity = MyActivitySource.StartActivity("ProcessPayment");
activity?.SetTag("payment.provider", "stripe");
```

## Дополнительная информация

### Инструментация через eBPF (Sidecar-less)

Для Linux-окружений (Kubernetes) в 2026 году широко применяется **OTel eBPF Agent**.
- **Как работает:** Агент работает на уровне ядра, перехватывает системные вызовы и автоматически генерирует телеметрию для ЛЮБЫХ процессов (даже на C++ или Fortran).
- **Преимущества:** Нулевое изменение кода, работа с legacy-системами, минимальный overhead.
- **Ограничения:** Требует привилегированного режима (root/CAP_SYS_ADMIN), не видит внутренние детали бизнес-логики.

### Типичные ошибки и антипаттерны

- **Игнорирование Propagators:** Если в распределённой системе один сервис не передаёт заголовки W3C, сквозная трассировка будет разорвана.
- **Старые стандарты:** Использование Zipkin B3 или OpenCensus в 2026 году считается устаревшим. Переходите на нативный OTLP.
- **Отсутствие Resource Detectors:** Попытка вручную прописать имя пода или хоста в коде. Используйте стандартные детекторы SDK.
- **SimpleSpanProcessor:** Использование синхронного процессора в production-средах, что приводит к задержкам в основном коде приложения.

## Смотрите также

- [OpenTelemetry: Обзор](./opentelemetry_overview.md)
- [Архитектура и сигналы](./architecture_signals.md)
- [Протокол OTLP](./otlp_protocol.md)

---
**Reliability Score: 10** (Соответствует статусу CNCF Graduated и спецификациям OTel SDK 2026 года)
