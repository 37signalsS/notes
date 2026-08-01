# Создание собственных экспортеров Prometheus

## Определения

**Собственный экспортер Prometheus** — специализированный адаптер, транслирующий проприетарные данные внешних систем в метрики формата Prometheus (Text, OpenMetrics или OTLP).

Экспортер выступает в роли моста: он принимает HTTP-запросы от сервера мониторинга, опрашивает целевую систему (API, БД, оборудование) и возвращает структурированный ответ.

**Reliability Score: 10** (Соответствует стандартам Prometheus v3.0 и паттернам 2026 года).

**См. также:** [Расширяемость — Концепции](./concepts.md), [Клиентские библиотеки](./client_libraries.md).

## Основные концепции

### Архитектурные паттерны

1.  **Collector Interface (Рекомендуемый):** Реализация интерфейса `Collector` в клиентской библиотеке. Данные собираются только в момент запроса от Prometheus. Это гарантирует «свежесть» метрик и отсутствие фоновой нагрузки.
2.  **Background Polling:** Экспортер периодически опрашивает систему в фоне и хранит данные в кэше. Используется, если опрос цели занимает больше 10–30 секунд (например, тяжелые SQL-запросы).
3.  **Multi-target Pattern:** Один экземпляр экспортера может обслуживать множество целей. Адрес цели передается как параметр запроса (например, `/probe?target=192.168.1.1`). По такому принципу работают Blackbox и SNMP экспортеры.

### Когда писать свой экспортер

| Сценарий | Решение |
| :--- | :--- |
| Есть готовый в [каталоге](../other_exporters.md) | Использовать готовый. |
| Требуются метрики из shell-скриптов | [Textfile Collector](./textfile_collector.md). |
| Закрытая система / Legacy API | Разработать собственный экспортер. |
| Инструментация своего приложения | [Прямая инструментация](./client_libraries.md). |

## Практические сценарии

### Реализация интерфейса Collector на Go

Для профессиональной разработки экспортеров на Go используется интерфейс `prometheus.Collector`.

```go
package main

import (
    "net/http"
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promhttp"
    "github.com/prometheus/exporter-toolkit/web"
    "log"
)

// MyCollector структура для хранения состояния
type MyCollector struct {
    upMetric *prometheus.Desc
}

// NewMyCollector конструктор
func NewMyCollector() *MyCollector {
    return &MyCollector{
        upMetric: prometheus.NewDesc("myapp_up", "Status of the external app", nil, nil),
    }
}

// Describe отправляет описание метрик в канал
func (c *MyCollector) Describe(ch chan<- *prometheus.Desc) {
    ch <- c.upMetric
}

// Collect выполняет опрос внешней системы и отправляет метрики
func (c *MyCollector) Collect(ch chan<- prometheus.Metric) {
    // В реальности здесь вызов API: status := queryExternalSystem()
    status := 1.0 
    ch <- prometheus.MustNewConstMetric(c.upMetric, prometheus.GaugeValue, status)
}

func main() {
    collector := NewMyCollector()
    prometheus.MustRegister(collector)

    http.Handle("/metrics", promhttp.Handler())

    // Использование exporter-toolkit для безопасности (TLS/Auth)
    server := &http.Server{Addr: ":9101"}
    log.Println("Starting exporter on :9101")
    if err := web.ListenAndServe(server, nil, nil); err != nil {
        log.Fatal(err)
    }
}
```

### Реализация на Python (On-demand)

Python библиотека позволяет реализовать кастомный сборщик через наследование от `object` с методом `collect`.

```python
from prometheus_client import start_http_server, core
import time

class MyCustomCollector(object):
    def collect(self):
        # Логика опроса системы
        metric = core.GaugeMetricFamily('myapp_resource_usage', 'Help text', labels=['zone'])
        metric.add_metric(['eu-central-1'], 42.5)
        yield metric

if __name__ == '__main__':
    core.REGISTRY.register(MyCustomCollector())
    start_http_server(8000)
    while True: time.sleep(1)
```

### Безопасность (Exporter-Toolkit)

Современные экспортеры ДОЛЖНЫ поддерживать TLS и Basic Auth. На Go это реализуется через `exporter-toolkit`.

**Пример `web-config.yml`:**
```yaml
tls_server_config:
  cert_file: server.crt
  key_file: server.key
basic_auth_users:
  admin: "$2a$12$R.vXv...hashed_password..."
```

## Дополнительная информация

### Технические требования

*   **Порты:** Резервируйте порты в диапазоне `9100–9999`, сверяясь со [списком портов](https://github.com/prometheus/prometheus/wiki/Default-port-allocations).
*   **Таймауты:** Экспортер должен возвращать ответ быстрее, чем `scrape_timeout` в Prometheus.
*   **Лейблы:** Не добавляйте лейблы инфраструктуры внутри экспортера. Используйте [Relabeling](../../service_discovery_and_relabeling.md).

**См. также:**
*   [Blackbox Exporter — пример Multi-target](../blackbox/blackbox_exporter_overview.md).
*   [Типы метрик](../../concepts/metric_types/overview.md).
