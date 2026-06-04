# Формат экспозиции метрик Prometheus

## Определения

**Text Exposition Format** (текстовый формат экспозиции) — это стандарт представления метрик по протоколу HTTP, используемый Prometheus для сбора данных (scraping). Prometheus ожидает данные в формате обычного текста (plain text) в кодировке UTF-8. С версии 0.4.0 это единственный поддерживаемый формат (поддержка Protobuf удалена).

## Основные концепции

### Структура формата

Каждая метрика в потоке данных состоит из трех основных компонентов:

| Директива | Обязательность | Назначение |
|:---|:---|:---|
| `# HELP <имя> <описание>` | Обязательно | Описание метрики и её предназначения |
| `# TYPE <имя> <тип>` | Обязательно | Тип метрики (`counter`, `gauge`, `histogram`, `summary`, `untyped`). Должна быть объявлена до первого использования метрики |
| `<имя>{<лейблы>} <значение> [<timestamp>]` | Обязательно | Фактическое значение временного ряда |

### Правила синтаксиса

- **Имя метрики:** должно соответствовать регулярному выражению `[a-zA-Z_:][a-zA-Z0-9_:]*`.
- **Лейблы:** указываются в фигурных скобках через запятую: `{key="value",key2="value2"}`. Ключи указываются без кавычек, значения — строго в двойных кавычках.
- **Значение:** должно быть числом с плавающей точкой (float64).
- **Временная метка (Timestamp):** опционально, указывается в миллисекундах (Unix time). Не рекомендуется выставлять вручную, так как Prometheus автоматически добавляет метку времени в момент сбора (scrape).
- **Комментарии:** строки, начинающиеся с символа `#`, игнорируются парсером, за исключением служебных директив `HELP` и `TYPE`.
- **Пустые строки:** игнорируются и могут использоваться для визуального разделения групп метрик.

### Суффиксы метрик по типам

| Тип метрики | Обязательные суффиксы | Пример |
|:---|:---|:---|
| **Counter** | `_total` | `http_requests_total` |
| **Histogram** | `_bucket`, `_sum`, `_count` | `http_duration_seconds_bucket{le="0.5"}` |
| **Summary** | `_sum`, `_count`, `{quantile="..."}` | `http_duration_seconds{quantile="0.95"}` |
| **Gauge** | отсутствуют | `node_memory_mem_available_bytes` |

Подробные правила именования описаны в разделе [Расширяемость экспортеров — Концепции](../../Exporters/extensibility/concepts.md).

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

- Одна метрика может порождать несколько временных рядов в зависимости от набора лейблов.
- Каждый ряд представлен отдельной строкой.

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

- `_bucket{le="..."}` — кумулятивные корзины (less than or equal).
- `le="+Inf"` — обязательная корзина, содержащая общее количество всех наблюдений.
- `_sum` — суммарное значение всех наблюдений.
- `_count` — общее количество наблюдений (должно совпадать с корзиной `+Inf`).

### Сценарий 3: Gauge с временной меткой

```text
# HELP node_memory_mem_available_bytes Available memory in bytes.
# TYPE node_memory_mem_available_bytes gauge
node_memory_mem_available_bytes 4294967296 1395066363000
```

**Особенности:**

- Временная метка `1395066363000` указана в миллисекундах.
- Использование ручных временных меток оправдано только в специфических случаях (например, при импорте исторических данных).

### Сценарий 4: Информационная метрика (`_info`)

```text
# HELP app_version_info Application version information.
# TYPE app_version_info gauge
app_version_info{version="2.1.0",commit="abc123"} 1
```

**Особенности:**

- Паттерн `_info` используется для передачи метаданных через лейблы.
- Значение такой метрики всегда равно `1`.

## Дополнительная информация

- **Валидация:** для проверки корректности формата рекомендуется использовать утилиту [promtool](../../promtool_and_best_practices.md): `promtool check metrics <file.prom>`.
- **Textfile Collector:** позволяет собирать метрики из статических `.prom`-файлов. Подробнее в [Textfile Collector](../../Exporters/extensibility/textfile_collector.md).
- **Pushgateway:** использует тот же текстовый формат для приема метрик. См. [Pushgateway](../../pushgateway.md).
- **VictoriaMetrics:** полностью поддерживает формат экспозиции Prometheus. См. [VictoriaMetrics overview](../../../VictoriaMetrics/overview.md).
- **Связанные темы:**
  - [Процесс экспозиции](../../Exporters/overview.md) — механизмы отдачи метрик.
  - [Инструментация](../../Exporters/extensibility/client_libraries.md) — использование клиентских библиотек для формирования формата.
