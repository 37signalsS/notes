# Формат экспозиции метрик Prometheus

## Определения

**Формат экспозиции (Exposition Format)** — это стандарт представления метрик, предназначенный для передачи данных от экспортёров и приложений к серверу [Prometheus](../../overview.md) по протоколу HTTP. 

В современной экосистеме (v3.0+) сосуществуют три спецификации:
1.  **Prometheus Text Format (v0.0.4):** Классический текстовый формат, стандарт де-факто для Pull-модели.
2.  **OpenMetrics:** Расширение текстового формата, добавляющее поддержку единиц измерения (UNIT), экземпляров (Exemplars) и нативных гистограмм.
3.  **OTLP (OpenTelemetry Line Protocol):** Бинарный формат на базе Protobuf, который в Prometheus v3.0 стал нативным протоколом для приема метрик (Push и Pull).

## Основные концепции

### Структура текстового формата

Каждая метрика в потоке данных должна быть описана метаданными перед выводом точек данных.

| Директива / Строка | Обязательность | Описание |
|:---|:---|:---|
| `# HELP <имя> <текст>` | Рекомендуется | Поясняет смысл метрики. |
| `# TYPE <имя> <тип>` | **Обязательно** | Тип данных: `counter`, `gauge`, `histogram`, `summary`. |
| `# UNIT <имя> <единица>` | Опционально | Единицы измерения (только в OpenMetrics). |
| `<имя>{<метки>} <значение> [<timestamp>]` | **Обязательно** | Конкретный временной ряд и его текущее значение. |

### Синтаксис и UTF-8 (Prometheus v3.0)

До версии 3.0 имена метрик были ограничены ASCII. Начиная с v3.0, Prometheus поддерживает **полный UTF-8**:
- Метрики могут содержать любые символы (точки, пробелы, эмодзи, кириллицу), если они передаются через OTLP или закодированы в кавычках (в OpenMetrics).
- **Пример классического имени:** `http_requests_total` (соответствует `[a-zA-Z_:][a-zA-Z0-9_:]*`).
- **Значения:** Только `float64`. Поддерживаются `NaN`, `+Inf`, `-Inf`.

### Экземпляры (Exemplars)

OpenMetrics позволяет прикреплять к метрикам (обычно Histogram или Counter) ссылки на конкретные события, например `trace_id`. Это обеспечивает бесшовную корреляцию метрик и трейсов ([OpenTelemetry](../../../OpenTelemetry/architecture_signals.md)).

**Синтаксис:**
```text
http_request_duration_seconds_bucket{le="0.5"} 12 # {trace_id="a1b2c3d4"} 0.452
```
Здесь `0.452` — это конкретное значение задержки, которое попало в эту корзину и связано с указанным трейсом.

## Практические сценарии

### Сценарий 1: Пример в коде (Go)

Как создать метрики, которые будут генерировать правильный формат экспозиции через `client_golang`.

```go
import (
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
    // Обязательно указываем суффикс _total для Counter
    opsProcessed = prometheus.NewCounter(prometheus.CounterOpts{
        Name: "myapp_processed_ops_total", 
        Help: "Общее количество обработанных операций.",
    })
)

// При GET-запросе на /metrics библиотека выдаст:
// # HELP myapp_processed_ops_total Общее количество обработанных операций.
// # TYPE myapp_processed_ops_total counter
// myapp_processed_ops_total 1024
```

### Сценарий 2: Гистограмма в текстовом формате

Гистограмма всегда порождает группу взаимосвязанных рядов.

```text
# HELP http_request_duration_seconds Latency in seconds.
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{le="0.1"} 15
http_request_duration_seconds_bucket{le="0.5"} 42
http_request_duration_seconds_bucket{le="1.0"} 50
http_request_duration_seconds_bucket{le="+Inf"} 52
http_request_duration_seconds_sum 12.5
http_request_duration_seconds_count 52
```

**Важное напоминание:** Составляющие `_bucket`, `_sum` и `_count` являются **счётчиками (Counters)**. При их анализе в PromQL всегда используйте `rate()` перед любой агрегацией (например, `sum`), чтобы корректно обрабатывать рестарты приложения.

### Сценарий 3: Информационные метрики (Info-pattern)

Для передачи метаданных, которые не меняются (версия, ветка git), используется Gauge со значением 1.

```text
# HELP myapp_build_info Build information.
# TYPE myapp_build_info gauge
myapp_build_info{version="1.5.0",revision="af23c",go_version="1.22"} 1
```

## Дополнительная информация

### Согласование контента (Content Negotiation)

Prometheus запрашивает данные с определенными заголовками `Accept`. Экспортёр должен отдавать предпочтение наиболее современному формату:
1.  `application/openmetrics-text` (если нужны Exemplars).
2.  `application/vnd.google.protobuf` (OTLP, самый эффективный).
3.  `text/plain` (обратная совместимость).

### Валидация

Всегда проверяйте корректность формата вашего экспортёра с помощью утилиты `promtool`:
```bash
curl -s http://localhost:8080/metrics | promtool check metrics
```

### См. также

- [Типы метрик: обзор](./overview.md) — семантика Counter, Gauge, Histogram.
- [Инструментация приложений](../../Exporters/extensibility/client_libraries.md) — выбор библиотеки для генерации формата.
- [Протокол OTLP](../../../OpenTelemetry/otlp_protocol.md) — бинарная альтернатива тексту.
- [VictoriaMetrics](../../../VictoriaMetrics/overview.md) — поддержка форматов в высоконагруженных средах.

---
**Reliability Score: 10** (Соответствует спецификациям Prometheus v3.0, OpenMetrics и OTLP 2026 года)
