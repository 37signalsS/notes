# Типы метрик в Prometheus

## Определения

**Типы метрик** в [Prometheus](./overview.md) — это классификация временных рядов по их семантике, то есть по тому, как их значения изменяются с течением времени. Prometheus выделяет четыре основных типа метрик. Правильный выбор типа является ключевым для корректного анализа данных, агрегации и построения запросов в [PromQL](./promql.md).

> **См. также:** [Лейблы и кардинальность](./labels_and_cardinality.md) — правильное использование лейблов для всех типов метрик.

## Основные концепции

### 1. Counter (Счётчик)

**Counter** — это кумулятивная метрика, значение которой может только увеличиваться или сбрасываться до нуля при перезапуске сервиса.

* **Примеры использования:**
  * Количество обработанных HTTP-запросов (`http_requests_total`).
  * Число выполненных задач.
  * Количество залогированных ошибок.
* **Особенности:**
  * Сам по себе бесполезен для анализа, так как показывает только общее накопленное значение.
  * Анализируется с помощью функций [PromQL](./promql.md), таких как `rate()` (для вычисления средней скорости в секунду) и `increase()` (для вычисления прироста за интервал).
  * По соглашению, имена счётчиков должны заканчиваться на `_total`.
* **Примеры метрик:**
  * `http_requests_total{method="POST",status="200"}`
  * `node_cpu_seconds_total{cpu="0",mode="user"}`
  * `container_cpu_usage_seconds_total{container="app"}`

**Пример PromQL для Counter:**

```promql
# Средняя скорость запросов в секунду за 5 минут
rate(http_requests_total[5m])

# Прирост запросов за последний час
increase(http_requests_total[1h])

# Количество сбросов счётчика (признак перезапуска сервиса)
resets(http_requests_total[1h])
```

### 2. Gauge (Измеритель)

**Gauge** — это метрика, которая представляет одно числовое значение, способное произвольно увеличиваться и уменьшаться.

* **Примеры использования:**
  * Текущая температура.
  * Использование памяти (`node_memory_mem_available_bytes`).
  * Количество элементов в очереди.
  * Количество активных соединений.
* **Особенности:**
  * Показывает текущее состояние "здесь и сейчас".
  * Может иметь отрицательные значения.
* **Примеры метрик:**
  * `node_memory_mem_available_bytes{instance="server-1"}`
  * `process_resident_memory_bytes{job="app"}`
  * `kube_pod_status_phase{namespace="default",phase="Running"}`

**Пример PromQL для Gauge:**

```promql
# Использование памяти в %
(1 - node_memory_mem_available_bytes / node_memory_mem_total_bytes) * 100

# Скорость изменения памяти (производная)
deriv(process_resident_memory_bytes[5m])

# Прогноз использования памяти через 4 часа
predict_linear(node_memory_mem_available_bytes[1h], 3600 * 4)
```

### 3. Histogram (Гистограмма)

**Histogram** — это метрика для отслеживания распределения наблюдаемых событий. Она группирует значения в настраиваемые корзины (buckets) и предоставляет счётчик и сумму всех наблюдений.

* **Примеры использования:**
  * Длительность ответа API (latency).
  * Размеры HTTP-запросов.
  * Время выполнения запросов к БД.
* **Особенности:**
  * Экспортирует несколько временных рядов:
    * `_bucket{le="<upper_bound>"}`: кумулятивные счётчики для каждой корзины (le = less than or equal).
    * `_sum`: общая сумма всех наблюдаемых значений.
    * `_count`: общее количество наблюдаемых событий.
  * Позволяет вычислять квантили (перцентили) на стороне сервера с помощью функции `histogram_quantile()` в PromQL. Это её ключевое преимущество.
  * Требует предварительной настройки корзин.
* **Примеры метрик:**
  * `http_request_duration_seconds_bucket{le="0.1",path="/api"}`
  * `apiserver_request_duration_seconds_bucket{le="0.5",verb="GET"}`

**Пример PromQL для Histogram:**

```promql
# 95-й перцентиль длительности запросов по всему кластеру
histogram_quantile(0.95, 
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
)

# Среднее время ответа (сумма / количество)
sum(rate(http_request_duration_seconds_sum[5m])) 
/ 
sum(rate(http_request_duration_seconds_count[5m]))

# Количество запросов медленнее 1 секунды
sum(rate(http_request_duration_seconds_bucket{le="1"}[5m]))
```

### 4. Summary (Сводка)

**Summary**, как и гистограмма, измеряет распределение. Однако она вычисляет квантили на стороне клиента (в экспортёре) и предоставляет их в готовом виде.

* **Особенности:**
  * Экспортирует временные ряды:
    * `{quantile="<φ>"}`: значение φ-квантиля.
    * `_sum`: общая сумма всех наблюдаемых значений.
    * `_count`: общее количество наблюдаемых событий.
  * **Ключевой недостаток:** квантили, рассчитанные Summary, нельзя корректно агрегировать (например, усреднять) по нескольким инстансам.
* **Примеры метрик:**
  * `grpc_server_handling_seconds{quantile="0.5",grpc_method="GetUser"}`
  * `grpc_server_handling_seconds{quantile="0.99",grpc_method="GetUser"}`

**Пример PromQL для Summary:**

```promql
# 99-й перцентиль (уже вычислен на клиенте, нельзя агрегировать)
grpc_server_handling_seconds{quantile="0.99"}

# Среднее время ответа
sum(rate(grpc_server_handling_seconds_sum[5m])) 
/ 
sum(rate(grpc_server_handling_seconds_count[5m]))
```

## Практические сценарии

### Выбор между Histogram и Summary

| Критерий | Histogram | Summary |
|---|---|---|
| **Агрегация** | **Можно** агрегировать (вычислять `rate()` и `sum()` по инстансам) | **Нельзя** корректно агрегировать квантили |
| **Вычисление квантилей** | На стороне сервера (Prometheus) через `histogram_quantile()` | На стороне клиента (экспортёр) |
| **Точность квантилей** | Приблизительная, зависит от настроек корзин | Точная, но только для одного инстанса |
| **Производительность** | Меньше нагрузка на клиент | Больше нагрузка на клиент |
| **Основной сценарий** | Анализ производительности распределённых систем (например, 95-й перцентиль latency по всему кластеру) | Мониторинг одного конкретного процесса, где агрегация не нужна |

**Рекомендация:** Для анализа задержек (latency) или размеров запросов в распределённых системах **почти всегда следует использовать Histogram**.

### Примеры алертов для разных типов метрик

**Алерт на основе Counter (доля ошибок > 5%):**

```yaml
- alert: HighErrorRate
  expr: |
    sum(rate(http_requests_total{status=~"5.."}[5m])) 
    / 
    sum(rate(http_requests_total[5m])) > 0.05
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Высокая доля ошибок HTTP 5xx"
    description: "Доля ошибок составляет {{ $value | humanizePercentage }}"
```

**Алерт на основе Gauge (мало свободной памяти):**

```yaml
- alert: LowMemory
  expr: |
    (node_memory_mem_available_bytes / node_memory_mem_total_bytes) * 100 < 10
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Мало свободной памяти на {{ $labels.instance }}"
    description: "Свободно только {{ $value | humanize }}%"
```

**Алерт на основе Histogram (медленные запросы):**

```yaml
- alert: HighLatency
  expr: |
    histogram_quantile(0.95, 
      sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
    ) > 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Высокая латентность запросов"
    description: "95-й перцентиль: {{ $value | humanizeDuration }}"
```

> **См. также:** [Rules и алертинг](../rules.md) — полное руководство по созданию правил.

## Дополнительная информация

### Формат экспозиции (Text Exposition Format)

Экспортёры предоставляют метрики по HTTP в простом текстовом формате.

* `# HELP <имя_метрики> <описание>`: Комментарий с описанием метрики.
* `# TYPE <имя_метрики> <тип>`: Директива, указывающая тип метрики (`counter`, `gauge`, `histogram`, `summary`). Эта строка должна быть объявлена до первого использования метрики.
* `<имя_метрики>{<лейблы>} <значение> [<timestamp>]`: Сам временной ряд.

```text
# HELP http_requests_total Количество HTTP-запросов.
# TYPE http_requests_total counter
http_requests_total{method="POST",code="200"} 1027 1395066363000

# HELP request_duration_seconds Латентность запросов.
# TYPE request_duration_seconds histogram
request_duration_seconds_bucket{le="0.1"} 240
request_duration_seconds_bucket{le="0.5"} 980
...
request_duration_seconds_sum 75.3
request_duration_seconds_count 1210
```

### Соглашения по именованию и лейблам

* **Имена:** `snake_case`.
* **Единицы измерения:** Имена метрик должны содержать базовые единицы (например, `_seconds`, `_bytes`).
* **Кардинальность:** Избегайте использования в лейблах значений с высокой кардинальностью (ID пользователей, хэши запросов), так как это приводит к "взрыву" количества временных рядов. Подробнее см. в [Лейблы и кардинальность](./labels_and_cardinality.md).
* **Суффиксы по типу:**
  * `_total` — для Counter (обязательно)
  * `_bucket`, `_sum`, `_count` — для Histogram
  * `_sum`, `_count`, `{quantile="..."}` — для Summary

### Инструментация приложений

Для добавления метрик в приложение используйте клиентские библиотеки:

* **Go:** `github.com/prometheus/client_golang/prometheus`
* **Python:** `prometheus_client`
* **Java:** `io.prometheus:simpleclient`
* **Node.js:** `prom-client`

> **См. также:** [Extensibility — создание собственных экспортёров](./extensibility.md) — практические примеры на Python и Go.

### Сравнение с VictoriaMetrics

VictoriaMetrics использует расширенный язык запросов [MetricsQL](../../VictoriaMetrics/overview.md), который обратно совместим с PromQL и поддерживает все типы метрик Prometheus.
