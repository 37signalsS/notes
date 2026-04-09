# Функции PromQL

## Definitions

**Функции PromQL** — встроенные операции для обработки временных рядов в Prometheus. В отличие от [операторов агрегации](./aggregation.md), которые работают с instant vector, большинство функций принимают **range vector** и возвращают **instant vector**. Функции классифицируются по типу метрик, для которых они предназначены ([Counter](../metric_types/counter.md), [Gauge](../metric_types/gauge.md), [Histogram](../metric_types/histogram.md), [Summary](../metric_types/summary.md)).

## Basic Concepts

### Функции для счётчиков (Counters)

| Функция | Описание | Тип входа | Формула |
|---------|----------|-----------|---------|
| `rate(v)` | Средняя скорость роста в секунду | range-vector | `Δv / Δt` |
| `irate(v)` | Мгновенная скорость (2 последние точки) | range-vector | Локальная производная |
| `increase(v)` | Абсолютный прирост за интервал | range-vector | `rate() × интервал` |
| `resets(v)` | Количество сбросов счётчика | range-vector | Подсчёт разрывов |

**Ключевые особенности:**
- `rate()` и `increase()` **автоматически учитывают сбросы** в 0 при рестарте приложения
- `increase()` — сахар для `rate() × интервал`, результат может быть дробным из-за экстраполяции
- `irate()` чувствителен к шуму — предпочтительнее `rate()` для большинства сценариев
- `resets()` — обнаружение рестартов приложений

**Пример:**

```promql
# Средняя скорость запросов (RPS)
rate(http_requests_total[5m])

# Общее количество запросов за час
increase(http_requests_total[1h])

# Количество рестартов приложения
resets(process_start_time_seconds[1h])
```

### Функции для измерителей (Gauges)

| Функция | Описание | Тип входа | Формула |
|---------|----------|-----------|---------|
| `deriv(v)` | Производная (скорость изменения) | range-vector | Линейная регрессия |
| `predict_linear(v, t)` | Прогноз значения через `t` секунд | range-vector, scalar | Линейная экстраполяция |
| `delta(v)` | Разница между первым и последним значением | range-vector | `v_last - v_first` |
| `changes(v)` | Количество изменений значения | range-vector | Подсчёт переходов |

**Ключевые особенности:**
- `deriv()` — аналог `rate()` для Gauge, но **не учитывает сбросы в 0**
- `predict_linear()` — прогноз нехватки ресурсов (диск, память) для [алертинга](../../rules.md)
- `delta()` — отбрасывает промежуточные значения, можно пропустить резкий всплеск
- `changes()` — обнаружение нестабильности метрики

**Пример:**

```promql
# Прогноз нехватки диска через 4 часа
predict_linear(node_filesystem_free_bytes{mountpoint="/"}[1h], 3600 * 4) < 0

# Скорость изменения памяти
deriv(process_resident_memory_bytes[5m])

# Сколько изменилось значение за интервал
changes(node_load1[1h])
```

### Функции для гистограмм (Histograms)

| Функция | Описание | Тип входа |
|---------|----------|-----------|
| `histogram_quantile(φ, b)` | Вычисляет φ-квантиль (0 ≤ φ ≤ 1) | scalar, histogram |

**Ключевые особенности:**
- Вычисление перцентилей **на стороне сервера** — основное преимущество Histogram над [Summary](../metric_types/summary.md)
- Требует агрегации `sum by (le)` перед вычислением ([Агрегация](./aggregation.md))
- Точность зависит от настройки корзин ([Histogram](../metric_types/histogram.md))

**Пример:**

```promql
# 95-й перцентиль времени ответа
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
)
```

### Функции для сводок (Summaries)

Summary вычисляет квантили на стороне клиента, поэтому в PromQL **нет специальных функций** для работы с ними — квантили доступны напрямую:

```promql
# 95-й перцентиль из Summary
http_duration_summary{quantile="0.95"}
```

> **Важно:** Квантили из Summary **нельзя агрегировать** через `avg()` или `sum()`. Для распределённых систем используйте Histogram + `histogram_quantile()` ([Перцентили](../metric_types/percentiles.md)).

### Прочие функции

| Функция | Описание | Пример |
|---------|----------|--------|
| `absent(v)` | Возвращает `1`, если вектор пуст | `absent(up{job="critical"})` |
| `sort(v)` / `sort_desc(v)` | Сортировка вектора по значению | `sort(node_cpu_seconds_total)` |
| `round(v)`, `ceil(v)`, `floor(v)` | Округление значений | `round(avg(node_cpu_seconds_total))` |
| `time()` | Текущее время в Unix timestamp | `time()` |
| `holt_winters(v, sf, tf)` | Двойное экспоненциальное сглаживание | `holt_winters(node_cpu_seconds_total[1d], 0.5, 0.5)` |
| `clamp(v, min, max)` | Ограничение значения в диапазоне | `clamp(node_load1, 0, 100)` |
| `clamp_max(v, max)` / `clamp_min(v, min)` | Ограничение максимумом/минимумом | `clamp_max(node_load1, 100)` |

## Practical Scenarios

### Расчёт доли ошибок HTTP 5xx

```promql
sum(rate(http_requests_total{code=~"5.."}[5m]))
/
sum(rate(http_requests_total[5m]))
```

### Алерт на отсутствие метрики

```promql
# Вернёт 1, если метрика отсутствует — триггер для алерта
absent(up{job="my-critical-service"})
```

### Прогнозирование нехватки диска

```promql
# Диск закончится через 4 часа
predict_linear(node_filesystem_free_bytes{mountpoint="/"}[1h], 3600 * 4) < 0
```

### Перцентиль латентности с группировкой по сервису

```promql
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service)
)
```

### Обнаружение частых рестартов

```promql
# Больше 3 рестартов за час — алерт
resets(process_start_time_seconds[1h]) > 3
```

### Ограничение значений для визуализации

```promql
# Ограничить график нагрузки 0–100
clamp(node_load1, 0, 100)
```

## Additional Information

### Предостережения

- **`rate()` vs `irate()`** — `rate()` предпочтительнее для алертинга и дашбордов, `irate()` — для отладки резких скачков ([Реальное поведение метрик](./real_world_behavior.md))
- **`deriv()` при рестартах** — не учитывает сбросы в 0, может дать некорректный результат после перезапуска приложения
- **`histogram_quantile()` без `sum by (le)`** — посчитает перцентиль для каждого инстанса отдельно, а не агрегированный
- **Summary квантили + агрегация** — нельзя использовать `avg()` или `sum()`, применяйте `max()` или агрегируйте `_sum`/`_count ([Summary](../metric_types/summary.md))`

### Взаимосвязь с типами данных

- Функции для Counter/Gauge/Histogram принимают **range vector**, возвращают **instant vector** ([Типы данных](./data_types.md))
- Subqueries позволяют применять `..._over_time` к функциям instant vector: `avg_over_time(rate(http_requests_total[5m])[1h:5m])`
- Операторы агрегации (`sum()`, `avg()`) комбинируются с функциями: `sum(rate(http_requests_total[5m]))`
