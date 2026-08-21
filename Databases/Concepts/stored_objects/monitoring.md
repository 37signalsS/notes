# Мониторинг хранимых объектов

## PostgreSQL

### pg_stat_user_functions

Системное представление `pg_stat_user_functions`收集 выполнения функций, но **не процедур** (процедуры PostgreSQL не отслеживаются в этом представлении).

```sql
-- Статистика выполнения функций
SELECT
    schemaname,
    funcname,
    calls,
    total_time,
    self_time,
    ROUND(total_time / calls, 3) AS avg_time_ms
FROM pg_stat_user_functions
ORDER BY total_time DESC;
-- → schemaname | funcname          | calls | total_time | self_time | avg_time_ms
-- → -----------+-------------------+-------+------------+-----------+------------
-- → public     | audit_changes     | 15234 | 4523.12    | 4523.12   | 0.297
-- → public     | calculate_tax     | 8901  | 1234.56    | 1234.56   | 0.139
```

**Разница `total_time` vs `self_time`:**
- `total_time` — общее время выполнения (включая вызовы других функций).
- `self_time` — время, затраченное непосредственно на код функции (без учёта вложенных вызовов).
- Если `self_time` значительно меньше `total_time` — функция тратит время на вызов других функций (контекстное переключение).

### Настройка сбора статистики

```sql
-- Проверка текущего значения
SHOW track_functions;
-- → track_functions
-- → ----------------
-- → none             -- статистика не собирается (по умолчанию)

-- Включение сбора
ALTER SYSTEM SET track_functions = 'all';  -- 'none', 'pl', 'all'
SELECT pg_reload_conf();

-- 'pl'  — только PL/pgSQL и другие procedural languages
-- 'all' — все функции, включая SQL-функции
```

**Примечание:** `track_functions` не отслеживает хранимые процедуры (`PROCEDURE`). Для мониторинга процедур используйте `pg_stat_statements`.

### pg_stat_statements

Расширение `pg_stat_statements` отслеживает **все** SQL-выполнения, включая вызовы процедур через `CALL`.

```sql
-- Установка
CREATE EXTENSION pg_stat_statements;

-- Топ-10 самых частых/долгих запросов (включая CALL)
SELECT
    calls,
    ROUND(total_exec_time::numeric, 2) AS total_ms,
    ROUND(mean_exec_time::numeric, 2) AS avg_ms,
    LEFT(query, 80) AS query_preview
FROM pg_stat_statements
WHERE query LIKE 'CALL %' OR query LIKE '%update_order%'
ORDER BY total_exec_time DESC
LIMIT 10;
```

### Отладка выполнения

Подробнее см. [Отладка объектов в PostgreSQL](../../PostgreSQL/Concepts/stored_objects_debugging.md).

---

## MariaDB/MySQL

### Performance Schema

MariaDB/MySQL собирают статистику через `performance_schema`. Ключевые таблицы:

| Таблица | Назначение |
|---|---|
| `events_statements_summary_by_program` | Агрегированная статистика по программам (процедуры, функции, триггеры, события) |
| `events_statements_summary_by_digest` | Статистика по unique SQL-паттернам (включая SQL внутри хранимых объектов) |
| `threads` | Активные сессии и выполняемые в данный момент программы |
| `metadata_locks` | Блокировки метаданных (DDL внутри хранимых объектов) |

### Включение сбора статистики

```sql
-- Проверка: включён ли сбор для programs
SELECT * FROM performance_schema.setup_consumers
WHERE NAME = 'events_statements_summary_by_program';
-- → NAME                                    | ENABLED
-- → ----------------------------------------+--------
-- → events_statements_summary_by_program     | NO     -- по умолчанию может быть выключен

-- Включение
UPDATE performance_schema.setup_consumers
SET ENABLED = 'YES'
WHERE NAME = 'events_statements_summary_by_program';
```

### Топ-хранимых объектов по времени выполнения

```sql
SELECT
    SCHEMA_NAME,
    ROUTINE_NAME,
    ROUTINE_TYPE,
    EXECUTION_COUNT,
    ROUND(SUM_TIMER_WAIT / 1e12, 3) AS total_time_sec,
    COUNT_TIMER_WAIT AS call_count
FROM performance_schema.events_statements_summary_by_program
JOIN information_schema.ROUTINES USING (ROUTINE_NAME)
WHERE SCHEMA_NAME = 'mydb'
ORDER BY SUM_TIMER_WAIT DESC;
-- → SCHEMA_NAME | ROUTINE_NAME       | ROUTINE_TYPE | total_time_sec | call_count
-- → ------------+--------------------+--------------+----------------+-----------
-- → mydb        | archive_old_orders | PROCEDURE    | 12.345         | 89
-- → mydb        | calculate_age      | FUNCTION     |  0.234         | 1523
```

### Медленные SQL-запросы внутри хранимых объектов

```sql
-- Запросы, выполняемые внутри хранимых объектов, сортированные по времени
SELECT
    SCHEMA_NAME,
    DIGEST_TEXT,
    COUNT_STAR AS exec_count,
    ROUND(SUM_TIMER_WAIT / 1e12, 3) AS total_sec,
    ROUND(AVG_TIMER_WAIT / 1e12, 6) AS avg_sec
FROM performance_schema.events_statements_summary_by_digest
WHERE SCHEMA_NAME = 'mydb'
  AND DIGEST_TEXT LIKE '%orders%'
ORDER BY SUM_TIMER_WAIT DESC
LIMIT 10;
```

### Активные программы в данный момент

```sql
SELECT
    t.THREAD_ID,
    t.PROCESSLIST_ID AS pid,
    t.PROCESSLIST_USER AS user,
    t.PROCESSLIST_HOST AS host,
    t.PROCESSLIST_DB AS db,
    t.PROCESSLIST_STATE AS state,
    t.PROCESSLIST_TIME AS time_sec
FROM performance_schema.threads t
WHERE t.TYPE = 'FOREGROUND'
  AND t.PROCESSLIST_STATE LIKE '%executing%';
```

---

## Рекомендации

1. **Алерты:** Настраивайте алерты на аномальное среднее время выполнения хранимых объектов.
2. **Базeline:** Собирайте статистику минимум 7 дней до настройки алертов — это позволит определить нормальные диапазоны.
3. **pg_stat_statements (PostgreSQL):** Включайте в production — это расширение критически важно для анализа производительности.
4. **Performance Schema (MariaDB):** Включайте `events_statements_summary_by_program` и `events_statements_summary_by_digest` в production.
