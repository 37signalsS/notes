# Развертывание Apache Kafka в Docker: современный стек (KRaft)

Использование Docker является стандартом для локальной разработки и тестирования Apache Kafka. Это позволяет развернуть полноценный кластер с инструментами визуализации за несколько минут, обеспечивая изоляцию зависимостей и повторяемость окружения.

---

## Основные концепции

### Компоненты окружения
1.  **Kafka Broker (KRaft mode):** Современный режим работы Kafka, исключающий зависимость от ZooKeeper. Роли контроллера и брокера совмещены в одном контейнере.
2.  **Kafka UI:** Веб-интерфейс (от Provectuslabs или AKHQ) для управления топиками, просмотра сообщений и мониторинга потребителей (consumers).
3.  **Persistence (Персистентность):** Использование Docker Volumes для сохранения данных и логов Kafka между перезапусками контейнеров.
4.  **Слушатели (Listeners):** Механизм разделения трафика. В Docker обычно настраиваются два слушателя: один для связи между контейнерами (внутренний), другой — для доступа с хост-машины (внешний).

---
## Практические сценарии

### Сценарий 1: Развертывание через Docker Compose (Рекомендуется)

Использование `compose.yaml` позволяет декларативно описать весь стек. Ниже приведен пример для Kafka 3.x/4.0+ в режиме KRaft.

**Файл `compose.yaml`:**
```yaml
services:
  kafka:
    image: apache/kafka:latest
    container_name: kafka-broker
    ports:
      - "9092:9092"
    environment:
      # --- Настройки режима KRaft (Kafka Raft) ---
      KAFKA_NODE_ID: 1 # Уникальный целочисленный ID брокера в кластере
      KAFKA_PROCESS_ROLES: broker,controller # Узлы могут быть брокерами, контроллерами или совмещать роли

      # Список контроллеров, участвующих в голосовании (кворуме)
      # Формат: node_id@host:port
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka-broker:9093

      # Идентификатор кластера (произвольная строка). Все брокеры одного кластера должны иметь общий CLUSTER_ID
      CLUSTER_ID: 'Mk3OEYBSD34fcwNTJENDM2Qk'

      # --- Сетевые настройки ---
      # Слушатели определяют "двери", через которые можно подключиться:
      # 9092 - для клиентов (продюсеры/консьюмеры), 9093 - для внутренней связи контроллеров
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
```

### Разбор ключевых параметров KRaft

*   **`KAFKA_NODE_ID`**: В KRaft это основной идентификатор узла. В отличие от старого `broker.id`, он используется для формирования кворума.
*   **`KAFKA_PROCESS_ROLES`**: Управляет архитектурой. В малых средах (`broker,controller`) один процесс делает всё. В высоконагруженных Production-кластерах рекомендуется разделять: выделенные узлы-контроллеры (без данных) и узлы-брокеры.
*   **`KAFKA_CONTROLLER_QUORUM_VOTERS`**: Определяет "избирательную комиссию" кластера. Для отказоустойчивости обычно используется 3 или 5 контроллеров.
*   **`KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR`**: Это SSoT-настройка для DevOps. Если оставить значение `3` (по умолчанию) на кластере из 1-2 нод, создание групп потребителей завершится ошибкой, так как Kafka не сможет гарантировать сохранность офсетов.
*   **Слушатели (Listeners)**: 
    *   `KAFKA_LISTENERS`: На каком интерфейсе/порту сервер *слушает*.
    *   `KAFKA_ADVERTISED_LISTENERS`: Какой адрес сервер *сообщает* клиенту. В Docker это часто `localhost:9092`, чтобы клиент снаружи контейнера знал, куда слать данные.

    image: provectuslabs/kafka-ui:latest
    container_name: kafka-ui
    ports:
      - "8080:8080"
    environment:
      KAFKA_CLUSTERS_0_NAME: local-cluster
      KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS: kafka-broker:9092
    depends_on:
      - kafka

volumes:
  kafka_data:
```

**Запуск стека:**
```bash
docker compose up -d
# → Проверка статуса: docker compose ps
```

### Сценарий 2: Быстрый запуск через Docker CLI

Если необходимо запустить только брокер без создания файлов конфигурации.

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
  -e CLUSTER_ID='Mk3OEYBSD34fcwNTJENDM2Qk' \
  apache/kafka:latest
```

---

## Проверка и первичная настройка

1.  **Доступ к Kafka UI:** Откройте `http://localhost:8080`. В статус-баре кластер должен иметь состояние `Online`.
2.  **Создание топика:**
    *   **Через UI:** `Topics` -> `Add a Topic`. Для локальной разработки установите `Partitions: 1` и `Replication Factor: 1`.
    *   **Через CLI (внутри контейнера):**
        ```bash
        docker exec -it kafka-broker kafka-topics.sh --create --topic test-data --bootstrap-server localhost:9092
        ```
3.  **Проверка персистентности:** После `docker compose down` и повторного `up` созданные топики и данные должны сохраниться благодаря тому `kafka_data`.

---

## Дополнительная информация

### Белые пятна и рекомендации
- **Управление памятью:** По умолчанию Kafka может потреблять много RAM. Всегда ограничивайте Heap через `KAFKA_HEAP_OPTS` в Docker.
- **Healthcheck:** Для сложных Compose-стеков добавьте проверку готовности:
  ```yaml
  healthcheck:
    test: ["CMD-SHELL", "kafka-topics.sh --bootstrap-server localhost:9092 --list"]
    interval: 10s
    timeout: 5s
    retries: 5
  ```
- **Версии образов:** Для промышленно-подобных тестов фиксируйте версию (например, `apache/kafka:3.8.0`), избегая `latest`.

### См. также
- **[Обзор Apache Kafka](./kafka_overview.md)** — архитектура журналов и режим KRaft.
- **[CLI-инструменты Kafka](./kafka_cli_tools.md)** — детальный справочник по командам внутри контейнера.
- **[Партиционирование и балансировка](./partitioning_and_balancing.md)** — как проектировать топики в Docker-среде.
