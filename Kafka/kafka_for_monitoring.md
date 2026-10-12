# Использование Apache Kafka в системах мониторинга и наблюдаемости

**Актуально для:** Apache Kafka 3.8.x / 3.9.x / 4.0.x (KRaft), Prometheus 2.50+ / 3.x, JMX Exporter 1.0.x, kafka_exporter 1.8.x

---

## Определения

- **Буферизация и демпфирование (Spike Absorption):** Использование распределенного персистентного журнала Kafka для временного накопления всплесков телеметрии (логов, метрик, трейсов), изолируя приемники от перегрузки по вводу-выводу.
- **Обратное давление (Back-pressure):** Механизм управления скоростью передачи данных, при котором системы-приемники (консьюмеры) запрашивают данные с доступной им скоростью обработки (`pull`-модель), исключая каскадный отказ хранилищ.
- **Декаплинг (Decoupling):** Архитектурное разделение генераторов телеметрии (агенты на серверах) и потребителей (системы индексации и хранения). Сбои или плановые работы на стороне хранилищ не приводят к сбоям приложений-источников.
- **Consumer Lag (Задержка консьюмера):** Разница между последним записанным смещением в партиции (Log End Offset) и последним зафиксированным смещением консьюмера (Committed Offset).
- **Offset Lag:** Количество сообщений, ожидающих обработки консьюмером (`LEO - Committed Offset`).
- **Time Lag:** Задержка во времени между моментом публикации записи продюсером (`message.timestamp`) и временем ее фактической вычитки консьюмером.
- **Drain Time (Время вычитки):** Прогнозируемое время ликвидации лага при текущей скорости обработки: `DrainTime = ConsumerLag / ConsumptionRate`.
- **Log End Offset (LEO):** Смещение следующей записи, которая будет добавлена в партицию брокером.
- **High Watermark (HW):** Смещение последней записи, успешно реплицированной на все реплики из списка ISR. Консьюмеры видят данные строго до HW.
- **In-Sync Replicas (ISR):** Множество реплик партиции (включая лидера), догнавших лидера в пределах тайм-аута `replica.lag.time.max.ms`.
- **Under-Replicated Partitions (URP):** Партиции, у которых фактическое число реплик в ISR меньше сконфигурированного фактора репликации (`replication.factor`).
- **KRaft (Kafka Raft):** Протокол консенсуса управления метаданными Kafka, полностью заменивший ZooKeeper. Управляется кворумом контроллеров (`QuorumController`).
- **Prometheus JMX Exporter:** In-process Java-агент, подключаемый к JVM брокера, транслирующий внутренние MBean-метрики Kafka и JVM в формат Prometheus.
- **Kafka Exporter:** Внешний независимый сервис на Go, опрашивающий кластер по бинарному протоколу Kafka для вычисления смещений и лагов консьюмер-групп без нагрузки на JVM брокера.
- **Tiered Storage (KIP-405):** Механизм двухуровневого хранения Kafka, переносящий архивные сегменты логов в локальное S3-совместимое объектное хранилище (MinIO/Ceph) и освобождающий быстрые диски NVMe брокеров.

---

## Основные концепции

### Роль Kafka в архитектуре наблюдаемости

В высоконагруженных системах (High Load) прямая доставка телеметрии от агентов сбора в конечные хранилища (ClickHouse, OpenSearch, VictoriaMetrics) недопустима. При отказах хранилища или всплесках нагрузки (Log Spikes) буферы агентов в оперативной памяти моментально переполняются, что приводит к потере данных или деградации клиентских сервисов из-за блокировки потоков ввода-вывода.

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│  Edge Sources   │       │ Transport Layer │       │ Analytics Layer │
│ (Vector, Fluent)│ ────▶ │  Apache Kafka   │ ────▶ │ (ClickHouse /   │
│   (OTLP Logs)   │       │ (Buffer / Disk) │       │   OpenSearch)   │
└─────────────────┘       └─────────────────┘       └─────────────────┘
                                   │
                                   ▼
                          ┌─────────────────┐
                          │   Cold Storage  │
                          │  (MinIO / Ceph) │
                          └─────────────────┘
```

**Ключевые преимущества применения Kafka:**
1. **Персистентность на диске:** Телеметрия сразу сбрасывается в PageCache ОС и реплицируется на диск других брокеров. При полном падении принимающего хранилища данные сохраняются на глубину retention (например, 72 часа).
2. **Асинхронность и демпфирование всплесков:** Агенты сбрасывают данные батчами с подтверждением `acks=1` или `acks=all`, не дожидаясь длительной транзакционной записи или построения индексов в поисковых движках.
3. **Эффективное потоковое сжатие:**
   - **LZ4:** Минимальное потребление CPU, максимальная пропускная способность. Рекомендуется для структурированных логов приложений.
   - **Zstandard (zstd):** Высокая степень компрессии (коэффициент сжатия до 5–7x). Оптимально для тяжелых audit-логов, сетевых flow-логов и метрических серий.

---

### Две плоскости наблюдаемости

При эксплуатации Kafka в DevOps/SRE-контуре необходимо четко разделять две независимые задачи:

| Плоскость | Объект наблюдения | Инструменты | Ключевой фокус |
|---|---|---|---|
| **Kafka как транспорт телеметрии** | Потоки прикладных логов, трейсов и метрик, проходящих через кластер | Vector, Fluent Bit, OTel Collector, Logstash | Объем данных (Throughput), процент сжатия, распределение по топикам, отбрасывание поврежденных событий (DLQ). |
| **Мониторинг самой Kafka** | Инфраструктурное здоровье брокеров, контроллеров KRaft, сети, JVM и групп потребителей | Prometheus JMX Exporter, `kafka_exporter`, Prometheus, Grafana, Alertmanager | Репликация (URP), сбои дисков, доступность кворума, задержка консьюмеров (Consumer Lag), задержки очередей запросов. |

---

### Архитектура сбора метрик: JMX Exporter vs Kafka Exporter

Для полного покрытия observability-контура самой Kafka используется гибридный подход:

```
                  ┌──────────────────────────────────────────────────┐
                  │                 Кластер Kafka                    │
                  │                                                  │
                  │   ┌──────────────────────────────────────────┐   │
                  │   │               Брокер 1                   │   │
                  │   │                                          │   │
                  │   │   ┌─────────────┐   ┌────────────────┐   │   │
                  │   │   │ Kafka Core  │   │  JMX Exporter  │   │   │
                  │   │   │  (JVM MBean)│──▶│  (Java Agent)  │   │   │
                  │   │   └─────────────┘   └────────┬───────┘   │   │
                  │   └──────────────────────────────┼───────────┘   │
                  └──────────────────────────────────┼───────────────┘
                                                     │ HTTP :8080
                                                     │ (JVM, брокер, KRaft)
                                                     ▼
┌──────────────────┐    Бинарный Kafka API   ┌───────────────┐
│  kafka_exporter  │ ◀───────────────────────│  Prometheus   │
│  (Go daemon)     │                         │  Scrape Job   │
└────────┬─────────┘                         └───────────────┘
         │ HTTP :9308
         │ (Lag, Offsets, Groups)
         ▼
┌──────────────────┐
│    Prometheus    │
└──────────────────┘
```

1. **Prometheus JMX Exporter (In-process):**
   - Работает как `-javaagent` внутри процесса брокера JVM.
   - Обеспечивает доступ к метрикам JVM (GC pauses, heap allocations), состоянию контроллера KRaft, пулам потоков брокера (`RequestHandlerAvgIdlePercent`), операциям ввода-вывода и репликации (`UnderReplicatedPartitions`).
   - *Ограничение:* Сбор метрик consumer lag через JMX требует, чтобы консьюмеры сами отдавали метрики, либо брокер вычислял их локально с высокой нагрузкой на процессор.

2. **Kafka Exporter (Out-of-process):**
   - Отдельный легковесный Go-демон (порт 9308), не зависящий от JVM.
   - Подключается к брокерам как стандартный клиент и через AdminClient API собирает:
     - `LogEndOffset` каждой партиции всех топиков;
     - `CommittedOffset` всех активных и неактивных consumer groups;
     - рассчитывает агрегированный и попартиционный лаг.
   - *Преимущество:* Изолирует брокеры от лишних накладных расходов при мониторинге сотен групп потребителей.

---

### Анатомия Consumer Lag

Consumer Lag — первичный сервисный индикатор здоровья конвейера доставки данных.

```
Партиция 0: [msg 0][msg 1][msg 2][msg 3][msg 4][msg 5][msg 6]
                                   ↑                       ↑
                         Committed Offset (3)      Log End Offset (7)
                         
Consumer Lag = LEO - Committed Offset = 7 - 3 = 4 сообщения
```

#### Различие Offset Lag и Time Lag
- **Offset Lag (сообщения):** Показывает абсолютное число необработанных записей. 
  - *Ловушка статических порогов:* В ненагруженный период (ночь) лаг в 20 000 сообщений может означать, что консьюмер полностью завис (задержка данных на часы). В пиковый час тот же лаг в 20 000 сообщений вычитывается за 500 миллисекунд и является штатным явлением.
- **Time Lag (миллисекунды):** Измеряет фактическое отставание по времени между timestamp сообщения в начале лага и текущим моментом времени (`now() - record.timestamp()`). Именно Time Lag определяет нарушение SLA доставки телеметрии.

#### Вычисление тренда и Drain Time в PromQL
Для исключения ложных срабатываний в системах мониторинга отслеживают производную лага и расчетное время его устранения:

1. **Скорость нарастания лага (тренд):**
   ```promql
   # Если производная > 0, консьюмер отстает от потока входящих данных
   deriv(kafka_consumergroup_lag{consumergroup="vector-logs-consumer"}[5m]) > 0
   ```

2. **Drain Time (прогнозируемое время вычитки в секундах):**
   ```promql
   # Время до полной ликвидации очереди при текущей скорости обработки
   kafka_consumergroup_lag{consumergroup="vector-logs-consumer"}
   /
   clamp_min(rate(kafka_consumergroup_current_offset{consumergroup="vector-logs-consumer"}[5m]), 1)
   ```

---

### Мониторинг кворума KRaft (Kafka 3.8+ / 4.0+)

Начиная с Apache Kafka 3.3 (GA) и 4.0+ (где ZooKeeper полностью удален), архитектура метаданных опирается на встроенный кворум KRaft. Мониторинг ZooKeeper исключен; взамен контролируются следующие сущности:

- **Active Controller Count:** В кластере должен быть ровно один активный лидер кворума (`QuorumController`). Значение `0` означает паралич кластера (невозможно создавать топики, назначать партиции); значение `> 1` свидетельствует о катастрофическом разделении кворума (Split-Brain).
- **Metadata Loader / Replication Lag:** Задержка синхронизации метаданных между активным контроллером и остальными участниками кворума (voters/observers).
- **Raft Leader Elections:** Частота перевыборов лидера метаданных. Частые перевыборы указывают на сетевую нестабильность или паузы сборщика мусора (GC) на нодах-контроллерах.

---

### Сводная матрица критических метрик Kafka

Ниже приведена матрица мониторинга, объединяющая MBean-источники, имена метрик Prometheus, нормальные значения и действия SRE-инженера:

| Категория | Исходный MBean | Имя метрики в Prometheus | Норма | Критический порог | Влияние на систему и действие |
|---|---|---|---|---|---|
| **Репликация** | `kafka.server:type=ReplicaManager, name=UnderReplicatedPartitions` | `kafka_server_replicamanager_underreplicatedpartitions` | `0` | `> 0` более 3 минут | Партиции теряют избыточность. Риск потери данных при отказе брокера. Проверить диски и сеть. |
| **Репликация** | `kafka.server:type=ReplicaManager, name=UnderMinIsrPartitionCount` | `kafka_server_replicamanager_underminisrpartitioncount` | `0` | `> 0` | Число реплик меньше `min.insync.replicas`. Продюсеры с `acks=all` получают `NotEnoughReplicasException`. |
| **Доступность** | `kafka.controller:type=QuorumController, name=ActiveControllerCount` | `kafka_controller_activecontrollercount` | `1` на кластер | `!= 1` более 1 минуты | `0` — нет лидера кворума; `> 1` — split-brain. Заблокированы административные операции. |
| **Доступность** | `kafka.controller:type=QuorumController, name=OfflinePartitionCount` | `kafka_controller_offlinepartitioncount` | `0` | `> 0` | Партиции лишены лидера. Чтение и запись в них полностью заблокированы. |
| **Пул потоков** | `kafka.server:type=KafkaRequestHandlerPool, name=RequestHandlerAvgIdlePercent` | `kafka_server_kafkarequesthandlerpool_requesthandleravgidlepercent` | `> 0.50` | `< 0.20` более 5 минут | Потоки ввода-вывода брокера перегружены. Растут сетевые задержки. Необходим рост `num.io.threads` или шардирование. |
| **Сетевой пул** | `kafka.network:type=SocketServer, name=NetworkProcessorAvgIdlePercent` | `kafka_network_socketserver_networkprocessoravgidlepercent` | `> 0.50` | `< 0.20` более 5 минут | Потоки сетевого сокета перегружены. Увеличить `num.network.threads`. |
| **Очереди запросов** | `kafka.network:type=RequestChannel, name=RequestQueueTimeMs` | `kafka_network_requestchannel_requestqueuetimems{quantile="99thPercentile"}` | `< 10 ms` | `> 100 ms` | Запросы ожидают освобождения рабочего потока в очереди. Предвестник таймаутов у клиентов. |
| **Задержка записи** | `kafka.network:type=RequestMetrics, name=TotalTimeMs, request=Produce` | `kafka_network_requestmetrics_totaltimems{request="Produce", quantile="99thPercentile"}` | `< 50 ms` | `> 500 ms` | Общее время обработки produce-запроса (включая ожидание репликации на ISR). |
| **Consumer Lag** | Kafka API / `kafka_exporter` | `kafka_consumergroup_lag` | Стабилен | Постоянный рост + `deriv > 0` | Консьюмер не успевает за потоком. Риск переполнения retention и потери телеметрии. |
| **Паузы JVM GC** | `java.lang:type=GarbageCollector, name=*` | `jvm_gc_collectiontime_ms` | `< 50 ms/min` | `> 1000 ms/min` | Длинные паузы G1GC приводят к выпадению брокера из ISR по `replica.lag.time.max.ms` и ложным перевыборам лидера. |

---

## Практические сценарии

### Сценарий 1: Настройка Prometheus JMX Exporter для брокеров Kafka

Для интеграции с Prometheus на каждом узле Kafka настраивается официальный Java-агент JMX Exporter.

#### Шаг 1: Загрузка бинарного файла агента
```bash
# Размещение JavaAgent в каталоге библиотек Kafka
mkdir -p /opt/kafka/monitoring
curl -sSL https://repo1.maven.org/maven2/io/prometheus/jmx/jmx_prometheus_javaagent/1.0.1/jmx_prometheus_javaagent-1.0.1.jar \
    -o /opt/kafka/monitoring/jmx_prometheus_javaagent.jar
chmod 0644 /opt/kafka/monitoring/jmx_prometheus_javaagent.jar
```

#### Шаг 2: Создание оптимизированной конфигурации под KRaft
Конфигурация отфильтровывает ненужные шумные метрики и транслирует критические MBean в стандартные имена Prometheus.

```yaml
# /opt/kafka/monitoring/jmx-exporter-kafka.yaml
startDelaySeconds: 0
ssl: false
lowercaseOutputName: true
lowercaseOutputLabelNames: true

rules:
  # 1. KRaft Контроллер и кворум
  - pattern: "kafka.controller<type=(KafkaController|QuorumController), name=(.+)><>Value"
    name: "kafka_controller_$2"
    type: GAUGE
  - pattern: "kafka.server<type=raft-leader-election, name=(.+)><>Value"
    name: "kafka_raft_leader_election_$1"
    type: GAUGE
  - pattern: "kafka.server<type=raft-metrics, name=(.+)><>Value"
    name: "kafka_raft_metrics_$1"
    type: GAUGE

  # 2. Менеджер реплик и партиций
  - pattern: "kafka.server<type=ReplicaManager, name=(UnderReplicatedPartitions|UnderMinIsrPartitionCount|OfflineReplicaCount|PartitionCount|LeaderCount)><>Value"
    name: "kafka_server_replicamanager_$1"
    type: GAUGE

  # 3. Агрегированные метрики брокера по входящему/исходящему трафику
  - pattern: "kafka.server<type=BrokerTopicMetrics, name=(BytesInPerSec|BytesOutPerSec|MessagesInPerSec|TotalProduceRequestsPerSec)><>Count"
    name: "kafka_server_brokertopicmetrics_$1_total"
    type: COUNTER
  - pattern: "kafka.server<type=BrokerTopicMetrics, name=(BytesInPerSec|BytesOutPerSec|MessagesInPerSec|TotalProduceRequestsPerSec)><>OneMinuteRate"
    name: "kafka_server_brokertopicmetrics_$1_rate"
    type: GAUGE

  # 4. Метрики по конкретным топикам
  - pattern: "kafka.server<type=BrokerTopicMetrics, name=(BytesInPerSec|BytesOutPerSec|MessagesInPerSec), topic=(.+)><>Count"
    name: "kafka_server_brokertopicmetrics_$1_total"
    labels:
      topic: "$2"
    type: COUNTER

  # 5. Пулы потоков брокера
  - pattern: "kafka.server<type=KafkaRequestHandlerPool, name=RequestHandlerAvgIdlePercent><>OneMinuteRate"
    name: "kafka_server_kafkarequesthandlerpool_requesthandleravgidlepercent"
    type: GAUGE
  - pattern: "kafka.network<type=SocketServer, name=NetworkProcessorAvgIdlePercent><>Value"
    name: "kafka_network_socketserver_networkprocessoravgidlepercent"
    type: GAUGE

  # 6. Времена ожидания и задержки очередей
  - pattern: "kafka.network<type=RequestChannel, name=RequestQueueTimeMs><>(Mean|99thPercentile)"
    name: "kafka_network_requestchannel_requestqueuetimems"
    labels:
      quantile: "$1"
    type: GAUGE
  - pattern: "kafka.network<type=RequestMetrics, name=TotalTimeMs, request=(Produce|FetchConsumer|FetchFollower)><>(Mean|99thPercentile)"
    name: "kafka_network_requestmetrics_totaltimems"
    labels:
      request: "$1"
      quantile: "$2"
    type: GAUGE

  # 7. JVM Память и сборка мусора
  - pattern: "java.lang<type=GarbageCollector, name=(.+)><>(CollectionCount|CollectionTime)"
    name: "jvm_gc_$2"
    labels:
      gc: "$1"
  - pattern: "java.lang<type=Memory><HeapMemoryUsage>(used|max|committed)"
    name: "jvm_memory_heap_$1_bytes"
    type: GAUGE
```

#### Шаг 3: Подключение агента к сервису systemd
В файле переопределения окружения `/etc/default/kafka` задается переменная `KAFKA_JMX_OPTS`:

```bash
# /etc/default/kafka
KAFKA_JMX_OPTS="-javaagent:/opt/kafka/monitoring/jmx_prometheus_javaagent.jar=8080:/opt/kafka/monitoring/jmx-exporter-kafka.yaml"
```

Перезапуск службы и валидация отдачи метрик:
```bash
systemctl restart kafka
curl -s http://127.0.0.1:8080/metrics | grep -E "kafka_server_replicamanager_underreplicatedpartitions|kafka_controller_activecontrollercount"
# → kafka_server_replicamanager_underreplicatedpartitions 0.0
# → kafka_controller_activecontrollercount 1.0
```

---

### Сценарий 2: Развертывание `kafka_exporter` для мониторинга Consumer Lag

`kafka_exporter` опрашивает кластер извне и публикует метрики потребителей без нагрузки на JVM брокеров.

#### Вариант A: Развертывание через systemd (on-prem / bare-metal)
```bash
# Загрузка бинарного файла
curl -sSL https://github.com/danielqsj/kafka_exporter/releases/download/v1.8.0/kafka_exporter-1.8.0.linux-amd64.tar.gz \
    | tar -xz -C /usr/local/bin/ --strip-components=1 kafka_exporter-1.8.0.linux-amd64/kafka_exporter

# Создание сервиса
cat << 'EOF' > /etc/systemd/system/kafka-exporter.service
[Unit]
Description=Kafka Exporter for Prometheus
After=network.target

[Service]
Type=simple
User=prometheus
Group=prometheus
ExecStart=/usr/local/bin/kafka_exporter \
    --kafka.servers=kafka-node-01.internal:9092,kafka-node-02.internal:9092,kafka-node-03.internal:9092 \
    --web.listen-address=:9308 \
    --web.telemetry-path=/metrics \
    --concurrent.enable \
    --topic.filter=".*" \
    --group.filter=".*"
Restart=always
RestartSec=5s
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now kafka-exporter
```

#### Вариант B: Развертывание через Docker Compose
```yaml
# docker-compose.monitoring.yml
services:
  kafka-exporter:
    image: danielqsj/kafka-exporter:v1.8.0
    container_name: kafka-exporter
    restart: unless-stopped
    ports:
      - "9308:9308"
    command:
      - "--kafka.servers=kafka-broker-1:9092,kafka-broker-2:9092,kafka-broker-3:9092"
      - "--web.listen-address=:9308"
      - "--concurrent.enable"
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

Проверка доступности метрик:
```bash
curl -s http://127.0.0.1:9308/metrics | grep -E "kafka_brokers|kafka_consumergroup_lag" | head -n 4
# → # HELP kafka_brokers Number of Brokers in the Kafka Cluster.
# → # TYPE kafka_brokers gauge
# → kafka_brokers 3
# → kafka_consumergroup_lag{consumergroup="vector-logs-consumer",partition="0",topic="logs-app"} 12
```

---

### Сценарий 3: Сбор метрик в Prometheus (`scrape_configs`)

Конфигурация Prometheus объединяет сбор инфраструктурных метрик брокеров (порт 8080) и агрегированных метрик консьюмеров (порт 9308):

```yaml
# /etc/prometheus/prometheus.yml
scrape_configs:
  - job_name: 'kafka-brokers-jmx'
    scrape_interval: 15s
    scrape_timeout: 10s
    static_configs:
      - targets:
          - 'kafka-node-01.internal:8080'
          - 'kafka-node-02.internal:8080'
          - 'kafka-node-03.internal:8080'
        labels:
          cluster: 'kafka-prod-cluster'
          role: 'broker'

  - job_name: 'kafka-exporter'
    scrape_interval: 15s
    scrape_timeout: 10s
    static_configs:
      - targets:
          - 'monitoring-node-01.internal:9308'
        labels:
          cluster: 'kafka-prod-cluster'
          role: 'exporter'
```

---

### Сценарий 4: Правила алертинга Prometheus (Alertmanager)

Готовые production-правила обнаружения сбоев кластера и замедления консьюмеров:

```yaml
# /etc/prometheus/rules/kafka_alerts.yml
groups:
  - name: KafkaClusterHealth
    rules:
      - alert: KafkaBrokerDown
        expr: count(up{job="kafka-brokers-jmx"} == 1) < 3
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Один или несколько брокеров Kafka недоступны"
          description: "В кластере {{ $labels.cluster }} активны {{ $value }} из 3 брокеров."

      - alert: KafkaUnderReplicatedPartitions
        expr: sum(kafka_server_replicamanager_underreplicatedpartitions) by (cluster) > 0
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "Обнаружены Under-Replicated Partitions (URP)"
          description: "В кластере {{ $labels.cluster }} обнаружено {{ $value }} партиций с неполной репликацией. Риск потери данных при сбое."

      - alert: KafkaOfflinePartitions
        expr: sum(kafka_controller_offlinepartitioncount) by (cluster) > 0
        for: 1m
        labels:
          severity: page
        annotations:
          summary: "Партиции Kafka в статусе Offline"
          description: "В кластере {{ $labels.cluster }} обнаружено {{ $value }} оффлайн-партиций. Запись и чтение полностью заблокированы."

      - alert: KafkaNoActiveController
        expr: sum(kafka_controller_activecontrollercount) by (cluster) != 1
        for: 1m
        labels:
          severity: page
        annotations:
          summary: "Аномалия контроллера KRaft"
          description: "В кластере {{ $labels.cluster }} число активных контроллеров равно {{ $value }} (ожидается строго 1)."

      - alert: KafkaRequestHandlerPoolExhausted
        expr: kafka_server_kafkarequesthandlerpool_requesthandleravgidlepercent < 0.20
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Дефицит потоков ввода-вывода брокера (I/O Saturation)"
          description: "На узле {{ $labels.instance }} простой рабочих потоков упал до {{ $value | humanizePercentage }}. Запросы становятся в очередь."

  - name: KafkaConsumerLagMonitoring
    rules:
      - alert: KafkaConsumerGroupLagGrowing
        expr: |
          (deriv(kafka_consumergroup_lag[10m]) > 0)
          and
          (kafka_consumergroup_lag > 10000)
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Растет задержка консьюмер-группы"
          description: "Группа {{ $labels.consumergroup }} в топике {{ $labels.topic }} стабильно отстает. Лаг: {{ $value }} сообщений."

      - alert: KafkaConsumerGroupStalled
        expr: |
          (rate(kafka_consumergroup_current_offset[5m]) == 0)
          and
          (kafka_consumergroup_lag > 0)
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Консьюмер-группа полностью остановила чтение"
          description: "Группа {{ $labels.consumergroup }} не коммитит офсеты при наличии лага ({{ $value }} сообщений). Возможен сбой или deadlock."
```

---

### Сценарий 5: Буферизация телеметрии (Vector → Kafka → ClickHouse/OpenSearch)

Типовой конвейер обработки телеметрии, где Kafka поглощает пики логов и метрик, а Vector вычитывает их с управляемой скоростью.

#### Настройка продюсера в Vector (Edge-уровень):
```toml
# /etc/vector/vector-edge.toml
[sources.app_logs]
type = "file"
include = ["/var/log/apps/*.log"]
read_from = "beginning"

[transforms.parse_json]
type = "remap"
inputs = ["app_logs"]
source = '''
  . = parse_json!(.message)
  .@timestamp = now()
'''

[sinks.kafka_buffer]
type = "kafka"
inputs = ["parse_json"]
bootstrap_servers = "kafka-node-01.internal:9092,kafka-node-02.internal:9092,kafka-node-03.internal:9092"
topic = "logs-application-prod"
compression = "lz4"

# Оптимизация сетевого батчинга для снижения IOPS брокера
[sinks.kafka_buffer.batch]
max_bytes = 1048576       # 1 МБ
timeout_secs = 1          # Сброс батча не реже 1 секунды

[sinks.kafka_buffer.librdkafka_options]
"queue.buffering.max.messages" = "500000"
"compression.codec" = "lz4"
"acks" = "all"            # Гарантия записи во все реплики ISR
```

#### Настройка консьюмера в Vector (Aggregator-уровень):
```toml
# /etc/vector/vector-aggregator.toml
[sources.kafka_in]
type = "kafka"
bootstrap_servers = "kafka-node-01.internal:9092,kafka-node-02.internal:9092,kafka-node-03.internal:9092"
group_id = "vector-logs-aggregator"
topics = ["logs-application-prod"]
auto_offset_reset = "earliest"
commit_interval_ms = 5000

[sinks.clickhouse_out]
type = "clickhouse"
inputs = ["kafka_in"]
endpoint = "http://clickhouse-node-01.internal:8123"
database = "telemetry"
table = "app_logs"
skip_unknown_fields = true

# Защита ClickHouse через батчинг
[sinks.clickhouse_out.batch]
max_bytes = 10485760      # 10 МБ батч
timeout_secs = 5
```

---

### Сценарий 6: Автоскейлинг консьюмеров по лагу через KEDA

В Kubernetes-окружении для автоматического масштабирования подов-консьюмеров на основе Consumer Lag применяется KEDA. При росте очереди KEDA увеличивает число реплик пода вплоть до общего числа партиций топика.

```yaml
# keda-scaledobject.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kafka-consumer-scaler
  namespace: observability
spec:
  scaleTargetRef:
    name: vector-logs-aggregator
  pollingInterval: 15
  cooldownPeriod: 180
  minReplicaCount: 2
  maxReplicaCount: 16             # Ограничено количеством партиций топика
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka-node-01.internal:9092,kafka-node-02.internal:9092
        consumerGroup: vector-logs-aggregator
        topic: logs-application-prod
        lagThreshold: "5000"      # Целевой лаг на один под
        activationLagThreshold: "500"
```

> **Подробная документация по KEDA:** Детальная настройка HPA, аутентификации через Secret/Vault и масштабирования через Kafka Exporter описана в **[KEDA + Kafka Scaler](../Kubernetes/Autoscaling/keda/kafka-keda-scaler.md)**.

---

### Сценарий 7: Мониторинг лага через Burrow

Burrow (разработка LinkedIn) отслеживает лаг без статических числовых порогов, вычисляя тренд скользящего окна и присваивая статусы: `OK`, `WARN` (лаг нарастает), `ERROR` (консьюмер остановился), `STOP` (консьюмер отключен).

#### Конфигурация Burrow:
```toml
# /etc/burrow/burrow.toml
[general]
pidfile = "/var/run/burrow.pid"

[logging]
level = "info"
filename = "/var/log/burrow/burrow.log"

[client-profile.kafka-prod]
client-id = "burrow-lag-checker"
kafka-version = "3.8.0"

[cluster.production]
class-name = "kafka"
servers = ["kafka-node-01.internal:9092", "kafka-node-02.internal:9092", "kafka-node-03.internal:9092"]
client-profile = "kafka-prod"
topic-refresh = 120
offset-refresh = 30

[consumer.production]
class-name = "kafka"
cluster = "production"
servers = ["kafka-node-01.internal:9092", "kafka-node-02.internal:9092"]
client-profile = "kafka-prod"
group-denylist = "^console-consumer-.*"

[httpserver.default]
address = ":8000"
```

Запрос текущего статуса группы через HTTP API:
```bash
curl -s http://127.0.0.1:8000/v3/kafka/production/consumer/vector-logs-aggregator/status | jq .
```
```json
{
  "status": {
    "cluster": "production",
    "group": "vector-logs-aggregator",
    "status": "OK",
    "complete": 1,
    "partitions": [
      {
        "topic": "logs-application-prod",
        "partition": 0,
        "status": "OK",
        "start": {"offset": 120540, "timestamp": 1718000000, "lag": 45},
        "end": {"offset": 120600, "timestamp": 1718000030, "lag": 15}
      }
    ],
    "partition_count": 12,
    "maxlag": {
      "topic": "logs-application-prod",
      "partition": 0,
      "status": "OK",
      "start": {"offset": 120540, "timestamp": 1718000000, "lag": 45},
      "end": {"offset": 120600, "timestamp": 1718000030, "lag": 15}
    },
    "totallag": 180
  }
}
```

---

## Операции и команды

Ниже представлены базовые команды CLI для оперативной проверки состояния очередей и брокеров инженером SRE.

### 1. Проверка Consumer Lag через CLI
```bash
kafka-consumer-groups.sh --bootstrap-server 127.0.0.1:9092 \
    --describe --group vector-logs-aggregator
```
```text
# → GROUP                 TOPIC                 PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID     HOST            CLIENT-ID
# → vector-logs-aggregator logs-application-prod 0          140230          140250          20              vector-pod-1    /10.244.1.15    vector-client-1
# → vector-logs-aggregator logs-application-prod 1          138900          138902          2               vector-pod-2    /10.244.2.18    vector-client-2
# → vector-logs-aggregator logs-application-prod 2          141005          141005          0               vector-pod-1    /10.244.1.15    vector-client-1
```

### 2. Поиск неполных и рассинхронизированных реплик (URP)
```bash
kafka-topics.sh --bootstrap-server 127.0.0.1:9092 \
    --describe --under-replicated-partitions
```
```text
# → (Если вывод пустой — все партиции полностью синхронизированы в ISR)
# → При наличии проблемы:
# → Topic: logs-application-prod Partition: 2 Leader: 1 Replicas: 1,2,3 Isr: 1,3
```

### 3. Прямой опрос JMX-метрик через консоль (`JmxTool`)
Используется при недоступности сетевого агента или Prometheus:
```bash
kafka-run-class.sh kafka.tools.JmxTool \
    --jmx-url service:jmx:rmi:///jndi/rmi://127.0.0.1:9999/jmxrmi \
    --object-name "kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions" \
    --attributes Value --date-format "yyyy-MM-dd HH:mm:ss"
```
```text
# → 2026-10-12 14:35:00: "kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions": {"Value": 0}
```

Проверка свободного пула рабочих потоков:
```bash
kafka-run-class.sh kafka.tools.JmxTool \
    --jmx-url service:jmx:rmi:///jndi/rmi://127.0.0.1:9999/jmxrmi \
    --object-name "kafka.server:type=KafkaRequestHandlerPool,name=RequestHandlerAvgIdlePercent" \
    --attributes OneMinuteRate
```
```text
# → "kafka.server:type=KafkaRequestHandlerPool,name=RequestHandlerAvgIdlePercent": {"OneMinuteRate": 0.884}
```

### 4. Проверка сброса офсетов при аварийных ситуациях
При застревании консьюмера на "отравленном" сообщении (Poison Pill) для восстановления потока может потребоваться сдвиг указателя:

```bash
# Предварительный расчет (Dry-Run): сдвиг на конец очереди
kafka-consumer-groups.sh --bootstrap-server 127.0.0.1:9092 \
    --group vector-logs-aggregator \
    --topic logs-application-prod \
    --reset-offsets --to-latest --dry-run
```
```text
# → GROUP                 TOPIC                 PARTITION  NEW-OFFSET
# → vector-logs-aggregator logs-application-prod 0          140250
# → vector-logs-aggregator logs-application-prod 1          138902
# → vector-logs-aggregator logs-application-prod 2          141005
```

```bash
# Применение изменений (выполнять только при остановленных подах консьюмера!)
kafka-consumer-groups.sh --bootstrap-server 127.0.0.1:9092 \
    --group vector-logs-aggregator \
    --topic logs-application-prod \
    --reset-offsets --to-latest --execute
# → [2026-10-12 14:36:10,123] Reset offsets successfully.
```

---

## Диагностика и устранение неполадок

### Сводная таблица неисправностей

| Симптом | Вероятная причина | Метод первичной диагностики | Шаги устранения |
|---|---|---|---|
| Постоянный рост Consumer Lag | Недостаток консьюмеров, долгий парсинг или медленный Sink (БД) | Проверить `records-consumed-rate` и `assigned-partitions` | Добавить инстансы консьюмера (в пределах числа партиций); увеличить размер батча записи в БД. |
| Лаг застыл, смещение не растет (`Committed Offset = const`) | Зависание консьюмера (Deadlock, Poison Pill, OOMKilled) | Проверить логи консьюмера: `Rebalance`, `OutOfMemory`, `DeserializationException` | Изолировать битое сообщение в DLQ; перезапустить консьюмер; при необходимости выполнить `--reset-offsets`. |
| `UnderReplicatedPartitions > 0` | Сбой ноды брокера, деградация диска (I/O wait), сетевой jitter | `kafka-topics.sh --describe --under-replicated-partitions`; `iostat -xz 1` | Проверить логи `journalctl -u kafka`; заменить сбойный диск; проверить тайм-аут `replica.lag.time.max.ms`. |
| Резкое падение `RequestHandlerAvgIdlePercent < 0.2` | Лавина мелких запросов (недостаточный батчинг), медленный диск PageCache | `RequestQueueTimeMs` в JMX; `vmstat 1` | Включить сжатие и батчинг на продюсерах (`linger.ms=20`, `batch.size=65536`); увеличить `num.io.threads`. |
| Брокер самопроизвольно покидает кластер | Длинные паузы Stop-the-world JVM GC | Проверить `jvm_gc_collectiontime_ms` и журнал `/var/log/kafka/kafka-gc.log` | Настроить G1GC: `-XX:MaxGCPauseMillis=20`, увеличить кучу брокера до 8–10 ГБ (не выделять более 32 ГБ во избежание деградации Compressed OOPs). |

---

### Детальные сценарии диагностики

#### 1. Лавинообразный рост Consumer Lag
**Симптомы:** Alertmanager генерирует `KafkaConsumerGroupLagGrowing`. В Grafana график лага показывает непрерывный восходящий тренд.

**Диагностический алгоритм:**
1. Выполнить команду `kafka-consumer-groups.sh --describe --group <group_name>`.
2. Сопоставить число инстансов консьюмера и число партиций. Если партиций 12, а консьюмеров работает 2 — каждый обрабатывает по 6 партиций.
3. Оценить производительность принимающего хранилища (ClickHouse, OpenSearch, Postgres). Если база перегружена по disk write или CPU, консьюмер блокируется на этапе отправки батча.
4. Проверить интервал опроса: если время обработки одного батча превышает `max.poll.interval.ms` (по умолчанию 300 000 мс / 5 минут), координатор группы признает консьюмер мертвым и запускает ребалансировку. Постоянные ребалансировки (Rebalance Storm) парализуют чтение.

**Решение:**
- Уменьшить `max.poll.records` (например, со 500 до 100), чтобы укладываться в интервал опроса.
- Увеличить `max.poll.interval.ms`.
- Масштабировать инстансы консьюмера горизонтально.

---

#### 2. Under-Replicated Partitions (URP > 0)
**Симптомы:** Срабатывает алерт `KafkaUnderReplicatedPartitions`. Метрика `kafka_server_replicamanager_underreplicatedpartitions > 0`.

**Диагностический алгоритм:**
1. Определить проблемный брокер:
   ```bash
   kafka-topics.sh --bootstrap-server 127.0.0.1:9092 --describe --under-replicated-partitions
   ```
   Если в поле `Replicas: 1,2,3`, а в `Isr: 1,2`, значит брокер `3` выпал из синхронных реплик.
2. Проверить статус процесса Kafka на узле 3: `systemctl status kafka`.
3. Проверить дисковую подсистему узла: `iostat -xz 1 5`. Если утилизация диска `%util` близка к 100%, а задержка `await` превышает 50–100 мс, диск не успевает фиксировать реплицируемые данные.
4. Проверить сетевые потери между брокерами: `mtr -c 50 -r kafka-node-03.internal`.

**Решение:**
- Если диск перегружен, снизить конкурентную нагрузку (отключить лишние процессы, перенести лог-сегменты на отдельный массив NVMe).
- Если брокер завис на паузе GC, скорректировать параметры сборщика мусора и перезапустить брокер. После рестарта начнется процедура catch-up replication, и партиции вернутся в ISR автоматически.

---

#### 3. Thread Starvation: Падение `RequestHandlerAvgIdlePercent`
**Симптомы:** Растут сетевые тайм-ауты продюсеров (`TimeoutException`). Метрика `RequestHandlerAvgIdlePercent` падает ниже 0.20, а `RequestQueueTimeMs` возрастает до 200+ мс.

**Диагностический алгоритм:**
1. Проверить нагрузку на CPU ядер брокера (`htop`, `pidstat -p $(pgrep -f kafka) -t 1`).
2. Оценить профиль трафика: идет ли большой поток мелких записей без сжатия и группировки.
3. Проверить дисковый PageCache: если свободной памяти в Linux недостаточно, брокер вынужден обращаться к диску напрямую вместо оперативной памяти.

**Решение:**
- В `server.properties` увеличить пул потоков ввода-вывода брокера:
  ```properties
  # Рекомендуется: число физических ядер процессора
  num.io.threads=16
  # Число потоков приема сетевых сокетов
  num.network.threads=8
  ```
- Обязать продюсеров (Vector/Fluent Bit) выставлять `linger.ms` не менее 10–20 мс и `batch.size` не менее 64–128 КБ.

---

## Лучшие практики

### Рекомендации по настройке топиков телеметрии

Для топиков мониторинга и логирования в средах On-Premise/Bare-Metal рекомендуются следующие параметры:

| Параметр | Значение | Обоснование |
|---|---|---|
| `replication.factor` | `3` | Гарантия сохранности данных при отказе одного брокера и плановом обслуживании второго. |
| `min.insync.replicas` | `2` | Запрет на запись при падении двух брокеров из трех при `acks=all`, исключая запись в одинокую реплику с риском рассинхронизации. |
| `compression.type` | `lz4` или `zstd` | `lz4` — для логов приложений; `zstd` — для метрик и трейсов с высокой степенью сжатия. Экономия диска до 70%. |
| `retention.ms` | `259200000` (3 дня) | Достаточное окно для расследования инцидентов и восстановления принимающих хранилищ при авариях. |
| `segment.bytes` | `536870912` (512 МБ) | Оптимальный размер сегмента для быстрой очистки старых данных по retention без дисковых пиков. |
| `unclean.leader.election.enable` | `false` | Запрет выбора несинхронной реплики (вне ISR) в качестве лидера. Исключает потерю и искажение смещений. |

---

### Архитектурные правила SRE-контура

1. **Разделение экспортеров по зонам ответственности:**
   - Prometheus JMX Exporter используется **строго** для метрик брокера, JVM, дисков и кворума KRaft.
   - `kafka_exporter` используется **строго** для отслеживания Consumer Lag и офсетов групп. Это предотвращает перегрузку Java-потоков брокера сложными вычислениями смещений.
2. **Алертинг по производным и времени вычитки, а не статичным порогам:**
   - Не настраивайте жесткие триггеры на `lag > 1000`. Используйте связку: наличие лага + положительная производная (`deriv(lag[10m]) > 0`) + время вычитки (`Drain Time > 1800s`).
3. **Резервирование дисковой ёмкости:**
   - Дисковые разделы данных Kafka (`log.dirs`) должны проектироваться с запасом 40% от максимального пикового суточного объема. При заполнении диска свыше 85% брокер останавливает прием данных.
4. **Оптимизация операционной системы Linux:**
   - Лимит открытых файлов в systemd: `LimitNOFILE=1000000`.
   - Запрет сброса грязных страниц операционной системы в фоновый режим с блокировкой:
     ```bash
     # /etc/sysctl.d/99-kafka.conf
     vm.dirty_background_ratio = 5
     vm.dirty_ratio = 10
     vm.swappiness = 1
     vm.max_map_count = 1048576
     ```
5. **Конфигурация памяти JVM (Heap vs PageCache):**
   - Брокерам Kafka не требуется гигантский Heap. Выделяйте JVM от 6 до 10 ГБ оперативной памяти (`-Xms8g -Xmx8g`).
   - Вся остальная оперативная память сервера (32–128+ ГБ) должна оставаться под **PageCache ядра Linux**, откуда Kafka отдает данные клиентам по технологии Zero-Copy (`sendfile`).

---

## Дополнительная информация

### Связанные руководства в базе знаний

- **[Обзор Apache Kafka](./kafka_overview.md)** — архитектура кластера, брокеры, топики и протоколы репликации.
- **[Потоковая модель брокера Kafka](./kafka_broker_thread_model.md)** — глубокий разбор пулов `num.network.threads` и `num.io.threads`, профилирование задержек.
- **[ISR и репликация в Kafka](./kafka_isr_replication.md)** — внутренняя механика синхронизации реплик, High Watermark и обработка сбоев узлов.
- **[Тюнинг JVM и GC для Kafka](./kafka_jvm_gc_tuning.md)** — тонкая настройка сборщика мусора G1GC, предотвращение пауз Stop-the-world.
- **[Оптимизация ОС для Kafka](./kafka_os_tuning.md)** — параметры ядра Linux, планировщики дискового ввода-вывода и сетевой стек.
- **[Troubleshooting Playbook для Kafka](./kafka_troubleshooting_playbook.md)** — сценарии восстановления кластера при авариях и split-brain.
- **[KEDA + Kafka Scaler](../Kubernetes/Autoscaling/keda/kafka-keda-scaler.md)** — автоскейлинг консьюмеров на основе Consumer Lag в Kubernetes.
- **[Конвейер логов Fluent Bit → Kafka → Vector → OpenSearch](../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md)** — пошаговое руководство по сквозному observability-конвейеру.
- **[Методологии мониторинга (USE, RED, Four Golden Signals)](../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)** — практическое применение метрик Kafka в сервисных методологиях.
