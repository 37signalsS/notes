# Мониторинг миграций баз данных

## Определения

- **Мониторинг миграций** — процесс непрерывного сбора, агрегации и анализа данных о состоянии СУБД во время выполнения структурных (DDL) или контентных (DML) изменений.
- **Наблюдаемость миграций (Migration Observability)** — способность системы предоставлять глубокие данные о внутреннем состоянии процесса трансформации (блокировки, прогресс, влияние на ресурсы) через корреляцию метрик, логов и распределенных трассировок. Позволяет отвечать на вопрос «почему» миграция замедлилась или вызвала сбой.
- **Дрейф схемы (Schema Drift)** — расхождение между ожидаемым состоянием схемы (описанным в коде миграций или декларативных файлах) и фактическим состоянием в базе данных. Выявление дрейфа — критическая задача мониторинга для предотвращения непредсказуемого поведения Production-среды.
- **Событие ожидания (Wait Event)** — состояние, при котором серверный процесс приостановлен в ожидании ресурса (например, блокировки таблицы или завершения ввода-вывода). Ключевой индикатор при диагностике «зависших» миграций.

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

#### MySQL
- **`information_schema.innodb_trx`:** Список текущих транзакций, их длительность и влияние на `history list length` (размер UNDO-логов).
- **`performance_schema.data_locks`** (MySQL 8.0+) или `innodb_lock_waits`: Диагностика конфликтов доступа, показывающая, какая транзакция блокирует остальные.
- **`performance_schema.events_stages_current`:** Позволяет отслеживать прогресс выполнения текущих стадий запроса (например, `stage/innodb/alter table (copy)`).

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

## Дополнительная информация

### Рекомендации

- **Throttle (Троттлинг):** При обнаружении нагрузки на I/O выше 80% или лага репликации > 30с, процесс миграции данных должен автоматически замедляться. Используйте адаптивные скрипты, которые проверяют лаг перед каждым следующим батчем.
- **War Room Dashboard:** Создайте в Grafana дашборд, объединяющий:
    - Метрики ресурсов БД (CPU, IOPS, Disk Space).
    - Статус блокировок (`pg_locks`).
    - Прогресс длительных операций (`pg_stat_progress`).
    - Лаг репликации.
- **Audit-логи:** Храните историю выполнения миграций с указанием исполнителя. Используйте `SET application_name = 'migration_job_123'` перед запуском для удобства фильтрации в логах.
- **Линтинг схем:** Интегрируйте инструменты мониторинга дрейфа схемы в CI/CD (например, `sqlfluff` или `atlas lint`) для раннего обнаружения опасных паттернов.
- **Алертинг на долгоживущие транзакции:** Настройте алерт, когда сессия находится в статусе `idle in transaction` дольше порога (например, 30s). Такие сессии удерживают `AccessShareLock` и могут стать причиной каскадного зависания миграций. Запрос для детекта:
  ```sql
  SELECT pid, usename, xact_start, query
  FROM pg_stat_activity
  WHERE state = 'idle in transaction'
    AND xact_start < now() - interval '30s';
  ```

### Смежные темы

- **[Типовые сценарии миграций](scenarios.md)** — реализация батчинга и безопасных DDL.
- **[Database CI/CD](database-ci-cd.md)** — автоматизация проверок и GitOps.
- **[Безопасные массовые операции](../safe_large_scale_data_modification.md)** — глубокий разбор пакетной обработки и лимитов.
- **[Стратегии отката (Rollback)](rollback_strategies.md)** — действия при срабатывании алертов мониторинга.
- **[Метрики SRE](../../Concepts/sre_concepts_main.md)** — общие принципы надежности.
- **[Наблюдаемость PostgreSQL](../../Databases/PostgreSQL/Operations/observability.md)** — полная настройка стека мониторинга.
