# Создание собственных экспортеров Prometheus

## Определения

**Собственный экспортер Prometheus** — специализированный адаптер, транслирующий проприетарные данные внешних систем в метрики формата Prometheus (Text, OpenMetrics или OTLP).

Экспортер выступает в роли моста: он принимает HTTP-запросы от сервера мониторинга, опрашивает целевую систему (API, БД, оборудование) и возвращает структурированный ответ. В современных реалиях 2026 года стандартом является поддержка **Native Histograms**, **Exemplars** и **UTF-8** имен метрик.

**См. также:** [Расширяемость — Концепции](./concepts.md), [Клиентские библиотеки](./client_libraries.md).

## Основные концепции

### Архитектурные паттерны

1.  **Collector Interface (Рекомендуемый):** Реализация интерфейса `Collector` в клиентской библиотеке. Данные собираются только в момент запроса от Prometheus. Это гарантирует актуальность метрик и отсутствие постоянной фоновой нагрузки.
2.  **Background Polling:** Экспортер периодически опрашивает систему в фоне и хранит данные в кэше. Используется, если опрос цели занимает значительное время (больше `scrape_timeout`, обычно >10 секунд).
3.  **Multi-target Pattern:** Один экземпляр экспортера обслуживает множество целей. Адрес цели передается как параметр запроса (например, `/probe?target=192.168.1.1`).
4.  **Push-gateway Bridge:** Экспортер может выступать прокси для Push-модели, собирая данные от эфемерных задач и отдавая их Prometheus по Pull-модели.

### Когда писать свой экспортер

| Сценарий | Решение |
| :--- | :--- |
| Есть готовый в [каталоге](../other_exporters.md) | Использовать готовый и проверенный сообществом. |
| Требуются метрики из простых скриптов | [Textfile Collector](./textfile_collector.md). |
| Закрытая система / Legacy API | Разработать собственный экспортер. |
| Инструментация своего приложения | [Прямая инструментация](./client_libraries.md). |
| Переход на OTLP | Использовать OpenTelemetry SDK с экспортом в Prometheus. |

### Поддержка возможностей Prometheus 3.0+

При разработке современных экспортеров необходимо учитывать следующие технологии:
*   **Native Histograms:** Использование экспоненциальных бакетов вместо фиксированных границ позволяет значительно повысить точность квантилей при снижении объема хранимых данных.
*   **UTF-8 Names:** Поддержка точек в именах метрик (например, `myapp.requests.total`) для совместимости с OpenTelemetry.
*   **Exemplars:** Передача ID трассировок вместе с метриками для быстрой навигации к логам и трейсам.

## Практические сценарии

### Реализация интерфейса Collector на Go

Для профессиональной разработки на Go используется интерфейс `prometheus.Collector`. В примере ниже добавлена поддержка нативных гистограмм.

```go
package main

import (
    "net/http"
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promhttp"
    "github.com/prometheus/exporter-toolkit/web"
    "log"
)

// MyCollector структура для хранения дескрипторов метрик
type MyCollector struct {
    upMetric      *prometheus.Desc
    latencyMetric *prometheus.Desc
}

// NewMyCollector конструктор коллектора
func NewMyCollector() *MyCollector {
    return &MyCollector{
        upMetric: prometheus.NewDesc("myapp_up", "Статус внешней системы", nil, nil),
        latencyMetric: prometheus.NewDesc(
            "myapp_request_duration_seconds",
            "Задержка запросов (Native Histogram)",
            []string{"method"},
            nil,
        ),
    }
}

// Describe регистрирует метрики
func (c *MyCollector) Describe(ch chan<- *prometheus.Desc) {
    ch <- c.upMetric
    ch <- c.latencyMetric
}

// Collect собирает данные в реальном времени
func (c *MyCollector) Collect(ch chan<- prometheus.Metric) {
    // Симуляция опроса внешней системы
    status := 1.0 
    ch <- prometheus.MustNewConstMetric(c.upMetric, prometheus.GaugeValue, status)

    // Пример отдачи нативной гистограммы (v3.0+)
    // В реальном коде данные приходят из системных замеров
    ch <- prometheus.MustNewConstNativeHistogram(
        c.latencyMetric,
        100,            // Count
        450.5,          // Sum
        nil,            // NativeHistogram (экспоненциальные бакеты)
        "get",          // Label value
    )
}

func main() {
    collector := NewMyCollector()
    prometheus.MustRegister(collector)

    http.Handle("/metrics", promhttp.Handler())

    // Использование exporter-toolkit для безопасности (TLS/Auth)
    server := &http.Server{Addr: ":9101"}
    log.Println("Starting exporter on :9101")
    
    // Рекомендуется использовать флаги для путей к конфигу TLS
    if err := web.ListenAndServe(server, &web.FlagConfig{}, log.Default()); err != nil {
        log.Fatal(err)
    }
}
```

### Реализация на Python (Custom Registry)

Python библиотека позволяет создавать кастомные сборщики через `REGISTRY`.

```python
from prometheus_client import start_http_server, core
import time

class CustomCollector(object):
    def collect(self):
        # Логика опроса системы
        metric = core.GaugeMetricFamily('myapp_resource_usage', 'Использование ресурсов', labels=['zone'])
        metric.add_metric(['eu-central-1'], 42.5)
        yield metric

if __name__ == '__main__':
    # Регистрация сборщика
    core.REGISTRY.register(CustomCollector())
    # Запуск сервера
    start_http_server(8000)
    while True:
        time.sleep(1)
```

### Тестирование экспортера

Перед релизом экспортер необходимо проверить на соответствие стандартам форматирования:

1.  **Linter:** Используйте утилиту `promtool` для проверки формата метрик.
    ```bash
    curl -s http://localhost:9101/metrics | promtool check metrics
    ```
2.  **Unit-тесты:** Проверяйте, что `Collect` корректно обрабатывает ошибки API внешней системы и не «крашит» экспортер.
3.  **Smoke-тесты:** Убедитесь, что при недоступности цели метрика `myapp_up` принимает значение `0`.

### Собственные метрики экспортера (Internal)

Качественный экспортер должен отдавать метрики о собственной работе:
*   `exporter_scrape_duration_seconds` — сколько времени занял опрос цели.
*   `exporter_scrapes_total` — общее количество попыток опроса.
*   `exporter_errors_total` — количество ошибок при общении с внешней системой.

## Дополнительная информация

### Технические требования

*   **Порты:** Резервируйте порты в диапазоне `9100–9999`, сверяясь с [реестром портов](https://github.com/prometheus/prometheus/wiki/Default-port-allocations).
*   **Таймауты:** Ответ должен возвращаться быстрее, чем настроенный `scrape_timeout` в Prometheus (по умолчанию 10с).
*   **Лейблы:** Не добавляйте лейблы инфраструктуры (env, zone) внутри кода. Используйте [Relabeling](../../service_discovery_and_relabeling.md) для обогащения данных.
*   **Лимиты ресурсов:** Устанавливайте CPU и Memory limits для процесса экспортера, особенно при использовании паттерна Background Polling.

**См. также:**
*   [Blackbox Exporter — пример Multi-target](../blackbox/blackbox_exporter_overview.md).
*   [Типы метрик](../../concepts/metric_types/overview.md).
*   [Remote Write 2.0](../../scaling/remote_read_write.md).
