# Gauge (Измеритель)

**Gauge** — это метрика, которая представляет одно числовое значение, способное произвольно увеличиваться и уменьшаться.

## Примеры использования

* Текущая температура.
* Использование памяти (`node_memory_mem_available_bytes`).
* Количество элементов в очереди.
* Количество активных соединений.

## Особенности

* Показывает текущее состояние "здесь и сейчас".
* Может иметь отрицательные значения.

## Примеры метрик

* `node_memory_mem_available_bytes{instance="server-1"}`
* `process_resident_memory_bytes{job="app"}`
* `kube_pod_status_phase{namespace="default",phase="Running"}`

## Пример PromQL для Gauge

```promql
# Использование памяти в %
(1 - node_memory_mem_available_bytes / node_memory_mem_total_bytes) * 100

# Скорость изменения памяти (производная)
deriv(process_resident_memory_bytes[5m])

# Прогноз использования памяти через 4 часа
predict_linear(node_memory_mem_available_bytes[1h], 3600 * 4)
```

---

**Связанные темы:**

* [Counter](./counter.md) — кумулятивные счётчики
* [Histogram](./histogram.md) — гистограммы для распределений
* [PromQL функции](../promql/functions.md) — deriv(), predict_linear()
* [Примеры алертов](./alerts.md) — алерты на основе Gauge
