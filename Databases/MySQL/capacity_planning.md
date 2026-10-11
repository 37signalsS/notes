# Capacity Planning одиночного инстанса MySQL

**Актуально для:** MySQL 8.0.30+ / 8.4 LTS (для 8.0.29 и ниже redo log настраивается иначе — см. сценарий 4)

## Определения

*   **Capacity Planning** — прогнозирование ресурсов (CPU, RAM, диск, сеть) для поддержания производительности при росте нагрузки. Цель — масштабировать до исчерпания ресурсов, а не после.
*   **Baseline (базовая линия)** — зафиксированный снимок метрик (QPS, latency p95/p99, hit rate, скорость роста данных) до изменений. Без baseline невозможно оценить эффект тюнинга и спрогнозировать рост.
*   **Working set (рабочий набор)** — объём данных, активно читаемых в память. Ключевой параметр для sizing RAM: working set должен помещаться в `innodb_buffer_pool_size`.
*   **Buffer Pool Hit Rate** — доля чтений из buffer pool (без обращения к диску). Цель > 99% для OLTP. Формула: `1 - Innodb_buffer_pool_reads / Innodb_buffer_pool_read_requests`.
*   **IOPS** — операций ввода-вывода в секунду. Ключевой параметр для sizing диска (особенно для write-нагрузки и redo log).
*   **Throughput** — пропускная способность: TPS (транзакции/сек), QPS (запросы/сек).
*   **Headroom** — запас ресурсов (обычно 30-50%) для пиков нагрузки и роста.
*   **Saturation (насыщение)** — доля использования ресурса. Методология USE (Utilization, Saturation, Errors): **[Мониторинг](monitoring.md)**.

## Базовые концепции

### Четыре ресурса

| Ресурс | Ключевой параметр | Метрика | Цель |
| :--- | :--- | :--- | :--- |
| **CPU** | ядра | `Threads_running` vs ядра | `Threads_running` < 2× ядер (эвристика) |
| **RAM** | `innodb_buffer_pool_size` | buffer pool hit rate | > 99% (OLTP) |
| **Диск** | IOPS, latency | `Innodb_data_pending_{reads,writes,fsyncs}`, `iostat -x` | `await` < 10ms (SSD), pending ≈ 0 |
| **Сеть** | bandwidth, connections | `Bytes_sent/received`, `Threads_connected` | < 70% bandwidth |

### Формулы sizing

**RAM:**
```
innodb_buffer_pool_size ≈ working_set_size × 1.2 (запас)
Total RAM = buffer_pool + OS (1-2 GB) + per-thread (max_connections × per-thread) + Performance Schema
```

Официальная рекомендация MySQL: `innodb_buffer_pool_size` = **50–75% от RAM хоста** (How MySQL Uses Memory). На практике для выделенного MySQL-сервера часто указывают 70–80% — остаток должен вмещать OS, per-thread буферы и Performance Schema. Buffer pool можно менять онлайн (`SET GLOBAL`), но размер должен быть кратен `innodb_buffer_pool_chunk_size` (128MB по умолчанию) × `innodb_buffer_pool_instances` (по умолчанию 1 в 8.0+), иначе сервер автоматически округлит значение до кратного.

**Per-thread потребление (оценка, worst-case):**
```
per_thread ≈ sort_buffer_size + join_buffer_size + read_buffer_size +
             read_rnd_buffer_size + thread_stack + net_buffer_length
```

Формула из документации (InnoDB Startup Configuration): `key_buffer_size + max_connections × (sort_buffer_size + read_buffer_size + binlog_cache_size) + max_connections × 2MB`. Каждый поток использует stack (2MB, в бинарниках Oracle — 256KB) и в худшем случае ещё `sort_buffer_size` + `read_buffer_size`. Буферы выделяются по требованию (при сортировке, скане, join), а не постоянно — worst-case редко реализуется полностью, но именно так считают для планирования. `net_buffer_length` может расти до `max_allowed_packet` на соединение. Нюанс для hash join (8.0+): буфер выделяется инкрементально, мелкие запросы не аллоцируют весь `join_buffer_size`, но outer joins выделяют его целиком.

**Диск (write-нагрузка):**
```
Required IOPS ≈ (writes_per_sec × 2) + (reads_per_sec × (1 - hit_rate))
```

Множитель ×2 — поправка на redo log и doublewrite buffer: записанная страница проходит и redo, и doublewrite. `innodb_redo_log_capacity` (с 8.0.30) и doublewrite (`#ib_*.dblwr`) — основные потребители write IOPS.

**CPU:**
```
Required cores ≈ peak Threads_running × 1.5 (верхняя оценка для CPU-bound нагрузки)
```

Для mixed OLTP с простыми запросами — ×0.5–1. Это эвристика, не закон: валидируйте нагрузочным тестом (сценарий 7).

### Когда масштабировать

*   Buffer pool hit rate < 99% постоянно → увеличить RAM. Для scan-heavy нагрузки (много полных сканов) значение ниже 99% может быть нормой — смотрите тренд, а не абсолют.
*   `Threads_running` ≈ количество ядер постоянно → увеличить CPU.
*   I/O wait (`iostat` %util > 70%, `Innodb_data_pending_*` > 0) → быстрее диск (NVMe) или больше IOPS.
*   `Threads_connected` ≈ `max_connections` → connection pooling или больше RAM (per-thread).
*   Диск заполнен > 70% → больше места или архивация.

## Практические сценарии

### 1. Оценка текущего потребления

```sql
-- RAM: buffer pool
SHOW VARIABLES LIKE 'innodb_buffer_pool_size';
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read%';
-- Hit rate: 1 - reads/requests

-- Сколько данных в buffer pool
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_bytes_data';
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_pages_data';
-- pages_data × innodb_page_size (16K) ≈ объём данных в памяти

-- CPU: активные потоки
SHOW GLOBAL STATUS LIKE 'Threads_running';
SHOW GLOBAL STATUS LIKE 'Threads_connected';

-- Соединения: рост Threads_created → thread cache мал (считайте Threads_created / Connections)
SHOW GLOBAL STATUS LIKE 'Threads_created';
SHOW GLOBAL STATUS LIKE 'Connections';
SHOW GLOBAL STATUS LIKE 'Aborted_connects';
SHOW GLOBAL STATUS LIKE 'Aborted_clients';

-- Диск: текущие ожидающие операции (норма ≈ 0)
SHOW GLOBAL STATUS LIKE 'Innodb_data_pending%';
-- Innodb_data_pending_reads / _writes / _fsyncs
SHOW GLOBAL STATUS LIKE 'Innodb_data_reads';
SHOW GLOBAL STATUS LIKE 'Innodb_data_writes';
SHOW GLOBAL STATUS LIKE 'Innodb_os_log_written';

-- Временные таблицы: доля на диске — давление на I/O
SHOW GLOBAL STATUS LIKE 'Created_tmp%';

-- Сеть
SHOW GLOBAL STATUS LIKE 'Bytes_%';
```

```bash
# ОС
vmstat 1 5                # CPU, memory, swap, io
iostat -x 1 5             # disk utilization, await
free -h                   # RAM
df -h                     # disk space
du -sh /var/lib/mysql     # размер datadir — для тренда роста
```

### 2. Оценка working set

```sql
-- Размер данных и индексов
SELECT
  TABLE_SCHEMA,
  ROUND(SUM(DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 2) AS size_mb
FROM information_schema.TABLES
WHERE ENGINE = 'InnoDB'
GROUP BY TABLE_SCHEMA;

-- Страницы в buffer pool по схемам (InnoDB)
SELECT OBJECT_SCHEMA, COUNT(*) AS pages
FROM information_schema.INNODB_BUFFER_PAGE
GROUP BY OBJECT_SCHEMA;
```

**Правило:** `innodb_buffer_pool_size` должен покрывать working set (горячие данные), а не весь объём БД.

**Ограничения:** `INNODB_BUFFER_PAGE` требует привилегии `PROCESS`, а сам запрос тяжёлый на нагруженном инстансе — не оставляйте его в регламенте мониторинга. Для постоянного наблюдения используйте `Innodb_buffer_pool_bytes_data` / `Innodb_buffer_pool_pages_data` из `SHOW GLOBAL STATUS`.

### 3. Прогноз роста

```sql
-- Рост таблиц за период (пример: схема shop)
SELECT
  TABLE_NAME,
  DATA_LENGTH,
  UPDATE_TIME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'shop'
ORDER BY DATA_LENGTH DESC;
```

```bash
# Замерьте размер datadir сейчас и через месяц
du -sh /var/lib/mysql
# Прогноз: size_next_year = size_now × (1 + monthly_growth)^12
```

**Метод:** измерьте рост за 30 дней, экстраполируйте, добавьте 30–50% headroom на индексы, временные таблицы, binlog и рост. Пересчитывайте план ежемесячно и при изменении объёма в 2×.

### 4. Sizing диска: redo log, binlog, undo, temp

```ini
[mysqld]
# Redo log (8.0.30+): суммарная ёмкость; 32 файла по 1/32 в #innodb_redo/
innodb_redo_log_capacity = 4G
# до 8.0.30 (deprecated): innodb_log_file_size × innodb_log_files_in_group
# (2 файла по 5MB по умолчанию; суммарный размер — чуть меньше 512G)

# Binlog — место под ротацию
binlog_expire_logs_seconds = 604800   # 7 дней (дефолт 2592000 = 30 дней)
```

Компоненты, которые нужно спланировать в datadir и на томах:

*   **Redo log** — дефолт всего 100MB (`innodb_redo_log_capacity`): на write-нагрузке мал, рассчитывайте под 1–2 часа пиковых записей. Изменяется онлайн (`SET GLOBAL`), применяется сразу, но полное перераспределение по 32 файлам занимает время.
*   **Doublewrite buffer** — 2 файла `#ib_16384_*.dblwr` (8.0.20+), место в datadir.
*   **Binlog + индекс** — `binlog_size_per_day × retention` (см. формулу ниже).
*   **Undo tablespaces** — растут при долгих и массовых транзакциях.
*   **Внутренние temp-таблицы** — `ibtmp1` в datadir (по умолчанию `ibtmp1:12M:autoextend` — проверьте `SHOW VARIABLES LIKE 'innodb_temp_data_file_path'`); при большом объёме дисковых temp-таблиц задайте явный путь и лимит.
*   **Relay log** — на реплике: `binlog_rate × максимальный лаг`.
*   **Логи** (error, slow, general) — ротация или отдельный том.

**Оценка места:** `binlog_size_per_day × binlog_expire_logs_seconds / 86400` + redo log + relay log + datadir + headroom 30–50%.

### 5. Полный sizing для новой нагрузки

**Исходные данные (пример):** 100 GB working set, 5000 QPS, 80% read / 20% write, 500 соединений.

**RAM:**
```
innodb_buffer_pool_size = 100 GB × 1.2 = 120 GB
per-thread = 500 × 2 MB = 1 GB (worst-case)
OS + Performance Schema = 4 GB
Total ≈ 125 GB → берём 192 GB (buffer pool = 62.5% RAM — в пределах официальной рекомендации 50–75%)
```

**CPU:**
```
Threads_running (peak) ≈ 50–100
Required cores = 100 × 1.5 = 150 — верхняя оценка (CPU-bound)
mixed OLTP: 32–64 ядра + headroom; валидируйте sysbench'ом (сценарий 7)
```

**Диск:**
```
Write IOPS ≈ 5000 × 0.2 × 2 = 2000 IOPS → NVMe SSD (3000+ IOPS)
innodb_io_capacity: дефолт 200 (8.0) / 10000 (8.4) — ставьте ≈ IOPS устройства
innodb_io_capacity_max: max(2×io_capacity, 2000) (8.0) / 2×io_capacity, мин. 2000 (8.4)
```

**Сеть:**
```
5000 QPS × 1 KB avg = 5 MB/s = 40 Mbps → 1 GbE достаточно
```

### 6. Проверка дисковой подсистемы до развёртывания

```bash
# Пример: случайная запись 16K (близка к InnoDB page), 4 job'а, 60 сек
fio --name=randwrite --rw=randwrite --bs=16k --ioengine=libaio \
    --iodepth=32 --numjobs=4 --size=1G --runtime=60 --time_based \
    --group_reporting
```

Сравните полученные IOPS и latency с `Required IOPS` из сценария 5. Тест выполняйте на том же типе хранилища (local NVMe, SAN, network volume) — цифры разных типов несопоставимы.

### 7. Проверка sizing нагрузочным тестом

Перед сменой железа или масштабированием воспроизведите нагрузку: **[sysbench](../Concepts/sysbench.md)** (встроенные OLTP-профили и кастомные Lua-сценарии), методология подготовки и интерпретации — **[Бенчмаркинг СУБД](../Concepts/benchmarking.md)**, теория TPS/latency/USE — **[Концепции производительности](../Concepts/database_performance_concepts.md)**.

## Валидация

1.  Через 24–48 часов после изменения sizing сравните факт с прогнозом: hit rate, `Threads_running` (p95), `iostat -x` (`await`, `%util`), `Innodb_data_pending_*`, скорость роста datadir (`du -sh` раз в неделю).
2.  Онлайн-изменения без перезапуска:

```sql
SET GLOBAL innodb_buffer_pool_size = 128G;          -- кратно chunk × instances
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_resize_status';
SET GLOBAL innodb_redo_log_capacity = 8589934592;   -- 8.0.30+ (8 GB), применяется сразу
SET GLOBAL innodb_io_capacity = 5000;
SET GLOBAL innodb_io_capacity_max = 10000;
```

3.  Прогрев после перезапуска: `innodb_buffer_pool_dump_at_shutdown` и `innodb_buffer_pool_load_at_startup` включены по умолчанию (`innodb_buffer_pool_dump_pct` = 25) — pool восстанавливается в фоне и не задерживает старт. После онлайн-изменения размера pool прогрев начинается заново.

## Устранение неисправностей (Troubleshooting)

### Типичные симптомы нехватки ресурсов

| Симптом | Ресурс | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Hit rate < 99% | RAM | `Innodb_buffer_pool_reads` растёт | Увеличить `innodb_buffer_pool_size` |
| `Threads_running` ≈ ядра | CPU | `SHOW GLOBAL STATUS` | Оптимизировать запросы, добавить ядра |
| `Innodb_data_pending_*` > 0 | Диск | `iostat -x 1`, `SHOW GLOBAL STATUS` | NVMe, больше IOPS, `innodb_io_capacity` |
| `Threads_connected` ≈ `max_connections` | RAM/connections | `SHOW PROCESSLIST` | Connection pooling, `wait_timeout` |
| `Innodb_buffer_pool_wait_free` > 0 | RAM | `SHOW GLOBAL STATUS` | Buffer pool переполнен — увеличить |
| `Threads_created` растёт | Connections | `Threads_created / Connections` | Увеличить `thread_cache_size` |
| `Created_tmp_disk_tables` растёт | Диск | `SHOW GLOBAL STATUS LIKE 'Created_tmp%'` | `tmp_table_size`/`max_heap_table_size`, оптимизация запросов |
| Диск > 70% | Диск | `df -h`, `du -sh /var/lib/mysql` | Архивация, `binlog_expire_logs_seconds` |

### Ошибки sizing

1.  **`innodb_buffer_pool_size` > доступной RAM** → OOM Killer. Оставьте 1–2 GB на OS + per-thread buffers.
2.  **`max_connections` завышен без пула** → per-thread память × connections = OOM. Считайте: `max_connections × per_thread_buffers`.
3.  **`innodb_io_capacity` не соответствует диску** → checkpoint не успевает, `Innodb_data_pending_writes` растёт. NVMe: 10000–20000, SSD: 2000–5000, HDD: 100–200. Учтите версию: дефолт 200 (8.0) и 10000 (8.4) — конфиг, переехавший с 8.0 на 8.4, может «просесть» или наоборот.
4.  **Buffer pool не кратен `innodb_buffer_pool_chunk_size` × `innodb_buffer_pool_instances`** → сервер автоматически округлит размер (сюрприз при планировании «ровно 100G»). Считайте кратность заранее.
5.  **Redo log по дефолту (100MB) на write-heavy инстансе** → частые checkpoint-бёрсты, просадка write throughput. Рассчитывайте под 1–2 часа пиковой записи.
6.  **`innodb_flush_sync` (ON по умолчанию)** игнорирует `innodb_io_capacity` при checkpoint-бёрстах — если нужен строгий лимит I/O, выключите.

## Лучшие практики

1.  **Baseline до изменений** — зафиксируйте QPS, latency (p95, p99), hit rate до тюнинга.
2.  **Working set, не весь объём** — buffer pool под горячие данные, не под всю БД.
3.  **Headroom 30–50%** — планируйте с запасом на пики и рост.
4.  **Считайте per-thread память** — `max_connections` × буферы, а не только buffer pool.
5.  **Мониторьте saturation** — USE-методология: Utilization, Saturation, Errors.
6.  **Алерты заранее** — disk 70/80/90%, hit rate < 99% (15m), `Threads_running` > 2× ядер (5m); примеры Prometheus — **[Мониторинг](monitoring.md)**.
7.  **`innodb_dedicated_server`** — авто-настройка `innodb_buffer_pool_size`, redo log и `innodb_flush_method` по RAM хоста; полезен для быстрого старта, но в production считайте размер вручную (дефолт OFF).
8.  **Тяжёлые диагностические запросы** (`SHOW ENGINE INNODB STATUS`, `INNODB_BUFFER_PAGE`) — генерация вывода влияет на производительность: не ставьте в регламент мониторинга на нагруженном инстансе.

## Дополнительная информация

### См. также

*   **[Обзор MySQL](overview.md)** — раздел Capacity Planning.
*   **[Конфигурация](configuration.md)** — тюнинг параметров.
*   **[Мониторинг](monitoring.md)** — метрики и алертинг.
*   **[Управление соединениями](connection-management.md)** — per-thread память.
*   **[sysbench](../Concepts/sysbench.md)** — нагрузочное тестирование.
*   **[Бенчмаркинг СУБД](../Concepts/benchmarking.md)** — методология.
*   **[MariaDB: capacity planning](../MariaDB/capacity_planning.md)** — аналог для MariaDB.

### Внешние ресурсы

*   [MySQL Capacity Planning](https://dev.mysql.com/doc/refman/8.4/en/capacity-planning.html)
*   [InnoDB Buffer Pool](https://dev.mysql.com/doc/refman/8.4/en/innodb-buffer-pool.html)
*   [How MySQL Uses Memory](https://dev.mysql.com/doc/refman/8.4/en/memory-use.html)
*   [Configuring InnoDB Buffer Pool Size](https://dev.mysql.com/doc/refman/8.4/en/innodb-buffer-pool-resize.html)
*   [Configuring InnoDB I/O Capacity](https://dev.mysql.com/doc/refman/8.4/en/innodb-configuring-io-capacity.html)
*   [Redo Log](https://dev.mysql.com/doc/refman/8.4/en/innodb-redo-log.html)
