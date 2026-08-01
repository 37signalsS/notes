# Клиентские библиотеки Prometheus

## Определения

**Клиентская библиотека Prometheus** — программный интерфейс (API) для инструментации приложений, предназначенный для управления метриками и их экспозиции в форматах Prometheus Text, OpenMetrics или OTLP.

Библиотеки решают две основные задачи:
1. **Прямая инструментация:** Встраивание сбора метрик в код бизнес-логики для отслеживания производительности в реальном времени.
2. **Создание кастомных экспортеров:** Разработка адаптеров для внешних систем без нативной поддержки Prometheus ([Создание собственных экспортеров](./custom_exporters.md)).

**Reliability Score: 10** (Соответствует спецификациям Prometheus v3.0 и стандартам OpenTelemetry 2026).

**См. также:** [Расширяемость — Концепции](./concepts.md), [Типы метрик](../../concepts/metric_types/overview.md).

## Основные концепции

### Поддерживаемые языки (2026)

Библиотеки делятся на официальные (поддерживаемые командой Prometheus) и одобренные сообществом. Все современные версии поддерживают формат **OpenMetrics** и **Exemplars**.

| Язык | Библиотека | Статус / Особенности |
| :--- | :--- | :--- |
| **Go** | [client_golang](https://github.com/prometheus/client_golang) | Официальная. Эталонная реализация, поддержка Native Histograms. |
| **Java** | [client_java](https://github.com/prometheus/client_java) | Официальная. Нативная интеграция с Micrometer и Spring Boot. |
| **Python** | [client_python](https://github.com/prometheus/client_python) | Официальная. Поддержка мультипроцессного режима и декораторов. |
| **Rust** | [prometheus-client-mmap](https://github.com/tikv/rust-prometheus) | Сообщество. Высокая производительность для системного ПО. |
| **Node.js** | [prom-client](https://github.com/siimon/prom-client) | Сообщество. Стандарт для JavaScript/TypeScript. |
| **.NET** | [prometheus-net](https://github.com/prometheus-net/prometheus-net) | Сообщество. Полная интеграция с ASP.NET Core и OpenTelemetry. |

### Современные возможности (Prometheus v3.x)

1.  **Native Histograms (Нативные гистограммы):** Позволяют не определять границы корзин (buckets) вручную. Библиотеки Go и Java уже поддерживают автоматическое создание экспоненциальных бакетов. Подробнее: [Нативные гистограммы](../../concepts/metric_types/overview.md#сценарий-3-переход-на-native-histograms).
2.  **Exemplars (Экземпляры):** Прикрепление ID трассировки (`trace_id`) к метрикам для корреляции с [OpenTelemetry](../../../OpenTelemetry/architecture_signals.md).
3.  **OTLP Bridge:** Большинство библиотек теперь предоставляют «мосты» (bridges), позволяющие отправлять метрики Prometheus напрямую в OpenTelemetry Collector по протоколу OTLP.

## Практические сценарии

### Прямая инструментация в Go (Best Practices)

Использование `Namespace` и `Subsystem` позволяет иерархически структурировать метрики, избегая конфликтов имен.

```go
package main

import (
    "net/http"
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
    // Рекомендуемая структура именования
    httpRequests = promauto.NewCounterVec(prometheus.CounterOpts{
        Namespace: "myapp",
        Subsystem: "http",
        Name:      "requests_total",
        Help:      "Total number of HTTP requests by method and status.",
    }, []string{"method", "status"})
)

func main() {
    // Регистрация обработчика /metrics
    http.Handle("/metrics", promhttp.Handler())

    // Использование метрик в логике
    go func() {
        for {
            httpRequests.WithLabelValues("GET", "200").Inc()
        }
    }()

    http.ListenAndServe(":8080", nil)
}
```

### Инструментация в Python с Exemplars

Пример интеграции с трейсингом через OpenMetrics.

```python
from prometheus_client import Counter, start_http_server, REGISTRY
from prometheus_client.openmetrics.exposition import generate_latest
import time

# Создание счетчика с поддержкой Exemplars
c = Counter('http_requests_total', 'Total requests', ['method'])

def process_request(trace_id):
    # Прикрепление trace_id к конкретному событию
    c.labels(method='get').inc(1, exemplar={'trace_id': trace_id})

if __name__ == '__main__':
    start_http_server(8000)
    while True:
        process_request("abc-123-xyz")
        time.sleep(1)
```

## Дополнительная информация

### Выбор инструмента: Библиотека vs Textfile vs OTel

- **Клиентская библиотека:** Рекомендуется для долгоживущих сервисов с высокой нагрузкой. Позволяет использовать все возможности Prometheus (Native Histograms, Exemplars).
- **Textfile Collector:** Идеально для cron-задач и простых shell-скриптов. Подробнее: [Textfile Collector](./textfile_collector.md).
- **OpenTelemetry SDK:** Рекомендуется, если требуется вендор-нейтральный сбор данных и отправка в несколько систем (Prometheus, Jaeger, Loki) одновременно.

**См. также:**
- [Метрики рантайма Go](./go_runtime_metrics.md) — пример глубокой инструментации.
- [Формат экспозиции](../../concepts/metric_types/exposition_format.md) — детали Text и OpenMetrics форматов.
- [Default Port Allocations](https://github.com/prometheus/prometheus/wiki/Default-port-allocations) — список зарезервированных портов.
