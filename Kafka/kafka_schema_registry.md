# Schema Registry в Apache Kafka

**Актуально для:** Confluent Schema Registry 7.7.x / 7.8.x, Apache Kafka 3.8.x / 3.9.x / 4.0.x (KRaft)

**Schema Registry** — это распределенный сервис и централизованное хранилище схем данных для сообщений Apache Kafka. Он обеспечивает контрактное взаимодействие между producer'ами и consumer'ами, валидирует совместимость форматов при эволюции структур данных и исключает необходимость передачи полного описания схемы внутри каждого отдельного сообщения.

---

## Определения

- **Schema:** Формальное описание структуры данных (поля, типы, правила обязательности и значения по умолчанию).
- **Schema Registry:** Выделенный веб-сервис с REST API для хранения, версионирования и валидации схем.
- **Subject:** Логическая область видимости (пространство имен) для версионирования схем в реестре. По умолчанию формируется как `<topic-name>-key` для ключа и `<topic-name>-value` для полезной нагрузки.
- **Schema ID:** Глобальный уникальный числовой идентификатор (4 байта), присваиваемый схеме при ее первой регистрации в кластере Schema Registry.
- **Magic Byte:** Служебный нулевой байт (`0x00`), помещаемый в начало бинарного полезного груза Kafka-сообщения для обозначения формата сжатия Confluent Wire Format.
- **Compatibility:** Политика сопоставления новой версии схемы с ранее зарегистрированными версиями в рамках одного Subject.
- **Schema Evolution:** Процесс изменения структуры данных во времени с сохранением работоспособности существующих потребителей и производителей.
- **Compacted Topic (`_schemas`):** Служебный внутренний топик Kafka с одной партицией и политикой `cleanup.policy=compact`, используемый Schema Registry в качестве единого персистентного журнала состояния (write-ahead log).
- **Leader (Master) Node:** Экземпляр Schema Registry, координирующий операцию записи схем в топик `_schemas` и выделяющий монотонно возрастающие Schema ID.
- **Follower Node:** Экземпляр Schema Registry, обслуживающий операции чтения из локального in-memory кэша и проксирующий запросы на запись к текущему лидеру.
- **Subject Name Strategy:** Алгоритм формирования имени Subject на основе имени топика или имени класса сериализуемого объекта.
- **Avro:** Бинарный формат сериализации данных на базе JSON-схем с развитой поддержкой эволюции и динамического разрешения типов.
- **Protobuf (Protocol Buffers):** Бинарный строго типизированный формат описания интерфейсов и сообщений от Google с индексацией по тегам полей.
- **JSON Schema:** Спецификация для описания структуры и валидации документов в формате JSON.

---

## Основные концепции и архитектура

### Зачем нужен Schema Registry

В стандартной модели Apache Kafka брокеры работают с сообщениями как с непрозрачными массивами байтов (`byte[]`) и не валидируют структуру передаваемых данных.

**Проблема без Registry:**
```
Producer (v1) ──▶ Kafka Broker ──▶ Consumer (v1, v2, v3)
                       │
                       └── Нет валидации контракта!
                           Producer может отправить поврежденные данные или
                           изменить структуру, сломав Consumer в production.
```

**С Schema Registry:**
```
Producer (v1/v2) ──(1. Проверка/Получение ID)──▶ Schema Registry
       │                                                │
       │ (2. Отправка данных + ID)             (Хранение в топике _schemas)
       ▼                                                │
  Kafka Broker ───────────────────────────────┐         ▼
       │                                      └── Schema Registry Cache
       ▼ (3. Чтение сообщения)                          ▲
 Consumer (v1/v2/v3) ──(4. Запрос схемы по ID)──────────┘
```

### Бинарный формат сообщения (Confluent Wire Format)

Для минимизации оверхеда полная схема не внедряется в каждое сообщение. Вместо этого клиентские сериализаторы (SerDe) используют заголовок из 5 байт:

```
┌─────────────────────────────────────────────────────────────┐
│ Confluent Wire Format (Kafka Payload)                       │
├────────────────────────┬──────────────────────┬─────────────┤
│ Magic Byte (0x00)      │ Schema ID            │ Payload     │
│ 1 байт                 │ 4 байта (Big-Endian) │ n байт      │
└────────────────────────┴──────────────────────┴─────────────┘
```

1. **Magic Byte (`0x00`):** 1 байт. Флаг протокола Confluent Schema Registry. Позволяет консьюмеру убедиться, что сообщение содержит Schema ID, а не произвольный бинарный поток.
2. **Schema ID:** 4 байта в сетевом порядке байтов (big-endian). Уникальный идентификатор зарегистрированной схемы.
3. **Payload:** Бинарные сериализованные данные (Avro binary, Protobuf wire format или сжатый JSON).

**Жизненный цикл обработки:**
1. **Producer:** Сериализатор рассчитывает хэш схемы. Если схема уже есть в локальном кэше — извлекает ее ID. Если нет — обращается в Schema Registry, регистрирует или проверяет совместимость, сохраняет ID в локальный кэш и прикрепляет 5-байтовый заголовок к телу сообщения.
2. **Consumer:** Десериализатор считывает Magic Byte (`0x00`). Извлекает следующие 4 байта (Schema ID). Проверяет локальный кэш консьюмера: если схема с таким ID уже загружена, выполняет десериализацию мгновенно. Если схема отсутствует в кэше — выполняет `GET /schemas/ids/{id}` к Schema Registry, сохраняет ее в кэш и десериализует полезную нагрузку.

### Архитектура кластера и High Availability (HA)

Кластер Schema Registry строится из нескольких stateless-нод, объединенных через общий кластер Kafka:

```
                        ┌───────────────────────────────┐
                        │        Load Balancer          │
                        │    (HAProxy / Nginx / K8s)    │
                        └──────────────┬────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
        ┌───────────────────────┐             ┌───────────────────────┐
        │ Schema Registry Node1 │             │ Schema Registry Node2 │
        │ (Role: LEADER)        │             │ (Role: FOLLOWER)      │
        │ In-Memory Cache       │             │ In-Memory Cache       │
        └───────────┬───────────┘             └───────────┬───────────┘
                    │                                     │
                    │      Produce (Writes) / Consume     │ Proxy Writes / Consume
                    ▼                                     ▼
        ┌─────────────────────────────────────────────────────────────┐
        │                 Apache Kafka Cluster                        │
        │  Topic: `_schemas` (Single Partition, Compacted, RF=3)       │
        └─────────────────────────────────────────────────────────────┘
```

1. **Координация и выбор лидера:**
   - Выбор лидера осуществляется через встроенный механизм координации Kafka (Consumer Group с `kafkastore.group.id=schema-registry`).
   - Нода, получившая лидерство (`master-slave-role=1`), обрабатывает все мутирующие запросы (`POST`, `PUT`, `DELETE`).
   - Ноды-последователи (Followers) принимают запросы на чтение (`GET`) локально из оперативной памяти без задержек. Мутирующие запросы они прозрачно проксируют лидеру по HTTP/HTTPS либо возвращают HTTP-редирект (`307 Temporary Redirect`) согласно параметру `schema.registry.inter.instance.protocol`.
2. **Хранилище `_schemas`:**
   - Представляет собой топик Kafka с ровно **одной партицией** (`partitions=1`).
   - Использование одной партиции гарантирует строгий порядок поступления событий и атомарное монотонное увеличение счетчика Schema ID без распределенных блокировок.
   - Политика очистки — компакция (`cleanup.policy=compact`), что обеспечивает компактность хранилища при сохранении всех версий для каждого Subject.

### Стратегии именования Subject (Subject Name Strategies)

Стратегия определяет, под каким именем схема регистрируется в реестре и как она ассоциируется с топиком:

| Стратегия | Формат Subject | Назначение и контекст применения |
|---|---|---|
| **TopicNameStrategy** (по умолчанию) | `<topic>-key`<br>`<topic>-value` | В топике передаются сообщения строго одной структуры. Стандарт для большинства потоковых пайплайнов. |
| **RecordNameStrategy** | `<namespace>.<record_name>` | Позволяет публиковать сообщения одной структуры в разные топики под единой схемой, либо логически разделять схемы по классам моделей. |
| **TopicRecordNameStrategy** | `<topic>-<namespace>.<record_name>` | Позволяет безопасно передавать несколько различных типов событий в рамках одного топика с индивидуальным версионированием каждой структуры. |

### Режимы совместимости (Compatibility Modes)

Schema Registry гарантирует управляемую эволюцию контрактов данных через набор правил совместимости:

| Режим | Описание | Порядок обновления компонентов |
|---|---|---|
| **BACKWARD** (по умолчанию) | Новая схема может читать данные, записанные старыми схемами. | Consumers обновляются первыми. |
| **BACKWARD_TRANSITIVE** | Новая схема может читать данные, записанные ВСЕМИ предыдущими схемами. | Consumers обновляются первыми (рекомендуется для production). |
| **FORWARD** | Старые схемы могут читать данные, записанные новыми схемами. | Producers обновляются первыми. |
| **FORWARD_TRANSITIVE** | ВСЕ старые схемы могут читать данные, записанные новой схемой. | Producers обновляются первыми. |
| **FULL** | Двусторонняя совместимость (одновременно BACKWARD и FORWARD). | Любой порядок обновления (Producers или Consumers). |
| **FULL_TRANSITIVE** | Двусторонняя совместимость со всеми историческими версиями схемы. | Самый надежный режим для распределенных микросервисных архитектур. |
| **NONE** | Проверка совместимости отключена. | Применяется только при начальной миграции или масштабном рефакторинге. |

### Эволюция схемы (Schema Evolution)

#### Пример эволюции Avro

```json
// Схема v1 (первоначальная версия)
{
  "type": "record",
  "name": "User",
  "namespace": "com.example.events",
  "fields": [
    {"name": "id", "type": "int"},
    {"name": "name", "type": "string"}
  ]
}

// Схема v2 (добавлено поле со значением по умолчанию — совместимо с BACKWARD)
{
  "type": "record",
  "name": "User",
  "namespace": "com.example.events",
  "fields": [
    {"name": "id", "type": "int"},
    {"name": "name", "type": "string"},
    {"name": "email", "type": "string", "default": "unknown"}
  ]
}
```

**Правила изменений по режимам:**
- **BACKWARD:** Разрешено добавление полей со значением `default`; удаление полей (если у них не было `default`, consumer подставит дефолт старой схемы).
- **FORWARD:** Разрешено добавление любых полей; удаление полей, только если они имели `default`.
- **FULL:** Добавление и удаление разрешено исключительно для полей со значением `default`.

#### Синтаксис схем: Protobuf

Protocol Buffers (protobuf) опирается на номера тегов полей (field tags) для бинарной упаковки. В отличие от Avro, схема не встраивается в сообщение:

```protobuf
syntax = "proto3";
package com.example.events;

message User {
  int32 id = 1;                // Поле 1: уникальный тег 1
  string name = 2;             // Поле 2: уникальный тег 2
  string email = 3;            // Новое поле: добавление безопасно
  repeated string roles = 4;   // Массив строк
}
```

**Правила совместимости Protobuf:**
- Запрещено изменять номера тегов полей (`= 1`, `= 2`).
- При удалении поля его тег и имя должны быть объявлены в секции `reserved`, чтобы предотвратить их случайное повторное использование в будущих версиях:
  ```protobuf
  reserved 3;
  reserved "email";
  ```
- В `proto3` все поля по умолчанию являются опциональными (`optional`), что упрощает прямую и обратную совместимость.

#### Синтаксис схем: Thrift (сравнительный контекст)

Apache Thrift — бинарный RPC-формат, разработанный Facebook. В отличие от Avro и Protobuf, Confluent Schema Registry не предоставляет нативной поддержки Thrift из коробки (хранение возможно только в виде generic текстовых описаний или в специализированных RPC-реестрах). Синтаксис приводится для сравнения архитектурных подходов к IDL:

```thrift
namespace java com.example.events

struct User {
  1: required i32 id,
  2: required string name,
  3: optional string email,
  4: optional list<string> roles
}
```

**Ключевые отличия от Protobuf:**
- Номер поля указывается перед модификатором (`1: required string name`), в то время как в Protobuf он стоит в конце (`string name = 1;`).
- Явное разделение на `required` и `optional`. Изменение поля с `required` на `optional` требует строгой синхронизации потребителей.

### Сравнение форматов схем

| Формат | Преимущества | Ограничения | Основная сфера применения |
|---|---|---|---|
| **Avro** | Нативная поддержка Kafka/Connect, высокая компактность, мощная динамическая эволюция | Требует отдельного парсера схем, сложнее отладка сырых байтов | Корпоративные шины данных, ETL/ELT пайплайны, Kafka Connect |
| **Protobuf** | Высокая скорость сериализации, строгая типизация, отличная кросс-языковая кодогенерация | Семантика `reserved` тегов требует дисциплины разработки | gRPC микросервисы, высоконагруженные межсервисные шины |
| **JSON Schema** | Человекочитаемый текстовый формат, развитая экосистема валидации веб-стандартов | Избыточный размер бинарного представления, медленнее бинарных форматов | Интеграция с внешними публичными API, REST-шлюзы |

---

## Практические сценарии и конфигурация

### Сценарий 1: Production конфигурация на Linux (Systemd)

Файл `/etc/schema-registry/schema-registry.properties`:

```properties
# Сетевые слушатели (HTTP/HTTPS)
listeners=http://0.0.0.0:8081
host.name=sr-node01.infra.internal

# Подключение к кластеру Kafka (KRaft / ZooKeeper)
kafkastore.bootstrap.servers=PLAINTEXT://kafka01.infra.internal:9092,PLAINTEXT://kafka02.infra.internal:9092,PLAINTEXT://kafka03.infra.internal:9092

# Параметры системного топика _schemas
kafkastore.topic=_schemas
kafkastore.topic.replication.factor=3
kafkastore.topic.min.insync.replicas=2
kafkastore.group.id=schema-registry-cluster

# Политика совместимости по умолчанию для новых Subject
compatibility.level=BACKWARD_TRANSITIVE

# Управление регистрацией схем (запрет авторегистрации продюсерами в production)
auto.register.schemas=false

# Настройки кворума и лидерства
leader.eligibility=true
schema.registry.inter.instance.protocol=http

# Таймауты и ограничения запросов
kafkastore.timeout.ms=10000
kafkastore.init.timeout.ms=60000
```

Systemd unit-файл `/etc/systemd/system/schema-registry.service`:

```ini
[Unit]
Description=Confluent Schema Registry
Documentation=https://docs.confluent.io/
After=network.target network-online.target

[Service]
Type=simple
User=kafka
Group=kafka
Environment="SCHEMA_REGISTRY_HEAP_OPTS=-Xms2G -Xmx2G -XX:+UseG1GC -XX:MaxGCPauseMillis=20"
Environment="SCHEMA_REGISTRY_LOG4J_OPTS=-Dlog4j.configuration=file:/etc/schema-registry/log4j.properties"
ExecStart=/usr/bin/schema-registry-start /etc/schema-registry/schema-registry.properties
ExecStop=/usr/bin/schema-registry-stop
Restart=on-failure
RestartSec=10s
LimitNOFILE=65536
LimitNPROC=32768

[Install]
WantedBy=multi-user.target
```

Команды управления службой:
```bash
# Перезагрузка конфигурации systemd и запуск службы
sudo systemctl daemon-reload
sudo systemctl enable --now schema-registry
# → Created symlink /etc/systemd/system/multi-user.target.wants/schema-registry.service.

# Проверка статуса службы
sudo systemctl status schema-registry --no-pager
# → Active: active (running) since Mon 2026-10-12 14:00:00 MSK; 10min ago
```

### Сценарий 2: Развертывание в Docker Compose (On-Premise)

Файл `docker-compose.yml` для локального контура или изолированного стенда:

```yaml
version: '3.8'

services:
  schema-registry:
    image: confluentinc/cp-schema-registry:7.8.0
    hostname: schema-registry
    container_name: schema-registry
    restart: unless-stopped
    ports:
      - "8081:8081"
    environment:
      SCHEMA_REGISTRY_HOST_NAME: schema-registry
      SCHEMA_REGISTRY_LISTENERS: http://0.0.0.0:8081
      SCHEMA_REGISTRY_KAFKASTORE_BOOTSTRAP_SERVERS: PLAINTEXT://kafka01:9092,PLAINTEXT://kafka02:9092
      SCHEMA_REGISTRY_KAFKASTORE_TOPIC: _schemas
      SCHEMA_REGISTRY_KAFKASTORE_TOPIC_REPLICATION_FACTOR: 3
      SCHEMA_REGISTRY_KAFKASTORE_TOPIC_MIN_INSYNC_REPLICAS: 2
      SCHEMA_REGISTRY_KAFKASTORE_GROUP_ID: schema-registry-cluster
      SCHEMA_REGISTRY_COMPATIBILITY_LEVEL: BACKWARD_TRANSITIVE
      SCHEMA_REGISTRY_AUTO_REGISTER_SCHEMAS: "false"
      SCHEMA_REGISTRY_LEADER_ELIGIBILITY: "true"
      SCHEMA_REGISTRY_HEAP_OPTS: "-Xms1G -Xmx1G"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8081/subjects"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 30s
```

Запуск и проверка состояния контейнера:
```bash
docker compose up -d
# → [+] Running 1/1
# →  ✔ Container schema-registry  Started

docker compose ps
# → NAME              IMAGE                               COMMAND                  SERVICE             STATUS                    PORTS
# → schema-registry   confluentinc/cp-schema-registry:... "/etc/confluent/dock…"   schema-registry     Up 45 seconds (healthy)   0.0.0.0:8081->8081/tcp
```

### Сценарий 3: Развертывание в Kubernetes (On-Premise / Bare-Metal)

Манифест `schema-registry-k8s.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: schema-registry
  namespace: kafka
  labels:
    app.kubernetes.io/name: schema-registry
spec:
  type: ClusterIP
  ports:
    - name: http
      port: 8081
      targetPort: 8081
  selector:
    app.kubernetes.io/name: schema-registry
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: schema-registry
  namespace: kafka
  labels:
    app.kubernetes.io/name: schema-registry
spec:
  replicas: 2
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app.kubernetes.io/name: schema-registry
  template:
    metadata:
      labels:
        app.kubernetes.io/name: schema-registry
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchExpressions:
                    - key: app.kubernetes.io/name
                      operator: In
                      values: ["schema-registry"]
                topologyKey: kubernetes.io/hostname
      containers:
        - name: schema-registry
          image: confluentinc/cp-schema-registry:7.8.0
          ports:
            - containerPort: 8081
              name: http
          env:
            - name: SCHEMA_REGISTRY_LISTENERS
              value: "http://0.0.0.0:8081"
            - name: SCHEMA_REGISTRY_KAFKASTORE_BOOTSTRAP_SERVERS
              value: "kafka-cluster-kafka-bootstrap.kafka.svc.cluster.local:9092"
            - name: SCHEMA_REGISTRY_KAFKASTORE_TOPIC
              value: "_schemas"
            - name: SCHEMA_REGISTRY_KAFKASTORE_TOPIC_REPLICATION_FACTOR
              value: "3"
            - name: SCHEMA_REGISTRY_KAFKASTORE_TOPIC_MIN_INSYNC_REPLICAS
              value: "2"
            - name: SCHEMA_REGISTRY_AUTO_REGISTER_SCHEMAS
              value: "false"
            - name: SCHEMA_REGISTRY_COMPATIBILITY_LEVEL
              value: "BACKWARD_TRANSITIVE"
            - name: SCHEMA_REGISTRY_HEAP_OPTS
              value: "-Xms2G -Xmx2G -XX:+UseG1GC"
          resources:
            requests:
              cpu: 500m
              memory: 2Gi
            limits:
              cpu: 2000m
              memory: 4Gi
          livenessProbe:
            httpGet:
              path: /subjects
              port: 8081
            initialDelaySeconds: 30
            periodSeconds: 15
            timeoutSeconds: 5
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /subjects
              port: 8081
            initialDelaySeconds: 15
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 2
```

Применение манифеста:
```bash
kubectl apply -f schema-registry-k8s.yaml
# → service/schema-registry created
# → deployment.apps/schema-registry created

kubectl -n kafka get pods -l app.kubernetes.io/name=schema-registry
# → NAME                               READY   STATUS    RESTARTS   AGE
# → schema-registry-78d49dfd4b-g9k7z   1/1     Running   0          45s
# → schema-registry-78d49dfd4b-m4w2p   1/1     Running   0          45s
```

### Сценарий 4: Настройка безопасности (TLS и SASL к Kafka)

При работе в защищенном контуре Schema Registry взаимодействует с брокерами Kafka через SASL/TLS, а клиенты подключаются к Schema Registry через HTTPS.

Дополнения к `schema-registry.properties`:

```properties
# 1. Защита клиентского HTTPS-интерфейса Schema Registry
listeners=https://0.0.0.0:8081
ssl.keystore.location=/etc/schema-registry/security/schema-registry.keystore.jks
ssl.keystore.password=KeystoreSecretPass123
ssl.key.password=KeySecretPass123
ssl.truststore.location=/etc/schema-registry/security/schema-registry.truststore.jks
ssl.truststore.password=TruststoreSecretPass123
ssl.client.auth=false

# 2. Подключение к брокерам Kafka по защищенному протоколу SASL_SSL
kafkastore.bootstrap.servers=SASL_SSL://kafka01.infra.internal:9093,SASL_SSL://kafka02.infra.internal:9093
kafkastore.security.protocol=SASL_SSL
kafkastore.sasl.mechanism=SCRAM-SHA-512
kafkastore.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required \
    username="schema_registry_user" \
    password="StrongClusterPassword456";

# 3. Доверенные корневые сертификаты для взаимодействия с Kafka
kafkastore.ssl.truststore.location=/etc/schema-registry/security/kafka.truststore.jks
kafkastore.ssl.truststore.password=TruststoreSecretPass123
```

Необходимые ACL в Kafka для сервисного аккаунта `schema_registry_user`:
```bash
# Разрешение прав на системный топик _schemas
kafka-acls.sh --bootstrap-server kafka01.infra.internal:9093 \
  --command-config /etc/kafka/adminclient.properties \
  --add --allow-principal User:schema_registry_user \
  --operation All --topic _schemas
# → Adding ACLs for resource `ResourcePattern(resourceType=TOPIC, name=_schemas, patternType=LITERAL)`:
# → 	(principal=User:schema_registry_user, host=*, operation=ALL, permissionType=ALLOW)

# Разрешение прав на Consumer Group
kafka-acls.sh --bootstrap-server kafka01.infra.internal:9093 \
  --command-config /etc/kafka/adminclient.properties \
  --add --allow-principal User:schema_registry_user \
  --operation All --group schema-registry-cluster
# → Adding ACLs for resource `ResourcePattern(resourceType=GROUP, name=schema-registry-cluster, patternType=LITERAL)`:
# → 	(principal=User:schema_registry_user, host=*, operation=ALL, permissionType=ALLOW)
```

### Сценарий 5: Администрирование схем через REST API

#### 1. Регистрация новой схемы
```bash
curl -s -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data '{"schema": "{\"type\": \"record\", \"name\": \"UserEvent\", \"namespace\": \"com.infra\", \"fields\": [{\"name\": \"user_id\", \"type\": \"long\"}, {\"name\": \"action\", \"type\": \"string\"}]}"}' \
  http://schema-registry:8081/subjects/user-events-value/versions
# → {"id":1}
```

#### 2. Проверка совместимости схемы перед регистрацией
```bash
curl -s -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data '{"schema": "{\"type\": \"record\", \"name\": \"UserEvent\", \"namespace\": \"com.infra\", \"fields\": [{\"name\": \"user_id\", \"type\": \"long\"}, {\"name\": \"action\", \"type\": \"string\"}, {\"name\": \"ip\", \"type\": \"string\", \"default\": \"0.0.0.0\"}]}"}' \
  http://schema-registry:8081/compatibility/subjects/user-events-value/versions/latest
# → {"is_compatible":true}
```

#### 3. Получение схемы по ID (используется консьюмерами)
```bash
curl -s http://schema-registry:8081/schemas/ids/1
# → {"schema":"{\"type\":\"record\",\"name\":\"UserEvent\",\"namespace\":\"com.infra\",\"fields\":[{\"name\":\"user_id\",\"type\":\"long\"},{\"name\":\"action\",\"type\":\"string\"}]}"}
```

#### 4. Получение списка Subject и версий
```bash
# Список всех зарегистрированных Subject
curl -s http://schema-registry:8081/subjects
# → ["user-events-value"]

# Список версий для Subject
curl -s http://schema-registry:8081/subjects/user-events-value/versions
# → [1,2]

# Получение конкретной версии схемы с метаданными
curl -s http://schema-registry:8081/subjects/user-events-value/versions/latest
# → {"subject":"user-events-value","id":2,"version":2,"schema":"{\"type\":\"record\",\"name\":\"UserEvent\"...}"}
```

#### 5. Управление уровнем совместимости (Global и Per-Subject)
```bash
# Получение глобальной политики совместимости
curl -s http://schema-registry:8081/config
# → {"compatibilityLevel":"BACKWARD_TRANSITIVE"}

# Установка политики для конкретного Subject
curl -s -X PUT -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data '{"compatibility": "FULL_TRANSITIVE"}' \
  http://schema-registry:8081/config/user-events-value
# → {"compatibility":"FULL_TRANSITIVE"}
```

#### 6. Удаление схем (Soft Delete и Hard Delete)
```bash
# Soft delete конкретной версии (помечается удаленной, ID сохраняется)
curl -s -X DELETE http://schema-registry:8081/subjects/user-events-value/versions/1
# → 1

# Hard delete (полное необратимое удаление, требуется предварительный soft delete)
curl -s -X DELETE "http://schema-registry:8081/subjects/user-events-value/versions/1?permanent=true"
# → 1

# Полное удаление всего Subject со всеми версиями
curl -s -X DELETE "http://schema-registry:8081/subjects/user-events-value?permanent=true"
# → [2]
```

### Сценарий 6: Schema Evolution в CI/CD (GitOps валидация)

В production-средах авторегистрация (`auto.register.schemas`) выключается. Все изменения схем проверяются в репозитории на этапе Merge Request перед деплоем:

```yaml
# Пример задачи в GitLab CI (.gitlab-ci.yml)
stages:
  - schema-validation
  - schema-deploy

validate-schema-compatibility:
  stage: schema-validation
  image: badouralix/curl-jq:latest
  script:
    - |
      echo "Проверка совместимости схемы с production Schema Registry..."
      ESCAPED_SCHEMA=$(jq -Rs . schemas/user_event.avsc)
      RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
        -H "Content-Type: application/vnd.schemaregistry.v1+json" \
        --data "{\"schema\": $ESCAPED_SCHEMA}" \
        http://schema-registry.infra.internal:8081/compatibility/subjects/user-events-value/versions/latest)
      
      HTTP_STATUS=$(echo "$RESPONSE" | tail -n1)
      BODY=$(echo "$RESPONSE" | sed '$d')
      
      if [ "$HTTP_STATUS" -ne 200 ]; then
        echo "Ошибка обращения к Schema Registry! HTTP Status: $HTTP_STATUS"
        echo "$BODY"
        exit 1
      fi
      
      IS_COMPATIBLE=$(echo "$BODY" | jq -r .is_compatible)
      if [ "$IS_COMPATIBLE" != "true" ]; then
        echo "КРИТИЧЕСКАЯ ОШИБКА: Схема несовместима с текущей версией в продакшене!"
        echo "$BODY"
        exit 1
      fi
      echo "Схема успешно прошла валидацию совместимости."
  only:
    - merge_requests

register-schema-production:
  stage: schema-deploy
  image: badouralix/curl-jq:latest
  script:
    - |
      echo "Регистрация подтвержденной схемы в Schema Registry..."
      ESCAPED_SCHEMA=$(jq -Rs . schemas/user_event.avsc)
      curl -s -f -X POST \
        -H "Content-Type: application/vnd.schemaregistry.v1+json" \
        --data "{\"schema\": $ESCAPED_SCHEMA}" \
        http://schema-registry.infra.internal:8081/subjects/user-events-value/versions
  only:
    - main
```

### Сценарий 7: Конфигурация клиентов и Kafka Connect

#### Producer конфигурация (`producer.properties`):
```properties
bootstrap.servers=kafka01.infra.internal:9092,kafka02.infra.internal:9092
key.serializer=org.apache.kafka.common.serialization.StringSerializer
value.serializer=io.confluent.kafka.serializers.KafkaAvroSerializer
schema.registry.url=http://schema-registry:8081

# Запрет неконтролируемой регистрации схем продюсером
auto.register.schemas=false
use.latest.version=true
```

#### Consumer конфигурация (`consumer.properties`):
```properties
bootstrap.servers=kafka01.infra.internal:9092,kafka02.infra.internal:9092
group.id=billing-processor-group
key.deserializer=org.apache.kafka.common.serialization.StringDeserializer
value.deserializer=io.confluent.kafka.serializers.KafkaAvroDeserializer
schema.registry.url=http://schema-registry:8081

# Использование конкретных сгенерированных Java-классов вместо GenericRecord
specific.avro.reader=true
```

#### Конфигурация Kafka Connect:
В распределенном кластере Kafka Connect конвертеры настраиваются в `connect-distributed.properties`:
```properties
key.converter=org.apache.kafka.connect.storage.StringConverter
value.converter=io.confluent.connect.avro.AvroConverter
value.converter.schema.registry.url=http://schema-registry:8081
value.converter.auto.register.schemas=false
value.converter.use.latest.version=true
```

---

## Диагностика и устранение неполадок

### 1. Ошибка 409 Conflict при регистрации схемы

**Симптом:**
```bash
curl -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data '{"schema": "{\"type\": \"record\", \"name\": \"UserEvent\", \"fields\": [{\"name\": \"id\", \"type\": \"string\"}]}"}' \
  http://schema-registry:8081/subjects/user-events-value/versions
# → {"error_code":409,"message":"Schema being registered is incompatible with an earlier schema"}
```

**Причина:**
Новая версия схемы нарушает заданный уровень совместимости (например, в режиме `BACKWARD` удалено обязательное поле без значения по умолчанию, либо изменен фундаментальный тип существующего поля `int` → `string`).

**Решение:**
1. Выгрузить текущую версию схемы через `curl -s http://schema-registry:8081/subjects/user-events-value/versions/latest | jq .schema | jq fromjson`.
2. Найти различия (diff) в полях.
3. Добавить недостающим полям значения по умолчанию (`default`), либо вернуть исходные типы.
4. Если несовместимое изменение запланировано и архитектурно необходимо:
   - Временно ослабить уровень совместимости для Subject:
     ```bash
     curl -X PUT -H "Content-Type: application/vnd.schemaregistry.v1+json" \
       --data '{"compatibility": "NONE"}' \
       http://schema-registry:8081/config/user-events-value
     # → {"compatibility":"NONE"}
     ```
   - Зарегистрировать новую схему.
   - Вернуть режим совместимости `BACKWARD_TRANSITIVE`.
   - В качестве альтернативы (рекомендуется): создать новый топик `user-events-v2` и новый Subject.

### 2. Ошибка 422 Unprocessable Entity

**Симптом:**
```bash
# → {"error_code":422,"message":"Invalid schema: ..."}
```

**Причина:**
Синтаксически некорректный JSON/Avro документ (пропущена запятая, отсутствует обязательное поле `name` или `type`, дублирующиеся имена полей).

**Решение:**
Проверить валидность схемы утилитой `jq`:
```bash
cat schema.avsc | jq . > /dev/null
# → parse error: Expected separator between values at line 5, column 10
```

### 3. Ошибка SerializationException: Unknown magic byte!

**Симптом в логах Consumer:**
```
org.apache.kafka.common.errors.SerializationException: Error deserializing key/value for partition user-events-0 at offset 12345. If needed, please seek past the record to continue consumption.
Caused by: org.apache.kafka.common.errors.SerializationException: Unknown magic byte!
```

**Причина:**
Consumer настроен на использование `KafkaAvroDeserializer` и ожидает заголовок Confluent Wire Format (Magic Byte `0x00` в первых 5 байтах), но в топик было записано сообщение сырого формата (Plain JSON, чистая строка, gzip-архив) сторонним продюсером без SerDe.

**Диагностика и решение:**
1. Инспектировать сырые байты заголовка сообщения:
   ```bash
   kcat -b kafka01:9092 -t user-events -p 0 -o 12345 -c 1 -C -e | xxd -l 10
   # → 00000000: 7b22 7573 6572 5f69 6422 3a                {"user_id":
   ```
   В выводе видно `7b` (`{`), а не `00`. Сообщение является plain JSON.
2. Изолировать и исправить producer, записывающий невалидные сообщения.
3. Для продолжения работы консьюмера выполнить смещение оффсета (seek past the record) через `kafka-consumer-groups.sh --reset-offsets`.

### 4. SchemaRegistryInitializationException при запуске ноды

**Симптом в логах службы:**
```
io.confluent.kafka.schemaregistry.exceptions.SchemaRegistryInitializationException: Initialization failed
Caused by: org.apache.kafka.common.errors.TimeoutException: Failed to update metadata after 60000 ms.
```

**Причина:**
- Недоступны брокеры Kafka, указанные в `kafkastore.bootstrap.servers`.
- Топик `_schemas` не может быть создан из-за нехватки брокеров: например, `kafkastore.topic.replication.factor=3`, а в кластере доступно только 2 брокера.
- Отсутствуют права доступа (Kafka ACL) у сервисного пользователя Schema Registry.

**Диагностика:**
```bash
# Проверить сетевую доступность брокеров
nc -zv kafka01.infra.internal 9092
# → Connection to kafka01.infra.internal 9092 port [tcp/*] succeeded!

# Проверить состояние топика _schemas в Kafka
kafka-topics.sh --bootstrap-server kafka01:9092 --describe --topic _schemas
# → Topic: _schemas	TopicId: ...	PartitionCount: 1	ReplicationFactor: 3	Configs: cleanup.policy=compact,min.insync.replicas=2
```

### 5. Ошибка 40301: Subject is read-only

**Симптом:**
```bash
# → {"error_code":40301,"message":"Subject 'user-events-value' is in READONLY mode"}
```

**Причина:**
Subject или весь кластер Schema Registry переведен в режим `READONLY` (часто используется при Disaster Recovery или плановом обслуживании).

**Решение:**
Проверить и перевести режим в `READWRITE`:
```bash
# Проверить текущий режим
curl -s http://schema-registry:8081/mode
# → {"mode":"READONLY"}

# Переключить режим в READWRITE
curl -s -X PUT -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data '{"mode": "READWRITE"}' \
  http://schema-registry:8081/mode
# → {"mode":"READWRITE"}
```

---

## Рекомендации и Best Practices (SRE & DevOps)

### Production Чек-лист

- [ ] **Запрет авторегистрации:** `auto.register.schemas=false` на всех Schema Registry нодах и клиентских конфигурациях. Схемы регистрируются исключительно через CI/CD.
- [ ] **Режим совместимости:** Использование `BACKWARD_TRANSITIVE` или `FULL_TRANSITIVE` для критичных шин данных.
- [ ] **Высокая доступность:** Развертывание минимум 2 (оптимально 3) экземпляров Schema Registry за балансировщиком нагрузки.
- [ ] **Топик `_schemas`:** Ровно 1 партиция, `replication.factor=3`, `min.insync.replicas=2`, `cleanup.policy=compact`.
- [ ] **Кэширование:** Настройка размера in-memory кэша клиентов (`schema.registry.cache.capacity` по умолчанию 1000 схем).
- [ ] **Безопасность:** Доступ по HTTPS/TLS, шифрование трафика к брокерам (SASL_SSL) и строгие Kafka ACL.
- [ ] **Мониторинг:** Настроен сбор JMX метрик, алертинг на смену лидера и HTTP 5xx ошибки.

### Sizing и JVM тюнинг

Schema Registry является сравнительно легковесным приложением (I/O сосредоточено в кэшировании в JVM Heap и передаче метаданных):

- **CPU:** 1–2 vCPU на инстанс достаточно для обработки до 5000 rps запросов на чтение схем.
- **RAM / Heap:** 
  - Рекомендуемый объем JVM Heap: `2G` (`-Xms2G -Xmx2G`).
  - Для сред с числом схем более 50 000 — увеличить Heap до `4G`.
- **Garbage Collector:** Рекомендуется сборщик `G1GC` с низкими паузами:
  ```properties
  SCHEMA_REGISTRY_HEAP_OPTS="-Xms2G -Xmx2G -XX:+UseG1GC -XX:MaxGCPauseMillis=20 -XX:InitiatingHeapOccupancyPercent=45"
  ```

### Мониторинг и метрики (JMX Exporter)

Конфигурация Prometheus JMX Exporter (`schema_registry_jmx.yml`):

```yaml
lowercaseOutputName: true
lowercaseOutputLabelNames: true
rules:
  # Роль ноды: 1 = Лидер, 0 = Последователь
  - pattern: 'kafka.schema.registry<type=master-slave-role><>(master-slave-role): (\d+)'
    name: schema_registry_leader_role
    type: GAUGE
  # Общее количество схем
  - pattern: 'kafka.schema.registry<type=schema-registry-metrics><>(schema-count): (\d+)'
    name: schema_registry_schema_count
    type: GAUGE
  # Счетчик запросов
  - pattern: 'kafka.schema.registry<type=jetty-metrics><>([a-z-]+-requests): (\d+)'
    name: schema_registry_http_requests_total
    type: COUNTER
  # Задержки запросов
  - pattern: 'kafka.schema.registry<type=schema-registry-metrics><>([a-z-]+-latency-ms): (.+)'
    name: schema_registry_request_latency_ms
    type: GAUGE
```

**Ключевые Prometheus Alerting Rules:**
```yaml
groups:
  - name: schema-registry-alerts
    rules:
      - alert: SchemaRegistryNoLeader
        expr: sum(schema_registry_leader_role) != 1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "В кластере Schema Registry отсутствует либо дублируется лидер"
          description: "Сумма schema_registry_leader_role равна {{ $value }}. Ожидается ровно 1 лидер."

      - alert: SchemaRegistryHighErrorRate
        expr: rate(schema_registry_http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Повышенная частота HTTP 5xx ошибок в Schema Registry"
          description: "Доля 5xx ответов превышает 5% за последние 5 минут."
```

### Резервное копирование и Disaster Recovery топика `_schemas`

Поскольку все состояние хранится в топике `_schemas`, бэкап реестра эквивалентен бэкапу этого топика.

#### 1. Создание резервной копии через консольный консьюмер
```bash
# Дамп всех сообщений топика с ключами и оффсетами
kafka-console-consumer.sh --bootstrap-server kafka01.infra.internal:9092 \
  --topic _schemas \
  --from-beginning \
  --property print.key=true \
  --property key.separator="||" \
  --timeout-ms 10000 > /backup/schemas/schemas_backup_$(date +%Y%m%d_%H%M%S).dump
# → Завершено по таймауту после чтения всех записей
```

#### 2. Восстановление топика `_schemas`
```bash
# В случае повреждения топика: создание нового топика с корректными параметрами
kafka-topics.sh --bootstrap-server kafka01.infra.internal:9092 \
  --create --topic _schemas_restored \
  --partitions 1 \
  --replication-factor 3 \
  --config cleanup.policy=compact \
  --config min.insync.replicas=2
# → Created topic _schemas_restored.

# Заливка данных из дампа
kafka-console-producer.sh --bootstrap-server kafka01.infra.internal:9092 \
  --topic _schemas_restored \
  --property parse.key=true \
  --property key.separator="||" < /backup/schemas/schemas_backup_20261012_140000.dump
```

#### 3. Межкластерная репликация (Active-Passive DC)
Для репликации схем между дата-центрами используется Kafka MirrorMaker 2:
- Топик `_schemas` реплицируется в целевой дата-центр.
- Schema Registry в резервном DC запускается в режиме `READONLY` (`mode=READONLY`), чтобы исключить конфликты генерации Schema ID.
- При переключении трафика (Failover) резервный Schema Registry переводится в `READWRITE`.

---

## Дополнительная информация

### Взаимосвязь с компонентами экосистемы Kafka

- **[Обзор Apache Kafka](./kafka_overview.md)** — архитектура брокеров, логи и топики.
- **[Kafka Connect в Production](./kafka_connect_production.md)** — использование `AvroConverter` и `ProtobufConverter` в распределенных коннекторах.
- **[CLI-утилиты для Kafka](./kafka_cli_tools.md)** — декодирование бинарных сообщений Avro/Protobuf через `kafkactl` и `kcat`.
- **[Гарантии доставки сообщений](./delivery_guarantees.md)** — обеспечение семантики доставки и целостности данных.
- **[Мониторинг Apache Kafka](./kafka_for_monitoring.md)** — общие подходы к сбору метрик JMX и алертингу.
- **[JVM и GC тюнинг Kafka](./kafka_jvm_gc_tuning.md)** — настройка сборщика мусора G1GC.
- **[Strimzi Kafka Operator](./strimzi_kafka_operator.md)** — эксплуатация Kafka в Kubernetes.

### Внешние ресурсы

- [Официальная документация Confluent Schema Registry](https://docs.confluent.io/platform/current/schema-registry/index.html)
- [Confluent Wire Format Specification](https://docs.confluent.io/platform/current/schema-registry/fundamentals/serdes-develop/index.html#wire-format)
- [Apache Avro Documentation](https://avro.apache.org/docs/)
- [Protocol Buffers Language Guide](https://protobuf.dev/programming-guides/proto3/)
