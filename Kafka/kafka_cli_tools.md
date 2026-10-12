# CLI-инструменты для работы с Apache Kafka

**Актуально для:** Apache Kafka 3.8.x / 3.9.x / 4.0.x (KRaft)

Для взаимодействия с Apache Kafka из командной строки используются стандартные утилиты, входящие в дистрибутив, а также специализированные высокопроизводительные сторонние решения: `kcat`, `rpk` и `kafkactl`. Они обеспечивают администрирование топиков, потоковое чтение и отправку сообщений, диагностику отставания потребителей (Consumer Lag), динамическое конфигурирование параметров без перезагрузки брокеров, перераспределение партиций, инспекцию дисковых сегментов и нагрузочное тестирование. Теоретические основы архитектуры и протокола — [Обзор Apache Kafka](./kafka_overview.md).

---

## Определения

- **Kafka Standard CLI**: Набор shell-скриптов (оберток над Java-классами `org.apache.kafka.tools.*`), поставляемых в каталоге `bin/` официального дистрибутива Apache Kafka. Требуют наличия JVM (начиная с Kafka 4.0 — строго Java 17+ согласно KIP-750/KIP-1013). Для Windows в комплекте поставляются bat-файлы в каталоге `bin/windows/`.
- **kcat (ранее kafkacat)**: Универсальная не-JVM консольная утилита на базе C-библиотеки `librdkafka` («netcat для Kafka»). Отличается мгновенным запуском, минимальным потреблением ресурсов, поддержкой форматированного вывода и гибким позиционированием по офсетам и меткам времени. Идеальна для отладки данных и конвейеров shell.
- **rpk (Redpanda CLI)**: Высокоскоростной CLI на Go, распространяемый как единый статический бинарный файл без внешних зависимостей. Поддерживает парадигму `noun + verb` (`rpk topic list`, `rpk group describe`), профили подключений и совместим со стандартным бинарным протоколом Apache Kafka для операций с топиками, группами потребителей и ACL.
- **kafkactl**: Специализированный CLI на Go от Device Insight с декларативным синтаксисом в стиле `kubectl` (`get`, `describe`, `alter`, `create`, `delete`). Поддерживает многокластерные контексты, декодирование схем Avro/Protobuf через Schema Registry и прямое проксирование запросов к подам в Kubernetes.
- **librdkafka**: C/C++ реализация клиентской библиотеки Kafka. Все её низкоуровневые параметры конфигурации могут передаваться напрямую в `kcat` через флаг `-X <property>=<value>`.
- **AdminClient**: Программный интерфейс Java (`org.apache.kafka.clients.admin.AdminClient`), через который современные утилиты взаимодействуют с кластером поверх стандартных сетевых листенеров брокеров (`--bootstrap-server`).
- **Consumer Lag**: Разница между последним записанным офсетом в партиции (`LOG-END-OFFSET`) и последним подтвержденным офсетом группы потребителей (`CURRENT-OFFSET`). Ключевой эксплуатационный показатель задержки обработки.
- **Command Config (`--command-config`)**: Файл свойств клиента (`client.properties`), передаваемый административным утилитам для настройки протоколов безопасности (TLS, SASL, JAAS), таймаутов сетевых запросов и доверенных сертификатов.
- **KRaft Quorum Metadata**: Журнал событий метаданных (`@metadata`), реплицируемый контроллерами кластера на базе алгоритма Raft, полностью заменивший ZooKeeper. Диагностируется утилитами `kafka-metadata-quorum.sh` и `kafka-features.sh`.

---

## Архитектура и основные концепции

### Сравнение инструментов командной строки

| Критерий | Стандартные утилиты Kafka | kcat | rpk | kafkactl |
| :--- | :--- | :--- | :--- | :--- |
| **Ядро / Зависимости** | Java (JVM 17+ для Kafka 4.x, JVM 11+ для 3.x) | C (`librdkafka`) | Go (статический бинарник) | Go (статический бинарник) |
| **Стиль синтаксиса** | Разрозненные bash-скрипты | POSIX-флаги (`-C`, `-P`, `-L`, `-G`) | `noun + verb` (`rpk topic ...`) | `kubectl`-стиль (`get`, `describe`) |
| **Управление профилями** | Флаги в командной строке / свойства | Флаг `-F`, `~/.config/kcat.conf` | Профили (`rpk profile`) | Контексты (`~/.config/kafkactl/config.yml`) |
| **Администрирование кластера** | Полное (ACL, квоты, ребалансировка, KRaft, логи) | Только инспекция метаданных (`-L`) | Высокое (топики, группы, ACL) | Высокое (топики, группы, ACL, пользователи) |
| **Потоковая работа с данными** | `kafka-console-producer/consumer.sh` | Превосходная (JSON, таймстампы, пайпы) | Высокая (`rpk topic produce/consume`) | Высокая (+ Avro, Protobuf) |
| **Время инициализации** | Медленно (старт JVM 1.5–3.5 сек) | Мгновенно (< 20 мс) | Мгновенно (< 25 мс) | Мгновенно (< 25 мс) |
| **Инспекция файлов на диске** | Да (`kafka-dump-log.sh`) | Нет | Нет | Нет |

Инструменты дополняют друг друга в работе системного администратора и SRE:
- `rpk` и `kafkactl` оптимальны для ежедневных оперативных задач, рутинного мониторинга лага и интеграции в скрипты автоматизации за счет мгновенного отклика.
- `kcat` является непревзойденным инструментом для исследования потоков данных, фильтрации по времени, отладки сериализации и извлечения сообщений в shell-пайплайнах с `jq`.
- Стандартные утилиты незаменимы для низкоуровневого обслуживания кластера: планового перемещения партиций, анализа кворума метаданных KRaft, инспекции индексных файлов на хостах брокеров и стресс-тестирования.

### Протоколы подключения и аутентификация

Все клиентские утилиты обращаются к кластеру через начальный список брокеров (Bootstrap Servers). Историческая справка и архитектурные различия:

1. До Kafka 2.2 административные утилиты использовали прямое подключение к метаданным ZooKeeper через флаг `--zookeeper host:2181`. Это обходило сетевые политики брокеров и аутентификацию.
2. В Kafka 2.x–3.x утилиты были переведены на работу через `AdminClient` с флагом `--bootstrap-server host:9092`, а флаг `--zookeeper` был объявлен устаревшим.
3. Начиная с Kafka 4.0 поддержка ZooKeeper полностью удалена из исходного кода. Все утилиты работают **исключительно** через протокол Kafka RPC с флагом `--bootstrap-server` (или `--bootstrap-controller` для специализированных команд управления кворумом метаданных).

При работе в защищенном контуре параметры соединения передаются через конфигурационные файлы.

#### Разделение конфигурационных флагов стандартных утилит

Частая ошибка при вызове стандартных утилит — передача неверного конфигурационного ключа:
- Административные утилиты (`kafka-topics.sh`, `kafka-consumer-groups.sh`, `kafka-configs.sh`, `kafka-acls.sh`, `kafka-reassign-partitions.sh`, `kafka-features.sh`) принимают флаг `--command-config <path>`.
- Консольный консьюмер (`kafka-console-consumer.sh`) принимает флаг `--consumer.config <path>`.
- Консольный продюсер (`kafka-console-producer.sh`) принимает флаг `--producer.config <path>`.
- Бенчмарк-утилиты (`kafka-consumer-perf-test.sh`, `kafka-producer-perf-test.sh`) принимают флаги `--consumer-property` и `--producer-props` соответственно.

Пример эталонного файла конфигурации `client-sasl-ssl.properties`:

```properties
# Протокол взаимодействия: SASL поверх защищенного TLS-канала
security.protocol=SASL_SSL

# Механизм аутентификации (рекомендуемый стандарт: SCRAM-SHA-512)
sasl.mechanism=SCRAM-SHA-512

# Строка JAAS конфигурации с учетными данными
sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required \
    username="sre-admin" \
    password="SecretPassword512!";

# Доверенное хранилище корневых сертификатов CA
ssl.truststore.location=/var/private/ssl/kafka.truststore.jks
ssl.truststore.password=TruststorePassword123

# Идентификация конечного узла (проверка hostname в SAN сертификата)
ssl.endpoint.identification.algorithm=HTTPS
```

Для инструментов на базе C/Go (`kcat`, `kafkactl`) параметры JKS-хранилища не поддерживаются: сертификаты предоставляются в открытом формате PEM (`ca.pem`, `client.crt`, `client.key`).

### Контексты и профили окружения

В инфраструктуре с несколькими контурами (dev, stage, prod) ручной ввод адресов и путей к сертификатам увеличивает риск ошибки оператора. Использование профилей изолирует окружения.

Структура конфигурации `kafkactl` (`~/.config/kafkactl/config.yml`):

```yaml
contexts:
  local-dev:
    brokers:
      - "127.0.0.1:9092"
  prod-cluster:
    brokers:
      - "kafka-broker-1.prod.internal:9093"
      - "kafka-broker-2.prod.internal:9093"
      - "kafka-broker-3.prod.internal:9093"
    tls:
      enabled: true
      ca: /etc/ssl/certs/internal-ca.pem
      cert: /home/sre/.ssl/client.crt
      certKey: /home/sre/.ssl/client.key
    sasl:
      enabled: true
      mechanism: scram-sha512
      username: sre-operator
      password: "OperatorSecretPassword!"
current-context: local-dev
```

Переключение контекста выполняется командой:

```bash
kafkactl config use-context prod-cluster
# → Context 'prod-cluster' set

kafkactl get brokers
# → ID   HOST                            PORT    RACK
# → 1    kafka-broker-1.prod.internal   9093    rack-a
# → 2    kafka-broker-2.prod.internal   9093    rack-b
# → 3    kafka-broker-3.prod.internal   9093    rack-c
```

---

## Установка и базовая настройка

### Системные требования

- **Java Runtime Environment**: Для стандартных утилит Kafka 3.x требуется Java 11+, для Kafka 4.0+ — строго Java 17 или 21. Наличие JDK не требуется, достаточно headless JRE (`openjdk-17-jre-headless`).
- **Оперативная память для CLI**: По умолчанию скрипт `kafka-run-class.sh` считывает переменную `KAFKA_HEAP_OPTS`. Если на хосте не задан лимит, утилита может запускаться с избыточным выделением памяти. Рекомендуется явно ограничивать память для терминальных сессий:
  ```bash
  export KAFKA_HEAP_OPTS="-Xmx512M -Xms128M"
  ```

### Установка стандартных утилит без запуска брокера

Для администрирования не требуется развертывать полноценный сервис Kafka. На управляющий бастион или рабочий сервер распаковывается бинарный архив дистрибутива:

```bash
# Загрузка официального архива Apache Kafka 3.9.0 (Scala 2.13)
curl -LO https://downloads.apache.org/kafka/3.9.0/kafka_2.13-3.9.0.tgz

# Распаковка в системный каталог
sudo tar -xzf kafka_2.13-3.9.0.tgz -C /opt/
sudo ln -s /opt/kafka_2.13-3.9.0 /opt/kafka

# Добавление утилит в системный PATH
echo 'export PATH=$PATH:/opt/kafka/bin' >> ~/.bashrc
source ~/.bashrc

# Проверка работоспособности
kafka-topics.sh --version
# → 3.9.0
```

### Установка сторонних инструментов

```bash
# --- 1. kcat ---
# Debian / Ubuntu (пакет сохраняет историческое название kafkacat)
sudo apt-get update && sudo apt-get install -y kafkacat
# Создание алиаса для обратной совместимости
sudo ln -s /usr/bin/kafkacat /usr/local/bin/kcat 2>/dev/null || true

# RHEL / Rocky Linux (через репозиторий EPEL)
sudo dnf install -y epel-release && sudo dnf install -y kcat

# Запуск в Docker без установки в хост-систему
docker run --rm -it --network=host edenhill/kcat:1.7.1 -b 127.0.0.1:9092 -L

# --- 2. rpk ---
# Прямая загрузка статического бинарного файла для Linux x86_64
curl -LO https://github.com/redpanda-data/redpanda/releases/latest/download/rpk-linux-amd64.zip
unzip rpk-linux-amd64.zip -d /tmp/
sudo install -m 755 /tmp/rpk /usr/local/bin/rpk
rm -f rpk-linux-amd64.zip /tmp/rpk

# --- 3. kafkactl ---
# Прямая установка бинарного релиза Device Insight
KAFKACTL_VER="v5.6.0"
curl -LO "https://github.com/deviceinsight/kafkactl/releases/download/${KAFKACTL_VER}/kafkactl_${KAFKACTL_VER#v}_linux_amd64.tar.gz"
tar -xzf "kafkactl_${KAFKACTL_VER#v}_linux_amd64.tar.gz" kafkactl
sudo install -m 755 kafkactl /usr/local/bin/kafkactl
rm -f "kafkactl_${KAFKACTL_VER#v}_linux_amd64.tar.gz" kafkactl
```

### Конфигурация kcat по умолчанию

Для устранения необходимости передачи адресов и параметров аутентификации в каждом вызове создается конфигурационный файл `~/.config/kcat.conf`:

```properties
# Адреса брокеров
metadata.broker.list=10.0.10.11:9093,10.0.10.12:9093,10.0.10.13:9093

# Безопасность
security.protocol=SASL_SSL
sasl.mechanisms=SCRAM-SHA-512
sasl.username=sre-operator
sasl.password=OperatorSecretPassword!
ssl.ca.location=/etc/ssl/certs/company-root-ca.pem

# Таймауты сети
socket.timeout.ms=10000
```

```bash
chmod 600 ~/.config/kcat.conf
```

---

## Практические сценарии и типовые операции

### Сценарий 1: Управление топиками и инспекция метаданных

#### Стандартные утилиты

```bash
# 1. Получение списка топиков
kafka-topics.sh --bootstrap-server 10.0.10.11:9092 --list
# → orders
# → payments-v1
# → __consumer_offsets

# 2. Создание production-топика с явными параметрами надежности
kafka-topics.sh --bootstrap-server 10.0.10.11:9092 --create \
    --topic orders \
    --partitions 12 \
    --replication-factor 3 \
    --config min.insync.replicas=2 \
    --config retention.ms=604800000 \
    --config compression.type=lz4
# → Created topic orders.

# 3. Детальный аудит партиций топика (лидеры, ISR, переопределенные конфиги)
kafka-topics.sh --bootstrap-server 10.0.10.11:9092 --describe --topic orders
# → Topic: orders	TopicId: 4L6g3nShT-eMCtK--X86sw	PartitionCount: 12	ReplicationFactor: 3	Configs: min.insync.replicas=2,retention.ms=604800000,compression.type=lz4
# → 	Topic: orders	Partition: 0	Leader: 1	Replicas: 1,2,3	Isr: 1,2,3
# → 	Topic: orders	Partition: 1	Leader: 2	Replicas: 2,3,1	Isr: 2,3,1
# → 	Topic: orders	Partition: 2	Leader: 3	Replicas: 3,1,2	Isr: 3,1,2

# 4. Поиск проблемных топиков (где список ISR меньше Replicas или рассинхронизирован)
kafka-topics.sh --bootstrap-server 10.0.10.11:9092 --describe --under-replicated-partitions
# → (пустой вывод означает, что все партиции полностью синхронизированы)

# 5. Поиск партиций, чей текущий лидер отличается от предпочтительного (Preferred Leader)
kafka-topics.sh --bootstrap-server 10.0.10.11:9092 --describe --under-min-isr-partitions

# 6. Увеличение количества партиций (уменьшение в Kafka технически невозможно!)
kafka-topics.sh --bootstrap-server 10.0.10.11:9092 --alter --topic orders --partitions 24
# → Updated partition count for topic orders.

# 7. Проверка версий протокола API брокеров (совместимость клиентов)
kafka-broker-api-versions.sh --bootstrap-server 10.0.10.11:9092 | head -n 5
# → 10.0.10.11:9092 (id: 1 rack: rack-a): Produce(0): 0 to 12 [usable: 12]
# → 10.0.10.11:9092 (id: 1 rack: rack-a): Fetch(1): 0 to 17 [usable: 17]

# 8. Получение уникального Cluster ID
kafka-cluster.sh cluster-id --bootstrap-server 10.0.10.11:9092
# → Cluster ID: 5L6g3nShT-eMCtK--X86sw
```

#### kcat

Быстрый аудит метаданных кластера без задержек JVM:

```bash
# Получение списка брокеров, топиков, партиций и ISR
kcat -b 10.0.10.11:9092 -L
# → Metadata for all topics (from broker 1: 10.0.10.11:9092/1):
# →  3 brokers:
# →   broker 1 at 10.0.10.11:9092 (controller)
# →   broker 2 at 10.0.10.12:9092
# →   broker 3 at 10.0.10.13:9092
# →  1 topics:
# →   topic "orders" with 12 partitions:
# →     partition 0, leader 1, replicas: 1,2,3, isrs: 1,2,3
```

#### rpk и kafkactl

```bash
# Просмотр топиков через rpk
rpk topic list --brokers 10.0.10.11:9092
# → NAME     PARTITIONS  REPLICAS
# → orders   12          3

# Детальное описание в kafkactl
kafkactl describe topic orders
# → Name: orders
# → Partitions: 12
# → Replication Factor: 3
# → Configuration:
# →   min.insync.replicas: 2
# →   retention.ms: 604800000
```

---

### Сценарий 2: Потоковая отправка и чтение данных

#### Стандартные утилиты

```bash
# 1. Отправка сообщений с явными ключами через консольный продюсер
kafka-console-producer.sh --bootstrap-server 10.0.10.11:9092 --topic orders \
    --producer.config client.properties \
    --property parse.key=true \
    --property key.separator=:
# > user-101:{"order_id": 5510, "amount": 1200}
# > user-102:{"order_id": 5511, "amount": 450}

# 2. Чтение данных с начала топика с выводом таймстампа, партиции и ключа
kafka-console-consumer.sh --bootstrap-server 10.0.10.11:9092 --topic orders \
    --consumer.config client.properties \
    --from-beginning \
    --property print.timestamp=true \
    --property print.partition=true \
    --property print.key=true \
    --property key.separator=" | "
# → CreateTime:1728561200000 | Partition:2 | user-101 | {"order_id": 5510, "amount": 1200}
# → CreateTime:1728561205000 | Partition:5 | user-102 | {"order_id": 5511, "amount": 450}
```

#### Продвинутые пайплайны kcat

`kcat` является стандартом де-факто для SRE при отладке содержимого:

```bash
# 1. Чтение последних 5 сообщений из партиции 0 и немедленный выход (-e)
kcat -b 10.0.10.11:9092 -t orders -p 0 -C -o -5 -e
# → {"order_id": 5510, "amount": 1200}

# 2. Чтение в структурированном JSON-формате (-J) и фильтрация через jq
kcat -b 10.0.10.11:9092 -t orders -C -J -e | jq -r '.payload | fromjson | select(.amount > 1000) | .order_id'
# → 5510

# 3. Чтение интервала по временным меткам (Unix timestamp в миллисекундах)
# s@<start_ts> - начало, e@<end_ts> - конец
kcat -b 10.0.10.11:9092 -t orders -C -o s@1728560000000 -o e@1728563600000 -e

# 4. Кастомный формат вывода (%t - topic, %p - partition, %o - offset, %k - key, %s - payload)
kcat -b 10.0.10.11:9092 -t orders -C -f 'T:%t P:%p Off:%o Key:%k Val:%s\n' -e

# 5. Потоковая отправка лог-файла со сжатием LZ4 и разделителем ключа
tail -n 1000 /var/log/app/audit.log | kcat -b 10.0.10.11:9092 -t audit-events -P -z lz4

# 6. Отправка бинарного файла целиком одним неделимым сообщением (-D <delim>)
kcat -b 10.0.10.11:9092 -t firmware-updates -P -D "" /tmp/firmware.bin
```

---

### Сценарий 3: Диагностика групп консьюмеров и Consumer Lag

#### Стандартные утилиты

```bash
# 1. Список зарегистрированных групп потребителей
kafka-consumer-groups.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --list
# → orders-worker-group
# → billing-stream-processor

# 2. Проверка лага и распределения партиций по инстансам группы
kafka-consumer-groups.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties \
    --describe --group orders-worker-group
# → GROUP                TOPIC   PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG   CONSUMER-ID      HOST         CLIENT-ID
# → orders-worker-group  orders  0          185200          185250          50    worker-1-a8f...  /10.0.10.51  worker-1
# → orders-worker-group  orders  1          142100          142100          0     worker-2-b4c...  /10.0.10.52  worker-2

# 3. Проверка жизненного цикла группы (State: Stable, CompletingRebalance, PreparingRebalance, Empty, Dead)
kafka-consumer-groups.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties \
    --describe --group orders-worker-group --state
# → GROUP                COORDINATOR (ID)       ASSIGNMENT-STRATEGY  STATE           #MEMBERS
# → orders-worker-group  10.0.10.12:9092 (2)    range                Stable          2

# 4. Аудит активных участников группы (Members) и назначенных им партиций
kafka-consumer-groups.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties \
    --describe --group orders-worker-group --members --verbose
```

#### Регламент сброса офсетов (Offset Reset)

> [!WARNING]
> Сброс офсетов допустим только тогда, когда группа потребителей находится в состоянии **Empty** (все инстансы сервиса остановлены). Если запустить команду при работающих потребителях, брокер вернет ошибку `GroupNotEmptyException`.

Сброс офсетов выполняется строго в два шага:

```bash
# ШАГ 1: Dry-run — генерация плана сброса БЕЗ применения (по умолчанию)
kafka-consumer-groups.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties \
    --group orders-worker-group \
    --topic orders \
    --reset-offsets \
    --to-earliest
# → TOPIC   PARTITION  NEW-OFFSET
# → orders  0          0
# → orders  1          0

# ШАГ 2: Применение сгенерированного плана с обязательным флагом --execute
kafka-consumer-groups.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties \
    --group orders-worker-group \
    --topic orders \
    --reset-offsets \
    --to-earliest \
    --execute
# → TOPIC   PARTITION  NEW-OFFSET
# → orders  0          0
# → orders  1          0
```

Альтернативные стратегии позиционирования:
- `--to-latest`: Перемещение в конец журнала (пропуск очереди сообщений в инциденте).
- `--to-datetime 2026-10-12T00:00:00.000`: Позиционирование на первое сообщение после указанного времени UTC.
- `--by-duration PT2H`: Сдвиг назад на 2 часа относительно текущего времени.
- `--shift-by -500`: Сдвиг назад ровно на 500 сообщений в каждой партиции.
- `--from-file /tmp/offsets.csv`: Применение точечного плана из CSV-файла вида `topic,partition,offset`.

#### Оперативная проверка лага через rpk

```bash
# Вывод только партиций с ненулевым лагом
rpk group lag orders-worker-group --brokers 10.0.10.11:9092
# → GROUP                TOPIC   PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG
# → orders-worker-group  orders  0          185200          185250          50
```

---

### Сценарий 4: Динамическое конфигурирование параметров и логирования

Утилита `kafka-configs.sh` изменяет конфигурации брокеров и топиков без перезапуска JVM-процессов. Поддерживаемые сущности (`--entity-type`): `topics`, `brokers`, `broker-loggers`, `users`, `clients`, `ips`.

```bash
# 1. Изменение retention и политики очистки для топика
kafka-configs.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --alter \
    --entity-type topics --entity-name orders \
    --add-config retention.ms=86400000,max.message.bytes=2097152
# → Completed updating config for topic orders.

# 2. Установка квоты на скорость записи (Throttling) для конкретного пользователя (в байтах/сек)
# 10485760 байт/сек = 10 МБ/сек
kafka-configs.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --alter \
    --entity-type users --entity-name analytics-client \
    --add-config producer_byte_rate=10485760,consumer_byte_rate=20971520
# → Completed updating config for user analytics-client.

# 3. Лимит на входящие TCP-соединения с подозрительной подсети/IP
kafka-configs.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --alter \
    --entity-type ips --entity-name 192.168.1.100 \
    --add-config connection_creation_rate=5
# → Completed updating config for ip 192.168.1.100.

# 4. Просмотр ВСЕХ действующих настроек брокера (включая статические defaults из server.properties)
kafka-configs.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --describe \
    --entity-type brokers --entity-name 1 --all | grep -E "log.cleaner|num.network.threads"

# 5. ДИНАМИЧЕСКОЕ ИЗМЕНЕНИЕ УРОВНЯ ЛОГИРОВАНИЯ БРОКЕРА В RUNTIME (без рестарта)
# Включение подробного DEBUG-логирования для модуля репликации на брокере 1:
kafka-configs.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --alter \
    --entity-type broker-loggers --entity-name 1 \
    --add-config kafka.server.ReplicaManager=DEBUG
# → Completed updating config for broker-logger 1.

# Возврат уровня логирования обратно к INFO после локализации сбоя:
kafka-configs.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --alter \
    --entity-type broker-loggers --entity-name 1 \
    --add-config kafka.server.ReplicaManager=INFO
# → Completed updating config for broker-logger 1.

# 6. Удаление динамического переопределения (возврат к значению по умолчанию кластера)
kafka-configs.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --alter \
    --entity-type topics --entity-name orders \
    --delete-config max.message.bytes
# → Completed updating config for topic orders.
```

---

### Сценарий 5: Управление правами доступа (ACL)

Управление списками контроля доступа базируется на принципалах (`User:<name>`), ресурсах (`--topic`, `--group`, `--cluster`), типах операций и политиках (`--allow` / `--deny`).

```bash
# 1. Выдача прав продюсеру на конкретный топик (Write, Describe, Create)
kafka-acls.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --add \
    --allow-principal User:svc-orders-backend \
    --producer \
    --topic orders
# → Adding ACLs for resource `ResourcePattern(resourceType=TOPIC, name=orders, patternType=LITERAL)`:
# → 	(principal=User:svc-orders-backend, host=*, operation=WRITE, permissionType=ALLOW)...

# 2. Выдача прав консьюмеру (для чтения консьюмеру ТРЕБУЮТСЯ права на топик И группу)
kafka-acls.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --add \
    --allow-principal User:svc-billing-service \
    --consumer \
    --topic orders \
    --group billing-worker-group

# 3. Префиксные ACL для микросервисов с динамическими именами топиков
kafka-acls.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --add \
    --allow-principal User:svc-telemetry \
    --operation Read \
    --topic telemetry- \
    --resource-pattern-type prefixed

# 4. Явный запрет (Deny) — имеет абсолютный приоритет над любыми Allow
kafka-acls.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --add \
    --deny-principal User:contractor-temp \
    --operation Read \
    --topic financial-ledger

# 5. Просмотр действующих ACL для ресурса
kafka-acls.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --list --topic orders
# → Current ACLs for resource `Topic:LITERAL:orders`:
# →   (principal=User:svc-orders-backend, host=*, operation=WRITE, permissionType=ALLOW)

# 6. Удаление правила
kafka-acls.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --remove \
    --allow-principal User:contractor-temp --operation Read --topic financial-ledger --force
```

> [!NOTE]
> Учетные записи, перечисленные в параметре брокера `super.users` (например, `super.users=User:admin;User:kafka`), обходят любые ограничения механизма авторизации и не требуют явных записей в ACL.

---

### Сценарий 6: Обслуживание дисков, кворума KRaft и миграция партиций

#### Перераспределение партиций (Partition Reassignment)

При добавлении нового брокера в кластер или выводе старого из эксплуатации партиции не перемещаются автоматически. Перемещение выполняется утилитой `kafka-reassign-partitions.sh` в три этапа:

```bash
# ШАГ 1: Подготовка списка перемещаемых топиков и генерация плана
cat << 'EOF' > /tmp/topics-move.json
{
  "topics": [{"topic": "orders"}],
  "version": 1
}
EOF

# Генерация плана миграции на брокеры 1, 2, 3, 4:
kafka-reassign-partitions.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties \
    --topics-to-move-json-file /tmp/topics-move.json \
    --broker-list "1,2,3,4" \
    --generate > /tmp/raw-plan.json

# Вывод содержит два блока:
# 1) "Current partition replica assignment" — СОХРАНИТЕ ЕГО КАК ПЛАН ОТКАТА (rollback.json)!
# 2) "Proposed partition reassignment configuration" — целевой план (plan.json).
```

```bash
# ШАГ 2: Запуск выполнения плана С ОБЯЗАТЕЛЬНЫМ ОГРАНИЧЕНИЕМ СКОРОСТИ (Throttle)
# 50000000 байт/сек = 50 МБ/сек (защита сети и дисков от перегрузки)
kafka-reassign-partitions.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties \
    --reassignment-json-file /tmp/plan.json \
    --execute \
    --throttle 50000000
# → Successfully started partition reassignment for orders-0, orders-1...

# ШАГ 3: Контроль завершения и СНЯТИЕ ТРОТТЛИНГА (критически важно!)
kafka-reassign-partitions.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties \
    --reassignment-json-file /tmp/plan.json \
    --verify
# → Status of partition reassignment:
# → Reassignment of partition orders-0 is completed.
# → Reassignment of partition orders-1 is completed.
# → Clearing broker-level throttles...
# → Clearing topic-level throttles...
# → Verification completed successfully.
```

> [!IMPORTANT]
> Если не запустить команду с ключом `--verify` после окончания переноса, установленный лимит пропускной способности репликации (`leader.replication.throttled.rate` / `follower.replication.throttled.rate`) останется активным на брокерах, замедляя штатную синхронизацию ISR!

В случае необходимости отмены зависшей миграции используется флаг `--cancel`:
```bash
kafka-reassign-partitions.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties \
    --reassignment-json-file /tmp/plan.json \
    --cancel
```

#### Принудительные выборы предпочтительных лидеров

После перезапуска или сетевого сбоя лидерство партиций может распределиться неравномерно. Восстановление приоритетных лидеров:

```bash
kafka-leader-election.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties \
    --election-type PREFERRED \
    --all-topic-partitions
# → Successfully started leader election for partitions orders-0, orders-1...
```

#### Инспекция дискового пространства и сегментов данных

```bash
# 1. Проверка размера данных по каталогам и партициям брокеров
kafka-log-dirs.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties \
    --describe --broker-list 1,2,3 --topic-list orders | jq .
# → { "brokers": [ { "broker": 1, "logDirs": [ { "logDir": "/var/lib/kafka/data", "partitions": [ { "partition": "orders-0", "size": 154210400 } ] } ] } ] }

# 2. Низкоуровневая инспекция сегмента журнала (выполняется НА ХОСТЕ брокера)
kafka-dump-log.sh --files /var/lib/kafka/data/orders-0/00000000000000000000.log \
    --print-data-log \
    --deep-iteration | head -n 20
# → baseOffset: 0 lastOffset: 12 baseTimestamp: 1728560000000 ...
# → | offset: 0 CreateTime: 1728560000000 keySize: 8 valueSize: 45 payload: {"order_id": 5510}

# 3. Проверка целостности индексных файлов
kafka-dump-log.sh --files /var/lib/kafka/data/orders-0/00000000000000000000.index \
    --verify-index-only
# → /var/lib/kafka/data/orders-0/00000000000000000000.index is valid.

# 4. Чтение журнала метаданных KRaft (__cluster_metadata)
kafka-dump-log.sh --files /var/lib/kafka/data/__cluster_metadata-0/00000000000000000000.log \
    --cluster-metadata-decoder | head -n 30
```

#### Диагностика кворума метаданных KRaft

```bash
# 1. Статус кворума контроллеров (лидер, эпоха, активные voters)
kafka-metadata-quorum.sh --bootstrap-server 10.0.10.11:9092 describe --status
# → ClusterId:              5L6g3nShT-eMCtK--X86sw
# → LeaderId:               1
# → LeaderEpoch:            4
# → HighWatermark:          85230
# → MaxFollowerLag:         0
# → MaxFollowerLagTimeMs:   25
# → CurrentVoters:          [{"id": 1, "directoryId": "...", "endpoints": ["..."]}, ...]

# 2. Детальный лаг репликации метаданных по контроллерам
kafka-metadata-quorum.sh --bootstrap-server 10.0.10.11:9092 describe --replication

# 3. Инспекция версии метаданных и доступных фичей (Metadata Version)
kafka-features.sh --bootstrap-server 10.0.10.11:9092 describe
# → Feature: metadata.version	SupportedMinVersion: 3.3-IV0	SupportedMaxVersion: 4.0-IV3	FinalizedVersionLevel: 3.9-IV0

# 4. Повышение версии метаданных после завершения обновления всех брокеров
kafka-features.sh --bootstrap-server 10.0.10.11:9092 upgrade --metadata 4.0
# → Feature metadata.version was successfully upgraded to 4.0.
```

#### Инициализация и форматирование хранилища KRaft

При развертывании узла на bare-metal или виртуальной машине каталоги данных форматируются утилитой `kafka-storage.sh`:

```bash
# 1. Генерация уникального Base64 Cluster ID (один на весь кластер)
KAFKA_CLUSTER_ID="$(kafka-storage.sh random-uuid)"
echo "Generated Cluster ID: $KAFKA_CLUSTER_ID"
# → Generated Cluster ID: 5L6g3nShT-eMCtK--X86sw

# 2. Форматирование каталогов данных первого узла
kafka-storage.sh format \
    --cluster-id "$KAFKA_CLUSTER_ID" \
    --config /opt/kafka/config/kraft/server.properties \
    --ignore-formatted
# → Formatting /var/lib/kafka/data with metadata.version 3.9-IV0.

# 3. Проверка форматирования существующего каталога
kafka-storage.sh info --config /opt/kafka/config/kraft/server.properties
# → The log directory /var/lib/kafka/data is formatted with cluster ID 5L6g3nShT-eMCtK--X86sw
```

#### Поиск зависших транзакций

В кластерах с транзакционными продюсерами незавершенная транзакция блокирует чтение консьюмерам в режиме `isolation.level=read_committed`:

```bash
# Поиск зависших транзакций на брокере
kafka-transactions.sh --bootstrap-server 10.0.10.11:9092 find-hanging --broker 1
# → TransactionalId: order-tx-processor-1, ProducerId: 1042, ProducerEpoch: 3, Coordinator: 1

# Принудительное прерывание зависшей транзакции (Abort)
kafka-transactions.sh --bootstrap-server 10.0.10.11:9092 abort \
    --topic orders --partition 0 \
    --producer-id 1042 --producer-epoch 3 --coordinator-epoch 1
```

---

### Сценарий 7: Бенчмаркинг и нагрузочное тестирование

Встроенные утилиты дистрибутива позволяют оценить производительность дисковой подсистемы и сети перед вводом кластера в эксплуатацию.

```bash
# 1. Тестирование пропускной способности продюсера (1 000 000 записей по 1 КБ)
# Флаг --throughput -1 отключает искусственное ограничение скорости для поиска максимального потолка
kafka-producer-perf-test.sh --topic perf-test-topic \
    --num-records 1000000 \
    --record-size 1024 \
    --throughput -1 \
    --producer-props \
        bootstrap.servers=10.0.10.11:9092 \
        acks=all \
        compression.type=lz4 \
        linger.ms=20 \
        batch.size=65536
# → 1000000 records sent, 185240.2 records/sec (180.90 MB/sec), 24.12 ms avg latency, 412.00 ms max latency, 18 ms 50th, 55 ms 95th, 120 ms 99th, 280 ms 99.9th.

# 2. Тестирование пропускной способности консьюмера
kafka-consumer-perf-test.sh --bootstrap-server 10.0.10.11:9092 \
    --topic perf-test-topic \
    --messages 1000000 \
    --threads 1 \
    --consumer-property group.id=perf-eval-group
# → start.time, end.time, data.consumed.in.MB, MB.sec, data.consumed.in.nMsg, nMsg.sec, rebalance.time.ms, fetch.time.ms
# → 2026-10-12 14:00:00:000, 2026-10-12 14:00:05:420, 976.56, 180.18, 1000000, 184501.8, 120, 5300

# 3. Измерение сквозной задержки End-to-End (отправка сообщения и замер времени возврата)
kafka-run-class.sh kafka.tools.EndToEndLatency 10.0.10.11:9092 perf-test-topic 500 1 1024
# → Avg latency: 2.45 ms, Min: 1.82 ms, Max: 7.15 ms
```

---

### Сценарий 8: Автоматизация и headless-скрипты SRE

При использовании утилит в сценариях мониторинга, bash-скриптах и CI/CD критичны: корректная обработка кодов возврата (`exit code`), подавление лишнего вывода и исключение зависаний по таймауту.

```bash
#!/usr/bin/env bash
set -euo pipefail

BOOTSTRAP="10.0.10.11:9092"
CONFIG="/etc/kafka/client.properties"
CRITICAL_LAG=5000

# Пример: проверка суммарного лага группы без участия JVM с мгновенным возвратом через rpk
TOTAL_LAG=$(rpk group lag orders-worker-group --brokers "$BOOTSTRAP" --format json \
  | jq '[.[] | .lag] | add')

if [ "$TOTAL_LAG" -gt "$CRITICAL_LAG" ]; then
    echo "CRITICAL: Consumer lag for orders-worker-group is $TOTAL_LAG (exceeds $CRITICAL_LAG)" >&2
    exit 2
fi

echo "OK: Consumer lag is normal ($TOTAL_LAG)"
exit 0
```

Проверка доступности брокеров в CI/CD конвейере через `kcat`:

```bash
# Проверка сетевого кворума с жестким таймаутом в 3 секунды
if kcat -b 10.0.10.11:9092 -L -X socket.timeout.ms=3000 > /dev/null 2>&1; then
    echo "Kafka cluster is ready"
else
    echo "Kafka cluster is unreachable" >&2
    exit 1
fi
```

---

## Диагностика и устранение неполадок

### Матрица типовых ошибок при вызове CLI

| Симптом / Ошибка | Вероятная причина | Метод быстрой диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| `TimeoutException: Timed out waiting for a node assignment` / `Connection to node -1 could not be established` | Недоступен порт брокера, закрыт сетевой экран (firewall) или в кластере неверно настроен `advertised.listeners` | `nc -zv <host> 9092`<br>`openssl s_client -connect <host>:9093` | Проверить сетевые маршруты; в `server.properties` брокеров убедиться, что `advertised.listeners` возвращает доступные клиенту IP/DNS |
| `SaslAuthenticationException: Authentication failed` / `Invalid credentials` | Ошибка в учетных данных, несовпадение `sasl.mechanism` или синтаксическая ошибка в JAAS | Запуск `kcat` с явными флагами `-X sasl.username=... -X sasl.password=...` | Проверить точку с запятой `;` в конце `sasl.jaas.config`; убедиться, что пользователь зарегистрирован через `kafka-configs.sh` |
| `TopicAuthorizationException` / `GroupAuthorizationException` | У клиента отсутствуют права доступа в ACL для запрошенного ресурса | `kafka-acls.sh --list --topic <topic>` | Добавить недостающие ACL через `kafka-acls.sh --add` (для консьюмера требуются права на Topic И Group!) |
| `CommitFailedException` / `GroupNotEmptyException` при сбросе офсетов | Инстансы группы потребителей продолжают работать во время вызова `--reset-offsets` | `kafka-consumer-groups.sh --describe --group <group> --state` | Остановить все поды/процессы приложения-консьюмера; убедиться, что состояние группы перешло в `Empty` |
| Сброс офсетов завершился без ошибок, но смещения не изменились | Команда выполнена в режиме Dry-run, пропущен обязательный флаг `--execute` | Проверка `CURRENT-OFFSET` через `--describe` | Повторить команду с обязательным флагом `--execute` в конце аргументов |
| `java.lang.OutOfMemoryError: Java heap space` при запуске утилиты | Переменная `KAFKA_HEAP_OPTS` унаследована от серверного профиля или не задана в окружении с жестким лимитом cgroups | `echo $KAFKA_HEAP_OPTS` | Явно задать перед вызовом утилиты: `export KAFKA_HEAP_OPTS="-Xmx512M -Xms128M"` |
| `UnrecognizedOptionException: command-config is not a recognized option` | Передан неверный конфигурационный флаг для типа утилиты | Проверка синтаксиса: `kafka-console-consumer.sh --help` | Для консольного консьюмера использовать `--consumer.config`, для продюсера — `--producer.config` |
| Ребалансировка завершена, но репликация в кластере работает аномально медленно | Не сняты квоты троттлинга (`leader.replication.throttled.rate`), пропущен шаг `--verify` | `kafka-configs.sh --describe --entity-type brokers --entity-name 1` | Выполнить `kafka-reassign-partitions.sh --verify` с исходным JSON-файлом миграции |

### Разбор диагностических кейсов

#### Кейс 1: Синтаксическая ошибка в JAAS-конфигурации

Симптом: Утилиты Java падают с ошибкой `IllegalArgumentException: Could not find a 'KafkaClient' entry in JAAS configuration` или `SecurityException`.

Причина: В файле `client.properties` строка `sasl.jaas.config` должна быть строго валидной для Java JAAS-парсера:
1. Имя класса: `org.apache.kafka.common.security.scram.ScramLoginModule` (или `PlainLoginModule`).
2. Флаг: `required`.
3. Обязательная точка с запятой `;` в самом конце строки после параметров.

Корректный синтаксис:
```properties
sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="alice" password="password123";
```

#### Кейс 2: Зависшая миграция партиций

Симптом: Повторный запуск миграции возвращает: `There is an existing reassignment in progress for partitions...`.

Диагностика и решение:
1. Проверить статус миграции:
   ```bash
   kafka-reassign-partitions.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties \
       --reassignment-json-file /tmp/plan.json --verify
   ```
2. Если миграция зависла из-за недоступности целевого брокера или переполнения диска, прервать операцию:
   ```bash
   kafka-reassign-partitions.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties \
       --reassignment-json-file /tmp/plan.json --cancel
   ```
3. Принудительно очистить динамические квоты троттлинга на топике:
   ```bash
   kafka-configs.sh --bootstrap-server 10.0.10.11:9092 --command-config client.properties --alter \
       --entity-type topics --entity-name orders \
       --delete-config leader.replication.throttled.replicas,follower.replication.throttled.replicas
   ```

---

## Рекомендации и лучшие практики

1. **Безопасное хранение учетных данных**:
   - Никогда не передавать логины, пароли и токены параметрами командной строки (они сохраняются в `/root/.bash_history`, `/proc/<pid>/cmdline` и видны через `ps aux`).
   - Использовать файлы конфигураций (`client.properties`, `~/.config/kcat.conf`, `~/.config/kafkactl/config.yml`) с обязательным ограничением прав: `chmod 600`.
2. **Предпочтение легковесным CLI для мониторинга и CI/CD**:
   - Избегать запуска стандартных скриптов `bin/kafka-*.sh` в периодических заданиях (cron, проверки здоровья раз в 5 секунд). Каждое обращение тратит 2–3 секунды на инициализацию JVM и считывание метаданных.
   - Использовать `kcat` или `rpk` для автоматизации — они отрабатывают за десятки миллисекунд и не создают скачков потребления оперативной памяти.
3. **Строгий двухэтапный регламент изменения смещений**:
   - Любой сброс офсетов (`--reset-offsets`) начинать с фазы Dry-run. Всегда сверять планируемые смещения с реальными `LOG-END-OFFSET` перед передачей ключа `--execute`.
4. **Обязательное ограничение пропускной способности миграций**:
   - При перемещении партиций (`kafka-reassign-partitions.sh`) на работающем кластере всегда задавать параметр `--throttle <bytes_per_sec>`, рассчитывая лимит как не более 25–30% от свободной полосы диска или сетевого интерфейса брокера.
   - Завершать процедуру вызовом `--verify` для очистки throttling-квот.
5. **Контроль кворума KRaft перед регламентными работами**:
   - Перед перезапуском или выводом узла в обслуживание обязательно проверить статус кворума метаданных через `kafka-metadata-quorum.sh describe --status`. Ни в коем случае не останавливать контроллер, если `MaxFollowerLag` отличен от нуля или кворум находится в состоянии репликационного отставания.
6. **Автоматизация балансировки лидеров**:
   - Регулярно запускать проверку `kafka-topics.sh --describe --under-min-isr-partitions` и восстанавливать баланс лидеров партиций командой `kafka-leader-election.sh --election-type PREFERRED --all-topic-partitions`.

---

## Дополнительная информация

### Матрица выбора инструментов

```
                  ┌─────────────────────────────┐
                  │    Какая задача решается?   │
                  └──────────────┬──────────────┘
                                 │
         ┌───────────────────────┼────────────────────────┐
         ▼                       ▼                        ▼
┌──────────────────┐    ┌──────────────────┐     ┌──────────────────┐
│ Чтение / отладка │    │   Повседневное   │     │  Низкоуровневое  │
│  потоков данных  │    │ администрирование│     │   обслуживание   │
└────────┬─────────┘    └────────┬─────────┘     └────────┬─────────┘
         │                       │                        │
         ▼                       ▼                        ▼
      [ kcat ]             [ rpk / kafkactl ]      [ Standard CLI ]
 (быстрый запуск,        (профили, быстрый lag,   (reassign, KRaft,
  фильтры jq, таймстампы) топики, группы, ACL)     log dump, perf-test)
```

- **kcat**: Незаменим для разработчиков, SRE и data engineers при исследовании данных, проверке форматов сообщений и написании shell-пайплайнов.
- **rpk**: Оптимальный выбор для повседневных системных операций (топики, группы, ACL). Мгновенный отклик, удобный синтаксис.
- **kafkactl**: Лучший выбор для сред со множеством кластеров, при работе с Schema Registry (Avro/Protobuf) и в Kubernetes-кластерах.
- **Стандартные утилиты**: Обязательный инструментарий системного администратора для глубоких задач: переноса партиций, работы с метаданными KRaft, форматирования дисков и прямого чтения файлов журнала.

### Ограничения и краевые случаи

- **JVM Startup Overhead**: Каждое выполнение стандартных утилит порождает новый процесс Java с оверхедом в 1.5–3.5 секунды. В циклах обработки по множеству топиков всегда используйте групповые аргументы (`--all-groups`, `--all-topic-partitions`) либо утилиты `rpk`/`kafkactl`.
- **Строгие требования к Java 17+**: Дистрибутив Kafka 4.x не поддерживает Java 8 и 11 (KIP-750). Запуск утилит на устаревших JVM приведет к ошибке `UnsupportedClassVersionError`.
- **Специфика bat-скриптов в Windows**: В командных сценариях Windows (`bin/windows/`) правила экранирования спецсимволов и кавычек в аргументах свойств (`--property parse.key=true`) отличаются от POSIX-оболочек. Сложные сценарии надежнее исполнять в WSL2 или контейнерах Linux.
- **Ограничения rpk при работе с Apache Kafka**: Базовые команды (`topic`, `group`, `acl`) полностью совместимы со стандартным бинарным протоколом Kafka. Однако команды управления кластером (`rpk cluster config`, tiered storage) работают исключительно с Redpanda.
- **Доступ к локальным дискам для dump-log**: Утилита `kafka-dump-log.sh` не использует сетевой протокол Kafka — она открывает файлы сегментов (`.log`, `.index`) напрямую с блочного устройства хоста.
- **Защита метаданных KRaft при форматировании**: Повторный запуск команды `kafka-storage.sh format` с тем же или новым Cluster ID на работающем каталоге без флага `--ignore-formatted` приведет к ошибке, а при некорректной очистке каталога — к повреждению кворума метаданных кластера.

### См. также

- **[Обзор Apache Kafka](./kafka_overview.md)** — архитектура кластера, брокеры, контроллеры и протокол репликации.
- **[Партиционирование и балансировка](./partitioning_and_balancing.md)** — математика распределения партиций, выбор ключей и балансировка.
- **[Гарантии доставки](./delivery_guarantees.md)** — семантика доставки сообщений (at-least-once, exactly-once), настройки `acks` и `min.insync.replicas`.
- **[Troubleshooting Playbook для Apache Kafka](./kafka_troubleshooting_playbook.md)** — пошаговые алгоритмы локализации инцидентов и деревья решений.
- **[Развертывание Kafka в Docker](./kafka_docker_setup.md)** — контейнеризация Kafka в режиме KRaft и локальные стенды.
- **[Мониторинг Kafka](./kafka_for_monitoring.md)** — ключевые метрики JMX, правила алертинга и экспортеры.
- **[Тюнинг JVM и GC для Kafka](./kafka_jvm_gc_tuning.md)** — параметры сборщиков мусора (G1GC) и профилирование памяти.
- **[Strimzi Kafka Operator](./strimzi_kafka_operator.md)** — эксплуатация Kafka в Kubernetes через оператор Strimzi.
