# Клиентские библиотеки Prometheus

## Определения

**Клиентская библиотека Prometheus** — это программный интерфейс (API) для конкретного языка программирования, предназначенный для создания, управления и экспозиции метрик в формате, совместимом с Prometheus.

Библиотеки решают две основные задачи:

1. **Прямая инструментация:** встраивание сбора метрик непосредственно в исходный код приложения (бизнес-логика, время ответа API).
2. **Создание кастомных экспортеров:** разработка отдельных сервисов для мониторинга внешних систем, которые не поддерживают формат Prometheus "из коробки" ([Создание собственных экспортеров](./custom_exporters.md)).

## Основные концепции

### Поддерживаемые языки

Официальные и поддерживаемые сообществом библиотеки обеспечивают реализацию стандарта экспозиции метрик для большинства современных стеков.

| Язык | Репозиторий | Особенности |
| :--- | :--- | :--- |
| **Go** | [prometheus/client_golang](https://github.com/prometheus/client_golang) | Самая функциональная библиотека; нативная поддержка конкурентности. |
| **Python** | [prometheus/client_python](https://github.com/prometheus/client_python) | Поддерживает различные режимы (multiprocess) и декораторы. |
| **Java** | [prometheus/client_java](https://github.com/prometheus/client_java) | Интеграция с JMX, Spring Boot, Micrometer. |
| **JavaScript** | [siimon/prom-client](https://github.com/siimon/prom-client) | Стандарт для Node.js приложений. |
| **Ruby** | [prometheus/client_ruby](https://github.com/prometheus/client_ruby) | Поддержка Rack-интеграции. |
| **.NET** | [prometheus-net](https://github.com/prometheus-net/prometheus-net) | Полная интеграция с ASP.NET Core. |

### Поддержка типов метрик

Все библиотеки реализуют четыре базовых [типа метрик](../../concepts/metric_types/overview.md):

* **Counter:** накопительные счетчики (запросы, ошибки).
* **Gauge:** мгновенные значения (память, температура).
* **Histogram:** распределение значений по корзинам (латентность).
* **Summary:** расчет квантилей на стороне клиента.

### Автоматическая экспозиция

Библиотеки включают встроенные HTTP-обработчики для эндпоинта `/metrics`. При скрапинге (HTTP GET запрос) библиотека на лету генерирует текстовое представление всех зарегистрированных метрик.

## Практические сценарии

### Прямая инструментация в Go

Использование пакета `promauto` позволяет автоматически регистрировать метрики в глобальном реестре (`DefaultRegisterer`).

```go
package main

import (
    "net/http"
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
    // Определение метрики с автоматической регистрацией
    opsProcessed = promauto.NewCounter(prometheus.CounterOpts{
        Name: "myapp_processed_ops_total",
        Help: "The total number of processed events",
    })
)

func main() {
    // Регистрация обработчика /metrics
    http.Handle("/metrics", promhttp.Handler())
    
    // Имитация работы приложения
    go func() {
        for {
            opsProcessed.Inc()
        }
    }()

    http.ListenAndServe(":8080", nil)
}
```

### Инструментация в Python

Библиотека предоставляет декораторы и контекстные менеджеры для удобного сбора метрик времени выполнения.

```python
from prometheus_client import start_http_server, Summary, Counter
import time
import random

# Создание метрик
REQUEST_TIME = Summary('request_processing_seconds', 'Time spent processing request')
ERRORS = Counter('app_errors_total', 'Total application errors')

@REQUEST_TIME.time()
def process_request():
    """Функция с автоматическим замером времени выполнения"""
    if random.random() < 0.1:
        ERRORS.inc()
    time.sleep(random.random())

if __name__ == '__main__':
    # Запуск HTTP-сервера для экспозиции метрик
    start_http_server(8000)
    while True:
        process_request()
```

### Когда использовать библиотеки вместо скриптов

* **Textfile Collector** предпочтителен для cron-задач или простых системных скриптов, где время жизни процесса меньше интервала скрапинга.
* **Клиентские библиотеки** необходимы для долгоживущих сервисов, высоконагруженных систем и когда требуется сложная агрегация данных (Histogram/Summary).

## Дополнительная информация

* [Расширяемость экспортеров — Концепции](./concepts.md) — правила именования, работа с лейблами и кардинальностью.
* [Создание собственных экспортеров](./custom_exporters.md) — архитектурные паттерны и полные примеры реализации.
* [Default Port Allocations](https://github.com/prometheus/prometheus/wiki/Default-port-allocations) — список зарезервированных портов для экспортеров.
