# Глубокое погружение в Storage Engines MySQL и Percona

**Актуально для:** MySQL 8.4 LTS / 9.x Innovation, Percona Server 8.0.x

## Определения

*   **Движок хранения (Storage Engine)** — модульная подсистема СУБД, отвечающая за физическое хранение данных, индексацию, блокировки и транзакционность. В MySQL архитектура Pluggable Storage Engine API позволяет подключать разные движки для отдельных таблиц.
*   **InnoDB** — основной транзакционный движок MySQL с ACID, MVCC и кластерным B-Tree индексом. Стандарт с версии 5.5; в MySQL 8.0+ системные таблицы тоже переведены на InnoDB.
*   **MyISAM** — исторический движок без транзакций и внешних ключей, с блокировкой на уровне таблицы. В MySQL 8.0+ присутствует только для временных таблиц и ограниченного набора задач.
*   **Memory (HEAP)** — движок, хранящий данные только в оперативной памяти. Использует HASH-индексы по умолчанию, не поддерживает `TEXT`/`BLOB`, данные теряются при перезапуске.
*   **Archive** — специализированный движок для логов и аудита. Данные сжимаются zlib, поддерживаются только `INSERT` и `SELECT`. Индекс — только PK на `AUTO_INCREMENT`.
*   **MyRocks** — движок на базе LSM-дерева (RocksDB) в Percona Server. Оптимизирован для интенсивной записи и высокого сжатия. В Percona Server 8.0 доступен как `RocksDB`.
*   **TokuDB** — движок на основе Fractal Tree индексов. В Percona Server 8.0.28+ и MariaDB 10.6+ поддержка прекращена (deprecated) в пользу MyRocks.
*   **LSM-дерево (Log-Structured Merge-tree)** — структура данных, оптимизированная для записи: данные буферизуются в MemTable, периодически сбрасываются на диск как иммутабельные SST-файлы и фоново уплотняются (compaction).
*   **Фрагментация (Bloat)** — накопление пустого пространства в страницах движка из-за частых `UPDATE`/`DELETE`. В B-Tree движках приводит к раздуванию индексов и файлов данных.
*   **Write Amplification** — коэффициент, показывающий, сколько записей на диск генерирует одна логическая операция записи. Критичен для SSD износа и производительности.

---

## Архитектура Pluggable Storage Engine API

MySQL разделена на два уровня: **SQL Layer** (обработка запросов, парсинг, оптимизация) и **Storage Engine Layer** (физическое хранение). Движок не видит запросы других движков; взаимодействие идет через стандартный API (`handler` interface).

**Этапы работы движка при выполнении запроса:**
1.  SQL Layer передает план выполнения через стандартный вызов.
2.  Движок определяет, какие страницы данных нужно прочитать (из Buffer Pool или с диска).
3.  Выполняет чтение/запись с учетом своих механизмов блокировок и транзакций.
4.  Возвращает строки или код ошибки.

**Важно для SRE:** Настройки `innodb_*`, `rocksdb_*`, `key_buffer_size` и другие относятся конкретно к движку. Если на сервере используются разные движки, параметры одного не покрывают потребности другого (например, MyISAM не использует InnoDB Buffer Pool).

---

## Движки Oracle MySQL

### InnoDB: Основной транзакционный движек

InnoDB — единственный движок, рекомендуемый для продакшн OLTP в MySQL 8.4+. Детальная архитектура (Buffer Pool, Redo/Undo Log, MVCC, Doublewrite Buffer) описана в **[Обзор MySQL](../overview.md)**. Здесь рассматриваются операционные аспекты, метрики и принятие решений.

**Ключевые SRE-характеристики:**
*   **Блокировки:** Row-level locking + Next-Key Locks на уровне индексов. Неявные блокировки захватываются автоматически при `INSERT`/`UPDATE`/`DELETE`. При отсутствии подходящего индекса может заблокировать весь диапазон. Детали в **[Блокировки и Deadlocks](../locking_and_deadlocks.md)**.
*   **Транзакционность:** Полная ACID. `innodb_flush_log_at_trx_commit` и `sync_binlog` управляют балансом между надежностью и производительностью.
*   **Crash Recovery:** При старте СУБД применяет Redo Log до точки последнего чекпоинта и откатывает незавершенные транзакции через Undo Log.
*   **Сжатие:** Поддерживается `ROW_FORMAT=COMPRESSED` (page-level, выравнивание до 4KB/8KB) и сжатие страниц (Page Compression) через атрибут `COMPRESSION`. Второй механизм не имеет отдельной системной переменной в MySQL — `innodb_page_compressed` существует только в MariaDB.
*   **Шифрование:** TDE (Transparent Data Encryption) шифрует табличные пространства. Детали в **[Безопасность MySQL](../security.md)**.

**Метрики мониторинга (InnoDB-специфичные):**
```sql
-- Размер Buffer Pool и заполненность
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_%';
-- Через Performance Schema
SELECT * FROM information_schema.innodb_metrics
WHERE name LIKE 'buffer_pool%' AND status = 'enabled';

-- Активные транзакции и блокировки
SELECT * FROM information_schema.innodb_trx;
SELECT * FROM information_schema.innodb_lock_waits;

-- Адаптивные хэш-индексы
SHOW ENGINE INNODB STATUS\G
-- Или через sys schema
SELECT * FROM sys.innodb_buffer_stats_by_table;
```

**Page Compression — как это работает в MySQL:**

```sql
-- Требуется innodb_file_per_table=ON и файловая система с поддержкой hole punching
CREATE TABLE shop.events (
  id BIGINT UNSIGNED PRIMARY KEY,
  payload JSON
) COMPRESSION='zlib';
-- → Query OK, 0 rows affected

-- ALTER меняет только атрибут пространства; существующие страницы
-- пережимаются только при пересборке таблицы
ALTER TABLE shop.events COMPRESSION='zlib';
OPTIMIZE TABLE shop.events;
```

Сжатие возможно, только если данные ужимаются до размера не больше «размер страницы InnoDB минус размер блока файловой системы»:

| Размер кластера файловой системы | Максимальный размер сжатой страницы |
| :--- | :--- |
| 512 байт | 8 KB |
| 1 KB | 16 KB |
| 2 KB | 32 KB |
| 4 KB | 64 KB |

Метаданные сжатия видны в `INFORMATION_SCHEMA.INNODB_TABLESPACES`.

**Диагностика внутренних структур:**

```sql
-- Давление на purge: растёт ли длина истории версий
SELECT trx_id, trx_started, trx_rows_locked, trx_rows_modified,
       trx_mysql_thread_id, LEFT(trx_query, 60) AS query
FROM information_schema.INNODB_TRX ORDER BY trx_started;
-- → trx_mysql_thread_id: NULL означает транзакцию, о которой сервер ничего не знает:
--   либо она в состоянии prepare, либо клиент потерял соединение
```

```sql
-- Undo tablespaces: сколько их и какого размера
SELECT NAME, ROW_FORMAT, SPACE_TYPE, FILE_SIZE, ALLOCATED_SIZE
FROM INFORMATION_SCHEMA.INNODB_TABLESPACES
WHERE ROW_FORMAT = 'Undo'
ORDER BY NAME;
-- → SPACE | NAME          | ROW_FORMAT | SPACE_TYPE | FILE_SIZE | ALLOCATED_SIZE
-- →     38 | innodb_undo_001 | Undo      | Undo       |   1048576 |     655360
-- →     39 | innodb_undo_002 | Undo      | Undo       |   1048576 |     655360

-- Точное число файлов undo на сервере
SHOW VARIABLES LIKE 'innodb_undo_tablespaces';
-- → innodb_undo_tablespaces = 2   (по умолчанию)

-- Потолок размера одного undo tablespace
SHOW VARIABLES LIKE 'innodb_max_undo_log_size';
-- → innodb_max_undo_log_size = 10485760   (10 MB, по умолчанию)
```

> **Практическая деталь:** начиная с MySQL 8.0.21 `innodb_max_undo_log_size` — это
> **максимум размера одного tablespace**, а не общий объём; общий объём задаётся числом
> `innodb_undo_tablespaces`. Если purge не успевает, история версий растёт и место на диске
> расходуется — один из сценариев внезапного `Disk full`.

```sql
-- Адаптивный хэш-индекс (AHI): включается автоматически, но может мешать
SHOW VARIABLES LIKE 'innodb_adaptive_hash_index';
-- → innodb_adaptive_hash_index = ON

-- Точки входа и конфликты AHI видны в SHOW ENGINE INNODB STATUS
SHOW ENGINE INNODB STATUS\G
-- → INSERT BUFFER AND ADAPTIVE HASH INDEX
-- →   hl_count: 0        page_old_bits: 0
-- →   searches: 0        inserts: 0
```

```bash
# Сопоставить внутренние счётчики с реальной нагрузкой на диск
vmstat 1 5      # bi/bo — фактический ввод-вывод в KB/s
iostat -x 1 3   # %util и await по устройствам
```

**Конфигурация (ключевые параметры):**
```ini
[mysqld]
innodb_buffer_pool_size = 75%RAM        # Для выделенного сервера БД
innodb_redo_log_capacity = 20G          # Управляет размером redo log начиная с 8.0.30
# innodb_log_file_size и innodb_log_files_in_group объявлены устаревшими в 8.0.30
# и не должны присутствовать в новой конфигурации
innodb_redo_log_buffer_size = 16M       # буфер записи redo
innodb_flush_method = O_DIRECT          # Обход OS cache
innodb_flush_log_at_trx_commit = 1      # Полная надежность (2 = периодически, 0 = отложено)
innodb_file_per_table = ON
innodb_io_capacity = 200                # IOPS для фоновых операций (SSD)
innodb_io_capacity_max = 400
innodb_adaptive_flushing = ON
innodb_change_buffer_max_size = 25      # % от Buffer Pool
innodb_lru_scan_depth = 1024            # Управление вымыванием из LRU
innodb_buffer_pool_instances = 4        # По одному на каждый инстанс buffer pool
innodb_undo_tablespaces = 2
innodb_max_undo_log_size = 10M
innodb_purge_threads = 4                # Число потоков purge
innodb_max_purge_lag = 1000000          # Задержка purge при значении > 0
```

> `innodb_monitor_enable = 'all'` включает все счётчики `INNODB_METRICS` и заметно снижает
> производительность. Применять его нужно точечно и временно, только для диагностики; в
> постоянной конфигурации опираться на Performance Schema —
> **[Performance Schema и sys schema](./performance-schema-and-sys.md)**.

### MyISAM: Наследие и системные нужды

MyISAM полностью удален из продакшн-рекомендаций для MySQL 8.0+. Используется только:
*   Системные временные таблицы MySQL (внутренние операции)
*   Легаси-приложения, которые не планируется переводить на InnoDB
*   `REPAIR TABLE` для восстановления поврежденных таблиц

**SRE-характеристики:**
*   **Блокировки:** Table-level locking. Любой `UPDATE`/`INSERT`/`DELETE` блокирует всю таблицу для чтений и других изменений. Непригоден для конкурентной OLTP.
*   **Кэширование:** Только индексы кэшируются в `key_buffer_size`. Данные кэшируются OS page cache — нагружает память ядра.
*   **Восстановление:** При сбое питания `.MYD`/`.MYI` файлы часто повреждаются. Требуется `REPAIR TABLE` или `myisamchk`.
*   **Полнотекстовый поиск:** InnoDB поддерживает FULLTEXT с MySQL 5.6, поэтому преимущество MyISAM исчезло.

**Операционные команды:**
```sql
-- Проверка и восстановление
REPAIR TABLE myisam_table QUICK;
CHECK TABLE myisam_table;

-- Внешний инструмент (offline)
myisamchk --recover --key_buffer_size=4G /var/lib/mysql/db/table.MYI
```

### Memory (HEAP)

Идеален для краткосрочных кешей, сессионных данных, промежуточных результатов.

**SRE-характеристики:**
*   **Индексы:** HASH по умолчанию (точное совпадение). BTREE доступен для диапазонов (`>`, `<`, `BETWEEN`).
*   **Лимиты:** `max_heap_table_size` и `tmp_table_size` ограничивают максимальный размер. При превышении — ошибка `The table '...' is full`.
*   **Потеря данных:** Содержимое теряется при перезапуске MySQL. Структура таблицы сохраняется в `.frm`.
*   **Типы данных:** Не поддерживает `TEXT`, `BLOB`, `MEDIUMBLOB` и т.д.

**Практическое применение:**
```sql
-- Создание кеша с BTREE для диапазонов
CREATE TABLE session_cache (
  session_id CHAR(64) PRIMARY KEY,
  user_id INT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_user (user_id) USING BTREE
) ENGINE=MEMORY;

-- Проверка размера
SHOW TABLE STATUS FROM db WHERE Name = 'session_cache';
```

### Archive

Специализированный движок для хранения логов, событий, аудита — данных, которые редко изменяются и seldom читаются целиком.

**SRE-характеристики:**
*   **Сжатие:** zlib на уровне строк. Типичное сжатие 3-10x для текстовых логов.
*   **Ограничения:** Нет индексов кроме PK на `AUTO_INCREMENT`. Нет `UPDATE`/`DELETE` (в MySQL 8.0+ `DELETE` возможен, но медленный).
*   **Сценарии:** Хранение событий безопасности, исторических метрик, логов приложений.

```sql
-- Создание архивной таблицы
CREATE TABLE audit_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_time DATETIME NOT NULL,
  user_host VARCHAR(255),
  event_type VARCHAR(50),
  event_data JSON,
  PRIMARY KEY (id)
) ENGINE=ARCHIVE;

-- Чтение (последовательное, медленное)
SELECT * FROM audit_log WHERE id BETWEEN 1000 AND 2000;
```

### NDB Cluster (MySQL Cluster)

Распределенный движок для кластерных конфигураций с высокой доступностью.

*   **Архитектура:** SQL Nodes → Data Nodes (NDB). Данные реплицируются синхронно между Data Nodes.
*   **Использование:** Телеком, real-time приложения, где требуется sub-second failover.
*   **Ограничения:** Не поддерживает все типы индексов и DDL операции. Сложность операций (SRE) выше, чем у InnoDB + репликации.

---

## Движки Percona Server (SRE Choice)

### MyRocks (RocksDB)

Движок, интегрирующий RocksDB в MySQL. В конфигурации MySQL движок регистрируется как `RocksDB`, но в документации и обсуждениях используется название MyRocks.

**Архитектура LSM:**
1.  **MemTable:** Новые записи пишутся в память (Write-Ahead Log + MemTable).
2.  **Immutable MemTable:** При заполнении замораживается в SSTable на диске.
3.  **SSTable:** Иммутабельные отсортированные файлы. Организованы в уровни (L0-L6). В нижних уровнях данные сжимаются сильнее.
4.  **Compaction:** Фоновый процесс объединяет SST-файлы, удаляет помеченные на удаление строки и старые версии (GC).

**SRE-преимущества:**
*   **Сжатие:** В 2-3 раза плотнее InnoDB за счет отсутствия фрагментации B-Tree страниц. Для архивов и логов дает экономию в разы.
*   **Write Amplification:** На 50-70% ниже, чем у InnoDB. Продлевает жизнь SSD/NVMe.
*   **Кеширование:** Использует Block Cache (аналог Buffer Pool) и Row Cache для часто читаемых данных.

**SRE-внимание:**
*   **Read Amplification:** Чтение диапазона может потребовать проверки нескольких уровней SST. Для read-heavy workloads может уступать InnoDB.
*   **Compaction Stall:** При высокой нагрузке фоновый compaction не успевает, возникает `Write Stall` (запросы на запись блокируются).
*   **Отсутствие Foreign Keys:** MyRocks не поддерживает внешние ключи. Это не баг, а особенность архитектуры LSM.

**Конфигурация (Percona Server 8.0):**
```ini
[mysqld]
rocksdb_block_cache_size = 4G           # Аналог Buffer Pool
rocksdb_max_background_compactions = 4  # Потоки compaction
rocksdb_max_background_flushes = 2      # Потоки сброса MemTable
rocksdb_compaction_readahead_size = 2M  # Последовательное чтение при compaction
rocksdb_use_direct_reads = ON           # O_DIRECT, минуя OS cache
rocksdb_wal_dir = /var/lib/mysql/rocksdb_wal  # Отдельный диск для WAL (опционально)
rocksdb_enable_native_partition = ON    # Для секционированных таблиц
rocksdb_stats_dump_period_sec = 3600    # Логирование статистики
```

**Мониторинг MyRocks:**
```sql
-- Статистика через performance_schema
SELECT * FROM performance_schema.rocksdb_global_info;
SELECT * FROM performance_schema.rocksdb_cf_stats;

-- Через SHOW ENGINE
SHOW ENGINE ROCKSDB STATUS\G

-- Ключевые метрики
SHOW GLOBAL STATUS LIKE 'rocksdb_%';
```

### TokuDB (Deprecated)

*   **Статус:** Поддержка прекращена в Percona Server 8.0.28+ и MariaDB 10.6+.
*   **Почему deprecated:** MyRocks показал лучшую производительность на современных многоядерных CPU, лучше интегрирован в экосистему и активнее развивается.
*   **Миграция:** Для существующих инсталляций требуется дамп (`mysqldump`/`mydumper`) и загрузка в MyRocks или InnoDB. Секционированные таблицы TokuDB требуют `UPGRADE PARTITIONING` при переходе на MySQL 8.0+.

---

## Практические сценарии

### Выбор движка под задачу

| Задача | Рекомендуемый движок | Почему? |
| :--- | :--- | :--- |
| **Стандартная OLTP** | **InnoDB** | ACID, MVCC, row-level locking, кластерный индекс. Единственный выбор для новых продакшен-приложений. |
| **Логирование / Архив (>1ТБ/день)** | **MyRocks** | Высокое сжатие, низкий Write Amp, отсутствие фрагментации. |
| **Краткосрочный кеш / Session** | **Memory** | Данные в RAM, HASH индексы, максимальный RPS. |
| **Аналитика (Read-only / Append)** | **Archive** | Сжатие zlib, экономия места. Для аналитики рассмотрите ColumnStore (MariaDB) или внешние решения. |
| **Высоконагруженный лог событий** | **MyRocks** или **Archive** | MyRocks для >1ТБ/день с возможностью индексации. Archive для простых append-only логов. |

### Конвертация таблиц (SRE Best Practice)

```sql
-- 1. Проверка текущего использования диска по движкам
SELECT engine, COUNT(*) as tables,
  SUM(data_length+index_length)/1024/1024/1024 AS total_gb
FROM information_schema.tables
WHERE table_schema NOT IN ('information_schema', 'performance_schema', 'sys', 'mysql')
GROUP BY engine;

-- 2. Проверка совместимости перед конвертацией в MyRocks
-- MyRocks не поддерживает: FOREIGN KEY, SPATIAL indexes, FULLTEXT (до Percona 8.0.34+), CHECK constraints (ограниченно)
SELECT TABLE_NAME, CONSTRAINT_NAME, CONSTRAINT_TYPE
FROM information_schema.REFERENTIAL_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA = 'mydb';

-- 3. Миграция на MyRocks (Percona Server)
ALTER TABLE heavy_logs ENGINE=RocksDB;

-- 4. Миграция на InnoDB (любой MySQL 8.0+)
ALTER TABLE myisam_table ENGINE=InnoDB;
```

### Изменение движка по умолчанию

```sql
-- Проверка текущего значения
SHOW VARIABLES LIKE 'default_storage_engine';

-- Глобальное изменение (вступит для новых таблиц)
SET GLOBAL default_storage_engine = 'InnoDB';

-- В конфигурации
[mysqld]
default_storage_engine = InnoDB
```

---

## Валидация и мониторинг

### Проверка поддерживаемых движков

```sql
-- Доступные движки
SHOW ENGINES;

-- Проверка движка конкретной таблицы
SELECT TABLE_NAME, ENGINE
FROM information_schema.tables
WHERE TABLE_SCHEMA = 'mydb';

-- Размеры таблиц по движкам
SELECT engine, COUNT(*) as tables,
  ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS total_mb
FROM information_schema.tables
GROUP BY engine;
```

### Мониторинг фрагментации (InnoDB)

```sql
-- Оценка фрагментации таблиц InnoDB
SELECT
  table_name,
  ROUND(data_free / 1024 / 1024, 2) AS data_free_mb,
  ROUND((data_length + index_length) / 1024 / 1024, 2) AS total_mb,
  ROUND(data_free / (data_length + index_length) * 100, 2) AS fragmentation_pct
FROM information_schema.tables
WHERE engine = 'InnoDB'
  AND table_schema NOT IN ('information_schema', 'performance_schema', 'sys', 'mysql')
ORDER BY fragmentation_pct DESC;

-- Оптимизация (осторожно в продакшене!)
ALTER TABLE fragmented_table ENGINE=InnoDB;
-- Или для Online DDL (MySQL 8.0+):
ALTER TABLE fragmented_table FORCE;
```

### Мониторинг MyRocks

```sql
-- Статистика compaction и stalls
SHOW ENGINE ROCKSDB STATUS\G

-- Ключевые счетчики
SHOW GLOBAL STATUS LIKE 'rocksdb_%';

-- Размеры SST-файлов по уровням
SELECT * FROM performance_schema.rocksdb_cf_stats;
```

---

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Table '...' is marked as crashed` | Сбой MyISAM таблицы при падении питания. | `REPAIR TABLE table_name;` или `myisamchk --recover`. Рассмотрите миграцию на InnoDB. |
| `The table '...' is full` | Лимит `max_heap_table_size` для Memory engine превышен. | Увеличьте лимит в `my.cnf` или очистите таблицу. Для временных таблиц проверьте `tmp_table_size` / `max_heap_table_size`. |
| `Write Stall` в MyRocks | Слишком медленный compaction (disky bottleneck или `max_background_compactions`=0). | Проверьте `rocksdb_max_background_compactions`, скорость диска, уменьшите `rocksdb_block_cache_size` если память переполнена. |
| `Out of memory` при ALTER ENGINE=InnoDB | Недостаточно памяти для создания нового индекса или буферов сортировки. | Увеличьте `innodb_buffer_pool_size` (временно), увеличьте `sort_buffer_size`, используйте `pt-online-schema-change` для больших таблиц. |
| Высокий `data_free` в InnoDB | Фрагментация B-Tree страниц после массовых `DELETE`/`UPDATE`. | `ALTER TABLE ... ENGINE=InnoDB` (rebuild) или `OPTIMIZE TABLE`. В MySQL 8.0.31+ есть `innodb_fill_factor` для предотвращения. |
| Низкое сжатие в MyRocks | Неправильный алгоритм сжатия или данные уже сжаты на уровне приложения. | Проверьте `rocksdb_compression_type` (lz4, zstd, zlib). zstd дает лучшее сжатие на современных CPU. |
| `Cannot find file: '*.frm'` | Поврежденный файл таблицы или неверный путь в `db.opt`. | Проверьте `lower_case_table_names`, права доступа к файлам, восстановите из бэкапа. |

---

## Лучшие практики

1.  **InnoDB везде, где возможно:** Для новых таблиц используйте `ENGINE=InnoDB` явно или через `default_storage_engine`. MyISAM/Memory/Archive — только для узкоспециализированных задач.
2.  **Buffer Pool под размер RAM:** Для выделенного сервера БД `innodb_buffer_pool_size = 50-75%` от оперативной памяти. Оставьте запас на OS и per-thread buffers (`innodb_sort_buffer_size`, `read_buffer_size`).
3.  **O_DIRECT для InnoDB:** `innodb_flush_method = O_DIRECT` избегает двойного кэширования (OS cache + InnoDB Buffer Pool). На macOS доступен `O_DIRECT` с ограничениями; на Linux — стандартно.
4.  **Мониторинг фрагментации:** Добавьте в `cron` или monitoring проверку `data_free` для InnoDB и compaction stats для MyRocks.
5.  **Не используйте Memory для критичных данных:** Данные теряются при перезапуске. Для кешей рассмотрите Redis/Memcached вне БД.
6.  **MyRocks требует отдельного тюнинга:** Не используйте параметры InnoDB (`innodb_*`) для диагностики MyRocks. Используйте `SHOW ENGINE ROCKSDB STATUS` и `performance_schema.rocksdb_*`.
7.  **Документируйте нестандартные движки:** Если в продакшене используется MyRocks или Archive, зафиксируйте это в runbook. При восстановлении из бэкапа проверьте, что движок доступен на целевой версии.

---

## Граничные случаи и ограничения

### Известные ограничения

1.  **NULL в индексах InnoDB B-Tree:** `NULL` значения индексируются, но `IS NOT NULL` может не использовать индекс в некоторых версиях. `IS NULL` работает корректно.
2.  **Миграция с MyISAM на InnoDB:** В MySQL 8.0+ партиционированные MyISAM таблицы несовместимы. Требуется удалить партиционирование или конвертировать в InnoDB до обновления. См. [MySQL 8.4 Reference](https://dev.mysql.com/doc/refman/8.4/en/partitioning-limitations.html).
3.  **TokuDB и партиционирование в MySQL 8.0:** MySQL 8.0 поддерживает партиционирование только для InnoDB и NDB. При upgrade с Percona Server 5.7/8.0 с TokuDB требуется `ALTER TABLE ... UPGRADE PARTITIONING` или пересоздание таблиц.
4.  **MyRocks и Foreign Keys:** На уровне движка не поддерживаются. На уровне SQL parser в Percona проверкаFK отключена при `ENGINE=RocksDB`. При миграции с InnoDB удалите FK перед `ALTER TABLE`.
5.  **Memory engine и BLOB/TEXT:** Типы `BLOB`, `TEXT`, `GEOMETRY` не поддерживаются. Используйте `VARCHAR(65535)` или перейдите на InnoDB.
6.  **Archive engine и UPDATE:** В MySQL до 8.0.19 `UPDATE` не поддерживался. В 8.0.19+ поддерживается, но работает медленно (перезапись строки).
7.  **InnoDB и большие BLOBs:** Данные >10KB могут вытеснять записи из буфера, что снижает производительность. Для больших объектов рассмотрите отдельное хранилище или `FILE`_per_table.
8.  **Секционирование и движки:** Только InnoDB, NDB и MyRocks (с `rocksdb_enable_native_partition=ON`) поддерживают секционирование в MySQL 8.0+.

---

## Дополнительная информация

### См. также

*   **[Обзор MySQL](../overview.md)** — архитектура InnoDB, Buffer Pool, Redo/Undo Log.
*   **[Блокировки и Deadlocks](../locking_and_deadlocks.md)** — row-level locking, Next-Key Locks, MDL.
*   **[Мониторинг MySQL](../monitoring.md)** — Performance Schema, InnoDB Metrics, sys schema.
*   **[Механизмы оптимизатора MySQL](../optimizer_mechanisms.md)** — ICP, MRR, BKA (взаимодействие движка и оптимизатора).
*   **[Безопасность MySQL](../security.md)** — TDE, шифрование табличных пространств InnoDB.
*   **[Индексы в MySQL](../indexing.md)** — B-Tree, Full-text, функциональные индексы.
*   **[Движки хранения в MariaDB](../../MariaDB/storage_engines.md)** — Aria, ColumnStore, Spider (SSoT для MariaDB).
*   **[Управление памятью в MariaDB](../../MariaDB/memory_management.md)** — расчет Key Buffer для MyISAM/Aria.

### Полезные ссылки

*   [MySQL 8.4 Reference: Storage Engines](https://dev.mysql.com/doc/refman/8.4/en/storage-engines.html)
*   [MySQL 8.4 Reference: InnoDB](https://dev.mysql.com/doc/refman/8.4/en/innodb-storage-engine.html)
*   [MySQL 8.4 Reference: Converting MyISAM to InnoDB](https://dev.mysql.com/doc/refman/8.4/en/converting-tables-to-innodb.html)
*   [Percona Server 8.0: MyRocks](https://docs.percona.com/percona-server/8.0/rocksdb/rocksdb_overview.html)
*   [Percona Server 8.0: Upgrade from TokuDB/MyRocks](https://docs.percona.com/percona-server/8.0/upgrade-tokudb-myrocks.html)
*   [MariaDB Knowledge Base: Storage Engines](https://mariadb.com/kb/en/storage-engines/)
