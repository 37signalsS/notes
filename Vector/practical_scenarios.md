# Vector: Practical Scenarios

## Definitions

**Конфигурация Vector** — TOML/YAML-файл с тремя секциями: `[sources]`, `[transforms]`, `[sinks]`. Компоненты связываются через параметр `inputs`.

---

## Basic Concepts

### Базовая конфигурация

```toml
# Источник: чтение логов из файлов
[sources.app_logs]
  type = "file"
  include = ["/var/log/app/*.log"]

# Трансформация: парсинг JSON
[transforms.parse_json]
  type = "remap"
  inputs = ["app_logs"]
  source = '''
    . = parse_json!(string!(.message))
    .processed_at = now()
  '''

# Приёмник: отправка в Elasticsearch
[sinks.elasticsearch]
  type = "elasticsearch"
  inputs = ["parse_json"]
  endpoint = "http://elasticsearch:9200"
  index = "app-logs-%Y.%m.%d"
```

Для Kubernetes используется Helm-чарт с передачей конфигурации через `values.yaml`.

---

## Practical Scenarios

### Сценарий: Роутер логов из Kafka в OpenSearch

**Архитектура:** `Fluent Bit → Kafka → Vector → OpenSearch`

**Проблема:** прямой поток от агентов к хранилищу при высоких нагрузках приводит к потере данных; поля с точками (`annotations.kubernetes.io/name`) не индексируются в ES/OS.

**Решение** — Vector читает из Kafka, трансформирует через VRL, отправляет в OpenSearch:

```yaml
customConfig:
  sources:
    kube_logs:
      type: kafka
      bootstrap_servers: "kafka-broker.kafka.svc:9092"
      topics: ["kube"]
      group_id: "vector-loggers"

  transforms:
    process_kube_logs:
      type: remap
      inputs: ["kube_logs"]
      source: |
        . = parse_json!(.message)
        remove(.p)
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
```

**Ключевые VRL-команды:**

| Команда | Назначение |
| :--- | :--- |
| `. = parse_json!(.message)` | Распаковка JSON в корневой объект |
| `map_keys(..., recursive: true)` | Рекурсивный обход вложенных ключей |
| `replace(key, ".", "_")` | Замена точек для совместимости с ES/OS |
| `remove(.field)` | Удаление ненужных полей |

Полное руководство с развёртыванием: **[Fluent Bit → Kafka → Vector → OpenSearch Tutorial](../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md)**.

### Сценарий: Сбор метрик с Prometheus endpoints

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

### Сценарий: Обогащение логов GeoIP

GeoIP в VRL выполняется через **enrichment tables**, а не через отдельную функцию:

```toml
# Объявление таблицы GeoIP
[enrichment_tables.geoip_table]
  type = "geoip"
  path = "/usr/share/GeoIP/GeoLite2-City.mmdb"

# Источник
[sources.app]
  type = "file"
  include = ["/var/log/app/access.log"]

# Трансформация с обогащением
[transforms.geoip]
  type = "remap"
  inputs = ["app"]
  source = '''
    .geoip = get_enrichment_table_record!("geoip_table", { "ip": .client_ip })
  '''

# Приёмник
[sinks.elasticsearch]
  type = "elasticsearch"
  inputs = ["geoip"]
  endpoint = "http://elasticsearch:9200"
  index = "access-logs-%Y.%m.%d"
```

Функция `get_enrichment_table_record!` принимает имя таблицы и маппинг полей (`"ip"` — обязательный ключ для GeoIP). Результат — структура с городом, страной, координатами.

---

## Additional Information

**Связанные заметки:** [Vector Overview](./vector_overview.md) — общий обзор; [VRL Language](./vrl_language.md) — язык трансформации; полный туториал пайплайна — [Fluent Bit → Kafka → Vector → OpenSearch](../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md).
