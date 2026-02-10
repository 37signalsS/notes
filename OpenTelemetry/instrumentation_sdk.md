# OpenTelemetry: Instrumentations и SDK

В экосистеме OpenTelemetry **инструментализация** (instrumentation) отвечает за сбор телеметрии в коде, а **SDK** (Software Development Kit) управляет её жизненным циклом: созданием, обработкой и экспортом.

## Роли компонентов

| Компонент            | Назначение                                             | Где находится                          | Примеры                                           |
|----------------------|--------------------------------------------------------|----------------------------------------|---------------------------------------------------|
| **Instrumentation**  | Встраивает получение метрик, логов, спанов; вызывает API | В коде приложения или в агенте         | HTTP, gRPC, DB драйверы, фреймворки (Django, Spring) |
| **API**              | Контракты для записи телеметрии                        | Библиотека, импортируемая приложением    | `Tracer`, `Meter`, `Logger`                       |
| **SDK**              | Реализация API с политиками и жизненным циклом данных  | В процессе приложения                  | `Sampler`, `SpanProcessor`, `Aggregator`          |
| **Exporter**         | Отправка за пределы процесса                           | Часть SDK или плагин                   | OTLP/gRPC, OTLP/HTTP, Prometheus                  |
| **Context Propagation**| Протокол переноса контекста между сервисами            | Заголовки/метаданные                   | W3C Trace Context                                 |

## Автоматическая vs. Ручная инструментализация

- **Автоматическая**: Агент подключается без изменения кода и "на лету" перехватывает вызовы популярных библиотек.
  - **Плюсы**: Быстрый старт, единообразие, минимальные риски регрессий.
  - **Минусы**: Ограниченная гибкость, не покрывает специфичные бизнес-события.

- **Ручная**: Прямые вызовы API (`Tracer`, `Meter`, `Logger`) в нужных местах кода.
  - **Плюсы**: Точная семантика, добавление бизнес-атрибутов, полный контроль над объёмом данных.
  - **Минусы**: Требует поддержки кода и согласованности в командах.

**Практический подход** — комбинировать оба метода: авто-инструментализация для стандартных инфраструктурных компонентов (веб-фреймворки, клиенты БД) и ручная — для ключевых бизнес-операций.

## Основные элементы SDK

- **Sampler**: Управляет созданием спанов/трейсов. Часто используют `ParentBased+TraceIdRatio` для балансировки объёма.
- **Span Processor**: Буферизация и батчинг спанов перед экспортом. `BatchSpanProcessor` снижает накладные расходы.
- **Exporter**: Определяет протокол и адрес назначения, обычно OTLP в сторону коллектора.
- **Resource**: Описывает службу и среду развертывания через атрибуты (`service.name`, `service.version`, `deployment.environment`).
- **Context/Baggage**: Механизмы для переноса корреляционных идентификаторов и атрибутов между сервисами.

## Примеры

### Ручная инструментализация (Python)

```python
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# 1. Определяем ресурс
resource = Resource.create({
    "service.name": "checkout",
    "service.version": "1.3.2",
    "deployment.environment": "prod"
})

# 2. Настраиваем провайдер трассировки
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://otel-collector:4318/v1/traces"))
)
trace.set_tracer_provider(provider)

# 3. Получаем трейсер
tracer = trace.get_tracer("checkout-handler")

# 4. Создаем спан
def place_order():
    with tracer.start_as_current_span("place_order") as span:
        span.set_attribute("order.items", 3)
        span.set_attribute("user.tier", "gold")
        # бизнес-логика...
```

### Авто-инструментализация (Java Agent)

Запуск приложения с Java-агентом, который автоматически инструментирует код.

```bash
java -javaagent:opentelemetry-javaagent.jar 
  -Dotel.service.name=payments 
  -Dotel.exporter.otlp.endpoint=http://otel-collector:4317 
  -Dotel.traces.sampler=parentbased_traceidratio 
  -Dotel.traces.sampler.arg=0.1 
  -jar app.jar
```

### Авто-инструментализация (Python)

Использование `opentelemetry-instrument` для запуска приложения.

```bash
export OTEL_SERVICE_NAME=api-gateway
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
export OTEL_TRACES_SAMPLER=parentbased_traceidratio
export OTEL_TRACES_SAMPLER_ARG=0.05

opentelemetry-instrument python app.py
```

## Сценарии и выбор

- **Высоконагруженные сервисы**: Требуют агрессивного сэмплирования, батчинга (`BatchSpanProcessor`) и строгих лимитов на размеры атрибутов.
- **Микросервисы в Kubernetes**: Эффективна комбинация авто-инструментализации и передачи конфигурации через аннотации подов, с единым маршрутом OTLP к коллектору.
- **Сложные бизнес-процессы**: Лучше всего подходят ручные спаны для ключевых шагов домена, с единой схемой атрибутов, согласованной с продуктовой аналитикой.

## Типичные ошибки

- **Отсутствие `Resource`-атрибутов**: Затрудняет фильтрацию и агрегацию телеметрии.
- **Дублирование экспортёров**: Приводит к лишней нагрузке и дублированию записей.
- **Неправильное использование сэмплеров**: Смешение разных политик без понимания наследования контекста.
- **Игнорирование `Context Propagation`**: Потеря сквозной трассировки на асинхронных границах (например, в очередях сообщений).
```
