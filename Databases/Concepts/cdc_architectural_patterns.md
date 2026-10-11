# Архитектурные паттерны CDC (Change Data Capture)

**Актуально для:** Debezium 3.x, Apache Kafka 3.x, PostgreSQL 18, MySQL 8.4 LTS, MariaDB 12.x, MongoDB 8.0, SQL Server 2022

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

### Почему WAL и Binlog — физическая основа CDC

CDC через чтение журналов работает, потому что СУБД гарантирует **Write-Ahead Logging (WAL)**. Любое изменение данных сначала попадает в последовательный лог на диск, и только потом обновляет страницы данных. Благодаря этому:

1.  **Изменения доступны до фиксации приложением.** Приложение может выполнить `COMMIT`, а CDC уже прочитал событие из WAL и доставил его в Kafka. Consumer получает событие практически одновременно с фиксацией.
2.  **Нет двойной записи.** Trigger-based CDC пишет событие дважды: один раз в основную таблицу, второй раз в shadow-таблицу. WAL-based CDC читает уже записанное изменение.
3.  **Гарантия доставки.** Если Consumer упал, он может "догнать" позицию из WAL, потому что WAL хранится до подтверждения доставки на все подписчики.

В PostgreSQL логическое декодирование (`pgoutput`, `wal2json`) преобразует физический WAL в независимый поток изменений. В MySQL/MariaDB это `binlog` в режиме `ROW`, где каждая строка после изменения записывается как отдельная запись. В MongoDB — **oplog** ( capped collection ), который хранит изменения в порядке их применения.

### Общая архитектура (Data Hub)

CDC превращает базу данных из "пассивного хранилища" в "активный источник событий". Это фундамент архитектуры **Event-Driven Data Integration**.

```text
[ Source DB ] -> [ Debezium (Kafka Connect) ] -> [ Apache Kafka ] -> [ Consumers / Sinks ]
       |                 |                             |                    |
  (WAL/Binlog)      (Log Reader)                  (Event Log)        (ES, Redis, OLAP)
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

Для работы Log-based CDC необходимо подготовить СУБД-источник и инфраструктуру доставки.

### Требования к СУБД-источнику

1.  **Включено логическое журналирование.** Для PostgreSQL — `wal_level = logical`. Для MySQL/MariaDB — `binlog_format = ROW` и `binlog_row_image = FULL`.
2.  **Актуальная версия СУБД.** CDC опирается на стабильные форматы WAL/Binlog. Минимальные версии: PostgreSQL 12+, MySQL 8.0+, MariaDB 10.5+, MongoDB 4.0+, SQL Server 2016+.
3.  **Достаточные права доступа.** Пользователь для CDC должен иметь роль `REPLICATION` (PostgreSQL) / `REPLICATION SLAVE` (MySQL) и `SELECT` на целевые таблицы. Для чтения WAL в PostgreSQL требуется атрибут `REPLICATION` в pg_hba.conf.
4.  **Настроен retention для журналов.** WAL/Binlog должны храниться достаточно долго, чтобы компенсировать простой консьюмера. Рекомендуется: не менее 72 часов архивации.
5.  **REPLICA IDENTITY (PostgreSQL).** Для получения состояния `before` при UPDATE/DELETE настройте `REPLICA IDENTITY FULL` на таблицах, где требуется отслеживание изменений.

### Требования к инфраструктуре (SRE/Sysadmin)

1.  **Отдельные диски для данных и журналов.** WAL/Binlog — последовательная запись, данные — случайная. Разделение на `data` и `wal` mounts позволяет изолировать профили нагрузки и упрощает troubleshooting.
2.  **Синхронизация времени (NTP).** Все узлы (БД, Kafka Connect, Kafka brokers) должны иметь синхронизированные часы. `ts_ms` в событиях Debezium используется для упорядочивания и идемпотентности.
3.  **Сетевая доступность.** Kafka Connect должен иметь стабильный TCP-доступ до порта 5432/3306/27017 на СУБД и до портов 9092/2181 на Kafka. Настройте firewall и MTU; для cross-DC — рассмотрите VPN или dedicated link.
4.  **Хранилище ключей (Vault/OpenBao/HSM).** Пароли для подключения к СУБД и шифрования данных в transit должны храниться в системе управления секретами, а не в конфигах.
5.  **Runbook и escalation.** Документируйте процедуры: как перезапустить коннектор, как очистить зависший slot, как переключить на резервный Kafka Connect.

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

#### Валидация

1.  **Проверка slot в PostgreSQL:**
    ```sql
    SELECT slot_name, slot_type, active, restart_lsn, confirmed_flush_lsn
    FROM pg_replication_slots
    WHERE slot_name = 'debezium_slot';
    # → active = true, confirmed_flush_lsn растет
    ```
2.  **Проверка позиции в MySQL:**
    ```sql
    SHOW REPLICA STATUS\G
    # → Replica_IO_Running: Yes, Seconds_Behind_Source: 0
    ```
3.  **Проверка метрик Debezium:** В логах Kafka Connect ищите строки `WorkerInfo` и `ConnectorInfo`. Отсутствие ошибок `ERROR` в логах в течение 5 минут — признак стабильной работы.

#### Очистка / Откат

1.  **Удаление коннектора:**
    ```bash
    curl -X DELETE http://kafka-connect:8083/connectors/inventory-connector
    ```
2.  **Удаление slot (PostgreSQL):**
    ```sql
    SELECT pg_drop_replication_slot('debezium_slot');
    ```
3.  **Удаление publication (PostgreSQL 10+):**
    ```sql
    DROP PUBLICATION dbz_publication;
    ```
4.  **Очистка Kafka topics:** Удалите топики, созданные коннектором, через `kafka-topics.sh --delete --topic <name>`. Убедитесь, что консьюмеры больше не используют эти топики.

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

1.  **Избегайте огромных транзакций:** CDC читает WAL последовательно. Одна транзакция на 10 ГБ может "забить" канал и вызвать огромный лаг. Разбивайте массовые операции на батчи по 10 000–100 000 строк.
2.  **Мониторинг слотов репликации:** Если коннектор упал, слот репликации в Postgres будет накапливать WAL на диске до тех пор, пока не закончится место. Всегда настраивайте алерты на `pg_wal` size и `active = false` дольше 5 минут.
3.  **Использование Avro/Protobuf:** JSON слишком избыточен для CDC (метаданные могут занимать 80% объема). Schema Registry поможет контролировать изменения схем. Для новых проектов используйте Avro с Schema Registry по умолчанию.
4.  **Фильтрация на источнике:** Используйте `table.include.list` или `column.exclude.list`, чтобы не передавать лишние данные (например, логи приложений или технические таблицы) в Kafka.
5.  **Настройка Snapshot:** Для больших таблиц используйте `snapshot.mode = initial_only` или инкрементальные снапшоты (Debezium 2.x+), чтобы не блокировать БД. Для PostgreSQL 18+ рассмотрите `snapshot.mode = when_needed` с курсором на транзакции.
6.  **Надежность доставки:** Настройте Kafka topics с `replication.factor=3` и `min.insync.replicas=2`. Включите `acks=all` на producer side.
7.  **Идемпотентность sink:** Гарантия At-Least-Once означает возможные дубли. Всегда проектируйте sink с идемпотентностью: UPSERT по primary key, дедупликация по `source.ts_ms` + `source.lsn`.
8.  **Retention WAL/Binlog:** Храните журналы не менее 72 часов. Для PostgreSQL настройте `wal_keep_size` и архив. Для MySQL — `binlog_expire_logs_seconds`.
9.  **Разделение дисков:** Храните WAL/Binlog на выделенном устройстве с высокой последовательной производительностью. Данные — на другом устройстве с высокой случайной производительностью.
10. **Тестируйте failover коннектора:** Раз в квартал выполняйте drill: остановите Kafka Connect, убедитесь, что slot не переполняет WAL, перезапустите, проверьте, что события доставлены без дублей и потерь.
11. **Используйте GTID в MySQL/MariaDB:** GTID устойчив к ротации бинарных логов и упрощает автоматизацию восстановления. Настройте `gtid_mode = ON` и `enforce_gtid_consistency = ON`.
12. **Следите за `Seconds_Behind_Source` в MySQL:** При значении > 60 секунд Debezium начинает отставать. Настройте алерт и проверьте пропускную способность сети и диск на Kafka Connect.
13. **Включайте `max_slot_wal_keep_size`:** В PostgreSQL 13+ ограничьте рост WAL при неактивном slot, чтобы предотвратить переполнение диска.
14. **Настройка `wal_sender_timeout`:** Если между PostgreSQL и Kafka Connect высокая задержка, увеличьте `wal_sender_timeout` до 300 секунд, чтобы избежать разрыва репликации.

## Эксплуатация и SRE-метрики

### Мониторинг надежности
1.  **Consumer Lag (Kafka):** Разрыв между последним событием в Kafka и последним обработанным событием консьюмером.
2.  **Connector Lag (Debezium):** Разрыв между LSN в базе данных и позицией, которую прочитал Debezium.
3.  **Capture Error Rate:** Количество ошибок при чтении логов (например, из-за удаления старых WAL-файлов).

### SLO и SLI для CDC

| SLI (Service Level Indicator) | Целевое значение (SLO) | Измерение |
| :--- | :--- | :--- |
| **End-to-end latency** (DB change → Sink) | P99 < 5 секунд | Разница `ts_ms` в событии и временем записи в целевую БД |
| **Consumer Lag** | < 10 секунд | `kafka_consumergroup_lag` в Prometheus |
| **Connector uptime** | 99.9% | Время в статусе `RUNNING` / общее время |
| **Data completeness** | 100% событий доставлены | Сравнение счетчиков INSERT/UPDATE/DELETE в источнике и sink |
| **Schema compatibility** | 100% совместимых изменений | Количество ошибок `Schema mismatch` / всего изменений схемы |

### Runbook: Перезапуск коннектора после сбоя

1.  **Проверка статуса:**
    ```bash
    curl -s http://kafka-connect:8083/connectors/inventory-connector/status | jq
    # → ищите "state": "FAILED" или "RUNNING" == false
    ```
2.  **Остановка коннектора:**
    ```bash
    curl -X DELETE http://kafka-connect:8083/connectors/inventory-connector
    ```
3.  **Проверка slot (PostgreSQL):**
    ```sql
    SELECT slot_name, active, restart_lsn FROM pg_replication_slots
    WHERE slot_name = 'debezium_slot';
    # → active = false означает, что slot неактивен
    ```
4.  **Перезапуск:**
    ```bash
    curl -X POST -H "Content-Type: application/json" \
      --data @connector-config.json \
      http://kafka-connect:8083/connectors
    ```
5.  **Валидация:** Проверьте, что `active` снова стал `true`, а `confirmed_flush_lsn` растет.

### Compliance и аудит

1.  **Неизменяемость Kafka topics:** Для аудита настройте topic retention на `-1` (бесконечно) или используйте immutable storage. Запретите compaction для аудит-топиков.
2.  **PII маскирование:** Используйте SMT `MaskField` для обезличивания данных перед записью в Kafka. Документируйте, какие колонки маскируются и какой алгоритм используется.
3.  **Журнал доступа:** Включите аудит подключений к СУБД (`pg_audit` в PostgreSQL, `audit_log` в MySQL) для отслеживания, кто и когда изменял данные через приложения.
4.  **Резервное копирование Schema Registry:** Реестр схем — критически важный компонент. Включите репликацию и регулярный бэкап.
5.  **Тестирование отката:** Раз в квартал выполняйте drill: отключите коннектор, убедитесь, что slot не переполняет WAL, перезапустите, проверьте, что все события доставлены без дублей.

### Chaos Engineering и отказоустойчивость

1.  **Отключение Kafka Connect:** Убедитесь, что при падении Kafka Connect slot не вызывает переполнение WAL. Проверьте поведение с `max_slot_wal_keep_size`.
2.  **Задержка сети между Kafka Connect и СУБД:** Проверьте, что Debezium корректно обрабатывает таймауты и переподключения.
3.  **Падение одного Kafka broker:** Kafka поддержиет replication factor >= 3. Проверьте, что топики созданы с `replication.factor=3` и `min.insync.replicas=2`.
4.  **Изменение схемы в источнике:** Выполните `ALTER TABLE` на staging и убедитесь, что Schema Registry обрабатывает изменение корректно, а sink-система не теряет данные.

## Поиск и устранение неисправностей

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **События перестали приходить** | Слот репликации в PG неактивен. | Проверить `pg_replication_slots`. Перезапустить коннектор. |
| **Дублирование данных** | Перезапуск консьюмера при гарантии At-Least-Once. | Обеспечьте **идемпотентность** на стороне Sink (например, UPSERT по PK). |
| **Рост WAL на мастере** | Debezium не успевает вычитывать логи. | Увеличьте `logical_decoding_work_mem`. Проверьте пропускную способность до Kafka. |
| **Sink Connector падает** | Несоответствие типов данных (например, `null` в обязательном поле). | Настройте DLQ (Dead Letter Queue) в Kafka Connect. |
| **Snapshot завис на 0%** | Блокировка таблиц (Access Exclusive Lock) другими процессами. | Проверьте `pg_stat_activity` на предмет длинных транзакций, удерживающих замки на таблицы из `include.list`. |
| **Ошибка Schema mismatch** | Изменение схемы в БД без обновления Schema Registry. | Обновите схему в Registry или настройте `auto.register.schemas=true` (только для Dev). |
| **Connector в статусе FAILED** | Ошибка подключения или нехватка прав. | Изучите логи Kafka Connect: `grep -i 'ERROR\\|FAIL' /var/log/kafka-connect/connect.log` или `journalctl -u kafka-connect`. Проверьте сетевые доступы. |
| **Replication slot overflow** | Consumer долго не читает Kafka, slot накапливает WAL. | Остановите коннектор, убедитесь, что WAL не переполняет диск, удалите slot и пересоздайте с `max_slot_wal_keep_size`. |
| **MySQL: потеря binlog** | `binlog_expire_logs_seconds` слишком мал, Debezium запросил старую позицию. | Увеличьте retention binlog. Если данные потеряны — перезапустите коннектор с `snapshot.mode=initial_only`. |
| **События приходят с задержкой** | Недостаток ресурсов на Kafka Connect или сетевой bottleneck. | Проверьте `top`/`htop` на узле Kafka Connect, увеличите `num.connectors` или добавьте workers. |
| **Out Of Memory на Kafka Connect** | Слишком много коннекторов или большой `logical_decoding_work_mem`. | Ограничьте память JVM (`-Xmx`), увеличьте `logical_decoding_work_mem` на стороне СУБД, распределите коннекторы по нескольким инстансам. |
| **События не упорядочены** | Primary Key не использован как ключ партиционирования. | Настройте `primary.key.mode=record_key` и `primary.key.fields=id` в коннекторе. |
| **GTID сбился (MySQL)** | Сеть разорвана во время логирования, GTID не согласован. | Выполните `RESET MASTER` только если у вас есть полный бэкап. Для восстановления GTID используйте `gtid_purged`. |

### Edge Cases и ограничения

1.  **DDL-операции (ALTER TABLE).** Debezium не отправляет DDL как отдельное событие по умолчанию. Для захвата DDL включите `database.history.kafka.bootstrap.servers` и `schema.history.internal.kafka.topic`. Без этого коннектор может упасть при изменении схемы.
2.  **Транзакции объемом > 1 ГБ.** PostgreSQL ограничивает размер одного WAL-сегмента (обычно 16 MB или 64 MB). Огромные транзакции могут вызвать "забивание" канала и огромный лаг. Разбивайте массовые операции на батчи.
3.  **Major version mismatch.** Не рекомендуется подключать Debezium к СУБД с другой major версией, чем та, для которой собран коннектор. Проверьте compatibility matrix в документации Debezium.
4.  **Сеть с задержкой > 10 секунд.** При высоком latency между Kafka Connect и СУБД логический репликационный слот может отвалиться. Настройте `wal_sender_timeout` и `tcp_keepalives_idle`.
5.  **Зависшие транзакции (idle in transaction).** Длинные транзакции мешают VACUUM и ротации WAL. Настройте `idle_in_transaction_session_timeout = 5min` в PostgreSQL.
6.  **Одновременный откат и CDC.** Если во время отката миграции Debezium активен, он может доставить часть откатываемых событий. Остановите коннектор перед опасной операцией и перезапустите после.

## Дополнительная информация

### Смежные темы
- **[Паттерны кэширования](../../Concepts/Caching/caching_patterns.md)** — использование CDC для Redis.
- **[Распределенные транзакции](./distributed_transactions.md)** — паттерн Outbox и его связь с CDC.
- **[Журнал предзаписи (WAL)](./write_ahead_log.md)** — физическая основа CDC.
- **[Моделирование хранилища данных](./dwh_modeling.md)** — CDC как источник поставки данных в DWH (ETL/ELT).
- **[Интеграция ClickHouse и Kafka](../ClickHouse/clickhouse_kafka_integration.md)** — детали со стороны приемника.
- **[Neo4j: Change Data Capture](../Neo4j/cdc_integration.md)** — родной CDC Neo4j (`db.cdc.query`, `txLogEnrichment`), отличающийся от Debezium-based CDC реляционных СУБД.
