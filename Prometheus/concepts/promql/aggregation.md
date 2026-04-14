# Агрегация в PromQL

## Definitions

**Агрегация** — операция объединения множества временных рядов в один результат. Операторы агрегации принимают вектор мгновенных значений и возвращают агрегированный вектор с уменьшенным количеством рядов.

**Ключевые модификаторы:**

- `by (<label1>, <label2>)` — группировка по указанным лейблам, все остальные лейблы удаляются из результата
- `without (<label1>, <label2>)` — агрегация по всем лейблам, кроме указанных

## Basic Concepts

### Синтаксис агрегации

```promql
<aggr_op> [parameter] by(<labels>) ([metric])
<aggr_op> [parameter] without(<labels>) ([metric])
```

### Операторы мгновенной агрегации

| Оператор | Описание | Пример |
|----------|----------|--------|
| `sum()` | Сумма значений | `sum(http_requests_total)` |
| `avg()` | Среднее значение | `avg(node_cpu_seconds_total)` |
| `count()` | Количество рядов | `count(up{job="api"})` |
| `min()`, `max()` | Минимум/максимум | `max(node_filesystem_avail_bytes)` |
| `stddev()`, `stdvar()` | Стандартное отклонение/дисперсия | `stddev(http_request_duration_seconds)` |
| `topk(k, v)` | `k` наибольших значений | `topk(5, node_cpu_seconds_total)` |
| `bottomk(k, v)` | `k` наименьших значений | `bottomk(3, node_memory_MemFree_bytes)` |
| `count_values(label, v)` | Подсчёт рядов с одинаковыми значениями | `count_values("version", app_build_info)` |
| `quantile(φ, v)` | φ-квантиль (0 ≤ φ ≤ 1) | `quantile(0.95, http_request_duration_seconds)` |

### Агрегация по времени (`..._over_time`)

Функциции диапазона агрегируют значения _каждого_ ряда в указанном окне и возвращают instant vector:

| Функция | Описание |
|---------|----------|
| `avg_over_time(range)` | Среднее значение в диапазоне |
| `min_over_time(range)`, `max_over_time(range)` | Минимум/максимум в диапазоне |
| `sum_over_time(range)` | Сумма значений в диапазоне |
| `count_over_time(range)` | Количество точек в диапазоне |
| `first_over_time(range)`, `last_over_time(range)` | Первое/последнее значение |
| `stddev_over_time(range)`, `stdvar_over_time(range)` | Отклонение/дисперсия в диапазоне |
| `quantile_over_time(φ, range)` | φ-квантиль в диапазоне |

## Practical Scenarios

### Группировка по лейблам

```promql
# Сумма запросов для каждого path
sum by (path) (http_requests_total)

# Средний CPU по instance, исключая лейблы cpu и mode
avg without (cpu, mode) (node_cpu_seconds_total{mode="idle"})
```

### Расчёт доли ошибок HTTP 5xx

```promql
sum(rate(http_requests_total{code=~"5.."}[5m]))
/
sum(rate(http_requests_total[5m]))
```

### Top-5 подов по потреблению памяти

```promql
topk(5, container_memory_usage_bytes{container!=""})
```

### Прогнозирование нехватки диска

```promql
# Среднее свободное место за последний час
avg_over_time(node_filesystem_avail_bytes[1h])
```

### Подсчёт количества инстансов с одинаковой версией

```promql
count_values("version", app_build_info)
```

## Additional Information

### Предостережения

- **Counter + `sum(rate())`** — безопасная комбинация для распределённых систем. Суммирование rate по counter корректно отражает общую скорость ([Счётчики](../metric_types/counter.md))
- **Summary квантили нельзя агрегировать** через `avg()` или `sum()` — они уже вычислены на стороне клиента. Используйте `max()` или агрегируйте `_sum`/`_count ([Summary](../metric_types/summary.md))`
- **Histogram + `histogram_quantile()`** — предпочтительный подход для перцентилей в распределённых системах ([Гистограммы](../metric_types/histogram.md))

### Subqueries и агрегация

Subqueries позволяют применять `..._over_time` к функциям instant vector:

```promql
# Среднее rate за последний час с шагом 5 минут
avg_over_time(rate(http_requests_total[5m])[1h:5m])
```

Подробнее о векторных операциях и subqueries — [Операции с векторами](./vector_operations.md).
