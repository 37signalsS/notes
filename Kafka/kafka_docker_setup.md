# Развертывание Apache Kafka в Docker (KRaft)

Использование Docker является стандартом для локальной разработки и тестирования Apache Kafka. Это позволяет развернуть полноценный кластер с инструментами визуализации за несколько минут, обеспечивая изоляцию зависимостей и повторяемость окружения.

---

## Определения

- **Kafka Broker (KRaft mode):** Современный режим работы Kafka, исключающий зависимость от ZooKeeper. Роли контроллера и брокера совмещены в одном контейнере (**combined mode**) либо разнесены по отдельным контейнерам (**isolated mode**).
- **Официальный образ `apache/kafka`:** JVM-образ от Apache Software Foundation, публикуется на Docker Hub начиная с Kafka 3.7.0.
- **`apache/kafka-native`:** Экспериментальный GraalVM-based нативный образ (с версии 3.8.0). Быстрый старт и низкое потребление RAM, но предназначен только для локальной разработки/тестов; SASL-аутентификация в нем не поддерживается (KAFKA-19584).
- **Kafka UI:** Веб-интерфейс для управления топиками, просмотра сообщений и мониторинга потребителей (consumers). Актуальные варианты: **Kafbat UI** (активный форк проекта Provectus, образ `ghcr.io/kafbat/kafka-ui`) и **AKHQ**. Исходный образ `provectuslabs/kafka-ui` более не обновляется (последние публикации — 2023 год), используйте форк Kafbat.
- **Persistence (Персистентность):** Использование Docker Volumes для сохранения данных и логов Kafka между перезапусками контейнеров. Детали механики томов: [Docker Volumes](../Docker/Docker_fs/docker_volumes.md).
- **Слушатели (Listeners):** Механизм разделения трафика. В Docker обычно настраиваются два слушателя: один для связи между контейнерами (внутренний), другой — для доступа с хост-машины (внешний).
- **Cluster ID:** Уникальный идентификатор кластера KRaft (base64-кодированный UUID). Генерируется командой `kafka-storage.sh random-uuid`; все узлы одного кластера должны иметь общий Cluster ID. В официальном образе есть встроенный default Cluster ID — если вы не переопределяете конфигурацию, указывать его не обязательно.

---

## Основные концепции

### Выбор образа

| Образ | Статус | Когда использовать |
| :--- | :--- | :--- |
| `apache/kafka` | Официальный, JVM | Дефолтный выбор для разработки и промышленно-подобных стендов |
| `apache/kafka-native` | Экспериментальный, GraalVM | Быстрые интеграционные тесты; без SASL, не для production |
| `confluentinc/cp-kafka` | Коммерческая экосистема | Нужны Schema Registry, Control Center и остальной стек Confluent Platform |
| `bitnami/kafka` | Недоступен бесплатно | С августа–сентября 2025 бесплатные образы Bitnami перенесены в `bitnamilegacy/*` (без обновлений) либо стали коммерческими (Bitnami Secure Images). Существующие compose-файлы мигрируйте на `apache/kafka` или `confluentinc/cp-kafka` |

### Ключевые переменные окружения (разбор)

> **Важная особенность официального образа:** если переопределить *хотя бы одну* переменную конфигурации, встроенные значения по умолчанию применяться перестают целиком — придется задать весь обязательный минимум (роли, кворум, слушатели). Либо не задавать ничего: тогда образ сам поднимает одноузловой combined-режим с готовыми настройками.

*   **`KAFKA_NODE_ID`**: В KRaft это основной идентификатор узла. В отличие от старого `broker.id`, он используется для формирования кворума.
*   **`KAFKA_PROCESS_ROLES`**: Управляет архитектурой. В малых средах (`broker,controller`) один процесс делает всё. В высоконагруженных Production-кластерах рекомендуется разделять: выделенные узлы-контроллеры (без данных) и узлы-брокеры.
*   **`KAFKA_CONTROLLER_QUORUM_VOTERS`**: Определяет "избирательную комиссию" кластера. Формат: `node_id@host:port`. Для отказоустойчивости обычно используется 3 или 5 контроллеров.
*   **`KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR`**: Критически важная настройка для DevOps. Если оставить значение `3` (по умолчанию) на кластере из 1-2 нод, создание групп потребителей завершится ошибкой, так как Kafka не сможет гарантировать сохранность офсетов.
*   **`KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR` / `KAFKA_TRANSACTION_STATE_LOG_MIN_ISR`**: Аналогичное требование для internal-топика транзакций; на одной ноде оба параметра = 1.
*   **`CLUSTER_ID`**: Общий идентификатор кластера для всех брокеров (см. Определения).
*   **Слушатели (Listeners)**:
    *   `KAFKA_LISTENERS`: На каком интерфейсе/порту сервер *слушает*. По умолчанию bind идет на `0.0.0.0`.
    *   `KAFKA_ADVERTISED_LISTENERS`: Какой адрес сервер *сообщает* клиенту. В Docker это часто `localhost:9092`, чтобы клиент снаружи контейнера знал, куда слать данные.
    *   В многоузловом кластере слушателей делают три: внутренний для межброкерного трафика (`KAFKA_INTER_BROKER_LISTENER_NAME`), внешний для хоста и CONTROLLER для кворума KRaft.
*   **`KAFKA_HEAP_OPTS`**: Прямое управление Heap JVM. В контейнерах всегда ограничивайте явно — иначе JVM возьмет четверть лимита контейнера или больше, а при отсутствии лимита может конфликтовать с OOM Killer.

### Механизм Listeners: почему клиенты «не видят» брокера

Клиент Kafka подключается сначала к bootstrap-адресу, а затем брокер отдает ему адрес из `advertised.listeners` для дальнейшей работы. Отсюда классические ошибки:

- Изнутри docker-сети работает `kafka-broker:9092`, но с хоста — connection refused: advertised-адрес не резолвится снаружи.
- С хоста работает `localhost:9092`, но другие контейнеры падают: им тоже достается `localhost`.

Решение — два именованных слушателя с разными advertised-адресами (см. Сценарий 3). Теория сетей Docker: [Docker Network](../Docker/Docker_network/docker_network.md).

---

## Практические сценарии

### Сценарий 1: Одноузловой стек через Docker Compose (Рекомендуется)

Использование `compose.yaml` позволяет декларативно описать весь стек: брокер + веб-интерфейс + постоянное хранилище.

**Файл `compose.yaml`:**
```yaml
services:
  kafka:
    image: apache/kafka:4.3.1 # фиксируйте версию; latest — только для экспериментов
    container_name: kafka-broker
    ports:
      - "9092:9092"
    environment:
      # --- Настройки режима KRaft (Kafka Raft) ---
      KAFKA_NODE_ID: 1 # Уникальный целочисленный ID брокера в кластере
      KAFKA_PROCESS_ROLES: broker,controller # Узлы могут быть брокерами, контроллерами или совмещать роли

      # Список контроллеров, участвующих в голосовании (кворуме)
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka-broker:9093

      # Идентификатор кластера. Все брокеры одного кластера должны иметь общий CLUSTER_ID
      CLUSTER_ID: 'Mk3OEYBSD34fcwNTJENDM2Qk'

      # --- Сетевые настройки ---
      # 9092 - для клиентов, 9093 - для внутренней связи контроллеров
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER

      # --- Оптимизация для одного узла ---
      # Критически важно для 1 брокера: Kafka по умолчанию ждет 3 копии метаданных офсетов.
      # Если не установить 1, консьюмеры не смогут работать в одноузловом кластере.
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1

      KAFKA_HEAP_OPTS: "-Xmx512M -Xms512M"
    volumes:
      - kafka_data:/var/lib/kafka/data
    healthcheck:
      test: ["CMD-SHELL", "kafka-topics.sh --bootstrap-server localhost:9092 --list"]
      interval: 10s
      timeout: 5s
      retries: 5

  kafka-ui:
    image: ghcr.io/kafbat/kafka-ui:latest # активный форк provectuslabs/kafka-ui
    container_name: kafka-ui
    ports:
      - "8080:8080"
    environment:
      KAFKA_CLUSTERS_0_NAME: local-cluster
      KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS: kafka-broker:9092 # имя сервиса = DNS внутри сети Compose
    depends_on:
      kafka:
        condition: service_healthy # UI стартует только после готовности брокера

volumes:
  kafka_data:
```

**Запуск стека:**
```bash
docker compose up -d
# → Проверка статуса: docker compose ps
```

Подробности синтаксиса Compose: [Docker Compose — обзор](../Docker/Docker_compose/docker_compose_overview.md).

### Сценарий 2: Быстрый запуск через Docker CLI

Если необходимо запустить только брокер без создания файлов конфигурации:

```bash
docker run -d \
  --name kafka-standalone \
  -p 9092:9092 \
  -e KAFKA_NODE_ID=1 \
  -e KAFKA_PROCESS_ROLES=broker,controller \
  -e KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093 \
  -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://localhost:9092 \
  -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@localhost:9093 \
  -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
  -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
  apache/kafka:latest
```

Альтернатива — вообще без переменных окружения: `docker run -d -p 9092:9092 apache/kafka:latest`. Образ использует встроенную дефолтную конфигурацию одноузлового combined-режима (включая replication factor внутренних топиков = 1). Минус: advertised-адрес по умолчанию рассчитан на подключение с той же машины; под свои задачи конфигурируйте явно.

### Сценарий 3: Мультиброкерный кластер (3 combined-узла)

Минимальный отказоустойчивый стенд: три брокера-контроллера с общим кворумом и двойными слушателями (внутренний + внешний для хоста). При трех брокерах переопределения replication factor не нужны — значение по умолчанию `3` становится корректным. YAML-якоря избавляют от дублирования общих настроек.

```yaml
x-kafka-common: &kafka-common
  image: apache/kafka:4.3.1
  environment: &kafka-env
    KAFKA_PROCESS_ROLES: broker,controller
    KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka-1:9093,2@kafka-2:9093,3@kafka-3:9093
    KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT,CONTROLLER:PLAINTEXT
    KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
    KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
    KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS: 0
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

  kafka-2:
    <<: *kafka-common
    container_name: kafka-2
    ports: ["39092:9092"]
    environment:
      <<: *kafka-env
      KAFKA_NODE_ID: 2
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:19092,PLAINTEXT_HOST://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka-2:19092,PLAINTEXT_HOST://localhost:39092

  kafka-3:
    <<: *kafka-common
    container_name: kafka-3
    ports: ["49092:9092"]
    environment:
      <<: *kafka-env
      KAFKA_NODE_ID: 3
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:19092,PLAINTEXT_HOST://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka-3:19092,PLAINTEXT_HOST://localhost:49092
```

```bash
docker compose up -d && docker compose ps
# → 3 контейнера Up; клиент с хоста: --bootstrap-server localhost:29092
# → клиент из docker-сети (например, kafka-ui): --bootstrap-server kafka-1:19092
```

Проверка распределения партиций после создания топика: [Партиционирование и балансировка](./partitioning_and_balancing.md).

### Сценарий 4: Защищенный стенд (SASL/SSL)

Для промышленно-подобного тестирования включайте безопасность до того, как стенд «переедет» в прод:

- **SASL_PLAINTEXT:** JAAS-файл монтируется томом, `KAFKA_OPTS` указывает на него; настраиваются отдельные пользователи для inter-broker связи и клиентов.
- **SSL:** keystore/truststore монтируются в `/etc/kafka/secrets`, параметры задаются через `KAFKA_SSL_*` переменные; в `KAFKA_ADVERTISED_LISTENERS` должен присутствовать listener с протоколом SSL.
- **Нативный образ не поддерживает SASL** (ограничение reflection-конфигурации GraalVM).
- **Не передавайте креденшелы через `environment`**: их видно любому через `docker inspect`. Безопасные способы доставки секретов в Compose: [Управление секретами](../Docker/Docker_security/secrets_management.md), [Vault + Docker](../Vault/guides/vault_docker_integration.md).

### Интеграционные тесты вместо постоянного стенда

Если Kafka нужна только тестам приложения, постоянный compose-стенд избыточен: Testcontainers поднимает одноразовый кластер программно, с динамическими портами. Детали: [Testcontainers](../Testing/testcontainers_overview.md).

---

## Проверка и первичная настройка

1.  **Доступ к Kafka UI:** Откройте `http://localhost:8080`. В статус-баре кластер должен иметь состояние `Online`.
2.  **Создание топика:**
    *   **Через UI:** `Topics` -> `Add a Topic`. Для локальной разработки установите `Partitions: 1` и `Replication Factor: 1`.
    *   **Через CLI (внутри контейнера):**
        ```bash
        docker exec -it kafka-broker kafka-topics.sh --create --topic test-data --bootstrap-server localhost:9092
        ```
        Полный справочник CLI: [CLI-инструменты Kafka](./kafka_cli_tools.md).
3.  **Smoke-тест продюсер/консьюмер:**
    ```bash
    docker exec -it kafka-broker kafka-console-producer.sh --topic test-data --bootstrap-server localhost:9092
    # → вводите сообщения строка за строкой, Ctrl+C для выхода
    docker exec -it kafka-broker kafka-console-consumer.sh --topic test-data --from-beginning --bootstrap-server localhost:9092
    # → получаете ранее отправленные сообщения
    ```
4.  **Проверка персистентности:** После `docker compose down` и повторного `up` созданные топики и данные должны сохраниться благодаря тому, что данные живут в именованном томе `kafka_data`. Учтите: `docker compose down -v` удаляет том вместе со всеми данными.

---

## Дополнительная информация

### Белые пятна и рекомендации
- **Управление памятью:** По умолчанию Kafka может потреблять много RAM. Всегда ограничивайте Heap через `KAFKA_HEAP_OPTS` в Docker; дополнительно задавайте лимит контейнера (`mem_limit` / `deploy.resources`) и мониторьте RSS вне heap.
- **Healthcheck:** Для сложных Compose-стеков добавьте проверку готовности (пример в Сценарии 1). Зависимые сервисы ждут её через `depends_on: condition: service_healthy` — подробнее в [HEALTHCHECK и health signals](../Docker/Dockerfile/Instructions/health_signals.md).
- **Версии образов:** Для промышленно-подобных тестов фиксируйте версию (например, `apache/kafka:4.3.1`), избегая `latest`. Актуальная минорная версия может отличаться — сверяйтесь с официальной страницей образа.
- **Права доступа к томам:** На Linux с SELinux/страными uid том может оказаться не записываемым; официальный образ требует Docker ≥ 20.10.4 для корректной работы non-root пользователя.
- **Логи контейнера:** stdout/stderr брокера смотрите через `docker logs kafka-broker`; настройка драйверов логирования — [Docker Logging](../Docker/Docker_logs/docker_logging_drivers_overview.md).

### Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Клиент с хоста висит или получает `Connection refused` после bootstrap | `advertised.listeners` отдает адрес, недоступный с хоста (например, `kafka-broker:9092`) | Разделяйте listeners: внутренний advertised на hostname контейнера, внешний — на `localhost:<порт>` |
| Контейнеры подключаются по `localhost:9092` и падают | Единый advertised-адрес рассчитан только на хост | См. Сценарий 3: два клиента-listener'а с разными advertised-адресами |
| `InconsistentClusterIdException` при старте | Том `kafka_data` содержит метаданные старого кластера, а `CLUSTER_ID` изменился | Одинаковый `CLUSTER_ID` во всех запусках; либо очистить том (`docker compose down -v`) осознанно |
| `TimeoutException` при создании consumer group / топика | Replication factor внутренних топиков (3) > числа брокеров (1–2) | `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1` (+ transaction state log параметры) на малых кластерах |
| UI показывает кластер, но топики пустые/ошибки метаданных | UI подключился раньше готовности брокера | `depends_on` c `condition: service_healthy` + healthcheck |
| Брокер убит OOM Killer / контейнер перезапускается | Heap не ограничен и конфликтует с лимитом контейнера | Явные `KAFKA_HEAP_OPTS` + `mem_limit`; следить за off-heap памятью |

### См. также
- **[Обзор Apache Kafka](./kafka_overview.md)** — архитектура журналов и режим KRaft.
- **[CLI-инструменты Kafka](./kafka_cli_tools.md)** — детальный справочник по командам внутри контейнера.
- **[Strimzi Operator](./strimzi_kafka_operator.md)** — следующий шаг после Docker: Kafka в Kubernetes.
