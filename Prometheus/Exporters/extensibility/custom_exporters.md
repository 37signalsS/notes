# Создание собственных экспортеров Prometheus

## Определения

**Собственный экспортер Prometheus** — специализированное приложение, предназначенное для сбора метрик из внешних систем (базы данных, аппаратное обеспечение, проприетарные API) и их трансляции в формат, понятный Prometheus.

Экспортер выступает в роли прокси-сервера: он принимает HTTP-запросы от сервера Prometheus на эндпоинт `/metrics`, опрашивает целевую систему и возвращает актуальные данные.

## Основные концепции

### Архитектурные паттерны

При создании экспортера следует придерживаться одного из двух подходов:

1. **Collector Pattern (рекомендуемый):** экспортер запрашивает данные из целевой системы только тогда, когда Prometheus обращается к нему. Это гарантирует актуальность данных ("свежесть") и отсутствие лишней нагрузки на систему при отсутствии скрапинга.
2. **Background Polling:** экспортер периодически опрашивает систему в фоновом режиме и кэширует результат. Применяется, если опрос целевой системы занимает слишком много времени (дольше стандартного таймаута скрапинга в 10–30 секунд).

### Когда необходимо писать свой экспортер

| Ситуация | Решение |
| :--- | :--- |
| Готовый экспортер доступен в комьюнити | Использовать готовое решение ([Обзор экспортеров](../overview.md)) |
| Требуются метрики из простых shell-скриптов | Использовать [Textfile Collector](./textfile_collector.md) |
| Система не поддерживает Prometheus "из коробки" | Разработать собственный экспортер (этот документ) |
| Метрики генерируются внутри вашего кода | Использовать [клиентские библиотеки](./client_libraries.md) |

### Технические требования

* **Порты:** при выборе порта следует руководствоваться [официальным списком](https://github.com/prometheus/prometheus/wiki/Default-port-allocations). Для частных разработок обычно используется диапазон `9100–9200`.
* **Формат данных:** экспортер должен поддерживать текстовый формат экспозиции Prometheus.
* **Именование:** правила формирования имен метрик и лейблов описаны в [Расширяемость экспортеров — Концепции](./concepts.md).

## Практические сценарии

### Реализация экспортера на Go

Для разработки на Go используется официальная библиотека `client_golang`.

**Пример минимального экспортера:**

```go
package main

import (
    "net/http"
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promhttp"
    "github.com/prometheus/client_golang/prometheus/promauto"
    "log"
)

var (
    // Пример метрики: счетчик обработанных событий
    eventsProcessed = promauto.NewCounter(prometheus.CounterOpts{
        Name: "custom_exporter_events_total",
        Help: "Total number of events processed by this exporter",
    })
)

func main() {
    // Регистрация стандартного обработчика метрик
    http.Handle("/metrics", promhttp.Handler())
    
    log.Println("Starting exporter on :2112")
    // Запуск HTTP-сервера
    if err := http.ListenAndServe(":2112", nil); err != nil {
        log.Fatal(err)
    }
}
```

**Запуск и проверка:**

```bash
# Инициализация проекта и запуск
go mod init custom_exporter
go get github.com/prometheus/client_golang/prometheus
go run main.go

# В другом терминале проверка вывода
curl http://localhost:2112/metrics | grep custom_exporter
# → custom_exporter_events_total 0
```

### Реализация экспортера на Python

Библиотека `prometheus_client` позволяет быстро развернуть HTTP-сервер для отдачи метрик.

**Пример с использованием Gauge для мониторинга внешнего ресурса:**

```python
from prometheus_client import start_http_server, Gauge
import random
import time

# Определение метрики: уровень "заполненности" ресурса
RESOURCE_USAGE = Gauge('external_resource_usage_percent', 'Usage percentage of external resource')

def update_metrics():
    """Имитация опроса внешней системы"""
    while True:
        # В реальности здесь был бы вызов API или запрос к БД
        usage = random.uniform(0, 100)
        RESOURCE_USAGE.set(usage)
        time.sleep(10)

if __name__ == '__main__':
    # Запуск HTTP-сервера на порту 8000
    start_http_server(8000)
    print("Exporter started on port 8000")
    update_metrics()
```

**Проверка:**

```bash
curl http://localhost:8000/metrics
# → external_resource_usage_percent 45.23
```

## Дополнительная информация

* [Расширяемость экспортеров — Концепции](./concepts.md) — правила именования, работа с лейблами и кардинальностью.
* [Клиентские библиотеки](./client_libraries.md) — подробный список библиотек для различных языков программирования.
* [Textfile Collector](./textfile_collector.md) — сбор метрик через текстовые файлы без написания кода.
* [Service Discovery и Relabeling](../../service_discovery_and_relabeling.md) — как Prometheus находит новые экспортеры.
