# Временные таблицы (Temporary Tables) в MySQL

**Актуально для:** MySQL 8.4 LTS / 9.7 LTS / 26.x Innovation

> **EoL-замечание:** MySQL 8.0 достиг конца поддержки (8.0.46, апрель 2026). Ниже описано
> поведение 8.4/9.x; для 8.0 устаревшие детали отмечены отдельно.

## Требования и предпосылки

| Проверка | Ожидание | Где проверить |
| :--- | :--- | :--- |
| Версия MySQL | 8.0+ для TempTable; 8.4/9.x для текущих рекомендаций | `SELECT VERSION()` |
| `internal_tmp_mem_storage_engine` | `TempTable` (дефолт с 8.0); `MEMORY` — только по необходимости | `SHOW VARIABLES LIKE 'internal_tmp_mem_storage_engine'` |
| `internal_tmp_disk_storage_engine` | Переменная удалена в 8.0.16 — на 8.4 её нет | `SHOW VARIABLES LIKE 'internal_tmp_disk_storage_engine'` (должно быть 0 строк) |
| `temptable_use_mmap` | `OFF` (дефолт); `ON` — устаревшее, не рекомендуется | `SHOW VARIABLES LIKE 'temptable_use_mmap'` |
| `tmpdir` | Достаточно места; не в `datadir` | `SHOW VARIABLES LIKE 'tmpdir'` |
| `innodb_tmpdir` | Опционален, для отдельного диска | `SHOW VARIABLES LIKE 'innodb_tmpdir'` |
| `innodb_temp_tablespaces_dir` | По умолчанию `#innodb_temp` в `datadir` | `SHOW VARIABLES LIKE 'innodb_temp_tablespaces_dir'` |
| Привилегии | `SESSION_VARIABLES_ADMIN` для смены `internal_tmp_mem_storage_engine` и `big_tables` | `SHOW GRANTS` |
| Репликация | `gtid_mode = ON` — не создавать temporary table внутри транзакции (ошибка 3748) | `SHOW VARIABLES LIKE 'gtid_mode'` |

**Замечания:**
- Зарезервированные слова: `tmp_table_size`, `max_heap_table_size`, `temptable_max_ram`,
  `temptable_max_mmap`, `temptable_use_mmap`, `big_tables`, `internal_tmp_mem_storage_engine`,
  `Created_tmp_tables`, `Created_tmp_disk_tables`, `tmpdir`, `innodb_tmpdir` — не использовать
  в качестве имён таблиц, колонок или баз.
- При апгрейде с 5.7: `internal_tmp_disk_storage_engine` удалена в 8.0.16 — убрать из `my.cnf`.
- На реплике: `replica_load_tmpdir` задаёт отдельный каталог для временных файлов при репликации
  `LOAD DATA` (должен быть на дисковой ФС, не очищаемой ОС при старте).
- Пул session temporary tablespaces (10 шт.) создаётся при старте; если не получилось — старт отклоняется.

## Определения

*   **Temporary Table (временная таблица)** — таблица, существующая только в рамках сессии, создаваемая явно (`CREATE TEMPORARY TABLE`) или неявно оптимизатором для выполнения запроса (GROUP BY, ORDER BY, DISTINCT, подзапросы, UNION).
*   **Internal Temporary Table (внутренняя временная таблица)** — таблица, создаваемая оптимизатором автоматически для промежуточных результатов. Начинается в памяти (MEMORY-движок) и при превышении лимита сбрасывается на диск (InnoDB в MySQL 8.0+).
*   **`tmp_table_size` / `max_heap_table_size`** — лимиты размера внутренней временной таблицы в памяти. Реальный лимит = `MIN(tmp_table_size, max_heap_table_size)`. При превышении таблица конвертируется в on-disk (InnoDB).
*   **`internal_tmp_mem_storage_engine`** — движок для in-memory внутренних временных таблиц. Дефолт: `TempTable` (с 8.0). Можно переключить на `MEMORY` (требует `SESSION_VARIABLES_ADMIN`).
*   **`temptable_max_ram`** — глобальный лимит RAM для `TempTable` (дефолт 3% ОЗУ, минимум 1 GB, максимум 4 GB). При превышении таблица идёт в mmap-файлы или InnoDB on-disk, в зависимости от `temptable_use_mmap`.
*   **`temptable_use_mmap`** — включает mmap-переполнение `TempTable`. **Устаревшее** (deprecated), ожидается удаление. Эквивалентно `temptable_max_mmap = 0` — отключает mmap.
*   **`temptable_max_mmap`** — максимум mmap-пространства перед переходом на InnoDB on-disk (дефолт 0).
*   **`big_tables`** — сессионная переменная: при `ON` внутренние временные таблицы всегда на диске, минуя in-memory.
*   **`Created_tmp_tables`** — счётчик созданных внутренних временных таблиц (всех).
*   **`Created_tmp_disk_tables`** — счётчик временных таблиц, сброшенных на диск. Высокий ratio `Created_tmp_disk_tables / Created_tmp_tables` — сигнал нехватки памяти или неоптимальных запросов.
*   **Ограничение счётчика:** `Created_tmp_disk_tables` **не** учитывает on-disk таблицы, созданные через mmap-переполнение `TempTable`. По дефолту mmap отключён, так что счётчик точен; при включённом mmap он занижает реальное количество disk-таблиц.
*   **`internal_tmp_disk_storage_engine`** — переменная, задававшая движок для on-disk временных таблиц (MyISAM/InnoDB). **Удалена в MySQL 8.0.16**: on-disk внутренние временные таблицы всегда используют InnoDB.

## Базовые концепции

### Два вида временных таблиц

1.  **Явные (`CREATE TEMPORARY TABLE`):** создаются пользователем, видны только в сессии, автоматически удаляются при закрытии сессии. Могут использовать любой движок. Имеют приоритет над постоянными таблицами с тем же именем в сессии.
2.  **Внутренние (optimizer-created):** создаются оптимизатором для GROUP BY, ORDER BY, DISTINCT, UNION, derived tables, материализации подзапросов. Начинаются в памяти (MEMORY), при превышении лимита — сбрасываются на диск (InnoDB в 8.0+).

### Когда оптимизатор создаёт внутреннюю временную таблицу

*   `GROUP BY` без подходящего индекса.
*   `ORDER BY` по выражению, не покрытому индексом (`Using filesort` + временная таблица).
*   `DISTINCT` без индекса.
*   `UNION` (кроме `UNION ALL` в некоторых случаях).
*   Derived tables (подзапросы в FROM) — до 8.0.14 материализуются; в 8.0.14+ оптимизатор может merge-ить (derived merge).
*   Материализация подзапросов.
*   Некоторые `JOIN` с `ORDER BY`.

### Путь выполнения: память → диск

```
Запрос с GROUP BY
  ↓
Внутренняя временная таблица (TempTable, in-memory)
  ↓ размер > MIN(tmp_table_size, temptable_max_ram)
  ├─ temptable_use_mmap = OFF (дефолт):
  │   Конвертация в on-disk (InnoDB в MySQL 8.0+)
  │   ↓
  │   Запись в session temporary tablespace (ibtmp1, в datadir)
  │   или в tmpdir для mmap-файлов
  └─ temptable_use_mmap = ON (устаревшее):
      Запись в mmap-файл в tmpdir (не учитывается Created_tmp_disk_tables)
```

**Критично:** конвертация in-memory → on-disk — дорогая операция (двойное хранение, I/O). Цель — минимизировать `Created_tmp_disk_tables`.

**Важно для репликации:** в `STATEMENT`/`MIXED` формате временные таблицы реплицируются; в `ROW` — изменения временных таблиц не записываются в binlog. При `gtid_mode = ON` создание/удаление temporary table внутри транзакции вызывает ошибку 3748 на реплике.

**Мониторинг TempTable:** инструменты `memory/temptable/physical_ram` и
`memory/temptable/physical_disk` в Performance Schema показывают выделение RAM и mmap.
`physical_disk > 0` при mmap-переполнении — сигнал, что достигнут `temptable_max_ram`.

## Практические сценарии

### 1. Проверка текущего состояния

```sql
-- Лимиты
SHOW VARIABLES LIKE 'tmp_table_size';
SHOW VARIABLES LIKE 'max_heap_table_size';

-- TempTable-переменные (8.0+)
SHOW VARIABLES LIKE 'temptable%';
SHOW VARIABLES LIKE 'internal_tmp_mem_storage_engine';
SHOW VARIABLES LIKE 'big_tables';

-- Счётчики
SHOW GLOBAL STATUS LIKE 'Created_tmp%';
-- Created_tmp_tables       — всего создано
-- Created_tmp_disk_tables  — сброшено на диск
-- Created_tmp_files        — файлов на диске

-- Ratio on-disk (цель < 25%)
SELECT
  ROUND(
    100 *
    (SELECT VARIABLE_VALUE FROM performance_schema.global_status
     WHERE VARIABLE_NAME = 'Created_tmp_disk_tables') /
    (SELECT VARIABLE_VALUE FROM performance_schema.global_status
     WHERE VARIABLE_NAME = 'Created_tmp_tables'),
    2
  ) AS tmp_disk_ratio_percent;

-- TempTable выделение RAM/mmap (Physical Schema)
SELECT
  EVENT_NAME,
  SUM_NUMBER_OF_BYTES_ALLOC / 1024 / 1024 AS alloc_mb
FROM performance_schema.memory_summary_global_by_event_name
WHERE EVENT_NAME LIKE 'memory/temptable%'
ORDER BY alloc_mb DESC;
```

### 2. Настройка

```ini
[mysqld]
# Лимит in-memory внутренней таблицы (реальный = MIN из двух)
tmp_table_size = 64M
max_heap_table_size = 64M

# Глобальный лимит RAM для TempTable (дефолт: 3% ОЗУ, минимум 1 GB, максимум 4 GB)
# temptable_max_ram = 3G

# mmap-переполнение (устаревшее, дефолт OFF)
# temptable_use_mmap = OFF
# temptable_max_mmap = 0

# Каталог для временных файлов
tmpdir = /tmp
# Для InnoDB on-disk temp tables можно задать отдельный каталог:
# innodb_tmpdir = /ssd/tmp
# Каталог для session temporary tablespaces (дефолт: #innodb_temp в datadir)
# innodb_temp_tablespaces_dir = /ssd/innodb_temp
# Глобальный temporary tablespace (ibtmp1), включает rollback segments для user temp tables
# innodb_temp_data_file_path = ibtmp1:12M:autoextend:max:500M
```

**Важно:** `tmp_table_size` и `max_heap_table_size` — per-connection. При `max_connections = 1000` и
`tmp_table_size = 64M` теоретический максимум потребления = 64 GB. Не завышайте без расчёта.

**Версии:** в MySQL 8.0.16+ переменная `internal_tmp_disk_storage_engine` удалена — on-disk
внутренние временные таблицы всегда InnoDB. В MariaDB аналог —
`internal_tmp_disk_storage_engine = Aria` (дефолт с 10.5).

### 2.1. Принудительное использование диска (`big_tables`)

```sql
-- Сессионно: внутренние временные таблицы сразу на disk, без in-memory
SET SESSION big_tables = ON;

-- Проверить
SELECT @@SESSION.big_tables;
-- → 1
```

Полезно для отладки: если запрос падает с `The table '...' is full`, включите `big_tables`
и перезапустите — если ошибка исчезнет, проблема в in-memory лимите, а не в данных.

### 3. Явные временные таблицы

```sql
-- Создание
CREATE TEMPORARY TABLE tmp_orders (
  id INT PRIMARY KEY,
  total DECIMAL(10,2),
  INDEX idx_total (total)
) ENGINE = InnoDB;

-- Использование (видна только в этой сессии)
INSERT INTO tmp_orders SELECT id, total FROM orders WHERE created_at > NOW() - INTERVAL 1 DAY;

-- Приоритет над постоянной таблицей с тем же именем
SELECT * FROM tmp_orders;  -- временная, не постоянная

-- Удаление
DROP TEMPORARY TABLE tmp_orders;
```

**Особенности явных временных таблиц:**
*   Не видны другим сессиям.
*   Имеют приоритет над постоянными таблицами с тем же именем в сессии.
*   Автоматически удаляются при закрытии сессии.
*   `ROLLBACK` не удаляет временную таблицу (только откатывает DML в ней).
*   В `STATEMENT`-репликации реплицируются; в `ROW` — нет.

### 4. Диагностика запросов с временными таблицами

```sql
-- EXPLAIN: ищите "Using temporary"
EXPLAIN SELECT status, COUNT(*) FROM orders GROUP BY status;
-- → Extra: Using temporary

-- Какие запросы создают дисковые временные таблицы (Performance Schema)
SELECT DIGEST_TEXT, COUNT_STAR, SUM_CREATED_TMP_DISK_TABLES
FROM performance_schema.events_statements_summary_by_digest
WHERE SUM_CREATED_TMP_DISK_TABLES > 0
ORDER BY SUM_CREATED_TMP_DISK_TABLES DESC
LIMIT 10;
```

## Устранение неисправностей (Troubleshooting)

### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Высокий `Created_tmp_disk_tables` | `tmp_table_size` мал или запросы тяжёлые | Увеличить лимит; оптимизировать запрос (индекс на GROUP BY/ORDER BY) |
| `The table '...' is full` | Превышен `max_heap_table_size` | Увеличить `tmp_table_size`/`max_heap_table_size` |
| Ошибка 3748 (GTID) | CREATE/DROP TEMPORARY TABLE внутри транзакции | Выносить создание временной таблицы за транзакцию |
| Много `Created_tmp_files` | On-disk временные таблицы | Оптимизировать запросы; проверить `tmpdir` на диске |
| `Using temporary` в EXPLAIN | Нет индекса для GROUP BY/ORDER BY/DISTINCT | Добавить составной индекс |

### Почему `Using temporary` — не всегда плохо

`Using temporary` в EXPLAIN означает, что оптимизатор создал внутреннюю временную таблицу. Это нормально для `GROUP BY`/`DISTINCT`/`UNION`. Проблема — когда таблица сбрасывается на диск (`Created_tmp_disk_tables`). Цель: `Using temporary` в памяти, не на диске.

## Лучшие практики

1.  **Индекс на GROUP BY/ORDER BY** — лучший способ избежать временных таблиц.
2.  **`tmp_table_size` = `max_heap_table_size`** — задавайте одинаковые, иначе работает MIN.
3.  **Не завышайте per-connection лимиты** — считайте `max_connections × tmp_table_size`.
4.  **Мониторьте ratio** `Created_tmp_disk_tables / Created_tmp_tables` — цель < 25%.
5.  **`innodb_tmpdir`** — вынесите on-disk временные таблицы на быстрый диск.

## Дополнительная информация

### См. также

*   **[Оптимизация запросов](Operations/explain_and_optimization.md)** — `Using temporary`.
*   **[Индексы](indexing.md)** — индексы для GROUP BY/ORDER BY.
*   **[Конфигурация](configuration.md)** — `tmp_table_size`, `max_heap_table_size`.
*   **[Репликация: binlog formats](replication/binlog_formats.md)** — временные таблицы и ROW.
*   **[MariaDB: временные таблицы](../MariaDB/temporary_tables.md)** — аналог для MariaDB (Aria).

### Внешние ресурсы

*   [MySQL Temporary Tables](https://dev.mysql.com/doc/refman/8.4/en/internal-temporary-tables.html)
*   [CREATE TEMPORARY TABLE](https://dev.mysql.com/doc/refman/8.4/en/create-table.html)
