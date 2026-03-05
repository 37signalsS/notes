# Расширяемость экспортеров Prometheus — Концепции

## Определения

**Расширяемость экспортеров** — возможность добавления произвольных метрик в Prometheus через внешние скрипты или создания собственных экспортеров с использованием клиентских библиотек.

## Основные механизмы

### 1. Textfile Collector

Механизм `node_exporter` для сбора произвольных метрик, предоставляемых внешними скриптами или приложениями.

**Принцип работы:**

1. Внешний скрипт (например, на Python или Bash) выполняется по расписанию (cron)
2. Скрипт выполняет свою логику: парсит логи, опрашивает оборудование, проверяет статус сервиса
3. Результат записывается в виде метрик в текстовый файл с расширением `.prom` в специальную директорию
4. `node_exporter` автоматически читает все `.prom` файлы из этой директории и добавляет метрики к общему выводу на `/metrics`

**Подробнее:** [Textfile Collector](./textfile_collector.md)

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

* **Не использовать** в лейблах: `region`, `zone`, `cluster`, `az`, `datacenter`, `customer` — это задача [Service Discovery](../service_discovery_and_relabeling.md)
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

| Язык | Репозиторий | Документация |
| :--- | :--- | :--- |
| Go | [prometheus/client_golang](https://github.com/prometheus/client_golang) | [pkg.go.dev](https://pkg.go.dev/github.com/prometheus/client_golang) |
| Python | [prometheus/client_python](https://github.com/prometheus/client_python) | [pypi.org](https://pypi.org/project/prometheus-client/) |
| Java | [prometheus/client_java](https://github.com/prometheus/client_java) | [github.com](https://github.com/prometheus/client_java) |
| JavaScript | [siimon/prom-client](https://github.com/siimon/prom-client) | [npmjs.com](https://www.npmjs.com/package/prom-client) |
| Ruby | [prometheus/client_ruby](https://github.com/prometheus/client_ruby) | [rubygems.org](https://rubygems.org/gems/prometheus-client) |
| .NET | [prometheus-net](https://github.com/prometheus-net/prometheus-net) | [nuget.org](https://www.nuget.org/packages/prometheus-net) |

**Подробнее:** [Клиентские библиотеки](./client_libraries.md)

## Связанные темы

* [Node Exporter](./node_exporter.md) — основной экспортер для Linux
* [Service Discovery и Relabeling](../service_discovery_and_relabeling.md)
* [Лейблы и кардинальность](../../Concepts/labels_and_cardinality.md)
* [Типы метрик](../../Concepts/metric_types.md)

## Официальные ресурсы

* [Instrumenting Client Libraries](https://prometheus.io/docs/instrumenting/clientlibs/)
* [Exposition Formats](https://prometheus.io/docs/instrumenting/exposition_formats/)
* [Default Port Allocations](https://github.com/prometheus/prometheus/wiki/Default-port-allocations)
