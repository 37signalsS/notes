# Архитектурные паттерны CDC (Change Data Capture)

## Определения

**Change Data Capture (CDC)** — это набор технологических паттернов для идентификации и захвата изменений в базе данных (INSERT, UPDATE, DELETE) с целью их доставки в другие системы в реальном времени.

### Типы реализации CDC

1.  **Log-based CDC (Рекомендуемый):** Чтение журналов транзакций СУБД (WAL в Postgres, Binlog в MySQL).
    - **Плюсы:** Минимальная нагрузка на БД, захват всех промежуточных состояний, не требует изменения схемы.
    - **Минусы:** Требует специфических прав доступа и настройки параметров журналирования.
2.  **Query-based CDC:** Периодический опрос таблиц по колонке `updated_at`.
    - **Плюсы:** Простота реализации, не зависит от типа СУБД.
    - **Минусы:** Не захватывает удаления (DELETE), нагружает БД частыми SELECT, задержка (Polling Interval).
3.  **Trigger-based CDC:** Использование триггеров для записи изменений в отдельную "shadow" таблицу.
    - **Плюсы:** Гарантированный захват на уровне приложения БД.
    - **Минусы:** Существенное снижение производительности записи (каждый INSERT порождает второй INSERT), сложность поддержки схем.

**Компоненты стека Debezium + Kafka:**
- **Source Database:** СУБД-источник (PostgreSQL, MySQL, MongoDB), где включено логическое журналирование.
- **Debezium:** Платформа CDC с открытым исходным кодом, работающая как набор коннекторов для Kafka Connect. Она читает журналы транзакций и преобразует их в поток событий.
- **Apache Kafka:** Распределенный брокер сообщений, выступающий в роли отказоустойчивого буфера и транспортного слоя.
- **Kafka Connect:** Фреймворк для масштабируемого запуска коннекторов Debezium.
- **Sink Connectors:** Готовые компоненты для записи данных из Kafka в целевые системы (Elasticsearch, ClickHouse).
- **Custom Consumers:** Приложения, реализующие бизнес-логику на основе потока изменений.

## Основные концепции

### Общая архитектура (Data Hub)

CDC превращает базу данных из "пассивного хранилища" в "активный источник событий". Это фундамент архитектуры **Event-Driven Data Integration**.

```text
[ Source DB ] -> [ Debezium (Kafka Connect) ] -> [ Apache Kafka ] -> [ Consumers / Sinks ]
      |                 |                             |                    |
 (WAL/Binlog)      (Log Reader)                  (Event Log)        (ES, Redis, S3)
```

**Преимущества паттерна:**
1.  **Low Latency:** Изменения доставляются за миллисекунды.
2.  **Zero Load on Application:** Приложению не нужно знать о других системах (решение проблемы Dual Writes).
3.  **Reliability:** Kafka гарантирует доставку (At-Least-Once) и позволяет "переигрыть" события (Replay).
4.  **Decoupling:** Полная изоляция источника и приемников.

### Формат событий Debezium
Каждое событие Debezium — это сложный JSON (или Avro/Protobuf), содержащий:
- **`op`:** Тип операции (`c` — create, `u` — update, `d` — delete, `r` — read/snapshot).
- **`before`:** Состояние строки до изменения (null для INSERT).
- **`after`:** Состояние строки после изменения (null для DELETE).
- **`source`:** Метаданные источника (имя БД, таблица, LSN, transaction id, timestamp).
- **`ts_ms`:** Время захвата события Debezium.

Пример структуры (упрощенно):
```json
{
  "before": { "id": 1, "status": "new" },
  "after": { "id": 1, "status": "processed" },
  "source": { "version": "2.5.0", "db": "inventory", "table": "orders", "lsn": 123456 },
  "op": "u",
  "ts_ms": 1672531200000
}
```

## Предварительные требования

Для работы Log-based CDC необходимо подготовить СУБД-источник.

### Настройка PostgreSQL
1.  **Уровень WAL:** Установите `wal_level = logical` в `postgresql.conf`.
2.  **Слоты репликации:** Увеличьте `max_replication_slots` (минимум 1 на каждый коннектор) и `max_wal_senders`.
3.  **Права доступа:** Пользователь должен иметь роль `REPLICATION` и доступ `SELECT` к таблицам.
4.  **REPLICA IDENTITY:** Для получения состояния `before` при UPDATE/DELETE выполните:
    ```sql
    ALTER TABLE my_table REPLICA IDENTITY FULL;
    ```

### Настройка MySQL
1.  **Binlog:** Включите `log-bin` и установите `binlog_format = ROW`.
2.  **Row Image:** Установите `binlog_row_image = FULL` для захвата всех колонок.

## Практическая реализация

Настройка Debezium выполняется через REST API сервиса Kafka Connect.

### 1. Регистрация коннектора (PostgreSQL)
Отправьте POST-запрос на `http://kafka-connect:8083/connectors`:

```json
{
  "name": "inventory-connector",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "postgres",
    "database.port": "5432",
    "database.user": "debezium",
    "database.password": "dbz",
    "database.dbname": "inventory",
    "database.server.name": "dbserver1",
    "table.include.list": "public.orders,public.products",
    "plugin.name": "pgoutput",
    "slot.name": "debezium_slot",
    "publication.name": "dbz_publication"
  }
}
```

### 2. Проверка статуса
```bash
# Список активных коннекторов
curl -s http://kafka-connect:8083/connectors

# Статус конкретного коннектора
curl -s http://kafka-connect:8083/connectors/inventory-connector/status | jq
```

### 3. Проверка данных в Kafka
Используйте `kafka-console-consumer` для верификации потока:
```bash
kafka-console-consumer --bootstrap-server kafka:9092 \
  --topic dbserver1.public.orders --from-beginning
```

## Практические сценарии доставки

### 1. Поисковая индексация (Elasticsearch / OpenSearch)
Автоматическое обновление поискового индекса при изменении данных в основной БД.
- **Флоу:** `PostgreSQL -> Debezium -> Kafka -> Elasticsearch Sink Connector`.
- **Зачем:** Обеспечение актуальности поиска без синхронных запросов из кода приложения.
- **Нюанс:** Требуется денормализация. Если в ES нужен "широкий" документ из нескольких таблиц БД, используйте **Kafka Streams** или **Flink** для JOIN-а потоков в реальном времени перед записью в Sink.

### 2. Инвалидация и обновление кэша (Redis)
Реализация паттерна Write-Through на уровне инфраструктуры.
- **Флоу:** `PostgreSQL -> Debezium -> Kafka -> Custom Consumer -> Redis`.
- **Два подхода:**
    - **Инвалидация:** Consumer просто удаляет ключ в Redis по ID из события.
    - **Обновление:** Consumer обновляет значение в Redis данными из поля `after`.
- **Зачем:** Исключение "грязного" кэша и упрощение кода приложения (убираем логику удаления кэша из бизнес-слоя).

### 3. CQRS (Command Query Responsibility Segregation)
Разделение модели записи (OLTP) и модели чтения (ReadOnly API / Dashboard).
- **Флоу:** `Write DB -> CDC -> Kafka -> Read DB (например, MongoDB или другая инстанция Postgres)`.
- **Зачем:** Оптимизация тяжелых выборок на чтение без влияния на производительность транзакционного мастера.

### 4. Аналитический мост (ClickHouse / Snowflake)
Доставка данных в DWH/OLAP системы для аналитики.
- **Инструментарий:** PeerDB (для ClickHouse) или нативные Sink коннекторы.
- Подробнее: **[Интеграция PostgreSQL и ClickHouse](../PostgreSQL/Integrations/clickhouse.md)**.

### 5. Аудит и комплаенс
Создание неизменяемого журнала всех изменений данных для безопасности и аудита.
- **Преимущество:** В отличие от аудита в БД, события в Kafka могут храниться вечно (Topic Retention) и доступны для анализа без нагрузки на транзакционную БД.

### 6. Трансформация данных «на лету» (SMT)
Изменение структуры сообщения внутри Kafka Connect перед отправкой в Kafka.
- **Примеры SMT (Single Message Transformations):**
    - `ExtractNewRecordState`: Разворачивает структуру Debezium, оставляя только поля из `after` (удобно для простых Sink).
    - `MaskField`: Маскирование PII (персональных данных) перед записью в Kafka.
    - `RouteByField`: Динамическое распределение событий по разным топикам на основе значения колонки.

## Рекомендации и Best Practices

1.  **Избегайте огромных транзакций:** CDC читает WAL последовательно. Одна транзакция на 10 ГБ может "забить" канал и вызвать огромный лаг.
2.  **Мониторинг слотов репликации:** Если коннектор упал, слот репликации в Postgres будет накапливать WAL на диске до тех пор, пока не закончится место. Всегда настраивайте алерты на `pg_wal` size.
3.  **Использование Avro/Protobuf:** JSON слишком избыточен для CDC (метаданные могут занимать 80% объема). Schema Registry поможет контролировать изменения схем.
4.  **Фильтрация на источнике:** Используйте `table.include.list` или `column.exclude.list`, чтобы не передавать лишние данные (например, логи приложений или технические таблицы) в Kafka.
5.  **Настройка Snapshot:** Для больших таблиц используйте `snapshot.mode = initial_only` или инкрементальные снапшоты (Debezium 2.x+), чтобы не блокировать БД.

## Эксплуатация и SRE-метрики

### Мониторинг надежности
1.  **Consumer Lag (Kafka):** Разрыв между последним событием в Kafka и последним обработанным событием консьюмером.
2.  **Connector Lag (Debezium):** Разрыв между LSN в базе данных и позицией, которую прочитал Debezium.
3.  **Capture Error Rate:** Количество ошибок при чтении логов (например, из-за удаления старых WAL-файлов).

### Обработка изменений схемы (Schema Evolution)
- **Проблема:** При `ALTER TABLE` в источнике Debezium меняет формат сообщения. Sink может упасть.
- **Решение:** Использование **Schema Registry** (Avro/Protobuf). Коннекторы проверяют совместимость схем. Рекомендуется использовать режим `Forward Compatibility` для Sink-систем.

### Масштабирование и порядок (Ordering)
- **Partitioning:** Для сохранения порядка изменений одной строки (например, UPDATE после INSERT) используйте **Primary Key** как ключ партиционирования в Kafka. Все изменения одного ID попадут в одну партицию и будут обработаны последовательно.

## Поиск и устранение неисправностей

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **События перестали приходить** | Слот репликации в PG неактивен. | Проверить `pg_replication_slots`. Перезапустить коннектор. |
| **Дублирование данных** | Перезапуск консьюмера при гарантии At-Least-Once. | Обеспечьте **идемпотентность** на стороне Sink (например, UPSERT по PK). |
| **Рост WAL на мастере** | Debezium не успевает вычитывать логи. | Увеличьте `logical_decoding_work_mem`. Проверьте пропускную способность до Kafka. |
| **Sink Connector падает** | Несоответствие типов данных (например, `null` в обязательном поле). | Настройте DLQ (Dead Letter Queue) в Kafka Connect. |
| **Snapshot завис на 0%** | Блокировка таблиц (Access Exclusive Lock) другими процессами. | Проверьте `pg_stat_activity` на предмет длительных транзакций, удерживающих замки на таблицы из `include.list`. |
| **Ошибка Schema mismatch** | Изменение схемы в БД без обновления Schema Registry. | Обновите схему в Registry или настройте `auto.register.schemas=true` (только для Dev). |
| **Connector в статусе FAILED** | Ошибка подключения или нехватка прав. | Изучите логи Kafka Connect: `kubectl logs <connect-pod>`. Проверьте сетевые доступы. |

## Дополнительная информация

### Смежные темы
- **[Паттерны кэширования](../../Concepts/Caching/caching_patterns.md)** — использование CDC для Redis.
- **[Распределенные транзакции](./distributed_transactions.md)** — паттерн Outbox и его связь с CDC.
- **[Журнал предзаписи (WAL)](./write_ahead_log.md)** — физическая основа CDC.
- **[Интеграция ClickHouse и Kafka](../ClickHouse/clickhouse_kafka_integration.md)** — детали со стороны приемника.
