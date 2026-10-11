# Capacity Planning одиночного инстанса MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **Capacity Planning** — прогнозирование ресурсов (CPU, RAM, диск, сеть) для поддержания производительности при росте нагрузки. Цель — масштабировать до исчерпания ресурсов, а не после.
*   **Working set (рабочий набор)** — объём данных, активно читаемых в память. Ключевой параметр для sizing RAM: working set должен помещаться в `innodb_buffer_pool_size`.
*   **Buffer Pool Hit Rate** — доля чтений из buffer pool (без обращения к диску). Цель > 99%. Формула: `1 - Innodb_buffer_pool_reads / Innodb_buffer_pool_read_requests`.
*   **IOPS** — операций ввода-вывода в секунду. Ключевой параметр для sizing диска (особенно для write-нагрузки и redo log).
*   **Throughput** — пропускная способность: TPS (транзакции/сек), QPS (запросы/сек).
*   **Headroom** — запас ресурсов (обычно 30-50%) для пиков нагрузки и роста.
*   **Saturation (насыщение)** — доля использования ресурса. Методология USE (Utilization, Saturation, Errors): **[Мониторинг](monitoring.md)**.

## Базовые концепции

### Четыре ресурса

| Ресурс | Ключевой параметр | Метрика | Цель |
| :--- | :--- | :--- | :--- |
| **CPU** | ядра | `Threads_running` vs ядра | `Threads_running` < 2× ядер |
| **RAM** | `innodb_buffer_pool_size` | buffer pool hit rate | > 99% |
| **Диск** | IOPS, latency | `Innodb_data_pending_*`, iostat | latency < 10ms (SSD) |
| **Сеть** | bandwidth, connections | `Bytes_sent/received`, `Threads_connected` | < 70% bandwidth |

### Формулы sizing

**RAM:**
```
innodb_buffer_pool_size ≈ working_set_size × 1.2 (запас)
Total RAM = buffer_pool + OS (1-2 GB) + per-thread (max_connections × per-thread) + Performance Schema
```

**Per-thread потребление (оценка):**
```
per_thread ≈ sort_buffer_size + join_buffer_size + read_buffer_size +
             read_rnd_buffer_size + thread_stack + net_buffer_length
```
При `max_connections = 500` и 2 MB per-thread → 1 GB (теоретический максимум).

**Диск (write-нагрузка):**
```
Required IOPS ≈ (writes_per_sec × 2) + (reads_per_sec × (1 - hit_rate))
```
Redo log (`innodb_log_file_size`) и doublewrite buffer — основные потребители write IOPS.

**CPU:**
```
Required cores ≈ peak Threads_running × 1.5 (headroom)
```

### Когда масштабировать

*   Buffer pool hit rate < 99% постоянно → увеличить RAM.
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

-- CPU: активные потоки
SHOW GLOBAL STATUS LIKE 'Threads_running';
SHOW GLOBAL STATUS LIKE 'Threads_connected';

-- Соединения
SHOW GLOBAL STATUS LIKE 'Threads_created';
SHOW GLOBAL STATUS LIKE 'Connections';

-- Диск: I/O
SHOW GLOBAL STATUS LIKE 'Innodb_data_pending%';
SHOW GLOBAL STATUS LIKE 'Innodb_data_reads';
SHOW GLOBAL STATUS LIKE 'Innodb_data_writes';

-- Сеть
SHOW GLOBAL STATUS LIKE 'Bytes_%';
```

```bash
# ОС
vmstat 1 5          # CPU, memory, swap, io
iostat -x 1 5       # disk utilization, await
free -h             # RAM
df -h               # disk space
```

### 2. Оценка working set

```sql
-- Размер данных и индексов
SELECT
  TABLE_SCHEMA,
  ROUND(SUM(DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024 / 1024, 2) AS size_gb
FROM information_schema.TABLES
GROUP BY TABLE_SCHEMA;

-- Размер buffer pool в страницах
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_pages_%';
-- pages_data × innodb_page_size (16K) = данные в buffer pool
```

**Оценка working set:** если `Innodb_buffer_pool_pages_data` стабильно растёт и hit rate < 99% — working set больше buffer pool.

### 3. Прогноз роста

```bash
# Рост данных за период
# Замерьте размер datadir сейчас и через месяц
du -sh /var/lib/mysql

# Прогноз: size_next_year = size_now × (1 + monthly_growth)^12
```

```sql
-- Рост таблиц
SELECT TABLE_NAME,
  ROUND(DATA_LENGTH / 1024 / 1024, 2) AS data_mb,
  ROUND(INDEX_LENGTH / 1024 / 1024, 2) AS index_mb
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'shop'
ORDER BY DATA_LENGTH DESC
LIMIT 10;
```

### 4. Sizing для новой нагрузки

**Исходные данные:** 100 GB working set, 5000 QPS, 80% read / 20% write, 500 соединений.

**RAM:**
```
innodb_buffer_pool_size = 100 GB × 1.2 = 120 GB
per-thread = 500 × 2 MB = 1 GB
OS + Performance Schema = 4 GB
Total RAM ≈ 128 GB (округлить до 128-192 GB)
```

**CPU:**
```
Threads_running (peak) ≈ 50-100
Required cores = 100 × 1.5 = 150 → 16-32 ядра (зависит от сложности запросов)
```

**Диск:**
```
Write IOPS ≈ 5000 × 0.2 × 2 = 2000 IOPS
→ NVMe SSD (3000+ IOPS) или RAID10 SSD
```

**Сеть:**
```
5000 QPS × 1 KB avg = 5 MB/s = 40 Mbps → 1 GbE достаточно
```

### 5. Мониторинг насыщения (алерты)

```yaml
# Prometheus алерты (см. monitoring.md)
- alert: MariaDBBufferPoolHitRateLow
  expr: 1 - (mysql_global_status_innodb_buffer_pool_reads /
    mysql_global_status_innodb_buffer_pool_read_requests) < 0.99
  for: 15m

- alert: MariaDBHighIOWait
  expr: rate(node_disk_io_time_seconds_total[5m]) > 0.7

- alert: MariaDBDiskFull
  expr: node_filesystem_avail_bytes{mountpoint="/var/lib/mysql"} /
    node_filesystem_size_bytes{mountpoint="/var/lib/mysql"} < 0.3
```

## Устранение неполадок (Troubleshooting)

### Buffer pool hit rate < 99%

*   **Причина:** working set > buffer pool.
*   **Диагностика:** `Innodb_buffer_pool_reads` (физические чтения) растёт; `Innodb_buffer_pool_pages_data` стабильно высокий.
*   **Решение:** увеличить `innodb_buffer_pool_size`; оптимизировать запросы (меньше чтений); архивировать старые данные.

### Высокий I/O wait

*   **Причина:** диск не справляется с нагрузкой.
*   **Диагностика:** `iostat -x 1` — `%util > 70%`, `await` высокий; `Innodb_data_pending_*` > 0.
*   **Решение:** быстрее диск (NVMe); увеличить `innodb_io_capacity`; оптимизировать запросы; уменьшить `innodb_flush_neighbors` (SSD).

### CPU на 100%

*   **Причина:** сложные запросы, недостаточно ядер, или `Threads_running` высокий.
*   **Диагностика:** `top` — %CPU; `SHOW PROCESSLIST` — `Threads_running`.
*   **Решение:** оптимизировать запросы (EXPLAIN); увеличить ядра; включить Thread Pool.

## Лучшие практики (Best Practices)

1.  **Working set в RAM:** `innodb_buffer_pool_size` ≥ working set.
2.  **Headroom 30-50%:** планируйте с запасом под пики и рост.
3.  **Мониторьте насыщение** (USE-методология) — алерты до исчерпания.
4.  **Прогнозируйте рост** — замеряйте размер данных ежемесячно.
5.  **Не завышайте `max_connections`** — per-thread память растёт линейно.
6.  **NVMe для write-нагрузки** — redo log и doublewrite чувствительны к IOPS.

## Дополнительная информация

### См. также

*   **[Управление памятью](memory_management.md)** — расчёт буферов.
*   **[Мониторинг](monitoring.md)** — USE-методология, алерты.
*   **[Конфигурация](configuration.md)** — sizing параметров.
*   **[Репликация: capacity planning](replication/capacity_planning.md)** — sizing для репликации.
*   **[Нагрузочное тестирование](performance_testing.md)** — измерение throughput.

### Внешние ресурсы

*   [MariaDB Capacity Planning](https://mariadb.com/kb/en/capacity-planning/)
*   [MariaDB InnoDB System Variables](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-system-variables)
*   [USE Method](http://www.brendangregg.com/usemethod.html)
