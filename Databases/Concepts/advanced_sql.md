**Актуально для:** PostgreSQL 16–18 / MySQL 8.0+ / MariaDB 10.2+ / SQLite 3.25+ (2024–2026)

# Продвинутый SQL: оконные функции, рекурсивные CTE

Оконные функции в MySQL (синтаксис, фреймы, примеры) — в **[MySQL 8.x features](../MySQL/sql-8x-features.md)**. SQLite-реализация — в **[SQLite features](../SQLite/Operations/sqlite_sql_features.md)**. Этот файл — кросс-СУБД совместимость, рекурсивные CTE и паттерны.

## Определения

**Оконная функция (Window Function)** — функция, вычисляющая значение для каждой строки на основе набора связанных строк («окна»), не сворачивая строки в одну (в отличие от `GROUP BY`). Требует клаузу `OVER`.

**CTE (Common Table Expression)** — именованный временный результат в рамках одного запроса (`WITH name AS (SELECT ...)`). Улучшает читаемость; в PostgreSQL 12+ может быть материализован или встроен в план.

**Recursive CTE** — CTE, ссылающийся на себя: обход иерархий (оргструктура, BOM, дерево категорий, графы).

**Window frame (фрейм)** — подмножество строк окна, по которому вычисляются `FIRST_VALUE`/`LAST_VALUE`/агрегаты: `ROWS`/`RANGE`/`GROUPS` между границами.

**Peer (равный)** — строки с одинаковыми значениями `ORDER BY` в партиции; ранжирующие функции дают одинаковый результат для peers.

**QUALIFY** — клауза фильтрации по результату оконной функции (Teradata, Snowflake, DuckDB). В PostgreSQL/MySQL/MariaDB — нет: нужен подзапрос или CTE.

## Основные концепции

### Порядок логического выполнения запроса

```
FROM → JOIN → WHERE → GROUP BY → HAVING → WINDOW → QUALIFY → DISTINCT → ORDER BY → LIMIT
```

**Следствия:**
- Оконную функцию **нельзя** использовать в `WHERE`/`GROUP BY`/`HAVING` — она вычисляется после них. Только в `SELECT`, `ORDER BY`, `QUALIFY` (где поддерживается).
- Агрегат с `OVER` — оконная агрегация (без свёртки строк); без `OVER` — обычная агрегация.

### Кросс-СУБД совместимость

| Возможность | PostgreSQL | MySQL | MariaDB | SQLite |
| :--- | :--- | :--- | :--- | :--- |
| **Оконные функции** | 8.4+ | 8.0.2+ | 10.2+ | 3.25+ |
| **Рекурсивные CTE** | 8.4+ | 8.0+ | 10.2+ | 3.8.3+ |
| **`FILTER` (для агрегатов)** | 9.4+ | нет | нет | 3.30+ |
| **Фрейм `GROUPS`** | 11+ | нет | нет | 3.28+ |
| **`EXCLUDE` clause** | 11+ | нет | нет | 3.28+ |
| **`WINDOW` clause (именованные окна)** | 9.4+ | 8.0+ | 10.2+ | 3.28+ |
| **`QUALIFY`** | нет | нет | нет | нет |
| **`PERCENTILE_CONT`** | 9.4+ (ordered-set) | нет | 10.3.3+ (PERCENTILE_CONT/DISC) | 3.51+ (опц. расширение) |

**Примечания:**
- `FILTER` в PostgreSQL — для агрегатов (`count(*) FILTER (WHERE ...)`), не для скалярных оконных функций.
- `EXCLUDE` (PostgreSQL 11+, SQLite 3.28+): `EXCLUDE CURRENT ROW`, `EXCLUDE GROUP`, `EXCLUDE TIES`, `EXCLUDE NO OTHERS` (по умолчанию).
- MySQL и MariaDB: только фреймы `ROWS` и `RANGE`. `GROUPS` и `EXCLUDE` распознаются парсером, но дают ошибку (MySQL 8.0+: раздел «Window Function Restrictions»; MariaDB: «does not support GROUPS frames / frame exclusion»).
- MariaDB 10.3.3+: `PERCENTILE_CONT`/`PERCENTILE_DISC` — оконные функции, обязателен `OVER`: `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY x) OVER ([PARTITION BY ...])`.
- SQLite 3.51+: `percentile_cont()` доступен при сборке с `-DSQLITE_ENABLE_PERCENTILE` или как loadable extension.
- MySQL 8.0.2+: `PERCENT_RANK`, `CUME_DIST` есть; `PERCENTILE_CONT` — нет (только через подзапросы).

### Рекурсивный CTE: механизм

```sql
WITH RECURSIVE cte AS (
    -- Anchor member: начальная строка
    SELECT id, parent_id, name, 1 AS depth
    FROM categories WHERE parent_id IS NULL
  UNION ALL
    -- Recursive member: шаг рекурсии (ссылается на cte)
    SELECT c.id, c.parent_id, c.name, cte.depth + 1
    FROM categories c JOIN cte ON c.parent_id = cte.id
)
SELECT * FROM cte;
```

**Правила:**
- `UNION ALL` (или `UNION` для дедупликации); `UNION` замедляет и может прервать зацикливание, но не гарантирует завершение рекурсии.
- PostgreSQL: `CYCLE` clause (PG 14+) для защиты от циклов; MySQL: `cte_max_recursion_depth` (по умолчанию 1000).
- Рекурсивный член может ссылаться на CTE только один раз (PostgreSQL, MySQL).

## Практические сценарии

#### Предпосылки

Перед сценариями проверьте:

- **Версии СУБД** — по матрице совместимости выше; `GROUPS`-фреймы и `EXCLUDE` доступны только в PostgreSQL 11+ и SQLite 3.28+, в MySQL/MariaDB их нет.
- **Права:** `SELECT` на целевые таблицы; для разбора планов — `EXPLAIN` (PostgreSQL, MySQL, MariaDB) или `EXPLAIN QUERY PLAN` (SQLite).
- **Тестовая среда:** рекурсивные CTE и «сухие прогоны» — на staging; глубина рекурсии ограничена (`cte_max_recursion_depth` в MySQL/MariaDB, по умолчанию 1000).
- **Память под сортировку:** оконные запросы сортируют данные — `work_mem` (PostgreSQL); при нехватке памята сортировка уходит на диск во всех четырёх СУБД.

### Сценарий 1: Иерархия организации (recursive CTE)

```sql
WITH RECURSIVE org_tree AS (
    SELECT id, name, manager_id, 1 AS level
    FROM employees WHERE id = 1  -- CEO
  UNION ALL
    SELECT e.id, e.name, e.manager_id, ot.level + 1
    FROM employees e JOIN org_tree ot ON e.manager_id = ot.id
)
SELECT repeat('  ', level - 1) || name AS org_chart, level
FROM org_tree ORDER BY level, name;
-- → дерево с отступами по уровням
```

**PostgreSQL 14+ — защита от циклов:**
```sql
WITH RECURSIVE org_tree AS (
    SELECT id, name, manager_id, 1 AS level, ARRAY[id] AS path
    FROM employees WHERE id = 1
  UNION ALL
    SELECT e.id, e.name, e.manager_id, ot.level + 1, ot.path || e.id
    FROM employees e JOIN org_tree ot ON e.manager_id = ot.id
    WHERE NOT e.id = ANY(ot.path)  -- ручная защита; или CYCLE clause
)
SELECT * FROM org_tree;
```

### Сценарий 2: Gaps-and-islands (пропуски и острова)

**Задача:** найти непрерывные серии дат активности пользователя.

```sql
WITH dates AS (
    SELECT DISTINCT activity_date AS d FROM user_activity WHERE user_id = 42
),
grouped AS (
    SELECT d,
           d - (row_number() OVER (ORDER BY d) * interval '1 day') AS grp
    FROM dates
)
SELECT min(d) AS series_start, max(d) AS series_end, count(*) AS days
FROM grouped GROUP BY grp ORDER BY series_start;
-- → каждая непрерывная серия — одна строка
```

**Принцип:** `row_number()` растёт на 1 для каждой строки; у непрерывных дат разница `d - row_number` постоянна → это и есть «остров».

### Сценарий 3: Running total (накопительный итог)

```sql
SELECT day, amount,
       sum(amount) OVER (ORDER BY day
                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_total
FROM daily_sales;
```

**Важно:** без явного фрейма `ORDER BY` в `OVER` даёт фрейм `RANGE UNBOUNDED PRECEDING .. CURRENT ROW` — при одинаковых `day` строки-«peers» включаются все. Для построчного итога — явный `ROWS` фрейм.

### Сценарий 4: Top-N на группу

```sql
-- Три последних заказа на клиента (полный разбор — в MySQL 8.x features)
SELECT * FROM (
    SELECT customer_id, created_at, amount,
           row_number() OVER (PARTITION BY customer_id ORDER BY created_at DESC) AS rn
    FROM orders
) t WHERE rn <= 3;
```

### Сценарий 5: Дедупликация через ROW_NUMBER

```sql
-- Удаление дубликатов (оставить новейший по каждому email)
WITH ranked AS (
    SELECT id, email,
           row_number() OVER (PARTITION BY email ORDER BY created_at DESC) AS rn
    FROM users
)
DELETE FROM users WHERE id IN (SELECT id FROM ranked WHERE rn > 1);
```

### Сценарий 6: PostgreSQL `FILTER` — условные агрегаты

```sql
SELECT product_id,
       count(*) AS total,
       count(*) FILTER (WHERE status = 'refunded') AS refunded,
       sum(amount) FILTER (WHERE status = 'paid') AS paid_amount
FROM orders GROUP BY product_id;
-- → один проход вместо CASE WHEN внутри каждого агрегата
```

### Сценарий 7: CTE и оптимизация (PostgreSQL 12+)

```sql
-- PG 12+: CTE инлайнится в план, если не MATERIALIZED
WITH recent AS (SELECT * FROM orders WHERE created_at > now() - interval '30 days')
SELECT * FROM recent WHERE amount > 1000;

-- Принудительная материализация (optimization fence):
WITH recent AS MATERIALIZED (SELECT * FROM orders WHERE created_at > now() - interval '30 days')
SELECT * FROM recent WHERE amount > 1000;
-- MATERIALIZED: CTE вычисляется один раз; полезно при многократном обращении
```

**До PG 12:** CTE всегда материализовались — optimization fence, блокирующий pushdown предикатов. Миграция с старых версий: проверить планы после апгрейда.

## Операции и команды

### Проверка поддержки

```sql
-- PostgreSQL: версия
SELECT version();
-- → PostgreSQL 18.x ...

-- MySQL: версия и поддержка CTE
SELECT VERSION();  -- → 8.0.x+

-- SQLite: версия
SELECT sqlite_version();  -- → 3.25+ для оконных функций
```

### Ограничение рекурсии

```sql
-- MySQL/MariaDB: глубина рекурсии
SET SESSION cte_max_recursion_depth = 10000;  -- по умолчанию 1000

-- PostgreSQL: защита от бесконечной рекурсии — CYCLE (14+)
WITH RECURSIVE t AS (
    SELECT id, parent_id FROM nodes WHERE id = 1
  UNION ALL
    SELECT n.id, n.parent_id FROM nodes n JOIN t ON n.parent_id = t.id
) CYCLE id SET is_cycle USING path
SELECT * FROM t;
```

## Поиск и устранение неисправностей

### Проблема: «window function is not allowed here»

**Симптомы:** ошибка при использовании оконной функции в `WHERE`/`GROUP BY`/`HAVING`.

**Причина:** оконные функции вычисляются после `WHERE`/`GROUP BY`.

**Решение:** обернуть в подзапрос/CTE и фильтровать снаружи (как в сценарии Top-N), или `QUALIFY` (если СУБД поддерживает).

### Проблема: LAST_VALUE возвращает не последнее значение

**Симптомы:** `LAST_VALUE(amount) OVER (PARTITION BY ... ORDER BY ...)` возвращает значение текущей строки.

**Причина:** фрейм по умолчанию — `RANGE UNBOUNDED PRECEDING .. CURRENT ROW`; «последняя строка фрейма» = текущая.

**Решение:** явный фрейм `RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING` (см. **[MySQL 8.x features](../MySQL/sql-8x-features.md)**).

### Проблема: рекурсивный CTE не завершается

**Симптомы:** запрос висит или падает по `cte_max_recursion_depth` / `stack depth`.

**Причина:** цикл в иерархии (A→B→A) или отсутствие anchor-строк.

**Решение:**
1. `UNION` вместо `UNION ALL` (дедупликация).
2. PostgreSQL 14+: `CYCLE` clause.
3. Ручной `path`-массив с проверкой `NOT id = ANY(path)`.
4. Проверить anchor: `WHERE parent_id IS NULL` возвращает строки?

### Проблема: оконный запрос медленный

**Симптомы:** `WindowAgg` в плане сортирует миллионы строк; `Sort Method: external merge Disk`.

**Причина:** нет индекса под `PARTITION BY ... ORDER BY ...`; сортировка на диске.

**Решение:**
1. Индекс `(partition_col, order_col)` — сортировка в память.
2. Увеличить `work_mem` (PostgreSQL) для сортировки.
3. Предфильтровать строки `WHERE` до окна.

### Проблема: CTE вычисляется многократно

**Симптомы:** план показывает повторное сканирование базовой таблицы для каждого обращения к CTE (PostgreSQL < 12 или при инлайне).

**Решение:** `AS MATERIALIZED` (PG 12+) или переписать как подзапрос/временную таблицу.

### Проблема: `PERCENTILE_CONT` недоступен

**Симптомы:** MySQL 8.0 не имеет `PERCENTILE_CONT`.

**Решение:** через оконные функции:
```sql
SELECT percentile FROM (
    SELECT amount,
           round(percent_rank() OVER (ORDER BY amount), 2) AS pr
    FROM orders
 ) t WHERE pr >= 0.95 ORDER BY pr LIMIT 1;

-- или MariaDB 10.3.3+ (PERCENTILE_CONT — оконная функция, требуется OVER):
SELECT p95 FROM (
    SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY amount) OVER () AS p95
    FROM orders
) t LIMIT 1;
```

## Лучшие практики

1. **Оконные функции вместо самосоединений** — обычно на порядок дешевле (**[MySQL 8.x features](../MySQL/sql-8x-features.md)**).
2. **Явный фрейм** для `LAST_VALUE`/`NTH_VALUE`/агрегатов — избегайте подводного камня фрейма по умолчанию.
3. **Индекс под `PARTITION BY + ORDER BY`** — ключ к производительности оконных запросов.
4. **Recursive CTE:** `CYCLE`/`path`-защита от циклов всегда; ограничивайте глубину.
5. **CTE для читаемости;** в PostgreSQL 12+ проверяйте, что инлайн не ухудшил план (`MATERIALIZED` при необходимости).
6. **`FILTER` вместо `CASE WHEN`** в агрегатах (PostgreSQL, SQLite) — чище и быстрее.
7. **Кросс-СУБД код:** проверяйте матрицу совместимости перед переносом (`FILTER`, `EXCLUDE`, `QUALIFY`).
8. **Тяжёлую аналитику — в нативный SQL**, а не через ORM (**[ORM-подводные камни](./orm_pitfalls.md)**).

## Дополнительная информация

### Смежные темы
- **[MySQL 8.x features](../MySQL/sql-8x-features.md)** — оконные функции: полный синтаксис, фреймы, примеры.
- **[SQLite features](../SQLite/Operations/sqlite_sql_features.md)** — оконные функции и рекурсивные CTE в SQLite.
- **[PostgreSQL: planner internals](../PostgreSQL/Concepts/planner_internals.md)** — как оптимизатор обрабатывает CTE и окна.
- **[Индексы](./indexes.md)** — индексы для оконных запросов.
- **[ORM-подводные камни](./orm_pitfalls.md)** — когда ORM не справляется и нужен нативный SQL.
- **[Моделирование DWH](./dwh_modeling.md)** — аналитические запросы на звёздной схеме.
- **[Benchmarking](./benchmarking.md)** — замер pgbench/sysbench.
