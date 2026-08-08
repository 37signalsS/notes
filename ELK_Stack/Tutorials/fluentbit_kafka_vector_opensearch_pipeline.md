# Руководство: Высоконагруженный конвейер логов (Fluent Bit, Kafka, Vector, OpenSearch)

> Эта заметка является SSoT (авторитетным источником) по построению масштабируемых систем сбора логов в архитектуре "Edge → Transport → Aggregator → Storage". Она описывает интеграцию современных компонентов (Fluent Bit 3.x, Kafka 3.x, Vector 0.40+, OpenSearch 3.x) с упором на протокол OpenTelemetry (OTel).

## Определения

* **Конвейер логов (Logging Pipeline)** — последовательность этапов обработки данных. Типовой стек 2026 года: `Edge Agent (Fluent Bit) → Buffer (Kafka) → Heavy Transformer (Vector) → Search AI Platform (OpenSearch)`.
* **OTLP (OpenTelemetry Protocol)** — открытый стандарт передачи телеметрии (логов, метрик, трассировок), ставший основным протоколом взаимодействия в современных конвейерах.
* **VRL (Vector Remap Language)** — выражено-ориентированный, типобезопасный язык трансформации данных в Vector; VRL-программы компилируются в нативный код Rust при старте Vector, обеспечивая производительность уровня Rust и безопасность типов. Подробнее: **[Язык VRL](../../Vector/vrl_language.md)**.
* **Противодавление (Backpressure)** — состояние, при котором приемник не успевает обрабатывать данные. В данном конвейере Kafka выступает основным буфером, изолирующим Edge-агентов от проблем хранилища.
* **Dead Letter Queue (DLQ)** — механизм перенаправления событий, которые не удалось распарсить или доставить, во вторичное хранилище (например, S3) для последующего анализа.

## Основные концепции

### Архитектура и поток данных

В высоконагруженных системах (High Load) прямая отправка логов в OpenSearch недопустима из-за риска потери данных при всплесках трафика (bursts).

1.  **Edge Layer (Сбор)**: Fluent Bit 3.x работает как OTel-native агент, минимизируя нагрузку на CPU/RAM узла.
2.  **Transport Layer (Буфер)**: Kafka обеспечивает персистентность. Даже при полной остановке OpenSearch на 24 часа, логи сохраняются в топиках.
3.  **Aggregation Layer (Трансформация)**: Vector вычитывает данные, нормализует их к единому стандарту (ECS/OTel) и выполняет тяжелые вычисления (GeoIP, декодирование стектрейсов).
4.  **Storage Layer (Аналитика)**: OpenSearch 3.x индексирует данные, поддерживая поиск на базе ИИ и эффективное сжатие (Parquet-backed storage).

### Роли и характеристики компонентов

| Компонент | Язык / Технология | Роль в 2026 году | Ключевая фича |
| :--- | :--- | :--- | :--- |
| **Fluent Bit** | C | Легкий Edge-агент | SQL Processor на стороне Edge |
| **Kafka** | Java / Scala | Durability Buffer | Zstd сжатие и Schema Registry |
| **Vector** | Rust | ETL Агрегатор | VRL (безопасные трансформации) |
| **OpenSearch** | Java (Lucene 10) | Search AI Platform | Native OTLP ingestion |

## Практические сценарии

### 1. Настройка Fluent Bit 3.x (Edge)

В современных версиях рекомендуется использовать формат YAML для конфигурации.

```yaml
service:
  flush: 1
  storage.path: /var/log/flb-storage/
  storage.type: filesystem # Защита от OOM при переполнении буфера

pipeline:
  inputs:
    - name: tail
      path: /var/log/containers/*.log
      multiline.parser: docker, cri

  filters:
    - name: kubernetes
      match: "*"
    - name: rewrite_tag
      match: "*"
      rule: $level ^(error|critical)$ logs.priority true
    
  outputs:
    - name: kafka
      match: "*"
      brokers: kafka-prod:9092
      topic: logs-k8s-raw
      rdkafka.compression.codec: zstd
      rdkafka.acks: 1
      threaded: "on"
```

### 2. Конфигурация Kafka (Буфер)

Для Production-сред топики логов должны иметь:
*   **Partitions**: Равно или кратно количеству инстансов Vector (например, 12 партиций на 3 инстанса Vector).
*   **Retention**: Минимум 24 часа (`retention.ms=86400000`).
*   **Compression**: `compression.type=zstd` для максимальной экономии места.

### 3. Настройка Vector (Агрегатор и Трансформатор)

Vector преобразует сырой JSON из Kafka в структурированный OTel-формат.

```toml
[sources.kafka_in]
type = "kafka"
bootstrap_servers = "kafka-prod:9092"
group_id = "vector-aggregator"
topics = ["logs-k8s-raw"]

[transforms.vrl_processing]
type = "remap"
inputs = ["kafka_in"]
source = """
# Парсинг сообщения
.message, err = parse_json(.message)
if err != null {
    log("Failed to parse JSON: " + err, level: "error")
    .status = "error_parsing"
}

# Нормализация метаданных (OTel-style)
.service.name = .kubernetes.container_name
.host.hostname = .kubernetes.host
del(.kubernetes)

# Удаление лишнего
del(.kafka_metadata)
"""

[sinks.opensearch_out]
type = "elasticsearch" # Совместим с OpenSearch 3.x
inputs = ["vrl_processing"]
endpoints = ["https://opensearch:9200"]
mode = "data_stream"
auth.strategy = "basic"
auth.user = "${OS_USER}"
auth.password = "${OS_PASS}"
bulk.index_configs = false # Отключаем в пользу Data Streams
```

## Дополнительная информация

### Мониторинг конвейера (Observability)

1.  **Consumer Lag**: Самая важная метрика. Если лаг в Kafka растет — Vector не справляется. Решение: добавьте партиции в топик и увеличьте количество реплик Vector.
2.  **Backpressure в Fluent Bit**: Следите за метрикой `fluentbit_storage_layer_chunks_count`. Если она растет, Kafka работает медленно.
3.  **End-to-End Tracing**: Используйте `trace_id` из OpenTelemetry для корреляции лога с конкретным запросом пользователя во всем конвейере.

### Безопасность и отказоустойчивость

*   **Шифрование**: Используйте TLS 1.3 для всех сегментов сети.
*   **Изоляция**: Выделяйте Vector-агрегаторы в отдельный пул узлов (Node Pool), чтобы тяжелые трансформации не влияли на работу приложений.
*   **Схема данных**: Стандартизируйте логи на базе **ECS (Elastic Common Schema)**. Это позволит использовать готовые правила безопасности в OpenSearch Security Analytics.

---
*   **[OpenSearch: Обзор системы](../OpenSearch/opensearch_overview.md)** — архитектура и Data Streams.
*   **[Kafka: Обзор и высокая производительность](../../Kafka/kafka_overview.md)** — как выжать максимум из брокера.
*   **[Vector: Язык VRL](../../Vector/vrl_language.md)** — детальный справочник по функциям.
