# Vector: Практические сценарии

## Определения

**Конфигурация Vector** — файл (TOML, YAML или JSON), описывающий направленный ациклический граф (DAG) обработки данных.
*   **Sources** — входные данные.
*   **Transforms** — логика обработки и фильтрации.
*   **Sinks** — выходные данные (хранилища, очереди).

---

## Основные концепции

### Топология и связность

Компоненты связываются через параметр `inputs`. Одно преобразование может принимать данные из нескольких источников, а один источник может отправлять данные в несколько преобразований или приёмников одновременно.

**Базовый пример (TOML):**

```toml
[sources.app_logs]
  type = "file"
  include = ["/var/log/app/*.log"]

[transforms.parse_json]
  type = "remap"
  inputs = ["app_logs"]
  source = '''
    . = parse_json!(string!(.message))
    .processed_at = now()
  '''

[sinks.opensearch]
  type = "elasticsearch" # Используется для OpenSearch
  inputs = ["parse_json"]
  endpoint = "https://os.example.com:9200"
  mode = "data_stream"
  index = "logs-app-default"
```

**Буферизация и backpressure.** Каждый Sink может иметь собственный буфер между transform-ом и отправкой:

*   **`buffer.type = "memory"`** (по умолчанию) — быстрый, но данные теряются при аварийном перезапуске.
*   **`buffer.type = "disk"`** (`max_size`, `when_full = "block"` / `drop_newest`) — персистентный сброс на диск, гарантия **at-least-once** delivery. Рекомендуется для критичных пайплайнов (Kafka → OpenSearch).

**Взаимодействие с backpressure:** если Sink не справляется, Vector через adaptive request concurrency автоматически замедляет Sources (например, чтение из Kafka), не теряя данные.

---

## Практические сценарии

### 1. Роутер логов: Kafka → OpenSearch

**Сценарий:** Агрегация логов из высоконагруженного кластера Kubernetes через промежуточный буфер в Kafka.

**Задача:**
1.  Вычитывание из Kafka по Consumer Group.
2.  Парсинг JSON.
3.  Очистка ключей (замена точек на подчеркивания для совместимости с индексацией OpenSearch/Elasticsearch).
4.  Маршрутизация по индексам на основе метаданных.

```yaml
# Пример в формате YAML (часто используется в K8s Helm values)
customConfig:
  sources:
    kafka_in:
      type: kafka
      bootstrap_servers: "kafka-cluster:9092"
      topics: ["kubernetes-logs"]
      group_id: "vector-aggregator-v1"

  transforms:
    process_logs:
      type: remap
      inputs: ["kafka_in"]
      source: |
        # Парсинг основного сообщения
        . = parse_json!(.message)
        
        # Рекурсивная замена точек в ключах (K8s annotations/labels)
        if exists(.kubernetes.labels) {
          .kubernetes.labels = map_keys(.kubernetes.labels, recursive: true) -> |key| {
            replace(key, ".", "_")
          }
        }
        
        # Удаление временных полей
        del(.kafka_metadata)

  sinks:
    os_out:
      type: elasticsearch
      inputs: ["process_logs"]
      endpoint: "https://opensearch:9200"
      compression: "gzip"
      # Шаблон индекса: поле события + strftime-спецификатор (Vector template syntax)
      index: "logs-{{ kubernetes.namespace }}-%Y.%m.%d"
```

### 2. Адаптивное сэмплирование (Load-based throttling)

**Сценарий:** Автоматическое снижение объема хранимых логов при резком росте нагрузки (например, во время DDoS или аварии), чтобы не "положить" хранилище.

Для статистического (probability-based) сэмплирования в Vector также есть встроенный transform **`sample`** с параметром `rate` — он эффективнее ручного VRL-кода при простых постоянных коэффициентах. Пример ниже демонстрирует гибкий вариант на VRL, когда частота может вычисляться динамически (нагрузка, внешние метрики, A/B-тесты).

```vrl
# Transform type: remap
# Логика: 
# 1. ERROR и WARN пропускаем всегда (100%).
# 2. INFO сэмплируем динамически: коэффициент задаётся переменной sampling_rate.

if .level == "ERROR" || .level == "WARN" {
    . = . # Оставляем без изменений
} else {
    # Динамический порог (можно завязать на внешнюю таблицу или метрики)
    sampling_rate = 0.1
    if random_float() > sampling_rate {
        log("Event dropped due to sampling", level: "debug")
        abort # Прерываем обработку события (оно не пойдет в Sink)
    }
}
```

### 3. Обогащение данных через Enrichment Tables

**Сценарий:** Добавление информации о пользователе из внешней базы (GeoIP или внутренний API) без выполнения сетевых запросов на каждое событие.

```toml
# 1. Объявление таблицы (подгружается в память)
[enrichment_tables.user_db]
  type = "file"
  file = { path = "/etc/vector/users.json", format = "json" }
  # Обновление таблицы без перезапуска Vector каждые 5 минут
  refresh_interval_secs = 300

[transforms.enrich_user]
  type = "remap"
  inputs = ["app_logs"]
  source = '''
    # Поиск по ID пользователя
    user_info, err = get_enrichment_table_record("user_db", { "user_id": .user_id })
    if err == null {
        .user_details = user_info
    }
  '''
```

**Сигнатура и дополнительные возможности:**

Функция возвращает **ровно одну** запись: при отсутствии совпадений или нескольких совпадений возвращается ошибка. Если возможны множественные совпадения — используйте `find_enrichment_table_records` (возвращает массив).

```vrl
# Полная сигнатура: table, condition, select (подмножество полей), wildcard (подстановка)
user_info = get_enrichment_table_record!(
    "user_db",
    { "user_id": .user_id },
    select: ["name", "email", "plan"]
)

# wildcard-поиск: сопоставление по префиксу/маске
matches = find_enrichment_table_records!(
    "user_db",
    { "plan": "pro" },
    wildcard: "%"
)
```

Типы enrichment-таблиц: `file` (JSON/CSV), `geoip`/`mmdb` (MaxMind GeoIP — поиск по IP-адресу, одиночное условие `{"ip": .ip}`), а также динамическая перезагрузка через `reload_behavior` (v0.55+).

### 4. Высокопроизводительная доставка: ClickHouse + Arrow

**Сценарий:** Запись миллиардов событий в секунду в ClickHouse с использованием бинарного формата Apache Arrow для минимизации нагрузки на CPU и сеть.

```toml
[sources.high_load_tcp]
  type = "tcp"
  address = "0.0.0.0:9000"
  decoding.codec = "json"

[sinks.clickhouse_heavy]
  type = "clickhouse"
  inputs = ["high_load_tcp"]
  endpoint = "http://clickhouse:8123"
  database = "logs"
  table = "raw_events"
  format = "arrow_stream"    # Apache Arrow IPC streaming format (v0.55+)
  batch_encoding = { codec = "arrow_stream" }
  batch = { max_bytes = 10485760 }  # 10MB батчи
  skip_unknown_fields = true
```

**Особенности `arrow_stream` (v0.55+):**
*   Формат запрашивает схему таблицы у ClickHouse при старте и маппит типы колонок в типы Arrow — лучшая производительность и типизированность по сравнению с JSON.
*   Схема вытягивается **один раз при старте**: имя `table` и `database` должны быть **статическими** (без шаблонов) — динамическая маршрутизация по таблицам с этим форматом не поддерживается.
*   Неподдерживаемые типы колонок: `IPv4`, `IPv6` (для них используйте JSON-формат).

### 5. Сбор метрик и конвертация в логи

**Сценарий:** Сбор метрик из нестандартных источников и их отправка в Loki для анализа вместе с логами.

```toml
[sources.prom_scrape]
  type = "prometheus_scrape"
  endpoints = ["http://app:8080/metrics"]
  scrape_interval_secs = 15

[transforms.m2l]
  type = "metric_to_log"
  inputs = ["prom_scrape"]

[sinks.loki_metrics]
  type = "loki"
  inputs = ["m2l"]
  endpoint = "http://loki:3100"
  labels = { source = "vector_metrics", app = "my_app" }
```

### 6. Маршрутизация по уровням логирования (route)

**Сценарий:** Разбиение единого потока логов на несколько Sink-ов по приоритету: ошибки — в отдельный индекс Elasticsearch/OpenSearch, остальное — в Loki. Для безусловного отбора в один или несколько выходов используется transform **`route`**.

```yaml
transforms:
  split_logs:
    type: route
    inputs: ["app_logs"]
    route:
      errors: '.level == "error" || .level == "crit"'
      info: '.level == "info"'

sinks:
  es_errors:
    type: elasticsearch
    inputs: ["split_logs.errors"]
    endpoint: "https://es:9200"
    index: "app-errors-%Y.%m.%d"

  loki_info:
    type: loki
    inputs: ["split_logs.info"]
    endpoint: "http://loki:3100"
```

Для простого отсева по одному условию существует transform **`filter`** (оставляет только прошедшие условие события), для ветвления по нескольким условиям — **`route`** (каждый именованный выход получает только прошедшие его условие события).

### 7. Наблюдаемость самого Vector (self-observability)

**Сценарий:** Отслеживание работы самого Vector: его логи, метрики компонентов, ошибки конфигурации — используются для SLO/алертов и capacity planning.

```toml
[sources.vector_logs]
  type = "internal_logs"

[sources.vector_metrics]
  type = "internal_metrics"

[sinks.vector_metrics_out]
  type = "prometheus_remote_write"
  inputs = ["vector_metrics"]
  endpoint = "http://prometheus:9090/api/v1/write"
  decimals = 5
```

**Ключевые метрики для мониторинга:**
*   `component_errors_total` — ошибки обработки компонента (включая `confinement_failed` при отклоненных шаблонах, v0.57+).
*   `component_received_events_total` / `component_sent_events_total` — баланс входных/выходных событий.
*   `component_latency_seconds` — время обработки события компонентом.
*   `buffer_size_bytes` — заполненность дисковых/оперативных буферов.

### 8. Unit-тестирование конфигурации (vector test)

**Сценарий:** Автоматизированная проверка VRL-трансформаций и фильтров перед деплоем. Тесты описываются прямо в конфигурационном файле в секции `[[tests]]`.

```toml
[[tests]]
  name = "parse_json_enrich"
  [tests.input]
    insert_at = "enrich_user"
    type = "raw"
    value = '{"user_id": "42", "message": "hello"}'
  [[tests.outputs]]
    extract_from = "enrich_user"
    [[tests.outputs.conditions]]
      type = "vrl"
      source = '''
        .user_details.name == "Alice"
        && is_null(.unused_field)
      '''
```

Также поддерживается проверка **количества** исходящих событий через `expected_event_count` в `[[tests.outputs]]` (например, после сэмплирования) и проверка полного выхода пайплайна. Запуск: `vector test /etc/vector/vector.yaml` — конфигурация возвращает ненулевой код при падении любого теста (используется в CI).

---

## Дополнительная информация

**Ключевые команды отладки:**
*   `vector validate [--no-environment] [--deny-warnings]` — проверка конфигурации на корректность без запуска (заменяет прежнюю `vector check`). `--no-environment` пропускает проверки окружения.
*   `vector graph` — вывод топологии в формате DOT (GraphViz) для визуализации DAG.
*   `vector vrl` — запуск интерактивной песочницы REPL для проверки выражений (с v0.56 включает полный набор функций).
*   `vector tap <component_id>` — просмотр событий "на лету" на этапе пайплайна (аналог `tail -f`).
*   `vector top` — визуализация топологии и нагрузки в реальном времени (через gRPC API).

**Интерполяция переменных окружения (v0.57+):** `${VAR}` в конфигурации отключена по умолчанию — включение только через `--dangerously-allow-env-var-interpolation` (см. [Vector Overview](./vector_overview.md), раздел «Безопасность»).

**Связанные заметки:**
*   [Vector Overview](./vector_overview.md) — общие сведения и архитектура.
*   [VRL Language](./vrl_language.md) — синтаксис и функции языка трансформации.
*   [Fluent Bit → Kafka → Vector → OpenSearch](../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md) — детальное руководство по развертыванию инфраструктуры.
