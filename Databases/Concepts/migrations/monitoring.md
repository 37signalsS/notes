# Мониторинг миграций баз данных

**Актуально для:** PostgreSQL 11+, MySQL 8.0.12+, MariaDB 10.3+

## Определения

- **Мониторинг миграций** — процесс непрерывного сбора, агрегации и анализа данных о состоянии СУБД во время выполнения структурных (DDL) или контентных (DML) изменений.
- **Наблюдаемость миграций (Migration Observability)** — способность системы предоставлять глубокие данные о внутреннем состоянии процесса трансформации (блокировки, прогресс, влияние на ресурсы) через корреляцию метрик, логов и распределенных трассировок. Позволяет отвечать на вопрос «почему» миграция замедлилась или вызвала сбой.
- **Дрейф схемы (Schema Drift)** — расхождение между ожидаемым состоянием схемы (описанным в коде миграций или декларативных файлах) и фактическим состоянием в базе данных. Выявление дрейфа — критическая задача мониторинга для предотвращения непредсказуемого поведения Production-среды.
- **Событие ожидания (Wait Event)** — состояние, при котором серверный процесс приостановлен в ожидании ресурса (например, блокировки таблицы или завершения ввода-вывода). Ключевой индикатор при диагностике «зависших» миграций.
- **SRE Golden Signals** — четыре базовых сигнала (Ошибки, Длительность, Насыщенность, Блокировки), используемые для оценки здоровья любого сервисного процесса, включая миграции.
- **Maintenance Window** — заранее согласованное с бизнесом окно времени, в течение которого допустимо снижение производительности или кратковременный простой для проведения миграций.
- **Change Advisory Board (CAB)** — группа, ответственная за оценку рисков миграций, согласование окон обслуживания и утверждение планов изменений в Production.

## Основные концепции

Эффективный мониторинг строится на трех уровнях: уровне СУБД, уровне инструментов управления миграциями и уровне приложения.

### Ключевые метрики (SRE Golden Signals) в миграциях

1. **Ошибки (Errors):** Отслеживание неудачных попыток применения изменений. Алертинг должен срабатывать на любой `failure_total > 0`. Сюда входят ошибки синтаксиса, нарушения `Constraint` и таймауты.
2. **Длительность (Latency):** Время выполнения конкретных шагов или батчей. **Теория:** Рост задержки на больших объемах данных часто сигнализирует о неэффективном плане запроса (например, отсутствие индекса для DML) или о конкуренции за ресурсы.
3. **Насыщенность (Saturation):** Влияние миграции на системные ресурсы. Критично для Online Schema Change (OSC) инструментов, которые могут утилизировать 100% IOPS или CPU, вытесняя пользовательский трафик.
4. **Блокировки (Traffic/Concurrency):** Количество запросов, ожидающих освобождения ресурсов, захваченных миграцией. Высокий уровень блокировок может привести к каскадному отказу приложения (connection pool exhaustion).

### Объекты наблюдения в СУБД

#### PostgreSQL

- **`pg_stat_activity`:** Показывает текущие сессии, их состояние (`active`, `idle in transaction`) и `wait_event`. Позволяет мгновенно увидеть, что миграция заблокирована другим процессом.
- **`pg_stat_progress_*`:** Специализированные представления для отслеживания прогресса тяжелых операций:
    - `pg_stat_progress_create_index` — прогресс построения индексов (колонки `phase`, `blocks_done`, `blocks_total`).
    - `pg_stat_progress_analyze` / `vacuum` — прогресс фонового обслуживания, необходимого после массовых DML для обновления статистики.
    - `pg_stat_progress_cluster` — прогресс операций пересоздания таблиц (`CLUSTER`, `VACUUM FULL`).
    - `pg_stat_progress_copy` — прогресс массовой загрузки данных.
- **`pg_locks`:** Детальная информация о типах удерживаемых (`AccessExclusiveLock`, `RowShareLock`) и запрашиваемых блокировок.
- **`pg_stat_replication`:** Статус репликации (WAL sender), позиция LSN и текущий лаг реплики в секундах.
- **`pg_stat_wal_receiver`:** Состояние приемника WAL на репликах.
- **`pg_stat_user_tables`:** Счетчики seq_scan, idx_scan, n_dead_tup — позволяют оценить фрагментацию таблиц после массовых DML.
- **`pg_statio_user_tables`:** Статистика физического ввода-вывода по таблицам (heap_blks_read, idx_blks_hit) — помогает диагностировать снижение кэш-попаданий во время миграции.
- **`pg_stat_database`:** Общие метрики по БД (xact_commit, xact_rollback, deadlocks) — рост deadlocks при миграции указывает на неконтролируемую конкуренцию.
- **`pg_stat_bgwriter`:** Метрики фонового писателя (checkpoints, buffers written) — рост частоты чекпоинтов при массовых операциях означает нагрузку на дисковую подсистему.

#### MySQL

- **`information_schema.innodb_trx`:** Список текущих транзакций, их длительность и влияние на `history list length` (размер UNDO-логов).
- **`performance_schema.data_locks`** (MySQL 8.0+) или `innodb_lock_waits`: Диагностика конфликтов доступа, показывающая, какая транзакция блокирует остальные.
- **`performance_schema.events_stages_current`:** Позволяет отслеживать прогресс выполнения текущих стадий запроса (например, `stage/innodb/alter table (copy)`).
- **`sys.schema_table_lock_waits`:** Удобное представление для быстрого поиска конфликтов блокировок на таблицах.
- **`performance_schema.file_summary_by_instance`:** Статистика операций ввода-вывода по файлам — помогает выявить горячие таблицы во время массовой загрузки.
- **`information_schema.INNODB_METRICS`:** Детальные метрики InnoDB (purge, insert buffer, adaptive hash index) — полезны для анализа поведения движка под нагрузкой миграции.

## Предпосылки и подготовка

Перед запуском миграции в Production выполните стандартный чек-лист. Детальный разбор параметров сессии, проверки индексов и оценки объёма данных см. в **[Безопасные массовые операции](../safe_large_scale_data_modification.md#pre-flight-проверки)**.

- **Change Advisory Board (CAB):** Миграции, затрагивающие таблицы > 10 ГБ или содержащие `DROP/RENAME`, требуют утверждения. Документируйте окно деплоя, критерии отката и контакты on-call.
- **Maintenance Window:** Для миграций с ожидаемым простем > 30с согласуйте окно с бизнесом. Для zero-downtime — фиксируйте время cutover в runbook.
- **Runbook:** Для каждой миграции создайте пошаговый runbook с командами проверки, точками отката и контактами ответственных. Runbook должен содержать:
    - Диаграмму последовательности фаз (Expand / Migrate / Contract).
    - Критерии успешного выполнения каждого этапа.
    - Команды для экстренной остановки (`pg_terminate_backend`, `KILL`).
    - Шаблон для сообщения в War Room (Slack/IRC/PagerDuty).

## Практические сценарии

### Сценарий 1: Диагностика блокировок в реальном времени (PostgreSQL)

Обнаружение транзакций, которые мешают выполнению миграции (`lock_timeout`), выстраивая очередь из заблокированных запросов.

#### Предпосылки
- Наличие прав `pg_monitor` или `SUPERUSER`.
- Установленный `lock_timeout` в сессии миграции для предотвращения "завешивания" всей БД.

#### Пошаговая инструкция
Выполнение запроса для поиска пары «блокировщик — заблокированный»:

```sql
SELECT
    blocked_locks.pid AS blocked_pid,
    blocking_locks.pid AS blocking_pid,
    blocked_activity.query AS blocked_statement,
    blocking_activity.query AS blocking_statement,
    blocked_activity.wait_event AS wait_event,
    age(now(), blocking_activity.xact_start) AS blocking_xact_age
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks 
    ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
    AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
    AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
    AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
    AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
    AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
    AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
    AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

#### Валидация
- Если результат не пуст — миграция стоит в очереди. 
- Проверьте `blocking_xact_age`: слишком старые транзакции могут быть признаком "зависших" соединений приложения.

#### Устранение неисправностей
- **Idle in transaction:** Если блокировщик находится в этом статусе, необходимо принудительно завершить его: `SELECT pg_terminate_backend(blocking_pid);` (после анализа причин).

---

### Сценарий 2: Алертинг на лаг репликации (Prometheus)

Критический показатель при миграции данных в больших таблицах. Рост лага может привести к чтению устаревших данных на репликах и переполнению диска на мастере (накопление WAL/binlog).

#### Предпосылки
- Настроенный `postgres_exporter` или `mysqld_exporter`.
- Alertmanager для доставки уведомлений.

#### Пример правила (Prometheus)
```yaml
groups:
- name: DatabaseMigrationSafety
  rules:
  - alert: CriticalReplicationLag
    expr: pg_replication_lag_seconds > 60
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "Критический лаг репликации БД"
      description: "Лаг репликации на {{ $labels.instance }} превысил 60 секунд во время выполнения миграции. Риск рассинхронизации данных."
```

#### Валидация
- Проверьте текущее значение лага: `SELECT pg_last_xact_replay_timestamp() - now();` (PostgreSQL).

#### Устранение неисправностей
- **Троттлинг:** Если лаг растет — приостановите или замедлите процесс пакетной миграции данных (увеличьте `sleep` между батчами).

---

### Сценарий 3: Сквозная трассировка (Distributed Tracing)

Использование **sqlcommenter** для связки SQL-запроса миграции с трейсом приложения или пайплайна.

#### Теория
Добавление комментариев в SQL позволяет инструментам мониторинга (Google Cloud SQL, Datadog, Jaeger) сопоставлять нагрузку на БД с конкретными релизами или запросами пользователей.

#### Пошаговая инструкция
Добавьте метаданные в SQL-команду:

```sql
-- Пример запроса, видимого в pg_stat_activity и логах
ALTER TABLE users ADD COLUMN age INT; /* traceparent='00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01',deployment='v42' */
```

#### Валидация
- Проверьте `pg_stat_activity`: комментарий должен быть виден в колонке `query`.

---

### Сценарий 4: Метрики инструментов и обнаружение дрейфа

Современные инструменты (Flyway, Atlas, Liquibase) предоставляют данные о своем состоянии.

#### Метрики Prometheus
- `flyway_release_info`: Версия текущей схемы.
- `atlas_migration_duration_seconds`: Время выполнения.
- `atlas_migration_errors_total`: Счетчик ошибок.

#### Обнаружение дрейфа схемы (CI/CD)
Использование `atlas schema inspect` для сравнения текущего состояния с мастер-веткой.

```bash
# В CI/CD пайплайне
atlas schema inspect -u "postgres://user:pass@db-host:5432/db" > current.hcl
atlas schema diff --from "file://schema.hcl" --to "file://current.hcl"
```
*Если diff не пуст — миграции в Production были применены вручную в обход CI/CD.*

---

### Сценарий 5: Мониторинг истощения connection pool во время миграции

Длительные миграции могут привести к исчерпанию пула соединений приложения, если сессии миграции удерживают блокировки долго.

#### Предпосылки
- Настроен PgBouncer, HAProxy или встроенный пул приложения (HikariCP, SQLAlchemy).
- Доступ к метрикам пула соединений.

#### Пошаговая инструкция (PostgreSQL + PgBouncer)

1. Мониторинг метрик PgBouncer через `SHOW POOLS` и `SHOW CLIENTS`:
   ```sql
   -- На PgBouncer
   SHOW POOLS;
   -- active_clients + wait_clients не должны превышать max_client_conn
   SHOW STATS;
   ```

2. Настройка алерта на количество ожидающих соединений (`wait_clients`):
   ```yaml
   - alert: PgBouncerConnectionPoolExhaustion
     expr: pgbouncer_wait_clients > 10
     for: 1m
     labels:
       severity: warning
     annotations:
       summary: "Connection pool exhaustion на {{ $labels.instance }}"
   ```

#### Валидация
- Проверка `pg_stat_activity`: количество активных миграционных сессий + обычные сессии < `max_connections`.

#### Устранение неисправностей
- **Снизить `max_migrations`:** Запускайте миграции последовательно, а не параллельно.
- **Увеличить `wait_timeout`:** Для PgBouncer можно временно увеличить `max_wait_client`, но это маскирует проблему — лучше упростить миграцию.

---

### Сценарий 6: Мониторинг роста WAL / Binlog во время массовых DML

Массовая миграция данных генерирует огромный объем журналов репликации. Если диск, на котором хранится WAL (PostgreSQL) или Binlog (MySQL), заполняется, репликация останавливается.

#### Пошаговая инструкция (PostgreSQL)

1. Мониторинг размера WAL:
   ```sql
   SELECT pg_size_pretty(count(*) * 16 * 1024 * 1024) AS wal_size_mb
   FROM pg_ls_waldir();
   ```

2. Мониторинг роста WAL в реальном времени через `pg_stat_wal` (PostgreSQL 14+):
   ```sql
   SELECT wal_records, wal_bytes, wal_fpi, wal_stats_reset
   FROM pg_stat_wal;
   ```

#### Валидация
- Убедитесь, что свободное место на диске с WAL > 2x ожидаемого размера миграции.
- Настройте алерт на `disk_free_bytes < 20%` для разделов с WAL / Binlog.

#### Устранение неисправностей
- **Включить `wal_compression`:** Для массовых `COPY` или `INSERT` PostgreSQL 14+ поддерживает сжатие WAL.
- **Увеличить `max_wal_size`:** Позволяет реже запускать чекпоинты, но требует больше места.

---

## Пограничные случаи и ограничения

1.  **Секционированные таблицы:** Миграция отдельной секции (ATTACH/DETACH PARTITION) имеет свои паттерны мониторинга. Следите за `pg_stat_progress_cluster` и метриками конкретной секции в `pg_stat_user_tables`.
2.  **Внешние ключи без `NOT VALID`:** Длинные проверки FK блокируют таблицу на запись. Мониторинг `pg_locks` и `pg_stat_activity` обязателен.
3.  **Триггеры и логирование:** Триггеры, созданные в рамках Expand-Contract, добавляют накладные расходы на каждую запись. Сравнивайте `tup_inserted` / `tup_updated` до и после включения триггера.
4.  **Таблицы > 1 ТБ:** Для таблиц этого размера мониторинг прогресса через `pg_stat_progress_create_index` обязателен. Отсутствие прогресса в течение 10 минут — сигнал к отмене миграции.
5.  **Асинхронные реплики:** На репликах лаг репликации может значительно превышать мастерские значения из-за нагрузки на чтение. Используйте `pg_stat_replication` на мастере, а не на реплике.
6.  **Миграция между инстансами (pg_dump / logical replication):** Логическая репликация добавляет промежуточный слой ( publisher / subscriber ). Мониторинг должен включать метрики подписчика (`pg_stat_subscription`) и размер очереди `pg_stat_subscription_stats`.
7.  **MySQL Online DDL (`ALGORITHM=INPLACE, LOCK=NONE`):** Не все DDL-операции в MySQL могут выполняться онлайн. Список поддерживаемых операций зависит от версии и версионирования таблиц (`FIL_VISIBLE` vs `FIL_HIDDEN`). Перед миграцией проверяйте `SHOW CREATE TABLE` и документацию Oracle.

## Устранение неисправностей

### Паттерны неисправностей при миграциях

| Паттерн | Возможная причина | Первый шаг диагностики |
| :--- | :--- | :--- |
| **Зависший батч (idle in transaction)** | Блокировка строки другим процессом | `SELECT * FROM pg_stat_activity WHERE state = 'idle in transaction';` |
| **Рост репликационного лага** | Слишком большой батч или отсутствие индекса | Уменьшите `batch_size`; проверьте `EXPLAIN ANALYZE` запроса |
| **Раздувание таблицы (bloat)** | `autovacuum` не справляется с нагрузкой | Проверьте `n_dead_tup` в `pg_stat_user_tables`; включите агрессивный `autovacuum` |
| **Ошибка `lock_timeout`** | Конфликт с другими транзакциями | Увеличьте `lock_timeout` или используйте `SKIP LOCKED` для пропуска заблокированных строк |
| **Завершение соединения (statement_timeout)** | Батч выполняется дольше установленного таймаута | Увеличьте `statement_timeout` для сессии или разбейте батч на меньшие части |
| **Очередь блокировок в MySQL** | Длинная транзакция удерживает `metadata lock` | `SHOW PROCESSLIST`; завершите блокирующий поток (`KILL <thread_id>`) |
| **Истощение connection pool** | Миграция удерживает соединения дольше ожидания | Увеличьте `max_client_conn` (PgBouncer) или упростите параллелизм миграции |

### Operational Runbook: Анализ миграции

1.  **Быстрая проверка (5 минут):**
    - `SELECT count(*) FROM pg_stat_activity WHERE state = 'active';` — нет ли зависших транзакций?
    - `SELECT * FROM pg_prepared_xacts;` — нет ли зависших prepared-транзакций?
    - `SHOW SLAVE STATUS\G` / `pg_stat_replication` — каков текущий лаг репликации?
    - `df -h` / `du -sh /var/lib/pgsql/data/pg_wal` — достаточно ли места для WAL?

2.  **Диагностика (30 минут):**
    - `EXPLAIN ANALYZE` на проблемный запрос — есть ли Sequential Scan?
    - `SELECT * FROM pg_locks WHERE granted = false;` — нет ли дедлоков?
    - `SELECT relname, n_dead_tup, last_autovacuum FROM pg_stat_user_tables;` — насколько быстро растет bloat?
    - `SHOW ENGINE INNODB STATUS\G` (MySQL) — аккуратное состояние InnoDB, история purge, счетчики lock waits.

3.  **Корректировка (1–2 часа):**
    - Уменьшение `batch_size` и увеличение паузы между батчами.
    - Принудительный `ROLLBACK` зависших транзакций (с подтверждением, что они не активны).
    - Включение агрессивного `autovacuum` для целевой таблицы.
    - Для MySQL: снижение `innodb_lock_wait_timeout` и проверка `performance_schema.data_locks`.

4.  **Валидация:**
    - Запуск тестового батча и проверка репликационного лага.
    - Сравнение `count(*)` до и после операции.
    - Настройка алертов на `replication_lag > 10s` и `prepared_transactions_count > 0`.

## Рекомендации

- **Throttle (Троттлинг):** При обнаружении нагрузки на I/O выше 80% или лага репликации > 30с, процесс миграции данных должен автоматически замедляться. Используйте адаптивные скрипты, которые проверяют лаг перед каждым следующим батчем.
- **War Room Dashboard:** Создайте в Grafana дашборд, объединяющий:
    - Метрики ресурсов БД (CPU, IOPS, Disk Space).
    - Статус блокировок (`pg_locks`, `performance_schema.data_locks`).
    - Прогресс длительных операций (`pg_stat_progress`).
    - Лаг репликации.
    - WAL / Binlog growth rate.
    - Connection pool utilization.
- **Audit-логи:** Храните историю выполнения миграций с указанием исполнителя. Используйте `SET application_name = 'migration_job_123'` перед запуском для удобства фильтрации в логах.
- **Линтинг схем:** Интегрируйте инструменты мониторинга дрейфа схемы в CI/CD (например, `sqlfluff` или `atlas lint`) для раннего обнаружения опасных паттернов.
- **Алертинг на долгоживущие транзакции:** Настройте алерт, когда сессия находится в статусе `idle in transaction` дольше порога (например, 30s). Такие сессии удерживают `AccessShareLock` и могут стать причиной каскадного зависания миграций. Запрос для детекта:
  ```sql
  SELECT pid, usename, xact_start, query
  FROM pg_stat_activity
  WHERE state = 'idle in transaction'
    AND xact_start < now() - interval '30s';
  ```
- **SLO / SLI для миграций:** Определите целевые значения:
    - **Длительность миграции:** P95 < 5 минут для миграций в окне обслуживания.
    - **Лаг репликации:** < 5 секунд в течение 99% времени миграции.
    - **Ошибки миграций:** 0 неудачных деплоев на квартал.
    - **Downtime при миграции:** 0 для zero-downtime миграций; < 30 секунд для согласованных окон.
- **Снэпшот метрик до/после:** Перед миграцией сохраните baseline (CPU, IOPS, лаг, количество активных соединений) и сравнивайте с ним во время и после миграции. Отклонение > 20% — повод остановить деплой.
- **DBA Review:** Все миграции, затрагивающие таблицы размером > 10 ГБ или содержащие `DROP/RENAME`, требуют ручного ревью Senior инженером.
- **Изоляция прав:** CI-пользователь не должен иметь прав `OWNER` на всю базу. Используйте минимально необходимые привилегии для DDL.

## Смежные темы

- **[Типовые сценарии миграций](scenarios.md)** — реализация батчинга и безопасных DDL.
- **[Database CI/CD](database-ci-cd.md)** — автоматизация проверок и GitOps.
- **[Безопасные массовые операции](../safe_large_scale_data_modification.md)** — глубокий разбор пакетной обработки и лимитов.
- **[Стратегии отката (Rollback)](rollback_strategies.md)** — действия при срабатывании алертов мониторинга.
- **[Обратно-совместимые миграции (Expand-Contract)](expand_contract.md)** — методология Zero-downtime.
- **[Лучшие практики миграций](migration_practices.md)** — именование, транзакции, линтинг.
- **[Метрики SRE](../../../Concepts/sre_concepts_main.md)** — общие принципы надежности.
- **[Наблюдаемость PostgreSQL](../../Databases/PostgreSQL/Operations/observability.md)** — полная настройка стека мониторинга.
