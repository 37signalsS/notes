# OpenTelemetry: Миграция с Jaeger и Zipkin

## Определения

**Миграция с Jaeger/Zipkin на OpenTelemetry** — это процесс перехода от специализированных систем трассировки (Jaeger, Zipkin) к унифицированному стандарту OpenTelemetry. Миграция может быть:

1. **Полная** — замена Jaeger/Zipkin на OTel Collector + backend (Tempo, Jaeger v2).
2. **Частичная** — использование OTel Collector как промежуточного слоя для сбора данных.
3. **Параллельная** — одновременная отправка данных в старую и новую системы (dual-write).

В 2026 году Jaeger v2 построен на OTel Collector и принимает данные через OTLP, что упрощает миграцию.

## Теоретический блок

### Сравнение систем

| Характеристика | Jaeger v1 | Zipkin | OpenTelemetry |
| :--- | :--- | :--- | :--- |
| **Протокол** | Jaeger Thrift, OTLP | Zipkin B3 | OTLP (gRPC, HTTP) |
| **Формат данных** | Jaeger-specific | Zipkin-specific | Унифицированный |
| **Инструментация** | Jaeger SDK | Zipkin SDK | OTel SDK |
| **Хранение** | Cassandra, Elasticsearch, Kafka | Cassandra, Elasticsearch | Tempo, Jaeger v2, ClickHouse |

### Стратегии миграции

```text
Стратегия 1: Dual-Write (безопасная)
Приложение → OTel SDK → Collector → Jaeger v1 (старый)
                                 → Tempo (новый)

Стратегия 2: Collector as Gateway
Приложение → Jaeger/Zipkin SDK → Collector → Jaeger v1
                                            → Tempo

Стратегия 3: Полная замена
Приложение → OTel SDK → Collector → Tempo
```

### Преимущества миграции

- **Универсальность** — один стандарт для всех сигналов.
- **Гибкость** — возможность маршрутизации в несколько backend.
- **Будущее** — OTel является CNCF Graduated проектом.
- **Интеграция** — лучшая поддержка современных инструментов.

## Практические сценарии

### Сценарий 1: Dual-Write (безопасная миграция)

**Цель:** Отправлять данные одновременно в Jaeger v1 и Tempo для проверки корректности.

**Конфигурация OTel Collector:**

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
  batch:
    timeout: 10s

exporters:
  # Старый backend (Jaeger v1)
  otlp/jaeger:
    endpoint: "jaeger-collector:4317"
    tls:
      insecure: true

  # Новый backend (Tempo)
  otlp/tempo:
    endpoint: "tempo:4317"
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp/jaeger, otlp/tempo]
```

**Валидация:**

```bash
# Проверка данных в Jaeger
curl -s "http://jaeger:16686/api/traces?service=my-service" | jq '.data | length'

# Проверка данных в Tempo
curl -s "http://tempo:3100/api/search?query={service.name=\"my-service\"}" | jq '.traces | length'
```

### Сценарий 2: Миграция с Jaeger SDK на OTel SDK

**Шаг 1: Установка OTel SDK вместо Jaeger SDK**

```python
# Было (Jaeger SDK)
from jaeger_client import Config
config = Config(service_name='my-service', config={'sampler': {'type': 'const', 'param': 1}})
tracer = config.initialize_tracer()

# Стало (OTel SDK)
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

provider = TracerProvider()
processor = BatchSpanProcessor(OTLPSpanExporter(endpoint="http://collector:4317"))
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("my-service")
```

**Шаг 2: Конфигурация OTel Collector для приема OTLP**

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

exporters:
  # Экспорт в Jaeger v2 (OTLP)
  otlp/jaeger:
    endpoint: "jaeger-collector:4317"
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlp/jaeger]
```

### Сценарий 3: Миграция с Zipkin

**Настройка OTel Collector для приема Zipkin:**

```yaml
receivers:
  zipkin:
    endpoint: 0.0.0.0:9411

processors:
  batch:
    timeout: 10s

exporters:
  otlp/tempo:
    endpoint: "tempo:4317"
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [zipkin]
      processors: [batch]
      exporters: [otlp/tempo]
```

**Настройка Zipkin SDK для отправки в OTel Collector:**

```python
from opentelemetry.exporter.zipkin.proto.grpc import ZipkinExporter

exporter = ZipkinExporter(endpoint="http://collector:9411")
```

### Сценарий 4: Постепенная миграция сервисов

**Фаза 1: Миграция 10% сервисов**
```yaml
# Разделение трафика через OTel Collector
processors:
  routing:
    default_exporter: jaeger
    table:
      - service.name: "new-service"
        exporter: tempo
```

**Фаза 2: Миграция 50% сервисов**
```yaml
# Увеличение доли сервисов на OTel
processors:
  routing:
    default_exporter: tempo
    table:
      - service.name: "legacy-service"
        exporter: jaeger
```

**Фаза 3: Полная миграция**
```yaml
# Все сервисы на OTel
exporters:
  otlp/tempo:
    endpoint: "tempo:4317"
```

## Дополнительная информация

### Типичные проблемы и решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Данные не появляются в новом backend** | Неверный endpoint или протокол | Проверить `OTEL_EXPORTER_OTLP_ENDPOINT`, логи Collector |
| **Дублирование трассировок** | Dual-write не отключен после миграции | Отключить exporter в старую систему |
| **Потеря контекста** | Разные propagators (B3 vs W3C) | Настроить `OTEL_PROPAGATORS=tracecontext,baggage` |
| **Разные имена span** | Отличия семантических конвенций | Использовать OTel Semantic Conventions |

### Checklist миграции

1. **Подготовка:**
   - [ ] Установить OTel Collector и backend (Tempo/Jaeger v2)
   - [ ] Настроить dual-write для параллельной работы
   - [ ] Проверить корректность данных в обоих backend

2. **Миграция:**
   - [ ] Заменить SDK в приложениях на OTel SDK
   - [ ] Настроить OTel Collector для маршрутизации
   - [ ] Проверить корреляцию сигналов

3. **Завершение:**
   - [ ] Отключить dual-write
   - [ ] Удалить старые SDK и конфигурации
   - [ ] Обновить документацию и мониторинг

### Best Practices

1. **Начните с dual-write** — это безопасный способ проверить корректность данных.
2. **Мигрируйте поэтапно** — не заменяйте все сервисы одновременно.
3. **Тестируйте на staging** — проверяйте миграцию в тестовом окружении.
4. **Мониторьте метрики** — отслеживайте количество span в старой и новой системе.
5. **Документируйте изменения** — фиксируйте все изменения конфигурации.

### Ссылки

- [Jaeger v2 with OTel](https://www.jaegertracing.io/docs/latest/getting-started/)
- [Zipkin to OTel Migration](https://opentelemetry.io/docs/collector/zipkin/)
- [OTel Collector Contrib](https://github.com/open-telemetry/opentelemetry-collector-contrib)
