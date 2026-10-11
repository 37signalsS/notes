# CQL: синтаксис и примеры

**Актуально для:** Apache Cassandra 5.0.x / ScyllaDB 2026.x

**CQL (Cassandra Query Language)** — SQL-подобный язык запросов для Cassandra и ScyllaDB. Подробности по моделированию данных и типам — **[Обзор и моделирование данных](./overview.md)**.

## Определения

| Термин | Значение |
|---|---|
| CQL | Язык запросов Cassandra (CQL v3, спецификация 3.4.x). Не SQL: другая семантика фильтрации, сортировки и транзакций |
| cqlsh | Интерактивная оболочка для CQL (Python, native protocol driver). Подключается к одному указанному узлу; координатор маршрутизирует запросы по кольцу |
| Partition Key | Первая часть `PRIMARY KEY`; определяет распределение строк по узлам (хеш токена) |
| Clustering Column | Остальные колонки `PRIMARY KEY`; определяют порядок сортировки строк внутри партиции |
| TTL | Time To Live — время жизни данных в секундах; по истечении строка превращается в tombstone |
| LWT | Lightweight Transaction — условная операция (`IF ...`) на основе Paxos |
| Consistency Level | Уровень согласованности — сколько реплик должны подтвердить операцию |
| Batch | Группировка нескольких `INSERT`/`UPDATE`/`DELETE` в одном запросе; не аналог SQL-транзакции |

## Как работает CQL (отличия от SQL)

- **Нет JOIN и подзапросов.** Денормализация — основной способ работы с связями (см. моделирование в overview.md).
- **Нет произвольного `WHERE`.** Фильтрация только по колонкам первичного ключа (и индексам). Фильтр по другой колонке требует `ALLOW FILTERING` — полного сканирования, см. раздел SELECT.
- **`INSERT` — это upsert.** Запись с тем же первичным ключом перезаписывает предыдущую (last-write-wins по timestamp). Отдельного `MERGE`/`ON DUPLICATE KEY` нет.
- **Нет транзакций между партициями.** `BATCH` не даёт изоляции и атомарности в смысле SQL; изоляция гарантирована только внутри одной партиции.
- **`ORDER BY`** возможен только по clustering column и только в порядке, объявленном в `CLUSTERING ORDER BY` (или обратном).
- **Схема обязательна.** Типы колонок задаются при `CREATE TABLE`; JSON-интерфейс тоже проходит валидацию схемы.

## Подключение (cqlsh)

```bash
# Подключение к кластеру (порт 9042 по умолчанию)
cqlsh <node_ip> 9042

# С аутентификацией
cqlsh -u <username> -p <password> <node_ip> 9042

# Сразу в keyspace, выполнить один запрос и выйти
cqlsh -k my_app -e "SELECT * FROM user_events LIMIT 5" 10.0.1.1

# Выполнить скрипт из файла
cqlsh -f schema.cql 10.0.1.1

# TLS (настройка — в разделе Безопасность)
cqlsh --ssl 10.0.1.1 9042

# В Docker
docker exec -it <cassandra_container> cqlsh
docker exec -it <scylla_container> cqlsh
```

Основные опции CLI:

| Опция | Назначение |
|---|---|
| `-e <statement>` / `--execute` | Выполнить statement и выйти |
| `-f <file>` / `--file` | Выполнить команды из файла, затем выйти |
| `-k <keyspace>` | Подключиться к указанному keyspace |
| `-u` / `-p` | Имя пользователя и пароль |
| `--ssl` | TLS-подключение (см. [Безопасность](./security.md)) |
| `--request-timeout <sec>` | Таймаут запроса, по умолчанию 10 секунд |
| `--connect-timeout <sec>` | Таймаут подключения, по умолчанию 5 секунд |
| `--cqlshrc <path>` | Альтернативный конфиг (по умолчанию `~/.cassandra/cqlshrc`) |
| `--cqlversion` / `--protocol-version` | Зафиксировать версию CQL / native protocol (по умолчанию — максимальная поддерживаемая сервером) |
| `--encoding` | Кодировка вывода (по умолчанию utf-8) |
| `--disable-history` | Не писать историю (история по умолчанию — `~/.cassandra/cql_history`, переменная `CQL_HISTORY`) |
| `--version` / `-v` | Версия cqlsh |

**Совместимость:** конкретная версия `cqlsh` гарантированно работает только с той версией Cassandra, с которой выпущена; со старшими/младшими версиями — без гарантий. Метки времени cqlsh показывает в UTC; для отображения в другом часовом поясе (Python 3.9+) — переменная `TZ` или опция `timezone` в cqlshrc.

## Команды cqlsh (специальные команды)

Специальные команды интерпретируются самой оболочкой и не отправляются на сервер как CQL.

```sql
-- Информация о кластере и схеме (DESC — сокращение)
DESCRIBE CLUSTER;
-- → Cluster: Test Cluster
-- → Partitioner: Murmur3Partitioner

DESCRIBE KEYSPACES;
DESCRIBE KEYSPACE my_app;          -- DDL keyspace и всех её объектов
DESCRIBE TABLES;
DESCRIBE TABLE user_events;        -- полный DDL таблицы
DESCRIBE SCHEMA;                   -- DDL всех не-system keyspaces
DESCRIBE FULL SCHEMA;              -- включая system keyspaces
DESCRIBE INDEX / MATERIALIZED VIEW / TYPES / TYPE / FUNCTIONS / FUNCTION / AGGREGATES / AGGREGATE;

-- Уровень согласованности для текущей сессии
CONSISTENCY LOCAL_QUORUM;
CONSISTENCY;                       -- просмотр текущего значения

-- Serial consistency для LWT (фаза Paxos)
SERIAL CONSISTENCY LOCAL_SERIAL;

-- Трассировка запросов (диагностика latency)
TRACING ON;
SELECT * FROM user_events WHERE user_id = 550e8400-e29b-41d4-a716-446655440000;
-- → Trace session: <session_id> ... (события с source_elapsed)
TRACING OFF;
SHOW SESSION <session_id>;         -- повторный вывод трассировки

-- Формат вывода
PAGING ON;                         -- постраничный вывод (рекомендуется держать включённым)
PAGING 100;                        -- размер страницы в строках
PAGING OFF;
EXPAND ON;                         -- вертикальный вывод строк (полезно при многих колонках)
CAPTURE 'output.txt';              -- сохранять результаты запросов в файл (CAPTURE OFF — выключить)
SOURCE '/path/to/script.cql';      -- выполнить файл

-- Сессия
SHOW VERSION;                      -- [cqlsh 6.0.0 | Cassandra 5.0.9 | CQL spec 3.4.6 | Native protocol v5]
SHOW HOST;                         -- Connected to Test_Cluster at 10.0.1.1:9042.
SHOW REPLICAS 95 my_app;           -- реплики для токена (Cassandra 4.2+)
LOGIN <username> [<password>];     -- сменить пользователя сессии
HISTORY 20;                        -- последние N команд (по умолчанию 50)
HELP [topic];
EXIT;                              -- или QUIT
CLEAR;                             -- или CLS
```

**DESCRIBE** начиная с Cassandra 4.0 выполняется на сервере (CASSANDRA-14825): cqlsh 6.x не может выполнять `DESCRIBE` к кластерам 3.x. Данные трассировки пишутся в keyspace `system_traces` (таблицы `sessions`, `events`) и хранятся 24 часа; для вероятностной трассировки на узле — `nodetool settraceprobability`.

**COPY** — импорт/экспорт CSV:

```sql
COPY user_events (user_id, event_time, event_type) TO 'events.csv' WITH HEADER = true;
COPY user_events FROM 'events.csv' WITH HEADER = true;
```

Опции: `PAGESIZE` (1000), `MAXREQUESTS` (6), `INGESTRATE` (100000 строк/с), `MAXINSERTERRORS` (1000), `ERRFILE` (по умолчанию `import_<ks>_<table>.err`), `NUMPROCESSES` (16, не более cores-1), `MAXATTEMPTS` (5), `NULLVAL` (`null`).

**Экранирование:** одинарная кавычка в строковом литерале удваивается: `'I''m fine'`.

## DDL: управление схемой

```sql
-- Создание Keyspace с NetworkTopologyStrategy (для production)
CREATE KEYSPACE IF NOT EXISTS my_app WITH replication = {
    'class': 'NetworkTopologyStrategy',
    'DC1': 3,
    'DC2': 3
};

-- Cassandra 4.1+: auto-expand — те же 3 реплики во всех DC
CREATE KEYSPACE my_app2 WITH replication = {
    'class': 'NetworkTopologyStrategy',
    'replication_factor': 3
};

-- SimpleStrategy — только для тестов и single-DC (не учитывает топологию)
CREATE KEYSPACE test_ks WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

-- Использование Keyspace
USE my_app;

-- Создание таблицы
CREATE TABLE user_events (
    user_id uuid,
    event_time timeuuid,
    event_type text,
    payload text,
    PRIMARY KEY (user_id, event_time)
) WITH CLUSTERING ORDER BY (event_time DESC)
  AND default_time_to_live = 7776000;  -- TTL 90 дней

-- Добавление колонки
ALTER TABLE user_events ADD metadata map<text, text>;

-- Удаление колонки (Cassandra 3.0+)
ALTER TABLE user_events DROP metadata;

-- Переименование clustering column (Cassandra 3.0+)
ALTER TABLE user_events RENAME event_time TO occurred_at;

-- Изменение опций таблицы
ALTER TABLE user_events WITH gc_grace_seconds = 864000
  AND comment = 'события пользователей';

-- Смена RF keyspace (после — repair/rebuild, см. operations.md)
ALTER KEYSPACE my_app WITH replication = {'class': 'NetworkTopologyStrategy', 'DC1': 5};

-- Очистка данных (логическое удаление; физически — при compaction)
TRUNCATE user_events;

-- Удаление таблицы / keyspace
DROP TABLE IF EXISTS user_events;
DROP KEYSPACE IF EXISTS my_app;
```

Типичные опции таблицы (значения по умолчанию для новой таблицы, видны в выводе `DESCRIBE TABLE`):

| Опция | По умолчанию | Назначение |
|---|---|---|
| `gc_grace_seconds` | 864000 (10 дней) | Окно для repair перед окончательным удалением tombstones |
| `default_time_to_live` | 0 (без TTL) | TTL по умолчанию для всех строк таблицы |
| `bloom_filter_fp_chance` | 0.01 | Вероятность ложного срабатывания bloom filter |
| `caching` | `{'keys': 'ALL', 'rows_per_partition': 'NONE'}` | Кэширование ключей/строк |
| `compaction` | `{'class': 'SizeTieredCompactionStrategy', ...}` | Стратегия сжатия — см. [operations.md](./operations.md#стратегии-сжатия-compaction-strategies) |
| `compression` | `{'class': 'LZ4Compressor', 'chunk_length_in_kb': 64}` | Сжатие SSTables |
| `speculative_retry` | `'99PERCENTILE'` | Speculative retry при медленных репликах |
| `read_repair_chance` / `dclocal_read_repair_chance` | 0.0 / 0.1 | Вероятность read-repair при чтении |
| `comment` | `''` | Комментарий к таблице |

 Secondary indexes, Materialized Views, UDT — **[Обзор и моделирование данных](./overview.md)**. Cassandra 5.0: Storage Attached Indexes (SAI) — современная замена 2i. `CREATE ROLE`/`GRANT` — **[Безопасность](./security.md)**; `CREATE FUNCTION` (UDF) по умолчанию отключены (см. [Безопасность](./security.md#сетевая-защита-firewall)).

## DML: запись данных

```sql
-- Вставка данных (upsert: повторная вставка с тем же PK перезапишет строку)
INSERT INTO user_events (user_id, event_time, event_type, payload)
VALUES (550e8400-e29b-41d4-a716-446655440000, now(), 'login', '{"ip":"10.0.0.1"}')
USING TTL 86400;  -- автоудаление через 24 часа

-- USING TIMESTAMP — явный timestamp (микросекунды epoch) для упорядочивания записей
INSERT INTO user_events (user_id, event_time, event_type)
VALUES (550e8400-e29b-41d4-a716-446655440000, now(), 'login')
USING TIMESTAMP 1736899200000000;

-- Обновление (тоже upsert)
UPDATE user_events
SET payload = '{"ip":"10.0.0.2"}'
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
  AND event_time = 550e8400-e29b-41d4-a716-446655440000;

-- Удаление строки целиком
DELETE FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
  AND event_time = 550e8400-e29b-41d4-a716-446655440000;

-- Удаление отдельных колонок
DELETE payload, metadata FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
  AND event_time = 550e8400-e29b-41d4-a716-446655440000;

-- Условное удаление (LWT, Cassandra 4.0+)
DELETE FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
  AND event_time = 550e8400-e29b-41d4-a716-446655440000
IF EXISTS;
```

**Вставка из JSON** (Cassandra 2.2+, ScyllaDB 2.3+). Схема по-прежнему проверяется:

```sql
INSERT INTO user_events JSON '{
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "event_time": "550e8400-e29b-41d4-a716-446655440000",
    "event_type": "login"
}' DEFAULT UNSET;
```

`DEFAULT UNSET` — пропущенные колонки не трогаются; по умолчанию (или `DEFAULT NULL`) пропущенные колонки обнуляются (создаётся tombstone). Функции `fromJson()` / `toJson()` (ScyllaDB: `fromJson()` / `toJson()`) преобразуют JSON для одного значения.

**Функции текущего времени** (Cassandra 4.0+): `currentTimestamp()`, `currentDate()`, `currentTime()`, `currentTimeUUID()`.

### Counters (счётчики)

Counter — специальный тип колонки: 64-битный счётчик с операциями инкремента/декремента. Значение нельзя задать напрямую, только `+`/`-`:

```sql
CREATE TABLE page_views (
    page_id uuid,
    day date,
    views counter,
    PRIMARY KEY (page_id, day)
);

UPDATE page_views SET views = views + 1
WHERE page_id = 550e8400-e29b-41d4-a716-446655440000 AND day = '2026-01-15';
```

Ограничения counters:
- Колонка counter не может быть частью `PRIMARY KEY`.
- Таблица с counter может содержать только counter-колонки (все не-PK колонки — counter, или ни одной).
- TTL (`USING TTL`) и `USING TIMESTAMP` для counters не поддерживаются.
- Обновления **не идемпотентны**: при таймауте или обрыве соединения неизвестно, применился ли инкремент; повтор может дать двойной счёт.
- Удаление counter гарантированно работает только первый раз; не обновляйте удалённый counter.
- Для группировки counter-обновлений — `BEGIN COUNTER BATCH` (см. раздел BATCH).

## SELECT: чтение данных

```sql
-- Точечный запрос (самый быстрый: одна партиция)
SELECT * FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000;

-- Range-запрос по clustering column
-- для timeuuid используются minTimeuuid()/maxTimeuuid() (строка даты напрямую сравнивать нельзя)
SELECT event_type, payload FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
  AND event_time > minTimeuuid('2026-01-01 00:00:00+0000')
  AND event_time < maxTimeuuid('2026-01-31 23:59:59+0000');

-- Лимит результатов
SELECT * FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
LIMIT 100;

-- Лимит на партицию (Cassandra 4.0+, CASSANDRA-7017; ScyllaDB 3.1+)
SELECT * FROM user_events PER PARTITION LIMIT 10;

-- COUNT
SELECT COUNT(*) FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000;

-- Агрегации и GROUP BY (Cassandra 4.0+, CASSANDRA-10707; ScyllaDB 5.4+)
SELECT event_type, COUNT(*) as cnt
FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
GROUP BY event_type;

-- DISTINCT: только колонки partition key (и static) — Cassandra 2.2+ (CQL 3.4, CASSANDRA-4536)
SELECT DISTINCT user_id FROM user_events;

-- Псевдофункции: время записи и оставшийся TTL
SELECT event_type, writetime(payload), ttl(payload) FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000;

-- CAST и функции над коллекциями
SELECT CAST(event_time AS timestamp), map_keys(metadata) FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000;

-- Вывод строки как JSON
SELECT JSON * FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000;
```

Правила и ограничения `SELECT`:

- **`ORDER BY`** — только по clustering column, в порядке `CLUSTERING ORDER BY` (или обратном); сортировка по произвольной колонке невозможна.
- **`IN`** по partition key допустим, но для больших наборов — антипаттерн (координатор опрашивает много узлов); `IN` по clustering column — только для последней колонки ключа.
- **`ALLOW FILTERING`** — разрешает фильтрацию по не-ключевым колонкам без индекса: полный скан, непредсказуемая производительность. Только для разовых административных запросов, не для приложений:

  ```sql
  SELECT * FROM user_events WHERE event_type = 'login' ALLOW FILTERING;
  ```

- **`token()`** — диапазон по токену кольца; используется для параллельного сканирования всего кластера (Spark, миграции, аудит):

  ```sql
  SELECT * FROM user_events
  WHERE token(user_id) > token(550e8400-e29b-41d4-a716-446655440000)
    AND token(user_id) <= token(660e8400-e29b-41d4-a716-446655440000);
  ```

## BATCH: группировка операций

```sql
-- Атомарная запись в пределах одного partition (рекомендуется)
BEGIN BATCH
    INSERT INTO user_events (user_id, event_time, event_type)
    VALUES (550e8400-e29b-41d4-a716-446655440000, now(), 'purchase');
    INSERT INTO user_events (user_id, event_time, event_type)
    VALUES (550e8400-e29b-41d4-a716-446655440000, now(), 'notification');
APPLY BATCH;

-- Без batchlog: быстрее, но при сбое часть операций может не примениться
BEGIN UNLOGGED BATCH
    UPDATE user_events SET payload = '{"ip":"10.0.0.3"}'
    WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
      AND event_time = 550e8400-e29b-41d4-a716-446655440000;
APPLY BATCH;

-- Группировка counter-обновлений (только counter-операции, без кастомных timestamp)
BEGIN COUNTER BATCH
    UPDATE page_views SET views = views + 1 WHERE page_id = 550e8400-e29b-41d4-a716-446655440000 AND day = '2026-01-15';
    UPDATE page_views SET views = views + 125 WHERE page_id = 660e8400-e29b-41d4-a716-446655440000 AND day = '2026-01-15';
APPLY BATCH;
```

**Семантика BATCH:**
- Logged batch (по умолчанию) пишет batchlog на других узлах, чтобы все операции в итоге применились (или ни одна) — но изоляция только внутри одной партиции. Logged batch к одной партиции автоматически превращается в unlogged.
- `UNLOGGED` — без batchlog: быстрее, но при сбое batch может примениться частично.
- Batch может содержать только `INSERT`, `UPDATE`, `DELETE` (не вложенные batch).
- Если timestamp не задан явно, все операции получают один timestamp; при конфликте порядок применения может отличаться от порядка в batch — для гарантированного порядка задавайте `USING TIMESTAMP` на каждой операции.
- **Кросс-партиционные `BATCH` (для разных Partition Key) — антипаттерн.** Подробнее — **[Антипаттерны](./performance.md#антипаттерны-чего-нельзя-делать)**.

## Lightweight Transactions (LWT)

Cassandra/ScyllaDB поддерживают атомарные операции сравнения (`IF`) на основе Paxos:

```sql
-- Условная вставка (только если ключ ещё не существует)
INSERT INTO users (user_id, name, email)
VALUES (550e8400-e29b-41d4-a716-446655440000, 'Ivan', 'ivan@example.com')
IF NOT EXISTS;
-- → [applied]
-- → True

-- Условное обновление
UPDATE users SET name = 'Ivan Petrov'
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
IF name = 'Ivan';
-- → [applied] | name | email
-- → True     | Ivan | ivan@example.com
```

Таблица `users` для примеров: `CREATE TABLE users (user_id uuid PRIMARY KEY, name text, email text);`

**Особенности LWT:**
- Paxos добавляет 2 дополнительных round-trip (prepare + accept/learn), поэтому стоимость заметно выше обычной записи.
- Не масштабируются: при конкуренции за одну партицию возникают конфликты и таймауты.
- Используйте только для редких атомарных проверок, не для высокочастотных записей.
- Serial consistency (фаза Paxos) задаётся отдельно: `SERIAL CONSISTENCY LOCAL_SERIAL;`. Обычный `CONSISTENCY` определяет фазу «learn» (какие чтения гарантированно увидят результат); при `CONSISTENCY ANY` результат гарантированно видит только чтение с уровнем `SERIAL`.

## Уровни согласованности

```sql
-- Установка для текущей сессии (применяется ко всем последующим запросам)
CONSISTENCY LOCAL_QUORUM;

-- Просмотр текущего уровня
CONSISTENCY;
-- → Current consistency level is LOCAL_QUORUM.
```

Допустимые уровни: `ANY`, `ONE`, `TWO`, `THREE`, `QUORUM`, `ALL`, `LOCAL_QUORUM`, `LOCAL_ONE`, `SERIAL`, `LOCAL_SERIAL` (последние два — только для LWT).

**Важно:** в cqlsh уровень задаётся для сессии целиком, а не для отдельного запроса. Per-query consistency устанавливается через API драйвера (например, `session.execute(stmt, consistency_level=...)`).

Подробнее о уровнях согласованности — **[SRE-практики: Репликация и согласованность](./operations.md#уровни-согласованности-consistency-levels)**.

## Расширения ScyllaDB

ScyllaDB совместима с Cassandra по CQL и добавляет расширения:

```sql
-- Обход кэша (чтение напрямую из SSTables, для «холодных» данных)
SELECT * FROM user_events WHERE user_id = 550e8400-e29b-41d4-a716-446655440000 BYPASS CACHE;

-- Таймаут конкретного запроса (переопределяет клиентский таймаут)
SELECT * FROM user_events WHERE user_id = 550e8400-e29b-41d4-a716-446655440000 USING TIMEOUT 500ms;
```

- `PER PARTITION LIMIT` — с ScyllaDB 3.1 (в Cassandra — с 4.0).
- `GROUP BY` — с ScyllaDB 5.4 (в Cassandra — с 4.0). Замечание: в ScyllaDB 5.4.0 был регресс `SELECT *` + `GROUP BY` (возвращались все строки вместо первой в группе), исправленный в 5.4.1; используйте 5.4.1+.
- JSON-функции в ScyllaDB называются `fromJson()` / `toJson()` (camelCase).

## Поиск и устранение неисправностей

| Ошибка | Причина | Решение |
|---|---|---|
| `SyntaxException: ... no viable alternative at input` | Синтаксическая ошибка: пропущена точка с запятой, неверное ключевое слово, опечатка | Проверить statement; `HELP <topic>` для команд cqlsh |
| `InvalidRequest: ... may have unpredictable performance ... use ALLOW FILTERING` | Фильтр по колонке вне первичного ключа без индекса | Добавить secondary index/SAI (overview.md) или пересмотреть модель данных |
| `UnavailableException: Cannot achieve consistency level ...` | Недостаточно живых реплик для выбранного уровня | `nodetool status` (operations.md); снизить уровень или поднять кластер |
| `ReadTimeout` / `WriteTimeout` | Координатор не дождался ответа реплик в срок | Проверить latency и нагрузку (monitoring.md); проверить GC/compaction |
| `OperationTimedOut` (cqlsh) | Запрос не завершился за `--request-timeout` (10 с по умолчанию) | `cqlsh --request-timeout 60`; затем разобраться с причиной медленного запроса |
| `Invalid UUID string: '2026-01-15 10:30:00+0000'` | Сравнение колонки `timeuuid` со строкой даты | UUID-литерал или `minTimeuuid()` / `maxTimeuuid()` |
| `InvalidRequest: unconfigured table ...` / `Keyspace ... does not exist` | Не выполнена `USE` или объект не создан | `DESCRIBE KEYSPACES` / `DESCRIBE TABLES` |
| `Connection refused` | Узел недоступен, порт 9042 закрыт | `nodetool status`, firewall (security.md) |
| `Unable to authenticate` | Неверные учётные данные; `PasswordAuthenticator` не включён на всех узлах | См. [Безопасность](./security.md#поиск-и-устранение-неисправностей) |
| Таймауты/`ServerError` на LWT | Конкуренция за одну партицию в условных операциях | Уменьшить частоту LWT; разнести горячие ключи |

## Рекомендации

- Всегда указывать полный partition key в `WHERE` и добавлять `LIMIT`.
- Держать `PAGING ON` в интерактивной сессии, чтобы не выгружать огромные результаты разом.
- `TRACING ON` для диагностики медленных запросов (данные — в `system_traces`, 24 часа).
- `DESCRIBE SCHEMA` — выгрузка DDL всей схемы для клонирования кластера или бэкапа схемы.
- `COPY TO` / `COPY FROM` — импорт/экспорт CSV для небольших объёмов; для bulk-загрузки — `sstableloader` (operations.md).
- BATCH — только в пределах одной партиции; `UNLOGGED` — когда атомарность не требуется.
- LWT — только для редких условных проверок; `IF NOT EXISTS` — для идемпотентной вставки (с учётом стоимости Paxos).
- Counters — в отдельной таблице, без TTL; повторы после сбоя могут дать двойной счёт.
- TTL — на уровне таблицы (`default_time_to_live`) или запроса (`USING TTL`).
- Перед сменой RF — `ALTER KEYSPACE`, затем repair (operations.md).

## См. также
- **[Обзор и моделирование данных](./overview.md)** — определения, Primary Key, типы данных, индексы, MV, UDT.
- **[Обслуживание и эксплуатация](./operations.md)** — Compaction, Repair, gc_grace_seconds, consistency levels.
- **[Тюнинг производительности](./performance.md)** — антипаттерны, Tombstones.
- **[Безопасность](./security.md)** — аутентификация, RBAC, TLS для cqlsh.
- **[Установка и настройка](./installation.md)** — запуск кластера и первое подключение cqlsh.
