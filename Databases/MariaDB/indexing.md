# Индексы в MariaDB: типы, создание и обслуживание

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **Индекс (Index)** — структура данных, ускоряющая поиск строк по значениям столбцов. В MariaDB реализованы B-tree (по умолчанию для InnoDB/Aria/MyISAM), R-tree (SPATIAL), FULLTEXT и HASH (MEMORY).
*   **Clustered Index (кластерный индекс)** — в InnoDB данные таблицы физически хранятся в порядке первичного ключа (PK). Каждая таблица InnoDB имеет ровно один кластерный индекс. Если PK не задан, InnoDB выбирает первый уникальный NOT NULL индекс, иначе создаёт скрытый `GEN_CLUST_INDEX` по rowid.
*   **Secondary Index (вторичный индекс)** — любой индекс, кроме кластерного. Листья вторичного индекса содержат значение PK, поэтому поиск по вторичному индексу требует дополнительного обращения к кластерному (index lookup → PK → clustered lookup).
*   **Covering Index (покрывающий индекс)** — индекс, содержащий все столбцы, нужные для запроса. Позволяет ответить на запрос, не обращаясь к данным таблицы. В `EXPLAIN` отмечается как `Using index` в столбце `Extra`.
*   **Composite Index (составной индекс)** — индекс по нескольким столбцам. Порядок столбцов критичен: индекс `(a, b, c)` используется для условий по `a`, `(a, b)`, `(a, b, c)`, но **не** для условий только по `b` или `c` (правило leftmost prefix).
*   **Prefix Index (префиксный индекс)** — индекс по первым N символам строкового столбца (`INDEX (col(20))`). Экономит место, но не поддерживает `ORDER BY` / `GROUP BY` и не может быть covering.
*   **Ignored Index (игнорируемый индекс, MariaDB 10.6+)** — аналог MySQL Invisible Index: индекс существует и обслуживается при записи, но оптимизатор его не использует. Служит для безопасной проверки необходимости индекса перед удалением. **Важно:** в MariaDB это отдельная фича с другим синтаксисом (`ALTER INDEX ... IGNORED`), а не MySQL-ский `INVISIBLE`.
*   **Invisible Column (невидимый столбец, MariaDB 10.3+)** — столбец, не отображаемый в `SELECT *` и требующий явного указания. **Не путать** с невидимыми индексами — это разные механизмы.
*   **Generated Column (вычисляемый столбец)** — столбец, значение которого вычисляется из выражения. Может быть индексирован, что позволяет индексировать вычисляемые значения (аналог функциональных индексов MySQL 8.0.13+).
*   **FULLTEXT Index** — индекс для полнотекстового поиска (`MATCH ... AGAINST`). Поддерживается InnoDB (MariaDB 10.0.5+) и MyISAM.
*   **SPATIAL Index (R-tree)** — индекс для геоданных (`GEOMETRY`). Поддерживается MyISAM и InnoDB (MariaDB 10.2.2+).

## Базовые концепции

### Типы индексов по движкам

| Тип индекса | InnoDB | Aria | MyISAM | MEMORY | Назначение |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **B-tree** | Да | Да | Да | Да | По умолчанию; равенства, диапазоны, сортировка |
| **FULLTEXT** | Да (10.0.5+) | Нет | Да | Нет | Полнотекстовый поиск |
| **SPATIAL (R-tree)** | Да (10.2.2+) | Нет | Да | Нет | Геоданные |
| **HASH** | Нет | Нет | Нет | Да | Только равенства (MEMORY) |

### Анатомия составного индекса

Индекс `(a, b, c)` эффективен для:
*   `WHERE a = 1`
*   `WHERE a = 1 AND b = 2`
*   `WHERE a = 1 AND b = 2 AND c = 3`
*   `WHERE a = 1 AND b > 2` (range на b)
*   `ORDER BY a, b` (если a — equality)

Индекс `(a, b, c)` **не** эффективен для:
*   `WHERE b = 2` (нарушение leftmost prefix)
*   `WHERE a > 1 AND b = 2` (range на a отменяет использование b)
*   `WHERE a = 1 AND c = 3` (пропуск b)

**Правило:** в составном индексе сначала столбцы с равенствами (`=`), потом столбцы с диапазонами (`<`, `>`, `BETWEEN`), потом столбцы для `ORDER BY`.

### Ignored Indexes (MariaDB 10.6+) — безопасное удаление индексов

MariaDB 10.6+ поддерживает игнорируемые индексы — механизм, аналогичный MySQL Invisible Index, но с другим синтаксисом. Индекс в состоянии `IGNORED` продолжает обслуживаться при `INSERT/UPDATE/DELETE`, но оптимизатор его не использует. Это позволяет проверить, не сломается ли производительность без индекса, прежде чем его удалить.

**Важно:** MySQL-ский синтаксис `CREATE INDEX ... INVISIBLE` / `ALTER TABLE ... ALTER INDEX ... INVISIBLE` в MariaDB **не поддерживается**. Используйте `IGNORED`.

## Практические сценарии

### 1. Создание индексов

```sql
-- Простой индекс
CREATE INDEX idx_customer ON orders (customer_id);

-- Составной индекс (порядок важен!)
CREATE INDEX idx_customer_status ON orders (customer_id, status);

-- Уникальный индекс
CREATE UNIQUE INDEX idx_email ON users (email);

-- Префиксный индекс (первые 20 символов)
CREATE INDEX idx_name_prefix ON users (last_name(20));

-- Индекс на вычисляемом столбце
ALTER TABLE products ADD COLUMN name_lower VARCHAR(255)
  AS (LOWER(name)) STORED,
  ADD INDEX idx_name_lower (name_lower);

-- FULLTEXT (InnoDB, MariaDB 10.0.5+)
CREATE FULLTEXT INDEX idx_ft ON articles (title, body);

-- SPATIAL (InnoDB, MariaDB 10.2.2+)
CREATE SPATIAL INDEX idx_geo ON locations (coords);
```

### 2. Ignored Indexes (MariaDB 10.6+)

```sql
-- Создать индекс сразу в игнорируемом состоянии
CREATE INDEX idx_test ON orders (status) IGNORED;

-- Перевести существующий индекс в игнорируемое состояние
ALTER TABLE orders ALTER INDEX idx_status IGNORED;

-- Вернуть индекс в активное состояние
ALTER TABLE orders ALTER INDEX idx_status VISIBLE;

-- Проверить состояние индексов
SELECT INDEX_NAME, IGNORED FROM information_schema.STATISTICS
  WHERE TABLE_NAME = 'orders';

-- Удалить индекс после проверки
DROP INDEX idx_test ON orders;
```

**Валидация:** после перевода индекса в `IGNORED` повторите `EXPLAIN` на целевом запросе — если план ухудшился (`type = ALL`), индекс нужен; если план не изменился — индекс можно удалить.

### 3. Обслуживание индексов

```sql
-- Обновить статистику индексов (кардинальность)
ANALYZE TABLE orders;

-- Проверить целостность таблицы и индексов
CHECK TABLE orders;

-- Проверка через CLI
mariadb-check --check orders

-- Список индексов таблицы
SHOW INDEX FROM orders;
SHOW INDEXES FROM orders;

-- Размер индексов
SELECT
  TABLE_NAME,
  INDEX_NAME,
  ROUND(STAT_VALUE * @@innodb_page_size / 1024 / 1024, 2) AS size_mb
FROM mysql.innodb_index_stats
WHERE DATABASE_NAME = 'shop' AND TABLE_NAME = 'orders'
  AND STAT_NAME = 'size';
```

### 4. Поиск неиспользуемых индексов

```sql
-- Индексы, которые никогда не использовались для чтения (MariaDB 10.5+)
SELECT * FROM sys.schema_unused_indexes;

-- Или через Performance Schema
SELECT OBJECT_SCHEMA, OBJECT_NAME, INDEX_NAME
FROM performance_schema.table_io_waits_summary_by_index_usage
WHERE INDEX_NAME IS NOT NULL AND COUNT_STAR = 0
  AND OBJECT_SCHEMA NOT IN ('mysql', 'sys', 'performance_schema', 'information_schema');
```

### 5. Дублирующиеся и избыточные индексы

```sql
-- Поиск дубликатов через sys schema
SELECT * FROM sys.schema_redundant_indexes;

-- Ручная проверка: индексы с одинаковым leftmost prefix
SELECT TABLE_NAME, INDEX_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS cols
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = 'shop'
GROUP BY TABLE_NAME, INDEX_NAME
ORDER BY TABLE_NAME, cols;
```

## Устранение неполадок (Troubleshooting)

### Индекс не используется оптимизатором

*   **Причина:** нарушение leftmost prefix, скрытое приведение типов, функция над столбцом, или оптимизатор оценил full scan как дешевле (высокая селективность).
*   **Диагностика:** `EXPLAIN` — проверьте `possible_keys` и `key`. Проверьте типы данных в условии.
*   **Решение:** пересоздайте индекс с правильным порядком столбцов; устраните приведение типов; используйте `FORCE INDEX` для проверки (но не в production-коде без необходимости).

### Медленная запись при большом числе индексов

*   **Причина:** каждый индекс обслуживается при `INSERT/UPDATE/DELETE`. 10+ индексов на таблице заметно замедляют запись.
*   **Диагностика:** `sys.schema_unused_indexes` — найдите неиспользуемые индексы.
*   **Решение:** удалите неиспользуемые и дублирующиеся индексы; перед удалением переведите в `IGNORED` (10.6+) и проверьте план.

### Префиксный индекс не ускоряет сортировку

*   **Причина:** префиксные индексы не хранят полные значения, поэтому не могут обслуживать `ORDER BY` / `GROUP BY`.
*   **Решение:** для сортировки создайте индекс на полном столбце или на вычисляемом столбце с нужной длиной.

## Лучшие практики (Best Practices)

1.  **PK обязателен:** каждая таблица InnoDB должна иметь PK — иначе InnoDB создаёт скрытый кластерный индекс по rowid, что замедляет вторичные индексы и репликацию.
2.  **Составные индексы по правилу:** равенства → диапазоны → сортировка.
3.  **Covering index:** включайте в индекс столбцы из `SELECT`, если запрос частый — это исключает обращение к данным.
4.  **Ignored Indexes перед удалением:** в MariaDB 10.6+ переводите индекс в `IGNORED` на 1-2 недели перед `DROP INDEX`.
5.  **Не более 5-6 индексов на таблицу** для таблиц с интенсивной записью.
6.  **Мониторьте неиспользуемые индексы** через `sys.schema_unused_indexes` ежемесячно.

## Дополнительная информация

### См. также

*   **[Оптимизация запросов](query_optimization.md)** — EXPLAIN, ANALYZE, гистограммы.
*   **[Общие концепции индексов](../Concepts/indexes.md)** — теория B-tree, кардинальность, покрывающие индексы.
*   **[Движки хранения](storage_engines.md)** — особенности индексов в MyRocks, ColumnStore.
*   **[MySQL: Индексы](../MySQL/indexing.md)** — отличия MySQL (Skip Scan, Multi-Valued, Descending, Invisible).
*   **[Online DDL](online_schema_change.md)** — создание индексов без блокировок.

### Внешние ресурсы

*   [MariaDB CREATE INDEX](https://mariadb.com/kb/en/create-index/)
*   [MariaDB Ignored Indexes](https://mariadb.com/kb/en/ignored-indexes/)
*   [MariaDB Index Hints](https://mariadb.com/kb/en/index-hints/)
*   [MariaDB Generated Columns](https://mariadb.com/kb/en/generated-columns/)
