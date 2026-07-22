# Руководство: Построение отказоустойчивого конвейера логов (Fluent Bit, Kafka, Vector, OpenSearch)

> Данное руководство описывает архитектуру и практические шаги по созданию масштабируемого конвейера сбора, обработки и хранения логов. Архитектура ориентирована на высокую доступность и предотвращение потери данных при пиковых нагрузках.

> Базовые понятия: [Fluent Bit](../../Kubernetes/MonitoringLogging/EFK/fluentbit/fluent_comparison.md), [Kafka](../../Kafka/kafka_overview.md), [Vector](../../Vector/vector_overview.md), [OpenSearch](../OpenSearch/opensearch_overview.md).

## Определения

* **Конвейер логов (Logging Pipeline)** — последовательность компонентов для сбора, трансформации и доставки логов. Типовая схема: `Агент → Буфер → Агрегатор → Хранилище`.
* **Асинхронная буферизация** — механизм защиты от потери данных путем использования промежуточного персистентного хранилища (Kafka) между отправителем и получателем.
* **Противодавление (Backpressure)** — состояние системы, при котором принимающий компонент не успевает обрабатывать входящий поток данных, что приводит к заполнению буферов отправителя и потенциальной блокировке или сбросу данных.
* **VRL (Vector Remap Language)** — специализированный язык выражений в Vector для глубокой трансформации, фильтрации и обогащения данных.

## Основные концепции

### Проблема: Потеря данных и нестабильность

Прямая отправка логов (`Агент → Хранилище`) в высоконагруженных системах критически уязвима:
* **Переполнение локальных буферов**: у агентов (Fluent Bit) ограниченный объем RAM/дискового буфера. При недоступности OpenSearch более чем на несколько часов данные будут потеряны.
* **Каскадные сбои**: всплеск трафика (burst) может перегрузить API хранилища, вызывая задержки (latency) и отказы в обслуживании.

### Решение: Kafka как Single Source of Truth для логов

Введение Kafka позволяет разделить (Decoupling) процесс генерации логов и их записи:
1. **Сглаживание пиков**: Kafka принимает данные на скорости диска, позволяя хранилищу обрабатывать их в комфортном темпе.
2. **Множественные потребители**: один поток логов из Kafka может одновременно направляться в OpenSearch для аналитики и в S3 для долгосрочного архива.

**Схема конвейера:**
`Fluent Bit → Kafka (Topics) → Vector (Aggregator) → OpenSearch (Data Streams)`

### Роли компонентов

| Компонент | Роль | Особенности реализации |
| :--- | :--- | :--- |
| **Fluent Bit** | Агент (Edge) | Минимальное потребление ресурсов на хосте. Отправка в Kafka через `rdkafka`. |
| **Kafka** | Персистентный буфер | Хранение логов в партиционированных топиках. Гарантия сохранности данных. |
| **Vector** | Агрегатор | Чтение из Kafka по Consumer Groups. Масштабирование через увеличение реплик. |
| **OpenSearch** | Хранилище | Индексация и поиск. Рекомендуется использование **Data Streams** для логов. |

## Практические сценарии

### 1. Настройка Fluent Bit (Отправитель)

Fluent Bit должен распределять логи по топикам в зависимости от их типа или метаданных приложения.

**Пример `fluent-bit.conf`:**
```ini
[INPUT]
    Name              tail
    Path              /var/log/containers/*.log
    Tag               kube.*

[FILTER]
    Name              kubernetes
    Match             kube.*

[OUTPUT]
    Name              kafka
    Match             kube.*
    Brokers           kafka-broker-1:9092,kafka-broker-2:9092
    Topics            logs-kubernetes
    # Гарантия доставки: 1 (leader ack) или all (full sync)
    rdkafka.acks      1
    # Сжатие данных для экономии трафика и места в Kafka
    rdkafka.compression.codec snappy
```

### 2. Конфигурация Kafka (Буфер)

Для обеспечения высокой пропускной способности и отказоустойчивости топик должен иметь:
* **Партиции (Partitions)**: >= количеству инстансов Vector для параллельной обработки.
* **Фактор репликации (Replication Factor)**: >= 3 для Production сред.
* **Retention Policy**: время хранения (например, 24 часа), достаточное для восстановления OpenSearch при аварии.

### 3. Настройка Vector (Агрегатор)

Vector выступает в роли Consumer Group, читая данные из Kafka, преобразуя их и отправляя в OpenSearch.

**Пример `vector.toml`:**
```toml
[sources.kafka_logs]
type = "kafka"
bootstrap_servers = "kafka-broker-1:9092,kafka-broker-2:9092"
group_id = "vector-aggregator-group"
topics = ["logs-kubernetes"]

[transforms.parse_logs]
type = "remap"
inputs = ["kafka_logs"]
source = """
# Парсинг JSON содержимого лога
.message = parse_json!(.message)

# Обогащение: добавление метки окружения
.env = "production"

# Удаление лишних полей для экономии места
del(.kafka_metadata)
"""

[sinks.opensearch_output]
type = "elasticsearch" # Vector использует этот тип и для OpenSearch
inputs = ["parse_logs"]
endpoints = ["https://opensearch-cluster:9200"]
mode = "data_stream" # Использование Data Streams для логов
auth.strategy = "basic"
auth.user = "${OPENSEARCH_USER}"
auth.password = "${OPENSEARCH_PASSWORD}"
tls.verify_certificate = true
```

## Дополнительная информация

### Эксплуатация и мониторинг

* **Consumer Lag**: ключевая метрика. Если лаг растет, необходимо увеличить количество партиций в Kafka и количество подов Vector.
* **Backpressure в Vector**: при недоступности OpenSearch Vector начнет накапливать данные в своем буфере (рекомендуется использовать `disk` буфер для Vector).
* **Схема данных**: используйте VRL для приведения всех логов к единому стандарту (Common Schema), что упростит создание дашбордов в Dashboards (Kibana).

### Безопасность

1. **Шифрование**: TLS между всеми компонентами (Fluent Bit -> Kafka, Kafka -> Vector, Vector -> OpenSearch).
2. **Аутентификация**:
    * Fluent Bit и Vector -> Kafka: SASL/SCRAM или сертификаты (mTLS).
    * Vector -> OpenSearch: Basic Auth или IAM роли (в AWS).
3. **RBAC**: ограничение прав Vector в OpenSearch только на запись в конкретные индексы/потоки.

> **См. также:**
> * [Vector: Язык трансформации VRL](../../Vector/vrl_language.md)
> * [Kafka: Настройка производительности](../../Kafka/kafka_performance_tuning.md)
> * [OpenSearch: Управление жизненным циклом индексов (ISM)](../OpenSearch/opensearch_ism_lifecycle.md)
