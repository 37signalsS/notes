# Клиентские библиотеки Prometheus

## Обзор

Клиентские библиотеки Prometheus предоставляют API для создания метрик и экспортеров на различных языках программирования.

## Поддерживаемые языки

| Язык | Репозиторий | Документация |
| :--- | :--- | :--- |
| **Go** | [prometheus/client_golang](https://github.com/prometheus/client_golang) | [pkg.go.dev](https://pkg.go.dev/github.com/prometheus/client_golang) |
| **Python** | [prometheus/client_python](https://github.com/prometheus/client_python) | [pypi.org](https://pypi.org/project/prometheus-client/) |
| **Java** | [prometheus/client_java](https://github.com/prometheus/client_java) | [github.com](https://github.com/prometheus/client_java) |
| **JavaScript** | [siimon/prom-client](https://github.com/siimon/prom-client) | [npmjs.com](https://www.npmjs.com/package/prom-client) |
| **Ruby** | [prometheus/client_ruby](https://github.com/prometheus/client_ruby) | [rubygems.org](https://rubygems.org/gems/prometheus-client) |
| **.NET** | [prometheus-net](https://github.com/prometheus-net/prometheus-net) | [nuget.org](https://www.nuget.org/packages/prometheus-net) |

## Типы метрик

Все клиентские библиотеки поддерживают следующие типы метрик:

* **Counter** — монотонно возрастающий счетчик
* **Gauge** — метрика, которая может увеличиваться и уменьшаться
* **Histogram** — распределение значений по бакетам
* **Summary** — квантили распределения

## Примеры использования

### Go

```go
import (
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
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
```

### Python

```python
from prometheus_client import Counter, Gauge

requests = Counter('http_requests_total', 'Total number of HTTP requests')
memory = Gauge('app_memory_usage_bytes', 'Memory usage in bytes')

# Инкремент счетчика
requests.inc()

# Установка значения gauge
memory.set(524288000)
```

## Выбор порта

При создании экспортера выбирайте порт с учетом [официального списка](https://github.com/prometheus/prometheus/wiki/Default-port-allocations).

**Рекомендуемый диапазон:** 9100-9200

## Связанные темы

* [Расширяемость экспортеров](./concepts.md) — базовые концепции
* [Создание собственных экспортеров](./custom_exporters.md) — примеры кода на Go и Python
* [Textfile Collector](./textfile_collector.md) — альтернативный способ добавления метрик

## Официальные ресурсы

* [Instrumenting Client Libraries](https://prometheus.io/docs/instrumenting/clientlibs/)
* [Exposition Formats](https://prometheus.io/docs/instrumenting/exposition_formats/)
