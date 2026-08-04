# Мониторинг миграций баз данных

## Определения

- **Мониторинг миграций** — это процесс непрерывного наблюдения за выполнением изменений в схеме (DDL) и данных (DML) базы данных.
- **Наблюдаемость миграций (Migration Observability)** — способность системы предоставлять данные о внутреннем состоянии процесса трансформации (блокировки, прогресс, влияние на ресурсы) через метрики, логи и трейсы.
- **Дрейф схемы (Schema Drift)** — расхождение между ожидаемым состоянием схемы (описанным в коде) и фактическим состоянием в БД, которое мониторинг должен выявлять.

## Основные концепции

Эффективный мониторинг строится на трех уровнях: уровне СУБД, уровне инструментов миграций и уровне приложения.

### Ключевые метрики (SRE Golden Signals)

1. **Успешность (Errors):** Отслеживание неудачных попыток применения миграций. Алертинг должен срабатывать на любой `failure_total > 0`.
2. **Длительность (Latency):** Время выполнения конкретных шагов. Позволяет выявить деградацию производительности на больших объемах данных.
3. **Насыщенность (Saturation):** Влияние миграции на системные ресурсы (CPU, I/O, Disk Space). Критично для Online Schema Change (OSC) инструментов.
4. **Блокировки (Traffic/Concurrency):** Количество запросов, ожидающих освобождения ресурсов, захваченных миграцией.

### Объекты наблюдения в СУБД

#### PostgreSQL
- **`pg_stat_activity`:** Текущие сессии, их состояние и `wait_event` (события ожидания).
- **`pg_stat_progress_*`:** Специализированные представления для отслеживания прогресса:
    - `pg_stat_progress_create_index` — прогресс построения индексов.
    - `pg_stat_progress_analyze` / `vacuum` — фоновое обслуживание после массовых DML.
    - `pg_stat_progress_cluster` — прогресс пересоздания таблиц.
- **`pg_locks`:** Детальная информация о типах удерживаемых и запрашиваемых блокировок.

#### MySQL
- **`information_schema.innodb_trx`:** Список текущих транзакций и их длительность.
- **`performance_schema.data_locks`** (MySQL 8.0+) или `innodb_lock_waits`: Диагностика конфликтов доступа к данным.
- **`performance_schema.events_stages_current`:** Прогресс выполнения текущих стадий запроса.

## Практические сценарии

### Сценарий 1: Диагностика блокировок в реальном времени (PostgreSQL)

Обнаружение транзакций, которые мешают выполнению миграции (`lock_timeout`).

```sql
-- Поиск блокирующего и заблокированного PID
SELECT
    blocked_locks.pid AS blocked_pid,
    blocking_locks.pid AS blocking_pid,
    blocked_activity.query AS blocked_statement,
    blocking_activity.query AS blocking_statement
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

### Сценарий 2: Алертинг на лаг репликации (Prometheus)

Критический показатель при миграции данных в больших таблицах. Рост лага может привести к чтению устаревших данных на репликах.

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
      description: "Лаг репликации на {{ $labels.instance }} превысил 60 секунд во время выполнения миграции."
```

### Сценарий 3: Сквозная трассировка (Distributed Tracing)

Использование **sqlcommenter** (или аналогов) для добавления `trace_id` в SQL-запросы миграций. Это позволяет связать выполнение DDL в логах базы данных с конкретным запуском пайплайна в CI/CD или сервисом миграций.

```sql
-- Пример запроса, видимого в pg_stat_activity
ALTER TABLE users ADD COLUMN age INT; /* traceparent='00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01' */
```

### Сценарий 4: Метрики инструментов (Flyway / Atlas)

Современные инструменты экспортируют собственные метрики:
- `flyway_release_info`: Версия текущей схемы.
- `atlas_migration_duration_seconds`: Время выполнения.
- `atlas_migration_errors_total`: Счетчик ошибок.

## Дополнительная информация

### Рекомендации

- **Throttle (Троттлинг):** При обнаружении нагрузки на I/O выше 80% или лага репликации > 30с, процесс миграции данных должен автоматически замедляться (увеличение `sleep` между батчами или пауза OSC-инструмента).
- **War Room Dashboard:** Создайте в Grafana дашборд, объединяющий метрики ресурсов БД, статус блокировок и прогресс миграции (`pg_stat_progress`).
- **Audit-логи:** Храните историю выполнения миграций с указанием исполнителя (через `SET application_name`) для быстрого расследования инцидентов.
- **Линтинг схем:** Интегрируйте инструменты мониторинга дрейфа схемы в CI/CD для обнаружения изменений, сделанных в обход процесса миграций.

### Смежные темы

- **[Типовые сценарии миграций](scenarios.md)** — реализация батчинга и безопасных DDL.
- **[Безопасные массовые операции](../safe_large_scale_data_modification.md)** — глубокий разбор пакетной обработки и лимитов.
- **[Стратегии отката (Rollback)](rollback_strategies.md)** — действия при срабатывании алертов.
- **[Метрики SRE](../../Concepts/sre_concepts_main.md)** — общие принципы надежности систем.
- **[Наблюдаемость PostgreSQL](../../Databases/PostgreSQL/Operations/observability.md)** — специфика сбора метрик и логов.
