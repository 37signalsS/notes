# OpenTelemetry: Инструментация и SDK

## Определения

**Инструментация (Instrumentation)** — это процесс встраивания в код приложения механизмов сбора телеметрии. OpenTelemetry предоставляет для этого два основных компонента: API и SDK.

- **API (Application Programming Interface):** Набор абстрактных интерфейсов (`Tracer`, `Meter`, `Logger`), которые используются в коде для генерации спанов, метрик и логов. API не зависит от конкретной реализации, что позволяет менять обработчик телеметрии без изменения кода.
- **SDK (Software Development Kit):** Конкретная реализация API. SDK управляет жизненным циклом телеметрии: сэмплированием, обработкой, пакетированием и экспортом данных в Collector или напрямую в бэкенд.

### Статус SDK по языкам

| Язык | Статус SDK | Примечание |
|------|------------|------------|
| **Java** | `stable` | Автоматическая инструментация через javaagent |
| **Python** | `stable` | Полная поддержка метрик, логов, трассировок |
| **JavaScript/TypeScript** | `stable` | SDK v2.x с улучшенной производительностью |
| **Go** | `stable` | Модульная архитектура |
| **.NET** | `stable` | Автоматическая инструментация через profiler |
| **C++** | `beta` | Активное развитие |
| **Android** | `stable` | Специализированные модули для мобильных паттернов |

## Основные концепции

### Автоматическая vs. Ручная инструментация

**Автоматическая инструментация**

- **Что это:** Подключение агента или библиотеки, которые "на лету" (в runtime) перехватывают вызовы стандартных фреймворков и библиотек (например, HTTP-серверы, клиенты БД, gRPC) и создают телеметрические данные.
- **Плюсы:** Быстрый старт, не требует изменения кода, обеспечивает единообразный сбор данных.
- **Минусы:** Ограниченная гибкость, не покрывает специфичную бизнес-логику.

**Ручная инструментация**

- **Что это:** Прямые вызовы OTel API в коде для создания кастомных спанов, метрик и логов, отражающих бизнес-операции.
- **Плюсы:** Полный контроль, возможность добавить важные бизнес-атрибуты, точная семантика.
- **Минусы:** Требует написания и поддержки дополнительного кода.

**Рекомендация:** Используйте гибридный подход. Автоматическая инструментация для всей инфраструктурной обвязки и ручная — для ключевых бизнес-процессов.

### Ключевые компоненты SDK

- **Resource:** Описывает источник телеметрии через атрибуты (`service.name`, `service.version`). Является обязательным.
- **Tracer/Meter/Logger Provider:** Фабрики, которые создают и настраивают экземпляры `Tracer`, `Meter` и `Logger`.
- **Sampler:** Решает, будет ли для трассировки создан полноценный спан. `ParentBased_TraceIdRatio` — популярная стратегия, которая сэмплирует заданный процент трассировок.
- **Span Processor:** Обрабатывает спаны перед экспортом. `BatchSpanProcessor` — стандартный выбор для группировки спанов в пакеты.
- **Exporter:** Отправляет данные. Обычно это `OtlpGrpcExporter` или `OtlpHttpExporter`, направляющий данные в Collector.

## Практические сценарии

### Сценарий 1: Автоматическая инструментация Java-приложения

Запуск JAR-файла с подключенным Java-агентом. Конфигурация передается через системные свойства или переменные окружения.

```bash
java -javaagent:opentelemetry-javaagent.jar \
     -Dotel.service.name=payment-service \
     -Dotel.exporter.otlp.endpoint=http://otel-collector:4317 \
     -Dotel.traces.sampler=parentbased_traceidratio \
     -Dotel.traces.sampler.arg=0.1 \
     -jar app.jar
```

### Сценарий 2: Ручная инструментация в Python-приложении

Полная настройка SDK и создание кастомного спана для бизнес-логики.

```python
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# 1. Определение ресурса
resource = Resource.create({
    "service.name": "checkout-service",
    "service.version": "1.3.2"
})

# 2. Настройка провайдера трассировки с экспортёром
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://otel-collector:4318/v1/traces"))
)
trace.set_tracer_provider(provider)

# 3. Получение трейсера
tracer = trace.get_tracer("checkout.handler")

# 4. Создание спана вокруг бизнес-логики
def process_payment(order_id: str):
    with tracer.start_as_current_span("process_payment") as span:
        # Добавление бизнес-атрибутов
        span.set_attribute("order.id", order_id)
        span.set_attribute("user.level", "gold")
        # ... здесь логика обработки платежа ...
```

### Сценарий 3: Инструментация в .NET (C#)

В платформе .NET базовые абстракции (API) для генерации телеметрии встроены непосредственно в фреймворк (в `System.Diagnostics`), что делает интеграцию с OpenTelemetry максимально нативной.

**Основные классы API:**

- **`ActivitySource`** и **`Activity`**: Выступают в роли Tracer и Span соответственно.
- **`Meter`**: Фабрика для метрик (Counter, Gauge, Histogram).

**Настройка автоинструментации и экспорта (ASP.NET Core):**

```csharp
// Идентификатор ресурса
var resourceBuilder = ResourceBuilder.CreateDefault()
    .AddService("checkout-service");

builder.Services.AddOpenTelemetry()
    .WithTracing(tracerProviderBuilder => tracerProviderBuilder
        .SetResourceBuilder(resourceBuilder)
        .AddAspNetCoreInstrumentation() // Автоинструментация входящих HTTP-запросов
        .AddHttpClientInstrumentation() // Автоинструментация исходящих запросов
        .AddSource("checkout-service") // Подписка на кастомные спаны из ActivitySource
        .AddOtlpExporter(opts => { opts.Endpoint = new Uri("http://otel-collector:4317"); }))
    .WithMetrics(meterProviderBuilder => meterProviderBuilder
        .SetResourceBuilder(resourceBuilder)
        .AddAspNetCoreInstrumentation()
        .AddRuntimeInstrumentation() // Системные метрики (.NET GC, ThreadPool, память)
        .AddMeter("checkout-service") // Подписка на кастомные метрики из Meter
        .AddOtlpExporter(opts => { opts.Endpoint = new Uri("http://otel-collector:4317"); }));

// В бизнес-логике ручное создание спана:
// static readonly ActivitySource activitySource = new ActivitySource("checkout-service");
// using var activity = activitySource.StartActivity("process_checkout");
// activity?.SetTag("order.id", orderId);
```

### Сценарий 4: Ручная инструментация Go-приложения

В Go (в отличие от Java) отсутствует механизм автоматической инструментации через агент — требуется ручная настройка SDK. Код инициализации обычно выносится в функцию, вызываемую при старте приложения.

```go
package main

import (
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
    "go.opentelemetry.io/otel/propagation"
    "go.opentelemetry.io/otel/sdk/resource"
    sdktrace "go.opentelemetry.io/otel/sdk/trace"
    semconv "go.opentelemetry.io/otel/semconv/v1.21.0"
)

func initTracer() (*sdktrace.TracerProvider, error) {
    // 1. Создание экспортёра — отправляет данные в OTel Collector по gRPC
    exporter, err := otlptracegrpc.New(ctx,
        otlptracegrpc.WithEndpoint("otel-collector:4317"),
        otlptracegrpc.WithInsecure(),
    )
    if err != nil {
        return nil, err
    }

    // 2. Resource — идентификация сервиса
    res, err := resource.New(ctx,
        resource.WithAttributes(
            semconv.ServiceNameKey.String("payment-service"),
            semconv.ServiceVersionKey.String("1.0.0"),
        ),
    )

    // 3. TracerProvider — основной компонент SDK, создаёт Tracer
    tp := sdktrace.NewTracerProvider(
        sdktrace.WithBatcher(exporter),
        sdktrace.WithResource(res),
        sdktrace.WithSampler(sdktrace.TraceIDRatioBased(0.1)),
    )
    otel.SetTracerProvider(tp)

    // 4. Propagators — обеспечивают передачу trace context между сервисами
    otel.SetTextMapPropagator(
        propagation.NewCompositeTextMapPropagator(
            propagation.TraceContext{},
            propagation.Baggage{},
        ),
    )
    return tp, nil
}
```

**Важные моменты:**

- **Экспортёр:** рекомендуется `OTLP/gRPC` (порт `4317`). HTTP-экспортёр (порт `4318`) подходит для окружений с HTTP-прокси.
- **Propagators:** обязательны для сквозной трассировки. Без них `trace_id` не будет передаваться между сервисами, и трейсы «разорвутся».
- **Sampler:** `TraceIDRatioBased(0.1)` — сохраняет 10% трассировок. Должен быть одинаковым на всех коллекторах и сервисах для целостности трейсов.
- **Boilerplate:** код инициализации одинаков для всех Go-сервисов и рекомендуется выносить в общую платформенную библиотеку.

Аналогично настраиваются экспортёры для метрик (`otlpmetricgrpc`) и логов (`otlploggrpc`).

## Дополнительная информация

### Типичные ошибки

- **Отсутствие `Resource` атрибутов:** `service.name` является ключевым атрибутом. Его отсутствие делает телеметрию практически бесполезной.
- **Неправильная передача контекста:** Потеря сквозной трассировки на границах асинхронных операций (например, при работе с очередями сообщений) из-за ручного управления контекстом.
- **Использование `SimpleSpanProcessor` в production:** Этот процессор отправляет спаны по одному, создавая избыточную нагрузку. Всегда используйте `BatchSpanProcessor`.
- **Неправильная конфигурация сэмплера:** Слишком агрессивный сэмплинг может привести к потере важных трассировок, а его отсутствие — к перегрузке системы.

### eBPF-инструментация

**OpenTelemetry eBPF** — направление бесшовной инструментации без изменения кода приложения. eBPF-агент перехватывает системные вызовы и сетевой трафик, автоматически генерируя спаны.

**Преимущества:**

- Нулевое вмешательство в код
- Поддержка legacy-приложений
- Низкие накладные расходы

**Ограничения:**

- Только Linux (требуется ядро 4.x+)
- Ограниченная семантика (нет бизнес-атрибутов)
- В разработке

**Рекомендация:** Комбинируйте eBPF для инфраструктурного уровня с SDK-инструментацией для бизнес-логики.

## Смотрите также

- [OpenTelemetry: Обзор](./opentelemetry_overview.md)
- [Архитектура и сигналы](./architecture_signals.md)
- [Протокол OTLP](./otlp_protocol.md)
