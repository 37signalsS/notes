# Мониторинг MariaDB: Prometheus, Thread Pool и Galera

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS, mysqld_exporter 0.20.0+

## Определения

*   **`mysqld_exporter`** — основной инструмент для сбора метрик MariaDB/MySQL в формате Prometheus. Работет по модели Pull: Prometheus.periodically опрашивает exporter, который возвращает текущие значения счетчиков (counters), гаугов (gauges) и гистограмм. Экспортер поддерживает множество коллекторов для различных подсистем СУБД.
*   **Flow Control (Контроль потока)** — механизм Galera Cluster, приостанавливающий запись на всех узлах, если один из узлов не успевает применять транзакции (Receive Queue переполнена). При активном Flow Control все записи в кластере замедляются до скорости самого медленного узла.
*   **Thread Pool (Пул потоков)** — механизм масштабирования соединений, позволяющий эффективно обрабатывать тысячи сессий через ограниченное количество рабочих потоков. В MariaDB реализован нативно (в отличие от MySQL Enterprise). Потоки переиспользуются: завершив обработку одного запроса, поток берет следующий из очереди, а не завершается.
*   **Performance Schema** — подсистема MariaDB для инструментирования (instrumentation) внутренних событий СУБД. Отслеживает потребление памяти, locks, I/O, соединения и SQL-запросы на уровне функций. Данные хранятся в таблицах `performance_schema.*` и доступны через SQL.
*   **`sys` Schema** — набор представлений и функций поверх Performance Schema, предоставляющий удобные агрегированные отчеты. Ключевые представления: `sys.memory_global_by_current_bytes`, `sys.host_summary`, `sys.statement_analysis`.
*   **InnoDB Metrics** — счетчики движка InnoDB, доступные через `SHOW GLOBAL STATUS` ( префикс `Innodb_*`) и таблицу `information_schema.innodb_metrics`. Содержат детальную статистику: buffer pool, транзакции, блокировки, I/O, adaptive hash index.
*   **Slow Query Log** — лог-файл, в который записываются запросы, превышающие порог `long_query_time`. Содержит текст запроса, время выполнения, количество строк, план выполнения. Является основным инструментом анализа производительности SQL.
*   **Replication Lag (Лаг репликации)** — задержка применения транзакций на реплике относительно источника (Source). Измеряется в секундах (`Seconds_Behind_Source`) или в позиции GTID. Критичен для кластеров: лаг > 60 секунд требует вмешательства.

## Базовые концепции

### Специфика MariaDB в mysqld_exporter

Хотя `mysqld_exporter` универсален, MariaDB имеет уникальные системные переменные и статусы, которые требуют включения специфических коллекторов:

1.  **Thread Pool Metrics:** Требуют включения `collect.info_schema.processlist` или специфических переменных статуса через `collect.global_status`.
2.  **Galera Metrics:** Доступны через `collect.global_status` (префикс `wsrep_*`). Для полного набора также включите `collect.engine_innodb_status=true`.
3.  **RocksDB/MyRocks:** Если используется движок MyRocks, отключите ненужные коллекторы InnoDB: `--no-collect.engine_innodb_status` (если InnoDB не используется) и `--no-collect.perf_schema.tablelocks` (если не нужна диагностика блокировок MyRocks). Для MyRocks метрики доступны через `SHOW ENGINE ROCKSDB STATUS` и собираются через `collect.engine_innodb_status` только если InnoDB активен.
4.  **Aria Engine:** Метрики Aria доступны через `collect.global_status` (префикс `Aria_*`). Ключевые: `Aria_pagecache_buffers`, `Aria_pagecache_read_requests`.
5.  **Performance Schema:** Для глубокой диагностики включите `collect.perf_schema.tableiowaits` (статус InnoDB) и `collect.perf_schema.tablelocks` (блокировки).

### Источники данных для мониторинга

MariaDB предоставляет несколько уровней метрик, каждый из которых решает свою задачу:

| Источник | Тип данных | Назначение | Примеры метрик |
| :--- | :--- | :--- | :--- |
| **SHOW GLOBAL STATUS** | Счетчики (counters) и значения (gauges) | Общая картина: соединения, трафик, буферы | `Threads_connected`, `Queries`, `Innodb_buffer_pool_read_requests` |
| **SHOW GLOBAL VARIABLES** | Конфигурация | Проверка текущих настроек | `innodb_buffer_pool_size`, `max_connections` |
| **Performance Schema** | События, таймеры, счетчики | Глубокая диагностика: locks, I/O, memory | `events_statements_summary_by_digest`, `memory_global_by_current_bytes` |
| **`sys` Schema** | Агрегированные представления | Удобные отчеты без написания сложных запросов | `sys.memory_global_by_current_bytes`, `sys.host_summary` |
| **SHOW ENGINE INNODB STATUS** | Текстовый отчет | Диагностика транзакций, deadlocks, buffer pool | Секции `TRANSACTIONS`, `LATEST DETECTED DEADLOCK` |
| **Error Log** | Логи | Критические ошибки, crash, corruption | `journalctl -u mariadb` |
| **Process Metrics** | Метрики ОС и процесса | Потребление RAM/CPU, файловые дескрипторы | `process_resident_memory_bytes`, `process_cpu_seconds_total` (node_exporter) |
| **Slow Query Log** | SQL-запросы | Анализ тяжелых запросов | Запросы > `long_query_time` |

### Философия мониторинга: USE-method

Для эффективного мониторинга MariaDB используйте методологию **USE** (Utilization, Saturation, Errors):

- **Utilization (Утилизация):** Какая доля ресурса занята?
  - CPU: `Threads_running` vs количество ядер
  - Память: `Innodb_buffer_pool_pages_total` * page_size vs `innodb_buffer_pool_size`
  - Диск: `Innodb_data_pending_reads` + `Innodb_data_pending_writes`

- **Saturation (Насыщение):** Сколько работы скопилось в очереди?
  - `Threads_connected` vs `max_connections`
  - `wsrep_local_recv_queue` (Galera)
  - `Created_tmp_disk_tables` (временные таблицы на диске)

- **Errors (Ошибки):** Сколько ошибок происходит?
  - `Innodb_buffer_pool_wait_free` (не хватает страниц в buffer pool)
  - `Aborted_clients` / `Aborted_connects`
  - `Slow_queries` (запросы > `long_query_time`)

---

## Практические сценарии

### 1. Создание пользователя для мониторинга

Для любого инструмента мониторинга требуется пользователь с минимально необходимыми правами:

```sql
-- Создание пользователя с лимитом соединений
CREATE USER 'monitor'@'localhost' IDENTIFIED BY 'YOUR_SECURE_PASSWORD'
  WITH MAX_USER_CONNECTIONS 3;

-- Базовые права для сбора метрик
GRANT REPLICATION CLIENT, PROCESS, SHOW DATABASES, SHOW VIEW ON *.* TO 'monitor'@'localhost';
GRANT SELECT ON performance_schema.* TO 'monitor'@'localhost';
GRANT SELECT ON information_schema.* TO 'monitor'@'localhost';
GRANT SELECT ON sys.* TO 'monitor'@'localhost';

-- Для MariaDB 10.11+: REPLICATION CLIENT покрывает мониторинг репликации

FLUSH PRIVILEGES;
```

**Проверка прав:**
```bash
mysql -u monitor -p -e "SHOW GLOBAL STATUS LIKE 'Threads_connected';"
# → Threads_connected    N
```

**Безопасное хранение учетных данных:**

Минимальный вариант для тестовых сред — `.my.cnf`:

```bash
cat <<EOF > /etc/mysqld_exporter/.my.cnf
[client]
user=monitor
password=YOUR_SECURE_PASSWORD
EOF
chown mysql:mysql /etc/mysqld_exporter/.my.cnf
chmod 600 /etc/mysqld_exporter/.my.cnf
```

Для production Recommended использовать:
- **HashiCorp Vault** — динамические credentials с автоматической ротацией.
- **Docker secrets** — для контейнеризированных развертываний (`docker secret create mariodb-monitor .my.cnf`).
- **Kubernetes secrets** — для K8s (см. `secret` типа `Opaque` с ключом `.my.cnf`).
- **Ansible Vault** — для инфраструктуры как код (IaC).

> **Важно:** никогда не передавайте пароль через аргументы командной строки (`--password`), он попадет в `ps aux` и логи.

### 2. Полная настройка mysqld_exporter для MariaDB

Для получения полной картины состояния в 2026 году Recommended запускать экспортер **v0.20.0+** со следующими флагами:

```bash
mysqld_exporter \
  --config.my-cnf=/etc/mysqld_exporter/.my.cnf \
  --collect.global_status \
  --collect.global_variables \
  --collect.info_schema.processlist \
  --collect.info_schema.query_response_time \
  --collect.info_schema.innodb_metrics \
  --collect.perf_schema.tableiowaits \
  --collect.perf_schema.tablelocks \
  --collect.engine_innodb_status=true \
  --web.listen-address=:9104
```

**Multi-target режим (альтернатива):** вместо отдельного экземпляра на узел можно использовать один `mysqld_exporter` с флагом `--config.addr` и параметром `--param_target` для мониторинга нескольких инстансов через один процесс. Пример запуска:

```bash
mysqld_exporter \
  --config.my-cnf=/etc/mysqld_exporter/.my.cnf \
  --web.listen-address=:9104 \
  --config.addr=unix:///run/mysqld/mysqld.sock
```

При использовании multi-target в Prometheus добавьте `__param_target`:

```yaml
scrape_configs:
  - job_name: 'mariadb'
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: localhost:9104
```

**Параметры:**
- `--config.my-cnf`: путь к файлу с учетными данными (не передавайте пароль в аргументах командной строки).
- `--collect.global_status`: все счетчики `SHOW GLOBAL STATUS` (включая Galera `wsrep_*` и Aria `Aria_*`).
- `--collect.info_schema.processlist`: метрики по соединениям (Thread Pool, Sleep/Active).
- `--collect.info_schema.innodb_metrics`: детальные счетчики InnoDB из `information_schema.innodb_metrics`.
- `--collect.engine_innodb_status`: сбор текстового отчета `SHOW ENGINE INNODB STATUS` (транзакции, deadlocks, purge).
- `--collect.info_schema.query_response_time`: распределение времени выполнения запросов. **Важно:** для работы требуется установить плагин `INSTALL SONAME 'query_response_time'` и включить `query_response_time_stats=ON` (по умолчанию OFF).
- `--collect.perf_schema.tableiowaits`: время ожидания I/O по таблицам.
- `--web.listen-address`: порт для scrape Prometheus (по умолчанию 9104).

**Включение Query Response Time (если используется):**
```sql
-- Установка плагина (требуется SUPER)
INSTALL SONAME 'query_response_time';

-- Включение сбора статистики (можно в my.cnf)
SET GLOBAL query_response_time_stats = ON;
```

**Проверка работоспособности:**
```bash
curl -s http://localhost:9104/metrics | grep -c "mysql_global_status"
# → > 100 (ожидается более 100 метрик)
```

### 3. Настройка Prometheus для MariaDB

#### Конфигурация scrape

Добавьте в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'mariadb'
    scrape_interval: 15s
    static_configs:
      - targets:
          - 'db-node-01:9104'
          - 'db-node-02:9104'
          - 'db-node-03:9104'
    metrics_path: /metrics
```

#### Рекомендуемые правила алертинга

Создайте файл `mariadb_alerts.yml`:

```yaml
groups:
  - name: mariadb_alerts
    rules:
      # === Соединения ===
      - alert: MariaDBTooManyConnections
        expr: mysql_global_status_threads_connected / mysql_global_variables_max_connections * 100 > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "MariaDB: >80% соединений занято ({{ $value | humanize }}%)"

      - alert: MariaDBConnectionStorm
        expr: rate(mysql_global_status_threads_created[5m]) > 10
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "MariaDB: высокий rate создания потоков ({{ $value }}/s)"

      # === Buffer Pool ===
      - alert: MariaDBBufferPoolHitRateLow
        expr: |
          1 - (
            mysql_global_status_innodb_buffer_pool_reads
            /
            mysql_global_status_innodb_buffer_pool_read_requests
          ) < 0.99
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "MariaDB: Buffer Pool Hit Rate < 99% ({{ $value | humanizePercentage }})"

      - alert: MariaDBBufferPoolWaitFree
        expr: rate(mysql_global_status_innodb_buffer_pool_wait_free[5m]) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "MariaDB: Buffer Pool wait_free > 0 (нехватка страниц)"

      # === Память ===
      - alert: MariaDBSwapUsage
        expr: mysql_global_status_swap > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "MariaDB: swap используется ({{ $value }} bytes)"

      - alert: MariaDBHighRSS
        expr: |
          process_resident_memory_bytes{job="mariadb"} / 1024 / 1024 / 1024 > 0.8 * (
            mysql_global_variables_innodb_buffer_pool_size
            + mysql_global_variables_key_buffer_size
            + mysql_global_variables_aria_pagecache_size
          ) / 1024 / 1024 / 1024
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "MariaDB: RSS процесса превышает 80% от суммарного размера буферов ({{ $value | humanize }}GB)"

      # === Репликация ===
      - alert: MariaDBReplicationLag
        expr: mysql_slave_status_seconds_behind_master > 60
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "MariaDB: лаг репликации > 60с ({{ $value }}s)"

      - alert: MariaDBReplicationStopped
        expr: mysql_slave_status_slave_io_running == 0 or mysql_slave_status_slave_sql_running == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "MariaDB: репликация остановлена"

      # === Ошибки ===
      - alert: MariaDBAbortedConnections
        expr: rate(mysql_global_status_aborted_connects[5m]) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "MariaDB: высокий rate aborted connections ({{ $value }}/s)"

      - alert: MariaDBSlowQueries
        expr: rate(mysql_global_status_slow_queries[5m]) > 1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "MariaDB: > 1 slow query/сек ({{ $value }}/s)"

      # === Galera ===
      - alert: GaleraClusterSizeMismatch
        expr: mysql_global_status_wsrep_cluster_size != 3
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Galera: размер кластера {{ $value }} (ожидается 3)"

      - alert: GaleraFlowControlActive
        expr: rate(mysql_global_status_wsrep_flow_control_paused[1m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Galera: Flow Control активен"

      - alert: GaleraNodeNotSynced
        expr: mysql_global_status_wsrep_local_state != 4
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Galera: узел не в состоянии Synced (state={{ $value }})"
```

### 4. Мониторинг Thread Pool

Thread Pool в MariaDB критичен для предотвращения "Connection Storms". Ключевые метрики для алертинга:

| Метрика | Описание | Критическое значение |
| :--- | :--- | :--- |
| `mysql_global_status_threadpool_threads` | Количество активных потоков в пуле. | Близко к `thread_pool_max_threads` |
| `mysql_global_status_threadpool_idle_threads` | Потоки, ожидающие работу. | Низкое значение при высоком CPU |
| `mysql_global_status_threadpool_waits` | Количество раз, когда сессии пришлось ждать свободного потока. | Постоянный рост > 0 |

**Prometheus Query (Утилизация пула):**
```promql
mysql_global_status_threadpool_threads / mysql_global_variables_thread_pool_max_threads * 100
```

**Prometheus Query (Wait Rate):**
```promql
rate(mysql_global_status_threadpool_waits[5m])
```

**SQL-диагностика:**
```sql
-- Текущее состояние пула
SHOW STATUS LIKE 'Threadpool_%';

-- Сравнение активных vs idle потоков
SELECT
  VARIABLE_VALUE AS active
FROM performance_schema.global_status
WHERE VARIABLE_NAME = 'Threadpool_threads';

SELECT
  VARIABLE_VALUE AS idle
FROM performance_schema.global_status
WHERE VARIABLE_NAME = 'Threadpool_idle_threads';
```

### 5. Мониторинг состояния Galera Cluster

Для SRE критически важно отслеживать не только "жив" ли кластер, но и не является ли один из узлов "тормозом" для всей системы.

#### А) Flow Control (Паузы записи)
Если `wsrep_flow_control_paused` > 0, значит кластер стоит.
*   **Метрика:** `mysql_global_status_wsrep_flow_control_paused`
*   **Алерт:** `rate(mysql_global_status_wsrep_flow_control_paused[1m]) > 0.1`

#### Б) Очереди (Queues)
*   **Send Queue (`wsrep_local_send_queue`):** Если растет — проблема с сетью или пропускной способностью исходящего канала.
*   **Receive Queue (`wsrep_local_recv_queue`):** Если растет — узел не успевает применять (apply) транзакции к данным. Часто вызвано медленными дисками или отсутствием PK.

#### В) Размер и статус
*   `mysql_global_status_wsrep_cluster_size` — количество узлов в Primary компоненте.
*   `mysql_global_status_wsrep_local_state` — должен быть равен 4 (`Synced`).

**SQL-проверки Galera:**
```sql
-- Полная проверка здоровья кластера
SELECT
  VARIABLE_NAME, VARIABLE_VALUE
FROM performance_schema.global_status
WHERE VARIABLE_NAME IN (
  'wsrep_cluster_size',
  'wsrep_local_state_comment',
  'wsrep_ready',
  'wsrep_cluster_status',
  'wsrep_flow_control_paused',
  'wsrep_local_recv_queue_avg',
  'wsrep_local_send_queue_avg'
);
```

> Подробные примеры алертинга для Galera, диагностика Split-Brain и SST-ошибок см. в **[Отказоустойчивость MariaDB](high_availability.md)**.

### 6. Мониторинг InnoDB: Buffer Pool, транзакции, I/O

InnoDB — основной движок MariaDB. Его метрики отражают здоровье всей СУБД.

**Buffer Pool Hit Rate (цель > 99%):**
```sql
SELECT
  ROUND(
    (1 - (
      (SELECT VARIABLE_VALUE FROM performance_schema.global_status
       WHERE VARIABLE_NAME = 'Innodb_buffer_pool_reads') /
      (SELECT VARIABLE_VALUE FROM performance_schema.global_status
       WHERE VARIABLE_NAME = 'Innodb_buffer_pool_read_requests')
    )) * 100, 2
  ) AS hit_ratio_percent;
```

**PromQL:**
```promql
1 - (
  mysql_global_status_innodb_buffer_pool_reads
  /
  mysql_global_status_innodb_buffer_pool_read_requests
)
```

**InnoDB I/O и транзакции:**
```sql
-- Проверка I/O pending (ожидание диска)
SHOW GLOBAL STATUS LIKE 'Innodb_data_pending%';
-- Innodb_data_pending_reads  = 0 (норма)
-- Innodb_data_pending_writes = 0 (норма)

-- Среднее время блокировки строки
SHOW GLOBAL STATUS LIKE 'Innodb_row_lock_time_avg';
-- Если растет — проблема с транзакциями

-- Deadlocks (количество с момента старта)
SHOW GLOBAL STATUS LIKE 'Innodb_deadlocks';
```

**PromQL для алертов:**
```promql
# I/O wait превышен
rate(mysql_global_status_innodb_data_reads[5m]) > 1000

# Среднее время row lock > 500ms
mysql_global_status_innodb_row_lock_time_avg > 500
```

### 7. Анализ медленных запросов (Slow Query Log)

Конфигурация и анализ slow query log:

```ini
# В my.cnf
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow.log
long_query_time = 0.5    # 500ms — рекомендуемый порог для production
log_slow_extra = ON       # Дополнительная информация (MariaDB 10.5+)
log_slow_admin_statements = ON  # Логировать медленные DDL
log_queries_not_using_indexes = ON  # Логировать запросы без индексов
```

**Анализ через `mariadb-dumpslow` (встроенный инструмент):**
```bash
# Топ-10 запросов по общему времени
mariadb-dumpslow -s t /var/log/mysql/slow.log | head -10

# Топ-10 запросов по количеству вызовов
mariadb-dumpslow -s c /var/log/mysql/slow.log | head -10
```

**Анализ через Performance Schema (без лог-файла):**
```sql
-- Топ-10 запросов по общему времени выполнения
SELECT
  DIGEST_TEXT AS query,
  COUNT_STAR AS exec_count,
  ROUND(SUM_TIMER_WAIT / 1e12, 2) AS total_time_sec,
  ROUND(AVG_TIMER_WAIT / 1e12, 4) AS avg_time_sec,
  SUM_ROWS_EXAMINED AS rows_examined,
  SUM_ROWS_SENT AS rows_sent
FROM performance_schema.events_statements_summary_by_digest
ORDER BY SUM_TIMER_WAIT DESC
LIMIT 10;
```

**PromQL:**
```promql
# Количество slow queries в секунду
rate(mysql_global_status_slow_queries[5m])
```

### 8. Мониторинг репликации (Source-Replica)

Для классической асинхронной репликации MariaDB:

```sql
-- Статус реплики (выполняется на Replica)
SHOW REPLICA STATUS\G

-- Ключевые поля:
-- Source_IO_Running: Yes
-- Source_SQL_Running: Yes
-- Seconds_Behind_Source: 0    (лаг в секундах)
-- Last_IO_Error: (пусто)
-- Last_SQL_Error: (пусто)
```

**Prometheus метрики:**
| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `mysql_slave_status_seconds_behind_master` | Лаг репликации в секундах | > 60 |
| `mysql_slave_status_slave_io_running` | Статус I/O потока (1=running) | == 0 |
| `mysql_slave_status_slave_sql_running` | Статус SQL потока (1=running) | == 0 |
| `mysql_slave_status_slave_retried_transactions` | Количество повторных попыток | Рост > 0 |

**PromQL:**
```promql
# Лаг репликации > 60 секунд
mysql_slave_status_seconds_behind_master > 60

# Репликация остановлена
mysql_slave_status_slave_io_running == 0 or mysql_slave_status_slave_sql_running == 0
```

**SQL-мониторинг на Source:**
```sql
-- Проверка потоков репликации на Source
SHOW MASTER STATUS;
SHOW SLAVE HOSTS;
```

### 9. Диагностика через sys Schema

`sys` schema предоставляет удобные представления для быстрой диагностики:

```sql
-- Память: топ потребителей
SELECT * FROM sys.memory_global_by_current_bytes
ORDER BY current_alloc DESC
LIMIT 10;

-- Топ SQL-запросов по времени
SELECT * FROM sys.statement_analysis
ORDER BY total_latency DESC
LIMIT 10;

-- Активные соединения и их потребление памяти
SELECT * FROM sys.session
WHERE command != 'Sleep';

-- I/O по файлам (какие файлы больше всего нагружены)
SELECT * FROM sys.io_global_by_file_by_bytes
ORDER BY total_read + total_write DESC
LIMIT 10;

-- Распределение памяти по хостам
SELECT * FROM sys.memory_global_total;
```

### 9.1. Percona Monitoring and Management (PMM)

PMM — платформа мониторинга от Percona (Grafana + Prometheus + ClickHouse + экспортеры). Поддерживает MariaDB через `pmm-admin`. Альтернатива самостоятельной сборке Prometheus + mysqld_exporter.

**Установка клиента:**
```bash
# Debian/Ubuntu
curl -fsSL https://www.percona.com/get/pmm | bash

# Или пакет
sudo apt-get install pmm2-client
```

**Регистрация и добавление MariaDB:**
```bash
# Подключение к PMM-серверу
pmm-admin config --server-url=https://admin:admin@pmm.example.com

# Добавление MariaDB (через Performance Schema — рекомендуется)
pmm-admin add mysql:metrics \
  --username=monitor \
  --password=YOUR_SECURE_PASSWORD \
  --query-source=perfschema

# Добавление QAN (Query Analytics) из slow query log
pmm-admin add mysql:queries \
  --username=monitor \
  --password=YOUR_SECURE_PASSWORD \
  --query-source=slowlog

# Проверка статуса
pmm-admin list
pmm-admin status
```

**Параметры `--query-source`:**
| Значение | Источник | Назначение |
| :--- | :--- | :--- |
| `perfschema` | Performance Schema | Метрики и QAN (рекомендуется) |
| `slowlog` | Slow Query Log | QAN (анализ запросов) |
| `none` | — | Только метрики |

**Примечания:**
*   Для MariaDB требуется пользователь с `REPLICATION CLIENT`, `PROCESS`, `SELECT` на `performance_schema` (см. сценарий 1).
*   PMM не поддерживает `CALL sys.diagnostics()` (это MySQL-специфичная процедура, в MariaDB sys schema её нет).
*   QAN показывает топ запросов по времени, числу вызовов, просмотренным строкам — аналог `pt-query-digest` с веб-интерфейсом.
*   Подробнее о PMM для MySQL: **[MySQL: Мониторинг](../MySQL/monitoring.md)**.

### 9.2. Zabbix

Zabbix — альтернатива Prometheus для организаций с существующей Zabbix-инфраструктурой.

**Шаблоны:**
*   Официальный шаблон: `MariaDB by Zabbix agent` (Zabbix 6.0+).
*   Community: `Percona MySQL Templates` (работают с MariaDB).

**Настройка (Zabbix agent 2):**
```ini
# /etc/zabbix/zabbix_agent2.conf
Plugins.MariaDB.Sessions.MariaDB.uri=tcp://127.0.0.1:3306
Plugins.MariaDB.Sessions.MariaDB.User=monitor
Plugins.MariaDB.Sessions.MariaDB.Password=YOUR_SECURE_PASSWORD
```

**Ключевые метрики Zabbix:**
*   `mysql.status[Threads_connected]` — соединения.
*   `mysql.status[Innodb_buffer_pool_read_requests]` — buffer pool.
*   `mysql.status[Seconds_Behind_Master]` — лаг репликации.
*   `mysql.status[wsrep_cluster_size]` — размер Galera-кластера.

**Триггеры (примеры):**
*   `Threads_connected / max_connections > 80%` — Warning.
*   `Buffer pool hit rate < 99%` — Warning.
*   `Replication lag > 60s` — High.
*   `wsrep_cluster_size < N` — Disaster.

**Сравнение подходов:**
| Подход | Когда использовать |
| :--- | :--- |
| **Prometheus + mysqld_exporter** | Cloud-native, гибкие PromQL, алерты в Alertmanager |
| **PMM** | Готовая платформа с QAN, минимум настройки |
| **Zabbix** | Существующая Zabbix-инфраструктура, единый стек мониторинга |

### 10. Настройка Grafana Dashboard

Рекомендуемые панели для дашборда MariaDB:

| Панель | Тип | PromQL / Метрика | Описание |
| :--- | :--- | :--- | :--- |
| **Connections** | Time Series | `mysql_global_status_threads_connected` | Активные соединения |
| **QPS** | Rate | `rate(mysql_global_status_queries[5m])` | Запросов в секунду |
| **Buffer Pool Hit Rate** | Gauge | `(1 - reads/requests) * 100` | Эффективность кеша (цель > 99%) |
| **InnoDB Row Operations** | Time Series | `rate(mysql_global_status_innodb_rows_read[5m])`, `rate(mysql_global_status_innodb_rows_inserted[5m])` | Read/Insert/Update/Delete |
| **Replication Lag** | Time Series | `mysql_slave_status_seconds_behind_master` | Лаг реплики |
| **Galera Cluster Size** | Stat | `mysql_global_status_wsrep_cluster_size` | Количество узлов |
| **Galera Flow Control** | Time Series | `rate(mysql_global_status_wsrep_flow_control_paused[5m])` | Паузы записи |
| **Slow Queries** | Rate | `rate(mysql_global_status_slow_queries[5m])` | Медленные запросы/сек |
| **Aborted Connections** | Rate | `rate(mysql_global_status_aborted_connects[5m])` | Ошибки подключения |
| **Thread Pool Utilization** | Gauge | `threads / max_threads * 100` | Утилизация пула потоков |
| **Process RSS** | Gauge | `process_resident_memory_bytes / 1024 / 1024 / 1024` | Потребление RAM процессом mysqld (GB) |

---

## Лучшие практики (Best Practices)

- **Принцип минимальных привилегий:** пользователь `monitor` должен иметь только права `REPLICATION CLIENT`, `PROCESS`, `SELECT` на `performance_schema`, `information_schema`, `sys`. Никаких прав на запись.
- **Безопасное хранение учетных данных:** избегайте хранения паролей в `.my.cnf` в production. Используйте `ansible-vault`, HashiCorp Vault, Docker secrets или Kubernetes secrets. При использовании `.my.cnf` ограничьте права `600` и владельца `mysql:mysql`.
- **Шифрование соединения:** для защиты метрик от перехвата настройте TLS на стороне MariaDB и используйте `--config.ssl-ca`, `--config.ssl-cert`, `--config.ssl-key` в `mysqld_exporter` (поддерживается в v0.20.0+).
- **Ограничение количества коллекторов:** отключайте ненужные коллекторы (`--no-collect.*`). Каждый активный коллектор выполняет SQL-запросы к БД; при высокой нагрузке это может добавить задержку.
- **Scrape interval:** для production используйте `15s` или `30s`. Интервал `< 10s` избыточен для большинства метрик СУБД и создает лишнюю нагрузку.
- **Recording rules:** вынесите сложные PromQL-выражения (Buffer Pool Hit Rate, Thread Pool Utilization) в recording rules, чтобы снизить нагрузку на Prometheus и ускорить алерты.
- **Flapping protection:** всегда используйте `for: >= 2m` в алертах, чтобы избежать ложных срабатываний при кратковременных скачках метрик.
- **Дашборд по методологии USE:** организуйте Grafana-панели по принципу Utilization → Saturation → Errors. Это позволяет быстро локализовать проблему (не хватает ресурсов, очередь или ошибки).
- **Регулярный аудит прав:** раз в квартал проверяйте права пользователя `monitor` и ротируйте пароль. Убедитесь, что учетные данные не попали в логи или репозитории.
- **Connection Pooling:** для приложений с большим количеством коротких соединений используйте ProxySQL или MaxScale вместо увеличения `max_connections`. Это снижает нагрузку на Thread Pool и уменьшает латентность.

## Особенности и ограничения (Edge Cases)

- **Performance Schema отключен:** если подсистема Performance Schema выключена (`performance_schema=OFF`), метрики `events_statements_summary_by_digest`, `memory_global_by_current_bytes` и другие `perf_schema.*` коллекторы `mysqld_exporter` вернут пустые значения или ошибки. Для production Recommended оставлять Performance Schema включенным.
- **Очень большое количество соединений (`> 1000`):** коллектор `collect.info_schema.processlist` выполняет сканирование `information_schema.processlist`, что при высокой нагрузке может вызывать задержки до нескольких секунд. Используйте фильтрацию (`--collect.info_schema.processlist.min_time`) или временно отключайте коллектор при диагностике.
- **Контейнеры и cgroups:** в Docker/Kubernetes метрика `process_resident_memory_bytes` отражает RSS внутри контейнера, а не всей ОС. Для корректного сравнения с `innodb_buffer_pool_size` используйте лимит cgroup (`container_spec_memory_limit_bytes`) как верхнюю границу.
- **Unix socket:** `mysqld_exporter` поддерживает подключение через unix socket (`--config.addr=unix:///run/mysqld/mysqld.sock`). Это безопаснее TCP, но работает только на локальном хосте. Не используйте socket для мониторинга удаленных узлов.
- **Сетевое разделение (Split-Brain) в Galera:** при потере кворума метрики `wsrep_local_state` и `wsrep_cluster_size` становятся некорректными на отдельных узлах. Дополнительно мониторьте `wsrep_cluster_status` (ожидается `Primary`) и настраивайте отдельный health-check через MaxScale или Keepalived.
- **GTID и переключение мастера:** после failover в Source-Replica топологии метрика `mysql_slave_status_seconds_behind_master` может показывать `NULL` или отрицательные значения в течение нескольких секунд. Настройте алерт с `for: >= 5m` и дополнительную проверку `Slave_IO_Running` / `Slave_SQL_Running`.
- **Scrape timeout:** время сбора метрик (`scrape_timeout` в Prometheus) должно быть меньше `scrape_interval`. Для `mysqld_exporter` с полным набором коллекторов Recommended значение `scrape_timeout: 10s` при `scrape_interval: 15s`.
- **Ограничение соединений:** вmysqld_exporter v0.20.0+ используйте `SetMaxOpenConns(n)` (или `--config.max-connections`) для ограничения параллельных соединений к БД при высоком числе экземпляров экспортера на одном хосте.
- **Таймаут запросов:** используйте `SetQueryTimeout(duration)` вmysqld_exporter v0.20.0+ для предотвращения зависаний при тяжелых запросах (Recommended значение: `5s`).
- **Windows:** MariaDB на Windows не поддерживает Galera и имеет ограниченную поддержку Performance Schema. Некоторые метрики (Thread Pool, Aria) могут отсутствовать или иметь иные имена.

### Сценарий: "Кластер тормозит, загрузка CPU низкая"
1.  **Проверьте Flow Control:** Если он активен, ищите узел с максимальным `wsrep_local_recv_queue`.
2.  **Анализ узла-виновника:**
    *   Проверьте `wsrep_apply_window` (количество параллельно применяемых транзакций).
    *   Возможно, выполняется тяжелый `ALTER TABLE` без режима RSU.
3.  **Решение:** Используйте `pt-online-schema-change` вместо `ALTER TABLE` в Galera.

### Типовые ошибки mysqld_exporter
*   **`Access denied`**: У пользователя экспортера нет прав `PROCESS`, `REPLICATION CLIENT` и `SELECT` на `performance_schema` / `information_schema`.
    *   *Решение:* Убедитесь, что пользователь `monitor` имеет все необходимые гранты (см. сценарий 1).
*   **`Too many open files`**: При сборе метрик по каждой таблице (если их > 100k), экспортеру может не хватать файловых дескрипторов.
    *   *Решение:* Увеличьте лимит в systemd: `LimitNOFILE=65535` в секции `[Service]` (см. **[MariaDB под systemd](systemd.md#операции-и-команды-operations-and-commands)**).
*   **`context deadline exceeded`**: Prometheus не успевает собрать метрики за `scrape_interval`.
    *   *Решение:* Увеличьте `scrape_interval` до 30s или оптимизируйте количество коллекторов.

### Высокий `Threads_connected` при низком `Threads_running`
- **Причина:** Много соединений в состоянии Sleep (keep-alive в приложении, утечки соединений).
- **Диагностика:**
  ```sql
  SELECT command, COUNT(*) AS cnt
  FROM information_schema.processlist
  GROUP BY command;
  ```
- **Решение:** Уменьшите `wait_timeout` и `interactive_timeout`. Включите Thread Pool для управления соединениями.

### `Created_tmp_disk_tables` растет быстрее `Created_tmp_tables`
- **Причина:** Временные таблицы превышают `MIN(tmp_table_size, max_heap_table_size)` и сбрасываются на диск.
- **Диагностика:**
  ```sql
  SHOW VARIABLES LIKE 'tmp_table_size';
  SHOW VARIABLES LIKE 'max_heap_table_size';
  SHOW GLOBAL STATUS LIKE 'Created_tmp%';
  ```
- **Решение:** Увеличьте оба параметра до 64MB. Добавьте индексы для `ORDER BY` / `GROUP BY` запросов.

### Медленные запросы при нормальной утилизации CPU
- **Причина:** Lock contention, I/O wait, или неоптимизированные запросы.
- **Диагностика:**
  ```sql
  -- Проверка блокировок
  SELECT * FROM sys.innodb_lock_waits;

  -- Проверка I/O
  SELECT * FROM sys.io_global_by_file_by_bytes LIMIT 5;

  -- План выполнения тяжелого запроса
  EXPLAIN SELECT ...;
  ```
- **Решение:** Оптимизируйте индексы, разбейте длинные транзакции, используйте `OPTIMIZE TABLE` для фрагментированных таблиц.

---

## Дополнительная информация

### См. также
- **[Мониторинг безопасности MariaDB](security/security-monitoring.md)** — security-алерты: всплеск `Access denied`, отключение аудита, истечение TLS-сертификата.
- **[Отказоустойчивость MariaDB](high_availability.md)** — архитектура Galera, логика кворума и детальные алерты.
- **[Управление памятью MariaDB](memory_management.md)** — диагностика утечек и тюнинг буферов.
- **[Конфигурация MariaDB](configuration.md)** — настройка параметров Thread Pool и InnoDB.
