# Расширяемость экспортеров Prometheus — Концепции

## Определения

**Расширяемость экспортеров** — возможность добавления произвольных метрик в Prometheus через внешние скрипты или создания собственных экспортеров с использованием клиентских библиотек.

## Основные механизмы

### 1. Textfile Collector

Механизм `node_exporter` для сбора произвольных метрик через внешние скрипты, записывающие данные в `.prom` файлы.

**Подробнее:** [Textfile Collector](./textfile_collector.md) — активация, практические сценарии, troubleshooting.

### 2. Собственные экспортеры

Создание отдельных экспортеров с использованием клиентских библиотек Prometheus.

**Общие рекомендации:**

#### Именование метрик

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

#### Выбор labels

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

#### Рекомендации по коду

* Получение данных должно происходить только в момент скрапинга Prometheus'ом
* Не выставлять временные метки (timestamp), это задача Prometheus
* Выбирать порт с учетом [официального списка](https://github.com/prometheus/prometheus/wiki/Default-port-allocations)
* Использовать стандартные порты (диапазон 9100-9200)

**Подробнее:** [Создание собственных экспортеров](./custom_exporters.md)

## Клиентские библиотеки

Для создания собственных экспортеров и прямой инструментации используются официальные клиентские библиотеки Prometheus.

**Подробнее:** [Клиентские библиотеки](./client_libraries.md) — полный список, типы метрик и примеры использования.

## Связанные темы

* [Node Exporter](../node_exporter.md) — основной экспортер для Linux
* [Service Discovery и Relabeling](../../service_discovery_and_relabeling.md)
* [Лейблы и кардинальность](../../concepts/labels_and_cardinality.md)
* [Типы метрик](../../concepts/metric_types/overview.md)

## Официальные ресурсы

* [Instrumenting Client Libraries](https://prometheus.io/docs/instrumenting/clientlibs/)
* [Exposition Formats](https://prometheus.io/docs/instrumenting/exposition_formats/)
* [Default Port Allocations](https://github.com/prometheus/prometheus/wiki/Default-port-allocations)
