# Thread Model брокера Apache Kafka

**Актуально для:** Apache Kafka 3.8 / 3.9 / 4.0 (KRaft)

**Thread Model брокера** — это архитектура многопоточной обработки сетевых запросов, репликации и фоновых операций ввода-вывода в Apache Kafka. Модель построена на базе шаблона Reactor (Java NIO) и пулов асинхронных воркеров. Корректный расчет и тюнинг пулов потоков предотвращает деградацию пропускной способности (throughput), блокировки сетевых очередей и всплески задержек (latency spikes) на уровне операционной системы и JVM.

---

## Определения

- **Acceptor Thread:** Поток сетевого уровня, слушающий порт входящего сокета (endpoint/listener) и регистрирующий входящие TCP-соединения, передавая сокет-каналы потокам-процессорам по алгоритму Round-Robin.
- **Network Thread (Processor):** Сетевой поток-процессор (пул `num.network.threads`), выполняющий неблокирующее чтение входящих байтов из сокета, десериализацию заголовков/кадров Kafka-протокола, упаковку запроса в `RequestChannel` и обратную запись готовых ответов клиентам.
- **Request Handler Thread (IO Thread):** Поток пула `KafkaRequestHandlerPool` (настраивается параметром `num.io.threads`), извлекающий запросы из общей очереди `RequestQueue`, исполняющий бизнес-логику (чтение/запись в сегменты логов через Page Cache, изменение метаданных) и отправляющий ответ в очередь ответа или в Purgatory.
- **RequestQueue:** Общая потокобезопасная блокирующая очередь (`ArrayBlockingQueue`), куда Network Threads помещают входящие запросы. Размер ограничен параметром `queued.max.requests`.
- **ResponseQueue:** Индивидуальная очередь ответов, привязанная к конкретному сетевому потоку Processor. По завершении обработки запроса IO Thread возвращает результат в очередь того процессора, который принял данный сокет.
- **Purgatory:** Внутрипамяточная структура брокера для асинхронного удержания отложенных операций (`DelayedProduce`, `DelayedFetch`, `DelayedHeartbeat`), ожидающих наступления внешнего условия или истечения таймаута без блокировки пула `num.io.threads`.
- **Hierarchical Timing Wheels:** Алгоритмическая структура данных (многоуровневое колесо таймеров), используемая Purgatory для регистрации и отслеживания истечения таймаутов операций с вычислительной сложностью $O(1)$.
- **Replica Fetcher Thread:** Поток на брокере-follower (`num.replica.fetchers`), инициирующий запросы `FetchRequest` к лидер-репликам для копирования записей и продвижения смещения репликации (Log End Offset).
- **Log Cleaner Thread:** Фоновый поток компакции (`log.cleaner.threads`), выполняющий слияние и удаление устаревших записей в топиках с политикой `cleanup.policy=compact`.
- **Recovery & Flush Threads:** Потоки (`num.recovery.threads.per.data.dir`), используемые при старте брокера для валидации индексов и восстановления сегментов логов, а также при остановке брокера для сброса данных на диск.
- **KRaft Metadata Threads:** Внутренние потоки протокола консенсуса Raft и загрузчика метаданных брокера (`metadata-loader`, `raft-io-thread`, `kafka-raft-network-thread`), заменяющие устаревшие потоки ZooKeeper контроллера.
- **Thread Starvation (голодание потоков):** Состояние перегрузки пула, при котором входящие задачи накапливаются в очередях быстрее, чем потоки успевают их обработать, приводящее к падению метрик простоя (Idle Percent) ниже критического уровня.

---

## Основные концепции и архитектура потоков

### Архитектура сетевого конвейера (Reactor Pattern)

Сетевая подсистема Kafka (`SocketServer`) разделяет сетевой I/O и бизнес-логику обработки данных:

```
                  ┌─────────────────────────────────────────────────────────────┐
                  │                 Linux Kernel Socket Buffer                  │
                  └──────────────────────────────┬──────────────────────────────┘
                                                 │ TCP Connect (SYN)
                                                 ▼
                  ┌─────────────────────────────────────────────────────────────┐
                  │                       Acceptor Thread                       │
                  │              (1 поток на каждый listener/порт)              │
                  └──────────────────────────────┬──────────────────────────────┘
                                                 │ Round-Robin регистрация каналов
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│ Network Processors Pool (num.network.threads)                                               │
│                                                                                             │
│ ┌─────────────────────────┐   ┌─────────────────────────┐   ┌─────────────────────────┐     │
│ │   Network Processor 0   │   │   Network Processor 1   │   │   Network Processor N   │     │
│ │  (Read TCP, SSL/TLS,    │   │  (Read TCP, SSL/TLS,    │   │  (Read TCP, SSL/TLS,    │     │
│ │   парсинг Frame)        │   │   парсинг Frame)        │   │   парсинг Frame)        │     │
│ └────────────┬────────────┘   └────────────┬────────────┘   └────────────┬────────────┘     │
└──────────────┼─────────────────────────────┼─────────────────────────────┼──────────────────┘
               │                             │                             │
               └───────────────────────┬─────┴─────────────────────────────┘
                                       │ Request (включая ссылку на Processor ID)
                                       ▼
                  ┌─────────────────────────────────────────────────────────────┐
                  │             RequestQueue (queued.max.requests)              │
                  └────────────────────────────┬────────────────────────────────┘
                                               │ Dequeue
                                               ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│ Request Handler Pool (num.io.threads)                                                       │
│                                                                                             │
│ ┌──────────────────────┐  ┌──────────────────────┐  ┌─────────────────────────────────────┐ │
│ │  Request Handler 0   │  │  Request Handler 1   │  │         Request Handler M           │ │
│ │ (Запись/чтение логов │  │ (Запись/чтение логов │  │        (Запись/чтение логов         │ │
│ │   в Page Cache)      │  │   в Page Cache)      │  │          в Page Cache)              │ │
│ └──────────┬───────────┘  └──────────┬───────────┘  └──────────────────┬──────────────────┘ │
└────────────┼─────────────────────────┼─────────────────────────────────┼────────────────────┘
             │                         │                                 │
             ├─────────────────────────┴─────────────────────────────────┤
             │                                                           │
             ▼ acks=0,1 (готов)                                          ▼ acks=all / min.bytes
┌─────────────────────────────┐                         ┌─────────────────────────────────────┐
│    Direct Response Path     │                         │        Purgatory (In-Memory)        │
│                             │                         │   - DelayedProduce (ждёт ISR)       │
│                             │                         │   - DelayedFetch (ждёт min.bytes)   │
└────────────┬────────────────┘                         └──────────────────┬──────────────────┘
             │                                                             │ Условие выполнено
             │                                                             ▼
             └─────────────────────────┬───────────────────────────────────┘
                                       │ Response
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│ Response Queues (по 1 локальной очереди на каждый Network Processor)                        │
│                                                                                             │
│  ┌───────────────────────┐    ┌───────────────────────┐    ┌─────────────────────────────┐  │
│  │  Response Queue 0     │    │  Response Queue 1     │    │     Response Queue N        │  │
│  └───────────┬───────────┘    └───────────┬───────────┘    └──────────────┬──────────────┘  │
└──────────────┼────────────────────────────┼───────────────────────────────┼─────────────────┘
               │                            │                               │
               ▼                            ▼                               ▼
     Processor 0 (Send TCP)       Processor 1 (Send TCP)          Processor N (Send TCP)
```

### Анатомия времени обработки запроса (SRE Request Lifecycle)

Общее время обработки клиентского запроса (`TotalTimeMs`) складывается из дискретных фаз. Измерение этих метрик позволяет точно локализовать узкое место:

$$\text{TotalTimeMs} = \text{RequestQueueTimeMs} + \text{LocalTimeMs} + \text{RemoteTimeMs} + \text{ThrottleTimeMs} + \text{ResponseQueueTimeMs} + \text{ResponseSendTimeMs}$$

| Фаза метрики | Ответственный пул / компонент | Физический смысл | Нормальное состояние | Причина деградации |
| :--- | :--- | :--- | :--- | :--- |
| **RequestQueueTimeMs** | `RequestQueue` | Время ожидания в очереди перед освобождением IO-потока | < 2–5 ms | Нехватка `num.io.threads`, перегрузка CPU ядрами |
| **LocalTimeMs** | `num.io.threads` | Время непосредственного выполнения запроса внутри JVM/ОС | < 10–15 ms | Задержки Page Cache (dirty pages flush), конкуренция за блокировки |
| **RemoteTimeMs** | `Purgatory` | Время ожидания внешних условий (репликация на ISR, таймаут consumer fetch) | Зависит от клиента / $0$ при `acks=1` | Медленные брокеры-реплики, сетевые задержки между узлами кластера |
| **ThrottleTimeMs** | Quota Manager | Задержка, наложенная брокером из-за превышения клиентских квот | $0$ ms | Превышение лимитов байт/сек или времени CPU клиентом |
| **ResponseQueueTimeMs**| `ResponseQueue` | Время ожидания готового ответа перед отправкой сетевым процессором | < 2 ms | Перегрузка пула `num.network.threads` |
| **ResponseSendTimeMs** | `num.network.threads` | Время передачи байтов в сокет операционной системы | < 5–10 ms | Заполнение сетевого буфера TCP, медленный клиент, потери пакетов |

### Сводная таблица пулов потоков брокера

| Название потока в JVM | Параметр конфигурации | Значение по умолчанию | Рекомендуемое для Production | Зона ответственности |
| :--- | :--- | :--- | :--- | :--- |
| `kafka-socket-acceptor-<Listener>-<Port>` | 1 на listener | Фиксировано (1) | 1 на listener | Прием входящих TCP-соединений, TLS handshake delegation |
| `kafka-network-thread-<Listener>-<ProcessorId>` | `num.network.threads` | 3 | $cores / 2$ (от 4 до 16) | Чтение/запись сокетов, парсинг заголовков, SSL termination |
| `kafka-request-handler-<Id>` | `num.io.threads` | 8 | $cores \times (1 \dots 2)$ (от 8 до 32) | Обработка Produce/Fetch, работа с файловой системой логов |
| `ReplicaFetcherThread-<Id>-<SourceBrokerId>` | `num.replica.fetchers` | 1 | 2–4 | Выкачивание записей с лидер-брокеров для репликации ISR |
| `kafka-log-cleaner-thread-<Id>` | `log.cleaner.threads` | 1 | 2–4 (по числу дисков) | Дедупликация и компакция сегментов compact-топиков |
| `log-recovery-thread-<DirId>-<ThreadId>` | `num.recovery.threads.per.data.dir` | 1 | 2–4 на точку монтирования | Параллельная проверка логов и индексов при старте/останове |
| `kafka-scheduler-<Id>` | `background.threads` | 10 | 10–20 | Фоновые служебные задачи (ротация логов, очистка по retention) |
| `metadata-loader` | Внутренний KRaft | 1 | 1 | Чтение коммитов метаданных из Raft-кворума и обновление кэша |
| `raft-io-thread` / `kafka-raft-network-thread` | Внутренний KRaft | 1 | 1 | Обслуживание репликации системного топика `@metadata` |

### Механизм Purgatory и Delayed Operations

Purgatory изолирует длительные ожидания от рабочего пула `num.io.threads`:
1. Если продюсер отправляет сообщение с `acks=all`, лидер записывает данные в локальный лог через Page Cache, после чего создает объект `DelayedProduce` со сроком жизни `request.timeout.ms`.
2. Запрос регистрируется в иерархическом колесе таймеров (`Timer`) и подписывается на событие изменения High Watermark для соответствующей партиции.
3. Поток `Request Handler` освобождается и берет следующий запрос из `RequestQueue`.
4. Когда фоновый поток `ReplicaFetcherThread` другого брокера забирает данные и подтверждает LEO, лидер продвигает High Watermark.
5. Событие пробуждает `DelayedProduce`, который формирует ответ и направляет его в `ResponseQueue` соответствующего сетевого процессора.
6. Если за время `request.timeout.ms` реплики не ответили, таймер Purgatory завершает операцию по таймауту с ошибкой `NOT_ENOUGH_REPLICAS` или `REQUEST_TIMED_OUT`.

---

## Практические сценарии и конфигурация

### Сценарий 1: Базовая производственная конфигурация (Bare-metal / VM, 16–32 vCPU, NVMe)

Конфигурация для типового брокера на выделенном Linux-сервере (16–32 ядра, 64–128 GB RAM, быстрые диски NVMe):

Файл `/etc/kafka/server.properties`:
```properties
############################# Thread Pools #############################
# Сетевые процессоры (потоки сетевого I/O на каждый endpoint)
# Для 16-32 vCPU рекомендуется выделить 8 потоков на listener
num.network.threads=8

# Потоки обработки бизнес-логики и I/O диска
# При использовании быстрых NVMe/SSD оптимально cores * 1
num.io.threads=16

# Потоки репликации партиций от других брокеров
# Предотвращает отставание ISR при интенсивной входящей записи
num.replica.fetchers=4

# Потоки фоновой очистки и компакции ключей
log.cleaner.threads=2

# Потоки восстановления сегментов логов при старте брокера (на каждую директорию)
num.recovery.threads.per.data.dir=2

############################# Queues & Buffers #############################
# Лимит очереди входящих запросов перед Request Handlers
queued.max.requests=2000

# Максимальный суммарный размер очереди запросов в байтах (защита от OOM)
# -1 означает отключение лимита по байтам, опираясь только на queued.max.requests
queued.max.request.bytes=-1

# Размеры сетевых буферов сокетов ядра ОС
socket.send.buffer.bytes=1048576
socket.receive.buffer.bytes=1048576
socket.request.max.bytes=104857600
```

### Сценарий 2: Высоконагруженный брокер с JBOD и массивным числом партиций (>2000 партиций)

На серверах с несколькими отдельными точками монтирования дисков (JBOD) и 48–64 vCPU пулы потоков настраиваются с учетом разделения дисковой очереди и сетевой нагрузки:

Файл `/etc/kafka/server.properties`:
```properties
# Выделение сетевых процессоров с запасом под TLS дешифрование
num.network.threads=16

# Потоки I/O масштабируются под количество дисков и ядер
num.io.threads=32

# Увеличение потоков репликации для параллельного выкачивания сотен партиций
num.replica.fetchers=8

# Компакция логов: по 1 потоку на каждые 2 физических диска
log.cleaner.threads=4

# Параллельное открытие и восстановление индексов при рестарте для каждого диска
num.recovery.threads.per.data.dir=4

# Увеличенный размер очереди запросов для сглаживания пиков сетевого трафика
queued.max.requests=5000

# Таймаут ожидания выполнения запроса на брокере
request.timeout.ms=30000
```

### Сценарий 3: Ускорение холодного старта и восстановления после сбоя

При нештатном завершении работы брокера (hard reset, kernel panic) Kafka выполняет валидацию сегментов и перестроение индексных файлов `.index` и `.timeindex`. При значении по умолчанию `num.recovery.threads.per.data.dir=1` восстановление сотен гигабайт данных выполняется строго последовательно, что растягивает старт сервиса на десятки минут.

Расчет параметра:
- Количество директорий хранения (`log.dirs`): $N$
- Число ядер на сервере: $C$
- Значение: $\min(4, \lfloor C / N \rfloor)$

Пример конфигурации для 4 дисков JBOD на 32-ядерном сервере:
```properties
log.dirs=/data/kafka1,/data/kafka2,/data/kafka3,/data/kafka4
num.recovery.threads.per.data.dir=4
```
В момент запуска брокер запустит $4 \times 4 = 16$ потоков `log-recovery-thread`, сокращая время простоя при аварийном старте в 3–4 раза.

### Сценарий 4: Ограничение системных ресурсов на уровне systemd (Linux Bare-Metal / On-Premise)

При развертывании Kafka на выделенных Linux-хостах необходимо обеспечить корректные системные лимиты для процессов и потоков JVM, предотвращая падение по `unable to create native thread`.

Файл `/etc/systemd/system/kafka.service.d/override.conf`:
```ini
[Service]
# Лимит на максимальное количество потоков и процессов для пользователя kafka
# Каждый поток JVM создаёт поток уровня ОС (pthread), поэтому лимит должен быть достаточным
LimitNPROC=65536

# Лимит на открытые файловые дескрипторы (сокеты + открытые сегменты логов и индексов)
LimitNOFILE=1000000

# Защита от OOM killer ядра Linux
OOMScoreAdjust=-1000

# Ограничение общего количества задач cgroups (для systemd >= 228)
TasksMax=65536
```

Применение конфигурации:
```bash
sudo systemctl daemon-reload
# → (успешное применение без вывода)

sudo systemctl restart kafka
# → (перезапуск сервиса)

systemctl show kafka.service | grep -E "LimitNPROC|LimitNOFILE|TasksMax"
# → LimitNOFILE=1000000
# → LimitNOFILESoft=1000000
# → LimitNPROC=65536
# → LimitNPROCSoft=65536
# → TasksMax=65536
```

---

## Операции и команды

### 1. Мониторинг потоков процесса Kafka на уровне Linux

Диагностика активности и загрузки CPU отдельными потоками JVM через утилиты ОС:

```bash
# Определение PID процесса брокера Kafka
pgrep -f "io.confluent|kafka.Kafka|org.apache.kafka"
# → 14205

# Просмотр наиболее нагруженных потоков Kafka в реальном времени
ps -T -p $(pgrep -f "kafka.Kafka") -o pid,spid,pcpu,comm | sort -k3 -nr | head -n 12
# →   PID    SPID  %CPU COMMAND
# → 14205   14320  14.2 kafka-request-h
# → 14205   14321  13.8 kafka-request-h
# → 14205   14322  13.5 kafka-request-h
# → 14205   14312   6.1 kafka-network-t
# → 14205   14313   5.9 kafka-network-t
# → 14205   14401   3.2 ReplicaFetcherT
# → 14205   14402   3.0 ReplicaFetcherT
# → 14205   14290   1.8 metadata-loader
# → 14205   14210   1.2 VM Thread
# → 14205   14350   0.8 kafka-scheduler
# → 14205   14380   0.4 kafka-log-clean

# Проверка общего числа активных потоков процесса брокера
ls /proc/$(pgrep -f "kafka.Kafka")/task | wc -l
# → 128
```

### 2. Снятие и анализ Thread Dump брокера

Снятие полного среза потоков JVM при диагностике блокировок:

```bash
# Снятие thread dump через стандартную утилиту jcmd
jcmd $(pgrep -f "kafka.Kafka") Thread.print > /tmp/kafka-threaddump.txt
# → 14205:
# → Dumped to /tmp/kafka-threaddump.txt

# Проверка распределения состояний потоков в дампе
grep "java.lang.Thread.State:" /tmp/kafka-threaddump.txt | sort | uniq -c
# →       18 java.lang.Thread.State: BLOCKED
# →       42 java.lang.Thread.State: RUNNABLE
# →       14 java.lang.Thread.State: TIMED_WAITING (parking)
# →       54 java.lang.Thread.State: WAITING (parking)

# Анализ состояния пула Request Handlers
grep -A 4 -E "\"kafka-request-handler" /tmp/kafka-threaddump.txt | grep -E "Thread.State|kafka-request-handler" | head -n 8
# → "kafka-request-handler-0" #32 daemon prio=5 os_prio=0 cpu=1240.12ms elapsed=3420.10s tid=0x00007f3b8c012000 nid=0x37f0 waiting on condition [0x00007f3b6421a000]
# →    java.lang.Thread.State: WAITING (parking)
# → "kafka-request-handler-1" #33 daemon prio=5 os_prio=0 cpu=1180.45ms elapsed=3420.10s tid=0x00007f3b8c014000 nid=0x37f1 runnable [0x00007f3b6431b000]
# →    java.lang.Thread.State: RUNNABLE
```

### 3. Проверка утилизации и простоя пулов через JMX

Чтение ключевых метрик простоя (Idle Percent) с помощью JMX CLI:

```bash
# Проверка процента простоя пула Request Handlers (значение от 0.0 до 1.0)
kafka-run-class org.apache.kafka.tools.JmxTool \
  --jmx-url service:jmx:rmi:///jndi/rmi://127.0.0.1:9999/jmxrmi \
  --object-name "kafka.server:type=KafkaRequestHandlerPool,name=RequestHandlerAvgIdlePercent" \
  --one-time true
# → "kafka.server:type=KafkaRequestHandlerPool,name=RequestHandlerAvgIdlePercent": {"Count": 1, "MeanRate": 0.865, "OneMinuteRate": 0.842}

# Проверка процента простоя пула сетевых процессоров
kafka-run-class org.apache.kafka.tools.JmxTool \
  --jmx-url service:jmx:rmi:///jndi/rmi://127.0.0.1:9999/jmxrmi \
  --object-name "kafka.network:type=SocketServer,name=NetworkProcessorAvgIdlePercent" \
  --one-time true
# → "kafka.network:type=SocketServer,name=NetworkProcessorAvgIdlePercent": {"Count": 1, "MeanRate": 0.912, "OneMinuteRate": 0.895}
```

### 4. Контроль очередей и времени ожидания запросов

```bash
# Проверка текущего количества запросов в RequestQueue
kafka-run-class org.apache.kafka.tools.JmxTool \
  --jmx-url service:jmx:rmi:///jndi/rmi://127.0.0.1:9999/jmxrmi \
  --object-name "kafka.network:type=RequestChannel,name=RequestQueueSize" \
  --one-time true
# → "kafka.network:type=RequestChannel,name=RequestQueueSize": {"Value": 0}

# Проверка времени нахождения запроса в RequestQueue (в миллисекундах)
kafka-run-class org.apache.kafka.tools.JmxTool \
  --jmx-url service:jmx:rmi:///jndi/rmi://127.0.0.1:9999/jmxrmi \
  --object-name "kafka.network:type=RequestMetrics,name=RequestQueueTimeMs,request=Produce" \
  --one-time true
# → "kafka.network:type=RequestMetrics,name=RequestQueueTimeMs,request=Produce": {"50thPercentile": 0.42, "99thPercentile": 1.85, "Mean": 0.58}

# Проверка размера Purgatory для Produce-запросов
kafka-run-class org.apache.kafka.tools.JmxTool \
  --jmx-url service:jmx:rmi:///jndi/rmi://127.0.0.1:9999/jmxrmi \
  --object-name "kafka.server:type=DelayedOperationPurgatory,name=PurgatorySize,delayedOperation=Produce" \
  --one-time true
# → "kafka.server:type=DelayedOperationPurgatory,name=PurgatorySize,delayedOperation=Produce": {"Value": 4}
```

---

## Диагностика и устранение неисправностей

| Проблема / Симптом | Корневая причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Падение `RequestHandlerAvgIdlePercent < 0.2`** (дефицит IO потоков) | Потоки `num.io.threads` непрерывно заняты записью/чтением. Высокий I/O wait на дисках или нехватка потоков под объем запросов. | Метрика `RequestQueueTimeMs` возрастает (> 10 ms). В `ps` потоки `kafka-request-h` потребляют 100% CPU ядра. | 1. Увеличить `num.io.threads` (до $cores \times 2$).<br>2. Проверить задержки записи на диск через `iostat -xz 1`.<br>3. Устранить нехватку Page Cache, снизив размер JVM Heap. |
| **Падение `NetworkProcessorAvgIdlePercent < 0.2`** (дефицит сетевых потоков) | Сетевые процессоры перегружены TLS-шифрованием, десериализацией мелких пакетов или приемом соединений. | Растет `ResponseQueueTimeMs`. Сетевые потоки `kafka-network-t` утилизируют CPU. | 1. Увеличить `num.network.threads` (например, с 8 до 16).<br>2. Настроить продюсеры на укрупнение батчей (`batch.size`, `linger.ms`).<br>3. Использовать аппаратное ускорение AES-NI в процессоре. |
| **Взрывной рост `PurgatorySize` для Produce** | Запросы с `acks=all` не могут получить подтверждение от реплик из-за сетевого лага или деградации follower. | Метрика `RemoteTimeMs` у продюсеров возрастает в десятки раз. Растут `UnderReplicatedPartitions`. | 1. Локализовать отстающий брокер-follower по метрике `records-lag`.<br>2. Проверить дисковую подсистему и сеть между брокерами.<br>3. Убедиться, что на follower хватает `num.replica.fetchers`. |
| **Зависание или отставание `ReplicaFetcherThread`** | Потоки репликации блокируются медленным дисковым вводом-выводом на follower или застревают в обработке больших батчей. | В логах брокера: `ReplicaFetcherThread ... Error in fetch to broker`. Рост лага репликации. | 1. Увеличить `num.replica.fetchers` с 1 до 2–4.<br>2. Проверить `replica.fetcher.max.bytes` (не должен превышать свободную память).<br>3. Проверить thread dump на предмет `BLOCKED` в `ReplicaFetcherThread`. |
| **Долгий запуск брокера после аварийной остановки** | Последовательная валидация сегментов и перестроение индексов при `num.recovery.threads.per.data.dir=1`. | В логах медленно идут сообщения `Loading log <partition>` по одному топику за раз. | Увеличить `num.recovery.threads.per.data.dir` до 2–4 на директорию в `server.properties`. |
| **Ошибка `OutOfMemoryError: unable to create native thread`** | Превышен лимит ОС на максимальное число процессов/потоков пользователя (`LimitNPROC` или `ulimit -u`). | В логе брокера ошибка создания потока при подключении нового listener или фоновой задачи. | 1. Проверить `ulimit -u` для пользователя kafka.<br>2. Выставить `LimitNPROC=65536` и `TasksMax=65536` в systemd unit-файле. |

---

## Лучшие практики

### 1. Формулы и правила расчета пулов потоков

- **`num.network.threads`:**
  - Базовое правило: $\max(4, \lfloor \text{Physical Cores} / 2 \rfloor)$.
  - Если на брокере активно используется шифрование TLS (SSL) и клиенты передают несжатые мелкие сообщения, пул сетевых потоков увеличивают до числа физических ядер ($\text{Physical Cores}$).
  - Учитывайте, что при наличии нескольких listener (например, `INTERNAL://:9092` и `EXTERNAL://:9094`) значение `num.network.threads` применяется **к каждому слушателю отдельно**. Если `num.network.threads=8` и определено 2 listener, брокер создаст 16 сетевых потоков.

- **`num.io.threads`:**
  - Для быстрых накопителей NVMe/SSD: $\text{Physical Cores} \times 1 \dots 1.5$.
  - Для массивов HDD (JBOD): $\max(\text{Physical Cores}, \text{Количество дисков} \times 2)$. Дополнительные потоки позволяют компенсировать длительный I/O wait шпиндельных накопителей.
  - Избегайте избыточного завышения (например, > 64 потоков при 16 ядрах): чрезмерное количество конкурирующих потоков вызывает лавинообразный рост контекстных переключений процессора (Context Switches) и деградацию L1/L2/L3 кэшей CPU.

- **`num.replica.fetchers`:**
  - Значение по умолчанию ($1$) недостаточно для production-кластеров. Рекомендуется задавать от $2$ до $4$.
  - Значение определяет количество потоков, выделяемых **на каждый исходный брокер**, с которого текущий узел реплицирует партиции. Если в кластере 5 брокеров и `num.replica.fetchers=2`, то данный брокер запустит $4 \times 2 = 8$ потоков выкачивания.

- **`num.recovery.threads.per.data.dir`:**
  - Задавать значение от $2$ до $4$. На этапе нормальной работы брокера эти потоки завершены и не потребляют системные ресурсы, но критически ускоряют запуск при инцидентах.

### 2. Предотвращение деградации от переключения контекста (Context Switches)

При мониторинге хоста с помощью `vmstat 1` следите за колонкой `cs` (context switches):
```bash
vmstat 1 5
# → procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
# →  r  b   swpd   free   buff  cache   si   so    bi    bo   in     cs us sy id wa st
# →  3  0      0 8432104 421100 48123004    0    0     4   120 4210  12450 12  4 83  1  0
```
- Если значение `cs` превышает $100\,000$ переключений в секунду при росте `sy` (system CPU time) > 15–20%, пулы потоков брокера перегружены. Снизьте `num.io.threads` и проверьте, не создают ли клиенты чрезмерное количество короткоживущих TCP-сессий (Connection Churn).

### 3. Пороговые значения метрик для мониторинга (SRE SLA)

| Метрика JMX / Prometheus | Предупреждение (Warning) | Авария (Critical) | Действие дежурного инженера |
| :--- | :--- | :--- | :--- |
| `RequestHandlerAvgIdlePercent` | < 0.30 (простой < 30%) | < 0.15 (простой < 15%) | Проверить диск на насыщение I/O; запланировать увеличение `num.io.threads` или горизонтальное масштабирование брокеров. |
| `NetworkProcessorAvgIdlePercent` | < 0.30 (простой < 30%) | < 0.15 (простой < 15%) | Увеличить `num.network.threads`; проверить TLS overhead и наличие connection storms. |
| `RequestQueueTimeMs (Produce, p99)` | > 10 ms | > 50 ms | Потоки Request Handler не успевают забирать задачи из очереди. Проверить блокировки в дампе потоков. |
| `RequestQueueSize` | > 100 | > 500 (при лимите 1000) | Очередь переполняется. Риск отбрасывания входящих соединений клиентами. |
| `PurgatorySize (Produce)` | > 50 | > 500 | Задержка подтверждения репликации в ISR. Проверить состояние брокеров-реплик. |

---

## Дополнительная информация

### Взаимосвязь с другими подсистемами брокера

- **Подсистема памяти и Page Cache:** Увеличение `num.io.threads` не должно сопровождаться чрезмерным раздуванием JVM Heap. Память хоста должна оставаться свободной под Page Cache ядра Linux, иначе дисковые операции IO-потоков будут вызывать физические блокировки с диска вместо работы с ОЗУ.
- **Подсистема дискового I/O:** При высокой утилизации дисков увеличение `num.io.threads` может вызвать обратный эффект — увеличение времени дискового ожидания (`%iowait`) из-за конкуренции за очереди контроллера накопителей.
- **Сетевые буферы ядра Linux:** Параметры `socket.send.buffer.bytes` и `socket.receive.buffer.bytes` брокера должны быть согласованы с системными лимитами ядра `net.core.rmem_max`, `net.core.wmem_max` и `net.ipv4.tcp_rmem` / `net.ipv4.tcp_wmem`.

### Связанные материалы базы знаний

- [Обзор архитектуры и компонентов Apache Kafka](./kafka_overview.md) — фундаментальные принципы брокера, партиционирования и репликации.
- [OS тюнинг для Apache Kafka](./kafka_os_tuning.md) — параметры ядра Linux (`vm.dirty_ratio`, `vm.max_map_count`, сетевые буферы).
- [JVM и GC тюнинг для Apache Kafka](./kafka_jvm_gc_tuning.md) — распределение оперативной памяти между Heap и Page Cache, тюнинг сборщиков мусора G1GC/ZGC.
- [ISR и репликация в Apache Kafka](./kafka_isr_replication.md) — детальная работа потоков репликации `ReplicaFetcherThread` и механизмы ISR.
- [Playbook по устранению неисправностей Kafka](./kafka_troubleshooting_playbook.md) — пошаговые инструкции при авариях и деградациях кластера.
- [Развертывание кластера Kafka через Ansible](./kafka_ansible_deployment.md) — автоматизация развертывания на bare-metal серверах с production-конфигурацией.
