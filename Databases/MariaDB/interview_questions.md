# Вопросы на собеседовании по MariaDB (общие)

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **Собеседование по MariaDB** — оценка знаний администрирования, оптимизации и архитектуры MariaDB. Вопросы покрывают: архитектуру, движки, репликацию, Galera, оптимизацию, безопасность, мониторинг, troubleshooting.
*   **Отличие от MySQL-вопросов:** MariaDB имеет уникальные движки (Aria, MyRocks, ColumnStore, Spider), Thread Pool во всех редакциях, системное версионирование, Ignored Indexes, другие дефолты кодировок. Вопросы о MySQL-специфичных фичах (InnoDB Cluster, Group Replication, JSON-тип, EXPLAIN FORMAT=TREE) в MariaDB не применимы.

## Базовые концепции

### Тематические блоки

1.  **Архитектура и движки** — pluggable storage engine, InnoDB, Aria, MyRocks, ColumnStore, Spider.
2.  **Репликация** — Source-Replica, GTID, semi-sync, multi-source, parallel replication.
3.  **Galera Cluster** — wsrep, certification, quorum, SST/IST, Flow Control.
4.  **Оптимизация** — EXPLAIN, ANALYZE, индексы, гистограммы, query optimization.
5.  **Безопасность** — аутентификация, RBAC, шифрование, TDE, аудит.
6.  **Мониторинг** — Prometheus, Performance Schema, sys schema, slow query log.
7.  **Troubleshooting** — deadlocks, lock waits, connection storms, corruption.

## Практические сценарии (вопросы и ответы)

### Архитектура и движки

**Q: В чём отличие MariaDB от MySQL?**
A: MariaDB — форк MySQL (2010, M. Widenius). Отличия: pluggable движки (Aria, MyRocks, ColumnStore, Spider), Thread Pool во всех редакциях (в MySQL — Enterprise only), системное версионирование (10.3+), Ignored Indexes (10.6+), дефолтная кодировка latin1 → utf8mb4 (11.6+), другие дефолты collation. Совместимость высокая, но не 100% (GTID, аутентификация, JSON-тип).

**Q: Какие движки хранения есть в MariaDB? Когда какой использовать?**
A: InnoDB (по умолчанию, транзакции, FK), Aria (crash-safe, системные таблицы, замена MyISAM), MyRocks (LSM-tree, высокое сжатие, SSD, нет FK), ColumnStore (OLAP, колоночное, MPP), Spider (шардирование), MEMORY (временные данные), Archive (логи). Выбор: OLTP → InnoDB; аналитика → ColumnStore; сжатие → MyRocks.

**Q: Что такое Aria?**
A: Crash-safe движок, замена MyISAM для системных таблиц. Поддерживает транзакционные логи (aria_log), crash recovery. Используется для внутренних временных таблиц (on-disk) с 10.5+.

### Репликация

**Q: Как работает GTID в MariaDB?**
A: GTID = `domain-id-server-id:sequence`. Уникально идентифицирует транзакцию. Упрощает failover (`CHANGE REPLICATION SOURCE TO SOURCE_USE_GTID=slave_pos`). С 10.10 GTID по умолчанию для новых реплик. `gtid_strict_mode = ON` рекомендуется.

**Q: Полусинхронная репликация: AFTER_SYNC vs AFTER_COMMIT?**
A: `AFTER_SYNC` (рекомендуется): source записывает в движок и binlog, ждёт ACK от replica, только потом транзакция видна клиентам — нет phantom reads. `AFTER_COMMIT` (дефолт): транзакция фиксируется до ACK — клиенты могут увидеть данные, ещё не ушедшие на replica.

**Q: Параллельная репликация: режимы `slave_parallel_mode`?**
A: `optimistic` (дефолт с 10.5): параллельно, при конфликте — откат и последовательно. `conservative`: параллельно только для group commit. `aggressive`: максимальный параллелизм. `minimal`: только commit параллельно.

### Galera

**Q: Как работает Galera Cluster?**
A: Синхронная multi-master репликация (wsrep). Транзакция выполняется на узле, write set отправляется на все узлы, каждый проверяет на конфликты (certification), при успехе — коммит на всех. RPO=0. Кворум: `floor(N/2)+1` узлов (минимум 3, или 2 + garbd).

**Q: Что такое Flow Control?**
A: Механизм Galera: если узел не успевает применять транзакции (`wsrep_local_recv_queue` растёт), кластер замедляет запись до скорости самого медленного узла. `wsrep_flow_control_paused > 0` — сигнал проблемы.

**Q: SST vs IST?**
A: SST (State Snapshot Transfer) — полная передача данных новому узлу (блокирует донора, если не mariabackup). IST (Incremental State Transfer) — передача только недостающих транзакций из gcache (не блокирует донора). IST возможен, если транзакции ещё в gcache.

### Оптимизация

**Q: Как диагностировать медленный запрос?**
A: `EXPLAIN` / `EXPLAIN FORMAT=JSON` — план; `ANALYZE` — реальные метрики; slow query log + `pt-query-digest` — топ запросов; Performance Schema — `events_statements_summary_by_digest`; проверить индексы (`type = ALL`, `Using filesort`, `Using temporary`), гистограммы на неравномерных столбцах.

**Q: Чем EXPLAIN отличается от ANALYZE?**
A: `EXPLAIN` — показывает план без выполнения (оценки). `ANALYZE` — выполняет запрос и показывает реальные метрики (строки, время). `ANALYZE FORMAT=JSON` — реальные метрики в JSON. `EXPLAIN FORMAT=TREE` в MariaDB нет (это MySQL 8.0.16+).

**Q: Что такое гистограммы в MariaDB?**
A: Статистика распределения значений столбца для оценки селективности неравенств. Создаются: `ANALYZE TABLE ... PERSISTENT FOR COLUMNS (col)`. Хранятся в `mysql.column_stats`. Типы: `SINGLE_PREC_HB`, `DOUBLE_PREC_HB`, `JSON_HB`. Важны для столбцов с перекошенным распределением.

**Q: Ignored Indexes — что это?**
A: MariaDB 10.6+: индекс существует и обслуживается при записи, но оптимизатор его не использует. Аналог MySQL Invisible Index, но другой синтаксис: `ALTER TABLE ... ALTER INDEX ... IGNORED`. Используется для безопасной проверки перед `DROP INDEX`.

### Безопасность

**Q: Плагины аутентификации в MariaDB?**
A: `unix_socket` (root на localhost через sudo, без пароля), `ed25519` (по умолчанию для новых пользователей с 10.4+), `mysql_native_password` (совместимость), `caching_sha2_password` (10.6+). `mysql_old_password` — устаревший, не использовать.

**Q: TDE (Transparent Data Encryption)?**
A: Шифрование данных at-rest (табличные пространства InnoDB/Aria). Доступно в MariaDB Enterprise Server (коммерческая) и Community (с 10.11.6+ для некоторых компонентов). Ключи управляются через `keyring` плагины (file, AWS KMS, etc.).

### Мониторинг и troubleshooting

**Q: Как мониторить MariaDB в production?**
A: Prometheus + mysqld_exporter (метрики), Grafana (дашборды), алерты (Threads_connected, buffer pool hit rate, replication lag, wsrep_*), slow query log + pt-query-digest, Performance Schema, sys schema. Методология USE (Utilization, Saturation, Errors).

**Q: Too many connections (1040) — что делать?**
A: Увеличить `max_connections`; включить Thread Pool; сократить `wait_timeout`; настроить connection pooling (ProxySQL/MaxScale); найти утечки соединений (`SHOW PROCESSLIST` — много Sleep).

**Q: Deadlock (1213) — что делать?**
A: Приложение должно повторить транзакцию (retry). Диагностика: `SHOW ENGINE INNODB STATUS` (LATEST DETECTED DEADLOCK), `sys.innodb_lock_waits`. Профилактика: короткие транзакции, упорядоченный доступ к строкам, индексы.

**Q: Как найти неиспользуемые индексы?**
A: `sys.schema_unused_indexes` (MariaDB 10.5+), или Performance Schema `table_io_waits_summary_by_index_usage` (COUNT_STAR = 0). Перед удалением — перевести в `IGNORED` (10.6+) и проверить план.

## Устранение неполадок (Troubleshooting)

### Как подготовиться к собеседованию

1.  **Практика:** настройте MariaDB в Docker, выполните EXPLAIN, создайте репликацию.
2.  **Документация:** mariadb.com/kb/en/ — официальная KB.
3.  **Отличия MySQL:** знайте, что есть в MySQL, но нет в MariaDB (и наоборот).
4.  **Версии:** знайте LTS-версии (10.11, 11.4, 11.8, 12.3) и ключевые фичи каждой.

## Лучшие практики (Best Practices)

1.  **Знайте отличия MariaDB от MySQL** — ключевой вопрос на собеседовании.
2.  **Практический опыт:** EXPLAIN, репликация, Galera — настраивайте в лабе.
3.  **Терминология:** Source/Replica (не Master/Slave), `SHOW REPLICA STATUS`.
4.  **Версии:** LTS-линии и их фичи.
5.  **Для репликации:** см. **[Репликация: собеседование](replication/interview_questions.md)** — специализированные вопросы.

## Дополнительная информация

### См. также

*   **[Обзор MariaDB](overview.md)** — архитектура и возможности.
*   **[Репликация: собеседование](replication/interview_questions.md)** — вопросы по репликации.
*   **[Оптимизация запросов](query_optimization.md)** — EXPLAIN, ANALYZE.
*   **[Индексы](indexing.md)** — типы индексов.
*   **[Отказоустойчивость](high_availability.md)** — Galera, Orchestrator.
*   **[Хранимые объекты: собеседование](../Concepts/stored_objects/interview_questions.md)** — процедуры, функции, триггеры, события.
*   **[MySQL: собеседование](../MySQL/)** — вопросы по MySQL.

### Внешние ресурсы

*   [MariaDB Knowledge Base](https://mariadb.com/kb/en/)
*   [MariaDB Interview Questions](https://mariadb.com/interview-questions/)
*   [MariaDB Certification](https://mariadb.com/services/training-certification/)
