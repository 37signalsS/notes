# Интеграция PostgreSQL и ClickHouse

**Актуально для:** ClickHouse 26.7.x (Stable) / PostgreSQL 12+

## Определения и терминология

**Гибридная архитектура (HTAP)** — использование комбинации систем для обработки транзакционных (OLTP) и аналитических (OLAP) нагрузок в рамках одной экосистемы.

*   **PostgreSQL (OLTP):** Система-источник «горячих» транзакционных данных. Гарантирует целостность через [ACID](../../Concepts/acid.md).
*   **ClickHouse (OLAP):** Система-приемник данных для высокоскоростной аналитики.
*   **CDC (Change Data Capture):** Технология отслеживания изменений в базе данных (через чтение логов транзакций) для их репликации в реальном времени.
*   **LSN (Log Sequence Number):** Уникальный идентификатор позиции в логе транзакций PostgreSQL, используется для синхронизации и мониторинга лага.
*   **Replica Identity:** Метка строки в логической репликации PostgreSQL, по которой ClickHouse находит строку для `UPDATE`/`DELETE` (по умолчанию — первичный ключ, альтернатива — уникальный индекс).
*   **Named Collection:** Именованный набор параметров подключения в конфигурации ClickHouse (или SQL-объект), позволяющий не хранить пароли в SQL-запросах.

## Требования и подготовка

### Совместимость версий
*   **PostgreSQL:** 12+ — минимальная поддерживаемая версия для табличного движка `PostgreSQL` и функции `postgresql()`; для CDC необходима логическая репликация (`wal_level = logical`, плагин `pgoutput`).
*   **ClickHouse:** 26.7.x (Stable). Отдельные возможности версионированы:
    *   тип `JSON` — экспериментальный с 24.8, **production-ready в OSS с 25.3** (до 25.3 не рекомендуется для продакшена);
    *   передача произвольного `SELECT`-запроса вместо имени таблицы в `postgresql()` / движке `PostgreSQL` — **с 26.7**;
    *   настройки схемы `materialized_postgresql_schema` / `materialized_postgresql_schema_list` — **с 21.12**.

### Сетевая связность
*   **Порты:** доступ к PostgreSQL (`5432`) с серверов ClickHouse или узлов ETL (Kafka Connect, PeerDB); со стороны PostgreSQL — к ClickHouse (`9000` TCP/Native для clickhouse_fdw, `8123` HTTP).
*   **Firewall:** iptables/nftables или сетевые ACL должны пропускать эти направления; для TLS — `sslmode` в параметрах подключения.

### Конфигурация PostgreSQL (для CDC)
```ini
# postgresql.conf
wal_level = logical              # Обязательно для CDC и MaterializedPostgreSQL
max_replication_slots = 10       # Default; MaterializedPostgreSQL требует >= 2
max_wal_senders = 10             # Default
logical_decoding_work_mem = 64MB # Default; увеличить при интенсивной записи
```
После изменения `wal_level` требуется перезапуск PostgreSQL (остальные параметры — `pg_reload_conf()`).

### Права доступа
Для работы `MaterializedPostgreSQL` пользователю нужны: `CREATE PUBLICATION`, `CREATE_REPLICATION_SLOT`, `pg_drop_replication_slot` (или суперпользователь), `DROP PUBLICATION`, а также доступ к системным таблицам `pg_publication`, `pg_replication_slots`, `pg_publication_tables`. Для чтения через `postgresql()` достаточно `SELECT` (выполняется как `COPY (SELECT ...) TO STDOUT` в read-only транзакции).

## Основные концепции

### Два направления интеграции

1.  **PostgreSQL → ClickHouse:** репликация или перенос данных для аналитики (CDC, batch ETL, словари). Данные перемещаются из нормализованной OLTP-схемы в денормализованное OLAP-хранилище.
2.  **ClickHouse → PostgreSQL:** проксирование — PostgreSQL обращается к аналитическим данным ClickHouse на лету (`clickhouse_fdw`, расширение `pg_clickhouse`).

### Денормализация данных

В PostgreSQL данные обычно хранятся в нормализованном виде (много связанных таблиц) для минимизации избыточности. В ClickHouse операции `JOIN` являются дорогостоящими, поэтому основным подходом является **денормализация**.

При интеграции рекомендуется:
1.  **Объединение таблиц:** На этапе переноса данных (ETL/ELT) объединять связанные таблицы в одну «широкую» таблицу.
2.  **Материализация справочников:** Вместо хранения ID внешних ключей записывать текстовые значения (например, имя клиента вместо `customer_id`).
3.  **Использование массивов и вложенных структур:** ClickHouse эффективно работает с типами `Array` и `Nested`, что позволяет хранить связанные данные внутри одной строки.
4.  **Тип `JSON`:** прямой маппинг `JSONB` из PostgreSQL с сохранением типизации и быстрым доступом к вложенным полям как к sub-columns. Компромиссы (из документации): более медленные `INSERT`, медленное чтение целого документа целиком и дополнительные накладные расходы на хранение — если документ хранится «прозрачно», лучше использовать `String`.
5.  **Использование `ReplacingMergeTree`:** При использовании CDC (PeerDB, Kafka) на стороне ClickHouse необходимо использовать движок `ReplacingMergeTree` с указанием колонки-версии (например, `updated_at` или `lsn` из PostgreSQL) для автоматического схлопывания дубликатов при обновлениях.

### Маппинг типов данных

| PostgreSQL Type | ClickHouse Type | Комментарий |
| :--- | :--- | :--- |
| `UUID` | `UUID` | Нативная поддержка в обеих системах |
| `JSONB` | `JSON` / `String` | `JSON` production-ready с 25.3; для «прозрачного» хранения — `String` |
| `INET` / `CIDR` | `IPv4` / `IPv6` | CH автоматически парсит строки IP |
| `TIMESTAMP` / `TIMESTAMPTZ` | `DateTime64(3)` | Рекомендуется точность до миллисекунд |
| `DATE` | `Date32` / `Date` | `MaterializedPostgreSQL` мапит в `Date32` по умолчанию (`materialized_postgresql_use_extended_date_and_time_types = 1`) |
| `NUMERIC` | `Decimal(P, S)` | Требует явного указания точности (P, S) |
| `BYTEA` | `String` | Бинарные данные передаются как строки |
| `Array` | `Array(T)` | Массивы конвертируются автоматически; в CH запрещены многомерные массивы разной размерности в одном столбце |

### Разделение данных по времени (Hot/Cold)

*   **Hot data:** Последние данные (например, за последние 24 часа или текущий месяц), которые часто меняются. Хранятся в PostgreSQL.
*   **Cold data:** Исторические данные, которые используются только для чтения и анализа. Хранятся в ClickHouse.
*   **Warm data:** Промежуточный слой, который может реплицироваться в ClickHouse в реальном времени для оперативной отчетности.

## Практические сценарии

### Пакетная загрузка (Bulk Load)

Используется для начального наполнения или периодического переноса исторических срезов.

*   **Механизм 1 — прямой INSERT через табличную функцию:**
    ```sql
    INSERT INTO ch_table
    SELECT * FROM postgresql('pg-host:5432', 'db', 'users', 'app_user', 'password')
    WHERE updated_at > (SELECT max(updated_at) FROM ch_table);
    # → инкрементальная загрузка: фильтр по max(updated_at) читается из CH-таблицы
    ```
    Инкрементальная схема: сначала определяется `SELECT max(updated_at) FROM ch_table`, затем загружаются только новые строки. Для безопасности пароль передают через Named Collection, а не в тексте запроса.
*   **Механизм 2 — выгрузка через `COPY`:** `COPY (SELECT ...) TO STDOUT` в PostgreSQL → файл CSV/TSV → `clickhouse-client --query "INSERT INTO ch_table FORMAT CSV" < file.csv`.
*   **Рекомендации:** оптимальный размер пачки (batch) — от 100 тыс. до 1 млн строк; одиночные строковые `INSERT` в ClickHouse приводят к деградации (ошибка «Too many parts»).

### Нативное чтение PostgreSQL из ClickHouse

ClickHouse может напрямую обращаться к PostgreSQL на уровне табличной функции, табличного движка и движка базы данных.

#### Табличная функция `postgresql()`

```sql
-- Named Collection (рекомендуется для production; возможна и SQL-форма:
-- CREATE NAMED COLLECTION mypg AS host='...', port=5432, database='...', user='...', password='...')
SELECT * FROM postgresql(pg_analytics, table='users') WHERE str IN ('test');

-- INSERT в PostgreSQL через функцию
INSERT INTO TABLE FUNCTION postgresql('pg-host:5432', 'db', 'users', 'user', 'password') (int_id, float) VALUES (2, 3);

-- Настройка пула соединений
SELECT * FROM postgresql('pg-host:5432', 'db', 'users', 'user', 'password', SETTINGS postgresql_connection_pool_size = 32);
```
*   **Аргументы:** `host:port`, `database`, `table`, `user`, `password`, `schema` (не-default схема), `on_conflict` (например, `ON CONFLICT DO NOTHING`; снижает скорость вставки).
*   **Replicas:** перечисление через `{2|3|4}` или `host:port|host:port` — `postgresql(\`postgres{1|2|3}:5432\`, ...)`.
*   **Произвольный запрос вместо таблицы (с 26.7):** третий аргумент может быть `SELECT`-запросом — `(SELECT a, b FROM t1 JOIN t2 USING (id) WHERE a > 0)` или в форме `query('...')` (отправляется в PostgreSQL verbatim; подзапросная форма парсится ClickHouse и должна быть валидным CH SQL). Такая таблица read-only. Полезно для pushdown джойнов и агрегаций на сторону PostgreSQL. Внешние `WHERE`/`LIMIT` в окружающем запросе **не** пробрасываются внутрь переданного запроса.
*   **Реализация (важно для планирования нагрузки):** `SELECT` выполняется на стороне PostgreSQL как `COPY (SELECT ...) TO STDOUT` в read-only транзакции с коммитом после каждого запроса. На PostgreSQL пробрасываются только простые `WHERE` (`=`, `!=`, `>`, `>=`, `<`, `<=`, `IN`); все джойны, агрегации, сортировки, `IN [array]` и `LIMIT` выполняются в ClickHouse после получения данных.

#### Движок таблиц `PostgreSQL`

Прокси-таблица в ClickHouse: `SELECT` и `INSERT` на удалённой PostgreSQL-таблице, данные в ClickHouse не хранятся. Удобно для небольших таблиц-справочников и разовых анализов.

```sql
CREATE TABLE pg_proxy (float_nullable Nullable(Float32), str String, int_id Int32)
ENGINE = PostgreSQL('pg-host:5432', 'public', 'test', 'postgres_user', 'password')
SETTINGS postgresql_connection_pool_size = 32, postgresql_connection_pool_auto_close_connection = 1;
```
*   Структура может отличаться от оригинала: имена столбцов должны совпадать (можно использовать подмножество в любом порядке), типы приводятся к ClickHouse-типам.
*   **Пул соединений (настройки движка/функции, defaults):** `postgresql_connection_pool_size = 16`, `postgresql_connection_pool_wait_timeout = 5000` (мс, `0` — блокировать), `postgresql_connection_pool_retries = 2`, `postgresql_connection_pool_auto_close_connection = false`, `postgresql_connection_attempt_timeout = 2` (сек, передаётся как `connect_timeout`).
*   `external_table_functions_use_nulls` (default `1`) управляет только обработкой `Nullable`-столбцов: при `0` столбцы не делают Nullable и вместо NULL подставляются значения по умолчанию.
*   TLS/SSL: `sslmode` (`disable`/`allow`/`prefer`/`require`/`verify-ca`/`verify-full`; default libpq — `prefer`), сертификаты — путями из Named Collection (`sslrootcert`, `sslcert`, `sslkey`, только server-side файлы) или содержимым `sslrootcert_pem`/`sslcert_pem`/`sslkey_pem` (маскируются в логах, как пароль).

#### Движок базы данных `PostgreSQL`

Позволяет подключить всю схему PostgreSQL как внешнюю БД. Данные не хранятся в ClickHouse, а проксируются — каждый запрос к CH-таблице исполняется на стороне PostgreSQL.

#### Движок базы данных `MaterializedPostgreSQL` (Experimental)

Создаёт копию базы данных PostgreSQL: сначала снапшот + захват LSN, далее догоняет изменения из WAL по протоколу логической репликации. Данные каждой таблицы живут во вложенной `ReplacingMergeTree`-таблице.

```sql
SET allow_experimental_database_materialized_postgresql = 1;
CREATE DATABASE pg_mirror
ENGINE = MaterializedPostgreSQL('pg-host:5432', 'prod_db', 'reader_user', 'password');
```
*   **Статус:** экспериментальный; требует `SET allow_experimental_database_materialized_postgresql = 1`. Не поддерживается в ClickHouse Cloud.
*   **Требования:** `wal_level = logical`, `max_replication_slots >= 2`; каждая реплицируемая таблица должна иметь Replica Identity (PK по умолчанию или уникальный индекс). Проверка текущего режима:
    ```sql
    SELECT CASE relreplident
              WHEN 'd' THEN 'default' WHEN 'n' THEN 'nothing'
              WHEN 'f' THEN 'full'    WHEN 'i' THEN 'index'
           END AS replica_identity
    FROM pg_class WHERE oid = 'postgres_table'::regclass;
    ```
*   **Новые таблицы не добавляются автоматически:** `ATTACH TABLE pg_mirror.new_table;` (удаление — `DETACH TABLE pg_mirror.old_table PERMANENTLY;`).
*   **DDL:** протокол логической репликации не передаёт DDL. Изменения, ломающие репликацию (смена типа, добавление/удаление столбца), останавливают обновления для такой таблицы — лечится полной перезагрузкой через `ATTACH`/`DETACH PERMANENTLY`. Неломающие изменения (например, переименование столбца) не останавливают репликацию (вставка идёт по позиции).
*   **TOAST:** большие значения, хранящиеся вне строки, **реплицируются**; при обновлении PostgreSQL присылает ссылку на неизменённый TOAST, и существующее значение сохраняется.
*   **Ключевые настройки:** `materialized_postgresql_tables_list` (подмножество таблиц с опциональными подмножествами столбцов: `'t1(col1,col2),t2'`), `materialized_postgresql_schema` / `materialized_postgresql_schema_list` (с 21.12; таблицы доступны как `db.schema.table`), `materialized_postgresql_max_block_size` (default `65536`), `materialized_postgresql_use_extended_date_and_time_types` (default `1` → `Date32`/`DateTime64`), `materialized_postgresql_use_unique_replication_consumer_identifier` (несколько зеркал одной PG-таблицы).
*   **Failover:** логические слоты не переносятся на standby при failover PostgreSQL. Решение — управлять слотом самостоятельно (например, через Patroni) и передавать его через `materialized_postgresql_replication_slot` + `materialized_postgresql_snapshot` (идентификатор из `SELECT pg_export_snapshot()`).
*   **Бэкап/восстановление:** `BACKUP DATABASE pg_mirror TO Disk('backups', 'pg.zip');` работает (делегируется вложенной ReplacingMergeTree). Восстановление in place **не поддерживается** — восстанавливать данные следует в обычные `ReplacingMergeTree`-таблицы (`RESTORE TABLE ... AS ... SETTINGS allow_different_table_def = 1`).

### Репликация в реальном времени (CDC)

Обеспечивает минимальную задержку (Lag) между системами за счет чтения логов транзакций (WAL). Общий архитектурный паттерн с использованием Debezium и Kafka для доставки изменений в различные системы описан в разделе **[Архитектурные паттерны CDC](../../Concepts/cdc_architectural_patterns.md)**.

1.  **PeerDB:** инструмент CDC, разрабатываемый ClickHouse (OSS, AGPL-3.0, Go; документация — [docs.peerdb.io](https://docs.peerdb.io/introduction)).
    *   **Флоу настройки:** создание PostgreSQL Peer (источник с `wal_level = logical`) → создание ClickHouse Peer (приемник) → создание Mirror (задание репликации с выбором таблиц).
    *   **Преимущества:** высокая надежность, поддержка сложных схем, автоматическое управление слотами репликации и прозрачная обработка `UPDATE`/`DELETE` через автоматическое создание `ReplacingMergeTree`.
2.  **Классический стек (Kafka):** `PostgreSQL → Debezium → Kafka → ClickHouse`. Надежно, масштабируемо, поддерживает сложную трансформацию и много систем-приемников. Гарантия exactly-once достигается движком `Kafka2` + `insert_deduplicate = 1` (оффсеты в ClickHouse Keeper); детали и версии — в **[Интеграция ClickHouse и Kafka](../../ClickHouse/clickhouse_kafka_integration.md)**.
3.  **Altinity Sink Connector:** специализированный коннектор для Kafka Connect, оптимизированный под ClickHouse. Позволяет эффективно использовать движок `ReplacingMergeTree` для синхронизации изменяемых данных.

#### Настройка PostgreSQL для CDC
Для работы любого CDC-решения необходимо включить логическую репликацию (см. раздел «Конфигурация PostgreSQL для CDC» выше — `wal_level = logical`, `max_replication_slots`, `max_wal_senders`).

### Словари (Dictionaries)

Словари в ClickHouse кэшируют данные из PostgreSQL в оперативной памяти, что обеспечивает сверхбыстрый доступ (lookups).

*   **Преимущества:** данные всегда «подогреты», обновление происходит в фоне по расписанию.
*   **Использование:** замена `JOIN` со справочниками на функцию `dictGet()`.
```sql
CREATE DICTIONARY users_dict (
    id UInt64,
    name String
)
PRIMARY KEY id
SOURCE(POSTGRESQL(pg_analytics table 'users'))
LAYOUT(HASHED())
LIFETIME(MIN 300 MAX 600); -- Обновление каждые 5-10 минут
```
*   В XML-описании словаря поддерживаются реплики PostgreSQL с приоритетами (`<replica><host>...</host><priority>N</priority></replica>`; чем больше число — тем ниже приоритет, `0` — высший), `<where>`-фильтр и `<invalidate_query>` для инвалидации кэша.

### Материализованные представления (MV)

Используются для автоматической трансформации данных «на лету» при их поступлении в ClickHouse (например, из Kafka).

*   **Классические MV:** срабатывают только на новые вставки (`INSERT`). Используются для денормализации и агрегации.
*   **Refreshable MV:** обновляются целиком по расписанию. Подходят для тяжелых отчетов, где не важна репликация в реальном времени.

### Обратная интеграция: `pg_clickhouse`

Официальное расширение ClickHouse Inc. (Apache-2.0, [GitHub](https://github.com/ClickHouse/pg_clickhouse)), позволяющее выполнять аналитические запросы к ClickHouse из PostgreSQL без переписывания SQL.

*   **Механизм:** foreign-data wrapper — SQL транслируется в foreign scan к ClickHouse через HTTP-интерфейс (требуется `libcurl`), агрегации и фильтры проталкиваются (pushdown) в ClickHouse насколько это возможно. Не все запросы пушатся полностью: часть TPC-H запросов выполняется частично (см. таблицу pushdown в README).
*   **Совместимость:** PostgreSQL 14+ (тестировано до 19), ClickHouse 23+ (тестировано 23.3–26.9).
*   **Установка:** `pgxn install pg_clickhouse` (PGXN) или Docker-образ `ghcr.io/clickhouse/pg_clickhouse`; зависимости сборки — `libcurl`, `libuuid`, `liblz4`, `libzstd`, компилятор, `make`. Затем:
    ```sql
    CREATE EXTENSION pg_clickhouse;
    ```
*   **Сопутствующее расширение:** `pg_re2` — ClickHouse-совместимые regex-функции на базе RE2.

### Внешние таблицы (FDW) на стороне PostgreSQL

Использование **[clickhouse_fdw](./fdw.md)** для чтения данных из ClickHouse в джойнах с локальными табцами PG (протокол Native, порт `9000`).

*   **Ограничение:** не рекомендуется для массовой перекачки данных (ETL), так как PostgreSQL становится «бутылочным горлышком». Подходит для небольших справочников или агрегированных результатов.
*   **Настройка:** требует установки расширения в ОС и в саму базу данных.

## Валидация и диагностика (Troubleshooting)

### Мониторинг лага репликации (PostgreSQL side)
Проверка состояния слота репликации и объема WAL, ожидающего отправки:
```sql
SELECT slot_name, active,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS lag_size
FROM pg_replication_slots;
# → NULL в lag_size или inactive slot = потребитель (CH/PeerDB/Debezium) не подключен
```
Растущий `lag_size` при активном slot — сигнал перегрузки приемника или сетевой проблемы; осиротевшие слоты нужно удалять (`pg_drop_replication_slot`), иначе WAL будет расти бесконечно.

### Проверка статуса словарей (ClickHouse side)
```sql
SELECT name, type, status, last_exception
FROM system.dictionaries
WHERE name = 'users_dict';
```

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Memory limit exceeded` | Движок `PostgreSQL` читает всю таблицу в RAM при больших выборках | Пробросить фильтр на сторону PG (простой `WHERE`) или передать запрос через `query('...')` (с 26.7) |
| `Logical decoding buffer full` | Нехватка `logical_decoding_work_mem` при интенсивной записи | Увеличить параметр (128MB+) |
| `Connection refused` | `listen_addresses` / firewall | Проверить `listen_addresses` в `postgresql.conf` и правила iptables/nftables |
| UPDATE/DELETE не применяются в CH | У таблицы нет подходящей Replica Identity | Создать PK или `ALTER TABLE ... REPLICA IDENTITY USING INDEX` |
| Репликация остановилась после DDL | Ломающий DDL (тип/столбцы) | `DETACH TABLE ... PERMANENTLY`, синхронизировать схему, `ATTACH TABLE ...` |
| Репликация сломалась после failover PG | Логический слот не перенесён на standby | Управляемый слот: `materialized_postgresql_replication_slot` + `materialized_postgresql_snapshot` |
| Очередь соединений к PG / таймауты | Исчерпан пул | Настроить `postgresql_connection_pool_size` / `_wait_timeout` / `_retries` |
| `Too many parts` в CH | Мелкие вставки вместо батчей | Батчи от 100 тыс. строк, вставки через MV/Kafka |

## Лучшие практики и оптимизация

1.  **Мониторинг Lag:** при использовании CDC критически важно отслеживать задержку между `lsn` в PostgreSQL и положением потребителя. Лаг > 5 минут обычно считается критическим для оперативной аналитики.
2.  **Pushdown фильтров:** простые `WHERE` (`=`, `!=`, `>`, `>=`, `<`, `<=`, `IN`) исполняются на стороне PostgreSQL; джойны, агрегации, сортировка и `LIMIT` — только в ClickHouse. Для больших таблиц формируйте запрос так, чтобы объём данных, передаваемых по сети, был минимальным (с 26.7 — через `query('...')`).
3.  **Индексы:** в ClickHouse `ORDER BY` должен соответствовать наиболее частым фильтрам в аналитических запросах, а не повторять Primary Key из PostgreSQL.
4.  **Batching:** объединяйте мелкие вставки в пачки от 100 тыс. строк. Прямые одиночные `INSERT` из приложения в ClickHouse приводят к деградации производительности.
5.  **Schema Evolution (Развитие схемы):**
    *   При использовании CDC сначала применяйте DDL-изменения в ClickHouse (добавление колонки), а затем в PostgreSQL.
    *   Большинство инструментов (Debezium, PeerDB) требуют временной остановки репликации или пересоздания Mirror при удалении колонок или изменении типов данных.
    *   Для `MaterializedPostgreSQL` — `DETACH PERMANENTLY` / `ATTACH` для синхронизации схемы.
6.  **Безопасность подключений:** пароли и сертификаты — только через Named Collections (XML в `config.d` или `CREATE NAMED COLLECTION`), TLS — `sslmode = 'verify-full'` при передаче по недоверенным сетям.
7.  **Cleanup (откат интеграции):** остановить Mirror (PeerDB) → `DETACH TABLE ... PERMANENTLY` / `DROP DATABASE` для `MaterializedPostgreSQL` → проверить отсутствие осиротевших слотов в `pg_replication_slots` → `DROP EXTENSION pg_clickhouse` (если использовался) → закрыть порты в firewall.

## Дополнительная информация

### Сравнение способов интеграции

| Способ | Задержка (Lag) | Нагрузка на PG | Сложность | Типовой сценарий |
| :--- | :--- | :--- | :--- | :--- |
| **Bulk Load** | Высокая | Низкая | Низкая | Исторические данные (разово) |
| **FDW / Native Engines** | Мгновенно | Высокая | Низкая | Ad-hoc запросы, справочники |
| **MaterializedPostgreSQL** | Секунды | Средняя | Средняя | Репликация простых схем (Experimental) |
| **PeerDB** | < 1 сек | Низкая | Средняя | Промышленный CDC |
| **CDC (Kafka)** | Секунды | Низкая | Высокая | Сложный ETL, много систем-приемников |
| **Dictionaries** | Минуты | Средняя | Средняя | Кэширование справочников в RAM |

### Смотрите также

*   [Архитектурные паттерны CDC](../../Concepts/cdc_architectural_patterns.md)
*   [Логическая репликация в PostgreSQL](../Concepts/replication.md)
*   [Масштабирование PostgreSQL](../Concepts/scaling.md)
*   [Обзор ClickHouse](../../ClickHouse/clickhouse.md)
*   [Интеграция ClickHouse и Kafka](../../ClickHouse/clickhouse_kafka_integration.md)
*   [Foreign Data Wrappers (FDW)](./fdw.md)
