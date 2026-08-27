# Использование Apache Kafka в системах мониторинга и наблюдаемости

**Kafka для мониторинга** — это архитектурный паттерн, при котором Apache Kafka выступает в роли распределенного персистентного буфера между источниками телеметрии (метрики, логи, трассировки) и системами их обработки и хранения. Этот подход является стандартом для высоконагруженных систем (High Load), обеспечивая надежность и масштабируемость observability-пайплайнов.

---

## Определения

- **Очередь-буфер (Buffering):** Механизм временного хранения данных в Kafka для изоляции систем-источников от систем-приемников. Позволяет сглаживать пики нагрузки.
- **Обратное давление (Back-pressure):** Состояние, при котором система-приемник не успевает обрабатывать входящий поток данных. В Kafka консьюмеры сами контролируют скорость чтения, предотвращая перегрузку хранилищ.
- **Лаг консьюмера (Consumer Lag):** Разница между последним записанным офсетом в партиции (Log End Offset) и последним прочитанным офсетом консьюмера (Committed Offset). Ключевая метрика здоровья observability-пайплайна. Подробнее см. раздел «Основные концепции».
- **Декаплинг (Decoupling):** Архитектурное разделение процессов генерации телеметрии и её индексации. Изменения или сбои в хранилище (например, Elasticsearch) не влияют на работу агентов сбора данных на серверах приложений.
- **Fan-out (Множественные потребители):** Возможность Kafka транслировать один поток телеметрии сразу в несколько систем (например, логи одновременно идут в OpenSearch для поиска и в S3 для долгосрочного аудита).
- **High Watermark (HW):** Офсет последней записи, успешно реплицированной на все реплики из ISR (In-Sync Replicas). Консьюмеры видят записи только до этой отметки — это исключает чтение данных, которые могут быть потеряны при смене лидера.
- **ISR (In-Sync Replicas):** Список реплик (включая лидера), которые полностью синхронизианы. Новый лидер выбирается только из ISR. Если ISR сокращается, растёт риск потери данных.
- **Log End Offset (LEO):** Офсет следующей записи, которая будет записана в партицию. Используется для расчёта лага: `Lag = LEO - Committed Offset`.
- **Time Lag:** Временная задержка между производством сообщения и его потреблением. В отличие от offset lag (количество сообщений), time lag измеряет задержку в секундах/миллисекундах.
- **Burrow:** Инструмент LinkedIn для мониторинга consumer lag. Оценивает лаг на основе трендов (OK/WARN/ERROR), а не абсолютных значений, что снижает количество ложных алертов.
- **Tiered Storage:** Функция Kafka (начиная с Confluent 6.0+ и Apache Kafka 3.5+ с KIP-405), позволяющая выгружать старые сегменты в S3/HDFS, храня на дисках брокеров только свежие данные.

---

## Основные концепции

### Роль Kafka в архитектуре наблюдаемости

Kafka выполняет роль «амортизатора» и «распределителя» данных. В современных системах наблюдаемости (Observability) она занимает центральное место между уровнем сбора (Edge) и уровнем хранения (Storage).

**Ключевые преимущества:**

1.  **Персистентность:** В отличие от буферов в оперативной памяти агентов, Kafka записывает данные на диск. При перезагрузке агента или сбое сети данные не теряются.
2.  **Асинхронность:** Приложения отправляют телеметрию в Kafka за миллисекунды и продолжают работу, не дожидаясь медленной индексации в БД.
3.  **Сжатие данных:** Использование алгоритмов сжатия позволяет экономить до 80% сетевого трафика.
     - **LZ4/Snappy:** Низкая нагрузка на CPU, высокая скорость. Оптимально для логов приложений.
     - **Zstd:** Высокая степень сжатия. Рекомендуется для метрик и аудит-логов с длительным хранением.

### Анатомия Consumer Lag

Consumer Lag — главная метрика здоровья observability-пайплайна. Важно понимать разницу между двумя типами лага:

| Тип лага | Что измеряет | Когда использовать |
| :--- | :--- | :--- |
| **Offset Lag** | Разницу в количестве сообщений (LEO - Committed Offset) | Мониторинг пропускной способности, планирование масштабирования |
| **Time Lag** | Временную задержку между `max_message_timestamp` и текущим временем | SLA-мониторинг, контроль свежести данных |

**Почему нельзя полагаться только на абсолютные значения лага:**
- В периоды низкой активности лаг в 10,000 сообщений может означать задержку в минуты.
- В часы пик тот же лаг может означать секунды.
- **Решение:** Мониторить тренд лага (rate of change), а не абсолютные значения.

**Визуализация расчёта лага:**
```
Партиция: [msg0][msg1][msg2][msg3][msg4][msg5]
                               ↑               ↑
                    Committed Offset (3)   Log End Offset (6)
                    
Consumer Lag = 6 - 3 = 3 сообщения
```

### Риски прямой отправки телеметрии

Прямая отправка (например, `Fluent Bit → OpenSearch`) допустима только в малых системах. В High Load возникают следующие проблемы:

- **Потеря данных:** При недоступности БД агенты (Fluent Bit, Vector) начинают переполнять свои ограниченные буферы в RAM и в итоге отбрасывают новые события.
- **Блокировка ресурсов:** Агенты тратят CPU и память на попытки переотправки данных (retries) в недоступную систему, что может привести к деградации самого приложения.
- **Отсутствие гибкости:** Если нужно добавить вторую систему анализа, придется перенастраивать все агенты на всех хостах.

### Эффективность через батчинг и тюнинг агентов

Для мониторинга критически важна оптимизация ресурсов на этапе отправки в Kafka:

1.  **Батчинг (Batching):** Группировка логов перед отправкой. Рекомендуемый размер батча — 1–5 МБ или 1000–5000 записей.
2.  **Стратегия ретраев (Retry Strategy):** Настройка экспортеров (Vector/Fluent Bit) на экспоненциальную задержку при ошибках записи в Kafka.
3.  **Использование Tiered Storage:** Позволяет хранить терабайты аудит-логов в Kafka, выгружая старые сегменты в S3, оставляя на дисках брокеров только свежие данные для оперативного анализа.

### Ключевые JMX-метрики мониторинга

Kafka сотни метрик через JMX. Для observability-пайплайнов критически важны:

**Метрики консьюмера:**
| MBean | Атрибут | Описание |
| :--- | :--- | :--- |
| `kafka.consumer:type=consumer-fetch-manager-metrics,client-id=*` | `records-lag-max` | Максимальный лаг по всем партициям |
| `kafka.consumer:type=consumer-fetch-manager-metrics,client-id=*,topic=*,partition=*` | `records-lag` | Лаг для конкретной партиции |
| `kafka.consumer:type=consumer-fetch-manager-metrics,client-id=*` | `records-consumed-rate` | Скорость потребления (сообщений/сек) |
| `kafka.consumer:type=consumer-fetch-manager-metrics,client-id=*` | `bytes-consumed-rate` | Скорость потребления (байт/сек) |
| `kafka.consumer:type=consumer-coordinator-metrics,client-id=*` | `assigned-partitions` | Количество назначенных партиций |
| `kafka.consumer:type=consumer-coordinator-metrics,client-id=*` | `commit-rate` | Частота коммитов офсетов |

**Метрики брокера:**
| Метрика Prometheus | Описание | Критичность |
| :--- | :--- | :--- |
| `kafka_server_replica_under_replicated_partitions_count` | Количество партиций с неполной репликацией | Критическая — риск потери данных |
| `kafka_controller_active_controller_count` | Количество активных контроллеров (должно быть 1) | Критическая — split-brain если > 1 |
| `kafka_network_request_per_sec` | Количество запросов в секунду | Высокая — нагрузка на кластер |
| `kafka_log_log_size_bytes` | Размер логов на диске | Средняя — планирование ёмкости |

---

## Практические сценарии

### Сценарий 1: Обработка всплесков логов (Log Spikes)

**Проблема:** Ошибка в коде вызывает бесконечный цикл записи лога. Поток данных вырастает с 10 МБ/с до 500 МБ/с. Хранилище (Loki/Elasticsearch) выходит из строя.

**Решение с Kafka:**

1.  **Агент (Vector):** Отправляет пиковый поток в Kafka. Запись 500 МБ/с на кластер — штатная задача.
2.  **Консьюмер (Vector/Logstash):** Видит рост лага, но продолжает вычитывать данные со скоростью, которую выдерживает хранилище (например, 50 МБ/с).
3.  **Итог:** Хранилище стабильно, логи не потеряны, они доиндексируются позже.

**Валидация решения:**
```bash
# Проверка текущего лага консьюмера
kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
    --group log-consumer \
    --describe

# Ожидаемый вывод: LAG растёт, но CURRENT-OFFSET продолжает увеличиваться
```

### Сценарий 2: Пайплайн с OpenTelemetry и Vector

Современная схема: `Приложение (OTLP) → OTel Collector (Edge) → Kafka → Vector (Aggregator) → ClickHouse / VictoriaMetrics`.

**Преимущества:**
- **OTel Collector:** Собирает данные, выполняет первичную фильтрацию и обогащение метаданными.
- **Vector:** Выполняет тяжелые трансформации (парсинг сложных форматов, маскирование данных) после Kafka, не нагружая приложение.

**Конфигурация Vector для чтения из Kafka:**
```yaml
# vector.yaml - консьюмер из Kafka
sources:
  kafka_logs:
    type: kafka
    bootstrap_servers: "kafka1:9092,kafka2:9092,kafka3:9092"
    group_id: "vector-logs-consumer"
    topics: ["logs-.*"]
    auto_offset_reset: earliest

sinks:
  clickhouse_logs:
    type: clickhouse
    endpoint: "http://clickhouse:8123"
    database: "logs"
    table: "app_logs"
    encoding:
      timestamp_format: unix
```

### Сценарий 3: Мониторинг инфраструктуры через Kafka

1.  **Ключевые метрики (Prometheus):**
     - `kafka_consumergroup_lag`: Рост лага означает, что консьюмеры не справляются.
     - `kafka_server_replica_under_replicated_partitions_count`: Проблемы с репликацией.
     - `kafka_controller_active_controller_count`: Должен быть строго 1.
2.  **Инструменты самомониторинга:**
     - **Kafka Exporter:** Внешний сервис для сбора метрик лагов.
     - **JMX Exporter:** Java-агент внутри брокера для метрик JVM.

### Сценарий 4: Мониторинг лага с Burrow (LinkedIn)

Burrow решает проблему ложных алертов при пиках трафика, оценивая тренд лага, а не абсолютные значения.

**Установка и настройка Burrow:**
```toml
# /etc/burrow/burrow.toml
[general]
pidfile = "/var/run/burrow.pid"

[logging]
filename = "/var/log/burrow/burrow.log"

[client-profile.kafka-cluster]
client-id = "burrow-client"
kafka-version = "3.5.0"

[cluster.production]
class-name = "kafka"
servers = ["kafka1:9092", "kafka2:9092", "kafka3:9092"]
client-profile = "kafka-cluster"
topic-refresh = 60
offset-refresh = 30

[consumer.production]
class-name = "kafka"
cluster = "production"
servers = ["kafka1:9092", "kafka2:9092"]
client-profile = "kafka-cluster"
group-denylist = "^console-consumer-"

[httpserver.default]
address = ":8000"
```

**Запрос статуса консьюмера:**
```bash
# Получить статус консьюмер-группы
curl http://burrow:8000/v3/kafka/production/consumer/log-consumer/lag

# Ответ содержит статусы: OK, WARN, ERROR, STOP, STALL
{
  "status": "OK",
  "partitions": [
    {
      "topic": "logs-app",
      "partition": 0,
      "status": "OK",
      "start": {"offset": 15000, "lag": 50},
      "end": {"offset": 15050, "lag": 0}
    }
  ]
}
```

**Интеграция с Prometheus:**
```yaml
# prometheus.yml - сбор метрик Burrow
scrape_configs:
  - job_name: 'burrow'
    static_configs:
      - targets: ['burrow:8000']
    metrics_path: /metrics
```

### Сценарий 5: Автоскейлинг консьюмеров через KEDA

KEDA (Kubernetes Event-driven Autoscaling) позволяет автоматически масштабировать поды консьюмеров на основе лага Kafka.

**Конфигурация KEDA ScaledObject:**
```yaml
# keda-scaledobject.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kafka-consumer-scaler
spec:
  scaleTargetRef:
    name: log-consumer-deployment
  pollingInterval: 30
  cooldownPeriod: 300
  minReplicaCount: 2
  maxReplicaCount: 20
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka1:9092,kafka2:9092,kafka3:9092
        consumerGroup: log-consumer
        topic: logs-app
        lagThreshold: "1000"  # Целевой лаг на под
        activationLagThreshold: "100"  # Минимальный лаг для активации
```

**Принцип работы:**
1. KEDA опрашивает Kafka Exporter/Burrow для получения текущего лага.
2. Если лаг превышает `lagThreshold`, KEDA увеличивает количество реплик.
3. При снижении лага ниже порога — уменьшает количество реплик (до `minReplicaCount`).

### Сценарий 6: Настройка JMX Exporter для Prometheus

JMX Exporter — Java-агент, который собирает метрики JVM и Kafka, предоставляя их в формате Prometheus.

**Шаг 1: Загрузка JMX Exporter**
```bash
# Скачать JMX Exporter
wget https://repo1.maven.org/maven2/io/prometheus/jmx/jmx_prometheus_javaagent/0.19.0/jmx_prometheus_javaagent-0.19.0.jar -P /opt/kafka/
```

**Шаг 2: Конфигурация сбора метрик**
```yaml
# /opt/kafka/jmx-exporter-config.yaml
startDelaySeconds: 0
ssl: false
lowercaseOutputName: true
rules:
  # Метрики брокера
  - pattern: "kafka.server<type=(.+), name=(.+)><>Value"
    name: "kafka_server_$1_$2"
    type: GAUGE
  # Метрики партиций
  - pattern: "kafka.log<type=Log, name=(.+), topic=(.+), partition=(.+)><>Value"
    name: "kafka_log_$1"
    labels:
      topic: "$2"
      partition: "$3"
  # Метрики контроллера
  - pattern: "kafka.controller<type=(.+), name=(.+)><>Value"
    name: "kafka_controller_$1_$2"
```

**Шаг 3: Запуск Kafka с JMX Exporter**
```bash
# Добавить в окружение брокера
export KAFKA_OPTS="-javaagent:/opt/kafka/jmx_prometheus_javaagent-0.19.0.jar=7071:/opt/kafka/jmx-exporter-config.yaml"

# Запуск брокера
bin/kafka-server-start.sh config/server.properties
```

**Шаг 4: Настройка Prometheus**
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'kafka-jmx'
    static_configs:
      - targets:
          - 'kafka-broker-1:7071'
          - 'kafka-broker-2:7071'
          - 'kafka-broker-3:7071'
```

---

## Дополнительная информация

### Рекомендуемые настройки топиков для телеметрии

| Тип данных | Срок хранения (Retention) | Фактор репликации | Сжатие | Мин. партиций |
| :--- | :--- | :--- | :--- | :--- |
| **Логи приложений** | 3–7 дней | 3 | `lz4` | 6–12 |
| **Аудит-логи** | 14–90 дней | 3 | `zstd` | 6–12 |
| **Метрики** | 12–24 часа | 2 | `zstd` | 3–6 |
| **Трассировки (Traces)** | 12–24 часа | 2 | `snappy` | 6–12 |

**Пояснения:**
- **Фактор репликации 3** для критичных данных обеспечивает сохранность при потере 2 брокеров.
- **Сжатие `zstd`** даёт лучшее сжатие, но требует больше CPU; подходит для данных с длительным хранением.
- **Минимальное количество партиций** должно быть кратно числу брокеров для равномерного распределения.

### Интеграции

- **[AKHQ](https://akhq.io/):** Визуализация лагов и содержимого топиков мониторинга.
- **[Burrow](https://github.com/linkedin/Burrow):** Продвинутый мониторинг consumer lag с оценкой трендов.
- **[KEDA](https://keda.sh/):** Автоскейлинг Kubernetes подов на основе метрик Kafka.
- **[Пайплайн Fluent Bit → Kafka → Vector → OpenSearch](../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md):** Руководство по развертыванию.
- **ClickHouse:** Оптимальное хранилище для логов и трейсов из Kafka (через движок `Kafka` или Vector).

### Troubleshooting: Типичные проблемы и решения

#### Проблема: Consumer Lag постоянно растёт

**Диагностика:**
```bash
# 1. Проверить текущий лаг
kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
    --group my-consumer \
    --describe

# 2. Проверить скорость потребления
# Метрика: records-consumed-rate (должна быть > 0)

# 3. Проверить количество консьюмеров vs партиций
kafka-topics.sh --bootstrap-server kafka:9092 --describe --topic my-topic
```

**Возможные причины и решения:**

| Причина | Диагностика | Решение |
| :--- | :--- | :--- |
| Медленная обработка | Высокий `records-lag-max`, низкий `records-consumed-rate` | Оптимизировать код консьюмера, добавить индексы в БД |
| Недостаточно консьюмеров | `assigned-partitions` < общее число партиций | Увеличить число инстансов консьюмера |
| Частые ребалансировки | Логи: `Rebalancing group` | Увеличить `max.poll.interval.ms`, `session.timeout.ms` |
| Проблемы с брокером | `under_replicated_partitions` > 0 | Проверить здоровье брокеров, сеть, диски |
| Пик нагрузки продюсера | Резкий рост `kafka_topic_partition_current_offset` | Масштабировать консьюмеров, увеличить `max.poll.records` |

#### Проблема: Under-Replicated Partitions (URP) > 0

**Критическая ситуация** — риск потери данных при следующем сбое узла.

**Диагностика:**
```bash
# Проверить URP
kafka-topics.sh --bootstrap-server kafka:9092 \
    --describe \
    --under-replicated-partitions

# Проверить статус ISR
kafka-topics.sh --bootstrap-server kafka:9092 \
    --describe \
    --topics-under-replicated
```

**Решения:**
1. Проверить доступность брокеров (`systemctl status kafka`).
2. Проверить сетевую связность между брокерами.
3. Проверить загрузку дисков (iostat, df -h).
4. При необходимости — перезапустить проблемный брокер.

#### Проблема: Consumer Group Stuck (STOP/STALL в Burrow)

**Признаки:** Лаг не уменьшается, `Committed Offset` не меняется.

**Диагностика:**
```bash
# Проверить статус в Burrow
curl http://burrow:8000/v3/kafka/production/consumer/my-group/lag | jq '.partitions[].status'

# Проверить логи консьюмера
kubectl logs -f deployment/my-consumer --tail=100
```

**Типичные причины:**
- Консьюмер упал (OOMKilled, CrashLoopBackOff).
- Консьюмер завис на обработке «отравленного» сообщения (poison message).
- Проблема с подключением к Kafka (аутентификация, сеть).

**Решение:**
```bash
# Перезапуск консьюмера
kubectl rollout restart deployment/my-consumer

# При необходимости — сброс офсета (ОПАСНО: возможна потеря/дублирование данных)
kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
    --group my-consumer \
    --topic my-topic \
    --reset-offsets \
    --to-latest \
    --execute
```

### Best Practices для Production

1. **Мониторинг трендов, не абсолютных значений:** Используйте Burrow или rate-based алерты вместо фиксированных порогов.
2. **Настройка алертов с учётом времени суток:** Разные пороги для пиковых и ночных часов.
3. **Резервирование ёмкости:** Планируйте хранение с запасом 30-50% для обработки всплесков.
4. **Регулярный аудит consumer groups:** Удаляйте неиспользуемые группы для снижения нагрузки на координатор.
5. **Используйте `min.insync.replicas=2`:** Для критичных топиков это предотвратит потерю данных при одном сбое.
6. **Настройте `unclean.leader.election.enable=false`:** Запретит выбор неполной реплики в качестве лидера.
7. **Мониторьте не только лаг, но и throughput:** `records-consumed-rate` и `bytes-consumed-rate` должны быть стабильными.

### Валидация конфигурации

После настройки пайплайна выполните проверки:

```bash
# 1. Проверить, что продюсер пишет в Kafka
kafka-console-consumer.sh --bootstrap-server kafka:9092 \
    --topic logs-app \
    --from-beginning \
    --max-messages 5

# 2. Проверить, что консьюмер читает данные
kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
    --group log-consumer \
    --describe
# Ожидаемо: LAG = 0 или небольшой, CURRENT-OFFSET растёт

# 3. Проверить метрики в Prometheus
# kafka_consumergroup_lag{consumergroup="log-consumer"} < 1000
# kafka_server_replica_under_replicated_partitions_count == 0
```

### См. также

- **[Проектирование высоконагруженного мониторинга](../Concepts/Observability_and_Monitoring/designing_high_load_monitoring_in_distributed_systems.md)**
- **[Обзор Apache Kafka](./kafka_overview.md)** — основы архитектуры.
- **[Гарантии доставки](./delivery_guarantees.md)** — выбор семантики At-least-once для телеметрии.
- **[Партиционирование и балансировка](./partitioning_and_balancing.md)** — стратегии партиционирования для observability-топиков.
