# PostgreSQL: вопросы и ответы для собеседования (DevOps / SRE / Sysadmin)

**Актуально для:** PostgreSQL 14–18

## Определения

*   **Q&A-шпаргалка** — сборник типовых вопросов с короткими ответами и ссылками на глубокий разбор в тематических файлах; не заменяет практики, а проверяет её.
*   **Операционный вопрос** — вопрос про эксплуатацию (бэкап, failover, тюнинг), а не про написание запросов: фокус этого файла.
*   **Короткий ответ** — 2–5 строк: суть + ключевой параметр/команда; детали — по ссылке.

## Базовые концепции

### Как устроен вопросник

Интервьюер проверяет три слоя:

1.  **Архитектура** — как работает PostgreSQL внутри (процессы, MVCC, WAL).
2.  **Эксплуатация** — что делать в production (бэкап, failover, тюнинг, инциденты).
3.  **Сценарии** — «что будет, если…» и «как диагностировать…».

Правило ответа: **сначала суть, потом параметр/команда, потом границы применимости**. Например: «`VACUUM` освобождает место внутри таблицы для переиспользования, но не уменьшает файл; для сжатия — `pg_repack` или `REPACK` (PG 19)».

## Практические сценарии

### Архитектура и MVCC

**Q: Чем PostgreSQL отличается от MySQL по модели процессов?**
Process-per-connection: каждое соединение — отдельный процесс (не поток). При сотнях/тысячах клиентов — оверхед на форк и память; решение — пулер (PgBouncer/Pgpool-II). [Архитектура](./Concepts/architecture.md)

**Q: Что такое MVCC и почему читатели не блокируют писателей?**
Каждое изменение создаёт новую версию строки; старая помечается «мёртвой» (dead tuple). Читатели видят снапшот, писатели пишут новую версию — блокировок чтения нет. Мёртвые кортежи чистит `VACUUM`. [Concurrency and Locking](./Concepts/concurrency_and_locking.md)

**Q: Что такое WAL и зачем он?**
Write-Ahead Log: изменения сначала пишутся в последовательный журнал (`pg_wal`), потом — в файлы данных. Обеспечивает Durability при сбое питания и лежит в основе репликации и PITR. [WAL](../Concepts/write_ahead_log.md)

**Q: Что такое чекпоинт и как он влияет на производительность?**
Момент сброса «грязных» страниц из `shared_buffers` на диск. Частые чекпоинты — больше I/O записи; редкие — дольше recovery. Баланс: `max_wal_size`, `checkpoint_timeout`, `checkpoint_completion_target`. [Performance tuning](./Operations/performance_tuning.md)

**Q: Что такое Transaction ID Wraparound?**
Исчерпание 32-битного пространства XID (~2 млрд транзакций): база отказывает в записи. Защита — `VACUUM` (freezing старых XID), мониторинг `datfrozenxid`. [VACUUM internals](./Concepts/vacuum_internals.md)

### Типы данных и целостность

**Q: `timestamp` или `timestamptz`?**
Всегда `timestamptz` для моментов событий: хранит абсолютный момент (UTC), отображение зависит от `timezone` сессии. `timestamp` — только для «наивных» понятий (расписание). Конвертация — `AT TIME ZONE`. [Timezone handling](./Concepts/timezone_handling.md)

**Q: Чем `now()` отличается от `clock_timestamp()`?**
`now()`/`CURRENT_TIMESTAMP` — время **начала транзакции** (фиксировано внутри транзакции); `clock_timestamp()` — реальное текущее время. Для `DEFAULT updated_at` все строки одной транзакции получат одинаковую метку от `now()`. [Timezone handling](./Concepts/timezone_handling.md)

**Q: Зачем массивы и range-типы?**
Массивы — набор значений в одной колонке (`ANY`, `@>`, GIN-индекс); range-типы (`tstzrange`, `int4range`) — интервалы с операторами пересечения `&&`, `@>`, GiST-индекс. Классика: бронирования без пересечения через `EXCLUDE`. [Arrays and ranges](./Concepts/arrays_and_ranges.md)

**Q: Что такое EXCLUSION constraint?**
Обобщение UNIQUE: гарантирует, что для любых двух строк хотя бы одно сравнение ложно. Требует GiST (расширение `btree_gist` для смешения `=` и range-операторов). Атомарная защита от пересечения интервалов — без race condition, в отличие от триггера. [Constraints](./Concepts/constraints.md)

**Q: Как добавить CHECK/FK на горячей таблице без простоя?**
Двумя шагами: `ADD CONSTRAINT ... NOT VALID` (мгновенно, проверяет только новые строки) → `VALIDATE CONSTRAINT` (сканирует существующие под `SHARE UPDATE EXCLUSIVE`, не блокируя чтение). [Constraints](./Concepts/constraints.md)

**Q: Что такое DEFERRABLE constraint?**
Проверка откладывается до `COMMIT` (`INITIALLY DEFERRED`) или может быть отложена явно (`SET CONSTRAINTS ALL DEFERRED`). Нужно для циклических FK и перестановки уникальных значений в одном `UPDATE`. [Constraints](./Concepts/constraints.md)

### Бэкапы и восстановление

**Q: Чем `pg_dump` отличается от `pg_basebackup`?**
`pg_dump` — логический дамп (SQL/COPY), переносимость между версиями, медленное восстановление, нет PITR. `pg_basebackup` — физическая побайтовая копия кластера, быстрое восстановление, только та же мажорная версия, основа для PITR и реплик. [Backup and recovery](./Concepts/backup_and_recovery.md)

**Q: Что такое PITR?**
Point-in-Time Recovery: восстановление base backup + replay WAL-архива до произвольной точки времени. Требует `archive_mode = on` и `wal_level = replica`. [Backup and recovery](./Concepts/backup_and_recovery.md)

**Q: Почему `pg_dump` не подходит для PITR?**
Дамп — снапшот на момент начала; он не содержит журнала изменений. PITR требует непрерывный поток WAL-сегментов. [Backup and recovery](./Concepts/backup_and_recovery.md)

**Q: Как восстановить одну таблицу после `DROP TABLE`?**
Напрямую нельзя: PITR восстанавливает весь кластер в отдельный каталог до точки до ошибки, оттуда таблицу выгружают и загружают в production. [DR-runbook](./Operations/disaster_recovery.md#сценарий-логическая-ошибка-drop-table-update-без-where)

**Q: Как проверить, что бэкап рабочий?**
Только восстановлением: поднять кластер из бэкапа + WAL на стенде, прогнать smoke-тест. Бэкап без проверенного восстановления не является бэкапом. [Backup validation](../Concepts/backup_validation.md)

### Репликация и HA

**Q: Чем физическая репликация отличается от логической?**
Физическая (streaming) — побайтовая передача WAL, весь кластер, та же мажорная версия. Логическая — изменения отдельных таблиц/строк, между разными мажорными версиями, выборочная. [Replication](../Concepts/replication.md)

**Q: Что такое replication slot и чем он опасен?**
Механизм, гарантирующий, что WAL не удаляется до передачи подписчику. Неактивный слот удерживает WAL до заполнения диска — защита `max_slot_wal_keep_size`, мониторинг `pg_replication_slots`. [Replication](../Concepts/replication.md)

**Q: Как измерить лаг репликации?**
На Primary: `pg_stat_replication` (`replay_lag`, `write_lag`, `flush_lag`). На Standby: `pg_last_xact_replay_timestamp()`. Алерты при `replay_lag > 30s` (порог по SLO). [Observability](./Operations/observability.md)

**Q: Что делает `pg_rewind`?**
Быстро возвращает бывший Primary в кластер как replica после failover без полной перебазы (если он не повреждён). [Replication](../Concepts/replication.md)

**Q: Как устроен failover в Patroni?**
DCS (etcd/Consul) хранит лидера; при недоступности Primary узлы голосуют, standby делает `promote`, HAProxy переключает трафик. Нечётное число узлов (3+3) для кворума; split-brain предотвращается кворумом DCS. [High Availability](./Concepts/high_availability.md)

**Q: Синхронная vs асинхронная репликация?**
Асинхронная: нет потерь производительности, но возможна потеря записей при failover. Синхронная: нулевые потери (RPO=0) ценой роста latency коммита. [Replication](../Concepts/replication.md)

**Q: Как устроен cross-region DR для PostgreSQL?**
Три уровня: WAL-архив offsite (RPO минуты, RTO часы), async standby в другом регионе (RPO секунды, RTO минуты — promote), sync standby между регионами (RPO=0, но latency коммита +RTT — почти всегда неоправдан). Стандарт: async standby + WAL offsite. [Cross-region DR](./Concepts/cross_region_dr.md)

**Q: Зачем chaos engineering для базы данных?**
Контролируемые инъекции отказов (kill бэкенда/postmaster, заполнение диска, `tc netem`, connection storm) на staging проверяют устойчивость и алерты. Правила: гипотеза и steady state до старта, минимальный blast radius, автооткат, один фактор. [Chaos Engineering](./Operations/chaos_engineering.md)

### Производительность и тюнинг

**Q: Какие параметры памяти настраивают первыми?**
`shared_buffers` ≈ 25% RAM; `effective_cache_size` ≈ 75% RAM; `work_mem` — на операцию (считать бюджет `work_mem × max_connections`); `maintenance_work_mem` 1–2 GB. [Performance tuning](./Operations/performance_tuning.md)

**Q: Почему `random_page_cost = 4.0` плохо на SSD/NVMe?**
Константа издержки случайного чтения под HDD. На SSD/NVMe — `1.1–1.5`, иначе планировщик избегает индексов. Можно задать на уровне tablespace. [Planner internals](./Concepts/planner_internals.md)

**Q: Что такое bloat и как с ним бороться?**
Раздувание таблиц/индексов мёртвыми кортежами. `VACUUM` освобождает место внутри файла, но не сжимает его; сжатие — `pg_repack` (или `REPACK` в PG 19). Профилактика: autovacuum tuning per-table. [VACUUM internals](./Concepts/vacuum_internals.md)

**Q: Как понять, что autovacuum отстаёт?**
`pg_stat_user_tables`: растёт `n_dead_tup`, стареет `last_autovacuum`. Решение: `autovacuum_vacuum_scale_factor = 0.01–0.05` для больших таблиц, `autovacuum_vacuum_cost_limit = 1000–2000`. [VACUUM internals](./Concepts/vacuum_internals.md)

**Q: Что показывает `EXPLAIN (ANALYZE, BUFFERS)`?**
Реальный план: `actual time` vs оценка (разрыв — устаревшая статистика), `Buffers: shared hit/read` (попадание в кэш vs диск), `Batches > 1` в Sort/Hash (не хватает `work_mem`). [Performance tuning](./Operations/performance_tuning.md)

**Q: Зачем `pg_stat_statements` и как его включить?**
Статистика по запросам (вызовы, время, строки): `shared_preload_libraries = 'pg_stat_statements'` (restart) + `CREATE EXTENSION`. Top по `total_exec_time` — первый источник для оптимизации. [Extensions utility](./Concepts/extensions_utility.md)

**Q: Что такое JIT и когда его выключать?**
JIT-компиляция выражений для тяжёлых запросов. На OLTP — источник бесполезного CPU на планировании: `jit = off`; на аналитике — `jit = on`. [Planner internals](./Concepts/planner_internals.md)

**Q: Что настраивать в Linux под PostgreSQL?**
THP = `never`; huge pages (`vm.nr_hugepages` + `huge_pages = on`) при больших `shared_buffers`; NUMA (`numactl --interleave=all`); `vm.overcommit_memory = 2` с расчётом; `swappiness = 1`; cgroups-лимиты. Всё — по замерам, не «по статье». [Linux tuning](./Operations/linux_tuning.md)

**Q: Какой каденс обслуживания PostgreSQL?**
Autovacuum/ANALYZE — непрерывно (не по расписанию). Daily — мониторинг dead tuples/wraparound; weekly — `REINDEX CONCURRENTLY` по bloat-отчёту, `REFRESH MATERIALIZED VIEW`; monthly — restore-test бэкапа. `pg_cron` — для SQL-задач, системный cron — для `pg_dump`/`pg_basebackup`. [Maintenance automation](./Operations/maintenance_automation.md)

### Аудит и профилирование

**Q: Что такое event triggers и чем они отличаются от обычных?**
Обычный триггер — на DML строк таблицы; event trigger — на серверные события DDL (`ddl_command_start/end`, `sql_drop`, `table_rewrite`). Применение: аудит DDL в таблицу, запрет `DROP`, защита горячих таблиц от `ALTER`. [Event triggers](./Concepts/event_triggers.md)

**Q: Чем `pg_qualstats` отличается от `pg_stat_statements`?**
`pg_stat_statements` — статистика по запросам целиком; `pg_qualstats` — статистика по **предикатам** (какие условия, сколько раз, сколько строк отфильтровано) — источник для рекомендаций индексов. [Query profiling](./Concepts/query_profiling.md)

**Q: Что такое `pgsi` и `pg_store_plans`?**
`pgsi` (PostgreSQL Suggest Indexes) — анализирует `pg_qualstats` и предлагает частичные индексы; `pg_store_plans` — хранит исторические планы по `queryid` (как план менялся со временем). `pg_profile` — снапшоты и отчёты по нагрузке (аналог AWR). [Query profiling](./Concepts/query_profiling.md)

### SQL: базовые конструкции

**Q: Какие виды JOIN знаешь?**
Inner — только совпадения в обеих таблицах. Left — все строки левой + NULL там, где справа нет совпадения. Right — симметрично Left. Full outer — объединение обоих наборов. Cross — декартово произведение (каждая строка с каждой). Self join — таблица соединяется сама с собой (иерархии, сравнение строк). Важно: порядок таблиц в `FROM` не влияет на результат для Inner/Full, но важен для Left/Right.

### Блокировки и конкурентность

**Q: Что такое deadlock и как его предотвратить?**
Взаимная блокировка транзакций; PostgreSQL детектирует автоматически (`deadlock_timeout`, дефолт 1s) и прерывает одну. Предотвращение: единый порядок обновления таблиц/строк; приложение умеет повторять транзакцию. [Concurrency and Locking](./Concepts/concurrency_and_locking.md)

**Q: Чем `statement_timeout`, `lock_timeout`, `idle_in_transaction_session_timeout`?**
Лимиты: на оператор, на ожидание блокировки, на сессию в состоянии `idle in transaction`. Ни один не включён по умолчанию — настраивать на ролях. [Connection management](./Operations/connection_management.md)

**Q: Что такое advisory locks?**
Рекомендательные блокировки приложения (`pg_advisory_lock`): быстрее флага в таблице, не создают bloat, автоматически снимаются в конце сессии. [Concurrency and Locking](./Concepts/concurrency_and_locking.md)

**Q: Что такое SSI и Serializable?**
Serializable Snapshot Isolation: уровень изоляции Serializable без блокировок чтения; конфликты обнаруживаются как `40001 serialization_failure` — приложение повторяет транзакцию. [Concurrency and Locking](./Concepts/concurrency_and_locking.md)

### Наблюдаемость

**Q: Что такое wait events?**
Причина, по которой процесс сейчас не работает: `wait_event_type` + `wait_event` в `pg_stat_activity` (`IO`, `Lock`, `LWLock`, `Client`, `Timeout`). Дешёвый способ отличить проблему диска от конкуренции за блокировки. [Observability](./Operations/observability.md)

**Q: Как найти блокирующую сессию?**
`pg_locks WHERE NOT granted` + `pg_blocking_pids()` + `pg_stat_activity` — кто кого блокирует и каким оператором. [Troubleshooting runbook](./Operations/troubleshooting_runbook.md)

**Q: Какие метрики в минимальном дашборде?**
Доступность, число соединений, самая долгая транзакция, блокировки, лаг репликации и слоты, cache hit ratio, чекпоинты, WAL-архивация, deadlocks, autovacuum. [Observability](./Operations/observability.md#базовые-метрики-здоровья-минимальный-дашборд)

**Q: Как ловить медленные запросы в лог?**
`log_min_duration_statement = 1000` (мс) — оператор попадает в лог; анализ — pgbadger. [Observability](./Operations/observability.md)

**Q: Пользователи жалуются, что база «тормозит». С чего начнешь диагностику?**
Правильный ответ — не лезть в конфиг, а собрать факты. Методика (сверху вниз):
1.  **Встречные вопросы**: Всё медленно или одна страница? Когда началось? Что менялось (выкатка, рост нагрузки, новый отчёт)? Половина оценки — здесь.
2.  **Инфраструктура (Node Exporter / `htop` / `iostat`)**: CPU, RAM, диск (iowait, `%util`, `await`), сеть. Частая причина — забитый диск или throttling.
3.  **Соединения**: `pg_stat_activity` — число активных/idlе, не превышен ли `max_connections`. Тысячи соединений без пулера — типичная проблема.
4.  **Блокировки**: `pg_locks` + `pg_blocking_pids()` — кто кого блокирует. Отдельно — `idle in transaction`: открытая брошенная транзакция, держит локи и мешает autovacuum.
5.  **Тяжёлые запросы**: `pg_stat_statements` — ищем не самый долгий, а самый дорогой суммарно (`total_exec_time`). Запрос на 20 мс × 100k/min вреднее отчёта на 1 мин × 1/день.
6.  **План запроса**: `EXPLAIN (ANALYZE, BUFFERS)` — Seq Scan вместо Index Scan, неверные оценки строк, `Batches > 1` в Sort/Hash (мало `work_mem`).
7.  **Bloat и autovacuum**: `pg_stat_user_tables` — растут `n_dead_tup`, стареет `last_autovacuum`. Таблицы раздулись от мёртвых кортежей, autovacuum не успевает. Настройка per-table: `autovacuum_vacuum_scale_factor = 0.01–0.05`, `autovacuum_vacuum_cost_limit = 1000–2000`.
8.  **Настройки памяти/обслуживания**: Только в конце — `shared_buffers`, `work_mem`, `maintenance_work_mem`, `autovacuum_*`, чекпоинты.

Главный вывод: виновата почти всегда не «база медленная», а 1–2 конкретных запроса без индекса или перебор соединений. [Troubleshooting runbook](./Operations/troubleshooting_runbook.md), [Performance tuning](./Operations/performance_tuning.md), [VACUUM internals](./Concepts/vacuum_internals.md)

### Безопасность

**Q: Что такое `pg_hba.conf`?**
Host-Based Authentication: правила «кто откуда к какой базе как аутентифицируется». Дефолт для TCP — `scram-sha-256` (MD5 deprecated в PG 18). [Security and encryption](./Concepts/security_and_encryption.md)

**Q: Что такое RLS?**
Row-Level Security: политики доступа на уровне строк (`CREATE POLICY`); применяются при `FORCE ROW LEVEL SECURITY` и для владельца — с ` FORCE`. [Security and encryption](./Concepts/security_and_encryption.md)

**Q: Поддерживает ли PostgreSQL TDE?**
Нативно — нет. Прозрачное шифрование данных — расширение `pg_tde` (Percona) или шифрование на уровне ОС/диска. TLS для соединений — штатно. [Security and encryption](./Concepts/security_and_encryption.md)

**Q: Как ротировать TLS-сертификат без простоя?**
Подложить новый cert/key, `systemctl reload postgresql` (сервер перечитывает сертификаты; ошибка reload не роняет сервер). Существующие сессии живут на старом сертификате до переподключения. Passphrase на ключе отключает reload — использовать `ssl_passphrase_command`. [Security and encryption](./Concepts/security_and_encryption.md)

**Q: Что такое роль `pg_monitor`?**
Предопределённая роль для мониторинга (`pg_read_all_settings`, `pg_read_all_stats`, `pg_stat_scan_tables`) — мониторинг не от суперпользователя. [Observability](./Operations/observability.md)

### Эксплуатация: апгрейд и миграции

**Q: Как обновить мажорную версию с минимальным простоем?**
Три пути: `pg_upgrade` (минуты, полный простой, in-place), dump/restore (медленно), логическая репликация на новый кластер (секунды простоя на cutover). [Zero-downtime migration](./Operations/zero_downtime_migration.md), [pg_upgrade](./Operations/pg_upgrade.md)

**Q: Что переносит `pg_upgrade` и что нет?**
Переносит файлы данных и (PG 18+) основную статистику оптимизатора. Не переносит: `CREATE STATISTICS`, статистику расширений; расширения нужно установить в новом кластере. После апгрейда — `vacuumdb --all --analyze-in-stages --missing-stats-only`, затем `--analyze-only`. [pg_upgrade](./Operations/pg_upgrade.md)

**Q: Что такое expand-contract при миграциях?**
Паттерн DDL без простоя: сначала аддитивное изменение (новая колонка/таблица), миграция данных, переключение записи, удаление старого. [Schema migrations](./Concepts/schema_migrations.md)

**Q: Чем PgBouncer отличается от Pgpool-II?**
PgBouncer — специализированный пулер с тремя режимами: **session** (соединение закрепляется за клиентом на всю сессию — мало пользы), **transaction** (соединение выдаётся на время транзакции — основной рабочий режим), **statement** (на один запрос — редко). Pgpool-II — middleware: пул + балансировка read + failover + (опционально) репликация. [PgBouncer](./Operations/pgbouncer_setup.md), [Pgpool-II](./Operations/pgpool.md)

**Q: Что делать, если `max_connections` исчерпан?**
Сначала пулер (PgBouncer), потом `max_connections` (restart); резерв `superuser_reserved_connections`/`reserved_connections` для админов и мониторинга. [Connection management](./Operations/connection_management.md)

## Лучшие практики

1.  **Отвечать структурой**: суть → параметр/команда → границы применимости.
2.  **Знать дефолты**: `deadlock_timeout` 1s, `shared_buffers` 128MB, `work_mem` 4MB, `max_connections` 100, `random_page_cost` 4.0.
3.  **Знать, что не включено по умолчанию**: все таймауты (`statement_timeout`, `idle_in_transaction_session_timeout`, `lock_timeout`), `log_lock_waits` (до PG 19).
4.  **Связывать тему с файлом**: «детали — в соответствующем файле раздела» показывает системное мышление.
5.  **Не путать `VACUUM` и сжатие**: `VACUUM` не уменьшает файл — это классический вопрос-ловушка.
6.  **Не путать `pg_dump` и PITR**: `pg_dump` не даёт PITR — второй классический вопрос-ловушка.

## Дополнительная информация

*   [Обзор PostgreSQL](./overview.md) — точка входа в раздел
*   [Диагностический runbook](./Operations/troubleshooting_runbook.md) — разбор инцидентов
*   [Оптимизация производительности](./Operations/performance_tuning.md) — тюнинг
*   [Бэкап и восстановление](./Concepts/backup_and_recovery.md) — PITR
*   [High Availability](./Concepts/high_availability.md) — Patroni, failover
*   [Коды ошибок](./Concepts/error_codes.md) — SQLSTATE
*   [Хранимые объекты: собеседование](../Concepts/stored_objects/interview_questions.md) — процедуры, функции, триггеры, события
*   [Технические вопросы на собеседовании](../../Interview_and_Work/Interview/Технические_вопросы.md) — общая методика
*   [Официальная документация](https://www.postgresql.org/docs/current/)

### Q: Надо ли вам настройку индексов, копирования, трешинг — что из этого в зоне ответственности DevOps/SRE?

**Тип ответа:** разделение ответственности между DevOps/SRE и DBA.

**Рекомендуемый ответ:**
> В идеале этим должен заниматься DBA, поэтому если не знаете про базу данных, можете сказать, что это не ваша самоизвестность. Этим занимался DB.

**Ключевые элементы ответа, которые стоит продемонстрировать:**
- Понимание, что **настройка индексов, репликации, тюнинг производительности** — это зона **DBA** (Database Administrator), а не SRE/DevOps.
- SRE/DevOps отвечает за: **доступность** PostgreSQL (развертывание, HA, бэкапы, восстановление, мониторинг, обновление), **инфраструктуру** (диск, память, сеть), **интеграцию** (Kubernetes-операторы, секреты, подключения).
- Честность: если кандидат не знает про БД — лучше честно сказать, чем inventировать. Это показывает зрелость и понимание границ компетенций.
- Практический совет: DevOps может диагностировать проблемы на уровне ОС (I/O, память, сеть) и перекинуть на DBA issues на уровне БД (long transactions, dead tuples, бэкапы).

**Чего избегать:** пытаться показать эксперта по БД, если таковым не являешься. Ответ должен демонстрировать понимание, где заканчивается зона ответственности DevOps/SRE и начинается DBA.

## Каверзные и бонусные вопросы

### Q: Что происходит под капотом у `SELECT`?

Это вопрос, который проверяет глубину понимания движка. Ожидаемый ответ — пошаговый путь запроса:

1.  **Парсинг** (parse analysis): SQL → дерево разбора (parse tree). Проверка синтаксиса, разрешение имен таблиц/колонок, проверка прав доступа.
2.  **Планирование** (planner/optimizer): Дерево разбора → план выполнения (plan tree). Планировщик строит альтернативы (Seq Scan, Index Scan, Join методы), оценивает стоимость (cost model) через статистику (`pg_statistic`), выбирает минимальный cost. Ключевые параметры: `enable_*`, `random_page_cost`, `geqo_threshold`, `join_collapse_limit`.
3.  **Переписывание** (rewrite): Применение правил (rules), раскрытие VIEW, RLS-политики, `INSTEAD` triggers.
4.  **Исполнение** (executor): План → итераторы (Executor nodes). Каждый узел — `ExecInitNode` / `ExecProcNode` / `ExecEndNode`. Читает страницы из `shared_buffers` (или диск → `shared_buffers`), применяет квалификации (qual), проекции, JOIN-логику (Nested Loop / Hash / Merge), агрегацию, сортировку. Результат возвращается клиенту по порциям (tuple stream).
5.  **Параллелизм** (parallel query): При включённом `max_parallel_workers_per_gather` > 0 и подходящем плане — `Gather (Merge)` собирает результаты от фоновых рабочих процессов.

Дополнительно можно упомянуть: JIT-компиляция (PG 11+), `EXPLAIN (ANALYZE, BUFFERS, SETTINGS)` для диагностики, `pg_stat_statements` для агрегированной статистики.
