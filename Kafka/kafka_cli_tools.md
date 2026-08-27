# CLI-инструменты для работы с Apache Kafka

Для взаимодействия с Apache Kafka из командной строки используются стандартные утилиты, входящие в дистрибутив, а также сторонние решения, такие как `kcat`, `rpk` и `kafkactl`. Они позволяют управлять топиками, читать и отправлять сообщения, диагностировать состояние кластера, перераспределять партиции и проводить нагрузочные тесты. Теоретические основы описанных операций — [Обзор Apache Kafka](./kafka_overview.md).

## Определения

- **Kafka CLI (Standard)**: Набор shell-скриптов (оберток над Java-приложениями), поставляемых в составе дистрибутива Apache Kafka в каталоге `bin/`. Требуют наличия JVM; начиная с Kafka 4.0 — JVM версии 17 или выше (KIP-750, KIP-1013). Для Windows существуют аналоги с расширением `.bat`. Основные утилиты: `kafka-topics.sh`, `kafka-console-consumer.sh`, `kafka-consumer-groups.sh`, `kafka-configs.sh`.
- **kcat (ранее kafkacat)**: Универсальный не-JVM инструмент (на базе `librdkafka`) для работы с Kafka, «netcat для Kafka». Идеален для отладки, чтения данных и интеграции в shell-пайплайны. Переименован из `kafkacat` в августе 2021 года по требованию Apache Software Foundation (торговая марка); функционально это тот же инструмент. Актуальная линейка версий — 1.7.x.
- **rpk (Redpanda CLI)**: Современный, быстрый инструмент на Go, распространяется как статический бинарный файл без зависимостей. Несмотря на то, что это основной CLI для Redpanda, он совместим с Apache Kafka в части стандартных операций (топики, группы, ACL) и часто используется как более удобная альтернатива стандартным скриптам. Часть команд работает только с Redpanda (см. «Ограничения»).
- **kafkactl**: Специализированный CLI от Device Insight с интерфейсом в стиле `kubectl` (`get`, `describe`, `alter`, `create`, `delete`), ориентированный на управление множеством кластеров через контексты. Активно развивается, поддерживает Avro, Protobuf, Schema Registry, работу с кластерами внутри Kubernetes и управление SCRAM-пользователями.
- **Confluent CLI**: Фирменный инструмент для работы с Confluent Cloud и Confluent Platform. Управляет окружениями, кластерами и API-ключами Confluent Cloud; локальные данные при этом читаются теми же стандартными утилитами или `kcat`.
- **librdkafka**: C-библиотека клиента Kafka, на которой построены `kcat` и клиенты многих языков (Python `confluent-kafka`, Go `franz-go`/`sarama` частично). Все её параметры конфигурации можно передать в `kcat` через флаг `-X`.

## Основные концепции

### Сравнение инструментов

| Критерий | Стандартные утилиты | kcat | rpk | kafkactl |
| :--- | :--- | :--- | :--- | :--- |
| **Язык / Зависимости** | Java (JVM 17+ для Kafka 4.x) | C (librdkafka) | Go (статический бинарный файл) | Go (статический бинарный файл) |
| **Стиль команд** | Множество скриптов | Однобуквенные флаги (`-C`, `-P`, `-L`) | Глагол + Существительное (`rpk topic list`) | Интерфейс `kubectl` (`get topics`) |
| **Управление кластерами** | Флаги в каждой команде | Флаги командной строки, файл конфигурации (`-F`) | Профили (`rpk profile`) | Контексты (YAML-конфигурация) |
| **Администрирование** | Максимальное (ACL, квоты, ребалансировка, логи, метаданные KRaft) | Только данные и метаданные (`-L`) | Высокое (Topic, Group, ACL) | Среднее-высокое (Topic, Group, ACL, Users, Brokers) |
| **Чтение/запись данных** | `kafka-console-producer/consumer.sh` | Лучший в классе (форматы, фильтры, пайплайны) | Хорошие (`rpk topic produce/consume`) | Хорошие (+ Avro/Protobuf) |
| **Скорость старта** | Медленно (запуск JVM, секунды) | Мгновенно | Мгновенно | Мгновенно |

Вывод из таблицы: инструменты не конкурируют, а дополняют друг друга — типичный SRE использует `rpk`/`kafkactl` для повседневных операций, `kcat` для работы с данными и пайплайнами, а стандартные утилиты — для задач, недоступных другим инструментам (ребалансировка партиций, дамп логов, квоты на уровне брокеров).

### Подключение и аутентификация

Все стандартные утилиты подключаются к брокерам через флаг `--bootstrap-server host:port`. История аргументов важна для понимания легаси-скриптов:

- До Kafka 2.2 административные утилиты принимали `--zookeeper zookeeper:2181` и читали метаданные напрямую из ZooKeeper, минуя механизмы безопасности Kafka.
- С Kafka 2.2 аргумент `--zookeeper` объявлен устаревшим (KIP-377: утилиты переведены на AdminClient).
- В современных версиях (линейки 3.x–4.x) аргумент `--zookeeper` и сам ZooKeeper полностью удалены: любая утилита работает **только** через `--bootstrap-server`. Скрипты со `--zookeeper` требуют переписывания.

Для кластера с включённой безопасностью (SASL/TLS) каждой утилите дополнительно передается файл конфигурации клиента через `--command-config`. Минимальный пример `client.properties` для SASL_SSL с механизмом SCRAM:

```properties
# Протокол соединения: SASL поверх TLS
security.protocol=SASL_SSL
# Механизм аутентификации (SCRAM-SHA-512 — рекомендуемый; PLAIN допустим за TLS)
sasl.mechanism=SCRAM-SHA-512
# JAAS-строка с учетными данными (логин/пароль пользователя)
sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required \
    username="alice" \
    password="alice-secret";
# Доверенное хранилище для проверки сертификата брокера
ssl.truststore.location=/etc/kafka/truststore.jks
ssl.truststore.password=changeit
```

```bash
# Любая административная утилита принимает этот файл одинаково
kafka-topics.sh --bootstrap-server broker1:9093 \
    --command-config client.properties \
    --list
```

Применение того же файла в `kcat` — через параметры librdkafka (эквиваленты тех же свойств):

```bash
# Каждый параметр security.protocol/sasl.* передается через -X
kcat -b broker1:9093 -t orders -C -e \
    -X security.protocol=SASL_SSL \
    -X sasl.mechanisms=SCRAM-SHA-512 \
    -X sasl.username=alice \
    -X sasl.password=alice-secret \
    -X ssl.ca.location=/etc/kafka/ca.pem
```

Чтобы не набирать длинные наборы `-X`, `kcat` поддерживает конфигурационные файлы: флаг `-F <file>`, переменная окружения `KCAT_CONFIG` либо файл по умолчанию `~/.config/kcat.conf`.

### Контексты и профили

Современные инструменты (`kafkactl`, `rpk`, `confluent-cli`) используют концепцию **контекстов** или **профилей**. Это позволяет переключаться между разными кластерами (например, `dev`, `staging`, `prod`) без ручного ввода адресов брокеров и путей к сертификатам.

**Преимущества профилей:**

1. **Безопасность**: Секреты хранятся в конфигурационных файлах с ограниченными правами или переменных окружения, а не в истории shell.
2. **Скорость**: Отсутствие необходимости в длинных флагах `--bootstrap-server` и `--command-config`.
3. **Единообразие**: Команды выглядят одинаково для любого окружения; снижается риск выполнить деструктивную операцию не на том кластере (текущий контекст всегда виден в промпте/выводе).

Пример контекста `kafkactl` (файл `~/.config/kafkactl/config.yml`):

```yaml
contexts:
  dev:
    brokers:
      - localhost:9092
  prod:
    brokers:
      - broker1.prod:9093
      - broker2.prod:9093
    tls:
      enabled: true
      ca: ca.pem
      cert: alice.crt
      certKey: alice.key
    sasl:
      enabled: true
      mechanism: scram-sha512
      username: alice
current-context: dev
```

```bash
# Переключение и проверка текущего контекста
kafkactl config use-context prod
# → Context 'prod' set

kafkactl get topics
```

Особенность `kafkactl`: контекст может указывать не напрямую на брокер, а на кластер внутри Kubernetes — инструмент сам выполнит `kubectl port-forward`/подключится через под, используя секреты Strimzi (`tlsSecret`, `saslSecret`). Это удобно для отладки прод-кластеров, доступных только изнутри кластера.

## Практические сценарии

### Сценарий 1: Управление топиками и метаданными

**Стандартные утилиты:**

```bash
# Список топиков
kafka-topics.sh --bootstrap-server localhost:9092 --list
# → orders
# → payments
# → __consumer_offsets   (внутренний топик координатора групп)

# Детальное описание топика (лидеры партиций, ISR, конфиги)
kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic orders
# → Topic: orders	PartitionCount: 3	ReplicationFactor: 3	Configs: min.insync.replicas=2,cleanup.policy=delete
# → 	Topic: orders	Partition: 0	Leader: 1	Replicas: 1,2,3	Isr: 1,2,3
# → 	Topic: orders	Partition: 1	Leader: 2	Replicas: 2,3,1	Isr: 2,3,1
# → 	Topic: orders	Partition: 2	Leader: 3	Replicas: 3,1,2	Isr: 3,1,2

# Создание топика с параметрами (партиции, репликация, конфиги)
kafka-topics.sh --bootstrap-server localhost:9092 --create \
    --topic orders --partitions 12 --replication-factor 3 \
    --config retention.ms=604800000 --config min.insync.replicas=2

# Изменение числа партиций (только увеличение; уменьшение невозможно и нарушит порядок по ключу)
kafka-topics.sh --bootstrap-server localhost:9092 --alter --topic orders --partitions 24

# Чтение сообщений из топика с самого начала (Интерактивно; выход Ctrl+C)
kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic orders --from-beginning
# → {"order_id": "a1", "amount": 100}
# → {"order_id": "a2", "amount": 250}

# Проверка версий API брокеров и их состояния (диагностика совместимости клиентов)
kafka-broker-api-versions.sh --bootstrap-server localhost:9092
# → localhost:9092 (id: 1 rack: null): Produce(0): 0 to 12 [usable: 12]
# → localhost:9092 (id: 1 rack: null): Fetch(1): 0 to 17 [usable: 17]
# → ...

# Идентификатор кластера (полезен при инвентаризации и в мониторинге)
kafka-cluster.sh cluster-id --bootstrap-server localhost:9092
# → Cluster ID: 5L6g3nShT-eMCtK--X86sw
```

Трактовка вывода `--describe`: если какая-то реплика отсутствует в списке `Isr`, она отстала или недоступна; поле `Leader` показывает брокера, обслуживающего чтение/запись партиции. Все реплики должны совпадать с ISR у здорового кластера. Подробнее о механике репликации — [Обзор Apache Kafka](./kafka_overview.md).

**Работа в Docker:**
Если Kafka запущена в контейнере, команды выполняются через `docker exec`:

```bash
docker exec -it <container_name> kafka-topics.sh --bootstrap-server localhost:9092 --list
```

В официальных образах (`apache/kafka`, `confluentinc/cp-kafka`) скрипты доступны в `PATH` контейнера, поэтому путь `bin/` указывать не нужно. Полный рабочий стек — [Развертывание Kafka в Docker](./kafka_docker_setup.md).

**rpk:**

```bash
# Список топиков
rpk topic list
# NAME     PARTITIONS  REPLICAS
# orders   3           3

# Создание топика с настройками
rpk topic create orders -p 12 -r 3 --topic-config retention.ms=604800000

# Чтение сообщений (Interactive)
rpk topic consume orders

# Детальное описание партиций и конфигов
rpk topic describe orders -p
```

**kafkactl:**

```bash
# Детальная информация
kafkactl describe topic orders
# Per default печатаются только переопределенные конфиги; для всех значений:
kafkactl describe topic orders --all-configs

# Создание и удаление
kafkactl create topic orders --partitions 12 --replication-factor 3
kafkactl delete topic old-orders
```

### Сценарий 2: Чтение и отправка данных

**Стандартные утилиты:**

```bash
# Отправка сообщения (интерактивно; каждая строка — сообщение, выход Ctrl+C/Ctrl+D)
kafka-console-producer.sh --bootstrap-server localhost:9092 --topic orders
# > order-a1
# > order-a2

# Отправка сообщений С КЛЮЧАМИ (ключ и значение разделяются разделителем;
# без ключа партиционер распределит записи батчами, порядок по ключу не сохранится)
kafka-console-producer.sh --bootstrap-server localhost:9092 --topic orders \
    --property parse.key=true --property key.separator=:
# > customer-42:{"order_id": "a1", "amount": 100}

# Чтение с выводом ключа, таймстампа и разделителя
kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic orders \
    --from-beginning \
    --property print.key=true \
    --property print.timestamp=true \
    --property key.separator=" | "
# → CreateTime:1724508000000	customer-42	{"order_id": "a1", "amount": 100}
```

Нюанс версий: классы форматтеров сообщений исторически жили в пакете `kafka.tools.*`, в современных версиях они перенесены в `org.apache.kafka.tools.*` — при использовании нестандартного `--formatter` (например, для чтения внутренних топиков) указывайте актуальное имя пакета.

**kcat:**

```bash
# Чтение в JSON формате с метаданными (partition, offset, timestamp, key, payload)
kcat -b localhost:9092 -t orders -C -J
# → {"topic":"orders","partition":0,"offset":15233,"tstype":"create","ts":1724508000123,
#    "key":"customer-42","payload":"{\"order_id\": \"a1\"}"}

# Потребление последних N сообщений и выход после них (-o -N — относительный офсет, -e — выход в конце)
kcat -b localhost:9092 -t orders -C -o -10 -e

# Чтение диапазона по таймстампу (Unix time в миллисекундах)
kcat -b localhost:9092 -t orders -C -o s@1724500000000 -o e@1724503600000 -e

# Потребление сообщений с фильтрацией через jq
kcat -b localhost:9092 -t orders -C -e | jq '.payload'

# Красивый формат вывода через строку формата (%t топик, %p партиция, %o офсет, %k ключ, %S размер, %s payload)
kcat -b localhost:9092 -t syslog -f 'Topic %t[%p], offset: %o, key: %k, %S bytes: %s\n'

# Отправка: каждая строка stdin — отдельное сообщение
echo '{"order_id": "a3"}' | kcat -b localhost:9092 -t orders -P -K:

# Отправка ключ:значение из файла (разделитель после -K)
cat events.txt | kcat -b localhost:9092 -t orders -P -K:

# Отправка файла ЦЕЛИКОМ одним сообщением (для бинарных данных; -l разбивает по строкам, -T эхо ввода)
kcat -b localhost:9092 -t blobs -P report.bin

# Режим consumer group (-G) — как обычный консьюмер, офсеты коммитятся в группу
kcat -b localhost:9092 -G my-debug-group orders

# Продюсирование со сжатием
tail -f app.log | kcat -b localhost:9092 -t syslog -P -z snappy
```

Без явного `-C`/`-P` режим выбирается автоматически: данные приходят **из** пайпа — потребитель, уходят **в** пайп — продюсер.

**rpk:**

```bash
# Чтение сообщений
rpk topic consume orders

# Чтение в JSON-обертке с метаданными
rpk topic consume orders -f '%v\n'      # только значение
rpk topic consume orders --print-keys   # ключ + значение

# Ограничение чтения и позиционирование
rpk topic consume orders -n 10          # первые 10 от текущего конца
rpk topic consume orders --offset start # с начала журнала

# Отправка сообщения из файла
rpk topic produce orders < message.json

# Отправка с ключами (формат "key\tvalue" по умолчанию)
echo -e "customer-42\t{\"order_id\": \"a3\"}" | rpk topic produce orders -k "\t"
```

**kafkactl:**

```bash
# Чтение с выводом ключа и метаданных
kafkactl consume orders --print-key --offset-offsets earliest
# → order-a1 (partition 0 @ 15233)

# Отправка ключа и значения
kafkactl produce orders --key customer-42 --value '{"order_id": "a3"}'
```

Отличительная возможность `kafkactl` — нативная работа со схемами: при настроенном Schema Registry в контексте он умеет читать и писать Avro (`schemaRegistry.url`), Protobuf (`--value-proto-type`, `--proto-file`), что избавляет от ручной сборки SerDes.

### Сценарий 3: Группы потребителей и LAG

Диагностика отставания консьюмеров (Consumer Lag) — самая частая операция при разборе инцидентов доставки. Что такое офсеты и группы — [Обзор Apache Kafka](./kafka_overview.md).

**Стандартные утилиты:**

```bash
# Список групп
kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list
# → my-service
# → orders-processor

# Проверка лага (самая частая операция)
kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group my-service
# → GROUP       TOPIC   PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG   CONSUMER-ID        HOST        CLIENT-ID
# → my-service  orders  0          15234           15240           6     consumer-1-a3f...  /10.0.0.5   consumer-1
# → my-service  orders  1          9811            9811            0     consumer-2-b7c...  /10.0.0.6   consumer-2

# Состояние группы без деталей по партициям (Empty = нет активных членов)
kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group my-service --state
# → GROUP       COORDINATOR (ID)  ASSIGNMENT-STRATEGY  STATE           #MEMBERS
# → my-service  broker1:9092 (1)  range                Stable          2

# Состав группы и назначенные партиции
kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group my-service --members --verbose

# Диагностика всех групп сразу
kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --all-groups --state
```

Трактовка колонок: `CURRENT-OFFSET` — закоммиченный офсет группы; `LOG-END-OFFSET` — офсет последней записи в журнале; `LAG = LOG-END-OFFSET − CURRENT-OFFSET`. Постоянно растущий лаг означает, что потребители не успевают (медленная обработка, недостаточно потребителей, стоп ребалансировок). Пустой `CONSUMER-ID` при непустом лаге — группа существует, но активных членов нет (приложение остановлено).

**Сброс офсетов (reset-offsets)** — восстановление потребления после сбоя или перезачитывание данных:

```bash
# ШАГ 1: группа НЕ должна иметь активных членов, иначе будет ошибка
# → Error: Assignment size of group my-service is smaller than ...
# Остановите приложение или используйте другую группу.

# ШАГ 2: сначала DRY-RUN (по умолчанию!) — команда покажет план, ничего не меняя
kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
    --group my-service --topic orders --reset-offsets --to-earliest
# → TOPIC   PARTITION  NEW-OFFSET
# → orders  0          0
# → orders  1          0

# ШАГ 3: применение плана — обязательно добавить --execute
kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
    --group my-service --topic orders --reset-offsets --to-earliest --execute

# Другие стратегии сброса:
# --to-latest            на конец журнала (пропустить backlog)
# --to-datetime 2026-01-01T00:00:00.000   на первый офсет после момента времени
# --by-duration PT1H     на первый офсет час назад
# --shift-by -100        сдвиг назад на 100 записей
# --from-file offsets.csv план из CSV (topic,partition,offset)

# Удаление пустой (без членов) группы
kafka-consumer-groups.sh --bootstrap-server localhost:9092 --delete --group my-service
# → Deletion of requested consumer groups ('my-service') was successful.
```

Критично: забытый `--execute` — самая частая ошибка этой утилиты; без него команда работает как dry-run и изменения не применяются.

**rpk:**

```bash
# Просмотр состояния групп
rpk group describe my-service

# Только лагающие партиции (удобно для алертов и триажа)
rpk group lag my-service
# GROUP        TOPIC   PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG
# my-service   orders  0          15234           15240           6

# Список всех групп
rpk group list
```

**kafkactl:**

```bash
# Описание группы; флаг --only-with-lag оставляет только проблемные партиции
kafkactl describe consumer-group my-service --only-with-lag

# Сброс офсета конкретной партиции
kafkactl reset consumer-group-offset my-service --topic orders --partition 0 --offset earliest
```

**kcat:** режим `-G <group>` позволяет проверить потребление от имени реальной группы без написания приложения (см. Сценарий 2).

### Сценарий 4: Динамическая конфигурация (kafka-configs.sh)

Утилита `kafka-configs.sh` позволяет менять настройки брокеров и топиков «на лету» без перезагрузки. Типы сущностей (`--entity-type`): `topics`, `brokers`, `broker-loggers` (уровни логирования!), `users` и `clients` (квоты), `ips` (лимиты соединений). Приоритет конфигурации: переопределение топика перекрывает значение по умолчанию брокера.

```bash
# Ограничение скорости (квота) для пользователя: producer_byte_rate в байтах/сек
kafka-configs.sh --bootstrap-server localhost:9092 --alter \
    --entity-type users --entity-name user1 \
    --add-config 'producer_byte_rate=1048576'
# → Completed updating config for user: user1.

# Включение сжатия для топика
kafka-configs.sh --bootstrap-server localhost:9092 --alter \
    --entity-type topics --entity-name orders \
    --add-config compression.type=lz4
# → Completed updating config for topic 'orders'.

# Просмотр текущих переопределенных настроек брокера
kafka-configs.sh --bootstrap-server localhost:9092 --describe \
    --entity-type brokers --entity-name 1

# Просмотр ВСЕХ настроек, включая унаследованные значения по умолчанию
kafka-configs.sh --bootstrap-server localhost:9092 --describe \
    --entity-type brokers --entity-name 1 --all

# Значения по умолчанию для ВСЕЙ категории (кластерный дефолт)
kafka-configs.sh --bootstrap-server localhost:9092 --describe \
    --entity-type brokers --entity-default

# Снятие переопределения (возврат к значению по умолчанию)
kafka-configs.sh --bootstrap-server localhost:9092 --alter \
    --entity-type topics --entity-name orders --delete-config compression.type

# Динамическое изменение уровня логирования на работающем брокере — без рестарта
kafka-configs.sh --bootstrap-server localhost:9092 --alter \
    --entity-type broker-loggers --entity-name 1 \
    --add-config kafka.server.KafkaApis=DEBUG
# → Completed updating config for broker-logger '1'.
# Вернуть назад: --add-config kafka.server.KafkaApis=INFO
```

Последняя команда — незаменимый инструмент диагностики: можно временно включить DEBUG у конкретного класса на конкретном брокере и вернуть уровень обратно, не трогая `log4j.properties` и не перезапуская процесс.

Эквивалент в `kafkactl`: `kafkactl alter topic orders --config compression.type=lz4`, просмотр — `kafkactl describe broker 1 --all-configs`.

### Сценарий 5: Управление правами доступа (ACL)

Используется для настройки безопасности в кластере. Принципы именуются `User:<principal>`; операции применяются к ресурсам (`--topic`, `--group`, `--cluster`). Для кластера с SASL/TLS добавьте `--command-config client.properties` к каждой команде. Подробнее о слоях безопасности — [Обзор Apache Kafka](./kafka_overview.md).

```bash
# Разрешить пользователю чтение из топика + чтение группы (оба ресурса нужны консьюмеру)
kafka-acls.sh --bootstrap-server localhost:9092 --add \
    --allow-principal User:alice --operation Read \
    --topic orders --group my-group

# Список всех ACL
kafka-acls.sh --bootstrap-server localhost:9092 --list
# → Current ACLs for resource `Topic:LITERAL:orders`:
# →   (principal=User:alice, host=*, operation=READ, permissionType=ALLOW)

# Готовые наборы операций: --producer (Write, Describe, Create) и --consumer (Read, Describe)
kafka-acls.sh --bootstrap-server localhost:9092 --add \
    --allow-principal User:svc-orders --producer --consumer \
    --topic orders --group orders-processor

# Явный запрет перекрывает разрешение (deny имеет приоритет над allow)
kafka-acls.sh --bootstrap-server localhost:9092 --add \
    --deny-principal User:contractor --operation Read --topic payments

# Шаблонные ресурсы: префиксные правила для серии топиков (orders-eu-*, orders-us-*...)
kafka-acls.sh --bootstrap-server localhost:9092 --add \
    --allow-principal User:analytics --operation Read \
    --topic orders- --resource-pattern-type prefixed

# Фильтрованный список
kafka-acls.sh --bootstrap-server localhost:9092 --list --topic orders

# Удаление конкретного правила
kafka-acls.sh --bootstrap-server localhost:9092 --remove \
    --allow-principal User:alice --operation Read --topic orders --group my-group
```

Краевой случай: принципалы, перечисленные в `super.users` конфигурации брокера, обходят все ACL-проверки — аудит таких учетных записей ведите отдельно.

### Сценарий 6: Обслуживание и диагностика кластера

Задачи этого сценария недоступны сторонним CLI — здесь нужны стандартные утилиты.

**Перераспределение партиций между брокерами** (балансировка дисков/нагрузки, вывод брокера из кластера) — строго трехшаговый процесс:

```bash
# ШАГ 1: сгенерировать план. В topics.json перечисляем темы; broker-ids — целевая раскладка
cat > topics.json <<EOF
{"topics": [{"topic": "orders"}, {"topic": "payments"}], "version": 1}
EOF

kafka-reassign-partitions.sh --bootstrap-server localhost:9092 \
    --topics-to-move-json-file topics.json \
    --broker-list "1,2,3" --generate
# → Current partition replica assignment
# → {"version":1,"partitions":[...]}
# → Proposed partition reassignment configuration
# → {"version":1,"partitions":[{"topic":"orders","partition":0,"replicas":[2,3,1],...},...]}

# Сохраняем предложенный JSON в reassignment.json и запускаем ШАГ 2.
# Текущая раскладка из блока "Current..." сохраните отдельно — это план отката!

# ШАГ 2: выполнить план с троттлингом (ограничить скорость миграции, чтобы не задушить кластер)
kafka-reassign-partitions.sh --bootstrap-server localhost:9092 \
    --reassignment-json-file reassignment.json --execute --throttle 50000000

# ШАГ 3: контролировать прогресс до завершения (повторять команду)
kafka-reassign-partitions.sh --bootstrap-server localhost:9092 \
    --reassignment-json-file reassignment.json --verify
# → Status of partition reassignment:
# → Reassignment of partition orders-0 is still in progress
# → ... (в конце: Reassignment of partition X is completed.)
```

Во время миграции копируются целые сегменты журнала — на больших топиках это часы; троттлинг (байт/сек) обязателен для прод-кластеров.

**Принудительные выборы лидера** (после восстановления брокера, чтобы вернуть preferred leader):

```bash
# Для всех партиций, где текущий лидер не является предпочтительным
kafka-leader-election.sh --bootstrap-server localhost:9092 \
    --election-type PREFERRED --all-topic-partitions
# → Successfully started leader election for partitions orders-0, ...

# Или для конкретного списка партиций (path-to-json-file с {"partitions":[{"topic":"orders","partition":0}]})
```

**Дисковая занятость по партициям:**

```bash
# Размеры журналов и лаг реплик по каждому каталогу данных
kafka-log-dirs.sh --bootstrap-server localhost:9092 \
    --describe --broker-list 1,2,3 --topic-list orders | jq .
# → {"version":1,"brokers":[{"broker":1,"logDirs":[
#     {"logDir":"/var/lib/kafka/data","partitions":[
#       {"partition":"orders-0","size":1073741824,"offsetLag":0,...}]}]}]}
```

**Инспекция файлов журнала на диске** (выполняется НА хосте брокера, где лежат сегменты):

```bash
# Расшифровка содержимого сегмента: сообщения, ключи, контрольные суммы
kafka-dump-log.sh --files /var/lib/kafka/data/orders-0/00000000000000000000.log \
    --print-data-log
# → Starting offset: 0
# → baseOffset: 0 lastOffset: 99 baseTimestamp: 1724508000123 ... validBytes: 58210
# → | offset: 0 CreateTime: 1724508000123 keySize: 11 valueSize: 27 ...

# Проверка индексов сегмента
kafka-dump-log.sh --files /var/lib/kafka/data/orders-0/00000000000000000000.index \
    /var/lib/kafka/data/orders-0/00000000000000000000.timeindex

# В KRaft-кластере так же читается журнал метаданных __cluster_metadata
kafka-dump-log.sh --files /var/lib/kafka/data/__cluster_metadata-0/00000000000000000000.log \
    --cluster-metadata-decoder
```

**Здоровье кворума метаданных (KRaft)** — замена прежних проверок ZooKeeper:

```bash
# Состояние кворума: лидер, избиратели, идентификатор кластера
kafka-metadata-quorum.sh --bootstrap-server localhost:9092 describe --status
# → ClusterId:              5L6g3nShT-eMCtK--X86sw
# → LeaderId:               1
# → QuorumState:            Leader
# → ...

# Детали репликации метаданных по контроллерам (lag каждого узла)
kafka-metadata-quorum.sh --bootstrap-server localhost:9092 describe --replication
```

**Управление feature-флагами и версией метаданных** (критично при апгрейдах 3.x → 4.x):

```bash
# Текущие флаги и metadata.version кластера
kafka-features.sh --bootstrap-server localhost:9092 describe
# → Feature: metadata.version   SupportedMinVersion: 3.0-IV1   MaxVersionLevel: 4.0-IV3  ...

# Повышение после успешного обновления всех брокеров (необратимо даунгрейдится ограниченно!)
kafka-features.sh --bootstrap-server localhost:9092 upgrade --metadata 4.0

# Доступны также: downgrade, disable, version-mapping, feature-dependencies
# Утилита может работать и напрямую с контроллерами: --bootstrap-controller localhost:9094
```

**Зависшие транзакции** (после падения продюсера транзакционные записи могут блокировать чтение консьюмерам с `read_committed`):

```bash
# Список открытых транзакций по всем партициям
kafka-transactions.sh --bootstrap-server localhost:9092 list
# → TRANSACTIONAL-ID  PRODUCER-ID  LAST-UPDATE  PARTITION  START-OFFSET

# Кто держит транзакцию: какие продюсеры писали в координатор
kafka-transactions.sh --bootstrap-server localhost:9092 describe-producers --topic orders --partition 0

# Поиск транзакций, которые не двигаются (кандидаты на прерывание)
kafka-transactions.sh --bootstrap-server localhost:9092 find-hanging --broker 1
```

**Проверка совместимости клиентов:** команда `kafka-broker-api-versions.sh` из Сценария 1 показывает максимальную версию каждого API на брокере — если клиент старше, часть функций недоступна.

### Сценарий 7: Нагрузочное тестирование

В дистрибутив входят готовые бенчмарки — базовая линия производительности кластера и сети без внешних инструментов.

```bash
# Producer benchmark: 1 млн записей размером 1024 Б, целевой throughput 50k записей/сек
kafka-producer-perf-test.sh --topic perf-test \
    --num-records 1000000 --record-size 1024 --throughput -1 \
    --producer-props bootstrap.servers=localhost:9092 acks=all linger.ms=10
# → 1000000 records sent, records/sec: 187543.2, MB/sec: 183.15,
# → avg latency: 41.20 ms, max latency: 812.35 ms,
# → 50th percentile latency: 28 ms, 95th percentile: 96 ms, 99th: 210 ms, 99.9th: 540 ms

# Consumer benchmark: чтение того же объема с начала топика
kafka-consumer-perf-test.sh --bootstrap-server localhost:9092 \
    --topic perf-test --messages 1000000 \
    --consumer-property group.id=perf-consumer
# → data.consumed.in.MB.MB.sec  nMsg.sec  fetch.MB.sec  nMsg.sec ...
# → 976.56                      245098    183.15        224512

# Сквозная задержка end-to-end (отправка и немедленное чтение одного сообщения; интерактивно)
bin/kafka-run-class.sh kafka.tools.EndToEndLatency localhost:9092 perf-test 100 1 1024
# → Avg latency: 3.215 ms, Min: 2.101 ms, Max: 8.442 ms
```

Флаг `--throughput -1` отключает троттлинг (замер потолка); заданное число (например, `50000`) имитирует ограниченный поток. Тестируйте конфигурации из [Гарантии доставки](./delivery_guarantees.md): сравнение `acks=all` против `acks=1` наглядно показывает цену надежности.

## Работа в Docker и Kubernetes

- Локальный стенд и выполнение команд через `docker exec` — [Развертывание Kafka в Docker](./kafka_docker_setup.md); healthcheck-команды там же используют `kafka-topics.sh --list`.
- В Kubernetes-кластерах, развернутых оператором, клиентские сертификаты выдаются как секреты CR `KafkaUser` (Strimzi) — эти секреты подключаются в `client.properties` или контекст `kafkactl` (поддержка `tlsSecret` из коробки): [Strimzi Kafka Operator](./strimzi_kafka_operator.md).
- Мониторинг-специфичные команды (лаг, квоты) в контексте наблюдаемости — [Мониторинг Kafka](./kafka_for_monitoring.md).

## Установка сторонних инструментов

```bash
# kcat
brew install kcat                      # macOS
apt-get install kafkacat               # Debian/Ubuntu (пакет сохраняет старое имя)
docker run -it --network=host edenhill/kcat:1.7.1 -b broker:9092 -L   # без установки вообще

# rpk
brew install redpanda-data/tap/redpanda
curl -LO https://github.com/redpanda-data/redpanda/releases/latest/download/rpk-linux-amd64.zip

# kafkactl
brew install deviceinsight/tap/kafkactl
snap install kafkactl
go install github.com/deviceinsight/kafkactl/v5@latest
```

## Дополнительная информация

### Выбор инструмента

- **rpk**: Лучший выбор для повседневных операций (Topic, Group, ACL). Быстрый, современный и не требует Java.
- **kcat**: Незаменим для сложных пайплайнов обработки данных в shell, точечного чтения по офсету/таймстампу и быстрого воспроизведения багов.
- **Стандартные утилиты**: «Последняя миля» для специфических задач (перераспределение партиций, низкоуровневые конфиги, дамп логов, кворум KRaft, нагрузочное тестирование).
- **kafkactl**: Удобен при работе с десятками разных кластеров (контексты), в Kubernetes-окружениях и при работе со схемами (Avro/Protobuf).
- **Confluent CLI**: Обязателен при работе с Confluent Cloud (управление окружениями и API-ключами); для данных используется вместе с перечисленными выше.

### Ограничения и краевые случаи

- **JVM-старт**: каждая команда стандартных утилит поднимает JVM (~1–3 сек). В цикле по сотням топиков используйте `rpk`/`kafkactl` или один вызов с `--all-groups`/`--all-topic-partitions`.
- **Java 17+**: для утилит дистрибутива Kafka 4.x требуется современная JVM (поддержка Java 8/11 удалена, KIP-750/KIP-1013). На машинах со старым JDK команды падают с ошибками компиляции классов — проверьте `java -version`.
- **Windows**: скрипты `.bat` работают, но экранирование кавычек в свойствах (`--property key.separator=...`) отличается от POSIX-shell — сложные команды надежнее выполнять в WSL/Linux-контейнере.
- **rpk и Apache Kafka**: базовые команды (`topic`, `group`, `acl`, `produce`, `consume`) совместимы, но часть функциональности специфична для Redpanda (`rpk cluster config`, tiered storage, self-test) и на Apache Kafka вернет ошибку или пустой результат.
- **kcat не администратор**: нет управления топиками/ACL; `-o end` означает «с конца журнала», а не «с закоммиченного офсета группы» — для проверки группы используйте `-G` или `kafka-consumer-groups.sh`.
- **Dry-run по умолчанию у reset-offsets**: без `--execute` план только печатается (см. Сценарий 3).
- **Reassignment небесплатен**: миграция копирует сегменты целиком; без `--throttle` может деградировать кластер. Прервать начатую миграцию корректнее всего выполнив обратную (сохраненную «Current») раскладку.
- **dump-log требует доступа к диску брокера**: команда читает файлы сегментов локально — в контейнере монтируйте тот же volume или выполняйте `docker exec` на хост брокера.
- **Автоформатирование KRaft**: начиная с Kafka 4.0 дистрибутив умеет автоматически форматировать пустые каталоги хранилища при первом старте брокера, поэтому явный вызов `kafka-storage.sh format` может быть не нужен. Однако повторный `format` с тем же ID кластера на живом кластере опасен (перезапись журнала метаданных) — на существующих узлах используйте `--ignore-formatted` или выполняйте форматирование только на чистых каталогах. Поведение зависит от способа запуска (systemd-юнит, официальный образ) — сверяйтесь с конфигурацией конкретного развертывания.
- **Легаси `--zookeeper`**: любые скрипты/ранбуки с этим аргументом несовместимы с современными кластерами; при миграции замените на `--bootstrap-server` (+ `--command-config` для защищенных кластеров).

### См. также

- **[Обзор Apache Kafka](./kafka_overview.md)** — архитектура и основные понятия.
- **[Партиционирование и балансировка](./partitioning_and_balancing.md)** — детали работы с разделами.
- **[Гарантии доставки](./delivery_guarantees.md)** — настройки надежности (acks, retries).
