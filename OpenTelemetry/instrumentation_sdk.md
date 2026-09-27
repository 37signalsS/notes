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

### Детекторы ресурсов (Resource Detectors)

Resource Detectors автоматически определяют атрибуты окружения (`service.name`, `k8s.pod.name`, `host.name`, `process.pid`), исключая хардкод в коде приложения. SDK применяет каскадный приоритет: официальные детекторы выполняются в порядке, и их результаты объединяются (`merge`), где приоритет имеет явно заданное значение.

**Официальные детекторы:**
- **Env Detector** (`env`): Читает `OTEL_RESOURCE_ATTRIBUTES`. Самый высокий приоритет, позволяет переопределить любой автоматически определённый атрибут.
- **Process Detector** (`process`): Добавляет `process.pid`, `process.executable.name`, `process.command_line`. Стабилен во всех SDK.
- **Container Detector** (`container`): Для Docker/Kubernetes — добавляет `container.name`, `container.image.name`, `container.id`. Требует доступа к cgroup filesystem (`/proc/1/cgroup`).
- **Kubernetes Detector** (`k8s`): Добавляет `k8s.pod.name`, `k8s.namespace.name`, `k8s.node.name`, `k8s.pod.uid`. Работает через downward API и kubelet metadata.
- **OS Detector** (`os`, `host`): Добавляет `os.type`, `os.description`, `host.name`, `host.arch`.

**SRE-совет:** Никогда не используйте ручное переопределение атрибутов в коде, если можете использовать `OTEL_RESOURCE_ATTRIBUTES`. Это упрощает отладку и исключает race condition при горячем обновлении конфигурации.

### Типы сэмплеров (Samplers)

- **AlwaysOn / AlwaysOff:** Всегда сохраняют или отклоняют трейс. Используются для debug (`AlwaysOn`) и extreme-load (`AlwaysOff`).
- **TraceIdRatioBased:** Сохраняет указанный процент трейсов (0.0–1.0). Вероятностное, но согласованное: если родительский спан сохранён, дочерний тоже сохраняется.
- **ParentBased:** Принимает решение на основе родительского спана. На корневом спане применяет указанный sampler, на дочерних — наследует решение родителя. Это стандартный вариант для production, предотвращающий разрывы трейсов.
- **Remote (в разработке):** Принимает решение от удалённого конфигурационного сервиса (например, через Jaeger sampling store).

**SRE-совет:** Для head-based сэмплинга используйте `ParentBased_TraceIdRatio` с аргументом 0.01–0.1 (1–10%). Для tail-based сэмплинга настройте Gateway или Collector с `groupbytrace` processor, чтобы сохранять ошибки и медленные запросы независимо от head-based решения.

### Процессоры (Processors)

- **BatchSpanProcessor:** Стандарт для production. Накопливает спаны в очередь и отправляет батчами. Ключевые параметры: `schedule_delay_millis` (интервал отправки, по умолчанию 5000ms), `max_queue_size` (максимальный размер очереди, по умолчанию 2048), `export_timeout_millis` (таймаут на экспорт, по умолчанию 30000ms), `max_export_batch_size` (размер батча, по умолчанию 512). При переполнении очереди спаны отбрасываются с логированием.
- **MemoryLimiterProcessor:** Защищает приложение от OOM. Проверяет использование памяти с заданным интервалом и ограничивает `check_interval`, `limit_mib` (порог, по умолчанию 0 = disabled), `spike_limit_mib` (допустимый всплеск). Обязателен в production для приложений с переменной нагрузкой.
- **GroupByTraceProcessor:** Группирует спаны по trace ID перед отправкой. Используется для tail-based сэмплинга на Gateway/Collector. Гарантирует, что решение о сохранении трейса принимается после завершения всех его спанов.
- **SimpleSpanProcessor:** Отправляет каждый спан немедленно. Используйте только в тестах и CLI-скриптах. В production приводит к блокировке потоков приложения при задержках Collector.

**SRE-совет:** Всегда используйте `BatchSpanProcessor` с `max_queue_size=2048` и `MemoryLimiterProcessor` с `limit_mib=512` (для JVM) или `limit_mib=256` (для Go/Python native). Для высоконагруженных сервисов увеличьте очередь до 4096 и добавьте второй Collector для горизонтального масштабирования.

### Методы конфигурации и жизненный цикл SDK

OpenTelemetry SDK может конфигурироваться двумя способами, которые можно комбинировать:

**1. Переменные окружения (OTEL_*) — рекомендуемый для 12-Factor App**
- Полная настройка без изменения кода.
- Ключевые переменные: `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_TRACES_SAMPLER`, `OTEL_TRACES_SAMPLER_ARG`, `OTEL_RESOURCE_ATTRIBUTES`, `OTEL_PROPAGATORS`, `OTEL_METRICS_EXPORTER`, `OTEL_EXPORTER_OTLP_COMPRESSION`.
- Преимущества: конфигурация вынесена в окружение, работает с любым языком, переключается без пересборки образа.
- Недостатки: сложная логика (кастомный sampler, conditional export, multi-exporter) недоступна.

**2. Fluent API в коде — для сложных сценариев**
- Полный контроль над TracerProvider, MeterProvider, Processor, Exporter.
- Подходит для кастомного сэмплирования, multi-exporter, graceful shutdown, compression, retry policy.
- Недостатки: требует правки кода при изменении конфигурации.

**3. Гибридный подход (рекомендуется в production)**
- Через env vars: endpoint, service name, resource attributes, sampler тип/аргумент.
- Через код: BatchProcessor параметры, retry policy, compression, multi-exporter.

### Завершение работы SDK (Shutdown)

SDK накапливает телеметрию в очереди. При остановке приложения необходимо гарантировать доставку накопленных данных:

```python
# Python: корректное завершение
provider.shutdown()  # блокирует до экспорта всех данных
# Или с таймаутом:
import signal
signal.signal(signal.SIGTERM, lambda s, f: provider.shutdown())
```

```go
// Go: graceful shutdown
func main() {
    tp, _ := initTracer()
    defer func() {
        ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
        defer cancel()
        if err := tp.Shutdown(ctx); err != nil {
            log.Fatal(err)
        }
    }()
}
```

**ForceFlush vs Shutdown:**
- `ForceFlush`: экспортирует текущие данные, но оставляет SDK рабочим. Используется в тестах.
- `Shutdown`: экспортирует все данные и освобождает ресурсы (соединения, горутины). Используется при остановке приложения.
- **SRE-правило:** Всегда используйте `Shutdown` с таймаутом. Без таймаута зависнувший Collector заблокирует остановку пода Kubernetes, что приведёт к `TerminationGracePeriodSeconds` и принудительному SIGKILL с потерей данных.

### Log Bridge API и Semantic Conventions

- **Log Bridge (Мост логов):** В 2026 году OTel SDK не требует замены привычных библиотек логирования (Log4j, Logback, Python logging). Вместо этого используется Log Bridge — специальный аппендер, который перехватывает логи из стандартной библиотеки, обогащает их текущим `trace_id`/`span_id` и отправляет через OTLP Exporter.
- **Semantic Conventions:** В 2026 году Semantic Conventions v1.x являются стабильными и покрывают все основные домены (HTTP, gRPC, DB, messaging, фасилитация K8s). Используйте языковые пакеты (`opentelemetry-semconv-java`, `opentelemetry-semconv-python`, `go.opentelemetry.io/otel/semconv/v1.21.0`) вместо сырых строк. Например, `HttpAttributes.HTTP_STATUS_CODE` вместо `"http.status_code"`. Это гарантирует совместимость с дашбордами вендоров и защищает от опечаток.
- **Diagnostics и отладка SDK:** Включите `OTEL_LOG_LEVEL=debug` для получения подробных логов инициализации SDK, особенно при проблемах с ResourceDetectors или Propagators. Для метрик используйте `OTEL_METRICS_DEBUG_VIEW=all` для включения exemplars в отладческий вывод. Collector предоставляет endpoint `debugpprof` для детального профилирования.

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

```go
package main

import (
    "context"
    "log"
    "time"
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/attribute"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
    "go.opentelemetry.io/otel/sdk/resource"
    sdktrace "go.opentelemetry.io/otel/sdk/trace"
    semconv "go.opentelemetry.io/otel/semconv/v1.21.0"
)

func initTracer(ctx context.Context) (*sdktrace.TracerProvider, error) {
    exporter, err := otlptracegrpc.New(ctx,
        otlptracegrpc.WithEndpoint("otel-collector:4317"),
        otlptracegrpc.WithInsecure(),
    )
    if err != nil {
        return nil, err
    }

    tp := sdktrace.NewTracerProvider(
        sdktrace.WithBatcher(exporter,
            sdktrace.WithMaxQueueSize(2048),
            sdktrace.WithExportTimeout(30*time.Second),
            sdktrace.WithMaxExportBatchSize(512),
        ),
        sdktrace.WithResource(resource.NewWithAttributes(
            semconv.ServiceNameKey.String("payment-api"),
            semconv.ServiceVersionKey.String("1.0.0"),
            semconv.DeploymentEnvironmentKey.String("production"),
        )),
        sdktrace.WithSampler(sdktrace.TraceIDRatioBased(0.1)),
    )

    otel.SetTracerProvider(tp)
    return tp, nil
}

func main() {
    ctx := context.Background()
    tp, err := initTracer(ctx)
    if err != nil {
        log.Fatalf("failed to init tracer: %v", err)
    }
    defer func() {
        shutdownCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
        defer cancel()
        if err := tp.Shutdown(shutdownCtx); err != nil {
            log.Printf("tracer shutdown error: %v", err)
        }
    }()

    tracer := otel.Tracer("payment-api")
    ctx, span := tracer.Start(ctx, "ProcessPayment")
    defer span.End()

    span.SetAttributes(
        attribute.String("payment.method", "card"),
        attribute.Int("payment.amount", 1500),
    )
    span.AddEvent("payment_validated")
}
```

**SRE-замечания для Go:**
- `WithInsecure()` допустим только в доверенных сетях (bare-metal L2, service mesh с mTLS). Для внешних вызовов используйте TLS-credentials.
- Go не имеет Java-style runtime agent. Для автоматической инструментации HTTP/gRPC используйте compile-time инструментацию (`-ldflags` с OpenTelemetry Go Instrumentation) или Prometheus client + manual spans.
- Для Kubernetes добавьте `k8sdetector` и `containerdetector` пакеты для автоматического определения pod/container атрибутов.

---

## Дополнительная информация

### Инструментация через eBPF (Sidecar-less)

Для Linux-окружений (Kubernetes) в 2026 году широко применяется **OTel eBPF Agent** (наследник проекта Odigos/Pixie).
- **Как работает:** Агент работает на уровне узла (DaemonSet), перехватывает системные вызовы в пространстве ядра и автоматически генерирует телеметрию для ЛЮБЫХ процессов (даже написанных на C++, Rust или Fortran) без инъекции в память пода.
- **Преимущества:** Нулевое изменение манифестов приложений, работа со статически скомпилированными legacy-системами, видимость TLS-трафика до шифрования.
- **Ограничения:** Требует привилегий уровня узла (`NET_ADMIN`, `SYS_ADMIN`), собирает только базовые метрики и трейсы (HTTP/RPC), не видит внутренние детали бизнес-логики и пользовательские переменные.

### Сценарий 5: Чистое конфигурирование через переменные окружения (12-Factor App)

Для приложений, где изменение кода невозможно или нежелательно (legacy, third-party binaries), вся конфигурация SDK задаётся через `OTEL_*` переменные:

```bash
# .env или манифест Deployment
OTEL_SERVICE_NAME=payment-api
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.opentelemetry:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1
OTEL_RESOURCE_ATTRIBUTES=service.namespace=production,deployment.environment=prod,team=payments
OTEL_PROPAGATORS=tracecontext,baggage
OTEL_LOG_LEVEL=info
```

```dockerfile
# Dockerfile: применение env vars без изменения кода
FROM python:3.12-slim
ENV OTEL_SERVICE_NAME=payment-api \
    OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 \
    OTEL_TRACES_SAMPLER=parentbased_traceidratio \
    OTEL_TRACES_SAMPLER_ARG=0.1
COPY requirements.txt .
RUN pip install opentelemetry-distro opentelemetry-exporter-otlp
CMD ["opentelemetry-instrument", "python", "app.py"]
```

**Валидация:**
```bash
# Проверка переменных внутри пода
kubectl exec -it <pod> -- env | grep OTEL

# Проверка приёма Collector
kubectl logs -l app=otel-collector -c opentelemetry-collector | grep "payment-api"
```

### Сценарий 6: Диагностика и отладка инструментации

При отсутствии телеметрии в backend используйте последовательную диагностику:

**Шаг 1. Включите debug-логи SDK**
```bash
export OTEL_LOG_LEVEL=debug
export OTEL_LOG_FILE=/tmp/otel-sdk.log
```

**Шаг 2. Проверьте ResourceDetectors**
```python
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.resources import (
    ProcessResourceDetector,
    EnvResourceDetector,
)

for detector in [ProcessResourceDetector(), EnvResourceDetector()]:
    print(detector.detect().attributes)
```

**Шаг 3. Валидируйте через Collector metrics**
```bash
# Prometheus endpoint Collector
curl -s http://otel-collector:8888/metrics \
  | grep otelcol_receiver_accepted_ \
  | grep -v "protocol="http""
```

**Шаг 4. Проверьте Propagators**
```bash
# Входящий запрос должен содержать traceparent
curl -v -H "traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01" \
  http://payment-api:8080/check
```

**Типичные проблемы диагностики:**
- Нет `process.pid` → приложение работает в chroot/sandbox без доступа к `/proc`.
- Нет `k8s.pod.name` → kubelet metadata API недоступна (проверьте RBAC).
- Спаны есть, но trace разорван → отсутствует Propagator или нарушена семантика W3C.

### Типичные ошибки и антипаттерны

- **Игнорирование Propagators:** Если в распределённой системе один сервис не передаёт заголовки W3C Trace Context (особенно в асинхронных очередях типа Kafka), сквозная трассировка будет разорвана. Очереди требуют явного извлечения/инъекции контекста.
- **Использование устаревших стандартов:** Использование Zipkin B3, OpenCensus или кастомных заголовков `x-request-id` для трассировки в 2026 году считается Legacy.
- **Отсутствие Resource Detectors:** Попытка вручную прописать имя пода или хоста в коде (например, через переменные среды приложения). Используйте стандартные Kubernetes/AWS/GCP детекторы SDK.
- **Синхронный экспорт:** Использование `SimpleSpanProcessor` в production-средах приводит к блокировке потоков приложения при задержках на стороне коллектора. Обязателен `BatchSpanProcessor`.

### Типичные проблемы и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Connection refused на 4317** | endpoint неверен или Collector не слушает gRPC | Проверить `OTEL_EXPORTER_OTLP_ENDPOINT`, `kubectl get pods -l app=otel-collector`, логи Collector |
| **Нет resource атрибутов** | ResourceDetectors не сработали (отсутствуют права cgroup/kubelet) | Проверить `OTEL_RESOURCE_ATTRIBUTES`, права пода (`securityContext.privileged` для eBPF), логи SDK (`OTEL_LOG_LEVEL=debug`) |
| **Спаны не поступают** | Sampler отбросил трейс или Propagator не настроен | Проверить `OTEL_TRACES_SAMPLER`, заголовки `traceparent` в запросах между сервисами |
| **Высокое потребление памяти** | `max_queue_size` BatchSpanProcessor слишком большой | Уменьшить очередь, добавить `MemoryLimiterProcessor` |
| **Потеря данных при SIGTERM** | Отсутствует graceful shutdown (`Shutdown` с таймаутом) | Реализовать `Shutdown` с `context.WithTimeout`, проверить `terminationGracePeriodSeconds` |
| **Контекст теряется между сервисами** | W3C Trace Context не распространяется через очередь/message broker | Явно инжектировать/экстрактировать Propagator на границах асинхронных вызовов |
| **Слишком много метрик/трейсов** | Отсутствует сэмплирование или кардинальность атрибутов слишком высокая | Настроить `TraceIDRatioBased`, использовать aggregation в SDK, ограничить `OTEL_RESOURCE_ATTRIBUTES` |

### Очистка окружения

```bash
# Очистка тестовых ресурсов Kubernetes
kubectl delete instrumentation --all -n my-app
kubectl delete pods -l instrumentation.opentelemetry.io/inject-java=true -n my-app

# Очистка тестовых метрик и логов
rm -f /tmp/otel-sdk.log /tmp/otel-sdk-debug.log

# Остановка фоновых Collector'ов
docker stop otel-collector && docker rm otel-collector
```

## Смотрите также

- [OpenTelemetry: Обзор](./opentelemetry_overview.md)
- [Архитектура и сигналы](./architecture_signals.md)
- [Протокол OTLP](./otlp_protocol.md)
- [Миграция с Jaeger/Zipkin](./migration_from_jaeger_zipkin.md)
- [Collector в не-Kubernetes средах](./collector_without_kubernetes.md)
