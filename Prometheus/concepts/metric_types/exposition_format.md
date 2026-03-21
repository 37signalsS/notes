# Формат экспозиции и инструментация

## Формат экспозиции (Text Exposition Format)

Экспортёры предоставляют метрики по HTTP в простом текстовом формате.

* `# HELP <имя_метрики> <описание>`: Комментарий с описанием метрики.
* `# TYPE <имя_метрики> <тип>`: Директива, указывающая тип метрики (`counter`, `gauge`, `histogram`, `summary`). Эта строка должна быть объявлена до первого использования метрики.
* `<имя_метрики>{<лейблы>} <значение> [<timestamp>]`: Сам временной ряд.

```text
# HELP http_requests_total Количество HTTP-запросов.
# TYPE http_requests_total counter
http_requests_total{method="POST",code="200"} 1027 1395066363000

# HELP request_duration_seconds Латентность запросов.
# TYPE request_duration_seconds histogram
request_duration_seconds_bucket{le="0.1"} 240
request_duration_seconds_bucket{le="0.5"} 980
...
request_duration_seconds_sum 75.3
request_duration_seconds_count 1210
```

## Соглашения по именованию и лейблам

* **Имена:** `snake_case`.
* **Единицы измерения:** Имена метрик должны содержать базовые единицы (например, `_seconds`, `_bytes`).
* **Кардинальность:** Избегайте использования в лейблах значений с высокой кардинальностью (ID пользователей, хэши запросов), так как это приводит к "взрыву" количества временных рядов. Подробнее см. в [Лейблы и кардинальность](../labels_and_cardinality.md).
* **Суффиксы по типу:**
  * `_total` — для Counter (обязательно)
  * `_bucket`, `_sum`, `_count` — для Histogram
  * `_sum`, `_count`, `{quantile="..."}` — для Summary

## Инструментация приложений

Для добавления метрик в приложение используйте клиентские библиотеки:

* **Go:** `github.com/prometheus/client_golang/prometheus`
* **Python:** `prometheus_client`
* **Java:** `io.prometheus:simpleclient`
* **Node.js:** `prom-client`

> **См. также:** [Extensibility — создание собственных экспортёров](../../Exporters/extensibility/custom_exporters.md) — практические примеры на Python и Go.

## Сравнение с VictoriaMetrics

VictoriaMetrics использует расширенный язык запросов [MetricsQL](../../../VictoriaMetrics/overview.md), который обратно совместим с PromQL и поддерживает все типы метрик Prometheus.

---

**Связанные темы:**

* [Лейблы и кардинальность](../labels_and_cardinality.md)
* [Counter](./counter.md) — суффикс `_total`
* [Histogram](./histogram.md) — суффиксы `_bucket`, `_sum`, `_count`
* [Summary](./summary.md) — суффиксы `{quantile="..."}`
