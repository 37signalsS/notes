# Мониторинг MySQL: Zabbix, Prometheus и PMM

**Актуально для:** MySQL 8.0.x / 8.4 LTS

## Определения

**Мониторинг MySQL** — процесс непрерывного сбора и анализа метрик производительности, состояния здоровья и безопасности сервера БД. В современных реализациях мониторинг перешел от простого опроса статусных переменных к глубокому анализу событий через **Performance Schema** и **InnoDB Metrics**.

**Zabbix Agent 2** — агент на Go с нативным плагином `MySQL`. Поддерживает постоянные соединения (**Connection Pooling**), параллельные проверки и механизм **Named Sessions**, что критично для высоконагруженных СУБД.

**mysqld_exporter** — специализированный сервис для сбора метрик MySQL в формате Prometheus. Работает по модели Pull, экспортируя данные о состоянии движка, репликации и схемах.

**PMM (Percona Monitoring and Management)** — комплексная платформа мониторинга с открытым исходным кодом, объединяющая Prometheus, Grafana и инструменты глубокого анализа запросов (QAN).

**Master / Dependent Items** — архитектурный подход в Zabbix (6.0+), при котором один "мастер-элемент" получает массив данных (JSON), а "зависимые элементы" извлекают метрики без повторных запросов к БД.

**LLD (Low Level Discovery)** — механизм автоматического обнаружения объектов: баз данных, табличных пространств, каналов репликации и пользовательских метрик.

## Базовые концепции

### Сравнение методов мониторинга

| Характеристика | Classic Agent (Legacy) | Zabbix Agent 2 (Standard) | Prometheus / PMM |
| :--- | :--- | :--- | :--- |
| **Механизм** | `UserParameter` + Shell | Native Go Plugin | Exporter (Scrape model) |
| **Соединения** | Новое на каждый запрос | **Connection Pool** | Persistent / Pool |
| **Формат данных** | Одиночные значения | **JSON (Master Item)** | Time-series / OpenTelemetry |
| **Диагностика** | Базовая | Хорошая (LLD) | **Отличная (QAN/Trace)** |
| **Репликация** | Скрипты (Master/Slave) | Нативная (Source/Replica) | Нативная (Full metrics) |

### Источники данных в MySQL

*   **Status Variables (`SHOW GLOBAL STATUS`):** Основной источник счетчиков (запросы, трафик, кэши).
*   **Performance Schema (P_S):** Инструментарий для анализа внутренних событий.
    *   `events_statements_summary_by_digest`: анализ групп SQL-запросов и их нагрузки.
    *   `table_io_waits_summary_by_index_usage`: выявление неиспользуемых индексов.
*   **Information Schema:** Метаданные о схемах, таблицах и правах.
*   **InnoDB Metrics:** Таблица `information_schema.innodb_metrics`. Содержит детальные счетчики движка InnoDB (адаптивные хэш-индексы, транзакции). Многие метрики требуют включения: `SET GLOBAL innodb_monitor_enable = 'module_name'`.
*   **Error Log:** Анализ критических ошибок (Corruption, CrashLoop).

### Современная терминология

Используется терминология **Source** (Источник) и **Replica** (Реплика).
*   Метрики источника: бинарные логи, GTID, активные потоки дампа.
*   Метрики реплики: `Seconds_Behind_Source`, статус потоков I/O и SQL.

### Архитектура мониторинга

Стандартный стек мониторинга MySQL состоит из трех уровней:

1. **Агент сбора (Collection):** `mysqld_exporter` или Zabbix Agent 2. Подключается к MySQL через нативный протокол, выполняет системные запросы к `performance_schema`, `information_schema` и `SHOW GLOBAL STATUS`. Работает на том же хосте, что и MySQL (localhost), что минимизирует сетевую задержку.

2. **Хранилище и обработка (Storage & Processing):**
   * **Prometheus:** Pull-модель. Периодически опрашивает экспортер, хранит временные ряды в локальной TSDB. Для долгосрочного хранения использует удаленные хранилища (VictoriaMetrics, Mimir, Thanos).
   * **Zabbix:** Push/Pull-модель. История хранится в SQL-БД (PostgreSQL/MySQL). Подходит для сред, где требуется классическая отчетность.

3. **Визуализация и алертинг (Visualization & Alerting):**
   * **Grafana:** Дашборды на основе методологий USE/RED/Golden Signals.
   * **Alertmanager (Prometheus):** Группировка, подавление, маршрутизация алертов.
   * **Zabbix Triggers + Actions:** Встроенная система оповещений.

> **Методология:** Для выбора метрик используйте **USE** (ресурсы СУБД) и **RED** (соединения, запросы, латентность). Подробнее: **[Методологии мониторинга](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)**.

## Практические сценарии

### Подготовка СУБД (Создание пользователя)

Для любого инструмента мониторинга требуется пользователь с ограниченными правами.

```sql
-- Создание пользователя (MySQL 8.x / 9.x / MariaDB)
CREATE USER 'monitor'@'localhost' IDENTIFIED BY 'your_secure_password' WITH MAX_USER_CONNECTIONS 3;

-- Базовые права и доступ к Performance Schema
GRANT REPLICATION CLIENT, PROCESS, SHOW DATABASES, SHOW VIEW ON *.* TO 'monitor'@'localhost';
GRANT SELECT ON performance_schema.* TO 'monitor'@'localhost';
GRANT SELECT ON sys.* TO 'monitor'@'localhost';

-- Для MariaDB 10.5+ (обязательно для мониторинга репликации)
GRANT SLAVE MONITOR ON *.* TO 'monitor'@'localhost';

FLUSH PRIVILEGES;
```

### Настройка Zabbix Agent 2

#### Конфигурация Named Sessions

В `/etc/zabbix/zabbix_agent2.d/plugins.d/mysql.conf`:
```ini
Plugins.Mysql.Sessions.ProdDB.Uri=tcp://localhost:3306
Plugins.Mysql.Sessions.ProdDB.User=monitor
Plugins.Mysql.Sessions.ProdDB.Password=your_secure_password
Plugins.Mysql.KeepAlive=300
```

#### Настройка в Zabbix Web

1. Прилинкуйте шаблон **MySQL by Zabbix agent 2**.
2. Установите макрос `{$MYSQL.DSN}` в `ProdDB`.

Подробнее о принципах мониторинга баз данных через Zabbix: **[Zabbix: Мониторинг баз данных](../../Zabbix/zabbix_database_monitoring.md)**.

### Настройка Prometheus (mysqld_exporter)

#### Конфигурация аутентификации

Создайте файл `/etc/mysqld_exporter/.my.cnf`:
```ini
[client]
user=monitor
password=your_secure_password
```

#### Запуск через Systemd

```bash
# /etc/systemd/system/mysqld_exporter.service
[Service]
ExecStart=/usr/local/bin/mysqld_exporter \
  --config.my-cnf=/etc/mysqld_exporter/.my.cnf \
  --collect.info_schema.innodb_metrics \
  --collect.perf_schema.tableiowaits
Restart=always
```

#### Проверка работоспособности

```bash
curl -s http://localhost:9104/metrics | grep -c "mysql_global_status"
# → > 100 (ожидается более 100 метрик)
```

### Настройка Classic Zabbix Agent (Legacy)

#### Конфигурация UserParameter

Файл `/etc/zabbix/zabbix_agentd.d/mysql.conf`:
```conf
UserParameter=mysql.ping,mysqladmin --defaults-extra-file=/var/lib/zabbix/.my.cnf ping | grep -c alive
UserParameter=mysql.status[*],mysql --defaults-extra-file=/var/lib/zabbix/.my.cnf -N -e "show global status where Variable_name='$1';" | awk '{print $2}'
UserParameter=mysql.innodb[*],mysql --defaults-extra-file=/var/lib/zabbix/.my.cnf -N -e "SELECT count FROM information_schema.innodb_metrics WHERE name='$1';"
```

#### Безопасная аутентификация (.my.cnf)

```bash
cat <<EOF > /var/lib/zabbix/.my.cnf
[client]
user=monitor
password=your_secure_password
EOF
chown zabbix:zabbix /var/lib/zabbix/.my.cnf
chmod 600 /var/lib/zabbix/.my.cnf
```

### Использование Percona PMM

1. **Установка клиента:** `curl -fsSL https://www.percona.com/get/pmm | bash`
2. **Регистрация:** `pmm-admin config --server-url=https://admin:admin@pmm.local`
3. **Добавление MySQL:** `pmm-admin add mysql --username=monitor --password=your_secure_password --query-source=perfschema`

### Проверка и отладка

```bash
# Проверка Agent 2
zabbix_get -s 127.0.0.1 -k mysql.ping[ProdDB]

# Проверка получения JSON (Master Item)
zabbix_get -s 127.0.0.1 -k mysql.get_status_variables[ProdDB]
```

## Ключевые метрики и алертинг

### Ключевые метрики для алертинга (SRE Guide)

*   **`Threads_connected`**: Рост сигнализирует об утечках в приложении или "зависании" запросов.
*   **`Max_used_connections`**: Лимит `max_connections` должен иметь запас 20-30%.
*   **`Innodb_buffer_pool_wait_free`**: Если > 0, Buffer Pool переполнен, запись тормозит (нужен тюнинг памяти).
*   **`Seconds_Behind_Source`** (на MySQL до 8.0.22 — `Seconds_Behind_Master`): основной алерт для репликации. Лаг > 60с требует вмешательства. Учитывайте, что значение ненадёжно при медленной сети и входит в `NULL`, когда поток SQL не работает.
*   **`Innodb_row_lock_time_avg`**: Рост среднего времени блокировки указывает на неоптимальные транзакции.
*   **`trx_rseg_history_len`** (счётчик `INNODB_METRICS`, подсистема `transaction`): длина истории транзакций — количество невытесненных записей undo log. Рост означает, что purge не догоняет запись, то есть на сервере есть длинная транзакция. Документация указывает, что значение обычно невелико («менее нескольких тысяч») и растёт при записи высокой интенсивности или при длинных транзакциях; числового порога в документации нет — выбирайте свой по baseline. Полный разбор в [Undo logs и purge](./undo_logs_and_purge.md).

### SHOW ENGINE INNODB STATUS в error log

Для непрерывной диагностики можно включить периодическую запись
состояния InnoDB в error log (вместо ручного `SHOW ENGINE INNODB STATUS`):

```sql
SET GLOBAL innodb_status_output = ON;         -- каждые ~15 секунд
SET GLOBAL innodb_status_output_locks = ON;   -- + информация о блокировках
```

`innodb_status_output_locks` существенно увеличивает объём записи —
включать только на время диагностики дедлоков и блокировок. Обе
переменные **не сохраняются** при перезапуске (не persistent) —
для постоянного мониторинга используйте экспорт метрик
(см. [Prometheus](#рекомендуемые-правила-алертинга-prometheus)).

### Рекомендуемые правила алертинга (Prometheus)

Создайте файл `mysql_alerts.yml`:

```yaml
groups:
  - name: mysql_alerts
    rules:
      # === Соединения ===
      - alert: MySQLTooManyConnections
        expr: mysql_global_status_threads_connected / mysql_global_variables_max_connections * 100 > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "MySQL: >80% соединений занято ({{ $value | humanize }}%)"

      - alert: MySQLConnectionStorm
        expr: rate(mysql_global_status_threads_created[5m]) > 10
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "MySQL: высокий rate создания потоков ({{ $value }}/s)"

      # === Buffer Pool ===
      - alert: MySQLBufferPoolHitRateLow
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
          summary: "MySQL: Buffer Pool Hit Rate < 99% ({{ $value | humanizePercentage }})"

      - alert: MySQLBufferPoolWaitFree
        expr: rate(mysql_global_status_innodb_buffer_pool_wait_free[5m]) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "MySQL: Buffer Pool wait_free > 0 (нехватка страниц)"

      # === Память ===
      - alert: MySQLSwapUsage
        expr: mysql_global_status_swap > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "MySQL: swap используется ({{ $value }} bytes)"

      # === Purge / undo ===
      # Счётчик берётся из INFORMATION_SCHEMA.INNODB_METRICS, а не из
      # SHOW GLOBAL STATUS. Имя метрики у mysqld_exporter зависит от того,
      # включён ли коллектор info_schema.innodb_metrics, поэтому проверьте
      # фактическое имя на своём инстансе:
      #   curl -s http://localhost:9104/metrics | grep -i rseg_history
      # Ориентир: документация называет нормальным значение «менее нескольких
      # тысяч»; порог ниже — сигнал искать длинную транзакцию, а не повод
      # немедленно увеличивать innodb_purge_threads.
      - alert: MySQLPurgeLagHigh
        expr: mysql_innodb_metrics_trx_rseg_history_len > 10000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "MySQL: длина истории транзакций > 10000 ({{ $value }}) — purge не догоняет, ищите длинную транзакцию"
          runbook: "SELECT trx_id, trx_started, trx_mysql_thread_id, trx_query FROM information_schema.INNODB_TRX ORDER BY trx_started;"

      - alert: MySQLPurgeNotProgressing
        expr: rate(mysql_innodb_metrics_purge_requests[15m]) == 0
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: "MySQL: purge не обрабатывает запросы — транзакция удерживает read view"
          runbook: "SHOW ENGINE INNODB STATUS — секция TRANSACTIONS, History list length"

      # === Репликация ===
      # ВНИМАНИЕ к именам метрик репликации у mysqld_exporter: они строятся из
      # имён колонок SHOW REPLICA STATUS, поэтому зависят от версии сервера.
      #   MySQL < 8.0.22 → Seconds_Behind_Master / Slave_IO_Running
      #   MySQL >= 8.0.22 → Seconds_Behind_Source / Replica_IO_Running
      # Коллектор slave_status у mysqld_exporter пробует SHOW ALL SLAVES STATUS,
      # затем SHOW SLAVE STATUS, затем SHOW REPLICA STATUS — на 8.4 работает
      # третья, и префикс метрик остаётся mysql_slave_status_*.
      # Проверьте фактические имена на своём инстансе:
      #   curl -s http://localhost:9104/metrics | grep -i behind
      - alert: MySQLReplicationLag
        expr: mysql_slave_status_seconds_behind_source > 60
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "MySQL: лаг репликации > 60с ({{ $value }}s)"

      - alert: MySQLReplicationStopped
        expr: mysql_slave_status_replica_io_running == 0 or mysql_slave_status_replica_sql_running == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "MySQL: репликация остановлена"

      # === Ошибки ===
      - alert: MySQLAbortedConnections
        expr: rate(mysql_global_status_aborted_connects[5m]) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "MySQL: высокий rate aborted connections ({{ $value }}/s)"

      - alert: MySQLAbortedClients
        expr: rate(mysql_global_status_aborted_clients[5m]) > 20
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "MySQL: высокий rate aborted clients ({{ $value }}/s)"

      - alert: MySQLSlowQueries
        expr: rate(mysql_global_status_slow_queries[5m]) > 1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "MySQL: > 1 slow query/сек ({{ $value }}/s)"
```

### Рекомендуемые панели Grafana

| Панель | Тип | Метрика | Описание |
| :--- | :--- | :--- | :--- |
| **Connections** | Time Series | `mysql_global_status_threads_connected` | Активные соединения |
| **QPS** | Rate | `rate(mysql_global_status_questions[5m])` | Запросов в секунду |
| **Buffer Pool Hit Rate** | Gauge | `(1 - reads/requests) * 100` | Эффективность кеша (цель > 99%) |
| **InnoDB Row Operations** | Time Series | `rate(mysql_global_status_innodb_row_ops_total[5m])` | Read/Insert/Update/Delete |
| **Replication Lag** | Time Series | `mysql_slave_status_seconds_behind_source` | Лаг реплики |
| **Slow Queries** | Rate | `rate(mysql_global_status_slow_queries[5m])` | Медленные запросы/сек |
| **Aborted Connections** | Rate | `rate(mysql_global_status_aborted_connects[5m])` | Ошибки подключения |

### Мониторинг Slow Queries (Медленные запросы)

#### Конфигурация MySQL

```ini
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow.log
long_query_time = 0.1 # 100 мс
log_slow_extra = ON  # MySQL 8.0.14+
```

*   **Микросекундная точность:** В современных версиях (MySQL 5.1+, MariaDB) `long_query_time` поддерживает дробные значения (например, `0.001` для 1 мс). В legacy-версиях поддерживались только целые секунды.

#### Анализ

*   **Zabbix:** отслеживает `Slow_queries` (счетчик).
*   **PMM:** инструмент **Query Analytics (QAN)** визуализирует планы выполнения и находит "самые тяжелые" запросы.

## Устранение неисправностей (Troubleshooting)

### Сценарий: "Высокий CPU при нормальной нагрузке"

1.  **Проверьте медленные запросы:**
    ```sql
    SHOW GLOBAL STATUS LIKE 'Slow_queries';
    SELECT * FROM sys.statement_analysis ORDER BY total_latency DESC LIMIT 10;
    ```
2.  **Проверьте планы выполнения:**
    ```sql
    EXPLAIN ANALYZE SELECT ...;
    ```
3.  **Решение:** добавить индекс, оптимизировать запрос, ограничить `max_execution_time`.

### Сценарий: "Высокая latency / таймауты"

1.  **Проверьте блокировки:**
    ```sql
    SELECT * FROM sys.innodb_lock_waits;
    ```
2.  **Проверьте Buffer Pool:**
    ```sql
    SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_wait_free';
    ```
3.  **Решение:** тюнинг `innodb_lock_wait_timeout`, уменьшение размера транзакций, разбиение на части.

### Сценарий: "Replication broken"

1.  **Диагностика:**
    ```sql
    SHOW REPLICA STATUS;
    SHOW ENGINE INNODB STATUS;
    ```
2.  **Решение:** `RESET REPLICA ALL`, переконфигурация, `SET GLOBAL sql_slave_skip_counter` при необходимости.

### Типовые ошибки mysqld_exporter

*   **`Access denied`**: У пользователя экспортера нет прав `PROCESS`, `REPLICATION CLIENT` и `SELECT` на `performance_schema` / `information_schema`.
    *   *Решение:* Убедитесь, что пользователь `monitor` имеет все необходимые гранты (см. сценарий 1).
*   **`Too many open files`**: При сборе метрик по каждой таблице (если их > 100k), экспортеру может не хватать файловых дескрипторов.
    *   *Решение:* Увеличьте лимит в systemd: `LimitNOFILE=65535` в секции `[Service]` файла сервиса.
*   **`context deadline exceeded`**: Prometheus не успевает собрать метрики за `scrape_interval`.
    *   *Решение:* Увеличьте `scrape_interval` до 30s или оптимизируйте количество коллекторов.

## Best Practices

1.  **Baseline before changing:** Record QPS, latency percentiles (p95, p99), connections, and Buffer Pool hit rate before any schema change, upgrade, or configuration modification.
2.  **Validate backups:** Follow the 3-2-1 backup rule (3 copies, 2 media types, 1 offsite) and test restores regularly. RTO/RPO must be validated in drills, not assumed.
3.  **Stage changes first:** Test schema changes, version upgrades, and parameter changes on a production-like replica before applying to primary.
4.  **Prefer rolling upgrades:** For replication topologies, upgrade replicas before the source. This minimizes downtime and provides instant rollback.
5.  **SLO-based alerting:** Alert on error budget burn and baseline deviation, not just static thresholds. This reduces noise and catches gradual degradation early.
6.  **Least privilege:** Grant minimum required privileges. Separate application accounts from admin accounts. Audit grants and rotate passwords on a schedule.
7.  **Document topology and runbooks:** Keep replication topology diagrams, failover procedures, and escalation paths current. Runbooks must cover crash recovery and replica re-initialization.
8.  **Maintenance windows:** Schedule writes-heavy operations (`OPTIMIZE TABLE`, index rebuild, major upgrades) during low-traffic periods.

## Мета-мониторинг

Мониторьте саму систему сбора метрик MySQL. Ключевые точки:

*   **Доступность экспортера:** `up{job="mysql"} == 0` — алерт на недоступность `mysqld_exporter`.
*   **Время сбора (Scrape Duration):** `histogram_quantile(0.99, rate(mysqld_exporter_scrape_duration_seconds_bucket[5m]))` — если P99 > `scrape_timeout`, увеличьте интервал или оптимизируйте коллекторы.
*   **Ошибки сбора:** `rate(mysqld_exporter_scrape_errors_total[5m]) > 0` — ошибки подключения или таймауты.
*   **Количество метрик:** `count(mysql_global_status_*)` — резкое падение количества метрик может указывать на проблему с правами пользователя или изменением схемы.

## Дополнительная информация

### Методологии наблюдения

*   **USE Method:** Для ресурсов СУБД (CPU, RAM, Disk, Buffer Pool).
*   **RED Method:** Для взаимодействий (Connections, Queries, Latency).
*   **Golden Signals:** Для критических сервисов (Latency, Traffic, Errors, Saturation).

Подробнее: **[Методологии мониторинга](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)**.

### Рекомендации по алертингу

*   **Actionability:** Каждый алерт должен иметь `runbook_url`.
*   **Действенность:** Алерты на симптомы (рост 5xx, Latency), а не на причины (CPU, RAM).
*   **Иерархия критичности:** Critical (звонок), Warning (Slack/Ticket), Info (лог).

Подробнее: **[Рекомендации по мониторингу и алертингу](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md)**.

### См. также

*   **[Обзор MySQL и форков](./overview.md)** — архитектура InnoDB и Redo/Undo Log.
*   **[Zabbix: Мониторинг баз данных](../../Zabbix/zabbix_database_monitoring.md)** — общие принципы Zabbix.
*   **[Prometheus: mysqld_exporter](https://github.com/prometheus/mysqld_exporter)** — официальная документация.
*   **[Конфигурация параметров my.cnf](./configuration.md)** — детали настройки Performance Schema.
*   **[Мониторинг MariaDB](../MariaDB/monitoring.md)** — специфичные для MariaDB метрики (Galera, Thread Pool).
*   **[Методологии мониторинга](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)** — USE, RED, Golden Signals.
*   **[Рекомендации по алертингу](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md)** — SRE-подход к алертингу.
