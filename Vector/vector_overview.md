# Определения

**Vector** — это высокопроизводительный конвейер для сбора, обработки и отправки логов, метрик и событий. Он написан на языке Rust, что обеспечивает высокую производительность и безопасность при работе с памятью.

---

## 1. Основные концепции

### 1.1. Ключевые характеристики

- **Производительность:** Значительно быстрее и менее ресурсоемок по сравнению с альтернативами.
- **Надежность:** Гарантирует доставку данных (at-least-once delivery).
- **Единый инструмент:** Может выполнять роль как легковесного агента (замена Filebeat/Fluent Bit), так и агрегатора (замена Logstash/Fluentd).

### 1.2. Архитектура

Архитектура Vector концептуально похожа на Logstash и состоит из трех компонентов:

1. **Sources (Источники):** Определяют, откуда Vector будет получать данные (например, файлы, сокеты, Kafka, HTTP).
2. **Transforms (Преобразования):** Позволяют модифицировать, фильтровать и обогащать данные в процессе их передачи.
3. **Sinks (Приемники):** Определяют, куда Vector будет отправлять обработанные данные (например, Elasticsearch, Loki, Kafka, ClickHouse).

---

## 2. Практические сценарии

### 2.1. Конфигурация

- Vector использует формат **TOML** (`vector.toml`) для конфигурации, который является более строгим и читаемым по сравнению с другими форматами.
- Конфигурация состоит из секций `[sources]`, `[transforms]`, и `[sinks]`, которые связываются между собой через параметры `inputs`.

### 2.2. Пример преобразования (VRL)

Vector использует язык **VRL (Vector Remap Language)** для сложных преобразований данных. Это мощный и безопасный язык, специально разработанный для обработки событий.

```toml
[transforms.my_transform]
  type = "remap"
  inputs = ["my_source"]
  source = '''
  # Преобразование VRL
  .message = "processed: " + .message
  .new_field = "hello world"
  '''
```

### 2.3. Практический сценарий: Роутер логов из Kafka в OpenSearch

Один из мощных сценариев использования Vector — в роли **агрегатора-трансформера** в конвейере логирования, например, в связке `Fluent Bit -> Kafka -> Vector -> OpenSearch`.

#### Проблема

1.  **Масштабируемость**: При высоких нагрузках прямой поток логов от агентов (Fluent Bit) к хранилищу (OpenSearch) может привести к потере данных, если хранилище не справляется с потоком записи. Kafka используется как буфер для решения этой проблемы.
2.  **Ограничения агентов**: Некоторые легковесные агенты, как Fluent Bit, исторически не умели читать данные из Kafka. Они могут только отправлять данные в Kafka.
3.  **Совместимость данных**: Поля в JSON-логах, особенно метаданные Kubernetes, часто содержат точки (`.`), например, `annotations.kubernetes.io/name`. Elasticsearch/OpenSearch не могут индексировать такие поля, что приводит к потере части лога.

#### Решение с помощью Vector

Vector выступает в роли "моста", который забирает данные из Kafka, преобразует их и отправляет в OpenSearch.

**Конфигурация (в формате `yaml` для Helm-чарта):**

```yaml
customConfig:
  # 1. Источники данных: читаем из топиков Kafka
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

  # 2. Трансформации: магия VRL для исправления данных
  transforms:
    process_kube_logs:
      type: remap
      inputs: ["kube_logs"]
      source: |
        # Шаг 1: Распарсить сообщение из Kafka и сделать его корнем (.)
        # Сообщение от Fluent Bit приходит как JSON внутри поля "message"
        . = parse_json!(.message)

        # Шаг 2: Удалить ненужные поля
        remove(.p)
        remove(@timestamp)

        # Шаг 3: Рекурсивно заменить точки на подчеркивания в ключах
        # Это критически важно для совместимости с Elasticsearch/OpenSearch!
        if exists(.kubernetes.labels) {
          .kubernetes.labels = map_keys(.kubernetes.labels, recursive: true) -> |key| { replace(key, ".", "_") }
        }
        if exists(.kubernetes.annotations) {
          .kubernetes.annotations = map_keys(.kubernetes.annotations, recursive: true) -> |key| { replace(key, ".", "_") }
        }

  # 3. Приемники: отправляем обработанные логи в OpenSearch
  sinks:
    opensearch_sink:
      type: elasticsearch # Используется общий драйвер
      inputs: ["process_kube_logs"]
      endpoint: "https://opensearch-master.logging.svc:9200"
      index: "cube-{{`{{ EventTime }}`|strftime(format:`%Y.%m.%d`)}}"
      # Отключаем проверку TLS для самоподписанных сертификатов в dev-среде
      tls:
        verify: false
      auth:
        strategy: basic
        user: "admin"
        password: "admin_password"
```

**Ключевые моменты трансформации:**

*   `. = parse_json!(.message)`: Сообщение из Kafka содержит обертку с метаданными. Полезная нагрузка (сам лог от Fluent Bit) находится в поле `message`. Эта команда распаковывает JSON из `message` и делает его новым корневым объектом.
*   `map_keys(..., recursive: true)`: Эта функция рекурсивно обходит все вложенные ключи в полях `kubernetes.labels` и `kubernetes.annotations`.
*   `replace(key, ".", "_")`: Заменяет каждую точку в имени ключа на подчеркивание, решая проблему совместимости.

---

# Дополнительная информация

## Сравнение с аналогами

Vector является отличным выбором для высоконагруженных систем, где критически важны производительность и эффективное использование ресурсов.

- **Logstash**: Vector значительно превосходит Logstash по производительности, но имеет менее зрелую экосистему плагинов.
    > Подробное сравнение доступно в заметке: **[Сравнение Logstash и Vector](../ELK_Stack/Logstash/logstash_overview.md#32-сравнение-logstash-и-vector)**.

- **file.d**: Быстрая альтернатива от OzonTech, также написанная с упором на производительность.
    > Подробности в заметке: **[file.d Обзор](../FileD/file.d_overview.md)**.
