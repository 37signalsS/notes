# Оптимизация производительности PostgreSQL

## Определения

**MVCC (Multi-Version Concurrency Control)** — механизм управления параллельным доступом, при котором для каждого изменения строки создается новая версия. Подробности — **[Concurrency and Locking](../Concepts/concurrency_and_locking.md)**.

**Bloat** — раздувание таблиц из-за накопления "мёртвых" кортежей (dead tuples) — следствие работы MVCC.

**VACUUM** — процесс очистки "мёртвых" кортежей для повторного использования пространства. `autovacuum` — фоновый процесс автоматической очистки.

**План выполнения** — последовательность операций (сканирование, соединения, сортировка), которую PostgreSQL планирует выполнить для запроса. `EXPLAIN ANALYZE` выполняет запрос и показывает реальное время каждого шага.

**Cache hit rate** — доля запрошенных данных, найденных в кэше (`shared_buffers`), а не прочитанных с диска. Целевой показатель: >99%.

**Индекс** — структура данных для ускорения доступа к строкам таблицы. Теория — **[Индексы в базах данных](../../Concepts/indexes.md)**.

## Основные концепции

### MVCC и VACUUM

PostgreSQL использует MVCC: при `UPDATE` или `DELETE` старая версия строки помечается как "мёртвая" (dead tuple). Со временем это приводит к раздуванию (bloat) таблиц и индексов.

**Autovacuum** критически важен для:
- Очистки dead tuples
- Сбора статистики для планировщика (`ANALYZE`)
- Предотвращения transaction ID wraparound

Подробнее — **[Concurrency and Locking](../Concepts/concurrency_and_locking.md#practical-scenarios)**.

### Индексы

Помимо стандартного **B-Tree**, PostgreSQL поддерживает специализированные типы:

| Тип | Назначение |
| :--- | :--- |
| **GIN** | Полнотекстовый поиск, массивы, `jsonb` |
| **GiST** | Геопространственные данные (PostGIS) |
| **BRIN** | Большие упорядоченные таблицы (временные ряды) |

Подробнее — **[Индексы в базах данных](../../Concepts/indexes.md)**.

### Анализ планов запросов

**`EXPLAIN`** показывает план выполнения:
- **Типы сканирования:** `Seq Scan` (полное), `Index Scan`, `Bitmap Scan`
- **Типы JOIN:** `Nested Loop`, `Hash Join`, `Merge Join`
- **Стоимость:** `startup cost` и `total cost`

**Чтение плана:** "Изнутри наружу" и "снизу вверх". Ищите `Seq Scan` на больших таблицах — кандидат на отсутствие индекса.

### Аппаратное обеспечение и ОС

**Рекомендации:**
- **CPU:** Высокая частота для OLTP, много ядер для OLAP
- **RAM:** Чем больше, тем лучше (держит "горячие" данные в кэше)
- **Диски:** SSD/NVMe стандарт; разносите данные, WAL и индексы на разные диски

**Настройки Linux:**
- `swappiness = 1` или `5`
- `transparent_hugepage = never`
- `noatime` в `fstab`

### Настройка параметров

**Ключевые параметры `postgresql.conf`:**

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `shared_buffers` | Кэш страниц данных | ~25% RAM |
| `effective_cache_size` | Подсказка планировщику о кэше ОС | 50-75% RAM |
| `work_mem` | Память на операцию сортировки/хеширования | Осторожно: на каждую операцию |
| `maintenance_work_mem` | Память для `VACUUM`, `CREATE INDEX` | Можно временно увеличивать |
| `max_connections` | Максимум подключений | Учитывайте приложение + мониторинг |
| `autovacuum` | Включить автовакуум | `on` (по умолчанию) |

**Мониторинг запросов:**
- `pg_stat_statements` — статистика по всем запросам (требует `shared_preload_libraries`)
- `auto_explain` — логирование планов медленных запросов
- `pg_stat_monitor` — продвинутая альтернатива `pg_stat_statements`

Для упрощения тюнинга используйте `pgtune` или `PGConfig.org` (отправная точка).

## Практические сценарии

### Сценарий 1: Общий анализ ("Что-то тормозит")

#### 1. Проверка на уровне ОС

Используйте [`top`](../../../Linux/Diagnostics/Processes/top.md) / [`htop`](../../../Linux/Diagnostics/Processes/htop.md), `iostat`, `df`, `free` / `vmstat`. Проверьте OOM Killer: `dmesg | grep oom-killer`.

#### 2. Анализ на уровне БД

**Активные запросы (`pg_stat_activity`):**

```sql
-- Запросы, выполняющиеся дольше 5 минут
SELECT pid, age(clock_timestamp(), query_start), usename, query
FROM pg_stat_activity
WHERE state = 'active' 
  AND (clock_timestamp() - query_start) > interval '5 minutes';
```

Особое внимание — `idle in transaction`.

**Дорогие запросы (`pg_stat_statements`):**

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

SELECT total_exec_time, calls, mean_exec_time, query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 10;
```

#### 3. Завершение проблемных запросов

```sql
-- Мягко
SELECT pg_cancel_backend(PID);

-- Жёстко
SELECT pg_terminate_backend(PID);
```

### Сценарий 2: Оптимизация медленного запроса

#### 1. Изучение плана

```sql
EXPLAIN ANALYZE <ваш_запрос>;
```

> **Важно:** `EXPLAIN ANALYZE` **выполняет** запрос. Осторожно с `INSERT`, `UPDATE`, `DELETE`.

**Что искать:**
- `Seq Scan` на больших таблицах — нужен индекс
- Неверные оценки `rows` — устаревшая статистика

#### 2. Оптимизация

- Добавить/изменить индекс
- Переписать запрос (упростить, разбить)
- Создать материализованное представление
- Собрать статистику: `ANALYZE table_name;`
- Увеличить `work_mem` для сессии: `SET work_mem = '32MB';`

**Обязательно** выполните `EXPLAIN ANALYZE` после изменений.

### Сценарий 3: Проактивный мониторинг

#### Управление конфигурацией

```sql
ALTER SYSTEM SET work_mem = '16MB';
SELECT pg_reload_conf(); -- Без перезапуска
```

#### Мониторинг кэша

```sql
SELECT
    (sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read))) * 100 AS cache_hit_rate
FROM pg_statio_user_tables;
```

#### Мониторинг Autovacuum

```sql
SELECT relname, n_live_tup, n_dead_tup, last_autovacuum, last_autoanalyze
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC;
```

#### Настройка auto_explain

```ini
shared_preload_libraries = 'pg_stat_statements, auto_explain'
auto_explain.log_min_duration = '250ms'
auto_explain.log_sample_rate = 0.5
```

#### Неиспользуемые индексы

Запрос для поиска — **[Индексы](../../Concepts/indexes.md#поиск-и-удаление-неиспользуемых-индексов)**.

## Дополнительная информация

**Прямое влияние на планировщик** (для отладки):

```sql
SET enable_indexscan = off;
RESET enable_indexscan;
```

**Инструменты:**
- **Визуализация планов:** [explain.depesz.com](https://explain.depesz.com/)
- **Профилирование:** `pg_profile` (аналог AWR в Oracle)
- **JIT:** Статистика видна в `EXPLAIN ANALYZE` (PostgreSQL 16+)

**Связанные документы:**

- **Мониторинг:** **[Full-Stack Observability](./observability.md)**
- **Индексы:** **[Indexes](../../Concepts/indexes.md)**
- **MVCC:** **[Concurrency and Locking](../Concepts/concurrency_and_locking.md)**
- **Бэкапы:** **[Backup and Recovery](../Concepts/backup_and_recovery.md)**
