# Оптимизация запросов: EXPLAIN и Optimizer Hints в MySQL/MariaDB

**Актуально для:** MySQL 8.4 LTS / 9.x Innovation, MariaDB 11.4 LTS / 12.x Innovation

## Определения

*   **План выполнения (Execution Plan)** — последовательность операций, которую выбирает оптимизатор СУБД для получения результата запроса. Строится на основе статистики индексов, а не реального пересчёта строк.
*   **EXPLAIN** — команда для анализа плана выполнения. Показывает, как БД будет искать строки, какие индексы использовать и в каком порядке соединять таблицы.
*   **EXPLAIN ANALYZE** — расширенная команда (MySQL 8.0.18+, MariaDB 10.1+), которая выполняет запрос и показывает реальное время выполнения, количество строк и использованную память для каждого узла плана.
*   **ANALYZE TABLE** — команда для принудительного обновления статистики индексов. В MySQL 8.x статистика хранится персистентно в системных таблицах `mysql.innodb_index_stats` / `mysql.innodb_table_stats`. Автопересчёт срабатывает при изменении ~10% строк (`innodb_stats_auto_recalc = ON`), но после массовой нагрузки план может временно «плыть».
*   **Optimizer Hints (Подсказки оптимизатору)** — специальные инструкции внутри SQL-комментариев (`/*+ ... */`), которые принудительно изменяют решение оптимизатора (например, выбор конкретного индекса или порядка JOIN).
*   **Filesort** — алгоритм сортировки данных в памяти или на диске, который применяется, когда БД не может использовать индекс для получения строк в нужном порядке.
*   **Temporary Table** — временная таблица, создаваемая в памяти (RAM) или на диске для хранения промежуточных результатов (обычно при `GROUP BY`, `DISTINCT` или сложных `JOIN`).
*   **Гистограмма (Histogram)** — структура данных, позволяющая оптимизатору точнее оценивать распределение значений в столбце. Критична для неравномерных данных, где индекс может быть неэффективен из-за низкой селективности.
*   **sys schema** — набор представлений и функций поверх Performance Schema, предоставляющий удобные агрегированные отчеты по производительности запросов. В MySQL 8.0+ включён по умолчанию.

---

## Архитектура оптимизатора

### Как строится план выполнения

Оптимизатор MySQL проходит через несколько этапов:

1.  **Парсинг и валидация:** SQL-запрос преобразуется в Abstract Syntax Tree (AST). Проверяется синтаксис и права доступа.
2.  **Предварительная оптимизация (Pre-optimization):** Нормализация запроса, развёртывание представлений (view merging), упрощение выражений.
3.  **Выбор индексов (Index Selection):** Для каждого табличного доступа оптимизатор оценивает доступные индексы по стоимости (cost). Использует:
    *   Статистику индексов (cardinality)
    *   Селективность предикатов
    *   Наличие гистограмм (MySQL 8.0+)
4.  **Выбор порядка соединений (Join Order):** Перебор возможных порядков соединения таблиц. Для >7 таблиц используется жадный алгоритм (greedy), а не полный перебор, чтобы ограничить время планирования.
5.  **Выбор алгоритмов соединений (Join Algorithm):** BNLJ, BNLJ with batched key access, hash join (MySQL 8.0.20+), nested loop, merge join.
6.  **Оценка стоимости (Cost Estimation):** Каждой операции присваивается стоимость на основе параметров `cost_model` (`io_cost`, `cpu_cost`). Оптимизатор выбирает план с минимальной суммарной стоимостью.

### Факторы, влияющие на выбор плана

*   **Статистика:** Устаревшая статистика — основная причина неоптимальных планов. `ANALYZE TABLE` обновляет cardinality.
*   **Гистограммы:** В MySQL 8.0+ можно создавать гистограммы для столбцов с неравномерным распределением. Типы: `SINGLE_PREC_HB` и `DOUBLE_PREC_HB`.
*   **Параметры cost model:** `optimizer_cost_model` может быть `io` (по умолчанию) или `cpu` (учитывает только CPU). В I/O-bound системах `io` точнее.
*   **Лимиты планировщика:** `optimizer_search_depth` ограничивает глубину перебора порядка соединений. `optimizer_prune_level = ON` (по умолчанию) отключает перебор заведомо плохих планов.

---

## Анализ плана выполнения (EXPLAIN)

### Форматы вывода (MySQL 8.0+)

1.  **TRADITIONAL (Табличный):** Стандартный вывод. Удобен для быстрой оценки типов доступа (`type`) и используемых ключей (`key`).
2.  **JSON:** Самый подробный формат. Содержит информацию о **стоимости (cost)** каждой операции, использовании памяти и буферов.
    ```sql
    EXPLAIN FORMAT=JSON SELECT ...;
    ```
3.  **TREE:** Иерархический вид, введенный в MySQL 8.0.16. Максимально нагляден для понимания порядка соединений и вложенности.
    ```sql
    EXPLAIN FORMAT=TREE SELECT ...;
    ```
4.  **EXPLAIN ANALYZE:** Выполняет запрос и показывает реальные метрики (actual rows, time, memory).
    ```sql
    EXPLAIN ANALYZE SELECT ...;
    ```

### Ключевые столбцы и их значение

| Столбец | Значение | SRE-индикатор |
| :--- | :--- | :--- |
| **`id`** | Порядковый номер оператора в плане | Одинаковые id = соединение (JOIN). Увеличивающиеся id = вложенные запросы (dependent subquery). |
| **`select_type`** | Тип оператора SELECT | `SIMPLE` — простой запрос; `PRIMARY` — внешний запрос; `DEPENDENT SUBQUERY` — вложенный, зависящий от внешнего; `DERIVED` — производная таблица (из подзапроса в FROM). |
| **`table`** | Имя таблицы | `table` = `<derivedN>` означает временную таблицу из подзапроса. |
| **`partitions`** | Список секций (partitioning) | Если пустой или не все секции — проверяете partition pruning. |
| **`type`** | Метод поиска строк. | **ALL** (Full Table Scan) — критично; **index** (Full Index Scan) — медленно; **range** — хорошо; **ref/eq_ref/const** — отлично. |
| **`possible_keys`** | Потенциальные индексы | Показывает, какие индексы могут быть использованы. Если пустой — индексов нет. |
| **`key`** | Реально выбранный индекс | Если `NULL` — индекс не используется. |
| **`key_len`** | Длина использованной части индекса | Позволяет понять, используется ли индекс полностью или только левый префикс. |
| **`rows`** | Оценочное количество строк | Чем больше, тем выше I/O нагрузка. |
| **`filtered`** | % строк после фильтрации | Низкое значение при большом `rows` говорит о неэффективном индексе. |
| **`Extra`** | Дополнительная информация | Ищите `Using filesort`, `Using temporary`, `Using index condition`, `Using MRR`, `Using join buffer (Batched Key Access)`. |

### Разбор формата TREE

Формат `EXPLAIN FORMAT=TREE` показывает иерархию операций:

```sql
EXPLAIN FORMAT=TREE
SELECT * FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.order_date > '2026-01-01';
```

Пример вывода:
```
-> Nested Loop Inner Join
    -> Filter: (o.order_date > '2026-01-01')
        -> Index Scan on orders using idx_order_date
    -> Single-Row Lookup on customers using PRIMARY
```

**Интерпретация:** Внешний цикл по `orders` с фильтром по дате, затем для каждой строки — поиск в `customers` по первичному ключу.

### Разбор EXPLAIN ANALYZE

Команда выполняет запрос и показывает реальные метрики:

```sql
EXPLAIN ANALYZE
SELECT c.name, COUNT(*) as order_count
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.order_date BETWEEN '2026-01-01' AND '2026-01-31'
GROUP BY c.name;
```

**Ключевые метрики в выводе:**
*   `actual time=N..M` — время выполнения для первой..последней строки (в миллисекундах).
*   `loops=N` — сколько раз выполнялся узел.
*   `rows=N` — реальное количество строк, прошедших через узел.
*   `memory usage=N` — потребление памяти для временных таблиц/сортировок.

**Сравнение с оценкой:** Если `rows` значительно отличается от оценочного `rows` в TRADITIONAL формате — статистика устарела. Выполните `ANALYZE TABLE`.

---

## Глубокий разбор Extra-индикаторов

### Using filesort
**Что это:** MySQL приходится выполнять дополнительный проход для сортировки данных, так как порядок в индексе не совпадает с `ORDER BY` или `GROUP BY`.
*   **Почему это плохо:** Потребляет много CPU. Если данные не влезают в `sort_buffer_size`, используется медленный диск.
*   **Как исправить:** Создать составной индекс, включающий поля фильтрации (`WHERE`) и поля сортировки (`ORDER BY`) в правильном порядке. Для `GROUP BY` можно использовать тот же индекс.

### Using temporary
**Что это:** Для выполнения запроса требуется промежуточный набор данных.
*   **Почему это плохо:** Создание таблицы в памяти — дорого, а если она перерастает в дисковую (InnoDB temp table) — запрос становится крайне медленным.
*   **Частые причины:** `DISTINCT`, `GROUP BY` по полям без индекса, использование `UNION` вместо `UNION ALL`, подзапросы в `FROM`.
*   **Как исправить:** Индексация полей группировки или оптимизация структуры JOIN. Для `UNION` рассмотрите `UNION ALL` если дубликаты не важны.

### Using index condition
**Что это:** Работает ICP (Index Condition Pushdown). Часть условий `WHERE` фильтруется на уровне индекса, до чтения полной строки из таблицы.
*   **SRE-эффект:** Снижение количества обращений к кластеризованному индексу.
*   **Условие:** Только для вторичных индексов. Если не появляется — проверьте, что условия используют только поля индекса.

### Using MRR / Using join buffer (Batched Key Access)
**Что это:** MRR превращает случайное чтение (Random I/O) в последовательное (Sequential I/O). BKA улучшает JOIN больших таблиц.
*   **SRE-эффект:** На SSD снижает нагрузку на контроллер. На HDD дает кратный прирост скорости.
*   **Диагностика:** В `EXPLAIN` отображается `Using MRR` или `Using join buffer (Batched Key Access)`.
*   **Настройка:** `optimizer_switch='mrr=on,mrr_cost_based=off,batched_key_access=on'`.

---

## Использование Optimizer Hints

В MySQL 8.0 подсказки пишутся в формате `/*+ HINT_NAME */` сразу после ключевого слова `SELECT`, `INSERT`, `REPLACE`, `UPDATE` или `DELETE`.

### Популярные подсказки

1.  **Управление индексами:**
    ```sql
    -- Принудительно использовать индекс
    SELECT /*+ INDEX(t1 idx_name) */ * FROM table1 t1;
    -- Игнорировать индекс
    SELECT /*+ IGNORE_INDEX(t1 idx_name) */ * FROM table1 t1;
    ```
2.  **Порядок соединения (Join Order):**
    ```sql
    -- Соединять таблицы в указанном порядке
    SELECT /*+ JOIN_ORDER(t2, t1) */ * FROM t1 JOIN t2 ON ...;
    ```
3.  **Ограничение ресурсов:**
    ```sql
    -- Прервать запрос, если он длится дольше 1000мс
    SELECT /*+ MAX_EXECUTION_TIME(1000) */ * FROM heavy_table;
    ```
4.  **Управление соединениями (Join Algorithm):**
    ```sql
    -- Запретить Block Nested Loop Join
    SELECT /*+ NO_BNL(t1, t2) */ * FROM t1 JOIN t2 ON ...;
    -- Принудительно использовать Hash Join (MySQL 8.0.20+)
    SELECT /*+ HASH_JOIN(t1, t2) */ * FROM t1 JOIN t2 ON ...;
    ```

### Когда использовать Hints?

*   **SRE Best Practice:** Использовать только как временное решение (hotfix), когда оптимизатор ошибается из-за устаревшей статистики.
*   **Риск:** При изменении структуры данных или объемов "зашитая" подсказка может сделать запрос в разы хуже. Всегда предпочитайте `ANALYZE TABLE` для обновления статистики.
*   **Альтернатива:** Вместо hints рассмотрите `optimizer_switch` на уровне сессии:
    ```sql
    SET SESSION optimizer_switch='mrr=on,mrr_cost_based=off';
    ```

### Классические index hints (USE / FORCE / IGNORE INDEX)

Помимо optimizer hints (`/*+ */`), MySQL поддерживает классические
подсказки выбора индекса, указываемые после имени таблицы:

```sql
SELECT * FROM t1 USE INDEX (idx_name) WHERE ...;
SELECT * FROM t1 FORCE INDEX (idx_name) WHERE ...;   -- использовать обязательно
SELECT * FROM t1 IGNORE INDEX (idx_name) WHERE ...;

-- Отдельно для JOIN, ORDER BY, GROUP BY:
SELECT * FROM t1 USE INDEX FOR JOIN (idx_a) FOR ORDER BY (idx_b);
```

| Hint | Поведение |
| :--- | :--- |
| `USE INDEX` | Оптимизатор рассматривает только перечисленные индексы (но full scan всё ещё возможен) |
| `FORCE INDEX` | Как `USE`, но сканирование таблицы считается очень дорогим — индекс используется почти всегда |
| `IGNORE INDEX` | Перечисленные индексы исключаются из рассмотрения |

**Когда применять:** `FORCE INDEX` — когда оптимизатор упорно выбирает
full scan на большом диапазоне (устаревшая статистика, неравномерное
распределение). Это временный hotfix; постоянное решение —
`ANALYZE TABLE` или пересмотр индекса.

### Специфика MariaDB

MariaDB поддерживает классический синтаксис `USE/FORCE/IGNORE INDEX`, а также свои специфические подсказки:
*   **`/*M! ... */`** — комментарии, выполняемые только MariaDB.
*   **`ANALYZE FORMAT=JSON`** — показывает не только план, но и **реальное время** выполнения каждого узла (аналог `EXPLAIN ANALYZE` в MySQL).
*   **`ANALYZE FORMAT=tree`** — иерархический вывод плана.

---

## Практические сценарии

### 1. Базовый анализ медленного запроса

```sql
-- 1. Получить список медленных запросов из Performance Schema
SELECT
  digest_text,
  count_star,
  sum_timer_wait / 1e12 AS total_time_sec,
  avg_timer_wait / 1e9 AS avg_time_ms,
  sum_rows_examined,
  sum_rows_sent
FROM performance_schema.events_statements_summary_by_digest
ORDER BY sum_timer_wait DESC
LIMIT 10;

-- 2. Проанализировать план конкретного запроса
EXPLAIN FORMAT=TREE
SELECT * FROM orders WHERE customer_id = 123 AND order_date > '2026-01-01';

-- 3. Проверить реальное выполнение
EXPLAIN ANALYZE
SELECT * FROM orders WHERE customer_id = 123 AND order_date > '2026-01-01';
```

### 2. Обнаружение неиспользуемых индексов

Неиспользуемые индексы замедляют `INSERT`/`UPDATE` и увеличивают время бэкапа.

```sql
-- MySQL 8.0+: через sys schema
SELECT
  object_schema,
  object_name,
  index_name,
  rows_selected,
  rows_inserted,
  rows_updated,
  rows_deleted
FROM sys.schema_unused_indexes
ORDER BY object_schema, object_name;

-- Через Performance Schema напрямую
SELECT
  object_schema,
  object_name,
  index_name,
  idx_scan,
  last_idx_scan
FROM performance_schema.table_io_waits_summary_by_index_usage
WHERE object_schema NOT IN ('mysql', 'sys', 'performance_schema', 'information_schema')
  AND index_name IS NOT NULL
ORDER BY idx_scan ASC;
```

### 3. Использование sys schema для анализа

**sys schema** предоставляет готовые представления для быстрого диагноза:

```sql
-- Топ-10 запросов по общему времени
SELECT * FROM sys.statements_with_runtimes_in_95th_percentile LIMIT 10;

-- Запросы с полным сканированием таблиц
SELECT * FROM sys.statements_with_full_table_scans;

-- Запросы, сортирующие на диске (Using filesort)
SELECT * FROM sys.statements_with_sorting;

-- Анализlock
SELECT * FROM sys.memory_global_by_current_bytes LIMIT 10;
```

### 4. Создание индекса на основе анализа EXPLAIN

Пример workflow: запрос с `USING filesort` и `USING temporary`.

**Исходный запрос:**
```sql
SELECT customer_id, SUM(total_amount) as total
FROM orders
WHERE order_date >= '2026-01-01'
GROUP BY customer_id
ORDER BY total DESC;
```

**EXPLAIN показывает:** `Using filesort`, `Using temporary`, `type=range`.

**Решение:** Создать покрывающий составной индекс:
```sql
-- Индекс покрывает WHERE и GROUP BY
CREATE INDEX idx_orders_date_customer_amount
ON orders (order_date, customer_id, total_amount);
```

**Проверка:**
```sql
EXPLAIN FORMAT=TREE
SELECT customer_id, SUM(total_amount) as total
FROM orders
WHERE order_date >= '2026-01-01'
GROUP BY customer_id
ORDER BY total DESC;

-- Должен показать: type=range, key=idx_orders_date_customer_amount, Extra=Using index
```

### 5. Работа с гистограммами

Для столбцов с неравномерным распределением (например, `status` с 90% записей `active`) оптимизатор может делать неверные предположения о селективности.

```sql
-- Создание гистограммы (MySQL 8.0+)
CREATE TABLE customers (
  id INT PRIMARY KEY,
  status VARCHAR(20),
  region VARCHAR(20)
);

-- Создание гистограммы на столбце status
ALTER TABLE customers
  ADD COLUMN status_histogram JSON
  GENERATED ALWAYS AS (JSON_OBJECT()) VIRTUAL;

-- Или через UPDATE:
UPDATE customers SET status_histogram = JSON_OBJECT();

-- Создание гистограммы через ANALYZE TABLE
ANALYZE TABLE customers UPDATE HISTOGRAM ON status WITH 100 BUCKETS;

-- Проверка гистограммы
SELECT * FROM information_schema.column_statistics
WHERE table_name = 'customers' AND column_name = 'status';
```

### 6. Валидация после оптимизации

После применения изменений (создание индекса, обновление статистики) выполните проверку:

```sql
-- 1. Проверьте, что индекс используется
EXPLAIN FORMAT=JSON
SELECT * FROM orders WHERE customer_id = 123\G

-- Ищите в выводе: "key": "idx_customer_id"

-- 2. Сравните реальное время выполнения
SET profiling = 1;
SELECT * FROM orders WHERE customer_id = 123;
SHOW PROFILES;
SHOW PROFILE FOR QUERY 1;

-- 3. Проверьте метрики Performance Schema
SELECT
  event_name,
  count_star,
  sum_timer_wait / 1e12 AS total_time_sec,
  avg_timer_wait / 1e9 AS avg_time_ms
FROM performance_schema.events_statements_summary_by_digest
WHERE digest_text LIKE '%customer_id = 123%';
```

---

## Валидация после развертывания изменений

### Чек-лист проверки

1.  **План выполнения:** Убедитесь, что запрос использует ожидаемый индекс (`key` не `NULL`).
2.  **Тип доступа:** `type` должен быть `ref`, `eq_ref`, `range` или лучше. `ALL` означает полное сканирование.
3.  **Extra-индикаторы:** Отсутствуют `Using filesort` и `Using temporary` (если они не ожидаются).
4.  **Фильтрация:** `filtered` % должен быть высоким (>90%) при использовании индекса.
5.  **Реальное время:** Сравните `EXPLAIN ANALYZE` до и после изменений.
6.  **Метрики мониторинга:** Проверьте `Handler_read_next`, `Handler_read_rnd_next`, `Sort_merge_passes` в `SHOW GLOBAL STATUS`.

### Команды для автоматизации проверки

```bash
# Скрипт для сравнения планов до/после
mysql -u root -p -e "
SELECT 'BEFORE' as stage;
EXPLAIN FORMAT=JSON SELECT ...;
ANALYZE TABLE orders;
SELECT 'AFTER' as stage;
EXPLAIN FORMAT=JSON SELECT ...;
"
```

---

## Устранение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **ALL / Full Table Scan** | Отсутствует индекс или оптимизатор выбрал sequential scan из-за низкой селективности (>20-30% строк) | Создать индекс или пересмотреть логику запроса. Для больших таблиц с низкой селективностью sequential scan может быть оптимальным. |
| **Using filesort** | Отсутствует индекс для `ORDER BY`/`GROUP BY` | Создать составной индекс, покрывающий поля сортировки. Проверить `sort_buffer_size`. |
| **Using temporary** | `GROUP BY`/`DISTINCT` по полям без индекса или `UNION` | Индексировать поля группировки. Заменить `UNION` на `UNION ALL` если применимо. |
| **Using index** (в Extra) | Отлично — Covering Index. Запрос выполнен без обращения к таблице. | Нет действий — это оптимальный сценарий. |
| **DEPENDENT SUBQUERY** | Вложенный подзапрос выполняется для каждой строки внешнего запроса | Переписать на JOIN или использовать CTE (MySQL 8.0.14+). |
| **План "плывёт" после ANALYZE** | Устаревшая статистика или extreme data skew | Создать гистограмму. Рассмотреть `optimizer_switch='condition_fanout_filter=off'`. |
| **EXPLAIN ANALYZE не доступен** | Версия MySQL < 8.0.18 или MariaDB < 10.1 | Использовать `SET profiling = 1` (deprecated в 8.0) или `SHOW PROFILES`. |
| **Access denied для sys schema** | Пользователь не имеет прав на `performance_schema` | `GRANT SELECT ON performance_schema.* TO 'user'@'host';` |

---

## Лучшие практики

1.  **Анализ перед индексацией:** Всегда используйте `EXPLAIN` или `sys schema` перед созданием индекса. Индексы замедляют запись.
2.  **Обновление статистики:** После массовой загрузки данных или изменений >10% строк выполните `ANALYZE TABLE`. В продакшене используйте `ANALYZE TABLE ... UPDATE HISTOGRAM` для неравномерных данных.
3.  **Covering Index:** Создавайте покрывающие индексы для частых запросов. Используйте `INCLUDE` для неключевых столбцов (PostgreSQL, SQL Server). В MySQL добавьте столбцы в конец индекса.
4.  **Избегайте функций в WHERE:** `WHERE YEAR(created_at) = 2026` не использует индекс. Перепишите на `WHERE created_at BETWEEN '2026-01-01' AND '2026-12-31'`.
5.  **Проверяйте execution time:** `EXPLAIN` показывает оценку, не реальное время. Используйте `EXPLAIN ANALYZE` для точной диагностики.
6.  **Hints как временная мера:** Всегда документируйте причину использования hint. Создайте тикет на пересмотр при изменении данных.
7.  **Мониторинг в продакшене:** Включите `slow_query_log` и используйте `performance_schema` для обнаружения проблемных запросов до их влияния на пользователей.

---

## Граничные случаи и ограничения

### Известные ограничения

1.  **NULL в индексах:** В MySQL `NULL` значения индексируются в B-Tree, но `IS NULL` может использовать индекс, а `IS NOT NULL` — нет, в зависимости от версии и оптимизатора.
2.  **LIKE с подстановочными знаками:** `LIKE '%pattern%'` не использует индекс (Full Scan). `LIKE 'pattern%'` использует range scan. Для полнотекстового поиска используйте `FULLTEXT` индекс (InnoDB/MariaDB) или внешние движки (Elasticsearch).
3.  **Неявное приведение типов:** Если столбец `bigint`, а в запросе передается строка `'123'`, индекс может не сработать из-за неявного приведения. Используйте явные типы.
4.  **Статистика и extreme data skew:** При распределении 90/10 оптимизатор может выбрать неоптимальный план. Решение — гистограммы или hints.
5.  **Подзапросы в FROM:** В MySQL до 8.0.14 подзапросы в `FROM` материализуются в временные таблицы. В 8.0.14+ оптимизатор может их де-материализовать (derived merge), но это зависит от флага `derived_merge`.
6.  **CTE (Common Table Expressions):** Рекурсивные CTE в MySQL до 8.0.19 не поддерживались. С 8.0.19+ рекурсивные CTE работают, но имеют ограничения на глубину (CTE_MAX_RECURSION_DEPTH).
7.  **Partition Pruning:** Для партиционированных таблиц проверяйте, что `EXPLAIN` показывает `partitions` с подмножеством секций. Если пустой массив — pruning не сработал.

---

## Дополнительная информация

### См. также

- **[Конфигурация MySQL](../configuration.md)** — настройка `sort_buffer_size`, `tmp_table_size`, `optimizer_switch`.
- **[Индексы в БД (Теория)](../../Concepts/indexes.md)** — как работают B-Tree и когда они не спасают.
- **[Механизмы оптимизатора MySQL](../optimizer_mechanisms.md)** — ICP, MRR и Batched Key Access.
- **[Мониторинг MySQL](../monitoring.md)** — отслеживание `Sort_merge_passes`, `Handler_read_rnd_next` и других метрик.
- **[Блокировки и Deadlocks](../locking_and_deadlocks.md)** — как планы выполнения влияют на захват ресурсов.

### Полезные ссылки

- [MySQL 8.4 Reference: EXPLAIN Statement](https://dev.mysql.com/doc/refman/8.4/en/explain.html)
- [MySQL 8.4 Reference: Optimizer Hints](https://dev.mysql.com/doc/refman/8.4/en/optimizer-hints.html)
- [MySQL 8.4 Reference: ANALYZE TABLE](https://dev.mysql.com/doc/refman/8.4/en/analyze-table.html)
- [MariaDB Knowledge Base: EXPLAIN](https://mariadb.com/kb/en/explain/)
