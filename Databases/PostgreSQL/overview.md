# PostgreSQL: Обзор

**Актуально для:** PostgreSQL 17 / 18

Файл — точка входа в раздел PostgreSQL. Описывает концепции и операции, применимые к двум актуальным веткам: **17** (релиз 2024-09-26) и **18** (релиз 2025-09-25, current). Версияспецифичные фичи помечены явно; глубокая проработка каждой темы — в соответствующих файлах (ссылки в «Дополнительной информации»).

## Определения

**PostgreSQL** — свободная объектно-реляционная система управления базами данных (СУБД) с открытым исходным кодом. Остается стандартом де-факто для надежного хранения структурированных и слабоструктурированных данных, благодаря строгому следованию стандартам SQL и реализации полноценных транзакций [ACID](../Concepts/acid.md).

*   **OLTP (Online Transactional Processing):** Основной профиль использования — высокоинтенсивная обработка коротких транзакций в реальном времени.
*   **Экземпляр (Instance) vs Кластер:** Экземпляр — это совокупность процессов и разделяемой памяти в RAM, а Кластер — это совокупность баз данных, хранящихся в едином каталоге на диске (**PGDATA**).
*   **Расширяемость:** Уникальная архитектура позволяет подключать внешние модули (Extensions), типы данных и процедурные языки (`PL/pgSQL`, `PL/Python` — в составе ядра; `PL/v8` — сторонний), превращая СУБД в универсальную платформу.
*   **Надежность (SRE-контекст):** Минимальные показатели **RPO** (целевая точка восстановления) достигаются через WAL-архивирование и PITR, а **RTO** (время восстановления) — через восстановление из базового бэкапа + WAL (см. [Бэкап и восстановление](./Concepts/backup_and_recovery.md)).

## Базовые концепции

### Архитектура и надежность

PostgreSQL использует модель **Process-per-connection** (отдельный процесс на каждое соединение), что гарантирует изоляцию: сбой в одной сессии не влияет на работу всего инстанса.

*   **Процессная модель:** Главный процесс (**postmaster**) порождает Backend-процессы для клиентов. Из-за оверхеда на форк процессов при больших нагрузках (>500-1000 соединений) критически важно использование пулеров соединений, таких как **[PgBouncer](./Operations/pgbouncer_setup.md)**.
*   **MVCC (Multi-Version Concurrency Control):** Механизм многоверсионности позволяет читающим процессам не блокировать пишущие. Каждое изменение создает новую версию строки, а старая помечается как «мертвая» (dead tuple).
*   **Очистка и VACUUM:** Для удаления мертвых кортежей используется процесс `VACUUM`.
    - **TidStore (PG 17):** Новая подсистема хранения TID для `VACUUM` — существенно снижает потребление RAM и снимает неявное ограничение в 1 ГБ памяти при больших `maintenance_work_mem` / `autovacuum_work_mem`, что ускоряет обслуживание очень больших таблиц.
*   **Журнал предзаписи (WAL):** Все изменения сначала пишутся в последовательный журнал (`pg_wal`), что обеспечивает **Durability** при сбоях питания. В **PG 17** `pg_basebackup` поддерживает инкрементальные бэкапы (`--incremental`, сборка — утилитой `pg_combinebackup`) и суммаризацию WAL (`summarize_wal`).
*   **Потоковое чтение (PG 17):** Streaming I/O для последовательных чтений — группировка файловых чтений (`io_combine_limit`), ускоряет sequential reads.
*   **Асинхронный ввод-вывод AIO (PG 18):** Нативная подсистема асинхронного I/O (`io_method`, `io_combine_limit` / `io_max_combine_limit`) позволяет бэкендам ставить запросы чтения в очередь, что ускоряет `Sequential Scan`, `Bitmap Heap Scan` и `VACUUM`; статистика — в системном представлении `pg_aios`.
*Подробнее: [Архитектура](./Concepts/architecture.md) и [MVCC](./Concepts/concurrency_and_locking.md)*.

### Репликация и доступность
*   **Физическая репликация (Streaming):** Побайтовая передача WAL-записей.
    *   **Асинхронная:** Высокая производительность, возможен лаг репликации и потеря данных при сбое мастера.
    *   **Синхронная:** Гарантирует доставку данных на реплику перед подтверждением транзакции клиенту (ценой роста latency коммита).
*   **Логическая репликация:** Передача изменений на уровне отдельных строк. Позволяет реплицировать данные между разными мажорными версиями или отдельными таблицами.
    - **pg_createsubscriber (PG 17):** Утилита для создания логической реплики из физического Standby (конвертация standby в subscriber).
    - **Failover логических слотов (PG 17):** Управление failover через `CREATE/ALTER SUBSCRIPTION ... FAILOVER` и `sync_replication_slots`.
*   **High Availability (HA):** Построение отказоустойчивых кластеров с помощью **Patroni**, использующих DCS (etcd/Consul) для управления лидером и автоматического Failover.
*Подробнее: [Репликация](./Concepts/replication.md) и [High Availability](./Concepts/high_availability.md)*.

### Безопасность и управление
*   **RBAC (Role-Based Access Control):** Иерархическая система ролей и привилегий.
    - **Привилегия MAINTAIN (PG 17):** Делегирование задач обслуживания (`VACUUM`, `ANALYZE`, `REINDEX`, `REFRESH MATERIALIZED VIEW`, `CLUSTER`, `LOCK TABLE`) без прав суперпользователя — на уровне таблицы (`MAINTAIN`) или роли (`pg_maintain`).
*   **RLS (Row-Level Security):** Политики доступа к данным на уровне конкретных строк таблицы.
*   **Аутентификация:** `SCRAM-SHA-256` (дефолт с PG 14), LDAP/Kerberos, **OAuth (PG 18)**. **MD5-аутентификация объявлена deprecated в PG 18** (удаление в будущей мажорной версии).
*   **Шифрование:** TLS для соединений (настройка `ssl`; рекомендуется в production, но не принудительно по умолчанию) и прозрачное шифрование данных (TDE) — нативно в PostgreSQL не поддерживается, реализуется расширением `pg_tde` (Percona) или шифрованием на уровне ОС. Подробный разбор методов защиты: **[Безопасность и шифрование](./Concepts/security_and_encryption.md)**.

### Универсальность и расширяемость
*   **Типы индексов:** B-дерево (стандарт), Hash, GiST (геометрия/текст), GIN (массивы/JSONB), BRIN (огромные временные ряды).
*   **JSONB:** Нативная поддержка двоичного JSON с возможностью индексации и поиска, сопоставимая по скорости с NoSQL-решениями.
*   **Расширения:**
    *   `pg_stat_statements`: Детальный анализ производительности запросов.
    *   `PostGIS`: ГИС-функционал мирового уровня.
    *   `pgvector`: Хранение и поиск по векторам (эмбеддингам).

## Практические сценарии

### PostgreSQL как универсальная платформа
Благодаря расширениям, PostgreSQL может успешно заменять специализированные инструменты:

| Задача | Решение в PostgreSQL | Преимущество |
| :--- | :--- | :--- |
| **Документная БД** | Тип **[JSONB](./Concepts/json_support.md)** | Транзакции ACID + валидация схемы через `CHECK` |
| **Временные ряды** | Расширение **[TimescaleDB](../timescaledb.md)** | Автоматическое партиционирование и сжатие |
| **Уникальные ID** | **UUIDv7** (PG 18+, функция `uuidv7()`) | Нативная поддержка сортируемых по времени UUID |
| **Гео-данные** | Расширение **PostGIS** | Пространственные индексы и сложные SQL-функции |
| **Поиск (FTS)** | Встроенный **[FTS](./Concepts/full_text_search.md)** | Поиск с учетом словоформ и триграмм |
| **Векторный поиск** | Расширение **[pgvector](./pgvector.md)** | Хранение эмбеддингов в одной базе с метаданными |

### Эксплуатационные SRE-операции
Базовые команды для инспекции состояния в `psql`:

**1. Проверка активных сессий и блокировок:**
```sql
-- Поиск долгих активных запросов (>5 секунд)
SELECT pid, usename, state, now() - query_start AS duration, query 
FROM pg_stat_activity 
WHERE state != 'idle' AND now() - query_start > interval '5s';
-- → pid | usename | state | duration | query
-- → 12345 | app_user | active | 00:00:12 | SELECT * FROM orders WHERE ...
-- → (0 rows) — долгих запросов нет

-- Выявление блокирующих процессов
SELECT blocked_locks.pid AS blocked_pid, blocking_locks.pid AS blocking_pid,
       blocking_activity.query AS blocking_statement
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocked_locks.pid = blocked_activity.pid
WHERE NOT blocked_locks.granted;
-- → blocked_pid | blocking_pid | blocking_statement
-- → (0 rows) — блокировок нет
```

**2. Анализ производительности запроса:**
```sql
EXPLAIN (ANALYZE, BUFFERS, SETTINGS)
SELECT * FROM orders WHERE user_id = 123;
-- → Seq Scan / Index Scan на orders ... Buffers: shared hit=... read=...
-- → Обращайте внимание на 'shared hit' (попадание в кэш) vs 'shared read' (чтение с диска)
```

**3. Проверка размера таблиц и индексов (Bloat):**
```sql
SELECT relname AS "Table", 
       pg_size_pretty(pg_total_relation_size(relid)) AS "Total Size"
FROM pg_catalog.pg_statio_user_tables 
ORDER BY pg_total_relation_size(relid) DESC 
LIMIT 5;
-- → Table | Total Size
-- → orders | 42 GB
```

### SRE Чек-лист: Что делать, если база «тормозит»?
1.  **Инфраструктура:** Проверить CPU (Steal time?), Disk IOPS (%util?), Memory (Swap?).
2.  **Соединения:** Проверить количество `active` vs `idle` соединений. Возможно, забит `max_connections`.
3.  **Блокировки:** Найти транзакцию, которая держит `ExclusiveLock` на важную таблицу.
4.  **Статистика:** Проверить дату последнего `ANALYZE`. Если статистика устарела, план запроса будет неоптимальным.
5.  **Bloat:** Если `autovacuum` не успевает, может потребоваться `VACUUM ANALYZE` вручную или `pg_repack`.

## Лучшие практики

1.  **Пулинг соединений:** PgBouncer при сотнях/тысячах клиентов — process-per-connection не масштабируется (каждый бэкенд — отдельный процесс с собственной памятью).
2.  **Контрольная сумма данных:** включать при `initdb` (в PG 18 — дефолт; в 17 — указать явно, `--data-checksums`).
3.  **Современная аутентификация:** `SCRAM-SHA-256`; отказ от MD5 (deprecated в PG 18).
4.  **Наблюдаемость:** `pg_stat_statements`, `pg_stat_activity`, мониторинг dead tuples и autovacuum, `pg_stat_checkpointer` (PG 17+).
5.  **Ограничение транзакций:** `transaction_timeout` (PG 17) для защиты от длинных транзакций, блокирующих очистку.
6.  **Наименьшие привилегии:** делегирование обслуживания через `MAINTAIN` / роль `pg_maintain` вместо выдачи суперправ.
7.  **Тестирование восстановления:** бэкап без проверенного восстановления не является бэкапом (см. [Валидация бэкапов](../Concepts/backup_validation.md)).

## Пограничные случаи

*   **Потолок соединений:** деградация при тысячах соединений без пулера — форк процесса на каждое подключение.
*   **Dead tuples и bloat:** `autovacuum` освобождает место внутри таблицы, но не уменьшает файл на диске; сжатие — `VACUUM FULL` или `pg_repack` (сторонний).
*   **Длинные транзакции:** мешают `VACUUM` (накопление dead tuples); параметр `old_snapshot_threshold` удалён в PG 17.
*   **Репликация:** асинхронная — возможна потеря записей при failover; синхронная — рост latency коммита.
*   **AIO (PG 18):** включается через `io_method`; эффект зависит от нагрузки — сначала замерить на staging.

## Дополнительная информация

### Эксплуатация и администрирование
*   **Развертывание:** [Установка на Ubuntu](./Operations/installation_ubuntu.md), [Установка на RHEL / Rocky / AlmaLinux](./Operations/installation_rhel.md), [PostgreSQL в Docker](./Operations/docker_deployment.md) или [в Kubernetes](./Operations/kubernetes_deployment.md).
*   **Отказоустойчивость:** [PostgreSQL HA (Patroni, etcd, HAProxy)](./Operations/high_availability_patroni.md) — построение High Availability кластера; [Аварийное восстановление (DR)](./Operations/disaster_recovery.md) — RPO/RTO, учения восстановления; [Кросс-региональный DR](./Concepts/cross_region_dr.md) — WAL offsite, standby в другом регионе; [Chaos Engineering](./Operations/chaos_engineering.md) — инъекции отказов для PostgreSQL.
*   **Управление:** [Роли и базы данных](./Operations/role_management.md), [Основы работы в psql](./Operations/console_basics.md), [Управление соединениями](./Operations/connection_management.md), [Настройка репликации](./Operations/replication_setup.md), [Автоматизация бэкапов](./Operations/backup_automation.md), [Автоматизация обслуживания](./Operations/maintenance_automation.md) — pg_cron, REINDEX, bloat, wraparound; [Обновление между мажорными версиями (pg_upgrade)](./Operations/pg_upgrade.md).
*   **Типы данных и целостность:** [Часовые пояса (timestamptz)](./Concepts/timezone_handling.md), [Массивы и range-типы](./Concepts/arrays_and_ranges.md), [Ограничения целостности (Constraints)](./Concepts/constraints.md), [Event Triggers (аудит DDL)](./Concepts/event_triggers.md).
*   **Инструменты:** [Графические и веб-интерфейсы](./Operations/management_tools.md), [PgBouncer](./Operations/pgbouncer_setup.md) и [Pgpool-II](./Operations/pgpool.md) — пулинг, балансировка и failover.
*   **Наблюдаемость:** [Мониторинг и трассировка SQL](./Operations/observability.md), [Профилирование запросов](./Concepts/query_profiling.md) — pg_qualstats, pgsi, pg_profile, pg_store_plans, и [Ёмкостное планирование](./Operations/capacity_planning.md).
*   **Платформа:** [Тюнинг Linux под PostgreSQL](./Operations/linux_tuning.md) — THP, huge pages, NUMA, cgroups, sysctl.
*   **Резервное копирование:** [Бэкап и восстановление](./Concepts/backup_and_recovery.md) и [Corruption Recovery](./Concepts/corruption_recovery.md).
*   **Оптимизация:** [Производительность](./Operations/performance_tuning.md), [Масштабирование](./Concepts/scaling.md), [Оптимизация PL/pgSQL](./Concepts/pl_pgsql_optimization.md) и [Отладка хранимых объектов](./Concepts/stored_objects_debugging.md).
*   **Диагностика:** [Диагностический runbook](./Operations/troubleshooting_runbook.md) — симптом → команда → причина; [Справочник кодов ошибок](./Concepts/error_codes.md) — SQLSTATE.
*   **Подготовка к собеседованию:** [Вопросы и ответы (DevOps/SRE/Sysadmin)](./interview_qa.md).

### Смотрите также
*   [Интеграция с ClickHouse](./Integrations/clickhouse.md)
*   [Работа с внешними данными (FDW)](./Integrations/fdw.md)
*   [JSON и NoSQL возможности](./Concepts/json_support.md)
*   [Write-Ahead Log (WAL) — теория надежности](../Concepts/write_ahead_log.md)
*   [Политика поддержки версий](https://www.postgresql.org/support/versioning/)
