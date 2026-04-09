# Формат экспозиции метрик Prometheus (Text Exposition Format)

## Определения

**Text Exposition Format** — текстовый формат предоставления метрик по HTTP, используемый Prometheus для сбора данных (scraping). Prometheus ожидает plain text в кодировке UTF-8 — это единственный поддерживаемый формат с версии 0.4.0 (Protobuf удалён).

> **См. также:** [Процесс экспозиции](../../Exporters/overview.md) — как экспортеры отдают метрики, [Инструментация](../../Exporters/extensibility/client_libraries.md) — клиентские библиотеки для генерации формата.

## Основные концепции

### Структура формата

Каждая метрика в формате состоит из трёх компонентов:

| Директива | Обязательность | Назначение |
|---|---|---|
| `# HELP <имя> <описание>` | Обязательно | Документирование метрики |
| `# TYPE <имя> <тип>` | Обязательно | Тип метрики (`counter`, `gauge`, `histogram`, `summary`, `untyped`). Объявляется **до первого использования** |
| `<имя>{<лейблы>} <значение> [<timestamp>]` | Обязательно | Сам временной ряд |

### Правила синтаксиса

- **Имя метрики:** `[a-zA-Z_:][a-zA-Z0-9_:]*` (regex)
- **Лейблы:** `{key="value",key2="value2"}` — ключи без кавычек, значения в двойных кавычках
- **Значение:** число с плавающей точкой
- **Timestamp:** опционально, в миллисекундах (Unix time). **Не рекомендуется** выставлять вручную — Prometheus добавляет timestamp при scrape
- **Комментарии:** строки, начинающиеся с `#`, игнорируются парсером (кроме `# HELP` и `# TYPE`)
- **Пустые строки:** игнорируются, используются для визуального разделения метрик

### Суффиксы метрик по типам

| Тип метрики | Обязательные суффиксы | Пример |
|---|---|---|
| **Counter** | `_total` | `http_requests_total` |
| **Histogram** | `_bucket`, `_sum`, `_count` | `http_duration_seconds_bucket{le="0.5"}` |
| **Summary** | `_sum`, `_count`, `{quantile="..."}` | `http_duration_seconds{quantile="0.95"}` |
| **Gauge** | Нет | `node_memory_mem_available_bytes` |

> Правила именования метрик и лейблов см. в [Расширяемость экспортеров — Концепции](../../Exporters/extensibility/concepts.md).

## Практические сценарии

### Сценарий 1: Counter в формате экспозиции

```text
# HELP http_requests_total Total number of HTTP requests.
# TYPE http_requests_total counter
http_requests_total{method="GET",status="200"} 1523
http_requests_total{method="POST",status="201"} 87
http_requests_total{method="GET",status="500"} 3
```

**Особенности:**
- Одна метрика = несколько временных рядов (комбинации лейблов)
- Каждый ряд — отдельная строка с уникальным набором лейблов

### Сценарий 2: Histogram в формате экспозиции

```text
# HELP http_request_duration_seconds HTTP request latency in seconds.
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{le="0.1"} 240
http_request_duration_seconds_bucket{le="0.5"} 980
http_request_duration_seconds_bucket{le="1.0"} 1200
http_request_duration_seconds_bucket{le="+Inf"} 1250
http_request_duration_seconds_sum 75.3
http_request_duration_seconds_count 1250
```

**Особенности:**
- `_bucket{le="..."}` — кумулятивные корзины (less than or equal)
- `le="+Inf"` — обязательная корзина, содержит общее количество наблюдений
- `_sum` — сумма всех наблюдаемых значений (для вычисления среднего)
- `_count` — общее количество наблюдений (должно совпадать с `le="+Inf"`)

### Сценарий 3: Gauge с временной меткой

```text
# HELP node_memory_mem_available_bytes Available memory in bytes.
# TYPE node_memory_mem_available_bytes gauge
node_memory_mem_available_bytes 4294967296 1395066363000
```

**Особенности:**
- Timestamp `1395066363000` — Unix time в миллисекундах
- На практике экспортеры **не выставляют** timestamp — Prometheus добавляет его при scrape

### Сценарий 4: Специальная метрика `_info`

```text
# HELP app_version_info Application version information.
# TYPE app_version_info gauge
app_version_info{version="2.1.0",commit="abc123"} 1
```

**Особенности:**
- Паттерн `_info` — информационная метрика со статичными лейблами
- Значение всегда `1`, полезная нагрузка — в лейблах
- Используется для enrich-дашбордов (версия, окружение, билд)

## Дополнительная информация

- **Protobuf формат:** Удалён в версии 0.4.0 (2015). Актуальные версии Prometheus поддерживают только text format.
- **Валидация:** Используйте [promtool](../../promtool_and_best_practices.md) для проверки корректности формата: `promtool check metrics <file.prom>`
- **Textfile Collector:** Альтернативный способ отдачи метрик через `.prom`-файлы без написания кода. См. [Textfile Collector](../../Exporters/extensibility/textfile_collector.md).
- **Pushgateway:** Принимает метрики в том же формате через HTTP PUT/POST. См. [Pushgateway](../../pushgateway.md).
- **VictoriaMetrics:** Совместима с форматом экспозиции Prometheus и поддерживает PromQL/MetricsQL. См. [VictoriaMetrics overview](../../../VictoriaMetrics/overview.md).
