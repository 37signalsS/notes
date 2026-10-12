# ISR и репликация в Apache Kafka

**Актуально для:** Apache Kafka 3.8.x / 3.9.x / 4.0.x (KRaft)

**ISR (In-Sync Replicas)** — это динамический набор реплик партиции, которые полностью синхронизированы с лидером и не отстают от него дольше допустимого интервала времени. Механизм ISR лежит в основе модели отказоустойчивости Apache Kafka: он балансирует требования к строгой согласованности (durability) и доступности на запись (availability), позволяя кластеру продолжать обслуживание запросов без потери подтвержденных сообщений при сбое отдельных брокеров.

---

## Определения

- **ISR (In-Sync Replicas):** Список брокеров-реплик (включая лидера), признанных лидером партиции синхронными. Только реплика из текущего набора ISR имеет право стать новым лидером при штатном переключении или аварии.
- **HW (High Watermark):** Смещение (offset) последнего сообщения, успешно записанного и подтвержденного всеми репликами из текущего набора ISR. Сообщения со смещением выше HW считаются незакоммиченными и недоступны для вычитки консьюмерами.
- **LEO (Log End Offset):** Смещение следующей записи, которая будет добавлена в локальный лог брокера (на единицу больше смещения последнего физически записанного сообщения).
- **Replica Lag:** Отставание реплики от лидера. Выражается либо во времени с момента последнего успешного fetch-запроса, либо в количестве сообщений между LEO лидера и LEO follower.
- **Leader Epoch:** Монотонно возрастающий целочисленный идентификатор поколения лидерства партиции (KIP-101). Фиксируется в файле `leader-epoch-checkpoint` и предотвращает расхождение логов (log divergence) и потерю данных при восстановлении брокеров после сбоев.
- **ReplicaFetcherThread:** Фоновый пул потоков брокера (`num.replica.fetchers`), инициирующий запросы `FetchRequest` к лидерам удаленных партиций для копирования данных на follower.
- **ProducePurgatory:** Внутрипамяточная структура лидера (`DelayedProduce`), удерживающая клиентские запросы продюсеров с `acks=all` до тех пор, пока все реплики из ISR не подтвердят запись или не истечет таймаут.
- **min.insync.replicas:** Минимальное количество синхронных реплик в ISR (включая лидера), необходимое для подтверждения записи при `acks=all` (`acks=-1`).
- **replica.lag.time.max.ms:** Пороговый интервал времени, в течение которого реплика-follower обязана отправить запрос на чтение и догнать LEO лидера, чтобы не быть исключенной из ISR.
- **ISR Shrink:** Событие исключения отстающей или недоступной реплики из набора ISR лидером партиции.
- **ISR Expand:** Событие возвращения догнавшей реплики в набор ISR.
- **Under-Replicated Partitions (URP):** Партиции, у которых текущий размер набора ISR строго меньше заданного фактора репликации (`replication.factor`).
- **Under-Min-ISR Partitions:** Партиции, у которых текущий размер ISR строго меньше значения `min.insync.replicas` (запись с `acks=all` полностью блокируется).
- **Unclean Leader Election:** Вынужденное назначение лидером реплики, не входящей в ISR, в ситуации, когда все участники ISR стали недоступны. Приводит к потере данных и перезаписи офсетов.
- **Preferred Leader:** Первая реплика в статическом списке назначенных реплик партиции (AR — Assigned Replicas). Служит целевым узлом для балансировки нагрузки между брокерами.
- **AlterPartition RPC:** Протокол взаимодействия в архитектуре KRaft, посредством которого брокер-лидер атомарно регистрирует изменения состава ISR в метаданных контроллера.

---

## Архитектура и внутренние механизмы

### Механизм ISR и продвижение High Watermark

В Kafka лидер партиции управляет жизненным циклом ISR и вычисляет границу High Watermark (HW):

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Partition 0 (RF=3)                               │
├──────────────────────────────────────────────────────────────────────────┤
│  Leader (Broker 1)                                                       │
│  ├── LEO: 100                                                            │
│  ├── HW:  95  <── min(LEO всех ISR: Broker 1=100, Broker 2=98, Broker 3=95)│
│  └── ISR: [1, 2, 3]                                                      │
├──────────────────────────────────────────────────────────────────────────┤
│  Follower (Broker 2)                                                     │
│  ├── LEO: 98 (отставание: 2 сообщения)                                  │
│  └── Статус: ISR (FetchRequest отправлен 40 мс назад)                    │
├──────────────────────────────────────────────────────────────────────────┤
│  Follower (Broker 3)                                                     │
│  ├── LEO: 95 (отставание: 5 сообщений)                                  │
│  └── Статус: ISR (FetchRequest отправлен 120 мс назад)                   │
└──────────────────────────────────────────────────────────────────────────┘
```

#### Жизненный цикл репликации сообщения

1. **Запись на лидере:** Продюсер отправляет батч сообщений. Поток `KafkaRequestHandler` записывает батч в Page Cache сегмента лога лидера. LEO лидера увеличивается (например, с 95 до 100).
2. **Помещение в Purgatory:** Если продюсер указал `acks=all`, запрос удерживается в структуре `DelayedProduce`.
3. **Fetch-запросы от follower:** Потоки `ReplicaFetcherThread` на брокерах 2 и 3 отправляют лидеру запрос `FetchRequest`, содержащий текущий LEO фолловера и его текущий `Leader Epoch`.
4. **Ответ лидера и локальная запись:** Лидер передает запрошенные данные и текущее значение HW. Брокеры-follower записывают батч в свои локальные логи и обновляют свои LEO (Broker 2 до 98, Broker 3 до 95).
5. **Фиксация LEO фолловеров лидером:** Лидер узнает о продвижении LEO фолловеров из смещения следующего входящего `FetchRequest`. Как только смещение 95 подтверждено всеми репликами из ISR `[1, 2, 3]`, лидер сдвигает свой HW до 95.
6. **Подтверждение продюсеру:** Когда HW достигает смещения отправленного продюсером батча (при условии, что размер ISR $\ge$ `min.insync.replicas`), операция в `DelayedProduce` завершается, и лидер возвращает продюсеру успешный `ProduceResponse`.
7. **Чтение консьюмерами:** Консьюмеры имеют доступ только к записям с офсетами $< \text{HW}$. Сообщения в диапазоне между HW и LEO лидера считаются незакоммиченными (uncommitted).

```
Продюсер               Лидер (Брокер 1)             Follower (Брокер 2)
   │                          │                             │
   │── Produce (acks=all) ───>│                             │
   │   (LEO: 95 -> 100)       │── Append to log             │
   │                          │── Add to ProducePurgatory   │
   │                          │                             │
   │                          │<── FetchRequest (offset=95)─│
   │                          │    (Leader Epoch=1)         │
   │                          │                             │
   │                          │── FetchResponse (data) ────>│
   │                          │   (HW=95)                   │── Append to log
   │                          │                             │   (LEO: 95 -> 100)
   │                          │                             │
   │                          │<── FetchRequest (offset=100)│
   │                          │    (Leader узнает LEO=100)  │
   │                          │                             │
   │                          │── HW сдвигается до 100      │
   │                          │── Complete ProducePurgatory │
   │<── ProduceResponse ──────│                             │
   │    (offset=95..99 OK)    │                             │
```

---

### Правила членства в ISR (Shrink и Expand)

Реплика считается синхронной (In-Sync) при выполнении двух условий:
1. Она непрерывно отправляет `FetchRequest` к лидеру, и пауза между запросами не превышает `replica.lag.time.max.ms`.
2. Если в партицию непрерывно поступают новые сообщения, реплика успевает догонять LEO лидера так, чтобы интервал отставания от LEO лидера по времени не превышал `replica.lag.time.max.ms`.

> **Историческая справка:** Параметр `replica.lag.max.messages` (ограничение по абсолютному количеству сообщений) был удален в Kafka 0.9.0 (KIP-16), так как вызывал ложные исключения реплик из ISR (ISR thrashing/flapping) при кратковременных всплесках пакетного трафика. Актуальным критерием является исключительно временной порог `replica.lag.time.max.ms`.

#### Механизм исключения (ISR Shrink)

- Лидер отслеживает время последнего запроса и последнего продвижения LEO для каждого follower.
- Если follower не подтверждает актуальный LEO в течение `replica.lag.time.max.ms`, лидер формирует запрос на исключение.
- **В архитектуре KRaft:** Лидер отправляет RPC-запрос `AlterPartition` активному KRaft-контроллеру. Контроллер выполняет запись в лог метаданных `@metadata` и возвращает лидеру подтверждение с новым `PartitionEpoch`. После этого реплика официально исключена из ISR, и брокер обновляет метрику `UnderReplicatedPartitions`.

#### Механизм возвращения (ISR Expand)

- Отставшая реплика продолжает отправлять `FetchRequest` и вычитывать лог лидера.
- Когда LEO реплики сравнивается с LEO лидера, лидер отправляет `AlterPartition` контроллеру для возврата брокера в ISR.
- После подтверждения контроллером реплика снова учитывается при расчете HW, а метрика `UnderReplicatedPartitions` уменьшается.

---

### Leader Epoch и предотвращение расхождения логов

До введения механизма Leader Epoch (KIP-101) реплики при перезапуске после сбоя усекали свой локальный лог до собственного сохраненного значения High Watermark (`replication-offset-checkpoint`). Это приводило к двум критическим аномалиям:
1. **Потеря подтвержденных данных (Silent Data Loss):** Если брокер падал до того, как сбросил обновленный HW на диск, после перезапуска он усекал сообщения, которые продюсер уже получил как успешно сохраненные.
2. **Расхождение логов (Log Divergence):** При чередующихся авариях двух брокеров новый лидер начинал записывать новые сообщения с теми же смещениями, на которых у старого лидера хранились другие данные, что приводило к рассинхронизации реплик.

#### Как работает Leader Epoch

Каждый брокер сохраняет в каталоге партиции файл `leader-epoch-checkpoint`. Файл содержит таблицу отображения эпохи лидера на начальное смещение этой эпохи:

```text
# leader-epoch-checkpoint
0    # Версия формата
2    # Количество записей
0 0  # Epoch 0: начинается со смещения 0
1 45 # Epoch 1: начинается со смещения 45
```

- При перезапуске follower **не усекает** свой лог до HW.
- Follower отправляет новому лидеру запрос `OffsetForLeaderEpochRequest`, передавая свой последний сохраненный Leader Epoch.
- Лидер возвращает конечное смещение (End Offset) для этой эпохи.
- Follower усекает лог только до того смещения, которое лидер признал валидным для соответствующей эпохи. Если данные совпадают, усечение не выполняется, исключая потерю сообщений.

---

### Взаимодействие acks и min.insync.replicas

Надежность доставки и доступность кластера определяются совместной работой конфигурации продюсера `acks` и настроек партиции `replication.factor` (RF) и `min.insync.replicas`:

| Конфигурация | Гарантия записи | Поведение при отказе брокеров | Риск потери данных |
|---|---|---|---|
| `acks=0` | Запись в сокет продюсера | Продюсер не ждет ответа. Ошибки брокера игнорируются. | Критический (любой сбой ведет к потере данных). |
| `acks=1` | Запись в Page Cache лидера | Лидер подтверждает запись немедленно, не дожидаясь реплик. | Высокий (авария лидера до репликации на follower ведет к потере батча). |
| `acks=all` (`-1`) + `min.insync.replicas=1` | Запись во все реплики текущего ISR | Если в живых остался только лидер, ISR=[1]. Запись подтверждается одиночным лидером. | Средний (при падении последнего брокера данные могут быть потеряны). |
| `acks=all` (`-1`) + `min.insync.replicas=2` (при RF=3) | Запись минимум на 2 брокера | Допускается падение одного брокера из трех без остановки записи. При падении двух — запись блокируется. | Минимальный (стандарт для production). |
| `acks=all` (`-1`) + `min.insync.replicas=3` (при RF=3) | Запись на все 3 брокера | Любой плановый рестарт или кратковременный сбой любого брокера полностью останавливает запись. | Избыточно жесткий (кластер теряет устойчивость к единичным сбоям). |

#### Исключения продюсера при нарушении кворума

Если размер текущего набора ISR меньше `min.insync.replicas`, лидер отклоняет входящие сообщения с `acks=all`:
- **`NotEnoughReplicasException`:** Выбрасывается до добавления сообщений в лог, если в момент прихода запроса число реплик в ISR уже строго меньше `min.insync.replicas`. Является повторимым (retriable) исключением: продюсер повторяет отправку согласно `retries` и `retry.backoff.ms`.
- **`NotEnoughReplicasAfterAppendException`:** Выбрасывается в том случае, если в момент добавления сообщения в локальный лог лидера размер ISR был достаточен, но в процессе ожидания репликации фолловеры отпали, и продвинуть HW оказалось невозможно. Сообщение физически записано в лог лидера, но продюсер получает retriable ошибку.

---

### Unclean Leader Election

Параметр `unclean.leader.election.enable` определяет поведение кластера, когда **все** реплики из набора ISR вышли из строя, но остались доступными реплики, не входящие в ISR (out-of-sync followers).

```
Исходное состояние: ISR = [Broker 1 (Leader), Broker 2 (Follower)]. Broker 3 отстает (LEO=80 при лидерском LEO=100).
Авария: Брокеры 1 и 2 одновременно выходят из строя (питание, сеть).
```

- **При `unclean.leader.election.enable=false` (рекомендуется):**
  - Кластер запрещает назначение Брокера 3 лидером.
  - Партиция переходит в состояние недоступности для чтения и записи (`OfflinePartitions`).
  - Кластер ждет восстановления хотя бы одного брокера из прежнего состава ISR (Брокер 1 или 2).
  - **Результат:** Доступность временно принесена в жертву сохранности данных (Consistency > Availability). Ни одно подтвержденное сообщение не теряется.
- **При `unclean.leader.election.enable=true`:**
  - Контроллер назначает Брокер 3 новым лидером.
  - LEO Брокера 3 равен 80. Сообщения с 80 по 99, которые были подтверждены продюсерам старым лидером, безвозвратно теряются.
  - Продюсеры продолжают писать в Брокер 3, формируя смещения 80, 81, 82... с новым содержимым.
  - Когда Брокер 1 возвращается, его лог усекается по новому Leader Epoch, перезаписывая старые данные новыми.
  - **Результат:** Нарушение порядка, потеря подтвержденных транзакций, расхождение смещений у консьюмеров.

---

### Параметры репликации брокера

Ниже приведены ключевые параметры подсистемы репликации в файле `server.properties`:

| Параметр | По умолчанию | Рекомендуемое (Production) | Тип | Описание |
|---|---|---|---|---|
| `replica.lag.time.max.ms` | `30000` | `10000`–`30000` | Dynamic | Максимальный интервал времени без fetch-запросов или прогресса LEO до исключения реплики из ISR. |
| `min.insync.replicas` | `1` | `2` (при RF=3) | Dynamic (topic/broker) | Минимальное число реплик в ISR для успешной фиксации записи при `acks=all`. |
| `unclean.leader.election.enable` | `false` | `false` | Dynamic (topic/broker) | Запрет на выборы лидера из несинхронизированных реплик при отказе всех членов ISR. |
| `num.replica.fetchers` | `1` | `2`–`4` | Static | Количество параллельных потоков копирования данных с каждого исходного брокера. |
| `replica.fetch.max.bytes` | `1048576` (1 МБ) | `4194304`–`10485760` (4–10 МБ) | Dynamic | Максимальный объем данных, запрашиваемый потоком fetcher за один запрос для одной партиции. |
| `replica.fetch.response.max.bytes` | `10485760` (10 МБ) | `33554432`–`67108864` (32–64 МБ) | Dynamic | Максимальный совокупный размер ответа на `FetchRequest` со всеми партициями. |
| `replica.fetch.wait.max.ms` | `500` | `200`–`500` | Static | Максимальное время удержания fetch-запроса лидером при отсутствии новых данных (`DelayedFetch`). |
| `replica.fetch.min.bytes` | `1` | `1` | Static | Минимальный объем данных, при накоплении которого лидер немедленно отдает ответ реплике. |
| `replica.socket.timeout.ms` | `30000` | `30000` | Static | Сетевой таймаут сокета для межброкерных fetch-запросов (должен быть $\ge$ `replica.fetch.wait.max.ms`). |
| `replica.socket.receive.buffer.bytes` | `65536` (64 КБ) | `1048576` (1 МБ) | Static | Размер буфера приема сокета для потоков репликации. Критично для 10GbE/25GbE сетей. |
| `replica.high.watermark.checkpoint.interval.ms` | `5000` | `5000` | Static | Периодичность сброса HW каждой партиции в файл `replication-offset-checkpoint` на диске. |
| `auto.leader.rebalance.enable` | `true` | `true` | Static | Фоновый автоматический возврат лидерства репликам Preferred Leader для исключения перекоса нагрузки. |
| `leader.imbalance.per.broker.percentage` | `1` | `1` | Static | Допустимый процент дисбаланса предпочтительных лидеров перед запуском автоматической перебалансировки. |

---

## Практические сценарии и конфигурация

### Сценарий 1: Конфигурация кластера для максимальной надежности (Zero Data Loss)

Конфигурация исключает потерю подтвержденных сообщений при отказе любого отдельного узла кластера.

#### 1. Глобальные параметры брокера (`/etc/kafka/server.properties`)

```properties
# Запретить выбор лидера не из ISR
unclean.leader.election.enable=false

# Значения по умолчанию для создаваемых топиков
default.replication.factor=3
min.insync.replicas=2

# Настройки потоков репликации под 10GbE сеть
num.replica.fetchers=4
replica.fetch.max.bytes=5242880
replica.fetch.response.max.bytes=52428800
replica.socket.receive.buffer.bytes=1048576

# Порог исключения отстающей реплики (30 секунд)
replica.lag.time.max.ms=30000

# Автоматический возврат лидеров на preferred-ноды
auto.leader.rebalance.enable=true
leader.imbalance.per.broker.percentage=1
```

#### 2. Создание и валидация топика через CLI

```bash
# Создание топика с RF=3 и явным указанием min.insync.replicas=2
/opt/kafka/bin/kafka-topics.sh --bootstrap-server 10.0.10.11:9092 \
  --create --topic orders.financial \
  --partitions 12 \
  --replication-factor 3 \
  --config min.insync.replicas=2
# → Created topic orders.financial.

# Проверка конфигурации топика
/opt/kafka/bin/kafka-configs.sh --bootstrap-server 10.0.10.11:9092 \
  --entity-type topics --entity-name orders.financial --describe
# → Dynamic configs for topic orders.financial are:
# →   min.insync.replicas=2 sensitive=false synonyms={DYNAMIC_TOPIC_CONFIG:min.insync.replicas=2}
```

#### 3. Настройка клиента-продюсера

```properties
# Обязательное подтверждение от всех реплик в ISR
acks=all

# Включение идемпотентности продюсера (защита от дубликатов при retry)
enable.idempotence=true
max.in.flight.requests.per.connection=5
retries=2147483647
delivery.timeout.ms=120000
```

---

### Сценарий 2: Диагностика деградации ISR и недореплицированных партиций

При падении брокера или перегрузке дисковой подсистемы размер набора ISR падает ниже фактора репликации (`UnderReplicatedPartitions > 0`).

#### Шаг 1. Локализация проблемных партиций через CLI

```bash
# Поиск партиций, где число реплик в ISR < replication.factor
/opt/kafka/bin/kafka-topics.sh --bootstrap-server 10.0.10.11:9092 \
  --describe --under-replicated-partitions
# → Topic: orders.financial  Partition: 3  Leader: 1  Replicas: 1,2,3  Isr: 1,2
# → Topic: telemetry.events  Partition: 0  Leader: 2  Replicas: 2,3,1  Isr: 2

# Поиск критических партиций, где число ISR < min.insync.replicas (запись заблокирована)
/opt/kafka/bin/kafka-topics.sh --bootstrap-server 10.0.10.11:9092 \
  --describe --under-min-isr-partitions
# → Topic: telemetry.events  Partition: 0  Leader: 2  Replicas: 2,3,1  Isr: 2
```

#### Шаг 2. Проверка метрик отставания через JMX

```bash
# Проверка текущего количества URP на брокере
/opt/kafka/bin/kafka-run-class.sh kafka.tools.JmxTool \
  --jmx-url service:jmx:rmi:///jndi/rmi://10.0.10.11:9999/jmxrmi \
  --object-name "kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions" \
  --one-time true
# → "kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions": {"Value": 2}

# Проверка максимального отставания репликатора (MaxLag)
/opt/kafka/bin/kafka-run-class.sh kafka.tools.JmxTool \
  --jmx-url service:jmx:rmi:///jndi/rmi://10.0.10.11:9999/jmxrmi \
  --object-name "kafka.server:type=ReplicaFetcherManager,name=MaxLag,clientId=Replica" \
  --one-time true
# → "kafka.server:type=ReplicaFetcherManager,name=MaxLag,clientId=Replica": {"Value": 145020}
```

#### Шаг 3. Анализ логов брокера-лидера

```bash
# Поиск событий исключения и возврата реплик в логе брокера
grep -E "is no longer in sync|Expanding ISR|Shrinking ISR" /var/log/kafka/server.log
# → [2026-10-12 14:10:02,114] INFO [Partition orders.financial-3 broker=1] Shrinking ISR from 1,2,3 to 1,2. Leader: 1, Epoch: 4, CurrentConfigMinIsr: 2 (kafka.cluster.Partition)
# → [2026-10-12 14:10:02,118] INFO [Partition orders.financial-3 broker=1] Cached zkVersion [4] updated to [5] after successfully altering ISR to 1,2 (kafka.cluster.Partition)
```

---

### Сценарий 3: Сверка целостности и смещений реплик через kafka-replica-verification

Для проверки идентичности данных на всех репликах партиций без прерывания работы кластера используется утилита `kafka-replica-verification.sh`:

```bash
# Запуск валидации согласованности реплик для целевого топика
/opt/kafka/bin/kafka-replica-verification.sh \
  --bootstrap-server 10.0.10.11:9092 \
  --topic-white-list 'orders.financial' \
  --report-interval-ms 2000
# → 2026-10-12 14:20:00: verification process is checking 12 topic-partitions
# → 2026-10-12 14:20:02: orders.financial-0: max lag is 0 for replica 2. Current offset is 4512034.
# → 2026-10-12 14:20:02: orders.financial-1: max lag is 0 for replica 3. Current offset is 3891022.
# → 2026-10-12 14:20:02: orders.financial-3: max lag is 120 for replica 3. Current offset is 5120400.
```

---

### Сценарий 4: Плановое обслуживание брокера без деградации ISR

Для проведения регламентных работ (обновление ядра ОС, замена оборудования) вывод брокера осуществляется штатным образом с контролем миграции лидеров.

#### Шаг 1. Проверка включения Controlled Shutdown

Убедитесь, что в `/etc/kafka/server.properties` включен параметр:
```properties
controlled.shutdown.enable=true
controlled.shutdown.max.retries=3
controlled.shutdown.retry.backoff.ms=5000
```

#### Шаг 2. Корректная остановка службы

При сигнале `SIGTERM` брокер самостоятельно передает лидерство по всем своим партициям другим синхронным репликам из набора ISR до завершения процесса:

```bash
# Остановка сервиса брокера
systemctl stop kafka

# Проверка логов контролируемой передачи лидерства
journalctl -u kafka -n 50 --no-pager | grep "ControlledShutdown"
# → INFO [KafkaServer id=3] Controlled shutdown succeeded! (kafka.server.KafkaServer)
# → INFO [KafkaServer id=3] Shutting down complete (kafka.server.KafkaServer)
```

#### Шаг 3. Запуск и контроль ресинхронизации (ISR Expansion)

После завершения работ брокер запускается обратно:

```bash
systemctl start kafka

# Мониторинг восстановления набора ISR в реальном времени
watch -n 1 "/opt/kafka/bin/kafka-topics.sh --bootstrap-server 10.0.10.11:9092 --describe --under-replicated-partitions"
# → Вывод должен стать пустым по завершении вычитки отставания:
# → (пустой вывод)
```

#### Шаг 4. Возврат Preferred Leader

Если автоматическая перебалансировка лидеров не сработала немедленно, восстановите эталонное распределение лидеров:

```bash
/opt/kafka/bin/kafka-leader-election.sh \
  --bootstrap-server 10.0.10.11:9092 \
  --election-type PREFERRED \
  --all-topic-partitions
# → Successfully completed leader election (PREFERRED) for partitions: orders.financial-0, orders.financial-1, ...
```

---

### Сценарий 5: Оптимизация репликации при сетевых задержках (Cross-DC / Campus)

При репликации между территориально распределенными серверными стойками или площадками с round-trip time (RTT) 5–15 мс стандартные настройки сокетов и буферов приводят к ложным исключениям реплик из ISR.

#### Конфигурация брокера (`server.properties`)

```properties
# Увеличение таймаута для предотвращения флаппинга при всплесках задержки
replica.lag.time.max.ms=60000

# Увеличение времени ожидания накопления данных лидером
replica.fetch.wait.max.ms=1000

# Увеличение размера разовой порции репликации
replica.fetch.max.bytes=10485760
replica.fetch.response.max.bytes=104857600

# Увеличение количества параллельных потоков вычитки на каждый брокер
num.replica.fetchers=4

# Тюнинг сетевых буферов TCP под высокое произведение задержки на пропускную способность (BDP)
replica.socket.receive.buffer.bytes=4194304
replica.socket.timeout.ms=60000
```

#### Проверка сетевого стека Linux

```bash
# Проверка сетевой задержки и потерь пакетов
ping -c 100 -i 0.2 10.0.20.12 | tail -n 2
# → 100 packets transmitted, 100 received, 0% packet loss, time 19808ms
# → rtt min/avg/max/mdev = 4.120/5.210/8.940/0.450 ms

# Проверка очередей сокетов на порту Kafka (наличие переполнения Recv-Q / Send-Q)
ss -t -i '( sport = :9092 or dport = :9092 )'
# → State      Recv-Q Send-Q  Local Address:Port   Peer Address:Port
# → ESTAB      0      0       10.0.10.11:9092      10.0.20.12:43210  rtt:5.2/0.4 rcvspace:4194304 ssthresh:28 cwnd:30
```

---

### Сценарий 6: Аварийное восстановление при полной потере ISR (Все реплики ISR недоступны)

Случай: в живых остался только Брокер 3, который был исключен из ISR до аварии (содержит LEO=80 при лидерском LEO=100). Партиция перешла в состояние offline.

#### Вариант А: Ожидание исходных реплик (Безопасный, без потери данных)

Приоритетное действие администратора: не трогать конфигурацию топика, локализовать причину сбоя на брокерах 1 и 2 (проблема питания, сбой ОС) и запустить их. Как только любой узел из исходного набора ISR стартует, контроллер назначит его лидером, и запись возобновится без потери сообщений.

#### Вариант Б: Принудительный Unclean Leader Election (Крайняя мера, с потерей данных)

Если брокеры 1 и 2 физически уничтожены и восстановлению не подлежат, а простой сервиса недопустим:

```bash
# 1. Проверка текущего состояния партиции
/opt/kafka/bin/kafka-topics.sh --bootstrap-server 10.0.10.13:9092 \
  --describe --topic orders.financial
# → Topic: orders.financial Partition: 0 Leader: none Replicas: 1,2,3 Isr: 1,2 Offline: 1,2

# 2. Принудительный запуск выборов несинхронного лидера через утилиту выборов
/opt/kafka/bin/kafka-leader-election.sh \
  --bootstrap-server 10.0.10.13:9092 \
  --election-type UNCLEAN \
  --topic orders.financial \
  --partition 0
# → Successfully completed leader election (UNCLEAN) for partitions: orders.financial-0

# 3. Проверка возвращения партиции в рабочий статус с новым лидером
/opt/kafka/bin/kafka-topics.sh --bootstrap-server 10.0.10.13:9092 \
  --describe --topic orders.financial
# → Topic: orders.financial Partition: 0 Leader: 3 Replicas: 1,2,3 Isr: 3
```

> **Важно:** Сообщения со смещениями 80..99 потеряны. Консьюмеры, уже прочитавшие старые сообщения, при рестарте столкнутся с несоответствием смещений.

---

## Диагностика и устранение неполадок

| Симптом / Ошибка | Первопричина | Метод диагностики | Способ устранения |
|---|---|---|---|
| Продюсер получает `NotEnoughReplicasException` | Число активных синхронных реплик в ISR упало ниже `min.insync.replicas`. Запись остановлена для предотвращения потери данных. | `kafka-topics.sh --describe --under-min-isr-partitions`<br>Метрика JMX: `UnderMinIsrPartitionCount > 0` | 1. Найти упавший брокер и перезапустить службу.<br>2. Проверить сетевую доступность между брокерами.<br>3. **Запрещено** снижать `min.insync.replicas` на лету в production. |
| Продюсер получает `NotEnoughReplicasAfterAppendException` | Батч записан в лог лидера, но в процессе ожидания репликации фолловеры отпали по таймауту, и HW не достиг смещения батча. | Логи продюсера и лог брокера-лидера: `Shrinking ISR`<br>Проверка задержки дисков на follower | 1. Продюсер автоматически повторит отправку при `retries > 0`.<br>2. Устранить причины отставания follower (дисковые очереди, сеть). |
| Постоянно `UnderReplicatedPartitions > 0` при работающих брокерах | Реплика не успевает за лидером: медленный диск (высокий I/O wait), перегрузка сети, нехватка потоков `num.replica.fetchers`. | 1. `iostat -xz 1` на отстающем узле (%util, await).<br>2. JMX: `MaxLag` на ReplicaFetcherManager.<br>3. `top` / `sar -n DEV 1`. | 1. Увеличить `num.replica.fetchers` с 1 до 2–4.<br>2. Увеличить `replica.fetch.max.bytes`.<br>3. Оптимизировать файловую систему (опция монтирования `noatime`). |
| Периодический ISR Flapping (быстрый Shrink и Expand) | Длительные паузы Stop-the-World JVM Garbage Collection на follower либо кратковременные всплески задержек сети. | 1. Логи GC: `/var/log/kafka/kafka-gc.log`<br>2. Метрики JMX: `IsrShrinkRate` и `IsrExpandRate`.<br>3. Поиск пауз JVM длительностью $\ge$ `replica.lag.time.max.ms`. | 1. Тюнинг G1GC (`-XX:MaxGCPauseMillis=20`, `-XX:InitiatingHeapOccupancyPercent=45`).<br>2. Увеличить `replica.lag.time.max.ms` с 10000 до 30000 мс.<br>3. Проверить отсутствие свопинга (`vm.swappiness=1`). |
| Ошибка консьюмера `OffsetOutOfRangeException` на follower | Follower усек лог некорректно либо произошел сброс retention при повреждении файла `leader-epoch-checkpoint`. | Лог follower: `Resetting fetch offset`<br>Сверка `leader-epoch-checkpoint` на узлах | Проверить целостность файловой системы. Выполнить проверку консистентности через `kafka-replica-verification.sh`. |
| `OfflinePartitionsCount > 0` | Все реплики партиции недоступны либо упал брокер-лидер при выключенном `unclean.leader.election.enable`. | `kafka-topics.sh --describe --unavailable-partitions` | Поднять упавшие брокеры. При необратимой потере всех узлов ISR — принудительный unclean leader election (см. Сценарий 6). |
| Перекос лидеров (`LeaderCount` сильно различается между узлами) | После падений и перезапусков брокеры вернулись, но лидерство осталось на оставшихся узлах. | JMX: `LeaderCount`<br>`kafka-topics.sh --describe` | Выполнить перебалансировку: `kafka-leader-election.sh --election-type PREFERRED --all-topic-partitions`. Включить `auto.leader.rebalance.enable=true`. |

---

## Лучшие практики

### 1. Архитектурное правило кворума: RF=3 и min.insync.replicas=2

- **Фактор репликации 3 (RF=3):** Стандарт для корпоративных сред. Обеспечивает наличие 1 лидера и 2 независимых follower.
- **`min.insync.replicas=2` при `acks=all`:** Гарантирует, что сообщение зафиксировано как минимум на двух независимых дисковых накопителях перед подтверждением клиенту.
- **Почему нельзя ставить `min.insync.replicas=3` при RF=3:** Если все 3 реплики обязательны для записи, то любой регламентный перезапуск хотя бы одного брокера или минутная задержка сети приведет к немедленной ошибке `NotEnoughReplicasException` и полному отказу кластера на запись.
- **Почему RF=2 является антипаттерном:** При RF=2 и `min.insync.replicas=2` отказ одного узла блокирует запись. При RF=2 и `min.insync.replicas=1` отказ одного узла оставляет данные с единственной копией, где любой следующий сбой приводит к безвозвратной потере.

### 2. Оптимизация операционной системы и дисковой подсистемы

- **Файловая система:** Используйте XFS с опциями монтирования `noatime,nodiratime,logbufs=8,logbsize=256k`.
- **Выделенные диски:** Хранилище логов Kafka (`log.dirs`) должно располагаться на выделенных физических NVMe/SSD накопителях, изолированно от корневой файловой системы ОС и логов приложений.
- **Page Cache:** Объем оперативной памяти должен позволять удерживать активный хвост логов (working set) в системном Page Cache Linux. Это позволяет потокам `ReplicaFetcherThread` читать данные напрямую из RAM, не вызывая физических чтений с диска лидера.
- **Свопинг:** Полностью исключите вытеснение памяти JVM в своп: настройте sysctl `vm.swappiness=1`.

### 3. Производственный чек-лист SRE / Sysadmin

- [ ] Все критичные топики имеют `replication.factor=3` и `min.insync.replicas=2`.
- [ ] Параметр `unclean.leader.election.enable` установлен в `false` на уровне брокеров и топиков.
- [ ] Параметр `num.replica.fetchers` настроен на 2–4 потока на брокер для параллельного копирования.
- [ ] Включен `auto.leader.rebalance.enable=true` с проверкой `leader.imbalance.per.broker.percentage=1`.
- [ ] Включен `controlled.shutdown.enable=true` для безаварийного вывода нод на обслуживание.
- [ ] Продюсеры настроены с `acks=all` и `enable.idempotence=true`.
- [ ] Настроены алерты мониторинга на метрики `UnderReplicatedPartitions > 0` и `UnderMinIsrPartitionCount > 0`.
- [ ] Настроен непрерывный сбор логов сборщика мусора JVM (`kafka-gc.log`) для контроля пауз Stop-the-World.

---

## Дополнительная информация

### Мониторинг и метрики подсистемы репликации

#### Ключевые JMX-метрики брокера

| Метрика JMX (Mbean) | Имя в Prometheus JMX Exporter | Описание | Норма | Критический порог |
|---|---|---|---|---|
| `kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions` | `kafka_server_replicamanager_underreplicatedpartitions` | Количество партиций, где число реплик в ISR меньше фактора репликации | `0` | `> 0` более 3 минут |
| `kafka.server:type=ReplicaManager,name=UnderMinIsrPartitionCount` | `kafka_server_replicamanager_underminisrpartitioncount` | Количество партиций, где число реплик в ISR меньше `min.insync.replicas` | `0` | `> 0` немедленно (блокировка записи) |
| `kafka.server:type=ReplicaManager,name=OfflineReplicaCount` | `kafka_server_replicamanager_offlinereplicacount` | Количество реплик на брокерах, диски которых перешли в режим offline | `0` | `> 0` |
| `kafka.controller:type=KafkaController,name=OfflinePartitionCount` | `kafka_controller_kafkacontroller_offlinepartitioncount` | Количество партиций без назначенного лидера (полная недоступность) | `0` | `> 0` немедленно |
| `kafka.server:type=ReplicaManager,name=IsrShrinksPerSec` | `kafka_server_replicamanager_isrshrinkspersec` | Частота исключения реплик из состава ISR в секунду | `0` | `> 0` (сигнал о деградации реплик) |
| `kafka.server:type=ReplicaManager,name=IsrExpandsPerSec` | `kafka_server_replicamanager_isrexpandspersec` | Частота возвращения реплик в состав ISR в секунду | `0` | Всплески после аварии — норма |
| `kafka.server:type=ReplicaFetcherManager,name=MaxLag,clientId=Replica` | `kafka_server_replicafetchermanager_maxlag` | Максимальное отставание follower по смещениям от лидера | `< 1000` | Постоянный рост |

#### Пример правил алертинга для Prometheus (`kafka_alerts.yml`)

```yaml
groups:
  - name: kafka_replication_alerts
    rules:
      - alert: KafkaUnderReplicatedPartitions
        expr: kafka_server_replicamanager_underreplicatedpartitions > 0
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Брокер Kafka содержит недореплицированные партиции"
          description: "На брокере {{ $labels.instance }} обнаружено {{ $value }} недореплицированных партиций более 3 минут."

      - alert: KafkaUnderMinIsrPartitions
        expr: kafka_server_replicamanager_underminisrpartitioncount > 0
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "Блокировка записи: размер ISR меньше min.insync.replicas"
          description: "На брокере {{ $labels.instance }} обнаружено {{ $value }} партиций ниже min.insync.replicas. Продюсеры получают NotEnoughReplicasException."

      - alert: KafkaOfflinePartitions
        expr: kafka_controller_kafkacontroller_offlinepartitioncount > 0
        for: 10s
        labels:
          severity: critical
        annotations:
          summary: "Критическая авария: партиции без лидера"
          description: "В кластере обнаружено {{ $value }} оффлайн-партиций. Данные недоступны для чтения и записи."
```

---

### См. также

- **[Гарантии доставки в Apache Kafka](./delivery_guarantees.md)** — семантика доставки сообщений (at-least-once, exactly-once), параметры `acks` и идемпотентность продюсера.
- **[Партиционирование и балансировка](./partitioning_and_balancing.md)** — распределение реплик по брокерам, назначение preferred-лидеров и перераспределение разделов.
- **[Thread Model брокера Apache Kafka](./kafka_broker_thread_model.md)** — детальная работа потоков репликации `ReplicaFetcherThread` и архитектура `ProducePurgatory`.
- **[Мониторинг Apache Kafka](./kafka_for_monitoring.md)** — организация мониторинга брокеров через Prometheus JMX Exporter и метрики надежности.
- **[CLI-утилиты Apache Kafka](./kafka_cli_tools.md)** — справочник команд администрирования топиков, квот и динамических конфигураций.
- **[Траблшутинг Apache Kafka](./kafka_troubleshooting_playbook.md)** — пошаговый плейбук диагностики сбоев брокеров, очередей ввода-вывода и сетевых изоляций.
- **[Тюнинг операционной системы для Apache Kafka](./kafka_os_tuning.md)** — настройка параметров ядра Linux, сетевого стека TCP, дисковых планировщиков и подсистемы виртуальной памяти.
