# Протокол OTLP: Структура данных

**OTLP (OpenTelemetry Protocol)** — это унифицированный протокол для передачи сигналов наблюдаемости (трассировок, метрик, логов), основанный на Protobuf-схемах. Он обеспечивает единый формат данных, что упрощает их обработку в коллекторах и бэкендах.

## Иерархия контейнеров

OTLP использует общую иерархическую структуру для всех сигналов:

1.  **Resource**: Контейнер верхнего уровня, описывающий источник данных через атрибуты (`service.name`, `host.name` и т.д.). Все сигналы в одном `Resource`-сообщении исходят от одной и той же сущности.
2.  **Scope (InstrumentationScope)**: Группирует телеметрию по источнику инструментирования (например, имя и версия библиотеки: `io.opentelemetry.spring-webmvc-5.3`).
3.  **Signal Records**: Непосредственно данные — спаны, метрики или логи.

Эта иерархия позволяет эффективно применять общие метаданные к множеству записей. Структура выглядит так:
- `ResourceSpans` → `ScopeSpans` → `Span[]`
- `ResourceMetrics` → `ScopeMetrics` → `Metric[]`
- `ResourceLogs` → `ScopeLogs` → `LogRecord[]`

## Атрибуты и типы данных

Атрибуты (пары ключ-значение) используются во всех сущностях. Значения представлены унифицированным типом `AnyValue`, который поддерживает:
- Примитивные типы: строка, булево, целое число, число с плавающей точкой, байтовый массив.
- Массив значений `AnyValue`.
- Вложенный список `KeyValue` для структурированных данных.

Единая модель атрибутов обеспечивает совместимость между сигналами и позволяет создавать унифицированные правила фильтрации и маршрутизации.

## Идентификаторы и время

- **Метки времени**: Хранятся как `unix_nano` (целые числа, наносекунды от Unix-эпохи).
- **Идентификаторы**: `TraceID` (16 байт) и `SpanID` (8 байт). В Protobuf представляются как `bytes`, в JSON — как hex-строки.
- **Severity**: Для логов используется `severity_number` и `severity_text`.

## Структуры сигналов

### Трассировки (Span)
- `name`, `kind` (client, server, etc.).
- `start_time_unix_nano`, `end_time_unix_nano`.
- `attributes[]`.
- `events[]`: события внутри спана с собственными атрибутами и метками времени.
- `links[]`: связи с другими спанами/трассами.
- `status` (code и message).

### Метрики (Metric)
- `name`, `description`, `unit`.
- Тип данных: `Gauge`, `Sum`, `Histogram`, `ExponentialHistogram`, `Summary`.
- Точки данных (`dataPoints`) содержат:
  - `attributes[]`.
  - `time_unix_nano` / `start_time_unix_nano`.
  - `value` (число) или `distribution` (bucket counts, sum, etc.).
  - `exemplars[]` (ссылки на трассы).
- `Sum` также имеет флаг `is_monotonic` и `aggregation_temporality` (`DELTA` или `CUMULATIVE`).

### Логи (LogRecord)
- `body` (тип `AnyValue`).
- `attributes[]`.
- `severity_number`, `severity_text`.
- `trace_id` и `span_id` для корреляции с трассировками.

## Пример OTLP/HTTP JSON: метрика Gauge

Сокращённый пример полезной нагрузки OTLP в формате JSON, демонстрирующий иерархию `Resource` → `Scope` → `Metric` → `DataPoint`.

```json
{
  "resourceMetrics": [
    {
      "resource": {
        "attributes": [
          {"key": "service.name", "value": {"stringValue": "payments-api"}},
          {"key": "service.version", "value": {"stringValue": "1.4.2"}}
        ]
      },
      "scopeMetrics": [
        {
          "scope": {"name": "otel.instrumentation.http", "version": "2.1.0"},
          "metrics": [
            {
              "name": "http.server.active_requests",
              "description": "In-flight HTTP requests",
              "unit": "{request}",
              "gauge": {
                "dataPoints": [
                  {
                    "timeUnixNano": "1717428123000000000",
                    "attributes": [
                      {"key": "http.method", "value": {"stringValue": "POST"}},
                      {"key": "http.route", "value": {"stringValue": "/v1/charge"}}
                    ],
                    "asInt": "7"
                  }
                ]
              }
            }
          ]
        }
      ]
    }
  ]
}
```
В этом же формате передаются и другие сигналы, меняется только полезная нагрузка внутри `metrics`, `spans` или `logs`.
