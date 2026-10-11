# Управление памятью в MariaDB: Диагностика и оптимизация

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **Global Buffers (Глобальные буферы)** — области памяти, выделяемые один раз при старте сервера и разделяемые между всеми потоками. Ключевые параметры: `innodb_buffer_pool_size`, `innodb_log_buffer_size`, `key_buffer_size`, `aria_pagecache_size`, `query_cache_size` (выключен по умолчанию, но поддерживается во всех версиях MariaDB — в отличие от MySQL 8.0, где он удалён). Глобальные буферы не освобождаются на протяжении всего времени работы процесса и не зависят от количества активных соединений.
*   **Per-Thread Memory (Память на поток)** — память, выделяемая для каждого соединения. Основные параметры: `sort_buffer_size`, `join_buffer_size`, `read_buffer_size`, `read_rnd_buffer_size`, `thread_stack`, `net_buffer_length`, `binlog_cache_size`, `tmp_table_size`, `max_heap_table_size`. Общий объем per-thread потребления = сумма буферов на одно соединение, умноженная на количество активных соединений. Важно: `sort_buffer_size` и `join_buffer_size` выделяются по требованию на запрос, но не освобождаются из памяти потока после завершения запроса — переиспользуются.
*   **Memory Leak (Утечка памяти)** — ситуация, при которой процесс MariaDB потребляет все больше оперативной памяти (RSS), не возвращая её ОС, даже при низкой нагрузке. В MariaDB утечки часто маскируются под фрагментацию аллокатора или рост пула соединений.
*   **RSS (Resident Set Size)** — реальный объем физической памяти, занимаемый процессом. Отображается в `top`/`htop` как `RES`. Отличается от `VSZ` (Virtual Size), который включает виртуальную память, выделенную, но не обязательно используемую.
*   **Buffer Pool LRU (Least Recently Used)** — алгоритм управления страницами в InnoDB Buffer Pool. Pages делятся на young sublist (горячие данные, 5/8 пула) и old sublist (холодные данные, 3/8 пула). При чтении новая страница попадает в середину old sublist, что защищает горячие данные от однократных сканирований (table scans).
*   **Adaptive Hash Index (AHI)** — механизм InnoDB, автоматически строящий хеш-индекс в памяти для часто запрашиваемых страниц. Ускоряет point lookups, но потребляет дополнительную память (до 1/64 от Buffer Pool). Отключается параметром `innodb_adaptive_hash_index=OFF` при высокой нагрузке на блокировки.
*   **tmp_table_size / max_heap_table_size** — лимит размера внутренних временных таблиц в памяти. Если запрос превышает этот порог, временная таблица сбрасывается на диск (Aria в MariaDB по умолчанию). Реальный лимит = `MIN(tmp_table_size, max_heap_table_size)`.
*   **Thread Cache** — кэш неактивных потоков, позволяющий переиспользовать их при новых подключениях без затрат на создание OS-потока. Настраивается параметром `thread_cache_size`. Эффективность кэша оценивается через `Threads_created / Connections` (цель < 1%).
*   **Table Cache** — кэш дескрипторов открытых таблиц. Настраивается через `table_open_cache` и `table_definition_cache`. Каждый дескриптор потребляет память в kernel space. При нехватке — рост `Opened_tables` и снижение производительности из-за частого `open`/`close`.
*   **Performance Schema Memory Instrumentation** — подсистема MariaDB для отслеживания всех аллокаций памяти на уровне индивидуальных функций. Позволяет точно идентифицировать утечки памяти, измеряя потребление по компонентам (InnoDB, SQL-parser, MyRocks и т.д.).
*   **Jemalloc** — аллокатор памяти, используемый по умолчанию в большинстве сборок MariaDB (начиная с 5.5). Эффективнее стандартного `glibc malloc`, борется с фрагментацией при массовых аллокациях/деаллокациях разного размера. Мониторинг: `MALLOC_CONF="stats_print:true"`.
*   **Huge Pages** — механизм ОС, позволяющий использовать страницы памяти размером 2MB или 1GB вместо стандартных 4KB. InnoDB Buffer Pool может использовать явно настроенные Huge Pages для снижения TLB misses. Transparent Huge Pages (THP) может вызывать latency spikes при дефрагментации — рекомендуется `transparent_hugepage=never` для MariaDB.
*   **Memory Lock (mlockall)** — механизм ОС, предотвращающий свопинг страниц процесса в swap. В MariaDB включается параметром `memlock = 1` в `my.cnf`. Критичен для production-серверов с большими Buffer Pool.
*   **NUMA (Non-Uniform Memory Access)** — архитектура многосокетных серверов, при которой доступ к памяти зависит от близости к CPU. Для MariaDB рекомендуется `numactl --interleave=all` для равномерного распределения памяти между NUMA-узлами, иначе Buffer Pool может быть ограничен памятью одного сокета.
*   **query_prealloc_size / query_alloc_block_size** — параметры управления предварительным выделением памяти при парсинге и выполнении запросов. Правильная настройка снижает фрагментацию памяти. Рекомендации: `query_prealloc_size` обычно не более 50KB, `query_alloc_block_size` — 1KB, `query_cache_type = DEMAND`.

## Базовые концепции

### Иерархия потребления памяти

Общее потребление MariaDB = `Global Buffers` + (`max_connections` * `Per-Thread Memory`).

```
Total RAM
├── OS & System Services (10-15%)
├── Global Buffers
│   ├── innodb_buffer_pool_size     (основной потребитель, 50-75% от доступной RAM)
│   ├── innodb_log_buffer_size      (буфер WAL-логов)
│   ├── key_buffer_size             (MyISAM/Aria индексы)
│   ├── aria_pagecache_size         (кеш страниц Aria)
│   └── query_cache_size            (выключен по умолчанию; query_cache_type=OFF, query_cache_size=0)
├── Per-Thread Buffers × max_connections
│   ├── sort_buffer_size            (сортировка)
│   ├── join_buffer_size            (неупорядоченные JOIN)
│   ├── read_buffer_size            (последовательное чтение)
│   ├── read_rnd_buffer_size        (произвольное чтение)
│   ├── thread_stack                (стек потока)
│   ├── net_buffer_length           (сетевой буфер)
│   ├── binlog_cache_size           (кеш бинарного лога)
│   └── tmp_table_size / max_heap_table_size (временные таблицы)
└── Shared Memory (Performance Schema, table cache, etc.)
```

### InnoDB Buffer Pool: внутренняя архитектура

Buffer Pool — основной потребитель памяти в большинстве конфигураций InnoDB. Он хранит копии страниц данных и индексов, уменьшая необходимость обращения к диску.

**Структура LRU-списка:**
- **Young sublist (горячие страницы):** 5/8 от общего размера. Содержит страницы, к которым недавно обращались.
- **Old sublist (холодные страницы):** 3/8 от общего размера. Новые страницы попадают сюда. Это защищает горячие данные от однократных full table scans, которые вытесняют нужные страницы.
- **midpoint:** Точка, куда попадает страница при первом чтении (между old и young sublist).
- **InnoDB Read-Ahead:** Предиктивное чтение соседних страниц при последовательном доступе. Регулируется параметром `innodb_read_ahead_threshold`. При последовательном чтении > N страниц InnoDB предзагружает следующие.

**Cleanup mechanics:**
- Фоновые потоки (page cleaner) сбрасывают грязные страницы (dirty pages) на диск.
- При нехватке страниц для выделения — InnoDB сбрасывает `flush_LRU_list`, вытесняя самые холодные страницы.
- `innodb_old_blocks_time=1000` (ms) — задержка перед перемещением страницы из old в young sublist, предотвращающая «отравление» горячих данных.

**Buffer Pool resizing (MariaDB 10.11.12 / 11.4.6 / 11.8.2 / 12.3 LTS):**
- `innodb_buffer_pool_size` теперь можно изменять с шагом 1MB (раньше — только chunk size).
- `innodb_buffer_pool_size_max` — максимальный размер, задаваемый при старте (по умолчанию 8 TiB). Если не указан — равен начальному `innodb_buffer_pool_size`, что фактически запрещает увеличение.
- `innodb_buffer_pool_size_auto_min` — минимальный размер при автоматическом сокращении под давлением памяти (только Linux). По умолчанию равен `innodb_buffer_pool_size_max`, то есть автоматическое сокращение отключено.
- `Innodb_buffer_pool_resize_status` удален. `SET GLOBAL innodb_buffer_pool_size` теперь блокирует выполнение до завершения resize.

**Ключевые метрики эффективности:**

| Метрика | Формула | Целевое значение |
| :--- | :--- | :--- |
| **Buffer Pool Hit Rate** | `1 - (Innodb_buffer_pool_reads / Innodb_buffer_pool_read_requests)` | > 99% |
| **Dirty Pages Ratio** | `Innodb_buffer_pool_pages_dirty / Innodb_buffer_pool_pages_total` | < 75% |
| **Read-Ahead Efficiency** | `Innodb_buffer_pool_read_ahead / Innodb_buffer_pool_read_ahead_evicted` | > 0 (отрицательный = useless read-ahead) |
| **LRU List Length** | `Innodb_buffer_pool_pages_total` | Стабильный, без частых скачков |

### Per-Thread буферы: назначение и типичные ошибки

| Буфер | Назначение | Когда выделяется | Типичная ошибка |
| :--- | :--- | :--- | :--- |
| `sort_buffer_size` | Сортировка результата (ORDER BY, GROUP BY без индекса) | Каждый запрос с сортировкой | Слишком большой (>1MB) приводит к фрагментации |
| `join_buffer_size` | Буфер для неупорядоченных join (BNL, hash join) | JOIN без индекса на присоединяемой таблице | Наивно увеличивают при медленных JOIN |
| `read_buffer_size` | Последовательное чтение по PRIMARY KEY или индексу | Sequential full table/index scan | Редко меняется, обычно 256KB достаточно |
| `read_rnd_buffer_size` | Буфер для чтения после сортировки | ORDER BY + LIMIT с индексом | Не увеличивать >1MB без нужды |
| `thread_stack` | Стек для выполнения SQL-кода | Каждое соединение | Стандартное значение 256KB оптимально |
| `net_buffer_length` | Сетевой буфер для отправки/получения результатов | Каждое соединение | 16KB по умолчанию, редко меняется |
| `binlog_cache_size` | Кеш бинарного лога на соединение | Каждая транзакция | По умолчанию 32KB, достаточно для большинства случаев |

**Важно:** Все per-thread буферы выделяются по требованию (на запрос) и освобождаются при завершении запроса. Однако `sort_buffer_size` и `join_buffer_size` не освобождаются из памяти потока после запроса — переиспользуются. Это значит, что при большом количестве соединений каждый поток удерживает свой максимальный буфер.

### Thread Cache и Table Cache

**Thread Cache (`thread_cache_size`):**
- Хранит завершенные потоки для переиспользования.
- При `thread_cache_size = 0` каждый новый коннект создает OS-поток (дорого).
- Мониторинг: `SHOW STATUS LIKE 'Threads_%'`. Если `Threads_created` растет быстрее `Connections` — увеличьте кэш.
- Рекомендация: `thread_cache_size = max(16, max_connections / 100)`.
- При использовании Thread Pool (`thread_handling = pool-of-threads`) кэш потоков не используется; вместо этого настраивайте `thread_pool_size` и `thread_pool_max_threads`.

**Table Cache (`table_open_cache`, `table_definition_cache`):**
- `table_open_cache`: количество открытых таблиц на процесс. Каждая запись потребляет ~2KB kernel memory.
- `table_definition_cache`: кэш определений (метаданных) таблиц. Не зависит от дескрипторов.
- При нехватке: рост `Opened_tables` (>1/сек = проблема), lock contention на `open_lock`.
- Рекомендация: `table_open_cache` ≈ `max_connections * среднее_количество_таблиц_на_запрос`.

### Performance Schema: инструментарий отслеживания памяти

Performance Schema отслеживает аллокации по компонентам, что позволяет точно идентифицировать утечки:

```sql
-- Включить инструментарий памяти (обычно включен по умолчанию)
UPDATE performance_schema.setup_instruments
SET ENABLED = 'YES', TIMED = 'YES'
WHERE NAME LIKE 'memory%';

-- Общее потребление по компонентам
SELECT event_name, current_alloc, high_alloc, current_count
FROM sys.memory_global_by_current_bytes
WHERE current_count > 0
ORDER BY current_alloc DESC
LIMIT 20;
```

**Ключевые категории:**
- `memory/innodb/buf_buf_pool` — потребление Buffer Pool (должно быть ~ `innodb_buffer_pool_size`).
- `memory/sql/*` — потребление SQL-слоя (парсер, временные структуры).
- `memory/performance_schema/*` — overhead самого Performance Schema (~5-10% от общего).
- `memory/aria/*` — потребление Aria (системные таблицы, временные).

### Операционная система и память

MariaDB работает в контексте ОС, и OS-level настройки критически влияют на стабильность.

**Transparent Huge Pages (THP):**
```bash
# Проверка текущего состояния
cat /sys/kernel/mm/transparent_hugepage/enabled
# → рекомендуется: never

# Отключение для MariaDB (рекомендуется)
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/defrag
```
THP может вызывать latency spikes при дефрагментации (compaction), что критично для латентных OLTP-сценариев.

**Явные Huge Pages (explicit huge pages):**
```bash
# Проверка количества настроенных huge pages
cat /proc/meminfo | grep HugePages

# Настройка в /etc/sysctl.conf
vm.nr_hugepages = 1024

# Проверка после применения
sysctl -p
```
Для InnoDB Buffer Pool explicit huge pages предпочтительнее THP, так как обеспечивают предсказуемость. Размер страницы 2MB или 1GB (требует поддержки в CPU).

**vm.swappiness:**
- Значение по умолчанию `60` слишком агрессивно для БД.
- Рекомендация: `vm.swappiness = 1` — ОС будет использовать swap только в крайнем случае.
- Значение `0` (старые ядра) — никогда не свопает; `1` (современные ядра) — минимальный swap.

**vm.overcommit_memory:**
- `0` (по умолчанию): heuristical overcommit — ОС может убить процесс при нехватке памяти.
- `1`: всегда разрешать — опасно для БД, может привести к OOM без предупреждений.
- `2`: жесткий лимит = `swap + RAM * overcommit_ratio` (по умолчанию 50%). Рекомендуется для production.

**memlock / mlockall:**
```bash
# Проверка текущего лимита блокировки памяти
ulimit -l
# → рекомендуется: unlimited или >= размер Buffer Pool

# В /etc/security/limits.conf
mysql soft memlock unlimited
mysql hard memlock unlimited
```
Включение `memlock = 1` в `my.cnf` предотвращает свопинг страниц Buffer Pool. Критично для production с большим Buffer Pool.

**NUMA:**
```bash
# Проверка топологии NUMA
numactl --hardware

# Рекомендуемый запуск MariaDB с interleave
numactl --interleave=all mysqld_safe
```
На многосокетных серверах без `numactl --interleave=all` Buffer Pool может быть ограничен памятью одного сокета, что приводит к неэффективному использованию RAM.

**ulimit и файловые дескрипторы:**
```bash
# Проверка текущих лимитов
ulimit -n          # открытые файлы (цель > 65535 для MariaDB)
ulimit -s          # размер стека потока (обычно 8MB, достаточно)
ulimit -l          # memlock (цель: unlimited)

# Установка в /etc/security/limits.conf
mysql soft nofile 65535
mysql hard nofile 65535
mysql soft memlock unlimited
mysql hard memlock unlimited
```

## Предварительные требования

Перед настройкой параметров памяти убедитесь, что среда соответствует требованиям.

### Требования к оборудованию и ОС

- **ОЗУ:** Минимум 2GB для тестовых сред. Production: минимум 8GB, рекомендуется 16GB+.
- **Диск:** Поддерживаются любые файловые системы, совместимые с `O_DIRECT` (ext4, XFS, ZFS).
- **Ядра Linux:** 5.4+ для стабильной работы Thread Pool и Transparent Huge Pages.
- **Права доступа:** Пользователь `mysql` должен иметь права на запись в `datadir`, каталог логов и каталог сокета.

### Подготовка ОС

```bash
# Проверка прозрачных огромных страниц (THP)
cat /sys/kernel/mm/transparent_hugepage/enabled
# → рекомендуется: never

# Проверка vm.swappiness
sysctl vm.swappiness
# → рекомендуется: 1

# Проверка vm.overcommit_memory
sysctl vm.overcommit_memory
# → рекомендуется: 2

# Проверка лимитов файловых дескрипторов
ulimit -n
# → должно быть >= 65535 для production

# Проверка memlock
ulimit -l
# → рекомендуется: unlimited
```

**Валидация:**

```bash
# Проверка vm.swappiness
sysctl vm.swappiness
# → vm.swappiness = 1

# Проверка vm.overcommit_memory
sysctl vm.overcommit_memory
# → vm.overcommit_memory = 2

# Проверка открытых файловых дескрипторов для mysql
cat /proc/$(pidof mysqld)/limits | grep "open files"
# → Max open files 65535 65535 files

# Проверка memlock
cat /proc/$(pidof mysqld)/limits | grep "max locked memory"
# → max locked memory unlimited
```

## Практические сценарии

### 1. Расчет буферов для смешанных нагрузок

Если в системе одновременно используются таблицы InnoDB (OLTP) и MyISAM/Aria (архив или системные), необходимо балансировать между `innodb_buffer_pool_size` и `key_buffer_size`.

**Формула расчета (SRE Best Practice):**
1.  Выделите 10-15% RAM для ОС и системных нужд.
2.  Вычислите объем на поток: `PerThread = (sort + join + read + read_rnd + thread_stack + net_buffer + binlog_cache) * max_connections`.
3.  Остаток распределите между буферами в пропорции к объему данных:
    *   **Преимущественно InnoDB:** `innodb_buffer_pool_size` = 60-75% от доступной RAM.
    *   **Смешанная нагрузка:** Используйте `SHOW TABLE STATUS` для оценки объема индексов каждого типа и распределите пропорционально.

**Пример (сервер 64GB RAM, 500 соединений):**
- ОС: 8GB
- Per-Thread (2MB на поток): 1GB
- Остаток: 55GB.
- Настройка: `innodb_buffer_pool_size = 48G`, `key_buffer_size = 4G`, `aria_pagecache_size = 2G`.

**Валидация после настройки:**
```sql
-- Проверка фактического потребления
SELECT
  ROUND(@@innodb_buffer_pool_size / 1024 / 1024 / 1024, 2) AS buffer_pool_GB,
  ROUND(@@key_buffer_size / 1024 / 1024 / 1024, 2) AS key_buffer_GB,
  ROUND(@@aria_pagecache_size / 1024 / 1024 / 1024, 2) AS aria_pagecache_GB,
  (SELECT VARIABLE_VALUE FROM performance_schema.global_status
   WHERE VARIABLE_NAME = 'Innodb_buffer_pool_pages_total') * @@innodb_page_size / 1024 / 1024 / 1024 AS actual_pool_GB;
```

### 2. Мониторинг эффективности Buffer Pool

Проверка hit ratio и выявление проблем:

```sql
-- 1. Текущий Hit Rate (цель > 99%)
SELECT
  ROUND(
    (1 - (
      (SELECT VARIABLE_VALUE FROM performance_schema.global_status
       WHERE VARIABLE_NAME = 'Innodb_buffer_pool_reads') /
      (SELECT VARIABLE_VALUE FROM performance_schema.global_status
       WHERE VARIABLE_NAME = 'Innodb_buffer_pool_read_requests')
    )) * 100, 2
  ) AS hit_ratio_percent;

-- 2. Состояние dirty pages
SELECT
  ROUND(
    (SELECT VARIABLE_VALUE FROM performance_schema.global_status
     WHERE VARIABLE_NAME = 'Innodb_buffer_pool_pages_dirty') /
    (SELECT VARIABLE_VALUE FROM performance_schema.global_status
     WHERE VARIABLE_NAME = 'Innodb_buffer_pool_pages_total') * 100, 2
  ) AS dirty_ratio_percent;

-- 3. Эффективность read-ahead
SELECT
  VARIABLE_VALUE AS read_ahead_total
FROM performance_schema.global_status
WHERE VARIABLE_NAME = 'Innodb_buffer_pool_read_ahead';

-- 4. Если Hit Rate < 99% — проблема: Buffer Pool слишком мал
--    или полные табличные сканы вытесняют горячие данные.
--    Решение: увеличьте innodb_buffer_pool_size или добавьте индексы.
```

### 3. Диагностика утечек памяти

Если RSS процесса растет, а `Global Buffers` статичны:

1.  **Проверка Performance Schema:**
    ```sql
    SELECT event_name, current_alloc, high_alloc, current_count
    FROM sys.memory_global_by_current_bytes
    WHERE current_count > 0
    ORDER BY current_alloc DESC
    LIMIT 20;
    ```
2.  **Анализ пула соединений:** В MariaDB утечки часто связаны с огромным количеством «спящих» соединений, каждое из которых удерживает `thread_stack` и буферы сортировки. Проверьте `SHOW STATUS LIKE 'Threads_connected'` и `SHOW PROCESSLIST`.
3.  **OS-level (Jemalloc/Malloc):** Используйте `MALLOC_CONF="stats_print:true"` для вывода статистики аллокатора в лог MariaDB. MariaDB часто собирается с **Jemalloc**, который эффективнее работает с фрагментацией.

**Сравнение RSS с ожидаемым потреблением:**
```bash
# Ожидаемое потребление (Bytes)
EXPECTED=$((innodb_buffer_pool_size + key_buffer_size + aria_pagecache_size + (sort_buffer_size + join_buffer_size + read_buffer_size + thread_stack) * max_connections))

# Фактическое RSS (Bytes)
RSS=$(ps -o rss= -p $(pidof mysqld) | awk '{print $1 * 1024}')

# Если RSS > EXPECTED * 1.3 — вероятна утечка
echo "Expected: $((EXPECTED / 1024 / 1024))MB, RSS: $((RSS / 1024 / 1024))MB"
```

### 4. Динамическая настройка буферов в рантайме

Некоторые параметры памяти можно изменять без перезагрузки. Начиная с MariaDB 10.11.12/11.4.6/11.8.2/12.3 LTS, `innodb_buffer_pool_size` изменяется с шагом 1MB и блокирует выполнение до завершения resize.

```sql
-- Без перезагрузки (динамические):
SET GLOBAL innodb_buffer_pool_size = 8 * 1024 * 1024 * 1024;  -- 8GB
SET GLOBAL max_connections = 500;
SET GLOBAL thread_cache_size = 32;
SET GLOBAL table_open_cache = 4000;
SET GLOBAL tmp_table_size = 67108864;      -- 64MB
SET GLOBAL max_heap_table_size = 67108864; -- 64MB

-- Только при перезагрузке (статические):
-- key_buffer_size, sort_buffer_size, join_buffer_size,
-- read_buffer_size, read_rnd_buffer_size, thread_stack,
-- innodb_buffer_pool_size_max, innodb_buffer_pool_size_auto_min
```

**Проверка статуса изменений:**
```sql
-- До 10.11.12: статус resize
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_resize_status';

-- С 10.11.12+: SET GLOBAL блокирует до завершения resize
-- Проверка текущего размера
SHOW GLOBAL VARIABLES LIKE 'innodb_buffer_pool_size';
-- → innodb_buffer_pool_size = 8589934592 (8G)
```

### 5. Memory Management для MyRocks (LSM-trees)

Если используется движок MyRocks, `innodb_buffer_pool_size` должен быть уменьшен, так как RocksDB использует собственный **Block Cache**:
*   `rocksdb_block_cache_size` — аналог Buffer Pool для RocksDB.
*   **Рекомендация:** При использовании обоих движков (InnoDB + MyRocks) делите память 50/50 или согласно объему горячих данных.

**Пример распределения (64GB RAM):**
```ini
[mariadb]
innodb_buffer_pool_size = 28G      # Для InnoDB-таблиц
rocksdb_block_cache_size = 24G     # Для MyRocks-таблиц
# Остаток: 12GB для OS, per-thread, и других нужд
```

**Валидация:**
```sql
SHOW VARIABLES LIKE 'rocksdb_block_cache_size';
-- → 25769803776 (24G)

SHOW ENGINE ROCKSDB STATUS;
-- → block cache hit ratio, compaction stats
```

### 6. Оптимизация temp-таблиц и предотвращение использования диска

Временные таблицы создаются в памяти, если не превышают `MIN(tmp_table_size, max_heap_table_size)`. При превышении — сбрасываются на диск (Aria по умолчанию), что замедляет запросы.

```sql
-- 1. Проверка текущих лимитов
SHOW VARIABLES LIKE 'tmp_table_size';      -- 16MB по умолчанию
SHOW VARIABLES LIKE 'max_heap_table_size'; -- 16MB по умолчанию

-- 2. Увеличение до 64MB (динамически)
SET GLOBAL tmp_table_size = 67108864;
SET GLOBAL max_heap_table_size = 67108864;

-- 3. Мониторинг: сколько запросов использует disk tmp tables
SHOW GLOBAL STATUS LIKE 'Created_tmp%';
-- Created_tmp_disk_tables / Created_tmp_tables > 25% = проблема
```

### 7. Алертинг через Prometheus: ключевые метрики памяти

```yaml
# Примеры PromQL-запросов для алертов

# 1. Buffer Pool Hit Rate < 99%
1 - (
  mysql_global_status_innodb_buffer_pool_reads
  /
  mysql_global_status_innodb_buffer_pool_read_requests
) < 0.99

# 2. RSS процесса превышает ожидаемое потребление в 1.5 раза
process_resident_memory_bytes
/
(innodb_buffer_pool_size + key_buffer_size + aria_pagecache_size) > 1.5

# 3. Swap Usage > 0 (должен быть 0 на DB-серверах)
mysql_global_status_swap > 0

# 4. Thread Cache Miss Rate > 1%
rate(mysql_global_status_threads_created[5m])
/
rate(mysql_global_status_connections[5m]) > 0.01

# 5. Created_tmp_disk_tables растет быстрее Created_tmp_tables
rate(mysql_global_status_created_tmp_disk_tables[5m])
/
rate(mysql_global_status_created_tmp_tables[5m]) > 0.25
```

## Лучшие практики (Best Practices)

1.  **Выделяйте 50-75% RAM под Buffer Pool.** Для систем с преимущественно InnoDB — 60-75% от доступной RAM. Для смешанных нагрузок — оцените объем индексов MyISAM/Aria через `SHOW TABLE STATUS` и выделите остаток под `key_buffer_size` и `aria_pagecache_size`.
2.  **Отключайте THP.** Всегда ставьте `transparent_hugepage=never`. Для explicit huge pages используйте `vm.nr_hugepages` и настройте `memlock = 1`.
3.  **Устанавливайте `vm.swappiness = 1` и `vm.overcommit_memory = 2`.** Это предотвращает свопинг Buffer Pool и защищает от OOM Killer.
4.  **Используйте `memlock = 1`.** Блокирует страницы Buffer Pool в RAM, исключая своп. Требует настройки `ulimit -l unlimited` для пользователя `mysql`.
5.  **Настраивайте NUMA.** На многосокетных серверах используйте `numactl --interleave=all` для равномерного распределения памяти.
6.  **Ограничивайте `max_connections` реалистично.** Высокий лимит без пула соединений на стороне приложения приводит к исчерпанию RAM. Рекомендуется `max_connections = 500-1000` с connection pooling.
7.  **Не увеличивайте per-thread буферы глобально.** `sort_buffer_size` и `join_buffer_size` > 1MB приводят к фрагментации. Настраивайте на уровне сессии при необходимости.
8.  **Включайте Performance Schema.** Для диагностики утечек и анализа потребления памяти Performance Schema должна быть включена (`performance_schema=ON`).
9.  **Используйте Jemalloc.** Если сборка MariaDB использует glibc malloc, рассмотрите переход на Jemalloc для снижения фрагментации при высокой нагрузке.
10. **Мониторьте Buffer Pool Hit Rate.** Цель > 99%. Если ниже — увеличьте `innodb_buffer_pool_size` или оптимизируйте запросы/индексы.
11. **Настраивайте `innodb_old_blocks_time`.** Значение 1000ms защищает горячие данные от вытеснения при полных табличных сканах.
12. **Используйте Buffer Pool dump/load.** `innodb_buffer_pool_dump_at_shutdown=ON` и `innodb_buffer_pool_load_at_startup=ON` исключают холодный старт после перезагрузки.

## Особенности и ограничения (Edge Cases)

1.  **MyRocks и память:** При использовании MyRocks разделите память между `innodb_buffer_pool_size` и `rocksdb_block_cache_size`. MyRocks несовместим с Galera Cluster.
2.  **2-узловой кластер без arbitrator:** В Galera с 2 узлами без QDevice кворум может быть потерян при падении одного узла. Для HA-сценариев используйте 3 узла или 2 + QDevice.
3.  **Memory pressure auto-shrinking:** Начиная с 10.11.12/11.4.6/11.8.2, Linux может автоматически уменьшать Buffer Pool под давлением памяти. Настройте `innodb_buffer_pool_size_auto_min` для контроля минимального размера.
4.  **SST блокирует донора:** При добавлении узла в Galera без `mariadb-backup` SST блокирует донора на время передачи данных.
5.  **Flow Control:** При перегрузке одного узла Flow Control замедляет весь кластер. Мониторьте `wsrep_flow_control_paused`.
6.  **Orchestrator и Raft:** Orchestrator 3.2.6+ использует Raft для консенсуса. При падении большинства узлов Raft-кластер теряет лидер.
7.  **MaxScale и Galera:** MaxScale определяет `Primary Component` через `galeramon`. Убедитесь, что `wsrep_sst_donor` настроен корректно.
8.  **Rolling Upgrade:** При обновлении Galera используйте `wsrep_cluster_address` с постепенным добавлением узлов. См. **[Безостановочное обновление](Operations/zero_downtime_upgrade.md)**.
9.  **GTID и стандартная репликация:** GTID упрощает failover, но требует одинаковых `gtid_slave_pos` на всех репликах. См. **[Репликация MariaDB: Обзор](replication/overview.md)**.
10. **Семисинхронная репликация:** Требует настроенного `rpl_semi_sync_master_timeout` и `rpl_semi_sync_slave_enabled`. При таймауте автоматически переключается на асинхронную.

## Устранение неисправностей (Troubleshooting)

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **OOM Killer убивает MariaDB** | Сумма `Global + Per-Thread` > Physical RAM. | `dmesg | grep -i oom`; сравните RSS с расчетом. | Уменьшите `max_connections` или `innodb_buffer_pool_size`. Добавьте swap. |
| **Swap Usage растет** | `innodb_buffer_pool_size` слишком велик, ОС вытесняет буферы в своп. | `free -h`, `cat /proc/swaps`, `vmstat 1`. | Включите `memlock = 1` (в конфиге) или уменьшите размер буфера. Установите `vm.swappiness = 1`. |
| **Высокая фрагментация RSS** | Частые аллокации/деаллокации разного размера; glibc malloc не справляется. | `pmap -x <pid>`, `MALLOC_CONF="stats_print:true"`. | Используйте Jemalloc. Не устанавливайте `sort_buffer_size` глобально слишком большим (>1MB). |
| **Created_tmp_disk_tables растет** | Временные таблицы превышают `tmp_table_size`. | `SHOW GLOBAL STATUS LIKE 'Created_tmp%'`. | Увеличьте `tmp_table_size` и `max_heap_table_size`. Добавьте индексы для ORDER BY/GROUP BY. |
| **Opened_tables растет** | `table_open_cache` слишком мал. | `SHOW GLOBAL STATUS LIKE 'Opened_tables'`. | Увеличьте `table_open_cache`. Проверьте `ulimit -n` (нужно > 65535). |
| **Threads_created растет** | `thread_cache_size` недостаточен, каждый коннект создает новый поток. | `SHOW STATUS LIKE 'Threads_%'`. | Увеличьте `thread_cache_size`. |
| **Buffer Pool Hit Rate < 99%** | Buffer Pool слишком мал для рабочего набора данных. | `SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool%'`. | Увеличьте `innodb_buffer_pool_size` или добавьте индексы. |
| **Алерт: RSS > expected × 1.5** | Утечка памяти или фрагментация. | `sys.memory_global_by_current_bytes`, `pmap -x`. | Идентифицируйте компонент через Performance Schema. Перезапустите при необходимости. |
| **MariaDB не стартует (Cannot allocate memory)** | `innodb_buffer_pool_size` + per-thread > RAM при включении. | Проверьте `dmesg`. | Уменьшите `innodb_buffer_pool_size` в my.cnf. |
| **Connection Storm (Thread Pool)** | Все потоки заняты, новые соединения ждут. | `mysql_global_status_threadpool_waits` растет. | Увеличьте `thread_pool_max_threads`, оптимизируйте длинные запросы. |

## Дополнительная информация

### См. также

- **[Конфигурация MariaDB](configuration.md)** — базовые настройки параметров и иерархия загрузки.
- **[Мониторинг MariaDB](monitoring.md)** — отслеживание метрик памяти через Prometheus и `mysqld_exporter`.
- **[Движки хранения](storage_engines.md)** — особенности MyRocks (Block Cache) и Aria (pagecache).
- **[Репликация MariaDB: Обзор](replication/overview.md)** — классическая асинхронная и полусинхронная репликация, GTID, Multi-source.
- **[Отказоустойчивость MariaDB](high_availability.md)** — архитектура Galera, логика кворума и детальные алерты.
- **[Безостановочное обновление](Operations/zero_downtime_upgrade.md)** — процедура rolling upgrade кластеров.
