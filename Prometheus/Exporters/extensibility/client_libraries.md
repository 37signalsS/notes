# Клиентские библиотеки Prometheus

## Определения

**Клиентская библиотека Prometheus** — программный интерфейс (API) для инструментации приложений, предназначенный для управления метриками и их экспозиции в форматах Prometheus Text, OpenMetrics или OTLP.

Библиотеки решают две основные задачи:
1.  **Прямая инструментация:** Встраивание сбора метрик непосредственно в код бизнес-логики для отслеживания производительности, ошибок и бизнес-показателей в реальном времени.
2.  **Создание кастомных экспортеров:** Разработка адаптеров для внешних систем без нативной поддержки Prometheus ([Создание собственных экспортеров](./custom_exporters.md)).

**См. также:**
*   [Расширяемость — Концепции](./concepts.md)
*   [Типы метрик](../../concepts/metric_types/overview.md)

## Основные концепции

### Поддерживаемые языки (2026)

Библиотеки делятся на официальные (поддерживаемые командой Prometheus) и одобренные сообществом. Все современные версии поддерживают формат **OpenMetrics**, **Exemplars** и нативный прием **OTLP**.

| Язык | Библиотека | Статус / Особенности |
| :--- | :--- | :--- |
| **Go** | [client_golang](https://github.com/prometheus/client_golang) | Официальная. Эталонная реализация, полная поддержка Native Histograms и UTF-8. |
| **Java** | [client_java](https://github.com/prometheus/client_java) | Официальная. Глубокая интеграция с Micrometer, Spring Boot 3.x и Quarkus. |
| **Python** | [client_python](https://github.com/prometheus/client_python) | Официальная. Поддержка мультипроцессного режима (WSGI/ASGI) и декораторов. |
| **Rust** | [prometheus-client-mmap](https://github.com/tikv/rust-prometheus) | Сообщество. Оптимизирована для систем с минимальным оверхедом. |
| **Node.js** | [prom-client](https://github.com/siimon/prom-client) | Сообщество. Поддержка TypeScript и агрегации воркеров (Cluster mode). |
| **.NET** | [prometheus-net](https://github.com/prometheus-net/prometheus-net) | Сообщество. Нативная интеграция с диагностикой .NET 8+ и OTel. |

### Технологические возможности (Prometheus 3.0+)

1.  **Native Histograms (Нативные гистограммы):** Обеспечивают высокую точность квантилей без ручного подбора границ корзин. Библиотеки Go и Java автоматически генерируют экспоненциальные бакеты, что снижает нагрузку на хранилище и упрощает конфигурацию.
2.  **Exemplars (Экземпляры):** Позволяют связать метрики с трейсами OpenTelemetry, передавая `trace_id` прямо в строке метрики. Это критично для перехода от графиков задержек к конкретным запросам в Jaeger/Tempo.
3.  **OTLP Integration:** Современные библиотеки могут экспортировать данные как через стандартный HTTP-скрейпинг, так и отправлять (push) их в формате OTLP в Prometheus OTLP Receiver или OpenTelemetry Collector.
4.  **UTF-8 Support:** Поддержка расширенных имен метрик и лейблов, что упрощает прямую трансляцию имен из OpenTelemetry без их искажения (например, использование точек в именах).

## Практические сценарии

### Инструментация в Go (С учетом Native Histograms)

Использование `promauto` для автоматической регистрации и нативных гистограмм для точного измерения задержек.

```go
package main

import (
    "net/http"
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
    // Нативная гистограмма (v3.0+)
    requestLatency = promauto.NewHistogram(prometheus.HistogramOpts{
        Namespace: "api",
        Subsystem: "http",
        Name:      "request_duration_seconds",
        Help:      "Duration of HTTP requests in seconds (Native Histogram).",
        // Включаем нативные гистограммы вместо классических бакетов
        NativeHistogramBucketFactor: 1.1, 
    })

    httpRequests = promauto.NewCounterVec(prometheus.CounterOpts{
        Namespace: "api",
        Subsystem: "http",
        Name:      "requests_total",
        Help:      "Total number of HTTP requests.",
    }, []string{"method", "code"})
)

func main() {
    // Стандартный эндпоинт для скрейпинга
    http.Handle("/metrics", promhttp.Handler())
    
    // Пример использования в middleware
    http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
        timer := prometheus.NewTimer(requestLatency)
        defer timer.ObserveDuration()
        
        w.WriteHeader(http.StatusOK)
        httpRequests.WithLabelValues(r.Method, "200").Inc()
    })

    http.ListenAndServe(":8080", nil)
}
```

### Инструментация в Python с использованием Exemplars

Пример связки метрики со сквозным ID запроса (Trace ID) для глубокой диагностики.

```python
from prometheus_client import Counter, start_http_server
import time
import random

# Счетчик с поддержкой меток
REQUESTS = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint'])

def handle_request(trace_id):
    # При инкрементации передаем exemplar для корреляции с трейсом
    REQUESTS.labels(method='get', endpoint='/api/v1/data').inc(1, exemplar={'trace_id': trace_id})

if __name__ == '__main__':
    # Запуск HTTP сервера на порту 8000
    start_http_server(8000)
    while True:
        # Симуляция обработки запроса с фиктивным Trace ID
        handle_request(f"trace-{random.randint(1000, 9999)}")
        time.sleep(1)
```

## Дополнительная информация

### Критерии выбора метода инструментации

| Критерий | Клиентская библиотека | Textfile Collector | OTel SDK |
| :--- | :--- | :--- | :--- |
| **Тип сервиса** | Долгоживущий (API, DB) | Краткосрочный (Cron) | Cloud-Native / Multi-cloud |
| **Точность** | Максимальная | Низкая (stale data) | Высокая |
| **Сложность** | Средняя (код) | Низкая (скрипт) | Высокая (конфигурация) |
| **Возможности** | Exemplars, Native Histograms | Только Counter/Gauge | Traces, Logs, Metrics |

### Рекомендации по безопасности

1.  **Exporter-Toolkit:** При написании собственных экспортеров на Go всегда используйте `prometheus/exporter-toolkit` для реализации TLS и аутентификации.
2.  **Защита эндпоинта:** Не выставляйте эндпоинт `/metrics` в публичный интернет без защиты на уровне Ingress или Firewall.
3.  **Порты:** Следуйте [реестру портов Prometheus](https://github.com/prometheus/prometheus/wiki/Default-port-allocations) для предотвращения конфликтов.

**См. также:**
*   [Метрики рантайма Go](./go_runtime_metrics.md)
*   [Формат экспозиции](../../concepts/metric_types/exposition_format.md)
