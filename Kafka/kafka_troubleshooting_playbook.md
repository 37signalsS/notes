# Troubleshooting Playbook для Apache Kafka

**Актуально для:** Apache Kafka 3.8.x / 3.9.x / 4.0.x (KRaft)

**Troubleshooting Playbook** — это структурированный операционный регламент для SRE, DevOps и системных администраторов по локализации, диагностике и устранению аварий в кластерах Apache Kafka под управлением KRaft. Документ содержит алгоритмы триажа, деревья решений (decision trees), низкоуровневые команды ОС Linux, анализ дампов JVM и сценарии восстановления доступности данных без потерь.

---

## Определения

- **High Watermark (HW):** Смещение (offset) последней записи, которая была успешно реплицирована на все синхронные реплики (ISR). Записи до HW доступны для чтения консьюмерами.
- **Log End Offset (LEO):** Смещение следующей записи, которая будет записана в локальный лог партиции на данном брокере.
- **Under-Replicated Partitions (URP):** Партиции, у которых количество актуальных реплик в ISR меньше сконфигурированного фактора репликации (`replication.factor`).
- **In-Sync Replicas (ISR):** Множество реплик партиции, которые полностью догнали лидера по журналу сообщений и находятся в пределах окна отставания `replica.lag.time.max.ms`.
- **Consumer Lag:** Разница между LEO лидера партиции и текущим зафиксированным смещением (committed offset) группы потребителей.
- **Hot Partition / Key Skew:** Аномальная концентрация входящего потока данных в одной или нескольких партициях из-за низкой кардинальности ключей партиционирования (`message.key`).
- **Poison Pill:** Сообщение с некорректной структурой данных, вызывающее циклическую фатальную ошибку десериализации или обработки на стороне консьюмера и блокирующее продвижение оффсета.
- **Rebalance Storm:** Лавинообразный процесс непрерывной перебалансировки партиций между членами consumer group, приводящий к полной остановке обработки сообщений.
- **KRaft Quorum & Leader Epoch:** Архитектура консенсуса метаданных на базе алгоритма Raft, заменившая ZooKeeper. Номер эпохи (epoch) служит барьером (fencing token) для предотвращения split-brain при смене лидера контроллеров.
- **Thread Starvation:** Дефицит процессорного времени или блокировка пулов потоков брокера (`network` или `io/request-handler`), приводящая к росту очередей запросов и тайм-аутам клиентов.
- **Backpressure:** Механизм сдерживания отправителей при исчерпании буферов или задержках записи на диск/сеть для предотвращения переполнения памяти.

---

## Основные концепции

### Архитектура диагностики и конвейер обработки запросов

Для быстрой локализации сбоев необходимо понимать путь запроса внутри брокера Kafka:

```
[ Клиент (Producer/Consumer) ]
             │
      TCP Сокет (:9092)
             ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. SocketServer / Acceptor Thread                           │
│    Принимает соединения, передает в Network Threads        │
└─────────────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Network Processors (num.network.threads)                 │
│    Читают сокет, декодируют кадры, помещают в очередь      │
└─────────────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Request Queue (queued.max.requests)                      │
│    Буфер ожидания запросов на исполнение                    │
└─────────────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Kafka Request Handlers (num.io.threads)                  │
│    Выполняют логику, работают с PageCache / Диском / ISR    │
└─────────────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. Purgatory (DelayedProduce / DelayedFetch)                │
│    Ожидание acks=all от реплик или min.bytes от консьюмеров  │
└─────────────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. Response Queue -> Network Processors -> TCP Socket       │
│    Отправка подтверждения или данных клиенту                │
└─────────────────────────────────────────────────────────────┘
```

Формула суммарного времени ответа брокера:
$$\text{TotalTime} = \text{RequestQueueTime} + \text{LocalTime} + \text{RemoteTime} + \text{ResponseQueueTime} + \text{ResponseSendTime}$$

- Высокий `RequestQueueTime`: перегрузка пула `num.io.threads` (IO Starvation) либо медленный диск.
- Высокий `LocalTime`: задержки обращения к PageCache, файловой системе или блокировки синхронизации.
- Высокий `RemoteTime`: задержки репликации между брокерами (ожидание подтверждения от follower при `acks=all`).
- Высокий `ResponseSendTime`: сетевые задержки или медленный прием со стороны клиента (TCP Window Full).

### Методология триажа (USE и RED)

1. **USE Метод (Utilization, Saturation, Errors) для хоста брокера:**
   - **CPU:** Загрузка ядер (`top`, `pidstat`), процент системного времени (I/O wait, context switching).
   - **Дисковая подсистема:** Утилизация дисков `%util`, время ожидания `await` (`iostat -xz 1`), дефицит грязных страниц PageCache (`vmstat -s`).
   - **Сеть:** Пропускная способность интерфейсов, насыщение очередей сокетов, процент TCP-ретрансмиссий (`ss -ti`, `sar -n ETCP 1`).
   - **JVM Память:** Использование Heap, Direct Memory, паузы сборщика мусора G1GC (`jstat -gcutil`, GC-логи).
2. **RED Метод (Rate, Errors, Duration) для Kafka:**
   - **Rate:** `MessagesInPerSec`, `BytesInPerSec`, `BytesOutPerSec`.
   - **Errors:** `UnderReplicatedPartitions`, `OfflinePartitionsCount`, `UnderMinIsrPartitionCount`, ошибки авторизации/протокола.
   - **Duration:** `TotalTimeMs` (p95, p99) по типам запросов (`Produce`, `FetchConsumer`, `FetchFollower`).

### Матрица ключевых метрик здоровья кластера

| JMX-метрика | Норма | Порог предупреждения (Warning) | Критический порог (Critical) | Значение и корневая причина |
|---|---|---|---|---|
| `kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions` | `0` | `> 0` | `> 0` (> 5 мин) | Реплики отстают от лидера. Риск потери данных или доступности при аварии. |
| `kafka.controller:type=KafkaController,name=OfflinePartitionCount` | `0` | `> 0` | `> 0` | Партиции не имеют активного лидера. Запись и чтение полностью заблокированы. |
| `kafka.server:type=ReplicaManager,name=UnderMinIsrPartitionCount` | `0` | `> 0` | `> 0` | Число реплик меньше `min.insync.replicas`. Запись с `acks=all` отклоняется (`NotEnoughReplicasException`). |
| `kafka.server:type=KafkaRequestHandlerPool,name=RequestHandlerAvgIdlePercent` | `> 0.50` | `< 0.30` | `< 0.15` | Голодание пула потоков ввода-вывода. Брокер перегружен запросами или завис на операциях с диском. |
| `kafka.network:type=SocketServer,name=NetworkProcessorAvgIdlePercent` | `> 0.50` | `< 0.30` | `< 0.15` | Голодание сетевых процессоров. Недостаточно `num.network.threads` для входящих TCP-соединений. |
| `kafka.network:type=RequestMetrics,name=RequestQueueTimeMs,request=Produce` | `< 5ms` | `> 20ms` | `> 100ms` | Запросы простаивают в очереди на обработку. Очередь `RequestChannel` переполнена. |
| `kafka.server:type=raft-leader-election-metrics,name=leader-id` (KRaft) | `id >= 0` | `LeaderId = -1` | `> 10s` без лидера | Потеря кворума контроллеров KRaft. Кластер не может обновлять метаданные и регистрировать топики/брокеры. |
| `kafka.server:type=ReplicaManager,name=IsrShrinksPerSec` | `0` | `> 0.1` | `> 1.0` | Нестабильность репликации. Постоянный выброс реплик из ISR из-за сети или диска. |

### Базовые команды оперативной экспресс-диагностики

```bash
# 1. Проверка доступности портов и узлов кластера
nc -zvw2 10.0.10.11 9092
# → Connection to 10.0.10.11 9092 port [tcp/*] succeeded!

# 2. Проверка состояния кворума метаданных KRaft
kafka-metadata-quorum.sh --bootstrap-server 10.0.10.11:9092 describe --status
# → ClusterId:              J6T3tYf4R8a0ZlMnOpQrSt
# → LeaderId:               1
# → LeaderEpoch:            4
# → HighWatermark:          124982
# → MaxFollowerLag:         0
# → MaxFollowerLagTimeMs:   12
# → CurrentVoters:          [1, 2, 3]

# 3. Выявление партиций с нарушенной репликацией (URP)
kafka-topics.sh --bootstrap-server 10.0.10.11:9092 --describe --under-replicated-partitions
# → (если вывод пуст — все реплики синхронизированы)

# 4. Проверка состояния consumer groups с максимальным лагом
kafka-consumer-groups.sh --bootstrap-server 10.0.10.11:9092 --describe --group payments-processor
# → GROUP              TOPIC           PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID     HOST            CLIENT-ID
# → payments-processor payments.events 0          1048576         1048590         14              consumer-1-a... /10.0.20.15     consumer-1

# 5. Экспресс-мониторинг загрузки пула обработчиков через JMX
kafka-run-class.sh kafka.tools.JmxTool \
  --object-name "kafka.server:type=KafkaRequestHandlerPool,name=RequestHandlerAvgIdlePercent" \
  --one-time true
# → "kafka.server:type=KafkaRequestHandlerPool,name=RequestHandlerAvgIdlePercent": {"OneMinuteRate": 0.842}

# 6. Анализ критических записей в журнале брокера
journalctl -u kafka -n 100 --no-pager | grep -E "ERROR|FATAL|CorruptRecord|Offline"
```

---

## Практические сценарии диагностики и устранения аварий

### Сценарий 1: Лавинообразный рост Consumer Lag и нестабильность групп (Rebalance Storms)

#### Симптомы и триггеры

- Алерт: `ConsumerLag > 100000` сообщений или экспоненциальный рост времени отставания `Estimated Max Lag Time`.
- Статус группы в `kafka-consumer-groups.sh`: непрерывные переходы в состояние `PreparingRebalance` или `CompletingRebalance`.
- Логи консьюмеров: частые исключения `CommitFailedException: Commit cannot be completed since the group has already rebalanced and assigned the partitions to another member`.

#### Decision Tree: Анализ Consumer Lag

```
Рост Consumer Lag
      │
      ├── 1. Проверить статус группы: kafka-consumer-groups.sh --describe --group <grp> --state
      │       ├── State = PreparingRebalance / CompletingRebalance
      │       │     └── Идет Rebalance Storm → перейти к ветке стабилизации членства
      │       ├── State = Empty / Dead
      │       │     └── Инстансы консьюмеров отключились → проверить логи подов/процессов
      │       └── State = Stable
      │             └── Группа стабильна → проверить распределение лага по партициям
      │
      ├── 2. Распределение лага:
      │       ├── Лаг растет равномерно на ВСЕХ партициях
      │       │     ├── Причина: Производительность обработки ниже входящего битрейта
      │       │     └── Действие: Масштабировать консьюмеры (до числа партиций) или ускорить бизнес-логику
      │       └── Лаг растет локально на ОДНОЙ партиции
      │             ├── Проверить LEO и входящий рейт:
      │             │     ├── Входящий поток на партицию кратно выше других → Hot Key / Key Skew
      │             │     └── Входящий поток нормален, но committed offset не двигается → Poison Pill
      │             └── Проверить статус воркера, обслуживающего проблемную партицию
      │
      └── 3. Проверка причины выпадения консьюмеров:
              ├── Время обработки пачки превышает max.poll.interval.ms (по умолчанию 300 000 ms = 5 мин)
              └── Сетевые обрывы heartbeat (heartbeat.interval.ms / session.timeout.ms)
```

#### Пошаговая диагностика

1. **Проверка состояния группы и распределения партиций:**

```bash
kafka-consumer-groups.sh --bootstrap-server 10.0.10.11:9092 \
  --describe --group orders-worker --state
# → GROUP         COORDINATOR (ID)          ASSIGNMENT-STRATEGY  STATE           #MEMBERS
# → orders-worker 10.0.10.12:9092 (2)       range                PreparingRebalance 8
```

2. **Детальный аудит участников и зависших инстансов:**

```bash
kafka-consumer-groups.sh --bootstrap-server 10.0.10.11:9092 \
  --describe --group orders-worker --members --verbose
# → MEMBER-ID                                  CLIENT-ID   HOST           GROUP-INSTANCE-ID  #ASSIGNED-PARTITIONS
# → orders-worker-app-1_697b0a...              orders-app  /10.0.20.11    worker-node-1      2
# → orders-worker-app-2_a44c11...              orders-app  /10.0.20.12    worker-node-2      0
```

3. **Проверка наличия Hot Key через анализ сегмента лога:**

```bash
kafka-dump-log.sh \
  --files /var/lib/kafka/data/orders.events-0/00000000000000100000.log \
  --print-data-log --deep-iteration | grep -o 'key: [^,]*' | sort | uniq -c | sort -rn | head -n 5
# → 145020 key: "CUSTOMER_DEFAULT"
# →      5 key: "USER_88192"
# →      3 key: "USER_11203"
# → (Обнаружен экстремальный перекос: ключ "CUSTOMER_DEFAULT" занимает 99% сообщений партиции)
```

#### План устранения и ликвидация Rebalance Storm

1. **Устранение Rebalance Storm:**
   - Перевести консьюмеры на статический протокол членства (`group.instance.id = "worker-<hostname>"`). При кратковременном перезапуске подов консьюмера координатор группы ждет `session.timeout.ms` (например, 45 секунд) и не инициирует глобальную перебалансировку.
   - Включить кооперативный assignor: `partition.assignment.strategy = org.apache.kafka.clients.consumer.CooperativeStickyAssignor`. В отличие от `RangeAssignor`, кооперативный протокол отзывает только перераспределяемые партиции, не останавливая мир (`Stop-The-World`) для всей группы.
2. **Ликвидация выпадений из-за долгой обработки:**
   - Если обработка одной пачки сообщений упирается во внешнюю СУБД, уменьшить `max.poll.records` (например, со `500` до `50`).
   - Увеличить `max.poll.interval.ms` (например, до `600000` мс / 10 минут), если тяжелые транзакции невозможно разбить.
3. **Ликвидация Hot Key:**
   - Если выявлен перекос ключа (Data Skew), внедрить в продюсере составной ключ (соление: `key = originalKey + "_" + (random % N)`) либо передавать `null` в качестве ключа для включения round-robin/sticky partitioner.

---

### Сценарий 2: Деградация репликации и Under-Replicated Partitions (URP / ISR Shrink)

#### Симптомы и триггеры

- Алерт: `UnderReplicatedPartitions > 0` в течение более 60 секунд.
- Метрика `kafka.server:type=ReplicaManager,name=IsrShrinksPerSec > 0`.
- Продюсеры с `acks=all` получают `NotEnoughReplicasException` (если число реплик в ISR упало ниже `min.insync.replicas`).

#### Decision Tree: Локализация URP

```
UnderReplicatedPartitions > 0
      │
      ├── 1. Выявить проблемные топики и брокеры:
      │       └── kafka-topics.sh --describe --under-replicated-partitions
      │             ├── Все URP связаны с ОДНИМ брокером (ID в поле Replicas, но нет в Isr)
      │             │     └── Проблема локализована на данном узле-follower → перейти к проверке узла
      │             └── URP распределены равномерно по всему кластеру
      │                   └── Системная деградация (сеть кластера / насыщение дисков на лидерах)
      │
      ├── 2. Проверка состояния брокера-follower:
      │       ├── Проверить доступность процесса Kafka: systemctl status kafka / jps
      │       ├── Проверить диск follower: iostat -xz 1 (%util > 90%, await > 20ms)
      │       ├── Проверить память и GC follower: долгие паузы Stop-The-World (> replica.lag.time.max.ms)
      │       └── Проверить сеть между лидером и follower: задержки, потери пакетов
      │
      └── 3. Проверка параметров отставания:
              ├── replica.lag.time.max.ms (по умолчанию 30 000 ms)
              └── num.replica.fetchers (дефицит потоков вычитки реплик)
```

#### Пошаговая диагностика

1. **Локализация выбывших реплик:**

```bash
kafka-topics.sh --bootstrap-server 10.0.10.11:9092 --describe --under-replicated-partitions
# → Topic: telemetry.events  Partition: 3  Leader: 1  Replicas: 1,2,3  Isr: 1,3
# → Topic: telemetry.events  Partition: 7  Leader: 1  Replicas: 1,2,3  Isr: 1,3
# → Topic: logs.audit        Partition: 1  Leader: 3  Replicas: 3,2,1  Isr: 3,1
# → (Брокер 2 отсутствует в списке Isr для всех проблемных партиций)
```

2. **Проверка сетевой задержки и сокетов до выбывшего узла (ID 2 = 10.0.10.12):**

```bash
# Проверка сокетов и TCP ретрансмиссий
ss -ti 'dport = :9092 and dst 10.0.10.12'
# → State   Recv-Q  Send-Q   Local Address:Port   Peer Address:Port
# → ESTAB   0       131072   10.0.10.11:58432     10.0.10.12:9092
# →  cubic wscale:7,7 rto:1200 rtt:850.4/120.2 ato:40 retrans:12/48 lost:6

# Замер дисковой задержки на узле 10.0.10.12
iostat -xz 1 3 | awk '{print $1, $8, $9, $10, $14}'
# → Device r_await w_await areq-sz %util
# → nvme0n1 0.42 124.50 128.00 98.40
# → (Диск перегружен операциями записи: w_await > 120ms, утилизация 98%)
```

3. **Проверка логов репликации на брокере-лидере (ID 1):**

```bash
grep -E "Shrinking ISR|Cached zkVersion" /var/log/kafka/server.log | tail -n 5
# → [2026-10-12 14:10:22,104] INFO [Partition telemetry.events-3] Shrinking ISR from 1,2,3 to 1,3 because follower 2 is lagging (replica.lag.time.max.ms=30000)
```

#### План устранения и ликвидация URP

1. **Аварийное дросселирование репликации при сатурации канала/диска:**
   Если выбывший брокер вернулся в строй и начинает вычитывать гигабайты отставания, он может перегрузить сеть и диски лидеров. Для предотвращения каскадного сбоя ограничить пропускную способность репликации:

```bash
# Ограничение скорости репликации на лидере и follower (например, 50 МБ/с = 52428800 байт/с)
kafka-configs.sh --bootstrap-server 10.0.10.11:9092 --alter \
  --entity-type brokers --entity-name 2 \
  --add-config leader.replication.throttled.rate=52428800,follower.replication.throttled.rate=52428800
# → Completed updating config for broker 2.
```

2. **Оптимизация пула репликации:**
   Если брокер не успевает вычитывать сотни партиций при наличии мощного CPU и быстрого диска, увеличить количество потоков репликации в `server.properties`:
   - `num.replica.fetchers=4` (по умолчанию `1`, рекомендуется от `2` до `cores / 4`).
   - `replica.fetch.max.bytes=5242880` (5 МБ за один Fetch-запрос).
3. **Снятие лимита после восстановления ISR:**

```bash
kafka-configs.sh --bootstrap-server 10.0.10.11:9092 --alter \
  --entity-type brokers --entity-name 2 \
  --delete-config leader.replication.throttled.rate,follower.replication.throttled.rate
# → Completed updating config for broker 2.
```

---

### Сценарий 3: Рост задержек (High Request Latency) и Thread Starvation

#### Симптомы и триггеры

- Алерт: `RequestHandlerAvgIdlePercent < 0.20` или `NetworkProcessorAvgIdlePercent < 0.20`.
- Метрика `RequestQueueTimeMs` возрастает с обычных 1–3 мс до 150–500 мс.
- Продюсеры регистрируют всплеск `TimeoutException` и `Expiring X record(s) for topic-partition: Y ms has passed since batch creation`.

#### Decision Tree: Локализация деградации задержек

```
Рост задержек (Latency)
      │
      ├── 1. Проверить распределение фаз задержки (JMX RequestMetrics):
      │       ├── RequestQueueTimeMs > 50ms
      │       │     └── Перегрузка очереди запросов → Thread Starvation пула num.io.threads
      │       ├── LocalTimeMs > 50ms
      │       │     └── Медленная запись на локальный диск или дефицит PageCache
      │       ├── RemoteTimeMs > 100ms
      │       │     └── Задержки подтверждения репликации (acks=all) → сетевой лаг фолловеров
      │       └── ResponseSendTimeMs > 50ms
      │             └── Сетевой сокет переполнен → медленный клиент (TCP window exhaustion)
      │
      ├── 2. Анализ системных узких мест:
      │       ├── CPU: top / pidstat (проверить I/O wait %wa и кражу тактов %steal)
      │       ├── Диск: vmstat -s (проверить рост "dirty pages" и сброс на диск)
      │       └── JVM GC: jstat -gcutil (STW паузы сборщика G1)
      │
      └── 3. Анализ дампов потоков (Thread Dump):
              └── Проверить потоки 'kafka-request-handler-*': состояние BLOCKED или WAITING
```

#### Пошаговая диагностика

1. **Инспекция метрик очередей брокера:**

```bash
kafka-run-class.sh kafka.tools.JmxTool \
  --object-name "kafka.network:type=RequestMetrics,name=RequestQueueTimeMs,request=Produce" \
  --one-time true
# → "kafka.network:type=RequestMetrics,name=RequestQueueTimeMs,request=Produce": {"99thPercentile": 218.4, "Mean": 84.1}
```

2. **Проверка состояния дискового кэша и I/O wait:**

```bash
vmstat 1 3
# → procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
# →  r  b   swpd   free   buff  cache   si   so    bi    bo   in    cs us sy id wa st
# →  8  4      0 120480 341020 28410240    0    0   120 18450 12400 18900 24 18 32 26  0
# → (Столбец 'b' (блокированные процессы) = 4, CPU 'wa' (I/O wait) = 26%)
```

3. **Снятие и анализ Thread Dump процесса брокера:**

```bash
# Получение PID процесса Kafka
KAFKA_PID=$(pgrep -f "kafka.Kafka")

# Снятие thread dump через jcmd
jcmd ${KAFKA_PID} Thread.print > /tmp/kafka_threads.tdump

# Поиск заблокированных потоков обработчиков
grep -A 3 -B 1 "kafka-request-handler" /tmp/kafka_threads.tdump | grep -E "State:|waiting to lock|BLOCKED"
# → java.lang.Thread.State: WAITING (parking)
# → java.lang.Thread.State: BLOCKED (on java.io.FileDescriptor)
```

#### План устранения и ликвидация Thread Starvation

1. **Тюнинг пулов потоков Kafka (`server.properties`):**
   - Увеличить пул обработчиков: `num.io.threads = cores * 2` (например, 32 на 16-ядерном сервере при наличии быстрых NVMe).
   - Увеличить пул сетевых процессоров: `num.network.threads = cores` (например, 16).
   - Увеличить глубину очереди запросов: `queued.max.requests = 10000` (дефолт 500, предотвращает отказ при кратковременных всплесках).
2. **Оптимизация сброса страниц ядра Linux (`/etc/sysctl.d/99-kafka-io.conf`):**
   Предотвратить синхронную блокировку записи ядром при накоплении грязных страниц:

```bash
cat << 'EOF' > /etc/sysctl.d/99-kafka-io.conf
vm.dirty_background_ratio = 5
vm.dirty_ratio = 10
vm.dirty_expire_centisecs = 3000
vm.dirty_writeback_centisecs = 500
EOF
sysctl -p /etc/sysctl.d/99-kafka-io.conf
# → vm.dirty_background_ratio = 5
# → vm.dirty_ratio = 10
# → vm.dirty_expire_centisecs = 3000
# → vm.dirty_writeback_centisecs = 500
```

---

### Сценарий 4: Аварийное падение брокера и исчерпание памяти (OOM Killer / JVM Heap)

#### Симптомы и триггеры

- Процесс Kafka внезапно исчезает из списка процессов (`systemctl status kafka` переходит в `failed`).
- В системном логе ядра `dmesg`: `Out of memory: Killed process <pid> (java)`.
- Либо в `server.log` фиксируется `java.lang.OutOfMemoryError: Java heap space` / `Direct buffer memory`.

#### Decision Tree: Локализация аварийного завершения

```
Падение брокера (Crash / Terminated)
      │
      ├── 1. Проверить код завершения и системный журнал ядра:
      │       ├── dmesg -T | grep -E -i "oom|killed process"
      │       │     └── Найден OOM Killer → Linux убил JVM из-за дефицита физической RAM / cgroups
      │       └── dmesg чист → проверить логи Kafka и crash dumps (hs_err_pid*.log)
      │
      ├── 2. Если OOM Killer:
      │       ├── Проверить соотношение: JVM Heap (-Xmx) + Direct Memory + OS PageCache
      │       │     └── Ошибка: Heap выделен слишком большой (> 70% RAM), вытеснил ядро и системные сервисы
      │       └── Проверить cgroup limits (в Docker/VM): утилизация памяти контейнера уперлась в лимит
      │
      └── 3. Если JVM OutOfMemoryError в server.log:
              ├── OutOfMemoryError: Java heap space
              │     └── Утечка памяти в буферах, десериализации или декомпрессии → анализ Heap Dump
              ├── OutOfMemoryError: Direct buffer memory
              │     └── Исчерпание off-heap буферов (max.direct.memory) при сокетах/zero-copy
              └── OutOfMemoryError: Metaspace
                    └── Недостаточно MaxMetaspaceSize при динамической загрузке классов
```

#### Пошаговая диагностика

1. **Проверка вмешательства Linux OOM Killer:**

```bash
dmesg -T | grep -i -E "oom-killer|killed process" | tail -n 2
# → [Sun Oct 12 14:22:01 2026] Out of memory: Killed process 38412 (java) total-vm:48210340kB, anon-rss:28312012kB, file-rss:0kB, shmem-rss:0kB
```

2. **Проверка cgroup ограничений (для VM и контейнеризированных окружений):**

```bash
cat /sys/fs/cgroup/memory.current 2>/dev/null || cat /sys/fs/cgroup/memory/memory.usage_in_bytes
# → 33554432000
cat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes
# → 34359738368
# → (Память подошла вплотную к лимиту cgroup 32 GiB)
```

3. **Снятие гистограммы классов работающего или восстанавливающегося брокера:**

```bash
KAFKA_PID=$(pgrep -f "kafka.Kafka")
jcmd ${KAFKA_PID} GC.class_histogram | head -n 15
# →  num     #instances         #bytes  class name (module)
# → -------------------------------------------------------
# →    1:       4120194      428500176  [B (java.base@21.0.4)
# →    2:       1240120       99209600  java.util.concurrent.ConcurrentHashMap$Node (java.base@21.0.4)
# →    3:        520114       41609120  org.apache.kafka.common.record.DefaultRecord
```

4. **Анализ Heap Dump (сохраненного по флагу `-XX:+HeapDumpOnOutOfMemoryError`):**
   *Примечание:* Утилита `jhat` удалена начиная с JDK 9. Для профессионального анализа на сервере применяется CLI-режим Eclipse Memory Analyzer (MAT):

```bash
# Генерация отчета через headless Eclipse MAT ParseHeapDump
./ParseHeapDump.sh /var/log/kafka/kafka_oom_pid38412.hprof org.eclipse.mat.api:suspects
# → Creates: kafka_oom_pid38412_Leak_Suspects.zip
unzip -p kafka_oom_pid38412_Leak_Suspects.zip index.html | grep -A 5 "Problem Suspect"
```

#### План устранения и ликвидация OOM

1. **Корректный сайзинг JVM Heap (SRE Standard для Kafka):**
   - **Никогда** не выделять Kafka брокеру 32+ ГБ кучи! Это отключает сжатые указатели (`Compressed Oops`) и провоцирует гигантские паузы G1GC.
   - Оптимальный размер кучи для прод-брокера Kafka: **от 6 ГБ до 12 ГБ**.
   - Вся остальная физическая память сервера (64–256 ГБ) должна принадлежать ядру Linux под **PageCache**, который обслуживает операции zero-copy (`sendfile`).
2. **Настройка флагов JVM в `/etc/default/kafka` или `kafka-env.sh`:**

```bash
export KAFKA_HEAP_OPTS="-Xms8g -Xmx8g -XX:MetaspaceSize=128m -XX:MaxMetaspaceSize=512m -XX:MaxDirectMemorySize=8g"
export KAFKA_JVM_PERFORMANCE_OPTS="-server -XX:+UseG1GC -XX:MaxGCPauseMillis=20 -XX:InitiatingHeapOccupancyPercent=45 -XX:G1ReservePercent=15 -XX:MinMetaspaceFreeRatio=50 -XX:+ExplicitGCInvokesConcurrent -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/var/log/kafka/"
```

3. **Защита процесса от OOM Killer через oom_score_adj:**

```bash
# Исключение Kafka из первоочередных жертв OOM Killer в systemd unit
# /etc/systemd/system/kafka.service.d/override.conf
[Service]
OOMScoreAdjust=-900
```

---

### Сценарий 5: Сбои кворума метаданных KRaft и рассинхронизация контроллеров

#### Симптомы и триггеры

- Алерт: Отсутствует активный лидер метаданных (`kafka.server:type=raft-leader-election-metrics,name=leader-id = -1`).
- Клиенты и административные утилиты получают ошибки `NotControllerException`, `LeaderRecoveryException` или `TimeoutException` при попытке создать топик или изменить квоты.
- В логах брокеров: `[RaftManager id=1] Connection to node 2 (kafka-controller-2:9093) failed. Network unreachable`.

#### Decision Tree: Восстановление KRaft Quorum

```
Сбой кворума метаданных KRaft
      │
      ├── 1. Проверить статус кворума: kafka-metadata-quorum.sh describe --status
      │       ├── Ошибка: Не удалось подключиться к брокерам
      │       │     └── Проверить статус сетевого порта 9093 и процессы контроллеров
      │       └── Статус получен, но LeaderId отсутствует (-1)
      │             └── Нарушен кворум (Raft Quorum Lost: доступно < (N/2 + 1) контроллеров)
      │
      ├── 2. Оценка доступности узлов-voters (CurrentVoters):
      │       ├── Сетевая изоляция (Network Split) между датацентрами/стойками
      │       ├── Физическое падение большинства нод контроллеров (например, 2 из 3)
      │       └── Рассинхронизация журнала метаданных (HighWatermark / LEO)
      │
      └── 3. Восстановление:
              ├── Если большинство живо: восстановить сетевую связность / запустить упавшие ноды
              └── Если большинство контроллеров утеряно безвозвратно:
                    └── Аварийная переконфигурация кворума из уцелевшего узла метаданных
```

#### Пошаговая диагностика

1. **Проверка статуса кворума Raft:**

```bash
kafka-metadata-quorum.sh --bootstrap-server 10.0.10.11:9092 describe --status
# → ClusterId:              AbC3dEfGhIjKlMnOpQrStU
# → LeaderId:               -1
# → LeaderEpoch:            12
# → HighWatermark:          48102
# → MaxFollowerLag:         -1
# → MaxFollowerLagTimeMs:   -1
# → CurrentVoters:          [1, 2, 3]
# → CurrentObservers:       [4, 5, 6]
# → (Лидер отсутствует, кворум из 3 контроллеров парализован)
```

2. **Детальная инспекция репликации журнала метаданных:**

```bash
kafka-metadata-quorum.sh --bootstrap-server 10.0.10.11:9092 describe --replication
# → NodeId  LogEndOffset  Lag  LastFetchTimestamp  LastCaughtUpTimestamp  Status
# → 1       48102         0    1728741800120       1728741800120          Candidate
# → 2       -1            -1   -1                  -1                     Unreachable
# → 3       -1            -1   -1                  -1                     Unreachable
# → (Узлы 2 и 3 недоступны, узел 1 находится в бесконечном раунде выборов)
```

3. **Проверка сетевой доступности порта кворума 9093 между контроллерами:**

```bash
# С узла 1 проверяем доступность узлов 2 и 3
nc -zvw2 10.0.10.12 9093
# → nc: connect to 10.0.10.12 port 9093 (tcp) failed: Connection refused
nc -zvw2 10.0.10.13 9093
# → nc: connect to 10.0.10.13 port 9093 (tcp) failed: No route to host
```

#### План устранения и восстановление кворума

1. **Штатное восстановление большинства:**
   - Поднять службы Kafka на узлах 2 и 3: `systemctl start kafka`.
   - Устранить блокировки межсетевого экрана (iptables/nftables) для порта `controller.listener.names` (порт `9093`).
   - Как только минимум 2 узла из 3 смогут обмениваться пакетами, кворум автоматически выберет лидера и обновит `LeaderEpoch`.
2. **Аварийный вывод мертвого контроллера (если нода уничтожена):**
   Если один контроллер из трех физически уничтожен и не вернется, исключить его из кворума для предотвращения задержек:

```bash
kafka-metadata-quorum.sh --bootstrap-server 10.0.10.11:9092 \
  remove-controller --controller-id 3 --controller-directory-id AbCdEf123456
# → Successfully removed controller with id 3.
```

---

### Сценарий 6: Переполнение дисковой подсистемы (Disk Full) и I/O Bottlenecks

#### Симптомы и триггеры

- Алерт: `DiskSpaceFree < 10%` или файловая система `/var/lib/kafka/data` заполнена на 100%.
- Брокер переводит журнал в read-only и падает с `KafkaStorageException: Disk is full` или `IOException: No space left on device`.
- Репликация останавливается, топики переходят в статус URP.

#### Decision Tree: Экстренная ликвидация переполнения диска

```
Переполнение диска (Disk Full)
      │
      ├── 1. Проверить свободное место и точку монтирования: df -hT /var/lib/kafka/data
      │       ├── Место закончилось на 100% → брокер может аварийно остановиться
      │       └── Место на исходе (90-95%) → есть время на штатную очистку
      │
      ├── 2. Найти топик-виновник аномального роста:
      │       └── du -h --max-depth=1 /var/lib/kafka/data | sort -hr | head -n 10
      │
      ├── 3. Выбор безопасного метода освобождения места:
      │       ├── Метод А (Штатный, динамический): Уменьшить retention.ms / retention.bytes для топика
      │       ├── Метод Б (Принудительный ролл сегментов): Уменьшить segment.ms для сброса активного сегмента
      │       └── КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО: Удалять активные файлы .log и .index через 'rm -f' на живом брокере!
      │
      └── 4. После очистки:
              └── Проверить работу Log Cleaner: log.cleaner.enable = true
```

#### Пошаговая диагностика

1. **Поиск самых объемных разделов на диске:**

```bash
du -h --max-depth=1 /var/lib/kafka/data | sort -hr | head -n 6
# → 1.8T   /var/lib/kafka/data
# → 1.2T   /var/lib/kafka/data/raw-telemetry-0
# → 320G   /var/lib/kafka/data/raw-telemetry-1
# → 110G   /var/lib/kafka/data/application-logs-2
```

2. **Проверка текущей политики retention для проблемного топика:**

```bash
kafka-configs.sh --bootstrap-server 10.0.10.11:9092 \
  --entity-type topics --entity-name raw-telemetry --describe
# → Dynamic configs for topic raw-telemetry are:
# →   retention.ms=604800000 (7 дней)
# →   retention.bytes=-1 (без лимита по объему)
```

#### План устранения и безопасная очистка

1. **Экстренное динамическое урезание Retention без перезапуска брокера:**
   Установить срок хранения сообщений топика, например, в 6 часов (21600000 мс) или ограничить объем партиции до 50 ГБ:

```bash
kafka-configs.sh --bootstrap-server 10.0.10.11:9092 --alter \
  --entity-type topics --entity-name raw-telemetry \
  --add-config retention.ms=21600000,retention.bytes=53687091200
# → Completed updating config for topic raw-telemetry.
```

2. **Принудительная активация ротации сегментов (Segment Rolling):**
   Kafka удаляет только закрытые (неактивные) сегменты лога. Если текущий активный сегмент весит гигабайты и еще не закрылся, принудительно уменьшить `segment.ms`:

```bash
kafka-configs.sh --bootstrap-server 10.0.10.11:9092 --alter \
  --entity-type topics --entity-name raw-telemetry \
  --add-config segment.ms=3600000
# → Completed updating config for topic raw-telemetry.
```

3. **Мониторинг процесса удаления старых сегментов:**

```bash
grep -E "Deleting segment|Found deletable segments" /var/log/kafka/server.log | tail -n 5
# → [2026-10-12 14:35:10,812] INFO [Log partition=raw-telemetry-0] Deleting segment LogSegment(baseOffset=0, size=1073741824) due to retention time 21600000ms breach
```

4. **Действия при аварийном падении брокера из-за 100% Full Disk:**
   Если брокер не запускается (`No space left on device`):
   - **НЕ удалять** активные файлы `.log` (файлы с максимальным offset)!
   - Найти **самый старый** сегмент (например, `00000000000000000000.log` и соответствующие ему `.index`, `.timeindex`) в переполненной партиции и переместить/удалить его вручную.
   - Запустить брокер: `systemctl start kafka`. Он восстановит индекс и выполнит штатную очистку остальных сегментов.

---

### Сценарий 7: "Отравленные сообщения" (Poison Pill) и повреждение сегментов лога

#### Симптомы и триггеры

- Консьюмер бесконечно падает при чтении определенного оффсета с `RecordDeserializationException` или `ClassCastException`.
- Брокер регистрирует `CorruptRecordException: Record size is less than minimum record overhead` или ошибку проверки контрольной суммы CRC32 после сбоя питания сервера.

#### Decision Tree: Изоляция повреждений и Poison Pill

```
Сбой чтения / Повреждение лога
      │
      ├── 1. Ошибка на стороне консьюмера (Poison Pill):
      │       ├── Лог консьюмера: Deserialization error на партиции P и оффсете O
      │       ├── Шаг 1: Проинспектировать полезную нагрузку через kafka-console-consumer / dump-log
      │       ├── Решение А: Dead Letter Queue (DLQ) на уровне приложения (рекомендуется)
      │       └── Решение Б: Принудительный сдвиг оффсета группы на (O + 1) через kafka-consumer-groups.sh
      │
      └── 2. Повреждение сегмента на брокере (Log Corruption):
              ├── Лог брокера: CorruptRecordException / Invalid CRC32
              ├── Шаг 1: Верификация индекса: kafka-dump-log.sh --verify-index-only
              ├── Решение А (Поврежден только индекс): Удалить .index и .timeindex, перезапустить брокер (авторебилд)
              └── Решение Б (Поврежден сам .log): Очистить поврежденный лидер и позволить синхронизироваться из ISR
```

#### Пошаговая диагностика

1. **Низкоуровневая проверка целостности сегментов и индексов лога:**

```bash
kafka-dump-log.sh \
  --files /var/lib/kafka/data/orders.events-0/00000000000000500000.log \
  --verify-index-only
# → Verifying index /var/lib/kafka/data/orders.events-0/00000000000000500000.index
# → Mismatch in offset between index and log: index points to 500210, log points to 500208
# → (Обнаружено расхождение смещения в индексе из-за аварийного отключения питания)
```

2. **Дамп проблемного сообщения "отравленной таблетки":**

```bash
kafka-console-consumer.sh --bootstrap-server 10.0.10.11:9092 \
  --topic orders.events --partition 0 --offset 500208 --max-messages 1 --property print.timestamp=true
# → CreateTime:1728742510000   {"order_id": null, "payload": "MALFORMED_NON_JSON_BINARY_DATA\x00\x01"}
```

#### План устранения

1. **Автоматическое восстановление поврежденных индексов (.index и .timeindex):**
   При повреждении индексных файлов брокер Kafka способен пересоздать их с нуля на основе бинарного `.log` файла:

```bash
# Останавливаем брокер
systemctl stop kafka

# Удаляем поврежденные файлы индексов конкретного сегмента
rm -f /var/lib/kafka/data/orders.events-0/00000000000000500000.index
rm -f /var/lib/kafka/data/orders.events-0/00000000000000500000.timeindex

# Запускаем брокер — Kafka автоматически перечитает .log и перестроит индексы
systemctl start kafka

# Проверяем в логе завершение ребилда
grep "Recovering log" /var/log/kafka/server.log
# → [Log partition=orders.events-0] Recovering segment 500000 to rebuild index files
```

2. **Экстренный пропуск отравленного сообщения (Poison Pill Skip):**
   Если приложение консьюмера зависло на оффсете `500208` и не имеет встроенного DLQ:

```bash
# 1. Остановить процесс/поды консьюмера, чтобы перевести группу в состояние Empty
# 2. Выполнить точечный сдвиг оффсета вперед на 1 позицию:
kafka-consumer-groups.sh --bootstrap-server 10.0.10.11:9092 \
  --group orders-worker \
  --topic orders.events:0 \
  --reset-offsets --to-offset 500209 \
  --execute
# → GROUP         TOPIC          PARTITION  NEW-OFFSET
# → orders-worker orders.events  0          500209

# 3. Запустить процесс консьюмера — обработка возобновится со следующего сообщения
```

---

## Операции и команды оперативной диагностики

Сводная таблица утилит командной строки для решения инцидентов:

| Утилита / Команда | Ключевые параметры | Назначение при инциденте | Пример вызова |
|---|---|---|---|
| `kafka-metadata-quorum.sh` | `describe --status`, `describe --replication` | Диагностика кворума метаданных KRaft, выявление изоляции контроллеров | `kafka-metadata-quorum.sh --bootstrap-server :9092 describe --status` |
| `kafka-topics.sh` | `--under-replicated-partitions`, `--unavailable-partitions` | Быстрый поиск деградировавших партиций и партиций без лидеров | `kafka-topics.sh --bootstrap-server :9092 --describe --under-replicated-partitions` |
| `kafka-consumer-groups.sh` | `--describe --members --verbose`, `--state` | Выявление зависших консьюмеров, лавин ребалансировок и размера лага | `kafka-consumer-groups.sh --bootstrap-server :9092 --describe --group app-grp` |
| `kafka-dump-log.sh` | `--files <path>`, `--print-data-log`, `--verify-index-only` | Низкоуровневый аудит сегментов на диске, поиск Hot Key и повреждений | `kafka-dump-log.sh --files /path/000.log --verify-index-only` |
| `kafka-configs.sh` | `--alter --entity-type topics`, `--add-config retention.ms` | Экстренное изменение retention и троттлинга репликации на лету | `kafka-configs.sh --bootstrap-server :9092 --alter --entity-type topics --entity-name t1 --add-config retention.ms=3600000` |
| `jcmd <pid>` | `Thread.print`, `GC.class_histogram`, `GC.heap_dump` | Диагностика дедлоков потоков и утечек памяти JVM без остановки брокера | `jcmd $(pgrep -f kafka) Thread.print > /tmp/threads.txt` |
| `iostat -xz 1` | `-xz 1 5` | Анализ задержек дисковых очередей, `%util`, `r_await`, `w_await` | `iostat -xz 1 5` |
| `ss -ti` | `'sport = :9092'` | Анализ насыщения TCP-сокетов, окна передачи и процента ретрансмиссий | `ss -ti 'sport = :9092'` |

---

## Типовые ошибки и матрица решений

| Исключение / Симптом | Корневая причина | Диагностика | Решение дежурного инженера |
|---|---|---|---|
| `NotLeaderOrFollowerException` | Запрос клиента направлен на брокер, который перестал быть лидером (произошла смена лидера). | Проверить смену лидеров в `server.log`, стабильность контроллера. | Нормально при плановом failover. На клиентах обновить метаданные (`metadata.max.age.ms`). |
| `NotEnoughReplicasException` | Число активных реплик в ISR упало ниже `min.insync.replicas` при `acks=all`. | Проверить URP через `kafka-topics.sh`, диски и сеть на отстающих follower. | Восстановить выпавшие ноды из ISR. Не снижать `min.insync.replicas` без согласования риска потери данных! |
| `CorruptRecordException` | Несовпадение контрольной суммы CRC32, частичная запись из-за сбоя питания. | `kafka-dump-log.sh --verify-index-only`. | Удалить поврежденные файлы `.index`/`.timeindex` для авторебилда; синхронизировать партицию с лидера. |
| `RecordTooLargeException` | Размер пачки превышает `max.message.bytes` на брокере или топике. | Проверить размер сообщений в продюсере, конфигурацию топика. | Увеличить `max.message.bytes` на топике и `max.partition.fetch.bytes` на консьюмерах либо включить сжатие (`compression.type=zstd`). |
| `CommitFailedException` | Время обработки сообщений превысило `max.poll.interval.ms`, консьюмер исключен из группы. | Логи консьюмеров, мониторинг времени обработки одного батча. | Уменьшить `max.poll.records`, оптимизировать бизнес-логику либо увеличить `max.poll.interval.ms`. |
| `KafkaStorageException` | Ошибка ввода-вывода диска: `Read-only file system`, битые сектора диска или 100% Full Disk. | `dmesg`, `df -h /var/lib/kafka/data`, SMART диска. | Освободить место (retention); при аппаратной деградации диска вывести брокер и мигрировать партиции. |
| `FencedLeaderEpochException` | Попытка продюсера или реплики обратиться с устаревшим epoch (старый лидер после сетевой изоляции). | Логи брокера: `LeaderEpoch` mismatch. | Продюсер автоматически обновит метаданные. Проверить стабильность сети кластера. |

---

## Рекомендации и превентивные меры (Best Practices)

### SRE Golden Rules при ликвидации аварий в Kafka

1. **Никогда не перезапускать все брокеры одновременно:**
   - Перезапуск брокеров выполняется строго последовательно (Rolling Restart).
   - Перед перезапуском следующего узла **обязательно** дождаться, пока `UnderReplicatedPartitions` вернется в `0`.
2. **Никогда не включать вслепую `unclean.leader.election.enable=true`:**
   - Включение нечистых выборов позволяет несинхронной реплике стать лидером, что приводит к **безвозвратной потере данных** и расхождению оффсетов. Допустимо исключительно при катастрофической потере всех ISR как осознанное решение пожертвовать данными ради доступности.
3. **Никогда не удалять активные `.log` файлы вручную через `rm`:**
   - Удаление открытого дескриптора на работающем брокере переводит партицию в состояние `Offline` и вызывает фатальный `KafkaStorageException`.
4. **Не раздувать JVM Heap:**
   - Размер кучи не должен превышать 12 ГБ. Память ОС PageCache критически важна для высокой производительности и отсутствия задержек I/O.
5. **Всегда резервировать место на диске:**
   - Настраивать алертинг на дисковое пространство на уровнях 75% (Warning) и 85% (Critical). Оставлять минимум 15% запаса под аварийные всплески трафика и сжатие логов.

### Чек-лист дежурного инженера при инциденте

- [ ] 1. Зафиксировать состояние кворума метаданных KRaft (`kafka-metadata-quorum.sh describe --status`).
- [ ] 2. Проверить наличие `OfflinePartitionsCount` (критический приоритет P1).
- [ ] 3. Проверить `UnderReplicatedPartitions` и локализовать отстающие брокеры.
- [ ] 4. Проверить статус дисковой подсистемы (`df -h`, `iostat -xz 1`).
- [ ] 5. Проверить метрику простоя пула обработчиков `RequestHandlerAvgIdlePercent`.
- [ ] 6. Проверить логи брокера на наличие OOM, аппаратных сбоев дисков или kernel errors (`dmesg -T`).
- [ ] 7. Проверить consumer lag ключевых бизнес-групп.

### Регламент безопасного Rolling Restart брокеров

Для планового обновления конфигураций или перезапуска узлов кластера:

```bash
# Шаг 1: Проверка отсутствия недореплицированных партиций
kafka-topics.sh --bootstrap-server 10.0.10.11:9092 --describe --under-replicated-partitions
# (Вывод должен быть абсолютно пустым)

# Шаг 2: Контролируемая остановка брокера (Controlled Shutdown)
systemctl stop kafka

# Шаг 3: Проверка успешного переноса лидерства партиций на оставшиеся узлы в server.log
grep "Controlled shutdown succeeded" /var/log/kafka/server.log

# Шаг 4: Запуск брокера
systemctl start kafka

# Шаг 5: Ожидание полного восстановления ISR (циклический опрос)
while true; do
  URP=$(kafka-topics.sh --bootstrap-server 10.0.10.11:9092 --describe --under-replicated-partitions | wc -l)
  if [ "$URP" -eq 0 ]; then
    echo "Брокер успешно вошел в ISR, URP = 0. Можно переходить к следующему узлу."
    break
  fi
  echo "Ожидание синхронизации реплик... Текущих URP строк: $URP"
  sleep 5
done
```

---

## Дополнительная информация

### Взаимосвязь с архитектурными разделами базы знаний

- **[kafka_for_monitoring.md](./kafka_for_monitoring.md)** — архитектура JMX-метрик, алерты Prometheus и дашборды Grafana для превентивного мониторинга.
- **[kafka_cli_tools.md](./kafka_cli_tools.md)** — полное руководство по утилитам командной строки Apache Kafka и KRaft.
- **[kafka_isr_replication.md](./kafka_isr_replication.md)** — глубокая теория механизма репликации ISR, High Watermark и предотвращения потерь данных.
- **[kafka_broker_thread_model.md](./kafka_broker_thread_model.md)** — внутренняя модель потоков брокера, сетевой конвейер и оптимизация очередей.
- **[kafka_jvm_gc_tuning.md](./kafka_jvm_gc_tuning.md)** — тюнинг сборщика мусора G1GC, предотвращение пауз Stop-The-World и сайзинг памяти.
- **[kafka_os_tuning.md](./kafka_os_tuning.md)** — низкоуровневая оптимизация параметров ядра Linux (sysctl, PageCache, дисковый планировщик).
- **[kafka_capacity_dr.md](./kafka_capacity_dr.md)** — сайзинг кластеров, аварийное восстановление (DR) и репликация между ЦОД через MirrorMaker 2.
- **[partitioning_and_balancing.md](./partitioning_and_balancing.md)** — стратегии партиционирования, ликвидация перекоса ключей и ребалансировка.
- **[delivery_guarantees.md](./delivery_guarantees.md)** — гарантии доставки сообщений (at-least-once, exactly-once) и idempotent producer.
