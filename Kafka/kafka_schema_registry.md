# Schema Registry в Apache Kafka

**Schema Registry** — это централизованное хранилище схем данных для Kafka-сообщений. Обеспечивает совместимость схем между producer'ами и consumer'ами, предотвращает отправку невалидных данных и упрощает эволюцию форматов.

---

## Определения

- **Schema:** Описание структуры данных (поля, типы, значения по умолчанию).
- **Schema Registry:** Сервис для хранения и управления схемами.
- **Compatibility:** Правила проверки совместимости новых схем с предыдущими.
- **Schema ID:** Уникальный идентификатор схемы в Registry (вместо полной схемы в сообщении).
- **Subject:** Логическое имя для группы схем (обычно `<topic-name>-key` или `<topic-name>-value`).
- **Avro:** Формат сериализации на основе JSON-схем. Самый популярный для Kafka.
- **Protobuf:** Protocol Buffers — бинарный формат от Google.
- **JSON Schema:** JSON-формат описания схем.
- **Schema Evolution:** Процесс изменения схемы без нарушения существующих потребителей.

---

## Основные концепции

### Зачем нужен Schema Registry

**Проблема без Registry:**
```
Producer (v1) ──▶ Kafka ──▶ Consumer (v1, v2, v3)
                    │
                    └── Нет проверки структуры!
                        Consumer v2 может сломаться на данных от Producer v1
```

**С Registry:**
```
Producer (v1) ──▶ Schema Registry ──┐
                                    ├──▶ Kafka ──▶ Consumer (v1, v2, v3)
Producer (v2) ──▶ Schema Registry ──┘
         │                                │
         └── Проверка совместимости ───────┘
              (compatibility check)
```

### Формат сообщения с Registry

```
┌─────────────────────────────────────────────────────────────┐
│  Message (с Schema Registry)                               │
├─────────────────────────────────────────────────────────────┤
│  Magic Byte (0x0) │ Schema ID (4 bytes) │ Payload (Avro/...)│
│       1 byte      │       4 bytes       │     variable      │
└─────────────────────────────────────────────────────────────┘
```

**Преимущества:**
- Экономия трафика (вместо полной схемы — только ID)
- Централизованное управление схемами
- Проверка совместимости при изменении схемы

### Уровни совместимости (Compatibility)

| Тип | Описание | Когда использовать |
|-----|----------|-------------------|
| **BACKWARD** (по умолчанию) | Новая схема может читать данные старых схем | Потребители обновляются первыми |
| **FORWARD** | Старые схемы могут читать данные новых схем | Продюсеры обновляются первыми |
| **FULL** | Двусторонняя совместимость | Самый строгий режим |
| **NONE** | Без проверки совместимости | Для миграции или экспериментов |
| **BACKWARD_TRANSITIVE** | BACKWARD для всех версий схемы | Для CI/CD |
| **FORWARD_TRANSITIVE** | FORWARD для всех версий схемы | Для CI/CD |
| **FULL_TRANSITIVE** | FULL для всех версий схемы | Для CI/CD |

### Эволюция схемы (Schema Evolution)

**Пример (Avro):**
```json
// Схема v1
{
  "type": "record",
  "name": "User",
  "fields": [
    {"name": "id", "type": "int"},
    {"name": "name", "type": "string"}
  ]
}

// Схема v2 (добавлено поле с default — совместимо с BACKWARD)
{
  "type": "record",
  "name": "User",
  "fields": [
    {"name": "id", "type": "int"},
    {"name": "name", "type": "string"},
    {"name": "email", "type": "string", "default": "unknown"}
  ]
}
```

**Правила совместимости:**
- **BACKWARD:** Можно добавить поле с `default`, удалить поле с `default`
- **FORWARD:** Можно добавить поле, удалить поле с `default`
- **FULL:** Можно добавить/удалить только поля с `default`

### Форматы схем

| Формат | Преимущества | Недостатки | Когда использовать |
|--------|-------------|-------------|-------------------|
| **Avro** | Человекочитаемая схема, хорошая эволюция, сжатие | Требует парсинга | Kafka-native, микросервисы |
| **Protobuf** | Бинарный компактный, кросс-языковый | Схема не в данных | gRPC-системы, высокая производительность |
| **JSON Schema** | JSON-формат, простота | Менее строгая типизация | Простые системы, REST API |

---

## Практические сценарии

### Сценарий 1: Настройка Schema Registry

`schema-registry.properties`:
```properties
# Слушание
listeners=http://0.0.0.0:8081

# Хранилище схем в Kafka
kafkastore.bootstrap.servers=PLAINTEXT://kafka:9092
kafkastore.topic=_schemas

# Совместимия по умолчанию
kafkastore.topic=_schemas
auto.register.schemas=false

# Лидерство
leader.eligibility=true
```

### Сценарий 2: Регистрация схемы и проверка совместимости

```bash
# Регистрация схемы
curl -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data '{"schema": "{\"type\": \"record\", \"name\": \"User\", \"fields\": [{\"name\": \"id\", \"type\": \"int\"}, {\"name\": \"name\", \"type\": \"string\"}]}"}' \
  http://schema-registry:8081/subjects/Users-value/versions

# Проверка совместимости
curl -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data '{"schema": "{\"type\": \"record\", \"name\": \"User\", \"fields\": [{\"name\": \"id\", \"type\": \"int\"}, {\"name\": \"name\", \"type\": \"string\"}, {\"name\": \"email\", \"type\": \"string\", \"default\": \"unknown\"}]}"}' \
  http://schema-registry:8081/compatibility/subjects/Users-value/versions/latest

# Получение всех версий схемы для топика
curl http://schema-registry:8081/subjects/Users-value/versions
```

### Сценарий 3: Настройка совместимости

```bash
# Установка глобальной совместимости
curl -X PUT -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data '{"compatibility": "BACKWARD"}' \
  http://schema-registry:8081/config

# Установка совместимости для конкретного топика
curl -X PUT -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data '{"compatibility": "FORWARD"}' \
  http://schema-registry:8081/config/Users-value
```

### Сценарий 4: Конфигурация Producer с Avro

```properties
# Producer с Avro и Schema Registry
key.converter=io.confluent.connect.avro.AvroConverter
value.converter=io.confluent.connect.avro.AvroConverter
key.converter.schema.registry.url=http://schema-registry:8081
value.converter.schema.registry.url=http://schema-registry:8081

# Автоматическая регистрация схем (не рекомендуется для production)
auto.register.schemas=false
```

**Java пример:**
```java
props.put("key.serializer", "io.confluent.kafka.serializers.KafkaAvroSerializer");
props.put("value.serializer", "io.confluent.kafka.serializers.KafkaAvroSerializer");
props.put("schema.registry.url", "http://schema-registry:8081");
```

### Сценарий 5: Обработка ошибок совместCompatibility

```bash
# Попытка зарегистрировать несовместимую схему
curl -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data '{"schema": "{\"type\": \"record\", \"name\": \"User\", \"fields\": [{\"name\": \"id\", \"type\": \"string\"}]}"}' \
  http://schema-registry:8081/subjects/Users-value/versions

# Ответ (409 Conflict)
# {"error_code":40901,"message":"Schema being registered is incompatible with an earlier schema"}
```

### Сценарий 6: Schema Evolution в CI/CD

```yaml
# Проверка совместимости в пайплайне
- name: Check schema compatibility
  run: |
    curl -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
      --data "{\"schema\": $(cat user.avsc | jq -Rs .)}" \
      http://schema-registry:8081/compatibility/subjects/Users-value/versions/latest
```

---

## Дополнительная информация

### Мониторинг Schema Registry

Ключевые метрики:
- `kafka.schema.registry:master_slave_role` — роль (leader/follower)
- `kafka.schema.registry:schema_count` — количество схем
- `kafka.schema.registry:register_schema_request_count` — количество регистраций
- `kafka.schema.registry:get_schema_request_count` — количество запросов схем

### Безопасность

```properties
# SSL для клиентов
client.security.protocol=SSL
client.ssl.keystore.location=/path/to/keystore
client.ssl.keystore.password=password

# SASL для Kafka
kafkastore.security.protocol=SASL_SSL
kafkastore.sasl.mechanism=PLAIN
```

### Бэкап Schema Registry

Схемы хранятся в Kafka-топике `_schemas`:
```bash
# Экспорт схем
kafka-console-consumer.sh --bootstrap-server kafka:9092 \
  --topic _schemas --from-beginning > schemas-backup.json
```

### Чек-лист для production

- [ ] `auto.register.schemas=false` (ручная регистрация схем)
- [ ] `compatibility=BACKWARD` или `FULL` для критичных топиков
- [ ] Мониторинг Schema Registry
- [ ] SSL/SASL для доступа к Registry
- [ ] Бэкап топика `_schemas`
- [ ] Проверка совместимости в CI/CD

### Связь с другими компонентами

- **[Kafka Connect](./kafka_connect_production.md)** — Connect использует Registry для конвертеров
- **[Avro/Protobuf](#форматы-схем)** — форматы сериализации
- **[Гарантии доставки](./delivery_guarantees.md)** — схемы влияют на десериализацию

### См. также
- **[Kafka Connect](./kafka_connect_production.md)** — использование Registry в коннекторах
- **[Гарантии доставки](./delivery_guarantees.md)** — совместимость схем
- **[Обзор Apache Kafka](./kafka_overview.md)** — экосистема Kafka
- **[Strimzi оператор](./strimzi_kafka_operator.md)** — Schema Registry в Kubernetes
