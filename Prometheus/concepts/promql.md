# Язык запросов PromQL

## Определения

**PromQL (Prometheus Query Language)** — это мощный **функциональный язык запросов**, разработанный для работы с многомерными данными временных рядов в [Prometheus](./overview.md). В отличие от SQL, он оптимизирован для вычислений и агрегаций над временными рядами. PromQL позволяет выбирать и агрегировать данные в реальном времени, результаты чего могут быть отображены в [Grafana](../../Grafana/grafana_overview.md), таблицах или использованы внешними системами через [HTTP API](../prometheus_api.md).

> **См. также:** [Типы метрик](./metric_types.md) — counter, gauge, histogram, summary.

### Типы данных

PromQL оперирует четырьмя основными типами данных:

* **Instant vector (вектор мгновенных значений)**: Набор временных рядов, где для каждого ряда есть только одна точка данных (последняя). Это самый частый результат запроса.
* **Range vector (вектор диапазона значений)**: Набор временных рядов, где для каждого ряда сохранен диапазон точек данных за определенный промежуток времени.
* **Scalar (скаляр)**: Простое числовое значение с плавающей точкой.
* **String (строка)**: Строковое значение (в настоящее время в PromQL напрямую не используется).

## Основные концепции

### Селекторы и Матчеры

Селекторы используются для выбора временных рядов на основе имени метрики и [лейблов](./labels_and_cardinality.md).

* **Вектор мгновенных значений (Instant Vector)**: `node_memory_mem_available_bytes{job="node-exporter"}`
* **Вектор диапазона значений (Range Vector)**: `node_network_receive_bytes_total[5m]`
  * *Единицы времени:* `s`, `m`, `h`, `d`, `w`, `y`.
  * Векторы диапазона нельзя напрямую отобразить на графике, они используются в функциях, таких как `rate()`.

Для фильтрации по лейблам внутри селектора (`{...}`) используются **матчеры**:

* `=`: Точное равенство.
* `!=`: Неравенство.
* `=~`: Соответствие регулярному выражению.
* `!~`: Несоответствие регулярному выражению.

*Пример:* `http_requests_total{job=~"api-server|web-server", method!="GET"}`

### Модификаторы времени

* `offset <duration>`: Позволяет получить данные из прошлого. `sum(http_requests_total) offset 1d`
* `@ <timestamp>`: Позволяет указать точное время для выполнения запроса. `node_memory_MemAvailable_bytes @ 1609459200`

### Операторы

#### Математические операторы

`+`, `-`, `*`, `/`, `%`, `^`. Применяются к скалярам и векторам.

#### Операторы сравнения

`==`, `!=`, `>`, `<`, `>=`, `<=`. Применяются к скалярам и векторам. С модификатором `bool` возвращают `0` или `1`.

*Пример:* `node_cpu_seconds_total > bool 3`

#### Логические операторы (только для `instant vector`)

* `and` (И): Элементы `vector1`, для которых есть элементы в `vector2` с тем же набором меток.
* `or` (ИЛИ): Все элементы `vector1` плюс уникальные элементы `vector2`.
* `unless` (ИСКЛЮЧАЯ): Элементы `vector1`, для которых нет совпадений в `vector2`.

## Практические сценарии

### Операторы агрегации

Позволяют агрегировать данные по нескольким временным рядам. Используются с `by` (группировка по лейблам) или `without` (исключение лейблов из группировки).

* `sum()`: сумма значений.
* `avg()`: среднее значение.
* `count()`: количество временных рядов.
* `min()`, `max()`: минимальное и максимальное значения.
* `stddev()`, `stdvar()`: стандартное отклонение и дисперсия.
* `topk(k, ...)` / `bottomk(k, ...)`: `k` наибольших/наименьших значений.
* `count_values("label", ...)`: количество элементов с одинаковым значением лейбла.
* `quantile(φ, ...)`: φ-квантиль (0 ≤ φ ≤ 1).

*Пример:* `sum by (path) (http_requests_total)` — сумма запросов для каждого `path`.

### Функции

PromQL имеет большой набор функций, которые можно разделить по типам метрик, с которыми они работают. Подробнее о типах метрик см. в **[Типы метрик в Prometheus](./metric_types.md)**.

#### Функции для счётчиков (Counters)

* `rate(v range-vector)`: **Средняя скорость** увеличения в секунду. Учитывает сбросы счётчика.
  * `rate(node_network_receive_bytes_total[5m])`
* `irate(v range-vector)`: **Мгновенная скорость** увеличения (использует две последние точки). Чувствителен к скачкам.
* `increase(v range-vector)`: Абсолютный прирост за диапазон.
* `resets(v range-vector)`: Количество сбросов счётчика.

#### Функции для измерителей (Gauges)

* `changes(v range-vector)`: Количество изменений значения.
* `deriv(v range-vector)`: Производная (скорость изменения) с использованием линейной регрессии.
* `predict_linear(v range-vector, t scalar)`: Прогнозирует значение через `t` секунд. Полезно для [алертинга](../rules.md).
  * `predict_linear(node_filesystem_free_bytes[1h], 3600 * 4) < 0` — прогноз нехватки места на диске через 4 часа.
* `delta(v range-vector)`: Разница между началом и концом диапазона.

#### Функции для гистограмм (Histograms)

* `histogram_quantile(φ float, b histogram)`: Вычисляет φ-квантиль (0 ≤ φ ≤ 1). Это основной способ использования гистограмм для расчета перцентилей.
  * `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))`

### Агрегация по времени (`..._over_time`)

Эти функции агрегируют значения *каждого* временного ряда в диапазоне и возвращают мгновенный вектор.

* `avg_over_time(v range-vector)`: Скользящее среднее.
* `max_over_time()`, `min_over_time()`, `sum_over_time()`, и др.
* `count_over_time()`: Количество точек в диапазоне.
* `first_over_time()`, `last_over_time()`: Первое/последнее значение.
* `stddev_over_time()`, `stdvar_over_time()`: Стандартное отклонение/дисперсия.
* `quantile_over_time(φ, v range-vector)`: φ-квантиль в диапазоне.

### Шаблоны выражений

#### Мониторинг инфраструктуры

* **Утилизация CPU по instance (в %):**

    ```promql
    avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100
    ```

* **Использование памяти (в %):**

    ```promql
    (1 - node_memory_mem_available_bytes / node_memory_mem_total_bytes) * 100
    ```

* **Использование диска (в %):**

    ```promql
    (1 - node_filesystem_avail_bytes / node_filesystem_size_bytes) * 100
    ```

* **Входящий сетевой трафик (байт/сек):**

    ```promql
    rate(node_network_receive_bytes_total[5m])
    ```

#### Мониторинг приложений

* **Доля ошибок HTTP 5xx:**

    ```promql
    sum(rate(http_requests_total{code=~"5.."}[5m]))
    /
    sum(rate(http_requests_total[5m]))
    ```

* **95-й перцентиль времени ответа:**

    ```promql
    histogram_quantile(0.95, 
      sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
    )
    ```

* **RPS (запросов в секунду):**

    ```promql
    sum(rate(http_requests_total[5m]))
    ```

#### Мониторинг Kubernetes

* **Количество подов в состоянии Running:**

    ```promql
    sum(kube_pod_status_phase{phase="Running"})
    ```

* **Использование CPU контейнером (в ядрах):**

    ```promql
    rate(container_cpu_usage_seconds_total[5m])
    ```

* **Использование памяти контейнером:**

    ```promql
    container_memory_usage_bytes
    ```

#### Алертинг

* **Проверка отсутствия метрики (для алертинга):**

    ```promql
    absent(up{job="my-critical-service"})
    ```

* **Сервис недоступен:**

    ```promql
    up{job="api-server"} == 0
    ```

* **Прогноз нехватки диска через 4 часа:**

    ```promql
    predict_linear(node_filesystem_free_bytes[1h], 3600 * 4) < 0
    ```

* **Высокая загрузка CPU (>80% в течение 10 минут):**

    ```promql
    avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100 < 20
    ```

> **См. также:** [Rules и алертинг](../rules.md) — создание правил для Alertmanager.

## Дополнительная информация

### Сопоставление векторов

PromQL позволяет производить операции между векторами.

* **Один к одному (One-to-one)**: Операция выполняется между элементами с идентичными наборами лейблов.
* **Многие к одному (Many-to-one)**: Используются ключевые слова `group_left` или `group_right` для указания "главного" вектора, чьи лейблы сохранятся в результате.
* **Фильтрация сопоставления**:
  * `on(<label_list>)`: Указывает, по каким лейблам сопоставлять векторы.
  * `ignoring(<label_list>)`: Указывает, какие лейблы игнорировать при сопоставлении.

**Пример many-to-one с group_left:**

```promql
# Добавляем лейбл job из метрики up к метрике node_cpu_seconds_total
node_cpu_seconds_total * group_left(job) up
```

### Функции для работы с метками (Labels)

* `label_replace(v, dst_label, replacement, src_label, regex)`: Создает новую метку `dst_label` на основе `regex`, примененного к `src_label`.
* `label_join(v, dst_label, separator, src_label_1, ...)`: Объединяет значения нескольких меток в одну.

**Пример label_replace (шаблонизация URL):**

```promql
# Преобразуем /api/users/123 в /api/users/:id
label_replace(
  http_requests_total,
  "templated_path",
  "/api/users/:id",
  "path",
  "/api/users/[^/]+"
)
```

### Прочие функции

* `absent()`: Возвращает `1`, если переданный вектор пуст, иначе — пустой результат.
* `sort()` / `sort_desc()`: Сортировка вектора по значению.
* `round()`, `ceil()`, `floor()`: Функции округления.
* `time()`: Возвращает текущее время в формате Unix time.
* `holt_winters()`: Реализует двойное экспоненциальное сглаживание для прогнозирования и очистки данных от шума.
* `clamp(v, min, max)`: Ограничивает значение в диапазоне.
* `clamp_max(v, max)` / `clamp_min(v, min)`: Ограничивает значение максимумом/минимумом.

### Subqueries (подзапросы)

Subqueries позволяют применять функции диапазона к функциям instant vector:

```promql
# Среднее значение rate за последний час с шагом 5 минут
avg_over_time(rate(http_requests_total[5m])[1h:5m])

# Максимум 95-го перцентиля за день
max_over_time(
  histogram_quantile(0.95, sum(rate(http_duration_bucket[5m])) by (le))[1d:1h]
)
```

### Связанные темы

* [Типы метрик](./metric_types.md) — counter, gauge, histogram, summary
* [Лейблы и кардинальность](./labels_and_cardinality.md) — правильное использование лейблов
* [TSDB](./tsdb.md) — хранение временных рядов
* [Rules](../rules.md) — создание правил алертинга
* [Prometheus API](../prometheus_api.md) — выполнение запросов через API
* [Grafana](../../Grafana/grafana_overview.md) — визуализация результатов запросов
