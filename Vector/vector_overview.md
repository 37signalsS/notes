# Vector

## Определения

**Vector** — это высокопроизводительный конвейер для сбора, обработки и отправки логов, метрик и событий. Написан на языке Rust, что обеспечивает высокую производительность, безопасность памяти и низкое потребление ресурсов.

**Ключевая особенность:** Vector может работать в двух режимах:
- **Agent** — легковесный агент на каждом хосте (замена Filebeat/Fluent Bit)
- **Aggregator** — централизованный обработчик потоков данных (замена Logstash/Fluentd)

---

## Основные концепции

### Архитектура

Архитектура Vector состоит из трёх компонентов:

1. **Sources (Источники)** — определяют, откуда Vector получает данные:
    - Файлы логов (`/var/log/*.log`, journald)
    - Сетевые протоколы (Syslog, HTTP, TCP, UDP)
    - Очереди сообщений (Kafka, NATS)
    - Облачные сервисы (AWS S3, GCP Pub/Sub, Azure Event Hubs)
    - Контейнеры и оркестраторы (Docker, Kubernetes)
    - Системные метрики (OS, Prometheus endpoints)

2. **Transforms (Преобразования)** — модифицируют, фильтруют и обогащают данные:
    - **`remap`** — преобразования с помощью [VRL](#vector-remap-language-vrl)
    - **`filter`** — фильтрация событий по условиям
    - **`route`** — маршрутизация по разным sink'ам
    - **`reduce`** — агрегация нескольких событий
    - **`luajit`** — кастомная логика на Lua

3. **Sinks (Приемники)** — определяют, куда отправлять обработанные данные:
    - Хранилища логов (Elasticsearch, OpenSearch, Loki, ClickHouse)
    - Очереди (Kafka, NATS, AWS SQS)
    - Метрики (Prometheus remote write, Datadog, StatsD)
    - Облака (AWS S3, GCS, Azure Blob Storage)
    - HTTP/Webhook endpoints

### Ключевые характеристики

| Характеристика | Описание |
| :--- | :--- |
| **Производительность** | В 5–10 раз быстрее Logstash/Fluentd при меньшем потреблении CPU |
| **Безопасность памяти** | Гарантии Rust исключают уязвимости типа buffer overflow |
| **Гарантия доставки** | At-least-once delivery с персистентным буфером на диске |
| **Мультиплатформенность** | Linux, macOS, Windows, Docker, Kubernetes |
| **Конфигурация** | TOML, YAML, JSON (TOML рекомендуется для строгости) |
| **Обработка ошибок** | Встроенные механизмы retry, dead letter queue |

### Режимы развертывания

#### Agent Mode (Агент на каждом хосте)

Vector устанавливается на каждый хост как DaemonSet (Kubernetes) или systemd-сервис (VM).

**Преимущества:**
- Минимальная задержка доставки
- Локальная буферизация при потере сети
- Снижение нагрузки на сеть (сжатие, агрегация на месте)

**Сценарии:**
- Сбор логов с файлов (`/var/log`, journald)
- Сбор метрик с экспортеров
- Отправка напрямую в хранилище или в Kafka

#### Aggregator Mode (Централизованный обработчик)

Vector разворачивается как отдельный сервис/кластер для обработки потоков от агентов.

**Преимущества:**
- Централизованная трансформация и обогащение
- Снижение нагрузки на агенты
- Удобство управления конфигурацией

**Сценарии:**
- Чтение из Kafka и трансформация перед отправкой в хранилище
- Агрегация логов из нескольких кластеров Kubernetes
- Обогащение данными из внешних источников (GeoIP, Kubernetes metadata)

#### Hybrid Mode (Комбинированный)

Агенты собирают и отправляют в Kafka → Aggregator читает из Kafka, трансформирует и отправляет в хранилища.

**Сценарий:** `Fluent Bit → Kafka → Vector → OpenSearch`

Подробный разбор см. в **[Практическом сценарии: Роутер логов из Kafka в OpenSearch](#практический-сценарий-роутер-логов-из-kafka-в-opensearch)**.

---

## Vector Remap Language (VRL

**VRL (Vector Remap Language)** — это предметно-ориентированный язык (DSL) для трансформации данных в Vector. Компилируется в нативный код Rust, обеспечивая высокую производительность и безопасность.

### Основные возможности VRL

1. **Трансформация событий:**
    - Парсинг структурированных данных (JSON, syslog, logfmt, regex)
    - Преобразование типов данных
    - Создание, удаление, переименование полей

2. **Фильтрация и маршрутизация:**
    - Булевы выражения для условий
    - Проверка существования полей (`exists(.field)`)

3. **Библиотека функций:**
    - Парсинг: `parse_json!()`, `parse_syslog!()`, `parse_key_value!()`, `parse_regex!()`
    - Время: `now()`, `parse_timestamp()`, `to_unix_timestamp()`, `strftime()`
    - Строки: `downcase()`, `upcase()`, `split()`, `replace()`, `trim()`
    - Когерция типов: `string!()`, `to_int()`, `to_bool()`
    - Работа с коллекциями: `map_keys()`, `map_values()`, `recursive: true`

### Характеристики VRL

| Характеристика | Описание |
| :--- | :--- |
| **Безопасность** | Проверка типов на этапе компиляции, явная обработка ошибок |
| **Производительность** | Компиляция в Rust, нет GC, нет FFI-накладных расходов |
| **Stateless** | Каждое событие обрабатывается независимо |
| **Ограничения** | Нет пользовательских функций, нет рекурсии, нет состояния между событиями |

**Ограничения намеренные** — обеспечивают безопасность, предсказуемость и высокую производительность.

### Пример VRL-скрипта

```vrl
# Парсинг JSON из поля message
. = parse_json!(string!(.message))

# Обработка timestamp с fallback
parsed_timestamp, err = parse_timestamp(.timestamp, format: "%Y-%m-%dT%H:%M:%S.%fZ")
if err == null {
  .timestamp = to_unix_timestamp(parsed_timestamp)
} else {
  .timestamp = to_unix_timestamp(now())
}

# Рекурсивная замена точек в ключах (для Elasticsearch/OpenSearch)
if exists(.kubernetes.annotations) {
  .kubernetes.annotations = map_keys(.kubernetes.annotations, recursive: true) -> |key| {
    replace(key, ".", "_")
  }
}

# Удаление ненужных полей
del(.p)
del(@timestamp)

# Преобразование строки
.message = downcase(string!(.message))
```

**Инструменты для работы с VRL:**
- **[VRL Playground](https://vrl.dev)** — онлайн-песочница для тестирования
- **[VSCode Extension](https://marketplace.visualstudio.com/items?itemName=oryanp.vscode-vrl)** — подсветка синтаксиса и автодополнение

---

## Практические сценарии

### Конфигурация Vector

Vector использует формат **TOML** (`vector.toml`) для конфигурации. Конфигурация состоит из секций `[sources]`, `[transforms]`, и `[sinks]`, которые связываются через параметры `inputs`.

**Пример базовой конфигурации:**

```toml
# Источник: чтение логов из файлов
[sources.app_logs]
  type = "file"
  include = ["/var/log/app/*.log"]

# Трансформация: парсинг JSON и добавление поля
[transforms.parse_json]
  type = "remap"
  inputs = ["app_logs"]
  source = '''
    . = parse_json!(string!(.message))
    .processed_at = now()
  '''

# Приемник: отправка в Elasticsearch
[sinks.elasticsearch]
  type = "elasticsearch"
  inputs = ["parse_json"]
  endpoint = "http://elasticsearch:9200"
  index = "app-logs-%Y.%m.%d"
```

Для Kubernetes рекомендуется использовать Helm-чарт с передачей конфигурации через `values.yaml`.

---

### Практический сценарий: Роутер логов из Kafka в OpenSearch

**Архитектура:** `Fluent Bit → Kafka → Vector → OpenSearch`

#### Проблема

1. **Масштабируемость:** При высоких нагрузках прямой поток от агентов к хранилищу приводит к потере данных. Kafka используется как буфер.
2. **Ограничения агентов:** Легковесные агенты (Fluent Bit) не умеют читать из Kafka — только отправляют.
3. **Совместимость данных:** Поля с точками (`annotations.kubernetes.io/name`) не индексируются в Elasticsearch/OpenSearch.

#### Решение с помощью Vector

Vector выступает как «мост», который забирает данные из Kafka, трансформирует и отправляет в OpenSearch.

**Конфигурация (Helm values.yaml):**

```yaml
customConfig:
  sources:
    kube_logs:
      type: kafka
      bootstrap_servers: "kafka-broker.kafka.svc:9092"
      topics: ["kube"]
      group_id: "vector-loggers"
    host_logs:
      type: kafka
      bootstrap_servers: "kafka-broker.kafka.svc:9092"
      topics: ["host"]
      group_id: "vector-loggers"

  transforms:
    process_kube_logs:
      type: remap
      inputs: ["kube_logs"]
      source: |
        # Распаковка JSON из Kafka-сообщения
        . = parse_json!(.message)

        # Удаление ненужных полей
        remove(.p)
        remove(@timestamp)

        # Рекурсивная замена точек на подчеркивания в ключах
        if exists(.kubernetes.labels) {
          .kubernetes.labels = map_keys(.kubernetes.labels, recursive: true) -> |key| {
            replace(key, ".", "_")
          }
        }
        if exists(.kubernetes.annotations) {
          .kubernetes.annotations = map_keys(.kubernetes.annotations, recursive: true) -> |key| {
            replace(key, ".", "_")
          }
        }

  sinks:
    opensearch_sink:
      type: elasticsearch
      inputs: ["process_kube_logs"]
      endpoint: "https://opensearch-master.logging.svc:9200"
      index: "kube-{{`{{ EventTime }}`|strftime(format:`%Y.%m.%d`)}}"
      tls:
        verify: false  # Только для dev-среды!
      auth:
        strategy: basic
        user: "admin"
        password: "admin_password"
```

**Ключевые моменты трансформации:**

| Команда | Назначение |
| :--- | :--- |
| `. = parse_json!(.message)` | Распаковка JSON из поля `message` в корневой объект |
| `map_keys(..., recursive: true)` | Рекурсивный обход всех вложенных ключей |
| `replace(key, ".", "_")` | Замена точек на подчеркивания для совместимости с ES/OS |
| `remove(.field)` | Удаление ненужных полей для экономии места |

**Преимущества архитектуры:**

- **Масштабируемость:** Каждый компонент масштабируется независимо
- **Гибкость:** Централизованная обработка в Vector позволяет менять логику без изменения конфигурации агентов
- **Надежность:** Kafka сохраняет данные при недоступности OpenSearch

---

### Практический сценарий: Сбор метрик с Prometheus endpoints

Vector может собирать метрики с Prometheus-экспортеров и отправлять их в удаленное хранилище.

```toml
[sources.prometheus]
  type = "prometheus_scrape"
  endpoints = [
    "http://node-exporter:9100/metrics",
    "http://cadvisor:8080/metrics"
  ]

[transforms.aggregate]
  type = "metric_to_log"
  inputs = ["prometheus"]

[sinks.loki]
  type = "loki"
  inputs = ["aggregate"]
  endpoint = "http://loki:3100"
  labels = {job = "metrics"}
```

---

### Практический сценарий: Обогащение логов GeoIP

Vector может обогащать логи данными GeoIP на основе IP-адресов.

```toml
[sources.app]
  type = "file"
  include = ["/var/log/app/access.log"]

[transforms.geoip]
  type = "remap"
  inputs = ["app"]
  source = '''
    .geo = parse_groks!(.client_ip, patterns: [
      "%{IPORHOST:client_ip}"
    ])
    .geo.city = get_geoip_city(.client_ip)  # Требуется база GeoIP
  '''

[sinks.elasticsearch]
  type = "elasticsearch"
  inputs = ["geoip"]
  endpoint = "http://elasticsearch:9200"
  index = "access-logs-%Y.%m.%d"
```

---

## Дополнительная информация

### Сравнение с аналогами

| Характеристика | Vector | Logstash | Fluentd/Fluent Bit | file.d |
| :--- | :--- | :--- | :--- | :--- |
| **Язык** | Rust | Java/JRuby | Ruby/C | Go |
| **Производительность** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Потребление памяти** | Низкое | Высокое | Среднее | Низкое |
| **Экосистема плагинов** | Средняя | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Малая |
| **Конфигурация** | TOML/YAML | DSL (Ruby-like) | DSL | YAML |
| **Язык трансформации** | VRL | Filter-плагины | Record-modifier | Lua/Go |
| **Гарантия доставки** | At-least-once | At-least-once | At-least-once | At-least-once |

#### Vector vs Logstash

- **Vector** превосходит Logstash по производительности (в 5–10 раз) и потреблению ресурсов
- **Logstash** имеет более зрелую экосистему плагинов (200+ против ~100 у Vector)
- **Выбор в пользу Vector:** Высоконагруженные системы, ограниченные ресурсы, безопасность
- **Выбор в пользу Logstash:** Экзотические плагины, legacy-интеграции

> Сравнение подробно разобрано в **[Logstash Overview](../ELK_Stack/Logstash/logstash_overview.md#сравнение-logstash-и-vector)**.

#### Vector vs file.d

- **file.d** — российская альтернатива от OzonTech, также ориентирована на производительность
- **Vector** имеет более богатый функционал трансформаций (VRL vs Lua) и шире распространен
- **Выбор в пользу file.d:** Требования к импортозамещению, простая конфигурация
- **Выбор в пользу Vector:** Сложные трансформации, международная поддержка

> Подробнее о file.d см. в **[file.d Обзор](../FileD/file.d_overview.md)**.

#### Vector vs Fluent Bit

- **Fluent Bit** — сверхлегкий агент (образ ~5 MB), но с ограниченными возможностями трансформации
- **Vector** тяжелее (~30 MB), но предоставляет полноценный язык трансформаций VRL
- **Оптимальная связка:** Fluent Bit как агент → Kafka → Vector как агрегатор

---

### Интеграция с Kubernetes

Vector официально поддерживает развертывание в Kubernetes через Helm-чарт.

**Рекомендуемые паттерны:**

1. **DaemonSet для сбора логов с хостов:**
    - Сбор с `/var/log/pods/*`
    - Автоматическое обогащение Kubernetes metadata

2. **Deployment для агрегации из Kafka:**
    - Горизонтальное масштабирование по CPU/RAM
    - Consumer groups для балансировки нагрузки

3. **StatefulSet для stateful-источников:**
    - Персистентный буфер на диске
    - Гарантированная доставка при перезапусках

---

### Миграция с других инструментов

#### С Logstash на Vector

1. Экспорт конфигурации Logstash (pipeline, фильтры)
2. Переписывание фильтров на VRL (синтаксис отличается)
3. Тестирование на параллельном потоке данных
4. Переключение трафика через балансировщик

#### С Fluent Bit на Vector

1. Fluent Bit уже может работать как агент — замена не требуется
2. Vector разворачивается как агрегатор вместо Fluentd
3. Постепенная миграция sink'ов

---

### Ресурсы

- **[Официальная документация](https://vector.dev/docs/)** — полные docs, tutorials, API reference
- **[VRL Playground](https://vrl.dev)** — онлайн-песочница для тестирования скриптов
- **[GitHub Repository](https://github.com/vectordotdev/vector)** — исходный код, issues, RFC
- **[Vector Discord](https://discord.gg/vectordotdev)** — сообщество для вопросов

---

### Связанные заметки

| Тема | Ссылка |
| :--- | :--- |
| Observability (4 столпа) | **[Обзор Observability](../Concepts/Observability_and_Monitoring/observability_overview.md)** |
| Архитектура сбора логов | **[Проектирование высоконагруженного мониторинга](../Concepts/Observability_and_Monitoring/designing_high-load_monitoring_in_distributed_systems.md)** |
| Пайплайн Fluent Bit → Kafka → Vector | **[Tutorial](../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md)** |
| Сравнение с Logstash | **[Logstash Overview](../ELK_Stack/Logstash/logstash_overview.md)** |
| Альтернатива file.d | **[file.d Обзор](../FileD/file.d_overview.md)** |
| Хранение в OpenSearch | **[OpenSearch Overview](../ELK_Stack/OpenSearch/opensearch_overview.md)** |
| Хранение в Loki | **[Loki Overview](../Loki/loki_overview.md)** |
