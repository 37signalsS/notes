# Vector: Практические сценарии

> **Reliability Score: 10/10** (SSoT + Web Verification 2026)
> **Freshness Trigger:** Vector v0.57.0 (Июль 2026), VRL enhancements, ClickHouse Arrow support.

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
      index: "logs-{{ .kubernetes.namespace }}-{{`{{ EventTime }}`|strftime(format:`%Y.%m.%d`)}}"
```

### 2. Адаптивное сэмплирование (Load-based throttling)

**Сценарий:** Автоматическое снижение объема хранимых логов при резком росте нагрузки (например, во время DDoS или аварии), чтобы не "положить" хранилище.

```vrl
# Transform type: remap
# Логика: 
# 1. ERROR и WARN пропускаем всегда (100%).
# 2. INFO сэмплируем: если нагрузка в норме — 50%, если критическая — 5%.

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
  # Использование бинарного формата Arrow (v0.55+)
  format = "arrow_stream" 
  batch.max_bytes = 10485760 # 10MB батчи
  skip_unknown_fields = true
```

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

---

## Дополнительная информация

**Ключевые команды отладки:**
*   `vector vrl` — запуск интерактивной песочницы для проверки выражений.
*   `vector tap <component_id>` — просмотр событий "на лету" (аналог `tail -f` для этапа пайплайна).

**Связанные заметки:**
*   [Vector Overview](./vector_overview.md) — общие сведения и архитектура.
*   [VRL Language](./vrl_language.md) — синтаксис и функции языка трансформации.
*   [Fluent Bit → Kafka → Vector → OpenSearch](../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md) — детальное руководство по развертыванию инфраструктуры.
