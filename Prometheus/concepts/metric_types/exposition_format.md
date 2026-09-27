# Формат экспозиции метрик Prometheus

## Определения

**Формат экспозиции (Exposition Format)** — это стандарт представления метрик, предназначенный для передачи данных от экспортёров и приложений к серверу [Prometheus](../../overview.md) по протоколу HTTP.

В современной экосистеме (v3.0+) сосуществуют три спецификации:
1.  **Prometheus Text Format (v0.0.4/1.0):** Классический текстовый формат. В версии 1.0 (Prometheus v3.0+) добавлена поддержка UTF-8 через согласование параметров.
2.  **OpenMetrics (v1.0/v2.0):** Расширение текстового формата. Версия 2.0 (стандарт в Prometheus v3.0+) вводит текстовое представление нативных гистограмм и упрощенную передачу времени начала (Start Timestamps).
3.  **OTLP (OpenTelemetry Line Protocol):** Бинарный формат на базе Protobuf. В Prometheus v3.0 стал нативным протоколом для высокоэффективного приема данных (Push и Pull).

## Предварительные требования

**Версии инструментов:**
- **Prometheus Server:** v2.40+ (базовая поддержка нативных гистограмм) или **v3.0+** (полная поддержка OpenMetrics 2.0, OTLP, UTF-8).
- **Клиентские библиотеки:** `client_golang` v1.18+, `client_python` v0.16+, `simpleclient` (Java) v0.16+.
- **Экспортёры:** node_exporter, blackbox_exporter и другие должны поддерживать нужную версию формата (обычно указывается в release notes).

**Конфигурация Prometheus (v3.x) для приёма разных форматов:**

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'api-service'
    scrape_interval: 15s
    scrape_protocols:
      - OpenMetricsText
      - PrometheusText
      - Protobuf
    static_configs:
      - targets: ['app1:8080', 'app2:8080']

# Включение OTLP-приёмника (Prometheus v3.0+)
otlp:
  grpc:
    endpoint: 0.0.0.0:4317
  http:
    endpoint: 0.0.0.0:4318
```

## Основные концепции

### Структура текстового формата (OpenMetrics / Prometheus Text)

Каждая метрика должна быть описана метаданными перед выводом точек данных. Формат является строковым и разбит на строки, завершающиеся символом `\n`.

| Директива / Строка | Обязательность | Описание |
|:---|:---|:---|
| `# HELP <имя> <текст>` | Рекомендуется | Поясняет смысл метрики. Должно быть уникальным для имени метрики. |
| `# TYPE <имя> <тип>` | **Обязательно** | Типы: `counter`, `gauge`, `histogram`, `summary`, `info`, `stateset`. |
| `# UNIT <имя> <единица>` | Опционально | Единицы измерения (например, `seconds`, `bytes`). |
| `<имя>{<метки>} <значение> [<timestamp>] [st@<start_timestamp>]` | **Обязательно** | Конкретный временной ряд. `st@` — время начала (только в OM 2.0). |
| `# EOF` | Опционально | Маркер конца потока (OpenMetrics). |
| `# <комментарий>` | Опционально | Любая строка, начинающаяся с `#`, является комментарием. |

**Важно:** Имена метрик должны соответствовать регулярному выражению `[a-zA-Z_:][a-zA-Z0-9_:]*`. В Prometheus v3.0 с поддержкой UTF-8 разрешены любые символы при использовании escaping.

### Версии текстового формата

| Версия | MIME-тип | Особенности | Prometheus |
|:---|:---|:---|:---|
| **v0.0.4** | `text/plain; version=0.0.4` | Базовый текстовый формат, HELP/TYPE, без `# EOF`. | v2.x |
| **v1.0** | `text/plain; version=1.0.0` | Добавлен `# EOF`, UTF-8 через escaping. | v2.49+ |
| **OpenMetrics 1.0** | `application/openmetrics-text; version=1.0.0` | Единицы (`# UNIT`), exemplars, `_created`. | v2.x |
| **OpenMetrics 2.0** | `application/openmetrics-text; version=2.0.0` | Нативные гистограммы в тексте, `st@`, UTF-8 без ограничений. | v3.0+ |

### UTF-8 и экранирование (Prometheus v3.0)

Начиная с версии 3.0, Prometheus поддерживает **полный UTF-8** для имен метрик и меток. Это управляется через заголовок `Accept` при скрейпинге:

- **`escaping=allow-utf-8`**: Позволяет использовать любые символы (кириллица, эмодзи, точки).
- **Экранирование:** Внутри кавычек (значения меток) символы `\`, `\n` и `"` должны экранироваться (`\\`, `\n`, `\"`).
- **Legacy-режим:** Если клиент не поддерживает UTF-8, Prometheus автоматически заменяет недопустимые символы на подчеркивания (`_`).

### Нативные гистограммы в текстовом формате (OM 2.0)

В OpenMetrics 2.0 (Prometheus v3.0+) гистограммы больше не требуют множества строк `_bucket`. Они передаются одной строкой с использованием **CompositeValue**.

**Синтаксис:**
```text
http_request_duration_seconds {count:50, sum:12.5, schema:1, zero_threshold:0.001, zero_count:2, positive_spans:[0:2], positive_buckets:[15,28]} st@1723380000.000
```
- **`schema`**: Определяет ширину экспоненциальных корзин.
- **`spans` и `buckets`**: Компактное описание заполненных корзин без перечисления пустых.

### OTLP (OpenTelemetry Line Protocol)

OTLP — это бинарный протокол на базе Protocol Buffers, предназначенный для эффективной передачи телеметрии. В Prometheus v3.0 он поддерживается нативно:

| Транспорт | Порт | Описание |
|:---|:---|:---|
| **gRPC** | 4317/tcp | Бинарный транспорт HTTP/2. Предпочтителен для высоконагруженных систем благодаря streaming. |
| **HTTP/Protobuf** | 4318/tcp | Простота интеграции через стандартный HTTP. Подходит для firewall-ов, пропускающих только HTTP. |
| **HTTP/Arrow** | experimental | Использование Apache Arrow для сериализации. Максимальная производительность для batch-передач. |

OTLP передаёт метрики в формате Protobuf, где каждая метрика содержит:
- **ResourceAttributes:** атрибуты источника (hostname, service.name, region).
- **Scope:** имя библиотеки/пакета, от которой поступили метрики.
- **Metrics:** сами данные ( counters, gauges, histograms, summaries).

### Экземпляры (Exemplars)

Позволяют прикрепить к метрике ссылку на конкретное событие (например, `trace_id`), что обеспечивает корреляцию с трассировкой ([OpenTelemetry](../../../OpenTelemetry/architecture_signals.md)).

**Пример:**
```text
http_request_duration_seconds_bucket{le="0.5"} 12 # {trace_id="a1b2c3d4"} 0.452
```

### Правила парсинга и ограничения

1.  **Кодировка:** По умолчанию UTF-8. Устаревшие парсеры могут требовать ASCII.
2.  **Разделители:** Между именем метрики и метками, метками и значением должен быть ровно один пробел.
3.  **Множественные значения:** В OpenMetrics 2.0 нативная гистограмма передаётся одной строкой. В классическом формате — несколькими.
4.  **Stale markers:** Экспортёр может передать `NaN` для маркировки устаревших данных (stale). Prometheus прервёт ряд на этой точке.
5.  **Timestamp:** Если не указан, Prometheus использует время скрейпинга. Для данных из прошлого указывайте timestamp в секундах (Unix time).

### Согласование формата (Content Negotiation)

Клиент и сервер согласовывают формат через заголовки HTTP `Accept` (запрос) и `Content-Type` (ответ). Экспортер должен отдавать наиболее приоритетный поддерживаемый формат.

## Практические сценарии

### Сценарий 1: UTF-8 в именах метрик (v3.0)

При использовании `escaping=allow-utf-8` экспортер может выдавать метрики с именами, содержащими произвольные символы.

```text
# TYPE "запросы_общие_total" counter
"запросы_общие_total"{метод="GET"} 1024
```
*Примечание: В классическом формате имена с кириллицей должны быть заключены в кавычки в директивах `# TYPE` и `# HELP`.*

### Сценарий 2: Передача времени начала (Start Timestamps)

В OpenMetrics 1.0 время начала передавалось через отдельную метрику `_created`. В OM 2.0 это делается суффиксом `st@` на той же строке.

```text
# TYPE process_cpu_seconds_total counter
process_cpu_seconds_total 45.67 st@1723370000.500
```
Это критически важно для корректного вычисления `rate()` после рестартов приложения без потери точности на первом интервале.

### Сценарий 3: Гистограмма (Classic vs Native)

**Классическая гистограмма (совместимость):**
```text
http_duration_seconds_bucket{le="0.1"} 5
http_duration_seconds_sum 0.45
http_duration_seconds_count 5
```

**Нативная гистограмма (эффективность):**
```text
http_duration_seconds {count:5, sum:0.45, schema:1, positive_spans:[0:1], positive_buckets:[5]}
```

### Сценарий 4: Textfile Collector (cron-скрипты)

Для сбора метрик от кратковременных задач (бэкапы, очистка кэша) без постоянно работающего экспортёра используйте Textfile Collector:

```bash
#!/bin/bash
# /usr/local/bin/backup-metrics.sh
METRICS_FILE="/var/lib/node_exporter/textfile_collector/backup-metrics.prom"
TMP_FILE=$(mktemp)

cat > "$TMP_FILE" <<EOF
# HELP backup_last_success_timestamp_seconds Время последнего успешного бэкапа.
# TYPE backup_last_success_timestamp_seconds gauge
backup_last_success_timestamp_seconds $(date +%s)
EOF

mv "$TMP_FILE" "$METRICS_FILE"
```

Настройте cron:
```bash
# Запуск каждые 5 минут
*/5 * * * * root /usr/local/bin/backup-metrics.sh
```

Prometheus автоматически подхватит файлы с расширением `.prom` из директории `textfile_collector`.

### Сценарий 5: Создание кастомного экспортёра (Python)

Минимальный экспортёр, отдающий метрики в текстовом формате OpenMetrics:

```python
from prometheus_client import generate_latest, REGISTRY
from flask import Flask

app = Flask(__name__)

@app.route('/metrics')
def metrics():
    return generate_latest(REGISTRY), 200, {'Content-Type': 'application/openmetrics-text; version=2.0.0'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
```

### Сценарий 6: Диагностика проблем экспозиции

**Проблема:** Метрика отображается как `stale` или исчезает после рестарта.

**Диагностика:**
```bash
# 1. Проверьте, что экспортёр возвращает метрику с корректным типом
curl -s http://localhost:8080/metrics | grep '^# TYPE my_metric'
# → # TYPE my_metric counter

# 2. Проверьте наличие stale marker (NaN)
curl -s http://localhost:8080/metrics | grep 'my_metric'
# → my_metric 42
# → my_metric NaN   ← после graceful shutdown

# 3. Проверьте конфигурацию Prometheus
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="my-job")'
```

**Решение:** Убедитесь, что экспортёр корректно обрабатывает graceful shutdown и передаёт `NaN` (stale marker) для всех метрик перед выходом.

### Сценарий 7: Выбор формата через Content Negotiation

Экспортёр должен поддерживать несколько форматов и выбирать наилучший из списка, предложенного Prometheus:

```python
from flask import Flask, request

@app.route('/metrics')
def metrics():
    accept = request.headers.get('Accept', '')
    if 'application/openmetrics-text; version=2.0.0' in accept:
        content_type = 'application/openmetrics-text; version=2.0.0'
    elif 'application/openmetrics-text; version=1.0.0' in accept:
        content_type = 'application/openmetrics-text; version=1.0.0'
    elif 'text/plain; version=1.0.0' in accept:
        content_type = 'text/plain; version=1.0.0'
    else:
        content_type = 'text/plain; version=0.0.4'
    return generate_latest(REGISTRY), 200, {'Content-Type': content_type}
```

## Дополнительная информация

### Сравнение форматов

| Критерий | Prometheus Text | OpenMetrics 1.0 | OpenMetrics 2.0 | OTLP |
|:---|:---|:---|:---|:---|
| **Тип данных** | Текст | Текст | Текст | Бинарный (Protobuf) |
| **Нативные гистограммы** | Нет | Нет | Да | Да |
| **Exemplars** | Нет | Да | Да | Да |
| **UTF-8** | Ограниченно | Да | Полная | Да |
| **Сжатие** | gzip | gzip | gzip | gRPC framing / Arrow |
| **Push-модель** | Нет | Нет | Нет | Да |
| **Сложность парсинга** | Низкая | Средняя | Средняя | Высокая |
| **Производительность** | Базовая | Средняя | Средняя | Максимальная |

### Производительность и OTLP

Для высоконагруженных систем (миллионы метрик) рекомендуется использовать **OTLP (OpenTelemetry Protocol)**:
- **Бинарное сжатие:** OTLP/gRPC или OTLP/HTTP снижают нагрузку на сеть в 5–10 раз по сравнению с текстом.
- **OTLP/Arrow:** Использование Apache Arrow для передачи метрик позволяет еще сильнее оптимизировать сериализацию.

### Валидация

Проверка корректности формата с помощью `promtool`:

```bash
# 1. Проверка локального вывода
curl -s http://localhost:8080/metrics | promtool check metrics
# → SUCCESS: 15 metric families found

# 2. Проверка с учетом UTF-8
curl -H "Accept: text/plain; version=1.0.0; escaping=allow-utf-8" http://localhost:8080/metrics | promtool check metrics

# 3. Проверка конкретного файла (Textfile Collector)
promtool check metrics /var/lib/node_exporter/textfile_collector/backup-metrics.prom

# 4. Валидация PromQL-выражений и правил
promtool check rules /etc/prometheus/rules/*.yml
```

### Кардинальность и потребление ресурсов

| Формат | Сети ( Pull ) | Парсинг | Хранение в TSDB | Рекомендация |
|:---|:---|:---|:---|:---|
| **Prometheus Text 0.0.4** | Базовый | Простой | Стандартное | Legacy-системы |
| **OpenMetrics 1.0** | +5–10% | Среднее | Стандартное | v2.x |
| **OpenMetrics 2.0** | +5% | Среднее | Сжатие Native | v3.x (рекомендуется) |
| **OTLP/gRPC** | -50–70% | Сложный | Сжатие Remote Write | Высокие нагрузки |

### Типовые ошибки и устранение неполадок

1.  **Отсутствует `# TYPE`:** Prometheus не сможет определить тип метрики. Всегда добавляйте директиву для каждой метрики.
2.  **Нет пробела между именем и значением:** `http_requests_total{method="GET"}1024` — неверно. Правильно: `http_requests_total{method="GET"} 1024`.
3.  **Неэкранированные кавычки в значениях меток:** `{method="GET"}`, но не `{method="GE\"T"}` без экранирования.
4.  **Смешение Classic и Native гистограмм в одном запросе:** В Prometheus v3.0 нельзя агрегировать обычные float-метрики и нативные гистограммы вместе. Разделите запросы.
5.  **Stale markers не обрабатываются:** При graceful shutdown экспортёр должен передавать `NaN`, иначе алерты будут «висеть» на старых данных до 5 минут.
6.  **Неправильный Content-Type:** Без правильного заголовка Prometheus может не распознать формат. Используйте точные MIME-типы из таблицы.
7.  **Большие payload без сжатия:** Для текстовых форматов всегда включайте gzip на стороне экспортёра. OTLP автоматически использует сжатие gRPC.
8.  **Временные метки в будущем:** Prometheus отклоняет метрики с timestamp, превышающим `MaxAge` (обычно 10 минут в будущем). Используйте только текущее время или данные из прошлого.

### Рекомендации по настройке параметров

| Параметр | Рекомендация | Обоснование |
|:---|:---|:---|
| **scrape_interval** | 15–30 секунд | Меньше 15s создаёт избыточную нагрузку на Prometheus. |
| **scrape_timeout** | 10 секунд (по умолчанию) | Должен быть меньше `scrape_interval`. |
| **Формат по умолчанию** | OpenMetrics 2.0 | Лучшая совместимость с v3.x, UTF-8, нативные гистограммы. |
| **Escaping UTF-8** | Включить для новых сервисов | Упрощает интеграцию с OpenTelemetry. |
| **gzip** | Обязателен для текстовых форматов | Снижает трафик в 3–10 раз. |
| **Stale markers** | Обязательны для graceful shutdown | Предотвращает ложные алерты. |
| **Grace period для миграции** | ≥ 2 недель | Время для валидации дашбордов и алертов на новом формате. |

### См. также

- [Типы метрик: обзор](./overview.md) — семантика Counter, Gauge, Histogram.
- [Инструментация приложений](../../Exporters/extensibility/client_libraries.md) — библиотеки для генерации формата.
- [Протокол OTLP](../../../OpenTelemetry/otlp_protocol.md) — бинарная альтернатива тексту.
