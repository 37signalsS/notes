# Наблюдаемость баз данных (Database Observability)

**Актуально для:** PostgreSQL 14–17, MySQL 8.0/8.4, Prometheus 3.13.x, Grafana Alerting 11.x, Zabbix 7.0 LTS/7.4, Netdata 2.x, Loki 3.x, Linux 5.4+ (PSI)

---

## Определения

- **Database Observability (Наблюдаемость БД)** — способность понимать внутреннее состояние базы данных через её внешние сигналы: метрики, логи, трейсы и события.

- **Query Performance (Производительность запросов)** — скорость выполнения SQL-запросов, включая latency, throughput, количество строк, обработанных за запрос.

- **Connection Pool (Пул соединений)** — кэш активных соединений к БД, сокращающий overhead на установку нового соединения для каждого запроса.

- **Replication Lag (Задержка репликации)** — задержка между записью в primary и применением той же записи на replica.

- **Lock contention (Конкуренция за блокировки)** — состояние, при котором несколько транзакций ожидают освобождения ресурсов, заблокированных другими транзакциями.

- **Slow Query (Медленный запрос)** — запрос, время выполнения которого превышает установленный порог (обычно 100ms–1s в зависимости от контекста).

- **Deadlock (Взаимная блокировка)** — состояние, при котором две или более транзакций блокируют друг друга, ожидая освобождения ресурсов, занятых противоположной стороной.

- **VACUUM (Уборка)** — процесс очистки неактуальных версий строк (tuples) в PostgreSQL, предотвращающий раздувание таблиц.

- **WAL (Write-Ahead Log)** — журнал предзаписи, обеспечивающий durability и служащий источником для репликации и PITR.

- **Buffer Pool Hit Ratio** — доля запросов, найденных в buffer pool (кэше) без обращения к диску.

- **Checkpoint** — процесс сброса изменённых страниц из buffer pool на диск, обеспечивающий консистентность и ускоряющий recovery.

---

## Архитектура и принципы

### Пайплайн сбора сигналов

```
[DB Instance]
    │
    ├─── Метрики ──► [Exporter] ──► [Prometheus] ──► [Grafana / Alertmanager]
    │
    ├─── Логи ─────► [Loki / Promtail] ──► [Grafana] ──► [Alertmanager]
    │
    ├─── Трейсы ───► [OTel Collector] ──► [Grafana Tempo]
    │
    └─── События ──► [Системные логи / journalctl] ──► [Loki]
```

### Критические зависимости

**NTP / синхронизация времени**
- Без синхронизированных часов между DB, exporter и Prometheus correlation метрик и трейсов невозможна. Используйте chrony или systemd-timesyncd. Дрейг >1s искажает `pg_stat_activity` и replication lag.
- Для корреляции логов и метрик время на exporter и на DB должно совпадать.

**Scrape reliability**
- Scrape interval 15s — стандарт для активных инстансов. 60s — минимум для пассивных реплик.
- Если scrape пропускает данные, `absent_over_time()` создаст ложные алерты. Настройте `scrape_timeout` меньше `scrape_interval`.

**Label hygiene**
- Используйте `application_name` или `job` для идентификации сервиса. Избегайте high-cardinality лейблов в метриках exporters (trace_id, session_id).
- При изменении labels или job name старая серия метрик исчезает (`absent()`), что может сломать алерты.

### Recording rules

Запросы к `pg_stat_statements` и `pg_stat_activity` могут быть ресурсоёмкими. Используйте recording rules:

```yaml
groups:
  - name: db.rules
    rules:
      - record: db:connections:active
        expr: sum(pg_stat_activity_count{state="active"}) by (instance, datname)

      - record: db:connections:utilization
        expr: sum(pg_stat_activity_count{state="active"}) by (instance, datname)
            / pg_settings_max_connections

      - record: db:replication:lag_seconds
        expr: pg_stat_replication_lag_seconds

      - record: db:cache:hit_ratio
        expr: (
          sum(pg_statio_user_tables_heap_blks_hit + pg_statio_user_tables_idx_blks_hit)
          /
          sum(pg_statio_user_tables_heap_blks_hit + pg_statio_user_tables_idx_blks_hit
              + pg_statio_user_tables_heap_blks_read + pg_statio_user_tables_idx_blks_read)
        ) by (instance)
```

---

## Базовые концепции

### Четыре столпа наблюдаемости БД

| Столп | Что показывает | Примеры метрик |
| :--- | :--- | :--- |
| **Latency** | Задержка выполнения операций | Query duration P50/P95/P99, connection time |
| **Throughput** | Пропускная способность | Queries per second, transactions per second, rows read/written |
| **Errors** | Частота сбоев | Deadlocks, connection failures, timeout errors, constraint violations |
| **Saturation** | Приближение к лимитам | Connection pool utilization, disk I/O, lock waits, replication lag |

### Иерархия диагностики БД

При расследовании проблемы с БД двигайтесь по иерархии:

```
Instance Level (узел)
  └── Database Level (база)
      └── Schema Level (схема)
          └── Table Level (таблица)
              └── Query Level (запрос)
                  └── Execution Plan (план выполнения)
```

**Принцип:** Начните с instance-level метрик (CPU, memory, disk, connections). Если они в норме — опускайтесь на уровень запросов.

### Метрики по уровням

#### Instance Level (Уровень инстанса)

| Категория | Метрики | Почему важно |
| :--- | :--- | :--- |
| **Ресурсы** | CPU, RAM, Disk I/O, Disk usage | Дефицит ресурсов — частая причина деградации |
| **Соединения** | Active connections, connection pool utilization, connection errors | Истощение пула соединений — частая причина отказов |
| **Сеть** | Network latency, packets retransmitted, connections refused | Сетевые проблемы между приложением и БД |
| **Репликация** | Replication lag, replication slot usage, WAL sending rate | Отставание реплик влияет на read scalability и DR |

#### Database Level (Уровень БД)

| Категория | Метрики | Почему важно |
| :--- | :--- | :--- |
| **Транзакции** | Transactions per second, commit rate, rollback rate | Высокий rollback rate — признак проблем в приложении |
| **Локи** | Lock waits, deadlocks, lock duration | Blocking transactions — bottleneck |
| **Кэш** | Buffer pool hit ratio, cache efficiency | Низкий hit ratio — все запросы идут на диск |
| **WAL** | WAL generation rate, WAL archive lag | Высокий WAL rate — интенсивная запись, может влиять на replication |

#### Query Level (Уровень запросов)

| Категория | Метрики | Почему важно |
| :--- | :--- | :--- |
| **Latency** | Query duration P50/P95/P99 | Высокая latency — медленные запросы |
| **Throughput** | Queries per second per query | Рост QPS — новые узкие места |
| **Rows** | Rows examined vs rows returned | Большое разрыв — missing index |
| **Errors** | Timeout errors, constraint violations | Ошибки приложения из-за БД |

---

## Практические сценарии

### Сценарий 1: Диагностика медленных запросов в PostgreSQL

**Ситуация:** P99 latency сервиса вырос с 50ms до 2s. Подозрение на медленные запросы.

**Шаги диагностики:**

```sql
-- 1. Найти медленные запросы (pg_stat_statements)
SELECT
  query,
  calls,
  mean_exec_time,
  max_exec_time,
  stddev_exec_time,
  rows / calls AS avg_rows
FROM pg_stat_statements
WHERE mean_exec_time > 100  -- медленнее 100ms
ORDER BY mean_exec_time DESC
LIMIT 10;

-- → query: SELECT * FROM orders WHERE user_id = $1 AND status = 'active'
-- → calls: 15420
-- → mean_exec_time: 850.5
-- → max_exec_time: 3200.1
-- → stddev_exec_time: 450.2
-- → avg_rows: 15400  -- ← возвращает слишком много строк

-- 2. Проверить план выполнения
EXPLAIN ANALYZE SELECT * FROM orders WHERE user_id = 12345 AND status = 'active';

-- → Seq Scan on orders  (cost=0.00..15420.00 rows=15400 width=128)
-- →   Filter: (user_id = 12345 AND status = 'active')
-- →   Rows Removed by Filter: 15400
-- → Planning Time: 0.05 ms
-- → Execution Time: 1.2 s  -- ← Seq Scan, нет индекса

-- 3. Проверить наличие индекса
\d orders
-- → Table "public.orders"
-- →   Column   |  Type   | Collation | Nullable | Default
-- →   user_id   | integer |           | not null |
-- →   status    | text    |           | not null |
-- →   created_at| timestamp|          | not null |
-- → Indexes: "orders_pkey" PRIMARY KEY (id)

-- 4. Создать composite index
CREATE INDEX CONCURRENTLY idx_orders_user_id_status ON orders(user_id, status);
-- → CREATE INDEX

-- 5. Проверить улучшение
EXPLAIN ANALYZE SELECT * FROM orders WHERE user_id = 12345 AND status = 'active';
-- → Index Scan using idx_orders_user_id_status on orders
-- →   Index Cond: (user_id = 12345 AND status = 'active')
-- → Execution Time: 0.8 ms  -- ← улучшение в 1500 раз
```

### Сценарий 2: Диагностика исчерпания пула соединений

**Ситуация:** Приложение получает `connection pool exhausted`, новые запросы не могут получить соединение.

```sql
-- 1. Проверить активные соединения
SELECT
  state,
  COUNT(*) as count,
  MAX(now() - state_change) as max_duration
FROM pg_stat_activity
GROUP BY state
ORDER BY count DESC;

-- → state      | count | max_duration
-- → active     | 198   | 00:05:30
-- → idle       | 2     | 00:00:02
-- → idle in transaction | 15 | 00:02:15  -- ← проблема: долгие транзакции

-- 2. Найти висячие транзакции
SELECT
  pid,
  state,
  query,
  now() - state_change as duration,
  wait_event_type,
  wait_event
FROM pg_stat_activity
WHERE state = 'idle in transaction'
  AND now() - state_change > interval '1 minute'
ORDER BY duration DESC;

-- → pid    | state              | query                                    | duration  | wait_event
-- → 12345  | idle in transaction| BEGIN; SELECT pg_sleep(1000); -- утечка | 00:05:30  | ClientRead

-- 3. Проверить настройки пула приложения
-- В connection pool config (HikariCP, pgx, etc.)
-- maxPoolSize = 20  -- ← слишком мало для пиковой нагрузки
-- connectionTimeout = 30s

-- 4. Короткое решение: увеличить пул
ALTER SYSTEM SET max_connections = 200;
SELECT pg_reload_conf();

-- 5. Долгое решение: фикс утечки соединений в приложении
```

### Сценарий 3: Диагностика replication lag

**Ситуация:** Replica отстает от primary на 45 секунд. Read-операции возвращают устаревшие данные.

```sql
-- На primary
SELECT
  client_addr,
  state,
  sent_lsn,
  write_lsn,
  flush_lsn,
  replay_lsn,
  (pg_wal_lsn_diff(sent_lsn, replay_lsn) / 1024 / 1024) AS lag_mb
FROM pg_stat_replication;

-- → client_addr | state | sent_lsn | write_lsn | flush_lsn | replay_lsn | lag_mb
-- → 10.0.0.20   | streaming | 0/1A000000 | 0/1A000000 | 0/1A000000 | 0/19FFFFF | 1.5

-- На replica
SELECT
  pg_size_pretty(pg_wal_lsn_diff(
    (SELECT sent_lsn FROM pg_stat_wal_receiver),
    pg_current_wal_lsn()
  )) AS replication_lag;

-- → 1.5 MB

-- Причины и решения:
-- 1. Высокая write нагрузка на primary
--    → Решение: увеличить wal_buffers, оптимизировать write-heavy запросы
-- 2. Медленная disk I/O на replica
--    → Решение: использовать SSD, проверить iostat
-- 3. Долгая транзакция на replica
--    → Решение: завершить долгие запросы на replica
-- 4. Отставание после failover
--    → Решение: pglogical или logical replication для selective replication
```

### Сценарий 4: Мониторинг connection pool (HikariCP)

```yaml
# application.yml
spring:
  datasource:
    hikari:
      maximum-pool-size: 20
      minimum-idle: 5
      connection-timeout: 30000
      idle-timeout: 600000
      max-lifetime: 1800000
      leak-detection-threshold: 60000  # 60 секунд — утечка

# Prometheus метрики через micrometer
management:
  metrics:
    enable:
      hikari: true

# Проверка метрик в Prometheus
# hikaricp_connections_active
# hikaricp_connections_idle
# hikaricp_connections_pending
# hikaricp_connection_acquire_time_seconds_max
```

### Сценарий 5: Мониторинг slow query через логи (Loki/Promtail)

**Ситуация:** `pg_stat_statements` не показывает все запросы, или требуется исторический анализ slow queries за недели/месяцы.

**Архитектура:**
```
[PostgreSQL slow_query_log] → [Promtail] → [Loki] → [Grafana Alerting]
```

**Настройка PostgreSQL:**
```sql
ALTER SYSTEM SET log_min_duration_statement = 250;  -- ms
ALTER SYSTEM SET log_line_prefix = '%t [%p] %q%u@%d ';
SELECT pg_reload_conf();
```

**Promtail configuration:**
```yaml
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: postgres
    static_configs:
      - targets: [localhost]
        labels:
          job: postgres
          __path__: /var/log/postgresql/postgresql-*.log
    pipeline_stages:
      - regex:
          expression: '^.*duration:\s+(?P<duration>\d+\.\d+)\s+ms\s+statement:\s+(?P<query>.+)$'
      - labels:
          duration: ""
      - metrics:
          pg_slow_query_duration_seconds:
            type: Histogram
            description: "Slow query duration from logs"
            source: duration
            buckets: [0.1, 0.25, 0.5, 1, 5, 10, 30, 60]
          pg_slow_query_total:
            type: Counter
            description: "Total slow queries"
```

**LogQL запросы:**
```logql
# Топ-10 самых частых медленных запросов за час
sum by (query) (
  count_over_time({job="postgres"} |= "duration:" [1h])
)
* on(query) group_left() avg_over_time({job="postgres"} |= "duration:" [1h])

# Распределение длительности
histogram_quantile(0.99,
  sum by (le) (rate(pg_slow_query_duration_seconds_bucket[5m]))
)

# Алерт на аномальный рост slow queries
rate(pg_slow_query_total[10m]) > 5
```

Для детального разбора slow query log analysis см. [Log-based Exporters: mtail и grok_exporter](../../Prometheus/Exporters/log_based_exporters.md).

---

## Метрики и алерты

### Обязательные метрики

#### PostgreSQL (pg_exporter / postgres_exporter)

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `pg_up` | Доступен ли инстанс | < 1 → SEV1 |
| `pg_stat_activity_count` | Активные соединения | > 80% max_connections |
| `pg_locks_count` | Количество локов | Резкий рост |
| `pg_deadlocks_total` | Взаимные блокировки | > 0 за 5 минут → SEV2 |
| `pg_replication_slot_used` | Использование слотов репликации | > 80% max_slot_wal_keep_size |
| `pg_wal_size` | Размер WAL | > 80% disk |
| `pg_stat_database_tuples_inserted` | Вставки в секунду | Резкое изменение → anomaly |
| `pg_stat_database_tuples_fetched` | Чтение строк | Резкое изменение |
| `pg_stat_database_blk_read_time` | Время чтения блоков с диска | > 100ms → disk I/O issue |
| `pg_stat_database_blk_write_time` | Время записи блоков на диск | > 100ms → disk I/O issue |
| `pg_stat_user_tables_seq_scan` | Последовательные сканирования | Резкий рост → missing index |
| `pg_statio_user_tables_heap_blks_hit` | Cache hit ratio | < 0.99 → buffer pool недостаточен |
| `pg_stat_user_tables_idx_blks_hit` | Index cache hit ratio | < 0.99 → index bloat |
| `pg_stat_statements_mean_exec_time` | Среднее время запроса | > 500ms → slow query |
| `pg_stat_statements_calls` | Количество вызовов запроса | Резкий рост |

#### MySQL (mysqld_exporter)

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `mysql_up` | Доступен ли инстанс | < 1 → SEV1 |
| `mysql_global_status_threads_connected` | Активные соединения | > 80% max_connections |
| `mysql_global_status_threads_running` | Выполняющиеся потоки | > 50 |
| `mysql_global_status_slow_queries` | Медленные запросы | > 10 за 5 минут |
| `mysql_global_status_aborted_clients` | Прерванные соединения | Резкий рост |
| `mysql_global_status_innodb_row_lock_time_avg` | Среднее время лока | > 1000ms |
| `mysql_global_status_innodb_row_lock_waits` | Ожидания лока | > 0 за 5 минут |
| `mysql_global_status_replication_lag` | Задержка репликации (секунды) | > 30 секунд |
| `mysql_global_variables_innodb_buffer_pool_pages_dirty` | Грязные страницы | > 25% buffer pool |
| `mysql_global_status_created_tmp_disk_tables` | Временные таблицы на диске | Резкий рост → нужно оптимизировать |

### Примеры алертов

```yaml
# PostgreSQL: исчерпание пула соединений
- alert: PostgreSQLConnectionPoolExhausted
  expr: |
    pg_stat_activity_count{state="active"}
    /
    pg_settings_max_connections
    > 0.8
  for: 5m
  labels:
    severity: page
  annotations:
    summary: "PostgreSQL connection pool > 80% ({{ $value | humanizePercentage }})"
    runbook_url: "https://wiki.internal/runbooks/postgres-connection-pool"

# PostgreSQL: deadlock
- alert: PostgreSQLDeadlock
  expr: increase(pg_deadlocks_total[5m]) > 0
  for: 0m
  labels:
    severity: page
  annotations:
    summary: "PostgreSQL deadlock detected"
    runbook_url: "https://wiki.internal/runbooks/postgres-deadlock"

# PostgreSQL: репликация отстает
- alert: PostgreSQLReplicationLag
  expr: |
    pg_stat_replication_lag_seconds > 30
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "PostgreSQL replication lag {{ $value }}s"
    runbook_url: "https://wiki.internal/runbooks/postgres-replication-lag"

# PostgreSQL: медленный запрос
- alert: PostgreSQLSlowQuery
  expr: |
    pg_stat_statements_mean_exec_time{query!~"autovacuum"} > 500
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Slow query detected: {{ $labels.query }} ({{ $value }}ms)"
    runbook_url: "https://wiki.internal/runbooks/postgres-slow-query"

# MySQL: исчерпание пула соединений
- alert: MySQLConnectionPoolExhausted
  expr: |
    mysql_global_status_threads_connected / mysql_global_variables_max_connections > 0.8
  for: 5m
  labels:
    severity: page
  annotations:
    summary: "MySQL connection pool > 80% ({{ $value | humanizePercentage }})"
    runbook_url: "https://wiki.internal/runbooks/mysql-connection-pool"
```

---

## Устранение неполадок

### Высокий latency при низком CPU

**Возможные причины:**
- Чтение с диска из-за низкого buffer pool hit ratio
- Медленная disk I/O (проверьте `iostat -xz 1`, PSI через `/proc/pressure/io`)
- Блокировки (`pg_locks`, `information_schema.innodb_lock_waits`)
- Долгие транзакции, мешающие VACUUM

**Диагностика:**
```sql
-- PostgreSQL: проверка cache hit ratio
SELECT
  sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) AS ratio
FROM pg_statio_user_tables;

-- PostgreSQL: текущие ожидания
SELECT wait_event_type, wait_event, count(*)
FROM pg_stat_activity
WHERE wait_event_type IS NOT NULL
GROUP BY wait_event_type, wait_event;

-- MySQL: InnoDB status
SHOW ENGINE INNODB STATUS\G
```

**Решение:**
- Увеличьте `shared_buffers` (PostgreSQL) или `innodb_buffer_pool_size` (MySQL)
- Проверьте индексы для устранения Seq Scan
- Завершите долгие транзакции через `pg_terminate_backend()`

---

### Скачки WAL / replication lag

**Возможные причины:**
- Массовая загрузка данных без batching
- Медленная disk I/O на replica
- Долгие транзакции на replica, блокирующие replay
- Отсутствие `pg_stat_statements` не позволяет найти write-heavy запросы

**Диагностика:**
```sql
-- На primary: WAL generation rate
SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0') / 1024 / 1024 AS wal_mb;

-- На replica: replay lag
SELECT pg_last_wal_replay_lsn() AS replayed_lsn,
       pg_last_wal_receive_lsn() AS received_lsn;
```

**Решение:**
- Используйте `synchronous_commit = off` для массовых загрузок (с осторожностью)
- Увеличьте `max_wal_size` и `wal_buffers`
- Вынесите WAL на отдельные NVMe-диски
- Для аналитики используйте отдельные реплики

---

### Ложные алерты из-за пропусков в данных

**Причина:** scrape timeout, network partition, перезагрузка exporter.

**Решение:**
- В алертах используйте `absent_over_time()` для проверки наличия данных:
  ```promql
  pg_up == 0
  ```
- Исключайте периоды обслуживания из baseline через `ALERTS`:
  ```promql
  avg_over_time(metric[1h] unless ALERTS{alertname="HighErrorRate"}[1h])
  ```
- Проверяйте `up{job="postgres"}` для подтверждения доступности exporter

---

### Alert fatigue от медленных запросов

**Причина:** порог `> 500ms` срабатывает на каждый запрос.

**Решение:**
- Используйте `for: 5m` для подавления шума
- Исключайте autovacuum и известные maintenance-запросы через `query!~"autovacuum|VACUUM|ANALYZE"`
- Группируйте алерты по `query` fingerprint, чтобы не получать 100 алертов на один и тот же запрос

---

### Contaminated baseline

**Причина:** baseline включает периоды аномалий (инциденты, релизы).

**Решение:**
- Исключайте периоды с активными инцидентами из baseline через `ALERTS`:
  ```promql
  avg_over_time(metric[1h] unless ALERTS{alertname="HighErrorRate"}[1h])
  ```
- Используйте seasonal baseline только после минимум 7 дней чистых данных
- Пересчитывайте baseline после каждого значимого изменения (релиз, изменение индексов)

---

## Лучшие практики

### Проектирование

1. **Connection pool на стороне приложения:** Используйте HikariCP (Java), pgxpool (Go), asyncpg pool (Node.js). Избегайте создания нового соединения на каждый запрос.

2. **Connection string с параметрами:**
   - `connect_timeout=10` — таймаут на подключение
   - `tcp_keepalives_idle=60` — keepalive для detection разрывов
   - `application_name=payment-service` — идентификация в `pg_stat_activity`

3. **Prepared statements:** Переиспользуйте планы запросов. Снижают overhead на парсинг.

4. **Индексы для горячих запросов:** Используйте `pg_stat_statements` для идентификации запросов, стоящих оптимизации.

### Наблюдаемость

1. **pg_stat_statements обязателен:** Активируйте расширение на всех инстансах.

2. **Auto-explain для медленных запросов:**
   ```sql
   ALTER SYSTEM SET auto_explain.log_min_duration = 100;  -- ms
   ALTER SYSTEM SET auto_explain.log_analyze = true;
   SELECT pg_reload_conf();
   ```

3. **Сбор метрик через exporters:**
   - PostgreSQL: `postgres_exporter` или `pg_exporter`
   - MySQL: `mysqld_exporter`
   - MongoDB: `mongodb_exporter`

4. **Мониторинг через логи:** Для исторического анализа slow queries используйте Loki с Promtail/grok_exporter (см. Сценарий 5).

5. **Структурированные логи:** Включите `log_line_prefix` с `application_name`, `client_addr`, `duration`:
   ```sql
   ALTER SYSTEM SET log_line_prefix = '%t [%p-%l] %q%u@%d ';
   ALTER SYSTEM SET log_min_duration_statement = 100;  -- ms
   SELECT pg_reload_conf();
   ```

6. **Резервное копирование:**
   - **Physical backup:** `pg_basebackup`, `xtrabackup` (MySQL).
   - **Logical backup:** `pg_dump`, `mysqldump`.
   - **PITR:** WAL archiving (PostgreSQL) / binary log (MySQL).

### Эксплуатация

1. **Не делайте DDL в production без плана:** `ALTER TABLE` может заблокировать таблицу на часы. Используйте `ALTER TABLE ... ALGORITHM=INPLACE, LOCK=NONE` (MySQL) или `CONCURRENTLY` (PostgreSQL).

2. **Регулярное обслуживание:**
   - PostgreSQL: `VACUUM ANALYZE` (autovacuum), `REINDEX` при необходимости.
   - MySQL: `ANALYZE TABLE`, `OPTIMIZE TABLE` (осторожно, блокирует).

3. **Capacity planning:** Мониторьте рост размера БД, количество таблиц, количество индексов. Планируйте upgrades за квартал.

4. **Runbook для DBA:** Документируйте процедуры развертывания, escalation path и контакты на_call. Каждый алерт должен иметь ссылку на runbook.

---

## Инструменты

| Категория | Инструменты | Назначение |
| :--- | :--- | :--- |
| **Exporters** | postgres_exporter, pg_exporter, mysqld_exporter, mongodb_exporter | Сбор метрик в Prometheus |
| **Monitoring** | Prometheus + Grafana, Zabbix, Netdata | Дашборды, алерты, исторические данные |
| **Logs** | Loki, Promtail, grok_exporter, mtail | Парсинг slow query логов, корреляция |
| **Query Analysis** | pg_stat_statements, auto_explain, EXPLAIN ANALYZE, pgbadger | Анализ запросов |
| **Change Data Capture** | Debezium, pglogical | Стриминг изменений БД |
| **Backup** | pgBackRest, WAL-G, Percona XtraBackup | Резервное копирование |
| **HA** | Patroni, Repmgr, Orchestrator | Репликация и failover |
| **Proxy** | PgBouncer, ProxySQL, HAProxy | Connection pooling, load balancing |
| **Security** | Vault, pgcrypto | Управление секретами |

---

## Граничные случаи

### Высоконагруженные OLTP системы

**Проблема:** 10k+ TPS, миллионы соединений. Обычный connection pooling не справляется.

**Решение:**
- PgBouncer в режиме transaction pooling (не session pooling).
- Используйте fewer connections, но longer duration.
- Application-side connection pool с warmup.

### Large objects / BLOBs

**Проблема:** Хранение изображений, видео, файлов в БД. Размер БД растет экспоненциально.

**Решение:**
- Храните BLOBs во внешнем файловом хранилище.
- В БД храните только metadata и ссылки.
- Используйте bytea для small BLOBs (< 1MB).

### Sharding

**Проблема:** Одна инстанс не справляется с нагрузкой.

**Решение:**
- Horizontal partitioning (sharding) по ключу (user_id, tenant_id).
- Vitess (MySQL), Citus (PostgreSQL) для управления шардами.
- Мониторинг lag между шардами.

### Multi-master replication

**Проблема:** Нужна запись в несколько регионов.

**Решение:**
- Используйте eventual consistency модели.
- Мониторьте конфликты (например, через trigger-based CDC).
- Рассмотрите distributed SQL (CockroachDB, YugabyteDB).

---

## См. также

- **[Четыре столпа Observability](./four_pillars_of_observability.md)** — метрики, логи, трейсы, события.
- **[Метрики глубокий dive](./metrics_deep_dive.md)** — типы метрик, агрегация, процентили.
- **[Логи глубокий dive](./logs_deep_dive.md)** — структурированные логи, парсинг, корреляция.
- **[Трейсы глубокий dive](./traces_deep_dive.md)** — distributed tracing, OpenTelemetry.
- **[Meta-Monitoring](./meta-monitoring.md)** — мониторинг самой системы мониторинга.
- **[Проектирование высоконагруженного мониторинга](./designing_high-load_monitoring_in_distributed_systems.md)** — retention tiers, cost optimization.
- **[Prometheus](../../Prometheus/overview.md)** — сбор и хранение метрик.
- **[Grafana](../../Grafana/grafana_overview.md)** — визуализация и алертинг.
- **[Концепции SRE](../sre_concepts_main.md)** — SLO/SLI/SLA, error budgets.
- **[Наблюдаемость PostgreSQL](./PostgreSQL/Operations/observability.md)** — wait events, pg_stat_statements, корреляция с трейсами.
- **[Диагностика дисковых узких мест](./db_disk_bottleneck_troubleshooting.md)** — I/O wait, PSI, wait events.
- **[Log-based Exporters](../../Prometheus/Exporters/log_based_exporters.md)** — mtail, grok_exporter, парсинг slow query логов.
