# Диагностика и отладка PromQL-запросов

## Определения

**Диагностика PromQL** — пошаговый процесс выявления причин некорректного поведения запроса: пустого результата, ложных срабатываний алертов, аномальных значений на графиках или ошибок выполнения. В отличие от [типовых ошибок](./selectors_operators.md#типовые-ошибки-селекторов-и-диагностика), этот файл описывает системный подход к отладке, а не отдельные ошибки.

**Отладочный запрос (Debug Query)** — упрощённое выражение PromQL, используемое для изолированной проверки отдельного компонента сложного выражения. Принцип: разбей сложный запрос на простые части и проверяй каждую по отдельности.

## Базовые концепции

### Пошаговый алгоритм диагностики

При столкновении с проблемой следуйте алгоритму из 6 шагов:

#### Шаг 1: Проверьте наличие данных

Прежде чем искать ошибку в PromQL, убедитесь, что данные вообще есть в TSDB:

```promql
# Есть ли метрика?
count(http_requests_total)
# → 1523 (если > 0 — данные есть)

# Есть ли данные за нужный интервал?
count_over_time(http_requests_total[5m])
# → 1523 (если > 0 — данные есть за 5 минут)

# Есть ли данные для конкретного селектора?
up{job="api-server"}
# → {instance="10.0.0.1:8080", job="api-server"} 1
```

**Если данные отсутствуют:**
- Проверьте targets: `up{job="..."}` — если `0`, сервис не доступен
- Проверьте scrape interval: `prometheus_tsdb_head_samples_appended_total` растёт?
- Проверьте конфигурацию сбора: `prometheus_config_last_reload_successful == 1`

#### Шаг 2: Проверьте тип результата

PromQL возвращает разные типы, и функции ожидают определённый тип:

| Ошибка | Значит | Решение |
|:---|:---|:---|
| `expected type range vector` | Функция получила instant vector | Добавьте `[5m]` к селектору |
| `expected type instant vector` | Функция получила range vector | Оберните в функцию: `rate(metric[5m])` |
| `vector cannot contain metrics with the same labelset` | Дубликаты лейблов после `on`/`ignoring` | Агрегируйте или добавьте уникальный лейбл |

**Быстрая проверка типа:**
```promql
# Instant vector? Должен вернуть значение
up{job="api"}

# Range vector? Должен вернуть ошибку без функции
# up{job="api"}[5m]  ← нельзя отобразить на графике

# Scalar? Должен вернуть одно число без лейблов
count(up)
```

#### Шаг 3: Изолируйте проблемный компонент

Разбейте сложное выражение на части. Пример:

**Проблемный запрос:**
```promql
sum by (job) (rate(http_requests_total{status=~"5.."}[5m]))
/
sum by (job) (rate(http_requests_total[5m])) > 0.05
```

**Диагностика по частям:**
```promql
# 1. Проверяем числитель (ошибки)
sum by (job) (rate(http_requests_total{status=~"5.."}[5m]))
# → {job="api"} 2.5

# 2. Проверяем знаменатель (все запросы)
sum by (job) (rate(http_requests_total[5m]))
# → {job="api"} 150.0

# 3. Проверяем деление
sum by (job) (rate(http_requests_total{status=~"5.."}[5m]))
/
sum by (job) (rate(http_requests_total[5m]))
# → {job="api"} 0.0167

# 4. Проверяем порог
sum by (job) (rate(http_requests_total{status=~"5.."}[5m]))
/
sum by (job) (rate(http_requests_total[5m])) > 0.05
# → (пустой результат — условие не выполнено)
```

#### Шаг 4: Проверьте лейблы

Частая причина пустых результатов — несовпадение лейблов при бинарных операциях:

```promql
# Проблема: два вектора не совпадают по лейблам
# Вектор A: {job="api", instance="host1"}
# Вектор B: {job="api", instance="host1", method="GET"}

# Решение: использовать on() для игнорирования лишних лейблов
vector_a / on(job) vector_b

# Или ignoring() для исключения мешающих лейблов
vector_a * ignoring(method) vector_b
```

**Визуальная проверка лейблов:**
```promql
# Посмотрите, какие лейблы у результата
label_join(
  sum by (job) (rate(http_requests_total[5m])),
  "all_labels", ",",
  "job", "instance"
)
# → {job="api", instance="host1", all_labels="api,host1"}
```

#### Шаг 5: Проверьте время и окна

```promql
# Правило 4 точек: в окне rate() должно быть минимум 4 точки
# При scrape_interval=15s: минимальное окно = 1m
# При scrape_interval=30s: минимальное окно = 2m

# Проверка количества точек в окне
count_over_time(http_requests_total[5m])
# → 20 (нормально, при 15s interval это 20 точек за 5 минут)

# Проверка свежести данных
time() - timestamp(http_requests_total)
# → {instance="host1"} 12.5 (данные 12.5 секунд назад — нормально)
```

#### Шаг 6: Проверьте экстраполяцию и float64

```promql
# Проблема: increase() возвращает дробное число
increase(http_requests_total[5m])
# → 4.28 (ожидается целое)

# Это нормально — экстраполяция. Не используйте == 1
# ПРАВИЛЬНО:
increase(http_requests_total[5m]) >= 1
# или
rate(http_requests_total[5m]) > 0

# Проблема: сравнение float64 с точным значением
node_load1 == 0.85
# → может не сработать из-за погрешности

# РЕШЕНИЕ:
abs(node_load1 - 0.85) < 0.001
```

### Типичные паттерны диагностики

#### Пустой результат запроса

| Шаг | Проверка | Команда |
|:---|:---|:---|
| 1 | Метрика существует? | `count(metric_name)` |
| 2 | Есть данные за окно? | `count_over_time(metric_name[5m])` |
| 3 | Лейблы совпадают? | `metric_name{label="value"}` |
| 4 | Функция получает правильный тип? | Проверьте синтаксис |
| 5 | Данные свежие? | `time() - timestamp(metric_name)` |

#### Ложные срабатывания алертов

| Шаг | Проверка | Команда |
|:---|:---|:---|
| 1 | Есть ли шум в данных? | Постройте график `rate()` с разными окнами |
| 2 | Достаточно ли `for`? | Увеличьте до 3-5x `scrape_interval` |
| 3 | Не используется ли `irate()`? | Замените на `rate()` |
| 4 | Есть ли дребезг (flapping)? | `changes(metric[1h]) > 10` |

#### Аномальные значения на графике

| Шаг | Проверка | Команда |
|:---|:---|:---|
| 1 | Есть ли сбросы счётчиков? | `resets(metric[1h]) > 0` |
| 2 | Не смешаны ли типы? | Проверьте, что `float` и `histogram` не в одной агрегации |
| 3 | Корректно ли окно `rate()`? | `count_over_time(metric[5m])` — минимум 4 точки |
| 4 | Не влияет ли `offset`? | Уберите `offset` и сравните результат |

### Инструменты отладки

#### Prometheus Web UI

```
http://localhost:9090/graph
```

- **Graph**: визуализация instant/range запросов
- **Table**: табличный вывод instant запросов
- **Debug**: расширенный вывод (в Prometheus v3.0+)

#### promtool query

```bash
# Instant query
promtool query instant http://localhost:9090 'rate(http_requests_total[5m])'

# Range query
promtool query range http://localhost:9090 'rate(http_requests_total[5m])' \
  --start=2026-01-01T00:00:00Z --end=2026-01-01T01:00:00Z --step=1m

# Compare two queries
promtool query diff http://localhost:9090 \
  'rate(http_requests_total[5m])' \
  'rate(http_requests_total[10m])'
```

#### HTTP API

```bash
# Instant query
curl -s 'http://localhost:9090/api/v1/query?query=up' | jq .

# Range query
curl -s 'http://localhost:9090/api/v1/query_range?query=rate(http_requests_total[5m])&start=2026-01-01T00:00:00Z&end=2026-01-01T01:00:00Z&step=1m' | jq .

# Labels
curl -s 'http://localhost:9090/api/v1/labels' | jq .

# Label values
curl -s 'http://localhost:9090/api/v1/label/job/values' | jq .
```

## Практические сценарии

### Сценарий 1: Алерт не срабатывает

**Симптом:** Алерт `HighErrorRate` должен был сработать, но не сработал.

```promql
# Шаг 1: Проверяем выражение алерта
sum by (job) (rate(http_requests_total{status=~"5.."}[5m]))
/
sum by (job) (rate(http_requests_total[5m])) > 0.05
# → (пустой результат)

# Шаг 2: Проверяем числитель отдельно
sum by (job) (rate(http_requests_total{status=~"5.."}[5m]))
# → {job="api"} 0.02

# Шаг 3: Проверяем знаменатель
sum by (job) (rate(http_requests_total[5m]))
# → {job="api"} 150.0

# Шаг 4: Вычисляем долю
0.02 / 150.0
# → 0.000133 (это 0.013%, что МЕНЬШЕ порога 5%)

# РЕШЕНИЕ: Порог 0.05 (5%) слишком высок. Понизить до 0.01 (1%)
# или проверить, что ошибки действительно происходят
```

### Сценарий 2: График показывает "дыры"

**Симптом:** На графике `rate()` периодически появляются пропуски.

```promql
# Шаг 1: Проверяем количество точек в окне
count_over_time(http_requests_total[5m])
# → intermittent: 20, 0, 20, 0...

# Шаг 2: Проверяем targets
up{job="api"}
# → intermittently 0 and 1

# Шаг 3: Проверяем scrape interval
prometheus_scrape_duration_seconds{job="api"}
# → 0.15 (нормально)

# Шаг 4: Проверяем staleness
time() - timestamp(http_requests_total)
# → spike to 300+ seconds

# РЕШЕНИЕ: Таргет периодически недоступен. Проверьте:
# 1. Сетевую доступность
# 2. Логи приложения
# 3. Не перезапускается ли под
```

### Сценарий 3: Запрос возвращает NaN

**Симптом:** `histogram_quantile()` возвращает `NaN`.

```promql
# Шаг 1: Проверяем наличие данных в корзинах
count(http_request_duration_seconds_bucket)
# → 0 (нет данных!)

# Шаг 2: Проверяем, есть ли сама метрика
count(http_request_duration_seconds_sum)
# → 150 (данные есть)

# Шаг 3: Проверяем rate() по корзинам
rate(http_request_duration_seconds_bucket[5m])
# → (пустой результат)

# Шаг 4: Проверяем окно
count_over_time(http_request_duration_seconds_bucket[5m])
# → 0

# РЕШЕНИЕ: Классическая гистограмма не отправляет корзины.
# Проверьте конфигурацию экспортера и наличие лейбла le.
# Или перейдите на Native Histograms (Prometheus 3.0+).
```

### Сценарий 4: Деление на пустой вектор

**Симптом:** Запрос возвращает `NaN` или `+Inf`.

```promql
# Шаг 1: Проверяем делитель
sum by (job) (rate(http_requests_total{status="200"}[5m]))
# → (пустой результат — нет запросов со статусом 200)

# Шаг 2: Проверяем без фильтра
sum by (job) (rate(http_requests_total[5m]))
# → {job="api"} 150.0

# Шаг 3: Проверяем с другим фильтром
sum by (job) (rate(http_requests_total{status=~"2.."}[5m]))
# → {job="api"} 145.0

# РЕШЕНИЕ: Защита от деления на пустой вектор
sum by (job) (rate(http_requests_total{status=~"5.."}[5m]))
/
(sum by (job) (rate(http_requests_total[5m])) > 0)
# → {job="api"} 0.033 (вместо NaN)
```

### Сценарий 5: group_left не работает

**Симптом:** Ошибка `many-to-many matching not allowed`.

```promql
# Шаг 1: Проверяем кардинальность левого вектора
count by (deployment) (kube_pod_info)
# → {deployment="api"} 5

# Шаг 2: Проверяем кардинальность правого вектора
count by (deployment) (kube_deployment_labels)
# → {deployment="api"} 1

# Шаг 3: Пробуем group_left
kube_pod_info * on(deployment) group_left() kube_deployment_labels
# → many-to-many matching not allowed

# Шаг 4: Проверяем лейблы
labels(kube_pod_info)
# → deployment, namespace, pod, node...
labels(kube_deployment_labels)
# → deployment, namespace, version...

# РЕШЕНИЕ: Левый вектор имеет несколько рядов на один deployment.
# Агрегируйте левый вектор:
count by (deployment, namespace) (kube_pod_info)
* on(deployment, namespace) group_left()
kube_deployment_labels
```

### Сценарий 6: rate() возвращает неожиданно большие значения

**Симптом:** `rate()` показывает огромные пики после рестарта.

```promql
# Шаг 1: Проверяем resets
resets(http_requests_total[5m])
# → {instance="host1"} 3

# Шаг 2: Проверяем raw данные
http_requests_total{instance="host1"}
# → 100 → 0 → 50 (сброс + начальное значение)

# Шаг 3: Проверяем rate() с разными окнами
rate(http_requests_total[5m])
# → spike после сброса

rate(http_requests_total[10m])
# → более сглаженный

# РЕШЕНИЕ: Используйте более широкое окно (10m вместо 5m)
# или aggregating recording rule:
# job:http_requests:rate10m = sum by (job) (rate(http_requests_total[10m]))
```

## Дополнительная информация

### Чек-лист диагностики PromQL

| # | Проверка | Команда |
|:---|:---|:---|
| 1 | Метрика существует | `count(metric_name) > 0` |
| 2 | Данные за окно | `count_over_time(metric_name[5m]) >= 4` |
| 3 | Targets доступны | `up{job="..."} == 1` |
| 4 | Данные свежие | `time() - timestamp(metric_name) < 300` |
| 5 | Нет resets | `resets(metric_name[1h]) == 0` |
| 6 | Лейблы совпадают | Визуально проверьте `by`/`on` |
| 7 | Тип правильный | Нет ошибок `expected type` |
| 8 | Порог корректен | Значение < порога или > порога? |

### Связанные ресурсы

> - [Селекторы и операторы](./selectors_operators.md) — типовые ошибки селекторов.
> - [Типы данных](./data_types.md) — различие instant/range vector.
> - [Реальное поведение метрик](./real_world_behavior.md) — экстраполяция, staleness, counter resets.
> - [Функции PromQL](./functions.md) — справочник по функциям.
> - [promtool и лучшие практики](../../promtool_and_best_practices.md) — валидация и тестирование.
