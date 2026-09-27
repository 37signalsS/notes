# Тип метрики Гистограмма (Histogram)

## Определения

**Гистограмма (Histogram)** — это тип метрики в [Prometheus](../../overview.md), предназначенный для измерения распределения наблюдаемых величин (например, длительности запросов, размеров ответов или веса сообщений).

Гистограмма группирует значения в диапазоны — **корзины (buckets)** — и предоставляет статистические данные о выборке. Это позволяет вычислять перцентили (квантили) на стороне сервера, что делает гистограммы незаменимыми для анализа «хвостов» распределения (tail latency) в распределённых системах.

В отличие от [Summary](./summary.md), гистограммы позволяют агрегировать данные от нескольких инстансов, что критично для мониторинга кластеров.

## Предварительные требования

**Версии инструментов:**
- **Prometheus Server:** v2.40+ (экспериментальная поддержка нативных гистограмм) или **v3.0+** (стабильная поддержка, рекомендуется).
- **Клиентские библиотеки:** `client_golang` v1.18+, `client_python` v0.16+, `simpleclient` (Java) v0.16+.
- **Scrape Interval:** не менее 15 секунд. Для гистограмм окно `rate(metric[5m])` требует минимум 4 точек, поэтому при `scrape_interval: 30s` минимальное окно — `[2m]`, рекомендуется `[5m]`.

**Конфигурация Prometheus (v3.x):**

```yaml
scrape_configs:
  - job_name: 'api-service'
    scrape_interval: 15s
    scrape_native_histograms: true  # Включение сбора нативных гистограмм (v3)
    static_configs:
      - targets: ['app1:8080', 'app2:8080']
```

**Требования к памяти:**
- Классическая гистограмма с 15 корзинами и 1000 инстансами создаёт ~15 000 временных рядов.
- Нативная гистограмма создаёт 1 ряд на инстанс, что снижает потребление RAM/диска на 60–80%.

## Основные концепции

### Поведение классической гистограммы (Classic Histograms)

Классическая гистограмма использует фиксированные границы корзин, заданные на этапе инструментации кода.

| Свойство | Описание |
|:---|:---|
| **Направление** | Значения в корзинах (`_bucket`), сумма (`_sum`) и количество (`_count`) являются кумулятивными счётчиками ([Counter](./counter.md)) и только растут. |
| **Сброс (Reset)** | Происходит при перезапуске приложения. Корректно обрабатывается функциями `rate()` и `increase()`. |
| **Агрегация** | Допускается суммирование корзин по инстансам (`sum by (le)`), что позволяет вычислять общие перцентили для всего сервиса или кластера. |
| **Интерполяция** | Квантили вычисляются методом линейной интерполяции между границами корзин. Точность зависит от плотности границ. |

### Структура временных рядов (Classic)

Одна классическая гистограмма порождает группу временных рядов:
- `<имя>_bucket{le="<граница>"}`: Количество событий со значением $\le$ границе.
- `<имя>_sum`: Сумма всех наблюдаемых значений.
- `<имя>_count`: Общее количество наблюдений (равно корзине `le="+Inf"`).

### Нативные гистограммы (Native Histograms / v3.0+)

Начиная с Prometheus v3.0, **нативные гистограммы** (также известные как экспоненциальные) стали стандартом для высокоточного мониторинга.

1.  **Экспоненциальная сетка:** Вместо ручного подбора корзин используется динамическая сетка, где границы корзин растут экспоненциально. Это обеспечивает фиксированную относительную погрешность (например, 1%).
2.  **Эффективность хранения:** Все корзины хранятся в **одном временном ряду** в виде компактного разреженного массива. Это радикально снижает кардинальность по сравнению с классическим подходом, где каждая корзина — отдельный ряд.
3.  **Высокая точность:** Линейная интерполяция выполняется на гораздо более узких интервалах, что почти исключает ошибку вычисления «хвостов».

### Структура нативной гистограммы

Нативная гистограмма передаётся как единый временной ряд без лейбла `le`. В текстовом формате OpenMetrics 2.0 она выглядит как строка с полями:

```text
http_request_duration_seconds{count:50, sum:12.5, schema:1, zero_threshold:0.001, zero_count:2, positive_spans:[0:2], positive_buckets:[15,28]}
```

- **`schema`**: Определяет ширину экспоненциальных корзин. Формула: `граница = 2^(n / 2^schema)`. При `schema=1` шаг удваивается каждые 2 корзины.
- **`zero_threshold` / `zero_count`**: Обработка значений около нуля (меньше порога).
- **`positive_spans` / `positive_buckets`**: Компактное описание заполненных положительных корзин. `spans` задаёт диапазоны индексов, `buckets` — количество значений в каждом диапазоне.

### Метаданные и Remote Write 2.0

В современной инфраструктуре (Prometheus 3.x) гистограммы поддерживают расширенные возможности протокола **Remote Write 2.0**:
- **Типизация:** Информация о том, что серия является гистограммой, передается нативно во внешние хранилища (Mimir, VictoriaMetrics).
- **Единицы измерения (Units):** Метаданные об единицах (например, `seconds`) сохраняются, что позволяет Grafana автоматически настраивать оси графиков.
- **UTF-8:** Поддержка UTF-8 в именах метрик позволяет нативно принимать гистограммы из OpenTelemetry (OTLP) без искажения имен.

### Критическое правило агрегации

Для всех составляющих гистограммы, являющихся счётчиками, действует строгое правило: **сначала вычисляется скорость (`rate`), затем производится агрегация (`sum`)**.

*   **ПРАВИЛЬНО:** `sum by (le) (rate(http_request_duration_seconds_bucket[5m]))`
*   **ОШИБОЧНО:** `rate(sum by (le) (http_request_duration_seconds_bucket)[5m])`

Нарушение этого порядка приведет к потере данных о сбросах счётчиков при рестартах подов, что сделает алертинг и графики недостоверными.

### Функции PromQL для гистограмм

| Функция | Назначение | Применение |
|:---|:---|:---|
| `histogram_quantile(φ, buckets)` | φ-квантиль (0 ≤ φ ≤ 1) | Классические и нативные гистограммы. Для классических требует `sum by (le)` |
| `histogram_avg(v)` | Среднее значение | Нативные гистограммы (v2.40+) |
| `histogram_sum(v)` | Сумма значений | Нативные гистограммы (v2.40+) |
| `histogram_count(v)` | Количество сэмплов | Нативные гистограммы (v2.40+) |
| `histogram_fraction(l, u, v)` | Доля сэмплов между `l` и `u` | Нативные гистограммы (v2.40+) |
| `histogram_stddev(v)` | Среднеквадратичное отклонение | Нативные гистограммы (v2.40+) |
| `histogram_stdvar(v)` | Дисперсия | Нативные гистограммы (v2.40+) |

## Формат экспозиции

### Классическая гистограмма (совместимость)

```text
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{le="0.005"} 2
http_request_duration_seconds_bucket{le="0.01"} 5
http_request_duration_seconds_bucket{le="0.025"} 12
http_request_duration_seconds_bucket{le="0.05"} 24
http_request_duration_seconds_bucket{le="0.1"} 40
http_request_duration_seconds_bucket{le="0.25"} 68
http_request_duration_seconds_bucket{le="0.5"} 85
http_request_duration_seconds_bucket{le="1.0"} 92
http_request_duration_seconds_bucket{le="2.5"} 98
http_request_duration_seconds_bucket{le="5.0"} 99
http_request_duration_seconds_bucket{le="10.0"} 100
http_request_duration_seconds_bucket{le="+Inf"} 100
http_request_duration_seconds_sum 45.2
http_request_duration_seconds_count 100
```

### Нативная гистограмма (OpenMetrics 2.0)

```text
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds{count:100, sum:45.2, schema:1, zero_threshold:0.001, zero_count:2, positive_spans:[0:4], positive_buckets:[3,8,15,20,30,25,8,1]} st@1723380000.000
```

В OpenMetrics 2.0 суффикс `st@<timestamp>` указывает время начала cumulative метрики, что критично для точного `rate()` после рестартов.

Подробнее о формате см. [Формат экспозиции](./exposition_format.md).

## Практические сценарии

### Сценарий 1: Вычисление p99 латентности (Classic)

Использование классического подхода для вычисления 99-го перцентиля.

```promql
# Вычисление p99 по всем инстансам за последние 5 минут
histogram_quantile(0.99,
  sum by (le) (rate(http_request_duration_seconds_bucket[5m]))
)
```

### Сценарий 2: Использование нативных гистограмм (v3.x)

Нативные гистограммы позволяют использовать новые функции для более глубокого анализа.

```promql
# Вычисление среднего значения из нативной гистограммы
histogram_avg(http_request_duration_seconds)

# Доля запросов, уложившихся в 500мс (SLA)
histogram_fraction(0, 0.5, http_request_duration_seconds)
```

### Сценарий 3: Расчёт среднего времени ответа (Average)

Полезно для оценки общей производительности, но скрывает "выбросы".

```promql
# Среднее = Сумма скоростей изменений / Сумма скоростей событий
sum(rate(http_request_duration_seconds_sum[5m]))
/
sum(rate(http_request_duration_seconds_count[5m]))
```

### Сценарий 4: Recording Rules для гистограмм (SLO/SLI)

Предварительный расчет перцентилей в recording rule снижает нагрузку на Prometheus и стабилизирует графики.

```yaml
groups:
  - name: api.slo.rules
    interval: 30s
    rules:
      # P99 latency для алертов и дашбордов
      - record: job:api:latency_p99
        expr: histogram_quantile(0.99,
          sum by (le, job) (rate(http_request_duration_seconds_bucket[5m]))
        )

      # Доля запросов быстрее 500мс (SLO SLI)
      - record: job:api:latency_slo_ratio
        expr: |
          histogram_fraction(0, 0.5,
            sum by (le, job) (rate(http_request_duration_seconds_bucket[5m]))
          )

      # Средняя латентность (нативная гистограмма)
      - record: job:api:latency_avg
        expr: histogram_avg(http_request_duration_seconds)
```

Затем в Grafana и алертах используются простые запросы:
```promql
job:api:latency_p99 > 0.2  # Превoshenие 200мс
job:api:latency_slo_ratio < 0.95  # Нарушение SLO
```

### Сценарий 5: Валидация инструментации через promtool

Перед деплоем в продакшен проверьте корректность формата экспозиции:

```bash
# 1. Проверка формата экспозиции
curl -s http://localhost:8080/metrics | promtool check metrics
# → SUCCESS: 15 metric families found

# 2. Проверка с поддержкой UTF-8 (если используете не-ASCII имена)
curl -H "Accept: text/plain; version=1.0.0; escaping=allow-utf-8" \
  http://localhost:8080/metrics | promtool check metrics

# 3. Проверка правил алертинга и recording rules
promtool check rules /etc/prometheus/rules/*.yml
# → SUCCESS: 12 rules found

# 4. Модульное тестирование алертов
promtool test rules /etc/prometheus/tests/histogram_alerts.yml
```

### Сценарий 6: Миграция с Classic на Native Histogram (v3.x)

Переход на нативные гистограммы требует изменения как кода приложения, так и запросов PromQL.

**Шаг 1. Включите нативные гистограммы в Prometheus:**

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'api-service'
    scrape_interval: 15s
    scrape_native_histograms: true
```

**Шаг 2. Дублируйте метрику на переходный период (Go):**

```go
// Классическая гистограмма (LEGACY) — оставьте для совместимости
var legacyHistogram = promauto.NewHistogram(prometheus.HistogramOpts{
    Name:    "http_request_duration_seconds_classic",
    Help:    "Duration of HTTP requests (Classic Histogram).",
    Buckets: prometheus.ExponentialBuckets(0.001, 2, 10),
})

// Нативная гистограмма (РЕКОМЕНДУЕТСЯ) — основной вариант
var nativeHistogram = promauto.NewHistogram(prometheus.HistogramOpts{
    Name:                            "http_request_duration_seconds",
    Help:                            "Duration of HTTP requests (Native Histogram).",
    NativeHistogramBucketFactor:     1.1,  # Относительная погрешность ~10%
    NativeHistogramMaxBucketNumber:  100,  # Максимум корзин (минимум 0)
})
```

**Шаг 3. Обновите запросы в дашбордах:**

```promql
# Было (Classic):
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))

# Стало (Native):
histogram_quantile(0.99, rate(http_request_duration_seconds[5m]))
# или для доли:
histogram_fraction(0, 0.5, rate(http_request_duration_seconds[5m]))
```

**Шаг 4. Валидируйте миграцию:**

```bash
# Проверьте, что нативные гистограммы собираются
curl -s http://localhost:9090/api/v1/query?query=http_request_duration_seconds | jq '.data.result[].metric'

# Убедитесь, что запрос histogram_quantile возвращает результаты без ошибок
curl -s "http://localhost:9090/api/v1/query?query=histogram_quantile(0.99,rate(http_request_duration_seconds[5m]))" | jq '.data.result'
```

**Шаг 5. Удалите старую метрику после подтверждения работоспособности ( grace period ≥ 2 недель).**

### Сценарий 7: SLO/SLI на основе гистограмм

Пример полного цикла SLO: 99% запросов выполняются быстрее 500мс.

```yaml
# Recording rule: SLI (Service Level Indicator)
groups:
  - name: api.slo
    interval: 30s
    rules:
      - record: job:api:sli_latency
        expr: histogram_fraction(0, 0.5,
          sum by (le, job) (rate(http_request_duration_seconds_bucket[5m]))
        )

# Alerting rule: Error Budget Burn Rate
      - alert: APIHighLatencyErrorBudgetBurn
        expr: |
          (
            job:api:sli_latency < 0.99
          ) and (
            (
              job:api:sli_latency < 0.99
            ) for (1h > 0)
          )
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Error Budget сжигается ({{ $value | humanizePercentage }})"
          description: "SLO 99% < 500мс нарушается. Проверьте производительность {{ $labels.job }}."
```

### Сценарий 8: Диагностика распределения через Heatmap

Для визуализации всех корзин одновременно используйте Heatmap в Grafana:

```promql
# Classic Histogram — все корзины для Heatmap
sum by (le, instance) (rate(http_request_duration_seconds_bucket[5m]))

# Native Histogram — автоматическое преобразование в heatmap
rate(http_request_duration_seconds[5m])
```

Heatmap показывает бимодальные распределения (два пика задержек), которые перцентили могут маскировать.

## Инструментация

### Go

```go
package main

import (
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
    "time"
)

// Нативная гистограмма (РЕКОМЕНДУЕТСЯ для Prometheus v3.0+)
var requestDuration = promauto.NewHistogram(prometheus.HistogramOpts{
    Name:                            "http_request_duration_seconds",
    Help:                            "Длительность HTTP-запросов в секундах (Native Histogram).",
    NativeHistogramBucketFactor:     1.1,   # Относительная погрешность ~10%
    NativeHistogramMaxBucketNumber:  100,   # Максимум корзин (0 = без ограничений)
    NativeHistogramMinResetDuration: 1 * time.Hour,
    Buckets:                         prometheus.ExponentialBuckets(0.001, 2, 10), # Для классического режима
})

// Классическая гистограмма (LEGACY)
var legacyRequestDuration = promauto.NewHistogram(prometheus.HistogramOpts{
    Name:    "http_request_duration_seconds_classic",
    Help:    "Длительность HTTP-запросов в секундах (Classic Histogram).",
    Buckets: prometheus.ExponentialBuckets(0.001, 2, 10),
})

func handler(w http.ResponseWriter, r *http.Request) {
    start := time.Now()
    // ... обработка запроса
    duration := time.Since(start)
    requestDuration.Observe(duration.Seconds())
    legacyRequestDuration.Observe(duration.Seconds())
}
```

### Python

```python
from prometheus_client import Histogram, start_http_server

# Нативная гистограмма (РЕКОМЕНДУЕТСЯ)
request_duration = Histogram(
    'http_request_duration_seconds',
    'Длительность HTTP-запросов в секундах (Native Histogram).',
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

@app.route('/api/data')
def get_data():
    with request_duration.time():
        # ... обработка запроса
        pass
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    start_http_server(8080)
    app.run()
```

### Java (Micrometer + Prometheus)

```yaml
# application.yml
management:
  metrics:
    distribution:
      percentiles-histogram:
        http.server.requests: true
      percentiles:
        http.server.requests: 0.95, 0.99
```

```xml
<!-- pom.xml -->
<dependency>
    <groupId>io.micrometer</groupId>
    <artifactId>micrometer-registry-prometheus</artifactId>
    <version>1.13.0</version>
</dependency>
```

## Дополнительная информация

### Сравнение с типом Summary

| Критерий | Гистограмма (Histogram) | Сводка (Summary) |
|:---|:---|:---|
| **Агрегируемость** | Полная (по кластеру/сервису) | Нет (только по инстансу) |
| **Нагрузка на клиент** | Низкая (только инкремент) | Высокая (вычисление квантилей в RAM) |
| **Точность** | Зависит от сетки корзин (Classic) или относительной погрешности (Native) | Очень высокая (фиксированная, задаётся `Objectives`) |
| **Поддержка v3.0** | Native Histograms (рекомендуется) | Legacy-поддержка |
| **Кардинальность** | Средняя/Высокая (Classic), Низкая (Native) | Низкая |

### Кардинальность и потребление ресурсов

| Тип гистограммы | Временные ряды на одну метрику | Потребление RAM | Потребление диска | Рекомендация |
|:---|:---|:---|:---|:---|
| **Classic (15 buckets)** | 15 + 2 = 17 | Среднее | Среднее | Только для совместимости |
| **Native (v3.0)** | 1 | Минимальное | Минимальное | Стандарт для новых сервисов |
| **Summary** | 1 + N_quantiles | Высокое | Высокое | Только для single-instance |

### Типовые ошибки и устранение неполадок

1.  **Недостаточная плотность корзин:** Слишком широкие корзины (например, 100мс и 1с) приводят к большой ошибке интерполяции.
2.  **Забытый лейбл `le`:** При агрегации классических гистограмм через `sum by (...)` отсутствие `le` в списке группировки сломает функцию `histogram_quantile`.
3.  **Использование для редких событий:** Если за интервал `rate` попадает меньше 2-3 событий, вычисление квантилей становится статистически недостоверным.
4.  **Ошибка порядка `rate()` и `sum()`:** `rate(sum by (le) (...)[5m])` — неверно. Всегда сначала `sum by (le) (rate(...))`.
5.  **Слишком много корзин:** >20 корзин при высокой кардинальности лейблов приводят к OOM на Prometheus. Используйте 10–15 корзин или переходите на Native Histograms.
6.  **Отсутствие `+Inf` корзины:** Без корзины `le="+Inf"` `histogram_quantile` не сможет вычислить квантиль, если значение превышает максимальную границу.
7.  **Смешение Classic и Native в одном запросе:** В Prometheus v3.0 нельзя смешивать обычные float-метрики и нативные гистограммы в одной группе агрегации (`sum by (...)`). Разделите запросы.
8.  **Игнорирование stale markers:** При graceful shutdown экспортёр должен передавать `NaN` (stale marker), иначе алерты будут «висеть» на старых данных до 5 минут.

### Рекомендации по настройке параметров

| Параметр | Рекомендация | Обоснование |
|:---|:---|:---|
| **scrape_interval** | 15–30 секунд | Меньше 15s создаёт избыточную нагрузку на Prometheus. |
| **Количество корзин (Classic)** | 10–15 | Баланс между точностью и кардинальностью. |
| **Диапазон корзин** | От 1ms до 10s для latency | Охватывает 99.9% запросов в веб-сервисах. |
| **NativeHistogramBucketFactor** | 1.1–1.2 (10–20% погрешность) | Меньший factor → больше корзин → выше точность, но больше RAM. |
| **NativeHistogramMaxBucketNumber** | 100–200 | Ограничение на максимальное количество корзин для защиты от OOM. |
| **Окно rate()** | `[5m]` при `scrape_interval: 15s` | Минимум 4× scrape_interval. |
| **Grace period для миграции** | ≥ 2 недель | Время для валидации дашбордов и алертов на новой метрике. |

### См. также

- [Функции PromQL](../promql/functions.md) — справочник по `histogram_quantile`, `histogram_avg`, `histogram_fraction`.
- [Перцентили и квантили](./percentiles.md) — математические основы распределений.
- [Примеры алертов](./alerts.md) — настройка оповещений по Latency.
- [Формат экспозиции](./exposition_format.md) — технические детали передачи данных по HTTP.
- [Удаленная запись (Remote Write 2.0)](../../scaling/remote_read_write.md) — передача метаданных типов.
- [Правила Prometheus](../../rules.md) — recording rules и алертинг.
- [Метаданные и кардинальность](../labels_and_cardinality.md) — управление сериями в TSDB.
- [Exemplars](../exemplars.md) — связь гистограмм с трейсами через exemplars.
