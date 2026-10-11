**Актуально для:** PostgreSQL 16–18 / Oracle 26ai / SQL Server 2022 / ClickHouse 24.x / Cassandra 5.x (2024–2026)

# Материализованные представления (Materialized Views)

**Предварительные требования:** владелец MV или привилегия `MAINTAIN` (PG 17+) на MV для `REFRESH`; для `REFRESH CONCURRENTLY` — уникальный индекс на MV; `pg_cron` (расширение) или системный cron для расписания.

## Определения

**Materialized View (MV, материализованное представление)** — объект БД, хранящий результат запроса физически (на диске), в отличие от обычного представления (view), которое перевычисляет запрос при каждом обращении.

**Refresh (обновление)** — перевычисление и перезапись хранимого результата MV. Стратегии: по требованию (`REFRESH`), по расписанию, инкрементально (fast refresh) или полностью (complete refresh).

**Staleness (устаревание)** — расхождение данных MV с базовыми таблицами. MV — всегда «снимок на момент refresh»; свежесть определяется частотой refresh.

**Query rewrite (переписывание запроса)** — оптимизатор автоматически подменяет обращение к базовым таблицам на обращение к MV, если это эквивалентно и выгодно (Oracle, SQL Server). PostgreSQL query rewrite — нет (нужно явное обращение к MV).

**Indexed View (SQL Server)** — представление с уникальным кластерным индексом = материализованное представление в SQL Server; поддерживает автоматическое обслуживание при DML на базовых таблицах.

**POPULATE (ClickHouse)** — при создании MV заполнение из текущих данных базовой таблицы; без `POPULATE` — только новые данные.

## Основные концепции

### MV vs View vs Table

| Свойство | View | Materialized View | Table |
| :--- | :--- | :--- | :--- |
| **Хранение данных** | нет (только определение) | да (физически) | да |
| **Свежесть** | всегда свежие | на момент refresh | всегда свежие |
| **Стоимость чтения** | перевычисление запроса | чтение готового результата | чтение |
| **Стоимость записи** | — | refresh (полный или инкрементальный) | DML напрямую |
| **Индексы** | нет | да (PostgreSQL, Oracle) | да |

### Когда MV оправдан

1. **Дорогие агрегаты** для дашбордов: `GROUP BY` по миллионам строк → предвычисление раз в минуту.
2. **Сложные JOIN** для read-only отчётов (denormalized read model).
3. **Репликация подмножества данных** (фильтр по tenant, региону).
4. **Кэш на уровне БД** для запросов, которые нельзя ускорить индексом.

### Когда MV не подходит

- Нужна актуальность «на секунду» — используйте обычные таблицы/индексы или триггеры.
- Базовые таблицы обновляются чаще, чем имеет смысл делать refresh (refresh дороже, чем прямой запрос).
- MySQL/MariaDB/SQLite: нативных MV нет — см. обходные пути ниже.

### Поддержка по СУБД

| СУБД | Нативные MV | Механизм |
| :--- | :--- | :--- |
| **PostgreSQL** | да (с 9.3; `CONCURRENTLY` — с 9.5) | `CREATE MATERIALIZED VIEW`; `REFRESH MATERIALIZED VIEW [CONCURRENTLY]` (нужен уникальный индекс); query rewrite — нет |
| **Oracle** | да | `CREATE MATERIALIZED VIEW`; fast refresh (инкрементальный через materialized view logs); query rewrite — да |
| **SQL Server** | да (Indexed Views) | уникальный кластерный индекс на view; автообновление при DML; требует `SCHEMABINDING`; автоматический query rewrite — только в Enterprise/Developer, в других редакциях — хинт `WITH (NOEXPAND)` |
| **ClickHouse** | да | MV на базе `MergeTree`-таблиц; `POPULATE`; целевая таблица задаётся явно; обновление — при вставке в источник; также Refreshable MV с расписанием (`REFRESH ... EVERY`) — **[Производительность](../ClickHouse/clickhouse-performance.md)** |
| **Cassandra** | да | `CREATE MATERIALIZED VIEW`; **не рекомендуется в production** (дополнительная запись на каждый mutation, риски производительности) |
| **MySQL** | нет (community) | только MySQL HeatWave (analytics engine, с 9.5); в InnoDB — обходные пути |
| **MariaDB** | нет | обходные пути (см. ниже) |
| **SQLite** | нет | обходные пути |

**Обходные пути для MySQL/MariaDB/SQLite:**
1. **Таблица + событие/крон:** создать таблицу-витрину и периодически `TRUNCATE` + `INSERT INTO ... SELECT` (или `INSERT ... ON DUPLICATE KEY UPDATE` для инкремента).
2. **Триггеры** на базовых таблицах для поддержания витрины (дорого при высокой записи).
3. **FlexViews** (MySQL) — инструмент на binlog для инкрементального refresh.
4. **Слой приложения/CDC:** поддержание витрины через поток изменений (**[CDC](./cdc_architectural_patterns.md)**).

## Практические сценарии

### Сценарий 1: PostgreSQL — дашборд продаж

```sql
-- Создание
CREATE MATERIALIZED VIEW sales_daily AS
SELECT date_trunc('day', created_at) AS day,
       product_id,
       count(*) AS orders,
       sum(amount_cents) AS revenue
FROM orders
GROUP BY 1, 2;

-- Уникальный индекс обязателен для CONCURRENTLY
CREATE UNIQUE INDEX idx_sales_daily ON sales_daily (day, product_id);

-- Полное обновление (блокирует чтение MV на время refresh)
REFRESH MATERIALIZED VIEW sales_daily;

-- Параллельное обновление (чтение не блокируется)
REFRESH MATERIALIZED VIEW CONCURRENTLY sales_daily;

-- Обращение — как к обычной таблице
SELECT * FROM sales_daily WHERE day > '2026-09-01';
```

**Важные ограничения `REFRESH` (PostgreSQL):**
- Обычный `REFRESH` берёт `ACCESS EXCLUSIVE` (блокирует и чтение); `CONCURRENTLY` — `EXCLUSIVE` (чтение идёт параллельно).
- `CONCURRENTLY` требует уникальный индекс **только на колонках, без выражений и без `WHERE`**; MV должен быть populated (`WITH NO DATA` нельзя сочетать с `CONCURRENTLY`); одновременно может идти только один refresh одного MV.
- Быстрое развёртывание: `CREATE MATERIALIZED VIEW ... WITH NO DATA` — MV создаётся незаполненным (`ispopulated = false`, `SELECT` с него ошибка), заполняется первым полным `REFRESH`.

**Валидация:**
```sql
-- Заполнен ли MV, есть ли индексы
SELECT ispopulated, hasindexes FROM pg_matviews WHERE matviewname = 'sales_daily';
```

**Расписание (pg_cron):**
```sql
SELECT cron.schedule('sales_daily', '*/5 * * * *',
    $$REFRESH MATERIALIZED VIEW CONCURRENTLY sales_daily$$);

-- Отключение расписания (cleanup)
SELECT cron.unschedule('sales_daily');

-- Удаление MV (cleanup)
DROP MATERIALIZED VIEW IF EXISTS sales_daily;
```

### Сценарий 2: ClickHouse — MV как трансформация при вставке

```sql
-- Целевая таблица агрегатов
CREATE TABLE analytics.orders_daily (
    day Date, store_id UInt32, amount UInt64
) ENGINE = SummingMergeTree ORDER BY (day, store_id);

-- MV: пересчёт при каждой вставке в raw.orders
CREATE MATERIALIZED VIEW orders_mv TO analytics.orders_daily AS
SELECT toDate(event_time) AS day,
       JSONExtractUInt(data, 'store_id') AS store_id,
       JSONExtractUInt(data, 'amount') AS amount
FROM raw.orders;

-- С заполнением из существующих данных (POPULATE)
CREATE MATERIALIZED VIEW orders_mv TO analytics.orders_daily
POPULATE AS
SELECT ... FROM raw.orders;
-- Внимание: данные, вставленные в raw.orders в момент создания MV,
-- могут не попасть в целевую таблицу — после POPULATE сверьте счётчики
```

### Сценарий 3: MySQL — витрина через таблицу + событие

```sql
-- Витрина как обычная таблица
CREATE TABLE sales_daily (
    day DATE, product_id BIGINT,
    orders BIGINT, revenue BIGINT,
    PRIMARY KEY (day, product_id)
) ENGINE = InnoDB;

-- Инкрементальное обновление по watermark
-- ВАЖНО: схема корректна только для append-only данных (новые заказы).
-- Для UPDATE существующих строк (смена суммы) нужна инкрементальника по старым
-- значениям: FlexViews/binlog или CDC, либо полный пересчёт затронутых пар (day, product_id).
CREATE TABLE refresh_watermark (name VARCHAR(64) PRIMARY KEY, refreshed_at TIMESTAMP);
DELIMITER ;;
CREATE EVENT refresh_sales_daily
ON SCHEDULE EVERY 5 MINUTE
DO
BEGIN
    INSERT INTO sales_daily (day, product_id, orders, revenue)
    SELECT DATE(created_at), product_id, count(*), sum(amount_cents)
    FROM orders
    WHERE created_at > (SELECT COALESCE(max(refreshed_at), '1970-01-01')
                        FROM refresh_watermark WHERE name='sales_daily')
    GROUP BY 1, 2
    ON DUPLICATE KEY UPDATE
        orders = orders + VALUES(orders),
        revenue = revenue + VALUES(revenue);

    UPDATE refresh_watermark SET refreshed_at = now() WHERE name='sales_daily';
END;;
DELIMITER ;
SET GLOBAL event_scheduler = ON;  -- требует SUPER/persist-привилегии
```

### Сценарий 4: Oracle — fast refresh через MV logs

```sql
-- Лог изменений на базовой таблице
CREATE MATERIALIZED VIEW LOG ON orders WITH ROWID, SEQUENCE
    (created_at, product_id, amount_cents) INCLUDING NEW VALUES;

-- MV с быстрым refresh
-- Для fast refresh агрегатов обязательно: COUNT(*) + COUNT(aggr_col) на каждый SUM/AVG,
-- иначе fast refresh возможен только после INSERT
CREATE MATERIALIZED VIEW sales_daily
BUILD IMMEDIATE REFRESH FAST ON DEMAND
AS SELECT created_at, product_id,
        count(*) AS cnt, count(amount_cents) AS cnt_amount,
        sum(amount_cents) FROM orders GROUP BY 1, 2;

-- Инкрементальный refresh (только изменения с последнего refresh)
EXEC DBMS_MVIEW.REFRESH('sales_daily', method => 'F');
```

## Операции и команды

### Мониторинг MV

```sql
-- PostgreSQL: инвентарь MV (размер, заполнен, есть индексы)
SELECT schemaname, matviewname, ispopulated, hasindexes,
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||matviewname))
FROM pg_matviews;

-- PostgreSQL НЕ хранит время последнего refresh (в pg_matviews нет столбца last_refresh).
-- Паттерн SRE: таблица аудита, обновляемая в той же транзакции, что и refresh
CREATE TABLE mv_refresh_audit (
    matviewname text PRIMARY KEY,
    refreshed_at timestamptz NOT NULL,
    duration_ms integer
);
BEGIN;
REFRESH MATERIALIZED VIEW CONCURRENTLY sales_daily;
INSERT INTO mv_refresh_audit VALUES ('sales_daily', now(), 4200)
  ON CONFLICT (matviewname) DO UPDATE
  SET refreshed_at = now(), duration_ms = EXCLUDED.duration_ms;
COMMIT;

-- Алерт на устаревание
SELECT matviewname, now() - refreshed_at AS staleness
FROM mv_refresh_audit WHERE now() - refreshed_at > interval '10 minutes';
```

```sql
-- Oracle: свежесть MV
SELECT mview_name, staleness, last_refresh_type, last_refresh_date
FROM user_mviews;
```

### Обслуживание

```sql
-- PostgreSQL: переиндексация MV после большого refresh
REINDEX MATERIALIZED VIEW sales_daily;

-- Анализ плана: используется ли MV (PostgreSQL — только при явном обращении)
EXPLAIN SELECT * FROM sales_daily WHERE day > '2026-09-01';
```

## Поиск и устранение неисправностей

### Проблема: данные MV устарели

**Симптомы:** дашборд показывает суммы, не совпадающие с `SELECT` по базовым таблицам.

**Причина:** refresh не запускался, упал cron/pg_cron, или refresh был прерван.

**Решение:**
1. Мониторинг: алерт на `now() - refreshed_at > порог` по таблице аудита (`mv_refresh_audit`, см. Мониторинг).
2. `REFRESH MATERIALIZED VIEW CONCURRENTLY` в транзакции — атомарность.
3. Для критичной свежести — триггерная поддержка или CDC-конвейер.

### Проблема: `REFRESH` блокирует чтение

**Симптомы:** дашборды «зависают» на время refresh.

**Причина:** обычный `REFRESH MATERIALIZED VIEW` берёт `ACCESS EXCLUSIVE` (блокирует и чтение, и DML). `REFRESH ... CONCURRENTLY` берёт `EXCLUSIVE` — чтение (`SELECT`) идёт параллельно, DML на MV блокируется.

**Решение:** `REFRESH MATERIALIZED VIEW CONCURRENTLY` (PostgreSQL 9.5+). Требования: уникальный индекс только на колонках (не expression index, без `WHERE`), MV должен быть populated, одновременно только один refresh на MV. Цена: медленнее полного refresh при большом объёме изменений.

### Проблема: MV не используется оптимизатором

**Симптомы:** запрос к базовым таблицам медленный, хотя MV с тем же результатом существует.

**Причина:** PostgreSQL не делает автоматический query rewrite — нужно обращаться к MV явно. Oracle/SQL Server делают rewrite, но только при совместимости (агрегаты, JOIN-условия).

**Решение:**
1. PostgreSQL: переписать запрос на обращение к MV (или обернуть в view с тем же именем).
2. Oracle: `DBMS_MVIEW.EXPLAIN_REWRITE` — почему rewrite не применён.

### Проблема: MV не заполнен (`WITH NO DATA`)

**Симптомы:** `ERROR: materialized view "sales_daily" has not been populated` (HINT: Use the REFRESH MATERIALIZED VIEW command) при `SELECT` из MV; `ERROR: CONCURRENTLY cannot be used when the materialized view is not populated` при `REFRESH ... CONCURRENTLY`.

**Причина:** MV создан (или refreshed) с `WITH NO DATA`; `ispopulated = false` (`pg_class.relispopulated`).

**Решение:** полный `REFRESH MATERIALIZED VIEW sales_daily;` (без `CONCURRENTLY` и без `WITH NO DATA`). Проверка: `SELECT ispopulated FROM pg_matviews WHERE matviewname = 'sales_daily';`

### Проблема: MV не реплицируется на standby/реплику

**Симптомы:** на реплике MV пустой или устаревший, хотя primary свежий.

**Причина:** materialized views не входят в публикации логической репликации; физическая репликация копирует содержимое, но refresh на реплике не запускается автоматически.

**Решение:** запускать `REFRESH` на каждой реплике по расписанию (свой pg_cron/cron на реплике) либо читать MV только с primary.

### Проблема: раздутие MV

**Симптомы:** размер MV растёт быстрее, чем данных.

**Причина:** частые full refresh без `VACUUM`/`REINDEX`; dead tuples.

**Решение:** `ANALYZE sales_daily;` после refresh (`REFRESH` не обновляет статистику оптимизатора); `VACUUM`/`REINDEX` периодически (autovacuum обрабатывает MV как обычную таблицу).

### Проблема: Cassandra MV тормозит запись

**Симптомы:** latency записи выросла после создания MV.

**Причина:** каждый mutation обновляет и MV (дополнительная запись + консенсус).

**Решение:** удалить MV; поддерживать витрину в приложении или через CDC (Spark/Flink).

### Проблема: MV на MySQL HeatWave не обновляется

**Симптомы:** данные MV не соответствуют таблицам после DML.

**Причина:** HeatWave MV рематериализуется при запросе, если базовые таблицы изменились; прямые DML на MV невозможны.

**Решение:** проверить, что таблица загружена в HeatWave; DML — только на базовые таблицы.

## Лучшие практики

1. **MV — кэш, а не источник правды.** Всегда известна свежесть и способ refresh.
2. **`CONCURRENTLY` для read-нагруженных MV** (PostgreSQL) + уникальный индекс.
3. **Мониторинг свежести:** алерт на устаревание, а не только на ошибки refresh.
4. **Индексы на MV** под запросы дашбордов — как на обычные таблицы.
5. **Не MV для высокочастотных изменений:** если refresh чаще, чем раз в минуту — пересмотрите дизайн (триггеры, CDC, денормализация в таблице).
6. **Cassandra MV — не в production**; используйте приложение или CDC.
7. **Документируйте зависимости:** MV зависит от базовых таблиц; миграции, меняющие их, должны обновлять MV (**[Миграции: основы](./migrations/migration_basics.md)**).
8. **Cleanup:** `DROP MATERIALIZED VIEW` освобождает место и индексы; отменяйте расписание (`cron.unschedule`) до удаления MV.
9. **TimescaleDB:** для time-series используйте continuous aggregates (`WITH (timescaledb.continuous)` + `add_continuous_aggregate_policy`) — инкрементальный refresh вместо полного (**[TimescaleDB](../timescaledb.md)**).

## Дополнительная информация

### Смежные темы
- **[Stored objects: обзор](./stored_objects_overview.md)** — views, процедуры, триггеры.
- **[CDC-архитектуры](./cdc_architectural_patterns.md)** — поддержание витрин через потоки изменений.
- **[Индексы](./indexes.md)** — индексы на MV.
- **[Партиционирование](./partitioning.md)** — партиционированные витрины.
- **[Моделирование DWH](./dwh_modeling.md)** — MV как агрегатные таблицы.
- **[PostgreSQL: архитектура](../PostgreSQL/Concepts/architecture.md)** — MV в контексте PostgreSQL.
- **[PostgreSQL: блокировки](../PostgreSQL/Concepts/concurrency_and_locking.md)** — уровни блокировок `REFRESH`.
- **[TimescaleDB](../timescaledb.md)** — continuous aggregates как MV с инкрементальным refresh.
- **[ClickHouse](../ClickHouse/clickhouse.md)** — MV как движок трансформации.
- **[Benchmarking](./benchmarking.md)** — замер выигрыша от MV.
