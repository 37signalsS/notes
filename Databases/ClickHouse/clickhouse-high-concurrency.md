# ClickHouse — Высокая конкурентность

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**Query Cache** — серверный кэш результатов запросов: повторный идентичный запрос (по AST) возвращается из кэша без выполнения. Has in-memory и on-disk backens.

**Query Cache on Disk** — дополнение к in-memory кэшу: результаты сохраняются на файловую подсистему через filesystem cache. Настраивается через `query_cache_on_disk_cache_name`.

**Query Cache Tag** — метка для групповой инвалидации кэша. Применяется через `query_cache_tag` и `SYSTEM DROP QUERY CACHE 'tag'`.

**Parallel Replicas** — распределение выполнения одного запроса по нескольким репликам одного шарда для ускорения сканирования больших таблиц.

**enable_parallel_replicas** — настройка: `0` (выкл), `1` (вкл), `2` (force — throw exception if parallel replicas not used).

**as_prefer** — при включении (default) локальная реплика всегда включается в набор для параллельного чтения.

**max_parallel_replicas** — максимальное количество реплик для параллельного выполнения запроса на шарде.

**Connection Pooling** — переиспользование соединений к ClickHouse для снижения накладных расходов на установку TCP/TLS. Реализуется на стороне клиента или прокси.

**max_concurrent_queries** — лимит одновременно выполняемых запросов на сервере (0 = unlimited).

**queue_max_wait_ms** — время ожидания слота в очереди при достижении `max_concurrent_queries` (default 0 = immediate rejection с `TOO_MANY_SIMULTANEOUS_QUERIES`).

**max_concurrent_queries_for_user** — лимит одновременных запросов на одного пользователя.

**max_concurrent_queries_for_all_users** — сквозной лимит для всех пользователей (ClickHouse Cloud default: 1000).

**max_waiting_queries** — лимит запросов в очереди ожидания (`SHOW PROCESSLIST`).

**connection_pool_max_wait_ms** — таймаут ожидания соединения из пула (session-level, per replica).

## Основные концепции

### Query Cache

Кэш результатов SELECT-запросов на сервере. Ключ = нормализованный AST + параметры. Поддерживает in-memory и on-disk backend.

**Конфигурация (config.xml):**
```xml
<clickhouse>
    <query_cache>
        <max_entries>1024</max_entries>
        <max_size_in_bytes>1073741824</max_size_in_bytes>       <!-- 1 GB -->
        <max_entry_size_in_bytes>1048576</max_entry_size_in_bytes>  <!-- 1 MB -->
        <max_entry_size_in_rows>30000000</max_entry_size_in_rows>
    </query_cache>
</clickhouse>
```

**On-disk query cache:**
```xml
<clickhouse>
    <query_cache>
        <!-- ... -->
        <query_cache_on_disk_cache_name>query_results</query_cache_on_disk_cache_name>
        <!-- query_cache_on_disk_codec: ZSTD(3) by default -->
    </query_cache>
</clickhouse>
```

**Настройки сессии (in-memory + on-disk):**
```sql
-- Включить использование кэша
SET use_query_cache = 1;

-- Мин. длительность запроса для кэширования (мс)
SET query_cache_min_query_duration = 0;

-- Мин. количество выполнений до кэширования
SET query_cache_min_query_runs = 1;

-- TTL записи в кэше (секунды)
SET query_cache_ttl = 60;

-- Тег для инвалидации
SET query_cache_tag = 'dashboard_sales';

-- Запись в кэш (in-memory, default 1)
SET enable_writes_to_query_cache = 1;

-- Чтение из кэша (in-memory, default 1)
SET enable_reads_from_query_cache = 1;

-- On-disk cache (default 1)
SET enable_writes_to_query_cache_on_disk = 1;
SET enable_reads_from_query_cache_on_disk = 1;

-- Кэш для подзапросов
SET query_cache_for_subqueries = 1;

-- Разделять кэш между пользователями (0 = общий; не рекомендуется по соображениям безопасности)
SET query_cache_share_between_users = 0;
```

**Управление кэшем:**
```sql
-- Очистить весь кэш (in-memory + on-disk)
SYSTEM CLEAR QUERY CACHE;

-- Удалить записи с тегом
SYSTEM DROP QUERY CACHE 'dashboard_sales';

-- Содержимое in-memory кэша
SELECT * FROM system.query_cache;
```

**Мониторинг (devops/sre):**
```sql
-- Hit/miss ratio за интервал
SELECT
    event, value
FROM system.events
WHERE event IN ('QueryCacheHits', 'QueryCacheMisses',
                'QueryCacheOnDiskHits', 'QueryCacheAgeSeconds')
ORDER BY event;

-- Размер кэша в реальном времени
SELECT *
FROM system.metrics
WHERE metric IN ('QueryCacheEntries', 'QueryCacheBytes');

-- Запросы, использовавшие кэш
SELECT
    query_id,
    query_cache_usage,
    query_duration_ms
FROM system.query_log
WHERE query_cache_usage != 'None'
ORDER BY event_time DESC
LIMIT 10;
```

**Ограничения:**
- Кэшируются только standalone `SELECT` (не запросы в视图ах через `CREATE VIEW AS SELECT ... SETTINGS use_query_cache = true`).
- Запросы с недетерминированными функциями (`now()`, `rand()`) не кэшируются.
- Кэш инвалидируется при изменении данных в таблицах, участвующих в запросе.
- On-disk entries — элементы filesystem cache, subject to LRU eviction; используйте выделенный filesystem cache для экономии `SYSTEM CLEAR QUERY CACHE`.

### Parallel Replicas

Распределение одного запроса по репликам шарда. Каждая реплика обрабатывает свою часть данных. Инициатор координирует выполнение.

**Настройки:**
```sql
-- Включить (0=off, 1=on, 2=force — exception if not used)
SET enable_parallel_replicas = 1;

-- Кол-во реплик для параллельного выполнения
SET max_parallel_replicas = 4;

-- Ключ распределения (по умолчанию — хеш ключа сортировки)
SET parallel_replicas_custom_key = 'user_id';

-- Мин. строк на реплику (чтобы не дробить на мелкие куски)
SET parallel_replicas_min_number_of_rows_per_replica = 1000000;

-- Кластер для параллельных реплик (если не указан — текущий)
SET cluster_for_parallel_replicas = 'logs_cluster';

-- Всегда включать локальную реплику (default 1)
SET as_prefer = 1;
```

**Мониторинг:**
```sql
-- Профиль событий последнего запроса
SELECT event, value
FROM system.query_log
ARRAY JOIN ProfileEvents
WHERE type = 'QueryFinish'
  AND event LIKE 'ParallelReplicas%'
ORDER BY event_time DESC
LIMIT 10;
```

Профильные события: `ParallelReplicasUsedCount`, `ParallelReplicasTotalCount`.

**Ограничения:**
- Не работает с `FINAL`.
- Проекции не используются при параллельных репликах.
- Высокая кардинальность ключа замедляет распределение.
- `parallel_replicas_count` — internal setting; не использовать напрямую (автоматически устанавливается инициатором).

**Когда использовать:**
- Большие сканирования (десятки миллиардов строк) на реплицированных таблицах.
- Не использовать для точечных запросов — накладные расходы на координацию превысят выигрыш.

### Connection Pooling

ClickHouse не имеет встроенного пула соединений на сервере; пулинг реализуется на стороне клиента или прокси.

**На стороне клиента:**
- `clickhouse-client` — пул через `--connection_pool_size`.
- JDBC/ODBC драйверы — встроенные пулы.
- HTTP — keep-alive соединения.

**Прокси (рекомендуется для продакшена):**
- **CHProxy** — кэширующий прокси с пулом соединений.
- **HAProxy / nginx** — балансировка и keep-alive.

**Настройки сервера:**
```xml
<!-- config.xml -->
<clickhouse>
    <max_connections>4096</max_connections>          <!-- default 100 -->
    <max_concurrent_queries>200</max_concurrent_queries>  <!-- default 0=unlimited -->
    <queue_max_wait_ms>10000</queue_max_wait_ms>     <!-- bounded wait при overload -->
    <max_waiting_queries>1000</max_waiting_queries>
    <listen_host>0.0.0.0</listen_host>
    <http_port>8123</http_port>
    <tcp_port>9000</tcp_port>
</clickhouse>
```

Подробнее: [Настройка лимитов и пулов](./clickhouse-capacity-upgrades.md).

## Архитектура конкурентного доступа

ClickHouse использует **многопоточную обработку запросов** на уровне одного сервера:

- `max_threads` — верхний лимит потоков (default = CPU cores). ClickHouse auto-масштабирует вниз для малых данных.
- `merge_tree_min_rows_for_concurrent_read` (default 163840) и `merge_tree_min_bytes_for_concurrent_read` (default 2097152) — пороги для активации parallel read.
- Для удалённых ФС: `merge_tree_min_rows_for_concurrent_read_for_remote_filesystem`, `merge_tree_min_bytes_for_concurrent_read_for_remote_filesystem`.

**Сервер-сайд конкурентность:**
- `max_concurrent_queries` — admission control на сервере.
- `max_concurrent_queries_for_user` — лимит на пользователя.
- `max_concurrent_queries_for_all_users` — сквозной лимит (Cloud default: 1000).
- `max_concurrent_select_queries` / `max_concurrent_insert_queries` — выборочные лимиты.
- `queue_max_wait_ms` — bounded wait при переполнении (default 0 = immediate `TOO_MANY_SIMULTANEOUS_QUERIES`).
- `QUERY` resource — workload-aware scheduling (burst control, rate limiting).
- `connection_pool_max_wait_ms` — таймаут ожидания соединения из пула (session-level, per replica); истекает с `NO_FREE_CONNECTION`.

## Практические сценарии

### Кэширование дашбордов (in-memory)

```sql
SET use_query_cache = 1;
SET query_cache_ttl = 60;
SET query_cache_tag = 'dashboard_sales';

SELECT service, sum(revenue)
FROM sales
WHERE event_date >= today() - 7
GROUP BY service;
```

### On-disk query cache для больших результатов

```sql
-- On-disk backend хранит результаты в filesystem cache
SET use_query_cache = 1;
SET enable_writes_to_query_cache_on_disk = 1;
SET enable_reads_from_query_cache_on_disk = 1;
SET query_cache_on_disk_cache_name = 'query_results';
SET query_cache_on_disk_codec = 'ZSTD(3)';

SELECT service, sum(revenue)
FROM sales
WHERE event_date >= today() - 7
GROUP BY service;
```

### Инвалидация кэша при обновлении данных

```sql
-- При загрузке новых данных — инвалидируем тегом
SYSTEM DROP QUERY CACHE 'dashboard_sales';

-- Или очищаем весь кэш
SYSTEM CLEAR QUERY CACHE;
```

### Ускорение тяжёлых сканирований

```sql
-- Большая таблица с 4 репликами на шард
SET enable_parallel_replicas = 1;
SET max_parallel_replicas = 4;

SELECT count(), avg(duration_ns)
FROM traces
WHERE start_time > now() - INTERVAL 1 DAY;
```

### Управление конкурентностью запросов

```sql
-- Настройка очереди на уровне профиля пользователя (users.xml)
-- <profile>
--     <max_concurrent_queries_for_user>50</max_concurrent_queries_for_user>
--     <queue_max_wait_ms>10000</queue_max_wait_ms>
-- </profile>

-- Проверка текущей нагрузки
SELECT count() AS active_queries
FROM system.processes
WHERE query IS NOT NULL;

-- Ожидающие запросы (в очереди)
SELECT query_id, query, elapsed
FROM system.processes
WHERE state = 'Queued'
ORDER BY elapsed DESC;
```

### Проверка использования кэша и параллельных реплик

```sql
-- Was query served from cache?
SELECT query_id, query_cache_usage, query_duration_ms
FROM system.query_log
WHERE query_id = 'last_query_id'
LIMIT 1;

-- # → query_cache_usage: ReadAndWrite
```

```sql
-- Параллельные реплики в профиле
SELECT event, value
FROM system.query_log
ARRAY JOIN ProfileEvents
WHERE type = 'QueryFinish'
  AND event LIKE 'ParallelReplicas%'
ORDER BY event_time DESC
LIMIT 10;
```

## Операции и команды

| Операция | Команда / настройка | Описание |
| :--- | :--- | :--- |
| Очистить весь кэш | `SYSTEM CLEAR QUERY CACHE` | Сброс in-memory и on-disk кэша |
| Инвалидация по тегу | `SYSTEM DROP QUERY CACHE 'tag'` | Удаление записей с тегом |
| Просмотр in-memory кэша | `SELECT * FROM system.query_cache` | Содержимое in-memory кэша |
| Hit/miss метрики | `SELECT * FROM system.events WHERE event LIKE 'QueryCache*'` | `QueryCacheHits`, `QueryCacheMisses`, `QueryCacheOnDiskHits` |
| Размер кэша | `SELECT * FROM system.metrics WHERE metric IN ('QueryCacheEntries', 'QueryCacheBytes')` | Entries / bytes in real-time |
| Использование кэша | `SELECT query_cache_usage FROM system.query_log` | `None`/`Read`/`Write`/`ReadAndWrite`/`InvalidateTag` |
| Включить параллельные реплики | `SET enable_parallel_replicas = 1` | 0=off, 1=on, 2=force |
| Мониторинг параллельных реплик | `SELECT * FROM system.query_log ARRAY JOIN ProfileEvents WHERE event LIKE 'ParallelReplicas%'` | `ParallelReplicasUsedCount`, `ParallelReplicasTotalCount` |
| Admission control | `max_concurrent_queries` (server), `max_concurrent_queries_for_user` (per-user) | 0 = unlimited |
| Query queue | `queue_max_wait_ms` + `max_waiting_queries` | Bounded wait при overload |
| Workload scheduling | `QUERY` resource | Rate limiting, burst control per workload |

## Валидация

### Проверка создания и использования query cache

```sql
-- 1. Включаем кэш и выполняем запрос дважды
SET use_query_cache = 1, enable_writes_to_query_cache = 1;
SELECT count() FROM large_table WHERE created_at >= today() - 1;
-- # → 1000000

SELECT count() FROM large_table WHERE created_at >= today() - 1;
-- # → 1000000 (served from cache)

-- 2. Проверяем метрики
SELECT event, value
FROM system.events
WHERE event IN ('QueryCacheHits', 'QueryCacheMisses')
ORDER BY event;
-- # → QueryCacheHits: 1, QueryCacheMisses: 1

-- 3. Запрос в query_log показывает тип доступа
SELECT query_id, query_cache_usage, query_duration_ms
FROM system.query_log
WHERE query LIKE '%large_table%'
ORDER BY event_time DESC
LIMIT 5;
```

### Проверка parallel replicas

```sql
-- 1. Включаем и выполняем
SET enable_parallel_replicas = 1, max_parallel_replicas = 4;
SELECT count() FROM replicated_table WHERE event_date >= '2024-01-01';

-- 2. Проверяем ProfileEvents
SELECT name, value
FROM system.query_log
CROSS JOIN UNNEST_split_by_string(ProfileEvents.Names, ProfileEvents.Values)
WHERE type = 'QueryFinish'
  AND name LIKE 'ParallelReplicas%'
ORDER BY event_time DESC
LIMIT 5;

-- 3. Проверяем план
EXPLAIN SYNTAX SELECT count() FROM replicated_table;
```

### Проверка конкурентности

```sql
-- Активные запросы
SELECT count() AS concurrent_queries
FROM system.processes
WHERE query IS NOT NULL;

-- Ожидающие в очереди
SELECT query_id, query, elapsed
FROM system.processes
WHERE state = 'Queued';

-- События перегрузки
SELECT event, value
FROM system.events
WHERE event = 'TooManySimultaneousQueries';
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Кэш не работает | `use_query_cache = 0` или недетерминированный запрос | Включить настройку; убрать `now()`/`rand()` |
| Кэш быстро устаревает | TTL слишком короткий | Увеличить `query_cache_ttl` |
| On-disk cache не используется | `query_cache_on_disk_cache_name` не настроен или filesystem cache отсутствует | Настроить `<query_cache_on_disk_cache_name>` и filesystem cache |
| Parallel replicas не ускоряют | Точечный запрос или `FINAL` | Использовать только для больших сканирований; убрать `FINAL` |
| `parallel_replicas_count` в запросах | Используется internal setting | Заменить на `max_parallel_replicas` |
| `Too Many Simultaneous Queries` (`202`) | `max_concurrent_queries` исчерпан | Увеличить лимит; добавить `queue_max_wait_ms`; использовать `QUERY` resource |
| `Too many connections` (`203`) | `max_connections` исчерпан | Пулинг на клиенте/прокси; увеличить `max_connections` |
| Кэш не инвалидируется | Данные изменились, но кэш живёт | Уменьшить `query_cache_ttl` или использовать теги |
| `NO_FREE_CONNECTION` | Пул соединений переполнен | Увеличить `connection_pool_max_wait_ms`; настроить `connection_pool_size` на клиенте |

## Лучшие практики

1. **Query Cache** — для дашбордов и повторяющихся отчётов с TTL 30–300 сек.
2. **On-disk cache** — для больших result sets; используйте выделенный filesystem cache (`query_cache_on_disk_cache_name`) и SLA on-disk codec (`ZSTD(3)`).
3. **Parallel Replicas** — только для тяжёлых сканирований (>1B строк); не для точечных запросов. Используйте `max_parallel_replicas`, а не internal `parallel_replicas_count`.
4. **Connection Pooling** — всегда через клиентский пул (JDBC/ODBC/Python) или прокси (CHProxy/HAProxy).
5. **`max_concurrent_queries`** — настраивать по CPU/RAM; добавлять `queue_max_wait_ms` для graceful degradation вместо мгновенного `202 Too Many Simultaneous Queries`.
6. **`max_concurrent_queries_for_user` / `_for_all_users`** — выставлять per-user/per-service для изоляции tenants.
7. **Инвалидация кэша** — через теги (`SYSTEM DROP QUERY CACHE 'tag'`) при обновлении данных.
8. **`as_prefer = 1`** (default) — держить локальную реплику в наборе для cache locality.
9. **Мониторинг** — `system.query_cache`, `system.query_log` (`query_cache_usage`, `ProfileEvents`), `system.metrics` (`QueryCacheEntries`, `QueryCacheBytes`), `system.events` (`QueryCacheHits/Misses`, `QueryCacheOnDiskHits`).
10. **Workload isolation** — используйте `QUERY` resource для rate-limiting и burst control; не полагайтесь только на `max_concurrent_queries`.

## Дополнительная информация

### Смежные темы

- Параметры сервера (лимиты, конкурентность, пулы) — **[Производительность](./clickhouse-capacity-upgrades.md)**.
- Параметры запроса и приоритеты — **[Производительность](./clickhouse-performance.md#параметры-серверного-конфига-configxml)**.
- Кластерная архитектура и балансировка — **[Кластерное управление](./clickhouse-cluster.md)**.
- Общий мониторинг и метрики — **[Мониторинг](./clickhouse-monitoring.md)**.

### Ресурсы

- [Query Cache](https://clickhouse.com/docs/operations/query-cache)
- [On-Disk Query Cache](https://clickhouse.com/docs/concepts/features/performance/caches/query-cache)
- [Parallel Replicas](https://clickhouse.com/docs/operations/parallel-replicas)
- [Concurrency Settings](https://clickhouse.com/docs/resources/engineering/high-concurrency-sizing-user-analytics)
- [system.query_cache](https://clickhouse.com/docs/reference/system-tables/query_cache)
- [max_concurrent_* Settings](https://clickhouse.com/docs/reference/settings/server-settings/settings/max-concurrent)
- [Connection Pooling](https://clickhouse.com/docs/reference/settings/session-settings/other#connection_pool_max_wait_ms)
