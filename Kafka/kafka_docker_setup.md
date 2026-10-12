# Развертывание Apache Kafka в Docker (KRaft)

**Актуально для:** Apache Kafka 3.8.x / 3.9.x / 4.0.x (KRaft), Docker Engine 24+ / 27+, Docker Compose v2

Использование Docker является стандартом для локальной разработки, функционального тестирования и создания изолированных стендов Apache Kafka. Контейнеризация позволяет развернуть воспроизводимый кластер с веб-интерфейсом управления и мониторингом за считанные минуты, гарантируя изоляцию зависимостей и независимость от устаревшего ZooKeeper (полностью удаленного в Kafka 4.0).

---

## Определения

- **Kafka Broker (KRaft mode):** Современная архитектура управления метаданными на основе протокола консенсуса Raft (KIP-500), исключающая зависимость от ZooKeeper. Роли контроллера и брокера могут быть совмещены в одном контейнере (**combined mode**) либо разнесены по отдельным контейнерам (**isolated mode**).
- **Официальный образ `apache/kafka`:** Официальный JVM-образ от Apache Software Foundation (публикуется на Docker Hub начиная с версии 3.7.0). Базируется на Ubuntu/Eclipse Temurin, работает от непривилегированного пользователя `appuser` (UID 1000).
- **`apache/kafka-native`:** Экспериментальный GraalVM-based нативный образ (начиная с версии 3.8.0). Обеспечивает быстрый старт (< 1 с) и низкое потребление базовой RAM (~50–100 МБ), но предназначен исключительно для локальных тестов; не поддерживает SASL-аутентификацию (KAFKA-19584) и внешние плагины.
- **Kafka UI (Kafbat UI):** Веб-интерфейс для управления топиками, просмотра сообщений, мониторинга consumer lag и конфигураций. Актуальный активно поддерживаемый форк: **Kafbat UI** (образ `ghcr.io/kafbat/kafka-ui`). Исходный проект `provectuslabs/kafka-ui` заброшен с 2023 года.
- **Слушатели (Listeners):** Сетевые интерфейсы брокера. Разграничивают трафик: внутренний (`PLAINTEXT` для контейнеров внутри bridge-сети Docker), внешний (`PLAINTEXT_HOST` для хост-машины и разработчиков) и контроллерный (`CONTROLLER` для кворума KRaft).
- **Cluster ID:** Уникальный 16-байтный Base64-идентификатор кластера KRaft. Генерируется утилитой `kafka-storage.sh random-uuid` и записывается в файл `meta.properties` каждого узла при форматировании хранилища.
- **Graceful Shutdown (`controlled.shutdown`):** Механизм штатной остановки брокера. При получении сигнала `SIGTERM` брокер сбрасывает dirty pages из PageCache на диск и передает лидерство партиций другим репликам, исключая долгий этап Log Recovery при следующем старте.
- **PageCache & Zero-Copy:** Модель подсистемы I/O в Kafka. Основное кэширование сегментов логов выполняет кэш страниц ядра ОС хоста, а отправка сообщений сетевым клиентам производится через системный вызов `sendfile()` напрямую из файлового дескриптора в сокет без копирования в JVM Heap.

---

## Основные концепции

### Выбор базового образа

| Образ | Статус | Назначение и ограничения |
| :--- | :--- | :--- |
| `apache/kafka` | Официальный, JVM | Стандарт для разработки, staging и production-like стендов. Полная поддержка SASL/TLS, JMX, плагинов. |
| `apache/kafka-native` | Экспериментальный, GraalVM | Ультрабыстрый старт для короткоживущих интеграционных тестов. Не поддерживает SASL; не для production. |
| `confluentinc/cp-kafka` | Коммерческая экосистема | Применяется, если необходимы сопутствующие компоненты Confluent Platform (Schema Registry, Control Center, Connectors). |
| `bitnami/kafka` | Недоступен бесплатно | С августа 2025 года образы Bitnami перенесены в `bitnamilegacy/*` без обновлений безопасности либо лицензируются платно. Существующие стенды следует переводить на `apache/kafka`. |

### Архитектурные режимы KRaft в контейнерах

1. **Combined Mode (`KAFKA_PROCESS_ROLES: broker,controller`):**
   - Роли брокера данных и контроллера метаданных выполняются одним Java-процессом.
   - Минимальное потребление ресурсов хоста: идеален для локальных стендов, CI/CD runner и сред разработки.
2. **Isolated Mode (раздельные контейнеры):**
   - Контроллеры (`controller`) управляют только кворумом Raft и метаданными, не обслуживая клиентский трафик и партиции топиков.
   - Брокеры (`broker`) обслуживают чтение/запись данных и клиентуру.
   - Исключает деградацию кворума Raft при пиковой дисковой или сетевой нагрузке на брокеры в high-load окружениях.

### Сетевая модель и маршрутизация Listeners

Клиент Kafka подключается к кластеру в два этапа:
1. **Первичный handshake:** клиент подключается к любому адресу из списка `bootstrap.servers` (например, `localhost:9092`).
2. **Получение метаданных:** брокер возвращает клиенту список лидеров партиций и их адреса из своего параметра `advertised.listeners`. После этого все операции чтения/записи идут строго по этим адресам.

```
Хост-машина (Разработчик / CLI / kcat)
  │
  │  1. Подключение к localhost:9092
  ▼
[Docker Port Forwarding: 9092 → 9092]
  │
  ▼
Контейнер Kafka:
  ├── Слушатель PLAINTEXT_HOST (0.0.0.0:9092)
  │     └─ Отдает advertised.listener: localhost:9092  ──► Клиент переподключается на localhost:9092
  ├── Слушатель PLAINTEXT (0.0.0.0:19092)
  │     └─ Отдает advertised.listener: kafka-broker:19092 ──► Контейнеры сети Compose общаются напрямую
  └── Слушатель CONTROLLER (0.0.0.0:9093)
        └─ Внутренний обмен кворума KRaft (голоса, репликация метаданных)
```

**Классические сетевые дефекты:**
- *Хост не может подключиться после bootstrap:* брокер отдает `advertised.listeners` с именем контейнера (`kafka-broker:9092`), которое хост не может разрезолвить в DNS.
- *Контейнеры внутри docker-сети не видят брокер:* брокер отдает `localhost:9092`, и контейнеры пытаются подключиться к собственному loopback-интерфейсу.
- *Решение:* всегда настраивать минимум два раздельных слушателя — внутренний и внешний.

### Модель памяти и ресурсов контейнера (SRE)

Kafka архитектурно отличается от типичных Java-приложений:
- **JVM Heap:** хранит исключительно индексы, кэш метаданных контроллера, временные сетевые буферы и объекты соединений. Для брокера среднего стенда достаточно 1–2 ГБ Heap (`-Xms1g -Xmx1g`).
- **Off-Heap & Direct Memory:** используется Netty и внутренними буферами сжатия сообщений (Snappy/zstd/LZ4).
- **PageCache (ОС хоста):** именно в системном кэше страниц операционной системы оседают недавно записанные сегменты логов, откуда они мгновенно отдаются консьюмерам через Zero-Copy `sendfile()`.

> **Критическое правило SRE:** Лимит памяти контейнера (`mem_limit`) **никогда не должен быть равен** размеру JVM Heap. Если выделить контейнеру 2 ГБ и задать `-Xmx2g`, брокер гарантированно будет уничтожен ядром ОС по OOMKilled (Exit Code 137) из-за накладных расходов JVM и потоков. Безопасное соотношение:
> `Container Memory Limit = JVM Heap + (1...2 ГБ под Off-Heap/OS) + запас под PageCache`.

### Хранилище, I/O и права доступа (Sysadmin)

- **Монтирование данных:** в официальном образе каталог данных — `/var/lib/kafka/data`.
- **Именованные тома (`named volumes`) vs Bind Mounts:**
  - Именованные тома предпочтительны: Docker автоматически создает их с корректным владельцем.
  - При монтировании каталога с хоста (`bind mount`) процесс завершится ошибкой `Permission denied`, так как контейнер запускается под пользователем `appuser` (UID 1000). Каталог на хосте перед запуском требует явной смены владельца: `chown -R 1000:1000 /opt/kafka-data`.
- **Файловая система:** на Linux-хостах рекомендуется монтировать накопители под тома Kafka с опцией `noatime` (файловые системы XFS или ext4), что предотвращает избыточные операции записи метаданных при чтении сегментов логов.

### Жизненный цикл и Graceful Shutdown (DevOps)

По умолчанию Docker посылает контейнеру сигнал `SIGTERM` и ожидает всего **10 секунд**, после чего принудительно завершает процесс сигналом `SIGKILL`. Для брокера Kafka этого времени недостаточно при наличии активных продюсеров и незафиксированных страниц.
При жестком завершении (`SIGKILL`):
1. Не сбрасываются индексы и заголовки сегментов логов.
2. Не передается лидерство по партициям соседним брокерам (`controlled.shutdown`).
3. При следующем старте брокер выполняет длительную валидацию и перестроение индексов (`Log Recovery`), продлевая downtime кластера.
4. **Решение:** в конфигурации сервиса Compose обязателен параметр `stop_grace_period: 60s` (или более).

---

## Практические сценарии

### Сценарий 1: Одноузловой Production-like стенд в Docker Compose (Рекомендуется)

Стек включает: брокер Kafka в режиме KRaft, веб-интерфейс Kafbat UI, явные лимиты ресурсов, ротацию логов контейнера и проверку работоспособности (`healthcheck`).

**Файл `compose.yaml`:**
```yaml
services:
  kafka:
    image: apache/kafka:4.0.0
    container_name: kafka-broker
    restart: unless-stopped
    stop_grace_period: 60s
    ports:
      - "9092:9092"
    environment:
      # --- Режим KRaft (Combined: брокер + контроллер) ---
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka-broker:9093
      CLUSTER_ID: 'Mk3OEYBSD34fcwNTJENDM2Qk'

      # --- Сетевые интерфейсы и слушатели ---
      # PLAINTEXT: внутри сети Compose (порт 19092)
      # PLAINTEXT_HOST: для хоста (порт 9092)
      # CONTROLLER: для кворума Raft (порт 9093)
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:19092,PLAINTEXT_HOST://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka-broker:19092,PLAINTEXT_HOST://localhost:9092
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT,CONTROLLER:PLAINTEXT
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER

      # --- Оптимизация для одноузлового кластера ---
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1
      KAFKA_DEFAULT_REPLICATION_FACTOR: 1
      KAFKA_NUM_PARTITIONS: 3

      # --- Управление памятью JVM ---
      KAFKA_HEAP_OPTS: "-Xms1g -Xmx1g"
      KAFKA_LOG_DIRS: "/var/lib/kafka/data"
    volumes:
      - kafka_data:/var/lib/kafka/data
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2560M
        reservations:
          cpus: '1.0'
          memory: 1536M
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    healthcheck:
      test: ["CMD-SHELL", "kafka-topics.sh --bootstrap-server localhost:9092 --list"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 25s

  kafka-ui:
    image: ghcr.io/kafbat/kafka-ui:latest
    container_name: kafka-ui
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      KAFKA_CLUSTERS_0_NAME: local-cluster
      KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS: kafka-broker:19092
    depends_on:
      kafka:
        condition: service_healthy
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  kafka_data:
    name: kafka_single_node_data
```

**Запуск и проверка стека:**
```bash
docker compose up -d
# → [+] Running 3/3
# →  ✔ Network compose_default  Created
# →  ✔ Container kafka-broker   Healthy
# →  ✔ Container kafka-ui       Started

docker compose ps
# → NAME           IMAGE                         COMMAND                  SERVICE    STATUS                    PORTS
# → kafka-broker   apache/kafka:4.0.0            "/opt/kafka/bin/dock…"   kafka      Up (healthy)              0.0.0.0:9092->9092/tcp
# → kafka-ui       ghcr.io/kafbat/kafka-ui:latest "/bin/sh -c 'java --…"   kafka-ui   Up                        0.0.0.0:8080->8080/tcp
```

Детали синтаксиса Compose: [Docker Compose — обзор](../Docker/Docker_compose/docker_compose_overview.md).

---

### Сценарий 2: Быстрый запуск standalone через Docker CLI

Если требуется поднять изолированный брокер без составления YAML-манифестов:

```bash
docker run -d \
  --name kafka-standalone \
  --restart unless-stopped \
  --stop-timeout 60 \
  -p 9092:9092 \
  -e KAFKA_NODE_ID=1 \
  -e KAFKA_PROCESS_ROLES=broker,controller \
  -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@localhost:9093 \
  -e KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093 \
  -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://localhost:9092 \
  -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
  -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
  -e KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1 \
  -e KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1 \
  -e KAFKA_HEAP_OPTS="-Xms1g -Xmx1g" \
  -e CLUSTER_ID='Mk3OEYBSD34fcwNTJENDM2Qk' \
  -m 2048m \
  -v kafka_standalone_data:/var/lib/kafka/data \
  apache/kafka:4.0.0
# → c8b7468e712a32c5240bcfe74e12e75e9f143715c0e4da3bf8b67f10b78c6e5a
```

*Примечание:* Запуск `docker run -d -p 9092:9092 apache/kafka:4.0.0` без переменных окружения поднимает брокер со встроенным сгенерированным Cluster ID и дефолтными настройками. Однако в этом случае advertised listener привязывается к сетевому имени контейнера, что делает его недоступным с хоста без явной правки `KAFKA_ADVERTISED_LISTENERS`.

---

### Сценарий 3: Отказоустойчивый мультиброкерный кластер (3 узла KRaft)

Полноценный стенд с кворумом Raft из трех узлов. При трех брокерах настройки фактора репликации (`offsets.topic.replication.factor=3`, `transaction.state.log.min.isr=2`) соответствуют промышленным стандартам. Использование YAML-якорей исключает дублирование общих параметров.

**Файл `compose.yaml`:**
```yaml
x-kafka-common: &kafka-common
  image: apache/kafka:4.0.0
  restart: unless-stopped
  stop_grace_period: 60s
  logging:
    driver: "json-file"
    options:
      max-size: "10m"
      max-file: "3"
  environment: &kafka-env
    KAFKA_PROCESS_ROLES: broker,controller
    KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka-1:9093,2@kafka-2:9093,3@kafka-3:9093
    KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT,CONTROLLER:PLAINTEXT
    KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
    KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
    KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 3
    KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 3
    KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 2
    KAFKA_DEFAULT_REPLICATION_FACTOR: 3
    KAFKA_MIN_INSYNC_REPLICAS: 2
    KAFKA_HEAP_OPTS: "-Xms1g -Xmx1g"
    CLUSTER_ID: 'Mk3OEYBSD34fcwNTJENDM2Qk'

services:
  kafka-1:
    <<: *kafka-common
    container_name: kafka-1
    ports: ["29092:9092"]
    environment:
      <<: *kafka-env
      KAFKA_NODE_ID: 1
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:19092,PLAINTEXT_HOST://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka-1:19092,PLAINTEXT_HOST://localhost:29092
    volumes:
      - kafka_1_data:/var/lib/kafka/data

  kafka-2:
    <<: *kafka-common
    container_name: kafka-2
    ports: ["39092:9092"]
    environment:
      <<: *kafka-env
      KAFKA_NODE_ID: 2
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:19092,PLAINTEXT_HOST://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka-2:19092,PLAINTEXT_HOST://localhost:39092
    volumes:
      - kafka_2_data:/var/lib/kafka/data

  kafka-3:
    <<: *kafka-common
    container_name: kafka-3
    ports: ["49092:9092"]
    environment:
      <<: *kafka-env
      KAFKA_NODE_ID: 3
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:19092,PLAINTEXT_HOST://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka-3:19092,PLAINTEXT_HOST://localhost:49092
    volumes:
      - kafka_3_data:/var/lib/kafka/data

volumes:
  kafka_1_data:
  kafka_2_data:
  kafka_3_data:
```

**Проверка кворума Raft:**
```bash
docker exec -it kafka-1 kafka-metadata-quorum.sh --bootstrap-server localhost:9092 describe --status
# → ClusterId:              Mk3OEYBSD34fcwNTJENDM2Qk
# → LeaderId:               1
# → LeaderEpoch:            1
# → HighWatermark:          124
# → MaxFollowerLag:         0
# → MaxFollowerLagTimeMs:   12
# → CurrentVoters:          [1,2,3]
```

Архитектура репликации и кворума: [Партиционирование и балансировка](./partitioning_and_balancing.md).

---

### Сценарий 4: Защищенный стенд с SASL_PLAINTEXT и Docker Secrets (Sysadmin / Security)

Передача паролей в открытых переменных `environment` компрометирует безопасность: они видны в выводе `docker inspect <container>`. Для защищенных стендов конфигурационный файл JAAS монтируется в контейнер в режиме `read_only`.

**1. Подготовка файла JAAS (`kafka_jaas.conf`):**
```properties
KafkaServer {
    org.apache.kafka.common.security.plain.PlainLoginModule required
    username="admin"
    password="AdminSecurePassword123"
    user_admin="AdminSecurePassword123"
    user_client="ClientSecurePassword456";
};
```

**2. Конфигурация сервиса в `compose.yaml`:**
```yaml
services:
  kafka-secure:
    image: apache/kafka:4.0.0
    container_name: kafka-secure
    ports:
      - "9092:9092"
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@localhost:9093
      CLUSTER_ID: 'Mk3OEYBSD34fcwNTJENDM2Qk'
      KAFKA_LISTENERS: SASL_PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: SASL_PLAINTEXT://localhost:9092
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: SASL_PLAINTEXT:SASL_PLAINTEXT,CONTROLLER:PLAINTEXT
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_SASL_ENABLED_MECHANISMS: PLAIN
      KAFKA_SASL_MECHANISM_INTER_BROKER_PROTOCOL: PLAIN
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      # Передача JAAS через JVM опции
      KAFKA_OPTS: "-Djava.security.auth.login.config=/etc/kafka/secrets/kafka_jaas.conf"
    volumes:
      - ./kafka_jaas.conf:/etc/kafka/secrets/kafka_jaas.conf:ro
      - kafka_secure_data:/var/lib/kafka/data

volumes:
  kafka_secure_data:
```

Руководство по управлению секретами: [Управление секретами в Docker](../Docker/Docker_security/secrets_management.md).

---

### Сценарий 5: Мониторинг и наблюдаемость в Docker (SRE)

Для интеграции со стеком Prometheus/Grafana в compose-стек добавляется официальный экспортер метрик `kafka-exporter`. Он опрашивает брокер по протоколу Kafka RPC и отдает метрики consumer lag, брокеров и топиков.

**Фрагмент `compose.yaml` для мониторинга:**
```yaml
services:
  kafka-exporter:
    image: danielqsj/kafka-exporter:v1.8.0
    container_name: kafka-exporter
    restart: unless-stopped
    ports:
      - "9308:9308"
    command:
      - "--kafka.servers=kafka-broker:19092"
      - "--web.listen-address=:9308"
      - "--web.telemetry-path=/metrics"
    depends_on:
      kafka:
        condition: service_healthy
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

**Проверка метрик:**
```bash
curl -s http://localhost:9308/metrics | grep -E "kafka_brokers|kafka_consumergroup_lag"
# → # HELP kafka_brokers Number of Brokers in the Kafka Cluster.
# → # TYPE kafka_brokers gauge
# → kafka_brokers 1
# → # HELP kafka_consumergroup_lag Current Approximate Lag of Consumer Group at Topic/Partition
# → # TYPE kafka_consumergroup_lag gauge
```

Архитектура метрик и алертинга: [Мониторинг Apache Kafka](./kafka_for_monitoring.md).

---

## Операции и команды

### Управление жизненным циклом и кворумом

Все утилиты выполняются через `docker exec` внутри контейнера брокера:

| Операция | Команда | Назначение |
| :--- | :--- | :--- |
| **Статус кворума Raft** | `docker exec -it kafka-broker kafka-metadata-quorum.sh --bootstrap-server localhost:9092 describe --status` | Проверка активного лидера KRaft, эпохи и лага фолловеров |
| **Генерация Cluster ID** | `docker run --rm apache/kafka:4.0.0 kafka-storage.sh random-uuid` | Генерация нового UUID кластера без запуска брокера |
| **Список топиков** | `docker exec -it kafka-broker kafka-topics.sh --bootstrap-server localhost:9092 --list` | Просмотр существующих топиков кластера |
| **Создание топика** | `docker exec -it kafka-broker kafka-topics.sh --bootstrap-server localhost:9092 --create --topic telemetry --partitions 3 --replication-factor 1` | Создание топика с заданным числом партиций |
| **Детали топика** | `docker exec -it kafka-broker kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic telemetry` | Проверка лидеров партиций, ISR и конфигурации |
| **Consumer Groups & Lag** | `docker exec -it kafka-broker kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --all-groups` | Аудит лага консьюмеров и распределения партиций |

### Пример сквозного функционального тестирования

```bash
# 1. Создание топика
docker exec -it kafka-broker kafka-topics.sh --bootstrap-server localhost:9092 --create --topic app-logs --partitions 3 --replication-factor 1
# → Created topic app-logs.

# 2. Отправка тестовых сообщений
echo "event-test-message-1" | docker exec -i kafka-broker kafka-console-producer.sh --bootstrap-server localhost:9092 --topic app-logs
# → (сообщение отправлено, возврат 0)

# 3. Вычитка сообщений из топика
docker exec -it kafka-broker kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic app-logs --from-beginning --max-messages 1
# → event-test-message-1
# → Processed a total of 1 messages
```

Полный справочник по утилитам: [CLI-инструменты Kafka](./kafka_cli_tools.md).

### Резервное копирование и миграция данных тома Docker

Вне зависимости от операционной системы хоста, резервное копирование тома Docker выполняется через вспомогательный контейнер:

```bash
# 1. Остановка брокера для обеспечения консистентности log-файлов на диске
docker compose stop kafka

# 2. Создание tar-архива данных тома kafka_single_node_data в текущую директорию
docker run --rm \
  -v kafka_single_node_data:/source:ro \
  -v "$(pwd)":/backup \
  alpine tar czf /backup/kafka_data_backup.tar.gz -C /source .
# → (создан архив kafka_data_backup.tar.gz)

# 3. Восстановление архива в новый том на другом хосте
docker volume create kafka_restored_data
docker run --rm \
  -v kafka_restored_data:/target \
  -v "$(pwd)":/backup \
  alpine tar xzf /backup/kafka_data_backup.tar.gz -C /target

# 4. Запуск брокера
docker compose start kafka
```

Механика работы томов: [Docker Volumes](../Docker/Docker_fs/docker_volumes.md).

---

## Диагностика и устранение неполадок

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Connection Refused / Cannot connect to node -1** | Клиент подключается к адресу, который не указан в `advertised.listeners`, либо брокер возвращает неразрешимый для клиента хостнейм. | Проверить метаданные через `kcat -b localhost:9092 -L` или вывод `docker logs kafka-broker \| grep advertised.listeners`. | Разделять слушатели на `PLAINTEXT` (имя контейнера для docker-сети) и `PLAINTEXT_HOST` (`localhost:9092` для внешних клиентов). |
| **`InconsistentClusterIdException` при старте** | Том данных уже содержит файл `meta.properties` от предыдущего кластера, а в переменной `CLUSTER_ID` передан другой UUID. | В логах: `The Cluster ID Mk3... doesn't match stored cluster ID XYZ...`. | 1. Использовать фиксированный `CLUSTER_ID`, совпадающий с `meta.properties`.<br>2. Для полной очистки dev-стенда: `docker compose down -v`. |
| **`TimeoutException` / `LeaderNotAvailableException` при создании групп** | Фактор репликации внутренних топиков по умолчанию равен 3, а в кластере запущен только 1 брокер. | `docker logs kafka-broker \| grep offsets.topic.replication.factor`. | Задать `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1` и `KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1`. |
| **Контейнер падает с кодом 137 (OOMKilled)** | Лимит памяти контейнера (`mem_limit`) равен значению `KAFKA_HEAP_OPTS`, ядро завершило процесс при выделении Direct Memory. | `docker inspect kafka-broker --format='{{.State.OOMKilled}}'` возвращает `true`. | Выделить под контейнер минимум на 1–1.5 ГБ больше RAM, чем `-Xmx`, либо снизить `-Xmx` до `512M`–`1G`. |
| **Долгий старт брокера и сканирование сегментов (Dirty Shutdown)** | Контейнер остановлен по `SIGKILL` из-за нехватки стандартного 10-секундного таймаута Docker. | В логах: `Found unclean shutdown file... Recovering open segments`. | Добавить в `compose.yaml` директиву `stop_grace_period: 60s`. |
| **`Permission denied` при записи в `/var/lib/kafka/data`** | При использовании bind-mount директория на Linux-хосте принадлежит `root`, а процесс в контейнере работает от UID 1000 (`appuser`). | `ls -ld /opt/kafka-data` на хосте показывает владельца `root:root`. | Выполнить на хосте: `chown -R 1000:1000 /opt/kafka-data`. Либо перейти на именованные Docker тома. |
| **Kafka UI показывает статус Offline** | Контейнер UI запустился раньше, чем брокер завершил инициализацию метаданных KRaft. | В логах UI: `Connection to kafka-broker:19092 failed`. | Настроить `healthcheck` у брокера и `depends_on: condition: service_healthy` у UI. |

Детальные алгоритмы локализации инцидентов: [Troubleshooting Playbook для Apache Kafka](./kafka_troubleshooting_playbook.md).

---

## Рекомендации и Best Practices

### Чек-лист DevOps & SRE для Docker-окружения

1. **Ресурсное профилирование памяти:**
   - Для стенда разработки: `-Xms1g -Xmx1g` при лимите контейнера `2048M`–`2560M`.
   - Не забирайте всю память хоста под контейнер: оставляйте не менее 30–50% системной RAM под PageCache ядра ОС для обеспечения высокой скорости чтения/записи.
   - Подробнее: [Тюнинг JVM и сборщика мусора для Kafka](./kafka_jvm_gc_tuning.md).
2. **Гарантии корректного завершения:**
   - Всегда объявляйте `stop_grace_period: 60s` в Compose или `--stop-timeout 60` в Docker CLI. Это исключает повреждение индексов и ускоряет последующий перезапуск.
3. **Безопасность и запуск от non-root:**
   - Не запускайте брокер под пользователем `root`. Официальный образ `apache/kafka` работает под пользователем `appuser` (UID 1000).
   - Никогда не передавайте пароли и ключи через открытые переменные `environment`. Используйте монтирование конфигурационных файлов (JAAS) в режиме `ro` или Docker Secrets.
4. **Конфигурация хранилища и хоста:**
   - Используйте именованные тома (`named volumes`) для изоляции прав доступа.
   - На хостовой системе примените настройки виртуальной памяти Linux: `vm.swappiness=1` (защита от вытеснения PageCache в swap) и `vm.max_map_count=1048576` (для поддержки большого количества открытых сегментов mmap).
   - Подробнее: [Оптимизация ОС Linux для Kafka](./kafka_os_tuning.md).
5. **Ротация логов Docker daemon:**
   - Брокер Kafka генерирует интенсивный поток stdout/stderr логов. Без настройки ротации драйвер `json-file` быстро переполнит дисковое пространство хоста. Всегда задавайте `max-size: "10m"` и `max-file: "3"`.
   - Детали: [Docker Logging](../Docker/Docker_logs/docker_logging_drivers_overview.md).
6. **Фиксация тегов образов:**
   - Фиксируйте точную минорную версию образа (например, `apache/kafka:4.0.0`), избегая плавающего тега `latest`, чтобы исключить непреднамеренное обновление формата метаданных кластера при очередном pull.

---

## Дополнительная информация

### См. также

- **[Обзор Apache Kafka](./kafka_overview.md)** — архитектура журналов, протокол KRaft и жизненный цикл сообщений.
- **[CLI-инструменты Kafka](./kafka_cli_tools.md)** — полный справочник командных утилит управления кластером.
- **[Troubleshooting Playbook для Apache Kafka](./kafka_troubleshooting_playbook.md)** — алгоритмы диагностики инцидентов и метрики здоровья брокеров.
- **[Тюнинг JVM и сборщика мусора для Kafka](./kafka_jvm_gc_tuning.md)** — оптимизация сборщиков мусора G1GC и ZGC для низких задержек.
- **[Оптимизация ОС Linux для Kafka](./kafka_os_tuning.md)** — системные параметры ядра, pagecache, sysctl и ulimits.
- **[Strimzi Operator для Kubernetes](./strimzi_kafka_operator.md)** — масштабирование и управление Kafka в Kubernetes после этапа Docker-стендов.
- **[Docker Volumes](../Docker/Docker_fs/docker_volumes.md)** — персистентность данных и механика работы томов.
- **[Docker Network](../Docker/Docker_network/docker_network.md)** — сетевые драйверы, мосты и маршрутизация трафика.
- **[Docker Compose — обзор](../Docker/Docker_compose/docker_compose_overview.md)** — синтаксис манифестов Compose, anchors и зависимости сервисов.
- **[HEALTHCHECK и health signals](../Docker/Dockerfile/Instructions/health_signals.md)** — проверка готовности контейнеров и сигналы жизненного цикла.
- **[Docker Logging](../Docker/Docker_logs/docker_logging_drivers_overview.md)** — настройка драйверов логирования и защита диска от переполнения.
- **[Управление секретами в Docker](../Docker/Docker_security/secrets_management.md)** — безопасная доставка конфиденциальных данных в контейнеры.
