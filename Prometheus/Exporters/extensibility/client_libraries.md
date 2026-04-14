# Клиентские библиотеки Prometheus

## Определения

**Клиентская библиотека Prometheus** — программная библиотека для конкретного языка программирования, предоставляющая API для создания метрик (Counter, Gauge, Histogram, Summary) и реализации HTTP-эндпоинта `/metrics` в формате, совместимом с Prometheus.

Используются для:

- **Прямой инструментации** — встраивания метрик непосредственно в код приложения
- **Создания кастомных экспортеров** — написания отдельных программ, собирающих и отдающих метрики ([Создание собственных экспортеров](./custom_exporters.md))

## Основные понятия

### Поддерживаемые языки

| Язык | Репозиторий | Документация |
| :--- | :--- | :--- |
| **Go** | [prometheus/client_golang](https://github.com/prometheus/client_golang) | [pkg.go.dev](https://pkg.go.dev/github.com/prometheus/client_golang) |
| **Python** | [prometheus/client_python](https://github.com/prometheus/client_python) | [pypi.org](https://pypi.org/project/prometheus-client/) |
| **Java** | [prometheus/client_java](https://github.com/prometheus/client_java) | [github.com](https://github.com/prometheus/client_java) |
| **JavaScript** | [siimon/prom-client](https://github.com/siimon/prom-client) | [npmjs.com](https://www.npmjs.com/package/prom-client) |
| **Ruby** | [prometheus/client_ruby](https://github.com/prometheus/client_ruby) | [rubygems.org](https://rubygems.org/gems/prometheus-client) |
| **.NET** | [prometheus-net](https://github.com/prometheus-net/prometheus-net) | [nuget.org](https://www.nuget.org/packages/prometheus-net) |

### Типы метрик

Все клиентские библиотеки поддерживают четыре основных типа:

- **Counter** — монотонно возрастающий счётчик (например, количество запросов). Суффикс `_total` обязателен.
- **Gauge** — метрика, которая может увеличиваться и уменьшаться (например, использование памяти).
- **Histogram** — распределение значений по бакетам, автоматически выдаёт `_count`, `_sum` и `_bucket`. Подходит для измерения длительности операций.
- **Summary** — квантили распределения, вычисляются на стороне клиента. Подходит когда нужны точные квантили без аппроксимации.

**Подробнее о типах:** [Типы метрик](../../concepts/metric_types/overview.md)

Правила именования, работы с лейблами и рекомендации по коду — в [Расширяемость экспортеров — Концепции](./concepts.md).

## Практические сценарии

### Инструментация Go-приложения

```go
import (
    "net/http"
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
    requests = promauto.NewCounter(prometheus.CounterOpts{
        Name: "http_requests_total",
        Help: "Total number of HTTP requests",
    })

    memory = promauto.NewGauge(prometheus.GaugeOpts{
        Name: "app_memory_usage_bytes",
        Help: "Memory usage in bytes",
    })
)

func main() {
    // Регистрация обработчика /metrics
    http.Handle("/metrics", promhttp.Handler())
    http.ListenAndServe(":8080", nil)
}
```

### Инструментация Python-приложения

```python
from prometheus_client import start_http_server, Counter, Gauge

# Создание метрик
requests = Counter('http_requests_total', 'Total number of HTTP requests')
memory = Gauge('app_memory_usage_bytes', 'Memory usage in bytes')

# Инкремент счётчика
requests.inc()

# Установка значения gauge
memory.set(524288000)

# Запуск HTTP-сервера на порту 8000
start_http_server(8000)
```

### Выбор порта для кастомного экспортера

При создании собственного экспортера выбирайте порт с учётом [официального списка](https://github.com/prometheus/prometheus/wiki/Default-port-allocations).

**Рекомендуемый диапазон:** 9100–9200

## Дополнительная информация

### Связанные темы

- [Расширяемость экспортеров](./concepts.md) — правила именования метрик, labels, рекомендации по коду
- [Создание собственных экспортеров](./custom_exporters.md) — полные примеры экспортеров на Go и Python
- [Textfile Collector](./textfile_collector.md) — альтернативный способ добавления метрик без написания кода
- [Лейблы и кардинальность](../../concepts/labels_and_cardinality.md) — правила работы с лейблами
- [Формат экспозиции](../../concepts/metric_types/exposition_format.md) — текстовый формат метрик Prometheus
