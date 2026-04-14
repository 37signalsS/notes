# Создание собственных экспортеров Prometheus

## Определения

**Собственный экспортер Prometheus** — отдельная программа, написанная с использованием [клиентских библиотек](./client_libraries.md), которая собирает данные из внешней системы и отдаёт их в формате Prometheus через HTTP-эндпоинт `/metrics`.

Применяется, когда готового экспортера нет в [каталоге](https://prometheus.io/docs/instrumenting/exporters/) или требуется специфическая логика сбора.

## Основные понятия

### Когда писать свой экспортер

| Сценарий | Подход |
| :--- | :--- |
| Готовый экспортер существует | Использовать готовый ([Обзор экспортеров](../overview.md)) |
| Нужны произвольные скриптовые метрики | [Textfile Collector](./textfile_collector.md) — без написания кода |
| Нужна интеграция с внешней системой | Собственный экспортер (этот документ) |
| Метрики генерируются внутри приложения | Прямая инструментация ([Клиентские библиотеки](./client_libraries.md)) |

### Правила создания метрик

Все правила именования, работы с лейблами и рекомендации по коду собраны в [Расширяемость экспортеров — Концепции](./concepts.md).

**Ключевые принципы:**

- Данные собираются только в момент скрапинга Prometheus'ом
- Timestamp не выставляется — это задача Prometheus
- Порт выбирается по [официальному списку](https://github.com/prometheus/prometheus/wiki/Default-port-allocations), диапазон 9100–9200

## Практические сценарии

### Экспортер на Go

**Полный пример — счётчик событий с HTTP-эндпоинтом `/metrics`:**

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

**Инициализация, установка зависимостей и запуск:**

```bash
go mod init example_exporter
go get github.com/prometheus/client_golang/prometheus
go get github.com/prometheus/client_golang/prometheus/promhttp
go get github.com/prometheus/client_golang/prometheus/promauto
go get github.com/sirupsen/logrus
go run example_exporter.go
```

**Проверка:**

```bash
curl http://localhost:2112/metrics
```

### Экспортер на Python

**Полный пример — счётчик и gauge с labels:**

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
        MEMORY.set(random.randint(100000000, 500000000))
        time.sleep(5)

if __name__ == '__main__':
    start_http_server(8000)

    import threading
    threading.Thread(target=collect_metrics, daemon=True).start()

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

## Дополнительная информация

### Связанные темы

- [Расширяемость экспортеров](./concepts.md) — правила именования метрик, labels, рекомендации по коду
- [Клиентские библиотеки](./client_libraries.md) — список библиотек, типы метрик, примеры инструментации
- [Textfile Collector](./textfile_collector.md) — сбор метрик через внешние скрипты без написания экспортера
- [Node Exporter](../node_exporter.md) — основной экспортер для Linux
- [Обзор экспортеров](../overview.md) — каталог готовых экспортеров
