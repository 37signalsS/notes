# Автоматизация обслуживания PostgreSQL

**Актуально для:** PostgreSQL 13–19 (`pg_cron` 1.5+ — `cron.timezone` и секундные интервалы; `cron.schedule_in_database` / `cron.alter_job` — 1.4+; `MAINTAIN` / `pg_maintain` — PG 17+)

## Определения

*   **Обслуживание (Maintenance)** — регламентные операции, которые autovacuum не выполняет: `REINDEX`, `REFRESH MATERIALIZED VIEW`, обновление расширенной статистики, проверка bloat и wraparound, проверка целостности (`amcheck`), валидация бэкапов.
*   **`pg_cron`** — расширение-планировщик SQL-задач внутри базы (background worker; синтаксис расписания — Vixie cron). Метаданные (`cron.job`) живут в одной базе кластера (`cron.database_name`, по умолчанию `postgres`); расширение можно установить только в одну базу.
*   **Каденс (cadence)** — периодичность операций: daily / weekly / monthly. Autovacuum и ANALYZE работают непрерывно по порогам и не требуют расписания; расписание нужно для всего остального.
*   **Bloat-метрики** — оценки раздувания таблиц и индексов: `pgstattuple` (точная, полный скан), `pgstattuple_approx` (быстрая, пропускает all-visible страницы по visibility map), `pgstatindex` (плотность листьев B-tree).
*   **Wraparound-мониторинг** — контроль `age(datfrozenxid)` и `mxid_age(datminmxid)` по базам; жёсткий лимит XID — 2.1 млрд с запасом 3 млн, failsafe-порог `vacuum_failsafe_age` — 1.6 млрд (PG 14+). Подробнее — [Внутреннее устройство VACUUM](../Concepts/vacuum_internals.md).
*   **`MAINTAIN` (PG 17+)** — привилегия на задачи обслуживания (`VACUUM`, `ANALYZE`, `REINDEX`, `REFRESH MATERIALIZED VIEW`, `CLUSTER`, `LOCK TABLE`) без прав суперпользователя; роль `pg_maintain` — глобальный аналог.
*   **`pg_repack`** — расширение для онлайн-дефрагментации таблиц и индексов (альтернатива `VACUUM FULL` без длительной полной блокировки).
*   **`amcheck`** — расширение логической проверки целостности btree-индексов и heap (`bt_index_check`, `bt_index_parent_check`, `verify_heapam`); см. [Восстановление после повреждений](../Concepts/corruption_recovery.md).

## Базовые концепции

### Что делает autovacuum, а что нет

| Операция | Autovacuum | Нужен каденс |
| :--- | :--- | :--- |
| `VACUUM` (обычный) | Да (по порогам) | Только для отстающих таблиц |
| `ANALYZE` | Да (по порогам) | После массовой загрузки |
| `REINDEX` | Нет | Да (повреждения, bloat индексов) |
| `REFRESH MATERIALIZED VIEW` | Нет | Да (по SLA свежести) |
| Extended statistics (`CREATE STATISTICS`) | Нет | После изменения паттернов запросов |
| Проверка целостности (`amcheck`) | Нет | Да (weekly/monthly) |
| Проверка бэкапа (restore test) | Нет | Да (weekly/monthly) |
| Контроль wraparound | Частично (autovacuum freezing) | Да (ежедневный мониторинг) |

### Режимы блокировок операций обслуживания

Выбор операции определяется тем, что она блокирует (полная таблица режимов — в [Блокировках](../Concepts/concurrency_and_locking.md)):

| Операция | Блокировка | Чтение | Запись |
| :--- | :--- | :--- | :--- |
| `VACUUM` (обычный), `ANALYZE` | SHARE UPDATE EXCLUSIVE | да | да |
| `CREATE INDEX CONCURRENTLY`, `REINDEX CONCURRENTLY` | SHARE UPDATE EXCLUSIVE | да | да |
| `REINDEX` (обычный) | запись на таблице заблокирована; ACCESS EXCLUSIVE — на самом индексе | да, кроме запросов по этому индексу | нет |
| `VACUUM FULL`, `CLUSTER` | ACCESS EXCLUSIVE | нет | нет |
| `REFRESH MATERIALIZED VIEW` | ACCESS EXCLUSIVE | нет | нет |
| `REFRESH MATERIALIZED VIEW CONCURRENTLY` | EXCLUSIVE | да | нет |

### `pg_cron` — как устроен

*   Загружается через `shared_preload_libraries = 'pg_cron'` (требуется restart); база с метаданными — `pg_cron.database_name` (по умолчанию `postgres`).
*   Задача — строка в `cron.job` (`jobid`, `schedule`, `command`, `database`, `username`, `nodename`, `nodeport`). Выполняется в базе из поля `database` под ролью из поля `username` (по умолчанию — текущие при создании); RLS-политика ограничивает видимость задач создателем (кроме superuser / `bypassrls`).
*   Расписание — 5 полей cron; `$` — последний день месяца (pg_cron 1.6+); интервалы вида `'30 seconds'` (1.5+). Время интерпретируется в `cron.timezone` (по умолчанию GMT — явно задайте локальный пояс).
*   Параллелизм: разные задачи выполняются параллельно (до `cron.max_running_jobs`, default 32), но одна и та же задача — только в одной инстанции; повторный триггер ставится в очередь, а не пропускается.
*   Подключение к БД: по умолчанию libpq на `localhost` — требуется `trust` в `pg_hba.conf` для роли задач или `.pgpass`; альтернативы — `cron.host = '/tmp'` (unix-сокет) или `cron.use_background_workers = on` (конкурентность ограничена `max_worker_processes`).
*   Hot standby: на репликах задачи не выполняются; после promote планировщик стартует автоматически.
*   История: `cron.job_run_details` (`jobid`, `runid`, `job_pid`, `database`, `username`, `command`, `status`, `return_message`, `start_time`, `end_time`). Записи не чистятся автоматически — нужна задача-чистка или `cron.log_run = off`.
*   Ограничения: только SQL-команды (shell-уровень — `pg_dump`, `pg_basebackup`, `pg_ctl` — в системном cron/systemd, см. [Автоматизацию бэкапов](./backup_automation.md)); одна команда на задачу; `REINDEX CONCURRENTLY` нельзя в транзакции (см. [Устранение неполадок](#устранение-неполадок)).

Настройки pg_cron (context: postmaster, кроме `cron.log_min_messages` и `cron.launch_active_jobs` — sighup, применяются через `pg_reload_conf()`):

| Параметр | Default | Назначение |
| :--- | :--- | :--- |
| `cron.database_name` | `postgres` | База с метаданными (`cron.job`) |
| `cron.host` | `localhost` | Хост для подключений к БД (можно unix-сокет) |
| `cron.timezone` | `GMT` | Часовой пояс расписания |
| `cron.max_running_jobs` | `32` | Макс. число одновременно выполняемых задач |
| `cron.use_background_workers` | `off` | Выполнять задачи через background workers вместо клиентских подключений |
| `cron.log_run` | `on` | Писать запуски в `cron.job_run_details` |
| `cron.log_statement` | `on` | Логировать команды задач перед выполнением |
| `cron.log_min_messages` | `WARNING` | Уровень сообщений launcher-процесса |
| `cron.launch_active_jobs` | `on` | При `off` — отключить все активные задачи без restart (reload) |
| `cron.enable_superuser_jobs` | `on` | Разрешать задачи от superuser (отключите при раздельной эксплуатации) |

Текущие значения: `SELECT * FROM pg_settings WHERE name LIKE 'cron.%';`

### Привилегии для обслуживания

До PG 17: `VACUUM`/`ANALYZE`/`REINDEX`/`REFRESH MATERIALIZED VIEW` требовали владельца таблицы или суперправ. PG 17+: `GRANT MAINTAIN ON TABLE t TO role;` или `GRANT pg_maintain TO role;` — делегирование без суперправ (см. [Роли](./role_management.md)).

*   `REINDEX INDEX`/`REINDEX TABLE` — достаточно `MAINTAIN` на таблице; `REINDEX SCHEMA`/`REINDEX DATABASE` — владелец схемы/базы или `pg_maintain`; системные (shared) каталоги переиндексируются только при `MAINTAIN` на них.
*   `REFRESH MATERIALIZED VIEW` (любая форма) — требует `MAINTAIN` на материализованном представлении.
*   `pgstattuple` — `EXECUTE` по умолчанию только у роли `pg_stat_scan_tables` (добавьте роль в неё или выдайте `EXECUTE`).

## Практические сценарии

### Предварительные требования

1.  **`pg_cron`**: пакет из PGDG — `postgresql-18-cron` (Debian/Ubuntu) или `pg_cron_18` (RHEL/CentOS/Fedora); `shared_preload_libraries = 'pg_cron'` + restart.
2.  **Права**: суперпользователь для установки расширения; `pg_maintain` (PG 17+) или владелец таблиц для задач обслуживания.
3.  **Доступ**: `pg_hba.conf` разрешает локальное подключение роли задач (`trust` для localhost / unix-сокет) либо `.pgpass`, либо `cron.use_background_workers = on`.

### 1. Установка и первая задача `pg_cron`

```bash
# postgresql.conf
shared_preload_libraries = 'pg_cron'
pg_cron.database_name = 'postgres'
cron.timezone = 'Europe/Moscow'
```
```bash
sudo systemctl restart postgresql
# → Cluster is running
```
```sql
-- В базе postgres:
CREATE EXTENSION pg_cron;
-- → CREATE EXTENSION

-- Каждый день в 03:00 по локальному времени: обновление статистики по горячей таблице
SELECT cron.schedule('nightly-analyze-events',
                     '0 3 * * *',
                     'ANALYZE events');
-- →        jobid
-- → 1

-- Просмотр задач и истории
SELECT jobid, schedule, command, database, username FROM cron.job;
-- → jobid | schedule  | command         | database | username
-- → 1     | 0 3 * * * | ANALYZE events  | postgres | postgres

SELECT jobid, runid, status, return_message, start_time, end_time
FROM cron.job_run_details ORDER BY start_time DESC LIMIT 5;
-- → jobid | runid | status    | return_message | start_time          | end_time
-- → 1     | 42    | succeeded | ANALYZE events | 2026-10-04 03:00:01 | 2026-10-04 03:00:03

-- Управление задачей (pg_cron 1.4+)
SELECT cron.alter_job(1, '0 4 * * *');              -- → изменить расписание
SELECT cron.unschedule('nightly-analyze-events'); -- → true (удалить по имени)
```

Задача в другой базе (pg_cron 1.4+):

```sql
SELECT cron.schedule_in_database('nightly-analyze-events',
                                 '0 3 * * *',
                                 'ANALYZE events',
                                 'analytics_db');
-- → jobid
```

Чистка истории (записи `cron.job_run_details` не чистятся автоматически):

```sql
SELECT cron.schedule('cleanup-job-run-details',
                     '0 4 * * *',
                     $$DELETE FROM cron.job_run_details WHERE end_time < now() - interval '7 days'$$);
-- → jobid
```

### 2. Daily-скрипт (системный cron или pg_cron)

```sql
-- 1. Отстающий autovacuum: таблицы с большим числом мёртвых кортежей
SELECT schemaname, relname, n_dead_tup,
       round(n_dead_tup * 100.0 / greatest(n_live_tup, 1), 1) AS dead_pct,
       last_autovacuum
FROM pg_stat_user_tables
WHERE n_dead_tup > 50000 AND n_dead_tup * 100.0 / greatest(n_live_tup, 1) > 20
ORDER BY n_dead_tup DESC;
-- → schemaname | relname | n_dead_tup | dead_pct | last_autovacuum
-- → (0 rows) — всё чисто

-- 2. Wraparound: возраст XID и MXID по базам (тревога — 1.5 млрд, failsafe — 1.6 млрд, лимит — 2.1 млрд)
SELECT datname, age(datfrozenxid) AS xid_age, mxid_age(datminmxid) AS mxid_age
FROM pg_database ORDER BY xid_age DESC;
-- → datname  | xid_age  | mxid_age
-- → myapp_db | 12345678 | 456789
-- → (если xid_age > 1.5e9 — срочный агрессивный VACUUM; см. [Внутреннее устройство VACUUM](../Concepts/vacuum_internals.md))

-- 3. Неиспользуемые индексы (кандидаты на удаление)
SELECT schemaname, relname, indexrelname, idx_scan
FROM pg_stat_user_indexes
JOIN pg_index USING (indexrelid)
WHERE idx_scan = 0 AND NOT indisunique AND NOT indisprimary
ORDER BY pg_relation_size(indexrelid) DESC LIMIT 10;
-- → перед удалением убедитесь, что статистика не обнулена перезапуском (см. Пограничные случаи)

-- 4. Проверка задач pg_cron за сутки (SRE-алерт на failed)
SELECT jobid, runid, status, return_message, start_time
FROM cron.job_run_details
WHERE status = 'failed' AND start_time > now() - interval '1 day';
-- → (0 rows) — всё успешно
```

### 3. Weekly: REINDEX и bloat

```sql
-- REINDEX CONCURRENTLY: перестройка индекса без блокировки записи (PG 12+)
REINDEX INDEX CONCURRENTLY idx_events_user_id;
-- → REINDEX (без блокировки записи; при сбое — INVALID-индекс *_ccnew, удалите его и повторите)

-- Точная оценка bloat таблицы (полный скан — дорого на TB-таблицах)
CREATE EXTENSION IF NOT EXISTS pgstattuple;
SELECT * FROM pgstattuple('events');
-- → table_len | tuple_count | tuple_len | tuple_percent | dead_tuple_count | dead_tuple_len | dead_tuple_percent | free_space | free_percent
-- → 42 GB     | 120M        | 38 GB     | 90.5          | 8M               | 2.1 GB         | 5.0                | ...        | ...
-- dead_tuple_percent > 20% — кандидат на VACUUM FULL / pg_repack

-- Быстрая оценка на больших таблицах (пропускает all-visible страницы)
SELECT table_len, scanned_percent, dead_tuple_percent, approx_tuple_percent
FROM pgstattuple_approx('events');
-- → table_len | scanned_percent | dead_tuple_percent | approx_tuple_percent
-- → 42 GB     | 3.2             | 5.0                | 91.4

-- Bloat индекса: плотность листьев B-tree (< 50–60% — кандидат на перестройку)
SELECT avg_leaf_density, leaf_fragmentation FROM pgstatindex('idx_events_user_id');
-- → avg_leaf_density | leaf_fragmentation
-- → 41.20            | 0
```

Прогресс перестройки отслеживается в `pg_stat_progress_create_index` (`REINDEX` и `REINDEX CONCURRENTLY`, PG 12+); для всей базы офлайн — `reindexdb -j 4 mydb` (параллельные подключения). Раздувание таблиц (heap), а не индексов, онлайн-решает `pg_repack` (см. [Индексы](../Concepts/indexes.md)). Память: `maintenance_work_mem` (см. [Оптимизацию производительности](./performance_tuning.md)).

### 4. Monthly: materialized views, amcheck, валидация бэкапа

```sql
-- REFRESH MATERIALIZED VIEW CONCURRENTLY (требует уникальный индекс по столбцам без WHERE/выражений; MV должен быть populated)
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_sales;
-- → REFRESH MATERIALIZED VIEW (без блокировки чтения; блокирует запись — режим EXCLUSIVE)

-- Аудит свежести MV: PG не хранит время рефреша — процедура + задача pg_cron
-- (REFRESH ... CONCURRENTLY допустим внутри транзакции, в отличие от REINDEX CONCURRENTLY)
CREATE OR REPLACE PROCEDURE refresh_mv_with_audit()
LANGUAGE plpgsql AS $$
BEGIN
  REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_sales;
  INSERT INTO mv_refresh_audit (matviewname, refreshed_at) VALUES ('mv_daily_sales', now());
END $$;

SELECT cron.schedule('refresh-mv-daily-sales', '0 3 * * *', 'CALL refresh_mv_with_audit()');
-- → jobid
```

```sql
-- Логическая проверка целостности (amcheck; untrusted-расширение — суперправа)
CREATE EXTENSION IF NOT EXISTS amcheck;
-- bt_index_check: AccessShareLock (как SELECT), работает на репликах; ошибка = повреждение
SELECT bt_index_check('idx_events_user_id');
-- → (без ошибки) — индекс консистентен; разбор вывода ошибок в [Восстановлении после повреждений](../Concepts/corruption_recovery.md)
-- bt_index_parent_check: ShareLock (блокирует запись), НЕ работает на hot standby — для окон обслуживания
```

Валидация бэкапа — восстановление на стенде и smoke-тест: см. [Валидацию бэкапов](../../Concepts/backup_validation.md) и [Автоматизацию бэкапов](./backup_automation.md).

### 5. Делегирование обслуживания (PG 17+)

```sql
-- Роль для задач обслуживания без суперправ
CREATE ROLE maintenance_job;
GRANT pg_maintain TO maintenance_job;
GRANT CONNECT ON DATABASE myapp_db TO maintenance_job;
-- Таймауты задаём на уровне роли: задача pg_cron — одна команда, SET внутри неё не работает
ALTER ROLE maintenance_job SET statement_timeout = '1h';
ALTER ROLE maintenance_job SET lock_timeout = '5min';
-- Затем задачи pg_cron планировать от этой роли (поле username в cron.job)
```

## Устранение неполадок

| Ошибка / симптом | Причина | Решение |
| :--- | :--- | :--- |
| `ERROR: extension "pg_cron" is not available` / `can only create extension in database "postgres"` | `CREATE EXTENSION` выполнен не в `cron.database_name` | Выполнить в настроенной базе (по умолчанию `postgres`) |
| Задача есть в `cron.job`, но не выполняется | pg_hba не разрешает локальное подключение роли; launcher не стартовал | Проверить `cron.host`, `trust`/`.pgpass`, `shared_preload_libraries`; статус — в `cron.job_run_details` (`return_message`) |
| `ERROR: cannot execute REINDEX CONCURRENTLY in a transaction block` | Команда внутри `BEGIN`/`COMMIT`, функции или multi-строковой команды | Запускать как автономную команду; таймауты — через `ALTER ROLE ... SET` |
| Индекс `..._ccnew` в статусе `INVALID` после `REINDEX CONCURRENTLY` | Сбой конкурентной перестройки (deadlock, нарушение уникальности) | `DROP INDEX CONCURRENTLY "..._ccnew"` и повторить `REINDEX INDEX CONCURRENTLY` |
| `ERROR: cannot refresh materialized view "..." because it is not populated` | `CONCURRENTLY` требует заполненный MV | Сначала полный `REFRESH MATERIALIZED VIEW` (без `CONCURRENTLY`) |
| `ERROR: cannot refresh ... concurrently because it does not have a unique index` | Нет уникального индекса по столбцам (без выражений и `WHERE`) | Создать `CREATE UNIQUE INDEX` на MV |
| Задача не запускается повторно, хотя время прошло | Предыдущая инстанция ещё выполняется — повторный запуск в очереди | Проверить `cron.job_run_details` на `running`; настроить `statement_timeout` роли |
| `cron.job_run_details` растёт без ограничений | Записи не чистятся автоматически | Задача-чистка (см. сценарий 1) или `cron.log_run = off` |
| `database is not accepting commands to avoid wraparound data loss in database "..."` | Аварийный режим wraparound (возраст ≈ 2.1 млрд − 3 млн) | Остановить БД, запустить в single-user mode, выполнить агрессивный `VACUUM` (разбор в [Внутреннем устройстве VACUUM](../Concepts/vacuum_internals.md)) |
| Задачи не выполняются на реплике | pg_cron не запускает задачи в hot standby | Ожидаемое поведение; после promote планировщик стартует автоматически |

## Лучшие практики

1.  **Каденс по умолчанию:** daily — мониторинг (dead tuples, wraparound, неиспользуемые индексы, failed-задачи); weekly — `REINDEX CONCURRENTLY` по bloat-отчёту, `REFRESH MATERIALIZED VIEW`; monthly — restore-test бэкапа, `amcheck`, пересборка расширенной статистики.
2.  **`REINDEX CONCURRENTLY` вместо `REINDEX` на production:** обычный `REINDEX` блокирует запись на таблицу и берёт ACCESS EXCLUSIVE на индексе (чтение через него встаёт); `CONCURRENTLY` — только SHARE UPDATE EXCLUSIVE. При сбое `CONCURRENTLY` оставляет INVALID-индекс `_ccnew` (удалить и повторить).
3.  **`REFRESH MATERIALIZED VIEW CONCURRENTLY`** — требует уникального индекса по столбцам на заполненном MV; без него — полный блокирующий рефреш (ACCESS EXCLUSIVE). Одновременно может выполняться только один рефреш одного MV.
4.  **`pg_cron` для SQL, системный cron/systemd для shell**: `pg_dump`/`pg_basebackup`/`wal-g` — в systemd timer/cron/Ansible (timers предпочтительнее cron — защита от наложения через `flock`, см. [Автоматизацию бэкапов](./backup_automation.md)); `ANALYZE`/`REFRESH`/`REINDEX` — в `pg_cron`.
5.  **Не дублируйте autovacuum**: ручной `VACUUM` — только для отстающих таблиц (см. мониторинг выше); глобальный nightly `VACUUM FULL` — антипаттерн (блокирует и переписывает всё).
6.  **Wraparound-алерт** — ежедневно: `age(datfrozenxid) > 1.5e9` — страница в runbook; `> 1.6e9` — срабатывает failsafe (`vacuum_failsafe_age`, PG 14+): VACUUM обходит cost-delay и обслуживание индексов; `> 1.8e9` — инцидент; жёсткий лимит — 2.1 млрд (с запасом 3 млн — аварийное отключение команд).
7.  **Логирование**: `log_autovacuum_min_duration = 10s` — все autovacuum-действия дольше 10с в лог (см. [Наблюдаемость](./observability.md)); `cron.log_statement = on` — команды задач перед выполнением.
8.  **Часовой пояс**: явно задайте `cron.timezone` (по умолчанию GMT) — иначе «03:00» в расписании — это GMT, а не локальное время.
9.  **Таймауты на роли обслуживания** (`statement_timeout`, `lock_timeout` через `ALTER ROLE`) — долгая задача не висит бесконечно и не держит очередь каденса.
10. **`max_parallel_maintenance_workers`** (default 2, PG 11+) управляет параллелизмом внутри `REINDEX`/`CREATE INDEX`; поднимайте при перестройке больших индексов в окне обслуживания (вместе с `maintenance_work_mem`).

## Пограничные случаи

*   **`pg_cron` и транзакции**: каждая задача — отдельная транзакция; команда одна на задачу (не оборачивайте в `BEGIN`/`COMMIT` и не объединяйте несколько инструкций — `REINDEX CONCURRENTLY` в таком виде не выполнится); длинные задачи обрываются по `statement_timeout` роли.
*   **`REINDEX CONCURRENTLY` и параллельность**: одновременно — только одна конкурентная перестройка на таблицу; `max_parallel_maintenance_workers` управляет воркерами внутри одной операции; обычный `REINDEX` параллелит построение (PG 11+), `VACUUM (PARALLEL n)` — PG 13+.
*   **`REINDEX` на партиционированных таблицах**: каждая партиция переиндексируется в отдельной транзакции; команду нельзя запустить внутри `BEGIN`/`COMMIT`; `TABLESPACE` обновляет только leaf-партиции.
*   **`REINDEX SYSTEM` не поддерживает `CONCURRENTLY`**; индексы exclusion-ограничений нельзя перестраивать конкурентно (в форме `REINDEX TABLE/DATABASE CONCURRENTLY` они пропускаются).
*   **`pgstattuple` vs `pgstattuple_approx`**: `pgstattuple` — точный полный скан (дорого на TB-таблицах); `pgstattuple_approx` — пропускает all-visible страницы по visibility map, dead-кортежи считает точно, live — приближённо. Быстрая оценка dead-кортежей — `pg_stat_user_tables.n_dead_tup`.
*   **`ANALYZE` после `COPY`**: массовая загрузка (`COPY`) не запускает autovacuum-ANALYZE сразу — делайте `ANALYZE` в конце ETL-окна.
*   **Неиспользуемые индексы и перезапуск**: статистика `pg_stat_user_indexes` обнуляется при перезапуске кластера — не удаляйте «неиспользуемые» индексы сразу после restart; набирайте статистику за полный цикл.
*   **`pg_cron` в HA-кластере (Patroni/Spilo)**: на standby задачи не выполняются; при failover планировщик автоматически стартует на новом лидере (расширение должно быть в `shared_preload_libraries` всех узлов).
*   **Wraparound в multi-DB кластере**: `age(datfrozenxid)` считается по базе; агрессивный autovacuum в одной базе не спасает другую. В PG 19 multixact переведён на 64-битные смещения — wraparound MXID устранён (см. [Внутреннее устройство VACUUM](../Concepts/vacuum_internals.md)).
*   **PG 19**: autovacuum умеет параллельно обслуживать индексы (`autovacuum_max_parallel_workers`, default `0` = выключено; per-table `autovacuum_parallel_workers`).
*   **Безопасность pg_cron**: задачи видны и изменяемы только создателем (RLS); `cron.enable_superuser_jobs = off` запрещает задачи от superuser — рекомендуется при разделении эксплуатации.

## Дополнительная информация

*   [Внутреннее устройство VACUUM](../Concepts/vacuum_internals.md) — freezing, wraparound, пороги autovacuum.
*   [Оптимизация производительности](./performance_tuning.md) — `maintenance_work_mem`, `autovacuum_work_mem`.
*   [Автоматизация бэкапов](./backup_automation.md) — системный cron/systemd timer для `pg_dump`/`pg_basebackup`.
*   [Валидация бэкапов](../../Concepts/backup_validation.md) — restore-test.
*   [Роли и базы данных](./role_management.md) — `pg_maintain` / `MAINTAIN`.
*   [Наблюдаемость](./observability.md) — `log_autovacuum_min_duration`, `pg_stat_progress_*`.
*   [Вспомогательные расширения](../Concepts/extensions_utility.md) — настройка `pg_cron`, `pg_stat_statements`, `auto_explain`.
*   [Восстановление после повреждений](../Concepts/corruption_recovery.md) — `amcheck`, `REINDEX` при коррупции.
*   [Индексы](../Concepts/indexes.md) — `pgstatindex`, bloat, `pg_repack`.
*   [Блокировки](../Concepts/concurrency_and_locking.md) — режимы блокировок.
*   [Официальная документация: pg_cron](https://github.com/citusdata/pg_cron)
*   [Официальная документация: REINDEX](https://www.postgresql.org/docs/current/sql-reindex.html)
*   [Официальная документация: REFRESH MATERIALIZED VIEW](https://www.postgresql.org/docs/current/sql-refreshmaterializedview.html)
*   [Официальная документация: pgstattuple](https://www.postgresql.org/docs/current/pgstattuple.html)
*   [Официальная документация: amcheck](https://www.postgresql.org/docs/current/amcheck.html)
