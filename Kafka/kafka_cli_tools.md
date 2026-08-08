# CLI-инструменты для работы с Apache Kafka

Для взаимодействия с Apache Kafka из командной строки используются стандартные утилиты, входящие в дистрибутив, а также сторонние решения, такие как `kcat` и `kafkactl`. Они позволяют управлять топиками, читать и отправлять сообщения, а также диагностировать состояние кластера.

## Определения

- **Kafka CLI (Standard)**: Набор shell-скриптов (оберток над Java-приложениями), поставляемых в составе дистрибутива Apache Kafka. Требуют наличия JRE/JVM. Основные утилиты: `kafka-topics.sh`, `kafka-console-consumer.sh`, `kafka-configs.sh`.
- **kcat (ранее kafkacat)**: Универсальный не-Java инструмент (на базе `librdkafka`) для работы с Kafka. Идеален для отладки, чтения данных и интеграции в shell-пайплайны.
- **rpk (Redpanda CLI)**: Современный, быстрый инструмент на Go. Несмотря на то, что это основной CLI для Redpanda, он полностью совместим с Apache Kafka и часто используется как более удобная альтернатива стандартным скриптам.
- **kafkactl**: Специализированный CLI с интерфейсом в стиле `kubectl`, ориентированный на управление множеством кластеров через контексты.
- **Confluent CLI**: Фирменный инструмент для работы с Confluent Cloud и Confluent Platform.

## Основные концепции

### Сравнение инструментов

| Критерий | Стандартные утилиты | kcat | rpk | kafkactl |
| :--- | :--- | :--- | :--- | :--- |
| **Язык / Зависимости** | Java (JVM) | C (librdkafka) | Go (статический бинарный файл) | Go (статический бинарный файл) |
| **Стиль команд** | Множество скриптов | Флаги (`-C`, `-P`, `-L`) | Глагол + Существительное (`rpk topic ...`) | Интерфейс `kubectl` (`get topics`) |
| **Управление кластерами** | Параметры в каждой команде | Параметры командной строки | Конфигурационные профили | Контексты (YAML) |
| **Администрирование** | Максимальное (ACL, Configs) | Только данные и метаданные | Высокое (Topic, Group, ACL) | Среднее (Topic, Group) |

### Архитектура подключения и контексты

Современные инструменты (`kafkactl`, `rpk`, `confluent-cli`) используют концепцию **контекстов** или **профилей**. Это позволяет переключаться между разными кластерами (например, `dev`, `staging`, `prod`) без ручного ввода адресов брокеров и путей к сертификатам.

**Преимущества профилей:**
1. **Безопасность**: Секреты хранятся в зашифрованных файлах или переменных окружения.
2. **Скорость**: Отсутствие необходимости в длинных флагах `--bootstrap-server` и `--command-config`.
3. **Единообразие**: Команды выглядят одинаково для любого окружения.

## Практические сценарии

### Сценарий 1: Управление топиками

**Стандартные утилиты:**
```bash
# Список топиков
kafka-topics.sh --bootstrap-server localhost:9092 --list

# Описание топика
kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic orders
```

**rpk:**
```bash
# Список топиков
rpk topic list

# Создание топика с настройками
rpk topic create orders -p 12 -r 3 --topic-config retention.ms=604800000
```

**kafkactl:**
```bash
# Детальная информация
kafkactl describe topic orders
```

### Сценарий 2: Чтение и отправка данных

**kcat:**
```bash
# Чтение в JSON формате с метаданными
kcat -b localhost:9092 -t orders -C -J

# Потребление сообщений с фильтрацией через jq
kcat -b localhost:9092 -t orders -C -e | jq '.payload'
```

**rpk:**
```bash
# Чтение сообщений
rpk topic consume orders

# Отправка сообщения из файла
rpk topic produce orders < message.json
```

### Сценарий 3: Группы потребителей и LAG

**Стандартные утилиты:**
```bash
# Список групп
kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list

# Проверка лага (самая частая операция)
kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group my-service
```

**rpk:**
```bash
# Просмотр состояния групп
rpk group describe my-service
```

### Сценарий 4: Динамическая конфигурация (kafka-configs.sh)

Утилита `kafka-configs.sh` позволяет менять настройки брокеров и топиков «на лету» без перезагрузки.

```bash
# Ограничение скорости (квота) для пользователя
kafka-configs.sh --bootstrap-server localhost:9092 --alter --add-config 'producer_byte_rate=1048576' --entity-type users --entity-name user1

# Включение сжатия для топика
kafka-configs.sh --bootstrap-server localhost:9092 --alter --entity-type topics --entity-name orders --add-config compression.type=lz4

# Просмотр текущих настроек брокера
kafka-configs.sh --bootstrap-server localhost:9092 --describe --entity-type brokers --entity-name 1
```

### Сценарий 5: Управление правами доступа (ACL)

Используется для настройки безопасности в кластере.

```bash
# Разрешить пользователю чтение из топика
kafka-acls.sh --bootstrap-server localhost:9092 --add --allow-principal User:alice --operation Read --topic orders --group my-group

# Список всех ACL
kafka-acls.sh --bootstrap-server localhost:9092 --list
```

## Дополнительная информация

### Выбор инструмента

- **rpk**: Лучший выбор для повседневных операций (Topic, Group, ACL). Быстрый, современный и не требует Java.
- **kcat**: Незаменим для сложных пайплайнов обработки данных в shell.
- **Стандартные утилиты**: "Последняя миля" для специфических задач (перераспределение партиций, низкоуровневые конфиги).
- **kafkactl**: Удобен при работе с десятками разных кластеров.

### См. также

- **[Обзор Apache Kafka](./kafka_overview.md)** — архитектура и основные понятия.
- **[Партиционирование и балансировка](./partitioning_and_balancing.md)** — детали работы с разделами.
- **[Гарантии доставки](./delivery_guarantees.md)** — настройки надежности (acks, retries).
