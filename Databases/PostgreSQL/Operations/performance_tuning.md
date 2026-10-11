# Оптимизация производительности PostgreSQL

**Актуально для:** PostgreSQL 14–18

Операционный тюнинг: параметры памяти, I/O, autovacuum, диагностика и SRE-чек-листы. Теория — в концептуальных файлах: архитектура и память (**[Архитектура](../Concepts/architecture.md)**), MVCC и блокировки (**[Concurrency and Locking](../Concepts/concurrency_and_locking.md)**), механизмы VACUUM (**[Внутреннее устройство VACUUM](../Concepts/vacuum_internals.md)**), математика планировщика (**[Cost Model](../Concepts/planner_internals.md)**).

## Определения

**Многоверсионность (MVCC, Multi-Version Concurrency Control)** — основной механизм управления параллельным доступом. При каждом `UPDATE`/`DELETE` создаётся новая версия строки, а старая помечается как «мёртвая». Читающие процессы не блокируют пишущие, и наоборот. Подробности — **[Управление параллелизмом и блокировки](../Concepts/concurrency_and_locking.md)**.

**Раздувание (Bloat)** — физическое увеличение объёма таблиц и индексов из-за накопления «мёртвых» кортежей (dead tuples). Bloat увеличивает I/O, замедляет последовательное сканирование и неэффективно использует кэш.

**Очистка (VACUUM)** — процесс, который делает «мёртвые» кортежи доступными для повторного использования, очищает их записи из индексов и предотвращает Transaction ID Wraparound. Обычный `VACUUM` не уменьшает физический файл таблицы; для переписи требуется `VACUUM FULL` или `pg_repack`. Глубокий разбор (Freezing, Multixacts, Wraparound) — **[Внутреннее устройство VACUUM](../Concepts/vacuum_internals.md)**.

**План выполнения (Execution Plan)** — стратегия, выбранная оптимизатором. `EXPLAIN ANALYZE` выполняет запрос и показывает реальную статистику; **GENERIC_PLAN (PG 16)** — план параметризованного запроса без его выполнения. Cost model (MCV, гистограммы) — **[Математика планировщика](../Concepts/planner_internals.md)**.

**Коэффициент попадания в кэш (Cache hit rate)** — доля страниц данных, найденных в `shared_buffers`. Целевое значение для активных данных — >99%.

**Журнал упреждающей записи (WAL, Write-Ahead Logging)** — механизм обеспечения надёжности (Atomicity & Durability). Все изменения сначала фиксируются в WAL (последовательный ввод-вывод), а затем асинхронно применяются к файлам данных.

**Контрольная точка (Checkpoint)** — момент синхронизации «грязных» страниц из RAM на диск. Оптимизация частоты чекпоинтов — ключ к стабильной производительности I/O.

**Пул соединений (Connection Pool)** — прокси-сервис (например, PgBouncer), решающий проблему Process-per-connection. Позволяет обслуживать тысячи клиентов ограниченным числом процессов PostgreSQL.

**Контекст параметра** — уровень, на котором применяется настройка: `postmaster` (только при restart), `sighup` (reload), `user` (в рамках сессии/транзакции). Определяет, требуется ли перезапуск кластера — критично для планирования обслуживания.

## Предпосылки

- PostgreSQL 14–18; доступ к `postgresql.conf` и права суперпользователя (или роль `pg_monitor` для чтения статистики).
- **Baseline до тюнинга:** снять метрики (`pg_stat_statements`, `iostat -xz 1`, cache hit ratio) — без исходных замеров нельзя отличить улучшение от шума.
- Расширение `pg_stat_statements` установлено: `CREATE EXTENSION pg_stat_statements;` + `shared_preload_libraries = 'pg_stat_statements'` в `postgresql.conf` (требует **restart**).
- Известна конфигурация железа: объём RAM, тип хранилища (HDD/SSD/NVMe), число ядер, модель нагрузки (OLTP/OLAP).

## Основные концепции

### Оптимизация на уровне операционной системы (Linux)

Производительность PostgreSQL критически зависит от настроек ядра и файловой системы.

| Область | Параметр | Рекомендация | Обоснование |
| :--- | :--- | :--- | :--- |
| **Память** | `vm.swappiness` | `1` - `10` | Минимизирует использование swap, предотвращая резкие скачки Latency. |
| **Память** | `Huge Pages` | `try` или `on` | Снижает нагрузку на TLB (Translation Lookaside Buffer) за счет страниц по 2 МБ вместо 4 КБ. Число страниц (`vm.nr_hugepages`) рассчитывается как `(shared_buffers + запас на внутренние структуры PostgreSQL) / 2 МБ`. |
| **Память** | `Overcommit` | `vm.overcommit_memory = 2` | Защищает от OOM-killer, запрещая ядру подтверждать выделение памяти сверх физического лимита + swap. `vm.overcommit_ratio` ≈ `100 × (RAM − shared_buffers − запас ОС) / RAM`. |
| **Диск** | `Scheduler` | `mq-deadline` / `none` | Современные SSD/NVMe эффективнее работают без сложного планирования I/O на уровне ядра. |
| **Диск** | `Mount options` | `noatime, nodiratime` | Отключает обновление времени доступа к файлам, экономя ресурс диска и IOPS. |
| **Сеть** | `TCP Keepalives` | Снизить интервалы | Позволяет быстрее обнаруживать и закрывать «повисшие» клиентские соединения. |

### Работа MVCC и влияние на производительность

MVCC избавляет от блокировок при чтении, но создаёт нагрузку на подсистему хранения. Если данные обновляются быстрее, чем `autovacuum` их очищает, возникает **Bloat**.

**Задачи Autovacuum:**
- Освобождение места для повторного использования.
- Сбор статистики для планировщика (`ANALYZE`).
- Предотвращение Transaction ID Wraparound (критическая ситуация, требующая остановки БД).
- **Streaming I/O (PG 17)** — ускоряет работу `ANALYZE` и последовательного сканирования за счет асинхронной подгрузки данных.
- **TidStore (PG 17)** — структура в RAM для эффективной очистки индексов.

### Методы доступа к данным (Scans)

| Тип | Описание | Применение |
| :--- | :--- | :--- |
| **Seq Scan** | Последовательное чтение всей таблицы. | Малые таблицы или выборка > 15-20% данных. |
| **Index Scan** | Поиск в индексе + переход к строке в куче. | Точечные запросы, высокая селективность. |
| **Index Only Scan** | Чтение данных напрямую из индекса. | Индекс содержит все запрашиваемые колонки (см. `INCLUDE`). |
| **Bitmap Scan** | Сбор TID из индекса → Сортировка → Чтение страниц. | Несколько индексов, средняя селективность, сложный `WHERE`. |

### Причины игнорирования индексов

1. **Низкая селективность:** если планировщик считает, что быстрее прочитать всю таблицу, чем прыгать по индексу.
2. **Устаревшая статистика:** отсутствие актуальных данных после массовых изменений (требуется `ANALYZE`).
3. **Функции в условии:** `WHERE date(created_at) = '2026-08-17'` не использует обычный индекс. *Решение: индекс по выражению.*
4. **Неявное приведение типов:** сравнение `varchar` с `int` заставляет БД выполнять преобразование для каждой строки.
5. **Тюнинг стоимости чтения:** если `random_page_cost` завышен относительно реальности (например, оставлен 4.0 для NVMe). *Решение: снизить до 1.1.*

### Анализ планов запросов

Команда `EXPLAIN (ANALYZE, BUFFERS, SETTINGS)` — «золотой стандарт» диагностики.

**Пример вывода:**
```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM users WHERE id = 42;
-- Index Scan using users_pkey on users  (cost=0.42..8.44 rows=1 width=102) (actual time=0.015..0.016 rows=1 loops=1)
--   Index Cond: (id = 42)
--   Buffers: shared hit=3
-- Planning Time: 0.088 ms
-- Execution Time: 0.035 ms
```

**На что смотреть:**
- **Actual time:** реальное время выполнения.
- **Rows (Estimation vs Actual):** если разница значительна — статистика устарела.
- **Buffers:**
    - `shared hit`: данные взяты из `shared_buffers` (RAM).
    - `shared read`: данные прочитаны с диска.
    - `shared dirtied/written`: указывает на «грязные» страницы, которые придется сбрасывать на диск.

## Практические сценарии

### Сценарий 1: Базовый тюнинг параметров (postgresql.conf)

Настройки зависят от объема RAM и типа нагрузки. **Контекст** определяет применение: `postmaster` — только restart, `sighup` — reload (`sudo systemctl reload postgresql`), `user` — в рамках сессии.

| Параметр | Значение по умолчанию | Рекомендация | Комментарий |
| :--- | :--- | :--- | :--- |
| `shared_buffers` | 128MB | 25% от всей RAM | Кэш страниц. Контекст: **postmaster** (restart). Выше 32ГБ часто не имеет смысла из-за оверхеда на управление. Документация прямо предупреждает: выделение более 40% RAM в `shared_buffers` вряд ли окажется лучше меньшего значения, поскольку PostgreSQL опирается и на кэш ОС. |
| `effective_cache_size` | 4GB | 75% от всей RAM | Помогает планировщику оценить объем кэша ОС. Значение по умолчанию не резервирует и не распределяет память — оно используется только для оценок. |
| `work_mem` | 4MB | 4MB - 64MB | Память на **каждую** операцию сортировки/хэша, а не на запрос. Опасно при высоком `max_connections`. |
| `hash_mem_multiplier` | 2.0 | 2.0 - 4.0 | PG 13+; допустимый диапазон 1-1000. Хеш-таблицы получают `work_mem × hash_mem_multiplier`. Хеш-операции чувствительнее к памяти, чем эквивалентные сортировки: поднимайте множитель, когда spill наблюдается только у хеш-узлов. |
| `maintenance_work_mem` | 64MB | 512MB - 2GB | Ускоряет `VACUUM`, `CREATE INDEX`, `ALTER TABLE ADD FOREIGN KEY`. Может быть многократно больше `work_mem`: операции выполняются по одной на сессию. |
| `autovacuum_work_mem` | -1 (наследует `maintenance_work_mem`) | Задать явно при большом числе таблиц | Иначе каждый воркер autovacuum получает полный `maintenance_work_mem`, и суммарно их может быть до `autovacuum_max_workers × maintenance_work_mem`. |
| `wal_buffers` | -1 (≈1/32 `shared_buffers`, min 64kB) | Оставить -1 | Контекст: **postmaster**. Автонастройка даёт разумный результат; вручную (несколько МБ) имеет смысл только при массе одновременных коммитов — эффект от больших значений незначителен. |
| `effective_io_concurrency` | 1 | 200 (SSD/NVMe) | Число одновременных I/O-операций на одну сессию (Seq Scan, bitmap heap scan). Для HDD оставить 1. Аналог для обслуживающих операций — `maintenance_io_concurrency` (default 10). |
| `max_parallel_workers_per_gather` | 2 | 2 - 4 | Параллельные запросы: каждый воркер получает собственный лимит `work_mem`, поэтому пиковое потребление памяти умножается на `(1 + число воркеров)`. |
| `random_page_cost` | 4.0 | 1.1 (SSD) / 4.0 (HDD) | Для современных хранилищ разрыв между Seq и Random минимален. |
| `max_wal_size` | 1GB | 4GB - 16GB | Увеличивает интервал между Checkpoint, снижая I/O пики. |
| `checkpoint_timeout` | 5min | 15min - 30min | Увеличивает производительность, но замедляет восстановление после сбоя. |
| `checkpoint_completion_target` | 0.9 | 0.9 | Размывает нагрузку записи на весь интервал чекпоинта. |

**Бюджет `work_mem`: почему «4MB - 64MB» опасно.** `work_mem` ограничивает каждую отдельную операцию, а не запрос:

*   **Сортировки** используют `work_mem` в `ORDER BY`, `DISTINCT` и merge join.
*   **Хеш-таблицы** используют `work_mem × hash_mem_multiplier` в hash join, хеш-агрегации, узлах `Memoize` и при обработке `IN`-подзапросов через хеш.

Один запрос может выполнять несколько таких операций одновременно, а параллельные запросы — умножаться на число воркеров. Оценка пикового потребления:

```text
peak ≈ work_mem × hash_mem_multiplier × (число узлов Sort/Hash в плане) × (1 + max_parallel_workers_per_gather)
```

Официальная документация формулирует это так: параллельный запрос с 4 воркерами может использовать до 5 раз больше CPU, памяти и полосы I/O, чем запрос без воркеров, поскольку лимиты вроде `work_mem` применяются к каждому воркеру отдельно. Отсюда правило: глобальное увеличение `work_mem` противопоказано при большом `max_connections` — вместо этого его поднимают локально в конкретной сессии или в конкретной роли.

Дополнительный множитель появляется при разбиении по партициям. Параметры `enable_partitionwise_join` и `enable_partitionwise_aggregate` (оба по умолчанию `off`) увеличивают число узлов, ограниченных `work_mem`, линейно числу сканируемых партиций, а планирование при этом становится заметно дороже по памяти и CPU.

```sql
-- Диагностика: сколько операций с ограничением work_mem в конкретном плане
EXPLAIN (ANALYZE, BUFFERS) SELECT ...;
```

Признаки spill на диск в выводе `EXPLAIN (ANALYZE)`:

*   У узла `Sort` поле `Sort Method` принимает значение `external merge` вместо `quicksort` и появляется размер `Disk: ...kB`. Допустимые значения — `quicksort`, `top-N heapsort`, `external merge`.
*   У узлов `Hash Join` и `HashAggregate` появляется `Batches` больше 1 и ненулевой `Disk Usage`. Признак не зависит от имени узла, поэтому ориентироваться нужно именно на эти поля.

**Логирование для диагностики** (контекст: `sighup`, reload):
```conf
log_min_duration_statement = 200ms   # лог медленных запросов
log_checkpoints = on                 # частота и длительность чекпоинтов
log_autovacuum_min_duration = 10s    # действия autovacuum
track_counts = on                    # default; статистика для pg_stat_*
```

### Сценарий 2: Управление соединениями

PostgreSQL использует модель **Process-per-connection**: каждое подключение порождает отдельный backend-процесс. При большом количестве клиентов накладные расходы на переключение контекста снижают RPS, а потребление RAM растёт линейно.

**Ключевые подходы:**
- **Внешний пулер (PgBouncer)** — оптимален для веб-приложений и ORM. Позволяет держать `max_connections` на уровне 100–300, обслуживая тысячи внешних соединений. Подробнее: **[Настройка PgBouncer](./pgbouncer_setup.md)**.
- **Нативная оптимизация** — настройка `max_connections`, `idle_in_transaction_session_timeout`, `tcp_keepalives_*`, мониторинг `pg_stat_activity`. Полное руководство: **[Управление соединениями PostgreSQL](./connection_management.md)**.

**Правило:** сумма `default_pool_size` всех пулов PgBouncer **меньше** `max_connections` PostgreSQL (оставляем запас на админов и миграции).

### Сценарий 3: Секционирование (Partitioning)

Для таблиц > 50-100 ГБ.
- **Partition Pruning:** планировщик читает только нужные партиции.
- **Maintenance:** мгновенное удаление старых данных через `DETACH PARTITION` и `DROP TABLE`.
- **Локальность:** индексы на партициях меньше и лучше помещаются в RAM.

### Сценарий 4: Оптимизация тяжелых запросов

1. **Поиск:** Расширение `pg_stat_statements` (обязательно в Production). Анализ `total_exec_time`.
2. **Анализ:** `EXPLAIN (ANALYZE, BUFFERS)` для выявления узких мест.
3. **Индексация:** Добавление пропущенных индексов, использование покрывающих индексов (`INCLUDE`).
4. **Статистика:** `CREATE STATISTICS` для коррелирующих колонок (например, `city` и `zip_code`).
5. **JIT:** Отключение для OLTP (`jit = off`), включение для сложных OLAP запросов.
6. **Процедурная логика:** Оптимизация PL/pgSQL функций и триггеров (устранение переключений контекста). См. **[Оптимизация PL/pgSQL](../Concepts/pl_pgsql_optimization.md)**.

### Сценарий 5: Борьба с раздуванием (Bloat) и настройка autovacuum

Если `autovacuum` не успевает очищать данные (растёт `n_dead_tup`, падает производительность, раздуваются таблицы):

**Пороги срабатывания autovacuum** (контекст: `sighup`, переопределяются на уровне таблицы):

| Параметр | Default | Назначение |
| :--- | :--- | :--- |
| `autovacuum_vacuum_scale_factor` | 0.2 | Доля таблицы, добавляемая к порогу мёртвых кортежей для VACUUM. Для больших таблиц 20% — слишком много: снижают до 0.01-0.05. |
| `autovacuum_vacuum_threshold` | 50 | Абсолютный минимум мёртвых кортежей. |
| `autovacuum_vacuum_insert_scale_factor` | 0.2 | Доля для триггера VACUUM по вставкам (PG 13+) — актуально для append-only таблиц. |
| `autovacuum_vacuum_insert_threshold` | 1000 | Абсолютный порог вставок (PG 13+); `-1` отключает вакуумирование по вставкам. |
| `autovacuum_analyze_scale_factor` | 0.1 | Доля для триггера ANALYZE. |
| `autovacuum_naptime` | 1min | Интервал проверки таблиц воркером. |
| `autovacuum_max_workers` | 3 | Число параллельных воркеров. |

**Переопределение для конкретной таблицы** (не требует reload — хранимые параметры):
```sql
ALTER TABLE big_table SET (autovacuum_vacuum_scale_factor = 0.01,
                           autovacuum_vacuum_threshold = 1000);
```

**Порядок действий:**
1. **Мониторинг:** оценка Bloat через расширение `pgstattuple` (`SELECT pgstattuple('table');` → `dead_tuple_percent`) или динамику `n_dead_tup` из `pg_stat_user_tables`.
2. **Тюнинг:** снижение `autovacuum_vacuum_scale_factor` до 0.01 для больших таблиц (см. таблицу выше).
3. **pg_repack:** онлайн-пересоздание таблицы без эксклюзивной блокировки.
4. **Large Objects:** если используются блобы, не забывайте про очистку "сиротских" объектов через `vacuumlo`, так как они значительно раздувают базу и замедляют бэкапы. См. **[Large Objects: Администрирование и очистка](../Concepts/large_objects.md)**.

**Как работает pg_repack** (пошагово):
    1. Создаётся временная таблица-копия.
    2. Данные копируются из оригинала в копию.
    3. Триггер ловит все текущие изменения (`INSERT/UPDATE/DELETE`) и пишет их в лог-таблицу.
    4. Изменения из лог-таблицы применяются к копии до полной синхронизации.
    5. Происходит быстрая подмена (swap) имен таблиц.
    6. Оригинал удаляется.

**Результат:** полная дефрагментация без остановки сервиса.

### Сценарий 6: SRE Чек-лист экспресс-диагностики

Когда база «тормозит» сейчас:

**1. ОС и Инфраструктура:**
- `htop` (CPU), `iostat -xz 1` (диск, искать `%util > 80%`), `dmesg` (OOM).

**2. Слой СУБД (Диагностические запросы):**
- **Поиск блокировок:**
  ```sql
  SELECT blocked_locks.pid AS blocked_pid, blocking_locks.pid AS blocking_pid,
         blocked_activity.query AS blocked_statement, blocking_activity.query AS blocking_statement
  FROM pg_catalog.pg_locks blocked_locks
  JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_locks.pid = blocked_activity.pid
  JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype
  JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_locks.pid = blocking_activity.pid
  WHERE NOT blocked_locks.granted;
  ```
- **Долгие активные запросы:**
  ```sql
  SELECT pid, now() - query_start as duration, state, query 
  FROM pg_stat_activity 
  WHERE state != 'idle' AND now() - query_start > interval '5s';
  ```
- **Эффективность индексов:**
  ```sql
  SELECT relname, 100 * idx_scan / (seq_scan + idx_scan) as index_usage_pct 
  FROM pg_stat_user_tables 
  WHERE seq_scan + idx_scan > 100 ORDER BY index_usage_pct ASC;
  ```

**3. Быстрые меры:**
- `pg_terminate_backend(pid)` для критических блокировщиков.
- `ANALYZE table_name` для исправления кривого плана.
- Создание индекса `CONCURRENTLY`.

## Мониторинг

Регулярные метрики для capacity planning и раннего обнаружения деградации (подробнее — **[Наблюдаемость PostgreSQL](./observability.md)**):

```sql
-- Коэффициент попадания в кэш (с момента запуска кластера)
SELECT sum(blks_hit) AS hit, sum(blks_read) AS read,
       round(100.0 * sum(blks_hit) / nullif(sum(blks_hit) + sum(blks_read), 0), 2) AS hit_pct
FROM pg_stat_database;
-- → hit_pct > 99 для активных данных

-- Топ запросов по суммарному времени
SELECT query, calls, mean_exec_time, total_exec_time
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10;

-- Прогресс текущего VACUUM
SELECT pid, relid::regclass, phase, heap_blks_total, heap_blks_scanned
FROM pg_stat_progress_vacuum;

-- Spill на диск (временные файлы сортировок/хешей)
SELECT temp_files, pg_size_pretty(temp_bytes) FROM pg_stat_database;
```

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `shared read` доминирует над `shared hit` в EXPLAIN | Данные не помещаются в `shared_buffers` или нет индексов | Поднять `shared_buffers` (restart); добавить/перестроить индексы |
| `Sort Method: external merge`, `Disk: ...kB` | Сортировка не влезает в `work_mem` | Поднять `work_mem` для сессии/роли (`SET work_mem = '64MB';`), не глобально |
| `Batches > 1`, `Disk Usage` у Hash-узлов | Хеш-таблица не влезает в `work_mem × hash_mem_multiplier` | Поднять `hash_mem_multiplier` (2→4) вместо `work_mem` |
| В логе частые checkpoint (`checkpoints are too frequent`) | `max_wal_size` мал для нагрузки | Поднять `max_wal_size` (4-16GB), `checkpoint_timeout` (15-30min) |
| `n_dead_tup` растёт, таблицы раздуваются | Autovacuum отстаёт от нагрузки | Снизить scale factors per-table (см. сценарий 5); увеличить `autovacuum_max_workers` |
| Много `idle in transaction` | Приложение держит открытые транзакции | `idle_in_transaction_session_timeout`; исправление приложения |
| Растут `temp_files` / `temp_bytes` | Регулярный spill при сортировках/хешах | См. строки выше; проверить `temp_file_limit` |
| OOM-killer в `dmesg` | Перерасход памяти: `work_mem × max_connections`, `overcommit_memory=0` | `vm.overcommit_memory = 2`; снизить `work_mem`, `max_connections` |

## Лучшие практики

*   **Один параметр за раз:** изменяйте и замеряйте эффект на staging с реалистичной нагрузкой (`pgbench`), иначе невозможно определить причину регрессии.
*   **Контекст перед изменением:** проверьте контекст параметра (`SELECT name, context FROM pg_settings WHERE name = '...';`) — параметры `postmaster` требуют окна обслуживания с restart, `sighup` — только reload.
*   **Переопределения вместо правки файла:** `ALTER SYSTEM SET ...` (кластер), `ALTER DATABASE ... SET ...`, `ALTER ROLE ... SET ...` — иерархия ROLE > DATABASE > SYSTEM. Проверка неприменённых правок: `SELECT * FROM pg_file_settings;` (разбор без применения), применение — `SELECT pg_reload_conf();`.
*   **Не слепое копирование генераторов:** pgTune/PGConfig дают стартовую точку, но не знают вашу нагрузку — все значения из сценария 1 проверяйте на своих замерах.
*   **Autovacuum per-table:** универсальные scale factors 0.2 плохо работают и для маленьких, и для гигантских таблиц — переопределяйте хранимые параметры для аутлиеров.
*   **Статистика важнее индексов:** после массовых изменений — `ANALYZE`; кривой план чаще лечится статистикой, чем новым индексом.

## Очистка и откат

**Откат параметров:**
```sql
ALTER SYSTEM RESET work_mem;        -- снять переопределение ALTER SYSTEM
SELECT pg_reload_conf();            -- применить (sighup-параметры)
```
Для параметров `postmaster` (`shared_buffers`, `wal_buffers`, `huge_pages`) — правка `postgresql.conf` и `sudo systemctl restart postgresql`.

**Временные файлы:** счётчики `pg_stat_database.temp_files` сбрасываются перезапуском; orphaned файлы в `base/pgsql_tmp` удалять только при остановленном сервере.

**Откат `pg_stat_statements`:** убрать из `shared_preload_libraries`, restart; `DROP EXTENSION pg_stat_statements;` удаляет собранную статистику.

## Дополнительная информация

### Инструменты продвинутой оптимизации
*   **auto_explain:** логирование планов медленных запросов в `stderr` (загрузка через `shared_preload_libraries` — restart).
*   **hypopg:** гипотетические индексы (проверка влияния без создания).
*   **pg_hint_plan:** принудительное управление планом (крайняя мера).
*   **pg_stat_kcache:** статистика использования CPU и кэша ОС на уровне запроса.

### Полезные ресурсы
- **pgTune / PGConfig:** генераторы конфигурации (стартовая точка, см. «Лучшие практики»).
- **explain.depesz.com:** визуализатор планов.
- **[Full-Stack Observability](./observability.md):** настройка мониторинга.

### Связанные документы
- **[Архитектура PostgreSQL](../Concepts/architecture.md)** — глубокое описание процессов и памяти.
- **[Индексы в PostgreSQL](../Concepts/indexes.md)** — типы и применение.
- **[Управление параллелизмом](../Concepts/concurrency_and_locking.md)** — блокировки и MVCC.
- **[Журнал предзаписи (WAL)](../../Concepts/write_ahead_log.md)** — устройство логов.
