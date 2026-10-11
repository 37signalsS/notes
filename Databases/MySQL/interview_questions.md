# Вопросы на собеседовании по MySQL (общие)

**Актуально для:** MySQL 8.0.x / 8.4 LTS / 9.x Innovation

## Определения

*   **Собеседование по MySQL** — оценка знаний администрирования, оптимизации и архитектуры MySQL. Вопросы покрывают: архитектуру, InnoDB, репликацию, Group Replication, оптимизацию, безопасность, мониторинг, troubleshooting.
*   **Отличие от MariaDB-вопросов:** MySQL имеет уникальные механизмы (InnoDB Cluster, Group Replication, JSON-тип, EXPLAIN FORMAT=TREE, descending indexes, multi-valued indexes, Document Store), Thread Pool только в Enterprise/Percona, другие дефолты кодировок (utf8mb4 с 8.0). Вопросы о MariaDB-специфичных фичах (Aria, ColumnStore, Spider, системное версионирование, Ignored Indexes) в MySQL не применимы — см. **[Собеседование по MariaDB](../MariaDB/interview_questions.md)**.

## Базовые концепции

### Тематические блоки

1.  **Архитектура и движки** — SQL Layer + Storage Engine Layer, pluggable storage engine, InnoDB, MyISAM, MEMORY, Archive, MyRocks (Percona).
2.  **InnoDB** — Buffer Pool, Redo/Undo Log, Doublewrite Buffer, Change Buffer, MVCC, Adaptive Hash Index.
3.  **Репликация** — Source-Replica, GTID, semi-sync, MTS, multi-source, binlog formats.
4.  **Group Replication / InnoDB Cluster** — Paxos, сертификация, quorum, MySQL Router.
5.  **Оптимизация** — EXPLAIN, EXPLAIN ANALYZE, индексы, гистограммы, optimizer hints.
6.  **Безопасность** — caching_sha2_password, RBAC, TDE, аудит, Enterprise Firewall.
7.  **Мониторинг** — Performance Schema, sys schema, slow query log, pt-query-digest, PMM.
8.  **Troubleshooting** — deadlocks, MDL, lock waits, connection storms, corruption.

## Практические сценарии (вопросы и ответы)

### Архитектура и InnoDB

**Q: Архитектура MySQL — два уровня?**
A: SQL Layer (parser, optimizer, executor, connection manager, ACL) и Storage Engine Layer (InnoDB, MyISAM, MEMORY и др.). Оптимизатор — cost-based, выбирает план по статистике, стоимости I/O и CPU. Движки подключаются через pluggable API.

**Q: Что такое Buffer Pool и как он работает?**
A: Область RAM, где кэшируются страницы данных и индексов InnoDB. Использует модифицированный LRU для защиты от вымывания при полном сканировании (midpoint insertion). Dirty pages сбрасываются на диск Checkpointer. Размер — `innodb_buffer_pool_size` (50–75% RAM на выделенном сервере). Hit rate > 99% — цель.

**Q: Redo Log vs Undo Log?**
A: Redo Log (WAL) — журнал опережающей записи для Durability: при сбое изменения восстанавливаются из него (crash recovery). Управляется `innodb_redo_log_capacity` (8.0.30+) / `innodb_log_file_size` × `innodb_log_files_in_group` (до 8.0.30). Undo Log — хранит старые версии строк для отката транзакций и MVCC (чтение согласованных снимков). Раздувается при долгих транзакциях (`History list length`).

**Q: MVCC и уровни изоляции?**
A: MVCC (Multi-Version Concurrency Control) — чтение согласованных снимков без блокировок. Дефолт — REPEATABLE READ (Next-Key Locks, нет фантомных чтений). READ COMMITTED — Record Locks без Gap Locks (меньше дедлоков, но фантомы возможны). SERIALIZABLE — SELECT превращается в `LOCK IN SHARE MODE`.

**Q: Doublewrite Buffer?**
A: Защита от torn pages (разорванных страниц) при сбое питания. Данные сначала пишутся в doublewrite buffer, затем в основной файл. В 8.0.30+ — отдельные файлы в `#innodb_doublewrite/`.

### Репликация

**Q: Как работает GTID?**
A: GTID (Global Transaction Identifier) = `UUID:transaction_id`. Уникально идентифицирует транзакцию во всей топологии. Упрощает failover (`SOURCE_AUTO_POSITION = 1`), гарантирует отсутствие дублей. Обязателен для Group Replication. Формат: `3E11FA47-71CA-11E1-9E33-C80AA9429562:1-5`.

**Q: Binlog formats: STATEMENT vs ROW vs MIXED?**
A: STATEMENT — записывает SQL-запросы (компактно, но риск расхождений при недетерминированных функциях). ROW — записывает изменения строк (дефолт в 8.0+, точность, обязателен для GTID и Group Replication). MIXED — автоматический выбор. Для production — ROW.

**Q: Полусинхронная репликация — что гарантирует?**
A: Источник ждёт подтверждения записи в relay log хотя бы от одной реплики перед коммитом. Защищает от потери данных при отказе источника. НЕ гарантирует применения на реплике (ACK после записи в relay log, до применения в таблицы). Не замена бэкапам.

**Q: Параллельная репликация (MTS)?**
A: `slave_parallel_workers` (до 8.0.26) / `replica_parallel_workers`. Режимы: `DATABASE` (параллельно по схемам), `LOGICAL_CLOCK` (параллельно по логическим часам group commit; write-set — уточнение зависимостей на источнике, `binlog_transaction_dependency_tracking=WRITESET`). Ускоряет применение на реплике при высокой записи. Детали — `replication/parallel_replication_mts.md`.

### Group Replication / InnoDB Cluster

**Q: Как работает Group Replication?**
A: Синхронная репликация на базе Paxos. Транзакция выполняется на узле, write set отправляется группе, каждый узел проверяет на конфликты (certification), при успехе — коммит на всех. Режимы: single-primary (один writer, остальные read-only) и multi-primary (все пишут, сертификация конфликтов). RPO ≈ 0. Кворум: `floor(N/2)+1` (минимум 3 узла).

**Q: InnoDB Cluster — что это?**
A: Комплексное HA-решение: Group Replication (данные) + MySQL Router (прозрачный failover, маршрутизация read-write/read-only) + MySQL Shell (администрирование, `dba.createCluster()`). MySQL Router читает метаданные кластера через X Protocol (порт 33060) и автоматически переключает трафик.

**Q: Split-Brain в Group Replication?**
A: Предотвращается сертификацией транзакций и кворумом Paxos. При потере кворума (partition) узлы в minority переходят в состояние, не принимающее запись. Группа из 2 узлов не формирует кворум при потере одного — минимум 3 узла.

### Оптимизация

**Q: Как диагностировать медленный запрос?**
A: `EXPLAIN` / `EXPLAIN FORMAT=TREE` — план; `EXPLAIN ANALYZE` (8.0.18+) — реальные метрики (actual rows, time); slow query log + `pt-query-digest` — топ запросов; Performance Schema `events_statements_summary_by_digest`; проверить `type = ALL` (full scan), `Using filesort`, `Using temporary`, `Using index condition` (ICP).

**Q: Чем EXPLAIN отличается от EXPLAIN ANALYZE?**
A: `EXPLAIN` — оценка плана без выполнения. `EXPLAIN ANALYZE` — выполняет запрос и показывает реальное время и количество строк на каждом узле. `EXPLAIN FORMAT=TREE` (8.0.16+) — древовидное представление плана. `EXPLAIN FORMAT=JSON` — расширенный JSON.

**Q: Что такое гистограммы?**
A: Статистика распределения значений столбца для оценки селективности неравенств. Создаются: `ANALYZE TABLE ... UPDATE HISTOGRAM ON col WITH 100 BUCKETS`. Хранятся в `mysql.column_stats`. Важны для столбцов с перекошенным распределением (data skew).

**Q: Invisible Index — зачем?**
A: Индекс существует и обслуживается при записи, но оптимизатор его не использует. Позволяет безопасно проверить необходимость индекса в production без блокировок: `ALTER TABLE t ALTER INDEX idx INVISIBLE`. Перед `DROP INDEX` — перевести в INVISIBLE и проверить план.

**Q: Skip Scan?**
A: Стратегия доступа (8.0.13+), позволяющая использовать составной индекс, когда левый префикс отсутствует в WHERE. Эффективен для колонок с низкой кардинальностью. В EXPLAIN — `type = index` или `range` с `key = idx_abc`.

### Безопасность

**Q: Плагины аутентификации в MySQL 8.x?**
A: `caching_sha2_password` (дефолт с 8.0, SHA-256 с кэшем), `mysql_native_password` (legacy, отключён по умолчанию в 8.4, удалён в 9.0), `sha256_password` (требует TLS или RSA). Для совместимости старых клиентов — включить `mysql_native_password` явно.

**Q: TDE (Transparent Data Encryption)?**
A: Шифрование данных at-rest (табличные пространства InnoDB). Ключи управляются через keyring (component_keyring_file — Community, keyring_hashicorp/keyring_okv — Enterprise). Двухуровневая иерархия: master key → tablespace keys. Не защищает error log, slow log, swap.

**Q: MySQL Enterprise Firewall?**
A: Application-level firewall (Enterprise Edition only). Разрешает/запрещает SQL-операторы по allowlist паттернов. Режимы: RECORDING (обучение), PROTECTING (блокировка), DETECTING (только логирование). Плагины: MYSQL_FIREWALL, MYSQL_FIREWALL_USERS, MYSQL_FIREWALL_WHITELIST. Защита от SQL-инъекций — defense-in-depth, не замена параметризованным запросам.

### Мониторинг и troubleshooting

**Q: Как мониторить MySQL в production?**
A: Prometheus + mysqld_exporter (метрики), Grafana (дашборды), алерты (Threads_connected, buffer pool hit rate, replication lag, Threads_running), slow query log + pt-query-digest, Performance Schema, sys schema. Методология USE (Utilization, Saturation, Errors). PMM (Percona Monitoring and Management) — QAN для анализа запросов.

**Q: Too many connections (1040) — что делать?**
A: Найти утечки соединений (`SHOW PROCESSLIST` — много Sleep), сократить `wait_timeout`, настроить connection pooling (ProxySQL), увеличить `max_connections` с запасом. В Percona — включить Thread Pool. Увеличение `max_connections` без пула усугубляет проблему (per-thread память).

**Q: Deadlock (1213) — что делать?**
A: Приложение должно повторить транзакцию (retry). Диагностика: `SHOW ENGINE INNODB STATUS` (LATEST DETECTED DEADLOCK), `sys.innodb_lock_waits`, `innodb_print_all_deadlocks = ON` (полная история в error log). Профилактика: короткие транзакции, упорядоченный доступ к строкам, индексы, READ COMMITTED для очередей (отключает Gap Locks).

**Q: MDL (Metadata Lock) — что это?**
A: Блокировка на уровне словаря данных, предотвращающая DDL, пока идёт DML/SELECT. Проблема: долгий SELECT удерживает Shared MDL → ALTER TABLE встаёт в очередь на Exclusive MDL → все последующие SELECT встают за ALTER → исчерпание пула соединений. Диагностика: `performance_schema.metadata_locks`, `sys.schema_table_lock_waits`. Решение: `KILL` долгого запроса, `lock_wait_timeout` (дефолт 1 год — ограничивать сессионно перед DDL).

**Q: Как найти неиспользуемые индексы?**
A: `sys.schema_unused_indexes` или Performance Schema `table_io_waits_summary_by_index_usage` (COUNT_STAR = 0). Перед удалением — перевести в INVISIBLE и проверить план.

## Устранение неполадок (Troubleshooting)

### Как подготовиться к собеседованию

1.  **Практика:** настройте MySQL в Docker, выполните EXPLAIN ANALYZE, создайте репликацию с GTID.
2.  **Документация:** dev.mysql.com/doc/refman/8.4/en/ — официальная документация.
3.  **Отличия MariaDB:** знайте, что есть в MySQL, но нет в MariaDB (и наоборот).
4.  **Версии:** знайте LTS-версии (8.0, 8.4) и ключевые фичи каждой.

## Лучшие практики (Best Practices)

1.  **Знайте отличие MySQL от MariaDB** — ключевой вопрос на собеседовании.
2.  **Практический опыт:** EXPLAIN ANALYZE, репликация с GTID, Group Replication — настраивайте в лабе.
3.  **Терминология:** Source/Replica (не Master/Slave), `SHOW REPLICA STATUS`, `START REPLICA`.
4.  **Версии:** LTS-линии (8.0, 8.4) и их фичи.
5.  **Для репликации:** специализированные вопросы в MariaDB-версии — **[Репликация: собеседование](../MariaDB/replication/interview_questions.md)**; по MySQL механизмы разобраны в **[Репликация](replication/overview.md)** и **[Параллельная репликация](replication/parallel_replication_mts.md)**.

## Дополнительная информация

### См. также

*   **[Обзор MySQL](overview.md)** — архитектура и возможности.
*   **[Индексы](indexing.md)** — типы индексов, Skip Scan, Invisible.
*   **[Блокировки и дедлоки](locking_and_deadlocks.md)** — MDL, Next-Key, диагностика.
*   **[Репликация](replication/overview.md)** — GTID, binlog, MTS.
*   **[Высокая доступность](high_availability.md)** — Group Replication, InnoDB Cluster.
*   **[Мониторинг](monitoring.md)** — Prometheus, PMM, алертинг.
*   **[Хранимые объекты: собеседование](../Concepts/stored_objects/interview_questions.md)** — процедуры, функции, триггеры, события.
*   **[MariaDB: собеседование](../MariaDB/interview_questions.md)** — вопросы по MariaDB.

### Внешние ресурсы

*   [MySQL 8.4 Reference Manual](https://dev.mysql.com/doc/refman/8.4/en/)
*   [MySQL Interview Questions](https://dev.mysql.com/doc/refman/8.4/en/)
