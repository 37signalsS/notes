# Ёмкостное планирование PostgreSQL (Capacity Planning)

**Актуально для:** PostgreSQL 14–18 (изменения PG 17+ и PG 18+ помечены отдельно)

## Определения

*   **Capacity planning** — прогноз потребления ресурсов (RAM, CPU, диск, соединения, сеть) и планирование масштабирования до наступления деградации.
*   **Working set** — объём «горячих» данных, к которому обращается нагрузка; определяет требования к RAM.
*   **Headroom** — запас ресурса до насыщения; планируют масштабирование при расходовании headroom, а не после.
*   **Saturation** — точка, при которой ресурс перестаёт справляться (disk `%util` ≈ 100%, очередь `run queue` > ядер, соединения ≈ `max_connections`).
*   **RPO / RTO** — целевые потери данных и время восстановления; влияют на объём WAL-архива и число реплик (см. [Бэкап и восстановление](../Concepts/backup_and_recovery.md)).
*   **`wal_bytes` (pg_stat_wal)** — суммарный объём WAL-записей в байтах (PG 14+); в PG 18 остаётся в `pg_stat_wal`, хотя WAL I/O-статистика (включая времена записи/фсинка) перешла в `pg_stat_io` (см. ниже).
*   **`pg_stat_io` (PG 17+)** — кластер-wide I/O-статистика по `backend_type`/`context`/объекту; в PG 18 включает WAL-объекты (`object='wal'`) с колонками `read_bytes`/`write_bytes`, а также времена `fsync_time`/`write_time` для WAL.
*   **`pg_stat_checkpointer` (PG 17+)** — статистика процесса чекпоинтера; в PG ≤16 её показатели были в `pg_stat_bgwriter`.

## Предпосылки

1.  **Доступ к PostgreSQL:** роль `pg_monitor` или `SUPERUSER` (требуются права на `pg_stat_*`, `pg_database_size`, `pg_settings`).
2.  **OS-утилиты:** `iostat`, `vmstat`, `sar`, `free`, `df`, `nproc` — PostgreSQL-статистика дополняется данными ОС.
3.  **TSDB для долгосрочного хранения:** метрики должны храниться 1+ год для сезонного анализа (см. [Наблюдаемость](./observability.md)). Требуется `track_io_timing = on` и `track_wal_io_timing = on` (PG 14–17) для I/O-тайминга.
4.  **Синхронизация времени:** `chrony` или `systemd-timesyncd` на всех узлах — необходима для корректной корреляции метрик.
5.  **База baseline:** до начала тюнинга зафиксировать исходные замеры (`pgbench`, `iostat`, cache hit ratio) — иначе улучшение не отделить от шума.
6.  **PostgreSQL 18+** (рекомендуется): в PG 18 `track_wal_io_timing` удалён — WAL-тайминг читается из `pg_stat_io` для объекта `wal` без дополнительной конфигурации.

## Базовые концепции

### Что планируем

| Ресурс | Источник метрик | Ключевые параметры |
| :--- | :--- | :--- |
| RAM | `free`, `pg_stat_database` | `shared_buffers`, `work_mem`, `maintenance_work_mem`, `effective_cache_size` |
| CPU | `top`, `vmstat` | `max_connections`, `max_worker_processes`, `autovacuum_max_workers`, параллельные запросы |
| Диск: объём | `pg_database_size`, `pg_total_relation_size` | рост таблиц, bloat, `pg_wal`, temp-файлы |
| Диск: IOPS/throughput | `iostat -x`, `pg_stat_io` (PG 17+) | случайное vs последовательное чтение, чекпоинты; в PG 18 `pg_stat_io` также покрывает WAL-I/O с колонками `read_bytes`/`write_bytes` |
| Соединения | `pg_stat_activity` | `max_connections`, пулер |
| WAL | `pg_stat_wal` (PG 14–18: `wal_bytes`), `pg_stat_archiver`, `pg_stat_io` (PG 18+: объект `wal`) | `max_wal_size`, скорость генерации, архив |
| Сеть | `pg_stat_replication` | лаг, объём репликации |

### Бюджет RAM: как считать

*   `shared_buffers` ≈ **25% RAM** (дефолт 128MB; при > 32GB эффективность Clock Sweep снижается).
*   `effective_cache_size` ≈ **75% RAM** (оценка OS page cache + `shared_buffers`; не резервирует память).
*   `work_mem` — **на каждую** операцию сортировки/хеша: бюджет `work_mem × max_connections` может превысить RAM (при `max_connections=200` и `work_mem=64MB` — потенциально 12.8 GB).
*   `maintenance_work_mem` — на DDL-операцию (`CREATE INDEX`, `VACUUM`); 1–2 GB на сервере с большими таблицами.
*   `autovacuum_work_mem` — учесть множитель: до `autovacuum_max_workers × autovacuum_work_mem`.
*   Huge Pages: `vm.nr_hugepages` = (`shared_buffers` + запас на внутренние структуры) / 2MB.

Детали: [Оптимизация производительности](./performance_tuning.md), [Архитектура](../Concepts/architecture.md), [Настройка Linux](./linux_tuning.md).

### Бюджет диска: как считать

*   **Данные:** тренд `pg_database_size` по времени (метрики хранят 1+ год для capacity planning).
*   **WAL:** `pg_stat_wal.wal_bytes` (PG 14+) — скорость генерации × retention; OLTP-нагрузка с бинарными полями/JSON генерирует WAL на уровне блоков. В PG 18 дополнительно: `SELECT write_bytes FROM pg_stat_io WHERE object = 'wal'` — WAL I/O в байтах с временем записи/фсинка.
*   **Bloat:** `n_dead_tup` и реальный размер таблицы — раздувание увеличивает потребление диска и I/O.
*   **Temp-файлы:** `pg_stat_database.temp_files`, `temp_bytes` — внешние сортировки при нехватке `work_mem`.
*   **Репликация:** слоты удерживают WAL — `max_slot_wal_keep_size` как предохранитель.
*   **Правило:** планировать диск с запасом под WAL-архив (retention × скорость генерации) и под рост данных до следующего окна масштабирования.

### Бюджет соединений

Process-per-connection: каждое соединение — отдельный процесс с собственной памятью. Формула: `max_connections` определяется не числом клиентов, а числом **параллельных операций**; остальное — задача пулера ([PgBouncer](./pgbouncer_setup.md), [Pgpool-II](./pgpool.md)).

| Профиль | `max_connections` |
| :--- | :--- |
| Без пулера | 100–500 |
| С PgBouncer | 100–300 (запас 30% на админов, миграции, логическую репликацию) |

Детали: [Управление соединениями](./connection_management.md).

### Параметры WAL по умолчанию (справочно)

| Параметр | Дефолт | Описание |
| :--- | :--- | :--- |
| `max_wal_size` | 1 GB | Верхний порог before forced checkpoint; **не hard limit** — может превышаться на один цикл |
| `min_wal_size` | 80 MB | Минимум для рециклинга WAL-сегментов |
| `checkpoint_timeout` | 5 min | Интервал плановых чекпоинтов |
| `checkpoint_completion_target` | 0.9 | Доля интервала, за которую spread I/O |
| `checkpoint_warning` | 30s | Логирует предупреждение, если чекпоинты чаще |
| `wal_buffers` | 16MB (или 1/32 от `shared_buffers`, если `shared_buffers < 16MB`) | Буфер WAL в shared memory |

Источник: [WAL Configuration](https://www.postgresql.org/docs/18/wal-configuration.html)

## Операции и команды

| Команда / View | Цель | PG | Примечание |
| :--- | :--- | :--- | :--- |
| `pg_database_size(oid)` | Размер всех БД | 14+ | Считается в shared buffers |
| `pg_total_relation_size(regclass)` | Размер таблицы + индексов | 14+ | Включает toast |
| `pg_stat_wal.wal_bytes` | Объём WAL | 14+ | Дельта = скорость генерации |
| `pg_stat_io` (object='wal') | WAL I/O в байтах + времена | 17+ (WAL — PG 18+) | `read_bytes`, `write_bytes`, `fsync_time` |
| `pg_stat_checkpointer` | Чекпоинты, I/O | 17+ | `checkpoint_write_time`, `checkpoint_sync_time` |
| `pg_stat_bgwriter` | Чекпоинты (legacy) | ≤16 | В PG 17+ — `pg_stat_checkpointer` |
| `pg_stat_archiver` | Архивация WAL | 14+ | `archived_count`, `failed_count` |
| `pg_stat_database.blks_hit/blks_read` | Cache hit ratio | 14+ | `hit = hit / (hit + read)` |
| `pg_stat_activity` (state ≠ idle) | Активные соединения | 14+ | Фильтр по `query_start` для долгих |
| `pg_stat_replication` | Лаг репликации | 14+ | `write_lag`, `flush_lag`, `replay_lag` |
| `pg_stat_replication_slots` | Удержание WAL слотами | 14+ | `pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)` |
| `pg_stat_progress_vacuum` | Прогресс VACUUM | 12+ | `heap_blks_scanned` / `heap_blks_total` |
| `pg_stat_progress_create_index` | Прогресс CREATE INDEX | 12+ | `tuples_done` / `tuples_total` |
| `pg_stat_database_conflicts` | Конфликты на standby | 14+ | `conflicts_deadlock`, `conflicts_checksum` |

## Практические сценарии

### Сценарий: Прогноз роста данных

```sql
-- Текущие размеры топ-таблиц (база для тренда)
SELECT relname AS "Table",
       pg_size_pretty(pg_total_relation_size(relid)) AS "Total Size",
       pg_total_relation_size(relid) AS bytes
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC LIMIT 10;
-- → Table | Total Size | bytes
-- → events | 42 GB | 45097156608
```

Экспортируйте `bytes` в TSDB, постройте тренд на 90–365 дней, экстрапируйте до порога (например, 70% диска) — дата пересечения = дата масштабирования.

### Сценарий: Оценка скорости генерации WAL

```sql
-- PG 14+: общий объём WAL-записей
SELECT wal_bytes, pg_size_pretty(wal_bytes) AS pretty FROM pg_stat_wal;
-- → wal_bytes | pretty
-- → 1825363968 | 1741 MB

-- PG 18+: WAL I/O в байтах (замена/дополнение к pg_stat_wal)
SELECT write_bytes, write_time, fsyncs, fsync_time
FROM pg_stat_io WHERE object = 'wal' AND context = 'normal';
-- → write_bytes | write_time | fsyncs | fsync_time
-- → 1825363968  | 45200      | 1204   | 8412
```

Замерьте дважды с интервалом (например, час) — разница `wal_bytes` = скорость генерации WAL. Умножьте на retention WAL-архива (RPO-политика) — минимальный объём архивного хранилища.

> **PG 18:** `wal_bytes` в `pg_stat_wal` измеряет размер WAL-записей. `write_bytes` в `pg_stat_io` (object='wal') — размер по `wal_block_size` (обычно 8KB). Они не идентичны, но коррелируют.

### Сценарий: Проверка, что working set помещается в RAM

```sql
-- Cache hit ratio по базе
SELECT blks_hit, blks_read,
       round(blks_hit::numeric / nullif(blks_hit + blks_read, 0), 4) AS hit_ratio
FROM pg_stat_database WHERE datname = current_database();
-- → blks_hit | blks_read | hit_ratio
-- → 98410233 | 120441    | 0.9988
```

`hit_ratio < 0.99` для активных данных — working set не помещается в RAM (или bloat раздувает сканирования). Действия: масштабировать RAM, уменьшить bloat, проверить `shared_buffers`.

### Сценарий: IOPS и чекпоинты

```sql
-- PG 17+: статистика чекпоинтера (ранее — pg_stat_bgwriter в PG ≤16)
SELECT checkpoints_timed, checkpoints_req,
       checkpoint_write_time, checkpoint_sync_time
FROM pg_stat_checkpointer;
-- → checkpoints_timed | checkpoints_req | checkpoint_write_time | checkpoint_sync_time
-- → 1204              | 312             | 8412                    | 902
```

`checkpoints_req` ≈ `checkpoints_timed` — чекпоинты упираются в `max_wal_size`, увеличьте его (баланс RTO vs производительность записи). На диске: `iostat -x 1` — `%util` ≈ 100% и растущий `await` при пиках чекпоинтов = не хватает IOPS или WAL на отдельном томе.

> **В PG ≤16** аналогичные метрики в `pg_stat_bgwriter` (столбцы `checkpoints_timed`, `checkpoints_req`, `checkpoint_write_time`, `checkpoint_sync_time`).

### Сценарий: Когда масштабироваться (пороги)

| Метрика | Порог | Действие |
| :--- | :--- | :--- |
| Соединения / `max_connections` | > 80% | Пулер, `max_connections`, разбор утечек |
| Cache hit ratio | < 99% | RAM, bloat, `shared_buffers` |
| Диск занято | > 70% | Рост, очистка, масштабирование |
| Диск `%util` (iostat) | ≈ 100% постоянно | IOPS, WAL на отдельный том, NVMe |
| `checkpoints_req` / (`checkpoints_timed` + `checkpoints_req`) | > 20% | `max_wal_size` ↑, I/O |
| `n_dead_tup` растёт, `last_autovacuum` стареет | — | autovacuum tuning, workers |
| CPU run queue | > число ядер | CPU, параллелизм запросов |
| `wal_bytes` рост > 2× baseline | — | Разбор bulk-операций, инъекции WAL |
| Replay lag | > 30s (SLO) | Реплика: CPU/диск, `max_standby_streaming_delay` |

### Сценарий: Планирование под пиковую нагрузку

1.  Замерить baseline в часы минимальной нагрузки (`pg_stat_statements`, `iostat -xz 1`, cache hit ratio).
2.  Определить пиковый коэффициент (например, 3× от медианы) по историческим метрикам.
3.  Проверить headroom по каждому ресурсу при пике: RAM (working set + буферы), CPU (run queue), диск (IOPS × пик), соединения (пик × коэффициент).
4.  Заложить запас под отказ узла (HA): при потере Primary нагрузка переезжает на standby — его профиль должен тянуть пик.

## Валидация и проверка

1.  **Cache hit ratio** — `SELECT sum(blks_hit)::float / (sum(blks_hit) + sum(blks_read)) FROM pg_stat_database;` должен быть `> 0.99` для OLTP, `> 0.95` для аналитики.
2.  **WAL headroom** — `wal_bytes` за 1 час × retention (в часах) < (свободное место на диске − план роста данных). Допустимый coэффициент запаса: 2×.
3.  **Проверка bloat** — `SELECT schemaname, tabname, bs * (relpages)::bigint AS real_size, bs * (relpages - avgsize)::bigint AS approx_table_size FROM ...` (см. [VACUUM internals](../Concepts/vacuum_internals.md)). Разница > 50% = bloat требует очистки.
4.  **Проверка слотов репликации** — `SELECT slot_name, pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes FROM pg_replication_slots;` — retained > 50% от `max_slot_wal_keep_size` = слот удерживает WAL, диск заполняется.
5.  **Проверка temp_files** — рост `pg_stat_database.temp_bytes` между базой и staging = недостаточно `work_mem` или аналитические запросы просачиваются в OLTP.

## Мониторинг и алерты (DevOps / SRE)

### SLO и пороги

| Метрика | Warning | Critical | SLO Action |
| :--- | :--- | :--- | :--- |
| Диск (данные) | > 70% | > 85% | Scale-up, cleanup, partition pruning |
| Диск (`pg_wal`) | > 50% | > 75% | Увеличить `max_wal_size`, отдельный том |
| WAL generation rate | > 2× baseline | > 5× baseline | Разбор bulk-операций, throttling |
| `checkpoints_req` fraction | > 10% | > 30% | Увеличить `max_wal_size` |
| Cache hit ratio | < 99% | < 97% | RAM, bloat, `shared_buffers` |
| `max_connections` usage | > 80% | > 95% | PgBouncer, `max_connections` |
| Replication replay lag | > 10s | > 60s | Диагностика standby |

### Автоматизация

**Cron-скрипт для съёма метрик** (пример с `psql` + запись в локальный файл для затем импорта в TSDB):

```bash
#!/bin/bash
# capacity_metrics.sh — ежедневный сбор ёмкостных метрик
TS=$(date +%s)
psql -At -c "
  SELECT now(),
         (SELECT pg_database_size(current_database())),
         (SELECT wal_bytes FROM pg_stat_wal),
         (SELECT round(100*(sum(blks_hit)::float)/(sum(blks_hit)+sum(blks_read)),2) FROM pg_stat_database),
         (SELECT count(*) FROM pg_stat_activity WHERE state != 'idle'),
         (SELECT setting::int FROM pg_settings WHERE name = 'max_connections')
" >> /var/log/postgres/metrics_capacity.tsv
```

**SRE-чек перед деплоем:** перед bulk-операцией проверяйте `pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0')` на standby и `pg_stat_io` для объекта `wal` — WAL surge > 3× baseline = отложите или уменьшите `batch_size`.

### Dashboards (оперативный мониторинг)

| Панель | Метрика | Источник | Цель |
| :--- | :--- | :--- | :--- |
| Диск и WAL | Рост данных + WAL generation rate | `pg_database_size` + `pg_stat_wal.wal_bytes` | Forecast до порога |
| I/O нагрузка | `pg_stat_checkpointer.checkpoint_sync_time` | `pg_stat_checkpointer` | Чекпоинт-стресс |
| Соединения | Активные / `max_connections` | `pg_stat_activity` | Saturation risk |
| Replication | Replay lag, slot retention | `pg_stat_replication`, `pg_replication_slots` | Failover readiness |

Подробнее: [Наблюдаемость](./observability.md), [Архитектура наблюдаемости БД](../../../Concepts/Observability_and_Monitoring/database_observability.md).

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Cache hit ratio < 99% | Working set > RAM; или bloat | Увеличить RAM; `VACUUM ANALYZE` + `pg_repack`; проверить `shared_buffers` |
| Частые forced checkpoint (`checkpoints_req`) | `max_wal_size` мал для нагрузки | Увеличить `max_wal_size` (баланс с RTO); вынести `pg_wal` на быстрый том |
| `temp_files` растут | `work_mem` недостаточен | `SET LOCAL work_mem` для аналитики; проверить неанализированные bulk-операции |
| Replication lag растёт | WAL generation > standby throughput | Отложить bulk-операции; проверить диск/CPU на standby; `max_standby_streaming_delay` |
| Слоты удерживают WAL | Standby отстаёт, слот не two_phase | Отключить слот, дождаться catch-up, перезапустить; `max_slot_wal_keep_size` как safety net |
| `n_dead_tup` растёт, autovacuum не работает | scale_factor слишком мал для больших таблиц | Per-table `autovacuum_vacuum_scale_factor`/`autovacuum_analyze_scale_factor`; увеличить `autovacuum_max_workers` |
| OOM-killer в `dmesg` | `work_mem × max_connections` + overcommit | `vm.overcommit_memory = 2`; снизить `work_mem` или `max_connections`; добавить RAM |
| Бурный рост размера таблицы без роста данных | Bloat (UPDATE-heavy) | `pgstattuple`, `pg_repack` или `pg_squeeze`; планировать в окне обслуживания |
| `wal_bytes` spike после `ALTER TABLE` | Полный rewrite + full-page writes | Планировать rewrite в off-peak; `wal_compression = on` для уменьшения |
| `parallel_workers_to_launch` ≈ 0 (PG 18) | max_parallel_workers exhausted | Увеличить `max_parallel_workers`; проверить `max_parallel_workers_per_gather` |

Подробнее: [Диагностический runbook](./troubleshooting_runbook.md) — сценарии 6–12, 14 охватывают ёмкостные проблемы.

## Лучшие практики

1.  **Метрики хранить 1+ год** — сезонность (месячные отчёты, годовые пики) видна только на длинном горизонте.
2.  **Baseline до тюнинга** — без исходных замеров улучшение отличить от шума невозможно.
3.  **Планировать по тренду, а не по текущему** — дата пересечения порога = дата действия.
4.  **Считать `work_mem` как бюджет** — `work_mem × max_connections`, а не изолированно.
5.  **WAL — отдельный том** — изоляция последовательной записи WAL от случайного доступа таблиц.
6.  **Тестировать пик на staging** — AIO (PG 18), JIT, параллелизм: эффект зависит от нагрузки.
7.  **Ёмкость реплик = ёмкость Primary** — при failover standby должен принять полную нагрузку.
8.  **Увеличивать `max_wal_size` только после измерения** — неуглывший WAL = `max_wal_size` слишком мал; решение не в blind-увеличении, а в выявлении причины spike.
9.  **SRE: alert на WAL rate spike** — WAL generation > 2× baseline за 15 мин = сигнал для анализа bulk-операций или инъекций.

## Очистка и откат

**Откат параметров памяти и WAL (требуют restart):**
```sql
-- Откат через ALTER SYSTEM (без pg_reload_conf — postmaster context)
ALTER SYSTEM RESET shared_buffers;
ALTER SYSTEM RESET max_wal_size;
ALTER SYSTEM RESET wal_buffers;
SELECT pg_reload_conf();  -- только для sighup-параметров
```
Для параметров `postmaster` (`shared_buffers`, `wal_buffers`, `huge_pages`) — правка `postgresql.conf` и `sudo systemctl restart postgresql`.

**Откат session-параметров:**
```sql
-- Сброс session-override (work_mem, temp_buffers и т.п.)
SET LOCAL work_mem = DEFAULT;        -- на оставшиеся команды транзакции
RESET work_mem;                      -- на всю сессию
```

**Очистка мониторинговых артефактов:**
```bash
# Временные файлы PostgreSQL (удалять только при остановленном сервере)
ls $PGDATA/base/*/pgsql_tmp/
```

**Восстановление disk headroom после очистки:** удалите старые логи (`log_directory`), уменьшите retention в `archive_command` (если локальный), запустите `REINDEX` или `pg_repack` для очистки bloat.

## Ограничения и граничные случаи

*   **Bulk LOAD (COPY/INSERT):** WAL-генерация может spike до 10–50× baseline — `max_wal_size` должен покрывать пик, а не среднее. Для bulk-загрузки: `wal_level = minimal` (только для одноразовых загрузок, не для репликации), `UNLOGGED` таблицы.
*   **Seasonal (periodическая) нагрузка:** планировать ресурсы на пик, а не на среднее — Black Friday, отчётные периоды, ETL-окна.
*   **`interval '1 day'` ≠ 24 часа:** при смене season (DST) `interval '1 day'` = 24 часа фиксированно, а `timestamp + interval '1 day'` может сместиться на час. Используйте `timestamp + interval '1 day'` только если это допустимо.
*   **Контейнеры (systemd-nspawn, chroot):** `--tmpfs /var/lib/postgresql/data/pg_wal` для уменьшения WAL-нагрузки на диск; `shared_buffers` ограничены cgroup-лимитами — проверяйте `memory.max` в systemd-юните.
*   **Logical replication:** `pg_logical` слоты не удерживают WAL так же, как physical — но `max_replication_slots` всё равно ограничен.
*   **AIO (PG 18+):** `io_uring` может снизить latency, но не решает проблему insufficient IOPS — планировать диск с запасом.
*   **`wal_compression = on`:** уменьшает WAL volume за счёт CPU — эффективно при storage-бутылочном горлышке, но не при CPU-bound.

## Дополнительная информация

*   [Оптимизация производительности](./performance_tuning.md) — параметры памяти и I/O
*   [Управление соединениями](./connection_management.md) — слоты, `max_connections`, пулинг
*   [Наблюдаемость](./observability.md) — метрики и алерты
*   [Репликация](../Concepts/replication.md) — лаг, слоты
*   [Внутреннее устройство VACUUM](../Concepts/vacuum_internals.md) — bloat и потребление диска
*   [Диагностический runbook](./troubleshooting_runbook.md) — разбор насыщения ресурсов
*   [Общая концепция наблюдаемости БД](../../../Concepts/Observability_and_Monitoring/database_observability.md) — типы метрик, процентили
*   [Настройка Linux для PostgreSQL](./linux_tuning.md) — NUMA, huge pages, vm.overcommit_memory
*   [WAL Configuration](https://www.postgresql.org/docs/18/wal-configuration.html) — checkpoint parameters
*   [Monitoring Database Activity](https://www.postgresql.org/docs/18/monitoring.html) — views and stats
*   [Runtime Configuration](https://www.postgresql.org/docs/18/runtime-config-resource.html) — memory и параметры
