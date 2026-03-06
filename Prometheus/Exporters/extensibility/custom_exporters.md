# Создание собственных экспортеров Prometheus

## Общие рекомендации

### Именование метрик

* **Нижний регистр:** `[a-zA-Z0-9_:]`
* **Суффиксы:**
  * `_total` — для counter (обязательно)
  * `_sum`, `_count`, `_bucket` — для histogram
  * `_info` — для метрик с информацией (версия, конфигурация)
* **Префиксы:** избегать `process_`, `scrape_` (зарезервированы)
* **Единицы измерения:** включать в название (`_seconds`, `_bytes`, `_count`)

**Примеры правильных имён:**

```
nginx_http_request_duration_seconds
mysql_queries_total
app_memory_usage_bytes
node_cpu_seconds_total
```

### Выбор labels

* **Не использовать** в лейблах: `region`, `zone`, `cluster`, `az`, `datacenter`, `customer` — это задача [Service Discovery](../../service_discovery_and_relabeling.md)
* **Избегать высокой кардинальности:** не использовать `request_id`, `user_id`, `email`
* **Метрика должна иметь смысл при агрегации:** не разделять `read/write` с помощью лейбла, лучше сделать две разные метрики

**Примеры правильных лейблов:**

```
http_requests_total{method="GET",status="200"}
mysql_queries_total{database="users"}
```

**Примеры неправильных лейблов:**

```
http_requests_total{request_id="abc123"}     # Высокая кардинальность
user_actions_total{user_email="..."}         # Высокая кардинальность
```

### Рекомендации по коду

* Получение данных должно происходить только в момент скрапинга Prometheus'ом
* Не выставлять временные метки (timestamp), это задача Prometheus
* Выбирать порт с учетом [официального списка](https://github.com/prometheus/prometheus/wiki/Default-port-allocations)
* Использовать стандартные порты (диапазон 9100-9200)

## Пример экспортера на Go

**Простейший экспортер, который инкрементирует счетчик каждые 2 секунды:**

**Код (`example_exporter.go`):**

```go
package main

import (
        "net/http"
        "time"
        log "github.com/sirupsen/logrus"

        "github.com/prometheus/client_golang/prometheus"
        "github.com/prometheus/client_golang/prometheus/promhttp"
        "github.com/prometheus/client_golang/prometheus/promauto"
)

func recordMetrics() {
        go func() {
                for {
                        opsProcessed.Inc()
                        time.Sleep(2 * time.Second)
                }
        }()
}

var (
        opsProcessed = promauto.NewCounter(prometheus.CounterOpts{
                Name: "example_exporter_processed_ops_total",
                Help: "The total number of processed events",
        })
)

func main() {
        recordMetrics()

        http.Handle("/metrics", promhttp.Handler())
        log.Info("Beginning to serve on port :2112")
        log.Fatal(http.ListenAndServe(":2112", nil))
}
```

**Установка зависимостей и запуск:**

```bash
# Инициализация модуля
go mod init example_exporter

# Установка зависимостей
go get github.com/prometheus/client_golang/prometheus
go get github.com/prometheus/client_golang/prometheus/promhttp
go get github.com/prometheus/client_golang/prometheus/promauto
go get github.com/sirupsen/logrus

# Запуск
go run example_exporter.go
```

**Проверка:**

```bash
curl http://localhost:2112/metrics
```

## Пример экспортера на Python

**Использование библиотеки `prometheus_client`:**

```python
#!/usr/bin/env python3

from prometheus_client import start_http_server, Counter, Gauge
import time
import random

# Создаем метрики
REQUESTS = Counter('http_requests_total', 'Total HTTP requests', ['method'])
MEMORY = Gauge('app_memory_usage_bytes', 'Memory usage in bytes')

def collect_metrics():
    """Сбор метрик"""
    while True:
        # Эмулируем сбор метрик
        MEMORY.set(random.randint(100000000, 500000000))
        time.sleep(5)

if __name__ == '__main__':
    # Запускаем HTTP-сервер
    start_http_server(8000)

    # Запускаем сбор метрик в фоне
    import threading
    threading.Thread(target=collect_metrics, daemon=True).start()

    # Эмулируем обработку запросов
    while True:
        method = random.choice(['GET', 'POST', 'PUT', 'DELETE'])
        REQUESTS.labels(method=method).inc()
        time.sleep(1)
```

**Установка и запуск:**

```bash
pip install prometheus_client
python example_exporter.py
```

## Клиентские библиотеки

Подробный список клиентских библиотек для различных языков программирования доступен в [Клиентские библиотеки](./client_libraries.md).

## Связанные темы

* [Расширяемость экспортеров](./concepts.md) — базовые концепции
* [Textfile Collector](./textfile_collector.md) — сбор метрик через внешние скрипты
* [Node Exporter](../node_exporter.md) — основной экспортер для Linux
