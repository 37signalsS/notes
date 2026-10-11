# Временные таблицы (Temporary Tables) в MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **Temporary Table (временная таблица)** — таблица, существующая только в рамках сессии, создаваемая явно (`CREATE TEMPORARY TABLE`) или неявно оптимизатором для выполнения запроса (GROUP BY, ORDER BY, DISTINCT, подзапросы, UNION).
*   **Internal Temporary Table (внутренняя временная таблица)** — таблица, создаваемая оптимизатором автоматически для промежуточных результатов. Начинается в памяти (движок MEMORY) и при превышении лимита сбрасывается на диск (по умолчанию Aria в MariaDB 10.5+).
*   **Явная временная таблица** — создаётся пользователем командой `CREATE TEMPORARY TABLE`. Видна только текущей сессии, имеет приоритет над постоянной таблицей с тем же именем, автоматически удаляется при закрытии сессии.
*   **`tmp_table_size` / `max_heap_table_size`** — лимиты размера внутренней временной таблицы в памяти. Реальный лимит = `MIN(tmp_table_size, max_heap_table_size)`. При превышении таблица конвертируется в on-disk (Aria).
*   **`max_heap_table_size`** — также ограничивает размер пользовательских таблиц движка MEMORY.
*   **`Created_tmp_tables`** — счётчик созданных внутренних временных таблиц (всех).
*   **`Created_tmp_disk_tables`** — счётчик внутренних временных таблиц, сброшенных на диск. Высокий ratio `Created_tmp_disk_tables / Created_tmp_tables` — сигнал нехватки памяти или неоптимальных запросов.
*   **`Created_tmp_files`** — счётчик временных файлов, созданных на диске для внутренних временных таблиц.
*   **`internal_tmp_disk_storage_engine`** — движок для on-disk внутренних временных таблиц. В MariaDB 10.5+ по умолчанию `Aria`. Ранее использовался MyISAM.
*   **`tmpdir`** — каталог для размещения временных файлов (on-disk внутренние временные таблицы Aria, а также другие временные файлы).

## Базовые концепции

### Два вида временных таблиц

1.  **Явные (`CREATE TEMPORARY TABLE`)** — создаются пользователем, видны только в текущей сессии, автоматически удаляются при закрытии сессии. Могут использовать любой доступный движок. Имеют приоритет над постоянными таблицами с тем же именем в сессии.
2.  **Внутренние (optimizer-created)** — создаются оптимизатором для промежуточных результатов: `GROUP BY`, `ORDER BY`, `DISTINCT`, `UNION`, производные таблицы (derived tables), материализация подзапросов. Начинаются в памяти (MEMORY), при превышении лимита — сбрасываются на диск (Aria).

### Когда оптимизатор создаёт внутреннюю временную таблицу

*   `GROUP BY` без подходящего индекса (требуется агрегация).
*   `ORDER BY` по выражению, не покрытому индексом (`Using filesort` + временная таблица).
*   `DISTINCT` без подходящего индекса.
*   `UNION` (не `UNION ALL` во многих случаях).
*   Производные таблицы (`FROM (SELECT ...)`).
*   Материализация некоторых подзапросов.
*   Некоторые `JOIN` с `ORDER BY`, когда сортировка не может быть выполнена по индексу.

### Путь выполнения: память → диск

```text
Запрос с необходимостью промежуточных данных
  ↓
Внутренняя временная таблица (MEMORY, in-memory)
  ↓ размер > MIN(tmp_table_size, max_heap_table_size)
Конвертация в on-disk (Aria, internal_tmp_disk_storage_engine)
  ↓
Запись во временный каталог (tmpdir)
```

**Критично:** конвертация in-memory → on-disk — дорогостоящая операция (двойное хранение, I/O). Цель — минимизировать значение `Created_tmp_disk_tables`.

## Практические сценарии

### 1. Проверка текущего состояния

```sql
-- Лимиты
SHOW VARIABLES LIKE 'tmp_table_size';
SHOW VARIABLES LIKE 'max_heap_table_size';
SHOW VARIABLES LIKE 'internal_tmp_disk_storage_engine';
SHOW VARIABLES LIKE 'tmpdir';

-- Счётчики внутренних временных таблиц
SHOW GLOBAL STATUS LIKE 'Created_tmp%';
-- Created_tmp_tables       — всего создано внутренних временных таблиц
-- Created_tmp_disk_tables  — сброшено на диск
-- Created_tmp_files        — файлов на диске
```

#### Расчёт доли временных таблиц, сброшенных на диск

```sql
-- Целевое значение: < 25%. Чем ниже — тем лучше.
SELECT
  ROUND(
    100 *
    GREATEST(
      (SELECT VARIABLE_VALUE FROM performance_schema.global_status
       WHERE VARIABLE_NAME = 'Created_tmp_disk_tables'),
      0
    ) /
    NULLIF(
      (SELECT VARIABLE_VALUE FROM performance_schema.global_status
       WHERE VARIABLE_NAME = 'Created_tmp_tables'),
      0
    ),
    2
  ) AS tmp_disk_ratio_percent;
```

### 2. Настройка

```ini
[mariadb]
# Лимит in-memory внутренней временной таблицы (реальный = MIN из двух)
tmp_table_size = 64M
max_heap_table_size = 64M

# Движок для on-disk внутренних временных таблиц (Aria — дефолт с 10.5)
internal_tmp_disk_storage_engine = Aria

# Каталог для временных файлов
tmpdir = /tmp
```

**Важно:**
*   `tmp_table_size` и `max_heap_table_size` являются per-connection (на соединение). При большом `max_connections` суммарное потребление RAM может быть значительным — не завышайте без расчёта.
*   MEMORY-движок **не поддерживает** столбцы `BLOB`/`TEXT`. Если внутренняя временная таблица должна содержать `BLOB`/`TEXT` — она будет создана сразу на диске (Aria), минуя in-memory-этап.
*   Реальный лимит in-memory — всегда `MIN(tmp_table_size, max_heap_table_size)`. Рекомендуется выставлять эти значения одинаковыми для предсказуемости.

### 3. Явные временные таблицы

```sql
-- Создание явной временной таблицы
CREATE TEMPORARY TABLE tmp_orders (
  id INT PRIMARY KEY,
  total DECIMAL(10,2),
  created_at DATETIME,
  INDEX idx_total (total),
  INDEX idx_created_at (created_at)
) ENGINE = InnoDB;

-- Использование (видна только в текущей сессии)
INSERT INTO tmp_orders
SELECT id, total, created_at
FROM orders
WHERE created_at > NOW() - INTERVAL 1 DAY;

-- Выборка
SELECT * FROM tmp_orders ORDER BY total DESC LIMIT 10;

-- Приоритет над постоянной таблицей с тем же именем
-- Если существует постоянная orders_tmp — будет использована временная
SELECT * FROM tmp_orders;

-- Проверка существования
SHOW TABLES LIKE 'tmp_orders';

-- Удаление (можно не делать — удалится автоматически при закрытии сессии)
DROP TEMPORARY TABLE tmp_orders;
```

**Особенности явных временных таблиц:**
*   Не видны другим сессиям.
*   Имеют приоритет над постоянными таблицами с тем же именем в текущей сессии.
*   Автоматически удаляются при закрытии сессии.
*   `ROLLBACK` не удаляет саму временную таблицу — откатываются только DML-изменения внутри неё.
*   Репликация: поведение зависит от формата бинлога (Statement/Mixed/Row). Следует учитывать особенности репликации в конкретном окружении.

### 4. Поиск запросов, создающих временные таблицы

```sql
-- Через Performance Schema (по дайджестам запросов)
SELECT
  DIGEST_TEXT,
  COUNT_STAR,
  SUM_CREATED_TMP_TABLES AS sum_created_tmp,
  SUM_CREATED_TMP_DISK_TABLES AS sum_created_tmp_disk
FROM performance_schema.events_statements_summary_by_digest
WHERE SUM_CREATED_TMP_TABLES > 0
ORDER BY SUM_CREATED_TMP_DISK_TABLES DESC
LIMIT 10;
```

```sql
-- Через sys schema (если доступен)
SELECT
  query,
  calls,
  tmp_tables,
  tmp_disk_tables
FROM sys.statement_analysis
WHERE tmp_tables > 0 OR tmp_disk_tables > 0
ORDER BY tmp_disk_tables DESC
LIMIT 10;
```

### 5. Диагностика через EXPLAIN

```sql
EXPLAIN FORMAT=JSON SELECT customer_id, COUNT(*) FROM orders GROUP BY customer_id\G
-- Или классический:
EXPLAIN SELECT customer_id, COUNT(*) FROM orders GROUP BY customer_id;
```

**На что обращать внимание:**
*   `Extra: "Using temporary"` — оптимизатор создаёт внутреннюю временную таблицу (чаще при `GROUP BY`/`DISTINCT` без подходящего индекса).
*   `Extra: "Using temporary; Using filesort"` — создаётся временная таблица + дополнительная сортировка.
*   `Using filesort` сам по себе не всегда требует временной таблицы, но часто сочетается с ней.

**Типичные решения:**
*   Добавить индекс по столбцам `GROUP BY` (либо покрывающий индекс).
*   Сопоставить порядок `GROUP BY`/`ORDER BY` с индексом.
*   Избегать сортировки по выражениям, не покрываемым индексом.

## Устранение неполадок (Troubleshooting)

### `Created_tmp_disk_tables` растёт быстрее `Created_tmp_tables`

*   **Причина:** внутренние временные таблицы превышают `MIN(tmp_table_size, max_heap_table_size)`; либо в результате присутствуют столбцы `BLOB`/`TEXT` (MEMORY их не поддерживает) — таблица сразу создаётся на диске.
*   **Диагностика:**
  ```sql
  SHOW GLOBAL STATUS LIKE 'Created_tmp%';
  -- Считаем ratio < 25% — норма
  ```
*   **Решение:**
  *   Увеличить `tmp_table_size` и `max_heap_table_size` (одинаковые значения).
  *   Добавить/скорректировать индексы под `GROUP BY`/`ORDER BY`.
  *   Избегать `BLOB`/`TEXT` в промежуточных результатах, по возможности нормализовать/проецировать только нужные столбцы.
  *   Проверить, нет ли избыточной сортировки/группировки.

### Ошибка «The table '...' is full»

*   **Причина:** внутренняя временная таблица превысила лимит in-memory (`tmp_table_size`/`max_heap_table_size`) и при конвертации/работе с on-disk-таблицей не хватает места в `tmpdir`, либо превысила ограничения движка Aria для конкретного файла.
*   **Диагностика:**
  ```bash
  df -h $(dirname $(mariadb -Nse "SELECT @@tmpdir"))
  ```
*   **Решение:**
  *   Увеличить место в `tmpdir` (или перенести `tmpdir` на диск с большим объёмом/быстрее).
  *   Увеличить `tmp_table_size`/`max_heap_table_size`, если есть свободная RAM и нет риска по `max_connections`.
  *   Оптимизировать запрос (меньше строк/столбцов в промежуточном результате).
  *   При необходимости временно увеличить лимиты с последующим мониторингом.

### Медленные запросы с `Using temporary`

*   **Причина:** `GROUP BY`/`ORDER BY`/`DISTINCT` без подходящего индекса; материализация производных таблиц.
*   **Решение:**
  *   Проанализировать `EXPLAIN`/`EXPLAIN FORMAT=JSON`.
  *   Создать покрывающий индекс по столбцам, участвующим в `GROUP BY`/`ORDER BY`.
  *   Убрать из `SELECT` ненужные столбцы (особенно `BLOB`/`TEXT`).
  *   Рассмотреть переписывание запроса (избежать derived tables, где неэффективно).

### Временные файлы не очищаются / tmpdir переполнен

*   **Причина:** Aria временные файлы обычно удаляются при закрытии сессии/завершении запроса. При аварийном отключении сессии файлы теоретически могут остаться (редко в нормальных условиях).
*   **Решение:**
  *   Мониторить `tmpdir`: `df -h /tmp` + наличие старых `#sql*`, `aria_tmp*` файлов.
  *   Не удалять файлы вручную во время активной работы MariaDB — лучше перезапуск сессии/очистка по завершении неактивных соединений.
  *   Настроить алертинг по свободному месту в `tmpdir`.

## Лучшие практики (Best Practices)

1.  **Контролировать соотношение**: `Created_tmp_disk_tables / Created_tmp_tables < 25%`. Значение > 50% — явный сигнал к оптимизации.
2.  **Устанавливать одинаково**: `tmp_table_size` и `max_heap_table_size` — реальный лимит = `MIN(...)`. Рекомендуется держать их равными для предсказуемости.
3.  **Индексировать**: добавлять индексы под `GROUP BY`, `ORDER BY`, `DISTINCT`. Правильно подобранный индекс часто полностью исключает создание внутренних временных таблиц.
4.  **Соблюдать баланс RAM**: `tmp_table_size` — per-connection. При высокой конкуренции соединений избыточный лимит ведёт к большому пиковому потреблению памяти.
5.  **Избегать BLOB/TEXT в промежуточных агрегациях**: MEMORY их не поддерживает — таблица сразу на диске. Проецируйте только необходимые столбцы.
6.  **Мониторить `tmpdir`**: on-disk временные таблицы пишутся в `tmpdir`. Обязательно следить за свободным местом и производительностью диска (для нагруженных систем предпочтительнее быстрый диск).
7.  **Минимизировать промежуточные выборки**: уменьшение количества строк/столбцов в агрегациях снижает вероятность сброса на диск.
8.  **Анализировать топ-запросы**: использовать Performance Schema/sys для выявления запросов, генерирующих наибольшее количество `tmp_disk_tables`.
9.  **Явные временные таблицы**: применять осознанно, с подходящим `ENGINE` под задачу (InnoDB — для транзакционной консистентности, MEMORY — только когда размер гарантированно мал и нет BLOB/TEXT).

## Дополнительная информация

### См. также

*   [Оптимизация запросов](../query_optimization.md) — диагностика `Using temporary` через EXPLAIN, работа с индексами.
*   [Управление памятью](../memory_management.md) — per-thread буферы, параметры памяти MariaDB.
*   [Мониторинг](../monitoring.md) — алерты на `Created_tmp_disk_tables`, метрики производительности.

### Внешние ресурсы

*   [MariaDB: Temporary Tables](https://mariadb.com/kb/en/temporary-tables/)
*   [MariaDB: Internal Temporary Tables](https://mariadb.com/kb/en/internal-temporary-tables/)
*   [MariaDB: CREATE TEMPORARY TABLE](https://mariadb.com/kb/en/create-temporary-table/)
