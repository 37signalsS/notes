# Диагностический runbook PostgreSQL: симптом, команда, причина

**Актуально для:** PostgreSQL 14–18 (возможности PG 17+ и 18+ помечены отдельно)

Справочник для разбора инцидентов по принципу «симптом → первая команда → вероятная
причина → решение». Не заменяет детальные разборы в специализированных файлах, а
связывает их: задача runbook — за минуту прийти к правильному файлу и правильной
команде.

Партнёры по теме: [Наблюдаемость](./observability.md) — метрики и wait events;
[Управление соединениями](./connection_management.md) — слоты и таймауты;
[Конкурентность и блокировки](../Concepts/concurrency_and_locking.md) — deadlock;
[Внутреннее устройство VACUUM](../Concepts/vacuum_internals.md) — bloat;
[Репликация](../Concepts/replication.md) — лаг и слоты; [Бэкап и восстановление](../Concepts/backup_and_recovery.md) — PITR;
[Восстановление после повреждений](../Concepts/corruption_recovery.md) — крах кластера;
[Коды ошибок](../Concepts/error_codes.md) — SQLSTATE.

## Определения

| Термин | Значение |
| :--- | :--- |
| Runbook | Документ, связывающий наблюдаемый симптом с диагностическими командами |
| First responder | Тот, кто разбирает инцидент первым; ему нужны команды, а не объяснения |
| Server log | Основной журнал сервера (`log_directory`); место, где всегда ищут первопричину |
| Wait event | Причина, по которой процесс сейчас не работает (`wait_event_type` + `wait_event` в `pg_stat_activity`) |
| Saturation | Степень загрузки ресурса, при которой он перестаёт справляться |
| SQLSTATE | Пятизначный код ошибки по стандарту SQL (например, `53300`); стабильнее текста ошибки |

## Базовые концепции

### Порядок разбора: не начинать с оптимизации

```
Симптом: «PostgreSQL тормозит»
  │
  ├─ 1. Воспроизводится ли? (тест извне против внутреннего SELECT 1)
  ├─ 2. Где слой: приложение / сеть / процесс postgres / диск / память
  ├─ 3. Что растёт: соединения, CPU, iowait, блокировки, dead tuples, WAL
  └─ 4. Только затем: планы запросов, индексы, настройки
```

Практическое правило: **прежде чем читать `EXPLAIN`, нужно установить, что именно
тормозит**. Обычная картина — приложение ждёт соединение (пулер упёрся в
`max_connections`), а не запрос; или запрос выполняется 3 мс, а latency 2 с из-за
ожидания в очереди на ввод-вывод. Оптимизация запроса в такой ситуации бесполезна.

### Первый сбор данных при инциденте

Собирайте всё одновременно и **до** любых изменений: после перезапуска следы
исчезают.

```sql
-- Минимальный ручной срез состояния кластера
SELECT version();
SELECT now() - xact_start AS xact_duration, pid, usename, state, left(query, 80) AS query
FROM pg_stat_activity WHERE xact_start IS NOT NULL ORDER BY xact_start LIMIT 5;
-- → xact_duration | pid | usename | state | query
-- → 00:14:32      | 742 | app_user | idle in transaction | UPDATE orders SET ...

SELECT count(*) AS total, state FROM pg_stat_activity GROUP BY state;
-- → total | state
-- → 187   | active
-- → 12    | idle in transaction

SELECT count(*) FROM pg_locks WHERE NOT granted;   -- число ожидающих блокировку
SELECT * FROM pg_stat_database WHERE datname = current_database() \gx
-- → blks_hit, blks_read (cache hit ratio), deadlocks, conflicts, temp_files
```

```bash
# Системный уровень
top -b -n1 | head -20              # CPU и load average
vmstat 1 5                         # iowait, run queue, free memory
iostat -x 1 3                      # %util, await, aqu-sz по дискам
free -h                            # доступная память и swap
df -h /var/lib/postgresql          # свободное место (PGDATA, pg_wal, tablespaces)
ss -tanp | grep 5432 | wc -l       # число TCP-соединений к 5432

# Server log — искать последнее, что произошло перед инцидентом
sudo tail -200 /var/log/postgresql/postgresql-18-main.log
```

### Что собрать перед перезапуском сервера

| Что | Зачем |
| :--- | :--- |
| `pg_stat_activity` (все колонки) | Долгие транзакции, `idle in transaction`, wait events |
| `pg_locks WHERE NOT granted` + `pg_blocking_pids()` | Цепочки блокировок |
| `pg_stat_replication` / `pg_replication_slots` | Лаг репликации, слоты, удерживающие WAL |
| `pg_stat_archiver` | Состояние WAL-архивации |
| `pg_stat_user_tables` (`n_dead_tup`, `last_autovacuum`) | Отставание autovacuum |
| `pg_stat_statements` (top по `total_exec_time`) | Тяжёлые запросы |
| `dmesg -T \| tail -50` | OOM-killer, ошибки диска |

## Практические сценарии

### Сценарий 1. «База тормозит» — общий алгоритм

| Шаг | Команда | На что смотреть |
| :--- | :--- | :--- |
| 1. Инфраструктура | `top`, `iostat -x 1`, `free -h` | CPU (steal time?), `%util` диска, swap |
| 2. Соединения | `SELECT count(*) FROM pg_stat_activity GROUP BY state;` | Доля `active` vs `idle`, приближение к `max_connections` |
| 3. Блокировки | `SELECT count(*) FROM pg_locks WHERE NOT granted;` | Растущая очередь ожидающих |
| 4. Статистика | `SELECT last_analyze FROM pg_stat_user_tables ORDER BY last_analyze LIMIT 5;` | Устаревший `ANALYZE` → плохой план |
| 5. Bloat | `SELECT n_dead_tup, last_autovacuum FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 5;` | Autovacuum отстаёт |
| 6. Планы | `EXPLAIN (ANALYZE, BUFFERS)` на эталонном запросе | `shared read` вместо `hit`, `Batches > 1` |

Глубокий разбор: [Оптимизация производительности](./performance_tuning.md),
[Математика планировщика](../Concepts/planner_internals.md).

### Сценарий 2. `FATAL: sorry, too many clients already` (SQLSTATE `53300`)

**Симптом:** приложение массово теряет соединения; новые подключения отклоняются.

```sql
SELECT count(*) AS used, (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') AS max_conn,
       (SELECT setting::int FROM pg_settings WHERE name = 'superuser_reserved_connections') AS reserved
FROM pg_stat_activity;
-- → used | max_conn | reserved
-- → 200  | 200      | 3
```

| Возможная причина | Решение |
| :--- | :--- |
| Утечка соединений в приложении (не закрываются) | Найти хосты с наибольшим числом сессий: `SELECT client_addr, count(*) FROM pg_stat_activity GROUP BY 1 ORDER BY 2 DESC;` |
| Нет пулера при process-per-connection | Включить [PgBouncer](./pgbouncer_setup.md) или [Pgpool-II](./pgpool.md) |
| `max_connections` занижен | Поднять (требует restart) — но сначала пулер; бюджет RAM: `work_mem × max_connections` |
| Connection storm после рестарта приложения | Растянуть reconnect в приложении; `reserved_connections` (PG 17+) для ролей мониторинга/миграций |

Детали: [Управление соединениями](./connection_management.md).

### Сценарий 3. `ERROR: deadlock detected` (SQLSTATE `40P01`)

**Симптом:** транзакции прерываются с `deadlock detected`; в логе `LOG: process NNN deadlock detected`.

```sql
SELECT deadlocks FROM pg_stat_database WHERE datname = current_database();
-- → deadlocks
-- → 42
```

| Возможная причина | Решение |
| :--- | :--- |
| Разный порядок UPDATE нескольких таблиц в коде | Единый порядок обновления таблиц/строк во всём приложении |
| Долгие транзакции, удерживающие блокировки | `idle_in_transaction_session_timeout`, `statement_timeout` на роли |
| Нужна диагностика конкуренции | `log_lock_waits = on` (дефолт off в PG 13–18, **on в PG 19**); `deadlock_timeout` (дефолт 1s) |

Детали: [Конкурентность и блокировки](../Concepts/concurrency_and_locking.md).

### Сценарий 4. `canceling statement due to statement timeout` (SQLSTATE `57014`) / `lock timeout` (`55P03`)

**Симптом:** запросы отменяются по таймауту; DDL зависает на `AccessExclusiveLock`.

```sql
-- Кто держит блокировку, мешающую миграции
SELECT blocked.pid AS blocked_pid, blocking.pid AS blocking_pid, blocking.query AS blocking_statement
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocked_locks.pid = blocking_activity.pid
WHERE NOT blocked_locks.granted;
-- → blocked_pid | blocking_pid | blocking_statement
-- → 8821        | 4417         | UPDATE orders SET status = ...
```

| Возможная причина | Решение |
| :--- | :--- |
| Долгий запрос держит таблицу | `pg_cancel_backend(pid)` (SIGINT) или `pg_terminate_backend(pid)` (SIGTERM; право `pg_signal_backend`) |
| Зависшая `idle in transaction` | Разобрать сессию; включить `idle_in_transaction_session_timeout` |
| Таймауты не настроены | `statement_timeout`, `lock_timeout`, `transaction_timeout` (PG 17) на роли |

Детали: [Управление соединениями](./connection_management.md),
[Миграции схемы](../Concepts/schema_migrations.md).

### Сценарий 5. База не стартует

**Симптом:** `systemctl start postgresql` падает; в логе `PANIC`, `invalid xlog record`, `lock file exists`.

| Симптом в логе | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `lock file exists` | Остался `postmaster.pid` после краха | Убедиться, что процессов нет (`pgrep postgres`), удалить `postmaster.pid` |
| `invalid xlog record at ...` | Повреждён WAL | [PITR из архива WAL](../Concepts/backup_and_recovery.md); `pg_resetwal` последним средством |
| `PANIC: could not locate a valid checkpoint record` | Повреждён `pg_control` | Восстановление из бэкапа; `pg_resetwal` последним средством |
| `database files are incompatible with server` | Запуск другими бинарниками (другая мажорная версия) | Запустить правильную версию (`/usr/lib/postgresql/18/bin/postgres`) |
| `FATAL: the database system is starting up` | Идёт recovery | Дождаться; проверить `pg_stat_recovery_prefetch` (PG 17+) |

Детали: [Восстановление после повреждений](../Concepts/corruption_recovery.md).

### Сценарий 6. Диск заполнен (SQLSTATE `53100`)

**Симптом:** `ERROR: could not extend file ...: No space left on device`; `df -h` показывает 100%.

```bash
# Что занимает место
du -sh /var/lib/postgresql/*/data/pg_wal /var/lib/postgresql/*/data/base/* 2>/dev/null | sort -rh | head
```

| Возможная причина | Решение |
| :--- | :--- |
| Replication slot не двигается (`restart_lsn` застыл) | `SELECT slot_name, wal_status, safe_wal_size FROM pg_replication_slots;` — удалить осиротевший слот или починить потребителя; ограничить `max_slot_wal_keep_size` |
| WAL-архивация не успевает | `SELECT failed_count, last_failed_wal FROM pg_stat_archiver;` — починить `archive_command`/S3 |
| Bloat таблиц | `VACUUM` (не освобождает диск), `pg_repack` / `REPACK` (PG 19) |
| Логи сервера разрослись | Ротация (`log_rotation_age`, `log_rotation_size`), чистка |
| `pg_wal` на отдельном диске не настроен | Перенести `pg_wal` на выделенный том |

Детали: [Репликация](../Concepts/replication.md) (слоты), [VACUUM](../Concepts/vacuum_internals.md) (bloat).

### Сценарий 7. OOM-killer убивает postgres

**Симптом:** в `dmesg -T` — `Out of memory: Killed process ... (postgres)`; соединения рвутся.

| Возможная причина | Решение |
| :--- | :--- |
| `work_mem × max_connections` превышает RAM | Снизить `work_mem` (бюджет: RAM × 0.25 / max_connections); `ALTER ROLE` для тяжёлых ролей |
| `maintenance_work_mem` / `autovacuum_work_mem` слишком велики | Ограничить; учесть `autovacuum_max_workers × autovacuum_work_mem` |
| Ядро разрешает overcommit | `vm.overcommit_memory = 2`, `vm.overcommit_ratio` по формуле из [тюнинга ОС](./performance_tuning.md#оптимизация-на-уровне-операционной-системы-linux) |
| Контейнер без лимитов | Memory limits + Guaranteed QoS в Kubernetes |

Детали: [Оптимизация производительности](./performance_tuning.md).

### Сценарий 8. Autovacuum отстаёт, bloat растёт

**Симптом:** `n_dead_tup` растёт, `last_autovacuum` стареет, таблицы раздуваются, запросы медленнеют.

```sql
SELECT relname, n_dead_tup, n_live_tup,
       round(n_dead_tup::numeric / greatest(n_live_tup, 1), 3) AS dead_ratio,
       last_autovacuum
FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 10;
-- → relname | n_dead_tup | n_live_tup | dead_ratio | last_autovacuum
-- → events  | 18400000   | 2100000    | 8.762      | 2026-10-03 04:12:01
```

| Возможная причина | Решение |
| :--- | :--- |
| Долгие транзакции удерживают `xmin` | Найти: `SELECT pid, now() - xact_start FROM pg_stat_activity WHERE xact_start IS NOT NULL ORDER BY 2 DESC;` |
| Глобальные scale factors не подходят для больших таблиц | `ALTER TABLE events SET (autovacuum_vacuum_scale_factor = 0.01);` |
| Autovacuum упирается в I/O | `autovacuum_vacuum_cost_limit = 1000–2000`, `autovacuum_vacuum_cost_delay` |
| Вручную разово | `VACUUM (VERBOSE) events;` — место на диске не вернёт; для этого `pg_repack` / `REPACK` (PG 19) |

Детали: [Внутреннее устройство VACUUM](../Concepts/vacuum_internals.md).

### Сценарий 9. Репликация отстаёт / слот удерживает WAL

**Симптом:** `pg_stat_replication.replay_lag` растёт; диск на Primary забит WAL.

```sql
-- На Primary
SELECT client_addr, state, sync_state, write_lag, flush_lag, replay_lag FROM pg_stat_replication;
-- → client_addr | state  | sync_state | write_lag | flush_lag | replay_lag
-- → 10.0.0.11   | streaming | sync    | 00:00:01  | 00:00:01  | 00:00:42

SELECT slot_name, slot_type, wal_status, safe_wal_size FROM pg_replication_slots;
-- → slot_name | slot_type | wal_status | safe_wal_size
-- → node2     | physical  | extended   | 0
```

| Возможная причина | Решение |
| :--- | :--- |
| Реплика медленно применяет WAL (диск/CPU) | Профиль реплики; `max_standby_streaming_delay` при конфликтах |
| Долгий запрос на реплике отменяется | `pg_stat_database_conflicts`, `hot_standby_feedback = on` (ценой bloat на Primary) |
| Неактивный слот держит WAL | Удалить слот или ограничить `max_slot_wal_keep_size`; `idle_replication_slot_timeout` (PG 18) |
| Сетевой разрыв | `wal_keep_size` как буфер для быстрого переподключения |

Детали: [Репликация](../Concepts/replication.md), [Наблюдаемость](./observability.md).

### Сценарий 10. WAL-архивация не работает

**Симптом:** `pg_stat_archiver.failed_count` растёт; `WARNING: WAL archiving is not enabled`.

```sql
SELECT archived_count, failed_count, last_archived_wal, last_failed_wal FROM pg_stat_archiver;
-- → archived_count | failed_count | last_archived_wal | last_failed_wal
-- → 1204           | 37           | 000000010000000A000000F2 | 000000010000000A000000F3
```

| Возможная причина | Решение |
| :--- | :--- |
| `archive_command` не записывает (нет места/прав) | Проверить вручную; `archive_mode = on`, `wal_level = replica` |
| Архив не самодостаточен для PITR | Бэкап без архивации WAL не даёт PITR — включить архивацию |
| Нужен стриминг без archive_timeout | `pg_receivewal` — получает WAL в реальном времени |

Детали: [Бэкап и восстановление](../Concepts/backup_and_recovery.md),
[WAL](../../Concepts/write_ahead_log.md).

### Сценарий 11. Cache hit ratio падает

**Симптом:** `blks_read` растёт относительно `blks_hit`; дисковая подсистема нагружена.

```sql
SELECT blks_hit, blks_read, round(blks_hit::numeric / nullif(blks_hit + blks_read, 0), 4) AS hit_ratio
FROM pg_stat_database WHERE datname = current_database();
-- → blks_hit | blks_read | hit_ratio
-- → 98410233 | 120441    | 0.9988
```

| Возможная причина | Решение |
| :--- | :--- |
| Working set не помещается в RAM | Масштабировать RAM; `shared_buffers` ≈ 25% RAM |
| Bloat раздувает сканирования | Сценарий 8 |
| Статистика PostgreSQL не различает диск и page cache ОС | Комбинировать `pg_statio_*` с `iostat` |

Детали: [Наблюдаемость](./observability.md), [Ёмкостное планирование](./capacity_planning.md).

### Сценарий 12. После апгрейда всё работает медленнее

**Симптом:** после `pg_upgrade` / `pg_restore` планы хуже, latency вырос.

| Возможная причина | Решение |
| :--- | :--- |
| Статистика оптимизатора отсутствует/устарела | `vacuumdb --all --analyze-in-stages --missing-stats-only`, затем `vacuumdb --all --analyze-only` (см. [pg_upgrade](./pg_upgrade.md)) |
| Расширенная статистика не перенесена | Пересоздать `CREATE STATISTICS` |
| Стоимостные константы под старое железо | `random_page_cost` (1.1–1.5 для SSD/NVMe), `effective_cache_size` |

Детали: [pg_upgrade](./pg_upgrade.md), [Математика планировщика](../Concepts/planner_internals.md).

### Сценарий 13. Частые ошибки приложений (SQLSTATE)

| SQLSTATE | Ошибка | Типичная причина | Решение |
| :--- | :--- | :--- | :--- |
| `23505` | `duplicate key value violates unique constraint` | Дубликат уникального ключа | Обработать в приложении (`ON CONFLICT`); проверить логику повторов |
| `23502` | `null value in column violates not-null constraint` | NOT NULL без значения | Исправить INSERT; проверить `DEFAULT` |
| `23503` | `insert or update on table violates foreign key constraint` | Родительской строки нет | Порядок вставок; `ON DELETE` политика |
| `23514` | `new row violates check constraint` | CHECK-ограничение | Валидация на входе |
| `22P02` | `invalid input syntax for type ...` | Тип не совпадает (`'abc'` → int) | Приведение типов в приложении/запросе |
| `42703` | `column "..." does not exist` | Опечатка/миграция не применена | Проверить миграции |
| `42P01` | `relation "..." does not exist` | Таблица не создана/переименована | Проверить search_path и миграции |
| `42501` | `permission denied for table ...` | Нет прав | `GRANT`; роль `pg_read_all_data` |
| `40001` | `could not serialize access due to concurrent update` | SSI/serializable конфликт | Повтор транзакции с экспоненциальной задержкой |
| `08006` | `connection failure` | Сеть/пулер/сервер недоступен | Проверить порт, firewall, PgBouncer |
| `57P03` | `the database system is starting up` | Идёт старт/recovery | Дождаться; проверить recovery |

Полный справочник: [Коды ошибок](../Concepts/error_codes.md).

### Сценарий 14. `idle in transaction` накапливаются

**Симптом:** растёт доля `idle in transaction`; VACUUM не успевает; блокировки висят.

```sql
SELECT pid, usename, now() - xact_start AS xact_age, state, left(query, 60) AS last_query
FROM pg_stat_activity WHERE state = 'idle in transaction' ORDER BY xact_age DESC LIMIT 10;
-- → pid  | usename | xact_age | state             | last_query
-- → 3311 | app     | 02:14:09 | idle in transaction | BEGIN
```

| Возможная причина | Решение |
| :--- | :--- |
| Приложение открывает транзакцию и не коммитит | Починить код; ORM-пулинг с `autocommit` |
| Нет защиты | `idle_in_transaction_session_timeout = 30s–5min` на роли |
| Нужна диагностика источника | `client_addr`, `application_name` в `pg_stat_activity` |

Детали: [Управление соединениями](./connection_management.md).

## Лучшие практики

1. **Собирайте данные до изменений** — после перезапуска следы исчезают.
2. **Не оптимизируйте запрос, не установив слой проблемы** — чаще всего это не запрос.
3. **Настройте таймауты на ролях** (`statement_timeout`, `idle_in_transaction_session_timeout`, `lock_timeout`) — ни один не включён по умолчанию.
4. **Мониторьте ведущие индикаторы**: соединения, deadlocks, `n_dead_tup`, `replay_lag`, `failed_count` архивера, cache hit ratio — [дашборд](./observability.md#базовые-метрики-здоровья-минимальный-дашборд).
5. **Логируйте ожидания блокировок**: `log_lock_waits = on` (в PG 19 уже дефолт).
6. **Учите приложение повторять транзакции** при `40001` и `40P01` — это норма для конкурентной среды.
7. **Runbook живёт рядом с алертами** — каждый алерт ссылается на сценарий этого файла.

## Дополнительная информация

*   [Наблюдаемость PostgreSQL](./observability.md) — wait events, метрики, алерты
*   [Управление соединениями](./connection_management.md) — слоты, таймауты, connection storm
*   [Оптимизация производительности](./performance_tuning.md) — тюнинг памяти, I/O, autovacuum
*   [Конкурентность и блокировки](../Concepts/concurrency_and_locking.md) — MVCC, deadlock, SSI
*   [Внутреннее устройство VACUUM](../Concepts/vacuum_internals.md) — bloat, freezing, wraparound
*   [Репликация](../Concepts/replication.md) — streaming, logical, слоты, лаг
*   [Бэкап и восстановление](../Concepts/backup_and_recovery.md) — PITR, pg_basebackup
*   [Восстановление после повреждений](../Concepts/corruption_recovery.md) — amcheck, pg_resetwal
*   [Коды ошибок](../Concepts/error_codes.md) — справочник SQLSTATE
*   [Общая методология диагностики сервисов](../../../Linux/Diagnostics/Troubleshooting/general_troubleshooting_methodology.md) — от порта к приложению
*   [Официальная документация: Server Messages](https://www.postgresql.org/docs/current/errcodes-appendix.html)
