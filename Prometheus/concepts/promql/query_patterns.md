# Шаблоны запросов PromQL

## Определения

**Шаблоны запросов (Query Patterns)** — проверенные на практике PromQL-выражения для решения типовых задач мониторинга. Каждый шаблон комбинирует [функции](./functions.md), [операторы агрегации](./aggregation.md) и [селекторы](./selectors_operators.md) в единую логическую конструкцию.

Для системного подхода к мониторингу рекомендуется использовать стандартные методологии:
- **RED (Rate, Errors, Duration)** — для анализа состояния сервисов и приложений.
- **USE (Utilization, Saturation, Errors)** — для анализа состояния ресурсов и инфраструктуры.
- **Four Golden Signals** (Latency, Traffic, Errors, Saturation) — фундамент мониторинга SRE.

## Базовые концепции

### Принцип построения запроса
Выбор метрики → Фильтрация по лейблам → Сдвиг во времени (`offset`) → Вычисление скорости/прироста (`rate`/`increase`) → Агрегация (`sum by`, `avg by`) → Арифметические операции (проценты, отношения).

### Расчёт долей и процентов
Общая формула отношения событий:
```promql
# Доля успешных запросов (SLA/SLI)
sum(rate(http_requests_total{status=~"2.."}[5m]))
/
sum(rate(http_requests_total[5m]))
```
Результат — значение от 0 до 1. Для получения процентов умножьте на `100`.

### Перцентили и квантили
Вычисляются исключительно через `histogram_quantile` над агрегированными корзинами:
```promql
# Обязательная агрегация sum(rate(...)) by (le)
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
```
Подробнее об устройстве — [Гистограммы](../metric_types/histogram.md).

## Практические сценарии

### Методология RED (Мониторинг сервисов)

**Rate (Интенсивность трафика):**
```promql
# Суммарный RPS всех инстансов сервиса
sum(rate(http_requests_total[5m])) by (service)
```

**Errors (Ошибки):**
```promql
# Интенсивность ошибок 5xx по путям (path)
sum(rate(http_requests_total{code=~"5.."}[5m])) by (path)
```

**Duration (Длительность/Латентность):**
```promql
# 95-й перцентиль времени ответа по методам
histogram_quantile(0.95, 
  sum by (le, method) (rate(http_request_duration_seconds_bucket[5m]))
)
```

### Методология USE (Инфраструктура)

**Utilization (Утилизация ресурсов):**
```promql
# Утилизация CPU (инверсия idle) по узлам
100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# Использование оперативной памяти (в %)
(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100

# Использование дискового пространства (фильтр по mountpoint обязателен)
(1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100
```

**Saturation (Насыщенность/Очереди):**
```promql
# Нагрузка относительно количества ядер (Saturation)
node_load1 / count by (instance) (node_cpu_seconds_total{mode="idle"})

# Дисковый I/O (Saturation через время операций)
rate(node_disk_io_time_seconds_total[5m])
```

**Errors (Ошибки оборудования/сети):**
```promql
# Скорость ошибок на сетевом интерфейсе (eth0)
rate(node_network_receive_bytes_total{device="eth0"}[5m])
```

### Мониторинг ресурсов Kubernetes

**Потребление памяти контейнерами (RSS):**
```promql
# Топ-5 потребителей памяти в неймспейсе
topk(5, sum by (pod) (container_memory_rss{container!="", namespace="prod"}))
```

**CPU Throttling (Saturation):**
```promql
# Процент времени, когда CPU контейнера ограничивался (throttled)
sum by (container, pod) (rate(container_cpu_cfs_throttled_seconds_total[5m]))
/
sum by (container, pod) (rate(container_cpu_usage_seconds_total[5m])) * 100
```

**Количество подов в состоянии Running:**
```promql
sum by (namespace) (kube_pod_status_phase{phase="Running"})
```

### Продвинутые паттерны и обнаружение аномалий

**Z-Score (Детекция всплесков):**
Сравнивает текущий rate со средним и стандартным отклонением за период.
```promql
# Отклонение более чем на 3 сигмы
(
  rate(http_requests_total[5m]) - avg_over_time(rate(http_requests_total[5m])[1h:5m])
) 
/ 
stddev_over_time(rate(http_requests_total[5m])[1h:5m]) > 3
```

**Прогноз исчерпания диска (Linear Prediction):**
```promql
# Место на диске закончится через 4 часа (на основе данных за 1 час)
predict_linear(node_filesystem_free_bytes{mountpoint="/"}[1h], 3600 * 4) < 0
```

**Нативные гистограммы (Prometheus 3.x):**
```promql
# Расчёт перцентиля без лейбла 'le' (Native Histograms)
histogram_quantile(0.99, sum by (service) (rate(http_request_duration_seconds[5m])))
```

## Дополнительная информация

### Предостережения

- **`irate()` vs `rate()`**: `irate()` чувствителен к мгновенным скачкам и подходит для графиков с высокой детализацией. Для алертов и долгосрочных трендов всегда используйте `rate()`, чтобы не пропустить данные между скрейпами.
- **Агрегация и Counter**: Никогда не суммируйте значения Counter напрямую. Сначала `rate()`, потом `sum()`. Нарушение этого правила ведет к некорректным данным при рестартах.
- **Агрегация квантилей**: Квантили (например, из Summary) нельзя усреднять. Если нужно объединить несколько инстансов, используйте Histogram.
- **Grafana и `$__rate_interval`**: Всегда используйте эту переменную в Grafana вместо фиксированных интервалов для корректного отображения `rate` на разных масштабах времени.

### Выбор интервала
- **Оперативный мониторинг**: 1m–5m (сглаживание шума).
- **Анализ трендов**: 30m–1h.
- **Алертинг**: Должен соответствовать `for` в правилах алертинга. Рекомендуется интервал функции как минимум в 2–3 раза больше `scrape_interval`.

> **См. также:**
>
> - [Функции PromQL](./functions.md) — детальное описание встроенных функций.
> - [Агрегация в PromQL](./aggregation.md) — группировка и модификаторы `by`/`without`.
> - [Реальное поведение метрик](./real_world_behavior.md) — нюансы экстраполяции и рестартов.
