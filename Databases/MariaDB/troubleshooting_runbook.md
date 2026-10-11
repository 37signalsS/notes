# Единый runbook устранения неполадок MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **Runbook** — пошаговая процедура диагностики и устранения типовых инцидентов. Цель — быстрое восстановление сервиса (снижение MTTR) и единообразие действий SRE.
*   **MTTR (Mean Time To Repair)** — среднее время восстановления. Runbook снижает MTTR за счёт заранее проверенных шагов.
*   **Симптом → Причина → Диагностика → Решение** — структура каждого пункта runbook.
*   **`mariadb-admin ping`** — быстрая проверка доступности сервера (`mysqld is alive`). Нюанс: exit code `0` возвращается даже при `Access denied` — сервер считается живым. Для health-проверки используйте `mariadb-admin status` или SQL-запрос.
*   **`mariadb-admin status`** — однострочный статус: `Uptime`, `Threads`, `Questions`, `Slow queries`, `Opens`, `Flush tables`, `Open tables`, `Queries per second avg`.
*   **`SHOW ENGINE INNODB STATUS`** — текстовый отчёт InnoDB: транзакции, deadlocks, buffer pool, foreign key errors.
*   **`KILL QUERY`** — прервать оператор, который выполняет соединение, не разрывая само соединение (в отличие от `KILL` / `KILL CONNECTION`, которые закрывают соединение). Есть также `KILL QUERY ID <query_id>` и `KILL USER <user>`.
*   **`SET GLOBAL`** — изменение системной переменной в рантайме. **Не персистентно**: после рестарта значение вернётся к значению из `my.cnf`. В MariaDB нет `SET PERSIST` (это синтаксис MySQL) — постоянное изменение требует правки опционного файла.

## Базовые концепции

### Методология диагностики (сверху вниз)

```
1. Доступен ли сервер?        → mariadb-admin ping, systemctl status
2. Принимает ли соединения?   → mariadb -u root -p, SHOW PROCESSLIST
3. Что происходит?            → SHOW GLOBAL STATUS, PROCESSLIST, INNODB STATUS
4. Где узкое место?           → CPU / RAM / Disk I/O / Network
5. Что изменилось?            → логи, недавние деплои, конфигурация
```

### Ключевые команды диагностики

```bash
# Сервер запущен?
systemctl status mariadb
mariadb-admin -u root -p ping      # → mysqld is alive
mariadb-admin -u root -p status    # → Uptime/Threads/Questions/Slow queries...

# Логи (все / только ошибки / ядро)
journalctl -u mariadb -b --since "1 hour ago"
journalctl -u mariadb -b -p err
journalctl -k -b | grep -i -e oom -e mariadb

# Ресурсы (включая иноды — дефицит inode выглядит как «нет места»)
top -p $(pgrep mariadbd)
df -h /var/lib/mysql /tmp
df -i /var/lib/mysql
free -h
iostat -x 1 5
```

```sql
-- Соединения
SHOW GLOBAL STATUS LIKE 'Threads_%';
SHOW PROCESSLIST;

-- Ошибки
SHOW GLOBAL STATUS LIKE 'Aborted_%';
SHOW ENGINE INNODB STATUS\G

-- Репликация
SHOW REPLICA STATUS\G

-- Galera
SHOW STATUS LIKE 'wsrep_%';
```

## Практические сценарии (runbook)

### Инцидент 1: MariaDB не отвечает / не запускается

**Симптом:** приложение не может подключиться; `mariadb-admin ping` не отвечает.

**Шаги:**

```bash
# 1. Статус сервиса
systemctl status mariadb

# 2. Логи (служба + ядро, только ошибки)
journalctl -u mariadb -b | tail -100
journalctl -u mariadb -b -p err
journalctl -k -b | grep -i -e oom -e mariadb

# 3. Процесс
pgrep mariadbd
ps aux | grep mariadbd

# 4. Порт
ss -tlnp | grep 3306

# 5. Место на диске и иноды
df -h /var/lib/mysql
df -i /var/lib/mysql
```

**Типичные причины и решения:**

| Причина | Диагностика | Решение |
| :--- | :--- | :--- |
| Сервис остановлен | `systemctl status` — inactive | `systemctl start mariadb` |
| Ошибка в `my.cnf` | логи — `unknown variable` | исправить `my.cnf`, `systemctl restart` |
| Нет места на диске | `df -h` — 100% | очистить логи/binlog (`PURGE BINARY LOGS`) |
| OOM killer | `journalctl -k -b \| grep -i oom` (`dmesg` может быть недоступен без прав) | увеличить RAM/swap, снизить `innodb_buffer_pool_size` |
| Закончились иноды | `df -i` — 100% при свободном `df -h` | найти мелкие файлы, очистить |
| Повреждение таблицы / краш | логи — `InnoDB: Database page corruption` | сначала `innodb_force_recovery=1..6` в `my.cnf` для экспорта (см. **[Обслуживание](maintenance.md)**), иначе восстановление из бэкапа (см. **[Резервное копирование](backup_and_recovery.md)**) |

#### Клиентские ошибки 2002 / 2003: не подключиться

```text
ERROR 2002 (HY000): Can't connect to local MySQL server through socket '/var/run/mysqld/mysqld.sock' (2 "No such file or directory")
ERROR 2003 (HY000): Can't connect to MySQL server on 'localhost' (111 "Connection refused")
```

| Ошибка | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| 2002 — нет socket-файла | сервер не запущен; путь socket различается в конфигах сервера и клиента; cron чистит `/tmp` | `SHOW VARIABLES LIKE 'socket';` (на сервере), `netstat -ln \| grep mysqld` | запустить сервер; привести `socket` к одному значению в `[server]` и `[client]`; подключаться `--socket=/путь` |
| 2003 — Connection refused | неверный host/port; firewall; `bind-address=127.0.0.1` (только loopback); `skip-networking` | `ss -tlnp \| grep 3306`; `telnet <host> 3306`; `SHOW VARIABLES LIKE 'bind_address';`, `SHOW VARIABLES LIKE 'skip_networking';` | исправить host/port; открыть порт; снять `skip-networking`; расширить `bind-address` |
| 2002/2003 — при `Access denied` | сетевой путь жив, проблема в учётных данных | `mariadb-admin -h <host> -P 3306 -u root -p ping` | см. **[RBAC и привилегии](security/rbac.md)** |

> **Нюанс мониторинга:** `mariadb-admin ping` возвращает exit code `0` даже при `Access denied` — сервер «жив», но учётные данные неверны. Для health-check используйте `mariadb-admin status` или SQL-запрос от диагностического пользователя.

### Инцидент 2: Too many connections (1040)

**Симптом:** ошибка `ERROR 1040 (08004): Too many connections`.

**Шаги:**

```sql
-- Текущее состояние
SHOW GLOBAL STATUS LIKE 'Threads_connected';
SHOW GLOBAL STATUS LIKE 'Connection_errors%';   -- Connection_errors_max_connections и др.
SHOW VARIABLES LIKE 'max_connections';

-- Кто держит соединения
SELECT USER, HOST, COMMAND, COUNT(*) AS cnt
FROM information_schema.PROCESSLIST
GROUP BY USER, HOST, COMMAND
ORDER BY cnt DESC;

-- Idle-соединения (утечки)
SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE COMMAND = 'Sleep';

-- Отказы по хостам (host cache; требует performance_schema=ON)
SELECT IP, HOST, SUM_CONNECT_ERRORS FROM performance_schema.host_cache
ORDER BY SUM_CONNECT_ERRORS DESC;
```

**Решение:**
1.  Увеличить `max_connections` (`SET GLOBAL max_connections = 500;`). **Важно:** `SET GLOBAL` не персистентен — после рестарта значение вернётся к значению из `my.cnf`; в MariaDB нет `SET PERSIST`, поэтому изменение нужно продублировать в опционном файле. Память: каждое соединение потребляет per-thread буферы (`sort_buffer_size` + `join_buffer_size` + …) — расчёт в **[Управление соединениями](connection_management.md)**.
2.  Thread Pool для тысяч соединений: встроенный в MariaDB (не плагин), включается параметрами запуска `thread_handling=pool-of-threads` и `thread_pool_size` (≈ число CPU; startup-переменная). Настройка — в **[Управление соединениями](connection_management.md)**.
3.  Сократить `wait_timeout` для закрытия idle.
4.  Настроить connection pooling (ProxySQL/MaxScale).
5.  Если в логах `Host '...' is blocked because of many connection errors` — сработал host cache: `max_connect_errors` (default `100`) последовательных ошибок блокирует хост. Разблокировать: `FLUSH HOSTS;` или `mariadb-admin flush-hosts`. Причину смотреть в `performance_schema.host_cache` (`SUM_CONNECT_ERRORS`) и в `Aborted_connects`.
6.  Найти и исправить утечки в приложении.

Подробнее: **[Управление соединениями](connection_management.md)**.

### Инцидент 3: Медленные запросы / деградация производительности

**Симптом:** приложение тормозит, высокий latency.

**Шаги:**

```sql
-- Долгие запросы прямо сейчас
SELECT ID, USER, HOST, DB, COMMAND, TIME, STATE, INFO
FROM information_schema.PROCESSLIST
WHERE COMMAND != 'Sleep' AND TIME > 5
ORDER BY TIME DESC;

-- Топ запросов по времени (Performance Schema)
SELECT DIGEST_TEXT, COUNT_STAR, SUM_TIMER_WAIT/1e12 AS total_sec
FROM performance_schema.events_statements_summary_by_digest
ORDER BY SUM_TIMER_WAIT DESC LIMIT 10;

-- Блокировки
SELECT * FROM sys.innodb_lock_waits;

-- Buffer pool hit rate
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read%';

-- Медленные запросы с момента старта сервера
SHOW GLOBAL STATUS LIKE 'Slow_queries';
```

> **Предварительное требование:** `performance_schema=ON` в `my.cnf` — в MariaDB Performance Schema **выключена по умолчанию** (в отличие от MySQL 8.0+), переменная не динамическая (требуется рестарт). Без неё `events_statements_summary_by_digest`, `sys.*` и `host_cache` пусты.

**Решение:**
1.  `EXPLAIN` / `ANALYZE` на медленных запросах (см. **[Оптимизация запросов](query_optimization.md)**).
2.  Проверить индексы (`sys.schema_unused_indexes`).
3.  Проверить buffer pool hit rate (цель > 99%).
4.  Проверить I/O (`iostat -x 1`).
5.  Проверить slow query log + `pt-query-digest` (`slow_query_log=ON`, `long_query_time` — default `10`).
6.  Runaway-запрос: `KILL QUERY <id>` — прервать оператор, сохранив соединение; `KILL <id>` — разорвать соединение целиком. Быстрая сводка: `mariadb-admin status` и `mariadb-admin processlist`.

### Инцидент 4: Deadlock (1213) / Lock wait timeout (1205)

**Симптом:** ошибка `ERROR 1213 (40001): Deadlock found` или `ERROR 1205 (HY000): Lock wait timeout exceeded`.

**Шаги:**

```sql
-- Последний deadlock
SHOW ENGINE INNODB STATUS\G
-- Секция "LATEST DETECTED DEADLOCK"

-- Текущие ожидания
SELECT * FROM sys.innodb_lock_waits;

-- Активные транзакции
SELECT * FROM information_schema.INNODB_TRX;
```

**Решение:**
1.  **Deadlock (1213):** приложение должно повторить транзакцию (retry). Сократите транзакции, упорядочьте доступ к строкам. Чтобы не терять историю взаимоблокировок — `innodb_print_all_deadlocks=ON` и `innodb_deadlock_report` (см. **[Транзакции и блокировки](transactions_and_locking.md)**).
2.  **Lock wait (1205):** найдите блокирующую транзакцию (`sys.innodb_lock_waits`), сократите её или `KILL` при необходимости. Увеличьте `innodb_lock_wait_timeout` при необходимости.
3.  Привилегии: `PROCESS` — видеть чужие сессии в `SHOW PROCESSLIST`; `SUPER` или `CONNECTION_ADMIN` (с 10.5.2) — `KILL` чужих соединений и операторов. `KILL QUERY <id>` прерывает только текущий оператор, не разрывая соединение.

Подробнее: **[Транзакции и блокировки](transactions_and_locking.md)**.

### Инцидент 5: Репликация остановлена

**Симптом:** `Replica_IO_Running: No` или `Replica_SQL_Running: No`.

**Шаги:**

```sql
SHOW REPLICA STATUS\G
-- Last_IO_Error, Last_SQL_Error
-- Replica_IO_Running, Replica_SQL_Running
-- Seconds_Behind_Source
```

**Типичные причины:**

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Last_IO_Error: Can't connect` | сеть, firewall, неверный host/порт | проверить сеть, `CHANGE REPLICATION SOURCE TO` |
| `Last_SQL_Error: Duplicate entry` (1062) | конфликт данных | **предпочтительно GTID-пропуск** (`SET GTID_NEXT`, см. **[Репликация: troubleshooting](replication/troubleshooting.md)**); `sql_slave_skip_counter` deprecated и не работает с GTID. Только без GTID: `STOP REPLICA;` → `SET GLOBAL sql_slave_skip_counter = 1;` → `START REPLICA;` (осторожно!) |
| `Last_SQL_Error: Unknown column` (1054) | рассинхронизация схемы | применить DDL на реплике |
| `Could not find first log file` (1236) | binlog удалён | `CHANGE REPLICATION SOURCE TO SOURCE_USE_GTID=slave_pos`; на 10.10+ GTID включён по умолчанию (MDEV-19801). Для превращения бывшего primary в реплику — `SOURCE_DEMOTE_TO_SLAVE=1` (`SOURCE_USE_GTID=current_pos` deprecated с 10.10, MDEV-20122) |

Подробнее: **[Репликация: troubleshooting](replication/troubleshooting.md)**.

### Инцидент 6: Galera Cluster — узел Non-Primary

**Симптом:** `wsrep_cluster_status: Non-Primary`, записи отклоняются.

**Шаги:**

```sql
SHOW STATUS LIKE 'wsrep_cluster_status';
SHOW STATUS LIKE 'wsrep_cluster_size';
SHOW STATUS LIKE 'wsrep_local_state_comment';
```

**Решение:**
1.  Проверьте сетевую связность между узлами (порты 4567/4568/4444).
2.  Если узел точно имеет актуальные данные — `SET GLOBAL wsrep_provider_options='pc.bootstrap=YES';` (**только на одном узле!**).
3.  Проверьте `wsrep_flow_control_paused` — Flow Control: значение > 0 означает, что узел приостанавливал обработку транзакций; устойчиво высокое значение — узел не поспевает за записью.

Подробнее: **[Отказоустойчивость](high_availability.md)**.

### Инцидент 7: Диск заполнен

**Симптом:** `ERROR 1114 (HY000): The table is full` или ошибки записи.

**Шаги:**

```bash
df -h /var/lib/mysql /tmp
df -i /var/lib/mysql                        # иноды: «нет места» при свободных GB
du -sh /var/lib/mysql/* /var/log/mysql/*
```

```sql
-- Какие binlog занимают место
SHOW BINARY LOGS;
```

**Решение:**
1.  **Binlog:** `PURGE BINARY LOGS BEFORE '...';` или `SET GLOBAL binlog_expire_logs_seconds = 604800;` (перед `PURGE` убедитесь, что реплики прочитали файлы — `SHOW REPLICA STATUS`).
2.  **Логи:** ротация logrotate (см. **[Управление логами](log_management.md)**).
3.  **Relay log:** `FLUSH RELAY LOGS;` на реплике.
4.  **Временные файлы:** очистить `tmpdir`.
5.  **Другие причины `ERROR 1114 (The table is full)`:** переполнение `tmp_table_size`/`max_heap_table_size` (MEMORY-таблицы и внутренние временные таблицы) или полный tablespace InnoDB — проверяйте размер файлов данных, а не только свободное место на диске.

### Инцидент 8: Высокое потребление RAM / swap

**Симптом:** `free -h` — swap используется; OOM.

**Шаги:**

```bash
free -h
ps aux --sort=-%mem | head -5
cat /proc/$(pgrep mariadbd)/status | grep -i vm
```

```sql
-- Распределение памяти
SELECT * FROM sys.memory_global_by_current_bytes ORDER BY current_alloc DESC LIMIT 10;
```

**Решение:**
1.  Проверьте `innodb_buffer_pool_size` (50-75% RAM).
2.  Проверьте per-thread буферы × `max_connections`.
3.  Проверьте утечки (RSS растёт при низкой нагрузке).
4.  Отключите swap или настройте `memlock`.

Подробнее: **[Управление памятью](memory_management.md)**.

## Устранение неполадок (Troubleshooting)

### Сбор информации для эскалации

При эскалации в vendor support соберите:

```bash
# Версия
mariadb --version

# Конфигурация (серверная, не клиентская)
mariadbd --print-defaults

# Статус
mariadb-admin status
SHOW GLOBAL STATUS LIKE 'Uptime';
SHOW GLOBAL STATUS;
SHOW GLOBAL VARIABLES;

# InnoDB
SHOW ENGINE INNODB STATUS\G

# Логи
journalctl -u mariadb --since "24 hours ago"

# Процесс и ресурсы
ps aux | grep mariadbd
cat /proc/$(pgrep mariadbd)/limits
df -h /var/lib/mysql; df -i /var/lib/mysql
```

## Лучшие практики (Best Practices)

1.  **Сверху вниз:** сначала доступность, потом производительность, потом причина.
2.  **Не меняйте конфигурацию вслепую:** сначала диагностика (`EXPLAIN`, `PROCESSLIST`, `INNODB STATUS`).
3.  **`SET GLOBAL` не персистентен:** любое runtime-изменение после рестарта вернётся к значению из `my.cnf`; в MariaDB нет `SET PERSIST` — дублируйте изменение в опционном файле.
4.  **Документируйте инциденты:** что произошло, что помогло — пополняйте runbook.
5.  **Автоматизируйте:** алерты Prometheus на `Threads_connected`, `Aborted_*`, `wsrep_*`, replication lag — готовые PromQL-правила в **[Мониторинг MariaDB](monitoring.md)**.
6.  **Проверьте привилегии диагноста:** `PROCESS` — чужие сессии, `SUPER`/`CONNECTION_ADMIN` — `KILL`, `RELOAD` — `FLUSH`.
7.  **Тестируйте runbook** в staging — шаги должны быть воспроизводимы.

## Дополнительная информация

### См. также

*   **[Коды ошибок](error_codes.md)** — справочник кодов.
*   **[Управление соединениями](connection_management.md)** — Too many connections, Thread Pool.
*   **[Оптимизация запросов](query_optimization.md)** — медленные запросы.
*   **[Транзакции и блокировки](transactions_and_locking.md)** — deadlocks, lock waits, idle-таймауты.
*   **[Репликация: troubleshooting](replication/troubleshooting.md)** — репликация.
*   **[Отказоустойчивость](high_availability.md)** — Galera.
*   **[Мониторинг](monitoring.md)** — алерты и метрики.
*   **[Обслуживание](maintenance.md)** — `innodb_force_recovery`, проверка таблиц.
*   **[MySQL: Troubleshooting Runbook](../MySQL/troubleshooting-runbook.md)** — MySQL-специфичный runbook.

### Внешние ресурсы

*   [Debugging & Troubleshooting (hub)](https://mariadb.com/docs/server/reference/product-development/mariadb-fault-finding/) — трассировки, core dumps, дебаггер.
*   [Checking MariaDB (Troubleshooting Overview)](https://mariadb.com/docs/server/reference/product-development/mariadb-fault-finding/checking-mariadb/) — диагностика для DBAs и разработчиков.
*   [MariaDB Crashes](https://mariadb.com/docs/server/reference/product-development/mariadb-fault-finding/mariadb-crashes/) — анализ крашей.
*   [Troubleshooting Connection Issues](https://mariadb.com/docs/server/mariadb-quickstart-guides/mariadb-connection-troubleshooting-guide) — ошибки 2002/2003, socket, `bind-address`.
