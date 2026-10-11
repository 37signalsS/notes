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

**Fan-out (множественные выходы):** Vector поддерживает произвольное ветвление — один source может питать несколько transforms или sinks одновременно. Это позволяет дублировать поток: например, отправлять логи и в Loki, и в Elasticsearch, и в локальный файл без промежуточного копирования.

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
type = "elasticsearch"
inputs = ["parse_json"]
endpoints = ["https://os.example.com:9200"]
mode = "data_stream"
index = "logs-app-default"
```

### Источники (Sources)

Vector предоставляет разнообразные источники для сбора логов и метрик с хостов, контейнеров и внешних систем:

*   **`file`** — чтение текстовых логов из файлов. Ключевые параметры:
    *   `ignore_not_found` — пропускать отсутствующие файлы (полезно при ротации).
    *   `ignore_older` — игнорировать файлы, не модифицированные дольше N секунд (критично при logrotate).
    *   `start_at_beginning` — начать чтение с начала файла (`false` — только новые события).
    *   `max_line_bytes` — максимальный размер строки (по умолчанию 1 MiB).
    *   `multiline` — конфигурация склейки многострочных логов (Java stack traces, Python traceback).
*   **`journald`** — чтение из systemd-journald. Параметры: `include_units`, `exclude_units`, `priority` (числовой фильтр по приоритету).
*   **`syslog`** — чтение из Unix domain socket (`/dev/log`) или TCP/UDP.
*   **`tcp`** / **`udp`** — сетевые источники для кастомных протоколов и агентов.
*   **`prometheus_scrape`** — активный сбор метрик по HTTP с заданным интервалом.
*   **`internal_metrics`** — метрики самого Vector (component_errors, buffer sizes и т.д.).
*   **`internal_logs`** — логи самого Vector (для self-observability).

### Преобразования (Transforms) — расширение

Помимо `remap`, Vector предоставляет специализированные преобразования:

*   **`filter`** — безусловное отсеивание событий по VRL-условию. Оставляет только прошедшие проверку события.
*   **`route`** — ветвление потока по нескольким условиям. Каждый именованный выход получает только события, соответствующие его выражению.
*   **`throttle`** — ограничение количества событий в единицу времени (окно сброса + лимит). Защищает хранилище от всплесков.
*   **`dedupe`** — удаление дубликатов по хешу всего события или по указанным полям. Окно запоминания задаётся параметром `expire_after`.
*   **`reduce`** — агрегация событий за скользящее или фиксированное окно времени. Поддерживает стратегии `sum`, `last`, `min`, `max`, `mean` для числовых полей.
*   **`tag_cardinality_limit`** — защита от взрыва кардинальности метрик. Отбрасывает новые уникальные значения тегов при превышении лимита.
*   **`regex_parser`** / **`json_parser`** — специализированные парсеры с предкомпилированными регулярными выражениями или декодерами JSON для производительности.

### Буферизация и backpressure

Каждый Sink может иметь собственный буфер между transform-ом и отправкой:

*   **`buffer.type = "memory"`** (по умолчанию) — быстрый, но данные теряются при аварийном перезапуске.
*   **`buffer.type = "disk"`** (`max_size`, `when_full = "block"` / `drop_newest`) — персистентный сброс на диск, гарантия **at-least-once** delivery. Рекомендуется для критичных пайплайнов (Kafka → OpenSearch, audit логи).

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
      endpoints: ["https://opensearch:9200"]
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
# Полная сигнатура: table, condition, select (подмножество полей), wildcard-подстановка
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

> **Примечание:** Для обратного преобразования (логи → метрики) используется transform `log_to_metric`. Он удобен для создания SLI/SLO из логов об ошибках.

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
    endpoints: ["https://es:9200"]
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

### 9. Fan-out: один источник → несколько хранилищ

**Сценарий:** Отправить логи одновременно в Loki для поиска, в Elasticsearch для полнотекстового поиска и в локальный файл для аудита. Это типичная архитектура для средних инфраструктур, где требуется единый сбор с последующим распределением.

```toml
[sources.app]
  type = "file"
  include = ["/var/log/app/*.log"]

[transforms.parse]
  type = "remap"
  inputs = ["app"]
  source = "."

[sinks.loki]
  type = "loki"
  inputs = ["parse"]
  endpoint = "http://loki:3100"
  labels = { app = "myapp", host = "${HOSTNAME}" }

[sinks.elastic]
  type = "elasticsearch"
  inputs = ["parse"]
  endpoints = ["http://es:9200"]
  index = "app-logs-%Y.%m.%d"
  compression = "gzip"

[sinks.file_audit]
  type = "file"
  inputs = ["parse"]
  path = "/var/log/vector/audit.log"
  encoding.codec = "json"
```

**Валидация:**
```bash
vector validate /etc/vector/vector.yaml
# → код возврата 0

# Проверяем, что события доходят во все sinks:
vector tap parse
# → должны появляться события в tap
```

### 10. Обработка ротированных логов (file source)

**Сценарий:** Читать логи приложения, которое использует logrotate, без потерь и дублирования при смене файла. Это критично для production-систем, где ротация происходит ежедневно или по размеру.

```toml
[sources.app]
  type = "file"
  include = ["/var/log/app/*.log"]
  ignore_not_found = true
  ignore_older = 86400  # Не читать файлы, не модифицированные 24h
  start_at_beginning = false  # Начать с конца (только новые события)
  max_line_bytes = 1048576  # 1 MiB лимит на строку

  # Для multiline (Java stack traces, Python traceback):
  # multiline.condition = { type = "regexp", pattern = "^\s", mode = "continue" }
```

**Ключевые параметры:**
*   `ignore_older` — предотвращает повторное чтение уже ротированных файлов. Значение должно превышать интервал ротации (например, при daily-ротации ставьте ≥ 86400).
*   `start_at_beginning = false` — Vector игнорирует существующие данные и читает только новые строки (аналогично `tail -F`).
*   `max_line_bytes` — защита от OOM при попадании в лог бинарного мусора или гигантских JSON.

**Валидация:**
```bash
# После logrotate:
ls -la /var/log/app/
# vector должен начать читать новый файл автоматически

vector tap app
# → новые события появляются без дублей
```

### 11. Deduplication идентичных событий

**Сценарий:** Убрать дублирующиеся события при сбое с сетевого хранилища, перезапуске источника или при использовании нескольких Vector-агентов на одном хосте (не рекомендуется, но бывает).

```toml
[transforms.dedup]
  type = "dedupe"
  inputs = ["app_logs"]
  key = "$$.hash"  # Хеш всего события; или укажите поле: key = ".message"
  expire_after = 60  # Окно запоминания (сек)
```

**Мониторинг:**
```bash
curl -s http://localhost:9598/metrics | grep component_deduced_events_total
# → количество отброшенных дубликатов
```

**Ограничения:**
*   Окно `expire_after` хранится в памяти. При больших окнах (>300с) потребление RAM растёт пропорционально уникальным событиям.
*   Для распределённых систем лучше использовать идемпотентные ключи на стороне источника.

### 12. Агрегация через reduce

**Сценарий:** Сворачивать метрики или события за фиксированное окно времени для снижения нагрузки на хранилище и соблюдения retention-политик.

```toml
[transforms.rollup_cpu]
  type = "reduce"
  inputs = ["host_metrics"]
  key = "$$.metric"  # Группируем по имени метрики
  period = 60s  # Окно агрегации
  merge_strategy = "last"  # Для gauge; для counter — "sum"
```

**Примеры стратегий:**
*   `last` — последнее значение за окно (для gauge: memory_used, cpu_usage).
*   `sum` — сумма всех значений (для counters: bytes_sent_total).
*   `min` / `max` / `mean` — статистические агрегаты.

### 13. Ограничение кардинальности (tag_cardinality_limit)

**Сценарий:** Предотвратить взрыв кардинальности, когда в логах появляется уникальный `request_id`, `trace_id` или другие высоковариативные поля, которые разрушают индексы Loki/Elasticsearch.

```toml
[transforms.limit_card]
  type = "tag_cardinality_limit"
  inputs = ["app_logs"]
  cardinality_limit = 1000  # Макс. уникальных значений на тег
  mode = "monotonic_cache"  # Запоминать и отбрасывать новые
```

**Режимы работы:**
*   `monotonic_cache` — кеширует уникальные значения; новые отбрасываются с логированием.
*   `expire_after` — автоматически очищает кеш через заданный период (для долгоживущих процессов).

### 14. Парсинг nginx access.log

**Сценарий:** Из plain-text access.log nginx извлечь статус, URL, user-agent, время ответа и отправить в Loki с нормализованными полями.

```toml
[sources.nginx]
  type = "file"
  include = ["/var/log/nginx/access.log"]
  ignore_older = 86400

[transforms.parse_nginx]
  type = "remap"
  inputs = ["nginx"]
  source = '''
    # Парсим стандартный combined format
    . = parse_nginx_log!(.message, format: "combined")
    # Fallback если парсер не сработал
    if !exists(.request) {
      abort
    }
  '''

[transforms.enrich_nginx]
  type = "remap"
  inputs = ["parse_nginx"]
  source = '''
    # Сокращаем длинный user-agent
    .user_agent_short = .http_user_agent ?? "unknown"
    del(.http_user_agent)
    
    # Вычисляем bucket статуса
    .status_class = to_int!(.status) -> {
      0: "error",
      1: "error",
      2: "success",
      3: "success",
      4: "client_error",
      5: "server_error"
    }
  '''

[sinks.loki_nginx]
  type = "loki"
  inputs = ["enrich_nginx"]
  endpoint = "http://loki:3100"
  labels = { service = "nginx", host = "${HOSTNAME}" }
```

**Валидация:**
```bash
vector tap parse_nginx
# → {"request":"GET /healthz 200","status":"200","status_class":"success",...}
```

### 15. Сбор kernel/dmesg и hardware events

**Сценарий:** Собирать логи ядра с bare-metal серверов для диагностики hardware проблем, OOM-killer и модулей ядра.

```toml
[sources.kernel]
  type = "file"
  include = ["/var/log/kern.log", "/var/log/dmesg"]
  ignore_older = 86400

[transforms.normalize_kernel]
  type = "remap"
  inputs = ["kernel"]
  source = '''
    # Приводим приоритет к стандартным уровням
    if exists(.priority) {
      .severity = to_int!(.priority)
      .level = {
        0: "emerg", 1: "alert", 2: "crit", 3: "err",
        4: "warning", 5: "notice", 6: "info", 7: "debug"
      }[.severity] ?? "info"
    }
    .facility = "kernel"
    
    # Извлекаем модуль ядра из сообщения
    .module = capture(.message, r'^(\w+):')?.[0] ?? "kernel"
  '''

[sinks.loki_kernel]
  type = "loki"
  inputs = ["normalize_kernel"]
  endpoint = "http://loki:3100"
  labels = { facility = "kernel", host = "${HOSTNAME}" }
```

**Практическое применение:**
*   OOM-killer: `kern.log` содержит `Out of memory: Kill process`.
*   Hardware errors: `mce` [Machine Check Exception] для диагностики памяти/CPU.
*   Module load/unload: отслеживание загрузки модулей ядра.

### 16. vector test: тестирование route и filter

**Сценарий:** Расширить покрытие тестами, проверив ветвление по `route` и отсев через `filter`.

```toml
[[tests]]
  name = "route_errors_to_es"
  [tests.input]
    insert_at = "split_logs"
    type = "raw"
    value = '{"level":"error","message":"boom"}'
  [[tests.outputs]]
    extract_from = "split_logs.errors"
    [[tests.outputs.conditions]]
      type = "vrl"
      source = '.level == "error"'
  [[tests.outputs]]
    extract_from = "split_logs.info"
    expected_event_count = 0  # error не должен попасть в info

[[tests]]
  name = "filter_dropped"
  [tests.input]
    insert_at = "filter_debug"
    type = "raw"
    value = '{"level":"debug","message":"hello"}'
  [[tests.outputs]]
    extract_from = "filter_debug"
    expected_event_count = 0  # debug логи отброшены

[[tests]]
  name = "sample_count_check"
  [tests.input]
    insert_at = "adaptive_sample"
    type = "raw"
    value = '{"level":"info","message":"test"}'
  [[tests.outputs]]
    extract_from = "adaptive_sample"
    expected_event_count = 1  # или 0, в зависимости от sampling_rate
```

### 17. Тюнинг производительности: batch и concurrency

**Сценарий:** Оптимизировать пропускную способность Vector на хосте с высокой нагрузкой (10K+ событий/сек) без увеличения потребления RAM.

```toml
# Глобальные параметры (в [global] секции)
[global]
  data_dir = "/var/lib/vector"

# Настройки batch для снижения количества запросов
[buffer]
  type = "memory"
  max_events = 1000
  max_bytes = 10485760  # 10 MiB

# Адаптивный контроль concurrency
[transforms.parse]
  type = "remap"
  inputs = ["app_logs"]
  source = "."

[sinks.loki]
  type = "loki"
  inputs = ["parse"]
  endpoint = "http://loki:3100"
  compression = "gzip"
  
  batch = {
    max_bytes = 10485760,  # 10 MiB
    timeout_secs = 2       # Flush каждые 2с или при заполнении
  }
  
  request = {
    concurrency = "adaptive"  # Автоподстройка под нагрузку
    max_concurrency = 8       # Лимит для защиты Loki
    timeout_secs = 10
  }
```

**Рекомендации:**
*   `batch.timeout_secs` — уменьшайте для низкой задержки (1-2с), увеличивайте для высокой пропускной способности (5-10с).
*   `request.concurrency = "adaptive"` — Vector автоматически регулирует параллельные запросы на основе `component_sent_events_total` и `component_received_events_total`.
*   `compression = "gzip"` — снижает сетевой трафик на 60-80% для текстовых форматов.

---

## Дополнительная информация

### Ключевые команды отладки

*   `vector validate [--no-environment] [--deny-warnings]` — проверка конфигурации на корректность без запуска (заменяет прежнюю `vector check`). `--no-environment` пропускает проверки окружения.
*   `vector graph` — вывод топологии в формате DOT (GraphViz) для визуализации DAG.
*   `vector vrl` — запуск интерактивной песочницы REPL для проверки выражений (с v0.56 включает полный набор функций).
*   `vector tap <component_id>` — просмотр событий "на лету" на этапе пайплайна (аналог `tail -f`).
*   `vector top` — визуализация топологии и нагрузки в реальном времени (через gRPC API).
*   `vector remap <expr>` — однострочное применение VRL-выражения к JSON-событию (удобно для отладки).
*   `vector convert <input> <output>` — конвертация конфигурации между форматами TOML/YAML/JSON.

### Health checks и управление службой

Vector поставляется с systemd-юнитом (`/etc/systemd/system/vector.service`). Для production рекомендуется настроить:

```ini
# /etc/systemd/system/vector.service.d/restart.conf
[Service]
Restart=on-failure
RestartSec=5
LimitNOFILE=65536
Environment="HOSTNAME=%H"
```

Проверка работоспособности:
```bash
systemctl status vector
# → active (running)

# Health endpoint (если включен http API):
curl -s http://localhost:9598/health
# → {"status":"healthy"}
```

Горячая перезагрузка без потерь:
```bash
systemctl reload vector
# → читает новый конфиг, сохраняя буферы
```

### Интерполяция переменных окружения (v0.57+)

`${VAR}` в конфигурации отключена по умолчанию — включение только через `--dangerously-allow-env-var-interpolation` (см. [Vector Overview](./vector_overview.md), раздел «Безопасность»).

### Связанные заметки

*   [Vector Overview](./vector_overview.md) — общие сведения и архитектура.
*   [VRL Language](./vrl_language.md) — синтаксис и функции языка трансформации.
*   [Логирование: глубокое погружение](../Concepts/Observability_and_Monitoring/logs_deep_dive.md) — сценарии централизованного логирования bare-metal, маскирования PII и диагностики.
*   [Fluent Bit → Kafka → Vector → OpenSearch](../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md) — детальное руководство по развертыванию инфраструктуры.
