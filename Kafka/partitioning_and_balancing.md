# Партиционирование и балансировка в Apache Kafka

**Актуально для:** Apache Kafka 3.8.x / 3.9.x / 4.0.x (KRaft)

Партиционирование — фундаментальный архитектурный механизм Apache Kafka, обеспечивающий горизонтальное масштабирование, параллелизм потоковой обработки и физическую изоляцию данных. Балансировка нагрузки распределяет партиции и роли лидеров между брокерами кластера, дисковыми томами (JBOD), а также распределяет потоки сообщений между потребителями внутри консьюмер-групп без простоев и потерь данных.

---

## Определения

- **Партиция (Partition):** Минимальная физическая единица шардирования топика и параллелизма в Kafka. Представляет собой строго упорядоченный, неизменяемый журнал (append-only commit log) записей на диске. Порядок сообщений гарантируется строго в пределах одной партиции.
- **Репликация (Replication):** Механизм отказоустойчивости, создающий идентичные копии партиций на независимых брокерах в соответствии с заданным фактором репликации (Replication Factor, RF).
- **Лидер реплики (Leader):** Узел кластера, обслуживающий все клиентские операции записи и (по умолчанию) чтения для конкретной партиции.
- **Последователь реплики (Follower):** Узел кластера, пассивно реплицирующий лог сообщений с лидера партиции.
- **Синхронные реплики (ISR — In-Sync Replicas):** Множество реплик (включая лидера), которые не отстают от лидера дольше интервала `replica.lag.time.max.ms`. Только реплика из состава ISR может быть выбрана новым лидером при штатном или аварийном переключении.
- **Log End Offset (LEO):** Смещение следующей записи, которая будет добавлена в локальный лог брокера (позиция последней физически записанной репликой строки).
- **High Watermark (HW):** Наивысший офсет записи, успешно зафиксированный всеми репликами из текущего списка ISR. Консьюмеры могут читать сообщения только до значения High Watermark.
- **Partitioner:** Клиентский компонент продюсера, вычисляющий целевую партицию для каждого исходящего сообщения на основе ключа, метаданных топика или внутреннего состояния батчера.
- **Preferred Leader:** Первая реплика в исходном списке распределения (`Replicas`), назначенная контроллером при создании топика или плановом перераспределении. Обеспечивает равномерный баланс CPU и сети между узлами.
- **Preferred Leader Imbalance:** Ситуация, при которой текущий лидер партиции не совпадает с preferred leader (например, вследствие перезапуска брокеров). Приводит к перекосу нагрузки.
- **Rack Awareness:** Механизм распределения реплик партиций с учетом топологии физических серверных стоек (`broker.rack`) для защиты от потери доступности при обесточивании стойки или сбое Top-of-Rack коммутатора.
- **Follower Fetching (KIP-392):** Механизм чтения консьюмерами данных с ближайшей синхронной follower-реплики в пределах одной стойки/зоны доступности (`client.rack`), исключающий лишний межсетевой трафик.
- **Under-Replicated Partitions (URP):** Партиции, у которых текущее количество реплик в ISR меньше установленного фактора репликации (`|ISR| < RF`). Ключевой индикатор деградации кластера.
- **Offline Partitions:** Партиции, у которых отсутствует активный лидер. Запись и чтение таких партиций полностью заблокированы (инцидент наивысшего приоритета P0).
- **Assignor (Partition Assignment Strategy):** Клиентский или серверный алгоритм распределения партиций топика между участниками консьюмер-группы (`Range`, `RoundRobin`, `Sticky`, `CooperativeSticky`).
- **Rebalancing (Ребалансировка группы):** Процесс отзыва и переназначения партиций между консьюмерами при изменении состава группы (добавление, падение воркера) или изменении топологии топиков.
- **Eager Rebalance:** Классический протокол ребалансировки с полной остановкой обработки ("Stop-the-World"): все консьюмеры группы синхронно сбрасывают офсеты, отдают все назначенные партиции и блокируют чтение до завершения синхронизации.
- **Incremental Cooperative Rebalance (KIP-429):** Инкрементальный протокол ребалансировки, при котором отзываются и переназначаются только перемещаемые партиции. Остальные консьюмеры продолжают непрерывную обработку.
- **Static Membership (KIP-345):** Режим работы консьюмера с фиксированным идентификатором `group.instance.id`, позволяющий перезапускать воркер без инициации ребалансировки, если он возвращается в группу в пределах `session.timeout.ms`.
- **KIP-848 (Next-Gen Consumer Group Protocol):** Архитектурный протокол управления группами, в котором логика назначения партиций полностью перенесена на координатор брокера. Устраняет клиентские паузы и циклы SyncGroup/JoinGroup. Generally Available (GA) с Kafka 4.0.
- **Data Skew (Hot Partition):** Неравномерное распределение объемов данных или частоты запросов по партициям топика, приводящее к исчерпанию диска на отдельных брокерах и асимметричному Consumer Lag.
- **Cruise Control:** Автоматизированная система мониторинга, планирования емкости и непрерывной балансировки кластеров Apache Kafka, оптимизирующая распределение реплик и лидеров по CPU, сети и дискам на основе заданных целей (Goals).

---

## Архитектура и основные концепции

### Физическая структура партиции на диске

Партиция в Kafka представляет собой каталог в файловой системе брокера (в одном из путей `log.dirs`), имеющий формат `<topic_name>-<partition_index>`. Внутри каталога лог разбивается на неизменяемые сегменты (Log Segments):

```
/var/lib/kafka/data/orders-0/
├── 00000000000000000000.index               # Индекс смещений (offset → физическая позиция в .log)
├── 00000000000000000000.log                 # Бинарный журнал с записями сообщений
├── 00000000000000000000.timeindex           # Индекс меток времени (timestamp → offset)
├── 00000000000000000000.txnindex           # Индекс транзакций (для Read Committed)
├── 00000000000001502400.log                 # Активный сегмент (куда идет запись)
├── 00000000000001502400.index
├── 00000000000001502400.timeindex
└── leader-epoch-checkpoint                  # Чекпоинт соответствия Leader Epoch и начальных офсетов
```

1. **Сегментация лога:** Сегмент закрывается для записи и ротируется при достижении предельного размера (`segment.bytes`, по умолчанию 1 ГБ) или времени жизни (`segment.ms`, по умолчанию 7 дней). Неактивные сегменты передаются под управление процессам удаления (`cleanup.policy=delete`) или компактификации (`cleanup.policy=compact`).
2. **Разреженные индексы (Sparse Indexes):** Файлы `.index` и `.timeindex` отображаются в виртуальную память через системный вызов `mmap`. Брокер добавляет запись в индекс не для каждого сообщения, а через заданный интервал байт (`index.interval.bytes`, по умолчанию 4 КБ), что минимизирует расход оперативной памяти.
3. **Механизм Zero-Copy:** При передаче данных консьюмерам брокер использует системный вызов `sendfile(2)`, перекачивая страницы сегмента из Page Cache ОС напрямую в сетевой сокет, минуя копирование в user space JVM.
4. **Гарантии порядка:** Строгий хронологический порядок обработки сообщений обеспечивается только в пределах конкретной партиции. Глобальный порядок по всему топику физически невозможен без деградации параллелизма до одной-единственной партиции.

### Стратегии партиционирования на продюсере (Partitioner)

Выбор целевой партиции выполняется на стороне продюсера перед добавлением записи в локальный буфер отправки (`RecordAccumulator`).

```
                              ┌─────────────────────────┐
                              │     ProducerRecord      │
                              └────────────┬────────────┘
                                           │
                                  Есть ключ (key)?
                                   /             \
                             ДА   /               \  НЕТ (key = null)
                                 v                 v
           ┌───────────────────────────────┐   ┌───────────────────────────────┐
           │ MurmurHash2 Partitioner       │   │ Uniform Sticky Partitioner    │
           │ hash(key) & 0x7fffffff % N    │   │ (KIP-480 / BuiltInPartitioner)│
           └──────────────┬────────────────┘   └───────────────┬───────────────┘
                          │                                    │
                          v                                    v
            Фиксированная партиция               Партия заполняется в батч
            для конкретного ключа                до linger.ms / batch.size,
                                                 затем переключается на новую
```

#### 1. Партиционирование по ключу (Key-based)

- **Алгоритм:** По умолчанию клиентская библиотека Kafka использует 32-битный алгоритм MurmurHash2:
  ```java
  Utils.toPositive(Utils.murmur2(keyBytes)) % numPartitions;
  ```
- **Гарантии:** Записи с одинаковым байтовым представлением ключа всегда направляются в одну и ту же партицию при неизменном числе партиций. Это обеспечивает строгую последовательность событий по сущности (например, `order_id`, `device_uuid`).
- **Архитектурный риск:** Если количество уникальных ключей невелико или на один ключ приходится аномальная доля трафика, возникает перекос (Data Skew).

#### 2. Сообщения без ключа (Uniform Sticky Partitioning)

- **История и эволюция:** До Kafka 2.4 сообщения без ключа распределялись по круговому циклу (Round-Robin) на уровне отдельных записей. Это приводило к фрагментации батчей: продюсер отправлял полупустые пакеты во все партиции, создавая высокую сетевую нагрузку и ухудшая сжатие.
- **Sticky Partitioner (KIP-480 / KIP-794):** Продюсер удерживает ("прилипает") выбранную партицию и направляет в нее все сообщения до тех пор, пока батч не заполнится (`batch.size`) или не истечет таймер `linger.ms`. После отправки пакета выбирается следующая доступная партиция.
- **Преимущества:** Увеличение коэффициента сжатия (LZ4/Zstandard), снижение количества сетевых прерываний и системных вызовов ядра, минимальная задержка передачи при высоких нагрузках.

#### 3. Кастомные партиционеры (Custom Partitioner)

Реализация интерфейса `org.apache.kafka.clients.producer.Partitioner` применяется в специализированных сценариях:
- **Tenant Isolation:** Выделение изолированного пула партиций под критический трафик крупных клиентов (VIP-партиции), предотвращающее влияние второстепенных потребителей ресурсов (Noisy Neighbors).
- **Географическое или региональное шардирование:** Направление данных в определенные партиции для оптимизации последующей аналитики.
- **Детерминизм:** Любой кастомный партиционер обязан быть строго детерминированным. Использование генераторов случайных чисел без фиксации состояния разрушает гарантии порядка.

### Проблема Data Skew (Hot Partition)

Data Skew — перекос нагрузки, при котором одна или несколько партиций получают в разы больший объем данных по сравнению с остальными.

**Причины:**
1. **Низкая кардинальность ключа:** Например, шардирование по статусу заказа (`NEW`, `PAID`, `CANCELLED`) или по коду страны, где 90% данных приходятся на один регион.
2. **"Знаменитый ключ" (Celebrity / Heavy-Hitter Key):** Крупный корпоративный клиент, генерирующий миллионы событий в секунду, тогда как остальные создают единицы.
3. **Ошибочный fallback:** Запись пустых или дефолтных значений как строкового ключа (например, `"null"`, `"-1"`, `"unknown"`).

**Следствия для инфраструктуры (SRE/DevOps):**
- Неравномерный износ дисков: том одного брокера заполняется на 100%, требуя экстренной очистки, в то время как остальные диски загружены на 20%.
- Деградация Page Cache брокера: чтение горячей партиции вымывает из кэша данные других топиков, провоцируя дисковые I/O задержки.
- Асимметрия задержек в консьюмер-группе: воркер, читающий горячую партицию, постоянно отстает (высокий Consumer Lag), в то время как соседние воркеры простаивают.

**Методы устранения Data Skew:**
- **Соление ключа (Key Salting):** Добавление псевдослучайного суффикса к ключу для распределения по $K$ корзинам:
  $$\text{salted\_key} = \text{original\_key} + \text{"\_"} + (\text{random}() \pmod K)$$
  Консьюмеры агрегируют результат на втором этапе (Scatter-Gather).
- **Композитные ключи (Compound Keys):** Использование ключей более высокой гранулярности (например, `tenant_id:user_id:device_id` вместо `tenant_id`).
- **Разделение топиков (Dedicated Topics):** Вынос трафика крупного арендатора в отдельный топик с независимым масштабированием партиций.

### Динамическое изменение количества партиций

Количество партиций топика можно увеличить "на лету" с помощью команды `kafka-topics.sh --alter --partitions <count>`. Однако эта операция влечет серьезные архитектурные последствия:

1. **Разрушение порядка ключей:** Kafka не перераспределяет исторические сегменты данных. Старые сообщения остаются в прежних партициях. Так как формула выбора партиции `hash(key) % N` зависит от общего числа $N$, новые сообщения для существующего ключа начнут попадать в другую партицию. В результате сообщения с одним ключом окажутся разнесены по двум партициям, а их сквозной хронологический порядок нарушится.
2. **Невозможность уменьшения:** **Уменьшить количество партиций в Apache Kafka невозможно.** Это привело бы к необходимости слияния логов, пересчета смещений и потере семантики офсетов консьюмеров. Единственный способ сократить число партиций — создать новый топик и перекачать данные (Topic Re-piping / Mirroring).
3. **Планирование емкости:** Количество партиций должно закладываться заранее исходя из прогноза нагрузки на 1–2 года вперед.

### Балансировка на уровне кластера и брокеров

#### Размещение партиций и учет стоек (Rack Awareness)

При создании топика контроллер распределяет реплики партиций между доступными брокерами по детерминированному алгоритму:
1. Выбирается случайный начальный брокер для первой партиции.
2. Последующие лидеры и реплики распределяются циклически (Round-Robin).
3. Если на брокерах настроен параметр `broker.rack`, контроллер принудительно разносит реплики одной и той же партиции по разным физическим стойкам (или зонам доступности). Две реплики одной партиции никогда не будут размещены на узлах с одинаковым идентификатором стойки, если в кластере достаточно уникальных стоек.

#### Перекос лидеров (Leader Skew) и Preferred Leader Election

- **Суть проблемы:** Лидеры партиций несут основную нагрузку по CPU, памяти и сети. При плановом перезапуске брокера (Rolling Restart) лидерство временно переходит к последователям (Followers) на других узлах. После возвращения узла в строй лидерство автоматически не возвращается, если отключена автоматическая ребалансировка. В итоге несколько оставшихся брокеров становятся лидерами подавляющего большинства партиций кластера.
- **Preferred Leader Election:** Контроллер стремится вернуть роль лидера первой реплике в исходном списке распределения.
  - В фоновом режиме процесс управляется параметрами:
    - `auto.leader.rebalance.enable = true` (по умолчанию включено);
    - `leader.imbalance.per.broker.percentage = 1` (допустимый процент дисбаланса, по умолчанию 1%);
    - `leader.imbalance.check.interval.seconds = 300` (интервал проверки дисбаланса).
  - При ручном вмешательстве используется утилита `kafka-leader-election.sh`.

#### Follower Fetching (KIP-392)

Исторически консьюмеры читали данные исключительно с лидеров партиций. Начиная с Kafka 2.4, механизм KIP-392 позволяет консьюмерам запрашивать данные с локальной follower-реплики, находящейся в той же стойке:
- **Настройка брокера:** `broker.rack = rack-1` и `replica.selector.class = org.apache.kafka.common.replica.RackAwareReplicaSelector`.
- **Настройка консьюмера:** `client.rack = rack-1`.
- **Эффект:** Экономия пропускной способности магистральной сети дата-центра и снижение задержек (RTT) при кросс-стоечном взаимодействии.

### Стратегии назначения партиций консьюмерам (Assignors)

Консьюмер-группа обеспечивает совместное чтение топиков: каждая партиция в любой момент времени читается строго одним воркером группы. Распределение партиций определяется стратегией `partition.assignment.strategy`.

| Стратегия (Assignor) | Класс реализации | Алгоритм работы | Достоинства | Недостатки |
| :--- | :--- | :--- | :--- | :--- |
| **RangeAssignor** | `org.apache.kafka.clients.consumer.RangeAssignor` | Топики обрабатываются по отдельности. Партиции делятся на непрерывные диапазоны по числу воркеров. | Простота, сохранение локальности по порядковым номерам. | Сильный перекос нагрузки при подписке на несколько топиков с малым числом партиций (первый воркер получает избыток). |
| **RoundRobinAssignor** | `org.apache.kafka.clients.consumer.RoundRobinAssignor` | Все партиции всех подписанных топиков сортируются и циклически распределяются между воркерами. | Равномерное количество партиций на каждого участника группы. | При любом изменении состава группы перетасовывает абсолютно все партиции, сбрасывая локальные состояния. |
| **StickyAssignor** | `org.apache.kafka.clients.consumer.StickyAssignor` | Стремится к равномерности, минимизируя перемещение уже назначенных партиций при ребалансировках. | Сохраняет стабильность назначений при сбоях; ускоряет возобновление чтения. | Классический Eager-протокол: полная остановка мира (Stop-the-World) во время фазы ребалансировки. |
| **CooperativeStickyAssignor** | `org.apache.kafka.clients.consumer.CooperativeStickyAssignor` | Инкрементальное кооперативное перераспределение (KIP-429). Отзываются только те партиции, которые перемещаются на другие узлы. | **Де-факто production-стандарт (3.x).** Нет глобальной паузы группы; непрерывная обработка стабильных партиций. | Требует единой стратегии у всех консьюмеров группы (несовместима со смешанными группами Eager). |

```
Eager Rebalance (Старый протокол):
Воркер 1: [P0, P1] ────> Сброс всех партиций ───[Пауза Stop-The-World]───> [P0]
Воркер 2: [P2, P3] ────> Сброс всех партиций ───[Пауза Stop-The-World]───> [P1, P2]
Воркер 3: (Новый)  ────> Ожидание назначения ───[Пауза Stop-The-World]───> [P3]

Cooperative Rebalance (KIP-429):
Воркер 1: [P0, P1] ────> Продолжает читать P0; отдает только P1 ─────────> [P0]
Воркер 2: [P2, P3] ────> Продолжает читать P2; отдает только P3 ─────────> [P1, P2]
Воркер 3: (Новый)  ────> Получает P1 и P3 без блокировки P0 и P2 ────────> [P3]
```

### Статическое членство групп (Static Membership — KIP-345)

В средах виртуализации и контейнеризации (Kubernetes, Docker, systemd) плановый перезапуск сервиса приводит к ложным ребалансировкам:
1. Воркер останавливается для обновления или применения конфигурации.
2. Координатор фиксирует уход воркера, запускает ребалансировку группы (Stop-the-World или перетасовку партиций).
3. Через 15 секунд воркер поднимается, подключается к группе и провоцирует вторую волну ребалансировки (Rebalance Storm).

**Решение:** Параметр `group.instance.id`.
- Консьюмер регистрируется с постоянным строковым идентификатором (например, именем пода или hostname сервера).
- При перезапуске координатор брокера держит партиции за данным участником в течение тайм-аута `session.timeout.ms` (например, 45–60 секунд).
- Если воркер переподключается с тем же `group.instance.id` до истечения тайм-аута, он сразу продолжает чтение своих партиций без инициации ребалансировки в кластере.

### Новый протокол консьюмер-групп KIP-848 (Kafka 4.0 GA)

Исторический протокол ребалансировки имел серьезное ограничение: координатор брокера выбирал одного из клиентских консьюмеров группы "лидером группы" (Group Leader). Этот клиент выполнял расчет назначения партиций на своем CPU и отправлял результат обратно на брокер через запрос `SyncGroup`. При тысячах партиций или сотен воркеров это вызывало огромные задержки и таймауты.

**Архитектура KIP-848:**
- Вся логика назначения партиций перенесена на сторону брокера (Group Coordinator).
- Консьюмеры подключаются по легковесному протоколу Heartbeat (`ConsumerGroupHeartbeat`).
- Назначение выполняется инкрементально и прозрачно. Время ребалансировки сокращается с десятков секунд до миллисекунд.
- Активация на клиентах: `group.protocol = consumer`. На брокере: `group.coordinator.new.enable = true` (включено по умолчанию в 4.0).

### Автоматизация балансировки через Cruise Control

Для кластеров размером более 10–15 брокеров и десятков тысяч партиций ручное управление раскладкой через CLI непрактично. Стандартом балансировки bare-metal и виртуальных инфраструктур является Open Source система **Cruise Control** (разработка LinkedIn):

```
┌────────────────────────────────────────────────────────┐
│                     Cruise Control                     │
│  ┌──────────────────┐  ┌─────────────────────────────┐  │
│  │ Anomaly Detector │  │ Goal Optimizer (Hard/Soft)  │  │
│  └────────┬─────────┘  └──────────────┬──────────────┘  │
│           │                           │                 │
│           v                           v                 │
│  ┌───────────────────────────────────────────────────┐  │
│  │         Executor (Throttled Reassignment)         │  │
│  └───────────────────────────┬───────────────────────┘  │
└──────────────────────────────┼──────────────────────────┘
                               │ REST / JMX
                               v
┌────────────────────────────────────────────────────────┐
│                     Kafka Cluster                      │
│     Broker 1              Broker 2          Broker 3   │
│  [CC Metrics Rep.]   [CC Metrics Rep.]  [CC Metrics...]│
└────────────────────────────────────────────────────────┘
```

- **Cruise Control Metrics Reporter:** Java-агент или плагин метрик, разворачиваемый на каждом брокере Kafka, собирающий поминутную загрузку CPU, входящую/исходящую сеть и занятость дисков на уровне каждой партиции и пишущий их во внутренний топик `__CruiseControlMetrics`.
- **Hard Goals (Строгие цели):** Правила, нарушение которых категорически запрещено:
  - `RackAwareGoal` — гарантия разнесения реплик по стойкам.
  - `MinTopicLeadersPerBrokerGoal` — наличие лидеров топика минимум на одном брокере.
  - `ReplicaCapacityGoal` — непревышение абсолютного лимита реплик на брокер.
- **Soft Goals (Мягкие цели):** Оптимизационные правила, балансируемые алгоритмом:
  - `CpuCapacityGoal` — удержание загрузки CPU брокеров ниже порогового значения (например, 70%).
  - `DiskCapacityGoal` — предотвращение переполнения дисковых разделов.
  - `NetworkInboundCapacityGoal` / `NetworkOutboundCapacityGoal` — выравнивание сетевого ввода-вывода.
- **Self-Healing:** Автоматическое обнаружение сбойных брокеров или «битых» дисков в JBOD и перемещение реплик на здоровые узлы без вмешательства дежурного инженера.

---

## Практические сценарии и конфигурация

### Сценарий 1: Расчет оптимального количества партиций и лимиты кластера

При проектировании топиков расчет числа партиций опирается на целевую пропускную способность (Throughput) продюсеров и консьюмеров.

#### Формула расчета
$$P = \max\left(\left\lceil \frac{T_{\text{target}}}{T_{\text{producer\_partition}}} \right\rceil, \left\lceil \frac{T_{\text{target}}}{T_{\text{consumer\_partition}}} \right\rceil\right)$$

Где:
- $T_{\text{target}}$ — суммарный целевой поток данных топика (МБ/с).
- $T_{\text{producer\_partition}}$ — максимальная скорость записи в одну партицию с учетом сети, батчинга и сжатия (на современных серверах с NVMe составляет ~10–25 МБ/с при `acks=all`).
- $T_{\text{consumer\_partition}}$ — скорость обработки данных одним потоком консьюмера (сильно зависит от бизнес-логики; при взаимодействии с БД или сторонними API часто составляет 2–5 МБ/с).

#### Практический расчет
- Входящий поток: $T_{\text{target}} = 100\text{ МБ/с}$.
- Производительность записи в партицию: $T_{\text{producer\_partition}} = 20\text{ МБ/с}$.
  $$P_{\text{prod}} = \frac{100}{20} = 5\text{ партиций}$$
- Производительность бизнес-консьюмера: $T_{\text{consumer\_partition}} = 4\text{ МБ/с}$.
  $$P_{\text{cons}} = \frac{100}{4} = 25\text{ партиций}$$
- **Итого:** Топику требуется не менее **25 партиций**, чтобы консьюмер-группа из 25 воркеров успевала обрабатывать входящий трафик без накопления лага.

#### Лимиты и сайзинг в KRaft
- На одном физическом брокере с дисками NVMe и 64–128 ГБ RAM рекомендуется держать **до 2 000–4 000 партиций** (включая реплики).
- В архитектуре KRaft метаданные обрабатываются быстрее, чем в старом ZooKeeper, но контроллер по-прежнему держит структуры партиций в памяти. Общий лимит на кластер KRaft составляет до 100 000–200 000 партиций при наличии выделенного пула узлов контроллеров (Dedicated Controllers).

### Сценарий 2: Перераспределение партиций при расширении кластера (`kafka-reassign-partitions.sh`)

При вводе новых брокеров в существующий кластер партиции автоматически не мигрируют. Для балансировки применяется утилита `kafka-reassign-partitions.sh`.

#### Пошаговый production-регламент

```bash
# ШАГ 1: Подготовка списка топиков для миграции
cat << 'EOF' > /tmp/topics-move.json
{
  "topics": [
    {"topic": "orders"},
    {"topic": "payments"}
  ],
  "version": 1
}
EOF

# ШАГ 2: Генерация плана миграции на расширенный пул брокеров (узлы 1, 2, 3, 4)
kafka-reassign-partitions.sh --bootstrap-server localhost:9092 \
    --topics-to-move-json-file /tmp/topics-move.json \
    --broker-list "1,2,3,4" \
    --generate > /tmp/reassign-raw.json

# Вывод содержит две секции:
# 1. "Current partition replica assignment" — ОБЯЗАТЕЛЬНО сохраните в /tmp/rollback-plan.json!
# 2. "Proposed partition reassignment configuration" — сохраните в /tmp/plan.json.

# Извлечение предлагаемого плана через jq
jq -r '.proposed' /tmp/reassign-raw.json > /tmp/plan.json
# Извлечение плана отката
jq -r '.current' /tmp/reassign-raw.json > /tmp/rollback-plan.json
```

```bash
# ШАГ 3: Запуск миграции С ОБЯЗАТЕЛЬНЫМ ТРОТТЛИНГОМ (Throttle)
# Лимит 50000000 байт/сек = 50 МБ/сек (защищает сеть репликации от деградации)
kafka-reassign-partitions.sh --bootstrap-server localhost:9092 \
    --reassignment-json-file /tmp/plan.json \
    --execute \
    --throttle 50000000
# → Current partition replica assignment
# → ...
# → Save this to use as the --reassignment-json-file option during rollback
# → Successfully started partition reassignments for orders-0, orders-1, payments-0...
```

```bash
# ШАГ 4: Мониторинг процесса перемещения
kafka-reassign-partitions.sh --bootstrap-server localhost:9092 \
    --reassignment-json-file /tmp/plan.json \
    --verify
# → Status of partition reassignment:
# → Reassignment of partition orders-0 is completed.
# → Reassignment of partition orders-1 is in progress.
# → Reassignment of partition payments-0 is completed.
# → Clearing broker-level throttles...
# → Verification is still in progress.
```

```bash
# ШАГ 5: Финальная валидация и СНЯТИЕ ТРОТТЛИНГА
# Повторять до появления статуса "Verification completed successfully"
kafka-reassign-partitions.sh --bootstrap-server localhost:9092 \
    --reassignment-json-file /tmp/plan.json \
    --verify
# → Status of partition reassignment:
# → Reassignment of partition orders-0 is completed.
# → Reassignment of partition orders-1 is completed.
# → Reassignment of partition payments-0 is completed.
# → Clearing broker-level throttles...
# → Clearing topic-level throttles...
# → Verification completed successfully.
```

> [!IMPORTANT]
> Если администратор прервал процесс или забыл выполнить команду с ключом `--verify` после окончания переноса, установленный лимит пропускной способности репликации (`leader.replication.throttled.rate` / `follower.replication.throttled.rate`) останется активным в метаданных брокеров! Это приведет к хроническому росту `UnderReplicatedPartitions`.

#### Аварийное снятие забытого троттлинга вручную
Если оригинальный JSON-план утерян, а брокеры продолжают троттлить репликацию:

```bash
# 1. Проверить наличие динамических квот на брокере 1
kafka-configs.sh --bootstrap-server localhost:9092 \
    --entity-type brokers --entity-name 1 --describe
# → Dynamic configs for broker 1 are:
# →   leader.replication.throttled.rate=50000000 sensitive=false synonyms={}
# →   follower.replication.throttled.rate=50000000 sensitive=false synonyms={}

# 2. Удалить брокерные ограничения
kafka-configs.sh --bootstrap-server localhost:9092 \
    --entity-type brokers --entity-name 1 \
    --alter --delete-config leader.replication.throttled.rate,follower.replication.throttled.rate
# → Completed updating config for broker: 1.

# 3. Удалить списки троттлируемых реплик с топика
kafka-configs.sh --bootstrap-server localhost:9092 \
    --entity-type topics --entity-name orders \
    --alter --delete-config leader.replication.throttled.replicas,follower.replication.throttled.replicas
# → Completed updating config for topic: orders.
```

### Сценарий 3: Междисковая балансировка внутри брокера (JBOD Intra-Broker Balancing)

В production-конфигурациях с несколькими дисками JBOD (`log.dirs=/mnt/disk1/kafka,/mnt/disk2/kafka`) один диск может переполниться из-за тяжелой партиции, в то время как соседний диск пуст. Начиная с KIP-113, Kafka поддерживает перемещение партиций между каталогами одного и того же брокера без отправки данных по сети:

```bash
# Подготовка плана с явным указанием путей в log_dirs
cat << 'EOF' > /tmp/jbod-move.json
{
  "version": 1,
  "partitions": [
    {
      "topic": "orders",
      "partition": 0,
      "replicas": [1, 2, 3],
      "log_dirs": ["/mnt/disk2/kafka", "any", "any"]
    }
  ]
}
EOF

# Запуск перемещения на диске брокера 1
kafka-reassign-partitions.sh --bootstrap-server localhost:9092 \
    --reassignment-json-file /tmp/jbod-move.json \
    --execute

# Проверка прогресса
kafka-reassign-partitions.sh --bootstrap-server localhost:9092 \
    --reassignment-json-file /tmp/jbod-move.json \
    --verify
# → Reassignment of partition orders-0 is completed.
```

### Сценарий 4: Бесшовный деплой консьюмеров без Rebalance Storm

Для предотвращения каскадных ребалансировок при перезапуске консьюмеров (в Kubernetes StatefulSet или под управлением systemd) настраивается комбинация **Static Membership** и **Cooperative Sticky Assignor**:

```ini
# consumer.properties
bootstrap.servers=kafka-node-01:9092,kafka-node-02:9092,kafka-node-03:9092
group.id=orders-processor-group

# 1. Фиксация статического идентификатора воркера (уникального для каждого пода/сервера)
# В K8s: передается через Downward API из metadata.name
group.instance.id=orders-processor-pod-0

# 2. Инкрементальная кооперативная стратегия
partition.assignment.strategy=org.apache.kafka.clients.consumer.CooperativeStickyAssignor

# 3. Тайм-ауты обнаружения сбоя
# session.timeout.ms должен с запасом покрывать время рестарта пода (например, 45 секунд)
session.timeout.ms=45000
heartbeat.interval.ms=15000

# 4. Защита от долгой обработки бизнес-логики
max.poll.interval.ms=300000
max.poll.records=500
```

При плановом перезапуске пода координатор брокера ждет 45 секунд. Если под поднимается и отправляет heartbeat в течение этого окна, партиции остаются закрепленными за ним, а остальные консьюмеры группы работают непрерывно.

### Сценарий 5: Управление Preferred Leader Election

Если в результате сетевых сбоев или планового обслуживания брокеров возник дисбаланс лидеров:

```bash
# 1. Проверка текущего дисбаланса лидеров
kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic orders
# → Topic: orders	Partition: 0	Leader: 2	Replicas: 1,2,3	Isr: 1,2,3
# Обратите внимание: реплика 1 является preferred leader (стоит первой в Replicas), но лидером стал брокер 2.

# 2. Принудительный запуск выборов Preferred Leader для всех партиций
kafka-leader-election.sh --bootstrap-server localhost:9092 \
    --election-type PREFERRED \
    --all-topic-partitions
# → Successfully started leader election for partitions orders-0, orders-1, payments-0...

# 3. Валидация выравнивания
kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic orders
# → Topic: orders	Partition: 0	Leader: 1	Replicas: 1,2,3	Isr: 1,2,3
```

### Сценарий 6: Production-профили конфигурации

#### 1. Профиль брокера (`server.properties` / Bare-metal)
```properties
# Идентификатор узла и слушатели
node.id=1
process.roles=broker
listeners=PLAINTEXT://10.0.10.11:9092
advertised.listeners=PLAINTEXT://10.0.10.11:9092

# Учет топологии стоек
broker.rack=rack-dc1-row2

# Автоматическая балансировка preferred leaders
auto.leader.rebalance.enable=true
leader.imbalance.per.broker.percentage=1
leader.imbalance.check.interval.seconds=300

# Защита от потерь данных (строгий запрет грязных выборов)
unclean.leader.election.enable=false

# Настройки топиков по умолчанию
default.replication.factor=3
num.partitions=12
min.insync.replicas=2

# Таймаут выбывания из ISR (адаптирован под локальную сеть DC)
replica.lag.time.max.ms=30000
num.replica.fetchers=4

# Поддержка чтения с ближайшей реплики (KIP-392)
replica.selector.class=org.apache.kafka.common.replica.RackAwareReplicaSelector

# Дисковая подсистема (JBOD)
log.dirs=/data/kafka-disk1,/data/kafka-disk2
num.recovery.threads.per.data.dir=4
```

#### 2. Профиль продюсера (`producer.properties`)
```properties
bootstrap.servers=10.0.10.11:9092,10.0.10.12:9092,10.0.10.13:9092

# Гарантия доставки без дубликатов
acks=all
enable.idempotence=true
max.in.flight.requests.per.connection=5

# Оптимизация Sticky Partitioner и пакетирования
compression.type=lz4
batch.size=65536
linger.ms=20

# Таймауты отправки
delivery.timeout.ms=120000
request.timeout.ms=30000
```

#### 3. Настройки ядра Linux (`/etc/sysctl.d/99-kafka-balancing.conf`)
```ini
# Запрет вытеснения страниц Kafka в swap
vm.swappiness = 1

# Фоновый сброс грязных страниц для исключения блокировок дисковой подсистемы
vm.dirty_background_ratio = 5
vm.dirty_ratio = 10

# Расширение таблиц дескрипторов и областей памяти mmap
fs.file-max = 1000000
vm.max_map_count = 1048576

# Сетевые буферы передачи
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
```

---

## Операции и команды

Сводный справочник эксплуатационных команд администратора кластера Apache Kafka:

| Операция | Команда | Назначение |
| :--- | :--- | :--- |
| **Создание топика с явной раскладкой** | `kafka-topics.sh --bootstrap-server localhost:9092 --create --topic orders --replica-assignment 1:2:3,2:3:1,3:1:2` | Ручное размещение реплик по брокерам в обход стандартного алгоритма. |
| **Увеличение числа партиций** | `kafka-topics.sh --bootstrap-server localhost:9092 --alter --topic orders --partitions 24` | Увеличение пропускной способности (партиции 12..23 будут созданы на доступных узлах). |
| **Проверка партиций с нарушением ISR** | `kafka-topics.sh --bootstrap-server localhost:9092 --describe --under-replicated-partitions` | Быстрый поиск деградировавших партиций кластера. |
| **Проверка партиций без лидеров (P0)** | `kafka-topics.sh --bootstrap-server localhost:9092 --describe --unavailable-partitions` | Поиск заблокированных партиций, недоступных для записи и чтения. |
| **Инспекция занятости дисков брокеров** | `kafka-log-dirs.sh --bootstrap-server localhost:9092 --describe --broker-list 1,2,3 --topic-list orders` | Вывод размера каждой партиции на каждом дисковом каталоге брокеров. |
| **Запуск Preferred Leader Election** | `kafka-leader-election.sh --bootstrap-server localhost:9092 --election-type PREFERRED --all-topic-partitions` | Возврат лидеров на исходные брокеры для устранения дисбаланса. |
| **Проверка статуса ребалансировки партиций** | `kafka-reassign-partitions.sh --bootstrap-server localhost:9092 --reassignment-json-file /tmp/plan.json --verify` | Контроль завершения миграции и снятие динамического троттлинга. |
| **Отмена зависшей миграции** | `kafka-reassign-partitions.sh --bootstrap-server localhost:9092 --reassignment-json-file /tmp/plan.json --cancel` | Аварийная остановка перемещения партиций. |
| **Проверка состава консьюмер-группы** | `kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group orders-processor --state` | Проверка состояния группы (`Stable`, `PreparingRebalance`, `CompletingRebalance`). |
| **Инспекция участников и распределения** | `kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group orders-processor --members --verbose` | Проверка соответствия `CLIENT-ID`, `HOST`, `INSTANCE-ID` и назначенных партиций. |

### Примеры выполнения базовых команд с валидацией

```bash
# 1. Инспекция распределения партиций топика orders
kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic orders
# → Topic: orders	TopicId: 4L6g3nShT-eMCtK--X86sw	PartitionCount: 3	ReplicationFactor: 3	Configs: min.insync.replicas=2
# → 	Topic: orders	Partition: 0	Leader: 1	Replicas: 1,2,3	Isr: 1,2,3
# → 	Topic: orders	Partition: 1	Leader: 2	Replicas: 2,3,1	Isr: 2,3,1
# → 	Topic: orders	Partition: 2	Leader: 3	Replicas: 3,1,2	Isr: 3,1,2

# 2. Инспекция дискового пространства через kafka-log-dirs.sh
kafka-log-dirs.sh --bootstrap-server localhost:9092 --describe --broker-list 1 --topic-list orders | jq .
# → {
# →   "brokers": [
# →     {
# →       "broker": 1,
# →       "logDirs": [
# →         {
# →           "logDir": "/data/kafka-disk1",
# →           "partitions": [
# →             {
# →               "partition": "orders-0",
# →               "size": 104857600,
# →               "offsetLag": 0,
# →               "isFuture": false
# →             }
# →           ]
# →         }
# →       ]
# →     }
# →   ]
# → }

# 3. Инспекция состава консьюмер-группы
kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group orders-processor --members
# → GROUP            MEMBER-ID                     CLIENT-ID    HOST         INSTANCE-ID                 ASSIGNMENT
# → orders-processor pod-0-848f-4a21-99ef          client-pod-0 /10.244.1.15 orders-processor-pod-0     orders(0)
# → orders-processor pod-1-712a-4c33-88bb          client-pod-1 /10.244.2.19 orders-processor-pod-1     orders(1,2)
```

---

## Диагностика и устранение неполадок

| Проблема / Симптом | Первопричина | Диагностика (Linux / Kafka / JMX) | Решение и устранение |
| :--- | :--- | :--- | :--- |
| **Постоянный `UnderReplicatedPartitions > 0` после переезда партиций** | Не сняты квоты троттлинга (`leader.replication.throttled.rate`), либо пропущен шаг `--verify`. | `kafka-configs.sh --bootstrap-server localhost:9092 --entity-type brokers --entity-name 1 --describe`<br>JMX: `kafka.server:type=FetcherLagMetrics,name=ConsumerLag` | 1. Выполнить `kafka-reassign-partitions.sh --verify` с исходным JSON-файлом.<br>2. При утере файла снять квоты вручную через `kafka-configs.sh --alter --delete-config ...`. |
| **Дисбаланс лидеров (Leader Skew): один брокер нагружен по CPU/Сети на 90%, остальные на 15%** | Перезапуск узлов без возврата preferred leader; параметр `auto.leader.rebalance.enable = false`. | `kafka-topics.sh --describe` (сравнить поле `Leader` и первую цифру в `Replicas`).<br>JMX: `PreferredReplicaImbalanceCount` | 1. Запустить `kafka-leader-election.sh --election-type PREFERRED --all-topic-partitions`.<br>2. Включить в конфигурации `auto.leader.rebalance.enable=true`. |
| **Шторм ребалансировок (Rebalance Storm): консьюмеры зависают, лаг растет лавинообразно** | 1. Время обработки батча превышает `max.poll.interval.ms`.<br>2. Долгие Full GC паузы в JVM консьюмера.<br>3. Частое падение подов без Static Membership. | 1. Логи консьюмера: поиск `CommitFailedException` или `Attempt to heartbeat failed`.<br>2. `jstat -gcutil <pid> 1000`<br>3. `kafka-consumer-groups.sh --describe --state` | 1. Уменьшить `max.poll.records` (например, с 500 до 50).<br>2. Увеличить `max.poll.interval.ms`.<br>3. Перевести группу на `CooperativeStickyAssignor`.<br>4. Включить `group.instance.id`. |
| **Hot Partition: диск одного брокера переполнен, на остальных свободно 70%** | Data Skew из-за низкой кардинальности ключа или "celebrity key". | 1. `du -sh /data/kafka/* \| sort -rh \| head -n 10`<br>2. `kafka-dump-log.sh --files <segment>.log --print-data-log \| head -n 30` (анализ ключей). | 1. Внедрить соление ключей (Key Salting) на стороне продюсера.<br>2. Для сообщений без ключа убедиться в работе Sticky Partitioner.<br>3. Переместить тяжелую партицию на более свободный узел через `kafka-reassign-partitions.sh`. |
| **Миграция партиций зависает: прогресс не меняется часами** | 1. Слишком жесткий throttle (например, 1 МБ/с для топика объемом 2 ТБ).<br>2. Сбой брокера-получателя.<br>3. Деградация дискового ввода-вывода (I/O). | 1. `kafka-reassign-partitions.sh --verify`<br>2. `iostat -xz 1` (проверить %util дисков).<br>3. JMX `ReplicaFetcherManager:name=BytesPerSec` | 1. Увеличить лимит скорости: повторно запустить команду `--execute` с повышенным `--throttle 100000000` (100 МБ/с).<br>2. В критической ситуации отменить миграцию ключом `--cancel`. |
| **Ошибки клиентов `NotLeaderForPartitionException`** | Метаданные на клиенте устарели во время переключения лидера. | Логи продюсера/консьюмера; частота смены лидеров в `server.log`. | Клиентский драйвер обязан иметь корректные настройки повторов: `retries = 2147483647` (по умолчанию с 2.7) и `retry.backoff.ms = 100`. |
| **Консьюмеры находятся в статусе `IDLE` и ничего не читают** | Число активных воркеров в консьюмер-группе превышает количество партиций топика. | `kafka-consumer-groups.sh --describe --group <group>` (у части воркеров пустое поле `PARTITION`). | 1. Kafka не может распределить одну партицию на двух воркеров одной группы.<br>2. Увеличить количество партиций (`kafka-topics.sh --alter`), либо сократить число воркеров. |
| **Кворум контроллеров KRaft перегружен метаданными (Over-Partitioning)** | Создано более 6 000–8 000 партиций на брокер; взрывной рост задержек при смене лидеров. | JMX: `kafka.controller:type=KafkaController,name=ActiveControllerCount`<br>`kafka.network:type=RequestChannel,name=RequestQueueTimeMs` | 1. Объединить мелкодисперсные топики.<br>2. Удалить неиспользуемые топики.<br>3. Добавить новые физические брокеры и распределить нагрузку.<br>4. Выделить контроллеры KRaft на выделенные серверы (Dedicated Controller Nodes). |

---

## Лучшие практики (Best Practices)

### Архитектура топиков и партиций
- **Фактор репликации:** Для всех production-топиков строго `replication.factor = 3` и `min.insync.replicas = 2` при обязательном использовании `acks = all` на продюсерах.
- **Число партиций:** Рассчитывайте число партиций заранее с запасом на рост нагрузки на 1–2 года. Не создавайте топики с 1–2 партициями для высоконагруженных сервисов, так как последующее расширение нарушит порядок существующих ключей.
- **Запрет автосоздания топиков:** Обязательно выставляйте на брокерах `auto.create.topics.enable = false`. Топики должны создаваться строго через GitOps / автоматизацию с проверенными параметрами партиционирования.
- **Предотвращение Over-Partitioning:** Держите суммарное число партиций на брокер в пределах **1 000–3 000** (максимум до 4 000 на высокопроизводительных серверах).

### Надежность и непрерывность балансировки
- **Автоматический возврат лидеров:** Всегда держите включенным `auto.leader.rebalance.enable = true` с порогом дисбаланса `leader.imbalance.per.broker.percentage = 1`.
- **Защита от потери данных:** Всегда выставляйте `unclean.leader.election.enable = false`. Ни при каких обстоятельствах не позволяйте несинхронизированным репликам становиться лидерами в production.
- **Регламент перемещения партиций:**
  1. Никогда не запускайте `kafka-reassign-partitions.sh` без явного указания `--throttle`. Рассчитывайте throttle как не более 20–30% от свободной полосы сетевого интерфейса и диска.
  2. Всегда сохраняйте блок `Current partition replica assignment` в файл отката перед стартом.
  3. Всегда доводите процедуру до конца вызовом `--verify` для очистки динамических квот троттлинга.
- **Rack Awareness:** Настраивайте `broker.rack` на всех узлах bare-metal и виртуальных машин. Совместно с `replica.selector.class = org.apache.kafka.common.replica.RackAwareReplicaSelector` это гарантирует выживание при отказе стойки и экономит трафик при Follower Fetching.

### Конфигурация консьюмеров
- **Стратегия назначения:** Используйте исключительно `CooperativeStickyAssignor` на Kafka 3.x для предотвращения пауз Stop-the-World. При переходе на Kafka 4.0 планируйте активацию KIP-848 (`group.protocol = consumer`).
- **Статическое членство:** Для всех сервисов, разворачиваемых в Kubernetes (StatefulSet) или перезапускаемых по расписанию, настраивайте `group.instance.id` с запасом `session.timeout.ms = 45000`.
- **Баланс времени обработки:** Значение `max.poll.interval.ms` (по умолчанию 300 000 мс / 5 минут) должно как минимум в 3–5 раз превышать максимальное время обработки пакета из `max.poll.records`.

### Чеклист метрик мониторинга и алертинга

| Метрика (JMX / Prometheus) | Описание | Нормальное значение | Порог алерта |
| :--- | :--- | :--- | :--- |
| `kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions` | Количество партиций с неполным ISR | `0` | `> 0` (Severity: P1 / Critical при удержании > 3 мин) |
| `kafka.controller:type=KafkaController,name=OfflinePartitionsCount` | Количество партиций без лидера | `0` | `> 0` (Severity: P0 / Blocker немедленно) |
| `kafka.controller:type=KafkaController,name=PreferredReplicaImbalanceCount` | Количество партиций с перекосом preferred leader | `0` | `> 0` (Severity: P2 при удержании > 15 мин) |
| `kafka.server:type=ReplicaFetcherManager,name=MaxLag,clientId=Replica` | Максимальный лаг отставания реплик от лидера | `< 1000` сообщений | Рост метрики указывает на проблемы с диском или сетью follower |
| `kafka.consumer:type=consumer-coordinator-metrics,name=rebalance-latency-avg` | Средняя длительность ребалансировки группы | `< 1000` мс | `> 5000` мс (указывает на Eager Stop-the-world) |
| `kafka.consumer:type=consumer-coordinator-metrics,name=rebalance-rate-per-hour` | Частота ребалансировок в час | `0` | `> 3` (признак шторма ребалансировок) |

---

## Дополнительная информация

### См. также

- **[Обзор Apache Kafka](./kafka_overview.md)** — фундаментальная архитектура распределенного журнала, контроллеров KRaft и семантики сообщений.
- **[CLI-инструменты Kafka](./kafka_cli_tools.md)** — практическое руководство по консольным утилитам администрирования (`kafka-topics.sh`, `kafka-reassign-partitions.sh`, `kafka-configs.sh`).
- **[ISR и репликация в Kafka](./kafka_isr_replication.md)** — глубокий разбор механизмов High Watermark, LEO, сжатия и расширения ISR, расчета доступности.
- **[OS тюнинг для Apache Kafka](./kafka_os_tuning.md)** — низкоуровневая оптимизация параметров ядра Linux, виртуальной памяти, Page Cache и сетевого стека.
- **[Troubleshooting Playbook для Apache Kafka](./kafka_troubleshooting_playbook.md)** — деревья решений и регламенты реагирования на инциденты деградации кластера.
- **[Kafka для мониторинга](./kafka_for_monitoring.md)** — сбор метрик через Prometheus JMX Exporter, настройка дашбордов Grafana и правил оповещения.
- **[Capacity Planning и Disaster Recovery](./kafka_capacity_dr.md)** — сайзинг кластеров, расчет дисковой емкости и сценарии аварийного восстановления.
- **[Strimzi Kafka Operator](./strimzi_kafka_operator.md)** — управление кластерами Kafka и автоматическая ребалансировка через Cruise Control в Kubernetes.

### Внешние инструменты экосистемы

- **[LinkedIn Cruise Control](https://github.com/linkedin/cruise-control)** — Open Source решение для автоматического мониторинга рабочей нагрузки, балансировки дисков JBOD и выравнивания сетевых ресурсов кластеров Kafka.
- **[Cruise Control UI](https://github.com/linkedin/cruise-control-ui)** — веб-интерфейс для визуализации предложенных планов ребалансировки и состояния целей (Goals).
- **[AKHQ](https://akhq.io/)** — Open Source веб-интерфейс для мониторинга топиков, инспекции данных в партициях, анализа потребительских групп и лагов.
- **[Kafka UI (Provectus)](https://github.com/provectus/kafka-ui)** — быстрый легковесный дашборд для администрирования кластеров Kafka, управления топиками и квотами.
