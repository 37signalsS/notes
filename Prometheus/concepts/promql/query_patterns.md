# Шаблоны запросов PromQL

## Определения

**Шаблоны запросов (Query Patterns)** — проверенные на практике PromQL-выражения для решения типовых задач мониторинга. Каждый шаблон комбинирует [функции](./functions.md), [операторы агрегации](./aggregation.md) и [селекторы](./selectors_operators.md) в единую логическую конструкцию.

Актуально для **Prometheus v3.0+**, включая нативную поддержку OpenTelemetry (OTLP), нативные гистограммы и новые возможности метаданных.

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
# → {service="auth"} 150.5
```

**Errors (Ошибки):**
```promql
# Интенсивность ошибок 5xx по путям (path)
sum(rate(http_requests_total{code=~"5.."}[5m])) by (path)
# → {path="/api/login"} 2.1
```

**Duration (Длительность/Латентность):**
```promql
# 95-й перцентиль времени ответа по методам (Classic Histograms)
histogram_quantile(0.95, 
  sum by (le, method) (rate(http_request_duration_seconds_bucket[5m]))
)
# → {method="GET"} 0.12

# 95-й перцентиль через Native Histograms (v3.0) — точнее и эффективнее
histogram_quantile(0.95, sum by (method) (rate(http_request_duration_seconds[5m])))
# → {method="GET"} 0.115
```

### Методология USE (Инфраструктура)

**Utilization (Утилизация ресурсов):**
```promql
# Утилизация CPU (инверсия idle) по узлам
100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
# → {instance="node-1"} 45.5

# Использование оперативной памяти (в %)
(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100
# → {instance="node-1"} 62.1
```

**Saturation (Насыщенность/Очереди):**
```promql
# Нагрузка относительно количества ядер (Saturation)
node_load1 / count by (instance) (node_cpu_seconds_total{mode="idle"})
# → {instance="node-2"} 1.5 (перегрузка, если > 1)

# Дисковый I/O (Saturation через время операций)
rate(node_disk_io_time_seconds_total[5m])
# → {device="sda"} 0.8 (близко к пределу 1.0)
```

**Errors (Ошибки оборудования/сети):**
```promql
# Скорость ошибок на сетевом интерфейсе (Errors)
rate(node_network_receive_errs_total{device="eth0"}[5m])
# → {device="eth0"} 0.05
```

### Мониторинг ресурсов Kubernetes

**Потребление памяти контейнерами (RSS):**
```promql
# Топ-5 потребителей памяти в неймспейсе
topk(5, sum by (pod) (container_memory_rss{container!="", namespace="prod"}))
# → {pod="api-7f6d"} 512MiB
```

**CPU Throttling (Saturation):**
```promql
# Процент времени, когда CPU контейнера ограничивался (throttled)
sum by (container, pod) (rate(container_cpu_cfs_throttled_seconds_total[5m]))
/
sum by (container, pod) (rate(container_cpu_usage_seconds_total[5m])) * 100
# → {pod="worker-1"} 12.5 (значение > 10% требует внимания)
```

**Количество подов в состоянии Running:**
```promql
sum by (namespace) (kube_pod_status_phase{phase="Running"})
# → {namespace="prod"} 24
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
# → {path="/api/attack"} 4.2
```

**Прогноз исчерпания диска (Linear Prediction):**
```promql
# Место на диске закончится через 4 часа (на основе данных за 1 час)
predict_linear(node_filesystem_free_bytes{mountpoint="/"}[1h], 3600 * 4) < 0
# → {instance="db-1"} 1
```

### Работа с метаданными (v3.0+)

**Обогащение через `info()` (exp):**
Автоматически добавляет лейблы из инфо-метрик без сложных `group_left`.
```promql
# Добавить версию из node_info к метрике загрузки CPU
info(node_load1, node_info)
# → {instance="node-1", version="v1.2.3"} 0.85
```

**Сортировка по лейблам через `sort_by_label()` (exp):**
```promql
# Топ-5 ошибок, отсортированных по имени сервиса для Grafana
sort_by_label(topk(5, rate(errors_total[5m])), "service")
```

## Дополнительная информация

### Предостережения

- **`irate()` vs `rate()`**: `irate()` чувствителен к мгновенным скачкам и подходит для графиков с высокой детализацией. Для алертов всегда используйте `rate()`.
- **Агрегация и Counter**: Сначала `rate()`, потом `sum()`. Выражение `rate(sum(...))` — **ошибка**, приводящая к искажению данных при рестартах.
- **OTLP Совместимость**: При работе с метриками OpenTelemetry через Prometheus v3.0, используйте паттерны нативных гистограмм для корректного отображения экспоненциальных бакетов.
- **Grafana и `$__rate_interval`**: Всегда используйте эту переменную для автоматического выбора окна агрегации в зависимости от шага графика.

### Выбор интервала
- **Оперативный мониторинг**: 1m–5m (сглаживание шума).
- **Анализ трендов**: 30m–1h.
- **Правило 4 точек**: Интервал функции должен быть как минимум в 4 раза больше `scrape_interval` для корректной обработки сбросов.

> **См. также:**
>
> - [Функции PromQL](./functions.md) — справочник встроенных функций.
> - [Агрегация в PromQL](./aggregation.md) — группировка и модификаторы `by`/`without`.
> - [Реальное поведение метрик](./real_world_behavior.md) — нюансы экстраполяции и staleness.
> - [Типы данных](./data_types.md) — подробности о векторах и скалярах.
