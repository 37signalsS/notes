# Kafka Streams в Production: Архитектура, Эксплуатация и SRE-практики

**Актуально для:** Apache Kafka 3.8.x / 3.9.x / 4.0.x, Kafka Streams 3.8.x / 3.9.x / 4.0.x

**Kafka Streams** — это клиентская Java/JVM-библиотека для построения распределенных потоковых приложений и микросервисов поверх Apache Kafka. В отличие от внешних вычислительных кластеров (Apache Flink, Spark Streaming), Kafka Streams не требует отдельного кластерного ресурсного менеджера: масштабирование, координация и отказоустойчивость реализуются через нативный протокол групп консьюмеров Kafka, а локальное состояние сохраняется во встроенном движке RocksDB с репликацией через changelog-топики.

Для инженеров DevOps, SRE и системных администраторов эксплуатация Kafka Streams сопряжена с управлением дисковым вводом-выводом (I/O), контролем внекучевой (off-heap) памяти RocksDB, минимизацией пауз при ребалансировках, администрированием внутренних топиков и процедурами безопасного сброса состояния (application reset).

---

## Определения

- **Stream (Поток):** Бесконечный, упорядоченный, отказоустойчивый поток неизменяемых записей, обновляемый только добавлением (append-only).
- **KStream:** Абстракция потока данных, где каждая входящая запись интерпретируется как независимая операция вставки (INSERT).
- **KTable:** Абстракция таблицы изменений (changelog stream), где каждая запись интерпретируется как обновление по первичному ключу (UPSERT), а значение `null` — как удаление (TOMBSTONE / DELETE).
- **GlobalKTable:** Локально реплицированная полная копия таблицы на каждом экземпляре приложения, заполняемая со всех партиций топика (используется для broadcast join без репартиционирования).
- **Processor Topology:** Ациклический граф (DAG) узлов обработки потока: источниковые узлы (Source Processors), узлы трансформации (Stream Processors) и приемные узлы (Sink Processors).
- **StreamThread:** Системный поток ОС внутри JVM-процесса, исполняющий назначенное множество задач (`StreamTask`). Количество потоков задается параметром `num.stream.threads`.
- **StreamTask:** Минимальная неделимая единица логического параллелизма. Каждая задача обрабатывает строго фиксированное подмножество партиций входных топиков.
- **StandbyTask:** Пассивная резервная копия задачи (`num.standby.replicas`), реплицирующая changelog-топик в фоновом режиме на другом экземпляре для мгновенного failover без прогрева диска.
- **State Store:** Локальное встраиваемое хранилище состояния для stateful-операций (агрегации, оконные функции, join'ы). По умолчанию реализуется на базе встраиваемой LSM-базы данных RocksDB.
- **Changelog Topic:** Внутренний топик Kafka с политикой `cleanup.policy=compact`, автоматически создаваемый для каждого state store для резервного копирования и восстановления состояния.
- **Repartition Topic:** Внутренний топик Kafka с политикой `cleanup.policy=delete`, создаваемый для перераспределения сообщений по новому ключу перед join- или aggregate-операциями.
- **Cooperative Sticky Assignor:** Протокол распределения задач, исключающий глобальную остановку обработки (stop-the-world) за счет поэтапного переназначения только перемещаемых задач.
- **Exactly-Once Semantics (EOS / `exactly_once_v2`):** Гарантия сквозной обработки «ровно один раз», связывающая чтение входных смещений, мутацию локального state store и запись в выходные топики в единую распределенную транзакцию Kafka.
- **Interactive Queries:** Механизм прямого чтения данных из локальных хранилищ State Store запущенного инстанса через API без обращения к брокерам.

---

## Архитектура и принципы работы

### Модель потоков, задач и параллелизма

Масштабирование Kafka Streams опирается на партиционирование входных топиков Kafka. Количество задач (`StreamTask`) определяется максимальным числом партиций среди объединяемых во входной топологии топиков.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Kafka Cluster (Brokers)                         │
│  Input Topic (4 partitions): [P0]      [P1]      [P2]      [P3]        │
└───────────────┬─────────────────┬─────────────────┬─────────────────┬──┘
                │                 │                 │                 │
┌───────────────▼─────────────────▼───────────┐ ┌───▼─────────────────▼───────────┐
│ Instance 1 (Host/Pod A)                     │ │ Instance 2 (Host/Pod B)         │
│ ┌─────────────────────────────────────────┐ │ │ ┌─────────────────────────────┐ │
│ │ StreamThread 1                          │ │ │ │ StreamThread 1              │ │
│ │  ┌───────────────┐   ┌────────────────┐ │ │ │  ┌───────────────┐             │ │
│ │  │ Task 0_0 [P0] │   │ Task 0_1 [P1]  │ │ │ │  │ Task 0_2 [P2] │             │ │
│ │  │ Active        │   │ Active         │ │ │ │  │ Active        │             │ │
│ │  └───────┬───────┘   └───────┬────────┘ │ │ │  └───────┬───────┘             │ │
│ │          │                   │          │ │ │          │                     │ │
│ │   ┌──────▼──────┐     ┌──────▼──────┐   │ │ │   ┌──────▼──────┐              │ │
│ │   │ RocksDB (0) │     │ RocksDB (1) │   │ │ │   │ RocksDB (2) │              │ │
│ │   └─────────────┘     └─────────────┘   │ │ │   └─────────────┘              │ │
│ └─────────────────────────────────────────┘ │ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────────────┐ │ ┌─────────────────────────────────┐ │
│ │ StreamThread 2                          │ │ │ StreamThread 2                  │ │
│ │  ┌────────────────────────────────────┐ │ │ │  ┌────────────────────────────┐ │ │
│ │  │ Task 0_3-Standby (Shadowing P3)    │ │ │ │  │ Task 0_3 [P3] (Active)     │ │ │
│ │  └────────────────────────────────────┘ │ │ │  └────────────────────────────┘ │ │
│ └─────────────────────────────────────────┘ │ └─────────────────────────────────┘ │
└─────────────────────────────────────────────┘ └─────────────────────────────────┘
```

**Ключевые правила распределения:**
1. Если приложение имеет 4 входные партиции, создается ровно 4 активные задачи: `0_0`, `0_1`, `0_2`, `0_3`.
2. Добавление инстансов или потоков сверх числа входных партиций приводит к простаиванию лишних потоков (idle threads), если не настроены `StandbyTask`.
3. Потоки одного приложения распределяются между всеми запущенными инстансами с одинаковым `application.id`.

### Устройство локального хранилища RocksDB и потребление памяти

Каждый stateful-процессор внутри задачи создает изолированный экземпляр RocksDB. RocksDB — это встраиваемая база данных на основе LSM-дерева (Log-Structured Merge-tree), написанная на C++. Взаимодействие с ней из JVM происходит через JNI (Java Native Interface).

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Хост / Контейнер (RAM)                          │
├───────────────────────────────────┬────────────────────────────────────┤
│ JVM Heap                          │ Off-Heap (Native C++ Memory)       │
│                                   │                                    │
│ ┌───────────────────────────────┐ │ ┌────────────────────────────────┐ │
│ │ Kafka Consumer / Producer     │ │ │ RocksDB Block Cache            │ │
│ │ Record Caches                 │ │ │ (кэш несжатых блоков данных)   │ │
│ │ SerDes Buffers                │ │ ├────────────────────────────────┤ │
│ │ Java Application Objects      │ │ │ MemTables (Write Buffers)      │ │
│ └───────────────────────────────┘ │ │ (активные буферы записи в RAM) │ │
│                                   │ ├────────────────────────────────┤ │
│                                   │ │ Index & Filter Blocks (Bloom)  │ │
│                                   │ ├────────────────────────────────┤ │
│                                   │ │ OS Page Cache (файлы SST, WAL) │ │
│                                   │ └────────────────────────────────┘ │
└───────────────────────────────────┴────────────────────────────────────┘
```

> [!CAUTION]
> **Внекучевая память (Off-Heap) и OOM Killer:**
> По умолчанию каждый RocksDB State Store выделяет собственную память под MemTables и Block Cache. Если в приложении 16 задач и в каждой топологии по 3 state store, создается 48 независимых инстансов RocksDB. Без централизованного ограничения памяти суммарный native-расход выходит за лимиты контейнера cgroup, и процесс мгновенно завершается ядром Linux с сигналом `SIGKILL` (код завершения 137).

### Внутренние топики (Internal Topics)

Kafka Streams автоматически регистрирует и администрирует внутренние топики через встроенный `AdminClient`:

| Тип топика | Шаблон имени | Политика очистки | Назначение |
|---|---|---|---|
| **Changelog** | `<application.id>-<store-name>-changelog` | `compact` | Репликация изменений State Store. При падении инстанса или переносе задачи состояние восстанавливается чтением этого лога. |
| **Repartition** | `<application.id>-<operator>-repartition` | `delete` (`retention.ms` по умолчанию минимален) | Буферизация и перераспределение записей при вызове `selectKey()`, `groupBy()` или `join()` с несогласованным ключом. |

**Требования брокера к внутренним топикам:**
- Количество партиций в changelog- и repartition-топиках обязано строго совпадать с числом партиций входного топика.
- Брокер Kafka должен разрешать создание топиков клиентом либо внутренние топики должны создаваться pre-provisioning скриптами CI/CD с корректными параметрами компактификации.

### Протокол ребалансировки Cooperative Sticky

До появления Cooperative Rebalance (KIP-429 / KIP-441) процедура распределения партиций (Eager Protocol) приводила к полной остановке всех задач (stop-the-world): все консьюмеры сбрасывали смещения, закрывали локальные базы RocksDB и ожидали назначения.

В современном Kafka Streams по умолчанию активен `CooperativeStickyAssignor`:
1. При перезапуске одного пода активные задачи на здоровых подах **не останавливаются**.
2. Воркер, лишающийся задачи, плавно закрывает хранилище и коммитит смещения.
3. Если задача переносится на узел, где уже существовала прогретая `StandbyTask`, переключение происходит за доли секунды без выкачивания changelog-топика из брокера.

---

## Практические сценарии и конфигурация

### Сценарий 1: Production-конфигурация `streams.properties`

Файл конфигурации для отказоустойчивого развертывания с жесткими гарантиями консистентности и управляемой утилизацией памяти:

```properties
# -------------------------------------------------------------
# Идентификация и брокеры
# -------------------------------------------------------------
# Уникальный идентификатор приложения (используется как consumer group.id и префикс топиков)
application.id=payment-enrichment-stream-prod

# Список брокеров Kafka
bootstrap.servers=kafka-broker-01.infra.internal:9092,kafka-broker-02.infra.internal:9092,kafka-broker-03.infra.internal:9092

# Уникальный ID инстанса для удобства трассировки в логах и JMX
client.id=payment-enrichment-node-01

# -------------------------------------------------------------
# Надежность и транзакции (EOS)
# -------------------------------------------------------------
# Гарантия обработки ровно один раз версии 2
processing.guarantee=exactly_once_v2

# Фактор репликации для автоматически создаваемых changelog и repartition топиков
replication.factor=3

# Минимальное число синхронных реплик для внутренних топиков
topic.min.insync.replicas=2

# Таймаут транзакций (должен быть меньше transaction.max.timeout.ms на брокере)
transaction.timeout.ms=30000

# -------------------------------------------------------------
# Параллелизм и локальное состояние
# -------------------------------------------------------------
# Количество потоков обработки на текущем JVM-инстансе
num.stream.threads=4

# Количество теплых реплик на других узлах для мгновенного failover
num.standby.replicas=1

# Каталог для хранения баз RocksDB (ОБЯЗАТЕЛЬНО выделенный диск, НЕ /tmp)
state.dir=/var/lib/kafka-streams/payment-enrichment

# Допустимое отставание standby-реплики в записях перед промоутом до active
acceptable.recovery.lag=10000

# -------------------------------------------------------------
# Буферизация и тайминги
# -------------------------------------------------------------
# Суммарный объем буфера кэширования записей перед записью в RocksDB (на процесс)
statestore.cache.max.bytes=67108864

# Интервал фиксации состояния и транзакций (мс)
commit.interval.ms=100

# Максимальный интервал между вызовами poll() до выбывания из группы
max.poll.interval.ms=300000

# Сериализаторы по умолчанию
default.key.serde=org.apache.kafka.common.serialization.Serdes$StringSerde
default.value.serde=org.apache.kafka.common.serialization.Serdes$ByteArraySerde

# Оптимизация топологии (объединение узлов перепартиционирования)
topology.optimization=all

# -------------------------------------------------------------
# Ограничение памяти RocksDB через кастомный класс
# -------------------------------------------------------------
rocksdb.config.setter=org.infra.kafka.streams.BoundedRocksDBConfigSetter
```

### Сценарий 2: Ограничение Off-Heap памяти RocksDB через BoundedMemory

Для предотвращения падения контейнеров по Linux OOM необходимо использовать единый пул памяти (`org.rocksdb.Cache` и `org.rocksdb.WriteBufferManager`), разделяемый между всеми экземплярами RocksDB внутри JVM-процесса:

```java
package org.infra.kafka.streams;

import org.apache.kafka.streams.state.RocksDBConfigSetter;
import org.rocksdb.BlockBasedTableConfig;
import org.rocksdb.Cache;
import org.rocksdb.LRUCache;
import org.rocksdb.Options;
import org.rocksdb.WriteBufferManager;

import java.util.Map;

public class BoundedRocksDBConfigSetter implements RocksDBConfigSetter {
    // 512 MB суммарно под кэш блоков для ВСЕХ State Stores на процесс
    private static final long TOTAL_CACHE_SIZE_BYTES = 512 * 1024 * 1024L;
    // 256 MB суммарно под MemTables (буферы записи)
    private static final long TOTAL_WRITE_BUFFER_SIZE_BYTES = 256 * 1024 * 1024L;

    private static final Cache SHARED_BLOCK_CACHE = new LRUCache(TOTAL_CACHE_SIZE_BYTES);
    private static final WriteBufferManager WRITE_BUFFER_MANAGER = 
            new WriteBufferManager(TOTAL_WRITE_BUFFER_SIZE_BYTES, SHARED_BLOCK_CACHE);

    @Override
    public void setConfig(String storeName, Options options, Map<String, Object> configs) {
        BlockBasedTableConfig tableConfig = (BlockBasedTableConfig) options.tableFormatConfig();
        if (tableConfig == null) {
            tableConfig = new BlockBasedTableConfig();
        }

        // Привязываем общий кэш и заставляем индексы/фильтры жить в этом же кэше
        tableConfig.setBlockCache(SHARED_BLOCK_CACHE);
        tableConfig.setCacheIndexAndFilterBlocks(true);
        tableConfig.setPinL0FilterAndIndexBlocksInCache(true);
        tableConfig.setCacheIndexAndFilterBlocksWithHighPriority(true);

        options.setTableFormatConfig(tableConfig);
        options.setWriteBufferManager(WRITE_BUFFER_MANAGER);

        // Ограничиваем количество фоновых потоков compaction на один store
        options.setMaxBackgroundJobs(2);
    }

    @Override
    public void close(String storeName, Options options) {
        // Очистка ресурсов при закрытии хранилища
    }
}
```

### Сценарий 3: Обработка ошибок десериализации (DLQ) и исключений потоков

В production «сообщение-отравитель» (битый JSON, несоответствие Avro-схеме) не должно останавливать обработку всего топика.

**Настройка перенаправления битых записей (Deserialization Exception Handling):**

```properties
default.deserialization.exception.handler=org.apache.kafka.streams.errors.LogAndContinueExceptionHandler
```

Для промышленного продакшена пишется кастомный обработчик, отправляющий битые записи в DLT (Dead Letter Topic):

```java
package org.infra.kafka.streams;

import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.streams.errors.DeserializationExceptionHandler;
import org.apache.kafka.streams.processor.ProcessorContext;
import org.apache.kafka.common.record.TimestampType;

import java.util.Map;

public class DeadLetterQueueDeserializationHandler implements DeserializationExceptionHandler {
    private KafkaProducer<byte[], byte[]> deadLetterProducer;
    private String dlqTopic = "payment-enrichment.dlq";

    @Override
    public DeserializationHandlerResponse handle(ProcessorContext context,
                                                org.apache.kafka.clients.consumer.ConsumerRecord<byte[], byte[]> record,
                                                Exception exception) {
        // Отправка некорректного сообщения в служебный топик для дальнейшего разбора инженерами
        deadLetterProducer.send(new ProducerRecord<>(
            dlqTopic, null, record.timestamp(), record.key(), record.value(), record.headers()
        ));
        return DeserializationHandlerResponse.CONTINUE;
    }

    @Override
    public void configure(Map<String, ?> configs) {
        // Инициализация KafkaProducer по параметрам
    }
}
```

**Обработка неотловленных ошибок в runtime:**

```java
kafkaStreams.setUncaughtExceptionHandler(exception -> {
    // Если упал отдельный поток — безопасно перезапускаем поток вместо убийства всего пода
    return StreamsUncaughtExceptionHandler.StreamThreadExceptionResponse.REPLACE_THREAD;
});
```

### Сценарий 4: Развертывание под Systemd на Linux-сервере

При развертывании на выделенных серверах или ВМ RocksDB должен располагаться на быстром локальном NVMe-накопителе:

Файл `/etc/systemd/system/kafka-streams-payment.service`:
```ini
[Unit]
Description=Kafka Streams Payment Enrichment Service
After=network.target local-fs.target
Wants=network-online.target

[Service]
Type=simple
User=kafka-apps
Group=kafka-apps
Environment="JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64"
Environment="APP_HOME=/opt/kafka-streams-payment"
Environment="MALLOC_ARENA_MAX=2"
Environment="JAVA_OPTS=-Xms4g -Xmx4g -XX:+UseG1GC -XX:MaxGCPauseMillis=20 -XX:InitiatingHeapOccupancyPercent=45 -XX:+ExplicitGCInvokesConcurrent"

WorkingDirectory=/opt/kafka-streams-payment
ExecStart=/usr/bin/java $JAVA_OPTS -jar /opt/kafka-streams-payment/app.jar --config=/etc/kafka-streams/streams.properties

# Корректное завершение (graceful shutdown) для фиксации RocksDB и коммита смещений
TimeoutStopSec=120
KillMode=mixed
KillSignal=SIGTERM

# Ограничения ОС для работы с RocksDB и сокетами
LimitNOFILE=65536
LimitNPROC=8192
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

Команды управления сервисом:
```bash
# Перечитывание конфигурации systemd
sudo systemctl daemon-reload

# Запуск сервиса
sudo systemctl start kafka-streams-payment.service

# Проверка статуса
sudo systemctl status kafka-streams-payment.service
# → ● kafka-streams-payment.service - Kafka Streams Payment Enrichment Service
#      Loaded: loaded (/etc/systemd/system/kafka-streams-payment.service; enabled; preset: enabled)
#      Active: active (running) since Mon 2026-10-12 14:30:10 UTC; 25min ago
#    Main PID: 34120 (java)
#       Tasks: 42 (limit: 8192)
#      Memory: 5.8G (max: 8.0G)
#         CPU: 18.2s
#      CGroup: /system.slice/kafka-streams-payment.service
#              └─34120 /usr/lib/jvm/java-21-openjdk-amd64/bin/java -Xms4g -Xmx4g ...
```

### Сценарий 5: Развертывание в Kubernetes через StatefulSet

Для приложений с локальным состоянием RocksDB предпочтительнее использовать `StatefulSet` с локальными PersistentVolume (Local PV / NVMe) вместо `Deployment`. Это гарантирует, что под после рестарта монтирует свой прежний диск и не выкачивает десятки гигабайт из changelog-топиков:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: streams-payment-enrichment
  namespace: data-streams
  labels:
    app: streams-payment-enrichment
spec:
  serviceName: streams-payment-enrichment-headless
  replicas: 4
  podManagementPolicy: Parallel
  updateStrategy:
    type: RollingUpdate
  selector:
    matchLabels:
      app: streams-payment-enrichment
  template:
    metadata:
      labels:
        app: streams-payment-enrichment
    spec:
      terminationGracePeriodSeconds: 120
      containers:
        - name: streams-app
          image: internal-registry.infra.local/apps/streams-payment:v1.4.2
          env:
            - name: STATE_DIR
              value: /var/data/kafka-streams
            - name: JAVA_TOOL_OPTIONS
              value: "-Xms3g -Xmx3g -XX:+UseG1GC -XX:+ExitOnOutOfMemoryError"
          ports:
            - name: metrics
              containerPort: 7071
            - name: http-query
              containerPort: 8080
          resources:
            requests:
              cpu: "2000m"
              memory: "6Gi"
            limits:
              cpu: "4000m"
              memory: "7Gi"
          volumeMounts:
            - name: rocksdb-storage
              mountPath: /var/data/kafka-streams
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health/live
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 10
  volumeClaimTemplates:
    - metadata:
        name: rocksdb-storage
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: local-nvme-sc
        resources:
          requests:
            storage: 100Gi
```

> [!TIP]
> **Переменная `podManagementPolicy: Parallel`:**
> Позволяет Kubernetes обновлять и масштабировать поды без строгого порядкового ожидания (0 -> 1 -> 2), что в сочетании с Cooperative Sticky Assignor сокращает время редеплоя кластера в несколько раз.

---

## Эксплуатация и управление (Operations)

### Сброс состояния приложения через `kafka-streams-application-reset`

Утилита `kafka-streams-application-reset` поставляется в дистрибутиве Apache Kafka (`/opt/kafka/bin/`). Она применяется при смене схемы данных, изменении топологии либо необходимости полной переобработки истории топиков.

Утилита выполняет следующие действия:
1. Сбрасывает смещения (offsets) консьюмеров входных топиков на начало (`earliest`) или указанное значение.
2. Удаляет внутренние топики (changelog и repartition топики приложения).

> [!IMPORTANT]
> **Золотое правило сброса:**
> Перед запуском утилиты **ВСЕ экземпляры приложения должны быть остановлены**. Если хотя бы один инстанс останется работать во время сброса, он тут же пересоздаст топики или восстановит старые коммиты, что приведет к повреждению данных.

#### Пошаговый регламент полного сброса (Full Reset Playbook):

**Шаг 1. Остановка всех инстансов приложения:**
```bash
# Для Kubernetes
kubectl scale statefulset streams-payment-enrichment -n data-streams --replicas=0
# → statefulset.apps/streams-payment-enrichment scaled

# Проверка, что подов не осталось
kubectl get pods -n data-streams -l app=streams-payment-enrichment
# → No resources found in data-streams namespace.
```

**Шаг 2. Запуск в режиме имитации (`--dry-run`):**
```bash
/opt/kafka/bin/kafka-streams-application-reset.sh \
  --bootstrap-servers kafka-broker-01.infra.internal:9092 \
  --application-id payment-enrichment-stream-prod \
  --input-topics raw-payments,customer-profiles \
  --dry-run
```
*Ожидаемый вывод:*
```text
# → Reset-offsets for input topics [raw-payments, customer-profiles]
# → Following input topics offsets will be reset to (earliest):
# → Topic: raw-payments, Partition: 0, New-Offset: 0
# → Topic: raw-payments, Partition: 1, New-Offset: 0
# → Topic: raw-payments, Partition: 2, New-Offset: 0
# → Topic: raw-payments, Partition: 3, New-Offset: 0
# → Topic: customer-profiles, Partition: 0, New-Offset: 0
# → Deleting specified internal topics:
# → Topic: payment-enrichment-stream-prod-KSTREAM-AGGREGATE-STATE-STORE-0000000003-changelog
# → Topic: payment-enrichment-stream-prod-payment-join-repartition
# → Dry run complete. No changes were made.
```

**Шаг 3. Исполнение сброса:**
```bash
/opt/kafka/bin/kafka-streams-application-reset.sh \
  --bootstrap-servers kafka-broker-01.infra.internal:9092 \
  --application-id payment-enrichment-stream-prod \
  --input-topics raw-payments,customer-profiles \
  --execute
```
*Ожидаемый вывод:*
```text
# → Reset-offsets for input topics [raw-payments, customer-profiles]
# → Successfully reset offsets for input topics.
# → Deleting internal topics...
# → Successfully deleted internal topics:
# → [payment-enrichment-stream-prod-KSTREAM-AGGREGATE-STATE-STORE-0000000003-changelog, payment-enrichment-stream-prod-payment-join-repartition]
# → Done.
```

**Шаг 4. Очистка локального каталога `state.dir` на узлах:**
Так как внутренние топики удалены, старые файлы RocksDB на дисках инстансов невалидны и должны быть удалены перед запуском:
```bash
# Удаление файлов локального состояния на ноде
rm -rf /var/lib/kafka-streams/payment-enrichment/payment-enrichment-stream-prod/*
```

**Шаг 5. Запуск приложения:**
```bash
kubectl scale statefulset streams-payment-enrichment -n data-streams --replicas=4
# → statefulset.apps/streams-payment-enrichment scaled
```

### Инспекция каталога состояния `state.dir`

Структура каталогов на диске хоста:
```text
/var/lib/kafka-streams/payment-enrichment/
└── payment-enrichment-stream-prod/
    ├── 0_0/                       # Task ID: подтопология 0, партиция 0
    │   ├── rocksdb/
    │   │   └── aggregates-store/  # База RocksDB
    │   │       ├── 000042.sst     # Таблица SST
    │   │       ├── CURRENT
    │   │       ├── MANIFEST-000002
    │   │       └── LOG
    │   └── .lock                  # Блокировка задачи процессом
    ├── 0_1/
    └── kafka-streams-process-metadata
```

Проверка размера каталогов задач:
```bash
du -sh /var/lib/kafka-streams/payment-enrichment/payment-enrichment-stream-prod/*
# → 1.4G    /var/lib/kafka-streams/payment-enrichment/payment-enrichment-stream-prod/0_0
# → 1.3G    /var/lib/kafka-streams/payment-enrichment/payment-enrichment-stream-prod/0_1
# → 4.0K    /var/lib/kafka-streams/payment-enrichment/payment-enrichment-stream-prod/kafka-streams-process-metadata
```

### Динамическое управление потоками через JMX / Code

Kafka Streams позволяет менять число активных потоков без перезапуска JVM:

```bash
# Вызов добавления потока через jconsole или jmx4perl:
# MBean: "kafka.streams:type=KafkaStreams,name=payment-enrichment-node-01"
# Операция: addStreamThread()
```

В коде приложения:
```java
// Добавить рабочий поток в рантайме при росте входящей нагрузки
Optional<String> newThread = kafkaStreams.addStreamThread();

// Удалить рабочий поток при спаде нагрузки
Optional<String> removedThread = kafkaStreams.removeStreamThread(Duration.ofSeconds(30));
```

---

## Мониторинг, метрики и алертинг

Kafka Streams предоставляет богатый набор метрик через JMX. Для экспорта в Prometheus рекомендуется `jmx_prometheus_javaagent`.

### Ключевые JMX-метрики

| Категория | MBean / Имя метрики | Описание | Критический порог |
|---|---|---|---|
| **Потоки** | `kafka.streams:type=stream-metrics,client-id=*` -> `alive-stream-threads` | Число работающих потоков обработки | `< num.stream.threads` (Алерт!) |
| **Потоки** | `kafka.streams:type=stream-metrics,client-id=*` -> `failed-stream-threads` | Число потоков, завершившихся по ошибке | `> 0` (Критический инцидент) |
| **Пропускная способность** | `kafka.streams:type=stream-thread-metrics,thread-id=*` -> `process-rate` | Число обработанных записей в секунду | Резкое падение до 0 |
| **Фиксация** | `kafka.streams:type=stream-thread-metrics,thread-id=*` -> `commit-rate` | Частота фиксации транзакций/смещений | `== 0` при наличии входных данных |
| **Восстановление** | `kafka.streams:type=stream-state-updater-metrics` -> `restore-remaining-records` | Число записей, оставшихся до полного прогрева store | Мониторинг времени прогрева пода |
| **Дроп записей** | `kafka.streams:type=stream-task-metrics,task-id=*` -> `dropped-records-rate` | Записи, отброшенные из-за late-arrival или битых данных | `> 0` |
| **RocksDB I/O** | `kafka.streams:type=stream-state-metrics,client-id=*,task-id=*,store-id=*` -> `bytes-written-rate` | Скорость записи на диск в локальный store | Контроль I/O лимитов диска |

### Конфигурация Prometheus JMX Exporter

Файл `/etc/kafka-streams/jmx-exporter-config.yaml`:
```yaml
lowercaseOutputName: true
lowercaseOutputLabelNames: true
rules:
  # Метрики потоков (alive/failed threads)
  - pattern: 'kafka.streams<type=stream-metrics, client-id=(.+)><>(alive-stream-threads|failed-stream-threads): (.+)'
    name: kafka_streams_$2
    labels:
      client_id: "$1"

  # Метрики производительности потока (process-rate, commit-rate, poll-rate)
  - pattern: 'kafka.streams<type=stream-thread-metrics, thread-id=(.+)><>(process-rate|commit-rate|poll-rate): (.+)'
    name: kafka_streams_thread_$2
    labels:
      thread_id: "$1"

  # Метрики восстановления состояния (восстановление changelog)
  - pattern: 'kafka.streams<type=stream-task-metrics, task-id=(.+)><>(restore-remaining-records|dropped-records-rate): (.+)'
    name: kafka_streams_task_$2
    labels:
      task_id: "$1"
```

### Prometheus Alerting Rules

```yaml
groups:
  - name: kafka-streams-alerts
    rules:
      - alert: KafkaStreamsThreadFailed
        expr: kafka_streams_failed_stream_threads > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Поток Kafka Streams упал на инстансе {{ $labels.client_id }}"
          description: "Один или несколько потоков завершились аварийно. Возможно необработанное исключение или нехватка памяти."

      - alert: KafkaStreamsActiveThreadsDegraded
        expr: kafka_streams_alive_stream_threads < 4
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Деградация параллелизма Kafka Streams ({{ $labels.client_id }})"
          description: "Число активных потоков {{ $value }} меньше целевого значения."

      - alert: KafkaStreamsHighDroppedRecords
        expr: rate(kafka_streams_task_dropped_records_rate[5m]) > 5
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Потеря/отброс записей в Kafka Streams"
          description: "Записи отбрасываются из-за позднего времени поступления (late records) или ошибок сериализации."
```

---

## Диагностика и устранение неполадок

### 1. Аварийная остановка потоков (`All StreamThreads are dead`)

**Симптомы:** Метрика `alive-stream-threads` падает в 0, процесс висит, обработка сообщений полностью прекращается, консьюмер перестает слать heartbeat брокеру.
**Причина:** В коде топологии возникло непроверяемое исключение (`NullPointerException`, `ClassCastException`, ошибка десериализации), которое не было перехвачено. По умолчанию поведение Kafka Streams при необработанном исключении — закрытие упавшего потока (`StreamThread.State: DEAD`). Когда падают все потоки, приложение переходит в состояние `ERROR`.

**Диагностика:**
```bash
# Поиск стека ошибки в логах приложения
journalctl -u kafka-streams-payment.service --since "1 hour ago" | grep -A 10 "Encountered following error during processing"
```
*Пример вывода:*
```text
# → ERROR [payment-enrichment-node-01-StreamThread-2] org.apache.kafka.streams.processor.internals.StreamThread: 
# → stream-thread [payment-enrichment-node-01-StreamThread-2] Encountered following error during processing. 
# → java.lang.NullPointerException: Cannot invoke "String.toUpperCase()" because the return value of "Payment.getUser()" is null
# →   at org.infra.kafka.streams.PaymentTopology.lambda$build$0(PaymentTopology.java:45)
# →   at org.apache.kafka.streams.kstream.internals.KStreamMapValues$KStreamMapValuesProcessor.process(KStreamMapValues.java:41)
```

**Решение:**
1. Настроить глобальный обработчик `setUncaughtExceptionHandler` с политикой `REPLACE_THREAD` (позволяет приложению продолжить работу, если баг затронул отдельную запись).
2. Зафиксировать NPE в коде топологии.
3. Добавить `LogAndContinueExceptionHandler` для битых сообщений.

### 2. Шторм ребалансировок и `CommitFailedException`

**Симптомы:** Постоянные ребалансировки в логах: `PreparingRebalance -> CompletingRebalance`. Обработка идет рывками, задачи бесконечно передаются между подами.
**Причина:** Превышение таймаута `max.poll.interval.ms` (по умолчанию 300 000 мс = 5 минут). Если обработка пачки записей или первичная инициализация и чтение состояния из RocksDB занимает больше времени, координатор группы считает инстанс мертвым и инициирует ребалансировку.

**Диагностика:**
```bash
grep -i "CommitFailedException" /var/log/kafka-streams/app.log
# → org.apache.kafka.clients.consumer.CommitFailedException: 
# → Offset commit cannot be completed since the consumer is not part of an active group for auto partition assignment;
# → it is likely that the time between consecutive polls has exceeded max.poll.interval.ms.
```

**Решение:**
1. Увеличить `max.poll.interval.ms` до 600000 (10 минут), если операции агрегации требуют длительного времени.
2. Уменьшить размер пачки записей: `max.poll.records=500` (или `200`).
3. Включить `num.standby.replicas=1` — тогда при ребалансировках новому владельцу не придется читать changelog-топик с нуля.

### 3. Завершение процесса по сигналу OOM Killer (Exit Code 137)

**Симптомы:** JVM-процесс мгновенно исчезает без сообщений `java.lang.OutOfMemoryError` в логах. Команда `dmesg` или системный журнал фиксируют вызов ядра `oom-killer`.
**Причина:** Неконтролируемый рост native-памяти RocksDB (Block Cache + MemTables всех созданных State Store) в сумме с JVM Heap превысил память контейнера или хоста.

**Диагностика:**
```bash
# Проверка системного лога на срабатывание OOM Killer
sudo dmesg -T | grep -E -i "oom[-_]killer|killed process"
```
*Пример вывода:*
```text
# → [Mon Oct 12 14:15:22 2026] Memory cgroup out of memory: Killed process 34120 (java) total-vm:14820120kB, anon-rss:7245800kB, file-rss:32140kB, shmem-rss:0kB, UID 1001 pgtables:18400kB oom_score_adj:998
```

**Решение:**
1. Реализовать `BoundedRocksDBConfigSetter` (см. Сценарий 2) с жестким ограничением общего кэша.
2. Ограничить арены glibc: добавить в окружение сервиса `MALLOC_ARENA_MAX=2`.
3. Рассчитывать лимит памяти контейнера по формуле: `Container Limit = Heap (Xmx) + RocksDB Cache + RocksDB Memtables + 1.5 GB (OS buffer + thread stacks)`.

### 4. `ProducerFencedException` и зомби-инстансы в режиме EOS

**Симптомы:** В логах появляется исключение:
`org.apache.kafka.common.errors.ProducerFencedException: Producer attempted an operation with an old epoch`.
**Причина:** При использовании `processing.guarantee=exactly_once_v2` брокер назначает каждому инстансу эпохи транзакций. Если инстанс надолго завис (например, долгая GC-пауза) и группа переназначила его задачу другому инстансу, вернувшийся «зомби»-инстанс блокируется брокером, предотвращая дублирование данных.

**Диагностика:**
```bash
grep "ProducerFencedException" /var/log/kafka-streams/app.log
```

**Решение:**
- Это штатный защитный механизм Kafka Streams в режиме EOS.
- Поток, получивший `ProducerFencedException`, должен быть корректно закрыт и пересоздан (`REPLACE_THREAD`), либо весь процесс перезапущен, чтобы под заново синхронизировал метаданные.

### 5. Повреждение State Store (`CorruptedStateStoreException` / Disk I/O Error)

**Симптомы:** Ошибка при старте: `org.apache.kafka.streams.errors.ProcessorStateException: Error opening store ...`.
**Причина:** Аварийное отключение питания, переполнение диска (`No space left on device`) или жесткий перезапуск сервера во время записи в файлы SST RocksDB.

**Диагностика:**
```bash
# Проверка свободного места на диске
df -h /var/lib/kafka-streams
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/nvme0n1p1   98G   98G     0 100% /var/lib/kafka-streams
```

**Решение:**
1. Освободить место на диске.
2. Если повреждена локальная база RocksDB, безопасный способ восстановления — удалить локальный каталог сбойной задачи (например, `rm -rf /var/lib/kafka-streams/.../0_2`).
3. При следующем запуске Kafka Streams обнаружит отсутствие локального store и автоматически перекачает всё состояние из авторитетного топика `<application.id>-<store>-changelog`.

---

## Рекомендации и лучшие практики (Best Practices)

### SRE-чеклист для Production

#### 1. Дисковая подсистема и хранилище
- [ ] **Никогда не использовать `/tmp`:** По умолчанию `state.dir` указывает на `/tmp/kafka-streams`. В большинстве дистрибутивов Linux `/tmp` очищается утилитой `systemd-tmpfiles` либо монтируется как `tmpfs` в оперативной памяти. Всегда задавайте постоянный путь (`/var/lib/kafka-streams/...`).
- [ ] **Только быстрые диски (NVMe / SSD):** RocksDB генерирует высокий случайный I/O при сбросе MemTable и процедурах compaction. Использование сетевых файловых систем (NFS, CIFS) категорически запрещено из-за проблем с файловыми блокировками (`.lock`) и задержками `fsync`.
- [ ] **Монтирование дисков с флагом `noatime`:** Снижает накладные расходы файловой системы при чтении файлов SST.

#### 2. Планирование ресурсов и памяти
- [ ] **Формула расчета RAM:**
  $$\text{RAM}_{\text{total}} = \text{JVM Heap } (Xmx) + \text{RocksDB Block Cache} + (\text{MemTables} \times \text{Stores}) + 1.5\text{ GB (Stack/Direct/Glibc)}$$
- [ ] **Тюнинг JVM:** Для Kafka Streams рекомендуется сборщик мусора **G1GC** (`-XX:+UseG1GC -XX:MaxGCPauseMillis=20`). Большие паузы GC приводят к выбыванию из consumer group и каскадным ребалансировкам.
- [ ] **Ограничение Glbc Memory Arenas:** Добавьте переменную `MALLOC_ARENA_MAX=2` (или `4`). По умолчанию glibc выделяет до $8 \times \text{cores}$ арен памяти, что в многопоточных Java+JNI приложениях приводит к фрагментации и раздуванию памяти виртуального адресного пространства.

#### 3. Сеть и брокеры Kafka
- [ ] **Топики Changelog:** Проверьте параметры внутренних топиков:
  - `cleanup.policy=compact`
  - `min.insync.replicas=2` (при `replication.factor=3`)
  - `delete.retention.ms=86400000` (1 сутки для надежной репликации tombstone-записей)
- [ ] **Упреждающее создание топиков:** В production-кластерах с отключенным `auto.create.topics.enable=false` внутренние топики должны создаваться заранее автоматизированными пайплайнами с правильным количеством партиций.

#### 4. Безопасность и эксплуатация
- [ ] **Graceful Shutdown Hook:** Всегда регистрируйте перехватчик остановки JVM:
  ```java
  Runtime.getRuntime().addShutdownHook(new Thread(() -> {
      // Даем до 2 минут на корректный коммит смещений и закрытие RocksDB
      kafkaStreams.close(Duration.ofMinutes(2));
  }));
  ```
  Это предотвратит повреждение файлов SST и исключит длительное восстановление при следующем старте.
- [ ] **Наличие Standby Replicas:** Настройка `num.standby.replicas=1` обязательна для stateful-приложений размером более 10 ГБ. Это сокращает среднее время восстановления (MTTR) при перезапуске ноды с десятков минут до нескольких секунд.

---

## См. также

- **[Обзор Apache Kafka](./kafka_overview.md)** — концептуальная архитектура брокеров, топиков и партиций
- **[Гарантии доставки сообщений](./delivery_guarantees.md)** — реализация Exactly-Once (EOS), транзакции и идемпотентность
- **[Партиционирование и балансировка топиков](./partitioning_and_balancing.md)** — стратегии партиционирования и параллелизм консьюмеров
- **[Kafka Connect в Production](./kafka_connect_production.md)** — архитектура коннекторов, внутренние топики и воркеры
- **[Schema Registry в Production](./kafka_schema_registry.md)** — управление Avro/JSON/Protobuf схемами для Kafka Streams SerDes
- **[Мониторинг Apache Kafka](./kafka_for_monitoring.md)** — настройка JMX Exporter, Prometheus и ключевые алерты кластера
- **[Тюнинг JVM и сборщика мусора для Kafka](./kafka_jvm_gc_tuning.md)** — оптимизация сборщиков G1GC и ZGC для компонентов Kafka
- **[Оптимизация параметров ОС Linux для Kafka](./kafka_os_tuning.md)** — сетевой стек, дисковые очереди и page cache ОС
- **[CLI утилиты Kafka](./kafka_cli_tools.md)** — консольные инструменты управления топиками и группами консьюмеров
- **[Kafka Troubleshooting Playbook](./kafka_troubleshooting_playbook.md)** — диагностика сетевых сбоев, лагов и аварий брокеров
