# Планирование ресурсов репликации MariaDB (Capacity Planning)

**Актуально для:** MariaDB 11.4 LTS / 12.3 LTS

## Определения

*   **Capacity Planning** — планирование ресурсов (CPU, RAM, диск, сеть) для репликации с учётом нагрузки и требований к лагу.
*   **Binlog throughput** — объём бинарного лога, генерируемого источником за единицу времени (МБ/час). Основной параметр для sizing диска и сети.
*   **Relay log headroom** — запас места на реплике под relay log при худшем лаге.
*   **RPO (Recovery Point Objective)** — максимально допустимая потеря данных (для асинхронной репликации > 0).
*   **RTO (Recovery Time Objective)** — максимально допустимое время восстановления.
*   **GTID (Global Transaction ID)** — глобальный идентификатор транзакции для позиционирования репликации.
*   **SOURCE_DELAY** — задержка применения транзакций на реплике (в секундах).
*   **slave_parallel_threads** — количество параллельных SQL-потоков на реплике (алиас: `slave_parallel_workers`).
*   **slave_parallel_mode** — режим параллелизма: `optimistic` (рекомендуется), `conservative`, `aggressive`, `minimal`.

## Базовые концепты

### Что планировать

| Ресурс | Что измерять | Формула / правило |
| :--- | :--- | :--- |
| **Диск (binlog на источнике)** | `binlog throughput` | `binlog_МБ/час × binlog_expire_logs_seconds / 3600` |
| **Диск (relay log на реплике)** | `binlog throughput × лаг` | `binlog_МБ/час × max_lag_часов` + запас 20–50% |
| **Сеть** | `binlog throughput` | `binlog_МБ/час / 3600` → Мбит/с × запас 2× |
| **CPU (реплика)** | SQL-поток | Параллельная репликация: `slave_parallel_threads` ≈ ядра CPU |
| **RAM (реплика)** | Buffer pool | Как у источника (для одинаковой производительности применения) |
| **Диск I/O (реплика)** | Write IOPS | Не менее IOPS источника для применения (fsync relay log, запись данных) |

### Архитектура репликации и её влияние на ресурсы

Репликация MariaDB состоит из двух потоков на реплике:
1.  **I/O-поток** — получает события от источника, записывает в relay log. Сетевой и дисковый (запись) боттлнек.
2.  **SQL-поток** — читает relay log, применяет транзакции. CPU- и дисковый (чтение/запись данных, redo log) боттлнек.

При **параллельной репликации** (`slave_parallel_threads > 1`) SQL-поток распараллеливается на несколько worker-потоков. Координатор распределяет транзакции по workers согласно `slave_parallel_mode`:
- `optimistic` — параллельно, откат при конфликте (рекомендуется с MariaDB 10.5+).
- `conservative` — только group commit параллельно.
- `aggressive` — максимальный параллелизм, риск конфликтов.
- `minimal` — только commit параллельно.

**RBR (Row-Based Replication)** генерирует больше binlog, чем SBR (Statement-Based), но детерминистичнее. При массовых UPDATE/DELETE RBR создаёт высокую нагрузку на диск и CPU реплики.

### Измерение binlog throughput

```sql
-- Текущий размер binlog
SHOW BINARY LOGS;
-- Или через GTID
SELECT @@gtid_binlog_pos;

-- Через Performance Schema / мониторинг (mysqld_exporter)
-- mysql_global_status_binlog_bytes_written (счётчик, использовать rate())
```

```bash
# Измерение за период (простой способ)
# Разница размера binlog за час:
ls -l /var/log/mysql/mariadb-bin.000001
# через час
ls -l /var/log/mysql/mariadb-bin.000001

# Более точный способ через mysqlbinlog (размер событий за период)
mysqlbinlog --start-datetime="2026-01-01 10:00:00" --stop-datetime="2026-01-01 11:00:00" \
  /var/log/mysql/mariadb-bin.000001 | wc -c
```

**Рекомендация:** измеряйте в пиковые часы нагрузки (минимум 24 часа, лучше 7 дней) и берите p95/p99 значение для sizing.

### Sizing диска

**Binlog на источнике:**
```
binlog_размер = binlog_МБ/час × binlog_expire_logs_seconds / 3600
```
Пример: 500 МБ/час × 7 дней = 500 × 24 × 7 = 84 ГБ.

**Relay log на реплике:**
```
relay_размер = binlog_МБ/час × max_lag_часов + запас_20-50%
```
Пример: 500 МБ/час × 2 часа (макс. лаг) × 1.5 (запас) = 1.5 ГБ.

> **Примечание:** при отложенной репликации (`SOURCE_DELAY`) relay log растёт на всю величину задержки: `binlog_МБ/час × SOURCE_DELAY / 3600`.

**Рекомендации по размещению:**
- Выносите `log_bin` и `relay_log` на отдельные физические диски/тома от `datadir` — изолирует I/O, упрощает мониторинг и предотвращает остановку сервера при заполнении.
- Используйте NVMe/SSD для binlog и relay log — последовательная запись, но чувствительна к latency при fsync.

### Sizing сети

```
bandwidth_Мбит/с = (binlog_МБ/час / 3600) × 8 × 2 (запас)
```
Пример: 500 МБ/час / 3600 × 8 × 2 ≈ 2.2 Мбит/с (минимум). Для высоконагруженных систем — 1 Гбит/с.

**Удалённые реплики (WAN):**
*   Включите сжатие: `slave_compressed_protocol = ON` (снижает трафик ~60-80% на типичных данных).
*   Учитывайте RTT: при RTT > 100 мс лаг растёт из-за TCP window.
*   Для межрегиональных сценариев — асинхронная репликация с полусинхронной (`rpl_semi_sync_source_enabled=ON`) внутри региона.

### Sizing CPU и RAM

*   **CPU**: при параллельной репликации `slave_parallel_threads` ≈ количество ядер. SQL-поток CPU-bound при RBR с массовыми UPDATE/DELETE. При `optimistic` режиме конфликты вызывают откат и повторное выполнение — нагрузка растёт.
*   **RAM**: `innodb_buffer_pool_size` на реплике должен быть не меньше, чем на источнике, чтобы применение не отставало из-за cache misses. Per-thread память (`sort_buffer_size`, `join_buffer_size`, `read_buffer_size`, `read_rnd_buffer_size`, `thread_stack`) × `slave_parallel_threads` добавляется к базе.
*   **Диск I/O**: реплика должна обеспечивать не менее IOPS источника для применения (fsync relay log при `sync_relay_log=1`, запись данных, redo log, doublewrite buffer).

## Практических сценарии

### Сценарий 1: Расчёт ресурсов для production

**Исходные данные:**
*   Binlog throughput: 500 МБ/час (p95 за неделю)
*   Максимальный допустимый лаг: 60 секунд
*   `binlog_expire_logs_seconds`: 7 дней (604800)
*   Отложенная реплика: 1 час (3600 сек)
*   Топология: 1 источник, 2 реплики (одна синхронная, одна отложенная)

**Расчёт:**
```
Binlog (источник): 500 × 24 × 7 = 84 ГБ → с запасом 50% = 126 ГБ
Relay log (обычная реплика): 500 × (60/3600) × 1.5 ≈ 12.5 ГБ
Relay log (отложенная реплика): 500 × 1 × 1.5 = 750 ГБ
Сеть: 500/3600 × 8 × 2 ≈ 2.2 Мбит/с (минимум), рекомендуется 1 Гбит/с
CPU: 8 ядер (slave_parallel_threads = 8)
RAM: как у источника (например, 64 ГБ buffer pool + 4 ГБ OS + per-thread)
```

### Сценарий 2: Мониторинг заполнения диска

```sql
-- Текущий размер binlog на источнике
SHOW BINARY LOGS;

-- Relay log на реплике
SHOW REPLICA STATUS\G
-- Relay_Log_Space (размер в байтах)
```

```bash
# Алерты на заполнение диска (Prometheus + node_exporter)
# node_filesystem_avail_bytes{mountpoint="/var/log/mysql"} / node_filesystem_size_bytes{mountpoint="/var/log/mysql"} < 0.2

# Алерты на лаг (mysqld_exporter)
# mysql_slave_status_seconds_behind_master > 30 (warning), > 60 (critical)
```

### Сценарий 3: Планирование роста

```
Проекция на год:
Текущий binlog: 500 МБ/час
Рост нагрузки: 20%/год
Через год: 600 МБ/час
Binlog (7 дней): 600 × 24 × 7 = 100 ГБ
Relay log (отложенная, 1ч): 600 × 1.5 = 900 ГБ
```

Закладывайте запас 30–50% на рост. Пересчитывайте ежеквартально.

### Сценарий 4: Оценка влияния параллельной репликации

```sql
-- Текущий параллелизм
SHOW VARIABLES LIKE 'slave_parallel_threads';
SHOW VARIABLES LIKE 'slave_parallel_mode';

-- Если SQL-поток не успевает (лаг растёт):
-- 1. Проверьте CPU: top, mpstat -P ALL 1
-- 2. Проверьте I/O: iostat -x 1
-- 3. Увеличьте slave_parallel_threads до числа ядер
SET GLOBAL slave_parallel_threads = 8;
SET GLOBAL slave_parallel_mode = 'optimistic';

-- Для постоянного эффекта — в конфиге:
# [mariadb]
# slave_parallel_threads = 8
# slave_parallel_mode = optimistic
```

**Влияние на ресурсы:**
- `slave_parallel_threads = N` увеличивает per-thread память: `N × (sort_buffer_size + join_buffer_size + read_buffer_size + read_rnd_buffer_size + thread_stack)`.
- При `optimistic` режиме конфликты увеличивают CPU. Мониторьте `mysql_slave_status_slave_retried_transactions`.

### Сценарий 5: RPO/RTO для репликации

| Топология | RPO | RTO |
| :--- | :--- | :--- |
| Асинхронная | > 0 (до последней неприменённой транзакции) | 30–60 сек (ручной/автоматический failover) |
| Полусинхронная (`rpl_semi_sync_source_enabled=ON`) | ~0 (последняя транзакция подтверждена хотя бы одной репликой) | 30–60 сек |
| Galera Cluster | 0 (синхронная, multi-master) | 0 (автоматический failover) |

**Для RPO ~0 с асинхронной репликацией** используйте `binlog_expire_logs_seconds > max_lag + 1 день` и регулярные бэкапы для PITR.

### Сценарий 6: Sizing для мульти-источника (Multi-Source Replication)

При репликации от нескольких источников на одну реплику:
```
Total relay log = Σ (binlog_МБ/час_источника_i × max_lag_i) + запас
slave_parallel_threads = ядер CPU (общий пул для всех источников)
```
Каждый источник имеет свой канал (`CHANNEL`), настройки `SOURCE_DELAY`, `slave_parallel_threads` применяются глобально.

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Binlog заполнил диск на источнике | `binlog_expire_logs_seconds` слишком велик или диск мал | Пересчитайте sizing; увеличьте диск или сократите срок хранения; `PURGE BINARY LOGS BEFORE` (только если реплики прочитали) |
| Relay log заполнил диск на реплике | Лаг реплики растёт или `relay_log_purge = OFF` | Увеличьте диск; проверьте лаг; включите `relay_log_purge = ON`; настройте `relay_log_space_limit` |
| Лаг растёт после роста нагрузки | CPU/RAM реплики недостаточны | Увеличьте `slave_parallel_threads`, CPU, RAM; проверьте `optimistic` конфликты |
| Сеть — узкое место | Bandwidth < binlog throughput | Увеличьте bandwidth; включите `slave_compressed_protocol = ON` |
| Реплика отстаёт после перезапуска | Re-seeding занимает время | Планируйте окно; используйте `mariadb-backup` для быстрого клонирования |
| `Error 1236: master has purged binary logs` | Реплика слишком долго была отключена; источник удалил binlog | Пересоздание снимка (re-seeding). Увеличьте `binlog_expire_logs_seconds` |
| Параллельная репликация не помогает | Конфликты в `optimistic` режиме или `slave_parallel_mode = conservative` | Проверьте `slave_retried_transactions`; рассмотрите `aggressive` или sharding по схемам |

**Диагностика лага:**
```sql
-- Точный лаг через GTID (а не Seconds_Behind_Source)
-- На источнике:
SELECT @@gtid_binlog_pos;
-- На реплике:
SELECT @@gtid_slave_pos;
-- Разница = не применённые транзакции

-- Альтернатива: pt-heartbeat (истинный лаг приложения)
```

## Best Practices

1.  **Измерьте binlog throughput** перед sizing — не оценивайте на глаз. Замеряйте в пик нагрузки минимум 24ч.
2.  **Закладывайте запас 20–50%** на рост нагрузки и пиковые нагрузки.
3.  **Отдельный диск для binlog и relay log** — изолирует I/O и упрощает мониторинг.
4.  **Мониторьте заполнение диска** — алерт при < 20% свободного места на томах binlog/relay log.
5.  **Параллельная репликация** — `slave_parallel_threads` ≈ ядра CPU на реплике, `slave_parallel_mode = optimistic`.
6.  **`relay_log_recovery = ON`** на всех репликах (crash-safe).
7.  **`binlog_expire_logs_seconds > max_lag + 1 день`** — для PITR и предотвращения Error 1236.
8.  **Периодический пересчёт** — при росте нагрузки пересчитывайте sizing ежеквартально.
9.  **Тестируйте failover** — RTO измеряется практикой, а не теорией.
10. **Сжатие для WAN** — `slave_compressed_protocol = ON` для межрегиональных реплик.

## Дополнительная информация

### См. также

- **[Обзор репликации](./overview.md)** — конфигурация и параметры, параллельная репликация.
- **[Управление Relay Log](./relay_log_management.md)** — sizing relay log, `relay_log_space_limit`, purge.
- **[Мониторинг репликации](./monitoring.md)** — метрики, алерты, mysqld_exporter, GTID-лаг.
- **[Отложенная репликация](./delayed_replication.md)** — сценарии использования, влияние на ресурсы.
- **[Диагностика и Troubleshooting](./troubleshooting.md)** — анализ лага, ошибки репликации.
- **[Capacity Planning одиночного инстанса MariaDB](../capacity_planning.md)** — общая методология CPU/RAM/диск.
- **[Конфигурация MariaDB](../configuration.md)** — параметры сервера.
- **[Бенчмаркинг СУБД](../../Concepts/benchmarking.md)** — методика нагрузочного тестирования.

### Внешние ресурсы

- [MariaDB Capacity Planning](https://mariadb.com/kb/en/capacity-planning/)
- [MariaDB Replication Overview](https://mariadb.com/kb/en/replication-overview/)
- [MariaDB Parallel Replication](https://mariadb.com/kb/en/parallel-replication/)
- [MariaDB Semi-Synchronous Replication](https://mariadb.com/kb/en/semi-synchronous-replication/)
- [USE Method](http://www.brendangregg.com/usemethod.html)