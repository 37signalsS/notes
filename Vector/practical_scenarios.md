# Практические сценарии использования Vector

## Конфигурация Vector

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

## Практический сценарий: Роутер логов из Kafka в OpenSearch

**Архитектура:** `Fluent Bit → Kafka → Vector → OpenSearch`

### Проблема

1. **Масштабируемость:** При высоких нагрузках прямой поток от агентов к хранилищу приводит к потере данных. Kafka используется как буфер.
2. **Ограничения агентов:** Легковесные агенты (Fluent Bit) не умеют читать из Kafka — только отправляют.
3. **Совместимость данных:** Поля с точками (`annotations.kubernetes.io/name`) не индексируются в Elasticsearch/OpenSearch.

### Решение с помощью Vector

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

### Ключевые моменты трансформации

| Команда | Назначение |
| :--- | :--- |
| `. = parse_json!(.message)` | Распаковка JSON из поля `message` в корневой объект |
| `map_keys(..., recursive: true)` | Рекурсивный обход всех вложенных ключей |
| `replace(key, ".", "_")` | Замена точек на подчеркивания для совместимости с ES/OS |
| `remove(.field)` | Удаление ненужных полей для экономии места |

### Преимущества архитектуры

- **Масштабируемость:** Каждый компонент масштабируется независимо
- **Гибкость:** Централизованная обработка в Vector позволяет менять логику без изменения конфигурации агентов
- **Надежность:** Kafka сохраняет данные при недоступности OpenSearch

---

## Практический сценарий: Сбор метрик с Prometheus endpoints

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

## Практический сценарий: Обогащение логов GeoIP

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

## Связанные заметки

| Тема | Ссылка |
| :--- | :--- |
| Vector Overview | **[Vector Overview](../Concepts/vector_overview.md)** |
| VRL Language | **[VRL Language](../VRL/vrl_language.md)** |
| Fluent Bit → Kafka → Vector Pipeline | **[Tutorial](../../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md)** |
