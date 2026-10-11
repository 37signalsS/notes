# Мониторинг хранимых объектов

**Актуально для:** PostgreSQL 17/18, MariaDB 10.11/11.4, MySQL 8.4 LTS

## Определения

**`pg_stat_user_functions`** — системное представление PostgreSQL, содержащее статистику выполнения пользовательских функций (количество вызовов, общее и среднее время).

**`pg_stat_statements`** — расширение PostgreSQL, отслеживающее все SQL-выполнения на уровне уникальных запросов, включая вызовы процедур через `CALL`.

**`track_functions`** — параметр `postgresql.conf`, определяющий уровень сбора статистики по функциям (`none`, `pl`, `all`).

**Performance Schema** — подсистема MariaDB/MySQL для инструментирования внутренних событий СУБД. Отслеживает потребление памяти, блокировки, I/O, соединения и SQL-запросы на уровне программ.

**`events_statements_summary_by_program`** — таблица Performance Schema, агрегирующая статистику по хранимым программам (процедуры, функции, триггеры, события).

**`events_statements_summary_by_digest`** — таблица Performance Schema, агрегирующая статистику по уникальным SQL-паттернам, включая SQL внутри хранимых объектов.

---

## Базовые концепции

### Почему мониторинг хранимых объектов отличается от обычного SQL

Хранимые объекты (процедуры, функции, триггеры, события) выполняются **внутри процесса СУБД**, а не на уровне приложения. Это создаёт специфические сложности для мониторинга:

1. **Невидимость для внешних профайлеров:** Инструменты приложения (APM, Application Performance Monitoring) не видят время, затраченное внутри хранимого объекта, так как вызов `CALL` выглядит как один SQL-оператор.
2. **Каскадный эффект:** Долгие триггеры замедляют все операции `INSERT`/`UPDATE`/`DELETE` на таблице, а не только вызовы процедуры. Проблема маскируется под "общую медленную запись".
3. **Потребление ресурсов БД:** Вычисления внутри хранимых объектов потребляют CPU и RAM сервера базы данных, который сложнее масштабировать горизонтально, чем уровень приложения.
4. **Сложность отладки:** Для диагностики нужны инструменты именно СУБД, так как логика недоступна для step-through отладки на уровне приложения.

### Методология сбора метрик

**PostgreSQL:**
- `track_functions` + `pg_stat_user_functions` — статистика по пользовательским функциям (не процедурам).
- `pg_stat_statements` — расширение, отслеживающее все SQL-выполнения, включая `CALL` процедур.
- `pg_stat_activity` — активные сессии и выполняемые в данный момент запросы.

**MariaDB/MySQL:**
- Performance Schema — подсистема инструментирования, требующая явного включения коллекторов.
- `sys` Schema — набор удобных агрегированных представлений над Performance Schema.
- Slow Query Log — лог запросов, превышающих порог `long_query_time`.

### Применение USE-методологии к хранимым объектам

Для диагностики проблем с хранимыми объектами используйте методологию **USE** (Utilization, Saturation, Errors) для ресурсов СУБД:

| Ресурс | Утилизация (Utilization) | Насыщение (Saturation) | Ошибки (Errors) |
| :--- | :--- | :--- | :--- |
| **CPU** | Загрузка ядер СУБД | Длина очереди CPU | Context switching |
| **RAM** | Потребление процессом СУБД | Swap usage, OOM | ECC errors |
| **Disk I/O** | `%util` дисков | Длина очереди I/O (`avgqu-sz`) | Тайм-ауты, битые блоки |
| **Соединения** | `Threads_connected` / `max_connections` | Очередь ожидания соединений | `Aborted_connects` |

### Базовый принцип: Baseline перед алертингом

Собирайте статистику минимум **7 дней** до настройки алертов. Это позволяет определить нормальные диапазоны (baseline) для:
- Среднего времени выполнения процедур (`avg_time_ms`).
- Количества вызовов в час/день.
- Пиковых значений при типичной нагрузке.

Алерты, настроенные без baseline, генерируют шум (false positives) и игнорируются SRE.

---

## Практические сценарии

### PostgreSQL: pg_stat_user_functions

Системное представление `pg_stat_user_functions` собирает статистику выполнения функций, но **не процедур** (процедуры PostgreSQL не отслеживаются в этом представлении).

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

### PostgreSQL: pg_stat_statements

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

**Валидация:** После создания расширения проверьте, что метрики собираются:

```sql
-- Проверка работы расширения
SELECT count(*) AS tracked_queries
FROM pg_stat_statements;
-- → tracked_queries > 0
```

### MariaDB/MySQL: Performance Schema

Performance Schema собирает статистику через системные таблицы. Ключевые таблицы для мониторинга хранимых объектов:

| Таблица | Назначение |
| :--- | :--- |
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

### Наблюдаемость запланированных заданий

Статистика вызовов показывает, что происходит с объектом, когда он вызывается. Но для заданий по расписанию нужен отдельный слой наблюдения: нужно знать не «сколько раз вызвали», а «выполнялось ли задание вообще и с каким результатом».

**PostgreSQL (`pg_cron`):**

```sql
-- Текущее состояние заданий: расписание, активность
SELECT jobid, schedule, command, database, username, active
FROM cron.job
WHERE active
ORDER BY jobid;
-- → jobid | schedule  | command                      | database | username | active
-- →    1 | '5 * * * *'| SELECT app.rebuild_stats();  | mydb     | app      | t

-- Последние запуски: статус и сообщение об ошибке
SELECT jobid, runid, status, return_message,
       start_time, end_time,
       round(extract(epoch FROM (end_time - start_time))::numeric, 3) AS duration_sec
FROM cron.job_run_details
ORDER BY start_time DESC
LIMIT 10;
-- → jobid | runid | status   | return_message | start_time           | duration_sec
-- →    1 |    42 | failed   | ERROR: deadlock detected | 2026-10-04 05:00:01 |      0.842
```

Ключевая алертинговая метрика — **`status = 'failed'` с привязкой к `jobid`**, а не агрегаты времени: сломанное задание часто выполняется быстро и не даёт нагрузки, поэтому метрики производительности его не поймают. Полезна также метрика «последний успешный запуск»: для задания с часовым расписанием `last_success` старше двух периодов означает, что задание перестало выполняться, даже не падая.

Разбор самой таблицы и её колонок — в [Автоматизация обслуживания](../../PostgreSQL/Operations/maintenance_automation.md); здесь важно два эксплуатационных свойства:

- записи **не очищаются автоматически**, поэтому нужен собственный retention: удаляйте строки старше заданного окна отдельной задачей, иначе таблица растёт неограниченно;
- на `cron.job` включён RLS с политикой `username = current_user` — пользователь видит только свои задания, поэтому сбор метрик выполняйте от привилегированной роли, иначе результат будет неполным.

**MariaDB/MySQL (Event Scheduler):**

```sql
-- Состояние событий: важно отличать ENABLED от REPLICA_SIDE_DISABLED
-- (на старых версиях MySQL — SLAVESIDE_DISABLED)
SELECT EVENT_SCHEMA, EVENT_NAME, STATUS,
       INTERVAL_VALUE, INTERVAL_FIELD, LAST_EXECUTED
FROM information_schema.EVENTS
ORDER BY EVENT_SCHEMA, EVENT_NAME;
-- → mydb | nightly_purge | ENABLED            | 1 | DAY | 2026-10-04 03:00:00
-- → mydb | legacy_report  | REPLICA_SIDE_DISABLED | 1 | DAY | NULL

-- Глобальный переключатель планировщика
SHOW VARIABLES LIKE 'event_scheduler';
-- → Variable_name | Value
-- → event_scheduler | ON
```

Здесь `LAST_EXECUTED` фиксирует момент **старта** последнего выполнения, а не завершения, поэтому свежее значение при долгой задаче не означает успеха; `NULL` означает, что событие ни разу не выполнялось. Значение `event_scheduler` проверяйте явно: `OFF` управляется через `SET GLOBAL`, а `DISABLED` задаётся только при старте сервера и не меняется во время работы — события при этом выглядят как `ENABLED`, но не выполняются.

События в статусе `REPLICA_SIDE_DISABLED` (на старых инсталляциях — `SLAVESIDE_DISABLED`) требуют отдельного внимания при переключении реплики: они пришли с источника репликации и здесь не выполняются, а после promotion требуют ручного `ALTER EVENT ... ENABLE` (см. [Управление изменениями](change_management.md)).

---

## Валидация и baseline

### Проверка корректности сбора статистики

**PostgreSQL:**

```sql
-- Проверка: статистика по функциям собирается
SELECT * FROM pg_stat_user_functions LIMIT 1;
-- → возвращает строки (сбор активен) или пустой результат (track_functions = none)

-- Проверка: pg_stat_statements активен
SELECT * FROM pg_extension WHERE extname = 'pg_stat_statements';
-- → extname = pg_stat_statements
```

**MariaDB/MySQL:**

```sql
-- Проверка: Performance Schema включена
SHOW VARIABLES LIKE 'performance_schema';
-- → performance_schema | ON

-- Проверка: потребитель programs включен
SELECT NAME, ENABLED
FROM performance_schema.setup_consumers
WHERE NAME LIKE '%program%';
-- → events_statements_summary_by_program | YES
```

### Построение baseline

1. **Соберите данные за 7 дней** в нормальных условиях эксплуатации.
2. **Рассчитайте перцентили** (P50, P95, P99) для времени выполнения ключевых процедур.
3. **Определите пороги алертов** на основе P99 + 20% (запас на всплески).
4. **Документируйте baseline** в runbook для отладки инцидентов.

---

## Рекомендации

1. **Алерты:** Настраивайте алерты на аномальное среднее время выполнения хранимых объектов.
2. **Базлайн:** Собирайте статистику минимум 7 дней до настройки алертов — это позволит определить нормальные диапазоны.
3. **pg_stat_statements (PostgreSQL):** Включайте в production — это расширение критически важно для анализа производительности хранимых процедур.
4. **Performance Schema (MariaDB/MySQL):** Включайте `events_statements_summary_by_program` и `events_statements_summary_by_digest` в production.
5. **Таймауты:** Устанавливайте локальные таймауты внутри процедур, чтобы избежать зависания сессий. В PostgreSQL: `statement_timeout`; в MariaDB: `max_statement_time`; в MySQL: `max_execution_time`. Последние два не ограничивают выполнение самого хранимого объекта, поэтому таймаут задаётся внутри тела.
6. **Версионирование:** Храните исходный код всех хранимых объектов в Git. Используйте инструменты миграций (Flyway, Liquibase, Atlas) для деплоя.
7. **Логирование:** Используйте встроенные механизмы (`RAISE NOTICE/LOG` в PostgreSQL, таблицу логов в MariaDB) для отслеживания хода выполнения тяжёлых процедур.

---

## Устранение неполадок

### Статистика по функциям пуста

**Симптомы:** `pg_stat_user_functions` возвращает пустой результат, хотя функции вызываются.

**Причина:** Параметр `track_functions` равен `none` (по умолчанию) или `pl`.

**Решение:**

```sql
-- Проверка
SHOW track_functions;
-- → none

-- Включение
ALTER SYSTEM SET track_functions = 'all';
SELECT pg_reload_conf();
```

### Процедуры не попадают в pg_stat_statements

**Симптомы:** Вызовы `CALL my_procedure()` не видны в `pg_stat_statements`.

**Причина:** Расширение не установлено или не подключено в `shared_preload_libraries`.

**Решение:**

```sql
-- Проверка установки
SELECT * FROM pg_extension WHERE extname = 'pg_stat_statements';

-- Если не установлено:
CREATE EXTENSION pg_stat_statements;
```

### Performance Schema не собирает статистику по программам

**Симптомы:** Таблица `events_statements_summary_by_program` пуста или отсутствует.

**Причина:** Потребитель `events_statements_summary_by_program` выключен.

**Решение:**

```sql
-- Включение
UPDATE performance_schema.setup_consumers
SET ENABLED = 'YES'
WHERE NAME = 'events_statements_summary_by_program';
```

### Высокое среднее время выполнения процедуры

**Диагностика:**

1. Определите проблемную процедуру через `pg_stat_user_functions` (PostgreSQL) или `events_statements_summary_by_program` (MariaDB/MySQL).
2. Проверьте `self_time` vs `total_time` — если `self_time` мал, проблема во вложенных вызовах.
3. Проанализируйте SQL внутри процедуры через `pg_stat_statements` или `events_statements_summary_by_digest`.
4. Проверьте блокировки: `pg_stat_activity` (PostgreSQL) или `sys.innodb_lock_waits` (MariaDB/MySQL).

---

## Лучшие практики

1. **Включайте `track_functions = all` в PostgreSQL на staging/production** — без этого вы не увидите статистику по функциям.
2. **Включайте Performance Schema в MariaDB/MySQL** — это подсистема с нулевым влиянием на производительность, когда не используется.
3. **Используйте `pg_stat_statements` как основной источник** для анализа производительности хранимых процедур в PostgreSQL.
4. **Документируйте baseline** времени выполнения ключевых процедур — это ускоряет диагностику инцидентов.
5. **Настраивайте алерты на P99, а не на среднее** — аномалии в "длинном хвосте" указывают на деградацию раньше, чем падение среднего.
6. **Коррелируйте метрики:** при росте времени выполнения процедуры проверяйте одновременно CPU, Disk I/O и блокировки — проблема может быть не в коде процедуры, а в ресурсах.

---

## Дополнительная информация

### См. также

- **[Хранимые объекты: обзор](../stored_objects_overview.md)** — общие принципы хранимых объектов.
- **[Отладка объектов в PostgreSQL](../../PostgreSQL/Concepts/stored_objects_debugging.md)** — техники профилирования и поиска ошибок.
- **[Управление объектами в MariaDB/MySQL](../../MariaDB/Concepts/stored_objects_management.md)** — Event Scheduler и отладка.
- **[Ключевые концепции производительности БД](../database_performance_concepts.md)** — USE-методология, Baseline, Troubleshooting паттерны.
- **[Troubleshooting хранимых объектов](troubleshooting.md)** — блокировки, рекурсия, ограничения СУБД.
- **[Безопасность хранимых объектов](security.md)** — модель привилегий, SECURITY DEFINER, динамический SQL.
