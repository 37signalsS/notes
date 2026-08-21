# Управление памятью в MariaDB: Диагностика и оптимизация

## Определения

*   **Global Buffers (Глобальные буферы)** — области памяти, выделяемые один раз при старте сервера и разделяемые между всеми потоками. Ключевые параметры: `innodb_buffer_pool_size`, `key_buffer_size`, `innodb_log_buffer_size`, `query_cache_size` (устарел в MariaDB 10.6+). Глобальные буферы не освобождаются на протяжении всего времени работы процесса и не зависят от количества активных соединений.
*   **Per-Thread Memory (Память на поток)** — память, выделяемая для каждого отдельного соединения. Основные параметры: `sort_buffer_size`, `join_buffer_size`, `read_buffer_size`, `read_rnd_buffer_size`, `tmp_table_size`, `max_heap_table_size`. Общий объем per-thread потребления = сумма всех буферов на одно соединение, умноженная на количество активных соединений.
*   **Memory Leak (Утечка памяти)** — ситуация, при которой процесс MariaDB потребляет все больше оперативной памяти (RSS), не возвращая её ОС, даже при низкой нагрузке. В MariaDB утечки часто маскируются под фрагментацию аллокатора или рост пула соединений.
*   **RSS (Resident Set Size)** — реальный объем физической памяти, занимаемый процессом. Отображается в `top`/`htop` как `RES`. Отличается от `VSZ` (Virtual Size), который включает виртуальную память, выделенную, но не обязательно используемую.
*   **Buffer Pool LRU (Least Recently Used)** — алгоритм управления страницами в InnoDB Buffer Pool. Pages делятся на young sublist (горячие данные, 5/8 пула) и old sublist (холодные данные, 3/8 пула). При чтении новая страница попадает в середину old sublist, что защищает горячие данные от однократных сканирований (table scans).
*   **Adaptive Hash Index (AHI)** — механизм InnoDB, автоматически строящий хеш-индекс в памяти для часто запрашиваемых страниц. Ускоряет point lookups, но потребляет дополнительную память (до 1/64 от Buffer Pool). Отключается параметром `innodb_adaptive_hash_index=OFF` при высокой нагрузке на блокировки.
*   **tmp_table_size / max_heap_table_size** — лимит размера внутренних временных таблиц в памяти. Если запрос превышает этот порог, временная таблица сбрасывается на диск (Aria в MariaDB по умолчанию). Реальный лимит = `MIN(tmp_table_size, max_heap_table_size)`.
*   **Thread Cache** — кэш неактивных потоков, позволяющий переиспользовать их при новых подключениях без затрат на создание OS-потока. Настраивается параметром `thread_cache_size`. Эффективность кэша оценивается через `Threads_created / Connections` (цель < 1%).
*   **Table Cache** — кэш дескрипторов открытых таблиц. Настраивается через `table_open_cache` и `table_definition_cache`. Каждый дескриптор потребляет память в kernel space. При нехватке — рост `Opened_tables` и снижение производительности из-за частого `open`/`close`.
*   **Performance Schema Memory Instrumentation** — подсистема MariaDB для отслеживания всех аллокаций памяти на уровне индивидуальных функций. Позволяет точно идентифицировать утечки памяти, измеряя потребление по компонентам (InnoDB, SQL-parser, MyRocks и т.д.).
*   **Jemalloc** — аллокатор памяти, используемый по умолчанию в большинстве сборок MariaDB (начиная с 5.5). Эффективнее стандартного `glibc malloc` борется с фрагментацией при массовых аллокациях/деаллокациях разного размера. Мониторинг: `MALLOC_CONF="stats_print:true"`.
*   **Huge Pages** — механизм ОС, позволяющий использовать страницы памяти размером 2MB или 1GB вместо стандартных 4KB. InnoDB Buffer Pool может использовать Transparent Huge Pages (THP) для снижения TLB misses, но THP может вызывать lag при дефрагментации — рекомендуется `transparent_hugepage=never` для MariaDB.

## Базовые концепции

### Иерархия потребления памяти

Общее потребление MariaDB = `Global Buffers` + (`max_connections` * `Per-Thread Memory`).

```
Total RAM
├── OS & System Services (10-15%)
├── Global Buffers
│   ├── innodb_buffer_pool_size     (основной потребитель)
│   ├── innodb_log_buffer_size      (буфер WAL-логов)
│   ├── key_buffer_size             (MyISAM/Aria индексы)
│   ├── query_cache_size            (устарел, отключить)
│   └── aria_pagecache_size         (кеш страниц Aria)
├── Per-Thread Buffers × max_connections
│   ├── sort_buffer_size            (сортировка)
│   ├── join_buffer_size            (неупорядоченные JOIN)
│   ├── read_buffer_size            (последовательное чтение)
│   ├── read_rnd_buffer_size        (произвольное чтение)
│   ├── thread_stack                (стек потока)
│   ├── net_buffer_length           (сетевой буфер)
│   └── binlog_cache_size           (кеш бинарного лога)
└── Shared Memory (Performance Schema, table cache, etc.)
```

### InnoDB Buffer Pool: внутренняя архитектура

Buffer Pool — основной потребитель памяти в большинстве конфигураций InnoDB. Он хранит копии страниц данных и индексов, уменьшая необходимость обращения к диску.

**Структура LRU-списка:**
- **Young sublist (горячие страницы):** 5/8 от общего размера. Содержит страницы, к которым недавно обращались.
- **Old sublist (холодные страницы):** 3/8 от общего размера. Новые страницы попадают сюда. Это защищает горячие данные от однократных full table scans, которые вытесняют нужные страницы.
- ** midpoint:** Точка, куда попадает страница при первом чтении (между old и young sublist).
- **InnoDB Read-Ahead:** Предиктивное чтение邻接ных страниц ( hendeler变数 в `innodb_read_ahead_threshold`). При последовательном чтении > N страниц InnoDB предзагружает следующие.

**Cleanup mechanics:**
- Фоновые потоки (page cleaner) сбрасывают грязные страницы (dirty pages) на диск.
- При нехватке страниц для выделения — InnoDBflush_LRU_list, вытесняя самые холодные страницы.
- `innodb_old_blocks_time=1000` (ms) — задержка перед перемещением страницы из old в young sublist, предотвращающая «отравление» горячих данных.

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
| `read_buffer_size` | Последовательное чтение поIMARY KEY или индексу | Sequential full table/index scan | Редко меняется, обычно 256KB достаточно |
| `read_rnd_buffer_size` | Буфер для чтения после сортировки ( rnd_) | ORDER BY + LIMIT с индексом | Не увеличивать >1MB без нужды |
| `thread_stack` | Стек для выполнения SQL-кода | Каждое соединение | Стандартное значение 256KB оптимально |
| `net_buffer_length` | Сетевой буфер для отправки/получения результатов | Каждое соединение | 16KB по умолчанию, редко меняется |

**Важно:** Все per-thread буферы выделяются по требованию (на запрос) и освобождаются при завершении запроса. Однако `sort_buffer_size` и `join_buffer_size` не освобождаются из памяти потока после запроса — они переиспользуются. Это значит, что при большом количестве соединений каждый поток удерживает свой максимальный буфер.

### Thread Cache и Table Cache

**Thread Cache (`thread_cache_size`):**
- Хранит завершенные потоки для переиспользования.
- При `thread_cache_size = 0` каждый новый коннект создает OS-поток (дорого).
- Мониторинг: `SHOW STATUS LIKE 'Threads_%'`. Если `Threads_created` растет быстрее `Connections` — увеличьте кэш.
- Рекомендация: `thread_cache_size = max(16, max_connections / 100)`.

**Table Cache (`table_open_cache`, `table_definition_cache`):**
- `table_open_cache`: количество открытых таблиц на процесс. Каждая запись потребляет ~2KB kernel memory.
- `table_definition_cache`: кэш определений (metadанных) таблиц. Не зависит от дескрипторов.
- При нехватке: рост `Opened_tables` (>1/сек = проблема), lock contention на `open_lock`.
- Рекомендация: `table_open_cache` = `max_connections * join_buffer_size_of_tables` (приблизительно).

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
# → [always] madvise never

# Отключение для MariaDB (рекомендуется)
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/defrag
```
THP может вызывать latency spikes при дефрагментации (compaction), что критично для латентных OLTP-сценариев.

**vm.swappiness:**
- Значение по умолчанию `60` слишком агрессивно для БД.
- Рекомендация: `vm.swappiness = 1` — ОС будет использовать swap только в крайнем случае.
- Значение `0` (старые ядра) — никогда не свопает; `1` (современные ядра) — минимальный swap.

**vm.overcommit_memory:**
- `0` (по умолчанию): heuristical overcommit — ОС может убить процесс при нехватке памяти.
- `1`: всегда разрешать — опасно для БД, может привести к OOM без предупреждений.
- `2`: жесткий лимит = `swap + RAM * overcommit_ratio` (по умолчанию 50%). Рекомендуется для production.

**ulimit и файловые дескрипторы:**
```bash
# Проверка текущих лимитов
ulimit -n          # открытыe файлы (цель > 65535 для MariaDB)
ulimit -s          # размер стека потока (обычно 8MB, достаточно)

# Установка в /etc/security/limits.conf
mysql soft nofile 65535
mysql hard nofile 65535
```

---

## Практические сценарии

### 1. Расчет буферов для смешанных нагрузок

Если в системе одновременно используются таблицы InnoDB (OLTP) и MyISAM/Aria (архив или системные), необходимо балансировать между `innodb_buffer_pool_size` и `key_buffer_size`.

**Формула расчета (SRE Best Practice):**
1.  Выделите 10-15% RAM для ОС и системных нужд.
2.  Вычислите объем на поток: `PerThread = (sort + join + read + read_rnd + thread_stack + net_buffer) * max_connections`.
3.  Остаток распределите между буферами в пропорции к объему данных:
    *   **Преимущественно InnoDB:** `innodb_buffer_pool_size` = 80-90% от остатка.
    *   **Смешанная нагрузка:** Используйте `SHOW TABLE STATUS` для оценки объема индексов каждого типа и распределите пропорционально.

**Пример (сервер 64GB RAM, 500 соединений):**
- ОС: 8GB
- Per-Thread (2MB на поток): 1GB
- Остаток: 55GB.
- Настройка: `innodb_buffer_pool_size = 48G`, `key_buffer_size = 4G`.

**Валидация после настройки:**
```sql
-- Проверка фактического потребления
SELECT
  ROUND(@@innodb_buffer_pool_size / 1024 / 1024 / 1024, 2) AS buffer_pool_GB,
  ROUND(@@key_buffer_size / 1024 / 1024 / 1024, 2) AS key_buffer_GB,
  (SELECT VARIABLE_VALUE FROM performance_schema.global_status
   WHERE VARIABLE_NAME = 'Innodb_buffer_pool_pages_total') * 16 / 1024 / 1024 AS actual_pool_GB;
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
--    или many full table scans вытесняют горячие данные.
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
2.  **Анализ пула потоков (Thread Pool):** В MariaDB утечки часто связаны с огромным количеством «спящих» соединений, каждое из которых удерживает `thread_stack` и буферы сортировки.
3.  **OS-level (Jemalloc/Malloc):** Используйте `MALLOC_CONF="stats_print:true"` для вывода статистики аллокатора в лог MariaDB. MariaDB часто собирается с **Jemalloc**, который эффективнее работает с фрагментацией.

**Сравнение RSS с ожидаемым потреблением:**
```bash
# Ожидаемое потребление (Bytes)
EXPECTED=$((innodb_buffer_pool_size + key_buffer_size + (sort_buffer_size + join_buffer_size + read_buffer_size + thread_stack) * max_connections))

# Фактическое RSS (Bytes)
RSS=$(ps -o rss= -p $(pidof mysqld) | awk '{print $1 * 1024}')

# Если RSS > EXPECTED * 1.3 — вероятна утечка
echo "Expected: $((EXPECTED / 1024 / 1024))MB, RSS: $((RSS / 1024 / 1024))MB"
```

### 4. Динамическая настройка буферов в рантайме

Некоторые параметры памяти можно изменять без перезагрузки:

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
-- read_buffer_size, read_rnd_buffer_size, thread_stack
```

**Проверка статуса изменений:**
```sql
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_resize_status';
-- → "Completed resizing buffer pool at 240820 10:30:15"
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

### 6. Настройка памяти для контейнеров (Docker/Kubernetes)

В контейнерах лимит памяти жестко задается cgroup limit. Ошибка настройки приводит к OOM Kill.

**Docker:**
```bash
docker run -d \
  --name mariadb \
  --memory="8g" \
  --memory-swap="8g" \
  -e MARIADB_ROOT_PASSWORD=secret \
  mariadb:12.3
```

**Kubernetes:**
```yaml
resources:
  requests:
    memory: "8Gi"
  limits:
    memory: "8Gi"  # Guaranteed QoS: requests == limits
```

**Важно:** `innodb_buffer_pool_size` должен быть **меньше** лимита контейнера минимум на 1-2GB (запас на OS overhead, per-thread buffers, kernel memory). Типичная ошибка — установить `innodb_buffer_pool_size` равным лимиту контейнера, что приводит к OOM Kill при пиках нагрузки.

### 7. Оптимизация temp-таблиц и предотвращение использования диска

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

### 8. Алертинг через Prometheus: ключевые метрики памяти

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
(innodb_buffer_pool_size + key_buffer_size) > 1.5

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

---

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
- **[Мониторинг MariaDB](monitoring.md)** — отслеживание метрик памяти через Prometheus и mysqld_exporter.
- **[Движки хранения](storage_engines.md)** — особенности MyRocks (Block Cache) и Aria (pagecache).
- **[MySQL: Memory Architecture](../../MySQL/configuration.md#расчет-памяти)** — сравнение с Oracle MySQL.
